"""Тесты для ThemeManager."""

from __future__ import annotations

from unittest.mock import MagicMock

from codelab.client.tui.themes.manager import (
    DARK_THEME,
    LIGHT_THEME,
    Theme,
    ThemeManager,
)


class TestTheme:
    """Тесты для Theme dataclass."""

    def test_theme_creation(self) -> None:
        """Создание темы с цветами."""
        theme = Theme(name="test", display_name="Test", colors={"bg": "#000000"})
        assert theme.name == "test"
        assert theme.display_name == "Test"
        assert theme.colors["bg"] == "#000000"

    def test_get_css_variables(self) -> None:
        """Генерация CSS переменных."""
        theme = Theme(name="test", display_name="Test", colors={"bg": "#000000", "fg": "#ffffff"})
        css = theme.get_css_variables()
        assert "--bg: #000000" in css
        assert "--fg: #ffffff" in css

    def test_to_textual_theme_dark(self) -> None:
        """Конвертация dark темы в Textual Theme."""
        textual_theme = DARK_THEME.to_textual_theme()
        assert textual_theme.name == "dark"
        assert textual_theme.primary == "#7aa2f7"
        assert textual_theme.background == "#1a1b26"
        assert textual_theme.foreground == "#c0caf5"
        assert textual_theme.dark is True
        # Проверяем что дополнительные переменные переданы (без -- префикса)
        assert "border" in textual_theme.variables
        assert textual_theme.variables["border"] == "#565f89"

    def test_to_textual_theme_light(self) -> None:
        """Конвертация light темы в Textual Theme."""
        textual_theme = LIGHT_THEME.to_textual_theme()
        assert textual_theme.name == "light"
        assert textual_theme.primary == "#1d4ed8"
        assert textual_theme.background == "#f3f4f7"
        assert textual_theme.foreground == "#141a22"
        assert textual_theme.dark is False


class TestThemeManager:
    """Тесты для ThemeManager."""

    def test_default_theme_is_light(self) -> None:
        """По умолчанию тема light."""
        manager = ThemeManager()
        assert manager.current_theme_name == "light"

    def test_available_themes(self) -> None:
        """Доступные темы."""
        manager = ThemeManager()
        assert "light" in manager.available_themes
        assert "dark" in manager.available_themes

    def test_set_theme_dark(self) -> None:
        """Установка dark темы."""
        manager = ThemeManager()
        result = manager.set_theme("dark")
        assert result is True
        assert manager.current_theme_name == "dark"

    def test_set_theme_light(self) -> None:
        """Установка light темы."""
        manager = ThemeManager()
        manager.set_theme("dark")
        result = manager.set_theme("light")
        assert result is True
        assert manager.current_theme_name == "light"

    def test_set_theme_invalid(self) -> None:
        """Установка несуществующей темы."""
        manager = ThemeManager()
        result = manager.set_theme("invalid")
        assert result is False
        assert manager.current_theme_name == "light"  # Не изменилась

    def test_toggle_theme_from_light(self) -> None:
        """Переключение с light на dark."""
        manager = ThemeManager()
        new_theme = manager.toggle_theme()
        assert new_theme == "dark"
        assert manager.current_theme_name == "dark"

    def test_toggle_theme_from_dark(self) -> None:
        """Переключение с dark на light."""
        manager = ThemeManager()
        manager.set_theme("dark")
        new_theme = manager.toggle_theme()
        assert new_theme == "light"
        assert manager.current_theme_name == "light"

    def test_register_theme(self) -> None:
        """Регистрация новой темы."""
        manager = ThemeManager()
        custom_theme = Theme(name="custom", display_name="Custom", colors={"bg": "#ff0000"})
        manager.register_theme(custom_theme)
        assert "custom" in manager.available_themes

    def test_register_textual_themes(self) -> None:
        """Регистрация тем в Textual."""
        mock_app = MagicMock()
        manager = ThemeManager(app=mock_app)

        manager.register_textual_themes()

        # Проверяем что register_theme был вызван для каждой темы
        assert mock_app.register_theme.call_count == 2

        # Проверяем что темы зарегистрированы
        assert manager._themes_registered is True

    def test_register_textual_themes_idempotent(self) -> None:
        """register_textual_themes можно вызывать только один раз."""
        mock_app = MagicMock()
        manager = ThemeManager(app=mock_app)

        manager.register_textual_themes()
        manager.register_textual_themes()
        manager.register_textual_themes()

        # register_theme должен быть вызван только 2 раза (по одному на тему)
        assert mock_app.register_theme.call_count == 2

    def test_register_textual_themes_no_app(self) -> None:
        """register_textual_themes без app не делает ничего."""
        manager = ThemeManager()
        manager.register_textual_themes()
        # Не должно быть ошибок
        assert manager._themes_registered is False

    def test_apply_theme_with_app(self) -> None:
        """Применение темы с приложением."""
        mock_app = MagicMock()
        mock_app.theme = "light"  # Initial theme

        manager = ThemeManager(app=mock_app)

        # Применяем тему
        manager.set_theme("dark")

        # Проверяем что theme был установлен
        assert mock_app.theme == "dark"

    def test_apply_theme_no_app(self) -> None:
        """Применение темы без app не делает ничего."""
        manager = ThemeManager()
        manager.set_theme("dark")
        # Не должно быть ошибок
        assert manager.current_theme_name == "dark"

    def test_predefined_themes_have_all_colors(self) -> None:
        """Предустановленные темы имеют все необходимые цвета."""
        required_keys = {
            "background",
            "foreground",
            "primary",
            "border",
            "header-bg",
            "footer-bg",
        }

        for key in required_keys:
            assert key in DARK_THEME.colors, f"Dark theme missing {key}"
            assert key in LIGHT_THEME.colors, f"Light theme missing {key}"

    def test_dark_theme_contrast_improved(self) -> None:
        """Dark theme имеет улучшенный контраст границ."""
        # Border должен быть #565f89 вместо старого #3b4261
        assert DARK_THEME.colors["border"] == "#565f89"
        assert DARK_THEME.colors["sidebar-border"] == "#565f89"
        assert DARK_THEME.colors["input-border"] == "#565f89"
