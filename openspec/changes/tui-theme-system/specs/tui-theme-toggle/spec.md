## ADDED Requirements

### Requirement: Theme toggle action
The system SHALL provide a toggle action that switches between "light" and "dark" themes when invoked via keyboard shortcut (Ctrl+T), command palette, or UI button.

#### Scenario: Toggle from light to dark
- **WHEN** current theme is "light" and toggle action is invoked
- **THEN** system SHALL switch to "dark" theme

#### Scenario: Toggle from dark to light
- **WHEN** current theme is "dark" and toggle action is invoked
- **THEN** system SHALL switch to "light" theme

#### Scenario: Toggle saves theme to config
- **WHEN** theme is toggled via any method
- **THEN** system SHALL save new theme to `~/.codelab/tui_config.json`

#### Scenario: Toggle logs the change
- **WHEN** theme is toggled
- **THEN** system SHALL log the theme change with new theme name

### Requirement: Theme visual indicator in QuickActionsBar
The system SHALL display a theme icon in QuickActionsBar that reflects the current theme: sun icon (☀️) for light theme, moon icon (🌙) for dark theme.

#### Scenario: Show sun icon for light theme
- **WHEN** current theme is "light"
- **THEN** QuickActionsBar SHALL display sun icon (☀️) on theme toggle button

#### Scenario: Show moon icon for dark theme
- **WHEN** current theme is "dark"
- **THEN** QuickActionsBar SHALL display moon icon (🌙) on theme toggle button

#### Scenario: Icon updates on toggle
- **WHEN** theme is toggled
- **THEN** QuickActionsBar icon SHALL update to reflect new theme

### Requirement: Theme display in FooterBar
The system SHALL display the current theme name in FooterBar as text indicator.

#### Scenario: Display "Light" in footer
- **WHEN** current theme is "light"
- **THEN** FooterBar SHALL display "Light" or equivalent indicator

#### Scenario: Display "Dark" in footer
- **WHEN** current theme is "dark"
- **THEN** FooterBar SHALL display "Dark" or equivalent indicator

#### Scenario: Footer updates on toggle
- **WHEN** theme is toggled
- **THEN** FooterBar text SHALL update to reflect new theme name

### Requirement: Command palette theme toggle
The system SHALL include "Toggle Theme" command in command palette that invokes theme toggle action.

#### Scenario: Execute toggle from command palette
- **WHEN** user selects "Toggle Theme" in command palette
- **THEN** system SHALL execute theme toggle action
