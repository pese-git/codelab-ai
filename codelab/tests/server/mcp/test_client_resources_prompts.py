"""Тесты для MCPClient resources и prompts методов."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from codelab.server.mcp.client import (
    MCPClient,
    MCPClientError,
    MCPClientState,
)
from codelab.server.mcp.models import (
    MCPServerConfig,
    MCPResource,
    MCPPrompt,
    MCPPromptArgument,
)


class TestMCPClientListResources:
    """Тесты метода list_resources."""

    @pytest.mark.asyncio
    async def test_list_resources_success(self):
        """Успешное получение списка ресурсов."""
        config = MCPServerConfig(name="test", type="stdio", command="mcp-server")
        client = MCPClient(config)
        client._state = MCPClientState.READY

        mock_transport = AsyncMock()
        mock_transport.send_request = AsyncMock(return_value={
            "resources": [
                {
                    "uri": "file:///tmp/test.txt",
                    "name": "test.txt",
                    "description": "A test file",
                    "mimeType": "text/plain",
                },
                {
                    "uri": "file:///tmp/data.json",
                    "name": "data.json",
                    "mimeType": "application/json",
                },
            ]
        })
        client._transport = mock_transport

        # Добавляем capabilities с resources
        from codelab.server.mcp.models import MCPCapabilities
        client._capabilities = MCPCapabilities(resources={"subscribe": False})

        resources = await client.list_resources()

        assert len(resources) == 2
        assert resources[0].uri == "file:///tmp/test.txt"
        assert resources[0].name == "test.txt"
        assert resources[1].uri == "file:///tmp/data.json"

        mock_transport.send_request.assert_called_once_with(
            method="resources/list",
            timeout=30.0,
        )

    @pytest.mark.asyncio
    async def test_list_resources_not_ready(self):
        """Ошибка при list_resources в неправильном состоянии."""
        config = MCPServerConfig(name="test", type="stdio", command="mcp-server")
        client = MCPClient(config)
        client._state = MCPClientState.CREATED

        with pytest.raises(MCPClientError, match="Cannot list resources"):
            await client.list_resources()

    @pytest.mark.asyncio
    async def test_list_resources_no_transport(self):
        """Ошибка при list_resources без транспорта."""
        config = MCPServerConfig(name="test", type="stdio", command="mcp-server")
        client = MCPClient(config)
        client._state = MCPClientState.READY
        client._transport = None

        with pytest.raises(MCPClientError, match="Transport not available"):
            await client.list_resources()

    @pytest.mark.asyncio
    async def test_list_resources_not_supported(self):
        """Ресурсы не поддерживаются сервером."""
        config = MCPServerConfig(name="test", type="stdio", command="mcp-server")
        client = MCPClient(config)
        client._state = MCPClientState.READY

        mock_transport = AsyncMock()
        client._transport = mock_transport

        # Capabilities без resources
        from codelab.server.mcp.models import MCPCapabilities
        client._capabilities = MCPCapabilities(tools={"listChanged": True})

        resources = await client.list_resources()

        assert resources == []
        mock_transport.send_request.assert_not_called()


class TestMCPClientReadResource:
    """Тесты метода read_resource."""

    @pytest.mark.asyncio
    async def test_read_resource_success(self):
        """Успешное чтение ресурса."""
        config = MCPServerConfig(name="test", type="stdio", command="mcp-server")
        client = MCPClient(config)
        client._state = MCPClientState.READY

        mock_transport = AsyncMock()
        mock_transport.send_request = AsyncMock(return_value={
            "contents": [
                {
                    "type": "text",
                    "text": "Hello, world!",
                }
            ]
        })
        client._transport = mock_transport

        result = await client.read_resource("file:///tmp/test.txt")

        assert len(result.contents) == 1
        assert result.contents[0]["type"] == "text"
        assert result.contents[0]["text"] == "Hello, world!"
        assert result.get_text_content() == "Hello, world!"

        mock_transport.send_request.assert_called_once_with(
            method="resources/read",
            params={"uri": "file:///tmp/test.txt"},
            timeout=30.0,
        )

    @pytest.mark.asyncio
    async def test_read_resource_cached(self):
        """Чтение ресурса из кэша."""
        config = MCPServerConfig(name="test", type="stdio", command="mcp-server")
        client = MCPClient(config)
        client._state = MCPClientState.READY

        mock_transport = AsyncMock()
        client._transport = mock_transport

        # Добавляем в кэш
        from codelab.server.mcp.models import MCPReadResourceResult
        client._resources_cache["file:///tmp/test.txt"] = MCPReadResourceResult(
            contents=[{"type": "text", "text": "Cached content"}]
        )

        result = await client.read_resource("file:///tmp/test.txt")

        assert result.get_text_content() == "Cached content"
        mock_transport.send_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_read_resource_not_ready(self):
        """Ошибка при read_resource в неправильном состоянии."""
        config = MCPServerConfig(name="test", type="stdio", command="mcp-server")
        client = MCPClient(config)
        client._state = MCPClientState.CREATED

        with pytest.raises(MCPClientError, match="Cannot read resource"):
            await client.read_resource("file:///tmp/test.txt")


class TestMCPClientListPrompts:
    """Тесты метода list_prompts."""

    @pytest.mark.asyncio
    async def test_list_prompts_success(self):
        """Успешное получение списка промптов."""
        config = MCPServerConfig(name="test", type="stdio", command="mcp-server")
        client = MCPClient(config)
        client._state = MCPClientState.READY

        mock_transport = AsyncMock()
        mock_transport.send_request = AsyncMock(return_value={
            "prompts": [
                {
                    "name": "code_review",
                    "description": "Review code for best practices",
                    "arguments": [
                        {
                            "name": "language",
                            "description": "Programming language",
                            "required": True,
                        }
                    ],
                },
                {
                    "name": "summarize",
                    "description": "Summarize text",
                },
            ]
        })
        client._transport = mock_transport

        # Добавляем capabilities с prompts
        from codelab.server.mcp.models import MCPCapabilities
        client._capabilities = MCPCapabilities(prompts={"listChanged": True})

        prompts = await client.list_prompts()

        assert len(prompts) == 2
        assert prompts[0].name == "code_review"
        assert len(prompts[0].arguments) == 1
        assert prompts[0].arguments[0].name == "language"
        assert prompts[1].name == "summarize"

        mock_transport.send_request.assert_called_once_with(
            method="prompts/list",
            timeout=30.0,
        )

    @pytest.mark.asyncio
    async def test_list_prompts_not_ready(self):
        """Ошибка при list_prompts в неправильном состоянии."""
        config = MCPServerConfig(name="test", type="stdio", command="mcp-server")
        client = MCPClient(config)
        client._state = MCPClientState.CREATED

        with pytest.raises(MCPClientError, match="Cannot list prompts"):
            await client.list_prompts()

    @pytest.mark.asyncio
    async def test_list_prompts_not_supported(self):
        """Промпты не поддерживаются сервером."""
        config = MCPServerConfig(name="test", type="stdio", command="mcp-server")
        client = MCPClient(config)
        client._state = MCPClientState.READY

        mock_transport = AsyncMock()
        client._transport = mock_transport

        # Capabilities без prompts
        from codelab.server.mcp.models import MCPCapabilities
        client._capabilities = MCPCapabilities(tools={"listChanged": True})

        prompts = await client.list_prompts()

        assert prompts == []
        mock_transport.send_request.assert_not_called()


class TestMCPClientGetPrompt:
    """Тесты метода get_prompt."""

    @pytest.mark.asyncio
    async def test_get_prompt_success(self):
        """Успешное получение промпта."""
        config = MCPServerConfig(name="test", type="stdio", command="mcp-server")
        client = MCPClient(config)
        client._state = MCPClientState.READY

        mock_transport = AsyncMock()
        mock_transport.send_request = AsyncMock(return_value={
            "description": "Code review prompt",
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": "Review this Python code:",
                    },
                }
            ]
        })
        client._transport = mock_transport

        result = await client.get_prompt(
            "code_review",
            arguments={"language": "python"},
        )

        assert result.description == "Code review prompt"
        assert len(result.messages) == 1
        assert result.messages[0]["role"] == "user"

        mock_transport.send_request.assert_called_once_with(
            method="prompts/get",
            params={
                "name": "code_review",
                "arguments": {"language": "python"},
            },
            timeout=30.0,
        )

    @pytest.mark.asyncio
    async def test_get_prompt_cached(self):
        """Получение промпта из кэша."""
        config = MCPServerConfig(name="test", type="stdio", command="mcp-server")
        client = MCPClient(config)
        client._state = MCPClientState.READY

        mock_transport = AsyncMock()
        client._transport = mock_transport

        # Добавляем в кэш
        from codelab.server.mcp.models import MCPGetPromptResult
        cache_key = "code_review:[('language', 'python')]"
        client._prompts_cache[cache_key] = MCPGetPromptResult(
            description="Cached prompt",
            messages=[],
        )

        result = await client.get_prompt(
            "code_review",
            arguments={"language": "python"},
        )

        assert result.description == "Cached prompt"
        mock_transport.send_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_prompt_not_ready(self):
        """Ошибка при get_prompt в неправильном состоянии."""
        config = MCPServerConfig(name="test", type="stdio", command="mcp-server")
        client = MCPClient(config)
        client._state = MCPClientState.CREATED

        with pytest.raises(MCPClientError, match="Cannot get prompt"):
            await client.get_prompt("code_review")

    @pytest.mark.asyncio
    async def test_get_prompt_without_arguments(self):
        """Получение промпта без аргументов."""
        config = MCPServerConfig(name="test", type="stdio", command="mcp-server")
        client = MCPClient(config)
        client._state = MCPClientState.READY

        mock_transport = AsyncMock()
        mock_transport.send_request = AsyncMock(return_value={
            "description": "Simple prompt",
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": "Hello!",
                    },
                }
            ]
        })
        client._transport = mock_transport

        result = await client.get_prompt("greeting")

        assert result.description == "Simple prompt"

        mock_transport.send_request.assert_called_once_with(
            method="prompts/get",
            params={"name": "greeting"},
            timeout=30.0,
        )
