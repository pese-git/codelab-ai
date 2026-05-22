"""Маппинг имён инструментов между ACP протоколом и LLM API.

ACP протокол использует имена с `/` (например `fs/read_text_file`),
но некоторые LLM провайдеры (Azure через OpenRouter) не поддерживают
символ `/` в именах функций. Паттерн: ^[a-zA-Z0-9_\\.-]+$

Этот модуль обеспечивает двусторонний маппинг:
- ACP → LLM: замена `/` на `_` при отправке в LLM API
- LLM → ACP: замена `_` на `/` при получении ответа от LLM

Пример использования:
    >>> acp_name_to_llm_name("fs/read_text_file")
    "fs_read_text_file"
    >>> llm_name_to_acp_name("fs_read_text_file")
    "fs/read_text_file"
"""

# Префиксы инструментов ACP, которые нужно маппить.
# Порядок важен: более специфичные префиксы должны идти первыми.
_TOOL_PREFIXES = [
    "fs/",
    "terminal/",
]


def acp_name_to_llm_name(acp_name: str) -> str:
    """Преобразовать ACP имя инструмента в LLM-совместимое имя.

    Заменяет `/` на `_` в именах инструментов.

    Args:
        acp_name: Имя инструмента в формате ACP (например `fs/read_text_file`).

    Returns:
        LLM-совместимое имя (например `fs_read_text_file`).

    Example:
        >>> acp_name_to_llm_name("fs/read_text_file")
        'fs_read_text_file'
        >>> acp_name_to_llm_name("terminal/create")
        'terminal_create'
        >>> acp_name_to_llm_name("update_plan")  # уже совместимо
        'update_plan'
    """
    return acp_name.replace("/", "_")


def llm_name_to_acp_name(llm_name: str) -> str:
    """Преобразовать LLM имя инструмента обратно в ACP формат.

    Восстанавливает `/` из `_` для известных префиксов инструментов.

    Алгоритм:
    1. Проверяем каждый известный префикс (например `fs_`, `terminal_`)
    2. Если имя начинается с префикса — заменяем первое `_` на `/`

    Args:
        llm_name: LLM-совместимое имя (например `fs_read_text_file`).

    Returns:
        ACP имя инструмента (например `fs/read_text_file`).

    Example:
        >>> llm_name_to_acp_name("fs_read_text_file")
        'fs/read_text_file'
        >>> llm_name_to_acp_name("terminal_create")
        'terminal/create'
        >>> llm_name_to_acp_name("update_plan")  # не маппится
        'update_plan'
    """
    for prefix in _TOOL_PREFIXES:
        llm_prefix = prefix.replace("/", "_")
        if llm_name.startswith(llm_prefix) and llm_name != llm_prefix:
            # Заменяем первое вхождение `_` после префикса на `/`
            return prefix + llm_name[len(llm_prefix):]
    return llm_name
