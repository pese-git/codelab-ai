# Proposal: Complete MCP Integration

## Why

Текущая MCP реализация поддерживает только stdio transport, tools/list и tools/call. MCP инструменты **не подключены к LLM loop** — это критичный гэп, из-за которого MCP серверы подключаются, но LLM не может использовать их инструменты. Кроме того, отсутствуют MCP Resources (пассивные data sources), MCP Prompts (параметризованные templates), notifications (`tools/list_changed`), auto-reconnect при падении сервера, и HTTP transport для remote MCP servers.

Согласно ACP spec (`doc/Agent Client Protocol/protocol/03-Session Setup.md`): «Agents SHOULD connect to all MCP servers specified by the Client» и «MCP servers can be connected to using different transports. All Agents MUST support the stdio transport, while HTTP and SSE transports are optional».

## What Changes

### Фаза 1: MCP Tools в LLM Loop (P0 — критично)
- **`MCPToolExecutor`** — обёртка, адаптирующая `MCPManager.call_tool()` под интерфейс `ToolExecutor`
- **Интеграция в `LLMLoopStage`** — распознавание MCP namespace (`mcp:server:tool`) и делегирование в `MCPManager`
- **MCP tools в `AgentContext.available_tools`** — LLM видит MCP инструменты
- **MCP tool call lifecycle** — pending → in_progress → completed/failed с notifications
- **Permission flow для MCP tools** — через существующий `PermissionManager`

### Фаза 2: MCP Resources (P1)
- **Модели** — `MCPResource`, `MCPResourceTemplate`, `MCPReadResourceParams`, `MCPReadResourceResult`
- **MCPClient API** — `list_resources()`, `list_resource_templates()`, `read_resource(uri)`
- **MCPManager** — `get_all_resources()`, `read_resource(server_id, uri)`
- **Интеграция в ACP** — MCP Resources → ACP `ResourceLinkContent`

### Фаза 3: MCP Prompts (P1)
- **Модели** — `MCPPrompt`, `MCPPromptArgument`, `MCPListPromptsResult`, `MCPGetPromptResult`
- **MCPClient API** — `list_prompts()`, `get_prompt(name, arguments)`
- **MCPManager** — `get_all_prompts()`, `get_prompt(server_id, name, arguments)`
- **Интеграция в ACP** — MCP Prompts → ACP slash commands

### Фаза 4: Notifications и Auto-reconnect (P1)
- **Tool list change notifications** — `notifications/tools/list_changed` handling
- **Auto-reconnect** — health check, reconnect policy, backoff, graceful degradation
- **Resource/Prompt change notifications** — `resources/list_changed`, `prompts/list_changed`

### Фаза 5: Advanced Features (P2)
- **Image/Resource content в tool results** — MCPImageContent → ACP ImageContent
- **MCP Roots** — `roots/list`, `notifications/roots/list_changed`
- **MCP Sampling** — `sampling/createMessage` → LLM provider delegation
- **MCP Elicitation** — `elicitation/create` → UI modal
- **Progress notifications** — progress tokens → ACP tool_call_update

### Фаза 6: HTTP Transport (P2)
- **MCPHttpTransport** — aiohttp-based HTTP transport
- **MCPServerConfig** — поддержка `type: "http"`, `url`, `headers`
- **mcpCapabilities.http: true** в initialize response

## Capabilities

### New Capabilities
- `mcp-tools-in-llm-loop`: MCP инструменты доступны LLM и выполняются через MCPManager
- `mcp-resources`: Обнаружение и чтение MCP Resources (resources/list, resources/read)
- `mcp-prompts`: Обнаружение и получение MCP Prompts (prompts/list, prompts/get)
- `mcp-notifications`: Обработка MCP notifications (tools/list_changed, resources/list_changed)
- `mcp-auto-reconnect`: Автоматическое переподключение к MCP серверам при падении
- `mcp-http-transport`: Подключение к MCP серверам через HTTP transport

### Modified Capabilities
- `codelab`: Раздел 19 (MCP интеграция) — расширяется полной поддержкой MCP spec

## Impact

**Затронутые файлы сервера:**
- `server/mcp/` — новые модели, client methods, manager methods, transport
- `server/tools/` — MCPToolExecutor, интеграция в registry
- `server/protocol/handlers/pipeline/stages/llm_loop.py` — MCP tool execution
- `server/agent/orchestrator.py` — MCP tools в AgentContext
- `server/shared/content/` — MCP content → ACP content conversion

**Тесты:**
- ~130-170 новых тестов для всех фаз

**ACP Protocol:**
- Полная совместимость — MCP spec следует ACP architecture
