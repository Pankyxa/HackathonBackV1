# src/utils/router_states.py
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.enums import (
    TeamRole, TeamMemberStatus, FileType,
    FileOwnerType, FileFormat, UserRole
)
from src.utils.enum_utils import get_enum_data


class TeamRouterState:
    def __init__(self):
        self.teamlead_role_id: UUID = None
        self.member_role_id: UUID = None
        self.mentor_role_id: UUID = None
        self.pending_status_id: UUID = None
        self.accepted_status_id: UUID = None
        self.rejected_status_id: UUID = None

    async def initialize(self, session: AsyncSession):
        """Инициализация ID при старте приложения"""
        enum_data = get_enum_data()
        self.teamlead_role_id = enum_data.get_team_role_id(TeamRole.TEAMLEAD)
        self.member_role_id = enum_data.get_team_role_id(TeamRole.MEMBER)
        self.mentor_role_id = enum_data.get_team_role_id(TeamRole.MENTOR)
        self.pending_status_id = enum_data.get_team_member_status_id(TeamMemberStatus.PENDING)
        self.accepted_status_id = enum_data.get_team_member_status_id(TeamMemberStatus.ACCEPTED)
        self.rejected_status_id = enum_data.get_team_member_status_id(TeamMemberStatus.REJECTED)


class FileRouterState:
    def __init__(self):
        self.consent_type_id: UUID = None
        self.education_certificate_type_id: UUID = None
        self.team_logo_type_id: UUID = None

        self.user_owner_type_id: UUID = None
        self.team_owner_type_id: UUID = None

        self.pdf_format_id: UUID = None
        self.image_format_id: UUID = None

    async def initialize(self, session: AsyncSession):
        """Инициализация ID при старте приложения"""
        enum_data = get_enum_data()

        self.consent_type_id = enum_data.get_file_type_id(FileType.CONSENT)
        self.education_certificate_type_id = enum_data.get_file_type_id(FileType.EDUCATION_CERTIFICATE)
        self.job_certificate_type_id = enum_data.get_file_type_id(FileType.JOB_CERTIFICATE)
        self.team_logo_type_id = enum_data.get_file_type_id(FileType.TEAM_LOGO)

        self.user_owner_type_id = enum_data.get_file_owner_type_id(FileOwnerType.USER)
        self.team_owner_type_id = enum_data.get_file_owner_type_id(FileOwnerType.TEAM)

        self.pdf_format_id = enum_data.get_file_format_id(FileFormat.PDF)
        self.image_format_id = enum_data.get_file_format_id(FileFormat.IMAGE)


class UserRouterState:
    def __init__(self):
        self.participant_role_id: UUID = None
        self.mentor_role_id: UUID = None
        self.jury_role_id: UUID = None
        self.admin_role_id: UUID = None

    async def initialize(self, session: AsyncSession):
        """Инициализация ID при старте приложения"""
        enum_data = get_enum_data()
        self.participant_role_id = enum_data.get_user_role_id(UserRole.PARTICIPANT)
        self.mentor_role_id = enum_data.get_user_role_id(UserRole.MENTOR)
        self.jury_role_id = enum_data.get_user_role_id(UserRole.JURY)
        self.admin_role_id = enum_data.get_user_role_id(UserRole.ADMIN)


team_router_state = TeamRouterState()
file_router_state = FileRouterState()
user_router_state = UserRouterState()


async def initialize_router_states(session: AsyncSession):
    """Инициализация всех состояний роутеров"""
    await team_router_state.initialize(session)
    await file_router_state.initialize(session)
    await user_router_state.initialize(session)