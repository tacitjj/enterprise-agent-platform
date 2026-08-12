const AGENT_STATUS_LABELS = Object.freeze({
  WORKING: "工作中",
  WAITING_USER: "等待确认",
  WAITING_APPROVAL: "待审批",
  NEEDS_ATTENTION: "需处理",
  IDLE: "空闲",
});

const TASK_STATUS_PRESENTATION = Object.freeze({
  DRAFT: ["草稿", "neutral"],
  PLANNING: ["规划中", "info"],
  WAITING_USER: ["等待补充", "warning"],
  QUEUED: ["已排队", "info"],
  RUNNING: ["执行中", "info"],
  APPLYING_GUIDANCE: ["应用引导中", "info"],
  REPLANNING: ["重新规划中", "info"],
  WAITING_CONFIRMATION: ["等待确认", "warning"],
  WAITING_APPROVAL: ["等待审批", "warning"],
  PAUSED: ["已暂停", "warning"],
  SUCCEEDED: ["任务已成功", "success"],
  PARTIAL_SUCCESS: ["部分成功", "danger"],
  FAILED: ["任务失败", "danger"],
  CANCELLED: ["已取消", "neutral"],
});

const STEP_STATUS_PRESENTATION = Object.freeze({
  PENDING: ["待开始", "neutral"],
  READY: ["待执行", "info"],
  RUNNING: ["执行中", "info"],
  WAITING_EXTERNAL: ["等待外部", "warning"],
  RETRY_WAIT: ["等待重试", "warning"],
  SUCCEEDED: ["已完成", "success"],
  FAILED_FINAL: ["失败", "danger"],
  SKIPPED: ["已跳过", "neutral"],
  CANCELLED: ["已取消", "neutral"],
  BLOCKED_SIDE_EFFECT_RECONCILIATION: ["等待对账", "danger"],
});

const CAPABILITY_VISUAL = Object.freeze({
  GRAPHIC_DESIGN: {
    tone: "blue",
    shortIcon: "图",
    image: "/assets/employees/graphic-designer.png",
    placeholder: "描述用途、尺寸、文案和希望呈现的风格…",
  },
  CONTRACT_REVIEW: {
    tone: "amber",
    shortIcon: "审",
    image: "/assets/employees/contract-reviewer.png",
    placeholder: "说明我方身份、合同类型与重点关注条款…",
  },
  QUOTATION: {
    tone: "cyan",
    shortIcon: "价",
    image: "/assets/employees/quotation-specialist.png",
    placeholder: "输入客户、项目要求、规格和交付条件…",
  },
});

const ACTIVE_STEP_STATUSES = new Set(["RUNNING", "READY", "WAITING_EXTERNAL", "RETRY_WAIT"]);

const TRACE_TITLES = Object.freeze({
  GOAL_CONFIRMED: "任务目标已确认",
  PLAN_CREATED: "执行计划已创建",
  STEP_STARTED: "步骤已开始",
  STEP_COMPLETED: "步骤已完成",
  EVIDENCE_USED: "已使用授权依据",
  TOOL_RESULT: "工具结果已记录",
  CHECKPOINT_OPENED: "等待人工检查",
  CHECKPOINT_RESOLVED: "人工检查已完成",
  ARTIFACT_CREATED: "成果版本已生成",
  COST_UPDATED: "智点状态已更新",
  CONTROL_APPLIED: "执行控制已应用",
  FAILURE: "执行异常",
});

const ARTIFACT_STATUS_PRESENTATION = Object.freeze({
  DRAFT: ["草稿", "neutral"],
  READY: ["可确认", "success"],
  STALE: ["已失效", "warning"],
});

const APPROVAL_STATUS_PRESENTATION = Object.freeze({
  PENDING: ["待审批", "warning"],
  APPROVED: ["已通过", "success"],
  REJECTED: ["已退回", "danger"],
  WITHDRAWN: ["已撤回", "neutral"],
  INVALIDATED: ["已失效", "warning"],
});

const DELIVERY_STATUS_PRESENTATION = Object.freeze({
  PENDING: ["待交付", "neutral"],
  SENDING: ["交付中", "info"],
  ACCEPTED: ["对方已接收", "info"],
  DELIVERED: ["已确认交付", "success"],
  RETRY_WAIT: ["等待重试", "warning"],
  FAILED: ["交付失败", "danger"],
  CANCELLED: ["已取消", "neutral"],
  UNKNOWN: ["结果待核对", "warning"],
});

