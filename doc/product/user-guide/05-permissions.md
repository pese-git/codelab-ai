# Система разрешений

> Руководство по управлению разрешениями агента.

## Обзор

CodeLab использует систему разрешений для контроля доступа агента к ресурсам клиента: файловой системе и терминалу. Это обеспечивает безопасность и контроль пользователя над действиями AI.

## Поток выполнения разрешений

```mermaid
sequenceDiagram
    participant User as Пользователь
    participant Client as Клиент (TUI)
    participant WS as WebSocket
    participant ACP as ACPProtocol
    participant PO as PromptOrchestrator
    participant LL as LLMLoopStage
    participant Storage[(SessionStorage)]
    participant TR as ToolRegistry
    participant LLM as LLM Provider

    User->>Client: Вводит prompt
    Client->>WS: session/prompt
    WS->>ACP: handle()
    ACP->>PO: handle_prompt()
    PO->>LL: process(context)
    LL->>LLM: create_completion(messages, tools)
    LLM-->>LL: tool_call (terminal/create)
    
    Note over LL: Проверка разрешений
    LL->>LL: decide_tool_execution()
    Note over LL: Нет политики → ask user
    
    LL->>LL: build_permission_request()
    Note over LL: Устанавливает active_turn.permission_request_id
    LL-->>PO: LLMLoopResult(pending_permission=True)
    PO-->>ACP: ProtocolOutcome(notifications)
    ACP->>Storage: save_session(session)
    Note over Storage: permission_request_id сохранён
    ACP-->>WS: session/request_permission
    WS-->>Client: permission request
    
    Note over Client: UI: показать permission widget
    Client->>User: Показать опции
    
    User->>Client: Выбрать "allow_once"
    Client->>WS: {id: permission_request_id, result: {...}}
    WS->>ACP: handle_client_response()
    ACP->>ACP: _resolve_permission_response()
    ACP->>Storage: find_session_by_permission_request_id()
    Storage-->>ACP: SessionState (permission_request_id совпадает)
    ACP->>ACP: resolve_permission_response_impl()
    Note over ACP: permission_request_id очищен
    ACP-->>WS: ProtocolOutcome(pending_tool_execution)
    
    Note over WS: Фоновая задача: _execute_tool_in_background
    WS->>ACP: execute_pending_tool()
    ACP->>Storage: load_session()
    ACP->>PO: orchestrator.execute_pending_tool()
    PO->>LL: execute_pending_tool()
    LL->>TR: execute_tool(terminal/create)
    TR-->>LL: ToolExecutionResult
    LL->>LLM: continue_turn(tool_results)
    LLM-->>LL: tool_call (terminal/wait_for_exit)
    
    alt Tool не требует permission
        LL->>TR: execute_tool(wait_for_exit)
        TR-->>LL: ToolExecutionResult
        LL->>LLM: continue_turn(tool_results)
        LLM-->>LL: final response (end_turn)
        LL-->>PO: LLMLoopResult(stop_reason=end_turn)
        PO-->>ACP: LLMLoopResult
    else Tool требует permission
        LL->>LL: build_permission_request()
        Note over LL: Устанавливает НОВЫЙ permission_request_id
        LL-->>PO: LLMLoopResult(pending_permission=True)
        PO-->>ACP: LLMLoopResult
        ACP->>Storage: save_session(session)
        Note over Storage: НОВЫЙ permission_request_id сохранён
    end
    
    ACP->>Storage: save_session(session)
    Note over Storage: Актуальное состояние сохранено
    ACP-->>WS: turn completion / notifications
    WS-->>Client: updates
    Client-->>User: Показывает результат
```

## Типы разрешений

### File System

| Операция | Описание | Уровень риска |
|----------|----------|---------------|
| `read` | Чтение файлов | 🟢 Низкий |
| `write` | Запись/изменение файлов | 🟡 Средний |

### Terminal

| Операция | Описание | Уровень риска |
|----------|----------|---------------|
| `execute` | Выполнение команд | 🔴 Высокий |

## Диалог разрешения

При запросе агентом операции появляется диалог:

```
┌────────────────────────────────────────────────────────────┐
│  🔒 Запрос разрешения                                      │
│                                                            │
│  Операция: read_text_file                                  │
│  Путь: /project/src/main.py                                │
│                                                            │
│  [Allow]  [Allow All]  [Always Allow]  [Deny]             │
└────────────────────────────────────────────────────────────┘
```

