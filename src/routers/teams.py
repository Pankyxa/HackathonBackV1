import uuid

from fastapi import Header
from fastapi.responses import StreamingResponse, Response
import hashlib
import aiofiles
import asyncio
from datetime import datetime

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    File,
    UploadFile,
    Form,
    Query,
)
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, exists, func, and_, update
from typing import List, Optional
import json
from io import BytesIO
from uuid import UUID
import os
import glob

from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy.orm import joinedload, selectinload

from src.db import get_session
from src.models import User, Team, TeamMember, Role, UserStatusHistory, Stage
from src.models.event import Event
from src.models.evaluation import TeamEvaluation
from src.models.file import File as DBFile
from src.models.enums import (
    TeamMemberStatus,
    TeamRole,
    FileType,
    FileOwnerType,
    StageType,
)
from src.models.user import User2Roles
from src.schemas.team import (
    TeamCreate,
    TeamResponse,
    TeamMemberResponse,
    TeamMemberCreate,
    TeamInvitationResponse,
    TeamMembersResponse,
    TeamMemberDetailResponse,
    TeamStatusDetails,
    PaginatedTeamsResponse,
)
from src.auth.jwt import get_current_user

from src.settings import settings
from fastapi import BackgroundTasks
from src.utils.background_tasks import (
    send_team_invitation_email,
    send_hackathon_consultation_notification,
    send_team_confirmation_email_background,
    send_judge_briefing_notification,
    send_single_judge_briefing_notification,
    send_task_update_notification,
    send_hackathon_opening_notification,
    send_judge_opening_notification,
    send_defense_schedule_notification,
    send_closing_ceremony_notification,
    send_first_stage_results_notification,
    send_kickoff_meeting_notification,
    send_kickoff_meeting_notification_to_extra_recipients,
    send_finalists_kickoff_meeting_notification,
    send_finalists_stage2_consultation_notification,
)
from src.utils.email_utils import email_sender
from src.utils.file_utils import save_file
from src.utils.router_states import (
    team_router_state,
    user_router_state,
    stage_router_state,
    file_router_state,
)
from src.utils.stage_checker import check_stage
from src.utils.event_utils import get_active_event
from src.utils.user_status_utils import update_team_members_statuses_for_event
from src.utils.vuz_utils import unique_vuz_list
from src.utils.finalists_utils import is_effective_finalist, get_effective_finalist_ids

router = APIRouter(prefix="/teams", tags=["teams"])


def get_role_id(role: TeamRole) -> UUID:
    if role == TeamRole.TEAMLEAD:
        return team_router_state.teamlead_role_id
    elif role == TeamRole.MENTOR:
        return team_router_state.mentor_role_id
    return team_router_state.member_role_id


def get_status_id(status: TeamMemberStatus) -> UUID:
    if status == TeamMemberStatus.PENDING:
        return team_router_state.pending_status_id
    elif status == TeamMemberStatus.ACCEPTED:
        return team_router_state.accepted_status_id
    return team_router_state.rejected_status_id


@router.post("/create", response_model=TeamResponse)
async def create_team(
    team_name: str = Form(...),
    team_motto: str = Form(...),
    member_ids: str = Form(default="[]"),
    logo: UploadFile = UploadFile(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await check_stage(session, StageType.REGISTRATION)
    active_event = await get_active_event(session)

    """Создание команды с указанием участников по их ID"""
    try:
        member_ids_list = [UUID(id_str) for id_str in json.loads(member_ids)]
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный формат member_ids"
        )

    if member_ids_list:
        users_query = select(User).where(User.id.in_(member_ids_list))
        result = await session.execute(users_query)
        found_users = result.scalars().all()

        if len(found_users) != len(member_ids_list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Некоторые пользователи не найдены",
            )

    # Проверяем, не является ли пользователь тимлидом в активном событии
    existing_teamlead_query = (
        select(TeamMember)
        .join(Team, TeamMember.team_id == Team.id)
        .where(
            TeamMember.user_id == current_user.id,
            TeamMember.role_id == team_router_state.teamlead_role_id,
            TeamMember.status_id == team_router_state.accepted_status_id,
            Team.event_id == active_event.id,
        )
    )
    existing_teamlead = await session.execute(existing_teamlead_query)
    if existing_teamlead.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пользователь уже является тимлидом другой команды в текущем событии",
        )

    # Отклоняем pending приглашения в активном событии
    pending_invitations_query = (
        select(TeamMember)
        .join(Team, TeamMember.team_id == Team.id)
        .where(
            TeamMember.user_id == current_user.id,
            TeamMember.status_id == team_router_state.pending_status_id,
            Team.event_id == active_event.id,
        )
    )
    pending_invitations = await session.execute(pending_invitations_query)
    for invitation in pending_invitations.scalars():
        invitation.status_id = team_router_state.rejected_status_id
    await session.flush()

    team = Team(
        id=uuid.uuid4(),
        team_name=team_name,
        team_motto=team_motto,
        team_leader_id=current_user.id,
        logo_file_id=None,
        event_id=active_event.id,
    )
    session.add(team)
    await session.flush()

    logo_file = await save_file(
        upload_file=logo,
        owner_id=team.id,
        file_type=FileType.TEAM_LOGO,
        owner_type=FileOwnerType.TEAM,
    )
    session.add(logo_file)
    await session.flush()

    team.logo_file_id = logo_file.id
    await session.flush()

    team_leader_member = TeamMember(
        id=uuid.uuid4(),
        team_id=team.id,
        user_id=current_user.id,
        role_id=team_router_state.teamlead_role_id,
        status_id=team_router_state.accepted_status_id,
    )
    session.add(team_leader_member)

    if member_ids_list:
        team_members = []
        for user_id in member_ids_list:
            if user_id != current_user.id:
                existing_member_query = select(TeamMember).where(
                    TeamMember.user_id == user_id,
                    TeamMember.status_id == team_router_state.accepted_status_id,
                )
                existing_member = await session.execute(existing_member_query)
                if not existing_member.scalar_one_or_none():
                    team_member = TeamMember(
                        id=uuid.uuid4(),
                        team_id=team.id,
                        user_id=user_id,
                        role_id=team_router_state.member_role_id,
                        status_id=team_router_state.pending_status_id,
                    )
                    team_members.append(team_member)

        if team_members:
            session.add_all(team_members)

        invited_users_query = (
            select(User)
            .where(User.id.in_(member_ids_list))
            .where(User.id != current_user.id)
        )
        result = await session.execute(invited_users_query)
        invited_users = result.scalars().all()

        for invited_user in invited_users:
            background_tasks.add_task(
                send_team_invitation_email, user=invited_user, team=team
            )

    await session.commit()

    team_query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members).selectinload(TeamMember.role),
            selectinload(Team.members).selectinload(TeamMember.status),
        )
        .where(Team.id == team.id)
    )
    result = await session.execute(team_query)
    team_with_relations = result.scalar_one()

    return TeamResponse.from_orm_team(team_with_relations)


@router.post("/{team_id}/mentor", response_model=TeamMemberResponse)
async def invite_team_mentor(
    team_id: uuid.UUID,
    mentor_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Пригласить ментора в команду"""
    await check_stage(session, StageType.REGISTRATION)
    active_event = await get_active_event(session)

    team_query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members).selectinload(TeamMember.role),
            selectinload(Team.members).selectinload(TeamMember.status),
        )
        .where(Team.id == team_id, Team.event_id == active_event.id)
    )
    team = await session.execute(team_query)
    team = team.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена или не принадлежит активному событию",
        )

    if team.team_leader_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только лидер команды может приглашать ментора",
        )

    mentor_query = (
        select(User)
        .options(selectinload(User.user2roles).selectinload(User2Roles.role))
        .where(User.id == mentor_id)
    )
    mentor = await session.execute(mentor_query)
    mentor = mentor.scalar_one_or_none()

    if not mentor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден"
        )

    is_mentor = any(
        user2role.role_id == user_router_state.mentor_role_id
        for user2role in mentor.user2roles
    )
    if not is_mentor:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пользователь не является ментором",
        )

    existing_mentor_query = select(TeamMember).where(
        TeamMember.team_id == team_id,
        TeamMember.role_id == team_router_state.mentor_role_id,
        TeamMember.status_id == team_router_state.accepted_status_id,
    )
    existing_mentor = await session.execute(existing_mentor_query)
    if existing_mentor.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="В команде уже есть ментор"
        )

    existing_invitation_query = select(TeamMember).where(
        TeamMember.team_id == team_id, TeamMember.user_id == mentor_id
    )
    existing_invitation = await session.execute(existing_invitation_query)
    existing_invitation = existing_invitation.scalar_one_or_none()

    if existing_invitation:
        if existing_invitation.status_id == team_router_state.pending_status_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Приглашение уже отправлено",
            )
        elif existing_invitation.status_id == team_router_state.accepted_status_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ментор уже является участником команды",
            )

    team_member = TeamMember(
        id=uuid.uuid4(),
        team_id=team_id,
        user_id=mentor_id,
        role_id=team_router_state.mentor_role_id,
        status_id=team_router_state.pending_status_id,
    )
    session.add(team_member)
    await session.commit()
    await session.refresh(team_member)

    background_tasks.add_task(send_team_invitation_email, mentor, team)

    return team_member


@router.post("/{team_id}/members", response_model=TeamMemberResponse)
async def invite_team_member(
    team_id: uuid.UUID,
    member_data: TeamMemberCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Пригласить пользователя в команду"""
    await check_stage(session, StageType.REGISTRATION)

    # Получаем активное событие для проверки
    active_event = await get_active_event(session)

    team_query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members).selectinload(TeamMember.role),
            selectinload(Team.members).selectinload(TeamMember.status),
        )
        .where(Team.id == team_id)
    )
    team = await session.execute(team_query)
    team = team.scalar_one_or_none()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Команда не найдена"
        )

    # Проверяем, что команда принадлежит активному событию
    if team.event_id != active_event.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Команда не принадлежит активному событию",
        )

    if team.team_leader_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только лидер команды может приглашать участников",
        )

    user_query = (
        select(User)
        .options(selectinload(User.current_status))
        .where(User.id == member_data.user_id)
    )
    user = await session.execute(user_query)
    user = user.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден"
        )

    member_query = select(TeamMember).where(
        TeamMember.team_id == team_id, TeamMember.user_id == member_data.user_id
    )
    existing_member = await session.execute(member_query)
    existing_member = existing_member.scalar_one_or_none()

    if existing_member:
        if existing_member.status_id == team_router_state.pending_status_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Приглашение уже отправлено",
            )
        elif existing_member.status_id == team_router_state.accepted_status_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Пользователь уже является участником команды",
            )
        elif existing_member.status_id == team_router_state.rejected_status_id:
            existing_member.status_id = team_router_state.pending_status_id
            existing_member.role_id = get_role_id(member_data.role)
            await session.commit()
            await session.refresh(existing_member)

            background_tasks.add_task(send_team_invitation_email, user, team)

            return existing_member

    team_member = TeamMember(
        id=uuid.uuid4(),
        team_id=team_id,
        user_id=member_data.user_id,
        role_id=get_role_id(member_data.role),
        status_id=team_router_state.pending_status_id,
    )
    session.add(team_member)
    await session.commit()
    await session.refresh(team_member)

    background_tasks.add_task(send_team_invitation_email, user, team)

    return team_member