const RUN_STATUS_PRESENTATION = Object.freeze({
  QUEUED: "等待运行",
  RUNNING: "运行中",
  WAITING_USER_INPUT: "等待用户补充",
  WAITING_AUTH: "等待授权",
  PAUSED: "已暂停",
  CANCEL_REQUESTED: "请求取消中",
  CANCELLING: "取消中",
  COMPLETED: "已完成",
  FAILED: "运行失败",
  CANCELLED: "已取消",
  CANCEL_OUTCOME_UNKNOWN: "取消结果待核对",
});

export class ApiContractError extends Error {
  constructor(message) {
    super(message);
    this.name = "ApiContractError";
    this.code = "API_CONTRACT_MISMATCH";
  }
}

function requireObject(value, path) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new ApiContractError(`${path} must be an object`);
  }
  return value;
}

function requireArray(value, path) {
  if (!Array.isArray(value)) throw new ApiContractError(`${path} must be an array`);
  return value;
}

function requireText(value, path) {
  const text = String(value ?? "").trim();
  if (!text) throw new ApiContractError(`${path} must not be blank`);
  return text;
}

function optionalText(value) {
  if (value === undefined || value === null) return null;
  const text = String(value).trim();
  return text || null;
}

function pointValue(value, path) {
  const text = String(value ?? "").trim();
  if (!/^(0|[1-9][0-9]*)(\.[0-9]{1,6})?$/.test(text)) {
    throw new ApiContractError(`${path} must be a non-negative point value`);
  }
  return text;
}

function numberValue(value, path) {
  const number = Number(value);
  if (!Number.isInteger(number) || number < 0) {
    throw new ApiContractError(`${path} must be a non-negative integer`);
  }
  return number;
}

function formatTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function visualFor(capabilityCode) {
  return CAPABILITY_VISUAL[capabilityCode] ?? {
    tone: "blue",
    shortIcon: "员",
    image: "/assets/brand/dianlian-symbol.png",
    placeholder: "描述工作目标、输入条件和期望成果…",
  };
}

function statusPresentation(status) {
  return TASK_STATUS_PRESENTATION[status] ?? [status, "neutral"];
}

function pointSummary(dto, path) {
  const summary = requireObject(dto, path);
  return {
    estimatedMax: pointValue(summary.estimatedUpperBound, `${path}.estimatedUpperBound`),
    reserved: pointValue(summary.reserved, `${path}.reserved`),
    captured: pointValue(summary.captured, `${path}.captured`),
    released: pointValue(summary.released, `${path}.released`),
    pendingSettlement: pointValue(summary.pendingSettlement, `${path}.pendingSettlement`),
  };
}

function mapOfficeAgent(dto, index) {
  const value = requireObject(dto, `office.agents[${index}]`);
  const capability = requireText(value.capabilityCode, `office.agents[${index}].capabilityCode`);
  const visual = visualFor(capability);
  const status = requireText(value.officeStatus, `office.agents[${index}].officeStatus`);
  const allowedActions = requireArray(value.allowedActions, `office.agents[${index}].allowedActions`).map(String);
  const skills = requireArray(value.skillLabels, `office.agents[${index}].skillLabels`).map(String);
  return {
    id: requireText(value.agentId, `office.agents[${index}].agentId`),
    name: requireText(value.displayName, `office.agents[${index}].displayName`),
    capability,
    capabilityLabel: requireText(value.roleName, `office.agents[${index}].roleName`),
    profile: requireText(value.profile, `office.agents[${index}].profile`),
    skills,
    skillSummary: skills.slice(0, 2).join(" · ") || "能力由员工版本提供",
    image: optionalText(value.avatarUrl) ?? visual.image,
    status,
    statusLabel: AGENT_STATUS_LABELS[status] ?? status,
    currentTaskTitle: optionalText(value.currentTaskTitle) ?? "当前没有进行中的工作",
    quickPlaceholder: visual.placeholder,
    tone: visual.tone,
    allowedActions,
    canStartTask: allowedActions.includes("START_WORK"),
  };
}

function nextActionForStatus(status) {
  if (["WAITING_USER", "WAITING_CONFIRMATION", "PAUSED"].includes(status)) return "查看待处理事项";
  if (status === "WAITING_APPROVAL") return "查看审批状态";
  if (["FAILED", "PARTIAL_SUCCESS"].includes(status)) return "查看异常";
  if (["SUCCEEDED", "CANCELLED"].includes(status)) return "查看任务记录";
  return "查看真实进展";
}

