# План реализации MCP интеграции

**Дата:** 2026-05-26  
**Основано на:** MCP spec (`doc/Model Context Protocol/`), ACP spec (`doc/Agent Client Protocol/`), текущая реализация (`codelab/src/codelab/server/mcp/`)

---

## Текущее состояние

### ✅ Реализовано

| Компонент | Файл | Статус |
|---|---|---|
| StdioTransport | `mcp/transport.py` | Полностью — subprocess, send_request, send_notification, close |
| MCPClient | `mcp/client.py` | Полностью — connect, initialize, list_tools, call_tool, state machine |
| MCPManager | `mcp/manager.py` | Полностью — multi-server lifecycle, add/remove, get_tools, call_tool |
| MCPToolAdapter | `mcp/tool_adapter.py` | Полностью — namespace `mcp:server:tool`, конвертация MCP→ACP |
| JSON-RPC модели | `mcp/models.py` | Полностью — MCPRequest, MCPResponse, MCPError, MCPTool, MCPCallToolResult |
| Content модели | `mcp/models.py` | Полностью — MCPTextContent, MCPImageContent, MCPEmbeddedResource |
| Интеграция в ACP | `protocol/core.py` | Полностью — `_setup_mcp_if_needed()`, MCPManager в SessionState |
| Session lifecycle | `handlers/session.py` | Полностью — MCP серверы подключаются при session/new и session/load |
| Тесты | `tests/server/test_mcp_module.py` | 27 тестов — transport, client, manager, adapter, models |

### ❌ Не реализовано (приоритизировано)

| # | Задача | Приоритет | Описание |
|---|---|---|---|
| 1 | **MCP Tools в LLM Loop** | 🔴 P0 | MCP инструменты не подключены к `LLMLoopStage` — критичный гэп |
| 2 | **MCP Resources** | 🟡 P1 | `resources/list`, `resources/templates/list`, `resources/read` |
| 3 | **MCP Prompts** | 🟡 P1 | `prompts/list`, `prompts/get` |
| 4 | **Tool list change notifications** | 🟡 P1 | `notifications/tools/list_changed` не обрабатывается |
| 5 | **Auto-reconnect** | 🟡 P1 | Нет переподключения при падении MCP сервера |
| 6 | **Image/Resource content в результатах** | 🟢 P2 | Только text извлекается из tool results |
| 7 | **MCP Roots** | 🟢 P2 | `roots/list` capability — client→server |
| 8 | **MCP Sampling** | 🟢 P2 | `sampling/createMessage` — server→client LLM request |
| 9 | **MCP Elicitation** | 🟢 P2 | `elicitation/create` — server→client user input |
| 10 | **Progress notifications** | 🟢 P2 | Progress tokens / progress notifications |
| 11 | **HTTP Transport** | 🟢 P2 | MCP over HTTP (Streamable HTTP) |

---

## Фаза 1: MCP Tools в LLM Loop (P0 — критично)

**Проблема:** MCP инструменты регистрируются через `MCPToolAdapter`, но **не вызываются** из `LLMLoopStage`. Сейчас `ToolRegistry.execute_tool()` работает только для встроенных инструментов (filesystem, terminal).

### 1.1 Интеграция MCP Tools в ToolRegistry

**Файлы:** `server/tools/registry.py`, `server/protocol/handlers/pipeline/stages/llm_loop.py`

**Задача:** При выполнении tool call в `LLMLoopStage`, если инструмент имеет MCP namespace (`mcp:server:tool`), вызывать `MCPManager.call_tool()` вместо `ToolRegistry.execute_tool()`.

**Подзадачи:**
- [ ] 1.1.1 Добавить `mcp_manager` в контекст `LLMLoopStage` (через `PromptOrchestrator`)
- [ ] 1.1.2 В `_process_tool_calls_for_llm_loop()` проверить: если `tool_name` начинается с `mcp:`, делегировать в `MCPManager.call_tool()`
- [ ] 1.1.3 Создать `MCPToolExecutor` — обёртка, адаптирующая `MCPManager.call_tool()` под интерфейс `ToolExecutor`
- [ ] 1.1.4 Обработка MCP content types в результате (text, image, resource) → ACP content format
- [ ] 1.1.5 Тесты: unit + integration (mock MCP server → tool call → LLM loop)

### 1.2 MCP Tools в available_tools для LLM

**Файлы:** `server/agent/orchestrator.py`, `server/agent/naive.py`

