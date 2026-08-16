"""
Утилиты для работы с финалистами
"""
from typing import List, Tuple, Optional, Set
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from uuid import UUID

from src.models.team import Team, TeamMember
from src.models.user import User, User2Roles
from src.models.evaluation import TeamEvaluation
from src.models.event import Event
from src.utils.evaluation_utils import filter_evaluations_by_stage_group


def get_solution_link_for_stage_group(team: Team, stage_group: Optional[str]) -> Optional[str]:
    """Возвращает ссылку на решение для нужного этапа: очный — отдельная, иначе заочная."""
    if stage_group == "on_site":
        return team.on_site_solution_link
    return team.solution_link


async def user_can_access_on_site_materials(session: AsyncSession, user: User) -> bool:
    """Админы, организаторы, жюри и участники команд-финалистов могут видеть материалы очного этапа."""
    from src.utils.router_states import user_router_state, team_router_state
    from src.utils.event_utils import get_active_event

    await user_router_state.initialize(session)
    await team_router_state.initialize(session)

    user_roles_query = select(User2Roles).where(User2Roles.user_id == user.id)
    user_roles = (await session.execute(user_roles_query)).scalars().all()

    privileged_role_ids = {
        user_router_state.admin_role_id,
        user_router_state.organizer_role_id,
        user_router_state.judge_role_id,
    }
    if any(role.role_id in privileged_role_ids for role in user_roles):
        return True

    try:
        active_event = await get_active_event(session)
    except Exception:
        return False

    finalist_ids = await get_effective_finalist_ids(session, active_event.id)
    if not finalist_ids:
        return False

    membership_query = (
        select(TeamMember.id)
        .join(Team, TeamMember.team_id == Team.id)
        .where(
            TeamMember.user_id == user.id,
            TeamMember.status_id == team_router_state.accepted_status_id,
            Team.event_id == active_event.id,
            Team.id.in_(finalist_ids),
        )
        .limit(1)
    )
    membership = (await session.execute(membership_query)).scalar_one_or_none()
    return membership is not None


# Количество финалистов (можно сделать настраиваемым)
FINALISTS_COUNT = 4


async def get_effective_finalist_ids(
    session: AsyncSession,
    event_id: UUID,
    count: int = FINALISTS_COUNT,
) -> Set[UUID]:
    """Финалисты: отмеченные флагом is_finalist или топ-N по оценкам заочного этапа."""
    flagged_query = select(Team.id).where(
        Team.event_id == event_id,
        Team.is_finalist == True,  # noqa: E712
    )
    flagged_ids = set((await session.execute(flagged_query)).scalars().all())
    top_teams = await get_top_finalists_by_scores(
        session, event_id, stage_group="remote", count=count
    )
    return flagged_ids.union(team.id for team in top_teams)


async def is_effective_finalist(session: AsyncSession, team: Team) -> bool:
    if getattr(team, "is_finalist", False):
        return True
    return team.id in await get_effective_finalist_ids(session, team.event_id)


async def get_top_finalists_by_scores(
    session: AsyncSession,
    event_id: UUID,
    stage_group: str = "remote",
    count: int = FINALISTS_COUNT
) -> List[Team]:
    """
    Получает топ команд по оценкам заочного этапа для определения финалистов
    
    Args:
        session: Сессия БД
        event_id: ID события
        stage_group: Группа этапа ('remote' для заочного этапа)
        count: Количество финалистов (по умолчанию 4)
    
    Returns:
        Список команд-финалистов, отсортированных по убыванию среднего балла
    """
    # Получаем все команды события с загрузкой members и их relationships
    teams_query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.role),
            selectinload(Team.members)
            .selectinload(TeamMember.status)
        )
        .where(Team.event_id == event_id)
    )
    teams_result = await session.execute(teams_query)
    all_teams = teams_result.scalars().all()
    
    # Получаем оценки за заочный этап
    evaluations_query = (
        select(TeamEvaluation)
        .where(TeamEvaluation.event_id == event_id)
    )
    
    # Фильтруем по группе этапа (заочный)
    evaluations_query = await filter_evaluations_by_stage_group(
        session, evaluations_query, stage_group, event_id
    )
    
    evaluations_result = await session.execute(evaluations_query)
    evaluations = evaluations_result.scalars().all()
    
    # Вычисляем средний балл для каждой команды
    team_scores = {}
    team_evaluation_counts = {}
    
    for evaluation in evaluations:
        team_id = evaluation.team_id
        total_score = evaluation.get_total_score()
        
        if team_id not in team_scores:
            team_scores[team_id] = 0
            team_evaluation_counts[team_id] = 0
        
        team_scores[team_id] += total_score
        team_evaluation_counts[team_id] += 1
    
    # Вычисляем средний балл и создаем список команд с баллами
    # Для определения финалистов учитываем все команды, которые имеют хотя бы базовую структуру
    # (лидер, наставник, 4 участника), независимо от статуса одобрения
    teams_with_scores = []
    for team in all_teams:
        # Проверяем только базовую структуру команды (не статус одобрения)
        # Это нужно, чтобы на этапе "Регистрация закрыта" команды все равно могли быть финалистами
        has_leader = team.get_team_leader_member() is not None
        has_mentor = team.get_mentor() is not None
        regular_members = team.get_regular_members()
        has_4_members = len(regular_members) == 4
        
        if not (has_leader and has_mentor and has_4_members):
            continue
            
        if team.id in team_scores and team_evaluation_counts[team.id] > 0:
            average_score = team_scores[team.id] / team_evaluation_counts[team.id]
            teams_with_scores.append((team, average_score, team_scores[team.id]))
        else:
            # Команды без оценок получают 0 баллов
            teams_with_scores.append((team, 0.0, 0))
    
    # Сортируем по среднему баллу (убывание), затем по общему баллу
    teams_with_scores.sort(key=lambda x: (x[1], x[2]), reverse=True)
    
    # Берем топ-N команд (если команд меньше N, берем все доступные)
    top_teams = [team for team, _, _ in teams_with_scores[:count]]
    
    return top_teams


async def update_finalists_automatically(
    session: AsyncSession,
    event_id: UUID,
    stage_group: str = "remote",
    count: int = FINALISTS_COUNT
) -> Tuple[int, List[UUID]]:
    """
    Автоматически обновляет список финалистов на основе оценок заочного этапа
    
    Args:
        session: Сессия БД
        event_id: ID события
        stage_group: Группа этапа ('remote' для заочного этапа)
        count: Количество финалистов (по умолчанию 4)
    
    Returns:
        Кортеж (количество обновленных команд, список ID команд-финалистов)
    """
    from sqlalchemy import update
    
    # Сбрасываем всех финалистов текущего события
    await session.execute(
        update(Team)
        .where(Team.event_id == event_id)
        .values(is_finalist=False)
    )
    
    # Получаем топ команд по оценкам
    top_teams = await get_top_finalists_by_scores(
        session, event_id, stage_group, count
    )
    
    # Отмечаем их как финалистов
    finalist_ids = []
    for team in top_teams:
        team.is_finalist = True
        finalist_ids.append(team.id)
    
    await session.flush()
    
    return len(finalist_ids), finalist_ids