function mapOfficeTask(dto, index, agentsById) {
  const value = requireObject(dto, `office.tasks[${index}]`);
  const status = requireText(value.status, `office.tasks[${index}].status`);
  const [statusLabel, statusTone] = statusPresentation(status);
  const responsibleAgentIds = requireArray(
    value.responsibleAgentIds,
    `office.tasks[${index}].responsibleAgentIds`,
  ).map(String);
  if (responsibleAgentIds.length === 0) {
    throw new ApiContractError(`office.tasks[${index}].responsibleAgentIds must not be empty`);
  }
  const completedStepCount = numberValue(value.completedStepCount, `office.tasks[${index}].completedStepCount`);
  const totalStepCount = numberValue(value.totalStepCount, `office.tasks[${index}].totalStepCount`);
  const currentStepTitle = optionalText(value.currentStepTitle);
  const currentStepIndex = totalStepCount === 0
    ? 0
    : Math.min(totalStepCount, completedStepCount + (currentStepTitle ? 1 : 0));
  const owner = agentsById.get(responsibleAgentIds[0]);
  const capability = owner?.capability ?? "UNKNOWN";
  const visual = visualFor(capability);
  const points = pointSummary(value.pointSummary, `office.tasks[${index}].pointSummary`);
  return {
    id: requireText(value.taskId, `office.tasks[${index}].taskId`),
    title: requireText(value.title, `office.tasks[${index}].title`),
    status,
    statusLabel,
    statusTone,
    displayStatus: requireText(value.displayStatus, `office.tasks[${index}].displayStatus`),
    agentId: owner?.id ?? responsibleAgentIds[0],
    ownerName: owner?.name ?? "数字员工",
    ownerImage: owner?.image ?? visual.image,
    capability,
    tone: visual.tone,
    shortIcon: visual.shortIcon,
    planVersion: "—",
    stepIndex: currentStepIndex,
    stepCount: totalStepCount,
    currentStep: currentStepTitle ?? (totalStepCount === 0 ? "等待服务端生成计划" : "当前计划无执行中步骤"),
    stepSummary: "来自办公室授权摘要",
    nextAction: nextActionForStatus(status),
    pointCaptured: points.captured,
    pointEstimated: points.estimatedMax,
    pointReserved: points.reserved,
    pointSummary: points,
    allowedActions: requireArray(value.allowedActions, `office.tasks[${index}].allowedActions`).map(String),
    updatedAt: requireText(value.updatedAt, `office.tasks[${index}].updatedAt`),
    updatedAtLabel: formatTime(value.updatedAt),
  };
}

export function mapSessionResponse(dto) {
  const value = requireObject(dto, "session");
  const user = requireObject(value.user, "session.user");
  const tenant = value.activeTenant === null
    ? null
    : requireObject(value.activeTenant, "session.activeTenant");
  return {
    id: requireText(value.sessionId, "session.sessionId"),
    user: {
      id: requireText(user.id, "session.user.id"),
      name: requireText(user.displayName, "session.user.displayName"),
      avatarUrl: optionalText(user.avatarUrl),
      status: requireText(user.accountStatus, "session.user.accountStatus"),
    },
    tenant: tenant
      ? {
        id: requireText(tenant.id, "session.activeTenant.id"),
        name: requireText(tenant.displayName, "session.activeTenant.displayName"),
        status: requireText(tenant.tenantStatus, "session.activeTenant.tenantStatus"),
        membershipStatus: requireText(tenant.membershipStatus, "session.activeTenant.membershipStatus"),
      }
      : null,
    permissions: requireArray(value.permissions, "session.permissions").map(String),
    permissionVersion: requireText(value.permissionVersion, "session.permissionVersion"),
    serverTime: requireText(value.serverTime, "session.serverTime"),
  };
}

