# nodejs-parity-ui-flow Specification

## Purpose
TBD - created by archiving change python-nodejs-parity. Update Purpose after archive.
## Requirements
### Requirement: User menu and callback parity

The Python bot SHALL present the same user-facing menu structure, callback actions, and state-driven prompts as the Node.js bot for core flows.

#### Scenario: Main menu parity after start

- **WHEN** an allowed user sends `/start` or `/menu`
- **THEN** the bot MUST show the same main menu options and entry points used by the Node.js bot

#### Scenario: Broadcast setup interaction parity

- **WHEN** a user enters message setup and interval setup through menu callbacks
- **THEN** the bot MUST move through equivalent states and prompts as the Node.js bot before activating broadcast configuration

### Requirement: Admin interaction parity

The Python bot SHALL support equivalent admin-visible interaction branches used in the Node.js bot, including user access management paths and related responses.

#### Scenario: Admin-only command behavior

- **WHEN** a non-admin user invokes an admin-only path
- **THEN** the bot MUST deny access with behavior equivalent to the Node.js bot

#### Scenario: Admin access action behavior

- **WHEN** an admin performs access-management callbacks or commands
- **THEN** the bot MUST execute equivalent action outcomes and user feedback to the Node.js bot

