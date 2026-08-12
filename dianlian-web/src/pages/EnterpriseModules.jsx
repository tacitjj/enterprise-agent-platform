import { useEffect, useMemo, useRef, useState } from "react";
import {
  IconActivity,
  IconAdjustments,
  IconAlertTriangle,
  IconBell,
  IconBook2,
  IconBrain,
  IconBuildingSkyscraper,
  IconCheck,
  IconChevronDown,
  IconChevronRight,
  IconCircleCheck,
  IconCoin,
  IconDatabase,
  IconDeviceDesktopAnalytics,
  IconEye,
  IconFileAnalytics,
  IconFileDescription,
  IconFilter,
  IconHistory,
  IconKey,
  IconLock,
  IconMessages,
  IconPencil,
  IconPlayerPause,
  IconPlayerPlay,
  IconPlus,
  IconRefresh,
  IconSearch,
  IconSettings,
  IconShieldCheck,
  IconTools,
  IconUpload,
  IconUserPlus,
  IconUsers,
  IconUsersGroup,
  IconX,
} from "@tabler/icons-react";
import "./enterprise-modules.css";

const MODULE_META = {
  agents: { label: "员工实例", title: "数字员工", description: "招聘、定制并治理企业内的数字员工实例。", icon: IconUsers },
  knowledge: { label: "企业知识", title: "企业知识", description: "管理文档版本、解析状态、引用范围与检索权限。", icon: IconBook2 },
  memory: { label: "记忆治理", title: "记忆治理", description: "确认长期记忆候选，处理冲突、纠错与遗忘请求。", icon: IconBrain },
  tools: { label: "技能与工具", title: "技能与工具", description: "按员工与项目范围授权可调用的企业工具。", icon: IconTools },
  models: { label: "模型策略", title: "模型策略", description: "配置能力路由、备用模型、限额与受控降级。", icon: IconSettings },
  org: { label: "部门与成员", title: "部门与成员", description: "维护组织、角色及员工和数据的可见边界。", icon: IconUsersGroup },
  groups: { label: "群聊治理", title: "群聊治理", description: "控制群内可用员工、历史策略、资料范围与费用归属。", icon: IconMessages },
  approvals: { label: "审批中心", title: "审批中心", description: "集中处理合同、报价、视觉成果和权限审批。", icon: IconShieldCheck },
  points: { label: "智点与费用", title: "智点、预算与费用", description: "查看额度、预算、预占、实扣、释放和调用级费用。", icon: IconCoin },
  tasks: { label: "任务监控", title: "任务监控", description: "按任务、Run、步骤和异常查看真实执行状态。", icon: IconActivity },
  audit: { label: "异常与审计", title: "异常与审计", description: "追踪授权、配置、调用和人工决策的完整证据。", icon: IconFileAnalytics },
};

export const ENTERPRISE_MODULE_KEYS = Object.freeze(Object.keys(MODULE_META));

const NAV_GROUPS = [
  { label: "数字员工", keys: ["agents", "tools"] },
  { label: "知识与记忆", keys: ["knowledge", "memory"] },
  { label: "组织与协作", keys: ["org", "groups", "approvals"] },
  { label: "模型与智点", keys: ["models", "points"] },
  { label: "运营治理", keys: ["tasks", "audit"] },
];

const EMPLOYEE_TEMPLATES = [
  {
    id: "graphic",
    name: "平面出图专员",
    role: "品牌视觉与多尺寸物料",
    image: "/assets/employees/graphic-designer.png",
    tone: "blue",
    skills: ["主视觉生成", "局部修改", "多尺寸派生"],
    knowledge: "品牌规范、项目素材、渠道尺寸规则",
    model: "视觉创作路由",
  },
  {
    id: "contract",
    name: "法务合同审核专员",
    role: "条款定位、风险分级与修订建议",
    image: "/assets/employees/contract-reviewer.png",
    tone: "amber",
    skills: ["合同解析", "风险分级", "修订建议"],
    knowledge: "标准条款、历史合同、法务处理口径",
    model: "严谨审查路由",
  },
  {
    id: "quotation",
    name: "报价专员",
    role: "历史关联、成本测算与价格审批",
    image: "/assets/employees/quotation-specialist.png",
    tone: "cyan",
    skills: ["历史匹配", "规则测算", "内外版报价"],
    knowledge: "历史项目、供应成本、报价规则",
    model: "结构化推理路由",
  },
];

const INITIAL_AGENTS = [
  { id: "agent-01", name: "平面出图专员", department: "市场部", status: "运行中", tone: "success", model: "视觉创作路由", tasks: 8, points: 1240, version: "v2.4.1", scope: "市场部项目", image: EMPLOYEE_TEMPLATES[0].image },
  { id: "agent-02", name: "法务合同审核专员", department: "法务部", status: "等待确认", tone: "warning", model: "严谨审查路由", tasks: 5, points: 680, version: "v2.2.0", scope: "法务部合同", image: EMPLOYEE_TEMPLATES[1].image },
  { id: "agent-03", name: "报价专员", department: "商务部", status: "空闲", tone: "neutral", model: "结构化推理路由", tasks: 6, points: 910, version: "v2.1.3", scope: "已授权项目", image: EMPLOYEE_TEMPLATES[2].image },
];

const INITIAL_DOCUMENTS = [
  { id: "doc-01", name: "点联品牌规范 v3.2", type: "PDF", space: "品牌资产", scope: "市场部 · 平面出图专员", version: "v3.2", status: "可用", tone: "success", chunks: 86, updated: "今天 09:18" },
  { id: "doc-02", name: "场馆服务合同标准条款", type: "DOCX", space: "法务知识", scope: "法务部 · 合同审核专员", version: "v5.0", status: "可用", tone: "success", chunks: 128, updated: "昨天 16:42" },
  { id: "doc-03", name: "历史项目与成本资料 2026-Q2", type: "XLSX", space: "报价依据", scope: "商务部 · 报价专员", version: "v2.6", status: "索引中", tone: "info", chunks: 642, updated: "8 分钟前", progress: 72 },
  { id: "doc-04", name: "供应商价格表 2026-Q3", type: "XLSX", space: "报价依据", scope: "商务部负责人", version: "v1.0", status: "待确认", tone: "warning", chunks: 214, updated: "32 分钟前" },
];

const INITIAL_APPROVALS = [
  { id: "AP-260811-018", type: "合同高风险确认", title: "场馆服务合同 · 付款与违约条款", owner: "法务合同审核专员", requester: "林悦", department: "法务部", risk: "高风险", tone: "danger", points: 180, status: "待我审批", created: "今天 09:18", evidence: "合同 v3、标准条款 v5、3 项高风险定位" },
  { id: "AP-260811-017", type: "报价例外审批", title: "工商银行展台项目 · 报价 v2", owner: "报价专员", requester: "周航", department: "商务部", risk: "中风险", tone: "warning", points: 210, status: "待我审批", created: "今天 09:12", evidence: "4 个历史案例、成本快照 Q2、报价规则 v8.4" },
  { id: "AP-260811-016", type: "视觉成果确认", title: "夏季展会主视觉 · 候选方案 B", owner: "平面出图专员", requester: "陈曦", department: "市场部", risk: "低风险", tone: "info", points: 320, status: "待我审批", created: "今天 08:56", evidence: "品牌规范 v3.2、版权检查、3 个输出规格" },
  { id: "AP-260810-041", type: "知识权限变更", title: "供应商价格表扩大至商务负责人", owner: "知识管理员", requester: "赵楠", department: "商务部", risk: "中风险", tone: "warning", points: 0, status: "已通过", created: "昨天 17:30", evidence: "ACL 版本 18 → 19、审批人陈曦" },
];

const INITIAL_TASKS = [
  { id: "TK-260811-031", title: "夏季展会主视觉", agent: "平面出图专员", department: "市场部", status: "执行中", tone: "info", step: "生成候选预览", progress: 46, run: "Run 1", points: "320 / 600", updated: "2 分钟前" },
  { id: "TK-260811-026", title: "场馆服务合同审查", agent: "法务合同审核专员", department: "法务部", status: "等待确认", tone: "warning", step: "法务人工确认", progress: 82, run: "Run 1", points: "180 / 300", updated: "5 分钟前" },
  { id: "TK-260811-024", title: "工商银行展台项目报价", agent: "报价专员", department: "商务部", status: "待审批", tone: "warning", step: "价格人工审批", progress: 88, run: "Run 1", points: "210 / 350", updated: "8 分钟前" },
  { id: "TK-260811-019", title: "供应商价格表解析", agent: "报价专员", department: "商务部", status: "异常", tone: "danger", step: "表格结构确认", progress: 38, run: "Run 2", points: "95 / 220", updated: "21 分钟前" },
];

