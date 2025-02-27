from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from src.auth.jwt import get_current_user
from src.db import get_session
from src.models.user import User
from src.models.team import Team
from src.models.evaluation import TeamEvaluation
from src.schemas.evaluation import (
    TeamEvaluationCreate,
    TeamEvaluationResponse,
    TeamTotalScore, UnevaluatedTeam
)

router = APIRouter(
    prefix="/evaluations",
    tags=["evaluations"]
)


@router.post("/", response_model=TeamEvaluationResponse)
async def create_evaluation(
        evaluation: TeamEvaluationCreate,
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Создание оценки команды членом жюри"""
    if not current_user.role.name == "judge":
        raise HTTPException(status_code=403, detail="Only judges can evaluate teams")

    team = await session.execute(
        select(Team).where(Team.id == evaluation.team_id)
    )
    team = team.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    existing_evaluation = await session.execute(
        select(TeamEvaluation).where(
            TeamEvaluation.team_id == evaluation.team_id,
            TeamEvaluation.judge_id == current_user.id
        )
    )
    if existing_evaluation.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail="You have already evaluated this team"
        )

    db_evaluation = TeamEvaluation(
        team_id=evaluation.team_id,
        judge_id=current_user.id,
        criterion_1=evaluation.criterion_1,
        criterion_2=evaluation.criterion_2,
        criterion_3=evaluation.criterion_3,
        criterion_4=evaluation.criterion_4,
        criterion_5=evaluation.criterion_5
    )

    session.add(db_evaluation)
    await session.commit()
    await session.refresh(db_evaluation)

    response_data = TeamEvaluationResponse(
        id=db_evaluation.id,
        team_id=db_evaluation.team_id,
        judge_id=db_evaluation.judge_id,
        criterion_1=db_evaluation.criterion_1,
        criterion_2=db_evaluation.criterion_2,
        criterion_3=db_evaluation.criterion_3,
        criterion_4=db_evaluation.criterion_4,
        criterion_5=db_evaluation.criterion_5,
        created_at=db_evaluation.created_at,
        updated_at=db_evaluation.updated_at,
        total_score=db_evaluation.get_total_score()
    )
    return response_data


@router.get("/team/{team_id}", response_model=List[TeamEvaluationResponse])
async def get_team_evaluations(
        team_id: str,
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Получение всех оценок команды"""
    if not (current_user.role.name in ["judge", "admin"]):
        raise HTTPException(
            status_code=403,
            detail="Only judges and administrators can view evaluations"
        )

    result = await session.execute(
        select(TeamEvaluation).where(TeamEvaluation.team_id == team_id)
    )
    evaluations = result.scalars().all()

    return [
        TeamEvaluationResponse(
            id=eval.id,
            team_id=eval.team_id,
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


@router.get("/results", response_model=List[TeamTotalScore])
async def get_evaluation_results(
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Получение итоговых результатов всех команд"""
    if not (current_user.role.name in ["judge", "admin"]):
        raise HTTPException(
            status_code=403,
            detail="Only judges and administrators can view results"
        )

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
        func.count(TeamEvaluation.id).label('evaluations_count'),
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
    if not current_user.role.name == "judge":
        raise HTTPException(status_code=403, detail="Only judges can access their evaluations")

    result = await session.execute(
        select(TeamEvaluation).where(TeamEvaluation.judge_id == current_user.id)
    )
    evaluations = result.scalars().all()

    return [
        TeamEvaluationResponse(
            id=eval.id,
            team_id=eval.team_id,
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


@router.get("/unevaluated-teams", response_model=List[UnevaluatedTeam])
async def get_unevaluated_teams(
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Получение списка команд, которые еще не были оценены текущим членом жюри"""
    if not current_user.role.name == "judge":
        raise HTTPException(status_code=403, detail="Only judges can access this endpoint")

    evaluated_teams_subquery = select(TeamEvaluation.team_id).where(
        TeamEvaluation.judge_id == current_user.id
    ).scalar_subquery()

    query = (
        select(Team)
        .where(Team.id.not_in(evaluated_teams_subquery))
    )

    result = await session.execute(query)
    teams = result.scalars().all()

    participating_teams = [
        UnevaluatedTeam(
            id=team.id,
            team_name=team.team_name,
            team_motto=team.team_motto
        )
        for team in teams
        if team.can_participate()
    ]

    return participating_teams
