"""Простой MCP сервер для интеграционных тестов.

Эмулирует sqlite MCP сервер с инструментами:
- query: выполнение SQL SELECT запросов (read-only)
- exec: выполнение SQL INSERT/UPDATE/DELETE (destructive)

Запускается как stdio subprocess, общается через JSON-RPC 2.0.
"""

import asyncio
import json
import sys


def make_response(request_id: int | str, result: dict) -> str:
    """Создать JSON-RPC ответ."""
    return json.dumps({
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    })


def make_error_response(request_id: int | str, code: int, message: str) -> str:
    """Создать JSON-RPC ответ с ошибкой."""
    return json.dumps({
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    })


def send_response(response: str) -> None:
    """Отправить ответ в stdout."""
    sys.stdout.write(response + "\n")
    sys.stdout.flush()


async def handle_initialize(request_id: int | str, params: dict) -> None:
    """Обработать запрос initialize."""
    send_response(make_response(request_id, {
        "protocolVersion": "2024-11-05",
        "capabilities": {
            "tools": {"listChanged": True},
        },
        "serverInfo": {
            "name": "test-sqlite-mcp",
            "version": "1.0.0",
        },
        "instructions": "Test SQLite MCP server for integration tests",
    }))


async def handle_tools_list(request_id: int | str) -> None:
    """Обработать запрос tools/list."""
    send_response(make_response(request_id, {
        "tools": [
            {
                "name": "query",
                "description": "Execute a SQL SELECT query (read-only)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "sql": {
                            "type": "string",
                            "description": "SQL SELECT query",
                        }
                    },
                    "required": ["sql"],
                },
                "annotations": {
                    "title": "Query Database",
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
            },
            {
                "name": "exec",
                "description": "Execute a SQL INSERT/UPDATE/DELETE statement",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "sql": {
                            "type": "string",
                            "description": "SQL statement",
                        }
                    },
                    "required": ["sql"],
                },
                "annotations": {
                    "title": "Execute SQL",
                    "readOnlyHint": False,
                    "destructiveHint": True,
                    "idempotentHint": False,
                    "openWorldHint": False,
                },
            },
            {
                "name": "unknown_tool",
                "description": "A tool with no recognizable pattern",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        ],
    }))


async def handle_tools_call(request_id: int | str, params: dict) -> None:
    """Обработать запрос tools/call."""
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    if tool_name == "query":
        sql = arguments.get("sql", "SELECT 1")
        send_response(make_response(request_id, {
            "content": [
                {"type": "text", "text": f"Query result: {sql} -> [(1, 'test')]"},
            ],
            "isError": False,
        }))
    elif tool_name == "exec":
        sql = arguments.get("sql", "INSERT INTO test VALUES (1)")
        send_response(make_response(request_id, {
            "content": [
                {"type": "text", "text": f"Executed: {sql} (1 row affected)"},
            ],
            "isError": False,
        }))
    elif tool_name == "unknown_tool":
        send_response(make_response(request_id, {
            "content": [
                {"type": "text", "text": "Unknown tool executed"},
            ],
            "isError": False,
        }))
    else:
        send_response(make_error_response(request_id, -32601, f"Unknown tool: {tool_name}"))


async def handle_notification(method: str, params: dict) -> None:
    """Обработать нотификацию (игнорируем)."""
    pass


async def main() -> None:
    """Основной цикл сервера."""
    # Читаем stdin построчно
    loop = asyncio.get_event_loop()

    while True:
        try:
            # Читаем строку из stdin
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break

            line = line.strip()
            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            method = data.get("method", "")
            request_id = data.get("id")
            params = data.get("params", {})

            # Нотификации не имеют id
            if request_id is None:
                await handle_notification(method, params)
                continue

            # Диспетчеризация запросов
            if method == "initialize":
                await handle_initialize(request_id, params)
            elif method == "tools/list":
                await handle_tools_list(request_id)
            elif method == "tools/call":
                await handle_tools_call(request_id, params)
            else:
                msg = f"Method not found: {method}"
                send_response(make_error_response(request_id, -32601, msg))

        except Exception as e:
            # Пишем ошибку в stderr
            sys.stderr.write(f"Error: {e}\n")
            sys.stderr.flush()


if __name__ == "__main__":
    asyncio.run(main())