const MEMORY_CANDIDATES = [
  { id: "mem-01", subject: "陈曦 × 平面出图专员", content: "展会视觉默认采用明亮蓝色，避免紫色与游戏化装饰。", source: "夏季展会主视觉任务", scope: "个人 × 员工", confidence: "高", status: "待确认" },
  { id: "mem-02", subject: "工商银行项目群 × 报价专员", content: "同客户项目优先关联近两年同城市、同面积案例。", source: "项目群消息与报价 v2", scope: "群聊 × 员工", confidence: "中", status: "待确认" },
  { id: "mem-03", subject: "法务部 × 合同审核专员", content: "场馆合同付款周期超过 30 个工作日需列为中风险。", source: "企业法务处理记录", scope: "部门 × 员工", confidence: "高", status: "已确认" },
];

const TOOL_ROWS = [
  { id: "tool-01", name: "企业文件读取", provider: "点联内置", scope: "任务授权文件", agents: "3 位员工", status: true, risk: "低" },
  { id: "tool-02", name: "视觉渲染器", provider: "图像服务集群", scope: "市场部项目", agents: "平面出图专员", status: true, risk: "中" },
  { id: "tool-03", name: "报价规则引擎", provider: "企业私有服务", scope: "商务部已授权项目", agents: "报价专员", status: true, risk: "中" },
  { id: "tool-04", name: "合同文档解析", provider: "点联内置", scope: "法务知识空间", agents: "合同审核专员", status: true, risk: "低" },
];

const LEDGER_ROWS = [
  { id: "LE-083105", time: "09:26:18", source: "夏季展会主视觉", capability: "图像生成", kind: "实扣", amount: -280, balance: 48620, trace: "call-98F21" },
  { id: "LE-083104", time: "09:18:42", source: "场馆服务合同审查", capability: "合同审核", kind: "实扣", amount: -100, balance: 48900, trace: "call-98E77" },
  { id: "LE-083103", time: "09:12:07", source: "工商银行展台报价", capability: "报价测算", kind: "预占", amount: -140, balance: 49000, trace: "resv-98D42" },
  { id: "LE-083102", time: "08:56:31", source: "夏季展会主视觉", capability: "图像生成", kind: "释放", amount: 80, balance: 49140, trace: "resv-98B19" },
];

const AUDIT_ROWS = [
  { id: "AU-94218", time: "09:28:14", actor: "陈曦", action: "审批报价版本", object: "报价 v2 / AP-260811-017", result: "成功", tone: "success", ip: "10.20.18.46" },
  { id: "AU-94217", time: "09:24:02", actor: "系统", action: "Run 租约接管", object: "TK-260811-019 / Run 2", result: "已接管", tone: "warning", ip: "runtime-worker-03" },
  { id: "AU-94216", time: "09:18:43", actor: "法务合同审核专员", action: "读取知识片段", object: "企业条款库 v5 / 6 段", result: "允许", tone: "success", ip: "ai-runtime" },
  { id: "AU-94215", time: "09:15:27", actor: "周航", action: "请求扩大文档权限", object: "供应商价格表 2026-Q3", result: "等待审批", tone: "info", ip: "10.20.22.15" },
  { id: "AU-94214", time: "09:11:09", actor: "未知成员", action: "访问法务合同正文", object: "场馆服务合同-v3.pdf", result: "已拒绝", tone: "danger", ip: "10.20.31.08" },
];

function StatusTag({ tone = "neutral", children }) {
  return <span className={`dlm-status dlm-status--${tone}`}>{children}</span>;
}

function MetricStrip({ items }) {
  return (
    <section className="dlm-metrics">
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <article key={item.label}>
            <span className={`dlm-metric-icon dlm-metric-icon--${item.tone ?? "blue"}`}><Icon size={20} /></span>
            <div><small>{item.label}</small><strong>{item.value}</strong><p>{item.note}</p></div>
          </article>
        );
      })}
    </section>
  );
}

function Panel({ title, description, action, children, className = "" }) {
  return (
    <section className={`dlm-panel ${className}`.trim()}>
      <header className="dlm-panel-header">
        <div><h2>{title}</h2>{description ? <p>{description}</p> : null}</div>
        {action}
      </header>
      {children}
    </section>
  );
}

function SearchBox({ value, onChange, placeholder = "搜索" }) {
  return <label className="dlm-search"><IconSearch size={17} /><input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} /></label>;
}

function AgentsModule({ agents, onRecruit, openDrawer }) {
  const [query, setQuery] = useState("");
  const [view, setView] = useState("instances");
  const visibleAgents = useMemo(() => agents.filter((agent) => `${agent.name}${agent.department}${agent.model}`.includes(query)), [agents, query]);
  return (
    <>
      <MetricStrip items={[
        { label: "在岗员工", value: agents.length, note: "覆盖 3 个核心能力", icon: IconUsers },
        { label: "今日运行任务", value: "19", note: "8 个正在执行", icon: IconActivity, tone: "cyan" },
        { label: "等待人工处理", value: "5", note: "合同 3 · 报价 1 · 视觉 1", icon: IconShieldCheck, tone: "amber" },
        { label: "今日消耗", value: "2,830", note: "智点 · 较昨日 -8.2%", icon: IconCoin, tone: "green" },
      ]} />
      <div className="dlm-toolbar">
        <div className="dlm-tabs"><button className={view === "instances" ? "is-active" : ""} type="button" onClick={() => setView("instances")}>员工实例</button><button className={view === "templates" ? "is-active" : ""} type="button" onClick={() => setView("templates")}>可招聘模板</button></div>
        <SearchBox value={query} onChange={setQuery} placeholder="搜索员工、部门或模型" />
        <button className="dlm-primary" type="button" onClick={() => onRecruit()}><IconUserPlus size={17} /> 招聘并定制</button>
      </div>
      {view === "templates" ? (
        <div className="dlm-template-grid">
          {EMPLOYEE_TEMPLATES.map((template) => (
            <article className={`dlm-template-card dlm-template-card--${template.tone}`} key={template.id}>
              <img src={template.image} alt={template.name} />
              <div><span className="dlm-template-kind">官方岗位模板</span><h2>{template.name}</h2><p>{template.role}</p><div className="dlm-chip-row">{template.skills.map((skill) => <span key={skill}>{skill}</span>)}</div><dl><div><dt>默认知识</dt><dd>{template.knowledge}</dd></div><div><dt>模型策略</dt><dd>{template.model}</dd></div></dl><button type="button" onClick={() => onRecruit(template.id)}>选择此模板 <IconChevronRight size={16} /></button></div>
            </article>
          ))}
        </div>
      ) : (
        <Panel title="企业员工实例" description="员工实例与官方模板版本分离，企业配置独立生效。">
          <div className="dlm-table dlm-agent-table">
            <div className="dlm-table-head"><span>数字员工</span><span>部门 / 范围</span><span>模型策略</span><span>当前状态</span><span>今日任务</span><span>今日智点</span><span>操作</span></div>
            {visibleAgents.map((agent) => <div className="dlm-table-row" key={agent.id}><div className="dlm-person"><img src={agent.image} alt="" /><span><strong>{agent.name}</strong><small>模板 {agent.version}</small></span></div><span><strong>{agent.department}</strong><small>{agent.scope}</small></span><span>{agent.model}</span><StatusTag tone={agent.tone}>{agent.status}</StatusTag><strong>{agent.tasks}</strong><strong>{agent.points.toLocaleString()}</strong><button className="dlm-link" type="button" onClick={() => openDrawer("agent", agent.id)}>配置与运行 <IconChevronRight size={15} /></button></div>)}
          </div>
        </Panel>
      )}
    </>
  );
}

