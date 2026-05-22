"""Модели и утилиты клиента для JSON-RPC/ACP сообщений.

Модуль описывает:
- базовые структуры JSON-RPC (`ACPMessage`, `JsonRpcError`),
- типизированный формат уведомления `session/update`,
- парсинг JSON-аргументов CLI.

Пример использования:
    request = ACPMessage.request("initialize", {"protocolVersion": 1})
    payload = request.to_json()
"""

from __future__ import annotations

import json
from json import JSONDecodeError
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, model_validator

type JsonRpcId = str | int


class JsonRpcError(BaseModel):
    """Структура ошибки JSON-RPC, полученной от сервера.

    Поле `data` опционально и содержит дополнительную диагностику.

    Пример использования:
        err = JsonRpcError(code=-32602, message="Invalid params")
    """

    # Код и текст ошибки соответствуют JSON-RPC 2.0.
    code: int
    message: str
    # Произвольные детали ошибки от сервера.
    data: Any | None = None


class ACPMessage(BaseModel):
    """Унифицированная модель JSON-RPC сообщения в клиенте.

    Модель поддерживает три формы:
    - request (есть `method` и `id`),
    - notification (есть `method`, нет `id`),
    - response (нет `method`, есть `result` или `error`).

    Пример использования:
        msg = ACPMessage.request("session/list", {})
        wire = msg.to_dict()
    """

    model_config = ConfigDict(extra="allow")

    jsonrpc: Literal["2.0"] = "2.0"
    id: JsonRpcId | None = None
    method: str | None = None
    params: dict[str, Any] | None = None
    result: Any | None = None
    error: JsonRpcError | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> ACPMessage:
        """Проверяет, что поля сообщения соответствуют форме JSON-RPC.

        Валидатор не допускает:
        - `result/error` в request или notification,
        - отсутствие `result` и `error` в response,
        - одновременное наличие `result` и `error`.

        Пример использования:
            ACPMessage.model_validate({"jsonrpc": "2.0", "id": "1", "result": {}})
        """

        # Отличаем явно переданные поля от отсутствующих для корректной проверки контракта.
        has_result = "result" in self.model_fields_set
        has_error = "error" in self.model_fields_set and self.error is not None

        if self.method is not None:
            if has_result or has_error:
                msg = "Request/notification must not contain result or error"
                raise ValueError(msg)
            return self

        if not has_result and not has_error:
            msg = "Response must contain result or error"
            raise ValueError(msg)
        if has_result and has_error:
            msg = "Response must not contain both result and error"
            raise ValueError(msg)
        return self

    @classmethod
    def request(
        cls,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        request_id: JsonRpcId | None = None,
    ) -> ACPMessage:
        """Создает request-сообщение JSON-RPC с авто-генерацией `id`.

        Если `request_id` не передан, будет сгенерирован короткий hex-идентификатор.

        Пример использования:
            ACPMessage.request("initialize", {"protocolVersion": 1})
        """

        generated_id = request_id if request_id is not None else uuid4().hex[:8]
        return cls(id=generated_id, method=method, params=params or {})

    @classmethod
    def notification(cls, method: str, params: dict[str, Any] | None = None) -> ACPMessage:
        """Создает notification-сообщение JSON-RPC без поля `id`.

        Пример использования:
            ACPMessage.notification("session/cancel", {"sessionId": "sess_1"})
        """

        return cls(id=None, method=method, params=params or {})

    @classmethod
    def response(cls, request_id: JsonRpcId | None, result: Any) -> ACPMessage:
        """Создает успешный response для входящего JSON-RPC запроса.

        Пример использования:
            ACPMessage.response("perm_1", {"outcome": "cancelled"})
        """

        return cls(id=request_id, result=result)

    @classmethod
    def from_json(cls, raw: str) -> ACPMessage:
        """Десериализует JSON-строку в типизированный `ACPMessage`.

        Пример использования:
            ACPMessage.from_json('{"jsonrpc":"2.0","id":"1","result":{}}')
        """

        return cls.model_validate_json(raw)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ACPMessage:
        """Десериализует словарь в `ACPMessage`.

        Пример использования:
            ACPMessage.from_dict({"jsonrpc": "2.0", "id": "1", "result": {}})
        """

        return cls.model_validate(data)

    def to_json(self) -> str:
        """Сериализует сообщение в компактную JSON-строку для транспорта.

        Пример использования:
            wire = ACPMessage.request("ping", {}).to_json()
        """

        return json.dumps(self.to_dict(), separators=(",", ":"))

    def to_dict(self) -> dict[str, Any]:
        """Преобразует сообщение в словарь wire-формата JSON-RPC.

        Метод аккуратно формирует payload:
        - request/notification содержат `method` и опционально `params`,
        - response всегда содержит `id` и одно из `result/error`.

        Пример использования:
            payload = ACPMessage(id="1", result=None).to_dict()
        """

        payload: dict[str, Any] = {"jsonrpc": self.jsonrpc}

        if self.method is not None:
            if self.id is not None:
                payload["id"] = self.id
            payload["method"] = self.method
            if "params" in self.model_fields_set:
                payload["params"] = self.params
            return payload

        payload["id"] = self.id
        if "result" in self.model_fields_set:
            payload["result"] = self.result
        if self.error is not None:
            payload["error"] = self.error.model_dump(exclude_none=True)
        return payload


