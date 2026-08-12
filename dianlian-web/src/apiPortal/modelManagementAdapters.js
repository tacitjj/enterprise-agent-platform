const MAX_SIGNED_LONG = 9_223_372_036_854_775_807n;
const MICRO_CREDITS_PER_POINT = 1_000_000n;
const CODE_PATTERN = /^[A-Z][A-Z0-9_.-]{1,127}$/;
const CREDENTIAL_REFERENCE_PATTERN = /^env:DIANLIAN_MODEL_[A-Z0-9_]{1,113}$/;
const INTEGER_STRING_PATTERN = /^(0|[1-9][0-9]{0,18})$/;
const POSITIVE_INTEGER_STRING_PATTERN = /^[1-9][0-9]{0,18}$/;

export const MODEL_PERMISSIONS = Object.freeze({
  READ: "platform.model.read",
  MANAGE: "platform.model.manage",
});

export const MODEL_CAPABILITIES = Object.freeze([
  Object.freeze({ value: "TEXT_CHAT", label: "文本对话" }),
  Object.freeze({ value: "TEXT_REASONING", label: "文本推理" }),
  Object.freeze({ value: "VISION_UNDERSTANDING", label: "视觉理解" }),
  Object.freeze({ value: "IMAGE_GENERATION", label: "图像生成" }),
  Object.freeze({ value: "IMAGE_EDITING", label: "图像编辑" }),
  Object.freeze({ value: "EMBEDDING", label: "向量化" }),
  Object.freeze({ value: "RERANK", label: "重排序" }),
  Object.freeze({ value: "OCR", label: "文字识别" }),
]);

export const MODEL_PROTOCOLS = Object.freeze([
  Object.freeze({ value: "OPENAI_COMPATIBLE", label: "OpenAI Compatible" }),
]);

const CAPABILITY_LABELS = new Map(MODEL_CAPABILITIES.map((item) => [item.value, item.label]));
const PROTOCOL_LABELS = new Map(MODEL_PROTOCOLS.map((item) => [item.value, item.label]));
const STATUS_LABELS = new Map([
  ["ACTIVE", "可用"],
  ["DISABLED", "已停用"],
]);

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function text(value) {
  return typeof value === "string" ? value.trim() : "";
}

function requiredText(value, label, maxLength) {
  const normalized = text(String(value ?? ""));
  if (!normalized) throw new Error(`请填写${label}。`);
  if (normalized.length > maxLength) throw new Error(`${label}不能超过 ${maxLength} 个字符。`);
  return normalized;
}

function stableCode(value, label, maxLength) {
  const normalized = requiredText(value, label, maxLength).toUpperCase();
  if (!CODE_PATTERN.test(normalized)) {
    throw new Error(`${label}必须以大写字母开头，只能包含大写字母、数字、点、下划线和短横线。`);
  }
  return normalized;
}

function integerString(value, label, { positive = false } = {}) {
  const normalized = requiredText(value, label, 19);
  const pattern = positive ? POSITIVE_INTEGER_STRING_PATTERN : INTEGER_STRING_PATTERN;
  if (!pattern.test(normalized) || BigInt(normalized) > MAX_SIGNED_LONG) {
    throw new Error(`${label}必须是后端 long 范围内的${positive ? "正" : "非负"}整数字符串。`);
  }
  return normalized;
}

function responseIntegerString(value, { positive = false } = {}) {
  if (typeof value !== "string") return null;
  const pattern = positive ? POSITIVE_INTEGER_STRING_PATTERN : INTEGER_STRING_PATTERN;
  if (!pattern.test(value)) return null;
  try {
    return BigInt(value) <= MAX_SIGNED_LONG ? value : null;
  } catch {
    return null;
  }
}

function enumLabel(value, labels) {
  const normalized = text(value);
  if (!normalized) return "未返回";
  return labels.get(normalized) ?? `未知值（${normalized}）`;
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (!isObject(value)) return value;
  return Object.keys(value).sort().reduce((result, key) => {
    result[key] = canonicalize(value[key]);
    return result;
  }, {});
}