function KnowledgeModule({ documents, openModal, openDrawer }) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("全部状态");
  const visible = documents.filter((doc) => `${doc.name}${doc.space}${doc.scope}`.includes(query) && (status === "全部状态" || doc.status === status));
  return (
    <>
      <MetricStrip items={[
        { label: "知识空间", value: "6", note: "4 个部门空间 · 2 个项目空间", icon: IconDatabase },
        { label: "有效文档", value: "1,284", note: "今日新增 18 个版本", icon: IconFileDescription, tone: "cyan" },
        { label: "处理中", value: documents.filter((doc) => doc.status === "索引中").length, note: "解析、切分与索引可追踪", icon: IconRefresh, tone: "amber" },
        { label: "待确认权限", value: "3", note: "均需数据 Owner 审批", icon: IconLock, tone: "green" },
      ]} />
      <div className="dlm-toolbar"><SearchBox value={query} onChange={setQuery} placeholder="搜索文档、知识空间或授权范围" /><label className="dlm-select"><IconFilter size={16} /><select value={status} onChange={(event) => setStatus(event.target.value)}><option>全部状态</option><option>可用</option><option>索引中</option><option>待确认</option></select></label><button className="dlm-secondary" type="button" onClick={() => openDrawer("knowledge-policy")}><IconKey size={17} /> 权限策略</button><button className="dlm-primary" type="button" onClick={() => openModal("upload")}><IconUpload size={17} /> 上传知识</button></div>
      <Panel title="知识文档与版本" description="检索前先鉴权，正文、引用和附件保持同一受众边界。">
        <div className="dlm-table dlm-document-table"><div className="dlm-table-head"><span>文档</span><span>知识空间</span><span>授权范围</span><span>版本</span><span>处理状态</span><span>索引规模</span><span>操作</span></div>{visible.map((doc) => <div className="dlm-table-row" key={doc.id}><div className="dlm-doc"><span>{doc.type}</span><div><strong>{doc.name}</strong><small>更新于 {doc.updated}</small></div></div><span>{doc.space}</span><span>{doc.scope}</span><strong>{doc.version}</strong><div>{doc.progress ? <div className="dlm-progress"><i style={{ width: `${doc.progress}%` }} /><small>{doc.progress}%</small></div> : <StatusTag tone={doc.tone}>{doc.status}</StatusTag>}</div><strong>{doc.chunks} 段</strong><div className="dlm-row-actions"><button type="button" onClick={() => openDrawer("document", doc.id)}>查看</button><button type="button" onClick={() => openDrawer("document-permission", doc.id)}>权限</button></div></div>)}</div>
      </Panel>
    </>
  );
}

function MemoryModule({ notify, openDrawer }) {
  const [rows, setRows] = useState(MEMORY_CANDIDATES);
  const decide = (id, nextStatus) => { setRows((items) => items.map((item) => item.id === id ? { ...item, status: nextStatus } : item)); notify(nextStatus === "已确认" ? "记忆已确认并写入对应作用域" : "候选已忽略，不会写入长期记忆"); };
  return <><MetricStrip items={[{ label: "待确认候选", value: rows.filter((item) => item.status === "待确认").length, note: "确认后才写入长期记忆", icon: IconBrain }, { label: "有效长期记忆", value: "286", note: "个人、群、项目严格隔离", icon: IconDatabase, tone: "cyan" }, { label: "冲突待处理", value: "4", note: "新旧偏好或事实不一致", icon: IconAlertTriangle, tone: "amber" }, { label: "本月遗忘完成", value: "18", note: "删除记录与向量均已对齐", icon: IconCircleCheck, tone: "green" }]} /><div className="dlm-two-column"><Panel title="记忆候选确认" description="候选来源、作用域和证据必须可回看。"><div className="dlm-memory-list">{rows.map((item) => <article key={item.id}><div className="dlm-memory-top"><StatusTag tone={item.status === "待确认" ? "warning" : "success"}>{item.status}</StatusTag><span>{item.scope}</span><small>置信度 {item.confidence}</small></div><h3>{item.subject}</h3><p>{item.content}</p><footer><span>来源：{item.source}</span><div>{item.status === "待确认" ? <><button type="button" onClick={() => decide(item.id, "已忽略")}>忽略</button><button className="is-primary" type="button" onClick={() => decide(item.id, "已确认")}>确认写入</button></> : <button type="button" onClick={() => openDrawer("memory", item.id)}>查看审计</button>}</div></footer></article>)}</div></Panel><Panel title="写入与召回策略" description="默认最小作用域，私人记忆不得进入群聊。"><div className="dlm-policy-list">{[["长期记忆先确认再写入", true], ["群聊仅召回群与项目记忆", true], ["相似偏好自动合并", false], ["过期事实进入复核队列", true]].map(([label, enabled]) => <PolicyToggle key={label} label={label} initial={enabled} notify={notify} />)}</div><button className="dlm-wide-action" type="button" onClick={() => openDrawer("memory-policy")}><IconAdjustments size={17} /> 查看作用域与冲突规则</button></Panel></div></>;
}

function PolicyToggle({ label, initial, notify }) {
  const [enabled, setEnabled] = useState(initial);
  return <button type="button" className="dlm-policy-toggle" onClick={() => { setEnabled((value) => !value); notify(`${label}已${enabled ? "关闭" : "开启"}`); }}><span><strong>{label}</strong><small>{enabled ? "规则已启用" : "规则已停用"}</small></span><i className={enabled ? "is-on" : ""}><b /></i></button>;
}

function ToolsModule({ notify, openDrawer }) {
  const [tools, setTools] = useState(TOOL_ROWS);
  const toggle = (id) => setTools((rows) => rows.map((tool) => tool.id === id ? { ...tool, status: !tool.status } : tool));
  return <><MetricStrip items={[{ label: "已接入工具", value: tools.length, note: "均经过企业级授权", icon: IconTools }, { label: "今日调用", value: "1,486", note: "成功率 99.4%", icon: IconActivity, tone: "cyan" }, { label: "高风险授权", value: "0", note: "外部写操作需二次审批", icon: IconShieldCheck, tone: "green" }, { label: "授权即将过期", value: "2", note: "未来 7 天", icon: IconHistory, tone: "amber" }]} /><Panel title="技能与工具授权" description="授权限定员工、资料、项目和有效期，不赋予无限调用权。" action={<button className="dlm-primary" type="button" onClick={() => openDrawer("tool-connect")}><IconPlus size={16} /> 接入工具</button>}><div className="dlm-table dlm-tool-table"><div className="dlm-table-head"><span>工具</span><span>Provider</span><span>数据范围</span><span>可用员工</span><span>风险</span><span>授权状态</span><span>操作</span></div>{tools.map((tool) => <div className="dlm-table-row" key={tool.id}><div className="dlm-icon-name"><span><IconTools size={17} /></span><strong>{tool.name}</strong></div><span>{tool.provider}</span><span>{tool.scope}</span><span>{tool.agents}</span><StatusTag tone={tool.risk === "中" ? "warning" : "success"}>{tool.risk}风险</StatusTag><button className="dlm-switch-button" type="button" onClick={() => { toggle(tool.id); notify(`${tool.name}已${tool.status ? "停用" : "启用"}`); }}><i className={tool.status ? "is-on" : ""}><b /></i>{tool.status ? "已启用" : "已停用"}</button><button className="dlm-link" type="button" onClick={() => openDrawer("tool", tool.id)}>查看授权</button></div>)}</div></Panel></>;
}

function ModelsModule({ notify, openDrawer }) {
  const [guardrail, setGuardrail] = useState(true);
  return <><MetricStrip items={[{ label: "模型路由", value: "3", note: "对应首批三类能力", icon: IconSettings }, { label: "今日模型调用", value: "1,204", note: "P95 2.8 秒", icon: IconActivity, tone: "cyan" }, { label: "受控降级", value: "2", note: "近 24 小时", icon: IconRefresh, tone: "amber" }, { label: "预算保护", value: guardrail ? "已开启" : "已关闭", note: "超限前停止新调用", icon: IconShieldCheck, tone: "green" }]} /><div className="dlm-two-column dlm-model-layout"><Panel title="能力路由策略" description="主模型、备用模型和成本上限按能力分别配置。"><div className="dlm-route-list">{EMPLOYEE_TEMPLATES.map((template, index) => <article key={template.id}><img src={template.image} alt="" /><div><strong>{template.name}</strong><small>{template.model}</small></div><span>主：{["视觉模型 A", "文本模型 B", "推理模型 C"][index]}</span><span>备：{["视觉模型 D", "文本模型 E", "推理模型 B"][index]}</span><button type="button" onClick={() => openDrawer("model", template.id)}>编辑路由</button></article>)}</div></Panel><Panel title="企业模型护栏" description="费用、延迟和安全阈值在调用前生效。"><div className="dlm-policy-list"><PolicyToggle label="任务费用超过上限前请求确认" initial notify={notify} /><PolicyToggle label="Provider 异常时允许同等级降级" initial notify={notify} /><PolicyToggle label="敏感资料禁止发送至非白名单模型" initial notify={notify} /><button type="button" className="dlm-policy-toggle" onClick={() => { setGuardrail((value) => !value); notify(`企业预算保护已${guardrail ? "关闭" : "开启"}`); }}><span><strong>企业总预算保护</strong><small>{guardrail ? "剩余 10% 时阻止新任务" : "当前未启用"}</small></span><i className={guardrail ? "is-on" : ""}><b /></i></button></div></Panel></div></>;
}

