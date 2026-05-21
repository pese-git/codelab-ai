"""Тесты для извлечения и разрешения prompt директив.

Покрывают:
- extract_prompt_directives — парсинг slash-команд stop reasons
- resolve_prompt_directives — объединение text и _meta.overrides
- forced_stop_reason для всех ACP stop reasons
"""

from __future__ import annotations

from codelab.server.protocol.handlers.prompt import (
    extract_prompt_directives,
    resolve_prompt_directives,
)
from codelab.server.protocol.state import PromptDirectives


class TestExtractPromptDirectivesStopReasons:
    """Тесты парсинга forced_stop_reason из slash-команд."""

    _DEFAULT_TOOL_KINDS = {
        "read", "edit", "delete", "move", "search",
        "execute", "think", "fetch", "switch_mode", "other",
    }

    def test_stop_max_tokens(self) -> None:
        """Slash-команда /stop-max-tokens устанавливает forced_stop_reason."""
        directives = extract_prompt_directives(
            "/stop-max-tokens", self._DEFAULT_TOOL_KINDS
        )
        assert directives.forced_stop_reason == "max_tokens"

    def test_stop_max_tokens_with_additional_text(self) -> None:
        """forced_stop_reason извлекается даже с дополнительным текстом."""
        directives = extract_prompt_directives(
            "/stop-max-tokens some extra text", self._DEFAULT_TOOL_KINDS
        )
        assert directives.forced_stop_reason == "max_tokens"

    def test_stop_max_turn_requests(self) -> None:
        """Slash-команда /stop-max-turn-requests устанавливает forced_stop_reason."""
        directives = extract_prompt_directives(
            "/stop-max-turn-requests", self._DEFAULT_TOOL_KINDS
        )
        assert directives.forced_stop_reason == "max_turn_requests"

    def test_stop_max_turn_requests_with_additional_text(self) -> None:
        """forced_stop_reason извлекается даже с дополнительным текстом."""
        directives = extract_prompt_directives(
            "/stop-max-turn-requests and some text", self._DEFAULT_TOOL_KINDS
        )
        assert directives.forced_stop_reason == "max_turn_requests"

    def test_refuse(self) -> None:
        """Slash-команда /refuse устанавливает forced_stop_reason."""
        directives = extract_prompt_directives(
            "/refuse", self._DEFAULT_TOOL_KINDS
        )
        assert directives.forced_stop_reason == "refusal"

    def test_refuse_with_additional_text(self) -> None:
        """forced_stop_reason извлекается даже с дополнительным текстом."""
        directives = extract_prompt_directives(
            "/refuse because of policy", self._DEFAULT_TOOL_KINDS
        )
        assert directives.forced_stop_reason == "refusal"

    def test_no_forced_stop_reason_for_normal_prompt(self) -> None:
        """Обычный промпт не устанавливает forced_stop_reason."""
        directives = extract_prompt_directives(
            "Hello, how are you?", self._DEFAULT_TOOL_KINDS
        )
        assert directives.forced_stop_reason is None

    def test_no_forced_stop_reason_for_other_slash_commands(self) -> None:
        """Другие slash-команды не устанавливают forced_stop_reason."""
        for cmd in ["/help", "/mode code", "/status", "/tool execute", "/plan"]:
            directives = extract_prompt_directives(cmd, self._DEFAULT_TOOL_KINDS)
            assert directives.forced_stop_reason is None, f"Failed for: {cmd}"

    def test_all_supported_stop_reasons_via_slash(self) -> None:
        """Все поддерживаемые stop reasons (кроме end_turn, cancelled) извлекаются."""
        slash_map = {
            "/stop-max-tokens": "max_tokens",
            "/stop-max-turn-requests": "max_turn_requests",
            "/refuse": "refusal",
        }
        for cmd, expected in slash_map.items():
            directives = extract_prompt_directives(cmd, self._DEFAULT_TOOL_KINDS)
            assert directives.forced_stop_reason == expected


