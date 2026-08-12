[English](README.md) | **简体中文**

# Enterprise Agent Platform

一个面向企业数字员工与 AI Agent 协作场景的早期参考实现。项目内部当前使用“点联”作为产品代号。

> [!WARNING]
> 本项目处于早期开发阶段，仅用于本地研究、架构验证和社区协作，尚未经过生产环境安全加固或兼容性承诺。请勿直接用于生产或处理敏感数据。

当前仓库包含三类不同性质的工程资产：

- `dianlian-web/`：已完成的高保真前端原型，正在通过 API adapter 逐步接入真实服务。
- `dianlian-platform/`：Java 21 + Spring Boot + Spring Modulith 业务主系统。
- `dianlian-ai-runtime/`：Python AI Runtime 防腐层；LlamaIndex 与 DeerFlow 只有在对应能力通过门禁后才启用。
- `contracts/`：Java、Python 和 Web 共用的版本化接口与事件契约。
- `deploy/local/`：仅用于本地开发的依赖编排，不包含线上配置。

## 当前开发边界

第一批研发先建立可启动、可观测、失败关闭的工程内核，不伪造模型、知识检索或长任务成功：

1. Java 是租户、权限、任务、成果、审批和智点的业务真相。
2. Python 只通过版本化内部 HTTP/SSE 契约接入，默认功能关闭。
3. 前端 API 模式失败时不得静默回退演示数据。
4. 小节点只运行编译、契约和高风险规则的最小验证；完整跨端回归在阶段闭环后统一执行。

## 本地依赖

- Java 21
- Maven 3.8.6+
- Python 3.12 与 `uv`
- Node.js 22+
- Docker Desktop（本地 PostgreSQL/pgvector）

所有密钥和密码必须通过环境变量或本地 `.env` 注入；仓库只保留 `.env.example` 占位说明。

## 本地 PostgreSQL

```bash
cp deploy/local/.env.example deploy/local/.env
docker compose --env-file deploy/local/.env -f deploy/local/compose.yaml up -d postgres
```

示例文件中的密码必须在本机修改，不能用于共享或线上环境。

本地体验账号、三位数字员工、智点账本与幂等校验见
[`deploy/local/README.md`](deploy/local/README.md)。本地平台角色包含官方模板和模型管理权限；企业角色包含员工管理、任务与内部会话权限。

## Java 主服务

应用只接受环境变量中的数据库、JWT 与模型密钥。模型管理页面保存的是
`env:DIANLIAN_MODEL_*` 引用，不保存真实 Key；`DIANLIAN_MODEL_ALLOWED_HOSTS`
必须填写实际 Provider 域名的精确白名单。

```bash
set -a
source deploy/local/.env
set +a
export DIANLIAN_DB_URL="jdbc:postgresql://127.0.0.1:${DIANLIAN_POSTGRES_PORT}/$DIANLIAN_POSTGRES_DB"
export DIANLIAN_DB_USERNAME="$DIANLIAN_POSTGRES_USER"
export DIANLIAN_DB_PASSWORD="$DIANLIAN_POSTGRES_PASSWORD"
env JAVA_HOME=/opt/homebrew/opt/openjdk@21 mvn -f dianlian-platform/pom.xml \
  -pl dianlian-bootstrap -am -DskipTests package
env JAVA_HOME=/opt/homebrew/opt/openjdk@21 java \
  -jar dianlian-platform/dianlian-bootstrap/target/dianlian-bootstrap-0.1.0-SNAPSHOT.jar \
  --spring.profiles.active=local
```

模型定义和默认路由配置完成后，再在本地 `.env` 中显式开启对应 Worker：

```dotenv
DIANLIAN_INTERACTION_WORKER_ENABLED=true
DIANLIAN_TASK_WORKER_ENABLED=true
```

对话 Worker 处理真人触发的数字员工回复；任务 Worker 当前只执行明确标记为
`MODEL` 的步骤。未接入的 `TOOL / RETRIEVAL / RULE_ENGINE` 步骤会安全停在等待状态，不会伪造完成。

## Web API 模式

```bash
cd dianlian-web
env VITE_DATA_SOURCE=api \
  DIANLIAN_DEV_API_TARGET=http://127.0.0.1:8080 \
  npm run dev
```

API 模式失败时不会回退演示数据。员工端、企业管理中心与平台运营中心使用彼此独立的信息架构。

## Python Runtime

```bash
cd dianlian-ai-runtime
uv sync --dev
uv run uvicorn dianlian_runtime.app:create_app --factory --host 127.0.0.1 --port 8091
```

健康检查：

```bash
curl -s http://127.0.0.1:8091/internal/v1/health/liveness
curl -s http://127.0.0.1:8091/internal/v1/health/readiness
curl -s http://127.0.0.1:8091/internal/v1/runtime/status
```

## 开源协作

- 提交改动前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。
- 安全问题请按 [SECURITY.md](SECURITY.md) 私下报告，不要直接公开利用细节。
- 当前版本按 [MIT License](LICENSE) 开源。
