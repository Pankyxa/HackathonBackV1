from .auth import router as auth_router
from .teams import router as teams_router
from .users import router as users_router
from .files import router as files_router
from .evaluations import router as evaluations_router

__all__ = ['auth_router', 'teams_router', 'users_router', 'files_router', 'evaluations_router']
