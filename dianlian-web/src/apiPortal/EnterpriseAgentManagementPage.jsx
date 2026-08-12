import { useEffect, useMemo, useRef, useState } from "react";
import {
  IconArrowLeft,
  IconBook2,
  IconBrain,
  IconBriefcase,
  IconBuildingCommunity,
  IconBuildingSkyscraper,
  IconCheck,
  IconChevronRight,
  IconCoinYuan,
  IconListCheck,
  IconPlus,
  IconRefresh,
  IconSettings,
  IconShieldCheck,
  IconShieldLock,
  IconUsers,
  IconX,
} from "@tabler/icons-react";
import { BrandLogo } from "../components/BrandLogo.jsx";
import { StatusChip } from "../components/StatusChip.jsx";
import {
  buildEnterpriseAgentConfigurationPayload,
  loadEnterpriseManagementData,
  refreshActivatedEnterpriseAgentViews,
} from "./enterpriseAgentManagementData.js";
import { prepareStableEmployeeCommand } from "./employeeCommandIntent.js";
import "./enterprise-agent-management.css";

const CREATE_CONFIGURATION_VERSION = "CREATE_CONFIGURATION_VERSION";
const ACTIVATE = "ACTIVATE";

const capabilityPresentation = Object.freeze({
  GRAPHIC_DESIGN: { label: "平面出图", image: "/assets/employees/graphic-designer.png" },
  CONTRACT_REVIEW: { label: "法务合同审核", image: "/assets/employees/contract-reviewer.png" },
  QUOTATION: { label: "报价", image: "/assets/employees/quotation-specialist.png" },
});

const modePresentation = Object.freeze({
  PLATFORM_DEFAULT: ["平台默认", "继承平台已发布的模型策略"],
  NONE: ["暂未绑定", "当前配置没有绑定企业知识范围"],
  TENANT: ["当前企业", "仅在当前企业的数据与权限边界内生效"],
});

const actionPresentation = Object.freeze({
  VIEW: "查看配置",
  CREATE_CONFIGURATION_VERSION: "保存新配置版本",
  ACTIVATE: "启用员工",
});

function visualFor(capabilityCode) {
  return capabilityPresentation[capabilityCode] ?? {
    label: capabilityCode || "通用能力",
    image: "/assets/brand/dianlian-symbol.png",
  };
}

function statusPresentation(status) {
  if (status === "ACTIVE") return ["已到岗", "success"];
  if (status === "DRAFT") return ["待配置", "warning"];
  if (status === "RESTRICTED") return ["受限", "danger"];
  if (status === "DISABLED") return ["已停用", "neutral"];
  return ["未知状态", "neutral"];
}

function errorMessage(error, fallback) {
  return error?.detail ?? error?.message ?? fallback;
}

function formValues(detail) {
  const configuration = detail?.latestConfiguration;
  return {
    displayName: configuration?.displayNameSnapshot ?? detail?.displayName ?? "",
    profile: configuration?.profile ?? detail?.template?.templateDescription ?? "",
    enterpriseInstructions: configuration?.enterpriseInstructions ?? "",
  };
}

function sameForm(left, right) {
  return left.displayName === right.displayName
    && left.profile === right.profile
    && left.enterpriseInstructions === right.enterpriseInstructions;
}

function ModeCard({ label, value }) {
  const [title, description] = modePresentation[value] ?? [value || "未返回", "以服务端返回的生效范围为准"];
  return (
    <span className="eam-mode-card">
      <small>{label}</small>
      <strong>{title}</strong>
      <code>{value || "—"}</code>
      <em>{description}</em>
    </span>
  );
}

