"""Извлечение и обработка prompt директив."""

from __future__ import annotations

from codelab.server.protocol.state import PromptDirectives


def resolve_tool_title(kind: str) -> str:
    """Возвращает человекочитаемый title для tool-call по kind."""
    titles = {
        "read": "Tool read operation",
        "edit": "Tool edit operation",
        "delete": "Tool delete operation",
        "move": "Tool move operation",
        "execute": "Tool execution",
        "search": "Tool search operation",
        "think": "Tool reasoning step",
        "fetch": "Tool fetch operation",
        "switch_mode": "Tool mode switch",
        "other": "Tool operation",
    }
    return titles.get(kind, "Tool operation")


def normalize_tool_kind(candidate: str, supported_tool_kinds: set[str] | None = None) -> str | None:
    """Нормализует tool kind к поддерживаемому множеству ACP."""
    if supported_tool_kinds is None:
        supported_tool_kinds = {
            "read",
            "edit",
            "delete",
            "move",
            "search",
            "execute",
            "think",
            "fetch",
            "switch_mode",
            "other",
        }

    normalized = "edit" if candidate == "write" else candidate
    if normalized in supported_tool_kinds:
        return normalized
    return None


def extract_prompt_directives(
    text_preview: str,
    supported_tool_kinds: set[str],
) -> PromptDirectives:
    """Извлекает служебные флаги turn из текстового preview prompt."""
    normalized_tokens = {
        token.strip().lower()
        for token in text_preview.replace("\n", " ").split(" ")
        if token.strip()
    }

    has_plan_directive = "/plan" in normalized_tokens
    has_tool_directive = "/tool" in normalized_tokens
    has_pending_directive = "/tool-pending" in normalized_tokens
    tool_kind = "other"
    fs_read_path: str | None = None
    fs_write_path: str | None = None
    fs_write_content: str | None = None
    terminal_command: str | None = None
    forced_stop_reason: str | None = None

    stripped_preview = text_preview.strip()
    if stripped_preview.startswith("/fs-read "):
        maybe_path = stripped_preview[len("/fs-read ") :].strip()
        if maybe_path:
            fs_read_path = maybe_path
    if stripped_preview.startswith("/fs-write "):
        raw_write_payload = stripped_preview[len("/fs-write ") :].strip()
        path_and_content = raw_write_payload.split(" ", 1)
        if len(path_and_content) == 2:
            candidate_path = path_and_content[0].strip()
            candidate_content = path_and_content[1]
            if candidate_path:
                fs_write_path = candidate_path
                fs_write_content = candidate_content
    if stripped_preview.startswith("/term-run "):
        raw_command = stripped_preview[len("/term-run ") :].strip()
        if raw_command:
            terminal_command = raw_command
    if stripped_preview.startswith("/stop-max-tokens"):
        forced_stop_reason = "max_tokens"
    if stripped_preview.startswith("/stop-max-turn-requests"):
        forced_stop_reason = "max_turn_requests"
    if stripped_preview.startswith("/refuse"):
        forced_stop_reason = "refusal"

    if stripped_preview.startswith("/tool "):
        candidate = stripped_preview[len("/tool ") :].split(" ", 1)[0].strip().lower()
        normalized_candidate = normalize_tool_kind(candidate, supported_tool_kinds)
        if normalized_candidate is not None:
            tool_kind = normalized_candidate
    if stripped_preview.startswith("/tool-pending "):
        candidate = stripped_preview[len("/tool-pending ") :].split(" ", 1)[0].strip().lower()
        normalized_candidate = normalize_tool_kind(candidate, supported_tool_kinds)
        if normalized_candidate is not None:
            tool_kind = normalized_candidate

    return PromptDirectives(
        request_tool=has_tool_directive or has_pending_directive,
        keep_tool_pending=has_pending_directive,
        publish_plan=has_plan_directive,
        plan_entries=None,
        tool_kind=tool_kind,
        fs_read_path=fs_read_path,
        fs_write_path=fs_write_path,
        fs_write_content=fs_write_content,
        terminal_command=terminal_command,
        forced_stop_reason=forced_stop_reason,
    )
