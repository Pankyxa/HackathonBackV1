import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, EmailStr
from .file import FileResponse

class UserBase(BaseModel):
    email: EmailStr

class UserCreate(UserBase):
    password: str
    number: str
    vuz: str
    vuz_direction: str
    code_speciality: str
    course: str
    full_name: Optional[str] = None

class UserLogin(UserBase):
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class UserResponse(BaseModel):
    id: UUID
    email: str
    full_name: str
    number: str
    vuz: str
    vuz_direction: str
    code_speciality: str
    course: str
    registered_at: datetime.datetime
    class Config:
        from_attributes = True

class UserResponseRegister(UserResponse):
    files: List[FileResponse] = []
