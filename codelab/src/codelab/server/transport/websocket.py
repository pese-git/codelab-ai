"""WebSocket транспорт ACP-сервера.

Модуль содержит реализацию AcpServerTransport поверх aiohttp WebSocket.
Обрабатывает JSON-RPC сообщения, управляет жизненным циклом соединения,
deferred prompt tasks и background tool execution.

Пример использования:
    transport = WebSocketTransport(ws, app_container, config)
    await transport.run(on_message=protocol.handle)
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import structlog
from aiohttp import WSMsgType, web
from dishka import AsyncContainer

from codelab.server.client_rpc.service import ClientRPCService
from codelab.server.messages import ACPMessage
from codelab.server.protocol.core import ACPProtocol
from codelab.server.protocol.state import ProtocolOutcome
from codelab.server.rpc_holder import ClientRPCServiceHolder

if TYPE_CHECKING:
    from codelab.server.config import AppConfig

# Константа: максимальное время ожидания для deferred prompt tasks (в секундах)
DEFERRED_PROMPT_TIMEOUT = 30.0

logger = structlog.get_logger()


def _truncate_payload(payload: str, max_length: int = 500) -> str:
    """Обрезает payload для логирования, сохраняя значимую часть.

    Args:
        payload: Строка payload для обрезки
        max_length: Максимальная длина результата

    Returns:
        Обрезанный payload или полный, если он короче max_length
    """
    if len(payload) > max_length:
        return payload[:max_length]
    return payload


class WebSocketTransport:
    """WebSocket реализация AcpServerTransport.

    Управляет одним WebSocket соединением: читает сообщения, передаёт
    их в callback on_message, отправляет responses и notifications.

    Атрибуты:
        ws: aiohttp WebSocketResponse
        app_container: DI контейнер приложения
        config: Конфигурация приложения
    """

    def __init__(
        self,
        ws: web.WebSocketResponse,
        app_container: AsyncContainer,
        config: AppConfig,
        connection_id: str,
        remote_addr: str,
    ) -> None:
        """Инициализирует WebSocket транспорт.

        Args:
            ws: aiohttp WebSocketResponse (уже prepared)
            app_container: DI контейнер приложения (REQUEST scope будет создан внутри)
            config: Конфигурация приложения
            connection_id: Уникальный ID соединения для логирования
            remote_addr: Адрес клиента для логирования
        """
        self._ws = ws
        self._app_container = app_container
        self._config = config
        self._connection_id = connection_id
        self._remote_addr = remote_addr
        self._ws_send_lock = asyncio.Lock()
        self._closed = False
        self._conn_logger = logger.bind(
            connection_id=connection_id,
            remote_addr=remote_addr,
        )

    async def run(
        self,
        on_message: Any = None,
    ) -> None:
        """Основной цикл обработки WebSocket сообщений.

        Args:
            on_message: Callback, принимающий ACPMessage и возвращающий
                       ProtocolOutcome. Если None, создаёт REQUEST scope
                       и получает ACPProtocol из DI контейнера.
        """
        start_time = time.time()

        self._conn_logger.info("ws connection established")

        # Создаём ClientRPCService с callback на отправку
        client_rpc_service = ClientRPCService(
            send_request_callback=self._send_rpc_request,
            client_capabilities={},
        )

        # Состояние соединения
        deferred_prompt_tasks: dict[str, asyncio.Task[None]] = {}
        prompt_request_tasks: set[asyncio.Task[None]] = set()
        initialized = False

        # Используем REQUEST scope для этого WebSocket соединения
        if self._app_container is None:
            self._conn_logger.error("app container not initialized")
            await self._ws.close()
            return

        # Устанавливаем ClientRPCService в holder перед созданием REQUEST scope
        holder = await self._app_container.get(ClientRPCServiceHolder)
        holder.service = client_rpc_service

        async with self._app_container() as request_scope:
            protocol = await request_scope.get(ACPProtocol)

            # Настраиваем send_callback для отправки сообщений из фоновых задач
            protocol._send_callback = self._send_protocol_message

            # Если on_message не передан, используем protocol.handle_and_process
            handler = on_message if on_message is not None else protocol.handle_and_process

            try:
                async for message in self._ws:
                    if message.type == WSMsgType.TEXT:
                        method_name: str | None = None
                        session_id: str | None = None
                        request_id: str | None = None
                        try:
                            acp_request = ACPMessage.from_json(message.data)
                            method_name = acp_request.method
                            request_id = (
                                str(acp_request.id)
                                if acp_request.id is not None
                                else None
                            )

                            self._conn_logger.debug(
                                "message received",
                                payload=_truncate_payload(message.data),
                            )

                            # Обработка initialize
                            if method_name == "initialize":
                                initialized = True
                                if isinstance(acp_request.params, dict):
                                    caps = acp_request.params.get("clientCapabilities", {})
                                    if isinstance(caps, dict):
                                        client_rpc_service._capabilities = caps
                                        self._conn_logger.debug(
                                            "client_rpc_service capabilities updated",
                                            capabilities=caps,
                                        )
                            elif not initialized:
                                # Требуют инициализацию перед другими методами
                                if acp_request.is_notification:
                                    outcome = ProtocolOutcome()
                                else:
                                    outcome = ProtocolOutcome(
                                        response=ACPMessage.error_response(
                                            acp_request.id,
                                            code=-32000,
                                            message="Initialize required before session methods",
                                        )
                                    )
                                method_name = None
                                session_id = None
                                await self._send_outcome(outcome, request_id=request_id)
                                continue

                            # Извлекаем sessionId
                            if isinstance(acp_request.params, dict):
                                raw_session_id = acp_request.params.get("sessionId")
                                if isinstance(raw_session_id, str):
                                    session_id = raw_session_id

                            # session/prompt — выполняем в фоне
                            if method_name == "session/prompt":
                                prompt_task = asyncio.create_task(
                                    self._process_prompt_request_in_background(
                                        acp_request=acp_request,
                                        handler=handler,
                                        method_name=method_name,
                                        session_id=session_id,
                                        request_id=request_id,
                                        deferred_prompt_tasks=deferred_prompt_tasks,
                                        protocol=protocol,
                                    )
                                )
                                prompt_request_tasks.add(prompt_task)
                                prompt_task.add_done_callback(
                                    lambda finished_task: prompt_request_tasks.discard(
                                        finished_task
                                    )
                                )
                                self._conn_logger.debug(
                                    "prompt request scheduled in background",
                                    request_id=request_id,
                                    session_id=session_id,
                                )
                                continue

                            # Response от клиента (Agent→Client RPC)
                            if method_name is None and acp_request.id is not None:
                                self._conn_logger.debug(
                                    "response received, routing to handle_client_response",
                                    request_id=request_id,
                                )
                                outcome = await protocol.handle_client_response(acp_request)
                            else:
                                outcome = await handler(acp_request)

                            self._conn_logger.info(
                                "request received",
                                method=method_name,
                                request_id=request_id,
                                session_id=session_id,
                            )

                        except Exception as exc:
                            self._conn_logger.error(
                                "request parse error",
                                request_id=request_id,
                                error=str(exc),
                                exc_info=True,
                            )
                            outcome = ProtocolOutcome(
                                response=ACPMessage.error_response(
                                    None,
                                    code=-32700,
                                    message="Parse error",
                                    data=str(exc),
                                )
                            )

                        await self._finalize_outcome_and_send(
                            method_name=method_name,
                            session_id=session_id,
                            request_id=request_id,
                            outcome=outcome,
                            deferred_prompt_tasks=deferred_prompt_tasks,
                            protocol=protocol,
                        )

                    elif message.type == WSMsgType.ERROR:
                        self._conn_logger.warning(
                            "ws_error",
                            exception=str(self._ws.exception())
                            if self._ws.exception()
                            else None,
                            peer=self._remote_addr,
                        )
                        break
                    elif message.type in {WSMsgType.CLOSE, WSMsgType.CLOSING}:
                        break

            finally:
                # Cleanup: отменяем все prompt tasks
                if prompt_request_tasks:
                    self._conn_logger.info(
                        "cleaning up prompt request tasks",
                        pending_tasks_count=len(prompt_request_tasks),
                    )
                    for prompt_task in list(prompt_request_tasks):
                        if not prompt_task.done():
                            prompt_task.cancel()
                    await asyncio.gather(*prompt_request_tasks, return_exceptions=True)
                    prompt_request_tasks.clear()

                # Cleanup: отменяем deferred prompt tasks
                if deferred_prompt_tasks:
                    self._conn_logger.info(
                        "cleaning up deferred prompt tasks",
                        pending_tasks_count=len(deferred_prompt_tasks),
                    )
                    for sid, task in list(deferred_prompt_tasks.items()):
                        if not task.done():
                            task.cancel()
                            self._conn_logger.debug(
                                "deferred prompt task cancelled",
                                session_id=sid,
                            )
                        deferred_prompt_tasks.pop(sid, None)

                # Отменяем активные turns при отключении
                cancelled_turns_count = await protocol.cancel_active_turns_on_disconnect()
                if cancelled_turns_count > 0:
                    self._conn_logger.info(
                        "active turns cancelled on disconnect",
                        cancelled_turns_count=cancelled_turns_count,
                    )

                # Отменяем pending ClientRPC requests
                if client_rpc_service is not None:
                    cancelled_rpc_count = client_rpc_service.cancel_all_pending_requests(
                        reason="WS connection closed before client response",
                    )
                    if cancelled_rpc_count > 0:
                        self._conn_logger.info(
                            "pending client rpc cancelled on disconnect",
                            cancelled_rpc_count=cancelled_rpc_count,
                        )

                duration = time.time() - start_time
                self._conn_logger.info(
                    "ws connection closed",
                    duration=round(duration, 3),
                    pending_deferred_tasks=len(deferred_prompt_tasks),
                )

    async def send(self, message: ACPMessage) -> None:
        """Отправить сообщение через WebSocket.

        Args:
            message: ACPMessage для отправки (response, notification или RPC request).
        """
        async with self._ws_send_lock:
            if self._ws.closed:
                return
            await self._ws.send_str(message.to_json())

    async def close(self) -> None:
        """Закрыть WebSocket соединение.

        Метод идемпотентен — повторный вызов безопасен.
        """
        self._closed = True
        if not self._ws.closed:
            await self._ws.close()

    # =========================================================================
    # Internal helpers
    # =========================================================================

    async def _send_rpc_request(self, request_dict: dict) -> None:
        """Отправляет JSON-RPC request клиенту (callback для ClientRPCService)."""
        async with self._ws_send_lock:
            if not self._ws.closed:
                await self._ws.send_json(request_dict)

    async def _send_protocol_message(self, message: ACPMessage) -> None:
        """Отправляет сообщение из фоновых задач протокола.

        Используется ACPProtocol._execute_tool_in_background для отправки
        notifications и turn completion.
        """
        async with self._ws_send_lock:
            if not self._ws.closed:
                await self._ws.send_str(message.to_json())

    async def _send_outcome(
        self,
        outcome: ProtocolOutcome,
        *,
        request_id: str | None,
    ) -> None:
        """Отправляет notifications/response/followups в рамках одного lock."""
        async with self._ws_send_lock:
            if self._ws.closed:
                return

            for notification in outcome.notifications:
                notification_json = notification.to_json()
                await self._ws.send_str(notification_json)
                self._conn_logger.debug(
                    "notification sent",
                    method=notification.method,
                    payload=_truncate_payload(notification_json),
                )

            if outcome.response is not None:
                response_json = outcome.response.to_json()
                await self._ws.send_str(response_json)
                self._conn_logger.debug(
                    "response sent",
                    request_id=request_id,
                    has_error=outcome.response.error is not None,
                    payload=_truncate_payload(response_json),
                )

            for followup_response in outcome.followup_responses:
                followup_json = followup_response.to_json()
                await self._ws.send_str(followup_json)
                self._conn_logger.debug(
                    "followup response sent",
                    request_id=followup_response.id,
                    payload=_truncate_payload(followup_json),
                )

    async def _finalize_outcome_and_send(
        self,
        *,
        method_name: str | None,
        session_id: str | None,
        request_id: str | None,
        outcome: ProtocolOutcome,
        deferred_prompt_tasks: dict[str, asyncio.Task[None]],
        protocol: ACPProtocol,
    ) -> None:
        """Применяет post-processing outcome и отправляет его в WS."""
        # session/cancel — отменяем deferred prompt
        if method_name == "session/cancel" and session_id is not None:
            task = deferred_prompt_tasks.pop(session_id, None)
            if task is not None:
                task.cancel()

        # session/prompt без response — создаём deferred task
        if (
            method_name == "session/prompt"
            and session_id is not None
            and outcome.response is None
            and await protocol.should_auto_complete_active_turn(session_id)
        ):
            task = deferred_prompt_tasks.pop(session_id, None)
            if task is not None:
                task.cancel()
            deferred_prompt_tasks[session_id] = asyncio.create_task(
                self._complete_deferred_prompt(
                    protocol=protocol,
                    session_id=session_id,
                    deferred_prompt_tasks=deferred_prompt_tasks,
                )
            )

        # Обработка pending_tool_execution для permission response
        if outcome.pending_tool_execution is not None:
            pending = outcome.pending_tool_execution
            self._conn_logger.info(
                "scheduling pending tool execution in background",
                session_id=pending.session_id,
                tool_call_id=pending.tool_call_id,
            )
            asyncio.create_task(
                protocol._execute_tool_in_background(
                    session_id=pending.session_id,
                    tool_call_id=pending.tool_call_id,
                )
            )

        await self._send_outcome(outcome, request_id=request_id)

    async def _process_prompt_request_in_background(
        self,
        *,
        acp_request: ACPMessage,
        handler: Any,
        method_name: str,
        session_id: str | None,
        request_id: str | None,
        deferred_prompt_tasks: dict[str, asyncio.Task[None]],
        protocol: ACPProtocol,
    ) -> None:
        """Выполняет `session/prompt` в фоне, не блокируя receive-loop."""
        try:
            outcome = await handler(acp_request)
            self._conn_logger.info(
                "request received",
                method=method_name,
                request_id=request_id,
                session_id=session_id,
            )
            await self._finalize_outcome_and_send(
                method_name=method_name,
                session_id=session_id,
                request_id=request_id,
                outcome=outcome,
                deferred_prompt_tasks=deferred_prompt_tasks,
                protocol=protocol,
            )
        except Exception as exc:
            self._conn_logger.error(
                "background prompt request error",
                request_id=request_id,
                session_id=session_id,
                error=str(exc),
                exc_info=True,
            )
            error_outcome = ProtocolOutcome(
                response=ACPMessage.error_response(
                    acp_request.id,
                    code=-32603,
                    message="Internal error",
                    data=str(exc),
                )
            )
            await self._send_outcome(error_outcome, request_id=request_id)

    async def _complete_deferred_prompt(
        self,
        *,
        protocol: ACPProtocol,
        session_id: str,
        deferred_prompt_tasks: dict[str, asyncio.Task[None]],
    ) -> None:
        """Завершает отложенный `session/prompt` и отправляет финальный response."""
        conn_logger = self._conn_logger.bind(session_id=session_id)

        try:
            # Небольшая задержка оставляет окно для входящего `session/cancel`
            await asyncio.sleep(0.05)

            try:
                response = await protocol.complete_active_turn(
                    session_id, stop_reason="end_turn"
                )
            except TimeoutError:
                conn_logger.warning(
                    "deferred prompt completion timeout",
                    timeout_sec=DEFERRED_PROMPT_TIMEOUT,
                )
                response = None
            except Exception as exc:
                conn_logger.error(
                    "deferred prompt completion error",
                    error=str(exc),
                    exc_info=True,
                )
                response = None

            # Отправляем response если он есть и соединение ещё живо
            if response is not None and not self._ws.closed:
                try:
                    await self._ws.send_str(response.to_json())
                    conn_logger.info("deferred prompt completed successfully")
                except Exception as exc:
                    conn_logger.error(
                        "deferred prompt send error",
                        error=str(exc),
                        exc_info=True,
                    )
            elif self._ws.closed:
                conn_logger.debug("deferred prompt skipped (websocket closed)")
            else:
                conn_logger.debug("deferred prompt skipped (no response)")

        except asyncio.CancelledError:
            conn_logger.info("deferred prompt cancelled by client")
            try:
                session = await protocol._storage.load_session(session_id)
                if session is not None and session.pending_prompt_response is not None:
                    prompt_resp = session.pending_prompt_response
                    response = ACPMessage.response(
                        prompt_resp["request_id"],
                        {"stopReason": prompt_resp["stop_reason"]},
                    )
                    session.pending_prompt_response = None
                    await protocol._storage.save_session(session)
                    if not self._ws.closed:
                        await self._ws.send_str(response.to_json())
                        conn_logger.info("deferred prompt cancelled response sent")
            except Exception as exc:
                conn_logger.debug(
                    "deferred prompt cancelled response error",
                    error=str(exc),
                )
            return
        except Exception as exc:
            conn_logger.error(
                "deferred prompt unexpected error",
                error=str(exc),
                exc_info=True,
            )
        finally:
            removed = deferred_prompt_tasks.pop(session_id, None)
            if removed is not None:
                conn_logger.debug("deferred prompt task removed from tracking")
