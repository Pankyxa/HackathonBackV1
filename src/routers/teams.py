import uuid

from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, exists, func
from typing import List, Optional
import json
from uuid import UUID
import os

from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.testing.plugin.plugin_base import options

from src.db import get_session
from src.models import User, Team, TeamMember, Role, UserStatusHistory
from src.models.file import File as DBFile
from src.models.enums import TeamMemberStatus, TeamRole, FileType, FileOwnerType
from src.models.user import User2Roles
from src.schemas.team import TeamCreate, TeamResponse, TeamMemberResponse, TeamMemberCreate, TeamInvitationResponse, \
    TeamMembersResponse, TeamMemberDetailResponse, TeamStatusDetails, PaginatedTeamsResponse
from src.auth.jwt import get_current_user
from src.routers.auth import save_file
from src.utils.router_states import team_router_state, user_router_state

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
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Создание команды с указанием участников по их ID"""
    try:
        member_ids_list = [UUID(id_str) for id_str in json.loads(member_ids)]
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный формат member_ids"
        )

    if member_ids_list:
        users_query = select(User).where(User.id.in_(member_ids_list))
        result = await session.execute(users_query)
        found_users = result.scalars().all()

        if len(found_users) != len(member_ids_list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Некоторые пользователи не найдены"
            )

    existing_teamlead_query = select(TeamMember).where(
        TeamMember.user_id == current_user.id,
        TeamMember.role_id == team_router_state.teamlead_role_id,
        TeamMember.status_id == team_router_state.accepted_status_id
    )
    existing_teamlead = await session.execute(existing_teamlead_query)
    if existing_teamlead.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пользователь уже является тимлидом другой команды"
        )

    pending_invitations_query = select(TeamMember).where(
        TeamMember.user_id == current_user.id,
        TeamMember.status_id == team_router_state.pending_status_id
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
        logo_file_id=None
    )
    session.add(team)
    await session.flush()

    logo_file = await save_file(
        upload_file=logo,
        owner_id=team.id,
        file_type=FileType.TEAM_LOGO,
        owner_type=FileOwnerType.TEAM
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
        status_id=team_router_state.accepted_status_id
    )
    session.add(team_leader_member)

    if member_ids_list:
        team_members = []
        for user_id in member_ids_list:
            if user_id != current_user.id:
                existing_member_query = select(TeamMember).where(
                    TeamMember.user_id == user_id,
                    TeamMember.status_id == team_router_state.accepted_status_id
                )
                existing_member = await session.execute(existing_member_query)
                if not existing_member.scalar_one_or_none():
                    team_member = TeamMember(
                        id=uuid.uuid4(),
                        team_id=team.id,
                        user_id=user_id,
                        role_id=team_router_state.member_role_id,
                        status_id=team_router_state.pending_status_id
                    )
                    team_members.append(team_member)

        if team_members:
            session.add_all(team_members)

    await session.commit()

    team_query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members)
            .selectinload(TeamMember.role),
            selectinload(Team.members)
            .selectinload(TeamMember.status)
        )
        .where(Team.id == team.id)
    )
    result = await session.execute(team_query)
    team_with_relations = result.scalar_one()

    return TeamResponse(
        id=team_with_relations.id,
        team_name=team_with_relations.team_name,
        team_motto=team_with_relations.team_motto,
        team_leader_id=team_with_relations.team_leader_id,
        logo_file_id=team_with_relations.logo_file_id,
        status_details=TeamStatusDetails(**team_with_relations.get_status_details())
    )


@router.post("/{team_id}/mentor", response_model=TeamMemberResponse)
async def invite_team_mentor(
        team_id: uuid.UUID,
        mentor_id: UUID,
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Пригласить ментора в команду"""
    team_query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members)
            .selectinload(TeamMember.role),
            selectinload(Team.members)
            .selectinload(TeamMember.status)
        )
        .where(Team.id == team_id)
    )
    team = await session.execute(team_query)
    team = team.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена"
        )

    if team.team_leader_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только лидер команды может приглашать ментора"
        )

    mentor_query = (
        select(User)
        .options(
            selectinload(User.user2roles)
            .selectinload(User2Roles.role)
        )
        .where(User.id == mentor_id)
    )
    mentor = await session.execute(mentor_query)
    mentor = mentor.scalar_one_or_none()

    if not mentor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )

    is_mentor = any(
        user2role.role_id == user_router_state.mentor_role_id
        for user2role in mentor.user2roles
    )
    if not is_mentor:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пользователь не является ментором"
        )

    existing_mentor_query = (
        select(TeamMember)
        .where(
            TeamMember.team_id == team_id,
            TeamMember.role_id == team_router_state.mentor_role_id,
            TeamMember.status_id == team_router_state.accepted_status_id
        )
    )
    existing_mentor = await session.execute(existing_mentor_query)
    if existing_mentor.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="В команде уже есть ментор"
        )

    existing_invitation_query = (
        select(TeamMember)
        .where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == mentor_id
        )
    )
    existing_invitation = await session.execute(existing_invitation_query)
    existing_invitation = existing_invitation.scalar_one_or_none()

    if existing_invitation:
        if existing_invitation.status_id == team_router_state.pending_status_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Приглашение уже отправлено"
            )
        elif existing_invitation.status_id == team_router_state.accepted_status_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ментор уже является участником команды"
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

    return team_member


