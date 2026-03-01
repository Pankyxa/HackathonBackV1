from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime
from uuid import UUID
import pytz

from src.models.enums import StageType


class StageBase(BaseModel):
    name: str
    order: int
    is_active: bool
    type: str


class StageResponse(BaseModel):
    id: UUID
    name: str
    type: StageType
    order: int
    is_active: bool
    is_auto_activate: bool = False
    auto_activate_at: Optional[datetime] = None
    group: Optional[str] = None  # Группировка: "registration", "remote", "on_site", "final"
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class StageActivationResponse(BaseModel):
    message: str
    previous_stage: StageResponse
    new_stage: StageResponse

    class Config:
        orm_mode = True


class StageCreate(BaseModel):
    name: str
    type: str
    order: int
    is_auto_activate: bool = False
    auto_activate_at: Optional[datetime] = None  # Дата и время в формате МСК (будет конвертирована в UTC)
    group: Optional[str] = None  # Группировка: "registration", "remote", "on_site", "final"
    
    @field_validator('auto_activate_at', mode='before')
    @classmethod
    def validate_auto_activate_at(cls, v):
        """Конвертирует время из МСК в UTC для хранения в БД"""
        import logging
        
        if v is None:
            return None
        
        # Если это строка, парсим её
        if isinstance(v, str):
            from datetime import datetime as dt
            try:
                # Пробуем стандартный ISO формат
                v = dt.fromisoformat(v.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                # Если не получилось, пробуем парсить вручную
                try:
                    # Формат: "2025-03-15T10:00:00+03:00"
                    if '+' in v or v.endswith('Z'):
                        # Убираем Z и заменяем на +00:00
                        v_clean = v.replace('Z', '+00:00')
                        v = dt.fromisoformat(v_clean)
                    else:
                        # Без timezone - добавляем МСК
                        v = dt.fromisoformat(v)
                except Exception as e:
                    logging.error(f"Ошибка парсинга времени: {v}, ошибка: {e}")
                    raise ValueError(f"Неверный формат времени: {v}. Ожидается ISO формат (например: 2025-03-15T10:00:00+03:00)")
        
        # Если время не имеет timezone, считаем что это МСК
        msk_tz = pytz.timezone('Europe/Moscow')
        if v.tzinfo is None:
            # Предполагаем, что переданное время - это МСК
            v = msk_tz.localize(v)
        else:
            # Если timezone указан, извлекаем локальное время (без timezone) и интерпретируем его как МСК
            # Это нужно, чтобы избежать проблем с неправильными timezone offsets от фронтенда
            # Например, если приходит 22:13:00+02:30, мы берем 22:13:00 и интерпретируем как МСК
            local_time = v.replace(tzinfo=None)
            # Интерпретируем локальное время как МСК
            v = msk_tz.localize(local_time)
            logging.info(f"Время с timezone преобразовано: локальное время {local_time} интерпретировано как МСК: {v}")
        
        # Конвертируем МСК в UTC для хранения
        utc_time = v.astimezone(pytz.UTC)
        time_diff_minutes = (utc_time - v).total_seconds() / 60
        logging.info(f"Время конвертировано: {v} (МСК) -> {utc_time} (UTC), разница: {time_diff_minutes:.0f} минут")
        if abs(time_diff_minutes) != 180 and abs(time_diff_minutes) != 0:
            logging.warning(f"Неожиданная разница времени: {time_diff_minutes} минут (ожидается 180 минут для МСК->UTC)")
        return utc_time


class StageUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    order: Optional[int] = None
    is_auto_activate: Optional[bool] = None
    auto_activate_at: Optional[datetime] = None  # Дата и время в формате МСК (будет конвертирована в UTC)
    group: Optional[str] = None  # Группировка: "registration", "remote", "on_site", "final"
    
    @field_validator('auto_activate_at', mode='before')
    @classmethod
    def validate_auto_activate_at(cls, v):
        """Конвертирует время из МСК в UTC для хранения в БД"""
        import logging
        
        if v is None:
            return None
        
        # Если это строка, парсим её
        if isinstance(v, str):
            from datetime import datetime as dt
            try:
                # Пробуем стандартный ISO формат
                v = dt.fromisoformat(v.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                # Если не получилось, пробуем парсить вручную
                try:
                    # Формат: "2025-03-15T10:00:00+03:00"
                    if '+' in v or v.endswith('Z'):
                        # Убираем Z и заменяем на +00:00
                        v_clean = v.replace('Z', '+00:00')
                        v = dt.fromisoformat(v_clean)
                    else:
                        # Без timezone - добавляем МСК
                        v = dt.fromisoformat(v)
                except Exception as e:
                    logging.error(f"Ошибка парсинга времени: {v}, ошибка: {e}")
                    raise ValueError(f"Неверный формат времени: {v}. Ожидается ISO формат (например: 2025-03-15T10:00:00+03:00)")
        
        # Если время не имеет timezone, считаем что это МСК
        msk_tz = pytz.timezone('Europe/Moscow')
        if v.tzinfo is None:
            # Предполагаем, что переданное время - это МСК
            v = msk_tz.localize(v)
        else:
            # Если timezone указан, извлекаем локальное время (без timezone) и интерпретируем его как МСК
            # Это нужно, чтобы избежать проблем с неправильными timezone offsets от фронтенда
            # Например, если приходит 22:13:00+02:30, мы берем 22:13:00 и интерпретируем как МСК
            local_time = v.replace(tzinfo=None)
            # Интерпретируем локальное время как МСК
            v = msk_tz.localize(local_time)
            logging.info(f"Время с timezone преобразовано: локальное время {local_time} интерпретировано как МСК: {v}")
        
        # Конвертируем МСК в UTC для хранения
        utc_time = v.astimezone(pytz.UTC)
        time_diff_minutes = (utc_time - v).total_seconds() / 60
        logging.info(f"Время конвертировано: {v} (МСК) -> {utc_time} (UTC), разница: {time_diff_minutes:.0f} минут")
        if abs(time_diff_minutes) != 180 and abs(time_diff_minutes) != 0:
            logging.warning(f"Неожиданная разница времени: {time_diff_minutes} минут (ожидается 180 минут для МСК->UTC)")
        return utc_time