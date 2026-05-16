"""CLI-точка входа ACP-сервера.

Модуль читает аргументы запуска и поднимает WS транспорт.

Пример использования:
    codelab serve --host 127.0.0.1 --port 8080
    codelab serve --log-level DEBUG
    codelab serve --log-level INFO --log-json
    codelab serve --log-level DEBUG --log-file default
    codelab serve --log-level INFO --log-json --log-file /var/log/codelab-server.log
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

import structlog
from dotenv import load_dotenv

from codelab.shared.logging import setup_logging

from .config import AppConfig
from .http_server import ACPHttpServer
from .storage import CachedSessionStorage, InMemoryStorage, JsonFileStorage, SessionStorage


def parse_storage_arg(storage_arg: str) -> SessionStorage:
    """Парсит аргумент --storage и создаёт соответствующий backend.

    Поддерживаемые форматы:
    - 'memory' — In-memory хранилище (default)
    - 'json:/path/to/dir' — JSON файловое хранилище

    Args:
        storage_arg: Строка с аргументом хранилища.

    Returns:
        Объект SessionStorage соответствующей реализации.

    Raises:
        ValueError: При неизвестном формате аргумента.

    Пример:
        storage = parse_storage_arg("json:~/.acp/sessions")
    """
    # Получаем logger для логирования инициализации хранилища
    logger = structlog.get_logger()

    if storage_arg == "memory":
        logger.debug("creating in-memory storage backend")
        return InMemoryStorage()
    elif storage_arg.startswith("json:"):
        path_str = storage_arg[5:]  # Убрать префикс "json:"
        path = Path(path_str).expanduser()
        logger.debug("creating json file storage backend", path=str(path))
        storage = JsonFileStorage(path)
        logger.debug("json file storage initialized", path=str(path))
        return storage
    else:
        logger.error("unknown storage backend format", storage_arg=storage_arg)
        raise ValueError(f"Unknown storage backend: {storage_arg}")


def describe_storage(storage: SessionStorage) -> str:
    """Возвращает человеко-читаемое описание backend и его пути.

    Пример:
        description = describe_storage(storage)
    """

    if isinstance(storage, JsonFileStorage):
        return f"json:{storage.base_path.resolve()}"
    return "memory"


def run_server() -> None:
    """Запускает ACP WS-сервер из аргументов командной строки.

    Загружает переменные окружения из .env файла в текущей директории.
    Приоритет: CLI аргументы > .env переменные > значения по умолчанию

    Пример .env файла:
        CODELAB_LLM_PROVIDER=openai
        CODELAB_LLM_MODEL=gpt-4-turbo
        CODELAB_LLM_API_KEY=sk-...
        CODELAB_LLM_TEMPERATURE=0.9
        CODELAB_SYSTEM_PROMPT=Your custom prompt

    Пример использования:
        # Загружает .env из текущей директории
        run_server()
    """
    # Инициализируем базовое логирование для вывода ошибок инициализации
    logger = setup_logging(level="INFO", json_format=False)
    logger.debug("codelab-server starting up")

    # Загружаем переменные окружения из .env файла если он существует
    load_dotenv()
    logger.debug("environment variables loaded from .env")

    parser = argparse.ArgumentParser(prog="codelab serve")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument(
        "--require-auth",
        action="store_true",
        help="Требовать authenticate перед session/new и session/load",
    )
    parser.add_argument(
        "--auth-api-key",
        default=None,
        help=(
            "Локальный API key для authenticate (передается клиентом в params.apiKey); "
            "можно также задать через переменную среды ACP_SERVER_API_KEY"
        ),
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Уровень логирования (DEBUG, INFO, WARNING, ERROR). По умолчанию INFO.",
    )
    parser.add_argument(
        "--log-json",
        action="store_true",
        help="Использовать JSON формат для логов (для production). По умолчанию консольный формат.",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Путь к файлу логов. 'default' для ~/.codelab/logs/codelab-server.log",
    )
    parser.add_argument(
        "--storage",
        default="memory",
        help="Storage backend: 'memory' (default) или 'json:/path/to/dir' для persistence",
    )
    parser.add_argument(
        "--llm-provider",
        default=None,
        help="LLM провайдер (openai, mock). Переопределяет ACP_LLM_PROVIDER",
    )
    parser.add_argument(
        "--llm-model",
        default=None,
        help="Модель LLM. Переопределяет ACP_LLM_MODEL",
    )
    parser.add_argument(
        "--llm-api-key",
        default=None,
        help="API ключ для LLM. Переопределяет ACP_LLM_API_KEY",
    )
    parser.add_argument(
        "--llm-base-url",
        default=None,
        help="Base URL для LLM провайдера. Переопределяет ACP_LLM_BASE_URL",
    )
    parser.add_argument(
        "--llm-temperature",
        type=float,
        default=None,
        help="Temperature для LLM (0.0-1.0). Переопределяет ACP_LLM_TEMPERATURE",
    )
    parser.add_argument(
        "--llm-max-tokens",
        type=int,
        default=None,
        help="Максимум токенов для LLM. Переопределяет ACP_LLM_MAX_TOKENS",
    )
    parser.add_argument(
        "--system-prompt",
        default=None,
        help="Системный промпт для агента. Переопределяет ACP_SYSTEM_PROMPT",
    )
    args = parser.parse_args()
    logger.debug("command line arguments parsed")

    # Инициализируем логирование перед запуском сервера с поддержкой сохранения в файл
    logger = setup_logging(
        level=args.log_level,
        json_format=args.log_json,
        log_file=args.log_file or None,
    )
    logger.info(
        "logging configured",
        level=args.log_level,
        json_format=args.log_json,
        log_file=args.log_file or "console only",
    )

    # Загружаем конфигурацию из переменных окружения
    logger.debug("loading application configuration")
    config = AppConfig.from_env()
    logger.debug(
        "application configuration loaded",
        llm_provider=config.llm.provider,
        has_api_key=bool(config.llm.api_key),
    )

    # Переопределяем конфиг из аргументов командной строки если указаны
    cli_overrides = []
    if args.llm_provider:
        config.llm.provider = args.llm_provider
        cli_overrides.append(f"llm_provider={args.llm_provider}")
    if args.llm_model:
        config.llm.model = args.llm_model
        cli_overrides.append(f"llm_model={args.llm_model}")
    if args.llm_api_key:
        config.llm.api_key = args.llm_api_key
        cli_overrides.append("llm_api_key=***")
    if args.llm_base_url:
        config.llm.base_url = args.llm_base_url
        cli_overrides.append(f"llm_base_url={args.llm_base_url}")
    if args.llm_temperature is not None:
        config.llm.temperature = args.llm_temperature
        cli_overrides.append(f"llm_temperature={args.llm_temperature}")
    if args.llm_max_tokens is not None:
        config.llm.max_tokens = args.llm_max_tokens
        cli_overrides.append(f"llm_max_tokens={args.llm_max_tokens}")
    if args.system_prompt:
        config.agent.system_prompt = args.system_prompt
        cli_overrides.append("system_prompt=***")

    if cli_overrides:
        logger.debug("configuration overridden", overrides=", ".join(cli_overrides))

    # Обработка аутентификации
    logger.debug("processing authentication configuration", require_auth=args.require_auth)
    auth_api_key = args.auth_api_key
    if not isinstance(auth_api_key, str) or not auth_api_key:
        env_api_key = os.getenv("ACP_SERVER_API_KEY")
        auth_api_key = env_api_key if isinstance(env_api_key, str) and env_api_key else None
        if env_api_key:
            logger.debug("auth api key loaded from environment")

    if auth_api_key:
        logger.debug("authentication api key configured")
    elif args.require_auth:
        logger.warning("authentication required but no api key configured")

    # Парсим и создаём storage backend, оборачиваем в LRU-кэш
    logger.debug("initializing storage backend", storage_type=args.storage)
    raw_storage = parse_storage_arg(args.storage)
    storage = CachedSessionStorage(
        backend=raw_storage,
        max_size=config.storage.session_cache_size,
    )
    logger.info(
        "storage_backend_initialized",
        storage_type=type(raw_storage).__name__,
        storage_target=describe_storage(raw_storage),
        session_cache_size=config.storage.session_cache_size,
    )

    # Создаём и запускаем сервер
    logger.debug(
        "initializing http server",
        host=args.host,
        port=args.port,
        require_auth=args.require_auth,
    )
    server = ACPHttpServer(
        host=args.host,
        port=args.port,
        require_auth=args.require_auth,
        auth_api_key=auth_api_key,
        storage=storage,
        config=config,
    )
    logger.debug("http server initialized, preparing to start")

    # Запускаем сервер
    try:
        logger.info("starting codelab-server", host=args.host, port=args.port)
        asyncio.run(server.run())
    except KeyboardInterrupt:
        logger.info("server interrupted by user")
    except Exception as e:
        logger.error("server error", error=str(e), exc_info=True)
        raise
