## ADDED Requirements

### Requirement: Dynamic theme application without restart
The system SHALL apply theme changes immediately without requiring application restart, using Textual's CSS refresh mechanism.

#### Scenario: Apply theme on startup
- **WHEN** application starts with theme from config
- **THEN** system SHALL load and apply corresponding TCSS file before UI is displayed

#### Scenario: Apply theme on toggle
- **WHEN** theme is toggled at runtime
- **THEN** system SHALL load new TCSS file and refresh CSS within 500ms

#### Scenario: No visual glitch during theme switch
- **WHEN** theme is toggled
- **THEN** system SHALL not display mixed colors from both themes during transition

### Requirement: TCSS file loading
The system SHALL load theme-specific TCSS files from `tui/themes/` directory: `light.tcss` for light theme, `dark.tcss` for dark theme.

#### Scenario: Load light.tcss for light theme
- **WHEN** theme is set to "light"
- **THEN** system SHALL load `tui/themes/light.tcss` and apply all styles

#### Scenario: Load dark.tcss for dark theme
- **WHEN** theme is set to "dark"
- **THEN** system SHALL load `tui/themes/dark.tcss` and apply all styles

#### Scenario: Handle missing TCSS file
- **WHEN** theme TCSS file does not exist
- **THEN** system SHALL log error and fallback to light theme with default styles

### Requirement: Layout and theme separation
The system SHALL maintain separation between layout styles (in `app.tcss`) and theme colors (in `themes/*.tcss`), with `app.tcss` containing only structural properties (height, width, padding, margin, layout, border-style without colors).

#### Scenario: app.tcss contains no color values
- **WHEN** `app.tcss` is parsed
- **THEN** it SHALL NOT contain any hex color values or color property definitions

#### Scenario: Theme TCSS contains all color definitions
- **WHEN** `themes/light.tcss` or `themes/dark.tcss` is parsed
- **THEN** it SHALL contain all color-related properties (background, color, border-color) for all UI components

#### Scenario: Theme TCSS covers all selectors from app.tcss
- **WHEN** comparing selectors in `app.tcss` and theme TCSS files
- **THEN** every selector with color properties in `app.tcss` SHALL have corresponding selector in both theme TCSS files

### Requirement: ThemeManager CSS variable system
The ThemeManager SHALL generate CSS variables from theme color definitions and apply them to the Textual application.

#### Scenario: Generate CSS variables from theme
- **WHEN** theme is set
- **THEN** ThemeManager SHALL generate CSS variables for all color keys in theme definition

#### Scenario: Apply CSS variables to screen
- **WHEN** CSS variables are generated
- **THEN** system SHALL apply them to Screen root element for cascade inheritance

### Requirement: Component DEFAULT_CSS compatibility
All TUI components using DEFAULT_CSS SHALL use Textual CSS variables (e.g., `$primary`, `$surface`) that adapt to theme changes, not hardcoded color values.

#### Scenario: MessageBubble adapts to theme
- **WHEN** theme is toggled
- **THEN** MessageBubble background colors SHALL update to match new theme

#### Scenario: ActionButton adapts to theme
- **WHEN** theme is toggled
- **THEN** ActionButton background and text colors SHALL update to match new theme

#### Scenario: CodeBlock adapts to theme
- **WHEN** theme is toggled
- **THEN** CodeBlock background and border colors SHALL update to match new theme
