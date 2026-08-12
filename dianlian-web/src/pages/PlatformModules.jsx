import { useEffect, useMemo, useState } from "react";
import {
  IconActivity,
  IconAdjustments,
  IconAlertTriangle,
  IconArrowsExchange,
  IconBook,
  IconBuilding,
  IconCheck,
  IconChecklist,
  IconChevronRight,
  IconCircleCheck,
  IconCpu,
  IconDatabase,
  IconDeviceDesktopAnalytics,
  IconFileText,
  IconLink,
  IconLock,
  IconPlus,
  IconRefresh,
  IconSearch,
  IconShieldCheck,
  IconTag,
  IconTools,
  IconUserShield,
  IconWallet,
  IconX,
} from "@tabler/icons-react";
import "./platform-modules.css";

export const PLATFORM_MODULE_KEYS = Object.freeze([
  "tenants",
  "agent-templates",
  "skills",
  "industry-knowledge",
  "providers",
  "models",
  "rates",
  "multipliers",
  "points",
  "usage",
  "monitoring",
  "audit",
]);

const MODULE_META = {
  tenants: {
    title: "租户运营",
    description: "管理企业开通、套餐、管理员、能力权益与停用影响，平台人员默认不可读取企业私有内容。",
    scope: "租户元数据、套餐权益、账户摘要与操作审计",
    action: "开通租户",
    actionKind: "tenant-create",
    icon: IconBuilding,
  },
  "agent-templates": {
    title: "官方模板",
    description: "维护数字员工模板、不可变版本、岗位验收集与租户灰度，发布不会静默改变企业实例。",
    scope: "平台模板、版本依赖、验收结果与发布策略",
    action: "创建模板草稿",
    actionKind: "template-create",
    icon: IconFileText,
  },
  skills: {
    title: "技能中心",
    description: "管理平台受控技能的 Schema、工具依赖、安全审核、灰度和回滚，不开放任意代码上传。",
    scope: "技能定义、版本、签名、风险与调用摘要",
    action: "注册技能版本",
    actionKind: "skill-register",
    icon: IconTools,
  },
  "industry-knowledge": {
    title: "行业知识",
    description: "发布可复用的行业知识模板和检索策略，与企业私有文档保持物理及权限隔离。",
    scope: "行业模板、样例数据、评估结果与派生映射",
    action: "创建知识模板",
    actionKind: "knowledge-create",
    icon: IconBook,
  },
  providers: {
    title: "Provider 治理",
    description: "治理外部能力、区域、凭证引用、健康检查、限流和熔断，凭证正文永不回显。",
    scope: "Provider 元数据、健康、授权范围与故障记录",
    action: "接入 Provider",
    actionKind: "provider-connect",
    icon: IconLink,
  },
  models: {
    title: "官方模型",
    description: "以稳定模型标识屏蔽供应商差异，统一管理模态、上下文、路由、主备兼容与 Provider Attempt。",
    scope: "官方模型、供应商型号、路由与健康指标",
    action: "登记官方模型",
    actionKind: "model-register",
    icon: IconCpu,
  },
  rates: {
    title: "供应商费率",
    description: "按计量项管理供应商成本费率、币种、税口径和生效区间；历史 Attempt 永远引用原费率快照。",
    scope: "Provider Rate、汇率、税口径与审批记录",
    action: "新建费率版本",
    actionKind: "rate-create",
    icon: IconTag,
  },
  multipliers: {
    title: "企业销售价格",
    description: "管理企业销售倍率和适用范围，固定展示 1 元 = 100 智点；倍率与货币换算职责分离。",
    scope: "销售价格版本、倍率、影响预览与审批",
    action: "新建价格版本",
    actionKind: "multiplier-create",
    icon: IconAdjustments,
  },
  points: {
    title: "智点账本",
    description: "企业智点通过批次和不可变分录发放、退回、调账与冲正，创建和审批严格职责分离。",
    scope: "企业账户、批次、账本事务、审批与勾稽",
    action: "发起智点发放",
    actionKind: "point-grant",
    icon: IconWallet,
  },
  usage: {
    title: "调用成本与对账",
    description: "从 Logical Invocation 下钻到每次 Provider Attempt、标准化用量、真实成本、企业实扣与账单差异。",
    scope: "UsageCall、Provider Attempt、成本和账单匹配",
    action: "导入供应商账单",
    actionKind: "usage-import",
    icon: IconArrowsExchange,
  },
  monitoring: {
    title: "运行监控",
    description: "监控 Java 控制面、Python Agent Runtime、Worker 租约、SSE 游标、队列、沙箱与 Provider 熔断。",
    scope: "运行元数据、租约、事件游标、告警与恢复演练",
    action: "配置治理策略",
    actionKind: "monitor-policy",
    icon: IconDeviceDesktopAnalytics,
  },
  audit: {
    title: "安全与审计",
    description: "记录高权限操作、跨租户拦截和限时支持授权；支持访问必须绑定工单、对象、字段与截止时间。",
    scope: "安全事件、操作审计、支持会话与导出记录",
    action: "申请支持授权",
    actionKind: "audit-support",
    icon: IconShieldCheck,
  },
};

const MODULE_METRICS = {
  tenants: [["企业总数", "132", "正常 126 · 冻结 4 · 待开通 2"], ["活跃员工", "1,904", "近 24 小时产生任务"], ["可用智点", "286.4 万", "企业账户可用余额"], ["待审批操作", "7", "套餐、停用与智点相关"]],
  "agent-templates": [["官方模板", "18", "首批模板 3 个"], ["已发布版本", "42", "版本不可变"], ["灰度企业", "37", "覆盖 3 个发布批次"], ["待审核", "4", "含 1 个验收集未通过"]],
  skills: [["受控技能", "36", "不含企业私有连接器"], ["全量版本", "28", "均有冻结 Schema"], ["高风险技能", "6", "执行前需要审批"], ["近 24h 异常", "9", "已进入责任队列"]],
  "industry-knowledge": [["行业模板", "12", "覆盖 6 个行业"], ["已派生企业", "86", "升级不覆盖企业文档"], ["检索评估通过", "91.8%", "脱敏黄金集"], ["待重建索引", "3", "均有可见原因"]],
  providers: [["可用 Provider", "8", "文本、视觉、OCR、工具"], ["近 15m 可用性", "99.91%", "按真实 Attempt 统计"], ["受控降级", "2", "未发生越权直连"], ["凭证待轮换", "1", "仅显示凭证引用"]],
  models: [["官方模型", "14", "稳定标识与型号分离"], ["多模态模型", "6", "视觉、生图、编辑"], ["健康路由", "11", "3 个处于受控降级"], ["今日 Attempt", "18,642", "含自动重试与备用模型"]],
  rates: [["生效费率", "32", "覆盖 8 个 Provider"], ["待审批版本", "5", "创建人不可自审"], ["汇率版本", "2026-08-11", "CNY 基准"], ["区间冲突", "0", "激活前强校验"]],
  multipliers: [["生效价格", "21", "企业/套餐范围"], ["平均倍率", "1.48×", "不等于货币换算"], ["待生效", "3", "均已完成影响预览"], ["大幅变价", "1", "需要双人审批"]],
  points: [["企业可用智点", "286.4 万", "不含预占"], ["当前预占", "41.8 万", "按批次与任务冻结"], ["待审批发放", "12.6 万", "4 笔"], ["账本差异", "0", "账户与分录重算一致"]],
  usage: [["Logical Invocation", "12,486", "近 24 小时"], ["Provider Attempt", "13,204", "自动重试 718 次"], ["确认成本", "¥31,842", "另有暂估 ¥1,286"], ["待匹配账单行", "23", "容差外差异 4 笔"]],
  monitoring: [["活跃 Run", "1,904", "单 Thread 单活"], ["Worker 租约", "126", "超时接管 1 次"], ["SSE 活跃连接", "3,842", "重放缺口 2 个"], ["待处理告警", "12", "高 2 · 中 7 · 低 3"]],
  audit: [["高权限操作", "486", "近 24 小时"], ["跨租户拦截", "17", "正文泄漏 0"], ["有效支持会话", "3", "全部限时、限字段"], ["待复核事件", "6", "含凭证轮换 1 项"]],
};

const INITIAL_TENANTS = [
  { id: "ENT-001", name: "星海会展集团", plan: "专业版", admins: 6, agents: 12, points: "48,620", status: "正常", updated: "08-11 10:42" },
  { id: "ENT-002", name: "蓝海设计院", plan: "专业版", admins: 3, agents: 8, points: "32,180", status: "正常", updated: "08-11 09:18" },
  { id: "ENT-003", name: "智联咨询", plan: "标准版", admins: 4, agents: 6, points: "19,843", status: "待变更", updated: "08-10 17:26" },
  { id: "ENT-004", name: "金禾地产", plan: "试点版", admins: 2, agents: 3, points: "6,210", status: "冻结", updated: "08-10 15:04" },
  { id: "ENT-005", name: "启明科技", plan: "标准版", admins: 3, agents: 5, points: "12,135", status: "正常", updated: "08-10 11:33" },
];

const INITIAL_TEMPLATES = [
  { id: "TPL-GRAPHIC", name: "平面出图员工", published: "v1.4.0", candidate: "v1.5.0", acceptance: "98.7%", tenants: 48, status: "灰度中 20%", updated: "08-11 10:06" },
  { id: "TPL-CONTRACT", name: "法务合同审核员工", published: "v1.2.0", candidate: "v1.3.0", acceptance: "97.4%", tenants: 42, status: "待审核", updated: "08-11 09:12" },
  { id: "TPL-QUOTE", name: "报价员工", published: "v1.3.1", candidate: "v1.4.0", acceptance: "99.1%", tenants: 36, status: "已发布", updated: "08-10 18:45" },
  { id: "TPL-BID", name: "投标协作员工", published: "v0.8.0", candidate: "v0.9.0", acceptance: "92.8%", tenants: 6, status: "测试中", updated: "08-10 15:22" },
];

const INITIAL_SKILLS = [
  { id: "SKL-IMG-001", name: "品牌视觉生成", version: "v2.4.1", risk: "中", calls: "3,842", error: "0.31%", status: "全量", updated: "08-11 09:46" },
  { id: "SKL-CTR-002", name: "合同条款定位", version: "v1.8.0", risk: "高", calls: "1,206", error: "0.18%", status: "全量", updated: "08-11 08:32" },
  { id: "SKL-QUO-003", name: "报价规则复算", version: "v1.6.2", risk: "高", calls: "986", error: "0.09%", status: "灰度", updated: "08-10 19:05" },
  { id: "SKL-OCR-004", name: "文档 OCR 解析", version: "v3.1.0", risk: "中", calls: "2,418", error: "0.46%", status: "审核中", updated: "08-10 16:24" },
];

const INITIAL_KNOWLEDGE = [
  { id: "IKT-EXPO", name: "会展项目通用知识模板", version: "v3.2", documents: 48, score: "91.8%", derived: 36, status: "已发布", updated: "08-11 08:20" },
  { id: "IKT-CONTRACT", name: "企业合同审核基线", version: "v2.1", documents: 26, score: "94.2%", derived: 28, status: "灰度", updated: "08-10 20:04" },
  { id: "IKT-BRAND", name: "品牌视觉规范模板", version: "v1.9", documents: 32, score: "89.6%", derived: 22, status: "评估中", updated: "08-10 17:35" },
  { id: "IKT-PRICE", name: "报价资产目录规范", version: "v1.6", documents: 18, score: "96.1%", derived: 19, status: "已发布", updated: "08-10 14:10" },
];

