from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
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
    order = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=False)
    event_id = Column(UUID(as_uuid=True), ForeignKey('events.id'), nullable=False)
    is_auto_activate = Column(Boolean, default=False, nullable=False)  # Автоматическая активация по расписанию
    auto_activate_at = Column(DateTime(timezone=True), nullable=True)  # Дата и время активации (по МСК, хранится в UTC)
    group = Column(String, nullable=True)  # Группировка этапов: "registration", "remote", "on_site", "final"
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    event = relationship("Event", back_populates="stages")

    class Config:
        from_attributes = True