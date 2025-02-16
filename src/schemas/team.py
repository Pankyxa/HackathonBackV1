from __future__ import annotations

import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, constr

from src.models import TeamRole
from src.models.enums import TeamMemberStatus
from src.schemas.user import UserResponse

class TeamCreate(BaseModel):
    team_name: constr(min_length=1, max_length=255)
    team_name: str
    member_ids: List[UUID]

class TeamResponse(BaseModel):
    id: UUID
    team_name: str
    team_motto: str
    team_leader_id: UUID
    logo_file_id: UUID | None

    class Config:
        from_attributes = True

class TeamMemberCreate(BaseModel):
    user_id: UUID
    role: TeamRole

class TeamMemberResponse(BaseModel):
    id: UUID
    team_id: UUID
    user_id: UUID
    role: TeamRole
    status: TeamMemberStatus
    created_at: datetime.datetime
    updated_at: datetime.datetime | None

    class Config:
        from_attributes = True

class TeamMemberDetailResponse(BaseModel):
    id: UUID
    user: UserResponse
    role: TeamRole
    status: TeamMemberStatus
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