class AgentCapabilities(BaseModel):
    """Ключевые capability-поля агента из ответа `initialize`.

    Пример использования:
        AgentCapabilities.model_validate({
            "loadSession": True,
            "promptCapabilities": {},
            "mcpCapabilities": {},
            "sessionCapabilities": {},
        })
    """

    loadSession: bool = False
    promptCapabilities: dict[str, Any] = {}
    mcpCapabilities: dict[str, Any] = {}
    sessionCapabilities: dict[str, Any] = {}
    model_config = ConfigDict(extra="allow")


class InitializeResult(BaseModel):
    """Типизированный `result` успешного ответа на `initialize`.

    Пример использования:
        InitializeResult.model_validate({
            "protocolVersion": 1,
            "agentCapabilities": {"loadSession": True},
            "agentInfo": {"name": "agent", "version": "1.0.0"},
            "authMethods": [],
        })
    """

    protocolVersion: int
    agentCapabilities: AgentCapabilities
    agentInfo: dict[str, Any] | None = None
    authMethods: list[AuthMethod] = []
    model_config = ConfigDict(extra="allow")


class AuthMethod(BaseModel):
    """Описание одного метода аутентификации из `initialize`.

    Пример использования:
        AuthMethod.model_validate({"id": "local", "name": "Local", "type": "api_key"})
    """

    id: str
    name: str | None = None
    description: str | None = None
    type: str | None = None
    model_config = ConfigDict(extra="allow")


class SessionListItem(BaseModel):
    """Элемент списка сессий из ответа `session/list`.

    Пример использования:
        SessionListItem.model_validate({
            "sessionId": "sess_1",
            "cwd": "/tmp",
            "updatedAt": "2026-04-07T00:00:00Z",
        })
    """

    sessionId: str
    cwd: str
    title: str | None = None
    updatedAt: str | None = None
    model_config = ConfigDict(extra="allow")


class SessionListResult(BaseModel):
    """Типизированный `result` ответа `session/list`.

    Пример использования:
        SessionListResult.model_validate({"sessions": [], "nextCursor": None})
    """

    sessions: list[SessionListItem]
    nextCursor: str | None = None
    model_config = ConfigDict(extra="allow")


class SessionMode(BaseModel):
    """Описывает один доступный режим работы из `modes.availableModes`.

    Пример использования:
        SessionMode.model_validate({"id": "ask", "name": "Ask mode"})
    """

    id: str
    name: str
    description: str | None = None
    model_config = ConfigDict(extra="allow")


class SessionModeState(BaseModel):
    """Состояние режимов в ответах `session/new` и `session/load`.

    Пример использования:
        SessionModeState.model_validate({"availableModes": [], "currentModeId": "ask"})
    """

    availableModes: list[SessionMode]
    currentModeId: str
    model_config = ConfigDict(extra="allow")


class SessionConfigValueOption(BaseModel):
    """Один selectable-вариант значения конфигурации сессии.

    Пример использования:
        SessionConfigValueOption.model_validate({"value": "ask", "name": "Ask"})
    """

    value: str
    name: str
    description: str | None = None
    model_config = ConfigDict(extra="allow")


