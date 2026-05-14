"""Тесты для ResourceLinkContent.

Тестирует создание, сериализацию, десериализацию и валидацию
ссылок на ресурсы.
"""

import pytest
from pydantic import ValidationError

from codelab.shared.content import ResourceLinkContent


class TestResourceLinkContent:
    """Тесты для класса ResourceLinkContent."""

    def test_create_resource_link_minimal(self) -> None:
        """Тест создания минимального ResourceLinkContent."""
        content = ResourceLinkContent(
            uri="file:///document.pdf",
            name="document.pdf",
        )
        assert content.type == "resource_link"
        assert content.uri == "file:///document.pdf"
        assert content.name == "document.pdf"
        assert content.mimeType is None
        assert content.title is None
        assert content.description is None
        assert content.size is None

    def test_create_resource_link_full(self) -> None:
        """Тест создания полного ResourceLinkContent со всеми полями."""
        content = ResourceLinkContent(
            uri="file:///document.pdf",
            name="document.pdf",
            mimeType="application/pdf",
            title="My Document",
            description="A PDF document with important information",
            size=1024000,
        )
        assert content.uri == "file:///document.pdf"
        assert content.name == "document.pdf"
        assert content.mimeType == "application/pdf"
        assert content.title == "My Document"
        assert content.description == "A PDF document with important information"
        assert content.size == 1024000

    def test_create_resource_link_with_annotations(self) -> None:
        """Тест создания ResourceLinkContent с аннотациями."""
        annotations = {"priority": "high", "read": False}
        content = ResourceLinkContent(
            uri="file:///file.txt",
            name="file.txt",
            annotations=annotations,
        )
        assert content.annotations == annotations

    def test_resource_link_empty_uri(self) -> None:
        """Тест валидации пустого URI."""
        with pytest.raises(ValidationError) as exc_info:
            ResourceLinkContent(uri="", name="file.txt")
        assert "uri не может быть пустым" in str(exc_info.value)

    def test_resource_link_whitespace_uri(self) -> None:
        """Тест валидации URI состоящего только из пробелов."""
        with pytest.raises(ValidationError) as exc_info:
            ResourceLinkContent(uri="   ", name="file.txt")
        assert "uri не может быть пустым" in str(exc_info.value)

    def test_resource_link_empty_name(self) -> None:
        """Тест валидации пустого имени."""
        with pytest.raises(ValidationError) as exc_info:
            ResourceLinkContent(uri="file:///test", name="")
        assert "name не может быть пустым" in str(exc_info.value)

    def test_resource_link_whitespace_name(self) -> None:
        """Тест валидации имени состоящего только из пробелов."""
        with pytest.raises(ValidationError) as exc_info:
            ResourceLinkContent(uri="file:///test", name="   ")
        assert "name не может быть пустым" in str(exc_info.value)

    def test_resource_link_negative_size(self) -> None:
        """Тест валидации отрицательного размера."""
        with pytest.raises(ValidationError) as exc_info:
            ResourceLinkContent(
                uri="file:///test",
                name="test",
                size=-1,
            )
        assert "size не может быть отрицательным" in str(exc_info.value)

    def test_resource_link_zero_size(self) -> None:
        """Тест что нулевой размер разрешён."""
        content = ResourceLinkContent(
            uri="file:///empty",
            name="empty.txt",
            size=0,
        )
        assert content.size == 0

    def test_resource_link_empty_title(self) -> None:
        """Тест валидации пустого заголовка."""
        with pytest.raises(ValidationError) as exc_info:
            ResourceLinkContent(
                uri="file:///test",
                name="test",
                title="",
            )
        assert "title не может быть пустой" in str(exc_info.value)

    def test_resource_link_whitespace_title(self) -> None:
        """Тест валидации заголовка состоящего только из пробелов."""
        with pytest.raises(ValidationError) as exc_info:
            ResourceLinkContent(
                uri="file:///test",
                name="test",
                title="   ",
            )
        assert "title не может быть пустой" in str(exc_info.value)

    def test_resource_link_empty_description(self) -> None:
        """Тест валидации пустого описания."""
        with pytest.raises(ValidationError) as exc_info:
            ResourceLinkContent(
                uri="file:///test",
                name="test",
                description="",
            )
        assert "description не может быть пустой" in str(exc_info.value)

    def test_resource_link_whitespace_description(self) -> None:
        """Тест валидации описания состоящего только из пробелов."""
        with pytest.raises(ValidationError) as exc_info:
            ResourceLinkContent(
                uri="file:///test",
                name="test",
                description="   ",
            )
        assert "description не может быть пустой" in str(exc_info.value)

    def test_resource_link_empty_mime_type(self) -> None:
        """Тест валидации пустого MIME-типа."""
        with pytest.raises(ValidationError) as exc_info:
            ResourceLinkContent(
                uri="file:///test",
                name="test",
                mimeType="",
            )
        assert "mimeType не может быть пустой" in str(exc_info.value)

    def test_resource_link_serialization(self) -> None:
        """Тест сериализации ResourceLinkContent в JSON."""
        content = ResourceLinkContent(
            uri="file:///doc.pdf",
            name="doc.pdf",
            mimeType="application/pdf",
            size=2048,
        )
        data = content.model_dump(exclude_none=True)
        assert data["type"] == "resource_link"
        assert data["uri"] == "file:///doc.pdf"
        assert data["name"] == "doc.pdf"
        assert data["mimeType"] == "application/pdf"
        assert data["size"] == 2048

    def test_resource_link_serialization_minimal(self) -> None:
        """Тест сериализации минимального ResourceLinkContent."""
        content = ResourceLinkContent(
            uri="file:///test.txt",
            name="test.txt",
        )
        data = content.model_dump(exclude_none=True)
        assert data == {
            "type": "resource_link",
            "uri": "file:///test.txt",
            "name": "test.txt",
        }

    def test_resource_link_deserialization(self) -> None:
        """Тест десериализации ResourceLinkContent из JSON."""
        json_data = {
            "type": "resource_link",
            "uri": "file:///document.pdf",
            "name": "document.pdf",
            "mimeType": "application/pdf",
            "size": 1024000,
        }
        content = ResourceLinkContent.model_validate(json_data)
        assert content.uri == "file:///document.pdf"
        assert content.name == "document.pdf"
        assert content.mimeType == "application/pdf"
        assert content.size == 1024000

    def test_resource_link_json_round_trip(self) -> None:
        """Тест сериализации и десериализации в JSON."""
        original = ResourceLinkContent(
            uri="file:///important.doc",
            name="important.doc",
            mimeType="application/msword",
            title="Important Document",
            description="This is an important document",
            size=512000,
        )
        json_str = original.model_dump_json(exclude_none=True)
        restored = ResourceLinkContent.model_validate_json(json_str)
        assert restored.uri == original.uri
        assert restored.name == original.name
        assert restored.mimeType == original.mimeType
        assert restored.title == original.title
        assert restored.description == original.description
        assert restored.size == original.size

    def test_resource_link_with_special_characters(self) -> None:
        """Тест ResourceLinkContent с специальными символами."""
        content = ResourceLinkContent(
            uri="file:///path/to/file-with-dash_and_underscore.pdf",
            name="file-with-dash_and_underscore.pdf",
            title="File with @#$% special chars",
        )
        assert "@#$%" in content.title

    def test_resource_link_unicode(self) -> None:
        """Тест ResourceLinkContent с Unicode."""
        content = ResourceLinkContent(
            uri="file:///документ.pdf",
            name="документ.pdf",
            title="Важный документ",
            description="Описание на русском языке",
        )
        assert "документ" in content.uri
        assert "русском" in content.description

    def test_resource_link_large_size(self) -> None:
        """Тест ResourceLinkContent с большим размером."""
        large_size = 5 * 1024 * 1024 * 1024  # 5 GB
        content = ResourceLinkContent(
            uri="file:///large.iso",
            name="large.iso",
            size=large_size,
        )
        assert content.size == large_size

    def test_resource_link_long_description(self) -> None:
        """Тест ResourceLinkContent с длинным описанием."""
        long_description = "A" * 10000
        content = ResourceLinkContent(
            uri="file:///test",
            name="test",
            description=long_description,
        )
        assert len(content.description) == 10000

    def test_resource_link_many_annotations(self) -> None:
        """Тест ResourceLinkContent с большим количеством аннотаций."""
        annotations = {f"key_{i}": f"value_{i}" for i in range(100)}
        content = ResourceLinkContent(
            uri="file:///test",
            name="test",
            annotations=annotations,
        )
        assert len(content.annotations) == 100

    def test_resource_link_type_default(self) -> None:
        """Тест что тип по умолчанию установлен в 'resource_link'."""
        content = ResourceLinkContent(
            uri="file:///test",
            name="test",
        )
        assert content.type == "resource_link"

    def test_resource_link_none_optional_fields(self) -> None:
        """Тест что None опциональные поля исключаются при сериализации."""
        content = ResourceLinkContent(
            uri="file:///test",
            name="test",
            mimeType=None,
            title=None,
            description=None,
            size=None,
        )
        data = content.model_dump(exclude_none=True)
        assert "mimeType" not in data
        assert "title" not in data
        assert "description" not in data
        assert "size" not in data

    def test_resource_link_http_uri(self) -> None:
        """Тест ResourceLinkContent с HTTP URI."""
        content = ResourceLinkContent(
            uri="https://example.com/file.pdf",
            name="file.pdf",
        )
        assert content.uri == "https://example.com/file.pdf"

    def test_resource_link_s3_uri(self) -> None:
        """Тест ResourceLinkContent с S3 URI."""
        content = ResourceLinkContent(
            uri="s3://bucket/path/to/file.zip",
            name="file.zip",
        )
        assert content.uri == "s3://bucket/path/to/file.zip"
