from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.stage import Stage
from src.models.enums import StageType
from typing import List, Union
from sqlalchemy import select


async def check_stage(db: AsyncSession, allowed_stages: Union[StageType, List[StageType]]) -> Stage:
    """
    Проверяет, находится ли система на допустимом этапе

    :param db: AsyncSession базы данных
    :param allowed_stages: Этап или список этапов, на которых разрешена операция
    :return: Текущий активный этап
    :raises: HTTPException если текущий этап не соответствует разрешенным
    """
    result = await db.execute(
        select(Stage).where(Stage.is_active == True)
    )
    current_stage = result.scalar_one_or_none()

    if not current_stage:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нет активного этапа"
        )

    if isinstance(allowed_stages, StageType):
        allowed_stages = [allowed_stages]

    if current_stage.type not in [stage.value for stage in allowed_stages]:
        stage_names = [stage.name for stage in allowed_stages]
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Эта операция не разрешена на текущем этапе. Разрешенные этапы: {', '.join(stage_names)}"
        )

    return current_stage