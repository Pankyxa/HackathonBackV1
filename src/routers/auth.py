from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, BackgroundTasks
from fastapi.security import HTTPBearer
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
import uuid
import os
import aiofiles

from src.auth.utils import verify_password, get_password_hash
from src.db import get_session
from src.models import User, FileType, FileOwnerType, File as FileModel, ParticipantInfo
from src.models.enums import StageType
from src.models.user import User2Roles, MentorInfo, UserStatusHistory, EmailVerificationToken, PasswordResetToken, UserEventStatus
from src.utils.event_utils import get_active_event
from src.schemas.user import UserCreate, UserLogin, Token, UserResponse, UserResponseRegister, MentorCreate
from src.auth.jwt import create_access_token, get_current_user
from src.settings import settings
from src.utils.email_verification import create_verification_token, send_verification_email, verify_email_token
from src.utils.password_reset import (
    create_password_reset_token,
    send_password_reset_email,
    verify_password_reset_token
)
from src.utils.file_utils import save_file

from src.utils.router_states import file_router_state, user_router_state
from src.utils.stage_checker import check_stage
from src.utils.background_tasks import send_registration_confirmation_email, \
    send_single_hackathon_consultation_notification
from src.utils.user_status_utils import get_user_status_for_event, requires_document_check
from src.utils.event_utils import get_active_event