@router.get("/invitations", response_model=List[TeamInvitationResponse])
async def get_pending_invitations(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Получить список pending приглашений в команды в активном событии"""
    await check_stage(session, StageType.REGISTRATION)
    active_event = await get_active_event(session)

    query = (
        select(Team, TeamMember)
        .join(TeamMember, Team.id == TeamMember.team_id)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members).selectinload(TeamMember.role),
            selectinload(Team.members).selectinload(TeamMember.status),
        )
        .where(
            Team.event_id == active_event.id,
            TeamMember.user_id == current_user.id,
            TeamMember.status_id == team_router_state.pending_status_id,
        )
    )
    result = await session.execute(query)
    # Итерируем напрямую по результату - он возвращает кортежи (Team, TeamMember)
    invitations = []
    for row in result:
        team, member = row
        # Обновляем статусы пользователей на статусы для активного события
        await update_team_members_statuses_for_event(session, team, active_event.id)
        invitations.append(
            TeamInvitationResponse(
                team=TeamResponse.from_orm_team(team),
                member=member,
            )
        )
    return invitations


@router.post("/invitations/{invitation_id}/accept")
async def accept_invitation(
    invitation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: AsyncSession = Depends(get_session),
):
    """Принять приглашение в команду"""
    await check_stage(session, StageType.REGISTRATION)

    query = select(TeamMember).where(
        TeamMember.id == invitation_id,
        TeamMember.user_id == current_user.id,
        TeamMember.status_id == team_router_state.pending_status_id,
    )
    invitation = await session.execute(query)
    invitation = invitation.scalar_one_or_none()

    if not invitation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Приглашение не найдено"
        )

    is_mentor = invitation.role_id == team_router_state.mentor_role_id

    if is_mentor:
        existing_mentor_query = select(TeamMember).where(
            TeamMember.team_id == invitation.team_id,
            TeamMember.role_id == team_router_state.mentor_role_id,
            TeamMember.status_id == team_router_state.accepted_status_id,
        )
        existing_mentor = await session.execute(existing_mentor_query)
        if existing_mentor.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="В команде уже есть ментор",
            )

        other_mentor_invitations_query = select(TeamMember).where(
            TeamMember.team_id == invitation.team_id,
            TeamMember.role_id == team_router_state.mentor_role_id,
            TeamMember.status_id == team_router_state.pending_status_id,
            TeamMember.id != invitation_id,
        )
        other_mentor_invitations = await session.execute(other_mentor_invitations_query)
        for other_invitation in other_mentor_invitations.scalars():
            other_invitation.status_id = team_router_state.rejected_status_id
    else:
        team_members_count_query = (
            select(func.count())
            .select_from(TeamMember)
            .where(
                TeamMember.team_id == invitation.team_id,
                TeamMember.status_id == team_router_state.accepted_status_id,
                TeamMember.role_id != team_router_state.mentor_role_id,
            )
        )
        current_team_members = await session.execute(team_members_count_query)
        current_team_members = current_team_members.scalar_one()

        if current_team_members == 4:
            other_pending_invitations_query = select(TeamMember).where(
                TeamMember.team_id == invitation.team_id,
                TeamMember.status_id == team_router_state.pending_status_id,
                TeamMember.role_id != team_router_state.mentor_role_id,
                TeamMember.id != invitation_id,
            )
            other_pending_invitations = await session.execute(
                other_pending_invitations_query
            )
            for other_invitation in other_pending_invitations.scalars():
                other_invitation.status_id = team_router_state.rejected_status_id

    other_invitations_query = select(TeamMember).where(
        TeamMember.user_id == current_user.id,
        TeamMember.status_id == team_router_state.pending_status_id,
        TeamMember.id != invitation_id,
    )
    other_invitations = await session.execute(other_invitations_query)
    for other_invitation in other_invitations.scalars():
        other_invitation.status_id = team_router_state.rejected_status_id

    invitation.status_id = team_router_state.accepted_status_id
    await session.flush()
    await session.refresh(invitation)

    active_event = await get_active_event(session)
    teams_query = (
        select(Team)
        .options(
            selectinload(
                Team.members.and_(
                    TeamMember.status_id == team_router_state.accepted_status_id
                )
            )
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members).selectinload(TeamMember.role),
            selectinload(Team.members).selectinload(TeamMember.status),
        )
        .where(Team.event_id == active_event.id)
    )
    result = await session.execute(teams_query)
    teams = result.scalars().all()

    # Обновляем статусы пользователей для всех команд перед проверкой
    for team in teams:
        await update_team_members_statuses_for_event(session, team, active_event.id)

    active_teams = [team for team in teams if team.get_status() == "active"]
    active_teams_count = len(active_teams)

    if active_teams_count >= 20:
        current_stage_query = select(Stage).where(
            Stage.is_active == True, Stage.event_id == active_event.id
        )
        current_stage = await session.execute(current_stage_query)
        current_stage = current_stage.scalar_one_or_none()

        if current_stage and current_stage.type == StageType.REGISTRATION.value:
            registration_closed_stage_query = select(Stage).where(
                Stage.type == StageType.REGISTRATION_CLOSED.value,
                Stage.event_id == active_event.id,
                Stage.is_active == False,
            )
            registration_closed_stage = await session.execute(
                registration_closed_stage_query
            )
            registration_closed_stage = registration_closed_stage.scalar_one_or_none()

            if registration_closed_stage:
                from src.utils.background_tasks import (
                    activate_stage_automatically_background,
                )

                # Используем обертку для фоновой активации этапа, чтобы не блокировать ответ
                background_tasks.add_task(
                    activate_stage_automatically_background,
                    registration_closed_stage.id,
                    "при достижении лимита команд (20)",
                )
                # Используем обертку, которая создает свою сессию, и запускаем только один раз
                background_tasks.add_task(send_team_confirmation_email_background)

    await session.commit()
    return {"message": "Приглашение принято"}


@router.post("/invitations/{invitation_id}/reject")
async def reject_invitation(
    invitation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Отклонить приглашение в команду"""
    await check_stage(session, StageType.REGISTRATION)

    query = select(TeamMember).where(
        TeamMember.id == invitation_id,
        TeamMember.user_id == current_user.id,
        TeamMember.status_id == team_router_state.pending_status_id,
    )
    invitation = await session.execute(query)
    invitation = invitation.scalar_one_or_none()

    if not invitation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Приглашение не найдено"
        )

    invitation.status_id = team_router_state.rejected_status_id
    await session.commit()
    return {"message": "Приглашение отклонено"}


