# dianlian-ai-runtime

点联 Python AI Runtime 的版本化防腐入口。Java 仍然持有租户、权限、员工、
知识/记忆业务真相和索引任务租约；本模块只维护可重建的上下文投影并返回证据。

当前 B1 节点交付：

- 进程存活、就绪和能力状态接口。
- 明确的进程角色与功能开关。
- Java 授权后的上下文检索请求、证据包契约和失败关闭入口。
- `llama-index-core==0.14.22` 的固定 `SentenceSplitter` 配置；V1 profile 为
  `context-default-v1`（chunk size 512、overlap 64）。
- PostgreSQL `dianlian_context` 词法投影、显式迁移 CLI，以及 psycopg3 连接池。
- LEXICAL UPSERT/DELETE、按事件序列的 tombstone/fence 和确定性 chunk ID。
- 知识文档/版本精确 allowlist 检索，以及个人/员工/群聊记忆 scope 检索。

当前节点额外交付 DeerFlow Harness H0：

- 只复用锁定 commit 的 `backend/packages/harness` 与 `extension-api`，不搬
  DeerFlow App/UI。
- 使用真实 `RunManager + SQL RunRepository(SQLite) + JsonlRunEventStore +
  AsyncSqliteSaver` 跑无模型、无工具的 interrupt/resume dummy graph。
- 持久化点联 `executionId` 与 DeerFlow `runId` 映射，支持幂等创建、事件游标、
  checkpoint guidance、cancel，以及进程重启后的查询与事件重放。
- H0 是单节点可重复 smoke，不是生产 Supervisor。当前锁定版本没有任意 Worker
  跨进程 claim 并从 checkpoint 接管执行的公共入口，生产 takeover 与能力路由
  均保持关闭。

当前节点不交付：

- 生产级 DeerFlow Run Supervisor 或跨进程 checkpoint takeover。
- 向量索引、GraphRAG、模型答案或业务数据库直读。
- 任何假 Run、假事件或假成功结果。

`POST /internal/v1/retrieval/search` 只有在上下文功能已开启且真实检索器已装配时
才允许返回证据。功能关闭、实现未接入或请求缺少对应来源的显式授权清单时，
接口分别返回 `503` 或契约校验错误，不会把空清单解释为全库检索。

`POST /internal/v1/indexing/apply` 接受严格的 LEXICAL/VECTOR 索引契约。LEXICAL
已实现；没有正式 embedding provider 时，VECTOR 固定返回 HTTP 503 和
`INDEX_PROVIDER_NOT_CONFIGURED`，生产代码不使用 `MockEmbedding`。

两个 Context 接口都要求专用 RS256 Service JWT，不接受用户 Access Token：

- `/internal/v1/retrieval/search` 要求 `context.retrieve`；
- `/internal/v1/indexing/apply` 要求 `context.index.write`。

Python 只接收 `DIANLIAN_SERVICE_JWT_PUBLIC_KEY_RING_JSON` 指向的静态公钥环，
配置形态为 `kid -> 绝对 PEM 文件路径`。公钥环缺失或无效时存活探针保持可用，
就绪探针和受保护接口失败关闭。密钥轮换、固定 issuer/audience 与 60 秒 TTL 上限
见 `docs/adr/ADR-043-内部服务采用专用RS256-Service-JWT.md`。

## Supervisor permit authorizer（默认关闭）

`POST /internal/v1/runtime-supervisor/external-permits/consume-and-authorize`
只负责原子消费一个当前 Run fence 下的 external permit，要求独立 scope
`runtime.external-permit.authorize`。请求体不接受 `consumedBy`；该值只从验签后的
Java Service JWT principal 派生。响应只返回 `APPLIED` 或 `NOT_APPLIED`，不返回
permit、租约或数据库事实，也不会自动接入 H1、模型或工具执行。

该路由默认不注册。启用前必须已应用 Supervisor migration `011`，并为进程注入
只继承 `dianlian_supervisor_permit_authorizer` 的独立登录 DSN：

```bash
DIANLIAN_PERMIT_AUTHORIZER_ENABLED=true \
DIANLIAN_PERMIT_AUTHORIZER_DATABASE_DSN='<injected-authorizer-dsn>' \
DIANLIAN_PERMIT_AUTHORIZER_DATABASE_CONNECT_TIMEOUT_SECONDS=5 \
DIANLIAN_PERMIT_AUTHORIZER_DATABASE_STATEMENT_TIMEOUT_SECONDS=5 \
DIANLIAN_PERMIT_AUTHORIZER_DATABASE_LOCK_TIMEOUT_SECONDS=5 \
DIANLIAN_SERVICE_JWT_PUBLIC_KEY_RING_JSON='{"<kid>":"/absolute/path/to/public-key.pem"}' \
uv run uvicorn dianlian_runtime.app:create_app --factory --host 127.0.0.1 --port 8091
```

启动 readiness 会校验当前登录只能执行 migration `011` 的 current-authority
wrapper，不能执行旧 consume、不能创建 schema 对象，也不能直接访问 Run 与三张
permit 表。连接、语句和行锁等待均有独立上限；任何权限、迁移、数据库或结果契约
异常都会使 authorizer 失败关闭。DSN 不进入 settings 的 `repr`。

