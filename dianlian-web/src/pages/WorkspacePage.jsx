import { useEffect, useMemo, useState } from "react";
import {
  IconArrowRight,
  IconBook2,
  IconBrandAdobe,
  IconCalculator,
  IconCheck,
  IconFileDescription,
  IconFileText,
  IconHistory,
  IconMessageCircle2,
  IconPaperclip,
  IconScale,
  IconShieldCheck,
  IconSparkles,
  IconUpload,
} from "@tabler/icons-react";
import { EventWorkSurface } from "../components/EventWorkSurface.jsx";
import { StatusChip } from "../components/StatusChip.jsx";
import "./workspace.css";

const capabilityContent = {
  GRAPHIC_DESIGN: {
    title: "建立视觉简报",
    intro: "我会先确认用途、尺寸、文案和品牌素材，再生成可比较的候选图。",
    placeholder: "例如：为 2026 夏季展会设计蓝色科技感主视觉，需要 16:9 和 1:1 两种尺寸…",
    tags: ["品牌规范 v3.2", "夏季展会文案", "渠道尺寸规则"],
    schemaId: "graphic-design-input",
    artifactType: "GRAPHIC_DESIGN_PACKAGE",
    fields: [
      { key: "usageScenario", label: "使用场景", value: "展会主视觉" },
      { key: "dimensions", label: "画面尺寸", value: "1920 × 1080 · 16:9" },
      { key: "candidateCount", label: "候选方案", value: "3" },
      { key: "outputFormats", label: "输出格式", value: "PNG,PDF" },
    ],
    plan: ["确认视觉简报与素材", "生成基础候选图", "人工选版与局部修改", "派生多尺寸版本", "文字、品牌与版权确认"],
    icon: IconBrandAdobe,
  },
  CONTRACT_REVIEW: {
    title: "提交合同与审核口径",
    intro: "我会定位条款、列出风险和修改建议；高风险结果必须由有权限的法务人员确认。",
    placeholder: "补充我方身份、合同类型、交易背景和需要重点关注的事项…",
    tags: ["场馆服务合同模板", "企业条款库 v5", "风险规则 2026.1"],
    schemaId: "contract-review-input",
    artifactType: "CONTRACT_REVIEW_REPORT",
    fields: [
      { key: "contractFileName", label: "合同文件", value: "场馆服务合同-对方版.pdf" },
      { key: "partyRole", label: "我方身份", value: "采购方" },
      { key: "reviewPolicy", label: "审核口径", value: "星海会展标准条款" },
      { key: "focusAreas", label: "重点关注", value: "付款,违约,知识产权" },
    ],
    plan: ["文件解析与条款分段", "确认合同类型和适用口径", "检索规则与历史处理", "风险分级与修改建议", "生成报告并提交法务确认"],
    icon: IconScale,
  },
  QUOTATION: {
    title: "整理报价需求",
    intro: "我会关联授权历史案例，按冻结的成本和价格规则确定性复算，不会猜测缺失价格。",
    placeholder: "例如：工商银行 180㎡ 展台，包含搭建、灯光、屏幕、运输和驻场服务…",
    tags: ["历史项目库", "供应成本 2026-Q2", "报价规则 v8.4"],
    schemaId: "quotation-input",
    artifactType: "QUOTATION_PACKAGE",
    fields: [
      { key: "customerProject", label: "客户与项目", value: "工商银行 · 上海金融展" },
      { key: "areaSquareMeters", label: "项目面积（㎡）", value: "180", inputMode: "decimal" },
      { key: "taxRatePercent", label: "含税税率（%）", value: "6", inputMode: "decimal" },
      { key: "validityDays", label: "报价有效期（天）", value: "30", inputMode: "numeric" },
    ],
    plan: ["结构化需求并识别缺项", "关联历史案例与差异", "冻结成本和报价规则", "确定性测算与例外检查", "生成内外版并提交审批"],
    icon: IconCalculator,
  },
};

const genericCapabilityContent = {
  title: "整理工作输入",
  intro: "我会按当前员工版本的输入规则整理目标，再生成可追踪的执行计划。",
  placeholder: "描述工作背景、约束和期望成果…",
  tags: [],
  schemaId: null,
  artifactType: null,
  fields: [],
  plan: [],
  icon: IconSparkles,
};

