from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, exists
import uuid
from typing import List

from src.db import get_session
from src.models import User, Team, TeamMember, TeamRole, FileType, FileFormat, FileOwnerType
from src.auth.jwt import get_current_user
from src.schemas.team import TeamResponse, TeamMemberCreate, TeamMemberResponse
from src.routers.auth import save_file

router = APIRouter(prefix="/teams", tags=["teams"])


@router.post("/create", response_model=TeamResponse)
async def create_team(
        team_name: str = Form(...),
        team_motto: str = Form(...),
        logo: UploadFile = File(...),
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
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

    if not logo.content_type.startswith('image/'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Логотип должен быть изображением"
        )

    team = Team(
        id=uuid.uuid4(),
        team_name=team_name,
        team_motto=team_motto,
        team_leader_id=current_user.id
    )
    session.add(team)
    await session.flush()

    logo_file = await save_file(
        logo,
        team.id,
        FileType.TEAM_LOGO,
        FileOwnerType.TEAM
    )
    session.add(logo_file)
    await session.flush()

    team.logo_file_id = logo_file.id
    await session.flush()

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
    team_query = select(Team).where(Team.id == team_id)
    team = await session.execute(team_query)
    team = team.scalar_one_or_none()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )

    if team.team_leader_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only team leader can add members"
        )

    user_query = select(User).where(User.id == member_data.user_id)
    user = await session.execute(user_query)
    user = user.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

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