class SessionConfigOption(BaseModel):
    """Типизированная запись `configOptions[]` из ответов настройки сессии.

    Пример использования:
        SessionConfigOption.model_validate({
            "id": "mode",
            "name": "Mode",
            "category": "mode",
            "type": "select",
            "currentValue": "ask",
            "options": [{"value": "ask", "name": "Ask"}],
        })
    """

    id: str
    name: str
    category: str
    type: Literal["select"]
    currentValue: str
    options: list[SessionConfigValueOption]
    model_config = ConfigDict(extra="allow")


class SessionSetupResult(BaseModel):
    """Типизированный `result` для `session/new` и `session/load`.

    Пример использования:
        SessionSetupResult.model_validate({"configOptions": [], "modes": {...}})
    """

    sessionId: str | None = None
    configOptions: list[SessionConfigOption]
    modes: SessionModeState | None = None
    model_config = ConfigDict(extra="allow")


class TextContentBlock(BaseModel):
    """Текстовый блок контента ACP (`ContentBlock::text`).

    Пример использования:
        TextContentBlock.model_validate({"type": "text", "text": "hello"})
    """

    type: Literal["text"]
    text: str
    model_config = ConfigDict(extra="allow")


class ImageContentBlock(BaseModel):
    """Изображение в контенте ACP (`ContentBlock::image`).

    Пример использования:
        ImageContentBlock.model_validate({"type": "image", "data": "...", "mimeType": "image/png"})
    """

    type: Literal["image"]
    data: str
    mimeType: str
    uri: str | None = None
    model_config = ConfigDict(extra="allow")


class AudioContentBlock(BaseModel):
    """Аудио-блок ACP (`ContentBlock::audio`).

    Пример использования:
        AudioContentBlock.model_validate({"type": "audio", "data": "...", "mimeType": "audio/wav"})
    """

    type: Literal["audio"]
    data: str
    mimeType: str
    model_config = ConfigDict(extra="allow")


class ResourceLinkContentBlock(BaseModel):
    """Ссылка на ресурс в ACP (`ContentBlock::resource_link`).

    Пример использования:
        ResourceLinkContentBlock.model_validate(
            {"type": "resource_link", "uri": "file:///a", "name": "a"}
        )
    """

    type: Literal["resource_link"]
    uri: str
    name: str
    model_config = ConfigDict(extra="allow")


class EmbeddedResourceContentBlock(BaseModel):
    """Встроенный ресурс ACP (`ContentBlock::resource`).

    Пример использования:
        EmbeddedResourceContentBlock.model_validate({"type": "resource", "resource": {"uri": "file:///a"}})
    """

    type: Literal["resource"]
    resource: dict[str, Any]
    model_config = ConfigDict(extra="allow")


type ContentBlock = (
    TextContentBlock
    | ImageContentBlock
    | AudioContentBlock
    | ResourceLinkContentBlock
    | EmbeddedResourceContentBlock
)


class MessageChunkUpdate(BaseModel):
    """Событие chunk-сообщения (`agent_message_chunk` / `user_message_chunk`).

    Пример использования:
        MessageChunkUpdate.model_validate({
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "hi"},
        })
    """

    sessionUpdate: Literal["agent_message_chunk", "user_message_chunk"]
    content: ContentBlock
    model_config = ConfigDict(extra="allow")


class ThoughtChunkUpdate(BaseModel):
    """Событие `agent_thought_chunk` с reasoning-фрагментом агента.

    Пример использования:
        ThoughtChunkUpdate.model_validate({
            "sessionUpdate": "agent_thought_chunk",
            "content": {"type": "text", "text": "thinking..."},
        })
    """

    sessionUpdate: Literal["agent_thought_chunk"]
    content: ContentBlock
    model_config = ConfigDict(extra="allow")


class SessionInfoUpdate(BaseModel):
    """Событие `session_info_update` с метаданными активной сессии.

    Пример использования:
        SessionInfoUpdate.model_validate({
            "sessionUpdate": "session_info_update",
            "title": "My session",
            "updatedAt": "2026-04-07T00:00:00Z",
        })
    """

    sessionUpdate: Literal["session_info_update"]
    title: str | None = None
    updatedAt: str | None = None
    model_config = ConfigDict(extra="allow")


class CurrentModeUpdate(BaseModel):
    """Событие `current_mode_update` для смены активного режима.

    Пример использования:
        CurrentModeUpdate.model_validate({
            "sessionUpdate": "current_mode_update",
            "currentModeId": "ask",
        })
    """

    sessionUpdate: Literal["current_mode_update"]
    currentModeId: str
    model_config = ConfigDict(extra="allow")


