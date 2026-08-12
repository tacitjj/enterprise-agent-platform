import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import test from "node:test";
import {
  ApiContractError,
  buildCapabilityInputValues,
  buildCreateTaskRequest,
  mapEmployeeWorkspaceResponse,
  mapOfficeSnapshotResponse,
  mapSessionResponse,
  mapTaskSnapshotResponse,
} from "../src/apiPortal/adapters.js";
import { ApiBoundaryState } from "../src/apiPortal/ApiBoundaryState.js";
import {
  canAccessEnterpriseEmployeeManagement,
  loadPortalBootstrap,
  PLATFORM_TEMPLATE_READ_PERMISSION,
  resolvePortalSessionScope,
} from "../src/apiPortal/portalBootstrap.js";
import { executeStableTaskSubmission, prepareStableTaskSubmission } from "../src/apiPortal/taskSubmission.js";
import {
  buildEnterpriseAgentConfigurationPayload,
  loadEnterpriseManagementData,
  refreshActivatedEnterpriseAgentViews,
} from "../src/apiPortal/enterpriseAgentManagementData.js";
import { prepareStableEmployeeCommand } from "../src/apiPortal/employeeCommandIntent.js";
import {
  buildConversationMessagePayload,
  buildCreateAgentDirectPayload,
  buildCreateGroupPayload,
  findAgentDirectConversation,
  mapConversationSummary,
  prepareStableConversationCommand,
} from "../src/apiPortal/conversationAdapters.js";
import { createSingleFlight } from "../src/apiPortal/singleFlight.js";
import { MODEL_PERMISSIONS } from "../src/apiPortal/modelManagementAdapters.js";

const sessionDto = {
  sessionId: "session-1",
  user: { id: "user-1", displayName: "陈露", avatarUrl: null, accountStatus: "ACTIVE" },
  activeTenant: { id: "tenant-1", displayName: "星海会展集团", tenantStatus: "ACTIVE", membershipStatus: "ACTIVE" },
  permissions: ["TASK_CREATE"],
  permissionVersion: "permission-v1",
  serverTime: "2026-08-11T08:00:00Z",
};

const officeDto = {
  snapshotVersion: "office-v1",
  generatedAt: "2026-08-11T08:00:00Z",
  mappingVersion: "office-mapping-v1",
  agents: [{
    agentId: "agent-quotation",
    displayName: "报价专员",
    roleName: "项目报价",
    capabilityCode: "QUOTATION",
    profile: "基于授权资料整理报价输入",
    skillLabels: ["需求结构化", "报价复核"],
    avatarUrl: null,
    officeStatus: "IDLE",
    currentTaskTitle: null,
    allowedActions: ["VIEW", "START_WORK"],
  }],
  rooms: [],
  tasks: [],
  artifacts: [],
  todos: [],
  hasMore: { agents: false, rooms: false, tasks: false, artifacts: false, todos: false },
};

const employeeDto = {
  agentId: "agent-quotation",
  agentVersionId: "agent-version-3",
  displayName: "报价专员",
  roleName: "项目报价",
  capabilityCode: "QUOTATION",
  profile: "基于授权资料整理报价输入",
  skillLabels: ["需求结构化", "报价复核"],
  avatarUrl: null,
  inputSchema: {
    schemaId: "quotation-input",
    schemaVersion: "3",
    jsonSchema: {
      type: "object",
      additionalProperties: false,
      required: ["customerProject", "areaSquareMeters", "taxMode"],
      properties: {
        customerProject: { type: "string", title: "客户与项目", minLength: 2, maxLength: 100 },
        areaSquareMeters: { type: "number", title: "项目面积", minimum: 1, maximum: 10000 },
        taxMode: { type: "string", title: "税务口径", enum: ["INCLUDED", "EXCLUDED"] },
      },
    },
  },
  executionTemplate: {
    templateCode: "quotation-v1",
    version: "3",
    steps: [
      { stepKey: "structure", title: "结构化需求", executorType: "AGENT", dependsOn: [], inputSchemaRef: "quotation-input:3", outputSchemaRef: "quotation-brief:1", humanCheckpoint: false },
      { stepKey: "confirm", title: "人工确认", executorType: "HUMAN", dependsOn: ["structure"], inputSchemaRef: "quotation-brief:1", outputSchemaRef: "quotation-confirmed:1", humanCheckpoint: true },
    ],
  },
  pointEstimate: "12.5",
  allowedActions: ["VIEW", "START_WORK"],
};

