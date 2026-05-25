"""Дерево файлов проекта для sidebar панели TUI."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

from rich.style import Style
from rich.text import Text
from textual.message import Message
from textual.widget import AwaitRemove
from textual.widgets import DirectoryTree
from textual.widgets._directory_tree import DirEntry
from textual.widgets.tree import TreeNode

if TYPE_CHECKING:
    from codelab.client.presentation.filesystem_view_model import FileSystemViewModel


class FileTree(DirectoryTree):
    """Показывает локальную структуру файлов с фильтрацией скрытых путей.
    
    Интегрирован с FileSystemViewModel для управления состоянием:
    - root_path: корневой путь из ViewModel
    - selected_path: выбранный файл из ViewModel
    - is_loading: статус загрузки из ViewModel
    
    Все изменения UI синхронизируются с ViewModel через Observable паттерн.
    """

    class FileOpenRequested(Message):
        """Событие запроса на открытие файла из дерева."""

        def __init__(self, path: Path) -> None:
            """Сохраняет абсолютный путь выбранного файла."""

            super().__init__()
            self.path = path

    def __init__(
        self,
        *,
        filesystem_vm: FileSystemViewModel,
        root_path: str | None = None,
    ) -> None:
        """Создает дерево файлов с указанным корневым абсолютным путем.
        
        Args:
            filesystem_vm: FileSystemViewModel для управления состоянием.
                Обязательный параметр для MVVM интеграции.
            root_path: Начальный корневой путь (опционально).
                Если указан, используется вместо значения из ViewModel.
        """
        # Сохраняем ViewModel
        self.filesystem_vm = filesystem_vm
        
        # Используем переданный путь или значение из ViewModel
        if root_path:
            self._root_path = Path(root_path).expanduser()
            self.filesystem_vm.set_root(self._root_path)
        else:
            self._root_path = (
                self.filesystem_vm.root_path.value
                or Path.home()
            )
        
        self._changed_paths: set[Path] = set()
        
        # Сохраняем unsubscribe функции для очистки при уничтожении
        self._unsubscribers: list[Callable[[], None]] = []
        
        super().__init__(str(self._root_path), id="file-tree")
        
        # Подписываемся на изменения ViewModel
        self._subscribe_to_view_model()

    def _subscribe_to_view_model(self) -> None:
        """Подписаться на изменения ViewModel.
        
        Устанавливает observers на все Observable свойства ViewModel
        для синхронизации UI при изменениях состояния.
        """
        # Подписываемся на изменение корневого пути
        unsub_root = self.filesystem_vm.root_path.subscribe(
            self._on_root_path_changed
        )
        self._unsubscribers.append(unsub_root)
        
        # Подписываемся на изменение выбранного пути
        unsub_selected = self.filesystem_vm.selected_path.subscribe(
            self._on_selected_path_changed
        )
        self._unsubscribers.append(unsub_selected)
        
        # Подписываемся на изменение статуса загрузки
        unsub_loading = self.filesystem_vm.is_loading.subscribe(
            self._on_loading_changed
        )
        self._unsubscribers.append(unsub_loading)
    
    def _on_root_path_changed(self, new_root: Path | None) -> None:
        """Обработчик изменения корневого пути в ViewModel.
        
        Args:
            new_root: Новое значение корневого пути или None.
        """
        if new_root is None:
            return
        
        normalized_path = new_root.expanduser()
        if not normalized_path.is_absolute():
            return
        if not normalized_path.exists() or not normalized_path.is_dir():
            return
        
        self._root_path = normalized_path
        self._changed_paths = set()
        
        # Обновляем дерево если компонент смонтирован
        try:
            _ = self.app
            self.path = normalized_path
            self.reload()
        except Exception:
            pass  # Компонент еще не смонтирован
    
    def _on_selected_path_changed(self, new_selected: Path | None) -> None:
        """Обработчик изменения выбранного пути в ViewModel.
        
        Args:
            new_selected: Новый выбранный путь или None.
        """
        # Здесь можно добавить логику обновления визуального выделения
        # в дереве если необходимо (зависит от требований)
        pass
    
    def _on_loading_changed(self, is_loading: bool) -> None:
        """Обработчик изменения статуса загрузки в ViewModel.
        
        Args:
            is_loading: True если дерево загружается, False иначе.
        """
        # Здесь можно добавить логику отображения loading indicator
        # или отключения взаимодействия со скомпонентом
        pass
    
    def _unsubscribe_from_view_model(self) -> None:
        """Отписаться от всех изменений ViewModel.
        
        Вызывается при уничтожении компонента для очистки памяти.
        """
        for unsub in self._unsubscribers:
            with suppress(Exception):
                unsub()
        self._unsubscribers.clear()
    
    @property
    def root_path(self) -> Path:
        """Возвращает последнее установленное корневое значение для дерева."""

        return self._root_path

    def set_root_path(self, root_path: str) -> None:
        """Обновляет корневой путь дерева через ViewModel.
        
        Нормализует и валидирует путь, затем обновляет его через
        ViewModel для синхронизации состояния.
        """
        normalized_path = Path(root_path).expanduser()
        if not normalized_path.is_absolute():
            return
        if not normalized_path.exists() or not normalized_path.is_dir():
            return
        
        # Обновляем через ViewModel, который запустит _on_root_path_changed
        self.filesystem_vm.set_root(normalized_path)

    def select_file(self, path: Path | None) -> None:
        """Выбрать файл в дереве через ViewModel.
        
        Обновляет выбранный путь через ViewModel для синхронизации состояния.
        
        Args:
            path: Путь для выбора или None для очистки выбора.
        """
        self.filesystem_vm.select_path(path)
    
    def refresh_tree(self) -> None:
        """Принудительно обновляет дерево файлов, если компонент смонтирован."""

        try:
            _ = self.app
        except Exception:
            return
        self.reload()

    def mark_changed(self, path: Path) -> None:
        """Помечает файл как измененный для визуального индикатора в дереве."""

        normalized_path = path.expanduser().resolve()
        if normalized_path.is_absolute():
            self._changed_paths.add(normalized_path)

    def is_changed(self, path: Path) -> bool:
        """Проверяет, что путь имеет отметку измененного файла в текущем root."""

        return self._path_has_changes(path.expanduser().resolve())

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        """Пробрасывает выбор файла в приложение через отдельное событие.
        
        Синхронизирует выбор с ViewModel и отправляет сообщение приложению.
        """

        if event.path is None:
            return
        selected_path = Path(event.path)
        if not selected_path.is_file():
            return
        
        # Обновляем выбранный путь в ViewModel
        self.filesystem_vm.select_path(selected_path)
        
        # Отправляем сообщение приложению
        self.post_message(self.FileOpenRequested(selected_path))

    def render_label(self, node: TreeNode[DirEntry], base_style: Style, style: Style) -> Text:
        """Добавляет маркер `*` к файлам и директориям с локальными изменениями."""

        label = super().render_label(node, base_style, style)
        node_data = node.data
        if node_data is None:
            return label
        node_path = node_data.path.resolve()
        if self._path_has_changes(node_path):
            label.append(" *", style="bold $warning")
        return label

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        """Скрывает dot-файлы и служебные каталоги из дерева проекта."""

        return [path for path in paths if not path.name.startswith(".")]

    def _path_has_changes(self, path: Path) -> bool:
        """Определяет, затронут ли путь прямым или дочерним изменением."""

        if path in self._changed_paths:
            return True
        if not path.is_dir():
            return False
        return any(changed_path.is_relative_to(path) for changed_path in self._changed_paths)
    
    def remove(self) -> AwaitRemove:
        """Удалить компонент и очистить ресурсы.
        
        Отписываемся от всех observers ViewModel при удалении компонента.
        """
        self._unsubscribe_from_view_model()
        return super().remove()
