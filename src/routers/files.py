import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import os

from sqlalchemy.orm import selectinload

from src.db import get_session
from src.models import File as FileModel, User
from src.auth.jwt import get_current_user
from src.utils.router_states import user_router_state

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/{file_id}")
async def get_file(
        file_id: uuid.UUID,
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Получение файла по его ID"""
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
        .where(FileModel.id == file_id)
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