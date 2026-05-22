"""FileSystemHandler - обработчик fs/* методов от агента.

Модуль предоставляет:
- Обработку fs/read_text_file запросов от агента
- Обработку fs/write_text_file запросов от агента
- Логирование и обработку ошибок

Пример использования:
    executor = FileSystemExecutor(base_path=Path("/workspace"))
    handler = FileSystemHandler(executor)
    result = await handler.handle_read_text_file({
        "sessionId": "sess_123",
        "path": "src/main.py",
        "line": 1,
        "limit": 50
    })
"""

from __future__ import annotations

from typing import Any

import structlog

from codelab.client.infrastructure.services.file_system_executor import FileSystemExecutor

logger = structlog.get_logger("file_system_handler")


class FileSystemHandler:
    """Обработчик fs/* методов от агента.

    Класс обрабатывает входящие RPC запросы от агента для файловых операций.

    Модель разрешений (согласно ACP спецификации 08-Tool Calls#Requesting Permission):
    Проверка разрешений выполняется на сервере ДО отправки RPC клиенту.
    Корректный поток:

        1. LLM → Agent: tool call (например, edit kind)
        2. Agent → Client: session/request_permission (PermissionHandler)
        3. Client → Agent: пользователь выбирает allow/reject
        4. Если allow → Agent → Client: fs/write_text_file RPC (этот handler)
        5. Client → Agent: {result: null}

    Таким образом, когда Agent отправляет fs/write_text_file RPC, разрешение
    уже получено от пользователя. Клиент доверяет серверу и выполняет
    операцию без дополнительной проверки.

    Attributes:
        executor: FileSystemExecutor для выполнения операций
    """

    def __init__(self, executor: FileSystemExecutor) -> None:
        """Инициализирует handler с executor.

        Args:
            executor: FileSystemExecutor для выполнения операций

        Пример:
            executor = FileSystemExecutor(base_path=Path("/home/user/work"))
            handler = FileSystemHandler(executor)
        """
        self.executor = executor
        logger.debug("file_system_handler_initialized")

    async def handle_read_text_file(self, params: dict[str, Any]) -> dict[str, Any]:
        """Обработать fs/read_text_file request от агента.

        Агент запрашивает чтение файла с опциональными параметрами
        для указания диапазона строк.

        Args:
            params: Request параметры
                - sessionId (str): ID сессии запроса
                - path (str): Путь к файлу
                - line (int, optional): Начальная строка (1-based)
                - limit (int, optional): Максимум строк

        Returns:
            dict с ключом "content" содержащим прочитанный текст

        Raises:
            FileNotFoundError: Файл не найден
            ValueError: Некорректный путь
            IOError: Ошибка чтения
        """
        session_id = params.get("sessionId", "unknown")
        path = params.get("path")
        line = params.get("line")
        limit = params.get("limit")

        if not path:
            logger.warning("read_text_file_missing_path", session_id=session_id)
            raise ValueError("Missing required parameter: path")

        logger.info(
            "agent_read_text_file_request",
            session_id=session_id,
            path=path,
            line=line,
            limit=limit,
        )

        try:
            content = await self.executor.read_text_file(path, line=line, limit=limit)
            
            logger.info(
                "agent_read_text_file_success",
                session_id=session_id,
                path=path,
                content_size=len(content),
            )
            return {"content": content}
        except (OSError, FileNotFoundError, ValueError) as e:
            logger.error(
                "agent_read_text_file_error",
                session_id=session_id,
                path=path,
                error=str(e),
            )
            raise

    async def handle_write_text_file(self, params: dict[str, Any]) -> dict[str, Any]:
        """Обработать fs/write_text_file request от агента.

        Агент запрашивает запись файла. Проверка разрешения выполняется
        на стороне сервера через PermissionManager перед отправкой RPC
        клиенту, поэтому клиент доверяет серверу и выполняет операцию
        без дополнительной проверки.

        Args:
            params: Request параметры
                - sessionId (str): ID сессии запроса
                - path (str): Путь к файлу
                - content (str): Содержимое для записи

        Returns:
            dict с ключом "success" = true

        Raises:
            ValueError: Отсутствуют необходимые параметры
            IOError: Ошибка записи
        """
        session_id = params.get("sessionId", "unknown")
        path = params.get("path")
        content = params.get("content")

        if not path:
            logger.warning("write_text_file_missing_path", session_id=session_id)
            raise ValueError("Missing required parameter: path")

        if content is None:
            logger.warning("write_text_file_missing_content", session_id=session_id)
            raise ValueError("Missing required parameter: content")

        logger.info(
            "agent_write_text_file_request",
            session_id=session_id,
            path=path,
            content_size=len(content),
        )

        try:
            await self.executor.write_text_file(path, content)
            
            logger.info(
                "agent_write_text_file_success",
                session_id=session_id,
                path=path,
                content_size=len(content),
            )
            # ACP spec: empty response means success
            return {}
        except (OSError, ValueError) as e:
            logger.error(
                "agent_write_text_file_error",
                session_id=session_id,
                path=path,
                error=str(e),
            )
            raise
