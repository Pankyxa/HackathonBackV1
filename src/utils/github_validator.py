"""
Утилиты для валидации GitHub репозиториев
"""
import re
from urllib.parse import urlparse
from typing import Optional, Tuple


def validate_github_url(url: str) -> Tuple[bool, Optional[str]]:
    """
    Валидирует URL GitHub репозитория
    
    Args:
        url: URL для проверки
        
    Returns:
        Tuple[bool, Optional[str]]: (is_valid, error_message)
        - is_valid: True если URL валидный
        - error_message: Сообщение об ошибке, если URL невалидный
    """
    if not url or not url.strip():
        return False, "Ссылка не может быть пустой"
    
    url = url.strip()
    
    # Паттерны для различных форматов GitHub URL
    github_patterns = [
        # https://github.com/username/repo
        r'^https?://(www\.)?github\.com/[\w\.-]+/[\w\.-]+/?$',
        # https://github.com/username/repo.git
        r'^https?://(www\.)?github\.com/[\w\.-]+/[\w\.-]+\.git/?$',
        # git@github.com:username/repo.git
        r'^git@github\.com:[\w\.-]+/[\w\.-]+\.git$',
        # github.com/username/repo (без протокола)
        r'^github\.com/[\w\.-]+/[\w\.-]+/?$',
    ]
    
    # Проверяем соответствие паттернам
    matches_pattern = any(re.match(pattern, url, re.IGNORECASE) for pattern in github_patterns)
    
    if not matches_pattern:
        return False, (
            "Неверный формат ссылки на GitHub. "
            "Ожидается формат: https://github.com/username/repository или "
            "git@github.com:username/repository.git"
        )
    
    # Парсим URL для дополнительной проверки
    try:
        # Если это SSH формат, преобразуем для парсинга
        if url.startswith('git@'):
            # git@github.com:username/repo.git -> https://github.com/username/repo
            url_parts = url.replace('git@github.com:', '').replace('.git', '')
            username, repo = url_parts.split('/', 1) if '/' in url_parts else (None, None)
        else:
            # Убираем протокол если его нет
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            
            parsed = urlparse(url)
            path_parts = parsed.path.strip('/').split('/')
            
            if len(path_parts) < 2:
                return False, "Ссылка должна содержать username и название репозитория"
            
            username = path_parts[0]
            repo = path_parts[1].replace('.git', '')
        
        # Проверяем что username и repo не пустые
        if not username or not repo:
            return False, "Username и название репозитория не могут быть пустыми"
        
        # Проверяем длину
        if len(username) > 39:  # GitHub ограничение
            return False, "Username слишком длинный (максимум 39 символов)"
        
        if len(repo) > 100:  # GitHub ограничение
            return False, "Название репозитория слишком длинное (максимум 100 символов)"
        
        # Проверяем допустимые символы
        if not re.match(r'^[\w\.-]+$', username):
            return False, "Username содержит недопустимые символы"
        
        if not re.match(r'^[\w\.-]+$', repo):
            return False, "Название репозитория содержит недопустимые символы"
        
        return True, None
        
    except Exception as e:
        return False, f"Ошибка при проверке ссылки: {str(e)}"


def normalize_github_url(url: str) -> str:
    """
    Нормализует GitHub URL к стандартному формату https://github.com/username/repo
    
    Args:
        url: URL для нормализации
        
    Returns:
        str: Нормализованный URL
    """
    url = url.strip()
    
    # SSH формат -> HTTPS
    if url.startswith('git@'):
        url = url.replace('git@github.com:', 'https://github.com/').replace('.git', '')
    
    # Убираем .git в конце
    if url.endswith('.git'):
        url = url[:-4]
    
    # Добавляем протокол если его нет
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    # Убираем www.
    url = url.replace('www.github.com', 'github.com')
    
    # Убираем trailing slash
    url = url.rstrip('/')
    
    return url


def extract_repo_info(url: str) -> Optional[dict]:
    """
    Извлекает информацию о репозитории из URL
    
    Args:
        url: GitHub URL
        
    Returns:
        dict: {'username': str, 'repo': str, 'full_url': str} или None
    """
    is_valid, error = validate_github_url(url)
    if not is_valid:
        return None
    
    normalized = normalize_github_url(url)
    
    try:
        parsed = urlparse(normalized)
        path_parts = parsed.path.strip('/').split('/')
        
        if len(path_parts) >= 2:
            return {
                'username': path_parts[0],
                'repo': path_parts[1],
                'full_url': normalized
            }
    except Exception:
        pass
    
    return None
