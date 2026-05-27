## ADDED Requirements

### Requirement: Обработка server-initiated notifications
Агент SHALL обрабатывать notifications от MCP серверов, включая `notifications/tools/list_changed` и другие server-initiated события.

#### Scenario: Получение tools/list_changed notification
- **WHEN** MCP сервер отправляет `notifications/tools/list_changed`
- **THEN** агент вызывает `tools/list` для обновления кэша инструментов

#### Scenario: Обновление ToolRegistry после list_changed
- **WHEN** агент получает обновленный список инструментов от MCP сервера
- **THEN** агент обновляет ToolRegistry и отправляет `available_commands_update` клиенту

#### Scenario: Игнорирование неизвестных notifications
- **WHEN** MCP сервер отправляет неизвестный тип notification
- **THEN** агент логирует debug message и игнорирует notification

### Requirement: Notification handler architecture
Агент SHALL использовать event-driven architecture для обработки MCP notifications с поддержкой multiple handlers.

#### Scenario: Регистрация handler для notification type
- **WHEN** компонент регистрирует handler для `tools/list_changed`
- **THEN** handler вызывается при получении соответствующей notification

#### Scenario: Multiple handlers для одного notification type
- **WHEN** несколько компонентов регистрируют handlers для одного notification type
- **THEN** все handlers вызываются параллельно

### Requirement: Notification logging
Агент SHALL логировать все полученные notifications с уровнем DEBUG для troubleshooting.

#### Scenario: Логирование полученной notification
- **WHEN** агент получает notification от MCP сервера
- **THEN** агент логирует: server_id, notification method, timestamp, params (если есть)
