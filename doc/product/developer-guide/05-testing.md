# Тестирование CodeLab

> Руководство по запуску и написанию тестов для CodeLab.

## Обзор

CodeLab имеет ~2200 тестов, покрывающих клиентскую и серверную части, включая unit, integration и E2E тесты.

```
tests/
├── client/                 # Тесты клиента (~1100)
│   ├── domain/
│   ├── application/
│   ├── infrastructure/
│   ├── presentation/
│   └── tui/
├── server/                 # Тесты сервера (~700)
│   ├── protocol/
│   ├── agent/
│   ├── tools/
│   ├── storage/
│   ├── mcp/
│   └── e2e/               # E2E тесты (24)
└── conftest.py
```

## Запуск тестов

### Полный набор проверок

```bash
# Из корня репозитория
make check

# Или вручную
cd codelab
uv run ruff check .
uv run ty check
uv run python -m pytest
```

### Запуск тестов

```bash
# Все тесты
uv run python -m pytest

# Только серверные тесты
uv run python -m pytest tests/server/

# Только клиентские тесты
uv run python -m pytest tests/client/

# Тесты с покрытием
uv run python -m pytest --cov=codelab --cov-report=html

# Конкретный тест
uv run python -m pytest tests/server/test_prompt_orchestrator.py -v

# Тесты по маркеру
uv run python -m pytest -m "asyncio"
uv run python -m pytest -m "slow"
```

### E2E тесты

```bash
# Все E2E тесты
uv run python -m pytest tests/server/e2e/

# Конкретный E2E тест
uv run python -m pytest tests/server/e2e/test_e2e_text_content.py -v
```

## Структура тестов

### Unit тесты

Тестируют отдельные компоненты в изоляции:

```python
import pytest
from codelab.server.protocol.handlers.state_manager import StateManager

@pytest.mark.asyncio
async def test_state_manager_create_turn():
    manager = StateManager()
    turn = manager.create_active_turn()
    assert turn is not None
    assert turn.tool_calls == []
```

### Integration тесты

Тестируют взаимодействие компонентов:

```python
@pytest.mark.asyncio
async def test_session_lifecycle():
    storage = InMemoryStorage()
    protocol = ACPProtocol(storage=storage, ...)
    
    # Создание сессии
    result = await protocol.handle(ACPMessage.request("session/new", {}))
    session_id = result.response["result"]["sessionId"]
    
    # Загрузка сессии
    result = await protocol.handle(ACPMessage.request("session/load", {"sessionId": session_id}))
    assert result.response["result"]["sessionId"] == session_id
```

### E2E тесты

Тестируют полный цикл обработки контента:

```python
@pytest.mark.asyncio
async def test_e2e_text_content():
    # ToolExecutor → ContentExtractor → ContentValidator → ContentFormatter
    result = await executor.execute("fs/read_text_file", {"path": "test.txt"})
    content = extractor.extract(result)
    validation = validator.validate(content)
    formatted = formatter.format_for_openai(content, "call_123")
    
    assert validation.is_valid
    assert formatted["role"] == "tool"
    assert "content" in formatted
```

## Категории тестов

### Серверные тесты

| Категория | Файлы | Описание |
|-----------|-------|----------|
| Protocol | `test_protocol.py`, `test_prompt_orchestrator.py` | Обработчики методов ACP |
| Agent | `test_agent_orchestrator.py`, `test_naive_agent.py` | LLM агент |
| Tools | `test_tool_registry.py`, `test_filesystem_executor.py`, `test_terminal_executor.py` | Инструменты |
| Storage | `test_storage_memory.py`, `test_storage_json_file.py` | Хранилище сессий |
| MCP | `test_mcp_client.py`, `test_mcp_manager.py`, `test_mcp_tool_adapter.py`, `test_transport_http.py`, `test_manager_reconnect.py`, `test_client_notifications.py`, `test_client_resources_prompts.py`, `test_models_config.py`, `test_mcp_integration.py`, `test_mcp_executor.py`, `test_session_runtime.py` | MCP интеграция (150+ тестов) |
| Content | `test_content_extraction.py`, `test_content_formatting.py`, `test_content_validator.py` | Content pipeline |
| Permissions | `test_permission_manager.py`, `test_permission_flow.py`, `test_permission_policy_persistence.py` | Система разрешений (51 тест) |

### Клиентские тесты