**Задача:** При построении `AgentContext`, добавить MCP инструменты из `session_state.mcp_manager.get_all_tools()` в `available_tools`.

**Подзадачи:**
- [ ] 1.2.1 В `_create_agent_context()` добавить MCP tools к `available_tools`
- [ ] 1.2.2 MCP tools должны проходить через `ToolMapping.acp_name_to_llm_name()` для совместимости имён
- [ ] 1.2.3 Тесты: agent context содержит MCP tools, LLM получает их в tools list

### 1.3 MCP Tool Call lifecycle

**Файлы:** `server/protocol/handlers/pipeline/stages/llm_loop.py`, `server/protocol/state.py`

**Задача:** MCP tool calls должны проходить полный lifecycle: pending → in_progress → completed/failed, с notifications.

**Подзадачи:**
- [ ] 1.3.1 MCP tool calls создают `ToolCallState` с `kind="mcp"`
- [ ] 1.3.2 Permission flow для MCP tools (через `PermissionManager`)
- [ ] 1.3.3 Timeout handling для MCP tool calls (настраиваемый per-server)
- [ ] 1.3.4 Error handling: MCP server crash, timeout, invalid response
- [ ] 1.3.5 Тесты: полный lifecycle MCP tool call

---

## Фаза 2: MCP Resources (P1)

**Цель:** Поддержка MCP Resources — пассивных data sources для контекста.

### 2.1 Модели

**Файлы:** `server/mcp/models.py`

**Подзадачи:**
- [ ] 2.1.1 `MCPResource` — uri, name, description, mimeType
- [ ] 2.1.2 `MCPResourceTemplate` — uriTemplate, name, description, mimeType
- [ ] 2.1.3 `MCPListResourcesResult` — resources: list[MCPResource]
- [ ] 2.1.4 `MCPListResourceTemplatesResult` — resourceTemplates: list[MCPResourceTemplate]
- [ ] 2.1.5 `MCPReadResourceParams` — uri: str
- [ ] 2.1.6 `MCPReadResourceResult` — contents: list[MCPResourceContent]
- [ ] 2.1.7 `MCPResourceContent` — uri, mimeType, text?: str, blob?: str

### 2.2 MCPClient — Resources API

**Файлы:** `server/mcp/client.py`

**Подзадачи:**
- [ ] 2.2.1 `list_resources()` → `MCPListResourcesResult`
- [ ] 2.2.2 `list_resource_templates()` → `MCPListResourceTemplatesResult`
- [ ] 2.2.3 `read_resource(uri)` → `MCPReadResourceResult`
- [ ] 2.2.4 Capability checking: `server_capabilities.resources` должен быть declared

### 2.3 MCPManager — Resources

**Файлы:** `server/mcp/manager.py`

**Подзадачи:**
- [ ] 2.3.1 `get_all_resources()` → list всех resources от всех серверов
- [ ] 2.3.2 `read_resource(server_id, uri)` → читать resource с конкретного сервера
- [ ] 2.3.3 Resource URI routing: по uri определить какой сервер обслуживает

### 2.4 Интеграция в ACP

**Файлы:** `server/protocol/handlers/prompt.py`, `server/shared/content/`

**Подзадачи:**
- [ ] 2.4.1 MCP Resources → ACP `ResourceLinkContent` маппинг
- [ ] 2.4.2 При session/load: MCP resources могут быть включены в replay
- [ ] 2.4.3 Тесты: list resources, read resource, content conversion

---

## Фаза 3: MCP Prompts (P1)

**Цель:** Поддержка MCP Prompts — параметризованных prompt templates.

### 3.1 Модели

**Файлы:** `server/mcp/models.py`

**Подзадачи:**
- [ ] 3.1.1 `MCPPrompt` — name, description, arguments: list[MCPPromptArgument]
- [ ] 3.1.2 `MCPPromptArgument` — name, description, required, enum?
- [ ] 3.1.3 `MCPListPromptsResult` — prompts: list[MCPPrompt]
- [ ] 3.1.4 `MCPGetPromptParams` — name: str, arguments: dict
- [ ] 3.1.5 `MCPGetPromptResult` — description, messages: list[MCPPromptMessage]
- [ ] 3.1.6 `MCPPromptMessage` — role: str, content: MCPContent

### 3.2 MCPClient — Prompts API

**Файлы:** `server/mcp/client.py`

