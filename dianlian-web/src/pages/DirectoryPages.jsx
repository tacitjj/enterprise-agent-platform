import { useEffect, useMemo, useState } from "react";
import {
  IconAlertTriangle,
  IconArrowRight,
  IconBook2,
  IconCircleCheck,
  IconClock,
  IconCoinYuan,
  IconFilter,
  IconListCheck,
  IconReceipt,
  IconRobot,
  IconSearch,
  IconShieldLock,
} from "@tabler/icons-react";
import { EventWorkSurface } from "../components/EventWorkSurface.jsx";
import { StatusChip } from "../components/StatusChip.jsx";
import "./directory.css";

const ALL_CAPABILITIES = "__ALL_CAPABILITIES__";

const runningTaskStatuses = new Set(["PLANNING", "QUEUED", "RUNNING", "APPLYING_GUIDANCE", "REPLANNING"]);
const waitingTaskStatuses = new Set(["WAITING_USER", "WAITING_CONFIRMATION", "WAITING_APPROVAL", "PAUSED"]);
const exceptionTaskStatuses = new Set(["FAILED", "PARTIAL_SUCCESS"]);

function statusToneClass(status) {
  return ["WORKING", "WAITING_USER", "WAITING_APPROVAL", "NEEDS_ATTENTION", "IDLE"].includes(status)
    ? status.toLowerCase().replaceAll("_", "-")
    : "idle";
}

function capabilityLabel(agent) {
  return agent.capabilityLabel?.trim() || agent.capability?.trim() || "未命名能力";
}

function capabilityBadge(agent) {
  const label = capabilityLabel(agent);
  const hanCharacters = Array.from(label).filter((character) => /[\u3400-\u9fff]/u.test(character));
  if (hanCharacters.length > 0) return hanCharacters.slice(0, 2).join("");

  const labelWords = label.match(/[A-Za-z0-9]+/g) ?? [];
  if (labelWords.length > 1) return labelWords.slice(0, 3).map((word) => word[0]).join("").toUpperCase();

  const capabilityWords = (agent.capability ?? "").split("_").filter(Boolean);
  if (capabilityWords.length > 1) return capabilityWords.slice(0, 3).map((word) => word[0]).join("").toUpperCase();

  return Array.from(label.replaceAll(" ", "")).slice(0, 3).join("").toUpperCase();
}

function buildCapabilityFilters(agents) {
  const capabilities = new Map();
  agents.forEach((agent) => {
    const id = agent.capability?.trim();
    if (!id) return;

    const label = capabilityLabel(agent);
    if (!capabilities.has(id) || capabilities.get(id) === id) capabilities.set(id, label);
  });
  return [[ALL_CAPABILITIES, "全部"], ...capabilities.entries()];
}

