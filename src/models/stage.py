from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from src.db import Base
import uuid
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
from src.models.enums import StageType


class Stage(Base):
    __tablename__ = "stages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    order = Column(Integer, nullable=False, unique=True)
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    class Config:
        from_attributes = True