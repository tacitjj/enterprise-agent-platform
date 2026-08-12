**English** | [简体中文](SECURITY.zh-CN.md)

# Security Policy

## Supported versions

The project is an early reference implementation. It does not yet publish a production-supported version or a guaranteed security-fix service level.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting flow:

https://github.com/tacitjj/enterprise-agent-platform/security/advisories/new

Include the affected boundary, reproduction conditions, potential impact, and a suggested remediation direction when possible. Do not disclose unpatched vulnerabilities, credentials, exploit details, or real data in a public issue.

## Deployment notice

The current code is intended for local research and architecture validation. Before any public or production deployment, operators must perform their own threat model and review at least:

- identity, authorization, and tenant isolation;
- model and tool endpoint allowlists;
- network egress and sandbox policy;
- request, payload, and rate limits;
- secret and key lifecycle management;
- dependency and container provenance;
- audit logging, monitoring, backup, and recovery;
- remote side-effect idempotency and reconciliation.

Security-sensitive defaults should fail closed. A green test suite is not a production security certification.
