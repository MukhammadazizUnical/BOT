## ADDED Requirements

### Requirement: Per-account queue isolation

The system SHALL isolate broadcast processing by sender account so that jobs from one account do not consume worker capacity reserved for other accounts.

#### Scenario: Concurrent broadcasts from different accounts

- **WHEN** two or more accounts start broadcasts at the same time
- **THEN** each account's jobs are scheduled in its own partition without blocking unrelated accounts

### Requirement: Deterministic recipient ordering

For a given broadcast campaign, the system SHALL dispatch recipients in a deterministic order that can be reproduced after worker restart.

#### Scenario: Restart during campaign processing

- **WHEN** a worker restarts while a campaign is in progress
- **THEN** processing resumes from the next unsent recipient without reordering already persisted queue position

### Requirement: Configurable concurrency limits

The system SHALL enforce configurable per-account and global dispatch concurrency limits before starting message send attempts.

#### Scenario: Account reaches dispatch limit

- **WHEN** an account already has active sends equal to its configured limit
- **THEN** additional jobs for that account remain queued until capacity is available
