## 1. TOML поддержка в TUIConfigStore

- [x] 1.1 Добавить метод `_load_from_toml_chain()` в `TUIConfigStore` для загрузки `[tui]` секции из цепочки TOML файлов
- [x] 1.2 Добавить метод `load_with_priority()` объединяющий JSON и TOML конфиги с правильным приоритетом
- [x] 1.3 Обновить `resolve_tui_connection()` → `resolve_tui_config()` для возврата полной конфигурации (host, port, theme)
- [ ] 1.4 Написать unit-тесты для TOML loading в `tests/client/tui/test_config.py`
- [ ] 1.5 Написать unit-тесты для priority resolution в `tests/client/tui/test_config.py`

## 2. CLI флаг --theme

- [x] 2.1 Добавить `--theme` аргумент в `connect_parser` в `cli.py` с choices=["light", "dark"]
- [x] 2.2 Обновить `run_connect()` для передачи theme в `_run_tui_app()`
- [x] 2.3 Обновить `_run_tui_app()` для передачи theme в `ACPClientApp.__init__()`
- [x] 2.4 Добавить поддержку env variable `CODELAB_THEME` в `cli.py`

## 3. Исправление багов в app.py

- [x] 3.1 Исправить `action_toggle_theme()` — заменить сравнение `Theme` объекта на `current_theme_name` (строка)
- [x] 3.2 Добавить сохранение темы в конфиг после переключения в `action_toggle_theme()`
- [x] 3.3 Загрузить тему из конфига в `__init__()` после создания `ThemeManager`
- [x] 3.4 Передать theme из CLI args в `__init__()` с приоритетом над конфигом
- [ ] 3.5 Написать интеграционные тесты для применения темы при старте в `tests/client/tui/test_app_theme.py`

## 4. Динамическое применение темы в ThemeManager

- [x] 4.1 Реализовать `_apply_theme()` для загрузки TCSS файла (`light.tcss` или `dark.tcss`)
- [x] 4.2 Использовать Textual API для применения TCSS к приложению без перезапуска
- [x] 4.3 Добавить fallback на дефолтные цвета если TCSS файл не найден
- [ ] 4.4 Написать unit-тесты для `_apply_theme()` в `tests/client/tui/themes/test_manager.py`
- [ ] 4.5 Написать тесты для toggle_theme() в `tests/client/tui/themes/test_manager.py`

## 5. Разделение app.tcss на layout и theme

- [x] 5.1 Удалить все color-related свойства из `app.tcss` (background, color, border-color с hex значениями)
- [x] 5.2 Оставить в `app.tcss` только layout свойства (height, width, padding, margin, layout, border-style)
- [x] 5.3 Проверить что `themes/light.tcss` содержит все цветовые селекторы из app.tcss
- [x] 5.4 Проверить что `themes/dark.tcss` содержит все цветовые селекторы из app.tcss
- [x] 5.5 Добавить недостающие селекторы в theme TCSS файлы если необходимо

## 6. Обновление компонентов с DEFAULT_CSS

- [x] 6.1 Проверить все 57 компонентов с DEFAULT_CSS на использование hex цветов
- [x] 6.2 Заменить hex цвета на Textual CSS variables (`$primary`, `$surface`, `$text-muted`) в компонентах
- [x] 6.3 Проверить что `message_bubble.py` адаптируется к теме
- [x] 6.4 Проверить что `action_button.py` адаптируется к теме
- [x] 6.5 Проверить что `markdown.py` адаптируется к теме (включая CodeBlock theme)
- [x] 6.6 Проверить что `quick_actions_bar.py` адаптируется к теме
- [x] 6.7 Проверить что `footer_bar.py` адаптируется к теме

## 7. Визуальная индикация темы

- [x] 7.1 Обновить иконку в `QuickActionsBar` — ☀️ для light, 🌙 для dark
- [x] 7.2 Добавить отображение текущей темы в `FooterBar` (текст "Light"/"Dark")
- [x] 7.3 Обновить иконку при переключении темы (реактивность)
- [x] 7.4 Обновить текст в footer при переключении темы (реактивность)

## 8. Документация и финальная проверка

- [ ] 8.1 Добавить пример `[tui]` секции в `~/.codelab/codelab.toml.example`
- [ ] 8.2 Обновить `codelab/README.md` с описанием конфигурации тем
- [x] 8.3 Запустить `make check` для проверки linting и type checking
- [ ] 8.4 Запустить все тесты `uv run python -m pytest` для проверки покрытия
- [ ] 8.5 Ручное тестирование: переключение тем, сохранение конфига, визуальная индикация
