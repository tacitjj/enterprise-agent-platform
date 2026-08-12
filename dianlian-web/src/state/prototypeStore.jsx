import { createContext, useContext, useMemo, useReducer } from "react";
import {
  APPROVAL_STATUS,
  ARTIFACT_STATUS,
  CAPABILITY_KIND,
  CAPABILITY_TASK_TEMPLATES,
  GROUP_MODE,
  MESSAGE_TRIGGER_TYPE,
  POINT_RESERVATION_STATUS,
  PROTOTYPE_ACTION,
  RUN_STATUS,
  STEP_STATUS,
  TASK_BLOCKER,
  TASK_DISPLAY,
  TASK_STATUS,
  createPrototypeInitialState,
} from "../data/prototypeData.js";

const PrototypeStateContext = createContext(null);
const PrototypeDispatchContext = createContext(null);

const TERMINAL_TASK_STATUSES = new Set([
  TASK_STATUS.SUCCEEDED,
  TASK_STATUS.CANCELLED,
]);

const ACTIVE_TASK_STATUSES = new Set([
  TASK_STATUS.PLANNING,
  TASK_STATUS.QUEUED,
  TASK_STATUS.RUNNING,
  TASK_STATUS.APPLYING_GUIDANCE,
  TASK_STATUS.REPLANNING,
]);

const STATUS_PRIORITY = Object.freeze({
  NEEDS_ATTENTION: 5,
  WAITING_APPROVAL: 4,
  WAITING_USER: 3,
  WORKING: 2,
  IDLE: 1,
});

function cloneState(value) {
  if (typeof structuredClone === "function") {
    return structuredClone(value);
  }

  return JSON.parse(JSON.stringify(value));
}

function initializeState(initialState) {
  return initialState ? cloneState(initialState) : createPrototypeInitialState();
}

function createAllocator(state) {
  let nextSequence = state.meta.nextSequence;

  return {
    id(prefix) {
      const id = `${prefix}-${nextSequence}`;
      nextSequence += 1;
      return id;
    },
    nextSequence() {
      return nextSequence;
    },
  };
}

function nextLogicalTime(state) {
  const time = new Date(state.meta.logicalTime);
  time.setSeconds(time.getSeconds() + 30);
  return time.toISOString();
}

function withUpdatedMeta(state, allocator, at) {
  return {
    ...state.meta,
    nextSequence: allocator.nextSequence(),
    logicalTime: at,
  };
}

function getTaskPlan(state, task) {
  return task?.activePlanId ? state.plansById[task.activePlanId] : null;
}

function getOrderedTaskSteps(state, task) {
  const plan = getTaskPlan(state, task);
  return plan ? plan.stepIds.map((stepId) => state.stepsById[stepId]).filter(Boolean) : [];
}

function getTaskArtifacts(state, taskId) {
  return Object.values(state.artifactsById)
    .filter((artifact) => artifact.taskId === taskId)
    .sort((left, right) => left.version - right.version);
}

function getTaskApproval(state, task) {
  if (task?.approvalId) {
    return state.approvalsById[task.approvalId] ?? null;
  }

  return Object.values(state.approvalsById).find((approval) => approval.taskId === task?.id) ?? null;
}

function getTaskReservation(state, task) {
  return task?.pointReservationId
    ? state.pointReservationsById[task.pointReservationId] ?? null
    : null;
}

function getTenantPointAccount(state) {
  const tenant = state.tenantsById[state.session.currentTenantId];
  return tenant?.pointAccountId ? state.pointAccountsById[tenant.pointAccountId] ?? null : null;
}

function getDefaultConversationId(state, agentId) {
  return Object.values(state.conversationsById).find(
    (conversation) => conversation.type === "DIRECT" && conversation.agentIds.includes(agentId),
  )?.id ?? null;
}

function createCapabilityData(capability) {
  if (capability === CAPABILITY_KIND.GRAPHIC_DESIGN) {
    return {
      brief: { purpose: null, copy: null, brandAssetIds: [] },
      outputSpecs: [
        { id: "default-landscape", label: "横版主视觉", width: 1920, height: 1080, unit: "PX", format: "PNG", status: "PENDING" },
      ],
      rightsFlags: [],
    };
  }

  if (capability === CAPABILITY_KIND.CONTRACT_REVIEW) {
    return { contractVersion: null, risks: [] };
  }

  return {
    currency: "CNY",
    taxMode: "INCLUDED",
    validUntil: null,
    ruleVersion: "quotation-rule-2026.08",
    items: [],
    totals: { subtotalMinor: 0, taxMinor: 0, totalMinor: 0 },
    exceptions: [],
  };
}

function resolveExecutorId(stepTemplate, agentId, currentUserId) {
  if (stepTemplate.executorType === "HUMAN") {
    return currentUserId;
  }
  if (stepTemplate.executorType === "RULE_ENGINE") {
    return "quotation-rule-engine";
  }
  if (stepTemplate.executorType === "TOOL") {
    return `${agentId}-tool`;
  }
  return agentId;
}

