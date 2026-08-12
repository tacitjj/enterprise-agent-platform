import { useEffect, useMemo, useRef, useState } from "react";
import {
  IconActivity,
  IconAlertTriangle,
  IconArrowsExchange,
  IconBell,
  IconBook,
  IconBox,
  IconBuilding,
  IconBuildingSkyscraper,
  IconCalendar,
  IconChartBar,
  IconChevronDown,
  IconChevronLeft,
  IconCircleCheck,
  IconClock,
  IconCoinYen,
  IconCpu,
  IconDatabase,
  IconDeviceDesktopAnalytics,
  IconExternalLink,
  IconFileText,
  IconInfoCircle,
  IconLink,
  IconReceipt2,
  IconShieldCheck,
  IconTag,
  IconUsers,
  IconWallet,
  IconX,
} from "@tabler/icons-react";
import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { PlatformModules } from "./PlatformModules.jsx";
import "./platform.css";

const trendData = [
  { day: "06-01", points: 58, cost: 9.8, contribution: 3.2 },
  { day: "06-02", points: 54, cost: 11.5, contribution: 3.0 },
  { day: "06-03", points: 68, cost: 15.8, contribution: 6.6 },
  { day: "06-04", points: 84, cost: 13.1, contribution: 4.0 },
  { day: "06-05", points: 69, cost: 16.7, contribution: 7.4 },
  { day: "06-06", points: 71, cost: 14.2, contribution: 6.2 },
  { day: "06-07", points: 76, cost: 18.3, contribution: 8.6 },
];

const capabilityData = [
  { id: "graphic", name: "平面出图", value: 56.21, points: "271.53万", color: "#1768e5" },
  { id: "contract", name: "合同审核", value: 24.37, points: "117.61万", color: "#27a9d0" },
  { id: "quotation", name: "报价", value: 12.44, points: "60.04万", color: "#43b88b" },
  { id: "other", name: "其他", value: 7.98, points: "38.47万", color: "#dbe3ef" },
];

const dateRanges = [
  { id: "7d", label: "近 7 天", range: "2025-06-01  ～  2025-06-07" },
  { id: "30d", label: "近 30 天", range: "2025-05-09  ～  2025-06-07" },
  { id: "month", label: "本月", range: "2025-06-01  ～  2025-06-30" },
];

const capabilityOptions = [
  { id: "all", label: "全部能力" },
  { id: "graphic", label: "平面出图" },
  { id: "contract", label: "合同审核" },
  { id: "quotation", label: "报价" },
];

const tenants = [
  { name: "星海会展集团", agents: 312, tasks: "1,246", points: "482,650", alarm: "中", status: "正常" },
  { name: "蓝海设计院", agents: 184, tasks: 861, points: "321,780", alarm: "低", status: "正常" },
  { name: "智联咨询", agents: 156, tasks: 612, points: "198,430", alarm: "中", status: "正常" },
  { name: "金禾地产", agents: 128, tasks: 498, points: "156,210", alarm: "高", status: "受限" },
  { name: "启明科技", agents: 97, tasks: 387, points: "121,350", alarm: "低", status: "正常" },
];

const providerRows = [
  { name: "火山方舟", uptime: "99.95%", latency: "642 ms", error: "0.22%", cost: "¥12,342", degrade: "无" },
  { name: "阿里云百炼", uptime: "99.88%", latency: "715 ms", error: "0.34%", cost: "¥9,873", degrade: "无" },
  { name: "腾讯云 TI", uptime: "99.92%", latency: "688 ms", error: "0.41%", cost: "¥6,321", degrade: "模型降级" },
  { name: "百度千帆", uptime: "99.73%", latency: "881 ms", error: "0.78%", cost: "¥3,306", degrade: "区域降级" },
];

const templateRows = [
  { name: "平面出图", version: "v2.4.1", count: 98, status: "已全量" },
  { name: "法务合同审核", version: "v2.2.0", count: 112, status: "已全量" },
  { name: "报价", version: "v2.1.3", count: 96, status: "灰度中（30%）" },
];

