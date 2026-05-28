"""Единый CLI для CodeLab.

Режимы работы:
- local (по умолчанию): запускает сервер на localhost и TUI
- serve: запускает только сервер с WebSocket API
- connect: запускает только TUI клиент

Примеры использования:
    codelab                                      # Локальный режим (сервер + TUI)
    codelab serve --port 4096 --host 0.0.0.0     # Режим сервера (WebSocket API)
    codelab connect --host 127.0.0.1 --port 4096 # Режим клиента (TUI)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from dotenv import load_dotenv

if TYPE_CHECKING:
    pass

# Настройка логирования для CLI
logger = structlog.get_logger("codelab.cli")

# Порт по умолчанию для WebSocket сервера (читается из env с fallback)
DEFAULT_PORT = int(os.getenv("CODELAB_PORT", "8765"))
DEFAULT_HOST = os.getenv("CODELAB_HOST", "127.0.0.1")

# Домашняя директория CodeLab (из env или ~/.codelab)
_codelab_home_env = os.getenv("CODELAB_HOME")
CODELAB_HOME = (
    Path(_codelab_home_env).expanduser() if _codelab_home_env else Path.home() / ".codelab"
)

# Шаблон дефолтного .env файла для автоматической генерации при первом запуске
DEFAULT_ENV_TEMPLATE = """# CodeLab Configuration
# =====================
# Этот файл создан автоматически при первом запуске.
# Измените значения под ваши нужды.

# === LLM Провайдер ===
# Тип провайдера: openai, anthropic или mock
CODELAB_LLM_PROVIDER=mock

# API ключ (требуется для openai/anthropic)
# CODELAB_LLM_API_KEY=sk-your-key-here

# Base URL для LLM провайдера (опционально)
# CODELAB_LLM_BASE_URL=https://api.openai.com/v1

# Модель LLM (по умолчанию: gpt-4o)
CODELAB_LLM_MODEL=gpt-4o

# Temperature (0.0-1.0)
CODELAB_LLM_TEMPERATURE=0.7

# Максимальное количество токенов
CODELAB_LLM_MAX_TOKENS=8192

# === Сервер ===
CODELAB_PORT=8765
CODELAB_HOST=127.0.0.1

