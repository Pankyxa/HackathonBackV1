from enum import Enum
from sqlalchemy import Column, String, ForeignKey, Enum as SQLAlchemyEnum
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid

from src.db import Base


class TeamRole(str, Enum):
    TEAMLEAD = 'teamlead'
    DEVELOPER = 'developer'
    MENTOR = 'mentor'


class Team(Base):
    """Модель команды"""
    __tablename__ = 'teams'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_name = Column(String(255), nullable=False)
    team_motto = Column(String(255), nullable=False)
    team_leader_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    logo_file_id = Column(UUID(as_uuid=True), ForeignKey('files.id'), nullable=True)  # Добавляем поле для логотипа

    # Relationships
    team_leader = relationship("User", back_populates="teams_as_leader")
    members = relationship("TeamMember", back_populates="team")
    logo = relationship("File")  # Добавляем связь с файлом логотипа


class TeamMember(Base):
    """Модель участника команды"""
    __tablename__ = 'team_members'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey('teams.id'), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    role = Column(SQLAlchemyEnum(TeamRole), nullable=False)

    # Relationships
    team = relationship("Team", back_populates="members")
    user = relationship("User", back_populates="team_members")