@router.get("", response_model=List[TeamResponse])
async def get_teams(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Получить список команд пользователя в активном событии"""
    active_event = await get_active_event(session)
    query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members).selectinload(TeamMember.role),
            selectinload(Team.members).selectinload(TeamMember.status),
        )
        .where(
            Team.event_id == active_event.id,
            exists(
                select(1).where(
                    TeamMember.team_id == Team.id,
                    TeamMember.user_id == current_user.id,
                    TeamMember.status_id == team_router_state.accepted_status_id,
                )
            ),
        )
    )
    result = await session.execute(query)
    teams = result.scalars().all()

    # Обновляем статусы пользователей для всех команд
    for team in teams:
        await update_team_members_statuses_for_event(session, team, active_event.id)

    finalist_ids = await get_effective_finalist_ids(session, active_event.id)
    return [
        TeamResponse.from_orm_team(team, is_finalist=team.id in finalist_ids)
        for team in teams
    ]


@router.get("/{team_id}", response_model=TeamResponse)
async def get_team(
    team_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Получить информацию о команде по ID"""
    active_event = await get_active_event(session)

    team_query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members).selectinload(TeamMember.role),
            selectinload(Team.members).selectinload(TeamMember.status),
        )
        .where(Team.id == team_id, Team.event_id == active_event.id)
    )
    team = await session.execute(team_query)
    team = team.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена или не принадлежит активному событию",
        )

    member_query = select(TeamMember).where(
        TeamMember.team_id == team_id,
        TeamMember.user_id == current_user.id,
        TeamMember.status_id == team_router_state.accepted_status_id,
    )
    is_member = await session.execute(member_query)
    if not is_member.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="У вас нет доступа к информации об этой команде",
        )

    # Обновляем статусы пользователей на статусы для активного события
    await update_team_members_statuses_for_event(session, team, active_event.id)

    return TeamResponse.from_orm_team(
        team, is_finalist=await is_effective_finalist(session, team)
    )


@router.get("/my/team", response_model=TeamResponse)
async def get_my_team(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Получить информацию о своей команде"""
    active_event = await get_active_event(session)

    member_query = (
        select(TeamMember)
        .join(Team, TeamMember.team_id == Team.id)
        .where(
            TeamMember.user_id == current_user.id,
            TeamMember.status_id == team_router_state.accepted_status_id,
            Team.event_id == active_event.id,
        )
    )
    my_membership = await session.execute(member_query)
    my_membership = my_membership.scalar_one_or_none()

    if not my_membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Вы не состоите в команде активного события",
        )

    team_query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members).selectinload(TeamMember.role),
            selectinload(Team.members).selectinload(TeamMember.status),
        )
        .where(Team.id == my_membership.team_id, Team.event_id == active_event.id)
    )
    team = await session.execute(team_query)
    team = team.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена или не принадлежит активному событию",
        )

    # Обновляем статусы пользователей на статусы для активного события
    await update_team_members_statuses_for_event(session, team, active_event.id)

    return TeamResponse.from_orm_team(
        team, is_finalist=await is_effective_finalist(session, team)
    )


@router.get("/mentor/teams", response_model=List[TeamResponse])
async def get_mentor_teams(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Получить список всех команд, где пользователь является ментором"""
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_mentor = any(
        role.role_id == user_router_state.mentor_role_id for role in user_roles
    )

    if not is_mentor:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для менторов",
        )

    teams_query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members).selectinload(TeamMember.role),
            selectinload(Team.members).selectinload(TeamMember.status),
        )
        .where(
            exists(
                select(1).where(
                    TeamMember.team_id == Team.id,
                    TeamMember.user_id == current_user.id,
                    TeamMember.role_id == team_router_state.mentor_role_id,
                    TeamMember.status_id == team_router_state.accepted_status_id,
                )
            )
        )
    )

    result = await session.execute(teams_query)
    teams = result.scalars().all()

    # Получаем активное событие для обновления статусов
    active_event = await get_active_event(session)

    # Обновляем статусы пользователей для всех команд
    for team in teams:
        await update_team_members_statuses_for_event(session, team, active_event.id)

    finalist_ids = await get_effective_finalist_ids(session, active_event.id)
    return [
        TeamResponse.from_orm_team(team, is_finalist=team.id in finalist_ids)
        for team in teams
    ]


@router.get("/admin/teams", response_model=PaginatedTeamsResponse)
async def get_admin_teams(
    limit: int = Query(default=10, le=50, description="Number of results to return"),
    offset: int = Query(default=0, description="Number of results to skip"),
    search: Optional[str] = Query(
        None, min_length=2, description="Optional search query for team name"
    ),
    event_id: Optional[uuid.UUID] = Query(
        default=None,
        description="Идентификатор события. Если не указан — используется активное событие.",
    ),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Получение списка всех команд активного события с пагинацией и поиском.
    Доступно только для администраторов и организаторов.
    """
    # Определяем событие: либо указанное явно, либо текущее активное
    if event_id:
        event_query = select(Event).where(Event.id == event_id)
        event_result = await session.execute(event_query)
        event = event_result.scalar_one_or_none()
        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Событие не найдено"
            )
        current_event_id = event.id
    else:
        active_event = await get_active_event(session)
        current_event_id = active_event.id
    current_user_query = (
        select(User)
        .options(selectinload(User.user2roles))
        .where(User.id == current_user.id)
    )
    result = await session.execute(current_user_query)
    current_user_with_roles = result.scalar_one()

    is_admin = any(
        role.role_id == user_router_state.admin_role_id
        for role in current_user_with_roles.user2roles
    )
    is_organizer = any(
        role.role_id == user_router_state.organizer_role_id
        for role in current_user_with_roles.user2roles
    )

    if not (is_admin or is_organizer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов",
        )

    query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members).selectinload(TeamMember.role),
            selectinload(Team.members).selectinload(TeamMember.status),
        )
        .where(Team.event_id == current_event_id)
    )

    if search:
        search_query = f"%{search}%"
        query = query.where(Team.team_name.ilike(search_query))

    count_query = select(func.count()).select_from(query.subquery())
    total = await session.scalar(count_query)

    query = query.order_by(Team.team_name).limit(limit).offset(offset)

    result = await session.execute(query)
    teams = result.scalars().all()

    # Получаем активное событие для обновления статусов
    if event_id:
        event_for_status = event_id
    else:
        active_event = await get_active_event(session)
        event_for_status = active_event.id

    # Обновляем статусы пользователей для всех команд
    for team in teams:
        await update_team_members_statuses_for_event(session, team, event_for_status)

    finalist_ids = await get_effective_finalist_ids(session, event_for_status)

    return {
        "teams": [
            TeamResponse.from_orm_team(team, is_finalist=team.id in finalist_ids)
            for team in teams
        ],
        "total": total,
    }


@router.get("/admin/teams/export")
async def export_active_teams(
    event_id: Optional[uuid.UUID] = Query(
        default=None,
        description="Идентификатор события. Если не указан — используется активное событие.",
    ),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if event_id:
        event_query = select(Event).where(Event.id == event_id)
        event_result = await session.execute(event_query)
        target_event = event_result.scalar_one_or_none()
        if not target_event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Событие не найдено",
            )
    else:
        target_event = await get_active_event(session)

    current_user_query = (
        select(User)
        .options(selectinload(User.user2roles))
        .where(User.id == current_user.id)
    )
    result = await session.execute(current_user_query)
    current_user_with_roles = result.scalar_one()

    is_admin = any(
        role.role_id == user_router_state.admin_role_id
        for role in current_user_with_roles.user2roles
    )
    is_organizer = any(
        role.role_id == user_router_state.organizer_role_id
        for role in current_user_with_roles.user2roles
    )

    if not (is_admin or is_organizer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов",
        )

    query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.participant_info),
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.mentor_info),
            selectinload(Team.members).selectinload(TeamMember.role),
            selectinload(Team.members).selectinload(TeamMember.status),
        )
        .where(Team.event_id == target_event.id)
        .order_by(Team.team_name)
    )

    result = await session.execute(query)
    teams = result.scalars().all()

    for team in teams:
        await update_team_members_statuses_for_event(session, team, target_event.id)

    active_teams = [team for team in teams if team.get_status() == "active"]

    team_status_labels = {
        "active": "Активна",
        "incomplete": "Неполный состав",
        "pending": "Ожидает подтверждения",
        "needs_update": "Требует обновления",
        "invalid": "Некорректна",
    }
    team_role_labels = {
        "teamlead": "Тимлид",
        "member": "Участник",
        "mentor": "Наставник",
    }

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Active Teams"

    headers = [
        "Название команды",
        "Статус команды",
        "Финалист",
        "ФИО",
        "Роль",
        "Вуз",
        "Email",
        "Телефон",
    ]
    sheet.append(headers)

    for cell in sheet[1]:
        cell.font = Font(bold=True)

    for team in active_teams:
        for member in team.get_active_members():
            user = member.user
            participant_info = user.participant_info
            mentor_info = user.mentor_info
            university = participant_info.vuz if participant_info else ""
            phone = ""

            if participant_info and participant_info.number:
                phone = participant_info.number
            elif mentor_info and mentor_info.number:
                phone = mentor_info.number

            sheet.append(
                [
                    team.team_name,
                    team_status_labels.get(team.get_status(), team.get_status()),
                    "Да" if team.is_finalist else "Нет",
                    user.full_name,
                    team_role_labels.get(member.role.name, member.role.name)
                    if member.role
                    else "",
                    university,
                    user.email,
                    phone,
                ]
            )

    for column in sheet.columns:
        max_length = 0
        column_letter = column[0].column_letter
        for cell in column:
            value = str(cell.value) if cell.value is not None else ""
            if len(value) > max_length:
                max_length = len(value)
        sheet.column_dimensions[column_letter].width = min(max_length + 2, 40)

    sheet.freeze_panes = "A2"

    output = BytesIO()
    workbook.save(output)
    output.seek(0)

    file_name = f"active_teams_{target_event.id}.xlsx"

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


@router.get("/mentor/teams/{team_id}", response_model=TeamResponse)
async def get_mentor_team(
    team_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Получить информацию о конкретной команде ментора"""
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_mentor = any(
        role.role_id == user_router_state.mentor_role_id for role in user_roles
    )

    is_admin = any(
        role.role_id == user_router_state.admin_role_id for role in user_roles
    )

    is_judge = any(
        role.role_id == user_router_state.judge_role_id for role in user_roles
    )

    is_organizer = any(
        role.role_id == user_router_state.organizer_role_id for role in user_roles
    )

    member_query = select(TeamMember).where(
        TeamMember.team_id == team_id,
        TeamMember.user_id == current_user.id,
        TeamMember.status_id == team_router_state.accepted_status_id,
    )
    is_team_member = await session.execute(member_query)
    is_team_member = is_team_member.scalar_one_or_none()

    if not (is_mentor or is_admin or is_team_member or is_judge or is_organizer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для менторов",
        )

    if not (is_admin or is_team_member or is_judge or is_organizer):
        mentor_check_query = select(TeamMember).where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == current_user.id,
            TeamMember.role_id == team_router_state.mentor_role_id,
            TeamMember.status_id == team_router_state.accepted_status_id,
        )
        mentor_check = await session.execute(mentor_check_query)
        if not mentor_check.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="У вас нет доступа к информации об этой команде",
            )

    active_event = await get_active_event(session)

    team_query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members).selectinload(TeamMember.role),
            selectinload(Team.members).selectinload(TeamMember.status),
        )
        .where(Team.id == team_id, Team.event_id == active_event.id)
    )

    result = await session.execute(team_query)
    team = result.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена или не принадлежит активному событию",
        )

    # Обновляем статусы пользователей на статусы для активного события
    await update_team_members_statuses_for_event(session, team, active_event.id)

    return TeamResponse.from_orm_team(
        team, is_finalist=await is_effective_finalist(session, team)
    )


