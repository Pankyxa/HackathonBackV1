"""
Нормализация названий вузов для тегов команды.

Участники писали одно и то же по-разному: регистр, кавычки,
полное имя или аббревиатура. Для карточек сводим это к одному тегу.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, List, Sequence, Tuple


_PREFIX_RE = re.compile(
    r"^(?:"
    r"фгаоу\s+во\s+|"
    r"фгбоу\s+во\s+|"
    r"фгбоу\s+|"
    r"фгаоу\s+|"
    r"гбпоу\s+янао\s+|"
    r"гапоу\s+|"
    r"федеральное государственное автономное образовательное учреждение высшего образования\s+|"
    r"федеральное государственное бюджетное образовательное учреждение высшего образования\s+"
    r")",
)

# Более специфичные группы должны идти раньше общих (МПК ТИУ до ТИУ).
_VUZ_GROUPS: Sequence[Tuple[str, Sequence[str]]] = (
    (
        "МПК ТИУ",
        (
            "мпк тиу",
            "многопрофильный колледж тиу",
            "многопрофильный колледж тюменского индустриального университета",
            "тиу многопрофильный колледж",
        ),
    ),
    (
        "Филиал ТИУ в г. Тобольске",
        (
            "тобольский индустриальный институт",
            "филиал тиу в городе тобольске",
            "филиал тиу в г тобольске",
            "филиал тюменского индустриального университета в г тобольске",
        ),
    ),
    (
        "ТИУ ИСОУ",
        ("тиу исоу", "исоу"),
    ),
    (
        "ТИУ",
        (
            "тиу",
            "тюменский индустриальный университет",
        ),
    ),
    (
        "ТюмГУ",
        (
            "тюмгу",
            "тюменский государственный университет",
            "тюменский государственный универститет",
        ),
    ),
    (
        "НГТУ",
        (
            "нгту",
            "нгту нэти",
            "новосибирский государственный технический университет",
        ),
    ),
    (
        "ТПУ",
        (
            "тпу",
            "томский политехнический университет",
            "национальный исследовательский томский политехнический университет",
        ),
    ),
    (
        "ТГУ",
        ("национальный исследовательский томский государственный университет",),
    ),
    (
        "ОмГТУ",
        (
            "омгту",
            "омский государственный технический университет",
        ),
    ),
    (
        "УГНТУ",
        (
            "угнту",
            "уфимский государственный нефтяной технический университет",
        ),
    ),
    (
        "ЮГУ",
        (
            "югу",
            "югорский государственный университет",
        ),
    ),
    (
        "СевГУ",
        ("севастопольский государственный университет",),
    ),
    (
        "НИУ МЭИ",
        (
            "ниу мэи",
            "национальный исследовательский университет мэи",
        ),
    ),
    (
        "ИТМО",
        (
            "итмо",
            "университет итмо",
            "национальный исследовательский университет итмо",
        ),
    ),
    (
        "СГУ",
        (
            "сгу имени н г чернышевского",
            "саратовский государственный университет имени н г чернышевского",
            "саратовский национальный исследовательский государственный университет имени н г чернышевского",
        ),
    ),
    (
        "Карагандинский индустриальный университет",
        ("карагандинский индустриальный университет",),
    ),
    (
        "Муравленковский многопрофильный колледж",
        (
            "муравленковский многопрофильный колледж",
            "муравленковский многпрофильный колледж",
        ),
    ),
    (
        "НКПИИТ",
        (
            "нкпиит",
            "ноябрьский колледж профессиональных и информационных технологий",
        ),
    ),
    (
        "ГАПОУ ГТТ",
        (
            "гтт",
            "гуманитарно технический техникум",
            "государственное гуманитарно технический техникум",
        ),
    ),
)


def normalize_vuz(name: str) -> str:
    if not name:
        return ""

    # Не используем NFKD: он разбивает «й» на «и» + кратку.
    # Снимаем только знаки ударения (комбинирующие символы).
    text = "".join(char for char in name if unicodedata.category(char) != "Mn")
    text = text.lower().replace("ё", "е")
    text = text.replace("«", " ").replace("»", " ").replace('"', " ").replace("'", " ")
    text = text.replace("(", " ").replace(")", " ").replace(".", " ").replace(",", " ")
    text = text.replace("—", " ").replace("–", " ").replace("-", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = _PREFIX_RE.sub("", text).strip()
    text = re.sub(r"^во\s+", "", text)
    return text


def _matches_alias(normalized: str, alias: str) -> bool:
    if not normalized or not alias:
        return False
    if normalized == alias:
        return True
    # Короткие аббревиатуры («тиу») не ищем как подстроку, иначе склеятся с «мпк тиу»
    if len(normalized) <= 8 or len(alias) <= 8:
        return False
    return alias in normalized or normalized in alias


def canonical_vuz(name: str) -> str:
    normalized = normalize_vuz(name)
    if not normalized:
        return ""

    for canonical, aliases in _VUZ_GROUPS:
        if any(_matches_alias(normalized, alias) for alias in aliases):
            return canonical

    cleaned = re.sub(r"\s+", " ", name).strip(" \t\"'«»")
    return cleaned


def unique_vuz_list(names: Iterable[str]) -> List[str]:
    """Возвращает уникальные канонические названия вузов с сохранением порядка."""
    result: List[str] = []
    seen = set()

    for name in names:
        if not name or not str(name).strip():
            continue

        canonical = canonical_vuz(str(name))
        key = normalize_vuz(canonical)
        if not key or key in seen:
            continue
        if len(key) < 2 or key.isdigit():
            continue

        seen.add(key)
        result.append(canonical)

    return result


def vuz_list_from_team_members(members) -> List[str]:
    """Собирает уникальные вузы принятых участников команды."""
    names = []
    for member in members or []:
        status = getattr(member, "status", None)
        if status is not None and getattr(status, "name", None) not in (
            None,
            "accepted",
        ):
            continue
        user = getattr(member, "user", None)
        info = getattr(user, "participant_info", None) if user else None
        vuz = getattr(info, "vuz", None) if info else None
        if vuz:
            names.append(vuz)
    return unique_vuz_list(names)
