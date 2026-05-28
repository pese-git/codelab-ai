from __future__ import annotations

from pathlib import Path

from codelab.client.tui.config import TUIConfig, TUIConfigStore, resolve_tui_connection


def test_tui_config_store_save_and_load_roundtrip(tmp_path: Path) -> None:
    config_file = tmp_path / "config" / "tui_config.json"
    store = TUIConfigStore(file_path=config_file)
    store.save(TUIConfig(host="127.0.0.9", port=9900, theme="dark"))

    loaded = store.load()

    assert loaded.host == "127.0.0.9"
    assert loaded.port == 9900
    assert loaded.theme == "dark"


def test_tui_config_store_fallbacks_on_invalid_payload(tmp_path: Path) -> None:
    config_file = tmp_path / "config" / "tui_config.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text('{"host": 1, "port": "bad", "theme": "unknown"}', encoding="utf-8")

    loaded = TUIConfigStore(file_path=config_file).load()

    assert loaded.host == "127.0.0.1"
    assert loaded.port == 8765
    assert loaded.theme == "light"


def test_resolve_tui_connection_uses_store_values_when_args_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "codelab.client.tui.config.TUIConfigStore.load",
        lambda _self: TUIConfig(host="127.0.0.8", port=8800, theme="light"),
    )

    host, port, theme, timeout = resolve_tui_connection(host=None, port=None)

    assert host == "127.0.0.8"
    assert port == 8800
    assert theme == "light"
    assert timeout == 60.0