const INITIAL_PROVIDERS = [
  { id: "PRV-VOLC", name: "火山方舟", capability: "文本 / 视觉 / 生图", region: "华北 2", uptime: "99.95%", p95: "642 ms", credential: "cred_volc_prod_03", status: "可用" },
  { id: "PRV-ALI", name: "阿里云百炼", capability: "文本 / Embedding / Rerank", region: "华东 1", uptime: "99.88%", p95: "715 ms", credential: "cred_bailian_prod_02", status: "可用" },
  { id: "PRV-TENCENT", name: "腾讯云 TI", capability: "文本 / OCR", region: "华南 1", uptime: "99.92%", p95: "688 ms", credential: "cred_ti_prod_01", status: "受控降级" },
  { id: "PRV-BAIDU", name: "百度千帆", capability: "文本", region: "华北 1", uptime: "99.73%", p95: "881 ms", credential: "cred_qianfan_prod_01", status: "限流" },
];

const INITIAL_MODELS = [
  { id: "mdl-text-pro", name: "点联文本 Pro", provider: "火山方舟", providerModel: "doubao-pro-32k", modality: "文本 / Tool Call", context: "32K", route: "主路由", health: "健康" },
  { id: "mdl-vision-pro", name: "点联视觉 Pro", provider: "火山方舟", providerModel: "doubao-vision-pro", modality: "文本 / 图片", context: "32K", route: "主路由", health: "健康" },
  { id: "mdl-image-v1", name: "点联生图 V1", provider: "火山方舟", providerModel: "seedream-v4", modality: "生图 / 编辑", context: "8 图", route: "主路由", health: "健康" },
  { id: "mdl-text-backup", name: "点联文本备用", provider: "阿里云百炼", providerModel: "qwen-plus", modality: "文本 / Tool Call", context: "128K", route: "备用路由", health: "观察" },
  { id: "mdl-ocr", name: "点联合同 OCR", provider: "腾讯云 TI", providerModel: "contract-ocr-v3", modality: "OCR", context: "200 页", route: "受控降级", health: "降级" },
];

const INITIAL_RATES = [
  { id: "RATE-0811-01", provider: "火山方舟", meter: "TEXT_INPUT_TOKEN", price: "¥0.0008 / 千 Token", currency: "CNY", tax: "含税 6%", effective: "2026-08-15", status: "待审批" },
  { id: "RATE-0808-02", provider: "火山方舟", meter: "IMAGE_GENERATION", price: "¥0.1800 / 张", currency: "CNY", tax: "含税 6%", effective: "2026-08-08", status: "已生效" },
  { id: "RATE-0805-03", provider: "阿里云百炼", meter: "EMBEDDING_TOKEN", price: "¥0.0005 / 千 Token", currency: "CNY", tax: "含税 6%", effective: "2026-08-05", status: "已生效" },
  { id: "RATE-0801-04", provider: "腾讯云 TI", meter: "OCR_PAGE", price: "¥0.0350 / 页", currency: "CNY", tax: "未税", effective: "2026-08-01", status: "已生效" },
];

const INITIAL_MULTIPLIERS = [
  { id: "SELL-0811-01", scope: "专业版企业", resource: "文本模型", multiplier: "1.42×", affected: 68, effective: "2026-08-18", status: "待审批" },
  { id: "SELL-0809-02", scope: "全部企业", resource: "图片生成", multiplier: "1.65×", affected: 126, effective: "2026-08-09", status: "已生效" },
  { id: "SELL-0806-03", scope: "试点企业", resource: "合同 OCR", multiplier: "1.20×", affected: 12, effective: "2026-08-12", status: "待生效" },
  { id: "SELL-0801-04", scope: "标准版企业", resource: "Embedding / Rerank", multiplier: "1.35×", affected: 46, effective: "2026-08-01", status: "已生效" },
];

const INITIAL_POINT_ACCOUNTS = [
  { tenant: "星海会展集团", available: 48620, reserved: 12840, consumed: 32480, expiring: 8600, status: "正常" },
  { tenant: "蓝海设计院", available: 32180, reserved: 7210, consumed: 19420, expiring: 4200, status: "正常" },
  { tenant: "智联咨询", available: 19843, reserved: 3860, consumed: 14120, expiring: 2800, status: "正常" },
  { tenant: "金禾地产", available: 6210, reserved: 1240, consumed: 10890, expiring: 2100, status: "冻结" },
];

const INITIAL_POINT_TRANSACTIONS = [
  { id: "PTX-20260811-008", tenant: "星海会展集团", type: "发放", amount: 50000, batch: "LOT-2026-Q3-18", creator: "陈敏", approver: "待分配", status: "待审批", time: "08-11 10:18" },
  { id: "PTX-20260811-007", tenant: "蓝海设计院", type: "退回", amount: -1200, batch: "LOT-2026-Q2-09", creator: "林琦", approver: "周维", status: "已过账", time: "08-11 09:32" },
  { id: "PTX-20260810-021", tenant: "智联咨询", type: "调账", amount: 380, batch: "ADJ-2026-0810", creator: "陈敏", approver: "周维", status: "已过账", time: "08-10 18:05" },
];

const INITIAL_USAGE_CALLS = [
  { id: "UC-8F31A2", tenant: "星海会展集团", capability: "平面出图", model: "点联生图 V1", attempts: 2, usage: "4 张 · 2048×2048", points: "286", cost: "¥1.44", status: "已确认", time: "08-11 10:42" },
  { id: "UC-8F319D", tenant: "蓝海设计院", capability: "合同审核", model: "点联文本 Pro", attempts: 1, usage: "36.4K Token · 18 页 OCR", points: "118", cost: "¥0.63", status: "暂估", time: "08-11 10:38" },
  { id: "UC-8F3187", tenant: "智联咨询", capability: "报价", model: "点联文本 Pro", attempts: 3, usage: "18.2K Token", points: "76", cost: "¥0.41", status: "差异待处理", time: "08-11 10:31" },
  { id: "UC-8F3172", tenant: "星海会展集团", capability: "合同审核", model: "点联合同 OCR", attempts: 1, usage: "42 页 OCR", points: "92", cost: "¥1.47", status: "已确认", time: "08-11 10:22" },
];

const ATTEMPTS_BY_CALL = {
  "UC-8F31A2": [
    { id: "ATT-90112", provider: "火山方舟", result: "超时", usage: "0 张", cost: "¥0.00", charged: "否（平台重试）", epoch: "1" },
    { id: "ATT-90113", provider: "火山方舟", result: "成功", usage: "4 张", cost: "¥1.44", charged: "是", epoch: "1" },
  ],
  "UC-8F319D": [{ id: "ATT-90108", provider: "火山方舟 + 腾讯云 TI", result: "成功", usage: "36.4K Token / 18 页", cost: "¥0.63 暂估", charged: "是", epoch: "4" }],
  "UC-8F3187": [
    { id: "ATT-90101", provider: "火山方舟", result: "限流", usage: "0", cost: "¥0.00", charged: "否（平台重试）", epoch: "2" },
    { id: "ATT-90102", provider: "阿里云百炼", result: "成功", usage: "18.2K Token", cost: "¥0.37", charged: "是", epoch: "2" },
    { id: "ATT-90103", provider: "账单追补", result: "待匹配", usage: "缓存 Token", cost: "+¥0.04", charged: "否", epoch: "—" },
  ],
  "UC-8F3172": [{ id: "ATT-90094", provider: "腾讯云 TI", result: "成功", usage: "42 页", cost: "¥1.47", charged: "是", epoch: "6" }],
};

const INITIAL_RUNTIME_SERVICES = [
  { name: "Java Control Plane", instances: "4 / 4", latency: "82 ms", queue: "124", error: "0.08%", status: "健康" },
  { name: "Python Agent Runtime", instances: "8 / 8", latency: "1.8 s", queue: "286", error: "0.31%", status: "健康" },
  { name: "Runtime Authorizer", instances: "3 / 3", latency: "18 ms", queue: "—", error: "0.02%", status: "健康" },
  { name: "Sandbox Pool", instances: "22 / 24", latency: "4.2 s", queue: "18", error: "0.44%", status: "观察" },
  { name: "SSE Gateway", instances: "4 / 4", latency: "41 ms", queue: "3,842 连接", error: "0.12%", status: "健康" },
];

const INITIAL_RUNTIME_RUNS = [
  { id: "RUN-A92F", task: "TASK-24810", tenant: "星海会展集团", worker: "py-worker-07", epoch: 4, generation: 2, heartbeat: "6 秒前", checkpoint: "CP-18", status: "运行中" },
  { id: "RUN-A92C", task: "TASK-24804", tenant: "蓝海设计院", worker: "py-worker-03", epoch: 7, generation: 1, heartbeat: "38 秒前", checkpoint: "CP-09", status: "租约超时" },
  { id: "RUN-A918", task: "TASK-24788", tenant: "智联咨询", worker: "py-worker-05", epoch: 3, generation: 3, heartbeat: "9 秒前", checkpoint: "CP-24", status: "等待用户" },
  { id: "RUN-A902", task: "TASK-24763", tenant: "星海会展集团", worker: "py-worker-01", epoch: 5, generation: 1, heartbeat: "已终止", checkpoint: "CP-31", status: "结果待确认" },
];

const INITIAL_AUDIT_ROWS = [
  { id: "AUD-811-0048", actor: "平台定价管理员 / 陈敏", action: "提交费率版本", object: "RATE-0811-01", scope: "全平台费率", result: "待审批", trace: "TR-783A", time: "08-11 10:26" },
  { id: "AUD-811-0047", actor: "Runtime Authorizer", action: "拒绝旧 epoch 工具调用", object: "RUN-A92C / epoch 6", scope: "蓝海设计院", result: "已阻断", trace: "TR-7831", time: "08-11 10:22" },
  { id: "AUD-811-0046", actor: "平台支持 / 林琦", action: "读取运行元数据", object: "SUP-260811-03", scope: "星海会展集团 · 30 分钟", result: "允许", trace: "TR-782D", time: "08-11 10:18" },
  { id: "AUD-811-0045", actor: "跨租户访问守卫", action: "读取合同正文", object: "DOC-REDACTED", scope: "不匹配租户", result: "已阻断", trace: "TR-7822", time: "08-11 10:11" },
];

const INITIAL_SUPPORT_SESSIONS = [
  { id: "SUP-260811-03", tenant: "星海会展集团", ticket: "TKT-19382", scope: "Run / Attempt 元数据", expires: "08-11 11:00", operator: "林琦", status: "生效中" },
  { id: "SUP-260811-02", tenant: "蓝海设计院", ticket: "TKT-19371", scope: "SSE 游标与告警", expires: "08-11 10:45", operator: "周维", status: "即将到期" },
  { id: "SUP-260810-11", tenant: "智联咨询", ticket: "TKT-19320", scope: "模型路由元数据", expires: "08-10 18:00", operator: "林琦", status: "已到期" },
];

function statusTone(value = "") {
  if (/健康|正常|可用|已发布|已生效|已确认|已过账|全量|允许|已阻断|生效中/.test(value)) return "success";
  if (/待|观察|灰度|暂估|即将|测试|变更/.test(value)) return "warning";
  if (/冻结|超时|差异|异常|失败|降级|限流|熔断|到期|撤销|结果待确认/.test(value)) return "danger";
  return "info";
}

function matchesQuery(row, query) {
  if (!query.trim()) return true;
  return Object.values(row).join(" ").toLowerCase().includes(query.trim().toLowerCase());
}

function filterRows(rows, query, filter, statusKey = "status") {
  return rows.filter((row) => matchesQuery(row, query) && (filter === "全部状态" || row[statusKey] === filter));
}

function StatusBadge({ children }) {
  return <span className={`pm-status pm-status--${statusTone(String(children))}`}>{children}</span>;
}

function RiskBadge({ level }) {
  const tone = level === "高" ? "danger" : level === "中" ? "warning" : "success";
  return <span className={`pm-risk pm-risk--${tone}`}>{level}风险</span>;
}

