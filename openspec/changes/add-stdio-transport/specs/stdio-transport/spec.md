## ADDED Requirements

### Requirement: Серверный stdio транспорт
Сервер SHALL поддерживать stdio транспорт для приёма JSON-RPC сообщений из stdin и отправки ответов в stdout. Каждое сообщение SHALL быть отделено символом новой строки (`\n`). Кодировка — UTF-8.

#### Scenario: Приём и отправка сообщения через stdio
- **WHEN** клиент записывает в stdin сервера строку `{"jsonrpc":"2.0","id":"1","method":"initialize","params":{...}}\n`
- **THEN** сервер парсит JSON, обрабатывает через ACPProtocol и записывает в stdout: `{"jsonrpc":"2.0","id":"1","result":{...}}\n`

#### Scenario: Отправка нескольких notifications подряд
- **WHEN** ACPProtocol возвращает ProtocolOutcome с несколькими notifications
- **THEN** сервер записывает каждое notification в stdout отдельной строкой, в порядке следования

#### Scenario: Обработка EOF (закрытие stdin)
- **WHEN** stdin закрывается (клиент завершил subprocess)
- **THEN** сервер завершает цикл чтения, выполняет cleanup активных turns и завершает работу

#### Scenario: Обработка невалидного JSON
- **WHEN** сервер получает строку, не являющуюся валидным JSON
- **THEN** сервер записывает в stdout: `{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"Parse error"}}\n`

### Requirement: Логирование сервера ТОЛЬКО в stderr
Сервер в stdio режиме SHALL направлять все логи исключительно в stderr. stdout SHALL содержать ТОЛЬКО JSON-RPC сообщения.

#### Scenario: Логирование при обработке запроса
- **WHEN** сервер обрабатывает входящее сообщение
- **THEN** все логи (debug, info, warning, error) записываются в stderr, stdout остаётся чистым

#### Scenario: Логирование ошибок парсинга
- **WHEN** сервер получает невалидный JSON
- **THEN** ошибка логируется в stderr, error response записывается в stdout

### Requirement: Блокировка записи в stdout
Сервер в stdio режиме SHALL использовать asyncio.Lock для защиты всех записей в stdout, включая responses, notifications и Agent→Client RPC запросы.

#### Scenario: Одновременная отправка response и notification
- **WHEN** сервер одновременно пытается отправить response и notification
- **THEN** записи выполняются последовательно, без interleaving JSON

#### Scenario: Agent→Client RPC во время отправки response
- **WHEN** Agent→Client RPC запрос отправляется одновременно с response на client request
- **THEN** оба сообщения записываются в stdout полностью, без пересечения

### Requirement: Graceful shutdown сервера
Сервер в stdio режиме SHALL корректно завершать работу при получении SIGTERM или SIGINT.

#### Scenario: Завершение по SIGTERM
- **WHEN** сервер получает сигнал SIGTERM
- **THEN** сервер завершает активные turns, закрывает соединения и завершает процесс с кодом 0

#### Scenario: Завершение по SIGINT
- **WHEN** сервер получает сигнал SIGINT (Ctrl+C)
- **THEN** сервер завершает активные turns, закрывает соединения и завершает процесс с кодом 0

### Requirement: Клиентский stdio транспорт
Клиент SHALL поддерживать stdio транспорт, запускающий агент как subprocess и коммуницирующий через stdin/stdout pipes.

#### Scenario: Запуск subprocess
- **WHEN** клиент вызывает connect с stdio транспортом и командой `codelab serve --stdio`
- **THEN** клиент запускает subprocess с stdin=PIPE, stdout=PIPE, stderr=PIPE

#### Scenario: Отправка сообщения в subprocess
- **WHEN** клиент отправляет JSON-RPC запрос через stdio транспорт
- **THEN** запрос записывается в stdin subprocess как строка UTF-8 с завершающим `\n`

#### Scenario: Получение сообщения из subprocess
- **WHEN** subprocess записывает строку в stdout
- **THEN** клиент получает строку через background reader и передаёт в routing queue

#### Scenario: Логирование stderr subprocess
- **WHEN** subprocess записывает данные в stderr
- **THEN** клиент логирует stderr как отладочную информацию, НЕ парсит как JSON-RPC

### Requirement: Graceful shutdown клиента
Клиент в stdio режиме SHALL корректно завершать subprocess при отключении.

#### Scenario: Нормальное завершение
- **WHEN** клиент вызывает disconnect
- **THEN** клиент закрывает stdin subprocess, ожидает завершения (timeout 5s), при необходимости — принудительно завершает

#### Scenario: Неожиданный выход subprocess
- **WHEN** subprocess завершается с ненулевым кодом во время работы
- **THEN** клиент логирует ошибку и уведомляет пользователя о потере соединения

### Requirement: CLI флаг --stdio для сервера
Команда `codelab serve` SHALL поддерживать флаг `--stdio` для запуска сервера в stdio режиме.