export function mapOfficeSnapshotResponse(dto) {
  const value = requireObject(dto, "office");
  const agents = requireArray(value.agents, "office.agents").map(mapOfficeAgent);
  const agentsById = new Map(agents.map((agent) => [agent.id, agent]));
  const tasks = requireArray(value.tasks, "office.tasks")
    .map((task, index) => mapOfficeTask(task, index, agentsById));
  return {
    snapshotVersion: requireText(value.snapshotVersion, "office.snapshotVersion"),
    generatedAt: requireText(value.generatedAt, "office.generatedAt"),
    mappingVersion: requireText(value.mappingVersion, "office.mappingVersion"),
    agents,
    agentsById,
    tasks,
    rooms: requireArray(value.rooms, "office.rooms"),
    artifacts: requireArray(value.artifacts, "office.artifacts"),
    todos: requireArray(value.todos, "office.todos"),
    hasMore: requireObject(value.hasMore, "office.hasMore"),
  };
}

function schemaType(schema) {
  const declared = Array.isArray(schema.type) ? schema.type.find((type) => type !== "null") : schema.type;
  return declared ?? (schema.enum ? typeof schema.enum[0] : "string");
}

function fieldDefault(schema) {
  if (schema.default !== undefined) return schema.default;
  return "";
}

function mapInputField(name, schema, required) {
  requireObject(schema, `employee.inputSchema.jsonSchema.properties.${name}`);
  const type = schemaType(schema);
  const supportedTypes = new Set(["string", "number", "integer", "boolean", "array", "object"]);
  if (!supportedTypes.has(type)) {
    throw new ApiContractError(`Unsupported input field type for ${name}: ${type}`);
  }
  const options = Array.isArray(schema.enum)
    ? schema.enum.map((value) => ({ label: String(value), value }))
    : [];
  return {
    key: name,
    label: optionalText(schema.title) ?? name,
    description: optionalText(schema.description),
    type,
    required,
    defaultValue: fieldDefault(schema),
    options,
    minimum: schema.minimum ?? null,
    maximum: schema.maximum ?? null,
    minLength: schema.minLength ?? null,
    maxLength: schema.maxLength ?? null,
    pattern: optionalText(schema.pattern),
    itemType: schema.items && typeof schema.items === "object" ? schemaType(schema.items) : "string",
  };
}

export function mapEmployeeWorkspaceResponse(dto, officeAgent) {
  const value = requireObject(dto, "employee");
  const inputSchema = requireObject(value.inputSchema, "employee.inputSchema");
  const jsonSchema = requireObject(inputSchema.jsonSchema, "employee.inputSchema.jsonSchema");
  if (schemaType(jsonSchema) !== "object") {
    throw new ApiContractError("employee.inputSchema.jsonSchema must declare an object root");
  }
  const properties = requireObject(jsonSchema.properties ?? {}, "employee.inputSchema.jsonSchema.properties");
  const required = new Set(requireArray(jsonSchema.required ?? [], "employee.inputSchema.jsonSchema.required").map(String));
  for (const requiredName of required) {
    if (!Object.hasOwn(properties, requiredName)) {
      throw new ApiContractError(`Required input field is missing from properties: ${requiredName}`);
    }
  }
  const fields = Object.entries(properties).map(([name, schema]) => mapInputField(name, schema, required.has(name)));
  const executionTemplate = requireObject(value.executionTemplate, "employee.executionTemplate");
  const steps = requireArray(executionTemplate.steps, "employee.executionTemplate.steps").map((rawStep, index) => {
    const step = requireObject(rawStep, `employee.executionTemplate.steps[${index}]`);
    return {
      key: requireText(step.stepKey, `employee.executionTemplate.steps[${index}].stepKey`),
      title: requireText(step.title, `employee.executionTemplate.steps[${index}].title`),
      executorType: requireText(step.executorType, `employee.executionTemplate.steps[${index}].executorType`),
      dependsOn: requireArray(step.dependsOn, `employee.executionTemplate.steps[${index}].dependsOn`).map(String),
      humanCheckpoint: Boolean(step.humanCheckpoint),
    };
  });
  if (steps.length === 0) throw new ApiContractError("employee.executionTemplate.steps must not be empty");
  const capability = requireText(value.capabilityCode, "employee.capabilityCode");
  const visual = visualFor(capability);
  const allowedActions = requireArray(value.allowedActions, "employee.allowedActions").map(String);
  const pointEstimate = pointValue(value.pointEstimate, "employee.pointEstimate");
  if (Number(pointEstimate) <= 0) throw new ApiContractError("employee.pointEstimate must be positive");
  return {
    agentId: requireText(value.agentId, "employee.agentId"),
    agentVersionId: requireText(value.agentVersionId, "employee.agentVersionId"),
    displayName: requireText(value.displayName, "employee.displayName"),
    roleName: requireText(value.roleName, "employee.roleName"),
    capability,
    profile: requireText(value.profile, "employee.profile"),
    skills: requireArray(value.skillLabels, "employee.skillLabels").map(String),
    image: optionalText(value.avatarUrl) ?? officeAgent?.image ?? visual.image,
    inputSchema: {
      schemaId: requireText(inputSchema.schemaId, "employee.inputSchema.schemaId"),
      schemaVersion: requireText(inputSchema.schemaVersion, "employee.inputSchema.schemaVersion"),
      jsonSchema,
      fields,
    },
    executionTemplate: {
      templateCode: requireText(executionTemplate.templateCode, "employee.executionTemplate.templateCode"),
      version: requireText(executionTemplate.version, "employee.executionTemplate.version"),
      steps,
    },
    pointEstimate,
    allowedActions,
    canStartTask: allowedActions.includes("START_WORK"),
  };
}

