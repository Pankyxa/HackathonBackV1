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
from src.models import User, FileType, FileOwnerType, File as FileModel, ParticipantInfo
from src.models.user import User2Roles, MentorInfo, UserStatusHistory
from src.schemas.user import UserCreate, UserLogin, Token, UserResponse, UserResponseRegister, MentorCreate
from src.auth.jwt import create_access_token, get_current_user

from src.utils.router_states import file_router_state, user_router_state

security = HTTPBearer()
router = APIRouter(prefix="/auth", tags=["auth"])


async def save_file(
        upload_file: UploadFile,
        owner_id: uuid.UUID,
        file_type: FileType,
        owner_type: FileOwnerType
) -> FileModel:
    """Сохранение файла с указанием владельца"""
    owner_type_id = (file_router_state.user_owner_type_id
                     if owner_type == FileOwnerType.USER
                     else file_router_state.team_owner_type_id)

    if file_type == FileType.CONSENT:
        file_type_id = file_router_state.consent_type_id
    elif file_type == FileType.EDUCATION_CERTIFICATE:
        file_type_id = file_router_state.education_certificate_type_id
    elif file_type == FileType.TEAM_LOGO:
        file_type_id = file_router_state.team_logo_type_id
    elif file_type == FileType.JOB_CERTIFICATE:
        file_type_id = file_router_state.job_certificate_type_id
    else:
        raise ValueError(f"Неизвестный тип файла: {file_type}")

    base_dir = "uploads/users" if owner_type_id == file_router_state.user_owner_type_id else "uploads/teams"
    upload_dir = f"{base_dir}/{owner_id}"
    os.makedirs(upload_dir, exist_ok=True)

    file_extension = os.path.splitext(upload_file.filename)[1]
    file_name = f"{uuid.uuid4()}{file_extension}"
    file_path = os.path.join(upload_dir, file_name)

    async with aiofiles.open(file_path, 'wb') as out_file:
        content = await upload_file.read()
        await out_file.write(content)

    file_format_id = file_router_state.pdf_format_id if file_extension.lower() == '.pdf' else file_router_state.image_format_id

    file_model = FileModel(
        id=uuid.uuid4(),
        filename=upload_file.filename,
        file_path=file_path,
        file_format_id=file_format_id,
        file_type_id=file_type_id,
        owner_type_id=owner_type_id,
        user_id=owner_id if owner_type == FileOwnerType.USER else None,
        team_id=owner_id if owner_type == FileOwnerType.TEAM else None
    )

    return file_model


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

    query = select(User).where(User.email == user_data.email)
    result = await session.execute(query)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email уже зарегистрирован"
        )

    user = User(
        id=uuid.uuid4(),
        email=user_data.email,
        password=get_password_hash(user_data.password),
        full_name=user_data.full_name,
        current_status_id=user_router_state.pending_status_id,
    )

    status_history = UserStatusHistory(
        id=uuid.uuid4(),
        user_id=user.id,
        status_id=user_router_state.pending_status_id,
        comment="Начальный статус при регистрации"
    )

    participant_info = ParticipantInfo(
        id=uuid.uuid4(),
        user_id=user.id,
        number=user_data.number,
        vuz=user_data.vuz,
        vuz_direction=user_data.vuz_direction,
        code_speciality=user_data.code_speciality,
        course=user_data.course
    )

    role = User2Roles(
        id=uuid.uuid4(),
        user_id=user.id,
        role_id=user_router_state.participant_role_id,
    )

    session.add(user)
    session.add(status_history)
    session.add(participant_info)
    session.add(role)

    consent_file_model = await save_file(consent_file, user.id, FileType.CONSENT, FileOwnerType.USER)
    education_file_model = await save_file(education_certificate_file, user.id, FileType.EDUCATION_CERTIFICATE,
                                           FileOwnerType.USER)

    session.add(consent_file_model)
    session.add(education_file_model)

    await session.commit()
    await session.refresh(user)

    query = (
        select(User)
        .options(
            selectinload(User.files).selectinload(FileModel.file_format),
            selectinload(User.files).selectinload(FileModel.file_type),
            selectinload(User.files).selectinload(FileModel.owner_type),
            selectinload(User.participant_info),
            selectinload(User.user2roles).selectinload(User2Roles.role),
            selectinload(User.current_status),
            selectinload(User.status_history).selectinload(UserStatusHistory.status),
        )
        .where(User.id == user.id)
    )
    result = await session.execute(query)
    user_with_data = result.scalar_one()
    user_with_data.mentor_info = None
    return user_with_data


