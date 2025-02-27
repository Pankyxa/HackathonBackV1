from enum import Enum


class UserRole(str, Enum):
    PARTICIPANT = "participant"
    MENTOR = "mentor"
    JUDGE = "judge"
    ADMIN = "admin"
    ORGANIZER = "organizer"


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
    ZIP = "zip"
    TXT = "txt"
    MD = "md"


class FileType(Enum):
    CONSENT = "consent"
    EDUCATION_CERTIFICATE = "education_certificate"
    TEAM_LOGO = "team_logo"
    JOB_CERTIFICATE = "job_certificate"
    SOLUTION = "solution"  # Для ZIP файлов с решением
    DEPLOYMENT = "deployment"  # Для файлов с описанием развертывания


class FileOwnerType(Enum):
    USER = "user"
    TEAM = "team"


class StageType(Enum):
    REGISTRATION = "registration"
    REGISTRATION_CLOSED = "registration_closed"
    TASK_DISTRIBUTION = "task_distribution"
    SOLUTION_SUBMISSION = "solution_submission"
    SOLUTION_REVIEW = "solution_review"
    ONLINE_DEFENSE = "online_defense"
    RESULTS_PUBLICATION = "results_publication"
    AWARD_CEREMONY = "award_ceremony"