test("enterprise management entry requires a management permission instead of employee visibility", () => {
  assert.equal(canAccessEnterpriseEmployeeManagement(["enterprise.employee.read"]), false);
  assert.equal(canAccessEnterpriseEmployeeManagement(["enterprise.employee.execute"]), false);
  assert.equal(canAccessEnterpriseEmployeeManagement(["enterprise.employee.hire"]), false);
  assert.equal(canAccessEnterpriseEmployeeManagement(["enterprise.employee.configure"]), false);
  assert.equal(canAccessEnterpriseEmployeeManagement(["enterprise.employee.activate"]), false);
  assert.equal(canAccessEnterpriseEmployeeManagement(["enterprise.employee.read", "enterprise.employee.hire"]), true);
  assert.equal(canAccessEnterpriseEmployeeManagement(["enterprise.employee.read", "enterprise.employee.configure"]), true);
  assert.equal(canAccessEnterpriseEmployeeManagement(["enterprise.employee.read", "enterprise.employee.activate"]), true);
});

test("coalesces concurrent portal bootstrap work and allows a later reload", async () => {
  const singleFlight = createSingleFlight();
  let calls = 0;
  let releaseFirst;
  const firstGate = new Promise((resolve) => { releaseFirst = resolve; });

  const first = singleFlight.run(async () => {
    calls += 1;
    await firstGate;
    return "ready";
  });
  const concurrent = singleFlight.run(async () => {
    calls += 1;
    return "duplicate";
  });

  assert.equal(first, concurrent);
  await Promise.resolve();
  assert.equal(calls, 1);
  releaseFirst();
  assert.equal(await concurrent, "ready");

  assert.equal(await singleFlight.run(async () => {
    calls += 1;
    return "reloaded";
  }), "reloaded");
  assert.equal(calls, 2);
});

test("platform-only session enters the platform scope without requesting an enterprise office", async () => {
  let officeCalls = 0;
  const platformSessionDto = {
    ...sessionDto,
    activeTenant: null,
    permissions: [PLATFORM_TEMPLATE_READ_PERMISSION],
  };
  const dataSource = {
    getSession: async () => platformSessionDto,
    getOfficeSnapshot: async () => {
      officeCalls += 1;
      throw new Error("platform-only sessions must not request an office");
    },
  };

  const result = await loadPortalBootstrap(dataSource);

  assert.equal(resolvePortalSessionScope(result.session), "platform");
  assert.equal(result.phase, "ready");
  assert.equal(result.session.tenant, null);
  assert.equal(result.office, null);
  assert.equal(officeCalls, 0);
  assert.equal(resolvePortalSessionScope({ ...result.session, permissions: [MODEL_PERMISSIONS.READ] }), "platform");
  assert.equal(resolvePortalSessionScope({ ...result.session, permissions: ["platform.employee.template.publish"] }), "no-tenant");
});

test("tenant session keeps the enterprise bootstrap and requests its office snapshot", async () => {
  let officeCalls = 0;
  const result = await loadPortalBootstrap({
    getSession: async () => sessionDto,
    getOfficeSnapshot: async () => {
      officeCalls += 1;
      return { snapshot: officeDto, etag: '"office-v1"', notModified: false };
    },
  });

  assert.equal(resolvePortalSessionScope(result.session), "tenant");
  assert.equal(result.phase, "ready");
  assert.equal(result.session.tenant.id, "tenant-1");
  assert.equal(result.office.agents.length, 1);
  assert.equal(officeCalls, 1);
  assert.equal(resolvePortalSessionScope({ ...result.session, permissions: [PLATFORM_TEMPLATE_READ_PERMISSION] }), "tenant");
});

