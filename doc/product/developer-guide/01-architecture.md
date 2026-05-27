# Архитектура CodeLab

> Детальное описание архитектуры клиента и сервера для разработчиков.

## Обзор

CodeLab реализует клиент-серверную архитектуру на основе [Agent Client Protocol (ACP)](../../Agent%20Client%20Protocol/get-started/01-Introduction.md). Проект использует **Dishka DI контейнер** для управления зависимостями и следует принципам **Clean Architecture** на клиенте.

```mermaid
graph TB
    subgraph Client["Клиент (Clean Architecture + MVVM)"]
        TUI[TUI App<br/>45 компонентов]
        VM[9 ViewModels]
        UC[5 Use Cases]
        TS[ACPTransportService]
    end
    
    subgraph Transport["Транспорт"]
        WS[WebSocket]
        STDIO[stdio]
    end
    
    subgraph Server["Сервер (Dishka DI)"]
        HTTP[ACPHttpServer]
        AP[ACPProtocol]
        PO[PromptOrchestrator]
        AO[AgentOrchestrator]
        TR[ToolRegistry]
        Storage[(SessionStorage)]
    end
    
    TUI --> VM --> UC --> TS
    TS --> WS & STDIO
    WS & STDIO --> HTTP --> AP --> PO
    PO --> AO --> TR
    AP --> Storage
```

## Структура проекта

```
codelab/
├── src/codelab/
│   ├── cli.py              # Единая точка входа CLI
│   ├── shared/             # Общие модули
│   │   ├── messages.py     # JSON-RPC сообщения (ACPMessage, JsonRpcError)
│   │   ├── logging.py      # Structlog конфигурация
│   │   └── content/        # ACP Content Types
│   ├── client/             # TUI клиент (Clean Architecture)
│   │   ├── domain/         # Entities, Repositories, Events
│   │   ├── application/    # Use Cases, DTOs, State Machine
│   │   ├── infrastructure/ # DI, Transport, Handlers, EventBus
│   │   ├── presentation/   # 9 ViewModels (MVVM)
│   │   └── tui/            # 45 Textual компонентов
│   └── server/             # ACP сервер (Dishka DI)
│       ├── di.py           # Dishka контейнер (APP/REQUEST scope)
│       ├── config.py       # Pydantic конфигурация
│       ├── http_server.py  # HTTP/WebSocket сервер
│       ├── protocol/       # ACP протокол
│       ├── agent/          # LLM агент
│       ├── tools/          # Инструменты
│       ├── storage/        # Хранилище сессий
│       ├── mcp/            # MCP интеграция
│       └── client_rpc/     # Agent→Client RPC
└── tests/                  # Тесты (~2200)
```

## Архитектура клиента

### Clean Architecture (5 слоёв)

```mermaid
graph TB
    subgraph TUI["TUI Layer"]
        App[ACPClientApp]
        Components[45 компонентов]
    end
    
    subgraph Presentation["Presentation Layer"]
        VM[9 ViewModels]
        Obs[Observable<T>]
    end
    
    subgraph Application["Application Layer"]
        UC[5 Use Cases]
        SM[UIStateMachine]
        PH[PermissionHandler]
    end
    
    subgraph Infrastructure["Infrastructure Layer"]
        DI[Dishka Container]
        TS[ACPTransportService]
        BgLoop[BackgroundReceiveLoop]
        Router[MessageRouter]
        EB[EventBus]
    end
    
    subgraph Domain["Domain Layer"]
        Entities[Session, Message]
        Repos[Repository interfaces]
        Events[16 Domain Events]
    end
    
    App --> Components --> VM --> Obs
    VM --> UC --> SM --> PH
    PH --> DI --> TS --> BgLoop --> Router --> EB
    EB --> Entities & Repos & Events
```

### Domain Layer (`client/domain/`)

**Сущности:**
- `Session` — ACP сессия с ID, capabilities, auth status
- `Message` — протокольное сообщение (request/response/notification)
- `Permission` — запрос разрешения
- `ToolCall` — вызов инструмента агентом

