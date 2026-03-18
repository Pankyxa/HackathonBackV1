"""
Утилиты для работы со статусами пользователей с учетом событий.
Обеспечивает обратную совместимость со старыми событиями.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import Optional
from uuid import UUID

from src.models import User, UserEventStatus, UserStatusType, User2Roles
from src.utils.event_utils import get_active_event
from src.utils.router_states import user_router_state


async def requires_document_check(session: AsyncSession, user: User) -> bool:
    """
    Проверяет, требуется ли проверка документов для пользователя.
    Для пользователей с ролями "Участник" или "Наставник" требуется проверка документов.
    Для остальных (администраторы, организаторы, жюри) проверка не требуется.

    Args:
        session: Сессия БД
        user: Объект User (должен иметь загруженные user2roles)

    Returns:
        True если требуется проверка документов, False если нет
    """
    # Если user2roles не загружены, загружаем их
    if not hasattr(user, "user2roles") or not user.user2roles:
        user_query = (
            select(User)
            .where(User.id == user.id)
            .options(selectinload(User.user2roles).selectinload(User2Roles.role))
        )
        result = await session.execute(user_query)
        user = result.scalar_one_or_none()
        if not user:
            return False

    # Проверяем наличие ролей participant или mentor
    for user2role in user.user2roles:
        role_name = user2role.role.name if user2role.role else None
        if role_name in ["participant", "mentor"]:
            return True

    # Если нет ролей participant или mentor, проверка документов не требуется
    return False


async def get_user_status_for_event(
    session: AsyncSession, user_id: UUID, event_id: Optional[UUID] = None
) -> Optional[UserStatusType]:
    """
    Получает статус пользователя для указанного события.
    Если event_id не указан, используется активное событие.
    Если статуса для события нет, возвращает глобальный current_status (для обратной совместимости).

    Args:
        session: Сессия БД
        user_id: ID пользователя
        event_id: ID события (опционально, по умолчанию активное событие)

    Returns:
        UserStatusType или None
    """
    if event_id is None:
        try:
            active_event = await get_active_event(session)
            event_id = active_event.id
        except Exception:
            # Если активного события нет, возвращаем глобальный статус
            user_query = (
                select(User)
                .where(User.id == user_id)
                .options(selectinload(User.current_status))
            )
            result = await session.execute(user_query)
            user = result.scalar_one_or_none()
            return user.current_status if user else None

    # Пытаемся получить статус для события
    user_event_status_query = (
        select(UserEventStatus)
        .where(UserEventStatus.user_id == user_id, UserEventStatus.event_id == event_id)
        .options(selectinload(UserEventStatus.status))
    )
    result = await session.execute(user_event_status_query)
    user_event_status = result.scalar_one_or_none()

    if user_event_status:
        return user_event_status.status

    # Fallback на глобальный статус для обратной совместимости
    user_query = (
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.current_status))
    )
    result = await session.execute(user_query)
    user = result.scalar_one_or_none()
    return user.current_status if user else None


async def get_user_status_id_for_event(
    session: AsyncSession, user_id: UUID, event_id: Optional[UUID] = None
) -> Optional[UUID]:
    """
    Получает ID статуса пользователя для указанного события.
    Если event_id не указан, используется активное событие.
    Если статуса для события нет, возвращает глобальный current_status_id (для обратной совместимости).

    Args:
        session: Сессия БД
        user_id: ID пользователя
        event_id: ID события (опционально, по умолчанию активное событие)

    Returns:
        UUID статуса или None
    """
    if event_id is None:
        try:
            active_event = await get_active_event(session)
            event_id = active_event.id
        except Exception:
            # Если активного события нет, возвращаем глобальный статус
            user_query = select(User).where(User.id == user_id)
            result = await session.execute(user_query)
            user = result.scalar_one_or_none()
            return user.current_status_id if user else None

    # Пытаемся получить статус для события
    user_event_status_query = select(UserEventStatus).where(
        UserEventStatus.user_id == user_id, UserEventStatus.event_id == event_id
    )
    result = await session.execute(user_event_status_query)
    user_event_status = result.scalar_one_or_none()

    if user_event_status:
        return user_event_status.status_id

    # Fallback на глобальный статус для обратной совместимости
    user_query = select(User).where(User.id == user_id)
    result = await session.execute(user_query)
    user = result.scalar_one_or_none()
    return user.current_status_id if user else None


async def filter_users_by_status_for_event(
    session: AsyncSession,
    base_query,
    status_ids: list[UUID],
    event_id: Optional[UUID] = None,
):
    """
    Фильтрует пользователей по статусам для указанного события.
    Если event_id не указан, используется активное событие.
    Учитывает как UserEventStatus, так и глобальный current_status_id для обратной совместимости.

    Args:
        session: Сессия БД
        base_query: Базовый SQLAlchemy запрос для User
        status_ids: Список ID статусов для фильтрации
        event_id: ID события (опционально, по умолчанию активное событие)

    Returns:
        Модифицированный запрос с фильтрацией
    """
    from sqlalchemy import or_, and_

    if event_id is None:
        try:
            active_event = await get_active_event(session)
            event_id = active_event.id
        except Exception:
            # Если активного события нет, фильтруем по глобальному статусу
            return base_query.where(User.current_status_id.in_(status_ids))

    # Фильтруем по UserEventStatus для события ИЛИ по глобальному статусу (для обратной совместимости)
    return base_query.where(
        or_(
            # Пользователи со статусом для события
            User.id.in_(
                select(UserEventStatus.user_id).where(
                    and_(
                        UserEventStatus.event_id == event_id,
                        UserEventStatus.status_id.in_(status_ids),
                    )
                )
            ),
            # Пользователи без статуса для события, но с глобальным статусом (обратная совместимость)
            and_(
                User.current_status_id.in_(status_ids),
                ~User.id.in_(
                    select(UserEventStatus.user_id).where(
                        UserEventStatus.event_id == event_id
                    )
                ),
            ),
        )
    )


async def update_team_members_statuses_for_event(
    session: AsyncSession, team, event_id: Optional[UUID] = None
):
    """
    Обновляет current_status для всех пользователей в команде на статус для указанного события.
    Это нужно для корректной работы team.get_status() и отображения статусов на фронтенде.

    Args:
        session: Сессия БД
        team: Объект Team с загруженными members
        event_id: ID события (опционально, по умолчанию активное событие)
    """
    from src.models.user import UserStatusType
    from sqlalchemy.orm import selectinload

    if event_id is None:
        try:
            active_event = await get_active_event(session)
            event_id = active_event.id
        except Exception:
            # Если активного события нет, оставляем глобальные статусы
            return

    if not hasattr(team, "members") or not team.members:
        return

    with session.no_autoflush:
        for member in team.members:
            if member.user:
                user_status_id = await get_user_status_id_for_event(
                    session, member.user.id, event_id
                )
                if user_status_id:
                    # Временно обновляем current_status_id для проверки статуса команды
                    # Это не сохраняется в БД, только для вычисления статуса
                    member.user.current_status_id = user_status_id
                    # Обновляем объект статуса
                    status_query = select(UserStatusType).where(
                        UserStatusType.id == user_status_id
                    )
                    status_result = await session.execute(status_query)
                    status_obj = status_result.scalar_one_or_none()
                    if status_obj:
                        member.user.current_status = status_obj