test("maps employee schema and builds a typed task request without client tenant facts", () => {
  const session = mapSessionResponse(sessionDto);
  const office = mapOfficeSnapshotResponse(officeDto);
  const workspace = mapEmployeeWorkspaceResponse(employeeDto, office.agents[0]);
  const values = buildCapabilityInputValues(workspace, {
    customerProject: "工商银行展台",
    areaSquareMeters: "180",
    taxMode: "INCLUDED",
  });
  const agent = { ...office.agents[0], canStartTask: workspace.canStartTask };
  const request = buildCreateTaskRequest({
    session,
    agent,
    request: {
      goal: "形成可确认的项目报价",
      maxPointCost: workspace.pointEstimate,
      capabilityInput: {
        schemaId: workspace.inputSchema.schemaId,
        schemaVersion: workspace.inputSchema.schemaVersion,
        values,
      },
      desiredArtifactType: null,
    },
  });

  assert.deepEqual(values, { customerProject: "工商银行展台", areaSquareMeters: 180, taxMode: "INCLUDED" });
  assert.equal(workspace.executionTemplate.steps[1].humanCheckpoint, true);
  assert.equal(workspace.pointEstimate, "12.5");
  assert.equal(request.ownership.ownerUserId, "user-1");
  assert.equal(request.ownership.billingScopeId, "tenant-1");
  assert.equal(request.maxPointCost, "12.5");
  assert.equal(request.capabilityInput.schemaVersion, "3");
  assert.equal(Object.hasOwn(request, "tenantId"), false);

  assert.throws(
    () => buildCapabilityInputValues(workspace, { customerProject: "A", areaSquareMeters: "0", taxMode: "OTHER" }),
    ApiContractError,
  );
});

test("maps the real planning snapshot without inventing a run, result, or command action", () => {
  const session = mapSessionResponse(sessionDto);
  const office = mapOfficeSnapshotResponse(officeDto);
  const task = mapTaskSnapshotResponse({
    taskId: "task-1",
    taskVersion: 1,
    title: "工商银行展台报价",
    goal: "形成可确认的项目报价",
    status: "PLANNING",
    blocker: null,
    planVersion: 1,
    collaborationMode: "SINGLE_TARGET",
    capabilityCode: "QUOTATION",
    capabilityView: { latestArtifactContent: "已生成报价阶段摘要", latestArtifactUsageEstimated: true },
    targetAgentIds: ["agent-quotation"],
    primaryAgentId: null,
    steps: [{
      stepId: "step-1",
      stepKey: "structure",
      title: "结构化需求",
      status: "PENDING",
      responsibleType: "AGENT",
      responsibleId: "agent-quotation",
      dependsOn: [],
      outputContract: "quotation-brief:1",
      blockerCode: null,
    }],
    activeRun: null,
    artifacts: [],
    approval: null,
    delivery: null,
    pointSummary: { estimatedUpperBound: "12.5", reserved: "12.5", captured: "0", released: "0", pendingSettlement: "0" },
    businessTrace: [{ traceItemId: "trace-1", type: "PLAN_CREATED", occurredAt: "2026-08-11T08:01:00Z", responsibleType: "SYSTEM", responsibleId: null, summary: "执行计划已持久化", referenceIds: [] }],
    allowedActions: ["VIEW"],
    resumeEventId: "event-1",
    updatedAt: "2026-08-11T08:01:00Z",
  }, { office, session });

  assert.equal(task.statusLabel, "规划中");
  assert.equal(task.steps[0].title, "结构化需求");
  assert.equal(task.pointSummary.reserved, "12.5");
  assert.equal(task.currentRunLabel, "尚未启动");
  assert.deepEqual(task.graphicCandidates, []);
  assert.deepEqual(task.allowedActions, []);
  assert.deepEqual(task.serverActionHints, ["VIEW"]);
  assert.equal(task.capabilityView.latestArtifactContent, "已生成报价阶段摘要");
  assert.equal(task.capabilityView.latestArtifactUsageEstimated, true);
});

