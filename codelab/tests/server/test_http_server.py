from __future__ import annotations

import asyncio
import socket
from typing import Any

import aiohttp
import pytest
from aiohttp import ClientSession, web

from codelab.server.http_server import ACPHttpServer
from codelab.server.messages import ACPMessage
from codelab.server.protocol import ACPProtocol, ProtocolOutcome


def _get_free_port() -> int:
    """Возвращает свободный локальный TCP-порт для тестового сервера."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _start_test_server(
    *,
    require_auth: bool = False,
    auth_api_key: str | None = None,
) -> tuple[web.AppRunner, int]:
    """Поднимает aiohttp-приложение с ACP WS handler."""

    port = _get_free_port()
    server = ACPHttpServer(
        host="127.0.0.1",
        port=port,
        require_auth=require_auth,
        auth_api_key=auth_api_key,
    )
    app = web.Application()
    app.router.add_get("/acp/ws", server.handle_ws_request)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=port)
    await site.start()
    return runner, port


async def _ws_initialize(ws: Any) -> None:
    """Выполняет обязательный ACP initialize в рамках WS-соединения."""

    await ws.send_json(
        {
            "jsonrpc": "2.0",
            "id": "init_1",
            "method": "initialize",
            "params": {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": True,
                },
            },
        }
    )
    payload = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
    assert payload["id"] == "init_1"
    assert payload.get("error") is None


@pytest.mark.asyncio
async def test_ws_prompt_with_permission_selection_finishes_with_end_turn() -> None:
    runner, port = await _start_test_server()

    try:
        async with ClientSession() as session:
            ws = await session.ws_connect(f"http://127.0.0.1:{port}/acp/ws")
            try:
                await _ws_initialize(ws)
                await ws.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": "new_1",
                        "method": "session/new",
                        "params": {"cwd": "/tmp", "mcpServers": []},
                    }
                )
                new_payload = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
                session_id = new_payload["result"]["sessionId"]

                await ws.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": "prompt_1",
                        "method": "session/prompt",
                        "params": {
                            "sessionId": session_id,
                            "prompt": [{"type": "text", "text": "/tool-pending run"}],
                        },
                    }
                )

                received_prompt_response: dict | None = None
                for _ in range(12):
                    payload = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
                    if payload.get("method") == "session/request_permission":
                        await ws.send_json(
                            {
                                "jsonrpc": "2.0",
                                "id": payload["id"],
                                "result": {
                                    "outcome": {
                                        "outcome": "selected",
                                        "optionId": "allow_once",
                                    },
                                },
                            }
                        )
                        continue
                    if payload.get("id") == "prompt_1":
                        received_prompt_response = payload
                        break

                assert received_prompt_response is not None
                assert received_prompt_response["result"] == {"stopReason": "end_turn"}
            finally:
                await ws.close()
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_ws_cancel_finishes_deferred_prompt_with_cancelled() -> None:
    runner, port = await _start_test_server()

    try:
        async with ClientSession() as session:
            ws = await session.ws_connect(f"http://127.0.0.1:{port}/acp/ws")
            try:
                await _ws_initialize(ws)
                await ws.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": "new_1",
                        "method": "session/new",
                        "params": {"cwd": "/tmp", "mcpServers": []},
                    }
                )
                new_payload = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
                session_id = new_payload["result"]["sessionId"]

                await ws.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": "prompt_1",
                        "method": "session/prompt",
                        "params": {
                            "sessionId": session_id,
                            "prompt": [{"type": "text", "text": "/tool-pending run"}],
                        },
                    }
                )
                permission_request_seen = False
                for _ in range(8):
                    payload = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
                    if payload.get("method") == "session/request_permission":
                        permission_request_seen = True
                        break
                assert permission_request_seen

                await ws.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": "cancel_1",
                        "method": "session/cancel",
                        "params": {"sessionId": session_id},
                    }
                )

                responses: dict[str, dict] = {}
                for _ in range(12):
                    payload = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
                    response_id = payload.get("id")
                    if isinstance(response_id, str):
                        responses[response_id] = payload
                    if "prompt_1" in responses and "cancel_1" in responses:
                        break

                assert responses["cancel_1"]["result"] is None
                assert responses["prompt_1"]["result"] == {"stopReason": "cancelled"}
            finally:
                await ws.close()
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_ws_rejects_session_methods_before_initialize() -> None:
    runner, port = await _start_test_server()

    try:
        async with ClientSession() as session:
            ws = await session.ws_connect(f"http://127.0.0.1:{port}/acp/ws")
            try:
                await ws.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": "new_1",
                        "method": "session/new",
                        "params": {"cwd": "/tmp", "mcpServers": []},
                    }
                )
                payload = await asyncio.wait_for(ws.receive_json(), timeout=1.0)

                assert payload["id"] == "new_1"
                assert payload["error"]["code"] == -32000
            finally:
                await ws.close()
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_ws_requires_authenticate_when_server_auth_enabled() -> None:
    runner, port = await _start_test_server(require_auth=True)

    try:
        async with ClientSession() as session:
            ws = await session.ws_connect(f"http://127.0.0.1:{port}/acp/ws")
            try:
                await _ws_initialize(ws)

                await ws.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": "new_1",
                        "method": "session/new",
                        "params": {"cwd": "/tmp", "mcpServers": []},
                    }
                )
                unauthorized = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
                assert unauthorized["id"] == "new_1"
                assert unauthorized["error"]["message"] == "auth_required"

                await ws.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": "auth_1",
                        "method": "authenticate",
                        "params": {"methodId": "local"},
                    }
                )
                authenticated = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
                assert authenticated["id"] == "auth_1"
                assert authenticated["result"] == {}

                await ws.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": "new_2",
                        "method": "session/new",
                        "params": {"cwd": "/tmp", "mcpServers": []},
                    }
                )
                authorized = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
                assert authorized["id"] == "new_2"
                assert isinstance(authorized.get("result", {}).get("sessionId"), str)
            finally:
                await ws.close()
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_ws_authenticate_requires_api_key_when_configured() -> None:
    runner, port = await _start_test_server(require_auth=True, auth_api_key="top-secret")

    try:
        async with ClientSession() as session:
            ws = await session.ws_connect(f"http://127.0.0.1:{port}/acp/ws")
            try:
                await _ws_initialize(ws)

                await ws.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": "auth_missing",
                        "method": "authenticate",
                        "params": {"methodId": "local"},
                    }
                )
                missing_key = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
                assert missing_key["id"] == "auth_missing"
                assert missing_key["error"]["message"] == "Invalid params: apiKey is required"

                await ws.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": "auth_wrong",
                        "method": "authenticate",
                        "params": {"methodId": "local", "apiKey": "wrong"},
                    }
                )
                wrong_key = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
                assert wrong_key["id"] == "auth_wrong"
                assert wrong_key["error"]["message"] == "auth_failed"

                await ws.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": "auth_ok",
                        "method": "authenticate",
                        "params": {"methodId": "local", "apiKey": "top-secret"},
                    }
                )
                authenticated = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
                assert authenticated["id"] == "auth_ok"
                assert authenticated["result"] == {}
            finally:
                await ws.close()
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_ws_prompt_fs_read_roundtrip_finishes_with_end_turn() -> None:
    runner, port = await _start_test_server()

    try:
        async with ClientSession() as session:
            ws = await session.ws_connect(f"http://127.0.0.1:{port}/acp/ws")
            try:
                await ws.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": "init_1",
                        "method": "initialize",
                        "params": {
                            "protocolVersion": 1,
                            "clientCapabilities": {
                                "fs": {"readTextFile": True, "writeTextFile": False},
                                "terminal": False,
                            },
                        },
                    }
                )
                _ = await asyncio.wait_for(ws.receive_json(), timeout=1.0)

                await ws.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": "new_1",
                        "method": "session/new",
                        "params": {"cwd": "/tmp", "mcpServers": []},
                    }
                )
                new_payload = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
                session_id = new_payload["result"]["sessionId"]

                await ws.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": "prompt_1",
                        "method": "session/prompt",
                        "params": {
                            "sessionId": session_id,
                            "prompt": [{"type": "text", "text": "/fs-read README.md"}],
                        },
                    }
                )

                received_prompt_response: dict | None = None
                for _ in range(12):
                    payload = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
                    if payload.get("method") == "fs/read_text_file":
                        await ws.send_json(
                            {
                                "jsonrpc": "2.0",
                                "id": payload["id"],
                                "result": {"content": "hello"},
                            }
                        )
                        continue
                    if payload.get("id") == "prompt_1":
                        received_prompt_response = payload
                        break

                assert received_prompt_response is not None
                assert received_prompt_response["result"] == {"stopReason": "end_turn"}
            finally:
                await ws.close()
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_ws_prompt_terminal_roundtrip_finishes_with_end_turn() -> None:
    runner, port = await _start_test_server()

    try:
        async with ClientSession() as session:
            ws = await session.ws_connect(f"http://127.0.0.1:{port}/acp/ws")
            try:
                await ws.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": "init_1",
                        "method": "initialize",
                        "params": {
                            "protocolVersion": 1,
                            "clientCapabilities": {
                                "fs": {"readTextFile": False, "writeTextFile": False},
                                "terminal": True,
                            },
                        },
                    }
                )
                _ = await asyncio.wait_for(ws.receive_json(), timeout=1.0)

                await ws.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": "new_1",
                        "method": "session/new",
                        "params": {"cwd": "/tmp", "mcpServers": []},
                    }
                )
                new_payload = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
                session_id = new_payload["result"]["sessionId"]

                await ws.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": "prompt_1",
                        "method": "session/prompt",
                        "params": {
                            "sessionId": session_id,
                            "prompt": [{"type": "text", "text": "/term-run ls"}],
                        },
                    }
                )

                received_prompt_response: dict | None = None
                for _ in range(20):
                    payload = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
                    method = payload.get("method")
                    if method == "terminal/create":
                        await ws.send_json(
                            {
                                "jsonrpc": "2.0",
                                "id": payload["id"],
                                "result": {"terminalId": "term_1"},
                            }
                        )
                        continue
                    if method == "terminal/output":
                        await ws.send_json(
                            {
                                "jsonrpc": "2.0",
                                "id": payload["id"],
                                "result": {"output": "ok"},
                            }
                        )
                        continue
                    if method == "terminal/wait_for_exit":
                        await ws.send_json(
                            {
                                "jsonrpc": "2.0",
                                "id": payload["id"],
                                "result": {"exitCode": 0},
                            }
                        )
                        continue
                    if method == "terminal/release":
                        await ws.send_json(
                            {
                                "jsonrpc": "2.0",
                                "id": payload["id"],
                                "result": {"ok": True},
                            }
                        )
                        continue
                    if payload.get("id") == "prompt_1":
                        received_prompt_response = payload
                        break

                assert received_prompt_response is not None
                assert received_prompt_response["result"] == {"stopReason": "end_turn"}
            finally:
                await ws.close()
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_ws_prompt_is_processed_in_background_and_does_not_block_ping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Проверяет, что in-flight prompt не блокирует обработку других запросов."""

    original_handle = ACPProtocol.handle

    async def delayed_prompt_handle(self: ACPProtocol, message: ACPMessage) -> ProtocolOutcome:
        if message.method == "session/prompt":
            await asyncio.sleep(0.3)
            return ProtocolOutcome(
                response=ACPMessage.response(message.id, {"stopReason": "end_turn"})
            )
        return await original_handle(self, message)

    monkeypatch.setattr(ACPProtocol, "handle", delayed_prompt_handle)

    runner, port = await _start_test_server()

    try:
        async with ClientSession() as session:
            ws = await session.ws_connect(f"http://127.0.0.1:{port}/acp/ws")
            try:
                await _ws_initialize(ws)
                await ws.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": "new_1",
                        "method": "session/new",
                        "params": {"cwd": "/tmp", "mcpServers": []},
                    }
                )
                new_payload = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
                session_id = new_payload["result"]["sessionId"]

                await ws.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": "prompt_1",
                        "method": "session/prompt",
                        "params": {
                            "sessionId": session_id,
                            "prompt": [{"type": "text", "text": "slow prompt"}],
                        },
                    }
                )
                await ws.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": "ping_1",
                        "method": "ping",
                        "params": {},
                    }
                )

                first_response = await asyncio.wait_for(ws.receive_json(), timeout=0.2)
                assert first_response.get("id") == "ping_1"

                second_response = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
                assert second_response.get("id") == "prompt_1"
                assert second_response.get("result") == {"stopReason": "end_turn"}
            finally:
                await ws.close()
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_oversized_message_rejected() -> None:
    """Тест: сообщение, превышающее лимит размера, приводит к закрытию соединения."""
    from codelab.server.config import AppConfig, WebSocketConfig

    port = _get_free_port()
    config = AppConfig(
        websocket=WebSocketConfig(max_msg_size=1024, heartbeat_interval=30.0),
    )
    server = ACPHttpServer(host="127.0.0.1", port=port, config=config)
    app = web.Application()
    app.router.add_get("/acp/ws", server.handle_ws_request)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=port)
    await site.start()

    try:
        async with ClientSession() as session:
            ws = await session.ws_connect(f"http://127.0.0.1:{port}/acp/ws")
            try:
                oversized = "x" * (2 * 1024)
                await ws.send_str(oversized)

                msg = await asyncio.wait_for(ws.receive(), timeout=5.0)
                assert msg.type in {
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.ERROR,
                }
            finally:
                if not ws.closed:
                    await ws.close()
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_message_within_limit_accepted() -> None:
    """Тест: сообщение в пределах лимита принимается нормально."""
    from codelab.server.config import AppConfig, WebSocketConfig

    port = _get_free_port()
    config = AppConfig(
        websocket=WebSocketConfig(max_msg_size=4 * 1024 * 1024, heartbeat_interval=30.0),
    )
    server = ACPHttpServer(host="127.0.0.1", port=port, config=config)
    app = web.Application()
    app.router.add_get("/acp/ws", server.handle_ws_request)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=port)
    await site.start()

    try:
        async with ClientSession() as session:
            ws = await session.ws_connect(f"http://127.0.0.1:{port}/acp/ws")
            try:
                await _ws_initialize(ws)

                normal_msg = "x" * 1024
                await ws.send_str(normal_msg)

                msg = await asyncio.wait_for(ws.receive(), timeout=2.0)
                assert msg.type == aiohttp.WSMsgType.TEXT
                assert '"error"' in msg.data
                assert "Parse error" in msg.data
            finally:
                await ws.close()
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_prompt_text_too_long_rejected() -> None:
    """Тест: промпт с текстом, превышающим лимит длины, отклоняется."""
    from codelab.server.protocol.handlers.prompt import MAX_PROMPT_TEXT_LENGTH

    runner, port = await _start_test_server()

    try:
        async with ClientSession() as session:
            ws = await session.ws_connect(f"http://127.0.0.1:{port}/acp/ws")
            try:
                await _ws_initialize(ws)
                await ws.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": "new_1",
                        "method": "session/new",
                        "params": {"cwd": "/tmp", "mcpServers": []},
                    }
                )
                new_payload = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
                session_id = new_payload["result"]["sessionId"]

                long_text = "x" * (MAX_PROMPT_TEXT_LENGTH + 1)
                await ws.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": "prompt_1",
                        "method": "session/prompt",
                        "params": {
                            "sessionId": session_id,
                            "prompt": [{"type": "text", "text": long_text}],
                        },
                    }
                )

                response = await asyncio.wait_for(ws.receive_json(), timeout=2.0)
                assert response.get("id") == "prompt_1"
                assert response.get("error") is not None
                assert "too long" in response["error"]["message"]
            finally:
                await ws.close()
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_prompt_text_within_length_limit_accepted() -> None:
    """Тест: промпт с текстом в пределах лимита длины принимается."""
    from codelab.server.protocol.handlers.prompt import MAX_PROMPT_TEXT_LENGTH

    runner, port = await _start_test_server()

    try:
        async with ClientSession() as session:
            ws = await session.ws_connect(f"http://127.0.0.1:{port}/acp/ws")
            try:
                await _ws_initialize(ws)
                await ws.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": "new_1",
                        "method": "session/new",
                        "params": {"cwd": "/tmp", "mcpServers": []},
                    }
                )
                new_payload = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
                session_id = new_payload["result"]["sessionId"]

                normal_text = "x" * (MAX_PROMPT_TEXT_LENGTH - 1)
                await ws.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": "prompt_1",
                        "method": "session/prompt",
                        "params": {
                            "sessionId": session_id,
                            "prompt": [{"type": "text", "text": normal_text}],
                        },
                    }
                )

                while True:
                    response = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
                    if response.get("id") == "prompt_1":
                        break

                assert response.get("error") is None
                assert response.get("result") is not None
            finally:
                await ws.close()
    finally:
        await runner.cleanup()
