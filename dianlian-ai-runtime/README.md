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

当前节点也提供默认关闭的 governed H12 `agent-worker` 组合入口。它只在显式开启时
装配 Run Supervisor、ADMISSION/MODEL/TOOL permit issuer、受治理 Java gateway、
H12 durable slots 和完整 INITIAL -> TOOL -> AFTER_TOOL Driver；不会回退到旧 H1/H12
链路。Run、租约、permit、dispatch arm 和 canonical outcome 仍由 PostgreSQL
Supervisor 与 Java 权威事实共同约束。

当前节点仍不交付：

- DeerFlow Harness H0/H1 的生产级 Supervisor；governed H12 Worker 是独立的
  默认关闭执行路径。
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

## Governed H12 agent-worker（默认关闭）

`DIANLIAN_GOVERNED_H12_DRIVER_ENABLED` 默认 `false`。开启时进程角色必须是
`agent-worker`，并同时开启 agent 与 Run Supervisor；配置缺失会在启动前失败，
不会静默退回 legacy model/tool endpoint。`DIANLIAN_RUN_SUPERVISOR_AGENT_NAME`
必须与 Java 准入时冻结的 `agentName` 精确一致，不能使用代码默认值猜测。

H12 durable slots 默认使用 `postgres` 后端，通过 Supervisor migration 016 的
current-fenced 整文档 CAS 原语追加不可变 checkpoint。`local` 后端保留给本地开发，
且只允许在 `DIANLIAN_RUNTIME_ENVIRONMENT=local` 时显式选择；staging/production
选择 SQLite 会在启动阶段失败，PostgreSQL 后端反向拒绝本地数据目录。

Supervisor DSN 必须是只继承 `dianlian_supervisor_executor` 的独立登录，不能复用
permit/dispatch/outcome HTTP capability DSN。checkpoint 只保存受治理 intent、
无密钥 exact receipt、显式 dispatch binding 与收敛状态，不保存 JWT、供应商凭证
或业务权威数据。以下是本地 SQLite 开发配置；省略 backend 时默认 PostgreSQL：

```bash
DIANLIAN_RUNTIME_ROLE=agent-worker \
DIANLIAN_RUNTIME_ENVIRONMENT=local \
DIANLIAN_RUNTIME_VERSION='<admitted-runtime-version>' \
DIANLIAN_AGENT_ENABLED=true \
DIANLIAN_RUN_SUPERVISOR_ENABLED=true \
DIANLIAN_GOVERNED_H12_DRIVER_ENABLED=true \
DIANLIAN_GOVERNED_H12_STORE_BACKEND=local \
DIANLIAN_RUN_SUPERVISOR_DATABASE_DSN='<injected-executor-dsn>' \
DIANLIAN_RUN_SUPERVISOR_AGENT_NAME='<admitted-agent-name>' \
DIANLIAN_RUN_SUPERVISOR_LEASE_SECONDS=30 \
DIANLIAN_GOVERNED_H12_DATA_DIR='/var/lib/dianlian/governed-h12' \
DIANLIAN_GOVERNED_H12_PERMIT_TTL_SECONDS=10 \
DIANLIAN_RUNTIME_MODEL_SERVICE_BASE_URL='https://java-internal.example' \
DIANLIAN_RUNTIME_MODEL_SERVICE_JWT_KEY_ID='<kid>' \
DIANLIAN_RUNTIME_MODEL_SERVICE_JWT_PRIVATE_KEY_PATH='/run/secrets/runtime-private.pem' \
uv run uvicorn dianlian_runtime.app:create_app --factory --host 127.0.0.1 --port 8091
```

数据库连接、语句和行锁等待分别由
`DIANLIAN_RUN_SUPERVISOR_DATABASE_*_TIMEOUT_SECONDS` 限制。permit TTL 必须短于
Run lease；任何数据库、JWT、Java gateway 或 durable receipt 不确定结果都按既有
reconciliation 语义失败关闭，不授权 Provider/Tool 重发。PostgreSQL 后端在 Driver 启动前
还会验证当前 executor 登录能解析并执行 migration 016 的 load/save 两个受限函数；迁移或
权限未就绪时进程不会进入 ready。

## Structured 3.0 agent-worker（默认关闭）

