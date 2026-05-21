"""Unit тесты для ClientRPCService.

Тестирует все методы сервиса, обработку ошибок, проверку capabilities
и сериализацию/десериализацию моделей.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from codelab.server.client_rpc import (
    ClientCapabilityMissingError,
    ClientRPCCancelledError,
    ClientRPCResponseError,
    ClientRPCService,
)


@pytest.fixture
def client_capabilities() -> dict:
    """Capabilities клиента для тестирования."""
    return {
        "fs": {"readTextFile": True, "writeTextFile": True},
        "terminal": True,
    }


@pytest.fixture
def mock_send_request() -> Any:
    """Mock для отправки requests.

    Сохраняет все отправленные requests в sent_requests для проверки.
    """
    sent_requests: list[dict] = []

    async def send(request: dict) -> None:
        sent_requests.append(request)

    send.sent_requests = sent_requests  # type: ignore
    return send


@pytest.fixture
def rpc_service(mock_send_request: Any, client_capabilities: dict) -> ClientRPCService:
    """RPC сервис для тестирования."""
    return ClientRPCService(
        send_request_callback=mock_send_request,
        client_capabilities=client_capabilities,
        timeout=1.0,
    )


# ===== File System Tests =====


@pytest.mark.asyncio
async def test_read_text_file_success(
    rpc_service: ClientRPCService, mock_send_request: Any
) -> None:
    """Тест успешного чтения файла."""
    # Запустить вызов
    task = asyncio.create_task(rpc_service.read_text_file(session_id="sess_123", path="/test.txt"))

    # Дождаться отправки request
    await asyncio.sleep(0.01)

    # Проверить отправленный request
    assert len(mock_send_request.sent_requests) == 1
    request = mock_send_request.sent_requests[0]
    assert request["method"] == "fs/read_text_file"
    assert request["params"]["sessionId"] == "sess_123"
    assert request["params"]["path"] == "/test.txt"
    assert request["jsonrpc"] == "2.0"
    assert "id" in request

    # Симулировать ответ от клиента
    rpc_service.handle_response(
        {"jsonrpc": "2.0", "id": request["id"], "result": {"content": "file content"}}
    )

    # Проверить результат
    content = await task
    assert content == "file content"


@pytest.mark.asyncio
async def test_read_text_file_with_line_and_limit(
    rpc_service: ClientRPCService, mock_send_request: Any
) -> None:
    """Тест чтения файла с параметрами line и limit."""
    task = asyncio.create_task(
        rpc_service.read_text_file(session_id="sess_123", path="/test.txt", line=10, limit=20)
    )

    await asyncio.sleep(0.01)

    request = mock_send_request.sent_requests[0]
    assert request["params"]["line"] == 10
    assert request["params"]["limit"] == 20

    rpc_service.handle_response(
        {"jsonrpc": "2.0", "id": request["id"], "result": {"content": "lines..."}}
    )

    content = await task
    assert content == "lines..."


@pytest.mark.asyncio
async def test_write_text_file_success(
    rpc_service: ClientRPCService, mock_send_request: Any
) -> None:
    """Тест успешной записи файла."""
    task = asyncio.create_task(
        rpc_service.write_text_file(session_id="sess_123", path="/test.txt", content="new content")
    )

    await asyncio.sleep(0.01)

    request = mock_send_request.sent_requests[0]
    assert request["method"] == "fs/write_text_file"
    assert request["params"]["sessionId"] == "sess_123"
    assert request["params"]["path"] == "/test.txt"
    assert request["params"]["content"] == "new content"

    rpc_service.handle_response(
        {"jsonrpc": "2.0", "id": request["id"], "result": {"success": True}}
    )

    result = await task
    assert result is True


@pytest.mark.asyncio
async def test_read_text_file_capability_missing(rpc_service: ClientRPCService) -> None:
    """Тест проверки отсутствующей capability для чтения."""
    rpc_service._capabilities["fs"]["readTextFile"] = False

    with pytest.raises(ClientCapabilityMissingError) as exc_info:
        await rpc_service.read_text_file("sess_123", "/test.txt")

    assert "fs.readTextFile" in str(exc_info.value)


@pytest.mark.asyncio
async def test_write_text_file_capability_missing(rpc_service: ClientRPCService) -> None:
    """Тест проверки отсутствующей capability для записи."""
    rpc_service._capabilities["fs"]["writeTextFile"] = False

    with pytest.raises(ClientCapabilityMissingError) as exc_info:
        await rpc_service.write_text_file("sess_123", "/test.txt", "content")

    assert "fs.writeTextFile" in str(exc_info.value)


# ===== Terminal Tests =====


@pytest.mark.asyncio
async def test_create_terminal_success(
    rpc_service: ClientRPCService, mock_send_request: Any
) -> None:
    """Тест создания терминала."""
    task = asyncio.create_task(rpc_service.create_terminal(session_id="sess_123", command="python"))

    await asyncio.sleep(0.01)

    request = mock_send_request.sent_requests[0]
    assert request["method"] == "terminal/create"
    assert request["params"]["sessionId"] == "sess_123"
    assert request["params"]["command"] == "python"

    rpc_service.handle_response(
        {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {"terminalId": "term_456"},
        }
    )

    terminal_id = await task
    assert terminal_id == "term_456"


@pytest.mark.asyncio
async def test_create_terminal_with_args_and_env(
    rpc_service: ClientRPCService, mock_send_request: Any
) -> None:
    """Тест создания терминала с аргументами и переменными окружения."""
    task = asyncio.create_task(
        rpc_service.create_terminal(
            session_id="sess_123",
            command="python",
            args=["-c", "print('hello')"],
            env={"PYTHONUNBUFFERED": "1"},
            cwd="/home/user",
            output_byte_limit=10000,
        )
    )

    await asyncio.sleep(0.01)

    request = mock_send_request.sent_requests[0]
    assert request["params"]["args"] == ["-c", "print('hello')"]
    assert request["params"]["env"] == {"PYTHONUNBUFFERED": "1"}
    assert request["params"]["cwd"] == "/home/user"
    assert request["params"]["outputByteLimit"] == 10000

    rpc_service.handle_response(
        {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {"terminalId": "term_456"},
        }
    )

    terminal_id = await task
    assert terminal_id == "term_456"


@pytest.mark.asyncio
async def test_terminal_output(rpc_service: ClientRPCService, mock_send_request: Any) -> None:
    """Тест получения output терминала."""
    task = asyncio.create_task(
        rpc_service.terminal_output(session_id="sess_123", terminal_id="term_456")
    )

    await asyncio.sleep(0.01)

    request = mock_send_request.sent_requests[0]
    assert request["method"] == "terminal/output"
    assert request["params"]["sessionId"] == "sess_123"
    assert request["params"]["terminalId"] == "term_456"

    rpc_service.handle_response(
        {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {"output": "hello world", "truncated": False},
        }
    )

    output, truncated, exit_code, signal = await task
    assert output == "hello world"
    assert truncated is False
    assert exit_code is None
    assert signal is None


@pytest.mark.asyncio
async def test_terminal_output_completed(
    rpc_service: ClientRPCService, mock_send_request: Any
) -> None:
    """Тест получения output завершённого терминала."""
    task = asyncio.create_task(
        rpc_service.terminal_output(session_id="sess_123", terminal_id="term_456")
    )

    await asyncio.sleep(0.01)

    request = mock_send_request.sent_requests[0]

    rpc_service.handle_response(
        {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {
                "output": "completed",
                "truncated": False,
                "exitStatus": {"exitCode": 0, "signal": None},
            },
        }
    )

    output, truncated, exit_code, signal = await task
    assert output == "completed"
    assert truncated is False
    assert exit_code == 0
    assert signal is None


@pytest.mark.asyncio
async def test_wait_for_exit(rpc_service: ClientRPCService, mock_send_request: Any) -> None:
    """Тест ожидания завершения команды."""
    task = asyncio.create_task(
        rpc_service.wait_for_exit(session_id="sess_123", terminal_id="term_456")
    )

    await asyncio.sleep(0.01)

    request = mock_send_request.sent_requests[0]
    assert request["method"] == "terminal/wait_for_exit"
    assert request["params"]["sessionId"] == "sess_123"
    assert request["params"]["terminalId"] == "term_456"

    rpc_service.handle_response(
        {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {"exitCode": 0, "signal": None},
        }
    )

    exit_code, signal = await task
    assert exit_code == 0
    assert signal is None


@pytest.mark.asyncio
async def test_wait_for_exit_with_timeout(
    rpc_service: ClientRPCService, mock_send_request: Any
) -> None:
    """Тест ожидания завершения с timeout."""
    task = asyncio.create_task(
        rpc_service.wait_for_exit(session_id="sess_123", terminal_id="term_456", timeout=5.0)
    )

    await asyncio.sleep(0.01)

    request = mock_send_request.sent_requests[0]
    assert request["params"]["timeout"] == 5.0

    rpc_service.handle_response(
        {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {"exitCode": 1, "signal": None},
        }
    )

    exit_code, signal = await task
    assert exit_code == 1
    assert signal is None


@pytest.mark.asyncio
async def test_kill_terminal(rpc_service: ClientRPCService, mock_send_request: Any) -> None:
    """Тест прерывания команды."""
    task = asyncio.create_task(
        rpc_service.kill_terminal(session_id="sess_123", terminal_id="term_456", signal="SIGKILL")
    )

    await asyncio.sleep(0.01)

    request = mock_send_request.sent_requests[0]
    assert request["method"] == "terminal/kill"
    assert request["params"]["sessionId"] == "sess_123"
    assert request["params"]["terminalId"] == "term_456"
    assert request["params"]["signal"] == "SIGKILL"

    rpc_service.handle_response(
        {"jsonrpc": "2.0", "id": request["id"], "result": {"success": True}}
    )

    result = await task
    assert result is True


@pytest.mark.asyncio
async def test_kill_terminal_default_signal(
    rpc_service: ClientRPCService, mock_send_request: Any
) -> None:
    """Тест прерывания команды со стандартным сигналом."""
    task = asyncio.create_task(
        rpc_service.kill_terminal(session_id="sess_123", terminal_id="term_456")
    )

    await asyncio.sleep(0.01)

    request = mock_send_request.sent_requests[0]
    assert request["params"]["signal"] == "SIGTERM"

    rpc_service.handle_response(
        {"jsonrpc": "2.0", "id": request["id"], "result": {"success": True}}
    )

    result = await task
    assert result is True


@pytest.mark.asyncio
async def test_release_terminal(rpc_service: ClientRPCService, mock_send_request: Any) -> None:
    """Тест освобождения ресурсов терминала."""
    task = asyncio.create_task(
        rpc_service.release_terminal(session_id="sess_123", terminal_id="term_456")
    )

    await asyncio.sleep(0.01)

    request = mock_send_request.sent_requests[0]
    assert request["method"] == "terminal/release"
    assert request["params"]["sessionId"] == "sess_123"
    assert request["params"]["terminalId"] == "term_456"

    rpc_service.handle_response(
        {"jsonrpc": "2.0", "id": request["id"], "result": {"success": True}}
    )

    result = await task
    assert result is True


@pytest.mark.asyncio
async def test_terminal_capability_missing(rpc_service: ClientRPCService) -> None:
    """Тест проверки отсутствующей capability для терминала."""
    rpc_service._capabilities["terminal"] = False

    with pytest.raises(ClientCapabilityMissingError) as exc_info:
        await rpc_service.create_terminal("sess_123", "python")

    assert "terminal" in str(exc_info.value)


# ===== Error Handling Tests =====


@pytest.mark.asyncio
async def test_request_cancellation(
    rpc_service: ClientRPCService, mock_send_request: Any
) -> None:
    """Тест отмены конкретного RPC запроса через cancel_request."""
    task = asyncio.create_task(rpc_service.read_text_file("sess_123", "/test.txt"))

    await asyncio.sleep(0.01)

    # Получаем request_id из отправленного запроса
    request = mock_send_request.sent_requests[0]
    request_id = request["id"]

    # Отменяем конкретный запрос
    result = rpc_service.cancel_request(request_id)
    assert result is True

    # Проверяем, что отмена несуществующего запроса возвращает False
    result_nonexistent = rpc_service.cancel_request("nonexistent_id")
    assert result_nonexistent is False

    # Проверяем, что задача завершается с ClientRPCCancelledError
    with pytest.raises(ClientRPCCancelledError):
        await task


@pytest.mark.asyncio
async def test_cancel_all_pending_requests_finishes_waiters(
    rpc_service: ClientRPCService,
) -> None:
    """Тест отмены всех pending RPC при закрытии транспорта."""

    task = asyncio.create_task(rpc_service.read_text_file("sess_123", "/test.txt"))

    await asyncio.sleep(0.01)
    cancelled_count = rpc_service.cancel_all_pending_requests("connection dropped")

    assert cancelled_count == 1
    # После рефакторинга запросы отменяются через cancellation_event
    # и выбрасывают ClientRPCCancelledError
    with pytest.raises(ClientRPCCancelledError):
        await task


@pytest.mark.asyncio
async def test_no_timeout_waiting(
    rpc_service: ClientRPCService, mock_send_request: Any
) -> None:
    """Тест что RPC ожидает бессрочно до получения ответа или отмены.
    
    Проверяет, что запрос не завершается по timeout, а ждёт ответа.
    """
    task = asyncio.create_task(rpc_service.read_text_file("sess_123", "/test.txt"))

    # Ждём дольше чем старый timeout (1 секунда в fixture)
    await asyncio.sleep(0.05)

    # Задача всё ещё выполняется (не завершилась по timeout)
    assert not task.done()

    # Отправляем ответ - запрос должен успешно завершиться
    request = mock_send_request.sent_requests[0]
    rpc_service.handle_response(
        {"jsonrpc": "2.0", "id": request["id"], "result": {"content": "file content"}}
    )

    content = await task
    assert content == "file content"


@pytest.mark.asyncio
async def test_cancel_multiple_pending_requests(
    rpc_service: ClientRPCService, mock_send_request: Any
) -> None:
    """Тест отмены нескольких pending запросов одновременно."""
    # Запускаем несколько запросов
    task1 = asyncio.create_task(rpc_service.read_text_file("sess_123", "/file1.txt"))
    task2 = asyncio.create_task(rpc_service.read_text_file("sess_123", "/file2.txt"))
    task3 = asyncio.create_task(rpc_service.write_text_file("sess_123", "/file3.txt", "content"))

    await asyncio.sleep(0.02)

    # Должны быть 3 pending requests
    cancelled_count = rpc_service.cancel_all_pending_requests("session cancelled")
    assert cancelled_count == 3

    # Все задачи должны завершиться с ошибкой отмены
    with pytest.raises(ClientRPCCancelledError):
        await task1
    with pytest.raises(ClientRPCCancelledError):
        await task2
    with pytest.raises(ClientRPCCancelledError):
        await task3


@pytest.mark.asyncio
async def test_rpc_error_response(rpc_service: ClientRPCService, mock_send_request: Any) -> None:
    """Тест обработки ошибки от клиента."""
    task = asyncio.create_task(rpc_service.read_text_file("sess_123", "/test.txt"))

    await asyncio.sleep(0.01)

    request = mock_send_request.sent_requests[0]

    rpc_service.handle_response(
        {
            "jsonrpc": "2.0",
            "id": request["id"],
            "error": {"code": -32001, "message": "File not found"},
        }
    )

    with pytest.raises(ClientRPCResponseError) as exc_info:
        await task

    assert exc_info.value.code == -32001
    assert "File not found" in str(exc_info.value)


@pytest.mark.asyncio
async def test_rpc_error_with_data(rpc_service: ClientRPCService, mock_send_request: Any) -> None:
    """Тест обработки ошибки с дополнительными данными."""
    task = asyncio.create_task(rpc_service.read_text_file("sess_123", "/test.txt"))

    await asyncio.sleep(0.01)

    request = mock_send_request.sent_requests[0]

    rpc_service.handle_response(
        {
            "jsonrpc": "2.0",
            "id": request["id"],
            "error": {
                "code": -32002,
                "message": "Permission denied",
                "data": {"path": "/test.txt", "permission": "read"},
            },
        }
    )

    with pytest.raises(ClientRPCResponseError) as exc_info:
        await task

    assert exc_info.value.code == -32002
    assert exc_info.value.data == {"path": "/test.txt", "permission": "read"}


@pytest.mark.asyncio
async def test_unknown_response_id(
    rpc_service: ClientRPCService,
) -> None:
    """Тест обработки ответа для неизвестного request_id.

    Функция должна обработать ответ без ошибок, даже если request_id неизвестен.
    """
    # Это не должно выбросить исключение
    rpc_service.handle_response(
        {"jsonrpc": "2.0", "id": "unknown_id", "result": {"content": "data"}}
    )


@pytest.mark.asyncio
async def test_invalid_response_no_result_or_error(
    rpc_service: ClientRPCService, mock_send_request: Any
) -> None:
    """Тест обработки невалидного response без result/error."""
    from codelab.server.client_rpc.exceptions import ClientRPCError

    task = asyncio.create_task(rpc_service.read_text_file("sess_123", "/test.txt"))

    await asyncio.sleep(0.01)

    request = mock_send_request.sent_requests[0]

    rpc_service.handle_response({"jsonrpc": "2.0", "id": request["id"]})

    with pytest.raises(ClientRPCError):
        await task


# ===== Request Format Tests =====


@pytest.mark.asyncio
async def test_json_rpc_format(rpc_service: ClientRPCService, mock_send_request: Any) -> None:
    """Тест формата JSON-RPC request."""
    task = asyncio.create_task(rpc_service.read_text_file("sess_123", "/test.txt"))

    await asyncio.sleep(0.01)

    request = mock_send_request.sent_requests[0]

    # Проверить JSON-RPC формат
    assert request["jsonrpc"] == "2.0"
    assert isinstance(request["id"], str)
    assert "method" in request
    assert "params" in request

    rpc_service.handle_response(
        {"jsonrpc": "2.0", "id": request["id"], "result": {"content": "data"}}
    )

    await task


@pytest.mark.asyncio
async def test_camel_case_serialization(
    rpc_service: ClientRPCService, mock_send_request: Any
) -> None:
    """Тест сериализации camelCase в JSON-RPC."""
    task = asyncio.create_task(
        rpc_service.create_terminal(
            session_id="sess_123",
            command="python",
            output_byte_limit=5000,
        )
    )

    await asyncio.sleep(0.01)

    request = mock_send_request.sent_requests[0]

    # Проверить, что используется camelCase для aliases
    assert "sessionId" in request["params"]
    assert "outputByteLimit" in request["params"]
    assert request["params"]["sessionId"] == "sess_123"
    assert request["params"]["outputByteLimit"] == 5000

    rpc_service.handle_response(
        {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {"terminalId": "term_456"},
        }
    )

    await task


# ===== Multiple Concurrent Requests =====


@pytest.mark.asyncio
async def test_multiple_concurrent_requests(
    rpc_service: ClientRPCService, mock_send_request: Any
) -> None:
    """Тест нескольких одновременных requests."""
    # Запустить несколько задач
    task1 = asyncio.create_task(rpc_service.read_text_file("sess_123", "/file1.txt"))
    task2 = asyncio.create_task(rpc_service.read_text_file("sess_123", "/file2.txt"))
    task3 = asyncio.create_task(rpc_service.write_text_file("sess_123", "/file3.txt", "content"))

    await asyncio.sleep(0.02)

    # Проверить, что все requests отправлены
    assert len(mock_send_request.sent_requests) == 3

    # Получить IDs
    ids = [req["id"] for req in mock_send_request.sent_requests]

    # Ответить в другом порядке
    rpc_service.handle_response({"jsonrpc": "2.0", "id": ids[2], "result": {"success": True}})
    result3 = await task3
    assert result3 is True

    rpc_service.handle_response({"jsonrpc": "2.0", "id": ids[0], "result": {"content": "content1"}})
    result1 = await task1
    assert result1 == "content1"

    rpc_service.handle_response({"jsonrpc": "2.0", "id": ids[1], "result": {"content": "content2"}})
    result2 = await task2
    assert result2 == "content2"