test("maps task run, artifact, approval, and delivery facts without inventing capability content", () => {
  const session = mapSessionResponse(sessionDto);
  const office = mapOfficeSnapshotResponse(officeDto);
  const task = mapTaskSnapshotResponse({
    taskId: "task-2",
    taskVersion: 4,
    title: "工商银行展台报价复核",
    goal: "形成可审批的项目报价",
    status: "WAITING_APPROVAL",
    blocker: { code: "APPROVAL_REQUIRED", responsibleParty: "APPROVER", message: "等待企业审批人确认" },
    planVersion: 2,
    collaborationMode: "SINGLE_TARGET",
    capabilityCode: "QUOTATION",
    capabilityView: {},
    targetAgentIds: ["agent-quotation"],
    primaryAgentId: null,
    steps: [{
      stepId: "step-2",
      stepKey: "pricing",
      title: "确定性计价复算",
      status: "SUCCEEDED",
      responsibleType: "AGENT",
      responsibleId: "agent-quotation",
      dependsOn: [],
      outputContract: "quotation-result:1",
      blockerCode: null,
    }],
    activeRun: {
      runtimeRunId: "run-2",
      taskStepId: "step-2",
      executionGeneration: 2,
      status: "COMPLETED",
      operationKind: "CONTINUE",
      checkpointId: null,
      startedAt: "2026-08-11T08:10:00Z",
      terminalAt: "2026-08-11T08:12:00Z",
    },
    artifacts: [{
      artifactVersionId: "artifact-v2",
      artifactType: "QUOTATION",
      title: "报价草案 v2",
      status: "READY",
      contentHash: "sha256:1234567890abcdef",
      sourceStepId: "step-2",
      parentArtifactVersionId: "artifact-v1",
      createdAt: "2026-08-11T08:12:00Z",
    }],
    approval: {
      approvalId: "approval-1",
      artifactVersionId: "artifact-v2",
      status: "PENDING",
      updatedAt: "2026-08-11T08:13:00Z",
    },
    delivery: {
      deliveryId: "delivery-1",
      artifactVersionId: "artifact-v2",
      status: "PENDING",
      destinationType: "WECHAT_DRAFT",
      reasonCode: null,
      updatedAt: "2026-08-11T08:13:00Z",
    },
    pointSummary: { estimatedUpperBound: "20", reserved: "5", captured: "15", released: "0", pendingSettlement: "0" },
    businessTrace: [],
    allowedActions: ["VIEW", "CANCEL"],
    resumeEventId: "event-9",
    updatedAt: "2026-08-11T08:13:00Z",
  }, { office, session });

  assert.equal(task.activeRun.statusLabel, "已完成");
  assert.equal(task.artifacts[0].statusLabel, "可确认");
  assert.equal(task.approval.statusLabel, "待审批");
  assert.equal(task.delivery.destinationType, "WECHAT_DRAFT");
  assert.equal(task.blocker.responsibleParty, "APPROVER");
  assert.deepEqual(task.allowedActions, []);
  assert.deepEqual(task.serverActionHints, ["VIEW", "CANCEL"]);
  assert.deepEqual(task.capabilityData.items, []);
});

test("automatic retry executes the same prepared idempotent command", async () => {
  let prepared = 0;
  const seenKeys = [];
  const dataSource = {
    prepareCreateTask() {
      prepared += 1;
      const command = {
        idempotencyKey: "task-fixed-idempotency-key",
        async execute() {
          seenKeys.push(command.idempotencyKey);
          if (seenKeys.length === 1) throw Object.assign(new Error("temporary network error"), { code: "NETWORK_ERROR" });
          return { taskId: "task-1" };
        },
      };
      return command;
    },
  };
  const payload = { goal: "形成报价" };
  const first = prepareStableTaskSubmission(dataSource, payload);
  const reused = prepareStableTaskSubmission(dataSource, payload, { previous: first });
  const result = await executeStableTaskSubmission(reused, { maxAttempts: 2 });

  assert.equal(first, reused);
  assert.equal(prepared, 1);
  assert.deepEqual(seenKeys, ["task-fixed-idempotency-key", "task-fixed-idempotency-key"]);
  assert.equal(result.taskId, "task-1");
});

test("employee command intent reuses a key only while the payload and state precondition stay unchanged", () => {
  const ids = ["command-1", "command-2", "command-3"];
  const randomUUID = () => ids.shift();
  const first = prepareStableEmployeeCommand(null, {
    prefix: "hire",
    payload: { agentVersionId: "version-1", displayName: "报价专员" },
    randomUUID,
  });
  const retry = prepareStableEmployeeCommand(first, {
    prefix: "hire",
    payload: { agentVersionId: "version-1", displayName: "报价专员" },
    randomUUID,
  });
  const edited = prepareStableEmployeeCommand(retry, {
    prefix: "hire",
    payload: { agentVersionId: "version-1", displayName: "高级报价专员" },
    randomUUID,
  });
  const newState = prepareStableEmployeeCommand(edited, {
    prefix: "hire",
    payload: { agentVersionId: "version-1", displayName: "高级报价专员", ifMatch: '"state-2"' },
    randomUUID,
  });

  assert.equal(first, retry);
  assert.equal(first.key, "hire:command-1");
  assert.equal(edited.key, "hire:command-2");
  assert.equal(newState.key, "hire:command-3");
});

