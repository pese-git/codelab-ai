"""Holder для ClientRPCService.

Вынесен в отдельный модуль для избежания циклических импортов.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .client_rpc.service import ClientRPCService


@dataclass
class ClientRPCServiceHolder:
    """Holder для ClientRPCService, обновляемый при каждом WebSocket соединении.
    
    Dishka не поддерживает переопределение контекста в дочерних контейнерах,
    поэтому используем holder паттерн для передачи request-scoped зависимости.
    """
    _service: ClientRPCService | None = field(default=None)

    @property
    def service(self) -> ClientRPCService | None:
        return self._service

    @service.setter
    def service(self, value: ClientRPCService | None) -> None:
        self._service = value
