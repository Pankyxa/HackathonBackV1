from enum import Enum

class TeamRole(str, Enum):
    TEAMLEAD = 'teamlead'
    DEVELOPER = 'developer'
    MENTOR = 'mentor'