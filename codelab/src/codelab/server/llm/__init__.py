"""LLM провайдеры и интерфейсы для работы с языковыми моделями.

Мульти-провайдер архитектура с поддержкой:
- OpenAI, Anthropic, OpenRouter, Zen, Go, Ollama, LMStudio
- Registry для динамической регистрации провайдеров
- Fallback цепочки при ошибках
- Model discovery и telemetry (extension points)
- ProviderEventBus для событий жизненного цикла
"""

# Базовые классы и модели
from codelab.server.llm.base import (
    LLMCapabilities,
    LLMConfig,
    LLMMessage,
    LLMProvider,
    LLMResponse,  # Алиас для CompletionResponse
    LLMToolCall,
)

# Модели данных
from codelab.server.llm.models import (
    CompletionRequest,
    CompletionResponse,
    ModelInfo,
    ProviderInfo,
    StopReason,
)

# Исключения
from codelab.server.llm.errors import (
    AllProvidersFailed,
    ModelNotFoundError,
    ProviderError,
    ProviderErrorType,
    ProviderNotFoundError,
)

# Registry и Resolver
from codelab.server.llm.registry import LLMProviderRegistry
from codelab.server.llm.resolver import ModelRef, ModelResolver

# Fallback система
from codelab.server.llm.fallback import (
    CircuitBreaker,
    FallbackConfig,
    FallbackContext,
    FallbackOrchestrator,
    FallbackStrategy,
    FallbackStrategyFactory,
    SequentialFallback,
)

# Discovery система
from codelab.server.llm.discovery import (
    DiscoveryConfig,
    ModelDiscovery,
    StaticDiscovery,
)

# Telemetry система
from codelab.server.llm.telemetry import (
    NoOpTelemetry,
    TelemetrySink,
)

# Event Bus
from codelab.server.llm.events import (
    ProviderEvent,
    ProviderEventBus,
    ProviderFailed,
    ProviderInitialized,
    FallbackTriggered,
    ModelsUpdated,
    event_bus,
)

# Провайдеры
from codelab.server.llm.providers import (
    OpenAICompatibleProvider,
    OpenAIProvider,
)
from codelab.server.llm.providers.anthropic import AnthropicProvider
from codelab.server.llm.providers.openrouter import OpenRouterProvider
from codelab.server.llm.providers.zen import ZenProvider
from codelab.server.llm.providers.go import GoProvider
from codelab.server.llm.providers.ollama import OllamaProvider
from codelab.server.llm.providers.lmstudio import LMStudioProvider
from codelab.server.llm.mock_provider import MockLLMProvider

__all__ = [
    # Базовые классы
    "LLMProvider",
    "LLMConfig",
    "LLMCapabilities",
    "LLMMessage",
    "LLMToolCall",
    "LLMResponse",  # Алиас
    # Модели
    "CompletionRequest",
    "CompletionResponse",
    "ModelInfo",
    "ProviderInfo",
    "StopReason",
    # Исключения
    "ProviderError",
    "ProviderErrorType",
    "ProviderNotFoundError",
    "ModelNotFoundError",
    "AllProvidersFailed",
    # Registry и Resolver
    "LLMProviderRegistry",
    "ModelRef",
    "ModelResolver",
    # Fallback
    "FallbackStrategy",
    "FallbackContext",
    "SequentialFallback",
    "CircuitBreaker",
    "FallbackConfig",
    "FallbackStrategyFactory",
    "FallbackOrchestrator",
    # Discovery
    "ModelDiscovery",
    "StaticDiscovery",
    "DiscoveryConfig",
    # Telemetry
    "TelemetrySink",
    "NoOpTelemetry",
    # Events
    "ProviderEvent",
    "ProviderEventBus",
    "ProviderInitialized",
    "ProviderFailed",
    "FallbackTriggered",
    "ModelsUpdated",
    "event_bus",
    # Провайдеры
    "OpenAICompatibleProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "OpenRouterProvider",
    "ZenProvider",
    "GoProvider",
    "OllamaProvider",
    "LMStudioProvider",
    "MockLLMProvider",
]
