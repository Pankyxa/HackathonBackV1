from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_, not_, exists
from sqlalchemy.orm import selectinload
from typing import List

from src.auth.jwt import get_current_user
from src.db import get_session
from src.models import User, TeamMember
from src.models.enums import TeamMemberStatus
from src.schemas.user import UserResponse
from src.utils.router_states import team_router_state

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/search", response_model=List[UserResponse])
async def search_users(
        query: str = Query(..., min_length=2, description="Search query for user full name"),
        limit: int = Query(default=10, le=50, description="Number of results to return"),
        offset: int = Query(default=0, description="Number of results to skip"),
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """
    Поиск пользователей по ФИО с пагинацией.
    """
    search_query = f"%{query}%"

    current_user_team = (
        select(TeamMember.team_id)
        .where(
            and_(
                TeamMember.user_id == current_user.id,
                TeamMember.status_id == team_router_state.accepted_status_id
            )
        )
    )

    stmt = (
        select(User)
        .options(selectinload(User.participant_info))
        .where(
            and_(
                User.full_name.ilike(search_query),
                User.id != current_user.id,
                not_(
                    exists(
                        select(1)
                        .where(
                            TeamMember.user_id == User.id,
                            TeamMember.status_id == team_router_state.accepted_status_id,
                            TeamMember.team_id == TeamMember.team_id,
                        )
                    )
                ),
                not_(
                    exists(
                        select(1)
                        .where(
                            TeamMember.user_id == User.id,
                            TeamMember.team_id.in_(current_user_team)
                        )
                    )
                )
            )
        )
        .limit(limit)
        .offset(offset)
        .order_by(User.full_name)
    )

    result = await session.execute(stmt)
    users = result.scalars().all()

    return users
