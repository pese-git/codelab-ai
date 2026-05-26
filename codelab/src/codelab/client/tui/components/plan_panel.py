"""Панель отображения плана выполнения в активной сессии с MVVM интеграцией.

Отвечает за:
- Отображение текущего плана агента
- Реактивное обновление при изменении плана через ViewModel
- Показ пустого состояния если плана нет
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widgets import Static

from codelab.client.messages import PlanUpdate

if TYPE_CHECKING:
    from codelab.client.presentation.plan_view_model import PlanViewModel


class PlanPanel(Static):
    """Показывает последний полученный план с приоритетами и статусами.

    Обязательно требует PlanViewModel для работы. Подписывается на Observable свойства:
    - plan_text: текст плана
    - has_plan: флаг наличия активного плана

    Примеры использования:
        >>> from codelab.client.presentation.plan_view_model import PlanViewModel
        >>> plan_vm = PlanViewModel()
        >>> plan_panel = PlanPanel(plan_vm)
        >>>
        >>> # Когда PlanViewModel обновляется, план отображается автоматически
        >>> plan_vm.set_plan("1. Задача A\\n2. Задача B")
    """

    DEFAULT_CSS = """
    PlanPanel {
        background: $background;
    }
    """

    def __init__(self, plan_vm: PlanViewModel) -> None:
        """Инициализирует PlanPanel с обязательным PlanViewModel.

        Args:
            plan_vm: PlanViewModel для управления состоянием плана
        """
        super().__init__("План: не получен", id="plan-panel")
        self.plan_vm = plan_vm
        self._entries: list[dict[str, str]] = []

        # Подписываемся на изменения в PlanViewModel
        self.plan_vm.plan_text.subscribe(self._on_plan_text_changed)
        self.plan_vm.has_plan.subscribe(self._on_has_plan_changed)

        # Инициализируем UI с текущим состоянием
        self._update_display()

    def _on_plan_text_changed(self, plan_text: str) -> None:
        """Обновить панель при изменении текста плана.

        Args:
            plan_text: Новый текст плана
        """
        self._update_display()

    def _on_has_plan_changed(self, has_plan: bool) -> None:
        """Обновить панель при изменении статуса наличия плана.

        Args:
            has_plan: Есть ли активный план
        """
        self._update_display()

    def _update_display(self) -> None:
        """Обновить содержимое панели на основе текущего состояния ViewModel."""
        if self.plan_vm.has_plan.value:
            self.update(self.plan_vm.plan_text.value)
        else:
            self.update("План: не получен")

    def reset(self) -> None:
        """Сбрасывает локальное состояние панели плана."""
        self._entries = []
        self.plan_vm.clear_plan()

    def apply_update(self, update: PlanUpdate) -> None:
        """Применяет новый snapshot плана из session/update события.

        Args:
            update: PlanUpdate с новыми пунктами плана
        """
        self._entries = [
            {
                "content": entry.content,
                "priority": entry.priority,
                "status": entry.status,
            }
            for entry in update.entries
        ]
        # Обновляем план через ViewModel для реактивности
        self.plan_vm.set_plan(self._render_text())

    def _render_text(self) -> str:
        """Формирует компактное представление пунктов плана."""
        if not self._entries:
            return "План: не получен"

        lines: list[str] = ["План:"]
        for entry in self._entries:
            lines.append(f"- [{entry['status']}] ({entry['priority']}) {entry['content']}")
        return "\n".join(lines)