function buildNewTaskState(state, payload) {
  const agentId = payload.agentId ?? state.activeContext.selectedAgentId;
  const agent = state.agentsById[agentId];
  if (!agent || agent.availability !== "ACTIVE") {
    return state;
  }

  const template = CAPABILITY_TASK_TEMPLATES[agent.capability];
  const allocator = createAllocator(state);
  const at = nextLogicalTime(state);
  const taskId = allocator.id("task");
  const planId = allocator.id("plan");
  const runId = allocator.id("run");
  const eventId = allocator.id("event");
  const reservationId = allocator.id("point-reservation");
  const ledgerEntryId = allocator.id("point-ledger");
  const stepIds = template.steps.map(() => allocator.id("step"));
  const createdArtifacts = {};
  const outputArtifactIdsByStepKey = {};
  if (agent.capability === CAPABILITY_KIND.GRAPHIC_DESIGN) {
    const firstPreviewId = allocator.id("artifact");
    const secondPreviewId = allocator.id("artifact");
    outputArtifactIdsByStepKey.preview = [firstPreviewId, secondPreviewId];
    createdArtifacts[firstPreviewId] = {
      id: firstPreviewId,
      taskId,
      type: "IMAGE",
      title: `${payload.title?.trim() || template.defaultTitle} · 候选 A`,
      version: 1,
      status: ARTIFACT_STATUS.DRAFT,
      previewUrl: null,
      contentHash: `mock:${firstPreviewId}`,
      parentVersionId: null,
      metadata: { isPreview: true },
    };
    createdArtifacts[secondPreviewId] = {
      id: secondPreviewId,
      taskId,
      type: "IMAGE",
      title: `${payload.title?.trim() || template.defaultTitle} · 候选 B`,
      version: 2,
      status: ARTIFACT_STATUS.DRAFT,
      previewUrl: null,
      contentHash: `mock:${secondPreviewId}`,
      parentVersionId: firstPreviewId,
      metadata: { isPreview: true },
    };
  } else {
    const artifactId = allocator.id("artifact");
    const outputStepKey = agent.capability === CAPABILITY_KIND.CONTRACT_REVIEW ? "risk" : "calculation";
    outputArtifactIdsByStepKey[outputStepKey] = [artifactId];
    createdArtifacts[artifactId] = {
      id: artifactId,
      taskId,
      type: agent.capability === CAPABILITY_KIND.CONTRACT_REVIEW ? "CONTRACT_REPORT" : "QUOTATION",
      title: agent.capability === CAPABILITY_KIND.CONTRACT_REVIEW ? "合同风险审核报告" : "项目报价草案",
      version: 1,
      status: ARTIFACT_STATUS.DRAFT,
      previewUrl: null,
      contentHash: `mock:${artifactId}`,
      parentVersionId: null,
      metadata: {},
    };
  }
  const account = getTenantPointAccount(state);
  const hasPoints = Boolean(account && account.available >= template.estimatedPoints);
  const conversationId = payload.conversationId ?? getDefaultConversationId(state, agentId);
  const sourceType = state.conversationsById[conversationId]?.type === "GROUP" ? "GROUP" : "DIRECT";

  const createdSteps = {};
  stepIds.forEach((stepId, index) => {
    const stepTemplate = template.steps[index];
    createdSteps[stepId] = {
      id: stepId,
      taskId,
      key: stepTemplate.key,
      title: stepTemplate.title,
      status: index === 0 ? STEP_STATUS.READY : STEP_STATUS.PENDING,
      executorType: stepTemplate.executorType,
      executorId: resolveExecutorId(stepTemplate, agentId, state.session.currentUserId),
      dependsOn: index === 0 ? [] : [stepIds[index - 1]],
      outputArtifactIds: outputArtifactIdsByStepKey[stepTemplate.key] ?? [],
      actualPoints: stepTemplate.actualPoints,
      capturedPoints: 0,
    };
  });

  const newTask = {
    id: taskId,
    tenantId: state.session.currentTenantId,
    agentId,
    collaboratingAgentIds: payload.collaboratingAgentIds ?? [],
    capability: agent.capability,
    title: payload.title?.trim() || template.defaultTitle,
    source: {
      type: sourceType,
      conversationId,
      sourceMessageId: payload.sourceMessageId ?? null,
    },
    ownerId: state.session.currentUserId,
    participantIds: [state.session.currentUserId],
    approverIds: payload.approverIds ?? [state.session.currentUserId],
    status: hasPoints ? TASK_STATUS.QUEUED : TASK_STATUS.WAITING_USER,
    blocker: hasPoints ? TASK_BLOCKER.NONE : TASK_BLOCKER.QUOTA,
    activePlanId: planId,
    activeStepId: stepIds[0],
    currentRunId: hasPoints ? runId : null,
    selectedArtifactId: null,
    pointReservationId: hasPoints ? reservationId : null,
    createdAt: at,
    updatedAt: at,
    capabilityData: createCapabilityData(agent.capability),
  };

  const baseState = {
    ...state,
    meta: withUpdatedMeta(state, allocator, at),
    tasksById: { ...state.tasksById, [taskId]: newTask },
    plansById: {
      ...state.plansById,
      [planId]: {
        id: planId,
        taskId,
        version: 1,
        previousPlanId: null,
        status: "ACTIVE",
        stepIds,
        createdAt: at,
      },
    },
    stepsById: { ...state.stepsById, ...createdSteps },
    artifactsById: { ...state.artifactsById, ...createdArtifacts },
  };

  if (!hasPoints) {
    return baseState;
  }

  return {
    ...baseState,
    runsById: {
      ...state.runsById,
      [runId]: {
        id: runId,
        taskId,
        stepId: stepIds[0],
        runNo: 1,
        status: RUN_STATUS.QUEUED,
        eventIds: [eventId],
        startedAt: null,
        endedAt: null,
      },
    },
    runEventsById: {
      ...state.runEventsById,
      [eventId]: {
        id: eventId,
        runId,
        type: "PLAN_CREATED",
        title: "任务已创建",
        summary: `已生成 ${template.steps.length} 个受控步骤并预占 ${template.estimatedPoints} 智点。`,
        occurredAt: at,
      },
    },
    pointAccountsById: {
      ...state.pointAccountsById,
      [account.id]: {
        ...account,
        available: account.available - template.estimatedPoints,
        reserved: account.reserved + template.estimatedPoints,
      },
    },
    pointReservationsById: {
      ...state.pointReservationsById,
      [reservationId]: {
        id: reservationId,
        accountId: account.id,
        sourceType: "TASK",
        sourceId: taskId,
        status: POINT_RESERVATION_STATUS.ACTIVE,
        estimated: template.estimatedPoints,
        captured: 0,
        released: 0,
      },
    },
    pointLedgerEntriesById: {
      ...state.pointLedgerEntriesById,
      [ledgerEntryId]: {
        id: ledgerEntryId,
        accountId: account.id,
        reservationId,
        type: "RESERVE",
        amount: template.estimatedPoints,
        occurredAt: at,
      },
    },
  };
}

function appendRunEvent(state, run, allocator, at, event) {
  if (!run) {
    return { runsById: state.runsById, runEventsById: state.runEventsById };
  }

  const eventId = allocator.id("event");
  return {
    runsById: {
      ...state.runsById,
      [run.id]: { ...run, eventIds: [...run.eventIds, eventId] },
    },
    runEventsById: {
      ...state.runEventsById,
      [eventId]: { id: eventId, runId: run.id, occurredAt: at, ...event },
    },
  };
}

function settleStepPoints(state, task, step, allocator, at, completeTask) {
  const reservation = getTaskReservation(state, task);
  if (!reservation) {
    return {
      pointAccountsById: state.pointAccountsById,
      pointReservationsById: state.pointReservationsById,
      pointLedgerEntriesById: state.pointLedgerEntriesById,
      capturedPoints: step.capturedPoints ?? 0,
    };
  }

  const account = state.pointAccountsById[reservation.accountId];
  const uncapturedStepPoints = Math.max(0, step.actualPoints - (step.capturedPoints ?? 0));
  const reservationRemaining = Math.max(0, reservation.estimated - reservation.captured - reservation.released);
  const captureAmount = Math.min(uncapturedStepPoints, reservationRemaining);
  let updatedAccount = {
    ...account,
    reserved: Math.max(0, account.reserved - captureAmount),
    consumed: account.consumed + captureAmount,
  };
  let updatedReservation = {
    ...reservation,
    captured: reservation.captured + captureAmount,
    status: captureAmount > 0
      ? POINT_RESERVATION_STATUS.PARTIALLY_CAPTURED
      : reservation.status,
  };
  let ledgerEntries = { ...state.pointLedgerEntriesById };

  if (captureAmount > 0) {
    const captureEntryId = allocator.id("point-ledger");
    ledgerEntries[captureEntryId] = {
      id: captureEntryId,
      accountId: account.id,
      reservationId: reservation.id,
      type: "CAPTURE",
      amount: captureAmount,
      occurredAt: at,
    };
  }

  if (completeTask) {
    const releaseAmount = Math.max(
      0,
      updatedReservation.estimated - updatedReservation.captured - updatedReservation.released,
    );
    updatedAccount = {
      ...updatedAccount,
      available: updatedAccount.available + releaseAmount,
      reserved: Math.max(0, updatedAccount.reserved - releaseAmount),
    };
    updatedReservation = {
      ...updatedReservation,
      released: updatedReservation.released + releaseAmount,
      status: updatedReservation.captured > 0
        ? POINT_RESERVATION_STATUS.CAPTURED
        : POINT_RESERVATION_STATUS.RELEASED,
    };
    if (releaseAmount > 0) {
      const releaseEntryId = allocator.id("point-ledger");
      ledgerEntries[releaseEntryId] = {
        id: releaseEntryId,
        accountId: account.id,
        reservationId: reservation.id,
        type: "RELEASE",
        amount: releaseAmount,
        occurredAt: at,
      };
    }
  }

  return {
    pointAccountsById: { ...state.pointAccountsById, [account.id]: updatedAccount },
    pointReservationsById: {
      ...state.pointReservationsById,
      [reservation.id]: updatedReservation,
    },
    pointLedgerEntriesById: ledgerEntries,
    capturedPoints: (step.capturedPoints ?? 0) + captureAmount,
  };
}

