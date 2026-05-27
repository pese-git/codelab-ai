## Context

Текущая реализация MCP поддерживает только stdio transport и tools capability. Согласно ACP spec, агенты MUST поддерживать stdio и SHOULD поддерживать HTTP transport. Текущий `MCPServerConfig` содержит только поля для stdio (`command`, `args`, `env`), нет поддержки `type`, `url`, `headers` для HTTP/SSE транспортов.

Архитектура MCP модуля:
- `transport.py` — StdioTransport (404 строки)
- `client.py` — MCPClient (398 строк, только tools methods)
- `manager.py` — MCPManager (402 строки, no reconnect logic)
- `tool_adapter.py` — MCPToolAdapter (298 строк)
- `models.py` — Pydantic модели (374 строки)

## Goals / Non-Goals

**Goals:**
- Добавить HTTP и SSE транспорты для MCP серверов
- Поддержка MCP resources и prompts (list + read/get)
- Автоматическое переподключение с exponential backoff
- Обработка server-initiated notifications
- Корректное capability advertisement в initialize response

**Non-Goals:**
- MCP roots/list (не требуется для MVP)
- MCP sampling/createMessage (client-side feature, не нужен агенту)
- Streamable HTTP transport (draft spec, не требуется ACP)

## Decisions

### 1. HTTP Transport Implementation
**Decision:** Использовать `aiohttp.ClientSession` для HTTP transport (уже есть в зависимостях проекта)

**Rationale:**
- aiohttp уже используется в проекте для WebSocket transport
- Поддерживает async/await, connection pooling, headers
- Альтернатива `httpx` — требует новой зависимости, не дает преимуществ

**Architecture:**
```python
class HttpTransport:
    async def connect(self) -> None:
        self._session = aiohttp.ClientSession(base_url=self._config.url)
    
    async def send_request(self, method: str, params: dict) -> dict:
        async with self._session.post("/", json=request) as response:
            return await response.json()
```

### 2. SSE Transport Implementation
**Decision:** Использовать `aiohttp` с SSE event streaming

**Rationale:**
- SSE — это HTTP connection с `text/event-stream` content type
- aiohttp поддерживает streaming responses
- SSE deprecated в MCP spec, но нужен для обратной совместимости

**Architecture:**
```python
class SseTransport:
    async def connect(self) -> None:
        self._response = await self._session.get("/sse")
        async for line in self._response.content:
            # Parse SSE event
```

### 3. Resources and Prompts Integration
**Decision:** Добавить отдельные методы в `MCPClient` для resources и prompts, не смешивать с tools

**Rationale:**
- Clear separation of concerns
- Resources и prompts имеют разные lifecycle и caching requirements
- Легче тестировать и поддерживать

**New methods:**
- `MCPClient.list_resources()` → `resources/list`
- `MCPClient.read_resource(uri)` → `resources/read`
- `MCPClient.list_prompts()` → `prompts/list`
- `MCPClient.get_prompt(name, arguments)` → `prompts/get`

### 4. Auto-Reconnect Strategy
**Decision:** Exponential backoff с jitter для предотвращения thundering herd

**Rationale:**
- Standard pattern для distributed systems
- Jitter предотвращает синхронные retry storms при массовом fallback
- Настраиваемые parameters через config

**Implementation:**
```python
async def reconnect_with_backoff(self):
    delay = self._initial_delay
    for attempt in range(self._max_retries):
        await asyncio.sleep(delay + random.uniform(0, delay * 0.1))  # 10% jitter
        try:
            await self.connect()
            return
        except Exception:
            delay = min(delay * self._backoff_multiplier, self._max_delay)
```

### 5. Notification Handling
**Decision:** Event-driven architecture с `asyncio.Queue` для notifications

**Rationale:**
- Notifications могут приходить в любое время, не только в response на request
- Queue decouples transport от business logic
- Легко добавить multiple handlers

**Architecture:**
```python
class MCPClient:
    def __init__(self):
        self._notification_queue: asyncio.Queue = asyncio.Queue()
        self._notification_handlers: dict[str, list[Callable]] = {}
    
    async def _process_notifications(self):
        while True:
            notification = await self._notification_queue.get()
            handlers = self._notification_handlers.get(notification.method, [])
            for handler in handlers:
                await handler(notification.params)
```

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|------|--------|------------|
| HTTP/SSE транспорты увеличивают сложность MCP модуля | Medium | Четкое разделение: transport/client/manager слои |
| Auto-reconnect может создать infinite loop | High | Max retries limit + FAILED state |
| Resources/prompts могут быть large | Medium | Size limits + streaming support |
| SSE deprecated — future maintenance burden | Low | Логировать warning, документировать deprecated status |
| Notification handlers могут блокировать queue | Medium | Async handlers + timeout |

## Migration Plan

**Phase 1:** HTTP/SSE transports (недели 1-2)
- Добавить `HttpTransport` и `SseTransport` классы
- Обновить `MCPServerConfig` для поддержки `type`, `url`, `headers`
- Тесты: unit + integration с mock MCP серверами

**Phase 2:** Resources и Prompts (недели 3-4)
- Добавить методы в `MCPClient` для resources/prompts
- Интеграция с ACP Content types
- Тесты: unit + integration

**Phase 3:** Auto-reconnect и Notifications (недели 5-6)
- Implement exponential backoff с jitter
- Event-driven notification handling
- Тесты: fault injection, network partition simulation

**Rollback Strategy:**
- Feature flags для каждого транспорта
- Fallback на stdio если HTTP/SSE недоступен
- Graceful degradation при ошибках reconnect
