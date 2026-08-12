import { httpClient } from "./httpClient.js";

function requireId(value, name) {
  const normalized = String(value ?? "").trim();
  if (!normalized) throw new TypeError(`${name} is required`);
  return normalized;
}

function conversationPath(conversationId, suffix = "") {
  return `/conversations/${encodeURIComponent(requireId(conversationId, "conversationId"))}${suffix}`;
}

function commandOptions(payload, { idempotencyKey, headers, ...options } = {}) {
  return {
    ...options,
    headers: {
      ...headers,
      "Idempotency-Key": requireId(idempotencyKey, "idempotencyKey"),
    },
    json: payload,
  };
}

export function createConversationApi(client = httpClient) {
  return Object.freeze({
    listConversations: (options) => client.get("/conversations", options),
    createConversation: (payload, options) => client.post(
      "/conversations",
      commandOptions(payload, options),
    ),
    listConversationMessages: (conversationId, {
      afterSequenceNo = 0,
      limit = 200,
      ...options
    } = {}) => client.get(conversationPath(conversationId, "/messages"), {
      ...options,
      query: { afterSequenceNo, limit },
    }),
    sendConversationMessage: (conversationId, payload, options) => client.post(
      conversationPath(conversationId, "/messages"),
      commandOptions(payload, options),
    ),
  });
}

export const conversationApi = createConversationApi();