function ModuleHeader({ meta, lastUpdated, onPrimaryAction, onRefresh }) {
  const ModuleIcon = meta.icon;
  return (
    <section className="pm-page-heading">
      <div className="pm-heading-copy">
        <span className="pm-heading-icon"><ModuleIcon size={22} stroke={1.7} /></span>
        <div>
          <h1>{meta.title}</h1>
          <p>{meta.description}</p>
          <small><IconLock size={13} />数据范围：{meta.scope} · 最近刷新 {lastUpdated}</small>
        </div>
      </div>
      <div className="pm-heading-actions">
        <button type="button" className="pm-button pm-button--secondary" onClick={onRefresh}><IconRefresh size={17} />刷新数据</button>
        <button type="button" className="pm-button pm-button--primary" onClick={onPrimaryAction}><IconPlus size={17} />{meta.action}</button>
      </div>
    </section>
  );
}

function MetricGrid({ metrics }) {
  const icons = [IconDatabase, IconActivity, IconChecklist, IconAlertTriangle];
  return (
    <section className="pm-metric-grid" aria-label="模块关键指标">
      {metrics.map(([label, value, note], index) => {
        const MetricIcon = icons[index];
        return (
          <article className="pm-metric" key={label}>
            <span className={`pm-metric__icon pm-metric__icon--${index + 1}`}><MetricIcon size={22} stroke={1.7} /></span>
            <div><p>{label}</p><strong>{value}</strong><small>{note}</small></div>
          </article>
        );
      })}
    </section>
  );
}

function ModuleToolbar({ query, onQueryChange, filter, onFilterChange, statuses, count, noun }) {
  return (
    <div className="pm-toolbar">
      <label className="pm-search"><IconSearch size={17} /><input value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder={`搜索${noun}、编号或状态`} /></label>
      <label className="pm-filter"><span>状态</span><select value={filter} onChange={(event) => onFilterChange(event.target.value)}>{statuses.map((status) => <option key={status}>{status}</option>)}</select></label>
      <span className="pm-result-count">当前 {count} 条</span>
    </div>
  );
}

function SectionHeader({ title, description, actionLabel, onAction }) {
  return (
    <div className="pm-section-heading">
      <div><h2>{title}</h2>{description && <p>{description}</p>}</div>
      {actionLabel && <button type="button" className="pm-inline-action" onClick={onAction}>{actionLabel}<IconChevronRight size={15} /></button>}
    </div>
  );
}

function EmptyRows({ colSpan }) {
  return <tr><td className="pm-empty-row" colSpan={colSpan}>当前筛选条件下没有记录，请调整搜索词或状态。</td></tr>;
}

function ActionButtons({ children }) {
  return <div className="pm-row-actions">{children}</div>;
}

function ProtectedNote({ children }) {
  return <div className="pm-protected-note"><IconShieldCheck size={17} />{children}</div>;
}

function TenantsView({ rows, query, setQuery, filter, setFilter, openDrawer, openConfirm }) {
  const visible = filterRows(rows, query, filter);
  return (
    <section className="pm-section">
      <SectionHeader title="企业租户与账户摘要" description="停用前必须预览登录、运行、检索、交付和计费影响；客户成功无权直接修改账本。" />
      <ModuleToolbar query={query} onQueryChange={setQuery} filter={filter} onFilterChange={setFilter} statuses={["全部状态", "正常", "待变更", "冻结"]} count={visible.length} noun="企业" />
      <div className="pm-table-wrap"><table className="pm-table"><thead><tr><th>企业</th><th>套餐</th><th>管理员</th><th>数字员工</th><th>可用智点</th><th>账户状态</th><th>更新时间</th><th>操作</th></tr></thead><tbody>
        {visible.map((row) => <tr key={row.id}><td><strong>{row.name}</strong><small>{row.id}</small></td><td>{row.plan}</td><td>{row.admins}</td><td>{row.agents}</td><td className="pm-number">{row.points}</td><td><StatusBadge>{row.status}</StatusBadge></td><td>{row.updated}</td><td><ActionButtons><button type="button" onClick={() => openDrawer("tenant-detail", row)}>查看影响</button><button type="button" className={row.status === "冻结" ? "is-positive" : "is-danger"} onClick={() => openConfirm("tenant-freeze", row)}>{row.status === "冻结" ? "解除冻结" : "冻结"}</button></ActionButtons></td></tr>)}
        {!visible.length && <EmptyRows colSpan={8} />}
      </tbody></table></div>
      <ProtectedNote>平台端只展示企业资料、套餐权益、管理员数量与账户摘要；合同正文、源图、提示词、报价明细和私人记忆不在本页数据范围。</ProtectedNote>
    </section>
  );
}

function TemplatesView({ rows, query, setQuery, filter, setFilter, openDrawer, openConfirm }) {
  const visible = filterRows(rows, query, filter);
  return (
    <div className="pm-stack">
      <section className="pm-release-rail" aria-label="模板版本发布门禁">
        {["创建不可变草稿", "岗位验收集", "审核与影响预览", "租户灰度", "全量或回滚"].map((step, index) => <div key={step}><span>{index + 1}</span><strong>{step}</strong><small>{index < 2 ? "版本输入" : index === 2 ? "maker-checker" : "实例显式升级"}</small></div>)}
      </section>
      <section className="pm-section">
        <SectionHeader title="官方模板与候选版本" description="模板与版本分离；已运行任务继续使用创建时冻结版本，发布不替换企业实例。" actionLabel="查看发布规则" onAction={() => openDrawer("template-policy")} />
        <ModuleToolbar query={query} onQueryChange={setQuery} filter={filter} onFilterChange={setFilter} statuses={["全部状态", "灰度中 20%", "待审核", "已发布", "测试中"]} count={visible.length} noun="模板" />
        <div className="pm-table-wrap"><table className="pm-table"><thead><tr><th>模板</th><th>当前发布</th><th>候选版本</th><th>岗位验收</th><th>企业实例</th><th>发布状态</th><th>更新时间</th><th>操作</th></tr></thead><tbody>
          {visible.map((row) => <tr key={row.id}><td><strong>{row.name}</strong><small>{row.id}</small></td><td>{row.published}</td><td>{row.candidate}</td><td><span className={Number.parseFloat(row.acceptance) < 95 ? "pm-score is-low" : "pm-score"}>{row.acceptance}</span></td><td>{row.tenants}</td><td><StatusBadge>{row.status}</StatusBadge></td><td>{row.updated}</td><td><ActionButtons><button type="button" onClick={() => openDrawer("template-detail", row)}>版本详情</button><button type="button" onClick={() => openDrawer("template-release", row)}>发布</button><button type="button" className="is-danger" onClick={() => openConfirm("template-rollback", row)}>回滚</button></ActionButtons></td></tr>)}
          {!visible.length && <EmptyRows colSpan={8} />}
        </tbody></table></div>
      </section>
    </div>
  );
}

function SkillsView({ rows, query, setQuery, filter, setFilter, openDrawer, openConfirm }) {
  const visible = filterRows(rows, query, filter);
  return (
    <section className="pm-section">
      <SectionHeader title="受控技能目录" description="每个版本冻结输入输出 Schema、工具依赖、权限、计费和失败策略；历史任务仍可复现。" />
      <ModuleToolbar query={query} onQueryChange={setQuery} filter={filter} onFilterChange={setFilter} statuses={["全部状态", "全量", "灰度", "审核中"]} count={visible.length} noun="技能" />
      <div className="pm-table-wrap"><table className="pm-table"><thead><tr><th>技能</th><th>版本</th><th>风险</th><th>近 24h 调用</th><th>异常率</th><th>状态</th><th>更新时间</th><th>操作</th></tr></thead><tbody>
        {visible.map((row) => <tr key={row.id}><td><strong>{row.name}</strong><small>{row.id}</small></td><td>{row.version}</td><td><RiskBadge level={row.risk} /></td><td>{row.calls}</td><td>{row.error}</td><td><StatusBadge>{row.status}</StatusBadge></td><td>{row.updated}</td><td><ActionButtons><button type="button" onClick={() => openDrawer("skill-detail", row)}>审核详情</button><button type="button" className="is-danger" onClick={() => openConfirm("skill-pause", row)}>{row.status === "暂停" ? "恢复" : "暂停"}</button></ActionButtons></td></tr>)}
        {!visible.length && <EmptyRows colSpan={8} />}
      </tbody></table></div>
      <ProtectedNote>高风险写技能必须经过安全审核和业务审批；页面不接受脚本粘贴、任意代码上传或企业自行加载未签名执行包。</ProtectedNote>
    </section>
  );
}

function KnowledgeView({ rows, query, setQuery, filter, setFilter, openDrawer, openConfirm }) {
  const visible = filterRows(rows, query, filter);
  return (
    <section className="pm-section">
      <SectionHeader title="行业知识模板与检索评估" description="平台模板只提供目录、规范和检索策略；企业派生后自有文档不会被平台升级覆盖。" />
      <ModuleToolbar query={query} onQueryChange={setQuery} filter={filter} onFilterChange={setFilter} statuses={["全部状态", "已发布", "灰度", "评估中"]} count={visible.length} noun="知识模板" />
      <div className="pm-table-wrap"><table className="pm-table"><thead><tr><th>行业模板</th><th>版本</th><th>样例文档</th><th>检索评估</th><th>派生企业</th><th>状态</th><th>更新时间</th><th>操作</th></tr></thead><tbody>
        {visible.map((row) => <tr key={row.id}><td><strong>{row.name}</strong><small>{row.id}</small></td><td>{row.version}</td><td>{row.documents}</td><td><span className="pm-score">{row.score}</span></td><td>{row.derived}</td><td><StatusBadge>{row.status}</StatusBadge></td><td>{row.updated}</td><td><ActionButtons><button type="button" onClick={() => openDrawer("knowledge-detail", row)}>评估详情</button><button type="button" onClick={() => openDrawer("knowledge-evaluate", row)}>重新评估</button><button type="button" className="is-danger" onClick={() => openConfirm("knowledge-stop", row)}>停用</button></ActionButtons></td></tr>)}
        {!visible.length && <EmptyRows colSpan={8} />}
      </tbody></table></div>
    </section>
  );
}

function ProvidersView({ rows, query, setQuery, filter, setFilter, openDrawer, openConfirm }) {
  const visible = filterRows(rows, query, filter);
  return (
    <div className="pm-two-column">
      <section className="pm-section pm-two-column__main">
        <SectionHeader title="Provider 健康与授权" description="所有模型和工具调用必须经过统一网关；凭证只保存引用，不在页面或日志回显。" />
        <ModuleToolbar query={query} onQueryChange={setQuery} filter={filter} onFilterChange={setFilter} statuses={["全部状态", "可用", "受控降级", "限流"]} count={visible.length} noun="Provider" />
        <div className="pm-table-wrap"><table className="pm-table"><thead><tr><th>Provider</th><th>能力</th><th>区域</th><th>可用性</th><th>P95</th><th>凭证引用</th><th>状态</th><th>操作</th></tr></thead><tbody>
          {visible.map((row) => <tr key={row.id}><td><strong>{row.name}</strong><small>{row.id}</small></td><td>{row.capability}</td><td>{row.region}</td><td>{row.uptime}</td><td>{row.p95}</td><td><code>{row.credential}</code></td><td><StatusBadge>{row.status}</StatusBadge></td><td><ActionButtons><button type="button" onClick={() => openDrawer("provider-detail", row)}>治理详情</button><button type="button" className="is-danger" onClick={() => openConfirm("provider-pause", row)}>{row.status === "熔断" ? "恢复" : "熔断"}</button></ActionButtons></td></tr>)}
          {!visible.length && <EmptyRows colSpan={8} />}
        </tbody></table></div>
      </section>
      <aside className="pm-side-panel">
        <SectionHeader title="调用边界" />
        <ol className="pm-policy-list"><li><IconCheck size={15} />超时、限流、重试和幂等由网关统一执行。</li><li><IconCheck size={15} />停用前展示受影响模型、技能、员工和租户。</li><li><IconCheck size={15} />回调重放使用稳定效果意图与请求哈希。</li><li><IconCheck size={15} />Provider 不承载点联核心业务事实。</li></ol>
        <button type="button" className="pm-button pm-button--secondary pm-button--block" onClick={() => openDrawer("provider-policy")}>查看健康与熔断策略</button>
      </aside>
    </div>
  );
}

