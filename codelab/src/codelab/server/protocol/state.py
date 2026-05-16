"""Pydantic-модели для состояния протокола ACP.

Содержит все структуры данных для хранения состояния сессий,
tool calls, и других компонентов протокола.

Использует Pydantic BaseModel для встроенной сериализации/десериализации
вместо ручных методов _serialize_* / _deserialize_*.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from ..messages import ACPMessage, JsonRpcId
from ..models import AvailableCommand, HistoryMessage, PlanStep

if TYPE_CHECKING:
    from ..mcp.manager import MCPManager


class SessionState(BaseModel):
    """Состояние ACP-сессии, хранимое в памяти сервера.

    Объект содержит контекст работы сессии, историю, конфигурацию и состояние
    инструментальных вызовов.

    Пример использования:
        state = SessionState(session_id="sess_1", cwd="/tmp", mcp_servers=[])
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Версия схемы для будущих миграций
    schema_version: int = Field(default=1)

    session_id: str
    cwd: str
    mcp_servers: list[dict[str, Any]] = Field(default_factory=list)
    # Заголовок сессии для UI; выставляется из первого пользовательского запроса.
    title: str | None = None
    # Время последнего изменения сессии в формате ISO 8601.
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    # Значения конфигурационных опций в рамках этой сессии.
    config_values: dict[str, str] = Field(default_factory=dict)
    # Упрощенная история, достаточная для текущих update-сценариев.
    history: list[HistoryMessage | dict[str, Any]] = Field(default_factory=list)
    # Текущее активное выполнение prompt-turn (если есть).
    # Сериализуется для корректного сопоставления permission/client_rpc ответов
    # с сессией через find_session_by_permission_request_id.
    # Очищается при старте нового prompt-turn (см. session_prompt).
    active_turn: ActiveTurnState | None = None
    # Локальный счетчик для стабильной генерации toolCallId.
    tool_call_counter: int = 0
    # Реестр созданных tool calls и их состояний.
    tool_calls: dict[str, ToolCallState] = Field(default_factory=dict)
    # Набор доступных slash-команд для `available_commands_update`.
    available_commands: list[AvailableCommand | dict[str, Any]] = Field(default_factory=list)
    # Последний опубликованный план выполнения для `session/update: plan`.
    latest_plan: list[PlanStep | dict[str, Any]] = Field(default_factory=list)
    # Персистентные permission-решения по kind (например, allow_always).
    permission_policy: dict[str, str] = Field(default_factory=dict)
    # Идентификаторы permission-запросов, отмененных через `session/cancel`.
    # Нужны для детерминированного игнорирования поздних client-responses.
    cancelled_permission_requests: set[JsonRpcId] = Field(default_factory=set)
    # Идентификаторы agent->client RPC, отмененных через `session/cancel`.
    # Поздние ответы на такие запросы должны игнорироваться детерминированно.
    cancelled_client_rpc_requests: set[JsonRpcId] = Field(default_factory=set)
    # Runtime-capabilities клиента, зафиксированные для этой сессии.
    # Используется для фильтрации доступных tools согласно спецификации ACP:
    # "Clients and Agents MUST treat all capabilities omitted in the
    # initialize request as UNSUPPORTED"
    # Структура: {fs_read: bool, fs_write: bool, terminal: bool}
    runtime_capabilities: ClientRuntimeCapabilities | None = None
    # История событий: session/update, permission requests и т.д.
    # Используется для полного восстановления истории при перезагрузке сессии.
    events_history: list[dict[str, Any]] = Field(default_factory=list)
    # MCPManager для управления подключёнными MCP серверами.
    # Используется для интеграции с внешними MCP серверами и их инструментами.
    # Runtime-поле: не сериализуется, пересоздаётся при session/load.
    # Строковая аннотация т.к. MCPManager импортируется только под TYPE_CHECKING.
    mcp_manager: "MCPManager | None" = Field(default=None, exclude=True)  # noqa: UP037

    @field_serializer("cancelled_permission_requests", "cancelled_client_rpc_requests")
    def serialize_set(self, value: set) -> list:
        """set не сериализуется в JSON напрямую — конвертируем в list."""
        return list(value)

    @model_validator(mode="before")
    @classmethod
    def migrate_schema(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Автоматическая миграция старых файлов с данными."""
        if not isinstance(data, dict):
            return data
        version = data.get("schema_version", 0)
        if version < 1:
            # Мигрировать поля из v0 в v1
            data.setdefault("events_history", [])
            data.setdefault("config_values", {})
            data["schema_version"] = 1
        return data


class ToolCallState(BaseModel):
    """Состояние одного tool call внутри prompt-turn.

    Используется для управления жизненным циклом `pending -> in_progress -> ...`
    и генерации корректных `tool_call_update` уведомлений.

    Пример использования:
        call = ToolCallState("call_001", "Demo", "other", "pending")
    """

    # Идентификатор связывает `tool_call` и `tool_call_update` события.
    tool_call_id: str
    # Заголовок для отображения в клиенте.
    title: str
    # Категория вызова (например, other/execute/search).
    kind: str
    # Текущий статус жизненного цикла tool call.
    status: str
    # Контент, возвращенный при завершении (если есть).
    content: list[dict[str, Any]] = Field(default_factory=list)
    # Извлеченный content из result tool execution для отправки клиенту.
    result_content: list[dict[str, Any]] = Field(default_factory=list)
    # Имя инструмента для выполнения (соответствует tool_name в registry).
    tool_name: str | None = None
    # Аргументы для выполнения инструмента (для отложенного выполнения после permission).
    tool_arguments: dict[str, Any] = Field(default_factory=dict)
    # Идентификатор tool_call из LLM ответа (для связки в истории диалога).
    # Может отличаться от tool_call_id, который генерируется нами.
    tool_call_id_from_llm: str | None = None


class ActiveTurnState(BaseModel):
    """Состояние текущего prompt-turn для корректной обработки cancel.

    Содержит идентификатор JSON-RPC запроса prompt и признак запроса отмены.

    Пример использования:
        turn = ActiveTurnState(prompt_request_id="req_1", session_id="sess_1")
    """

    prompt_request_id: JsonRpcId | None
    session_id: str
    cancel_requested: bool = False
    # Идентификатор исходящего permission-request при режиме `ask`.
    permission_request_id: JsonRpcId | None = None
    # Связанный tool call, ожидающий решения пользователя.
    permission_tool_call_id: str | None = None
    # Фаза жизненного цикла prompt-turn для детерминированного поведения.
    phase: str = "running"
    # Исходящий запрос к клиенту (fs/*), если turn ожидает его completion.
    pending_client_request: PendingClientRequestState | None = None


class PromptDirectives(BaseModel):
    """Нормализованные флаги поведения prompt-turn из пользовательского ввода.

    Используются для детерминированной slash-driven оркестрации prompt-turn
    без legacy marker-триггеров.

    Пример использования:
        directives = PromptDirectives(request_tool=True, keep_tool_pending=False)
    """

    request_tool: bool = False
    keep_tool_pending: bool = False
    publish_plan: bool = False
    plan_entries: list[dict[str, str]] | None = None
    tool_kind: str = "other"
    fs_read_path: str | None = None
    fs_write_path: str | None = None
    fs_write_content: str | None = None
    terminal_command: str | None = None
    forced_stop_reason: str | None = None


class PendingClientRequestState(BaseModel):
    """Состояние исходящего agent->client request внутри активного turn.

    Нужно для корреляции входящего client response с ожидаемым действием
    (например, `fs/read_text_file` или `fs/write_text_file`).

    Пример использования:
        pending = PendingClientRequestState(
            request_id="req_1",
            kind="fs_read",
            tool_call_id="call_001",
            path="/tmp/README.md",
        )
    """

    request_id: JsonRpcId
    kind: str
    tool_call_id: str
    path: str
    expected_new_text: str | None = None
    terminal_id: str | None = None
    terminal_output: str | None = None
    terminal_exit_code: int | None = None
    terminal_signal: str | None = None
    terminal_truncated: bool | None = None


class PreparedFsClientRequest(BaseModel):
    """Подготовленный пакет сообщений для fs/* agent->client запроса.

    Пример использования:
        prepared = PreparedFsClientRequest(messages=[...], pending_request=pending)
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    kind: str
    messages: list[ACPMessage]
    pending_request: PendingClientRequestState


class ClientRuntimeCapabilities(BaseModel):
    """Согласованные на `initialize` возможности клиентского runtime.

    Используются как feature-gate для веток, где агент ожидает клиентские
    RPC-возможности (например, запуск инструментов через client-side runtime).

    Пример использования:
        caps = ClientRuntimeCapabilities(fs_read=False, fs_write=False, terminal=True)
    """

    fs_read: bool = False
    fs_write: bool = False
    terminal: bool = False


class PendingToolExecution(BaseModel):
    """Информация о pending tool execution после permission approval.

    Используется для передачи информации от permission handler к http_server
    для выполнения реального tool через tool_registry.
    """

    session_id: str
    tool_call_id: str


class ToolResult(BaseModel):
    """Результат выполнения tool для передачи в LLM.

    Используется в LLM loop для сбора результатов выполнения tool calls
    и отправки их обратно в LLM для продолжения обработки.

    Пример использования:
        result = ToolResult(
            tool_call_id="call_abc123",
            tool_name="fs/read_text_file",
            success=True,
            output="File contents here...",
        )
    """

    tool_call_id: str
    tool_name: str
    success: bool
    output: str | None = None
    error: str | None = None


class LLMLoopResult(BaseModel):
    """Результат выполнения LLM loop.

    Содержит накопленные notifications, статус завершения и информацию
    о pending состояниях (permission, tool calls).

    Пример использования:
        result = LLMLoopResult(
            notifications=[...],
            stop_reason="end_turn",
            final_text="Here is the answer...",
        )
    """

    notifications: list[Any] = Field(default_factory=list)
    # Причина завершения: "end_turn", "cancelled", "max_iterations", None (deferred)
    stop_reason: str | None = None
    # Финальный текстовый ответ от LLM
    final_text: str | None = None
    # Флаг ожидания permission response
    pending_permission: bool = False
    # Оставшиеся tool calls для обработки после permission
    pending_tool_calls: list[Any] = Field(default_factory=list)
    # Накопленные ToolResult для передачи в следующую итерацию
    tool_results: list[ToolResult] = Field(default_factory=list)


class ProtocolOutcome(BaseModel):
    """Результат обработки входящего ACP-сообщения.

    Включает финальный response (если нужен) и список промежуточных
    notifications, которые транспорт должен отправить в указанном порядке.

    Пример использования:
        outcome = ProtocolOutcome(response=ACPMessage.response("id", {}))
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    response: ACPMessage | None = None
    notifications: list[ACPMessage] = Field(default_factory=list)
    # Дополнительные response-сообщения для отложенных JSON-RPC запросов (WS).
    followup_responses: list[ACPMessage] = Field(default_factory=list)
    # Информация о pending tool execution (если требуется асинхронное выполнение после permission).
    pending_tool_execution: PendingToolExecution | None = None


# Разрешаем forward references для Pydantic v2.
# SessionState ссылается на ActiveTurnState, PendingClientRequestState и MCPManager,
# которые определены ниже или импортированы только под TYPE_CHECKING.
def _rebuild_models() -> None:
    """Разрешает forward references после определения всех моделей."""
    # MCPManager нужен для model_rebuild, но импортируется только под TYPE_CHECKING.
    # Импортируем здесь, чтобы избежать циклических зависимостей.
    from ..mcp.manager import MCPManager  # noqa: F401

    SessionState.model_rebuild(_types_namespace={"MCPManager": MCPManager})


_rebuild_models()
