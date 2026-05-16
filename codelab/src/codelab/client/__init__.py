"""CodeLab client implementation.

Модуль клиента ACP протокола. Включает:
- domain: сущности и репозитории
- application: use cases, DTO, state machine
- infrastructure: DI, transport, handlers
- presentation: ViewModels (MVVM)
- tui: Textual UI компоненты
"""

# Основные модули клиента
from codelab.client.application.state_machine import StateTransitionError, UIState
from codelab.client.domain.entities import Message, Session
from codelab.client.infrastructure.transport import Transport, WebSocketTransport

__all__ = [
    # Domain
    "Message",
    "Session",
    # Application
    "UIState",
    "StateTransitionError",
    # Infrastructure
    "WebSocketTransport",
    "Transport",
]
