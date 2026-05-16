"""Тесты для serve_entry.py — точки входа textual-serve."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from codelab.client.tui.serve_entry import main


class TestServeEntry:
    """Тесты точки входа serve_entry."""

    @patch.dict(os.environ, {}, clear=True)
    @patch("textual_serve.server.Server")
    def test_uses_default_values_when_env_not_set(
        self, mock_server: MagicMock,
    ) -> None:
        """При отсутствии переменных окружения используются значения по умолчанию."""
        mock_server_instance = MagicMock()
        mock_server.return_value = mock_server_instance

        main()

        mock_server.assert_called_once()
        call_kwargs = mock_server.call_args[1]
        assert call_kwargs["host"] == "127.0.0.1"
        assert call_kwargs["port"] == 9765

    @patch.dict(
        os.environ,
        {
            "CODELAB_WS_HOST": "192.168.1.100",
            "CODELAB_WS_PORT": "9999",
            "CODELAB_WEB_UI_HOST": "0.0.0.0",
            "CODELAB_WEB_UI_PORT": "5000",
        },
    )
    @patch("textual_serve.server.Server")
    def test_reads_params_from_env(
        self, mock_server: MagicMock,
    ) -> None:
        """Параметры читаются из переменных окружения."""
        mock_server_instance = MagicMock()
        mock_server.return_value = mock_server_instance

        main()

        mock_server.assert_called_once()
        call_args = mock_server.call_args
        # Проверяем command (позиционный аргумент)
        command = call_args[1]["command"]
        assert "192.168.1.100" in command
        assert "9999" in command
        # Проверяем host и port (keyword аргументы)
        assert call_args[1]["host"] == "0.0.0.0"
        assert call_args[1]["port"] == 5000

    @patch.dict(os.environ, {}, clear=True)
    @patch("textual_serve.server.Server")
    def test_command_includes_ws_params(
        self, mock_server: MagicMock,
    ) -> None:
        """Command для textual-serve включает параметры подключения к WS."""
        mock_server_instance = MagicMock()
        mock_server.return_value = mock_server_instance

        main()

        call_kwargs = mock_server.call_args[1]
        command = call_kwargs["command"]
        assert "--host 127.0.0.1" in command
        assert "--port 8765" in command
        assert "codelab.client.tui" in command

    @patch.dict(os.environ, {}, clear=True)
    def test_exits_when_textual_serve_not_installed(
        self,
    ) -> None:
        """При отсутствии textual-serve программа завершается с ошибкой."""
        with (
            patch.dict(sys.modules, {"textual_serve.server": None}),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
