## ADDED Requirements

### Requirement: TUI theme configuration from multiple sources
The system SHALL support loading theme configuration from multiple sources with defined priority order: JSON config < TOML global < TOML project < Environment variable < CLI flag < UI toggle.

#### Scenario: Load theme from JSON config only
- **WHEN** no other sources provide theme configuration
- **THEN** system SHALL load theme from `~/.codelab/tui_config.json` with default value "light"

#### Scenario: TOML global overrides JSON config
- **WHEN** `~/.codelab/codelab.toml` contains `[tui]` section with `theme` key
- **THEN** system SHALL use theme from TOML global, overriding JSON config

#### Scenario: TOML project overrides TOML global
- **WHEN** `./codelab.toml` or `./codelab.local.toml` contains `[tui]` section with `theme` key
- **THEN** system SHALL use theme from project TOML, overriding TOML global

#### Scenario: Environment variable overrides TOML
- **WHEN** environment variable `CODELAB_THEME` is set to "light" or "dark"
- **THEN** system SHALL use theme from environment variable, overriding all TOML sources

#### Scenario: CLI flag overrides environment variable
- **WHEN** `codelab connect --theme dark` is executed
- **THEN** system SHALL use theme from CLI flag, overriding environment variable

#### Scenario: UI toggle overrides CLI flag at runtime
- **WHEN** user presses Ctrl+T or clicks theme toggle button
- **THEN** system SHALL switch theme and save to JSON config, overriding all other sources

### Requirement: TOML configuration format
The system SHALL read theme configuration from `[tui]` section in TOML files with key `theme` accepting values "light" or "dark".

#### Scenario: Valid TOML theme value
- **WHEN** TOML file contains `theme = "dark"` in `[tui]` section
- **THEN** system SHALL parse and use "dark" theme

#### Scenario: Invalid TOML theme value
- **WHEN** TOML file contains invalid theme value (not "light" or "dark")
- **THEN** system SHALL fallback to "light" theme and log warning

#### Scenario: Missing [tui] section
- **WHEN** TOML file does not contain `[tui]` section
- **THEN** system SHALL continue without error and use lower priority source

### Requirement: TOML file chain loading
The system SHALL load TOML files in order: `~/.codelab/codelab.toml` → `~/.codelab/auth.toml` → `./codelab.toml` → `./codelab.local.toml` → custom path (if provided).

#### Scenario: Load all existing TOML files
- **WHEN** multiple TOML files exist in the chain
- **THEN** system SHALL merge configurations with later files overriding earlier ones

#### Scenario: Skip non-existent TOML files
- **WHEN** some TOML files in chain do not exist
- **THEN** system SHALL skip them without error and continue with next file
