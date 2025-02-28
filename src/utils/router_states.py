from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.models.enums import (
    TeamRole, TeamMemberStatus, FileType,
    FileOwnerType, FileFormat, UserRole, UserStatus,
    StageType
)
from src.utils.enum_utils import get_enum_data
from src.models import Stage


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
        # Типы файлов
        self.consent_type_id: UUID = None
        self.education_certificate_type_id: UUID = None
        self.team_logo_type_id: UUID = None
        self.job_certificate_type_id: UUID = None
        self.solution_type_id: UUID = None
        self.deployment_type_id: UUID = None

        # Типы владельцев
        self.user_owner_type_id: UUID = None
        self.team_owner_type_id: UUID = None

        # Форматы файлов
        self.pdf_format_id: UUID = None
        self.image_format_id: UUID = None
        self.zip_format_id: UUID = None
        self.txt_format_id: UUID = None
        self.md_format_id: UUID = None

    async def initialize(self, session: AsyncSession):
        """Инициализация ID при старте приложения"""
        enum_data = get_enum_data()

        # Инициализация типов файлов
        self.consent_type_id = enum_data.get_file_type_id(FileType.CONSENT)
        self.education_certificate_type_id = enum_data.get_file_type_id(FileType.EDUCATION_CERTIFICATE)
        self.job_certificate_type_id = enum_data.get_file_type_id(FileType.JOB_CERTIFICATE)
        self.team_logo_type_id = enum_data.get_file_type_id(FileType.TEAM_LOGO)
        self.solution_type_id = enum_data.get_file_type_id(FileType.SOLUTION)
        self.deployment_type_id = enum_data.get_file_type_id(FileType.DEPLOYMENT)

        # Инициализация типов владельцев
        self.user_owner_type_id = enum_data.get_file_owner_type_id(FileOwnerType.USER)
        self.team_owner_type_id = enum_data.get_file_owner_type_id(FileOwnerType.TEAM)

        # Инициализация форматов файлов
        self.pdf_format_id = enum_data.get_file_format_id(FileFormat.PDF)
        self.image_format_id = enum_data.get_file_format_id(FileFormat.IMAGE)
        self.zip_format_id = enum_data.get_file_format_id(FileFormat.ZIP)
        self.txt_format_id = enum_data.get_file_format_id(FileFormat.TXT)
        self.md_format_id = enum_data.get_file_format_id(FileFormat.MD)


class UserRouterState:
    def __init__(self):
        self.participant_role_id: UUID = None
        self.mentor_role_id: UUID = None
        self.judge_role_id: UUID = None
        self.admin_role_id: UUID = None
        self.organizer_role_id: UUID = None
        self.pending_status_id: UUID = None
        self.approved_status_id: UUID = None
        self.need_update_status_id: UUID = None

    async def initialize(self, session: AsyncSession):
        """Инициализация ID при старте приложения"""
        enum_data = get_enum_data()
        self.participant_role_id = enum_data.get_user_role_id(UserRole.PARTICIPANT)
        self.mentor_role_id = enum_data.get_user_role_id(UserRole.MENTOR)
        self.judge_role_id = enum_data.get_user_role_id(UserRole.JUDGE)
        self.admin_role_id = enum_data.get_user_role_id(UserRole.ADMIN)
        self.organizer_role_id = enum_data.get_user_role_id(UserRole.ORGANIZER)
        self.pending_status_id = enum_data.get_user_status_id(UserStatus.PENDING)
        self.approved_status_id = enum_data.get_user_status_id(UserStatus.APPROVED)
        self.need_update_status_id = enum_data.get_user_status_id(UserStatus.NEED_UPDATE)


class UserStatusState:
    def __init__(self):
        self.pending_status_id: UUID = None
        self.approved_status_id: UUID = None
        self.need_update_status_id: UUID = None

    async def initialize(self, session: AsyncSession):
        """Инициализация ID при старте приложения"""
        enum_data = get_enum_data()
        self.pending_status_id = enum_data.get_user_status_id(UserStatus.PENDING)
        self.approved_status_id = enum_data.get_user_status_id(UserStatus.APPROVED)
        self.need_update_status_id = enum_data.get_user_status_id(UserStatus.NEED_UPDATE)


class StageRouterState:
    def __init__(self):
        self.registration_stage_id: UUID = None
        self.registration_closed_stage_id: UUID = None
        self.task_distribution_stage_id: UUID = None
        self.solution_submission_stage_id: UUID = None
        self.solution_review_stage_id: UUID = None
        self.online_defense_stage_id: UUID = None
        self.results_publication_stage_id: UUID = None
        self.award_ceremony_stage_id: UUID = None
        self.current_stage_id: UUID = None
        self.current_stage_order: int = None

    async def initialize(self, session: AsyncSession):
        """Инициализация ID этапов при старте приложения"""
        enum_data = get_enum_data()

        self.registration_stage_id = enum_data.get_stage_id(StageType.REGISTRATION)
        self.registration_closed_stage_id = enum_data.get_stage_id(StageType.REGISTRATION_CLOSED)
        self.task_distribution_stage_id = enum_data.get_stage_id(StageType.TASK_DISTRIBUTION)
        self.solution_submission_stage_id = enum_data.get_stage_id(StageType.SOLUTION_SUBMISSION)
        self.solution_review_stage_id = enum_data.get_stage_id(StageType.SOLUTION_REVIEW)
        self.online_defense_stage_id = enum_data.get_stage_id(StageType.ONLINE_DEFENSE)
        self.results_publication_stage_id = enum_data.get_stage_id(StageType.RESULTS_PUBLICATION)
        self.award_ceremony_stage_id = enum_data.get_stage_id(StageType.AWARD_CEREMONY)

        result = await session.execute(
            select(Stage).where(Stage.is_active == True)
        )
        current_stage = result.scalar_one_or_none()
        if current_stage:
            self.current_stage_id = current_stage.id
            self.current_stage_order = current_stage.order

    async def get_current_stage_order(self, session: AsyncSession) -> int:
        """Получить порядковый номер текущего этапа"""
        result = await session.execute(
            select(Stage.order).where(Stage.is_active == True)
        )
        current_stage = result.scalar_one_or_none()
        self.current_stage_order = current_stage
        return current_stage


team_router_state = TeamRouterState()
file_router_state = FileRouterState()
user_router_state = UserRouterState()
user_status_state = UserStatusState()
stage_router_state = StageRouterState()


async def initialize_router_states(session: AsyncSession):
    """Инициализация всех состояний роутеров"""
    await team_router_state.initialize(session)
    await file_router_state.initialize(session)
    await user_router_state.initialize(session)
    await user_status_state.initialize(session)
    await stage_router_state.initialize(session)