| Категория | Файлы | Описание |
|-----------|-------|----------|
| Domain | `test_entities.py`, `test_events.py` | Сущности и события |
| Application | `test_use_cases.py`, `test_session_coordinator.py` | Use Cases |
| Infrastructure | `test_transport.py`, `test_background_receive_loop.py`, `test_event_bus.py` | Инфраструктура |
| Presentation | `test_chat_view_model.py`, `test_observable.py` | ViewModels |
| TUI | `test_tui_chat_view.py`, `test_tui_sidebar.py`, `test_tui_*.py` | TUI компоненты |
| MVVM | `test_tui_*_mvvm.py` | MVVM интеграция (82 теста) |

### E2E тесты (24 теста)

| Файл | Тесты | Описание |
|------|-------|----------|
| `test_e2e_text_content.py` | 4 | Text content pipeline |
| `test_e2e_diff_content.py` | 4 | Diff content pipeline |
| `test_e2e_image_content.py` | 4 | Image content pipeline |
| `test_e2e_audio_content.py` | 4 | Audio content pipeline |
| `test_e2e_embedded_content.py` | 4 | Embedded content pipeline |
| `test_e2e_resource_link_content.py` | 4 | Resource link content pipeline |

## Фикстуры

### Общие фикстуры

```python
@pytest.fixture
def mock_llm_provider():
    provider = MockLLMProvider()
    provider.set_response("Hello, world!")
    return provider

@pytest.fixture
def in_memory_storage():
    return InMemoryStorage()

@pytest.fixture
def event_bus():
    return EventBus()
```

### E2E фикстуры

```python
@pytest.fixture
def content_extractor():
    return ContentExtractor()

@pytest.fixture
def content_validator():
    return ContentValidator()

@pytest.fixture
def content_formatter():
    return ContentFormatter()
```

## Написание тестов

### AAA паттерн

```python
@pytest.mark.asyncio
async def test_example():
    # Arrange
    manager = StateManager()
    
    # Act
    turn = manager.create_active_turn()
    
    # Assert
    assert turn is not None
```

### Тестирование Observable

```python
@pytest.mark.asyncio
async def test_observable_updates():
    vm = ChatViewModel(event_bus=EventBus(), logger=mock_logger)
    updates = []
    vm.messages.subscribe(updates.append)
    
    vm.messages.set([Message(role="user", content="Hello")])
    
    assert len(updates) == 1
    assert updates[0][0].role == "user"
```

### Тестирование EventBus

```python
@pytest.mark.asyncio
async def test_event_bus_publish_subscribe():
    bus = EventBus()
    received = []
    
    bus.subscribe(SessionCreatedEvent, lambda e: received.append(e))
    await bus.publish(SessionCreatedEvent(session_id="123"))
    
    assert len(received) == 1
    assert received[0].session_id == "123"
```

## Качество кода

### Линтинг

```bash
uv run ruff check .
uv run ruff check --fix .  # Автоисправление
```

### Type checking

```bash
uv run ty check
```

### Форматирование

```bash
uv run ruff format .
```

## Покрытие кода

```bash
# Генерация отчёта
uv run python -m pytest --cov=codelab --cov-report=html

# Открыть отчёт
open htmlcov/index.html
```

**Целевое покрытие:** 85%+ для критических путей.

## MCP тестирование

### Категории MCP тестов

| Категория | Файлы | Описание |
|-----------|-------|----------|
| Client | `test_mcp_client.py` | MCPClient lifecycle, initialize, tools |
| Manager | `test_mcp_manager.py`, `test_manager_reconnect.py` | MCPManager, add/remove server, reconnect |
| Transport | `test_transport_http.py` | HttpTransport, SseTransport, StdioTransport |
| Models | `test_models_config.py` | MCPServerConfig validation, retry config |
| Notifications | `test_client_notifications.py` | MCP notification handling |
| Resources/Prompts | `test_client_resources_prompts.py` | list_resources, read_resource, list_prompts, get_prompt |
| Tool Adapter | `test_mcp_tool_adapter.py` | adapt_tools, kind inference, namespaced names |
| Executor | `test_mcp_executor.py` | MCPToolExecution |
| Integration | `test_mcp_integration.py` | End-to-end MCP с реальным stdio сервером |
| Runtime | `test_session_runtime.py` | SessionRuntimeRegistry lifecycle |

### Unit тесты MCP