function OrgModule({ openModal, openDrawer }) {
  const departments = [{ name: "市场部", members: 18, agents: 1, spaces: 2, owner: "林悦" }, { name: "法务部", members: 8, agents: 1, spaces: 2, owner: "陈曦" }, { name: "商务部", members: 24, agents: 1, spaces: 2, owner: "周航" }, { name: "管理层", members: 6, agents: 3, spaces: 6, owner: "赵楠" }];
  return <><MetricStrip items={[{ label: "企业成员", value: "56", note: "4 个部门", icon: IconUsers }, { label: "企业角色", value: "8", note: "最小权限组合", icon: IconKey, tone: "cyan" }, { label: "数据 Owner", value: "12", note: "知识与项目分别负责", icon: IconShieldCheck, tone: "green" }, { label: "待处理邀请", value: "3", note: "24 小时内到期", icon: IconUserPlus, tone: "amber" }]} /><Panel title="组织与数据边界" description="部门关系不自动等于数据权限，所有授权均需明确作用域。" action={<button className="dlm-primary" type="button" onClick={() => openModal("member")}><IconUserPlus size={16} /> 添加成员</button>}><div className="dlm-department-grid">{departments.map((dept) => <button type="button" key={dept.name} onClick={() => openDrawer("department", dept.name)}><span className="dlm-department-icon"><IconBuildingSkyscraper size={21} /></span><div><strong>{dept.name}</strong><small>负责人 {dept.owner}</small></div><dl><div><dt>成员</dt><dd>{dept.members}</dd></div><div><dt>数字员工</dt><dd>{dept.agents}</dd></div><div><dt>知识空间</dt><dd>{dept.spaces}</dd></div></dl><IconChevronRight size={17} /></button>)}</div></Panel></>;
}

function GroupsModule({ openDrawer }) {
  const groups = [{ id: "group-01", name: "工商银行展台项目组", members: 8, agents: "3 位", mode: "默认单员工", history: "入群后可见", scope: "项目知识", cost: "项目预算", status: "活跃" }, { id: "group-02", name: "市场创意协作群", members: 14, agents: "1 位", mode: "默认单员工", history: "最近 30 天", scope: "市场部知识", cost: "市场部预算", status: "活跃" }, { id: "group-03", name: "法务合同评审群", members: 6, agents: "1 位", mode: "默认单员工", history: "不开放历史", scope: "法务部知识", cost: "法务部预算", status: "受控" }];
  return <><MetricStrip items={[{ label: "受管群聊", value: groups.length, note: "全部为企业内部群", icon: IconMessages }, { label: "今日点名调用", value: "42", note: "普通消息 316 条未调用模型", icon: IconActivity, tone: "cyan" }, { label: "多员工协作", value: "6", note: "主责汇总 2 次", icon: IconUsersGroup, tone: "green" }, { label: "权限拦截", value: "3", note: "均未投递正文", icon: IconLock, tone: "amber" }]} /><Panel title="群聊治理" description="目标、模式和主责不明确时必须由用户选择，员工不得无限互聊。"><div className="dlm-table dlm-group-table"><div className="dlm-table-head"><span>协作群</span><span>成员 / 员工</span><span>默认模式</span><span>历史策略</span><span>知识范围</span><span>费用归属</span><span>操作</span></div>{groups.map((group) => <div className="dlm-table-row" key={group.id}><div><strong>{group.name}</strong><small><StatusTag tone={group.status === "活跃" ? "success" : "warning"}>{group.status}</StatusTag></small></div><span>{group.members} 人 · {group.agents}</span><span>{group.mode}</span><span>{group.history}</span><span>{group.scope}</span><span>{group.cost}</span><button className="dlm-link" type="button" onClick={() => openDrawer("group", group.id)}>治理设置</button></div>)}</div></Panel></>;
}

function ApprovalsModule({ approvals, setApprovals, openDrawer, notify }) {
  const [tab, setTab] = useState("pending");
  const visible = approvals.filter((item) => tab === "pending" ? item.status === "待我审批" : item.status !== "待我审批");
  const decide = (id, status) => { setApprovals((rows) => rows.map((item) => item.id === id ? { ...item, status } : item)); notify(status === "已通过" ? "当前成果版本已通过审批" : "审批已退回，任务将生成新版本"); };
  return <><MetricStrip items={[{ label: "待我审批", value: approvals.filter((item) => item.status === "待我审批").length, note: "高风险 1 · 中风险 1", icon: IconShieldCheck }, { label: "今日已处理", value: "12", note: "平均用时 18 分钟", icon: IconCircleCheck, tone: "green" }, { label: "即将超时", value: "2", note: "未来 2 小时", icon: IconHistory, tone: "amber" }, { label: "退回率", value: "8.3%", note: "近 30 天", icon: IconRefresh, tone: "cyan" }]} /><div className="dlm-toolbar"><div className="dlm-tabs"><button type="button" className={tab === "pending" ? "is-active" : ""} onClick={() => setTab("pending")}>待处理</button><button type="button" className={tab === "done" ? "is-active" : ""} onClick={() => setTab("done")}>已处理</button></div><button className="dlm-secondary" type="button" onClick={() => openDrawer("approval-rules")}><IconAdjustments size={16} /> 审批规则</button></div><Panel title={tab === "pending" ? "待处理审批" : "审批记录"} description="审批只对当前成果版本生效，不代表任务或外部交付自动完成。"><div className="dlm-approval-list">{visible.map((item) => <article key={item.id}><span className={`dlm-approval-mark dlm-approval-mark--${item.tone}`}><IconShieldCheck size={19} /></span><div className="dlm-approval-copy"><div><StatusTag tone={item.tone}>{item.risk}</StatusTag><small>{item.id} · {item.created}</small></div><h3>{item.title}</h3><p>{item.type} · {item.owner} · 申请人 {item.requester}</p><span>依据：{item.evidence}</span></div><div className="dlm-approval-cost"><small>关联消耗</small><strong>{item.points} 智点</strong><StatusTag tone={item.status === "待我审批" ? "warning" : "success"}>{item.status}</StatusTag></div><div className="dlm-approval-actions"><button type="button" onClick={() => openDrawer("approval", item.id)}><IconEye size={16} /> 查看依据</button>{item.status === "待我审批" ? <><button type="button" onClick={() => decide(item.id, "已退回")}>退回</button><button className="is-primary" type="button" onClick={() => decide(item.id, "已通过")}><IconCheck size={16} /> 通过</button></> : null}</div></article>)}</div></Panel></>;
}

