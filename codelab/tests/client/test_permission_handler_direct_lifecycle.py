"""Тесты для новой реализации PermissionHandler.handle_request() с прямым управлением lifecycle.

Проверяет:
- Вызов callback с правильными параметрами
- Обработку выбора пользователя через on_choice callback
- Обработку timeout
- Обработку ошибок в callback
- Отправку response на сервер
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from unittest.mock import Mock

import pytest

from codelab.client.application.permission_handler import (
    PermissionHandler,
    PermissionRequest,
)
from codelab.client.domain import TransportService
from codelab.client.messages import (
    CancelledPermissionOutcome,
    PermissionOption,
    PermissionToolCall,
    RequestPermissionRequest,
    SelectedPermissionOutcome,
)


class TestPermissionHandlerDirectLifecycle:
    """Тесты для PermissionHandler.handle_request() с прямым управлением lifecycle."""

    @pytest.fixture
    def mock_transport(self) -> Mock:
        """Создать mock ACPTransportService."""
        return Mock(spec=TransportService)

    @pytest.fixture
    def mock_coordinator(self) -> Mock:
        """Создать mock SessionCoordinator."""
        from codelab.client.application.session_coordinator import SessionCoordinator

        return Mock(spec=SessionCoordinator)

    @pytest.fixture
    def permission_handler(
        self,
        mock_transport: Mock,
    ) -> PermissionHandler:
        """Создать настоящий PermissionHandler для тестирования."""
        handler = PermissionHandler(
            transport=mock_transport,
            logger=Mock(),
        )
        # Заменить mock logger на структурированный для логирования
        handler._logger = Mock()
        return handler

    @pytest.fixture
    def sample_permission_request(self) -> RequestPermissionRequest:
        """Создать sample RequestPermissionRequest."""
        return RequestPermissionRequest(
            jsonrpc="2.0",
            id="perm_1",
            method="session/request_permission",
            params={
                "sessionId": "session_1",
                "toolCall": {
                    "toolCallId": "tool_1",
                    "title": "File Write",
                },
                "options": [
                    {
                        "optionId": "allow_once",
                        "name": "Allow once",
                        "kind": "allow_once",
                    },
                    {
                        "optionId": "reject_once",
                        "name": "Reject",
                        "kind": "reject_once",
                    },
                ],
            },
        )

    @pytest.mark.asyncio
    async def test_handle_request_with_callback_and_user_selection(
        self,
        permission_handler: PermissionHandler,
        sample_permission_request: RequestPermissionRequest,
    ) -> None:
        """handle_request вызывает callback и обрабатывает выбор пользователя."""
        callback = Mock()
        on_choice_func = None

        def capture_on_choice(
            request_id: str,
            tool_call: PermissionToolCall,
            options: list[PermissionOption],
            on_choice: Callable[[str | int, str], None],
        ) -> None:
            """Захватить функцию on_choice для последующего вызова."""
            nonlocal on_choice_func
            on_choice_func = on_choice

        callback.side_effect = capture_on_choice

        # Запустить handle_request в background
        task = asyncio.create_task(
            permission_handler.handle_request(
                request=sample_permission_request,
                callback=callback,
            )
        )

        # Дать время на создание запроса
        await asyncio.sleep(0.05)

        # Проверить что callback был вызван с правильными параметрами
        callback.assert_called_once()
        call_args = callback.call_args
        assert call_args[0][0] == "perm_1"  # request_id
        assert call_args[0][1].toolCallId == "tool_1"  # tool_call
        assert len(call_args[0][2]) == 2  # options
        assert callable(call_args[0][3])  # on_choice функция

        # Вызвать on_choice для имитации выбора пользователя
        assert on_choice_func is not None
        on_choice_func("perm_1", "allow_once")

        # Дождаться результата
        outcome = await task

        assert isinstance(outcome, SelectedPermissionOutcome)
        assert outcome.outcome == "selected"
        assert outcome.optionId == "allow_once"

    @pytest.mark.asyncio
    async def test_handle_request_without_callback_returns_cancelled(
        self,
        permission_handler: PermissionHandler,
        sample_permission_request: RequestPermissionRequest,
    ) -> None:
        """handle_request без callback возвращает CancelledPermissionOutcome."""
        outcome = await permission_handler.handle_request(
            request=sample_permission_request,
            callback=None,
        )

        assert isinstance(outcome, CancelledPermissionOutcome)
        assert outcome.outcome == "cancelled"

    @pytest.mark.asyncio
    async def test_handle_request_with_callback_timeout(
        self,
        permission_handler: PermissionHandler,
        sample_permission_request: RequestPermissionRequest,
    ) -> None:
        """handle_request возвращает CancelledOutcome при timeout."""
        callback = Mock()

        def capture_callback(
            request_id: str,
            tool_call: PermissionToolCall,
            options: list[PermissionOption],
            on_choice: callable,  # type: ignore[type-arg]
        ) -> None:
            """Не вызываем on_choice - ждем timeout."""
            pass

        callback.side_effect = capture_callback

        # Для этого теста нам нужно использовать настоящий request_manager
        # с коротким timeout
        original_create = permission_handler._request_manager.create_request

        def patched_create(*args, **kwargs) -> PermissionRequest:  # type: ignore[type-arg]
            kwargs["timeout"] = 0.05  # 50ms timeout
            return original_create(*args, **kwargs)

        permission_handler._request_manager.create_request = patched_create  # type: ignore[method-assign]

        outcome = await permission_handler.handle_request(
            request=sample_permission_request,
            callback=callback,
        )

        # После timeout должно вернуть cancelled
        assert isinstance(outcome, CancelledPermissionOutcome)
        assert outcome.outcome == "cancelled"

    @pytest.mark.asyncio
    async def test_handle_request_with_invalid_option_id(
        self,
        permission_handler: PermissionHandler,
        sample_permission_request: RequestPermissionRequest,
    ) -> None:
        """handle_request отменяет request если выбран невалидный option_id."""
        callback = Mock()
        on_choice_func = None

        def capture_on_choice(
            request_id: str,
            tool_call: PermissionToolCall,
            options: list[PermissionOption],
            on_choice: Callable[[str | int, str], None],
        ) -> None:
            """Захватить функцию on_choice для последующего вызова."""
            nonlocal on_choice_func
            on_choice_func = on_choice

        callback.side_effect = capture_on_choice

        # Запустить handle_request в background
        task = asyncio.create_task(
            permission_handler.handle_request(
                request=sample_permission_request,
                callback=callback,
            )
        )

        # Дать время на создание запроса
        await asyncio.sleep(0.05)

        # Вызвать on_choice с невалидным option_id
        assert on_choice_func is not None
        on_choice_func("perm_1", "invalid_option_id")

        # Дождаться результата
        outcome = await task

        # Должно вернуть cancelled т.к. опция не найдена
        assert isinstance(outcome, CancelledPermissionOutcome)
        assert outcome.outcome == "cancelled"

    @pytest.mark.asyncio
    async def test_handle_request_callback_exception_handling(
        self,
        permission_handler: PermissionHandler,
        sample_permission_request: RequestPermissionRequest,
    ) -> None:
        """handle_request ловит исключение в callback и возвращает cancelled."""

        def failing_callback(
            request_id: str,
            tool_call: PermissionToolCall,
            options: list[PermissionOption],
            on_choice: callable,  # type: ignore[type-arg]
        ) -> None:
            """Callback который выбрасывает исключение."""
            raise RuntimeError("Callback error")

        outcome = await permission_handler.handle_request(
            request=sample_permission_request,
            callback=failing_callback,
        )

        # Должно вернуть cancelled из-за ошибки в callback
        assert isinstance(outcome, CancelledPermissionOutcome)
        assert outcome.outcome == "cancelled"

    @pytest.mark.asyncio
    async def test_handle_request_manages_request_lifecycle(
        self,
        permission_handler: PermissionHandler,
        sample_permission_request: RequestPermissionRequest,
    ) -> None:
        """handle_request создает и удаляет request из manager."""
        callback = Mock()
        on_choice_func = None

        def capture_on_choice(
            request_id: str,
            tool_call: PermissionToolCall,
            options: list[PermissionOption],
            on_choice: Callable[[str | int, str], None],
        ) -> None:
            """Захватить функцию on_choice для последующего вызова."""
            nonlocal on_choice_func
            on_choice_func = on_choice

        callback.side_effect = capture_on_choice

        # Запустить handle_request в background
        task = asyncio.create_task(
            permission_handler.handle_request(
                request=sample_permission_request,
                callback=callback,
            )
        )

        # Дать время на создание запроса
        await asyncio.sleep(0.05)

        # Проверить что request создан в manager
        assert permission_handler._request_manager.get_request("perm_1") is not None

        # Вызвать on_choice для завершения request
        assert on_choice_func is not None
        on_choice_func("perm_1", "allow_once")

        # Дождаться результата
        outcome = await task

        # Проверить что request был удален из manager
        assert permission_handler._request_manager.get_request("perm_1") is None
        assert isinstance(outcome, SelectedPermissionOutcome)

    @pytest.mark.asyncio
    async def test_handle_request_callback_receives_proper_parameters(
        self,
        permission_handler: PermissionHandler,
        sample_permission_request: RequestPermissionRequest,
    ) -> None:
        """handle_request передает правильные параметры в callback."""
        captured_params = {}

        def capturing_callback(
            request_id: str,
            tool_call: PermissionToolCall,
            options: list[PermissionOption],
            on_choice: callable,  # type: ignore[type-arg]
        ) -> None:
            """Захватить параметры callback."""
            captured_params["request_id"] = request_id
            captured_params["tool_call"] = tool_call
            captured_params["options"] = options
            captured_params["on_choice"] = on_choice

        task = asyncio.create_task(
            permission_handler.handle_request(
                request=sample_permission_request,
                callback=capturing_callback,
            )
        )

        await asyncio.sleep(0.05)

        # Проверить параметры
        assert captured_params["request_id"] == "perm_1"
        assert captured_params["tool_call"].toolCallId == "tool_1"
        assert captured_params["tool_call"].title == "File Write"
        assert len(captured_params["options"]) == 2
        assert captured_params["options"][0].optionId == "allow_once"
        assert captured_params["options"][1].optionId == "reject_once"
        assert callable(captured_params["on_choice"])

        # Завершить task
        captured_params["on_choice"]("perm_1", "allow_once")
        outcome = await task
        assert isinstance(outcome, SelectedPermissionOutcome)
