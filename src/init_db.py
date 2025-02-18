from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import sessionmaker
from src.db import Base
from src.models import User, File, Team, Role, TeamMember, UserStatusType
from src.models.enum_tables import (
    TeamRoleTable,
    TeamMemberStatusTable,
    FileFormatTable,
    FileTypeTable,
    FileOwnerTypeTable
)
from src.models.enums import TeamRole, TeamMemberStatus, FileFormat, FileType, FileOwnerType
import uuid


async def init_models(engine: AsyncEngine):
    """Инициализация моделей базы данных"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        user_statuses_data = [
            {"name": "pending", "description": "В ожидании"},
            {"name": "approved", "description": "Подтвержден"},
            {"name": "need_update", "description": "Отправлен на переотправление новых файлов"}
        ]

        for status_data in user_statuses_data:
            existing_status = await session.execute(
                UserStatusType.__table__.select().where(UserStatusType.name == status_data["name"])
            )
            if not list(existing_status):
                status = UserStatusType(
                    id=uuid.uuid4(),
                    name=status_data["name"],
                    description=status_data["description"]
                )
                session.add(status)

        roles_data = [
            {"name": "participant", "description": "Участник проекта"},
            {"name": "mentor", "description": "Наставник команды"},
            {"name": "jury", "description": "Член жюри"},
            {"name": "admin", "description": "Администратор системы"}
        ]

        for role_data in roles_data:
            existing_role = await session.execute(
                Role.__table__.select().where(Role.name == role_data["name"])
            )
            if not list(existing_role):
                role = Role(
                    id=uuid.uuid4(),
                    name=role_data["name"],
                    description=role_data["description"]
                )
                session.add(role)

        team_roles_data = [
            {"name": TeamRole.TEAMLEAD.value, "description": "Лидер команды"},
            {"name": TeamRole.MEMBER.value, "description": "Участник команды"},
            {"name": TeamRole.MENTOR.value, "description": "Наставник команды"}
        ]

        for role_data in team_roles_data:
            existing_role = await session.execute(
                TeamRoleTable.__table__.select().where(TeamRoleTable.name == role_data["name"])
            )
            if not list(existing_role):
                role = TeamRoleTable(
                    id=uuid.uuid4(),
                    name=role_data["name"],
                    description=role_data["description"]
                )
                session.add(role)

        status_data = [
            {"name": TeamMemberStatus.PENDING.value, "description": "Ожидает подтверждения"},
            {"name": TeamMemberStatus.ACCEPTED.value, "description": "Принят"},
            {"name": TeamMemberStatus.REJECTED.value, "description": "Отклонен"}
        ]

        for status in status_data:
            existing_status = await session.execute(
                TeamMemberStatusTable.__table__.select().where(TeamMemberStatusTable.name == status["name"])
            )
            if not list(existing_status):
                new_status = TeamMemberStatusTable(
                    id=uuid.uuid4(),
                    name=status["name"],
                    description=status["description"]
                )
                session.add(new_status)

        file_formats_data = [
            {"name": FileFormat.PDF.value, "description": "PDF документ"},
            {"name": FileFormat.IMAGE.value, "description": "Изображение"}
        ]

        for format_data in file_formats_data:
            existing_format = await session.execute(
                FileFormatTable.__table__.select().where(FileFormatTable.name == format_data["name"])
            )
            if not list(existing_format):
                new_format = FileFormatTable(
                    id=uuid.uuid4(),
                    name=format_data["name"],
                    description=format_data["description"]
                )
                session.add(new_format)

        file_types_data = [
            {"name": FileType.CONSENT.value, "description": "Согласие"},
            {"name": FileType.EDUCATION_CERTIFICATE.value, "description": "Сертификат об образовании"},
            {"name": FileType.JOB_CERTIFICATE.value, "description": "Сертификат с места работы"},
            {"name": FileType.TEAM_LOGO.value, "description": "Логотип команды"}
        ]

        for type_data in file_types_data:
            existing_type = await session.execute(
                FileTypeTable.__table__.select().where(FileTypeTable.name == type_data["name"])
            )
            if not list(existing_type):
                new_type = FileTypeTable(
                    id=uuid.uuid4(),
                    name=type_data["name"],
                    description=type_data["description"]
                )
                session.add(new_type)

        owner_types_data = [
            {"name": FileOwnerType.USER.value, "description": "Пользователь"},
            {"name": FileOwnerType.TEAM.value, "description": "Команда"}
        ]

        for owner_type in owner_types_data:
            existing_type = await session.execute(
                FileOwnerTypeTable.__table__.select().where(FileOwnerTypeTable.name == owner_type["name"])
            )
            if not list(existing_type):
                new_owner_type = FileOwnerTypeTable(
                    id=uuid.uuid4(),
                    name=owner_type["name"],
                    description=owner_type["description"]
                )
                session.add(new_owner_type)

        await session.commit()
