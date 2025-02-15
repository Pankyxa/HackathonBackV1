from datetime import datetime

from sqlalchemy import Column, String, ForeignKey, Enum as SQLAlchemyEnum, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid

from src.db import Base
from . import File
from .enums import TeamRole, TeamMemberStatus


class Team(Base):
    """Модель команды"""
    __tablename__ = 'teams'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_name = Column(String(255), nullable=False)
    team_motto = Column(String(255), nullable=False)
    team_leader_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    logo_file_id = Column(UUID(as_uuid=True), ForeignKey('files.id'), nullable=True)

    # Relationships
    team_leader = relationship("User", back_populates="teams_as_leader")
    members = relationship("TeamMember", back_populates="team")
    logo = relationship("File", foreign_keys=[logo_file_id])
    files = relationship("File", back_populates="team", foreign_keys=[File.team_id])


class TeamMember(Base):
    """Модель участника команды"""
    __tablename__ = 'team_members'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey('teams.id'), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    role = Column(SQLAlchemyEnum(TeamRole), nullable=False)
    status = Column(SQLAlchemyEnum(TeamMemberStatus), nullable=False, default=TeamMemberStatus.PENDING)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), onupdate=datetime.utcnow)

    # Relationships
    team = relationship("Team", back_populates="members")
    user = relationship("User", back_populates="team_members")
