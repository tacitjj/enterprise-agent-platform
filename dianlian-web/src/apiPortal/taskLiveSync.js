import { createBoundedEventDeduper, isTaskResetEvent } from "../api/sseEventStream.js";

export const TASK_LIVE_PHASE = Object.freeze({
  CONNECTING: "connecting",
  LIVE: "live",
  POLLING: "polling",
  PAUSED: "paused",
  ENDED: "ended",
});

const TERMINAL_TASK_STATUSES = new Set(["SUCCEEDED", "PARTIAL_SUCCESS", "FAILED", "CANCELLED"]);
const DEFAULT_RECONNECT_DELAYS_MS = Object.freeze([1_000, 2_000, 4_000, 8_000, 16_000, 30_000]);

export function isTerminalTaskStatus(status) {
  return TERMINAL_TASK_STATUSES.has(status);
}

export function reconnectDelayForAttempt(attempt, delays = DEFAULT_RECONNECT_DELAYS_MS) {
  if (!Number.isInteger(attempt) || attempt < 0) throw new TypeError("reconnect attempt must be a non-negative integer");
  if (!Array.isArray(delays) || delays.length === 0) throw new TypeError("reconnect delays are required");
  return delays[Math.min(attempt, delays.length - 1)];
}

function mergeRefreshOptions(current, next) {
  if (!current) return next;
  if (next.reset) return next;
  return current;
}

function errorDetail(error) {
  return error?.detail ?? error?.message ?? "实时连接暂不可用";
}

