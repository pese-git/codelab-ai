"""Обработчик permission requests на стороне ACP клиента.

Модуль отвечает за:
- Прием session/request_permission запросов от сервера
- Управление состоянием pending requests
- Интеграцию с UI (PermissionViewModel, PermissionModal)
- Отправку response обратно на сервер
- Обработку timeout и cancellation

Архитектура состоит из трех компонентов:
1. PermissionRequest - состояние одного запроса с asyncio.Future
2. PermissionRequestManager - реестр всех активных запросов
3. PermissionHandler - orchestration логика обработки
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import structlog

from codelab.client.messages import (
    ACPMessage,
    CancelledPermissionOutcome,
    JsonRpcId,
    PermissionOption,
    PermissionOutcome,
    PermissionToolCall,
    RequestPermissionRequest,
    SelectedPermissionOutcome,
)

if TYPE_CHECKING:
    from codelab.client.domain.services import TransportService


@dataclass
class PermissionRequest:
    """Состояние одного permission request с Future для ожидания результата.

    Представляет один запрос разрешения от сервера с метаданными:
    - ID запроса (для маршрутизации ответа)
    - Информация о tool call (что требуется разрешить)
    - Доступные опции (Allow, Reject и их вариации)
    - Future для ожидания выбора пользователя
    - Timeout задача для автоматической отмены

    Пример использования:
        request = PermissionRequest(
            request_id="perm_1",
            session_id="sess_1",
            tool_call=PermissionToolCall(...),
            options=[PermissionOption(...)],
        )
        outcome = await request.wait_for_outcome()  # Блокирует до выбора пользователя
        request.resolve_with_option("allow_once")  # Разрешить с выбранной опцией
    """

    # Основные идентификаторы и данные
    request_id: JsonRpcId
    session_id: str
    tool_call: PermissionToolCall
    options: list[PermissionOption]

    # Управление результатом
    future: asyncio.Future[PermissionOutcome] = field(default_factory=asyncio.Future)

    # Метаданные
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),  # noqa: UP017
    )

    # Управление timeout задачей (не сохраняется, управляется временем жизни)
    timeout_task: asyncio.Task[None] | None = field(default=None, init=False)

    # Logger для этого запроса
    _logger: Any = field(
        default_factory=lambda: structlog.get_logger("permission_request"),
        init=False,
    )

    async def wait_for_outcome(self) -> PermissionOutcome:
        """Дождаться выбора пользователя или timeout/cancellation.

        Returns:
            PermissionOutcome с результатом выбора пользователя

        Raises:
            asyncio.CancelledError: Если request был отменен сервером
            asyncio.TimeoutError: Если был timeout (обработан в PermissionHandler)

        Пример:
            outcome = await request.wait_for_outcome()
            print(f"User selected: {outcome.outcome}")
        """
        return await self.future

    def resolve_with_option(self, option_id: str) -> None:
        """Разрешить Future с выбранной опцией.

        Args:
            option_id: ID выбранной опции (e.g., "allow_once", "reject_always")

        Пример:
            request.resolve_with_option("allow_once")
        """
        if not self.future.done():
            outcome = SelectedPermissionOutcome(outcome="selected", optionId=option_id)
            self.future.set_result(outcome)
            self._logger.info(
                "permission_option_selected",
                request_id=self.request_id,
                session_id=self.session_id,
                tool_call_id=self.tool_call.toolCallId,
                option_id=option_id,
                created_at=self.created_at.isoformat(),
            )

    def resolve_with_cancellation(self) -> None:
        """Разрешить Future с cancelled outcome.

        Используется при timeout или отмене по инициативе сервера.

        Пример:
            request.resolve_with_cancellation()
        """
        if not self.future.done():
            outcome = CancelledPermissionOutcome(outcome="cancelled")
            self.future.set_result(outcome)
            self._logger.info(
                "permission_request_user_cancelled",
                request_id=self.request_id,
                session_id=self.session_id,
                tool_call_id=self.tool_call.toolCallId,
                created_at=self.created_at.isoformat(),
            )

    def cancel(self) -> None:
        """Отменить Future (например, по инициативе сервера через session/cancel).

        Вызывает CancelledError для любого await на этом Future.

        Пример:
            request.cancel()
        """
        if not self.future.done():
            self.future.cancel()
            self._logger.debug(
                "permission_request_cancelled_by_server",
                request_id=self.request_id,
            )


class PermissionRequestManager:
    """Реестр и управление всеми активными permission requests.

    Отслеживает все pending requests по их ID и предоставляет методы для:
    - Создания новых requests с автоматическим timeout
    - Поиска request по ID
    - Удаления completed requests
    - Отмены requests по инициативе сервера
    - Получения списка всех активных requests

    Пример использования:
        manager = PermissionRequestManager()
        
        # Создание нового запроса с timeout 300 сек
        request = manager.create_request(
            request_id="perm_1",
            session_id="sess_1",
            tool_call=tool_call_data,
            options=option_list,
            timeout=300,
        )
        
        # Ожидание результата
        outcome = await request.wait_for_outcome()
        
        # Удаление завершенного запроса
        manager.remove_request("perm_1")
    """

    def __init__(self) -> None:
        """Инициализировать PermissionRequestManager."""
        self._requests: dict[JsonRpcId, PermissionRequest] = {}
        self._logger = structlog.get_logger("permission_request_manager")

    def create_request(
        self,
        request_id: JsonRpcId,
        session_id: str,
        tool_call: PermissionToolCall,
        options: list[PermissionOption],
        timeout: float = 300.0,
    ) -> PermissionRequest:
        """Создать и зарегистрировать новый permission request с timeout.

        Args:
            request_id: ID от сервера (для маршрутизации response)
            session_id: ID сессии, к которой относится запрос
            tool_call: Информация о tool call, требующем разрешение
            options: Список доступных опций для выбора пользователю
            timeout: Timeout в секундах (по умолчанию 300)

        Returns:
            PermissionRequest готовый к использованию

        Пример:
            request = manager.create_request(
                request_id="perm_123",
                session_id="sess_1",
                tool_call=PermissionToolCall(...),
                options=[PermissionOption(...)],
                timeout=300,
            )
        """
        request = PermissionRequest(
            request_id=request_id,
            session_id=session_id,
            tool_call=tool_call,
            options=options,
        )

        # Запланировать timeout задачу
        timeout_task = asyncio.create_task(self._timeout_handler(request_id, timeout))
        request.timeout_task = timeout_task

        # Зарегистрировать в реестре
        self._requests[request_id] = request

        self._logger.debug(
            "permission_request_created",
            request_id=request_id,
            session_id=session_id,
            total_active=len(self._requests),
        )

        return request

    async def _timeout_handler(self, request_id: JsonRpcId, timeout_seconds: float) -> None:
        """Обработчик timeout для permission request.

        Через timeout_seconds секунд разрешает Future с cancelled outcome
        и удаляет запрос из реестра.

        Args:
            request_id: ID запроса для timeout обработки
            timeout_seconds: Время ожидания в секундах
        """
        try:
            await asyncio.sleep(timeout_seconds)

            # Timeout истек - получить и разрешить request
            request = self._requests.get(request_id)
            if request:
                self._logger.warning(
                    "permission_request_timeout_expired",
                    request_id=request_id,
                    session_id=request.session_id,
                    tool_call_id=request.tool_call.toolCallId,
                    timeout_seconds=timeout_seconds,
                    created_at=request.created_at.isoformat(),
                )
                request.resolve_with_cancellation()
                self.remove_request(request_id)

        except asyncio.CancelledError:
            # Timeout задача была отменена (request разрешился раньше)
            self._logger.debug(
                "permission_timeout_task_cancelled_early",
                request_id=request_id,
            )
            pass

    def get_request(self, request_id: JsonRpcId) -> PermissionRequest | None:
        """Получить request по ID.

        Args:
            request_id: ID запроса

        Returns:
            PermissionRequest или None если не найден

        Пример:
            request = manager.get_request("perm_1")
            if request:
                outcome = await request.wait_for_outcome()
        """
        return self._requests.get(request_id)

    def remove_request(self, request_id: JsonRpcId) -> None:
        """Удалить request из реестра и отменить его timeout задачу.

        Args:
            request_id: ID запроса

        Пример:
            manager.remove_request("perm_1")
        """
        if request_id in self._requests:
            request = self._requests[request_id]

            # Отменить timeout задачу
            if request.timeout_task:
                request.timeout_task.cancel()

            # Удалить из реестра
            del self._requests[request_id]

            self._logger.debug(
                "permission_request_removed",
                request_id=request_id,
                remaining=len(self._requests),
            )

    def cancel_request(self, request_id: JsonRpcId) -> None:
        """Отменить request (например, по инициативе сервера через session/cancel).

        Отменяет Future и удаляет запрос из реестра.

        Args:
            request_id: ID запроса для отмены

        Пример:
            manager.cancel_request("perm_1")
        """
        request = self._requests.get(request_id)
        if request:
            request.cancel()
            self.remove_request(request_id)
            self._logger.info(
                "permission_request_cancelled_by_server",
                request_id=request_id,
            )

    def get_all_active(self) -> list[PermissionRequest]:
        """Получить все активные (pending) requests.

        Returns:
            Список всех PermissionRequest которые ждут результата

        Пример:
            active = manager.get_all_active()
            print(f"Active requests: {len(active)}")
        """
        return list(self._requests.values())


class PermissionHandler:
    """Основной обработчик permission requests на стороне клиента.

    Координирует полный цикл обработки permission request:
    1. Получение session/request_permission от сервера
    2. Создание и регистрация PermissionRequest
    3. Показ модального окна пользователю через ViewModel
    4. Ожидание выбора пользователя
    5. Отправка session/request_permission_response на сервер
    6. Cleanup

    Архитектура:
    - Использует PermissionRequestManager для state management
    - Интегрируется с UI через PermissionViewModel
    - Отправляет response через transport

    Пример использования:
        handler = PermissionHandler(
            transport=transport,
            logger=logger,
        )
        
        # Обработать входящий request
        outcome = await handler.handle_request(request_message)
        
        # Response автоматически отправляется на сервер
    """

    def __init__(
        self,
        transport: TransportService,
        logger: Any,
    ) -> None:
        """Инициализировать PermissionHandler.

        Args:
            transport: TransportService для отправки response
            logger: Logger для структурированного логирования

        Пример:
            handler = PermissionHandler(
                transport=transport,
                logger=structlog.get_logger("permission_handler"),
            )
        """
        self._transport = transport
        self._logger = logger

        # Менеджер для управления всеми активными requests
        self._request_manager = PermissionRequestManager()

    def get_request_manager(self) -> PermissionRequestManager:
        """Получить менеджер requests (для интеграции с UI/другими компонентами).

        Returns:
            PermissionRequestManager

        Пример:
            manager = handler.get_request_manager()
            request = manager.get_request("perm_1")
        """
        return self._request_manager

    async def handle_request(
        self,
        request: RequestPermissionRequest,
        callback: (
            Callable[
                [
                    str | int,
                    PermissionToolCall,
                    list[PermissionOption],
                    Callable[[str | int, str], None],
                ],
                None,
            ]
            | None
        ) = None,
    ) -> PermissionOutcome:
        """Обработать входящий session/request_permission от сервера.

        Этот метод управляет полным lifecycle запроса разрешения:
        1. Создает PermissionRequest через _request_manager
        2. Вызывает callback для показа UI (если предоставлен)
        3. Ждет результата от пользователя
        4. Отправляет response на сервер
        5. Возвращает outcome

        Args:
            request: Типизированный RequestPermissionRequest от сервера
            callback: Функция для показа UI modal (опционально)
                Сигнатура: Callable[
                    [str|int, PermissionToolCall, list[PermissionOption], Callable],
                    None
                ]
                Вызывается как: callback(request_id, tool_call, options, on_choice)
                на_choice: Callable[[str], None] - для обработки выбора
                пользователя

        Returns:
            PermissionOutcome с результатом выбора пользователя

        Пример:
            from codelab.client.messages import parse_request_permission_request
            
            raw_message = {
                "jsonrpc": "2.0",
                "id": "perm_1",
                "method": "session/request_permission",
                "params": {...}
            }
            request = parse_request_permission_request(raw_message)
            if request:
                # С callback - показывает UI modal через callback
                def show_modal(req_id, tool_call, options, on_choice):
                    app.show_permission_modal(req_id, tool_call, options, on_choice)
                
                outcome = await handler.handle_request(request, callback=show_modal)
        """
        request_id = request.id
        session_id = request.params.sessionId
        tool_call = request.params.toolCall
        options = request.params.options

        self._logger.info(
            "handling_permission_request",
            request_id=request_id,
            session_id=session_id,
            tool_call_id=tool_call.toolCallId,
            tool_name=tool_call.title,
            has_callback=callback is not None,
        )

        try:
            # Создать PermissionRequest через manager
            perm_request = self._request_manager.create_request(
                request_id=request_id,
                session_id=session_id,
                tool_call=tool_call,
                options=options,
            )

            # Если callback предоставлен, вызвать его для показа UI
            if callback:
                self._logger.info(
                    "permission_callback_provided_showing_ui_modal",
                    request_id=request_id,
                    session_id=session_id,
                    tool_call_id=tool_call.toolCallId,
                )

                def on_choice(
                    req_id: str | int, option_id: str
                ) -> None:
                    """Callback для обработки выбора пользователя.
                    
                    Args:
                        req_id: ID permission request (дублируется для совместимости с интерфейсом)
                        option_id: ID выбранной опции или "cancelled"
                    """
                    self._logger.info(
                        "permission_choice_received_from_ui",
                        request_id=req_id,
                        session_id=session_id,
                        option_id=option_id,
                    )
                    # Найти опцию по ID
                    selected_option = next(
                        (opt for opt in options if opt.optionId == option_id),
                        None
                    )
                    if selected_option:
                        perm_request.resolve_with_option(option_id)
                    else:
                        self._logger.warning(
                            "permission_option_not_found_cancelling",
                            request_id=req_id,
                            session_id=session_id,
                            option_id=option_id,
                        )
                        perm_request.resolve_with_cancellation()

                # Вызвать callback для показа UI
                try:
                    callback(request_id, tool_call, options, on_choice)
                except Exception as e:
                    self._logger.error(
                        "permission_callback_execution_failed",
                        request_id=request_id,
                        session_id=session_id,
                        error=str(e),
                        error_type=type(e).__name__,
                    )
                    perm_request.resolve_with_cancellation()
            else:
                # Нет callback - автоматически отменить
                self._logger.warning(
                    "permission_request_no_callback_returning_cancelled",
                    request_id=request_id,
                    session_id=session_id,
                    tool_call_id=tool_call.toolCallId,
                    tool_name=tool_call.title,
                    message="UI modal НЕ будет показан - callback отсутствует",
                )
                perm_request.resolve_with_cancellation()

            # Ждать результата
            outcome = await perm_request.wait_for_outcome()

            self._logger.info(
                "permission_request_completed",
                request_id=request_id,
                session_id=session_id,
                outcome_type=type(outcome).__name__,
            )

        except asyncio.CancelledError:
            # Request был отменен (например, через session/cancel)
            self._logger.info(
                "permission_request_cancelled",
                request_id=request_id,
                session_id=session_id,
            )
            outcome = CancelledPermissionOutcome(outcome="cancelled")

        except Exception as e:
            # Неожиданная ошибка
            self._logger.error(
                "permission_request_error",
                request_id=request_id,
                session_id=session_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            outcome = CancelledPermissionOutcome(outcome="cancelled")

        # Отправить response на сервер
        try:
            # Отправить response на сервер
            response = self.build_response(request_id, outcome)
            self._logger.info(
                "sending_permission_response_to_server",
                request_id=request_id,
                session_id=session_id,
                tool_call_id=tool_call.toolCallId,
                outcome=outcome.outcome,
                option_id=getattr(outcome, 'optionId', None),
            )
            await self._transport.send(response.to_dict())

            self._logger.info(
                "permission_response_sent_successfully",
                request_id=request_id,
                session_id=session_id,
                tool_call_id=tool_call.toolCallId,
                outcome=outcome.outcome,
            )

        except Exception as e:
            self._logger.error(
                "permission_response_send_failed",
                request_id=request_id,
                session_id=session_id,
                tool_call_id=tool_call.toolCallId,
                error=str(e),
                error_type=type(e).__name__,
            )

        finally:
            # Очистить request из менеджера
            self._request_manager.remove_request(request_id)

        return outcome

    def build_response(
        self,
        request_id: JsonRpcId,
        outcome: PermissionOutcome,
    ) -> ACPMessage:
        """Сформировать JSON-RPC response для session/request_permission.

        Преобразует PermissionOutcome в ACPMessage готовый к отправке.

        Args:
            request_id: ID оригинального request
            outcome: Результат выбора пользователя (selected или cancelled)

        Returns:
            ACPMessage с правильной структурой response

        Пример:
            outcome = SelectedPermissionOutcome(
                outcome="selected",
                optionId="allow_once"
            )
            response = handler.build_response("perm_1", outcome)
            
            # response.to_dict() => {
            #     "jsonrpc": "2.0",
            #     "id": "perm_1",
            #     "result": {
            #         "outcome": "selected",
            #         "optionId": "allow_once"
            #     }
            # }
        """
        # Сериализуем outcome в dict формат согласно протоколу
        result = outcome.model_dump(exclude_none=True)

        # Создаем response message
        response = ACPMessage.response(request_id, result)

        return response

    async def cancel_request(self, request_id: JsonRpcId) -> None:
        """Отменить permission request (по инициативе сервера).

        Вызывается при получении session/cancel уведомления с ID
        активного permission request.

        Args:
            request_id: ID request для отмены

        Пример:
            # При получении session/cancel для permission request:
            await handler.cancel_request("perm_1")
        """
        self._request_manager.cancel_request(request_id)
        self._logger.info(
            "permission_request_cancelled_by_server",
            request_id=request_id,
        )
