"""SessionViewModel для управления сессиями.

Отвечает за:
- Загрузку и управление списком сессий
- Переключение между сессиями
- Создание новых сессий
- Обработку событий жизненного цикла сессий
"""

from typing import Any

from codelab.client.presentation.base_view_model import BaseViewModel
from codelab.client.presentation.observable import Observable, ObservableCommand


class SessionViewModel(BaseViewModel):
    """ViewModel для управления сессиями ACP.

    Хранит состояние сессий и команды для управления ими:
    - sessions: список доступных сессий
    - selected_session_id: ID выбранной сессии
    - is_loading_sessions: флаг загрузки
    - error_message: последняя ошибка

    Пример использования:
        >>> coordinator = SessionCoordinator(...)
        >>> vm = SessionViewModel(coordinator, event_bus)
        >>>
        >>> # Подписаться на изменения
        >>> vm.sessions.subscribe(lambda s: print(f"Sessions: {s}"))
        >>>
        >>> # Загрузить сессии
        >>> await vm.load_sessions_cmd.execute()
        >>>
        >>> # Создать новую сессию
        >>> await vm.create_session_cmd.execute("localhost", 8080)
        >>>
        >>> # Переключиться на сессию
        >>> await vm.switch_session_cmd.execute("session_id")
    """

    def __init__(
        self,
        coordinator: Any,  # SessionCoordinator
        event_bus: Any | None = None,
        logger: Any | None = None,
    ) -> None:
        """Инициализировать SessionViewModel.

        Args:
            coordinator: SessionCoordinator для работы с сессиями
            event_bus: EventBus для публикации/подписки на события
            logger: Logger для логирования
        """
        super().__init__(event_bus, logger)
        self.coordinator = coordinator

        # Observable свойства - с явной типизацией для type checker
        self.sessions: Observable[list[Any]] = Observable([])
        self.selected_session_id: Observable[str | None] = Observable(None)
        self.is_loading_sessions: Observable[bool] = Observable(False)
        self.error_message: Observable[str | None] = Observable(None)
        self.session_count: Observable[int] = Observable(0)

        # Observable команды
        self.load_sessions_cmd = ObservableCommand(self._load_sessions)
        self.create_session_cmd = ObservableCommand(self._create_session)
        self.switch_session_cmd = ObservableCommand(self._switch_session)
        self.delete_session_cmd = ObservableCommand(self._delete_session)

        # Подписываемся на события (если EventBus доступен)
        try:
            from codelab.client.domain.events import (
                SessionClosedEvent,
                SessionCreatedEvent,
                SessionInitializedEvent,
            )

            self.on_event(SessionCreatedEvent, self._handle_session_created)
            self.on_event(SessionInitializedEvent, self._handle_session_initialized)
            self.on_event(SessionClosedEvent, self._handle_session_closed)
        except ImportError:
            self.logger.debug("DomainEvents not available, skipping event subscriptions")

    async def _load_sessions(self) -> None:
        """Загрузить список сессий от coordinator.

        Обновляет sessions и session_count observables.
        """
        self.is_loading_sessions.value = True
        self.error_message.value = None

        try:
            sessions = await self.coordinator.list_sessions()
            self.sessions.value = sessions
            self.session_count.value = len(sessions)

            # Если текущий выбор отсутствует, автоматически выбираем первую сессию.
            current_selected_id = self.selected_session_id.value
            has_selected_session = any(
                self._extract_session_id(session) == current_selected_id for session in sessions
            )
            if sessions and not has_selected_session:
                first_session_id = self._extract_session_id(sessions[0])
                if first_session_id is not None:
                    self.selected_session_id.value = first_session_id

            self.logger.info(
                "Sessions loaded successfully",
                count=len(sessions),
            )
        except Exception as e:
            error_msg = f"Failed to load sessions: {str(e)}"
            self.error_message.value = error_msg
            self.logger.exception("Error loading sessions", error=str(e))
        finally:
            self.is_loading_sessions.value = False

    async def _create_session(self, host: str, port: int, **kwargs: Any) -> None:
        """Создать новую сессию.

        Args:
            host: Хост сервера
            port: Порт сервера
            **kwargs: Дополнительные параметры сессии (cwd, client_capabilities)
        """
        from pathlib import Path

        self.is_loading_sessions.value = True
        self.error_message.value = None

        # Используем текущую директорию как default для cwd
        cwd = kwargs.get("cwd") or str(Path.cwd())

        # DEBUG: Логируем переданные параметры
        self.logger.debug(
            "session_view_model_create_session_called",
            host=host,
            port=port,
            cwd=cwd,
            kwargs=kwargs,
        )

        try:
            # Передаем cwd и mcp_servers в координатор
            # Удаляем cwd и mcp_servers из kwargs, чтобы избежать дублирования параметра
            create_kwargs = {k: v for k, v in kwargs.items() if k not in ("cwd", "mcp_servers")}
            mcp_servers = kwargs.get("mcp_servers")
            result = await self.coordinator.create_session(
                host, port, cwd=cwd, mcp_servers=mcp_servers, **create_kwargs
            )

            # coordinator.create_session возвращает dict, преобразуем в объект для совместимости
            # Создаем простой объект для хранения результата сессии
            class SessionResult:
                def __init__(self, session_data: dict[str, Any]) -> None:
                    session_id = session_data.get("session_id")
                    self.id = session_id
                    self.session_id = session_id
                    self.sessionId = session_id  # camelCase для совместимости
                    # title используется для отображения в UI (sidebar)
                    self.title = f"Session {session_id[-8:]}" if session_id else "New Session"
                    self.server_capabilities = session_data.get("server_capabilities", {})
                    self.is_authenticated = session_data.get("is_authenticated", False)

            session = SessionResult(result)

            # Добавить новую сессию в список
            sessions = self.sessions.value + [session]
            self.sessions.value = sessions
            self.session_count.value = len(sessions)

            # Выбрать новую сессию
            self.selected_session_id.value = session.id

            self.logger.info(
                "Session created successfully",
                session_id=session.id,
                host=host,
                port=port,
            )
        except Exception as e:
            error_msg = f"Failed to create session: {str(e)}"
            self.error_message.value = error_msg
            self.logger.exception("Error creating session", error=str(e))
        finally:
            self.is_loading_sessions.value = False

    async def _switch_session(self, session_id: str) -> None:
        """Переключиться на другую сессию.

        Args:
            session_id: ID сессии для переключения
        """
        # Проверить что сессия существует
        session_exists = any(self._extract_session_id(s) == session_id for s in self.sessions.value)

        if not session_exists:
            error_msg = f"Session {session_id} not found"
            self.error_message.value = error_msg
            self.logger.warning(
                "Attempted to switch to non-existent session", session_id=session_id
            )
            return

        self.selected_session_id.value = session_id
        self.logger.info("Session switched", session_id=session_id)

    async def _delete_session(self, session_id: str) -> None:
        """Удалить сессию.

        Args:
            session_id: ID сессии для удаления
        """
        self.error_message.value = None

        try:
            await self.coordinator.delete_session(session_id)

            # Удалить сессию из списка
            sessions = [s for s in self.sessions.value if self._extract_session_id(s) != session_id]
            self.sessions.value = sessions
            self.session_count.value = len(sessions)

            # Если удалена выбранная сессия, выбрать первую оставшуюся или None
            if self.selected_session_id.value == session_id:
                self.selected_session_id.value = (
                    self._extract_session_id(sessions[0]) if sessions else None
                )

            self.logger.info("Session deleted successfully", session_id=session_id)
        except Exception as e:
            error_msg = f"Failed to delete session: {str(e)}"
            self.error_message.value = error_msg
            self.logger.exception("Error deleting session", error=str(e))

    def _handle_session_created(self, event: Any) -> None:
        """Обработать событие создания сессии.

        Args:
            event: SessionCreatedEvent из EventBus
        """
        self.logger.debug("Session created event received", session_id=event.session_id)
        # Logic может быть расширен в зависимости от Event структуры

    def _handle_session_initialized(self, event: Any) -> None:
        """Обработать событие инициализации сессии.

        Args:
            event: SessionInitializedEvent из EventBus
        """
        self.logger.debug(
            "Session initialized event received",
            session_id=event.session_id,
            capabilities=getattr(event, "capabilities", {}),
        )

    def _handle_session_closed(self, event: Any) -> None:
        """Обработать событие закрытия сессии.

        Args:
            event: SessionClosedEvent из EventBus
        """
        self.logger.debug(
            "Session closed event received",
            session_id=event.session_id,
            reason=getattr(event, "reason", "unknown"),
        )
        # Удалить закрытую сессию из списка
        sessions = [
            s for s in self.sessions.value if self._extract_session_id(s) != event.session_id
        ]
        if len(sessions) < len(self.sessions.value):
            self.sessions.value = sessions
            self.session_count.value = len(sessions)

    @staticmethod
    def _extract_session_id(session: Any) -> str | None:
        """Возвращает идентификатор сессии из разных форматов объекта."""

        if isinstance(session, dict):
            raw_id = session.get("sessionId") or session.get("id")
            return raw_id if isinstance(raw_id, str) else None

        for attribute_name in ("sessionId", "id"):
            if hasattr(session, attribute_name):
                raw_id = getattr(session, attribute_name)
                if isinstance(raw_id, str):
                    return raw_id
        return None
