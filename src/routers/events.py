import uuid
import re
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, and_
from sqlalchemy.orm import selectinload

from src.db import get_session
from src.models.event import Event, EventJudge
from src.models.user import User, User2Roles, UserEventStatus
from src.utils.router_states import user_router_state
from src.models.team import Team, TeamMember
from src.models.stage import Stage
from src.models.evaluation import TeamEvaluation
from src.models.file import File
from src.models.enums import StageType, TeamMemberStatus, TeamRole
from src.schemas.event import (
    EventCreate, EventUpdate, EventResponse, 
    EventStatistics, EventDetailResponse, JudgeResponse, EventJudgesResponse
)
from src.auth.jwt import get_current_user
from src.utils.router_states import user_router_state, team_router_state
from src.utils.vuz_utils import vuz_list_from_team_members

router = APIRouter(prefix="/events", tags=["events"])


async def check_admin_or_organizer(user: User, session: AsyncSession) -> bool:
    """Проверка наличия роли администратора или организатора у пользователя"""
    user_roles_query = select(User2Roles).where(User2Roles.user_id == user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_admin = any(role.role_id == user_router_state.admin_role_id for role in user_roles)
    is_organizer = any(role.role_id == user_router_state.organizer_role_id for role in user_roles)
    
    return is_admin or is_organizer


@router.post("", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(
    event_data: EventCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Создание нового события с автоматическим созданием этапов (только для администраторов и организаторов)"""
    if not await check_admin_or_organizer(current_user, session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов"
        )

    new_event = Event(
        id=uuid.uuid4(),
        name=event_data.name,
        description=event_data.description,
        is_active=False
    )
    
    session.add(new_event)
    await session.flush()
    
    # Создаем этапы для нового события
    if event_data.copy_stages_from_event_id:
        # Копируем этапы из указанного события
        source_stages_query = select(Stage).where(Stage.event_id == event_data.copy_stages_from_event_id)
        source_stages = await session.execute(source_stages_query)
        source_stages = source_stages.scalars().all()
        
        if not source_stages:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Исходное событие не найдено или не имеет этапов"
            )
        
        for source_stage in source_stages:
            new_stage = Stage(
                id=uuid.uuid4(),
                name=source_stage.name,
                type=source_stage.type,
                order=source_stage.order,
                is_active=False,  # Новые этапы всегда неактивны
                event_id=new_event.id,
                group=source_stage.group  # Копируем группу этапа
            )
            session.add(new_stage)
    else:
        # Создаем стандартные этапы
        default_stages = [
            {"name": "Регистрация", "type": StageType.REGISTRATION.value, "order": 1, "is_active": True},
            {"name": "Регистрация закрыта", "type": StageType.REGISTRATION_CLOSED.value, "order": 2, "is_active": False},
            {"name": "Распределение заданий", "type": StageType.TASK_DISTRIBUTION.value, "order": 3, "is_active": False},
            {"name": "Прием решений", "type": StageType.SOLUTION_SUBMISSION.value, "order": 4, "is_active": False},
            {"name": "Онлайн защита", "type": StageType.ONLINE_DEFENSE.value, "order": 5, "is_active": False},
            {"name": "Публикация результатов", "type": StageType.RESULTS_PUBLICATION.value, "order": 6, "is_active": False},
            {"name": "Церемония награждения", "type": StageType.AWARD_CEREMONY.value, "order": 7, "is_active": False},
        ]
        
        for stage_data in default_stages:
            new_stage = Stage(
                id=uuid.uuid4(),
                name=stage_data["name"],
                type=stage_data["type"],
                order=stage_data["order"],
                is_active=stage_data["is_active"],
                event_id=new_event.id
            )
            session.add(new_stage)
    
    await session.commit()
    await session.refresh(new_event)
    
    return EventResponse(
        id=new_event.id,
        name=new_event.name,
        description=new_event.description,
        is_active=new_event.is_active,
        created_at=new_event.created_at,
        updated_at=new_event.updated_at
    )


@router.get("", response_model=List[EventResponse])
async def get_events(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Получение списка всех событий"""
    query = select(Event).order_by(Event.created_at.desc())
    result = await session.execute(query)
    events = result.scalars().all()
    
    return [
        EventResponse(
            id=event.id,
            name=event.name,
            description=event.description,
            is_active=event.is_active,
            created_at=event.created_at,
            updated_at=event.updated_at
        )
        for event in events
    ]


@router.get("/active", response_model=EventResponse)
async def get_active_event(
    session: AsyncSession = Depends(get_session)
):
    """Получение активного события"""
    query = select(Event).where(Event.is_active == True)
    result = await session.execute(query)
    event = result.scalar_one_or_none()
    
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Активное событие не найдено"
        )
    
    return EventResponse(
        id=event.id,
        name=event.name,
        description=event.description,
        is_active=event.is_active,
        created_at=event.created_at,
        updated_at=event.updated_at
    )


@router.get("/past-results", response_model=List[dict])
async def get_past_events_results(
    session: AsyncSession = Depends(get_session)
):
    """Публичное получение результатов всех прошлых (неактивных) событий без авторизации"""
    # Получаем все неактивные события, отсортированные по дате создания (новые первыми)
    events_query = (
        select(Event)
        .where(Event.is_active == False)
        .order_by(Event.created_at.desc())
    )
    events_result = await session.execute(events_query)
    events = events_result.scalars().all()
    
    past_results = []
    
    for event in events:
        # Получаем результаты для каждого события
        latest_evaluations = (
            select(TeamEvaluation.id)
            .distinct(TeamEvaluation.judge_id, TeamEvaluation.team_id)
            .where(TeamEvaluation.event_id == event.id)
            .order_by(
                TeamEvaluation.judge_id,
                TeamEvaluation.team_id,
                TeamEvaluation.created_at.desc()
            )
        ).scalar_subquery()
        
        query = select(
            Team.id.label('team_id'),
            Team.team_name.label('team_name'),
            Team.team_motto.label('team_motto'),
            func.avg(
                TeamEvaluation.criterion_1 +
                TeamEvaluation.criterion_2 +
                TeamEvaluation.criterion_3 +
                TeamEvaluation.criterion_4 +
                TeamEvaluation.criterion_5
            ).label('average_score'),
            func.count(TeamEvaluation.judge_id.distinct()).label('evaluations_count'),
            func.sum(
                TeamEvaluation.criterion_1 +
                TeamEvaluation.criterion_2 +
                TeamEvaluation.criterion_3 +
                TeamEvaluation.criterion_4 +
                TeamEvaluation.criterion_5
            ).label('total_score')
        ).join(
            TeamEvaluation,
            Team.id == TeamEvaluation.team_id
        ).where(
            Team.event_id == event.id,
            TeamEvaluation.id.in_(latest_evaluations)
        ).group_by(
            Team.id,
            Team.team_name
        )
        
        result = await session.execute(query)
        teams = result.all()
        
        # Сортируем команды по total_score и берем топ-3 победителей
        sorted_teams = sorted(teams, key=lambda x: x.total_score or 0, reverse=True)
        top_teams = sorted_teams[:3] if len(sorted_teams) >= 3 else sorted_teams
        
        # Получаем финалистов (команды с is_finalist == True)
        # Исключаем команды, которые уже в топ-3 победителей
        winner_team_ids = [team.team_id for team in top_teams] if top_teams else []
        
        finalists_query = (
            select(Team)
            .options(
                selectinload(Team.members)
                .selectinload(TeamMember.user)
                .selectinload(User.participant_info),
            )
            .where(
                Team.event_id == event.id,
                Team.is_finalist == True
            )
            .order_by(Team.team_name)
        )
        finalists_result = await session.execute(finalists_query)
        finalist_teams = finalists_result.scalars().all()
        
        # Форматируем финалистов, исключая тех, кто уже в победителях
        finalists_list = []
        for finalist in finalist_teams:
            # Пропускаем финалистов, которые уже в топ-3 победителей
            if str(finalist.id) in winner_team_ids:
                continue
                
            # Получаем итоговый балл для финалиста, если есть оценки
            finalist_score_query = select(
                func.sum(
                    TeamEvaluation.criterion_1 +
                    TeamEvaluation.criterion_2 +
                    TeamEvaluation.criterion_3 +
                    TeamEvaluation.criterion_4 +
                    TeamEvaluation.criterion_5
                ).label('total_score')
            ).where(
                TeamEvaluation.team_id == finalist.id,
                TeamEvaluation.event_id == event.id
            )
            finalist_score_result = await session.execute(finalist_score_query)
            finalist_score_row = finalist_score_result.first()
            finalist_score = float(finalist_score_row.total_score) if finalist_score_row and finalist_score_row.total_score else None
            
            finalists_list.append({
                "team": finalist.team_name,
                "team_id": str(finalist.id),
                "theme": finalist.team_motto or "",
                "score": finalist_score,
                "vuz_list": vuz_list_from_team_members(finalist.members),
            })
        
        winner_ids = [team.team_id for team in top_teams]
        winner_vuz_by_id = {}
        if winner_ids:
            winners_result = await session.execute(
                select(Team)
                .options(
                    selectinload(Team.members)
                    .selectinload(TeamMember.user)
                    .selectinload(User.participant_info),
                )
                .where(Team.id.in_(winner_ids))
            )
            for winner_team in winners_result.scalars().all():
                winner_vuz_by_id[winner_team.id] = vuz_list_from_team_members(
                    winner_team.members
                )
        
        # Добавляем результаты, если есть победители или финалисты
        if top_teams or finalists_list:
            # Форматируем год: сначала пытаемся извлечь из названия, потом из даты создания
            event_year = None
            # Пытаемся извлечь год из названия (приоритет)
            year_match = re.search(r'20\d{2}', event.name)
            if year_match:
                event_year = int(year_match.group())
            # Если не нашли в названии, используем год из даты создания
            elif event.created_at:
                event_year = event.created_at.year
            
            past_results.append({
                "year": event_year or "Прошлый год",
                "event_name": event.name,
                "event_id": str(event.id),
                "winners": [
                    {
                        "place": "gold" if i == 0 else ("silver" if i == 1 else "bronze"),
                        "team": team.team_name,
                        "team_id": str(team.team_id),
                        "theme": team.team_motto or event.name,
                        "score": float(team.total_score) if team.total_score else 0,
                        "vuz_list": winner_vuz_by_id.get(team.team_id, []),
                    }
                    for i, team in enumerate(top_teams)
                ],
                "finalists": finalists_list
            })
    
    return past_results


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Получение события по ID"""
    query = select(Event).where(Event.id == event_id)
    result = await session.execute(query)
    event = result.scalar_one_or_none()
    
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Событие не найдено"
        )
    
    return EventResponse(
        id=event.id,
        name=event.name,
        description=event.description,
        is_active=event.is_active,
        created_at=event.created_at,
        updated_at=event.updated_at
    )


@router.put("/{event_id}", response_model=EventResponse)
async def update_event(
    event_id: uuid.UUID,
    event_data: EventUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Обновление события (только для администраторов и организаторов)"""
    if not await check_admin_or_organizer(current_user, session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов"
        )

    query = select(Event).where(Event.id == event_id)
    result = await session.execute(query)
    event = result.scalar_one_or_none()
    
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Событие не найдено"
        )
    
    if event_data.name is not None:
        event.name = event_data.name
    if event_data.description is not None:
        event.description = event_data.description
    if event_data.is_active is not None:
        # Если активируем событие, деактивируем все остальные
        if event_data.is_active:
            await session.execute(
                update(Event).where(Event.is_active == True).values(is_active=False)
            )
        event.is_active = event_data.is_active
    
    await session.commit()
    await session.refresh(event)
    
    return EventResponse(
        id=event.id,
        name=event.name,
        description=event.description,
        is_active=event.is_active,
        created_at=event.created_at,
        updated_at=event.updated_at
    )


@router.post("/{event_id}/activate", response_model=EventResponse)
async def activate_event(
    event_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Активация события (деактивирует все остальные)"""
    if not await check_admin_or_organizer(current_user, session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов"
        )

    query = select(Event).where(Event.id == event_id)
    result = await session.execute(query)
    event = result.scalar_one_or_none()
    
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Событие не найдено"
        )
    
    # Деактивируем все события
    await session.execute(
        update(Event).where(Event.is_active == True).values(is_active=False)
    )
    
    # Деактивируем все этапы всех событий
    await session.execute(
        update(Stage).where(Stage.is_active == True).values(is_active=False)
    )
    
    # Активируем выбранное событие
    event.is_active = True
    
    # Находим первый этап события (с минимальным order) и активируем его
    first_stage_query = (
        select(Stage)
        .where(Stage.event_id == event_id)
        .order_by(Stage.order)
        .limit(1)
    )
    first_stage_result = await session.execute(first_stage_query)
    first_stage = first_stage_result.scalar_one_or_none()
    
    if first_stage:
        first_stage.is_active = True
    
    # Создаем UserEventStatus для всех существующих пользователей со статусом need_update
    # Это требуется для нового события, так как документы могли устареть
    await user_router_state.initialize(session)
    
    all_users_query = select(User)
    all_users_result = await session.execute(all_users_query)
    all_users = all_users_result.scalars().all()
    
    from src.utils.user_status_utils import requires_document_check
    from sqlalchemy.orm import selectinload
    
    for user in all_users:
        # Проверяем, есть ли уже статус для этого события
        existing_status_query = select(UserEventStatus).where(
            UserEventStatus.user_id == user.id,
            UserEventStatus.event_id == event.id
        )
        existing_status_result = await session.execute(existing_status_query)
        existing_status = existing_status_result.scalar_one_or_none()
        
        if not existing_status:
            # Загружаем роли пользователя для проверки
            user_with_roles_query = select(User).where(User.id == user.id).options(
                selectinload(User.user2roles).selectinload(User2Roles.role)
            )
            user_result = await session.execute(user_with_roles_query)
            user_with_roles = user_result.scalar_one_or_none()
            
            if user_with_roles:
                # Определяем статус в зависимости от ролей пользователя
                if await requires_document_check(session, user_with_roles):
                    # Для участников и наставников - требуется проверка документов
                    status_id = user_router_state.need_update_status_id
                else:
                    # Для остальных (администраторы, организаторы, жюри) - автоматически подтвержден
                    status_id = user_router_state.approved_status_id
                
                user_event_status = UserEventStatus(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    event_id=event.id,
                    status_id=status_id
                )
                session.add(user_event_status)
            else:
                # Если пользователь не найден или не имеет ролей, создаем статус approved по умолчанию
                user_event_status = UserEventStatus(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    event_id=event.id,
                    status_id=user_router_state.approved_status_id
                )
                session.add(user_event_status)
    
    await session.commit()
    await session.refresh(event)
    
    return EventResponse(
        id=event.id,
        name=event.name,
        description=event.description,
        is_active=event.is_active,
        created_at=event.created_at,
        updated_at=event.updated_at
    )


@router.get("/{event_id}/statistics", response_model=EventStatistics)
async def get_event_statistics(
    event_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Получение статистики по событию"""
    if not await check_admin_or_organizer(current_user, session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов"
        )

    event_query = select(Event).where(Event.id == event_id)
    event = await session.execute(event_query)
    event = event.scalar_one_or_none()
    
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Событие не найдено"
        )
    
    # Подсчет команд
    teams_count_query = select(func.count()).select_from(Team).where(Team.event_id == event_id)
    total_teams = await session.scalar(teams_count_query) or 0
    
    # Подсчет активных команд (с полным составом)
    teams_query = (
        select(Team)
        .options(
            selectinload(Team.members).selectinload(TeamMember.user),
            selectinload(Team.members).selectinload(TeamMember.role),
            selectinload(Team.members).selectinload(TeamMember.status)
        )
        .where(Team.event_id == event_id)
    )
    teams = await session.execute(teams_query)
    teams = teams.scalars().all()
    active_teams = sum(1 for team in teams if team.can_participate())
    
    # Подсчет участников (исключая менторов)
    participants_query = (
        select(func.count(func.distinct(TeamMember.user_id)))
        .select_from(TeamMember)
        .join(Team)
        .where(
            and_(
                Team.event_id == event_id,
                TeamMember.role_id != team_router_state.mentor_role_id,
                TeamMember.status_id == team_router_state.accepted_status_id
            )
        )
    )
    total_participants = await session.scalar(participants_query) or 0
    
    # Подсчет менторов в командах
    mentors_query = (
        select(func.count(func.distinct(TeamMember.user_id)))
        .select_from(TeamMember)
        .join(Team)
        .where(
            and_(
                Team.event_id == event_id,
                TeamMember.role_id == team_router_state.mentor_role_id,
                TeamMember.status_id == team_router_state.accepted_status_id
            )
        )
    )
    total_mentors = await session.scalar(mentors_query) or 0
    
    # Подсчет оценок
    evaluations_count_query = (
        select(func.count())
        .select_from(TeamEvaluation)
        .where(TeamEvaluation.event_id == event_id)
    )
    total_evaluations = await session.scalar(evaluations_count_query) or 0
    
    # Команды с решениями
    teams_with_solutions_query = (
        select(func.count(func.distinct(Team.id)))
        .select_from(Team)
        .where(
            and_(
                Team.event_id == event_id,
                Team.solution_link.isnot(None)
            )
        )
    )
    teams_with_solutions = await session.scalar(teams_with_solutions_query) or 0
    
    return EventStatistics(
        event_id=event.id,
        event_name=event.name,
        total_teams=total_teams,
        active_teams=active_teams,
        total_participants=total_participants,
        total_mentors=total_mentors,
        total_evaluations=total_evaluations,
        teams_with_solutions=teams_with_solutions,
        created_at=event.created_at
    )


@router.get("/{event_id}/detail", response_model=EventDetailResponse)
async def get_event_detail(
    event_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Получение детальной информации о событии со статистикой"""
    if not await check_admin_or_organizer(current_user, session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов"
        )

    event_query = select(Event).where(Event.id == event_id)
    event = await session.execute(event_query)
    event = event.scalar_one_or_none()
    
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Событие не найдено"
        )
    
    statistics = await get_event_statistics(event_id, current_user, session)
    
    return EventDetailResponse(
        id=event.id,
        name=event.name,
        description=event.description,
        is_active=event.is_active,
        created_at=event.created_at,
        updated_at=event.updated_at,
        statistics=statistics
    )


@router.post("/{event_id}/copy-stages", response_model=EventResponse)
async def copy_stages_from_event(
    event_id: uuid.UUID,
    source_event_id: uuid.UUID = Query(...),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Копирование этапов из другого события (только для администраторов и организаторов)"""
    if not await check_admin_or_organizer(current_user, session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов"
        )

    # Проверяем целевое событие
    target_event_query = select(Event).where(Event.id == event_id)
    target_event = await session.execute(target_event_query)
    target_event = target_event.scalar_one_or_none()
    
    if not target_event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Целевое событие не найдено"
        )
    
    # Проверяем исходное событие
    source_event_query = select(Event).where(Event.id == source_event_id)
    source_event = await session.execute(source_event_query)
    source_event = source_event.scalar_one_or_none()
    
    if not source_event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Исходное событие не найдено"
        )
    
    # Получаем этапы из исходного события
    source_stages_query = select(Stage).where(Stage.event_id == source_event_id).order_by(Stage.order)
    source_stages = await session.execute(source_stages_query)
    source_stages = source_stages.scalars().all()
    
    if not source_stages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Исходное событие не имеет этапов"
        )
    
    # Удаляем существующие этапы целевого события
    delete_stages_query = select(Stage).where(Stage.event_id == event_id)
    existing_stages = await session.execute(delete_stages_query)
    for stage in existing_stages.scalars():
        await session.delete(stage)
    
    await session.flush()
    
    # Копируем этапы
    for source_stage in source_stages:
        new_stage = Stage(
            id=uuid.uuid4(),
            name=source_stage.name,
            type=source_stage.type,
            order=source_stage.order,
            is_active=False,  # Новые этапы всегда неактивны
            event_id=event_id
        )
        session.add(new_stage)
    
    await session.commit()
    await session.refresh(target_event)
    
    return EventResponse(
        id=target_event.id,
        name=target_event.name,
        description=target_event.description,
        is_active=target_event.is_active,
        created_at=target_event.created_at,
        updated_at=target_event.updated_at
    )


