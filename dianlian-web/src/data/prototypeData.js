export const CAPABILITY_KIND = Object.freeze({
  GRAPHIC_DESIGN: "GRAPHIC_DESIGN",
  CONTRACT_REVIEW: "CONTRACT_REVIEW",
  QUOTATION: "QUOTATION",
});

export const TASK_STATUS = Object.freeze({
  DRAFT: "DRAFT",
  PLANNING: "PLANNING",
  WAITING_USER: "WAITING_USER",
  QUEUED: "QUEUED",
  RUNNING: "RUNNING",
  APPLYING_GUIDANCE: "APPLYING_GUIDANCE",
  REPLANNING: "REPLANNING",
  WAITING_CONFIRMATION: "WAITING_CONFIRMATION",
  WAITING_APPROVAL: "WAITING_APPROVAL",
  PAUSED: "PAUSED",
  SUCCEEDED: "SUCCEEDED",
  PARTIAL_SUCCESS: "PARTIAL_SUCCESS",
  FAILED: "FAILED",
  CANCELLED: "CANCELLED",
});

export const TASK_BLOCKER = Object.freeze({
  NONE: "NONE",
  QUOTA: "QUOTA",
  AUTH: "AUTH",
  SIDE_EFFECT_RECONCILIATION: "SIDE_EFFECT_RECONCILIATION",
});

export const STEP_STATUS = Object.freeze({
  PENDING: "PENDING",
  READY: "READY",
  RUNNING: "RUNNING",
  WAITING_EXTERNAL: "WAITING_EXTERNAL",
  RETRY_WAIT: "RETRY_WAIT",
  SUCCEEDED: "SUCCEEDED",
  FAILED_FINAL: "FAILED_FINAL",
  SKIPPED: "SKIPPED",
  CANCELLED: "CANCELLED",
  BLOCKED_SIDE_EFFECT_RECONCILIATION: "BLOCKED_SIDE_EFFECT_RECONCILIATION",
});

export const RUN_STATUS = Object.freeze({
  QUEUED: "QUEUED",
  RUNNING: "RUNNING",
  WAITING_USER_INPUT: "WAITING_USER_INPUT",
  WAITING_AUTH: "WAITING_AUTH",
  PAUSED: "PAUSED",
  CANCEL_REQUESTED: "CANCEL_REQUESTED",
  CANCELLING: "CANCELLING",
  COMPLETED: "COMPLETED",
  FAILED: "FAILED",
  CANCELLED: "CANCELLED",
  CANCEL_OUTCOME_UNKNOWN: "CANCEL_OUTCOME_UNKNOWN",
});

export const ARTIFACT_STATUS = Object.freeze({
  DRAFT: "DRAFT",
  READY: "READY",
  STALE: "STALE",
  SECURITY_REJECTED: "SECURITY_REJECTED",
});

export const APPROVAL_STATUS = Object.freeze({
  PENDING: "PENDING",
  APPROVED: "APPROVED",
  REJECTED: "REJECTED",
  WITHDRAWN: "WITHDRAWN",
  INVALIDATED: "INVALIDATED",
});

export const POINT_RESERVATION_STATUS = Object.freeze({
  ACTIVE: "ACTIVE",
  PARTIALLY_CAPTURED: "PARTIALLY_CAPTURED",
  CAPTURED: "CAPTURED",
  RELEASED: "RELEASED",
  EXPIRED: "EXPIRED",
  USAGE_PENDING: "USAGE_PENDING",
  UNCOLLECTED: "UNCOLLECTED",
});

export const GROUP_MODE = Object.freeze({
  SINGLE_TARGET: "SINGLE_TARGET",
  PARALLEL_SEPARATE: "PARALLEL_SEPARATE",
  PRIMARY_SUMMARY: "PRIMARY_SUMMARY",
});

export const MESSAGE_TRIGGER_TYPE = Object.freeze({
  SELECTION: "SELECTION",
  MENTION: "MENTION",
  REPLY: "REPLY",
});

