# Исправление: пустой output терминальных команд

## Проблема
Клиент показывает "вывод команды пустой или не был захвачен" при выполнении terminal tools.

## Корневая причина
Race condition в `TerminalExecutor`:
- `_read_output` работает как фоновая задача (`asyncio.create_task`)
- `wait_for_exit` делает `await process.wait()` и сразу возвращает exit_code
- Фоновая задача может не успеть прочитать весь output из stdout буфера
- `get_output` вызывается после `wait_for_exit` и получает пустой буфер

## Решение

### 1. Добавить поле `read_task` в `TerminalSession`
**Файл:** `codelab/src/codelab/client/infrastructure/services/terminal_executor.py:47-70`

Добавить в dataclass:
```python
read_task: asyncio.Task[None] | None = None
```

### 2. Сохранять задачу в сессию в `create_terminal`
**Файл:** `codelab/src/codelab/client/infrastructure/services/terminal_executor.py:139-140`

Заменить:
```python
asyncio.create_task(self._read_output(session))
```
На:
```python
session.read_task = asyncio.create_task(self._read_output(session))
```

### 3. Обновить `wait_for_exit` чтобы ждать завершения read_task
**Файл:** `codelab/src/codelab/client/infrastructure/services/terminal_executor.py:242-279`

После `await session.process.wait()` добавить ожидание read_task:
```python
await session.process.wait()
exit_code = session.process.returncode or 0

# Дождаться завершения задачи чтения output
if session.read_task and not session.read_task.done():
    try:
        await asyncio.wait_for(session.read_task, timeout=5.0)
    except asyncio.TimeoutError:
        logger.warning(
            "read_task_timeout",
            terminal_id=terminal_id,
        )

session.exit_code = exit_code
session.state = TerminalState.EXITED

logger.info(
    "terminal_wait_complete",
    terminal_id=terminal_id,
    exit_code=exit_code,
)

return exit_code
```

### 4. Добавить логирование размера output в `handle_wait_for_exit`
**Файл:** `codelab/src/codelab/client/infrastructure/handlers/terminal_handler.py:203-215`

Добавить логирование:
```python
logger.info(
    "agent_terminal_wait_success",
    session_id=session_id,
    terminal_id=terminal_id,
    exit_code=exit_code,
    output_size=len(output),
)
```

## Тестирование
- Запустить `uv run pytest tests/client/test_terminal_executor.py -xvs`
- Проверить что тесты проходят
- Запустить `make check` для lint