function advanceTaskStep(state, payload) {
  const task = state.tasksById[payload.taskId];
  if (!task || task.blocker !== TASK_BLOCKER.NONE || task.status === TASK_STATUS.PAUSED) {
    return state;
  }
  if (![TASK_STATUS.QUEUED, TASK_STATUS.RUNNING].includes(task.status)) {
    return state;
  }

  const steps = getOrderedTaskSteps(state, task);
  const currentStepIndex = steps.findIndex((step) => step.id === task.activeStepId);
  const currentStep = steps[currentStepIndex];
  if (!currentStep || ![STEP_STATUS.READY, STEP_STATUS.RUNNING].includes(currentStep.status)) {
    return state;
  }
  if (
    task.capability === CAPABILITY_KIND.GRAPHIC_DESIGN
    && currentStep.key === "spec"
    && !task.selectedArtifactId
  ) {
    return state;
  }

  const allocator = createAllocator(state);
  const at = nextLogicalTime(state);
  const run = task.currentRunId ? state.runsById[task.currentRunId] : null;

  if (currentStep.status === STEP_STATUS.READY) {
    const eventState = appendRunEvent(state, run, allocator, at, {
      type: "STEP_STARTED",
      title: currentStep.title,
      summary: "该业务步骤已开始执行。",
    });
    return {
      ...state,
      meta: withUpdatedMeta(state, allocator, at),
      tasksById: {
        ...state.tasksById,
        [task.id]: {
          ...task,
          status: TASK_STATUS.RUNNING,
          capabilityData: task.capability === CAPABILITY_KIND.GRAPHIC_DESIGN && currentStep.key === "export"
            ? {
              ...task.capabilityData,
              outputSpecs: task.capabilityData.outputSpecs.map((spec) => ({ ...spec, status: "RUNNING" })),
            }
            : task.capabilityData,
          updatedAt: at,
        },
      },
      stepsById: {
        ...state.stepsById,
        [currentStep.id]: { ...currentStep, status: STEP_STATUS.RUNNING },
      },
      runsById: run
        ? {
          ...eventState.runsById,
          [run.id]: {
            ...eventState.runsById[run.id],
            stepId: currentStep.id,
            status: RUN_STATUS.RUNNING,
            startedAt: run.startedAt ?? at,
          },
        }
        : state.runsById,
      runEventsById: eventState.runEventsById,
    };
  }

  const nextStep = steps[currentStepIndex + 1] ?? null;
  const completesTask = !nextStep;
  const pointState = settleStepPoints(state, task, currentStep, allocator, at, completesTask);
  const updatedArtifacts = { ...state.artifactsById };
  let nextCapabilityData = task.capabilityData;
  let generatedOutputArtifactIds = currentStep.outputArtifactIds;
  currentStep.outputArtifactIds.forEach((artifactId) => {
    const artifact = updatedArtifacts[artifactId];
    if (artifact && artifact.status === ARTIFACT_STATUS.DRAFT) {
      updatedArtifacts[artifactId] = { ...artifact, status: ARTIFACT_STATUS.READY };
    }
  });
  if (task.capability === CAPABILITY_KIND.GRAPHIC_DESIGN && currentStep.key === "export") {
    const existingArtifactCount = getTaskArtifacts(state, task.id).length;
    generatedOutputArtifactIds = [];
    const outputSpecs = task.capabilityData.outputSpecs.map((spec, index) => {
      const artifactId = allocator.id("artifact");
      generatedOutputArtifactIds.push(artifactId);
      updatedArtifacts[artifactId] = {
        id: artifactId,
        taskId: task.id,
        type: "IMAGE",
        title: `${task.title} · ${spec.label}`,
        version: existingArtifactCount + index + 1,
        status: ARTIFACT_STATUS.READY,
        previewUrl: null,
        contentHash: `mock:${artifactId}`,
        parentVersionId: task.selectedArtifactId,
        metadata: Object.fromEntries(Object.entries(spec).filter(([key]) => key !== "status")),
      };
      return { ...spec, status: "READY", artifactId };
    });
    nextCapabilityData = { ...task.capabilityData, outputSpecs };
  }

  let nextTaskStatus = TASK_STATUS.SUCCEEDED;
  let nextRunStatus = RUN_STATUS.COMPLETED;
  if (nextStep?.executorType === "HUMAN") {
    nextTaskStatus = TASK_STATUS.WAITING_CONFIRMATION;
    nextRunStatus = RUN_STATUS.WAITING_USER_INPUT;
  } else if (nextStep) {
    nextTaskStatus = TASK_STATUS.RUNNING;
    nextRunStatus = RUN_STATUS.RUNNING;
  }

  const eventState = appendRunEvent(state, run, allocator, at, {
    type: completesTask ? "TASK_COMPLETED" : "STEP_COMPLETED",
    title: `${currentStep.title}已完成`,
    summary: nextStep ? `下一步：${nextStep.title}` : "任务执行步骤已全部完成。",
  });
  const nextStepsById = {
    ...state.stepsById,
      [currentStep.id]: {
        ...currentStep,
        status: STEP_STATUS.SUCCEEDED,
        outputArtifactIds: generatedOutputArtifactIds,
        capturedPoints: pointState.capturedPoints,
    },
  };
  if (nextStep) {
    nextStepsById[nextStep.id] = {
      ...nextStep,
      status: nextStep.executorType === "HUMAN" ? STEP_STATUS.READY : STEP_STATUS.RUNNING,
    };
  }

  return {
    ...state,
    meta: withUpdatedMeta(state, allocator, at),
    tasksById: {
      ...state.tasksById,
      [task.id]: {
        ...task,
        status: nextTaskStatus,
        activeStepId: nextStep?.id ?? currentStep.id,
        capabilityData: nextCapabilityData,
        updatedAt: at,
      },
    },
    stepsById: nextStepsById,
    runsById: run
      ? {
        ...eventState.runsById,
        [run.id]: {
          ...eventState.runsById[run.id],
          stepId: nextStep?.id ?? currentStep.id,
          status: nextRunStatus,
          endedAt: completesTask ? at : null,
        },
      }
      : state.runsById,
    runEventsById: eventState.runEventsById,
    artifactsById: updatedArtifacts,
    pointAccountsById: pointState.pointAccountsById,
    pointReservationsById: pointState.pointReservationsById,
    pointLedgerEntriesById: pointState.pointLedgerEntriesById,
  };
}

function applyTaskGuidance(state, payload) {
  const task = state.tasksById[payload.taskId];
  const currentPlan = getTaskPlan(state, task);
  if (!task || !currentPlan || TERMINAL_TASK_STATUSES.has(task.status) || !payload.text?.trim()) {
    return state;
  }

  const allocator = createAllocator(state);
  const at = nextLogicalTime(state);
  const guidanceId = allocator.id("guidance");
  const planId = allocator.id("plan");
  const nextRunId = allocator.id("run");
  const guidanceEventId = allocator.id("event");
  const impact = payload.impact ?? "LOW";
  const resolvesHumanCheckpoint = task.capability === CAPABILITY_KIND.CONTRACT_REVIEW
    && Boolean(payload.riskDecisions);
  const invalidatesArtifacts = Boolean(payload.invalidateArtifacts || impact === "HIGH");
  const run = task.currentRunId ? state.runsById[task.currentRunId] : null;
  const nextArtifacts = { ...state.artifactsById };
  const nextApprovals = { ...state.approvalsById };

  if (invalidatesArtifacts) {
    Object.values(nextArtifacts).forEach((artifact) => {
      if (artifact.taskId === task.id && artifact.status !== ARTIFACT_STATUS.SECURITY_REJECTED) {
        nextArtifacts[artifact.id] = { ...artifact, status: ARTIFACT_STATUS.STALE };
      }
    });
    Object.values(nextApprovals).forEach((approval) => {
      if (approval.taskId === task.id && approval.status !== APPROVAL_STATUS.INVALIDATED) {
        nextApprovals[approval.id] = {
          ...approval,
          status: APPROVAL_STATUS.INVALIDATED,
          decidedAt: at,
        };
      }
    });
  }

  let capabilityData = task.capabilityData;
  if (task.capability === CAPABILITY_KIND.CONTRACT_REVIEW && payload.riskDecisions) {
    capabilityData = {
      ...task.capabilityData,
      risks: task.capabilityData.risks.map((risk) => ({
        ...risk,
        decision: payload.riskDecisions[risk.id] ?? risk.decision,
      })),
    };
  }

  const nextRunStatus = impact === "HIGH" || resolvesHumanCheckpoint
    ? RUN_STATUS.WAITING_USER_INPUT
    : RUN_STATUS.QUEUED;

  return {
    ...state,
    meta: withUpdatedMeta(state, allocator, at),
    tasksById: {
      ...state.tasksById,
      [task.id]: {
        ...task,
        activePlanId: planId,
        currentRunId: nextRunId,
        approvalId: invalidatesArtifacts ? null : task.approvalId,
        status: impact === "HIGH" || resolvesHumanCheckpoint
          ? TASK_STATUS.WAITING_CONFIRMATION
          : TASK_STATUS.QUEUED,
        selectedArtifactId: invalidatesArtifacts ? null : task.selectedArtifactId,
        capabilityData,
        updatedAt: at,
      },
    },
    plansById: {
      ...state.plansById,
      [currentPlan.id]: { ...currentPlan, status: "SUPERSEDED" },
      [planId]: {
        ...currentPlan,
        id: planId,
        version: currentPlan.version + 1,
        previousPlanId: currentPlan.id,
        status: impact === "HIGH" ? "PENDING_CONFIRMATION" : "ACTIVE",
        createdAt: at,
      },
    },
    guidanceById: {
      ...state.guidanceById,
      [guidanceId]: {
        id: guidanceId,
        taskId: task.id,
        actorId: state.session.currentUserId,
        kind: payload.kind ?? "ADD_CONTEXT",
        text: payload.text.trim(),
        impact,
        invalidatesArtifacts,
        previousPlanId: currentPlan.id,
        nextPlanId: planId,
        createdAt: at,
      },
    },
    runsById: {
      ...state.runsById,
      ...(run
        ? {
          [run.id]: {
            ...run,
            status: RUN_STATUS.CANCELLED,
            endedAt: at,
            supersededByRunId: nextRunId,
          },
        }
        : {}),
      [nextRunId]: {
        id: nextRunId,
        taskId: task.id,
        stepId: task.activeStepId,
        runNo: (run?.runNo ?? 0) + 1,
        status: nextRunStatus,
        previousRunId: run?.id ?? null,
        eventIds: [guidanceEventId],
        startedAt: null,
        endedAt: null,
      },
    },
    runEventsById: {
      ...state.runEventsById,
      [guidanceEventId]: {
        id: guidanceEventId,
        runId: nextRunId,
        type: "GUIDANCE_APPLIED",
        title: "已应用执行中引导",
        summary: invalidatesArtifacts
          ? "本次修改影响既有成果，旧成果和审批已失效。"
          : `已基于 Run ${run?.runNo ?? 0} 建立新的执行版本，既有历史继续保留。`,
        occurredAt: at,
      },
    },
    artifactsById: nextArtifacts,
    approvalsById: nextApprovals,
  };
}

