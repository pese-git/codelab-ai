# Permission Flow: Диаграммы последовательности

## 1. Текущее состояние (СЛОМАНО)

```mermaid
sequenceDiagram
    participant User
    participant Client
    participant HTTP as HTTP/WS
    participant ACPProto as ACPProtocol
    participant PromptOrch as PromptOrchestrator
    participant LLM

    User->>Client: Ввод "Прочти README.md"
    Client->>HTTP: session/prompt (539b9741)
    HTTP->>ACPProto: handle(request)
    ACPProto->>PromptOrch: handle_prompt()
    PromptOrch->>LLM: chat completion
    LLM-->>PromptOrch: tool_call (read_text_file)
    
    Note over PromptOrch: Проверка разрешений
    PromptOrch->>PromptOrch: decide_tool_execution()
    Note over PromptOrch: Нет политики -> ask user
    
    PromptOrch->>HTTP: session/request_permission (e1636f91)
    HTTP->>Client: session/request_permission
    
    Note over Client: UI: показать permission widget
    Client->>User: Показать опции
    
    User->>Client: Выбрать "allow_once"
    Client->>HTTP: {id: e1636f91, result: {outcome: selected, optionId: allow_once}}
    
    Note over HTTP: Получено сообщение
    HTTP->>ACPProto: handle(response)
    
    rect rgb(255, 0, 0)
        Note over ACPProto: ❌ ПРОБЛЕМА
        ACPProto->>ACPProto: if message.method is None: ERROR
        ACPProto-->>HTTP: Error response (-32600)
        Note over ACPProto: PromptOrchestrator не уведомлен
        Note over ACPProto: Tool call не выполняется
    end
    
    Note over PromptOrch: ❌ ОЖИДАЕТ ВЕЧНО
    Note over Client: ❌ НЕ ПОЛУЧАЕТ РЕЗУЛЬТАТ
```

---

## 2. Исправленное состояние (РАБОТАЕТ)

```mermaid
sequenceDiagram
    participant User
    participant Client
    participant HTTP as HTTP/WS
    participant ACPProto as ACPProtocol
    participant PromptOrch as PromptOrchestrator
    participant Executor as Tool Executor
    participant LLM

    User->>Client: Ввод "Прочти README.md"
    Client->>HTTP: session/prompt (539b9741)
    HTTP->>ACPProto: handle(request)
    ACPProto->>PromptOrch: handle_prompt()
    PromptOrch->>LLM: chat completion
    LLM-->>PromptOrch: tool_call (read_text_file)
    
    Note over PromptOrch: Проверка разрешений
    PromptOrch->>PromptOrch: decide_tool_execution()
    Note over PromptOrch: Нет политики -> ask user
    
    PromptOrch->>HTTP: session/request_permission (e1636f91)
    HTTP->>Client: session/request_permission
    
    Note over Client: UI: показать permission widget
    Client->>User: Показать опции
    
    User->>Client: Выбрать "allow_once"
    Client->>HTTP: {id: e1636f91, result: {outcome: selected, optionId: allow_once}}
    
    Note over HTTP: Получено сообщение
    HTTP->>ACPProto: handle(response)
    
    rect rgb(0, 255, 0)
        Note over ACPProto: ✅ ИСПРАВЛЕНИЕ
        ACPProto->>ACPProto: if message.method is None: response!
        ACPProto->>ACPProto: handle_incoming_response()
        ACPProto->>ACPProto: _resolve_permission_response()
        Note over ACPProto: ✅ Маршрутизация на обработчик
    end
    
    Note over ACPProto: Сессия найдена
    ACPProto->>ACPProto: resolve_permission_response_impl()
    
    alt allow_once
        Note over ACPProto: ✅ Разрешение получено
        ACPProto->>HTTP: tool_call_update (status: in_progress)
        HTTP->>Client: tool_call_update
        
        Note over PromptOrch: ✅ ВОЗОБНОВЛЕНИЕ EXECUTION
        PromptOrch->>Executor: execute_tool(read_text_file, path=README.md)
        Executor-->>PromptOrch: file content
        
        PromptOrch->>HTTP: tool_call_update (status: completed)
        HTTP->>Client: tool_call_update (с результатом)
        
        Note over PromptOrch: ✅ ПРОДОЛЖЕНИЕ TURN
        PromptOrch->>LLM: send_tool_result()
        LLM-->>PromptOrch: final response
        
        PromptOrch->>HTTP: session/update (agent_message_chunk)
        HTTP->>Client: agent_message_chunk (финальный ответ)
        
    else reject_once
        Note over ACPProto: ✅ Отклонено пользователем
        ACPProto->>HTTP: tool_call_update (status: failed)
        HTTP->>Client: tool_call_update
        PromptOrch->>PromptOrch: finalize_turn(cancelled)
        PromptOrch->>HTTP: session/update (cancelled)
        HTTP->>Client: cancelled
    end
    
    Client->>User: Показать результат
```

