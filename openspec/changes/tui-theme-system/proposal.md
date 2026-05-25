## Why

Текущая система тем TUI клиента имеет критические баги и неполную реализацию: переключение тем не работает (сравнение `Theme` объекта с `ThemeType` enum), тема не загружается из конфига при старте, цвета захардкожены в `app.tcss`, и отсутствует поддержка TOML конфигурации. Пользователи не могут reliably использовать светлую тему, которая уже определена но не применяется корректно.

## What Changes

- **TUIConfigStore** получает поддержку загрузки темы из TOML файлов (`~/.codelab/codelab.toml`, `./codelab.toml`, `./codelab.local.toml`) с секцией `[tui]`
- **CLI** получает флаг `--theme` для `codelab connect` с приоритетом над конфигами
- **ACPClientApp** применяет тему при старте из конфига и сохраняет изменения при переключении
- **ThemeManager** корректно применяет тему через загрузку TCSS файлов (`light.tcss`/`dark.tcss`)
- **app.tcss** разделяется на layout-only стили, цвета перемещены в theme-specific TCSS файлы
- **QuickActionsBar** показывает иконку текущей темы (☀️/🌙)
- **FooterBar** отображает название текущей темы
- **Env variable** `CODELAB_THEME` поддерживается как источник конфигурации

## Capabilities

### New Capabilities
- `tui-theme-config`: Система конфигурации тем с приоритетом источников (JSON < TOML global < TOML project < Env < CLI < UI toggle)
- `tui-theme-toggle`: Корректное переключение тем с сохранением в конфиг и визуальной индикацией
- `tui-theme-apply`: Динамическое применение тем через Textual TCSS файлы без перезапуска приложения

### Modified Capabilities
- `tui-config`: Расширение TUIConfigStore для поддержки TOML источников конфигурации

## Impact

**Затронутые файлы:**
- `codelab/src/codelab/client/tui/config.py` — TUIConfigStore с TOML поддержкой
- `codelab/src/codelab/client/tui/app.py` — применение темы при старте, исправление toggle
- `codelab/src/codelab/client/tui/themes/manager.py` — динамическое применение TCSS
- `codelab/src/codelab/client/tui/styles/app.tcss` — удаление хардкод цветов
- `codelab/src/codelab/client/tui/components/quick_actions_bar.py` — иконка темы
- `codelab/src/codelab/client/tui/components/footer_bar.py` — отображение темы
- `codelab/src/codelab/cli.py` — CLI флаг `--theme`

**Новые файлы:**
- `codelab/src/codelab/client/tui/config_resolver.py` — логика приоритета источников

**Тесты:**
- `tests/client/tui/test_config.py` — TUIConfigStore с TOML
- `tests/client/tui/themes/test_manager.py` — ThemeManager
- `tests/client/tui/test_app_theme.py` — применение темы при старте

**Документация:**
- `~/.codelab/codelab.toml` — пример секции `[tui]`
- `codelab/README.md` — описание конфигурации тем
