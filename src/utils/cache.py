"""
Простая система кэширования с TTL для оптимизации запросов
"""
from datetime import datetime, timedelta
from typing import Any, Optional, Dict, Callable
import asyncio
from functools import wraps


class CacheEntry:
    """Запись в кэше с временем жизни"""
    def __init__(self, value: Any, ttl_seconds: int = 300):
        self.value = value
        self.created_at = datetime.utcnow()
        self.ttl_seconds = ttl_seconds
    
    def is_expired(self) -> bool:
        """Проверяет, истек ли срок действия кэша"""
        return datetime.utcnow() - self.created_at > timedelta(seconds=self.ttl_seconds)


class SimpleCache:
    """Простой in-memory кэш с TTL"""
    def __init__(self):
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()
    
    async def get(self, key: str) -> Optional[Any]:
        """Получает значение из кэша, если оно не истекло"""
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            
            if entry.is_expired():
                del self._cache[key]
                return None
            
            return entry.value
    
    async def set(self, key: str, value: Any, ttl_seconds: int = 300):
        """Устанавливает значение в кэш с указанным TTL"""
        async with self._lock:
            self._cache[key] = CacheEntry(value, ttl_seconds)
    
    async def delete(self, key: str):
        """Удаляет значение из кэша"""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
    
    async def clear(self):
        """Очищает весь кэш"""
        async with self._lock:
            self._cache.clear()
    
    async def invalidate_pattern(self, pattern: str):
        """Инвалидирует все ключи, содержащие паттерн"""
        async with self._lock:
            keys_to_delete = [key for key in self._cache.keys() if pattern in key]
            for key in keys_to_delete:
                del self._cache[key]


# Глобальный экземпляр кэша
cache = SimpleCache()


def cached(ttl_seconds: int = 300, key_prefix: str = ""):
    """
    Декоратор для кэширования результатов async функций
    
    Args:
        ttl_seconds: Время жизни кэша в секундах (по умолчанию 5 минут)
        key_prefix: Префикс для ключа кэша
    
    Usage:
        @cached(ttl_seconds=600, key_prefix="evaluations")
        async def get_evaluations(team_id: str):
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Формируем ключ кэша из аргументов функции
            cache_key = f"{key_prefix}:{func.__name__}:{str(args)}:{str(sorted(kwargs.items()))}"
            
            # Пытаемся получить значение из кэша
            cached_value = await cache.get(cache_key)
            if cached_value is not None:
                return cached_value
            
            # Если значения нет в кэше, выполняем функцию
            result = await func(*args, **kwargs)
            
            # Сохраняем результат в кэш
            await cache.set(cache_key, result, ttl_seconds)
            
            return result
        return wrapper
    return decorator


async def invalidate_evaluation_cache(event_id: Optional[str] = None, team_id: Optional[str] = None):
    """
    Инвалидирует кэш оценок
    
    Args:
        event_id: ID события (если указан, инвалидирует только для этого события)
        team_id: ID команды (если указан, инвалидирует только для этой команды)
    """
    if event_id:
        await cache.invalidate_pattern(f"evaluations:{event_id}")
    elif team_id:
        await cache.invalidate_pattern(f"evaluations:{team_id}")
    else:
        await cache.invalidate_pattern("evaluations")