---

## 3. Поток обработки responses в ACPProtocol

```mermaid
graph TD
    A["HTTP получает сообщение<br/>{method: null, id: xxx, result: ...}"] --> B{"Что происходит?"}
    
    B -->|❌ ДО ИСПРАВЛЕНИЯ| C["ACPProtocol.handle()<br/>if message.method is None:<br/>return ERROR"]
    C --> D["❌ Ошибка -32600"]
    D --> E["❌ Обработка останавливается"]
    
    B -->|✅ ПОСЛЕ ИСПРАВЛЕНИЯ| F["ACPProtocol.handle()<br/>if message.method is None:<br/>return handle_incoming_response()"]
    F --> G["handle_incoming_response()"]
    
    G --> H{"Тип response?"}
    
    H -->|Client RPC Response| I["_resolve_pending_client_rpc_response()"]
    I --> J["Найти pending RPC request"]
    J --> K["Отправить результат в executor"]
    K --> L["✅ Client RPC обработан"]
    
    H -->|Permission Response| M["_resolve_permission_response()"]
    M --> N["Найти session<br/>по permission_request_id"]
    N --> O{"Сессия найдена?"}
    
    O -->|Да| P["resolve_permission_response_impl()"]
    P --> Q{"Outcome?"}
    
    Q -->|allow_once/allow_always| R["build_policy_tool_execution_updates<br/>allowed=True"]
    R --> S["Отправить notifications"]
    S --> T["✅ Tool call может выполняться"]
    
    Q -->|reject_once/reject_always| U["build_policy_tool_execution_updates<br/>allowed=False"]
    U --> V["Tool call отклонен"]
    V --> W["finalize_turn(cancelled)"]
    W --> X["✅ Turn завершен"]
    
    Q -->|cancelled| Y["Turn был отменен"]
    Y --> X
    
    O -->|Нет| Z["Late response на отмененный request"]
    Z --> AA["✅ No-op (ignore)"]
```

---

## 4. Tool execution resumption flow

