"""Pydantic модели для MCP (Model Context Protocol).

Содержит модели для JSON-RPC 2.0 сообщений MCP протокола,
включая запросы, ответы, нотификации и модели инструментов.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ===== JSON-RPC 2.0 Base Models =====


class MCPRequest(BaseModel):
    """JSON-RPC 2.0 запрос для MCP протокола.
    
    Используется для отправки запросов к MCP серверу с ожиданием ответа.
    """
    
    model_config = ConfigDict(populate_by_name=True)
    
    jsonrpc: Literal["2.0"] = "2.0"
    """Версия JSON-RPC протокола."""
    
    id: int | str
    """Уникальный идентификатор запроса для сопоставления с ответом."""
    
    method: str
    """Имя вызываемого метода."""
    
    params: dict[str, Any] | None = None
    """Параметры метода (опционально)."""


class MCPResponse(BaseModel):
    """JSON-RPC 2.0 ответ от MCP сервера.
    
    Содержит либо результат успешного выполнения, либо ошибку.
    """
    
    model_config = ConfigDict(populate_by_name=True)
    
    jsonrpc: Literal["2.0"] = "2.0"
    """Версия JSON-RPC протокола."""
    
    id: int | str | None
    """Идентификатор запроса, на который это ответ."""
    
    result: dict[str, Any] | None = None
    """Результат успешного выполнения (отсутствует при ошибке)."""
    
    error: MCPError | None = None
    """Информация об ошибке (отсутствует при успехе)."""


class MCPNotification(BaseModel):
    """JSON-RPC 2.0 нотификация для MCP протокола.
    
    Односторонняя отправка сообщения без ожидания ответа.
    """
    
    model_config = ConfigDict(populate_by_name=True)
    
    jsonrpc: Literal["2.0"] = "2.0"
    """Версия JSON-RPC протокола."""
    
    method: str
    """Имя метода нотификации."""
    
    params: dict[str, Any] | None = None
    """Параметры нотификации (опционально)."""


class MCPError(BaseModel):
    """Структура ошибки JSON-RPC 2.0.
    
    Содержит код ошибки, сообщение и дополнительные данные.
    """
    
    code: int
    """Код ошибки (стандартные JSON-RPC или MCP-специфичные)."""
    
    message: str
    """Краткое описание ошибки."""
    
    data: Any | None = None
    """Дополнительные данные об ошибке (опционально)."""


# ===== MCP Server Info Models =====


class MCPServerInfo(BaseModel):
    """Информация о MCP сервере.
    
    Возвращается сервером при инициализации.
    """
    
    name: str
    """Имя MCP сервера."""
    
    version: str
    """Версия сервера."""


class MCPClientInfo(BaseModel):
    """Информация о MCP клиенте.
    
    Отправляется серверу при инициализации.
    """
    
    name: str
    """Имя клиента."""
    
    version: str
    """Версия клиента."""


class MCPCapabilities(BaseModel):
    """Capabilities MCP сервера.
    
    Описывает поддерживаемые возможности сервера.
    """
    
    model_config = ConfigDict(extra="allow")
    
    tools: dict[str, Any] | None = None
    """Поддержка инструментов (tools)."""
    
    resources: dict[str, Any] | None = None
    """Поддержка ресурсов (resources)."""
    
    prompts: dict[str, Any] | None = None
    """Поддержка промптов (prompts)."""
    
    logging: dict[str, Any] | None = None
    """Поддержка логирования."""


class MCPInitializeParams(BaseModel):
    """Параметры запроса initialize.
    
    Отправляются MCP серверу для инициализации соединения.
    """
    
    model_config = ConfigDict(populate_by_name=True)
    
    protocol_version: str = Field(alias="protocolVersion")
    """Версия MCP протокола (например, "2024-11-05")."""
    
    capabilities: dict[str, Any] = Field(default_factory=dict)
    """Capabilities клиента."""
    
    client_info: MCPClientInfo = Field(alias="clientInfo")
    """Информация о клиенте."""


class MCPInitializeResult(BaseModel):
    """Результат initialize от MCP сервера.
    
    Содержит информацию о сервере и его capabilities.
    """
    
    model_config = ConfigDict(populate_by_name=True)
    
    protocol_version: str = Field(alias="protocolVersion")
    """Версия протокола, согласованная сервером."""
    
    capabilities: MCPCapabilities
    """Capabilities сервера."""
    
    server_info: MCPServerInfo = Field(alias="serverInfo")
    """Информация о сервере."""
    
    instructions: str | None = None
    """Инструкции от сервера (опционально)."""


# ===== MCP Tool Models =====


class MCPToolInputSchema(BaseModel):
    """JSON Schema для входных параметров инструмента.
    
    Описывает структуру аргументов, которые принимает инструмент.
    """
    
    model_config = ConfigDict(extra="allow")
    
    type: str = "object"
    """Тип схемы (обычно object)."""
    
    properties: dict[str, Any] = Field(default_factory=dict)
    """Описания свойств (аргументов инструмента)."""
    
    required: list[str] = Field(default_factory=list)
    """Список обязательных аргументов."""


class MCPToolAnnotations(BaseModel):
    """Аннотации MCP инструмента (ToolAnnotations по MCP spec 2025-06-18).

    Используются для UX/kind mapping — не влияют на security/permission решения.
    """

    model_config = ConfigDict(populate_by_name=True)

    title: str | None = None
    """Человекочитаемое название инструмента."""

    read_only_hint: bool | None = Field(default=None, alias="readOnlyHint")
    """True если инструмент только читает данные (не изменяет)."""

    destructive_hint: bool | None = Field(default=None, alias="destructiveHint")
    """True если инструмент может разрушительно изменять данные."""

    idempotent_hint: bool | None = Field(default=None, alias="idempotentHint")
    """True если повторный вызов с теми же аргументами не меняет результат."""

    open_world_hint: bool | None = Field(default=None, alias="openWorldHint")
    """True если инструмент работает с открытым миром (внешние API, веб)."""


class MCPTool(BaseModel):
    """Определение инструмента MCP сервера.

    Содержит имя, описание и схему входных параметров.
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str
    """Уникальное имя инструмента."""

    description: str | None = None
    """Описание назначения инструмента."""

    input_schema: MCPToolInputSchema = Field(
        alias="inputSchema",
        default_factory=MCPToolInputSchema
    )
    """JSON Schema входных параметров."""

    annotations: MCPToolAnnotations | None = None
    """Опциональные аннотации инструмента (hints для kind inference)."""


