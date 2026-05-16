"""JSON файловое хранилище для сессий ACP.

Использует Pydantic model_dump/model_validate для сериализации,
что устраняет ~250 строк ручного кода _serialize_* / _deserialize_*.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import aiofiles
from pydantic import ValidationError

from ..exceptions import StorageError
from ..protocol.state import SessionState
from .base import SessionStorage


class JsonFileStorage(SessionStorage):
    """Хранилище сессий в JSON файлах.

    Каждая сессия сохраняется в отдельный файл:
    {base_path}/{session_id}.json

    Использует Pydantic model_dump(mode="json") для сериализации
    и SessionState.model_validate() для десериализации.

    Пример использования:
        storage = JsonFileStorage(Path.home() / ".acp" / "sessions")
        await storage.save_session(session)
        loaded = await storage.load_session(session_id)
    """

    def __init__(self, base_path: Path | str) -> None:
        """Инициализирует хранилище.

        Args:
            base_path: Директория для хранения JSON файлов
        """
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _session_file_path(self, session_id: str) -> Path:
        """Возвращает путь к файлу сессии."""
        # Экранировать session_id для безопасности
        safe_id = session_id.replace("/", "_").replace("\\", "_").replace("..", "_")
        return self.base_path / f"{safe_id}.json"

    async def save_session(self, session: SessionState) -> None:
        """Сохраняет сессию в JSON файл.

        Использует Pydantic model_dump(mode="json") для корректной
        конвертации всех типов включая set → list.

        Args:
            session: Состояние сессии для сохранения.

        Raises:
            StorageError: При ошибке сохранения.
        """
        try:
            # Обновить временную метку
            session.updated_at = datetime.now(UTC).isoformat()
            file_path = self._session_file_path(session.session_id)

            # model_dump(mode="json") — корректно конвертирует все типы
            data = session.model_dump(mode="json")

            async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(data, indent=2, ensure_ascii=False))

        except Exception as e:
            raise StorageError(f"Failed to save session {session.session_id}: {e}") from e

    async def load_session(self, session_id: str) -> SessionState | None:
        """Загружает сессию из JSON файла.

        Использует SessionState.model_validate() для десериализации
        с автоматической миграцией схемы через model_validator.

        Args:
            session_id: Идентификатор сессии.

        Returns:
            SessionState если найдена, None если не существует.

        Raises:
            StorageError: При ошибке загрузки.
        """
        try:
            file_path = self._session_file_path(session_id)
            if not file_path.exists():
                return None

            async with aiofiles.open(file_path, encoding="utf-8") as f:
                content = await f.read()

            data = json.loads(content)

            # model_validate автоматически применяет миграцию схемы
            session = SessionState.model_validate(data)
            return session

        except json.JSONDecodeError as e:
            raise StorageError(f"Corrupted session file {session_id}") from e
        except ValidationError as e:
            raise StorageError(f"Invalid session data {session_id}: {e}") from e
        except Exception as e:
            raise StorageError(f"Failed to load session {session_id}: {e}") from e

    async def delete_session(self, session_id: str) -> bool:
        """Удаляет JSON файл сессии.

        Args:
            session_id: Идентификатор сессии.

        Returns:
            True если сессия была удалена, False если не существовала.

        Raises:
            StorageError: При ошибке удаления.
        """
        try:
            file_path = self._session_file_path(session_id)
            if file_path.exists():
                file_path.unlink()
                return True
            return False
        except Exception as e:
            raise StorageError(f"Failed to delete session {session_id}: {e}") from e

    async def list_sessions(
        self,
        cwd: str | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> tuple[list[SessionState], str | None]:
        """Возвращает список сессий из файлов.

        Args:
            cwd: Фильтр по рабочей директории (опционально).
            cursor: Курсор для пагинации (session_id последней сессии предыдущей страницы).
            limit: Максимальное количество сессий на странице.

        Returns:
            Кортеж (список сессий, следующий курсор или None).

        Raises:
            StorageError: При ошибке получения списка.
        """
        try:
            # Загрузить все сессии
            sessions: list[SessionState] = []
            for file_path in self.base_path.glob("*.json"):
                session_id = file_path.stem
                session = await self.load_session(session_id)
                if session:
                    sessions.append(session)

            # Фильтрация по cwd
            if cwd:
                sessions = [s for s in sessions if s.cwd == cwd]

            # Сортировка по updated_at (новые первыми)
            sessions.sort(key=lambda s: s.updated_at, reverse=True)

            # Пагинация с курсором
            start_index = 0
            if cursor:
                for i, s in enumerate(sessions):
                    if s.session_id == cursor:
                        start_index = i + 1
                        break

            page = sessions[start_index : start_index + limit]
            next_cursor = (
                page[-1].session_id if len(sessions) > start_index + limit and page else None
            )

            return page, next_cursor

        except Exception as e:
            raise StorageError(f"Failed to list sessions: {e}") from e

    async def session_exists(self, session_id: str) -> bool:
        """Проверяет существование файла сессии.

        Args:
            session_id: Идентификатор сессии.

        Returns:
            True если сессия существует, False иначе.
        """
        return self._session_file_path(session_id).exists()
