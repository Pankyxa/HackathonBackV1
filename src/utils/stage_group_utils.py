"""
Утилиты для работы с группами этапов
"""
from src.models.stage import Stage
from src.models.enums import StageType


def is_remote_stage(stage: Stage) -> bool:
    """
    Проверяет, является ли этап заочным (remote)
    
    Args:
        stage: Объект этапа
        
    Returns:
        bool: True если этап заочный
    """
    remote_types = [
        StageType.REMOTE_TASK_DISTRIBUTION.value,
        StageType.REMOTE_SOLUTION_SUBMISSION.value,
        StageType.ONLINE_DEFENSE.value,  # Онлайн защита остается в заочном этапе
        # Старые типы для совместимости (если используются для заочного этапа)
        StageType.TASK_DISTRIBUTION.value,
        StageType.SOLUTION_SUBMISSION.value
    ]
    
    # Проверяем по типу этапа
    if stage.type in remote_types:
        return True
    
    # Проверяем по группе
    if stage.group == 'remote':
        return True
    
    return False


def is_on_site_stage(stage: Stage) -> bool:
    """
    Проверяет, является ли этап очным (on_site)
    
    Args:
        stage: Объект этапа
        
    Returns:
        bool: True если этап очный
    """
    on_site_types = [
        StageType.ON_SITE_TASK_DISTRIBUTION.value,
        StageType.ON_SITE_SOLUTION_SUBMISSION.value,
        StageType.ON_SITE_DEFENSE.value
    ]
    
    # Проверяем по типу этапа
    if stage.type in on_site_types:
        return True
    
    # Проверяем по группе
    if stage.group == 'on_site':
        return True
    
    return False


def is_task_distribution_stage(stage: Stage) -> bool:
    """
    Проверяет, является ли этап этапом распределения заданий
    
    Args:
        stage: Объект этапа
        
    Returns:
        bool: True если этап распределения заданий
    """
    task_distribution_types = [
        StageType.TASK_DISTRIBUTION.value,
        StageType.REMOTE_TASK_DISTRIBUTION.value,
        StageType.ON_SITE_TASK_DISTRIBUTION.value
    ]
    
    return stage.type in task_distribution_types


def is_solution_submission_stage(stage: Stage) -> bool:
    """
    Проверяет, является ли этап этапом приема решений
    
    Args:
        stage: Объект этапа
        
    Returns:
        bool: True если этап приема решений
    """
    solution_submission_types = [
        StageType.SOLUTION_SUBMISSION.value,
        StageType.REMOTE_SOLUTION_SUBMISSION.value,
        StageType.ON_SITE_SOLUTION_SUBMISSION.value
    ]
    
    return stage.type in solution_submission_types


def is_solution_review_stage(stage: Stage) -> bool:
    """
    Проверяет, является ли этап этапом проверки решений
    
    Args:
        stage: Объект этапа
        
    Returns:
        bool: True если этап проверки решений
    """
    solution_review_types = [
        StageType.SOLUTION_REVIEW.value,  # Старый тип для совместимости
        StageType.ON_SITE_DEFENSE.value  # Очный этап - проверка решений (защита)
    ]
    
    return stage.type in solution_review_types


def get_stage_group_from_type(stage_type: str) -> str:
    """
    Определяет группу этапа по его типу
    
    Args:
        stage_type: Тип этапа (значение StageType)
        
    Returns:
        str: Группа этапа ('registration', 'remote', 'on_site', 'final', None)
    """
    # Регистрация
    if stage_type in [StageType.REGISTRATION.value, StageType.REGISTRATION_CLOSED.value]:
        return 'registration'
    
    # Заочный этап
    if stage_type in [
        StageType.REMOTE_TASK_DISTRIBUTION.value,
        StageType.REMOTE_SOLUTION_SUBMISSION.value,
        StageType.ONLINE_DEFENSE.value  # Онлайн защита остается в заочном этапе
    ]:
        return 'remote'
    
    # Старые типы (для совместимости) - считаем заочными
    if stage_type in [
        StageType.TASK_DISTRIBUTION.value,
        StageType.SOLUTION_SUBMISSION.value
    ]:
        return 'remote'
    
    # Финалисты
    if stage_type == StageType.FINALISTS_SELECTION.value:
        return 'final'
    
    # Очный этап
    if stage_type in [
        StageType.ON_SITE_TASK_DISTRIBUTION.value,
        StageType.ON_SITE_SOLUTION_SUBMISSION.value,
        StageType.ON_SITE_DEFENSE.value
    ]:
        return 'on_site'
    
    # Завершение
    if stage_type in [
        StageType.RESULTS_PUBLICATION.value,
        StageType.AWARD_CEREMONY.value
    ]:
        return 'other'
    
    return None