function mergeWorkspaceContract(baseContent, workspaceContract) {
  if (!workspaceContract) return baseContent;
  const labels = new Map(baseContent.fields.map((field) => [field.key, field.label]));
  return {
    ...baseContent,
    schemaId: workspaceContract.inputSchema.schemaId,
    schemaVersion: workspaceContract.inputSchema.schemaVersion,
    fields: workspaceContract.inputSchema.fields.map((field) => ({
      ...field,
      label: field.label === field.key ? labels.get(field.key) ?? field.label : field.label,
    })),
    plan: workspaceContract.executionTemplate.steps,
  };
}

function initialFieldValues(content, apiMode) {
  return Object.fromEntries(content.fields.map((field) => [
    field.key,
    apiMode ? formatInitialFieldValue(field) : field.value,
  ]));
}

function formatInitialFieldValue(field) {
  const value = field.defaultValue;
  if (value === undefined || value === null) return "";
  if (["array", "object"].includes(field.type) && typeof value !== "string") {
    return JSON.stringify(value);
  }
  return value;
}

function FieldControl({ field, value, onChange }) {
  if (field.options?.length > 0) {
    return (
      <select value={String(value ?? "")} onChange={(event) => onChange(event.target.value)}>
        <option value="">请选择</option>
        {field.options.map((option) => <option key={String(option.value)} value={String(option.value)}>{option.label}</option>)}
      </select>
    );
  }
  if (field.type === "boolean") {
    return <select value={String(value ?? "")} onChange={(event) => onChange(event.target.value)}><option value="">请选择</option><option value="true">是</option><option value="false">否</option></select>;
  }
  if (field.type === "object") {
    return <textarea value={value ?? ""} onChange={(event) => onChange(event.target.value)} placeholder="请输入 JSON 对象" />;
  }
  return (
    <input
      inputMode={field.inputMode ?? (["number", "integer"].includes(field.type) ? "decimal" : undefined)}
      type={["number", "integer"].includes(field.type) ? "number" : "text"}
      step={field.type === "integer" ? "1" : field.type === "number" ? "any" : undefined}
      min={field.minimum ?? undefined}
      max={field.maximum ?? undefined}
      minLength={field.minLength ?? undefined}
      maxLength={field.maxLength ?? undefined}
      value={value ?? ""}
      onChange={(event) => onChange(event.target.value)}
      placeholder={field.type === "array" ? "多个值请用逗号分隔" : undefined}
    />
  );
}

function CapabilityForm({ content, values, onValueChange, brief, onBriefChange, apiMode }) {
  const Icon = content.icon;
  return (
    <div className="capability-form">
      <div className="capability-form__title">
        <span><Icon size={22} /></span>
        <div><h2>{content.title}</h2><p>{content.intro}</p>{apiMode ? <small>输入规则 {content.schemaId} · v{content.schemaVersion}</small> : null}</div>
      </div>
      <div className="capability-form__fields">
        {content.fields.map((field) => (
          <label key={field.key}>
            <span>{field.label}{field.required ? " *" : ""}</span>
            <FieldControl field={field} value={values[field.key]} onChange={(value) => onValueChange(field.key, value)} />
            {field.description ? <small>{field.description}</small> : null}
          </label>
        ))}
      </div>
      <label className="capability-form__brief">
        <span>补充说明</span>
        <textarea aria-label="补充说明" value={brief} onChange={(event) => onBriefChange(event.target.value)} placeholder={content.placeholder} />
      </label>
      <div className="capability-form__upload">
        <IconUpload size={20} />
        <span><strong>添加工作资料</strong><small>{apiMode ? "附件接口尚未进入当前真实切片" : "文档、图片或表格会按当前任务权限使用"}</small></span>
        <button type="button" disabled={apiMode}>选择文件</button>
      </div>
    </div>
  );
}