export function nextCommandIntent(currentIntent, prefix, payload, uuidFactory = () => crypto.randomUUID()) {
  const fingerprint = JSON.stringify(canonicalize(payload));
  if (currentIntent?.fingerprint === fingerprint) return currentIntent;
  return Object.freeze({
    fingerprint,
    key: `${requiredText(prefix, "幂等键前缀", 48)}:${uuidFactory()}`,
  });
}

export function buildModelDefinitionPayload(form) {
  const protocol = stableCode(form.protocol, "协议", 64);
  if (!PROTOCOL_LABELS.has(protocol)) throw new Error("当前运行时只支持 OPENAI_COMPATIBLE 协议。");

  const capabilityType = stableCode(form.capabilityType, "能力类型", 64);
  if (!CAPABILITY_LABELS.has(capabilityType)) throw new Error("请选择系统支持的能力类型。");

  const baseUrl = requiredText(form.baseUrl, "接口地址", 2_048).replace(/\/+$/, "");
  let parsedUrl;
  try {
    parsedUrl = new URL(baseUrl);
  } catch {
    throw new Error("接口地址必须是合法 URL。");
  }
  if (parsedUrl.protocol !== "https:" || !parsedUrl.hostname || parsedUrl.username || parsedUrl.password) {
    throw new Error("接口地址必须使用 HTTPS，且不能包含账号或密码。");
  }

  const credentialRef = requiredText(form.credentialRef, "密钥环境变量引用", 132);
  if (!CREDENTIAL_REFERENCE_PATTERN.test(credentialRef)) {
    throw new Error("密钥只能填写 env:DIANLIAN_MODEL_* 环境变量引用，不能填写真实 API Key。");
  }

  const temperatureText = requiredText(form.temperature, "Temperature", 16);
  if (!/^(?:0(?:\.\d+)?|1(?:\.\d+)?|2(?:\.0+)?)$/.test(temperatureText)) {
    throw new Error("Temperature 必须是 0 到 2 之间的数字。");
  }
  const temperature = Number(temperatureText);
  if (!Number.isFinite(temperature) || temperature < 0 || temperature > 2) {
    throw new Error("Temperature 必须是 0 到 2 之间的数字。");
  }

  const maxOutputTokensText = requiredText(form.maxOutputTokens, "最大输出 Token", 6);
  if (!/^[1-9]\d*$/.test(maxOutputTokensText)) throw new Error("最大输出 Token 必须是正整数。");
  const maxOutputTokens = Number(maxOutputTokensText);
  if (!Number.isInteger(maxOutputTokens) || maxOutputTokens > 131_072) {
    throw new Error("最大输出 Token 必须在 1 到 131072 之间。");
  }

  return Object.freeze({
    modelCode: stableCode(form.modelCode, "模型编码", 64),
    displayName: requiredText(form.displayName, "显示名称", 100),
    providerCode: stableCode(form.providerCode, "供应商编码", 64),
    protocol,
    baseUrl,
    providerModelName: requiredText(form.providerModelName, "供应商模型名称", 100),
    credentialRef,
    capabilityType,
    temperature,
    maxOutputTokens,
    inputRateMicroCreditPerMillionTokens: integerString(
      form.inputRateMicroCreditPerMillionTokens,
      "输入费率",
    ),
    outputRateMicroCreditPerMillionTokens: integerString(
      form.outputRateMicroCreditPerMillionTokens,
      "输出费率",
    ),
    reservationCeilingMicroCredit: integerString(
      form.reservationCeilingMicroCredit,
      "单次预占上限",
      { positive: true },
    ),
  });
}

export function buildPlatformRoutePayload(modelDefinitionId) {
  return Object.freeze({
    modelDefinitionId: requiredText(modelDefinitionId, "模型定义 ID", 128),
  });
}