`DIANLIAN_STRUCTURED_DRIVER_ENABLED` 默认 `false`，并与
`DIANLIAN_GOVERNED_H12_DRIVER_ENABLED` 强制互斥。它只领取
`TASK_STEP / 3.0 / JAVA_CAPABILITY_STRUCTURED` Run，使用 Supervisor migration 023 的
PostgreSQL append-only checkpoint 原语持久化 Java 权威 Manifest 与无密钥 exact receipt；
不支持本地 SQLite，也不会回退到 H12、Tool 或普通模型入口。

该组合入口只有在依赖完整时才能启动：agent-worker、Run Supervisor executor DSN、与 Java
Admission 精确一致的 agent name、内部 Java URL 以及只签发单 scope JWT 的密钥。示例仅表示
配置契约，仓库和部署清单不默认开启：

```bash
DIANLIAN_RUNTIME_ROLE=agent-worker \
DIANLIAN_RUNTIME_VERSION='<admitted-runtime-version>' \
DIANLIAN_AGENT_ENABLED=true \
DIANLIAN_RUN_SUPERVISOR_ENABLED=true \
DIANLIAN_STRUCTURED_DRIVER_ENABLED=true \
DIANLIAN_RUN_SUPERVISOR_DATABASE_DSN='<injected-executor-dsn>' \
DIANLIAN_RUN_SUPERVISOR_AGENT_NAME='<admitted-structured-agent-name>' \
DIANLIAN_RUN_SUPERVISOR_LEASE_SECONDS=30 \
DIANLIAN_STRUCTURED_DRIVER_PERMIT_TTL_SECONDS=10 \
DIANLIAN_RUNTIME_MODEL_SERVICE_BASE_URL='https://java-internal.example' \
DIANLIAN_RUNTIME_MODEL_SERVICE_JWT_KEY_ID='<kid>' \
DIANLIAN_RUNTIME_MODEL_SERVICE_JWT_PRIVATE_KEY_PATH='/run/secrets/runtime-private.pem' \
uv run uvicorn dianlian_runtime.app:create_app --factory --host 127.0.0.1 --port 8091
```

Driver 启动时先验证 migration 023 的 executor capability；未 ready、current fence 失效、Permit
或 Java 返回不确定时只进入收敛态，不授权重复 Provider 调用，也不释放模型候选正文。

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

## Supervisor dispatch authorizer（默认关闭）

`POST /internal/v1/runtime-supervisor/external-dispatches/consume-and-arm`
只负责原子消费 `MODEL_INVOKE` 或 `TOOL_INVOKE` permit，并为该外部调用建立一次性
dispatch arm。它要求只包含 `runtime.external-dispatch.arm` 的独立 Service JWT；
请求体不接受 `armedBy`，该值只从验签后的 principal subject 派生。响应为
`{decision, grantFact}`：`decision` 是 `GRANTED_NOW`、`DO_NOT_DISPATCH` 或
`NOT_APPLIED`；`NOT_APPLIED` 必须不带事实，其余决策必须带与请求完整绑定的当前
operation attempt 事实。只有 `GRANTED_NOW + DISPATCH_ARMED` 的精确事实，并且调用方
随后赢得本地耐久 Arm CAS，才允许发起外部调用。`DO_NOT_DISPATCH` 只用于按既有事实
收敛，永不授权再次派发；所有 `NOT_APPLIED`、非 200、超时、断连或坏响应也都必须
失败关闭。

该路由默认不注册，也不会自动接入 H1、Java、模型或工具链路。启用前必须已应用
Supervisor migration `012`，并为进程注入只继承
`dianlian_supervisor_dispatch_authorizer` 的独立登录 DSN；不得复用 permit authorizer
DSN：

```bash
DIANLIAN_DISPATCH_AUTHORIZER_ENABLED=true \
DIANLIAN_DISPATCH_AUTHORIZER_DATABASE_DSN='<injected-dispatch-authorizer-dsn>' \
DIANLIAN_DISPATCH_AUTHORIZER_DATABASE_CONNECT_TIMEOUT_SECONDS=5 \
DIANLIAN_DISPATCH_AUTHORIZER_DATABASE_STATEMENT_TIMEOUT_SECONDS=5 \
DIANLIAN_DISPATCH_AUTHORIZER_DATABASE_LOCK_TIMEOUT_SECONDS=5 \
DIANLIAN_SERVICE_JWT_PUBLIC_KEY_RING_JSON='{"<kid>":"/absolute/path/to/public-key.pem"}' \
uv run uvicorn dianlian_runtime.app:create_app --factory --host 127.0.0.1 --port 8091
```

