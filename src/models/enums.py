from enum import Enum


class UserRole(str, Enum):
    PARTICIPANT = "participant"
    MENTOR = "mentor"
    JURY = "jury"
    ADMIN = "admin"


class UserStatus(str, Enum):
    PENDING = "pending"  # В ожидании
    APPROVED = "approved"  # Подтвержден
    NEED_UPDATE = "need_update"  # Отправлен на переотправление новых файлов


class TeamRole(str, Enum):
    TEAMLEAD = "teamlead"
    MEMBER = "member"
    MENTOR = "mentor"


class TeamMemberStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class FileFormat(Enum):
    PDF = "pdf"
    IMAGE = "image"


class FileType(Enum):
    CONSENT = "consent"
    EDUCATION_CERTIFICATE = "education_certificate"
    TEAM_LOGO = "team_logo"
    JOB_CERTIFICATE = "job_certificate"


class FileOwnerType(Enum):
    USER = "user"
    TEAM = "team"
