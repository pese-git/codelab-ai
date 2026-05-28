## ADDED Requirements

### Requirement: MCP Resources — list
Агент SHALL поддерживать метод MCP `resources/list` для получения списка доступных ресурсов от MCP сервера.

#### Scenario: Получение списка ресурсов
- **WHEN** агент вызывает `resources/list` у MCP сервера
- **THEN** сервер возвращает список ресурсов с `uri`, `name`, `description`, `mimeType`

#### Scenario: Кэширование списка ресурсов
- **WHEN** агент получает список ресурсов от MCP сервера
- **THEN** агент кэширует ресурсы для последующего использования в prompt context

### Requirement: MCP Resources — read
Агент SHALL поддерживать метод MCP `resources/read` для чтения содержимого ресурса по URI.

#### Scenario: Чтение текстового ресурса
- **WHEN** агент вызывает `resources/read` с `uri` текстового ресурса
- **THEN** сервер возвращает содержимое ресурса в формате `text`

#### Scenario: Чтение бинарного ресурса
- **WHEN** агент вызывает `resources/read` с `uri` бинарного ресурса
- **THEN** сервер возвращает содержимое ресурса в формате `blob` (base64 encoded)

#### Scenario: Ресурс не найден
- **WHEN** агент вызывает `resources/read` с несуществующим `uri`
- **THEN** сервер возвращает MCP error с кодом -32001 (Resource not found)

### Requirement: Интеграция ресурсов с ACP Content
MCP ресурсы SHALL быть преобразованы в ACP ContentBlock типы (Text, Image, Audio, EmbeddedResource) для использования в prompt turn.

#### Scenario: MCP text resource → ACP Text content
- **WHEN** MCP сервер возвращает text resource
- **THEN** агент преобразует его в ACP `ContentBlock::Text`

#### Scenario: MCP image resource → ACP Image content
- **WHEN** MCP сервер возвращает image resource с `mimeType: "image/png"`
- **THEN** агент преобразует его в ACP `ContentBlock::Image`
