"""Тесты для базовых классов Content типов.

Тестирует базовые классы ContentBlock, TextResource и BlobResource,
включая валидацию и сериализацию.
"""

import pytest
from pydantic import ValidationError

from codelab.shared.content import (
    BlobResource,
    TextResource,
)


class TestTextResource:
    """Тесты для класса TextResource."""

    def test_create_text_resource(self) -> None:
        """Тест создания валидного TextResource."""
        resource = TextResource(
            uri="file:///script.py",
            text="def hello():\n    print('hello')",
            mimeType="text/x-python",
        )
        assert resource.uri == "file:///script.py"
        assert resource.text == "def hello():\n    print('hello')"
        assert resource.mimeType == "text/x-python"

    def test_create_text_resource_without_mime_type(self) -> None:
        """Тест создания TextResource без mimeType."""
        resource = TextResource(
            uri="file:///script.txt",
            text="Hello",
        )
        assert resource.uri == "file:///script.txt"
        assert resource.text == "Hello"
        assert resource.mimeType is None

    def test_text_resource_empty_uri(self) -> None:
        """Тест валидации пустого URI в TextResource."""
        with pytest.raises(ValidationError) as exc_info:
            TextResource(uri="", text="content")
        assert "URI не может быть пустым" in str(exc_info.value)

    def test_text_resource_whitespace_uri(self) -> None:
        """Тест валидации URI состоящего только из пробелов."""
        with pytest.raises(ValidationError) as exc_info:
            TextResource(uri="   ", text="content")
        assert "URI не может быть пустым" in str(exc_info.value)

    def test_text_resource_text_serialization(self) -> None:
        """Тест сериализации TextResource в JSON."""
        resource = TextResource(
            uri="file:///test.py",
            text="print('test')",
            mimeType="text/x-python",
        )
        data = resource.model_dump(exclude_none=True)
        assert data == {
            "uri": "file:///test.py",
            "text": "print('test')",
            "mimeType": "text/x-python",
        }

    def test_text_resource_deserialization(self) -> None:
        """Тест десериализации TextResource из JSON."""
        data = {
            "uri": "file:///test.py",
            "text": "print('test')",
            "mimeType": "text/x-python",
        }
        resource = TextResource.model_validate(data)
        assert resource.uri == "file:///test.py"
        assert resource.text == "print('test')"
        assert resource.mimeType == "text/x-python"


class TestBlobResource:
    """Тесты для класса BlobResource."""

    def test_create_blob_resource(self) -> None:
        """Тест создания валидного BlobResource."""
        resource = BlobResource(
            uri="file:///image.png",
            blob="iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB...",
            mimeType="image/png",
        )
        assert resource.uri == "file:///image.png"
        assert resource.blob == "iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB..."
        assert resource.mimeType == "image/png"

    def test_create_blob_resource_without_mime_type(self) -> None:
        """Тест создания BlobResource без mimeType."""
        resource = BlobResource(
            uri="file:///data.bin",
            blob="AQIDBA==",
        )
        assert resource.uri == "file:///data.bin"
        assert resource.blob == "AQIDBA=="
        assert resource.mimeType is None

    def test_blob_resource_empty_uri(self) -> None:
        """Тест валидации пустого URI в BlobResource."""
        with pytest.raises(ValidationError) as exc_info:
            BlobResource(uri="", blob="data")
        assert "URI не может быть пустым" in str(exc_info.value)

    def test_blob_resource_empty_blob(self) -> None:
        """Тест валидации пустого blob в BlobResource."""
        with pytest.raises(ValidationError) as exc_info:
            BlobResource(uri="file:///test", blob="")
        assert "blob не может быть пустым" in str(exc_info.value)

    def test_blob_resource_whitespace_blob(self) -> None:
        """Тест валидации blob состоящего только из пробелов."""
        with pytest.raises(ValidationError) as exc_info:
            BlobResource(uri="file:///test", blob="   ")
        assert "blob не может быть пустым" in str(exc_info.value)

    def test_blob_resource_serialization(self) -> None:
        """Тест сериализации BlobResource в JSON."""
        resource = BlobResource(
            uri="file:///image.png",
            blob="iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB...",
            mimeType="image/png",
        )
        data = resource.model_dump(exclude_none=True)
        assert data == {
            "uri": "file:///image.png",
            "blob": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB...",
            "mimeType": "image/png",
        }

    def test_blob_resource_deserialization(self) -> None:
        """Тест десериализации BlobResource из JSON."""
        data = {
            "uri": "file:///image.png",
            "blob": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB...",
            "mimeType": "image/png",
        }
        resource = BlobResource.model_validate(data)
        assert resource.uri == "file:///image.png"
        assert resource.blob == "iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB..."
        assert resource.mimeType == "image/png"
