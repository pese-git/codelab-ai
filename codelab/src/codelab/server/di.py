"""DI контейнер для серверной части ACP.

Использует Dishka для управления зависимостями APP scope:
- APP: LLMProvider, ToolRegistry, AgentOrchestrator, GlobalPolicyManager

REQUEST-scoped объекты (PromptOrchestrator, ACPProtocol) создаются вручную
в handle_ws_request, т.к. требуют ClientRPCService который доступен только
во время выполнения.

Пример использования:
    container = make_container(config, storage)
    async with container() as app_scope:
        llm = await app_scope.get(LLMProvider | None)
"""

from __future__ import annotations

from typing import Annotated

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
from .llm import LLMProvider, MockLLMProvider, OpenAIProvider
from .protocol.handlers.global_policy_manager import GlobalPolicyManager
from .storage import SessionStorage
from .storage.global_policy_storage import GlobalPolicyStorage
from .tools.base import ToolRegistry as ToolRegistryProtocol
from .tools.registry import SimpleToolRegistry


class ServerProvider(Provider):
    """Провайдер зависимостей серверного уровня (APP scope)."""

    @provide(scope=Scope.APP)
    async def get_llm_provider(
        self,
        config: Annotated[AppConfig, from_context(provides=AppConfig)],
    ) -> LLMProvider | None:
        """Создаёт LLM провайдера на основе конфигурации."""
        if config.llm.provider == "openai":
            provider = OpenAIProvider()
            config_dict = {
                "api_key": config.llm.api_key,
                "model": config.llm.model,
                "temperature": config.llm.temperature,
                "max_tokens": config.llm.max_tokens,
            }
            if config.llm.base_url:
                config_dict["base_url"] = config.llm.base_url
            await provider.initialize(config_dict)
            return provider
        elif config.llm.provider == "mock":
            return MockLLMProvider()
        else:
            return MockLLMProvider()

    @provide(scope=Scope.APP)
    def get_tool_registry(self) -> ToolRegistryProtocol:
        """Создаёт реестр инструментов для всего сервера."""
        return SimpleToolRegistry()

    @provide(scope=Scope.APP)
    def get_agent_orchestrator(
        self,
        config: Annotated[AppConfig, from_context(provides=AppConfig)],
        llm_provider: LLMProvider | None,
        tool_registry: ToolRegistryProtocol,
    ) -> AgentOrchestrator | None:
        """Создаёт AgentOrchestrator если есть LLM провайдер."""
        if llm_provider is None:
            return None

        orchestrator_config = OrchestratorConfig(
            enabled=True,
            agent_class="naive",
            model=config.llm.model,
            temperature=config.llm.temperature,
            max_tokens=config.llm.max_tokens,
            llm_provider_class="openai" if config.llm.provider == "openai" else "mock",
        )

        return AgentOrchestrator(
            config=orchestrator_config,
            llm_provider=llm_provider,
            tool_registry=tool_registry,
        )

    @provide(scope=Scope.APP)
    def get_global_policy_storage(self) -> GlobalPolicyStorage:
        """Создаёт хранилище глобальных политик."""
        return GlobalPolicyStorage()

    @provide(scope=Scope.APP)
    async def get_global_policy_manager(
        self,
        storage: GlobalPolicyStorage,
    ) -> GlobalPolicyManager:
        """Создаёт GlobalPolicyManager и инициализирует его."""
        manager = GlobalPolicyManager(storage=storage)
        await manager.initialize()
        return manager


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
        ServerProvider(),
        context={
            AppConfig: config,
            SessionStorage: storage,
            bool: require_auth,
            str | None: auth_api_key,
        },
    )
    return container
