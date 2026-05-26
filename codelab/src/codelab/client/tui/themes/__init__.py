"""Система тем для CodeLab TUI.

Предоставляет:
- ThemeManager: управление темами
- Theme: базовый класс темы (с методом to_textual_theme())
- DARK_THEME, LIGHT_THEME: предустановленные темы
- TextualTheme: алиас на textual.theme.Theme для удобства
"""

from textual.theme import Theme as TextualTheme

from .manager import (
    DARK_THEME,
    LIGHT_THEME,
    Theme,
    ThemeManager,
    ThemeType,
    get_theme_manager,
)

__all__ = [
    "DARK_THEME",
    "LIGHT_THEME",
    "TextualTheme",
    "Theme",
    "ThemeManager",
    "ThemeType",
    "get_theme_manager",
]
