import { httpClient } from "./httpClient.js";

function requireAgentId(agentId) {
  const value = String(agentId ?? "").trim();
  if (!value) throw new TypeError("agentId is required");
  return encodeURIComponent(value);
}

export function createEmployeeApi(client = httpClient) {
  return Object.freeze({
    async getEmployeeWorkspace(agentId, { etag, signal } = {}) {
      const headers = etag ? { "If-None-Match": etag } : undefined;
      const response = await client.get(`/employees/${requireAgentId(agentId)}`, {
        headers,
        signal,
        acceptedStatuses: [304],
        withResponse: true,
      });
      return {
        workspace: response.data,
        notModified: response.status === 304,
        etag: response.headers.get("etag") ?? etag ?? null,
        status: response.status,
      };
    },
  });
}

export const employeeApi = createEmployeeApi();
