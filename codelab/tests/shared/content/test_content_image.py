"""Тесты для ImageContent.

Тестирует создание, сериализацию, десериализацию и валидацию
контента с изображениями.
"""

import base64

import pytest
from pydantic import ValidationError

from codelab.shared.content import ImageContent


class TestImageContent:
    """Тесты для класса ImageContent."""

    def test_create_image_content_png(self) -> None:
        """Тест создания валидного PNG ImageContent."""
        # Минимальная валидная base64 PNG строка
        png_data = base64.b64encode(b"PNG_DATA").decode()
        content = ImageContent(mimeType="image/png", data=png_data)
        assert content.type == "image"
        assert content.mimeType == "image/png"
        assert content.data == png_data
        assert content.uri is None

    def test_create_image_content_jpeg(self) -> None:
        """Тест создания валидного JPEG ImageContent."""
        jpeg_data = base64.b64encode(b"JPEG_DATA").decode()
        content = ImageContent(mimeType="image/jpeg", data=jpeg_data)
        assert content.type == "image"
        assert content.mimeType == "image/jpeg"
        assert content.data == jpeg_data

    def test_create_image_content_with_uri(self) -> None:
        """Тест создания ImageContent с URI."""
        data = base64.b64encode(b"DATA").decode()
        content = ImageContent(
            mimeType="image/png",
            data=data,
            uri="file:///image.png",
        )
        assert content.uri == "file:///image.png"

    def test_create_image_content_with_annotations(self) -> None:
        """Тест создания ImageContent с аннотациями."""
        data = base64.b64encode(b"DATA").decode()
        annotations = {"alt": "A nice image"}
        content = ImageContent(
            mimeType="image/png",
            data=data,
            annotations=annotations,
        )
        assert content.annotations == annotations

    def test_image_content_mime_type_case_insensitive(self) -> None:
        """Тест что MIME-тип нечувствителен к регистру."""
        data = base64.b64encode(b"DATA").decode()
        # MIME-тип в разных регистрах должны быть приняты
        content1 = ImageContent(mimeType="image/png", data=data)
        content2 = ImageContent(mimeType="IMAGE/PNG", data=data)
        assert content1.mimeType == "image/png"
        assert content2.mimeType == "IMAGE/PNG"

    def test_image_content_custom_image_mime_type(self) -> None:
        """Тест поддержки пользовательских image/* MIME-типов."""
        data = base64.b64encode(b"DATA").decode()
        content = ImageContent(
            mimeType="image/svg+xml",
            data=data,
        )
        assert content.mimeType == "image/svg+xml"

    def test_image_content_empty_mime_type(self) -> None:
        """Тест валидации пустого MIME-типа."""
        with pytest.raises(ValidationError) as exc_info:
            ImageContent(mimeType="", data="dGVzdA==")
        assert "mimeType не может быть пустым" in str(exc_info.value)

    def test_image_content_invalid_mime_type(self) -> None:
        """Тест валидации неверного MIME-типа."""
        with pytest.raises(ValidationError) as exc_info:
            ImageContent(mimeType="text/plain", data="dGVzdA==")
        assert "не поддерживается" in str(exc_info.value)

    def test_image_content_empty_data(self) -> None:
        """Тест валидации пустых данных."""
        with pytest.raises(ValidationError) as exc_info:
            ImageContent(mimeType="image/png", data="")
        assert "data не может быть пустым" in str(exc_info.value)

    def test_image_content_invalid_base64(self) -> None:
        """Тест валидации неверной base64 строки."""
        with pytest.raises(ValidationError) as exc_info:
            # Специальные символы без правильного base64 выравнивания
            ImageContent(mimeType="image/png", data="!!!invalid!!!")
        assert "не является валидной base64" in str(exc_info.value)

    def test_image_content_base64_without_padding(self) -> None:
        """Тест валидной base64 без выравнивания (=)."""
        # base64 может быть без последних '='
        data = base64.b64encode(b"test").decode().rstrip("=")
        content = ImageContent(mimeType="image/png", data=data)
        assert content.data == data

    def test_image_content_empty_uri(self) -> None:
        """Тест валидации пустого URI."""
        with pytest.raises(ValidationError) as exc_info:
            ImageContent(
                mimeType="image/png",
                data="dGVzdA==",
                uri="",
            )
        assert "uri не может быть пустой" in str(exc_info.value)

    def test_image_content_whitespace_uri(self) -> None:
        """Тест валидации URI состоящего только из пробелов."""
        with pytest.raises(ValidationError) as exc_info:
            ImageContent(
                mimeType="image/png",
                data="dGVzdA==",
                uri="   ",
            )
        assert "uri не может быть пустой" in str(exc_info.value)

    def test_image_content_serialization(self) -> None:
        """Тест сериализации ImageContent в JSON."""
        data = base64.b64encode(b"DATA").decode()
        content = ImageContent(
            mimeType="image/png",
            data=data,
            uri="file:///img.png",
        )
        json_data = content.model_dump(exclude_none=True)
        assert json_data["type"] == "image"
        assert json_data["mimeType"] == "image/png"
        assert json_data["data"] == data
        assert json_data["uri"] == "file:///img.png"

    def test_image_content_deserialization(self) -> None:
        """Тест десериализации ImageContent из JSON."""
        data = base64.b64encode(b"DATA").decode()
        json_data = {
            "type": "image",
            "mimeType": "image/png",
            "data": data,
        }
        content = ImageContent.model_validate(json_data)
        assert content.type == "image"
        assert content.mimeType == "image/png"
        assert content.data == data

    def test_image_content_json_round_trip(self) -> None:
        """Тест сериализации и десериализации в JSON."""
        data = base64.b64encode(b"PNG_DATA").decode()
        original = ImageContent(
            mimeType="image/png",
            data=data,
            uri="file:///image.png",
        )
        json_str = original.model_dump_json(exclude_none=True)
        restored = ImageContent.model_validate_json(json_str)
        assert restored.mimeType == original.mimeType
        assert restored.data == original.data
        assert restored.uri == original.uri

    def test_image_content_large_base64(self) -> None:
        """Тест ImageContent с большой base64 строкой."""
        # Создаем большие данные
        large_data = b"X" * 100000
        base64_data = base64.b64encode(large_data).decode()
        content = ImageContent(mimeType="image/png", data=base64_data)
        assert len(content.data) > 100000

    def test_image_content_gif(self) -> None:
        """Тест ImageContent с GIF."""
        gif_data = base64.b64encode(b"GIF89a").decode()
        content = ImageContent(mimeType="image/gif", data=gif_data)
        assert content.mimeType == "image/gif"

    def test_image_content_webp(self) -> None:
        """Тест ImageContent с WebP."""
        webp_data = base64.b64encode(b"WEBP_DATA").decode()
        content = ImageContent(mimeType="image/webp", data=webp_data)
        assert content.mimeType == "image/webp"
