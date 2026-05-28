# Design: Complete MCP Integration

## Architecture

### MCP Tools в LLM Loop

```mermaid
sequenceDiagram
    participant LLM as LLM Provider
    participant AG as NaiveAgent
    participant ORCH as AgentOrchestrator
    participant LL as LLMLoopStage
    participant TCH as ToolCallHandler
    participant MCP as MCPManager
    participant MCPS as MCP Server

    LLM-->>AG: AgentResponse(tool_calls=[...])
    AG-->>ORCH: AgentResponse
    ORCH-->>LL: AgentResponse
    LL->>LL: _process_tool_calls()
    loop Каждый tool call
        LL->>TCH: create_tool_call(tool_name)
        TCH-->>LL: ToolCallState
        alt tool_name начинается с "mcp:"
            LL->>MCP: call_tool(namespaced_name, arguments)
            MCP->>MCPS: tools/call via StdioTransport
            MCPS-->>MCP: MCPCallToolResult
            MCP-->>LL: ToolResult (content converted)
        else Встроенный инструмент
            LL->>TCH: execute_tool(tool_name, arguments)
            TCH-->>LL: ToolResult
        end
        LL->>LL: update ToolCallState → completed/failed
    end
    LL->>LL: continue_turn с tool_results
```

### MCP Components

```mermaid
graph TB
    subgraph MCP["MCP Module (server/mcp/)"]
        MGR["MCPManager\nmulti-server lifecycle"]
        CLI["MCPClient\nper-server connection"]
        ADP["MCPToolAdapter\nnamespace + conversion"]
        STDIO["StdioTransport\nsubprocess I/O"]
        HTTP["MCPHttpTransport\nHTTP/SSE I/O"]
        MODELS["Models\nJSON-RPC + MCP types"]
    end

    subgraph Protocol["Protocol Layer"]
        LL["LLMLoopStage\ntool execution"]
        ORCH["PromptOrchestrator\npipeline coordinator"]
        PM["PermissionManager\nallow/deny/ask"]
    end

    subgraph Agent["Agent Layer"]
        AG["NaiveAgent\nLLM interaction"]
        REG["ToolRegistry\nbuilt-in tools"]
    end

    subgraph External["External"]
        MCP1["MCP Server 1\n(filesystem)"]
        MCP2["MCP Server 2\n(database)"]
        MCP3["MCP Server 3\n(remote HTTP)"]
    end

    ORCH --> LL
    LL --> AG
    LL --> REG
    LL --> MGR
    LL --> PM
    MGR --> CLI
    CLI --> ADP
    CLI --> STDIO
    CLI --> HTTP
    STDIO --> MCP1
    STDIO --> MCP2
    HTTP --> MCP3
```

## Key Design Decisions

### 1. MCP Tool Namespace

MCP инструменты используют формат `mcp:{server_id}:{tool_name}` для уникальной идентификации. Это позволяет:
- Различать MCP инструменты от встроенных (filesystem, terminal)
- Поддерживать несколько MCP серверов с одинаковыми именами инструментов
- Легко маршрутизировать вызовы в `LLMLoopStage`

### 2. Content Conversion

MCP tool results содержат `content: list[MCPContent]` где MCPContent может быть:
- `MCPTextContent` → ACP `TextContent`
- `MCPImageContent` → ACP `ImageContent` (base64)
- `MCPEmbeddedResource` → ACP `EmbeddedContent`

Конвертация происходит в `MCPToolExecutor.execute()` перед возвратом `ToolResult`.

### 3. Auto-reconnect Strategy

- **Exponential backoff**: 1s → 2s → 4s → 8s → 16s (max)
- **Max retries**: 5 попыток
- **Health check**: periodic ping или monitoring subprocess exit
- **Graceful degradation**: если server не восстанавливается, удалить из active и notify

### 4. Notifications Flow

```
MCP Server → StdioTransport → MCPClient → MCPManager → PromptOrchestrator → Client
```

MCP notifications (`tools/list_changed`) обрабатываются в `_handle_message()` транспорта, передаются через callback в MCPClient, затем в MCPManager, который обновляет кэш инструментов и уведомляет PromptOrchestrator.

### 5. HTTP Transport

- aiohttp-based `ClientSession` для connection pooling
- POST для client→server messages
- SSE для server→client streaming (optional)
- Headers: Authorization, Content-Type из MCPServerConfig
