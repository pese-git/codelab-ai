"""Адаптер для ClientRPCService, инкапсулирующий RPC вызовы для executors."""

from __future__ import annotations

from typing import Any

import structlog

from codelab.server.client_rpc.exceptions import (
    ClientCapabilityMissingError,
    ClientRPCError,
    ClientRPCResponseError,
    ClientRPCTimeoutError,
)
from codelab.server.client_rpc.service import ClientRPCService
from codelab.server.protocol.state import SessionState

logger = structlog.get_logger()


class ClientRPCBridge:
    """Адаптер, предоставляющий безопасный доступ к ClientRPCService для executors.
    
    Задачи:
    - Инкапсулировать ClientRPCService
    - Проверять capabilities перед вызовами
    - Преобразовывать RPC исключения в ToolExecutionResult
    - Логирование всех операций
    """

    def __init__(self, client_rpc_service: ClientRPCService) -> None:
        """Инициализировать bridge с ClientRPCService.
        
        Args:
            client_rpc_service: Экземпляр ClientRPCService для вызова методов на клиенте.
        """
        self._service = client_rpc_service

    async def read_file(
        self,
        session: SessionState,
        path: str,
        line: int | None = None,
        limit: int | None = None,
    ) -> str | None:
        """Прочитать текстовый файл через ClientRPC.
        
        Args:
            session: Состояние сессии для логирования и контекста.
            path: Путь к файлу.
            line: Начальная строка (1-based, опционально).
            limit: Максимум строк для чтения (опционально).
            
        Returns:
            Содержимое файла или None при ошибке.
            
        Логирует все ошибки перед возвращением None.
        """
        try:
            logger.debug(
                "Чтение файла через ClientRPC",
                extra={
                    "session_id": session.session_id,
                    "path": path,
                    "line": line,
                    "limit": limit,
                },
            )
            
            content = await self._service.read_text_file(
                session_id=session.session_id,
                path=path,
                line=line,
                limit=limit,
            )
            
            logger.debug(
                "Файл успешно прочитан",
                extra={
                    "session_id": session.session_id,
                    "path": path,
                    "bytes": len(content),
                },
            )
            
            return content
            
        except ClientCapabilityMissingError as e:
            logger.error(
                "Capability fs.readTextFile отсутствует на клиенте",
                extra={"session_id": session.session_id, "error": str(e)},
            )
            return None
            
        except (ClientRPCTimeoutError, ClientRPCResponseError, ClientRPCError) as e:
            logger.error(
                "Ошибка при чтении файла",
                extra={"session_id": session.session_id, "path": path, "error": str(e)},
            )
            return None

    async def write_file(
        self,
        session: SessionState,
        path: str,
        content: str,
    ) -> bool:
        """Записать текстовый файл через ClientRPC.
        
        Args:
            session: Состояние сессии для логирования и контекста.
            path: Путь к файлу.
            content: Содержимое для записи.
            
        Returns:
            True при успехе, False при ошибке.
            
        Логирует все ошибки перед возвращением False.
        """
        try:
            logger.debug(
                "Запись файла через ClientRPC",
                extra={
                    "session_id": session.session_id,
                    "path": path,
                    "bytes": len(content),
                },
            )
            
            success = await self._service.write_text_file(
                session_id=session.session_id,
                path=path,
                content=content,
            )
            
            logger.debug(
                "Файл успешно записан",
                extra={"session_id": session.session_id, "path": path},
            )
            
            return success
            
        except ClientCapabilityMissingError as e:
            logger.error(
                "Capability fs.writeTextFile отсутствует на клиенте",
                extra={"session_id": session.session_id, "error": str(e)},
            )
            return False
            
        except (ClientRPCTimeoutError, ClientRPCResponseError, ClientRPCError) as e:
            logger.error(
                "Ошибка при записи файла",
                extra={"session_id": session.session_id, "path": path, "error": str(e)},
            )
            return False

    async def create_terminal(
        self,
        session: SessionState,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        output_byte_limit: int | None = None,
    ) -> str | None:
        """Создать терминал через ClientRPC.
        
        Args:
            session: Состояние сессии для логирования и контекста.
            command: Команда для выполнения.
            args: Аргументы команды (опционально).
            env: Переменные окружения (опционально).
            cwd: Рабочая директория (опционально).
            output_byte_limit: Лимит байт output (опционально).
            
        Returns:
            Terminal ID при успехе, None при ошибке.
            
        Логирует все ошибки перед возвращением None.
        """
        try:
            logger.debug(
                "Создание терминала через ClientRPC",
                extra={
                    "session_id": session.session_id,
                    "command": command,
                    "cwd": cwd,
                },
            )
            
            terminal_id = await self._service.create_terminal(
                session_id=session.session_id,
                command=command,
                args=args,
                env=env,
                cwd=cwd,
                output_byte_limit=output_byte_limit,
            )
            
            logger.debug(
                "Терминал успешно создан",
                extra={
                    "session_id": session.session_id,
                    "terminal_id": terminal_id,
                },
            )
            
            return terminal_id
            
        except ClientCapabilityMissingError as e:
            logger.error(
                "Capability terminal отсутствует на клиенте",
                extra={"session_id": session.session_id, "error": str(e)},
            )
            return None
            
        except (ClientRPCTimeoutError, ClientRPCResponseError, ClientRPCError) as e:
            logger.error(
                "Ошибка при создании терминала",
                extra={
                    "session_id": session.session_id,
                    "command": command,
                    "error": str(e),
                },
            )
            return None

    async def wait_terminal_exit(
        self,
        session: SessionState,
        terminal_id: str,
    ) -> dict[str, Any] | None:
        """Ожидать завершения терминала через ClientRPC.
        
        Args:
            session: Состояние сессии для логирования и контекста.
            terminal_id: ID терминала.
            
        Returns:
            Словарь с exit_code и signal при успехе, None при ошибке.
            
        Логирует все ошибки перед возвращением None.
        """
        try:
            logger.debug(
                "Ожидание завершения терминала через ClientRPC",
                extra={
                    "session_id": session.session_id,
                    "terminal_id": terminal_id,
                },
            )
            
            exit_code, signal = await self._service.wait_for_exit(
                session_id=session.session_id,
                terminal_id=terminal_id,
            )
            
            logger.debug(
                "Терминал завершен",
                extra={
                    "session_id": session.session_id,
                    "terminal_id": terminal_id,
                    "exit_code": exit_code,
                    "signal": signal,
                },
            )
            
            return {
                "exit_code": exit_code,
                "signal": signal,
            }
            
        except ClientCapabilityMissingError as e:
            logger.error(
                "Capability terminal отсутствует на клиенте",
                extra={"session_id": session.session_id, "error": str(e)},
            )
            return None
            
        except (ClientRPCTimeoutError, ClientRPCResponseError, ClientRPCError) as e:
            logger.error(
                "Ошибка при ожидании завершения терминала",
                extra={
                    "session_id": session.session_id,
                    "terminal_id": terminal_id,
                    "error": str(e),
                },
            )
            return None

    async def terminal_output(
        self,
        session: SessionState,
        terminal_id: str,
    ) -> dict[str, Any] | None:
        """Получить текущий output терминала через ClientRPC.
        
        Args:
            session: Состояние сессии для логирования и контекста.
            terminal_id: ID терминала.
            
        Returns:
            Словарь {output, truncated, exit_code, signal, is_complete} или None при ошибке.
            is_complete вычисляется из наличия exit_status.
            
        Логирует все ошибки перед возвращением None.
        """
        try:
            logger.debug(
                "Получение output терминала через ClientRPC",
                extra={
                    "session_id": session.session_id,
                    "terminal_id": terminal_id,
                },
            )
            
            output, truncated, exit_code, signal = await self._service.terminal_output(
                session_id=session.session_id,
                terminal_id=terminal_id,
            )
            
            is_complete = exit_code is not None or signal is not None
            
            logger.debug(
                "Output терминала получен",
                extra={
                    "session_id": session.session_id,
                    "terminal_id": terminal_id,
                    "output_size": len(output),
                    "truncated": truncated,
                    "is_complete": is_complete,
                },
            )
            
            return {
                "output": output,
                "truncated": truncated,
                "is_complete": is_complete,
                "exit_code": exit_code,
                "signal": signal,
            }
            
        except ClientCapabilityMissingError as e:
            logger.error(
                "Capability terminal отсутствует на клиенте",
                extra={"session_id": session.session_id, "error": str(e)},
            )
            return None
            
        except (ClientRPCTimeoutError, ClientRPCResponseError, ClientRPCError) as e:
            logger.error(
                "Ошибка при получении output терминала",
                extra={
                    "session_id": session.session_id,
                    "terminal_id": terminal_id,
                    "error": str(e),
                },
            )
            return None

    async def release_terminal(
        self,
        session: SessionState,
        terminal_id: str,
    ) -> bool:
        """Освободить терминал через ClientRPC.
        
        Args:
            session: Состояние сессии для логирования и контекста.
            terminal_id: ID терминала.
            
        Returns:
            True при успехе, False при ошибке.
            
        Логирует все ошибки перед возвращением False.
        """
        try:
            logger.debug(
                "Освобождение терминала через ClientRPC",
                extra={
                    "session_id": session.session_id,
                    "terminal_id": terminal_id,
                },
            )
            
            success = await self._service.release_terminal(
                session_id=session.session_id,
                terminal_id=terminal_id,
            )
            
            logger.debug(
                "Терминал успешно освобожден",
                extra={
                    "session_id": session.session_id,
                    "terminal_id": terminal_id,
                },
            )
            
            return success
            
        except ClientCapabilityMissingError as e:
            logger.error(
                "Capability terminal отсутствует на клиенте",
                extra={"session_id": session.session_id, "error": str(e)},
            )
            return False
            
        except (ClientRPCTimeoutError, ClientRPCResponseError, ClientRPCError) as e:
            logger.error(
                "Ошибка при освобождении терминала",
                extra={
                    "session_id": session.session_id,
                    "terminal_id": terminal_id,
                    "error": str(e),
                },
            )
            return False