function RecruitDrawer({ templates, initialTemplateId, submitting, error, onClose, onConfirm }) {
  const initial = templates.find((item) => item.agentVersionId === initialTemplateId) ?? templates[0];
  const [selectedId, setSelectedId] = useState(initial?.agentVersionId ?? "");
  const selected = templates.find((item) => item.agentVersionId === selectedId) ?? initial;
  const [displayName, setDisplayName] = useState(selected?.templateName ?? "");
  const [employeeCode, setEmployeeCode] = useState("");

  useEffect(() => {
    if (!selected) return;
    setDisplayName(selected.templateName);
    setEmployeeCode(selected.templateCode);
  }, [selected?.agentVersionId]);

  if (!selected) return null;
  return (
    <div className="eam-layer" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <aside className="eam-drawer" role="dialog" aria-modal="true" aria-label="招聘数字员工">
        <header>
          <div><small>从平台官方模板招聘</small><h2>招聘数字员工</h2></div>
          <button type="button" aria-label="关闭招聘面板" onClick={onClose}><IconX size={20} /></button>
        </header>
        <div className="eam-drawer__body">
          <section>
            <h3>选择员工类型</h3>
            <div className="eam-template-options">
              {templates.map((item) => {
                const visual = visualFor(item.capabilityCode);
                return (
                  <button
                    className={selectedId === item.agentVersionId ? "is-selected" : ""}
                    type="button"
                    key={item.agentVersionId}
                    onClick={() => setSelectedId(item.agentVersionId)}
                  >
                    <img src={visual.image} alt="" />
                    <span><strong>{item.templateName}</strong><small>{visual.label} · {item.version}</small></span>
                    {selectedId === item.agentVersionId ? <IconCheck size={18} /> : null}
                  </button>
                );
              })}
            </div>
          </section>
          <section className="eam-form">
            <h3>设置在编身份</h3>
            <label><span>员工名称</span><input value={displayName} maxLength={100} onChange={(event) => setDisplayName(event.target.value)} /></label>
            <label><span>员工编号</span><input value={employeeCode} maxLength={64} onChange={(event) => setEmployeeCode(event.target.value)} /></label>
          </section>
          <section className="eam-contract-summary">
            <img src={visualFor(selected.capabilityCode).image} alt="" />
            <div>
              <strong>{displayName || selected.templateName}</strong>
              <p>{selected.templateDescription}</p>
              <span>官方版本 {selected.version} · 招聘后进入待配置状态，完成配置并启用后才能进入办公室</span>
            </div>
          </section>
          {error ? <p className="eam-error" role="alert">{error}</p> : null}
        </div>
        <footer>
          <button type="button" onClick={onClose}>取消</button>
          <button
            className="is-primary"
            type="button"
            disabled={submitting || !displayName.trim() || !employeeCode.trim()}
            onClick={() => onConfirm({
              agentVersionId: selected.agentVersionId,
              displayName: displayName.trim(),
              employeeCode: employeeCode.trim(),
            })}
          >
            {submitting ? "正在招聘…" : "确认招聘"}
          </button>
        </footer>
      </aside>
    </div>
  );
}

