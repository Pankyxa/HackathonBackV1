from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.security import HTTPBearer
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid
import os
import aiofiles

from src.auth.utils import verify_password, get_password_hash
from src.db import get_session
from src.models import User, FileFormat, FileType, File as FileModel
from src.schemas.user import UserCreate, UserLogin, Token, UserResponse, UserResponseRegister
from src.auth.jwt import create_access_token, get_current_user

security = HTTPBearer()
router = APIRouter(prefix="/auth", tags=["auth"])


# Функция для сохранения файла
async def save_file(upload_file: UploadFile, user_id: uuid.UUID, file_type: FileType) -> FileModel:
    # Создаем директорию для файлов пользователя, если её нет
    upload_dir = f"uploads/{user_id}"
    os.makedirs(upload_dir, exist_ok=True)

    # Получаем расширение файла
    file_extension = os.path.splitext(upload_file.filename)[1]
    # Создаем уникальное имя файла
    file_name = f"{uuid.uuid4()}{file_extension}"
    file_path = os.path.join(upload_dir, file_name)

    # Сохраняем файл
    async with aiofiles.open(file_path, 'wb') as out_file:
        content = await upload_file.read()
        await out_file.write(content)

    # Определяем формат файла по расширению
    file_format = FileFormat.PDF if file_extension.lower() == '.pdf' else FileFormat.IMAGE

    # Создаем запись в базе данных
    return FileModel(
        id=uuid.uuid4(),
        filename=upload_file.filename,
        file_path=file_path,
        file_format=file_format,
        file_type=file_type,
        user_id=user_id
    )


@router.post("/register", response_model=UserResponseRegister)
async def register(
        email: str = Form(...),
        password: str = Form(...),
        number: str = Form(...),
        vuz: str = Form(...),
        vuz_direction: str = Form(...),
        code_speciality: str = Form(...),
        course: str = Form(...),
        full_name: str = Form(None),
        consent_file: UploadFile = File(...),
        education_certificate_file: UploadFile = File(...),
        session: AsyncSession = Depends(get_session)
):
    # Create UserCreate object from form data
    user_data = UserCreate(
        email=email,
        password=password,
        number=number,
        vuz=vuz,
        vuz_direction=vuz_direction,
        code_speciality=code_speciality,
        course=course,
        full_name=full_name
    )

    # Check if email exists
    query = select(User).where(User.email == user_data.email)
    result = await session.execute(query)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email уже зарегистрирован"
        )
    # Create user
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

    # Сохраняем файлы
    consent_file_model = await save_file(consent_file, user.id, FileType.CONSENT)
    education_file_model = await save_file(education_certificate_file, user.id, FileType.EDUCATION_CERTIFICATE)

    # Добавляем файлы в сессию
    session.add(consent_file_model)
    session.add(education_file_model)

    # Сохраняем все изменения
    await session.commit()
    await session.refresh(user)

    # Загружаем пользователя с файлами для ответа
    query = select(User).options(selectinload(User.files)).where(User.id == user.id)
    result = await session.execute(query)
    user_with_files = result.scalar_one()

    return user_with_files


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


@router.get("/me", response_model=UserResponse)
async def read_users_me(
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    # Загружаем пользователя вместе с файлами
    query = select(User).options(selectinload(User.files)).where(User.id == current_user.id)
    result = await session.execute(query)
    user = result.scalar_one_or_none()
    return user
