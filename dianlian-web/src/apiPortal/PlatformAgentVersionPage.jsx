import { useEffect, useMemo, useRef, useState } from "react";
import {
  IconArrowLeft,
  IconBook2,
  IconCheck,
  IconChevronRight,
  IconCode,
  IconFileDescription,
  IconLogout,
  IconPlus,
  IconRefresh,
  IconRoute,
  IconSearch,
  IconServer,
  IconShieldCheck,
  IconUsersGroup,
  IconX,
} from "@tabler/icons-react";
import { BrandLogo } from "../components/BrandLogo.jsx";
import { StatusChip } from "../components/StatusChip.jsx";
import "./platform-agent-version.css";

const MICRO_CREDITS_PER_POINT = 1_000_000n;
const MAX_MICRO_CREDIT = 9_223_372_036_854_775_807n;
const CAPABILITY_PATTERN = /^[A-Z][A-Z0-9_]{1,63}$/;
const STABLE_CODE_PATTERN = /^[A-Za-z][A-Za-z0-9._-]*$/;
const SCHEMA_ID_PATTERN = /^[a-z][a-z0-9_.-]{1,127}$/;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const capabilityPresentation = Object.freeze({
  GRAPHIC_DESIGN: { label: "平面出图", image: "/assets/employees/graphic-designer.png" },
  CONTRACT_REVIEW: { label: "法务合同审核", image: "/assets/employees/contract-reviewer.png" },
  QUOTATION: { label: "报价", image: "/assets/employees/quotation-specialist.png" },
});

const executorLabels = Object.freeze({
  MODEL: "模型执行",
  RETRIEVAL: "知识检索",
  RULE_ENGINE: "规则引擎",
  TOOL: "工具调用",
  HUMAN_CHECKPOINT: "人工确认",
  SUBTASK: "子任务",
});

function visualFor(capabilityCode) {
  return capabilityPresentation[capabilityCode] ?? {
    label: capabilityCode || "待定义能力",
    image: "/assets/brand/dianlian-symbol.png",
  };
}

function newIdempotencyKey() {
  return `publish:${crypto.randomUUID()}`;
}

function formatPoints(microCredit) {
  try {
    const value = BigInt(microCredit);
    const whole = value / MICRO_CREDITS_PER_POINT;
    const fraction = (value % MICRO_CREDITS_PER_POINT).toString().padStart(6, "0").replace(/0+$/, "");
    return fraction ? `${whole}.${fraction}` : whole.toString();
  } catch {
    return "—";
  }
}

function pointInputToMicroCredit(value) {
  const normalized = String(value ?? "").trim();
  if (!/^(0|[1-9]\d*)(\.\d{1,6})?$/.test(normalized)) {
    throw new Error("预计智点必须是正数，最多保留 6 位小数。");
  }
  const [whole, fraction = ""] = normalized.split(".");
  const microCredit = (BigInt(whole) * MICRO_CREDITS_PER_POINT) + BigInt(fraction.padEnd(6, "0"));
  if (microCredit < 1n || microCredit > MAX_MICRO_CREDIT) {
    throw new Error("预计智点超出后端支持的正整数范围。");
  }
  return microCredit.toString();
}

function parseJsonObject(value, label) {
  let parsed;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error(`${label}不是合法 JSON。`);
  }
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error(`${label}必须是 JSON 对象。`);
  }
  return parsed;
}

function parseExecutionSteps(value) {
  let parsed;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error("执行步骤不是合法 JSON。");
  }
  if (!Array.isArray(parsed) || parsed.length === 0) {
    throw new Error("执行步骤必须是至少包含一项的 JSON 数组。");
  }
  return parsed;
}

function required(value, label) {
  const normalized = String(value ?? "").trim();
  if (!normalized) throw new Error(`请填写${label}。`);
  return normalized;
}