export function EmployeesPage({ agents, onOpenAgent, onClose }) {
  const [query, setQuery] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [capability, setCapability] = useState(ALL_CAPABILITIES);
  const capabilityFilters = useMemo(() => buildCapabilityFilters(agents), [agents]);
  const activeCapability = capabilityFilters.some(([id]) => id === capability)
    ? capability
    : ALL_CAPABILITIES;
  useEffect(() => {
    if (capability !== activeCapability) setCapability(activeCapability);
  }, [activeCapability, capability]);
  const visible = useMemo(
    () => agents.filter((agent) => (
      `${agent.name}${agent.capabilityLabel}${agent.profile}${agent.skills.join("")}`.includes(query.trim())
      && (activeCapability === ALL_CAPABILITIES || agent.capability === activeCapability)
    )),
    [activeCapability, agents, query],
  );
  const workingCount = agents.filter((agent) => agent.status === "WORKING").length;
  const waitingCount = agents.filter((agent) => ["WAITING_USER", "WAITING_APPROVAL", "NEEDS_ATTENTION"].includes(agent.status)).length;
  const idleCount = agents.filter((agent) => agent.status === "IDLE").length;

  return (
    <EventWorkSurface
      eyebrow="企业数字员工名册与状态"
      title="数字员工"
      description="员工范围已经按当前企业、当前成员与服务端授权裁剪"
      onClose={onClose}
      className="employee-directory-layer"
    >
      <div className="event-directory">
        <section className="event-directory-summary" aria-label="数字员工状态统计">
          <span><small>数字员工总数</small><strong>{agents.length}</strong></span>
          <span><small>工作中</small><strong>{workingCount}</strong></span>
          <span><small>等待处理</small><strong>{waitingCount}</strong></span>
          <span><small>空闲可用</small><strong>{idleCount}</strong></span>
        </section>

        <section className="event-directory-list">
          <header>
            <div>
              <strong>企业数字员工列表</strong>
              <small>点击员工查看档案、独立配置和当前工作</small>
            </div>
            <div className="event-directory-toolbar">
              <label>
                <IconSearch size={16} />
                <input aria-label="搜索数字员工" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索员工、能力或岗位" />
              </label>
              <button type="button" aria-expanded={filtersOpen} aria-controls="employee-filters" onClick={() => setFiltersOpen((open) => !open)}>
                <IconFilter size={16} /> 筛选
              </button>
            </div>
          </header>

          {filtersOpen ? (
            <div className="event-directory-filters" id="employee-filters">
              {capabilityFilters.map(([id, label]) => (
                <button type="button" aria-pressed={activeCapability === id} className={activeCapability === id ? "is-active" : ""} key={id} onClick={() => setCapability(id)}>
                  {label}
                </button>
              ))}
            </div>
          ) : null}

          <div className="event-directory-grid">
            {visible.map((agent) => (
              <article key={agent.id}>
                <button type="button" onClick={() => onOpenAgent(agent.id)} aria-label={`打开${agent.name}工作台`}>
                  <span className="event-directory-avatar">
                    <img src={agent.image} alt="" />
                    <i className={`is-${statusToneClass(agent.status)}`} />
                  </span>
                  <span className="event-directory-copy">
                    <strong>{agent.name}<em>AI</em></strong>
                    <small>{agent.capabilityLabel}</small>
                    <span><i>{agent.statusLabel}</i><b>{agent.currentTaskTitle}</b></span>
                  </span>
                  <span className="event-directory-capability" title={capabilityLabel(agent)}>{capabilityBadge(agent)}</span>
                </button>
              </article>
            ))}
          </div>

          {visible.length === 0 ? <div className="event-directory-empty"><IconRobot size={24} /><span>当前筛选条件下没有可用数字员工</span></div> : null}
        </section>

        <footer className="event-directory-note">
          员工的岗位版本、企业配置、知识范围和个人记忆彼此隔离；进入工作台后才会创建新的任务意图。
        </footer>
      </div>
    </EventWorkSurface>
  );
}

