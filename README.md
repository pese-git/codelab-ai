# CodeLab

> Унифицированная реализация [Agent Client Protocol (ACP)](doc/Agent%20Client%20Protocol/get-started/01-Introduction.md) — AI-агент и клиент в едином Python-пакете.

## Что такое CodeLab?

CodeLab — это полнофункциональная реализация протокола ACP для взаимодействия AI-агентов с редакторами кода. Проект объединяет:

- **ACP-сервер** — интеллектуальный агент с поддержкой OpenAI GPT-4
- **TUI-клиент** — терминальный интерфейс на базе Textual
- **Web UI** — браузерный интерфейс для удаленной работы
- **stdio транспорт** — основной транспорт ACP (stdin/stdout JSON-RPC)

## Быстрый старт

```bash
# Установка зависимостей
cd codelab && uv sync

# Локальный режим (stdio транспорт, сервер как subprocess)
uv run codelab

# Или сервер + клиент отдельно
uv run codelab serve --port 8080        # WebSocket сервер
uv run codelab connect --port 8080      # TUI клиент

# stdio транспорт (для IDE plugins)
uv run codelab serve --stdio            # сервер в stdio режиме
uv run codelab connect --stdio          # клиент запускает агент как subprocess
```

## Документация

| Раздел | Описание |
|--------|----------|
| [Введение](doc/product/overview/01-introduction.md) | Обзор возможностей и архитектуры |
| [Быстрый старт](doc/product/getting-started/03-quickstart.md) | Пошаговая инструкция запуска |
| [Руководство пользователя](doc/product/user-guide/01-tui-client.md) | Работа с TUI-клиентом |
| [Руководство разработчика](doc/product/developer-guide/01-architecture.md) | Архитектура и разработка |
| [Справочник CLI](doc/product/reference/01-cli.md) | Команды и опции |
| [ACP Protocol](doc/Agent%20Client%20Protocol/) | Официальная спецификация протокола |

## Структура проекта

```
acp-protocol/
├── codelab/                    # Основной Python-пакет
│   ├── src/codelab/
│   │   ├── client/             # ACP-клиент (Clean Architecture)
│   │   │   ├── domain/         # Сущности и интерфейсы
│   │   │   ├── application/    # Use Cases, State Machine
│   │   │   ├── infrastructure/ # DI, Transport, Handlers
│   │   │   ├── presentation/   # ViewModels (MVVM)
│   │   │   └── tui/            # Textual UI компоненты
│   │   ├── server/             # ACP-сервер
│   │   │   ├── protocol/       # Обработчики методов ACP
│   │   │   ├── agent/          # LLM-агент (OpenAI)
│   │   │   ├── tools/          # Инструменты (fs, terminal)
│   │   │   ├── storage/        # Хранилище сессий
│   │   │   └── llm/            # LLM-провайдеры
│   │   ├── shared/             # Общие модули
│   │   └── cli.py              # CLI точка входа
│   └── tests/                  # Тесты (~1800 тестов)
├── doc/
│   ├── product/                # Продуктовая документация
│   ├── architecture/           # Архитектурные документы
│   └── Agent Client Protocol/  # Спецификация ACP (не изменять!)
└── Makefile                    # Команды сборки и проверок
```

## Проверки

```bash
# Полный набор проверок
make check

# Или вручную
cd codelab
uv run ruff check .
uv run ty check
uv run python -m pytest
```

## Требования

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — менеджер пакетов

## Лицензия

MIT License
