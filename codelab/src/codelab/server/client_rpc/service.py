"""ClientRPCService для вызова методов на клиенте.

Предоставляет асинхронный сервис для инициирования RPC вызовов на клиентской стороне.
Агент использует этот сервис для доступа к локальной среде клиента:
- Чтение/запись файлов
- Выполнение терминальных команд
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Callable
from typing import Any

import structlog
from pydantic import BaseModel

from ..messages import JsonRpcId
from .exceptions import (
    ClientCapabilityMissingError,
    ClientRPCCancelledError,
    ClientRPCError,
    ClientRPCResponseError,
)
from .models import (
    PendingRequest,
    ReadTextFileRequest,
    ReadTextFileResponse,
    TerminalCreateRequest,
    TerminalCreateResponse,
    TerminalKillRequest,
    TerminalKillResponse,
    TerminalOutputRequest,
    TerminalOutputResponse,
    TerminalReleaseRequest,
    TerminalReleaseResponse,
    TerminalWaitForExitRequest,
    TerminalWaitForExitResponse,
    WriteTextFileRequest,
    WriteTextFileResponse,
)

logger = structlog.get_logger()


class ClientRPCService:
    """Сервис для вызова методов на клиенте (Agent → Client RPC).

    Агент использует этот сервис для доступа к локальной среде клиента:
    - Чтение/запись файлов
    - Выполнение терминальных команд

    Attributes:
        _send_request: Функция для отправки JSON-RPC request
        _capabilities: Capabilities из initialize response
        _pending_requests: Словарь активных requests (request_id -> PendingRequest)
    """

    def __init__(
        self,
        send_request_callback: Callable,
        client_capabilities: dict,
        timeout: float | None = None,  # Deprecated: игнорируется
    ) -> None:
        """Инициализировать ClientRPCService.

        Args:
            send_request_callback: Функция для отправки JSON-RPC request.
                Ожидается сигнатура: async def send(request: dict) -> None
            client_capabilities: Capabilities из initialize response.
                Словарь вида {"fs": {"readTextFile": True}, "terminal": True}
            timeout: DEPRECATED. Параметр игнорируется - RPC теперь ожидают бессрочно.
        """
        self._send_request = send_request_callback
        self._capabilities = client_capabilities
        # Храним PendingRequest вместо Future для поддержки отмены
        self._pending_requests: dict[str, PendingRequest] = {}

    def _check_capability(self, capability_path: str) -> None:
        """Проверить наличие capability у клиента.

        Args:
            capability_path: Путь к capability (например, "fs.readTextFile").

        Raises:
            ClientCapabilityMissingError: Если capability отсутствует.
        """
        parts = capability_path.split(".")
        current: Any = self._capabilities

        for part in parts:
            if not isinstance(current, dict) or part not in current:
                raise ClientCapabilityMissingError(
                    f"Клиент не поддерживает capability: {capability_path}"
                )
            current = current[part]

        if not current:
            raise ClientCapabilityMissingError(f"Capability {capability_path} отключена")

    async def _call_method(
        self,
        method: str,
        params: dict,
        response_model: type[BaseModel],
    ) -> Any:
        """Вызвать метод на клиенте и дождаться ответа без timeout.

        Метод ожидает ответ бессрочно до одного из событий:
        - Получен ответ от клиента (успешный или с ошибкой)
        - Запрос отменён через cancellation_event

        Args:
            method: Имя метода (например, "fs/read_text_file").
            params: Параметры запроса в виде словаря.
            response_model: Pydantic модель для парсинга ответа.

        Returns:
            Распарсенный response согласно response_model.

        Raises:
            ClientRPCCancelledError: Запрос был отменён.
            ClientRPCResponseError: Ошибка от клиента.
            ClientRPCError: Некорректный ответ от клиента.
        """
        request_id = str(uuid.uuid4())
        
        # Создаём PendingRequest с cancellation_event для координированной отмены
        pending_request = PendingRequest(
            future=asyncio.Future(),
            cancellation_event=asyncio.Event(),
            method=method,
        )
        self._pending_requests[request_id] = pending_request

        try:
            # Отправить JSON-RPC request
            await self._send_request(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                }
            )

            logger.debug(
                "Отправлен RPC запрос на клиент",
                extra={"method": method, "request_id": request_id},
            )

            # Ждём одно из двух событий: ответ или отмена (без timeout)
            future_task = asyncio.create_task(
                self._wrap_future(pending_request.future),
                name=f"rpc-future-{request_id}",
            )
            cancel_task = asyncio.create_task(
                pending_request.cancellation_event.wait(),
                name=f"rpc-cancel-{request_id}",
            )

            done, pending = await asyncio.wait(
                [future_task, cancel_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Отменяем оставшуюся задачу
            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

            # Проверяем, был ли запрос отменён
            if pending_request.cancellation_event.is_set():
                raise ClientRPCCancelledError(f"RPC вызов {method} был отменён")

            # Если Future завершился с исключением - пробрасываем его
            if pending_request.future.done():
                # Получаем исключение или результат
                exc = pending_request.future.exception()
                if exc:
                    raise exc
                result = pending_request.future.result()
            else:
                # Future должен быть done, если мы здесь
                raise ClientRPCError(f"Unexpected state: future not done for {method}")

            # Парсить ответ
            return response_model.model_validate(result)

        finally:
            self._pending_requests.pop(request_id, None)

    async def _wrap_future(self, future: asyncio.Future) -> Any:
        """Обёртка для ожидания Future как корутины.
        
        Args:
            future: Future для ожидания.
            
        Returns:
            Результат Future.
        """
        return await future

    def handle_response(self, response: dict) -> None:
        """Обработать ответ от клиента.

        Вызывается transport layer при получении JSON-RPC response.

        Args:
            response: JSON-RPC response от клиента вида:
                {"jsonrpc": "2.0", "id": "...", "result": {...}} или
                {"jsonrpc": "2.0", "id": "...", "error": {"code": -32001, ...}}
        """
        request_id = response.get("id")
        if not request_id or request_id not in self._pending_requests:
            logger.warning(
                "Получен ответ для неизвестного request_id",
                extra={"request_id": request_id},
            )
            return

        pending_request = self._pending_requests[request_id]

        if "error" in response:
            error = response["error"]
            pending_request.future.set_exception(
                ClientRPCResponseError(
                    code=error.get("code", -1),
                    message=error.get("message", "Unknown error"),
                    data=error.get("data"),
                )
            )
        elif "result" in response:
            pending_request.future.set_result(response["result"])
            logger.debug(
                "RPC ответ получен от клиента",
                extra={
                    "request_id": request_id,
                    "method": pending_request.method,
                },
            )
        else:
            pending_request.future.set_exception(
                ClientRPCError("Invalid response: missing 'result' or 'error'")
            )

    def has_pending_request(self, request_id: JsonRpcId | None) -> bool:
        """Проверить, ожидает ли сервис ответ для указанного request_id.

        Пример использования:
            if service.has_pending_request("req_1"):
                ...
        """
        if not isinstance(request_id, str):
            return False
        
        is_pending = request_id in self._pending_requests
        if is_pending:
            logger.debug(
                "RPC request найден в pending",
                extra={"request_id": request_id},
            )
        return is_pending

    def cancel_request(self, request_id: str) -> bool:
        """Отменить конкретный RPC запрос по его ID.

        Устанавливает cancellation_event, что приводит к немедленному
        завершению ожидания в _call_method с ClientRPCCancelledError.

        Args:
            request_id: ID запроса для отмены.

        Returns:
            True если запрос был найден и отменён, False если не найден.
        """
        if request_id not in self._pending_requests:
            return False
        
        pending_request = self._pending_requests[request_id]
        pending_request.cancellation_event.set()
        
        logger.debug(
            "RPC запрос отменён",
            extra={"request_id": request_id, "method": pending_request.method},
        )
        return True

    def cancel_all_pending_requests(self, reason: str | None = None) -> int:
        """Отменить все ожидающие RPC-запросы.

        Метод используется при session/cancel или disconnect, чтобы
        немедленно завершить все ожидающие RPC вызовы.

        Args:
            reason: Текст причины отмены (для логирования).

        Returns:
            Количество отменённых запросов.
        """
        cancelled_count = 0
        for _request_id, pending_request in list(self._pending_requests.items()):
            # Пропускаем уже завершённые
            if pending_request.future.done():
                continue
            
            # Устанавливаем event отмены - _call_method обработает и выбросит исключение
            pending_request.cancellation_event.set()
            cancelled_count += 1

        if cancelled_count > 0:
            logger.info(
                "pending client RPC requests cancelled",
                cancelled_count=cancelled_count,
                reason=reason or "no reason provided",
            )
        return cancelled_count

    # ===== File System методы =====

    async def read_text_file(
        self,
        session_id: str,
        path: str,
        line: int | None = None,
        limit: int | None = None,
    ) -> str:
        """Прочитать текстовый файл в окружении клиента.

        Args:
            session_id: ID сессии.
            path: Путь к файлу.
            line: Начальная строка (0-based, опционально).
            limit: Максимум строк (опционально).

        Returns:
            Содержимое файла.

        Raises:
            ClientCapabilityMissingError: Клиент не поддерживает fs.readTextFile.
            ClientRPCTimeoutError: Timeout.
            ClientRPCResponseError: Ошибка от клиента.
        """
        self._check_capability("fs.readTextFile")

        request = ReadTextFileRequest(
            sessionId=session_id, path=path, line=line, limit=limit
        )

        response = await self._call_method(
            method="fs/read_text_file",
            params=request.model_dump(by_alias=True, exclude_none=True),
            response_model=ReadTextFileResponse,
        )

        return response.content

    async def write_text_file(
        self,
        session_id: str,
        path: str,
        content: str,
    ) -> bool:
        """Записать текстовый файл в окружении клиента.

        Args:
            session_id: ID сессии.
            path: Путь к файлу.
            content: Содержимое для записи.

        Returns:
            True при успехе.

        Raises:
            ClientCapabilityMissingError: Клиент не поддерживает fs.writeTextFile.
            ClientRPCTimeoutError: Timeout.
            ClientRPCResponseError: Ошибка от клиента (включая отказ в разрешении).
        """
        self._check_capability("fs.writeTextFile")

        request = WriteTextFileRequest(
            sessionId=session_id, path=path, content=content
        )

        await self._call_method(
            method="fs/write_text_file",
            params=request.model_dump(by_alias=True),
            response_model=WriteTextFileResponse,
        )

        # ACP spec: наличие response (без ошибки) означает успех
        return True

    # ===== Terminal методы =====

    async def create_terminal(
        self,
        session_id: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        output_byte_limit: int | None = None,
    ) -> str:
        """Создать терминал и запустить команду в окружении клиента.

        Args:
            session_id: ID сессии.
            command: Команда для выполнения.
            args: Аргументы команды (опционально).
            env: Переменные окружения (опционально).
            cwd: Рабочая директория (опционально).
            output_byte_limit: Лимит байт output (опционально).

        Returns:
            Terminal ID для дальнейшего использования.

        Raises:
            ClientCapabilityMissingError: Клиент не поддерживает terminal.
            ClientRPCTimeoutError: Timeout.
            ClientRPCResponseError: Ошибка от клиента.
        """
        self._check_capability("terminal")

        request = TerminalCreateRequest(
            sessionId=session_id,
            command=command,
            args=args,
            env=env,
            cwd=cwd,
            outputByteLimit=output_byte_limit,
        )

        response = await self._call_method(
            method="terminal/create",
            params=request.model_dump(by_alias=True, exclude_none=True),
            response_model=TerminalCreateResponse,
        )

        return response.terminal_id

    async def terminal_output(
        self,
        session_id: str,
        terminal_id: str,
    ) -> tuple[str, bool, int | None, str | None]:
        """Получить текущий output терминала.

        Args:
            session_id: ID сессии.
            terminal_id: ID терминального сеанса.

        Returns:
            Кортеж (output, truncated, exit_code, signal).
            truncated True если output был обрезан.
            exit_code и signal из exitStatus (если команда завершилась).

        Raises:
            ClientCapabilityMissingError: Клиент не поддерживает terminal.
            ClientRPCTimeoutError: Timeout.
            ClientRPCResponseError: Ошибка от клиента.
        """
        self._check_capability("terminal")

        request = TerminalOutputRequest(
            sessionId=session_id, terminalId=terminal_id
        )

        response = await self._call_method(
            method="terminal/output",
            params=request.model_dump(by_alias=True),
            response_model=TerminalOutputResponse,
        )

        exit_code = response.exit_status.exit_code if response.exit_status else None
        signal = response.exit_status.signal if response.exit_status else None
        return response.output, response.truncated, exit_code, signal

    async def wait_for_exit(
        self,
        session_id: str,
        terminal_id: str,
        timeout: float | None = None,
    ) -> tuple[int | None, str | None]:
        """Блокирующее ожидание завершения команды в терминале.

        Args:
            session_id: ID сессии.
            terminal_id: ID терминального сеанса.
            timeout: Timeout ожидания в секундах (опционально).

        Returns:
            Кортеж (exit_code, signal) по ACP spec.

        Raises:
            ClientCapabilityMissingError: Клиент не поддерживает terminal.
            ClientRPCTimeoutError: Timeout.
            ClientRPCResponseError: Ошибка от клиента.
        """
        self._check_capability("terminal")

        request = TerminalWaitForExitRequest(
            sessionId=session_id, terminalId=terminal_id, timeout=timeout
        )

        response = await self._call_method(
            method="terminal/wait_for_exit",
            params=request.model_dump(by_alias=True, exclude_none=True),
            response_model=TerminalWaitForExitResponse,
        )

        return response.exit_code, response.signal

    async def kill_terminal(
        self,
        session_id: str,
        terminal_id: str,
        signal: str = "SIGTERM",
    ) -> bool:
        """Прервать команду в терминале.

        Args:
            session_id: ID сессии.
            terminal_id: ID терминального сеанса.
            signal: Сигнал для отправки (по умолчанию SIGTERM).

        Returns:
            True если сигнал успешно отправлен.

        Raises:
            ClientCapabilityMissingError: Клиент не поддерживает terminal.
            ClientRPCTimeoutError: Timeout.
            ClientRPCResponseError: Ошибка от клиента.
        """
        self._check_capability("terminal")

        request = TerminalKillRequest(
            sessionId=session_id, terminalId=terminal_id, signal=signal
        )

        await self._call_method(
            method="terminal/kill",
            params=request.model_dump(by_alias=True),
            response_model=TerminalKillResponse,
        )

        # ACP spec: наличие response (без ошибки) означает успех
        return True

    async def release_terminal(
        self,
        session_id: str,
        terminal_id: str,
    ) -> bool:
        """Освободить ресурсы терминала.

        Args:
            session_id: ID сессии.
            terminal_id: ID терминального сеанса.

        Returns:
            True если ресурсы успешно освобождены.

        Raises:
            ClientCapabilityMissingError: Клиент не поддерживает terminal.
            ClientRPCTimeoutError: Timeout.
            ClientRPCResponseError: Ошибка от клиента.
        """
        self._check_capability("terminal")

        request = TerminalReleaseRequest(
            sessionId=session_id, terminalId=terminal_id
        )

        await self._call_method(
            method="terminal/release",
            params=request.model_dump(by_alias=True),
            response_model=TerminalReleaseResponse,
        )

        # ACP spec: наличие response (без ошибки) означает успех
        return True
