import uuid

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_, not_, exists, func
from sqlalchemy.orm import selectinload
from typing import List, Optional

from starlette import status

from src.auth.jwt import get_current_user
from src.db import get_session
from src.models import User, TeamMember, File as FileModel
from src.models.user import User2Roles, UserStatusHistory
from src.schemas.file import FileResponse
from src.schemas.user import UserResponse, PaginatedUserResponse
from src.utils.router_states import team_router_state, user_router_state, file_router_state

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
        .options(
            selectinload(User.participant_info),
            selectinload(User.mentor_info),
            selectinload(User.user2roles).selectinload(User2Roles.role),
            selectinload(User.current_status),
            selectinload(User.status_history).selectinload(UserStatusHistory.status),
        )
        .where(
            and_(
                User.full_name.ilike(search_query),
                User.id != current_user.id,
                exists(
                    select(1)
                    .where(
                        User2Roles.user_id == User.id,
                        User2Roles.role_id == user_router_state.participant_role_id
                    )
                ),
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


@router.get("/search/mentors", response_model=List[UserResponse])
async def search_mentors(
        query: str = Query(..., min_length=2, description="Search query for mentor full name"),
        limit: int = Query(default=10, le=50, description="Number of results to return"),
        offset: int = Query(default=0, description="Number of results to skip"),
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """
    Поиск менторов по ФИО с пагинацией.
    В отличие от поиска обычных пользователей:
    - Ищет только пользователей с ролью ментора
    - Может возвращать менторов, которые уже состоят в других командах
    """
    search_query = f"%{query}%"

    stmt = (
        select(User)
        .options(
            selectinload(User.participant_info),
            selectinload(User.mentor_info),
            selectinload(User.user2roles).selectinload(User2Roles.role),
            selectinload(User.current_status),
            selectinload(User.status_history).selectinload(UserStatusHistory.status),
        )
        .where(
            and_(
                User.full_name.ilike(search_query),
                User.id != current_user.id,
                exists(
                    select(1)
                    .where(
                        User2Roles.user_id == User.id,
                        User2Roles.role_id == user_router_state.mentor_role_id
                    )
                )
            )
        )
        .limit(limit)
        .offset(offset)
        .order_by(User.full_name)
    )

    result = await session.execute(stmt)
    mentors = result.scalars().all()

    return mentors


@router.get("/", response_model=List[UserResponse])
async def get_users(
        limit: int = Query(default=10, le=50, description="Number of results to return"),
        offset: int = Query(default=0, description="Number of results to skip"),
        search: Optional[str] = Query(None, min_length=2,
                                      description="Optional search query for user full name or email"),
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """
    Получение списка всех пользователей с пагинацией и опциональной фильтрацией по ФИО или email.
    """
    query = select(User).options(
        selectinload(User.participant_info),
        selectinload(User.mentor_info),
        selectinload(User.user2roles).selectinload(User2Roles.role),
        selectinload(User.current_status),
        selectinload(User.status_history).selectinload(UserStatusHistory.status),
    )

    if search:
        search_query = f"%{search}%"
        query = query.where(
            or_(
                User.full_name.ilike(search_query),
                User.email.ilike(search_query)
            )
        )

    query = query.order_by(User.full_name) \
        .limit(limit) \
        .offset(offset)

    result = await session.execute(query)
    users = result.scalars().all()

    return users


@router.get("/pending", response_model=PaginatedUserResponse)
async def get_pending_users(
        limit: int = Query(default=10, le=50, description="Number of results to return"),
        offset: int = Query(default=0, description="Number of results to skip"),
        search: Optional[str] = Query(None, min_length=2,
                                      description="Optional search query for user full name or email"),
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """
    Получение списка пользователей со статусом PENDING.
    Поддерживает пагинацию и опциональный поиск по ФИО или email.
    """
    base_query = (
        select(User)
        .where(User.current_status_id == user_router_state.pending_status_id)
    )

    if search:
        search_query = f"%{search}%"
        base_query = base_query.where(
            or_(
                User.full_name.ilike(search_query),
                User.email.ilike(search_query)
            )
        )

    count_query = select(func.count()).select_from(base_query.subquery())
    total = await session.scalar(count_query)

    query = (
        base_query
        .options(
            selectinload(User.participant_info),
            selectinload(User.mentor_info),
            selectinload(User.user2roles).selectinload(User2Roles.role),
            selectinload(User.current_status),
            selectinload(User.status_history).selectinload(UserStatusHistory.status),
        )
        .order_by(User.registered_at.desc())
        .limit(limit)
        .offset(offset)
    )

    result = await session.execute(query)
    users = result.scalars().all()

    return {
        "users": users,
        "total": total
    }


@router.get("/{user_id}/documents", response_model=List[FileResponse])
async def get_user_documents(
        user_id: uuid.UUID,
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """
    Получение документов пользователя (согласие и справка с места учебы/работы)
    """
    current_user_query = (
        select(User)
        .options(selectinload(User.user2roles))
        .where(User.id == current_user.id)
    )
    result = await session.execute(current_user_query)
    current_user_with_roles = result.scalar_one()

    is_organizer = any(
        role.role_id == user_router_state.organizer_role_id
        for role in current_user_with_roles.user2roles
    )

    if current_user.id != user_id and not is_organizer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав для просмотра документов"
        )

    query = (
        select(FileModel)
        .options(
            selectinload(FileModel.file_format),
            selectinload(FileModel.file_type),
            selectinload(FileModel.owner_type)
        )
        .where(
            and_(
                FileModel.user_id == user_id,
                FileModel.owner_type_id == file_router_state.user_owner_type_id,
                FileModel.file_type_id.in_([
                    file_router_state.consent_type_id,
                    file_router_state.education_certificate_type_id,
                    file_router_state.job_certificate_type_id
                ])
            )
        )
    )

    result = await session.execute(query)
    documents = result.scalars().all()

    return documents
