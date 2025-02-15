from enum import Enum


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


class FileOwnerType(Enum):
    USER = "user"
    TEAM = "team"
