"""Тесты для tool definitions (FileSystem и Terminal).

Проверяет:
- Корректность регистрации в registry
- Валидность JSON Schema параметров
- Правильность requires_permission флагов
- Соответствие kind категориям ACP
- Структуру определений инструментов
"""

from __future__ import annotations

from codelab.server.tools.base import ToolDefinition
from codelab.server.tools.definitions.filesystem import FileSystemToolDefinitions
from codelab.server.tools.definitions.terminal import TerminalToolDefinitions


class TestFileSystemDefinitions:
    """Тесты определений файловых инструментов."""

    def test_filesystem_read_definition_structure(self) -> None:
        """Проверка структуры определения fs/read_text_file."""
        # Act
        definition = FileSystemToolDefinitions.read_text_file()
        
        # Assert
        assert isinstance(definition, ToolDefinition)
        assert definition.name == "fs/read_text_file"
        assert definition.kind == "read"
        assert definition.requires_permission is True
        assert definition.description is not None
        assert len(definition.description) > 0

    def test_filesystem_read_parameters_json_schema(self) -> None:
        """Проверка JSON Schema параметров fs/read_text_file."""
        # Act
        definition = FileSystemToolDefinitions.read_text_file()
        
        # Assert
        assert "properties" in definition.parameters
        assert "required" in definition.parameters
        assert definition.parameters["type"] == "object"
        
        # Проверка свойств
        props = definition.parameters["properties"]
        assert "path" in props
        assert "line" in props
        assert "limit" in props
        
        # Проверка обязательных полей
        assert "path" in definition.parameters["required"]
        assert "line" not in definition.parameters["required"]
        assert "limit" not in definition.parameters["required"]

    def test_filesystem_read_path_property(self) -> None:
        """Проверка свойства path в fs/read_text_file."""
        # Act
        definition = FileSystemToolDefinitions.read_text_file()
        path_prop = definition.parameters["properties"]["path"]
        
        # Assert
        assert path_prop["type"] == "string"
        assert "description" in path_prop
        assert path_prop["description"] != ""

    def test_filesystem_read_line_property(self) -> None:
        """Проверка свойства line в fs/read_text_file."""
        # Act
        definition = FileSystemToolDefinitions.read_text_file()
        line_prop = definition.parameters["properties"]["line"]
        
        # Assert
        assert line_prop["type"] == "integer"
        assert "description" in line_prop

    def test_filesystem_read_limit_property(self) -> None:
        """Проверка свойства limit в fs/read_text_file."""
        # Act
        definition = FileSystemToolDefinitions.read_text_file()
        limit_prop = definition.parameters["properties"]["limit"]
        
        # Assert
        assert limit_prop["type"] == "integer"
        assert "description" in limit_prop

    def test_filesystem_write_definition_structure(self) -> None:
        """Проверка структуры определения fs/write_text_file."""
        # Act
        definition = FileSystemToolDefinitions.write_text_file()
        
        # Assert
        assert isinstance(definition, ToolDefinition)
        assert definition.name == "fs/write_text_file"
        assert definition.kind == "edit"
        assert definition.requires_permission is True
        assert definition.description is not None

    def test_filesystem_write_parameters_json_schema(self) -> None:
        """Проверка JSON Schema параметров fs/write_text_file."""
        # Act
        definition = FileSystemToolDefinitions.write_text_file()
        
        # Assert
        assert "properties" in definition.parameters
        assert "required" in definition.parameters
        assert definition.parameters["type"] == "object"
        
        # Проверка свойств
        props = definition.parameters["properties"]
        assert "path" in props
        assert "content" in props
        
        # Проверка обязательных полей
        assert "path" in definition.parameters["required"]
        assert "content" in definition.parameters["required"]

    def test_filesystem_write_path_property(self) -> None:
        """Проверка свойства path в fs/write_text_file."""
        # Act
        definition = FileSystemToolDefinitions.write_text_file()
        path_prop = definition.parameters["properties"]["path"]
        
        # Assert
        assert path_prop["type"] == "string"
        assert "description" in path_prop

    def test_filesystem_write_content_property(self) -> None:
        """Проверка свойства content в fs/write_text_file."""
        # Act
        definition = FileSystemToolDefinitions.write_text_file()
        content_prop = definition.parameters["properties"]["content"]
        
        # Assert
        assert content_prop["type"] == "string"
        assert "description" in content_prop

    def test_filesystem_read_kind_is_read(self) -> None:
        """Проверка что read имеет kind='read'."""
        # Act
        definition = FileSystemToolDefinitions.read_text_file()
        
        # Assert
        assert definition.kind == "read"

    def test_filesystem_write_kind_is_write(self) -> None:
        """Проверка что write имеет kind='write'."""
        # Act
        definition = FileSystemToolDefinitions.write_text_file()
        
        # Assert
        assert definition.kind == "edit"

    def test_filesystem_both_require_permission(self) -> None:
        """Проверка что обе операции требуют разрешения."""
        # Act
        read_def = FileSystemToolDefinitions.read_text_file()
        write_def = FileSystemToolDefinitions.write_text_file()
        
        # Assert
        assert read_def.requires_permission is True
        assert write_def.requires_permission is True