export const PROTOTYPE_ACTION = Object.freeze({
  SELECT_AGENT: "SELECT_AGENT",
  START_TASK: "START_TASK",
  ADVANCE_STEP: "ADVANCE_STEP",
  GUIDE_TASK: "GUIDE_TASK",
  PAUSE_TASK: "PAUSE_TASK",
  PAUSE: "PAUSE",
  RESUME_TASK: "RESUME_TASK",
  RESUME: "RESUME",
  SELECT_ARTIFACT: "SELECT_ARTIFACT",
  SUBMIT_APPROVAL: "SUBMIT_APPROVAL",
  SUBMIT: "SUBMIT",
  APPROVE_APPROVAL: "APPROVE_APPROVAL",
  APPROVE: "APPROVE",
  REJECT_APPROVAL: "REJECT_APPROVAL",
  SEND_GROUP_MESSAGE: "SEND_GROUP_MESSAGE",
});

export const TASK_DISPLAY = Object.freeze({
  DRAFT: { label: "草稿", tone: "neutral" },
  PLANNING: { label: "正在制定计划", tone: "processing" },
  WAITING_USER: { label: "等待你补充", tone: "waiting" },
  QUEUED: { label: "排队中", tone: "processing" },
  RUNNING: { label: "执行中", tone: "processing" },
  APPLYING_GUIDANCE: { label: "正在分析修改", tone: "processing" },
  REPLANNING: { label: "正在调整计划", tone: "processing" },
  WAITING_CONFIRMATION: { label: "待确认", tone: "waiting" },
  WAITING_APPROVAL: { label: "待审批", tone: "waiting" },
  PAUSED: { label: "已暂停", tone: "warning" },
  SUCCEEDED: { label: "任务已完成", tone: "success" },
  PARTIAL_SUCCESS: { label: "部分完成", tone: "warning" },
  FAILED: { label: "执行失败", tone: "danger" },
  CANCELLED: { label: "已取消", tone: "neutral" },
});

export const CAPABILITY_TASK_TEMPLATES = Object.freeze({
  GRAPHIC_DESIGN: {
    defaultTitle: "生成展会主视觉与多尺寸物料",
    estimatedPoints: 600,
    chatPointEstimate: 45,
    steps: [
      { key: "brief", title: "确认用途、文案与尺寸", executorType: "AGENT", actualPoints: 40 },
      { key: "preview", title: "生成候选预览", executorType: "AGENT", actualPoints: 280 },
      { key: "spec", title: "确认方案与输出规格", executorType: "HUMAN", actualPoints: 0 },
      { key: "export", title: "导出多尺寸成果", executorType: "TOOL", actualPoints: 180 },
    ],
  },
  CONTRACT_REVIEW: {
    defaultTitle: "审核合同条款并形成风险报告",
    estimatedPoints: 300,
    chatPointEstimate: 35,
    steps: [
      { key: "file", title: "确认合同版本与审核范围", executorType: "AGENT", actualPoints: 20 },
      { key: "parse", title: "解析合同与条款映射", executorType: "TOOL", actualPoints: 60 },
      { key: "risk", title: "识别风险并生成修改建议", executorType: "AGENT", actualPoints: 100 },
      { key: "human-review", title: "法务人工确认", executorType: "HUMAN", actualPoints: 0 },
    ],
  },
  QUOTATION: {
    defaultTitle: "生成项目报价草案",
    estimatedPoints: 350,
    chatPointEstimate: 30,
    steps: [
      { key: "requirements", title: "校验报价输入", executorType: "AGENT", actualPoints: 25 },
      { key: "evidence", title: "匹配历史项目依据", executorType: "AGENT", actualPoints: 70 },
      { key: "calculation", title: "规则引擎计算金额", executorType: "RULE_ENGINE", actualPoints: 115 },
      { key: "price-approval", title: "价格人工审批", executorType: "HUMAN", actualPoints: 0 },
    ],
  },
});

const seedUsersById = {
  "user-current": {
    id: "user-current",
    tenantId: "tenant-xinghai",
    name: "陈曦",
    avatarUrl: "/assets/avatars/current-user.png",
    roleCodes: ["ENTERPRISE_MEMBER", "LEGAL_REVIEWER", "PRICE_APPROVER"],
    status: "ACTIVE",
  },
  "user-business": {
    id: "user-business",
    tenantId: "tenant-xinghai",
    name: "林悦",
    roleCodes: ["ENTERPRISE_MEMBER", "TASK_OWNER"],
    status: "ACTIVE",
  },
  "user-sales": {
    id: "user-sales",
    tenantId: "tenant-xinghai",
    name: "周航",
    roleCodes: ["ENTERPRISE_MEMBER", "TASK_OWNER"],
    status: "ACTIVE",
  },
};

