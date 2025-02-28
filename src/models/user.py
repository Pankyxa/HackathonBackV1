from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean
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
    current_status_id = Column(UUID(as_uuid=True), ForeignKey('user_status_types.id'), nullable=False)
    email_verified = Column(Boolean, default=False, nullable=False)

    # Relationships
    user2roles = relationship("User2Roles", back_populates="user")
    teams_as_leader = relationship("Team", back_populates="team_leader")
    team_members = relationship("TeamMember", back_populates="user")
    files = relationship("File", back_populates="user", cascade="all, delete-orphan")
    participant_info = relationship("ParticipantInfo", back_populates="user", uselist=False)
    mentor_info = relationship("MentorInfo", back_populates="user", uselist=False)
    current_status = relationship("UserStatusType")
    status_history = relationship("UserStatusHistory", back_populates="user", order_by="UserStatusHistory.created_at.desc()")

    @property
    def roles(self):
        return [user2role.role for user2role in self.user2roles]


class UserStatusType(Base):
    """Справочник статусов пользователя"""
    __tablename__ = 'user_status_types'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(50), nullable=False, unique=True)
    description = Column(String(255), nullable=True)


class UserStatusHistory(Base):
    """История статусов пользователя"""
    __tablename__ = 'user_status_history'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    status_id = Column(UUID(as_uuid=True), ForeignKey('user_status_types.id'), nullable=False)
    comment = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="status_history")
    status = relationship("UserStatusType")


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


class MentorInfo(Base):
    """Модель дополнительной информации наставника"""
    __tablename__ = 'mentor_info'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False, unique=True)
    number = Column(String(255), nullable=False)
    job = Column(String(255), nullable=False)
    job_title = Column(String(255), nullable=False)
    # Relationships
    user = relationship("User", back_populates="mentor_info")


class User2Roles(Base):
    """Модель связка пользователя с ролями"""
    __tablename__ = 'user_2_roles'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    role_id = Column(UUID(as_uuid=True), ForeignKey('roles.id'), nullable=False)

    # Relationships
    user = relationship("User", back_populates="user2roles")
    role = relationship("Role", back_populates="user2roles")


class EmailVerificationToken(Base):
    """Модель для хранения токенов подтверждения email"""
    __tablename__ = 'email_verification_tokens'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    token = Column(String(255), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, default=False, nullable=False)

    # Relationships
    user = relationship("User")

    @property
    def is_expired(self):
        return datetime.now(timezone.utc) > self.expires_at

