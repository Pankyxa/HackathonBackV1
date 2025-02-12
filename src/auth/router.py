from fastapi import APIRouter, Depends, HTTPException, status, Security
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid

from src.auth.utils import verify_password, get_password_hash
from src.db import get_session
from src.models.user import User
from src.schemas.user import UserCreate, UserLogin, Token, UserResponse
from src.auth.jwt import create_access_token, get_current_user, oauth2_scheme
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()
router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register", response_model=UserResponse)
async def register(user_data: UserCreate, session: AsyncSession = Depends(get_session)):
    query = select(User).where(User.email == user_data.email)
    result = await session.execute(query)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    user = User(
        id=uuid.uuid4(),
        email=user_data.email,
        password=get_password_hash(user_data.password),
        full_name=user_data.full_name,
        number=user_data.number,
        vuz=user_data.vuz,
        vuz_direction=user_data.vuz_direction,
        code_speciality=user_data.code_speciality,
        course=user_data.course
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    return user

@router.post("/login", response_model=Token)
async def login(user_data: UserLogin, session: AsyncSession = Depends(get_session)):
    query = select(User).where(User.email == user_data.email)
    result = await session.execute(query)
    user = result.scalar_one_or_none()

    if not user or not verify_password(user_data.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        data={"sub": user.email}
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.get(
    "/me",
    response_model=UserResponse,
    dependencies=[Depends(oauth2_scheme)],
    responses={
        401: {"description": "Not authenticated"},
    }
)
async def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user