## MODIFIED Requirements

### Requirement: Backoff follows provider guidance
The system SHALL schedule retry delay from provider-provided `retry_after` when available and SHALL apply bounded jitter to avoid synchronized retries, and SHALL never schedule a retry earlier than the provider-mandated wait.

#### Scenario: retry_after is provided
- **WHEN** Telegram returns a flood error with `retry_after`
- **THEN** the next attempt is scheduled no earlier than `retry_after` plus bounded jitter

#### Scenario: Slow mode wait without explicit retry_after
- **WHEN** a slow-mode style error is detected without a numeric retry_after value
- **THEN** the runtime SHALL apply configured slow-mode default wait as the minimum retry delay

### Requirement: Retry policy is bounded
The system SHALL enforce a configurable maximum number of retries, SHALL keep retriable attempts in `pending` with computed `next_attempt_at`, and SHALL transition the attempt to terminal failure only after the retry budget is exhausted.

#### Scenario: Retry budget exhausted
- **WHEN** the attempt reaches its configured maximum retry count
- **THEN** the system marks the attempt as terminally failed with reason `retry-exhausted`

#### Scenario: Retriable rate-limit before exhaustion
- **WHEN** a retriable flood/rate-limit error occurs and retry budget remains
- **THEN** the attempt remains recoverable and is rescheduled for a future eligible attempt time