@router.post("/{team_id}/members", response_model=TeamMemberResponse)
async def invite_team_member(
        team_id: uuid.UUID,
        member_data: TeamMemberCreate,
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Пригласить пользователя в команду"""
    team_query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members)
            .selectinload(TeamMember.role),
            selectinload(Team.members)
            .selectinload(TeamMember.status)
        )
        .where(Team.id == team_id)
    )
    team = await session.execute(team_query)
    team = team.scalar_one_or_none()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена"
        )

    if team.team_leader_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только лидер команды может приглашать участников"
        )

    user_query = select(User).where(User.id == member_data.user_id)
    user = await session.execute(user_query)
    user = user.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )

    member_query = select(TeamMember).where(
        TeamMember.team_id == team_id,
        TeamMember.user_id == member_data.user_id
    )
    existing_member = await session.execute(member_query)
    existing_member = existing_member.scalar_one_or_none()

    if existing_member:
        if existing_member.status_id == team_router_state.pending_status_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Приглашение уже отправлено"
            )
        elif existing_member.status_id == team_router_state.accepted_status_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Пользователь уже является участником команды"
            )

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
    return team_member


@router.get("/invitations", response_model=List[TeamInvitationResponse])
async def get_pending_invitations(
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Получить список pending приглашений в команды"""
    query = (
        select(Team, TeamMember)
        .join(TeamMember, Team.id == TeamMember.team_id)
        .where(
            TeamMember.user_id == current_user.id,
            TeamMember.status == TeamMemberStatus.PENDING
        )
    )
    result = await session.execute(query)
    invitations = [
        TeamInvitationResponse(team=team, member=member)
        for team, member in result
    ]
    return invitations


@router.post("/invitations/{invitation_id}/accept")
async def accept_invitation(
        invitation_id: uuid.UUID,
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Принять приглашение в команду"""
    query = select(TeamMember).where(
        TeamMember.id == invitation_id,
        TeamMember.user_id == current_user.id,
        TeamMember.status == TeamMemberStatus.PENDING
    )
    invitation = await session.execute(query)
    invitation = invitation.scalar_one_or_none()

    if not invitation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Приглашение не найдено"
        )

    invitation.status = TeamMemberStatus.ACCEPTED
    await session.commit()
    return {"message": "Приглашение принято"}


@router.post("/invitations/{invitation_id}/reject")
async def reject_invitation(
        invitation_id: uuid.UUID,
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Отклонить приглашение в команду"""
    query = select(TeamMember).where(
        TeamMember.id == invitation_id,
        TeamMember.user_id == current_user.id,
        TeamMember.status == TeamMemberStatus.PENDING
    )
    invitation = await session.execute(query)
    invitation = invitation.scalar_one_or_none()

    if not invitation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Приглашение не найдено"
        )

    invitation.status = TeamMemberStatus.REJECTED
    await session.commit()
    return {"message": "Приглашение отклонено"}


@router.get("", response_model=List[TeamResponse])
async def get_teams(
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Получить список команд пользователя"""
    query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members)
            .selectinload(TeamMember.role),
            selectinload(Team.members)
            .selectinload(TeamMember.status)
        )
        .where(
            exists(
                select(1).where(
                    TeamMember.team_id == Team.id,
                    TeamMember.user_id == current_user.id,
                    TeamMember.status_id == team_router_state.accepted_status_id
                )
            ))
    )
    result = await session.execute(query)
    teams = result.scalars().all()
    return [
        TeamResponse(
            id=team.id,
            team_name=team.team_name,
            team_motto=team.team_motto,
            team_leader_id=team.team_leader_id,
            logo_file_id=team.logo_file_id,
            status_details=TeamStatusDetails(**team.get_status_details())
        )
        for team in teams
    ]


@router.get("/{team_id}", response_model=TeamResponse)
async def get_team(
        team_id: uuid.UUID,
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Получить информацию о команде по ID"""
    team_query = (
        select(Team)
        .where(Team.id == team_id)
    )
    team = await session.execute(team_query)
    team = team.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена"
        )

    member_query = select(TeamMember).where(
        TeamMember.team_id == team_id,
        TeamMember.user_id == current_user.id,
        TeamMember.status_id == team_router_state.accepted_status_id
    )
    is_member = await session.execute(member_query)
    if not is_member.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="У вас нет доступа к информации об этой команде"
        )

    return TeamResponse(
        id=team.id,
        team_name=team.team_name,
        team_motto=team.team_motto,
        team_leader_id=team.team_leader_id,
        logo_file_id=team.logo_file_id,
        status_details=TeamStatusDetails(**team.get_status_details())
    )