function isEmptyInput(value) {
  return value === undefined || value === null || (typeof value === "string" && value.trim() === "");
}

function selectEnumValue(rawValue, field) {
  if (field.options.length === 0) return rawValue;
  const match = field.options.find((option) => String(option.value) === String(rawValue));
  if (!match) throw new ApiContractError(`${field.label} 不是允许的选项`);
  return match.value;
}

function coercePrimitive(rawValue, type, field) {
  if (type === "string") {
    const value = String(rawValue);
    if (field.minLength !== null && value.length < Number(field.minLength)) {
      throw new ApiContractError(`${field.label} 至少需要 ${field.minLength} 个字符`);
    }
    if (field.maxLength !== null && value.length > Number(field.maxLength)) {
      throw new ApiContractError(`${field.label} 不能超过 ${field.maxLength} 个字符`);
    }
    if (field.pattern) {
      let pattern;
      try {
        pattern = new RegExp(field.pattern);
      } catch {
        throw new ApiContractError(`${field.label} 的服务端校验规则无效`);
      }
      if (!pattern.test(value)) throw new ApiContractError(`${field.label} 格式不符合要求`);
    }
    return value;
  }
  if (type === "number" || type === "integer") {
    const value = Number(rawValue);
    if (!Number.isFinite(value) || (type === "integer" && !Number.isInteger(value))) {
      throw new ApiContractError(`${field.label} 必须是${type === "integer" ? "整数" : "数字"}`);
    }
    if (field.minimum !== null && value < Number(field.minimum)) {
      throw new ApiContractError(`${field.label} 不能小于 ${field.minimum}`);
    }
    if (field.maximum !== null && value > Number(field.maximum)) {
      throw new ApiContractError(`${field.label} 不能大于 ${field.maximum}`);
    }
    return value;
  }
  if (type === "boolean") {
    if (rawValue === true || rawValue === "true") return true;
    if (rawValue === false || rawValue === "false") return false;
    throw new ApiContractError(`${field.label} 必须选择是或否`);
  }
  return rawValue;
}

function coerceFieldValue(rawValue, field) {
  const selected = selectEnumValue(rawValue, field);
  if (field.type === "array") {
    let values = selected;
    if (!Array.isArray(values)) {
      const text = String(values).trim();
      if (text.startsWith("[")) {
        try {
          values = JSON.parse(text);
        } catch {
          throw new ApiContractError(`${field.label} 必须是 JSON 数组或逗号分隔列表`);
        }
      } else {
        values = text.split(",").map((item) => item.trim()).filter(Boolean);
      }
    }
    if (!Array.isArray(values)) throw new ApiContractError(`${field.label} 必须是数组`);
    return values.map((item) => coercePrimitive(item, field.itemType, field));
  }
  if (field.type === "object") {
    if (selected && typeof selected === "object" && !Array.isArray(selected)) return structuredClone(selected);
    try {
      const parsed = JSON.parse(String(selected));
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("not object");
      return parsed;
    } catch {
      throw new ApiContractError(`${field.label} 必须是 JSON 对象`);
    }
  }
  return coercePrimitive(selected, field.type, field);
}

export function buildCapabilityInputValues(employeeWorkspace, rawValues) {
  const source = requireObject(rawValues, "capabilityInput.values");
  const values = {};
  for (const field of employeeWorkspace.inputSchema.fields) {
    const rawValue = source[field.key];
    if (isEmptyInput(rawValue)) {
      if (field.required) throw new ApiContractError(`请填写${field.label}`);
      continue;
    }
    values[field.key] = coerceFieldValue(rawValue, field);
  }
  return values;
}

