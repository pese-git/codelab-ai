# План: SessionRuntimeRegistry

## Проблема

`SessionState` смешивает persisted данные (сериализуются в storage) и runtime объекты (in-memory). Поле `mcp_manager` имеет `Field(exclude=True)` — теряется при `load_session`. При `session/prompt` загружается сессия без MCP.

## Решение

Создать `SessionRuntimeRegistry` — REQUEST-scoped реестр runtime-состояний сессий. Разделить persisted (`SessionState`) и runtime (`SessionRuntimeState`) данные.

## Архитектурные решения

| Решение | Обоснование |
|---------|-------------|
| REQUEST-scoped registry | Живет в рамках одного WebSocket соединения; automatic cleanup при disconnect |
| one-session-one-client | MVP, нет collaboration сценариев |
| `mcp_manager` удалить из `SessionState` полностью | Чистое разделение, нет deprecated полей |
| `asyncio.Lock` для registry | Concurrent access из разных корутин |
| `shutdown()` при `remove()` | Предотвращение zombie subprocesses |
| Dishka generator для cleanup | `yield registry` → `await cleanup()` при exit из REQUEST scope |

---

## Файлы для создания

### 1. `codelab/src/codelab/server/protocol/session_runtime.py`

```python
"""Реестр runtime-состояний сессий.

Хранит in-memory объекты (MCP manager, кэши) отдельно от
сериализуемого SessionState. REQUEST-scoped, живет в рамках
одного WebSocket соединения. Dishka cleanup при disconnect.
"""

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..mcp.manager import MCPManager


@dataclass
class SessionRuntimeState:
    """Runtime-состояние одной сессии (не сериализуется)."""
    mcp_manager: "MCPManager | None" = None


class SessionRuntimeRegistry:
    """Реестр runtime-состояний сессий.

    Thread-safe через asyncio.Lock. REQUEST-scoped.
    Cleanup через dishka generator при exit из REQUEST scope.
    """

    def __init__(self) -> None:
        self._states: dict[str, SessionRuntimeState] = {}
        self._lock = asyncio.Lock()

    async def get(self, session_id: str) -> SessionRuntimeState | None:
        """Получить runtime state сессии или None."""
        async with self._lock:
            return self._states.get(session_id)

    async def get_or_create(self, session_id: str) -> SessionRuntimeState:
        """Получить или создать runtime state сессии."""
        async with self._lock:
            if session_id not in self._states:
                self._states[session_id] = SessionRuntimeState()
            return self._states[session_id]

    async def set_mcp_manager(
        self, session_id: str, mcp_manager: "MCPManager"
    ) -> None:
        """Установить MCP manager для сессии."""
        async with self._lock:
            if session_id not in self._states:
                self._states[session_id] = SessionRuntimeState()
            self._states[session_id].mcp_manager = mcp_manager

    async def remove(self, session_id: str) -> None:
        """Удалить runtime state с cleanup MCP subprocesses."""
        async with self._lock:
            state = self._states.pop(session_id, None)
        if state and state.mcp_manager:
            await state.mcp_manager.shutdown()

    async def cleanup(self) -> None:
        """Shutdown всех MCP managers при выходе из REQUEST scope.

        Вызывается автоматически dishka через generator cleanup.
        """
        async with self._lock:
            states = list(self._states.values())
            self._states.clear()
        for state in states:
            if state.mcp_manager:
                await state.mcp_manager.shutdown()
```

---

## Файлы для изменения

### 2. `codelab/src/codelab/server/protocol/__init__.py`

**Изменение:** Добавить экспорт новых классов.

```python
# Добавить к существующим экспортам:
from .session_runtime import SessionRuntimeRegistry, SessionRuntimeState

__all__ = [
    # ... существующие ...
    "SessionRuntimeRegistry",
    "SessionRuntimeState",
]
```

### 3. `codelab/src/codelab/server/protocol/core.py`

**Изменения:**

#### 3.1. Конструктор `ACPProtocol` (line ~66)

Добавить параметр `runtime_registry: SessionRuntimeRegistry`:

```python
def __init__(
    self,
    storage: SessionStorage,
    agent_orchestrator: AgentOrchestrator,
    client_rpc_service: ClientRPCService,
    tool_registry: ToolRegistry | None = None,
    prompt_orchestrator: PromptOrchestrator | None = None,
    global_policy_manager: GlobalPolicyManager | None = None,
    middleware: list[MiddlewareFn] | None = None,
    send_callback: Callable | None = None,
    llm_registry: LLMProviderRegistry | None = None,
    config_option_builder: ConfigOptionBuilder | None = None,
    runtime_registry: SessionRuntimeRegistry | None = None,  # NEW
) -> None:
```

