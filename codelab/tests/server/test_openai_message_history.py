"""Тесты для проверки корректности формирования истории сообщений для OpenAI API."""

import pytest

from codelab.server.llm.base import LLMMessage, LLMToolCall
from codelab.server.llm.providers.openai import OpenAIProvider


class TestOpenAIMessageHistory:
    """Тесты для проверки формирования истории сообщений согласно требованиям OpenAI API."""

    def test_convert_simple_messages(self) -> None:
        """Проверить преобразование простых сообщений."""
        provider = OpenAIProvider()
        messages = [
            LLMMessage(role="system", content="You are a helpful assistant"),
            LLMMessage(role="user", content="Hello"),
            LLMMessage(role="assistant", content="Hi there!"),
        ]

        openai_messages = provider._convert_to_openai_format(messages)

        assert len(openai_messages) == 3
        assert openai_messages[0] == {"role": "system", "content": "You are a helpful assistant"}
        assert openai_messages[1] == {"role": "user", "content": "Hello"}
        assert openai_messages[2] == {"role": "assistant", "content": "Hi there!"}

    def test_convert_assistant_with_tool_calls(self) -> None:
        """Проверить преобразование assistant message с tool_calls."""
        provider = OpenAIProvider()
        tool_calls = [
            LLMToolCall(id="call_1", name="read_file", arguments={"path": "/tmp/test.txt"}),
            LLMToolCall(
                id="call_2",
                name="write_file",
                arguments={"path": "/tmp/out.txt", "content": "test"},
            ),
        ]
        messages = [
            LLMMessage(role="user", content="Read and process files"),
            LLMMessage(role="assistant", content="I'll read the files", tool_calls=tool_calls),
        ]

        openai_messages = provider._convert_to_openai_format(messages)

        assert len(openai_messages) == 2
        assert openai_messages[1]["role"] == "assistant"
        assert openai_messages[1]["content"] == "I'll read the files"
        assert "tool_calls" in openai_messages[1]
        assert len(openai_messages[1]["tool_calls"]) == 2
        
        # Проверить структуру первого tool call
        tc1 = openai_messages[1]["tool_calls"][0]
        assert tc1["id"] == "call_1"
        assert tc1["type"] == "function"
        assert tc1["function"]["name"] == "read_file"
        assert '"path": "/tmp/test.txt"' in tc1["function"]["arguments"]

    def test_convert_tool_messages(self) -> None:
        """Проверить преобразование tool messages с tool_call_id."""
        provider = OpenAIProvider()
        messages = [
            LLMMessage(role="user", content="Read file"),
            LLMMessage(
                role="assistant",
                content="Reading file",
                tool_calls=[
                    LLMToolCall(id="call_1", name="read_file", arguments={"path": "/tmp/test.txt"})
                ],
            ),
            LLMMessage(
                role="tool",
                content="File content: Hello World",
                tool_call_id="call_1",
                name="read_file",
            ),
        ]

        openai_messages = provider._convert_to_openai_format(messages)

        assert len(openai_messages) == 3
        
        # Проверить tool message
        tool_msg = openai_messages[2]
        assert tool_msg["role"] == "tool"
        assert tool_msg["content"] == "File content: Hello World"
        assert tool_msg["tool_call_id"] == "call_1"
        assert tool_msg["name"] == "read_file"

    def test_validate_correct_history(self) -> None:
        """Проверить валидацию корректной истории сообщений."""
        provider = OpenAIProvider()
        messages = [
            {"role": "user", "content": "Hello"},
            {
                "role": "assistant",
                "content": "Using tool",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "test_tool", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "content": "Result", "tool_call_id": "call_1"},
        ]

        # Не должно выбросить исключение
        provider._validate_message_history(messages)

    def test_validate_tool_without_tool_call_id(self) -> None:
        """Проверить, что валидация отклоняет tool message без tool_call_id."""
        provider = OpenAIProvider()
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "tool", "content": "Result"},  # Нет tool_call_id
        ]

        with pytest.raises(ValueError, match="missing tool_call_id"):
            provider._validate_message_history(messages)

    def test_validate_tool_without_preceding_assistant(self) -> None:
        """Проверить, что валидация отклоняет tool message без предшествующего assistant."""
        provider = OpenAIProvider()
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Response"},  # Нет tool_calls
            {"role": "tool", "content": "Result", "tool_call_id": "call_1"},
        ]

        with pytest.raises(ValueError, match="must follow an assistant message with tool_calls"):
            provider._validate_message_history(messages)

    def test_validate_multiple_tool_calls_and_results(self) -> None:
        """Проверить валидацию с несколькими tool calls и результатами."""
        provider = OpenAIProvider()
        messages = [
            {"role": "user", "content": "Process files"},
            {
                "role": "assistant",
                "content": "Processing",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "read", "arguments": "{}"},
                    },
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {"name": "write", "arguments": "{}"},
                    },
                ],
            },
            {"role": "tool", "content": "Read result", "tool_call_id": "call_1"},
            {"role": "tool", "content": "Write result", "tool_call_id": "call_2"},
        ]

        # Не должно выбросить исключение
        provider._validate_message_history(messages)

    def test_full_conversation_with_tool_calls(self) -> None:
        """Проверить полный цикл преобразования и валидации."""
        provider = OpenAIProvider()
        
        # Создать историю с tool calls
        messages = [
            LLMMessage(role="system", content="You are helpful"),
            LLMMessage(role="user", content="Read /tmp/test.txt"),
            LLMMessage(
                role="assistant",
                content="Reading file",
                tool_calls=[
                    LLMToolCall(id="call_1", name="read_file", arguments={"path": "/tmp/test.txt"})
                ],
            ),
            LLMMessage(
                role="tool",
                content="File content: test data",
                tool_call_id="call_1",
                name="read_file",
            ),
            LLMMessage(role="assistant", content="The file contains: test data"),
        ]

        # Преобразовать в OpenAI формат
        openai_messages = provider._convert_to_openai_format(messages)

        # Валидировать
        provider._validate_message_history(openai_messages)

        # Проверить структуру
        assert len(openai_messages) == 5
        assert openai_messages[2]["role"] == "assistant"
        assert "tool_calls" in openai_messages[2]
        assert openai_messages[3]["role"] == "tool"
        assert openai_messages[3]["tool_call_id"] == "call_1"

    def test_assistant_message_with_empty_content(self) -> None:
        """Проверить assistant message с пустым content но с tool_calls."""
        provider = OpenAIProvider()
        messages = [
            LLMMessage(role="user", content="Do something"),
            LLMMessage(
                role="assistant",
                content=None,  # Пустой content
                tool_calls=[
                    LLMToolCall(id="call_1", name="action", arguments={})
                ],
            ),
            LLMMessage(
                role="tool",
                content="Done",
                tool_call_id="call_1",
                name="action",
            ),
        ]

        openai_messages = provider._convert_to_openai_format(messages)
        provider._validate_message_history(openai_messages)

        # Assistant message может не иметь content если есть tool_calls
        assert openai_messages[1]["role"] == "assistant"
        assert "tool_calls" in openai_messages[1]