readiness 会校验登录角色只有 arm wrapper 的执行权，没有其它 `deer_runtime` 函数、
表、列、序列或 schema create 权限。该 capability/readiness 权限模型当前以
PostgreSQL 17 为已验证基线；连接、语句和行锁等待使用独立上限，DSN 不进入
settings 的 `repr`。

## Supervisor outcome reconciler（默认关闭）

`POST /internal/v1/runtime-supervisor/external-operation-outcomes/record` 与
`POST /internal/v1/runtime-supervisor/external-operation-outcomes/reconcile` 分别要求
exact-single scope `runtime.external-outcome.record` 和
`runtime.external-outcome.reconcile`。请求体不接受 `evidenceKind` 或 `recordedBy`：
前者由 Python 固定为 `JAVA_CANONICAL_FACT`，后者只从验签后的 principal subject
派生。两路响应都只有 `outcome: APPLIED|NOT_APPLIED`，不会返回 Supervisor 事实，
也不会自动接入 Java、H1、模型或工具链路。

两条路由默认不注册。启用前必须已应用 Supervisor migration `012`，并为进程注入
只继承 `dianlian_supervisor_outcome_reconciler` 的独立登录 DSN：

```bash
DIANLIAN_OUTCOME_RECONCILER_ENABLED=true \
DIANLIAN_OUTCOME_RECONCILER_DATABASE_DSN='<injected-outcome-reconciler-dsn>' \
DIANLIAN_OUTCOME_RECONCILER_DATABASE_CONNECT_TIMEOUT_SECONDS=5 \
DIANLIAN_OUTCOME_RECONCILER_DATABASE_STATEMENT_TIMEOUT_SECONDS=5 \
DIANLIAN_OUTCOME_RECONCILER_DATABASE_LOCK_TIMEOUT_SECONDS=5 \
DIANLIAN_SERVICE_JWT_PUBLIC_KEY_RING_JSON='{"<kid>":"/absolute/path/to/public-key.pem"}' \
uv run uvicorn dianlian_runtime.app:create_app --factory --host 127.0.0.1 --port 8091
```

readiness 会要求该登录精确且仅能执行 record/reconcile 两个 wrapper，不能拥有其它
`deer_runtime` 函数、表、列、序列或 schema create 权限。连接、语句和锁等待使用
独立上限，DSN 不进入 settings 的 `repr`。

## Supervisor Run admitter（默认关闭）

`POST /internal/v1/runtime-supervisor/run-admissions/admit` 只接收 Java 业务事务已经
冻结并写入 outbox 的 32 字段 Run admission payload，要求 exact-single scope
`runtime.run.admit`。请求显式区分 `CONVERSATION` 与 `TASK_STEP` 来源，并包含 Runtime
Thread、任务/步骤、员工、用户、可选会话来源、部署版本、
预算、输入 Artifact、admission snapshot、稳定幂等身份和受控 `RUN_ACCEPTED` 事件；
Runtime 不从 HTTP principal 或默认值补造其中任何业务字段。响应只有
`outcome: APPLIED|NOT_APPLIED`。提交响应丢失时，调用方只能重放同一持久 payload，
不能重新生成 Run、Thread、事件或哈希。

路由默认不注册；Java 已有独立且默认关闭的 lease-fenced outbox 投递 worker，但尚未
生产启用，也未接现有 H1、模型、工具、角色流程或页面。启用前必须应用 migration
`017`，并为 runtime-api 注入只继承 sealed
`dianlian_supervisor_run_admitter` 的独立登录 DSN；不得复用 executor、permit、dispatch、
outcome 或 controller DSN：

```bash
DIANLIAN_RUN_ADMITTER_ENABLED=true \
DIANLIAN_RUN_ADMITTER_DATABASE_DSN='<injected-run-admitter-dsn>' \
DIANLIAN_RUN_ADMITTER_DATABASE_CONNECT_TIMEOUT_SECONDS=5 \
DIANLIAN_RUN_ADMITTER_DATABASE_STATEMENT_TIMEOUT_SECONDS=5 \
DIANLIAN_RUN_ADMITTER_DATABASE_LOCK_TIMEOUT_SECONDS=5 \
DIANLIAN_SERVICE_JWT_PUBLIC_KEY_RING_JSON='{"<kid>":"/absolute/path/to/public-key.pem"}' \
uv run uvicorn dianlian_runtime.app:create_app --factory --host 127.0.0.1 --port 8091
```