```mermaid
sequenceDiagram
    participant PromptOrch as PromptOrchestrator<br/>handle_prompt()
    participant StateManager as StateManager
    participant ToolExec as Tool Executor
    participant Perm as PermissionManager
    
    Note over PromptOrch: Фаза 1: LLM обработка
    PromptOrch->>PromptOrch: get_llm_response()
    Note over PromptOrch: LLM вернул tool calls
    
    Note over PromptOrch: Фаза 2: Проверка разрешений
    PromptOrch->>Perm: check_tool_execution_permission()
    
    alt Permission policy в session
        Perm-->>PromptOrch: allow/reject (policy)
    else No policy
        Perm-->>PromptOrch: ask (требуется разрешение)
    end
    
    alt ask
        Note over PromptOrch: Фаза 2a: Запрос разрешения
        PromptOrch->>PromptOrch: request_permission()
        PromptOrch->>StateManager: save_permission_request_id()
        Note over PromptOrch: ❌ ОЖИДАНИЕ АСИНХРОННОГО RESPONSE
        Note over PromptOrch: (turn приостановлена)
        
        Note over PromptOrch: [В другом async context]
        Note over PromptOrch: Permission response получена
        PromptOrch->>PromptOrch: resume_from_permission()
        
        Note over PromptOrch: ✅ ПРОДОЛЖЕНИЕ�А Фаза 2b
    end
    
    Note over PromptOrch: Фаза 2c: Tool execution decision
    alt allowed (по политике или разрешению)
        Note over PromptOrch: Фаза 3a: Tool execution
        PromptOrch->>ToolExec: execute_tool_call()
        ToolExec->>ToolExec: run_tool()
        ToolExec-->>PromptOrch: tool result
        Note over PromptOrch: Результат получен
        
        Note over PromptOrch: Фаза 3b: Continue with LLM
        PromptOrch->>PromptOrch: send_tool_result_to_llm()
        Note over PromptOrch: Итерация цикла
        
    else rejected (по политике или разрешению)
        Note over PromptOrch: Фаза 3c: Tool rejected
        PromptOrch->>PromptOrch: finalize_tool_as_rejected()
        Note over PromptOrch: Turn завершена
    end
```

---

## 5. State transitions при permission response

```mermaid
stateDiagram-v2
    [*] --> PromptStarted
    
    PromptStarted --> LLMProcessing: get_llm_response()
    LLMProcessing --> ToolCallReceived: tool_calls returned
    
    ToolCallReceived --> PermissionCheckStart: check permission
    
    PermissionCheckStart --> PermissionPolicyFound: policy exists
    PermissionPolicyFound --> ToolExecuting: execute immediately
    
    PermissionCheckStart --> NoPermissionPolicy: no policy
    NoPermissionPolicy --> AwaitingPermission: request_permission()
    
    AwaitingPermission --> PermissionResponseReceived: response received
    PermissionResponseReceived --> PermissionDecision: extract outcome
    
    PermissionDecision --> PermissionAllowed: allowed_once/allow_always
    PermissionDecision --> PermissionRejected: reject_once/reject_always
    PermissionDecision --> PermissionCancelled: turn cancelled
    
    PermissionAllowed --> ToolExecuting: execute tool
    PermissionRejected --> TurnFinalized: finalize cancelled
    PermissionCancelled --> TurnFinalized: finalize cancelled
    
    ToolExecuting --> ToolCompleted: tool finished
    ToolCompleted --> LLMContinuation: send result to LLM
    LLMContinuation --> LLMProcessing: next iteration
    
    TurnFinalized --> [*]
    LLMProcessing --> TurnFinalized: LLM decided to stop
```

---

## 6. Диаграмма классов для permission flow

```mermaid
classDiagram
    class ACPProtocol {
        -_sessions: dict
        +handle(message: ACPMessage) ProtocolOutcome
        +handle_incoming_response(message: ACPMessage) ProtocolOutcome*
        -_resolve_permission_response(id, result) ProtocolOutcome
        -_handle_permission_response(id, params, sessions) ProtocolOutcome
    }
    
    class PromptOrchestrator {
        -state_manager: StateManager
        -permission_manager: PermissionManager
        +handle_prompt(...) ProtocolOutcome
        +handle_permission_response(...)
        -resume_tool_execution_after_permission()
    }
    
    class PermissionManager {
        +request_permission(tool_call_id, options) JsonRpcId
        +extract_permission_outcome(result) str
        +extract_permission_option_id(result) str
        +build_policy_tool_execution_updates(...) list
    }
    
    class StateManager {
        -active_turn: TurnState
        +save_permission_request_id(id)
        +get_permission_request_id() JsonRpcId
    }
    
    class TurnState {
        +permission_request_id: JsonRpcId
        +permission_tool_call_id: str
        +tool_calls: dict
    }
    
    class SessionState {
        +active_turn: TurnState
        +tool_calls: dict
        +permission_policy: dict
    }
    
    ACPProtocol --> PromptOrchestrator: delegates to
    PromptOrchestrator --> PermissionManager: uses
    PromptOrchestrator --> StateManager: manages
    StateManager --> TurnState: contains
    SessionState --> TurnState: has
```

