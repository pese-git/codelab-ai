## ADDED Requirements

### Requirement: TUIConfigStore TOML loading capability
The TUIConfigStore SHALL support loading configuration from TOML files in addition to JSON, with proper merge priority.

#### Scenario: Load theme from TOML [tui] section
- **WHEN** TOML file contains `[tui]` section with `theme` key
- **THEN** TUIConfigStore SHALL extract theme value and include it in merged config

#### Scenario: Load host/port from TOML [tui] section
- **WHEN** TOML file contains `[tui]` section with `host` and `port` keys
- **THEN** TUIConfigStore SHALL extract these values and include them in merged config

#### Scenario: Merge JSON and TOML configs
- **WHEN** both JSON config and TOML files exist
- **THEN** TUIConfigStore SHALL merge them with TOML values overriding JSON values

### Requirement: TUIConfigStore priority resolution
The TUIConfigStore SHALL resolve configuration from multiple sources with defined priority: JSON < TOML chain.

#### Scenario: TOML overrides JSON for theme
- **WHEN** JSON has `theme: "light"` and TOML has `theme = "dark"`
- **THEN** resolved config SHALL have `theme = "dark"`

#### Scenario: JSON used when TOML has no [tui] section
- **WHEN** JSON has theme value and TOML has no `[tui]` section
- **THEN** resolved config SHALL use theme from JSON