**Подзадачи:**
- [ ] 3.2.1 `list_prompts()` → `MCPListPromptsResult`
- [ ] 3.2.2 `get_prompt(name, arguments)` → `MCPGetPromptResult`
- [ ] 3.2.3 Capability checking: `server_capabilities.prompts`

### 3.3 MCPManager — Prompts

**Файлы:** `server/mcp/manager.py`

**Подзадачи:**
- [ ] 3.3.1 `get_all_prompts()` → list всех prompts от всех серверов
- [ ] 3.3.2 `get_prompt(server_id, name, arguments)` → получить prompt с аргументами

### 3.4 Интеграция в ACP

**Файлы:** `server/protocol/handlers/prompt.py`, `server/protocol/handlers/slash_commands/`

**Подзадачи:**
- [ ] 3.4.1 MCP Prompts → ACP slash commands маппинг (каждый prompt становится slash-командой)
- [ ] 3.4.2 При вызове slash-команды: resolve MCP prompt → messages → inject в conversation
- [ ] 3.4.3 Тесты: list prompts, get prompt, slash command integration

---

## Фаза 4: Notifications и Auto-reconnect (P1)

### 4.1 Tool list change notifications

**Файлы:** `server/mcp/transport.py`, `server/mcp/client.py`, `server/mcp/manager.py`

**Подзадачи:**
- [ ] 4.1.1 В `_handle_message()` распознавать `notifications/tools/list_changed`
- [ ] 4.1.2 Callback mechanism: MCPClient → MCPManager при изменении tools
- [ ] 4.1.3 MCPManager → `PromptOrchestrator` → refresh available_tools
- [ ] 4.1.4 Отправка `available_commands_update` notification клиенту
- [ ] 4.1.5 Тесты: notification handling, tool refresh

### 4.2 Auto-reconnect

**Файлы:** `server/mcp/manager.py`, `server/mcp/client.py`

**Подзадачи:**
- [ ] 4.2.1 `MCPClient` — health check (periodic ping или monitoring subprocess)
- [ ] 4.2.2 `MCPManager` — reconnect policy: max_retries, backoff, timeout
- [ ] 4.2.3 При reconnect: re-initialize, re-list_tools, re-register
- [ ] 4.2.4 Notification клиенту о disconnect/reconnect
- [ ] 4.2.5 Graceful degradation: если server не восстанавливается, удалить из active
- [ ] 4.2.6 Тесты: reconnect scenarios, max retries, backoff

### 4.3 Resource/Prompt change notifications

**Подзадачи:**
- [ ] 4.3.1 `notifications/resources/list_changed` handling
- [ ] 4.3.2 `notifications/prompts/list_changed` handling

---

## Фаза 5: Advanced MCP Features (P2)

### 5.1 Image/Resource content в tool results

**Файлы:** `server/mcp/tool_adapter.py`, `server/shared/content/`

**Подзадачи:**
- [ ] 5.1.1 `MCPCallToolResult.content` может содержать `MCPImageContent` → конвертация в ACP `ImageContent`
- [ ] 5.1.2 `MCPCallToolResult.content` может содержать `MCPEmbeddedResource` → конвертация в ACP `EmbeddedContent`
- [ ] 5.1.3 Content pipeline: MCP content → ExtractedContent → LLM format
- [ ] 5.1.4 Тесты: image content, embedded resource content

### 5.2 MCP Roots

**Файлы:** `server/mcp/client.py`, `server/mcp/models.py`

**Подзадачи:**
- [ ] 5.2.1 `MCPRoot` — uri: str, name?: str
- [ ] 5.2.2 `roots/list` handler в MCPClient (server→client request)
- [ ] 5.2.3 При initialize: отправить `capabilities.roots` если поддерживается
- [ ] 5.2.4 Roots из session.cwd → `file://{cwd}`
- [ ] 5.2.5 `notifications/roots/list_changed` при смене cwd
- [ ] 5.2.6 Тесты: roots listing, notification

### 5.3 MCP Sampling

**Файлы:** `server/mcp/client.py`, `server/mcp/models.py`, `server/llm/`

**Подзадачи:**
- [ ] 5.3.1 `MCPSamplingMessage` — role, content
- [ ] 5.3.2 `sampling/createMessage` handler (server→client request)
- [ ] 5.3.3 Делегирование в LLM провайдер → возврат completion
- [ ] 5.3.4 Model preferences mapping → LLM resolver
- [ ] 5.3.5 Human-in-the-loop: approval через client (если требуется)
- [ ] 5.3.6 Тесты: sampling request → LLM → response