class TestResolvePromptDirectivesMetaOverrides:
    """Тесты _meta.promptDirectives.forcedStopReason overrides."""

    def test_meta_forced_stop_reason_max_tokens(self) -> None:
        """_meta.forcedStopReason: max_tokens overrides text."""
        directives = resolve_prompt_directives(
            params={
                "_meta": {
                    "promptDirectives": {
                        "forcedStopReason": "max_tokens",
                    }
                }
            },
            text_preview="plain text without slash command",
        )
        assert directives.forced_stop_reason == "max_tokens"

    def test_meta_forced_stop_reason_max_turn_requests(self) -> None:
        """_meta.forcedStopReason: max_turn_requests."""
        directives = resolve_prompt_directives(
            params={
                "_meta": {
                    "promptDirectives": {
                        "forcedStopReason": "max_turn_requests",
                    }
                }
            },
            text_preview="plain text",
        )
        assert directives.forced_stop_reason == "max_turn_requests"

    def test_meta_forced_stop_reason_refusal(self) -> None:
        """_meta.forcedStopReason: refusal."""
        directives = resolve_prompt_directives(
            params={
                "_meta": {
                    "promptDirectives": {
                        "forcedStopReason": "refusal",
                    }
                }
            },
            text_preview="plain text",
        )
        assert directives.forced_stop_reason == "refusal"

    def test_meta_forced_stop_reason_cancelled(self) -> None:
        """_meta.forcedStopReason: cancelled (допустимо через _meta)."""
        directives = resolve_prompt_directives(
            params={
                "_meta": {
                    "promptDirectives": {
                        "forcedStopReason": "cancelled",
                    }
                }
            },
            text_preview="plain text",
        )
        assert directives.forced_stop_reason == "cancelled"

    def test_meta_forced_stop_reason_end_turn(self) -> None:
        """_meta.forcedStopReason: end_turn."""
        directives = resolve_prompt_directives(
            params={
                "_meta": {
                    "promptDirectives": {
                        "forcedStopReason": "end_turn",
                    }
                }
            },
            text_preview="plain text",
        )
        assert directives.forced_stop_reason == "end_turn"

    def test_meta_overrides_slash_command(self) -> None:
        """_meta override имеет приоритет над slash-командой."""
        directives = resolve_prompt_directives(
            params={
                "_meta": {
                    "promptDirectives": {
                        "forcedStopReason": "refusal",
                    }
                }
            },
            text_preview="/stop-max-tokens",
        )
        # _meta имеет приоритет — должно быть refusal
        assert directives.forced_stop_reason == "refusal"

    def test_no_meta_returns_text_directives(self) -> None:
        """Без _meta используются директивы из текста."""
        directives = resolve_prompt_directives(
            params={},
            text_preview="/stop-max-tokens",
        )
        assert directives.forced_stop_reason == "max_tokens"

    def test_invalid_meta_ignored(self) -> None:
        """Некорректный _meta игнорируется."""
        for bad_meta in [
            {"_meta": "not a dict"},
            {"_meta": {"promptDirectives": "not a dict"}},
            {"_meta": {"promptDirectives": {"forcedStopReason": 123}}},
            {"_meta": {"promptDirectives": {"forcedStopReason": None}}},
        ]:
            directives = resolve_prompt_directives(
                params=bad_meta,
                text_preview="/stop-max-tokens",
            )
            # Должен использоваться текст, а не invalid _meta
            assert directives.forced_stop_reason == "max_tokens"

    def test_unsupported_forced_stop_reason_in_meta(self) -> None:
        """Неподдерживаемый forcedStopReason в _meta передаётся как есть."""
        # _meta с некорректным типом (int) игнорируется — используется текст
        directives = resolve_prompt_directives(
            params={
                "_meta": {
                    "promptDirectives": {
                        "forcedStopReason": 123,
                    }
                }
            },
            text_preview="/stop-max-tokens",
        )
        # Должен использоваться текст, а не invalid _meta
        assert directives.forced_stop_reason == "max_tokens"


class TestResolvePromptDirectivesCombined:
    """Тесты комбинаций директив с forced_stop_reason."""

    def test_forced_stop_reason_with_other_directives(self) -> None:
        """forced_stop_reason может сосуществовать с другими директивами."""
        directives = resolve_prompt_directives(
            params={
                "_meta": {
                    "promptDirectives": {
                        "forcedStopReason": "max_tokens",
                        "requestTool": True,
                        "publishPlan": True,
                    }
                }
            },
            text_preview="plain text",
        )
        assert directives.forced_stop_reason == "max_tokens"
        assert directives.request_tool is True
        assert directives.publish_plan is True

    def test_forced_stop_reason_with_tool_directive(self) -> None:
        """forced_stop_reason из _meta + tool directive из текста."""
        directives = resolve_prompt_directives(
            params={
                "_meta": {
                    "promptDirectives": {
                        "forcedStopReason": "refusal",
                    }
                }
            },
            text_preview="/tool execute some command",
        )
        assert directives.forced_stop_reason == "refusal"
        assert directives.request_tool is True
        assert directives.tool_kind == "execute"

    def test_forced_stop_reason_with_plan_directive(self) -> None:
        """forced_stop_reason из _meta + plan directive из текста."""
        directives = resolve_prompt_directives(
            params={
                "_meta": {
                    "promptDirectives": {
                        "forcedStopReason": "max_turn_requests",
                    }
                }
            },
            text_preview="/plan entry1, entry2",
        )
        assert directives.forced_stop_reason == "max_turn_requests"
        assert directives.publish_plan is True


