## 1. HTTP Transport Implementation

- [x] 1.1 Создать `HttpTransport` класс в `server/mcp/transport.py` с aiohttp.ClientSession
- [x] 1.2 Реализовать `connect()`, `send_request()`, `disconnect()` методы
- [x] 1.3 Добавить обработку HTTP headers из конфигурации
- [x] 1.4 Обработка ошибок: connection refused, timeout, HTTP errors
- [x] 1.5 Написать unit тесты для HttpTransport (mock aiohttp)
- [x] 1.6 Написать integration тесты с mock MCP HTTP сервером

## 2. SSE Transport Implementation

- [x] 2.1 Создать `SseTransport` класс в `server/mcp/transport.py`
- [x] 2.2 Реализовать SSE event parsing (data:, event:, id: lines)
- [x] 2.3 Реализовать `connect()`, `send_request()`, `disconnect()` методы
- [x] 2.4 Добавить warning logging о deprecated status
- [x] 2.5 Написать unit тесты для SseTransport
- [x] 2.6 Написать integration тесты с mock MCP SSE сервером

## 3. MCP Server Config Update

- [x] 3.1 Обновить `MCPServerConfig` модель: добавить `type`, `url`, `headers` поля
- [x] 3.2 Добавить валидацию: stdio требует `command`, HTTP/SSE требует `url`
- [x] 3.3 Обновить `get_env_dict()` → `get_connection_params()` method
- [x] 3.4 Написать тесты для валидации конфигурации

## 4. MCPClient — Resources Support

- [x] 4.1 Добавить `list_resources()` метод → `resources/list`
- [x] 4.2 Добавить `read_resource(uri)` метод → `resources/read`
- [x] 4.3 Создать модели: `MCPResource`, `MCPListResourcesResult`, `MCPReadResourceResult`
- [x] 4.4 Кэширование ресурсов в `_resources_cache`
- [x] 4.5 Написать unit тесты для resources methods
- [x] 4.6 Написать integration тесты с mock MCP сервером (resources)

## 5. MCPClient — Prompts Support

- [x] 5.1 Добавить `list_prompts()` метод → `prompts/list`
- [x] 5.2 Добавить `get_prompt(name, arguments)` метод → `prompts/get`
- [x] 5.3 Создать модели: `MCPPrompt`, `MCPListPromptsResult`, `MCPGetPromptResult`
- [x] 5.4 Кэширование промптов в `_prompts_cache`
- [x] 5.5 Написать unit тесты для prompts methods
- [x] 5.6 Написать integration тесты с mock MCP сервером (prompts)

## 6. MCPClient — Notification Handling

- [x] 6.1 Добавить `_notification_queue: asyncio.Queue` в MCPClient
- [x] 6.2 Реализовать `_process_notifications()` background task
- [x] 6.3 Добавить `register_handler(method, callback)` метод
- [x] 6.4 Обработка `notifications/tools/list_changed` → refresh tools
- [x] 6.5 Логирование всех notifications с DEBUG level
- [x] 6.6 Написать unit тесты для notification handling

## 7. MCPManager — Auto-Reconnect

- [x] 7.1 Добавить retry configuration: `max_retries`, `initial_delay`, `max_delay`, `backoff_multiplier`
- [x] 7.2 Реализовать `reconnect_with_backoff()` с exponential backoff + jitter
- [x] 7.3 Добавить `_state` tracking: READY, FAILED, RECONNECTING
- [x] 7.4 Health check mechanism: periodic ping каждые 60s
- [x] 7.5 Обработка FAILED state: graceful degradation, error reporting
- [x] 7.6 Написать unit тесты для reconnect logic
- [x] 7.7 Написать integration тесты с fault injection (kill subprocess)

## 8. Integration with ACP Protocol

- [x] 8.1 Обновить `agentCapabilities.mcpCapabilities` в initialize response
- [x] 8.2 Обновить `_initialize_mcp_servers()` для поддержки HTTP/SSE транспортов
- [x] 8.3 Интеграция MCP resources с ACP ContentBlock types
- [x] 8.4 Интеграция MCP prompts с session/prompt flow
- [x] 8.5 Обновить `AgentOrchestrator._build_system_message()` для resources/prompts info
- [x] 8.6 Написать integration тесты для полного MCP flow

## 9. Testing & Documentation

- [x] 9.1 Создать mock MCP сервер с HTTP/SSE endpoints для тестов
- [x] 9.2 Написать ~200+ тестов для всех новых функций
- [x] 9.3 Обновить `doc/architecture/ACP_IMPLEMENTATION_VERIFICATION.md`
- [x] 9.4 Добавить Mermaid диаграммы для новой архитектуры MCP
- [x] 9.5 Запустить `make check` — все тесты должны проходить
- [x] 9.6 Code review: ruff, ty, pytest coverage report
