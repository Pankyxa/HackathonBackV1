from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict
from src.db import get_session
from src.models.stage import Stage, StageType
from src.schemas.stage import StageResponse, StageActivationResponse
from src.auth.jwt import get_current_user
from src.models.user import User, User2Roles
from src.models.role import Role
from sqlalchemy import select, update
from src.utils.router_states import stage_router_state

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

@router.get("/all", response_model=List[StageResponse])
async def get_stages(
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """Получить список всех этапов"""
    query = select(Stage).order_by(Stage.order)
    result = await session.execute(query)
    stages = result.scalars().all()

    return [
        StageResponse(
            id=stage.id,
            name=stage.name,
            type=stage.type,
            order=stage.order,
            is_active=stage.is_active,
            created_at=stage.created_at,
            updated_at=stage.updated_at
        )
        for stage in stages
    ]


@router.get("/current", response_model=StageResponse)
async def get_current_stage(db: AsyncSession = Depends(get_session)):
    """Get current active stage"""
    result = await db.execute(
        select(Stage).where(Stage.is_active == True)
    )
    current_stage = result.scalar_one_or_none()

    if not current_stage:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active stage found"
        )
    return current_stage


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

    current_result = await db.execute(
        select(Stage).where(Stage.is_active == True)
    )
    current_stage = current_result.scalar_one_or_none()

    if not current_stage:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active stage found"
        )

    all_stages_result = await db.execute(
        select(Stage).order_by(Stage.order)
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

    The stage can only be changed to the next or previous stage in sequence,
    except for 'registration_closed' which is set automatically
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

    if new_stage.type == StageType.REGISTRATION_CLOSED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration closed stage is set automatically when conditions are met"
        )

    current_result = await db.execute(
        select(Stage).where(Stage.is_active == True)
    )
    current_stage = current_result.scalar_one_or_none()

    if not current_stage:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active stage found"
        )

    if abs(new_stage.order - current_stage.order) != 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only transition to adjacent stages"
        )
    await db.execute(
        update(Stage).where(Stage.is_active == True).values(is_active=False)
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