function executorName(step, agentsById, session) {
  if (step.responsibleType === "AGENT") return agentsById.get(String(step.responsibleId))?.name ?? "数字员工";
  if (step.responsibleType === "USER" && String(step.responsibleId) === session.user.id) return session.user.name;
  return ({ APPROVER: "审批人", SYSTEM: "点联系统", EXTERNAL: "受控外部工具", USER: "任务成员" })[
    step.responsibleType
  ] ?? "任务负责人";
}

function emptyCapabilityData(capabilityCode) {
  if (capabilityCode === "GRAPHIC_DESIGN") return { variants: [] };
  if (capabilityCode === "CONTRACT_REVIEW") {
    return { contractVersion: null, risks: [], unresolvedHighRiskCount: 0 };
  }
  return {
    items: [],
    totals: null,
    exceptions: [],
    ruleVersion: "等待成果",
    taxModeLabel: "—",
    validUntil: "—",
    stageLabel: "成果尚未生成",
  };
}

function mapTaskBlocker(dto) {
  if (dto === undefined || dto === null) return null;
  const blocker = requireObject(dto, "task.blocker");
  return {
    code: requireText(blocker.code, "task.blocker.code"),
    responsibleParty: requireText(blocker.responsibleParty, "task.blocker.responsibleParty"),
    message: requireText(blocker.message, "task.blocker.message"),
  };
}

function mapArtifactSummary(dto, index) {
  const artifact = requireObject(dto, `task.artifacts[${index}]`);
  const status = requireText(artifact.status, `task.artifacts[${index}].status`);
  const [statusLabel, statusTone] = ARTIFACT_STATUS_PRESENTATION[status] ?? [status, "neutral"];
  const createdAt = requireText(artifact.createdAt, `task.artifacts[${index}].createdAt`);
  return {
    id: requireText(artifact.artifactVersionId, `task.artifacts[${index}].artifactVersionId`),
    artifactVersionId: requireText(artifact.artifactVersionId, `task.artifacts[${index}].artifactVersionId`),
    type: requireText(artifact.artifactType, `task.artifacts[${index}].artifactType`),
    artifactType: requireText(artifact.artifactType, `task.artifacts[${index}].artifactType`),
    title: requireText(artifact.title, `task.artifacts[${index}].title`),
    status,
    statusLabel,
    statusTone,
    contentHash: requireText(artifact.contentHash, `task.artifacts[${index}].contentHash`),
    sourceStepId: requireText(artifact.sourceStepId, `task.artifacts[${index}].sourceStepId`),
    parentVersionId: optionalText(artifact.parentArtifactVersionId),
    createdAt,
    createdAtLabel: formatTime(createdAt),
  };
}

function mapApprovalSummary(dto) {
  if (dto === undefined || dto === null) return null;
  const approval = requireObject(dto, "task.approval");
  const status = requireText(approval.status, "task.approval.status");
  const [statusLabel, statusTone] = APPROVAL_STATUS_PRESENTATION[status] ?? [status, "neutral"];
  const updatedAt = requireText(approval.updatedAt, "task.approval.updatedAt");
  return {
    id: requireText(approval.approvalId, "task.approval.approvalId"),
    artifactVersionId: requireText(approval.artifactVersionId, "task.approval.artifactVersionId"),
    status,
    statusLabel,
    statusTone,
    updatedAt,
    updatedAtLabel: formatTime(updatedAt),
  };
}

function mapDeliverySummary(dto) {
  if (dto === undefined || dto === null) return null;
  const delivery = requireObject(dto, "task.delivery");
  const status = requireText(delivery.status, "task.delivery.status");
  const [statusLabel, statusTone] = DELIVERY_STATUS_PRESENTATION[status] ?? [status, "neutral"];
  const updatedAt = requireText(delivery.updatedAt, "task.delivery.updatedAt");
  return {
    id: requireText(delivery.deliveryId, "task.delivery.deliveryId"),
    artifactVersionId: requireText(delivery.artifactVersionId, "task.delivery.artifactVersionId"),
    status,
    statusLabel,
    statusTone,
    destinationType: requireText(delivery.destinationType, "task.delivery.destinationType"),
    reasonCode: optionalText(delivery.reasonCode),
    updatedAt,
    updatedAtLabel: formatTime(updatedAt),
  };
}