Сохранить как поле:
```python
self._runtime_registry = runtime_registry or SessionRuntimeRegistry()
```

#### 3.2. `_initialize_mcp_servers()` (line ~1167-1250)

**Было:**
```python
mcp_manager = MCPManager(session_state.session_id)
session_state.mcp_manager = mcp_manager
```

**Стало:**
```python
mcp_manager = MCPManager(session_state.session_id)
await self._runtime_registry.set_mcp_manager(
    session_state.session_id, mcp_manager
)
```

#### 3.3. `_setup_mcp_if_needed()` (line ~978-989)

Добавить проверку registry перед инициализацией:

```python
async def _setup_mcp_if_needed(self, session_state: SessionState) -> None:
    """Инициализировать MCP серверы если указаны в сессии."""
    if not session_state.mcp_servers:
        return

    # Проверить есть ли уже MCP в registry
    runtime = await self._runtime_registry.get(session_state.session_id)
    if runtime and runtime.mcp_manager is not None:
        return  # Уже инициализирован

    await self._initialize_mcp_servers(session_state)
```

#### 3.4. `_handle_session_prompt()` (line ~827-854)

Получить `mcp_manager` из registry и передать в `handle_prompt`:

```python
async def _handle_session_prompt(self, ...):
    # ... existing code ...
    mcp_manager = None
    runtime = await self._runtime_registry.get(session_state.session_id)
    if runtime:
        mcp_manager = runtime.mcp_manager

    outcome = await orchestrator.handle_prompt(
        request_id=message.id,
        params=message.params or {},
        session=session_state,
        storage=self._storage,
        agent_orchestrator=self._agent_orchestrator,
        mcp_manager=mcp_manager,  # NEW
    )
```

#### 3.5. Другие места вызова `handle_prompt` / `execute_pending_tool`

Аналогично — получить `mcp_manager` из registry и передать:
- `handle_pending_tool_execution()` (line ~1151)
- `handle_permission_response()` (line ~878)

### 4. `codelab/src/codelab/server/protocol/handlers/prompt_orchestrator.py`

**Изменения:** Добавить параметр `mcp_manager` в `handle_prompt()` и передать в `context.meta`.

#### 4.1. `handle_prompt()` (line ~126-182)

Добавить параметр:

```python
async def handle_prompt(
    self,
    request_id: JsonRpcId | None,
    params: dict[str, Any],
    session: SessionState,
    storage: SessionStorage,
    agent_orchestrator: AgentOrchestrator,
    mcp_manager: MCPManager | None = None,  # NEW
) -> ProtocolOutcome:
```

Передать в context:

```python
context = PromptContext(
    session_id=session_id,
    session=session,
    request_id=request_id,
    params=params,
    raw_text=prompt_text,
)
context.meta["agent_orchestrator"] = agent_orchestrator
context.meta["mcp_manager"] = mcp_manager  # NEW
```

#### 4.2. `execute_pending_tool()` и `handle_permission_response()`

Аналогично — добавить параметр `mcp_manager` и передать в `context.meta` или напрямую в `llm_loop_stage`.

### 5. `codelab/src/codelab/server/protocol/state.py`

**Изменение:** Удалить поле `mcp_manager` из `SessionState` (line 86).

**Было:**
```python
mcp_manager: "MCPManager | None" = Field(default=None, exclude=True)
```

**Стало:**
```python
# mcp_manager перенесен в SessionRuntimeRegistry
```

Удалить импорт `TYPE_CHECKING` для `MCPManager` если больше не нужен.

### 6. `codelab/src/codelab/server/agent/orchestrator.py`

**Изменения:** НЕ добавлять `runtime_registry` как зависимость (APP-scoped не может зависеть от REQUEST-scoped). Вместо этого sync методы принимают `mcp_manager` как параметр — `ACPProtocol` (REQUEST-scoped) получает его из registry и передает.

#### 5.1. Конструктор — БЕЗ изменений

#### 5.2. `process_prompt()` (line ~142-203)

Добавить параметр `mcp_manager`:

