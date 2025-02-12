from pydantic import BaseModel, constr
from uuid import UUID
from src.models.enums import TeamRole

class TeamCreate(BaseModel):
    team_name: constr(min_length=1, max_length=255)

class TeamResponse(BaseModel):
    id: UUID
    team_name: str
    team_leader_id: UUID

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

    class Config:
        from_attributes = True