@router.get("/my/team", response_model=TeamResponse)
async def get_my_team(
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Получить информацию о своей команде"""
    member_query = (
        select(TeamMember)
        .where(
            TeamMember.user_id == current_user.id,
            TeamMember.status_id == team_router_state.accepted_status_id
        )
    )
    my_membership = await session.execute(member_query)
    my_membership = my_membership.scalar_one_or_none()

    if not my_membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Вы не состоите в команде"
        )

    team_query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members)
            .selectinload(TeamMember.role),
            selectinload(Team.members)
            .selectinload(TeamMember.status)
        )
        .where(Team.id == my_membership.team_id)
    )
    team = await session.execute(team_query)
    team = team.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена"
        )

    return TeamResponse(
        id=team.id,
        team_name=team.team_name,
        team_motto=team.team_motto,
        team_leader_id=team.team_leader_id,
        logo_file_id=team.logo_file_id,
        status_details=TeamStatusDetails(**team.get_status_details())
    )


@router.get("/mentor/teams", response_model=List[TeamResponse])
async def get_mentor_teams(
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Получить список всех команд, где пользователь является ментором"""
    user_roles_query = (
        select(User2Roles)
        .where(User2Roles.user_id == current_user.id)
    )
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_mentor = any(
        role.role_id == user_router_state.mentor_role_id
        for role in user_roles
    )

    if not is_mentor:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для менторов"
        )

    teams_query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members)
            .selectinload(TeamMember.role),
            selectinload(Team.members)
            .selectinload(TeamMember.status)
        )
        .where(
            exists(
                select(1).where(
                    TeamMember.team_id == Team.id,
                    TeamMember.user_id == current_user.id,
                    TeamMember.role_id == team_router_state.mentor_role_id,
                    TeamMember.status_id == team_router_state.accepted_status_id
                )
            ))
    )

    result = await session.execute(teams_query)
    teams = result.scalars().all()

    return [
        TeamResponse(
            id=team.id,
            team_name=team.team_name,
            team_motto=team.team_motto,
            team_leader_id=team.team_leader_id,
            logo_file_id=team.logo_file_id,
            status_details=TeamStatusDetails(**team.get_status_details())
        )
        for team in teams
    ]


