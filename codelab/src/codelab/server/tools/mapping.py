"""Маппинг имён инструментов между ACP протоколом и LLM API.

ACP протокол использует имена с `/` (например `fs/read_text_file`),
но некоторые LLM провайдеры (Azure через OpenRouter) не поддерживают
символ `/` в именах функций. Паттерн: ^[a-zA-Z0-9_\\.-]+$

Этот модуль обеспечивает двусторонний маппинг:
- ACP → LLM: замена `/` на `_` при отправке в LLM API
- LLM → ACP: замена `_` на `/` при получении ответа от LLM

Также поддерживает MCP инструменты с namespace `mcp:`:
- MCP ACP → LLM: `mcp:server:tool_name` → `mcp_server_tool_name`
- MCP LLM → ACP: `mcp_server_tool_name` → `mcp:server:tool_name`

Пример использования:
    >>> acp_name_to_llm_name("fs/read_text_file")
    "fs_read_text_file"
    >>> llm_name_to_acp_name("fs_read_text_file")
    "fs/read_text_file"
    >>> acp_name_to_llm_name("mcp:fs:read_file")
    "mcp_fs_read_file"
    >>> llm_name_to_acp_name("mcp_fs_read_file")
    "mcp:fs:read_file"
"""

# Префиксы инструментов ACP, которые нужно маппить.
# Порядок важен: более специфичные префиксы должны идти первыми.
_TOOL_PREFIXES = [
    "fs/",
    "terminal/",
]

# MCP namespace prefix
_MCP_PREFIX = "mcp:"
_MCP_LLM_PREFIX = "mcp_"


def acp_name_to_llm_name(acp_name: str) -> str:
    """Преобразовать ACP имя инструмента в LLM-совместимое имя.

    Заменяет `/` на `_` в именах инструментов.
    Для MCP инструментов заменяет `:` на `_`.

    Args:
        acp_name: Имя инструмента в формате ACP (например `fs/read_text_file`
            или `mcp:fs:read_file`).

    Returns:
        LLM-совместимое имя (например `fs_read_text_file` или `mcp_fs_read_file`).

    Example:
        >>> acp_name_to_llm_name("fs/read_text_file")
        'fs_read_text_file'
        >>> acp_name_to_llm_name("terminal/create")
        'terminal_create'
        >>> acp_name_to_llm_name("update_plan")  # уже совместимо
        'update_plan'
        >>> acp_name_to_llm_name("mcp:fs:read_file")
        'mcp_fs_read_file'
    """
    # MCP инструменты: mcp:server:tool → mcp_server_tool
    if acp_name.startswith(_MCP_PREFIX):
        return acp_name.replace(":", "_")
    return acp_name.replace("/", "_")


def llm_name_to_acp_name(llm_name: str) -> str:
    """Преобразовать LLM имя инструмента обратно в ACP формат.

    Восстанавливает `/` из `_` для известных префиксов инструментов.
    Для MCP инструментов восстанавливает `:` из `_`.

    Алгоритм:
    1. Проверяем MCP префикс (mcp_) — восстанавливаем mcp:server:tool
    2. Проверяем каждый известный префикс (например `fs_`, `terminal_`)
    3. Если имя начинается с префикса — заменяем первое `_` на `/`

    Args:
        llm_name: LLM-совместимое имя (например `fs_read_text_file`
            или `mcp_fs_read_file`).

    Returns:
        ACP имя инструмента (например `fs/read_text_file` или `mcp:fs:read_file`).

    Example:
        >>> llm_name_to_acp_name("fs_read_text_file")
        'fs/read_text_file'
        >>> llm_name_to_acp_name("terminal_create")
        'terminal/create'
        >>> llm_name_to_acp_name("update_plan")  # не маппится
        'update_plan'
        >>> llm_name_to_acp_name("mcp_fs_read_file")
        'mcp:fs:read_file'
    """
    # MCP инструменты: mcp_server_tool → mcp:server:tool
    if llm_name.startswith(_MCP_LLM_PREFIX):
        # mcp_server_tool → mcp:server:tool
        # Убираем "mcp_" и восстанавливаем ":"
        rest = llm_name[len(_MCP_LLM_PREFIX):]
        if "_" in rest:
            first_underscore = rest.index("_")
            server_id = rest[:first_underscore]
            tool_name = rest[first_underscore + 1:]  # Пропускаем underscore
            return f"{_MCP_PREFIX}{server_id}:{tool_name}"
        # Если нет underscore, возвращаем как есть (некорректный формат)
        return llm_name

    for prefix in _TOOL_PREFIXES:
        llm_prefix = prefix.replace("/", "_")
        if llm_name.startswith(llm_prefix) and llm_name != llm_prefix:
            # Заменяем первое вхождение `_` после префикса на `/`
            return prefix + llm_name[len(llm_prefix):]
    return llm_name