function PointsModule({ openModal, openDrawer }) {
  const budgets = [{ department: "市场部", budget: 18000, consumed: 10240, reserved: 3200, remaining: 4560 }, { department: "法务部", budget: 12000, consumed: 6280, reserved: 820, remaining: 4900 }, { department: "商务部", budget: 22000, consumed: 12460, reserved: 4180, remaining: 5360 }];
  return <><MetricStrip items={[{ label: "可用智点", value: "48,620", note: "1 元 = 100 智点", icon: IconCoin }, { label: "已预占", value: "18,200", note: "34 个活跃任务", icon: IconLock, tone: "cyan" }, { label: "本月实扣", value: "32,480", note: "较上月 +11.2%", icon: IconActivity, tone: "amber" }, { label: "本月已释放", value: "9,320", note: "任务结束自动释放", icon: IconRefresh, tone: "green" }]} /><div className="dlm-points-grid"><Panel title="部门预算" description="预算限制新任务预占，不修改历史账本。" action={<button className="dlm-secondary" type="button" onClick={() => openModal("budget")}><IconPencil size={16} /> 调整预算</button>}><div className="dlm-budget-list">{budgets.map((item) => { const used = Math.round(((item.consumed + item.reserved) / item.budget) * 100); return <button type="button" key={item.department} onClick={() => openDrawer("budget", item.department)}><div><strong>{item.department}</strong><small>预算 {item.budget.toLocaleString()} 智点</small></div><div className="dlm-budget-bar"><i style={{ width: `${used}%` }} /><span>{used}%</span></div><dl><div><dt>实扣</dt><dd>{item.consumed.toLocaleString()}</dd></div><div><dt>预占</dt><dd>{item.reserved.toLocaleString()}</dd></div><div><dt>可用</dt><dd>{item.remaining.toLocaleString()}</dd></div></dl><IconChevronRight size={17} /></button>; })}</div></Panel><Panel title="能力消耗结构" description="按实际实扣智点统计。"><div className="dlm-consumption-bars">{[["图像生成", 38.4, "12,480"], ["大模型推理", 28.1, "9,120"], ["文档解析", 19.2, "6,240"], ["数据检索", 9.8, "3,200"], ["其他", 4.5, "1,440"]].map(([label, percent, value]) => <div key={label}><span>{label}</span><i><b style={{ width: `${percent * 2.25}%` }} /></i><strong>{value}</strong><small>{percent}%</small></div>)}</div></Panel></div><Panel title="智点账本" description="所有金额使用整数最小单位记账，可下钻到调用、价格快照和分录。" action={<button className="dlm-secondary" type="button" onClick={() => openDrawer("point-summary")}><IconFileAnalytics size={16} /> 导出对账摘要</button>}><div className="dlm-table dlm-ledger-table"><div className="dlm-table-head"><span>时间</span><span>来源</span><span>能力</span><span>分录类型</span><span>变动</span><span>余额</span><span>追踪 ID</span></div>{LEDGER_ROWS.map((row) => <button className="dlm-table-row" type="button" key={row.id} onClick={() => openDrawer("ledger", row.id)}><span>{row.time}</span><strong>{row.source}</strong><span>{row.capability}</span><StatusTag tone={row.kind === "实扣" ? "warning" : row.kind === "释放" ? "success" : "info"}>{row.kind}</StatusTag><strong className={row.amount > 0 ? "is-positive" : "is-negative"}>{row.amount > 0 ? "+" : ""}{row.amount}</strong><strong>{row.balance.toLocaleString()}</strong><code>{row.trace}</code></button>)}</div></Panel></>;
}

function TasksModule({ tasks, setTasks, openDrawer, notify }) {
  const [filter, setFilter] = useState("全部");
  const visible = tasks.filter((task) => filter === "全部" || task.status === filter);
  const refresh = () => notify("任务快照与最新事件已同步");
  return <><MetricStrip items={[{ label: "运行中", value: tasks.filter((task) => task.status === "执行中").length, note: "当前均持有有效 Run 租约", icon: IconPlayerPlay }, { label: "等待人工", value: tasks.filter((task) => ["等待确认", "待审批"].includes(task.status)).length, note: "不会自动越过检查点", icon: IconShieldCheck, tone: "amber" }, { label: "异常", value: tasks.filter((task) => task.status === "异常").length, note: "可恢复 1 · 待确认 0", icon: IconAlertTriangle, tone: "red" }, { label: "今日成功率", value: "98.7%", note: "任务、成果、交付分别统计", icon: IconCircleCheck, tone: "green" }]} /><div className="dlm-toolbar"><div className="dlm-tabs">{["全部", "执行中", "等待确认", "待审批", "异常"].map((item) => <button type="button" key={item} className={filter === item ? "is-active" : ""} onClick={() => setFilter(item)}>{item}</button>)}</div><button className="dlm-secondary" type="button" onClick={refresh}><IconRefresh size={16} /> 刷新快照</button></div><Panel title="任务与运行状态" description="进度来自持久步骤和事件，不使用模拟百分比作为权威事实。"><div className="dlm-table dlm-task-table"><div className="dlm-table-head"><span>任务</span><span>数字员工</span><span>当前步骤</span><span>任务状态</span><span>执行进度</span><span>智点</span><span>最近更新</span><span>操作</span></div>{visible.map((task) => <div className="dlm-table-row" key={task.id}><div><strong>{task.title}</strong><small>{task.id} · {task.department}</small></div><span>{task.agent}</span><span><strong>{task.step}</strong><small>{task.run}</small></span><StatusTag tone={task.tone}>{task.status}</StatusTag><div className="dlm-task-progress"><i><b style={{ width: `${task.progress}%` }} /></i><small>{task.progress}%</small></div><strong>{task.points}</strong><span>{task.updated}</span><button className="dlm-link" type="button" onClick={() => openDrawer("task", task.id)}>运行详情</button></div>)}</div></Panel></>;
}

function AuditModule({ openDrawer }) {
  const [query, setQuery] = useState("");
  const visible = AUDIT_ROWS.filter((row) => `${row.actor}${row.action}${row.object}${row.result}`.includes(query));
  return <><MetricStrip items={[{ label: "今日审计事件", value: "2,846", note: "完整率 100%", icon: IconFileAnalytics }, { label: "权限拒绝", value: "18", note: "均未投递正文", icon: IconLock, tone: "amber" }, { label: "异常接管", value: "1", note: "旧 generation 已隔离", icon: IconRefresh, tone: "cyan" }, { label: "高风险待处理", value: "0", note: "当前无未关闭事件", icon: IconShieldCheck, tone: "green" }]} /><div className="dlm-toolbar"><SearchBox value={query} onChange={setQuery} placeholder="搜索操作人、动作、对象或结果" /><button className="dlm-secondary" type="button" onClick={() => openDrawer("audit-export")}><IconFileAnalytics size={16} /> 导出审计证据</button></div><Panel title="操作与运行审计" description="记录主体、动作、对象、结果、时间和追踪标识，不保存模型思维链。"><div className="dlm-table dlm-audit-table"><div className="dlm-table-head"><span>时间</span><span>操作主体</span><span>动作</span><span>对象</span><span>结果</span><span>来源</span><span>操作</span></div>{visible.map((row) => <div className="dlm-table-row" key={row.id}><span>{row.time}</span><strong>{row.actor}</strong><span>{row.action}</span><span>{row.object}</span><StatusTag tone={row.tone}>{row.result}</StatusTag><code>{row.ip}</code><button className="dlm-link" type="button" onClick={() => openDrawer("audit", row.id)}>证据详情</button></div>)}</div></Panel></>;
}