class AvailableCommandInput(BaseModel):
    """Спецификация строкового ввода для slash-команды.

    Пример использования:
        AvailableCommandInput.model_validate({"hint": "Введите текст запроса"})
    """

    hint: str
    model_config = ConfigDict(extra="allow")


class AvailableCommand(BaseModel):
    """Описание одной slash-команды из `available_commands_update`.

    Пример использования:
        AvailableCommand.model_validate({"name": "status", "description": "Show state"})
    """

    name: str
    description: str
    input: AvailableCommandInput | None = None
    model_config = ConfigDict(extra="allow")


class AvailableCommandsUpdate(BaseModel):
    """Событие `available_commands_update` со snapshot команд.

    Пример использования:
        AvailableCommandsUpdate.model_validate({
            "sessionUpdate": "available_commands_update",
            "availableCommands": [],
        })
    """

    sessionUpdate: Literal["available_commands_update"]
    availableCommands: list[AvailableCommand]
    model_config = ConfigDict(extra="allow")


class ConfigOptionUpdate(BaseModel):
    """Событие `config_option_update` с актуальными config options.

    Пример использования:
        ConfigOptionUpdate.model_validate({
            "sessionUpdate": "config_option_update",
            "configOptions": [],
        })
    """

    sessionUpdate: Literal["config_option_update"]
    configOptions: list[SessionConfigOption]
    model_config = ConfigDict(extra="allow")


class SessionUpdatePayload(BaseModel):
    """Полезная нагрузка события `session/update`.

    Поле `sessionUpdate` задает тип события, остальные поля зависят от него.

    Пример использования:
        SessionUpdatePayload.model_validate({"sessionUpdate": "agent_message_chunk"})
    """

    # Дискриминатор типа события в `session/update`.
    sessionUpdate: str
    # Дальнейшие поля зависят от конкретного типа update.
    model_config = ConfigDict(extra="allow")


class SessionUpdateParams(BaseModel):
    """Параметры notification `session/update`.

    Содержат `sessionId` и вложенный объект update.

    Пример использования:
        SessionUpdateParams.model_validate({
            "sessionId": "sess_1",
            "update": {"sessionUpdate": "session_info_update"},
        })
    """

    # Идентификатор сессии, к которой относится update.
    sessionId: str
    # Расширяемое поле метаданных ACP для транспортной/клиентской интеграции.
    _meta: dict[str, Any] | None = None
    # Полезная нагрузка update-события.
    update: SessionUpdatePayload
    model_config = ConfigDict(extra="allow")


class SessionUpdateNotification(BaseModel):
    """Типизированное уведомление `session/update`.

    Модель используется в клиенте для безопасной обработки replay/update-потока.

    Пример использования:
        SessionUpdateNotification.model_validate(payload)
    """

    # Notification всегда в формате JSON-RPC 2.0.
    jsonrpc: Literal["2.0"] = "2.0"
    # Для данного помощника принимаем только `session/update`.
    method: Literal["session/update"]
    params: SessionUpdateParams
    model_config = ConfigDict(extra="allow")


type ToolKind = Literal[
    "read",
    "edit",
    "delete",
    "move",
    "search",
    "execute",
    "think",
    "fetch",
    "switch_mode",
    "other",
]


type ToolCallStatus = Literal[
    "pending",
    "in_progress",
    "completed",
    "failed",
    "cancelled",
]


class ToolCallLocation(BaseModel):
    """Локация файла, затронутого вызовом инструмента.

    Пример использования:
        ToolCallLocation.model_validate({"path": "src/main.py", "line": 42})
    """

    path: str
    line: int | None = None
    model_config = ConfigDict(extra="allow")


class ToolCallContentBlock(BaseModel):
    """Контент-элемент tool call с обычным ACP ContentBlock.

    Пример использования:
        ToolCallContentBlock.model_validate({
            "type": "content",
            "content": {"type": "text", "text": "done"},
        })
    """

    type: Literal["content"]
    content: ContentBlock
    model_config = ConfigDict(extra="allow")


class ToolCallDiffContent(BaseModel):
    """Контент-элемент tool call для diff-представления изменений файла.

    Пример использования:
        ToolCallDiffContent.model_validate({
            "type": "diff",
            "path": "README.md",
            "oldText": "old",
            "newText": "new",
        })
    """

    type: Literal["diff"]
    path: str
    newText: str
    oldText: str | None = None
    model_config = ConfigDict(extra="allow")