readiness 会要求该登录只能执行 `admit_runtime_run`，不能拥有其它 `deer_runtime`
函数、表、列、序列或 schema create 权限。该路由保留 32 KiB 流式请求上限，以覆盖
当前最多 256 个 Artifact ID 的 exact payload；其它高权路由仍保持 8 KiB 上限。

## Supervisor Run observer（默认关闭）

`POST /internal/v1/runtime-supervisor/run-projections/read` 以一次数据库快照读取一个
Run 的原生状态、终态/租约水位、Checkpoint 引用和有界连续事件页，要求
exact-single scope `runtime.run.observe`。请求必须精确绑定 tenant、Run、任务步骤、
执行代次、request hash 与事件游标；事件已经越过保留水位时返回显式 `replayGap`，
不会把残缺事件页伪装成可继续投影。不存在与服务不可用分别返回 404 和 503。

路由默认不注册，Java 的只读 client 也默认关闭；当前没有接入
`TaskRuntimeSyncApplicationService`，不会替换现有 H1 snapshot/event 来源或触发双启动。
启用前必须应用 migration `018`，并为 runtime-api 注入只继承 sealed
`dianlian_supervisor_run_observer` 的独立登录 DSN；不得复用 executor、admitter、
controller、permit、dispatch 或 outcome DSN：

```bash
DIANLIAN_RUN_OBSERVER_ENABLED=true \
DIANLIAN_RUN_OBSERVER_DATABASE_DSN='<injected-run-observer-dsn>' \
DIANLIAN_RUN_OBSERVER_DATABASE_CONNECT_TIMEOUT_SECONDS=5 \
DIANLIAN_RUN_OBSERVER_DATABASE_STATEMENT_TIMEOUT_SECONDS=5 \
DIANLIAN_RUN_OBSERVER_DATABASE_LOCK_TIMEOUT_SECONDS=5 \
DIANLIAN_SERVICE_JWT_PUBLIC_KEY_RING_JSON='{"<kid>":"/absolute/path/to/public-key.pem"}' \
uv run uvicorn dianlian_runtime.app:create_app --factory --host 127.0.0.1 --port 8091
```

readiness 会要求该登录只能执行 `read_runtime_run_projection`，不能拥有其它
`deer_runtime` 函数、表、列、序列或 schema create 权限。该观察接口是原生
Supervisor 投影边界，不复用旧 Java `RuntimeExecutionSnapshot` 的较窄状态枚举。

## Supervisor Run controller（默认关闭）

`POST /internal/v1/runtime-supervisor/run-cancellations/request` 只负责把 Java
业务控制面已授权的取消意图写成 durable `runtime_run_control` 与 Run 事件。它要求
exact-single scope `runtime.run.cancel`；请求体携带业务 actor、稳定 cancel request ID、
Run version、幂等键和请求哈希，但不接受 `eventPayload`。事件载荷由 Runtime 固定生成，
避免调用方自选审计事实。响应只有 `outcome: APPLIED|NOT_APPLIED`；它不表示取消已
完成，后续仍由持有当前 fence 的 Supervisor worker 执行本地 quiesce、外部 operation
barrier 检查并收敛为 `CANCELLED` 或 `CANCEL_OUTCOME_UNKNOWN`。

路由默认不注册，也不接入公开任务 API。启用前必须应用 migration `015`，为
runtime-api 注入只继承 `dianlian_supervisor_controller` 的独立登录 DSN；不得复用
worker executor、permit、dispatch 或 outcome DSN：

```bash
DIANLIAN_RUN_CONTROLLER_ENABLED=true \
DIANLIAN_RUN_CONTROLLER_DATABASE_DSN='<injected-controller-dsn>' \
DIANLIAN_RUN_CONTROLLER_DATABASE_CONNECT_TIMEOUT_SECONDS=5 \
DIANLIAN_RUN_CONTROLLER_DATABASE_STATEMENT_TIMEOUT_SECONDS=5 \
DIANLIAN_RUN_CONTROLLER_DATABASE_LOCK_TIMEOUT_SECONDS=5 \
DIANLIAN_SERVICE_JWT_PUBLIC_KEY_RING_JSON='{"<kid>":"/absolute/path/to/public-key.pem"}' \
uv run uvicorn dianlian_runtime.app:create_app --factory --host 127.0.0.1 --port 8091
```

