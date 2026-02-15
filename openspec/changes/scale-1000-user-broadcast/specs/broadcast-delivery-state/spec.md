## MODIFIED Requirements

### Requirement: Attempt lifecycle state machine
Each broadcast recipient attempt SHALL persist lifecycle transitions through `pending`, `in-flight`, `sent`, and `failed-terminal` states, and SHALL only re-enter `pending` for a new campaign cycle after the configured interval window has elapsed.

#### Scenario: Successful send completion
- **WHEN** a send attempt receives provider success confirmation
- **THEN** the attempt transitions to `sent` with completion timestamp

#### Scenario: Interval window not elapsed
- **WHEN** an attempt is already `sent` and the configured campaign interval has not yet elapsed
- **THEN** the attempt SHALL NOT be recycled to `pending` for the next cycle

### Requirement: Terminal failure is explicit
The system SHALL mark an attempt as `failed-terminal` only for non-retriable errors or after retry exhaustion, SHALL persist a machine-readable failure reason, and SHALL recycle terminal attempts to `pending` only when a new interval cycle is eligible.

#### Scenario: Non-retriable provider error
- **WHEN** a send attempt returns a non-retriable error
- **THEN** the attempt transitions to `failed-terminal` with a persisted terminal reason code

#### Scenario: New cycle after terminal state
- **WHEN** a campaign interval boundary is reached after prior `failed-terminal` attempts
- **THEN** eligible terminal attempts MAY be reset to `pending` with retry counters cleared for the new cycle