function ModelsView({ rows, query, setQuery, filter, setFilter, openDrawer, openConfirm, onTest }) {
  const visible = filterRows(rows, query, filter, "health");
  return (
    <div className="pm-stack">
      <section className="pm-routing-summary">
        <div><IconCpu size={21} /><span><strong>稳定模型 ID</strong><small>业务配置不引用供应商原生对象</small></span></div>
        <IconChevronRight size={18} />
        <div><IconAdjustments size={21} /><span><strong>能力与路由标签</strong><small>模态、区域、上下文、限额</small></span></div>
        <IconChevronRight size={18} />
        <div><IconLink size={21} /><span><strong>Provider Attempt</strong><small>每次真实上游尝试独立计量</small></span></div>
      </section>
      <section className="pm-section">
        <SectionHeader title="官方模型与全局路由" description="停用、降级和切换备用模型前先预览能力兼容、智点预估与在途任务影响。" />
        <ModuleToolbar query={query} onQueryChange={setQuery} filter={filter} onFilterChange={setFilter} statuses={["全部状态", "健康", "观察", "降级"]} count={visible.length} noun="模型" />
        <div className="pm-table-wrap"><table className="pm-table"><thead><tr><th>官方模型</th><th>Provider / 型号</th><th>模态</th><th>上下文</th><th>路由</th><th>健康</th><th>操作</th></tr></thead><tbody>
          {visible.map((row) => <tr key={row.id}><td><strong>{row.name}</strong><small>{row.id}</small></td><td><strong className="pm-cell-normal">{row.provider}</strong><small>{row.providerModel}</small></td><td>{row.modality}</td><td>{row.context}</td><td>{row.route}</td><td><StatusBadge>{row.health}</StatusBadge></td><td><ActionButtons><button type="button" onClick={() => openDrawer("model-detail", row)}>路由详情</button><button type="button" onClick={() => onTest(row)}>连通测试</button><button type="button" className="is-danger" onClick={() => openConfirm("model-failover", row)}>切换备用</button></ActionButtons></td></tr>)}
          {!visible.length && <EmptyRows colSpan={7} />}
        </tbody></table></div>
      </section>
    </div>
  );
}

function RatesView({ rows, query, setQuery, filter, setFilter, openDrawer, openConfirm }) {
  const visible = filterRows(rows, query, filter);
  return (
    <div className="pm-two-column pm-two-column--pricing">
      <section className="pm-section pm-two-column__main">
        <SectionHeader title="供应商成本费率版本" description="费率只能追加版本；激活时校验生效区间不重叠，历史成本继续使用原 RateSnapshot。" />
        <ModuleToolbar query={query} onQueryChange={setQuery} filter={filter} onFilterChange={setFilter} statuses={["全部状态", "待审批", "已生效"]} count={visible.length} noun="费率" />
        <div className="pm-table-wrap"><table className="pm-table"><thead><tr><th>费率版本</th><th>Provider</th><th>计量项</th><th>单位成本</th><th>币种</th><th>税口径</th><th>生效日</th><th>状态</th><th>操作</th></tr></thead><tbody>
          {visible.map((row) => <tr key={row.id}><td><strong>{row.id}</strong></td><td>{row.provider}</td><td><code>{row.meter}</code></td><td className="pm-number">{row.price}</td><td>{row.currency}</td><td>{row.tax}</td><td>{row.effective}</td><td><StatusBadge>{row.status}</StatusBadge></td><td><ActionButtons><button type="button" onClick={() => openDrawer("rate-detail", row)}>试算与差异</button>{row.status === "待审批" && <button type="button" onClick={() => openConfirm("rate-activate", row)}>审批激活</button>}</ActionButtons></td></tr>)}
          {!visible.length && <EmptyRows colSpan={9} />}
        </tbody></table></div>
      </section>
      <aside className="pm-side-panel pm-pricing-preview"><SectionHeader title="成本预览" description="以 2026-08-10 用量回放，不改历史账务。" /><dl><div><dt>当前确认成本</dt><dd>¥31,842.18</dd></div><div><dt>候选费率回放</dt><dd>¥32,406.72</dd></div><div><dt>预估变化</dt><dd className="is-danger">+1.77%</dd></div><div><dt>区间冲突</dt><dd className="is-success">0</dd></div></dl><button type="button" className="pm-button pm-button--secondary pm-button--block" onClick={() => openDrawer("rate-impact")}>查看完整影响预览</button></aside>
    </div>
  );
}

function MultipliersView({ rows, query, setQuery, filter, setFilter, openDrawer, openConfirm }) {
  const visible = filterRows(rows, query, filter);
  return (
    <div className="pm-two-column pm-two-column--pricing">
      <section className="pm-section pm-two-column__main">
        <SectionHeader title="企业销售价格版本" description="销售倍率按资源和范围冻结；价格变更不回写历史扣费，固定换算仍为 1 元 = 100 智点。" />
        <ModuleToolbar query={query} onQueryChange={setQuery} filter={filter} onFilterChange={setFilter} statuses={["全部状态", "待审批", "待生效", "已生效"]} count={visible.length} noun="价格版本" />
        <div className="pm-table-wrap"><table className="pm-table"><thead><tr><th>价格版本</th><th>适用范围</th><th>资源</th><th>销售倍率</th><th>影响企业</th><th>生效日</th><th>状态</th><th>操作</th></tr></thead><tbody>
          {visible.map((row) => <tr key={row.id}><td><strong>{row.id}</strong></td><td>{row.scope}</td><td>{row.resource}</td><td className="pm-number">{row.multiplier}</td><td>{row.affected}</td><td>{row.effective}</td><td><StatusBadge>{row.status}</StatusBadge></td><td><ActionButtons><button type="button" onClick={() => openDrawer("multiplier-detail", row)}>变价预览</button>{row.status !== "已生效" && <button type="button" onClick={() => openConfirm("multiplier-activate", row)}>审批发布</button>}</ActionButtons></td></tr>)}
          {!visible.length && <EmptyRows colSpan={8} />}
        </tbody></table></div>
      </section>
      <aside className="pm-side-panel pm-pricing-preview"><SectionHeader title="销售口径" /><dl><div><dt>智点换算</dt><dd>1 元 = 100 智点</dd></div><div><dt>平台平均倍率</dt><dd>1.48×</dd></div><div><dt>预计月贡献变化</dt><dd className="is-success">+¥8,240</dd></div><div><dt>大幅变价预警</dt><dd className="is-danger">1 个版本</dd></div></dl><ProtectedNote>企业管理员只看到官方销售价和智点，不显示供应商底价、内部倍率或平台贡献额。</ProtectedNote></aside>
    </div>
  );
}

function PointsView({ accounts, transactions, query, setQuery, filter, setFilter, openDrawer, openConfirm }) {
  const visible = filterRows(accounts, query, filter);
  return (
    <div className="pm-stack">
      <section className="pm-section">
        <SectionHeader title="企业智点账户" description="余额是不可变分录重算结果，禁止直接编辑；账户摘要与企业私有业务内容分离。" />
        <ModuleToolbar query={query} onQueryChange={setQuery} filter={filter} onFilterChange={setFilter} statuses={["全部状态", "正常", "冻结"]} count={visible.length} noun="企业账户" />
        <div className="pm-table-wrap"><table className="pm-table"><thead><tr><th>企业</th><th>可用智点</th><th>预占</th><th>累计实扣</th><th>30 日内到期</th><th>状态</th><th>操作</th></tr></thead><tbody>
          {visible.map((row) => <tr key={row.tenant}><td><strong>{row.tenant}</strong></td><td className="pm-number">{row.available.toLocaleString()}</td><td className="pm-number">{row.reserved.toLocaleString()}</td><td className="pm-number">{row.consumed.toLocaleString()}</td><td className="pm-number">{row.expiring.toLocaleString()}</td><td><StatusBadge>{row.status}</StatusBadge></td><td><ActionButtons><button type="button" onClick={() => openDrawer("point-detail", row)}>批次与分录</button><button type="button" onClick={() => openDrawer("point-grant", row)}>发起发放</button></ActionButtons></td></tr>)}
          {!visible.length && <EmptyRows colSpan={7} />}
        </tbody></table></div>
      </section>
      <section className="pm-section">
        <SectionHeader title="发放、退回与调账审批" description="创建人与审批人必须分离；已过账记录只能通过关联原交易的冲正分录调整。" />
        <div className="pm-table-wrap"><table className="pm-table"><thead><tr><th>事务号</th><th>企业</th><th>类型</th><th>智点</th><th>批次</th><th>创建 / 审批</th><th>状态</th><th>时间</th><th>操作</th></tr></thead><tbody>
          {transactions.map((row) => <tr key={row.id}><td><code>{row.id}</code></td><td>{row.tenant}</td><td>{row.type}</td><td className={row.amount < 0 ? "pm-number is-danger" : "pm-number is-success"}>{row.amount > 0 ? "+" : ""}{row.amount.toLocaleString()}</td><td>{row.batch}</td><td><strong className="pm-cell-normal">{row.creator}</strong><small>{row.approver}</small></td><td><StatusBadge>{row.status}</StatusBadge></td><td>{row.time}</td><td><ActionButtons><button type="button" onClick={() => openDrawer("point-transaction", row)}>审计链</button>{row.status === "待审批" && <button type="button" onClick={() => openConfirm("points-approve", row)}>审批过账</button>}</ActionButtons></td></tr>)}
        </tbody></table></div>
      </section>
    </div>
  );
}

function UsageView({ rows, query, setQuery, filter, setFilter, openDrawer, openConfirm }) {
  const visible = filterRows(rows, query, filter);
  const differences = rows.filter((row) => row.status === "差异待处理" || row.status === "暂估");
  return (
    <div className="pm-stack">
      <section className="pm-call-chain" aria-label="调用和计费事实链">
        {["Logical Invocation", "Provider Attempt", "标准化 Usage", "成本 RateSnapshot", "企业智点分录", "供应商账单"].map((step, index) => <div key={step}><span>{index + 1}</span><strong>{step}</strong></div>)}
      </section>
      <section className="pm-section">
        <SectionHeader title="调用、Attempt 与成本" description="每次真实上游尝试都独立记录；平台自动重试产生真实成本，但不默认重复扣企业智点。" />
        <ModuleToolbar query={query} onQueryChange={setQuery} filter={filter} onFilterChange={setFilter} statuses={["全部状态", "已确认", "暂估", "差异待处理"]} count={visible.length} noun="调用" />
        <div className="pm-table-wrap"><table className="pm-table"><thead><tr><th>UsageCall</th><th>企业 / 能力</th><th>官方模型</th><th>Attempt</th><th>标准化用量</th><th>企业实扣</th><th>Provider 成本</th><th>状态</th><th>操作</th></tr></thead><tbody>
          {visible.map((row) => <tr key={row.id}><td><code>{row.id}</code><small>{row.time}</small></td><td><strong className="pm-cell-normal">{row.tenant}</strong><small>{row.capability}</small></td><td>{row.model}</td><td>{row.attempts}</td><td>{row.usage}</td><td>{row.points} 智点</td><td className="pm-number">{row.cost}</td><td><StatusBadge>{row.status}</StatusBadge></td><td><ActionButtons><button type="button" onClick={() => openDrawer("usage-detail", row)}>下钻 Attempt</button>{row.status === "差异待处理" && <button type="button" onClick={() => openConfirm("usage-close", row)}>处理差异</button>}</ActionButtons></td></tr>)}
          {!visible.length && <EmptyRows colSpan={9} />}
        </tbody></table></div>
      </section>
      <section className="pm-section">
        <SectionHeader title="账单差异责任队列" description="成本调整使用追加记录，不覆盖原 Attempt、用量或费率快照。" />
        <div className="pm-queue-grid">{differences.map((row) => <button type="button" key={row.id} onClick={() => openDrawer("usage-detail", row)}><span className={`pm-queue-dot pm-queue-dot--${statusTone(row.status)}`} /><span><strong>{row.id} · {row.model}</strong><small>{row.tenant} · {row.usage}</small></span><StatusBadge>{row.status}</StatusBadge><IconChevronRight size={17} /></button>)}</div>
      </section>
    </div>
  );
}

