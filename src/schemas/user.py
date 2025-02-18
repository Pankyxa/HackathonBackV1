import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, EmailStr

from src.schemas.enum_tables import RoleResponse
from src.schemas.file import FileResponse
from src.schemas.participant_info import ParticipantInfoResponse


class UserBase(BaseModel):
    email: EmailStr


class UserCreate(UserBase):
    password: str
    full_name: Optional[str] = None
    number: str
    vuz: str
    vuz_direction: str
    code_speciality: str
    course: str


class UserLogin(UserBase):
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str


class UserResponse(BaseModel):
    id: UUID
    email: str
    full_name: str
    registered_at: datetime.datetime
    participant_info: Optional[ParticipantInfoResponse] = None
    roles: List[RoleResponse] = []

    class Config:
        from_attributes = True


class UserResponseRegister(UserResponse):
    files: List[FileResponse] = []