class TestNormalizeStopReason:
    """Тесты нормализации stop_reason к ACP spec."""

    def test_supported_reasons_pass_through(self) -> None:
        """Поддерживаемые stop_reasons возвращаются без изменений."""
        from codelab.server.protocol.handlers.prompt import normalize_stop_reason

        supported = {"end_turn", "max_tokens", "max_turn_requests", "refusal", "cancelled"}
        for reason in supported:
            result = normalize_stop_reason(reason)
            assert result == reason, f"Failed for: {reason}"

    def test_max_iterations_normalized_to_end_turn(self) -> None:
        """Внутренний max_iterations нормализуется к end_turn."""
        from codelab.server.protocol.handlers.prompt import normalize_stop_reason

        assert normalize_stop_reason("max_iterations") == "end_turn"

    def test_tool_use_normalized_to_end_turn(self) -> None:
        """LLM stop_reason 'tool_use' нормализуется к end_turn (не ACP spec)."""
        from codelab.server.protocol.handlers.prompt import normalize_stop_reason

        assert normalize_stop_reason("tool_use") == "end_turn"

    def test_unknown_reason_normalized_to_end_turn(self) -> None:
        """Неизвестный stop_reason нормализуется к end_turn."""
        from codelab.server.protocol.handlers.prompt import normalize_stop_reason

        assert normalize_stop_reason("unknown_reason") == "end_turn"

    def test_error_normalized_to_end_turn(self) -> None:
        """LLM stop_reason 'error' нормализуется к end_turn."""
        from codelab.server.protocol.handlers.prompt import normalize_stop_reason

        assert normalize_stop_reason("error") == "end_turn"

    def test_custom_supported_reasons(self) -> None:
        """normalize_stop_reason с кастомным набором supported reasons."""
        from codelab.server.protocol.handlers.prompt import normalize_stop_reason

        custom_supported = {"end_turn", "max_tokens"}
        assert normalize_stop_reason("max_tokens", custom_supported) == "max_tokens"
        assert normalize_stop_reason("refusal", custom_supported) == "end_turn"


class TestResolvePromptStopReason:
    """Тесты resolve_prompt_stop_reason функции."""

    def test_returns_forced_stop_reason(self) -> None:
        """resolve_prompt_stop_reason возвращает forced_stop_reason."""
        from codelab.server.protocol.handlers.prompt import resolve_prompt_stop_reason

        directives = PromptDirectives(forced_stop_reason="max_tokens")
        assert resolve_prompt_stop_reason(directives) == "max_tokens"

    def test_returns_end_turn_when_no_forced_reason(self) -> None:
        """resolve_prompt_stop_reason возвращает 'end_turn' без forced_stop_reason."""
        from codelab.server.protocol.handlers.prompt import resolve_prompt_stop_reason

        directives = PromptDirectives()
        assert resolve_prompt_stop_reason(directives) == "end_turn"

    def test_normalizes_unsupported_forced_stop_reason(self) -> None:
        """resolve_prompt_stop_reason нормализует unsupported forced_stop_reason."""
        from codelab.server.protocol.handlers.prompt import resolve_prompt_stop_reason

        directives = PromptDirectives(forced_stop_reason="max_iterations")
        assert resolve_prompt_stop_reason(directives) == "end_turn"

    def test_all_acp_reasons_via_resolve(self) -> None:
        """Все ACP stop reasons проходят через resolve_prompt_stop_reason."""
        from codelab.server.protocol.handlers.prompt import resolve_prompt_stop_reason

        acp_reasons = ["end_turn", "max_tokens", "max_turn_requests", "refusal", "cancelled"]
        for reason in acp_reasons:
            directives = PromptDirectives(forced_stop_reason=reason)
            result = resolve_prompt_stop_reason(directives)
            assert result == reason, f"Failed for: {reason}"
