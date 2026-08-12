import { httpClient } from "./httpClient.js";

function requireId(value, name) {
  const normalized = String(value ?? "").trim();
  if (!normalized) throw new TypeError(`${name} is required`);
  return normalized;
}

function agentPath(agentId, suffix = "") {
  return `/enterprise/agents/${encodeURIComponent(requireId(agentId, "agentId"))}${suffix}`;
}

function commandHeaders({ etag, idempotencyKey, headers } = {}) {
  return {
    ...headers,
    "If-Match": requireId(etag, "etag"),
    "Idempotency-Key": requireId(idempotencyKey, "idempotencyKey"),
  };
}

function managementDetail(response) {
  return {
    detail: response.data,
    etag: response.headers.get("etag"),
    status: response.status,
  };
}

export function createEmployeeManagementApi(client = httpClient) {
  return Object.freeze({
    listPlatformVersions: (options) => client.get("/platform/agent-versions", options),
    publishPlatformVersion: (payload, { idempotencyKey, ...options } = {}) => client.post(
      "/platform/agent-versions",
      {
        ...options,
        headers: { ...options.headers, "Idempotency-Key": requireId(idempotencyKey, "idempotencyKey") },
        json: payload,
      },
    ),
    listRecruitableVersions: (options) => client.get("/enterprise/agent-catalog", options),
    listEnterpriseAgents: (options) => client.get("/enterprise/agents", options),
    async getEnterpriseAgent(agentId, options = {}) {
      const response = await client.get(agentPath(agentId), { ...options, withResponse: true });
      return managementDetail(response);
    },
    hireEnterpriseAgent: (payload, { idempotencyKey, ...options } = {}) => client.post(
      "/enterprise/agents",
      {
        ...options,
        headers: { ...options.headers, "Idempotency-Key": requireId(idempotencyKey, "idempotencyKey") },
        json: payload,
      },
    ),
    async createEnterpriseAgentConfigurationVersion(agentId, payload, {
      etag,
      idempotencyKey,
      ...options
    } = {}) {
      const response = await client.post(agentPath(agentId, "/configuration-versions"), {
        ...options,
        headers: commandHeaders({ etag, idempotencyKey, headers: options.headers }),
        json: payload,
        withResponse: true,
      });
      return managementDetail(response);
    },
    async activateEnterpriseAgent(agentId, payload, {
      etag,
      idempotencyKey,
      ...options
    } = {}) {
      const response = await client.post(agentPath(agentId, "/activate"), {
        ...options,
        headers: commandHeaders({ etag, idempotencyKey, headers: options.headers }),
        json: payload,
        withResponse: true,
      });
      return managementDetail(response);
    },
  });
}

export const employeeManagementApi = createEmployeeManagementApi();
