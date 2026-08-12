import { useCallback, useEffect, useRef, useState } from "react";
import {
  BrowserRouter,
  Navigate,
  Outlet,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";
import { PortalHeader } from "../components/PortalHeader.jsx";
import { EmployeesPage, TasksPage } from "../pages/DirectoryPages.jsx";
import { OfficePage } from "../pages/OfficePage.jsx";
import { TaskDetailPage } from "../pages/TaskDetailPage.jsx";
import { WorkspacePage } from "../pages/WorkspacePage.jsx";
import {
  buildCapabilityInputValues,
  buildCreateTaskRequest,
  createApiDraftTask,
  mapEmployeeWorkspaceResponse,
  mapTaskSnapshotResponse,
} from "./adapters.js";
import { ApiBoundaryState } from "./ApiBoundaryState.js";
import { useApiPortal } from "./ApiPortalProvider.jsx";
import {
  canAccessEnterpriseEmployeeManagement,
  PLATFORM_TEMPLATE_PUBLISH_PERMISSION,
  PLATFORM_TEMPLATE_READ_PERMISSION,
} from "./portalBootstrap.js";
import { executeStableTaskSubmission, prepareStableTaskSubmission } from "./taskSubmission.js";
import { createTaskLiveSync, TASK_LIVE_PHASE } from "./taskLiveSync.js";
import { LoginPage } from "./LoginPage.jsx";
import { EnterpriseAgentManagementPage } from "./EnterpriseAgentManagementPage.jsx";
import { PlatformAgentVersionPage } from "./PlatformAgentVersionPage.jsx";
import { PlatformModelManagementPage } from "./PlatformModelManagementPage.jsx";
import { ConversationPage } from "./ConversationPage.jsx";
import { CONVERSATION_PERMISSIONS } from "./conversationAdapters.js";
import { MODEL_PERMISSIONS } from "./modelManagementAdapters.js";
import "./api-portal.css";

function resolveActiveKey(pathname) {
  if (pathname.startsWith("/messages")) return "messages";
  if (pathname.startsWith("/employees")) return "employees";
  if (pathname.startsWith("/tasks")) return "tasks";
  if (pathname.startsWith("/artifacts")) return "artifacts";
  if (pathname.startsWith("/knowledge")) return "knowledge";
  return "office";
}

function errorDetail(error, fallback = "请求失败，请稍后重试。") {
  return error?.detail ?? error?.message ?? fallback;
}

function boundaryKind(error) {
  if (error?.status === 401) return "unauthenticated";
  if (error?.status === 403) return "forbidden";
  if (error?.status === 404) return "not-found";
  return "error";
}

function PortalApiShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const { office, session, logout } = useApiPortal();
  if (!session.tenant || !office) {
    return <ApiBoundaryState kind="empty" title="尚未选择企业" detail="当前会话没有活动企业，无法进入企业数字办公大厅。" />;
  }
  if (location.pathname.startsWith("/messages")) return <Outlet />;
  const canManageEnterprise = canAccessEnterpriseEmployeeManagement(session.permissions);
  return (
    <div className="portal-app">
      <PortalHeader
        activeKey={resolveActiveKey(location.pathname)}
        onNavigate={navigate}
        pointBalance={null}
        tenantName={session.tenant.name}
        userName={session.user.name}
        userAvatar={session.user.avatarUrl ?? "/assets/brand/dianlian-symbol.png"}
        userRoleLabel={canManageEnterprise ? "企业成员 · 管理员" : "企业成员"}
        notificationCount={office.todos.length}
        showAdminLinks={false}
        showEnterpriseLink={canManageEnterprise}
        showPlatformLink={false}
        showMessages={session.permissions.includes(CONVERSATION_PERMISSIONS.READ)}
        messagePath="/messages"
        onLogout={logout}
      />
      <div className="portal-workspace"><Outlet /></div>
    </div>
  );
}

function OfficeRoute() {
  const navigate = useNavigate();
  const { office, session } = useApiPortal();
  if (office.agents.length === 0) return <ApiBoundaryState kind="empty" />;
  return (
    <OfficePage
      agents={office.agents}
      tasks={office.tasks}
      onOpenAgent={(agentId, quickGoal) => navigate(`/employees/${encodeURIComponent(agentId)}/workspace`, {
        state: quickGoal ? { quickGoal } : null,
      })}
      onMessageAgent={session.permissions.includes(CONVERSATION_PERMISSIONS.READ)
        ? (agentId) => navigate(`/messages?agentId=${encodeURIComponent(agentId)}`)
        : null}
      onOpenTask={(taskId) => navigate(`/tasks/${encodeURIComponent(taskId)}`)}
      onNavigate={navigate}
      messagePath={session.permissions.includes(CONVERSATION_PERMISSIONS.READ) ? "/messages" : null}
    />
  );
}