function GenericDrawer({ drawer, onClose, agents, setAgents, documents, setDocuments, approvals, setApprovals, tasks, setTasks, notify }) {
  if (!drawer) return null;
  const agent = agents.find((item) => item.id === drawer.id);
  const document = documents.find((item) => item.id === drawer.id);
  const approval = approvals.find((item) => item.id === drawer.id);
  const task = tasks.find((item) => item.id === drawer.id);
  const ledger = LEDGER_ROWS.find((item) => item.id === drawer.id);
  const audit = AUDIT_ROWS.find((item) => item.id === drawer.id);
  const titles = { agent: "员工配置与运行", document: "文档版本详情", "document-permission": "文档权限", "knowledge-policy": "知识权限策略", memory: "记忆审计", "memory-policy": "记忆作用域规则", tool: "工具授权详情", "tool-connect": "接入企业工具", model: "模型路由设置", department: "部门与数据边界", group: "群聊治理设置", approval: "审批依据", "approval-rules": "审批规则", budget: "部门预算详情", ledger: "账本分录", "point-summary": "对账摘要", task: "任务运行详情", audit: "审计证据", "audit-export": "导出审计证据", notifications: "企业通知" };
  const closeWith = (message) => { notify(message); onClose(); };
  return <div className="dlm-layer" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><aside className="dlm-drawer" role="dialog" aria-modal="true" aria-label={titles[drawer.kind] ?? "详情"}><header><div><small>点联企业管理中心</small><h2>{titles[drawer.kind] ?? "详情"}</h2></div><button autoFocus type="button" aria-label="关闭" onClick={onClose}><IconX size={20} /></button></header><div className="dlm-drawer-body">
    {agent ? <><div className="dlm-drawer-person"><img src={agent.image} alt="" /><div><StatusTag tone={agent.tone}>{agent.status}</StatusTag><h3>{agent.name}</h3><p>{agent.department} · 模板 {agent.version}</p></div></div><DetailList rows={[["模型策略", agent.model], ["数据范围", agent.scope], ["今日任务", `${agent.tasks} 个`], ["今日智点", `${agent.points} 智点`]]} /><DrawerSection title="能力与权限"><div className="dlm-chip-row"><span>读取授权知识</span><span>写入候选记忆</span><span>创建版本成果</span><span>申请人工审批</span></div></DrawerSection><div className="dlm-drawer-actions"><button type="button" onClick={() => closeWith("员工配置已保存")}>保存配置</button><button className="is-primary" type="button" onClick={() => { setAgents((rows) => rows.map((item) => item.id === agent.id ? { ...item, status: item.status === "已停用" ? "空闲" : "已停用", tone: item.status === "已停用" ? "neutral" : "danger" } : item)); closeWith(agent.status === "已停用" ? "员工已恢复调用" : "员工已停止接受新任务"); }}>{agent.status === "已停用" ? "恢复调用" : "停止新任务"}</button></div></> : null}
    {document ? <><DrawerSection title="文档快照"><DetailList rows={[["文档名称", document.name], ["知识空间", document.space], ["当前版本", document.version], ["处理状态", document.status], ["索引规模", `${document.chunks} 段`]]} /></DrawerSection><DrawerSection title="当前授权"><div className="dlm-permission-options">{["仅授权部门成员", "仅授权指定数字员工", "引用与附件使用相同边界", "撤权后立即停止后续正文投递"].map((label) => <label key={label}><input type="checkbox" defaultChecked /><span>{label}</span></label>)}</div></DrawerSection><div className="dlm-drawer-actions"><button type="button" onClick={onClose}>取消</button><button className="is-primary" type="button" onClick={() => { setDocuments((rows) => rows.map((item) => item.id === document.id ? { ...item, updated: "刚刚" } : item)); closeWith("文档权限版本已更新并写入审计"); }}>保存权限</button></div></> : null}
    {approval ? <><StatusTag tone={approval.tone}>{approval.risk}</StatusTag><h3 className="dlm-drawer-title">{approval.title}</h3><p className="dlm-drawer-lead">{approval.type} · {approval.owner}</p><DetailList rows={[["审批编号", approval.id], ["申请人", `${approval.requester} · ${approval.department}`], ["关联消耗", `${approval.points} 智点`], ["当前状态", approval.status]]} /><DrawerSection title="决策依据"><p>{approval.evidence}</p><div className="dlm-evidence-list"><span><IconCheck size={15} /> 权限与引用范围校验通过</span><span><IconCheck size={15} /> 成果内容哈希已冻结</span><span><IconCheck size={15} /> 审批仅绑定当前版本</span></div></DrawerSection>{approval.status === "待我审批" ? <div className="dlm-drawer-actions"><button type="button" onClick={() => { setApprovals((rows) => rows.map((item) => item.id === approval.id ? { ...item, status: "已退回" } : item)); closeWith("审批已退回，原成果保持可追溯"); }}>退回修改</button><button className="is-primary" type="button" onClick={() => { setApprovals((rows) => rows.map((item) => item.id === approval.id ? { ...item, status: "已通过" } : item)); closeWith("当前成果版本已通过审批"); }}>确认通过</button></div> : null}</> : null}
    {task ? <><div className="dlm-task-drawer-heading"><StatusTag tone={task.tone}>{task.status}</StatusTag><h3>{task.title}</h3><p>{task.id} · {task.agent} · {task.run}</p></div><DetailList rows={[["当前步骤", task.step], ["当前进度", `${task.progress}%`], ["实际 / 预计", `${task.points} 智点`], ["最近更新", task.updated]]} /><DrawerSection title="运行轨迹"><div className="dlm-timeline"><div><i className="is-done" /><span><strong>计划已确认</strong><small>输入、负责人、费用和人工检查点已冻结</small></span></div><div><i className="is-done" /><span><strong>知识与权限快照完成</strong><small>引用范围已保存</small></span></div><div><i className="is-current" /><span><strong>{task.step}</strong><small>负责人：{task.agent}</small></span></div></div></DrawerSection><div className="dlm-drawer-actions"><button type="button" onClick={() => { setTasks((rows) => rows.map((item) => item.id === task.id ? { ...item, status: item.status === "已暂停" ? "执行中" : "已暂停", tone: item.status === "已暂停" ? "info" : "warning" } : item)); closeWith(task.status === "已暂停" ? "任务已从安全点恢复" : "任务将在安全点暂停"); }}>{task.status === "已暂停" ? <IconPlayerPlay size={16} /> : <IconPlayerPause size={16} />}{task.status === "已暂停" ? "恢复" : "暂停"}</button><button className="is-primary" type="button" onClick={() => closeWith("已定位至当前 Run 的完整事件轨迹")}>查看全部事件</button></div></> : null}
    {ledger ? <><StatusTag tone={ledger.kind === "释放" ? "success" : "info"}>{ledger.kind}</StatusTag><h3 className="dlm-drawer-title">{ledger.source}</h3><DetailList rows={[["分录编号", ledger.id], ["发生时间", ledger.time], ["能力", ledger.capability], ["智点变动", `${ledger.amount > 0 ? "+" : ""}${ledger.amount}`], ["分录后余额", ledger.balance.toLocaleString()], ["追踪 ID", ledger.trace]]} /><DrawerSection title="勾稽关系"><div className="dlm-evidence-list"><span><IconCheck size={15} /> Reservation 与 LedgerEntry 已匹配</span><span><IconCheck size={15} /> 价格快照倍率版本：price-2026.08</span><span><IconCheck size={15} /> 可下钻至 UsageCall 与 Provider Attempt</span></div></DrawerSection><button className="dlm-wide-action" type="button" onClick={() => closeWith("该分录对账证据已复制到审计摘要")}>加入对账摘要</button></> : null}
    {audit ? <><StatusTag tone={audit.tone}>{audit.result}</StatusTag><h3 className="dlm-drawer-title">{audit.action}</h3><DetailList rows={[["事件编号", audit.id], ["时间", audit.time], ["操作主体", audit.actor], ["对象", audit.object], ["来源", audit.ip], ["结果", audit.result]]} /><DrawerSection title="证据完整性"><div className="dlm-evidence-list"><span><IconCheck size={15} /> 租户、主体与角色快照完整</span><span><IconCheck size={15} /> 请求、业务对象与结果可关联</span><span><IconCheck size={15} /> 敏感正文未写入平台审计摘要</span></div></DrawerSection></> : null}
    {!agent && !document && !approval && !task && !ledger && !audit ? <GenericDrawerContent kind={drawer.kind} id={drawer.id} closeWith={closeWith} /> : null}
  </div></aside></div>;
}

function GenericDrawerContent({ kind, id, closeWith }) {
  const content = {
    "knowledge-policy": ["检索前执行成员、部门、项目和员工实例四层鉴权。", "正文、引用片段与原附件采用同一 Audience。", "成员撤权后停止新投递，并清理未消费事件。"],
    "memory-policy": ["个人记忆仅在个人与员工单聊作用域召回。", "群聊只使用群与项目记忆，禁止读取成员私人记忆。", "冲突记忆进入人工复核，新候选不得静默覆盖。"],
    "tool-connect": ["选择企业已审核的 Provider 或填写内部服务标识。", "配置允许的员工、项目、操作与有效期。", "外部写操作必须绑定审批和幂等键。"],
    "approval-rules": ["合同高风险必须由法务角色确认。", "报价例外和低于底价必须由价格审批人确认。", "视觉版权与品牌要素由成果 Owner 确认。"],
    "point-summary": ["智点账户、预占、实扣和释放分录保持平衡。", "企业消费可下钻到 UsageCall、费率快照和 Provider 成本。", "导出内容不包含合同、图片、提示词或私有记忆正文。"],
    "audit-export": ["范围：当前筛选条件内的操作与运行事件。", "格式：CSV 数据索引 + PDF 证据摘要。", "导出行为本身会记录新的审计事件。"],
    notifications: ["2 条审批将在 2 小时内超时。", "供应商价格表存在 2 个待确认表格。", "报价专员预算已使用 76%。"],
  }[kind] ?? [id ? `当前对象：${id}` : "当前配置使用企业级最小权限策略。", "每次变更都会产生新版本并写入审计。", "保存后只影响后续任务，不静默改写历史事实。"];
  return <><div className="dlm-generic-drawer-icon"><IconShieldCheck size={25} /></div><div className="dlm-rule-list">{content.map((line, index) => <div key={line}><span>{index + 1}</span><p>{line}</p></div>)}</div><div className="dlm-drawer-actions"><button type="button" onClick={() => closeWith("配置保持不变")}>关闭</button><button className="is-primary" type="button" onClick={() => closeWith("配置已保存并生成新审计版本")}>保存设置</button></div></>;
}

