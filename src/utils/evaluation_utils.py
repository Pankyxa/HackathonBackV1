"""
Утилиты для работы с оценками команд
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from typing import Optional, List
from uuid import UUID
from src.models.evaluation import TeamEvaluation
from src.models.stage import Stage
from src.models.enums import StageType
from src.utils.stage_group_utils import is_remote_stage, is_on_site_stage
from src.utils.event_utils import get_active_event


async def get_stages_by_group(
    session: AsyncSession,
    group: str,
    event_id: Optional[UUID] = None
) -> List[Stage]:
    """
    Получает все этапы определенной группы (remote, on_site)
    
    Args:
        session: Сессия базы данных
        group: Группа этапов ('remote' или 'on_site')
        event_id: ID события (UUID, если None, используется активное событие)
        
    Returns:
        List[Stage]: Список этапов указанной группы
    """
    if event_id is None:
        active_event = await get_active_event(session)
        event_id = active_event.id
    
    query = select(Stage).where(
        and_(
            Stage.event_id == event_id,
            Stage.group == group
        )
    )
    result = await session.execute(query)
    return result.scalars().all()


async def filter_evaluations_by_stage_group(
    session: AsyncSession,
    evaluations_query,
    stage_group: str,
    event_id: Optional[UUID] = None
):
    """
    Фильтрует оценки по группе этапов (remote или on_site)
    
    Args:
        session: Сессия базы данных
        evaluations_query: Базовый запрос для оценок
        stage_group: Группа этапов ('remote' или 'on_site')
        event_id: ID события (UUID, если None, используется активное событие)
        
    Returns:
        Запрос с примененным фильтром по группе этапов
    """
    if event_id is None:
        active_event = await get_active_event(session)
        event_id = active_event.id
    
    # Получаем все этапы указанной группы
    stages = await get_stages_by_group(session, stage_group, event_id)
    stage_ids = [stage.id for stage in stages]
    
    if not stage_ids:
        # Если нет этапов этой группы, возвращаем пустой результат
        return evaluations_query.where(TeamEvaluation.stage_id.in_([]))
    
    # Фильтруем оценки по ID этапов
    return evaluations_query.where(TeamEvaluation.stage_id.in_(stage_ids))


async def get_current_stage_group(session: AsyncSession) -> Optional[str]:
    """
    Определяет группу текущего активного этапа
    
    Args:
        session: Сессия базы данных
        
    Returns:
        Optional[str]: Группа этапа ('remote', 'on_site' или None)
    """
    active_event = await get_active_event(session)
    query = select(Stage).where(
        and_(
            Stage.is_active == True,
            Stage.event_id == active_event.id
        )
    )
    result = await session.execute(query)
    current_stage = result.scalar_one_or_none()
    
    if not current_stage:
        return None
    
    if is_remote_stage(current_stage):
        return 'remote'
    elif is_on_site_stage(current_stage):
        return 'on_site'
    
    return None
