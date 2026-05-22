## Context

Текущая реализация ACP использует исключительно WebSocket транспорт (aiohttp) для всей коммуникации между клиентом и сервером. Спецификация ACP определяет stdio как основной транспорт, где клиент запускает агент как subprocess и общается через stdin/stdout.

Текущая архитектура:
- `ACPHttpServer` — монолитный класс, объединяющий HTTP-сервер, WebSocket-обработку, Web UI и бизнес-логику диспетчеризации
- `ACPProtocol` — transport-agnostic диспетчер, принимает `ACPMessage`, возвращает `ProtocolOutcome`
- Клиент использует `WebSocketTransport` + `ACPTransportService` (routing queues, background receive loop)

Ключевое преимущество: `ACPProtocol` уже не зависит от транспорта. Это позволяет добавить stdio без изменения бизнес-логики.

## Goals / Non-Goals

**Goals:**
- Реализовать stdio transport для сервера (чтение stdin, запись stdout, newline-delimited JSON-RPC)
- Реализовать stdio transport для клиента (subprocess launcher, pipe communication)
- Выделить транспортный слой сервера в отдельный пакет `server/transport/`
- Перевести local mode (`codelab`) на stdio (subprocess вместо thread)
- Добавить CLI флаги `--stdio` для serve и connect
- Обеспечить логирование ТОЛЬКО в stderr для stdio режима
- Предотвратить race condition при записи (единый asyncio.Lock)

**Non-Goals:**
- Streamable HTTP транспорт (отдельная задача)
- Изменение протокольных методов ACP
- Изменение бизнес-логики `ACPProtocol`
- Поддержка Windows (на первом этапе — macOS/Linux)

## Decisions

### D1: Абстракция транспорта сервера через Protocol (не ABC)

**Решение:** Использовать `typing.Protocol` для `AcpServerTransport` вместо абстрактного класса.

**Почему:**
- `Protocol` — структурная типизация, не требует наследования
- Каждый транспорт (WebSocket, Stdio) остаётся независимым классом
- Легче тестировать — можно создать mock через structural subtyping
- Соответствует Python 3.12+ стилю проекта

**Альтернатива:** ABC с `@abstractmethod`. Отклонена — добавляет ненужную иерархию наследования.

### D2: Callback-модель для обработки сообщений

**Решение:** `AcpServerTransport.run(on_message)` принимает callback `Callable[[ACPMessage], Awaitable[ProtocolOutcome]]`.

**Почему:**
- Транспорт не знает о `ACPProtocol` — только о сообщениях
- Транспорт управляет циклом чтения/записи, callback — бизнес-логикой
- Разделение ответственности: transport layer vs protocol layer

**Альтернатива:** Транспорт принимает `ACPProtocol` напрямую. Отклонена — создаёт жёсткую связность.

### D3: WebSocketTransport — перенос из ACPHttpServer

**Решение:** Вся логика `handle_ws_request()` переносится в `WebSocketTransport`. `ACPHttpServer` остаётся только для создания aiohttp.Application и маршрутизации.

**Почему:**
- `WebSocketTransport` реализует `AcpServerTransport` — единый интерфейс
- `ACPHttpServer` упрощается до orchestrator
- Поведение не меняется — весь код переносится 1:1

**Риски:** Большой объём кода для переноса (~400 строк). Митигация — пошаговый перенос с тестами после каждого шага.

### D4: StdioServerTransport — asyncio.StreamReader/Writer

**Решение:** Использовать `asyncio.StreamReader` обёртку над `sys.stdin.buffer` и `sys.stdout.buffer` для асинхронного чтения/записи.

**Почему:**
- Нативная async поддержка в Python
- Не блокирует event loop
- Совместимо с существующим asyncio кодом проекта

**Альтернатива:** `sys.stdin.readline()` в executor. Отклонена — сложнее управлять lifecycle.

### D5: Логирование ТОЛЬКО в stderr

**Решение:** Для stdio режима structlog настраивается с handler только на stderr. stdout — исключительно JSON-RPC сообщения.

**Почему:**
- Любые логи в stdout сломают JSON-RPC парсер клиента
- stderr — стандартное место для логов subprocess
- Соответствует спецификации ACP

**Реализация:** `StdioServerTransport` при инициализации перенастраивает structlog logger на stderr-only handler.

### D6: Единый asyncio.Lock на запись в stdout

**Решение:** Один `asyncio.Lock` защищает все записи в stdout — и response, и notifications, и Agent→Client RPC.

**Почему:**
- В stdio режиме все outgoing сообщения идут через один канал (stdout)
- Без lock возможна interleaving JSON (race condition)
- Простое и надёжное решение

### D7: StdioClientTransport — asyncio.create_subprocess_exec

**Решение:** Клиент запускает сервер через `asyncio.create_subprocess_exec(command, *args, stdin=PIPE, stdout=PIPE, stderr=PIPE)`.

**Почему:**
- Нативная async поддержка
- Контроль над stdin/stdout/stderr
- Возможность graceful shutdown

**Альтернатива:** `subprocess.Popen` + executor. Отклонена — блокирующий I/O.

### D8: Local mode — subprocess + stdio

**Решение:** `codelab` без подкоманды запускает сервер как subprocess через stdio вместо thread + WebSocket.

**Почему:**
- Соответствует спецификации ACP
- Изолированный процесс сервера
- Убирает hack с thread + WebSocket

**Миграция:** WebSocket local mode остаётся доступным через `codelab --local-transport ws` (на будущее, если понадобится).

### D9: Параметризация ACPTransportService

**Решение:** `ACPTransportService.__init__` принимает `Transport` (протокол) вместо создания `WebSocketTransport` внутри.

**Почему:**
- Вся routing infrastructure переиспользуется
- Минимум дублирования кода
- Dependency injection-friendly

## Risks / Trade-offs

| Риск | Влияние | Митигация |
|------|---------|-----------|
| Логи попадают в stdout | Критическое: клиент не может парсить JSON-RPC | Structlog handler только на stderr. Тест на capture stdout |
| Buffering stdout | Высокое: сообщения не доходят вовремя | `sys.stdout.reconfigure(line_buffering=True)` + ручной flush |
| Race condition writes | Высокое: interleaved JSON | Единый asyncio.Lock на все writes |
| Рефакторинг WebSocket | Среднее: регрессия поведения | Полное покрытие тестами до рефакторинга. CI проверка |
| Windows совместимость | Среднее: sys.stdin.buffer ведёт себя иначе | Отложено на отдельную задачу. macOS/Linux на первом этапе |
| Большой объём рефакторинга | Среднее: сложно ревью | Пошаговый перенос, каждый шаг с тестами |

## Migration Plan

1. **Фаза 1 (сервер):** Создать `server/transport/`, перенести WebSocket логику, добавить `StdioServerTransport`
2. **Фаза 2 (сервер CLI):** Добавить `--stdio` флаг
3. **Фаза 3 (клиент):** Создать `StdioClientTransport`, параметризовать `ACPTransportService`
4. **Фаза 4 (клиент CLI):** Добавить `--stdio` флаг, обновить local mode
5. **Фаза 5 (тесты):** Покрытие unit + integration тестами

**Rollback:** Все изменения обратно совместимы. WebSocket режим остаётся дефолтным для `serve` и `connect`. Для отката достаточно не использовать `--stdio` флаг.

## Open Questions

1. **Windows поддержка:** `sys.stdin.buffer` на Windows может требовать `msvcrt.setmode()`. Решить при реализации.
2. **Textual-web совместимость:** Web UI subprocess запускается через `textual-serve`. В stdio режиме Web UI не имеет смысла — нужно явно отключать.