const alerts = [
  {
    id: "ALT-1208",
    level: "高",
    title: "SSE 重放缺口",
    scope: "2 个租户",
    time: "06-07 11:23",
    status: "处理中",
    summary: "检测到消费游标超出保留窗口，已要求客户端重新获取办公室快照。",
    suggestion: "核对事件保留窗口与慢消费者告警，确认重置后无重复调用与重复扣费。",
  },
  {
    id: "ALT-1207",
    level: "中",
    title: "运行时租约接管",
    scope: "1 个租户",
    time: "06-07 10:52",
    status: "待确认",
    summary: "一个活跃 Run 的 heartbeat 超时，持久 Run Supervisor 已完成唯一接管。",
    suggestion: "检查旧 execution generation 的迟到事件是否均被 fencing 拒绝。",
  },
  {
    id: "ALT-1206",
    level: "中",
    title: "Provider 慢响应",
    scope: "全平台",
    time: "06-07 10:31",
    status: "观察中",
    summary: "腾讯云 TI 的 P95 延迟超过健康阈值，部分流量已进入受控降级。",
    suggestion: "继续观察 15 分钟健康窗口；若触发备用模型，先校验追加预占。",
  },
  {
    id: "ALT-1205",
    level: "低",
    title: "租户配额接近上限",
    scope: "3 个租户",
    time: "06-07 09:18",
    status: "已提醒",
    summary: "三个租户的可用智点低于企业预算策略阈值。",
    suggestion: "提醒企业管理员检查预算和进行中任务，不直接为企业自动增发智点。",
  },
];

const navGroups = [
  {
    title: "租户运营",
    items: [{ label: "租户运营", icon: IconUsers }],
  },
  {
    title: "员工生态",
    items: [
      { label: "官方模板", icon: IconFileText },
      { label: "技能中心", icon: IconBox },
      { label: "行业知识", icon: IconBook },
    ],
  },
  {
    title: "模型与 Provider",
    items: [
      { label: "Provider", icon: IconLink },
      { label: "官方模型", icon: IconCpu },
    ],
  },
  {
    title: "定价与财务",
    items: [
      { label: "供应商费率", icon: IconTag },
      { label: "企业销售价格", icon: IconTag },
      { label: "智点账本", icon: IconWallet },
      { label: "调用成本与对账", icon: IconArrowsExchange },
    ],
  },
  {
    title: "运行治理",
    items: [
      { label: "运行监控", icon: IconDeviceDesktopAnalytics },
      { label: "安全与审计", icon: IconShieldCheck },
    ],
  },
];

const platformRouteByLabel = {
  经营总览: "overview",
  租户运营: "tenants",
  官方模板: "agent-templates",
  技能中心: "skills",
  行业知识: "industry-knowledge",
  Provider: "providers",
  官方模型: "models",
  供应商费率: "rates",
  企业销售价格: "multipliers",
  智点账本: "points",
  调用成本与对账: "usage",
  运行监控: "monitoring",
  安全与审计: "audit",
};

const platformLabelByRoute = Object.fromEntries(Object.entries(platformRouteByLabel).map(([label, key]) => [key, label]));

const anomalyRows = [
  { label: "未匹配 Provider 发票行", count: 23, tone: "danger" },
  { label: "账本不平衡（笔数）", count: 0, tone: "success" },
  { label: "未知成本调用（未归因）", count: 17, tone: "warning" },
  { label: "调账任务（待处理）", count: 9, tone: "warning" },
];

const metricConfig = [
  {
    key: "enterprise",
    label: "活跃企业",
    value: "126",
    delta: "+8（+6.78%）",
    tone: "blue",
    icon: IconBuildingSkyscraper,
    note: "定义：有消耗的独立企业数",
  },
  {
    key: "points",
    label: "企业智点消耗",
    value: "4,826,500",
    delta: "+512,300（+11.89%）",
    tone: "cyan",
    icon: IconDatabase,
    note: "定义：已计费的智点总量",
  },
  {
    key: "cost",
    label: "Provider 实际成本",
    value: "¥31,842",
    delta: "+3,421（+12.04%）",
    tone: "indigo",
    icon: IconBox,
    note: "定义：Provider 实际发生成本",
    deltaTone: "danger",
  },
  {
    key: "contribution",
    label: "直接贡献额",
    value: "¥16,423",
    delta: "+2,138（+14.94%）",
    tone: "teal",
    icon: IconCoinYen,
    note: "定义：企业收入 − 直接成本",
  },
];