# === Логирование ===
# Уровень: DEBUG, INFO, WARNING, ERROR
CODELAB_LOG_LEVEL=INFO
"""


def ensure_home_directory() -> None:
    """Создать домашнюю директорию ~/.codelab/ с поддиректориями.

    Создаёт структуру директорий для хранения конфигурации,
    логов, данных сессий и кэша приложения.

    Структура:
        ~/.codelab/
        ├── config/       # Конфигурационные файлы
        ├── logs/         # Файлы логов
        ├── data/         # Данные приложения
        │   ├── sessions/ # Сессии сервера (JSON файлы)
        │   ├── history/  # История чатов клиента
        │   └── policies/ # Глобальные политики разрешений
        └── cache/        # Кэш MCP и временные данные
    """
    directories = [
        CODELAB_HOME,
        CODELAB_HOME / "config",  # Конфигурационные файлы
        CODELAB_HOME / "logs",  # Файлы логов
        CODELAB_HOME / "data",  # Данные приложения
        CODELAB_HOME / "data" / "sessions",  # Сессии сервера (JSON файлы)
        CODELAB_HOME / "data" / "history",  # История чатов клиента
        CODELAB_HOME / "data" / "policies",  # Глобальные политики разрешений
        CODELAB_HOME / "cache",  # Кэш MCP и временные данные
    ]

    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

    # Генерация глобального .env если не существует и нет codelab.toml
    global_env = CODELAB_HOME / "config" / ".env"
    global_toml = CODELAB_HOME / "codelab.toml"
    if not global_env.exists() and not global_toml.exists():
        global_env.write_text(DEFAULT_ENV_TEMPLATE, encoding="utf-8")
        print(f"✅ Создан файл конфигурации: {global_env}")
        print("💡 Отредактируйте его и добавьте CODELAB_LLM_API_KEY для работы с LLM.")


def _configure_logging(verbose: bool = False, console_output: bool = False) -> None:
    """Настраивает structlog для CLI с записью логов в файл.

    Args:
        verbose: Включить подробное логирование (DEBUG уровень)
        console_output: Выводить логи в консоль (для режима serve)
    """
    # Импортируем setup_logging из shared модуля
    from codelab.shared.logging import setup_logging

    # Приоритет: флаг --verbose > CODELAB_LOG_LEVEL > INFO
    env_log_level = os.getenv("CODELAB_LOG_LEVEL", "INFO").upper()
    level = "DEBUG" if verbose else env_log_level

    # Используем setup_logging из shared модуля с записью в файл
    # Логи сохраняются в ~/.codelab/logs/codelab.log с ротацией
    # Для режима serve включаем вывод в консоль
    setup_logging(
        level=level,
        json_format=False,  # Человекочитаемый формат
        log_file="default",  # ~/.codelab/logs/codelab.log
        console_output=console_output,  # Вывод в консоль для serve режима
    )


def main() -> None:
    """Главная точка входа CLI.

    Парсит аргументы командной строки и запускает соответствующий режим.
    
    Загрузка переменных окружения (порядок приоритета, от низкого к высокому):
    1. ~/.codelab/config/.env (глобальные настройки)
    2. .env в текущей директории (локальный проект)
    3. Переменные окружения системы (самый высокий приоритет)
    """
    # Загружаем .env файлы (load_dotenv не перезаписывает существующие переменные)
    # Сначала загружаем глобальный конфиг, затем локальный для правильного приоритета
    home_env = CODELAB_HOME / "config" / ".env"
    if home_env.exists():
        load_dotenv(home_env)
    
    # Локальный .env перезаписывает глобальный (override=True)
    load_dotenv(override=True)
    
    parser = argparse.ArgumentParser(
        prog="codelab",
        description="CodeLab - AI-powered coding assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  codelab                           Локальный режим (сервер + TUI)
  codelab serve --port 4096         Запустить только сервер
  codelab connect --host server.local --port 4096  Подключиться к серверу
        """,
    )

    # Глобальные опции
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Включить подробное логирование",
    )

    # Подкоманды
    subparsers = parser.add_subparsers(dest="command", help="Режим работы")

    # codelab serve - режим сервера
    serve_parser = subparsers.add_parser(
        "serve",
        help="Запустить сервер (WebSocket или stdio)",
        description="Запускает ACP сервер для удалённых клиентов",
    )
    serve_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help=f"Адрес для прослушивания (по умолчанию: {DEFAULT_HOST})",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Порт для прослушивания (по умолчанию: {DEFAULT_PORT})",
    )
    serve_parser.add_argument(
        "--stdio",
        action="store_true",
        help="Запустить stdio транспорт (чтение stdin, запись stdout)",
    )
    serve_parser.add_argument(
        "--no-web",
        action="store_true",
        help="Отключить Web UI на корневом пути /",
    )
    serve_parser.add_argument(
        "--trace-messages",
        action="store_true",
        default=False,
        help="Включить детальное логирование всех JSON-RPC сообщений",
    )
    serve_parser.add_argument(
        "--require-auth",
        action="store_true",
        help="Требовать аутентификацию перед session/new и session/load",
    )
    serve_parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        help="Уровень логирования (переопределяет CODELAB_LOG_LEVEL и -v)",
    )

    # codelab connect - режим клиента
    connect_parser = subparsers.add_parser(
        "connect",
        help="Подключиться к серверу (WebSocket или stdio)",
        description="Запускает TUI клиент и подключается к ACP серверу",
    )
    connect_parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Адрес сервера (по умолчанию: {DEFAULT_HOST})",
    )
    connect_parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Порт сервера (по умолчанию: {DEFAULT_PORT})",
    )
    connect_parser.add_argument(
        "--cwd",
        type=str,
        default=None,
        help="Рабочая директория проекта (по умолчанию: текущая)",
    )
    connect_parser.add_argument(
        "--stdio",
        action="store_true",
        help="Запустить агент как subprocess через stdio транспорт",
    )
    connect_parser.add_argument(
        "--agent-command",
        type=str,
        default=None,
        help="Команда для запуска агента (по умолчанию: codelab serve --stdio)",
    )
    connect_parser.add_argument(
        "--theme",
        type=str,
        choices=["light", "dark"],
        default=None,
        help="Тема TUI (light/dark, по умолчанию: из конфига)",
    )
    connect_parser.add_argument(
        "--receive-timeout",
        type=float,
        default=None,
        help="Таймаут ожидания ответа от сервера в секундах (по умолчанию: 60)",
    )

    args = parser.parse_args()

    # Создаём домашнюю директорию ~/.codelab/ с поддиректориями
    ensure_home_directory()

    # Настраиваем логирование
    # Для режима serve логирование настраивается в run_serve() (с поддержкой trace_file)
    is_serve_mode = args.command == "serve"
    if not is_serve_mode:
        _configure_logging(
            verbose=getattr(args, "verbose", False),
            console_output=False,
        )

    try:
        if args.command == "serve":
            run_serve(args)
        elif args.command == "connect":
            run_connect(args)
        else:
            # Локальный режим по умолчанию (без подкоманды)
            run_local(args)
    except KeyboardInterrupt:
        # Graceful shutdown при Ctrl+C
        logger.info("shutdown_requested", reason="KeyboardInterrupt")
        sys.exit(0)


