# Архитектура ACP Protocol — Детальное руководство

## Оглавление

1. [Введение](#введение)
2. [Обзор системы](#обзор-системы)
3. [Архитектура на уровне компонентов](#архитектура-на-уровне-компонентов)
4. [Потоки данных](#потоки-данных)
5. [Двухуровневая история в codelab.server](#двухуровневая-история)
6. [Background Receive Loop в codelab.client](#background-receive-loop)
7. [Критические архитектурные решения](#критические-архитектурные-решения)
8. [Расширение и интеграция](#расширение-и-интеграция)

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
        HttpServer["🌐 HTTP/WebSocket Server<br/>JSON-RPC Transport"]
        Protocol["🔄 Protocol Layer<br/>ACPProtocol + Handlers"]
        Agent["🤖 Agent Layer<br/>LLM Orchestration"]
        Tools["🛠️ Tools Layer<br/>Executors + Registry"]
        Storage["💾 Storage Layer<br/>SessionStorage Backends"]
    end
    
    WebSocket["WebSocket<br/>Connection"]
    
    TUI --> Presentation
    Presentation --> Application
    Application --> Infrastructure
    Infrastructure --> Domain
    Infrastructure --> WebSocket
    
    WebSocket --> HttpServer
    HttpServer --> Protocol
    Protocol --> Agent
    Protocol --> Tools
    Protocol --> Storage
    Agent --> Tools
    
    style Client fill:#e1f5ff,stroke:#01579b,stroke-width:2px
    style Server fill:#f3e5f5,stroke:#4a148c,stroke-width:2px
    style WebSocket fill:#fff3e0,stroke:#e65100,stroke-width:2px
```

### Таблица компонентов

| Компонент | Слой | Ответственность | Файлы |
|-----------|------|-----------------|-------|
| **TUI** | Presentation | Textual компоненты, User Interaction | `codelab/src/codelab/client/tui/` |
| **ViewModels** | Presentation | MVVM паттерн, Observable state | `codelab/src/codelab/client/presentation/` |
| **Use Cases** | Application | Business scenarios, DTOs | `codelab/src/codelab/client/application/` |
| **DIContainer** | Infrastructure | Dependency Injection | [`codelab/src/codelab/client/infrastructure/di_container.py`](codelab/src/codelab/client/infrastructure/di_container.py:33) |
| **BackgroundReceiveLoop** | Infrastructure | Единственный receive() на WebSocket | [`codelab/src/codelab/client/infrastructure/services/background_receive_loop.py`](codelab/src/codelab/client/infrastructure/services/background_receive_loop.py:22) |
| **MessageRouter** | Infrastructure | Маршрутизация сообщений | [`codelab/src/codelab/client/infrastructure/services/message_router.py`](codelab/src/codelab/client/infrastructure/services/message_router.py:26) |
| **EventBus** | Infrastructure | Pub/Sub система событий | [`codelab/src/codelab/client/infrastructure/events/bus.py`](codelab/src/codelab/client/infrastructure/events/bus.py) |
| **ACPProtocol** | Protocol | Диспетчер методов ACP | [`codelab/src/codelab/server/protocol/core.py`](codelab/src/codelab/server/protocol/core.py:39) |
| **Handlers** | Protocol | Обработчики методов (auth, session, prompt) | [`codelab/src/codelab/server/protocol/handlers/`](codelab/src/codelab/server/protocol/handlers/) |
| **PromptOrchestrator** | Protocol | Главный оркестратор prompt-turn | [`codelab/src/codelab/server/protocol/handlers/prompt_orchestrator.py`](codelab/src/codelab/server/protocol/handlers/prompt_orchestrator.py:32) |
| **AgentOrchestrator** | Agent | Управление LLM-агентом | [`codelab/src/codelab/server/agent/orchestrator.py`](codelab/src/codelab/server/agent/orchestrator.py:18) |
| **ToolRegistry** | Tools | Регистрация и управление инструментами | [`codelab/src/codelab/server/tools/registry.py`](codelab/src/codelab/server/tools/registry.py) |
| **Storage** | Storage | Persistence для сессий | [`codelab/src/codelab/server/storage/`](codelab/src/codelab/server/storage/) |
| **HttpServer** | Transport | WebSocket endpoint и JSON-RPC | [`codelab/src/codelab/server/http_server.py`](codelab/src/codelab/server/http_server.py) |

---

## Архитектура на уровне компонентов

### codelab-server: Внутренняя структура

```mermaid
graph LR
    subgraph Transport["Transport"]
        WS["WebSocket<br/>Endpoint"]
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
    
    WS --> Core
    Core --> Handlers
    Handlers --> PromptOrch
    PromptOrch --> Agent
    PromptOrch --> ToolReg
    ToolReg --> Executors
    Executors --> ClientRPCService
    ClientRPCService --> WS
    
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
        Transport["Transport Service<br/>WebSocket"]
        BgLoop["BackgroundReceiveLoop<br/>Единственный receive()"]
        Router["MessageRouter<br/>Маршрутизация"]
        Queues["RoutingQueues<br/>Распределение"]
        EventBus["EventBus<br/>Pub/Sub система"]
        DI["DIContainer<br/>Dependency Injection"]
        
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

### 2. Фильтрация инструментов по ClientRuntimeCapabilities

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

### 3. ClientRPCService для асинхронных вызовов

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

### 4. PromptOrchestrator как центральный координатор

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