readiness 会要求该登录只能执行 `request_runtime_run_cancel`，不能拥有其它
`deer_runtime` 函数、表、列、序列或 schema create 权限。migration `015` 同时从
通用 executor 收回该函数，避免 worker DSN 被复用成外部控制通道。

## 隔离上传检查服务（默认关闭）

上传检查使用独立 FastAPI 进程和 `upload.inspect` 单一 Service JWT scope。它只接受
Java 签发的精确对象版本短时 HTTPS 读取能力，不接收对象键、OSS 凭据或浏览器令牌；
下载后会重算长度与 SHA-256、识别允许媒体类型，并通过 clamd 原生 `VERSION` 和
`INSTREAM` 协议完成恶意内容扫描。Tika/Docling 不能替代此安全检查。

服务与 clamd 均默认关闭。目标环境必须显式提供允许的对象存储读取 Host、独立 clamd
地址和内部服务公钥环；签名 URL 不得写入日志：

```bash
DIANLIAN_UPLOAD_INSPECTION_SERVICE_ENABLED=true \
DIANLIAN_UPLOAD_INSPECTION_ALLOWED_SOURCE_HOSTS='objects.example.com' \
DIANLIAN_UPLOAD_INSPECTION_CLAMD_HOST='clamd.internal' \
DIANLIAN_UPLOAD_INSPECTION_CLAMD_PORT=3310 \
DIANLIAN_SERVICE_JWT_PUBLIC_KEY_RING_JSON='{"<kid>":"/absolute/path/to/public-key.pem"}' \
uv run uvicorn dianlian_runtime.upload_inspection.app:create_upload_inspection_app \
  --factory --host 127.0.0.1 --port 8093
```

仓库不固定或部署任何 ClamAV 容器镜像；真实病毒库更新、网络隔离、EICAR、对象存储
精确版本和 TLS 验收仍是目标环境的开门条件。

## 隔离内容规范化服务（默认关闭）

`POST /internal/v1/content/normalize` 是独立 FastAPI 进程，只接受
`content.normalize` 单一 Service JWT scope。Java 为已验证的精确对象版本签发短时
HTTPS GET 能力；Python 不接对象键或对象存储凭据，下载后重新校验长度与 SHA-256，
再把临时文件交给部署时明确选择的单一 Docling 或 Tika 服务。两侧都不做 AUTO 猜测、
引擎 fallback 或内联重试，错误响应正文与签名 URL 不进入日志。

目标环境需要单独部署并固定 Docling Serve 或 Tika Server 的镜像与版本。本仓库只
提供防腐 HTTP Wrapper，不把第三方解析器打包进 Runtime，也不把 Tika 当作病毒扫描器：

```bash
DIANLIAN_CONTENT_NORMALIZATION_SERVICE_ENABLED=true \
DIANLIAN_CONTENT_NORMALIZATION_SERVICE_ENGINE=DOCLING \
DIANLIAN_CONTENT_NORMALIZATION_ALLOWED_SOURCE_HOSTS='objects.example.com' \
DIANLIAN_CONTENT_NORMALIZATION_PARSER_BASE_URL='https://docling.internal' \
DIANLIAN_CONTENT_NORMALIZATION_PARSER_API_KEY='<optional-secret>' \
DIANLIAN_SERVICE_JWT_PUBLIC_KEY_RING_JSON='{"<kid>":"/absolute/path/to/public-key.pem"}' \
uv run uvicorn dianlian_runtime.content_normalization.app:create_content_normalization_app \
  --factory --host 127.0.0.1 --port 8092
```

使用 Tika 时把 engine 改为 `TIKA` 并指向独立 Tika Server。仅本地开发可显式允许
loopback HTTP；其它地址必须使用 HTTPS。当前基础合同只返回有序 `TEXT` 分段，不宣称
已经冻结页码、表格坐标或图片区域等富定位信息。

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
uv run pytest -q tests/test_retrieval.py tests/test_indexing.py tests/test_migrations.py
```

可选真实 PostgreSQL 测试必须使用专用测试库：

```bash
DIANLIAN_TEST_CONTEXT_DATABASE_DSN='<dedicated-test-dsn>' \
uv run pytest -q tests/test_postgres_context.py
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
