import { useEffect, useMemo, useRef, useState } from "react";
import {
  IconAntennaBars5,
  IconAlertTriangle,
  IconBook2,
  IconCheck,
  IconChevronRight,
  IconCircleCheck,
  IconClock,
  IconCoinYuan,
  IconFileDiff,
  IconPlayerPause,
  IconPlayerPlay,
  IconRefresh,
  IconRoute,
  IconSend,
  IconSparkles,
  IconUserCheck,
} from "@tabler/icons-react";
import { EventWorkSurface } from "../components/EventWorkSurface.jsx";
import { StatusChip } from "../components/StatusChip.jsx";
import "./workspace.css";

const ACTION_LABELS = Object.freeze({
  ADD_CONTEXT: "补充上下文",
  CORRECT_FACT: "纠正事实",
  CHANGE_CONSTRAINT: "调整约束",
  CHANGE_GOAL: "调整目标",
  STYLE_GUIDANCE: "补充风格要求",
  ANSWER_CHECKPOINT: "回答检查点",
  PAUSE: "暂停",
  RESUME: "继续",
  CANCEL: "取消",
  RETRY_FROM_STEP: "从步骤重试",
  SELECT_ARTIFACT: "选择成果",
  SUBMIT_APPROVAL: "提交审批",
  APPROVE: "通过审批",
  REJECT: "退回",
  DOWNLOAD: "下载",
  VIEW: "查看",
});

const APPROVAL_LABELS = Object.freeze({
  PENDING: "待审批",
  APPROVED: "已通过",
  REJECTED: "已退回",
  WITHDRAWN: "已撤回",
  INVALIDATED: "已失效",
});

const DELIVERY_LABELS = Object.freeze({
  PENDING: "待交付",
  SENDING: "交付中",
  ACCEPTED: "对方已接收",
  DELIVERED: "已确认交付",
  RETRY_WAIT: "等待重试",
  FAILED: "交付失败",
  CANCELLED: "已取消",
  UNKNOWN: "结果待核对",
});

const LIVE_STATUS_PRESENTATION = Object.freeze({
  connecting: ["动态连接中", "info"],
  live: ["实时同步", "success"],
  polling: ["自动轮询", "warning"],
  paused: ["更新已暂停", "neutral"],
  ended: ["同步完成", "neutral"],
});

function factStatusLabel(summary, labels, emptyLabel) {
  if (!summary) return emptyLabel;
  return summary.statusLabel ?? labels[summary.status] ?? summary.status;
}

function FactChip({ label, value, tone = "neutral" }) {
  return <div className="task-fact-chip"><span>{label}</span><StatusChip tone={tone}>{value}</StatusChip></div>;
}

function GraphicArtifact({ task, onSelect }) {
  const candidates = task.graphicCandidates;
  const variants = task.capabilityData?.variants ?? [];
  const [selected, setSelected] = useState(task.selectedArtifactId ?? candidates[0]?.id);
  return (
    <div className="graphic-artifact">
      <div className="artifact-section-title"><div><h3>候选图对比</h3><p>选择后可继续局部修改与尺寸派生</p></div><StatusChip tone="warning">待选版</StatusChip></div>
      <div className="graphic-candidates">
        {candidates.map((candidate) => (
          <button
            className={selected === candidate.id ? "graphic-candidate is-selected" : "graphic-candidate"}
            key={candidate.id}
            type="button"
            onClick={() => {
              setSelected(candidate.id);
              onSelect(candidate.id);
            }}
          >
            <img src={candidate.image} alt={candidate.label} />
            <span>{candidate.label}</span>
            {selected === candidate.id && <IconCircleCheck size={21} />}
          </button>
        ))}
      </div>
      <div className="variant-grid">
        {variants.map((variant) => (
          <div key={variant.id}>
            <span>{variant.label}</span>
            <strong>{variant.width} × {variant.height}</strong>
            <StatusChip tone={variant.status === "READY" ? "success" : variant.status === "FAILED" ? "danger" : "neutral"}>{variant.statusLabel}</StatusChip>
          </div>
        ))}
      </div>
    </div>
  );
}

