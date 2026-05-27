## ADDED Requirements

### Requirement: MCP Prompts — list
Агент SHALL поддерживать метод MCP `prompts/list` для получения списка доступных промптов от MCP сервера.

#### Scenario: Получение списка промптов
- **WHEN** агент вызывает `prompts/list` у MCP сервера
- **THEN** сервер возвращает список промптов с `name`, `description`, `arguments`

#### Scenario: Кэширование списка промптов
- **WHEN** агент получает список промптов от MCP сервера
- **THEN** агент кэширует промпты для использования в session setup

### Requirement: MCP Prompts — get
Агент SHALL поддерживать метод MCP `prompts/get` для получения конкретного промпта с аргументами.

#### Scenario: Получение промпта с аргументами
- **WHEN** агент вызывает `prompts/get` с `name` и `arguments`
- **THEN** сервер возвращает промпт с заполненными placeholder'ами

#### Scenario: Промпт не найден
- **WHEN** агент вызывает `prompts/get` с несуществующим `name`
- **THEN** сервер возвращает MCP error с кодом -32001 (Prompt not found)

### Requirement: Интеграция промптов с ACP session
MCP промпты SHALL быть доступны для использования в `session/prompt` как pre-built templates.

#### Scenario: Использование MCP промпта в session/prompt
- **WHEN** клиент вызывает `session/prompt` с ссылкой на MCP промпт
- **THEN** агент получает промпт через `prompts/get` и использует его как начальный prompt
