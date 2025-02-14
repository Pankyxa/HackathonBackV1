from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, exists
import uuid
from typing import List

from src.db import get_session
from src.models import User, Team, TeamMember, TeamRole, FileType, FileFormat
from src.auth.jwt import get_current_user
from src.schemas.team import TeamResponse, TeamMemberCreate, TeamMemberResponse
from src.routers.auth import save_file  # Импортируем функцию сохранения файла

router = APIRouter(prefix="/teams", tags=["teams"])


@router.post("/create", response_model=TeamResponse)
async def create_team(
        team_name: str = Form(...),
        team_motto: str = Form(...),
        logo: UploadFile = File(...),
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    # Проверяем, не является ли пользователь уже тимлидом другой команды
    query = select(TeamMember).where(
        TeamMember.user_id == str(current_user.id),
        TeamMember.role == TeamRole.TEAMLEAD
    )
    existing_teamlead = await session.execute(query)
    if existing_teamlead.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пользователь уже является тим лидером другой команды"
        )

    # Проверяем формат файла логотипа
    if not logo.content_type.startswith('image/'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Логотип должен быть изображением"
        )

    # Сохраняем файл логотипа
    logo_file = await save_file(logo, current_user.id, FileType.TEAM_LOGO)
    session.add(logo_file)
    await session.flush()

    # Создаем команду
    team = Team(
        id=uuid.uuid4(),
        team_name=team_name,
        team_motto=team_motto,
        team_leader_id=current_user.id,
        logo_file_id=logo_file.id  # Связываем команду с логотипом
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
    query = select(Team).where(
        exists(
            select(1).where(
                TeamMember.team_id == Team.id,
                TeamMember.user_id == current_user.id
            )
        ))
    result = await session.execute(query)
    teams = result.scalars().all()
    return teams