const seedAgentsById = {
  "agent-graphic": {
    id: "agent-graphic",
    tenantId: "tenant-xinghai",
    name: "平面出图专员",
    capability: CAPABILITY_KIND.GRAPHIC_DESIGN,
    title: "品牌视觉与多尺寸物料",
    description: "根据用途、品牌规范和尺寸要求生成并交付版本化视觉成果。",
    skillLabels: ["主视觉", "多尺寸", "图像生成"],
    imageUrl: "/assets/employees/graphic-designer.png",
    availability: "ACTIVE",
  },
  "agent-contract": {
    id: "agent-contract",
    tenantId: "tenant-xinghai",
    name: "法务合同审核专员",
    capability: CAPABILITY_KIND.CONTRACT_REVIEW,
    title: "条款审查与风险提示",
    description: "定位合同风险、引用原文并形成待人工法务确认的修改建议。",
    skillLabels: ["条款定位", "风险分级", "红线建议"],
    imageUrl: "/assets/employees/contract-reviewer.png",
    availability: "ACTIVE",
  },
  "agent-quotation": {
    id: "agent-quotation",
    tenantId: "tenant-xinghai",
    name: "报价专员",
    capability: CAPABILITY_KIND.QUOTATION,
    title: "项目报价与价格审批",
    description: "匹配历史依据并通过确定性规则生成可审批的报价草案。",
    skillLabels: ["历史匹配", "规则计算", "报价审批"],
    imageUrl: "/assets/employees/quotation-specialist.png",
    availability: "ACTIVE",
  },
};

