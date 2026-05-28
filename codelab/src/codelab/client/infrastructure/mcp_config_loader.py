"""MCPConfigLoader — загрузка конфигурации MCP серверов из TOML файлов.

Клиентский компонент для чтения секции [[mcp.servers]] из TOML файлов
(codelab.toml, codelab.local.toml, и т.д.) и передачи конфигурации
серверу через ACP протокол при создании/загрузке сессии.

Не зависит от серверных модулей — использует только стандартную библиотеку Python.
"""

import os
import re
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger("mcp_config_loader")


def expand_env_vars(value: str) -> str:
    """Раскрыть переменные окружения в строке.

    Поддерживает формат `${VAR_NAME}`.
    Если переменная не установлена, заменяется на пустую строку.

    Args:
        value: Строка с переменными окружения.

    Returns:
        Строка с раскрытыми переменными.
    """
    if not value or "$" not in value:
        return value

    result = value
    # ${VAR_NAME} format
    for match in re.finditer(r"\$\{([^}]+)\}", value):
        var_name = match.group(1)
        env_value = os.environ.get(var_name, "")
        result = result.replace(match.group(0), env_value)

    return result


def _expand_server_env_vars(server: dict[str, Any]) -> dict[str, Any]:
    """Рекурсивно раскрыть env vars во всех строковых полях MCP сервера.

    Args:
        server: Словарь конфигурации MCP сервера.

    Returns:
        Словарь с раскрытыми переменными окружения.
    """
    expanded: dict[str, Any] = {}

    for key, value in server.items():
        if isinstance(value, str):
            expanded[key] = expand_env_vars(value)
        elif isinstance(value, list):
            expanded[key] = [
                _expand_server_env_vars(item) if isinstance(item, dict)
                else expand_env_vars(item) if isinstance(item, str)
                else item
                for item in value
            ]
        elif isinstance(value, dict):
            expanded[key] = _expand_server_env_vars(value)
        else:
            expanded[key] = value

    return expanded


def _find_toml_chain(cwd: Path | None = None) -> list[Path]:
    """Найти цепочку TOML файлов в порядке приоритета.

    Порядок (от lowest к highest priority):
    1. ~/.codelab/codelab.toml — глобальный конфиг
    2. <cwd>/codelab.toml — проектный конфиг
    3. <cwd>/codelab.local.toml — project-local overrides

    Args:
        cwd: Рабочая директория проекта. Если None, используется текущая.

    Returns:
        Список существующих TOML файлов в порядке приоритета.
    """
    if cwd is None:
        cwd = Path.cwd()

    toml_files: list[Path] = []

    # Глобальный конфиг
    global_config = Path.home() / ".codelab" / "codelab.toml"
    if global_config.exists():
        toml_files.append(global_config)

    # Проектный конфиг
    project_config = cwd / "codelab.toml"
    if project_config.exists():
        toml_files.append(project_config)

    # Project-local overrides
    local_config = cwd / "codelab.local.toml"
    if local_config.exists():
        toml_files.append(local_config)

    return toml_files


def _load_mcp_servers_from_toml(toml_path: Path) -> list[dict[str, Any]]:
    """Загрузить MCP серверы из одного TOML файла.

    Парсит секцию [[mcp.servers]] и возвращает список словарей.

    Args:
        toml_path: Путь к TOML файлу.

    Returns:
        Список конфигураций MCP серверов.
    """
    import tomllib

    try:
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        logger.warning(
            "failed_to_parse_toml_file",
            path=str(toml_path),
            error=str(e),
        )
        return []

    mcp_section = data.get("mcp", {})
    servers = mcp_section.get("servers", [])

    if not servers:
        logger.debug("no_mcp_servers_found_in_toml", path=str(toml_path))

    return [dict(s) for s in servers]


def _merge_servers(
    existing: list[dict[str, Any]],
    new: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Объединить списки MCP серверов с override по name.

    Серверы из списка `new` с тем же `name` переопределяют серверы из `existing`.

    Args:
        existing: Существующие серверы (lower priority).
        new: Новые серверы (higher priority).

    Returns:
        Объединённый список серверов.
    """
    # Индекс существующих серверов по name
    by_name: dict[str, dict[str, Any]] = {}
    for server in existing:
        name = server.get("name")
        if name:
            by_name[name] = server

    # Добавляем новые серверы (переопределяют существующие с тем же name)
    for server in new:
        name = server.get("name")
        if name:
            by_name[name] = server

    return list(by_name.values())


def _validate_server(server: dict[str, Any]) -> bool:
    """Валидировать конфигурацию MCP сервера.

    Правила валидации:
    - Поле `name` обязательно для всех серверов
    - Для `type = "stdio"` обязательно поле `command`
    - Для `type = "http"` обязательно поле `url`
    - Если `type` не указан, подразумевается "stdio"

    Args:
        server: Словарь конфигурации MCP сервера.

    Returns:
        True если сервер валиден, False иначе.
    """
    name = server.get("name")
    if not name:
        logger.warning(
            "mcp_server_skipped_missing_name",
            server=server,
        )
        return False

    server_type = server.get("type", "stdio")

    if server_type == "stdio":
        if not server.get("command"):
            logger.warning(
                "mcp_server_skipped_missing_command",
                name=name,
                type=server_type,
            )
            return False
    elif server_type == "http":
        if not server.get("url"):
            logger.warning(
                "mcp_server_skipped_missing_url",
                name=name,
                type=server_type,
            )
            return False
    else:
        logger.warning(
            "mcp_server_skipped_unknown_type",
            name=name,
            type=server_type,
        )
        return False

    return True


class MCPConfigLoader:
    """Загрузчик конфигурации MCP серверов из TOML файлов.

    Находит TOML файлы в порядке приоритета, загружает MCP серверы,
    раскрывает переменные окружения и валидирует конфигурацию.
    """

    def __init__(self, cwd: Path | None = None) -> None:
        """Инициализировать загрузчик.

        Args:
            cwd: Рабочая директория проекта. Если None, используется текущая.
        """
        self._cwd = cwd or Path.cwd()

    def load_mcp_servers(self) -> list[dict[str, Any]]:
        """Загрузить MCP серверы из TOML файлов.

        Находит цепочку TOML файлов, загружает серверы из каждого,
        объединяет с override по name, раскрывает env vars и валидирует.

        Returns:
            Список валидных конфигураций MCP серверов.
        """
        toml_chain = _find_toml_chain(self._cwd)
        logger.debug(
            "toml_chain_found",
            files=[str(p) for p in toml_chain],
        )

        merged_servers: list[dict[str, Any]] = []

        for toml_path in toml_chain:
            servers = _load_mcp_servers_from_toml(toml_path)
            logger.debug(
                "loaded_mcp_servers_from_toml",
                path=str(toml_path),
                count=len(servers),
            )
            merged_servers = _merge_servers(merged_servers, servers)

        # Раскрыть переменные окружения и валидировать
        valid_servers: list[dict[str, Any]] = []
        for server in merged_servers:
            expanded = _expand_server_env_vars(server)
            if _validate_server(expanded):
                valid_servers.append(expanded)

        logger.info(
            "mcp_servers_loaded",
            total=len(valid_servers),
            files_processed=len(toml_chain),
        )

        return valid_servers
