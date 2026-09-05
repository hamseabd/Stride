# 0009. Split OIDC Roles for CI

Date: 2026-06-24 · Status: Accepted

## Context

A GitHub Actions workflow can be modified by a pull request on its own branch. If the workflow assumes write permissions, a hostile PR could rewrite Terraform to deploy unauthorized resources, delete data, or exfiltrate secrets. Long-lived credentials stored as GitHub Secrets are a single point of failure.

## Decision

Two IAM roles, both using OIDC trust, with different permissions and different GitHub branch filters. `stride-github-actions` has apply permissions and trusts only pushes to `main`. `stride-github-actions-plan` has read-only permissions, ECR push permission, and trusts only `pull_request` events. PassRole is scoped to the Lambda execution role.

## Consequences

A hostile PR can run plan and push images to ECR, but never apply Terraform or escalate permissions. No secrets are stored as GitHub Secrets; OIDC is the single source of identity. Key rotation is automatic via OIDC token expiry. The split role strategy adds configuration complexity but eliminates long-lived credentials entirely.
