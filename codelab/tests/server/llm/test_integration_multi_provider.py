"""Интеграционные тесты мульти-провайдер LLM архитектуры.

Тестируют полный поток:
- Registry → Resolver → Provider → Response
- Fallback chain при ошибках
- Model switching mid-session
- E2E flow: initialize → session/new → configOptions → set_config_option(model) → prompt
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from codelab.server.agent.orchestrator import AgentOrchestrator
from codelab.server.agent.state import OrchestratorConfig
from codelab.server.llm.base import LLMCapabilities, LLMConfig, LLMProvider, LLMMessage
from codelab.server.llm.errors import ProviderError, ProviderErrorType
from codelab.server.llm.mock_provider import MockLLMProvider
from codelab.server.llm.models import (
    CompletionRequest,
    CompletionResponse,
    ModelInfo,
    ProviderInfo,
    StopReason,
)
from codelab.server.llm.registry import LLMProviderRegistry
from codelab.server.llm.resolver import ModelRef, ModelResolver
from codelab.server.messages import ACPMessage
from codelab.server.protocol import ACPProtocol
from codelab.server.protocol.handlers.config import session_set_config_option
from codelab.server.protocol.handlers.config_option_builder import ConfigOptionBuilder
from codelab.server.protocol.state import SessionState
from codelab.server.storage.memory import InMemoryStorage
from codelab.server.tools.registry import SimpleToolRegistry


class FailingProvider(LLMProvider):
    """Провайдер который всегда падает (для тестов fallback)."""

    def __init__(self, provider_id: str = "failing", error_message: str = "Primary provider failed") -> None:
        self._provider_id = provider_id
        self._error_message = error_message
        self._config: LLMConfig | None = None

    @property
    def name(self) -> str:
        return self._provider_id

    @property
    def capabilities(self) -> LLMCapabilities:
        return LLMCapabilities(
            supports_tools=True,
            supports_streaming=True,
            supports_function_calling=True,
        )

    async def initialize(self, config: LLMConfig) -> None:
        self._config = config

    async def create_completion(self, request: CompletionRequest) -> CompletionResponse:
        raise ProviderError(
            message=self._error_message,
            error_type=ProviderErrorType.INTERNAL_ERROR,
        )

    async def stream_completion(
        self,
        request: CompletionRequest,
    ) -> AsyncGenerator[CompletionResponse, None]:
        raise ProviderError(
            message=self._error_message,
            error_type=ProviderErrorType.INTERNAL_ERROR,
        )


class SuccessProvider(LLMProvider):
    """Провайдер который всегда успешен (для тестов fallback)."""

    def __init__(self, provider_id: str = "success", response_text: str = "Fallback success") -> None:
        self._provider_id = provider_id
        self._response_text = response_text
        self._config: LLMConfig | None = None

    @property
    def name(self) -> str:
        return self._provider_id

    @property
    def capabilities(self) -> LLMCapabilities:
        return LLMCapabilities(
            supports_tools=True,
            supports_streaming=True,
            supports_function_calling=True,
        )

    async def initialize(self, config: LLMConfig) -> None:
        self._config = config

    async def create_completion(self, request: CompletionRequest) -> CompletionResponse:
        return CompletionResponse(
            text=self._response_text,
            stop_reason=StopReason.END_TURN,
            model=request.model,
        )

    async def stream_completion(
        self,
        request: CompletionRequest,
    ) -> AsyncGenerator[CompletionResponse, None]:
        yield CompletionResponse(
            text=self._response_text,
            stop_reason=StopReason.END_TURN,
            model=request.model,
        )


# ============================================================================
# 17.4 Интеграционный тест: Registry → Resolver → Provider → Response
# ============================================================================


@pytest.mark.asyncio
async def test_registry_resolver_provider_response_chain() -> None:
    """Проверить полную цепочку: Registry регистрирует → Resolver резолвит → Provider отвечает."""
    # Arrange — создать registry и зарегистрировать провайдеров
    registry = LLMProviderRegistry()

    # Зарегистрировать mock провайдер
    mock_provider = MockLLMProvider(response="Hello from mock")
    registry.register(
        "mock",
        lambda: mock_provider,
        info=ProviderInfo(
            id="mock",
            name="Mock Provider",
            models=[
                ModelInfo(id="mock-model", provider_id="mock", name="Mock Model"),
            ],
        ),
    )

    # Создать resolver
    resolver = ModelResolver(registry, default_provider="mock")

    # Act — резолвить модель
    provider, model_id = await resolver.resolve("mock/mock-model")

    # Assert — проверить что провайдер получен
    assert provider.name == "mock"
    assert model_id == "mock-model"

    # Act — создать completion
    request = CompletionRequest(
        messages=[{"role": "user", "content": "test"}],
        model=model_id,
    )
    response = await provider.create_completion(request)

    # Assert — проверить ответ
    assert response.text == "Hello from mock"
    assert response.stop_reason == StopReason.END_TURN


@pytest.mark.asyncio
async def test_registry_resolver_with_default_provider() -> None:
    """Проверить что resolver использует default_provider если нет provider_id."""
    registry = LLMProviderRegistry()
    mock_provider = MockLLMProvider(response="Default provider response")
    registry.register(
        "mock",
        lambda: mock_provider,
        info=ProviderInfo(
            id="mock",
            name="Mock Provider",
            models=[ModelInfo(id="gpt-4o", provider_id="mock", name="GPT-4o")],
        ),
    )

    resolver = ModelResolver(registry, default_provider="mock")

    # Резолвить без provider_id — должен использовать default
    provider, model_id = await resolver.resolve("gpt-4o")

    assert provider.name == "mock"
    assert model_id == "gpt-4o"


@pytest.mark.asyncio
async def test_registry_multiple_providers_resolution() -> None:
    """Проверить регистрацию нескольких провайдеров и разрешение."""
    registry = LLMProviderRegistry()

    # Зарегистрировать несколько провайдеров
    registry.register(
        "provider-a",
        lambda: MockLLMProvider(response="A"),
        info=ProviderInfo(
            id="provider-a",
            name="Provider A",
            models=[ModelInfo(id="model-a1", provider_id="provider-a", name="Model A1")],
        ),
    )
    registry.register(
        "provider-b",
        lambda: MockLLMProvider(response="B"),
        info=ProviderInfo(
            id="provider-b",
            name="Provider B",
            models=[ModelInfo(id="model-b1", provider_id="provider-b", name="Model B1")],
        ),
    )

    resolver = ModelResolver(registry, default_provider="provider-a")

    # Резолвить provider-a
    provider_a, _ = await resolver.resolve("provider-a/model-a1")
    assert provider_a.name == "mock"  # MockLLMProvider всегда возвращает "mock"

    # Резолвить provider-b
    provider_b, _ = await resolver.resolve("provider-b/model-b1")
    assert provider_b.name == "mock"  # MockLLMProvider всегда возвращает "mock"


# ============================================================================
# 17.2 E2E тест: fallback chain — primary fails → fallback succeeds
# ============================================================================


@pytest.mark.asyncio
async def test_fallback_chain_primary_fails_fallback_succeeds() -> None:
    """Проверить fallback цепочку: primary падает → fallback успешен."""
    from codelab.server.llm.fallback import FallbackOrchestrator, SequentialFallback
    from codelab.server.llm.fallback.config import FallbackConfig

    # Arrange — создать registry с failing и success провайдерами
    registry = LLMProviderRegistry()

    registry.register(
        "failing",
        lambda: FailingProvider(provider_id="failing", error_message="Primary failed"),
        info=ProviderInfo(
            id="failing",
            name="Failing Provider",
            models=[ModelInfo(id="fail-model", provider_id="failing", name="Fail Model")],
        ),
    )
    registry.register(
        "success",
        lambda: SuccessProvider(provider_id="success", response_text="Fallback worked"),
        info=ProviderInfo(
            id="success",
            name="Success Provider",
            models=[ModelInfo(id="success-model", provider_id="success", name="Success Model")],
        ),
    )

    resolver = ModelResolver(registry, default_provider="failing")

    # Создать fallback orchestrator
    fallback = SequentialFallback(
        provider_order=["failing", "success"],
    )
    config = FallbackConfig(enabled=True, max_attempts=3, retry_on=[ProviderErrorType.INTERNAL_ERROR])
    orchestrator = FallbackOrchestrator(strategy=fallback, config=config)

    # Act — выполнить completion с fallback
    request = CompletionRequest(
        messages=[LLMMessage(role="user", content="test fallback")],
        model="fail-model",
    )

    # Получить провайдеров для fallback
    failing_provider, _ = await resolver.resolve("failing/fail-model")
    success_provider, _ = await resolver.resolve("success/success-model")

    providers = [failing_provider, success_provider]

    response = await orchestrator.execute_completion(
        providers=providers,
        request=request,
    )

    # Assert — fallback сработал
    assert response.text == "Fallback worked"
    assert response.stop_reason == StopReason.END_TURN


# ============================================================================
# 17.1 E2E тест: full flow — initialize → session/new → configOptions → set_config_option(model) → prompt
# ============================================================================


@pytest.mark.asyncio
async def test_e2e_full_flow_with_model_config() -> None:
    """Полный поток: initialize → session/new → configOptions → set_config_option(model) → prompt."""
    # Arrange — создать registry с mock провайдером
    registry = LLMProviderRegistry()
    mock_provider = MockLLMProvider(response="E2E test response")
    registry.register(
        "mock",
        lambda: mock_provider,
        info=ProviderInfo(
            id="mock",
            name="Mock Provider",
            models=[
                ModelInfo(id="model-v1", provider_id="mock", name="Model V1"),
                ModelInfo(id="model-v2", provider_id="mock", name="Model V2"),
            ],
        ),
    )

    # Создать config specs из registry
    config_option_builder = ConfigOptionBuilder(registry)
    model_config_option = config_option_builder.build_model_config_option(
        default_model="mock/model-v1",
    )

    config_specs = {
        "model": {
            "name": "Model",
            "category": "model",
            "default": "mock/model-v1",
            "options": model_config_option["options"],
        },
    }

    # Создать storage с сессией
    storage = InMemoryStorage()
    session = SessionState(
        session_id="e2e-session",
        cwd="/tmp/test",
        config_values={"model": "mock/model-v1"},
    )
    await storage.save_session(session)

    # Act 1 — получить configOptions
    outcome = await session_set_config_option(
        request_id="req-1",
        params={
            "sessionId": "e2e-session",
            "configId": "model",
            "value": "mock/model-v2",
        },
        storage=storage,
        config_specs=config_specs,
    )

    # Assert 1 — configOptions обновлены
    assert outcome.response is not None
    assert outcome.response.result is not None
    result = outcome.response.result
    assert "configOptions" in result
    config_options = result["configOptions"]
    model_option = next(
        (opt for opt in config_options if opt["id"] == "model"),
        None,
    )
    assert model_option is not None
    assert model_option["currentValue"] == "mock/model-v2"


@pytest.mark.asyncio
async def test_e2e_initialize_session_prompt_with_mock_provider() -> None:
    """E2E: initialize → session/new → session/prompt с mock провайдером."""
    # Arrange — создать orchestrator с mock provider
    config = OrchestratorConfig(agent_class="naive")
    llm_provider = MockLLMProvider(response="Hello from E2E test")
    tool_registry = SimpleToolRegistry()
    agent_orchestrator = AgentOrchestrator(config, llm_provider, tool_registry)

    protocol = ACPProtocol(agent_orchestrator=agent_orchestrator)

    # Act — initialize
    init_outcome = await protocol.handle(
        ACPMessage.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {},
            },
        )
    )
    assert init_outcome.response is not None
    assert init_outcome.response.error is None

    # Act — session/new
    new_session = await protocol.handle(
        ACPMessage.request("session/new", {"cwd": "/tmp", "mcpServers": []})
    )
    assert new_session.response is not None
    assert isinstance(new_session.response.result, dict)
    session_id = new_session.response.result["sessionId"]

    # Act — session/prompt
    prompt_outcome = await protocol.handle(
        ACPMessage.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": "Hello"}],
            },
        )
    )

    # Assert — prompt успешен
    assert prompt_outcome.response is not None
    assert prompt_outcome.response.error is None
    assert prompt_outcome.response.result is not None
    assert prompt_outcome.response.result.get("stopReason") == "end_turn"


# ============================================================================
# 17.3 E2E тест: model switching mid-session
# ============================================================================


@pytest.mark.asyncio
async def test_model_switching_mid_session() -> None:
    """Проверить переключение модели mid-session через set_config_option."""
    # Arrange — создать storage с сессией
    storage = InMemoryStorage()
    session = SessionState(
        session_id="switch-session",
        cwd="/tmp/test",
        config_values={"model": "mock/model-v1"},
    )
    await storage.save_session(session)

    # Создать registry с несколькими моделями
    registry = LLMProviderRegistry()
    registry.register(
        "mock",
        lambda: MockLLMProvider(response="Model V1 response"),
        info=ProviderInfo(
            id="mock",
            name="Mock Provider",
            models=[
                ModelInfo(id="model-v1", provider_id="mock", name="Model V1"),
                ModelInfo(id="model-v2", provider_id="mock", name="Model V2"),
            ],
        ),
    )

    config_option_builder = ConfigOptionBuilder(registry)
    model_config_option = config_option_builder.build_model_config_option(
        default_model="mock/model-v1",
    )

    config_specs = {
        "model": {
            "name": "Model",
            "category": "model",
            "default": "mock/model-v1",
            "options": model_config_option["options"],
        },
    }

    # Act 1 — переключить на model-v2
    outcome1 = await session_set_config_option(
        request_id="req-1",
        params={
            "sessionId": "switch-session",
            "configId": "model",
            "value": "mock/model-v2",
        },
        storage=storage,
        config_specs=config_specs,
    )

    # Assert 1 — модель переключена
    assert outcome1.response is not None
    assert outcome1.response.result is not None
    config_options = outcome1.response.result["configOptions"]
    model_option = next(opt for opt in config_options if opt["id"] == "model")
    assert model_option["currentValue"] == "mock/model-v2"

    # Act 2 — переключить обратно на model-v1
    outcome2 = await session_set_config_option(
        request_id="req-2",
        params={
            "sessionId": "switch-session",
            "configId": "model",
            "value": "mock/model-v1",
        },
        storage=storage,
        config_specs=config_specs,
    )

    # Assert 2 — модель переключена обратно
    assert outcome2.response is not None
    config_options = outcome2.response.result["configOptions"]
    model_option = next(opt for opt in config_options if opt["id"] == "model")
    assert model_option["currentValue"] == "mock/model-v1"


@pytest.mark.asyncio
async def test_model_switching_invalid_model() -> None:
    """Проверить ошибку при переключении на несуществующую модель."""
    storage = InMemoryStorage()
    session = SessionState(
        session_id="invalid-switch-session",
        cwd="/tmp/test",
        config_values={"model": "mock/model-v1"},
    )
    await storage.save_session(session)

    registry = LLMProviderRegistry()
    registry.register(
        "mock",
        lambda: MockLLMProvider(response="response"),
        info=ProviderInfo(
            id="mock",
            name="Mock Provider",
            models=[ModelInfo(id="model-v1", provider_id="mock", name="Model V1")],
        ),
    )

    config_option_builder = ConfigOptionBuilder(registry)
    model_config_option = config_option_builder.build_model_config_option(
        default_model="mock/model-v1",
    )

    config_specs = {
        "model": {
            "name": "Model",
            "category": "model",
            "default": "mock/model-v1",
            "options": model_config_option["options"],
        },
    }

    # Act — переключить на несуществующую модель
    outcome = await session_set_config_option(
        request_id="req-1",
        params={
            "sessionId": "invalid-switch-session",
            "configId": "model",
            "value": "mock/nonexistent-model",
        },
        storage=storage,
        config_specs=config_specs,
    )

    # Assert — ошибка
    assert outcome.response is not None
    assert outcome.response.error is not None
    assert "not found" in outcome.response.error.message.lower() or "invalid" in outcome.response.error.message.lower()
