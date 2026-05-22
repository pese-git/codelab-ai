# Архитектура CodeLab

> Обзор архитектуры системы и взаимодействия компонентов.

## Общая архитектура

CodeLab реализует клиент-серверную архитектуру, определённую [Agent Client Protocol (ACP)](../../Agent%20Client%20Protocol/get-started/02-Architecture.md).

```mermaid
graph TB
    subgraph "Client Layer"
        TUI[TUI Client<br/>Textual]
        WebUI[Web UI<br/>Browser]
    end
    
    subgraph "Transport"
        WS[WebSocket<br/>JSON-RPC 2.0]
    end
    
    subgraph "Server Layer"
        Protocol[ACP Protocol<br/>Handler]
        Session[Session<br/>Manager]
        Agent[LLM Agent<br/>Orchestrator]
        Tools[Tool<br/>Registry]
    end
    
    subgraph "External"
        LLM[LLM Provider<br/>OpenAI/Anthropic]
        MCP[MCP Servers]
    end
    
    TUI --> WS
    WebUI --> WS
    WS --> Protocol
    Protocol --> Session
    Session --> Agent
    Agent --> Tools
    Agent --> LLM
    Tools --> MCP
```

## Компоненты системы

### Клиент (Client)

Клиент предоставляет пользовательский интерфейс и обрабатывает запросы сервера:

```mermaid
graph LR
    subgraph "TUI Client"
        UI[UI Components]
        VM[ViewModels<br/>MVVM]
        UC[Use Cases]
        Transport[Transport<br/>Layer]
    end
    
    UI --> VM
    VM --> UC
    UC --> Transport
```

**Слои клиента (Clean Architecture):**
- **Presentation** — UI компоненты (Textual widgets)
- **ViewModels** — логика представления (MVVM паттерн)
- **Application** — use cases, state machine
- **Infrastructure** — транспорт, DI, handlers

### Сервер (Server)

Сервер содержит AI-агента и обрабатывает протокол ACP:

```mermaid
graph TB
    subgraph "ACP Server"
        HTTP[HTTP/WebSocket<br/>Server]
        Protocol[Protocol<br/>Dispatcher]
        
        subgraph "Handlers"
            Auth[Auth]
            Session[Session]
            Prompt[Prompt]
            Perm[Permissions]
        end
        
        subgraph "Agent"
            Orch[Orchestrator]
            LLM[LLM Provider]
            ToolReg[Tool Registry]
        end
        
        Storage[(Session<br/>Storage)]
    end
    
    HTTP --> Protocol
    Protocol --> Auth
    Protocol --> Session
    Protocol --> Prompt
    Protocol --> Perm
    Session --> Storage
    Prompt --> Orch
    Orch --> LLM
    Orch --> ToolReg
```

## Протокол ACP

Взаимодействие происходит через JSON-RPC 2.0:

```mermaid
sequenceDiagram
    participant C as Client
    participant S as Server
    participant A as Agent (LLM)
    
    Note over C,S: Инициализация
    C->>S: initialize
    S-->>C: capabilities
    
    Note over C,S: Сессия
    C->>S: session/new
    S-->>C: session_id
    
    Note over C,S: Prompt Turn
    C->>S: session/prompt
    
    loop Agent работает
        S->>A: LLM запрос
        A-->>S: tool_call
        S-->>C: notification (tool_call)
        S->>C: client/request_permission
        C-->>S: permission response
        S-->>C: notification (result)
    end
    
    S-->>C: prompt/finished
```

## Агент и LLM

### Цикл обработки prompt

Полный путь запроса от пользователя до ответа LLM:

```mermaid
sequenceDiagram
    participant U as Пользователь
    participant C as Client
    participant S as ACPProtocol
    participant PO as PromptOrchestrator
    participant LL as LLMLoopStage
    participant ORCH as AgentOrchestrator
    participant AG as NaiveAgent
    participant LLM as OpenAIProvider
    participant TR as ToolRegistry
    participant TM as ToolMapping

    U->>C: Вводит prompt
    C->>S: session/prompt
    S->>PO: handle_prompt()
    PO->>LL: process(context)

    loop LLM Loop (до 10 итераций)
        alt Первая итерация (новый turn)
            LL->>ORCH: process_prompt(session, prompt)
            ORCH->>AG: start_turn(AgentContext)
            Note over AG: Добавляет user message<br/>из prompt к conversation_history
        else Последующие итерации (tool results)
            LL->>ORCH: continue_with_tool_results(session, tool_results)
            ORCH->>ORCH: _add_tool_result_to_history()
            ORCH->>AG: continue_turn(ContinuationContext)
            Note over AG: НЕ добавляет user message<br/>история содержит tool_results
        end
        AG->>TM: acp_name_to_llm_name() для инструментов
        TM-->>AG: LLM-совместимые имена (с _)
        AG->>LLM: create_completion(messages, tools)
        LLM-->>AG: LLMResponse(text, tool_calls, stop_reason)
        AG-->>ORCH: AgentResponse
        ORCH-->>LL: AgentResponse

        alt stop_reason = end_turn
            LL-->>PO: stop_reason=end_turn
            PO-->>S: ProtocolOutcome
            S-->>C: session/update + result
            C-->>U: Показывает ответ
        else stop_reason = tool_use
            loop Для каждого tool call
                LL->>TM: llm_name_to_acp_name(tool_name)
                TM-->>LL: ACP имя (с /)
                LL->>TR: execute_tool() или request_permission
                TR-->>LL: ToolResult
                S-->>C: session/update (статус инструмента)
            end
            LL->>LL: continue_turn с tool_results
        end
    end
```

### LLM Loop — алгоритм

```mermaid
flowchart TD
    START([session/prompt]) --> HIST[Подготовить историю сообщений]
    HIST --> TOOLS[Получить список инструментов]
    TOOLS --> MAP1[acp_name_to_llm_name()\n/ → _]
    MAP1 --> CANCEL{Отмена\nзапрошена?}
    CANCEL -->|Да| CANCELLED([stop_reason = cancelled])
    CANCEL -->|Нет| LLM[Вызов LLM API]
    LLM --> PARSE[Разобрать ответ]
    PARSE --> HAS_TOOLS{Есть\ntool calls?}

    HAS_TOOLS -->|Нет| END_TURN([stop_reason = end_turn])

    HAS_TOOLS -->|Да| FOREACH[Для каждого tool call]
    FOREACH --> MAP2[llm_name_to_acp_name()\n_ → /]
    MAP2 --> POLICY{Политика}
    POLICY -->|allow| EXEC[Выполнить инструмент]
    POLICY -->|ask| PERM([Запросить разрешение\nПайплайн приостановлен])
    POLICY -->|reject| FAIL[Пометить failed]

    EXEC --> RESULT[ToolResult]
    FAIL --> RESULT
    RESULT --> MORE{Ещё\ntool calls?}
    MORE -->|Да| FOREACH
    MORE -->|Нет| MAXITER{Макс.\nитераций?}
    MAXITER -->|Да| MAX([stop_reason = max_turn_requests])
    MAXITER -->|Нет| CANCEL
```

### Отмена prompt

```mermaid
sequenceDiagram
    participant U as Пользователь
    participant C as Client
    participant TS as ACPTransportService
    participant S as ACPProtocol
    participant ORCH as AgentOrchestrator
    participant AG as NaiveAgent
    participant LLM as OpenAI API

    Note over AG,LLM: asyncio.Task — HTTP запрос к LLM
    AG->>LLM: POST /chat/completions

    U->>C: Нажимает Stop
    Note over TS: cancel_prompt() обходит<br/>_callbacks_request_lock
    C->>TS: stop_button_pressed
    TS->>S: session/cancel (немедленно)
    S->>ORCH: cancel_prompt(session_id)
    ORCH->>AG: active_task.cancel()
    LLM--xAG: CancelledError
    AG-->>ORCH: stop_reason=cancelled
    ORCH-->>S: stop_reason=cancelled
    S-->>C: session/update {stopReason: cancelled}
    C-->>U: Стриминг остановлен
```