const seedTasksById = {
  "task-graphic-001": {
    id: "task-graphic-001",
    tenantId: "tenant-xinghai",
    agentId: "agent-graphic",
    collaboratingAgentIds: [],
    capability: CAPABILITY_KIND.GRAPHIC_DESIGN,
    title: "夏季展会主视觉 · 生成候选图",
    source: { type: "DIRECT", conversationId: "conversation-graphic" },
    ownerId: "user-current",
    participantIds: ["user-current"],
    approverIds: ["user-business"],
    status: TASK_STATUS.RUNNING,
    blocker: TASK_BLOCKER.NONE,
    activePlanId: "plan-graphic-v1",
    activeStepId: "step-graphic-preview",
    currentRunId: "run-graphic-001",
    selectedArtifactId: null,
    pointReservationId: "point-reservation-graphic",
    createdAt: "2026-08-11T09:00:00+08:00",
    updatedAt: "2026-08-11T09:26:00+08:00",
    capabilityData: {
      brief: {
        purpose: "夏季展会主视觉",
        copy: "智启未来，共创连接",
        brandAssetIds: ["brand-guide-2026"],
      },
      outputSpecs: [
        { id: "spec-graphic-16x9", label: "展厅大屏", width: 1920, height: 1080, unit: "PX", format: "PNG", status: "PENDING" },
        { id: "spec-graphic-poster", label: "竖版海报", width: 1080, height: 1440, unit: "PX", format: "PNG", status: "PENDING" },
        { id: "spec-graphic-print", label: "印刷展板", width: 1200, height: 900, unit: "MM", dpi: 300, bleedMm: 3, format: "PDF", status: "PENDING" },
      ],
      rightsFlags: ["BRAND"],
    },
  },
  "task-contract-001": {
    id: "task-contract-001",
    tenantId: "tenant-xinghai",
    agentId: "agent-contract",
    collaboratingAgentIds: [],
    capability: CAPABILITY_KIND.CONTRACT_REVIEW,
    title: "场馆服务合同 · 3 项高风险",
    source: { type: "GROUP", conversationId: "conversation-project", sourceMessageId: "message-project-002" },
    ownerId: "user-business",
    participantIds: ["user-business", "user-current"],
    approverIds: ["user-current"],
    status: TASK_STATUS.WAITING_CONFIRMATION,
    blocker: TASK_BLOCKER.NONE,
    activePlanId: "plan-contract-v1",
    activeStepId: "step-contract-human",
    currentRunId: "run-contract-001",
    selectedArtifactId: "artifact-contract-report-v1",
    pointReservationId: "point-reservation-contract",
    createdAt: "2026-08-11T08:20:00+08:00",
    updatedAt: "2026-08-11T09:18:00+08:00",
    capabilityData: {
      contractVersion: {
        fileName: "场馆服务合同-v3.pdf",
        contentHash: "sha256:contract-v3-demo",
        pages: 18,
      },
      risks: [
        { id: "risk-001", level: "HIGH", clauseRef: "第 7 条", title: "违约责任不对等", summary: "甲方承担范围明显高于对方。", suggestion: "调整为双方对等责任并设置上限。", decision: "PENDING", requiresHuman: true },
        { id: "risk-002", level: "HIGH", clauseRef: "第 12 条", title: "单方解除权", summary: "对方可单方解除且未约定补偿。", suggestion: "补充通知期及已发生成本补偿。", decision: "PENDING", requiresHuman: true },
        { id: "risk-003", level: "HIGH", clauseRef: "第 18 条", title: "争议管辖不利", summary: "约定由对方所在地法院管辖。", suggestion: "改为合同履行地或双方协商地点。", decision: "PENDING", requiresHuman: true },
      ],
    },
  },
  "task-quotation-001": {
    id: "task-quotation-001",
    tenantId: "tenant-xinghai",
    agentId: "agent-quotation",
    collaboratingAgentIds: [],
    capability: CAPABILITY_KIND.QUOTATION,
    title: "工商银行展台项目 · 报价 v2",
    source: { type: "GROUP", conversationId: "conversation-project", sourceMessageId: "message-project-003" },
    ownerId: "user-sales",
    participantIds: ["user-sales", "user-current"],
    approverIds: ["user-current"],
    status: TASK_STATUS.WAITING_APPROVAL,
    blocker: TASK_BLOCKER.NONE,
    activePlanId: "plan-quotation-v1",
    activeStepId: "step-quotation-approval",
    currentRunId: "run-quotation-001",
    selectedArtifactId: "artifact-quotation-v2",
    approvalId: "approval-quotation-v2",
    pointReservationId: "point-reservation-quotation",
    createdAt: "2026-08-11T08:40:00+08:00",
    updatedAt: "2026-08-11T09:12:00+08:00",
    capabilityData: {
      currency: "CNY",
      taxMode: "INCLUDED",
      validUntil: "2026-08-25",
      ruleVersion: "quotation-rule-2026.08",
      items: [
        { id: "quote-item-001", name: "人工成本", quantity: 1, unitPriceMinor: 12840000, amountMinor: 12840000, costMinor: 9620000 },
        { id: "quote-item-002", name: "物料成本", quantity: 1, unitPriceMinor: 8375000, amountMinor: 8375000, costMinor: 6540000 },
        { id: "quote-item-003", name: "场地费用", quantity: 1, unitPriceMinor: 5620000, amountMinor: 5620000, costMinor: 5620000 },
        { id: "quote-item-004", name: "其他费用", quantity: 1, unitPriceMinor: 1263000, amountMinor: 1263000, costMinor: 980000 },
      ],
      totals: { subtotalMinor: 28098000, taxMinor: 0, totalMinor: 28098000, costMinor: 22760000, marginMinor: 5338000 },
      exceptions: [],
    },
  },
};

const seedPlansById = {
  "plan-graphic-v1": { id: "plan-graphic-v1", taskId: "task-graphic-001", version: 1, previousPlanId: null, status: "ACTIVE", stepIds: ["step-graphic-brief", "step-graphic-preview", "step-graphic-spec", "step-graphic-export"], createdAt: "2026-08-11T09:02:00+08:00" },
  "plan-contract-v1": { id: "plan-contract-v1", taskId: "task-contract-001", version: 1, previousPlanId: null, status: "ACTIVE", stepIds: ["step-contract-file", "step-contract-parse", "step-contract-risk", "step-contract-human"], createdAt: "2026-08-11T08:22:00+08:00" },
  "plan-quotation-v1": { id: "plan-quotation-v1", taskId: "task-quotation-001", version: 1, previousPlanId: null, status: "ACTIVE", stepIds: ["step-quotation-input", "step-quotation-evidence", "step-quotation-calc", "step-quotation-approval"], createdAt: "2026-08-11T08:42:00+08:00" },
};

