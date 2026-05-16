"""Integration тесты для Global Policy Management fallback chain.

Проверяет что fallback chain работает корректно:
1. Session policy (имеет приоритет)
2. Global policy (если нет session policy)
3. Ask user (default)

Согласно doc/architecture/ADVANCED_PERMISSION_MANAGEMENT_ARCHITECTURE.md (Секция 13.4)
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from codelab.server.protocol.handlers.global_policy_manager import GlobalPolicyManager
from codelab.server.protocol.handlers.permissions import resolve_remembered_permission_decision
from codelab.server.protocol.session_factory import SessionFactory


class TestGlobalPolicyFallbackChain:
    """Тесты fallback chain для permission resolution."""

    @pytest.fixture(autouse=True)
    def cleanup(self) -> None:
        """Очистить singleton после каждого теста."""
        yield
        GlobalPolicyManager.reset_for_testing()

    @pytest_asyncio.fixture
    async def temp_policy_storage(self) -> Path:
        """Создать временное хранилище для policies (путь к файлу)."""
        tmpdir = tempfile.mkdtemp()
        policy_file = Path(tmpdir) / "test_policies.json"
        yield policy_file
        # Cleanup
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest_asyncio.fixture
    async def global_manager_with_policies(
        self, temp_policy_storage: Path
    ) -> GlobalPolicyManager:
        """Создать GlobalPolicyManager с тестовыми policies."""
        manager = await GlobalPolicyManager.get_instance(storage_path=temp_policy_storage)
        # Установить некоторые глобальные политики
        await manager.set_global_policy("read", "allow_always")
        await manager.set_global_policy("execute", "reject_always")
        await manager.set_global_policy("write", "allow_always")
        return manager

    @pytest.mark.asyncio
    async def test_fallback_chain_session_policy_wins(
        self, global_manager_with_policies: GlobalPolicyManager
    ) -> None:
        """Session policy имеет приоритет над global policy.

        Сценарий:
        - Global: read=allow_always
        - Session: read=reject_always
        - Ожидаемо: reject (session wins)
        """
        session = SessionFactory.create_session(
            cwd="/tmp",
            mcp_servers=[],
            config_values={"mode": "ask"},
            available_commands=[],
            runtime_capabilities=None,
        )

        # Session policy переопределяет global
        session.permission_policy["read"] = "reject_always"

        decision = await resolve_remembered_permission_decision(
            session=session,
            tool_kind="read",
            global_manager=global_manager_with_policies,
        )

        assert decision == "reject"

    @pytest.mark.asyncio
    async def test_fallback_chain_global_policy_used(
        self, global_manager_with_policies: GlobalPolicyManager
    ) -> None:
        """Global policy используется если нет session policy.

        Сценарий:
        - Global: read=allow_always
        - Session: {} (empty)
        - Ожидаемо: allow (from global)
        """
        session = SessionFactory.create_session(
            cwd="/tmp",
            mcp_servers=[],
            config_values={"mode": "ask"},
            available_commands=[],
            runtime_capabilities=None,
        )

        # Session не имеет read policy, используем global
        assert "read" not in session.permission_policy

        decision = await resolve_remembered_permission_decision(
            session=session,
            tool_kind="read",
            global_manager=global_manager_with_policies,
        )

        assert decision == "allow"

    @pytest.mark.asyncio
    async def test_fallback_chain_ask_default(
        self, global_manager_with_policies: GlobalPolicyManager
    ) -> None:
        """Ask default если нет ни session ни global policy.

        Сценарий:
        - Global: {} (не установлена для "other")
        - Session: {} (empty)
        - Ожидаемо: ask (default)
        """
        session = SessionFactory.create_session(
            cwd="/tmp",
            mcp_servers=[],
            config_values={"mode": "ask"},
            available_commands=[],
            runtime_capabilities=None,
        )

        # Ни global ни session не имеют policy для "other"
        decision = await resolve_remembered_permission_decision(
            session=session,
            tool_kind="other",
            global_manager=global_manager_with_policies,
        )

        assert decision == "ask"

    @pytest.mark.asyncio
    async def test_fallback_chain_without_global_manager(self) -> None:
        """Backward compatibility: работает когда global_manager=None.

        Сценарий:
        - Global manager: None
        - Session: execute=allow_always
        - Ожидаемо: allow (from session)
        """
        session = SessionFactory.create_session(
            cwd="/tmp",
            mcp_servers=[],
            config_values={"mode": "ask"},
            available_commands=[],
            runtime_capabilities=None,
        )

        session.permission_policy["execute"] = "allow_always"

        decision = await resolve_remembered_permission_decision(
            session=session,
            tool_kind="execute",
            global_manager=None,  # Опциональный параметр
        )

        assert decision == "allow"

    @pytest.mark.asyncio
    async def test_fallback_chain_without_global_manager_defaults_to_ask(
        self,
    ) -> None:
        """Backward compatibility: ask default когда global_manager=None.

        Сценарий:
        - Global manager: None
        - Session: {} (empty)
        - Ожидаемо: ask (default)
        """
        session = SessionFactory.create_session(
            cwd="/tmp",
            mcp_servers=[],
            config_values={"mode": "ask"},
            available_commands=[],
            runtime_capabilities=None,
        )

        decision = await resolve_remembered_permission_decision(
            session=session,
            tool_kind="read",
            global_manager=None,
        )

        assert decision == "ask"

    @pytest.mark.asyncio
    async def test_session_allow_overrides_global_reject(
        self, global_manager_with_policies: GlobalPolicyManager
    ) -> None:
        """Session allow_always переопределяет global reject_always.

        Сценарий:
        - Global: execute=reject_always
        - Session: execute=allow_always
        - Ожидаемо: allow (session always wins)
        """
        session = SessionFactory.create_session(
            cwd="/tmp",
            mcp_servers=[],
            config_values={"mode": "ask"},
            available_commands=[],
            runtime_capabilities=None,
        )

        # Session переопределяет global
        session.permission_policy["execute"] = "allow_always"

        decision = await resolve_remembered_permission_decision(
            session=session,
            tool_kind="execute",
            global_manager=global_manager_with_policies,
        )

        assert decision == "allow"

    @pytest.mark.asyncio
    async def test_session_reject_overrides_global_allow(
        self, global_manager_with_policies: GlobalPolicyManager
    ) -> None:
        """Session reject_always переопределяет global allow_always.

        Сценарий:
        - Global: write=allow_always
        - Session: write=reject_always
        - Ожидаемо: reject (session always wins)
        """
        session = SessionFactory.create_session(
            cwd="/tmp",
            mcp_servers=[],
            config_values={"mode": "ask"},
            available_commands=[],
            runtime_capabilities=None,
        )

        # Session переопределяет global
        session.permission_policy["write"] = "reject_always"

        decision = await resolve_remembered_permission_decision(
            session=session,
            tool_kind="write",
            global_manager=global_manager_with_policies,
        )

        assert decision == "reject"

    @pytest.mark.asyncio
    async def test_multiple_tool_kinds_mixed_policies(
        self, global_manager_with_policies: GlobalPolicyManager
    ) -> None:
        """Разные tool kinds с разными policies работают корректно.

        Сценарий:
        - Global: read=allow, execute=reject, write=allow, other=None
        - Session: read=reject, execute=None, write=None, other=None
        - Ожидаемо:
          - read=reject (session wins)
          - execute=reject (from global)
          - write=allow (from global)
          - other=ask (default)
        """
        session = SessionFactory.create_session(
            cwd="/tmp",
            mcp_servers=[],
            config_values={"mode": "ask"},
            available_commands=[],
            runtime_capabilities=None,
        )

        # Session переопределяет только read
        session.permission_policy["read"] = "reject_always"

        # Test каждого tool kind
        assert (
            await resolve_remembered_permission_decision(
                session=session,
                tool_kind="read",
                global_manager=global_manager_with_policies,
            )
            == "reject"  # from session
        )

        assert (
            await resolve_remembered_permission_decision(
                session=session,
                tool_kind="execute",
                global_manager=global_manager_with_policies,
            )
            == "reject"  # from global
        )

        assert (
            await resolve_remembered_permission_decision(
                session=session,
                tool_kind="write",
                global_manager=global_manager_with_policies,
            )
            == "allow"  # from global
        )

        assert (
            await resolve_remembered_permission_decision(
                session=session,
                tool_kind="other",
                global_manager=global_manager_with_policies,
            )
            == "ask"  # default
        )

    @pytest.mark.asyncio
    async def test_global_policy_persistence_across_manager_instances(
        self, temp_policy_storage: Path
    ) -> None:
        """Global policies персистентны между instances.

        Сценарий:
        1. Создать manager1, установить policy
        2. Сбросить singleton
        3. Создать manager2 с тем же storage
        4. Проверить что policy восстановлена
        """
        # Создать первый manager и установить policy
        manager1 = await GlobalPolicyManager.get_instance(storage_path=temp_policy_storage)
        await manager1.set_global_policy("test_tool", "allow_always")

        # Сбросить singleton
        GlobalPolicyManager.reset_for_testing()

        # Создать второй manager с тем же storage
        manager2 = await GlobalPolicyManager.get_instance(storage_path=temp_policy_storage)

        # Проверить что policy восстановлена
        policy = await manager2.get_global_policy("test_tool")
        assert policy == "allow_always"

    @pytest.mark.asyncio
    async def test_empty_global_policies_dont_affect_ask_default(self) -> None:
        """Пустой global manager не преодолевает ask default.

        Сценарий:
        - Global manager создан но пуст
        - Session пуста
        - Ожидаемо: ask (default)
        """
        session = SessionFactory.create_session(
            cwd="/tmp",
            mcp_servers=[],
            config_values={"mode": "ask"},
            available_commands=[],
            runtime_capabilities=None,
        )

        tmpdir = tempfile.mkdtemp()
        policy_file = Path(tmpdir) / "test_policies.json"
        try:
            manager = await GlobalPolicyManager.get_instance(storage_path=policy_file)
            # Manager пуст, нет policies

            decision = await resolve_remembered_permission_decision(
                session=session,
                tool_kind="any_kind",
                global_manager=manager,
            )

            assert decision == "ask"
        finally:
            import shutil

            shutil.rmtree(tmpdir, ignore_errors=True)
            GlobalPolicyManager.reset_for_testing()
