"""Тесты для EmbeddedResourceContent.

Тестирует создание, сериализацию, десериализацию и валидацию
встроенного контента ресурсов.
"""

import base64

import pytest
from pydantic import ValidationError

from codelab.shared.content import (
    BlobResource,
    EmbeddedResourceContent,
    TextResource,
)


class TestEmbeddedResourceContent:
    """Тесты для класса EmbeddedResourceContent."""

    def test_create_embedded_text_resource(self) -> None:
        """Тест создания EmbeddedResourceContent с TextResource."""
        resource = TextResource(
            uri="file:///script.py",
            text="def hello():\n    print('hello')",
            mimeType="text/x-python",
        )
        content = EmbeddedResourceContent(resource=resource)
        assert content.type == "resource"
        assert isinstance(content.resource, TextResource)
        assert content.resource.uri == "file:///script.py"
        assert content.resource.text == "def hello():\n    print('hello')"

    def test_create_embedded_blob_resource(self) -> None:
        """Тест создания EmbeddedResourceContent с BlobResource."""
        blob_data = base64.b64encode(b"binary_data").decode()
        resource = BlobResource(
            uri="file:///image.png",
            blob=blob_data,
            mimeType="image/png",
        )
        content = EmbeddedResourceContent(resource=resource)
        assert content.type == "resource"
        assert isinstance(content.resource, BlobResource)
        assert content.resource.uri == "file:///image.png"

    def test_create_embedded_with_annotations(self) -> None:
        """Тест создания EmbeddedResourceContent с аннотациями."""
        resource = TextResource(
            uri="file:///readme.md",
            text="# README",
            mimeType="text/markdown",
        )
        annotations = {"language": "markdown"}
        content = EmbeddedResourceContent(
            resource=resource,
            annotations=annotations,
        )
        assert content.annotations == annotations

    def test_embedded_from_dict_text_resource(self) -> None:
        """Тест десериализации EmbeddedResourceContent из dict с TextResource."""
        data = {
            "type": "resource",
            "resource": {
                "uri": "file:///script.py",
                "text": "print('hello')",
                "mimeType": "text/x-python",
            },
        }
        content = EmbeddedResourceContent.model_validate(data)
        assert isinstance(content.resource, TextResource)
        assert content.resource.text == "print('hello')"

    def test_embedded_from_dict_blob_resource(self) -> None:
        """Тест десериализации EmbeddedResourceContent из dict с BlobResource."""
        blob_data = base64.b64encode(b"data").decode()
        data = {
            "type": "resource",
            "resource": {
                "uri": "file:///data.bin",
                "blob": blob_data,
                "mimeType": "application/octet-stream",
            },
        }
        content = EmbeddedResourceContent.model_validate(data)
        assert isinstance(content.resource, BlobResource)
        assert content.resource.blob == blob_data

    def test_embedded_invalid_resource_no_text_or_blob(self) -> None:
        """Тест валидации ресурса без text или blob."""
        data = {
            "type": "resource",
            "resource": {
                "uri": "file:///invalid",
                # Нет ни text ни blob
            },
        }
        with pytest.raises(ValidationError) as exc_info:
            EmbeddedResourceContent.model_validate(data)
        assert "должен содержать" in str(exc_info.value)

    def test_embedded_serialization_text_resource(self) -> None:
        """Тест сериализации EmbeddedResourceContent с TextResource."""
        resource = TextResource(
            uri="file:///test.py",
            text="test()",
            mimeType="text/x-python",
        )
        content = EmbeddedResourceContent(resource=resource)
        data = content.model_dump(exclude_none=True)
        assert data["type"] == "resource"
        assert data["resource"]["uri"] == "file:///test.py"
        assert data["resource"]["text"] == "test()"

    def test_embedded_serialization_blob_resource(self) -> None:
        """Тест сериализации EmbeddedResourceContent с BlobResource."""
        blob_data = base64.b64encode(b"data").decode()
        resource = BlobResource(
            uri="file:///data.bin",
            blob=blob_data,
        )
        content = EmbeddedResourceContent(resource=resource)
        data = content.model_dump(exclude_none=True)
        assert data["type"] == "resource"
        assert data["resource"]["blob"] == blob_data

    def test_embedded_json_round_trip_text_resource(self) -> None:
        """Тест сериализации и десериализации в JSON для TextResource."""
        original = EmbeddedResourceContent(
            resource=TextResource(
                uri="file:///script.py",
                text="code here",
                mimeType="text/x-python",
            )
        )
        json_str = original.model_dump_json(exclude_none=True)
        restored = EmbeddedResourceContent.model_validate_json(json_str)
        assert isinstance(restored.resource, TextResource)
        assert restored.resource.uri == "file:///script.py"
        assert restored.resource.text == "code here"

    def test_embedded_json_round_trip_blob_resource(self) -> None:
        """Тест сериализации и десериализации в JSON для BlobResource."""
        blob_data = base64.b64encode(b"binary").decode()
        original = EmbeddedResourceContent(
            resource=BlobResource(
                uri="file:///file.bin",
                blob=blob_data,
            )
        )
        json_str = original.model_dump_json(exclude_none=True)
        restored = EmbeddedResourceContent.model_validate_json(json_str)
        assert isinstance(restored.resource, BlobResource)
        assert restored.resource.blob == blob_data

    def test_embedded_text_resource_without_mime_type(self) -> None:
        """Тест EmbeddedResourceContent с TextResource без mimeType."""
        resource = TextResource(
            uri="file:///plaintext.txt",
            text="Just plain text",
        )
        content = EmbeddedResourceContent(resource=resource)
        assert content.resource.mimeType is None

    def test_embedded_large_text_resource(self) -> None:
        """Тест EmbeddedResourceContent с большим TextResource."""
        large_text = "A" * 100000
        resource = TextResource(
            uri="file:///large.txt",
            text=large_text,
        )
        content = EmbeddedResourceContent(resource=resource)
        assert len(content.resource.text) == 100000

    def test_embedded_large_blob_resource(self) -> None:
        """Тест EmbeddedResourceContent с большим BlobResource."""
        large_binary = b"X" * 100000
        blob_data = base64.b64encode(large_binary).decode()
        resource = BlobResource(
            uri="file:///large.bin",
            blob=blob_data,
        )
        content = EmbeddedResourceContent(resource=resource)
        assert len(content.resource.blob) > 100000

    def test_embedded_with_annotations_serialization(self) -> None:
        """Тест сериализации с аннотациями."""
        resource = TextResource(
            uri="file:///doc.md",
            text="# Document",
        )
        content = EmbeddedResourceContent(
            resource=resource,
            annotations={"context": "important"},
        )
        data = content.model_dump(exclude_none=True)
        assert data["annotations"] == {"context": "important"}

    def test_embedded_unicode_text_resource(self) -> None:
        """Тест EmbeddedResourceContent с Unicode текстом."""
        resource = TextResource(
            uri="file:///doc.txt",
            text="Привет, мир! 你好 مرحبا",
        )
        content = EmbeddedResourceContent(resource=resource)
        assert content.resource.text == "Привет, мир! 你好 مرحبا"

    def test_embedded_multiline_text_resource(self) -> None:
        """Тест EmbeddedResourceContent с многострочным текстом."""
        multiline_text = "Line 1\nLine 2\nLine 3\nLine 4"
        resource = TextResource(
            uri="file:///multiline.txt",
            text=multiline_text,
        )
        content = EmbeddedResourceContent(resource=resource)
        assert content.resource.text == multiline_text
