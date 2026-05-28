# Справочник конфигурации

Полный справочник всех настроек CodeLab.

## Файлы конфигурации

CodeLab поддерживает два формата конфигурации:

### TOML файлы

| Файл | Приоритет | Описание | Коммитится |
|------|-----------|----------|------------|
| `~/.codelab/auth.toml` | Низший | Глобальные API keys | Нет |
| `codelab.toml` | Средний | Конфигурация проекта | Да |
| `codelab.local.toml` | Высокий | Локальные overrides | Нет |
| `--config <path>` | Высший | Кастомный файл | Зависит |

### Переменные окружения

| Файл | Приоритет | Описание |
|------|-----------|----------|
| Системные переменные | Высший | Переменные окружения ОС |
| `.env` (локальный) | Высокий | Настройки проекта |
| `~/.codelab/config/.env` | Низший | Глобальные настройки |

> **Примечание:** Переменные окружения переопределяют TOML значения.

## Конфигурация LLM

### Провайдер

| Опция | Значения | По умолчанию | Описание |
|-------|----------|--------------|----------|
| `CODELAB_LLM_PROVIDER` | `openai`, `anthropic`, `openrouter`, `zen`, `go`, `ollama`, `lmstudio`, `mock` | `mock` | Тип LLM провайдера |
| `CODELAB_LLM_MODEL` | `provider/model` | `mock/mock-model` | Модель в формате `"provider/model"` |

### Аутентификация

| Опция | Описание |
|-------|----------|
| `OPENAI_API_KEY` | API ключ OpenAI |
| `ANTHROPIC_API_KEY` | API ключ Anthropic |
| `OPENROUTER_API_KEY` | API ключ OpenRouter |
| `ZEN_API_KEY` | API ключ Zen |
| `GO_API_KEY` | API ключ Go |
| `CODELAB_LLM_BASE_URL` | Кастомный URL API (для совместимых сервисов) |

### Параметры модели

| Опция | По умолчанию | Описание |
|-------|--------------|----------|
| `CODELAB_LLM_MODEL` | `mock/mock-model` | Модель LLM в формате `"provider/model"` |
| `CODELAB_LLM_TEMPERATURE` | `0.7` | Temperature (0.0-1.0) |
| `CODELAB_LLM_MAX_TOKENS` | `8192` | Максимум токенов ответа |

### Fallback

| Опция | Значения | По умолчанию | Описание |
|-------|----------|--------------|----------|
| `CODELAB_FALLBACK_ENABLED` | `true`, `false` | `false` | Включить fallback цепочку |
| `CODELAB_FALLBACK_STRATEGY` | `sequential` | `sequential` | Стратегия fallback |
| `CODELAB_FALLBACK_ORDER` | `openai,openrouter,ollama` | — | Порядок провайдеров |

## Конфигурация сервера

| Опция | По умолчанию | Описание |
|-------|--------------|----------|
| `CODELAB_PORT` | `8765` | Порт WebSocket сервера |
| `CODELAB_HOST` | `127.0.0.1` | Адрес привязки сервера |
| `CODELAB_HOME` | `~/.codelab` | Домашняя директория приложения |

## Конфигурация логирования

| Опция | Значения | По умолчанию | Описание |
|-------|----------|--------------|----------|
| `CODELAB_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` | `INFO` | Уровень логирования |

## Пример конфигурации

### Минимальная конфигурация для работы с OpenAI

```env
CODELAB_LLM_PROVIDER=openai
CODELAB_LLM_API_KEY=sk-your-api-key-here
```

### Полная конфигурация (.env)

```env
# LLM Configuration
CODELAB_LLM_PROVIDER=openai
CODELAB_LLM_API_KEY=sk-your-api-key-here
CODELAB_LLM_MODEL=openai/gpt-4o
CODELAB_LLM_TEMPERATURE=0.7
CODELAB_LLM_MAX_TOKENS=8192

# Server Configuration
CODELAB_PORT=8765
CODELAB_HOST=127.0.0.1
CODELAB_HOME=~/.codelab

# Logging
CODELAB_LOG_LEVEL=INFO
```

### TOML конфигурация (codelab.toml)

```toml
[llm]
provider = "openai"
model = "openai/gpt-4o"
temperature = 0.7
max_tokens = 8192

[llm.providers.openai]
api_key = "${OPENAI_API_KEY}"
base_url = "https://api.openai.com/v1"

[llm.providers.openai.models.gpt-4o]
context_window = 128000
max_output_tokens = 16384

[llm.fallback]
enabled = true
order = ["openai", "openrouter", "ollama"]
retry_on = ["rate_limit", "timeout"]
```

### Использование совместимого API (OpenRouter, Azure)

```env
CODELAB_LLM_PROVIDER=openai
CODELAB_LLM_API_KEY=your-openrouter-key
CODELAB_LLM_BASE_URL=https://openrouter.ai/api/v1
CODELAB_LLM_MODEL=anthropic/claude-3-opus
```

## Конфигурация сессий

Настройки сессий задаются через ACP протокол при создании сессии (`session/new`):

| Параметр | Тип | Описание |
|----------|-----|----------|
| `workingDirectory` | `string` | Рабочая директория проекта |
| `environmentVariables` | `object` | Переменные окружения для инструментов |
| `mcpServers` | `array` | Список MCP серверов для подключения |