def _get_log_level_for_serve(args: argparse.Namespace) -> str:
    """Определить уровень логирования для режима serve.

    Приоритет:
    1. --log-level (если указан)
    2. --verbose/-v (DEBUG если True)
    3. CODELAB_LOG_LEVEL (из env)
    4. INFO (по умолчанию)
    """
    # Явный --log-level имеет высший приоритет
    log_level_arg = getattr(args, "log_level", None)
    if log_level_arg:
        return log_level_arg

    # Флаг --verbose
    if getattr(args, "verbose", False):
        return "DEBUG"

    # Переменная окружения
    env_log_level = os.getenv("CODELAB_LOG_LEVEL", "INFO").upper()
    return env_log_level


def run_local(args: argparse.Namespace) -> None:
    """Локальный режим: запускает сервер как subprocess через stdio.

    Сервер запускается как subprocess, TUI клиент подключается через
    stdio транспорт. При завершении TUI сервер автоматически останавливается.

    Args:
        args: Аргументы командной строки
    """
    cwd = os.getcwd()

    logger.info("starting_local_mode", transport="stdio", cwd=cwd)

    # Запускаем TUI с stdio транспортом
    _run_tui_app(
        host="127.0.0.1",
        port=DEFAULT_PORT,
        cwd=cwd,
        transport_mode="stdio",
        stdio_command="codelab",
        stdio_args=["serve", "--stdio"],
    )