**Интерфейсы:**
- `SessionRepository(ABC)` — save, load, delete, list_all
- `HistoryRepository(ABC)` — save_message, load_history, clear_history
- `TransportService(ABC)` — connect, disconnect, request_with_callbacks, cancel_prompt
- `SessionService(ABC)` — initialize, create_session, send_prompt, cancel_prompt

**Domain Events (16 типов):**
- Session: `SessionCreatedEvent`, `SessionInitializedEvent`, `SessionClosedEvent`, `SessionLoadedEvent`
- Prompt: `PromptStartedEvent`, `PromptCompletedEvent`, `PromptCancelledEvent`
- Permission: `PermissionRequestedEvent`, `PermissionGrantedEvent`, `PermissionDeniedEvent`
- Error: `ErrorOccurredEvent`, `ConnectionLostEvent`, `ConnectionRestoredEvent`
- Tool Call: `ToolCallStartedEvent`, `ToolCallCompletedEvent`, `ToolCallFailedEvent`

### Application Layer (`client/application/`)

**Use Cases (5):**
- `InitializeUseCase` — подключение к серверу, отправка `initialize`
- `CreateSessionUseCase` — создание сессии через `session/new`
- `LoadSessionUseCase` — загрузка сессии через `session/load` с replay updates
- `SendPromptUseCase` — отправка `session/prompt` с callbacks
- `ListSessionsUseCase` — список сессий через `session/list`

**SessionCoordinator** — оркестратор, композирующий все use cases.

**PermissionHandler** — полный цикл запроса разрешений: парсинг → UI modal → ожидание → отправка ответа.

**UIStateMachine** — управление состояниями UI: `INITIALIZING`, `READY`, `PROCESSING_PROMPT`, `WAITING_PERMISSION`, `CANCELLING`, `RECONNECTING`, `ERROR`.

### Infrastructure Layer (`client/infrastructure/`)

**DI Container (Dishka):**
- `create_client_container()` — фабрика контейнера
- `ClientProvider` — инфраструктурные сервисы (транспорт, репозитории, обработчики)
- `ViewModelProvider` — 9 ViewModels

**Транспорт:**
- `WebSocketTransport` — aiohttp WebSocket клиент
- `StdioClientTransport` — запуск агента как subprocess
- `ACPTransportService` — основной сервис транспорта с `request_with_callbacks()` и lock-free `cancel_prompt()`

