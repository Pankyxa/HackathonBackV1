from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid

from src.db import Base


class Event(Base):
    """Модель события/сезона хакатона"""
    __tablename__ = 'events'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(String(1024), nullable=True)
    is_active = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), onupdate=datetime.utcnow)

    # Relationships
    teams = relationship("Team", back_populates="event")
    stages = relationship("Stage", back_populates="event")
    evaluations = relationship("TeamEvaluation", back_populates="event")
    judges = relationship("EventJudge", back_populates="event", cascade="all, delete-orphan")
    user_statuses = relationship("UserEventStatus", back_populates="event", cascade="all, delete-orphan")


class EventJudge(Base):
    """Модель связи жюри с событием"""
    __tablename__ = 'event_judges'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(UUID(as_uuid=True), ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    judge_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    event = relationship("Event", back_populates="judges")
    judge = relationship("User", backref="event_judges")

    # Уникальный constraint: один жюри может быть привязан к событию только один раз
    __table_args__ = (
        UniqueConstraint('event_id', 'judge_id', name='uq_event_judge'),
    )