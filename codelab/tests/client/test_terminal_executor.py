"""Тесты для TerminalExecutor.

Проверяют:
- Создание терминалов
- Чтение output
- Ожидание завершения
- Убийство процесса
- Освобождение ресурсов
- Синхронное выполнение команд (безопасность)
"""

import asyncio

import pytest

from codelab.client.infrastructure.services.terminal_executor import (
    TerminalExecutor,
)


@pytest.fixture
def executor() -> TerminalExecutor:
    """TerminalExecutor для тестов."""
    return TerminalExecutor()


class TestTerminalExecutorCreate:
    """Тесты для создания терминалов."""

    async def test_create_terminal_with_echo(
        self, executor: TerminalExecutor
    ) -> None:
        """Тест создания терминала и запуска простой команды."""
        terminal_id = await executor.create_terminal("echo", ["Hello, World!"])

        assert terminal_id.startswith("term_")
        assert terminal_id in executor._terminals

    async def test_create_terminal_returns_unique_ids(
        self, executor: TerminalExecutor
    ) -> None:
        """Тест что каждый терминал получает уникальный ID."""
        id1 = await executor.create_terminal("echo", ["test1"])
        id2 = await executor.create_terminal("echo", ["test2"])

        assert id1 != id2

    async def test_create_terminal_with_invalid_command(
        self, executor: TerminalExecutor
    ) -> None:
        """Тест ошибки при запуске несуществующей команды."""
        with pytest.raises(RuntimeError, match="Failed to create terminal"):
            await executor.create_terminal("nonexistent_command_xyz", ["arg"])


class TestTerminalExecutorOutput:
    """Тесты для получения output."""

    async def test_get_output_running(
        self, executor: TerminalExecutor
    ) -> None:
        """Тест получения output из работающего процесса."""
        # Создать процесс который пишет в stdout
        terminal_id = await executor.create_terminal("echo", ["Hello, World!"])

        # Дать процессу время на завершение
        await asyncio.sleep(0.2)

        output, is_complete, exit_code = await executor.get_output(terminal_id)

        assert "Hello" in output
        assert is_complete  # echo завершается сразу
        assert exit_code == 0

    async def test_get_output_not_found(
        self, executor: TerminalExecutor
    ) -> None:
        """Тест ошибки когда терминал не найден."""
        with pytest.raises(ValueError, match="Terminal not found"):
            await executor.get_output("nonexistent_id")

    async def test_output_buffer_accumulates(
        self, executor: TerminalExecutor
    ) -> None:
        """Тест что output буферизируется."""
        terminal_id = await executor.create_terminal("echo", ["test"])
        await asyncio.sleep(0.2)

        output1, _, _ = await executor.get_output(terminal_id)
        output2, _, _ = await executor.get_output(terminal_id)

        # Оба вызова должны вернуть одинаковый output
        assert output1 == output2


class TestTerminalExecutorWaitForExit:
    """Тесты для ожидания завершения процесса."""

    async def test_wait_for_exit_success(
        self, executor: TerminalExecutor
    ) -> None:
        """Тест ожидания завершения процесса."""
        terminal_id = await executor.create_terminal("echo", ["done"])

        exit_code = await executor.wait_for_exit(terminal_id)

        assert exit_code == 0

    async def test_wait_for_exit_non_zero_exit_code(
        self, executor: TerminalExecutor
    ) -> None:
        """Тест ожидания процесса который завершится с ошибкой."""
        terminal_id = await executor.create_terminal("sh", ["-c", "exit 42"])

        exit_code = await executor.wait_for_exit(terminal_id)

        assert exit_code == 42

    async def test_wait_for_exit_not_found(
        self, executor: TerminalExecutor
    ) -> None:
        """Тест ошибки когда терминал не найден."""
        with pytest.raises(ValueError, match="Terminal not found"):
            await executor.wait_for_exit("nonexistent_id")


class TestTerminalExecutorKill:
    """Тесты для убийства процесса."""

    async def test_kill_terminal(self, executor: TerminalExecutor) -> None:
        """Тест убийства процесса."""
        terminal_id = await executor.create_terminal("sleep", ["100"])

        success = await executor.kill_terminal(terminal_id)

        assert success is True
        # Проверить что процесс действительно завершен
        output, is_complete, _ = await executor.get_output(terminal_id)
        assert is_complete

    async def test_kill_terminal_not_found(
        self, executor: TerminalExecutor
    ) -> None:
        """Тест ошибки при убийстве несуществующего терминала."""
        with pytest.raises(ValueError, match="Terminal not found"):
            await executor.kill_terminal("nonexistent_id")

    async def test_kill_already_exited(
        self, executor: TerminalExecutor
    ) -> None:
        """Тест убийства уже завершенного процесса."""
        terminal_id = await executor.create_terminal("echo", ["test"])
        await asyncio.sleep(0.2)

        # Процесс уже завершился
        success = await executor.kill_terminal(terminal_id)

        assert success is True