**BackgroundReceiveLoop** — единый `receive()` на WebSocket для избежания race condition. Маршрутизирует сообщения через `MessageRouter` в `RoutingQueues`:
- `response_queues` — per-request ответные очереди
- `notification_queue` — общие уведомления (session/update, fs/*, terminal/*)
- `permission_queue` — запросы разрешений

**EventBus** — pub/sub система для domain events с поддержкой sync/async handlers.

**Handlers:**
- `FileSystemHandler` + `FileSystemExecutor` — fs/read_text_file, fs/write_text_file
- `TerminalHandler` + `TerminalExecutor` — terminal/create, output, wait_for_exit, release, kill

### Presentation Layer (`client/presentation/`)

**MVVM паттерн с Observable состоянием:**

| ViewModel | Ответственность |
|-----------|-----------------|
| `UIViewModel` | Глобальное UI: connection_status, sidebar, modals, toasts |
| `SessionViewModel` | Управление сессиями: список, создание, переключение |
| `ChatViewModel` | Чат и prompt-turn: сообщения, streaming, tool calls, permissions |
| `PlanViewModel` | Отображение плана агента |
| `TerminalViewModel` | Вывод терминала |
| `FileSystemViewModel` | Дерево файлов |
| `FileViewerViewModel` | Просмотр файла (modal) |
| `PermissionViewModel` | Модальное окно разрешений |
| `TerminalLogViewModel` | Лог терминала (modal) |

**Observable<T>** — реактивное свойство с уведомлением об изменениях.
**ObservableCommand** — async команда с `is_executing` и `error` observables.

### TUI Layer (`client/tui/`)

**45 компонентов** в `tui/components/`:
- **Основные:** `ChatView`, `Sidebar`, `FileTree`, `PromptInput`, `ToolPanel`, `HeaderBar`, `FooterBar`
- **Сообщения:** `MessageBubble`, `MessageList`, `StreamingText`, `ThinkingIndicator`
- **Инструменты:** `ToolCallCard`, `ToolCallList`, `TerminalOutput`, `TerminalPanel`
- **Разрешения:** `PermissionModal`, `PermissionBadge`, `InlinePermissionWidget`
- **Файлы:** `FileViewer`, `FileChangePreview`, `FileChangePreviewModal`
- **Навигация:** `CommandPalette`, `Tabs`, `CollapsiblePanel`, `ContextMenu`
- **Утилиты:** `Toast`, `Spinner`, `Progress`, `SearchInput`, `StatusLine`, `KeyboardManager`, `MarkdownViewer`
- **Макет:** `MainLayout` (OpenCode-style: sidebar, content, dock regions)

**NavigationManager** — централизованное управление фокусом и навигацией.
**ThemeManager** — переключение тем (dark/light).

## Архитектура сервера

### Dishka DI контейнер

**Скоупы:**
- **APP scope** — синглтоны на всё время жизни сервера
- **REQUEST scope** — на одно WebSocket соединение

**Провайдеры (9):**

| Провайдер | Скоуп | Создаёт |
|-----------|-------|---------|
| `ManagersProvider` | APP | StateManager, PlanBuilder, TurnLifecycleManager, ToolCallHandler, PermissionManager, ClientRPCHandler |
| `SlashCommandsProvider` | APP | CommandRegistry, SlashCommandRouter |
| `StorageProvider` | APP | GlobalPolicyStorage, GlobalPolicyManager |
| `LLMProvider_` | APP | LLMProviderRegistry (8+ провайдеров: OpenAI, Anthropic, OpenRouter, Zen, Go, Ollama, LMStudio, Mock) |
| `ToolsProvider` | APP | SimpleToolRegistry |
| `AgentProvider` | APP | AgentOrchestrator |
| `PipelineProvider` | APP | LLMLoopStage, PromptPipeline (7 стадий) |
| `PromptOrchestratorProvider` | APP | ClientRPCServiceHolder, PromptOrchestrator |
| `RequestProvider` | REQUEST | ACPProtocol |

**Holder паттерн:** `ClientRPCServiceHolder` — мост между APP и REQUEST scope. `ClientRPCService` создаётся вручную в `handle_ws_request` и устанавливается в holder перед REQUEST scope.

### Protocol Layer (`server/protocol/`)

**ACPProtocol** — транспорт-agnostic диспетчер методов ACP. Принимает `ACPMessage`, возвращает `ProtocolOutcome`.

**Зарегистрированные методы:**

| Метод | Файл | Описание |
|-------|------|----------|
| `initialize` | `handlers/auth.py` | Инициализация, обмен capabilities |
| `authenticate` | `handlers/auth.py` | Аутентификация |
| `session/new` | `handlers/session.py` | Создание сессии |
| `session/load` | `handlers/session.py` | Загрузка сессии |
| `session/list` | `handlers/session.py` | Список сессий |
| `session/prompt` | `handlers/prompt.py` | Обработка промпта (через PromptOrchestrator) |
| `session/cancel` | `handlers/prompt.py` | Отмена промпта |
| `session/request_permission_response` | `handlers/permissions.py` | Ответ на запрос разрешения |
| `session/set_config_option` | `handlers/config.py` | Установка опции |
| `session/set_mode` | `handlers/config.py` | Установка режима |

**PromptOrchestrator** — центральный координатор prompt-turn. Инжектирует 10+ зависимостей: StateManager, PlanBuilder, TurnLifecycleManager, ToolCallHandler, PermissionManager, ClientRPCHandler, ToolRegistry, LLMLoopStage, ClientRPCServiceHolder, GlobalPolicyManager, CommandRegistry, PromptPipeline.

### Pipeline система (`protocol/handlers/pipeline/`)

**7 стадий обработки промпта:**

1. `ValidationStage` — валидация входных данных
2. `SlashCommandStage` — обработка `/help`, `/mode`, `/status`
3. `PlanBuildingStage` — построение плана выполнения
4. `TurnLifecycleStage(open)` — открытие turn, отправка session/started
5. `DirectivesStage` — обработка директив промпта, фильтрация инструментов
6. `LLMLoopStage` — основной цикл LLM с tool calls (до 10 итераций)
7. `TurnLifecycleStage(close)` — закрытие turn

**LLMLoopStage** — главная стадия:
- Вызов LLM через AgentOrchestrator
- Обработка tool calls с проверкой разрешений
- Выполнение инструментов через ToolRegistry
- Отправка session/update уведомлений

### Slash Commands (`protocol/handlers/slash_commands/`)

**Встроенные команды:**
- `/help` — список доступных команд
- `/mode` — переключение режима сессии
- `/status` — текущее состояние сессии

**Архитектура:** CommandRegistry → SlashCommandRouter → CommandHandler

### Agent Layer (`server/agent/`)

**Архитектура:** Один LLM вызов на turn; цикл tool calls живёт в `LLMLoopStage`, НЕ в агенте.

| Файл | Класс | Описание |
|------|-------|----------|
| `base.py` | `LLMAgent(ABC)` | Интерфейс: `start_turn()`, `continue_turn()`, `cancel_prompt()` |
| `naive.py` | `NaiveAgent` | Реализация с OpenAI function calling |
| `orchestrator.py` | `AgentOrchestrator` | Построение контекстов, фильтрация инструментов по capabilities |
| `plan_extractor.py` | `PlanExtractor` | Извлечение плана из LLM ответа |

**Фильтрация инструментов:** `_SERVER_SIDE_TOOL_KINDS = {"think", "plan"}` — всегда доступны. Остальные (fs_read, fs_write, terminal) требуют matching client capabilities.

### Tool System (`server/tools/`)

**Компоненты:**
- `ToolDefinition` — имя, описание, параметры, kind, requires_permission
- `ToolExecutionResult` — success, output, error, metadata, content
- `SimpleToolRegistry` — in-memory реестр с sync/async executors

**Инструменты:**

| Инструмент | Kind | Requires Permission |
|------------|------|---------------------|
| `fs/read_text_file` | read | Да |
| `fs/write_text_file` | edit | Да |
| `terminal/create` | execute | Да |
| `terminal/wait_for_exit` | read | Нет |
| `terminal/release` | delete | Нет |
| `terminal/kill` | execute | Нет |
| `terminal/output` | read | Нет |
| `update_plan` | think | Нет |

**ToolMapping:** `acp_name_to_llm_name()` (/ → _) и `llm_name_to_acp_name()` (_ → /) для совместимости с LLM провайдерами.

### MCP Integration (`server/mcp/`)

| Файл | Класс | Описание |
|------|-------|----------|
| `models.py` | Pydantic модели | MCPRequest, MCPResponse, MCPTool, MCPServerConfig |
| `transport.py` | `StdioTransport` | Stdio subprocess для MCP |
| `client.py` | `MCPClient` | Клиент для одного MCP-сервера |
| `manager.py` | `MCPManager` | Управление несколькими серверами на сессию |
| `tool_adapter.py` | `MCPToolAdapter` | Адаптация MCP инструментов к ACP |

**Именование:** `mcp:server_id:tool_name` (namespace для избежания конфликтов).

### Storage Layer (`server/storage/`)

| Backend | Файл | Описание |
|---------|------|----------|
| `SessionStorage(ABC)` | `base.py` | Интерфейс: save, load, delete, list (paginated) |
| `InMemoryStorage` | `memory.py` | Dict-based, для development |
| `JsonFileStorage` | `json_file.py` | Один файл на сессию, async I/O |
| `CachedSessionStorage` | `cached.py` | LRU cache (200 sessions) wrapper |
| `GlobalPolicyStorage` | `global_policy_storage.py` | Глобальные политики разрешений |

**CLI:** `--storage memory` или `--storage json:/path`, всегда обёрнуто в `CachedSessionStorage`.

## Потоки данных

### Жизненный цикл запроса

```mermaid
sequenceDiagram
    participant U as User
    participant C as Client
    participant S as ACPProtocol
    participant PO as PromptOrchestrator
    participant LL as LLMLoopStage
    participant AO as AgentOrchestrator
    participant LLM as LLM Provider
    participant TR as ToolRegistry
    participant Storage[(SessionStorage)]

    U->>C: Вводит prompt
    C->>S: session/prompt
    S->>PO: process_prompt_turn()
    PO->>LL: process(context)
    
    loop LLM Loop (до 10 итераций)
        LL->>AO: process_prompt/continue_turn
        AO->>LLM: create_completion(messages, tools)
        LLM-->>AO: LLMResponse(text, tool_calls, stop_reason)
        
        alt stop_reason = end_turn
            LL-->>PO: stop_reason=end_turn
        else stop_reason = tool_use
            loop Для каждого tool call
                LL->>LL: decide_tool_execution()
                
                alt policy = allow
                    LL->>TR: execute_tool()
                    TR-->>LL: ToolResult
                else policy = ask
                    LL->>LL: build_permission_request()
                    Note over LL: active_turn.permission_request_id = msg.id
                    LL-->>PO: pending_permission=True
                    PO-->>S: ProtocolOutcome(notifications)
                    S->>Storage: save_session(session)
                    S-->>C: session/request_permission
                    Note over C: UI: permission widget
                    C->>S: response (id=permission_request_id)
                    S->>S: _resolve_permission_response()
                    S->>Storage: find_session_by_permission_request_id()
                    Note over S: permission_request_id совпадает → session found
                    S->>S: resolve_permission_response_impl()
                    Note over S: pending_tool_execution → background task
                    S->>S: _execute_tool_in_background()
                    S->>PO: execute_pending_tool()
                    PO->>LL: execute_pending_tool()
                    LL->>TR: execute_tool()
                    TR-->>LL: ToolResult
                    LL->>LLM: continue_turn(tool_results)
                    LLM-->>LL: next response
                    
                    alt LLM вернул ещё tool с permission
                        LL->>LL: build_permission_request()
                        Note over LL: НОВЫЙ permission_request_id
                        LL-->>PO: pending_permission=True
                        PO-->>S: LLMLoopResult
                        S->>Storage: save_session(session)
                        Note over Storage: НОВЫЙ permission_request_id сохранён
                    end
                else policy = reject
                    LL->>LL: mark tool as failed
                    LL->>LLM: continue_turn(failed_result)
                end
                
                S-->>C: session/update
            end
        end
    end
    
    PO-->>S: ProtocolOutcome
    S->>Storage: save_session(session)
    S-->>C: session/update + result
    C-->>U: Показывает ответ
```

### Отмена промпта

`ACPTransportService.request_with_callbacks()` удерживает глобальный `asyncio.Lock` на всё время выполнения `session/prompt`. Чтобы отмена не вставала в очередь за этим локом, `cancel_prompt()` обходит `_callbacks_request_lock`:

```
cancel_prompt(session_id) → обходит _callbacks_request_lock
    └─ создаёт per-request response queue
    └─ отправляет session/cancel напрямую через send()
    └─ ждёт ответа (timeout 5 с) и очищает очередь
```

На стороне сервера `session/cancel` отменяет активный `asyncio.Task` с LLM-запросом через `AgentOrchestrator.cancel_prompt()`, что немедленно прерывает HTTP-запрос к модели (`CancelledError`).

## Дополнительные материалы

- [Разработка клиента](02-client-development.md) — детали реализации клиента
- [Разработка сервера](03-server-development.md) — детали реализации сервера
- [Обработчики протокола](04-protocol-handlers.md) — создание новых handlers
- [Тестирование](05-testing.md) — запуск и написание тестов
- [Вклад в проект](06-contributing.md) — как внести вклад
