"""FileSystemExecutor - исполнитель файловых операций в локальной среде клиента.

Модуль предоставляет:
- Чтение текстовых файлов с поддержкой диапазонов строк (async и sync)
- Запись текстовых файлов (async и sync)
- Валидацию путей (защита от path traversal)
- Асинхронные операции через aiofiles
- Синхронные операции для использования в callbacks

Пример использования:
    executor = FileSystemExecutor(base_path=Path("/workspace"))
    # Асинхронно
    content = await executor.read_text_file("src/main.py", line=1, limit=50)
    await executor.write_text_file("output.txt", "Hello, World!")
    # Синхронно
    content = executor.read_text_file_sync("src/main.py")
    executor.write_text_file_sync("output.txt", "Hello, World!")
"""

from __future__ import annotations

from pathlib import Path

import aiofiles
import structlog

logger = structlog.get_logger("file_system_executor")


class FileSystemExecutor:
    """Исполнитель файловых операций в локальной среде клиента.

    Выполняет чтение и запись файлов с валидацией путей и защитой от
    path traversal атак.

    Attributes:
        base_path: Базовая директория (sandbox). None = без ограничений.
    """

    def __init__(self, base_path: Path | None = None) -> None:
        """Инициализирует executor с опциональной базовой директорией.

        Args:
            base_path: Базовая директория (sandbox). None = без ограничений.

        Пример:
            # С sandbox ограничением
            executor = FileSystemExecutor(base_path=Path("/home/user/projects"))
            
            # Без ограничений
            executor = FileSystemExecutor()
        """
        self.base_path = base_path
        logger.debug(
            "file_system_executor_initialized",
            base_path=str(base_path) if base_path else None,
        )

    def _validate_path(self, path: str) -> Path:
        """Валидировать и нормализовать путь.

        Защита от path traversal атак (../../etc/passwd).

        Args:
            path: Путь к файлу (абсолютный или относительный)

        Returns:
            Нормализованный Path объект

        Raises:
            ValueError: Некорректный путь или path traversal
        """
        try:
            # Если есть base_path, разрешить путь относительно него
            if self.base_path:
                base_resolved = self.base_path.resolve()
                file_path = (base_resolved / path).resolve()
            else:
                file_path = Path(path).resolve()
        except (ValueError, RuntimeError) as e:
            logger.warning("invalid_path", path=path, error=str(e))
            raise ValueError(f"Invalid path: {path}") from e

        # Если задан base_path, проверить что путь внутри него
        if self.base_path:
            base_resolved = self.base_path.resolve()

            # is_relative_to() проверяет компоненты пути, а не строковый префикс.
            # /home/user/projects_evil НЕ является относительным к /home/user/projects
            if not file_path.is_relative_to(base_resolved):
                msg = (
                    f"Path traversal detected: '{path}' "
                    f"resolves outside sandbox '{base_resolved}'"
                )
                logger.warning(
                    "path_traversal_attempt",
                    path=path,
                    resolved=str(file_path),
                    base_path=str(base_resolved),
                )
                raise ValueError(msg)

        return file_path

    async def read_text_file(
        self,
        path: str,
        line: int | None = None,
        limit: int | None = None,
    ) -> str:
        """Прочитать текстовый файл.

        Поддерживает чтение диапазона строк через параметры line и limit.

        Args:
            path: Путь к файлу
            line: Начальная строка (1-based, опционально)
            limit: Максимум строк для чтения (опционально)

        Returns:
            Содержимое файла или диапазона строк

        Raises:
            FileNotFoundError: Файл не найден
            ValueError: Некорректный путь или не файл
            IOError: Ошибка чтения
        """
        file_path = self._validate_path(path)

        if not file_path.exists():
            logger.warning("file_not_found", path=path)
            raise FileNotFoundError(f"File not found: {path}")

        if not file_path.is_file():
            logger.warning("not_a_file", path=path)
            raise ValueError(f"Not a file: {path}")

        try:
            async with aiofiles.open(file_path, encoding="utf-8") as f:
                if line is None and limit is None:
                    # Читать весь файл
                    content = await f.read()
                else:
                    # Читать построчно с учетом диапазона
                    lines = await f.readlines()
                    start = (line - 1) if line else 0
                    end = start + limit if limit else None
                    content = "".join(lines[start:end])

            logger.info(
                "file_read_successfully",
                path=path,
                size=len(content),
                line=line,
                limit=limit,
            )
            return content
        except Exception as e:
            logger.error("file_read_error", path=path, error=str(e))
            raise OSError(f"Error reading file {path}: {e}") from e

    async def write_text_file(self, path: str, content: str) -> bool:
        """Записать текстовый файл.

        Создает родительские директории если необходимо.

        Args:
            path: Путь к файлу
            content: Содержимое для записи

        Returns:
            True при успешной записи

        Raises:
            ValueError: Некорректный путь
            IOError: Ошибка записи
        """
        file_path = self._validate_path(path)

        try:
            # Создать родительские директории если нужно
            file_path.parent.mkdir(parents=True, exist_ok=True)

            async with aiofiles.open(file_path, mode="w", encoding="utf-8") as f:
                await f.write(content)

            logger.info(
                "file_written_successfully",
                path=path,
                size=len(content),
            )
            return True
        except Exception as e:
            logger.error("file_write_error", path=path, error=str(e))
            raise OSError(f"Error writing file {path}: {e}") from e

    def read_text_file_sync(
        self,
        path: str,
        line: int | None = None,
        limit: int | None = None,
    ) -> str:
        """Прочитать текстовый файл синхронно.

        Поддерживает чтение диапазона строк через параметры line и limit.

        Args:
            path: Путь к файлу
            line: Начальная строка (1-based, опционально)
            limit: Максимум строк для чтения (опционально)

        Returns:
            Содержимое файла или диапазона строк

        Raises:
            FileNotFoundError: Файл не найден
            ValueError: Некорректный путь или не файл
            IOError: Ошибка чтения
        """
        file_path = self._validate_path(path)

        if not file_path.exists():
            logger.warning("file_not_found", path=path)
            raise FileNotFoundError(f"File not found: {path}")

        if not file_path.is_file():
            logger.warning("not_a_file", path=path)
            raise ValueError(f"Not a file: {path}")

        try:
            with open(file_path, encoding="utf-8") as f:
                if line is None and limit is None:
                    # Читать весь файл
                    content = f.read()
                else:
                    # Читать построчно с учетом диапазона
                    lines = f.readlines()
                    start = (line - 1) if line else 0
                    end = start + limit if limit else None
                    content = "".join(lines[start:end])

            logger.info(
                "file_read_successfully_sync",
                path=path,
                size=len(content),
                line=line,
                limit=limit,
            )
            return content
        except Exception as e:
            logger.error("file_read_error_sync", path=path, error=str(e))
            raise OSError(f"Error reading file {path}: {e}") from e

    def write_text_file_sync(self, path: str, content: str) -> bool:
        """Записать текстовый файл синхронно.

        Создает родительские директории если необходимо.

        Args:
            path: Путь к файлу
            content: Содержимое для записи

        Returns:
            True при успешной записи

        Raises:
            ValueError: Некорректный путь
            IOError: Ошибка записи
        """
        file_path = self._validate_path(path)

        try:
            # Создать родительские директории если нужно
            file_path.parent.mkdir(parents=True, exist_ok=True)

            with open(file_path, mode="w", encoding="utf-8") as f:
                f.write(content)

            logger.info(
                "file_written_successfully_sync",
                path=path,
                size=len(content),
            )
            return True
        except Exception as e:
            logger.error("file_write_error_sync", path=path, error=str(e))
            raise OSError(f"Error writing file {path}: {e}") from e
