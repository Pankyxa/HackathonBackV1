import uuid
import os
from urllib.parse import unquote, quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from sqlalchemy.orm import selectinload

from src.db import get_session
from src.models import File as FileModel, User
from src.auth.jwt import get_current_user
from src.utils.router_states import user_router_state
from src.utils.finalists_utils import user_can_access_on_site_materials

router = APIRouter(prefix="/files", tags=["files"])

# Путь к статическим файлам (исходные данные)
STATIC_FILES_DIR = "files"
ON_SITE_FILES_DIR = os.path.join(STATIC_FILES_DIR, "on_site")

CONTENT_TYPES = {
    '.pdf': 'application/pdf',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.doc': 'application/msword',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.xls': 'application/vnd.ms-excel',
    '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    '.ppt': 'application/vnd.ms-powerpoint',
    '.dwg': 'application/acad',
    '.txt': 'text/plain',
    '.md': 'text/markdown'
}


def _safe_static_filename(filename: str) -> str:
    try:
        decoded_filename = unquote(filename)
    except Exception:
        decoded_filename = filename

    if ".." in decoded_filename or "/" in decoded_filename or "\\" in decoded_filename:
        raise HTTPException(status_code=400, detail="Недопустимый путь к файлу")

    return decoded_filename


@router.get("/static/{filename:path}")
async def get_static_file(filename: str):
    """Получение статических файлов (исходные данные, задания заочного этапа)"""
    decoded_filename = _safe_static_filename(filename)
    full_path = os.path.join(STATIC_FILES_DIR, decoded_filename)

    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="Файл не найден")

    file_ext = os.path.splitext(decoded_filename)[1].lower()
    media_type = CONTENT_TYPES.get(file_ext, 'application/octet-stream')

    return FileResponse(
        path=full_path,
        filename=decoded_filename,
        media_type=media_type
    )


@router.get("/on-site/{filename:path}")
async def get_on_site_file(
    filename: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Файлы очного этапа: только финалисты, жюри, организаторы и администраторы."""
    if not await user_can_access_on_site_materials(session, current_user):
        raise HTTPException(
            status_code=403,
            detail="Материалы очного этапа доступны только командам-финалистам",
        )

    decoded_filename = _safe_static_filename(filename)
    full_path = os.path.join(ON_SITE_FILES_DIR, decoded_filename)

    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="Файл не найден")

    file_ext = os.path.splitext(decoded_filename)[1].lower()
    media_type = CONTENT_TYPES.get(file_ext, 'application/octet-stream')

    return FileResponse(
        path=full_path,
        filename=decoded_filename,
        media_type=media_type
    )


@router.get("/{file_id}")
async def get_file(
        file_id: str,
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Получение файла по ID из БД"""
    # Пытаемся распарсить как UUID
    try:
        file_uuid = uuid.UUID(file_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Файл не найден")
    
    # Это UUID - обрабатываем как файл из БД
    current_user_query = (
        select(User)
        .options(selectinload(User.user2roles))
        .where(User.id == current_user.id)
    )
    result = await session.execute(current_user_query)
    current_user_with_roles = result.scalar_one()

    query = (
        select(FileModel)
        .options(
            selectinload(FileModel.file_format)
        )
        .where(FileModel.id == file_uuid)
    )
    result = await session.execute(query)
    file = result.scalar_one_or_none()

    if not file:
        raise HTTPException(status_code=404, detail="Файл не найден")

    is_organizer = any(
        role.role_id == user_router_state.organizer_role_id
        for role in current_user_with_roles.user2roles
    )
    is_admin = any(
        role.role_id == user_router_state.admin_role_id
        for role in current_user_with_roles.user2roles
    )

    if file.user_id != current_user.id and not (is_organizer or is_admin):
        raise HTTPException(status_code=403, detail="Нет доступа к файлу")

    if not os.path.exists(file.file_path):
        raise HTTPException(status_code=404, detail="Файл не найден на сервере")

    content_type = "application/pdf" if file.file_format.name == "pdf" else "image/jpeg"

    return FileResponse(
        path=file.file_path,
        filename=file.filename,
        media_type=content_type
    )