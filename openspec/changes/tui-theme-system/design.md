## Context

Текущая система тем TUI клиента имеет три основных проблемы:

1. **Баг переключения**: `action_toggle_theme()` в `app.py:521-531` сравнивает `Theme` объект с `ThemeType` enum, что всегда возвращает False. Переключение тем не работает.

2. **Отсутствие загрузки при старте**: Тема по умолчанию всегда `LIGHT_THEME` (hardcoded в `manager.py:162`), конфигурация из `~/.codelab/tui_config.json` игнорируется.

3. **Хардкод цветов в app.tcss**: `app.tcss` содержит hex-цвета light темы, которые дублируются в `themes/light.tcss`. При переключении темы `app.tcss` переопределяет theme-specific стили.

4. **Нет TOML поддержки**: Сервер уже использует TOML конфигурацию (`codelab.toml`), но клиент читает только JSON.

Архитектура текущей системы тем:
- `ThemeManager` (manager.py) — управляет темами, имеет `DARK_THEME` и `LIGHT_THEME` dataclasses
- `TUIConfigStore` (config.py) — читает/сохраняет JSON конфиг
- `app.tcss` — основной stylesheet с хардкод цветами
- `themes/light.tcss`, `themes/dark.tcss` — полные theme-specific файлы (не используются динамически)

## Goals / Non-Goals

**Goals:**
- Исправить баг переключения тем
- Загружать тему из конфига при старте приложения
- Добавить поддержку TOML конфигурации с приоритетом источников
- Разделить layout и theme стили в TCSS
- Добавить визуальную индикацию текущей темы в UI
- Покрыть все изменения тестами

**Non-Goals:**
- Создание новых тем (только light/dark)
- Анимации перехода между темами
- Кастомизация цветов пользователем
- Изменение ACP протокола

## Decisions

### Decision 1: Priority resolution in TUIConfigStore

**Выбор:** Добавить метод `load_with_priority()` в `TUIConfigStore` вместо создания отдельного `ConfigResolver`.

**Альтернативы:**
- Отдельный `ConfigResolver` класс — более чистое разделение, но избыточно для одного поля `theme`
- Глобальная функция — менее тестируемо

**Решение:** Расширить `TUIConfigStore` методом `_load_from_toml_chain()` который читает TOML файлы и возвращает dict для merge.

### Decision 2: TCSS loading mechanism

**Выбор:** Использовать `self._app.mount()` для динамической загрузки TCSS файлов через `Screen` widget.

**Альтернативы:**
- `self._app.register_theme()` — требует Textual 2.0+, может не быть в текущей версии
- CSS injection через `self._app.styles` — менее надёжно
- Перезапуск приложения — плохой UX

**Решение:** В `_apply_theme()` загружать TCSS файл как string и применять через `self._app.Screen.styles.update()` или аналогичный Textual API.

### Decision 3: app.tcss refactoring

**Выбор:** Удалить все color-related свойства из `app.tcss`, переместить в theme TCSS файлы.

**Альтернативы:**
- Использовать CSS-variables в app.tcss (`$background`, `$primary`) — требует Textual поддержки переменных
- Два отдельных app.tcss (app-light.tcss, app-dark.tcss) — дублирование layout

**Решение:** Вариант A — app.tcss содержит только layout (height, width, padding, margin, layout, border-style без цвета). Все цвета в theme TCSS.

### Decision 4: TOML [tui] section format

**Выбор:** Использовать секцию `[tui]` в существующем `codelab.toml`:

```toml
[tui]
theme = "dark"
host = "127.0.0.1"
port = 8765
```

**Альтернативы:**
- Отдельный `tui.toml` — больше файлов, сложнее поддержка
- Секция `[client.tui]` — избыточная вложенность

**Решение:** `[tui]` в `codelab.toml` — соответствует существующим паттернам (`[llm]`, `[llm.fallback]`).

### Decision 5: Visual theme indicator

**Выбор:** Обновить иконку в `QuickActionsBar` и добавить текст в `FooterBar`.

**Альтернативы:**
- Только иконка — менее явно для пользователя
- Только текст в footer — менее заметно
- Отдельный widget в header — требует изменения layout

**Решение:** Оба индикатора — иконка в QuickActionsBar (☀️/🌙) и текст в FooterBar ("Light"/"Dark").

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| Textual API для динамической CSS загрузки может отличаться в разных версиях | Проверить версию Textual в pyproject.toml, использовать стабильный API |
| При переключении темы возможен visual glitch (mixed colors) | Использовать `refresh_css()` после полной загрузки нового TCSS |
| TOML parsing может замедлить запуск приложения | TOML файлы маленькие, парсинг < 10ms, кэшировать результат |
| app.tcss без цветов может сломать fallback если theme TCSS не загрузится | Добавить дефолтные цвета в `Theme.get_css_variables()` как fallback |
| Компоненты с DEFAULT_CSS могут не адаптироваться к теме | Проверить все 57 компонентов с DEFAULT_CSS, заменить hex на CSS variables |

## Migration Plan

1. **Deploy:**
   - Добавить `[tui]` секцию в `~/.codelab/codelab.toml.example` как шаблон
   - Обновить `codelab/README.md` с описанием конфигурации тем

2. **Rollback:**
   - Удалить `[tui]` секцию из TOML — система вернётся к JSON конфигур
   - Удалить `--theme` флаг из CLI —不影响 функциональность

3. **Data migration:**
   - Не требуется — JSON конфиг остаётся совместимым
   - Новые пользователи получат default theme "light"

## Open Questions

1. **Textual версия:** Какая версия Textual используется? Нужно проверить поддержку динамической CSS загрузки.
2. **CodeBlock theme:** CodeBlock использует `theme="monokai"` для markdown highlighting — нужно ли менять на светлую тему для light mode?
3. **Scrollbar styling:** Textual scrollbars могут иметь собственные стили — нужно проверить что theme TCSS покрывает их.
