"""Тесты для TUIConfigStore и конфигурации TUI."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from codelab.client.tui.config import TUIConfig, TUIConfigStore, resolve_tui_connection


class TestTUIConfig:
    """Тесты для TUIConfig dataclass."""

    def test_default_values(self) -> None:
        """Проверяет значения по умолчанию."""
        config = TUIConfig()
        assert config.host == "127.0.0.1"
        assert config.port == 8765
        assert config.theme == "light"


class TestTUIConfigStore:
    """Тесты для TUIConfigStore."""

    @pytest.fixture
    def temp_config_path(self, tmp_path: Path) -> Path:
        """Создаёт временный путь для конфигурации."""
        return tmp_path / "tui_config.json"

    def test_load_nonexistent_file(self, temp_config_path: Path) -> None:
        """Загрузка несуществующего файла возвращает default config."""
        store = TUIConfigStore(file_path=temp_config_path)
        config = store.load()
        assert config.host == "127.0.0.1"
        assert config.port == 8765
        assert config.theme == "light"

    def test_load_valid_json_config(self, temp_config_path: Path) -> None:
        """Загрузка валидного JSON конфига."""
        temp_config_path.write_text(
            json.dumps({"host": "192.168.1.1", "port": 9000, "theme": "dark"})
        )
        store = TUIConfigStore(file_path=temp_config_path)
        config = store.load()
        assert config.host == "192.168.1.1"
        assert config.port == 9000
        assert config.theme == "dark"

    def test_load_invalid_json_returns_default(self, temp_config_path: Path) -> None:
        """Загрузка invalid JSON возвращает default config."""
        temp_config_path.write_text("invalid json")
        store = TUIConfigStore(file_path=temp_config_path)
        config = store.load()
        assert config.host == "127.0.0.1"
        assert config.theme == "light"

    def test_save_config(self, temp_config_path: Path) -> None:
        """Сохранение конфигурации в файл."""
        store = TUIConfigStore(file_path=temp_config_path)
        config = TUIConfig(host="10.0.0.1", port=8080, theme="dark")
        store.save(config)

        # Проверяем что файл создан
        assert temp_config_path.exists()

        # Проверяем содержимое
        data = json.loads(temp_config_path.read_text())
        assert data["host"] == "10.0.0.1"
        assert data["port"] == 8080
        assert data["theme"] == "dark"

    def test_load_with_priority_cli_theme(self, temp_config_path: Path) -> None:
        """CLI theme имеет высший приоритет."""
        # Создаём JSON конфиг с light темой
        temp_config_path.write_text(json.dumps({"theme": "light"}))
        store = TUIConfigStore(file_path=temp_config_path)

        # CLI theme должен переопределить
        config = store.load_with_priority(cli_theme="dark")
        assert config.theme == "dark"

    def test_load_with_priority_env_theme(self, temp_config_path: Path) -> None:
        """Env theme переопределяет JSON конфиг."""
        temp_config_path.write_text(json.dumps({"theme": "light"}))
        store = TUIConfigStore(file_path=temp_config_path)

        config = store.load_with_priority(env_theme="dark")
        assert config.theme == "dark"

    def test_load_with_priority_cli_over_env(self, temp_config_path: Path) -> None:
        """CLI theme имеет приоритет над env."""
        temp_config_path.write_text(json.dumps({"theme": "light"}))
        store = TUIConfigStore(file_path=temp_config_path)

        config = store.load_with_priority(cli_theme="dark", env_theme="light")
        assert config.theme == "dark"


class TestTUIConfigStoreTOML:
    """Тесты для TOML поддержки в TUIConfigStore."""

    @pytest.fixture
    def temp_config_path(self, tmp_path: Path) -> Path:
        """Создаёт временный путь для конфигурации."""
        return tmp_path / "tui_config.json"

    def test_load_from_toml_chain_no_files(self, temp_config_path: Path) -> None:
        """Загрузка TOML когда файлов нет возвращает empty dict."""
        store = TUIConfigStore(file_path=temp_config_path)
        # Меняем cwd на временную директорию без TOML файлов
        with patch.object(Path, "cwd", return_value=temp_config_path.parent):
            result = store._load_from_toml_chain()
        assert result == {}

    def test_load_from_toml_chain_with_tui_section(self, tmp_path: Path) -> None:
        """Загрузка TOML с [tui] секцией."""
        # Создаём временный TOML файл
        toml_file = tmp_path / "codelab.toml"
        toml_file.write_text(
            """
[llm]
provider = "mock"

[tui]
theme = "dark"
host = "192.168.1.1"
port = 9000
"""
        )

        store = TUIConfigStore(file_path=tmp_path / "tui_config.json")

        # Патчим _find_toml_chain чтобы вернуть наш файл
        with patch.object(store, "_find_toml_chain", return_value=[toml_file]):
            result = store._load_from_toml_chain()

        assert result.get("theme") == "dark"
        assert result.get("host") == "192.168.1.1"
        assert result.get("port") == 9000

    def test_load_from_toml_chain_invalid_theme(self, tmp_path: Path) -> None:
        """Invalid theme value в TOML игнорируется."""
        toml_file = tmp_path / "codelab.toml"
        toml_file.write_text(
            """
