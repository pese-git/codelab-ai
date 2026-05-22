## 1. Абстракция транспорта сервера

- [x] 1.1 Создать пакет `server/transport/` с `__init__.py`
- [x] 1.2 Создать `server/transport/base.py` — протокол `AcpServerTransport` с методами `run(on_message)`, `send(message)`, `close()`
- [x] 1.3 Экспортировать `AcpServerTransport` из `server/transport/__init__.py`

## 2. WebSocketTransport (рефакторинг)

- [x] 2.1 Создать `server/transport/websocket.py` — класс `WebSocketTransport` реализующий `AcpServerTransport`
- [x] 2.2 Перенести логику из `ACPHttpServer.handle_ws_request()` в `WebSocketTransport.run()` (deferred tasks, background prompts, disconnect cleanup, ws_send_lock)
- [x] 2.3 Обновить `ACPHttpServer` — делегировать обработку в `WebSocketTransport`
- [x] 2.4 Убедиться что все существующие тесты проходят

## 3. StdioServerTransport

- [x] 3.1 Создать `server/transport/stdio.py` — класс `StdioServerTransport` реализующий `AcpServerTransport`
- [x] 3.2 Реализовать `run(on_message)` — цикл чтения из `sys.stdin.buffer` через `asyncio.StreamReader`
- [x] 3.3 Реализовать `send(message)` — запись в `sys.stdout.buffer` + flush
- [x] 3.4 Реализовать `close()` — graceful shutdown
- [x] 3.5 Настроить structlog handler ТОЛЬКО на stderr для stdio режима
- [x] 3.6 Добавить `asyncio.Lock` для защиты всех записей в stdout
- [x] 3.7 Добавить signal handlers (SIGTERM, SIGINT) для graceful shutdown

## 4. Stdio server runner

- [x] 4.1 Создать `server/transport/stdio_runner.py` — функция `run_stdio_server()`
- [x] 4.2 Реализовать создание DI контейнера, ClientRPCService, запуск цикла обработки
- [x] 4.3 Обеспечить единый Lock на запись (response + notifications + Agent→Client RPC)

## 5. CLI сервера

- [x] 5.1 Добавить флаг `--stdio` в `serve_parser` в `server/cli.py`
- [x] 5.2 Добавить функцию `run_stdio_serve()` в `server/cli.py`
- [x] 5.3 Обновить `run_serve()` — ветвление по `--stdio`
- [x] 5.4 Обновить `codelab/cli.py` — проброс `--stdio` флага

## 6. StdioClientTransport

- [x] 6.1 Создать `client/infrastructure/stdio_transport.py` — класс `StdioClientTransport`
- [x] 6.2 Реализовать `__aenter__()` — `asyncio.create_subprocess_exec` + background readers
- [x] 6.3 Реализовать `__aexit__()` — graceful shutdown subprocess
- [x] 6.4 Реализовать `send_str(data)` — запись в stdin subprocess
- [x] 6.5 Реализовать `receive_text()` — чтение из stdout queue
- [x] 6.6 Реализовать `is_connected()` — проверка состояния процесса

## 7. Параметризация ACPTransportService

- [x] 7.1 Обновить `ACPTransportService.__init__` — принимать `Transport` вместо создания WebSocketTransport внутри
- [x] 7.2 Создать factory функцию `create_websocket_transport_service()` для обратной совместимости
- [x] 7.3 Обновить `ClientProvider.get_transport()` — factory для stdio/websocket

## 8. Обновление ClientConfig и DI

- [x] 8.1 Добавить поля `transport_mode`, `stdio_command`, `stdio_args` в `ClientConfig`
- [x] 8.2 Обновить `create_client_container()` — новые параметры
- [x] 8.3 Обновить `ClientProvider` — создание правильного транспорта на основе config

## 9. Обновление TUI App

- [x] 9.1 Обновить `ACPClientApp.__init__` — параметры `transport_mode`, `stdio_command`, `stdio_args`
- [x] 9.2 Обновить `on_unmount()` — корректное завершение subprocess в stdio режиме

## 10. CLI клиента

- [x] 10.1 Добавить флаги `--stdio` и `--agent-command` в `connect_parser`
- [x] 10.2 Добавить функцию `_run_tui_app_stdio()` 
- [x] 10.3 Обновить `run_connect()` — ветвление по `--stdio`

## 11. Local mode на stdio

- [x] 11.1 Обновить `run_local()` в `codelab/cli.py` — запуск сервера как subprocess через stdio
- [x] 11.2 Убрать thread + WebSocket подход
- [x] 11.3 Обеспечить graceful shutdown при выходе из TUI

## 12. Тесты сервера

- [x] 12.1 Создать `tests/server/transport/test_stdio_transport.py` — тесты StdioServerTransport
- [x] 12.2 Создать `tests/server/transport/test_websocket_transport.py` — тесты WebSocketTransport после рефакторинга
- [x] 12.3 Тест: message roundtrip через stdio
- [x] 12.4 Тест: notification streaming
- [x] 12.5 Тест: EOF → graceful shutdown
- [x] 12.6 Тест: malformed JSON → error response
- [ ] 12.7 Тест: Lock предотвращает race condition

## 13. Тесты клиента

- [x] 13.1 Создать `tests/client/infrastructure/test_stdio_transport.py` — тесты StdioClientTransport
- [x] 13.2 Создать `tests/client/infrastructure/test_stdio_acp_transport_service.py` — тесты с stdio транспортом
- [x] 13.3 Тест: send → receive roundtrip
- [x] 13.4 Тест: subprocess exit → error handling
- [x] 13.5 Тест: graceful shutdown
- [x] 13.6 Интеграционный тест: полный lifecycle через stdio

## 14. Финальная проверка

- [x] 14.1 Запустить `make check` — линтер + тайпчекер + все тесты
- [x] 14.2 Ручная проверка: `codelab serve --stdio` + `codelab connect --stdio`
- [x] 14.3 Ручная проверка: `codelab` (local mode)