class ToolCallTerminalContent(BaseModel):
    """Контент-элемент tool call со ссылкой на терминал клиента.

    Пример использования:
        ToolCallTerminalContent.model_validate({
            "type": "terminal",
            "terminalId": "term_1",
        })
    """

    type: Literal["terminal"]
    terminalId: str
    model_config = ConfigDict(extra="allow")


type ToolCallContent = ToolCallContentBlock | ToolCallDiffContent | ToolCallTerminalContent


class ToolCallCreatedUpdate(BaseModel):
    """Типизированный payload для события `tool_call`.

    Используется, когда агент объявляет новый вызов инструмента.

    Пример использования:
        ToolCallCreatedUpdate.model_validate({
            "sessionUpdate": "tool_call",
            "toolCallId": "call_001",
            "title": "Demo tool",
            "kind": "other",
            "status": "pending",
        })
    """

    sessionUpdate: Literal["tool_call"]
    toolCallId: str
    title: str
    kind: ToolKind | None = None
    status: ToolCallStatus | None = None
    content: list[ToolCallContent] | None = None
    locations: list[ToolCallLocation] | None = None
    rawInput: dict[str, Any] | None = None
    rawOutput: dict[str, Any] | None = None
    model_config = ConfigDict(extra="allow")


class ToolCallStateUpdate(BaseModel):
    """Типизированный payload для события `tool_call_update`.

    Используется при изменении статуса уже созданного вызова инструмента.

    Пример использования:
        ToolCallStateUpdate.model_validate({
            "sessionUpdate": "tool_call_update",
            "toolCallId": "call_001",
            "status": "completed",
        })
    """

    sessionUpdate: Literal["tool_call_update"]
    toolCallId: str
    status: ToolCallStatus | None = None
    title: str | None = None
    kind: ToolKind | None = None
    content: list[ToolCallContent] | None = None
    locations: list[ToolCallLocation] | None = None
    rawInput: dict[str, Any] | None = None
    rawOutput: dict[str, Any] | None = None
    model_config = ConfigDict(extra="allow")


type ToolCallUpdate = ToolCallCreatedUpdate | ToolCallStateUpdate


class PlanEntry(BaseModel):
    """Элемент плана из `session/update` с типом `plan`.

    Пример использования:
        PlanEntry.model_validate({
            "content": "Собрать контекст",
            "priority": "high",
            "status": "pending",
        })
    """

    content: str
    priority: Literal["high", "medium", "low"]
    status: Literal["pending", "in_progress", "completed"]
    model_config = ConfigDict(extra="allow")


class PlanUpdate(BaseModel):
    """Типизированный payload события `plan`.

    Пример использования:
        PlanUpdate.model_validate({
            "sessionUpdate": "plan",
            "entries": [],
        })
    """

    sessionUpdate: Literal["plan"]
    entries: list[PlanEntry]
    model_config = ConfigDict(extra="allow")


type StructuredSessionUpdate = (
    ToolCallUpdate
    | PlanUpdate
    | MessageChunkUpdate
    | ThoughtChunkUpdate
    | SessionInfoUpdate
    | CurrentModeUpdate
    | AvailableCommandsUpdate
    | ConfigOptionUpdate
)


class PermissionOption(BaseModel):
    """Описывает один вариант выбора в `session/request_permission`.

    Пример использования:
        PermissionOption.model_validate({
            "optionId": "allow_once",
            "name": "Allow once",
            "kind": "allow_once",
        })
    """

    optionId: str
    name: str
    kind: Literal["allow_once", "allow_always", "reject_once", "reject_always"]
    model_config = ConfigDict(extra="allow")


class PermissionToolCall(BaseModel):
    """Типизированное описание tool call в `session/request_permission`.

    Пример использования:
        PermissionToolCall.model_validate({"toolCallId": "call_001", "title": "Run"})
    """

    toolCallId: str
    title: str | None = None
    kind: ToolKind | None = None
    status: ToolCallStatus | None = None
    model_config = ConfigDict(extra="allow")


class RequestPermissionPayload(BaseModel):
    """Параметры запроса `session/request_permission` от агента к клиенту.

    Пример использования:
        RequestPermissionPayload.model_validate({
            "sessionId": "sess_1",
            "toolCall": {},
            "options": [],
        })
    """

    sessionId: str
    toolCall: PermissionToolCall
    options: list[PermissionOption]
    model_config = ConfigDict(extra="allow")


