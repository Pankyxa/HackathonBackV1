import asyncio
import os
import uuid

from fastapi import APIRouter, Depends, Query, HTTPException, Form, UploadFile, File, BackgroundTasks
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_, not_, exists, func, delete
from sqlalchemy.orm import selectinload
from typing import List, Optional

from starlette import status

from src.auth.jwt import get_current_user
from src.db import get_session
from src.models import User, TeamMember, File as FileModel, UserStatus, Team, Stage
from src.models.enums import StageType
from src.models.user import User2Roles, UserStatusHistory, UserStatusType
from src.schemas.file import FileResponse
from src.schemas.user import UserResponse, PaginatedUserResponse, ChangeUserStatusRequest, UpdateUserRolesRequest, \
    UpdateUserDocumentsRequest
from src.utils.background_tasks import send_status_change_email, send_team_confirmation_email
from src.utils.router_states import team_router_state, user_router_state, file_router_state, stage_router_state
from src.utils.stage_checker import check_stage

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/search", response_model=List[UserResponse])
async def search_users(
        query: str = Query(..., min_length=2, description="Search query for user full name"),
        limit: int = Query(default=10, le=50, description="Number of results to return"),
        offset: int = Query(default=0, description="Number of results to skip"),
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """
    Поиск пользователей по ФИО с пагинацией.
    """
    search_query = f"%{query}%"

    current_user_team = (
        select(TeamMember.team_id)
        .where(
            and_(
                TeamMember.user_id == current_user.id,
                TeamMember.status_id == team_router_state.accepted_status_id
            )
        )
    )

    stmt = (
        select(User)
        .options(
            selectinload(User.participant_info),
            selectinload(User.mentor_info),
            selectinload(User.user2roles).selectinload(User2Roles.role),
            selectinload(User.current_status),
            selectinload(User.status_history).selectinload(UserStatusHistory.status),
        )
        .where(
            and_(
                User.full_name.ilike(search_query),
                User.id != current_user.id,
                exists(
                    select(1)
                    .where(
                        User2Roles.user_id == User.id,
                        User2Roles.role_id == user_router_state.participant_role_id
                    )
                ),
                not_(
                    exists(
                        select(1)
                        .where(
                            TeamMember.user_id == User.id,
                            TeamMember.status_id == team_router_state.accepted_status_id,
                            TeamMember.team_id == TeamMember.team_id,
                        )
                    )
                ),
                not_(
                    exists(
                        select(1)
                        .where(
                            TeamMember.user_id == User.id,
                            TeamMember.team_id.in_(current_user_team),
                            or_(
                                TeamMember.status_id == team_router_state.accepted_status_id,
                                TeamMember.status_id == team_router_state.pending_status_id
                            )
                        )
                    )
                )
            )
        )
        .limit(limit)
        .offset(offset)
        .order_by(User.full_name)
    )

    result = await session.execute(stmt)
    users = result.scalars().all()

    return users


@router.get("/search/mentors", response_model=List[UserResponse])
async def search_mentors(
        query: str = Query(..., min_length=2, description="Search query for mentor full name"),
        limit: int = Query(default=10, le=50, description="Number of results to return"),
        offset: int = Query(default=0, description="Number of results to skip"),
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """
    Поиск менторов по ФИО с пагинацией.
    В отличие от поиска обычных пользователей:
    - Ищет только пользователей с ролью ментора
    - Может возвращать менторов, которые уже состоят в других командах
    """
    search_query = f"%{query}%"

    current_user_team = (
        select(TeamMember.team_id)
        .where(
            and_(
                TeamMember.user_id == current_user.id,
                TeamMember.status_id == team_router_state.accepted_status_id
            )
        )
    )

    stmt = (
        select(User)
        .options(
            selectinload(User.participant_info),
            selectinload(User.mentor_info),
            selectinload(User.user2roles).selectinload(User2Roles.role),
            selectinload(User.current_status),
            selectinload(User.status_history).selectinload(UserStatusHistory.status),
        )
        .where(
            and_(
                User.full_name.ilike(search_query),
                User.id != current_user.id,
                exists(
                    select(1)
                    .where(
                        User2Roles.user_id == User.id,
                        User2Roles.role_id == user_router_state.mentor_role_id
                    )
                )
            ),
            not_(
                exists(
                    select(1)
                    .where(
                        TeamMember.user_id == User.id,
                        TeamMember.team_id.in_(current_user_team),
                        or_(
                            TeamMember.status_id == team_router_state.accepted_status_id,
                            TeamMember.status_id == team_router_state.pending_status_id
                        )
                    )
                )
            )
        )
        .limit(limit)
        .offset(offset)
        .order_by(User.full_name)
    )

    result = await session.execute(stmt)
    mentors = result.scalars().all()

    return mentors


@router.get("/all", response_model=PaginatedUserResponse)
async def get_users(
        limit: int = Query(default=10, le=50, description="Number of results to return"),
        offset: int = Query(default=0, description="Number of results to skip"),
        search: Optional[str] = Query(None, min_length=2,
                                      description="Optional search query for user full name or email"),
        roles: Optional[List[str]] = Query(None,
                                           description="Filter by user roles. Use '-' to find users without roles"),
        statuses: Optional[List[UserStatus]] = Query(None, description="Filter by user statuses"),
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """
    Получение списка всех пользователей с пагинацией и фильтрацией.
    Поддерживает:
    - Поиск по ФИО или email
    - Фильтрацию по ролям (используйте '-' для поиска пользователей без ролей)
    - Фильтрацию по статусам
    """
    query = select(User).options(
        selectinload(User.participant_info),
        selectinload(User.mentor_info),
        selectinload(User.user2roles).selectinload(User2Roles.role),
        selectinload(User.current_status),
        selectinload(User.status_history).selectinload(UserStatusHistory.status),
    )

    if search:
        search_query = f"%{search}%"
        query = query.where(
            or_(
                User.full_name.ilike(search_query),
                User.email.ilike(search_query)
            )
        )

    if roles:
        if "-" in roles:
            query = query.where(
                not_(
                    exists(
                        select(1)
                        .where(User2Roles.user_id == User.id)
                    )
                )
            )
            roles = [role for role in roles if role != "-"]

        if roles:
            role_ids = []
            for role_name in roles:
                role_id = getattr(user_router_state, f"{role_name}_role_id", None)
                if role_id is not None:
                    role_ids.append(role_id)

            if role_ids:
                query = query.where(
                    exists(
                        select(1)
                        .where(
                            and_(
                                User2Roles.user_id == User.id,
                                User2Roles.role_id.in_(role_ids)
                            )
                        )
                    )
                )

    if statuses:
        status_ids = []
        for status in statuses:
            if status == UserStatus.PENDING:
                status_ids.append(user_router_state.pending_status_id)
            elif status == UserStatus.APPROVED:
                status_ids.append(user_router_state.approved_status_id)
            elif status == UserStatus.NEED_UPDATE:
                status_ids.append(user_router_state.need_update_status_id)

        if status_ids:
            query = query.where(User.current_status_id.in_(status_ids))

    count_query = select(func.count()).select_from(query.subquery())
    total = await session.scalar(count_query)

    query = query.order_by(User.full_name) \
        .limit(limit) \
        .offset(offset)

    result = await session.execute(query)
    users = result.scalars().all()

    return {
        "users": users,
        "total": total
    }


@router.get("/pending", response_model=PaginatedUserResponse)
async def get_pending_users(
        limit: int = Query(default=10, le=50, description="Number of results to return"),
        offset: int = Query(default=0, description="Number of results to skip"),
        search: Optional[str] = Query(None, min_length=2,
                                      description="Optional search query for user full name or email"),
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """
    Получение списка пользователей со статусом PENDING.
    Поддерживает пагинацию и опциональный поиск по ФИО или email.
    """
    base_query = (
        select(User)
        .where(User.current_status_id == user_router_state.pending_status_id)
    )

    if search:
        search_query = f"%{search}%"
        base_query = base_query.where(
            or_(
                User.full_name.ilike(search_query),
                User.email.ilike(search_query)
            )
        )

    count_query = select(func.count()).select_from(base_query.subquery())
    total = await session.scalar(count_query)

    query = (
        base_query
        .options(
            selectinload(User.participant_info),
            selectinload(User.mentor_info),
            selectinload(User.user2roles).selectinload(User2Roles.role),
            selectinload(User.current_status),
            selectinload(User.status_history).selectinload(UserStatusHistory.status),
        )
        .order_by(User.registered_at.desc())
        .limit(limit)
        .offset(offset)
    )

    result = await session.execute(query)
    users = result.scalars().all()

    return {
        "users": users,
        "total": total
    }


@router.get("/{user_id}/documents", response_model=List[FileResponse])
async def get_user_documents(
        user_id: uuid.UUID,
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """
    Получение документов пользователя (согласие и справка с места учебы/работы)
    """
    current_user_query = (
        select(User)
        .options(selectinload(User.user2roles))
        .where(User.id == current_user.id)
    )
    result = await session.execute(current_user_query)
    current_user_with_roles = result.scalar_one()

    is_organizer = any(
        role.role_id == user_router_state.organizer_role_id
        for role in current_user_with_roles.user2roles
    )
    is_admin = any(
        role.role_id == user_router_state.admin_role_id
        for role in current_user_with_roles.user2roles
    )

    if current_user.id != user_id and not (is_organizer or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав для просмотра документов"
        )

    query = (
        select(FileModel)
        .options(
            selectinload(FileModel.file_format),
            selectinload(FileModel.file_type),
            selectinload(FileModel.owner_type)
        )
        .where(
            and_(
                FileModel.user_id == user_id,
                FileModel.owner_type_id == file_router_state.user_owner_type_id,
                FileModel.file_type_id.in_([
                    file_router_state.consent_type_id,
                    file_router_state.education_certificate_type_id,
                    file_router_state.job_certificate_type_id
                ])
            )
        )
    )

    result = await session.execute(query)
    documents = result.scalars().all()

    return documents


@router.put("/{user_id}/status", response_model=UserResponse)
async def change_user_status(
        user_id: uuid.UUID,
        status_request: ChangeUserStatusRequest,
        current_user: User = Depends(get_current_user),
        background_tasks: BackgroundTasks = BackgroundTasks(),
        session: AsyncSession = Depends(get_session)
):
    """Изменение статуса пользователя (доступно только для организаторов)"""
    await check_stage(session, StageType.REGISTRATION)

    current_user_query = (
        select(User)
        .options(selectinload(User.user2roles))
        .where(User.id == current_user.id)
    )
    result = await session.execute(current_user_query)
    current_user_with_roles = result.scalar_one()

    is_organizer = any(
        role.role_id == user_router_state.organizer_role_id
        for role in current_user_with_roles.user2roles
    )
    if not is_organizer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только организаторы могут изменять статус пользователей"
        )

    user_query = (
        select(User)
        .options(
            selectinload(User.participant_info),
            selectinload(User.mentor_info),
            selectinload(User.user2roles).selectinload(User2Roles.role),
            selectinload(User.current_status),
            selectinload(User.status_history).selectinload(UserStatusHistory.status),
        )
        .where(User.id == user_id)
    )
    result = await session.execute(user_query)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )

    status_id = None
    if status_request.status == UserStatus.PENDING:
        status_id = user_router_state.pending_status_id
    elif status_request.status == UserStatus.APPROVED:
        status_id = user_router_state.approved_status_id
    elif status_request.status == UserStatus.NEED_UPDATE:
        status_id = user_router_state.need_update_status_id

    if not status_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный статус"
        )

    old_status_id = user.current_status_id

    new_status_history = UserStatusHistory(
        user_id=user.id,
        status_id=status_id,
        comment=status_request.comment
    )
    session.add(new_status_history)
    user.current_status_id = status_id

    await session.flush()
    await session.commit()

    async with AsyncSession(session.bind) as new_session:
        await asyncio.sleep(0.5)

        if (old_status_id != status_id and
                status_id == user_router_state.approved_status_id):

            teams_query = (
                select(Team)
                .options(
                    selectinload(Team.members)
                    .selectinload(TeamMember.user)
                    .selectinload(User.current_status),
                    selectinload(Team.members)
                    .selectinload(TeamMember.role),
                    selectinload(Team.members)
                    .selectinload(TeamMember.status)
                )
            )
            result = await new_session.execute(teams_query)
            teams = result.scalars().all()

            for team in teams:
                await new_session.refresh(team)
                for member in team.members:
                    await new_session.refresh(member)
                    await new_session.refresh(member.user)

            active_teams = [team for team in teams if team.get_status() == "active"]
            active_teams_count = len(active_teams)
            print('\n', active_teams_count, '\n')

            if active_teams_count >= 20:
                current_stage_query = select(Stage).where(Stage.is_active == True)
                current_stage = await new_session.execute(current_stage_query)
                current_stage = current_stage.scalar_one_or_none()

                if current_stage and current_stage.type == StageType.REGISTRATION.value:
                    registration_closed_stage_query = (
                        select(Stage)
                        .where(Stage.type == StageType.REGISTRATION_CLOSED.value)
                    )
                    registration_closed_stage = await new_session.execute(registration_closed_stage_query)
                    registration_closed_stage = registration_closed_stage.scalar_one_or_none()

                    if registration_closed_stage:
                        current_stage.is_active = False
                        registration_closed_stage.is_active = True
                        await stage_router_state.initialize(new_session)

                        background_tasks.add_task(send_team_confirmation_email, new_session)
                        await new_session.commit()

    await session.refresh(user)
    return user


@router.put("/{user_id}/roles", response_model=UserResponse)
async def update_user_roles(
        user_id: uuid.UUID,
        roles_request: UpdateUserRolesRequest,
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """
    Обновление ролей пользователя (доступно только для администраторов)
    """
    current_user_query = (
        select(User)
        .options(selectinload(User.user2roles))
        .where(User.id == current_user.id)
    )
    result = await session.execute(current_user_query)
    current_user_with_roles = result.scalar_one()

    is_admin = any(
        role.role_id == user_router_state.admin_role_id
        for role in current_user_with_roles.user2roles
    )

    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только администраторы могут изменять роли пользователей"
        )

    role_ids = set()
    for role_name in roles_request.roles:
        role_id = getattr(user_router_state, f"{role_name}_role_id", None)
        if role_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Неверная роль: {role_name}"
            )
        role_ids.add(role_id)

    await session.execute(
        delete(User2Roles).where(User2Roles.user_id == user_id)
    )

    for role_id in role_ids:
        new_role = User2Roles(
            user_id=user_id,
            role_id=role_id
        )
        session.add(new_role)

    await session.commit()

    user_query = (
        select(User)
        .options(
            selectinload(User.participant_info),
            selectinload(User.mentor_info),
            selectinload(User.user2roles).selectinload(User2Roles.role),
            selectinload(User.current_status),
            selectinload(User.status_history).selectinload(UserStatusHistory.status),
        )
        .where(User.id == user_id)
    )

    result = await session.execute(user_query)
    updated_user = result.scalar_one_or_none()

    if not updated_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )

    return updated_user


