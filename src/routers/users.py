from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_
from typing import List

from src.auth.jwt import get_current_user
from src.db import get_session
from src.models import User
from src.schemas.user import UserResponse

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
    Search users by full name with pagination.
    Returns users where full_name contains the search query (case-insensitive).
    """
    search_query = f"%{query}%"

    stmt = (
        select(User)
        .where(and_(
            User.full_name.ilike(search_query),
            User.id != current_user.id
        ))
        .limit(limit)
        .offset(offset)
        .order_by(User.full_name)
    )

    result = await session.execute(stmt)
    users = result.scalars().all()

    return users
