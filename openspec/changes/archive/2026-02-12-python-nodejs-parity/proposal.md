## Why

The Python rewrite currently runs, but user-facing behavior and UI still diverge from the working Node.js bot in important paths (especially login and menu/state handling). We need strict parity so running the Python bot produces the same flows, outcomes, and operator experience as the existing Node.js implementation.

## What Changes

- Align Python bot UI and callback flows to match Node.js menus, states, transitions, and error messages.
- Make login/session lifecycle robust and equivalent to Node.js behavior, including phone/code/2FA edge cases.
- Preserve broadcast pipeline semantics (scheduler, queue, processor, retry/flood handling, per-user locking, continuation jobs) to match Node.js runtime behavior.
- Add parity-focused verification and test coverage for critical user and admin scenarios.

## Capabilities

### New Capabilities

- `nodejs-parity-ui-flow`: Ensure Python bot menus, callbacks, and state transitions match Node.js behavior for users and admins.
- `nodejs-parity-login-session`: Ensure Python login and session management matches Node.js behavior for phone, code, 2FA, and recovery/error states.
- `nodejs-parity-broadcast-runtime`: Ensure Python scheduler/worker/broadcast attempt lifecycle matches Node.js fairness, retry, and flood-safe semantics.

### Modified Capabilities

- None.

## Impact

- Affected code: `NEW BOT/app/bot_runner.py`, `NEW BOT/app/services/userbot_service.py`, `NEW BOT/app/services/scheduler_service.py`, `NEW BOT/app/services/broadcast_processor_service.py`, related DTO/models/config files.
- Affected runtime: `NEW BOT/docker-compose.yml`, `NEW BOT/.env`, bot/worker operational behavior and logs.
- Testing impact: add/update parity checks for login flow, callback/UI flow, and broadcast micro-batch processing.
