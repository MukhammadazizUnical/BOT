## ADDED Requirements

### Requirement: Phone-code-2FA login parity

The Python bot SHALL implement phone login, code verification, and optional 2FA completion with outcome semantics equivalent to the Node.js bot.

#### Scenario: Successful login without 2FA

- **WHEN** a user provides a valid phone number and valid login code
- **THEN** the bot MUST authenticate the Telegram account and persist a usable session for future operations

#### Scenario: Successful login with 2FA

- **WHEN** the provider requires password after code verification
- **THEN** the bot MUST request 2FA password and complete login on valid password input

### Requirement: Login input normalization and error parity

The Python bot SHALL normalize supported phone and code input formats and return deterministic user-facing errors for invalid, expired, or missing login state inputs.

#### Scenario: Spaced code normalization

- **WHEN** a user enters code with separators (for example `1 2 3 4 5`)
- **THEN** the bot MUST normalize and validate the code as numeric digits for verification

#### Scenario: Invalid or expired code

- **WHEN** a user submits invalid or expired code
- **THEN** the bot MUST return explicit error guidance and keep or reset state according to Node.js-equivalent flow expectations

#### Scenario: Missing login session state

- **WHEN** code or password is submitted without an active temporary login state
- **THEN** the bot MUST return a recovery message instructing the user to restart login

### Requirement: Durable account/session persistence parity

The Python implementation SHALL persist active Telegram account metadata and session credentials in storage with behavior equivalent to Node.js account lifecycle handling.

#### Scenario: Session persistence after login

- **WHEN** login completes successfully
- **THEN** account record state MUST be persisted as active and reusable by message and broadcast operations
