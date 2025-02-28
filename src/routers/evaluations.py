import uuid
from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from src.auth.jwt import get_current_user
from src.db import get_session
from src.models.user import User, User2Roles
from src.models.team import Team, TeamMember
from src.models.evaluation import TeamEvaluation
from src.schemas.evaluation import (
    TeamEvaluationCreate,
    TeamEvaluationResponse,
    TeamTotalScore, UnevaluatedTeam
)
from src.utils.router_states import user_router_state  # Добавляем импорт state

router = APIRouter(
    prefix="/evaluations",
    tags=["evaluations"]
)


@router.post("/evaluate-team", response_model=TeamEvaluationResponse)
async def create_evaluation(
        evaluation: TeamEvaluationCreate,
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Создание оценки команды членом жюри"""
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_judge = any(
        role.role_id == user_router_state.judge_role_id
        for role in user_roles
    )

    if not is_judge:
        raise HTTPException(status_code=403, detail="Only judges can evaluate teams")

    team_query = (
        select(Team)
        .where(Team.id == evaluation.team_id)
    )
    team = await session.execute(team_query)
    team = team.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Команда не найдена"
        )

    existing_evaluation_query = (
        select(TeamEvaluation)
        .where(
            TeamEvaluation.team_id == evaluation.team_id,
            TeamEvaluation.judge_id == current_user.id
        )
    )
    existing_evaluation = await session.execute(existing_evaluation_query)
    existing_evaluation = existing_evaluation.scalar_one_or_none()

    if existing_evaluation:
        existing_evaluation.criterion_1 = evaluation.criterion_1
        existing_evaluation.criterion_2 = evaluation.criterion_2
        existing_evaluation.criterion_3 = evaluation.criterion_3
        existing_evaluation.criterion_4 = evaluation.criterion_4
        existing_evaluation.criterion_5 = evaluation.criterion_5
        existing_evaluation.updated_at = datetime.utcnow()
        await session.commit()

        return TeamEvaluationResponse(
            id=existing_evaluation.id,
            team_id=existing_evaluation.team_id,
            team_name=team.team_name,
            team_motto=team.team_motto,
            judge_id=existing_evaluation.judge_id,
            criterion_1=existing_evaluation.criterion_1,
            criterion_2=existing_evaluation.criterion_2,
            criterion_3=existing_evaluation.criterion_3,
            criterion_4=existing_evaluation.criterion_4,
            criterion_5=existing_evaluation.criterion_5,
            total_score=existing_evaluation.get_total_score(),
            created_at=existing_evaluation.created_at,
            updated_at=existing_evaluation.updated_at
        )
    else:
        new_evaluation = TeamEvaluation(
            id=uuid.uuid4(),
            team_id=evaluation.team_id,
            judge_id=current_user.id,
            criterion_1=evaluation.criterion_1,
            criterion_2=evaluation.criterion_2,
            criterion_3=evaluation.criterion_3,
            criterion_4=evaluation.criterion_4,
            criterion_5=evaluation.criterion_5
        )

        session.add(new_evaluation)
        await session.commit()
        await session.refresh(new_evaluation)

        return TeamEvaluationResponse(
            id=new_evaluation.id,
            team_id=new_evaluation.team_id,
            team_name=team.team_name,
            team_motto=team.team_motto,
            judge_id=new_evaluation.judge_id,
            criterion_1=new_evaluation.criterion_1,
            criterion_2=new_evaluation.criterion_2,
            criterion_3=new_evaluation.criterion_3,
            criterion_4=new_evaluation.criterion_4,
            criterion_5=new_evaluation.criterion_5,
            total_score=new_evaluation.get_total_score(),
            created_at=new_evaluation.created_at,
            updated_at=new_evaluation.updated_at
        )


@router.get("/team/{team_id}", response_model=List[TeamEvaluationResponse])
async def get_team_evaluations(
        team_id: str,
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Получение всех оценок команды"""
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_judge = any(
        role.role_id == user_router_state.judge_role_id
        for role in user_roles
    )
    is_admin = any(
        role.role_id == user_router_state.admin_role_id
        for role in user_roles
    )

    if not (is_judge or is_admin):
        raise HTTPException(
            status_code=403,
            detail="Only judges and administrators can view evaluations"
        )

    result = await session.execute(
        select(TeamEvaluation)
        .options(selectinload(TeamEvaluation.team))
        .where(TeamEvaluation.team_id == team_id)
    )
    evaluations = result.scalars().all()

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
            total_score=eval.get_total_score()
        )
        for eval in evaluations
    ]

    evaluation_responses.sort(key=lambda x: x.total_score, reverse=True)

    return evaluation_responses


