# 0005. Single-Table DynamoDB

Date: 2026-03-01 · Status: Accepted

## Context

Stride runs on AWS Lambda with pay-per-request billing. Access patterns are known and stable: user profile lookups, project CRUD, cycle state, task state, message history, and metrics. A solo budget and Lambda's marginal cost per request make database simplicity a priority. Joins and multi-table operations multiply latency and cost.

## Decision

One DynamoDB table (`stride-prod`) with pay-per-request billing. Schema: `pk/sk` plus one global secondary index (`gsi1`). Primary partitions: `USER#`, `PROJECT#`, `CYCLE#`. Consented-user lookups (for the scheduler) use the GSI. Floating-point values are stored as `Decimal` to avoid JSON serialization loss.

## Consequences

No joins. No scans in the application handlers. The scheduler performs a GSI query to locate consented users—this is the single exception, documented in the schema. The schema is locked in `scrumbot-app/CLAUDE.md` and treated as source of truth for access patterns. Changes to the key design require ADR review.

Schema simplicity ensures cost predictability. Per-request billing scales smoothly with user count. All queries use key-based access, guaranteeing consistent latency. The trade-off is denormalization—some data is duplicated across items to support independent queries.
