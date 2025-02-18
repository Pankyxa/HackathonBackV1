from __future__ import annotations

import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, constr

from src.models import TeamRole
from src.models.enums import TeamMemberStatus
from src.schemas.enum_tables import TeamRoleResponse, TeamMemberStatusResponse
from src.schemas.user import UserResponse


class TeamCreate(BaseModel):
    team_name: constr(min_length=1, max_length=255)
    team_name: str
    member_ids: List[UUID]


class TeamStatusDetails(BaseModel):
    """Схема для деталей статуса команды"""
    status: str
    can_participate: bool
    total_members: int
    regular_members_count: int
    has_mentor: bool
    mentor_status: Optional[str]
    has_team_leader: bool
    team_leader_status: Optional[str]
    members_status: dict

    class Config:
        from_attributes = True


class TeamResponse(BaseModel):
    id: UUID
    team_name: str
    team_motto: str
    team_leader_id: UUID
    logo_file_id: UUID | None
    status_details: TeamStatusDetails

    @property
    def get_status_details(self) -> TeamStatusDetails:
        """Получение деталей статуса из модели"""
        if hasattr(self, '_root'):
            return TeamStatusDetails.model_validate(self._root.get_status_details())
        return None

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "id": "123e4567-e89b-12d3-a456-426614174000",
                    "team_name": "Dream Team",
                    "team_motto": "Together we achieve more",
                    "team_leader_id": "123e4567-e89b-12d3-a456-426614174001",
                    "logo_file_id": "123e4567-e89b-12d3-a456-426614174002",
                    "status_details": {
                        "status": "active",
                        "can_participate": True,
                        "total_members": 6,
                        "regular_members_count": 4,
                        "has_mentor": True,
                        "mentor_status": "approved",
                        "has_team_leader": True,
                        "team_leader_status": "approved",
                        "members_status": {
                            "approved": 4,
                            "pending": 0,
                            "need_update": 0
                        }
                    }
                }
            ]
        }
    }

class TeamMemberCreate(BaseModel):
    user_id: UUID
    role: TeamRole


class TeamMemberResponse(BaseModel):
    id: UUID
    team_id: UUID
    user_id: UUID
    role: TeamRoleResponse
    status: TeamMemberStatusResponse
    created_at: datetime.datetime
    updated_at: datetime.datetime | None

    class Config:
        from_attributes = True


class TeamMemberDetailResponse(BaseModel):
    id: UUID
    user: UserResponse
    role: str
    status: str
    created_at: datetime.datetime
    updated_at: Optional[datetime.datetime] = None

    class Config:
        from_attributes = True


class TeamMembersResponse(BaseModel):
    team_id: UUID
    team_name: str
    team_motto: str
    team_leader_id: UUID
    logo_file_id: Optional[UUID] = None
    members: List[TeamMemberDetailResponse]

    class Config:
        from_attributes = True


class TeamInvitationResponse(BaseModel):
    team: TeamResponse
    member: TeamMemberResponse

    class Config:
        from_attributes = True
