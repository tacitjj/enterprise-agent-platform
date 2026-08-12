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

当前节点不交付：

- DeerFlow Harness 或 Run Supervisor。
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

## 数据库迁移

应用启动只检查迁移版本，绝不自动建表。先向独立 CLI 注入专用 PostgreSQL DSN：

```bash
DIANLIAN_CONTEXT_DATABASE_DSN='<injected-dsn>' uv run dianlian-context-migrate
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
uv run pytest -q tests/test_retrieval.py tests/test_indexing.py tests/test_migrations.py
```

可选真实 PostgreSQL 测试必须使用专用测试库：

```bash
DIANLIAN_TEST_CONTEXT_DATABASE_DSN='<dedicated-test-dsn>' \
uv run pytest -q tests/test_postgres_context.py
```

功能只有在显式迁移、定向测试和故障门禁同时通过后，才能在目标环境设置
`DIANLIAN_CONTEXT_ENABLED=true`。
