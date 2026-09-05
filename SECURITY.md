# Security

Stride is a personal project that handles real phone numbers, so it is built
with a few hard rules: every inbound webhook is signature-checked, every agent
turn is bound to the authenticated user server-side, and no secret lives in
this repository.

The full list of assets, entry points, and mitigations is in
[docs/threat-model.md](docs/threat-model.md).

## Reporting

If you find a problem, email the address on the GitHub profile with a short
description and reproduction. Please do not open a public issue for anything
that could affect a live user. You will get a reply within a week.