export function TasksPage({ tasks, onOpenTask, onClose }) {
  const [activeFilter, setActiveFilter] = useState("ALL");
  const filters = [
    ["ALL", "全部任务", () => true],
    ["WAITING", "等待我", (task) => waitingTaskStatuses.has(task.status)],
    ["RUNNING", "进行中", (task) => runningTaskStatuses.has(task.status)],
    ["APPROVAL", "待审批", (task) => task.status === "WAITING_APPROVAL"],
    ["EXCEPTION", "异常", (task) => exceptionTaskStatuses.has(task.status)],
  ];
  const activePredicate = filters.find(([id]) => id === activeFilter)?.[2] ?? (() => true);
  const visibleTasks = tasks.filter(activePredicate);
  const summary = [
    { label: "全部任务", value: tasks.length, icon: IconListCheck },
    { label: "执行中", value: tasks.filter((task) => runningTaskStatuses.has(task.status)).length, icon: IconClock },
    { label: "等待我", value: tasks.filter((task) => waitingTaskStatuses.has(task.status)).length, icon: IconRobot },
    { label: "需处理", value: tasks.filter((task) => exceptionTaskStatuses.has(task.status)).length, icon: IconAlertTriangle },
  ];

  return (
    <EventWorkSurface
      eyebrow="任务、Run、成果与审批分别表达"
      title="当前任务"
      description="进度来自真实步骤、负责人和运行事件，不使用随机百分比"
      onClose={onClose}
      className="task-center-layer"
    >
      <div className="event-task-center">
        <section className="event-task-summary" aria-label="任务状态统计">
          {summary.map((item) => {
            const Icon = item.icon;
            return <span key={item.label}><Icon size={19} /><small>{item.label}</small><strong>{item.value}</strong></span>;
          })}
        </section>

        <div className="event-task-tabs">
          {filters.map(([id, label]) => (
            <button className={activeFilter === id ? "is-active" : ""} aria-pressed={activeFilter === id} type="button" key={id} onClick={() => setActiveFilter(id)}>{label}</button>
          ))}
        </div>

        <section className="event-task-table" aria-label="任务列表">
          <header><span>任务 / 目标</span><span>执行员工</span><span>当前步骤</span><span>状态与步骤</span><span>智点</span><span>操作</span></header>
          {visibleTasks.map((task) => (
            <button type="button" key={task.id} onClick={() => onOpenTask(task.id)}>
              <span><strong>{task.title}</strong><small>计划 v{task.planVersion} · {task.collaborationMode ?? "SINGLE_TARGET"}</small></span>
              <span><strong>{task.ownerName}</strong><small>{task.shortIcon} · 数字员工</small></span>
              <span><strong>{task.currentStep}</strong><small>{task.stepSummary}</small></span>
              <span><StatusChip tone={task.statusTone}>{task.statusLabel}</StatusChip><progress max={Math.max(task.stepCount, 1)} value={Math.min(task.stepIndex, task.stepCount)} /><small>{task.stepIndex}/{task.stepCount} 步</small></span>
              <span><strong>{task.pointCaptured} / {task.pointEstimated}</strong><small>实际 / 预计</small></span>
              <span className="event-task-open">{task.nextAction}<IconArrowRight size={15} /></span>
            </button>
          ))}
          {visibleTasks.length === 0 ? <div className="event-directory-empty"><IconListCheck size={24} /><span>当前筛选条件下没有任务</span></div> : null}
        </section>
      </div>
    </EventWorkSurface>
  );
}

export function ArtifactsPage({ tasks, onOpenTask, onClose }) {
  const tasksWithArtifacts = tasks.filter((task) => task.artifacts?.length > 0 || task.graphicCandidates?.length > 0 || task.selectedArtifactId);
  return (
    <EventWorkSurface
      eyebrow="版本化成果与人工确认"
      title="成果中心"
      description="任务成功、成果就绪、人工确认和外部交付分别表达"
      onClose={onClose}
      className="artifact-center-layer"
    >
      <div className="event-artifact-center">
        <section className="event-artifact-summary">
          <span><IconCircleCheck size={20} /><small>可见成果任务</small><strong>{tasksWithArtifacts.length}</strong></span>
          <span><IconClock size={20} /><small>等待人工</small><strong>{tasksWithArtifacts.filter((task) => ["WAITING_CONFIRMATION", "WAITING_APPROVAL"].includes(task.status)).length}</strong></span>
          <span><IconShieldLock size={20} /><small>权限范围</small><strong>当前成员</strong></span>
        </section>
        <div className="event-artifact-grid">
          {tasksWithArtifacts.map((task) => (
            <article key={task.id}>
              {task.capability === "GRAPHIC_DESIGN" ? <img src="/assets/results/expo-keyvisual-a.png" alt="平面出图成果预览" /> : <span className={`event-artifact-cover is-${task.tone}`}>{task.shortIcon}</span>}
              <div>
                <StatusChip tone={task.statusTone}>{task.statusLabel}</StatusChip>
                <h2>{task.title}</h2>
                <p>{task.ownerName} · 计划 v{task.planVersion} · {task.artifacts?.length ?? task.graphicCandidates?.length ?? 0} 个版本事实</p>
                <button type="button" onClick={() => onOpenTask(task.id)}>查看成果、依据与确认 <IconArrowRight size={16} /></button>
              </div>
            </article>
          ))}
        </div>
        {tasksWithArtifacts.length === 0 ? <div className="event-directory-empty"><IconCircleCheck size={24} /><span>当前没有可查看的成果版本</span></div> : null}
      </div>
    </EventWorkSurface>
  );
}