function MonitoringView({ services, runs, query, setQuery, filter, setFilter, openDrawer, openConfirm }) {
  const visible = filterRows(runs, query, filter);
  return (
    <div className="pm-stack">
      <section className="pm-service-grid">{services.map((service) => <article key={service.name}><div><span className={`pm-health-dot pm-health-dot--${statusTone(service.status)}`} /><strong>{service.name}</strong><StatusBadge>{service.status}</StatusBadge></div><dl><div><dt>实例</dt><dd>{service.instances}</dd></div><div><dt>P95</dt><dd>{service.latency}</dd></div><div><dt>队列/连接</dt><dd>{service.queue}</dd></div><div><dt>错误率</dt><dd>{service.error}</dd></div></dl></article>)}</section>
      <section className="pm-section">
        <SectionHeader title="Run、Worker 租约与恢复" description="接管时递增 execution epoch 并执行 fencing；旧 Worker 的后续 Gateway 请求必须失败关闭。" />
        <ModuleToolbar query={query} onQueryChange={setQuery} filter={filter} onFilterChange={setFilter} statuses={["全部状态", "运行中", "租约超时", "等待用户", "结果待确认"]} count={visible.length} noun="Run" />
        <div className="pm-table-wrap"><table className="pm-table"><thead><tr><th>Run / Task</th><th>企业</th><th>Worker</th><th>Epoch</th><th>Generation</th><th>Heartbeat</th><th>Checkpoint</th><th>状态</th><th>操作</th></tr></thead><tbody>
          {visible.map((row) => <tr key={row.id}><td><code>{row.id}</code><small>{row.task}</small></td><td>{row.tenant}</td><td>{row.worker}</td><td>{row.epoch}</td><td>{row.generation}</td><td>{row.heartbeat}</td><td>{row.checkpoint}</td><td><StatusBadge>{row.status}</StatusBadge></td><td><ActionButtons><button type="button" onClick={() => openDrawer("run-detail", row)}>运行轨迹</button>{row.status === "租约超时" && <button type="button" onClick={() => openConfirm("run-takeover", row)}>接管</button>}{row.status === "结果待确认" && <button type="button" className="is-danger" onClick={() => openConfirm("run-write-barrier", row)}>保持写屏障</button>}</ActionButtons></td></tr>)}
          {!visible.length && <EmptyRows colSpan={9} />}
        </tbody></table></div>
      </section>
      <section className="pm-monitor-bottom">
        <article className="pm-section"><SectionHeader title="SSE 与事件持久化" /><dl className="pm-compact-kpis"><div><dt>最新全局序号</dt><dd>8,941,276</dd></div><div><dt>重放窗口</dt><dd>24 小时</dd></div><div><dt>游标落后连接</dt><dd>18</dd></div><div><dt>需重置快照</dt><dd>2</dd></div></dl><button type="button" className="pm-button pm-button--secondary" onClick={() => openDrawer("sse-detail")}>查看事件与重放</button></article>
        <article className="pm-section"><SectionHeader title="熔断与舱壁" /><dl className="pm-compact-kpis"><div><dt>模型熔断</dt><dd>1</dd></div><div><dt>工具熔断</dt><dd>0</dd></div><div><dt>租户舱壁触发</dt><dd>3</dd></div><div><dt>沙箱待回收</dt><dd>2</dd></div></dl><button type="button" className="pm-button pm-button--secondary" onClick={() => openDrawer("bulkhead-detail")}>查看隔离策略</button></article>
      </section>
    </div>
  );
}

function AuditView({ rows, sessions, query, setQuery, filter, setFilter, openDrawer, openConfirm }) {
  const visible = filterRows(rows, query, filter, "result");
  return (
    <div className="pm-stack">
      <section className="pm-section">
        <SectionHeader title="安全事件与高权限操作" description="审计记录保留主体、动作、对象、范围、结果和追踪 ID，不写入无必要的企业正文。" />
        <ModuleToolbar query={query} onQueryChange={setQuery} filter={filter} onFilterChange={setFilter} statuses={["全部状态", "待审批", "已阻断", "允许"]} count={visible.length} noun="审计记录" />
        <div className="pm-table-wrap"><table className="pm-table"><thead><tr><th>审计号</th><th>主体</th><th>动作</th><th>对象</th><th>范围</th><th>结果</th><th>Trace ID</th><th>时间</th><th>操作</th></tr></thead><tbody>
          {visible.map((row) => <tr key={row.id}><td><code>{row.id}</code></td><td>{row.actor}</td><td>{row.action}</td><td>{row.object}</td><td>{row.scope}</td><td><StatusBadge>{row.result}</StatusBadge></td><td><code>{row.trace}</code></td><td>{row.time}</td><td><ActionButtons><button type="button" onClick={() => openDrawer("audit-detail", row)}>查看证据</button></ActionButtons></td></tr>)}
          {!visible.length && <EmptyRows colSpan={9} />}
        </tbody></table></div>
      </section>
      <section className="pm-section">
        <SectionHeader title="限时支持授权" description="支持人员不能获得常驻跨租户权限；每次访问绑定工单、数据字段、对象和到期时间。" />
        <div className="pm-support-grid">{sessions.map((session) => <article key={session.id}><div><IconUserShield size={19} /><strong>{session.id}</strong><StatusBadge>{session.status}</StatusBadge></div><dl><div><dt>企业</dt><dd>{session.tenant}</dd></div><div><dt>工单</dt><dd>{session.ticket}</dd></div><div><dt>范围</dt><dd>{session.scope}</dd></div><div><dt>到期</dt><dd>{session.expires}</dd></div></dl><div className="pm-card-actions"><button type="button" onClick={() => openDrawer("support-detail", session)}>访问记录</button>{session.status !== "已到期" && <button type="button" className="is-danger" onClick={() => openConfirm("audit-revoke", session)}>撤销授权</button>}</div></article>)}</div>
      </section>
    </div>
  );
}

const DRAWER_META = {
  "tenant-create": ["开通企业租户", "提交开通"], "tenant-detail": ["租户影响与权限", null],
  "template-create": ["创建模板草稿", "创建不可变草稿"], "template-detail": ["模板版本详情", null], "template-release": ["发布模板版本", "提交发布审批"], "template-policy": ["模板发布规则", null],
  "skill-register": ["注册技能版本", "提交安全审核"], "skill-detail": ["技能审核详情", null],
  "knowledge-create": ["创建行业知识模板", "创建模板"], "knowledge-detail": ["检索评估详情", null], "knowledge-evaluate": ["重新运行检索评估", "开始评估"],
  "provider-connect": ["接入 Provider", "提交接入验证"], "provider-detail": ["Provider 治理详情", null], "provider-policy": ["健康检查与熔断策略", "保存策略草稿"],
  "model-register": ["登记官方模型", "提交模型验证"], "model-detail": ["模型路由与 Attempt", null],
  "rate-create": ["新建供应商费率版本", "提交费率审批"], "rate-detail": ["费率试算与版本差异", null], "rate-impact": ["完整成本影响预览", null],
  "multiplier-create": ["新建企业销售价格", "提交价格审批"], "multiplier-detail": ["企业变价影响预览", null],
  "point-grant": ["发起企业智点发放", "提交账务审批"], "point-detail": ["智点批次与分录", null], "point-transaction": ["账务事务审计链", null],
  "usage-import": ["导入供应商账单", "校验并导入"], "usage-detail": ["调用与 Provider Attempt", null],
  "monitor-policy": ["运行治理策略", "保存策略草稿"], "run-detail": ["Run 持久轨迹", null], "sse-detail": ["SSE 事件与重放", null], "bulkhead-detail": ["熔断与舱壁策略", null],
  "audit-support": ["申请限时支持授权", "提交支持审批"], "audit-detail": ["审计证据", null], "support-detail": ["支持会话访问记录", null],
};

function Field({ label, hint, children }) {
  return <label className="pm-field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>;
}

function ReadonlyGrid({ items }) {
  return <dl className="pm-readonly-grid">{items.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value ?? "—"}</dd></div>)}</dl>;
}

function UsageDetailContent({ item }) {
  const attempts = ATTEMPTS_BY_CALL[item.id] || [];
  return <><ReadonlyGrid items={[["UsageCall", item.id], ["企业", item.tenant], ["能力", item.capability], ["官方模型", item.model], ["企业实扣", `${item.points} 智点`], ["Provider 成本", item.cost], ["状态", item.status], ["时间", item.time]]} /><h3 className="pm-drawer-subtitle">Provider Attempt</h3><div className="pm-mini-table"><div className="pm-mini-table__head"><span>Attempt</span><span>Provider / 结果</span><span>用量</span><span>成本 / 企业收费</span></div>{attempts.map((attempt) => <div key={attempt.id}><span><code>{attempt.id}</code><small>epoch {attempt.epoch}</small></span><span><strong>{attempt.provider}</strong><small>{attempt.result}</small></span><span>{attempt.usage}</span><span><strong>{attempt.cost}</strong><small>{attempt.charged}</small></span></div>)}</div><ProtectedNote>自动重试和备用模型 Attempt 记录真实成本；企业只对同一收费意图结算一次。</ProtectedNote></>;
}

