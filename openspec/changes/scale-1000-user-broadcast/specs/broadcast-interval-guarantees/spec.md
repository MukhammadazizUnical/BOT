## ADDED Requirements

### Requirement: Campaign interval lower-bound guarantee
The system SHALL NOT execute a campaign send cycle earlier than the configured interval for that campaign, measured from the campaign's last successful cycle boundary.

#### Scenario: Five-minute campaign due check
- **WHEN** a campaign is configured with `interval=300` seconds and the previous successful cycle boundary is less than 300 seconds ago
- **THEN** the scheduler and processor SHALL not execute a new cycle for that campaign

### Requirement: Interval drift reporting
The system SHALL record and expose scheduling lag metrics per campaign cycle so operators can verify interval compliance under load.

#### Scenario: Cycle starts after queue delay
- **WHEN** a due campaign cycle starts later than its scheduled due timestamp
- **THEN** the runtime SHALL emit lag telemetry including campaign identifier, scheduled time, start time, and lag milliseconds

### Requirement: Provider-constrained delay classification
The system SHALL classify delays caused by Telegram flood/slow-mode constraints separately from scheduler/runtime drift.

#### Scenario: Flood wait extends cycle start
- **WHEN** Telegram returns a provider wait that pushes execution beyond configured interval
- **THEN** the runtime SHALL classify the delay as provider-constrained and SHALL not classify it as early-run or scheduler drift violation