export function KnowledgePage() {
  const rows = [{ name: "点联品牌规范 v3.2", scope: "平面出图员工 · 市场部", status: "可用", count: "36 段" }, { name: "场馆服务合同标准条款", scope: "合同审核员工 · 法务部", status: "可用", count: "128 段" }, { name: "历史项目与成本资料 2026-Q2", scope: "报价员工 · 商务部", status: "索引中", count: "642 条" }];
  return <CollectionShell eyebrow="企业知识" title="员工能使用哪些企业资料" description="检索前先鉴权，正文、引用和附件始终使用同一受众边界。"><div className="knowledge-banner"><IconShieldLock size={22} /><span><strong>当前视图：星海会展集团</strong><small>只显示你有权查看的知识空间与文档元数据</small></span><button type="button">查看权限范围</button></div><div className="knowledge-table"><div className="knowledge-table__head"><span>知识资产</span><span>授权范围</span><span>处理状态</span><span>索引规模</span><span>操作</span></div>{rows.map((row) => <div key={row.name}><span><IconBook2 size={18} /><strong>{row.name}</strong></span><span>{row.scope}</span><StatusChip tone={row.status === "可用" ? "success" : "info"}>{row.status}</StatusChip><span>{row.count}</span><button type="button">查看版本</button></div>)}</div></CollectionShell>;
}

export function PointsPage({ account, entries }) {
  const typeLabel = { RESERVE: "任务预占", CAPTURE: "实际扣除", RELEASE: "预占释放", GRANT: "企业发放", ADJUST: "平台调账" };
  return <CollectionShell eyebrow="个人智点" title="智点余额与使用明细" description="智点来自企业账户，预占、实扣和释放分别记录；1 元 = 100 智点。"><div className="points-summary"><div><span>可用智点</span><strong>{account.available.toLocaleString("zh-CN")}</strong><small>可用于新任务与群聊调用</small></div><div><span>任务预占</span><strong>{account.reserved.toLocaleString("zh-CN")}</strong><small>尚未结算的预计消耗</small></div><div><span>累计实扣</span><strong>{account.consumed.toLocaleString("zh-CN")}</strong><small>可下钻到任务、Run 与调用</small></div></div><div className="point-ledger"><div className="point-ledger__heading"><span><IconReceipt size={18} /> 最近流水</span><small>整数最小单位记账</small></div>{entries.map((entry) => <div key={entry.id}><span className="point-ledger__icon"><IconCoinYuan size={17} /></span><span><strong>{typeLabel[entry.type] ?? entry.type}</strong><small>{entry.sourceLabel}</small></span><span>{entry.occurredAtLabel}</span><strong className={entry.type === "RELEASE" || entry.type === "GRANT" ? "is-positive" : ""}>{entry.type === "RELEASE" || entry.type === "GRANT" ? "+" : "-"}{entry.amount.toLocaleString("zh-CN")} 智点</strong></div>)}</div></CollectionShell>;
}

function CollectionShell({ eyebrow, title, description, children }) {
  return <main className="collection-page"><section className="collection-page__header"><span>{eyebrow}</span><h1>{title}</h1><p>{description}</p></section>{children}</main>;
}