@router.get("/results", response_model=List[TeamTotalScore])
async def get_evaluation_results(
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Получение итоговых результатов всех команд"""
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_judge = any(
        role.role_id == user_router_state.judge_role_id
        for role in user_roles
    )
    is_admin = any(
        role.role_id == user_router_state.admin_role_id
        for role in user_roles
    )

    if not (is_judge or is_admin):
        raise HTTPException(
            status_code=403,
            detail="Only judges and administrators can view results"
        )

    latest_evaluations = (
        select(TeamEvaluation.id)
        .distinct(TeamEvaluation.judge_id, TeamEvaluation.team_id)
        .order_by(
            TeamEvaluation.judge_id,
            TeamEvaluation.team_id,
            TeamEvaluation.created_at.desc()
        )
    ).scalar_subquery()

    query = select(
        Team.id.label('team_id'),
        Team.team_name.label('team_name'),
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
        TeamEvaluation.id.in_(latest_evaluations)
    ).group_by(
        Team.id,
        Team.team_name
    )

    result = await session.execute(query)
    return result.all()


@router.get("/my-evaluations", response_model=List[TeamEvaluationResponse])
async def get_judge_evaluations(
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Получение всех оценок, выставленных текущим членом жюри"""
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_judge = any(
        role.role_id == user_router_state.judge_role_id
        for role in user_roles
    )

    if not is_judge:
        raise HTTPException(status_code=403, detail="Only judges can access this endpoint")

    result = await session.execute(
        select(TeamEvaluation)
        .options(selectinload(TeamEvaluation.team))
        .where(TeamEvaluation.judge_id == current_user.id)
    )
    evaluations = result.scalars().all()

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
            total_score=eval.get_total_score()
        )
        for eval in evaluations
    ]

    evaluation_responses.sort(key=lambda x: x.total_score, reverse=True)

    return evaluation_responses


@router.get("/unevaluated-teams", response_model=List[UnevaluatedTeam])
async def get_unevaluated_teams(
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Получение списка команд, которые еще не были оценены текущим членом жюри"""
    user_roles_query = select(User2Roles).where(User2Roles.user_id == current_user.id)
    user_roles = await session.execute(user_roles_query)
    user_roles = user_roles.scalars().all()

    is_judge = any(
        role.role_id == user_router_state.judge_role_id
        for role in user_roles
    )

    if not is_judge:
        raise HTTPException(status_code=403, detail="Only judges can access this endpoint")

    evaluated_teams_subquery = (
        select(TeamEvaluation.team_id)
        .options(selectinload(TeamEvaluation.team))
        .where(TeamEvaluation.judge_id == current_user.id)
        .scalar_subquery()
    )

    query = (
        select(Team)
        .options(
            selectinload(Team.members)
            .selectinload(TeamMember.user)
            .selectinload(User.current_status),
            selectinload(Team.members)
            .selectinload(TeamMember.role),
            selectinload(Team.members)
            .selectinload(TeamMember.status)
        )
        .where(Team.id.notin_(evaluated_teams_subquery))
    )
    result = await session.execute(query)
    teams = result.scalars().all()

    participating_teams = [
        UnevaluatedTeam(
            team_id=team.id,
            team_name=team.team_name,
            team_motto=team.team_motto
        )
        for team in teams
        if team.can_participate()
    ]

    return participating_teams
