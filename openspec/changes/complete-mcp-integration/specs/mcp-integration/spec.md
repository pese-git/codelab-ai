# Spec: MCP Integration

## MCP Tools в LLM Loop

Система **MUST** подключать MCP инструменты к LLM loop, позволяя LLM обнаруживать и вызывать инструменты от MCP серверов.

### Tool Discovery

- Система **MUST** добавлять MCP инструменты из `MCPManager.get_all_tools()` в `AgentContext.available_tools`
- MCP инструменты **MUST** использовать namespace формат `mcp:{server_id}:{tool_name}`
- MCP инструменты **MUST** проходить через `ToolMapping.acp_name_to_llm_name()` для совместимости с LLM API
- LLM **MUST** получать MCP инструменты в том же формате что и встроенные инструменты

### Tool Execution

- При tool call с именем начинающимся с `mcp:`, система **MUST** делегировать выполнение в `MCPManager.call_tool()`
- MCP tool calls **MUST** создавать `ToolCallState` с `kind="mcp"`
- MCP tool calls **MUST** проходить полный lifecycle: pending → in_progress → completed/failed
- MCP tool calls **MUST** проходить через `PermissionManager` (allow/deny/ask chain)
- Timeout для MCP tool calls **MUST** быть настраиваемым per-server
- При ошибке MCP сервера, tool call **MUST** переходить в статус `failed` с описанием ошибки

### Content Conversion

- MCP tool result content **MUST** конвертироваться в ACP content format:
  - `MCPTextContent.type == "text"` → `TextContent`
  - `MCPImageContent.type == "image"` → `ImageContent` (base64, media_type preserved)
  - `MCPEmbeddedResource.type == "resource"` → `EmbeddedContent`
- Конвертированный контент **MUST** передаваться в LLM как tool result

## MCP Resources

Система **MUST** поддерживать MCP Resources — пассивные data sources для контекста.

### Resource Discovery

- MCPClient **MUST** вызывать `resources/list` при инициализации если server declares `capabilities.resources`
- MCPClient **MUST** вызывать `resources/templates/list` если server declares resource templates
- MCPManager **MUST** агрегировать resources от всех подключённых серверов

### Resource Reading

- MCPClient **MUST** поддерживать `read_resource(uri)` → `MCPReadResourceResult`
- MCPManager **MUST** маршрутизировать `read_resource` к правильному серверу по URI
- Resource content **MUST** конвертироваться в ACP `ResourceLinkContent`

### Resource Models

- `MCPResource`: uri (str), name (str), description (str), mimeType (str)
- `MCPResourceTemplate`: uriTemplate (str), name (str), description (str), mimeType (str)
- `MCPResourceContent`: uri (str), mimeType (str), text (str?), blob (str?)

## MCP Prompts

Система **MUST** поддерживать MCP Prompts — параметризованные prompt templates.

### Prompt Discovery

- MCPClient **MUST** вызывать `prompts/list` при инициализации если server declares `capabilities.prompts`
- MCPManager **MUST** агрегировать prompts от всех подключённых серверов

### Prompt Resolution

- MCPClient **MUST** поддерживать `get_prompt(name, arguments)` → `MCPGetPromptResult`
- MCP prompts **MUST** маппиться на ACP slash commands
- При вызове slash-команды, система **MUST** resolve MCP prompt → messages → inject в conversation

### Prompt Models

- `MCPPrompt`: name (str), description (str), arguments (list[MCPPromptArgument])
- `MCPPromptArgument`: name (str), description (str), required (bool), enum (list[str]?)
- `MCPPromptMessage`: role (str), content (MCPContent)

## MCP Notifications

Система **MUST** обрабатывать MCP notifications от серверов.

### Tool List Changed

- При получении `notifications/tools/list_changed`, система **MUST**:
  1. Вызвать `tools/list` для получения обновлённого списка
  2. Обновить кэш инструментов в MCPManager
  3. Обновить `available_tools` в active session
  4. Отправить `available_commands_update` notification клиенту

### Resource/Prompt List Changed

- При получении `notifications/resources/list_changed`, система **MUST** refresh resources
- При получении `notifications/prompts/list_changed`, система **MUST** refresh prompts

## MCP Auto-reconnect

Система **MUST** автоматически переподключаться к MCP серверам при падении.

### Reconnect Policy

- Max retries: **5** попыток
- Backoff: exponential, starting at 1s, max 16s
- Health check: monitoring subprocess exit code
- При успешном reconnect: re-initialize, re-list_tools, re-register

### Graceful Degradation

- Если server не восстанавливается после max retries, система **MUST**:
  1. Удалить сервер из active servers
  2. Отправить notification клиенту о disconnect
  3. Удалить MCP инструменты этого сервера из available_tools

## MCP Roots

Система **MUST** поддерживать MCP Roots — filesystem boundaries.

### Root Management

- При session creation, система **MUST** отправить roots: `[{uri: "file://{cwd}", name: "workspace"}]`
- При смене cwd, система **MUST** отправить `notifications/roots/list_changed`
- MCPClient **MUST** поддерживать `roots/list` handler

## MCP HTTP Transport

Система **MUST** поддерживать HTTP transport для remote MCP servers.

### Transport Requirements

- POST для client→server messages
- SSE для server→client streaming (optional)
- Headers: Authorization, Content-Type из MCPServerConfig
- Connection pooling, retry logic

### Configuration

- `MCPServerConfig` **MUST** поддерживать `type: "http" | "sse" | "stdio"`
- HTTP config: `type`, `url`, `headers`
- При HTTP transport, `mcpCapabilities.http` **MUST** быть `true` в initialize response