```python
async def process_prompt(
    self, session_state: SessionState, prompt: str,
    mcp_manager: MCPManager | None = None,  # NEW
) -> AgentResponse:
    # ... existing code ...
    context = AgentContext(
        session_id=session_state.session_id,
        session=session_state,
        prompt=[{"type": "text", "text": prompt}],
        conversation_history=self._build_history(session_state, mcp_manager),
        available_tools=self._filter_tools(session_state, mcp_manager),
        config=session_state.config_values,
        model=model_ref,
    )
```

#### 5.3. `continue_with_tool_results()` (line ~205-249)

Аналогично — добавить параметр `mcp_manager: MCPManager | None = None`.

#### 5.4. `_build_system_message()` (line ~272-305)

**Было:**
```python
def _build_system_message(self, session_state: SessionState) -> str:
    mcp_manager = session_state.mcp_manager
    has_mcp = mcp_manager is not None
    mcp_count = mcp_manager.server_count if has_mcp else 0
```

**Стало:**
```python
def _build_system_message(
    self, session_state: SessionState, mcp_manager: MCPManager | None = None
) -> str:
    has_mcp = mcp_manager is not None
    mcp_count = mcp_manager.server_count if has_mcp else 0
```

#### 5.5. `_build_history()` (line ~338-367)

Обновить сигнатуру и передать `mcp_manager` в `_build_system_message`:

```python
def _build_history(
    self, session_state: SessionState, mcp_manager: MCPManager | None = None
) -> list[LLMMessage]:
    # ...
    system_msg = self._build_system_message(session_state, mcp_manager)
```

#### 5.6. `_filter_tools()` (line ~369-389)

**Было:**
```python
def _filter_tools(self, session_state: SessionState) -> list[ToolDefinition]:
    # ...
    if session_state.mcp_manager is not None:
        mcp_tools = session_state.mcp_manager.get_all_tools()
        filtered.extend(mcp_tools)
```

**Стало:**
```python
def _filter_tools(
    self, session_state: SessionState, mcp_manager: MCPManager | None = None
) -> list[ToolDefinition]:
    all_tools = self.tool_registry.get_available_tools(session_state.session_id)
    filtered = self._filter_tools_by_capabilities(
        all_tools, session_state.runtime_capabilities
    )

    if mcp_manager is not None:
        mcp_tools = mcp_manager.get_all_tools()
        filtered.extend(mcp_tools)

    return filtered
```

### 7. `codelab/src/codelab/server/protocol/handlers/pipeline/stages/llm_loop.py`

**Изменения:** `LLMLoopStage` остается APP-scoped, НЕ зависит от registry. Получает `mcp_manager` через `PromptContext.meta`.

#### 6.1. Конструктор `LLMLoopStage` — БЕЗ изменений

#### 6.2. Helper-метод для получения MCP manager

Добавить приватный метод который читает из context:

```python
def _get_mcp_manager(self, context: PromptContext):
    """Получить MCP manager из PromptContext.meta."""
    return context.meta.get("mcp_manager")
```

#### 6.3. `process()` (line ~59-100)

Передать `mcp_manager` в `run_loop`:

```python
async def process(self, context: PromptContext) -> PromptContext:
    mcp_manager = self._get_mcp_manager(context)
    # ... existing code ...
    result = await self.run_loop(
        session=context.session,
        session_id=context.session_id,
        agent_orchestrator=agent_orchestrator,
        initial_prompt_text=context.raw_text,
        mcp_manager=mcp_manager,  # NEW
    )
```

#### 6.4. `run_loop()` и `_run_llm_loop()`

Добавить параметр `mcp_manager: MCPManager | None = None` и передать в `_process_tool_calls_for_llm_loop`.

#### 6.5. `execute_pending_tool()` (line ~119-277)

Добавить параметр `mcp_manager` и использовать его:

```python
async def execute_pending_tool(
    self, session, session_id, tool_call_id, agent_orchestrator,
    mcp_manager: MCPManager | None = None,  # NEW
) -> LLMLoopResult:
    # ...
    if MCPToolExecutor.is_mcp_tool(tool_name):
        if mcp_manager is None:
            raise RuntimeError("MCP manager not available for session")
        mcp_executor = MCPToolExecutor(mcp_manager)
```

#### 6.6. `_process_tool_calls_for_llm_loop()` (line ~508-515)

Добавить параметр `mcp_manager` и использовать:

