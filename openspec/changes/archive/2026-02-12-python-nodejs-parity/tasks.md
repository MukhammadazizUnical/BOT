## 1. Parity Baseline and Mapping

- [x] 1.1 Build a Node.js-to-Python parity matrix for user states, callbacks, commands, and expected prompts using `src/bot/bot.service.ts` as source of truth
- [x] 1.2 Enumerate admin-only branches and access-control outcomes in the parity matrix and mark must-have phase-1 flows
- [x] 1.3 Add a repeatable smoke checklist for `/start`, login, group import, message setup, interval setup, and start/stop broadcast

## 2. UI and State Flow Parity

- [x] 2.1 Align Python main menu rendering and callback ids to match Node.js menu structure and transitions
- [x] 2.2 Implement Node-equivalent state transitions for message setup and interval selection, including recovery from stale state
- [x] 2.3 Align admin interaction branches (commands/callback actions) to Node-equivalent behavior and feedback

## 3. Login and Session Parity

- [x] 3.1 Finalize phone-code-2FA flow so temporary login state survives between steps and is cleaned up on success/failure paths
- [x] 3.2 Ensure phone and code normalization supports expected user input formats (including spaced codes) without misrouting state
- [x] 3.3 Align invalid/expired code and missing-session responses to deterministic Node-equivalent recovery behavior
- [x] 3.4 Verify durable Telegram account/session persistence after successful login and 2FA completion

## 4. Broadcast Runtime Parity

- [x] 4.1 Verify scheduler due-window logic, max due per tick behavior, and deterministic jitter match Node scheduler semantics
- [x] 4.2 Verify processor per-user lock, micro-batch budget, and continuation requeue behavior match Node worker semantics
- [x] 4.3 Verify broadcast attempt lifecycle transitions (`pending`, `in-flight`, `sent`, `failed-terminal`) and retry delay logic match Node behavior
- [x] 4.4 Validate flood/retriable classification and retry exhaustion behavior against Node-equivalent outcomes

## 5. Verification and Hardening

- [x] 5.1 Add/update automated tests for login/session edge cases and critical callback/state parity paths
- [x] 5.2 Add/update broadcast parity tests for scheduler enqueue behavior, continuation, and attempt lifecycle transitions
- [x] 5.3 Run end-to-end Docker validation (`app`, `bot`, `worker`) and confirm no critical runtime warnings in logs
- [x] 5.4 Document final parity status with PASS/FAIL evidence for each required flow and list any deferred non-critical deltas
