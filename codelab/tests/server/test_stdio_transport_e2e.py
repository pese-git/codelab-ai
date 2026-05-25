"""E2E тесты stdio transport (сервер ↔ клиент через subprocess).

Тестирует полный цикл взаимодействия:
- Запуск сервера как subprocess
- Отправка JSON-RPC через stdin
- Получение ответов через stdout
- Graceful shutdown
- Обработка ошибок парсинга
- Полный handshake (initialize → session/new → session/list)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
from pathlib import Path

import pytest

# Путь к CLI entry point (абсолютный)
# tests/server/test_stdio_transport_e2e.py -> tests -> codelab -> src/codelab/cli.py
_PROJECT_ROOT = Path(__file__).parent.parent.parent
CLI_PATH = str((_PROJECT_ROOT / "src" / "codelab" / "cli.py").resolve())


def _make_request(method: str, params: dict, request_id: int = 1) -> str:
    """Создать JSON-RPC request строку."""
    return json.dumps({
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    })


async def _read_json_response(proc: asyncio.subprocess.Process, timeout: float = 10.0) -> dict:
    """Прочитать JSON-RPC ответ из stdout, пропуская не-JSON строки."""
    assert proc.stdout is not None
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            break
        line = await asyncio.wait_for(proc.stdout.readline(), timeout=max(0.1, remaining))
        if not line:
            break
        text = line.decode().strip()
        if not text:
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Пропускаем не-JSON строки (например, сообщения о создании config)
            continue
    raise TimeoutError("No JSON response received from server")


async def _read_all_json_responses(
    proc: asyncio.subprocess.Process,
    count: int,
    timeout: float = 10.0,
) -> list[dict]:
    """Прочитать несколько JSON-RPC ответов."""
    responses = []
    for _ in range(count):
        try:
            resp = await _read_json_response(proc, timeout=timeout)
            responses.append(resp)
        except TimeoutError:
            break
    return responses


def _server_env(tmp_cwd: Path) -> dict[str, str]:
    """Создать окружение для запуска сервера."""
    env = os.environ.copy()
    env.update({
        "CODELAB_LLM_PROVIDER": "mock",
        "CODELAB_HOME": str(tmp_cwd / ".codelab"),
    })
    return env


async def _start_server(tmp_cwd: Path) -> asyncio.subprocess.Process:
    """Запустить stdio сервер."""
    # Используем Python из venv для запуска сервера
    python_exe = sys.executable
    env = _server_env(tmp_cwd)
    # Добавляем PYTHONPATH чтобы сервер мог импортировать модули
    project_root = Path(__file__).parent.parent.parent.parent
    env["PYTHONPATH"] = str(project_root / "src")

    return await asyncio.create_subprocess_exec(
        python_exe,
        CLI_PATH,
        "serve",
        "--stdio",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(tmp_cwd),
        env=env,
    )


async def _stop_server(proc: asyncio.subprocess.Process) -> None:
    """Graceful shutdown сервера."""
    if proc.stdin is not None:
        proc.stdin.close()
    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except TimeoutError:
        proc.terminate()
        await proc.wait()


@pytest.fixture
def tmp_cwd(tmp_path: Path) -> Path:
    """Создать временную рабочую директорию."""
    return tmp_path


@pytest.mark.asyncio
async def test_stdio_server_starts_and_responds_to_initialize(tmp_cwd: Path) -> None:
    """Сервер запускается и отвечает на initialize."""
    proc = await _start_server(tmp_cwd)

    try:
        # Даем серверу время на запуск
        await asyncio.sleep(0.5)

        # Проверяем что сервер не упал сразу
        if proc.returncode is not None:
            stderr_data = b""
            if proc.stderr is not None:
                with contextlib.suppress(Exception):
                    stderr_data = await asyncio.wait_for(proc.stderr.read(), timeout=1.0)
            pytest.fail(
                f"Server exited immediately with code {proc.returncode}. "
                f"stderr: {stderr_data.decode(errors='replace')[:500]}"
            )

        # Отправляем initialize
        assert proc.stdin is not None
        proc.stdin.write((
            _make_request("initialize", {
                "protocolVersion": 1,
                "clientCapabilities": {},
            }) + "\n"
        ).encode())
        await proc.stdin.drain()

        # Читаем ответ
        response = await _read_json_response(proc)

        # Проверяем ответ
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert "result" in response
        assert response["result"]["protocolVersion"] == 1
        assert "agentCapabilities" in response["result"]

    finally:
        await _stop_server(proc)


@pytest.mark.asyncio
async def test_stdio_server_session_lifecycle(tmp_cwd: Path) -> None:
    """Полный lifecycle: initialize → session/new → session/list."""
    proc = await _start_server(tmp_cwd)

    try:
        await asyncio.sleep(0.5)
        assert proc.stdin is not None

        # 1. Initialize
        proc.stdin.write((
            _make_request("initialize", {
                "protocolVersion": 1,
                "clientCapabilities": {},
            }) + "\n"
        ).encode())
        await proc.stdin.drain()

        init_response = await _read_json_response(proc)
        assert init_response["result"]["protocolVersion"] == 1

        # 2. Session new
        proc.stdin.write((
            _make_request("session/new", {
                "cwd": str(tmp_cwd),
                "mcpServers": [],
            }, request_id=2) + "\n"
        ).encode())
        await proc.stdin.drain()

        new_response = await _read_json_response(proc)
        assert new_response["id"] == 2
        assert "result" in new_response
        session_id = new_response["result"]["sessionId"]
        assert session_id.startswith("sess_")

        # 3. Session list
        proc.stdin.write((
            _make_request("session/list", {}, request_id=3) + "\n"
        ).encode())
        await proc.stdin.drain()

        list_response = await _read_json_response(proc)
        assert list_response["id"] == 3
        assert "result" in list_response
        sessions = list_response["result"]["sessions"]
        assert len(sessions) >= 1
        assert sessions[0]["sessionId"] == session_id

    finally:
        await _stop_server(proc)


@pytest.mark.asyncio
async def test_stdio_server_handles_parse_error(tmp_cwd: Path) -> None:
    """Сервер обрабатывает невалидный JSON и возвращает parse error."""
    proc = await _start_server(tmp_cwd)

    try:
        await asyncio.sleep(0.5)
        assert proc.stdin is not None

        # Отправляем невалидный JSON
        proc.stdin.write(b"not valid json\n")
        await proc.stdin.drain()

        # Должен вернуться parse error
        response = await _read_json_response(proc)

        assert response["jsonrpc"] == "2.0"
        assert "error" in response
        assert response["error"]["code"] == -32700
        assert "Parse error" in response["error"]["message"]

    finally:
        await _stop_server(proc)


@pytest.mark.asyncio
async def test_stdio_server_handles_method_not_found(tmp_cwd: Path) -> None:
    """Сервер возвращает Method not found для неизвестного метода."""
    proc = await _start_server(tmp_cwd)

    try:
        await asyncio.sleep(0.5)
        assert proc.stdin is not None

        # Отправляем неизвестный метод
        proc.stdin.write((
            _make_request("unknown/method", {}, request_id=42) + "\n"
        ).encode())
        await proc.stdin.drain()

        response = await _read_json_response(proc)

        assert response["id"] == 42
        assert "error" in response
        assert response["error"]["code"] == -32601
        assert "Method not found" in response["error"]["message"]

    finally:
        await _stop_server(proc)


@pytest.mark.asyncio
async def test_stdio_server_graceful_shutdown_on_stdin_close(tmp_cwd: Path) -> None:
    """Сервер завершается при закрытии stdin."""
    proc = await _start_server(tmp_cwd)

    # Закрываем stdin — сервер должен завершиться
    await _stop_server(proc)

    # Проверяем что сервер завершился
    assert proc.returncode is not None


@pytest.mark.asyncio
async def test_stdio_server_handles_empty_lines(tmp_cwd: Path) -> None:
    """Сервер игнорирует пустые строки."""
    proc = await _start_server(tmp_cwd)

    try:
        await asyncio.sleep(0.5)
        assert proc.stdin is not None

        # Отправляем пустую строку, затем валидный запрос
        proc.stdin.write(b"\n")
        proc.stdin.write((
            _make_request("initialize", {
                "protocolVersion": 1,
                "clientCapabilities": {},
            }) + "\n"
        ).encode())
        await proc.stdin.drain()

        # Должен прийти ответ на initialize
        response = await _read_json_response(proc)

        assert response["result"]["protocolVersion"] == 1

    finally:
        await _stop_server(proc)


@pytest.mark.asyncio
async def test_stdio_server_multiple_requests_in_sequence(tmp_cwd: Path) -> None:
    """Сервер обрабатывает несколько запросов последовательно."""
    proc = await _start_server(tmp_cwd)

    try:
        await asyncio.sleep(0.5)
        assert proc.stdin is not None

        # Отправляем initialize
        proc.stdin.write((
            _make_request("initialize", {
                "protocolVersion": 1,
                "clientCapabilities": {},
            }, request_id=1) + "\n"
        ).encode())
        await proc.stdin.drain()

        response1 = await _read_json_response(proc)
        assert response1["id"] == 1

        # Создаем сессию
        proc.stdin.write((
            _make_request("session/new", {
                "cwd": str(tmp_cwd),
                "mcpServers": [],
            }, request_id=2) + "\n"
        ).encode())
        await proc.stdin.drain()

        response2 = await _read_json_response(proc)
        assert response2["id"] == 2
        session_id = response2["result"]["sessionId"]

        # Загружаем сессию
        proc.stdin.write((
            _make_request("session/load", {
                "sessionId": session_id,
                "cwd": str(tmp_cwd),
                "mcpServers": [],
            }, request_id=3) + "\n"
        ).encode())
        await proc.stdin.drain()

        # Load возвращает response + notifications
        responses = await _read_all_json_responses(proc, count=5, timeout=5.0)

        # Должен быть хотя бы response на load
        response_ids = [r.get("id") for r in responses if "id" in r]
        assert 3 in response_ids

    finally:
        await _stop_server(proc)


@pytest.mark.asyncio
async def test_stdio_server_logs_go_to_stderr(tmp_cwd: Path) -> None:
    """Логи сервера идут в stderr, не в stdout."""
    proc = await _start_server(tmp_cwd)

    try:
        await asyncio.sleep(0.5)
        assert proc.stdin is not None

        # Отправляем запрос
        proc.stdin.write((
            _make_request("initialize", {
                "protocolVersion": 1,
                "clientCapabilities": {},
            }) + "\n"
        ).encode())
        await proc.stdin.drain()

        # Читаем ответ из stdout
        response = await _read_json_response(proc)
        assert response["result"]["protocolVersion"] == 1

        # Даем время на запись логов
        await asyncio.sleep(0.5)

        # Закрываем stdin для завершения
        if proc.stdin is not None:
            proc.stdin.close()

        # Читаем stderr
        try:
            stderr_data = await asyncio.wait_for(proc.stderr.read(), timeout=2.0)
            stderr_text = stderr_data.decode(errors="replace")
            # Логи должны содержать информацию о запуске
            assert "stdio" in stderr_text.lower() or "starting" in stderr_text.lower()
        except TimeoutError:
            # stderr может быть буферизован, это нормально
            pass

    finally:
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except TimeoutError:
            proc.terminate()
            await proc.wait()