function LevelBadge({ level }) {
  const tone = level === "高" ? "danger" : level === "中" ? "warning" : "success";
  return <span className={`po-badge po-badge--${tone}`}>{level}</span>;
}

function StatusBadge({ status }) {
  const tone = status.includes("正常") || status.includes("全量") ? "success" : status.includes("灰度") ? "info" : "danger";
  return <span className={`po-status po-status--${tone}`}>{status}</span>;
}

function SectionLink({ children, onClick }) {
  return (
    <button type="button" className="po-section-link" onClick={onClick}>
      {children}
      <IconExternalLink size={14} stroke={1.8} />
    </button>
  );
}

function PlatformTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="po-chart-tooltip">
      <strong>{label}</strong>
      {payload.map((item) => (
        <div key={item.dataKey}>
          <span style={{ backgroundColor: item.color }} />
          {item.name}：{item.value}
          {item.dataKey === "points" ? " 万点" : " 万元"}
        </div>
      ))}
    </div>
  );
}

export function PlatformOverview({ moduleKey = "overview", onNavigate }) {
  const [dateRange, setDateRange] = useState(dateRanges[0]);
  const [capability, setCapability] = useState(capabilityOptions[0]);
  const [dateMenuOpen, setDateMenuOpen] = useState(false);
  const [capabilityMenuOpen, setCapabilityMenuOpen] = useState(false);
  const [drawerMode, setDrawerMode] = useState(null);
  const [selectedAlert, setSelectedAlert] = useState(null);
  const [activeNav, setActiveNav] = useState(platformLabelByRoute[moduleKey] ?? "经营总览");
  const drawerCloseRef = useRef(null);
  const drawerTriggerRef = useRef(null);

  const selectedCapabilityData = useMemo(() => {
    if (capability.id === "all") return capabilityData;
    const selected = capabilityData.find((item) => item.id === capability.id);
    return selected
      ? [selected, { id: "remaining", name: "其他能力", value: 100 - selected.value, points: "—", color: "#e3e9f2" }]
      : capabilityData;
  }, [capability]);

  const filteredTrend = useMemo(() => {
    const factor = capability.id === "graphic" ? 0.5621 : capability.id === "contract" ? 0.2437 : capability.id === "quotation" ? 0.1244 : 1;
    return trendData.map((item) => ({
      ...item,
      points: Number((item.points * factor).toFixed(1)),
      cost: Number((item.cost * factor).toFixed(1)),
      contribution: Number((item.contribution * factor).toFixed(1)),
    }));
  }, [capability]);

  const openDrawer = (mode, alert = null) => {
    drawerTriggerRef.current = document.activeElement;
    setDrawerMode(mode);
    setSelectedAlert(alert);
  };

  const navigateTo = (key) => {
    setActiveNav(platformLabelByRoute[key] ?? "经营总览");
    onNavigate?.(key);
  };

  useEffect(() => {
    setActiveNav(platformLabelByRoute[moduleKey] ?? "经营总览");
  }, [moduleKey]);

  const closeDrawer = () => {
    setDrawerMode(null);
    setSelectedAlert(null);
    requestAnimationFrame(() => drawerTriggerRef.current?.focus());
  };

  useEffect(() => {
    if (!drawerMode) return undefined;
    drawerCloseRef.current?.focus();
    const closeOnEscape = (event) => {
      if (event.key === "Escape") closeDrawer();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [drawerMode]);

  return (
    <div className="platform-overview">
      <header className="po-topbar">
        <div className="po-brand">
          <img src="/assets/brand/dianlian-logo.png" alt="点联" />
        </div>
        <div className="po-topbar-actions">
          <button type="button" className="po-top-select">
            <IconBuilding size={17} />
            点联平台
            <IconChevronDown size={15} />
          </button>
          <button type="button" className="po-top-select po-top-select--env">
            <span className="po-online-dot" />
            生产
            <IconChevronDown size={15} />
          </button>
          <button type="button" className="po-bell" aria-label="打开运行告警" onClick={() => openDrawer("alerts")}>
            <IconBell size={21} stroke={1.7} />
            <span>12</span>
          </button>
          <div className="po-operator">
            <strong>平台运营</strong>
            <img src="/assets/employees/quotation-specialist.png" alt="平台运营人员" />
            <IconChevronDown size={15} />
          </div>
        </div>
      </header>

      <aside className="po-sidebar">
        <button
          type="button"
          className={`po-nav-overview ${activeNav === "经营总览" ? "is-active" : ""}`}
          aria-current={activeNav === "经营总览" ? "page" : undefined}
          onClick={() => navigateTo("overview")}
        >
          <IconChartBar size={20} stroke={1.8} />
          经营总览
        </button>
        {navGroups.map((group) => (
          <div className="po-nav-group" key={group.title}>
            <p>{group.title}</p>
            {group.items.map((item) => {
              const NavIcon = item.icon;
              return (
                <button
                  type="button"
                  key={item.label}
                  className={activeNav === item.label ? "is-active" : ""}
                  aria-current={activeNav === item.label ? "page" : undefined}
                  onClick={() => navigateTo(platformRouteByLabel[item.label])}
                >
                  <NavIcon size={18} stroke={1.65} />
                  {item.label}
                </button>
              );
            })}
          </div>
        ))}
      </aside>

      {moduleKey === "overview" ? <main className="po-main">
        <section className="po-page-heading">
          <div>
            <div className="po-title-row">
              <h1>经营总览</h1>
              <span className="po-privacy-pill">
                内容默认不可见
                <IconInfoCircle size={13} />
              </span>
            </div>
            <p>
              数据范围：平台可见的租户元数据、使用量、成本、费率版本、追踪 ID 与健康状态；不包含企业合同正文、源图、提示词、报价成本明细与私有记忆。
            </p>
          </div>
          <div className="po-page-actions">
            <div className="po-filter-wrap">
              <button type="button" className="po-filter-button" aria-expanded={capabilityMenuOpen} aria-controls="platform-capability-menu" onClick={() => setCapabilityMenuOpen((open) => !open)}>
                <IconActivity size={17} />
                {capability.label}
                <IconChevronDown size={15} />
              </button>
              {capabilityMenuOpen && (
                <div className="po-popover po-popover--compact" id="platform-capability-menu">
                  {capabilityOptions.map((option) => (
                    <button
                      type="button"
                      key={option.id}
                      className={capability.id === option.id ? "is-selected" : ""}
                      onClick={() => {
                        setCapability(option);
                        setCapabilityMenuOpen(false);
                      }}
                    >
                      {option.label}
                      {capability.id === option.id && <IconCircleCheck size={15} />}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className="po-filter-wrap">
              <button type="button" className="po-date-button" aria-expanded={dateMenuOpen} aria-controls="platform-date-menu" onClick={() => setDateMenuOpen((open) => !open)}>
                <span>{dateRange.range}</span>
                <IconCalendar size={17} />
              </button>
              {dateMenuOpen && (
                <div className="po-popover po-popover--date" id="platform-date-menu">
                  {dateRanges.map((option) => (
                    <button
                      type="button"
                      key={option.id}
                      className={dateRange.id === option.id ? "is-selected" : ""}
                      onClick={() => {
                        setDateRange(option);
                        setDateMenuOpen(false);
                      }}
                    >
                      <span>{option.label}</span>
                      <small>{option.range}</small>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <button type="button" className="po-secondary-button" onClick={() => openDrawer("reconciliation")}>
              查看对账
            </button>
            <button type="button" className="po-primary-button" onClick={() => openDrawer("monitor")}>
              运行监控
            </button>
          </div>
        </section>

        <section className="po-metric-grid" aria-label="经营关键指标">
          {metricConfig.map((metric) => {
            const MetricIcon = metric.icon;
            return (
              <article className="po-card po-metric-card" key={metric.key}>
                <div className={`po-metric-icon po-metric-icon--${metric.tone}`}>
                  <MetricIcon size={28} stroke={1.65} />
                </div>
                <div className="po-metric-copy">
                  <p>
                    {metric.label}
                    <IconInfoCircle size={14} />
                  </p>
                  <strong>{metric.value}</strong>
                  <div>
                    <span>较上周</span>
                    <b className={metric.deltaTone === "danger" ? "is-negative" : ""}>{metric.delta}</b>
                  </div>
                  <small>时间范围：{dateRange.label}　{metric.note}</small>
                </div>
              </article>
            );
          })}
        </section>

        <section className="po-chart-grid">
          <article className="po-card po-panel po-trend-card">
            <div className="po-panel-header">
              <div>
                <h2>消耗、成本与贡献趋势</h2>
                <span className="po-panel-subtitle">{capability.label} · {dateRange.label}</span>
              </div>
              <button type="button" className="po-mini-select">
                按天
                <IconChevronDown size={14} />
              </button>
            </div>
            <div className="po-chart-legend">
              <span><i className="is-bar" />智点消耗（万点）</span>
              <span><i className="is-cost" />Provider 实际成本（万元）</span>
              <span><i className="is-contribution" />直接贡献额（万元）</span>
            </div>
            <div className="po-trend-chart">
              <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 600, height: 210 }}>
                <ComposedChart data={filteredTrend} margin={{ top: 10, right: 4, bottom: 0, left: -18 }}>
                  <CartesianGrid stroke="#e8eef6" strokeDasharray="4 4" vertical={false} />
                  <XAxis dataKey="day" axisLine={false} tickLine={false} tick={{ fill: "#66758d", fontSize: 11 }} />
                  <YAxis yAxisId="left" domain={[0, 100]} axisLine={false} tickLine={false} tick={{ fill: "#66758d", fontSize: 11 }} />
                  <YAxis yAxisId="right" orientation="right" domain={[0, 40]} axisLine={false} tickLine={false} tick={{ fill: "#66758d", fontSize: 11 }} />
                  <Tooltip content={<PlatformTooltip />} />
                  <Bar yAxisId="left" dataKey="points" name="智点消耗" fill="#c9ddff" radius={[3, 3, 0, 0]} barSize={18} />
                  <Line yAxisId="right" type="monotone" dataKey="cost" name="Provider 成本" stroke="#2aaed5" strokeWidth={2} dot={{ r: 2, fill: "#2aaed5" }} />
                  <Line yAxisId="right" type="monotone" dataKey="contribution" name="直接贡献额" stroke="#42b883" strokeWidth={2} dot={{ r: 2, fill: "#42b883" }} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </article>

          <article className="po-card po-panel po-capability-card">
            <div className="po-panel-header">
              <div>
                <h2>能力消耗占比（{dateRange.label}）</h2>
                <span className="po-panel-subtitle">仅显示调用元数据与计费聚合</span>
              </div>
            </div>
            <div className="po-capability-content">
              <div className="po-donut-wrap">
                <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 180, height: 180 }}>
                  <PieChart>
                    <Pie data={selectedCapabilityData} dataKey="value" innerRadius={52} outerRadius={74} paddingAngle={1} stroke="none">
                      {selectedCapabilityData.map((item) => <Cell key={item.id} fill={item.color} />)}
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
                <div className="po-donut-center">
                  <strong>{capability.id === "all" ? "482.65万" : capabilityData.find((item) => item.id === capability.id)?.points}</strong>
                  <span>{capability.id === "all" ? "总智点消耗" : capability.label}</span>
                </div>
              </div>
              <div className="po-capability-list">
                {capabilityData.map((item) => (
                  <button
                    type="button"
                    key={item.id}
                    className={capability.id === item.id ? "is-active" : ""}
                    onClick={() => {
                      const option = capabilityOptions.find((candidate) => candidate.id === item.id);
                      if (option) setCapability(option);
                    }}
                  >
                    <i style={{ backgroundColor: item.color }} />
                    <span>{item.name}</span>
                    <b>{item.value.toFixed(2)}%</b>
                    <em>{item.points}</em>
                  </button>
                ))}
              </div>
            </div>
          </article>
        </section>

        <section className="po-data-grid">
          <article className="po-card po-panel">
            <div className="po-panel-header">
              <h2>租户运行概况（{dateRange.label}）</h2>
            </div>
            <div className="po-table-wrap">
              <table className="po-table">
                <thead><tr><th>租户</th><th>活跃员工</th><th>运行任务</th><th>计费智点</th><th>告警</th><th>账户</th></tr></thead>
                <tbody>
                  {tenants.map((tenant) => (
                    <tr key={tenant.name}>
                      <td>{tenant.name}</td><td>{tenant.agents}</td><td>{tenant.tasks}</td><td>{tenant.points}</td>
                      <td><LevelBadge level={tenant.alarm} /></td><td><StatusBadge status={tenant.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <SectionLink onClick={() => navigateTo("tenants")}>查看全部租户</SectionLink>
          </article>

          <article className="po-card po-panel">
            <div className="po-panel-header">
              <h2>Provider 健康与尝试（近 15 分钟）</h2>
            </div>
            <div className="po-table-wrap">
              <table className="po-table po-provider-table">
                <thead><tr><th>Provider</th><th>可用性</th><th>P95 延迟</th><th>错误率</th><th>待结成本</th><th>最新降级</th></tr></thead>
                <tbody>
                  {providerRows.map((provider) => (
                    <tr key={provider.name}>
                      <td>{provider.name}</td><td>{provider.uptime}</td><td>{provider.latency}</td><td>{provider.error}</td><td>{provider.cost}</td><td>{provider.degrade}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="po-inline-note">
              <IconInfoCircle size={14} />
              上表为 Provider 尝试元数据；平台仅展示成功与失败调用的健康与成本，不展示企业输入或输出正文。
            </div>
            <SectionLink onClick={() => openDrawer("monitor")}>查看 Provider 详情</SectionLink>
          </article>

          <article className="po-card po-panel">
            <div className="po-panel-header">
              <h2>模板与版本（官方模板）</h2>
            </div>
            <div className="po-table-wrap">
              <table className="po-table">
                <thead><tr><th>模板</th><th>已发布版本</th><th>企业实例数</th><th>上线状态</th></tr></thead>
                <tbody>
                  {templateRows.map((template) => (
                    <tr key={template.name}>
                      <td>{template.name}</td><td>{template.version}</td><td>{template.count}</td><td><StatusBadge status={template.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <SectionLink onClick={() => navigateTo("agent-templates")}>查看模板与版本</SectionLink>
          </article>
        </section>

        <section className="po-bottom-grid">
          <article className="po-card po-panel">
            <div className="po-panel-header"><h2>对账与账本异常（队列）</h2></div>
            <div className="po-anomaly-list">
              {anomalyRows.map((item) => (
                <button type="button" key={item.label} onClick={() => openDrawer("reconciliation")}>
                  <span className={`po-anomaly-dot po-anomaly-dot--${item.tone}`} />
                  <span>{item.label}</span>
                  <strong className={`is-${item.tone}`}>{item.count}</strong>
                </button>
              ))}
            </div>
            <SectionLink onClick={() => openDrawer("reconciliation")}>查看对账中心</SectionLink>
          </article>

          <article className="po-card po-panel">
            <div className="po-panel-header"><h2>运行告警（当前）</h2></div>
            <div className="po-alert-table">
              <div className="po-alert-table-head"><span>级别</span><span>告警项</span><span>影响范围</span><span>首次时间</span><span>操作</span></div>
              {alerts.map((alert) => (
                <button type="button" key={alert.id} onClick={() => openDrawer("alerts", alert)}>
                  <LevelBadge level={alert.level} />
                  <span>{alert.title}</span><span>{alert.scope}</span><span>{alert.time}</span><em>查看详情</em>
                </button>
              ))}
            </div>
            <SectionLink onClick={() => openDrawer("alerts")}>查看全部告警</SectionLink>
          </article>

          <article className="po-card po-panel po-scope-card">
            <div className="po-panel-header"><h2>数据范围说明</h2></div>
            <ul>
              <li><IconCircleCheck size={15} />本页数据基于平台可见范围汇总计算。</li>
              <li><IconCircleCheck size={15} />不展示企业合同正文、源图、提示词、报价成本明细与私有记忆。</li>
              <li><IconCircleCheck size={15} />可通过追踪 ID 查询健康与成本，不涉及业务内容本身。</li>
              <li><IconCircleCheck size={15} />访问敏感元数据需要最小必要权限与审批流程。</li>
            </ul>
            <SectionLink onClick={() => navigateTo("audit")}>查看数据权限与审计</SectionLink>
          </article>
        </section>
      </main> : <PlatformModules moduleKey={moduleKey} />}

      {drawerMode && (
        <div className="po-drawer-layer" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && closeDrawer()}>
          <aside className="po-drawer" role="dialog" aria-modal="true" aria-label="平台详情">
            <div className="po-drawer-header">
              <div>
                <span className="po-eyebrow">平台元数据视图</span>
                <h2>
                  {drawerMode === "alerts" ? (selectedAlert ? "告警详情" : "运行告警") : drawerMode === "monitor" ? "运行监控" : "对账详情"}
                </h2>
              </div>
              <button ref={drawerCloseRef} type="button" aria-label="关闭" onClick={closeDrawer}><IconX size={20} /></button>
            </div>

            {drawerMode === "alerts" && selectedAlert && (
              <div className="po-drawer-body">
                <button type="button" className="po-back-button" onClick={() => setSelectedAlert(null)}><IconChevronLeft size={16} />返回告警列表</button>
                <div className="po-detail-title"><LevelBadge level={selectedAlert.level} /><h3>{selectedAlert.title}</h3></div>
                <dl className="po-detail-list">
                  <div><dt>追踪 ID</dt><dd>{selectedAlert.id}</dd></div>
                  <div><dt>影响范围</dt><dd>{selectedAlert.scope}</dd></div>
                  <div><dt>首次时间</dt><dd>{selectedAlert.time}</dd></div>
                  <div><dt>处理状态</dt><dd>{selectedAlert.status}</dd></div>
                </dl>
                <section className="po-drawer-section"><h4>元数据摘要</h4><p>{selectedAlert.summary}</p></section>
                <section className="po-drawer-section"><h4>建议动作</h4><p>{selectedAlert.suggestion}</p></section>
                <div className="po-protected-note"><IconShieldCheck size={18} />平台运营视角不显示关联企业的消息、文件、提示词或成果正文。</div>
              </div>
            )}

            {drawerMode === "alerts" && !selectedAlert && (
              <div className="po-drawer-body po-drawer-list">
                {alerts.map((alert) => (
                  <button type="button" key={alert.id} onClick={() => setSelectedAlert(alert)}>
                    <LevelBadge level={alert.level} />
                    <span><strong>{alert.title}</strong><small>{alert.scope} · {alert.time}</small></span>
                    <IconChevronDown size={16} className="po-rotate-left" />
                  </button>
                ))}
              </div>
            )}

            {drawerMode === "monitor" && (
              <div className="po-drawer-body">
                <div className="po-drawer-kpis">
                  <div><IconActivity size={20} /><span>活跃 Run</span><strong>1,904</strong></div>
                  <div><IconClock size={20} /><span>P95 执行延迟</span><strong>8.6 s</strong></div>
                  <div><IconAlertTriangle size={20} /><span>需关注</span><strong>12</strong></div>
                </div>
                <section className="po-drawer-section"><h4>健康摘要</h4><p>Java 任务监督、Python Run Supervisor 与 Provider 尝试均处于可追踪状态。当前有 1 次租约接管和 1 组受控模型降级。</p></section>
                <div className="po-timeline">
                  <div><i className="is-success" /><span><strong>11:25</strong> OfficeSnapshot 重置完成，未产生重复调用。</span></div>
                  <div><i className="is-info" /><span><strong>11:18</strong> Provider 健康路由恢复至观察状态。</span></div>
                  <div><i className="is-warning" /><span><strong>10:52</strong> Run lease 超时，fencing 后唯一接管。</span></div>
                </div>
                <div className="po-protected-note"><IconShieldCheck size={18} />运行监控仅包含状态、事件序号、耗时和追踪 ID。</div>
              </div>
            )}

            {drawerMode === "reconciliation" && (
              <div className="po-drawer-body">
                <div className="po-drawer-kpis">
                  <div><IconReceipt2 size={20} /><span>待匹配账单行</span><strong>23</strong></div>
                  <div><IconArrowsExchange size={20} /><span>未知成本调用</span><strong>17</strong></div>
                  <div><IconCircleCheck size={20} /><span>账本差异</span><strong>0</strong></div>
                </div>
                <section className="po-drawer-section"><h4>本期对账</h4><p>企业智点扣费、销售价格快照、Provider Attempt 暂估/实际成本和供应商账单行保持独立，可逐层追溯。</p></section>
                <div className="po-reconcile-list">
                  <div><span>阿里云百炼 · 账单批次 BL-0607</span><StatusBadge status="正常" /></div>
                  <div><span>火山方舟 · 23 行待匹配</span><span className="po-status po-status--danger">待处理</span></div>
                  <div><span>腾讯云 TI · 降级成本差异</span><span className="po-status po-status--info">核对中</span></div>
                </div>
                <div className="po-protected-note"><IconShieldCheck size={18} />账单核对不提供企业报价业务成本、合同正文或图像内容。</div>
              </div>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}

export default PlatformOverview;