export function createTaskLiveSync({
  readTaskEvents,
  refreshSnapshot,
  getCurrentSnapshot = () => null,
  onState = () => {},
  visibilityTarget = globalThis.document,
  scheduler = globalThis,
  pollIntervalMs = 5_000,
  eventRefreshDelayMs = 180,
  reconnectDelaysMs = DEFAULT_RECONNECT_DELAYS_MS,
} = {}) {
  if (typeof readTaskEvents !== "function") throw new TypeError("readTaskEvents is required");
  if (typeof refreshSnapshot !== "function") throw new TypeError("refreshSnapshot is required");
  if (typeof scheduler?.setTimeout !== "function" || typeof scheduler?.clearTimeout !== "function") {
    throw new TypeError("scheduler must provide setTimeout and clearTimeout");
  }

  const deduper = createBoundedEventDeduper();
  let started = false;
  let stopped = false;
  let terminal = false;
  let cursor = null;
  let connectionController = null;
  let eventRefreshTimer = null;
  let pollTimer = null;
  let reconnectTimer = null;
  let reconnectAttempt = 0;
  let refreshFlight = null;
  let queuedRefresh = null;
  let phase = null;

  const isHidden = () => visibilityTarget?.visibilityState === "hidden";

  function publish(nextPhase, detail) {
    phase = nextPhase;
    onState(Object.freeze({ phase: nextPhase, detail }));
  }

  function clearTimer(timer) {
    if (timer !== null) scheduler.clearTimeout(timer);
    return null;
  }

  function clearScheduledWork() {
    eventRefreshTimer = clearTimer(eventRefreshTimer);
    pollTimer = clearTimer(pollTimer);
    reconnectTimer = clearTimer(reconnectTimer);
  }

  function abortConnection() {
    connectionController?.abort();
    connectionController = null;
  }

  function finish() {
    if (terminal) return;
    terminal = true;
    abortConnection();
    clearScheduledWork();
    publish(TASK_LIVE_PHASE.ENDED, "任务已到终态，快照同步已完成");
  }

  function applySnapshot(snapshot) {
    if (snapshot?.resumeEventId) cursor = snapshot.resumeEventId;
    if (isTerminalTaskStatus(snapshot?.status)) finish();
    return snapshot;
  }

  function requestRefresh(options) {
    if (stopped || terminal) return Promise.resolve(getCurrentSnapshot());
    if (refreshFlight) {
      queuedRefresh = mergeRefreshOptions(queuedRefresh, options);
      return refreshFlight;
    }

    refreshFlight = (async () => {
      let next = options;
      let snapshot = getCurrentSnapshot();
      while (next && !stopped && !terminal) {
        queuedRefresh = null;
        snapshot = applySnapshot(await refreshSnapshot(next));
        next = queuedRefresh;
      }
      return snapshot;
    })().finally(() => {
      refreshFlight = null;
    });
    return refreshFlight;
  }

  function scheduleEventRefresh() {
    if (eventRefreshTimer !== null || stopped || terminal) return;
    eventRefreshTimer = scheduler.setTimeout(() => {
      eventRefreshTimer = null;
      void requestRefresh({ reset: false, reason: "event", silent: true }).catch((error) => {
        if (!stopped && !terminal && phase === TASK_LIVE_PHASE.LIVE) {
          publish(TASK_LIVE_PHASE.LIVE, `已收到任务动态，快照刷新失败：${errorDetail(error)}`);
        }
      });
    }, eventRefreshDelayMs);
  }

  function schedulePoll() {
    if (pollTimer !== null || stopped || terminal || phase !== TASK_LIVE_PHASE.POLLING) return;
    pollTimer = scheduler.setTimeout(() => {
      pollTimer = null;
      void requestRefresh({ reset: false, reason: "poll", silent: true })
        .catch(() => null)
        .finally(() => schedulePoll());
    }, pollIntervalMs);
  }

  function scheduleReconnect(connect) {
    if (reconnectTimer !== null || stopped || terminal || isHidden()) return;
    const delay = reconnectDelayForAttempt(reconnectAttempt, reconnectDelaysMs);
    reconnectAttempt += 1;
    reconnectTimer = scheduler.setTimeout(() => {
      reconnectTimer = null;
      void connect(true);
    }, delay);
  }

  function enterPolling(error, connect) {
    if (stopped || terminal || isHidden()) return;
    publish(TASK_LIVE_PHASE.POLLING, `实时连接暂不可用，正在自动轮询：${errorDetail(error)}`);
    void requestRefresh({ reset: false, reason: "stream-fallback", silent: true }).catch(() => null);
    schedulePoll();
    scheduleReconnect(connect);
  }

  async function connect(isReconnect = false) {
    if (stopped || terminal) return;
    if (isHidden()) {
      pause();
      return;
    }

    abortConnection();
    const controller = new AbortController();
    connectionController = controller;
    if (phase !== TASK_LIVE_PHASE.POLLING) {
      publish(TASK_LIVE_PHASE.CONNECTING, isReconnect ? "正在恢复任务动态连接" : "正在连接任务动态");
    }

    try {
      const events = readTaskEvents({
        afterEventId: cursor ?? undefined,
        signal: controller.signal,
        deduper,
        onOpen: () => {
          if (stopped || terminal || controller.signal.aborted) return;
          reconnectAttempt = 0;
          pollTimer = clearTimer(pollTimer);
          publish(TASK_LIVE_PHASE.LIVE, "任务动态实时同步中");
        },
      });

      for await (const event of events) {
        if (stopped || terminal || controller.signal.aborted) return;
        cursor = event.eventId;
        if (isTaskResetEvent(event)) {
          controller.abort();
          if (connectionController === controller) connectionController = null;
          eventRefreshTimer = clearTimer(eventRefreshTimer);
          try {
            await requestRefresh({ reset: true, reason: "stream-reset", silent: true });
          } catch (error) {
            enterPolling(error, connect);
            return;
          }
          if (!stopped && !terminal) void connect(true);
          return;
        }
        scheduleEventRefresh();
      }

      if (!controller.signal.aborted) throw new Error("任务动态连接已断开");
    } catch (error) {
      if (stopped || terminal || controller.signal.aborted || isHidden()) return;
      if (connectionController === controller) connectionController = null;
      enterPolling(error, connect);
    }
  }

  function pause() {
    if (stopped || terminal) return;
    abortConnection();
    clearScheduledWork();
    publish(TASK_LIVE_PHASE.PAUSED, "页面在后台，已暂停任务更新");
  }

  function resume() {
    if (stopped || terminal || isHidden()) return;
    publish(TASK_LIVE_PHASE.CONNECTING, "正在恢复任务动态连接");
    void requestRefresh({ reset: false, reason: "visibility-resume", silent: true })
      .then(() => {
        if (!stopped && !terminal) void connect(true);
      })
      .catch((error) => enterPolling(error, connect));
  }

  function handleVisibilityChange() {
    if (isHidden()) pause();
    else resume();
  }

  return Object.freeze({
    start() {
      if (started) return;
      started = true;
      stopped = false;
      const snapshot = getCurrentSnapshot();
      cursor = snapshot?.resumeEventId ?? null;
      visibilityTarget?.addEventListener?.("visibilitychange", handleVisibilityChange);
      if (isTerminalTaskStatus(snapshot?.status)) finish();
      else if (isHidden()) pause();
      else void connect(false);
    },
    stop() {
      if (stopped) return;
      stopped = true;
      abortConnection();
      clearScheduledWork();
      visibilityTarget?.removeEventListener?.("visibilitychange", handleVisibilityChange);
    },
  });
}
