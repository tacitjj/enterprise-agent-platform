import assert from "node:assert/strict";
import test from "node:test";
import {
  createBoundedEventDeduper,
  isTaskResetEvent,
  readTaskSseEvents,
  SseProtocolError,
} from "../src/api/sseEventStream.js";

function eventEnvelope(overrides = {}) {
  return {
    schemaVersion: 1,
    eventId: "187",
    streamType: "TASK",
    streamId: "task_01",
    eventType: "task.progress",
    aggregateType: "TASK",
    aggregateId: "task_01",
    aggregateVersion: 6,
    occurredAt: "2026-08-11T10:00:00Z",
    visibilityVersion: "permission-v9",
    traceId: "trace_01",
    payload: { taskId: "task_01", stepId: "step_02" },
    ...overrides,
  };
}

function sseResponse(chunks) {
  const encoder = new TextEncoder();
  return new Response(new ReadableStream({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
      controller.close();
    },
  }), {
    status: 200,
    headers: { "content-type": "text/event-stream; charset=utf-8" },
  });
}

async function collect(iterable) {
  const values = [];
  for await (const value of iterable) values.push(value);
  return values;
}

test("parses CRLF split across chunks, joins data lines, and ignores duplicate event ids", async () => {
  const envelope = eventEnvelope();
  const serialized = JSON.stringify(envelope);
  const splitAt = serialized.indexOf(",") + 1;
  const firstFrame = `: keepalive\r\nid: ${envelope.eventId}\r\nevent: ${envelope.eventType}\r\ndata: ${serialized.slice(0, splitAt)}\r`;
  const duplicateFrame = `id: ${envelope.eventId}\nevent: ${envelope.eventType}\ndata: ${serialized}\n\n`;
  const response = sseResponse([
    firstFrame,
    `\ndata: ${serialized.slice(splitAt)}\r\n\r\n${duplicateFrame}`,
  ]);

  const events = await collect(readTaskSseEvents(response, {
    taskId: "task_01",
    deduper: createBoundedEventDeduper(8),
  }));

  assert.equal(events.length, 1);
  assert.deepEqual(events[0], envelope);
});

test("rejects an event whose wire id does not match the event envelope", async () => {
  const envelope = eventEnvelope();
  const response = sseResponse([
    `id: 188\nevent: ${envelope.eventType}\ndata: ${JSON.stringify(envelope)}\n\n`,
  ]);

  await assert.rejects(
    () => collect(readTaskSseEvents(response, { taskId: "task_01" })),
    (error) => error instanceof SseProtocolError && /eventId/.test(error.message),
  );
});

test("recognizes the contract reset event without treating it as a command", async () => {
  const envelope = eventEnvelope({
    eventId: "reset-1",
    eventType: "stream.reset_required",
    aggregateType: "STREAM",
    payload: { reason: "CURSOR_EXPIRED" },
  });
  const response = sseResponse([
    `id: reset-1\nevent: stream.reset_required\ndata: ${JSON.stringify(envelope)}\n\n`,
  ]);

  const [event] = await collect(readTaskSseEvents(response, { taskId: "task_01" }));
  assert.equal(isTaskResetEvent(event), true);
});