@router.get("/{team_id}/logo")
async def get_team_logo(
    team_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """Получить логотип команды (доступен для команд из любых событий)"""
    import logging

    logger = logging.getLogger(__name__)

    query = select(Team).where(Team.id == team_id)
    team = await session.execute(query)
    team = team.scalar_one_or_none()

    if not team:
        logger.warning(f"Команда {team_id} не найдена в БД")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Команда не найдена"
        )

    if not team.logo_file_id:
        logger.warning(f"У команды {team_id} нет logo_file_id")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="У команды нет логотипа"
        )

    logo_query = select(DBFile).where(DBFile.id == team.logo_file_id)
    logo_file = await session.execute(logo_query)
    logo_file = logo_file.scalar_one_or_none()

    if not logo_file:
        logger.warning(
            f"Файл с ID {team.logo_file_id} не найден в таблице files для команды {team_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Запись о файле логотипа не найдена в БД",
        )

    # Проверяем существование файла по указанному пути
    from src.settings import BASE_DIR

    file_path = logo_file.file_path

    # Пробуем найти файл: сначала по указанному пути, потом абсолютный
    if os.path.exists(file_path):
        # Файл найден по указанному пути (относительному или абсолютному)
        logger.debug(f"Файл найден по пути: {file_path} для команды {team_id}")
    elif not os.path.isabs(file_path):
        # Путь относительный, пробуем сделать абсолютным
        abs_path = BASE_DIR / file_path
        if os.path.exists(abs_path):
            file_path = str(abs_path)
            logger.info(
                f"Найден файл по абсолютному пути: {file_path} для команды {team_id}"
            )
        else:
            logger.warning(
                f"Файл не существует по указанному пути: {logo_file.file_path} (абсолютный: {abs_path}) для команды {team_id}"
            )

            # Fallback: пытаемся найти файл в директории команды
            team_upload_dir = f"uploads/teams/{team_id}"
            team_upload_dir_abs = BASE_DIR / team_upload_dir

            # Пробуем относительный путь
            if os.path.exists(team_upload_dir):
                search_dir = team_upload_dir
            # Пробуем абсолютный путь
            elif os.path.exists(team_upload_dir_abs):
                search_dir = str(team_upload_dir_abs)
            else:
                search_dir = None

            if search_dir:
                # Ищем все файлы изображений в директории команды
                image_files = (
                    glob.glob(f"{search_dir}/*.png")
                    + glob.glob(f"{search_dir}/*.jpg")
                    + glob.glob(f"{search_dir}/*.jpeg")
                    + glob.glob(f"{search_dir}/*.gif")
                )

                if image_files:
                    # Берем первый найденный файл изображения
                    fallback_path = image_files[0]
                    logger.info(
                        f"Используем fallback файл: {fallback_path} для команды {team_id}"
                    )
                    return FileResponse(
                        fallback_path,
                        filename=os.path.basename(fallback_path),
                        media_type="image/png"
                        if fallback_path.endswith(".png")
                        else "image/jpeg",
                    )

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Файл логотипа не найден на диске: {logo_file.file_path}",
            )
    else:
        # Путь абсолютный, но файл не найден
        logger.warning(
            f"Файл не существует по указанному абсолютному пути: {file_path} для команды {team_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Файл логотипа не найден на диске: {file_path}",
        )

    return FileResponse(
        file_path,
        filename=logo_file.filename,
        media_type=f"image/{str(logo_file.file_format).lower()}",
    )


@router.delete("/{team_id}/members/{member_id}")
async def remove_team_member(
    team_id: uuid.UUID,
    member_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Удалить участника из команды"""
    await check_stage(session, StageType.REGISTRATION)

    active_event = await get_active_event(session)

    team_query = select(Team).where(
        Team.id == team_id, Team.event_id == active_event.id
    )
    team = await session.execute(team_query)
    team = team.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена или не принадлежит активному событию",
        )

    if team.team_leader_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только лидер команды может удалять участников",
        )

    member_query = select(TeamMember).where(
        TeamMember.team_id == team_id,
        TeamMember.id == member_id,
        TeamMember.status_id == team_router_state.accepted_status_id,
    )
    team_member = await session.execute(member_query)
    team_member = team_member.scalar_one_or_none()

    if not team_member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Участник не найден в команде"
        )

    if team_member.role_id == team_router_state.teamlead_role_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Невозможно удалить лидера команды",
        )

    await session.delete(team_member)
    await session.commit()

    return {"message": "Участник успешно удален из команды"}


@router.put("/{team_id}/logo")
async def update_team_logo(
    team_id: uuid.UUID,
    logo: UploadFile = UploadFile(...),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Обновить логотип команды"""
    await check_stage(session, StageType.REGISTRATION)

    active_event = await get_active_event(session)

    team_query = select(Team).where(
        Team.id == team_id, Team.event_id == active_event.id
    )
    team = await session.execute(team_query)
    team = team.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена или не принадлежит активному событию",
        )

    if team.team_leader_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только лидер команды может изменять логотип",
        )

    new_logo = await save_file(
        upload_file=logo,
        owner_id=team.id,
        file_type=FileType.TEAM_LOGO,
        owner_type=FileOwnerType.TEAM,
    )
    session.add(new_logo)
    await session.flush()

    old_logo_id = team.logo_file_id

    team.logo_file_id = new_logo.id
    await session.flush()

    if old_logo_id:
        old_logo_query = select(DBFile).where(DBFile.id == old_logo_id)
        old_logo = await session.execute(old_logo_query)
        old_logo = old_logo.scalar_one_or_none()
        if old_logo:
            if os.path.exists(old_logo.file_path):
                os.remove(old_logo.file_path)
            await session.delete(old_logo)

    await session.commit()

    return {"message": "Логотип команды успешно обновлен"}