## Маппинг имён инструментов

ACP протокол использует имена с `/` (например `fs/read_text_file`), но некоторые LLM провайдеры не поддерживают этот символ. Модуль `tools/mapping.py` обеспечивает двустороннюю конвертацию:

```mermaid
graph LR
    subgraph ACP["ACP Protocol"]
        A1["fs/read_text_file"]
        A2["terminal/create"]
    end
    
    subgraph Mapping["ToolMapping"]
        M1["acp_name_to_llm_name()\n/ → _"]
        M2["llm_name_to_acp_name()\n_ → /"]
    end
    
    subgraph LLM["LLM API"]
        L1["fs_read_text_file"]
        L2["terminal_create"]
    end
    
    A1 --> M1 --> L1
    A2 --> M1 --> L2
    L1 --> M2 --> A1
    L2 --> M2 --> A2
    
    style ACP fill:#e3f2fd,stroke:#1565c0
    style LLM fill:#fff3e0,stroke:#e65100
    style Mapping fill:#f3e5f5,stroke:#6a1b9a
```

**Применение:**
- При отправке инструментов в LLM: `acp_name_to_llm_name()`
- При получении tool calls от LLM: `llm_name_to_acp_name()`

## Потоки данных

### Prompt Turn

Цикл обработки пользовательского запроса:

```mermaid
flowchart TD
    A[User Prompt] --> B[session/prompt]
    B --> C{Agent Planning}
    C --> D[Generate Plan]
    D --> E{Execute Tools}
    
    E --> F[Tool Call]
    F --> G{Need Permission?}
    G -->|Yes| H[Request Permission]
    H --> I{User Decision}
    I -->|Allow| J[Execute]
    I -->|Deny| K[Skip]
    G -->|No| J
    
    J --> L[Tool Result]
    K --> L
    L --> M{More Tools?}
    M -->|Yes| E
    M -->|No| N[Final Response]
    N --> O[prompt/finished]
```

### Система разрешений

```mermaid
flowchart LR
    subgraph "Permission Flow"
        Tool[Tool Call] --> Check{Check Policy}
        Check -->|Auto-Allow| Execute[Execute]
        Check -->|Auto-Deny| Skip[Skip]
        Check -->|Ask| Request[Request<br/>Permission]
        Request --> User{User}
        User -->|Allow| Execute
        User -->|Allow All| Policy[Update<br/>Policy]
        Policy --> Execute
        User -->|Deny| Skip
    end
```

## Хранение данных

### Структура сессий

```mermaid
erDiagram
    SESSION ||--o{ MESSAGE : contains
    SESSION ||--o{ TOOL_CALL : has
    SESSION {
        string id PK
        string name
        datetime created_at
        json config
        json context
    }
    MESSAGE {
        string id PK
        string session_id FK
        string role
        json content
        datetime timestamp
    }
    TOOL_CALL {
        string id PK
        string session_id FK
        string tool_name
        json arguments
        json result
        string status
    }
```

## Директории проекта

```
codelab/src/codelab/
├── shared/              # Общие модули
│   ├── messages.py      # JSON-RPC сообщения
│   ├── logging.py       # Структурированное логирование
│   └── content/         # Типы контента ACP
│
├── server/              # Серверная часть
│   ├── protocol/        # ACP протокол
│   ├── agent/           # LLM агент
│   ├── tools/           # Инструменты
│   ├── storage/         # Хранилище сессий
│   └── mcp/             # MCP интеграция
│
└── client/              # Клиентская часть
    ├── domain/          # Domain Layer
    ├── application/     # Application Layer
    ├── infrastructure/  # Infrastructure Layer
    ├── presentation/    # ViewModels (MVVM)
    └── tui/             # TUI компоненты
```

## См. также

- [Введение](01-introduction.md) — общая информация о CodeLab
- [Сценарии использования](03-use-cases.md) — примеры применения
- [Спецификация ACP](../../Agent%20Client%20Protocol/protocol/01-Overview.md) — детали протокола
