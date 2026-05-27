## ADDED Requirements

### Requirement: SSE Transport для MCP серверов
Агент SHALL поддерживать SSE (Server-Sent Events) transport для подключения к MCP серверам через SSE endpoint. Данный транспорт deprecated в MCP spec и поддерживается только для обратной совместимости.

#### Scenario: Подключение к MCP серверу через SSE
- **WHEN** клиент предоставляет конфигурацию MCP сервера с `type: "sse"` и `url`
- **THEN** агент устанавливает SSE соединение с указанным URL и выполняет MCP initialize handshake

#### Scenario: SSE connection с headers
- **WHEN** конфигурация MCP сервера содержит `headers` array
- **THEN** агент включает указанные HTTP headers при установлении SSE соединения

#### Scenario: Предупреждение о deprecated SSE transport
- **WHEN** агент использует SSE transport
- **THEN** агент логирует warning о том, что SSE transport deprecated в MCP spec

### Requirement: Конфигурация SSE транспорта
Конфигурация SSE транспорта SHALL включать: `type` (обязательно "sse"), `name`, `url`, `headers` (опционально).

#### Scenario: Валидация SSE конфигурации
- **WHEN** конфигурация содержит `type: "sse"` но отсутствует `url`
- **THEN** агент возвращает ошибку валидации

### Requirement: Capability advertisement для SSE transport
Агент SHALL объявлять `mcpCapabilities.sse: true` в initialize response только если SSE transport реализован.

#### Scenario: Объявление SSE capability
- **WHEN** агент поддерживает SSE transport
- **THEN** initialize response содержит `agentCapabilities.mcpCapabilities.sse: true`
