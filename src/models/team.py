from datetime import datetime
from typing import List, Optional

from sqlalchemy import Column, String, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid

from src.db import Base
from . import File, TeamMemberStatus, UserStatus, TeamRole


PARTICIPATION_OVERRIDE_TEAM_IDS = {uuid.UUID("d14c42d3-25ef-4637-9d07-1df9ad67d0e4")}


class Team(Base):
    """Модель команды"""

    __tablename__ = "teams"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_name = Column(String(255), nullable=False)
    team_motto = Column(String(255), nullable=False)
    team_leader_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    logo_file_id = Column(UUID(as_uuid=True), ForeignKey("files.id"), nullable=True)
    solution_link = Column(String(1024), nullable=True)
    event_id = Column(UUID(as_uuid=True), ForeignKey("events.id"), nullable=False)
    is_finalist = Column(
        Boolean, default=False, nullable=False
    )  # Является ли команда финалистом

    # Relationships
    team_leader = relationship("User", back_populates="teams_as_leader")
    members = relationship("TeamMember", back_populates="team")
    logo = relationship("File", foreign_keys=[logo_file_id])
    files = relationship("File", back_populates="team", foreign_keys=[File.team_id])
    event = relationship("Event", back_populates="teams")

    def get_active_members(self) -> List["TeamMember"]:
        """Получение списка принятых участников команды"""
        try:
            return [
                member
                for member in self.members
                if hasattr(member, "status")
                and member.status
                and hasattr(member.status, "name")
                and member.status.name == TeamMemberStatus.ACCEPTED.value
            ]
        except Exception:
            # Если произошла ошибка при доступе к данным (например, lazy loading),
            # возвращаем пустой список
            return []

    def get_mentor(self) -> Optional["TeamMember"]:
        """Получение наставника команды"""
        try:
            active_members = self.get_active_members()
            for member in active_members:
                if (
                    hasattr(member, "role")
                    and member.role
                    and hasattr(member.role, "name")
                    and member.role.name == TeamRole.MENTOR.value
                ):
                    return member
            return None
        except Exception:
            return None

    def get_team_leader_member(self) -> Optional["TeamMember"]:
        """Получение тимлида как участника команды"""
        try:
            active_members = self.get_active_members()
            for member in active_members:
                if (
                    hasattr(member, "role")
                    and member.role
                    and hasattr(member.role, "name")
                    and member.role.name == TeamRole.TEAMLEAD.value
                ):
                    return member
            return None
        except Exception:
            return None

    def get_regular_members(self) -> List["TeamMember"]:
        """Получение обычных участников команды (не тимлид и не наставник)"""
        try:
            active_members = self.get_active_members()
            return [
                member
                for member in active_members
                if (
                    hasattr(member, "role")
                    and member.role
                    and hasattr(member.role, "name")
                    and member.role.name == TeamRole.MEMBER.value
                )
            ]
        except Exception:
            return []

    def has_participation_override(self) -> bool:
        return self.id in PARTICIPATION_OVERRIDE_TEAM_IDS

    def get_required_regular_members_count(self) -> int:
        if self.has_participation_override():
            return 3
        return 4

    def get_status(self) -> str:
        """Вычисляемый статус команды"""
        mentor = self.get_mentor()
        team_leader = self.get_team_leader_member()
        regular_members = self.get_regular_members()
        required_regular_members = self.get_required_regular_members_count()

        if not mentor or not team_leader:
            return "incomplete"

        if len(regular_members) != required_regular_members:
            return "incomplete"

        all_approved = True
        has_pending = False
        has_need_update = False

        def check_user_status(user):
            nonlocal all_approved, has_pending, has_need_update
            status = user.current_status.name
            if status == UserStatus.PENDING.value:
                has_pending = True
                all_approved = False
            elif status == UserStatus.NEED_UPDATE.value:
                has_need_update = True
                all_approved = False
            elif status != UserStatus.APPROVED.value:
                all_approved = False

        check_user_status(mentor.user)
        check_user_status(team_leader.user)
        for member in regular_members:
            check_user_status(member.user)

        if all_approved:
            return "active"
        elif has_need_update:
            return "needs_update"
        elif has_pending:
            return "pending"

        return "invalid"

    def can_participate(self) -> bool:
        """Проверка возможности участия команды"""
        required_regular_members = self.get_required_regular_members_count()

        return (
            self.get_status() == "active"
            and len(self.get_regular_members()) == required_regular_members
            and self.get_team_leader_member() is not None
            and self.get_mentor() is not None
        )

    def get_status_details(self) -> dict:
        """Получение детальной информации о статусе команды"""
        mentor = self.get_mentor()
        team_leader = self.get_team_leader_member()
        regular_members = self.get_regular_members()

        return {
            "status": self.get_status(),
            "can_participate": self.can_participate(),
            "total_members": len(self.get_active_members()),
            "regular_members_count": len(regular_members),
            "has_mentor": mentor is not None,
            "mentor_status": mentor.user.current_status.name if mentor else None,
            "has_team_leader": team_leader is not None,
            "team_leader_status": team_leader.user.current_status.name
            if team_leader
            else None,
            "members_status": {
                "approved": sum(
                    1
                    for m in regular_members
                    if m.user.current_status.name == UserStatus.APPROVED.value
                ),
                "pending": sum(
                    1
                    for m in regular_members
                    if m.user.current_status.name == UserStatus.PENDING.value
                ),
                "need_update": sum(
                    1
                    for m in regular_members
                    if m.user.current_status.name == UserStatus.NEED_UPDATE.value
                ),
            },
        }


class TeamMember(Base):
    """Модель участника команды"""

    __tablename__ = "team_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    role_id = Column(UUID(as_uuid=True), ForeignKey("team_roles.id"), nullable=False)
    status_id = Column(
        UUID(as_uuid=True), ForeignKey("team_member_statuses.id"), nullable=False
    )
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), onupdate=datetime.utcnow)

    # Relationships
    team = relationship("Team", back_populates="members")
    user = relationship("User", back_populates="team_members")
    role = relationship("TeamRoleTable", lazy="joined")
    status = relationship("TeamMemberStatusTable", lazy="joined")
