"""ThemeManager - менеджер тем для CodeLab TUI.

Обеспечивает:
- Регистрацию и переключение тем через Textual Theme API
- Загрузку TCSS стилей для компонент-specific стилей
- Сохранение выбранной темы в настройках
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

import structlog
from textual.theme import Theme as TextualTheme

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

    def to_textual_theme(self) -> TextualTheme:
        """Конвертирует Theme в Textual Theme.

        Returns:
            TextualTheme объект для регистрации в Textual
        """
        colors = self.colors
        is_dark = self.name == "dark"

        # Все кастомные цвета передаём как CSS-variables
        # Textual Theme требует primary, background, foreground, surface, panel
        # Остальные цвета идут в variables для использования в TCSS
        standard_keys = {
            "primary", "secondary", "warning", "error",
            "success", "accent", "foreground", "background",
            "surface", "panel",
        }

        return TextualTheme(
            name=self.name,
            primary=colors.get("primary", "#7aa2f7"),
            secondary=colors.get("secondary", "#bb9af7"),
            warning=colors.get("warning", "#e0af68"),
            error=colors.get("error", "#f7768e"),
            success=colors.get("success", "#9ece6a"),
            accent=colors.get("info", "#7dcfff"),
            foreground=colors.get("foreground", "#c0caf5"),
            background=colors.get("background", "#1a1b26"),
            surface=colors.get("background-secondary", "#24283b"),
            panel=colors.get("background-tertiary", "#2f3348"),
            dark=is_dark,
            # Дополнительные CSS-variables для использования в TCSS
            # Textual TCSS использует $variable синтаксис, поэтому убираем --
            variables={
                k: v
                for k, v in colors.items()
                if k not in standard_keys
            },
        )

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
        "message-user-bg": "#2a3a5a",
        "message-agent-bg": "#1f2335",
        "message-error-bg": "#3b2428",
        # Input
        "input-bg": "#24283b",
        "input-border": "#565f89",         # Было #3b4261
        "input-focus-border": "#7aa2f7",
        # Buttons
        "button-bg": "#3b4261",
        "button-hover": "#4a5577",
        "button-primary-bg": "#7aa2f7",
        "button-primary-hover": "#89b4fa",
        # Badge
        "badge-pending-bg": "#e0af68",
        "badge-pending-fg": "#1a1b26",
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
        "message-error-bg": "#fef2f2",
        # Input
        "input-bg": "#ffffff",
        "input-border": "#6d7f9a",
        "input-focus-border": "#1d4ed8",
        # Buttons
        "button-bg": "#e8eaf0",
        "button-hover": "#d1d5db",
        "button-primary-bg": "#1d4ed8",
        "button-primary-hover": "#2563eb",
        # Badge
        "badge-pending-bg": "#fef3c7",
        "badge-pending-fg": "#92400e",
    },
)


class ThemeManager:
    """Менеджер тем приложения.

    Управляет регистрацией, переключением и применением тем.
    Использует Textual Theme API для переключения базовых цветов
    и TCSS файлы для компонент-specific стилей.
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
        self._themes_registered = False

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

    def register_textual_themes(self) -> None:
        """Регистрирует все темы в Textual через register_theme().

        Вызывается один раз когда приложение готово (on_mount).
        """
        if self._app is None or self._themes_registered:
            return

        for theme in self._themes.values():
            textual_theme = theme.to_textual_theme()
            self._app.register_theme(textual_theme)
            logger.debug("textual_theme_registered", theme_name=theme.name)

        self._themes_registered = True
        logger.info("all_textual_themes_registered")

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
        """Применяет текущую тему к приложению.

        Переключает тему через Textual Theme API.
        Textual автоматически обновляет все CSS-variables
        ($background, $primary, --border, --header-bg, и т.д.)
        """
        if self._app is None:
            return

        try:
            self._app.theme = self._current_theme.name
            logger.info("textual_theme_applied", theme=self._current_theme.name)
        except Exception as e:
            logger.error("textual_theme_apply_error", error=str(e))

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
