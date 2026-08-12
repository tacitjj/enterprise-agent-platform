# 点联本地开发环境

`deploy/local` 只用于本地开发。生产迁移保持纯结构，体验账号、数字员工、智点与登录会话事实由这里的夹具提供。

## Golden Slice 夹具

夹具包含：

- 一个无租户的平台用户及平台模板发布权限；
- 一个 ACTIVE 企业、企业用户、成员关系及招聘/查看/配置/启用/执行权限；
- `GRAPHIC_DESIGN`、`CONTRACT_REVIEW`、`QUOTATION` 三个已发布模板版本；
- 三位已招聘的 ACTIVE 企业数字员工；每位员工绑定一个 ACTIVE 企业配置版本，包含非空企业指令、V1 模型/知识/可见范围模式，以及从招聘、创建配置到启用的完整状态审计；
- 一个含 100000 智点的企业主账户、可预占 lot 与平衡的初始发放账本；账务表内部按 `1 智点 = 1000000 micro_credit` 存储；
- 两个由本次运行提供用户名和 BCrypt 哈希的本地登录凭据，分别用于平台端和企业端；设备会话必须通过真实登录接口创建。

固定 UUID 是本地夹具的稳定业务标识，不是口令。原始 session token 与数据库连接信息不会写入 SQL，也不会由脚本输出。

## 使用方式

1. 复制 `.env.example` 为不入库的 `.env`，设置本地 PostgreSQL 密码与 JWT 签名密钥，然后启动 PostgreSQL 和 Redis：

   ```bash
   docker compose --env-file deploy/local/.env -f deploy/local/compose.yaml up -d postgres redis
   ```

2. 先通过应用 Flyway 或在一座全新的临时数据库中按顺序执行生产 `V1`～`V12` 迁移。seed 会主动依赖这些结构，不会代替 Flyway 重放迁移。

3. 在当前终端提供数据库 URL、企业/平台登录用户名和本地 BCrypt 哈希。生成脚本通过隐藏输入读取密码，只输出哈希：

   ```bash
   export DIANLIAN_DATABASE_URL='postgresql://dianlian_app:<local-password>@127.0.0.1:55432/dianlian'
   export DIANLIAN_LOCAL_USERNAME='dianlian-local'
   export DIANLIAN_LOCAL_PASSWORD_HASH="$(deploy/local/scripts/security/generate-password-hash.sh)"
   export DIANLIAN_LOCAL_PLATFORM_USERNAME='dianlian-platform-local'
   export DIANLIAN_LOCAL_PLATFORM_PASSWORD_HASH="$(deploy/local/scripts/security/generate-password-hash.sh)"
   deploy/local/scripts/seed/seed-golden-slice.sh
   unset DIANLIAN_LOCAL_USERNAME DIANLIAN_LOCAL_PASSWORD_HASH \
     DIANLIAN_LOCAL_PLATFORM_USERNAME DIANLIAN_LOCAL_PLATFORM_PASSWORD_HASH \
     DIANLIAN_DATABASE_URL
   ```

脚本只向 `psql` 传递用户名和 BCrypt 哈希。它先提交幂等 seed，再在独立事务内模拟一次报价任务的智点预占、计划、步骤、参与者、轨迹、outbox 与查询，验证完成后回滚 smoke 任务。

重复执行不会增加员工配置版本或状态审计，也不会推进员工 `state_version`、更新已发布员工版本或改写已入账分录。若本地业务测试已消耗到不足 600 智点，验证会明确失败；请换用全新临时数据库或显式追加一笔合规调账，而不是篡改已有账本。

## 本地登录夹具标识

- 企业 ID：`10000000-0000-4000-8000-000000000001`
- 平台用户 ID：`10000000-0000-4000-8000-000000000010`
- 企业用户 ID：`10000000-0000-4000-8000-000000000011`
- 平面设计员工 ID：`10000000-0000-4000-8000-000000000121`
- 合同审核员工 ID：`10000000-0000-4000-8000-000000000122`
- 报价员工 ID：`10000000-0000-4000-8000-000000000123`

浏览器和其他客户端统一使用 `Authorization: Bearer <JWT>`。JWT 和 Refresh Token 必须由认证服务在身份校验通过后签发；本地 seed 脚本不预建会话，也不会输出 Token。
