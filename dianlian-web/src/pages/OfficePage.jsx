import { useEffect, useMemo, useState } from "react";
import {
  IconArrowRight,
  IconBriefcase2,
  IconBuildingCommunity,
  IconCheck,
  IconClockHour4,
  IconListCheck,
  IconMessageCircle2,
  IconPhoto,
  IconReportAnalytics,
  IconRobot,
  IconSend2,
  IconUsersGroup,
  IconX,
} from "@tabler/icons-react";
import { StatusChip } from "../components/StatusChip.jsx";
import "./office.css";

const toneByStatus = {
  WORKING: "success",
  WAITING_USER: "warning",
  WAITING_APPROVAL: "info",
  NEEDS_ATTENTION: "danger",
  IDLE: "neutral",
};

const capabilityDisplay = {
  GRAPHIC_DESIGN: { code: "VIS", color: "#2f7fe7", icon: IconPhoto },
  CONTRACT_REVIEW: { code: "LAW", color: "#8a63d2", icon: IconReportAnalytics },
  QUOTATION: { code: "QUO", color: "#1b9a8a", icon: IconBriefcase2 },
};

const runningStatuses = new Set(["PLANNING", "QUEUED", "RUNNING", "APPLYING_GUIDANCE", "REPLANNING"]);
const waitingStatuses = new Set(["WAITING_USER", "WAITING_CONFIRMATION", "WAITING_APPROVAL", "PAUSED"]);
const completedStatuses = new Set(["SUCCEEDED", "PARTIAL_SUCCESS"]);

function capabilityFallback(capability) {
  const normalized = String(capability || "AI").replaceAll("_", "");
  return { code: normalized.slice(0, 3).toUpperCase() || "AI", color: "#5b78a5", icon: IconRobot };
}

function buildAgentZones(agents) {
  const groups = new Map();
  for (const agent of agents) {
    const key = agent.capability || agent.capabilityLabel || agent.id;
    const current = groups.get(key) ?? {
      id: key,
      title: agent.capabilityLabel || "数字员工",
      display: capabilityDisplay[key] ?? capabilityFallback(key),
      agents: [],
    };
    current.agents.push(agent);
    groups.set(key, current);
  }
  return [...groups.values()];
}

function summaryLabel(count, emptyText, countText) {
  return count > 0 ? `${count} ${countText}` : emptyText;
}

