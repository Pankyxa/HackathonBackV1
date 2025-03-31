import asyncio
import os
import tempfile
import shutil
import uuid
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import FileType, FileOwnerType, File as DBFile
from src.utils.router_states import file_router_state

solution_upload_semaphore = asyncio.Semaphore(3)

async def save_team_solution(
    upload_file,
    team_id: uuid.UUID,
    session: AsyncSession,
    max_file_size: int = 500 * 1024 * 1024
) -> DBFile:
    """
    Безопасное сохранение решения команды с обработкой конкурентных загрузок
    """
    async with solution_upload_semaphore:
        try:
            if not upload_file.filename.lower().endswith('.zip'):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Файл решения должен быть в формате ZIP"
                )

            upload_dir = f"uploads/teams/{team_id}"
            os.makedirs(upload_dir, exist_ok=True)

            file_name = f"solution_{uuid.uuid4()}.zip"
            file_path = os.path.join(upload_dir, file_name)

            temp_file = tempfile.NamedTemporaryFile(delete=False, prefix='solution_', dir=upload_dir)
            try:
                file_size = 0
                chunk_size = 64 * 1024
                
                while chunk := await upload_file.read(chunk_size):
                    file_size += len(chunk)
                    if file_size > max_file_size:
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"Размер файла не должен превышать {max_file_size/(1024*1024)}MB"
                        )
                    temp_file.write(chunk)
                    await asyncio.sleep(0)

                temp_file.close()

                shutil.move(temp_file.name, file_path)

                solution_file = DBFile(
                    id=uuid.uuid4(),
                    filename=upload_file.filename,
                    file_path=file_path,
                    file_format_id=file_router_state.zip_format_id,
                    file_type_id=file_router_state.solution_type_id,
                    owner_type_id=file_router_state.team_owner_type_id,
                    team_id=team_id
                )

                return solution_file

            except Exception as e:
                if os.path.exists(temp_file.name):
                    os.unlink(temp_file.name)
                if os.path.exists(file_path):
                    os.remove(file_path)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Ошибка при сохранении решения: {str(e)}"
                )

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Ошибка при загрузке решения: {str(e)}"
            )