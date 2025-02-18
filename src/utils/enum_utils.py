from typing import Dict
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    TeamRoleTable, TeamMemberStatusTable, FileFormatTable,
    FileTypeTable, FileOwnerTypeTable, Role,
    TeamRole, TeamMemberStatus, FileFormat,
    FileType, FileOwnerType, UserRole, UserStatus, UserStatusType
)


class EnumData:
    def __init__(self):
        self.team_role_ids: Dict[TeamRole, UUID] = {}
        self.team_member_status_ids: Dict[TeamMemberStatus, UUID] = {}
        self.file_format_ids: Dict[FileFormat, UUID] = {}
        self.file_type_ids: Dict[FileType, UUID] = {}
        self.file_owner_type_ids: Dict[FileOwnerType, UUID] = {}
        self.user_role_ids: Dict[UserRole, UUID] = {}
        self.user_status_ids: Dict[UserStatus, UUID] = {}

    async def initialize(self, session: AsyncSession):
        """Инициализация всех ID из enum таблиц"""
        team_roles = await session.execute(select(TeamRoleTable))
        for role in team_roles.scalars():
            self.team_role_ids[TeamRole(role.name)] = role.id

        team_member_statuses = await session.execute(select(TeamMemberStatusTable))
        for status in team_member_statuses.scalars():
            self.team_member_status_ids[TeamMemberStatus(status.name)] = status.id

        file_formats = await session.execute(select(FileFormatTable))
        for format_ in file_formats.scalars():
            self.file_format_ids[FileFormat(format_.name)] = format_.id

        file_types = await session.execute(select(FileTypeTable))
        for type_ in file_types.scalars():
            self.file_type_ids[FileType(type_.name)] = type_.id

        file_owner_types = await session.execute(select(FileOwnerTypeTable))
        for owner_type in file_owner_types.scalars():
            self.file_owner_type_ids[FileOwnerType(owner_type.name)] = owner_type.id

        user_roles = await session.execute(select(Role))
        for role in user_roles.scalars():
            self.user_role_ids[UserRole(role.name)] = role.id

        user_statuses = await session.execute(select(UserStatusType))
        for status in user_statuses.scalars():
            self.user_status_ids[UserStatus(status.name)] = status.id

    def get_user_role_id(self, role: UserRole) -> UUID:
        return self.user_role_ids[role]

    def get_team_role_id(self, role: TeamRole) -> UUID:
        return self.team_role_ids[role]

    def get_team_member_status_id(self, status: TeamMemberStatus) -> UUID:
        return self.team_member_status_ids[status]

    def get_file_format_id(self, format_: FileFormat) -> UUID:
        return self.file_format_ids[format_]

    def get_file_type_id(self, type_: FileType) -> UUID:
        return self.file_type_ids[type_]

    def get_file_owner_type_id(self, owner_type: FileOwnerType) -> UUID:
        return self.file_owner_type_ids[owner_type]

    def get_user_status_id(self, status: UserStatus) -> UUID:
        """Получение ID статуса пользователя"""
        return self.user_status_ids[status]


enum_data = EnumData()


async def initialize_enum_data(session: AsyncSession):
    """Инициализация глобального экземпляра EnumData"""
    await enum_data.initialize(session)


def get_enum_data() -> EnumData:
    """Получение инициализированного экземпляра EnumData"""
    return enum_data