function DrawerContent({ action }) {
  const { kind, item = {} } = action;
  switch (kind) {
    case "tenant-create": return <div className="pm-form-grid"><Field label="企业名称"><input name="name" required placeholder="输入企业全称" /></Field><Field label="企业编号"><input name="code" required placeholder="例如 ENT-006" /></Field><Field label="套餐"><select name="plan" defaultValue="标准版"><option>试点版</option><option>标准版</option><option>专业版</option></select></Field><Field label="首位企业管理员"><input name="admin" type="email" required placeholder="admin@example.com" /></Field><Field label="初始能力权益"><select name="capability" defaultValue="首批三类员工"><option>首批三类员工</option><option>仅平面出图</option><option>仅合同审核与报价</option></select></Field><Field label="数据保留策略"><select name="retention" defaultValue="企业标准策略"><option>企业标准策略</option><option>试点 90 天</option><option>受限行业策略</option></select></Field></div>;
    case "tenant-detail": return <><ReadonlyGrid items={[["企业编号", item.id], ["企业", item.name], ["套餐", item.plan], ["管理员", `${item.admins} 人`], ["数字员工", `${item.agents} 个`], ["可用智点", item.points], ["账户状态", item.status], ["更新时间", item.updated]]} /><h3 className="pm-drawer-subtitle">停用或冻结影响</h3><ul className="pm-impact-list"><li>阻止新登录、模型调用、知识检索和外部交付。</li><li>在途 Run 进入受控暂停，不伪装为已取消或已完成。</li><li>企业账本保持可审计，已过账分录不会被删除。</li><li>平台运营仍不能读取合同、源图、提示词与私人记忆正文。</li></ul></>;
    case "template-create": return <div className="pm-form-grid"><Field label="模板名称"><input name="name" required placeholder="例如 项目复盘员工" /></Field><Field label="能力包"><select name="capability"><option>graphic-design</option><option>contract-review</option><option>quotation</option><option>组合能力包</option></select></Field><Field label="初始版本"><input name="version" required defaultValue="v0.1.0" /></Field><Field label="岗位验收集"><input name="acceptance" required placeholder="选择已脱敏验收集" /></Field><Field label="默认模型能力"><select name="model"><option>文本 / Tool Call</option><option>视觉 / 生图 / 编辑</option><option>OCR / 文本</option></select></Field><Field label="发布负责人"><input name="owner" required placeholder="模板产品经理" /></Field></div>;
    case "template-detail": return <><ReadonlyGrid items={[["模板 ID", item.id], ["模板", item.name], ["已发布版本", item.published], ["候选版本", item.candidate], ["岗位验收", item.acceptance], ["企业实例", item.tenants], ["状态", item.status]]} /><div className="pm-version-timeline"><div className="is-current"><span /><strong>{item.candidate}</strong><small>候选版本 · 输入/输出 Schema、能力依赖和验收集已冻结</small></div><div><span /><strong>{item.published}</strong><small>当前发布 · 运行中任务继续引用此版本</small></div><div><span /><strong>历史版本</strong><small>只读保留，可用于审计和任务复现</small></div></div></>;
    case "template-release": return <><ReadonlyGrid items={[["模板", item.name], ["当前版本", item.published], ["候选版本", item.candidate], ["岗位验收", item.acceptance], ["当前状态", item.status], ["受影响企业", item.tenants]]} /><div className="pm-form-grid"><Field label="发布范围"><select name="scope" defaultValue="10% 灰度"><option>10% 灰度</option><option>30% 灰度</option><option>指定试点企业</option><option>全量发布</option></select></Field><Field label="计划生效"><input name="effective" type="datetime-local" required /></Field><Field label="审批人"><input name="approver" required placeholder="选择模板审核人" /></Field><Field label="发布说明"><textarea name="reason" required placeholder="说明差异、风险和回滚条件" /></Field></div><label className="pm-check-row"><input type="checkbox" required />已确认岗位验收集、模型/知识/工具依赖和失败策略</label><label className="pm-check-row"><input type="checkbox" required />已确认不会静默升级企业实例或改变运行中任务</label></>;
    case "template-policy": return <ol className="pm-rule-cards"><li><strong>版本不可变</strong><span>发布后不覆盖配置，修复也必须创建新版本。</span></li><li><strong>岗位验收门禁</strong><span>平面出图、合同审核和报价分别使用差异化黄金集。</span></li><li><strong>灰度与显式升级</strong><span>企业实例预览差异后选择升级；运行任务冻结旧版本。</span></li><li><strong>可验证回滚</strong><span>回滚改变新任务选择，不破坏历史任务复现。</span></li></ol>;
    case "skill-register": return <div className="pm-form-grid"><Field label="技能名称"><input name="name" required /></Field><Field label="版本"><input name="version" required defaultValue="v1.0.0" /></Field><Field label="风险等级"><select name="risk"><option>低</option><option>中</option><option>高</option></select></Field><Field label="能力包"><select name="pack"><option>graphic-design</option><option>contract-review</option><option>quotation</option><option>platform-shared</option></select></Field><Field label="输入 Schema 摘要"><textarea name="inputSchema" required /></Field><Field label="输出 Schema 摘要"><textarea name="outputSchema" required /></Field></div>;
    case "skill-detail": return <><ReadonlyGrid items={[["技能 ID", item.id], ["技能", item.name], ["版本", item.version], ["风险", `${item.risk}风险`], ["近 24h 调用", item.calls], ["异常率", item.error], ["状态", item.status]]} /><h3 className="pm-drawer-subtitle">审核门禁</h3><ul className="pm-impact-list"><li>Schema 兼容测试通过，历史任务可复现。</li><li>外部副作用具备效果意图、幂等键、超时和结果未知处理。</li><li>高风险动作由企业授权和审批拦截，技能自身不能绕过。</li></ul></>;
    case "knowledge-create": return <div className="pm-form-grid"><Field label="模板名称"><input name="name" required /></Field><Field label="行业"><select name="industry"><option>会展与活动</option><option>专业服务</option><option>通用企业管理</option></select></Field><Field label="版本"><input name="version" required defaultValue="v0.1" /></Field><Field label="索引策略"><select name="index"><option>全文 + 向量 + Rerank</option><option>全文 + 向量</option><option>结构化 + 关系检索</option></select></Field><Field label="脱敏黄金集"><input name="goldenSet" required /></Field><Field label="最低通过分"><input name="threshold" type="number" min="0" max="100" defaultValue="90" required /></Field></div>;
    case "knowledge-detail": return <><ReadonlyGrid items={[["模板 ID", item.id], ["模板", item.name], ["版本", item.version], ["样例文档", item.documents], ["检索评估", item.score], ["派生企业", item.derived], ["状态", item.status]]} /><div className="pm-quality-bars"><div><span>引用定位准确率</span><i><b style={{ width: "96%" }} /></i><strong>96.0%</strong></div><div><span>权限过滤准确率</span><i><b style={{ width: "100%" }} /></i><strong>100%</strong></div><div><span>答案证据充分率</span><i><b style={{ width: item.score }} /></i><strong>{item.score}</strong></div></div><ProtectedNote>平台评估使用脱敏样例；企业派生空间、文档正文和 ACL 不进入行业模板。</ProtectedNote></>;
    case "knowledge-evaluate": return <><ReadonlyGrid items={[["模板", item.name], ["版本", item.version], ["当前得分", item.score], ["样例文档", item.documents]]} /><div className="pm-form-grid"><Field label="评估集版本"><select name="set"><option>golden-2026.08</option><option>golden-2026.07</option></select></Field><Field label="检索配置"><select name="config"><option>当前发布配置</option><option>候选 Rerank 配置</option><option>GraphRAG 对照组</option></select></Field><Field label="失败阈值"><input name="threshold" type="number" defaultValue="90" min="0" max="100" /></Field></div></>;
    case "provider-connect": return <div className="pm-form-grid"><Field label="Provider 名称"><input name="name" required /></Field><Field label="稳定编号"><input name="id" required placeholder="PRV-..." /></Field><Field label="区域"><input name="region" required placeholder="例如 华东 1" /></Field><Field label="能力"><input name="capability" required placeholder="文本 / 视觉 / OCR / 工具" /></Field><Field label="凭证引用" hint="只填写密钥管理系统中的引用，不输入明文密钥"><input name="credential" required placeholder="cred_provider_prod_01" /></Field><Field label="健康检查"><select name="health"><option>每 30 秒</option><option>每 60 秒</option><option>每 5 分钟</option></select></Field></div>;
    case "provider-detail": return <><ReadonlyGrid items={[["Provider ID", item.id], ["Provider", item.name], ["能力", item.capability], ["区域", item.region], ["可用性", item.uptime], ["P95", item.p95], ["凭证引用", item.credential], ["状态", item.status]]} /><h3 className="pm-drawer-subtitle">停用影响摘要</h3><ul className="pm-impact-list"><li>受影响官方模型 3 个、技能 5 个、企业路由 42 条。</li><li>在途 Attempt 不盲目重试，结果未知时进入责任队列。</li><li>恢复后先经过健康窗口，不直接恢复全量流量。</li></ul></>;
    case "provider-policy": return <div className="pm-form-grid"><Field label="失败率熔断阈值"><input name="errorRate" type="number" min="1" max="100" defaultValue="5" /></Field><Field label="P95 延迟阈值（ms）"><input name="latency" type="number" min="100" defaultValue="3000" /></Field><Field label="半开健康窗口"><select name="window"><option>5 分钟</option><option>10 分钟</option><option>15 分钟</option></select></Field><Field label="单租户并发上限"><input name="concurrency" type="number" defaultValue="24" min="1" /></Field><Field label="备用路由"><select name="fallback"><option>兼容模型自动降级</option><option>只告警不切换</option><option>阻断新调用</option></select></Field></div>;
    case "model-register": return <div className="pm-form-grid"><Field label="稳定模型 ID"><input name="id" required placeholder="mdl-..." /></Field><Field label="展示名称"><input name="name" required /></Field><Field label="Provider"><select name="provider"><option>火山方舟</option><option>阿里云百炼</option><option>腾讯云 TI</option></select></Field><Field label="供应商型号"><input name="providerModel" required /></Field><Field label="模态"><select name="modality"><option>文本 / Tool Call</option><option>文本 / 图片</option><option>生图 / 编辑</option><option>OCR</option></select></Field><Field label="上下文/输入限制"><input name="context" required /></Field></div>;
    case "model-detail": return <><ReadonlyGrid items={[["稳定 ID", item.id], ["官方模型", item.name], ["Provider", item.provider], ["供应商型号", item.providerModel], ["模态", item.modality], ["上下文", item.context], ["路由", item.route], ["健康", item.health]]} /><div className="pm-attempt-summary"><h3>近 15 分钟 Attempt</h3><div><span>成功 2,846</span><span>超时 18</span><span>限流 31</span><span>备用路由 42</span></div></div><ProtectedNote>路由切换只影响后续 Attempt；已创建任务继续使用冻结模型策略和预算上限。</ProtectedNote></>;
    case "rate-create": return <div className="pm-form-grid"><Field label="Provider"><select name="provider"><option>火山方舟</option><option>阿里云百炼</option><option>腾讯云 TI</option></select></Field><Field label="计量项"><select name="meter"><option>TEXT_INPUT_TOKEN</option><option>TEXT_OUTPUT_TOKEN</option><option>IMAGE_GENERATION</option><option>IMAGE_EDITING</option><option>OCR_PAGE</option><option>RERANK_CALL</option></select></Field><Field label="单位成本"><input name="price" type="number" step="0.0001" min="0" required /></Field><Field label="币种"><select name="currency"><option>CNY</option><option>USD</option></select></Field><Field label="税口径"><select name="tax"><option>含税 6%</option><option>未税</option></select></Field><Field label="计划生效日"><input name="effective" type="date" required /></Field><Field label="变更依据"><textarea name="reason" required placeholder="供应商公告或合同版本" /></Field></div>;
    case "rate-detail": return <><ReadonlyGrid items={[["费率版本", item.id], ["Provider", item.provider], ["计量项", item.meter], ["单位成本", item.price], ["币种", item.currency], ["税口径", item.tax], ["生效日", item.effective], ["状态", item.status]]} /><div className="pm-compare-table"><div><span>回放调用</span><strong>12,486</strong></div><div><span>当前成本</span><strong>¥31,842.18</strong></div><div><span>候选成本</span><strong>¥32,406.72</strong></div><div><span>差异</span><strong className="is-danger">+¥564.54</strong></div></div></>;
    case "rate-impact": return <><div className="pm-compare-table pm-compare-table--wide"><div><span>影响 Provider</span><strong>3</strong></div><div><span>影响计量项</span><strong>8</strong></div><div><span>回放 Attempt</span><strong>13,204</strong></div><div><span>历史快照改写</span><strong className="is-success">0</strong></div></div><h3 className="pm-drawer-subtitle">校验结果</h3><ul className="pm-impact-list"><li>生效区间重叠冲突 0 个。</li><li>汇率和税口径均有冻结版本。</li><li>历史 Provider Attempt 仍引用原成本快照。</li><li>生效后预计月成本增加 1.77%。</li></ul></>;
    case "multiplier-create": return <div className="pm-form-grid"><Field label="适用范围"><select name="scope"><option>全部企业</option><option>专业版企业</option><option>标准版企业</option><option>指定试点企业</option></select></Field><Field label="资源"><select name="resource"><option>文本模型</option><option>图片生成</option><option>合同 OCR</option><option>Embedding / Rerank</option></select></Field><Field label="销售倍率"><input name="multiplier" type="number" min="1" step="0.01" defaultValue="1.40" required /></Field><Field label="计划生效日"><input name="effective" type="date" required /></Field><Field label="审批人"><input name="approver" required placeholder="选择非创建人的定价审批人" /></Field><Field label="变价原因"><textarea name="reason" required /></Field></div>;
    case "multiplier-detail": return <><ReadonlyGrid items={[["价格版本", item.id], ["范围", item.scope], ["资源", item.resource], ["倍率", item.multiplier], ["影响企业", item.affected], ["生效日", item.effective], ["状态", item.status]]} /><div className="pm-compare-table"><div><span>企业月智点变化</span><strong>+2.8%</strong></div><div><span>平台月贡献变化</span><strong className="is-success">+¥8,240</strong></div><div><span>企业预算触顶</span><strong className="is-danger">3 家</strong></div><div><span>历史账务改写</span><strong className="is-success">0</strong></div></div></>;
    case "point-grant": return <><div className="pm-form-grid"><Field label="企业"><select name="tenant" defaultValue={item.tenant || "星海会展集团"}><option>星海会展集团</option><option>蓝海设计院</option><option>智联咨询</option><option>金禾地产</option></select></Field><Field label="发放智点"><input name="amount" type="number" min="1" step="100" required /></Field><Field label="批次号"><input name="batch" required placeholder="LOT-2026-Q3-..." /></Field><Field label="到期日"><input name="expires" type="date" required /></Field><Field label="账务审批人"><input name="approver" required placeholder="必须与创建人不同" /></Field><Field label="业务依据"><textarea name="reason" required placeholder="合同、订单或审批单号" /></Field></div><ProtectedNote>提交后只创建“待审批”账务意图，不直接增加余额；审批过账后由不可变分录重算账户。</ProtectedNote></>;
    case "point-detail": return <><ReadonlyGrid items={[["企业", item.tenant], ["可用智点", item.available?.toLocaleString()], ["当前预占", item.reserved?.toLocaleString()], ["累计实扣", item.consumed?.toLocaleString()], ["30 日内到期", item.expiring?.toLocaleString()], ["状态", item.status]]} /><h3 className="pm-drawer-subtitle">批次消耗顺序</h3><div className="pm-lot-list"><div><span>LOT-2026-Q3-18</span><strong>18,600 / 30,000</strong><small>2026-09-30 到期</small></div><div><span>LOT-2026-Q2-09</span><strong>12,420 / 25,000</strong><small>2026-08-31 到期</small></div><div><span>LOT-OPENING</span><strong>17,600 / 40,000</strong><small>长期有效</small></div></div></>;
    case "point-transaction": return <><ReadonlyGrid items={[["事务号", item.id], ["企业", item.tenant], ["类型", item.type], ["智点", item.amount?.toLocaleString()], ["批次", item.batch], ["创建人", item.creator], ["审批人", item.approver], ["状态", item.status], ["时间", item.time]]} /><ol className="pm-audit-chain"><li><span>08-11 10:18</span><strong>账务意图创建</strong><small>幂等键和请求哈希已冻结</small></li><li><span>08-11 10:19</span><strong>职责分离校验</strong><small>创建人不在可审批人集合</small></li><li><span>当前</span><strong>{item.status}</strong><small>已过账记录只允许追加冲正</small></li></ol></>;
    case "usage-import": return <div className="pm-form-grid"><Field label="Provider"><select name="provider"><option>火山方舟</option><option>阿里云百炼</option><option>腾讯云 TI</option></select></Field><Field label="账期"><input name="period" type="month" required /></Field><Field label="账单文件"><input name="file" type="file" accept=".csv,.xlsx" required /></Field><Field label="币种"><select name="currency"><option>CNY</option><option>USD</option></select></Field><Field label="匹配容差"><input name="tolerance" type="number" step="0.01" min="0" defaultValue="0.01" /></Field><Field label="批次说明"><textarea name="reason" required /></Field></div>;
    case "usage-detail": return <UsageDetailContent item={item} />;
    case "monitor-policy": return <div className="pm-form-grid"><Field label="Worker 租约时长（秒）"><input name="lease" type="number" min="10" defaultValue="30" /></Field><Field label="Heartbeat 告警（秒）"><input name="heartbeat" type="number" min="5" defaultValue="20" /></Field><Field label="SSE 重放窗口（小时）"><input name="replay" type="number" min="1" defaultValue="24" /></Field><Field label="单租户活跃 Run 上限"><input name="runs" type="number" min="1" defaultValue="64" /></Field><Field label="Sandbox 回收超时（秒）"><input name="sandbox" type="number" min="10" defaultValue="90" /></Field><Field label="策略说明"><textarea name="reason" required defaultValue="变更先进入灰度环境并完成租约接管、SSE 重放和副作用幂等故障演练。" /></Field></div>;
    case "run-detail": return <><ReadonlyGrid items={[["Run", item.id], ["Task", item.task], ["企业", item.tenant], ["Worker", item.worker], ["Execution epoch", item.epoch], ["Generation", item.generation], ["Heartbeat", item.heartbeat], ["Checkpoint", item.checkpoint], ["状态", item.status]]} /><ol className="pm-audit-chain"><li><span>10:31:04</span><strong>Checkpoint {item.checkpoint} 已持久化</strong><small>状态、事件序号与工具效果意图已提交</small></li><li><span>10:31:11</span><strong>Worker heartbeat</strong><small>lease epoch {item.epoch} · generation {item.generation}</small></li><li><span>当前</span><strong>{item.status}</strong><small>接管后旧 epoch 的 Gateway 准入失败关闭</small></li></ol></>;
    case "sse-detail": return <><ReadonlyGrid items={[["活跃连接", "3,842"], ["最新全局序号", "8,941,276"], ["持久重放窗口", "24 小时"], ["落后连接", "18"], ["快照重置", "2"], ["重复业务事件", "0"]]} /><h3 className="pm-drawer-subtitle">恢复规则</h3><ul className="pm-impact-list"><li>断线重连携带最后确认游标，从持久事件日志重放。</li><li>游标超出保留窗口时返回 RESET_REQUIRED，并获取权威快照。</li><li>重放事件只恢复展示，不重新执行模型、工具或扣费副作用。</li></ul></>;
    case "bulkhead-detail": return <><ReadonlyGrid items={[["Java API 舱壁", "按租户 / 能力 / Provider"], ["Python Worker 池", "按能力与沙箱级别"], ["模型熔断", "1 个受控降级"], ["工具熔断", "0"], ["租户舱壁触发", "3"], ["沙箱待回收", "2"]]} /><ul className="pm-impact-list"><li>Authorizer 故障时 Java Gateway 失败关闭，不使用成功结果正缓存。</li><li>Provider 或租户拥塞不能耗尽全部 Worker、连接池和队列。</li><li>沙箱使用一次性执行令牌，超时后撤销并清理工作目录。</li></ul></>;
    case "audit-support": return <><div className="pm-form-grid"><Field label="企业"><select name="tenant"><option>星海会展集团</option><option>蓝海设计院</option><option>智联咨询</option></select></Field><Field label="工单号"><input name="ticket" required placeholder="TKT-..." /></Field><Field label="访问范围"><select name="scope"><option>Run / Attempt 元数据</option><option>SSE 游标与告警</option><option>模型路由元数据</option><option>账本勾稽摘要</option></select></Field><Field label="有效时长"><select name="duration"><option>30 分钟</option><option>60 分钟</option><option>2 小时</option></select></Field><Field label="审批人"><input name="approver" required /></Field><Field label="诊断原因"><textarea name="reason" required /></Field></div><ProtectedNote>授权不包含消息、合同、图片、提示词、报价明细或私人记忆正文；所有读取逐条记录。</ProtectedNote></>;
    case "audit-detail": return <><ReadonlyGrid items={[["审计号", item.id], ["主体", item.actor], ["动作", item.action], ["对象", item.object], ["范围", item.scope], ["结果", item.result], ["Trace ID", item.trace], ["时间", item.time]]} /><h3 className="pm-drawer-subtitle">证据摘要</h3><ul className="pm-impact-list"><li>身份、角色、对象范围和策略版本已冻结。</li><li>请求哈希、结果码和关联审批可追溯。</li><li>未记录无必要的企业业务正文或凭证明文。</li></ul></>;
    case "support-detail": return <><ReadonlyGrid items={[["支持会话", item.id], ["企业", item.tenant], ["工单", item.ticket], ["授权范围", item.scope], ["操作人", item.operator], ["到期", item.expires], ["状态", item.status]]} /><ol className="pm-audit-chain"><li><span>10:12</span><strong>授权审批通过</strong><small>范围和字段白名单已冻结</small></li><li><span>10:18</span><strong>读取 Run 元数据</strong><small>Trace TR-782D · 未读取业务正文</small></li><li><span>到期自动</span><strong>撤销访问令牌</strong><small>后续请求失败关闭</small></li></ol></>;
    default: return null;
  }
}

