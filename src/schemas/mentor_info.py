from uuid import UUID
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from src.schemas.file import FileResponse

class MentorInfoResponse(BaseModel):
    id: UUID
    user_id: UUID
    number: str
    job: str
    job_title: str

    class Config:
        from_attributes = True