function changePauseState(state, payload, shouldPause) {
  const task = state.tasksById[payload.taskId];
  if (!task) {
    return state;
  }
  if (shouldPause && ![TASK_STATUS.QUEUED, TASK_STATUS.RUNNING].includes(task.status)) {
    return state;
  }
  if (!shouldPause && task.status !== TASK_STATUS.PAUSED) {
    return state;
  }

  const allocator = createAllocator(state);
  const at = nextLogicalTime(state);
  const run = task.currentRunId ? state.runsById[task.currentRunId] : null;
  const eventState = appendRunEvent(state, run, allocator, at, {
    type: shouldPause ? "TASK_PAUSED" : "TASK_RESUMED",
    title: shouldPause ? "任务已暂停" : "任务已恢复",
    summary: shouldPause ? "将在当前安全点停止后续执行。" : "任务将从当前安全步骤继续。",
  });

  return {
    ...state,
    meta: withUpdatedMeta(state, allocator, at),
    tasksById: {
      ...state.tasksById,
      [task.id]: {
        ...task,
        status: shouldPause ? TASK_STATUS.PAUSED : TASK_STATUS.QUEUED,
        updatedAt: at,
      },
    },
    runsById: run
      ? {
        ...eventState.runsById,
        [run.id]: {
          ...eventState.runsById[run.id],
          status: shouldPause ? RUN_STATUS.PAUSED : RUN_STATUS.QUEUED,
        },
      }
      : state.runsById,
    runEventsById: eventState.runEventsById,
  };
}

function selectTaskArtifact(state, payload) {
  const task = state.tasksById[payload.taskId];
  const artifact = state.artifactsById[payload.artifactId];
  if (!task || !artifact || artifact.taskId !== task.id) {
    return state;
  }
  if (![ARTIFACT_STATUS.DRAFT, ARTIFACT_STATUS.READY].includes(artifact.status)) {
    return state;
  }

  const at = nextLogicalTime(state);
  return {
    ...state,
    meta: { ...state.meta, logicalTime: at },
    tasksById: {
      ...state.tasksById,
      [task.id]: { ...task, selectedArtifactId: artifact.id, updatedAt: at },
    },
  };
}

function submitTaskApproval(state, payload) {
  const task = state.tasksById[payload.taskId];
  if (!task || TERMINAL_TASK_STATUSES.has(task.status)) {
    return state;
  }
  if (task.capability === CAPABILITY_KIND.GRAPHIC_DESIGN && !task.selectedArtifactId && !payload.artifactId) {
    return state;
  }
  if (
    task.capability === CAPABILITY_KIND.QUOTATION
    && task.capabilityData.exceptions.some((exception) => !exception.resolved)
  ) {
    return state;
  }

  const artifactId = payload.artifactId
    ?? task.selectedArtifactId
    ?? getTaskArtifacts(state, task.id).findLast?.((artifact) => artifact.status === ARTIFACT_STATUS.READY)?.id
    ?? [...getTaskArtifacts(state, task.id)].reverse().find((artifact) => artifact.status === ARTIFACT_STATUS.READY)?.id;
  const artifact = artifactId ? state.artifactsById[artifactId] : null;
  if (!artifact || artifact.status !== ARTIFACT_STATUS.READY) {
    return state;
  }

  if (task.capability === CAPABILITY_KIND.CONTRACT_REVIEW) {
    const unresolvedHighRisk = task.capabilityData.risks.some(
      (risk) => risk.level === "HIGH" && risk.requiresHuman && risk.decision === "PENDING",
    );
    if (unresolvedHighRisk) {
      return state;
    }
  }

  const existingApproval = getTaskApproval(state, task);
  if (existingApproval?.status === APPROVAL_STATUS.PENDING) {
    return state;
  }

  const allocator = createAllocator(state);
  const at = nextLogicalTime(state);
  const approvalId = allocator.id("approval");
  const run = task.currentRunId ? state.runsById[task.currentRunId] : null;
  const eventState = appendRunEvent(state, run, allocator, at, {
    type: "CHECKPOINT_REQUIRED",
    title: "成果已提交审批",
    summary: `审批仅对成果版本 ${artifact.version} 生效。`,
    artifactId: artifact.id,
  });

  return {
    ...state,
    meta: withUpdatedMeta(state, allocator, at),
    tasksById: {
      ...state.tasksById,
      [task.id]: {
        ...task,
        status: TASK_STATUS.WAITING_APPROVAL,
        approvalId,
        selectedArtifactId: artifact.id,
        updatedAt: at,
      },
    },
    approvalsById: {
      ...state.approvalsById,
      [approvalId]: {
        id: approvalId,
        taskId: task.id,
        artifactVersionId: artifact.id,
        type: task.capability === CAPABILITY_KIND.QUOTATION ? "PRICE" : "BUSINESS",
        status: APPROVAL_STATUS.PENDING,
        requestedBy: state.session.currentUserId,
        approverId: payload.approverId ?? task.approverIds[0] ?? state.session.currentUserId,
        comment: payload.comment ?? null,
        requestedAt: at,
        decidedAt: null,
      },
    },
    runsById: run
      ? {
        ...eventState.runsById,
        [run.id]: { ...eventState.runsById[run.id], status: RUN_STATUS.WAITING_USER_INPUT },
      }
      : state.runsById,
    runEventsById: eventState.runEventsById,
  };
}

