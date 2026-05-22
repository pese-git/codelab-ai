"""Тесты для infrastructure.message_parser модуля.

Тестирует:
- Парсинг JSON-сообщений
- Валидацию JSON-RPC схемы
- Классификацию сообщений
- Парсинг специфичных результатов
"""

from __future__ import annotations

import pytest

from codelab.client.infrastructure.message_parser import MessageParser
from codelab.client.messages import ACPMessage


class TestMessageParserJsonParsing:
    """Тесты парсинга JSON-сообщений."""

    def test_parse_json_request(self) -> None:
        """Проверяет парсинг JSON-запроса."""
        parser = MessageParser()
        json_str = '{"jsonrpc": "2.0", "id": "1", "method": "initialize", "params": {"protocolVersion": 1}}'
        message = parser.parse_json(json_str)

        assert message.jsonrpc == "2.0"
        assert message.id == "1"
        assert message.method == "initialize"
        assert "protocolVersion" in message.params

    def test_parse_json_response_with_result(self) -> None:
        """Проверяет парсинг JSON-ответа с result."""
        parser = MessageParser()
        json_str = '{"jsonrpc": "2.0", "id": "1", "result": {"status": "ok"}}'
        message = parser.parse_json(json_str)

        assert message.jsonrpc == "2.0"
        assert message.id == "1"
        assert message.result == {"status": "ok"}
        assert message.error is None

    def test_parse_json_response_with_error(self) -> None:
        """Проверяет парсинг JSON-ответа с error."""
        parser = MessageParser()
        json_str = (
            '{"jsonrpc": "2.0", "id": "1", '
            '"error": {"code": -32600, "message": "Invalid Request"}}'
        )
        message = parser.parse_json(json_str)

        assert message.jsonrpc == "2.0"
        assert message.id == "1"
        assert message.error is not None
        assert message.error.code == -32600
        assert message.error.message == "Invalid Request"

    def test_parse_json_invalid_json(self) -> None:
        """Проверяет что невалидный JSON выбрасывает ValueError."""
        parser = MessageParser()
        with pytest.raises(ValueError):
            parser.parse_json('{"invalid": json}')

    def test_parse_json_invalid_schema(self) -> None:
        """Проверяет что невалидная схема выбрасывает ValueError."""
        parser = MessageParser()
        # Ответ не может содержать и result и error
        with pytest.raises(ValueError):
            parser.parse_json(
                '{"jsonrpc": "2.0", "id": "1", "result": {}, '
                '"error": {"code": -1, "message": "err"}}'
            )


class TestMessageParserDictParsing:
    """Тесты парсинга dict-сообщений."""

    def test_parse_dict_request(self) -> None:
        """Проверяет парсинг dict-запроса."""
        parser = MessageParser()
        payload = {"jsonrpc": "2.0", "id": "1", "method": "initialize", "params": {"protocolVersion": 1}}
        message = parser.parse_dict(payload)

        assert message.method == "initialize"
        assert message.id == "1"

    def test_parse_dict_response(self) -> None:
        """Проверяет парсинг dict-ответа."""
        parser = MessageParser()
        payload = {"jsonrpc": "2.0", "id": "1", "result": {"status": "ok"}}
        message = parser.parse_dict(payload)

        assert message.result == {"status": "ok"}
        assert message.error is None


class TestMessageParserClassification:
    """Тесты классификации сообщений."""

    def test_classify_request(self) -> None:
        """Проверяет классификацию запроса."""
        parser = MessageParser()
        message = ACPMessage.request("initialize", {"protocolVersion": 1, "clientCapabilities": {}})
        assert parser.classify_message(message) == "request"

    def test_classify_notification(self) -> None:
        """Проверяет классификацию уведомления."""
        parser = MessageParser()
        # Уведомление имеет method но нет id
        message = ACPMessage(
            method="session/update",
            params={},
            jsonrpc="2.0",
        )
        assert parser.classify_message(message) == "notification"

    def test_classify_response(self) -> None:
        """Проверяет классификацию ответа."""
        parser = MessageParser()
        message = ACPMessage.response("1", {"status": "ok"})
        assert parser.classify_message(message) == "response"