const seedStepsById = {
  "step-graphic-brief": { id: "step-graphic-brief", taskId: "task-graphic-001", key: "brief", title: "确认用途、文案与尺寸", status: STEP_STATUS.SUCCEEDED, executorType: "AGENT", executorId: "agent-graphic", dependsOn: [], outputArtifactIds: [], actualPoints: 40, capturedPoints: 40 },
  "step-graphic-preview": { id: "step-graphic-preview", taskId: "task-graphic-001", key: "preview", title: "生成候选预览", status: STEP_STATUS.RUNNING, executorType: "AGENT", executorId: "agent-graphic", dependsOn: ["step-graphic-brief"], outputArtifactIds: ["artifact-graphic-preview-v1", "artifact-graphic-preview-v2"], actualPoints: 280, capturedPoints: 280 },
  "step-graphic-spec": { id: "step-graphic-spec", taskId: "task-graphic-001", key: "spec", title: "确认方案与输出规格", status: STEP_STATUS.PENDING, executorType: "HUMAN", executorId: "user-current", dependsOn: ["step-graphic-preview"], outputArtifactIds: [], actualPoints: 0, capturedPoints: 0 },
  "step-graphic-export": { id: "step-graphic-export", taskId: "task-graphic-001", key: "export", title: "导出多尺寸成果", status: STEP_STATUS.PENDING, executorType: "TOOL", executorId: "graphic-renderer", dependsOn: ["step-graphic-spec"], outputArtifactIds: [], actualPoints: 180, capturedPoints: 0 },
  "step-contract-file": { id: "step-contract-file", taskId: "task-contract-001", key: "file", title: "确认合同版本与审核范围", status: STEP_STATUS.SUCCEEDED, executorType: "AGENT", executorId: "agent-contract", dependsOn: [], outputArtifactIds: [], actualPoints: 20, capturedPoints: 20 },
  "step-contract-parse": { id: "step-contract-parse", taskId: "task-contract-001", key: "parse", title: "解析合同与条款映射", status: STEP_STATUS.SUCCEEDED, executorType: "TOOL", executorId: "contract-parser", dependsOn: ["step-contract-file"], outputArtifactIds: [], actualPoints: 60, capturedPoints: 60 },
  "step-contract-risk": { id: "step-contract-risk", taskId: "task-contract-001", key: "risk", title: "识别风险并生成修改建议", status: STEP_STATUS.SUCCEEDED, executorType: "AGENT", executorId: "agent-contract", dependsOn: ["step-contract-parse"], outputArtifactIds: ["artifact-contract-report-v1"], actualPoints: 100, capturedPoints: 100 },
  "step-contract-human": { id: "step-contract-human", taskId: "task-contract-001", key: "human-review", title: "法务人工确认", status: STEP_STATUS.READY, executorType: "HUMAN", executorId: "user-current", dependsOn: ["step-contract-risk"], outputArtifactIds: [], actualPoints: 0, capturedPoints: 0 },
  "step-quotation-input": { id: "step-quotation-input", taskId: "task-quotation-001", key: "requirements", title: "校验报价输入", status: STEP_STATUS.SUCCEEDED, executorType: "AGENT", executorId: "agent-quotation", dependsOn: [], outputArtifactIds: [], actualPoints: 25, capturedPoints: 25 },
  "step-quotation-evidence": { id: "step-quotation-evidence", taskId: "task-quotation-001", key: "evidence", title: "匹配历史项目依据", status: STEP_STATUS.SUCCEEDED, executorType: "AGENT", executorId: "agent-quotation", dependsOn: ["step-quotation-input"], outputArtifactIds: [], actualPoints: 70, capturedPoints: 70 },
  "step-quotation-calc": { id: "step-quotation-calc", taskId: "task-quotation-001", key: "calculation", title: "规则引擎计算金额", status: STEP_STATUS.SUCCEEDED, executorType: "RULE_ENGINE", executorId: "quotation-rule-engine", dependsOn: ["step-quotation-evidence"], outputArtifactIds: ["artifact-quotation-v2"], actualPoints: 115, capturedPoints: 115 },
  "step-quotation-approval": { id: "step-quotation-approval", taskId: "task-quotation-001", key: "price-approval", title: "价格人工审批", status: STEP_STATUS.READY, executorType: "HUMAN", executorId: "user-current", dependsOn: ["step-quotation-calc"], outputArtifactIds: [], actualPoints: 0, capturedPoints: 0 },
};