def run_serve(args: argparse.Namespace) -> None:
    """Режим сервера: запускает WebSocket или stdio API.

    Args:
        args: Аргументы командной строки с host, port, stdio, no_web, trace_messages
    """
    from codelab.server.config import AppConfig
    from codelab.server.http_server import ACPHttpServer
    from codelab.server.storage.json_file import JsonFileStorage

    # Настраиваем логирование с учетом --log-level
    log_level = _get_log_level_for_serve(args)
    trace_messages = getattr(args, "trace_messages", False)
    require_auth = getattr(args, "require_auth", False)

    from codelab.shared.logging import setup_logging

    setup_logging(
        level=log_level,
        json_format=False,
        log_file="default",
        console_output=True,  # В serve режиме всегда выводим в консоль
    )

    host = args.host
    port = args.port
    enable_web = not getattr(args, "no_web", False)
    use_stdio = getattr(args, "stdio", False)

    # Создаём хранилище сессий
    sessions_dir = CODELAB_HOME / "data" / "sessions"
    storage = JsonFileStorage(sessions_dir)

    # Загружаем конфигурацию
    config = AppConfig.from_env()

    # Обработка аутентификации
    auth_api_key = os.getenv("ACP_SERVER_API_KEY")

    if use_stdio:
        # Stdio режим
        logger.info("starting_server_mode", transport="stdio")
        from codelab.server.transport.stdio_runner import run_stdio_server

        try:
            asyncio.run(
                run_stdio_server(
                    storage=storage,
                    config=config,
                    require_auth=require_auth,
                    auth_api_key=auth_api_key,
                    trace_messages=trace_messages,
                )
            )
        except KeyboardInterrupt:
            logger.info("server_shutdown", reason="KeyboardInterrupt")
    else:
        # WebSocket режим
        logger.info(
            "starting_server_mode",
            host=host,
            port=port,
            enable_web=enable_web,
            trace_messages=trace_messages,
        )
        logger.info(
            "endpoints_available",
            ws_api=f"ws://{host}:{port}/acp/ws",
            web_ui=f"http://{host}:{port}/" if enable_web else "disabled",
        )

        server = ACPHttpServer(
            host=host,
            port=port,
            enable_web=enable_web,
            storage=storage,
            config=config,
            require_auth=require_auth,
            auth_api_key=auth_api_key,
            trace_messages=trace_messages,
        )

        try:
            asyncio.run(server.run())
        except KeyboardInterrupt:
            logger.info("server_shutdown", reason="KeyboardInterrupt")


def run_connect(args: argparse.Namespace) -> None:
    """Режим клиента: подключается к серверу через WebSocket или stdio.

    Args:
        args: Аргументы командной строки с host, port, cwd, stdio и agent_command
    """
    host = args.host
    port = args.port
    cwd = getattr(args, "cwd", None)
    use_stdio = getattr(args, "stdio", False)
    agent_command = getattr(args, "agent_command", None)
    theme = getattr(args, "theme", None)
    receive_timeout = getattr(args, "receive_timeout", None)

    if use_stdio:
        logger.info(
            "starting_connect_mode",
            transport="stdio",
            agent_command=agent_command or "codelab serve --stdio",
            cwd=cwd,
        )
        stdio_cmd = agent_command or "codelab"
        stdio_args_list = stdio_cmd.split()
        if "--stdio" not in stdio_args_list:
            stdio_args_list.append("--stdio")
        _run_tui_app(
            host=host,
            port=port,
            cwd=cwd,
            transport_mode="stdio",
            stdio_command=stdio_args_list[0],
            stdio_args=[str(arg) for arg in stdio_args_list[1:]],
            theme=theme,
            receive_timeout=receive_timeout,
        )
    else:
        logger.info("starting_connect_mode", host=host, port=port)
        _run_tui_app(host=host, port=port, cwd=cwd, theme=theme, receive_timeout=receive_timeout)


def _run_tui_app(
    *,
    host: str,
    port: int,
    cwd: str | None = None,
    transport_mode: str = "websocket",
    stdio_command: str | None = None,
    stdio_args: list[str] | None = None,
    theme: str | None = None,
    receive_timeout: float | None = None,
) -> None:
    """Запускает TUI приложение.

    Args:
        host: Адрес сервера
        port: Порт сервера
        cwd: Рабочая директория (опционально)
        transport_mode: Режим транспорта ("websocket" или "stdio")
        stdio_command: Команда для запуска агента (для stdio режима)
        stdio_args: Аргументы команды (для stdio режима)
        theme: Тема интерфейса ("light" или "dark")
        receive_timeout: Таймаут ожидания ответа от сервера в секундах
    """
    from codelab.client.tui.app import run_tui_app

    logger.info("starting_tui", host=host, port=port, cwd=cwd or "(current)", theme=theme)

    run_tui_app(
        host=host,
        port=port,
        cwd=cwd,
        transport_mode=transport_mode,
        stdio_command=stdio_command,
        stdio_args=stdio_args,
        theme=theme,
        receive_timeout=receive_timeout,
    )

    logger.info("tui_exited")


if __name__ == "__main__":
    main()
