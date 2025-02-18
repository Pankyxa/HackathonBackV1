from uuid import UUID
from typing import Optional
from pydantic import BaseModel


class TeamRoleResponse(BaseModel):
    """Схема для ответа с ролью в команде"""
    id: UUID
    name: str  # teamlead, member, mentor
    description: Optional[str] = None

    class Config:
        from_attributes = True


class TeamMemberStatusResponse(BaseModel):
    """Схема для ответа со статусом участника команды"""
    id: UUID
    name: str  # pending, accepted, rejected
    description: Optional[str] = None

    class Config:
        from_attributes = True


class RoleResponse(BaseModel):
    """Схема для ответа с ролью пользователя"""
    id: UUID
    name: str  # member, mentor, teamlead, admin
    description: Optional[str] = None

    class Config:
        from_attributes = True