export function WorkspacePage({
  agent,
  task,
  initialGoal,
  onBack,
  onStartTask,
  onOpenTask,
  onMessageAgent = null,
  mode = "prototype",
  workspaceContract = null,
  submitting = false,
  submitError = null,
}) {
  const apiMode = mode === "api";
  const [activeTab, setActiveTab] = useState("work");
  const [message, setMessage] = useState("");
  const [conversationMessages, setConversationMessages] = useState(apiMode ? [] : [
    { id: "agent-welcome", type: "agent", text: "你好，我会先把目标整理成可确认计划，再开始执行。" },
    { id: "human-context", type: "human", text: initialGoal || "请先按当前项目资料准备一版专业方案，过程中有歧义先问我。" },
  ]);
  const baseContent = useMemo(() => capabilityContent[agent.capability] ?? genericCapabilityContent, [agent.capability]);
  const content = useMemo(() => mergeWorkspaceContract(baseContent, workspaceContract), [baseContent, workspaceContract]);
  const [fieldValues, setFieldValues] = useState(() => initialFieldValues(content, apiMode));
  const [brief, setBrief] = useState(initialGoal || (!apiMode && agent.capability === "GRAPHIC_DESIGN" ? "画面需要专业、明亮，标题突出；避免紫色和游戏感。" : ""));
  const [maxPointCost, setMaxPointCost] = useState(apiMode ? workspaceContract?.pointEstimate ?? "" : task.pointSummary.estimatedMax);
  const [localError, setLocalError] = useState("");
  const isStarted = task.status !== "DRAFT";

  useEffect(() => {
    setFieldValues(initialFieldValues(content, apiMode));
    setBrief(initialGoal || (!apiMode && agent.capability === "GRAPHIC_DESIGN" ? "画面需要专业、明亮，标题突出；避免紫色和游戏感。" : ""));
    setMaxPointCost(apiMode ? workspaceContract?.pointEstimate ?? "" : task.pointSummary.estimatedMax);
    setLocalError("");
  }, [agent.capability, agent.id, apiMode, content, initialGoal, task.pointSummary.estimatedMax, workspaceContract?.pointEstimate]);
  const sendConversationMessage = () => {
    if (apiMode) return;
    const text = message.trim();
    if (!text) return;
    setConversationMessages((items) => [
      ...items,
      { id: `human-${items.length}`, type: "human", text },
      { id: `agent-${items.length}`, type: "agent", text: `收到。我会把“${text.slice(0, 28)}”纳入当前工作上下文，并在执行前展示影响范围。` },
    ]);
    setMessage("");
  };

  const startTask = () => {
    if (apiMode && !brief.trim()) {
      setLocalError("请先填写明确的工作目标");
      return;
    }
    setLocalError("");
    onStartTask({
      goal: brief.trim() || task.title,
      maxPointCost,
      rawCapabilityValues: fieldValues,
      capabilityInput: {
        schemaId: content.schemaId,
        schemaVersion: content.schemaVersion ?? "1",
        values: apiMode ? fieldValues : { ...fieldValues, brief: brief.trim() },
      },
      desiredArtifactType: apiMode ? null : content.artifactType,
    });
  };

  return (
    <EventWorkSurface
      eyebrow="数字员工个人工作台"
      title={agent.name}
      description="岗位配置、企业知识和独立记忆仅在当前员工与授权范围内生效"
      onClose={onBack}
      className="workspace-event-layer"
      actions={(
        <div className="workspace-topbar__status">
          <StatusChip tone={isStarted ? "success" : "neutral"}>{isStarted ? task.statusLabel : "准备开始"}</StatusChip>
          <span>本任务预计 {apiMode ? workspaceContract?.pointEstimate : task.pointSummary.estimatedMax} 智点</span>
        </div>
      )}
    >

      <section className="workspace-agent">
        <img src={agent.image} alt={agent.name} />
        <div>
          <span className="eyebrow"><IconSparkles size={14} /> 已选择数字员工</span>
          <h1>{agent.name}</h1>
          <p>{agent.profile}</p>
          <div className="workspace-agent__meta">
            <span><IconShieldCheck size={16} /> {apiMode ? "权限由服务端准入校验" : "已授权当前项目资料"}</span>
            <span><IconBook2 size={16} /> {apiMode ? "知识范围由员工版本决定" : `${content.tags.length} 个知识范围`}</span>
            <span><IconHistory size={16} /> {apiMode ? "员工版本与权限可追溯" : "历史任务版本可追溯"}</span>
          </div>
        </div>
      </section>

      <section className="workspace-grid">
        <div className="workspace-main">
          <div className="workspace-tabs">
            <button className={activeTab === "work" ? "is-active" : ""} type="button" onClick={() => setActiveTab("work")}>工作台</button>
            <button className={activeTab === "conversation" ? "is-active" : ""} type="button" onClick={() => setActiveTab("conversation")}>{apiMode ? "与员工对话" : "对话记录"}</button>
            <button className={activeTab === "versions" ? "is-active" : ""} type="button" onClick={() => setActiveTab("versions")}>版本与权限</button>
          </div>

          {activeTab === "work" && (
            <CapabilityForm
              content={content}
              values={fieldValues}
              onValueChange={(key, value) => setFieldValues((current) => ({ ...current, [key]: value }))}
              brief={brief}
              onBriefChange={setBrief}
              apiMode={apiMode}
            />
          )}
          {activeTab === "conversation" && (
            <div className="workspace-conversation">
              {apiMode ? <div className="workspace-direct-chat"><span><IconMessageCircle2 size={24} /></span><div><strong>进入与 {agent.name} 的真实会话</strong><p>已有一对一会话会直接打开；没有时由你确认创建。发送后使用该员工独立的岗位配置、企业知识范围和会话记忆。</p><button type="button" disabled={!onMessageAgent} onClick={() => onMessageAgent?.(agent.id)}>打开发消息 <IconArrowRight size={16} /></button>{!onMessageAgent ? <small>当前身份没有会话查看权限。</small> : null}</div></div> : conversationMessages.map((item) => <div className={`conversation-bubble conversation-bubble--${item.type}`} key={item.id}>{item.text}</div>)}
              {!apiMode ? <div className="conversation-compose">
                <textarea aria-label="给数字员工发送消息" value={message} onChange={(event) => setMessage(event.target.value)} placeholder="补充背景、约束或期望成果…" />
                <button type="button" aria-label="添加对话附件"><IconPaperclip size={18} /></button>
                <button type="button" disabled={!message.trim()} onClick={sendConversationMessage}>发送</button>
              </div> : null}
            </div>
          )}
          {activeTab === "versions" && (
            <div className="version-list">
              <div><IconFileDescription size={20} /><span><strong>{apiMode ? `执行模板 v${workspaceContract?.executionTemplate.version}` : `当前计划 v${task.planVersion}`}</strong><small>{apiMode ? "来自当前企业员工冻结版本" : "基于当前工作资料 · 尚未执行"}</small></span><StatusChip tone="info">当前</StatusChip></div>
              <div><IconFileText size={20} /><span><strong>输入规则</strong><small>{apiMode ? `${content.schemaId} · v${content.schemaVersion}` : "4 个字段 · 3 个知识范围 · 权限版本 18"}</small></span>{!apiMode ? <button type="button">查看</button> : null}</div>
            </div>
          )}
        </div>

        <aside className="workspace-plan">
          <div className="workspace-plan__heading">
            <span>执行计划</span>
            <StatusChip tone="info">v{task.planVersion}</StatusChip>
          </div>
          <h2>{task.title}</h2>
          <p>开始前可确认负责人、输入、成果、费用和人工检查点。</p>

          <ol className="plan-steps">
            {content.plan.map((step, index) => (
              <li key={apiMode ? step.key : step}>
                <span>{index + 1}</span>
                <div><strong>{apiMode ? step.title : step}</strong><small>{apiMode ? (step.humanCheckpoint ? "人工检查点" : step.executorType) : index === content.plan.length - 1 ? "人工检查点" : `${40 + index * 35}–${80 + index * 45} 智点`}</small></div>
                {index === 0 && <IconCheck size={17} />}
              </li>
            ))}
          </ol>

          <div className="plan-knowledge">
            <span>本次会使用</span>
            {apiMode ? <small>授权知识范围将在任务执行时由服务端按当前身份裁剪。</small> : content.tags.map((tag) => <button type="button" key={tag}><IconBook2 size={15} /> {tag}</button>)}
          </div>

          <div className="plan-cost">
            <div><span>员工版本预估</span><strong>{apiMode ? workspaceContract?.pointEstimate : task.pointSummary.estimatedMax} 智点</strong></div>
            {apiMode ? <label className="plan-cost__limit"><span>本次智点上限</span><input aria-label="本次智点上限" inputMode="decimal" value={maxPointCost} onChange={(event) => setMaxPointCost(event.target.value)} /></label> : <div><span>启动后预占</span><strong>{task.pointSummary.reserved || task.pointSummary.estimatedMax} 智点</strong></div>}
            <small>任务取消或提前结束时，未使用的预占智点会释放。</small>
          </div>

          {(localError || submitError) ? <div className="workspace-submit-error" role="alert">{localError || submitError}</div> : null}

          {isStarted ? (
            <button className="primary-action" type="button" onClick={() => onOpenTask(task.id)}>查看执行轨迹 <IconArrowRight size={18} /></button>
          ) : (
            <button className="primary-action" type="button" disabled={submitting || (apiMode && !workspaceContract?.canStartTask)} onClick={startTask}>{submitting ? "正在提交…" : workspaceContract?.canStartTask === false ? "当前无启动权限" : "确认计划并开始"} {!submitting ? <IconArrowRight size={18} /> : null}</button>
          )}
        </aside>
      </section>
    </EventWorkSurface>
  );
}
