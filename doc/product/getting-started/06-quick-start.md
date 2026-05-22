# Quick Start: CodeLab

> Полное руководство: от установки до запуска сервера с TOML конфигурацией за 10 минут.

## Что вы сделаете

1. Установите CodeLab и зависимости
2. Настроите LLM провайдер через TOML конфигурацию
3. Запустите сервер
4. Подключитесь через TUI клиент
5. Выполните первый запрос к агенту

## Предварительные требования

| Требование | Минимальная версия | Проверка |
|------------|-------------------|----------|
| Python | 3.12+ | `python3 --version` |
| uv | 0.4+ | `uv --version` |
| Git | 2.0+ | `git --version` |
| OS | macOS, Linux, Windows | — |

> **Нет Python 3.12?** Установите через [pyenv](https://github.com/pyenv/pyenv) или скачайте с [python.org](https://www.python.org/downloads/).

## Шаг 1: Установка

### 1.1 Клонирование репозитория

```bash
git clone https://github.com/pese-git/codelab-ai.git
cd codelab-ai
```

### 1.2 Установка зависимостей

```bash
cd codelab
uv sync
```

Это установит:
- Все Python зависимости
- LLM провайдеры (OpenAI, Anthropic SDK)
- TUI клиент (Textual)
- WebSocket сервер

### 1.3 Проверка установки

```bash
uv run codelab --help
```

Вы должны увидеть:
```
Usage: codelab [OPTIONS] COMMAND [ARGS]...

CodeLab — ACP Server & Client

Commands:
  serve     Запустить ACP сервер
  connect   Подключить TUI клиент к серверу
  stdio     Запустить в stdio режиме (для IDE интеграции)
```

## Шаг 2: Конфигурация

CodeLab поддерживает два способа конфигурации: через переменные окружения (`.env`) и через TOML файлы. TOML рекомендуется для production.

### Вариант A: TOML конфигурация (рекомендуется)

#### 2.1 Создание codelab.toml

Создайте файл `codelab.toml` в корне проекта:

```bash
# Скопировать шаблон
cp codelab.toml.example codelab.toml

# Или создать вручную
touch codelab.toml
```

#### 2.2 Базовая конфигурация

Откройте `codelab.toml` и добавьте:

```toml
# codelab.toml

[llm]
# Активный провайдер: openai, anthropic, ollama, mock
provider = "openai"

# Модель в формате "provider/model"
model = "openai/gpt-4o"

# Параметры генерации
temperature = 0.7
max_tokens = 8192
```

#### 2.3 Настройка API ключа

**Способ 1: Через переменную окружения (рекомендуется)**

```bash
export OPENAI_API_KEY="sk-your-key-here"
```

Или добавьте в `.env`:
```bash
# .env
OPENAI_API_KEY=sk-your-key-here
```

В TOML используйте ссылку на переменную:
```toml
[llm.providers.openai]
api_key = "${OPENAI_API_KEY}"
```

**Способ 2: Напрямую в TOML (не рекомендуется для git)**

```toml
[llm.providers.openai]
api_key = "sk-your-key-here"
```

> **Важно:** Не коммитьте API keys в git! Используйте `.env` или `~/.codelab/auth.toml`.

#### 2.4 Глобальная аутентификация

Создайте файл `~/.codelab/auth.toml` для хранения API keys общих для всех проектов:

```bash
mkdir -p ~/.codelab
nano ~/.codelab/auth.toml
```

```toml
# ~/.codelab/auth.toml

[llm.providers.openai]
api_key = "sk-your-openai-key"

[llm.providers.anthropic]
api_key = "sk-ant-your-anthropic-key"
```

Этот файл автоматически загружается при запуске и имеет низший приоритет (переопределяется `codelab.toml`).

#### 2.5 Полная конфигурация с fallback

```toml
# codelab.toml — Production конфигурация

[llm]
provider = "openai"
model = "openai/gpt-4o"
temperature = 0.7
max_tokens = 8192

[llm.providers.openai]
api_key = "${OPENAI_API_KEY}"
base_url = "https://api.openai.com/v1"
default_model = "gpt-4o"

[llm.providers.openai.models.gpt-4o]
context_window = 128000
max_output_tokens = 16384

[llm.providers.openrouter]
api_key = "${OPENROUTER_API_KEY}"
base_url = "https://openrouter.ai/api/v1"

[llm.providers.ollama]
base_url = "http://localhost:11434/v1"
default_model = "llama3.1:70b"

[llm.fallback]
enabled = true
strategy = "sequential"
order = ["openai", "openrouter", "ollama"]
max_attempts = 3
retry_on = ["rate_limit", "timeout"]
```

### Вариант B: Конфигурация через .env

Создайте `.env` файл:

```bash
cp .env.example .env
nano .env
```

```bash
# .env

# LLM Configuration
CODELAB_LLM_PROVIDER=openai
CODELAB_LLM_MODEL=openai/gpt-4o
CODELAB_LLM_TEMPERATURE=0.7
CODELAB_LLM_MAX_TOKENS=8192

# API Keys
OPENAI_API_KEY=sk-your-key-here

# Server
CODELAB_PORT=8765
CODELAB_HOST=127.0.0.1
CODELAB_LOG_LEVEL=INFO
```

## Шаг 3: Запуск сервера

### 3.1 Базовый запуск

```bash
uv run codelab serve
```

Вы увидите:
```
INFO     Server starting on 127.0.0.1:8765
INFO     Web UI available at http://127.0.0.1:8765/
INFO     WebSocket endpoint: ws://127.0.0.1:8765/ws
INFO     Using LLM provider: openai
INFO     Using model: openai/gpt-4o
```

### 3.2 Запуск с кастомным TOML

```bash
uv run codelab serve --config /path/to/custom-config.toml
```

### 3.3 Запуск с fallback

```bash
uv run codelab serve \
  --fallback-enabled \
  --fallback-order openai,openrouter,ollama
```

### 3.4 Запуск с Ollama (локальная модель)

```bash
# 1. Установите Ollama: https://ollama.ai
# 2. Скачайте модель:
ollama pull llama3.1:70b

# 3. Настройте codelab.toml:
# [llm]
# provider = "ollama"
# model = "ollama/llama3.1:70b"

# 4. Запустите:
uv run codelab serve
```

### 3.5 Запуск в stdio режиме (для IDE)

```bash
uv run codelab stdio
```

Этот режим используется для интеграции с IDE (Zed, VS Code).

## Шаг 4: Подключение клиента

### 4.1 TUI клиент (рекомендуется)

В новом терминале:

```bash
cd codelab
uv run codelab connect
```

Или подключитесь к удалённому серверу:

```bash
uv run codelab connect --host 127.0.0.1 --port 8765
```

### 4.2 Web клиент

Откройте браузер и перейдите по адресу:

```
http://127.0.0.1:8765/
```

### 4.3 Локальный режим (всё в одном)

```bash
uv run codelab
```

Это запустит сервер и подключит TUI клиент автоматически.

## Шаг 5: Первый запрос

### 5.1 Создание сессии

При первом подключении сессия создаётся автоматически.

### 5.2 Отправка промпта

В TUI клиенте:
1. Нажмите `Enter` для активации поля ввода
2. Введите запрос: `Создай файл hello.py с функцией print("Hello, World!")`
3. Нажмите `Enter` для отправки

### 5.3 Результат

Агент выполнит запрос:
1. Проанализирует промпт
2. Создаст план действий
3. Вызовет инструменты (создание файла)
4. Вернёт результат

Вы увидите:
```
✓ Файл hello.py создан
✓ Содержимое: print("Hello, World!")
```

## Шаг 6: Проверка конфигурации

### 6.1 Проверка текущего провайдера

```bash
# Через переменные окружения
env | grep CODELAB_LLM

# Через логи сервера
grep "Using LLM provider" ~/.codelab/logs/codelab-server.log
```

### 6.2 Проверка TOML конфигурации

```python
# Проверить парсинг TOML
python3 -c "
import tomllib
config = tomllib.load(open('codelab.toml', 'rb'))
print(f'Provider: {config[\"llm\"][\"provider\"]}')
print(f'Model: {config[\"llm\"][\"model\"]}')
"
```

### 6.3 Тестовый запрос с mock провайдером

```bash
# Временно переключиться на mock
CODELAB_LLM_PROVIDER=mock uv run codelab serve
```

## Troubleshooting

### Ошибка: "ModuleNotFoundError: No module named 'codelab'"

**Решение:**
```bash
cd codelab
uv sync
```

### Ошибка: "Invalid API Key"

**Проверка:**
1. Убедитесь что API key установлен: `echo $OPENAI_API_KEY`
2. Проверьте что key активен в личном кабинете провайдера
3. Убедитесь что `codelab.toml` содержит `api_key = "${OPENAI_API_KEY}"`

### Ошибка: "Provider not found"

**Решение:**
Проверьте ID провайдера в `codelab.toml`. Доступные: `openai`, `anthropic`, `openrouter`, `zen`, `go`, `ollama`, `lmstudio`, `mock`.

### Ошибка: "Port 8765 already in use"

**Решение:**
```bash
# Использовать другой порт
uv run codelab serve --port 9000

# Или найти процесс занимающий порт
lsof -i :8765
kill <PID>
```

### Сервер запускается но клиент не подключается

**Проверка:**
1. Сервер запущен: `curl http://127.0.0.1:8765/`
2. Порт правильный: `uv run codelab connect --port 8765`
3. Firewall не блокирует: `telnet 127.0.0.1 8765`

## Следующие шаги

- [Настройка LLM провайдеров](../user-guide/11-llm-providers.md) — детальная настройка всех провайдеров
- [TOML конфигурация](../user-guide/13-toml-configuration.md) — полное руководство по TOML
- [Fallback и устойчивость](../user-guide/12-fallback-resilience.md) — настройка fallback цепочек
- [Разрешения](../user-guide/05-permissions.md) — управление доступами агента
- [Инструменты](../user-guide/07-tools.md) — файловая система и терминал

## См. также

- [Требования](01-requirements.md) — системные требования
- [Установка](02-installation.md) — детальная установка
- [CLI команды](../reference/01-cli.md) — справочник команд
- [Переменные окружения](../reference/03-environment.md) — все CODELAB_* переменные
