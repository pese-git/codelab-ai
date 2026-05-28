"""Тесты для маппинга имён инструментов между ACP и LLM."""

from codelab.server.tools.mapping import acp_name_to_llm_name, llm_name_to_acp_name


class TestAcpNameToLlmName:
    """Тесты конвертации ACP имён в LLM-совместимые имена."""

    def test_fs_read_text_file(self) -> None:
        """fs/read_text_file → fs_read_text_file."""
        assert acp_name_to_llm_name("fs/read_text_file") == "fs_read_text_file"

    def test_fs_write_text_file(self) -> None:
        """fs/write_text_file → fs_write_text_file."""
        assert acp_name_to_llm_name("fs/write_text_file") == "fs_write_text_file"

    def test_terminal_create(self) -> None:
        """terminal/create → terminal_create."""
        assert acp_name_to_llm_name("terminal/create") == "terminal_create"

    def test_terminal_wait_for_exit(self) -> None:
        """terminal/wait_for_exit → terminal_wait_for_exit."""
        assert acp_name_to_llm_name("terminal/wait_for_exit") == "terminal_wait_for_exit"

    def test_terminal_release(self) -> None:
        """terminal/release → terminal_release."""
        assert acp_name_to_llm_name("terminal/release") == "terminal_release"

    def test_terminal_output(self) -> None:
        """terminal/output → terminal_output."""
        assert acp_name_to_llm_name("terminal/output") == "terminal_output"

    def test_terminal_kill(self) -> None:
        """terminal/kill → terminal_kill."""
        assert acp_name_to_llm_name("terminal/kill") == "terminal_kill"

    def test_update_plan_unchanged(self) -> None:
        """update_plan остаётся без изменений (нет `/`)."""
        assert acp_name_to_llm_name("update_plan") == "update_plan"

    def test_multiple_slashes(self) -> None:
        """Несколько `/` заменяются на `_`."""
        assert acp_name_to_llm_name("a/b/c") == "a_b_c"


class TestLlmNameToAcpName:
    """Тесты обратной конвертации LLM имён в ACP формат."""

    def test_fs_read_text_file(self) -> None:
        """fs_read_text_file → fs/read_text_file."""
        assert llm_name_to_acp_name("fs_read_text_file") == "fs/read_text_file"

    def test_fs_write_text_file(self) -> None:
        """fs_write_text_file → fs/write_text_file."""
        assert llm_name_to_acp_name("fs_write_text_file") == "fs/write_text_file"

    def test_terminal_create(self) -> None:
        """terminal_create → terminal/create."""
        assert llm_name_to_acp_name("terminal_create") == "terminal/create"

    def test_terminal_wait_for_exit(self) -> None:
        """terminal_wait_for_exit → terminal/wait_for_exit."""
        assert llm_name_to_acp_name("terminal_wait_for_exit") == "terminal/wait_for_exit"

    def test_terminal_release(self) -> None:
        """terminal_release → terminal/release."""
        assert llm_name_to_acp_name("terminal_release") == "terminal/release"

    def test_terminal_output(self) -> None:
        """terminal_output → terminal/output."""
        assert llm_name_to_acp_name("terminal_output") == "terminal/output"

    def test_terminal_kill(self) -> None:
        """terminal_kill → terminal/kill."""
        assert llm_name_to_acp_name("terminal_kill") == "terminal/kill"

    def test_update_plan_unchanged(self) -> None:
        """update_plan остаётся без изменений (неизвестный префикс)."""
        assert llm_name_to_acp_name("update_plan") == "update_plan"

    def test_unknown_prefix_unchanged(self) -> None:
        """Неизвестные префиксы не маппятся."""
        assert llm_name_to_acp_name("custom_tool_name") == "custom_tool_name"


class TestRoundTrip:
    """Тесты двусторонней конвертации (round-trip)."""

    def test_fs_read_text_file_roundtrip(self) -> None:
        """ACP → LLM → ACP должно дать исходное имя."""
        acp = "fs/read_text_file"
        assert llm_name_to_acp_name(acp_name_to_llm_name(acp)) == acp

    def test_fs_write_text_file_roundtrip(self) -> None:
        """fs/write_text_file round-trip."""
        acp = "fs/write_text_file"
        assert llm_name_to_acp_name(acp_name_to_llm_name(acp)) == acp

    def test_terminal_create_roundtrip(self) -> None:
        """terminal/create round-trip."""
        acp = "terminal/create"
        assert llm_name_to_acp_name(acp_name_to_llm_name(acp)) == acp

    def test_terminal_wait_for_exit_roundtrip(self) -> None:
        """terminal/wait_for_exit round-trip."""
        acp = "terminal/wait_for_exit"
        assert llm_name_to_acp_name(acp_name_to_llm_name(acp)) == acp

    def test_terminal_release_roundtrip(self) -> None:
        """terminal/release round-trip."""
        acp = "terminal/release"
        assert llm_name_to_acp_name(acp_name_to_llm_name(acp)) == acp

    def test_update_plan_roundtrip(self) -> None:
        """update_plan round-trip (без изменений)."""
        acp = "update_plan"
        assert llm_name_to_acp_name(acp_name_to_llm_name(acp)) == acp


class TestMcpNameMapping:
    """Тесты маппинга MCP имён инструментов."""

    def test_mcp_acp_to_llm(self) -> None:
        """mcp:fs:read_file → mcp_fs_read_file."""
        assert acp_name_to_llm_name("mcp:fs:read_file") == "mcp_fs_read_file"

    def test_mcp_acp_to_llm_simple(self) -> None:
        """mcp:tool → mcp_tool."""
        assert acp_name_to_llm_name("mcp:tool") == "mcp_tool"

    def test_mcp_llm_to_acp(self) -> None:
        """mcp_fs_read_file → mcp:fs:read_file."""
        assert llm_name_to_acp_name("mcp_fs_read_file") == "mcp:fs:read_file"

    def test_mcp_llm_to_acp_simple(self) -> None:
        """mcp_tool → mcp:tool."""
        assert llm_name_to_acp_name("mcp_tool") == "mcp_tool"

    def test_mcp_roundtrip(self) -> None:
        """MCP round-trip: mcp:server:tool → mcp_server_tool → mcp:server:tool."""
        acp = "mcp:fs:read_file"
        assert llm_name_to_acp_name(acp_name_to_llm_name(acp)) == acp

    def test_mcp_roundtrip_complex(self) -> None:
        """MCP round-trip с复杂ным именем инструмента."""
        acp = "mcp:filesystem:read_text_file"
        assert llm_name_to_acp_name(acp_name_to_llm_name(acp)) == acp

    def test_mcp_llm_to_acp_no_underscore(self) -> None:
        """mcp_tool без underscore после server_id возвращается как есть."""
        assert llm_name_to_acp_name("mcp_tool") == "mcp_tool"