function decideTaskApproval(state, payload, approved) {
  const approval = state.approvalsById[payload.approvalId]
    ?? getTaskApproval(state, state.tasksById[payload.taskId]);
  if (!approval || approval.status !== APPROVAL_STATUS.PENDING) {
    return state;
  }

  const actorId = payload.actorId ?? state.session.currentUserId;
  if (approval.approverId !== actorId) {
    return state;
  }

  const task = state.tasksById[approval.taskId];
  const currentStep = state.stepsById[task.activeStepId];
  const allocator = createAllocator(state);
  const at = nextLogicalTime(state);
  const run = task.currentRunId ? state.runsById[task.currentRunId] : null;
  const pointState = approved
    ? settleStepPoints(state, task, currentStep ?? { actualPoints: 0, capturedPoints: 0 }, allocator, at, true)
    : {
      pointAccountsById: state.pointAccountsById,
      pointReservationsById: state.pointReservationsById,
      pointLedgerEntriesById: state.pointLedgerEntriesById,
      capturedPoints: currentStep?.capturedPoints ?? 0,
    };
  const eventState = appendRunEvent(state, run, allocator, at, {
    type: approved ? "APPROVAL_APPROVED" : "APPROVAL_REJECTED",
    title: approved ? "审批已通过" : "审批已驳回",
    summary: approved
      ? "任务完成、成果可用与审批通过分别保留状态；尚未进行外部交付。"
      : payload.comment || "请根据审批意见生成新的成果版本。",
    artifactId: approval.artifactVersionId,
  });

  return {
    ...state,
    meta: withUpdatedMeta(state, allocator, at),
    tasksById: {
      ...state.tasksById,
      [task.id]: {
        ...task,
        status: approved ? TASK_STATUS.SUCCEEDED : TASK_STATUS.WAITING_CONFIRMATION,
        updatedAt: at,
      },
    },
    stepsById: currentStep
      ? {
        ...state.stepsById,
        [currentStep.id]: {
          ...currentStep,
          status: approved ? STEP_STATUS.SUCCEEDED : STEP_STATUS.READY,
          capturedPoints: pointState.capturedPoints,
        },
      }
      : state.stepsById,
    approvalsById: {
      ...state.approvalsById,
      [approval.id]: {
        ...approval,
        status: approved ? APPROVAL_STATUS.APPROVED : APPROVAL_STATUS.REJECTED,
        comment: payload.comment ?? approval.comment,
        decidedAt: at,
      },
    },
    runsById: run
      ? {
        ...eventState.runsById,
        [run.id]: {
          ...eventState.runsById[run.id],
          status: approved ? RUN_STATUS.COMPLETED : RUN_STATUS.WAITING_USER_INPUT,
          endedAt: approved ? at : null,
        },
      }
      : state.runsById,
    runEventsById: eventState.runEventsById,
    pointAccountsById: pointState.pointAccountsById,
    pointReservationsById: pointState.pointReservationsById,
    pointLedgerEntriesById: pointState.pointLedgerEntriesById,
  };
}

function normalizeTargetAgentIds(payload) {
  return [...new Set(payload.targetAgentIds ?? payload.targets ?? [])];
}

export function validateGroupMessageCommand(state, payload) {
  const conversation = state.conversationsById[payload.conversationId];
  const text = payload.text?.trim() ?? "";
  const targetAgentIds = normalizeTargetAgentIds(payload);
  if (!conversation || conversation.type !== "GROUP" || conversation.status !== "ACTIVE") {
    return { ok: false, code: "GROUP_UNAVAILABLE", requiredFields: [] };
  }
  if (!conversation.memberIds.includes(state.session.currentUserId)) {
    return { ok: false, code: "GROUP_MEMBERSHIP_REQUIRED", requiredFields: [] };
  }
  if (!text) {
    return { ok: false, code: "MESSAGE_REQUIRED", requiredFields: ["text"] };
  }
  const invalidAgentId = targetAgentIds.find(
    (agentId) => !conversation.agentIds.includes(agentId) || state.agentsById[agentId]?.availability !== "ACTIVE",
  );
  if (invalidAgentId) {
    return { ok: false, code: "AGENT_NOT_AVAILABLE_IN_GROUP", requiredFields: ["targetAgentIds"] };
  }
  if (targetAgentIds.length > 1 && !payload.mode) {
    return { ok: false, code: "GROUP_MODE_REQUIRED", requiredFields: ["mode"] };
  }
  if (targetAgentIds.length > 1 && payload.mode === GROUP_MODE.SINGLE_TARGET) {
    return { ok: false, code: "MULTI_TARGET_MODE_REQUIRED", requiredFields: ["mode"] };
  }
  if (payload.mode === GROUP_MODE.PRIMARY_SUMMARY && !targetAgentIds.includes(payload.primaryAgentId)) {
    return { ok: false, code: "PRIMARY_AGENT_REQUIRED", requiredFields: ["primaryAgentId"] };
  }

  const estimatedPoints = targetAgentIds.reduce((total, agentId) => {
    const capability = state.agentsById[agentId].capability;
    return total + CAPABILITY_TASK_TEMPLATES[capability].chatPointEstimate;
  }, payload.mode === GROUP_MODE.PRIMARY_SUMMARY ? 20 : 0);
  const account = getTenantPointAccount(state);
  if (targetAgentIds.length > 0 && (!account || account.available < estimatedPoints)) {
    return { ok: false, code: "INSUFFICIENT_POINTS", requiredFields: [] };
  }

  return {
    ok: true,
    code: "OK",
    requiredFields: [],
    targetAgentIds,
    mode: targetAgentIds.length <= 1 ? GROUP_MODE.SINGLE_TARGET : payload.mode,
    primaryAgentId: targetAgentIds.length === 1 ? targetAgentIds[0] : payload.primaryAgentId ?? null,
    estimatedPoints,
  };
}