export function OfficePage({
  agents = [],
  tasks = [],
  onOpenAgent,
  onMessageAgent = null,
  onOpenTask,
  onNavigate,
  messagePath = null,
}) {
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [quickGoal, setQuickGoal] = useState("");
  const [quickError, setQuickError] = useState("");

  const selectedAgent = useMemo(
    () => agents.find((agent) => agent.id === selectedAgentId) ?? null,
    [agents, selectedAgentId],
  );
  const agentZones = useMemo(() => buildAgentZones(agents), [agents]);
  const runningTasks = useMemo(() => tasks.filter((task) => runningStatuses.has(task.status)), [tasks]);
  const waitingTasks = useMemo(() => tasks.filter((task) => waitingStatuses.has(task.status)), [tasks]);
  const completedTasks = useMemo(() => tasks.filter((task) => completedStatuses.has(task.status)), [tasks]);

  useEffect(() => {
    if (selectedAgentId && !selectedAgent) {
      setSelectedAgentId("");
      setQuickGoal("");
    }
  }, [selectedAgent, selectedAgentId]);

  const closeAgent = () => {
    setSelectedAgentId("");
    setQuickGoal("");
    setQuickError("");
  };

  const startQuickTask = () => {
    if (!selectedAgent) return;
    const goal = quickGoal.trim();
    if (!goal) {
      setQuickError("先描述这次要完成的工作，进入工作台后仍可继续补充。");
      return;
    }
    setQuickError("");
    onOpenAgent(selectedAgent.id, goal);
  };

  return (
    <main className="office-page">
      <section className="office-stage" aria-label="点联企业数字员工组织大厅">
        <header className="office-stage__toolbar">
          <div>
            <span className="office-stage__live"><i /> 企业协作大厅</span>
            <strong>先找到合适的数字员工，再把工作交给它</strong>
          </div>
          <span className="office-stage__summary">
            <IconRobot size={16} /> {agents.length} 位数字员工
            <i aria-hidden="true" />
            <IconListCheck size={16} /> {runningTasks.length} 项正在执行
          </span>
        </header>

        <div className="office-zone-grid">
          {agentZones.map((zone) => {
            const ZoneIcon = zone.display.icon;
            const activeCount = zone.agents.filter((agent) => agent.status !== "IDLE").length;
            return (
              <article
                className="office-zone office-zone--agents"
                key={zone.id}
                style={{ "--zone-color": zone.display.color }}
              >
                <header>
                  <span className="office-zone__code">{zone.display.code}</span>
                  <div>
                    <strong>{zone.title}</strong>
                    <small>{summaryLabel(activeCount, "当前可接新工作", "位正在处理工作")}</small>
                  </div>
                  <ZoneIcon size={17} stroke={1.7} />
                </header>
                <div className="office-zone__people">
                  {zone.agents.map((agent) => (
                    <button
                      className="office-worker"
                      key={agent.id}
                      type="button"
                      onClick={() => {
                        setSelectedAgentId(agent.id);
                        setQuickGoal("");
                        setQuickError("");
                      }}
                      aria-label={`查看${agent.name}并交办工作`}
                    >
                      <span className="office-worker__avatar">
                        <img src={agent.image || "/assets/brand/dianlian-symbol.png"} alt="" />
                        <i className={`is-${toneByStatus[agent.status] ?? "neutral"}`} />
                      </span>
                      <span className="office-worker__copy">
                        <strong>{agent.name}<em>AI</em></strong>
                        <small>{agent.currentTaskTitle || "当前没有进行中的工作"}</small>
                      </span>
                      <IconArrowRight size={15} />
                    </button>
                  ))}
                </div>
              </article>
            );
          })}

          <button
            className="office-zone office-zone--entry"
            type="button"
            onClick={() => messagePath && onNavigate(messagePath)}
            disabled={!messagePath}
          >
            <span className="office-entry-icon"><IconMessageCircle2 size={21} /></span>
            <span><strong>协作消息</strong><small>{messagePath ? "与真人同事、数字员工直接沟通或建群" : "当前身份尚未开放会话权限"}</small></span>
            <IconArrowRight size={17} />
          </button>

          <button className="office-zone office-zone--entry" type="button" onClick={() => onNavigate("/employees")}>
            <span className="office-entry-icon"><IconUsersGroup size={21} /></span>
            <span><strong>数字员工名册</strong><small>查看岗位能力、企业配置与可用范围</small></span>
            <IconArrowRight size={17} />
          </button>

          <button className="office-zone office-zone--task" type="button" onClick={() => onNavigate("/tasks")}>
            <header><IconListCheck size={19} /><span><strong>当前任务</strong><small>{tasks.length} 项对你可见</small></span><IconArrowRight size={16} /></header>
            <div>
              {tasks.slice(0, 2).map((task) => (
                <span key={task.id}><i className={`task-tone--${task.statusTone}`} /> <strong>{task.title}</strong><small>{task.statusLabel}</small></span>
              ))}
              {tasks.length === 0 ? <p>还没有任务。先从数字员工工位开始。</p> : null}
            </div>
          </button>

          <button className="office-zone office-zone--metric" type="button" onClick={() => onNavigate("/tasks")}>
            <IconClockHour4 size={22} />
            <span><strong>{runningTasks.length}</strong><small>正在执行</small></span>
            <p>{runningTasks[0]?.currentStep || "没有执行中的步骤"}</p>
          </button>

          <button className="office-zone office-zone--metric is-waiting" type="button" onClick={() => onNavigate("/tasks")}>
            <IconReportAnalytics size={22} />
            <span><strong>{waitingTasks.length}</strong><small>待我处理</small></span>
            <p>{waitingTasks[0]?.nextAction || "当前没有待确认或待审批事项"}</p>
          </button>

          <button className="office-zone office-zone--metric is-complete" type="button" onClick={() => onNavigate("/tasks")}>
            <IconCheck size={22} />
            <span><strong>{completedTasks.length}</strong><small>已形成结果</small></span>
            <p>{completedTasks[0]?.title || "成果将在任务完成后沉淀"}</p>
          </button>
        </div>
      </section>

      {selectedAgent ? (
        <aside className="office-agent-drawer" aria-label={`${selectedAgent.name}员工档案`}>
          <header>
            <span><small>数字员工档案</small><strong>{selectedAgent.name}</strong></span>
            <button type="button" aria-label="关闭员工档案" onClick={closeAgent}><IconX size={18} /></button>
          </header>
          <div className="office-agent-drawer__body">
            <section className="office-agent-profile">
              <img src={selectedAgent.image || "/assets/brand/dianlian-symbol.png"} alt="" />
              <div>
                <span><strong>{selectedAgent.name}</strong><em>AI</em></span>
                <p>{selectedAgent.capabilityLabel}</p>
                <StatusChip tone={toneByStatus[selectedAgent.status]}>{selectedAgent.statusLabel}</StatusChip>
              </div>
            </section>

            <section className="office-agent-section">
              <h2>岗位说明</h2>
              <p>{selectedAgent.profile || "按照企业配置、授权知识与独立记忆边界处理工作。"}</p>
            </section>

            <section className="office-agent-section">
              <h2>能力与边界</h2>
              <div className="office-agent-skills">
                {(selectedAgent.skills?.length ? selectedAgent.skills : [selectedAgent.skillSummary]).filter(Boolean).map((skill) => <span key={skill}>{skill}</span>)}
              </div>
              <p className="office-agent-memory"><IconBuildingCommunity size={15} /> 企业知识、岗位配置和与你的独立记忆会在授权范围内组合。</p>
            </section>

            <section className="office-agent-section">
              <h2>当前工作</h2>
              <button className="office-agent-current-task" type="button" onClick={() => {
                const task = tasks.find((item) => item.agentId === selectedAgent.id);
                if (task) onOpenTask(task.id);
              }} disabled={!tasks.some((item) => item.agentId === selectedAgent.id)}>
                <span>{selectedAgent.currentTaskTitle || "当前没有进行中的工作"}</span>
                <IconArrowRight size={16} />
              </button>
            </section>

            {onMessageAgent ? (
              <section className="office-agent-message">
                <button type="button" onClick={() => onMessageAgent(selectedAgent.id)}><IconMessageCircle2 size={17} /> 发消息</button>
                <span>进入统一会话；该员工的岗位配置、企业知识范围和与你的会话记忆独立生效。</span>
              </section>
            ) : null}

            <section className="office-agent-handoff">
              <label htmlFor="office-agent-goal">交办一项新工作</label>
              <textarea
                id="office-agent-goal"
                value={quickGoal}
                onChange={(event) => {
                  setQuickGoal(event.target.value);
                  setQuickError("");
                }}
                placeholder={selectedAgent.quickPlaceholder || "说明目标、输入资料和期望结果…"}
                rows={4}
              />
              {quickError ? <p role="alert">{quickError}</p> : null}
              <button type="button" onClick={startQuickTask}>进入工作台 <IconSend2 size={17} /></button>
            </section>
          </div>
        </aside>
      ) : null}
    </main>
  );
}
