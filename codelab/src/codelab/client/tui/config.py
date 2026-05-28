"""Конфигурация TUI-клиента и ее локальное хранение.

Поддерживает загрузку конфигурации из нескольких источников с приоритетом:
JSON < TOML global < TOML project < Environment variable < CLI flag.
"""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import structlog

logger = structlog.get_logger(__name__)

type TUITheme = Literal["light", "dark"]


@dataclass(slots=True)
class TUIConfig:
    """Пользовательская конфигурация запуска TUI."""

    host: str = "127.0.0.1"
    port: int = 8765
    theme: TUITheme = "light"
    receive_timeout: float = 60.0


class TUIConfigStore:
    """Загружает и сохраняет конфигурацию TUI из JSON и TOML источников.

    Приоритет источников (от низшего к высшему):
    1. JSON файл (~/.codelab/tui_config.json)
    2. TOML global (~/.codelab/codelab.toml)
    3. TOML project (./codelab.toml, ./codelab.local.toml)
    """

    def __init__(self, file_path: Path | None = None) -> None:
        """Настраивает путь хранения конфигурации в домашней директории."""

        self._file_path = file_path or (Path.home() / ".codelab" / "tui_config.json")

    def load(self) -> TUIConfig:
        """Загружает конфигурацию из JSON файла или возвращает значения по умолчанию."""

        if not self._file_path.exists():
            return TUIConfig()

        try:
            payload = json.loads(self._file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return TUIConfig()

        return self._from_payload(payload)

    def load_with_priority(
        self,
        *,
        cli_theme: TUITheme | None = None,
        env_theme: TUITheme | None = None,
        cli_receive_timeout: float | None = None,
        env_receive_timeout: float | None = None,
    ) -> TUIConfig:
        """Загружает конфигурацию из всех источников с учётом приоритета.

        Приоритет: CLI flag > Env variable > TOML chain > JSON config.

        Args:
            cli_theme: Тема из CLI флага --theme (наивысший приоритет)
            env_theme: Тема из CODELAB_THEME env variable
            cli_receive_timeout: Таймаут из CLI флага --receive-timeout
            env_receive_timeout: Таймаут из CODELAB_RECEIVE_TIMEOUT env variable

        Returns:
            Объединённая конфигурация с учётом приоритета источников.
        """
        # Загружаем JSON конфиг (низший приоритет)
        json_config = self.load()

        # Загружаем TOML цепочку (переопределяет JSON)
        toml_config = self._load_from_toml_chain()

        # Объединяем: TOML переопределяет JSON
        merged_host = toml_config.get("host", json_config.host)
        merged_port = toml_config.get("port", json_config.port)
        merged_theme: TUITheme = toml_config.get("theme", json_config.theme)
        merged_timeout: float = toml_config.get("receive_timeout", json_config.receive_timeout)

        # Env variable переопределяет TOML
        if env_theme is not None:
            merged_theme = env_theme
        if env_receive_timeout is not None:
            merged_timeout = env_receive_timeout

        # CLI flag переопределяет всё
        if cli_theme is not None:
            merged_theme = cli_theme
        if cli_receive_timeout is not None:
            merged_timeout = cli_receive_timeout

        return TUIConfig(
            host=merged_host,
            port=merged_port,
            theme=merged_theme,
            receive_timeout=merged_timeout,
        )

    def save(self, config: TUIConfig) -> None:
        """Сохраняет конфигурацию в JSON файл, не прерывая выполнение при ошибках IO."""

        try:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            self._file_path.write_text(
                json.dumps(
                    {
                        "host": config.host,
                        "port": config.port,
                        "theme": config.theme,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError:
            # Локальная конфигурация не должна ломать runtime поведение TUI.
            return

    @staticmethod
    def _from_payload(payload: Any) -> TUIConfig:
        """Преобразует произвольный JSON-payload в валидный объект TUIConfig."""

        if not isinstance(payload, dict):
            return TUIConfig()

        host = payload.get("host")
        port = payload.get("port")
        theme = payload.get("theme")
        receive_timeout = payload.get("receive_timeout")

        normalized_host = host if isinstance(host, str) and host else "127.0.0.1"
        normalized_port = port if isinstance(port, int) and port > 0 else 8765
        normalized_theme: TUITheme = "dark" if theme == "dark" else "light"
        normalized_timeout = (
            receive_timeout
            if isinstance(receive_timeout, (int, float)) and receive_timeout > 0
            else 60.0
        )

        return TUIConfig(
            host=normalized_host,
            port=normalized_port,
            theme=normalized_theme,
            receive_timeout=normalized_timeout,
        )

    def _load_from_toml_chain(self) -> dict[str, Any]:
        """Загружает [tui] секцию из цепочки TOML файлов.

        Цепочка (от низшего к высшему приоритету):
        1. ~/.codelab/codelab.toml
        2. ~/.codelab/auth.toml
        3. ./codelab.toml (текущая директория)
        4. ./codelab.local.toml (project-local overrides)

        Returns:
            Dict с ключами host, port, theme из TOML файлов.
        """
        toml_files = self._find_toml_chain()
        merged_tui: dict[str, Any] = {}

        for toml_path in toml_files:
            try:
                with open(toml_path, "rb") as f:
                    data = tomllib.load(f)
                tui_section = data.get("tui", {})
                if isinstance(tui_section, dict):
                    # Каждый следующий файл переопределяет предыдущий
                    merged_tui.update(tui_section)
            except (OSError, tomllib.TOMLDecodeError) as e:
                logger.debug("toml_load_failed", path=str(toml_path), error=str(e))

        return self._normalize_toml_tui(merged_tui)

    @staticmethod
    def _find_toml_chain() -> list[Path]:
        """Находит все TOML файлы в цепочке приоритета.

        Returns:
            Список Path к TOML файлам в порядке приоритета (от низшего к высшему).
        """
        files: list[Path] = []

        # 1. Global codelab.toml
        global_toml = Path.home() / ".codelab" / "codelab.toml"
        if global_toml.exists():
            files.append(global_toml)

        # 2. Global auth.toml
        auth_toml = Path.home() / ".codelab" / "auth.toml"
        if auth_toml.exists():
            files.append(auth_toml)

        # 3. Project codelab.toml
        project_toml = Path.cwd() / "codelab.toml"
        if project_toml.exists():
            files.append(project_toml)

        # 4. Project-local overrides
        local_toml = Path.cwd() / "codelab.local.toml"
        if local_toml.exists():
            files.append(local_toml)

        return files

    @staticmethod
    def _normalize_toml_tui(toml_tui: dict[str, Any]) -> dict[str, Any]:
        """Нормализует данные из TOML [tui] секции.

        Args:
            toml_tui: Сырые данные из TOML [tui] секции.

        Returns:
            Dict с нормализованными ключами host, port, theme, receive_timeout.
        """
        result: dict[str, Any] = {}

        # Host
        host = toml_tui.get("host")
        if isinstance(host, str) and host:
            result["host"] = host

        # Port
        port = toml_tui.get("port")
        if isinstance(port, int) and port > 0:
            result["port"] = port

        # Theme
        theme = toml_tui.get("theme")
        if theme in ("light", "dark"):
            result["theme"] = theme
        elif theme is not None:
            logger.warning("invalid_toml_theme_value", theme=theme, fallback="light")

        # Receive timeout
        timeout = toml_tui.get("receive_timeout")
        if isinstance(timeout, (int, float)) and timeout > 0:
            result["receive_timeout"] = float(timeout)

        return result


def resolve_tui_connection(
    *,
    host: str | None = None,
    port: int | None = None,
    theme: TUITheme | None = None,
    receive_timeout: float | None = None,
) -> tuple[str, int, TUITheme, float]:
    """Возвращает host/port/theme/receive_timeout запуска TUI с fallback на сохранённый конфиг.

    Args:
        host: Адрес сервера из CLI (если None, используется конфиг)
        port: Порт сервера из CLI (если None, используется конфиг)
        theme: Тема из CLI флага --theme (если None, используется конфиг)
        receive_timeout: Таймаут из CLI флага --receive-timeout (если None, используется конфиг)

    Returns:
        Кортеж (host, port, theme, receive_timeout) с учётом приоритета источников.
    """
    config_store = TUIConfigStore()

    # Проверяем env variables
    env_theme: TUITheme | None = None
    env_theme_value = os.getenv("CODELAB_THEME")
    if env_theme_value in ("light", "dark"):
        env_theme = cast(TUITheme, env_theme_value)

    env_timeout: float | None = None
    env_timeout_value = os.getenv("CODELAB_RECEIVE_TIMEOUT")
    if env_timeout_value:
        try:
            parsed = float(env_timeout_value)
            if parsed > 0:
                env_timeout = parsed
        except ValueError:
            logger.warning(
                "invalid_env_timeout",
                value=env_timeout_value,
                fallback=60.0,
            )

    # Загружаем с приоритетом
    config = config_store.load_with_priority(
        cli_theme=theme,
        env_theme=env_theme,
        cli_receive_timeout=receive_timeout,
        env_receive_timeout=env_timeout,
    )

    # Host и port из CLI имеют приоритет над конфигом
    resolved_host = host if isinstance(host, str) and host else config.host
    resolved_port = port if isinstance(port, int) and port > 0 else config.port

    return resolved_host, resolved_port, config.theme, config.receive_timeout
