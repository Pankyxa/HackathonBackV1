from datetime import datetime
from sqlalchemy import Column, String, ForeignKey, DateTime, Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from src.db import Base
from src.models.enums import FileFormat, FileType


class File(Base):
    """Модель файла в бд"""
    __tablename__ = 'files'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(512), nullable=False)
    file_format = Column(SQLAlchemyEnum(FileFormat), nullable=False)
    file_type = Column(SQLAlchemyEnum(FileType), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)

    # Relationships
    user = relationship("User", back_populates="files")