@router.put("/me", response_model=UserResponse)
async def update_current_user(
        user_data: dict,
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """
    Обновление данных текущего пользователя.
    Пользователь может обновить свои основные данные и информацию в зависимости от роли
    (participant_info для участников или mentor_info для менторов)
    """
    await check_stage(session, StageType.REGISTRATION)

    user_query = (
        select(User)
        .options(
            selectinload(User.participant_info),
            selectinload(User.mentor_info),
            selectinload(User.user2roles).selectinload(User2Roles.role),
            selectinload(User.current_status),
            selectinload(User.status_history).selectinload(UserStatusHistory.status),
        )
        .where(User.id == current_user.id)
    )

    result = await session.execute(user_query)
    user = result.scalar_one()

    if 'full_name' in user_data:
        user.full_name = user_data['full_name']

    if user.participant_info and 'participant_info' in user_data:
        participant_data = user_data['participant_info']
        if 'number' in participant_data:
            user.participant_info.number = participant_data['number']
        if 'vuz' in participant_data:
            user.participant_info.vuz = participant_data['vuz']
        if 'vuz_direction' in participant_data:
            user.participant_info.vuz_direction = participant_data['vuz_direction']
        if 'code_speciality' in participant_data:
            user.participant_info.code_speciality = participant_data['code_speciality']
        if 'course' in participant_data:
            user.participant_info.course = participant_data['course']

    if user.mentor_info and 'mentor_info' in user_data:
        mentor_data = user_data['mentor_info']
        if 'number' in mentor_data:
            user.mentor_info.number = mentor_data['number']
        if 'job' in mentor_data:
            user.mentor_info.job = mentor_data['job']
        if 'job_title' in mentor_data:
            user.mentor_info.job_title = mentor_data['job_title']

    try:
        await session.commit()

        refresh_query = (
            select(User)
            .options(
                selectinload(User.participant_info),
                selectinload(User.mentor_info),
                selectinload(User.user2roles).selectinload(User2Roles.role),
                selectinload(User.current_status),
                selectinload(User.status_history).selectinload(UserStatusHistory.status),
            )
            .where(User.id == current_user.id)
        )

        result = await session.execute(refresh_query)
        updated_user = result.scalar_one()

        return updated_user
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ошибка при обновлении данных пользователя"
        )