test("read-only employee management lists instances without requesting the hire-protected catalog", async () => {
  let catalogCalls = 0;
  const result = await loadEnterpriseManagementData({
    listEnterpriseAgents: async () => ({ items: [{ enterpriseAgentId: "agent-1" }] }),
    listRecruitableVersions: async () => {
      catalogCalls += 1;
      throw new Error("read-only sessions must not request the recruitment catalog");
    },
  }, { canHire: false });

  assert.equal(catalogCalls, 0);
  assert.deepEqual(result.templates, []);
  assert.deepEqual(result.agents, [{ enterpriseAgentId: "agent-1" }]);
});

test("employee configuration keeps the V1 policy scopes explicit and trims editable values", () => {
  assert.deepEqual(buildEnterpriseAgentConfigurationPayload({
    displayName: "  报价专员  ",
    profile: "  负责形成可复核报价  ",
    enterpriseInstructions: "  金额保留两位小数  ",
  }), {
    displayNameSnapshot: "报价专员",
    profile: "负责形成可复核报价",
    enterpriseInstructions: "金额保留两位小数",
    modelPolicyMode: "PLATFORM_DEFAULT",
    knowledgeScopeMode: "NONE",
    visibilityScope: "TENANT",
  });
});

test("office refresh failure is downgraded after activation and does not skip the employee list refresh", async () => {
  const calls = [];
  const warnings = await refreshActivatedEnterpriseAgentViews({
    refreshAgents: async () => {
      calls.push("agents");
      return true;
    },
    refreshOffice: async () => {
      calls.push("office");
      throw new Error("office temporarily unavailable");
    },
  });

  assert.deepEqual(calls, ["agents", "office"]);
  assert.deepEqual(warnings, ["办公室刷新失败"]);
});

test("renders explicit API boundary states and states that errors do not use demo data", () => {
  const forbidden = renderToStaticMarkup(ApiBoundaryState({ kind: "forbidden" }));
  const error = renderToStaticMarkup(ApiBoundaryState({ kind: "error" }));
  assert.match(forbidden, /无权进入当前企业/);
  assert.match(error, /不会回退到演示数据/);
});

test("conversation adapters distinguish human direct, agent direct, and group summaries", () => {
  const base = {
    status: "ACTIVE",
    membershipVersion: 2,
    humanMembers: [{ userId: "user-1", displayName: "陈露", avatarUrl: null, role: "OWNER" }],
    lastMessagePreview: null,
    lastMessageAt: null,
    unreadCount: 0,
    allowedActions: ["VIEW", "SEND"],
  };
  const agentDirect = mapConversationSummary({
    ...base,
    conversationId: "conversation-agent",
    type: "DIRECT",
    title: "报价专员",
    agents: [{ enterpriseAgentId: "agent-1", displayName: "报价专员", roleName: "项目报价", avatarUrl: null }],
  }, { currentUserId: "user-1", officeAgents: [{ id: "agent-1", image: "/agent.png" }] });
  const humanDirect = mapConversationSummary({
    ...base,
    conversationId: "conversation-human",
    type: "DIRECT",
    title: "陈露与林娜",
    humanMembers: [...base.humanMembers, { userId: "user-2", displayName: "林娜", avatarUrl: null, role: "MEMBER" }],
    agents: [],
  }, { currentUserId: "user-1" });
  const group = mapConversationSummary({
    ...base,
    conversationId: "conversation-group",
    type: "GROUP",
    title: "项目协作群",
    agents: [],
  }, { currentUserId: "user-1" });

  assert.equal(agentDirect.kind, "DIRECT_AGENT");
  assert.equal(agentDirect.agents[0].avatarUrl, "/agent.png");
  assert.equal(humanDirect.kind, "DIRECT_HUMAN");
  assert.equal(humanDirect.otherHumans[0].name, "林娜");
  assert.equal(group.kind, "GROUP");
});

