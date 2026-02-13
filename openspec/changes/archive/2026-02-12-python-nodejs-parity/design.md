## Context

The repository currently has a production-proven Node.js bot with stable user/admin flows, scheduler behavior, and queue-based broadcast processing. A Python rewrite exists under `NEW BOT/`, but parity is incomplete in user-visible UX/state flow and some runtime details. The project must keep existing operational safety semantics (flood-aware retry, per-user lock, continuation jobs, queue fairness) while making Python behavior match Node.js expectations.

Constraints:

- Zero regression for core user journeys (`/start`, login, group import, message setup, interval setup, start/stop broadcast).
- Maintain role split (`app` vs `worker`) and existing docker deployment model.
- Keep DB as source of truth and Redis as lock/queue transport.
- Avoid destructive migration or reset.

Stakeholders:

- End users configuring auto-broadcast.
- Admin operators managing access and runtime reliability.
- Maintainers needing predictable parity for future feature work.

## Goals / Non-Goals

**Goals:**

- Achieve 1:1 behavioral parity between Python and Node.js bot UX/state flow.
- Ensure login/session pipeline is robust for phone, code (including spaced code), and 2FA.
- Align scheduler/worker broadcast semantics with Node.js fairness and flood-safe runtime behavior.
- Provide parity-focused validation so future changes can be checked against Node behavior.

**Non-Goals:**

- Re-architecting business logic beyond what is needed for parity.
- Introducing new product features not already present in Node.js bot.
- Replacing infrastructure stack (Postgres/Redis/containers) or changing deployment topology.

## Decisions

1. Canonical parity source = Node.js `src/bot/bot.service.ts` flows (functional parity contract)

- Decision: Treat Node.js handlers, callback map, and state transitions as the authoritative contract for Python behavior, while requiring functional equivalence rather than byte-identical phrasing.
- Rationale: Reduces ambiguity and prevents drift caused by “similar but not identical” rewrites.
- Alternative considered: Functional-only parity (ignore UI wording/state details). Rejected because user-visible differences are currently the root issue.

2. Keep Python split architecture (`bot_runner`, `app`, `worker`) and align semantics, not process shape

- Decision: Maintain separate Python bot polling process and API/worker services, but enforce Node-equivalent logic in each path.
- Rationale: Current deployment already depends on multi-service compose; parity is primarily logic/state consistency.
- Alternative considered: Merge into single process for simplicity. Rejected due to operational mismatch and reduced isolation.

3. Login temporary state stored by deterministic session name; persist final session only after successful auth

- Decision: Use temporary session identity (`login_<userId>`) during code/2FA steps; export/store durable session only after success.
- Rationale: Prevents invalid session export edge cases and mirrors staged auth semantics.
- Alternative considered: Export session string immediately after send_code. Rejected due to runtime failures and unstable partial state.

4. Explicit parity mapping checklist for each UI/state branch

- Decision: Build and maintain a branch-level checklist (command, callback, expected prompt, next state, failure output).
- Rationale: Prevents hidden parity gaps across many callbacks and state transitions.
- Alternative considered: Ad-hoc manual verification. Rejected because it misses edge paths.

5. Preserve broadcast safety semantics from Node.js

- Decision: Keep micro-batch processing, per-user lock, continuation requeue with jitter, retry/backoff with flood hints, and durable attempt statuses.
- Rationale: These controls are essential to throughput fairness and account safety under load.
- Alternative considered: Simplified single-pass broadcast loop. Rejected due to known burst/flood regressions.

## Risks / Trade-offs

- [State drift between Node and Python as Node evolves] -> Mitigation: add parity checklist and regression tests keyed to Node flow names/callback ids.
- [Login edge cases vary by provider behavior (code format, 2FA timing)] -> Mitigation: normalize inputs, explicit exception mapping, and branch-specific logging.
- [Higher implementation effort for strict UX parity] -> Mitigation: prioritize critical user/admin journeys first, then secondary views.
- [Operational restarts can interrupt polling UX] -> Mitigation: keep idempotent state transitions and avoid fragile in-memory-only assumptions.

## Migration Plan

1. Implement parity fixes in Python login and state routing (phone/code/2FA).
2. Align callback/menu behavior with Node contract and verify each callback path.
3. Validate scheduler/worker parity against Node broadcast semantics.
4. Run parity smoke suite (manual + automated).
5. Deploy Python stack in controlled environment and compare outcomes with Node baseline.

Rollback:

- Keep Node bot as fallback runtime; revert traffic/process to Node deployment if parity checks fail.
- Revert Python container images to previous known-good tags if a specific release regresses.

## Open Questions

- Which admin-only flows are mandatory for phase-1 parity versus phase-2 parity?
- Do we enforce parity snapshots in CI as a required gate before deploy?