function buildPublishPayload(form) {
  const templateCode = required(form.templateCode, "模板编码");
  const capabilityCode = required(form.capabilityCode, "能力编码").toUpperCase();
  const schemaId = required(form.inputSchemaId, "输入 Schema ID");
  const executionTemplateCode = required(form.executionTemplateCode, "执行模板编码");
  if (!STABLE_CODE_PATTERN.test(templateCode)) throw new Error("模板编码只能包含字母、数字、点、下划线和短横线，且必须以字母开头。");
  if (!CAPABILITY_PATTERN.test(capabilityCode)) throw new Error("能力编码必须是大写字母开头的大写下划线编码。");
  if (!SCHEMA_ID_PATTERN.test(schemaId)) throw new Error("输入 Schema ID 必须以小写字母开头，只能包含小写字母、数字、点、下划线和短横线。");
  if (!STABLE_CODE_PATTERN.test(executionTemplateCode)) throw new Error("执行模板编码不符合稳定编码规则。");

  const visibilityMode = required(form.visibilityMode, "企业可见范围");
  const tenantIds = visibilityMode === "ALLOWLIST"
    ? [...new Set(form.tenantIds.split(/[\s,，]+/).map((item) => item.trim()).filter(Boolean))]
    : [];
  if (visibilityMode === "ALLOWLIST" && tenantIds.length === 0) throw new Error("指定企业可见时，至少填写一个企业 ID。");
  if (tenantIds.some((tenantId) => !UUID_PATTERN.test(tenantId))) throw new Error("企业 ID 必须使用标准 UUID 格式。");

  return {
    templateCode,
    templateName: required(form.templateName, "模板名称"),
    templateDescription: required(form.templateDescription, "模板说明"),
    version: required(form.version, "发布版本"),
    capabilityCode,
    inputSchema: {
      schemaId,
      schemaVersion: required(form.inputSchemaVersion, "输入 Schema 版本"),
      jsonSchema: parseJsonObject(form.inputSchemaJson, "输入 Schema"),
    },
    executionTemplate: {
      templateCode: executionTemplateCode,
      version: required(form.executionTemplateVersion, "执行模板版本"),
      steps: parseExecutionSteps(form.executionStepsJson),
    },
    pointEstimateMicroCredit: pointInputToMicroCredit(form.pointEstimate),
    enterpriseVisibility: { mode: visibilityMode, tenantIds },
  };
}

function emptyPublishForm() {
  return {
    templateCode: "",
    templateName: "",
    templateDescription: "",
    version: "",
    capabilityCode: "",
    inputSchemaId: "",
    inputSchemaVersion: "",
    inputSchemaJson: "",
    executionTemplateCode: "",
    executionTemplateVersion: "",
    executionStepsJson: "",
    pointEstimate: "",
    visibilityMode: "",
    tenantIds: "",
  };
}

function publishFormFromVersion(version) {
  if (!version) return emptyPublishForm();
  return {
    templateCode: version.templateCode,
    templateName: version.templateName,
    templateDescription: version.templateDescription,
    version: "",
    capabilityCode: version.capabilityCode,
    inputSchemaId: version.inputSchema.schemaId,
    inputSchemaVersion: version.inputSchema.schemaVersion,
    inputSchemaJson: JSON.stringify(version.inputSchema.jsonSchema, null, 2),
    executionTemplateCode: version.executionTemplate.templateCode,
    executionTemplateVersion: version.executionTemplate.version,
    executionStepsJson: JSON.stringify(version.executionTemplate.steps, null, 2),
    pointEstimate: formatPoints(version.pointEstimateMicroCredit),
    visibilityMode: version.enterpriseVisibility.mode,
    tenantIds: version.enterpriseVisibility.tenantIds.join("\n"),
  };
}

function visibilityLabel(visibility) {
  return visibility.mode === "ALL" ? "全部企业可见" : `指定 ${visibility.tenantIds.length} 家企业`;
}

function publishedAtLabel(value) {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(timestamp);
}