function sendGroupMessage(state, payload) {
  if (payload.commandId && state.meta.processedCommandIds?.includes(payload.commandId)) {
    return state;
  }
  const validation = validateGroupMessageCommand(state, payload);
  if (!validation.ok) {
    return state;
  }

  const allocator = createAllocator(state);
  const at = nextLogicalTime(state);
  const conversation = state.conversationsById[payload.conversationId];
  const messageId = allocator.id("message");
  const targetIds = [];
  const invocationIds = [];
  const replyMessageIds = [];
  const newTargets = {};
  const newInvocations = {};
  const newReplyMessages = {};
  let linkedTaskId = null;
  let reservationId = null;
  let accountState = state.pointAccountsById;
  let reservationState = state.pointReservationsById;
  let ledgerState = state.pointLedgerEntriesById;

  if (validation.targetAgentIds.length > 0) {
    const account = getTenantPointAccount(state);
    reservationId = allocator.id("point-reservation");
    const ledgerEntryId = allocator.id("point-ledger");
    accountState = {
      ...state.pointAccountsById,
      [account.id]: {
        ...account,
        available: account.available - validation.estimatedPoints,
        reserved: account.reserved + validation.estimatedPoints,
      },
    };
    reservationState = {
      ...state.pointReservationsById,
      [reservationId]: {
        id: reservationId,
        accountId: account.id,
        sourceType: "MESSAGE",
        sourceId: messageId,
        status: POINT_RESERVATION_STATUS.ACTIVE,
        estimated: validation.estimatedPoints,
        captured: 0,
        released: 0,
      },
    };
    ledgerState = {
      ...state.pointLedgerEntriesById,
      [ledgerEntryId]: {
        id: ledgerEntryId,
        accountId: account.id,
        reservationId,
        type: "RESERVE",
        amount: validation.estimatedPoints,
        occurredAt: at,
      },
    };

    validation.targetAgentIds.forEach((agentId) => {
      const targetId = allocator.id("message-target");
      const invocationId = allocator.id("invocation");
      targetIds.push(targetId);
      invocationIds.push(invocationId);
      newTargets[targetId] = {
        id: targetId,
        messageId,
        agentId,
        triggerType: payload.triggerType ?? MESSAGE_TRIGGER_TYPE.SELECTION,
        replyMessageId: payload.replyMessageId ?? null,
      };
      newInvocations[invocationId] = {
        id: invocationId,
        messageId,
        messageTargetId: targetId,
        agentId,
        taskId: null,
        status: "QUEUED",
        estimatedPoints: CAPABILITY_TASK_TEMPLATES[state.agentsById[agentId].capability].chatPointEstimate,
        pointReservationId: reservationId,
        createdAt: at,
      };
    });
  }

  let taskState = state.tasksById;
  let planState = state.plansById;
  let stepState = state.stepsById;
  let runState = state.runsById;
  let eventState = state.runEventsById;

  if (validation.mode === GROUP_MODE.PRIMARY_SUMMARY && validation.targetAgentIds.length > 1) {
    linkedTaskId = allocator.id("task");
    const planId = allocator.id("plan");
    const dispatchStepId = allocator.id("step");
    const summaryStepId = allocator.id("step");
    const confirmationStepId = allocator.id("step");
    const runId = allocator.id("run");
    const runEventId = allocator.id("event");
    const primaryAgent = state.agentsById[validation.primaryAgentId];

    taskState = {
      ...state.tasksById,
      [linkedTaskId]: {
        id: linkedTaskId,
        tenantId: state.session.currentTenantId,
        agentId: primaryAgent.id,
        collaboratingAgentIds: validation.targetAgentIds.filter((agentId) => agentId !== primaryAgent.id),
        capability: primaryAgent.capability,
        title: `群聊协作：${payload.text.trim().slice(0, 28)}`,
        source: { type: "GROUP", conversationId: conversation.id, sourceMessageId: messageId },
        ownerId: state.session.currentUserId,
        participantIds: [...conversation.memberIds],
        approverIds: [state.session.currentUserId],
        status: TASK_STATUS.QUEUED,
        blocker: TASK_BLOCKER.NONE,
        activePlanId: planId,
        activeStepId: dispatchStepId,
        currentRunId: runId,
        selectedArtifactId: null,
        pointReservationId: reservationId,
        createdAt: at,
        updatedAt: at,
        capabilityData: createCapabilityData(primaryAgent.capability),
      },
    };
    planState = {
      ...state.plansById,
      [planId]: { id: planId, taskId: linkedTaskId, version: 1, previousPlanId: null, status: "ACTIVE", stepIds: [dispatchStepId, summaryStepId, confirmationStepId], createdAt: at },
    };
    stepState = {
      ...state.stepsById,
      [dispatchStepId]: { id: dispatchStepId, taskId: linkedTaskId, key: "parallel-work", title: "分发并执行独立子任务", status: STEP_STATUS.READY, executorType: "AGENT", executorId: primaryAgent.id, dependsOn: [], outputArtifactIds: [], actualPoints: 0, capturedPoints: 0 },
      [summaryStepId]: { id: summaryStepId, taskId: linkedTaskId, key: "primary-summary", title: "主责员工统一汇总", status: STEP_STATUS.PENDING, executorType: "AGENT", executorId: primaryAgent.id, dependsOn: [dispatchStepId], outputArtifactIds: [], actualPoints: 0, capturedPoints: 0 },
      [confirmationStepId]: { id: confirmationStepId, taskId: linkedTaskId, key: "user-confirmation", title: "用户确认汇总成果", status: STEP_STATUS.PENDING, executorType: "HUMAN", executorId: state.session.currentUserId, dependsOn: [summaryStepId], outputArtifactIds: [], actualPoints: 0, capturedPoints: 0 },
    };
    runState = {
      ...state.runsById,
      [runId]: { id: runId, taskId: linkedTaskId, stepId: dispatchStepId, runNo: 1, status: RUN_STATUS.QUEUED, eventIds: [runEventId], startedAt: null, endedAt: null },
    };
    eventState = {
      ...state.runEventsById,
      [runEventId]: { id: runEventId, runId, type: "PLAN_CREATED", title: "多员工协作计划已建立", summary: `主责员工：${primaryAgent.name}；协作员工 ${validation.targetAgentIds.length - 1} 位。`, occurredAt: at },
    };
    Object.values(newInvocations).forEach((invocation) => {
      newInvocations[invocation.id] = { ...invocation, taskId: linkedTaskId, status: "RUNNING" };
    });

    const replyMessageId = allocator.id("message");
    replyMessageIds.push(replyMessageId);
    newReplyMessages[replyMessageId] = {
      id: replyMessageId,
      conversationId: conversation.id,
      senderType: "AGENT",
      senderId: primaryAgent.id,
      text: `已建立多员工协作任务，由我负责汇总；${validation.targetAgentIds.length - 1} 位协作员工将按计划分别处理。`,
      targetIds: [],
      mode: null,
      primaryAgentId: null,
      linkedTaskId,
      invocationIds: [],
      createdAt: at,
    };
  } else if (validation.targetAgentIds.length > 0) {
    const responseByCapability = {
      [CAPABILITY_KIND.GRAPHIC_DESIGN]: "已接收视觉工作，我会先核对用途、尺寸和品牌资料，再返回可比较的候选方案。",
      [CAPABILITY_KIND.CONTRACT_REVIEW]: "已接收审核工作，我会定位条款并给出风险等级；高风险结论仍需企业法务确认。",
      [CAPABILITY_KIND.QUOTATION]: "已接收报价工作，我会关联授权历史案例并按冻结规则复算，不会猜测缺失价格。",
    };
    validation.targetAgentIds.forEach((agentId) => {
      const agent = state.agentsById[agentId];
      const replyMessageId = allocator.id("message");
      replyMessageIds.push(replyMessageId);
      newReplyMessages[replyMessageId] = {
        id: replyMessageId,
        conversationId: conversation.id,
        senderType: "AGENT",
        senderId: agentId,
        text: responseByCapability[agent.capability],
        targetIds: [],
        mode: null,
        primaryAgentId: null,
        linkedTaskId: null,
        invocationIds: [],
        createdAt: at,
      };
    });
    Object.values(newInvocations).forEach((invocation) => {
      newInvocations[invocation.id] = { ...invocation, status: "COMPLETED", completedAt: at };
    });

    const account = getTenantPointAccount(state);
    const reservation = reservationState[reservationId];
    if (account && reservation) {
      const captureLedgerId = allocator.id("point-ledger");
      const reservedAccount = accountState[account.id];
      accountState = {
        ...accountState,
        [account.id]: {
          ...reservedAccount,
          reserved: Math.max(0, reservedAccount.reserved - reservation.estimated),
          consumed: reservedAccount.consumed + reservation.estimated,
        },
      };
      reservationState = {
        ...reservationState,
        [reservation.id]: {
          ...reservation,
          status: POINT_RESERVATION_STATUS.CAPTURED,
          captured: reservation.estimated,
        },
      };
      ledgerState = {
        ...ledgerState,
        [captureLedgerId]: {
          id: captureLedgerId,
          accountId: account.id,
          reservationId: reservation.id,
          type: "CAPTURE",
          amount: reservation.estimated,
          occurredAt: at,
        },
      };
    }
  }

  return {
    ...state,
    meta: {
      ...withUpdatedMeta(state, allocator, at),
      processedCommandIds: payload.commandId
        ? [...(state.meta.processedCommandIds ?? []).slice(-99), payload.commandId]
        : state.meta.processedCommandIds ?? [],
    },
    conversationsById: {
      ...state.conversationsById,
      [conversation.id]: { ...conversation, messageIds: [...conversation.messageIds, messageId, ...replyMessageIds] },
    },
    messagesById: {
      ...state.messagesById,
      [messageId]: {
        id: messageId,
        conversationId: conversation.id,
        senderType: "HUMAN",
        senderId: state.session.currentUserId,
        text: payload.text.trim(),
        targetIds,
        mode: validation.targetAgentIds.length === 0 ? null : validation.mode,
        primaryAgentId: validation.primaryAgentId,
        linkedTaskId,
        invocationIds,
        createdAt: at,
      },
      ...newReplyMessages,
    },
    messageTargetsById: { ...state.messageTargetsById, ...newTargets },
    invocationsById: { ...state.invocationsById, ...newInvocations },
    tasksById: taskState,
    plansById: planState,
    stepsById: stepState,
    runsById: runState,
    runEventsById: eventState,
    pointAccountsById: accountState,
    pointReservationsById: reservationState,
    pointLedgerEntriesById: ledgerState,
  };
}

