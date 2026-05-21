# Архитектура ACP Protocol — Детальное руководство

## Оглавление

1. [Введение](#введение)
2. [Обзор системы](#обзор-системы)
3. [Архитектура на уровне компонентов](#архитектура-на-уровне-компонентов)
4. [Потоки данных](#потоки-данных)
5. [Транспортный слой](#транспортный-слой)
6. [Двухуровневая история в codelab.server](#двухуровневая-история)
7. [Background Receive Loop в codelab.client](#background-receive-loop)
8. [Критические архитектурные решения](#критические-архитектурные-решения)
9. [Расширение и интеграция](#расширение-и-интеграция)

---

## Введение

ACP (Agent Client Protocol) — стандартный протокол взаимодействия между LLM-агентами и клиентами для выполнения задач с инструментами.

Проект реализован как **монорепозиторий** с двумя независимыми Python-компонентами:
- **[codelab/](codelab/)** — серверная реализация протокола с LLM-агентом и управлением сессиями
- **[codelab/](codelab/)** — клиентская реализация с TUI интерфейсом на базе Clean Architecture

---

## Обзор системы

### Диаграмма высокоуровневой архитектуры

```mermaid
graph TB
    subgraph Client["codelab-client (Client Side)"]
        TUI["🖥️ TUI Layer<br/>Textual UI Components"]
        Presentation["📊 Presentation Layer<br/>ViewModels + Observable"]
        Application["🎯 Application Layer<br/>Use Cases + State Machine"]
        Infrastructure["🔧 Infrastructure Layer<br/>DI, Transport, Event Bus"]
        Domain["📦 Domain Layer<br/>Entities, Events, Interfaces"]
    end
    
    subgraph Server["codelab-server (Server Side)"]
        Transport["🌐 Transport Layer<br/>WebSocket / stdio"]
        Protocol["🔄 Protocol Layer<br/>ACPProtocol + Handlers"]
        Agent["🤖 Agent Layer<br/>LLM Orchestration"]
        Tools["🛠️ Tools Layer<br/>Executors + Registry"]
        Storage["💾 Storage Layer<br/>SessionStorage Backends"]
    end
    
    subgraph Transports["Транспорты"]
        WS["WebSocket<br/>Connection"]
        STDIO["stdio<br/>stdin/stdout"]
    end
    
    TUI --> Presentation
    Presentation --> Application
    Application --> Infrastructure
    Infrastructure --> Domain
    Infrastructure --> Transports
    
    Transports --> Transport
    WS --> Transport
    STDIO --> Transport
    Transport --> Protocol
    Protocol --> Agent
    Protocol --> Tools
    Protocol --> Storage
    Agent --> Tools
    
    style Client fill:#e1f5ff,stroke:#01579b,stroke-width:2px
    style Server fill:#f3e5f5,stroke:#4a148c,stroke-width:2px
    style Transports fill:#fff3e0,stroke:#e65100,stroke-width:2px
```

### Таблица компонентов

| Компонент | Слой | Ответственность | Файлы |
|-----------|------|-----------------|-------|
| **TUI** | Presentation | Textual компоненты, User Interaction | `codelab/src/codelab/client/tui/` |
| **ViewModels** | Presentation | MVVM паттерн, Observable state | `codelab/src/codelab/client/presentation/` |
| **Use Cases** | Application | Business scenarios, DTOs | `codelab/src/codelab/client/application/` |
| **DIContainer** | Infrastructure | Dependency Injection | [`codelab/src/codelab/client/infrastructure/di_container.py`](codelab/src/codelab/client/infrastructure/di_container.py:33) |
| **BackgroundReceiveLoop** | Infrastructure | Единственный receive() на транспорт | [`codelab/src/codelab/client/infrastructure/services/background_receive_loop.py`](codelab/src/codelab/client/infrastructure/services/background_receive_loop.py:22) |
| **MessageRouter** | Infrastructure | Маршрутизация сообщений | [`codelab/src/codelab/client/infrastructure/services/message_router.py`](codelab/src/codelab/client/infrastructure/services/message_router.py:26) |
| **EventBus** | Infrastructure | Pub/Sub система событий | [`codelab/src/codelab/client/infrastructure/events/bus.py`](codelab/src/codelab/client/infrastructure/events/bus.py) |
| **StdioClientTransport** | Infrastructure | stdio транспорт (subprocess) | [`codelab/src/codelab/client/infrastructure/stdio_transport.py`](codelab/src/codelab/client/infrastructure/stdio_transport.py) |
| **ACPProtocol** | Protocol | Диспетчер методов ACP, `handle_and_process` для фоновых задач | [`codelab/src/codelab/server/protocol/core.py`](codelab/src/codelab/server/protocol/core.py:39) |
| **Handlers** | Protocol | Обработчики методов (auth, session, prompt) | [`codelab/src/codelab/server/protocol/handlers/`](codelab/src/codelab/server/protocol/handlers/) |
| **PromptOrchestrator** | Protocol | Главный оркестратор prompt-turn | [`codelab/src/codelab/server/protocol/handlers/prompt_orchestrator.py`](codelab/src/codelab/server/protocol/handlers/prompt_orchestrator.py:32) |
| **AgentOrchestrator** | Agent | Управление LLM-агентом | [`codelab/src/codelab/server/agent/orchestrator.py`](codelab/src/codelab/server/agent/orchestrator.py:18) |
| **ToolRegistry** | Tools | Регистрация и управление инструментами | [`codelab/src/codelab/server/tools/registry.py`](codelab/src/codelab/server/tools/registry.py) |
| **ToolMapping** | Tools | Маппинг имён ACP ↔ LLM (fs/read → fs_read) | [`codelab/src/codelab/server/tools/mapping.py`](codelab/src/codelab/server/tools/mapping.py) |
| **Storage** | Storage | Persistence для сессий | [`codelab/src/codelab/server/storage/`](codelab/src/codelab/server/storage/) |
| **WebSocketTransport** | Transport | WebSocket endpoint | [`codelab/src/codelab/server/transport/websocket.py`](codelab/src/codelab/server/transport/websocket.py) |
| **StdioServerTransport** | Transport | stdio транспорт (stdin/stdout) | [`codelab/src/codelab/server/transport/stdio.py`](codelab/src/codelab/server/transport/stdio.py) |
| **StdioRunner** | Transport | Запуск stdio сервера с DI | [`codelab/src/codelab/server/transport/stdio_runner.py`](codelab/src/codelab/server/transport/stdio_runner.py) |

---

## Архитектура на уровне компонентов

### codelab-server: Внутренняя структура

```mermaid
graph LR
    subgraph Transport["Transport Layer"]
        WS["WebSocket<br/>Endpoint"]
        STDIO["stdio<br/>stdin/stdout"]
        Base["AcpServerTransport<br/>Protocol Interface"]
    end
    
    subgraph Protocol["Protocol Layer"]
        Core["ACPProtocol"]
        Handlers["Handlers<br/>auth / session / prompt"]
        PromptOrch["PromptOrchestrator<br/>(Главный координатор)"]
    end
    
    subgraph Processing["Processing"]
        Agent["AgentOrchestrator<br/>LLM обработка"]
        ToolReg["ToolRegistry<br/>Управление инструментами"]
        Executors["Executors<br/>FS / Terminal"]
    end
    
    subgraph Persistence["Persistence"]
        SessionStore["SessionStorage<br/>Abstract"]
        InMem["InMemoryStorage"]
        JsonFile["JsonFileStorage"]
    end
    
    subgraph RPC["Client RPC"]
        ClientRPCService["ClientRPCService<br/>Асинхронные вызовы"]
    end
    
    WS --> Base
    STDIO --> Base
    Base --> Core
    Core --> Handlers
    Handlers --> PromptOrch
    PromptOrch --> Agent
    PromptOrch --> ToolReg
    ToolReg --> Executors
    Executors --> ClientRPCService
    ClientRPCService --> Base
    
    Core --> SessionStore
    SessionStore --> InMem
    SessionStore --> JsonFile
    
    style Transport fill:#fff3e0
    style Protocol fill:#f3e5f5
    style Processing fill:#e8f5e9
    style Persistence fill:#e0f2f1
    style RPC fill:#fce4ec
```

### codelab-client: Clean Architecture в 5 слоев

```mermaid
graph TB
    subgraph TUI["TUI Layer"]
        Chat["Chat View<br/>Terminal UI"]
        FileView["File Viewer"]
        Permission["Permission Modal"]
        Terminal["Terminal Output"]
    end
    
    subgraph Presentation["Presentation Layer"]
        ChatVM["ChatViewModel"]
        FileVM["FileSystemViewModel"]
        PermVM["PermissionViewModel"]
        SessionVM["SessionViewModel"]
    end
    
    subgraph Application["Application Layer"]
        UseCases["Use Cases<br/>session/prompt/load"]
        StateMachine["UIStateMachine<br/>State Management"]
        DTOs["DTOs<br/>Data Transfer Objects"]
    end
    
    subgraph Infrastructure["Infrastructure Layer"]
        Transport["Transport Service<br/>WebSocket / stdio"]
        BgLoop["BackgroundReceiveLoop<br/>Единственный receive()"]
        Router["MessageRouter<br/>Маршрутизация"]
        Queues["RoutingQueues<br/>Распределение"]
        EventBus["EventBus<br/>Pub/Sub система"]
        DI["DIContainer<br/>Dependency Injection"]
        StdioTransport["StdioClientTransport<br/>subprocess"]
        
        subgraph AgentRPC["Agent → Client RPC"]
            FSHandler["FileSystemHandler"]
            TermHandler["TerminalHandler"]
            FSExec["FileSystemExecutor"]
            TermExec["TerminalExecutor"]
        end
    end
    
    subgraph Domain["Domain Layer"]
        Entities["Entities<br/>Session, Message"]
        Events["Events<br/>Domain Events"]
        Repos["Repositories<br/>Interfaces"]
    end
    
    Chat --> ChatVM
    FileView --> FileVM
    Permission --> PermVM
    Terminal --> SessionVM
    
    ChatVM --> UseCases
    FileVM --> UseCases
    PermVM --> UseCases
    SessionVM --> UseCases
    
    UseCases --> StateMachine
    StateMachine --> DTOs
    
    DTOs --> Transport
    DTOs --> EventBus
    
    Transport --> BgLoop
    BgLoop --> Router
    Router --> Queues
    Queues --> EventBus
    
    Router --> FSHandler
    Router --> TermHandler
    FSHandler --> FSExec
    TermHandler --> TermExec
    
    EventBus --> Entities
    EventBus --> Events
    EventBus --> Repos
    
    DI --> TUI
    DI --> Presentation
    DI --> Application
    DI --> Infrastructure
    
    style TUI fill:#fff3e0,stroke:#e65100,stroke-width:2px
    style Presentation fill:#f3e5f5,stroke:#6a1b9a,stroke-width:2px
    style Application fill:#e8f5e9,stroke:#1b5e20,stroke-width:2px
    style Infrastructure fill:#e0f2f1,stroke:#004d40,stroke-width:2px
    style Domain fill:#eceff1,stroke:#263238,stroke-width:2px
```

---

## Потоки данных

### 1. Отправка промпта (Client → Server)

```mermaid
sequenceDiagram
    actor User
    participant TUI
    participant ChatVM
    participant UseCase
    participant Transport
    participant BgLoop
    participant Server as codelab-server

    User->>TUI: Вводит промпт
    TUI->>ChatVM: prompt_text.value = "..."
    ChatVM->>UseCase: send_prompt(session_id, text)
    UseCase->>Transport: request_with_callbacks(method="session/prompt")
    
    Transport->>Transport: Отправляет JSON-RPC<br/>на WebSocket
    Transport->>Transport: Создает asyncio.Future<br/>для ожидания результата
    
    rect RGB(200, 220, 255)
        Note over BgLoop,Server: В фоне: BackgroundReceiveLoop слушает
        Server->>Transport: Начинает обработку prompt
        Server->>Transport: Отправляет session/update
        Transport->>BgLoop: receive() получает update
        BgLoop->>Router: route(message)
        Router->>Queues: Помещает в notification_queue
        Queues->>UseCase: on_update_callback вызывается
        UseCase->>ChatVM: Обновляет view_model
    end
    
    Server->>Transport: Обработка завершена<br/>отправляет result
    Transport->>BgLoop: receive() получает result
    BgLoop->>Router: route(message) → response[id]
    Router->>Queues: response_queue[id].put(result)
    Queues->>Transport: await future.set_result()
    Transport->>UseCase: Возвращает результат
    UseCase->>ChatVM: Обновляет final state
    ChatVM->>TUI: Отрисовка завершена
```

### 2. Обработка session/prompt на сервере

```mermaid
sequenceDiagram
    participant Client
    participant HttpServer
    participant ACPProtocol
    participant PromptOrch as PromptOrchestrator
    participant Agent as AgentOrchestrator
    participant Tools as ToolRegistry
    participant ClientRPC as ClientRPCService

    Client->>HttpServer: session/prompt request
    HttpServer->>ACPProtocol: handle(message)
    
    ACPProtocol->>PromptOrch: process_prompt_turn(session_id, text)
    
    PromptOrch->>PromptOrch: 1. Валидация и preprocessing
    
    PromptOrch->>Agent: 2. agent.process_prompt(context)
    Agent->>Agent: Добавляет user message в LLM контекст
    Agent->>Tools: Получает доступные tools
    Agent->>Agent: Вызывает LLM
    
    Agent->>Tools: 3. Выполнение tool calls
    Tools->>ClientRPC: Запрос инструмента (fs/*, terminal/*)
    ClientRPC->>Client: RPC вызов (fs/readTextFile и т.д.)
    Client->>ClientRPC: Результат инструмента
    
    PromptOrch->>PromptOrch: 4. Обновление session/history
    PromptOrch->>PromptOrch: 5. Отправка session/update
    
    HttpServer->>Client: Итоговый результат
```

### 3. Обработка permission request на клиенте

```mermaid
sequenceDiagram
    participant Server as codelab-server
    participant BgLoop as BackgroundReceiveLoop
    participant PermVM as PermissionViewModel
    participant User as 👤 User
    participant Transport

    Server->>BgLoop: session/request_permission
    BgLoop->>Router: route(message) → permission_queue
    Router->>Queues: permission_queue.put(request)
    Queues->>PermVM: Уведомление о запросе
    
    PermVM->>PermVM: Заполняет permission data
    PermVM->>User: Показывает permission modal
    
    User->>User: Рассматривает запрос
    User->>PermVM: Нажимает Allow/Deny
    
    PermVM->>Transport: session/request_permission_response
    Transport->>Server: JSON-RPC ответ
    Server->>Server: Вычисляет result
    Server->>Transport: Отправляет session/update
    Transport->>BgLoop: receive() получает update
    BgLoop->>PermVM: on_update_callback
    PermVM->>PermVM: Обновляет state
```

### 4. Background Receive Loop: Маршрутизация сообщений

```mermaid
graph TD
    A["receive() на WebSocket<br/>await transport.receive()"]
    B["Парсинг JSON"]
    C{"Анализ сообщения"}
    
    D["message.method == 'session/update'"]
    E["message.method == 'session/request_permission'"]
    F["message.method == 'fs/*' или 'terminal/*'"]
    G["message.id присутствует"]
    H["Неизвестный тип"]
    
    D --> D1["→ notification_queue<br/>on_update_callback"]
    E --> E1["→ permission_queue<br/>on_permission_callback"]
    F --> F1["→ notification_queue<br/>request_with_callbacks callback"]
    G --> G1["→ response_queue[id]<br/>asyncio.Future.set_result"]
    H --> H1["Логирование ошибки"]
    
    A --> B --> C
    C -->|method first| D
    C -->|method first| E
    C -->|method first| F
    C -->|id check| G
    C -->|default| H
    
    D1 --> I["Распределение в очереди"]
    E1 --> I
    F1 --> I
    G1 --> I
    
    I --> J["Вызов callbacks<br/>или set asyncio.Future"]
    J --> A
    
    style A fill:#fff3e0,stroke:#e65100,stroke-width:2px
    style C fill:#f3e5f5,stroke:#6a1b9a,stroke-width:2px
    style I fill:#e8f5e9,stroke:#1b5e20,stroke-width:2px
    style J fill:#e0f2f1,stroke:#004d40,stroke-width:2px
```

---

## Транспортный слой

### Архитектура транспорта

`ACPProtocol` (dispatcher) **не зависит от транспорта** — он принимает `ACPMessage` и возвращает `ProtocolOutcome`. Транспортный слой реализует передачу сообщений между клиентом и сервером.

```mermaid
graph TB
    subgraph Server["Сервер"]
        ACP["ACPProtocol (core)<br/>transport-agnostic"]
        WS["WebSocketTransport"]
        STDIO_S["StdioServerTransport"]
        Base_S["AcpServerTransport<br/>Protocol"]
    end

    subgraph Client["Клиент"]
        WS_C["WebSocketTransport"]
        STDIO_C["StdioClientTransport<br/>(subprocess)"]
        Service["ACPTransportService"]
    end

    ACP --> Base_S
    WS --> Base_S
    STDIO_S --> Base_S
    WS_C --> WS
    STDIO_C --> STDIO_S
    Service --> WS_C
    Service --> STDIO_C
```

### Режимы работы

| Режим | Команда | Транспорт | Описание |
|-------|---------|-----------|----------|
| **Локальный** | `codelab` | stdio (subprocess) | Сервер запускается как subprocess, TUI подключается через stdio |
| **WebSocket сервер** | `codelab serve` | WebSocket | Сервер слушает ws://host:port/acp/ws |
| **stdio сервер** | `codelab serve --stdio` | stdio | Сервер читает stdin, пишет stdout (для IDE plugins) |
| **WebSocket клиент** | `codelab connect` | WebSocket | TUI подключается к удалённому серверу |
| **stdio клиент** | `codelab connect --stdio` | stdio (subprocess) | TUI запускает агент как subprocess |

### Серверный транспорт

**Интерфейс `AcpServerTransport`:**

```python
class AcpServerTransport(Protocol):
    async def run(
        self,
        on_message: Callable[[ACPMessage], Awaitable[ProtocolOutcome]],
    ) -> None: ...

    async def send(self, message: ACPMessage) -> None: ...
    async def close(self) -> None: ...
```

**Реализации:**

| Транспорт | Файл | Особенности |
|-----------|------|-------------|
| `WebSocketTransport` | `server/transport/websocket.py` | aiohttp WebSocket, Web UI |
| `StdioServerTransport` | `server/transport/stdio.py` | stdin/stdout, newline-delimited JSON-RPC |

**Ключевые детали stdio сервера:**

| Аспект | Решение |
|--------|---------|
| **Логирование** | ТОЛЬКО в stderr. Structlog handler на stderr |
| **Buffering** | `line_buffering=True` + ручной flush после каждого сообщения |
| **Agent→Client RPC** | Единый `asyncio.Lock` на запись в stdout |
| **EOF** | Graceful exit из цикла, cleanup pending operations |
| **SIGTERM/SIGINT** | Signal handlers → `close()` + `sys.exit(0)` |

### Клиентский транспорт

**Интерфейс `Transport`:**

```python
class Transport(Protocol):
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def send_str(self, data: str) -> None: ...
    async def receive_text(self) -> str: ...
    def is_connected(self) -> bool: ...
```

**Реализации:**

| Транспорт | Файл | Особенности |
|-----------|------|-------------|
| `WebSocketTransport` | `client/infrastructure/transport.py` | aiohttp WebSocket |
| `StdioClientTransport` | `client/infrastructure/stdio_transport.py` | asyncio subprocess, background reader |

**Ключевые детали stdio клиента:**

| Аспект | Решение |
|--------|---------|
| **Запуск** | `asyncio.create_subprocess_exec(command, *args, stdin=PIPE, stdout=PIPE, stderr=PIPE)` |
| **stdout reader** | Background task → `asyncio.Queue[str]` |
| **stderr reader** | Background task → логирование |
| **Graceful shutdown** | Close stdin → wait 5s → kill if needed |
| **Process exit** | Если процесс завершился → error при `receive_text()` |

---

## Двухуровневая история

### SessionState.history vs events_history

На сервере в codelab.server существует **двухуровневая система истории**:

```mermaid
graph TB
    subgraph LLMContext["LLM Context (SessionState.history)"]
        M1["user: Привет"]
        M2["assistant: Привет!"]
        M3["user: Выполни задачу X"]
    end
    
    subgraph ReplayContext["Replay Context (events_history)"]
        E1["session/started"]
        E2["message_added: user message"]
        E3["tool_call_started"]
        E4["tool_call_completed"]
        E5["message_added: assistant message"]
    end
    
    LLMContext -->|читается| AgentLLM["AgentOrchestrator<br/>для process_prompt"]
    ReplayContext -->|используется| SessionLoad["session/load<br/>для восстановления состояния"]
    
    NewPrompt["Новый prompt"]
    NewPrompt -->|добавляет в| LLMContext
    NewPrompt -->|добавляет events в| ReplayContext
    
    style LLMContext fill:#e3f2fd,stroke:#1565c0,stroke-width:2px
    style ReplayContext fill:#f3e5f5,stroke:#6a1b9a,stroke-width:2px
    style AgentLLM fill:#fff3e0,stroke:#e65100,stroke-width:2px
    style SessionLoad fill:#e8f5e9,stroke:#1b5e20,stroke-width:2px
```

**Ключевые различия:**

| Аспект | SessionState.history | events_history |
|--------|----------------------|-----------------|
| **Содержание** | Message objects (user/assistant) | Structured events (started, added, completed) |
| **Использование** | Передача LLM для контекста | Восстановление state при load |
| **Обновление** | Централизованно в PromptOrchestrator | Через TurnLifecycleManager |
| **Размер** | Компактный (только сообщения) | Расширенный (все события) |
| **Воспроизведение** | Невозможно (информация потеряна) | Полное восстановление через replay |

**Архитектурное решение:**
- **AgentOrchestrator.process_prompt()** — **НЕ** модифицирует SessionState
- **PromptOrchestrator** отвечает за добавление messages в history
- **TurnLifecycleManager** добавляет события в events_history
- Это обеспечивает **разделение ответственности** и **централизованное управление**

---

## Background Receive Loop

### Проблема: Race Condition при конкурентном доступе к WebSocket

```mermaid
graph LR
    subgraph Wrong["❌ Неправильно: Race Condition"]
        T1["Task 1<br/>receive()"]
        T2["Task 2<br/>receive()"]
        WS["WebSocket"]
        Error["RuntimeError:<br/>Only one receive() allowed"]
        
        T1 -->|получает сообщение| WS
        T2 -->|пытается получить| WS
        WS --> Error
    end
    
    subgraph Right["✅ Правильно: BackgroundReceiveLoop"]
        BgLoop["BackgroundReceiveLoop<br/>Единственный receive()"]
        Q1["response_queue"]
        Q2["notification_queue"]
        Q3["permission_queue"]
        T1["Task 1<br/>ждет response[id]"]
        T2["Task 2<br/>ждет callback"]
        
        BgLoop -->|message| Router["MessageRouter"]
        Router -->|маршрутизирует| Q1
        Router -->|маршрутизирует| Q2
        Router -->|маршрутизирует| Q3
        
        Q1 -->|asyncio.Future| T1
        Q2 -->|callback| T2
        Q3 -->|permission queue| T2
    end
    
    style Wrong fill:#ffebee,stroke:#c62828,stroke-width:2px
    style Right fill:#e8f5e9,stroke:#1b5e20,stroke-width:2px
    style Error fill:#ffcdd2,stroke:#b71c1c,stroke-width:2px
```

### Архитектура BackgroundReceiveLoop

```
┌─────────────────────────────────────────────────────────┐
│         BackgroundReceiveLoop                           │
│                                                          │
│  ┌──────────────────────────────────────────────┐      │
│  │ Главный цикл (asyncio.Task)                  │      │
│  │                                               │      │
│  │  while not should_stop:                      │      │
│  │    message = await transport.receive()       │      │
│  │    routing_key = router.route(message)       │      │
│  │    queue = queues.get(routing_key)           │      │
│  │    queue.put(message)                        │      │
│  └──────────────────────────────────────────────┘      │
│                     │                                   │
│    ┌────────────────┼────────────────┐                 │
│    ▼                ▼                ▼                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐         │
│  │Response  │  │Notif.    │  │Permission    │         │
│  │Queue     │  │Queue     │  │Queue         │         │
│  │          │  │          │  │              │         │
│  │[id1]:    │  │events:   │  │requests:     │         │
│  │Future    │  │list      │  │list          │         │
│  │[id2]:    │  │          │  │              │         │
│  │Future    │  │          │  │              │         │
│  └──────────┘  └──────────┘  └──────────────┘         │
│      ▲              ▲              ▲                   │
│      │              │              │                   │
│  ┌───┴──────────────┴──────────────┴─────┐            │
│  │ Потребители:                          │            │
│  │ - request_with_callbacks              │            │
│  │ - on_update_callback                  │            │
│  │ - on_permission_callback              │            │
│  └───────────────────────────────────────┘            │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

**Ключевые особенности:**

1. **Единственный receive()** — избегает RuntimeError при конкурентном доступе
2. **Маршрутизация на основе сообщения** — router.route() определяет очередь
3. **Три типа очередей:**
   - **response_queue** — RPC ответы (по id)
   - **notification_queue** — асинхронные уведомления (session/update, fs/*, terminal/*)
   - **permission_queue** — запросы разрешений
4. **Graceful shutdown** — await stop() дожидается завершения loop
5. **Диагностика** — счетчики сообщений и ошибок для мониторинга
6. **Async callbacks** — callbacks поддерживают как sync так и async функции через `_call_callback()`, что предотвращает блокировку event loop в stdio режиме

---

## Критические архитектурные решения

### 1. Абстракция SessionStorage в codelab.server

**Проблема:** Нужна гибкость в выборе хранилища (в памяти для dev, на диске для prod).

**Решение:** [`SessionStorage(ABC)`](codelab/src/codelab/server/storage/base.py) — интерфейс с двумя реализациями:

```mermaid
graph TB
    subgraph Interface["SessionStorage Abstract Interface"]
        create["async create_session()"]
        load["async load_session()"]
        list["async list_sessions()"]
        update["async update_session()"]
        delete["async delete_session()"]
    end
    
    subgraph Memory["InMemoryStorage"]
        MemDict["dict[id] = SessionState<br/>в памяти"]
    end
    
    subgraph File["JsonFileStorage"]
        FileDict["dir/id.json<br/>на диске"]
    end
    
    Interface --> Memory
    Interface --> File
    
    CLI["CLI флаг<br/>--storage"]
    CLI -->|memory://| Memory
    CLI -->|json://path| File
    
    style Interface fill:#f3e5f5,stroke:#6a1b9a,stroke-width:2px
    style Memory fill:#e8f5e9,stroke:#1b5e20,stroke-width:2px
    style File fill:#fff3e0,stroke:#e65100,stroke-width:2px
```

**Преимущества:**
- ✅ Easy testing (InMemoryStorage)
- ✅ Production persistence (JsonFileStorage)
- ✅ Plug-and-play новых backends (Redis, PostgreSQL)
- ✅ Изоляция логики хранения от протокола

### 2. Транспортная абстракция

**Проблема:** Нужна поддержка нескольких транспортов (WebSocket, stdio) без дублирования бизнес-логики.

**Решение:** `ACPProtocol` transport-agnostic, транспорт реализует единый интерфейс:

```mermaid
graph TB
    subgraph Protocol["ACPProtocol (transport-agnostic)"]
        Handle["handle(message) → outcome"]
        HandleAndProcess["handle_and_process(message)\n→ handle() + background tasks"]
        BackgroundTool["_execute_tool_in_background()\n(фоновая задача)"]
        SendCallback["_send_callback()\n(отправка из фона)"]
    end
    
    subgraph Transports["Transport Implementations"]
        WS["WebSocketTransport\naiohttp WebSocket"]
        STDIO["StdioServerTransport\nstdin/stdout"]
    end
    
    WS --> HandleAndProcess
    STDIO --> HandleAndProcess
    HandleAndProcess --> Handle
    HandleAndProcess --> BackgroundTool
    BackgroundTool --> SendCallback
    SendCallback --> WS
    SendCallback --> STDIO
    
    style Protocol fill:#f3e5f5,stroke:#6a1b9a,stroke-width:2px
    style Transports fill:#fff3e0,stroke:#e65100,stroke-width:2px
    style HandleAndProcess fill:#e8f5e9,stroke:#1b5e20,stroke-width:2px
```

**Преимущества:**
- ✅ Единая бизнес-логика для всех транспортов
- ✅ Локальный режим использует stdio (соответствует spec ACP)
- ✅ `codelab serve --stdio` для интеграции с IDE plugins
- ✅ Изолированный процесс сервера в local mode

### Маппинг имён инструментов ACP ↔ LLM

**Проблема:** ACP протокол использует имена инструментов с `/` (например `fs/read_text_file`, `terminal/create`), но некоторые LLM провайдеры (Azure через OpenRouter) не поддерживают символ `/` в именах функций. Допустимый паттерн: `^[a-zA-Z0-9_\.-]+$`.

**Решение:** [`tools/mapping.py`](codelab/src/codelab/server/tools/mapping.py) обеспечивает двусторонний маппинг:

```mermaid
graph LR
    subgraph ACP["ACP Protocol Names"]
        A1["fs/read_text_file"]
        A2["fs/write_text_file"]
        A3["terminal/create"]
        A4["terminal/wait_for_exit"]
    end
    
    subgraph Mapping["ToolMapping"]
        M1["acp_name_to_llm_name()\n/ → _"]
        M2["llm_name_to_acp_name()\n_ → / (для известных префиксов)"]
    end
    
    subgraph LLM["LLM API Names"]
        L1["fs_read_text_file"]
        L2["fs_write_text_file"]
        L3["terminal_create"]
        L4["terminal_wait_for_exit"]
    end
    
    A1 --> M1 --> L1
    A2 --> M1 --> L2
    A3 --> M1 --> L3
    A4 --> M1 --> L4
    
    L1 --> M2 --> A1
    L2 --> M2 --> A2
    L3 --> M2 --> A3
    L4 --> M2 --> A4
    
    style ACP fill:#e3f2fd,stroke:#1565c0,stroke-width:2px
    style LLM fill:#fff3e0,stroke:#e65100,stroke-width:2px
    style Mapping fill:#f3e5f5,stroke:#6a1b9a,stroke-width:2px
```

**Где применяется:**

| Место | Направление | Описание |
|-------|-------------|----------|
| `NaiveAgent._to_openai_tools_format()` | ACP → LLM | При отправке инструментов в LLM API |
| `SimpleToolRegistry.to_llm_tools()` | ACP → LLM | При конвертации для LLM |
| `SimpleToolRegistry.execute_tool()` | LLM → ACP | При выполнении инструмента (lookup в registry) |
| `LLMLoopStage._process_tool_calls()` | LLM → ACP | При обработке tool calls от LLM |

**Пример:**
```python
>>> acp_name_to_llm_name("fs/read_text_file")
"fs_read_text_file"
>>> llm_name_to_acp_name("fs_read_text_file")
"fs/read_text_file"
```

### 3. Фильтрация инструментов по ClientRuntimeCapabilities

**Проблема:** Не все клиенты поддерживают все инструменты (например, некоторые не поддерживают file system операции).

**Решение:** [`ClientRuntimeCapabilities`](codelab/src/codelab/server/protocol/state.py) для фильтрации:

```python
# Пример из PromptOrchestrator
available_tools = [
    tool for tool in all_tools
    if client_capabilities.supports_tool(tool.id)
]
```

**Ключевые возможности:**
- `supports_filesystem`: Поддержка fs операций
- `supports_terminal`: Поддержка terminal операций
- `max_tool_call_iterations`: Максимальное количество итераций tool calls

### 4. ClientRPCService для асинхронных вызовов

**Проблема:** Инструменты (fs/*, terminal/*) должны выполняться асинхронно на клиенте, а сервер ждет результата.

**Решение:** [`ClientRPCService`](codelab/src/codelab/server/client_rpc/service.py) управляет [`asyncio.Future`](codelab/src/codelab/server/client_rpc/models.py):

```mermaid
graph TD
    A["Инструмент начинает выполнение"]
    B["ClientRPCService.execute_tool()"]
    C["Отправляет RPC на клиент"]
    D["Создает asyncio.Future"]
    E["await future (блокирует до результата)"]
    F["Клиент выполняет операцию"]
    G["Отправляет ответ"]
    H["ClientRPCService получает ответ"]
    I["future.set_result()"]
    J["Инструмент получает результат"]
    
    A --> B --> C --> D --> E
    F --> G --> H --> I --> J
    
    style E fill:#fff3e0,stroke:#e65100,stroke-width:2px
    style I fill:#e8f5e9,stroke:#1b5e20,stroke-width:2px
```

### 4.1. Terminal output flow (по ACP spec)

**Проблема:** По спецификации ACP `terminal/wait_for_exit` возвращает только `exitCode` и `signal` — без output. Output получается через отдельный метод `terminal/output`.

**Решение:** [`TerminalToolExecutor.execute_wait_for_exit()`](codelab/src/codelab/server/tools/executors/terminal_executor.py) реализует корректный flow:

```mermaid
sequenceDiagram
    participant LLM
    participant Executor as TerminalToolExecutor
    participant Bridge as ClientRPCBridge
    participant Client

    LLM->>Executor: terminal/wait_for_exit(terminal_id)
    Executor->>Bridge: terminal_output(terminal_id)
    Bridge->>Client: terminal/output RPC
    Client-->>Bridge: output + exitStatus
    Bridge-->>Executor: output + is_complete + exit_code
    
    alt Terminal уже завершён (is_complete=True)
        Executor-->>LLM: ToolResult(output + exit_code)
    else Terminal ещё работает (is_complete=False)
        Executor->>Bridge: wait_terminal_exit(terminal_id)
        Bridge->>Client: terminal/wait_for_exit RPC
        Client-->>Bridge: exitCode + signal
        Bridge-->>Executor: exit_code + signal
        Executor->>Bridge: terminal_output(terminal_id)
        Bridge->>Client: terminal/output RPC
        Client-->>Bridge: финальный output
        Bridge-->>Executor: output + exitStatus
        Executor-->>LLM: ToolResult(output + exit_code + signal)
    end
```

**Ключевые изменения (2026-05-21):**
- `TerminalWaitForExitResponse` — только `exitCode` и `signal` (по spec)
- `TerminalOutputResponse` — `output`, `truncated`, `exitStatus` (по spec)
- `ClientRPCBridge.terminal_output()` — новый метод для получения output
- `ToolResult` передаёт `output` в LLM (исправлена потеря output)

### 5. PromptOrchestrator как центральный координатор

**Проблема:** Обработка prompt-turn включает множество этапов (валидация, LLM, tools, permissions, обновления).

**Решение:** [`PromptOrchestrator`](codelab/src/codelab/server/protocol/handlers/prompt_orchestrator.py) интегрирует все компоненты:

```python
class PromptOrchestrator:
    def __init__(
        self,
        state_manager: StateManager,
        plan_builder: PlanBuilder,
        turn_lifecycle_manager: TurnLifecycleManager,
        tool_call_handler: ToolCallHandler,
        permission_manager: PermissionManager,
        client_rpc_handler: ClientRPCHandler,
        tool_registry: ToolRegistry,
    ):
        # Все компоненты инжектированы
        self.state_manager = state_manager
        self.plan_builder = plan_builder
        # ...
```

**Координирует:**
1. Валидацию входных данных
2. Преобразование контекста для LLM
3. Вызов агента
4. Управление tool calls
5. Проверку разрешений
6. Обновление состояния сессии
7. Отправку events в историю

---

## Расширение и интеграция

### Добавление нового инструмента в codelab.server

1. **Определить инструмент** в `tools/definitions/`
2. **Реализовать executor** в `tools/executors/`
3. **Зарегистрировать** в `PromptOrchestrator`

Пример:

```python
from acp_server.tools.base import ToolDefinition, ToolExecutor

class MyToolDefinition(ToolDefinition):
    id = "my/tool"
    name = "My Tool"
    
    async def execute(self, input_schema: dict) -> dict:
        # Реализация
        pass

class MyToolExecutor(ToolExecutor):
    async def execute(self, name: str, arguments: dict) -> dict:
        # Выполнение
        pass

# В PromptOrchestrator.__init__():
tool_registry.register("my/tool", MyToolDefinition(), MyToolExecutor())
```

### Добавление нового обработчика в codelab.client

1. **Создать handler** в `infrastructure/handlers/`
2. **Зарегистрировать** в [`HandlerRegistry`](codelab/src/codelab/client/infrastructure/handler_registry.py)
3. **Добавить tests** в `tests/`

Пример:

```python
from acp_client.infrastructure.handler_registry import HandlerRegistry

class MyHandler:
    async def handle(self, request: dict) -> dict:
        # Обработка запроса
        pass

# Регистрация:
registry = HandlerRegistry()
registry.register("my/method", MyHandler())
```

### Интеграция нового LLM провайдера

1. **Наследовать** [`BaseLLMProvider`](codelab/src/codelab/server/llm/base.py)
2. **Реализовать** `async generate()` метод
3. **Зарегистрировать** в CLI флаге `--llm-provider`

Пример:

```python
from acp_server.llm.base import BaseLLMProvider, LLMMessage

class MyLLMProvider(BaseLLMProvider):
    async def generate(self, messages: list[LLMMessage]) -> str:
        # Вызов API
        response = await my_api.generate(messages)
        return response.text
```

---

## Документы проекта

### Справочная документация

- **[codelab/README.md](codelab/README.md)** — основная документация проекта
- **[doc/product/developer-guide/](doc/product/developer-guide/)** — руководство разработчика

### Специальные документы

- **[AGENTS.md](AGENTS.md)** — инструкции для агентных ассистентов
- **[doc/ACP_IMPLEMENTATION_STATUS.md](doc/ACP_IMPLEMENTATION_STATUS.md)** — матрица соответствия ACP спецификации
- **[doc/Agent Client Protocol/](doc/Agent Client Protocol/)** — официальная спецификация ACP (не менять!)

---

## Заключение

Архитектура Codelab разработана для:
- ✅ **Модульности** — каждый компонент отвечает за одно
- ✅ **Расширяемости** — добавление новых компонентов не требует изменений существующих
- ✅ **Тестируемости** — все слои имеют интерфейсы для mock-объектов
- ✅ **Производительности** — асинхронность, потоковые обновления, оптимальные структуры данных
- ✅ **Безопасности** — валидация, аутентификация, логирование всех операций
