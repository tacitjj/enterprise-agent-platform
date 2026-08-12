import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  IconAlertTriangle,
  IconArrowLeft,
  IconArrowsExchange,
  IconBolt,
  IconCheck,
  IconKey,
  IconLogout,
  IconPlus,
  IconRefresh,
  IconRoute,
  IconSearch,
  IconServer,
  IconShieldCheck,
  IconX,
} from "@tabler/icons-react";
import { modelManagementApi } from "../api/modelManagementApi.js";
import { BrandLogo } from "../components/BrandLogo.jsx";
import { StatusChip } from "../components/StatusChip.jsx";
import {
  MODEL_CAPABILITIES,
  MODEL_PERMISSIONS,
  MODEL_PROTOCOLS,
  adaptModelDefinition,
  adaptModelDefinitionList,
  adaptPlatformDefaultRouteList,
  adaptRouteBinding,
  buildModelDefinitionPayload,
  buildPlatformRoutePayload,
  classifyModelManagementError,
  formatMicroCreditAsPoints,
  nextCommandIntent,
} from "./modelManagementAdapters.js";
import "./platform-model-management.css";

const EMPTY_FORM = Object.freeze({
  modelCode: "",
  displayName: "",
  providerCode: "",
  protocol: "OPENAI_COMPATIBLE",
  baseUrl: "",
  providerModelName: "",
  credentialRef: "",
  capabilityType: "TEXT_CHAT",
  temperature: "0.2",
  maxOutputTokens: "4096",
  inputRateMicroCreditPerMillionTokens: "0",
  outputRateMicroCreditPerMillionTokens: "0",
  reservationCeilingMicroCredit: "1000000",
});

function formatDateTime(value) {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return value || "—";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(timestamp);
}

function modelStatusTone(status) {
  if (status === "ACTIVE") return "success";
  if (status === "DISABLED") return "neutral";
  return "warning";
}

function errorDetail(error) {
  const kind = classifyModelManagementError(error);
  if (kind === "unauthenticated") return "登录会话已失效，请重新登录后继续。";
  if (kind === "forbidden") return "当前账号没有平台模型管理权限，本次操作未执行。";
  const trace = error?.traceId ? `（追踪号：${error.traceId}）` : "";
  return `${error?.detail ?? error?.message ?? "请求失败，请稍后重试。"}${trace}`;
}

function PageBoundary({ kind, error, onRetry }) {
  const content = {
    loading: ["正在读取模型配置", "只读取平台模型定义，不读取任何供应商密钥。"],
    unauthenticated: ["登录会话已失效", "请重新登录后进入点联平台运营中心。"],
    forbidden: ["没有平台模型读取权限", "需要 platform.model.read 权限；页面不会发起越权请求。"],
    error: ["模型配置暂时不可用", errorDetail(error)],
  }[kind] ?? ["模型配置暂时不可用", "请稍后重试。"];
  return (
    <section className={`pmm-boundary is-${kind}`} role={kind === "loading" ? "status" : "alert"}>
      <span aria-hidden="true">{kind === "loading" ? <IconRefresh size={25} /> : <IconAlertTriangle size={25} />}</span>
      <h2>{content[0]}</h2>
      <p>{content[1]}</p>
      {kind === "error" && onRetry ? <button type="button" onClick={onRetry}>重新加载</button> : null}
    </section>
  );
}

function MutationError({ error }) {
  if (!error) return null;
  return (
    <div className="pmm-form-error" role="alert">
      <IconAlertTriangle size={17} />
      <span><strong>操作未完成</strong>{errorDetail(error)}</span>
    </div>
  );
}

function DrawerFrame({ title, eyebrow, submitting, onClose, children, footer }) {
  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key === "Escape" && !submitting) onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, submitting]);

  return (
    <div className="pmm-layer" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !submitting) onClose();
    }}>
      <aside className="pmm-drawer" role="dialog" aria-modal="true" aria-label={title}>
        <header className="pmm-drawer__header">
          <div><small>{eyebrow}</small><h2>{title}</h2></div>
          <button type="button" aria-label={`关闭${title}`} disabled={submitting} onClick={onClose}><IconX size={20} /></button>
        </header>
        <div className="pmm-drawer__body">{children}</div>
        <footer className="pmm-drawer__footer">{footer}</footer>
      </aside>
    </div>
  );
}

