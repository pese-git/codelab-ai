# План обновления документации и Mermaid-схем

## Контекст
Сравнение текущей ветки `opencode/brave-pixel` с `feature/agent` выявило следующие ключевые изменения:

---

## 1. Сервер: ACPProtocol — handle_and_process + send_callback

**Файлы:** `codelab/src/codelab/server/protocol/core.py`

**Изменения:**
- Добавлен метод `handle_and_process()` — основной entry point для транспорта
- Добавлен `_send_callback` — callback для отправки сообщений из фоновых задач
- Добавлен `_execute_tool_in_background()` — фоновая задача выполнения tool после permission approval
- Логика background tool execution перенесена из WebSocketTransport в ACPProtocol

**Что обновить в документации:**
- `ARCHITECTURE.md`: 
  - Обновить описание ACPProtocol — добавить handle_and_process, send_callback
  - Обновить диаграмму транспортных слоёв — показать что background execution теперь в протоколе
  - Обновить секцию "Транспортная абстракция" — показать новый flow
- `doc/product/developer-guide/01-architecture.md`: обновить примеры кода ACPProtocol

---

## 2. Сервер: ToolMapping — маппинг имён инструментов

**Файлы:** `codelab/src/codelab/server/tools/mapping.py` (новый), `registry.py`, `llm_loop.py`, `naive.py`

**Изменения:**
- Новый модуль `mapping.py` с функциями `acp_name_to_llm_name()` и `llm_name_to_acp_name()`
- ACP имена с `/` (например `fs/read_text_file`) конвертируются в LLM-совместимые имена с `_` (`fs_read_text_file`)
- Маппинг применяется в:
  - `_to_openai_tools_format()` в naive.py
  - `SimpleToolRegistry.to_llm_tools()` и `execute_tool()` в registry.py
  - `LLMLoopStage._process_tool_calls()` в llm_loop.py

**Что обновить в документации:**
- `ARCHITECTURE.md`:
  - Добавить ToolMapping в таблицу компонентов
  - Добавить секцию "Маппинг имён инструментов" с диаграммой
- `doc/product/overview/02-architecture.md`: добавить секцию ToolMapping
- `doc/product/developer-guide/01-architecture.md`: добавить описание в Tool System

---

## 3. Транспорт: stdio и WebSocket — новый entry point

**Файлы:** `codelab/src/codelab/server/transport/stdio_runner.py`, `websocket.py`

**Изменения:**
- `stdio_runner.py`: использует `protocol.handle_and_process()` вместо `protocol.handle()`
- `websocket.py`: использует `protocol.handle_and_process()` вместо `protocol.handle()`
- `_execute_tool_in_background()` удалён из WebSocketTransport (перенесён в ACPProtocol)
- Добавлен `_send_protocol_message()` в WebSocketTransport для фоновых задач

**Что обновить в документации:**
- `ARCHITECTURE.md`:
  - Обновить диаграмму транспортного слоя
  - Обновить описание stdio режима
  - Обновить flow обработки сообщений

---

## 4. Клиент: Async callbacks для stdio режима

**Файлы:** `codelab/src/codelab/client/infrastructure/services/acp_transport_service.py`, `chat_view_model.py`

**Изменения:**
- Добавлен `_call_callback()` — поддержка sync и async callbacks
- Все fs/terminal callbacks теперь async (`_handle_fs_read`, `_handle_fs_write`, terminal callbacks)
- `_handle_fs_read` и `_handle_fs_write` используют `asyncio.to_thread()` для sync операций
- Terminal callbacks используют async `create_terminal` + `wait_for_exit` вместо blocking execute

**Что обновить в документации:**
- `ARCHITECTURE.md`:
  - Обновить секцию Background Receive Loop — добавить async callbacks
  - Обновить таблицу компонентов клиента
- `doc/product/developer-guide/01-architecture.md`: обновить описание callbacks

---

## 5. Клиент: TUI — Content API для безопасного рендеринга

**Файлы:** `codelab/src/codelab/client/tui/components/chat_view.py`, `markdown.py`

**Изменения:**
- `chat_view.py`: использует `Content.from_markup()` + `Content.from_text()` вместо Rich markup escape
- `markdown.py`: новый подход к экранированию `[` через placeholder `\u0000LBRACKET\u0000`

**Что обновить в документации:**
- `ARCHITECTURE.md`: обновить описание TUI компонентов
- `doc/product/developer-guide/01-architecture.md`: обновить TUI Layer секцию

---

## Файлы для обновления

1. **ARCHITECTURE.md** (root) — главный архитектурный документ
   - Таблица компонентов (добавить ToolMapping, StdioRunner)
   - Диаграмма серверной архитектуры (добавить ToolMapping слой)
   - Секция "Транспортный слой" (обновить flow с handle_and_process)
   - Секция "Транспортная абстракция" (обновить диаграмму)
   - Добавить секцию "Маппинг имён инструментов"
   - Обновить секцию Background Receive Loop (async callbacks)
   - Обновить таблицу клиентских компонентов

2. **doc/product/overview/02-architecture.md**
   - Обновить "Цикл обработки prompt" (LLMLoopStage с маппингом)
   - Добавить секцию "Маппинг имён инструментов ACP ↔ LLM"
   - Обновить диаграмму LLM Loop (показать маппинг)

3. **doc/product/developer-guide/01-architecture.md**
   - Обновить Tool System секцию (добавить mapping.py)
   - Обновить примеры кода ACPProtocol
   - Обновить TUI Layer (Content API)
   - Обновить Infrastructure Layer (async callbacks)

---

## Приоритет

1. **Высокий:** ARCHITECTURE.md — handle_and_process, ToolMapping
2. **Высокий:** doc/product/overview/02-architecture.md — цикл обработки prompt
3. **Средний:** doc/product/developer-guide/01-architecture.md — ToolMapping, async callbacks
4. **Средний:** TUI компоненты — Content API