class TestTerminalExecutorRelease:
    """Тесты для освобождения ресурсов."""

    async def test_release_terminal(
        self, executor: TerminalExecutor
    ) -> None:
        """Тест освобождения ресурсов терминала."""
        terminal_id = await executor.create_terminal("echo", ["test"])
        await asyncio.sleep(0.2)

        success = await executor.release_terminal(terminal_id)

        assert success is True
        assert terminal_id not in executor._terminals

    async def test_release_not_found(
        self, executor: TerminalExecutor
    ) -> None:
        """Тест ошибки при освобождении несуществующего терминала."""
        with pytest.raises(ValueError, match="Terminal not found"):
            await executor.release_terminal("nonexistent_id")

    async def test_release_kills_running_process(
        self, executor: TerminalExecutor
    ) -> None:
        """Тест что release убивает работающий процесс."""
        terminal_id = await executor.create_terminal("sleep", ["100"])

        success = await executor.release_terminal(terminal_id)

        assert success is True
        assert terminal_id not in executor._terminals


class TestTerminalExecutorCleanup:
    """Тесты для очистки всех терминалов."""

    async def test_cleanup_all(self, executor: TerminalExecutor) -> None:
        """Тест очистки всех терминалов."""
        _id1 = await executor.create_terminal("sleep", ["100"])
        _id2 = await executor.create_terminal("sleep", ["100"])

        await executor.cleanup_all()

        assert len(executor._terminals) == 0

    async def test_cleanup_all_empty(
        self, executor: TerminalExecutor
    ) -> None:
        """Тест очистки когда терминалов нет."""
        await executor.cleanup_all()
        assert len(executor._terminals) == 0


class TestTerminalExecutorExecuteSync:
    """Тесты для синхронного выполнения команд (безопасность)."""

    def test_execute_simple_command(self) -> None:
        """Тест выполнения простой команды."""
        executor = TerminalExecutor()
        result = executor.execute("echo hello")

        assert result["success"] is True
        assert "hello" in result["output"]
        assert result["exit_code"] == 0

    def test_execute_shell_injection_is_blocked(self) -> None:
        """Shell-операторы не должны интерпретироваться оболочкой.

        Без shell=True строка "echo safe; echo injected" передаётся
        как один аргумент программе echo, а не как две команды.
        """
        executor = TerminalExecutor()
        # Попытка shell injection: весь текст — один аргумент для echo
        result = executor.execute("echo safe; echo injected")

        # Injection не происходит — вывод содержит всю строку целиком
        assert "safe; echo injected" in result["output"]
        # Но отдельной строки "injected" в выводе нет
        assert "injected" not in result["output"].split("\n")

    def test_execute_command_not_found(self) -> None:
        """Тест ошибки когда команда не найдена."""
        executor = TerminalExecutor()
        result = executor.execute("nonexistent_command_xyz_12345")

        assert result["success"] is False
        assert result["exit_code"] == 127
        assert "Command not found" in result["output"]

    def test_execute_empty_command(self) -> None:
        """Тест пустой команды."""
        executor = TerminalExecutor()
        result = executor.execute("")

        assert result["success"] is False
        assert result["exit_code"] == -1
        assert "Empty command" in result["output"]

    def test_execute_with_cwd(self, tmp_path) -> None:
        """Тест выполнения команды с указанием рабочей директории."""
        executor = TerminalExecutor()
        result = executor.execute("pwd", cwd=str(tmp_path))

        assert result["success"] is True
        assert str(tmp_path) in result["output"]

    def test_execute_with_pipe_blocked(self) -> None:
        """Pipe оператор | не должен интерпретироваться."""
        executor = TerminalExecutor()
        # Без shell=True pipe не работает — всё передаётся как аргументы echo
        result = executor.execute("echo hello | cat")

        # Pipe не сработал — вывод содержит всю строку целиком
        assert "hello | cat" in result["output"]

    def test_execute_with_redirect_blocked(self) -> None:
        """Redirect оператор > не должен интерпретироваться."""
        executor = TerminalExecutor()
        # Без shell=True redirect не работает
        result = executor.execute("echo hello > /tmp/test_redirect_blocked")

        # Redirect не сработал — команда выполнилась с аргументами
        assert result["success"] is True
        assert "hello > /tmp/test_redirect_blocked" in result["output"]

    def test_execute_with_and_operator_blocked(self) -> None:
        """Оператор && не должен интерпретироваться."""
        executor = TerminalExecutor()
        result = executor.execute("echo first && echo second")

        # && не сработал — всё один аргумент
        assert "first && echo second" in result["output"]

    def test_execute_invalid_syntax(self) -> None:
        """Тест команды с некорректным синтаксисом для shlex."""
        executor = TerminalExecutor()
        # Непарная кавычка — shlex.split выбросит ValueError
        result = executor.execute('echo "unclosed quote')

        assert result["success"] is False
        assert result["exit_code"] == -1
        assert "Invalid command syntax" in result["output"]

    def test_execute_with_cwd_not_found(self, tmp_path) -> None:
        """Тест команды с несуществующей рабочей директорией."""
        executor = TerminalExecutor()
        nonexistent_dir = tmp_path / "nonexistent"
        result = executor.execute("pwd", cwd=str(nonexistent_dir))

        assert result["success"] is False
