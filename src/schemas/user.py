import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, EmailStr

from src.models import UserStatus
from src.schemas.enum_tables import RoleResponse
from src.schemas.file import FileResponse
from src.schemas.mentor_info import MentorInfoResponse
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


class MentorCreate(UserBase):
    password: str
    full_name: str
    number: str
    job: str
    job_title: str


class UserLogin(UserBase):
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str


class UserStatusResponse(BaseModel):
    """Схема ответа для статуса пользователя"""
    id: UUID
    name: str
    description: Optional[str] = None

    class Config:
        from_attributes = True


class UserResponse(BaseModel):
    id: UUID
    email: str
    full_name: str
    registered_at: datetime.datetime
    participant_info: Optional[ParticipantInfoResponse] = None
    mentor_info: Optional[MentorInfoResponse] = None
    roles: List[RoleResponse] = []
    current_status: UserStatusResponse
    status_history: List["UserStatusHistoryResponse"] = []

    class Config:
        from_attributes = True


class UserResponseRegister(UserResponse):
    files: List[FileResponse] = []


class UserStatusHistoryResponse(BaseModel):
    id: UUID
    status: UserStatusResponse
    comment: Optional[str]
    created_at: datetime.datetime

    class Config:
        from_attributes = True

class PaginatedUserResponse(BaseModel):
    users: List[UserResponse]
    total: int

class ChangeUserStatusRequest(BaseModel):
    status: UserStatus
    comment: Optional[str] = None