export function prototypeReducer(state, action) {
  switch (action.type) {
    case PROTOTYPE_ACTION.SELECT_AGENT: {
      const agentId = action.payload?.agentId;
      if (!state.agentsById[agentId] || state.agentsById[agentId].availability !== "ACTIVE") {
        return state;
      }
      return {
        ...state,
        activeContext: { ...state.activeContext, selectedAgentId: agentId },
      };
    }
    case PROTOTYPE_ACTION.START_TASK:
      return buildNewTaskState(state, action.payload ?? {});
    case PROTOTYPE_ACTION.ADVANCE_STEP:
      return advanceTaskStep(state, action.payload ?? {});
    case PROTOTYPE_ACTION.GUIDE_TASK:
      return applyTaskGuidance(state, action.payload ?? {});
    case PROTOTYPE_ACTION.PAUSE:
    case PROTOTYPE_ACTION.PAUSE_TASK:
      return changePauseState(state, action.payload ?? {}, true);
    case PROTOTYPE_ACTION.RESUME:
    case PROTOTYPE_ACTION.RESUME_TASK:
      return changePauseState(state, action.payload ?? {}, false);
    case PROTOTYPE_ACTION.SELECT_ARTIFACT:
      return selectTaskArtifact(state, action.payload ?? {});
    case PROTOTYPE_ACTION.SUBMIT:
    case PROTOTYPE_ACTION.SUBMIT_APPROVAL:
      return submitTaskApproval(state, action.payload ?? {});
    case PROTOTYPE_ACTION.APPROVE:
    case PROTOTYPE_ACTION.APPROVE_APPROVAL:
      return decideTaskApproval(state, action.payload ?? {}, true);
    case PROTOTYPE_ACTION.REJECT_APPROVAL:
      return decideTaskApproval(state, action.payload ?? {}, false);
    case PROTOTYPE_ACTION.SEND_GROUP_MESSAGE:
      return sendGroupMessage(state, action.payload ?? {});
    default:
      return state;
  }
}

function deriveTaskDisplay(task) {
  if (task.blocker === TASK_BLOCKER.QUOTA) {
    return { label: "智点不足，等待处理", tone: "danger" };
  }
  if (task.blocker === TASK_BLOCKER.AUTH) {
    return { label: "等待授权恢复", tone: "warning" };
  }
  if (task.blocker === TASK_BLOCKER.SIDE_EFFECT_RECONCILIATION) {
    return { label: "外部结果待确认", tone: "danger" };
  }
  return TASK_DISPLAY[task.status] ?? { label: task.status, tone: "neutral" };
}

function deriveAgentStatus(tasks) {
  const statuses = tasks.map((task) => {
    if (task.blocker !== TASK_BLOCKER.NONE || [TASK_STATUS.FAILED, TASK_STATUS.PARTIAL_SUCCESS].includes(task.status)) {
      return "NEEDS_ATTENTION";
    }
    if (task.status === TASK_STATUS.WAITING_APPROVAL) {
      return "WAITING_APPROVAL";
    }
    if ([TASK_STATUS.WAITING_USER, TASK_STATUS.WAITING_CONFIRMATION, TASK_STATUS.PAUSED].includes(task.status)) {
      return "WAITING_USER";
    }
    if (ACTIVE_TASK_STATUSES.has(task.status)) {
      return "WORKING";
    }
    return "IDLE";
  });
  return statuses.sort((left, right) => STATUS_PRIORITY[right] - STATUS_PRIORITY[left])[0] ?? "IDLE";
}

function deriveCapabilityStage(state, task, steps, artifacts, approval) {
  const currentStep = steps.find((step) => step.id === task.activeStepId);
  if (task.capability === CAPABILITY_KIND.GRAPHIC_DESIGN) {
    const specs = task.capabilityData.outputSpecs;
    if (specs.some((spec) => spec.status === "FAILED")) return "PARTIAL_READY";
    if (specs.length > 0 && specs.every((spec) => spec.status === "READY")) return "READY";
    if (specs.some((spec) => spec.status === "RUNNING")) return "EXPORTING_VARIANTS";
    if (task.selectedArtifactId) return "SPEC_CONFIRMATION";
    if (artifacts.some((artifact) => artifact.status === ARTIFACT_STATUS.READY)) return "PREVIEW_READY";
    if (currentStep?.key === "preview") return "GENERATING_PREVIEW";
    return "BRIEF_INCOMPLETE";
  }
  if (task.capability === CAPABILITY_KIND.CONTRACT_REVIEW) {
    if (artifacts.some((artifact) => artifact.status === ARTIFACT_STATUS.STALE)) return "STALE";
    if (approval?.status === APPROVAL_STATUS.APPROVED || task.status === TASK_STATUS.SUCCEEDED) return "HUMAN_REVIEW_COMPLETED";
    if (task.status === TASK_STATUS.WAITING_CONFIRMATION || currentStep?.key === "human-review") return "HUMAN_REVIEW_REQUIRED";
    if (currentStep?.key === "risk") return "RISK_ANALYZING";
    if (currentStep?.key === "parse") return "PARSING";
    return "FILE_CONFIRMATION";
  }

  const validUntil = task.capabilityData.validUntil;
  if (validUntil && validUntil < state.meta.logicalTime.slice(0, 10)) return "EXPIRED";
  if (approval?.status === APPROVAL_STATUS.APPROVED) return "APPROVED";
  if (approval?.status === APPROVAL_STATUS.PENDING || task.status === TASK_STATUS.WAITING_APPROVAL) return "PRICE_APPROVAL_REQUIRED";
  if (task.capabilityData.exceptions.some((exception) => !exception.resolved)) return "PRICING_EXCEPTION";
  if (artifacts.some((artifact) => artifact.status === ARTIFACT_STATUS.READY)) return "DRAFT_READY";
  if (currentStep?.key === "calculation") return "CALCULATING";
  if (currentStep?.key === "evidence") return "MATCHING_EVIDENCE";
  return "INPUT_INCOMPLETE";
}

export function selectAllowedTaskActions(state, taskId, actorId = state.session.currentUserId) {
  const task = state.tasksById[taskId];
  if (!task) return [];
  const isOwner = task.ownerId === actorId;
  const isParticipant = task.participantIds.includes(actorId);
  const isApprover = task.approverIds.includes(actorId) || getTaskApproval(state, task)?.approverId === actorId;
  const actions = [];

  if (task.status === TASK_STATUS.DRAFT && isOwner) actions.push(PROTOTYPE_ACTION.START_TASK);
  if ([TASK_STATUS.QUEUED, TASK_STATUS.RUNNING].includes(task.status) && (isOwner || isParticipant)) {
    actions.push(PROTOTYPE_ACTION.GUIDE_TASK, PROTOTYPE_ACTION.PAUSE_TASK);
  }
  if (task.status === TASK_STATUS.PAUSED && isOwner) actions.push(PROTOTYPE_ACTION.RESUME_TASK);
  if ([TASK_STATUS.WAITING_USER, TASK_STATUS.WAITING_CONFIRMATION].includes(task.status) && (isOwner || isParticipant)) {
    actions.push(PROTOTYPE_ACTION.GUIDE_TASK);
    const hasReadyArtifact = getTaskArtifacts(state, task.id).some(
      (artifact) => artifact.status === ARTIFACT_STATUS.READY,
    );
    const contractRisksResolved = task.capability !== CAPABILITY_KIND.CONTRACT_REVIEW
      || task.capabilityData.risks.every(
        (risk) => !risk.requiresHuman || risk.decision !== "PENDING",
      );
    const quotationExceptionsResolved = task.capability !== CAPABILITY_KIND.QUOTATION
      || task.capabilityData.exceptions.every((exception) => exception.resolved);
    const graphicSelectionComplete = task.capability !== CAPABILITY_KIND.GRAPHIC_DESIGN
      || Boolean(task.selectedArtifactId);
    if (
      hasReadyArtifact
      && contractRisksResolved
      && quotationExceptionsResolved
      && graphicSelectionComplete
    ) {
      actions.push(PROTOTYPE_ACTION.SUBMIT_APPROVAL);
    }
  }
  if (task.capability === CAPABILITY_KIND.GRAPHIC_DESIGN && getTaskArtifacts(state, task.id).length > 0 && isParticipant) {
    actions.push(PROTOTYPE_ACTION.SELECT_ARTIFACT);
  }
  if (task.status === TASK_STATUS.WAITING_APPROVAL && isApprover) {
    actions.push(PROTOTYPE_ACTION.APPROVE_APPROVAL, PROTOTYPE_ACTION.REJECT_APPROVAL);
  }
  if ([TASK_STATUS.FAILED, TASK_STATUS.PARTIAL_SUCCESS].includes(task.status) && isOwner) {
    actions.push(PROTOTYPE_ACTION.ADVANCE_STEP);
  }

  return [...new Set(actions)];
}