function DetailDrawer({ version, canPublish, onClose, onUseAsBase }) {
  const visual = visualFor(version.capabilityCode);
  const schemaProperties = Object.keys(version.inputSchema?.jsonSchema?.properties ?? {});
  const steps = version.executionTemplate?.steps ?? [];
  useEffect(() => {
    const onKeyDown = (event) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div className="ptm-layer" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <aside className="ptm-drawer" role="dialog" aria-modal="true" aria-label={`${version.templateName}版本详情`}>
        <header className="ptm-drawer__header">
          <div><small>官方模板 · 已发布快照</small><h2>{version.templateName}</h2></div>
          <button type="button" aria-label="关闭详情" onClick={onClose}><IconX size={20} /></button>
        </header>
        <div className="ptm-drawer__body">
          <section className="ptm-version-hero">
            <img src={visual.image} alt="" />
            <div><span>{visual.label}</span><strong>{version.templateCode}</strong><p>{version.templateDescription}</p></div>
            <StatusChip tone={version.status === "PUBLISHED" ? "success" : "neutral"}>{version.status === "PUBLISHED" ? "已发布" : "已退役"}</StatusChip>
          </section>
          <section className="ptm-fact-grid">
            <span><small>模板版本</small><strong>{version.version}</strong></span>
            <span><small>预计消耗</small><strong>{formatPoints(version.pointEstimateMicroCredit)} 智点</strong></span>
            <span><small>企业范围</small><strong>{visibilityLabel(version.enterpriseVisibility)}</strong></span>
            <span><small>发布时间</small><strong>{publishedAtLabel(version.publishedAt)}</strong></span>
          </section>
          <section className="ptm-detail-section">
            <div className="ptm-detail-section__title"><IconCode size={18} /><div><strong>输入契约</strong><small>{version.inputSchema.schemaId} · {version.inputSchema.schemaVersion}</small></div></div>
            {schemaProperties.length ? <div className="ptm-token-list">{schemaProperties.map((field) => <span key={field}>{field}</span>)}</div> : <p className="ptm-muted">该 Schema 未声明 properties。</p>}
          </section>
          <section className="ptm-detail-section">
            <div className="ptm-detail-section__title"><IconRoute size={18} /><div><strong>执行模板</strong><small>{version.executionTemplate.templateCode} · {version.executionTemplate.version}</small></div></div>
            <ol className="ptm-step-list">{steps.map((step, index) => (
              <li key={step.stepKey}><b>{index + 1}</b><div><strong>{step.title}</strong><span>{executorLabels[step.executorType] ?? step.executorType}{step.humanCheckpoint ? " · 人工检查点" : ""}</span></div></li>
            ))}</ol>
          </section>
          {version.enterpriseVisibility.mode === "ALLOWLIST" ? (
            <section className="ptm-detail-section"><div className="ptm-detail-section__title"><IconUsersGroup size={18} /><div><strong>可见企业 ID</strong><small>平台仅展示授权标识，不读取企业业务内容</small></div></div><div className="ptm-id-list">{version.enterpriseVisibility.tenantIds.map((id) => <code key={id}>{id}</code>)}</div></section>
          ) : null}
        </div>
        <footer className="ptm-drawer__footer"><button type="button" onClick={onClose}>关闭</button>{canPublish ? <button className="is-primary" type="button" onClick={() => onUseAsBase(version)}>复制配置发布新版本</button> : null}</footer>
      </aside>
    </div>
  );
}

function PublishDrawer({ baseVersion, submitting, error, onClose, onPublish }) {
  const [form, setForm] = useState(() => publishFormFromVersion(baseVersion));
  const [formError, setFormError] = useState(null);
  const update = (field, value) => setForm((current) => ({ ...current, [field]: value }));
  useEffect(() => {
    const onKeyDown = (event) => event.key === "Escape" && !submitting && onClose();
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, submitting]);

  const submit = () => {
    try {
      setFormError(null);
      onPublish(buildPublishPayload(form));
    } catch (validationError) {
      setFormError(validationError.message);
    }
  };

  return (
    <div className="ptm-layer" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && !submitting && onClose()}>
      <aside className="ptm-drawer ptm-drawer--wide" role="dialog" aria-modal="true" aria-label="发布官方员工模板版本">
        <header className="ptm-drawer__header">
          <div><small>{baseVersion ? `复制 ${baseVersion.version} 的冻结配置` : "创建新的官方模板版本"}</small><h2>发布官方版本</h2></div>
          <button type="button" aria-label="关闭发布面板" disabled={submitting} onClick={onClose}><IconX size={20} /></button>
        </header>
        <div className="ptm-drawer__body ptm-publish-form">
          <p className="ptm-direct-publish"><IconShieldCheck size={18} />当前接口会直接形成已发布版本，不包含草稿、灰度和回滚。请确认全部契约后再提交。</p>
          {formError || error ? <p className="ptm-error" role="alert">{formError ?? error}</p> : null}
          <fieldset>
            <legend>岗位与版本</legend>
            <div className="ptm-form-grid">
              <label><span>模板编码</span><input maxLength={64} value={form.templateCode} onChange={(event) => update("templateCode", event.target.value)} placeholder="例如 graphic-designer" /></label>
              <label><span>模板名称</span><input maxLength={100} value={form.templateName} onChange={(event) => update("templateName", event.target.value)} placeholder="例如 平面出图专员" /></label>
              <label><span>发布版本</span><input maxLength={32} value={form.version} onChange={(event) => update("version", event.target.value)} placeholder="例如 v1.0.0" /></label>
              <label><span>能力编码</span><input maxLength={64} list="ptm-capability-codes" value={form.capabilityCode} onChange={(event) => update("capabilityCode", event.target.value.toUpperCase())} placeholder="例如 GRAPHIC_DESIGN" /><datalist id="ptm-capability-codes">{Object.keys(capabilityPresentation).map((code) => <option key={code} value={code} />)}</datalist></label>
              <label className="is-full"><span>模板说明</span><textarea maxLength={500} value={form.templateDescription} onChange={(event) => update("templateDescription", event.target.value)} placeholder="说明员工边界、主要成果和适用场景" /></label>
              <label><span>预计智点</span><input inputMode="decimal" value={form.pointEstimate} onChange={(event) => update("pointEstimate", event.target.value)} placeholder="例如 12.5" /><small>页面输入智点，提交时精确换算为最小整数单位。</small></label>
              <label><span>企业可见范围</span><select value={form.visibilityMode} onChange={(event) => update("visibilityMode", event.target.value)}><option value="">请选择</option><option value="ALL">全部企业</option><option value="ALLOWLIST">指定企业</option></select></label>
              {form.visibilityMode === "ALLOWLIST" ? <label className="is-full"><span>企业 ID</span><textarea value={form.tenantIds} onChange={(event) => update("tenantIds", event.target.value)} placeholder="每行一个 UUID，也可用逗号分隔" /></label> : null}
            </div>
          </fieldset>
          <fieldset>
            <legend>输入契约</legend>
            <div className="ptm-form-grid">
              <label><span>Schema ID</span><input maxLength={128} value={form.inputSchemaId} onChange={(event) => update("inputSchemaId", event.target.value)} /></label>
              <label><span>Schema 版本</span><input maxLength={32} value={form.inputSchemaVersion} onChange={(event) => update("inputSchemaVersion", event.target.value)} /></label>
              <label className="is-full"><span>JSON Schema</span><textarea className="is-code" value={form.inputSchemaJson} onChange={(event) => update("inputSchemaJson", event.target.value)} placeholder={'{\n  "type": "object",\n  "properties": {}\n}'} /></label>
            </div>
          </fieldset>
          <fieldset>
            <legend>执行模板</legend>
            <div className="ptm-form-grid">
              <label><span>执行模板编码</span><input maxLength={96} value={form.executionTemplateCode} onChange={(event) => update("executionTemplateCode", event.target.value)} /></label>
              <label><span>执行模板版本</span><input maxLength={32} value={form.executionTemplateVersion} onChange={(event) => update("executionTemplateVersion", event.target.value)} /></label>
              <label className="is-full"><span>执行步骤 JSON</span><textarea className="is-code is-tall" value={form.executionStepsJson} onChange={(event) => update("executionStepsJson", event.target.value)} placeholder={'[\n  {\n    "stepKey": "...",\n    "title": "...",\n    "executorType": "MODEL",\n    "dependsOn": [],\n    "inputSchemaRef": null,\n    "outputSchemaRef": null,\n    "humanCheckpoint": false\n  }\n]'} /></label>
            </div>
          </fieldset>
        </div>
        <footer className="ptm-drawer__footer"><button type="button" disabled={submitting} onClick={onClose}>取消</button><button className="is-primary" type="button" disabled={submitting} onClick={submit}>{submitting ? "正在发布…" : "确认并直接发布"}</button></footer>
      </aside>
    </div>
  );
}

