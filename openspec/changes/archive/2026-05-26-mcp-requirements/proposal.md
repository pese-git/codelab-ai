## Why

ACP spec требует поддержки MCP (Model Context Protocol) для подключения агента к внешним MCP серверам через различные транспорты. Текущая реализация поддерживает только stdio transport и tools capability. Согласно спецификации ACP Protocol (раздел 03 Session Setup, раздел 02 Initialization), агенты **MUST** поддерживать stdio transport и **SHOULD** поддерживать HTTP transport для совместимости с современными MCP серверами.

## What Changes

- **Новые транспорты MCP**: HTTP и SSE транспорты для подключения к MCP серверам (сейчас только stdio)
- **MCP capabilities расширение**: Поддержка MCP resources (resources/list, resources/read) и prompts (prompts/list, prompts/get) помимо текущих tools
- **Auto-reconnect**: Автоматическое переподключение к MCP серверам при обрыве соединения
- **Server notifications**: Обработка server-initiated notifications (tools/list_changed)
- **Capability advertisement**: Корректное объявление `mcpCapabilities.http` и `mcpCapabilities.sse` в initialize response

## Capabilities

### New Capabilities
- `mcp-http-transport`: HTTP transport для MCP серверов с поддержкой headers и authentication
- `mcp-sse-transport`: SSE transport для MCP серверов (deprecated в MCP spec, но требуется для обратной совместимости)
- `mcp-resources`: Поддержка MCP resources (resources/list, resources/read)
- `mcp-prompts`: Поддержка MCP prompts (prompts/list, prompts/get)
- `mcp-auto-reconnect`: Автоматическое переподключение к MCP серверам с retry/backoff
- `mcp-server-notifications`: Обработка server-initiated notifications (tools/list_changed, etc.)

### Modified Capabilities
- `session-setup`: Изменение требований к MCP подключению — теперь включает HTTP/SSE транспорты
- `initialization`: Обновление `mcpCapabilities` для отражения реальной поддержки транспортов

## Impact

**Затронутые файлы:**
- `server/mcp/transport.py` — новые HTTP/SSE transport классы
- `server/mcp/client.py` — поддержка resources, prompts, auto-reconnect
- `server/mcp/manager.py` — reconnect logic, notification handling
- `server/mcp/models.py` — новые модели для HTTP/SSE config, resources, prompts
- `server/protocol/core.py` — обновление capability advertisement
- `server/protocol/handlers/session.py` — обработка MCP серверов с разными транспортами

**Новые зависимости:** aiohttp (уже есть), httpx (для HTTP transport), sse-starlette (для SSE)

**Тесты:** ~200+ новых тестов для транспортов, resources, prompts, reconnect