function AgentConfigurationDrawer({
  state,
  saving,
  activating,
  actionError,
  onClose,
  onReload,
  onSave,
  onActivate,
}) {
  const detail = state.detail;
  const baseline = useMemo(() => formValues(detail), [detail]);
  const [form, setForm] = useState(baseline);

  useEffect(() => { setForm(baseline); }, [baseline]);

  const busy = saving || activating;
  const hasEtag = Boolean(state.etag);
  const allowedActions = detail?.allowedActions ?? [];
  const canSave = hasEtag && allowedActions.includes(CREATE_CONFIGURATION_VERSION);
  const canActivate = hasEtag && allowedActions.includes(ACTIVATE);
  const valid = Boolean(form.displayName.trim() && form.profile.trim());
  const dirty = !sameForm(form, baseline);
  const hasConfiguration = Boolean(detail?.latestConfiguration);
  const configuration = detail?.latestConfiguration;
  const visual = visualFor(detail?.capabilityCode);
  const [statusLabel, statusTone] = statusPresentation(detail?.status);
  const readiness = detail?.readiness;
  const blockers = readiness?.blockers ?? [];

  return (
    <div className="eam-layer" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && !busy && onClose()}>
      <aside className="eam-drawer eam-drawer--configuration" role="dialog" aria-modal="true" aria-label="数字员工配置">
        <header>
          <div><small>企业数字员工实例</small><h2>{detail?.displayName ?? "员工配置"}</h2></div>
          <button type="button" aria-label="关闭配置面板" disabled={busy} onClick={onClose}><IconX size={20} /></button>
        </header>

        {state.phase === "loading" ? <div className="eam-drawer-state">正在读取员工配置与启用条件…</div> : null}
        {state.phase === "error" ? (
          <div className="eam-drawer-state is-error">
            <strong>员工详情加载失败</strong>
            <span>{errorMessage(state.error, "暂时无法读取该员工。")}</span>
            <button type="button" onClick={onReload}>重新读取</button>
          </div>
        ) : null}

        {state.phase === "ready" && detail ? (
          <div className="eam-drawer__body">
            <section className="eam-configuration-identity">
              <img src={visual.image} alt="" />
              <div>
                <span><StatusChip tone={statusTone}>{statusLabel}</StatusChip><small>状态版本 {detail.stateVersion}</small></span>
                <strong>{form.displayName || detail.displayName}</strong>
                <p>{visual.label}数字员工 · {detail.employeeCode}</p>
              </div>
            </section>

            <section>
              <div className="eam-section-label"><div><h3>继承的官方模板</h3><p>企业配置不会修改平台发布的能力模板。</p></div><IconShieldLock size={18} /></div>
              <div className="eam-inherited-template">
                <strong>{detail.template.templateName}</strong>
                <span>官方版本 {detail.template.version}</span>
                <p>{detail.template.templateDescription}</p>
              </div>
            </section>

            <section>
              <div className="eam-section-label"><div><h3>企业实例配置</h3><p>{configuration ? `当前配置版本 ${configuration.revision} · ${configuration.status}` : "尚未保存企业配置版本"}；{canSave ? "再次保存会形成新版本。" : "当前状态仅允许查看。"}</p></div></div>
              <div className="eam-configuration-form">
                <label>
                  <span>员工名称</span>
                  <input
                    value={form.displayName}
                    maxLength={100}
                    readOnly={!canSave}
                    onChange={(event) => setForm((current) => ({ ...current, displayName: event.target.value }))}
                  />
                </label>
                <label>
                  <span>岗位画像</span>
                  <textarea
                    value={form.profile}
                    maxLength={2000}
                    readOnly={!canSave}
                    onChange={(event) => setForm((current) => ({ ...current, profile: event.target.value }))}
                  />
                </label>
                <label>
                  <span>企业补充指令</span>
                  <textarea
                    value={form.enterpriseInstructions}
                    maxLength={20000}
                    readOnly={!canSave}
                    placeholder="可补充企业术语、工作偏好和输出要求；不要填写密码或密钥。"
                    onChange={(event) => setForm((current) => ({ ...current, enterpriseInstructions: event.target.value }))}
                  />
                </label>
              </div>
            </section>

            <section>
              <div className="eam-section-label"><div><h3>配置边界</h3><p>以下范围由平台和企业权限策略确定，本页只读。</p></div></div>
              <div className="eam-mode-grid">
                <ModeCard label="模型策略" value={configuration?.modelPolicyMode ?? "PLATFORM_DEFAULT"} />
                <ModeCard label="知识范围" value={configuration?.knowledgeScopeMode ?? "NONE"} />
                <ModeCard label="可见范围" value={configuration?.visibilityScope ?? "TENANT"} />
              </div>
            </section>

            <section className={`eam-readiness ${readiness?.ready ? "is-ready" : "is-blocked"}`}>
              <div>
                <IconCheck size={18} />
                <span><strong>{readiness?.ready ? "已满足启用条件" : "尚未满足启用条件"}</strong><small>{readiness?.ready ? "启用后员工会进入办公室和员工名册。" : "请先处理以下配置项。"}</small></span>
              </div>
              {blockers.length ? (
                <ul>{blockers.map((blocker) => <li key={`${blocker.code}:${blocker.message}`}><code>{blocker.code}</code><span>{blocker.message}</span></li>)}</ul>
              ) : null}
            </section>

            <section>
              <div className="eam-section-label"><div><h3>当前可执行命令</h3><p>按钮以服务端返回的 allowedActions 为准。</p></div></div>
              <div className="eam-action-list">
                {allowedActions.map((action) => <span key={action}><strong>{actionPresentation[action] ?? action}</strong><code>{action}</code></span>)}
              </div>
            </section>

            {state.notice ? <p className={`eam-notice ${state.noticeTone === "warning" ? "is-warning" : ""}`} role="status">{state.notice}</p> : null}
            {!hasEtag ? <p className="eam-error" role="alert">详情响应缺少 ETag，已停止配置和启用操作，请重新读取员工状态。</p> : null}
            {actionError ? (
              <div className="eam-error" role="alert">
                <span>{errorMessage(actionError, "员工配置操作失败，请稍后重试。")}</span>
                {actionError.action === "REFRESH_RESOURCE" ? <button type="button" onClick={onReload}>重新读取员工状态</button> : null}
              </div>
            ) : null}
          </div>
        ) : null}

        <footer>
          <button type="button" disabled={busy} onClick={onClose}>关闭</button>
          {state.phase === "ready" && canSave ? (
            <button
              type="button"
              className={canActivate ? "" : "is-primary"}
              disabled={busy || !valid || (hasConfiguration && !dirty)}
              onClick={() => onSave(buildEnterpriseAgentConfigurationPayload(form))}
            >
              {saving ? "正在保存…" : "保存配置版本"}
            </button>
          ) : null}
          {state.phase === "ready" && canActivate ? (
            <button className="is-primary" type="button" disabled={busy || dirty || !configuration?.configurationVersionId} onClick={onActivate}>
              {activating ? "正在启用…" : "启用员工"}
            </button>
          ) : null}
        </footer>
      </aside>
    </div>
  );
}