security = HTTPBearer()
router = APIRouter(prefix="/auth", tags=["auth"])


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
        background_tasks: BackgroundTasks = BackgroundTasks(),
        session: AsyncSession = Depends(get_session)
):
    await check_stage(session, StageType.REGISTRATION)

    # Получаем активное событие
    active_event = await get_active_event(session)

    user_data = UserCreate(
        email=email.lower(),
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
    existing_user = result.scalar_one_or_none()
    
    is_new_user = existing_user is None
    
    if is_new_user:
        # Создаем нового пользователя
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
        
        # Создаем UserEventStatus для нового пользователя со статусом pending
        user_event_status = UserEventStatus(
            id=uuid.uuid4(),
            user_id=user.id,
            event_id=active_event.id,
            status_id=user_router_state.pending_status_id
        )
        session.add(user_event_status)
    else:
        # Пользователь уже существует - обновляем данные и создаем UserEventStatus
        user = existing_user
        
        # Загружаем роли пользователя для проверки
        user_with_roles_query = select(User).where(User.id == user.id).options(
            selectinload(User.user2roles).selectinload(User2Roles.role)
        )
        user_result = await session.execute(user_with_roles_query)
        user_with_roles = user_result.scalar_one_or_none()
        
        # Проверяем, есть ли уже статус для этого события
        existing_status_query = select(UserEventStatus).where(
            UserEventStatus.user_id == user.id,
            UserEventStatus.event_id == active_event.id
        )
        existing_status_result = await session.execute(existing_status_query)
        existing_event_status = existing_status_result.scalar_one_or_none()
        
        if existing_event_status:
            # Если статус уже существует, обновляем его только если требуется проверка документов
            if user_with_roles and await requires_document_check(session, user_with_roles):
                # Для участников и наставников - требуется перепроверка документов
                existing_event_status.status_id = user_router_state.need_update_status_id
                existing_event_status.updated_at = datetime.now(timezone.utc)
            # Для остальных ролей статус остается approved (не обновляем)
        else:
            # Определяем статус в зависимости от ролей пользователя
            if user_with_roles and await requires_document_check(session, user_with_roles):
                # Для участников и наставников - требуется проверка документов
                status_id = user_router_state.need_update_status_id
            else:
                # Для остальных (администраторы, организаторы, жюри) - автоматически подтвержден
                status_id = user_router_state.approved_status_id
            
            # Создаем новый статус для события
            user_event_status = UserEventStatus(
                id=uuid.uuid4(),
                user_id=user.id,
                event_id=active_event.id,
                status_id=status_id
            )
            session.add(user_event_status)
        
        # Обновляем participant_info если нужно
        if user.participant_info:
            user.participant_info.number = user_data.number
            user.participant_info.vuz = user_data.vuz
            user.participant_info.vuz_direction = user_data.vuz_direction
            user.participant_info.code_speciality = user_data.code_speciality
            user.participant_info.course = user_data.course
        else:
            participant_info = ParticipantInfo(
                id=uuid.uuid4(),
                user_id=user.id,
                number=user_data.number,
                vuz=user_data.vuz,
                vuz_direction=user_data.vuz_direction,
                code_speciality=user_data.code_speciality,
                course=user_data.course
            )
            session.add(participant_info)
        
        # Добавляем запись в историю статусов
        status_history = UserStatusHistory(
            id=uuid.uuid4(),
            user_id=user.id,
            status_id=user_router_state.need_update_status_id,
            comment=f"Повторная регистрация для события {active_event.name}. Требуется обновление документов."
        )
        session.add(status_history)
        
        # Удаляем старые файлы для существующего пользователя
        if not is_new_user:
            old_files_query = select(FileModel).where(
                and_(
                    FileModel.user_id == user.id,
                    FileModel.owner_type_id == file_router_state.user_owner_type_id,
                    FileModel.file_type_id.in_([
                        file_router_state.consent_type_id,
                        file_router_state.education_certificate_type_id
                    ])
                )
            )
            old_files_result = await session.execute(old_files_query)
            old_files = old_files_result.scalars().all()
            
            for old_file in old_files:
                if os.path.exists(old_file.file_path):
                    os.remove(old_file.file_path)
                await session.delete(old_file)

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

    verification_token = await create_verification_token(user.id, session)

    verification_link = f"{settings.base_url}/auth/verify-email/{verification_token.token}"
    
    # Костыль для разработки: выводим ссылку в терминал
    print(f"\n{'='*80}")
    print(f"[DEV] Email verification link for {user.email}:")
    print(f"{verification_link}")
    print(f"{'='*80}\n")

    background_tasks.add_task(send_registration_confirmation_email, user, verification_link)

    await session.commit()

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
        background_tasks: BackgroundTasks = BackgroundTasks(),
        session: AsyncSession = Depends(get_session)
):
    await check_stage(session, StageType.REGISTRATION)

    mentor_data = MentorCreate(
        email=email.lower(),
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

    # Получаем активное событие для создания UserEventStatus
    active_event = await get_active_event(session)
    
    # Создаем UserEventStatus для нового ментора со статусом pending (требуется проверка документов)
    user_event_status = UserEventStatus(
        id=uuid.uuid4(),
        user_id=user.id,
        event_id=active_event.id,
        status_id=user_router_state.pending_status_id
    )
    session.add(user_event_status)

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

    verification_token = await create_verification_token(user.id, session)

    verification_link = f"{settings.base_url}/auth/verify-email/{verification_token.token}"
    
    # Костыль для разработки: выводим ссылку в терминал
    print(f"\n{'='*80}")
    print(f"[DEV] Email verification link for {user.email}:")
    print(f"{verification_link}")
    print(f"{'='*80}\n")

    background_tasks.add_task(send_registration_confirmation_email, user, verification_link)

    await session.commit()

    return user_with_data


@router.post("/register/special", response_model=UserResponseRegister)
async def register_special(
        email: str = Form(...),
        password: str = Form(...),
        full_name: str = Form(...),
        background_tasks: BackgroundTasks = BackgroundTasks(),
        session: AsyncSession = Depends(get_session)
):
    """Специальная регистрация для жюри и организаторов - доступна всегда, независимо от этапа"""
    query = select(User).where(User.email == email.lower())
    result = await session.execute(query)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email уже зарегистрирован"
        )

    user = User(
        id=uuid.uuid4(),
        email=email.lower(),
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
    
    # Получаем активное событие для создания UserEventStatus (если есть)
    try:
        active_event = await get_active_event(session)
        # Для специальных пользователей (жюри, организаторы) статус всегда approved
        user_event_status = UserEventStatus(
            id=uuid.uuid4(),
            user_id=user.id,
            event_id=active_event.id,
            status_id=user_router_state.approved_status_id
        )
        session.add(user_event_status)
    except Exception:
        # Если активного события нет, просто пропускаем создание UserEventStatus
        pass

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

    verification_token = await create_verification_token(user.id, session)

    verification_link = f"{settings.base_url}/auth/verify-email/{verification_token.token}"
    
    # Костыль для разработки: выводим ссылку в терминал
    print(f"\n{'='*80}")
    print(f"[DEV] Email verification link for {user.email}:")
    print(f"{verification_link}")
    print(f"{'='*80}\n")

    background_tasks.add_task(send_registration_confirmation_email, user, verification_link)

    await session.commit()

    return user_with_data


@router.post("/login", response_model=Token)
async def login(user_data: UserLogin, session: AsyncSession = Depends(get_session)):
    query = select(User).where(User.email == user_data.email.lower())
    result = await session.execute(query)
    user = result.scalar_one_or_none()

    if not user or not verify_password(user_data.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email не подтвержден. Пожалуйста, проверьте вашу почту или запросите новое письмо для подтверждения.",
        )

    access_token = create_access_token(
        data={"sub": user.email}
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/forgot-password")
async def forgot_password(
        email: str = Form(...),
        background_tasks: BackgroundTasks = BackgroundTasks(),
        session: AsyncSession = Depends(get_session)
):
    """
    Запрос на восстановление пароля.
    Отправляет email со ссылкой для сброса пароля.
    Для безопасности всегда возвращает успешный ответ, даже если email не найден.
    """
    query = select(User).where(User.email == email.lower())
    result = await session.execute(query)
    user = result.scalar_one_or_none()

    # Для безопасности не сообщаем, существует ли пользователь
    if user:
        # Проверяем, был ли создан токен восстановления пароля в последние 5 минут
        # Проверяем все токены (включая использованные), так как ограничение по времени создания
        recent_token_query = (
            select(PasswordResetToken)
            .where(
                and_(
                    PasswordResetToken.user_id == user.id,
                    PasswordResetToken.created_at >= datetime.now(timezone.utc) - timedelta(minutes=5)
                )
            )
            .order_by(PasswordResetToken.created_at.desc())
        )
        result = await session.execute(recent_token_query)
        recent_tokens = result.scalars().all()

        if recent_tokens:
            # Логируем для отладки
            print(f"[DEBUG] Found {len(recent_tokens)} recent password reset tokens for user {user.email}")
            for token in recent_tokens:
                print(f"[DEBUG] Token created at: {token.created_at}, used: {token.used}")
            
            # Возвращаем ошибку, как для повторной отправки письма подтверждения
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Письмо с восстановлением пароля уже было отправлено недавно. Пожалуйста, подождите 5 минут перед повторной попыткой."
            )

        try:
            reset_token = await create_password_reset_token(user.id, session)
            await session.flush()  # Сначала flush, чтобы токен был доступен для проверки
            await session.commit()

            # Костыль для разработки: выводим ссылку в терминал
            reset_link = f"{settings.base_url}/auth/reset-password/{reset_token.token}"
            print(f"\n{'='*80}")
            print(f"[DEV] Password reset link for {user.email}:")
            print(f"{reset_link}")
            print(f"{'='*80}\n")

            background_tasks.add_task(
                send_password_reset_email,
                user.email,
                user.full_name or "Пользователь",
                reset_token.token
            )
        except Exception as e:
            # Логируем ошибку, но не раскрываем информацию пользователю
            print(f"Error creating password reset token: {e}")
            await session.rollback()

    # Всегда возвращаем успешный ответ для безопасности
    return {
        "message": "Если указанный email зарегистрирован в системе, на него будет отправлено письмо с инструкциями по восстановлению пароля"
    }


@router.post("/reset-password/{token}")
async def reset_password(
        token: str,
        new_password: str = Form(...),
        session: AsyncSession = Depends(get_session)
):
    """
    Сброс пароля по токену.
    """
    if len(new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пароль должен содержать минимум 6 символов"
        )

    try:
        user = await verify_password_reset_token(token, session)
    except HTTPException:
        raise

    # Деактивируем токен
    reset_token_query = (
        select(PasswordResetToken)
        .where(PasswordResetToken.token == token)
    )
    result = await session.execute(reset_token_query)
    reset_token = result.scalar_one()
    reset_token.used = True

    # Обновляем пароль
    user.password = get_password_hash(new_password)
    await session.commit()

    return {"message": "Пароль успешно изменен"}


@router.get("/me", response_model=UserResponse)
async def read_users_me(
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    query = (
        select(User)
        .options(
            selectinload(User.files).selectinload(FileModel.file_format),
            selectinload(User.files).selectinload(FileModel.file_type),
            selectinload(User.files).selectinload(FileModel.owner_type),
            selectinload(User.participant_info),
            selectinload(User.mentor_info),
            selectinload(User.user2roles).selectinload(User2Roles.role),
            selectinload(User.current_status),  # Для обратной совместимости
            selectinload(User.event_statuses).selectinload(UserEventStatus.status),
            selectinload(User.event_statuses).selectinload(UserEventStatus.event),
            selectinload(User.status_history).selectinload(UserStatusHistory.status),
        )
        .where(User.id == current_user.id)
    )
    result = await session.execute(query)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Обновляем current_status на статус для активного события
    try:
        active_event = await get_active_event(session)
        user_status = await get_user_status_for_event(session, user.id, active_event.id)
        if user_status:
            user.current_status = user_status
    except Exception:
        # Если активного события нет, оставляем глобальный статус
        pass

    is_mentor = any(role.role_id == user_router_state.mentor_role_id for role in user.user2roles)
    is_participant = any(role.role_id == user_router_state.participant_role_id for role in user.user2roles)

    if is_mentor and not is_participant:
        user.participant_info = None
    elif is_participant and not is_mentor:
        user.mentor_info = None
    elif not is_mentor and not is_participant:
        user.participant_info = None
        user.mentor_info = None

    return user


@router.get("/verify-email/{token}")
async def verify_email(
        token: str,
        session: AsyncSession = Depends(get_session)
):
    """Подтверждение email адреса"""
    user = await verify_email_token(token, session)
    await session.commit()
    return {"message": "Email успешно подтвержден"}


@router.post("/resend-verification")
async def resend_verification(
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Повторная отправка письма для подтверждения email"""
    if current_user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email уже подтвержден"
        )

    verification_token = await create_verification_token(current_user.id, session)
    
    verification_link = f"{settings.base_url}/auth/verify-email/{verification_token.token}"
    
    # Костыль для разработки: выводим ссылку в терминал
    print(f"\n{'='*80}")
    print(f"[DEV] Email verification link for {current_user.email}:")
    print(f"{verification_link}")
    print(f"{'='*80}\n")

    if await send_verification_email(current_user.email, current_user.full_name, verification_token.token):
        await session.commit()
        return {"message": "Письмо с подтверждением отправлено"}
    else:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка при отправке письма"
        )


@router.post("/resend-verification-email")
async def resend_verification_email(
        email: str = Form(...),
        background_tasks: BackgroundTasks = BackgroundTasks(),
        session: AsyncSession = Depends(get_session)
):
    """
    Повторная отправка письма для подтверждения email по email адресу.
    Не требует аутентификации.
    """
    query = (
        select(User)
        .where(User.email == email)
    )
    result = await session.execute(query)
    user = result.scalar_one_or_none()

    if not user:
        return {
            "message": "Если указанный email зарегистрирован в системе, на него будет отправлено письмо с подтверждением"}

    if user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email уже подтвержден"
        )

    recent_token_query = (
        select(EmailVerificationToken)
        .where(
            and_(
                EmailVerificationToken.user_id == user.id,
                EmailVerificationToken.used == False,
                EmailVerificationToken.created_at >= datetime.now(timezone.utc) - timedelta(minutes=5)
            )
        )
    )
    result = await session.execute(recent_token_query)
    recent_token = result.scalar_one_or_none()

    if recent_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Письмо с подтверждением уже было отправлено недавно. Пожалуйста, подождите 5 минут перед повторной попыткой."
        )

    verification_token = await create_verification_token(user.id, session)

    verification_link = f"{settings.base_url}/auth/verify-email/{verification_token.token}"
    
    # Костыль для разработки: выводим ссылку в терминал
    print(f"\n{'='*80}")
    print(f"[DEV] Email verification link for {user.email}:")
    print(f"{verification_link}")
    print(f"{'='*80}\n")

    background_tasks.add_task(send_registration_confirmation_email, user, verification_link)

    await session.commit()


@router.post("/test-email")
async def send_test_email(
        email: str = Form(...),
        session: AsyncSession = Depends(get_session)
):
    """
    Отправка тестового письма на указанный email.
    Используется для проверки работы системы отправки писем.
    """
    try:
        test_user = User(
            id=uuid.uuid4(),
            email=email,
            password="test",
            full_name="Test User",
            current_status_id=user_router_state.pending_status_id,
        )

        verification_token = EmailVerificationToken(
            user_id=test_user.id,
            token=str(uuid.uuid4()),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24)
        )

        if await send_verification_email(email, "Test User", verification_token.token):
            return {
                "message": "Тестовое письмо успешно отправлено",
                "email": email
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Ошибка при отправке тестового письма"
            )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка при отправке тестового письма: {str(e)}"
        )
