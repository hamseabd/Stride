# 0012. Server-Side Tenant Binding

Date: 2026-09-04 · Status: Accepted

## Context

Tools receive the user ID from the Strands SDK, which learned it from the prompt. An attacker who controls input to the SMS handler could inject a phone number into the prompt, and the model could pass it to a tool as the `user_id`. This would redirect the agent to operate on a different user's data.

## Decision

`bind_user()` wraps every agent turn; it extracts the authenticated user ID from the SMS context and stores it in a thread-local or process-local registry. Every user-keyed tool calls `enforce_user()` to verify that the `user_id` parameter matches the bound context. Mismatches are logged but never raised; the tool proceeds with the bound ID.

## Consequences

The model's user ID is advisory; the server enforces the canonical ID. Tools that take `project_id`, `cycle_id`, or `task_id` are not yet bound and are listed in the threat model. A regression test (BUG-002) ensures the binding is enforced. Logging mismatch attempts surfaces injection attempts or legitimate bugs in prompt formatting.