export function EnterpriseAgentManagementPage({ session, dataSource, onBack, onOfficeChanged }) {
  const [state, setState] = useState({ phase: "loading", templates: [], agents: [], error: null });
  const [drawer, setDrawer] = useState(null);
  const [detailState, setDetailState] = useState({ phase: "idle", detail: null, etag: null, error: null, notice: null, noticeTone: null });
  const [submitting, setSubmitting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [activating, setActivating] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const hireCommandRef = useRef(null);
  const configurationCommandRef = useRef(null);
  const activationCommandRef = useRef(null);
  const detailRequestRef = useRef(0);
  const canHire = session.permissions.includes("enterprise.employee.hire");

  const load = async () => {
    setState((current) => ({ ...current, phase: "loading", error: null }));
    try {
      const result = await loadEnterpriseManagementData(dataSource, { canHire });
      setState({ phase: "ready", ...result, error: null });
      return true;
    } catch (error) {
      setState((current) => ({ ...current, phase: "error", error }));
      return false;
    }
  };

  const loadDetail = async (agentId) => {
    const requestId = detailRequestRef.current + 1;
    detailRequestRef.current = requestId;
    setActionError(null);
    setDetailState({ phase: "loading", detail: null, etag: null, error: null, notice: null, noticeTone: null });
    try {
      const response = await dataSource.getEnterpriseAgent(agentId);
      if (requestId !== detailRequestRef.current) return;
      setDetailState({ phase: "ready", detail: response.detail, etag: response.etag, error: null, notice: null, noticeTone: null });
    } catch (error) {
      if (requestId !== detailRequestRef.current) return;
      setDetailState({ phase: "error", detail: null, etag: null, error, notice: null, noticeTone: null });
    }
  };

  const openAgent = (agentId) => {
    setDrawer({ type: "agent", agentId });
    configurationCommandRef.current = null;
    activationCommandRef.current = null;
    void loadDetail(agentId);
  };

  useEffect(() => { void load(); }, [dataSource]);

  const stats = useMemo(() => ({
    types: new Set(state.templates.map((item) => item.templateId)).size,
    agents: state.agents.length,
    active: state.agents.filter((item) => item.status === "ACTIVE").length,
    pending: state.agents.filter((item) => item.status === "DRAFT").length,
  }), [state.agents, state.templates]);

  const hire = async (payload) => {
    if (submitting) return;
    hireCommandRef.current = prepareStableEmployeeCommand(hireCommandRef.current, {
      prefix: "hire",
      payload,
    });
    setSubmitting(true);
    setSubmitError(null);
    try {
      const hired = await dataSource.hireEnterpriseAgent(payload, { idempotencyKey: hireCommandRef.current.key });
      if (!hired?.enterpriseAgentId) throw new Error("招聘响应缺少 enterpriseAgentId，无法继续配置。");
      hireCommandRef.current = null;
      setDrawer({ type: "agent", agentId: hired.enterpriseAgentId });
      await Promise.all([load(), loadDetail(hired.enterpriseAgentId)]);
    } catch (error) {
      setSubmitError(errorMessage(error, "招聘失败，请稍后重试。"));
    } finally {
      setSubmitting(false);
    }
  };

  const saveConfiguration = async (payload) => {
    if (saving || !drawer?.agentId || !detailState.etag) return;
    configurationCommandRef.current = prepareStableEmployeeCommand(configurationCommandRef.current, {
      prefix: "agent-config",
      payload: { agentId: drawer.agentId, ifMatch: detailState.etag, ...payload },
    });
    setSaving(true);
    setActionError(null);
    try {
      const response = await dataSource.createEnterpriseAgentConfigurationVersion(drawer.agentId, payload, {
        etag: detailState.etag,
        idempotencyKey: configurationCommandRef.current.key,
      });
      configurationCommandRef.current = null;
      activationCommandRef.current = null;
      setDetailState({
        phase: "ready",
        detail: response.detail,
        etag: response.etag,
        error: null,
        notice: "配置版本已保存。确认启用前，员工仍不会进入办公室。",
        noticeTone: null,
      });
    } catch (error) {
      setActionError(error);
    } finally {
      setSaving(false);
    }
  };

  const activate = async () => {
    if (activating || !drawer?.agentId || !detailState.etag) return;
    const configurationVersionId = detailState.detail?.latestConfiguration?.configurationVersionId;
    if (!configurationVersionId) {
      setActionError(new Error("当前没有可启用的配置版本，请先保存配置。"));
      return;
    }
    const payload = { configurationVersionId };
    activationCommandRef.current = prepareStableEmployeeCommand(activationCommandRef.current, {
      prefix: "agent-activate",
      payload: { agentId: drawer.agentId, ifMatch: detailState.etag, ...payload },
    });
    setActivating(true);
    setActionError(null);
    try {
      const response = await dataSource.activateEnterpriseAgent(drawer.agentId, payload, {
        etag: detailState.etag,
        idempotencyKey: activationCommandRef.current.key,
      });
      activationCommandRef.current = null;
      configurationCommandRef.current = null;
      setDetailState({
        phase: "ready",
        detail: response.detail,
        etag: response.etag,
        error: null,
        notice: "员工已启用，正在同步员工列表和办公室。",
        noticeTone: null,
      });

      const warnings = await refreshActivatedEnterpriseAgentViews({
        refreshAgents: load,
        refreshOffice: onOfficeChanged,
      });
      setDetailState((current) => ({
        ...current,
        notice: warnings.length
          ? `员工已启用，但${warnings.join("、")}。返回相应页面后可重新刷新。`
          : "员工已启用，并已同步到办公室。",
        noticeTone: warnings.length ? "warning" : null,
      }));
    } catch (error) {
      setActionError(error);
    } finally {
      setActivating(false);
    }
  };

  const closeDrawer = () => {
    if (submitting || saving || activating) return;
    detailRequestRef.current += 1;
    setDrawer(null);
    setSubmitError(null);
    setActionError(null);
    setDetailState({ phase: "idle", detail: null, etag: null, error: null, notice: null, noticeTone: null });
    hireCommandRef.current = null;
    configurationCommandRef.current = null;
    activationCommandRef.current = null;
  };

  return (
    <div className="eam-shell">
      <header className="eam-topbar">
        <button type="button" className="eam-brand" onClick={onBack} aria-label="返回企业数字办公大厅">
          <BrandLogo />
          <span>企业管理中心</span>
        </button>
        <div className="eam-topbar__context">
          <span className="eam-context-pill"><IconBuildingSkyscraper size={16} /><strong>{session.tenant.name}</strong></span>
          <span className="eam-user-context">
            <span className="eam-user-context__icon"><IconShieldLock size={17} /></span>
            <span><small>企业管理身份</small><strong>{session.user.name}</strong></span>
          </span>
        </div>
      </header>

      <aside className="eam-sidebar" aria-label="企业管理导航">
        <button type="button" className="eam-back-button" onClick={onBack}><IconArrowLeft size={18} /><span>返回办公大厅</span></button>
        <nav>
          <div className="eam-nav-group">
            <small>企业概况</small>
            <button type="button" disabled title="企业概览真实接口尚未接入"><IconBuildingCommunity size={18} /><span>企业概览</span><em>待接入</em></button>
          </div>
          <div className="eam-nav-group">
            <small>数字员工</small>
            <button className="is-active" type="button" aria-current="page"><IconBriefcase size={18} /><span>员工实例</span></button>
            {canHire ? <button type="button" disabled={state.phase !== "ready" || state.templates.length === 0} onClick={() => setDrawer({ type: "recruit" })}><IconPlus size={18} /><span>招聘员工</span></button> : null}
          </div>
          <div className="eam-nav-group">
            <small>知识与记忆</small>
            <button type="button" disabled title="企业知识真实接口尚未接入"><IconBook2 size={18} /><span>企业知识</span><em>待接入</em></button>
            <button type="button" disabled title="记忆治理真实接口尚未接入"><IconBrain size={18} /><span>记忆治理</span><em>待接入</em></button>
          </div>
          <div className="eam-nav-group">
            <small>组织与治理</small>
            <button type="button" disabled title="组织治理真实接口尚未接入"><IconUsers size={18} /><span>部门与成员</span><em>待接入</em></button>
            <button type="button" disabled title="审批中心真实接口尚未接入"><IconShieldCheck size={18} /><span>审批中心</span><em>待接入</em></button>
          </div>
          <div className="eam-nav-group">
            <small>模型与运营</small>
            <button type="button" disabled title="模型策略真实接口尚未接入"><IconSettings size={18} /><span>模型策略</span><em>待接入</em></button>
            <button type="button" disabled title="智点与费用真实接口尚未接入"><IconCoinYuan size={18} /><span>智点与费用</span><em>待接入</em></button>
            <button type="button" disabled title="任务监控真实接口尚未接入"><IconListCheck size={18} /><span>任务监控</span><em>待接入</em></button>
          </div>
        </nav>
      </aside>

      <main className="eam-main" aria-label="员工实例管理">
        <header className="eam-heading">
          <div>
            <small>数字员工 / 员工实例</small>
            <h1>员工实例</h1>
            <p>招聘平台已发布模板，为当前企业配置独立员工并在完成校验后启用。</p>
          </div>
          <div>
            <button type="button" aria-label="刷新员工实例" onClick={load} disabled={state.phase === "loading"}><IconRefresh size={16} />刷新</button>
            {canHire ? <button className="is-primary" type="button" disabled={state.phase !== "ready" || state.templates.length === 0} onClick={() => setDrawer({ type: "recruit" })}><IconPlus size={15} />招聘员工</button> : null}
          </div>
        </header>

        {state.phase === "loading" ? <div className="eam-state">正在读取{canHire ? "员工类型与" : ""}在编实例…</div> : null}
        {state.phase === "error" ? <div className="eam-state is-error"><strong>员工数据加载失败</strong><span>{errorMessage(state.error, "暂时无法读取员工数据。")}</span><button type="button" onClick={load}>重新加载</button></div> : null}
        {state.phase === "ready" ? (
          <>
            <section className="eam-stats" aria-label="数字员工状态统计">
              <article>
                <span className="eam-stat-icon"><IconBriefcase size={20} /></span>
                <span><small>可招聘类型</small><strong>{canHire ? stats.types : "—"}</strong><em>{canHire ? "当前权限可见模板" : "无招聘目录权限"}</em></span>
              </article>
              <article>
                <span className="eam-stat-icon"><IconUsers size={20} /></span>
                <span><small>员工实例</small><strong>{stats.agents}</strong><em>当前企业在编总数</em></span>
              </article>
              <article>
                <span className="eam-stat-icon is-success"><IconShieldCheck size={20} /></span>
                <span><small>已到岗</small><strong>{stats.active}</strong><em>可进入办公大厅工作</em></span>
              </article>
              <article>
                <span className="eam-stat-icon is-warning"><IconSettings size={20} /></span>
                <span><small>待配置</small><strong>{stats.pending}</strong><em>需完成配置与启用</em></span>
              </article>
            </section>

            {canHire ? <section className="eam-section">
              <div className="eam-section__title"><div><h2>可招聘员工模板</h2><p>来自点联平台已发布版本，招聘后形成当前企业独立实例。</p></div><small>平台官方模板</small></div>
              {state.templates.length ? <div className="eam-template-grid">{state.templates.map((item) => {
                const visual = visualFor(item.capabilityCode);
                return <button type="button" key={item.agentVersionId} onClick={() => setDrawer({ type: "recruit", templateId: item.agentVersionId })}><img src={visual.image} alt="" /><span><strong>{item.templateName}</strong><small>{visual.label} · v{item.version}</small></span><IconChevronRight size={16} /></button>;
              })}</div> : <div className="eam-empty eam-empty--compact">当前企业没有可招聘的员工模板。</div>}
            </section> : null}

            <section className="eam-section">
              <div className="eam-section__title"><div><h2>企业数字员工</h2><p>员工启用后进入办公大厅；每个实例拥有独立配置、知识范围与记忆边界。</p></div><small>共 {stats.agents} 位</small></div>
              {state.agents.length ? <div className="eam-agent-grid">{state.agents.map((item) => {
                const visual = visualFor(item.capabilityCode);
                const [label, tone] = statusPresentation(item.status);
                return (
                  <button className={`eam-agent-card status-${String(item.status).toLowerCase()}`} type="button" key={item.enterpriseAgentId} onClick={() => openAgent(item.enterpriseAgentId)}>
                    <span className="eam-agent-avatar"><img src={visual.image} alt="" /></span>
                    <span className="eam-agent-card__copy"><strong>{item.displayName}<em>{item.status === "DRAFT" ? "待配置" : "在编"}</em></strong><small>{visual.label}数字员工</small><span><StatusChip tone={tone}>{label}</StatusChip><b>{item.status === "DRAFT" ? "完成配置并启用后进入办公大厅" : `状态版本 ${item.stateVersion}`}</b></span></span>
                    <span className="eam-agent-card__action"><small>{item.employeeCode}</small><IconChevronRight size={15} /></span>
                  </button>
                );
              })}</div> : <div className="eam-empty"><IconBriefcase size={25} /><strong>还没有在编数字员工</strong><span>{canHire ? "先从上方员工模板招聘一位员工。" : "请联系有招聘权限的企业管理员。"}</span></div>}
            </section>
          </>
        ) : null}
      </main>

      {drawer?.type === "recruit" ? (
        <RecruitDrawer
          templates={state.templates}
          initialTemplateId={drawer.templateId}
          submitting={submitting}
          error={submitError}
          onClose={closeDrawer}
          onConfirm={hire}
        />
      ) : null}
      {drawer?.type === "agent" ? (
        <AgentConfigurationDrawer
          state={detailState}
          saving={saving}
          activating={activating}
          actionError={actionError}
          onClose={closeDrawer}
          onReload={() => loadDetail(drawer.agentId)}
          onSave={saveConfiguration}
          onActivate={activate}
        />
      ) : null}
    </div>
  );
}