function latestTemplateGroups(versions) {
  const sorted = [...versions].sort((left, right) => Date.parse(right.publishedAt) - Date.parse(left.publishedAt));
  const groups = new Map();
  for (const version of sorted) {
    const group = groups.get(version.templateId) ?? { latest: version, versions: [] };
    group.versions.push(version);
    groups.set(version.templateId, group);
  }
  return [...groups.values()];
}

export function PlatformAgentVersionPage({
  session,
  dataSource,
  canPublish,
  onBack,
  onNavigateModels,
  onLogout,
}) {
  const [state, setState] = useState({ phase: "loading", versions: [], error: null });
  const [search, setSearch] = useState("");
  const [drawer, setDrawer] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const publishCommandRef = useRef(null);

  const load = async () => {
    setState((current) => ({ ...current, phase: "loading", error: null }));
    try {
      const response = await dataSource.listPlatformVersions();
      setState({ phase: "ready", versions: response?.items ?? [], error: null });
    } catch (error) {
      setState((current) => ({ ...current, phase: "error", error }));
    }
  };

  useEffect(() => { load(); }, [dataSource]);

  const groups = useMemo(() => latestTemplateGroups(state.versions), [state.versions]);
  const normalizedSearch = search.trim().toLowerCase();
  const visibleGroups = groups.filter(({ latest }) => !normalizedSearch || [latest.templateName, latest.templateCode, latest.capabilityCode].some((value) => value.toLowerCase().includes(normalizedSearch)));
  const visibleVersions = state.versions.filter((version) => !normalizedSearch || [version.templateName, version.templateCode, version.capabilityCode, version.version].some((value) => value.toLowerCase().includes(normalizedSearch)));
  const stats = useMemo(() => ({
    templates: groups.length,
    versions: state.versions.length,
    active: state.versions.filter((item) => item.status === "PUBLISHED").length,
    restricted: state.versions.filter((item) => item.enterpriseVisibility.mode === "ALLOWLIST").length,
  }), [groups.length, state.versions]);

  const publish = async (payload) => {
    if (submitting) return;
    const fingerprint = JSON.stringify(payload);
    if (publishCommandRef.current?.fingerprint !== fingerprint) {
      publishCommandRef.current = { fingerprint, key: newIdempotencyKey() };
    }
    setSubmitting(true);
    setSubmitError(null);
    try {
      await dataSource.publishPlatformVersion(payload, { idempotencyKey: publishCommandRef.current.key });
      publishCommandRef.current = null;
      setDrawer(null);
      await load();
    } catch (error) {
      setSubmitError(error?.detail ?? error?.message ?? "版本发布失败，请检查契约后重试。");
    } finally {
      setSubmitting(false);
    }
  };

  const closeDrawer = () => {
    if (submitting) return;
    setDrawer(null);
    setSubmitError(null);
    publishCommandRef.current = null;
  };

  return (
    <div className="ptm-shell">
      <header className="ptm-topbar">
        {onBack ? <button type="button" className="ptm-brand" onClick={onBack}><BrandLogo /><span>平台运营中心</span></button> : <div className="ptm-brand"><BrandLogo /><span>平台运营中心</span></div>}
        <div className="ptm-topbar__identity"><strong>{session.user.name}</strong><button type="button" onClick={onLogout}><IconLogout size={17} />退出</button></div>
      </header>
      <aside className="ptm-sidebar">
        {onBack ? <button type="button" className="ptm-back" onClick={onBack}><IconArrowLeft size={18} /><span>返回企业办公室</span></button> : null}
        <small>员工生态</small>
        <nav aria-label="平台员工生态导航">
          <button className="is-active" type="button"><IconBook2 size={19} /><span>官方员工模板</span></button>
          {onNavigateModels ? <button type="button" onClick={onNavigateModels}><IconServer size={19} /><span>官方模型</span></button> : null}
        </nav>
        <div className="ptm-sidebar__note"><IconShieldCheck size={18} /><span><strong>平台数据边界</strong><small>这里只管理官方模板契约，不展示企业消息、文档、提示词或成果正文。</small></span></div>
      </aside>
      <main className="ptm-main">
        <header className="ptm-heading">
          <div><small>员工生态 / 官方模板</small><h1>官方员工模板</h1><p>维护平台可招聘的岗位能力与冻结版本，企业再基于官方版本招聘自己的数字员工。</p></div>
          <div><button type="button" onClick={load} disabled={state.phase === "loading"}><IconRefresh size={17} />刷新</button>{canPublish ? <button className="is-primary" type="button" onClick={() => setDrawer({ mode: "publish", baseVersion: null })}><IconPlus size={17} />发布官方版本</button> : null}</div>
        </header>

        {state.phase === "loading" ? <div className="ptm-state">正在读取官方员工模板…</div> : null}
        {state.phase === "error" ? <div className="ptm-state is-error"><strong>模板数据加载失败</strong><span>{state.error?.detail ?? state.error?.message}</span><button type="button" onClick={load}>重新加载</button></div> : null}
        {state.phase === "ready" ? (
          <>
            <section className="ptm-stats" aria-label="官方模板统计">
              <span><small>官方员工类型</small><strong>{stats.templates}</strong></span>
              <span><small>已记录版本</small><strong>{stats.versions}</strong></span>
              <span><small>当前已发布</small><strong>{stats.active}</strong></span>
              <span><small>指定企业可见</small><strong>{stats.restricted}</strong></span>
            </section>
            <section className="ptm-panel ptm-catalog">
              <div className="ptm-panel__heading"><div><h2>官方员工类型库</h2><p>每张卡片展示该员工类型最近发布的冻结版本。</p></div><label className="ptm-search"><IconSearch size={17} /><input aria-label="搜索官方员工模板" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索名称、编码或能力" /></label></div>
              {visibleGroups.length ? <div className="ptm-template-grid">{visibleGroups.map(({ latest, versions }) => {
                const visual = visualFor(latest.capabilityCode);
                return <button type="button" key={latest.templateId} onClick={() => setDrawer({ mode: "detail", version: latest })}><img src={visual.image} alt="" /><span><small>{visual.label}</small><strong>{latest.templateName}</strong><em>{latest.templateCode} · {versions.length} 个版本</em></span><div><StatusChip tone={latest.status === "PUBLISHED" ? "success" : "neutral"}>{latest.status === "PUBLISHED" ? "已发布" : "已退役"}</StatusChip><IconChevronRight size={18} /></div></button>;
              })}</div> : <div className="ptm-empty">{search ? "没有匹配的官方员工模板。" : "尚未发布官方员工模板。"}</div>}
            </section>
            <section className="ptm-panel">
              <div className="ptm-panel__heading"><div><h2>已发布版本</h2><p>版本是不可变快照；查看后可复制配置并发布新版本。</p></div></div>
              {visibleVersions.length ? <div className="ptm-version-table"><div className="ptm-version-table__head"><span>模板</span><span>版本</span><span>能力</span><span>企业范围</span><span>预计智点</span><span>发布时间</span><span>操作</span></div>{visibleVersions.map((version) => <button type="button" className="ptm-version-row" key={version.agentVersionId} onClick={() => setDrawer({ mode: "detail", version })}><span><strong>{version.templateName}</strong><small>{version.templateCode}</small></span><span>{version.version}</span><span>{visualFor(version.capabilityCode).label}</span><span>{visibilityLabel(version.enterpriseVisibility)}</span><span>{formatPoints(version.pointEstimateMicroCredit)}</span><span>{publishedAtLabel(version.publishedAt)}</span><span>查看详情 <IconChevronRight size={15} /></span></button>)}</div> : <div className="ptm-empty">没有可展示的版本。</div>}
            </section>
          </>
        ) : null}
      </main>
      {drawer?.mode === "detail" ? <DetailDrawer version={drawer.version} canPublish={canPublish} onClose={closeDrawer} onUseAsBase={(version) => { setSubmitError(null); setDrawer({ mode: "publish", baseVersion: version }); }} /> : null}
      {drawer?.mode === "publish" ? <PublishDrawer key={drawer.baseVersion?.agentVersionId ?? "new"} baseVersion={drawer.baseVersion} submitting={submitting} error={submitError} onClose={closeDrawer} onPublish={publish} /> : null}
    </div>
  );
}
