from datetime import datetime
import uuid
from sqlalchemy import Column, ForeignKey, Integer, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.db import Base


class TeamEvaluation(Base):
    """Модель оценки команды членом жюри"""
    __tablename__ = 'team_evaluations'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey('teams.id'), nullable=False)
    judge_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)

    criterion_1 = Column(Integer, nullable=False)  # Соответствие результата
    criterion_2 = Column(Integer, nullable=False)  # Корректность, оригинальность и инновационность
    criterion_3 = Column(Integer, nullable=False)  # Проработанность технического решения
    criterion_4 = Column(Integer, nullable=False)  # Эффективность предложенного решения
    criterion_5 = Column(Integer, nullable=False)  # Качество выступления
    
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), onupdate=datetime.utcnow)

    # Relationships
    team = relationship("Team", backref="evaluations")
    judge = relationship("User")

    def get_total_score(self) -> int:
        """Подсчет суммарного балла по всем критериям"""
        return (self.criterion_1 + self.criterion_2 + self.criterion_3 + 
                self.criterion_4 + self.criterion_5)