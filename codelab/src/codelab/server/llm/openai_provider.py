"""OpenAI LLM провайдер."""
# mypy: ignore-errors

import json
from collections.abc import AsyncGenerator
from typing import Any

import structlog
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from codelab.server.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMToolCall

# Используем structlog для структурированного логирования
logger = structlog.get_logger()


class OpenAIProvider(LLMProvider):
    """Провайдер для взаимодействия с OpenAI API.

    Поддерживает:
    - Обычные completion с инструментами
    - Потоковые completion
    - Преобразование инструментов в OpenAI формат
    """

    def __init__(self) -> None:
        """Инициализация провайдера."""
        self._client: AsyncOpenAI | None = None
        self._model: str = "gpt-4o"
        self._temperature: float = 0.7
        self._max_tokens: int = 8192

    async def initialize(self, config: dict[str, Any]) -> None:
        """Инициализировать провайдер с конфигурацией.

        Args:
            config: {
                "api_key": str (опционально, по умолчанию из переменной окружения),
                "model": str (по умолчанию "gpt-4o"),
                "temperature": float (по умолчанию 0.7),
                "max_tokens": int (по умолчанию 8192),
                "base_url": str (опционально),
            }
        """
        logger.debug("initializing openai provider")

        api_key = config.get("api_key")
        self._model = config.get("model", "gpt-4o")
        self._temperature = config.get("temperature", 0.7)
        self._max_tokens = config.get("max_tokens", 8192)

        base_url = config.get("base_url")

        # Создать async клиента OpenAI
        self._client = AsyncOpenAI(
            api_key=api_key,  # Если None, использует OPENAI_API_KEY из env
            base_url=base_url,  # Если None, использует дефолтный
        )

        logger.info(
            "openai provider initialized",
            model=self._model,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            has_base_url=bool(base_url),
        )

    async def create_completion(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Получить завершение от OpenAI API.

        Args:
            messages: История сообщений
            tools: Список инструментов в OpenAI формате
            **kwargs: Дополнительные параметры (temperature, max_tokens, etc.)

        Returns:
            LLMResponse с текстом, tool calls и stop reason
        """
        if self._client is None:
            msg = "Провайдер не инициализирован"
            raise RuntimeError(msg)

        logger.debug(
            "openai create_completion request starting",
            num_messages=len(messages),
            has_tools=bool(tools),
            num_tools=len(tools) if tools else 0,
        )

        # Преобразовать сообщения в формат OpenAI
        openai_messages = self._convert_to_openai_format(messages)
        
        # Валидировать историю сообщений
        try:
            self._validate_message_history(openai_messages)
        except ValueError as e:
            logger.error(
                "message history validation failed",
                error=str(e),
                num_messages=len(openai_messages),
            )
            raise

        # Подготовить параметры запроса
        request_params = {
            "model": self._model,
            "messages": openai_messages,
            "temperature": kwargs.get("temperature", self._temperature),
            "max_tokens": kwargs.get("max_tokens", self._max_tokens),
        }

        # Добавить инструменты если есть
        if tools:
            request_params["tools"] = tools
            request_params["tool_choice"] = "auto"

        try:
            logger.debug("sending request to openai api")
            response: ChatCompletion = await self._client.chat.completions.create(
                **request_params
            )
            logger.debug(
                "received openai api response",
                finish_reason=response.choices[0].finish_reason if response.choices else None,
            )

            parsed_response = self._parse_completion(response)

            # Логирование полученного ответа от LLM
            logger.info(
                "llm response received",
                response_length=len(parsed_response.text),
                has_tool_calls=bool(parsed_response.tool_calls),
            )
            logger.debug(
                "llm response content",
                content=parsed_response.text[:200],
            )
            logger.debug(
                "openai completion parsed",
                response_length=len(parsed_response.text),
                tool_calls_count=len(parsed_response.tool_calls),
                stop_reason=parsed_response.stop_reason,
            )

            return parsed_response

        except Exception as e:
            logger.error(
                "openai api error",
                error=str(e),
                exc_info=True,
            )
            raise

    async def stream_completion(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[LLMResponse, None]:
        """Потоковое получение ответа от OpenAI API.

        Генерирует промежуточные LLMResponse при получении данных.
        """
        if self._client is None:
            msg = "Провайдер не инициализирован"
            raise RuntimeError(msg)

        logger.debug(
            "openai stream_completion request starting",
            num_messages=len(messages),
            has_tools=bool(tools),
            num_tools=len(tools) if tools else 0,
        )

        # Преобразовать сообщения
        openai_messages = self._convert_to_openai_format(messages)

        request_params = {
            "model": self._model,
            "messages": openai_messages,
            "temperature": kwargs.get("temperature", self._temperature),
            "max_tokens": kwargs.get("max_tokens", self._max_tokens),
            "stream": True,
        }

        if tools:
            request_params["tools"] = tools
            request_params["tool_choice"] = "auto"

        try:
            # Получить потоковый ответ от OpenAI
            logger.debug("sending streaming request to openai api")
            stream = await self._client.chat.completions.create(
                **request_params
            )
            buffer = ""
            chunk_count = 0
            async for chunk in stream:
                chunk_count += 1
                if chunk.choices[0].delta.content:
                    buffer += chunk.choices[0].delta.content
                    logger.debug(
                        "openai stream chunk received",
                        chunk_count=chunk_count,
                        buffer_length=len(buffer),
                    )
                    yield LLMResponse(
                        text=buffer,
                        tool_calls=[],
                        stop_reason="streaming",
                    )

            logger.debug(
                "openai stream completed",
                total_chunks=chunk_count,
                final_length=len(buffer),
            )

        except Exception as e:
            logger.error(
                "openai stream error",
                error=str(e),
                exc_info=True,
            )
            raise

    def _parse_completion(self, response: ChatCompletion) -> LLMResponse:  # noqa: C901
        """Преобразовать ответ OpenAI в LLMResponse.

        Args:
            response: Ответ от OpenAI API

        Returns:
            LLMResponse с распарсенными инструментами
        """
        choice = response.choices[0]
        message = choice.message

        # Извлечь текст
        text = message.content or ""

        logger.debug(
            "parsing openai completion",
            finish_reason=choice.finish_reason,
            has_message_tool_calls=bool(message.tool_calls),
            message_content_length=len(text),
        )

        # Извлечь tool calls
        tool_calls: list[LLMToolCall] = []
        if message.tool_calls:
            logger.debug(
                "parsing tool_calls from message",
                num_tool_calls=len(message.tool_calls),
            )
            
            for idx, tool_call in enumerate(message.tool_calls):
                logger.debug(
                    "parsing individual tool_call",
                    tool_call_index=idx,
                    tool_call_id=tool_call.id,
                    tool_call_type=tool_call.type,
                )
                
                if tool_call.type == "function":
                    # Получить функцию из tool_call
                    func = tool_call.function
                    # Преобразовать arguments из строки в dict если нужно
                    args: dict[str, Any] = {}
                    if hasattr(func, "arguments"):  # noqa: SIM118
                        if isinstance(func.arguments, str):
                            try:
                                args = json.loads(func.arguments)
                                logger.debug(
                                    "parsed tool arguments from json",
                                    tool_name=func.name,
                                    arguments=args,
                                )
                            except (json.JSONDecodeError, TypeError) as e:
                                logger.error(
                                    "failed to parse tool arguments json",
                                    tool_name=func.name,
                                    raw_arguments=func.arguments,
                                    error=str(e),
                                )
                                args = {}
                        elif isinstance(func.arguments, dict):
                            args = func.arguments
                            logger.debug(
                                "tool arguments already dict",
                                tool_name=func.name,
                                arguments=args,
                            )

                    tool_calls.append(
                        LLMToolCall(
                            id=tool_call.id,
                            name=func.name,
                            arguments=args,
                        )
                    )
                    
                    logger.debug(
                        "tool_call parsed successfully",
                        tool_call_id=tool_call.id,
                        tool_name=func.name,
                    )

        # Определить stop reason
        stop_reason = "end_turn"
        if choice.finish_reason == "tool_calls":
            stop_reason = "tool_use"
        elif choice.finish_reason == "length":
            stop_reason = "max_tokens"

        logger.info(
            "openai completion parsed",
            stop_reason=stop_reason,
            num_tool_calls_parsed=len(tool_calls),
            text_length=len(text),
        )

        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
        )

    def _convert_to_openai_format(self, messages: list[LLMMessage]) -> list[dict[str, Any]]:
        """Преобразовать LLMMessage в формат OpenAI API.
        
        Поддерживает:
        - Обычные сообщения (system, user, assistant)
        - Assistant messages с tool_calls
        - Tool messages с tool_call_id
        
        Args:
            messages: Список LLMMessage
            
        Returns:
            Список словарей в формате OpenAI API
        """
        openai_messages: list[dict[str, Any]] = []
        
        for msg in messages:
            openai_msg: dict[str, Any] = {"role": msg.role}
            
            # Добавить content если есть
            if msg.content is not None:
                openai_msg["content"] = msg.content
            
            # Для assistant messages с tool_calls
            if msg.role == "assistant" and msg.tool_calls:
                # Преобразовать LLMToolCall в формат OpenAI
                openai_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in msg.tool_calls
                ]
            
            # Для tool messages
            if msg.role == "tool":
                if msg.tool_call_id:
                    openai_msg["tool_call_id"] = msg.tool_call_id
                if msg.name:
                    openai_msg["name"] = msg.name
            
            openai_messages.append(openai_msg)
        
        return openai_messages
    
    def _validate_message_history(self, messages: list[dict[str, Any]]) -> None:
        """Валидация истории сообщений перед отправкой в OpenAI API.
        
        Проверяет, что:
        - Tool messages следуют после assistant messages с tool_calls
        - Tool messages имеют tool_call_id
        
        Args:
            messages: Список сообщений в формате OpenAI
            
        Raises:
            ValueError: Если история сообщений некорректна
        """
        last_assistant_tool_call_ids: set[str] = set()
        
        for i, msg in enumerate(messages):
            role = msg.get("role")
            
            # Собрать tool_call_ids из assistant messages
            if role == "assistant":
                tool_calls = msg.get("tool_calls", [])
                if tool_calls:
                    last_assistant_tool_call_ids = {tc["id"] for tc in tool_calls}
                else:
                    # Assistant message без tool_calls - сбросить ожидаемые IDs
                    last_assistant_tool_call_ids = set()
            
            # Проверить tool messages
            elif role == "tool":
                tool_call_id = msg.get("tool_call_id")
                
                if not tool_call_id:
                    logger.error(
                        "tool message without tool_call_id",
                        message_index=i,
                        message=msg,
                    )
                    raise ValueError(
                        f"Tool message at index {i} missing tool_call_id"
                    )
                
                if not last_assistant_tool_call_ids:
                    logger.error(
                        "tool message without preceding assistant tool_calls",
                        message_index=i,
                        tool_call_id=tool_call_id,
                    )
                    raise ValueError(
                        f"Tool message at index {i} (tool_call_id={tool_call_id}) "
                        "must follow an assistant message with tool_calls"
                    )
