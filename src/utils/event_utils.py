from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.models.event import Event
from fastapi import HTTPException, status


async def get_active_event(session: AsyncSession) -> Event:
    """Получение активного события"""
    query = select(Event).where(Event.is_active == True)
    result = await session.execute(query)
    event = result.scalar_one_or_none()
    
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Активное событие не найдено. Пожалуйста, создайте и активируйте событие."
        )
    
    return event
