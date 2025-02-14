from sqlalchemy import Column, String
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid

from src.db import Base


class Role(Base):
    """Модель роли пользователя"""
    __tablename__ = 'roles'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), unique=True, nullable=False)
    description = Column(String(512), nullable=True)

    # Relationships
    user2roles = relationship("User2Roles", back_populates="role")
