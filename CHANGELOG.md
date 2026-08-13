# Changelog

All notable public changes are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and releases use semantic versioning while the project is pre-1.0.

## [Unreleased]

### Added

- English-first project documentation and a Chinese README.
- Concise architecture overview and public roadmap.
- Cross-stack GitHub Actions validation.
- Issue, pull request, support, and community governance templates.
- Gated DeerFlow H0/H1 harnesses with authenticated execution APIs and pinned upstream boundaries.
- Durable Runtime Supervisor migrations and tested lease, fencing, terminal-event, admission, and external-permit primitives.
- A fail-closed permit-authorizer endpoint backed by a separately privileged PostgreSQL role.

### Changed

- Python CI now installs the locked Harness dependency group and runs pytest as a module for reproducible nested-test imports.

## [0.1.0] - 2026-08-12

### Added

- Initial MIT-licensed public release.
- Java 21 Spring Modulith control plane.
- FastAPI context and runtime boundary.
- React application surfaces.
- Versioned OpenAPI and AsyncAPI contracts.
- Local development orchestration and architecture documentation.

[Unreleased]: https://github.com/tacitjj/enterprise-agent-platform/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/tacitjj/enterprise-agent-platform/releases/tag/v0.1.0
