# AGENTS

Инструкции для агентных ассистентов в этом репозитории.

## Контекст проекта

- Единый Python-проект `codelab/` объединяющий сервер и клиент ACP
- Менеджер окружения и запуск команд: `uv`
- Базовые проверки запускаются через `Makefile` из корня

## Рабочие правила

- Вносить минимальные и целевые изменения, не трогать лишние файлы.
- Не менять публичные интерфейсы CLI без явной необходимости.
- Сохранять совместимость с Python 3.12+.
- Следовать текущему стилю кода (типизация, простые функции, явные имена).
- Не добавлять зависимости без необходимости.
- Документацию вести на русском языке.
- Весь код должен иметь осмысленные комментарии.
- **Каждое изменение в коде должно быть покрыто тестом** (unit тесты, интеграционные тесты, как уместно).
- **Никогда не менять документацию в `doc/Agent Client Protocol/`** — это официальный протокол.
- **Никогда не нарушать протокол, описанный в `doc/Agent Client Protocol/`** — все изменения в коде должны соответствовать спецификации.

## Обязательная проверка после изменений

Из корня репозитория:

```bash
make check
```

Или локальная проверка в codelab:

```bash
cd codelab
uv run ruff check .
uv run ty check
uv run python -m pytest
```

## Где что находится

### Общие модули (`codelab/src/codelab/shared/`)
- `messages.py` — JSON-RPC сообщения (ACPMessage, JsonRpcError)
- `logging.py` — структурированное логирование
- `content/` — типы контента ACP (text, image, audio, embedded, resource_link)

### Сервер (`codelab/src/codelab/server/`)
- `protocol/` — модули протокола ACP:
  - `__init__.py` — экспорт публичных классов (ACPProtocol, ProtocolOutcome)
  - `core.py` — основной класс ACPProtocol (диспетчеризация методов)
  - `state.py` — dataclasses состояния (SessionState, ToolCallState, и т.д.)
  - `session_factory.py` — фабрика создания сессий
  - `handlers/` — обработчики методов протокола:
    - `auth.py` — методы аутентификации (authenticate, initialize)
    - `session.py` — управление сессиями (session/new, load, list)
    - `prompt.py` — обработка prompt-turn (session/prompt, cancel)
    - `prompt_orchestrator.py` — главный оркестратор prompt-turn
    - `permissions.py` — управление разрешениями (session/request_permission)
    - `permission_manager.py` — менеджер политик разрешений
    - `global_policy_manager.py` — глобальные политики разрешений
    - `config.py` — конфигурация сессий (session/set_config_option, session/set_mode)
    - `client_rpc_handler.py` — обработка RPC вызовов к клиенту
    - `tool_call_handler.py` — обработка tool calls
    - `plan_builder.py` — построение планов агента
    - `state_manager.py` — управление состоянием
    - `turn_lifecycle_manager.py` — управление жизненным циклом turn
  - `content/` — типы контента (ACP Content Types):
    - `base.py` — базовые классы
    - `text.py`, `image.py`, `audio.py` — типы контента
    - `embedded.py`, `resource_link.py` — ресурсы
    - `extractor.py`, `validator.py`, `formatter.py` — обработка контента
  - `prompt_handlers/` — обработчики директив промптов:
    - `directive_resolver.py` — разрешение директив
    - `validator.py` — валидация промптов
- `storage/` — хранилище сессий:
  - `base.py` — SessionStorage(ABC) интерфейс
  - `memory.py` — InMemoryStorage (development)
  - `json_file.py` — JsonFileStorage (production с persistence)
  - `global_policy_storage.py` — хранилище глобальных политик
- `client_rpc/` — RPC сервис для вызовов Agent → Client:
  - `service.py` — ClientRPCService
  - `models.py` — модели данных
  - `exceptions.py` — исключения
- `agent/` — LLM агенты:
  - `orchestrator.py` — AgentOrchestrator (управление LLM-агентом)
  - `naive.py` — NaiveAgent (базовая реализация)
  - `base.py` — базовые классы агентов
  - `state.py` — состояние агента
- `tools/` — инструменты агента:
  - `registry.py` — ToolRegistry (регистрация и управление инструментами)
  - `base.py` — базовые классы инструментов
  - `definitions/` — определения инструментов (filesystem.py, terminal.py)
  - `executors/` — исполнители инструментов (filesystem_executor.py, terminal_executor.py)
  - `integrations/` — интеграции (client_rpc_bridge.py, permission_checker.py)
- `llm/` — LLM провайдеры (OpenAI, Mock)
- `mcp/` — MCP интеграция
- `http_server.py` — WebSocket транспорт
- `web_app.py` — Web UI (Textual Web интеграция)
- `cli.py` — CLI команды сервера

### Клиент (`codelab/src/codelab/client/`)
Clean Architecture, 5 слоев:

- `domain/` — Domain Layer:
  - `entities.py` — сущности (Session, Message)
  - `repositories.py` — интерфейсы репозиториев
- `application/` — Application Layer:
  - Use Cases, DTOs, State Machine
- `infrastructure/` — Infrastructure Layer:
  - DI Container, Transport, Event Bus, Handlers (fs/*, terminal/*)
- `presentation/` — Presentation Layer:
  - ViewModels (MVVM), Observable
- `tui/` — TUI Layer:
  - Textual UI компоненты
  - `components/` — виджеты (chat_view, file_tree, prompt_input, etc.)
  - `navigation/` — менеджер навигации

### CLI (`codelab/src/codelab/cli.py`)
Единая точка входа:
- `codelab serve` — запуск сервера
- `codelab connect` — подключение TUI клиента

### Тесты (`codelab/tests/`)
- `client/` — тесты клиента (~1100 тестов)
- `server/` — тесты сервера (~700 тестов)

## Git-правила

- Не коммитить артефакты окружения и кэши (`.venv`, `__pycache__`, `.pytest_cache`, `.ruff_cache`).
- Один логический блок изменений = один коммит.
- Сообщение коммита: коротко и по сути (что и зачем).

## Документация

- При изменении поведения обновлять соответствующие README (`README.md`, `codelab/README.md`).
- Для сверки с протоколом использовать материалы в `doc/Agent Client Protocol/`.
- **Все диаграммы, схемы описывать с помощью Mermaid**.
- **При каждом изменении архитектуры необходимо обновлять документацию и диаграммы/графики/схемы** — архитектурная документация должна отражать текущее состояние системы.