@router.get("/admin/teams", response_model=PaginatedTeamsResponse)
async def get_admin_teams(
    limit: int = Query(default=10, le=50, description="Number of results to return"),
    offset: int = Query(default=0, description="Number of results to skip"),
    search: Optional[str] = Query(None, min_length=2, description="Optional search query for team name"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Получение списка всех команд с пагинацией и поиском.
    Доступно только для администраторов и организаторов.
    """
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
            detail="Доступ разрешен только для администраторов и организаторов"
        )

    query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members)
            .selectinload(TeamMember.role),
            selectinload(Team.members)
            .selectinload(TeamMember.status)
        )
    )

    if search:
        search_query = f"%{search}%"
        query = query.where(Team.team_name.ilike(search_query))

    count_query = select(func.count()).select_from(query.subquery())
    total = await session.scalar(count_query)

    query = (
        query
        .order_by(Team.team_name)
        .limit(limit)
        .offset(offset)
    )

    result = await session.execute(query)
    teams = result.scalars().all()

    return {
        "teams": [
            TeamResponse(
                id=team.id,
                team_name=team.team_name,
                team_motto=team.team_motto,
                team_leader_id=team.team_leader_id,
                logo_file_id=team.logo_file_id,
                status_details=TeamStatusDetails(**team.get_status_details())
            )
            for team in teams
        ],
        "total": total
    }

@router.get("/mentor/teams/{team_id}", response_model=TeamResponse)
async def get_mentor_team(
        team_id: UUID,
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Получить информацию о конкретной команде ментора"""
    user_roles_query = (
        select(User2Roles)
        .where(User2Roles.user_id == current_user.id)
    )
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_mentor = any(
        role.role_id == user_router_state.mentor_role_id
        for role in user_roles
    )

    is_admin = any(
        role.role_id == user_router_state.admin_role_id
        for role in user_roles
    )

    if not (is_mentor or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для менторов"
        )

    if not is_admin:
        mentor_check_query = select(TeamMember).where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == current_user.id,
            TeamMember.role_id == team_router_state.mentor_role_id,
            TeamMember.status_id == team_router_state.accepted_status_id
        )
        mentor_check = await session.execute(mentor_check_query)
        if not mentor_check.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="У вас нет доступа к информации об этой команде"
            )

    team_query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members)
            .selectinload(TeamMember.role),
            selectinload(Team.members)
            .selectinload(TeamMember.status)
        )
        .where(Team.id == team_id)
    )

    result = await session.execute(team_query)
    team = result.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена"
        )

    return TeamResponse(
        id=team.id,
        team_name=team.team_name,
        team_motto=team.team_motto,
        team_leader_id=team.team_leader_id,
        logo_file_id=team.logo_file_id,
        status_details=TeamStatusDetails(**team.get_status_details())
    )


@router.get("/{team_id}/logo")
async def get_team_logo(
        team_id: uuid.UUID,
        session: AsyncSession = Depends(get_session)
):
    """Получить логотип команды"""
    query = select(Team).where(Team.id == team_id)
    team = await session.execute(query)
    team = team.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена"
        )

    if not team.logo_file_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="У команды нет логотипа"
        )

    logo_query = select(DBFile).where(DBFile.id == team.logo_file_id)
    logo_file = await session.execute(logo_query)
    logo_file = logo_file.scalar_one_or_none()

    if not logo_file or not os.path.exists(logo_file.file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Файл логотипа не найден"
        )

    return FileResponse(
        logo_file.file_path,
        filename=logo_file.filename,
        media_type=f"image/{str(logo_file.file_format).lower()}"
    )


