from enum import Enum


class TeamRole(str, Enum):
    TEAMLEAD = 'teamlead'
    DEVELOPER = 'developer'
    MENTOR = 'mentor'

class FileFormat(Enum):
    PDF = "pdf"
    JPEG = "jpeg"
    PNG = "png"

class FileType(Enum):
    CONSENT = "consent"
    EDUCATION_CERTIFICATE = "education_certificate"
    PROFILE_PHOTO = "profile_photo"
