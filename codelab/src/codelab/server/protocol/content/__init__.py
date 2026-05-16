"""Content extraction и validation для ACP протокола.

Модули для работы с content типами и extraction/validation.
Типы контента реэкспортируются из shared для обратной совместимости.
"""

# Реэкспортируем из shared для обратной совместимости внутренних импортов
from codelab.shared.content import (
    AudioContent,
    BlobResource,
    EmbeddedResourceContent,
    ImageContent,
    ResourceLinkContent,
    TextContent,
    TextResource,
)

# Специфичные для сервера утилиты остаются здесь:
from .extractor import ContentExtractor, ExtractedContent
from .formatter import ContentFormatter
from .validator import ContentValidator

__all__ = [
    # из shared (реэкспорт):
    "TextContent",
    "AudioContent",
    "ImageContent",
    "EmbeddedResourceContent",
    "ResourceLinkContent",
    "TextResource",
    "BlobResource",
    # специфичные для сервера:
    "ContentExtractor",
    "ExtractedContent",
    "ContentValidator",
    "ContentFormatter",
]
