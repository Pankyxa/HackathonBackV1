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
    # Новые типы для двухэтапного хакатона
    REMOTE_TASK_DISTRIBUTION = "remote_task_distribution"  # Заочный этап - распределение заданий
    REMOTE_SOLUTION_SUBMISSION = "remote_solution_submission"  # Заочный этап - прием решений
    REMOTE_SOLUTION_REVIEW = "remote_solution_review"  # Устаревший тип - не используется (оценка происходит на этапе ONLINE_DEFENSE)
    FINALISTS_SELECTION = "finalists_selection"  # Определение финалистов
    ON_SITE_TASK_DISTRIBUTION = "on_site_task_distribution"  # Очный этап - распределение заданий
    ON_SITE_SOLUTION_SUBMISSION = "on_site_solution_submission"  # Очный этап - прием решений
    ON_SITE_DEFENSE = "on_site_defense"  # Очный этап - защита