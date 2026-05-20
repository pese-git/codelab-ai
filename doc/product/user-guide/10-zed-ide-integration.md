# Интеграция с Zed IDE

> Настройка CodeLab как AI агента в Zed IDE через ACP протокол.

## Обзор

Zed IDE поддерживает внешние AI агенты через ACP протокол. CodeLab можно использовать как agent server для работы прямо в редакторе.

## Установка

### 1. Установка codelab-agent

```bash
pipx install --force "git+https://github.com/pese-git/codelab-ai.git@feature/acp#subdirectory=codelab"
```

Проверка установки:
```bash
codelab --help
```

### 2. Настройка Zed IDE

Откройте настройки Zed: `Zed → Settings → Open Settings` (или `Cmd+,` / `Ctrl+,`)

Добавьте конфигурацию агента в `settings.json`:

```json
{
  "agent_servers": {
    "codelab-agent": {
      "type": "custom",
      "command": "codelab",
      "args": ["serve", "--stdio"],
      "env": {
        "OPENAI_API_KEY": "ваш_api_ключ_здесь"
      }
    }
  }
}
```

### 3. Настройка API ключа

Укажите ваш API ключ в поле `OPENAI_API_KEY`. Поддерживаемые провайдеры:
- OpenAI (`gpt-4o`, `gpt-4o-mini`, и др.)
- OpenAI-совместимые (через `CODELAB_LLM_BASE_URL`)

### Полный пример конфигурации

```json
{
  "agent_servers": {
    "codelab-agent": {
      "type": "custom",
      "command": "codelab",
      "args": ["serve", "--stdio"],
      "env": {
        "OPENAI_API_KEY": "sk-your-key-here",
        "CODELAB_LLM_MODEL": "gpt-4o",
        "CODELAB_LLM_PROVIDER": "openai"
      }
    }
  }
}
```

## Использование

После настройки:
1. Откройте AI панель в Zed (`Cmd+Shift+P` → `Zed AI: Toggle`)
2. Выберите `codelab-agent` из списка агентов
3. Начните диалог с агентом

## Дополнительные параметры

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `CODELAB_LLM_PROVIDER` | Провайдер LLM | `openai` |
| `CODELAB_LLM_MODEL` | Модель LLM | `gpt-4o` |
| `CODELAB_LLM_BASE_URL` | Base URL для совместимых API | — |
| `CODELAB_LLM_TEMPERATURE` | Temperature (0.0-1.0) | `0.7` |

## Troubleshooting

### Агент не появляется в списке
- Проверьте установку: `codelab --help`
- Убедитесь, что `settings.json` валидный JSON

### Ошибка API ключа
- Проверьте валидность ключа
- Убедитесь, что нет лишних пробелов

## См. также
- [Настройка сервера](03-server-setup.md)
- [Конфигурация](04-configuration.md)
