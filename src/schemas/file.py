from datetime import datetime
from uuid import UUID
from typing import Optional
from pydantic import BaseModel


class FileFormatResponse(BaseModel):
    """Схема для ответа с форматом файла"""
    id: UUID
    name: str
    description: Optional[str] = None

    class Config:
        from_attributes = True


class FileTypeResponse(BaseModel):
    """Схема для ответа с типом файла"""
    id: UUID
    name: str
    description: Optional[str] = None

    class Config:
        from_attributes = True


class FileOwnerTypeResponse(BaseModel):
    """Схема для ответа с типом владельца файла"""
    id: UUID
    name: str
    description: Optional[str] = None

    class Config:
        from_attributes = True


class FileBase(BaseModel):
    """Базовая схема файла"""
    filename: str


class FileCreate(FileBase):
    """Схема для создания файла"""
    file_format_id: UUID
    file_type_id: UUID
    owner_type_id: UUID


class FileResponse(FileBase):
    """Схема для ответа с файлом"""
    id: UUID
    file_path: str
    created_at: datetime

    # Связанные данные
    file_format: FileFormatResponse
    file_type: FileTypeResponse
    owner_type: FileOwnerTypeResponse

    # ID владельцев
    user_id: Optional[UUID] = None
    team_id: Optional[UUID] = None

    class Config:
        from_attributes = True


class FileDetailResponse(FileResponse):
    """Расширенная схема ответа с файлом"""

    class Config:
        from_attributes = True


class FileUpdate(BaseModel):
    """Схема для обновления файла"""
    filename: Optional[str] = None
    file_format_id: Optional[UUID] = None
    file_type_id: Optional[UUID] = None

    class Config:
        from_attributes = True