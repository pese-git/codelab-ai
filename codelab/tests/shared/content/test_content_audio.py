"""Тесты для AudioContent.

Тестирует создание, сериализацию, десериализацию и валидацию
контента с аудиоданными.
"""

import base64

import pytest
from pydantic import ValidationError

from codelab.shared.content import AudioContent


class TestAudioContent:
    """Тесты для класса AudioContent."""

    def test_create_audio_content_wav(self) -> None:
        """Тест создания валидного WAV AudioContent."""
        audio_data = base64.b64encode(b"WAV_DATA").decode()
        content = AudioContent(mimeType="audio/wav", data=audio_data)
        assert content.type == "audio"
        assert content.mimeType == "audio/wav"
        assert content.data == audio_data

    def test_create_audio_content_mp3(self) -> None:
        """Тест создания валидного MP3 AudioContent."""
        audio_data = base64.b64encode(b"MP3_DATA").decode()
        content = AudioContent(mimeType="audio/mp3", data=audio_data)
        assert content.type == "audio"
        assert content.mimeType == "audio/mp3"
        assert content.data == audio_data

    def test_create_audio_content_mpeg(self) -> None:
        """Тест создания AudioContent с audio/mpeg."""
        audio_data = base64.b64encode(b"MPEG_DATA").decode()
        content = AudioContent(mimeType="audio/mpeg", data=audio_data)
        assert content.type == "audio"
        assert content.mimeType == "audio/mpeg"

    def test_create_audio_content_with_annotations(self) -> None:
        """Тест создания AudioContent с аннотациями."""
        audio_data = base64.b64encode(b"DATA").decode()
        annotations = {"speaker": "Alice"}
        content = AudioContent(
            mimeType="audio/wav",
            data=audio_data,
            annotations=annotations,
        )
        assert content.annotations == annotations

    def test_audio_content_mime_type_case_insensitive(self) -> None:
        """Тест что MIME-тип нечувствителен к регистру."""
        audio_data = base64.b64encode(b"DATA").decode()
        content1 = AudioContent(mimeType="audio/wav", data=audio_data)
        content2 = AudioContent(mimeType="AUDIO/WAV", data=audio_data)
        assert content1.mimeType == "audio/wav"
        assert content2.mimeType == "AUDIO/WAV"

    def test_audio_content_custom_audio_mime_type(self) -> None:
        """Тест поддержки пользовательских audio/* MIME-типов."""
        audio_data = base64.b64encode(b"DATA").decode()
        content = AudioContent(
            mimeType="audio/ogg",
            data=audio_data,
        )
        assert content.mimeType == "audio/ogg"

    def test_audio_content_empty_mime_type(self) -> None:
        """Тест валидации пустого MIME-типа."""
        with pytest.raises(ValidationError) as exc_info:
            AudioContent(mimeType="", data="dGVzdA==")
        assert "mimeType не может быть пустым" in str(exc_info.value)

    def test_audio_content_invalid_mime_type(self) -> None:
        """Тест валидации неверного MIME-типа."""
        with pytest.raises(ValidationError) as exc_info:
            AudioContent(mimeType="text/plain", data="dGVzdA==")
        assert "не поддерживается" in str(exc_info.value)

    def test_audio_content_image_mime_type(self) -> None:
        """Тест что image MIME-типы отклоняются."""
        with pytest.raises(ValidationError) as exc_info:
            AudioContent(mimeType="image/png", data="dGVzdA==")
        assert "не поддерживается" in str(exc_info.value)

    def test_audio_content_empty_data(self) -> None:
        """Тест валидации пустых данных."""
        with pytest.raises(ValidationError) as exc_info:
            AudioContent(mimeType="audio/wav", data="")
        assert "data не может быть пустым" in str(exc_info.value)

    def test_audio_content_whitespace_data(self) -> None:
        """Тест валидации данных состоящих только из пробелов."""
        with pytest.raises(ValidationError) as exc_info:
            AudioContent(mimeType="audio/wav", data="   ")
        assert "data не может быть пустым" in str(exc_info.value)

    def test_audio_content_invalid_base64(self) -> None:
        """Тест валидации неверной base64 строки."""
        with pytest.raises(ValidationError) as exc_info:
            AudioContent(mimeType="audio/wav", data="!!!invalid!!!")
        assert "не является валидной base64" in str(exc_info.value)

    def test_audio_content_base64_without_padding(self) -> None:
        """Тест валидной base64 без выравнивания (=)."""
        data = base64.b64encode(b"audio").decode().rstrip("=")
        content = AudioContent(mimeType="audio/wav", data=data)
        assert content.data == data

    def test_audio_content_serialization(self) -> None:
        """Тест сериализации AudioContent в JSON."""
        audio_data = base64.b64encode(b"AUDIO").decode()
        content = AudioContent(
            mimeType="audio/wav",
            data=audio_data,
        )
        json_data = content.model_dump(exclude_none=True)
        assert json_data["type"] == "audio"
        assert json_data["mimeType"] == "audio/wav"
        assert json_data["data"] == audio_data

    def test_audio_content_serialization_with_annotations(self) -> None:
        """Тест сериализации AudioContent с аннотациями."""
        audio_data = base64.b64encode(b"AUDIO").decode()
        content = AudioContent(
            mimeType="audio/wav",
            data=audio_data,
            annotations={"duration": 30},
        )
        json_data = content.model_dump(exclude_none=True)
        assert json_data["annotations"] == {"duration": 30}

    def test_audio_content_deserialization(self) -> None:
        """Тест десериализации AudioContent из JSON."""
        audio_data = base64.b64encode(b"AUDIO").decode()
        json_data = {
            "type": "audio",
            "mimeType": "audio/wav",
            "data": audio_data,
        }
        content = AudioContent.model_validate(json_data)
        assert content.type == "audio"
        assert content.mimeType == "audio/wav"
        assert content.data == audio_data

    def test_audio_content_json_round_trip(self) -> None:
        """Тест сериализации и десериализации в JSON."""
        audio_data = base64.b64encode(b"WAV_DATA").decode()
        original = AudioContent(
            mimeType="audio/wav",
            data=audio_data,
            annotations={"duration": 45},
        )
        json_str = original.model_dump_json(exclude_none=True)
        restored = AudioContent.model_validate_json(json_str)
        assert restored.mimeType == original.mimeType
        assert restored.data == original.data
        assert restored.annotations == original.annotations

    def test_audio_content_large_base64(self) -> None:
        """Тест AudioContent с большой base64 строкой."""
        large_data = b"X" * 500000
        base64_data = base64.b64encode(large_data).decode()
        content = AudioContent(mimeType="audio/wav", data=base64_data)
        assert len(content.data) > 500000

    def test_audio_content_wave_variant(self) -> None:
        """Тест AudioContent с audio/wave."""
        audio_data = base64.b64encode(b"DATA").decode()
        content = AudioContent(mimeType="audio/wave", data=audio_data)
        assert content.mimeType == "audio/wave"

    def test_audio_content_mpeg3(self) -> None:
        """Тест AudioContent с audio/mpeg3."""
        audio_data = base64.b64encode(b"DATA").decode()
        content = AudioContent(mimeType="audio/mpeg3", data=audio_data)
        assert content.mimeType == "audio/mpeg3"