### Пример конфигурации сессии

```json
{
  "workingDirectory": "/home/user/project",
  "environmentVariables": {
    "NODE_ENV": "development"
  },
  "mcpServers": [
    {
      "name": "filesystem",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"]
    }
  ]
}
```

## Конфигурация MCP серверов

### Параметры MCP сервера (TOML)

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|--------------|----------|
| `name` | `string` | — | Уникальное имя сервера (обязательно) |
| `type` | `string` | `stdio` | Тип транспорта: `stdio`, `http`, `sse` |
| `command` | `string` | — | Команда запуска (для `stdio`) |
| `args` | `array` | `[]` | Аргументы командной строки (для `stdio`) |
| `env` | `array` | `[]` | Переменные окружения `[{name, value}]` |
| `url` | `string` | — | URL MCP сервера (для `http`/`sse`) |
| `headers` | `array` | `[]` | HTTP headers `[{name, value}]` |

### Параметры retry

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|--------------|----------|
| `max_retries` | `int` | `5` | Максимум попыток переподключения |
| `initial_delay` | `float` | `1.0` | Начальная задержка (секунды) |
| `max_delay` | `float` | `30.0` | Максимальная задержка (секунды) |
| `backoff_multiplier` | `float` | `2.0` | Множитель exponential backoff |

### Примеры конфигурации

**Stdio транспорт:**
```toml
[[mcp.servers]]
name = "filesystem"
type = "stdio"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/project"]
env = [
  { name = "DEBUG", value = "true" }
]
```

**HTTP транспорт:**
```toml
[[mcp.servers]]
name = "github"
type = "http"
url = "https://api.githubcopilot.com/mcp/"
headers = [
  { name = "Authorization", value = "${GITHUB_TOKEN}" }
]
max_retries = 3
initial_delay = 2.0
```

**SSE транспорт:**
```toml
[[mcp.servers]]
name = "streaming-server"
type = "sse"
url = "https://mcp.example.com/sse"
```

### Параметры сессии (JSON-RPC)

При создании сессии через `session/new`:

| Параметр | Тип | Описание |
|----------|-----|----------|
| `mcpServers` | `array` | Список MCP серверов для подключения |
| `mcpServers[].name` | `string` | Имя сервера |
| `mcpServers[].type` | `string` | Транспорт: `stdio`, `http`, `sse` |
| `mcpServers[].command` | `string` | Команда (stdio) |
| `mcpServers[].args` | `array` | Аргументы (stdio) |
| `mcpServers[].env` | `array` | Переменные окружения `[{name, value}]` |
| `mcpServers[].url` | `string` | URL (http/sse) |
| `mcpServers[].headers` | `array` | HTTP headers `[{name, value}]` |
| `mcpServers[].max_retries` | `int` | Retry попытки |
| `mcpServers[].initial_delay` | `float` | Начальная задержка |
| `mcpServers[].max_delay` | `float` | Максимальная задержка |
| `mcpServers[].backoff_multiplier` | `float` | Backoff множитель |

### Переменные окружения для MCP

| Переменная | Описание |
|------------|----------|
| `${GITHUB_TOKEN}` | Токен GitHub для GitHub MCP |
| `${OPENAI_API_KEY}` | API ключ для OpenAI MCP |
| `${DATABASE_URL}` | URL базы данных для Database MCP |
| `${MY_API_KEY}` | Любая кастомная переменная |

> **Примечание:** Используйте синтаксис `${VAR_NAME}` в TOML для раскрытия переменных окружения.

## Структура домашней директории

```
~/.codelab/
├── config/
│   └── .env              # Глобальная конфигурация
├── logs/
│   └── codelab.log       # Логи с ротацией
├── data/
│   ├── sessions/         # JSON файлы сессий
│   ├── history/          # История чатов клиента
│   └── policies/         # Глобальные политики разрешений
└── cache/                # Временные данные и кэш MCP
```

## MCP инструменты

### Именование

```
mcp:{server_id}:{tool_name}
```

### Kind Inference

| MCP Annotation | ACP Kind | Описание |
|----------------|----------|----------|
| `readOnlyHint: true` | `read` | Только чтение |
| `destructiveHint: true` | `execute` | Разрушительное действие |
| `idempotentHint: true` | `edit` | Изменяемое, идемпотентное |
| `openWorldHint: true` | `execute` | Внешний мир (API, веб) |

### Эвристика по имени (если нет annotations)

| Префикс | ACP Kind |
|---------|----------|
| `read_*`, `get_*`, `list_*`, `fetch_*` | `read` |
| `write_*`, `create_*`, `delete_*`, `remove_*` | `execute` |
| `update_*`, `modify_*`, `set_*` | `edit` |
| Остальные | `other` |

## См. также

- [TOML конфигурация](../user-guide/13-toml-configuration.md) — полное руководство по TOML
- [MCP серверы](../user-guide/14-mcp-servers.md) — подключение и настройка MCP
- [Переменные окружения](03-environment.md) — детальное описание переменных
- [CLI команды](01-cli.md) — справочник командной строки
- [Настройка сервера](../user-guide/03-server-setup.md) — руководство по настройке