function ContractArtifact({ task, onResolveRisk }) {
  const [selectedRiskId, setSelectedRiskId] = useState(task.capabilityData.risks[0]?.id);
  const selectedRisk = task.capabilityData.risks.find((risk) => risk.id === selectedRiskId);
  return (
    <div className="contract-artifact">
      <div className="artifact-section-title"><div><h3>合同原文与风险定位</h3><p>{task.capabilityData.contractVersion?.fileName ?? "等待上传合同文件"}{task.capabilityData.contractVersion?.pages ? ` · ${task.capabilityData.contractVersion.pages} 页` : ""}</p></div><StatusChip tone={task.capabilityData.unresolvedHighRiskCount > 0 ? "danger" : "neutral"}>{task.capabilityData.unresolvedHighRiskCount} 项高风险</StatusChip></div>
      <div className="contract-review-grid">
        <article className="contract-document">
          <span>第 12 条　付款与违约责任</span>
          <p>12.1 甲方应在项目验收后 30 个工作日内支付合同款项。</p>
          <p className={selectedRisk?.clauseRef === "第 12 条" ? "is-highlighted" : ""}>12.3 如因任何原因导致甲方延迟付款，乙方有权立即停止全部服务，并要求甲方承担合同总额 20% 的违约金。</p>
          <p>12.4 双方应就争议事项先行协商，协商不成的，按照本合同争议解决条款处理。</p>
          <span>第 18 条　知识产权</span>
          <p className={selectedRisk?.clauseRef === "第 18 条" ? "is-highlighted" : ""}>18.2 项目执行过程中产生的全部设计成果，其知识产权归乙方所有，甲方仅获得项目期间使用许可。</p>
        </article>
        <div className="risk-list">
          {task.capabilityData.risks.map((risk) => (
            <button className={selectedRiskId === risk.id ? "is-selected" : ""} key={risk.id} type="button" onClick={() => setSelectedRiskId(risk.id)}>
              <span className={`risk-level risk-level--${risk.level.toLowerCase()}`}>{risk.levelLabel}</span>
              <span><strong>{risk.title}</strong><small>{risk.clauseRef} · {risk.summary}</small></span>
              <IconChevronRight size={16} />
            </button>
          ))}
        </div>
      </div>
      {selectedRisk && (
        <div className="risk-detail">
          <div><span>修改建议</span><strong>{selectedRisk.suggestion}</strong></div>
          <div><span>依据</span><button type="button"><IconBook2 size={15} /> 企业标准条款 v5 · 付款条款 4.2</button></div>
          <div className="risk-actions">
            <button type="button" onClick={() => onResolveRisk(selectedRisk.id, "ACCEPTED")}>采纳修改建议</button>
            <button type="button" onClick={() => onResolveRisk(selectedRisk.id, "FALSE_POSITIVE")}>标记为误报</button>
          </div>
          <small>本结果用于辅助审核，不替代执业律师或企业法务的最终意见。</small>
        </div>
      )}
    </div>
  );
}

function QuotationArtifact({ task }) {
  const quote = task.capabilityData;
  return (
    <div className="quotation-artifact">
      <div className="artifact-section-title"><div><h3>报价测算明细</h3><p>规则 {quote.ruleVersion} · {quote.taxModeLabel} · 有效期至 {quote.validUntil}</p></div><StatusChip tone={quote.exceptions.some((item) => !item.resolved) ? "warning" : "success"}>{quote.stageLabel}</StatusChip></div>
      <div className="quotation-toolbar"><button type="button" className="is-active">内部版</button><button type="button">客户版</button><span>客户版将隐藏成本、利润和底价</span></div>
      <div className="quotation-table">
        <div className="quotation-table__head"><span>项目</span><span>数量</span><span>单价</span><span>成本</span><span>金额</span></div>
        {quote.items.map((item) => (
          <div className="quotation-table__row" key={item.id}><span><strong>{item.name}</strong><small>{item.source}</small></span><span>{item.quantity}</span><span>¥{item.unitPrice.toLocaleString()}</span><span>¥{item.cost.toLocaleString()}</span><span>¥{item.amount.toLocaleString()}</span></div>
        ))}
      </div>
      <div className="quotation-summary">
        <div><span>项目成本</span><strong>¥{quote.totals.cost.toLocaleString()}</strong></div>
        <div><span>税额</span><strong>¥{quote.totals.tax.toLocaleString()}</strong></div>
        <div><span>预计毛利</span><strong>¥{quote.totals.margin.toLocaleString()}</strong></div>
        <div className="is-total"><span>客户报价</span><strong>¥{quote.totals.total.toLocaleString()}</strong></div>
      </div>
      {quote.exceptions.map((exception) => <div className="quote-exception" key={exception.type}><IconAlertTriangle size={17} /><span>{exception.message}</span><button type="button">查看规则</button></div>)}
    </div>
  );
}

