## ADDED Requirements

### Requirement: Flood errors are retriable

The system SHALL classify Telegram flood/rate-limit responses as retriable unless maximum retry attempts are exhausted.

#### Scenario: Flood response received

- **WHEN** a send attempt returns a flood/rate-limit error
- **THEN** the attempt is marked for retry instead of terminal failure

### Requirement: Backoff follows provider guidance

The system SHALL schedule retry delay from provider-provided `retry_after` when available and SHALL apply bounded jitter to avoid synchronized retries.

#### Scenario: retry_after is provided

- **WHEN** Telegram returns a flood error with `retry_after`
- **THEN** the next attempt is scheduled no earlier than `retry_after` plus bounded jitter

### Requirement: Retry policy is bounded

The system SHALL enforce a configurable maximum number of retries and SHALL transition the attempt to terminal failure only after the retry budget is exhausted.

#### Scenario: Retry budget exhausted

- **WHEN** the attempt reaches its configured maximum retry count
- **THEN** the system marks the attempt as terminally failed with reason `retry-exhausted`
