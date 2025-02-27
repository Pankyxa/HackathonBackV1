from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from src.models import Team, Stage, User, TeamMember
from src.models.enums import StageType, UserStatus, TeamRole
from src.utils.router_states import stage_router_state, team_router_state
from typing import List


async def check_active_teams(db: AsyncSession) -> List[Team]:
    """
    Получить список активных команд (со статусом 'active')
    """
    teams_query = (
        select(Team)
        .outerjoin(TeamMember)
        .outerjoin(User)
    )

    result = await db.execute(teams_query)
    teams = result.unique().scalars().all()

    return [team for team in teams if team.get_status() == "active"]


async def check_and_update_registration_stage(db: AsyncSession) -> bool:
    """
    Проверяет количество активных команд и автоматически закрывает регистрацию,
    если достигнуто необходимое количество команд

    Returns:
        bool: True если регистрация была закрыта, False в противном случае
    """
    active_teams = await check_active_teams(db)
    active_teams_count = len(active_teams)

    current_stage = await db.execute(
        select(Stage).where(Stage.is_active == True)
    )
    current_stage = current_stage.scalar_one_or_none()

    if (active_teams_count >= 20 and current_stage and
            current_stage.type == StageType.REGISTRATION.value):
        registration_closed_stage = await db.execute(
            select(Stage).where(Stage.type == StageType.REGISTRATION_CLOSED.value)
        )
        registration_closed_stage = registration_closed_stage.scalar_one_or_none()

        if registration_closed_stage:
            current_stage.is_active = False
            registration_closed_stage.is_active = True

            await db.commit()

            await stage_router_state.initialize(db)

            return True

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