@router.delete("/{event_id}")
async def delete_event(
    event_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Удаление события (только для администраторов, только если нет связанных данных)"""
    if not await check_admin_or_organizer(current_user, session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов"
        )

    event_query = select(Event).where(Event.id == event_id)
    event = await session.execute(event_query)
    event = event.scalar_one_or_none()
    
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Событие не найдено"
        )
    
    if event.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Невозможно удалить активное событие. Сначала деактивируйте его."
        )
    
    # Проверяем наличие связанных данных
    teams_count_query = select(func.count()).select_from(Team).where(Team.event_id == event_id)
    teams_count = await session.scalar(teams_count_query) or 0
    
    if teams_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Невозможно удалить событие: к нему привязано {teams_count} команд. Удалите команды или переместите их в другое событие."
        )
    
    # Удаляем этапы события
    stages_query = select(Stage).where(Stage.event_id == event_id)
    stages = await session.execute(stages_query)
    for stage in stages.scalars():
        await session.delete(stage)
    
    # Удаляем событие
    await session.delete(event)
    await session.commit()
    
    return {"message": "Событие успешно удалено"}


@router.get("/{event_id}/judges", response_model=EventJudgesResponse)
async def get_event_judges(
    event_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Получение списка жюри для события (только для администраторов и организаторов)"""
    if not await check_admin_or_organizer(current_user, session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов"
        )
    
    # Проверяем существование события
    event_query = select(Event).where(Event.id == event_id)
    event = await session.execute(event_query)
    event = event.scalar_one_or_none()
    
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Событие не найдено"
        )
    
    # Получаем жюри события
    judges_query = (
        select(User)
        .join(EventJudge, User.id == EventJudge.judge_id)
        .where(EventJudge.event_id == event_id)
    )
    judges = await session.execute(judges_query)
    judges = judges.scalars().all()
    
    judges_response = [
        JudgeResponse(
            id=judge.id,
            full_name=judge.full_name,
            email=judge.email,
            created_at=judge.registered_at
        )
        for judge in judges
    ]
    
    return EventJudgesResponse(
        event_id=event_id,
        judges=judges_response
    )


