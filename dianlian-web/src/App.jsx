import { lazy, Suspense, useMemo } from "react";
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";
import { PortalShell } from "./layouts/PortalShell.jsx";
import { OfficePage } from "./pages/OfficePage.jsx";
import { WorkspacePage } from "./pages/WorkspacePage.jsx";
import { TaskDetailPage } from "./pages/TaskDetailPage.jsx";
import { GroupRoomPage } from "./pages/GroupRoomPage.jsx";
import {
  ArtifactsPage,
  EmployeesPage,
  KnowledgePage,
  PointsPage,
  TasksPage,
} from "./pages/DirectoryPages.jsx";
import {
  PROTOTYPE_ACTION,
  selectAgentViewModel,
  selectConversationViewModel,
  selectOfficeViewModel,
  selectPointViewModel,
  selectTaskViewModel,
  usePrototypeDispatch,
  usePrototypeState,
} from "./state/prototypeStore.jsx";

const EnterpriseOverview = lazy(() => import("./pages/EnterpriseOverview.jsx").then((module) => ({ default: module.EnterpriseOverview })));
const EnterpriseModules = lazy(() => import("./pages/EnterpriseModules.jsx").then((module) => ({ default: module.EnterpriseModules })));
const PlatformOverview = lazy(() => import("./pages/PlatformOverview.jsx").then((module) => ({ default: module.PlatformOverview })));

const enterpriseModuleKeys = new Set([
  "agents",
  "knowledge",
  "memory",
  "tools",
  "models",
  "org",
  "groups",
  "approvals",
  "points",
  "tasks",
  "audit",
]);

const platformModuleKeys = new Set([
  "tenants",
  "agent-templates",
  "skills",
  "industry-knowledge",
  "providers",
  "models",
  "rates",
  "multipliers",
  "points",
  "usage",
  "monitoring",
  "audit",
]);

const agentStatusLabels = {
  WORKING: "工作中",
  WAITING_USER: "等待确认",
  WAITING_APPROVAL: "待审批",
  NEEDS_ATTENTION: "需处理",
  IDLE: "空闲",
};

const stepStatusLabels = {
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
};

const toneByCapability = {
  GRAPHIC_DESIGN: "blue",
  CONTRACT_REVIEW: "amber",
  QUOTATION: "cyan",
};

const shortIconByCapability = {
  GRAPHIC_DESIGN: "图",
  CONTRACT_REVIEW: "审",
  QUOTATION: "价",
};

const placeholderByCapability = {
  GRAPHIC_DESIGN: "描述用途、尺寸、文案和希望呈现的风格…",
  CONTRACT_REVIEW: "上传合同并说明我方身份与重点关注条款…",
  QUOTATION: "输入客户、项目要求、规格和交付条件…",
};

const allowedActionAliases = {
  PAUSE_TASK: "PAUSE",
  RESUME_TASK: "RESUME",
  GUIDE_TASK: "ADD_CONTEXT",
  APPROVE_APPROVAL: "APPROVE",
};

function normalizeTone(tone) {
  if (tone === "processing") return "info";
  if (tone === "waiting") return "warning";
  return tone || "neutral";
}

function formatTime(value) {
  if (!value) return "刚刚";
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value));
}

function adaptAgent(agent) {
  return {
    id: agent.id,
    name: agent.name,
    capability: agent.capability,
    capabilityLabel: agent.title,
    profile: agent.description,
    skills: agent.skillLabels,
    skillSummary: agent.skillLabels.slice(0, 2).join(" · "),
    image: agent.imageUrl,
    status: agent.status,
    statusLabel: agentStatusLabels[agent.status] ?? agent.status,
    currentTaskTitle: agent.primaryTask?.title ?? "当前没有进行中的工作",
    quickPlaceholder: placeholderByCapability[agent.capability],
    tone: toneByCapability[agent.capability],
  };
}

function executorName(state, executorId) {
  return state.agentsById[executorId]?.name
    ?? state.usersById[executorId]?.name
    ?? ({ "contract-parser": "合同解析工具", "quotation-rule-engine": "报价规则引擎" }[executorId])
    ?? "受控工具";
}

