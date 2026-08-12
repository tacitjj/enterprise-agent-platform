# ADR-042：DeerFlow Gateway 运行内核通过防腐层接入

- 状态：PoC 候选已冻结，生产准入未通过
- 日期：2026-08-12
- 决策范围：复杂长任务 Python Harness 与 Run Supervisor

## 背景

点联需要为复杂长任务提供持久 Run、Checkpoint、暂停与取消、Worker 所有权、接管、事件重放、子 Agent 和受控 Sandbox。DeerFlow 的进程内 Client 可以驱动 Agent Graph，但不能单独承担跨实例 Run 生命周期。完整 DeerFlow App 又包含点联不需要的用户、页面、线程和产品入口，直接复用会形成第二套业务真相。

## 决策

1. 复杂长任务选择复用并锁定 DeerFlow Gateway Runtime Kernel，通过点联 `dianlian_deer_runtime` 防腐层接入；不部署完整 DeerFlow App 作为点联入口。
2. Java 继续拥有租户、权限、业务 Task/Run 映射、智点、审批、成果、工具副作用和面向用户的 SSE 真相。Python 只拥有引擎执行尝试、lease、Checkpoint、原始运行事件、Subagent 与 Sandbox 生命周期。
3. 点联业务代码只依赖自己的 `AgentRuntime` 契约。所有 DeerFlow import、DTO、配置和上游表访问集中在一个适配模块；不得让 Java 或其他 Python 模块直接依赖上游内部类型。
4. DeerFlow 长期记忆固定关闭：`enabled=false`、`injection_enabled=false`、`manager_class=noop`。点联按 `AGENT / USER_AGENT / GROUP_AGENT` 权威范围注入当前 Run 的短期 ContextBundle；DeerFlow Checkpoint 不等于企业长期记忆。
5. PoC 候选提交记录在 `dianlian-ai-runtime/upstream/deerflow.lock.json`。候选提交、Python 3.12、上游 `backend/uv.lock` 和点联 Adapter 版本必须作为一个制品集合验证和发布。
6. 当前锁定只表示可复现审查基线，不表示已安装或生产可用。未通过兼容、接管、取消竞争、重放缺口、作用域隔离、Sandbox、用量和成果幂等门禁前，`productionApproved` 必须保持 `false`，能力路由继续失败关闭或回退可由 LangChain4j 承载的路径。

## 接入边界

点联 Harness Port 最少提供：

```text
start_execution(request, idempotency_key)
stream_events(execution_id, after_sequence)
guide(execution_id, expected_checkpoint_id, guidance)
cancel(execution_id, action)
get_execution(execution_id)
```

运行映射固定为：

```text
Java task_step + task_execution_generation
    -> Python runtime_thread + runtime_run
    -> DeerFlow Thread / Run / Checkpoint
```

DeerFlow Subagent 只能服务当前数字员工步骤，继承同一不可扩大的租户、员工、个人或群聊授权范围；它不能创建企业数字员工、扩大知识范围、改变预算归属或绕过 Java Tool Gateway。

## 生产门禁

- 同一幂等键只产生一个 execution。
- 同一 Thread 同时只有一个 Active Operation。
- lease 接管后旧 Worker 的 Checkpoint、事件、工具、成果和终态提交全部被拒绝。
- cancel 与 complete 竞争只有一个权威终态；未知外部副作用进入对账阻断。
- 持久事件按序重放；游标过期返回明确 Replay Gap 并回源快照。
- 个人、群聊和数字员工上下文零串扰；Subagent 无法扩大 scope。
- DeerFlow Memory 关闭后没有读取、写入或提示词注入。
- 回调重试不重复扣智点、创建成果或执行外部写工具。
- 生产 Sandbox 与宿主机隔离，不开放本地 Bash 作为安全边界。

## 影响

- 不再选择“点联自建完整 Supervisor + 仅嵌入 DeerFlowClient”作为 V1 主路径，避免重复实现 Gateway 已有的 Run ownership、takeover、cancel 和 replay 内核。
- 上游 Runtime Kernel 属于固定提交上的内部依赖，不假定其 API 稳定；升级只能通过锁定测试后进行。
- 本 ADR 不提前启用 DeerFlow，也不阻塞知识、记忆和 LlamaIndex 主线。
