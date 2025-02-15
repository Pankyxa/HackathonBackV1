from uuid import UUID
from pydantic import BaseModel


class ParticipantInfoBase(BaseModel):
    number: str
    vuz: str
    vuz_direction: str
    code_speciality: str
    course: str


class ParticipantInfoCreate(ParticipantInfoBase):
    pass


class ParticipantInfoResponse(ParticipantInfoBase):
    id: UUID
    user_id: UUID

    class Config:
        from_attributes = True