const seedRunsById = {
  "run-graphic-001": { id: "run-graphic-001", taskId: "task-graphic-001", stepId: "step-graphic-preview", runNo: 1, status: RUN_STATUS.RUNNING, eventIds: ["event-g-001", "event-g-002", "event-g-003"], startedAt: "2026-08-11T09:02:00+08:00", endedAt: null },
  "run-contract-001": { id: "run-contract-001", taskId: "task-contract-001", stepId: "step-contract-human", runNo: 1, status: RUN_STATUS.WAITING_USER_INPUT, eventIds: ["event-c-001", "event-c-002", "event-c-003"], startedAt: "2026-08-11T08:22:00+08:00", endedAt: null },
  "run-quotation-001": { id: "run-quotation-001", taskId: "task-quotation-001", stepId: "step-quotation-approval", runNo: 1, status: RUN_STATUS.WAITING_USER_INPUT, eventIds: ["event-q-001", "event-q-002", "event-q-003"], startedAt: "2026-08-11T08:42:00+08:00", endedAt: null },
};

const seedRunEventsById = {
  "event-g-001": { id: "event-g-001", runId: "run-graphic-001", type: "PLAN_CREATED", title: "执行计划已确认", summary: "将先生成候选图，再确认规格并导出三个尺寸。", occurredAt: "2026-08-11T09:02:00+08:00" },
  "event-g-002": { id: "event-g-002", runId: "run-graphic-001", type: "STEP_COMPLETED", title: "需求已整理", summary: "已锁定主视觉文案、品牌规范与三个输出尺寸。", occurredAt: "2026-08-11T09:08:00+08:00" },
  "event-g-003": { id: "event-g-003", runId: "run-graphic-001", type: "STEP_STARTED", title: "正在生成候选图", summary: "当前批次将生成两版候选预览。", occurredAt: "2026-08-11T09:26:00+08:00" },
  "event-c-001": { id: "event-c-001", runId: "run-contract-001", type: "PLAN_CREATED", title: "合同审核计划已建立", summary: "审核范围包含责任、解除、付款和争议解决条款。", occurredAt: "2026-08-11T08:22:00+08:00" },
  "event-c-002": { id: "event-c-002", runId: "run-contract-001", type: "ARTIFACT_READY", title: "风险报告已生成", summary: "共识别 3 项高风险，均已关联合同原文位置。", occurredAt: "2026-08-11T09:14:00+08:00", artifactId: "artifact-contract-report-v1" },
  "event-c-003": { id: "event-c-003", runId: "run-contract-001", type: "CHECKPOINT_REQUIRED", title: "等待法务人工确认", summary: "请逐条处理高风险项，AI 结论不等同于法务批准。", occurredAt: "2026-08-11T09:18:00+08:00" },
  "event-q-001": { id: "event-q-001", runId: "run-quotation-001", type: "EVIDENCE_FOUND", title: "已匹配历史依据", summary: "匹配到 4 个同客户与同规模项目，采用已授权价格来源。", occurredAt: "2026-08-11T08:56:00+08:00" },
  "event-q-002": { id: "event-q-002", runId: "run-quotation-001", type: "ARTIFACT_READY", title: "报价草案 v2 已生成", summary: "金额由报价规则版本 quotation-rule-2026.08 计算。", occurredAt: "2026-08-11T09:08:00+08:00", artifactId: "artifact-quotation-v2" },
  "event-q-003": { id: "event-q-003", runId: "run-quotation-001", type: "CHECKPOINT_REQUIRED", title: "等待价格审批", summary: "批准仅对报价 v2 生效，不代表已经发送客户。", occurredAt: "2026-08-11T09:12:00+08:00" },
};

const seedArtifactsById = {
  "artifact-graphic-preview-v1": { id: "artifact-graphic-preview-v1", taskId: "task-graphic-001", type: "IMAGE", title: "夏季展会主视觉 · 候选 A", version: 1, status: ARTIFACT_STATUS.DRAFT, previewUrl: "/assets/artifacts/graphic-preview-a.png", contentHash: "sha256:graphic-preview-a", parentVersionId: null, metadata: { width: 1600, height: 1000, isPreview: true } },
  "artifact-graphic-preview-v2": { id: "artifact-graphic-preview-v2", taskId: "task-graphic-001", type: "IMAGE", title: "夏季展会主视觉 · 候选 B", version: 2, status: ARTIFACT_STATUS.DRAFT, previewUrl: "/assets/artifacts/graphic-preview-b.png", contentHash: "sha256:graphic-preview-b", parentVersionId: "artifact-graphic-preview-v1", metadata: { width: 1600, height: 1000, isPreview: true } },
  "artifact-contract-report-v1": { id: "artifact-contract-report-v1", taskId: "task-contract-001", type: "CONTRACT_REPORT", title: "场馆服务合同风险报告", version: 1, status: ARTIFACT_STATUS.READY, previewUrl: null, contentHash: "sha256:contract-report-v1", parentVersionId: null, metadata: { highRiskCount: 3, mediumRiskCount: 2, lowRiskCount: 1 } },
  "artifact-quotation-v2": { id: "artifact-quotation-v2", taskId: "task-quotation-001", type: "QUOTATION", title: "工商银行展台项目报价 v2", version: 2, status: ARTIFACT_STATUS.READY, previewUrl: null, contentHash: "sha256:quotation-v2", parentVersionId: null, metadata: { currency: "CNY", totalMinor: 28098000, validUntil: "2026-08-25" } },
};

