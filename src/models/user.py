from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid

from src.db import Base


class User(Base):
    """Модель пользователя в бд"""
    __tablename__ = 'users'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password = Column(String(512), nullable=False)
    full_name = Column(String(255), nullable=False, index=True)
    registered_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    user2roles = relationship("User2Roles", back_populates="user")
    teams_as_leader = relationship("Team", back_populates="team_leader")
    team_members = relationship("TeamMember", back_populates="user")
    files = relationship("File", back_populates="user", cascade="all, delete-orphan")
    participant_info = relationship("ParticipantInfo", back_populates="user", uselist=False)


class ParticipantInfo(Base):
    """Модель дополнительной информации участника"""
    __tablename__ = 'participant_info'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False, unique=True)
    number = Column(String(255), nullable=False)
    vuz = Column(String(255), nullable=False)
    vuz_direction = Column(String(255), nullable=False)
    code_speciality = Column(String(255), nullable=False)
    course = Column(String(255), nullable=False)
    # Relationships
    user = relationship("User", back_populates="participant_info")


class User2Roles(Base):
    """Модель связка пользователя с ролями"""
    __tablename__ = 'user_2_roles'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    role_id = Column(UUID(as_uuid=True), ForeignKey('roles.id'), nullable=False)

    # Relationships
    user = relationship("User", back_populates="user2roles")
    role = relationship("Role", back_populates="user2roles")
