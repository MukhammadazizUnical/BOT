## MODIFIED Requirements

### Requirement: Per-account queue isolation
The system SHALL isolate broadcast processing by sender account so that jobs from one account do not consume worker capacity reserved for other accounts, and SHALL prioritize actionable campaigns over non-actionable ones when worker capacity is limited.

#### Scenario: Concurrent broadcasts from different accounts
- **WHEN** two or more accounts start broadcasts at the same time
- **THEN** each account's jobs are scheduled in its own partition without blocking unrelated accounts

#### Scenario: Non-actionable campaign is due
- **WHEN** a campaign is due but the user has no currently available Telegram account
- **THEN** the scheduler SHALL skip enqueue for that campaign and SHALL preserve worker capacity for actionable campaigns

### Requirement: Configurable concurrency limits
The system SHALL enforce configurable per-account and global dispatch concurrency limits before starting message send attempts, and SHALL bound per-job claim size so a single campaign cannot monopolize low worker pools.

#### Scenario: Account reaches dispatch limit
- **WHEN** an account already has active sends equal to its configured limit
- **THEN** additional jobs for that account remain queued until capacity is available

#### Scenario: Low-worker fairness under heavy load
- **WHEN** worker count is low and many campaigns are due
- **THEN** one campaign job SHALL process at most the configured attempt budget for that run before yielding to other queued work
