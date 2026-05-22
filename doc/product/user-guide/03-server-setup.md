# Настройка сервера

> Руководство по запуску и настройке ACP сервера.

## Обзор

Сервер CodeLab обрабатывает ACP протокол, управляет сессиями и взаимодействует с LLM провайдерами.

## Режимы запуска

### Local mode (по умолчанию)

Запускает сервер и TUI клиент вместе:

```bash
codelab
```

### Server mode

Запускает только сервер с WebSocket API:

```bash
codelab serve [OPTIONS]
```

### Client mode

Подключает TUI клиент к существующему серверу:

```bash
codelab connect [OPTIONS]
```

## Параметры сервера

### Основные параметры

| Параметр | По умолчанию | Описание |
|----------|--------------|----------|
| `--host` | `127.0.0.1` | Адрес привязки |
| `--port` | `8765` | Порт WebSocket |
| `--verbose` | `false` | Подробное логирование |

### Примеры

```bash
# Стандартный запуск
codelab serve

# Кастомный порт
codelab serve --port 9000

# Внешний доступ
codelab serve --host 0.0.0.0 --port 8765

# С подробным логированием
codelab serve --verbose
```

## Переменные окружения

### Сеть

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `CODELAB_HOST` | Адрес привязки | `127.0.0.1` |
| `CODELAB_PORT` | Порт сервера | `8765` |

### LLM провайдер

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `CODELAB_LLM_PROVIDER` | Тип провайдера (`openai`, `anthropic`, `mock`) | `mock` |
| `CODELAB_LLM_API_KEY` | API ключ LLM | — |
| `CODELAB_LLM_MODEL` | Модель LLM | `gpt-4o` |
| `CODELAB_LLM_BASE_URL` | Base URL (для OpenAI-совместимых) | — |
| `CODELAB_LLM_TEMPERATURE` | Temperature (0.0-1.0) | `0.7` |
| `CODELAB_LLM_MAX_TOKENS` | Максимум токенов | `8192` |

### Логирование

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `CODELAB_LOG_LEVEL` | Уровень логов (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |

## Конфигурационные файлы

Порядок загрузки (от низкого приоритета к высокому):

1. `~/.codelab/config/.env` — глобальные настройки
2. `.env` в текущей директории — настройки проекта
3. Переменные окружения системы

### Пример .env файла

```bash
# LLM Configuration
CODELAB_LLM_PROVIDER=openai
CODELAB_LLM_API_KEY=sk-your-key-here
CODELAB_LLM_MODEL=gpt-4o
CODELAB_LLM_TEMPERATURE=0.7

# Server
CODELAB_PORT=8765
CODELAB_HOST=127.0.0.1

# Logging
CODELAB_LOG_LEVEL=INFO
```

## Структура директорий

При первом запуске создается `~/.codelab/`:

```
~/.codelab/
├── config/         # Конфигурационные файлы
│   └── .env        # Глобальная конфигурация
├── logs/           # Файлы логов
│   └── codelab.log
├── data/           # Данные приложения
│   ├── sessions/   # Сессии сервера (JSON)
│   ├── history/    # История чатов клиента
│   └── policies/   # Глобальные политики разрешений
└── cache/          # Кэш MCP и временные данные
```

## LLM провайдеры

### OpenAI

```bash
CODELAB_LLM_PROVIDER=openai
CODELAB_LLM_API_KEY=sk-...
CODELAB_LLM_MODEL=gpt-4o
```

### OpenAI-совместимые (Azure, Local)

```bash
CODELAB_LLM_PROVIDER=openai
CODELAB_LLM_API_KEY=...
CODELAB_LLM_BASE_URL=https://your-endpoint.com/v1
CODELAB_LLM_MODEL=your-model
```

### Mock (для разработки)

```bash
CODELAB_LLM_PROVIDER=mock
```

Mock провайдер не требует API ключа и возвращает тестовые ответы.

## Аутентификация

### Включение аутентификации

Установите переменную окружения `ACP_SERVER_API_KEY`:

```bash
export ACP_SERVER_API_KEY="your-secret-key"
codelab serve
```

Клиент должен будет предоставить API ключ при инициализации через метод `authenticate`.

## Хранение сессий

### In-Memory (по умолчанию для разработки)

Сессии хранятся в памяти и теряются при перезапуске.

### JSON File (production)

Сессии сохраняются в `~/.codelab/data/sessions/`:

```
sessions/
├── session-uuid-1.json
├── session-uuid-2.json
└── ...
```

## Логирование

Логи сохраняются в `~/.codelab/logs/codelab.log` с ротацией.

### Просмотр логов

```bash
# В реальном времени
tail -f ~/.codelab/logs/codelab.log

# С фильтрацией
grep ERROR ~/.codelab/logs/codelab.log
```

### Уровни логирования

| Уровень | Описание |
|---------|----------|
| `DEBUG` | Подробная отладка (включая JSON-RPC) |
| `INFO` | Основные события |
| `WARNING` | Предупреждения |
| `ERROR` | Ошибки |

## Healthcheck

Проверка работоспособности:

```bash
curl http://localhost:8765/health
# {"status": "ok"}
```

## Производительность

### Рекомендации

- Используйте SSD для `~/.codelab/data/`
- Увеличьте `CODELAB_LLM_MAX_TOKENS` для сложных задач
- Настройте `CODELAB_LLM_TEMPERATURE` под тип задач

### Ресурсы

Минимальные требования:
- RAM: 512 MB
- CPU: 1 core
- Disk: 100 MB для данных

## Troubleshooting

### Порт занят

```bash
# Найти процесс на порту
lsof -i :8765

# Использовать другой порт
codelab serve --port 9000
```

### Ошибка API ключа

```
Error: Invalid API key
```

Проверьте:
1. `CODELAB_LLM_API_KEY` установлен
2. Ключ валидный для провайдера
3. Нет лишних пробелов

### Сервер не отвечает

```bash
# Проверить запущен ли
ps aux | grep codelab

# Проверить логи
cat ~/.codelab/logs/codelab.log | tail -50
```

## См. также

- [Конфигурация](04-configuration.md) — детальная настройка
- [Разрешения](05-permissions.md) — политики безопасности
- [Интеграция с Zed IDE](10-zed-ide-integration.md) — настройка в Zed IDE
