"""Точка входа для запуска textual-serve.

Читает параметры подключения из переменных окружения,
установленных родительским процессом.
Использование: python -m codelab.client.tui.serve_entry
"""

from __future__ import annotations

import os
import sys


def main() -> None:
    """Запускает textual-serve сервер для Web UI."""
    ws_host = os.environ.get("CODELAB_WS_HOST", "127.0.0.1")
    ws_port = os.environ.get("CODELAB_WS_PORT", "8765")
    web_port = int(os.environ.get("CODELAB_WEB_UI_PORT", "9765"))
    web_host = os.environ.get("CODELAB_WEB_UI_HOST", "127.0.0.1")

    try:
        from textual_serve.server import Server
    except ImportError:
        print("textual-serve not installed. Run: pip install 'codelab[web]'", file=sys.stderr)
        sys.exit(1)

    server = Server(
        command=f"{sys.executable} -m codelab.client.tui --host {ws_host} --port {ws_port}",
        host=web_host,
        port=web_port,
        title="CodeLab TUI",
    )
    server.serve()


if __name__ == "__main__":
    main()
