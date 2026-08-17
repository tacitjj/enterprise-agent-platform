# Roadmap

This roadmap separates implemented foundations from planned work. It is directional rather than a compatibility promise.

## Available now

- Java 21 modular control plane for identity, enterprise agents, tasks, billing, knowledge, memory, context, model routing, interaction, and integrations.
- Versioned public/internal OpenAPI contracts, AsyncAPI events, and fixtures.
- FastAPI context indexing and retrieval boundary with internal authentication and PostgreSQL migrations.
- Gated DeerFlow H0/H1 harnesses and durable Supervisor foundations with 23 explicit migrations, lease fencing, terminal-event invariants, external-permit authorization, one-shot dispatch arms, and canonical-outcome reconciliation.
- Default-off governed H12 and structured 3.0 workers with PostgreSQL checkpoints and fenced cross-process takeover.
- React user, enterprise administration, and platform operation surfaces with explicit API adapters.
- Local PostgreSQL/pgvector and Redis orchestration.
- Automated Java, Python, and Web validation.

## Next

- Publish concise English documentation for the public contracts and key security invariants.
- Expand contract tests across Java, Python, and Web consumers.
- Publish reproducible local golden-flow verification for tenant isolation, governed execution, and authorized context retrieval.
- Harden model endpoint policies, request limits, and operational observability.
- Improve contributor onboarding and label issues suitable for first-time contributors.

## Gated research

- Controlled tool execution and remote side-effect reconciliation.
- Multi-node soak tests and operational recovery drills for governed workers.
- Retrieval quality evaluation and optional GraphRAG based on measured need.
- Production deployment guidance after threat modeling and security review.

## Explicit non-goals

- Treating model output as authorization, billing, approval, or task-state truth.
- Enabling arbitrary tools, model endpoints, or filesystem access by default.
- Claiming production readiness before security and operational gates are complete.