export function adaptModelDefinition(raw, index = 0) {
  if (!isObject(raw)) {
    return Object.freeze({
      modelDefinitionId: `invalid-${index}`,
      displayName: "响应记录格式异常",
      contractIssues: Object.freeze(["模型记录不是 JSON 对象"]),
      capabilityType: "",
      capabilityLabel: "未返回",
      protocol: "",
      protocolLabel: "未返回",
      status: "",
      statusLabel: "未返回",
    });
  }

  const inputRate = responseIntegerString(raw.inputRateMicroCreditPerMillionTokens);
  const outputRate = responseIntegerString(raw.outputRateMicroCreditPerMillionTokens);
  const reservationCeiling = responseIntegerString(raw.reservationCeilingMicroCredit, { positive: true });
  const contractIssues = [];
  if (inputRate === null) contractIssues.push("输入费率不是整数字符串");
  if (outputRate === null) contractIssues.push("输出费率不是整数字符串");
  if (reservationCeiling === null) contractIssues.push("预占上限不是正整数字符串");

  const capabilityType = text(raw.capabilityType);
  const protocol = text(raw.protocol);
  const status = text(raw.status);

  // credentialRef deliberately stays outside the UI view model, even if the API returns it.
  return Object.freeze({
    modelDefinitionId: text(raw.modelDefinitionId) || `invalid-${index}`,
    modelCode: text(raw.modelCode),
    configurationVersion: raw.configurationVersion,
    displayName: text(raw.displayName) || "未命名模型",
    providerCode: text(raw.providerCode),
    protocol,
    protocolLabel: enumLabel(protocol, PROTOCOL_LABELS),
    baseUrl: text(raw.baseUrl),
    providerModelName: text(raw.providerModelName),
    capabilityType,
    capabilityLabel: enumLabel(capabilityType, CAPABILITY_LABELS),
    temperature: raw.temperature,
    maxOutputTokens: raw.maxOutputTokens,
    inputRateMicroCreditPerMillionTokens: inputRate,
    outputRateMicroCreditPerMillionTokens: outputRate,
    reservationCeilingMicroCredit: reservationCeiling,
    status,
    statusLabel: enumLabel(status, STATUS_LABELS),
    createdAt: text(raw.createdAt),
    contractIssues: Object.freeze(contractIssues),
  });
}

export function adaptModelDefinitionList(payload) {
  if (!isObject(payload) || !Array.isArray(payload.items)) {
    throw new TypeError("模型列表响应必须包含 items 数组");
  }
  return Object.freeze(payload.items.map((item, index) => adaptModelDefinition(item, index)));
}

export function adaptRouteBinding(raw) {
  if (!isObject(raw)) throw new TypeError("模型路由响应必须是 JSON 对象");
  const capabilityType = text(raw.capabilityType);
  const status = text(raw.status);
  return Object.freeze({
    routeBindingId: text(raw.routeBindingId),
    scopeType: text(raw.scopeType),
    capabilityType,
    capabilityLabel: enumLabel(capabilityType, CAPABILITY_LABELS),
    modelDefinitionId: text(raw.modelDefinitionId),
    stateVersion: raw.stateVersion,
    status,
    statusLabel: enumLabel(status, STATUS_LABELS),
    createdAt: text(raw.createdAt),
  });
}

export function adaptPlatformDefaultRouteList(payload) {
  if (!isObject(payload) || !Array.isArray(payload.items)) {
    throw new TypeError("平台默认路由响应必须包含 items 数组");
  }
  return Object.freeze(payload.items.map(adaptRouteBinding));
}

export function classifyModelManagementError(error) {
  const status = Number(error?.status ?? 0);
  if (status === 401) return "unauthenticated";
  if (status === 403) return "forbidden";
  return "error";
}

export function formatMicroCreditAsPoints(value) {
  if (typeof value !== "string" || !INTEGER_STRING_PATTERN.test(value)) return "—";
  try {
    const amount = BigInt(value);
    const whole = amount / MICRO_CREDITS_PER_POINT;
    const fraction = (amount % MICRO_CREDITS_PER_POINT)
      .toString()
      .padStart(6, "0")
      .replace(/0+$/, "");
    return fraction ? `${whole}.${fraction}` : whole.toString();
  } catch {
    return "—";
  }
}

export function modelCapabilityLabel(value) {
  return enumLabel(value, CAPABILITY_LABELS);
}
