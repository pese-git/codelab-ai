"""ChatViewModel для управления чатом и prompt-turn.

Отвечает за:
- Управление сообщениями и tool calls в чате
- Отправку prompts и обработку responses
- Обработку разрешений пользователя
- Отслеживание статуса streaming
"""

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codelab.client.presentation.base_view_model import BaseViewModel
from codelab.client.presentation.observable import Observable, ObservableCommand


@dataclass
class PermissionRequest:
    """Запрос разрешения от сервера."""

    request_id: str
    session_id: str
    action: str
    resource: str
    description: str = ""


@dataclass
class ChatSessionState:
    """Состояние чата, привязанное к конкретной сессии."""

    messages: list[Any]
    tool_calls: list[Any]
    pending_permissions: list[Any]
    streaming_text: str
    is_streaming: bool
    last_stop_reason: str | None
    replay_updates: list[dict[str, Any]]


class ChatViewModel(BaseViewModel):
    """ViewModel для управления чатом в активной сессии.

    Хранит состояние чата:
    - messages: история сообщений
    - tool_calls: список tool calls
    - pending_permissions: запросы разрешений в ожидании
    - is_streaming: флаг активного streaming

    Пример использования:
        >>> coordinator = SessionCoordinator(...)
        >>> vm = ChatViewModel(coordinator, event_bus)
        >>>
        >>> # Подписаться на сообщения
        >>> vm.messages.subscribe(lambda m: print(f"Messages: {m}"))
        >>>
        >>> # Отправить prompt
        >>> await vm.send_prompt_cmd.execute("session_1", "Привет!")
        >>>
        >>> # Обработать разрешение
        >>> await vm.approve_permission_cmd.execute(
        ...     "session_1",
        ...     "permission_123",
        ...     approved=True
        ... )
    """

    def __init__(
        self,
        coordinator: Any,  # SessionCoordinator
        event_bus: Any | None = None,
        logger: Any | None = None,
        history_dir: Path | str | None = None,
        fs_executor: Any | None = None,  # FileSystemExecutor
        terminal_executor: Any | None = None,  # TerminalExecutor
        plan_vm: Any | None = None,  # PlanViewModel для обработки plan updates
    ) -> None:
        """Инициализировать ChatViewModel.

        Args:
            coordinator: SessionCoordinator для работы с prompt-turn
            event_bus: EventBus для публикации/подписки на события
            logger: Logger для логирования
            history_dir: Директория локального persistence истории
                (приоритет: history_dir -> CODELAB_CLIENT_HISTORY_DIR -> ~/.codelab/data/history)
            fs_executor: FileSystemExecutor для обработки fs/* callbacks (синхронно)
            terminal_executor: TerminalExecutor для обработки terminal/* callbacks (синхронно)
            plan_vm: PlanViewModel для обработки plan updates из session/update
        """
        super().__init__(event_bus, logger)
        self.coordinator = coordinator
        self._fs_executor = fs_executor
        self._terminal_executor = terminal_executor
        self._plan_vm = plan_vm

        # Локальный storage истории нужен для восстановления UI без network roundtrip.
        # Порядок приоритета: явный аргумент -> переменная окружения -> путь по умолчанию.
        env_history_dir = os.getenv("CODELAB_CLIENT_HISTORY_DIR")
        if history_dir is not None:
            resolved_history_dir = Path(history_dir)
        elif env_history_dir:
            resolved_history_dir = Path(env_history_dir)
        else:
            resolved_history_dir = Path.home() / ".codelab" / "data" / "history"
        self._history_dir = resolved_history_dir
        try:
            self._history_dir.mkdir(parents=True, exist_ok=True)
            self.logger.info(
                "chat_history_storage_initialized",
                history_dir=str(self._history_dir.resolve()),
            )
        except OSError as error:
            self.logger.warning(
                "chat_history_dir_unavailable",
                history_dir=str(self._history_dir),
                error=str(error),
            )

        # Observable свойства
        self.messages: Observable[list[Any]] = Observable([])
        self.tool_calls: Observable[list[Any]] = Observable([])
        self.is_streaming: Observable[bool] = Observable(False)
        self.pending_permissions: Observable[list[Any]] = Observable([])
        self.streaming_text: Observable[str] = Observable("")
        self.last_stop_reason: Observable[str | None] = Observable(None)

        # Активная сессия и кэш UI-состояния по session_id.
        self._active_session_id: str | None = None
        self._session_states: dict[str, ChatSessionState] = {}

        # Observable команды
        self.send_prompt_cmd = ObservableCommand(self._send_prompt)
        self.cancel_prompt_cmd = ObservableCommand(self._cancel_prompt)
        self.approve_permission_cmd = ObservableCommand(self._approve_permission)
        self.reject_permission_cmd = ObservableCommand(self._reject_permission)
        self.clear_chat_cmd = ObservableCommand(self._clear_chat)

        # Подписываемся на события (если EventBus доступен)
        try:
            from codelab.client.domain.events import (
                ErrorOccurredEvent,
                PermissionRequestedEvent,
                PromptCompletedEvent,
                PromptStartedEvent,
            )

            self.on_event(PromptStartedEvent, self._handle_prompt_started)
            self.on_event(PromptCompletedEvent, self._handle_prompt_completed)
            self.on_event(PermissionRequestedEvent, self._handle_permission_requested)
            self.on_event(ErrorOccurredEvent, self._handle_error_occurred)
        except ImportError:
            self.logger.debug("DomainEvents not available, skipping event subscriptions")

    async def _send_prompt(self, session_id: str, prompt_text: str, **kwargs: Any) -> None:
        """Отправить prompt в сессию.

        Args:
            session_id: ID сессии
            prompt_text: Текст prompt
            **kwargs: Дополнительные параметры
        """
        if not session_id:
            self.logger.warning("Cannot send prompt: session_id is empty")
            return

        # Гарантируем что prompt отправляется в активную сессию
        # и обновления пишутся в её состояние.
        self.set_active_session(session_id)

        self._set_streaming_state(session_id, is_streaming=True, clear_text=True)
        self._set_last_stop_reason(session_id, None)

        try:
            # Build terminal lifecycle callbacks backed by the sync executor.
            # Results are cached by terminal_id so the multi-step protocol
            # (create → output → wait_for_exit → release) maps onto a single
            # blocking execute() call made on terminal/create.
            terminal_callbacks: dict[str, Any] = {}
            if self._terminal_executor is not None:
                _results: dict[str, dict[str, Any]] = {}
                _executor = self._terminal_executor

                def _on_terminal_create(command: str) -> str:
                    tid = str(uuid.uuid4())
                    _results[tid] = _executor.execute(command)
                    return tid

                def _on_terminal_output(terminal_id: str) -> dict[str, Any]:
                    r = _results.get(terminal_id, {})
                    return {
                        "output": r.get("output", ""),
                        "isComplete": True,
                        "exitCode": r.get("exit_code"),
                    }

                def _on_terminal_wait_for_exit(
                    terminal_id: str,
                ) -> tuple[int | None, str | None]:
                    r = _results.get(terminal_id, {})
                    return (r.get("exit_code"), r.get("output", ""))

                def _on_terminal_release(terminal_id: str) -> None:
                    _results.pop(terminal_id, None)

                def _on_terminal_kill(terminal_id: str) -> bool:
                    return _results.pop(terminal_id, None) is not None

                terminal_callbacks = {
                    "on_terminal_create": _on_terminal_create,
                    "on_terminal_output": _on_terminal_output,
                    "on_terminal_wait_for_exit": _on_terminal_wait_for_exit,
                    "on_terminal_release": _on_terminal_release,
                    "on_terminal_kill": _on_terminal_kill,
                }

            # Отправить prompt через coordinator с callback для обработки обновлений
            # SessionCoordinator должен обработать updates и опубликовать события
            await self.coordinator.send_prompt(
                session_id,
                prompt_text,
                on_update=self._handle_session_update,
                on_fs_read=self._handle_fs_read,
                on_fs_write=self._handle_fs_write,
                **terminal_callbacks,
                **kwargs,
            )

            # Гарантированное добавление streaming текста в историю после завершения
            # (на случай, если PromptCompletedEvent не был опубликован)
            session_state = self._get_or_create_session_state(session_id)
            streaming_text = session_state.streaming_text
            if streaming_text:
                session_state.messages.append({"role": "assistant", "content": streaming_text})
                session_state.streaming_text = ""
                session_state.is_streaming = False
                self._session_states[session_id] = session_state
                self._persist_messages_to_local_storage(
                    session_id,
                    session_state.messages,
                    replay_updates=session_state.replay_updates,
                )
                if self._active_session_id == session_id:
                    self.messages.value = list(session_state.messages)
                    self.streaming_text.value = ""
                    self.is_streaming.value = False
                self.logger.info(
                    "Agent response added to message history (fallback)",
                    text_length=len(streaming_text),
                )

        except Exception as e:
            self.logger.exception("Error sending prompt", error=str(e))
            raise
        finally:
            # Очищаем streaming состояние
            self._set_streaming_state(session_id, is_streaming=False, clear_text=True)

    def _handle_session_update(self, update_data: dict[str, Any]) -> None:
        """Обработать session/update от сервера.

        Обрабатывает различные типы обновлений сессии:
        - agent_message_chunk: добавляет текст ответа агента к streaming_text
        - user_message_chunk: обрабатывает фрагменты сообщений пользователя
        - session_info_update: обновляет информацию о сессии
        - и другие типы согласно протоколу ACP

        Args:
            update_data: Данные обновления сессии от сервера
        """
        try:
            params = update_data.get("params", {})
            update = params.get("update", {})
            session_update_type = update.get("sessionUpdate")
            session_id = params.get("sessionId")
            target_session_id = (
                session_id if isinstance(session_id, str) else self._active_session_id
            )

            # Кэшируем все session/update события, чтобы можно было восстановить
            # состояние ChatView даже для типов обновлений, которые не рендерим как сообщения.
            if target_session_id is not None:
                state = self._get_or_create_session_state(target_session_id)
                state.replay_updates.append(update_data)
                self._session_states[target_session_id] = state
                self._persist_messages_to_local_storage(
                    target_session_id,
                    state.messages,
                    replay_updates=state.replay_updates,
                )

            self.logger.debug(
                "session_update_received",
                update_type=session_update_type,
                update=update,
            )

            # Обработка agent_message_chunk - добавляем текст ответа агента
            if session_update_type == "agent_message_chunk":
                content = update.get("content", {})
                text = content.get("text", "")

                if text:
                    # Добавляем текст в состояние той сессии, откуда пришёл update.
                    if target_session_id is not None:
                        if self._is_system_ack_chunk(text):
                            self.add_message("system", text, session_id=target_session_id)
                            return
                        self._append_streaming_text_to_session(target_session_id, text)

                    self.logger.debug("agent_message_chunk_processed", text_length=len(text))

            # Обработка user_message_chunk - добавляем сообщения пользователя в историю
            elif session_update_type == "user_message_chunk":
                content = update.get("content", {})
                text = content.get("text", "")

                if text and target_session_id is not None:
                    # Добавляем сообщение пользователя в состояние сессии.
                    state = self._get_or_create_session_state(target_session_id)
                    state.messages.append({"role": "user", "content": text})
                    self._session_states[target_session_id] = state

                    # Синхронизируем с UI если это активная сессия.
                    if self._active_session_id == target_session_id:
                        self.messages.value = list(state.messages)

                    # Сохраняем в локальное хранилище.
                    self._persist_messages_to_local_storage(
                        target_session_id,
                        state.messages,
                        replay_updates=state.replay_updates,
                    )

                    self.logger.debug("user_message_chunk_processed", text_length=len(text))

            # Обработка tool_call - отслеживание статуса выполнения инструмента
            elif session_update_type == "tool_call":
                tool_call_id = update.get("toolCallId")
                tool_title = update.get("title")
                tool_status = update.get("status")
                tool_kind = update.get("kind")

                if target_session_id is not None and tool_call_id:
                    self.logger.info(
                        "tool_call_status_changed",
                        session_id=target_session_id,
                        tool_call_id=tool_call_id,
                        tool_name=tool_title,
                        status=tool_status,
                        kind=tool_kind,
                    )
                    
                    # Добавляем tool call в состояние сессии
                    state = self._get_or_create_session_state(target_session_id)
                    tool_call_dict = {
                        "toolCallId": tool_call_id,
                        "title": tool_title,
                        "kind": tool_kind,
                        "status": tool_status,
                    }
                    # Обновляем existing tool call или добавляем новый
                    state.tool_calls = [
                        tc if tc.get("toolCallId") != tool_call_id else tool_call_dict
                        for tc in state.tool_calls
                    ]
                    if tool_call_id not in [tc.get("toolCallId") for tc in state.tool_calls]:
                        state.tool_calls.append(tool_call_dict)
                    
                    self._session_states[target_session_id] = state
                    
                    # Синхронизируем с UI если это активная сессия
                    if self._active_session_id == target_session_id:
                        self.tool_calls.value = list(state.tool_calls)

            elif session_update_type == "tool_call_result":
                tool_call_id = update.get("toolCallId")
                result = update.get("result")

                if target_session_id is not None and tool_call_id:
                    self.logger.info(
                        "tool_call_result_received",
                        session_id=target_session_id,
                        tool_call_id=tool_call_id,
                        has_result=bool(result),
                    )
            
            # Обработка tool_call_update - обновление статуса существующего tool call
            elif session_update_type == "tool_call_update":
                tool_call_id = update.get("toolCallId")
                tool_status = update.get("status")
                tool_title = update.get("title")

                if target_session_id is not None and tool_call_id:
                    self.logger.info(
                        "tool_call_status_update",
                        session_id=target_session_id,
                        tool_call_id=tool_call_id,
                        new_status=tool_status,
                    )
                    
                    # Обновляем статус существующего tool call в состоянии
                    # ВАЖНО: создаем новые копии словарей, чтобы Observable
                    # обнаружил изменение (сравнение по значению, а не ссылке)
                    state = self._get_or_create_session_state(target_session_id)
                    updated_tool_calls = []
                    for tc in state.tool_calls:
                        if tc.get("toolCallId") == tool_call_id:
                            # Создаём новый словарь с обновлёнными полями
                            updated_tc = {**tc}
                            if tool_status:
                                updated_tc["status"] = tool_status
                            if tool_title:
                                updated_tc["title"] = tool_title
                            updated_tool_calls.append(updated_tc)
                        else:
                            updated_tool_calls.append(tc)
                    state.tool_calls = updated_tool_calls
                    self._session_states[target_session_id] = state

                    # Синхронизируем с UI если это активная сессия
                    if self._active_session_id == target_session_id:
                        self.tool_calls.value = updated_tool_calls

            # Обработка plan - обновление плана агента через PlanViewModel
            elif session_update_type == "plan":
                entries = update.get("entries", [])
                self.logger.info(
                    "plan_session_update_received",
                    session_id=target_session_id,
                    entries_count=len(entries),
                    has_plan_vm=self._plan_vm is not None,
                    raw_entries=entries[:2] if entries else None,  # First 2 for debug
                )

                if self._plan_vm is not None and entries:
                    # Форматируем план для отображения в UI
                    plan_lines = ["План:"]
                    for entry in entries:
                        content = entry.get("content", "")
                        priority = entry.get("priority", "medium")
                        status = entry.get("status", "pending")
                        plan_lines.append(f"- [{status}] ({priority}) {content}")
                    plan_text = "\n".join(plan_lines)
                    self._plan_vm.set_plan(plan_text)

                    self.logger.info(
                        "plan_update_received",
                        session_id=target_session_id,
                        entries_count=len(entries),
                    )

        except Exception as e:
            self.logger.error(
                "Error handling session update",
                error=str(e),
                update_data=update_data,
            )

    async def _cancel_prompt(self, session_id: str) -> None:
        """Отменить текущий prompt.

        Args:
            session_id: ID сессии
        """
        if not session_id:
            self.logger.warning("Cannot cancel prompt: session_id is empty")
            return

        try:
            self.logger.info("Canceling prompt", session_id=session_id)
            await self.coordinator.cancel_prompt(session_id)
            self.is_streaming.value = False
        except Exception as e:
            self.logger.exception("Error canceling prompt", error=str(e))
            raise

    async def _approve_permission(
        self,
        session_id: str,
        permission_id: str,
        **kwargs: Any,
    ) -> None:
        """Утвердить разрешение.

        Args:
            session_id: ID сессии
            permission_id: ID разрешения
            **kwargs: Дополнительные параметры
        """
        try:
            self.logger.info(
                "Approving permission",
                session_id=session_id,
                permission_id=permission_id,
            )
            await self.coordinator.handle_permission(
                session_id,
                permission_id,
                approved=True,
                **kwargs,
            )
            # Удалить из pending
            self._remove_pending_permission(permission_id)
        except Exception as e:
            self.logger.exception("Error approving permission", error=str(e))
            raise

    async def _reject_permission(
        self,
        session_id: str,
        permission_id: str,
        **kwargs: Any,
    ) -> None:
        """Отклонить разрешение.

        Args:
            session_id: ID сессии
            permission_id: ID разрешения
            **kwargs: Дополнительные параметры
        """
        try:
            self.logger.info(
                "Rejecting permission",
                session_id=session_id,
                permission_id=permission_id,
            )
            await self.coordinator.handle_permission(
                session_id,
                permission_id,
                approved=False,
                **kwargs,
            )
            # Удалить из pending
            self._remove_pending_permission(permission_id)
        except Exception as e:
            self.logger.exception("Error rejecting permission", error=str(e))
            raise

    async def _clear_chat(self) -> None:
        """Очистить чат (все сообщения и tool calls)."""
        self.messages.value = []
        self.tool_calls.value = []
        self.pending_permissions.value = []
        self.streaming_text.value = ""
        self.last_stop_reason.value = None
        self._persist_active_state()
        self.logger.info("Chat cleared")

    def _handle_fs_read(self, path: str) -> str:
        """Обработать fs/read_text_file от агента (синхронный).

        Используется синхронный метод FileSystemExecutor напрямую.

        Args:
            path: Путь к файлу для чтения

        Returns:
            Содержимое файла или пустая строка в случае ошибки
        """
        try:
            session_id = self._active_session_id
            if not session_id:
                self.logger.warning("fs_read_no_active_session", path=path)
                return ""

            # Проверяем наличие executor'а перед использованием
            if self._fs_executor is None:
                self.logger.warning("fs_executor_not_initialized", path=path)
                return ""

            # Используем синхронный метод executor напрямую
            content = self._fs_executor.read_text_file_sync(path)
            self.logger.debug("fs_read_success", path=path, content_size=len(content))
            return content
        except Exception as e:
            self.logger.error("fs_read_error", path=path, error=str(e))
            return ""

    def _handle_fs_write(self, path: str, content: str) -> bool:
        """Обработать fs/write_text_file от агента (синхронный).

        Используется синхронный метод FileSystemExecutor напрямую.

        Args:
            path: Путь к файлу для записи
            content: Содержимое для записи

        Returns:
            True если запись успешна, False в случае ошибки
        """
        try:
            session_id = self._active_session_id
            if not session_id:
                self.logger.warning("fs_write_no_active_session", path=path)
                return False

            # Проверяем наличие executor'а перед использованием
            if self._fs_executor is None:
                self.logger.warning("fs_executor_not_initialized", path=path)
                return False

            # Используем синхронный метод executor напрямую
            self._fs_executor.write_text_file_sync(path, content)
            self.logger.debug("fs_write_success", path=path, content_size=len(content))
            return True
        except Exception as e:
            self.logger.error("fs_write_error", path=path, error=str(e))
            return False

    def _handle_terminal_execute(self, command: str, cwd: str | None = None) -> dict[str, Any]:
        """Обработать terminal/execute от агента (синхронный).

        Используется синхронный метод TerminalExecutor напрямую.

        Args:
            command: Команда для выполнения
            cwd: Рабочая директория (опционально)

        Returns:
            Словарь с результатом выполнения (success, output, exit_code)
        """
        try:
            session_id = self._active_session_id
            if not session_id:
                self.logger.warning("terminal_execute_no_active_session", command=command)
                return {"success": False, "error": "No active session"}

            # Проверяем наличие executor'а перед использованием
            if self._terminal_executor is None:
                self.logger.warning("terminal_executor_not_initialized", command=command)
                return {
                    "success": False,
                    "error": "Terminal executor not initialized",
                }

            # Используем синхронный метод executor напрямую
            result = self._terminal_executor.execute(command, cwd=cwd)
            self.logger.debug(
                "terminal_execute_result",
                command=command,
                exit_code=result.get("exit_code"),
                success=result.get("success"),
            )
            return result
        except Exception as e:
            self.logger.error("terminal_execute_error", command=command, error=str(e))
            return {"success": False, "error": str(e)}

    def add_message(self, role: str, content: str, session_id: str | None = None) -> None:
        """Добавить сообщение в чат.

        Args:
            role: Роль ("user", "assistant", "system")
            content: Содержимое сообщения
            session_id: ID сессии, для которой добавляется сообщение
        """
        if session_id is not None:
            state = self._get_or_create_session_state(session_id)
            state.messages.append({"role": role, "content": content})
            self._session_states[session_id] = state
            self._persist_messages_to_local_storage(
                session_id,
                state.messages,
                replay_updates=state.replay_updates,
            )
            if self._active_session_id == session_id:
                self.messages.value = list(state.messages)
        else:
            messages = self.messages.value
            messages.append({"role": role, "content": content})
            self.messages.value = list(messages)
            self._persist_active_state()
        self.logger.debug("Message added", role=role, content_length=len(content))

    def append_streaming_text(self, text: str) -> None:
        """Добавить текст к потоковому выводу.

        Args:
            text: Текст для добавления
        """
        self.streaming_text.value += text
        self._persist_active_state()

    def _remove_pending_permission(self, permission_id: str) -> None:
        """Удалить разрешение из pending.

        Args:
            permission_id: ID разрешения
        """
        perms = self.pending_permissions.value
        self.pending_permissions.value = [p for p in perms if p.request_id != permission_id]
        self._persist_active_state()

    def set_active_session(self, session_id: str | None) -> None:
        """Переключает ChatViewModel на состояние выбранной сессии."""

        # Сохраняем текущее состояние перед переключением.
        self._persist_active_state()
        self._active_session_id = session_id

        if session_id is None:
            self.messages.value = []
            self.tool_calls.value = []
            self.pending_permissions.value = []
            self.streaming_text.value = ""
            self.is_streaming.value = False
            self.last_stop_reason.value = None
            return

        state = self._get_or_create_session_state(session_id)

        self.messages.value = list(state.messages)
        self.tool_calls.value = list(state.tool_calls)
        self.pending_permissions.value = list(state.pending_permissions)
        self.streaming_text.value = state.streaming_text
        self.is_streaming.value = state.is_streaming
        self.last_stop_reason.value = state.last_stop_reason

    def restore_session_from_replay(
        self,
        session_id: str,
        replay_updates: list[dict[str, Any]],
    ) -> None:
        """Восстанавливает состояние чата по replay updates от `session/load`.

        Args:
            session_id: ID сессии, для которой применяем replay
            replay_updates: Список raw-уведомлений `session/update`
        """

        self.logger.info(
            "restore_session_from_replay_started",
            session_id=session_id,
            replay_updates_count=len(replay_updates),
        )

        # Полная пересборка сообщений из server-side истории исключает
        # зависимость от локального history-кэша клиента.
        rebuilt_messages: list[dict[str, str]] = []
        session_replay_updates: list[dict[str, Any]] = []

        for idx, update_data in enumerate(replay_updates):
            params = update_data.get("params", {})
            if params.get("sessionId") != session_id:
                self.logger.debug(
                    "restore_skipping_wrong_session",
                    idx=idx,
                    expected_session=session_id,
                    actual_session=params.get("sessionId"),
                )
                continue

            session_replay_updates.append(update_data)

            update = params.get("update", {})
            update_type = update.get("sessionUpdate")
            content = update.get("content")

            self.logger.debug(
                "restore_processing_update",
                idx=idx,
                update_type=update_type,
                has_content=content is not None,
                content_type=type(content).__name__ if content is not None else None,
            )

            if not isinstance(content, dict):
                self.logger.debug(
                    "restore_skipping_no_content",
                    idx=idx,
                    update_type=update_type,
                )
                continue

            text = content.get("text")
            if not isinstance(text, str) or text == "":
                self.logger.debug(
                    "restore_skipping_no_text",
                    idx=idx,
                    update_type=update_type,
                    has_text=text is not None,
                )
                continue

            if update_type == "user_message_chunk":
                rebuilt_messages.append({"role": "user", "content": text})
                self.logger.debug(
                    "restore_added_user_message",
                    idx=idx,
                    text_length=len(text),
                )
                continue
            if update_type == "agent_message_chunk":
                role = "system" if self._is_system_ack_chunk(text) else "assistant"
                rebuilt_messages.append({"role": role, "content": text})
                self.logger.debug(
                    "restore_added_agent_message",
                    idx=idx,
                    role=role,
                    text_length=len(text),
                )

        # Записываем пересобранное состояние в кэш конкретной сессии.
        state = self._get_or_create_session_state(session_id)
        state.messages = rebuilt_messages
        state.streaming_text = ""
        state.is_streaming = False
        state.replay_updates = session_replay_updates
        self._session_states[session_id] = state
        self._persist_messages_to_local_storage(
            session_id,
            rebuilt_messages,
            replay_updates=session_replay_updates,
        )

        # Если сессия активна в UI, синхронизируем observables сразу.
        if self._active_session_id == session_id:
            self.messages.value = list(rebuilt_messages)
            self.streaming_text.value = ""
            self.is_streaming.value = False

        self.logger.info(
            "restore_session_from_replay_completed",
            session_id=session_id,
            rebuilt_messages_count=len(rebuilt_messages),
            is_active_session=self._active_session_id == session_id,
        )

    def _persist_active_state(self) -> None:
        """Сохраняет текущее состояние чата для активной сессии."""

        if self._active_session_id is None:
            return

        existing_state = self._session_states.get(self._active_session_id)
        replay_updates = [] if existing_state is None else list(existing_state.replay_updates)

        state = ChatSessionState(
            messages=list(self.messages.value),
            tool_calls=list(self.tool_calls.value),
            pending_permissions=list(self.pending_permissions.value),
            streaming_text=self.streaming_text.value,
            is_streaming=self.is_streaming.value,
            last_stop_reason=self.last_stop_reason.value,
            replay_updates=replay_updates,
        )
        self._session_states[self._active_session_id] = state
        self._persist_messages_to_local_storage(
            self._active_session_id,
            state.messages,
            replay_updates=state.replay_updates,
        )

    def _get_or_create_session_state(self, session_id: str) -> ChatSessionState:
        """Возвращает состояние сессии или создаёт пустое."""

        state = self._session_states.get(session_id)
        if state is not None:
            return state

        persisted_messages = self._load_messages_from_local_storage(session_id)
        persisted_replay_updates = self._load_replay_updates_from_local_storage(session_id)
        if persisted_replay_updates:
            persisted_messages = self._rebuild_messages_from_replay(
                session_id,
                persisted_replay_updates,
            )

        state = ChatSessionState(
            messages=persisted_messages,
            tool_calls=[],
            pending_permissions=[],
            streaming_text="",
            is_streaming=False,
            last_stop_reason=None,
            replay_updates=persisted_replay_updates,
        )
        self._session_states[session_id] = state
        return state

    def _history_file_path(self, session_id: str) -> Path:
        """Возвращает путь JSON-файла истории для указанной сессии."""

        safe_session_id = session_id.replace("/", "_").replace("\\", "_")
        return self._history_dir / f"{safe_session_id}.json"

    def _persist_messages_to_local_storage(
        self,
        session_id: str,
        messages: list[Any],
        replay_updates: list[dict[str, Any]] | None = None,
    ) -> None:
        """Сохраняет сообщения сессии в локальный JSON storage."""

        serializable_messages = [
            message
            for message in messages
            if isinstance(message, dict)
            and isinstance(message.get("role"), str)
            and isinstance(message.get("content"), str)
        ]
        file_path = self._history_file_path(session_id)
        payload: dict[str, Any] = {"messages": serializable_messages}
        if replay_updates is not None:
            payload["replay_updates"] = [
                update for update in replay_updates if isinstance(update, dict)
            ]
        try:
            file_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as error:
            self.logger.warning(
                "chat_history_save_failed",
                session_id=session_id,
                path=str(file_path),
                error=str(error),
            )

    def _load_messages_from_local_storage(self, session_id: str) -> list[dict[str, str]]:
        """Загружает сообщения сессии из локального JSON storage."""

        file_path = self._history_file_path(session_id)
        if not file_path.exists():
            return []

        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            self.logger.warning(
                "chat_history_load_failed",
                session_id=session_id,
                path=str(file_path),
                error=str(error),
            )
            return []

        raw_messages = payload.get("messages") if isinstance(payload, dict) else None
        if not isinstance(raw_messages, list):
            return []

        normalized_messages: list[dict[str, str]] = []
        for message in raw_messages:
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            content = message.get("content")
            if isinstance(role, str) and isinstance(content, str):
                normalized_messages.append({"role": role, "content": content})
        return normalized_messages

    def _load_replay_updates_from_local_storage(self, session_id: str) -> list[dict[str, Any]]:
        """Загружает replay updates сессии из локального JSON storage."""

        file_path = self._history_file_path(session_id)
        if not file_path.exists():
            return []

        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            self.logger.warning(
                "chat_history_load_failed",
                session_id=session_id,
                path=str(file_path),
                error=str(error),
            )
            return []

        raw_replay_updates = payload.get("replay_updates") if isinstance(payload, dict) else None
        if not isinstance(raw_replay_updates, list):
            return []

        return [update for update in raw_replay_updates if isinstance(update, dict)]

    def _rebuild_messages_from_replay(
        self,
        session_id: str,
        replay_updates: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        """Восстанавливает сообщения из кэшированных replay updates одной сессии."""

        rebuilt_messages: list[dict[str, str]] = []

        for update_data in replay_updates:
            params = update_data.get("params", {})
            if params.get("sessionId") != session_id:
                continue

            update = params.get("update", {})
            update_type = update.get("sessionUpdate")
            content = update.get("content")
            if not isinstance(content, dict):
                continue

            text = content.get("text")
            if not isinstance(text, str) or text == "":
                continue

            if update_type == "user_message_chunk":
                rebuilt_messages.append({"role": "user", "content": text})
            elif update_type == "agent_message_chunk":
                role = "system" if self._is_system_ack_chunk(text) else "assistant"
                rebuilt_messages.append({"role": role, "content": text})

        return rebuilt_messages

    def _append_streaming_text_to_session(self, session_id: str, text: str) -> None:
        """Добавляет streaming chunk в состояние указанной сессии."""

        state = self._get_or_create_session_state(session_id)
        state.streaming_text += text
        state.is_streaming = True
        self._session_states[session_id] = state

        if self._active_session_id == session_id:
            self.streaming_text.value = state.streaming_text
            self.is_streaming.value = True

    def _set_streaming_state(
        self, session_id: str, *, is_streaming: bool, clear_text: bool
    ) -> None:
        """Обновляет флаг streaming и буфер текста для сессии."""

        state = self._get_or_create_session_state(session_id)
        state.is_streaming = is_streaming
        if clear_text:
            state.streaming_text = ""
        self._session_states[session_id] = state

        if self._active_session_id == session_id:
            self.is_streaming.value = is_streaming
            if clear_text:
                self.streaming_text.value = ""
            return

        # Если завершили поток неактивной сессии, синхронизируем общий UI-флаг,
        # чтобы поле prompt не оставалось disabled после фонового завершения turn.
        if not is_streaming:
            any_streaming = any(
                state_item.is_streaming for state_item in self._session_states.values()
            )
            if not any_streaming:
                self.is_streaming.value = False

    def _set_last_stop_reason(self, session_id: str, stop_reason: str | None) -> None:
        """Сохраняет stop reason для сессии и синхронизирует активный UI."""

        state = self._get_or_create_session_state(session_id)
        state.last_stop_reason = stop_reason
        self._session_states[session_id] = state

        if self._active_session_id == session_id:
            self.last_stop_reason.value = stop_reason

    @staticmethod
    def _is_system_ack_chunk(text: str) -> bool:
        """Определяет служебный ACK chunk от сервера."""

        normalized = text.strip()
        return normalized.startswith("Processing with agent:")

    # Event handlers
    def _handle_prompt_started(self, event: Any) -> None:
        """Обработать начало prompt-turn.

        Args:
            event: PromptStartedEvent из EventBus
        """
        self.logger.debug(
            "Prompt started event received - CLEARING streaming_text",
            session_id=getattr(event, "session_id", "unknown"),
        )
        session_id = getattr(event, "session_id", None)
        if isinstance(session_id, str):
            self._set_streaming_state(session_id, is_streaming=True, clear_text=True)

    def _handle_prompt_completed(self, event: Any) -> None:
        """Обработать завершение prompt-turn.

        После завершения streaming сохраняет накопленный текст агента в историю сообщений.

        Args:
            event: PromptCompletedEvent из EventBus
        """
        self.logger.debug(
            "Prompt completed event received - STOPPING streaming",
            session_id=getattr(event, "session_id", "unknown"),
            stop_reason=getattr(event, "stop_reason", None),
            final_streaming_text_length=len(self.streaming_text.value),
        )

        session_id = getattr(event, "session_id", None)
        if not isinstance(session_id, str):
            return

        state = self._get_or_create_session_state(session_id)
        streaming_text = state.streaming_text
        if streaming_text:
            state.messages.append({"role": "assistant", "content": streaming_text})
            self._session_states[session_id] = state
            self._persist_messages_to_local_storage(
                session_id,
                state.messages,
                replay_updates=state.replay_updates,
            )
            if self._active_session_id == session_id:
                self.messages.value = list(state.messages)
            self.logger.debug(
                "Agent response saved to message history",
                text_length=len(streaming_text),
            )

        # Отключаем streaming и очищаем буфер
        self._set_streaming_state(session_id, is_streaming=False, clear_text=True)
        self._set_last_stop_reason(session_id, getattr(event, "stop_reason", None))

    def _handle_permission_requested(self, event: Any) -> None:
        """Обработать запрос разрешения.

        Args:
            event: PermissionRequestedEvent из EventBus
        """
        perm = PermissionRequest(
            request_id=getattr(event, "request_id", "unknown"),
            session_id=getattr(event, "session_id", "unknown"),
            action=getattr(event, "action", "unknown"),
            resource=getattr(event, "resource", "unknown"),
            description=getattr(event, "description", ""),
        )
        perms = self.pending_permissions.value
        self.pending_permissions.value = list(perms) + [perm]
        self._persist_active_state()
        self.logger.debug(
            "Permission requested event received",
            request_id=perm.request_id,
            action=perm.action,
        )

    def _handle_error_occurred(self, event: Any) -> None:
        """Обработать ошибку.

        Args:
            event: ErrorOccurredEvent из EventBus
        """
        session_id = getattr(event, "session_id", None)
        if isinstance(session_id, str):
            self._set_streaming_state(session_id, is_streaming=False, clear_text=False)
        else:
            self.is_streaming.value = False
            self._persist_active_state()
        error_msg = getattr(event, "error_message", "Unknown error")
        self.logger.error(
            "Error occurred event received",
            error_message=error_msg,
            error_type=getattr(event, "error_type", "unknown"),
        )
