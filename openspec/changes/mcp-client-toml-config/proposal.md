## Why

Клиент ACP не загружает конфигурацию MCP серверов из TOML файлов (`codelab.toml`, `codelab.local.toml`), хотя протокол ACP поддерживает параметр `mcpServers` в методах `session/new` и `session/load`. В результате пользователи вынуждены указывать MCP серверы программно или через другие механизмы, хотя серверная часть уже поддерживает MCP интеграцию per-session.

Это изменение позволит клиентам автоматически загружать MCP конфигурацию из TOML файлов и передавать её серверу при создании/загрузке сессии, обеспечивая единообразный опыт конфигурации.

## What Changes

- Клиент получает новый компонент `MCPConfigLoader` для чтения `[[mcp.servers]]` из TOML файлов
- `ClientConfig` расширяется полем `mcp_servers` для передачи конфигурации через DI контейнер
- `CreateSessionRequest` и `CreateSessionUseCase` поддерживают передачу `mcpServers` в `session/new`
- TUI App загружает MCP конфигурацию при старте и передаёт в `SessionCoordinator`
- Обновляется пример конфигурации `codelab.toml.example` с секцией MCP серверов

## Capabilities

### New Capabilities
- `mcp-client-toml-config`: Клиент загружает MCP серверы из TOML конфигурации и передаёт серверу через ACP протокол при создании/загрузке сессии

### Modified Capabilities
- `codelab`: Раздел 19 (MCP интеграция) — добавляется требование загрузки MCP конфигурации из TOML на стороне клиента перед вызовом `session/new`/`session/load`

## Impact

**Затронутые файлы:**
- `codelab/src/codelab/client/infrastructure/mcp_config_loader.py` (новый)
- `codelab/src/codelab/client/infrastructure/client_config.py`
- `codelab/src/codelab/client/infrastructure/container_factory.py`
- `codelab/src/codelab/client/application/dto.py`
- `codelab/src/codelab/client/application/use_cases.py`
- `codelab/src/codelab/client/application/session_coordinator.py`
- `codelab/src/codelab/client/tui/app.py`
- `codelab/codelab.toml.example`

**Тесты:**
- `codelab/tests/client/infrastructure/test_mcp_config_loader.py` (новый)
- Обновление существующих тестов DTO, UseCase, SessionCoordinator

**Зависимости:**
- Не добавляет новых внешних зависимостей
- Использует стандартный `tomllib` (Python 3.11+)

**Breaking Changes:** Нет