class MCPListToolsResult(BaseModel):
    """Результат запроса tools/list.
    
    Содержит список доступных инструментов на MCP сервере.
    """
    
    tools: list[MCPTool]
    """Список доступных инструментов."""


# ===== MCP Resource Models =====


class MCPResource(BaseModel):
    """Определение ресурса MCP сервера.
    
    Содержит URI, имя и описание ресурса.
    """
    
    model_config = ConfigDict(populate_by_name=True)
    
    uri: str
    """Уникальный URI ресурса."""
    
    name: str
    """Человекочитаемое имя ресурса."""
    
    description: str | None = None
    """Описание ресурса."""
    
    mime_type: str | None = Field(default=None, alias="mimeType")
    """MIME-тип ресурса (например, text/plain, image/png)."""


class MCPListResourcesResult(BaseModel):
    """Результат запроса resources/list.
    
    Содержит список доступных ресурсов на MCP сервере.
    """
    
    resources: list[MCPResource]
    """Список доступных ресурсов."""


class MCPReadResourceResult(BaseModel):
    """Результат запроса resources/read.
    
    Содержит содержимое ресурса.
    """
    
    model_config = ConfigDict(populate_by_name=True)
    
    contents: list[dict[str, Any]]
    """Список элементов содержимого ресурса."""
    
    def get_text_content(self) -> str:
        """Извлечь текстовый контент из результата.
        
        Returns:
            Объединённый текст из всех текстовых элементов.
        """
        texts: list[str] = []
        for item in self.contents:
            if item.get("type") == "text":
                texts.append(item.get("text", ""))
        return "\n".join(texts)


# ===== MCP Prompt Models =====


class MCPPromptArgument(BaseModel):
    """Определение аргумента промпта MCP сервера."""
    
    model_config = ConfigDict(populate_by_name=True)
    
    name: str
    """Имя аргумента."""
    
    description: str | None = None
    """Описание аргумента."""
    
    required: bool = False
    """Обязателен ли аргумент."""


class MCPPrompt(BaseModel):
    """Определение промпта MCP сервера.
    
    Содержит имя, описание и аргументы промпта.
    """
    
    model_config = ConfigDict(populate_by_name=True)
    
    name: str
    """Уникальное имя промпта."""
    
    description: str | None = None
    """Описание промпта."""
    
    arguments: list[MCPPromptArgument] = Field(default_factory=list)
    """Список аргументов промпта."""


class MCPListPromptsResult(BaseModel):
    """Результат запроса prompts/list.
    
    Содержит список доступных промптов на MCP сервере.
    """
    
    prompts: list[MCPPrompt]
    """Список доступных промптов."""


class MCPGetPromptResult(BaseModel):
    """Результат запроса prompts/get.
    
    Содержит промпт с заполненными placeholder'ами.
    """
    
    model_config = ConfigDict(populate_by_name=True)
    
    description: str | None = None
    """Описание промпта."""
    
    messages: list[dict[str, Any]]
    """Список сообщений промпта."""


# ===== MCP Tool Call Models =====


class MCPCallToolParams(BaseModel):
    """Параметры запроса tools/call.
    
    Содержит имя инструмента и аргументы для вызова.
    """
    
    name: str
    """Имя вызываемого инструмента."""
    
    arguments: dict[str, Any] = Field(default_factory=dict)
    """Аргументы для инструмента."""