const seedApprovalsById = {
  "approval-quotation-v2": { id: "approval-quotation-v2", taskId: "task-quotation-001", artifactVersionId: "artifact-quotation-v2", type: "PRICE", status: APPROVAL_STATUS.PENDING, requestedBy: "user-sales", approverId: "user-current", comment: null, requestedAt: "2026-08-11T09:12:00+08:00", decidedAt: null },
};

const seedConversationsById = {
  "conversation-graphic": { id: "conversation-graphic", tenantId: "tenant-xinghai", type: "DIRECT", title: "与平面出图专员协作", memberIds: ["user-current"], agentIds: ["agent-graphic"], messageIds: [], status: "ACTIVE" },
  "conversation-project": { id: "conversation-project", tenantId: "tenant-xinghai", type: "GROUP", title: "工商银行展会项目协作群", memberIds: ["user-current", "user-business", "user-sales"], agentIds: ["agent-graphic", "agent-contract", "agent-quotation"], messageIds: ["message-project-001", "message-project-002", "message-project-003"], status: "ACTIVE", historyPolicy: "NO_PREJOIN_HISTORY" },
};

const seedMessagesById = {
  "message-project-001": { id: "message-project-001", conversationId: "conversation-project", senderType: "HUMAN", senderId: "user-sales", text: "今天先把合同和报价都确认下来。", targetIds: [], mode: null, primaryAgentId: null, linkedTaskId: null, invocationIds: [], createdAt: "2026-08-11T08:18:00+08:00" },
  "message-project-002": { id: "message-project-002", conversationId: "conversation-project", senderType: "HUMAN", senderId: "user-business", text: "请审核这份场馆服务合同，重点看违约和管辖条款。", targetIds: ["message-target-contract"], mode: GROUP_MODE.SINGLE_TARGET, primaryAgentId: "agent-contract", linkedTaskId: "task-contract-001", invocationIds: ["invocation-contract-001"], createdAt: "2026-08-11T08:20:00+08:00" },
  "message-project-003": { id: "message-project-003", conversationId: "conversation-project", senderType: "HUMAN", senderId: "user-sales", text: "按现有需求生成报价，历史工行项目优先参考。", targetIds: ["message-target-quotation"], mode: GROUP_MODE.SINGLE_TARGET, primaryAgentId: "agent-quotation", linkedTaskId: "task-quotation-001", invocationIds: ["invocation-quotation-001"], createdAt: "2026-08-11T08:40:00+08:00" },
};

const seedMessageTargetsById = {
  "message-target-contract": { id: "message-target-contract", messageId: "message-project-002", agentId: "agent-contract", triggerType: MESSAGE_TRIGGER_TYPE.MENTION, replyMessageId: null },
  "message-target-quotation": { id: "message-target-quotation", messageId: "message-project-003", agentId: "agent-quotation", triggerType: MESSAGE_TRIGGER_TYPE.SELECTION, replyMessageId: null },
};

const seedInvocationsById = {
  "invocation-contract-001": { id: "invocation-contract-001", messageId: "message-project-002", messageTargetId: "message-target-contract", agentId: "agent-contract", taskId: "task-contract-001", status: "COMPLETED", estimatedPoints: 35, createdAt: "2026-08-11T08:20:00+08:00" },
  "invocation-quotation-001": { id: "invocation-quotation-001", messageId: "message-project-003", messageTargetId: "message-target-quotation", agentId: "agent-quotation", taskId: "task-quotation-001", status: "COMPLETED", estimatedPoints: 30, createdAt: "2026-08-11T08:40:00+08:00" },
};