@router.put("/{team_id}")
async def update_team_info(
    team_id: uuid.UUID,
    team_name: str = Form(...),
    team_motto: str = Form(...),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Обновить название и девиз команды"""
    await check_stage(session, StageType.REGISTRATION)

    active_event = await get_active_event(session)

    team_query = select(Team).where(
        Team.id == team_id, Team.event_id == active_event.id
    )
    team = await session.execute(team_query)
    team = team.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена или не принадлежит активному событию",
        )

    if team.team_leader_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только лидер команды может изменять информацию о команде",
        )

    team.team_name = team_name
    team.team_motto = team_motto
    await session.commit()
    await session.refresh(team)

    return team


@router.get("/{team_id}/members", response_model=TeamMembersResponse)
async def get_team_members(
    team_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Получить список всех участников команды"""
    active_event = await get_active_event(session)

    team_query = select(Team).where(
        Team.id == team_id, Team.event_id == active_event.id
    )
    team = await session.execute(team_query)
    team = team.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена или не принадлежит активному событию",
        )

    member_query = select(TeamMember).where(
        TeamMember.team_id == team_id,
        TeamMember.user_id == current_user.id,
        TeamMember.status_id == team_router_state.accepted_status_id,
    )
    is_member = await session.execute(member_query)
    is_member = is_member.scalar_one_or_none()

    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_admin = any(
        role.role_id == user_router_state.admin_role_id for role in user_roles
    )

    is_organizer = any(
        role.role_id == user_router_state.organizer_role_id for role in user_roles
    )

    if not (is_member or is_admin or is_organizer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="У вас нет доступа к информации об участниках этой команды",
        )

    members_query = (
        select(TeamMember)
        .options(
            joinedload(TeamMember.user).joinedload(User.participant_info),
            joinedload(TeamMember.user).joinedload(User.mentor_info),
            joinedload(TeamMember.user)
            .joinedload(User.user2roles)
            .joinedload(User2Roles.role),
            joinedload(TeamMember.user).joinedload(User.current_status),
            joinedload(TeamMember.user)
            .joinedload(User.status_history)
            .joinedload(UserStatusHistory.status),
            joinedload(TeamMember.role),
            joinedload(TeamMember.status),
        )
        .where(
            TeamMember.team_id == team_id,
            TeamMember.status_id == team_router_state.accepted_status_id,
        )
    )

    result = await session.execute(members_query)
    members = result.unique().scalars().all()

    return TeamMembersResponse(
        team_id=team.id,
        team_name=team.team_name,
        team_motto=team.team_motto,
        team_leader_id=team.team_leader_id,
        logo_file_id=team.logo_file_id,
        members=[
            TeamMemberDetailResponse(
                id=member.id,
                user=member.user,
                role=member.role.name,
                status=member.status.name,
                created_at=member.created_at,
                updated_at=member.updated_at,
            )
            for member in members
        ],
    )


@router.delete("/{team_id}")
async def delete_team(
    team_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Удалить команду (только для лидера команды, только на этапе Регистрация)"""
    await check_stage(session, StageType.REGISTRATION)

    active_event = await get_active_event(session)

    team_query = select(Team).where(
        Team.id == team_id, Team.event_id == active_event.id
    )
    team = await session.execute(team_query)
    team = team.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена или не принадлежит активному событию",
        )

    if team.team_leader_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только лидер команды может удалить команду",
        )

    logo_file_id = team.logo_file_id

    if logo_file_id:
        team.logo_file_id = None
        await session.flush()

    members_query = select(TeamMember).where(TeamMember.team_id == team_id)
    members = await session.execute(members_query)
    for member in members.scalars():
        await session.delete(member)
    await session.flush()

    await session.delete(team)
    await session.flush()

    if logo_file_id:
        logo_query = select(DBFile).where(DBFile.id == logo_file_id)
        logo_file = await session.execute(logo_query)
        logo_file = logo_file.scalar_one_or_none()
        if logo_file:
            if os.path.exists(logo_file.file_path):
                os.remove(logo_file.file_path)
            await session.delete(logo_file)

    await session.commit()

    return {"message": "Команда успешно удалена"}


@router.post("/leave")
async def leave_team(
    team_id: UUID = Query(..., description="ID команды, из которой нужно выйти"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Выйти из команды (недоступно для лидера команды)"""
    await check_stage(session, StageType.REGISTRATION)

    # Получаем активное событие для фильтрации
    active_event = await get_active_event(session)

    member_query = (
        select(TeamMember)
        .join(Team, TeamMember.team_id == Team.id)
        .options(selectinload(TeamMember.role))
        .where(
            TeamMember.user_id == current_user.id,
            TeamMember.team_id == team_id,
            TeamMember.status_id == team_router_state.accepted_status_id,
            Team.event_id == active_event.id,
        )
    )
    result = await session.execute(member_query)
    member = result.scalar_one_or_none()

    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Вы не состоите в указанной команде",
        )

    # Проверяем роль через role_id, так как это более надежно
    if member.role_id == team_router_state.teamlead_role_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Лидер команды не может выйти из команды. Передайте права лидера другому участнику или удалите команду",
        )

    await session.delete(member)
    await session.commit()

    return {"message": "Вы успешно вышли из команды"}


