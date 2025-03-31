import asyncio
import os
import tempfile
import shutil
import uuid
from typing import Optional
from fastapi import HTTPException, status

from src.models import FileType, FileOwnerType, File as DBFile
from src.utils.router_states import file_router_state

upload_semaphore = asyncio.Semaphore(5)

async def save_file(
    upload_file,
    owner_id: uuid.UUID,
    file_type: FileType,
    owner_type: FileOwnerType,
    max_file_size: Optional[int] = None
) -> DBFile:
    """Базовая функция для сохранения файлов"""
    async with upload_semaphore:
        try:
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
            elif file_type == FileType.SOLUTION:
                file_type_id = file_router_state.solution_type_id
            elif file_type == FileType.DEPLOYMENT:
                file_type_id = file_router_state.deployment_type_id
            else:
                raise ValueError(f"Неизвестный тип файла: {file_type}")

            base_dir = "uploads/users" if owner_type == FileOwnerType.USER else "uploads/teams"
            upload_dir = f"{base_dir}/{owner_id}"
            os.makedirs(upload_dir, exist_ok=True)

            file_extension = os.path.splitext(upload_file.filename)[1].lower()
            file_name = f"{uuid.uuid4()}{file_extension}"
            file_path = os.path.join(upload_dir, file_name)

            temp_file = tempfile.NamedTemporaryFile(delete=False, prefix='upload_', dir=upload_dir)
            try:
                file_size = 0
                chunk_size = 64 * 1024
                
                while chunk := await upload_file.read(chunk_size):
                    file_size += len(chunk)
                    if max_file_size and file_size > max_file_size:
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"Размер файла не должен превышать {max_file_size/(1024*1024)}MB"
                        )
                    temp_file.write(chunk)
                    await asyncio.sleep(0)

                temp_file.close()

                shutil.move(temp_file.name, file_path)

                if file_extension == '.pdf':
                    file_format_id = file_router_state.pdf_format_id
                elif file_extension in ['.jpg', '.jpeg', '.png']:
                    file_format_id = file_router_state.image_format_id
                elif file_extension == '.zip':
                    file_format_id = file_router_state.zip_format_id
                elif file_extension == '.txt':
                    file_format_id = file_router_state.txt_format_id
                elif file_extension == '.md':
                    file_format_id = file_router_state.md_format_id
                else:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Неподдерживаемый формат файла: {file_extension}"
                    )

                file_model = DBFile(
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

            except Exception as e:
                if os.path.exists(temp_file.name):
                    os.unlink(temp_file.name)
                if os.path.exists(file_path):
                    os.remove(file_path)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Ошибка при сохранении файла: {str(e)}"
                )

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Ошибка при загрузке файла: {str(e)}"
            )