#### Scenario: Запуск сервера в stdio режиме
- **WHEN** пользователь выполняет `codelab serve --stdio`
- **THEN** сервер запускается в stdio режиме, читает stdin, пишет в stdout

#### Scenario: Игнорирование --port и --host в stdio режиме
- **WHEN** пользователь выполняет `codelab serve --stdio --port 8765`
- **THEN** сервер запускается в stdio режиме, параметры --port и --host игнорируются

#### Scenario: Автоматическое отключение Web UI в stdio режиме
- **WHEN** пользователь выполняет `codelab serve --stdio`
- **THEN** Web UI не запускается (не имеет смысла в stdio режиме)

### Requirement: CLI флаг --stdio для клиента
Команда `codelab connect` SHALL поддерживать флаг `--stdio` для подключения через stdio транспорт.

#### Scenario: Запуск клиента в stdio режиме с дефолтной командой
- **WHEN** пользователь выполняет `codelab connect --stdio --cwd /project`
- **THEN** клиент запускает subprocess `codelab serve --stdio` и подключается через stdio

#### Scenario: Запуск клиента с кастомной командой агента
- **WHEN** пользователь выполняет `codelab connect --stdio --agent-command "codelab serve --stdio --storage json:./sessions" --cwd /project`
- **THEN** клиент запускает указанную команду агента и подключается через stdio

### Requirement: Local mode через stdio
Команда `codelab` без подкоманды SHALL запускать сервер как subprocess через stdio транспорт вместо thread + WebSocket.

#### Scenario: Локальный режим через stdio
- **WHEN** пользователь выполняет `codelab` без подкоманды
- **THEN** сервер запускается как subprocess `codelab serve --stdio`, TUI подключается через stdio транспорт

#### Scenario: Завершение local mode
- **WHEN** пользователь выходит из TUI (Ctrl+Q)
- **THEN** TUI закрывает stdin subprocess, subprocess завершается gracefully

### Requirement: Параметризация ACPTransportService
Класс `ACPTransportService` SHALL принимать любой объект, реализующий протокол `Transport`, а не только `WebSocketTransport`.

#### Scenario: Создание с WebSocket транспортом
- **WHEN** `ACPTransportService` создаётся с `WebSocketTransport`
- **THEN** все методы (connect, disconnect, send, receive, request_with_callbacks) работают через WebSocket

#### Scenario: Создание с stdio транспортом
- **WHEN** `ACPTransportService` создаётся с `StdioClientTransport`
- **THEN** все методы работают через stdio, routing infrastructure переиспользуется

### Requirement: Абстракция AcpServerTransport
Сервер SHALL определять протокол `AcpServerTransport` с методами `run(on_message)`, `send(message)`, `close()`.

#### Scenario: WebSocketTransport реализует AcpServerTransport
- **WHEN** `WebSocketTransport` используется как `AcpServerTransport`
- **THEN** метод `run(on_message)` обрабатывает WebSocket сообщения через callback

#### Scenario: StdioServerTransport реализует AcpServerTransport
- **WHEN** `StdioServerTransport` используется как `AcpServerTransport`
- **THEN** метод `run(on_message)` обрабатывает stdin сообщения через callback

## MODIFIED Requirements

### Requirement: CLI команды сервера
Команда `codelab serve` поддерживает дополнительные флаги для выбора транспорта.

**Текущее поведение:** `codelab serve [--host HOST] [--port PORT] [--no-web]` — только WebSocket.

**Новое поведение:** `codelab serve [--host HOST] [--port PORT] [--no-web] [--stdio]` — WebSocket или stdio.

#### Scenario: Выбор WebSocket транспорта (дефолт)
- **WHEN** пользователь выполняет `codelab serve --port 8765`
- **THEN** сервер запускается в WebSocket режиме на указанном порту

#### Scenario: Выбор stdio транспорта
- **WHEN** пользователь выполняет `codelab serve --stdio`
- **THEN** сервер запускается в stdio режиме, параметры host/port игнорируются

### Requirement: CLI команды клиента
Команда `codelab connect` поддерживает дополнительные флаги для выбора транспорта.

**Текущее поведение:** `codelab connect [--host HOST] [--port PORT] [--cwd CWD]` — только WebSocket.

**Новое поведение:** `codelab connect [--host HOST] [--port PORT] [--cwd CWD] [--stdio] [--agent-command CMD]` — WebSocket или stdio.

#### Scenario: Выбор WebSocket транспорта (дефолт)
- **WHEN** пользователь выполняет `codelab connect --host 127.0.0.1 --port 8765`
- **THEN** клиент подключается к серверу через WebSocket

#### Scenario: Выбор stdio транспорта
- **WHEN** пользователь выполняет `codelab connect --stdio --cwd /project`
- **THEN** клиент запускает subprocess и подключается через stdio
