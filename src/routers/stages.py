from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict
from src.db import get_session
from src.models.stage import Stage, StageType
from src.schemas.stage import StageResponse, StageActivationResponse, StageCreate, StageUpdate
from src.auth.jwt import get_current_user
from src.models.user import User, User2Roles
from src.models.role import Role
from sqlalchemy import select, update, delete
import uuid
from src.utils.router_states import stage_router_state
from src.utils.event_utils import get_active_event
from src.utils.background_tasks import check_and_schedule_auto_activate_stages

router = APIRouter(
    prefix="/stages",
    tags=["stages"]
)

async def check_admin_role(user: User, db: AsyncSession) -> bool:
    """Проверка наличия роли администратора у пользователя"""
    query = select(Role).join(User2Roles).where(User2Roles.user_id == user.id)
    result = await db.execute(query)
    user_roles = result.scalars().all()
    return any(role.name == "admin" for role in user_roles)


async def check_admin_or_organizer(user: User, db: AsyncSession) -> bool:
    """Проверка наличия роли администратора или организатора у пользователя"""
    query = select(Role).join(User2Roles).where(User2Roles.user_id == user.id)
    result = await db.execute(query)
    user_roles = result.scalars().all()
    return any(role.name in ["admin", "organizer"] for role in user_roles)

@router.get("/all", response_model=List[StageResponse])
async def get_stages(
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Получить список всех этапов активного события"""
    active_event = await get_active_event(session)
    query = (
        select(Stage)
        .where(Stage.event_id == active_event.id)
        .order_by(Stage.order)
    )
    result = await session.execute(query)
    stages = result.scalars().all()

    return [
        StageResponse(
            id=stage.id,
            name=stage.name,
            type=stage.type,
            order=stage.order,
            is_active=stage.is_active,
            is_auto_activate=stage.is_auto_activate,
            auto_activate_at=stage.auto_activate_at,
            group=stage.group,
            created_at=stage.created_at,
            updated_at=stage.updated_at
        )
        for stage in stages
    ]


@router.get("/public", response_model=List[StageResponse])
async def get_public_stages(session: AsyncSession = Depends(get_session)):
    """Получить список всех этапов активного события (публичный endpoint, без аутентификации)"""
    active_event = await get_active_event(session)
    query = (
        select(Stage)
        .where(Stage.event_id == active_event.id)
        .order_by(Stage.order)
    )
    result = await session.execute(query)
    stages = result.scalars().all()

    return [
        StageResponse(
            id=stage.id,
            name=stage.name,
            type=stage.type,
            order=stage.order,
            is_active=stage.is_active,
            is_auto_activate=stage.is_auto_activate,
            auto_activate_at=stage.auto_activate_at,
            group=stage.group,
            created_at=stage.created_at,
            updated_at=stage.updated_at
        )
        for stage in stages
    ]


@router.get("/current", response_model=StageResponse)
async def get_current_stage(db: AsyncSession = Depends(get_session)):
    """Get current active stage for active event"""
    active_event = await get_active_event(db)
    result = await db.execute(
        select(Stage).where(
            Stage.is_active == True,
            Stage.event_id == active_event.id
        )
    )
    current_stage = result.scalar_one_or_none()

    if not current_stage:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active stage found"
        )
    return StageResponse(
        id=current_stage.id,
        name=current_stage.name,
        type=current_stage.type,
        order=current_stage.order,
        is_active=current_stage.is_active,
        is_auto_activate=current_stage.is_auto_activate,
        auto_activate_at=current_stage.auto_activate_at,
        group=current_stage.group,
        created_at=current_stage.created_at,
        updated_at=current_stage.updated_at
    )


@router.get("/available-transitions", response_model=Dict[str, List[StageResponse]])
async def get_available_transitions(
        db: AsyncSession = Depends(get_session),
        current_user: User = Depends(get_current_user)
):
    """Get available stage transitions for the current stage"""
    if not await check_admin_role(current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can view available transitions"
        )

    active_event = await get_active_event(db)
    current_result = await db.execute(
        select(Stage).where(
            Stage.is_active == True,
            Stage.event_id == active_event.id
        )
    )
    current_stage = current_result.scalar_one_or_none()

    if not current_stage:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active stage found"
        )

    all_stages_result = await db.execute(
        select(Stage)
        .where(Stage.event_id == active_event.id)
        .order_by(Stage.order)
    )
    all_stages = all_stages_result.scalars().all()

    available_stages = []
    for stage in all_stages:
        if abs(stage.order - current_stage.order) == 1:
            available_stages.append(stage)

    return {
        "current_stage": current_stage,
        "available_transitions": available_stages
    }


@router.put("/{stage_id}/activate", response_model=StageActivationResponse)
async def activate_stage(
        stage_id: str,
        db: AsyncSession = Depends(get_session),
        current_user: User = Depends(get_current_user)
):
    """
    Activate specific stage (admin only)

    The stage can only be changed to the next or previous stage in sequence.
    Note: 'registration_closed' can be activated manually or automatically when 20 teams are registered.
    """
    if not await check_admin_role(current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can change stages"
        )

    new_stage_result = await db.execute(
        select(Stage).where(Stage.id == stage_id)
    )
    new_stage = new_stage_result.scalar_one_or_none()

    if not new_stage:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stage not found"
        )

    active_event = await get_active_event(db)
    
    # Проверяем, что этап принадлежит активному событию
    if new_stage.event_id != active_event.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stage does not belong to active event"
        )

    current_result = await db.execute(
        select(Stage).where(
            Stage.is_active == True,
            Stage.event_id == active_event.id
        )
    )
    current_stage = current_result.scalar_one_or_none()

    if not current_stage:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active stage found"
        )

    # Для registration_closed разрешаем активацию вручную, даже если не соседний этап
    # (так как он может быть активирован администратором в любой момент)
    if new_stage.type != StageType.REGISTRATION_CLOSED.value:
        if abs(new_stage.order - current_stage.order) != 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Can only transition to adjacent stages"
            )
    await db.execute(
        update(Stage).where(
            Stage.is_active == True,
            Stage.event_id == active_event.id
        ).values(is_active=False)
    )

    new_stage.is_active = True
    await db.commit()
    await db.refresh(new_stage)

    await stage_router_state.initialize(db)

    return {
        "message": f"Stage '{new_stage.name}' activated successfully",
        "previous_stage": current_stage,
        "new_stage": new_stage
    }


@router.post("", response_model=StageResponse)
async def create_stage(
    stage_data: StageCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Создание нового этапа для активного события (только для администраторов и организаторов)"""
    if not await check_admin_or_organizer(current_user, session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов"
        )

    active_event = await get_active_event(session)

    # Проверяем, что этап с таким order не существует
    existing_stage_query = select(Stage).where(
        Stage.event_id == active_event.id,
        Stage.order == stage_data.order
    )
    existing_stage = await session.execute(existing_stage_query)
    if existing_stage.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Этап с порядковым номером {stage_data.order} уже существует"
        )

    new_stage = Stage(
        name=stage_data.name,
        type=stage_data.type,
        order=stage_data.order,
        event_id=active_event.id,
        is_active=False,
        is_auto_activate=stage_data.is_auto_activate,
        auto_activate_at=stage_data.auto_activate_at,
        group=stage_data.group
    )

    session.add(new_stage)
    await session.commit()
    await session.refresh(new_stage)
    
    # Если этап с автоматической активацией, планируем его активацию
    if new_stage.is_auto_activate and new_stage.auto_activate_at:
        import logging
        logging.info(f"Создан этап с автоматической активацией: {new_stage.name}, время: {new_stage.auto_activate_at}")
        await check_and_schedule_auto_activate_stages()

    return StageResponse(
        id=new_stage.id,
        name=new_stage.name,
        type=new_stage.type,
        order=new_stage.order,
        is_active=new_stage.is_active,
        is_auto_activate=new_stage.is_auto_activate,
        auto_activate_at=new_stage.auto_activate_at,
        group=new_stage.group,
        created_at=new_stage.created_at,
        updated_at=new_stage.updated_at
    )


