export class SseProtocolError extends Error {
  constructor(message, { cause } = {}) {
    super(message, { cause });
    this.name = "SseProtocolError";
  }
}

function requireText(value, field) {
  const normalized = String(value ?? "").trim();
  if (!normalized) throw new SseProtocolError(`SSE event field ${field} is required`);
  return normalized;
}

export function createBoundedEventDeduper(limit = 512) {
  if (!Number.isInteger(limit) || limit <= 0) {
    throw new TypeError("SSE dedupe limit must be a positive integer");
  }
  const seen = new Set();
  const order = [];

  return Object.freeze({
    accept(eventId) {
      const stableEventId = requireText(eventId, "eventId");
      if (seen.has(stableEventId)) return false;
      seen.add(stableEventId);
      order.push(stableEventId);
      if (order.length > limit) seen.delete(order.shift());
      return true;
    },
  });
}

async function* readSseLines(body, signal) {
  if (!body || typeof body.getReader !== "function") {
    throw new SseProtocolError("SSE response body is not a readable stream");
  }

  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let done = false;

  try {
    while (!done) {
      if (signal?.aborted) return;
      const result = await reader.read();
      done = result.done;
      buffer += decoder.decode(result.value, { stream: !done });

      let lineStart = 0;
      for (let index = 0; index < buffer.length; index += 1) {
        const character = buffer[index];
        if (character !== "\n" && character !== "\r") continue;
        if (character === "\r" && index === buffer.length - 1 && !done) break;

        yield buffer.slice(lineStart, index);
        if (character === "\r" && buffer[index + 1] === "\n") index += 1;
        lineStart = index + 1;
      }
      buffer = buffer.slice(lineStart);
    }

    if (buffer) yield buffer;
  } finally {
    reader.releaseLock();
  }
}

function parseField(line) {
  const colonIndex = line.indexOf(":");
  if (colonIndex < 0) return [line, ""];
  const field = line.slice(0, colonIndex);
  let value = line.slice(colonIndex + 1);
  if (value.startsWith(" ")) value = value.slice(1);
  return [field, value];
}

function validateEnvelope(frame, taskId) {
  let envelope;
  try {
    envelope = JSON.parse(frame.data.join("\n"));
  } catch (cause) {
    throw new SseProtocolError("SSE data is not valid JSON", { cause });
  }

  if (!envelope || typeof envelope !== "object" || Array.isArray(envelope)) {
    throw new SseProtocolError("SSE data must be an event envelope object");
  }
  if (envelope.schemaVersion !== 1) {
    throw new SseProtocolError(`Unsupported SSE schemaVersion: ${envelope.schemaVersion}`);
  }

  const eventId = requireText(envelope.eventId, "eventId");
  const eventType = requireText(envelope.eventType, "eventType");
  const streamType = requireText(envelope.streamType, "streamType");
  const streamId = requireText(envelope.streamId, "streamId");
  requireText(envelope.aggregateType, "aggregateType");
  requireText(envelope.aggregateId, "aggregateId");
  requireText(envelope.occurredAt, "occurredAt");
  requireText(envelope.visibilityVersion, "visibilityVersion");
  requireText(envelope.traceId, "traceId");

  if (streamType !== "TASK") throw new SseProtocolError(`Unexpected SSE streamType: ${streamType}`);
  if (streamId !== taskId) throw new SseProtocolError(`Unexpected SSE streamId: ${streamId}`);
  if (!Number.isInteger(envelope.aggregateVersion) || envelope.aggregateVersion < 0) {
    throw new SseProtocolError("SSE aggregateVersion must be a non-negative integer");
  }
  if (!envelope.payload || typeof envelope.payload !== "object" || Array.isArray(envelope.payload)) {
    throw new SseProtocolError("SSE payload must be an object");
  }
  if (frame.id && frame.id !== eventId) throw new SseProtocolError("SSE id does not match envelope eventId");
  if (frame.event && frame.event !== eventType) throw new SseProtocolError("SSE event does not match envelope eventType");

  return Object.freeze(envelope);
}

export async function* readTaskSseEvents(response, {
  taskId,
  signal,
  deduper = createBoundedEventDeduper(),
} = {}) {
  const stableTaskId = requireText(taskId, "taskId");
  const contentType = response?.headers?.get?.("content-type")?.toLowerCase() ?? "";
  if (!contentType.includes("text/event-stream")) {
    throw new SseProtocolError("Task event response is not text/event-stream");
  }

  let frame = { id: "", event: "", data: [] };
  const dispatch = () => {
    if (frame.data.length === 0) {
      frame = { id: "", event: "", data: [] };
      return null;
    }
    const envelope = validateEnvelope(frame, stableTaskId);
    frame = { id: "", event: "", data: [] };
    return deduper.accept(envelope.eventId) ? envelope : null;
  };

  for await (const line of readSseLines(response.body, signal)) {
    if (signal?.aborted) return;
    if (line === "") {
      const envelope = dispatch();
      if (envelope) yield envelope;
      continue;
    }
    if (line.startsWith(":")) continue;

    const [field, value] = parseField(line);
    if (field === "id") frame.id = value;
    if (field === "event") frame.event = value;
    if (field === "data") frame.data.push(value);
  }

  const envelope = dispatch();
  if (envelope) yield envelope;
}

export function isTaskResetEvent(event) {
  return event?.eventType === "stream.reset_required";
}