class RequestPermissionRequest(BaseModel):
    """Типизированное представление запроса `session/request_permission`.

    Пример использования:
        RequestPermissionRequest.model_validate(payload)
    """

    jsonrpc: Literal["2.0"] = "2.0"
    id: JsonRpcId
    method: Literal["session/request_permission"]
    params: RequestPermissionPayload
    model_config = ConfigDict(extra="allow")


class CancelledPermissionOutcome(BaseModel):
    """Ответ клиента, если permission-request отменен.

    Пример использования:
        CancelledPermissionOutcome(outcome="cancelled")
    """

    outcome: Literal["cancelled"]


class SelectedPermissionOutcome(BaseModel):
    """Ответ клиента с выбранной permission-опцией.

    Пример использования:
        SelectedPermissionOutcome(outcome="selected", optionId="allow_once")
    """

    outcome: Literal["selected"]
    optionId: str


type PermissionOutcome = CancelledPermissionOutcome | SelectedPermissionOutcome


type StopReason = Literal[
    "end_turn",
    "max_tokens",
    "max_turn_requests",
    "refusal",
    "cancelled",
]


class PromptResult(BaseModel):
    """Типизированный `result` ответа на `session/prompt`.

    Пример использования:
        PromptResult.model_validate({"stopReason": "end_turn"})
    """

    stopReason: StopReason
    model_config = ConfigDict(extra="allow")


class AuthenticateResult(BaseModel):
    """Типизированный `result` ответа на `authenticate`.

    По схеме ACP ответ — пустой объект с optional `_meta`.

    Пример использования:
        AuthenticateResult.model_validate({})
    """

    model_config = ConfigDict(extra="allow")


def parse_session_update_notification(payload: dict[str, Any]) -> SessionUpdateNotification | None:
    """Пытается распарсить словарь как `session/update` notification.

    Возвращает `None`, если передан payload другого метода.

    Пример использования:
        parsed = parse_session_update_notification(raw_payload)
    """

    # Если это не `session/update`, возвращаем None для удобной фильтрации.
    if payload.get("method") != "session/update":
        return None
    return SessionUpdateNotification.model_validate(payload)


def parse_tool_call_update(update: SessionUpdateNotification) -> ToolCallUpdate | None:
    """Пытается распарсить `session/update` как tool-call событие.

    Возвращает `None`, если update относится к другому типу событий
    (`agent_message_chunk`, `session_info_update`, и т.д.).

    Пример использования:
        parsed = parse_tool_call_update(notification)
    """

    payload = update.params.update.model_dump()
    session_update_type = payload.get("sessionUpdate")
    if session_update_type == "tool_call":
        return ToolCallCreatedUpdate.model_validate(payload)
    if session_update_type == "tool_call_update":
        return ToolCallStateUpdate.model_validate(payload)
    return None


def parse_plan_update(update: SessionUpdateNotification) -> PlanUpdate | None:
    """Пытается распарсить `session/update` как событие плана выполнения.

    Возвращает `None`, если update относится к другому типу.

    Пример использования:
        parsed = parse_plan_update(notification)
    """

    payload = update.params.update.model_dump()
    if payload.get("sessionUpdate") != "plan":
        return None
    return PlanUpdate.model_validate(payload)


def parse_structured_session_update(
    update: SessionUpdateNotification,
) -> StructuredSessionUpdate | None:
    """Пытается распарсить `session/update` в один из известных typed payload.

    Возвращает `None`, если тип update пока не поддерживается типизированной
    моделью в клиенте.

    Пример использования:
        parsed = parse_structured_session_update(notification)
    """

    payload = update.params.update.model_dump()
    session_update_type = payload.get("sessionUpdate")
    if session_update_type in {"tool_call", "tool_call_update"}:
        return parse_tool_call_update(update)
    if session_update_type == "plan":
        return PlanUpdate.model_validate(payload)
    if session_update_type in {"agent_message_chunk", "user_message_chunk"}:
        return MessageChunkUpdate.model_validate(payload)
    if session_update_type == "agent_thought_chunk":
        return ThoughtChunkUpdate.model_validate(payload)
    if session_update_type == "session_info_update":
        return SessionInfoUpdate.model_validate(payload)
    if session_update_type == "current_mode_update":
        return CurrentModeUpdate.model_validate(payload)
    if session_update_type == "available_commands_update":
        return AvailableCommandsUpdate.model_validate(payload)
    if session_update_type == "config_option_update":
        return ConfigOptionUpdate.model_validate(payload)
    return None