### Варианты ответа

| Кнопка | Действие | Область |
|--------|----------|---------|
| **Allow** | Разрешить один раз | Только этот запрос |
| **Allow All** | Разрешить все похожие | Текущая сессия |
| **Always Allow** | Всегда разрешать | Глобально |
| **Deny** | Отклонить | Только этот запрос |

## Политики разрешений

### Уровни политик

```mermaid
graph TD
    GLOBAL[Глобальные политики<br/>~/.codelab/data/policies/]
    SESSION[Политики сессии]
    REQUEST[Отдельные запросы]
    
    GLOBAL --> SESSION
    SESSION --> REQUEST
```

### Глобальные политики

Сохраняются в `~/.codelab/data/policies/global_policies.json`:

```json
{
  "rules": [
    {
      "operation": "read",
      "pattern": "*.md",
      "action": "allow"
    },
    {
      "operation": "write",
      "pattern": "node_modules/*",
      "action": "deny"
    }
  ]
}
```

### Политики сессии

Действуют только в текущей сессии и сбрасываются при её закрытии.

## Паттерны путей

Политики поддерживают glob-паттерны:

| Паттерн | Описание |
|---------|----------|
| `*.py` | Все Python файлы |
| `src/**/*` | Все файлы в src и вложенных |
| `test_*.py` | Файлы начинающиеся с test_ |
| `!*.secret` | Исключение файлов |

### Примеры

```json
{
  "rules": [
    {
      "operation": "read",
      "pattern": "**/*.py",
      "action": "allow",
      "comment": "Читать все Python файлы"
    },
    {
      "operation": "write",
      "pattern": "src/**/*",
      "action": "allow",
      "comment": "Писать в src/"
    },
    {
      "operation": "*",
      "pattern": ".env*",
      "action": "deny",
      "comment": "Никогда не трогать .env файлы"
    }
  ]
}
```

## Терминальные разрешения

### Безопасные команды

Команды с низким риском могут быть разрешены по умолчанию:

```json
{
  "terminal_rules": [
    {
      "command_pattern": "ls *",
      "action": "allow"
    },
    {
      "command_pattern": "cat *",
      "action": "allow"
    },
    {
      "command_pattern": "python -m pytest *",
      "action": "allow"
    }
  ]
}
```

### Опасные команды

Рекомендуется всегда блокировать:

```json
{
  "terminal_rules": [
    {
      "command_pattern": "rm -rf *",
      "action": "deny"
    },
    {
      "command_pattern": "sudo *",
      "action": "deny"
    },
    {
      "command_pattern": "* > /dev/*",
      "action": "deny"
    }
  ]
}
```

## Режимы безопасности

### Paranoid Mode

Запрашивать разрешение на каждую операцию:

```json
{
  "mode": "paranoid",
  "default_action": "ask"
}
```

### Standard Mode (по умолчанию)

Спрашивать для write/execute, разрешать read:

```json
{
  "mode": "standard",
  "default_actions": {
    "read": "allow",
    "write": "ask",
    "execute": "ask"
  }
}
```

### Trusted Mode

Разрешать большинство операций (только для доверенных проектов):

```json
{
  "mode": "trusted",
  "default_action": "allow",
  "exceptions": ["rm *", "sudo *"]
}
```

## Управление политиками

Политики разрешений управляются через UI и сохраняются в сессии. Глобальные политики хранятся в `~/.codelab/data/policies/global_permissions.json`.

### Уровни политик

1. **Глобальные политики** — применяются ко всем сессиям
2. **Сессионные политики** — применяются только к текущей сессии
3. **Запрос разрешения** — спрашивает пользователя при каждом вызове

### Сброс политик

```bash
# Сбросить глобальные политики
codelab permissions reset --global

# Сбросить политики сессии
# (происходит автоматически при закрытии сессии)
```

### Экспорт/импорт

```bash
# Экспорт
codelab permissions export > policies.json

# Импорт
codelab permissions import policies.json
```

## Inline разрешения

В чате разрешения отображаются inline:

```
🤖 Агент: Мне нужно прочитать файл main.py
   
   ┌─ 🔒 read_text_file: src/main.py ─┐
   │ [✓ Allow] [✓ All] [✗ Deny]       │
   └──────────────────────────────────┘
   
🤖 Агент: Вот содержимое файла...
```

