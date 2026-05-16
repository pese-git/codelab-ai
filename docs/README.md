# Документы по улучшению кодовой базы CodeLab

Каталог содержит инструкции для разработчиков, организованные по фазам выполнения.  
Каждый документ описывает одну конкретную проблему и содержит пошаговое решение с примерами кода и тестами.

---

## Фаза 0 — Немедленно (до следующего деплоя)

| Документ | Проблема | Оценка |
|---|---|---|
| [0.1 Отзыв API-ключа и очистка Git](phase-0-immediate/0.1-revoke-api-key-clean-git.md) | Реальный API-ключ в истории Git | 1–2 ч |
| [0.2 Pre-commit защита от секретов](phase-0-immediate/0.2-pre-commit-secrets-detection.md) | Нет автоматической защиты от утечки | 1 ч |

---

## Фаза 1 — Критические баги и безопасность (~1.5 недели)

| Документ | Проблема | Оценка |
|---|---|---|
| [1.1 Shell Injection](phase-1-security/1.1-shell-injection.md) | `shell=True` в `TerminalExecutor.execute()` | 2 ч |
| [1.2 Path Traversal](phase-1-security/1.2-path-traversal.md) | `startswith` вместо `is_relative_to` | 1 ч |
| [1.3 F-string инъекция в subprocess](phase-1-security/1.3-subprocess-fstring-injection.md) | Генерация Python-кода через f-string | 2 ч |
| [1.4 Запрос разрешения в FileSystemHandler](phase-1-security/1.4-permission-request-file-handler.md) | Запись файлов без подтверждения пользователя | 4 ч |
| [1.5 asyncio.Future вне SessionState](phase-1-security/1.5-asyncio-future-out-of-session-state.md) | Несериализуемый объект в персистируемой структуре | 5 ч |
| [1.7 Лимит размера WebSocket сообщений](phase-1-security/1.7-websocket-message-size-limit.md) | Нет защиты от oversized сообщений | 1 ч |

---

## Фаза 2 — Архитектурные улучшения (~4 недели)

| Документ | Проблема | Оценка |
|---|---|---|
| [2.1 Устранение двойного кэша сессий](phase-2-architecture/2.1-double-cache-session-state.md) | `_sessions` + `Storage._cache` расходятся | 1.5 дня |
| [2.2 Дедупликация пакетов `content`](phase-2-architecture/2.2-content-packages-deduplication.md) | 6 файлов дублируются в server и shared | 1 день |
| [2.3 Pydantic сериализация в Storage](phase-2-architecture/2.3-pydantic-serialization.md) | 250 строк ручного кода вместо model_dump() | 1.5 дня |
| [2.4 PromptOrchestrator → Pipeline](phase-2-architecture/2.4-prompt-orchestrator-pipeline.md) | 700 строк, 7 зависимостей, нарушение SRP | 2 дня |
| [2.5 Реестр обработчиков в ACPProtocol](phase-2-architecture/2.5-handle-method-registry.md) | Монолитный `handle()` на 400+ строк | 1 день |
| [2.6 asyncio.Lock в GlobalPolicyManager](phase-2-architecture/2.6-global-policy-manager-asyncio-lock.md) | Lock привязан к event loop при импорте | 3 ч |
| [2.7 Инжекция PromptOrchestrator](phase-2-architecture/2.7-inject-prompt-orchestrator.md) | Оркестратор создаётся при каждом вызове | 2 ч |
| [2.8 Миграция DI на dishka](phase-2-architecture/2.8-di-dishka-migration.md) | Самописный контейнер не делает DI | 2 дня |

---

## Фаза 3 — Качество кода (~2 недели)

| Документ | Проблема | Оценка |
|---|---|---|
| [3.1 Аудит type: ignore](phase-3-quality/3.1-type-ignore-audit.md) | 34 подавления, часть маскирует реальные баги | 2 дня |
| [3.2 LSP в ACPTransportService](phase-3-quality/3.2-lsp-transport-service.md) | Нарушение Liskov Substitution Principle | 3 ч |
| [3.3 Типизация mcp_manager](phase-3-quality/3.3-mcp-manager-typing.md) | `mcp_manager: Any` отключает type checking | 1 ч |
| [3.4 structlog без f-strings](phase-3-quality/3.4-structlog-fstrings.md) | f-strings разрушают структурированность логов | 2 ч |
| [3.5 Дедупликация PermissionManager](phase-3-quality/3.5-permission-manager-logic.md) | Дублирующаяся логика в двух методах | 2 ч |
| [3.6 Тесты для security-путей](phase-3-quality/3.6-security-tests.md) | Нет тестов path traversal и shell injection | 1 день |
| [3.7 Rate Limiting для authenticate](phase-3-quality/3.7-rate-limiting-auth.md) | Нет защиты от brute force | 4 ч |
| [3.8 Фикстура GlobalPolicyManager](phase-3-quality/3.8-global-policy-manager-test-fixture.md) | Singleton не сбрасывается между тестами | 1 ч |
| [3.9 Переименование TestViewModel](phase-3-quality/3.9-test-viewmodel-rename.md) | PytestCollectionWarning | 30 мин |

---

## Итого

| Фаза | Задач | Оценка |
|---|---|---|
| Фаза 0 | 2 | ~3 ч |
| Фаза 1 | 6 | ~2 недели |
| Фаза 2 | 8 | ~4 недели |
| Фаза 3 | 9 | ~2 недели |
| **Всего** | **25** | **~8 недель** (1 разработчик) / **~5 недель** (2 разработчика) |

Полное ревью: [CODE_REVIEW.md](../CODE_REVIEW.md)
