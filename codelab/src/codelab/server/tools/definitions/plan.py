"""Определение инструмента update_plan для обновления плана выполнения.

Инструмент позволяет LLM декларативно обновлять план выполнения задач.
Согласно спецификации ACP (protocol/11-Agent Plan.md), план состоит из
entries с полями content, priority и status.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from codelab.server.tools.base import ToolDefinition

if TYPE_CHECKING:
    from codelab.server.protocol.state import SessionState
    from codelab.server.tools.base import ToolRegistry
    from codelab.server.tools.executors.plan_executor import PlanToolExecutor


class PlanToolDefinitions:
    """Фабрика для создания определения инструмента update_plan.
    
    Инструмент не требует разрешений пользователя, так как обновление
    плана является внутренней операцией агента.
    """

    @staticmethod
    def update_plan() -> ToolDefinition:
        """Создать определение для инструмента update_plan.
        
        Позволяет LLM декларативно обновлять план выполнения задач.
        План отображается в UI клиента и помогает пользователю понять
        текущее состояние выполнения.
        
        Returns:
            ToolDefinition для регистрации в реестре.
        """
        return ToolDefinition(
            name="update_plan",
            description=(
                "Update the execution plan to show current task progress. "
                "Use this to communicate your plan to the user. "
                "Each entry should describe a task with its priority and status. "
                "Always send the COMPLETE list of entries (full replacement)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "entries": {
                        "type": "array",
                        "description": "List of plan entries",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {
                                    "type": "string",
                                    "description": "Short description of the task",
                                },
                                "priority": {
                                    "type": "string",
                                    "enum": ["low", "medium", "high"],
                                    "description": "Task importance level",
                                },
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"],
                                    "description": "Current task status",
                                },
                            },
                            "required": ["content", "priority", "status"],
                        },
                    },
                },
                "required": ["entries"],
            },
            # "think" - допустимое значение по спецификации ACP для внутренних операций
            kind="think",
            requires_permission=False,  # План не требует разрешений
        )

    @staticmethod
    def register_all(
        tool_registry: ToolRegistry,
        executor: PlanToolExecutor,
    ) -> None:
        """Зарегистрировать все plan инструменты в реестре.
        
        Регистрирует:
        - update_plan с executor для обновления плана
        
        Args:
            tool_registry: Реестр инструментов (SimpleToolRegistry)
            executor: Executor для выполнения операций с планом
        """
        # Создать обработчик для update_plan
        async def plan_handler(session: SessionState, **arguments: Any) -> Any:
            """Обработчик для update_plan."""
            return await executor.execute(session, arguments)

        # Зарегистрировать инструмент в реестре
        # Используем метод register() из SimpleToolRegistry
        tool_registry.register(
            PlanToolDefinitions.update_plan(),
            plan_handler,
        )
