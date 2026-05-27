## ADDED Requirements

### Requirement: HTTP Transport для MCP серверов
Агент SHALL поддерживать HTTP transport для подключения к MCP серверам через HTTP POST запросы с JSON-RPC сообщениями.

#### Scenario: Подключение к MCP серверу через HTTP
- **WHEN** клиент предоставляет конфигурацию MCP сервера с `type: "http"` и `url`
- **THEN** агент устанавливает HTTP соединение с указанным URL и выполняет MCP initialize handshake

#### Scenario: HTTP запрос с headers
- **WHEN** конфигурация MCP сервера содержит `headers` array
- **THEN** агент включает указанные HTTP headers в каждый запрос к MCP серверу

#### Scenario: Ошибка подключения к HTTP серверу
- **WHEN** HTTP сервер недоступен или возвращает ошибку
- **THEN** агент логирует ошибку и возвращает MCPManagerError клиенту

### Requirement: Конфигурация HTTP транспорта
Конфигурация HTTP транспорта SHALL включать: `type` (обязательно "http"), `name`, `url`, `headers` (опционально).

#### Scenario: Валидация HTTP конфигурации
- **WHEN** конфигурация содержит `type: "http"` но отсутствует `url`
- **THEN** агент возвращает ошибку валидации

#### Scenario: HTTP конфигурация с authentication headers
- **WHEN** клиент предоставляет `headers: [{"name": "Authorization", "value": "Bearer token"}]`
- **THEN** агент включает Authorization header во все HTTP запросы

### Requirement: Capability advertisement для HTTP transport
Агент SHALL объявлять `mcpCapabilities.http: true` в initialize response только если HTTP transport полностью реализован и протестирован.

#### Scenario: Объявление HTTP capability
- **WHEN** агент поддерживает HTTP transport
- **THEN** initialize response содержит `agentCapabilities.mcpCapabilities.http: true`

#### Scenario: Отсутствие HTTP capability
- **WHEN** агент не поддерживает HTTP transport
- **THEN** initialize response содержит `agentCapabilities.mcpCapabilities.http: false` или поле отсутствует