function ActionDrawer({ action, onClose, onSubmit }) {
  const [title, submitLabel] = DRAWER_META[action.kind] || ["平台操作", null];
  const handleSubmit = (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget).entries());
    onSubmit(action.kind, action.item, values);
  };
  return (
    <div className="pm-overlay" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <aside className="pm-drawer" role="dialog" aria-modal="true" aria-labelledby="pm-drawer-title">
        <header><div><span>点联平台运营中心</span><h2 id="pm-drawer-title">{title}</h2></div><button autoFocus type="button" aria-label="关闭抽屉" onClick={onClose}><IconX size={20} /></button></header>
        <form onSubmit={handleSubmit}>
          <div className="pm-drawer-body"><DrawerContent action={action} /></div>
          <footer><button type="button" className="pm-button pm-button--secondary" onClick={onClose}>关闭</button>{submitLabel && <button type="submit" className="pm-button pm-button--primary">{submitLabel}</button>}</footer>
        </form>
      </aside>
    </div>
  );
}

const CONFIRM_META = {
  "tenant-freeze": { title: "确认变更租户状态", confirm: "确认执行", tone: "danger", description: "状态变更将影响登录、运行、检索与交付；账本和审计记录不会删除。" },
  "template-rollback": { title: "确认回滚模板发布", confirm: "确认回滚", tone: "danger", description: "只改变后续新实例可选版本；运行中任务和历史实例继续引用冻结版本。" },
  "skill-pause": { title: "确认变更技能状态", confirm: "确认执行", tone: "danger", description: "暂停后拒绝新调用，在途外部副作用按原幂等键查询结果，不盲目重试。" },
  "knowledge-stop": { title: "确认停用行业知识模板", confirm: "确认停用", tone: "danger", description: "阻止新企业派生；现有企业知识空间和自有文档不会被删除。" },
  "provider-pause": { title: "确认切换 Provider 熔断", confirm: "确认切换", tone: "danger", description: "系统将预览受影响模型、技能和租户，并把新流量切到兼容备用路由或显式阻断。" },
  "model-failover": { title: "确认切换模型备用路由", confirm: "切换备用路由", tone: "danger", description: "只影响后续 Attempt；能力、智点预估和预算上限将重新校验。" },
  "rate-activate": { title: "审批并激活费率", confirm: "审批激活", tone: "primary", description: "激活前再次校验区间冲突、币种和税口径；历史 Attempt 的成本快照不变。" },
  "multiplier-activate": { title: "审批并发布企业销售价格", confirm: "审批发布", tone: "primary", description: "生效后只影响新收费意图，不修改历史智点分录；大幅变价必须由第二审批人复核。" },
  "points-approve": { title: "审批智点发放并过账", confirm: "审批过账", tone: "primary", description: "系统将创建不可变账本事务与分录，并从批次重算余额；已过账记录不可编辑或删除。" },
  "usage-close": { title: "确认对账差异处置", confirm: "追加调整并关闭", tone: "primary", description: "差异处置将追加成本调整记录，不覆盖原 Provider Attempt、Usage 或 RateSnapshot。" },
  "run-takeover": { title: "确认接管失联 Run", confirm: "执行唯一接管", tone: "danger", description: "接管事务将递增 execution epoch、绑定新 Worker，并让旧 epoch 的下一次 Gateway 准入失败关闭。" },
  "run-write-barrier": { title: "保持副作用写屏障", confirm: "保持屏障并进入处置", tone: "danger", description: "外部结果未知时禁止重发、重复扣费和继续依赖步骤，直到对账或人工确认完成。" },
  "audit-revoke": { title: "确认撤销支持授权", confirm: "立即撤销", tone: "danger", description: "执行令牌将失效，后续读取失败关闭；已有审计记录保留。" },
};

