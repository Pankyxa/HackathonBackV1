import uuid
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload

from src.auth.jwt import get_current_user
from src.db import get_session
from src.models.user import User, User2Roles
from src.models.team import Team, TeamMember
from src.models.evaluation import TeamEvaluation
from src.models.event import EventJudge
from src.models.stage import Stage
from src.schemas.evaluation import (
    TeamEvaluationCreate,
    TeamEvaluationResponse,
    TeamTotalScore,
    UnevaluatedTeam,
    DetailedTeamEvaluationResponse,
)
from src.utils.router_states import user_router_state
from src.utils.event_utils import get_active_event
from src.utils.stage_checker import check_stage
from src.utils.evaluation_utils import (
    filter_evaluations_by_stage_group,
    get_current_stage_group,
    get_stages_by_group,
)
from src.utils.finalists_utils import get_solution_link_for_stage_group
from src.utils.cache import cache, invalidate_evaluation_cache
from src.models.enums import StageType

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


@router.post("/evaluate-team", response_model=TeamEvaluationResponse)
async def create_evaluation(
    evaluation: TeamEvaluationCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Проверяем, что текущий этап позволяет оценивать команды
    current_stage = await check_stage(
        session,
        [
            StageType.ONLINE_DEFENSE,  # Заочный этап - онлайн защита (оценка происходит здесь)
            StageType.ON_SITE_DEFENSE,  # Очный этап - проверка решений (защита)
            StageType.SOLUTION_REVIEW,  # Старый тип (для совместимости)
        ],
    )

    # Получаем ID текущего этапа для сохранения в оценке
    current_stage_id = current_stage.id

    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_judge = any(
        role.role_id == user_router_state.judge_role_id for role in user_roles
    )
    is_admin = any(
        role.role_id == user_router_state.admin_role_id for role in user_roles
    )
    is_organizer = any(
        role.role_id == user_router_state.organizer_role_id for role in user_roles
    )

    if not (is_judge or is_admin or is_organizer):
        raise HTTPException(
            status_code=403,
            detail="Only judges, administrators and organizers can evaluate teams",
        )

    active_event = await get_active_event(session)

    effective_judge_id = current_user.id

    if evaluation.judge_id:
        if (is_admin or is_organizer) and not (
            is_judge and evaluation.judge_id == current_user.id
        ):
            effective_judge_id = evaluation.judge_id
        elif evaluation.judge_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Член жюри может выставлять оценки только от своего имени",
            )
    elif (is_admin or is_organizer) and not is_judge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Для администратора или организатора необходимо указать judge_id",
        )

    event_judge_query = select(EventJudge).where(
        EventJudge.event_id == active_event.id,
        EventJudge.judge_id == effective_judge_id,
    )
    event_judge_result = await session.execute(event_judge_query)
    event_judge = event_judge_result.scalar_one_or_none()

    if not event_judge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Указанный член жюри не привязан к активному событию",
        )

    team_query = select(Team).where(
        Team.id == evaluation.team_id, Team.event_id == active_event.id
    )
    team = await session.execute(team_query)
    team = team.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена или не принадлежит активному событию",
        )

    # Ищем существующую оценку для этого этапа (чтобы обновлять оценку на том же этапе)
    existing_evaluation_query = select(TeamEvaluation).where(
        TeamEvaluation.team_id == evaluation.team_id,
        TeamEvaluation.judge_id == effective_judge_id,
        TeamEvaluation.event_id == active_event.id,
        TeamEvaluation.stage_id == current_stage_id,
    )
    existing_evaluation = await session.execute(existing_evaluation_query)
    existing_evaluation = existing_evaluation.scalar_one_or_none()

    if existing_evaluation:
        existing_evaluation.criterion_1 = evaluation.criterion_1
        existing_evaluation.criterion_2 = evaluation.criterion_2
        existing_evaluation.criterion_3 = evaluation.criterion_3
        existing_evaluation.criterion_4 = evaluation.criterion_4
        existing_evaluation.criterion_5 = evaluation.criterion_5
        existing_evaluation.stage_id = (
            current_stage_id  # Обновляем stage_id на случай изменения
        )
        existing_evaluation.updated_at = datetime.utcnow()
        await session.commit()

        # Инвалидируем кэш оценок
        await invalidate_evaluation_cache(
            event_id=str(active_event.id), team_id=str(evaluation.team_id)
        )

        return TeamEvaluationResponse(
            id=existing_evaluation.id,
            team_id=existing_evaluation.team_id,
            team_name=team.team_name,
            team_motto=team.team_motto,
            judge_id=existing_evaluation.judge_id,
            stage_id=existing_evaluation.stage_id,
            criterion_1=existing_evaluation.criterion_1,
            criterion_2=existing_evaluation.criterion_2,
            criterion_3=existing_evaluation.criterion_3,
            criterion_4=existing_evaluation.criterion_4,
            criterion_5=existing_evaluation.criterion_5,
            total_score=existing_evaluation.get_total_score(),
            created_at=existing_evaluation.created_at,
            updated_at=existing_evaluation.updated_at,
        )
    else:
        new_evaluation = TeamEvaluation(
            id=uuid.uuid4(),
            team_id=evaluation.team_id,
            judge_id=effective_judge_id,
            event_id=active_event.id,
            stage_id=current_stage_id,  # Сохраняем ID этапа, на котором выставлена оценка
            criterion_1=evaluation.criterion_1,
            criterion_2=evaluation.criterion_2,
            criterion_3=evaluation.criterion_3,
            criterion_4=evaluation.criterion_4,
            criterion_5=evaluation.criterion_5,
        )

        session.add(new_evaluation)
        await session.commit()
        await session.refresh(new_evaluation)

        # Инвалидируем кэш оценок
        await invalidate_evaluation_cache(
            event_id=str(active_event.id), team_id=str(evaluation.team_id)
        )

        return TeamEvaluationResponse(
            id=new_evaluation.id,
            team_id=new_evaluation.team_id,
            team_name=team.team_name,
            team_motto=team.team_motto,
            judge_id=new_evaluation.judge_id,
            stage_id=new_evaluation.stage_id,
            criterion_1=new_evaluation.criterion_1,
            criterion_2=new_evaluation.criterion_2,
            criterion_3=new_evaluation.criterion_3,
            criterion_4=new_evaluation.criterion_4,
            criterion_5=new_evaluation.criterion_5,
            total_score=new_evaluation.get_total_score(),
            created_at=new_evaluation.created_at,
            updated_at=new_evaluation.updated_at,
        )


