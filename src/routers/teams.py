import uuid

from fastapi import APIRouter, Depends, HTTPException, status, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, exists
from typing import List
import json
from uuid import UUID

from src.db import get_session
from src.models import User, Team, TeamMember
from src.models.enums import TeamMemberStatus, TeamRole, FileType, FileOwnerType
from src.schemas.team import TeamCreate, TeamResponse, TeamMemberResponse, TeamMemberCreate, TeamInvitationResponse
from src.auth.jwt import get_current_user
from src.routers.auth import save_file

router = APIRouter(prefix="/teams", tags=["teams"])


@router.post("/create", response_model=TeamResponse)
async def create_team(
        team_name: str = Form(...),
        team_motto: str = Form(...),
        member_ids: str = Form(default="[]"),
        logo: UploadFile = File(...),
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
        TeamMember.role == TeamRole.TEAMLEAD,
        TeamMember.status == TeamMemberStatus.ACCEPTED
    )
    existing_teamlead = await session.execute(existing_teamlead_query)
    if existing_teamlead.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пользователь уже является тимлидом другой команды"
        )

    pending_invitations_query = select(TeamMember).where(
        TeamMember.user_id == current_user.id,
        TeamMember.status == TeamMemberStatus.PENDING
    )
    pending_invitations = await session.execute(pending_invitations_query)
    for invitation in pending_invitations.scalars():
        invitation.status = TeamMemberStatus.REJECTED
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
        role=TeamRole.TEAMLEAD,
        status=TeamMemberStatus.ACCEPTED
    )
    session.add(team_leader_member)

    if member_ids_list:
        team_members = []
        for user_id in member_ids_list:
            if user_id != current_user.id:
                existing_member_query = select(TeamMember).where(
                    TeamMember.user_id == user_id,
                    TeamMember.status == TeamMemberStatus.ACCEPTED
                )
                existing_member = await session.execute(existing_member_query)
                if not existing_member.scalar_one_or_none():
                    team_member = TeamMember(
                        id=uuid.uuid4(),
                        team_id=team.id,
                        user_id=user_id,
                        role=TeamRole.MEMBER,
                        status=TeamMemberStatus.PENDING
                    )
                    team_members.append(team_member)

        if team_members:
            session.add_all(team_members)

    await session.commit()
    await session.refresh(team)
    return team


@router.post("/{team_id}/members", response_model=TeamMemberResponse)
async def invite_team_member(
        team_id: uuid.UUID,
        member_data: TeamMemberCreate,
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Пригласить пользователя в команду"""
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
        if existing_member.status == TeamMemberStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Приглашение уже отправлено"
            )
        elif existing_member.status == TeamMemberStatus.ACCEPTED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Пользователь уже является участником команды"
            )

    team_member = TeamMember(
        id=uuid.uuid4(),
        team_id=team_id,
        user_id=member_data.user_id,
        role=member_data.role,
        status=TeamMemberStatus.PENDING
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
    query = select(Team).where(
        exists(
            select(1).where(
                TeamMember.team_id == Team.id,
                TeamMember.user_id == current_user.id,
                TeamMember.status == TeamMemberStatus.ACCEPTED
            )
        ))
    result = await session.execute(query)
    teams = result.scalars().all()
    return teams