def parse_request_permission_request(payload: dict[str, Any]) -> RequestPermissionRequest | None:
    """Пытается распарсить payload как `session/request_permission` request.

    Возвращает `None`, если payload относится к другому методу.

    Пример использования:
        request = parse_request_permission_request(raw_payload)
    """

    if payload.get("method") != "session/request_permission":
        return None
    return RequestPermissionRequest.model_validate(payload)


def parse_initialize_result(message: ACPMessage) -> InitializeResult:
    """Преобразует JSON-RPC response в типизированный `initialize` result.

    Бросает `ValueError`, если response содержит `error` или не имеет корректного
    объекта `result`.

    Пример использования:
        parsed = parse_initialize_result(response)
    """

    if message.error is not None:
        msg = f"Initialize failed: {message.error.code} {message.error.message}"
        raise ValueError(msg)
    if not isinstance(message.result, dict):
        raise ValueError("Initialize response must contain object result")
    return InitializeResult.model_validate(message.result)


def parse_session_list_result(message: ACPMessage) -> SessionListResult:
    """Преобразует JSON-RPC response в типизированный `session/list` result.

    Бросает `ValueError`, если response содержит `error` или невалидный `result`.

    Пример использования:
        parsed = parse_session_list_result(response)
    """

    if message.error is not None:
        msg = f"Session list failed: {message.error.code} {message.error.message}"
        raise ValueError(msg)
    if not isinstance(message.result, dict):
        raise ValueError("session/list response must contain object result")
    return SessionListResult.model_validate(message.result)


def parse_session_setup_result(message: ACPMessage, *, method_name: str) -> SessionSetupResult:
    """Преобразует response `session/new`/`session/load` в `SessionSetupResult`.

    Бросает `ValueError`, если response содержит `error` или невалидный `result`.

    Пример использования:
        parsed = parse_session_setup_result(response, method_name="session/new")
    """

    if message.error is not None:
        msg = f"{method_name} failed: {message.error.code} {message.error.message}"
        raise ValueError(msg)
    if not isinstance(message.result, dict):
        msg = f"{method_name} response must contain object result"
        raise ValueError(msg)
    return SessionSetupResult.model_validate(message.result)


def parse_prompt_result(message: ACPMessage) -> PromptResult:
    """Преобразует response `session/prompt` в типизированный `PromptResult`.

    Бросает `ValueError`, если response содержит ошибку или невалидный `result`.

    Пример использования:
        parsed = parse_prompt_result(response)
    """

    if message.error is not None:
        msg = f"session/prompt failed: {message.error.code} {message.error.message}"
        raise ValueError(msg)
    if not isinstance(message.result, dict):
        raise ValueError("session/prompt response must contain object result")
    return PromptResult.model_validate(message.result)


def parse_authenticate_result(message: ACPMessage) -> AuthenticateResult:
    """Преобразует response `authenticate` в типизированный результат.

    Бросает `ValueError`, если response содержит ошибку или невалидный `result`.

    Пример использования:
        parsed = parse_authenticate_result(response)
    """

    if message.error is not None:
        msg = f"authenticate failed: {message.error.code} {message.error.message}"
        raise ValueError(msg)
    if not isinstance(message.result, dict):
        raise ValueError("authenticate response must contain object result")
    return AuthenticateResult.model_validate(message.result)


def parse_json_params(value: str | None) -> dict[str, Any]:
    """Парсит значение `--params` из CLI в JSON-объект.

    Функция принимает только JSON-объект на верхнем уровне, чтобы параметры
    запроса всегда имели формат `dict[str, Any]`.

    Пример использования:
        params = parse_json_params('{"sessionId":"sess_1"}')
    """

    # CLI принимает params строкой; здесь приводим к JSON-объекту для ACP запроса.
    if value is None:
        return {}

    try:
        data = json.loads(value)
    except JSONDecodeError as exc:
        msg = f"Invalid JSON in --params: {exc.msg}"
        raise ValueError(msg) from exc

    if not isinstance(data, dict):
        raise ValueError("--params must be a JSON object")

    return data