function adaptCapabilityData(taskVm) {
  if (taskVm.capability === "GRAPHIC_DESIGN") {
    return {
      ...taskVm.capabilityData,
      selectedPreviewId: taskVm.selectedArtifact?.id ?? null,
      variants: taskVm.capabilityData.outputSpecs.map((spec) => ({
        ...spec,
        statusLabel: spec.status === "READY" ? "已就绪" : spec.status === "FAILED" ? "生成失败" : spec.status === "RUNNING" ? "生成中" : "待派生",
      })),
    };
  }
  if (taskVm.capability === "CONTRACT_REVIEW") {
    const risks = taskVm.capabilityData.risks.map((risk) => ({
      ...risk,
      levelLabel: risk.level === "HIGH" ? "高" : risk.level === "MEDIUM" ? "中" : "低",
      decisionLabel: risk.decision === "PENDING" ? "待处理" : risk.decision === "ACCEPTED" ? "已采纳" : "已处理",
    }));
    return {
      ...taskVm.capabilityData,
      risks,
      unresolvedHighRiskCount: risks.filter((risk) => risk.level === "HIGH" && risk.decision === "PENDING").length,
    };
  }

  const toYuan = (minor = 0) => Math.round(minor / 100);
  return {
    ...taskVm.capabilityData,
    taxModeLabel: taskVm.capabilityData.taxMode === "INCLUDED" ? "含税" : "未税",
    stageLabel: taskVm.status === "WAITING_APPROVAL" ? "待审批" : taskVm.capabilityStage === "APPROVED" ? "已审批" : "报价草案",
    items: taskVm.capabilityData.items.map((item, index) => ({
      ...item,
      unitPrice: toYuan(item.unitPriceMinor),
      amount: toYuan(item.amountMinor),
      cost: toYuan(item.costMinor),
      source: ["历史工行展台案例", "供应成本 2026-Q2", "场馆合同价格", "项目服务规则"][index] ?? "已授权价格资产",
    })),
    totals: {
      subtotal: toYuan(taskVm.capabilityData.totals.subtotalMinor),
      tax: toYuan(taskVm.capabilityData.totals.taxMinor),
      total: toYuan(taskVm.capabilityData.totals.totalMinor),
      cost: toYuan(taskVm.capabilityData.totals.costMinor),
      margin: toYuan(taskVm.capabilityData.totals.marginMinor),
    },
  };
}

function adaptTask(taskVm, state) {
  const activeIndex = Math.max(0, taskVm.steps.findIndex((step) => step.id === taskVm.activeStep?.id));
  const pointSummary = taskVm.pointSummary ?? { estimated: 0, captured: 0, reserved: 0, released: 0 };
  const steps = taskVm.steps.map((step) => {
    const [statusLabel, statusTone] = stepStatusLabels[step.status] ?? [step.status, "neutral"];
    return { ...step, executorName: executorName(state, step.executorId), statusLabel, statusTone };
  });
  const trace = taskVm.events.map((event) => ({ ...event, occurredAtLabel: formatTime(event.occurredAt) }));
  const nextAction = taskVm.status === "WAITING_APPROVAL"
    ? "处理审批"
    : taskVm.status === "WAITING_CONFIRMATION"
      ? "确认结果"
      : taskVm.status === "PAUSED"
        ? "继续任务"
        : "查看进展";

  return {
    ...taskVm,
    agentId: taskVm.agent.id,
    ownerName: taskVm.agent.name,
    ownerImage: taskVm.agent.imageUrl,
    tone: toneByCapability[taskVm.capability],
    shortIcon: shortIconByCapability[taskVm.capability],
    statusTone: normalizeTone(taskVm.statusTone),
    statusLabel: taskVm.statusLabel,
    stepIndex: activeIndex + 1,
    stepCount: taskVm.steps.length,
    currentStep: taskVm.activeStep?.title ?? "查看成果",
    stepSummary: taskVm.activeStep ? `${executorName(state, taskVm.activeStep.executorId)}正在负责` : "任务步骤已完成",
    nextAction,
    pointCaptured: pointSummary.captured,
    pointEstimated: pointSummary.estimated,
    pointReserved: pointSummary.reserved,
    pointSummary: {
      estimatedMax: pointSummary.estimated,
      captured: pointSummary.captured,
      reserved: pointSummary.reserved,
      released: pointSummary.released,
    },
    activeStepId: taskVm.activeStep?.id,
    steps,
    trace,
    capabilityData: adaptCapabilityData(taskVm),
    graphicCandidates: taskVm.artifacts.slice(0, 2).map((artifact, index) => ({
      id: artifact.id,
      image: index === 0 ? "/assets/results/expo-keyvisual-a.png" : "/assets/results/expo-keyvisual-b.png",
      label: index === 0 ? "方案 A · 深蓝空间" : "方案 B · 明亮建筑",
    })),
    selectedArtifactId: taskVm.selectedArtifact?.id ?? null,
    allowedActions: taskVm.allowedActions.map((action) => allowedActionAliases[action] ?? action),
    currentRunNo: taskVm.run?.runNo ?? 1,
    updatedAtLabel: formatTime(state.tasksById[taskVm.id]?.updatedAt),
  };
}

