import { useEffect, useMemo, useRef, useState } from "react";
import {
  IconAt,
  IconChevronLeft,
  IconInfoCircle,
  IconPaperclip,
  IconSend2,
  IconUsersGroup,
  IconX,
} from "@tabler/icons-react";
import { StatusChip } from "../components/StatusChip.jsx";
import "./group.css";

const modes = [
  { id: "PARALLEL_SEPARATE", title: "分别执行", description: "每位员工独立返回成果，不自动汇总。" },
  { id: "PRIMARY_SUMMARY", title: "主责汇总", description: "选择一位主责员工分工并汇总最终成果。" },
];

export function GroupRoomPage({ agents, messages, tasks, onBack, onOpenTask, onSendMessage }) {
  const [content, setContent] = useState("");
  const [targetIds, setTargetIds] = useState([]);
  const [mode, setMode] = useState("SINGLE_TARGET");
  const [primaryAgentId, setPrimaryAgentId] = useState("");
  const [targetPickerOpen, setTargetPickerOpen] = useState(false);
  const [modeDialogOpen, setModeDialogOpen] = useState(false);
  const [feedback, setFeedback] = useState("");
  const commandSequence = useRef(0);
  const modeDialogRef = useRef(null);

  const selectedAgents = useMemo(() => agents.filter((agent) => targetIds.includes(agent.id)), [agents, targetIds]);

  const toggleTarget = (agentId) => {
    setTargetIds((ids) => {
      const next = ids.includes(agentId) ? ids.filter((id) => id !== agentId) : [...ids, agentId];
      if (!next.includes(primaryAgentId)) setPrimaryAgentId("");
      if (next.length <= 1) setMode("SINGLE_TARGET");
      return next;
    });
    setFeedback("");
  };

  useEffect(() => {
    if (!modeDialogOpen) return undefined;
    modeDialogRef.current?.querySelector("button")?.focus();
    const closeOnEscape = (event) => {
      if (event.key === "Escape") setModeDialogOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [modeDialogOpen]);

  const send = () => {
    if (!content.trim()) return;
    if (targetIds.length > 1 && mode === "SINGLE_TARGET") {
      setModeDialogOpen(true);
      return;
    }
    if (mode === "PRIMARY_SUMMARY" && !primaryAgentId) {
      setFeedback("主责汇总必须先选择一位主责员工");
      setModeDialogOpen(true);
      return;
    }
    const targetCount = targetIds.length;
    commandSequence.current += 1;
    onSendMessage({ content: content.trim(), targetIds, mode: targetCount ? mode : undefined, primaryAgentId: primaryAgentId || undefined, commandId: `group-command-${Date.now()}-${commandSequence.current}` });
    setFeedback(targetCount === 0 ? "普通群消息已发送：未触发数字员工，也未扣智点。" : `已明确触发 ${targetCount} 位数字员工。`);
    setContent("");
    setTargetIds([]);
    setPrimaryAgentId("");
    setMode("SINGLE_TARGET");
  };

  return (
    <main className="group-page">
      <section className="group-shell">
        <aside className="group-sidebar">
          <button className="back-button" type="button" onClick={onBack}><IconChevronLeft size={18} /> 返回办公室</button>
          <div className="group-room-card is-active"><span><IconUsersGroup size={20} /></span><div><strong>工商银行展台项目组</strong><small>8 位同事 · 3 位数字员工</small></div></div>
          <div className="group-sidebar__section"><span>可用数字员工</span>{agents.map((agent) => <button key={agent.id} type="button" onClick={() => toggleTarget(agent.id)}><img src={agent.image} alt="" /><span><strong>{agent.name}</strong><small>{agent.statusLabel}</small></span><StatusChip tone={targetIds.includes(agent.id) ? "info" : "neutral"}>{targetIds.includes(agent.id) ? "已选择" : "可用"}</StatusChip></button>)}</div>
          <div className="group-boundary"><IconInfoCircle size={17} /><span>群聊只使用群和项目范围的资料与记忆，不读取任何成员的私人记忆。</span></div>
        </aside>

        <section className="group-conversation">
          <header><div><h1>工商银行展台项目组</h1><p>内部协作房间 · 默认一条消息只触发一位员工</p></div><button type="button">群聊设置</button></header>
          <div className="group-messages">
            {messages.map((message) => (
              <article className={`group-message group-message--${message.senderType.toLowerCase()}`} key={message.id}>
                <img src={message.avatar} alt="" />
                <div><div className="group-message__meta"><strong>{message.senderName}</strong><span>{message.createdAtLabel}</span>{message.pointImpact > 0 && <StatusChip tone="info">-{message.pointImpact} 智点</StatusChip>}</div><p>{message.text}</p>{message.targets?.length > 0 && <div className="message-targets"><IconAt size={14} /> {message.targets.map((target) => target.name).join("、")} · {message.modeLabel}</div>}</div>
              </article>
            ))}
          </div>

          <div className="group-composer">
            {selectedAgents.length > 0 && <div className="group-composer__targets">{selectedAgents.map((agent) => <button key={agent.id} type="button" onClick={() => toggleTarget(agent.id)}><img src={agent.image} alt="" />@{agent.name}<IconX size={13} /></button>)}{selectedAgents.length > 1 && <StatusChip tone="warning">{mode === "SINGLE_TARGET" ? "请选择协作模式" : modes.find((item) => item.id === mode)?.title}</StatusChip>}</div>}
            <textarea aria-label="群聊消息" value={content} onChange={(event) => setContent(event.target.value)} placeholder="输入普通群消息，或先选择 / @ 一位数字员工…" />
            <div className="group-composer__footer"><div><button type="button" aria-expanded={targetPickerOpen} aria-controls="group-target-picker" onClick={() => setTargetPickerOpen((open) => !open)}><IconAt size={18} /> 选择员工</button><button type="button"><IconPaperclip size={18} /> 添加资料</button></div><span>未选择员工时不会调用模型</span><button className="send-button" type="button" disabled={!content.trim()} onClick={send}><IconSend2 size={18} /> 发送</button></div>
            {targetPickerOpen && <div className="target-picker" id="group-target-picker">{agents.map((agent) => <button className={targetIds.includes(agent.id) ? "is-selected" : ""} aria-pressed={targetIds.includes(agent.id)} key={agent.id} type="button" onClick={() => toggleTarget(agent.id)}><img src={agent.image} alt="" /><span><strong>{agent.name}</strong><small>{agent.capabilityLabel}</small></span></button>)}</div>}
            {feedback && <div className="composer-feedback" role="status" aria-live="polite">{feedback}</div>}
          </div>
        </section>

        <aside className="group-context-panel"><div className="panel-heading"><span>本群工作</span><StatusChip tone="info">{tasks.length} 进行中</StatusChip></div>{tasks.slice(0, 3).map((task) => <div className="context-task" key={task.id}><strong>{task.title}</strong><span>{task.ownerName} · {task.statusLabel}</span><button type="button" onClick={() => onOpenTask(task.id)}>{task.nextAction}</button></div>)}<div className="group-access"><span>本群范围</span><p>项目知识：工商银行展台项目</p><p>记忆：群 × 员工作用域</p><p>费用归属：项目预算</p></div></aside>
      </section>

      {modeDialogOpen && <div className="modal-backdrop" onMouseDown={() => setModeDialogOpen(false)}><div className="mode-dialog" ref={modeDialogRef} role="dialog" aria-modal="true" aria-labelledby="group-mode-title" onMouseDown={(event) => event.stopPropagation()}><h2 id="group-mode-title">选择多员工协作模式</h2><p>已选择 {selectedAgents.map((agent) => agent.name).join("、")}，系统不会静默决定谁负责汇总。</p><div className="mode-options">{modes.map((item) => <button className={mode === item.id ? "is-selected" : ""} aria-pressed={mode === item.id} key={item.id} type="button" onClick={() => setMode(item.id)}><strong>{item.title}</strong><span>{item.description}</span></button>)}</div>{mode === "PRIMARY_SUMMARY" && <div className="primary-selector"><span>选择主责员工</span>{selectedAgents.map((agent) => <button className={primaryAgentId === agent.id ? "is-selected" : ""} aria-pressed={primaryAgentId === agent.id} key={agent.id} type="button" onClick={() => setPrimaryAgentId(agent.id)}><img src={agent.image} alt="" />{agent.name}</button>)}</div>}<div className="modal-actions"><button type="button" onClick={() => setModeDialogOpen(false)}>取消</button><button type="button" disabled={mode === "PRIMARY_SUMMARY" && !primaryAgentId} onClick={() => { setModeDialogOpen(false); setFeedback(""); queueMicrotask(send); }}>确认并发送</button></div></div></div>}
    </main>
  );
}