function sanitizeCapabilityDataForActor(state, task, actorId) {
  if (task.capability !== CAPABILITY_KIND.QUOTATION) {
    return task.capabilityData;
  }
  const actor = state.usersById[actorId];
  const canReadCost = actor?.roleCodes.some((role) => ["PRICE_APPROVER", "ENTERPRISE_FINANCE"].includes(role));
  if (canReadCost) return task.capabilityData;

  return {
    ...task.capabilityData,
    items: task.capabilityData.items.map(({ costMinor, ...item }) => item),
    totals: Object.fromEntries(
      Object.entries(task.capabilityData.totals).filter(([key]) => !["costMinor", "marginMinor"].includes(key)),
    ),
  };
}

export function selectTaskViewModel(state, taskId, actorId = state.session.currentUserId) {
  const task = state.tasksById[taskId];
  if (!task) return null;
  const plan = getTaskPlan(state, task);
  const steps = getOrderedTaskSteps(state, task);
  const run = task.currentRunId ? state.runsById[task.currentRunId] ?? null : null;
  const events = run ? run.eventIds.map((eventId) => state.runEventsById[eventId]).filter(Boolean) : [];
  const artifacts = getTaskArtifacts(state, task.id);
  const approval = getTaskApproval(state, task);
  const reservation = getTaskReservation(state, task);
  const display = deriveTaskDisplay(task);
  const activeStep = steps.find((step) => step.id === task.activeStepId) ?? null;
  const responsibleId = task.status === TASK_STATUS.WAITING_APPROVAL
    ? approval?.approverId
    : activeStep?.executorId ?? task.ownerId;

  return {
    id: task.id,
    title: task.title,
    capability: task.capability,
    agent: state.agentsById[task.agentId],
    collaboratingAgents: task.collaboratingAgentIds.map((agentId) => state.agentsById[agentId]).filter(Boolean),
    status: task.status,
    statusLabel: display.label,
    statusTone: display.tone,
    blocker: task.blocker,
    planVersion: plan?.version ?? 0,
    responsible: state.usersById[responsibleId] ?? state.agentsById[responsibleId] ?? { id: responsibleId, name: "系统" },
    source: task.source,
    steps,
    activeStep,
    run,
    events,
    artifacts,
    selectedArtifact: task.selectedArtifactId ? state.artifactsById[task.selectedArtifactId] ?? null : null,
    approval,
    pointSummary: reservation
      ? {
        estimated: reservation.estimated,
        captured: reservation.captured,
        reserved: Math.max(0, reservation.estimated - reservation.captured - reservation.released),
        released: reservation.released,
        status: reservation.status,
      }
      : null,
    capabilityStage: deriveCapabilityStage(state, task, steps, artifacts, approval),
    capabilityData: sanitizeCapabilityDataForActor(state, task, actorId),
    allowedActions: selectAllowedTaskActions(state, task.id, actorId),
    nextActionHint: task.blocker === TASK_BLOCKER.QUOTA
      ? "联系企业管理员补充智点后继续"
      : activeStep?.title ?? "查看成果与后续状态",
  };
}

export function selectAgentViewModel(state, agentId) {
  const agent = state.agentsById[agentId];
  if (!agent) return null;
  const tasks = Object.values(state.tasksById).filter(
    (task) => task.agentId === agent.id || task.collaboratingAgentIds.includes(agent.id),
  );
  const activeTasks = tasks.filter((task) => !TERMINAL_TASK_STATUSES.has(task.status));
  const status = deriveAgentStatus(tasks);
  const primaryTask = [...activeTasks].sort((left, right) => {
    const leftStatus = deriveAgentStatus([left]);
    const rightStatus = deriveAgentStatus([right]);
    return STATUS_PRIORITY[rightStatus] - STATUS_PRIORITY[leftStatus];
  })[0] ?? null;

  return {
    ...agent,
    status,
    activeTaskCount: activeTasks.length,
    primaryTask: primaryTask
      ? { id: primaryTask.id, title: primaryTask.title, ...deriveTaskDisplay(primaryTask) }
      : null,
  };
}

export function selectPointViewModel(state) {
  const account = getTenantPointAccount(state);
  if (!account) return null;
  return {
    ...account,
    totalManaged: account.available + account.reserved + account.consumed,
    utilizationRate: account.available + account.reserved + account.consumed > 0
      ? account.consumed / (account.available + account.reserved + account.consumed)
      : 0,
  };
}

export function selectConversationViewModel(state, conversationId) {
  const conversation = state.conversationsById[conversationId];
  if (!conversation) return null;
  return {
    ...conversation,
    members: conversation.memberIds.map((memberId) => state.usersById[memberId]).filter(Boolean),
    availableAgents: conversation.agentIds.map((agentId) => selectAgentViewModel(state, agentId)).filter(Boolean),
    messages: conversation.messageIds.map((messageId) => {
      const message = state.messagesById[messageId];
      const targets = message.targetIds.map((targetId) => state.messageTargetsById[targetId]).filter(Boolean);
      const invocations = message.invocationIds.map((invocationId) => state.invocationsById[invocationId]).filter(Boolean);
      return {
        ...message,
        sender: state.usersById[message.senderId] ?? state.agentsById[message.senderId],
        targets: targets.map((target) => ({ ...target, agent: state.agentsById[target.agentId] })),
        invocations,
        estimatedPointImpact: invocations.reduce((sum, invocation) => sum + invocation.estimatedPoints, 0)
          + (message.mode === GROUP_MODE.PRIMARY_SUMMARY ? 20 : 0),
      };
    }),
    pendingInvocations: Object.values(state.invocationsById).filter(
      (invocation) => invocation.status === "QUEUED"
        && state.messagesById[invocation.messageId]?.conversationId === conversation.id,
    ),
  };
}

export function selectOfficeViewModel(state) {
  const office = Object.values(state.officesById).find(
    (item) => item.tenantId === state.session.currentTenantId,
  );
  if (!office) return null;
  const agents = office.agentIds.map((agentId) => selectAgentViewModel(state, agentId)).filter(Boolean);
  const visibleTasks = Object.values(state.tasksById).filter((task) =>
    task.ownerId === state.session.currentUserId
      || task.participantIds.includes(state.session.currentUserId)
      || task.approverIds.includes(state.session.currentUserId));

  return {
    id: office.id,
    name: office.name,
    tenant: state.tenantsById[office.tenantId],
    selectedAgent: selectAgentViewModel(state, state.activeContext.selectedAgentId),
    agents,
    rooms: office.roomConversationIds
      .map((conversationId) => selectConversationViewModel(state, conversationId))
      .filter(Boolean),
    tasks: visibleTasks.map((task) => selectTaskViewModel(state, task.id)).filter(Boolean),
    pointAccount: selectPointViewModel(state),
    summary: {
      activeTaskCount: visibleTasks.filter((task) => !TERMINAL_TASK_STATUSES.has(task.status)).length,
      waitingForMeCount: visibleTasks.filter((task) =>
        [TASK_STATUS.WAITING_CONFIRMATION, TASK_STATUS.WAITING_APPROVAL].includes(task.status)).length,
      needsAttentionCount: agents.filter((agent) => agent.status === "NEEDS_ATTENTION").length,
    },
  };
}

export function PrototypeProvider({ children, initialState }) {
  const [state, dispatch] = useReducer(prototypeReducer, initialState, initializeState);
  return (
    <PrototypeStateContext.Provider value={state}>
      <PrototypeDispatchContext.Provider value={dispatch}>
        {children}
      </PrototypeDispatchContext.Provider>
    </PrototypeStateContext.Provider>
  );
}

export function usePrototypeState() {
  const state = useContext(PrototypeStateContext);
  if (!state) {
    throw new Error("usePrototypeState must be used inside PrototypeProvider");
  }
  return state;
}

export function usePrototypeDispatch() {
  const dispatch = useContext(PrototypeDispatchContext);
  if (!dispatch) {
    throw new Error("usePrototypeDispatch must be used inside PrototypeProvider");
  }
  return dispatch;
}

export function usePrototypeStore() {
  const state = usePrototypeState();
  const dispatch = usePrototypeDispatch();
  return useMemo(() => ({ state, dispatch }), [state, dispatch]);
}

export { PROTOTYPE_ACTION };
