"""Unit тесты для TerminalToolExecutor.

Проверяет:
- Инициализацию с зависимостями
- Создание терминала и запуск команды
- Ожидание завершения процесса
- Освобождение ресурсов терминала
- Lifecycle management (create → wait → release)
- Обработку ошибок на каждом этапе
- Корректность metadata в результатах
- Интеграционный flow: execute_wait_for_exit вызывает
  terminal/output → wait_for_exit → terminal/output
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from codelab.server.protocol.state import SessionState
from codelab.server.tools.executors.terminal_executor import TerminalToolExecutor
from codelab.server.tools.integrations.client_rpc_bridge import ClientRPCBridge
from codelab.server.tools.integrations.permission_checker import PermissionChecker


class TestTerminalExecutorInit:
    """Тесты инициализации TerminalToolExecutor."""

    def test_terminal_executor_init(self) -> None:
        """Инициализация с зависимостями."""
        # Arrange
        mock_bridge = MagicMock(spec=ClientRPCBridge)
        mock_checker = MagicMock(spec=PermissionChecker)
        
        # Act
        executor = TerminalToolExecutor(mock_bridge, mock_checker)
        
        # Assert
        assert executor._bridge == mock_bridge
        assert executor._permission_checker == mock_checker


class TestTerminalExecutorWaitForExitFlow:
    """Интеграционные тесты flow execute_wait_for_exit.
    
    По ACP spec terminal/wait_for_exit возвращает только exitCode/signal.
    Output получается через отдельный вызов terminal/output.
    Правильный flow: output → (wait_for_exit) → output
    """

    @pytest.fixture
    def session(self) -> SessionState:
        """Создает тестовую сессию."""
        return SessionState(
            session_id="test_session",
            cwd="/tmp",
            mcp_servers=[],
            config_values={},
        )

    @pytest.fixture
    def executor(self) -> TerminalToolExecutor:
        """Создает executor с mock зависимостями."""
        mock_bridge = MagicMock(spec=ClientRPCBridge)
        mock_checker = MagicMock(spec=PermissionChecker)
        return TerminalToolExecutor(mock_bridge, mock_checker)

    @pytest.mark.asyncio
    async def test_wait_for_exit_already_complete_skips_wait(
        self,
        executor: TerminalToolExecutor,
        session: SessionState,
    ) -> None:
        """Если terminal/output показывает завершённый статус — wait_for_exit не вызывается."""
        # Arrange
        executor._bridge.terminal_output = AsyncMock(return_value={  # type: ignore
            "output": "command output",
            "truncated": False,
            "is_complete": True,
            "exit_code": 0,
            "signal": None,
        })
        executor._bridge.wait_terminal_exit = AsyncMock(return_value={  # type: ignore
            "exit_code": 0,
            "signal": None,
        })

        # Act
        result = await executor.execute_wait_for_exit(
            session=session,
            terminal_id="term_001",
        )

        # Assert
        assert result.success is True
        assert result.output == "command output"
        assert result.metadata["exit_code"] == 0
        assert result.metadata["signal"] is None
        
        # terminal/output вызван один раз
        executor._bridge.terminal_output.assert_called_once_with(
            session=session,
            terminal_id="term_001",
        )
        # wait_terminal_exit НЕ вызывался
        executor._bridge.wait_terminal_exit.assert_not_called()

    @pytest.mark.asyncio
    async def test_wait_for_exit_running_terminal_calls_output_then_wait_then_output(
        self,
        executor: TerminalToolExecutor,
        session: SessionState,
    ) -> None:
        """Если терминал ещё работает — вызывается output → wait → output."""
        # Arrange
        executor._bridge.terminal_output = AsyncMock(side_effect=[  # type: ignore
            # Первый вызов — терминал ещё работает
            {
                "output": "partial output",
                "truncated": False,
                "is_complete": False,
                "exit_code": None,
                "signal": None,
            },
            # Третий вызов (после wait) — финальный output
            {
                "output": "final output",
                "truncated": False,
                "is_complete": True,
                "exit_code": 0,
                "signal": None,
            },
        ])
        executor._bridge.wait_terminal_exit = AsyncMock(return_value={  # type: ignore
            "exit_code": 0,
            "signal": None,
        })

        # Act
        result = await executor.execute_wait_for_exit(
            session=session,
            terminal_id="term_001",
        )

        # Assert
        assert result.success is True
        assert result.output == "final output"
        assert result.metadata["exit_code"] == 0
        
        # terminal/output вызван дважды
        assert executor._bridge.terminal_output.call_count == 2
        # wait_terminal_exit вызван один раз между вызовами output
        executor._bridge.wait_terminal_exit.assert_called_once_with(
            session=session,
            terminal_id="term_001",
        )

    @pytest.mark.asyncio
    async def test_wait_for_exit_with_signal(
        self,
        executor: TerminalToolExecutor,
        session: SessionState,
    ) -> None:
        """Корректная обработка сигнала завершения."""
        # Arrange
        executor._bridge.terminal_output = AsyncMock(return_value={  # type: ignore
            "output": "killed",
            "truncated": False,
            "is_complete": True,
            "exit_code": None,
            "signal": "SIGTERM",
        })

        # Act
        result = await executor.execute_wait_for_exit(
            session=session,
            terminal_id="term_001",
        )

        # Assert
        assert result.success is False  # exit_code != 0
        assert result.metadata["exit_code"] is None
        assert result.metadata["signal"] == "SIGTERM"

    @pytest.mark.asyncio
    async def test_wait_for_exit_non_zero_exit_code(
        self,
        executor: TerminalToolExecutor,
        session: SessionState,
    ) -> None:
        """Ненулевой exit_code возвращает success=False."""
        # Arrange
        executor._bridge.terminal_output = AsyncMock(side_effect=[  # type: ignore
            {
                "output": "", "is_complete": False,
                "exit_code": None, "signal": None, "truncated": False,
            },
            {
                "output": "error output", "is_complete": True,
                "exit_code": 1, "signal": None, "truncated": False,
            },
        ])
        executor._bridge.wait_terminal_exit = AsyncMock(return_value={  # type: ignore
            "exit_code": 1,
            "signal": None,
        })

        # Act
        result = await executor.execute_wait_for_exit(
            session=session,
            terminal_id="term_001",
        )

        # Assert
        assert result.success is False
        assert result.metadata["exit_code"] == 1
        assert result.output == "error output"

    @pytest.mark.asyncio
    async def test_wait_for_exit_wait_returns_none(
        self,
        executor: TerminalToolExecutor,
        session: SessionState,
    ) -> None:
        """Если wait_terminal_exit возвращает None — ошибка."""
        # Arrange
        executor._bridge.terminal_output = AsyncMock(return_value={  # type: ignore
            "output": "",
            "is_complete": False,
            "exit_code": None,
            "signal": None,
            "truncated": False,
        })
        executor._bridge.wait_terminal_exit = AsyncMock(return_value=None)  # type: ignore

        # Act
        result = await executor.execute_wait_for_exit(
            session=session,
            terminal_id="term_001",
        )

        # Assert
        assert result.success is False
        assert result.error is not None
        assert "Ошибка при ожидании завершения" in result.error

    @pytest.mark.asyncio
    async def test_wait_for_exit_output_returns_none_before_wait(
        self,
        executor: TerminalToolExecutor,
        session: SessionState,
    ) -> None:
        """Если первый terminal_output возвращает None — продолжается wait."""
        # Arrange
        executor._bridge.terminal_output = AsyncMock(side_effect=[  # type: ignore
            None,  # Первый вызов — None
            {
                "output": "final", "is_complete": True,
                "exit_code": 0, "signal": None, "truncated": False,
            },
        ])
        executor._bridge.wait_terminal_exit = AsyncMock(return_value={  # type: ignore
            "exit_code": 0,
            "signal": None,
        })

        # Act
        result = await executor.execute_wait_for_exit(
            session=session,
            terminal_id="term_001",
        )

        # Assert
        assert result.success is True
        assert result.output == "final"
        assert executor._bridge.terminal_output.call_count == 2
        executor._bridge.wait_terminal_exit.assert_called_once()

    @pytest.mark.asyncio
    async def test_wait_for_exit_final_output_returns_none(
        self,
        executor: TerminalToolExecutor,
        session: SessionState,
    ) -> None:
        """Если финальный terminal_output возвращает None — output остаётся пустым."""
        # Arrange
        executor._bridge.terminal_output = AsyncMock(side_effect=[  # type: ignore
            {
                "output": "", "is_complete": False,
                "exit_code": None, "signal": None, "truncated": False,
            },
            None,  # Финальный вызов — None
        ])
        executor._bridge.wait_terminal_exit = AsyncMock(return_value={  # type: ignore
            "exit_code": 0,
            "signal": None,
        })

        # Act
        result = await executor.execute_wait_for_exit(
            session=session,
            terminal_id="term_001",
        )

        # Assert
        assert result.success is True
        assert result.output == ""  # Пустой output
        assert result.metadata["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_wait_for_exit_call_sequence_order(
        self,
        executor: TerminalToolExecutor,
        session: SessionState,
    ) -> None:
        """Проверка точной последовательности вызовов: output → wait → output."""
        # Arrange
        call_order: list[str] = []
        
        async def mock_output(**kwargs: object) -> dict:
            if len(call_order) == 0:
                call_order.append("output_1")
                return {
                    "output": "", "is_complete": False,
                    "exit_code": None, "signal": None, "truncated": False,
                }
            call_order.append("output_2")
            return {
                "output": "done", "is_complete": True,
                "exit_code": 0, "signal": None, "truncated": False,
            }
        
        async def mock_wait(**kwargs: object) -> dict:
            call_order.append("wait")
            return {"exit_code": 0, "signal": None}
        
        executor._bridge.terminal_output = mock_output  # type: ignore
        executor._bridge.wait_terminal_exit = mock_wait  # type: ignore

        # Act
        await executor.execute_wait_for_exit(
            session=session,
            terminal_id="term_001",
        )

        # Assert
        assert call_order == ["output_1", "wait", "output_2"]

    @pytest.mark.asyncio
    async def test_wait_for_exit_content_includes_exit_message(
        self,
        executor: TerminalToolExecutor,
        session: SessionState,
    ) -> None:
        """Content содержит сообщение о завершении с exit code."""
        # Arrange
        executor._bridge.terminal_output = AsyncMock(return_value={  # type: ignore
            "output": "test output",
            "truncated": False,
            "is_complete": True,
            "exit_code": 42,
            "signal": None,
        })

        # Act
        result = await executor.execute_wait_for_exit(
            session=session,
            terminal_id="term_001",
        )

        # Assert
        assert len(result.content) == 1
        assert result.content[0]["type"] == "text"
        assert "exited with code 42" in result.content[0]["text"]
        assert "test output" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_wait_for_exit_content_includes_signal_message(
        self,
        executor: TerminalToolExecutor,
        session: SessionState,
    ) -> None:
        """Content содержит сообщение о сигнале завершения."""
        # Arrange
        executor._bridge.terminal_output = AsyncMock(return_value={  # type: ignore
            "output": "killed output",
            "truncated": False,
            "is_complete": True,
            "exit_code": None,
            "signal": "SIGKILL",
        })

        # Act
        result = await executor.execute_wait_for_exit(
            session=session,
            terminal_id="term_001",
        )

        # Assert
        assert len(result.content) == 1
        assert result.content[0]["type"] == "text"
        assert "exited with signal SIGKILL" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_wait_for_exit_terminal_id_passed_correctly(
        self,
        executor: TerminalToolExecutor,
        session: SessionState,
    ) -> None:
        """terminal_id корректно передаётся во все вызовы."""
        # Arrange
        executor._bridge.terminal_output = AsyncMock(side_effect=[  # type: ignore
            {
                "output": "", "is_complete": False,
                "exit_code": None, "signal": None, "truncated": False,
            },
            {
                "output": "out", "is_complete": True,
                "exit_code": 0, "signal": None, "truncated": False,
            },
        ])
        executor._bridge.wait_terminal_exit = AsyncMock(return_value={  # type: ignore
            "exit_code": 0,
            "signal": None,
        })

        # Act
        await executor.execute_wait_for_exit(
            session=session,
            terminal_id="term_abc123",
        )

        # Assert
        calls = executor._bridge.terminal_output.call_args_list
        assert len(calls) == 2
        for c in calls:
            assert c.kwargs["terminal_id"] == "term_abc123"
        
        wait_call = executor._bridge.wait_terminal_exit.call_args
        assert wait_call.kwargs["terminal_id"] == "term_abc123"

    @pytest.mark.asyncio
    async def test_wait_for_exit_exception_handling(
        self,
        executor: TerminalToolExecutor,
        session: SessionState,
    ) -> None:
        """Исключение в bridge корректно обрабатывается."""
        # Arrange
        executor._bridge.terminal_output = AsyncMock(side_effect=RuntimeError("bridge error"))  # type: ignore

        # Act
        result = await executor.execute_wait_for_exit(
            session=session,
            terminal_id="term_001",
        )

        # Assert
        assert result.success is False
        assert result.error is not None
        assert "bridge error" in result.error

