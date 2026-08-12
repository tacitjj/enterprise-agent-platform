# ADR-038：LangChain4j 按短任务 Golden Slice 引入

- 状态：已接受
- 日期：2026-08-11
- 决策范围：Java AI 运行时与首条业务切片

## 背景

点联 M0 首先要冻结租户权限、任务状态、成果版本、智点、错误、幂等和 SSE 契约。若在工程骨架阶段就引入模型框架，容易让厂商 DTO、流式回调或 Tool Call 类型反向污染业务模型，也无法证明这些依赖已经服务于一条真实业务链。

## 决策

1. Java 工程骨架阶段不引入 LangChain4j 依赖。
2. 先实现点联自有的 `AgentRuntimePort`、`ModelGateway`、任务/步骤、用量、智点、Artifact 和事件契约；端口不得暴露 LangChain4j 或模型厂商类型。
3. LangChain4j 在首条“内部群聊明确选择单一数字员工，完成短任务阶段成果并按实际用量结算”的 Golden Slice 中引入。
4. 首个适配器只承担普通对话、简单生成、结构化提取和单步工具调用；它不承担跨小时任务、长期审批、持久 Run Supervisor 或企业数字员工之间的协作真相。
5. Golden Slice 联调前允许使用确定性 Fake Runtime 做状态机、幂等、费用和 SSE 契约测试；最终阶段验收必须增加至少一次真实模型沙箱调用，并保留 Provider Attempt 与标准化 Usage。
6. LlamaIndex 继续作为后续知识/记忆上下文模块；DeerFlow Harness 继续受独立生产准入 PoC 约束。二者不因 LangChain4j 延后而改变业务契约。

## 影响

- M0 可以在不依赖模型可用性的情况下完成业务控制面和契约测试。
- LangChain4j 的版本、模型适配器和流式行为在短任务切片开始前另行冻结；本 ADR 不提前指定其具体版本。
- 替换 Java AI 框架时只需替换适配器，Task、Artifact、Usage、Point 和 SSE 语义保持不变。

## Golden Slice 准入

引入 LangChain4j 前必须具备：

- 同键同哈希只创建一个 Task 和一次收费意图。
- 智点预占成功后才允许调用模型；余额不足时 Provider 请求数为 0。
- Task、TaskStep、ArtifactVersion 和智点结算可以在无模型情况下完成契约测试。
- SSE 重放、ETag 与 ProblemDetail 契约已经冻结。

