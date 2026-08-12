import { httpClient } from "./httpClient.js";
import { createBoundedEventDeduper, readTaskSseEvents } from "./sseEventStream.js";

function requireTaskId(taskId) {
  const value = String(taskId ?? "").trim();
  if (!value) throw new TypeError("taskId is required");
  return value;
}

function taskPathId(taskId) {
  return encodeURIComponent(requireTaskId(taskId));
}

function requirePayload(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new TypeError("task payload must be an object");
  }
  return JSON.parse(JSON.stringify(payload));
}

export function createIdempotencyKey(prefix = "command", randomUUID = globalThis.crypto?.randomUUID?.bind(globalThis.crypto)) {
  if (typeof randomUUID !== "function") {
    throw new Error("crypto.randomUUID is required to create idempotency keys");
  }
  return `${prefix}-${randomUUID()}`;
}

function requireIdempotencyKey(value) {
  const key = String(value ?? "").trim();
  if (!key) throw new TypeError("idempotencyKey is required");
  return key;
}

export function createTaskApi(client = httpClient) {
  function prepareCreateTask(payload, {
    idempotencyKey = createIdempotencyKey("task"),
  } = {}) {
    const payloadSnapshot = requirePayload(payload);
    const stableIdempotencyKey = requireIdempotencyKey(idempotencyKey);

    return Object.freeze({
      idempotencyKey: stableIdempotencyKey,
      execute: ({ signal } = {}) => client.post("/tasks", {
        json: payloadSnapshot,
        signal,
        headers: {
          "Idempotency-Key": stableIdempotencyKey,
        },
      }),
    });
  }

  return Object.freeze({
    prepareCreateTask,
    createTask(payload, { idempotencyKey, signal } = {}) {
      return prepareCreateTask(payload, { idempotencyKey }).execute({ signal });
    },
    async getTask(taskId, { etag, signal } = {}) {
      const headers = etag ? { "If-None-Match": etag } : undefined;
      const response = await client.get(`/tasks/${taskPathId(taskId)}`, {
        headers,
        signal,
        acceptedStatuses: [304],
        withResponse: true,
      });

      return {
        task: response.data,
        notModified: response.status === 304,
        etag: response.headers.get("etag") ?? etag ?? null,
        status: response.status,
      };
    },
    openTaskEvents(taskId, {
      afterEventId,
      signal,
    } = {}) {
      const path = `/tasks/${taskPathId(taskId)}/events`;
      return client.stream(path, {
        query: { afterEventId },
        headers: { Accept: "text/event-stream" },
        signal,
      });
    },
    async *readTaskEvents(taskId, {
      afterEventId,
      signal,
      deduper = createBoundedEventDeduper(),
      onOpen,
    } = {}) {
      const stableTaskId = requireTaskId(taskId);
      const response = await client.stream(`/tasks/${taskPathId(stableTaskId)}/events`, {
        query: { afterEventId },
        headers: { Accept: "text/event-stream" },
        signal,
      });
      onOpen?.(response);
      yield* readTaskSseEvents(response, {
        taskId: stableTaskId,
        signal,
        deduper,
      });
    },
  });
}

export const taskApi = createTaskApi();