@router.post("/{team_id}/set-finalist", response_model=dict)
async def set_team_as_finalist(
    team_id: uuid.UUID,
    is_finalist: bool = True,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Отметить команду как финалиста (только для администраторов и организаторов)"""
    # Проверка прав
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_admin = any(
        role.role_id == user_router_state.admin_role_id for role in user_roles
    )
    is_organizer = any(
        role.role_id == user_router_state.organizer_role_id for role in user_roles
    )

    if not (is_admin or is_organizer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов",
        )

    # Получаем активное событие
    active_event = await get_active_event(session)

    # Получаем команду с проверкой event_id
    team_query = select(Team).where(
        Team.id == team_id, Team.event_id == active_event.id
    )
    team_result = await session.execute(team_query)
    team = team_result.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена или не принадлежит активному событию",
        )

    # Обновляем статус финалиста
    team.is_finalist = is_finalist
    await session.commit()
    await session.refresh(team)

    return {
        "message": f"Команда {'отмечена как финалист' if is_finalist else 'убрана из финалистов'}",
        "team_id": str(team.id),
        "team_name": team.team_name,
        "is_finalist": team.is_finalist,
    }


@router.post("/set-finalists-bulk", response_model=dict)
async def set_finalists_bulk(
    team_ids: List[uuid.UUID],
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Массово отметить команды как финалистов на основе топ результатов (только для администраторов и организаторов)"""
    # Проверка прав
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_admin = any(
        role.role_id == user_router_state.admin_role_id for role in user_roles
    )
    is_organizer = any(
        role.role_id == user_router_state.organizer_role_id for role in user_roles
    )

    if not (is_admin or is_organizer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов",
        )

    active_event = await get_active_event(session)

    # Сбрасываем всех финалистов текущего события
    await session.execute(
        update(Team).where(Team.event_id == active_event.id).values(is_finalist=False)
    )

    # Отмечаем указанные команды как финалисты
    updated_count = 0
    for team_id in team_ids:
        team_query = select(Team).where(
            Team.id == team_id, Team.event_id == active_event.id
        )
        team_result = await session.execute(team_query)
        team = team_result.scalar_one_or_none()

        if team:
            team.is_finalist = True
            updated_count += 1

    await session.commit()

    return {
        "message": f"Отмечено {updated_count} команд как финалисты",
        "finalists_count": updated_count,
    }


# ЗАКОММЕНТИРОВАНО: Загрузка файлов решений отключена, решения теперь через GitHub
# from src.utils.solution_utils import save_team_solution

# @router.post("/{team_id}/solution")
# async def upload_team_solution(
#         team_id: uuid.UUID,
#         solution_file: UploadFile = File(...),
#         current_user: User = Depends(get_current_user),
#         session: AsyncSession = Depends(get_session)
# ):
#     """Загрузка ZIP файла с решением команды"""
#     await check_stage(session, [StageType.TASK_DISTRIBUTION, StageType.SOLUTION_SUBMISSION])
#
#     team_query = select(Team).where(Team.id == team_id)
#     team = await session.execute(team_query)
#     team = team.scalar_one_or_none()
#
#     if not team:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail="Команда не найдена"
#         )
#
#     member_query = select(TeamMember).where(
#         TeamMember.team_id == team_id,
#         TeamMember.user_id == current_user.id,
#         TeamMember.status_id == team_router_state.accepted_status_id
#     )
#     member = await session.execute(member_query)
#     member = member.scalar_one_or_none()
#
#     if not member:
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail="Вы не являетесь участником этой команды"
#         )
#
#     existing_solution_query = select(DBFile).where(
#         DBFile.team_id == team_id,
#         DBFile.file_type_id == file_router_state.solution_type_id
#     )
#     existing_solution = await session.execute(existing_solution_query)
#     existing_solution = existing_solution.scalar_one_or_none()
#
#     if existing_solution:
#         if os.path.exists(existing_solution.file_path):
#             os.remove(existing_solution.file_path)
#         await session.delete(existing_solution)
#         await session.flush()
#
#     solution_file_model = await save_team_solution(
#         upload_file=solution_file,
#         team_id=team_id,
#         session=session,
#         max_file_size=500 * 1024 * 1024  # 500MB
#     )
#
#     session.add(solution_file_model)
#     await session.commit()
#     await session.refresh(solution_file_model)
#
#     return solution_file_model


@router.post("/{team_id}/deployment")
async def upload_team_deployment(
    team_id: uuid.UUID,
    deployment_file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Загрузка файла с описанием развертывания (TXT или MD)"""
    # Проверяем этап - разрешены заочный и очный этапы
    current_stage = await check_stage(
        session,
        [
            StageType.TASK_DISTRIBUTION,  # Старый тип (для совместимости)
            StageType.SOLUTION_SUBMISSION,  # Старый тип (для совместимости)
            StageType.REMOTE_TASK_DISTRIBUTION,  # Заочный этап - распределение заданий
            StageType.REMOTE_SOLUTION_SUBMISSION,  # Заочный этап - прием решений
            StageType.ON_SITE_TASK_DISTRIBUTION,  # Очный этап - распределение заданий
            StageType.ON_SITE_SOLUTION_SUBMISSION,  # Очный этап - прием решений
        ],
    )

    active_event = await get_active_event(session)

    team_query = select(Team).where(
        Team.id == team_id, Team.event_id == active_event.id
    )
    team = await session.execute(team_query)
    team = team.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена или не принадлежит активному событию",
        )

    # Проверяем, является ли это очным этапом (по типу или группе)
    from src.utils.stage_group_utils import is_on_site_stage

    is_on_site = is_on_site_stage(current_stage)

    # Если очный этап, проверяем, что команда является финалистом
    if is_on_site and not await is_effective_finalist(session, team):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только команды-финалисты могут загружать файлы на очном этапе",
        )

    member_query = select(TeamMember).where(
        TeamMember.team_id == team_id,
        TeamMember.user_id == current_user.id,
        TeamMember.status_id == team_router_state.accepted_status_id,
    )
    member = await session.execute(member_query)
    member = member.scalar_one_or_none()

    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Вы не являетесь участником этой команды",
        )

    file_ext = os.path.splitext(deployment_file.filename.lower())[1]
    if file_ext not in [".txt", ".md"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Файл описания должен быть в формате TXT или MD",
        )

    existing_deployment_query = select(DBFile).where(
        DBFile.team_id == team_id,
        DBFile.file_type_id == file_router_state.deployment_type_id,
    )
    existing_deployment = await session.execute(existing_deployment_query)
    existing_deployment = existing_deployment.scalar_one_or_none()

    if existing_deployment:
        if os.path.exists(existing_deployment.file_path):
            os.remove(existing_deployment.file_path)
        await session.delete(existing_deployment)
        await session.flush()

    deployment_file_model = await save_file(
        upload_file=deployment_file,
        owner_id=team_id,
        file_type=FileType.DEPLOYMENT,
        owner_type=FileOwnerType.TEAM,
    )

    session.add(deployment_file_model)
    await session.commit()
    await session.refresh(deployment_file_model)

    return deployment_file_model


# ЗАКОММЕНТИРОВАНО: Получение файлов решений отключено, решения теперь через GitHub
# @router.get("/{team_id}/solution")
# async def get_team_solution(
#         team_id: uuid.UUID,
#         range: Optional[str] = Header(None),
#         if_none_match: Optional[str] = Header(None),
#         if_modified_since: Optional[str] = Header(None),
#         current_user: User = Depends(get_current_user),
#         session: AsyncSession = Depends(get_session)
# ):
#     """Получить файл решения команды"""
#     team_query = select(Team).where(Team.id == team_id)
#     team = await session.execute(team_query)
#     team = team.scalar_one_or_none()
#
#     if not team:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail="Команда не найдена"
#         )
#
#     member_query = select(TeamMember).where(
#         TeamMember.team_id == team_id,
#         TeamMember.user_id == current_user.id,
#         TeamMember.status_id == team_router_state.accepted_status_id
#     )
#     is_member = await session.execute(member_query)
#     is_member = is_member.scalar_one_or_none()
#
#     user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
#     user_roles = await session.execute(user_roles_query)
#     user_roles = user_roles.scalars().all()
#
#     is_admin = any(role.role_id == user_router_state.admin_role_id for role in user_roles)
#     is_organizer = any(role.role_id == user_router_state.organizer_role_id for role in user_roles)
#     is_judge = any(role.role_id == user_router_state.judge_role_id for role in user_roles)
#
#     if not (is_member or is_admin or is_organizer or is_judge):
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail="У вас нет доступа к файлам этой команды"
#         )
#
#     solution_query = select(DBFile).where(
#         DBFile.team_id == team_id,
#         DBFile.file_type_id == file_router_state.solution_type_id
#     )
#     solution = await session.execute(solution_query)
#     solution = solution.scalar_one_or_none()
#
#     if not solution or not os.path.exists(solution.file_path):
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail="Файл решения не найден"
#         )
#
#     file_size = os.path.getsize(solution.file_path)
#     mtime = os.path.getmtime(solution.file_path)
#     mtime_dt = datetime.fromtimestamp(mtime)
#
#     etag = hashlib.md5(f"{mtime}{file_size}".encode()).hexdigest()
#
#     if if_none_match and if_none_match == etag:
#         return Response(status_code=304)
#
#     if if_modified_since:
#         try:
#             ims_dt = datetime.strptime(if_modified_since, "%a, %d %b %Y %H:%M:%S GMT")
#             if mtime_dt <= ims_dt:
#                 return Response(status_code=304)
#         except ValueError:
#             pass
#
#     start = 0
#     end = file_size - 1
#     status_code = 200
#
#     if range is not None:
#         try:
#             start_str = range.replace('bytes=', '').split('-')[0]
#             start = int(start_str)
#             if start < 0 or start >= file_size:
#                 raise HTTPException(
#                     status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
#                     detail="Requested range not satisfiable"
#                 )
#             status_code = 206
#         except ValueError:
#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail="Invalid range header"
#             )
#
#     headers = {
#         'Content-Disposition': f'attachment; filename="{solution.filename}"',
#         'Content-Type': 'application/zip',
#         'Accept-Ranges': 'bytes',
#         'Cache-Control': 'public, max-age=3600',
#         'ETag': etag,
#         'Last-Modified': mtime_dt.strftime("%a, %d %b %Y %H:%M:%S GMT"),
#         'Content-Length': str(end - start + 1),
#         'X-Accel-Buffering': 'no'
#     }
#
#     if status_code == 206:
#         headers['Content-Range'] = f'bytes {start}-{end}/{file_size}'
#
#     async def file_iterator():
#         chunk_size = 256 * 1024
#         async with aiofiles.open(solution.file_path, 'rb') as f:
#             await f.seek(start)
#             bytes_remaining = end - start + 1
#             while bytes_remaining > 0:
#                 chunk_size = min(chunk_size, bytes_remaining)
#                 chunk = await f.read(chunk_size)
#                 if not chunk:
#                     break
#                 yield chunk
#                 bytes_remaining -= len(chunk)
#                 await asyncio.sleep(0)
#
#     return StreamingResponse(
#         file_iterator(),
#         headers=headers,
#         media_type='application/zip',
#         status_code=status_code
#     )


@router.get("/{team_id}/deployment")
async def get_team_deployment(
    team_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Получить файл описания развертывания команды"""
    active_event = await get_active_event(session)

    team_query = select(Team).where(
        Team.id == team_id, Team.event_id == active_event.id
    )
    team = await session.execute(team_query)
    team = team.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена или не принадлежит активному событию",
        )

    member_query = select(TeamMember).where(
        TeamMember.team_id == team_id,
        TeamMember.user_id == current_user.id,
        TeamMember.status_id == team_router_state.accepted_status_id,
    )
    is_member = await session.execute(member_query)
    is_member = is_member.scalar_one_or_none()

    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_admin = any(
        role.role_id == user_router_state.admin_role_id for role in user_roles
    )
    is_organizer = any(
        role.role_id == user_router_state.organizer_role_id for role in user_roles
    )
    is_judge = any(
        role.role_id == user_router_state.judge_role_id for role in user_roles
    )

    if not (is_member or is_admin or is_organizer or is_judge):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="У вас нет доступа к файлам этой команды",
        )

    deployment_query = select(DBFile).where(
        DBFile.team_id == team_id,
        DBFile.file_type_id == file_router_state.deployment_type_id,
    )
    deployment = await session.execute(deployment_query)
    deployment = deployment.scalar_one_or_none()

    if not deployment or not os.path.exists(deployment.file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Файл описания развертывания не найден",
        )

    return FileResponse(
        path=deployment.file_path,
        filename=deployment.filename,
        media_type="text/plain"
        if deployment.filename.endswith(".txt")
        else "text/markdown",
    )