@router.put("/me/documents", response_model=UserResponse)
async def update_user_documents(
        document_type: str = Form(...),  # 'consent' или 'certificate'
        file: UploadFile = File(...),
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """
    Обновление документов текущего пользователя (согласие и справка с места учебы/работы).
    Принимает файл и тип документа (consent или certificate).
    """
    await check_stage(session, StageType.REGISTRATION)

    if document_type not in ['consent', 'certificate']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный тип документа. Допустимые значения: consent, certificate"
        )

    user_query = (
        select(User)
        .options(
            selectinload(User.user2roles)
        )
        .where(User.id == current_user.id)
    )
    result = await session.execute(user_query)
    user_with_roles = result.scalar_one()

    if document_type == 'consent':
        file_type_id = file_router_state.consent_type_id
    else:
        is_participant = any(
            role.role_id == user_router_state.participant_role_id
            for role in user_with_roles.user2roles
        )
        file_type_id = (
            file_router_state.education_certificate_type_id if is_participant
            else file_router_state.job_certificate_type_id
        )

    file_extension = Path(file.filename).suffix.lower()
    if file_extension not in ['.pdf', '.jpg', '.jpeg', '.png']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неподдерживаемый формат файла. Допустимые форматы: PDF, JPG, PNG"
        )

    file_format_id = None
    if file_extension == '.pdf':
        file_format_id = file_router_state.pdf_format_id
    elif file_extension in ['.jpg', '.jpeg']:
        file_format_id = file_router_state.jpg_format_id
    elif file_extension == '.png':
        file_format_id = file_router_state.png_format_id

    existing_file_query = (
        select(FileModel)
        .where(
            and_(
                FileModel.user_id == current_user.id,
                FileModel.file_type_id == file_type_id,
                FileModel.owner_type_id == file_router_state.user_owner_type_id
            )
        )
        .options(
            selectinload(FileModel.file_format),
            selectinload(FileModel.file_type),
            selectinload(FileModel.owner_type)
        )
    )
    result = await session.execute(existing_file_query)
    existing_file = result.scalar_one_or_none()

    upload_dir = Path("uploads/users") / str(current_user.id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_path = upload_dir / f"{document_type}{file_extension}"

    try:
        if existing_file and os.path.exists(existing_file.file_path):
            os.remove(existing_file.file_path)

        contents = await file.read()

        with open(file_path, "wb") as f:
            f.write(contents)

        if existing_file:
            existing_file.filename = file.filename
            existing_file.file_path = str(file_path)
            existing_file.file_format_id = file_format_id
        else:
            new_file = FileModel(
                filename=file.filename,
                file_path=str(file_path),
                file_format_id=file_format_id,
                file_type_id=file_type_id,
                owner_type_id=file_router_state.user_owner_type_id,
                user_id=current_user.id
            )
            session.add(new_file)

        user_query = (
            select(User)
            .options(
                selectinload(User.participant_info),
                selectinload(User.mentor_info),
                selectinload(User.user2roles).selectinload(User2Roles.role),
                selectinload(User.current_status),
                selectinload(User.status_history).selectinload(UserStatusHistory.status),
            )
            .where(User.id == current_user.id)
        )

        result = await session.execute(user_query)
        user = result.scalar_one()

        if user.current_status_id == user_router_state.need_update_status_id:
            new_status_history = UserStatusHistory(
                user_id=user.id,
                status_id=user_router_state.pending_status_id,
                comment="Документы обновлены пользователем"
            )
            session.add(new_status_history)
            user.current_status_id = user_router_state.pending_status_id

        await session.commit()

        refresh_query = (
            select(User)
            .options(
                selectinload(User.participant_info),
                selectinload(User.mentor_info),
                selectinload(User.user2roles).selectinload(User2Roles.role),
                selectinload(User.current_status),
                selectinload(User.status_history).selectinload(UserStatusHistory.status),
            )
            .where(User.id == current_user.id)
        )

        result = await session.execute(refresh_query)
        updated_user = result.scalar_one()

        return updated_user

    except Exception as e:
        if os.path.exists(file_path):
            os.remove(file_path)
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ошибка при обновлении документов пользователя"
        )