function usePrototypeView() {
  const state = usePrototypeState();
  const dispatch = usePrototypeDispatch();
  const office = useMemo(() => selectOfficeViewModel(state), [state]);
  const agents = useMemo(() => office.agents.map(adaptAgent), [office]);
  const tasks = useMemo(() => office.tasks.map((task) => adaptTask(task, state)), [office, state]);
  return { state, dispatch, office, agents, tasks };
}

function OfficeRoute() {
  const navigate = useNavigate();
  const { office, agents, tasks } = usePrototypeView();
  const firstConversationId = office.rooms[0]?.id ?? null;
  return <OfficePage agents={agents} tasks={tasks} onOpenAgent={(agentId, quickGoal) => navigate(`/employees/${agentId}/workspace`, { state: quickGoal ? { quickGoal } : null })} onOpenTask={(taskId) => navigate(`/tasks/${taskId}`)} onNavigate={navigate} messagePath={firstConversationId ? `/rooms/${firstConversationId}` : null} />;
}

function EmployeesRoute() {
  const navigate = useNavigate();
  const { agents } = usePrototypeView();
  return (
    <EmployeesPage
      agents={agents}
      onOpenAgent={(agentId) => navigate(`/employees/${agentId}/workspace`)}
      onClose={() => navigate("/office")}
    />
  );
}

function WorkspaceRoute() {
  const { agentId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { state, dispatch } = usePrototypeView();
  const rawAgent = selectAgentViewModel(state, agentId);
  if (!rawAgent) return <Navigate to="/office" replace />;
  const agent = adaptAgent(rawAgent);
  const quickGoal = location.state?.quickGoal?.trim() ?? "";
  const taskVm = quickGoal ? null : Object.values(state.tasksById)
    .filter((task) => task.agentId === agentId)
    .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))
    .map((task) => selectTaskViewModel(state, task.id))
    .find(Boolean);
  const task = taskVm
    ? adaptTask(taskVm, state)
    : {
      id: `draft-${agentId}`,
      title: quickGoal || `${agent.name}的新工作`,
      status: "DRAFT",
      statusLabel: "草稿",
      planVersion: 1,
      pointSummary: { estimatedMax: 400, captured: 0, reserved: 0, released: 0 },
    };

  const start = (request) => {
    if (task.status === "DRAFT") {
      const newTaskId = `task-${state.meta.nextSequence}`;
      dispatch({
        type: PROTOTYPE_ACTION.START_TASK,
        payload: {
          agentId,
          title: request?.goal || task.title,
          capabilityInput: request?.capabilityInput,
          desiredArtifactType: request?.desiredArtifactType,
        },
      });
      navigate(`/tasks/${newTaskId}`, { replace: true });
      return;
    }
    navigate(`/tasks/${task.id}`);
  };

  return <WorkspacePage agent={agent} task={task} initialGoal={quickGoal} onBack={() => navigate("/office")} onStartTask={start} onOpenTask={(taskId) => navigate(`/tasks/${taskId}`)} />;
}

