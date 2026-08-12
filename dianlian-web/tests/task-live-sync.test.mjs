import assert from "node:assert/strict";
import test from "node:test";
import {
  createTaskLiveSync,
  isTerminalTaskStatus,
  reconnectDelayForAttempt,
  TASK_LIVE_PHASE,
} from "../src/apiPortal/taskLiveSync.js";

function nextTurn(delay = 10) {
  return new Promise((resolve) => setTimeout(resolve, delay));
}

function event(overrides = {}) {
  return {
    eventId: "event-1",
    eventType: "task.progress",
    ...overrides,
  };
}

test("defines terminal states and caps reconnect backoff", () => {
  assert.equal(isTerminalTaskStatus("SUCCEEDED"), true);
  assert.equal(isTerminalTaskStatus("WAITING_APPROVAL"), false);
  assert.equal(reconnectDelayForAttempt(0, [10, 20]), 10);
  assert.equal(reconnectDelayForAttempt(9, [10, 20]), 20);
});

test("a task event only invalidates the authoritative ETag snapshot", async () => {
  const states = [];
  const refreshes = [];
  let snapshot = { status: "RUNNING", resumeEventId: "event-0" };
  const sync = createTaskLiveSync({
    readTaskEvents: async function* ({ onOpen, signal }) {
      onOpen();
      yield event();
      await new Promise((resolve) => signal.addEventListener("abort", resolve, { once: true }));
    },
    refreshSnapshot: async (options) => {
      refreshes.push(options);
      snapshot = { ...snapshot, resumeEventId: "event-1" };
      return snapshot;
    },
    getCurrentSnapshot: () => snapshot,
    onState: (state) => states.push(state),
    eventRefreshDelayMs: 0,
    reconnectDelaysMs: [1_000],
  });

  sync.start();
  await nextTurn();
  sync.stop();

  assert.ok(states.some((state) => state.phase === TASK_LIVE_PHASE.LIVE));
  assert.equal(refreshes.length, 1);
  assert.deepEqual(refreshes[0], { reset: false, reason: "event", silent: true });
});

test("falls back to ETag polling when the SSE endpoint is unavailable", async () => {
  const states = [];
  let refreshCount = 0;
  let firstRefresh;
  const refreshed = new Promise((resolve) => { firstRefresh = resolve; });
  const snapshot = { status: "RUNNING", resumeEventId: "event-0" };
  const sync = createTaskLiveSync({
    readTaskEvents: async function* () {
      throw new Error("SSE endpoint unavailable");
    },
    refreshSnapshot: async () => {
      refreshCount += 1;
      firstRefresh();
      return snapshot;
    },
    getCurrentSnapshot: () => snapshot,
    onState: (state) => states.push(state),
    pollIntervalMs: 5,
    reconnectDelaysMs: [1_000],
  });

  sync.start();
  await refreshed;
  await nextTurn(12);
  sync.stop();

  assert.ok(states.some((state) => state.phase === TASK_LIVE_PHASE.POLLING));
  assert.ok(refreshCount >= 2);
});

test("reset_required clears snapshot concurrency and reconnects from the new resume cursor", async () => {
  const subscriptions = [];
  const refreshes = [];
  let snapshot = { status: "RUNNING", resumeEventId: "event-old" };
  let secondOpened;
  const reconnected = new Promise((resolve) => { secondOpened = resolve; });
  const sync = createTaskLiveSync({
    readTaskEvents: async function* ({ afterEventId, onOpen, signal }) {
      subscriptions.push(afterEventId);
      onOpen();
      if (subscriptions.length === 1) {
        yield event({ eventId: "reset-1", eventType: "stream.reset_required" });
        return;
      }
      secondOpened();
      await new Promise((resolve) => signal.addEventListener("abort", resolve, { once: true }));
    },
    refreshSnapshot: async (options) => {
      refreshes.push(options);
      snapshot = { status: "RUNNING", resumeEventId: "event-reset" };
      return snapshot;
    },
    getCurrentSnapshot: () => snapshot,
    eventRefreshDelayMs: 0,
    reconnectDelaysMs: [1_000],
  });

  sync.start();
  await reconnected;
  sync.stop();

  assert.deepEqual(subscriptions, ["event-old", "event-reset"]);
  assert.deepEqual(refreshes, [{ reset: true, reason: "stream-reset", silent: true }]);
});
