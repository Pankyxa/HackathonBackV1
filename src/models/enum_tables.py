from sqlalchemy import Column, String
from sqlalchemy.dialects.postgresql import UUID
import uuid
from src.db import Base

class TeamRoleTable(Base):
    """Таблица для хранения возможных ролей в команде"""
    __tablename__ = 'team_roles'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(255), nullable=True)

class TeamMemberStatusTable(Base):
    """Таблица для хранения статусов членов команды"""
    __tablename__ = 'team_member_statuses'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(255), nullable=True)

class FileFormatTable(Base):
    """Таблица для хранения форматов файлов"""
    __tablename__ = 'file_formats'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(255), nullable=True)

class FileTypeTable(Base):
    """Таблица для хранения типов файлов"""
    __tablename__ = 'file_types'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(255), nullable=True)

class FileOwnerTypeTable(Base):
    """Таблица для хранения типов владельцев файлов"""
    __tablename__ = 'file_owner_types'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(255), nullable=True)