function PendingCapabilityArtifact({ task, agent }) {
  const isActivelyRunning = ["RUNNING", "APPLYING_GUIDANCE", "REPLANNING"].includes(task.status);
  return (
    <div className="capability-pending" role="status">
      <span><IconClock size={24} /></span>
      <div>
        <h3>成果尚未生成</h3>
        <p>{isActivelyRunning
          ? `${agent.name}正在按已确认计划处理“${task.currentStep || "准备执行"}”。`
          : `任务已持久化，当前状态为“${task.statusLabel}”，尚不能宣称员工正在执行。`}成果形成后会在这里展示版本、依据与人工确认入口。</p>
      </div>
    </div>
  );
}

function ArtifactSnapshotPanel({ task, agent }) {
  const artifacts = task.artifacts ?? [];
  if (artifacts.length === 0) return <PendingCapabilityArtifact task={task} agent={agent} />;
  return (
    <div className="artifact-snapshot">
      <div className="artifact-section-title">
        <div><h3>成果版本</h3><p>这里只展示当前身份可见的版本事实；成果正文与下载权限由独立成果接口控制。</p></div>
        <StatusChip tone="info">{artifacts.length} 个版本</StatusChip>
      </div>
      <div className="artifact-snapshot__list">
        {artifacts.map((artifact, index) => (
          <article key={artifact.id ?? artifact.artifactVersionId}>
            <span className="artifact-snapshot__index">V{index + 1}</span>
            <div>
              <strong>{artifact.title}</strong>
              <small>{artifact.type ?? artifact.artifactType} · {artifact.createdAtLabel ?? "生成时间以服务端为准"}</small>
              <code>{artifact.contentHash ? `内容指纹 ${String(artifact.contentHash).slice(0, 20)}…` : "内容指纹未返回"}</code>
            </div>
            <StatusChip tone={artifact.statusTone ?? (artifact.status === "READY" ? "success" : artifact.status === "STALE" ? "warning" : "neutral")}>{artifact.statusLabel ?? artifact.status}</StatusChip>
          </article>
        ))}
      </div>
      <div className="artifact-snapshot__flow" aria-label="成果状态链">
        <FactChip label="任务" value={task.statusLabel} tone={task.statusTone} />
        <FactChip label="审批" value={factStatusLabel(task.approval, APPROVAL_LABELS, "尚未提交")} tone={task.approval?.statusTone ?? "neutral"} />
        <FactChip label="交付" value={factStatusLabel(task.delivery, DELIVERY_LABELS, "尚未交付")} tone={task.delivery?.statusTone ?? "neutral"} />
      </div>
    </div>
  );
}

function StageArtifactContent({ task }) {
  const content = typeof task.capabilityView?.latestArtifactContent === "string"
    ? task.capabilityView.latestArtifactContent.trim()
    : "";
  if (!content) return null;
  const usageEstimated = task.capabilityView?.latestArtifactUsageEstimated === true;
  return (
    <section className="task-stage-output" aria-label="最新阶段成果正文">
      <header>
        <div><small>最新阶段成果</small><h3>数字员工输出</h3></div>
        <StatusChip tone={usageEstimated ? "warning" : "success"}>{usageEstimated ? "用量按上限估算" : "已记录"}</StatusChip>
      </header>
      <pre>{content}</pre>
      <p>该内容来自任务权威快照，仅代表当前步骤的版本化阶段成果；不等于审批通过或外部交付完成。</p>
    </section>
  );
}

