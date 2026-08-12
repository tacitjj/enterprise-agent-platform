import { httpClient } from "./httpClient.js";

function requireValue(value, fieldName) {
  const normalized = String(value ?? "").trim();
  if (!normalized) throw new TypeError(`${fieldName} is required`);
  return normalized;
}

function commandResult(response) {
  return Object.freeze({
    resource: response.data,
    status: response.status,
    replayed: response.headers.get("idempotency-replayed") === "true",
  });
}

function commandOptions(payload, idempotencyKey, options) {
  return {
    ...options,
    headers: {
      ...options.headers,
      "Idempotency-Key": requireValue(idempotencyKey, "idempotencyKey"),
    },
    json: payload,
    withResponse: true,
  };
}

export function createModelManagementApi(client = httpClient) {
  return Object.freeze({
    listModelDefinitions: (options) => client.get("/platform/model-definitions", options),
    listPlatformDefaultRoutes: (options) => client.get("/platform/model-routes/defaults", options),

    async registerModelDefinition(payload, { idempotencyKey, ...options } = {}) {
      const response = await client.post(
        "/platform/model-definitions",
        commandOptions(payload, idempotencyKey, options),
      );
      return commandResult(response);
    },

    async setPlatformDefaultRoute(capabilityType, payload, { idempotencyKey, ...options } = {}) {
      const normalizedCapability = requireValue(capabilityType, "capabilityType");
      const response = await client.post(
        `/platform/model-routes/${encodeURIComponent(normalizedCapability)}/default`,
        commandOptions(payload, idempotencyKey, options),
      );
      return commandResult(response);
    },
  });
}

export const modelManagementApi = createModelManagementApi();