### 5.4 MCP Elicitation

**Файлы:** `server/mcp/client.py`, `server/mcp/models.py`

**Подзадачи:**
- [ ] 5.4.1 `MCPElicitationRequest` — message, schema
- [ ] 5.4.2 `elicitation/create` handler (server→client request)
- [ ] 5.4.3 Делегирование в client → UI elicitation modal
- [ ] 5.4.4 Response validation against schema
- [ ] 5.4.5 Тесты: elicitation flow

### 5.5 Progress notifications

**Файлы:** `server/mcp/transport.py`, `server/mcp/client.py`

**Подзадачи:**
- [ ] 5.5.1 Progress token в request `_meta.progressToken`
- [ ] 5.5.2 `notifications/progress` handling
- [ ] 5.5.3 Progress → ACP notification (tool_call_update с progress)
- [ ] 5.5.4 Тесты: progress tracking

---

## Фаза 6: HTTP Transport (P2)

### 6.1 MCP HTTP Transport

**Файлы:** `server/mcp/transport.py` (новый: `HttpTransport`)

**Подзадачи:**
- [ ] 6.1.1 `MCPHttpTransport` — aiohttp-based HTTP transport
- [ ] 6.1.2 POST для client→server messages
- [ ] 6.1.3 SSE для server→client streaming (optional)
- [ ] 6.1.4 Headers: Authorization, Content-Type
- [ ] 6.1.5 Connection pooling, retry logic
- [ ] 6.1.6 Тесты: HTTP connect, request, response

### 6.2 MCPConfig — HTTP support

**Файлы:** `server/mcp/models.py`, `server/toml_config/`

**Подзадачи:**
- [ ] 6.2.1 `MCPServerConfig` — добавить `type: "http" | "sse" | "stdio"`, `url`, `headers`
- [ ] 6.2.2 TOML config: секция `[mcp.servers]` с http/sse support
- [ ] 6.2.3 `mcpCapabilities.http: true` в initialize response
- [ ] 6.2.4 Тесты: HTTP server config, connection

---

## Тестовая стратегия

### Unit тесты (каждая фаза)
- Mock MCP server для изолированного тестирования
- Тесты моделей (serialization/deserialization)
- Тесты client methods (list_tools, call_tool, list_resources, etc.)
- Тесты manager methods (add_server, get_tools, call_tool)

### Integration тесты
- Реальный MCP subprocess (filesystem server из MCP reference servers)
- Полный flow: session/new → MCP connect → prompt → MCP tool call → response
- Reconnect scenarios
- Notification handling

### E2E тесты
- stdio transport: client → server → MCP server → tool execution
- HTTP transport: client → server → remote MCP server

---

## Зависимости между фазами

```
Фаза 1 (MCP Tools в LLM Loop) — критично, без неё MCP tools не работают
    ↓
Фаза 2 (Resources) — независима от Фазы 1, но использует MCPClient/MCPManager
    ↓
Фаза 3 (Prompts) — независима от Фаз 1-2
    ↓
Фаза 4 (Notifications + Auto-reconnect) — зависит от Фазы 1 (tool list changed)
    ↓
Фаза 5 (Advanced Features) — зависит от Фаз 1-4
    ↓
Фаза 6 (HTTP Transport) — независима, но расширяет transport layer
```

---

## Оценка объёма

| Фаза | Файлов изменится | Тестов добавится | Сложность |
|---|---|---|---|
| 1. MCP Tools в LLM Loop | 5-7 | 30-40 | Высокая |
| 2. Resources | 4-5 | 20-25 | Средняя |
| 3. Prompts | 4-5 | 15-20 | Средняя |
| 4. Notifications + Reconnect | 3-4 | 20-25 | Высокая |
| 5. Advanced Features | 6-8 | 30-40 | Высокая |
| 6. HTTP Transport | 2-3 | 15-20 | Средняя |
| **Итого** | **24-32** | **130-170** | |

---

## Рекомендуемый порядок

1. **Фаза 1** — без неё MCP tools не работают вообще, это критичный гэп
2. **Фаза 4** — notifications и reconnect для стабильности
3. **Фаза 2** — resources для расширения контекста
4. **Фаза 3** — prompts для UX
5. **Фаза 5** — advanced features по мере необходимости
6. **Фаза 6** — HTTP transport когда появятся remote MCP servers