@router.get("/team/{team_id}", response_model=List[TeamEvaluationResponse])
async def get_team_evaluations(
    team_id: str,
    stage_group: Optional[str] = Query(
        None,
        description="Группа этапа: 'remote' (заочный) или 'on_site' (очный). Если не указано, используется текущий активный этап",
    ),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Получение оценок команды, отфильтрованных по группе этапа (заочный/очный)"""
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_judge = any(
        role.role_id == user_router_state.judge_role_id for role in user_roles
    )
    is_admin = any(
        role.role_id == user_router_state.admin_role_id for role in user_roles
    )
    is_organizer = any(
        role.role_id == user_router_state.organizer_role_id for role in user_roles
    )

    if not (is_judge or is_admin or is_organizer):
        raise HTTPException(
            status_code=403,
            detail="Only judges, administrators and organizers can view evaluations",
        )

    active_event = await get_active_event(session)

    effective_group = stage_group
    if effective_group and effective_group not in ["remote", "on_site"]:
        raise HTTPException(
            status_code=400, detail="stage_group должен быть 'remote' или 'on_site'"
        )
    if not effective_group:
        effective_group = await get_current_stage_group(session)

    # Базовый запрос
    base_query = (
        select(TeamEvaluation)
        .options(selectinload(TeamEvaluation.team))
        .where(
            TeamEvaluation.team_id == team_id,
            TeamEvaluation.event_id == active_event.id,
        )
    )

    if effective_group:
        base_query = await filter_evaluations_by_stage_group(
            session, base_query, effective_group, str(active_event.id)
        )

    result = await session.execute(base_query)
    evaluations = result.scalars().all()

    evaluation_responses = [
        TeamEvaluationResponse(
            id=eval.id,
            team_id=eval.team_id,
            team_name=eval.team.team_name,
            team_motto=eval.team.team_motto,
            judge_id=eval.judge_id,
            stage_id=eval.stage_id,
            criterion_1=eval.criterion_1,
            criterion_2=eval.criterion_2,
            criterion_3=eval.criterion_3,
            criterion_4=eval.criterion_4,
            criterion_5=eval.criterion_5,
            created_at=eval.created_at,
            updated_at=eval.updated_at,
            total_score=eval.get_total_score(),
            solution_link=get_solution_link_for_stage_group(eval.team, effective_group),
        )
        for eval in evaluations
    ]

    evaluation_responses.sort(key=lambda x: x.total_score, reverse=True)

    return evaluation_responses


@router.get("/results", response_model=List[TeamTotalScore])
async def get_evaluation_results(
    stage_group: Optional[str] = Query(
        None,
        description="Группа этапа: 'remote' (заочный) или 'on_site' (очный). Если не указано, используется текущий активный этап",
    ),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Получение итоговых результатов всех команд, отфильтрованных по группе этапа"""
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_judge = any(
        role.role_id == user_router_state.judge_role_id for role in user_roles
    )
    is_admin = any(
        role.role_id == user_router_state.admin_role_id for role in user_roles
    )

    if not (is_judge or is_admin):
        raise HTTPException(
            status_code=403, detail="Only judges and administrators can view results"
        )

    active_event = await get_active_event(session)
    latest_evaluations = (
        select(TeamEvaluation.id)
        .distinct(TeamEvaluation.judge_id, TeamEvaluation.team_id)
        .where(TeamEvaluation.event_id == active_event.id)
        .order_by(
            TeamEvaluation.judge_id,
            TeamEvaluation.team_id,
            TeamEvaluation.created_at.desc(),
        )
    ).scalar_subquery()

    query = (
        select(
            Team.id.label("team_id"),
            Team.team_name.label("team_name"),
            Team.team_motto.label("team_motto"),
            func.avg(
                TeamEvaluation.criterion_1
                + TeamEvaluation.criterion_2
                + TeamEvaluation.criterion_3
                + TeamEvaluation.criterion_4
                + TeamEvaluation.criterion_5
            ).label("average_score"),
            func.count(TeamEvaluation.judge_id.distinct()).label("evaluations_count"),
            func.sum(
                TeamEvaluation.criterion_1
                + TeamEvaluation.criterion_2
                + TeamEvaluation.criterion_3
                + TeamEvaluation.criterion_4
                + TeamEvaluation.criterion_5
            ).label("total_score"),
        )
        .join(TeamEvaluation, Team.id == TeamEvaluation.team_id)
        .where(
            Team.event_id == active_event.id, TeamEvaluation.id.in_(latest_evaluations)
        )
        .group_by(Team.id, Team.team_name)
    )

    result = await session.execute(query)
    return result.all()


@router.get("/my-evaluations", response_model=List[TeamEvaluationResponse])
async def get_judge_evaluations(
    stage_group: Optional[str] = Query(
        None,
        description="Группа этапа: 'remote' (заочный) или 'on_site' (очный). Если не указано, используется текущий активный этап",
    ),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Получение оценок, выставленных текущим членом жюри, отфильтрованных по группе этапа"""
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_judge = any(
        role.role_id == user_router_state.judge_role_id for role in user_roles
    )

    if not is_judge:
        raise HTTPException(
            status_code=403, detail="Only judges can access this endpoint"
        )

    active_event = await get_active_event(session)

    # Определяем группу этапа для фильтрации
    target_stage_group = stage_group
    if not target_stage_group:
        # Если группа не указана, используем текущий активный этап
        current_group = await get_current_stage_group(session)
        target_stage_group = current_group

    # Если очный этап, получаем список финалистов для фильтрации
    finalist_ids = None
    if target_stage_group == "on_site":
        from src.utils.finalists_utils import get_top_finalists_by_scores

        # Получаем топ-4 финалистов на основе оценок заочного этапа
        finalist_teams = await get_top_finalists_by_scores(
            session, active_event.id, stage_group="remote", count=4
        )
        finalist_ids = [team.id for team in finalist_teams]

    # Базовый запрос
    base_query = (
        select(TeamEvaluation)
        .options(selectinload(TeamEvaluation.team))
        .where(
            TeamEvaluation.judge_id == current_user.id,
            TeamEvaluation.event_id == active_event.id,
        )
    )

    # Если указана группа этапа, фильтруем по ней
    if stage_group:
        if stage_group not in ["remote", "on_site"]:
            raise HTTPException(
                status_code=400, detail="stage_group должен быть 'remote' или 'on_site'"
            )
        base_query = await filter_evaluations_by_stage_group(
            session, base_query, stage_group, active_event.id
        )
    else:
        # Если группа не указана, используем текущий активный этап
        if target_stage_group:
            base_query = await filter_evaluations_by_stage_group(
                session, base_query, target_stage_group, active_event.id
            )

    result = await session.execute(base_query)
    evaluations = result.scalars().all()

    # Фильтруем только финалистов для очного этапа
    if finalist_ids is not None:
        evaluations = [eval for eval in evaluations if eval.team_id in finalist_ids]

    evaluation_responses = [
        TeamEvaluationResponse(
            id=eval.id,
            team_id=eval.team_id,
            team_name=eval.team.team_name,
            team_motto=eval.team.team_motto,
            judge_id=eval.judge_id,
            criterion_1=eval.criterion_1,
            criterion_2=eval.criterion_2,
            criterion_3=eval.criterion_3,
            criterion_4=eval.criterion_4,
            criterion_5=eval.criterion_5,
            created_at=eval.created_at,
            updated_at=eval.updated_at,
            total_score=eval.get_total_score(),
            solution_link=get_solution_link_for_stage_group(eval.team, target_stage_group),
        )
        for eval in evaluations
    ]

    evaluation_responses.sort(key=lambda x: x.total_score, reverse=True)

    return evaluation_responses


@router.get("/unevaluated-teams", response_model=List[UnevaluatedTeam])
async def get_unevaluated_teams(
    stage_group: Optional[str] = Query(
        None,
        description="Группа этапа: 'remote' (заочный) или 'on_site' (очный). Если не указано, используется текущий активный этап",
    ),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Получение списка команд, которые еще не были оценены текущим членом жюри, отфильтрованных по группе этапа"""
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_judge = any(
        role.role_id == user_router_state.judge_role_id for role in user_roles
    )

    is_admin = any(
        role.role_id == user_router_state.admin_role_id for role in user_roles
    )

    if not is_judge and not is_admin:
        raise HTTPException(
            status_code=403, detail="Only judges can access this endpoint"
        )

    active_event = await get_active_event(session)

    # Определяем группу этапа для фильтрации
    target_stage_group = stage_group
    if not target_stage_group:
        # Если группа не указана, используем текущий активный этап
        from src.utils.evaluation_utils import get_current_stage_group

        target_stage_group = await get_current_stage_group(session)

    # Если очный этап, показываем только финалистов
    if target_stage_group == "on_site":
        from src.utils.finalists_utils import get_top_finalists_by_scores

        # Получаем топ-4 финалистов на основе оценок заочного этапа
        finalist_teams = await get_top_finalists_by_scores(
            session, active_event.id, stage_group="remote", count=4
        )
        finalist_ids = [team.id for team in finalist_teams]

        # Получаем этапы очной группы для фильтрации оценок
        from src.utils.evaluation_utils import get_stages_by_group

        on_site_stages = await get_stages_by_group(session, "on_site", active_event.id)
        on_site_stage_ids = [stage.id for stage in on_site_stages]

        evaluated_teams_subquery = (
            select(TeamEvaluation.team_id)
            .options(selectinload(TeamEvaluation.team))
            .where(
                TeamEvaluation.judge_id == current_user.id,
                TeamEvaluation.event_id == active_event.id,
            )
        )

        # Фильтруем оценки только по очным этапам
        if on_site_stage_ids:
            evaluated_teams_subquery = evaluated_teams_subquery.where(
                TeamEvaluation.stage_id.in_(on_site_stage_ids)
            )

        evaluated_teams_subquery = evaluated_teams_subquery.scalar_subquery()

        query = (
            select(Team)
            .options(
                selectinload(Team.members)
                .selectinload(TeamMember.user)
                .selectinload(User.current_status),
                selectinload(Team.members).selectinload(TeamMember.role),
                selectinload(Team.members).selectinload(TeamMember.status),
            )
            .where(
                Team.event_id == active_event.id,
                Team.id.notin_(evaluated_teams_subquery),
                Team.id.in_(finalist_ids),
            )
        )
    else:
        # Для заочного этапа получаем этапы заочной группы для фильтрации оценок
        from src.utils.evaluation_utils import get_stages_by_group

        remote_stages = await get_stages_by_group(session, "remote", active_event.id)
        remote_stage_ids = [stage.id for stage in remote_stages]

        evaluated_teams_subquery = (
            select(TeamEvaluation.team_id)
            .options(selectinload(TeamEvaluation.team))
            .where(
                TeamEvaluation.judge_id == current_user.id,
                TeamEvaluation.event_id == active_event.id,
            )
        )

        # Фильтруем оценки только по заочным этапам
        if remote_stage_ids:
            evaluated_teams_subquery = evaluated_teams_subquery.where(
                TeamEvaluation.stage_id.in_(remote_stage_ids)
            )

        evaluated_teams_subquery = evaluated_teams_subquery.scalar_subquery()

        query = (
            select(Team)
            .options(
                selectinload(Team.members)
                .selectinload(TeamMember.user)
                .selectinload(User.current_status),
                selectinload(Team.members).selectinload(TeamMember.role),
                selectinload(Team.members).selectinload(TeamMember.status),
            )
            .where(
                Team.event_id == active_event.id,
                Team.id.notin_(evaluated_teams_subquery),
            )
        )

    result = await session.execute(query)
    teams = result.scalars().all()

    # Для очного этапа не применяем фильтр can_participate(), так как финалисты уже отфильтрованы
    # Для заочного этапа применяем фильтр can_participate()
    if target_stage_group == "on_site":
        participating_teams = [
            UnevaluatedTeam(
                team_id=team.id,
                team_name=team.team_name,
                team_motto=team.team_motto,
                solution_link=get_solution_link_for_stage_group(team, target_stage_group),
            )
            for team in teams
        ]
    else:
        participating_teams = [
            UnevaluatedTeam(
                team_id=team.id,
                team_name=team.team_name,
                team_motto=team.team_motto,
                solution_link=get_solution_link_for_stage_group(team, target_stage_group),
            )
            for team in teams
            if team.can_participate()
        ]

    return participating_teams


@router.get("/detailed", response_model=List[DetailedTeamEvaluationResponse])
async def get_detailed_evaluations(
    stage_group: Optional[str] = Query(
        None,
        description="Группа этапа: 'remote' (заочный) или 'on_site' (очный). Если не указано, используется текущий активный этап",
    ),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """
    Получение детальной информации об оценках всех команд всеми судьями.
    Доступно только для администраторов и организаторов.
    """
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_admin = any(
        role.role_id == user_router_state.admin_role_id for role in user_roles
    )
    is_organizer = any(
        role.role_id == user_router_state.organizer_role_id for role in user_roles
    )

    if not (is_admin or is_organizer):
        raise HTTPException(
            status_code=403,
            detail="Only administrators and organizers can view detailed evaluations",
        )

    active_event = await get_active_event(session)

    # Определяем группу этапа для фильтрации
    target_stage_group = stage_group
    if not target_stage_group:
        # Если группа не указана, используем текущий активный этап
        target_stage_group = await get_current_stage_group(session)

        # Если текущий этап - публикация результатов, определяем последнюю группу этапа с оценками
        if not target_stage_group:
            # Проверяем, является ли текущий этап публикацией результатов
            current_stage_query = select(Stage).where(
                and_(Stage.is_active == True, Stage.event_id == active_event.id)
            )
            current_stage_result = await session.execute(current_stage_query)
            current_stage = current_stage_result.scalar_one_or_none()

            if (
                current_stage
                and current_stage.type == StageType.RESULTS_PUBLICATION.value
            ):
                # Проверяем, есть ли оценки для очного этапа
                on_site_stages = await get_stages_by_group(
                    session, "on_site", active_event.id
                )
                on_site_stage_ids = [stage.id for stage in on_site_stages]

                if on_site_stage_ids:
                    on_site_evaluations_query = select(TeamEvaluation).where(
                        and_(
                            TeamEvaluation.event_id == active_event.id,
                            TeamEvaluation.stage_id.in_(on_site_stage_ids),
                        )
                    )
                    on_site_evaluations_result = await session.execute(
                        on_site_evaluations_query
                    )
                    on_site_evaluations = on_site_evaluations_result.scalars().all()

                    # Если есть оценки для очного этапа, используем их
                    if on_site_evaluations:
                        target_stage_group = "on_site"
                    else:
                        # Иначе используем заочный этап
                        target_stage_group = "remote"
                else:
                    # Если нет очных этапов, используем заочный
                    target_stage_group = "remote"
            else:
                # Если нет активного этапа с группой, используем заочный по умолчанию
                target_stage_group = "remote"

    # Если очный этап, показываем только финалистов
    if target_stage_group == "on_site":
        from src.utils.finalists_utils import get_top_finalists_by_scores

        # Получаем топ-4 финалистов на основе оценок заочного этапа
        finalist_teams = await get_top_finalists_by_scores(
            session, active_event.id, stage_group="remote", count=4
        )
        # Фильтруем только финалистов
        finalist_ids = [team.id for team in finalist_teams]
        teams_query = (
            select(Team)
            .options(
                selectinload(Team.members)
                .selectinload(TeamMember.user)
                .selectinload(User.current_status),
                selectinload(Team.members).selectinload(TeamMember.role),
                selectinload(Team.members).selectinload(TeamMember.status),
            )
            .where(Team.event_id == active_event.id, Team.id.in_(finalist_ids))
        )
    else:
        teams_query = (
            select(Team)
            .options(
                selectinload(Team.members)
                .selectinload(TeamMember.user)
                .selectinload(User.current_status),
                selectinload(Team.members).selectinload(TeamMember.role),
                selectinload(Team.members).selectinload(TeamMember.status),
            )
            .where(Team.event_id == active_event.id)
        )
    teams = await session.execute(teams_query)
    teams = teams.scalars().all()

    # Получаем жюри, привязанные к текущему событию
    judges_query = (
        select(User)
        .join(EventJudge, User.id == EventJudge.judge_id)
        .where(EventJudge.event_id == active_event.id)
    )
    judges = await session.execute(judges_query)
    judges = judges.scalars().all()

    evaluations_query = (
        select(TeamEvaluation)
        .options(selectinload(TeamEvaluation.judge), selectinload(TeamEvaluation.team))
        .where(TeamEvaluation.event_id == active_event.id)
    )

    # Фильтруем оценки по определенной группе этапа
    if target_stage_group:
        evaluations_query = await filter_evaluations_by_stage_group(
            session, evaluations_query, target_stage_group, active_event.id
        )

    evaluations = await session.execute(evaluations_query)
    evaluations = evaluations.scalars().all()

    evaluation_map = {}
    for eval in evaluations:
        key = (str(eval.team_id), str(eval.judge_id))
        if (
            key not in evaluation_map
            or eval.created_at > evaluation_map[key].created_at
        ):
            evaluation_map[key] = eval

    detailed_evaluations = []
    for team in teams:
        # Для заочного этапа показываем только активные команды (can_participate())
        # Для очного этапа показываем всех финалистов, даже если они не проходят can_participate()
        if target_stage_group == "on_site" or team.can_participate():
            team_evaluations = []
            team_total_score = 0
            evaluations_count = 0

            for judge in judges:
                key = (str(team.id), str(judge.id))
                evaluation = evaluation_map.get(key)

                if evaluation:
                    evaluations_count += 1
                    score = evaluation.get_total_score()
                    team_total_score += score
                    team_evaluations.append(
                        {
                            "judge_id": judge.id,
                            "judge_name": judge.full_name,
                            "judge_email": judge.email,
                            "criterion_1": evaluation.criterion_1,
                            "criterion_2": evaluation.criterion_2,
                            "criterion_3": evaluation.criterion_3,
                            "criterion_4": evaluation.criterion_4,
                            "criterion_5": evaluation.criterion_5,
                            "total_score": score,
                            "created_at": evaluation.created_at,
                            "updated_at": evaluation.updated_at,
                        }
                    )
                else:
                    team_evaluations.append(
                        {
                            "judge_id": judge.id,
                            "judge_name": judge.full_name,
                            "judge_email": judge.email,
                            "criterion_1": None,
                            "criterion_2": None,
                            "criterion_3": None,
                            "criterion_4": None,
                            "criterion_5": None,
                            "total_score": None,
                            "created_at": None,
                            "updated_at": None,
                        }
                    )

            detailed_evaluations.append(
                {
                    "team_id": team.id,
                    "team_name": team.team_name,
                    "team_motto": team.team_motto,
                    "solution_link": get_solution_link_for_stage_group(
                        team, target_stage_group
                    ),
                    "evaluations_count": evaluations_count,
                    "total_score": team_total_score,
                    "evaluations": team_evaluations,
                }
            )

    detailed_evaluations.sort(key=lambda x: x["total_score"], reverse=True)

    return detailed_evaluations


@router.get("/public-results", response_model=List[TeamTotalScore])
async def get_public_evaluation_results(
    stage_group: Optional[str] = Query(
        None,
        description="Группа этапа: 'remote' (заочный) или 'on_site' (очный). Если не указано, используется текущий активный этап",
    ),
    session: AsyncSession = Depends(get_session),
):
    """Публичные итоги по группе этапа. Для очного этапа и публикации победителей — только финалисты."""
    active_event = await get_active_event(session)

    current_stage_query = select(Stage).where(
        and_(Stage.is_active == True, Stage.event_id == active_event.id)
    )
    current_stage = (await session.execute(current_stage_query)).scalar_one_or_none()
    is_results_stage = bool(
        current_stage
        and current_stage.type
        in (
            StageType.RESULTS_PUBLICATION.value,
            StageType.AWARD_CEREMONY.value,
        )
    )

    # Определяем группу этапа для фильтрации
    if stage_group:
        if stage_group not in ["remote", "on_site"]:
            raise HTTPException(
                status_code=400, detail="stage_group должен быть 'remote' или 'on_site'"
            )
        target_group = stage_group
    else:
        target_group = await get_current_stage_group(session)
        # Победители хакатона — только по оценкам очного этапа, без отката на заочный рейтинг
        if not target_group:
            if is_results_stage:
                target_group = "on_site"
            else:
                return []

    # Получаем этапы указанной группы
    stages = await get_stages_by_group(session, target_group, active_event.id)
    stage_ids = [stage.id for stage in stages]

    if not stage_ids:
        # Если нет этапов этой группы, возвращаем пустой список
        return []

    latest_evaluations = (
        select(TeamEvaluation.id)
        .distinct(TeamEvaluation.judge_id, TeamEvaluation.team_id)
        .where(
            TeamEvaluation.event_id == active_event.id,
            TeamEvaluation.stage_id.in_(stage_ids),
        )
        .order_by(
            TeamEvaluation.judge_id,
            TeamEvaluation.team_id,
            TeamEvaluation.created_at.desc(),
        )
    ).scalar_subquery()

    query = (
        select(
            Team.id.label("team_id"),
            Team.team_name.label("team_name"),
            Team.team_motto.label("team_motto"),
            func.avg(
                TeamEvaluation.criterion_1
                + TeamEvaluation.criterion_2
                + TeamEvaluation.criterion_3
                + TeamEvaluation.criterion_4
                + TeamEvaluation.criterion_5
            ).label("average_score"),
            func.count(TeamEvaluation.judge_id.distinct()).label("evaluations_count"),
            func.sum(
                TeamEvaluation.criterion_1
                + TeamEvaluation.criterion_2
                + TeamEvaluation.criterion_3
                + TeamEvaluation.criterion_4
                + TeamEvaluation.criterion_5
            ).label("total_score"),
        )
        .join(TeamEvaluation, Team.id == TeamEvaluation.team_id)
        .where(
            Team.event_id == active_event.id, TeamEvaluation.id.in_(latest_evaluations)
        )
        .group_by(Team.id, Team.team_name)
    )

    # Очный рейтинг и публикация победителей — только финалисты
    if target_group == "on_site":
        from src.utils.finalists_utils import get_effective_finalist_ids

        finalist_ids = await get_effective_finalist_ids(session, active_event.id)
        if not finalist_ids:
            return []
        query = query.where(Team.id.in_(finalist_ids))

    result = await session.execute(query)
    return result.all()


