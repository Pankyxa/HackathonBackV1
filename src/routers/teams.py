from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid
from typing import List

from src.db import get_session
from src.models.user import Team, TeamMember, User
from src.models.enums import TeamRole
from src.auth.jwt import get_current_user
from src.schemas.team import TeamCreate, TeamResponse, TeamMemberCreate, TeamMemberResponse

router = APIRouter(prefix="/teams", tags=["teams"])


@router.post("/create", response_model=TeamResponse)
async def create_team(
        team_data: TeamCreate,
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    # Проверяем, не является ли пользователь уже тимлидом другой команды
    query = select(TeamMember).where(
        TeamMember.user_id == str(current_user.id),  # Преобразуем UUID в строку
        TeamMember.role == TeamRole.TEAMLEAD
    )
    existing_teamlead = await session.execute(query)
    if existing_teamlead.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пользователь уже является тим лидером другой команды"
        )

    # Создаем команду
    team = Team(
        id=uuid.uuid4(),
        team_name=team_data.team_name,
        team_leader_id=current_user.id
    )
    session.add(team)
    await session.flush()

    # Добавляем создателя как тимлида команды
    team_member = TeamMember(
        id=uuid.uuid4(),
        team_id=team.id,
        user_id=current_user.id,
        role=TeamRole.TEAMLEAD
    )
    session.add(team_member)

    await session.commit()
    await session.refresh(team)

    return team

@router.post("/{team_id}/members", response_model=TeamMemberResponse)
async def add_team_member(
    team_id: uuid.UUID,
    member_data: TeamMemberCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    # Проверяем существование команды
    team_query = select(Team).where(Team.id == team_id)
    team = await session.execute(team_query)
    team = team.scalar_one_or_none()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )

    # Проверяем, является ли текущий пользователь тимлидом этой команды
    if team.team_leader_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only team leader can add members"
        )

    # Проверяем существование пользователя, которого добавляем
    user_query = select(User).where(User.id == member_data.user_id)
    user = await session.execute(user_query)
    user = user.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Проверяем, не является ли пользователь уже участником этой команды
    member_query = select(TeamMember).where(
        TeamMember.team_id == team_id,
        TeamMember.user_id == member_data.user_id
    )
    existing_member = await session.execute(member_query)
    if existing_member.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already a member of this team"
        )

    # Создаем нового участника команды
    team_member = TeamMember(
        id=uuid.uuid4(),
        team_id=team_id,
        user_id=member_data.user_id,
        role=member_data.role
    )
    session.add(team_member)
    await session.commit()
    await session.refresh(team_member)

    return team_member

@router.get("", response_model=List[TeamResponse])
async def get_teams(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    query = select(Team).where(Team.team_leader_id == current_user.id)
    result = await session.execute(query)
    teams = result.scalars().all()
    return teams