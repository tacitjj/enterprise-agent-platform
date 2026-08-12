import { ProblemDetail } from "./problem.js";
import { getAccessToken, recoverUnauthorizedSession } from "./accessTokenStore.js";

export const DEFAULT_API_BASE_URL = "/api/v1";
export const DEFAULT_API_TIMEOUT_MS = 15_000;

function runtimeEnvironment() {
  return import.meta.env ?? {};
}

function normalizeBaseUrl(value) {
  const baseUrl = String(value || DEFAULT_API_BASE_URL).trim();
  return baseUrl === "/" ? "" : baseUrl.replace(/\/+$/, "");
}

function parseTimeout(value) {
  if (value === undefined || value === null || value === "") return DEFAULT_API_TIMEOUT_MS;
  const timeout = Number(value);
  if (!Number.isInteger(timeout) || timeout <= 0) {
    throw new Error("VITE_API_TIMEOUT_MS must be a positive integer");
  }
  return timeout;
}

export function resolveHttpClientConfig(environment = runtimeEnvironment()) {
  return {
    baseUrl: normalizeBaseUrl(environment.VITE_API_BASE_URL),
    timeoutMs: parseTimeout(environment.VITE_API_TIMEOUT_MS),
  };
}

function joinUrl(baseUrl, path) {
  if (/^https?:\/\//i.test(path)) return path;
  const normalizedPath = `/${String(path).replace(/^\/+/, "")}`;
  return `${baseUrl}${normalizedPath}`;
}

function appendQuery(url, query) {
  const entries = Object.entries(query ?? {}).filter(([, value]) => value !== undefined && value !== null);
  if (entries.length === 0) return url;

  const serialized = new URLSearchParams(entries.map(([key, value]) => [key, String(value)])).toString();
  return `${url}${url.includes("?") ? "&" : "?"}${serialized}`;
}

function createAbortScope(externalSignal, timeoutMs) {
  const controller = new AbortController();
  let timedOut = false;
  let timeoutId;

  const abortFromCaller = () => controller.abort(externalSignal.reason);
  if (externalSignal?.aborted) {
    abortFromCaller();
  } else if (externalSignal) {
    externalSignal.addEventListener("abort", abortFromCaller, { once: true });
  }

  if (!controller.signal.aborted) {
    timeoutId = setTimeout(() => {
      timedOut = true;
      controller.abort(new DOMException("Request timed out", "TimeoutError"));
    }, timeoutMs);
  }

  return {
    signal: controller.signal,
    didTimeOut: () => timedOut,
    cleanup() {
      if (timeoutId !== undefined) clearTimeout(timeoutId);
      externalSignal?.removeEventListener("abort", abortFromCaller);
    },
  };
}

async function parseSuccessfulBody(response) {
  if ([204, 205, 304].includes(response.status)) return null;
  const text = await response.text();
  if (!text) return null;

  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";
  if (!contentType.includes("json")) return text;

  try {
    return JSON.parse(text);
  } catch (cause) {
    throw new ProblemDetail({
      code: "INVALID_JSON_RESPONSE",
      title: "接口响应格式错误",
      detail: "服务端返回了无法解析的 JSON 响应。",
      status: response.status,
      traceId: response.headers.get("x-trace-id"),
      cause,
    });
  }
}

export function createHttpClient({
  baseUrl,
  timeoutMs,
  fetchImpl = globalThis.fetch,
  accessTokenProvider = getAccessToken,
  credentials = "omit",
} = {}) {
  const runtimeConfig = resolveHttpClientConfig();
  const resolvedBaseUrl = normalizeBaseUrl(baseUrl ?? runtimeConfig.baseUrl);
  const resolvedTimeoutMs = parseTimeout(timeoutMs ?? runtimeConfig.timeoutMs);

  function buildUrl(path, query) {
    return appendQuery(joinUrl(resolvedBaseUrl, path), query);
  }

  function authenticatedHeaders(headers) {
    const requestHeaders = new Headers(headers);
    const accessToken = accessTokenProvider?.();
    if (accessToken && !requestHeaders.has("Authorization")) {
      requestHeaders.set("Authorization", `Bearer ${accessToken}`);
    }
    return requestHeaders;
  }

  async function request(path, {
    method = "GET",
    query,
    headers,
    json,
    body,
    signal,
    timeoutMs: requestTimeoutMs = resolvedTimeoutMs,
    acceptedStatuses = [],
    withResponse = false,
    retryUnauthorized = true,
    authRetried = false,
  } = {}) {
    if (typeof fetchImpl !== "function") {
      throw new ProblemDetail({
        code: "FETCH_UNAVAILABLE",
        title: "网络能力不可用",
        detail: "当前运行环境没有可用的 Fetch 实现。",
      });
    }
    if (json !== undefined && body !== undefined) {
      throw new TypeError("Use either json or body, not both");
    }

    const requestHeaders = authenticatedHeaders(headers);
    if (!requestHeaders.has("Accept")) requestHeaders.set("Accept", "application/json");
    let requestBody = body;
    if (json !== undefined) {
      if (!requestHeaders.has("Content-Type")) requestHeaders.set("Content-Type", "application/json");
      requestBody = JSON.stringify(json);
    }

    const url = buildUrl(path, query);
    const abortScope = createAbortScope(signal, parseTimeout(requestTimeoutMs));

    try {
      const response = await fetchImpl(url, {
        method,
        headers: requestHeaders,
        body: requestBody,
        credentials,
        signal: abortScope.signal,
      });
      if (response.status === 401 && retryUnauthorized && !authRetried) {
        const recovered = await recoverUnauthorizedSession();
        if (recovered) {
          return request(path, {
            method,
            query,
            headers,
            json,
            body,
            signal,
            timeoutMs: requestTimeoutMs,
            acceptedStatuses,
            withResponse,
            retryUnauthorized,
            authRetried: true,
          });
        }
      }
      const statusAccepted = response.ok || acceptedStatuses.includes(response.status);
      if (!statusAccepted) throw await ProblemDetail.fromResponse(response);

      const data = await parseSuccessfulBody(response);
      if (!withResponse) return data;
      return {
        data,
        status: response.status,
        headers: response.headers,
      };
    } catch (error) {
      if (error instanceof ProblemDetail) throw error;
      if (abortScope.didTimeOut()) {
        throw new ProblemDetail({
          code: "REQUEST_TIMEOUT",
          title: "请求超时",
          detail: "服务暂时没有响应，请稍后重试。",
          cause: error,
        });
      }
      if (signal?.aborted) {
        throw new ProblemDetail({
          code: "REQUEST_ABORTED",
          title: "请求已取消",
          detail: "请求在完成前被取消。",
          cause: error,
        });
      }
      throw new ProblemDetail({
        code: "NETWORK_ERROR",
        title: "网络请求失败",
        detail: "无法连接服务，请检查网络后重试。",
        cause: error,
      });
    } finally {
      abortScope.cleanup();
    }
  }

  async function stream(path, {
    query,
    headers,
    signal,
    retryUnauthorized = true,
    authRetried = false,
  } = {}) {
    if (typeof fetchImpl !== "function") {
      throw new ProblemDetail({
        code: "FETCH_UNAVAILABLE",
        title: "网络能力不可用",
        detail: "当前运行环境没有可用的 Fetch 实现。",
      });
    }

    const response = await fetchImpl(buildUrl(path, query), {
      method: "GET",
      headers: authenticatedHeaders(headers),
      credentials,
      signal,
    });
    if (response.status === 401 && retryUnauthorized && !authRetried) {
      const recovered = await recoverUnauthorizedSession();
      if (recovered) {
        return stream(path, {
          query,
          headers,
          signal,
          retryUnauthorized,
          authRetried: true,
        });
      }
    }
    if (!response.ok) throw await ProblemDetail.fromResponse(response);
    return response;
  }

  return Object.freeze({
    buildUrl,
    request,
    stream,
    get: (path, options) => request(path, { ...options, method: "GET" }),
    post: (path, options) => request(path, { ...options, method: "POST" }),
  });
}

export const httpClient = createHttpClient();
