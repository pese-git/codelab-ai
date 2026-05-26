"""Тесты для InlineMarkdown компонента."""

from __future__ import annotations

import pytest

from codelab.client.tui.components.markdown import InlineMarkdown


class TestConvertToRich:
    """Тесты для метода _convert_to_rich."""

    @pytest.fixture
    def widget(self) -> InlineMarkdown:
        """Создаёт экземпляр InlineMarkdown."""
        return InlineMarkdown()

    def test_empty_text(self, widget: InlineMarkdown) -> None:
        """Пустой текст возвращает пустую строку."""
        assert widget._convert_to_rich("") == ""
        assert widget._convert_to_rich(None) == ""

    def test_plain_text(self, widget: InlineMarkdown) -> None:
        """Обычный текст остаётся без изменений."""
        assert widget._convert_to_rich("Hello world") == "Hello world"

    def test_bold_text(self, widget: InlineMarkdown) -> None:
        """**text** конвертируется в [bold]text[/bold]."""
        result = widget._convert_to_rich("**bold text**")
        assert result == "[bold]bold text[/bold]"

    def test_italic_text(self, widget: InlineMarkdown) -> None:
        """*text* конвертируется в [italic]text[/italic]."""
        result = widget._convert_to_rich("*italic text*")
        assert result == "[italic]italic text[/italic]"

    def test_inline_code(self, widget: InlineMarkdown) -> None:
        """`code` конвертируется в [reverse] code [/reverse]."""
        result = widget._convert_to_rich("`code`")
        assert result == "[reverse] code [/reverse]"

    def test_strikethrough(self, widget: InlineMarkdown) -> None:
        """~~text~~ конвертируется в [strike]text[/strike]."""
        result = widget._convert_to_rich("~~deleted~~")
        assert result == "[strike]deleted[/strike]"

    def test_header(self, widget: InlineMarkdown) -> None:
        """# Header конвертируется в [bold]Header[/bold]."""
        result = widget._convert_to_rich("# Header")
        assert result == "[bold]Header[/bold]"

    def test_link(self, widget: InlineMarkdown) -> None:
        """[text](url) конвертируется в text (url)."""
        result = widget._convert_to_rich("[link](https://example.com)")
        assert result == "link (https://example.com)"

    def test_escaped_brackets_restored(self, widget: InlineMarkdown) -> None:
        """Экранированные [ восстанавливаются обратно в [."""
        # Тестируем исправление бага с '\[' -> '['
        result = widget._convert_to_rich("array[0]")
        assert "[" in result
        assert result == "array[0]"

    def test_literal_rich_tags_escaped(self, widget: InlineMarkdown) -> None:
        """Литеральные Rich-теги в тексте экранируются."""
        # Если LLM вернёт [/bold] в тексте, это не должно сломать парсер
        result = widget._convert_to_rich("text with [/bold] tag")
        # Скобка должна быть восстановлена
        assert "[/bold]" in result

    def test_mixed_formatting(self, widget: InlineMarkdown) -> None:
        """Комбинированное форматирование."""
        result = widget._convert_to_rich("**bold** and *italic* with `code`")
        assert "[bold]bold[/bold]" in result
        assert "[italic]italic[/italic]" in result
        assert "[reverse] code [/reverse]" in result

    def test_brackets_with_formatting(self, widget: InlineMarkdown) -> None:
        """Скобки внутри форматированного текста."""
        result = widget._convert_to_rich("**array[0]**")
        assert "[bold]array[0][/bold]" in result
