"""DI контейнер для серверной части ACP.

Архитектура скоупов:
- APP: синглтоны на всё время жизни сервера (LLM, ToolRegistry, менеджеры, стадии пайплайна)
- REQUEST: на одно WebSocket соединение (ClientRPCService, ACPProtocol)

Пример использования:
    container = make_container(config, storage)
    async with container() as request_scope:
        protocol = await request_scope.get(ACPProtocol)
"""

from __future__ import annotations

from typing import Annotated

import structlog
from dishka import (
    AsyncContainer,
    Provider,
    Scope,
    from_context,
    make_async_container,
    provide,
)

from .agent.orchestrator import AgentOrchestrator
from .agent.state import OrchestratorConfig
from .config import AppConfig
from .llm import LLMProvider, MockLLMProvider
from .llm.base import LLMConfig
from .llm.errors import ProviderNotFoundError
from .llm.registry import LLMProviderRegistry
from .protocol.core import ACPProtocol
from .protocol.handlers.client_rpc_handler import ClientRPCHandler
from .protocol.handlers.config_option_builder import ConfigOptionBuilder
from .protocol.handlers.global_policy_manager import GlobalPolicyManager
from .protocol.handlers.permission_manager import PermissionManager
from .protocol.handlers.pipeline import PromptPipeline
from .protocol.handlers.pipeline.stages import LLMLoopStage
from .protocol.handlers.plan_builder import PlanBuilder
from .protocol.handlers.prompt_orchestrator import PromptOrchestrator
from .protocol.handlers.slash_commands import CommandRegistry, SlashCommandRouter
from .protocol.handlers.slash_commands.builtin import (
    HelpCommandHandler,
    ModeCommandHandler,
    StatusCommandHandler,
)
from .protocol.handlers.state_manager import StateManager
from .protocol.handlers.tool_call_handler import ToolCallHandler
from .protocol.handlers.turn_lifecycle_manager import TurnLifecycleManager
from .rpc_holder import ClientRPCServiceHolder
from .storage import SessionStorage
from .storage.global_policy_storage import GlobalPolicyStorage
from .tools.base import ToolRegistry as ToolRegistryProtocol
from .tools.registry import SimpleToolRegistry


class ManagersProvider(Provider):
    """Провайдер stateless менеджеров (APP scope)."""

    @provide(scope=Scope.APP)
    def get_state_manager(self) -> StateManager:
        """Менеджер состояния сессии."""
        return StateManager()

    @provide(scope=Scope.APP)
    def get_plan_builder(self) -> PlanBuilder:
        """Построитель планов выполнения."""
        return PlanBuilder()

    @provide(scope=Scope.APP)
    def get_turn_lifecycle_manager(self) -> TurnLifecycleManager:
        """Менеджер жизненного цикла prompt-turn."""
        return TurnLifecycleManager()

    @provide(scope=Scope.APP)
    def get_tool_call_handler(self) -> ToolCallHandler:
        """Обработчик tool calls."""
        return ToolCallHandler()

    @provide(scope=Scope.APP)
    def get_permission_manager(self) -> PermissionManager:
        """Менеджер разрешений."""
        return PermissionManager()

    @provide(scope=Scope.APP)
    def get_client_rpc_handler(self) -> ClientRPCHandler:
        """Обработчик agent→client RPC."""
        return ClientRPCHandler()


class SlashCommandsProvider(Provider):
    """Провайдер slash commands (APP scope)."""

    @provide(scope=Scope.APP)
    def get_command_registry(self) -> CommandRegistry:
        """Реестр команд."""
        registry = CommandRegistry()
        registry.register(StatusCommandHandler())
        registry.register(ModeCommandHandler())
        registry.register(HelpCommandHandler(registry))
        return registry

    @provide(scope=Scope.APP)
    def get_slash_command_router(
        self,
        command_registry: CommandRegistry,
    ) -> SlashCommandRouter:
        """Маршрутизатор slash команд."""
        return SlashCommandRouter(command_registry)


class StorageProvider(Provider):
    """Провайдер хранилищ (APP scope)."""

    @provide(scope=Scope.APP)
    def get_global_policy_storage(self) -> GlobalPolicyStorage:
        """Хранилище глобальных политик."""
        return GlobalPolicyStorage()

    @provide(scope=Scope.APP)
    async def get_global_policy_manager(
        self,
        storage: GlobalPolicyStorage,
    ) -> GlobalPolicyManager:
        """Менеджер глобальных политик с инициализацией."""
        manager = GlobalPolicyManager(storage=storage)
        await manager.initialize()
        return manager


class LLMProvider_(Provider):
    """Провайдер LLM провайдеров (APP scope)."""

    @provide(scope=Scope.APP)
    async def get_llm_provider(
        self,
        config: Annotated[AppConfig, from_context(provides=AppConfig)],
        registry: LLMProviderRegistry,
    ) -> LLMProvider:
        """Создаёт LLM провайдера через Registry."""
        provider_id = config.llm.provider

        llm_config = LLMConfig(
            api_key=config.llm.api_key,
            model=config.llm.model,
            base_url=config.llm.base_url,
            temperature=config.llm.temperature,
            max_tokens=config.llm.max_tokens,
        )

        try:
            return await registry.create_provider(provider_id, llm_config)
        except ProviderNotFoundError:
            # Fallback на mock если провайдер не зарегистрирован
            provider = MockLLMProvider()
            await provider.initialize(LLMConfig(
                model=config.llm.model,
                temperature=config.llm.temperature,
                max_tokens=config.llm.max_tokens,
            ))
            return provider