[tui]
theme = "invalid"
"""
        )

        store = TUIConfigStore(file_path=tmp_path / "tui_config.json")

        with patch.object(store, "_find_toml_chain", return_value=[toml_file]):
            result = store._load_from_toml_chain()

        # Invalid theme не должен попасть в результат
        assert "theme" not in result

    def test_load_with_priority_toml_overrides_json(self, tmp_path: Path) -> None:
        """TOML переопределяет JSON конфиг."""
        # JSON конфиг
        json_path = tmp_path / "tui_config.json"
        json_path.write_text(json.dumps({"theme": "light", "host": "127.0.0.1"}))

        # TOML конфиг
        toml_file = tmp_path / "codelab.toml"
        toml_file.write_text(
            """
[tui]
theme = "dark"
"""
        )

        store = TUIConfigStore(file_path=json_path)

        with patch.object(store, "_find_toml_chain", return_value=[toml_file]):
            config = store.load_with_priority()

        assert config.theme == "dark"
        assert config.host == "127.0.0.1"  # Из JSON так как в TOML нет host


class TestResolveTUIConnection:
    """Тесты для resolve_tui_connection."""

    def test_resolve_with_cli_args(self, tmp_path: Path) -> None:
        """CLI args имеют приоритет."""
        json_path = tmp_path / "tui_config.json"
        json_path.write_text(json.dumps({"host": "127.0.0.1", "port": 8765, "theme": "light"}))

        store = TUIConfigStore(file_path=json_path)
        with patch("codelab.client.tui.config.TUIConfigStore", return_value=store):
            host, port, theme, timeout = resolve_tui_connection(
                host="192.168.1.1", port=9000, theme="dark"
            )

        assert host == "192.168.1.1"
        assert port == 9000
        assert theme == "dark"
        assert timeout == 60.0  # default

    def test_resolve_with_env_theme(self, tmp_path: Path) -> None:
        """Env theme используется когда CLI theme нет."""
        json_path = tmp_path / "tui_config.json"
        json_path.write_text(json.dumps({"theme": "light"}))

        store = TUIConfigStore(file_path=json_path)
        with patch("codelab.client.tui.config.TUIConfigStore", return_value=store):
            with patch.dict(os.environ, {"CODELAB_THEME": "dark"}):
                host, port, theme, timeout = resolve_tui_connection(host=None, port=None)

        assert theme == "dark"
        assert timeout == 60.0  # default

    def test_resolve_fallback_to_json_config(self, tmp_path: Path) -> None:
        """Fallback на JSON конфиг когда нет CLI/env."""
        json_path = tmp_path / "tui_config.json"
        json_path.write_text(json.dumps({"host": "10.0.0.1", "port": 8080, "theme": "dark"}))

        store = TUIConfigStore(file_path=json_path)
        with patch("codelab.client.tui.config.TUIConfigStore", return_value=store):
            host, port, theme, timeout = resolve_tui_connection(host=None, port=None)

        assert host == "10.0.0.1"
        assert port == 8080
        assert theme == "dark"
        assert timeout == 60.0  # default

    def test_resolve_with_cli_timeout(self, tmp_path: Path) -> None:
        """CLI timeout имеет приоритет."""
        json_path = tmp_path / "tui_config.json"
        json_path.write_text(json.dumps({"receive_timeout": 60}))

        store = TUIConfigStore(file_path=json_path)
        with patch("codelab.client.tui.config.TUIConfigStore", return_value=store):
            host, port, theme, timeout = resolve_tui_connection(receive_timeout=120.0)

        assert timeout == 120.0

    def test_resolve_with_env_timeout(self, tmp_path: Path) -> None:
        """Env timeout используется когда CLI timeout нет."""
        json_path = tmp_path / "tui_config.json"
        json_path.write_text(json.dumps({"receive_timeout": 60}))

        store = TUIConfigStore(file_path=json_path)
        with patch("codelab.client.tui.config.TUIConfigStore", return_value=store):
            with patch.dict(os.environ, {"CODELAB_RECEIVE_TIMEOUT": "90"}):
                host, port, theme, timeout = resolve_tui_connection()

        assert timeout == 90.0

    def test_resolve_timeout_from_json_config(self, tmp_path: Path) -> None:
        """Timeout загружается из JSON конфига."""
        json_path = tmp_path / "tui_config.json"
        json_path.write_text(json.dumps({"receive_timeout": 90.0}))

        store = TUIConfigStore(file_path=json_path)
        with patch("codelab.client.tui.config.TUIConfigStore", return_value=store):
            host, port, theme, timeout = resolve_tui_connection()

        assert timeout == 90.0
