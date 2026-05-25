"""ThemeManager - менеджер тем для CodeLab TUI.

Обеспечивает:
- Регистрацию и переключение тем
- Загрузку CSS стилей темы
- Сохранение выбранной темы в настройках
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from textual.app import App

logger = structlog.get_logger(__name__)


class ThemeType(Enum):
    """Доступные типы тем."""

    DARK = "dark"
    LIGHT = "light"


@dataclass
class Theme:
    """Определение темы с цветовыми переменными.

    Атрибуты:
        name: Уникальное имя темы
        display_name: Отображаемое название
        colors: Словарь CSS-переменных для цветов
    """

    name: str
    display_name: str
    colors: dict[str, str] = field(default_factory=dict)

    def get_css_variables(self) -> str:
        """Генерирует CSS с переменными темы."""
        lines = []
        for var_name, value in self.colors.items():
            lines.append(f"    --{var_name}: {value};")
        return "\n".join(lines)


# Предустановленная тёмная тема (Tokyo Night с улучшенным контрастом)
DARK_THEME = Theme(
    name="dark",
    display_name="Тёмная",
    colors={
        # Основные цвета
        "background": "#1a1b26",
        "background-secondary": "#24283b",
        "background-tertiary": "#2f3348",
        "foreground": "#c0caf5",
        "foreground-muted": "#565f89",
        "foreground-subtle": "#414868",
        # Акцентные цвета
        "primary": "#7aa2f7",
        "primary-hover": "#89b4fa",
        "secondary": "#bb9af7",
        "success": "#9ece6a",
        "warning": "#e0af68",
        "error": "#f7768e",
        "info": "#7dcfff",
        # Границы (улучшенный контраст)
        "border": "#565f89",               # Было #3b4261 (1.58:1 → 2.8:1)
        "border-focus": "#7aa2f7",
        # Header/Footer
        "header-bg": "#1e2030",
        "footer-bg": "#1e2030",
        # Sidebar
        "sidebar-bg": "#1f2335",
        "sidebar-border": "#565f89",       # Было #3b4261
        # Chat
        "chat-bg": "#1a1b26",
        "message-user-bg": "#24283b",
        "message-agent-bg": "#1f2335",
        # Input
        "input-bg": "#24283b",
        "input-border": "#565f89",         # Было #3b4261
        "input-focus-border": "#7aa2f7",
        # Buttons
        "button-bg": "#3b4261",
        "button-hover": "#4a5577",
        "button-primary-bg": "#7aa2f7",
        "button-primary-hover": "#89b4fa",
    },
)

# Предустановленная светлая тема
LIGHT_THEME = Theme(
    name="light",
    display_name="Светлая",
    colors={
        # Основные цвета
        "background": "#f3f4f7",
        "background-secondary": "#ffffff",
        "background-tertiary": "#e8eaf0",
        "foreground": "#141a22",
        "foreground-muted": "#6d7f9a",
        "foreground-subtle": "#9aa5b1",
        # Акцентные цвета
        "primary": "#1d4ed8",
        "primary-hover": "#2563eb",
        "secondary": "#7c3aed",
        "success": "#059669",
        "warning": "#d97706",
        "error": "#dc2626",
        "info": "#0891b2",
        # Границы
        "border": "#6d7f9a",
        "border-focus": "#1d4ed8",
        # Header/Footer
        "header-bg": "#1e3a5f",
        "footer-bg": "#1e3a5f",
        # Sidebar
        "sidebar-bg": "#ebeff7",
        "sidebar-border": "#6d7f9a",
        # Chat
        "chat-bg": "#ffffff",
        "message-user-bg": "#e3ecff",
        "message-agent-bg": "#f8fafc",
        # Input
        "input-bg": "#ffffff",
        "input-border": "#6d7f9a",
        "input-focus-border": "#1d4ed8",
        # Buttons
        "button-bg": "#e8eaf0",
        "button-hover": "#d1d5db",
        "button-primary-bg": "#1d4ed8",
        "button-primary-hover": "#2563eb",
    },
)


class ThemeManager:
    """Менеджер тем приложения.

    Управляет регистрацией, переключением и применением тем.
    Использует систему CSS Textual для применения стилей.
    """

    def __init__(self, app: App | None = None) -> None:
        """Инициализирует менеджер тем.

        Args:
            app: Textual приложение для применения стилей
        """
        self._app = app
        self._themes: dict[str, Theme] = {
            DARK_THEME.name: DARK_THEME,
            LIGHT_THEME.name: LIGHT_THEME,
        }
        self._current_theme: Theme = LIGHT_THEME
        self._css_path = Path(__file__).parent

    @property
    def current_theme(self) -> Theme:
        """Текущая активная тема."""
        return self._current_theme

    @property
    def current_theme_name(self) -> str:
        """Имя текущей темы."""
        return self._current_theme.name

    @property
    def available_themes(self) -> list[str]:
        """Список доступных тем."""
        return list(self._themes.keys())

    def register_theme(self, theme: Theme) -> None:
        """Регистрирует новую тему.

        Args:
            theme: Тема для регистрации
        """
        self._themes[theme.name] = theme
        logger.debug("theme_registered", theme_name=theme.name)

    def set_theme(self, theme_name: str) -> bool:
        """Устанавливает тему по имени.

        Args:
            theme_name: Имя темы для установки

        Returns:
            True если тема успешно установлена
        """
        if theme_name not in self._themes:
            logger.warning("theme_not_found", theme_name=theme_name)
            return False

        self._current_theme = self._themes[theme_name]
        logger.info("theme_changed", theme_name=theme_name)

        # Применяем тему к приложению если оно есть
        if self._app is not None:
            self._apply_theme()

        return True

    def toggle_theme(self) -> str:
        """Переключает между тёмной и светлой темой.

        Returns:
            Имя новой активной темы
        """
        if self._current_theme.name == "dark":
            self.set_theme("light")
        else:
            self.set_theme("dark")
        return self._current_theme.name

    def get_css(self) -> str:
        """Генерирует CSS для текущей темы.

        Returns:
            CSS строка с переменными темы
        """
        colors = self._current_theme.colors
        css_parts = ["/* Автоматически сгенерированные переменные темы */\n"]

        # Генерируем стили для Screen с переменными
        css_parts.append("Screen {")
        css_parts.append(f"    background: {colors.get('background', '#1a1b26')};")
        css_parts.append(f"    color: {colors.get('foreground', '#c0caf5')};")
        css_parts.append("}\n")

        return "\n".join(css_parts)

    def _apply_theme(self) -> None:
        """Применяет текущую тему к приложению."""
        if self._app is None:
            return

        # Загружаем TCSS файл темы
        tcss_file = self._css_path / f"{self._current_theme.name}.tcss"
        
        if not tcss_file.exists():
            logger.error("theme_tcss_not_found", tcss_file=str(tcss_file))
            return

        try:
            # Применяем TCSS через refresh CSS
            # Textual автоматически подхватывает изменения
            self._app.refresh_css()
            
            logger.info("theme_applied", theme=self._current_theme.name, tcss_file=str(tcss_file))
        except Exception as e:
            logger.error("theme_apply_error", error=str(e))

    def set_app(self, app: App) -> None:
        """Устанавливает приложение для управления темами.

        Args:
            app: Textual приложение
        """
        self._app = app


# Глобальный экземпляр менеджера тем
_theme_manager: ThemeManager | None = None


def get_theme_manager() -> ThemeManager:
    """Получает глобальный экземпляр менеджера тем."""
    global _theme_manager
    if _theme_manager is None:
        _theme_manager = ThemeManager()
    return _theme_manager
