from datetime import datetime
from sqlalchemy import Column, String, ForeignKey, DateTime, Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid

from src.db import Base


class File(Base):
    """Модель файла в бд"""
    __tablename__ = 'files'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(512), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    file_format_id = Column(UUID(as_uuid=True), ForeignKey('file_formats.id'), nullable=False)
    file_type_id = Column(UUID(as_uuid=True), ForeignKey('file_types.id'), nullable=False)
    owner_type_id = Column(UUID(as_uuid=True), ForeignKey('file_owner_types.id'), nullable=False)

    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=True)
    team_id = Column(UUID(as_uuid=True), ForeignKey('teams.id', ondelete='CASCADE'), nullable=True)

    # Relationships
    user = relationship("User", back_populates="files")
    team = relationship("Team", foreign_keys=[team_id], back_populates="files")

    owner_type = relationship("FileOwnerTypeTable", lazy="joined")
    file_format = relationship("FileFormatTable", lazy="joined")
    file_type = relationship("FileTypeTable", lazy="joined")

