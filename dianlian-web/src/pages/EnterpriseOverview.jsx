import { useMemo, useState } from "react";
import {
  IconActivity,
  IconAdjustments,
  IconAlertTriangle,
  IconArrowDown,
  IconArrowUp,
  IconBell,
  IconBook2,
  IconBrain,
  IconChecklist,
  IconChevronDown,
  IconChevronRight,
  IconChevronsLeft,
  IconCircleCheck,
  IconClipboardCheck,
  IconCoin,
  IconContract,
  IconDatabase,
  IconFileAnalytics,
  IconHome,
  IconMessages,
  IconPhoto,
  IconRefresh,
  IconSearch,
  IconSettings,
  IconTools,
  IconUser,
  IconUserPlus,
  IconUsers,
  IconUsersGroup,
  IconZoomMoney,
} from "@tabler/icons-react";
import {
  Area,
  AreaChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import "./enterprise.css";

const sidebarGroups = [
  {
    items: [{ label: "概览", icon: IconHome }],
  },
  {
    label: "数字员工",
    items: [
      { label: "员工实例", icon: IconUsers },
      { label: "招聘员工", icon: IconUserPlus },
      { label: "技能与工具", icon: IconTools },
    ],
  },
  {
    label: "知识与记忆",
    items: [
      { label: "企业知识", icon: IconBook2 },
      { label: "记忆治理", icon: IconBrain },
    ],
  },
  {
    label: "组织与协作",
    items: [
      { label: "部门与成员", icon: IconUsersGroup },
      { label: "群聊治理", icon: IconMessages },
      { label: "审批中心", icon: IconClipboardCheck },
    ],
  },
  {
    label: "模型与智点",
    items: [
      { label: "模型策略", icon: IconSettings },
      { label: "智点、预算与费用", icon: IconCoin },
    ],
  },
  {
    label: "运营治理",
    items: [
      { label: "任务监控", icon: IconActivity },
      { label: "异常与审计", icon: IconFileAnalytics },
    ],
  },
];

const enterpriseRouteByLabel = {
  概览: "overview",
  员工实例: "agents",
  招聘员工: "agents",
  技能与工具: "tools",
  企业知识: "knowledge",
  记忆治理: "memory",
  部门与成员: "org",
  群聊治理: "groups",
  审批中心: "approvals",
  模型策略: "models",
  "智点、预算与费用": "points",
  任务监控: "tasks",
  异常与审计: "audit",
  员工实例管理: "agents",
  智点与预算设置: "points",
};

const scopeMetrics = {
  本企业: [
    { label: "在线数字员工", value: "12", unit: "人", delta: "2", trend: "up", icon: IconUsers },
    { label: "运行中任务", value: "8", unit: "个", delta: "1", trend: "down", icon: IconChecklist },
    { label: "待处理审批", value: "5", unit: "条", delta: "2", trend: "alert", icon: IconClipboardCheck },
    { label: "可用智点", value: "48,620", unit: "", delta: "3,280", trend: "up", icon: IconCoin },
  ],
  我的部门: [
    { label: "在线数字员工", value: "7", unit: "人", delta: "1", trend: "up", icon: IconUsers },
    { label: "运行中任务", value: "6", unit: "个", delta: "2", trend: "up", icon: IconChecklist },
    { label: "待处理审批", value: "3", unit: "条", delta: "1", trend: "alert", icon: IconClipboardCheck },
    { label: "可用智点", value: "25,320", unit: "", delta: "1,460", trend: "up", icon: IconCoin },
  ],
  我负责的: [
    { label: "在线数字员工", value: "3", unit: "人", delta: "0", trend: "flat", icon: IconUsers },
    { label: "运行中任务", value: "4", unit: "个", delta: "1", trend: "down", icon: IconChecklist },
    { label: "待处理审批", value: "2", unit: "条", delta: "1", trend: "alert", icon: IconClipboardCheck },
    { label: "可用智点", value: "12,680", unit: "", delta: "620", trend: "up", icon: IconCoin },
  ],
};

const sparkData = [22, 25, 21, 29, 23, 27, 19, 18, 26, 31].map((value, index) => ({ index, value }));
const taskSparkData = [14, 15, 18, 18, 22, 16, 18, 21, 17].map((value, index) => ({ index, value }));
const approvalSparkData = [10, 13, 11, 15, 14, 20, 15, 17].map((value, index) => ({ index, value }));
const pointSparkData = [18, 19, 22, 18, 17, 15, 18, 17, 19].map((value, index) => ({ index, value }));
const sparkSets = [sparkData, taskSparkData, approvalSparkData, pointSparkData];

const employees = [
  {
    name: "平面出图专员",
    avatar: "/assets/employees/graphic-designer.png",
    health: "健康",
    healthTone: "healthy",
    task: "夏季展会主视觉\n生成候选图 3/5",
    active: "2 分钟前",
    points: 320,
  },
  {
    name: "法务合同审核专员",
    avatar: "/assets/employees/contract-reviewer.png",
    health: "健康",
    healthTone: "healthy",
    task: "场馆服务合同审查\n3 项高风险",
    active: "5 分钟前",
    points: 180,
  },
  {
    name: "报价专员",
    avatar: "/assets/employees/quotation-specialist.png",
    health: "轻载",
    healthTone: "light",
    task: "工商银行展台项目\n报价审核",
    active: "8 分钟前",
    points: 210,
  },
];

const todoItems = [
  {
    type: "合同高风险确认",
    summary: "场馆服务合同 · 条款 12.3\n付款违约责任",
    owner: "法务合同审核专员",
    avatar: "/assets/employees/contract-reviewer.png",
    deadline: "今天 17:00",
    deadlineTone: "danger",
    risk: "高风险",
    riskLevel: 3,
    icon: IconContract,
    tone: "orange",
  },
  {
    type: "报价价格异常审批",
    summary: "工商银行展台项目 · 报价 v2\n综合毛利率异常",
    owner: "报价专员",
    avatar: "/assets/employees/quotation-specialist.png",
    deadline: "明天 10:00",
    deadlineTone: "normal",
    risk: "中风险",
    riskLevel: 2,
    icon: IconCoin,
    tone: "blue",
  },
  {
    type: "图片版权/品牌确认",
    summary: "展会主视觉候选图 #3\n含品牌元素",
    owner: "平面出图专员",
    avatar: "/assets/employees/graphic-designer.png",
    deadline: "08-12 12:00",
    deadlineTone: "normal",
    risk: "低风险",
    riskLevel: 1,
    icon: IconPhoto,
    tone: "green",
  },
  {
    type: "智点预算即将触顶",
    summary: "市场部本月预算已使用 86%\n需要调整任务上限",
    owner: "企业管理员",
    avatar: "/assets/employees/graphic-designer.png",
    deadline: "08-13 18:00",
    deadlineTone: "normal",
    risk: "中风险",
    riskLevel: 2,
    icon: IconZoomMoney,
    tone: "purple",
  },
  {
    type: "知识解析异常",
    summary: "供应商价格表 2026-Q3\n2 个表格未能识别",
    owner: "知识管理员",
    avatar: "/assets/employees/contract-reviewer.png",
    deadline: "08-14 12:00",
    deadlineTone: "normal",
    risk: "中风险",
    riskLevel: 2,
    icon: IconDatabase,
    tone: "cyan",
  },
];

const pointLegend = [
  { label: "已消耗", value: "32,480", percent: "54.1%", color: "#1768e5" },
  { label: "已预占", value: "18,200", percent: "30.3%", color: "#32b7dc" },
  { label: "已释放", value: "9,320", percent: "15.6%", color: "#dbe4ef" },
];

const pointPie = pointLegend.map((item) => ({ name: item.label, value: Number.parseFloat(item.percent), color: item.color }));

const capabilityUsage = [
  { name: "图像生成", value: 12480, percent: 38.4, color: "#1768e5" },
  { name: "大模型推理", value: 9120, percent: 28.1, color: "#1768e5" },
  { name: "文档解析", value: 6240, percent: 19.2, color: "#32b7dc" },
  { name: "数据检索", value: 3200, percent: 9.8, color: "#7bcfe8" },
  { name: "其他", value: 1440, percent: 4.5, color: "#bcddec" },
];

const knowledgeRows = [
  { name: "文档解析", running: 14, complete: 86, confirm: 18, failed: 2 },
  { name: "知识索引", running: 22, complete: 102, confirm: 27, failed: 1 },
  { name: "ACL 范围更新", running: 8, complete: 36, confirm: "—", failed: 0 },
  { name: "记忆入库", running: 6, complete: 31, confirm: 15, failed: 0 },
];

const anomalyRows = [
  { label: "服务商重试中", count: 6, reason: "上游模型超时 / 5xx", impact: "3 个任务", action: "查看并重试", tone: "danger" },
  { label: "配额等待中", count: 4, reason: "模型调用配额已满", impact: "2 个任务", action: "排队中", tone: "warning" },
  { label: "权限被撤销", count: 3, reason: "成员/部门权限变更", impact: "2 个任务", action: "检查权限", tone: "warning" },
];

const quickEntries = [
  { label: "员工实例管理", icon: IconUser },
  { label: "审批中心", icon: IconClipboardCheck },
  { label: "任务监控", icon: IconActivity },
  { label: "智点与预算设置", icon: IconCoin },
];

function formatTime(date) {
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function Sparkline({ data, color }) {
  return (
    <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 112, height: 42 }}>
      <AreaChart data={data} margin={{ top: 4, right: 2, bottom: 0, left: 2 }}>
        <Area type="monotone" dataKey="value" stroke={color} strokeWidth={1.8} fill={color} fillOpacity={0.08} dot={false} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function SectionHeader({ title, aside, onAside, expanded }) {
  return (
    <div className="enterprise-section-header">
      <h2>{title}</h2>
      {aside ? (
        <button className="enterprise-link-button" type="button" onClick={onAside} aria-expanded={expanded}>
          {aside}
          <IconChevronRight size={16} stroke={2} />
        </button>
      ) : null}
    </div>
  );
}

export function EnterpriseOverview({ onNavigate }) {
  const [collapsed, setCollapsed] = useState(false);
  const [activeNav, setActiveNav] = useState("概览");
  const [scope, setScope] = useState("本企业");
  const [period, setPeriod] = useState("本月");
  const [riskFilter, setRiskFilter] = useState("全部风险");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [showAllTodos, setShowAllTodos] = useState(false);
  const [lastUpdated, setLastUpdated] = useState("2026-08-11 09:30:00");
  const [notice, setNotice] = useState("");

  const metrics = scopeMetrics[scope];
  const filteredTodos = useMemo(() => {
    const matching = riskFilter === "中高风险" ? todoItems.filter((item) => item.riskLevel >= 2) : todoItems;
    return showAllTodos ? matching : matching.slice(0, 3);
  }, [riskFilter, showAllTodos]);

  const handleRefresh = () => {
    setLastUpdated(formatTime(new Date()));
    setNotice("概览数据已刷新");
  };

  const handleQuickEntry = (label) => {
    const routeKey = enterpriseRouteByLabel[label]
      ?? (label.includes("员工") ? "agents" : null)
      ?? (label.includes("审批") || label.includes("合同高风险") || label.includes("报价价格") || label.includes("版权") ? "approvals" : null)
      ?? (label.includes("智点") || label.includes("用量") ? "points" : null)
      ?? (label.includes("知识") ? "knowledge" : null)
      ?? (label.includes("记忆") ? "memory" : null)
      ?? (label.includes("任务") || label.includes("重试") || label.includes("排队") ? "tasks" : null)
      ?? (label.includes("权限") ? "audit" : null);
    if (routeKey && onNavigate) {
      onNavigate(routeKey);
      return;
    }
    setNotice(`已选择「${label}」，原型暂保留在企业概览。`);
  };

  return (
    <div className={`enterprise-shell${collapsed ? " is-collapsed" : ""}`}>
      <header className="enterprise-topbar">
        <div className="enterprise-brand">
          <img src="/assets/brand/dianlian-symbol.png" alt="点联" />
          <strong>点联企业管理中心</strong>
        </div>

        <div className="enterprise-topbar-actions">
          <button className="enterprise-company-switcher" type="button">
            星海会展集团
            <IconChevronDown size={16} />
          </button>
          <button className="enterprise-icon-button enterprise-notification" type="button" aria-label="通知">
            <IconBell size={21} />
            <span>6</span>
          </button>
          <button className="enterprise-role-switcher" type="button">
            企业管理员
            <IconChevronDown size={15} />
          </button>
          <img className="enterprise-admin-avatar" src="/assets/employees/quotation-specialist.png" alt="企业管理员" />
          <IconChevronDown className="enterprise-avatar-chevron" size={16} />
        </div>
      </header>

      <aside className="enterprise-sidebar" aria-label="企业管理导航">
        <nav>
          {sidebarGroups.map((group, groupIndex) => (
            <div className="enterprise-nav-group" key={group.label ?? `root-${groupIndex}`}>
              {group.label ? <div className="enterprise-nav-heading">{group.label}</div> : null}
              {group.items.map((item) => {
                const Icon = item.icon;
                const active = activeNav === item.label;
                return (
                  <button
                    className={`enterprise-nav-item${active ? " is-active" : ""}`}
                    key={item.label}
                    type="button"
                    onClick={() => {
                      setActiveNav(item.label);
                      onNavigate?.(enterpriseRouteByLabel[item.label]);
                    }}
                    aria-current={active ? "page" : undefined}
                    title={collapsed ? item.label : undefined}
                  >
                    <Icon size={19} stroke={1.8} />
                    <span>{item.label}</span>
                  </button>
                );
              })}
            </div>
          ))}
        </nav>

        <button className="enterprise-collapse-button" type="button" onClick={() => setCollapsed((value) => !value)}>
          <IconChevronsLeft size={19} />
          <span>{collapsed ? "展开菜单" : "收起菜单"}</span>
        </button>
      </aside>

      <main className="enterprise-content">
        <div className="enterprise-page-heading">
          <div>
            <h1>企业概览</h1>
            <p>查看与管理企业的数字员工运行、知识与记忆、审批及智点使用情况。</p>
          </div>
          <div className="enterprise-heading-actions">
            <div className="enterprise-update-time">
              数据更新于 {lastUpdated}
              <button type="button" onClick={handleRefresh} aria-label="刷新概览">
                <IconRefresh size={17} />
              </button>
            </div>
            <button className={`enterprise-filter-trigger${filtersOpen ? " is-active" : ""}`} type="button" onClick={() => setFiltersOpen((value) => !value)} aria-expanded={filtersOpen}>
              <IconAdjustments size={18} />
              自定义概览
            </button>
          </div>
        </div>

        {filtersOpen ? (
          <section className="enterprise-filter-panel" aria-label="概览筛选">
            <div className="enterprise-filter-group">
              <span>概览范围</span>
              <div className="enterprise-segmented-control">
                {Object.keys(scopeMetrics).map((item) => (
                  <button key={item} type="button" className={scope === item ? "is-selected" : ""} onClick={() => setScope(item)} aria-pressed={scope === item}>
                    {item}
                  </button>
                ))}
              </div>
            </div>
            <div className="enterprise-filter-group">
              <span>统计周期</span>
              <div className="enterprise-segmented-control">
                {["今日", "本周", "本月"].map((item) => (
                  <button key={item} type="button" className={period === item ? "is-selected" : ""} onClick={() => setPeriod(item)} aria-pressed={period === item}>
                    {item}
                  </button>
                ))}
              </div>
            </div>
            <div className="enterprise-filter-group">
              <span>待办风险</span>
              <div className="enterprise-segmented-control">
                {["全部风险", "中高风险"].map((item) => (
                  <button key={item} type="button" className={riskFilter === item ? "is-selected" : ""} onClick={() => setRiskFilter(item)} aria-pressed={riskFilter === item}>
                    {item}
                  </button>
                ))}
              </div>
            </div>
            <div className="enterprise-filter-summary">
              <IconSearch size={17} />
              当前：{scope} · {period} · {riskFilter}
            </div>
          </section>
        ) : null}

        {notice ? (
          <div className="enterprise-inline-notice" role="status">
            <IconCircleCheck size={17} />
            {notice}
            <button type="button" onClick={() => setNotice("")} aria-label="关闭提示">×</button>
          </div>
        ) : null}

        <section className="enterprise-metric-grid" aria-label={`${scope}${period}关键指标`}>
          {metrics.map((metric, index) => {
            const Icon = metric.icon;
            const trendClass = metric.trend === "alert" ? "danger" : metric.trend === "up" ? "positive" : metric.trend === "down" ? "positive" : "neutral";
            return (
              <article className="enterprise-metric-card" key={metric.label}>
                <div className="enterprise-metric-title">
                  <span className="enterprise-metric-icon"><Icon size={24} stroke={1.9} /></span>
                  <div>
                    <span>{metric.label}</span>
                    <strong>{metric.value} <small>{metric.unit}</small></strong>
                  </div>
                </div>
                <div className="enterprise-metric-footer">
                  <span>较昨日</span>
                  <b className={trendClass}>
                    {metric.trend === "alert" || metric.trend === "up" ? <IconArrowUp size={14} /> : metric.trend === "down" ? <IconArrowDown size={14} /> : null}
                    {metric.delta}
                  </b>
                  <div className="enterprise-sparkline"><Sparkline data={sparkSets[index]} color={index === 3 ? "#32b7dc" : "#2a73ed"} /></div>
                </div>
              </article>
            );
          })}
        </section>

        <section className="enterprise-dashboard-grid enterprise-grid-primary">
          <article className="enterprise-card enterprise-agents-card">
            <SectionHeader title="数字员工运行态" aside="查看全部" />
            <div className="enterprise-table enterprise-agents-table">
              <div className="enterprise-table-head">
                <span>数字员工</span><span>健康状态</span><span>当前任务</span><span>最后活动</span><span>今日智点</span><span>操作</span>
              </div>
              {employees.map((employee) => (
                <div className="enterprise-table-row" key={employee.name}>
                  <div className="enterprise-person-cell">
                    <img src={employee.avatar} alt="" />
                    <strong>{employee.name}</strong>
                  </div>
                  <span className={`enterprise-status-text ${employee.healthTone}`}><i />{employee.health}</span>
                  <span className="enterprise-multiline-cell">{employee.task}</span>
                  <span>{employee.active}</span>
                  <span>{employee.points}</span>
                  <button className="enterprise-outline-button" type="button" onClick={() => handleQuickEntry(`${employee.name}运行详情`)}>查看运行</button>
                </div>
              ))}
            </div>
            <button className="enterprise-card-footer-link" type="button" onClick={() => handleQuickEntry("全部数字员工")}>全部 12 人 <IconChevronRight size={16} /></button>
          </article>

          <article className="enterprise-card enterprise-todos-card">
            <SectionHeader title="待处理事项" aside={showAllTodos ? "收起" : "查看全部"} onAside={() => setShowAllTodos((value) => !value)} expanded={showAllTodos} />
            <div className="enterprise-table enterprise-todo-table">
              <div className="enterprise-table-head">
                <span>事项类型</span><span>摘要</span><span>Owner</span><span>截止时间</span><span>风险级别</span><span>操作</span>
              </div>
              {filteredTodos.map((item) => {
                const ItemIcon = item.icon;
                return (
                  <div className="enterprise-table-row" key={item.type}>
                    <div className="enterprise-todo-type"><span className={`enterprise-todo-icon ${item.tone}`}><ItemIcon size={16} /></span><strong>{item.type}</strong></div>
                    <span className="enterprise-multiline-cell">{item.summary}</span>
                    <div className="enterprise-person-cell compact"><img src={item.avatar} alt="" /><span>{item.owner}</span></div>
                    <span className={item.deadlineTone === "danger" ? "enterprise-danger-text" : ""}>{item.deadline}</span>
                    <span className={`enterprise-risk enterprise-risk-${item.riskLevel}`}>{item.risk}</span>
                    <button className="enterprise-outline-button" type="button" onClick={() => handleQuickEntry(item.type)}>去处理</button>
                  </div>
                );
              })}
            </div>
            <button className="enterprise-card-footer-link" type="button" onClick={() => setShowAllTodos(true)}>全部 {riskFilter === "中高风险" ? 4 : 5} 条 <IconChevronRight size={16} /></button>
          </article>
        </section>

        <section className="enterprise-dashboard-grid enterprise-grid-secondary">
          <article className="enterprise-card enterprise-points-card">
            <SectionHeader title="智点与费用" />
            <span className="enterprise-title-note">1 元 = 100 智点</span>
            <div className="enterprise-points-layout">
              <div className="enterprise-points-overview">
                <h3>本月智点使用情况</h3>
                <div className="enterprise-points-overview-body">
                  <div className="enterprise-point-legend">
                    {pointLegend.map((item) => (
                      <div key={item.label}><i style={{ background: item.color }} /><span>{item.label}</span><b>{item.value}</b><small>({item.percent})</small></div>
                    ))}
                  </div>
                  <div className="enterprise-donut-wrap">
                    <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 116, height: 116 }}>
                      <PieChart>
                        <Pie data={pointPie} dataKey="value" innerRadius={36} outerRadius={52} startAngle={90} endAngle={-270} stroke="none" isAnimationActive={false}>
                          {pointPie.map((entry) => <Cell key={entry.name} fill={entry.color} />)}
                        </Pie>
                        <Tooltip formatter={(value) => `${value}%`} />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="enterprise-donut-label"><strong>60,000</strong><span>总智点</span></div>
                  </div>
                </div>
              </div>
              <div className="enterprise-capability-usage">
                <h3>能力消耗占比（已消耗）</h3>
                {capabilityUsage.map((item) => (
                  <div className="enterprise-capability-row" key={item.name}>
                    <span>{item.name}</span>
                    <div><i style={{ width: `${item.percent * 2.15}%`, background: item.color }} /></div>
                    <b>{item.value.toLocaleString()} <small>({item.percent}%)</small></b>
                  </div>
                ))}
              </div>
            </div>
            <div className="enterprise-card-link-row">
              <button type="button" onClick={() => handleQuickEntry("智点明细")}>查看智点明细 <IconChevronRight size={16} /></button>
              <button type="button" onClick={() => handleQuickEntry("智点、预算与费用")}>智点、预算与费用 <IconChevronRight size={16} /></button>
              <button type="button" onClick={() => handleQuickEntry("用量趋势分析")}>用量趋势分析 <IconChevronRight size={16} /></button>
            </div>
          </article>

          <article className="enterprise-card enterprise-knowledge-card">
            <SectionHeader title="知识与记忆处理" aside="查看全部" />
            <div className="enterprise-knowledge-table">
              <div className="enterprise-table-head"><span>处理类型</span><span>进行中</span><span>已完成（今日）</span><span>待确认候选</span><span>失败（今日）</span></div>
              {knowledgeRows.map((row) => (
                <div className="enterprise-table-row" key={row.name}>
                  <strong>{row.name}</strong><span className="blue">{row.running}</span><span>{row.complete}</span><span className={row.confirm === "—" ? "" : "red"}>{row.confirm}</span><span className={row.failed ? "red" : ""}>{row.failed}</span>
                </div>
              ))}
            </div>
            <div className="enterprise-card-link-row">
              <button type="button" onClick={() => handleQuickEntry("企业知识")}>进入企业知识 <IconChevronRight size={16} /></button>
              <button type="button" onClick={() => handleQuickEntry("记忆治理")}>记忆治理 <IconChevronRight size={16} /></button>
              <button type="button" onClick={() => handleQuickEntry("处理任务监控")}>处理任务监控 <IconChevronRight size={16} /></button>
            </div>
          </article>
        </section>

        <section className="enterprise-bottom-grid">
          <article className="enterprise-card enterprise-anomaly-card">
            <SectionHeader title="任务异常与恢复" aside="查看全部" />
            <div className="enterprise-anomaly-head"><span>异常类型</span><span>数量</span><span>典型原因</span><span>影响范围</span><span>建议操作</span></div>
            {anomalyRows.map((row) => (
              <div className="enterprise-anomaly-row" key={row.label}>
                <div><span className={`enterprise-anomaly-icon ${row.tone}`}><IconAlertTriangle size={15} /></span><strong>{row.label}</strong></div>
                <span>{row.count}</span><span>{row.reason}</span><span>{row.impact}</span>
                <button className="enterprise-outline-button" type="button" onClick={() => handleQuickEntry(row.action)}>{row.action}</button>
              </div>
            ))}
          </article>

          <article className="enterprise-card enterprise-platform-note">
            <SectionHeader title="平台说明" />
            <ul>
              <li>本页数据为企业域内汇总，可能存在延迟，仅供运营参考。</li>
              <li>平台模型、服务商价格与平台运营信息在本页面不可见。</li>
              <li>合同正文与报价敏感毛利数据不在概览展示，需授权后查看。</li>
              <li>如需变更数据与权限，请联系平台管理员。</li>
            </ul>
          </article>

          <article className="enterprise-card enterprise-quick-card">
            <SectionHeader title="快速入口" />
            <div className="enterprise-quick-grid">
              {quickEntries.map((item) => {
                const Icon = item.icon;
                return <button key={item.label} type="button" onClick={() => handleQuickEntry(item.label)}><Icon size={21} /><span>{item.label}</span><IconChevronRight size={17} /></button>;
              })}
            </div>
          </article>
        </section>
      </main>
    </div>
  );
}

export default EnterpriseOverview;
