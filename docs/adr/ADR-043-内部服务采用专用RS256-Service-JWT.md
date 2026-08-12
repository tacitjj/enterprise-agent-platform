# ADR-043：内部服务采用专用 RS256 Service JWT

## 状态

已接受。

## 背景

Java 平台需要调用 Python AI Runtime 的内部上下文索引与检索接口。公共 API
现有 Sa-Token JWT Simple 是用户登录凭证，使用 `DIANLIAN_JWT_SECRET` 并绑定
用户会话。Python 不能持有该用户签名密钥，内部调用也不能把用户 Access Token
当作服务身份。

## 决策

内部 Java → Python 调用使用一套独立的 RS256 Service JWT：

- 签发方固定为 `dianlian-platform`；
- 受众固定为 `dianlian-ai-runtime`；
- subject 固定为 `dianlian-platform`，并要求 `token_use=service`；
- JOSE Header 必须为 `alg=RS256`、`typ=JWT`，且携带非空 `kid`；
- Claims 必须包含 `iss / sub / aud / iat / exp / jti / token_use / scope`；
- Token TTL 默认 30 秒且不得超过 60 秒；Python 时钟偏差默认 5 秒且不得超过
  10 秒；
- `scope` 使用空格分隔，V1 只允许 `context.index.write` 与
  `context.retrieve`；
- 索引接口只接受 `context.index.write`，检索接口只接受 `context.retrieve`。

Java 使用 Nimbus JOSE + JWT `10.9.1` 签名，并使用其兼容的 Bouncy Castle
`bcpkix-jdk18on 1.81`、`bcutil/bcprov 1.81.1` 解析部署 PEM；Python 使用
`PyJWT[crypto]==2.13.0` 验签。算法白名单固定为 RS256，不根据 Token Header
动态选择算法，不混用 HMAC 与 RSA 密钥。

## 密钥与配置

Java 只从部署配置引用 PKCS#8/PKCS#1 RSA 私钥 PEM 文件：

- `DIANLIAN_SERVICE_JWT_ENABLED`，默认 `false`；
- `DIANLIAN_SERVICE_JWT_KEY_ID`；
- `DIANLIAN_SERVICE_JWT_PRIVATE_KEY_PATH`；
- `DIANLIAN_SERVICE_JWT_TTL_SECONDS`，默认 30，最大 60。

Python 使用 `DIANLIAN_SERVICE_JWT_PUBLIC_KEY_RING_JSON` 注入静态公钥环。它是
`kid -> 绝对 PEM 文件路径` 的 JSON 对象，可同时包含当前和上一把公钥。
`DIANLIAN_SERVICE_JWT_CLOCK_SKEW_SECONDS` 默认 5，最大 10。

私钥、公钥内容和真实路径值不进入仓库、数据库、接口响应或日志。示例配置只保留
空值或占位说明。严禁复用 `DIANLIAN_JWT_SECRET`。

RSA 密钥不得少于 2048 位。Java 启用签发能力但缺少 `kid`、私钥路径或私钥无效时
启动失败。Python 缺少或无法加载公钥环时保持存活探针可用，但就绪探针返回
`OUT_OF_SERVICE`，所有受保护接口返回 503，不允许降级为匿名访问。

## 双钥轮换

1. 先在 Python 公钥环加入新 `kid`，保留旧公钥并完成就绪验证；
2. 再把 Java 的当前 `kid` 与私钥路径切到新钥；
3. 等待旧 Token 的最大 TTL 加最大时钟偏差，即至少 70 秒；
4. 确认没有旧 `kid` 请求后，从 Python 公钥环移除旧公钥。

Python 对未知 `kid` 失败关闭，不尝试无 `kid` 回退或逐钥碰撞验签。

## 验证与拒绝规则

Python 必须同时验证签名、固定算法、issuer、唯一目标 audience、subject、token_use、
`iat / exp / jti`、最大 TTL 与目标 Scope。以下情况统一拒绝，不向调用方暴露验签
细节：

- 用户 Token、HMAC Token 或非 RS256 Token；
- 缺少、未知或格式非法的 `kid`；
- issuer、audience、subject 或 token_use 不匹配；
- 缺少目标 Scope，或包含未定义 Scope；
- Token 过期、签发时间超前、TTL 超过 60 秒或 jti 非法；
- 公钥环未配置、文件不可读或密钥强度不足。

认证失败返回 401，Token 有效但 Scope 不足返回 403，服务端验签配置不可用返回
503。错误响应不得包含 Token、密钥、PEM 内容或具体签名失败细节。

## 边界

本 ADR 只定义服务身份。租户、员工、知识、记忆、群聊历史和业务权限仍由 Java
计算并通过严格业务契约下发，Service JWT 不替代业务授权。后续 Run Admission、
Execution Token 或工具网关令牌需要独立 ADR，不复用本 Context Scope。
