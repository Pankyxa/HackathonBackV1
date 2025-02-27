from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import UUID

from src.models.enums import StageType


class StageBase(BaseModel):
    name: str
    order: int
    is_active: bool
    type: str


class StageResponse(BaseModel):
    id: UUID
    name: str
    type: StageType
    order: int
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class StageActivationResponse(BaseModel):
    message: str
    previous_stage: StageResponse
    new_stage: StageResponse

    class Config:
        orm_mode = True