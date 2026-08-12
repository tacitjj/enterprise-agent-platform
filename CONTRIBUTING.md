**English** | [简体中文](CONTRIBUTING.zh-CN.md)

# Contributing

Thank you for helping improve Enterprise Agent Platform. The repository is an early reference implementation, so focused changes with explicit boundaries are more useful than broad rewrites.

## Before opening a change

1. Search existing issues and the [roadmap](ROADMAP.md).
2. Open an issue for behavior changes, cross-module work, or new architecture decisions.
3. Keep each pull request independently reviewable and tied to one clear outcome.
4. Never include credentials, real accounts, production data, private endpoints, or assets you are not authorized to publish.

## Architecture boundaries

Changes that affect interfaces, authorization, tenants, tasks, billing, knowledge, memory, or state transitions must identify all affected consumers. In particular:

- Java remains authoritative for tenant, permission, task, billing, and audit facts.
- Python integrations must use versioned internal contracts and fail closed.
- Web API mode must not silently substitute prototype facts.
- Shared OpenAPI and AsyncAPI changes require consumer impact analysis.

## Local validation

Run the smallest relevant checks first, then the complete check for every affected stack.

### Java

```bash
env JAVA_HOME=/path/to/java-21 mvn -f dianlian-platform/pom.xml test
```

### Python

```bash
cd dianlian-ai-runtime
uv sync --frozen
uv run pytest
```

### Web

```bash
cd dianlian-web
npm ci
npm test
npm run test:sites
npm run build
```

## Pull requests

Use the pull request template to describe:

- the result and motivation;
- the checked impact surface;
- exact validation commands and outcomes;
- untested risks or follow-up work;
- security, compatibility, and migration considerations.

By contributing, you agree that your contribution is licensed under the repository's [MIT License](LICENSE).