function DrawerSection({ title, children }) { return <section className="dlm-drawer-section"><h4>{title}</h4>{children}</section>; }
function DetailList({ rows }) { return <dl className="dlm-detail-list">{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>; }

function RecruitModal({ initialTemplateId, onClose, onConfirm }) {
  const [step, setStep] = useState(1);
  const [templateId, setTemplateId] = useState(initialTemplateId ?? "graphic");
  const template = EMPLOYEE_TEMPLATES.find((item) => item.id === templateId);
  const [form, setForm] = useState({ name: template?.name ?? "平面出图专员", department: "市场部", model: template?.model ?? "视觉创作路由", scope: "当前部门与指定项目", monthlyLimit: "8000" });
  useEffect(() => { if (template) setForm((current) => ({ ...current, name: template.name, model: template.model })); }, [template]);
  const setField = (key, value) => setForm((current) => ({ ...current, [key]: value }));
  return <ModalFrame title="招聘并定制数字员工" onClose={onClose}><div className="dlm-stepper">{["选择岗位", "企业定制", "确认到岗"].map((label, index) => <div className={step >= index + 1 ? "is-active" : ""} key={label}><span>{step > index + 1 ? <IconCheck size={14} /> : index + 1}</span><strong>{label}</strong></div>)}</div>{step === 1 ? <div className="dlm-recruit-options">{EMPLOYEE_TEMPLATES.map((item) => <button type="button" className={templateId === item.id ? "is-selected" : ""} key={item.id} onClick={() => setTemplateId(item.id)}><img src={item.image} alt="" /><span><strong>{item.name}</strong><small>{item.role}</small></span>{templateId === item.id ? <IconCircleCheck size={19} /> : null}</button>)}</div> : null}{step === 2 ? <div className="dlm-form-grid"><label><span>员工名称</span><input value={form.name} onChange={(event) => setField("name", event.target.value)} /></label><label><span>所属部门</span><select value={form.department} onChange={(event) => setField("department", event.target.value)}><option>市场部</option><option>法务部</option><option>商务部</option><option>管理层</option></select></label><label><span>模型策略</span><select value={form.model} onChange={(event) => setField("model", event.target.value)}><option>视觉创作路由</option><option>严谨审查路由</option><option>结构化推理路由</option></select></label><label><span>月度智点上限</span><input type="number" value={form.monthlyLimit} onChange={(event) => setField("monthlyLimit", event.target.value)} /></label><label className="is-wide"><span>知识与记忆范围</span><select value={form.scope} onChange={(event) => setField("scope", event.target.value)}><option>当前部门与指定项目</option><option>仅指定项目</option><option>企业公开知识</option></select></label><div className="dlm-form-note"><IconShieldCheck size={18} /><span>员工默认不能读取成员私人记忆；跨部门资料需按任务临时授权。</span></div></div> : null}{step === 3 ? <div className="dlm-confirm-card"><img src={template.image} alt="" /><div><StatusTag tone="info">待确认到岗</StatusTag><h3>{form.name}</h3><p>{template.role}</p><DetailList rows={[["所属部门", form.department], ["模板", `${template.name} · 官方当前版`], ["模型策略", form.model], ["知识范围", form.scope], ["月度上限", `${Number(form.monthlyLimit || 0).toLocaleString()} 智点`]]} /></div></div> : null}<div className="dlm-modal-actions"><button type="button" onClick={step === 1 ? onClose : () => setStep((value) => value - 1)}>{step === 1 ? "取消" : "上一步"}</button><button className="is-primary" type="button" disabled={step === 2 && !form.name.trim()} onClick={() => { if (step < 3) setStep((value) => value + 1); else onConfirm({ template, form }); }}>{step < 3 ? "下一步" : "确认招聘并到岗"}</button></div></ModalFrame>;
}

function UploadModal({ onClose, onConfirm }) {
  const [form, setForm] = useState({ name: "供应商价格表 2026-Q3（补充版）", type: "XLSX", space: "报价依据", scope: "商务部 · 报价专员" });
  const setField = (key, value) => setForm((current) => ({ ...current, [key]: value }));
  return <ModalFrame title="上传企业知识" onClose={onClose}><div className="dlm-upload-zone"><IconUpload size={28} /><strong>已选择：{form.name}</strong><span>上传后将执行安全检查、解析、切分、索引和 ACL 快照。</span></div><div className="dlm-form-grid"><label><span>文档名称</span><input value={form.name} onChange={(event) => setField("name", event.target.value)} /></label><label><span>文件类型</span><select value={form.type} onChange={(event) => setField("type", event.target.value)}><option>PDF</option><option>DOCX</option><option>XLSX</option></select></label><label><span>知识空间</span><select value={form.space} onChange={(event) => setField("space", event.target.value)}><option>品牌资产</option><option>法务知识</option><option>报价依据</option></select></label><label><span>授权范围</span><select value={form.scope} onChange={(event) => setField("scope", event.target.value)}><option>市场部 · 平面出图专员</option><option>法务部 · 合同审核专员</option><option>商务部 · 报价专员</option></select></label></div><div className="dlm-modal-actions"><button type="button" onClick={onClose}>取消</button><button className="is-primary" type="button" disabled={!form.name.trim()} onClick={() => onConfirm(form)}>上传并开始处理</button></div></ModalFrame>;
}

function SimpleFormModal({ type, onClose, notify }) {
  const isMember = type === "member";
  return <ModalFrame title={isMember ? "添加企业成员" : "调整部门预算"} onClose={onClose}><div className="dlm-form-grid">{isMember ? <><label><span>姓名</span><input defaultValue="许宁" /></label><label><span>部门</span><select defaultValue="商务部"><option>市场部</option><option>法务部</option><option>商务部</option></select></label><label><span>企业角色</span><select defaultValue="项目负责人"><option>企业成员</option><option>项目负责人</option><option>审批人</option></select></label><label><span>数据范围</span><select defaultValue="所在部门与负责项目"><option>所在部门与负责项目</option><option>仅负责项目</option></select></label></> : <><label><span>部门</span><select defaultValue="商务部"><option>市场部</option><option>法务部</option><option>商务部</option></select></label><label><span>月度预算</span><input type="number" defaultValue="24000" /></label><label><span>预警阈值</span><select defaultValue="80%"><option>70%</option><option>80%</option><option>90%</option></select></label><label><span>超限策略</span><select defaultValue="阻止新任务"><option>阻止新任务</option><option>转人工确认</option></select></label></>}</div><div className="dlm-form-note"><IconShieldCheck size={18} /><span>{isMember ? "成员加入后仍需由数据 Owner 单独授予知识和项目范围。" : "调整只影响后续预占，不改写历史实扣和账本分录。"}</span></div><div className="dlm-modal-actions"><button type="button" onClick={onClose}>取消</button><button className="is-primary" type="button" onClick={() => { notify(isMember ? "成员邀请已发送并写入审计" : "新预算版本已生效"); onClose(); }}>{isMember ? "发送邀请" : "确认调整"}</button></div></ModalFrame>;
}

function ModalFrame({ title, onClose, children }) { return <div className="dlm-layer dlm-layer--modal" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><section className="dlm-modal" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(event) => event.stopPropagation()}><header><div><small>企业级配置</small><h2>{title}</h2></div><button autoFocus type="button" aria-label="关闭" onClick={onClose}><IconX size={20} /></button></header><div className="dlm-modal-body">{children}</div></section></div>; }

