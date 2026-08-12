const DEFAULT_HTTP_ERROR_CODE = "HTTP_REQUEST_FAILED";

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

async function readResponsePayload(response) {
  if ([204, 205, 304].includes(response.status)) return null;

  const text = await response.text();
  if (!text) return null;

  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";
  if (contentType.includes("json")) {
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }

  return text;
}

export class ProblemDetail extends Error {
  constructor({
    code = DEFAULT_HTTP_ERROR_CODE,
    title = "请求失败",
    detail,
    status = 0,
    traceId = null,
    type = null,
    instance = null,
    errors = null,
    retryable = false,
    action = "NONE",
    cause,
  } = {}) {
    super(detail || title);
    this.name = "ProblemDetail";
    this.code = code;
    this.title = title;
    this.detail = detail || title;
    this.status = status;
    this.traceId = traceId;
    this.type = type;
    this.instance = instance;
    this.errors = errors;
    this.retryable = Boolean(retryable);
    this.action = action || "NONE";
    if (cause !== undefined) this.cause = cause;
  }

  static async fromResponse(response) {
    const payload = await readResponsePayload(response);
    const problem = isObject(payload) ? payload : {};
    const fallbackTitle = response.statusText || "请求失败";
    const detail = problem.detail
      ?? problem.message
      ?? (typeof payload === "string" ? payload : fallbackTitle);

    return new ProblemDetail({
      code: problem.code ?? `HTTP_${response.status}`,
      title: problem.title ?? fallbackTitle,
      detail,
      status: Number.isFinite(problem.status) ? problem.status : response.status,
      traceId: problem.traceId ?? response.headers.get("x-trace-id") ?? null,
      type: problem.type ?? null,
      instance: problem.instance ?? null,
      errors: problem.errors ?? null,
      retryable: problem.retryable ?? false,
      action: problem.action ?? "NONE",
    });
  }

  toJSON() {
    return {
      type: this.type,
      title: this.title,
      status: this.status,
      code: this.code,
      detail: this.detail,
      instance: this.instance,
      traceId: this.traceId,
      errors: this.errors,
      retryable: this.retryable,
      action: this.action,
    };
  }
}

export function isProblemDetail(error) {
  return error instanceof ProblemDetail;
}
