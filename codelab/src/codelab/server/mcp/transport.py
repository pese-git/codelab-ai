"""Транспорты для MCP (Model Context Protocol).

Реализует асинхронную коммуникацию с MCP серверами через различные транспорты:
- StdioTransport: stdin/stdout subprocess
- HttpTransport: HTTP POST запросы с JSON-RPC
- SseTransport: Server-Sent Events (deprecated)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from typing import Any

import aiohttp

from .models import MCPNotification, MCPRequest, MCPResponse

logger = logging.getLogger(__name__)


class StdioTransportError(Exception):
    """Базовое исключение для ошибок транспорта."""
    pass


class ProcessNotStartedError(StdioTransportError):
    """Процесс MCP сервера не запущен."""
    pass


class ProcessExitedError(StdioTransportError):
    """Процесс MCP сервера неожиданно завершился."""
    
    def __init__(self, message: str, return_code: int | None = None):
        super().__init__(message)
        self.return_code = return_code


class StdioTransport:
    """Асинхронный stdio транспорт для коммуникации с MCP сервером.
    
    Запускает MCP сервер как subprocess и обеспечивает асинхронный обмен
    JSON-RPC 2.0 сообщениями через stdin/stdout. Stderr используется для логов.
    
    Attributes:
        command: Команда для запуска MCP сервера.
        args: Аргументы командной строки.
        env: Переменные окружения для процесса.
    
    Example:
        >>> transport = StdioTransport()
        >>> await transport.start("mcp-server", ["--stdio"])
        >>> response = await transport.send_request("initialize", {...})
        >>> await transport.close()
    """
    
    def __init__(self) -> None:
        """Инициализация транспорта."""
        self._process: asyncio.subprocess.Process | None = None
        self._request_id: int = 0
        self._pending_requests: dict[int | str, asyncio.Future[MCPResponse]] = {}
        self._read_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._closed: bool = False
        self._lock: asyncio.Lock = asyncio.Lock()
    
    @property
    def is_running(self) -> bool:
        """Проверить, запущен ли процесс MCP сервера."""
        return (
            self._process is not None 
            and self._process.returncode is None
            and not self._closed
        )
    
    async def start(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> None:
        """Запустить MCP сервер как subprocess.
        
        Args:
            command: Команда для запуска (путь к исполняемому файлу).
            args: Аргументы командной строки.
            env: Дополнительные переменные окружения.
            cwd: Рабочая директория для процесса.
        
        Raises:
            StdioTransportError: Если не удалось запустить процесс.
        """
        if self._process is not None:
            raise StdioTransportError("Transport already started")
        
        args = args or []
        
        # Формируем окружение: берём текущее и добавляем пользовательское
        import os
        process_env = os.environ.copy()
        if env:
            process_env.update(env)
        
        logger.debug(
            "Starting MCP server: %s %s (cwd=%s)",
            command, " ".join(args), cwd
        )
        
        try:
            self._process = await asyncio.create_subprocess_exec(
                command,
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=process_env,
                cwd=cwd,
            )
        except FileNotFoundError as e:
            raise StdioTransportError(f"MCP server not found: {command}") from e
        except OSError as e:
            raise StdioTransportError(f"Failed to start MCP server: {e}") from e
        
        # Запускаем фоновые задачи чтения
        self._read_task = asyncio.create_task(
            self._read_stdout_loop(),
            name="mcp_stdout_reader"
        )
        self._stderr_task = asyncio.create_task(
            self._read_stderr_loop(),
            name="mcp_stderr_reader"
        )
        
        logger.info("MCP server started (pid=%d)", self._process.pid)
    
    async def send_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Отправить JSON-RPC запрос и дождаться ответа.
        
        Args:
            method: Имя вызываемого метода.
            params: Параметры запроса.
            timeout: Таймаут ожидания ответа в секундах.
        
        Returns:
            Результат из ответа (поле result).
        
        Raises:
            ProcessNotStartedError: Если процесс не запущен.
            ProcessExitedError: Если процесс завершился.
            asyncio.TimeoutError: Если истёк таймаут.
            StdioTransportError: При ошибке в ответе.
        """
        if not self.is_running:
            raise ProcessNotStartedError("MCP server process not running")
        
        # Генерируем уникальный ID запроса
        async with self._lock:
            self._request_id += 1
            request_id = self._request_id
        
        # Создаём запрос
        request = MCPRequest(
            id=request_id,
            method=method,
            params=params
        )
        
        # Создаём Future для ожидания ответа
        loop = asyncio.get_running_loop()
        future: asyncio.Future[MCPResponse] = loop.create_future()
        self._pending_requests[request_id] = future
        
        try:
            # Отправляем запрос
            await self._write_message(request.model_dump(by_alias=True, exclude_none=True))
            
            logger.debug("Sent MCP request: method=%s id=%d", method, request_id)
            
            # Ожидаем ответ с таймаутом
            response = await asyncio.wait_for(future, timeout=timeout)
            
            # Проверяем на ошибку
            if response.error:
                raise StdioTransportError(
                    f"MCP error {response.error.code}: {response.error.message}"
                )
            
            return response.result or {}
            
        finally:
            # Удаляем из ожидающих
            self._pending_requests.pop(request_id, None)
    
    async def send_notification(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Отправить JSON-RPC нотификацию без ожидания ответа.
        
        Args:
            method: Имя метода нотификации.
            params: Параметры нотификации.
        
        Raises:
            ProcessNotStartedError: Если процесс не запущен.
        """
        if not self.is_running:
            raise ProcessNotStartedError("MCP server process not running")
        
        notification = MCPNotification(method=method, params=params)
        await self._write_message(
            notification.model_dump(by_alias=True, exclude_none=True)
        )
        
        logger.debug("Sent MCP notification: method=%s", method)
    
    async def close(self) -> None:
        """Закрыть соединение и завершить процесс MCP сервера.
        
        Выполняет graceful shutdown: сначала закрывает stdin,
        ждёт завершения процесса, при необходимости принудительно завершает.
        """
        if self._closed:
            return
        
        self._closed = True
        
        logger.debug("Closing MCP transport")
        
        # Отменяем все ожидающие запросы
        for _request_id, future in self._pending_requests.items():
            if not future.done():
                future.cancel()
        self._pending_requests.clear()
        
        # Останавливаем задачи чтения
        if self._read_task:
            self._read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._read_task
        
        if self._stderr_task:
            self._stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stderr_task
        
        # Закрываем процесс
        if self._process:
            # Закрываем stdin для сигнала о завершении
            if self._process.stdin:
                self._process.stdin.close()
                with contextlib.suppress(Exception):
                    await self._process.stdin.wait_closed()
            
            # Ждём завершения процесса (с таймаутом)
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
                logger.info(
                    "MCP server exited (code=%s)",
                    self._process.returncode
                )
            except TimeoutError:
                # Принудительное завершение
                logger.warning("MCP server did not exit, terminating")
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=2.0)
                except TimeoutError:
                    logger.warning("MCP server did not terminate, killing")
                    self._process.kill()
                    await self._process.wait()
        
        self._process = None
        logger.debug("MCP transport closed")
    
    async def _write_message(self, message: dict[str, Any]) -> None:
        """Записать JSON-RPC сообщение в stdin процесса.
        
        Args:
            message: Сообщение для отправки.
        
        Raises:
            ProcessExitedError: Если процесс завершился.
        """
        if not self._process or not self._process.stdin:
            raise ProcessNotStartedError("No stdin available")
        
        # Сериализуем в JSON + newline
        data = json.dumps(message) + "\n"
        
        try:
            self._process.stdin.write(data.encode("utf-8"))
            await self._process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as e:
            raise ProcessExitedError(
                f"MCP server pipe broken: {e}",
                self._process.returncode
            ) from e
    
    async def _read_stdout_loop(self) -> None:
        """Фоновая задача чтения ответов из stdout.
        
        Читает JSON-RPC сообщения построчно и диспетчеризирует их
        к соответствующим ожидающим Future.
        """
        if not self._process or not self._process.stdout:
            return
        
        try:
            while not self._closed:
                # Читаем строку (JSON-RPC сообщение)
                line = await self._process.stdout.readline()
                
                if not line:
                    # EOF - процесс завершился
                    logger.debug("MCP stdout EOF")
                    break
                
                # Декодируем и парсим JSON
                try:
                    data = json.loads(line.decode("utf-8").strip())
                except json.JSONDecodeError as e:
                    logger.warning("Invalid JSON from MCP server: %s", e)
                    continue
                
                # Обрабатываем сообщение
                await self._handle_message(data)
                
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Error reading MCP stdout: %s", e)
            # Отменяем все ожидающие запросы при ошибке
            for future in self._pending_requests.values():
                if not future.done():
                    future.set_exception(
                        ProcessExitedError(f"Read error: {e}")
                    )
    
    async def _read_stderr_loop(self) -> None:
        """Фоновая задача чтения логов из stderr.
        
        Выводит stderr MCP сервера в лог для отладки.
        """
        if not self._process or not self._process.stderr:
            return
        
        try:
            while not self._closed:
                line = await self._process.stderr.readline()
                
                if not line:
                    break
                
                # Логируем stderr как отладочную информацию
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    logger.debug("MCP stderr: %s", text)
                    
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Error reading MCP stderr: %s", e)
    
    async def _handle_message(self, data: dict[str, Any]) -> None:
        """Обработать входящее JSON-RPC сообщение.
        
        Args:
            data: Распарсенное JSON сообщение.
        """
        # Проверяем, есть ли id (это ответ на запрос)
        message_id = data.get("id")
        
        if message_id is not None:
            # Это ответ - ищем ожидающий Future
            future = self._pending_requests.get(message_id)
            
            if future and not future.done():
                # Парсим как MCPResponse
                try:
                    response = MCPResponse.model_validate(data)
                    future.set_result(response)
                except Exception as e:
                    future.set_exception(
                        StdioTransportError(f"Invalid response: {e}")
                    )
            else:
                logger.warning(
                    "Received response for unknown request id=%s",
                    message_id
                )
        else:
            # Это нотификация от сервера
            method = data.get("method", "unknown")
            logger.debug(
                "Received MCP notification: method=%s",
                method
            )
            # Нотификации пока игнорируем, но можно добавить обработку


# ===== HTTP Transport =====


class HttpTransportError(StdioTransportError):
    """Базовое исключение для ошибок HTTP транспорта."""
    pass


class HttpConnectionError(HttpTransportError):
    """Ошибка подключения к HTTP серверу."""
    pass


class HttpTimeoutError(HttpTransportError):
    """Таймаут HTTP запроса."""
    pass


class HttpTransport:
    """HTTP транспорт для коммуникации с MCP серверами.
    
    Использует HTTP POST запросы для отправки JSON-RPC сообщений
    к MCP серверу через HTTP endpoint.
    
    Attributes:
        url: URL MCP сервера.
        headers: HTTP headers для запросов.
        timeout: Таймаут запросов в секундах.
    
    Example:
        >>> config = HttpTransportConfig(url="http://localhost:8080")
        >>> transport = HttpTransport(config)
        >>> await transport.connect()
        >>> response = await transport.send_request("initialize", {...})
        >>> await transport.disconnect()
    """
    
    def __init__(
        self,
        url: str,
        headers: list[dict[str, str]] | None = None,
        timeout: float = 30.0,
    ) -> None:
        """Инициализация HTTP транспорта.
        
        Args:
            url: URL MCP сервера.
            headers: Список HTTP headers [{name: value}].
            timeout: Таймаут запросов в секундах.
        """
        self._url = url
        self._headers = self._build_headers(headers)
        self._timeout = timeout
        self._session: aiohttp.ClientSession | None = None
        self._request_id: int = 0
        self._pending_requests: dict[int | str, asyncio.Future[MCPResponse]] = {}
        self._closed: bool = False
        self._lock: asyncio.Lock = asyncio.Lock()
        self._notification_handlers: list[Callable] = []
    
    @staticmethod
    def _build_headers(headers: list[dict[str, str]] | None) -> dict[str, str]:
        """Преобразовать список headers в словарь.
        
        Args:
            headers: Список [{name: value}] или None.
        
        Returns:
            Словарь HTTP headers.
        """
        if not headers:
            return {}
        
        result = {}
        for item in headers:
            if "name" in item and "value" in item:
                result[item["name"]] = item["value"]
            else:
                result.update(item)
        return result
    
    @property
    def is_connected(self) -> bool:
        """Проверить, установлено ли соединение."""
        return (
            self._session is not None 
            and not self._session.closed
            and not self._closed
        )
    
    async def connect(self) -> None:
        """Установить HTTP соединение с MCP сервером.
        
        Создаёт aiohttp.ClientSession с настроенными headers.
        
        Raises:
            HttpConnectionError: Если не удалось подключиться.
        """
        if self._session is not None:
            raise HttpTransportError("Transport already connected")
        
        logger.debug("Connecting to MCP HTTP server: %s", self._url)
        
        try:
            timeout = aiohttp.ClientTimeout(total=self._timeout)
            self._session = aiohttp.ClientSession(
                headers=self._headers,
                timeout=timeout,
            )
            
            # Проверяем соединение, отправляя простой запрос
            async with self._session.head(self._url) as response:
                if response.status >= 400:
                    logger.warning(
                        "MCP HTTP server returned status %d on connect",
                        response.status
                    )
            
            logger.info("Connected to MCP HTTP server: %s", self._url)
            
        except aiohttp.ClientError as e:
            self._session = None
            raise HttpConnectionError(
                f"Failed to connect to MCP HTTP server: {e}"
            ) from e
    
    async def send_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Отправить JSON-RPC запрос и дождаться ответа.
        
        Args:
            method: Имя вызываемого метода.
            params: Параметры запроса.
            timeout: Таймаут ожидания ответа в секундах.
        
        Returns:
            Результат из ответа (поле result).
        
        Raises:
            HttpConnectionError: Если соединение не установлено.
            HttpTimeoutError: Если истёк таймаут.
            HttpTransportError: При ошибке в ответе.
        """
        if not self.is_connected:
            raise HttpConnectionError("Not connected to MCP server")
        
        if not self._session:
            raise HttpConnectionError("Session not initialized")
        
        # Генерируем уникальный ID запроса
        async with self._lock:
            self._request_id += 1
            request_id = self._request_id
        
        # Создаём запрос
        request = MCPRequest(
            id=request_id,
            method=method,
            params=params
        )
        
        # Создаём Future для ожидания ответа
        loop = asyncio.get_running_loop()
        future: asyncio.Future[MCPResponse] = loop.create_future()
        self._pending_requests[request_id] = future
        
        request_timeout = timeout or self._timeout
        
        try:
            # Отправляем HTTP POST запрос
            async with self._session.post(
                self._url,
                json=request.model_dump(by_alias=True, exclude_none=True),
                headers=self._headers,
            ) as response:
                logger.debug(
                    "HTTP response status: %d for method=%s id=%d",
                    response.status, method, request_id
                )
                
                if response.status == 408 or response.status == 504:
                    raise HttpTimeoutError(
                        f"HTTP timeout: status {response.status}"
                    )
                
                if response.status >= 500:
                    raise HttpTransportError(
                        f"HTTP server error: status {response.status}"
                    )
                
                if response.status >= 400:
                    raise HttpTransportError(
                        f"HTTP client error: status {response.status}"
                    )
                
                # Парсим JSON ответ
                try:
                    data = await response.json()
                except json.JSONDecodeError as e:
                    raise HttpTransportError(
                        f"Invalid JSON response: {e}"
                    ) from e
                
                # Обрабатываем ответ
                await self._handle_response(data)
            
            # Ожидаем ответ с таймаутом
            try:
                mcp_response = await asyncio.wait_for(future, timeout=request_timeout)
            except TimeoutError:
                raise HttpTimeoutError(
                    f"Request timeout after {request_timeout}s: method={method}"
                ) from None
            
            # Проверяем на ошибку
            if mcp_response.error:
                raise HttpTransportError(
                    f"MCP error {mcp_response.error.code}: {mcp_response.error.message}"
                )
            
            return mcp_response.result or {}
            
        finally:
            # Удаляем из ожидающих
            self._pending_requests.pop(request_id, None)
    
    async def send_notification(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Отправить JSON-RPC нотификацию без ожидания ответа.
        
        Args:
            method: Имя метода нотификации.
            params: Параметры нотификации.
        
        Raises:
            HttpConnectionError: Если соединение не установлено.
        """
        if not self.is_connected:
            raise HttpConnectionError("Not connected to MCP server")
        
        if not self._session:
            raise HttpConnectionError("Session not initialized")
        
        notification = MCPNotification(method=method, params=params)
        
        try:
            async with self._session.post(
                self._url,
                json=notification.model_dump(by_alias=True, exclude_none=True),
                headers=self._headers,
            ) as response:
                logger.debug(
                    "Sent HTTP notification: method=%s status=%d",
                    method, response.status
                )
        except aiohttp.ClientError as e:
            raise HttpTransportError(
                f"Failed to send notification: {e}"
            ) from e
    
    async def disconnect(self) -> None:
        """Закрыть HTTP соединение.
        
        Отменяет все ожидающие запросы и закрывает aiohttp session.
        """
        if self._closed:
            return
        
        self._closed = True
        
        logger.debug("Closing HTTP MCP transport")
        
        # Отменяем все ожидающие запросы
        for _request_id, future in self._pending_requests.items():
            if not future.done():
                future.set_exception(
                    HttpTransportError("Transport closed")
                )
        self._pending_requests.clear()
        
        # Закрываем session
        if self._session and not self._session.closed:
            await self._session.close()
        
        self._session = None
        logger.debug("HTTP MCP transport closed")
    
    async def _handle_response(self, data: dict[str, Any]) -> None:
        """Обработать входящее JSON-RPC сообщение.
        
        Args:
            data: Распарсенное JSON сообщение.
        """
        message_id = data.get("id")
        
        if message_id is not None:
            # Это ответ на запрос
            future = self._pending_requests.get(message_id)
            
            if future and not future.done():
                try:
                    response = MCPResponse.model_validate(data)
                    future.set_result(response)
                except Exception as e:
                    future.set_exception(
                        HttpTransportError(f"Invalid response: {e}")
                    )
            else:
                logger.warning(
                    "Received response for unknown request id=%s",
                    message_id
                )
        else:
            # Это нотификация
            method = data.get("method", "unknown")
            logger.debug(
                "Received MCP notification: method=%s",
                method
            )
            # Вызываем обработчики notifications
            for handler in self._notification_handlers:
                try:
                    handler(data)
                except Exception as e:
                    logger.error(
                        "Error in notification handler: %s", e
                    )
    
    def register_notification_handler(self, handler: Callable) -> None:
        """Зарегистрировать обработчик notifications.
        
        Args:
            handler: Функция для обработки notification.
        """
        self._notification_handlers.append(handler)


# ===== SSE Transport =====


class SseTransportError(StdioTransportError):
    """Базовое исключение для ошибок SSE транспорта."""
    pass


class SseTransport:
    """SSE (Server-Sent Events) транспорт для MCP серверов.
    
    Поддерживает SSE connection для получения событий от MCP сервера.
    Данный транспорт deprecated в MCP spec и поддерживается только
    для обратной совместимости.
    
    Attributes:
        url: URL SSE endpoint MCP сервера.
        headers: HTTP headers для запросов.
        timeout: Таймаут запросов в секундах.
    
    Example:
        >>> config = SseTransportConfig(url="http://localhost:8080/sse")
        >>> transport = SseTransport(config)
        >>> await transport.connect()
        >>> response = await transport.send_request("initialize", {...})
        >>> await transport.disconnect()
    """
    
    def __init__(
        self,
        url: str,
        headers: list[dict[str, str]] | None = None,
        timeout: float = 30.0,
    ) -> None:
        """Инициализация SSE транспорта.
        
        Args:
            url: URL SSE endpoint.
            headers: Список HTTP headers [{name: value}].
            timeout: Таймаут запросов в секундах.
        """
        self._url = url
        self._headers = HttpTransport._build_headers(headers)
        self._timeout = timeout
        self._session: aiohttp.ClientSession | None = None
        self._sse_response: aiohttp.ClientResponse | None = None
        self._request_id: int = 0
        self._pending_requests: dict[int | str, asyncio.Future[MCPResponse]] = {}
        self._closed: bool = False
        self._lock: asyncio.Lock = asyncio.Lock()
        self._notification_queue: asyncio.Queue = asyncio.Queue()
        self._notification_handlers: dict[str, list[Callable]] = {}
        self._read_task: asyncio.Task[None] | None = None
        
        # Логируем warning о deprecated статусе
        logger.warning(
            "SSE transport is deprecated in MCP spec. "
            "Consider using HTTP transport instead."
        )
    
    @property
    def is_connected(self) -> bool:
        """Проверить, установлено ли соединение."""
        return (
            self._session is not None
            and not self._session.closed
            and self._sse_response is not None
            and not self._closed
        )
    
    async def connect(self) -> None:
        """Установить SSE соединение с MCP сервером.
        
        Создаёт SSE connection и запускает фоновую задачу чтения событий.
        
        Raises:
            SseTransportError: Если не удалось подключиться.
        """
        if self._session is not None:
            raise SseTransportError("Transport already connected")
        
        logger.debug("Connecting to MCP SSE server: %s", self._url)
        
        try:
            timeout = aiohttp.ClientTimeout(total=self._timeout)
            self._session = aiohttp.ClientSession(
                headers=self._headers,
                timeout=timeout,
            )
            
            # Устанавливаем SSE соединение
            self._sse_response = await self._session.get(
                self._url,
                headers={
                    **self._headers,
                    "Accept": "text/event-stream",
                }
            )
            
            # Запускаем фоновую задачу чтения SSE событий
            self._read_task = asyncio.create_task(
                self._read_sse_loop(),
                name="mcp_sse_reader"
            )
            
            logger.info("Connected to MCP SSE server: %s", self._url)
            
        except aiohttp.ClientError as e:
            self._session = None
            raise SseTransportError(
                f"Failed to connect to MCP SSE server: {e}"
            ) from e
    
    async def send_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Отправить JSON-RPC запрос и дождаться ответа.
        
        Для SSE транспорта запросы отправляются через HTTP POST,
        а ответы приходят через SSE events.
        
        Args:
            method: Имя вызываемого метода.
            params: Параметры запроса.
            timeout: Таймаут ожидания ответа в секундах.
        
        Returns:
            Результат из ответа (поле result).
        
        Raises:
            SseTransportError: Если соединение не установлено.
        """
        if not self.is_connected:
            raise SseTransportError("Not connected to MCP server")
        
        if not self._session:
            raise SseTransportError("Session not initialized")
        
        # Генерируем уникальный ID запроса
        async with self._lock:
            self._request_id += 1
            request_id = self._request_id
        
        # Создаём запрос
        request = MCPRequest(
            id=request_id,
            method=method,
            params=params
        )
        
        # Создаём Future для ожидания ответа
        loop = asyncio.get_running_loop()
        future: asyncio.Future[MCPResponse] = loop.create_future()
        self._pending_requests[request_id] = future
        
        request_timeout = timeout or self._timeout
        
        try:
            # Отправляем HTTP POST запрос (SSE использует POST для запросов)
            async with self._session.post(
                self._url,
                json=request.model_dump(by_alias=True, exclude_none=True),
                headers=self._headers,
            ) as response:
                logger.debug(
                    "SSE HTTP response status: %d for method=%s id=%d",
                    response.status, method, request_id
                )
                
                if response.status >= 400:
                    raise SseTransportError(
                        f"HTTP error: status {response.status}"
                    )
            
            # Ожидаем ответ через SSE events
            try:
                mcp_response = await asyncio.wait_for(future, timeout=request_timeout)
            except TimeoutError:
                raise SseTransportError(
                    f"Request timeout after {request_timeout}s: method={method}"
                ) from None
            
            # Проверяем на ошибку
            if mcp_response.error:
                raise SseTransportError(
                    f"MCP error {mcp_response.error.code}: {mcp_response.error.message}"
                )
            
            return mcp_response.result or {}
            
        finally:
            self._pending_requests.pop(request_id, None)
    
    async def send_notification(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Отправить JSON-RPC нотификацию.
        
        Args:
            method: Имя метода нотификации.
            params: Параметры нотификации.
        
        Raises:
            SseTransportError: Если соединение не установлено.
        """
        if not self.is_connected:
            raise SseTransportError("Not connected to MCP server")
        
        if not self._session:
            raise SseTransportError("Session not initialized")
        
        notification = MCPNotification(method=method, params=params)
        
        try:
            async with self._session.post(
                self._url,
                json=notification.model_dump(by_alias=True, exclude_none=True),
                headers=self._headers,
            ) as response:
                logger.debug(
                    "Sent SSE notification: method=%s status=%d",
                    method, response.status
                )
        except aiohttp.ClientError as e:
            raise SseTransportError(
                f"Failed to send notification: {e}"
            ) from e
    
    async def disconnect(self) -> None:
        """Закрыть SSE соединение.
        
        Отменяет все ожидающие запросы и закрывает SSE connection.
        """
        if self._closed:
            return
        
        self._closed = True
        
        logger.debug("Closing SSE MCP transport")
        
        # Отменяем все ожидающие запросы
        for _request_id, future in self._pending_requests.items():
            if not future.done():
                future.set_exception(
                    SseTransportError("Transport closed")
                )
        self._pending_requests.clear()
        
        # Останавливаем задачу чтения
        if self._read_task:
            self._read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._read_task
        
        # Закрываем SSE response
        if self._sse_response and not self._sse_response.closed:
            await self._sse_response.release()
        
        # Закрываем session
        if self._session and not self._session.closed:
            await self._session.close()
        
        self._session = None
        self._sse_response = None
        logger.debug("SSE MCP transport closed")
    
    async def _read_sse_loop(self) -> None:
        """Фоновая задача чтения SSE событий.
        
        Парсит SSE events (data:, event:, id: lines) и диспетчеризирует их.
        """
        if not self._sse_response:
            return
        
        current_event = "message"  # default SSE event type
        current_data = []
        current_id = None
        
        try:
            async for line in self._sse_response.content:
                text = line.decode("utf-8").rstrip("\n")
                
                if not text:
                    # Пустая строка — конец события
                    if current_data:
                        await self._handle_sse_event(
                            event=current_event,
                            data="\n".join(current_data),
                            event_id=current_id
                        )
                        current_data = []
                        current_event = "message"
                        current_id = None
                    continue
                
                if text.startswith(":"):
                    # Комментарий — игнорируем
                    continue
                
                if ":" in text:
                    field, value = text.split(":", 1)
                    value = value.lstrip(" ")
                else:
                    field = text
                    value = ""
                
                if field == "event":
                    current_event = value
                elif field == "data":
                    current_data.append(value)
                elif field == "id":
                    current_id = value
        
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Error reading SSE events: %s", e)
            # Отменяем все ожидающие запросы
            for future in self._pending_requests.values():
                if not future.done():
                    future.set_exception(
                        SseTransportError(f"SSE read error: {e}")
                    )
    
    async def _handle_sse_event(
        self,
        event: str,
        data: str,
        event_id: str | None = None,
    ) -> None:
        """Обработать SSE событие.
        
        Args:
            event: Тип события.
            data: Данные события.
            event_id: ID события.
        """
        logger.debug(
            "Received SSE event: type=%s id=%s",
            event, event_id
        )
        
        try:
            json_data = json.loads(data)
        except json.JSONDecodeError as e:
            logger.warning("Invalid JSON in SSE event: %s", e)
            return
        
        # Проверяем, это ответ на запрос или notification
        message_id = json_data.get("id")
        
        if message_id is not None:
            # Это ответ на запрос
            future = self._pending_requests.get(message_id)
            
            if future and not future.done():
                try:
                    response = MCPResponse.model_validate(json_data)
                    future.set_result(response)
                except Exception as e:
                    future.set_exception(
                        SseTransportError(f"Invalid response: {e}")
                    )
            else:
                logger.warning(
                    "Received response for unknown request id=%s",
                    message_id
                )
        else:
            # Это notification
            method = json_data.get("method", "unknown")
            logger.debug(
                "Received MCP notification via SSE: method=%s",
                method
            )
            
            # Помещаем в очередь notifications
            await self._notification_queue.put(json_data)
            
            # Вызываем зарегистрированные handlers
            handlers = self._notification_handlers.get(method, [])
            for handler in handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(json_data)
                    else:
                        handler(json_data)
                except Exception as e:
                    logger.error(
                        "Error in SSE notification handler: %s", e
                    )
    
    def register_notification_handler(
        self,
        method: str,
        handler: Callable,
    ) -> None:
        """Зарегистрировать обработчик для конкретного типа notification.
        
        Args:
            method: Имя метода notification.
            handler: Функция для обработки.
        """
        if method not in self._notification_handlers:
            self._notification_handlers[method] = []
        self._notification_handlers[method].append(handler)
