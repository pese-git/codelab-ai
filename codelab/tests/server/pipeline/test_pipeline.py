"""Тесты для pipeline обработки prompt-turn.

Покрывают:
- PromptContext
- PromptStage (абстракция)
- PromptPipeline (runner)
- ValidationStage
- SlashCommandStage
- PlanBuildingStage
- TurnLifecycleStage
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from codelab.server.protocol.handlers.pipeline import (
    PromptContext,
    PromptPipeline,
    PromptStage,
)
from codelab.server.protocol.handlers.pipeline.stages import (
    PlanBuildingStage,
    SlashCommandStage,
    TurnLifecycleStage,
    ValidationStage,
)
from codelab.server.protocol.state import (
    ActiveTurnState,
    SessionState,
)
from codelab.shared.messages import ACPMessage


class TestPromptContext:
    """Тесты для PromptContext."""

    def test_create_context_with_defaults(self):
        session = SessionState(session_id="s1", cwd="/", mcp_servers=[])
        context = PromptContext(
            session_id="s1",
            session=session,
            request_id="req-1",
            params={},
            raw_text="hello",
        )

        assert context.session_id == "s1"
        assert context.raw_text == "hello"
        assert context.notifications == []
        assert context.stop_reason == "end_turn"
        assert context.should_stop is False
        assert context.error_response is None
        assert context.meta == {}

    def test_context_meta_stores_arbitrary_data(self):
        session = SessionState(session_id="s1", cwd="/", mcp_servers=[])
        context = PromptContext(
            session_id="s1",
            session=session,
            request_id="req-1",
            params={},
            raw_text="hello",
        )

        context.meta["key"] = "value"
        context.meta["counter"] = 42

        assert context.meta["key"] == "value"
        assert context.meta["counter"] == 42


class TestPromptStage:
    """Тесты для абстракции PromptStage."""

    def test_stage_name_returns_class_name(self):
        class CustomStage(PromptStage):
            async def process(self, context: PromptContext) -> PromptContext:
                return context

        stage = CustomStage()
        assert stage.name == "CustomStage"

    @pytest.mark.asyncio
    async def test_stage_process_is_abstract(self):
        """Проверка что абстрактный метод должен быть реализован."""
        with pytest.raises(TypeError):
            PromptStage()  # type: ignore[abstract]


class TestPromptPipeline:
    """Тесты для PromptPipeline runner."""

    @pytest.mark.asyncio
    async def test_pipeline_runs_all_stages(self):
        stage1 = MagicMock(spec=PromptStage)
        stage1.name = "Stage1"
        stage1.process = AsyncMock(side_effect=lambda ctx: ctx)

        stage2 = MagicMock(spec=PromptStage)
        stage2.name = "Stage2"
        stage2.process = AsyncMock(side_effect=lambda ctx: ctx)

        pipeline = PromptPipeline(stages=[stage1, stage2])
        session = SessionState(session_id="s1", cwd="/", mcp_servers=[])
        context = PromptContext(
            session_id="s1",
            session=session,
            request_id="req-1",
            params={},
            raw_text="hello",
        )

        await pipeline.run(context)

        stage1.process.assert_awaited_once()
        stage2.process.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pipeline_stops_on_should_stop(self):
        stage1 = MagicMock(spec=PromptStage)
        stage1.name = "Stage1"

        def stop_pipeline(ctx: PromptContext) -> PromptContext:
            ctx.should_stop = True
            return ctx

        stage1.process = AsyncMock(side_effect=stop_pipeline)

        stage2 = MagicMock(spec=PromptStage)
        stage2.name = "Stage2"
        stage2.process = AsyncMock(side_effect=lambda ctx: ctx)

        pipeline = PromptPipeline(stages=[stage1, stage2])
        session = SessionState(session_id="s1", cwd="/", mcp_servers=[])
        context = PromptContext(
            session_id="s1",
            session=session,
            request_id="req-1",
            params={},
            raw_text="hello",
        )

        await pipeline.run(context)

        stage1.process.assert_awaited_once()
        stage2.process.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_pipeline_stops_on_error_response(self):
        stage1 = MagicMock(spec=PromptStage)
        stage1.name = "Stage1"

        def set_error(ctx: PromptContext) -> PromptContext:
            ctx.error_response = ACPMessage.error_response(
                ctx.request_id, code=-32600, message="Test error"
            )
            ctx.should_stop = True
            return ctx

        stage1.process = AsyncMock(side_effect=set_error)

        stage2 = MagicMock(spec=PromptStage)
        stage2.name = "Stage2"
        stage2.process = AsyncMock(side_effect=lambda ctx: ctx)

        pipeline = PromptPipeline(stages=[stage1, stage2])
        session = SessionState(session_id="s1", cwd="/", mcp_servers=[])
        context = PromptContext(
            session_id="s1",
            session=session,
            request_id="req-1",
            params={},
            raw_text="hello",
        )

        result = await pipeline.run(context)

        assert result.should_stop is True
        assert result.error_response is not None
        stage2.process.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_pipeline_handles_exception_in_stage(self):
        stage1 = MagicMock(spec=PromptStage)
        stage1.name = "Stage1"
        stage1.process = AsyncMock(side_effect=RuntimeError("Stage error"))

        pipeline = PromptPipeline(stages=[stage1])
        session = SessionState(session_id="s1", cwd="/", mcp_servers=[])
        context = PromptContext(
            session_id="s1",
            session=session,
            request_id="req-1",
            params={},
            raw_text="hello",
        )

        result = await pipeline.run(context)

        assert result.should_stop is True
        assert result.error_response is not None
        assert "Internal error in Stage1" in result.error_response.error.message

    @pytest.mark.asyncio
    async def test_pipeline_accumulates_notifications(self):
        notif1 = ACPMessage.notification("session/update", {"data": "1"})
        notif2 = ACPMessage.notification("session/update", {"data": "2"})

        stage1 = MagicMock(spec=PromptStage)
        stage1.name = "Stage1"

        def add_notif1(ctx: PromptContext) -> PromptContext:
            ctx.notifications.append(notif1)
            return ctx

        stage1.process = AsyncMock(side_effect=add_notif1)

        stage2 = MagicMock(spec=PromptStage)
        stage2.name = "Stage2"

        def add_notif2(ctx: PromptContext) -> PromptContext:
            ctx.notifications.append(notif2)
            return ctx

        stage2.process = AsyncMock(side_effect=add_notif2)

        pipeline = PromptPipeline(stages=[stage1, stage2])
        session = SessionState(session_id="s1", cwd="/", mcp_servers=[])
        context = PromptContext(
            session_id="s1",
            session=session,
            request_id="req-1",
            params={},
            raw_text="hello",
        )

        result = await pipeline.run(context)

        assert len(result.notifications) == 2
        assert result.notifications[0] == notif1
        assert result.notifications[1] == notif2


class TestValidationStage:
    """Тесты для ValidationStage."""

    @pytest.mark.asyncio
    async def test_validation_passes_for_valid_context(self):
        state_manager = MagicMock()
        stage = ValidationStage(state_manager)

        session = SessionState(session_id="s1", cwd="/", mcp_servers=[])
        context = PromptContext(
            session_id="s1",
            session=session,
            request_id="req-1",
            params={},
            raw_text="hello",
        )

        result = await stage.process(context)

        assert result.should_stop is False
        assert result.error_response is None

    @pytest.mark.asyncio
    async def test_validation_stops_on_active_turn(self):
        state_manager = MagicMock()
        stage = ValidationStage(state_manager)

        session = SessionState(session_id="s1", cwd="/", mcp_servers=[])
        session.active_turn = ActiveTurnState(
            prompt_request_id="req-0",
            session_id="s1",
        )

        context = PromptContext(
            session_id="s1",
            session=session,
            request_id="req-1",
            params={},
            raw_text="hello",
        )

        result = await stage.process(context)

        assert result.should_stop is True
        assert result.error_response is not None
        assert result.error_response.error.code == -32003
        assert "Session busy" in result.error_response.error.message

    @pytest.mark.asyncio
    async def test_validation_stops_on_empty_prompt(self):
        state_manager = MagicMock()
        stage = ValidationStage(state_manager)

        session = SessionState(session_id="s1", cwd="/", mcp_servers=[])
        context = PromptContext(
            session_id="s1",
            session=session,
            request_id="req-1",
            params={},
            raw_text="   ",
        )

        result = await stage.process(context)

        assert result.should_stop is True
        assert result.error_response is not None
        assert result.error_response.error.code == -32602
        assert "Empty prompt" in result.error_response.error.message


class TestSlashCommandStage:
    """Тесты для SlashCommandStage."""

    @pytest.mark.asyncio
    async def test_slash_command_stops_pipeline(self):
        router = MagicMock()
        outcome = MagicMock()
        outcome.notifications = []
        router.route = MagicMock(return_value=outcome)

        stage = SlashCommandStage(router)

        session = SessionState(session_id="s1", cwd="/", mcp_servers=[])
        context = PromptContext(
            session_id="s1",
            session=session,
            request_id="req-1",
            params={},
            raw_text="/help",
        )

        result = await stage.process(context)

        assert result.should_stop is True
        router.route.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_slash_command_passes_through(self):
        router = MagicMock()
        stage = SlashCommandStage(router)

        session = SessionState(session_id="s1", cwd="/", mcp_servers=[])
        context = PromptContext(
            session_id="s1",
            session=session,
            request_id="req-1",
            params={},
            raw_text="hello world",
        )

        result = await stage.process(context)

        assert result.should_stop is False
        router.route.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_slash_command_does_not_stop(self):
        router = MagicMock()
        router.route = MagicMock(return_value=None)

        stage = SlashCommandStage(router)

        session = SessionState(session_id="s1", cwd="/", mcp_servers=[])
        context = PromptContext(
            session_id="s1",
            session=session,
            request_id="req-1",
            params={},
            raw_text="/unknown",
        )

        result = await stage.process(context)

        assert result.should_stop is False
        router.route.assert_called_once()


class TestPlanBuildingStage:
    """Тесты для PlanBuildingStage."""

    @pytest.mark.asyncio
    async def test_plan_building_passes_context_through(self):
        from codelab.server.protocol.handlers.plan_builder import PlanBuilder

        stage = PlanBuildingStage(PlanBuilder())

        session = SessionState(session_id="s1", cwd="/", mcp_servers=[])
        context = PromptContext(
            session_id="s1",
            session=session,
            request_id="req-1",
            params={},
            raw_text="do something",
        )

        result = await stage.process(context)

        # Стадия зарезервирована — контекст проходит без изменений
        assert result is context
        assert result.notifications == []
        assert result.should_stop is False


class TestTurnLifecycleStage:
    """Тесты для TurnLifecycleStage."""

    @pytest.mark.asyncio
    async def test_open_turn_creates_active_turn(self):
        turn_manager = MagicMock()
        active_turn = ActiveTurnState(prompt_request_id="req-1", session_id="s1")
        turn_manager.create_active_turn = MagicMock(return_value=active_turn)

        stage = TurnLifecycleStage(turn_manager, action="open")

        session = SessionState(session_id="s1", cwd="/", mcp_servers=[])
        context = PromptContext(
            session_id="s1",
            session=session,
            request_id="req-1",
            params={},
            raw_text="hello",
        )

        result = await stage.process(context)

        assert result.session.active_turn == active_turn
        turn_manager.create_active_turn.assert_called_once_with("s1", "req-1")

    @pytest.mark.asyncio
    async def test_close_turn_finalizes_and_clears(self):
        turn_manager = MagicMock()
        turn_manager.finalize_turn = MagicMock()
        turn_manager.clear_active_turn = MagicMock()

        stage = TurnLifecycleStage(turn_manager, action="close")

        session = SessionState(session_id="s1", cwd="/", mcp_servers=[])
        session.active_turn = ActiveTurnState(prompt_request_id="req-1", session_id="s1")
        context = PromptContext(
            session_id="s1",
            session=session,
            request_id="req-1",
            params={},
            raw_text="hello",
        )
        context.stop_reason = "end_turn"

        await stage.process(context)

        turn_manager.finalize_turn.assert_called_once_with(session, "end_turn")
        turn_manager.clear_active_turn.assert_called_once_with(session)
