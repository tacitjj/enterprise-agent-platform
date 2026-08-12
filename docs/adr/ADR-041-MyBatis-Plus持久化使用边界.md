# ADR-041：MyBatis-Plus 持久化使用边界

- 状态：已接受
- 适用版本：点联 V1

## 决策

采用 MyBatis-Plus 3.5.17 的 Spring Boot 3 Starter，作为模型目录、平台/企业后台配置、字典与普通分页查询的持久化工具。当前 Java 21、Spring Boot 3.5.x 与 PostgreSQL 基线保持不变。

MyBatis-Plus 不替代领域事务设计。以下路径继续保留显式 SQL/JDBC Repository，除非有等价的事务与并发证明后再逐个迁移：

- 智点账户、批次、预占、捕获、释放和不可变账本；
- 员工配置版本、激活 CAS、状态事件；
- 会话消息序号、成员撤权 fencing、AI Invocation lease；
- Task/Run、Outbox/Inbox、发布幂等和跨表一致性写入。

V1 不启用 MyBatis-Plus 多租户插件作为安全边界。租户、成员、数据范围和资源权限仍由服务端 `AccessContext`、业务查询条件、数据库约束及安全测试共同保证；拦截器只能作为防误用的补充。

## SQL 日志

本地 profile 使用 MyBatis 的 SLF4J 实现，并只对明确的 mapper 包开启 DEBUG。生产默认不打印 SQL 参数，不接入 p6spy；会话正文、企业提示词、合同、报价明细、知识片段、记忆和凭据引用不得进入普通 SQL 日志。

## 迁移方式

新增的简单 CRUD 可直接使用 MyBatis-Plus。已有 JDBC Repository 不做一次性重写；每次迁移只处理一个有测试覆盖的低风险读写面，并保留数据库约束、幂等语义、行锁/CAS 与错误映射。