export function TaskDetailPage({ task, agent, onBack, onAction, onRefresh, refreshing = false, liveState = null }) {
  const [guidanceOpen, setGuidanceOpen] = useState(false);
  const [guidance, setGuidance] = useState("");
  const guidanceInputRef = useRef(null);
  const currentStep = useMemo(() => task.steps.find((step) => step.id === task.activeStepId) ?? task.steps[0], [task]);
  const hasGraphicArtifact = task.capability === "GRAPHIC_DESIGN" && task.graphicCandidates?.length > 0;
  const hasContractArtifact = task.capability === "CONTRACT_REVIEW" && task.capabilityData?.risks?.length > 0;
  const hasQuotationArtifact = task.capability === "QUOTATION" && task.capabilityData?.items?.length > 0 && task.capabilityData?.totals;
  const hasCapabilityArtifact = hasGraphicArtifact || hasContractArtifact || hasQuotationArtifact;
  const interactiveActions = typeof onAction === "function";
  const allowedActions = task.allowedActions ?? [];
  const serverActionHints = task.serverActionHints ?? [];
  const canPause = interactiveActions && allowedActions.includes("PAUSE");
  const canResume = interactiveActions && allowedActions.includes("RESUME");
  const canGuide = interactiveActions && allowedActions.includes("ADD_CONTEXT");
  const canSubmit = interactiveActions && allowedActions.includes("SUBMIT_APPROVAL");
  const canApprove = interactiveActions && allowedActions.includes("APPROVE");
  const [liveLabel, liveTone] = LIVE_STATUS_PRESENTATION[liveState?.phase] ?? ["按需刷新", "neutral"];

  useEffect(() => {
    if (!guidanceOpen) return undefined;
    guidanceInputRef.current?.focus();
    const closeOnEscape = (event) => {
      if (event.key === "Escape") setGuidanceOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [guidanceOpen]);

  return (
    <EventWorkSurface
      eyebrow={`${agent.name} · 计划 v${task.planVersion}`}
      title={task.title}
      description={`当前由 ${currentStep?.executorName ?? agent.name} 负责“${currentStep?.title ?? "等待生成计划"}”`}
      onClose={onBack}
      className="task-detail-event-layer"
      actions={(
        <>
          <span className="task-detail-id">任务编号 {task.id}</span>
          <StatusChip tone={task.statusTone}>{task.statusLabel}</StatusChip>
          {liveState ? <span className={`task-live-status task-live-status--${liveTone}`} role="status" title={liveState.detail ?? liveLabel} aria-label={liveState.detail ?? liveLabel}><IconAntennaBars5 size={14} />{liveLabel}</span> : null}
          {onRefresh ? <button type="button" disabled={refreshing} onClick={onRefresh}><IconRefresh size={18} />{refreshing ? "刷新中" : "刷新任务"}</button> : null}
          {(canPause || canResume) && <button type="button" onClick={() => onAction(canPause ? "PAUSE" : "RESUME")}>{canPause ? <IconPlayerPause size={18} /> : <IconPlayerPlay size={18} />}{canPause ? "暂停" : "继续"}</button>}
        </>
      )}
    >
      <section className="task-detail-metrics">
        <div><IconCoinYuan size={19} /><span>实际 / 预计</span><strong>{task.pointSummary.captured} / {task.pointSummary.estimatedMax} 智点</strong></div>
        <div><IconClock size={19} /><span>最近更新</span><strong>{task.updatedAtLabel}</strong></div>
        <div><IconRoute size={19} /><span>当前 Run</span><strong>{task.currentRunLabel ?? `Run ${task.currentRunNo}`}</strong></div>
        <div><IconUserCheck size={19} /><span>当前负责人</span><strong>{currentStep?.executorName ?? agent.name}</strong></div>
      </section>

      {task.blocker ? (
        <section className="task-blocker" role="status">
          <IconAlertTriangle size={18} />
          <div><strong>{task.blocker.message}</strong><span>当前责任方：{task.blocker.responsibleParty} · {task.blocker.code}</span></div>
        </section>
      ) : null}

      <section className="task-detail-grid">
        <aside className="task-steps-panel">
          <div className="panel-heading"><span>执行步骤</span><StatusChip tone="info">当前 {task.stepIndex}/{task.steps.length}</StatusChip></div>
          <ol>
            {task.steps.map((step, index) => (
              <li className={step.id === task.activeStepId ? "is-active" : ""} key={step.id}>
                <span className={`step-node step-node--${step.status.toLowerCase()}`}>{step.status === "SUCCEEDED" ? <IconCheck size={15} /> : index + 1}</span>
                <div><strong>{step.title}</strong><small>{step.executorName}</small><StatusChip tone={step.statusTone}>{step.statusLabel}</StatusChip></div>
              </li>
            ))}
          </ol>
          <div className="step-runtime-note"><IconRoute size={16} /><span>步骤由运行引擎按依赖推进；需要改变方向时使用“补充或纠正”。</span></div>
        </aside>

        <section className="task-artifact-panel">
          <StageArtifactContent task={task} />
          {!hasCapabilityArtifact && <ArtifactSnapshotPanel task={task} agent={agent} />}
          {hasGraphicArtifact && <GraphicArtifact task={task} onSelect={(artifactId) => onAction("SELECT_ARTIFACT", { artifactId })} />}
          {hasContractArtifact && <ContractArtifact task={task} onResolveRisk={(riskId, decision) => onAction("RESOLVE_CONTRACT_RISK", { riskId, decision })} />}
          {hasQuotationArtifact && <QuotationArtifact task={task} />}
        </section>

        <aside className="task-trace-panel">
          <div className="panel-heading"><span>运行轨迹</span><StatusChip tone="neutral">{task.currentRunLabel ?? `Run ${task.currentRunNo}`}</StatusChip></div>
          <div className="trace-list">
            {task.trace.map((event) => (
              <div key={event.id}><span><IconSparkles size={14} /></span><div><strong>{event.title}</strong><p>{event.summary}</p><small>{event.occurredAtLabel}</small></div></div>
            ))}
            {task.trace.length === 0 ? <div className="trace-list__empty">当前快照还没有可展示的业务轨迹</div> : null}
          </div>
          <div className="trace-boundary"><IconUserCheck size={17} /><span><strong>展示业务轨迹</strong><small>不展示模型思维链、系统提示词或原始密钥</small></span></div>

          <div className="task-runtime-facts">
            <div><span>运行实例</span><strong>{task.activeRun?.statusLabel ?? "尚未创建"}</strong><small>{task.activeRun ? `${task.activeRun.operationKind} · ${task.activeRun.startedAtLabel}` : "当前快照没有运行事实"}</small></div>
            <div><span>智点状态</span><strong>预占 {task.pointSummary.reserved}</strong><small>已扣 {task.pointSummary.captured} · 已释放 {task.pointSummary.released} · 待结算 {task.pointSummary.pendingSettlement ?? "0"}</small></div>
            <div><span>成果 / 审批 / 交付</span><strong>{task.artifacts?.length ?? 0} / {task.approval ? 1 : 0} / {task.delivery ? 1 : 0}</strong><small>三类事实分别表达，不用任务成功代替交付成功</small></div>
          </div>

          {!interactiveActions && serverActionHints.length > 0 ? (
            <div className="task-command-boundary" role="note">
              <strong>当前状态候选动作</strong>
              <p>{serverActionHints.map((action) => ACTION_LABELS[action] ?? action).join("、")}</p>
              <small>任务控制接口和角色级权限尚未闭合，本页保持只读，不会伪造操作成功。</small>
            </div>
          ) : null}

          <div className="task-actions">
            {canGuide && <button type="button" onClick={() => setGuidanceOpen(true)}><IconFileDiff size={17} /> 补充或纠正</button>}
            {canSubmit && <button className="primary-action" type="button" onClick={() => onAction("SUBMIT_APPROVAL")}><IconSend size={17} /> 提交人工确认</button>}
            {canApprove && <button className="primary-action" type="button" onClick={() => onAction("APPROVE")}><IconUserCheck size={17} /> 通过当前版本审批</button>}
            {!canSubmit && !canApprove && <div className="task-next-action"><span>下一步</span><strong>{task.nextActionHint}</strong></div>}
          </div>
        </aside>
      </section>

      {guidanceOpen && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setGuidanceOpen(false)}>
          <div className="guidance-modal" role="dialog" aria-modal="true" aria-labelledby="guidance-title" onMouseDown={(event) => event.stopPropagation()}>
            <h2 id="guidance-title">执行中补充或纠正</h2>
            <p>系统会先展示受影响步骤、预计新增智点和成果失效范围，再等待确认。</p>
            <textarea ref={guidanceInputRef} aria-label="补充或纠正内容" value={guidance} onChange={(event) => setGuidance(event.target.value)} placeholder="例如：保留当前主视觉，只增加 16:9 和 1:1 尺寸，标题向上移动…" />
            <div className="guidance-impact"><span>预计影响</span><strong>2 个步骤 · +180 智点 · 候选图保持有效</strong></div>
            <div className="modal-actions"><button type="button" onClick={() => setGuidanceOpen(false)}>取消</button><button type="button" disabled={!guidance.trim()} onClick={() => { onAction("GUIDE_TASK", { text: guidance }); setGuidanceOpen(false); }}>确认并生成新计划</button></div>
          </div>
        </div>
      )}
    </EventWorkSurface>
  );
}
