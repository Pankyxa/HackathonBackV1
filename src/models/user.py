from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Enum as SQLAlchemyEnum
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid
from sqlalchemy.ext.declarative import declarative_base
from .enums import TeamRole

Base = declarative_base()


class User(Base):
    """Модель пользователя в бд"""
    __tablename__ = 'users'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password = Column(String(512), nullable=False)
    full_name = Column(String(255), nullable=False)
    number = Column(String(255), nullable=False)
    vuz = Column(String(255), nullable=False)
    vuz_direction = Column(String(255), nullable=False)
    code_speciality = Column(String(255), nullable=False)
    course = Column(String(255), nullable=False)
    registered_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    # Relationships
    user2roles = relationship("User2Roles", back_populates="user")
    teams_as_leader = relationship("Team", back_populates="team_leader")
    team_members = relationship("TeamMember", back_populates="user")


class Team(Base):
    """Модель команды"""
    __tablename__ = 'teams'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_name = Column(String(255), nullable=False)
    team_motto = Column(String(255), nullable=False)
    team_leader_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)

    # Relationships
    team_leader = relationship("User", back_populates="teams_as_leader")
    members = relationship("TeamMember", back_populates="team")


class TeamMember(Base):
    """Модель участника команды"""
    __tablename__ = 'team_members'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey('teams.id'), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    role = Column(SQLAlchemyEnum(TeamRole), nullable=False)  # Используем Enum
    # Relationships
    team = relationship("Team", back_populates="members")
    user = relationship("User", back_populates="team_members")


class User2Roles(Base):
    """Модель связка пользователя с ролями"""
    __tablename__ = 'user_2_roles'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    role_id = Column(UUID(as_uuid=True), ForeignKey('roles.id'), nullable=False)

    # Relationships
    user = relationship("User", back_populates="user2roles")
    role = relationship("Role", back_populates="user2roles")


class Role(Base):
    """Модель роли пользователя"""
    __tablename__ = 'roles'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), unique=True, nullable=False)
    description = Column(String(512), nullable=True)

    # Relationships
    user2roles = relationship("User2Roles", back_populates="role")