## 数据库迁移

应用启动只检查迁移版本，绝不自动建表。先向独立 CLI 注入专用 PostgreSQL DSN：

```bash
DIANLIAN_CONTEXT_DATABASE_DSN='<injected-dsn>' uv run dianlian-context-migrate
```

Run Supervisor 的 `deer_runtime` 迁移账本使用独立 DSN；当前命令只初始化显式迁移账本：

```bash
DIANLIAN_SUPERVISOR_MIGRATION_DATABASE_DSN='<injected-dsn>' \
uv run dianlian-supervisor-migrate
```

再启动服务，并显式开启上下文能力：

```bash
DIANLIAN_CONTEXT_ENABLED=true \
DIANLIAN_CONTEXT_DATABASE_DSN='<injected-dsn>' \
DIANLIAN_SERVICE_JWT_PUBLIC_KEY_RING_JSON='{"<kid>":"/absolute/path/to/public-key.pem"}' \
uv run uvicorn dianlian_runtime.app:app --host 127.0.0.1 --port 8091
```

可配置项包括连接池最小/最大连接数、连接超时和索引 profile；DSN 字段不会进入
settings 的 `repr`，数据库不可用日志只记录异常类型。

## 索引和检索边界

- `sourceContentHash` 表示权威源内容哈希，允许 64～128 位小写 hex；知识投影
  必填，记忆投影可空。`normalizedTextHash` 固定 64 位，必须等于
  `normalizedText` UTF-8 字节的 SHA-256。`normalizationProfileVersion` 也随投影
  固化；两类哈希不得混用。
- fence 身份为 authority、tenant、resource type、resource ID 和 profile。
  `eventSequence` 负责排序；同序 DELETE 优先，tombstone 阻止旧 UPSERT 复活。
- `resourceId` 是稳定的投影/DELETE 键；`sourceId + sourceVersion` 是证据与授权键。
  知识分别映射为 `documentVersionId` 和 `documentId + documentVersionId`，不得
  混为同一组身份。
- `jobId` 与 `leaseEpoch` 原样回传，由 Java 做最终租约回执判断；Python 不接管
  Java 的任务租约真相。
- 知识只按 Java 给出的文档 ID + 版本 ID 精确 allowlist 查询。记忆只按 tenant、
  员工和 scope 查询；GROUP_AGENT 缺 `sourceMessageSequenceNo` 时 fail closed。
- 记忆证据保留 `sourceId`、`sourceVersion`。Java 在进入模型提示词前仍需做最终
  当前版本/删除 fence；本投影不能宣称完全消除并发遗忘竞态。
- `retrievalTrace.strategies` 只记录实际执行策略；当前真实实现只会报告
  `LEXICAL`。

## 验证

默认测试不需要数据库：

```bash
uv run python -m pytest -q tests/test_retrieval.py tests/test_indexing.py tests/test_migrations.py
```

可选真实 PostgreSQL 测试必须使用专用测试库：

```bash
DIANLIAN_TEST_CONTEXT_DATABASE_DSN='<dedicated-test-dsn>' \
uv run python -m pytest -q tests/test_postgres_context.py
```

功能只有在显式迁移、定向测试和故障门禁同时通过后，才能在目标环境设置
`DIANLIAN_CONTEXT_ENABLED=true`。

### DeerFlow H0 smoke

先按 `upstream/deerflow.lock.json` 的 repository/commit 准备一个 sparse checkout，
只需包含 `backend/packages/harness`、`backend/packages/extension-api`、
`backend/pyproject.toml` 和 `backend/uv.lock`。随后执行：

```bash
DIANLIAN_DEERFLOW_SOURCE_ROOT='/absolute/path/to/pinned/deer-flow' \
uv run --group deerflow-h0 pytest -q tests/harness/test_h0_smoke.py
```

该 smoke 不读取任何模型 Key，也不会调用模型、工具或外部 Provider。未提供锁定
源码时默认测试会跳过 H0，而不会联网或静默改用其他 DeerFlow 版本。

### 本地受认证 H0 Runtime API

仓库根目录提供 `deploy/local/scripts/runtime/start-deerflow-h0.sh`。它要求显式设置
`DIANLIAN_DEERFLOW_H0_ENABLED=true`，校验官方 DeerFlow checkout 与
`upstream/deerflow.lock.json` 的 commit 一致，并强制关闭 Context、通用 Agent 和
Run Supervisor。H0 数据写入独立 `DIANLIAN_DEERFLOW_DATA_DIR`，不写 DeerFlow
源码目录。

脚本只接受 `DIANLIAN_SERVICE_JWT_KEY_ID` 与
`DIANLIAN_SERVICE_JWT_PUBLIC_KEY_PATH`，再为当前 Python 进程生成现有公钥环配置；
不会读取 Java 私钥、用户 JWT、模型 Key 或阿里 Key 文件。完整启动、健康检查和
Java Client 环境变量见 `deploy/local/README.md` 的“本地 DeerFlow H0 Runtime API”。