function TasksRoute() {
  const navigate = useNavigate();
  const { tasks } = usePrototypeView();
  return (
    <TasksPage
      tasks={tasks}
      onOpenTask={(taskId) => navigate(`/tasks/${taskId}`)}
      onClose={() => navigate("/office")}
    />
  );
}

function TaskRoute() {
  const { taskId } = useParams();
  const navigate = useNavigate();
  const { state, dispatch } = usePrototypeView();
  const taskVm = selectTaskViewModel(state, taskId);
  if (!taskVm) return <Navigate to="/tasks" replace />;
  const task = adaptTask(taskVm, state);
  const agent = adaptAgent(selectAgentViewModel(state, taskVm.agent.id));

  const handleAction = (action, payload = {}) => {
    if (action === "PAUSE") dispatch({ type: PROTOTYPE_ACTION.PAUSE_TASK, payload: { taskId } });
    if (action === "RESUME") dispatch({ type: PROTOTYPE_ACTION.RESUME_TASK, payload: { taskId } });
    if (action === "ADVANCE_STEP") dispatch({ type: PROTOTYPE_ACTION.ADVANCE_STEP, payload: { taskId } });
    if (action === "GUIDE_TASK") dispatch({ type: PROTOTYPE_ACTION.GUIDE_TASK, payload: { taskId, text: payload.text, impact: "LOW" } });
    if (action === "SELECT_ARTIFACT") dispatch({ type: PROTOTYPE_ACTION.SELECT_ARTIFACT, payload: { taskId, artifactId: payload.artifactId } });
    if (action === "SUBMIT_APPROVAL") dispatch({ type: PROTOTYPE_ACTION.SUBMIT_APPROVAL, payload: { taskId } });
    if (action === "APPROVE") dispatch({ type: PROTOTYPE_ACTION.APPROVE_APPROVAL, payload: { taskId } });
    if (action === "RESOLVE_CONTRACT_RISK") {
      const decisions = Object.fromEntries(taskVm.capabilityData.risks.map((risk) => [risk.id, risk.decision]));
      decisions[payload.riskId] = payload.decision;
      dispatch({ type: PROTOTYPE_ACTION.GUIDE_TASK, payload: { taskId, text: "人工处理合同风险项", riskDecisions: decisions, impact: "LOW" } });
    }
  };

  return <TaskDetailPage task={task} agent={agent} onBack={() => navigate("/tasks")} onAction={handleAction} />;
}

function ArtifactsRoute() {
  const navigate = useNavigate();
  const { tasks } = usePrototypeView();
  return (
    <ArtifactsPage
      tasks={tasks}
      onOpenTask={(taskId) => navigate(`/tasks/${taskId}`)}
      onClose={() => navigate("/office")}
    />
  );
}

function PointsRoute() {
  const { state } = usePrototypeView();
  const account = selectPointViewModel(state);
  const entries = Object.values(state.pointLedgerEntriesById)
    .filter((entry) => entry.accountId === account?.id)
    .sort((left, right) => right.occurredAt.localeCompare(left.occurredAt))
    .slice(0, 8)
    .map((entry) => {
      const reservation = state.pointReservationsById[entry.reservationId];
      return {
        ...entry,
        sourceLabel: reservation ? `${reservation.sourceType === "MESSAGE" ? "群聊调用" : "任务"} · ${reservation.sourceId}` : "企业账户",
        occurredAtLabel: formatTime(entry.occurredAt),
      };
    });
  if (!account) return <Navigate to="/office" replace />;
  return <PointsPage account={account} entries={entries} />;
}