function EmployeesRoute() {
  const navigate = useNavigate();
  const { office } = useApiPortal();
  if (office.agents.length === 0) return <ApiBoundaryState kind="empty" />;
  return (
    <EmployeesPage
      agents={office.agents}
      onOpenAgent={(agentId) => navigate(`/employees/${encodeURIComponent(agentId)}/workspace`)}
      onClose={() => navigate("/office")}
    />
  );
}

function MessagesRoute() {
  const { dataSource, office, session } = useApiPortal();
  if (!session.permissions.includes(CONVERSATION_PERMISSIONS.READ)) {
    return <ApiBoundaryState kind="forbidden" detail="当前身份没有查看企业会话的权限。" />;
  }
  return <ConversationPage session={session} office={office} dataSource={dataSource} />;
}

function employeeViewModel(workspace, officeAgent) {
  return {
    ...officeAgent,
    id: workspace.agentId,
    name: workspace.displayName,
    capability: workspace.capability,
    capabilityLabel: workspace.roleName,
    profile: workspace.profile,
    skills: workspace.skills,
    image: workspace.image,
    status: officeAgent?.status ?? "IDLE",
    statusLabel: officeAgent?.statusLabel ?? "可用",
    canStartTask: workspace.canStartTask,
    allowedActions: workspace.allowedActions,
  };
}