class MCPTextContent(BaseModel):
    """Текстовый контент в результате вызова инструмента."""
    
    type: Literal["text"] = "text"
    """Тип контента."""
    
    text: str
    """Текстовое содержимое."""


class MCPImageContent(BaseModel):
    """Изображение в результате вызова инструмента (base64)."""
    
    type: Literal["image"] = "image"
    """Тип контента."""
    
    data: str
    """Base64-закодированное изображение."""
    
    mime_type: str = Field(alias="mimeType")
    """MIME-тип изображения (например, image/png)."""


class MCPEmbeddedResource(BaseModel):
    """Встроенный ресурс в результате вызова инструмента."""
    
    type: Literal["resource"] = "resource"
    """Тип контента."""
    
    resource: dict[str, Any]
    """Данные ресурса."""


# Объединённый тип для контента в результатах
MCPContent = MCPTextContent | MCPImageContent | MCPEmbeddedResource


class MCPCallToolResult(BaseModel):
    """Результат вызова инструмента tools/call.
    
    Содержит контент результата и флаг ошибки.
    """
    
    model_config = ConfigDict(populate_by_name=True)
    
    content: list[dict[str, Any]] = Field(default_factory=list)
    """Список элементов контента результата."""
    
    is_error: bool = Field(default=False, alias="isError")
    """True если инструмент вернул ошибку."""
    
    def get_text_content(self) -> str:
        """Извлечь текстовый контент из результата.
        
        Returns:
            Объединённый текст из всех текстовых элементов.
        """
        texts: list[str] = []
        for item in self.content:
            if item.get("type") == "text":
                texts.append(item.get("text", ""))
        return "\n".join(texts)


# ===== MCP Server Configuration =====


class MCPServerConfig(BaseModel):
    """Конфигурация MCP сервера из параметров session/new.
    
    Описывает как запустить и подключиться к MCP серверу.
    Поддерживает три типа транспорта: stdio, http, sse.
    """
    
    model_config = ConfigDict(populate_by_name=True)
    
    name: str
    """Уникальное имя сервера (идентификатор)."""
    
    type: str = "stdio"
    """Тип транспорта: stdio, http, sse."""
    
    # Stdio transport параметры
    command: str | None = None
    """Команда для запуска сервера (для stdio)."""
    
    args: list[str] = Field(default_factory=list)
    """Аргументы командной строки (для stdio)."""
    
    env: list[dict[str, str]] = Field(default_factory=list)
    """Переменные окружения как список {name: value}."""
    
    # HTTP/SSE transport параметры
    url: str | None = None
    """URL MCP сервера (для http/sse)."""
    
    headers: list[dict[str, str]] = Field(default_factory=list)
    """HTTP headers для запросов (для http/sse)."""
    
    # Retry configuration
    max_retries: int = 5
    """Максимальное количество попыток переподключения."""
    
    initial_delay: float = 1.0
    """Начальная задержка между попытками (секунды)."""
    
    max_delay: float = 30.0
    """Максимальная задержка между попытками (секунды)."""
    
    backoff_multiplier: float = 2.0
    """Множитель для exponential backoff."""
    
    def model_post_init(self, __context) -> None:
        """Валидация конфигурации после инициализации."""
        # Stdio требует command
        if self.type == "stdio" and not self.command:
            raise ValueError(
                "MCPServerConfig: type='stdio' requires 'command' field"
            )
        
        # HTTP/SSE требует url
        if self.type in ("http", "sse") and not self.url:
            raise ValueError(
                f"MCPServerConfig: type='{self.type}' requires 'url' field"
            )
    
    def get_env_dict(self) -> dict[str, str]:
        """Преобразовать список env в словарь.
        
        Returns:
            Словарь переменных окружения.
        """
        result: dict[str, str] = {}
        for item in self.env:
            # Формат может быть {"name": "KEY", "value": "VAL"} или {"KEY": "VAL"}
            if "name" in item and "value" in item:
                result[item["name"]] = item["value"]
            else:
                result.update(item)
        return result
    
    def get_connection_params(self) -> dict[str, Any]:
        """Получить параметры подключения в зависимости от типа транспорта.
        
        Returns:
            Словарь параметров для транспорта.
        
        Raises:
            ValueError: Если тип транспорта не поддерживается.
        """
        if self.type == "stdio":
            return {
                "command": self.command,
                "args": self.args,
                "env": self.get_env_dict(),
            }
        elif self.type in ("http", "sse"):
            return {
                "url": self.url,
                "headers": self.headers,
            }
        else:
            raise ValueError(f"Unsupported transport type: {self.type}")
    
    def get_retry_config(self) -> dict[str, float | int]:
        """Получить конфигурацию retry.
        
        Returns:
            Словарь с retry parameters.
        """
        return {
            "max_retries": self.max_retries,
            "initial_delay": self.initial_delay,
            "max_delay": self.max_delay,
            "backoff_multiplier": self.backoff_multiplier,
        }
