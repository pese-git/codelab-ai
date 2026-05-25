# План: Логи с PID в имени файла

## Проблема

Zed и другие редакторы запускают `codelab serve --stdio` как subprocess. При перезапуске редактора:
- Старый процесс не всегда завершается
- Новый процесс запускается параллельно
- Оба процесса пишут в один файл `codelab.log` → дублирование записей

Попытка решить через `fcntl.flock()` привела к новой проблеме:
- Новый процесс убивает старый (SIGTERM → SIGKILL)
- Это ломает работу если несколько редакторов используют codelab одновременно
- Race condition при одновременном запуске

## Решение

Каждый процесс пишет логи в **отдельный файл** с PID в имени:

```
~/.codelab/logs/codelab-29648.log  ← процесс 29648
~/.codelab/logs/codelab-30460.log  ← процесс 30460
```

## Изменения

### 1. `codelab/src/codelab/shared/logging.py`

**Изменить:**
- В `setup_logging()` при `log_file="default"` использовать `codelab-{pid}.log` вместо `codelab.log`
- PID получается через `os.getpid()`

**Оставить:**
- Guard-флаг `_logging_configured` для идемпотентности
- Функцию `reset_logging()` для тестов
- Процессор `_add_pid` для добавления PID в каждую запись

### 2. `codelab/src/codelab/server/transport/stdio_runner.py`

**Удалить:**
- `_LOCK_FILE`, `_lock_file_handle`
- `_is_process_running()`, `_read_pid_from_lock()`
- `_acquire_singleton_lock()`, `_release_singleton_lock()`
- Импорт `fcntl`, `signal`, `time`

**Оставить:**
- Простую инициализацию без lock механизма
- `_PID_FILE` можно удалить (не нужен)

### 3. `codelab/tests/client/test_logging.py`

**Обновить:**
- Тесты на `log_file="default"` должны проверять что файл создаётся с PID в имени
- Убрать тесты на lock механизм

### 4. `codelab/tests/server/test_stdio_transport_e2e.py`

**Удалить:**
- `test_lock_file_functions`
- `test_acquire_lock_no_file`
- `test_acquire_lock_stale_pid`

## Поведение

### Запуск
```
codelab serve --stdio
→ PID=12345
→ Логи: ~/.codelab/logs/codelab-12345.log
```

### Перезапуск редактора
```
Старый процесс: PID=12345 → codelab-12345.log (продолжает писать)
Новый процесс:  PID=12346 → codelab-12346.log (новый файл)
```

### Очистка старых логов
- Файлы логов не удаляются автоматически
- RotatingFileHandler ограничивает размер каждого файла (10MB, 5备份)
- Для ручной очистки: `rm ~/.codelab/logs/codelab-*.log`

## Преимущества

| Аспект | Было (flock) | Станет (PID в имени) |
|--------|--------------|----------------------|
| Конфликты между редакторами | ❌ Kill процессов | ✅ Нет конфликтов |
| Race condition | ❌ Есть | ✅ Нет |
| Сложность кода | Высокая | Низкая |
| Изоляция процессов | ❌ Один файл | ✅ Отдельные файлы |
| Отладка | ❌ Смешанные логи | ✅ По PID легко найти |
| Накопление файлов | ❌ Один большой | ⚠️ Несколько (решаемо) |

## Тесты

1. `test_setup_logging_default_creates_pid_file` — проверка что файл создаётся с PID
2. `test_multiple_processes_separate_files` — два процесса пишут в разные файлы
3. `test_pid_in_log_entries` — PID присутствует в каждой записи

## Миграция

- Старые файлы `codelab.log` не удаляются автоматически
- Новые файлы создаются рядом: `codelab-<pid>.log`
- Для очистки: `rm ~/.codelab/logs/codelab.log` (опционально)
