"""Извлечение плана выполнения из ответа LLM.

Поддерживает два формата извлечения:
1. JSON в markdown code block внутри текстового ответа
2. Tool call `update_plan` с аргументами плана
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal, cast

import structlog

logger = structlog.get_logger()

# Допустимые значения для полей плана
ALLOWED_PRIORITIES = frozenset({"low", "medium", "high"})
ALLOWED_STATUSES = frozenset({"pending", "in_progress", "completed"})


@dataclass
class PlanEntry:
    """Один элемент плана выполнения.
    
    Attributes:
        content: Краткое описание задачи
        priority: Важность задачи (low, medium, high)
        status: Текущий статус (pending, in_progress, completed)
    """
    
    content: str
    priority: Literal["low", "medium", "high"]
    status: Literal["pending", "in_progress", "completed"]
    
    def to_dict(self) -> dict[str, str]:
        """Преобразовать в словарь для notification."""
        return {
            "content": self.content,
            "priority": self.priority,
            "status": self.status,
        }


class PlanExtractor:
    """Извлекает план из ответа LLM.
    
    Поддерживает форматы:
    - JSON в markdown code block: ```json {"plan": [...]} ```
    - Inline JSON объект с ключом "plan"
    - Tool call `update_plan` с entries
    
    Пример использования:
        >>> extractor = PlanExtractor()
        >>> entries = extractor.extract_from_text(llm_response_text)
        >>> if entries:
        ...     for entry in entries:
        ...         print(entry.content)
    """
    
    # Паттерн для извлечения JSON из markdown code block
    _JSON_BLOCK_PATTERN = re.compile(
        r"```(?:json)?\s*(\{[^`]*\"plan\"[^`]*\})\s*```",
        re.DOTALL | re.IGNORECASE,
    )
    
    # Паттерн для поиска inline JSON с "plan"
    _INLINE_PLAN_PATTERN = re.compile(
        r'\{\s*"plan"\s*:\s*\[',
        re.DOTALL,
    )
    
    def extract_from_text(self, text: str) -> list[dict[str, str]] | None:
        """Извлечь план из текстового ответа LLM.
        
        Args:
            text: Текстовый ответ LLM
            
        Returns:
            Список словарей с полями {content, priority, status, description}
            или None если план не найден или невалиден
        """
        if not text or not isinstance(text, str):
            return None
        
        # Попытка 1: JSON в markdown code block
        plan_data = self._parse_json_block(text)
        if plan_data:
            entries = self._validate_entries(plan_data.get("plan", []))
            if entries:
                logger.debug(
                    "plan extracted from markdown code block",
                    num_entries=len(entries),
                )
                return [e.to_dict() for e in entries]
        
        # Попытка 2: Inline JSON с "plan"
        plan_data = self._parse_inline_json(text)
        if plan_data:
            entries = self._validate_entries(plan_data.get("plan", []))
            if entries:
                logger.debug(
                    "plan extracted from inline JSON",
                    num_entries=len(entries),
                )
                return [e.to_dict() for e in entries]
        
        return None
    
    def extract_from_tool_call(
        self,
        tool_calls: list[Any],
    ) -> list[dict[str, str]] | None:
        """Извлечь план из tool call `update_plan`.
        
        Args:
            tool_calls: Список tool_calls из ответа LLM
            
        Returns:
            Список словарей с полями {content, priority, status, description}
            или None если tool call не найден или невалиден
        """
        if not tool_calls:
            return None
        
        for tool_call in tool_calls:
            # Поддерживаем разные форматы tool_call (dict или объект с атрибутами)
            if hasattr(tool_call, "name"):
                name = tool_call.name
                arguments = tool_call.arguments
            elif isinstance(tool_call, dict):
                name = tool_call.get("name", "")
                arguments = tool_call.get("arguments", {})
            else:
                continue
            
            if name != "update_plan":
                continue
            
            # Извлечь entries из arguments
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    continue
            
            raw_entries = arguments.get("entries", [])
            entries = self._validate_entries(raw_entries)
            
            if entries:
                logger.debug(
                    "plan extracted from update_plan tool call",
                    num_entries=len(entries),
                )
                return [e.to_dict() for e in entries]
        
        return None
    
    def _parse_json_block(self, text: str) -> dict[str, Any] | None:
        """Найти и распарсить JSON из markdown code block.
        
        Args:
            text: Текст для поиска
            
        Returns:
            Распарсенный JSON dict или None
        """
        match = self._JSON_BLOCK_PATTERN.search(text)
        if not match:
            return None
        
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError as e:
            logger.debug(
                "failed to parse JSON from code block",
                error=str(e),
            )
            return None
    
    def _parse_inline_json(self, text: str) -> dict[str, Any] | None:
        """Найти и распарсить inline JSON с "plan".
        
        Args:
            text: Текст для поиска
            
        Returns:
            Распарсенный JSON dict или None
        """
        match = self._INLINE_PLAN_PATTERN.search(text)
        if not match:
            return None
        
        # Найти начало JSON объекта
        start_idx = match.start()
        
        # Найти конец JSON объекта (балансировка скобок)
        brace_count = 0
        end_idx = start_idx
        
        for i, char in enumerate(text[start_idx:], start=start_idx):
            if char == "{":
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0:
                    end_idx = i + 1
                    break
        
        if end_idx <= start_idx:
            return None
        
        try:
            return json.loads(text[start_idx:end_idx])
        except json.JSONDecodeError as e:
            logger.debug(
                "failed to parse inline JSON",
                error=str(e),
            )
            return None
    
    def _validate_entries(self, raw_entries: Any) -> list[PlanEntry]:
        """Валидировать и нормализовать entries.
        
        Args:
            raw_entries: Сырые entries из JSON
            
        Returns:
            Список валидных PlanEntry объектов
        """
        if not isinstance(raw_entries, list):
            return []
        
        valid_entries: list[PlanEntry] = []
        
        for raw in raw_entries:
            if not isinstance(raw, dict):
                continue
            
            # Требуем content (может быть также title)
            content = raw.get("content") or raw.get("title")
            if not isinstance(content, str) or not content.strip():
                logger.debug(
                    "plan entry skipped: missing or invalid content",
                    raw=raw,
                )
                continue
            
            # Нормализуем priority
            raw_priority = raw.get("priority", "medium")
            priority = raw_priority if raw_priority in ALLOWED_PRIORITIES else "medium"
            
            # Нормализуем status
            raw_status = raw.get("status", "pending")
            status = raw_status if raw_status in ALLOWED_STATUSES else "pending"
            
            # Опциональное description
            valid_entries.append(
                PlanEntry(
                    content=content.strip(),
                    priority=cast(Literal["low", "medium", "high"], priority),
                    status=cast(Literal["pending", "in_progress", "completed"], status),
                )
            )
        
        return valid_entries