function NewModelDrawer({ submitting, serverError, onClose, onSubmit }) {
  const [form, setForm] = useState(() => ({ ...EMPTY_FORM }));
  const [validationError, setValidationError] = useState(null);
  const update = (field, value) => {
    setForm((current) => ({ ...current, [field]: value }));
    setValidationError(null);
  };
  const submit = (event) => {
    event.preventDefault();
    try {
      onSubmit(buildModelDefinitionPayload(form));
    } catch (error) {
      setValidationError(error);
    }
  };

  return (
    <DrawerFrame
      title="新建模型配置"
      eyebrow="模型与 Provider / 新建定义"
      submitting={submitting}
      onClose={onClose}
      footer={<><button type="button" disabled={submitting} onClick={onClose}>取消</button><button className="is-primary" type="submit" form="pmm-new-model-form" disabled={submitting}>{submitting ? "保存中…" : "保存模型配置"}</button></>}
    >
      <form id="pmm-new-model-form" className="pmm-model-form" onSubmit={submit}>
        <div className="pmm-security-note">
          <IconKey size={18} />
          <span><strong>密钥不进入页面和数据库明文</strong><small>这里只提交 `env:DIANLIAN_MODEL_*` 环境变量引用；模型列表不会回显该引用，更不会读取真实 Key。</small></span>
        </div>
        <MutationError error={validationError ?? serverError} />
        <fieldset>
          <legend>模型身份</legend>
          <div className="pmm-form-grid">
            <label>模型编码<input autoFocus value={form.modelCode} onChange={(event) => update("modelCode", event.target.value)} placeholder="例如 GENERIC_CHAT_V1" /></label>
            <label>显示名称<input value={form.displayName} onChange={(event) => update("displayName", event.target.value)} placeholder="企业用户可识别的名称" /></label>
            <label>供应商编码<input value={form.providerCode} onChange={(event) => update("providerCode", event.target.value)} placeholder="例如 PROVIDER_X" /></label>
            <label>供应商模型名称<input value={form.providerModelName} onChange={(event) => update("providerModelName", event.target.value)} placeholder="供应商接口使用的 model 名称" /></label>
            <label>能力类型<select value={form.capabilityType} onChange={(event) => update("capabilityType", event.target.value)}>{MODEL_CAPABILITIES.map((item) => <option key={item.value} value={item.value}>{item.label} · {item.value}</option>)}</select></label>
            <label>协议<select value={form.protocol} onChange={(event) => update("protocol", event.target.value)}>{MODEL_PROTOCOLS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select><small>当前 Java 运行时通过 LangChain4j 支持 OpenAI Compatible 协议，不绑定具体供应商。</small></label>
          </div>
        </fieldset>
        <fieldset>
          <legend>连接与生成参数</legend>
          <div className="pmm-form-grid">
            <label className="is-full">HTTPS 接口地址<input value={form.baseUrl} onChange={(event) => update("baseUrl", event.target.value)} placeholder="https://models.example.com/v1" inputMode="url" /><small>服务端还会执行 Provider 域名白名单校验。</small></label>
            <label className="is-full">密钥环境变量引用<input value={form.credentialRef} onChange={(event) => update("credentialRef", event.target.value)} placeholder="env:DIANLIAN_MODEL_PROVIDER_X_KEY" autoComplete="off" spellCheck="false" /><small>禁止粘贴真实 API Key；部署环境负责注入对应变量。</small></label>
            <label>Temperature<input value={form.temperature} onChange={(event) => update("temperature", event.target.value)} inputMode="decimal" /></label>
            <label>最大输出 Token<input value={form.maxOutputTokens} onChange={(event) => update("maxOutputTokens", event.target.value)} inputMode="numeric" /></label>
          </div>
        </fieldset>
        <fieldset>
          <legend>成本与预占</legend>
          <p className="pmm-fieldset-copy">以下三项按后端契约提交 JSON 字符串，不经过浮点数转换。1 智点 = 1,000,000 微智点。</p>
          <div className="pmm-form-grid">
            <label>输入费率（微智点 / 百万 Token）<input value={form.inputRateMicroCreditPerMillionTokens} onChange={(event) => update("inputRateMicroCreditPerMillionTokens", event.target.value)} inputMode="numeric" /></label>
            <label>输出费率（微智点 / 百万 Token）<input value={form.outputRateMicroCreditPerMillionTokens} onChange={(event) => update("outputRateMicroCreditPerMillionTokens", event.target.value)} inputMode="numeric" /></label>
            <label className="is-full">单次预占上限（微智点）<input value={form.reservationCeilingMicroCredit} onChange={(event) => update("reservationCeilingMicroCredit", event.target.value)} inputMode="numeric" /></label>
          </div>
        </fieldset>
      </form>
    </DrawerFrame>
  );
}

function RouteDrawer({ models, initialModel, submitting, serverError, onClose, onSubmit }) {
  const [capabilityType, setCapabilityType] = useState(initialModel?.capabilityType || "TEXT_CHAT");
  const eligibleModels = useMemo(
    () => models.filter((model) => model.status === "ACTIVE" && model.capabilityType === capabilityType),
    [capabilityType, models],
  );
  const [modelDefinitionId, setModelDefinitionId] = useState(initialModel?.modelDefinitionId || "");

  useEffect(() => {
    if (!eligibleModels.some((model) => model.modelDefinitionId === modelDefinitionId)) {
      setModelDefinitionId(eligibleModels[0]?.modelDefinitionId ?? "");
    }
  }, [eligibleModels, modelDefinitionId]);

  const selectedModel = eligibleModels.find((model) => model.modelDefinitionId === modelDefinitionId);
  return (
    <DrawerFrame
      title="切换平台默认模型"
      eyebrow="模型路由 / 平台默认"
      submitting={submitting}
      onClose={onClose}
      footer={<><button type="button" disabled={submitting} onClick={onClose}>取消</button><button className="is-primary" type="button" disabled={submitting || !selectedModel} onClick={() => onSubmit(capabilityType, buildPlatformRoutePayload(modelDefinitionId))}>{submitting ? "切换中…" : "确认切换"}</button></>}
    >
      <div className="pmm-route-warning">
        <IconArrowsExchange size={19} />
        <span><strong>影响继承平台默认策略的数字员工</strong><small>切换仅绑定同一能力类型的可用模型。已配置企业级或员工级覆盖的路由不在本次操作范围内。</small></span>
      </div>
      <MutationError error={serverError} />
      <div className="pmm-route-form">
        <label>能力类型<select value={capabilityType} onChange={(event) => setCapabilityType(event.target.value)}>{MODEL_CAPABILITIES.map((item) => <option key={item.value} value={item.value}>{item.label} · {item.value}</option>)}</select></label>
        <label>默认模型<select value={modelDefinitionId} onChange={(event) => setModelDefinitionId(event.target.value)} disabled={!eligibleModels.length}><option value="">请选择可用模型</option>{eligibleModels.map((model) => <option key={model.modelDefinitionId} value={model.modelDefinitionId}>{model.displayName} · {model.providerCode} · v{model.configurationVersion}</option>)}</select></label>
      </div>
      {selectedModel ? (
        <section className="pmm-route-target">
          <span><small>目标模型</small><strong>{selectedModel.displayName}</strong><em>{selectedModel.modelCode} · {selectedModel.providerModelName}</em></span>
          <StatusChip tone="success">可用</StatusChip>
        </section>
      ) : <div className="pmm-inline-empty">该能力下没有可用于路由的 ACTIVE 模型，请先新建模型配置。</div>}
    </DrawerFrame>
  );
}

export function PlatformModelManagementPage({
  session,
  dataSource = modelManagementApi,
  onBack,
  onNavigateTemplates,
  onLogout,
}) {
  const permissions = session?.permissions ?? [];
  const canRead = permissions.includes(MODEL_PERMISSIONS.READ);
  const canManage = permissions.includes(MODEL_PERMISSIONS.MANAGE);
  const [state, setState] = useState(() => ({
    phase: canRead ? "loading" : "forbidden",
    models: [],
    routes: [],
    error: null,
  }));
  const [query, setQuery] = useState("");
  const [capabilityFilter, setCapabilityFilter] = useState("ALL");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [drawer, setDrawer] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [mutationError, setMutationError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [lastRoute, setLastRoute] = useState(null);
  const definitionIntentRef = useRef(null);
  const routeIntentRef = useRef(null);

  const load = useCallback(async () => {
    if (!canRead) {
      setState({ phase: "forbidden", models: [], routes: [], error: null });
      return;
    }
    setState((current) => ({ ...current, phase: "loading", error: null }));
    try {
      const [definitionsPayload, routesPayload] = await Promise.all([
        dataSource.listModelDefinitions(),
        dataSource.listPlatformDefaultRoutes(),
      ]);
      setState({
        phase: "ready",
        models: adaptModelDefinitionList(definitionsPayload),
        routes: adaptPlatformDefaultRouteList(routesPayload),
        error: null,
      });
    } catch (error) {
      setState({ phase: classifyModelManagementError(error), models: [], routes: [], error });
    }
  }, [canRead, dataSource]);

  useEffect(() => { load(); }, [load]);

  const models = state.models;
  const routes = state.routes;
  const visibleModels = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return models.filter((model) => {
      if (capabilityFilter !== "ALL" && model.capabilityType !== capabilityFilter) return false;
      if (statusFilter !== "ALL" && model.status !== statusFilter) return false;
      if (!normalizedQuery) return true;
      return [model.displayName, model.modelCode, model.providerCode, model.providerModelName]
        .some((value) => String(value ?? "").toLowerCase().includes(normalizedQuery));
    });
  }, [capabilityFilter, models, query, statusFilter]);

  const stats = useMemo(() => ({
    definitions: models.length,
    active: models.filter((model) => model.status === "ACTIVE").length,
    providers: new Set(models.map((model) => model.providerCode).filter(Boolean)).size,
    capabilities: new Set(models.map((model) => model.capabilityType).filter(Boolean)).size,
  }), [models]);

  const closeDrawer = useCallback(() => {
    if (submitting) return;
    setDrawer(null);
    setMutationError(null);
    definitionIntentRef.current = null;
    routeIntentRef.current = null;
  }, [submitting]);

  const registerModel = async (payload) => {
    const intent = nextCommandIntent(definitionIntentRef.current, "model-definition", payload);
    definitionIntentRef.current = intent;
    setSubmitting(true);
    setMutationError(null);
    try {
      const result = await dataSource.registerModelDefinition(payload, { idempotencyKey: intent.key });
      const created = adaptModelDefinition(result.resource);
      definitionIntentRef.current = null;
      setDrawer(null);
      setNotice({
        tone: "success",
        text: result.replayed
          ? `模型“${created.displayName}”已按原幂等请求返回，未重复创建。`
          : `模型“${created.displayName}”已创建，可继续设置平台默认路由。`,
      });
      await load();
    } catch (error) {
      setMutationError(error);
    } finally {
      setSubmitting(false);
    }
  };

  const switchRoute = async (capabilityType, payload) => {
    const intentPayload = { capabilityType, ...payload };
    const intent = nextCommandIntent(routeIntentRef.current, "model-route", intentPayload);
    routeIntentRef.current = intent;
    setSubmitting(true);
    setMutationError(null);
    try {
      const result = await dataSource.setPlatformDefaultRoute(capabilityType, payload, { idempotencyKey: intent.key });
      const binding = adaptRouteBinding(result.resource);
      routeIntentRef.current = null;
      setLastRoute(binding);
      setDrawer(null);
      setNotice({
        tone: "success",
        text: result.replayed
          ? `${binding.capabilityLabel}默认路由已按原幂等请求返回，未重复写入。`
          : `${binding.capabilityLabel}默认路由已切换，状态版本 ${binding.stateVersion}。`,
      });
      await load();
    } catch (error) {
      setMutationError(error);
    } finally {
      setSubmitting(false);
    }
  };

  const openCreate = () => {
    setMutationError(null);
    setDrawer({ mode: "create" });
  };
  const openRoute = (model = null) => {
    setMutationError(null);
    setDrawer({ mode: "route", model });
  };

  return (
    <div className="pmm-shell">
      <header className="pmm-topbar">
        {onBack ? <button type="button" className="pmm-brand" onClick={onBack}><BrandLogo /><span>平台运营中心</span></button> : <div className="pmm-brand"><BrandLogo /><span>平台运营中心</span></div>}
        <div className="pmm-topbar__identity"><strong>{session?.user?.name ?? "平台管理员"}</strong>{onLogout ? <button type="button" onClick={onLogout}><IconLogout size={17} />退出</button> : null}</div>
      </header>
      <aside className="pmm-sidebar">
        {onBack ? <button type="button" className="pmm-back" onClick={onBack}><IconArrowLeft size={18} /><span>返回上一页</span></button> : null}
        <small>模型与 Provider</small>
        <nav aria-label="平台模型管理导航">
          {onNavigateTemplates ? <button type="button" onClick={onNavigateTemplates}><IconArrowLeft size={19} /><span>官方员工模板</span></button> : null}
          <button className="is-active" type="button"><IconServer size={19} /><span>官方模型</span></button>
        </nav>
        <div className="pmm-sidebar__note"><IconShieldCheck size={18} /><span><strong>平台安全边界</strong><small>只管理模型元数据、费率和环境变量引用；不展示真实密钥，也不读取企业会话、知识或记忆。</small></span></div>
      </aside>
      <main className="pmm-main">
        <header className="pmm-heading">
          <div><small>模型与 Provider / 官方模型</small><h1>官方模型配置</h1><p>按能力维护供应商无关的模型定义，并受控切换平台默认路由。</p></div>
          <div><button type="button" onClick={load} disabled={state.phase === "loading"}><IconRefresh size={17} />刷新</button>{canManage ? <><button type="button" onClick={() => openRoute()}><IconRoute size={17} />切换默认路由</button><button className="is-primary" type="button" onClick={openCreate}><IconPlus size={17} />新建模型配置</button></> : null}</div>
        </header>

        {!canManage && canRead ? <div className="pmm-readonly"><IconShieldCheck size={16} />当前账号只有 platform.model.read 权限；可查看配置，但不能新建模型或切换默认路由。</div> : null}
        {notice ? <div className={`pmm-notice is-${notice.tone}`} role="status"><IconCheck size={17} /><span>{notice.text}</span><button type="button" aria-label="关闭提示" onClick={() => setNotice(null)}><IconX size={16} /></button></div> : null}

        {state.phase !== "ready" ? <PageBoundary kind={state.phase} error={state.error} onRetry={load} /> : (
          <>
            <section className="pmm-stats" aria-label="模型配置统计">
              <span><small>模型配置版本</small><strong>{stats.definitions}</strong></span>
              <span><small>当前可用</small><strong>{stats.active}</strong></span>
              <span><small>供应商</small><strong>{stats.providers}</strong></span>
              <span><small>已覆盖能力</small><strong>{stats.capabilities}</strong></span>
            </section>

            <section className="pmm-route-status">
              <div><IconBolt size={19} /><span><strong>平台默认路由</strong><small>展示后端当前 ACTIVE 路由；切换后继承平台默认策略的数字员工将在后续新调用中使用新版本。</small></span></div>
              <div className="pmm-route-list">
                {routes.length ? routes.map((route) => {
                  const model = models.find((item) => item.modelDefinitionId === route.modelDefinitionId);
                  return <span key={route.routeBindingId}><small>{route.capabilityLabel}</small><strong>{model?.displayName ?? route.modelDefinitionId}</strong><em>状态版本 {route.stateVersion}</em></span>;
                }) : <span className="pmm-route-unknown">尚未配置平台默认路由</span>}
              </div>
              {lastRoute ? <div className="pmm-route-receipt"><small>最近一次切换回执</small><strong>{lastRoute.capabilityLabel} · 状态版本 {lastRoute.stateVersion}</strong><span>{formatDateTime(lastRoute.createdAt)}</span></div> : null}
            </section>

            <section className="pmm-panel">
              <div className="pmm-panel__heading">
                <div><h2>模型定义</h2><p>配置版本来自真实接口；费率始终按字符串契约处理。</p></div>
                <div className="pmm-filters">
                  <label className="pmm-search"><IconSearch size={16} /><input aria-label="搜索模型配置" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索模型或供应商" /></label>
                  <select aria-label="按能力筛选" value={capabilityFilter} onChange={(event) => setCapabilityFilter(event.target.value)}><option value="ALL">全部能力</option>{MODEL_CAPABILITIES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select>
                  <select aria-label="按状态筛选" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="ALL">全部状态</option><option value="ACTIVE">可用</option><option value="DISABLED">已停用</option></select>
                </div>
              </div>

              {visibleModels.length ? (
                <div className="pmm-table" role="table" aria-label="官方模型配置列表">
                  <div className="pmm-table__head" role="row"><span>模型</span><span>供应商 / 协议</span><span>能力</span><span>配置版本</span><span>生成参数</span><span>费率（智点）</span><span>状态</span><span>操作</span></div>
                  {visibleModels.map((model) => (
                    <div className="pmm-table__row" role="row" key={model.modelDefinitionId}>
                      <span><strong>{model.displayName}</strong><small>{model.modelCode || "未返回编码"} · {model.providerModelName || "未返回 provider model"}</small></span>
                      <span><strong>{model.providerCode || "未返回"}</strong><small>{model.protocolLabel}</small></span>
                      <span><strong>{model.capabilityLabel}</strong><small>{model.capabilityType || "—"}</small></span>
                      <span><strong>v{model.configurationVersion ?? "—"}</strong><small>{formatDateTime(model.createdAt)}</small></span>
                      <span><strong>T {String(model.temperature ?? "—")}</strong><small>最多 {String(model.maxOutputTokens ?? "—")} Token</small></span>
                      <span title={`输入 ${model.inputRateMicroCreditPerMillionTokens ?? "契约异常"} / 输出 ${model.outputRateMicroCreditPerMillionTokens ?? "契约异常"} 微智点`}><strong>入 {formatMicroCreditAsPoints(model.inputRateMicroCreditPerMillionTokens)}</strong><small>出 {formatMicroCreditAsPoints(model.outputRateMicroCreditPerMillionTokens)} · 预占 {formatMicroCreditAsPoints(model.reservationCeilingMicroCredit)}</small></span>
                      <span><StatusChip tone={modelStatusTone(model.status)}>{model.statusLabel}</StatusChip>{model.contractIssues.length ? <small className="pmm-contract-warning" title={model.contractIssues.join("；")}><IconAlertTriangle size={13} />响应契约异常</small> : null}</span>
                      <span>{canManage && model.status === "ACTIVE" && MODEL_CAPABILITIES.some((item) => item.value === model.capabilityType) ? <button type="button" onClick={() => openRoute(model)}>设为默认</button> : <em>{canManage ? "不可路由" : "只读"}</em>}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="pmm-empty">
                  <IconServer size={27} />
                  <strong>{models.length ? "没有匹配的模型配置" : "尚未创建模型配置"}</strong>
                  <p>{models.length ? "请调整搜索或筛选条件。" : "先创建一个供应商无关的模型定义，再按能力设置平台默认路由。"}</p>
                  {!models.length && canManage ? <button type="button" onClick={openCreate}><IconPlus size={16} />新建模型配置</button> : null}
                </div>
              )}
            </section>
          </>
        )}
      </main>

      {drawer?.mode === "create" ? <NewModelDrawer submitting={submitting} serverError={mutationError} onClose={closeDrawer} onSubmit={registerModel} /> : null}
      {drawer?.mode === "route" ? <RouteDrawer models={models} initialModel={drawer.model} submitting={submitting} serverError={mutationError} onClose={closeDrawer} onSubmit={switchRoute} /> : null}
    </div>
  );
}