test("employee message entry reuses an existing agent direct or builds a minimal real direct payload", () => {
  const conversations = [
    { id: "human-direct", kind: "DIRECT_HUMAN", agents: [] },
    { id: "agent-direct", kind: "DIRECT_AGENT", agents: [{ id: "agent-quotation" }] },
  ];

  assert.equal(findAgentDirectConversation(conversations, "agent-quotation")?.id, "agent-direct");
  assert.equal(findAgentDirectConversation(conversations, "agent-legal"), null);
  assert.deepEqual(buildCreateAgentDirectPayload({
    enterpriseAgentId: "agent-quotation",
    title: "点点报价师",
  }), {
    type: "DIRECT",
    title: "点点报价师",
    participantUserIds: [],
    enterpriseAgentIds: ["agent-quotation"],
  });
});

test("ordinary group messages keep targets empty while selection, mention, and reply stay structured", () => {
  const ordinary = buildConversationMessagePayload({
    clientMessageId: "web-message-1",
    text: "大家下午三点开会",
    targets: [],
    membershipVersion: 4,
  });
  const structured = buildConversationMessagePayload({
    clientMessageId: "web-message-2",
    text: "请分别给出意见",
    targets: [
      { enterpriseAgentId: "agent-1", triggerType: "SELECTION" },
      { enterpriseAgentId: "agent-2", triggerType: "MENTION" },
    ],
    membershipVersion: 4,
  });
  const reply = buildConversationMessagePayload({
    clientMessageId: "web-message-3",
    text: "继续核对这一点",
    targets: [{ enterpriseAgentId: "agent-1", triggerType: "REPLY", replyToMessageId: "message-9" }],
    membershipVersion: 4,
    replyToMessageId: "message-9",
  });

  assert.deepEqual(ordinary.targets, []);
  assert.equal(ordinary.collaborationMode, "SINGLE_TARGET");
  assert.deepEqual(structured.targets.map((target) => target.triggerType), ["SELECTION", "MENTION"]);
  assert.equal(structured.collaborationMode, "PARALLEL_SEPARATE");
  assert.equal(reply.targets[0].replyToMessageId, "message-9");
  assert.equal(reply.replyToMessageId, "message-9");
});

test("group creation stays on stable member ids and never submits display-only member facts", () => {
  assert.deepEqual(buildCreateGroupPayload({
    title: " 项目协作群 ",
    participantUserIds: ["user-2", "user-2"],
    enterpriseAgentIds: ["agent-1", "agent-1"],
  }), {
    type: "GROUP",
    title: "项目协作群",
    participantUserIds: ["user-2"],
    enterpriseAgentIds: ["agent-1"],
  });
});

test("conversation command intent reuses both idempotency and client message ids for the same intent", () => {
  const ids = ["command-1", "command-2"];
  const randomUUID = () => ids.shift();
  const first = prepareStableConversationCommand(null, {
    prefix: "conversation-message",
    payload: { text: "你好", targets: [] },
    randomUUID,
  });
  const retry = prepareStableConversationCommand(first, {
    prefix: "conversation-message",
    payload: { text: "你好", targets: [] },
    randomUUID,
  });
  const edited = prepareStableConversationCommand(retry, {
    prefix: "conversation-message",
    payload: { text: "你好，报价专员", targets: [] },
    randomUUID,
  });

  assert.equal(first, retry);
  assert.equal(first.idempotencyKey, "conversation-message:command-1");
  assert.equal(first.clientMessageId, "web:command-1");
  assert.equal(edited.idempotencyKey, "conversation-message:command-2");
});

test("conversation AI refresh is queued-only, visibility-bound, abortable, and bounded", () => {
  const source = readFileSync(new URL("../src/apiPortal/ConversationPage.jsx", import.meta.url), "utf8");

  assert.match(source, /const AI_POLL_INTERVAL_MS = 3_000;/);
  assert.match(source, /const AI_POLL_MAX_ATTEMPTS = 40;/);
  assert.match(source, /queuedInvocationIds\.length > 0/);
  assert.match(source, /document\.visibilityState !== "visible"/);
  assert.match(source, /document\.addEventListener\("visibilitychange"/);
  assert.match(source, /requestController\?\.abort\(\)/);
  assert.match(source, /afterSequenceNo: Math\.max\(0, aiWait\.sourceSequenceNo - 1\)/);
  assert.doesNotMatch(source, /window\.setInterval\(/);
});
