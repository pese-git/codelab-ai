"""Тесты для TextContent.

Тестирует создание, сериализацию, десериализацию и валидацию
текстового контента.
"""

import pytest
from pydantic import ValidationError

from codelab.shared.content import TextContent


class TestTextContent:
    """Тесты для класса TextContent."""

    def test_create_text_content(self) -> None:
        """Тест создания валидного TextContent."""
        content = TextContent(text="Hello, world!")
        assert content.type == "text"
        assert content.text == "Hello, world!"
        assert content.annotations is None

    def test_create_text_content_with_annotations(self) -> None:
        """Тест создания TextContent с аннотациями."""
        annotations = {"key": "value", "count": 42}
        content = TextContent(
            text="Message",
            annotations=annotations,
        )
        assert content.text == "Message"
        assert content.annotations == annotations

    def test_text_content_type_default(self) -> None:
        """Тест что тип по умолчанию установлен в 'text'."""
        content = TextContent(text="Test")
        assert content.type == "text"

    def test_text_content_empty_text(self) -> None:
        """Тест валидации пустого текста."""
        with pytest.raises(ValidationError) as exc_info:
            TextContent(text="")
        assert "text не может быть пустым" in str(exc_info.value)

    def test_text_content_whitespace_only(self) -> None:
        """Тест валидации текста состоящего только из пробелов."""
        with pytest.raises(ValidationError) as exc_info:
            TextContent(text="   \t\n  ")
        assert "text не может быть пустым" in str(exc_info.value)

    def test_text_content_non_string_text(self) -> None:
        """Тест валидации неправильного типа text."""
        with pytest.raises(ValidationError) as exc_info:
            TextContent(text=123)  # type: ignore
        assert "string_type" in str(exc_info.value)

    def test_text_content_multiline(self) -> None:
        """Тест создания TextContent с многострочным текстом."""
        text = "Line 1\nLine 2\nLine 3"
        content = TextContent(text=text)
        assert content.text == text

    def test_text_content_special_characters(self) -> None:
        """Тест создания TextContent со специальными символами."""
        text = "Hello! @#$%^&*() \"quotes\" 'apostrophes' \\ backslash"
        content = TextContent(text=text)
        assert content.text == text

    def test_text_content_unicode(self) -> None:
        """Тест создания TextContent с Unicode символами."""
        text = "Привет, мир! 你好世界 مرحبا بالعالم"
        content = TextContent(text=text)
        assert content.text == text

    def test_text_content_serialization(self) -> None:
        """Тест сериализации TextContent в JSON."""
        content = TextContent(text="Hello")
        data = content.model_dump(exclude_none=True)
        assert data == {"type": "text", "text": "Hello"}

    def test_text_content_serialization_with_annotations(self) -> None:
        """Тест сериализации TextContent с аннотациями."""
        content = TextContent(
            text="Hello",
            annotations={"tag": "greeting"},
        )
        data = content.model_dump(exclude_none=True)
        assert data == {
            "type": "text",
            "text": "Hello",
            "annotations": {"tag": "greeting"},
        }

    def test_text_content_deserialization(self) -> None:
        """Тест десериализации TextContent из JSON."""
        data = {"type": "text", "text": "Hello, world!"}
        content = TextContent.model_validate(data)
        assert content.type == "text"
        assert content.text == "Hello, world!"
        assert content.annotations is None

    def test_text_content_deserialization_with_annotations(self) -> None:
        """Тест десериализации TextContent с аннотациями."""
        data = {
            "type": "text",
            "text": "Hello",
            "annotations": {"color": "blue"},
        }
        content = TextContent.model_validate(data)
        assert content.text == "Hello"
        assert content.annotations == {"color": "blue"}

    def test_text_content_json_round_trip(self) -> None:
        """Тест сериализации и десериализации в JSON."""
        original = TextContent(
            text="Test message",
            annotations={"priority": "high"},
        )
        # Сериализуем в JSON
        json_str = original.model_dump_json(exclude_none=True)
        # Десериализуем обратно
        restored = TextContent.model_validate_json(json_str)
        assert restored.text == original.text
        assert restored.annotations == original.annotations
        assert restored.type == original.type

    def test_text_content_long_text(self) -> None:
        """Тест создания TextContent с длинным текстом."""
        long_text = "A" * 10000
        content = TextContent(text=long_text)
        assert len(content.text) == 10000
        assert content.text == long_text

    def test_text_content_empty_annotations(self) -> None:
        """Тест TextContent с пустым словарём аннотаций."""
        content = TextContent(text="Test", annotations={})
        assert content.annotations == {}

    def test_text_content_none_annotations_serialization(self) -> None:
        """Тест что None аннотации исключаются при сериализации."""
        content = TextContent(text="Test", annotations=None)
        data = content.model_dump(exclude_none=True)
        assert "annotations" not in data
