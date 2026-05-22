"""Shared test helpers for server tests."""

from __future__ import annotations

from codelab.server.client_rpc.service import ClientRPCService
from codelab.server.protocol.handlers.client_rpc_handler import ClientRPCHandler
from codelab.server.protocol.handlers.global_policy_manager import GlobalPolicyManager
from codelab.server.protocol.handlers.permission_manager import PermissionManager
from codelab.server.protocol.handlers.pipeline import (
    PlanBuildingStage,
    PromptPipeline,
    SlashCommandStage,
    TurnLifecycleStage,
    ValidationStage,
)
from codelab.server.protocol.handlers.pipeline.stages import LLMLoopStage
from codelab.server.protocol.handlers.pipeline.stages.directives import DirectivesStage
from codelab.server.protocol.handlers.plan_builder import PlanBuilder
from codelab.server.protocol.handlers.prompt_orchestrator import PromptOrchestrator
from codelab.server.protocol.handlers.slash_commands import CommandRegistry, SlashCommandRouter
from codelab.server.protocol.handlers.slash_commands.builtin import (
    HelpCommandHandler,
    ModeCommandHandler,
    StatusCommandHandler,
)
from codelab.server.protocol.handlers.state_manager import StateManager
from codelab.server.protocol.handlers.tool_call_handler import ToolCallHandler
from codelab.server.protocol.handlers.turn_lifecycle_manager import TurnLifecycleManager
from codelab.server.tools.base import ToolRegistry
from codelab.server.tools.registry import SimpleToolRegistry


def make_orchestrator(
    tool_registry: ToolRegistry | None = None,
    client_rpc_service: ClientRPCService | None = None,
    global_policy_manager: GlobalPolicyManager | None = None,
) -> PromptOrchestrator:
    """Build a fully-wired PromptOrchestrator for use in tests."""
    if tool_registry is None:
        tool_registry = SimpleToolRegistry()

    state_manager = StateManager()
    plan_builder = PlanBuilder()
    turn_lifecycle_manager = TurnLifecycleManager()
    tool_call_handler = ToolCallHandler()
    permission_manager = PermissionManager()
    client_rpc_handler = ClientRPCHandler()

    llm_loop_stage = LLMLoopStage(
        tool_registry=tool_registry,
        tool_call_handler=tool_call_handler,
        permission_manager=permission_manager,
        state_manager=state_manager,
        plan_builder=plan_builder,
        global_policy_manager=global_policy_manager,
    )

    command_registry = CommandRegistry()
    slash_router = SlashCommandRouter(command_registry)
    command_registry.register(StatusCommandHandler())
    command_registry.register(ModeCommandHandler())
    command_registry.register(HelpCommandHandler(command_registry))

    pipeline = PromptPipeline(stages=[
        ValidationStage(state_manager),
        SlashCommandStage(slash_router),
        PlanBuildingStage(plan_builder),
        TurnLifecycleStage(turn_lifecycle_manager, action="open"),
        DirectivesStage(tool_registry, permission_manager),
        llm_loop_stage,
        TurnLifecycleStage(turn_lifecycle_manager, action="close"),
    ])

    return PromptOrchestrator(
        state_manager=state_manager,
        plan_builder=plan_builder,
        turn_lifecycle_manager=turn_lifecycle_manager,
        tool_call_handler=tool_call_handler,
        permission_manager=permission_manager,
        client_rpc_handler=client_rpc_handler,
        tool_registry=tool_registry,
        llm_loop_stage=llm_loop_stage,
        client_rpc_service=client_rpc_service,
        global_policy_manager=global_policy_manager,
        command_registry=command_registry,
        pipeline=pipeline,
    )
