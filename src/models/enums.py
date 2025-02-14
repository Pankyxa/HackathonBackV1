from enum import Enum


class TeamRole(str, Enum):
    TEAMLEAD = 'teamlead'
    DEVELOPER = 'developer'
    MENTOR = 'mentor'


class FileFormat(Enum):
    PDF = "pdf"
    IMAGE = "image"


class FileType(Enum):
    CONSENT = "consent"
    EDUCATION_CERTIFICATE = "education_certificate"
    PROFILE_PHOTO = "profile_photo"
    TEAM_LOGO = "team_logo"


class FileOwnerType(Enum):
    USER = "user"
    TEAM = "team"