function ConfirmModal({ confirmation, onClose, onConfirm }) {
  const meta = CONFIRM_META[confirmation.kind];
  return (
    <div className="pm-overlay pm-overlay--center" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="pm-confirm" role="alertdialog" aria-modal="true" aria-labelledby="pm-confirm-title">
        <span className={`pm-confirm__icon pm-confirm__icon--${meta.tone}`}><IconAlertTriangle size={25} /></span>
        <h2 id="pm-confirm-title">{meta.title}</h2><p>{meta.description}</p>
        <div className="pm-confirm__object"><span>操作对象</span><strong>{confirmation.item?.name || confirmation.item?.tenant || confirmation.item?.id}</strong></div>
        <footer><button autoFocus type="button" className="pm-button pm-button--secondary" onClick={onClose}>取消</button><button type="button" className={`pm-button ${meta.tone === "danger" ? "pm-button--danger" : "pm-button--primary"}`} onClick={onConfirm}>{meta.confirm}</button></footer>
      </section>
    </div>
  );
}

export function PlatformModules({ moduleKey = "tenants" }) {
  const resolvedKey = PLATFORM_MODULE_KEYS.includes(moduleKey) ? moduleKey : "tenants";
  const meta = MODULE_META[resolvedKey];
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("全部状态");
  const [lastUpdated, setLastUpdated] = useState("08-11 10:45");
  const [drawer, setDrawer] = useState(null);
  const [confirmation, setConfirmation] = useState(null);
  const [toast, setToast] = useState(null);
  const [tenants, setTenants] = useState(INITIAL_TENANTS);
  const [templates, setTemplates] = useState(INITIAL_TEMPLATES);
  const [skills, setSkills] = useState(INITIAL_SKILLS);
  const [knowledge, setKnowledge] = useState(INITIAL_KNOWLEDGE);
  const [providers, setProviders] = useState(INITIAL_PROVIDERS);
  const [models, setModels] = useState(INITIAL_MODELS);
  const [rates, setRates] = useState(INITIAL_RATES);
  const [multipliers, setMultipliers] = useState(INITIAL_MULTIPLIERS);
  const [pointAccounts, setPointAccounts] = useState(INITIAL_POINT_ACCOUNTS);
  const [pointTransactions, setPointTransactions] = useState(INITIAL_POINT_TRANSACTIONS);
  const [usageCalls, setUsageCalls] = useState(INITIAL_USAGE_CALLS);
  const [runtimeRuns, setRuntimeRuns] = useState(INITIAL_RUNTIME_RUNS);
  const [auditRows, setAuditRows] = useState(INITIAL_AUDIT_ROWS);
  const [supportSessions, setSupportSessions] = useState(INITIAL_SUPPORT_SESSIONS);

  useEffect(() => {
    setQuery("");
    setFilter("全部状态");
    setDrawer(null);
    setConfirmation(null);
  }, [resolvedKey]);

  useEffect(() => {
    if (!toast) return undefined;
    const timer = window.setTimeout(() => setToast(null), 3200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    if (!drawer && !confirmation) return undefined;
    const closeOnEscape = (event) => {
      if (event.key !== "Escape") return;
      setDrawer(null);
      setConfirmation(null);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [drawer, confirmation]);

  const metrics = useMemo(() => MODULE_METRICS[resolvedKey], [resolvedKey]);
  const notify = (message, tone = "success") => setToast({ message, tone });
  const openDrawer = (kind, item = null) => setDrawer({ kind, item });
  const openConfirm = (kind, item) => setConfirmation({ kind, item });
  const refresh = () => {
    const now = new Date();
    setLastUpdated(`${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")} ${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`);
    notify(`${meta.title}数据已刷新`);
  };

  const submitDrawer = (kind, item, values) => {
    const now = "08-11 11:06";
    if (kind === "tenant-create") setTenants((current) => [{ id: values.code, name: values.name, plan: values.plan, admins: 1, agents: 0, points: "0", status: "待开通", updated: now }, ...current]);
    if (kind === "template-create") setTemplates((current) => [{ id: `TPL-${String(current.length + 1).padStart(3, "0")}`, name: values.name, published: "—", candidate: values.version, acceptance: "待运行", tenants: 0, status: "草稿", updated: now }, ...current]);
    if (kind === "template-release") setTemplates((current) => current.map((row) => row.id === item.id ? { ...row, status: values.scope.includes("全量") ? "待审核" : `灰度中 ${values.scope.replace(" 灰度", "")}`, updated: now } : row));
    if (kind === "skill-register") setSkills((current) => [{ id: `SKL-${String(current.length + 1).padStart(3, "0")}`, name: values.name, version: values.version, risk: values.risk, calls: "0", error: "—", status: "审核中", updated: now }, ...current]);
    if (kind === "knowledge-create") setKnowledge((current) => [{ id: `IKT-${String(current.length + 1).padStart(3, "0")}`, name: values.name, version: values.version, documents: 0, score: "待评估", derived: 0, status: "草稿", updated: now }, ...current]);
    if (kind === "knowledge-evaluate") setKnowledge((current) => current.map((row) => row.id === item.id ? { ...row, status: "评估中", updated: now } : row));
    if (kind === "provider-connect") setProviders((current) => [{ id: values.id, name: values.name, capability: values.capability, region: values.region, uptime: "待验证", p95: "—", credential: values.credential, status: "待验证" }, ...current]);
    if (kind === "model-register") setModels((current) => [{ id: values.id, name: values.name, provider: values.provider, providerModel: values.providerModel, modality: values.modality, context: values.context, route: "待验证", health: "待验证" }, ...current]);
    if (kind === "rate-create") setRates((current) => [{ id: `RATE-${Date.now().toString().slice(-6)}`, provider: values.provider, meter: values.meter, price: `¥${Number(values.price).toFixed(4)} / 单位`, currency: values.currency, tax: values.tax, effective: values.effective, status: "待审批" }, ...current]);
    if (kind === "multiplier-create") setMultipliers((current) => [{ id: `SELL-${Date.now().toString().slice(-6)}`, scope: values.scope, resource: values.resource, multiplier: `${Number(values.multiplier).toFixed(2)}×`, affected: values.scope === "全部企业" ? 126 : 24, effective: values.effective, status: "待审批" }, ...current]);
    if (kind === "point-grant") setPointTransactions((current) => [{ id: `PTX-${Date.now().toString().slice(-8)}`, tenant: values.tenant, type: "发放", amount: Number(values.amount), batch: values.batch, creator: "当前账务操作人", approver: values.approver, status: "待审批", time: now }, ...current]);
    if (kind === "usage-import") notify(`${values.provider} ${values.period} 账单已校验导入，差异行已进入责任队列`);
    if (kind === "audit-support") setSupportSessions((current) => [{ id: `SUP-${Date.now().toString().slice(-8)}`, tenant: values.tenant, ticket: values.ticket, scope: values.scope, expires: values.duration, operator: "待审批", status: "待审批" }, ...current]);
    if (kind === "provider-policy" || kind === "monitor-policy") notify("策略草稿已保存，发布前仍需审批和故障演练");
    if (!["usage-import", "provider-policy", "monitor-policy"].includes(kind)) notify(`${DRAWER_META[kind]?.[0] || "平台操作"}已提交`);
    setDrawer(null);
  };

  const applyConfirmation = () => {
    const { kind, item } = confirmation;
    if (kind === "tenant-freeze") setTenants((current) => current.map((row) => row.id === item.id ? { ...row, status: row.status === "冻结" ? "正常" : "冻结", updated: "08-11 11:08" } : row));
    if (kind === "template-rollback") setTemplates((current) => current.map((row) => row.id === item.id ? { ...row, candidate: row.published, status: "已回滚", updated: "08-11 11:08" } : row));
    if (kind === "skill-pause") setSkills((current) => current.map((row) => row.id === item.id ? { ...row, status: row.status === "暂停" ? "灰度" : "暂停", updated: "08-11 11:08" } : row));
    if (kind === "knowledge-stop") setKnowledge((current) => current.map((row) => row.id === item.id ? { ...row, status: "已停用", updated: "08-11 11:08" } : row));
    if (kind === "provider-pause") setProviders((current) => current.map((row) => row.id === item.id ? { ...row, status: row.status === "熔断" ? "观察" : "熔断" } : row));
    if (kind === "model-failover") setModels((current) => current.map((row) => row.id === item.id ? { ...row, route: "备用路由", health: "观察" } : row));
    if (kind === "rate-activate") setRates((current) => current.map((row) => row.id === item.id ? { ...row, status: "已生效" } : row));
    if (kind === "multiplier-activate") setMultipliers((current) => current.map((row) => row.id === item.id ? { ...row, status: "待生效" } : row));
    if (kind === "points-approve") {
      setPointTransactions((current) => current.map((row) => row.id === item.id ? { ...row, status: "已过账", approver: "当前审批人" } : row));
      setPointAccounts((current) => current.map((row) => row.tenant === item.tenant ? { ...row, available: row.available + item.amount } : row));
    }
    if (kind === "usage-close") setUsageCalls((current) => current.map((row) => row.id === item.id ? { ...row, status: "已确认", cost: "¥0.45" } : row));
    if (kind === "run-takeover") setRuntimeRuns((current) => current.map((row) => row.id === item.id ? { ...row, worker: "py-worker-08", epoch: row.epoch + 1, heartbeat: "刚刚", status: "运行中" } : row));
    if (kind === "audit-revoke") setSupportSessions((current) => current.map((row) => row.id === item.id ? { ...row, status: "已撤销" } : row));
    setAuditRows((current) => [{ id: `AUD-${Date.now().toString().slice(-7)}`, actor: "当前平台操作人", action: CONFIRM_META[kind].title, object: item.id || item.name || item.tenant, scope: item.tenant || "平台配置", result: "允许", trace: `TR-${Date.now().toString().slice(-5)}`, time: "08-11 11:08" }, ...current]);
    notify(`${CONFIRM_META[kind].title}已完成`);
    setConfirmation(null);
  };

  const common = { query, setQuery, filter, setFilter, openDrawer, openConfirm };
  let view;
  if (resolvedKey === "tenants") view = <TenantsView {...common} rows={tenants} />;
  if (resolvedKey === "agent-templates") view = <TemplatesView {...common} rows={templates} />;
  if (resolvedKey === "skills") view = <SkillsView {...common} rows={skills} />;
  if (resolvedKey === "industry-knowledge") view = <KnowledgeView {...common} rows={knowledge} />;
  if (resolvedKey === "providers") view = <ProvidersView {...common} rows={providers} />;
  if (resolvedKey === "models") view = <ModelsView {...common} rows={models} onTest={(model) => notify(`${model.name} 连通测试通过，Attempt 已记录`, "info")} />;
  if (resolvedKey === "rates") view = <RatesView {...common} rows={rates} />;
  if (resolvedKey === "multipliers") view = <MultipliersView {...common} rows={multipliers} />;
  if (resolvedKey === "points") view = <PointsView {...common} accounts={pointAccounts} transactions={pointTransactions} />;
  if (resolvedKey === "usage") view = <UsageView {...common} rows={usageCalls} />;
  if (resolvedKey === "monitoring") view = <MonitoringView {...common} services={INITIAL_RUNTIME_SERVICES} runs={runtimeRuns} />;
  if (resolvedKey === "audit") view = <AuditView {...common} rows={auditRows} sessions={supportSessions} />;

  return (
    <main className="platform-modules" data-module-key={resolvedKey}>
      <ModuleHeader meta={meta} lastUpdated={lastUpdated} onPrimaryAction={() => openDrawer(meta.actionKind)} onRefresh={refresh} />
      <MetricGrid metrics={metrics} />
      {view}
      {drawer && <ActionDrawer action={drawer} onClose={() => setDrawer(null)} onSubmit={submitDrawer} />}
      {confirmation && <ConfirmModal confirmation={confirmation} onClose={() => setConfirmation(null)} onConfirm={applyConfirmation} />}
      {toast && <div className={`pm-toast pm-toast--${toast.tone}`} role="status"><IconCircleCheck size={18} /><span>{toast.message}</span><button type="button" aria-label="关闭提示" onClick={() => setToast(null)}><IconX size={16} /></button></div>}
    </main>
  );
}

export default PlatformModules;
