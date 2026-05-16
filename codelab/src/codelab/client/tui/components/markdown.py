"""Компонент для рендеринга Markdown контента в TUI.

Отвечает за:
- Рендеринг Markdown текста с поддержкой Rich разметки
- Syntax highlighting для блоков кода
- Поддержка: заголовки, списки, код, ссылки, жирный/курсив

Референс OpenCode: packages/web/src/ui/markdown.tsx
"""

from __future__ import annotations

from textual.widgets import Markdown as TextualMarkdown
from textual.widgets import Static


class MarkdownViewer(TextualMarkdown):
    """Расширенный Markdown viewer с улучшенным стилем.
    
    Использует textual.widgets.Markdown как базу и добавляет:
    - Кастомные стили для чата
    - Поддержку inline code
    - Улучшенный syntax highlighting
    
    Пример:
        >>> md = MarkdownViewer("# Hello\\n**Bold** text with `code`")
        >>> # Отобразит форматированный Markdown
    """
    
    DEFAULT_CSS = """
    MarkdownViewer {
        padding: 0;
        margin: 0;
    }
    
    MarkdownViewer > .code_inline {
        background: $surface;
        color: $secondary;
    }
    """
    
    def __init__(
        self,
        markdown: str = "",
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Инициализирует MarkdownViewer.
        
        Args:
            markdown: Markdown текст для рендеринга
            name: Имя виджета
            id: ID виджета
            classes: CSS классы
        """
        super().__init__(markdown, name=name, id=id, classes=classes)


class InlineMarkdown(Static):
    """Компактный Markdown рендер для коротких inline текстов.
    
    Использует Rich markup вместо полного Markdown парсера для:
    - Быстрого рендеринга коротких сообщений
    - Inline форматирования (bold, italic, code)
    - Не создает лишних отступов/padding
    
    Конвертирует базовый Markdown в Rich markup:
    - **bold** -> [bold]...[/bold]
    - *italic* -> [italic]...[/italic]
    - `code` -> [reverse]...[/reverse]
    - [link](url) -> [link=url]...[/link]
    
    Пример:
        >>> text = InlineMarkdown("**Bold** and *italic* with `code`")
    """
    
    DEFAULT_CSS = """
    InlineMarkdown {
        padding: 0;
        margin: 0;
        height: auto;
    }
    """
    
    def __init__(
        self,
        content: str = "",
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Инициализирует InlineMarkdown.
        
        Args:
            content: Markdown текст
            name: Имя виджета  
            id: ID виджета
            classes: CSS классы
        """
        rendered = self._convert_to_rich(content)
        super().__init__(rendered, name=name, id=id, classes=classes, markup=True)
        self._raw_content = content
    
    @property
    def raw_content(self) -> str:
        """Возвращает исходный Markdown текст."""
        return self._raw_content
    
    def update_content(self, content: str) -> None:
        """Обновляет контент с новым Markdown.
        
        Args:
            content: Новый Markdown текст
        """
        self._raw_content = content
        self.update(self._convert_to_rich(content))
    
    def _convert_to_rich(self, text: str) -> str:
        """Конвертирует Markdown в Rich markup.

        Args:
            text: Markdown текст

        Returns:
            Rich markup строка
        """
        import re

        if not text:
            return ""

        result = text

        # Bold: **text** -> [bold]text[/bold]
        result = re.sub(r'\*\*([^*]+)\*\*', r'[bold]\1[/bold]', result)

        # Italic: *text* -> [italic]text[/italic] (но не **bold**)
        result = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'[italic]\1[/italic]', result)

        # Inline code: `code` -> [reverse]code[/reverse]
        result = re.sub(r'`([^`]+)`', r'[reverse] \1 [/reverse]', result)

        # Links: [text](url) -> text (url) — не используем [link=url] из-за
        # несовместимости Textual markup parser с https:// в значении атрибута
        result = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1 (\2)', result)

        # Strikethrough: ~~text~~ -> [strike]text[/strike]
        result = re.sub(r'~~([^~]+)~~', r'[strike]\1[/strike]', result)

        # Headers: # text -> [bold]text[/bold] (упрощенно для inline)
        result = re.sub(r'^#{1,6}\s+(.+)$', r'[bold]\1[/bold]', result, flags=re.MULTILINE)

        # Экранируем все [ что не являются нашими сгенерированными тегами:
        # [bold], [/bold], [italic], [/italic], [reverse], [/reverse],
        # [strike], [/strike]
        result = re.sub(
            r'\[(?!/?(?:bold|italic|reverse|strike)\])',
            r'\[',
            result,
        )

        return result


class CodeBlock(Static):
    """Блок кода с syntax highlighting.
    
    Использует Rich syntax highlighting для отображения кода
    с подсветкой синтаксиса.
    
    Пример:
        >>> code = CodeBlock("def hello():\\n    print('Hi')", language="python")
    """
    
    DEFAULT_CSS = """
    CodeBlock {
        background: $surface;
        padding: 1;
        margin: 1 0;
        border: solid $primary-background;
    }
    """
    
    def __init__(
        self,
        code: str,
        language: str = "text",
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Инициализирует CodeBlock.
        
        Args:
            code: Исходный код
            language: Язык программирования для подсветки
            name: Имя виджета
            id: ID виджета
            classes: CSS классы
        """
        from rich.syntax import Syntax
        
        self._code = code
        self._language = language
        
        # Создаем Rich Syntax объект
        syntax = Syntax(
            code,
            language,
            theme="monokai",
            line_numbers=False,
            word_wrap=True,
        )
        
        super().__init__(syntax, name=name, id=id, classes=classes)
    
    @property
    def code(self) -> str:
        """Возвращает исходный код."""
        return self._code
    
    @property
    def language(self) -> str:
        """Возвращает язык программирования."""
        return self._language
    
    def update_code(self, code: str, language: str | None = None) -> None:
        """Обновляет код.
        
        Args:
            code: Новый код
            language: Новый язык (опционально)
        """
        from rich.syntax import Syntax
        
        self._code = code
        if language is not None:
            self._language = language
        
        syntax = Syntax(
            code,
            self._language,
            theme="monokai",
            line_numbers=False,
            word_wrap=True,
        )
        self.update(syntax)
