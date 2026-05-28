"""Тесты для receive_timeout в TUI конфигурации."""

import os
from pathlib import Path
from unittest.mock import patch

from codelab.client.tui.config import TUIConfig, TUIConfigStore, resolve_tui_connection


class TestTUIConfigReceiveTimeout:
    """Tests for receive_timeout in TUIConfig."""

    def test_default_timeout(self) -> None:
        config = TUIConfig()
        assert config.receive_timeout == 60.0

    def test_custom_timeout(self) -> None:
        config = TUIConfig(receive_timeout=120.0)
        assert config.receive_timeout == 120.0


class TestTUIConfigStoreReceiveTimeout:
    """Tests for receive_timeout loading in TUIConfigStore."""

    def test_json_config_with_timeout(self, tmp_path: Path) -> None:
        json_file = tmp_path / "tui_config.json"
        json_file.write_text('{"receive_timeout": 90.0}')
        store = TUIConfigStore(file_path=json_file)
        config = store.load()
        assert config.receive_timeout == 90.0

    def test_json_config_invalid_timeout_uses_default(self, tmp_path: Path) -> None:
        json_file = tmp_path / "tui_config.json"
        json_file.write_text('{"receive_timeout": -5}')
        store = TUIConfigStore(file_path=json_file)
        config = store.load()
        assert config.receive_timeout == 60.0

    def test_toml_timeout(self, tmp_path: Path) -> None:
        toml = tmp_path / "codelab.toml"
        toml.write_text("[tui]\nreceive_timeout = 120\n")

        store = TUIConfigStore(file_path=tmp_path / "nonexistent.json")
        with patch.object(store, "_find_toml_chain", return_value=[toml]):
            config = store.load_with_priority()
        assert config.receive_timeout == 120.0

    def test_toml_invalid_timeout_ignored(self, tmp_path: Path) -> None:
        toml = tmp_path / "codelab.toml"
        toml.write_text("[tui]\nreceive_timeout = -10\n")

        store = TUIConfigStore(file_path=tmp_path / "nonexistent.json")
        with patch.object(store, "_find_toml_chain", return_value=[toml]):
            config = store.load_with_priority()
        assert config.receive_timeout == 60.0

    def test_cli_timeout_overrides_toml(self, tmp_path: Path) -> None:
        toml = tmp_path / "codelab.toml"
        toml.write_text("[tui]\nreceive_timeout = 60\n")

        store = TUIConfigStore(file_path=tmp_path / "nonexistent.json")
        with patch.object(store, "_find_toml_chain", return_value=[toml]):
            config = store.load_with_priority(cli_receive_timeout=180.0)
        assert config.receive_timeout == 180.0

    def test_env_timeout_overrides_toml(self, tmp_path: Path) -> None:
        toml = tmp_path / "codelab.toml"
        toml.write_text("[tui]\nreceive_timeout = 60\n")

        store = TUIConfigStore(file_path=tmp_path / "nonexistent.json")
        with patch.object(store, "_find_toml_chain", return_value=[toml]):
            config = store.load_with_priority(env_receive_timeout=150.0)
        assert config.receive_timeout == 150.0

    def test_cli_timeout_overrides_env(self, tmp_path: Path) -> None:
        toml = tmp_path / "codelab.toml"
        toml.write_text("[tui]\nreceive_timeout = 60\n")

        store = TUIConfigStore(file_path=tmp_path / "nonexistent.json")
        with patch.object(store, "_find_toml_chain", return_value=[toml]):
            config = store.load_with_priority(
                env_receive_timeout=150.0,
                cli_receive_timeout=200.0,
            )
        assert config.receive_timeout == 200.0


class TestResolveTuiConnectionTimeout:
    """Tests for resolve_tui_connection with receive_timeout."""

    def test_returns_timeout(self, tmp_path: Path) -> None:
        with patch("codelab.client.tui.config.TUIConfigStore") as mock_store_class:
            mock_store = mock_store_class.return_value
            mock_store.load_with_priority.return_value = TUIConfig(
                host="localhost",
                port=8000,
                theme="light",
                receive_timeout=90.0,
            )

            host, port, theme, timeout = resolve_tui_connection()
            assert timeout == 90.0

    def test_cli_timeout_passed_to_config(self, tmp_path: Path) -> None:
        with patch("codelab.client.tui.config.TUIConfigStore") as mock_store_class:
            mock_store = mock_store_class.return_value
            mock_store.load_with_priority.return_value = TUIConfig(
                receive_timeout=120.0,
            )

            resolve_tui_connection(receive_timeout=120.0)

            # Проверяем что cli_receive_timeout был передан
            call_kwargs = mock_store.load_with_priority.call_args[1]
            assert call_kwargs["cli_receive_timeout"] == 120.0

    def test_env_variable_timeout(self, tmp_path: Path) -> None:
        with patch("codelab.client.tui.config.TUIConfigStore") as mock_store_class:
            mock_store = mock_store_class.return_value
            mock_store.load_with_priority.return_value = TUIConfig(
                receive_timeout=100.0,
            )

            with patch.dict(os.environ, {"CODELAB_RECEIVE_TIMEOUT": "100"}):
                resolve_tui_connection()

            # Проверяем что env_receive_timeout был передан
            call_kwargs = mock_store.load_with_priority.call_args[1]
            assert call_kwargs["env_receive_timeout"] == 100.0

    def test_invalid_env_variable_timeout_ignored(self, tmp_path: Path) -> None:
        with patch("codelab.client.tui.config.TUIConfigStore") as mock_store_class:
            mock_store = mock_store_class.return_value
            mock_store.load_with_priority.return_value = TUIConfig(
                receive_timeout=60.0,
            )

            with patch.dict(os.environ, {"CODELAB_RECEIVE_TIMEOUT": "invalid"}):
                resolve_tui_connection()

            # invalid значение должно быть None (проигнорировано)
            call_kwargs = mock_store.load_with_priority.call_args[1]
            assert call_kwargs["env_receive_timeout"] is None
