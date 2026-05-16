"""Контекст выполнения pipeline обработки prompt-turn."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from codelab.server.messages import ACPMessage, JsonRpcId
from codelab.server.protocol.state import SessionState


@dataclass
class PromptContext:
    """Изменяемый контекст, передаваемый через все стадии pipeline."""

    # Входные данные
    session_id: str
    session: SessionState
    request_id: JsonRpcId | None
    params: dict[str, Any]
    raw_text: str

    # Результаты, накапливаемые по ходу pipeline
    notifications: list[ACPMessage] = field(default_factory=list)
    stop_reason: str = "end_turn"
    should_stop: bool = False       # True — прервать pipeline досрочно
    error_response: ACPMessage | None = None
    pending_permission: bool = False  # True — turn отложен, ожидает разрешения

    # Метаданные для передачи между стадиями
    meta: dict[str, Any] = field(default_factory=dict)
