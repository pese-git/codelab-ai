"""WebSocket транспорт ACP-сервера.

Модуль поднимает endpoint `GET /acp/ws` для двустороннего потока с
`session/update` и server->client RPC.

Пример использования:
    server = ACPHttpServer(host="127.0.0.1", port=8080)
    await server.run()
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import os
import re
import subprocess
import sys
import time
import uuid
from typing import TYPE_CHECKING

import structlog
from aiohttp import WSMsgType, web
from dishka import AsyncContainer

from .client_rpc.service import ClientRPCService
from .config import AppConfig
from .di import make_container
from .messages import ACPMessage
from .protocol.core import ACPProtocol
from .protocol.state import ProtocolOutcome
from .storage import SessionStorage

if TYPE_CHECKING:
    pass

# Получаем структурированный logger
logger = structlog.get_logger()

# Константа: максимальное время ожидания для deferred prompt tasks (в секундах)
# Если prompt не завершится за это время, его нужно отменить
DEFERRED_PROMPT_TIMEOUT = 30.0


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


class ACPHttpServer:
    """Транспортный слой ACP поверх aiohttp (WebSocket-only).

    Класс принимает wire-сообщения, передает их в `ACPProtocol` и отправляет
    обратно response/notifications в правильном порядке.

    Пример использования:
        server = ACPHttpServer(port=8080)
        await server.run()
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8080,
        *,
        require_auth: bool = False,
        auth_api_key: str | None = None,
        storage: SessionStorage | None = None,
        config: AppConfig | None = None,
        enable_web: bool = True,
    ) -> None:
        """Создает транспортный сервер с адресом прослушивания.

        Args:
            host: IP адрес для прослушивания (по умолчанию 127.0.0.1).
            port: Порт для прослушивания (по умолчанию 8080).
            require_auth: Требовать аутентификацию перед session/new и session/load.
            auth_api_key: API ключ для аутентификации.
            storage: Backend для хранения сессий (по умолчанию InMemoryStorage).
            config: Глобальная конфигурация приложения (LLM, агент и т.д.).
            enable_web: Включить Web UI на корневом пути "/" (по умолчанию True).

        Пример использования:
            ACPHttpServer(host="0.0.0.0", port=8080)
        """

        self.host = host
        self.port = port
        self.require_auth = require_auth
        self.auth_api_key = auth_api_key
        self.storage = storage
        self.config = config or AppConfig()
        self.enable_web = enable_web
        # DI контейнер приложения
        self._app_container: AsyncContainer | None = None
        # Subprocess для textual-serve (Web UI)
        self._web_ui_process: subprocess.Popen[bytes] | None = None
        # URL для web UI (локальный адрес)
        self._web_ui_url: str | None = None

        # Логируем инициализацию сервера
        logger.debug(
            "acp http server initialized",
            host=host,
            port=port,
            require_auth=require_auth,
            has_auth_key=bool(auth_api_key),
            enable_web=enable_web,
        )

    def _validate_host(self, host: str) -> str:
        """Проверяет, что host — корректный IP или hostname.

        Args:
            host: Строка хоста для валидации

        Returns:
            Валидированный хост

        Raises:
            ValueError: Если хост некорректный
        """
        # Попытаться распарсить как IP
        try:
            ipaddress.ip_address(host)
            return host
        except ValueError:
            pass
        # Проверить как hostname (только буквы, цифры, дефисы, точки)
        if re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9\-\.]{0,253}[a-zA-Z0-9])?$', host):
            return host
        raise ValueError(f"Invalid host: {host!r}")

    def _start_web_ui_subprocess(self) -> bool:
        """Запускает textual-serve как subprocess для локального Web UI.

        Параметры передаются через переменные окружения — никакой интерполяции в код.

        Returns:
            True если subprocess успешно запущен, False иначе.
        """
        from .web_app import is_web_ui_available

        if not is_web_ui_available():
            logger.debug("web_ui_not_started_textual_serve_unavailable")
            return False

        try:
            # Валидируем хост перед передачей в subprocess
            validated_host = self._validate_host(str(self.host))
            web_ui_port = self.port + 1000

            # Параметры передаются через env, не через f-string в код
            child_env = {
                **os.environ,
                "CODELAB_WS_HOST": validated_host,
                "CODELAB_WS_PORT": str(self.port),
                "CODELAB_WEB_UI_HOST": validated_host,
                "CODELAB_WEB_UI_PORT": str(web_ui_port),
            }

            self._web_ui_process = subprocess.Popen(
                [sys.executable, "-m", "codelab.client.tui.serve_entry"],
                env=child_env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

            self._web_ui_url = f"http://{validated_host}:{web_ui_port}/"

            logger.info(
                "web_ui_subprocess_started",
                pid=self._web_ui_process.pid,
                url=self._web_ui_url,
            )
            return True

        except Exception as e:
            logger.warning("failed_to_start_web_ui_subprocess", error=str(e))
            return False
    
    def _stop_web_ui_subprocess(self) -> None:
        """Останавливает subprocess с Web UI."""
        if self._web_ui_process is not None:
            try:
                self._web_ui_process.terminate()
                self._web_ui_process.wait(timeout=5)
                logger.info("web ui subprocess stopped")
            except Exception as e:
                logger.warning("failed to stop web ui subprocess", error=str(e))
                with contextlib.suppress(Exception):
                    self._web_ui_process.kill()
            finally:
                self._web_ui_process = None

    async def run(self) -> None:
        """Запускает WS endpoint и держит процесс живым.

        Инициализирует DI контейнер и поднимает WS endpoint.

        Пример использования:
            await ACPHttpServer().run()
        """
        if self.storage is None:
            from .storage import InMemoryStorage
            self.storage = InMemoryStorage()

        logger.debug(
            "creating DI container",
            llm_provider=self.config.llm.provider,
            storage_type=type(self.storage).__name__,
        )

        self._app_container = make_container(
            config=self.config,
            storage=self.storage,
            require_auth=self.require_auth,
            auth_api_key=self.auth_api_key,
        )

        app = web.Application()
        app.router.add_get("/acp/ws", self.handle_ws_request)
        
        if self.enable_web:
            app.router.add_get("/", self.handle_web_ui_request)
            web_ui_started = self._start_web_ui_subprocess()
            if web_ui_started and self._web_ui_url:
                logger.info(
                    "web ui enabled with textual-web",
                    main_url=f"http://{self.host}:{self.port}/",
                    web_ui_url=self._web_ui_url,
                )
            else:
                logger.info(
                    "web ui enabled (fallback mode)",
                    url=f"http://{self.host}:{self.port}/",
                )

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host=self.host, port=self.port)
        await site.start()

        logger.info(
            "server started",
            host=self.host,
            port=self.port,
            endpoint="/acp/ws",
        )

        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            self._stop_web_ui_subprocess()
            logger.info("server shutting down")
            await runner.cleanup()
            if self._app_container is not None:
                await self._app_container.close()

    async def handle_web_ui_request(self, request: web.Request) -> web.Response:
        """Обрабатывает запрос на Web UI.
        
        Если textual-web установлен, возвращает Web UI.
        Иначе возвращает информативную страницу с инструкциями.
        
        Пример использования:
            # вызывается aiohttp автоматически на GET /
        """
        from .web_app import get_fallback_html, is_web_ui_available
        
        # Если subprocess с textual-web запущен и URL получен - показываем redirect/iframe
        web_ui_running = (
            self._web_ui_process is not None
            and self._web_ui_process.poll() is None
            and self._web_ui_url
        )
        if web_ui_running:
            # Subprocess работает - редиректим на облачный URL или показываем iframe
            web_ui_url = self._web_ui_url
            html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CodeLab - Web UI</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html, body {{ height: 100%; overflow: hidden; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0d1117;
        }}
        .loading {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            color: #e4e4e4;
            text-align: center;
        }}
        .loading h2 {{ margin-bottom: 16px; color: #00d4ff; }}
        .spinner {{
            width: 40px;
            height: 40px;
            border: 3px solid #333;
            border-top-color: #00d4ff;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 16px;
        }}
        @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
        iframe {{
            width: 100%;
            height: 100%;
            border: none;
        }}
        .fallback-link {{
            margin-top: 24px;
            font-size: 0.875rem;
            color: #666;
        }}
        .fallback-link a {{ color: #00d4ff; }}
    </style>
</head>
<body>
    <div class="loading" id="loading">
        <div class="spinner"></div>
        <h2>🔬 CodeLab Web UI</h2>
        <p>Загрузка TUI интерфейса...</p>
        <p class="fallback-link">
            Не загружается? <a href="{web_ui_url}" target="_blank">Открыть напрямую</a>
        </p>
    </div>
    <iframe 
        id="webui" 
        src="{web_ui_url}"
        onload="document.getElementById('loading').style.display='none';"
        style="display: block;">
    </iframe>
</body>
</html>
"""
            return web.Response(text=html, content_type="text/html")
        
        elif is_web_ui_available():
            # textual-web установлен, но subprocess не запущен
            html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CodeLab - Web UI</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #e4e4e4;
        }}
        .container {{
            max-width: 600px;
            padding: 40px;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 16px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }}
        h1 {{ font-size: 2rem; margin-bottom: 16px; color: #00d4ff; }}
        .status {{
            display: inline-block;
            padding: 4px 12px;
            background: #ffaa00;
            color: #1a1a2e;
            border-radius: 20px;
            font-size: 0.875rem;
            font-weight: 600;
            margin-bottom: 24px;
        }}
        p {{ line-height: 1.7; margin-bottom: 16px; color: #b4b4b4; }}
        pre {{
            background: #0d1117;
            padding: 16px;
            border-radius: 8px;
            overflow-x: auto;
            margin: 16px 0;
        }}
        code {{ font-family: 'Fira Code', monospace; }}
        .url {{ color: #00ff88; }}
    </style>
</head>
<body>
    <div class="container">
        <span class="status">⚠️ Web UI не запущен</span>
        <h1>🔬 CodeLab</h1>
        <p>Textual Web установлен, но процесс Web UI не запустился.</p>
        <p>Запустите вручную (публикация через Ganglion):</p>
        <pre><code>textual-web --run \
"python -m codelab.client.tui.app --host {self.host} --port {self.port}"</code></pre>
        <p>Или используйте TUI клиент:</p>
        <pre><code>codelab connect --host {self.host} --port {self.port}</code></pre>
        <p>WebSocket endpoint: <span class="url">ws://{self.host}:{self.port}/acp/ws</span></p>
    </div>
</body>
</html>
"""
            return web.Response(text=html, content_type="text/html")
        else:
            # Textual Web не установлен, показываем fallback страницу
            html = get_fallback_html(self.host, self.port)
            return web.Response(text=html, content_type="text/html")

    async def handle_ws_request(self, request: web.Request) -> web.WebSocketResponse:
        """Обрабатывает WebSocket-сессию с поддержкой update-потока.

        Пример использования:
            # вызывается aiohttp автоматически на GET /acp/ws
        """
        connection_id = str(uuid.uuid4())[:8]
        remote_addr = request.remote or "unknown"
        start_time = time.time()

        logger.info(
            "ws connection request received",
            connection_id=connection_id,
            remote_addr=remote_addr,
        )

        logger.info(
            "ws connection established",
            connection_id=connection_id,
            remote_addr=remote_addr,
        )

        ws = web.WebSocketResponse(
            max_msg_size=self.config.websocket.max_msg_size,
            heartbeat=self.config.websocket.heartbeat_interval,
        )
        await ws.prepare(request)

        async def send_rpc_request(request_dict: dict) -> None:
            """Отправляет JSON-RPC request клиенту."""
            async with ws_send_lock:
                if not ws.closed:
                    await ws.send_json(request_dict)

        # Создаём ClientRPCService вручную (требует runtime callback)
        client_rpc_service = ClientRPCService(
            send_request_callback=send_rpc_request,
            client_capabilities={},
        )

        deferred_prompt_tasks: dict[str, asyncio.Task[None]] = {}
        prompt_request_tasks: set[asyncio.Task[None]] = set()
        initialized = False
        ws_send_lock = asyncio.Lock()

        conn_logger = logger.bind(connection_id=connection_id)

        # Используем REQUEST scope для этого WebSocket соединения
        if self._app_container is None:
            conn_logger.error("app container not initialized")
            await ws.close()
            return ws

        # Устанавливаем ClientRPCService в holder перед созданием REQUEST scope
        from .rpc_holder import ClientRPCServiceHolder
        holder = await self._app_container.get(ClientRPCServiceHolder)
        holder.service = client_rpc_service

        async with self._app_container() as request_scope:
            protocol = await request_scope.get(ACPProtocol)

            async def _send_outcome(
                outcome: ProtocolOutcome,
                *,
                request_id: str | None,
            ) -> None:
                """Отправляет notifications/response/followups в рамках одного lock."""
                async with ws_send_lock:
                    if ws.closed:
                        return

                    for notification in outcome.notifications:
                        notification_json = notification.to_json()
                        await ws.send_str(notification_json)
                        conn_logger.debug(
                            "notification sent",
                            method=notification.method,
                            payload=_truncate_payload(notification_json),
                        )

                    if outcome.response is not None:
                        response_json = outcome.response.to_json()
                        await ws.send_str(response_json)
                        conn_logger.debug(
                            "response sent",
                            request_id=request_id,
                            has_error=outcome.response.error is not None,
                            payload=_truncate_payload(response_json),
                        )

                    for followup_response in outcome.followup_responses:
                        followup_json = followup_response.to_json()
                        await ws.send_str(followup_json)
                        conn_logger.debug(
                            "followup response sent",
                            request_id=followup_response.id,
                            payload=_truncate_payload(followup_json),
                        )

            async def _finalize_outcome_and_send(
                *,
                method_name: str | None,
                session_id: str | None,
                request_id: str | None,
                outcome: ProtocolOutcome,
            ) -> None:
                """Применяет post-processing outcome и отправляет его в WS."""
                if method_name == "session/cancel" and session_id is not None:
                    task = deferred_prompt_tasks.pop(session_id, None)
                    if task is not None:
                        task.cancel()

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
                            ws=ws,
                            protocol=protocol,
                            session_id=session_id,
                            deferred_prompt_tasks=deferred_prompt_tasks,
                            connection_id=connection_id,
                        )
                    )

                await _send_outcome(outcome, request_id=request_id)

                if outcome.pending_tool_execution is not None:
                    pending = outcome.pending_tool_execution
                    conn_logger.info(
                        "scheduling pending tool execution in background",
                        session_id=pending.session_id,
                        tool_call_id=pending.tool_call_id,
                    )

                    async def _execute_tool_in_background() -> None:
                        """Background task для выполнения tool после permission."""
                        try:
                            llm_result = await protocol.execute_pending_tool(
                                session_id=pending.session_id,
                                tool_call_id=pending.tool_call_id,
                            )
                            
                            async with ws_send_lock:
                                for notification in llm_result.notifications:
                                    if not ws.closed:
                                        await ws.send_str(notification.to_json())
                                        conn_logger.debug(
                                            "llm loop notification sent",
                                            method=notification.method,
                                        )

                                if llm_result.pending_permission:
                                    conn_logger.debug(
                                        "llm loop deferred for permission",
                                        session_id=pending.session_id,
                                    )
                                    return
                                
                                stop_reason = llm_result.stop_reason or "end_turn"
                                turn_completion = await protocol.complete_active_turn(
                                    pending.session_id, stop_reason=stop_reason
                                )
                                if turn_completion is not None and not ws.closed:
                                    await ws.send_str(turn_completion.to_json())
                                    conn_logger.debug(
                                        "turn completion sent after llm loop",
                                        session_id=pending.session_id,
                                        stop_reason=stop_reason,
                                    )
                        except Exception as exc:
                            conn_logger.error(
                                "background tool execution failed",
                                session_id=pending.session_id,
                                tool_call_id=pending.tool_call_id,
                                error=str(exc),
                            )

                    asyncio.create_task(_execute_tool_in_background())

                if method_name == "shutdown":
                    conn_logger.info("shutdown requested")
                    await ws.close()

            async def _process_prompt_request_in_background(
                *,
                acp_request: ACPMessage,
                method_name: str,
                session_id: str | None,
                request_id: str | None,
            ) -> None:
                """Выполняет `session/prompt` в фоне, не блокируя receive-loop."""
                try:
                    outcome = await protocol.handle(acp_request)
                    conn_logger.info(
                        "request received",
                        method=method_name,
                        request_id=request_id,
                        session_id=session_id,
                    )
                    await _finalize_outcome_and_send(
                        method_name=method_name,
                        session_id=session_id,
                        request_id=request_id,
                        outcome=outcome,
                    )
                except Exception as exc:
                    conn_logger.error(
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
                    await _send_outcome(error_outcome, request_id=request_id)

            try:
                async for message in ws:
                    if message.type == WSMsgType.TEXT:
                        method_name: str | None = None
                        session_id: str | None = None
                        request_id: str | None = None
                        try:
                            acp_request = ACPMessage.from_json(message.data)
                            method_name = acp_request.method
                            request_id = str(acp_request.id) if acp_request.id is not None else None

                            conn_logger.debug(
                                "message received",
                                payload=_truncate_payload(message.data),
                            )

                            if method_name == "initialize":
                                initialized = True
                                if isinstance(acp_request.params, dict):
                                    caps = acp_request.params.get("clientCapabilities", {})
                                    if isinstance(caps, dict):
                                        client_rpc_service._capabilities = caps
                                        conn_logger.debug(
                                            "client_rpc_service capabilities updated",
                                            capabilities=caps,
                                        )
                            elif not initialized:
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
                                await _send_outcome(outcome, request_id=request_id)
                                continue
                            if isinstance(acp_request.params, dict):
                                raw_session_id = acp_request.params.get("sessionId")
                                if isinstance(raw_session_id, str):
                                    session_id = raw_session_id
                            if method_name == "session/prompt":
                                prompt_task = asyncio.create_task(
                                    _process_prompt_request_in_background(
                                        acp_request=acp_request,
                                        method_name=method_name,
                                        session_id=session_id,
                                        request_id=request_id,
                                    )
                                )
                                prompt_request_tasks.add(prompt_task)
                                prompt_task.add_done_callback(
                                    lambda finished_task: prompt_request_tasks.discard(
                                        finished_task
                                    )
                                )
                                conn_logger.debug(
                                    "prompt request scheduled in background",
                                    request_id=request_id,
                                    session_id=session_id,
                                )
                                continue

                            if method_name is None and acp_request.id is not None:
                                conn_logger.debug(
                                    "response received, routing to handle_client_response",
                                    request_id=request_id,
                                )
                                outcome = await protocol.handle_client_response(acp_request)
                            else:
                                outcome = await protocol.handle(acp_request)

                            conn_logger.info(
                                "request received",
                                method=method_name,
                                request_id=request_id,
                                session_id=session_id,
                            )
                        except Exception as exc:
                            conn_logger.error(
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
                        await _finalize_outcome_and_send(
                            method_name=method_name,
                            session_id=session_id,
                            request_id=request_id,
                            outcome=outcome,
                        )
                        if method_name == "shutdown":
                            break
                    elif message.type == WSMsgType.ERROR:
                        conn_logger.warning(
                            "ws_error",
                            exception=str(ws.exception()) if ws.exception() else None,
                            peer=request.remote,
                        )
                        break
                    elif message.type in {WSMsgType.CLOSE, WSMsgType.CLOSING}:
                        break
            finally:
                if prompt_request_tasks:
                    conn_logger.info(
                        "cleaning up prompt request tasks",
                        pending_tasks_count=len(prompt_request_tasks),
                    )
                    for prompt_task in list(prompt_request_tasks):
                        if not prompt_task.done():
                            prompt_task.cancel()
                    await asyncio.gather(*prompt_request_tasks, return_exceptions=True)
                    prompt_request_tasks.clear()

                if deferred_prompt_tasks:
                    conn_logger.info(
                        "cleaning up deferred prompt tasks",
                        pending_tasks_count=len(deferred_prompt_tasks),
                    )
                    for session_id_to_cancel, task_to_cancel in list(deferred_prompt_tasks.items()):
                        if not task_to_cancel.done():
                            task_to_cancel.cancel()
                            conn_logger.debug(
                                "deferred prompt task cancelled",
                                session_id=session_id_to_cancel,
                            )
                        deferred_prompt_tasks.pop(session_id_to_cancel, None)

                cancelled_turns_count = await protocol.cancel_active_turns_on_disconnect()
                if cancelled_turns_count > 0:
                    conn_logger.info(
                        "active turns cancelled on disconnect",
                        cancelled_turns_count=cancelled_turns_count,
                    )

                if client_rpc_service is not None:
                    cancelled_rpc_count = client_rpc_service.cancel_all_pending_requests(
                        reason="WS connection closed before client response",
                    )
                    if cancelled_rpc_count > 0:
                        conn_logger.info(
                            "pending client rpc cancelled on disconnect",
                            cancelled_rpc_count=cancelled_rpc_count,
                        )

                duration = time.time() - start_time
                conn_logger.info(
                    "ws connection closed",
                    duration=round(duration, 3),
                    pending_deferred_tasks=len(deferred_prompt_tasks),
                )

        return ws

    async def _complete_deferred_prompt(
        self,
        *,
        ws: web.WebSocketResponse,
        protocol: ACPProtocol,
        session_id: str,
        deferred_prompt_tasks: dict[str, asyncio.Task[None]],
        connection_id: str,
    ) -> None:
        """Завершает отложенный `session/prompt` и отправляет финальный response.

        Метод нужен для demo-эмуляции in-flight turn, который можно отменить через
        `session/cancel` до отправки финального `stopReason`.

        Включает механизмы:
        - Timeout обработки (30 сек по умолчанию)
        - Graceful обработка исключений
        - Очистка состояния при любом исходе
        - Детальное логирование жизненного цикла

        Пример использования:
            task = asyncio.create_task(server._complete_deferred_prompt(...))
        """

        conn_logger = logger.bind(connection_id=connection_id, session_id=session_id)

        try:
            # Небольшая задержка оставляет окно для входящего `session/cancel`.
            await asyncio.sleep(0.05)

            # Выполняем завершение turn с timeout
            try:
                response = await protocol.complete_active_turn(session_id, stop_reason="end_turn")
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

            # Отправляем response если он есть и соединение еще живо
            if response is not None and not ws.closed:
                try:
                    await ws.send_str(response.to_json())
                    conn_logger.info("deferred prompt completed successfully")
                except Exception as exc:
                    conn_logger.error(
                        "deferred prompt send error",
                        error=str(exc),
                        exc_info=True,
                    )
            elif ws.closed:
                conn_logger.debug("deferred prompt skipped (websocket closed)")
            else:
                conn_logger.debug("deferred prompt skipped (no response)")

        except asyncio.CancelledError:
            # Нормальная ветка: отмена задачи при `session/cancel`.
            conn_logger.info("deferred prompt cancelled by client")
            # Попробуем получить response из session.pending_prompt_response
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
                    if not ws.closed:
                        await ws.send_str(response.to_json())
                        conn_logger.info("deferred prompt cancelled response sent")
            except Exception as exc:
                conn_logger.debug(
                    "deferred prompt cancelled response error",
                    error=str(exc),
                )
            return
        except Exception as exc:
            # Неожиданное исключение - логируем, но не пробрасываем
            conn_logger.error(
                "deferred prompt unexpected error",
                error=str(exc),
                exc_info=True,
            )
        finally:
            # Гарантированная очистка из словаря
            removed = deferred_prompt_tasks.pop(session_id, None)
            if removed is not None:
                conn_logger.debug("deferred prompt task removed from tracking")