## Аудит действий

Все операции логируются:

```bash
# Просмотр последних операций
cat ~/.codelab/logs/codelab.log | grep "permission"
```

Формат лога:
```
2024-01-15 10:30:00 [INFO] permission.request operation=read path=/src/main.py
2024-01-15 10:30:02 [INFO] permission.response action=allow user_choice=allow_all
```

## Рекомендации по безопасности

### ✅ Рекомендуется

1. Использовать **Allow All** для безопасных операций (чтение документации)
2. Настроить глобальные политики для частых паттернов
3. Всегда проверять команды терминала перед разрешением

### ⚠️ С осторожностью

1. **Always Allow** для write операций
2. Разрешение команд с `sudo`
3. Операции над системными файлами

### ❌ Не рекомендуется

1. Trusted mode для незнакомых проектов
2. Разрешение `rm -rf`
3. Отключение системы разрешений

## Troubleshooting

### Слишком много запросов

Настройте политики для часто используемых путей:

```json
{
  "rules": [
    {"operation": "read", "pattern": "src/**/*", "action": "allow"}
  ]
}
```

### Агент не может работать

Проверьте, нет ли слишком строгих политик:

```bash
codelab permissions show | grep deny
```

## MCP разрешения

MCP инструменты проходят через ту же систему разрешений, что и встроенные инструменты.

### Определение типа MCP инструмента

Для применения политик разрешений CodeLab определяет тип (kind) MCP инструмента:

| MCP Annotation | ACP Kind | Описание |
|----------------|----------|----------|
| `readOnlyHint: true` | `read` | Только чтение |
| `destructiveHint: true` | `execute` | Разрушительное действие |
| `idempotentHint: true` | `edit` | Изменяемое, но идемпотентное |
| `openWorldHint: true` | `execute` | Внешний мир (API, веб) |

### Эвристика по имени

Если аннотации отсутствуют, используется анализ имени:

| Префикс имени | ACP Kind |
|---------------|----------|
| `read_*`, `get_*`, `list_*`, `fetch_*` | `read` |
| `write_*`, `create_*`, `delete_*`, `remove_*` | `execute` |
| `update_*`, `modify_*`, `set_*` | `edit` |
| Остальные | `other` |

### Политики для MCP

Глобальные политики поддерживают glob-паттерны для MCP инструментов:

```json
{
  "rules": [
    {
      "operation": "read",
      "pattern": "mcp:*:read_*",
      "action": "allow",
      "comment": "Разрешить все MCP read инструменты"
    },
    {
      "operation": "execute",
      "pattern": "mcp:github:*",
      "action": "ask",
      "comment": "Спрашивать для GitHub операций"
    },
    {
      "operation": "*",
      "pattern": "mcp:*:delete_*",
      "action": "deny",
      "comment": "Запретить удаление через MCP"
    }
  ]
}
```

### Диалог разрешения для MCP

```
┌────────────────────────────────────────────────────────────┐
│  🔒 Запрос разрешения                                      │
│                                                            │
│  Операция: [MCP:filesystem] write_file                     │
│  Путь: /project/src/main.py                                │
│  Сервер: filesystem (stdio)                                │
│                                                            │
│  [Allow]  [Allow All]  [Always Allow]  [Deny]             │
└────────────────────────────────────────────────────────────┘
```

### Примеры MCP политик

**Разрешить чтение всех MCP:**
```json
{"operation": "read", "pattern": "mcp:*:*", "action": "allow"}
```

**Спрашивать для конкретных серверов:**
```json
{"operation": "*", "pattern": "mcp:github:*", "action": "ask"}
{"operation": "*", "pattern": "mcp:playwright:*", "action": "ask"}
```

**Разрешить безопасные команды:**
```json
{"operation": "read", "pattern": "mcp:filesystem:read_*", "action": "allow"}
{"operation": "read", "pattern": "mcp:git:*", "action": "allow"}
```

## См. также

- [Инструменты](07-tools.md) — работа с файловой системой и терминалом
- [Сессии](06-sessions.md) — политики на уровне сессии
- [Архитектура разрешений](../../architecture/CLIENT_PERMISSION_HANDLING_ARCHITECTURE.md) — техническая документация
