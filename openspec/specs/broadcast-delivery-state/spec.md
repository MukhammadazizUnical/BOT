# broadcast-delivery-state Specification

## Purpose

Define durable broadcast attempt lifecycle guarantees so delivery outcomes are explicit, recoverable, and idempotent across retries and restarts.

## Requirements

### Requirement: Attempt lifecycle state machine

Each broadcast recipient attempt SHALL persist lifecycle transitions through `pending`, `in-flight`, `sent`, and `failed-terminal` states.

#### Scenario: Successful send completion

- **WHEN** a send attempt receives provider success confirmation
- **THEN** the attempt transitions to `sent` with completion timestamp

### Requirement: Terminal failure is explicit

The system SHALL mark an attempt as `failed-terminal` only for non-retriable errors or after retry exhaustion, and SHALL persist a machine-readable failure reason.

#### Scenario: Non-retriable provider error

- **WHEN** a send attempt returns a non-retriable error
- **THEN** the attempt transitions to `failed-terminal` with a persisted terminal reason code

### Requirement: Idempotent attempt identity

The system SHALL use a deterministic idempotency key per campaign-recipient attempt to prevent duplicate terminal sends across retries or worker restarts.

#### Scenario: Duplicate execution after restart

- **WHEN** the same campaign-recipient attempt is picked up again after restart
- **THEN** the system reuses the existing attempt identity and does not emit a second terminal send for the same attempt key
