"""Pipeline runner — запускает стадии последовательно."""

from __future__ import annotations

import structlog

from codelab.server.messages import ACPMessage

from .base import PromptStage
from .context import PromptContext

logger = structlog.get_logger()


class PromptPipeline:
    """Исполнитель pipeline стадий обработки prompt-turn."""

    def __init__(self, stages: list[PromptStage]) -> None:
        self._stages = stages

    async def run(self, context: PromptContext) -> PromptContext:
        """Запустить все стадии последовательно.

        Каждая стадия получает контекст, выполняет работу и возвращает
        изменённый контекст. Если стадия устанавливает should_stop=True
        или error_response — pipeline прерывается.
        """
        for stage in self._stages:
            logger.debug("pipeline_stage_start", stage=stage.name)
            try:
                context = await stage.process(context)
            except Exception as e:
                logger.error("pipeline_stage_error", stage=stage.name, error=str(e))
                context.error_response = ACPMessage.error_response(
                    context.request_id,
                    code=-32603,
                    message=f"Internal error in {stage.name}",
                )
                context.should_stop = True

            if context.should_stop:
                logger.debug(
                    "pipeline_stopped",
                    stage=stage.name,
                    has_error=context.error_response is not None,
                )
                break

        return context
