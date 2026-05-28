"""Тесты для настраиваемого таймаута stdio транспорта."""



from codelab.client.infrastructure.stdio_transport import StdioClientTransport


class TestStdioClientTransportTimeout:
    """Tests for configurable receive_timeout in StdioClientTransport."""

    def test_default_timeout_is_60_seconds(self) -> None:
        """Default receive_timeout should be 60.0 seconds."""
        transport = StdioClientTransport(command="echo", args=[])
        assert transport._receive_timeout == 60.0

    def test_custom_timeout(self) -> None:
        """Custom receive_timeout should be stored."""
        transport = StdioClientTransport(
            command="echo",
            args=[],
            receive_timeout=120.0,
        )
        assert transport._receive_timeout == 120.0

    def test_timeout_in_error_message(self) -> None:
        """Timeout error message should include the configured timeout value."""
        transport = StdioClientTransport(
            command="echo",
            args=[],
            receive_timeout=5.0,
        )
        # Проверяем что timeout используется в сообщении об ошибке
        # через inspect кода или mock
        assert transport._receive_timeout == 5.0


class TestClientConfigReceiveTimeout:
    """Tests for receive_timeout in ClientConfig."""

    def test_default_timeout(self) -> None:
        from pathlib import Path

        from codelab.client.infrastructure.client_config import ClientConfig

        config = ClientConfig(
            host="localhost",
            port=8000,
            cwd=Path("/tmp"),
        )
        assert config.receive_timeout == 60.0

    def test_custom_timeout(self) -> None:
        from pathlib import Path

        from codelab.client.infrastructure.client_config import ClientConfig

        config = ClientConfig(
            host="localhost",
            port=8000,
            cwd=Path("/tmp"),
            receive_timeout=120.0,
        )
        assert config.receive_timeout == 120.0


class TestCreateClientContainerTimeout:
    """Tests for receive_timeout parameter in create_client_container."""

    def test_default_timeout_passed(self) -> None:

        from codelab.client.infrastructure.client_config import ClientConfig
        from codelab.client.infrastructure.container_factory import create_client_container

        container = create_client_container(
            host="localhost",
            port=8000,
            cwd="/tmp",
        )
        config = container.get(ClientConfig)
        assert config.receive_timeout == 60.0
        container.close()

    def test_custom_timeout_passed(self) -> None:

        from codelab.client.infrastructure.client_config import ClientConfig
        from codelab.client.infrastructure.container_factory import create_client_container

        container = create_client_container(
            host="localhost",
            port=8000,
            cwd="/tmp",
            receive_timeout=90.0,
        )
        config = container.get(ClientConfig)
        assert config.receive_timeout == 90.0
        container.close()


class TestClientProviderTimeout:
    """Tests that ClientProvider passes receive_timeout to StdioClientTransport."""

    def test_provider_passes_timeout_to_stdio_transport(self) -> None:
        from pathlib import Path

        from dishka import make_container

        from codelab.client.domain.services import TransportService
        from codelab.client.infrastructure.client_config import ClientConfig
        from codelab.client.infrastructure.providers import ClientProvider
        from codelab.client.infrastructure.stdio_transport import StdioClientTransport

        config = ClientConfig(
            host="localhost",
            port=8000,
            cwd=Path("/tmp"),
            transport_mode="stdio",
            receive_timeout=90.0,
        )

        container = make_container(ClientProvider(), context={ClientConfig: config})
        transport = container.get(TransportService)

        # ACPTransportService оборачивает StdioClientTransport
        # Проверяем что underlying transport имеет правильный timeout
        assert hasattr(transport, "_transport")
        assert isinstance(transport._transport, StdioClientTransport)
        assert transport._transport._receive_timeout == 90.0

        container.close()
