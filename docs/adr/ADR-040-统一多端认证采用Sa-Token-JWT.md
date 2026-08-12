# ADR-040：统一多端认证采用 Sa-Token JWT

## 状态

已接受。

## 决策

点联公共 API 使用 Sa-Token 作为唯一登录认证框架，Access Token 统一为 JWT。Web、App、小程序和桌面端均使用：

```http
Authorization: Bearer <JWT>
```

采用 Sa-Token JWT Simple 模式与 Redis 会话状态结合，而不是纯无状态 JWT：

- JWT 承载短期 Access Token 和稳定的会话 ID；
- Redis 管理 Token 状态、设备会话、注销、踢下线和并发登录；
- PostgreSQL 保存用户、企业成员关系、角色授予、权限版本、登录会话和审计事实；
- 每次请求仍按 JWT 中的会话 ID 回源校验 PostgreSQL 权威会话，且 JWT 登录主体必须与会话用户一致；
- `AccessContext` 继续负责租户、资源范围和领域权限，Sa-Token 不替代数据权限。

Spring Security 不再作为登录认证链，避免同一应用维护两套安全上下文。业务模块不得直接依赖 Sa-Token 类型；Sa-Token 仅出现在启动适配层。

## 客户端约束

- Access Token 只通过 Authorization Header 发送，不放入 URL、请求体或租户头。
- Web 端 Access Token 只保存在内存；页面恢复由后续 Refresh Token 轮换接口完成。
- Refresh Token 不暴露给业务 JavaScript，Web 使用 HttpOnly Cookie，原生端使用系统安全存储。
- Refresh Token 是高熵随机值而不是第二套登录身份；服务端只保存 SHA-256 摘要，成功刷新后单次轮换，检测到旧 Token 重放时撤销整个设备会话。
- 业务写请求继续使用 `Idempotency-Key`；Bearer Header 模式不再要求业务接口携带 CSRF Token。
- SSE 使用支持自定义 Header 的 Fetch 流式客户端，禁止把 Access Token 放到查询参数。

## 配置与运行

- Sa-Token 版本固定为 `1.45.0`，仅显式管理 Sa-Token 自身依赖，不导入其整包 BOM。
- JWT 签名密钥只通过安全配置源注入，仓库与默认配置不提供可运行密钥。
- Redis 与 PostgreSQL 均属于认证准入依赖；任一不可用时新请求失败关闭。
- Access Token 默认 15 分钟，Refresh Token 默认 30 天且不滑动延长；两者由 identity 的统一有效期策略配置，Sa-Token 不另行定义业务有效期。
- 短期 JWT 关闭 Sa-Token 的额外闲置超时和自动续签，避免 SSE 或后台页面在绝对有效期内被另一套计时提前终止。
- 企业账号密码作为 V1 首个身份校验适配器，密码只保存 BCrypt 哈希；连续失败达到阈值后临时锁定，但对外始终返回相同的账号或密码错误，避免账号枚举。
- `web_session` 是设备会话事实，记录客户端类型与可选设备标识；JWT 失效、数据库撤权、Refresh 重放任一发生都不能绕过 PostgreSQL 会话校验。

## 扩展边界

短信、企业 SSO 等登录方式作为可插拔身份校验入口；它们完成身份校验后统一进入同一个 Token 签发、刷新、注销和设备会话流程，不各自定义 Token。租户切换、设备列表和全设备下线继续建立在同一 `web_session` 模型上，不新增平行认证体系。
