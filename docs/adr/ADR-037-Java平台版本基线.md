# ADR-037：Java 平台版本基线

- 状态：已接受
- 日期：2026-08-11
- 决策范围：`dianlian-platform`

## 背景

点联 V1 需要先建立多租户、会话、任务、成果、审批、智点和 SSE 的业务控制面。当前仓库尚未建立 Java 工程，若不先固定 JDK、Spring Boot 与 Spring Modulith 版本，模块拆分、依赖管理、测试基线和后续 Java/Python 契约会产生不必要差异。

## 决策

1. Java 运行和编译基线固定为 Java 21 LTS。
2. Spring Boot 固定为 `3.5.16`。
3. Spring Modulith 固定为 `1.4.12`。
4. 使用 Maven 多模块与统一 BOM/Dependency Management 管理版本，子模块不得自行覆盖 Spring Framework、Jackson、Tomcat、Micrometer 等 Boot 管理依赖。
5. 首期采用 Spring Boot 模块化单体；Spring Modulith 用于模块边界验证、模块测试和内部领域事件，不把它当分布式消息或工作流引擎。
6. V1 不因 Java 调用 Python 引入完整 Spring Cloud。HTTP/JSON、SSE、持久 Outbox/Inbox、有界资源池、超时、限流、熔断和 OpenTelemetry 先作为服务治理基线。
7. 数据库迁移、OpenAPI 生成、测试插件和构建镜像必须使用 Java 21；禁止本地可运行但 CI/生产使用其他主版本。

## 影响

- 后端骨架可以围绕身份租户、员工、交互、任务、成果、计费等 Modulith 模块建立清晰边界。
- 升级 Spring Boot 或 Spring Modulith 属于架构基线变更，必须单独 ADR，并验证模块测试、数据库迁移、序列化、SSE 和安全配置。
- 该决策不冻结具体 ORM、鉴权框架、数据库连接池和 HTTP 客户端；它们需在对应实现或 ADR 中确定。

## 验证门槛

- Maven Enforcer 拒绝低于 Java 21 的运行环境和不一致的依赖版本。
- Spring Modulith 模块结构测试通过，无未声明的跨模块内部包依赖。
- 最小应用能启动，并完成 PostgreSQL、统一 ProblemDetail、OpenAPI 和 SSE 的契约冒烟。

