"""Тесты для модуля логирования."""

import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import structlog

from codelab.shared.logging import reset_logging, setup_logging


def setup_function() -> None:
    """Сбрасываем состояние логирования перед каждым тестом."""
    reset_logging()


def test_setup_logging_default() -> None:
    """Тест настройки логирования с параметрами по умолчанию."""
    logger = setup_logging()
    # Функция возвращает lazy proxy logger, проверяем что он не None
    assert logger is not None


def test_setup_logging_debug_level() -> None:
    """Тест настройки уровня DEBUG."""
    logger = setup_logging(level="DEBUG")
    # Функция возвращает lazy proxy logger, проверяем что он не None
    assert logger is not None


def test_setup_logging_json_format() -> None:
    """Тест настройки JSON формата."""
    logger = setup_logging(json_format=True)
    # Функция возвращает lazy proxy logger, проверяем что он не None
    assert logger is not None


def test_setup_logging_console_format() -> None:
    """Тест настройки консольного формата."""
    logger = setup_logging(json_format=False)
    # Функция возвращает lazy proxy logger, проверяем что он не None
    assert logger is not None


def test_setup_logging_with_file() -> None:
    """Тест настройки логирования с сохранением в файл."""
    with TemporaryDirectory() as tmpdir:
        log_file = str(Path(tmpdir) / "test.log")
        logger = setup_logging(log_file=log_file)
        assert logger is not None
        # Проверяем что файл создан
        assert Path(log_file).exists()


def test_setup_logging_with_default_file_path() -> None:
    """Тест настройки логирования с путем по умолчанию 'default'."""
    logger = setup_logging(log_file="default")
    assert logger is not None
    # Проверяем что директория создана
    home = Path.home()
    log_dir = home / ".codelab" / "logs"
    assert log_dir.exists()
    # Проверяем что файл создан с PID в имени
    pid = os.getpid()
    log_file = log_dir / f"codelab-{pid}.log"
    assert log_file.exists()


def test_setup_logging_idempotent() -> None:
    """Повторный вызов setup_logging() не вызывает ошибок.

    Функция должна быть идемпотентной — второй вызов просто возвращает
    уже настроенный logger без повторной конфигурации handlers.
    """
    logger1 = setup_logging(level="INFO")
    logger2 = setup_logging(level="DEBUG")  # второй вызов
    assert logger1 is not None
    assert logger2 is not None


def test_setup_logging_returns_logger_on_second_call() -> None:
    """Повторный вызов возвращает рабочий logger.

    После первого вызова setup_logging() второй вызов должен вернуть
    рабочий logger без ошибок.
    """
    setup_logging(level="INFO")
    logger = setup_logging(level="DEBUG")
    # Должен вернуть logger без ошибок
    logger.info("test_message_idempotent")  # не должно вызывать исключений


def test_no_duplicate_log_entries() -> None:
    """Между двумя вызовами setup_logging() не создаётся дублирующих записей.

    Проверяем что guard-флаг предотвращает добавление дублирующих
    handlers в root logger.
    """
    with TemporaryDirectory() as tmpdir:
        log_file = str(Path(tmpdir) / "test_idempotent.log")
        # Первый вызов
        setup_logging(level="INFO", log_file=log_file)
        logger = structlog.get_logger("codelab")
        logger.info("single_entry_test")

        # Flush handlers чтобы запись точно попала в файл
        for handler in logging.getLogger().handlers:
            handler.flush()

        # Второй вызов — не должен добавить ещё один handler
        setup_logging(level="INFO", log_file=log_file)
        logger.info("after_second_setup")

        # Flush handlers
        for handler in logging.getLogger().handlers:
            handler.flush()

        content = Path(log_file).read_text()
        # Проверяем что каждая запись встречается один раз
        assert content.count("single_entry_test") == 1
        assert content.count("after_second_setup") == 1


def test_setup_logging_default_creates_pid_file() -> None:
    """Проверяет что файл создаётся с PID в имени при log_file='default'."""
    pid = os.getpid()
    log_dir = Path.home() / ".codelab" / "logs"
    expected_file = log_dir / f"codelab-{pid}.log"

    # Удаляем файл если существует (для чистоты теста)
    expected_file.unlink(missing_ok=True)

    logger = setup_logging(log_file="default")
    assert logger is not None
    assert expected_file.exists()


def test_pid_in_log_entries() -> None:
    """Проверяет что PID присутствует в каждой записи лога."""
    with TemporaryDirectory() as tmpdir:
        log_file = str(Path(tmpdir) / "test_pid.log")
        setup_logging(level="INFO", log_file=log_file)
        logger = structlog.get_logger("codelab")
        logger.info("test_pid_entry")

        # Flush handlers
        for handler in logging.getLogger().handlers:
            handler.flush()

        content = Path(log_file).read_text()
        # PID должен быть в записи
        assert str(os.getpid()) in content
