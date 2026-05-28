## 1. MCPConfigLoader Implementation

- [ ] 1.1 Создать файл `codelab/src/codelab/client/infrastructure/mcp_config_loader.py`
- [ ] 1.2 Реализовать функцию `expand_env_vars(value: str) -> str` для раскрытия `${VAR}` паттернов
- [ ] 1.3 Реализовать метод `_find_toml_chain() -> list[Path]` для поиска TOML файлов в порядке приоритета
- [ ] 1.4 Реализовать метод `_load_mcp_servers_from_toml(toml_path: Path) -> list[dict]` для парсинга `[[mcp.servers]]`
- [ ] 1.5 Реализовать метод `_merge_servers(existing: list[dict], new: list[dict]) -> list[dict]` с override по name
- [ ] 1.6 Реализовать метод `_validate_server(server: dict) -> bool` для валидации MCP сервера
- [ ] 1.7 Реализовать публичный метод `load_mcp_servers() -> list[dict[str, Any]]`
- [ ] 1.8 Добавить логирование через structlog для warning и debug сообщений

## 2. ClientConfig и DI Container

- [ ] 2.1 Добавить поле `mcp_servers: list[dict[str, Any]] = field(default_factory=list)` в `ClientConfig`
- [ ] 2.2 Добавить параметр `mcp_servers: list[dict[str, Any]] | None = None` в `create_client_container()`
- [ ] 2.3 Передать `mcp_servers` в `ClientConfig` при создании контейнера

## 3. Application Layer Updates

- [ ] 3.1 Добавить поле `mcp_servers: list[dict[str, Any]] | None = None` в `CreateSessionRequest`
- [ ] 3.2 Обновить `CreateSessionUseCase.execute()` для передачи `mcpServers` в `session/new`
- [ ] 3.3 Добавить параметр `mcp_servers` в `SessionCoordinator.create_session()`
- [ ] 3.4 Передать `mcp_servers` в `CreateSessionRequest` из `SessionCoordinator`

## 4. TUI App Integration

- [ ] 4.1 Импортировать `MCPConfigLoader` в `app.py`
- [ ] 4.2 Добавить `self._mcp_servers: list[dict[str, Any]]` в `__init__`
- [ ] 4.3 Загрузить MCP серверы в `on_mount()` или при инициализации
- [ ] 4.4 Логировать количество загруженных MCP серверов
- [ ] 4.5 Передать `mcp_servers` в `create_client_container()`
- [ ] 4.6 Обновить `_load_selected_session_history()` для использования `self._mcp_servers` вместо `[]`
- [ ] 4.7 Обновить создание новой сессии для передачи `mcp_servers`

## 5. Documentation

- [ ] 5.1 Добавить секцию `[[mcp.servers]]` примеры в `codelab/codelab.toml.example`
- [ ] 5.2 Добавить комментарии о безопасности (не хранить API keys в TOML)
- [ ] 5.3 Обновить README клиента если необходимо

## 6. Tests

- [ ] 6.1 Создать файл `codelab/tests/client/infrastructure/test_mcp_config_loader.py`
- [ ] 6.2 Тест: загрузка MCP серверов из одного TOML файла
- [ ] 6.3 Тест: env var expansion во всех строковых полях
- [ ] 6.4 Тест: TOML chain merge с override по name
- [ ] 6.5 Тест: валидация — пропуск сервера без name
- [ ] 6.6 Тест: валидация — пропуск stdio сервера без command
- [ ] 6.7 Тест: валидация — пропуск http сервера без url
- [ ] 6.8 Тест: пустой список при отсутствии MCP секции
- [ ] 6.9 Тест: отсутствующая переменная окружения заменяется на пустую строку
- [ ] 6.10 Обновить тесты `CreateSessionUseCase` для проверки передачи `mcpServers`
- [ ] 6.11 Обновить тесты `SessionCoordinator.create_session()` для параметра `mcp_servers`
- [ ] 6.12 Обновить тесты `LoadSessionUseCase` если необходимо

## 7. Verification

- [ ] 7.1 Запустить `uv run ruff check .` — без ошибок
- [ ] 7.2 Запустить `uv run ty check` — без ошибок типизации
- [ ] 7.3 Запустить `uv run python -m pytest` — все тесты проходят
- [ ] 7.4 Ручная проверка: создать `codelab.toml` с MCP серверами, запустить клиент, проверить что серверы передаются