---

## 7. Временная диаграмма обработки (timing)

```mermaid
timeline
    title Timing: Permission Flow от начала до конца
    
    12:30:17.517 : Client: prompt submitted
    12:30:17.517 : Client: sending_message (session/prompt)
    12:30:17.520 : Server: message received (prompt)
    12:30:17.520 : Server: active turn created
    12:30:17.520 : Server: openai create_completion request starting
    
    12:30:19.035 : Server: received openai api response (tool_calls)
    12:30:19.035 : Server: decision: ask user for permission
    12:30:19.036 : Server: permission request sent (e1636f91)
    12:30:19.037 : Server: notifications sent to client
    12:30:19.037 : Client: permission request received
    12:30:19.044 : Client: permission widget mounted
    
    12:30:19.044-12:30:21.202 : User: waiting (waiting for user choice)
    
    12:30:21.202 : Client: user selected allow_once
    12:30:21.202 : Client: permission choice received
    12:30:21.204 : Client: sending permission response (e1636f91)
    12:30:21.205 : Server: message received (permission response)
    
    rect rgb(255, 0, 0)
        12:30:21.205+ : ❌ LOGS STOPPED
    end
    
    rect rgb(0, 255, 0)
        12:30:21.205 : [AFTER FIX] response recognized
        12:30:21.205 : [AFTER FIX] handle_incoming_response()
        12:30:21.205 : [AFTER FIX] _resolve_permission_response()
        12:30:21.205 : [AFTER FIX] permission_response_impl()
        12:30:21.206 : [AFTER FIX] tool_call_update (running)
        12:30:21.206 : [AFTER FIX] tool execution starts
    end
    
    12:30:21.250 : [AFTER FIX] tool_call_update (completed)
    12:30:21.250 : [AFTER FIX] tool result sent to LLM
    12:30:21.250 : [AFTER FIX] LLM processing continues
    12:30:22.800 : [AFTER FIX] LLM response received
    12:30:22.801 : [AFTER FIX] agent_message_chunk sent
    12:30:22.801 : [AFTER FIX] turn finalized
    12:30:22.802 : Client: final response received
```

---

---

## 8. Execute Pending Tool Flow (исправление permission_request_id mismatch)

**Проблема:** После выполнения инструмента LLM loop мог вызвать ещё один tool, требующий permission. Новый `permission_request_id` записывался в in-memory session, но **не сохранялся** в storage. При ответе клиента `find_session_by_permission_request_id` читал storage и находил старый ID → mismatch → сессия не найдена → агент зависал.

