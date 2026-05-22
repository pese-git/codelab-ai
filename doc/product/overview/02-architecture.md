# Архитектура CodeLab

> Обзор архитектуры системы и взаимодействия компонентов.

## Общая архитектура

CodeLab реализует клиент-серверную архитектуру, определённую [Agent Client Protocol (ACP)](../../Agent%20Client%20Protocol/get-started/02-Architecture.md).

```mermaid
graph TB
    subgraph Client["Клиент (Clean Architecture + MVVM)"]
        TUI[TUI Components<br/>45 widgets]
        VM[9 ViewModels]
        UC[Use Cases]
        TS[ACPTransportService<br/>WebSocket / stdio]
        BgLoop[BackgroundReceiveLoop]
    end
    
    subgraph Transport["Транспорт"]
        WS[WebSocket<br/>JSON-RPC 2.0]
        STDIO[stdio<br/>stdin/stdout]
    end
    
    subgraph Server["Сервер (Dishka DI)"]
        HTTP[ACPHttpServer]
        AP[ACPProtocol]
        PO[PromptOrchestrator]
        AO[AgentOrchestrator]
        TR[ToolRegistry]
        MCP[MCPManager]
        Storage[(SessionStorage<br/>LRU Cache)]
    end
    
    subgraph External["Внешние системы"]
        LLM[LLM Provider<br/>OpenAI/Anthropic/Mock]
        FS[File System]
        TERM[Terminal]
    end
    
    TUI --> VM --> UC --> TS
    TS --> BgLoop
    TS --> WS & STDIO
    WS & STDIO --> HTTP --> AP --> PO
    PO --> AO --> LLM
    PO --> TR --> FS & TERM
    PO --> MCP
    AP --> Storage
```

## Компоненты системы

### Клиент (Client)

Клиент реализует **Clean Architecture** с 5 слоями и **MVVM паттерн** для реактивного UI:

```mermaid
graph TB
    subgraph TUI["TUI Layer (45 компонентов)"]
        Chat[ChatView]
        Sidebar[Sidebar]
        FileTree[FileTree]
        Prompt[PromptInput]
        ToolPanel[ToolPanel]
        CmdPalette[CommandPalette]
    end
    
    subgraph Presentation["Presentation Layer"]
        VM1[UIViewModel]
        VM2[SessionViewModel]
        VM3[ChatViewModel]
        VM4[PlanViewModel]
        VM5[TerminalViewModel]
        VM6[FileSystemViewModel]
        VM7[FileViewerViewModel]
        VM8[PermissionViewModel]
        VM9[TerminalLogViewModel]
    end
    
    subgraph Application["Application Layer"]
        UC1[InitializeUseCase]
        UC2[CreateSessionUseCase]
        UC3[SendPromptUseCase]
        UC4[ListSessionsUseCase]
        SM[UIStateMachine]
        PH[PermissionHandler]
    end
    
    subgraph Infrastructure["Infrastructure Layer"]
        DI[Dishka Container]
        TS[ACPTransportService]
        BgLoop[BackgroundReceiveLoop]
        Router[MessageRouter]
        Queues[RoutingQueues]
        EB[EventBus]
        Handlers[FS/Terminal Handlers]
    end
    
    subgraph Domain["Domain Layer"]
        Entities[Session, Message]
        Repos[Repositories]
        Events[16 Domain Events]
    end
    
    Chat & Sidebar & FileTree & Prompt & ToolPanel & CmdPalette --> VM1 & VM2 & VM3 & VM4 & VM5 & VM6 & VM7 & VM8 & VM9
    VM1 & VM2 & VM3 & VM4 & VM5 & VM6 & VM7 & VM8 & VM9 --> UC1 & UC2 & UC3 & UC4
    UC1 & UC2 & UC3 & UC4 --> SM & PH
    SM & PH --> DI
    DI --> TS & EB & Handlers
    TS --> BgLoop --> Router --> Queues
    Queues --> EB --> Entities & Repos & Events
```

**Слои клиента:**
- **TUI Layer** — 45 Textual компонентов (ChatView, Sidebar, FileTree, CommandPalette, и др.)
- **Presentation** — 9 ViewModels с Observable состоянием (MVVM)
- **Application** — 5 Use Cases, UIStateMachine, PermissionHandler
- **Infrastructure** — Dishka DI, ACPTransportService, BackgroundReceiveLoop, MessageRouter, EventBus
- **Domain** — Session, Message, Permission, ToolCall, Repository интерфейсы, 16 Domain Events

### Сервер (Server)

