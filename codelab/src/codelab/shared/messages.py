"""Модели JSON-RPC/ACP сообщений для CodeLab.

Модуль описывает единый wire-формат JSON-RPC 2.0, который используется
обработчиками транспортов и протоколом ACP как на сервере, так и на клиенте.

Пример использования:
    # Создание запроса
    msg = ACPMessage.request("initialize", {"capabilities": {}})
    raw = msg.to_json()

    # Парсинг входящего сообщения
    msg = ACPMessage.from_json(raw_message)
"""

from __future__ import annotations

import json
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

# Тип идентификатора JSON-RPC сообщения
type JsonRpcId = str | int


class JsonRpcError(BaseModel):
    """Структура ошибки JSON-RPC в ответе.

    Соответствует спецификации JSON-RPC 2.0 для error objects.

    Attributes:
        code: Числовой код ошибки (стандартные коды: -32700...-32600).
        message: Краткое описание ошибки.
        data: Дополнительные детали ошибки для диагностики.

    Пример использования:
        JsonRpcError(code=-32601, message="Method not found")
    """

    # Код ошибки по спецификации JSON-RPC 2.0
    code: int
    # Человеко-читаемое описание ошибки
    message: str
    # Дополнительные детали ошибки (опционально)
    data: Any | None = None


class ACPMessage(BaseModel):
    """Универсальная модель JSON-RPC сообщения для ACP протокола.

    Модель покрывает все типы сообщений JSON-RPC 2.0:
    - request (с id и method)
    - notification (без id, с method)
    - response (с id и result/error)

    Используется как единая точка сериализации/валидации
    перед отправкой в транспорт.

    Attributes:
        jsonrpc: Версия протокола, всегда "2.0".
        id: Идентификатор запроса (отсутствует для notifications).
        method: Имя вызываемого метода (отсутствует для responses).
        params: Параметры метода (опционально).
        result: Результат успешного выполнения.
        error: Объект ошибки при неуспешном выполнении.

    Пример использования:
        # Создание response
        response = ACPMessage.response("req_1", {"ok": True})

        # Сериализация
        wire = response.to_json()
    """

    model_config = ConfigDict(extra="forbid")

    # Версия JSON-RPC, фиксировано "2.0"
    jsonrpc: Literal["2.0"] = "2.0"
    # Идентификатор запроса/ответа
    id: JsonRpcId | None = None
    # Имя метода для request/notification
    method: str | None = None
    # Параметры вызова
    params: dict[str, Any] | None = None
    # Результат успешного выполнения
    result: Any | None = None
    # Объект ошибки
    error: JsonRpcError | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> ACPMessage:
        """Проверяет целостность формы JSON-RPC payload.

        Гарантирует соблюдение правил JSON-RPC 2.0:
        - Request/notification имеют method и не имеют result/error
        - Response имеет либо result, либо error (но не оба)

        Returns:
            Валидированный объект сообщения.

        Raises:
            ValueError: При нарушении структуры JSON-RPC.

        Пример:
            ACPMessage.model_validate({"jsonrpc": "2.0", "id": "1", "result": {}})
        """
        # Проверяем, какие поля реально были переданы во входном payload
        has_result = "result" in self.model_fields_set
        has_error = "error" in self.model_fields_set and self.error is not None

        # Если есть method — это request или notification
        if self.method is not None:
            if has_result or has_error:
                msg = "Request/notification must not contain result or error"
                raise ValueError(msg)
            return self

        # Иначе это должен быть response
        if not has_result and not has_error:
            msg = "Response must contain result or error"
            raise ValueError(msg)
        if has_result and has_error:
            msg = "Response must not contain both result and error"
            raise ValueError(msg)
        return self

    @property
    def is_notification(self) -> bool:
        """Проверяет, является ли сообщение notification.

        Notification — это сообщение с method, но без id.
        Не требует ответа от получателя.

        Returns:
            True если сообщение является notification.

        Пример:
            ACPMessage.notification("session/update", {}).is_notification  # True
        """
        return self.method is not None and self.id is None

    @property
    def is_request(self) -> bool:
        """Проверяет, является ли сообщение request.

        Request — это сообщение с method и id.
        Требует ответа от получателя.

        Returns:
            True если сообщение является request.

        Пример:
            ACPMessage.request("initialize", {"protocolVersion": 1}).is_request  # True
        """
        return self.method is not None and self.id is not None

    @classmethod
    def request(
        cls,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        request_id: JsonRpcId | None = None,
    ) -> ACPMessage:
        """Создает request-сообщение.

        Args:
            method: Имя вызываемого метода.
            params: Параметры вызова (опционально).
            request_id: Идентификатор запроса (генерируется автоматически если не указан).

        Returns:
            Сформированное request-сообщение.

        Пример:
            ACPMessage.request("session/list", {"filter": "active"})
        """
        # Генерируем ID если не указан явно
        generated_id = request_id if request_id is not None else uuid4().hex[:8]
        return cls(id=generated_id, method=method, params=params or {})

    @classmethod
    def notification(cls, method: str, params: dict[str, Any] | None = None) -> ACPMessage:
        """Создает notification-сообщение без поля id.

        Notification не требует ответа от получателя и используется
        для односторонней передачи информации.

        Args:
            method: Имя метода.
            params: Параметры (опционально).

        Returns:
            Сформированное notification-сообщение.

        Пример:
            ACPMessage.notification("session/cancel", {"sessionId": "sess_1"})
        """
        return cls(id=None, method=method, params=params or {})

    @classmethod
    def response(cls, request_id: JsonRpcId | None, result: Any) -> ACPMessage:
        """Создает успешный response.

        Args:
            request_id: Идентификатор исходного запроса.
            result: Результат выполнения метода.

        Returns:
            Сформированный успешный response.

        Пример:
            ACPMessage.response("req_1", {"stopReason": "end_turn"})
        """
        return cls(id=request_id, result=result)

    @classmethod
    def error_response(
        cls,
        request_id: JsonRpcId | None,
        *,
        code: int,
        message: str,
        data: Any | None = None,
    ) -> ACPMessage:
        """Создает error response с кодом и описанием ошибки.

        Args:
            request_id: Идентификатор исходного запроса.
            code: Числовой код ошибки.
            message: Описание ошибки.
            data: Дополнительные детали (опционально).

        Returns:
            Сформированный error response.

        Пример:
            ACPMessage.error_response("req_1", code=-32602, message="Invalid params")
        """
        return cls(id=request_id, error=JsonRpcError(code=code, message=message, data=data))

    @classmethod
    def from_json(cls, raw: str) -> ACPMessage:
        """Десериализует JSON-строку в ACPMessage.

        Args:
            raw: JSON-строка сообщения.

        Returns:
            Распарсенный объект ACPMessage.

        Raises:
            ValidationError: При невалидном JSON или структуре.

        Пример:
            msg = ACPMessage.from_json('{"jsonrpc":"2.0","id":"1","result":{}}')
        """
        return cls.model_validate_json(raw)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ACPMessage:
        """Десериализует словарь с поддержкой legacy-поля type.

        Поддерживает обратную совместимость с legacy форматом,
        где использовалось поле type вместо стандартного определения
        типа по наличию method/result/error.

        Args:
            data: Словарь с данными сообщения.

        Returns:
            Распарсенный объект ACPMessage.

        Пример:
            ACPMessage.from_dict({"jsonrpc": "2.0", "id": "1", "result": {}})
        """
        # Поддерживаем legacy-поле type для плавного перехода на новый wire-формат
        normalized = dict(data)
        legacy_type = normalized.pop("type", None)
        if legacy_type == "request" and "id" not in normalized:
            normalized["id"] = uuid4().hex[:8]
        return cls.model_validate(normalized)

    def to_json(self) -> str:
        """Сериализует сообщение в компактную JSON-строку.

        Returns:
            JSON-представление сообщения без лишних пробелов.

        Пример:
            wire = ACPMessage.request("initialize", {"protocolVersion": 1}).to_json()
        """
        return json.dumps(self.to_dict(), separators=(",", ":"))

    def to_dict(self) -> dict[str, Any]:
        """Собирает словарь wire-формата JSON-RPC.

        Формирует минимальный payload, включая только
        необходимые поля согласно спецификации.

        Returns:
            Словарь для сериализации в JSON.

        Пример:
            payload = ACPMessage(id="req_1", result=None).to_dict()
        """
        payload: dict[str, Any] = {"jsonrpc": self.jsonrpc}

        # Для request/notification добавляем method и опционально params
        if self.method is not None:
            if self.id is not None:
                payload["id"] = self.id
            payload["method"] = self.method
            if "params" in self.model_fields_set:
                payload["params"] = self.params
            return payload

        # Для ответов id передается всегда (включая null для parse errors)
        payload["id"] = self.id
        if "result" in self.model_fields_set:
            payload["result"] = self.result
        if self.error is not None:
            payload["error"] = self.error.model_dump(exclude_none=True)
        return payload


def is_parse_error(exc: Exception) -> bool:
    """Проверяет, является ли исключение ошибкой валидации/парсинга сообщения.

    Используется для определения типа ошибки при обработке
    входящих сообщений и формирования корректного error response.

    Args:
        exc: Исключение для проверки.

    Returns:
        True если исключение является ValidationError от Pydantic.

    Пример:
        if is_parse_error(exc):
            return ACPMessage.error_response(None, code=-32700, message="Parse error")
    """
    return isinstance(exc, ValidationError)
