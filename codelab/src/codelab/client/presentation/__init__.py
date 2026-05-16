"""Presentation Layer (MVVM паттерн).

Модуль содержит ViewModels и Observable объекты для управления UI состоянием.
Полностью отделён от Textual и может использоваться с любым интерфейсом.

Компоненты:
- Observable: Реактивное свойство с Observer паттерном
- ObservableCommand: Команда с отслеживанием статуса выполнения
- BaseViewModel: Базовый класс для всех ViewModels
- SessionViewModel: ViewModel для управления сессиями
- ChatViewModel: ViewModel для управления чатом
- UIViewModel: ViewModel для общего UI состояния
"""

from codelab.client.presentation.base_view_model import BaseViewModel
from codelab.client.presentation.chat_view_model import ChatViewModel
from codelab.client.presentation.file_viewer_view_model import FileViewerViewModel
from codelab.client.presentation.filesystem_view_model import FileSystemViewModel
from codelab.client.presentation.observable import Observable, ObservableCommand
from codelab.client.presentation.permission_view_model import PermissionViewModel
from codelab.client.presentation.plan_view_model import PlanViewModel
from codelab.client.presentation.session_view_model import SessionViewModel
from codelab.client.presentation.terminal_log_view_model import TerminalLogViewModel
from codelab.client.presentation.terminal_view_model import TerminalViewModel
from codelab.client.presentation.ui_view_model import UIViewModel

__all__ = [
    'Observable',
    'ObservableCommand',
    'BaseViewModel',
    'UIViewModel',
    'SessionViewModel',
    'ChatViewModel',
    'PlanViewModel',
    'TerminalViewModel',
    'FileSystemViewModel',
    'FileViewerViewModel',
    'PermissionViewModel',
    'TerminalLogViewModel',
]