@router.post("/notify/consultation")
async def notify_hackathon_consultation(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Отправить уведомление о консультации хакатона всем участникам и менторам"""
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_admin = any(
        role.role_id == user_router_state.admin_role_id for role in user_roles
    )
    is_organizer = any(
        role.role_id == user_router_state.organizer_role_id for role in user_roles
    )

    if not (is_admin or is_organizer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов",
        )

    background_tasks.add_task(send_hackathon_consultation_notification, session)

    return {"message": "Запущена рассылка уведомлений о консультации хакатона"}


@router.post("/notify/judge-briefing")
async def notify_hackathon_briefing(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Отправить уведомление о брифинге хакатона всем членам жюри"""
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_admin = any(
        role.role_id == user_router_state.admin_role_id for role in user_roles
    )
    is_organizer = any(
        role.role_id == user_router_state.organizer_role_id for role in user_roles
    )

    if not (is_admin or is_organizer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов",
        )

    background_tasks.add_task(send_judge_briefing_notification, session)

    return {"message": "Запущена рассылка уведомлений о консультации хакатона"}


@router.post("/notify/judge-briefing/{user_id}", status_code=status.HTTP_200_OK)
async def send_judge_briefing(
    user_id: UUID,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Отправляет уведомление о брифинге конкретному члену жюри
    """
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_admin = any(
        role.role_id == user_router_state.admin_role_id for role in user_roles
    )
    is_organizer = any(
        role.role_id == user_router_state.organizer_role_id for role in user_roles
    )

    if not (is_admin or is_organizer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов",
        )

    user_query = (
        select(User)
        .join(User2Roles)
        .where(
            and_(
                User.id == user_id,
                User2Roles.role_id == user_router_state.judge_role_id,
            )
        )
    )

    result = await session.execute(user_query)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден или не является членом жюри",
        )

    background_tasks.add_task(send_single_judge_briefing_notification, user)

    return {
        "message": f"Уведомление о брифинге поставлено в очередь для отправки пользователю {user.email}"
    }


@router.put("/{team_id}/solution-link")
async def update_solution_link(
    team_id: UUID,
    solution_link: str = Form(...),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Обновить ссылку на решение команды"""
    # Проверяем этап - разрешены заочный и очный этапы приема решений
    current_stage = await check_stage(
        session,
        [
            StageType.TASK_DISTRIBUTION,  # Старый тип (для совместимости)
            StageType.SOLUTION_SUBMISSION,  # Старый тип (для совместимости)
            StageType.REMOTE_TASK_DISTRIBUTION,  # Заочный этап - распределение заданий
            StageType.REMOTE_SOLUTION_SUBMISSION,  # Заочный этап - прием решений
            StageType.ON_SITE_TASK_DISTRIBUTION,  # Очный этап - распределение заданий
            StageType.ON_SITE_SOLUTION_SUBMISSION,  # Очный этап - прием решений
        ],
    )

    active_event = await get_active_event(session)

    # Получаем команду с проверкой event_id
    team_query = select(Team).where(
        Team.id == team_id, Team.event_id == active_event.id
    )
    team = await session.execute(team_query)
    team = team.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена или не принадлежит активному событию",
        )

    # Проверяем, является ли это очным этапом (по типу или группе)
    from src.utils.stage_group_utils import is_on_site_stage

    is_on_site = is_on_site_stage(current_stage)

    # Если очный этап, проверяем, что команда является финалистом
    if is_on_site and not await is_effective_finalist(session, team):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только команды-финалисты могут загружать решения на очном этапе",
        )

    member_query = select(TeamMember).where(
        TeamMember.team_id == team_id,
        TeamMember.user_id == current_user.id,
        TeamMember.status_id == team_router_state.accepted_status_id,
    )
    member = await session.execute(member_query)
    member = member.scalar_one_or_none()

    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Вы не являетесь участником этой команды",
        )

    # Валидация GitHub URL
    from src.utils.github_validator import validate_github_url, normalize_github_url

    is_valid, error_message = validate_github_url(solution_link)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=error_message
        )

    # Нормализуем URL к стандартному формату
    normalized_link = normalize_github_url(solution_link)

    if is_on_site:
        team.on_site_solution_link = normalized_link
    else:
        team.solution_link = normalized_link
    await session.commit()
    await session.refresh(team)

    saved_link = team.on_site_solution_link if is_on_site else team.solution_link

    return {
        "message": "Ссылка на решение успешно обновлена",
        "solution_link": saved_link,
        "on_site_solution_link": team.on_site_solution_link,
        "security_note": "⚠️ Убедитесь, что репозиторий приватный и вы добавили организаторов/жюри в Settings → Collaborators с правами Read.",
    }


