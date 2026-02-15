## MODIFIED Requirements

### Requirement: Scheduler and queue enqueue parity
The Python scheduler SHALL enqueue due broadcast configurations with equivalent due-window logic, bounded tick processing, and jitter-spread behavior as the Node.js scheduler, while enforcing a strict interval lower bound so campaigns are not executed earlier than configured.

#### Scenario: Due configuration enqueued
- **WHEN** an active broadcast configuration reaches due time
- **THEN** the scheduler MUST enqueue a broadcast job and update run bookkeeping equivalent to Node.js behavior

#### Scenario: Burst spread with deterministic jitter
- **WHEN** multiple users are due in the same scheduler window
- **THEN** enqueue timing MUST be jittered to reduce synchronized burst pressure

#### Scenario: Early-run prevention
- **WHEN** scheduler bookkeeping is updated by non-message config changes
- **THEN** the runtime MUST still prevent execution before the configured interval boundary

### Requirement: Processor fairness and per-user lock parity
The Python worker SHALL enforce per-user mutual exclusion and micro-batch execution semantics equivalent to the Node.js broadcast processor, and SHALL treat pending-only continuation states as deferred progress rather than hard failures.

#### Scenario: User lock prevents parallel processing
- **WHEN** concurrent jobs for the same user are available
- **THEN** only one job path MUST process that user while others defer or skip

#### Scenario: Continuation requeue for partial completion
- **WHEN** a batch run leaves pending or in-flight attempts without terminal failures
- **THEN** the processor MUST schedule a continuation job with configured delay and jitter

#### Scenario: Deferred batch status
- **WHEN** a processor run sends zero or more attempts and leaves only pending/in-flight work with no terminal failures
- **THEN** the run result MUST be reported as non-failure with defer context