function renderModule(key, context) {
  switch (key) {
    case "agents": return <AgentsModule agents={context.agents} onRecruit={context.onRecruit} openDrawer={context.openDrawer} />;
    case "knowledge": return <KnowledgeModule documents={context.documents} openModal={context.openModal} openDrawer={context.openDrawer} />;
    case "memory": return <MemoryModule notify={context.notify} openDrawer={context.openDrawer} />;
    case "tools": return <ToolsModule notify={context.notify} openDrawer={context.openDrawer} />;
    case "models": return <ModelsModule notify={context.notify} openDrawer={context.openDrawer} />;
    case "org": return <OrgModule openModal={context.openModal} openDrawer={context.openDrawer} />;
    case "groups": return <GroupsModule openDrawer={context.openDrawer} />;
    case "approvals": return <ApprovalsModule approvals={context.approvals} setApprovals={context.setApprovals} openDrawer={context.openDrawer} notify={context.notify} />;
    case "points": return <PointsModule openModal={context.openModal} openDrawer={context.openDrawer} />;
    case "tasks": return <TasksModule tasks={context.tasks} setTasks={context.setTasks} openDrawer={context.openDrawer} notify={context.notify} />;
    case "audit": return <AuditModule openDrawer={context.openDrawer} />;
    default: return null;
  }
}

export function EnterpriseModules({ moduleKey = "agents", onModuleChange }) {
  const normalizedKey = MODULE_META[moduleKey] ? moduleKey : "agents";
  const [localKey, setLocalKey] = useState(normalizedKey);
  const [collapsed, setCollapsed] = useState(false);
  const [tenantMenuOpen, setTenantMenuOpen] = useState(false);
  const [roleMenuOpen, setRoleMenuOpen] = useState(false);
  const [drawer, setDrawer] = useState(null);
  const [modal, setModal] = useState(null);
  const [toast, setToast] = useState("");
  const [agents, setAgents] = useState(INITIAL_AGENTS);
  const [documents, setDocuments] = useState(INITIAL_DOCUMENTS);
  const [approvals, setApprovals] = useState(INITIAL_APPROVALS);
  const [tasks, setTasks] = useState(INITIAL_TASKS);
  const overlayTriggerRef = useRef(null);

  useEffect(() => setLocalKey(normalizedKey), [normalizedKey]);
  const activeKey = localKey;
  const meta = MODULE_META[activeKey];
  const notify = (message) => setToast(message);
  const rememberOverlayTrigger = () => { overlayTriggerRef.current = document.activeElement; };
  const openDrawer = (kind, id) => { rememberOverlayTrigger(); setDrawer({ kind, id }); };
  const openModal = (type, data = {}) => { rememberOverlayTrigger(); setModal({ type, ...data }); };
  const closeOverlay = () => {
    setDrawer(null);
    setModal(null);
    requestAnimationFrame(() => overlayTriggerRef.current?.focus());
  };
  const navigate = (key) => { setLocalKey(key); onModuleChange?.(key); setDrawer(null); setModal(null); };
  const onRecruit = (templateId) => openModal("recruit", { templateId });
  const confirmRecruit = ({ template, form }) => {
    setAgents((rows) => [...rows, { id: `agent-${Date.now()}`, name: form.name, department: form.department, status: "空闲", tone: "neutral", model: form.model, tasks: 0, points: 0, version: "当前官方版", scope: form.scope, image: template.image }]);
    closeOverlay();
    setLocalKey("agents");
    notify(`${form.name}已到岗，可继续配置技能和权限`);
  };
  const confirmUpload = (form) => { setDocuments((rows) => [...rows, { id: `doc-${Date.now()}`, ...form, version: "v1.0", status: "索引中", tone: "info", chunks: 0, progress: 8, updated: "刚刚" }]); closeOverlay(); notify("文档已进入安全检查与解析队列"); };

  useEffect(() => {
    if (!drawer && !modal) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === "Escape") closeOverlay();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [drawer, modal]);

  const context = { agents, documents, approvals, setApprovals, tasks, setTasks, notify, openDrawer, openModal, onRecruit };

  return (
    <div className={`dlm-shell${collapsed ? " is-collapsed" : ""}`}>
      <header className="dlm-topbar"><div className="dlm-brand"><img src="/assets/brand/dianlian-symbol.png" alt="点联" /><strong>点联企业管理中心</strong></div><div className="dlm-top-actions"><div className="dlm-popover-wrap"><button type="button" onClick={() => setTenantMenuOpen((value) => !value)}><IconBuildingSkyscraper size={17} /> 星海会展集团 <IconChevronDown size={15} /></button>{tenantMenuOpen ? <div className="dlm-popover"><button type="button" className="is-selected" onClick={() => { setTenantMenuOpen(false); notify("已切换至星海会展集团"); }}><IconCheck size={15} /> 星海会展集团</button><button type="button" onClick={() => { setTenantMenuOpen(false); notify("当前账号仅有星海会展集团管理权限"); }}><IconLock size={15} /> 其他企业需授权</button></div> : null}</div><button className="dlm-bell" type="button" aria-label="企业通知" onClick={() => openDrawer("notifications")}><IconBell size={20} /><span>{approvals.filter((item) => item.status === "待我审批").length + 2}</span></button><div className="dlm-popover-wrap"><button type="button" onClick={() => setRoleMenuOpen((value) => !value)}>企业管理员 <IconChevronDown size={15} /></button>{roleMenuOpen ? <div className="dlm-popover dlm-popover--right"><button className="is-selected" type="button" onClick={() => setRoleMenuOpen(false)}><IconCheck size={15} /> 企业管理员</button><button type="button" onClick={() => { setRoleMenuOpen(false); notify("审批人视角已应用到当前页面"); }}><IconShieldCheck size={15} /> 审批人视角</button></div> : null}</div><img src="/assets/employees/quotation-specialist.png" alt="企业管理员" /></div></header>
      <aside className="dlm-sidebar"><button className="dlm-overview-link" type="button" onClick={() => onModuleChange?.("overview")}><IconDeviceDesktopAnalytics size={19} /><span>企业概览</span></button><nav>{NAV_GROUPS.map((group) => <section key={group.label}><p>{group.label}</p>{group.keys.map((key) => { const item = MODULE_META[key]; const Icon = item.icon; return <button className={activeKey === key ? "is-active" : ""} type="button" key={key} onClick={() => navigate(key)} title={collapsed ? item.label : undefined}><Icon size={18} /><span>{item.label}</span>{key === "approvals" && approvals.some((approval) => approval.status === "待我审批") ? <b>{approvals.filter((approval) => approval.status === "待我审批").length}</b> : null}</button>; })}</section>)}</nav><button className="dlm-collapse" type="button" onClick={() => setCollapsed((value) => !value)}><IconChevronRight size={18} /><span>{collapsed ? "展开菜单" : "收起菜单"}</span></button></aside>
      <main className="dlm-main"><header className="dlm-page-heading"><div><h1>{meta.title}</h1><p>{meta.description}</p></div><div><span><IconCircleCheck size={15} /> 数据更新于刚刚</span><button type="button" onClick={() => notify(`${meta.title}数据已刷新`)}><IconRefresh size={16} /> 刷新</button></div></header>{renderModule(activeKey, context)}</main>
      {toast ? <div className="dlm-toast" role="status"><IconCircleCheck size={18} /><span>{toast}</span><button type="button" aria-label="关闭提示" onClick={() => setToast("")}><IconX size={16} /></button></div> : null}
      <GenericDrawer drawer={drawer} onClose={closeOverlay} agents={agents} setAgents={setAgents} documents={documents} setDocuments={setDocuments} approvals={approvals} setApprovals={setApprovals} tasks={tasks} setTasks={setTasks} notify={notify} />
      {modal?.type === "recruit" ? <RecruitModal initialTemplateId={modal.templateId} onClose={closeOverlay} onConfirm={confirmRecruit} /> : null}
      {modal?.type === "upload" ? <UploadModal onClose={closeOverlay} onConfirm={confirmUpload} /> : null}
      {["member", "budget"].includes(modal?.type) ? <SimpleFormModal type={modal.type} onClose={closeOverlay} notify={notify} /> : null}
    </div>
  );
}

export default EnterpriseModules;