@router.post("/{event_id}/judges/{judge_id}", status_code=status.HTTP_201_CREATED)
async def add_judge_to_event(
    event_id: uuid.UUID,
    judge_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Добавление жюри к событию (только для администраторов и организаторов)"""
    if not await check_admin_or_organizer(current_user, session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов"
        )
    
    # Проверяем существование события
    event_query = select(Event).where(Event.id == event_id)
    event = await session.execute(event_query)
    event = event.scalar_one_or_none()
    
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Событие не найдено"
        )
    
    # Проверяем существование пользователя и что он является жюри
    user_query = select(User).where(User.id == judge_id)
    user = await session.execute(user_query)
    user = user.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )
    
    # Проверяем, что пользователь имеет роль жюри
    user_roles_query = select(User2Roles).where(User2Roles.user_id == judge_id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()
    
    is_judge = any(role.role_id == user_router_state.judge_role_id for role in user_roles)
    
    if not is_judge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пользователь не является жюри"
        )
    
    # Проверяем, не добавлен ли уже жюри к событию
    existing_query = select(EventJudge).where(
        EventJudge.event_id == event_id,
        EventJudge.judge_id == judge_id
    )
    existing = await session.execute(existing_query)
    existing = existing.scalar_one_or_none()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Жюри уже добавлен к этому событию"
        )
    
    # Добавляем жюри к событию
    event_judge = EventJudge(
        event_id=event_id,
        judge_id=judge_id
    )
    session.add(event_judge)
    await session.commit()
    
    return {"message": "Жюри успешно добавлен к событию"}


@router.delete("/{event_id}/judges/{judge_id}", status_code=status.HTTP_200_OK)
async def remove_judge_from_event(
    event_id: uuid.UUID,
    judge_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Удаление жюри из события (только для администраторов и организаторов)"""
    if not await check_admin_or_organizer(current_user, session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов"
        )
    
    # Проверяем существование связи
    event_judge_query = select(EventJudge).where(
        EventJudge.event_id == event_id,
        EventJudge.judge_id == judge_id
    )
    event_judge = await session.execute(event_judge_query)
    event_judge = event_judge.scalar_one_or_none()
    
    if not event_judge:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Жюри не найден в этом событии"
        )
    
    # Удаляем связь
    await session.delete(event_judge)
    await session.commit()
    
    return {"message": "Жюри успешно удален из события"}
