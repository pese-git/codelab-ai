# Установка

> Пошаговая инструкция по установке CodeLab.

## Быстрая установка

```bash
# 1. Клонирование репозитория
git clone https://github.com/your-org/acp-protocol.git
cd acp-protocol/codelab

# 2. Установка зависимостей
uv sync

# 3. Проверка установки
uv run codelab --help
```

## Варианты установки

CodeLab поддерживает несколько конфигураций через optional dependencies.

### Базовая установка

Минимальная установка для разработки:

```bash
uv sync
```

### С поддержкой LLM-сервера

Для работы с реальными LLM (OpenAI, Anthropic):

```bash
uv sync --extra server
```

### С TUI-клиентом

Для терминального интерфейса:

```bash
uv sync --extra tui
```

### С Web UI

Для браузерного интерфейса:

```bash
uv sync --extra web
```

### Полная установка

Все компоненты:

```bash
uv sync --extra full
```

### Для разработки

Включает инструменты разработки (pytest, ruff, ty):

```bash
uv sync --extra dev
```

## Конфигурация

### Создание файла конфигурации

```bash
# Копирование примера
cp .env.example .env

# Редактирование
nano .env  # или используйте любой редактор
```

### Основные переменные окружения

```bash
# .env файл

# LLM провайдер (openai, anthropic, mock)
CODELAB_LLM_PROVIDER=openai

# API ключ OpenAI
OPENAI_API_KEY=sk-your-key-here

# Модель LLM
CODELAB_LLM_MODEL=gpt-4o

# Порт сервера
CODELAB_PORT=8765

# Хост сервера
CODELAB_HOST=127.0.0.1

# Уровень логирования (DEBUG, INFO, WARNING, ERROR)
CODELAB_LOG_LEVEL=INFO
```

### Таблица конфигурации

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `CODELAB_LLM_PROVIDER` | Провайдер LLM | `mock` |
| `OPENAI_API_KEY` | API ключ OpenAI | — |
| `ANTHROPIC_API_KEY` | API ключ Anthropic | — |
| `CODELAB_LLM_MODEL` | Модель LLM | `gpt-4o` |
| `CODELAB_PORT` | Порт сервера | `8765` |
| `CODELAB_HOST` | Хост сервера | `127.0.0.1` |
| `CODELAB_LOG_LEVEL` | Уровень логов | `INFO` |

## Домашняя директория

При первом запуске создаётся структура в `~/.codelab/`:

```
~/.codelab/
├── config/   # Конфигурационные файлы
├── logs/     # Файлы логов (codelab.log)
├── data/     # Сессии, история
└── cache/    # Кэш MCP и временные данные
```

## Проверка установки

### Проверка CLI

```bash
uv run codelab --help
```

Ожидаемый вывод:
```
Usage: codelab [OPTIONS] COMMAND [ARGS]...

  CodeLab - ACP server and client

Commands:
  serve    Start the ACP server
  connect  Connect TUI client to server
```

### Проверка сервера

```bash
uv run codelab serve --port 8765
```

Ожидаемый вывод:
```
INFO     Server starting on 127.0.0.1:8765
INFO     Web UI available at http://127.0.0.1:8765/
INFO     WebSocket endpoint: ws://127.0.0.1:8765/ws
```

## Обновление

```bash
# Получение обновлений
cd acp-protocol
git pull origin main

# Переустановка зависимостей
cd codelab
uv sync
```

## Удаление

```bash
# Удаление репозитория
rm -rf acp-protocol

# Удаление домашней директории (опционально)
rm -rf ~/.codelab
```

## Решение проблем

### Ошибка "uv: command not found"

```bash
# Переустановка uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc  # или ~/.zshrc
```

### Ошибка "Python 3.12 required"

```bash
# macOS
brew install python@3.12

# Ubuntu
sudo apt install python3.12
```

### Ошибка при uv sync

```bash
# Очистка кэша и повторная установка
uv cache clean
uv sync --reinstall
```

### Порт уже занят

```bash
# Проверка занятости порта
lsof -i :8765

# Использование другого порта
uv run codelab serve --port 8766
```

## Следующие шаги

- [Быстрый старт](03-quickstart.md) — первый запуск и основы работы
- [Первый проект](04-first-project.md) — практический пример
- [Интеграция с Zed IDE](../user-guide/10-zed-ide-integration.md) — настройка в Zed IDE