```mermaid
sequenceDiagram
    participant Client as Клиент
    participant WS as WebSocket
    participant ACP as ACPProtocol
    participant PO as PromptOrchestrator
    participant LL as LLMLoopStage
    participant Storage[(SessionStorage)]
    participant TR as ToolRegistry
    participant LLM as LLM Provider

    Note over ACP,Storage: Фаза 1: Первый permission request
    ACP->>Storage: save_session (permission_request_id=AAA)
    ACP-->>Client: session/request_permission (id=AAA)
    Client->>ACP: response (id=AAA, allow_once)
    ACP->>ACP: _resolve_permission_response()
    Note over ACP: permission_request_id=AAA найден в storage ✓
    Note over ACP: pending_tool_execution → background task
    
    Note over ACP,Storage: Фаза 2: _execute_tool_in_background
    ACP->>PO: execute_pending_tool()
    PO->>Storage: load_session()
    PO->>LL: execute_pending_tool(session)
    LL->>TR: execute_tool(terminal/create)
    TR-->>LL: ToolExecutionResult
    LL->>LLM: continue_turn(tool_results)
    LLM-->>LL: tool_call (terminal/wait_for_exit)
    LL->>LL: execute_tool(wait_for_exit) — не требует permission
    LL->>LLM: continue_turn(tool_results)
    LLM-->>LL: tool_call (fs/write_text_file) — требует permission!
    LL->>LL: build_permission_request()
    Note over LL: active_turn.permission_request_id = BBB (НОВЫЙ)
    LL-->>PO: LLMLoopResult(pending_permission=True)
    PO-->>ACP: LLMLoopResult
    
    rect rgb(255, 255, 0)
        Note over ACP,Storage: ✅ ИСПРАВЛЕНИЕ: save_session ПЕРЕД возвратом
        ACP->>Storage: save_session(session)
        Note over Storage: permission_request_id=BBB сохранён
    end
    
    Note over ACP,Storage: Фаза 3: Второй permission response
    Client->>ACP: response (id=BBB, allow_once)
    ACP->>ACP: _resolve_permission_response()
    ACP->>Storage: find_session_by_permission_request_id(BBB)
    Storage-->>ACP: SessionState (permission_request_id=BBB) ✓
    Note over ACP: Сессия найдена! ✓
    ACP->>ACP: resolve_permission_response_impl()
    Note over ACP: pending_tool_execution → background task
    ACP->>PO: execute_pending_tool()
    PO->>LL: execute_pending_tool()
    LL->>TR: execute_tool(fs/write_text_file)
    TR-->>LL: ToolExecutionResult
    LL->>LLM: continue_turn(tool_results)
    LLM-->>LL: final response (end_turn)
    LL-->>PO: LLMLoopResult(stop_reason=end_turn)
    ACP->>Storage: save_session(session)
    ACP-->>Client: turn completion
```

### Ключевое изменение в `core.py`

**До (сломано):**
```python
async def execute_pending_tool(self, session_id, tool_call_id):
    session = await self._storage.load_session(session_id)
    orchestrator = await self._get_prompt_orchestrator()
    return await orchestrator.execute_pending_tool(session, ...)
    # ❌ Сессия НЕ сохранена — новый permission_request_id потерян
```

**После (исправлено):**
```python
async def execute_pending_tool(self, session_id, tool_call_id):
    session = await self._storage.load_session(session_id)
    orchestrator = await self._get_prompt_orchestrator()
    
    llm_result = await orchestrator.execute_pending_tool(session, ...)
    
    # ✅ Сохраняем сессию — LLM loop мог установить новый permission_request_id
    await self._storage.save_session(session)
    
    return llm_result
```

### Почему `load_session` в `_execute_tool_in_background` был ошибкой

Предыдущая попытка исправления делала `load_session()` в `_execute_tool_in_background`:

```python
# ❌ WRONG: load_session загружает СТАРУЮ копию из storage
session = await self._storage.load_session(session_id)
await self._storage.save_session(session)
```

Это перезаписывало in-memory изменения (новый `permission_request_id`) старой копией из storage. Правильное решение — сохранять сессию **внутри** `execute_pending_tool()`, где in-memory session содержит актуальные изменения.

---

## Заметки

1. **Критическое изменение**: Строка в `ACPProtocol.handle()` меняется с `return ERROR` на `return handle_incoming_response()`
2. **Cascade effect**: Это позволяет существующему коду обработать permission response
3. **No breaking changes**: Все остальное работает как раньше
4. **Tool execution resumption**: После разрешения, tool должен выполняться и результат отправляться в LLM
5. **Session persistence**: `execute_pending_tool()` сохраняет сессию после orchestrator вызова, чтобы новый `permission_request_id` был доступен в storage