@router.post("/register/mentor", response_model=UserResponseRegister)
async def register_mentor(
        email: str = Form(...),
        password: str = Form(...),
        full_name: str = Form(...),
        number: str = Form(...),
        job: str = Form(...),
        job_title: str = Form(...),
        consent_file: UploadFile = File(...),
        job_certificate_file: UploadFile = File(...),
        session: AsyncSession = Depends(get_session)
):
    mentor_data = MentorCreate(
        email=email,
        password=password,
        full_name=full_name,
        number=number,
        job=job,
        job_title=job_title
    )

    query = select(User).where(User.email == mentor_data.email)
    result = await session.execute(query)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email уже зарегистрирован"
        )

    user = User(
        id=uuid.uuid4(),
        email=mentor_data.email,
        password=get_password_hash(mentor_data.password),
        full_name=mentor_data.full_name,
        current_status_id=user_router_state.pending_status_id,
    )

    status_history = UserStatusHistory(
        id=uuid.uuid4(),
        user_id=user.id,
        status_id=user_router_state.pending_status_id,
        comment="Начальный статус при регистрации ментора"
    )

    mentor_info = MentorInfo(
        id=uuid.uuid4(),
        user_id=user.id,
        number=mentor_data.number,
        job=mentor_data.job,
        job_title=mentor_data.job_title
    )

    role = User2Roles(
        id=uuid.uuid4(),
        user_id=user.id,
        role_id=user_router_state.mentor_role_id,
    )

    session.add(user)
    session.add(status_history)
    session.add(mentor_info)
    session.add(role)

    consent_file_model = await save_file(consent_file, user.id, FileType.CONSENT, FileOwnerType.USER)
    job_certificate_model = await save_file(job_certificate_file, user.id, FileType.JOB_CERTIFICATE, FileOwnerType.USER)

    session.add(consent_file_model)
    session.add(job_certificate_model)

    await session.commit()
    await session.refresh(user)

    query = (
        select(User)
        .options(
            selectinload(User.files).selectinload(FileModel.file_format),
            selectinload(User.files).selectinload(FileModel.file_type),
            selectinload(User.files).selectinload(FileModel.owner_type),
            selectinload(User.mentor_info),
            selectinload(User.user2roles).selectinload(User2Roles.role),
            selectinload(User.current_status),
            selectinload(User.status_history).selectinload(UserStatusHistory.status),
        )
        .where(User.id == user.id)
    )
    result = await session.execute(query)
    user_with_data = result.scalar_one()
    user_with_data.participant_info = None
    return user_with_data


@router.post("/register/special", response_model=UserResponseRegister)
async def register_special(
        email: str = Form(...),
        password: str = Form(...),
        full_name: str = Form(...),
        session: AsyncSession = Depends(get_session)
):
    query = select(User).where(User.email == email)
    result = await session.execute(query)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email уже зарегистрирован"
        )

    user = User(
        id=uuid.uuid4(),
        email=email,
        password=get_password_hash(password),
        full_name=full_name,
        current_status_id=user_router_state.approved_status_id,
    )

    status_history = UserStatusHistory(
        id=uuid.uuid4(),
        user_id=user.id,
        status_id=user_router_state.approved_status_id,
        comment="Начальный статус при регистрации специального пользователя - подтвержден"
    )

    session.add(user)
    session.add(status_history)

    await session.commit()
    await session.refresh(user)

    query = (
        select(User)
        .options(
            selectinload(User.files).selectinload(FileModel.file_format),
            selectinload(User.files).selectinload(FileModel.file_type),
            selectinload(User.files).selectinload(FileModel.owner_type),
            selectinload(User.user2roles).selectinload(User2Roles.role),
            selectinload(User.current_status),
            selectinload(User.status_history).selectinload(UserStatusHistory.status),
        )
        .where(User.id == user.id)
    )
    result = await session.execute(query)
    user_with_data = result.scalar_one()

    user_with_data.participant_info = None
    user_with_data.mentor_info = None

    return user_with_data


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
    query = (
        select(User)
        .options(
            selectinload(User.files),
            selectinload(User.participant_info),
            selectinload(User.mentor_info),
            selectinload(User.user2roles).selectinload(User2Roles.role),
            selectinload(User.current_status),
            selectinload(User.status_history).selectinload(UserStatusHistory.status),
        )
        .where(User.id == current_user.id)
    )
    result = await session.execute(query)
    user = result.scalar_one_or_none()
    print(user.roles)
    return user