function WorkspaceRoute() {
  const { agentId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const { dataSource, office, session } = useApiPortal();
  const [resource, setResource] = useState({ phase: "loading", workspace: null, error: null });
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const submissionRef = useRef(null);

  useEffect(() => {
    const controller = new AbortController();
    setResource({ phase: "loading", workspace: null, error: null });
    setSubmitError(null);
    submissionRef.current = null;
    dataSource.getEmployeeWorkspace(agentId, { signal: controller.signal })
      .then((response) => {
        if (response.notModified || !response.workspace) {
          throw new Error("Initial employee request returned no workspace");
        }
        const officeAgent = office.agentsById.get(String(agentId));
        setResource({
          phase: "ready",
          workspace: mapEmployeeWorkspaceResponse(response.workspace, officeAgent),
          error: null,
        });
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setResource({ phase: boundaryKind(error), workspace: null, error });
      });
    return () => controller.abort();
  }, [agentId, dataSource, office.agentsById]);

  if (resource.phase === "loading") {
    return <ApiBoundaryState kind="loading" title="正在读取员工工作台" detail="正在读取当前员工版本、输入规则和执行模板。" />;
  }
  if (resource.phase !== "ready") {
    return (
      <ApiBoundaryState
        kind={resource.phase}
        detail={errorDetail(resource.error)}
        actionLabel="返回办公室"
        onAction={() => navigate("/office")}
      />
    );
  }

  const workspace = resource.workspace;
  const agent = employeeViewModel(workspace, office.agentsById.get(workspace.agentId));
  const quickGoal = location.state?.quickGoal?.trim() ?? "";
  const draft = createApiDraftTask(agent);
  const task = {
    ...draft,
    title: quickGoal || draft.title,
    pointSummary: { ...draft.pointSummary, estimatedMax: workspace.pointEstimate },
  };

  const start = async (request) => {
    if (submitting) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const values = buildCapabilityInputValues(workspace, request.rawCapabilityValues);
      const payload = buildCreateTaskRequest({
        session,
        agent,
        request: {
          ...request,
          desiredArtifactType: null,
          capabilityInput: {
            schemaId: workspace.inputSchema.schemaId,
            schemaVersion: workspace.inputSchema.schemaVersion,
            values,
          },
        },
      });
      const submission = prepareStableTaskSubmission(dataSource, payload, {
        previous: submissionRef.current,
      });
      submissionRef.current = submission;
      const accepted = await executeStableTaskSubmission(submission, { maxAttempts: 2 });
      const acceptedTaskId = String(accepted?.taskId ?? "").trim();
      if (!acceptedTaskId) throw new Error("Task creation response did not include taskId");
      navigate(`/tasks/${encodeURIComponent(acceptedTaskId)}`, { replace: true });
    } catch (error) {
      setSubmitError(errorDetail(error, "任务未创建，请检查输入后重试。"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <WorkspacePage
      mode="api"
      agent={agent}
      task={task}
      initialGoal={quickGoal}
      workspaceContract={workspace}
      submitting={submitting}
      submitError={submitError}
      onBack={() => navigate("/office")}
      onStartTask={start}
      onOpenTask={(taskId) => navigate(`/tasks/${encodeURIComponent(taskId)}`)}
      onMessageAgent={session.permissions.includes(CONVERSATION_PERMISSIONS.READ)
        ? (selectedAgentId) => navigate(`/messages?agentId=${encodeURIComponent(selectedAgentId)}`)
        : null}
    />
  );
}

function TasksRoute() {
  const navigate = useNavigate();
  const { office } = useApiPortal();
  return (
    <TasksPage
      tasks={office.tasks}
      onOpenTask={(taskId) => navigate(`/tasks/${encodeURIComponent(taskId)}`)}
      onClose={() => navigate("/office")}
    />
  );
}

function TaskRoute() {
  const { taskId } = useParams();
  const navigate = useNavigate();
  const { dataSource, office, session } = useApiPortal();
  const etagRef = useRef(null);
  const taskRef = useRef(null);
  const [resource, setResource] = useState({ phase: "loading", task: null, error: null, refreshing: false });
  const [liveState, setLiveState] = useState({ phase: TASK_LIVE_PHASE.CONNECTING, detail: "正在连接任务动态" });

  const loadTask = useCallback(async ({ refresh = false, reset = false, silent = false } = {}) => {
    if (refresh && !silent) {
      setResource((current) => ({ ...current, refreshing: true, error: null }));
    } else if (refresh) {
      setResource((current) => ({ ...current, error: null }));
    } else {
      etagRef.current = null;
      taskRef.current = null;
      setResource({ phase: "loading", task: null, error: null, refreshing: false });
      setLiveState({ phase: TASK_LIVE_PHASE.CONNECTING, detail: "正在连接任务动态" });
    }
    if (reset) etagRef.current = null;
    try {
      const response = await dataSource.getTask(taskId, { etag: refresh && !reset ? etagRef.current : null });
      if (response.notModified) {
        setResource({ phase: "ready", task: taskRef.current, error: null, refreshing: false });
        return taskRef.current;
      }
      if (!response.task) throw new Error("Task request returned no snapshot");
      const mapped = mapTaskSnapshotResponse(response.task, { office, session });
      etagRef.current = response.etag;
      taskRef.current = mapped;
      setResource({ phase: "ready", task: mapped, error: null, refreshing: false });
      return mapped;
    } catch (error) {
      if (refresh && taskRef.current) {
        setResource({ phase: "ready", task: taskRef.current, error, refreshing: false });
        throw error;
      }
      setResource({ phase: boundaryKind(error), task: null, error, refreshing: false });
      throw error;
    }
  }, [dataSource, office, session, taskId]);

  useEffect(() => {
    void loadTask().catch(() => null);
  }, [loadTask]);

  useEffect(() => {
    if (resource.phase !== "ready") return undefined;
    const liveSync = createTaskLiveSync({
      readTaskEvents: (options) => dataSource.readTaskEvents(taskId, options),
      refreshSnapshot: (options) => loadTask({ refresh: true, ...options }),
      getCurrentSnapshot: () => taskRef.current,
      onState: setLiveState,
    });
    liveSync.start();
    return () => liveSync.stop();
  }, [dataSource, loadTask, resource.phase, taskId]);

  if (resource.phase === "loading") {
    return <ApiBoundaryState kind="loading" title="正在读取任务" detail="正在读取权威任务快照、执行计划和智点状态。" />;
  }
  if (resource.phase !== "ready") {
    return (
      <ApiBoundaryState
        kind={resource.phase}
        detail={errorDetail(resource.error)}
        actionLabel="返回任务中心"
        onAction={() => navigate("/tasks")}
      />
    );
  }

  const task = resource.task;
  const agent = {
    id: task.agentId,
    name: task.ownerName,
    image: task.ownerImage,
    capability: task.capability,
  };
  return (
    <>
      {resource.error ? <div className="api-inline-error" role="alert">刷新失败：{errorDetail(resource.error)}</div> : null}
      <TaskDetailPage
        task={task}
        agent={agent}
        onBack={() => navigate("/tasks")}
        onAction={null}
        onRefresh={() => { void loadTask({ refresh: true }).catch(() => null); }}
        refreshing={resource.refreshing}
        liveState={liveState}
      />
    </>
  );
}

function UnavailableRoute() {
  return <ApiBoundaryState kind="unavailable" />;
}

function EnterpriseAgentsRoute() {
  const navigate = useNavigate();
  const { dataSource, refreshOffice, session } = useApiPortal();
  if (!canAccessEnterpriseEmployeeManagement(session.permissions)) {
    return <ApiBoundaryState kind="forbidden" detail="当前身份可以使用已授权数字员工，但没有企业员工管理权限。" actionLabel="返回办公室" onAction={() => navigate("/office")} />;
  }
  return (
    <EnterpriseAgentManagementPage
      session={session}
      dataSource={dataSource}
      onBack={() => navigate("/office")}
      onOfficeChanged={refreshOffice}
    />
  );
}

function PlatformAgentVersionsRoute() {
  const navigate = useNavigate();
  const { dataSource, logout, session } = useApiPortal();
  const isPlatformSession = !session.tenant
    && session.permissions.includes(PLATFORM_TEMPLATE_READ_PERMISSION);
  if (!isPlatformSession) {
    return (
      <ApiBoundaryState
        kind="forbidden"
        detail={session.tenant ? "平台运营中心仅允许平台会话进入。" : "当前身份没有查看官方员工模板的权限。"}
        actionLabel={session.tenant ? "返回办公室" : "退出登录"}
        onAction={session.tenant ? () => navigate("/office") : logout}
      />
    );
  }
  return (
    <PlatformAgentVersionPage
      session={session}
      dataSource={dataSource}
      canPublish={session.permissions.includes(PLATFORM_TEMPLATE_PUBLISH_PERMISSION)}
      onBack={null}
      onNavigateModels={session.permissions.includes(MODEL_PERMISSIONS.READ)
        ? () => navigate("/platform/models")
        : null}
      onLogout={logout}
    />
  );
}

function PlatformModelsRoute() {
  const navigate = useNavigate();
  const { dataSource, logout, session } = useApiPortal();
  const isPlatformSession = !session.tenant && session.permissions.includes(MODEL_PERMISSIONS.READ);
  if (!isPlatformSession) {
    return (
      <ApiBoundaryState
        kind="forbidden"
        detail={session.tenant ? "平台运营中心仅允许平台会话进入。" : "当前身份没有查看官方模型配置的权限。"}
        actionLabel={session.tenant ? "返回办公室" : "退出登录"}
        onAction={session.tenant ? () => navigate("/office") : logout}
      />
    );
  }
  return (
    <PlatformModelManagementPage
      session={session}
      dataSource={dataSource}
      onBack={null}
      onNavigateTemplates={session.permissions.includes(PLATFORM_TEMPLATE_READ_PERMISSION)
        ? () => navigate("/platform/agent-versions")
        : null}
      onLogout={logout}
    />
  );
}

function ReadyApplication({ session }) {
  const homePath = session.tenant
    ? "/office"
    : session.permissions.includes(PLATFORM_TEMPLATE_READ_PERMISSION)
      ? "/platform/agent-versions"
      : "/platform/models";
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to={homePath} replace />} />
        <Route path="/enterprise/agents" element={<EnterpriseAgentsRoute />} />
        <Route path="/platform" element={<Navigate to={homePath} replace />} />
        <Route path="/platform/agent-versions" element={<PlatformAgentVersionsRoute />} />
        <Route path="/platform/models" element={<PlatformModelsRoute />} />
        <Route path="/platform/*" element={<ApiBoundaryState kind="not-found" />} />
        <Route element={<PortalApiShell />}>
          <Route path="/office" element={<OfficeRoute />} />
          <Route path="/messages" element={<MessagesRoute />} />
          <Route path="/employees" element={<EmployeesRoute />} />
          <Route path="/employees/:agentId" element={<Navigate to="workspace" replace />} />
          <Route path="/employees/:agentId/workspace" element={<WorkspaceRoute />} />
          <Route path="/tasks" element={<TasksRoute />} />
          <Route path="/tasks/:taskId" element={<TaskRoute />} />
          <Route path="/artifacts" element={<UnavailableRoute />} />
          <Route path="/knowledge" element={<UnavailableRoute />} />
          <Route path="/rooms/*" element={<UnavailableRoute />} />
          <Route path="/me/points" element={<UnavailableRoute />} />
          <Route path="/enterprise/*" element={<UnavailableRoute />} />
          <Route path="*" element={<ApiBoundaryState kind="not-found" />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export function ApiPortalApp() {
  const { phase, error, reload, login, session } = useApiPortal();
  if (["loading-session", "loading-office"].includes(phase)) {
    return <ApiBoundaryState kind="loading" />;
  }
  if (phase === "unauthenticated") {
    return <LoginPage onLogin={login} error={error?.code === "INVALID_CREDENTIALS" ? errorDetail(error) : null} />;
  }
  if (phase === "forbidden") {
    return <ApiBoundaryState kind="forbidden" detail={errorDetail(error)} actionLabel="重新检查权限" onAction={reload} />;
  }
  if (phase === "no-tenant") {
    return <ApiBoundaryState kind="empty" title="尚未选择企业" detail="当前会话没有活动企业，无法读取企业数字员工办公室。" />;
  }
  if (phase === "error") {
    return <ApiBoundaryState kind="error" detail={errorDetail(error)} actionLabel="重新加载" onAction={reload} />;
  }
  return <ReadyApplication session={session} />;
}