class ToolsProvider(Provider):
    """Провайдер инструментов (APP scope)."""

    @provide(scope=Scope.APP)
    def get_tool_registry(self) -> ToolRegistryProtocol:
        """Реестр инструментов."""
        return SimpleToolRegistry()


class AgentProvider(Provider):
    """Провайдер агентов (APP scope)."""

    @provide(scope=Scope.APP)
    def get_agent_orchestrator(
        self,
        config: Annotated[AppConfig, from_context(provides=AppConfig)],
        llm_provider: LLMProvider,
        tool_registry: ToolRegistryProtocol,
        llm_registry: LLMProviderRegistry,
    ) -> AgentOrchestrator:
        """Создаёт AgentOrchestrator."""
        orchestrator_config = OrchestratorConfig(
            enabled=True,
            agent_class="naive",
            model=config.llm.model,
            temperature=config.llm.temperature,
            max_tokens=config.llm.max_tokens,
            llm_provider_class=config.llm.provider,
        )

        # Создать model resolver для multi-provider support
        from codelab.server.llm.resolver import ModelResolver

        model_resolver = ModelResolver(
            registry=llm_registry,
            default_provider=config.llm.provider,
            provider_configs=config.llm.providers,
        )

        return AgentOrchestrator(
            config=orchestrator_config,
            llm_provider=llm_provider,
            tool_registry=tool_registry,
            llm_registry=llm_registry,
            model_resolver=model_resolver,
        )


class PipelineProvider(Provider):
    """Провайдер pipeline стадий (APP scope)."""

    @provide(scope=Scope.APP)
    def get_llm_loop_stage(
        self,
        tool_registry: ToolRegistryProtocol,
        tool_call_handler: ToolCallHandler,
        permission_manager: PermissionManager,
        state_manager: StateManager,
        plan_builder: PlanBuilder,
        global_policy_manager: GlobalPolicyManager,
    ) -> LLMLoopStage:
        """Стадия LLM loop."""
        from .protocol.handlers.pipeline.stages import LLMLoopStage
        return LLMLoopStage(
            tool_registry=tool_registry,
            tool_call_handler=tool_call_handler,
            permission_manager=permission_manager,
            state_manager=state_manager,
            plan_builder=plan_builder,
            global_policy_manager=global_policy_manager,
        )

    @provide(scope=Scope.APP)
    def get_prompt_pipeline(
        self,
        state_manager: StateManager,
        slash_router: SlashCommandRouter,
        plan_builder: PlanBuilder,
        turn_lifecycle_manager: TurnLifecycleManager,
        tool_registry: ToolRegistryProtocol,
        permission_manager: PermissionManager,
        llm_loop_stage: LLMLoopStage,
    ) -> PromptPipeline:
        """Собирает PromptPipeline из всех стадий."""
        from .protocol.handlers.pipeline import (
            PlanBuildingStage,
            SlashCommandStage,
            TurnLifecycleStage,
            ValidationStage,
        )
        from .protocol.handlers.pipeline.stages.directives import DirectivesStage

        return PromptPipeline(stages=[
            ValidationStage(state_manager),
            SlashCommandStage(slash_router),
            PlanBuildingStage(plan_builder),
            TurnLifecycleStage(turn_lifecycle_manager, action="open"),
            DirectivesStage(tool_registry, permission_manager),
            llm_loop_stage,
            TurnLifecycleStage(turn_lifecycle_manager, action="close"),
        ])


class PromptOrchestratorProvider(Provider):
    """Провайдер PromptOrchestrator (APP scope)."""

    @provide(scope=Scope.APP)
    def get_client_rpc_service_holder(self) -> ClientRPCServiceHolder:
        """Создаёт holder для ClientRPCService (обновляется per-request)."""
        return ClientRPCServiceHolder()

    @provide(scope=Scope.APP)
    def get_prompt_orchestrator(
        self,
        state_manager: StateManager,
        plan_builder: PlanBuilder,
        turn_lifecycle_manager: TurnLifecycleManager,
        tool_call_handler: ToolCallHandler,
        permission_manager: PermissionManager,
        client_rpc_handler: ClientRPCHandler,
        tool_registry: ToolRegistryProtocol,
        llm_loop_stage: LLMLoopStage,
        holder: ClientRPCServiceHolder,
        global_policy_manager: GlobalPolicyManager,
        command_registry: CommandRegistry,
        pipeline: PromptPipeline,
    ) -> PromptOrchestrator:
        """Создаёт PromptOrchestrator со всеми зависимостями."""
        return PromptOrchestrator(
            state_manager=state_manager,
            plan_builder=plan_builder,
            turn_lifecycle_manager=turn_lifecycle_manager,
            tool_call_handler=tool_call_handler,
            permission_manager=permission_manager,
            client_rpc_handler=client_rpc_handler,
            tool_registry=tool_registry,
            llm_loop_stage=llm_loop_stage,
            client_rpc_service_holder=holder,
            global_policy_manager=global_policy_manager,
            command_registry=command_registry,
            pipeline=pipeline,
        )