Сервер использует **Dishka DI контейнер** с двумя скоупами и **Pipeline систему** для обработки промптов:

```mermaid
graph TB
    subgraph Transport["Transport Layer"]
        HTTP[ACPHttpServer]
        WS[WebSocketTransport]
        STDIO[StdioServerTransport]
    end
    
    subgraph Protocol["Protocol Layer"]
        AP[ACPProtocol<br/>REQUEST scope]
        PO[PromptOrchestrator<br/>APP scope]
    end
    
    subgraph Pipeline["Pipeline (7 стадий)"]
        V[ValidationStage]
        SC[SlashCommandStage]
        PB[PlanBuildingStage]
        TL1[TurnLifecycleStage open]
        DS[DirectivesStage]
        LL[LLMLoopStage]
        TL2[TurnLifecycleStage close]
    end
    
    subgraph Managers["Managers (APP scope)"]
        SM[StateManager]
        PBuilder[PlanBuilder]
        TLCM[TurnLifecycleManager]
        TCH[ToolCallHandler]
        PM[PermissionManager]
        CRH[ClientRPCHandler]
        GPM[GlobalPolicyManager]
    end
    
    subgraph Agent["Agent Layer"]
        AO[AgentOrchestrator]
        AG[NaiveAgent]
        LLM[LLM Provider]
    end
    
    subgraph Tools["Tools Layer"]
        TR[ToolRegistry]
        FS[FileSystemExecutor]
        TE[TerminalToolExecutor]
        Bridge[ClientRPCBridge]
    end
    
    subgraph MCP["MCP Layer"]
        MM[MCPManager]
        MT[MCPToolAdapter]
    end
    
    subgraph Storage["Storage Layer"]
        SS[SessionStorage<br/>LRU Cache]
        GPS[GlobalPolicyStorage]
    end
    
    HTTP --> WS & STDIO
    WS & STDIO --> AP
    AP --> PO
    PO --> Pipeline
    V --> SC --> PB --> TL1 --> DS --> LL --> TL2
    PO --> SM & PBuilder & TLCM & TCH & PM & CRH & GPM
    LL --> AO --> AG --> LLM
    LL --> TR --> FS & TE --> Bridge
    LL --> MM --> MT
    AP --> SS
    PM --> GPS
```

**Скоупы DI контейнера:**
- **APP scope** — синглтоны на всё время жизни сервера (LLM, ToolRegistry, менеджеры, pipeline)
- **REQUEST scope** — на одно WebSocket соединение (ClientRPCService, ACPProtocol)

**Менеджеры:**
| Менеджер | Ответственность |
|----------|-----------------|
| `StateManager` | Управление состоянием сессии |
| `PlanBuilder` | Построение планов выполнения |
| `TurnLifecycleManager` | Жизненный цикл prompt-turn |
| `ToolCallHandler` | Обработка tool calls |
| `PermissionManager` | Управление разрешениями |
| `ClientRPCHandler` | Обработка agent→client RPC |
| `GlobalPolicyManager` | Глобальные политики разрешений |

**Pipeline стадии:**
1. `ValidationStage` — валидация входных данных
2. `SlashCommandStage` — обработка `/help`, `/mode`, `/status`
3. `PlanBuildingStage` — построение плана
4. `TurnLifecycleStage(open)` — открытие turn
5. `DirectivesStage` — обработка директив промпта
6. `LLMLoopStage` — основной цикл LLM с tool calls
7. `TurnLifecycleStage(close)` — закрытие turn

## Background Receive Loop (Клиент)

Для избежания race condition при конкурентном доступе к WebSocket, клиент использует единый фоновый цикл получения сообщений:

```mermaid
graph TD
    A["WebSocket.receive_text()"] --> B["BackgroundReceiveLoop"]
    B --> C["MessageRouter.route()"]
    C --> D{"Тип сообщения"}
    D -->|session/update| E["notification_queue"]
    D -->|session/request_permission| F["permission_queue"]
    D -->|fs/* или terminal/*| E
    D -->|есть id| G["response_queue[id]"]
    D -->|session/cancel| E
    E --> H["Callbacks в request_with_callbacks()"]
    F --> I["PermissionHandler"]
    G --> J["asyncio.Future.set_result()"]
```

**Ключевые особенности:**
- **Единственный receive()** — избегает RuntimeError при конкурентном доступе
- **Три типа очередей:** response (per-request), notification (shared), permission (shared)
- **Graceful shutdown** — await stop() с 5-секундным таймаутом
- **Broadcast ошибок** — при разрыве соединения все ожидающие очереди получают уведомление

