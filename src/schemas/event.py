from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel


class EventCreate(BaseModel):
    """Схема для создания события"""
    name: str
    description: Optional[str] = None
    copy_stages_from_event_id: Optional[UUID] = None  # ID события, из которого копировать этапы


class EventUpdate(BaseModel):
    """Схема для обновления события"""
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class EventResponse(BaseModel):
    """Схема ответа для события"""
    id: UUID
    name: str
    description: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class EventStatistics(BaseModel):
    """Статистика по событию"""
    event_id: UUID
    event_name: str
    total_teams: int
    active_teams: int
    total_participants: int
    total_mentors: int
    total_evaluations: int
    teams_with_solutions: int
    created_at: datetime


class EventDetailResponse(EventResponse):
    """Детальная информация о событии со статистикой"""
    statistics: EventStatistics


class JudgeResponse(BaseModel):
    """Схема ответа для жюри"""
    id: UUID
    full_name: str
    email: str
    created_at: datetime

    class Config:
        from_attributes = True


class EventJudgesResponse(BaseModel):
    """Список жюри события"""
    event_id: UUID
    judges: List[JudgeResponse]