logger = structlog.get_logger()


class RegistryProvider(Provider):
    """Провайдер LLM Registry и ConfigOptionBuilder (APP scope)."""

    @provide(scope=Scope.APP)
    def get_llm_registry(
        self,
        config: Annotated[AppConfig, from_context(provides=AppConfig)],
    ) -> LLMProviderRegistry:
        """Создаёт реестр провайдеров с ProviderInfo из AppConfig."""
        registry = LLMProviderRegistry()

        # Регистрируем провайдеры из AppConfig (загружено из TOML при load())
        for provider_id, provider_cfg in config.llm.providers.items():
            provider_info = provider_cfg.to_provider_info(provider_id)
            factory = self._get_provider_factory(provider_id)
            registry.register(provider_id, factory, info=provider_info)
            logger.debug(
                "provider registered from config",
                provider_id=provider_id,
                models_count=len(provider_cfg.models),
            )

        # Mock провайдер без TOML config
        if "mock" not in registry.get_registered_providers():
            registry.register("mock", lambda: MockLLMProvider())

        logger.info(
            "llm registry created",
            providers_count=len(registry.get_registered_providers()),
            models_count=len(registry.list_all_models()),
        )

        return registry

    @staticmethod
    def _get_provider_factory(provider_id: str):
        """Возвращает factory-функцию для провайдера."""
        from codelab.server.llm.providers.anthropic import AnthropicProvider
        from codelab.server.llm.providers.go import GoProvider
        from codelab.server.llm.providers.lmstudio import LMStudioProvider
        from codelab.server.llm.providers.ollama import OllamaProvider
        from codelab.server.llm.providers.openai import OpenAIProvider
        from codelab.server.llm.providers.openrouter import OpenRouterProvider
        from codelab.server.llm.providers.zen import ZenProvider

        factories = {
            "openai": OpenAIProvider,
            "openrouter": OpenRouterProvider,
            "anthropic": AnthropicProvider,
            "zen": ZenProvider,
            "go": GoProvider,
            "ollama": OllamaProvider,
            "lmstudio": LMStudioProvider,
        }
        return factories.get(provider_id, lambda: MockLLMProvider())

    @provide(scope=Scope.APP)
    def get_config_option_builder(
        self,
        registry: LLMProviderRegistry,
    ) -> ConfigOptionBuilder:
        """Создаёт билдер config options."""
        return ConfigOptionBuilder(registry)


class RequestProvider(Provider):
    """Провайдер REQUEST-scoped зависимостей (на WebSocket соединение)."""

    @provide(scope=Scope.REQUEST)
    def get_acp_protocol(
        self,
        require_auth: Annotated[bool, from_context(provides=bool)],
        auth_api_key: Annotated[str | None, from_context(provides=str | None)],
        storage: SessionStorage,
        agent_orchestrator: AgentOrchestrator,
        tool_registry: ToolRegistryProtocol,
        prompt_orchestrator: PromptOrchestrator,
        holder: ClientRPCServiceHolder,
        registry: LLMProviderRegistry,
        config_option_builder: ConfigOptionBuilder,
    ) -> ACPProtocol:
        """Создаёт ACPProtocol для текущего соединения."""
        # ClientRPCService создаётся вручную в handle_ws_request (требует runtime callback)
        # и устанавливается в holder перед созданием ACPProtocol
        client_rpc_service = holder.service

        return ACPProtocol(
            require_auth=require_auth,
            auth_api_key=auth_api_key,
            storage=storage,
            agent_orchestrator=agent_orchestrator,
            client_rpc_service=client_rpc_service,
            tool_registry=tool_registry,
            prompt_orchestrator=prompt_orchestrator,
            llm_registry=registry,
            config_option_builder=config_option_builder,
        )


def make_container(
    config: AppConfig,
    storage: SessionStorage,
    *,
    require_auth: bool = False,
    auth_api_key: str | None = None,
) -> AsyncContainer:
    """Создаёт DI контейнер со всеми провайдерами.

    Args:
        config: Глобальная конфигурация приложения.
        storage: Хранилище сессий.
        require_auth: Требовать аутентификацию.
        auth_api_key: API ключ для аутентификации.

    Returns:
        AsyncContainer для получения зависимостей.
    """
    container = make_async_container(
        ManagersProvider(),
        SlashCommandsProvider(),
        StorageProvider(),
        RegistryProvider(),
        LLMProvider_(),
        ToolsProvider(),
        AgentProvider(),
        PipelineProvider(),
        PromptOrchestratorProvider(),
        RequestProvider(),
        context={
            AppConfig: config,
            SessionStorage: storage,
            bool: require_auth,
            str | None: auth_api_key,
        },
    )
    return container
