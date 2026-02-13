# nodejs-parity-broadcast-runtime Specification

## Purpose
TBD - created by archiving change python-nodejs-parity. Update Purpose after archive.
## Requirements
### Requirement: Scheduler and queue enqueue parity

The Python scheduler SHALL enqueue due broadcast configurations with equivalent due-window logic, bounded tick processing, and jitter-spread behavior as the Node.js scheduler.

#### Scenario: Due configuration enqueued

- **WHEN** an active broadcast configuration reaches due time
- **THEN** the scheduler MUST enqueue a broadcast job and update run bookkeeping equivalent to Node.js behavior

#### Scenario: Burst spread with deterministic jitter

- **WHEN** multiple users are due in the same scheduler window
- **THEN** enqueue timing MUST be jittered to reduce synchronized burst pressure

### Requirement: Processor fairness and per-user lock parity

The Python worker SHALL enforce per-user mutual exclusion and micro-batch execution semantics equivalent to the Node.js broadcast processor.

#### Scenario: User lock prevents parallel processing

- **WHEN** concurrent jobs for the same user are available
- **THEN** only one job path MUST process that user while others defer or skip

#### Scenario: Continuation requeue for partial completion

- **WHEN** a batch run leaves pending or in-flight attempts without terminal failures
- **THEN** the processor MUST schedule a continuation job with configured delay and jitter

### Requirement: Attempt lifecycle, retry, and flood-safe parity

The Python runtime SHALL maintain durable broadcast attempt statuses and retry/flood behavior equivalent to Node.js lifecycle semantics.

#### Scenario: Retriable failure path

- **WHEN** a send attempt hits retriable errors (including rate-limit or timeout-like conditions)
- **THEN** the attempt MUST return to pending with computed retry delay and updated retry count

#### Scenario: Terminal failure path

- **WHEN** a send attempt reaches non-retriable classification or exhausts retries
- **THEN** the attempt MUST transition to terminal failure with reason code persisted

#### Scenario: Successful delivery path

- **WHEN** a send attempt succeeds
- **THEN** the attempt MUST transition to sent with timestamp and campaign summary contribution