```python
async def _process_tool_calls_for_llm_loop(
    self, session, session_id, tool_calls, mcp_manager: MCPManager | None = None
):
    # ...
    if is_mcp:
        if mcp_manager is None:
            raise RuntimeError("MCP manager not available for session")
        mcp_executor = MCPToolExecutor(mcp_manager)
```

### 8. `codelab/src/codelab/server/tools/executors/mcp_executor.py`

**Изменения:** `execute()` должен использовать `self._mcp_manager` (уже передан в конструктор) вместо `session.mcp_manager`.

**Было (line 87-92):**
```python
mcp_manager = session.mcp_manager
if mcp_manager is None:
    return ToolExecutionResult(
        success=False,
        error=f"MCP manager not available for session {session.session_id}",
    )
```

**Стало:**
```python
if self._mcp_manager is None:
    session_id = session.session_id if session else "unknown"
    return ToolExecutionResult(
        success=False,
        error=f"MCP manager not available for session {session_id}",
    )
```

**И callers в `llm_loop.py`** получают `mcp_manager` из context и передают в конструктор:
```python
mcp_executor = MCPToolExecutor(mcp_manager)
```

**Не требуется:** менять конструктор `MCPToolExecutor` — он уже принимает `mcp_manager`.

### 9. `codelab/src/codelab/server/di.py`

**Изменения:** Создать новый провайдер, обновить только `RequestProvider`.

#### 8.1. Новый провайдер `RuntimeRegistryProvider`

Добавить новый класс провайдера (после `ToolsProvider`):

```python
class RuntimeRegistryProvider(Provider):
    """Провайдер SessionRuntimeRegistry (REQUEST scope)."""

    @provide(scope=Scope.REQUEST)
    async def get_runtime_registry(self) -> AsyncIterator[SessionRuntimeRegistry]:
        """Реестр runtime-состояний сессий.

        Dishka автоматически вызовет cleanup() при выходе из REQUEST scope.
        """
        registry = SessionRuntimeRegistry()
        yield registry
        await registry.cleanup()
```

#### 8.2. `AgentProvider.get_agent_orchestrator` — БЕЗ изменений

`AgentOrchestrator` остается APP-scoped, НЕ зависит от registry.

#### 8.3. `PipelineProvider.get_llm_loop_stage` — БЕЗ изменений

`LLMLoopStage` остается APP-scoped, НЕ зависит от registry.

#### 8.4. Обновить `RequestProvider.get_acp_protocol` (line 382-421)

Добавить параметр `runtime_registry`:

```python
@provide(scope=Scope.REQUEST)
def get_acp_protocol(
    self,
    require_auth: Annotated[bool, from_context(provides=bool)],
    auth_api_key: Annotated[str | None, from_context(provides=str | None)],
    storage: SessionStorage,
    agent_orchestrator: AgentOrchestrator,
    tool_registry: ToolRegistryProtocol,
    prompt_orchestrator: PromptOrchestrator,
    holder: ClientRPCServiceHolder,
    registry: LLMProviderRegistry,
    config_option_builder: ConfigOptionBuilder,
    runtime_registry: SessionRuntimeRegistry,  # NEW (REQUEST-scoped)
    trace_messages: Annotated[bool, from_context(provides="trace_messages")],
) -> ACPProtocol:
```

Передать в конструктор:
```python
return ACPProtocol(
    require_auth=require_auth,
    auth_api_key=auth_api_key,
    storage=storage,
    agent_orchestrator=agent_orchestrator,
    client_rpc_service=client_rpc_service,
    tool_registry=tool_registry,
    prompt_orchestrator=prompt_orchestrator,
    llm_registry=registry,
    config_option_builder=config_option_builder,
    middleware=middleware if middleware else None,
    runtime_registry=runtime_registry,  # NEW
)
```

#### 8.5. Обновить `make_container` (line 444-462)

Добавить `RuntimeRegistryProvider()` в список провайдеров:

```python
container = make_async_container(
    ManagersProvider(),
    SlashCommandsProvider(),
    StorageProvider(),
    RegistryProvider(),
    LLMProvider_(),
    ToolsProvider(),
    RuntimeRegistryProvider(),  # NEW
    AgentProvider(),
    PipelineProvider(),
    PromptOrchestratorProvider(),
    RequestProvider(),
    context={...},
)
```

#### 8.6. Добавить импорт

В начало файла:
```python
from collections.abc import AsyncIterator
from .protocol.session_runtime import SessionRuntimeRegistry
```

---

## Тесты

### 10. `tests/server/protocol/test_session_runtime.py`