class TestTerminalDefinitions:
    """Тесты определений терминальных инструментов."""

    def test_terminal_create_definition_structure(self) -> None:
        """Проверка структуры определения terminal/create."""
        # Act
        definition = TerminalToolDefinitions.create()
        
        # Assert
        assert isinstance(definition, ToolDefinition)
        assert definition.name == "terminal/create"
        assert definition.kind == "execute"
        assert definition.requires_permission is True
        assert definition.description is not None

    def test_terminal_create_parameters_json_schema(self) -> None:
        """Проверка JSON Schema параметров terminal/create."""
        # Act
        definition = TerminalToolDefinitions.create()
        
        # Assert
        assert "properties" in definition.parameters
        assert "required" in definition.parameters
        assert definition.parameters["type"] == "object"
        
        # Проверка свойств
        props = definition.parameters["properties"]
        assert "command" in props
        assert "args" in props
        assert "env" in props
        assert "cwd" in props
        assert "output_byte_limit" in props
        
        # Проверка обязательных полей
        assert "command" in definition.parameters["required"]

    def test_terminal_create_command_property(self) -> None:
        """Проверка свойства command в terminal/create."""
        # Act
        definition = TerminalToolDefinitions.create()
        command_prop = definition.parameters["properties"]["command"]
        
        # Assert
        assert command_prop["type"] == "string"
        assert "description" in command_prop

    def test_terminal_create_args_property(self) -> None:
        """Проверка свойства args в terminal/create."""
        # Act
        definition = TerminalToolDefinitions.create()
        args_prop = definition.parameters["properties"]["args"]
        
        # Assert
        assert args_prop["type"] == "array"
        assert "items" in args_prop
        assert args_prop["items"]["type"] == "string"

    def test_terminal_create_env_property(self) -> None:
        """Проверка свойства env в terminal/create."""
        # Act
        definition = TerminalToolDefinitions.create()
        env_prop = definition.parameters["properties"]["env"]
        
        # Assert
        assert env_prop["type"] == "object"
        assert "additionalProperties" in env_prop

    def test_terminal_create_cwd_property(self) -> None:
        """Проверка свойства cwd в terminal/create."""
        # Act
        definition = TerminalToolDefinitions.create()
        cwd_prop = definition.parameters["properties"]["cwd"]
        
        # Assert
        assert cwd_prop["type"] == "string"
        assert "description" in cwd_prop

    def test_terminal_create_output_byte_limit_property(self) -> None:
        """Проверка свойства output_byte_limit в terminal/create."""
        # Act
        definition = TerminalToolDefinitions.create()
        limit_prop = definition.parameters["properties"]["output_byte_limit"]
        
        # Assert
        assert limit_prop["type"] == "integer"
        assert "description" in limit_prop

    def test_terminal_wait_definition_structure(self) -> None:
        """Проверка структуры определения terminal/wait_for_exit."""
        # Act
        definition = TerminalToolDefinitions.wait_for_exit()
        
        # Assert
        assert isinstance(definition, ToolDefinition)
        assert definition.name == "terminal/wait_for_exit"
        assert definition.kind == "read"
        assert definition.requires_permission is False
        assert definition.description is not None

    def test_terminal_wait_parameters_json_schema(self) -> None:
        """Проверка JSON Schema параметров terminal/wait_for_exit."""
        # Act
        definition = TerminalToolDefinitions.wait_for_exit()
        
        # Assert
        assert "properties" in definition.parameters
        assert "required" in definition.parameters
        assert definition.parameters["type"] == "object"
        
        # Проверка свойств
        props = definition.parameters["properties"]
        assert "terminal_id" in props
        
        # Проверка обязательных полей
        assert "terminal_id" in definition.parameters["required"]

    def test_terminal_wait_terminal_id_property(self) -> None:
        """Проверка свойства terminal_id в terminal/wait_for_exit."""
        # Act
        definition = TerminalToolDefinitions.wait_for_exit()
        term_prop = definition.parameters["properties"]["terminal_id"]
        
        # Assert
        assert term_prop["type"] == "string"
        assert "description" in term_prop

    def test_terminal_wait_does_not_require_permission(self) -> None:
        """Проверка что wait_for_exit не требует разрешения."""
        # Act
        definition = TerminalToolDefinitions.wait_for_exit()
        
        # Assert
        assert definition.requires_permission is False

    def test_terminal_release_definition_structure(self) -> None:
        """Проверка структуры определения terminal/release."""
        # Act
        definition = TerminalToolDefinitions.release()
        
        # Assert
        assert isinstance(definition, ToolDefinition)
        assert definition.name == "terminal/release"
        assert definition.kind == "delete"
        assert definition.requires_permission is False
        assert definition.description is not None

    def test_terminal_release_parameters_json_schema(self) -> None:
        """Проверка JSON Schema параметров terminal/release."""
        # Act
        definition = TerminalToolDefinitions.release()
        
        # Assert
        assert "properties" in definition.parameters
        assert "required" in definition.parameters
        assert definition.parameters["type"] == "object"
        
        # Проверка свойств
        props = definition.parameters["properties"]
        assert "terminal_id" in props
        
        # Проверка обязательных полей
        assert "terminal_id" in definition.parameters["required"]

    def test_terminal_release_terminal_id_property(self) -> None:
        """Проверка свойства terminal_id в terminal/release."""
        # Act
        definition = TerminalToolDefinitions.release()
        term_prop = definition.parameters["properties"]["terminal_id"]
        
        # Assert
        assert term_prop["type"] == "string"
        assert "description" in term_prop

    def test_terminal_create_kind_is_execute(self) -> None:
        """Проверка что create имеет kind='execute'."""
        # Act
        definition = TerminalToolDefinitions.create()
        
        # Assert
        assert definition.kind == "execute"

    def test_terminal_wait_kind_is_read(self) -> None:
        """Проверка что wait_for_exit имеет kind='read'."""
        # Act
        definition = TerminalToolDefinitions.wait_for_exit()
        
        # Assert
        assert definition.kind == "read"

    def test_terminal_release_kind_is_delete(self) -> None:
        """Проверка что release имеет kind='delete'."""
        # Act
        definition = TerminalToolDefinitions.release()
        
        # Assert
        assert definition.kind == "delete"

    def test_terminal_create_requires_permission(self) -> None:
        """Проверка что create требует разрешения."""
        # Act
        definition = TerminalToolDefinitions.create()
        
        # Assert
        assert definition.requires_permission is True