const seedPointAccountsById = {
  "point-account-xinghai": { id: "point-account-xinghai", tenantId: "tenant-xinghai", available: 12450, reserved: 540, consumed: 4650, expiringSoon: 1200, displayRate: "1元=100智点" },
};

const seedPointReservationsById = {
  "point-reservation-graphic": { id: "point-reservation-graphic", accountId: "point-account-xinghai", sourceType: "TASK", sourceId: "task-graphic-001", status: POINT_RESERVATION_STATUS.PARTIALLY_CAPTURED, estimated: 600, captured: 320, released: 0 },
  "point-reservation-contract": { id: "point-reservation-contract", accountId: "point-account-xinghai", sourceType: "TASK", sourceId: "task-contract-001", status: POINT_RESERVATION_STATUS.PARTIALLY_CAPTURED, estimated: 300, captured: 180, released: 0 },
  "point-reservation-quotation": { id: "point-reservation-quotation", accountId: "point-account-xinghai", sourceType: "TASK", sourceId: "task-quotation-001", status: POINT_RESERVATION_STATUS.PARTIALLY_CAPTURED, estimated: 350, captured: 210, released: 0 },
};

const seedPointLedgerEntriesById = {
  "ledger-graphic-reserve": { id: "ledger-graphic-reserve", accountId: "point-account-xinghai", reservationId: "point-reservation-graphic", type: "RESERVE", amount: 600, occurredAt: "2026-08-11T09:02:00+08:00" },
  "ledger-graphic-capture": { id: "ledger-graphic-capture", accountId: "point-account-xinghai", reservationId: "point-reservation-graphic", type: "CAPTURE", amount: 320, occurredAt: "2026-08-11T09:26:00+08:00" },
  "ledger-contract-reserve": { id: "ledger-contract-reserve", accountId: "point-account-xinghai", reservationId: "point-reservation-contract", type: "RESERVE", amount: 300, occurredAt: "2026-08-11T08:22:00+08:00" },
  "ledger-contract-capture": { id: "ledger-contract-capture", accountId: "point-account-xinghai", reservationId: "point-reservation-contract", type: "CAPTURE", amount: 180, occurredAt: "2026-08-11T09:14:00+08:00" },
  "ledger-quotation-reserve": { id: "ledger-quotation-reserve", accountId: "point-account-xinghai", reservationId: "point-reservation-quotation", type: "RESERVE", amount: 350, occurredAt: "2026-08-11T08:42:00+08:00" },
  "ledger-quotation-capture": { id: "ledger-quotation-capture", accountId: "point-account-xinghai", reservationId: "point-reservation-quotation", type: "CAPTURE", amount: 210, occurredAt: "2026-08-11T09:08:00+08:00" },
};

export const prototypeInitialState = {
  meta: {
    nextSequence: 1000,
    logicalTime: "2026-08-11T09:30:00+08:00",
    processedCommandIds: [],
  },
  session: {
    currentTenantId: "tenant-xinghai",
    currentUserId: "user-current",
  },
  activeContext: {
    selectedAgentId: "agent-graphic",
  },
  tenantsById: {
    "tenant-xinghai": { id: "tenant-xinghai", name: "星海会展集团", status: "ACTIVE", pointAccountId: "point-account-xinghai" },
  },
  usersById: seedUsersById,
  agentsById: seedAgentsById,
  officesById: {
    "office-xinghai": { id: "office-xinghai", tenantId: "tenant-xinghai", name: "点联企业数字办公大厅", agentIds: ["agent-graphic", "agent-contract", "agent-quotation"], roomConversationIds: ["conversation-project"] },
  },
  conversationsById: seedConversationsById,
  messagesById: seedMessagesById,
  messageTargetsById: seedMessageTargetsById,
  invocationsById: seedInvocationsById,
  tasksById: seedTasksById,
  plansById: seedPlansById,
  stepsById: seedStepsById,
  runsById: seedRunsById,
  runEventsById: seedRunEventsById,
  guidanceById: {},
  artifactsById: seedArtifactsById,
  approvalsById: seedApprovalsById,
  pointAccountsById: seedPointAccountsById,
  pointReservationsById: seedPointReservationsById,
  pointLedgerEntriesById: seedPointLedgerEntriesById,
};

export function createPrototypeInitialState() {
  if (typeof structuredClone === "function") {
    return structuredClone(prototypeInitialState);
  }

  return JSON.parse(JSON.stringify(prototypeInitialState));
}
