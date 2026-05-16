"""Обработчик управления разрешениями и permission flow.

Содержит логику определения необходимости permission request, управления
permission policy, построения permission messages и обработки решений.
"""

from __future__ import annotations

from typing import Any

from ...messages import ACPMessage, JsonRpcId
from ..state import SessionState


class PermissionManager:
    """Управляет разрешениями и permission request flow.

    Инкапсулирует логику определения, нужен ли permission request,
    поиска remembered permissions, построения permission messages
    и обработки permission decisions.
    """

    # Спецификация всех доступных опций разрешения
    _PERMISSION_OPTIONS: list[dict[str, str]] = [
        {
            "optionId": "allow_once",
            "name": "Allow once",
            "kind": "allow_once",
        },
        {
            "optionId": "allow_always",
            "name": "Allow always",
            "kind": "allow_always",
        },
        {
            "optionId": "reject_once",
            "name": "Reject once",
            "kind": "reject_once",
        },
        {
            "optionId": "reject_always",
            "name": "Reject always",
            "kind": "reject_always",
        },
    ]

    def _resolve_policy(self, session: SessionState, tool_kind: str) -> str:
        """Разрешает политику для данного tool kind в единой точке.

        Args:
            session: Состояние сессии
            tool_kind: Категория tool

        Returns:
            'allow' если policy == 'allow_always'
            'reject' если policy == 'reject_always'
            'ask' если policy не установлена или неизвестна
        """
        match session.permission_policy.get(tool_kind):
            case "allow_always":
                return "allow"
            case "reject_always":
                return "reject"
            case _:
                return "ask"

    def should_request_permission(
        self,
        session: SessionState,
        tool_kind: str,
    ) -> bool:
        """Определяет, нужен ли permission request для данного tool kind.

        Returns:
            True если policy для tool_kind не установлена или равна 'ask'
            False если policy == 'allow_always' или 'reject_always'

        Args:
            session: Состояние сессии
            tool_kind: Категория tool (execute, read, write и т.д.)

        Returns:
            True если нужно запросить разрешение у пользователя
        """
        return self._resolve_policy(session, tool_kind) == "ask"

    def get_remembered_permission(
        self,
        session: SessionState,
        tool_kind: str,
    ) -> str:
        """Возвращает применяемое решение из permission_policy.

        Args:
            session: Состояние сессии
            tool_kind: Категория tool

        Returns:
            'allow' если policy == 'allow_always'
            'reject' если policy == 'reject_always'
            'ask' если policy не установлена или неизвестна
        """
        return self._resolve_policy(session, tool_kind)

    def build_permission_options(self) -> list[dict[str, Any]]:
        """Возвращает варианты решения для permission request.

        Returns:
            Список опций с optionId, name и kind
        """
        # Возвращаем копию, чтобы не модифицировать оригинал
        return [opt.copy() for opt in self._PERMISSION_OPTIONS]

    def build_permission_request(
        self,
        session: SessionState,
        session_id: str,
        tool_call_id: str,
        tool_title: str,
        tool_kind: str,
    ) -> ACPMessage:
        """Строит session/request_permission message.

        Создает RPC request для запроса разрешения пользователя на выполнение
        инструмента. Включает все доступные опции (allow_once, allow_always,
        reject_once, reject_always).

        Args:
            session: Состояние сессии (может быть обновлено с permission_request_id)
            session_id: ID сессии
            tool_call_id: ID связанного tool call
            tool_title: Название инструмента для отображения пользователю
            tool_kind: Категория инструмента

        Returns:
            ACPMessage типа request с методом "session/request_permission"
        """
        options = self.build_permission_options()

        # Формируем `toolCall` как ToolCallUpdate-объект по спецификации ACP.
        # Для совместимости UI передаем также title/kind, хотя обязателен только ID.
        msg = ACPMessage.request(
            "session/request_permission",
            {
                "sessionId": session_id,
                "toolCall": {
                    "toolCallId": tool_call_id,
                    "title": tool_title,
                    "kind": tool_kind,
                },
                "options": options,
            },
        )

        # Сохраняем ID permission request в active turn для корреляции response
        if session.active_turn is not None and msg.id is not None:
            session.active_turn.permission_request_id = msg.id
            session.active_turn.permission_tool_call_id = tool_call_id

        return msg

    def extract_permission_outcome(self, result: Any) -> str | None:
        """Извлекает outcome из response на session/request_permission.

        Поддерживает текущий ACP shape (`{"outcome": {"outcome": ...}}`) и
        legacy-вариант (`{"outcome": ...}`) для обратной совместимости.

        Args:
            result: Результат от клиента (обычно response.result)

        Returns:
            Значение outcome (e.g., "selected"), или None если не найдено
        """
        if not isinstance(result, dict):
            return None

        nested_outcome = result.get("outcome")
        if isinstance(nested_outcome, dict):
            # ACP format: {"outcome": {"outcome": "selected", ...}}
            raw_value = nested_outcome.get("outcome")
            if isinstance(raw_value, str):
                return raw_value

        # Legacy fallback: {"outcome": "selected"}
        if isinstance(nested_outcome, str):
            return nested_outcome

        return None

    def extract_permission_option_id(self, result: Any) -> str | None:
        """Извлекает optionId из response на session/request_permission.

        Поддерживает ACP shape (`{"outcome": {"optionId": ...}}`) и
        legacy формат (`{"optionId": ...}`) для обратной совместимости.

        Args:
            result: Результат от клиента (обычно response.result)

        Returns:
            optionId (e.g., "allow_once"), или None если не найдено
        """
        if not isinstance(result, dict):
            return None

        nested_outcome = result.get("outcome")
        if isinstance(nested_outcome, dict):
            # ACP format: {"outcome": {"optionId": "allow_once", ...}}
            raw_option_id = nested_outcome.get("optionId")
            if isinstance(raw_option_id, str):
                return raw_option_id

        # Legacy fallback: {"optionId": "allow_once"}
        raw_option_id = result.get("optionId")
        if isinstance(raw_option_id, str):
            return raw_option_id

        return None

    def resolve_permission_option_kind(
        self,
        option_id: str | None,
        permission_options: list[dict[str, Any]],
    ) -> str | None:
        """Возвращает kind опции разрешения по её optionId.

        Args:
            option_id: ID опции для поиска
            permission_options: Список опций для поиска

        Returns:
            kind опции (allow_once, allow_always, reject_once, reject_always) или None
        """
        if option_id is None:
            return None

        for option in permission_options:
            if not isinstance(option, dict):
                continue
            if option.get("optionId") != option_id:
                continue

            kind_value = option.get("kind")
            if isinstance(kind_value, str):
                return kind_value
            return None

        return None

    def build_permission_acceptance_updates(
        self,
        session: SessionState,
        session_id: str,
        tool_call_id: str,
        option_id: str,
    ) -> list[ACPMessage]:
        """Строит updates после выбора опции разрешения.

        Если опция имеет suffix 'always', сохраняет policy в
        session.permission_policy для future использования.

        Args:
            session: Состояние сессии (может быть обновлено)
            session_id: ID сессии
            tool_call_id: ID tool call'а
            option_id: Выбранная опция (allow_once, allow_always, reject_once, reject_always)

        Returns:
            Список ACPMessage notifications об обновлении разрешения
        """
        notifications: list[ACPMessage] = []

        # Определяем решение и нужно ли сохранять policy
        decision: str | None = None
        should_save_policy = False

        if option_id == "allow_once":
            decision = "allow"
            should_save_policy = False
        elif option_id == "allow_always":
            decision = "allow"
            should_save_policy = True
        elif option_id == "reject_once":
            decision = "reject"
            should_save_policy = False
        elif option_id == "reject_always":
            decision = "reject"
            should_save_policy = True

        # Если нужно сохранить policy, сохраняем в session
        if should_save_policy:
            # Находим tool_kind из текущего tool call
            tool_call = session.tool_calls.get(tool_call_id)
            if tool_call is not None:
                policy_value = "allow_always" if decision == "allow" else "reject_always"
                session.permission_policy[tool_call.kind] = policy_value

        # Отправляем notification об обновлении (если нужен клиенту)
        # В текущей реализации это может быть пусто, но интерфейс предусмотрен

        return notifications

    def find_session_by_permission_request_id(
        self,
        permission_request_id: JsonRpcId,
        sessions: dict[str, SessionState],
    ) -> SessionState | None:
        """Ищет сессию с активным turn, ожидающим ответ на permission request.

        Используется для корреляции входящего response с ожидаемым permission request.

        Args:
            permission_request_id: ID permission request для поиска
            sessions: Словарь всех сессий

        Returns:
            SessionState если найдена, иначе None
        """
        for session in sessions.values():
            active_turn = session.active_turn
            if active_turn is None:
                continue
            if active_turn.permission_request_id == permission_request_id:
                return session

        return None

    def request_tool_permission(
        self,
        session: SessionState,
        tool_call: Any,
        tool_kind: str,
        session_id: str,
    ) -> JsonRpcId:
        """Запросить разрешение для выполнения tool call.

        Создает session/request_permission request с информацией о tool call.
        Сохраняет correlation IDs в active turn для последующей обработки response.

        Логика:
        1. Генерировать уникальный permission_request_id
        2. Создать ACPMessage для session/request_permission с:
           - toolCallId
           - tool name и arguments
           - options (allow_once, allow_always, reject_once, reject_always)
        3. Вернуть permission_request_id для отслеживания

        Args:
            session: Состояние сессии
            tool_call: Состояние tool call с информацией
            tool_kind: Категория tool (execute, read, write и т.д.)
            session_id: ID сессии для notification

        Returns:
            permission_request_id для отслеживания
        """
        # Генерируем уникальный ID для permission request
        from uuid import uuid4

        permission_request_id = str(uuid4())

        # Извлекаем информацию из tool_call
        tool_call_id = tool_call.tool_call_id
        tool_title = tool_call.title

        # Строим permission request message через build_permission_request
        # (сохраняет ID в active_turn автоматически)
        permission_msg = self.build_permission_request(
            session,
            session_id,
            tool_call_id,
            tool_title,
            tool_kind,
        )

        # Используем ID из созданного сообщения (оно уже сгенерировано в build_permission_request)
        if permission_msg.id is not None:
            permission_request_id = permission_msg.id

        return permission_request_id
