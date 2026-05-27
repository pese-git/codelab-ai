"""MCPManager — управление несколькими MCP серверами в рамках сессии.

Централизованное управление жизненным циклом MCP клиентов,
их инструментами и маршрутизацией вызовов.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from enum import Enum
from typing import Any

from ..tools.base import ToolDefinition, ToolExecutionResult
from .client import MCPClient, MCPClientError, MCPClientState
from .models import MCPServerConfig, MCPTool
from .tool_adapter import MCPToolAdapter

logger = logging.getLogger(__name__)


class MCPManagerState(Enum):
    """Состояние MCPManager."""
    
    READY = "ready"
    """Готов к работе."""
    
    RECONNECTING = "reconnecting"
    """Выполняется переподключение."""
    
    FAILED = "failed"
    """Ошибка, переподключение не удалось."""


class MCPManagerError(Exception):
    """Базовое исключение для ошибок MCPManager."""
    pass


class MCPServerNotFoundError(MCPManagerError):
    """MCP сервер не найден."""
    pass


class MCPServerAlreadyExistsError(MCPManagerError):
    """MCP сервер с таким ID уже существует."""
    pass


class MCPManager:
    """Менеджер MCP серверов для одной сессии.
    
    Управляет несколькими MCP серверами, их жизненным циклом,
    инструментами и маршрутизацией вызовов.
    
    Attributes:
        session_id: ID сессии, которой принадлежит менеджер.
        servers: Словарь подключённых MCP клиентов (server_id -> client).
        adapters: Словарь адаптеров инструментов (server_id -> adapter).
    
    Example:
        >>> manager = MCPManager("session_123")
        >>> config = MCPServerConfig(name="fs", command="mcp-fs", args=["--stdio"])
        >>> await manager.add_server(config)
        >>> tools = manager.get_all_tools()
        >>> result = await manager.call_tool("mcp:fs:read_file", {"path": "/tmp/test"})
        >>> await manager.shutdown()
    """
    
    def __init__(self, session_id: str) -> None:
        """Инициализация менеджера.
        
        Args:
            session_id: ID сессии для контекста логирования.
        """
        self.session_id = session_id
        self._clients: dict[str, MCPClient] = {}
        self._adapters: dict[str, MCPToolAdapter] = {}
        self._tools_cache: dict[str, list[MCPTool]] = {}
        
        # Auto-reconnect state
        self._state: MCPManagerState = MCPManagerState.READY
        self._reconnect_tasks: dict[str, asyncio.Task] = {}
        self._health_check_tasks: dict[str, asyncio.Task] = {}
    
    @property
    def server_ids(self) -> list[str]:
        """Список ID подключённых серверов."""
        return list(self._clients.keys())
    
    @property
    def server_count(self) -> int:
        """Количество подключённых серверов."""
        return len(self._clients)
    
    def get_client(self, server_id: str) -> MCPClient | None:
        """Получить MCP клиент по ID сервера.
        
        Args:
            server_id: Идентификатор сервера.
        
        Returns:
            MCP клиент или None если не найден.
        """
        return self._clients.get(server_id)
    
    def has_server(self, server_id: str) -> bool:
        """Проверить, подключён ли сервер.
        
        Args:
            server_id: Идентификатор сервера.
        
        Returns:
            True если сервер подключён.
        """
        return server_id in self._clients
    
    async def add_server(self, config: MCPServerConfig) -> list[ToolDefinition]:
        """Добавить и инициализировать MCP сервер.
        
        Запускает процесс MCP сервера, выполняет initialize handshake,
        получает список инструментов и создаёт адаптер.
        
        Args:
            config: Конфигурация MCP сервера.
        
        Returns:
            Список адаптированных ToolDefinition от сервера.
        
        Raises:
            MCPServerAlreadyExistsError: Если сервер уже подключён.
            MCPManagerError: Если не удалось подключиться или инициализировать.
        """
        server_id = config.name
        
        if server_id in self._clients:
            raise MCPServerAlreadyExistsError(
                f"MCP server '{server_id}' already connected to session {self.session_id}"
            )
        
        logger.info(
            "Adding MCP server '%s' to session %s",
            server_id,
            self.session_id
        )
        
        client = MCPClient(config)
        
        try:
            # Подключаемся к серверу
            await client.connect()
            
            # Выполняем initialize
            await client.initialize()
            
            # Получаем список инструментов
            mcp_tools = await client.list_tools()
            
            # Создаём адаптер
            adapter = MCPToolAdapter(server_id, client)
            
            # Сохраняем в менеджере
            self._clients[server_id] = client
            self._adapters[server_id] = adapter
            self._tools_cache[server_id] = mcp_tools
            
            # Преобразуем инструменты
            tools = adapter.adapt_tools(mcp_tools)
            
            logger.info(
                "MCP server '%s' added successfully with %d tools",
                server_id,
                len(tools)
            )
            
            return tools
            
        except MCPClientError as e:
            # Пытаемся отключить клиент при ошибке
            with contextlib.suppress(Exception):
                await client.disconnect()
            
            raise MCPManagerError(
                f"Failed to add MCP server '{server_id}': {e}"
            ) from e
    
    async def remove_server(self, server_id: str) -> None:
        """Удалить MCP сервер.
        
        Отключает клиент и удаляет все связанные данные.
        
        Args:
            server_id: Идентификатор сервера для удаления.
        
        Raises:
            MCPServerNotFoundError: Если сервер не найден.
        """
        if server_id not in self._clients:
            raise MCPServerNotFoundError(
                f"MCP server '{server_id}' not found in session {self.session_id}"
            )
        
        logger.info(
            "Removing MCP server '%s' from session %s",
            server_id,
            self.session_id
        )
        
        client = self._clients[server_id]
        
        # Отключаем клиент
        try:
            await client.disconnect()
        except Exception as e:
            logger.warning(
                "Error disconnecting MCP server '%s': %s",
                server_id,
                str(e)
            )
        
        # Удаляем из менеджера
        del self._clients[server_id]
        del self._adapters[server_id]
        del self._tools_cache[server_id]
        
        logger.info("MCP server '%s' removed successfully", server_id)
    
    def get_all_tools(self) -> list[ToolDefinition]:
        """Получить все инструменты от всех MCP серверов.
        
        Returns:
            Объединённый список ToolDefinition от всех серверов.
        """
        all_tools: list[ToolDefinition] = []
        
        for server_id, mcp_tools in self._tools_cache.items():
            adapter = self._adapters.get(server_id)
            if adapter:
                tools = adapter.adapt_tools(mcp_tools)
                all_tools.extend(tools)
        
        return all_tools
    
    def get_tools_for_server(self, server_id: str) -> list[ToolDefinition]:
        """Получить инструменты конкретного сервера.
        
        Args:
            server_id: Идентификатор сервера.
        
        Returns:
            Список ToolDefinition от сервера.
        
        Raises:
            MCPServerNotFoundError: Если сервер не найден.
        """
        if server_id not in self._clients:
            raise MCPServerNotFoundError(
                f"MCP server '{server_id}' not found in session {self.session_id}"
            )
        
        adapter = self._adapters[server_id]
        mcp_tools = self._tools_cache[server_id]
        return adapter.adapt_tools(mcp_tools)
    
    async def call_tool(
        self,
        namespaced_name: str,
        arguments: dict[str, Any],
    ) -> ToolExecutionResult:
        """Вызвать MCP инструмент по namespaced имени.
        
        Разбирает имя, находит нужный сервер и выполняет вызов.
        
        Args:
            namespaced_name: Полное имя вида mcp:server_id:tool_name.
            arguments: Аргументы для вызова инструмента.
        
        Returns:
            Результат выполнения инструмента.
        
        Raises:
            MCPManagerError: Если формат имени неверный или сервер не найден.
        """
        # Разбираем namespaced имя
        parsed = MCPToolAdapter.parse_namespaced_name(namespaced_name)
        
        if parsed is None:
            return ToolExecutionResult(
                success=False,
                error=f"Invalid MCP tool name format: {namespaced_name}",
            )
        
        prefix, server_id, tool_name = parsed
        
        if prefix != MCPToolAdapter.NAMESPACE_PREFIX:
            return ToolExecutionResult(
                success=False,
                error=f"Invalid namespace prefix: {prefix}",
            )
        
        # Находим адаптер
        adapter = self._adapters.get(server_id)
        
        if adapter is None:
            return ToolExecutionResult(
                success=False,
                error=f"MCP server '{server_id}' not found",
            )
        
        # Проверяем состояние клиента
        client = self._clients.get(server_id)
        if client is None or client.state != MCPClientState.READY:
            return ToolExecutionResult(
                success=False,
                error=f"MCP server '{server_id}' is not ready",
            )
        
        # Вызываем инструмент через адаптер
        logger.debug(
            "Calling MCP tool: %s (server=%s, tool=%s)",
            namespaced_name,
            server_id,
            tool_name
        )
        
        return await adapter.call_tool(tool_name, arguments)
    
    def get_servers_info(self) -> list[dict[str, Any]]:
        """Получить информацию о всех подключённых серверах.
        
        Returns:
            Список словарей с информацией о серверах.
        """
        servers_info: list[dict[str, Any]] = []
        
        for server_id, client in self._clients.items():
            tools_count = len(self._tools_cache.get(server_id, []))
            
            server_info: dict[str, Any] = {
                "id": server_id,
                "name": client.config.name,
                "command": client.config.command,
                "state": client.state.value,
                "tools_count": tools_count,
            }
            
            # Добавляем capabilities если доступны
            if client.capabilities:
                server_info["capabilities"] = client.capabilities.model_dump(
                    exclude_none=True
                )
            
            servers_info.append(server_info)
        
        return servers_info
    
    async def refresh_tools(self, server_id: str) -> list[ToolDefinition]:
        """Обновить список инструментов сервера.
        
        Запрашивает tools/list заново и обновляет кэш.
        
        Args:
            server_id: Идентификатор сервера.
        
        Returns:
            Обновлённый список ToolDefinition.
        
        Raises:
            MCPServerNotFoundError: Если сервер не найден.
            MCPManagerError: Если не удалось получить инструменты.
        """
        if server_id not in self._clients:
            raise MCPServerNotFoundError(
                f"MCP server '{server_id}' not found in session {self.session_id}"
            )
        
        client = self._clients[server_id]
        adapter = self._adapters[server_id]
        
        try:
            mcp_tools = await client.list_tools()
            self._tools_cache[server_id] = mcp_tools
            
            logger.info(
                "Refreshed tools for MCP server '%s': %d tools",
                server_id,
                len(mcp_tools)
            )
            
            return adapter.adapt_tools(mcp_tools)
            
        except MCPClientError as e:
            raise MCPManagerError(
                f"Failed to refresh tools from '{server_id}': {e}"
            ) from e
    
    async def shutdown(self) -> None:
        """Отключить все MCP серверы.
        
        Безопасно завершает все соединения при завершении сессии.
        """
        logger.info(
            "Shutting down MCPManager for session %s (%d servers)",
            self.session_id,
            len(self._clients)
        )
        
        # Копируем список серверов т.к. remove_server модифицирует словарь
        server_ids = list(self._clients.keys())
        
        for server_id in server_ids:
            try:
                await self.remove_server(server_id)
            except Exception as e:
                logger.error(
                    "Error removing MCP server '%s' during shutdown: %s",
                    server_id,
                    str(e)
                )
        
        logger.info("MCPManager shutdown complete for session %s", self.session_id)
    
    # ===== Auto-Reconnect =====
    
    @property
    def state(self) -> MCPManagerState:
        """Текущее состояние менеджера."""
        return self._state
    
    async def reconnect_with_backoff(self, server_id: str) -> bool:
        """Переподключиться к серверу с exponential backoff.
        
        Args:
            server_id: Идентификатор сервера.
        
        Returns:
            True если переподключение удалось.
        """
        if server_id not in self._clients:
            logger.warning(
                "Cannot reconnect: server '%s' not found",
                server_id
            )
            return False
        
        client = self._clients[server_id]
        config = client.config
        retry_config = config.get_retry_config()
        
        max_retries = int(retry_config["max_retries"])
        initial_delay = float(retry_config["initial_delay"])
        max_delay = float(retry_config["max_delay"])
        backoff_multiplier = float(retry_config["backoff_multiplier"])
        
        self._state = MCPManagerState.RECONNECTING
        
        logger.info(
            "Starting reconnect for server '%s' (max_retries=%d)",
            server_id, max_retries
        )
        
        delay = initial_delay
        
        for attempt in range(max_retries):
            try:
                # Jitter: 10% от delay
                jitter = random.uniform(0, delay * 0.1)
                sleep_time = delay + jitter
                
                logger.info(
                    "Reconnect attempt %d/%d for server '%s' in %.2fs",
                    attempt + 1, max_retries, server_id, sleep_time
                )
                
                await asyncio.sleep(sleep_time)
                
                # Пытаемся переподключиться
                await client.disconnect()
                await client.connect()
                await client.initialize()
                
                # Обновляем инструменты
                mcp_tools = await client.list_tools()
                self._tools_cache[server_id] = mcp_tools
                
                # Обновляем адаптер
                adapter = self._adapters.get(server_id)
                if adapter:
                    adapter.adapt_tools(mcp_tools)
                
                logger.info(
                    "Successfully reconnected to server '%s'",
                    server_id
                )
                
                self._state = MCPManagerState.READY
                return True
                
            except Exception as e:
                logger.warning(
                    "Reconnect attempt %d/%d failed for server '%s': %s",
                    attempt + 1, max_retries, server_id, e
                )
                
                # Увеличиваем delay
                delay = min(delay * backoff_multiplier, max_delay)
        
        # Все попытки исчерпаны
        self._state = MCPManagerState.FAILED
        
        logger.error(
            "Failed to reconnect to server '%s' after %d attempts",
            server_id, max_retries
        )
        
        return False
    
    async def start_health_check(self, server_id: str, interval: float = 60.0) -> None:
        """Запустить periodic health check для сервера.
        
        Args:
            server_id: Идентификатор сервера.
            interval: Интервал проверки в секундах.
        """
        if server_id in self._health_check_tasks:
            logger.warning(
                "Health check already running for server '%s'",
                server_id
            )
            return
        
        task = asyncio.create_task(
            self._health_check_loop(server_id, interval),
            name=f"mcp_health_check_{server_id}"
        )
        self._health_check_tasks[server_id] = task
        
        logger.info(
            "Started health check for server '%s' (interval=%.0fs)",
            server_id, interval
        )
    
    async def _health_check_loop(self, server_id: str, interval: float) -> None:
        """Цикл periodic health check.
        
        Args:
            server_id: Идентификатор сервера.
            interval: Интервал проверки.
        """
        while self._state != MCPManagerState.FAILED:
            try:
                await asyncio.sleep(interval)
                
                client = self._clients.get(server_id)
                if client is None:
                    logger.warning(
                        "Health check: server '%s' not found",
                        server_id
                    )
                    break
                
                # Проверяем состояние клиента
                if client.state != MCPClientState.READY:
                    logger.warning(
                        "Health check failed for server '%s': state=%s",
                        server_id, client.state.value
                    )
                    
                    # Запускаем переподключение
                    await self.reconnect_with_backoff(server_id)
                
                else:
                    logger.debug(
                        "Health check passed for server '%s'",
                        server_id
                    )
            
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(
                    "Error in health check for server '%s': %s",
                    server_id, e
                )
    
    async def stop_health_check(self, server_id: str) -> None:
        """Остановить health check для сервера.
        
        Args:
            server_id: Идентификатор сервера.
        """
        task = self._health_check_tasks.pop(server_id, None)
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            
            logger.info(
                "Stopped health check for server '%s'",
                server_id
            )
    
    async def handle_server_failure(self, server_id: str) -> None:
        """Обработать ошибку сервера и запустить переподключение.
        
        Args:
            server_id: Идентификатор сервера.
        """
        logger.warning(
            "Server '%s' failure detected, initiating reconnect",
            server_id
        )
        
        # Запускаем переподключение в фоне
        if server_id not in self._reconnect_tasks:
            task = asyncio.create_task(
                self.reconnect_with_backoff(server_id),
                name=f"mcp_reconnect_{server_id}"
            )
            self._reconnect_tasks[server_id] = task