```python
@pytest.mark.asyncio
async def test_mcp_client_lifecycle():
    config = MCPServerConfig(
        name="test",
        command="echo",
        args=["hello"]
    )
    client = MCPClient(config)
    await client.connect()
    await client.initialize()
    tools = await client.list_tools()
    await client.disconnect()
    assert client.state == MCPClientState.CLOSED

@pytest.mark.asyncio
async def test_mcp_tool_adapter_kind_inference():
    adapter = MCPToolAdapter("test", mock_client)
    
    # ToolAnnotations
    tool = MCPTool(
        name="read_data",
        annotations=MCPToolAnnotations(read_only_hint=True)
    )
    definition = adapter.adapt_tools([tool])[0]
    assert definition.kind == "read"
    
    # Name heuristic
    tool = MCPTool(name="create_file")
    definition = adapter.adapt_tools([tool])[0]
    assert definition.kind == "execute"
    
    # Fallback
    tool = MCPTool(name="unknown")
    definition = adapter.adapt_tools([tool])[0]
    assert definition.kind == "other"

@pytest.mark.asyncio
async def test_mcp_tool_adapter_namespaced_name():
    name = MCPToolAdapter.create_namespaced_name("filesystem", "read_file")
    assert name == "mcp:filesystem:read_file"
    
    parsed = MCPToolAdapter.parse_namespaced_name(name)
    assert parsed == ("mcp", "filesystem", "read_file")

@pytest.mark.asyncio
async def test_mcp_config_validation():
    # Stdio требует command
    with pytest.raises(ValueError):
        MCPServerConfig(name="test", type="stdio")
    
    # HTTP требует url
    with pytest.raises(ValueError):
        MCPServerConfig(name="test", type="http")
    
    # Valid config
    config = MCPServerConfig(name="test", type="http", url="http://localhost")
    assert config.type == "http"
```

### Integration тесты MCP

```python
@pytest.mark.asyncio
async def test_mcp_manager_with_real_stdio_server():
    manager = MCPManager("test_session")
    config = MCPServerConfig(
        name="filesystem",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    )
    tools = await manager.add_server(config)
    assert len(tools) > 0
    
    result = await manager.call_tool(
        "mcp:filesystem:read_file",
        {"path": "/tmp/test.txt"}
    )
    assert result.success
    await manager.shutdown()

@pytest.mark.asyncio
async def test_mcp_reconnect_with_backoff():
    manager = MCPManager("test_session")
    config = MCPServerConfig(
        name="unreliable",
        command="false",
        max_retries=3,
        initial_delay=0.1
    )
    with pytest.raises(MCPManagerError):
        await manager.add_server(config)

@pytest.mark.asyncio
async def test_session_runtime_registry():
    registry = SessionRuntimeRegistry()
    
    state = await registry.get_or_create("session_123")
    assert state.mcp_manager is None
    
    manager = MCPManager("session_123")
    await registry.set_mcp_manager("session_123", manager)
    
    state = await registry.get("session_123")
    assert state.mcp_manager is manager
    
    await registry.remove("session_123")
    assert await registry.get("session_123") is None
```

### Mock MCP сервер для тестов

```python
class MockMCPServer:
    """Mock MCP сервер для интеграционных тестов."""
    
    async def handle_stdio(self):
        while True:
            line = await asyncio.stdin.readline()
            if not line:
                break
            request = json.loads(line)
            response = self._handle_request(request)
            print(json.dumps(response), flush=True)
    
    def _handle_request(self, request):
        method = request.get("method")
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "mock", "version": "1.0"}
                }
            }
        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {
                    "tools": [
                        {
                            "name": "echo",
                            "description": "Echo input",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"text": {"type": "string"}}
                            }
                        }
                    ]
                }
            }
```

### Запуск MCP тестов

```bash
# Все MCP тесты
uv run python -m pytest tests/server/mcp/ -v

# Конкретная категория
uv run python -m pytest tests/server/mcp/test_transport_http.py -v
uv run python -m pytest tests/server/mcp/test_manager_reconnect.py -v

# Integration тесты (могут быть медленными)
uv run python -m pytest tests/server/mcp/test_mcp_integration.py -v

# С покрытием
uv run python -m pytest tests/server/mcp/ --cov=codelab.server.mcp
```

## См. также

- [Архитектура](01-architecture.md) — общая архитектура системы
- [Разработка клиента](02-client-development.md) — детали реализации клиента
- [Разработка сервера](03-server-development.md) — детали реализации сервера
- [Вклад в проект](06-contributing.md) — как внести вклад
