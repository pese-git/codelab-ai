"""Pydantic модели для RPC запросов и ответов.

Содержит V2 Pydantic модели для сериализации и десериализации JSON-RPC сообщений,
отправляемых клиенту и получаемых от него.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ===== Internal State Models =====


@dataclass
class PendingRequest:
    """Ожидающий RPC запрос с поддержкой отмены.
    
    Хранит состояние ожидающего RPC запроса, включая Future для получения
    результата и Event для координированной отмены без timeout.
    
    Attributes:
        future: asyncio.Future для получения результата от клиента
        cancellation_event: Event для сигнализации об отмене запроса
        method: Имя вызываемого RPC метода (для логирования/диагностики)
        created_at: Время создания запроса (Unix timestamp)
    """
    
    future: asyncio.Future[Any]
    cancellation_event: asyncio.Event = field(default_factory=asyncio.Event)
    method: str = ""
    created_at: float = field(default_factory=time.time)

# ===== File System Models =====


class ReadTextFileRequest(BaseModel):
    """Запрос на чтение текстового файла (отправляется клиенту).
    
    Используется для чтения содержимого текстового файла из окружения клиента.
    Поддерживает чтение с начальной строки и лимитом строк.
    """

    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(..., alias="sessionId")
    """ID сессии для которой выполняется операция."""

    path: str
    """Путь к файлу (абсолютный или относительный от рабочей директории)."""

    line: int | None = None
    """Начальная строка для чтения (0-based, опционально)."""

    limit: int | None = None
    """Максимум строк для чтения (опционально)."""


class ReadTextFileResponse(BaseModel):
    """Ответ с содержимым файла (получен от клиента).
    
    Возвращает полное содержимое файла или подмножество строк.
    """

    content: str
    """Содержимое файла."""


class WriteTextFileRequest(BaseModel):
    """Запрос на запись файла (отправляется клиенту).
    
    Используется для записи содержимого в текстовый файл в окружении клиента.
    """

    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(..., alias="sessionId")
    """ID сессии для которой выполняется операция."""

    path: str
    """Путь к файлу (абсолютный или относительный от рабочей директории)."""

    content: str
    """Содержимое для записи в файл."""


class WriteTextFileResponse(BaseModel):
    """Подтверждение записи (получено от клиента).
    
    Согласно ACP spec, response не содержит полей кроме опционального _meta.
    Наличие ответа (без ошибки) означает успешную запись.
    """

    model_config = ConfigDict(extra="allow")


# ===== Terminal Models =====


class TerminalCreateRequest(BaseModel):
    """Запрос на создание терминала и запуск команды.
    
    Используется для создания нового терминального сеанса в окружении клиента
    и запуска в нём команды.
    """

    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(..., alias="sessionId")
    """ID сессии для которой создаётся терминал."""

    command: str
    """Команда для выполнения."""

    args: list[str] | None = None
    """Аргументы команды (опционально)."""

    env: dict[str, str] | None = None
    """Переменные окружения (опционально)."""

    cwd: str | None = None
    """Рабочая директория для команды (опционально)."""

    output_byte_limit: int | None = Field(None, alias="outputByteLimit")
    """Лимит байт для сохранения output (опционально)."""


class TerminalCreateResponse(BaseModel):
    """Ответ с ID терминала (получен от клиента).
    
    Возвращает уникальный идентификатор созданного терминала.
    """

    model_config = ConfigDict(populate_by_name=True)

    terminal_id: str = Field(..., alias="terminalId")
    """Уникальный ID терминального сеанса."""


class TerminalOutputRequest(BaseModel):
    """Запрос на получение output терминала.
    
    Используется для получения текущего output из работающего терминала.
    """

    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(..., alias="sessionId")
    """ID сессии."""

    terminal_id: str = Field(..., alias="terminalId")
    """ID терминального сеанса."""


class TerminalExitStatus(BaseModel):
    """Статус завершения терминала (часть terminal/output response).
    
    Соответствует ACP spec TerminalExitStatus.
    """

    model_config = ConfigDict(populate_by_name=True)

    exit_code: int | None = Field(None, alias="exitCode")
    """Код завершения (может быть None если завершён сигналом)."""

    signal: str | None = Field(None, alias="signal")
    """Сигнал, завершивший процесс (может быть None)."""


class TerminalOutputResponse(BaseModel):
    """Ответ с output терминала (получен от клиента).
    
    Соответствует ACP spec для terminal/output.
    """

    model_config = ConfigDict(populate_by_name=True)

    output: str
    """Накопленный output терминала."""

    truncated: bool = False
    """True если output был обрезан из-за лимита байт."""

    exit_status: TerminalExitStatus | None = Field(None, alias="exitStatus")
    """Статус завершения (присутствует только если команда завершилась)."""


class TerminalWaitForExitRequest(BaseModel):
    """Запрос на ожидание завершения команды в терминале.
    
    Используется для блокирующего ожидания завершения команды.
    """

    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(..., alias="sessionId")
    """ID сессии."""

    terminal_id: str = Field(..., alias="terminalId")
    """ID терминального сеанса."""

    timeout: float | None = None
    """Timeout ожидания в секундах (опционально)."""


class TerminalWaitForExitResponse(BaseModel):
    """Ответ после завершения команды (получен от клиента).
    
    Возвращает код завершения и сигнал (по ACP spec).
    """

    model_config = ConfigDict(populate_by_name=True)

    exit_code: int | None = Field(None, alias="exitCode")
    """Код завершения команды (может быть None если завершён сигналом)."""

    signal: str | None = Field(None, alias="signal")
    """Сигнал, завершивший процесс (может быть None если завершился нормально)."""


class TerminalKillRequest(BaseModel):
    """Запрос на прерывание команды в терминале.
    
    Используется для отправки сигнала завершения команде в терминале.
    """

    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(..., alias="sessionId")
    """ID сессии."""

    terminal_id: str = Field(..., alias="terminalId")
    """ID терминального сеанса."""

    signal: str = "SIGTERM"
    """Сигнал для отправки (по умолчанию SIGTERM)."""


class TerminalKillResponse(BaseModel):
    """Подтверждение прерывания команды (получено от клиента).
    
    Согласно ACP spec, response не содержит полей кроме опционального _meta.
    Наличие ответа (без ошибки) означает успешную отправку сигнала.
    """

    model_config = ConfigDict(extra="allow")


class TerminalReleaseRequest(BaseModel):
    """Запрос на освобождение ресурсов терминала.
    
    Используется для закрытия терминального сеанса и освобождения ресурсов.
    """

    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(..., alias="sessionId")
    """ID сессии."""

    terminal_id: str = Field(..., alias="terminalId")
    """ID терминального сеанса."""


class TerminalReleaseResponse(BaseModel):
    """Подтверждение освобождения ресурсов (получено от клиента).
    
    Согласно ACP spec, response не содержит полей кроме опционального _meta.
    Наличие ответа (без ошибки) означает успешное освобождение ресурсов.
    """

    model_config = ConfigDict(extra="allow")
