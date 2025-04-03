from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field


class TeamEvaluationBase(BaseModel):
    """Базовая схема оценки команды"""
    criterion_1: int = Field(..., ge=0, le=10, description="Соответствие результата поставленной задаче")
    criterion_2: int = Field(..., ge=0, le=10, description="Корректность, оригинальность и инновационность")
    criterion_3: int = Field(..., ge=0, le=10, description="Проработанность технического решения")
    criterion_4: int = Field(..., ge=0, le=10, description="Эффективность предложенного решения")
    criterion_5: int = Field(..., ge=0, le=10, description="Качество выступления")


class TeamEvaluationCreate(TeamEvaluationBase):
    team_id: UUID


class TeamEvaluationResponse(TeamEvaluationBase):
    id: UUID
    team_id: UUID
    team_name: str
    team_motto: str
    judge_id: UUID
    created_at: datetime
    updated_at: Optional[datetime]
    total_score: int
    solution_link: Optional[str] = None

    class Config:
        from_attributes = True


class TeamTotalScore(BaseModel):
    """Схема для отображения итоговых результатов команды"""
    team_id: UUID
    team_name: str
    average_score: float
    evaluations_count: int
    total_score: float

    class Config:
        from_attributes = True


class UnevaluatedTeam(BaseModel):
    team_id: UUID
    team_name: str
    team_motto: str