@router.put("/{stage_id}", response_model=StageResponse)
async def update_stage(
    stage_id: uuid.UUID,
    stage_data: StageUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Обновление этапа (только для администраторов и организаторов)"""
    if not await check_admin_or_organizer(current_user, session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов"
        )

    stage_query = select(Stage).where(Stage.id == stage_id)
    stage_result = await session.execute(stage_query)
    stage = stage_result.scalar_one_or_none()

    if not stage:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Этап не найден"
        )

    active_event = await get_active_event(session)
    if stage.event_id != active_event.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Этап не принадлежит активному событию"
        )

    # Если изменяется order, проверяем, что новый order не занят
    if stage_data.order is not None and stage_data.order != stage.order:
        existing_stage_query = select(Stage).where(
            Stage.event_id == active_event.id,
            Stage.order == stage_data.order,
            Stage.id != stage_id
        )
        existing_stage = await session.execute(existing_stage_query)
        if existing_stage.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Этап с порядковым номером {stage_data.order} уже существует"
            )

    if stage_data.name is not None:
        stage.name = stage_data.name
    if stage_data.type is not None:
        stage.type = stage_data.type
    if stage_data.order is not None:
        stage.order = stage_data.order
    if stage_data.group is not None:
        stage.group = stage_data.group
    if stage_data.is_auto_activate is not None:
        stage.is_auto_activate = stage_data.is_auto_activate
    if stage_data.auto_activate_at is not None:
        stage.auto_activate_at = stage_data.auto_activate_at

    await session.commit()
    await session.refresh(stage)
    
    # Если этап с автоматической активацией, перепланируем его активацию
    if stage.is_auto_activate and stage.auto_activate_at:
        import logging
        logging.info(f"Обновлен этап с автоматической активацией: {stage.name}, время: {stage.auto_activate_at}")
        await check_and_schedule_auto_activate_stages()

    return StageResponse(
        id=stage.id,
        name=stage.name,
        type=stage.type,
        order=stage.order,
        is_active=stage.is_active,
        is_auto_activate=stage.is_auto_activate,
        auto_activate_at=stage.auto_activate_at,
        group=stage.group,
        created_at=stage.created_at,
        updated_at=stage.updated_at
    )


@router.delete("/{stage_id}")
async def delete_stage(
    stage_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Удаление этапа (только для администраторов и организаторов)"""
    if not await check_admin_or_organizer(current_user, session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для администраторов и организаторов"
        )

    stage_query = select(Stage).where(Stage.id == stage_id)
    stage_result = await session.execute(stage_query)
    stage = stage_result.scalar_one_or_none()

    if not stage:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Этап не найден"
        )

    active_event = await get_active_event(session)
    if stage.event_id != active_event.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Этап не принадлежит активному событию"
        )

    if stage.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нельзя удалить активный этап. Сначала активируйте другой этап"
        )

    await session.delete(stage)
    await session.commit()

    return {"message": "Этап успешно удален"}