function GroupRoute() {
  const { conversationId = "conversation-project" } = useParams();
  const navigate = useNavigate();
  const { state, dispatch, agents } = usePrototypeView();
  const conversation = selectConversationViewModel(state, conversationId === "project-a" ? "conversation-project" : conversationId)
    ?? selectConversationViewModel(state, "conversation-project");
  const messages = conversation.messages.map((message) => ({
    id: message.id,
    senderType: message.senderType,
    senderName: message.sender?.name ?? "群成员",
    avatar: message.sender?.imageUrl ?? "/assets/employees/quotation-specialist.png",
    text: message.text,
    createdAtLabel: formatTime(message.createdAt),
    pointImpact: message.estimatedPointImpact,
    targets: message.targets.map((target) => ({ id: target.agentId, name: target.agent?.name ?? "数字员工" })),
    modeLabel: message.mode === "PRIMARY_SUMMARY" ? "主责汇总" : message.mode === "PARALLEL_SEPARATE" ? "分别执行" : "单员工",
  }));
  const roomTasks = Object.values(state.tasksById)
    .filter((task) => task.source?.conversationId === conversation.id)
    .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))
    .map((task) => selectTaskViewModel(state, task.id))
    .filter(Boolean)
    .map((task) => adaptTask(task, state));

  const send = ({ content, targetIds, mode, primaryAgentId, commandId }) => {
    dispatch({
      type: PROTOTYPE_ACTION.SEND_GROUP_MESSAGE,
      payload: {
        conversationId: conversation.id,
        text: content,
        targetAgentIds: targetIds,
        mode,
        primaryAgentId,
        commandId,
      },
    });
  };

  return <GroupRoomPage agents={agents} messages={messages} tasks={roomTasks} onBack={() => navigate("/office")} onOpenTask={(taskId) => navigate(`/tasks/${taskId}`)} onSendMessage={send} />;
}

function AdminLoading({ label }) {
  return <div className="admin-route-loading" role="status">正在加载{label}…</div>;
}

function EnterpriseOverviewRoute() {
  const navigate = useNavigate();
  return (
    <Suspense fallback={<AdminLoading label="企业概览" />}>
      <EnterpriseOverview onNavigate={(key) => navigate(key === "overview" ? "/enterprise/overview" : `/enterprise/${key}`)} />
    </Suspense>
  );
}

function EnterpriseModuleRoute() {
  const { moduleKey } = useParams();
  const navigate = useNavigate();
  if (!enterpriseModuleKeys.has(moduleKey)) return <Navigate to="/enterprise/overview" replace />;
  return (
    <Suspense fallback={<AdminLoading label="企业管理模块" />}>
      <EnterpriseModules moduleKey={moduleKey} onModuleChange={(key) => navigate(key === "overview" ? "/enterprise/overview" : `/enterprise/${key}`)} />
    </Suspense>
  );
}

function PlatformRoute() {
  const { moduleKey = "overview" } = useParams();
  const navigate = useNavigate();
  if (moduleKey !== "overview" && !platformModuleKeys.has(moduleKey)) return <Navigate to="/platform/overview" replace />;
  return (
    <Suspense fallback={<AdminLoading label="平台运营中心" />}>
      <PlatformOverview moduleKey={moduleKey} onNavigate={(key) => navigate(key === "overview" ? "/platform/overview" : `/platform/${key}`)} />
    </Suspense>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/office" replace />} />
        <Route element={<PortalShell />}>
          <Route path="/office" element={<OfficeRoute />} />
          <Route path="/employees" element={<EmployeesRoute />} />
          <Route path="/employees/:agentId" element={<Navigate to="workspace" replace />} />
          <Route path="/employees/:agentId/workspace" element={<WorkspaceRoute />} />
          <Route path="/tasks" element={<TasksRoute />} />
          <Route path="/tasks/:taskId" element={<TaskRoute />} />
          <Route path="/artifacts" element={<ArtifactsRoute />} />
          <Route path="/knowledge" element={<KnowledgePage />} />
          <Route path="/rooms/:conversationId" element={<GroupRoute />} />
          <Route path="/me/points" element={<PointsRoute />} />
        </Route>
        <Route path="/enterprise" element={<Navigate to="/enterprise/overview" replace />} />
        <Route path="/enterprise/overview" element={<EnterpriseOverviewRoute />} />
        <Route path="/enterprise/:moduleKey" element={<EnterpriseModuleRoute />} />
        <Route path="/platform" element={<Navigate to="/platform/overview" replace />} />
        <Route path="/platform/:moduleKey" element={<PlatformRoute />} />
        <Route path="*" element={<Navigate to="/office" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
