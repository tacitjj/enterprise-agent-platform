# Prototype Instructions

Run the local server yourself and open the preview in the browser available to this environment. Do not give the user server-start instructions when you can run it.

Before making substantial visual changes, use the Product Design plugin's `get-context` skill when the visual source is unclear or no longer matches the current goal. When the user gives durable prototype-specific design feedback, preferences, or decisions, record them in `AGENTS.md`.

When implementing from a selected generated mock, treat that image as the source of truth for layout, component anatomy, density, spacing, color, typography, visible content, and hierarchy.

Build app UI in `src/`. Keep `.openai/hosting.json`, `worker/index.js`, `scripts/prepare-sites-build.mjs`, and `tests/sites-worker.test.mjs` intact so the same local prototype can be handed to Sites. Before a Sites handoff, run `npm run build` and `npm run test:sites`; the build must leave `dist/client/index.html`, `dist/server/index.js`, and `dist/.openai/hosting.json`.

## 点联 V1 原型约束

- 用户端必须先展示企业数字员工，再由用户选择员工开始工作；快捷输入没有明确员工时不得直接触发任务。
- 前端页面的主视觉与主交互基线是 `/Users/jinyingxin/Documents/EVENT数字员工`：先继承其中已有的页面结构、导航、空间关系、卡片、抽屉、信息密度和交互，再在同一视觉语言中补充 EVENT 尚未覆盖的生产能力。不得再以当前点联旧 UI 或 `docs/design/concepts/` 概念稿覆盖 EVENT；概念稿只可用于 EVENT 缺失且已确认的新增区域。
- EVENT 只提供产品表现基线，不复用其固定员工、固定房间、演示身份、恢复数据、假进度和本地存储业务事实；真实接口、权限、配置版本、启用门禁、任务、费用、审批与审计仍以点联服务端契约为准。
- 首批能力固定为平面出图、法务合同审核、报价；知识与记忆是三类员工的共用底座，不单独占员工工位。
- 任务进度使用步骤、负责人、运行事件、成果和智点事实表达，不使用随机百分比或假进度。
- 企业普通员工与企业管理员共用同一企业登录、活动租户和 EVENT 风格工作平台；管理员仅按服务端权限增加受限管理入口。点联平台运营后台使用独立平台路由壳与权限上下文，平台角色默认不可见企业正文、图片、提示词、报价成本和私人记忆。
- 企业管理后台沿用点联企业管理中心参考稿的高密度白底数据工作台：左侧分组导航、顶部企业与管理员上下文、概览指标、运行状态、待办、知识记忆、智点费用和异常恢复。它是 EVENT 员工工作台内管理员可进入的独立后台，不得把平台运营能力混入企业后台。
- 平台运营后台沿用点联平台经营总览参考稿的高密度运营驾驶舱：租户、官方员工模板、行业知识、模型与 Provider、费率倍率、智点账本、成本对账、运行监控及安全审计。不得从企业管理页复制企业知识正文、私人记忆或业务内容到平台视图。
- “消息”统一承载真人与真人、真人与数字员工的直接会话和群聊。每次 AI 回复都必须绑定具体企业数字员工、岗位版本、企业配置版本、模型路由、授权知识范围及 `USER_AGENT` 或 `GROUP_AGENT` 记忆作用域；群聊普通消息未明确选择、@ 或回复数字员工时不得调用模型或扣智点。
- 小节点只做构建、受影响页面冒烟和高风险规则定向检查；跨端主链与视觉回归在完整页面阶段统一验收。