function mapRuntimeRun(dto) {
  if (dto === undefined || dto === null) return null;
  const run = requireObject(dto, "task.activeRun");
  const status = requireText(run.status, "task.activeRun.status");
  const startedAt = requireText(run.startedAt, "task.activeRun.startedAt");
  return {
    id: requireText(run.runtimeRunId, "task.activeRun.runtimeRunId"),
    taskStepId: requireText(run.taskStepId, "task.activeRun.taskStepId"),
    executionGeneration: numberValue(run.executionGeneration, "task.activeRun.executionGeneration"),
    status,
    statusLabel: RUN_STATUS_PRESENTATION[status] ?? status,
    operationKind: requireText(run.operationKind, "task.activeRun.operationKind"),
    checkpointId: optionalText(run.checkpointId),
    startedAt,
    startedAtLabel: formatTime(startedAt),
    terminalAt: optionalText(run.terminalAt),
    terminalAtLabel: run.terminalAt ? formatTime(run.terminalAt) : null,
  };
}

export function mapTaskSnapshotResponse(dto, { office, session }) {
  const value = requireObject(dto, "task");
  const status = requireText(value.status, "task.status");
  const capability = requireText(value.capabilityCode, "task.capabilityCode");
  const [statusLabel, statusTone] = statusPresentation(status);
  const targetAgentIds = requireArray(value.targetAgentIds, "task.targetAgentIds").map(String);
  const visual = visualFor(capability);
  const owner = targetAgentIds.map((id) => office.agentsById.get(id)).find(Boolean) ?? {
    id: targetAgentIds[0] ?? "unknown-agent",
    name: "数字员工",
    image: visual.image,
    capability,
    profile: "员工详情不在当前授权快照中",
  };
  const rawSteps = requireArray(value.steps, "task.steps");
  const steps = rawSteps.map((rawStep, index) => {
    const step = requireObject(rawStep, `task.steps[${index}]`);
    const stepStatus = requireText(step.status, `task.steps[${index}].status`);
    const [stepStatusLabel, stepStatusTone] = STEP_STATUS_PRESENTATION[stepStatus] ?? [stepStatus, "neutral"];
    return {
      id: requireText(step.stepId, `task.steps[${index}].stepId`),
      key: requireText(step.stepKey, `task.steps[${index}].stepKey`),
      title: requireText(step.title, `task.steps[${index}].title`),
      status: stepStatus,
      statusLabel: stepStatusLabel,
      statusTone: stepStatusTone,
      executorName: executorName(step, office.agentsById, session),
      responsibleType: requireText(step.responsibleType, `task.steps[${index}].responsibleType`),
      responsibleId: requireText(step.responsibleId, `task.steps[${index}].responsibleId`),
      dependsOn: requireArray(step.dependsOn, `task.steps[${index}].dependsOn`).map(String),
      outputContract: requireText(step.outputContract, `task.steps[${index}].outputContract`),
      blockerCode: optionalText(step.blockerCode),
    };
  });
  let activeIndex = steps.findIndex((step) => ACTIVE_STEP_STATUSES.has(step.status));
  if (activeIndex < 0) activeIndex = steps.findIndex((step) => !["SUCCEEDED", "SKIPPED", "CANCELLED"].includes(step.status));
  if (activeIndex < 0 && steps.length > 0) activeIndex = steps.length - 1;
  const activeStep = activeIndex >= 0 ? steps[activeIndex] : null;
  const trace = requireArray(value.businessTrace, "task.businessTrace").map((rawTrace, index) => {
    const item = requireObject(rawTrace, `task.businessTrace[${index}]`);
    const type = requireText(item.type, `task.businessTrace[${index}].type`);
    return {
      id: requireText(item.traceItemId, `task.businessTrace[${index}].traceItemId`),
      type,
      title: TRACE_TITLES[type] ?? "业务轨迹已更新",
      summary: requireText(item.summary, `task.businessTrace[${index}].summary`),
      occurredAt: requireText(item.occurredAt, `task.businessTrace[${index}].occurredAt`),
      occurredAtLabel: formatTime(item.occurredAt),
    };
  });
  const points = pointSummary(value.pointSummary, "task.pointSummary");
  const blocker = mapTaskBlocker(value.blocker);
  const activeRun = mapRuntimeRun(value.activeRun);
  const artifacts = requireArray(value.artifacts, "task.artifacts").map(mapArtifactSummary);
  const approval = mapApprovalSummary(value.approval);
  const delivery = mapDeliverySummary(value.delivery);
  const serverActionHints = requireArray(value.allowedActions, "task.allowedActions").map(String);
  const capabilityView = structuredClone(requireObject(value.capabilityView, "task.capabilityView"));
  return {
    id: requireText(value.taskId, "task.taskId"),
    title: requireText(value.title, "task.title"),
    goal: requireText(value.goal, "task.goal"),
    capability,
    agentId: owner.id,
    status,
    statusLabel,
    statusTone,
    blocker,
    planVersion: numberValue(value.planVersion, "task.planVersion"),
    steps,
    activeStepId: activeStep?.id ?? null,
    stepIndex: activeIndex >= 0 ? activeIndex + 1 : 0,
    stepCount: steps.length,
    currentStep: activeStep?.title ?? "当前没有执行中步骤",
    stepSummary: activeStep ? `${activeStep.executorName}负责` : "以任务快照为准",
    pointSummary: points,
    pointCaptured: points.captured,
    pointEstimated: points.estimatedMax,
    pointReserved: points.reserved,
    trace,
    artifacts,
    approval,
    delivery,
    capabilityView,
    capabilityData: emptyCapabilityData(capability),
    graphicCandidates: [],
    selectedArtifactId: null,
    allowedActions: [],
    serverActionHints,
    nextAction: blocker ? "处理阻塞事项" : nextActionForStatus(status),
    nextActionHint: blocker?.message ?? "当前为只读权威快照；刷新可读取最新任务、成果与费用状态",
    activeRun,
    currentRunLabel: activeRun ? `第 ${activeRun.executionGeneration} 次 · ${activeRun.statusLabel}` : "尚未启动",
    currentRunNo: activeRun?.executionGeneration ?? null,
    resumeEventId: requireText(value.resumeEventId, "task.resumeEventId"),
    updatedAt: requireText(value.updatedAt, "task.updatedAt"),
    updatedAtLabel: formatTime(value.updatedAt),
    tone: visual.tone,
    shortIcon: visual.shortIcon,
    ownerName: owner.name,
    ownerImage: owner.image,
    collaborationMode: requireText(value.collaborationMode, "task.collaborationMode"),
  };
}