```python
"""Тесты SessionRuntimeRegistry."""

import pytest
from codelab.server.protocol.session_runtime import (
    SessionRuntimeRegistry,
    SessionRuntimeState,
)


class TestSessionRuntimeRegistry:
    """Тесты lifecycle registry."""

    @pytest.mark.asyncio
    async def test_get_or_create(self):
        registry = SessionRuntimeRegistry()
        state = await registry.get_or_create("sess_1")
        assert state is not None
        assert state.mcp_manager is None

    @pytest.mark.asyncio
    async def test_get_nonexistent(self):
        registry = SessionRuntimeRegistry()
        state = await registry.get("sess_nonexistent")
        assert state is None

    @pytest.mark.asyncio
    async def test_set_mcp_manager(self):
        registry = SessionRuntimeRegistry()
        mock_manager = MockMCPManager()
        await registry.set_mcp_manager("sess_1", mock_manager)
        state = await registry.get("sess_1")
        assert state.mcp_manager is mock_manager

    @pytest.mark.asyncio
    async def test_remove_calls_shutdown(self):
        registry = SessionRuntimeRegistry()
        mock_manager = MockMCPManager()
        await registry.set_mcp_manager("sess_1", mock_manager)
        await registry.remove("sess_1")
        mock_manager.shutdown.assert_called_once()
        state = await registry.get("sess_1")
        assert state is None

    @pytest.mark.asyncio
    async def test_cleanup_all(self):
        registry = SessionRuntimeRegistry()
        mock_manager1 = MockMCPManager()
        mock_manager2 = MockMCPManager()
        await registry.set_mcp_manager("sess_1", mock_manager1)
        await registry.set_mcp_manager("sess_2", mock_manager2)
        await registry.cleanup()
        mock_manager1.shutdown.assert_called_once()
        mock_manager2.shutdown.assert_called_once()
        state = await registry.get("sess_1")
        assert state is None

    @pytest.mark.asyncio
    async def test_concurrent_access(self):
        """Тест concurrent get_or_create."""
        registry = SessionRuntimeRegistry()
        tasks = [
            registry.get_or_create("sess_1")
            for _ in range(10)
        ]
        results = await asyncio.gather(*tasks)
        # Все должны вернуть один и тот же объект
        assert all(r is results[0] for r in results)
```

### 11. Обновить существующие тесты

Найти и обновить тесты которые используют `session.mcp_manager`:
- `tests/server/agent/test_orchestrator.py`
- `tests/server/protocol/handlers/pipeline/stages/test_llm_loop.py`
- `tests/server/tools/executors/test_mcp_executor.py`

---

## Порядок выполнения

1. Создать `session_runtime.py` (`SessionRuntimeState`, `SessionRuntimeRegistry`)
2. Обновить `state.py` (удалить поле `mcp_manager`)
3. Обновить `__init__.py` (экспорты)
4. Обновить `di.py` (новый `RuntimeRegistryProvider` с REQUEST scope + generator cleanup, обновить `RequestProvider`)
5. Обновить `core.py` (конструктор, `_initialize_mcp_servers`, `_setup_mcp_if_needed`, передача `mcp_manager` в `handle_prompt`)
6. Обновить `prompt_orchestrator.py` (`handle_prompt` принимает `mcp_manager`, кладет в `context.meta`)
7. Обновить `orchestrator.py` (sync методы принимают `mcp_manager` параметром, async методы добавляют параметр)
8. Обновить `llm_loop.py` (helper `_get_mcp_manager` из context, async методы добавляют параметр `mcp_manager`)
9. Обновить `mcp_executor.py` (`execute()` использует `self._mcp_manager`)
10. Создать `tests/server/protocol/test_session_runtime.py`
11. Обновить существующие тесты
12. Запустить `make check`

---

## Риски и митигация

| Риск | Митигация |
|------|-----------|
| Race condition при concurrent access | `asyncio.Lock` на все операции |
| Zombie MCP subprocesses | Dishka generator cleanup при exit из REQUEST scope |
| Breaking changes в тестах | Обновить все тесты которые мокают `session.mcp_manager` |
| DI scope mismatch | Registry REQUEST-scoped, APP-scoped компоненты НЕ зависят от него напрямую |
| Sync методы не могут await registry | `mcp_manager` передается параметром из REQUEST-scoped caller |
| Deadlock в `set_mcp_manager` | Inline логика вместо вызова `get_or_create` |
