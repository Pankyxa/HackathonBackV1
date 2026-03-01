from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from src.models import Team, Stage, User, TeamMember
from src.models.enums import StageType, UserStatus, TeamRole
from src.models.user import UserStatusType
from src.utils.router_states import stage_router_state, team_router_state, user_router_state
from src.utils.user_status_utils import get_user_status_id_for_event
from typing import List


async def check_active_teams(db: AsyncSession) -> List[Team]:
    """
    Получить список активных команд (со статусом 'active') для активного события
    """
    from src.utils.event_utils import get_active_event
    from sqlalchemy.orm import selectinload
    import logging
    
    logger = logging.getLogger(__name__)
    
    try:
        active_event = await get_active_event(db)
    except Exception as e:
        logger.error(f"Ошибка получения активного события в check_active_teams: {e}", exc_info=True)
        return []
    
    try:
        # Загружаем команды с полной информацией о членах, ролях и статусах
        teams_query = (
            select(Team)
            .where(Team.event_id == active_event.id)
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

        result = await db.execute(teams_query)
        teams = result.unique().scalars().all()
        
        logger.debug(f"Загружено команд из БД: {len(teams)}")
        
        # Обновляем current_status для всех пользователей на статус для активного события
        # Это нужно для корректной работы team.get_status()
        await user_router_state.initialize(db)
        for team in teams:
            for member in team.members:
                if member.user:
                    user_status_id = await get_user_status_id_for_event(
                        db,
                        member.user.id,
                        active_event.id
                    )
                    if user_status_id:
                        # Временно обновляем current_status_id для проверки статуса команды
                        # Это не сохраняется в БД, только для вычисления статуса
                        original_status_id = member.user.current_status_id
                        member.user.current_status_id = user_status_id
                        # Обновляем объект статуса
                        from sqlalchemy.orm import selectinload
                        status_query = select(UserStatusType).where(UserStatusType.id == user_status_id)
                        status_result = await db.execute(status_query)
                        status_obj = status_result.scalar_one_or_none()
                        if status_obj:
                            member.user.current_status = status_obj
        
        # Фильтруем активные команды
        active_teams = []
        status_counts = {}
        for team in teams:
            try:
                team_status = team.get_status()
                status_counts[team_status] = status_counts.get(team_status, 0) + 1
                if team_status == "active":
                    active_teams.append(team)
            except Exception as e:
                logger.warning(f"Ошибка при получении статуса команды {team.id}: {e}")
                status_counts["error"] = status_counts.get("error", 0) + 1
                # Пропускаем команду с ошибкой
                continue
        
        logger.info(f"Статусы команд: {status_counts}")
        logger.info(f"Найдено активных команд: {len(active_teams)}")
        return active_teams
        
    except Exception as e:
        logger.error(f"Ошибка при загрузке команд в check_active_teams: {e}", exc_info=True)
        return []


async def check_and_update_registration_stage(db: AsyncSession) -> bool:
    """
    Проверяет количество активных команд и автоматически закрывает регистрацию,
    если достигнуто необходимое количество команд
    
    ВАЖНО: Эта функция теперь использует единую систему автоматической активации
    из background_tasks. Проверка также выполняется периодически каждую минуту.

    Returns:
        bool: True если регистрация была закрыта, False в противном случае
    """
    from src.utils.event_utils import get_active_event
    from src.utils.background_tasks import activate_stage_automatically
    
    try:
        active_event = await get_active_event(db)
    except Exception:
        return False
    
    active_teams = await check_active_teams(db)
    active_teams_count = len(active_teams)

    current_stage_query = select(Stage).where(
        Stage.is_active == True,
        Stage.event_id == active_event.id
    )
    current_stage_result = await db.execute(current_stage_query)
    current_stage = current_stage_result.scalar_one_or_none()

    if (active_teams_count >= 20 and current_stage and
            current_stage.type == StageType.REGISTRATION.value):
        registration_closed_query = select(Stage).where(
            Stage.type == StageType.REGISTRATION_CLOSED.value,
            Stage.event_id == active_event.id,
            Stage.is_active == False
        )
        registration_closed_result = await db.execute(registration_closed_query)
        registration_closed_stage = registration_closed_result.scalar_one_or_none()

        if registration_closed_stage:
            # Используем единую функцию активации
            success = await activate_stage_automatically(
                registration_closed_stage,
                db,
                "при достижении лимита команд (20)"
            )
            return success

    return False


async def check_team_status_after_user_update(
        db: AsyncSession,
        user_id: UUID
) -> None:
    """
    Проверяет статус команд пользователя после обновления его статуса
    и при необходимости обновляет этап регистрации
    """
    teams_query = (
        select(Team)
        .join(TeamMember)
        .where(
            TeamMember.user_id == user_id,
            TeamMember.status_id == team_router_state.accepted_status_id
        )
    )
    result = await db.execute(teams_query)
    teams = result.unique().scalars().all()

    for team in teams:
        old_status = team.get_status()
        if old_status != "active" and team.get_status() == "active":
            await check_and_update_registration_stage(db)
            break