## Двухуровневая история

На сервере существует **двухуровневая система истории**:

| Аспект | SessionState.history | events_history |
|--------|----------------------|-----------------|
| **Содержание** | Message objects (user/assistant) | Structured events (started, added, completed) |
| **Использование** | Передача LLM для контекста | Восстановление state при session/load |
| **Обновление** | Централизованно в PromptOrchestrator | Через TurnLifecycleManager |
| **Размер** | Компактный (только сообщения) | Расширенный (все события) |

**ReplayManager** использует `events_history` для полного восстановления состояния сессии при `session/load`.

## MCP интеграция

Модуль `server/mcp/` обеспечивает подключение внешних MCP-серверов:

| Компонент | Описание |
|-----------|----------|
| `MCPClient` | Клиент для одного MCP-сервера с state machine |
| `MCPManager` | Управление несколькими MCP-серверами на сессию |
| `MCPToolAdapter` | Адаптация MCP инструментов к ACP ToolDefinition |
| `StdioTransport` | Запуск MCP-серверов через stdio subprocess |

**Именование MCP инструментов:** `mcp:server_id:tool_name` (namespace для избежания конфликтов)

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
        S->>C: session/request_permission
        C-->>S: permission response
        S-->>C: notification (result)
    end
    
    S-->>C: session/update {stopReason}
```

**Методы протокола:**
| Метод | Направление | Описание |
|-------|-------------|----------|
| `initialize` | C→S | Инициализация, обмен capabilities |
| `authenticate` | C→S | Аутентификация (API key) |
| `session/new` | C→S | Создание новой сессии |
| `session/load` | C→S | Загрузка существующей сессии |
| `session/list` | C→S | Список сессий |
| `session/prompt` | C→S | Отправка промпта |
| `session/cancel` | C→S | Отмена текущего промпта |
| `session/update` | S→C | Уведомление о ходе выполнения |
| `session/request_permission` | S→C | Запрос разрешения |
| `session/request_permission_response` | C→S | Ответ на запрос разрешения |
| `session/set_config_option` | C→S | Установка опции конфигурации |
| `session/set_mode` | C→S | Установка режима сессии |

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
│   ├── di.py            # Dishka DI контейнер
│   ├── config.py        # Pydantic конфигурация
│   ├── http_server.py   # HTTP/WebSocket сервер
│   ├── web_app.py       # Web UI (textual-web)
│   ├── rpc_holder.py    # ClientRPCServiceHolder
│   ├── protocol/        # ACP протокол
│   │   ├── core.py      # ACPProtocol (dispatcher)
│   │   ├── state.py     # SessionState, ToolCallState
│   │   ├── handlers/    # Обработчики методов
│   │   │   ├── auth.py
│   │   │   ├── session.py
│   │   │   ├── prompt.py
│   │   │   ├── permissions.py
│   │   │   ├── config.py
│   │   │   ├── prompt_orchestrator.py  # Главный координатор
│   │   │   ├── pipeline/               # 7 стадий pipeline
│   │   │   ├── slash_commands/         # /help, /mode, /status
│   │   │   └── ... (менеджеры)
│   │   └── content/     # Extractor, Validator, Formatter
│   ├── agent/           # LLM агент (NaiveAgent, Orchestrator)
│   ├── tools/           # Инструменты (registry, executors)
│   ├── storage/         # Хранилище сессий (LRU cache)
│   ├── mcp/             # MCP интеграция
│   ├── client_rpc/      # Agent→Client RPC
│   ├── llm/             # LLM провайдеры (OpenAI, Mock)
│   └── transport/       # WebSocket, stdio
│
└── client/              # Клиентская часть
    ├── domain/          # Domain Layer (entities, repos)
    ├── application/     # Application Layer (use cases)
    ├── infrastructure/  # Infrastructure Layer (DI, transport)
    │   ├── services/    # ACPTransportService, BackgroundReceiveLoop
    │   ├── handlers/    # FS, Terminal handlers
    │   └── events/      # EventBus
    ├── presentation/    # ViewModels (MVVM, 9 штук)
    └── tui/             # TUI компоненты (45 файлов)
        ├── app.py       # ACPClientApp
        ├── components/  # ChatView, Sidebar, FileTree, ...
        ├── navigation/  # NavigationManager
        └── themes/      # Dark/Light themes
```

## См. также

- [Введение](01-introduction.md) — общая информация о CodeLab
- [Сценарии использования](03-use-cases.md) — примеры применения
- [Спецификация ACP](../../Agent%20Client%20Protocol/protocol/01-Overview.md) — детали протокола