class TestToolDefinitionsConsistency:
    """Тесты консистентности определений инструментов."""

    def test_all_filesystem_definitions_are_tool_definition(self) -> None:
        """Все определения FileSystem - это ToolDefinition."""
        # Act
        read_def = FileSystemToolDefinitions.read_text_file()
        write_def = FileSystemToolDefinitions.write_text_file()
        
        # Assert
        assert isinstance(read_def, ToolDefinition)
        assert isinstance(write_def, ToolDefinition)

    def test_all_terminal_definitions_are_tool_definition(self) -> None:
        """Все определения Terminal - это ToolDefinition."""
        # Act
        create_def = TerminalToolDefinitions.create()
        wait_def = TerminalToolDefinitions.wait_for_exit()
        release_def = TerminalToolDefinitions.release()
        
        # Assert
        assert isinstance(create_def, ToolDefinition)
        assert isinstance(wait_def, ToolDefinition)
        assert isinstance(release_def, ToolDefinition)

    def test_filesystem_definitions_have_valid_names(self) -> None:
        """FileSystem определения имеют валидные имена."""
        # Act
        read_def = FileSystemToolDefinitions.read_text_file()
        write_def = FileSystemToolDefinitions.write_text_file()
        
        # Assert
        assert read_def.name is not None
        assert read_def.name != ""
        assert write_def.name is not None
        assert write_def.name != ""
        assert read_def.name != write_def.name

    def test_terminal_definitions_have_valid_names(self) -> None:
        """Terminal определения имеют валидные имена."""
        # Act
        create_def = TerminalToolDefinitions.create()
        wait_def = TerminalToolDefinitions.wait_for_exit()
        release_def = TerminalToolDefinitions.release()
        
        # Assert
        assert create_def.name is not None
        assert create_def.name != ""
        assert wait_def.name is not None
        assert wait_def.name != ""
        assert release_def.name is not None
        assert release_def.name != ""
        # Проверка что имена уникальны
        names = {create_def.name, wait_def.name, release_def.name}
        assert len(names) == 3

    def test_all_definitions_have_descriptions(self) -> None:
        """Все определения имеют описания."""
        # Act
        fs_defs = [
            FileSystemToolDefinitions.read_text_file(),
            FileSystemToolDefinitions.write_text_file(),
        ]
        term_defs = [
            TerminalToolDefinitions.create(),
            TerminalToolDefinitions.wait_for_exit(),
            TerminalToolDefinitions.release(),
        ]
        
        # Assert
        for definition in fs_defs + term_defs:
            assert definition.description is not None
            assert len(definition.description) > 0

    def test_all_definitions_have_kind(self) -> None:
        """Все определения имеют kind."""
        # Act
        fs_defs = [
            FileSystemToolDefinitions.read_text_file(),
            FileSystemToolDefinitions.write_text_file(),
        ]
        term_defs = [
            TerminalToolDefinitions.create(),
            TerminalToolDefinitions.wait_for_exit(),
            TerminalToolDefinitions.release(),
        ]
        
        # Assert
        for definition in fs_defs + term_defs:
            assert definition.kind is not None
            assert definition.kind in ["read", "edit", "execute", "delete"]

    def test_all_definitions_have_parameters(self) -> None:
        """Все определения имеют параметры."""
        # Act
        fs_defs = [
            FileSystemToolDefinitions.read_text_file(),
            FileSystemToolDefinitions.write_text_file(),
        ]
        term_defs = [
            TerminalToolDefinitions.create(),
            TerminalToolDefinitions.wait_for_exit(),
            TerminalToolDefinitions.release(),
        ]
        
        # Assert
        for definition in fs_defs + term_defs:
            assert definition.parameters is not None
            assert isinstance(definition.parameters, dict)
            assert "type" in definition.parameters

    def test_all_parameters_are_valid_json_schema(self) -> None:
        """Все параметры - валидные JSON Schema."""
        # Act
        fs_defs = [
            FileSystemToolDefinitions.read_text_file(),
            FileSystemToolDefinitions.write_text_file(),
        ]
        term_defs = [
            TerminalToolDefinitions.create(),
            TerminalToolDefinitions.wait_for_exit(),
            TerminalToolDefinitions.release(),
        ]
        
        # Assert
        for definition in fs_defs + term_defs:
            params = definition.parameters
            assert "type" in params
            assert "properties" in params or "items" in params
            if "properties" in params:
                assert isinstance(params["properties"], dict)

    def test_filesystem_tools_have_read_edit_kinds(self) -> None:
        """FileSystem инструменты имеют read/edit kinds."""
        # Act
        read_def = FileSystemToolDefinitions.read_text_file()
        write_def = FileSystemToolDefinitions.write_text_file()
        
        # Assert
        assert read_def.kind == "read"
        assert write_def.kind == "edit"

    def test_terminal_tools_have_execute_read_delete_kinds(self) -> None:
        """Terminal инструменты имеют execute/read/delete kinds."""
        # Act
        create_def = TerminalToolDefinitions.create()
        wait_def = TerminalToolDefinitions.wait_for_exit()
        release_def = TerminalToolDefinitions.release()
        
        # Assert
        assert create_def.kind == "execute"
        assert wait_def.kind == "read"
        assert release_def.kind == "delete"
