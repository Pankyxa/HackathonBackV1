from datetime import datetime
from uuid import UUID
from pydantic import BaseModel
from src.models.enums import FileFormat, FileType

class FileBase(BaseModel):
    filename: str
    file_format: FileFormat
    file_type: FileType

class FileCreate(FileBase):
    pass

class FileResponse(FileBase):
    id: UUID
    created_at: datetime
    user_id: UUID

    class Config:
        from_attributes = True