export function createApiDraftTask(agent) {
  return {
    id: `draft-${agent.id}`,
    title: `${agent.name}的新工作`,
    status: "DRAFT",
    statusLabel: "准备开始",
    planVersion: 1,
    pointSummary: { estimatedMax: "待服务端校验", captured: "0", reserved: "0", released: "0" },
    requirePointLimit: true,
    requireInputDescriptor: true,
    planPreviewMode: "SERVER_AFTER_CREATE",
  };
}

export function buildCreateTaskRequest({ session, agent, request }) {
  if (!session.tenant) throw new ApiContractError("active tenant is required to create a task");
  if (!agent.canStartTask) throw new ApiContractError("selected employee is not executable for the current user");
  const maxPointCost = pointValue(request.maxPointCost, "task.maxPointCost");
  if (Number(maxPointCost) <= 0) throw new ApiContractError("task.maxPointCost must be positive");
  const capabilityInput = requireObject(request.capabilityInput, "task.capabilityInput");
  return {
    sourceConversationId: null,
    sourceMessageId: null,
    expectedMembershipVersion: null,
    goal: requireText(request.goal, "task.goal"),
    constraints: [],
    inputRefs: [],
    collaborationMode: "SINGLE_TARGET",
    targetAgentIds: [agent.id],
    primaryAgentId: null,
    ownership: {
      ownerUserId: session.user.id,
      projectId: null,
      billingScopeType: "TENANT",
      billingScopeId: session.tenant.id,
    },
    maxPointCost,
    capabilityInput: {
      schemaId: requireText(capabilityInput.schemaId, "task.capabilityInput.schemaId"),
      schemaVersion: requireText(capabilityInput.schemaVersion, "task.capabilityInput.schemaVersion"),
      values: structuredClone(requireObject(capabilityInput.values, "task.capabilityInput.values")),
    },
    desiredArtifactType: optionalText(request.desiredArtifactType),
  };
}
