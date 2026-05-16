"""Обработчики методов конфигурации сессии.

Содержит логику обработки session/set_config_option и session/set_mode.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ...messages import ACPMessage, JsonRpcId
from ...storage import SessionStorage
from ..state import ProtocolOutcome, SessionState
from .session import (
    build_config_options,
    build_modes_state,
    session_info_notification,
)


async def session_set_config_option(
    request_id: JsonRpcId | None,
    params: dict[str, Any],
    storage: SessionStorage,
    config_specs: dict[str, dict[str, Any]],
) -> ProtocolOutcome:
    """Изменяет значение конфигурационной опции сессии.

    В случае успеха возвращает новый snapshot `configOptions` и отправляет
    `config_option_update` + `session_info_update`.

    Пример использования:
        outcome = await session_set_config_option(
            "req_1",
            {"sessionId": "sess_1", "configId": "mode", "value": "code"},
            storage,
            config_specs,
        )
    """

    # Конфиг опции валидируем по локальной спецификации и допустимым значениям.
    session_id = params.get("sessionId")
    config_id = params.get("configId")
    value = params.get("value")

    if not isinstance(session_id, str):
        return ProtocolOutcome(
            response=ACPMessage.error_response(
                request_id,
                code=-32602,
                message="Invalid params: sessionId is required",
            )
        )
    if not isinstance(config_id, str) or not isinstance(value, str):
        return ProtocolOutcome(
            response=ACPMessage.error_response(
                request_id,
                code=-32602,
                message="Invalid params: configId and value must be strings",
            )
        )

    session = await storage.load_session(session_id)
    if session is None:
        return ProtocolOutcome(
            response=ACPMessage.error_response(
                request_id,
                code=-32001,
                message=f"Session not found: {session_id}",
            )
        )

    spec = config_specs.get(config_id)
    if spec is None:
        return ProtocolOutcome(
            response=ACPMessage.error_response(
                request_id,
                code=-32602,
                message=f"Invalid params: unknown config option {config_id}",
            )
        )

    available_values = {
        str(option["value"])
        for option in spec["options"]
        if isinstance(option, dict) and isinstance(option.get("value"), str)
    }
    if value not in available_values:
        return ProtocolOutcome(
            response=ACPMessage.error_response(
                request_id,
                code=-32602,
                message=f"Invalid params: unsupported value {value} for {config_id}",
            )
        )

    session.config_values[config_id] = value
    session.updated_at = datetime.now(UTC).isoformat()
    config_options = build_config_options(session.config_values, config_specs)
    # Отправляем полный snapshot configOptions, чтобы клиент не делал merge вручную.
    config_notification = ACPMessage.notification(
        "session/update",
        {
            "sessionId": session_id,
            "update": {
                "sessionUpdate": "config_option_update",
                "configOptions": config_options,
            },
        },
    )

    # Сохраняем изменённое состояние сессии
    await storage.save_session(session)

    return ProtocolOutcome(
        response=ACPMessage.response(
            request_id,
            {
                "configOptions": config_options,
                "modes": build_modes_state(session.config_values, config_specs),
            },
        ),
        notifications=build_config_update_notifications(
            session_id=session_id,
            config_id=config_id,
            session=session,
            config_notification=config_notification,
            config_specs=config_specs,
        ),
    )


async def session_set_mode(
    request_id: JsonRpcId | None,
    params: dict[str, Any],
    storage: SessionStorage,
    config_specs: dict[str, dict[str, Any]],
) -> ProtocolOutcome:
    """Legacy-совместимый метод смены режима через `session/set_mode`.

    Пример использования:
        outcome = await session_set_mode(
            "req_1",
            {"sessionId": "sess_1", "modeId": "code"},
            storage,
            config_specs,
        )
    """

    session_id = params.get("sessionId")
    mode_id = params.get("modeId")
    if not isinstance(session_id, str) or not isinstance(mode_id, str):
        return ProtocolOutcome(
            response=ACPMessage.error_response(
                request_id,
                code=-32602,
                message="Invalid params: sessionId and modeId must be strings",
            )
        )

    mapped = await session_set_config_option(
        request_id,
        {
            "sessionId": session_id,
            "configId": "mode",
            "value": mode_id,
        },
        storage,
        config_specs,
    )
    if mapped.response is None or mapped.response.error is not None:
        return mapped

    # По схеме `session/set_mode` возвращает пустой объект.
    return ProtocolOutcome(
        response=ACPMessage.response(request_id, {}),
        notifications=mapped.notifications,
    )


def build_config_update_notifications(
    *,
    session_id: str,
    config_id: str,
    session: SessionState,
    config_notification: ACPMessage,
    config_specs: dict[str, dict[str, Any]],
) -> list[ACPMessage]:
    """Формирует набор notifications после обновления config option.

    Пример использования:
        notes = build_config_update_notifications(
            session_id="sess_1",
            config_id="mode",
            session=state,
            config_notification=cfg_note,
            config_specs=specs,
        )
    """

    notifications: list[ACPMessage] = [config_notification]
    if config_id == "mode":
        notifications.append(
            ACPMessage.notification(
                "session/update",
                {
                    "sessionId": session_id,
                    "update": {
                        "sessionUpdate": "current_mode_update",
                        "currentModeId": session.config_values.get("mode", "ask"),
                    },
                },
            )
        )
    notifications.append(
        session_info_notification(
            session_id=session_id,
            title=None,
            updated_at=session.updated_at,
        )
    )
    return notifications
