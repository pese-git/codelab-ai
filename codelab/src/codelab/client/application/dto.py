"""Data Transfer Objects (DTOs) - контракты для обмена данными между слоями.

DTOs используются для:
- Передачи данных между Application и Presentation слоями
- Типизации параметров use cases
- Валидации входных данных
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CreateSessionRequest:
    """Request DTO для создания новой сессии.

    Содержит параметры необходимые для создания сессии
    на стороне Application слоя.
    """

    server_host: str
    """Адрес ACP сервера."""

    server_port: int
    """Порт ACP сервера."""

    cwd: str
    """Абсолютный путь рабочей директории сессии (обязательный параметр ACP протокола)."""

    client_capabilities: dict[str, Any] | None = None
    """Возможности клиента (если None, используются default)."""

    auth_method: str | None = None
    """Метод аутентификации (если требуется)."""

    auth_credentials: dict[str, Any] | None = None
    """Учетные данные для аутентификации."""

    mcp_servers: list[dict[str, Any]] | None = None
    """Список MCP-серверов для `session/new` (если None, используется пустой список)."""


@dataclass
class CreateSessionResponse:
    """Response DTO для результата создания сессии.

    Содержит данные созданной сессии для возврата в Presentation слой.
    """

    session_id: str
    """Уникальный ID созданной сессии."""

    server_capabilities: dict[str, Any]
    """Возможности сервера, полученные при initialize."""

    is_authenticated: bool
    """Авторизован ли клиент на этой сессии."""


@dataclass
class LoadSessionRequest:
    """Request DTO для загрузки существующей сессии.

    Содержит параметры необходимые для загрузки сессии
    из хранилища.
    """

    session_id: str
    """ID сессии для загрузки."""

    server_host: str
    """Адрес ACP сервера."""

    server_port: int
    """Порт ACP сервера."""

    cwd: str | None = None
    """Абсолютный путь рабочей директории для `session/load` (если None, берется текущий)."""

    mcp_servers: list[dict[str, Any]] | None = None
    """Список MCP-серверов для `session/load` (если None, используется пустой список)."""


@dataclass
class LoadSessionResponse:
    """Response DTO для результата загрузки сессии.

    Содержит загруженную сессию и историю для воспроизведения.
    """

    session_id: str
    """ID загруженной сессии."""

    server_capabilities: dict[str, Any]
    """Возможности сервера."""

    is_authenticated: bool
    """Авторизован ли клиент."""

    replay_updates: list[dict[str, Any]]
    """История обновлений для воспроизведения в UI."""


@dataclass
class SendPromptRequest:
    """Request DTO для отправки prompt в сессию.

    Содержит параметры prompt и callbacks для обработки событий.
    """

    session_id: str
    """ID сессии."""

    prompt_text: str
    """Текст prompt."""

    callbacks: PromptCallbacks | None = None
    """Callbacks для обработки событий во время выполнения."""


@dataclass
class PromptCallbacks:
    """Callbacks для обработки событий во время выполнения prompt.

    Содержит функции обработки различных событий,
    которые возникают во время выполнения prompt.
    """

    on_update: Any | None = None
    """Callback при получении обновления сессии."""

    on_fs_read: Any | None = None
    """Callback при чтении файла."""

    on_fs_write: Any | None = None
    """Callback при записи файла."""

    on_terminal_create: Any | None = None
    """Callback при создании терминала."""

    on_terminal_output: Any | None = None
    """Callback при получении вывода терминала."""

    on_terminal_wait_for_exit: Any | None = None
    """Callback при ожидании выхода терминала."""

    on_terminal_release: Any | None = None
    """Callback при освобождении терминала."""

    on_terminal_kill: Any | None = None
    """Callback при завершении терминала."""


@dataclass
class SendPromptResponse:
    """Response DTO для результата отправки prompt.

    Содержит результат выполнения prompt и финальное состояние.
    """

    session_id: str
    """ID сессии."""

    prompt_result: dict[str, Any]
    """Результат выполнения prompt."""

    updates: list[dict[str, Any]]
    """Обновления, полученные во время выполнения."""


@dataclass
class InitializeResponse:
    """Response DTO для результата инициализации.

    Содержит информацию о сервере и его возможностях.
    """

    server_capabilities: dict[str, Any]
    """Возможности сервера."""

    available_auth_methods: list[str]
    """Доступные методы аутентификации."""

    protocol_version: str
    """Версия протокола ACP."""


@dataclass
class ListSessionsResponse:
    """Response DTO для получения списка сессий.

    Содержит список доступных сессий.
    """

    sessions: list[dict[str, Any]]
    """Список сессий с метаданными."""