@router.post("/notify/task-update")
async def notify_task_update(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Отправить уведомление о публикации дополнения к исходным данным всем активным командам"""
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_admin = any(
        role.role_id == user_router_state.admin_role_id for role in user_roles
    )
    is_organizer = any(
        role.role_id == user_router_state.organizer_role_id for role in user_roles
    )

    if not (is_admin or is_organizer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов",
        )

    background_tasks.add_task(send_task_update_notification, session)

    return {
        "message": "Запущена рассылка уведомлений о публикации дополнения к исходным данным"
    }


@router.post("/notify/opening")
async def notify_hackathon_opening(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Отправить уведомление об открытии хакатона всем активным командам"""
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_admin = any(
        role.role_id == user_router_state.admin_role_id for role in user_roles
    )
    is_organizer = any(
        role.role_id == user_router_state.organizer_role_id for role in user_roles
    )

    if not (is_admin or is_organizer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов",
        )

    background_tasks.add_task(send_hackathon_opening_notification, session)

    return {"message": "Запущена рассылка уведомлений об открытии хакатона"}


@router.post("/notify/judge-opening")
async def notify_judge_opening(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Отправить уведомление об очном открытии хакатона всем членам жюри"""
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_admin = any(
        role.role_id == user_router_state.admin_role_id for role in user_roles
    )
    is_organizer = any(
        role.role_id == user_router_state.organizer_role_id for role in user_roles
    )

    if not (is_admin or is_organizer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов",
        )

    background_tasks.add_task(send_judge_opening_notification, session)

    return {
        "message": "Запущена рассылка уведомлений об очном открытии хакатона членам жюри"
    }


@router.post("/notify/defense-schedule", response_model=dict)
async def send_defense_schedule_notification_route(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Отправляет уведомления о защите проектов всем активным командам
    """
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_admin = any(
        role.role_id == user_router_state.admin_role_id for role in user_roles
    )
    is_organizer = any(
        role.role_id == user_router_state.organizer_role_id for role in user_roles
    )

    if not (is_admin or is_organizer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов",
        )

    background_tasks.add_task(send_defense_schedule_notification, session)

    return {
        "message": "Запущена рассылка уведомлений о защите проектов всем активным командам"
    }


@router.post("/notify/closing-ceremony", response_model=dict)
async def notify_closing_ceremony(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Отправить уведомление о торжественном закрытии хакатона всем активным командам"""
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_admin = any(
        role.role_id == user_router_state.admin_role_id for role in user_roles
    )
    is_organizer = any(
        role.role_id == user_router_state.organizer_role_id for role in user_roles
    )

    if not (is_admin or is_organizer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов",
        )

    background_tasks.add_task(send_closing_ceremony_notification, session)

    return {
        "message": "Запущена рассылка уведомлений о торжественном закрытии хакатона"
    }


@router.post("/notify/first-stage-results", response_model=dict)
async def notify_first_stage_results(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_admin = any(
        role.role_id == user_router_state.admin_role_id for role in user_roles
    )
    is_organizer = any(
        role.role_id == user_router_state.organizer_role_id for role in user_roles
    )

    if not (is_admin or is_organizer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов",
        )

    background_tasks.add_task(send_first_stage_results_notification, session)

    return {"message": "Запущена рассылка уведомлений о результатах первого этапа"}


@router.post("/notify/kickoff-meeting", response_model=dict)
async def notify_kickoff_meeting(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Отправить уведомление об установочной встрече всем участникам активных команд"""
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_admin = any(
        role.role_id == user_router_state.admin_role_id for role in user_roles
    )
    is_organizer = any(
        role.role_id == user_router_state.organizer_role_id for role in user_roles
    )

    if not (is_admin or is_organizer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов",
        )

    background_tasks.add_task(send_kickoff_meeting_notification, session)

    return {"message": "Запущена рассылка уведомлений об установочной встрече"}


@router.post("/notify/finalists-kickoff-meeting", response_model=dict)
async def notify_finalists_kickoff_meeting(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Отправить уведомление об установочной встрече финалистам (участники + наставник)"""
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_admin = any(
        role.role_id == user_router_state.admin_role_id for role in user_roles
    )
    is_organizer = any(
        role.role_id == user_router_state.organizer_role_id for role in user_roles
    )

    if not (is_admin or is_organizer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов",
        )

    background_tasks.add_task(send_finalists_kickoff_meeting_notification, session)

    return {
        "message": "Запущена рассылка уведомлений об установочной встрече финалистам"
    }


@router.post("/notify/finalists-stage2-consultation", response_model=dict)
async def notify_finalists_stage2_consultation(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Отправить уведомление о консультации 2 этапа финалистам (участники + наставник)"""
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_admin = any(
        role.role_id == user_router_state.admin_role_id for role in user_roles
    )
    is_organizer = any(
        role.role_id == user_router_state.organizer_role_id for role in user_roles
    )

    if not (is_admin or is_organizer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов",
        )

    background_tasks.add_task(
        send_finalists_stage2_consultation_notification, session
    )

    return {
        "message": "Запущена рассылка уведомлений о консультации 2 этапа финалистам"
    }


@router.post("/notify/kickoff-meeting-extra", response_model=dict)
async def notify_kickoff_meeting_extra(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_admin = any(
        role.role_id == user_router_state.admin_role_id for role in user_roles
    )
    is_organizer = any(
        role.role_id == user_router_state.organizer_role_id for role in user_roles
    )

    if not (is_admin or is_organizer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов",
        )

    background_tasks.add_task(send_kickoff_meeting_notification_to_extra_recipients)

    return {
        "message": "Запущена рассылка уведомления об установочной встрече на дополнительную почту"
    }


@router.get("/public/active-count")
async def get_active_teams_count(session: AsyncSession = Depends(get_session)):
    """Получить количество активных команд для активного события (публичный endpoint)"""
    from src.utils.event_utils import get_active_event
    from src.utils.team_utils import check_active_teams
    import logging

    logger = logging.getLogger(__name__)

    try:
        active_event = await get_active_event(session)
        logger.info(f"Активное событие найдено: {active_event.id}")
    except Exception as e:
        logger.error(f"Ошибка получения активного события: {e}", exc_info=True)
        return {"active_teams_count": 0, "max_teams": 20}

    try:
        active_teams = await check_active_teams(session)
        active_teams_count = len(active_teams)
        logger.info(f"Найдено активных команд: {active_teams_count}")
    except Exception as e:
        logger.error(f"Ошибка при подсчете активных команд: {e}", exc_info=True)
        # Возвращаем 0 вместо ошибки, чтобы не ломать фронтенд
        return {"active_teams_count": 0, "max_teams": 20}

    return {"active_teams_count": active_teams_count, "max_teams": 20}


@router.get("/public/finalists", response_model=dict)
async def get_public_finalists(session: AsyncSession = Depends(get_session)):
    """
    Публичное получение списка финалистов активного события без авторизации.
    На этапе определения финалистов — топ-4 и остальные с баллами заочного этапа.
    На очном этапе — только 4 финалиста, без баллов и без остальных команд.
    """
    from src.utils.evaluation_utils import filter_evaluations_by_stage_group

    active_event = await get_active_event(session)

    current_stage_query = select(Stage).where(
        Stage.is_active == True,  # noqa: E712
        Stage.event_id == active_event.id,
    )
    current_stage = (await session.execute(current_stage_query)).scalar_one_or_none()
    is_finalists_selection = bool(
        current_stage and current_stage.type == StageType.FINALISTS_SELECTION.value
    )
    include_remaining = is_finalists_selection
    include_scores = is_finalists_selection

    finalist_ids = await get_effective_finalist_ids(session, active_event.id)

    query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.participant_info),
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members).selectinload(TeamMember.role),
            selectinload(Team.members).selectinload(TeamMember.status),
        )
        .where(Team.event_id == active_event.id)
    )

    result = await session.execute(query)
    all_teams = result.scalars().all()

    team_scores = {}
    if include_scores:
        scores_query = select(
            TeamEvaluation.team_id,
            func.sum(
                TeamEvaluation.criterion_1
                + TeamEvaluation.criterion_2
                + TeamEvaluation.criterion_3
                + TeamEvaluation.criterion_4
                + TeamEvaluation.criterion_5
            ).label("total_score"),
        ).where(TeamEvaluation.event_id == active_event.id)
        scores_query = await filter_evaluations_by_stage_group(
            session, scores_query, "remote", active_event.id
        )
        scores_query = scores_query.group_by(TeamEvaluation.team_id)
        scores_result = await session.execute(scores_query)
        team_scores = {row.team_id: float(row.total_score) for row in scores_result.all()}

    finalists = []
    remaining_teams = []

    for team in all_teams:
        if team.id not in finalist_ids:
            if not include_remaining or not team.can_participate():
                continue

        active_members = [
            member
            for member in team.members
            if member.status.name == TeamMemberStatus.ACCEPTED.value
        ]

        members_info = []
        vuz_list = set()

        for member in active_members:
            user = member.user
            member_data = {"full_name": user.full_name, "role": member.role.name}

            if user.participant_info:
                vuz = user.participant_info.vuz
                if vuz:
                    vuz_list.add(vuz)
                member_data["vuz"] = vuz

            members_info.append(member_data)

        team_data = {
            "team_id": str(team.id),
            "team_name": team.team_name,
            "team_motto": team.team_motto or "",
            "logo_file_id": str(team.logo_file_id) if team.logo_file_id else None,
            "members": members_info,
            "vuz_list": unique_vuz_list(vuz_list),
        }
        if include_scores:
            team_data["total_score"] = team_scores.get(team.id, 0.0)

        if team.id in finalist_ids:
            finalists.append(team_data)
        elif include_remaining:
            remaining_teams.append(team_data)

    if include_scores:
        finalists.sort(key=lambda x: x.get("total_score", 0), reverse=True)
        remaining_teams.sort(key=lambda x: x.get("total_score", 0), reverse=True)
    else:
        finalists.sort(key=lambda x: x.get("team_name", ""))

    return {
        "finalists": finalists,
        "remaining_teams": remaining_teams,
    }


@router.get("/judge/{team_id}/info", response_model=dict)
async def get_judge_team_info(
    team_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Получение информации о команде для жюри (для оценки)"""
    from src.models.user import ParticipantInfo

    # Проверяем, что пользователь является жюри
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_judge = any(
        role.role_id == user_router_state.judge_role_id for role in user_roles
    )

    is_admin = any(
        role.role_id == user_router_state.admin_role_id for role in user_roles
    )

    if not (is_judge or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для жюри и администраторов",
        )

    active_event = await get_active_event(session)

    # Получаем команду с участниками
    query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.participant_info),
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members).selectinload(TeamMember.role),
            selectinload(Team.members).selectinload(TeamMember.status),
        )
        .where(Team.id == team_id, Team.event_id == active_event.id)
    )

    result = await session.execute(query)
    team = result.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена или не принадлежит активному событию",
        )

    # Получаем активных участников
    active_members = [
        member
        for member in team.members
        if member.status.name == TeamMemberStatus.ACCEPTED.value
    ]

    # Собираем информацию об участниках и вузах
    members_info = []
    vuz_list = set()

    for member in active_members:
        user = member.user
        member_data = {"full_name": user.full_name, "role": member.role.name}

        # Добавляем информацию о вузе, если есть
        if user.participant_info:
            vuz = user.participant_info.vuz
            if vuz:
                vuz_list.add(vuz)
            member_data["vuz"] = vuz

        members_info.append(member_data)

    from src.utils.evaluation_utils import get_current_stage_group
    from src.utils.finalists_utils import get_solution_link_for_stage_group

    current_group = await get_current_stage_group(session)

    return {
        "team_id": str(team.id),
        "team_name": team.team_name,
        "team_motto": team.team_motto or "",
        "solution_link": get_solution_link_for_stage_group(team, current_group),
        "on_site_solution_link": team.on_site_solution_link,
        "logo_file_id": str(team.logo_file_id) if team.logo_file_id else None,
        "members": members_info,
        "vuz_list": unique_vuz_list(vuz_list),
    }


@router.get("/public/{team_id}/info", response_model=dict)
async def get_public_team_info(
    team_id: uuid.UUID,
    event_id: Optional[uuid.UUID] = Query(
        None,
        description="ID события (опционально, если не указан - используется активное событие)",
    ),
    session: AsyncSession = Depends(get_session),
):
    """Публичное получение информации о команде (для победителей и финалистов) без авторизации"""
    from src.models.user import ParticipantInfo

    # Если event_id не указан, используем активное событие
    # Иначе используем указанное событие (для прошлых результатов)
    if event_id:
        event_query = select(Event).where(Event.id == event_id)
        event_result = await session.execute(event_query)
        event = event_result.scalar_one_or_none()
        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Событие не найдено"
            )
        target_event = event
    else:
        target_event = await get_active_event(session)

    # Получаем команду с участниками
    query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.participant_info),
            selectinload(Team.members).selectinload(TeamMember.role),
            selectinload(Team.members).selectinload(TeamMember.status),
        )
        .where(Team.id == team_id, Team.event_id == target_event.id)
    )

    result = await session.execute(query)
    team = result.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена или не принадлежит указанному событию",
        )

    # Проверяем, что команда является финалистом или победителем
    # (для победителей проверяем наличие оценок)
    if not team.is_finalist:
        # Проверяем, есть ли у команды оценки (т.е. она участвовала в оценке)
        evaluation_query = select(func.count(TeamEvaluation.id)).where(
            TeamEvaluation.team_id == team_id,
            TeamEvaluation.event_id == target_event.id,
        )
        evaluation_result = await session.execute(evaluation_query)
        evaluations_count = evaluation_result.scalar() or 0

        if evaluations_count == 0:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Информация доступна только для финалистов и победителей",
            )

    # Получаем активных участников
    active_members = [
        member
        for member in team.members
        if member.status.name == TeamMemberStatus.ACCEPTED.value
    ]

    # Собираем информацию об участниках и вузах
    members_info = []
    vuz_list = set()

    for member in active_members:
        user = member.user
        member_data = {"full_name": user.full_name, "role": member.role.name}

        # Добавляем информацию о вузе, если есть
        if user.participant_info:
            vuz = user.participant_info.vuz
            if vuz:
                vuz_list.add(vuz)
            member_data["vuz"] = vuz

        members_info.append(member_data)

    # Получаем итоговый балл, если есть оценки
    total_score = None
    score_query = select(
        func.sum(
            TeamEvaluation.criterion_1
            + TeamEvaluation.criterion_2
            + TeamEvaluation.criterion_3
            + TeamEvaluation.criterion_4
            + TeamEvaluation.criterion_5
        ).label("total_score")
    ).where(
        TeamEvaluation.team_id == team_id, TeamEvaluation.event_id == target_event.id
    )

    score_result = await session.execute(score_query)
    score_row = score_result.first()
    if score_row and score_row.total_score:
        total_score = float(score_row.total_score)

    return {
        "team_id": str(team.id),
        "team_name": team.team_name,
        "team_motto": team.team_motto or "",
        "logo_file_id": str(team.logo_file_id) if team.logo_file_id else None,
        "members": members_info,
        "vuz_list": unique_vuz_list(vuz_list),
        "total_score": total_score,
    }