@router.delete("/{team_id}/members/{member_id}")
async def remove_team_member(
        team_id: uuid.UUID,
        member_id: uuid.UUID,
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Удалить участника из команды"""
    team_query = select(Team).where(Team.id == team_id)
    team = await session.execute(team_query)
    team = team.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена"
        )

    if team.team_leader_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только лидер команды может удалять участников"
        )

    member_query = select(TeamMember).where(
        TeamMember.team_id == team_id,
        TeamMember.id == member_id,
        TeamMember.status_id == team_router_state.accepted_status_id
    )
    team_member = await session.execute(member_query)
    team_member = team_member.scalar_one_or_none()

    if not team_member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Участник не найден в команде"
        )

    if team_member.role_id == team_router_state.teamlead_role_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Невозможно удалить лидера команды"
        )

    await session.delete(team_member)
    await session.commit()

    return {"message": "Участник успешно удален из команды"}


@router.put("/{team_id}/logo")
async def update_team_logo(
        team_id: uuid.UUID,
        logo: UploadFile = UploadFile(...),
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Обновить логотип команды"""
    team_query = select(Team).where(Team.id == team_id)
    team = await session.execute(team_query)
    team = team.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена"
        )

    if team.team_leader_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только лидер команды может изменять логотип"
        )

    new_logo = await save_file(
        upload_file=logo,
        owner_id=team.id,
        file_type=FileType.TEAM_LOGO,
        owner_type=FileOwnerType.TEAM
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
        session: AsyncSession = Depends(get_session)
):
    """Обновить название и девиз команды"""
    team_query = select(Team).where(Team.id == team_id)
    team = await session.execute(team_query)
    team = team.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена"
        )

    if team.team_leader_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только лидер команды может изменять информацию о команде"
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
        session: AsyncSession = Depends(get_session)
):
    """Получить список всех участников команды"""
    team_query = (
        select(Team)
        .where(Team.id == team_id)
    )
    team = await session.execute(team_query)
    team = team.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена"
        )

    member_query = select(TeamMember).where(
        TeamMember.team_id == team_id,
        TeamMember.user_id == current_user.id,
        TeamMember.status_id == team_router_state.accepted_status_id
    )
    is_member = await session.execute(member_query)
    is_member = is_member.scalar_one_or_none()

    user_roles_query = (
        select(User2Roles)
        .where(User2Roles.user_id == current_user.id)
    )
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_admin = any(
        role.role_id == user_router_state.admin_role_id
        for role in user_roles
    )

    if not (is_member or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="У вас нет доступа к информации об участниках этой команды"
        )

    members_query = (
        select(TeamMember)
        .options(
            joinedload(TeamMember.user).joinedload(User.participant_info),
            joinedload(TeamMember.user).joinedload(User.mentor_info),
            joinedload(TeamMember.user).joinedload(User.user2roles).joinedload(User2Roles.role),
            joinedload(TeamMember.user).joinedload(User.current_status),
            joinedload(TeamMember.user).joinedload(User.status_history).joinedload(UserStatusHistory.status),
            joinedload(TeamMember.role),
            joinedload(TeamMember.status)
        )
        .where(
            TeamMember.team_id == team_id,
            TeamMember.status_id == team_router_state.accepted_status_id
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
                updated_at=member.updated_at
            ) for member in members
        ]
    )


@router.delete("/{team_id}")
async def delete_team(
        team_id: uuid.UUID,
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Удалить команду (только для лидера команды)"""
    team_query = select(Team).where(Team.id == team_id)
    team = await session.execute(team_query)
    team = team.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена"
        )

    if team.team_leader_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только лидер команды может удалить команду"
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
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Выйти из команды (недоступно для лидера команды)"""
    member_query = select(TeamMember).where(
        TeamMember.user_id == current_user.id,
        TeamMember.status_id == team_router_state.accepted_status_id
    )
    member = await session.execute(member_query)
    member = member.scalar_one_or_none()

    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Вы не состоите в команде"
        )

    if member.role == TeamRole.TEAMLEAD:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Лидер команды не может выйти из команды. Передайте права лидера другому участнику или удалите команду"
        )

    await session.delete(member)
    await session.commit()

    return {"message": "Вы успешно вышли из команды"}
