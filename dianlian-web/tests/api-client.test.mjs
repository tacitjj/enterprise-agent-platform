import assert from "node:assert/strict";
import test from "node:test";
import { createHttpClient } from "../src/api/httpClient.js";
import { createAuthApi } from "../src/api/authApi.js";
import {
  clearAccessToken,
  configureUnauthorizedHandler,
  getAccessToken,
} from "../src/api/accessTokenStore.js";
import { ProblemDetail } from "../src/api/problem.js";
import { createTaskApi } from "../src/api/taskApi.js";
import { createEmployeeManagementApi } from "../src/api/employeeManagementApi.js";
import { createConversationApi } from "../src/api/conversationApi.js";
import { DATA_SOURCE_MODE, resolveDataSourceMode, selectDataSource } from "../src/dataSources/index.js";

test("converts a failed JSON response into ProblemDetail", async () => {
  const client = createHttpClient({
    baseUrl: "https://api.example.test/api/v1",
    fetchImpl: async () => new Response(JSON.stringify({
      code: "TASK_INPUT_INVALID",
      message: "请补充任务目标",
      traceId: "trace-test-1",
      retryable: true,
      action: "REFRESH_TASK",
    }), {
      status: 422,
      statusText: "Unprocessable Content",
      headers: { "content-type": "application/problem+json" },
    }),
  });

  await assert.rejects(
    () => client.get("/tasks/task-1"),
    (error) => {
      assert.ok(error instanceof ProblemDetail);
      assert.equal(error.status, 422);
      assert.equal(error.code, "TASK_INPUT_INVALID");
      assert.equal(error.detail, "请补充任务目标");
      assert.equal(error.traceId, "trace-test-1");
      assert.equal(error.retryable, true);
      assert.equal(error.action, "REFRESH_TASK");
      assert.equal(error.toJSON().action, "REFRESH_TASK");
      return true;
    },
  );
});

test("prepared task creation reuses its idempotency key and payload", async () => {
  const requests = [];
  const client = createHttpClient({
    baseUrl: "https://api.example.test/api/v1",
    accessTokenProvider: () => "jwt-access-token",
    fetchImpl: async (url, init) => {
      requests.push({
        url,
        key: init.headers.get("Idempotency-Key"),
        authorization: init.headers.get("Authorization"),
        body: init.body,
      });
      return new Response(JSON.stringify({ taskId: "task-server-1" }), {
        status: 201,
        headers: { "content-type": "application/json" },
      });
    },
  });
  const tasks = createTaskApi(client);
  const payload = { agentId: "agent-quotation", goal: "生成项目报价" };
  const command = tasks.prepareCreateTask(payload, {
    idempotencyKey: "task-command-fixed",
  });

  payload.goal = "调用方后续误改的内容";
  const first = await command.execute();
  const second = await command.execute();

  assert.equal(first.taskId, "task-server-1");
  assert.equal(second.taskId, "task-server-1");
  assert.equal(command.idempotencyKey, "task-command-fixed");
  assert.deepEqual(requests.map((request) => request.key), ["task-command-fixed", "task-command-fixed"]);
  assert.deepEqual(requests.map((request) => request.authorization), ["Bearer jwt-access-token", "Bearer jwt-access-token"]);
  assert.deepEqual(requests.map((request) => JSON.parse(request.body)), [
    { agentId: "agent-quotation", goal: "生成项目报价" },
    { agentId: "agent-quotation", goal: "生成项目报价" },
  ]);
  assert.ok(requests.every((request) => request.url === "https://api.example.test/api/v1/tasks"));
});

test("employee hiring uses the enterprise endpoint and caller-owned idempotency key", async () => {
  const calls = [];
  const client = createHttpClient({
    baseUrl: "/api/v1",
    accessTokenProvider: () => "jwt-admin-token",
    fetchImpl: async (url, init) => {
      calls.push({
        url,
        key: init.headers.get("Idempotency-Key"),
        authorization: init.headers.get("Authorization"),
        body: JSON.parse(init.body),
      });
      return new Response(JSON.stringify({ enterpriseAgentId: "agent-1" }), {
        status: 201,
        headers: { "content-type": "application/json" },
      });
    },
  });
  const employees = createEmployeeManagementApi(client);
  const payload = {
    agentVersionId: "version-1",
    employeeCode: "quotation-01",
    displayName: "报价专员",
  };

  const result = await employees.hireEnterpriseAgent(payload, { idempotencyKey: "hire:fixed-command-01" });

  assert.equal(result.enterpriseAgentId, "agent-1");
  assert.deepEqual(calls, [{
    url: "/api/v1/enterprise/agents",
    key: "hire:fixed-command-01",
    authorization: "Bearer jwt-admin-token",
    body: payload,
  }]);
});

test("employee configuration commands preserve ETag, path identity, and separate idempotency keys", async () => {
  const calls = [];
  let responseIndex = 0;
  const responseEtags = ['"agent-state-1"', '"agent-state-2"', '"agent-state-3"'];
  const client = createHttpClient({
    baseUrl: "/api/v1",
    accessTokenProvider: () => "jwt-enterprise-admin-token",
    fetchImpl: async (url, init) => {
      calls.push({
        url,
        method: init.method,
        ifMatch: init.headers.get("If-Match"),
        key: init.headers.get("Idempotency-Key"),
        authorization: init.headers.get("Authorization"),
        body: init.body ? JSON.parse(init.body) : null,
      });
      const etag = responseEtags[responseIndex];
      responseIndex += 1;
      return new Response(JSON.stringify({ enterpriseAgentId: "agent/1", stateVersion: responseIndex }), {
        status: init.method === "GET" ? 200 : 201,
        headers: { "content-type": "application/json", etag },
      });
    },
  });
  const employees = createEmployeeManagementApi(client);
  const configuration = {
    displayNameSnapshot: "报价专员",
    profile: "负责形成可复核报价",
    enterpriseInstructions: "金额统一保留两位小数",
    modelPolicyMode: "PLATFORM_DEFAULT",
    knowledgeScopeMode: "NONE",
    visibilityScope: "TENANT",
  };

  const detail = await employees.getEnterpriseAgent("agent/1");
  const configured = await employees.createEnterpriseAgentConfigurationVersion("agent/1", configuration, {
    etag: detail.etag,
    idempotencyKey: "agent-config:fixed-command-01",
  });
  const activation = { configurationVersionId: "configuration-1" };
  const activated = await employees.activateEnterpriseAgent("agent/1", activation, {
    etag: configured.etag,
    idempotencyKey: "agent-activate:fixed-command-01",
  });

  assert.equal(detail.etag, '"agent-state-1"');
  assert.equal(configured.etag, '"agent-state-2"');
  assert.equal(activated.etag, '"agent-state-3"');
  assert.deepEqual(calls, [
    {
      url: "/api/v1/enterprise/agents/agent%2F1",
      method: "GET",
      ifMatch: null,
      key: null,
      authorization: "Bearer jwt-enterprise-admin-token",
      body: null,
    },
    {
      url: "/api/v1/enterprise/agents/agent%2F1/configuration-versions",
      method: "POST",
      ifMatch: '"agent-state-1"',
      key: "agent-config:fixed-command-01",
      authorization: "Bearer jwt-enterprise-admin-token",
      body: configuration,
    },
    {
      url: "/api/v1/enterprise/agents/agent%2F1/activate",
      method: "POST",
      ifMatch: '"agent-state-2"',
      key: "agent-activate:fixed-command-01",
      authorization: "Bearer jwt-enterprise-admin-token",
      body: activation,
    },
  ]);

  await assert.rejects(
    () => employees.activateEnterpriseAgent("agent/1", activation, { idempotencyKey: "agent-activate:new-command-01" }),
    /etag is required/,
  );
});

test("employee mutation responses never reuse the submitted ETag when the server omits a new one", async () => {
  const client = createHttpClient({
    baseUrl: "/api/v1",
    fetchImpl: async () => new Response(JSON.stringify({ enterpriseAgentId: "agent-1" }), {
      status: 201,
      headers: { "content-type": "application/json" },
    }),
  });
  const employees = createEmployeeManagementApi(client);

  const result = await employees.createEnterpriseAgentConfigurationVersion("agent-1", {
    displayNameSnapshot: "报价专员",
    profile: "负责形成可复核报价",
    enterpriseInstructions: "",
    modelPolicyMode: "PLATFORM_DEFAULT",
    knowledgeScopeMode: "NONE",
    visibilityScope: "TENANT",
  }, {
    etag: '"agent-state-1"',
    idempotencyKey: "agent-config:fixed-command-02",
  });

  assert.equal(result.etag, null);
});

test("platform employee versions use the published-version endpoints and preserve the publish key", async () => {
  const calls = [];
  const client = createHttpClient({
    baseUrl: "/api/v1",
    accessTokenProvider: () => "jwt-platform-token",
    fetchImpl: async (url, init) => {
      calls.push({
        url,
        method: init.method,
        key: init.headers.get("Idempotency-Key"),
        authorization: init.headers.get("Authorization"),
        body: init.body ? JSON.parse(init.body) : null,
      });
      return new Response(JSON.stringify(init.method === "GET"
        ? { items: [] }
        : { agentVersionId: "version-1" }), {
        status: init.method === "GET" ? 200 : 201,
        headers: { "content-type": "application/json" },
      });
    },
  });
  const employees = createEmployeeManagementApi(client);
  const payload = {
    templateCode: "quotation-specialist",
    templateName: "报价专员",
    templateDescription: "形成可复核的报价成果",
    version: "v1.0.0",
    capabilityCode: "QUOTATION",
    inputSchema: { schemaId: "quotation.input", schemaVersion: "1", jsonSchema: { type: "object" } },
    executionTemplate: { templateCode: "quotation-flow", version: "1", steps: [] },
    pointEstimateMicroCredit: "12500000",
    enterpriseVisibility: { mode: "ALL", tenantIds: [] },
  };

  assert.deepEqual(await employees.listPlatformVersions(), { items: [] });
  assert.equal((await employees.publishPlatformVersion(payload, { idempotencyKey: "publish:fixed-command-01" })).agentVersionId, "version-1");
  assert.deepEqual(calls, [
    {
      url: "/api/v1/platform/agent-versions",
      method: "GET",
      key: null,
      authorization: "Bearer jwt-platform-token",
      body: null,
    },
    {
      url: "/api/v1/platform/agent-versions",
      method: "POST",
      key: "publish:fixed-command-01",
      authorization: "Bearer jwt-platform-token",
      body: payload,
    },
  ]);
});

test("defaults to prototype and never falls back when api mode fails", async () => {
  assert.equal(resolveDataSourceMode({}), DATA_SOURCE_MODE.PROTOTYPE);
  assert.throws(
    () => resolveDataSourceMode({ MODE: "production" }),
    /VITE_DATA_SOURCE must be explicitly set/,
  );

  const expected = new Error("api unavailable");
  let prototypeCalled = false;
  const source = selectDataSource({
    mode: "API",
    apiSource: { getSession: async () => { throw expected; } },
    prototypeSource: { getSession: async () => { prototypeCalled = true; } },
  });

  await assert.rejects(() => source.getSession(), expected);
  assert.equal(prototypeCalled, false);
});

test("builds task endpoints and sends Bearer JWT on the SSE fetch stream", async () => {
  const calls = [];
  const client = createHttpClient({
    baseUrl: "/api/v1",
    accessTokenProvider: () => "jwt-stream-token",
    fetchImpl: async (url, init) => {
      calls.push({
        url,
        etag: init.headers.get("If-None-Match"),
        accept: init.headers.get("Accept"),
        authorization: init.headers.get("Authorization"),
      });
      return new Response(JSON.stringify({ id: "task/1" }), {
        status: 200,
        headers: { "content-type": "application/json", etag: '"task-v3"' },
      });
    },
  });
  const tasks = createTaskApi(client);

  const snapshot = await tasks.getTask("task/1", { etag: '"task-v2"' });
  await tasks.openTaskEvents("task/1", {
    afterEventId: "event 9",
  });

  assert.deepEqual(calls, [
    {
      url: "/api/v1/tasks/task%2F1",
      etag: '"task-v2"',
      accept: "application/json",
      authorization: "Bearer jwt-stream-token",
    },
    {
      url: "/api/v1/tasks/task%2F1/events?afterEventId=event+9",
      etag: null,
      accept: "text/event-stream",
      authorization: "Bearer jwt-stream-token",
    },
  ]);
  assert.equal(snapshot.task.id, "task/1");
  assert.equal(snapshot.etag, '"task-v3"');
  assert.equal(snapshot.notModified, false);
});

test("web login uses one auth endpoint, includes the refresh cookie channel, and keeps access token in memory", async () => {
  clearAccessToken();
  const requests = [];
  const client = createHttpClient({
    baseUrl: "/api/v1",
    credentials: "include",
    fetchImpl: async (url, init) => {
      requests.push({ url, credentials: init.credentials, body: JSON.parse(init.body) });
      return new Response(JSON.stringify({
        tokenType: "Bearer",
        accessToken: "jwt-login-token",
        expiresIn: 900,
        refreshToken: null,
        refreshExpiresIn: 2_592_000,
        sessionId: "session-1",
        clientType: "WEB",
      }), { status: 200, headers: { "content-type": "application/json" } });
    },
  });
  const auth = createAuthApi(client);

  await auth.login({ username: "alice", password: "secret", clientType: "WEB" });

  assert.equal(getAccessToken(), "jwt-login-token");
  assert.deepEqual(requests, [{
    url: "/api/v1/auth/login",
    credentials: "include",
    body: { username: "alice", password: "secret", clientType: "WEB", deviceId: null, deviceName: null },
  }]);
  clearAccessToken();
});

test("concurrent 401 responses share one refresh rotation and retry with the new access token", async () => {
  clearAccessToken();
  let refreshCalls = 0;
  configureUnauthorizedHandler(async () => {
    refreshCalls += 1;
    await Promise.resolve();
    return "jwt-refreshed-token";
  });
  const seenAuthorization = [];
  const client = createHttpClient({
    baseUrl: "/api/v1",
    fetchImpl: async (_url, init) => {
      const authorization = init.headers.get("Authorization");
      seenAuthorization.push(authorization);
      if (authorization !== "Bearer jwt-refreshed-token") {
        return new Response(JSON.stringify({ code: "AUTHENTICATION_REQUIRED" }), {
          status: 401,
          headers: { "content-type": "application/problem+json" },
        });
      }
      return new Response(JSON.stringify({ ready: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });

  const results = await Promise.all([client.get("/session"), client.get("/office")]);

  assert.deepEqual(results, [{ ready: true }, { ready: true }]);
  assert.equal(refreshCalls, 1);
  assert.deepEqual(seenAuthorization, [null, null, "Bearer jwt-refreshed-token", "Bearer jwt-refreshed-token"]);
  configureUnauthorizedHandler(null);
  clearAccessToken();
});

test("SSE stream retries one 401 with the same cursor after access-token recovery", async () => {
  clearAccessToken();
  configureUnauthorizedHandler(async () => "jwt-stream-refreshed");
  const calls = [];
  const client = createHttpClient({
    baseUrl: "/api/v1",
    fetchImpl: async (url, init) => {
      calls.push({ url, authorization: init.headers.get("Authorization") });
      if (!init.headers.get("Authorization")) {
        return new Response(JSON.stringify({ code: "AUTHENTICATION_REQUIRED" }), {
          status: 401,
          headers: { "content-type": "application/problem+json" },
        });
      }
      return new Response("data: connected\n\n", {
        status: 200,
        headers: { "content-type": "text/event-stream" },
      });
    },
  });

  try {
    const response = await client.stream("/tasks/task-1/events", {
      query: { afterEventId: "event-9" },
      headers: { Accept: "text/event-stream" },
    });

    assert.equal(response.status, 200);
    assert.deepEqual(calls, [
      { url: "/api/v1/tasks/task-1/events?afterEventId=event-9", authorization: null },
      { url: "/api/v1/tasks/task-1/events?afterEventId=event-9", authorization: "Bearer jwt-stream-refreshed" },
    ]);
  } finally {
    configureUnauthorizedHandler(null);
    clearAccessToken();
  }
});

test("conversation API keeps list, history, create, and send contracts on the shared client", async () => {
  const calls = [];
  const client = {
    get: async (path, options) => {
      calls.push({ method: "GET", path, options });
      return [];
    },
    post: async (path, options) => {
      calls.push({ method: "POST", path, options });
      return { resource: {} };
    },
  };
  const conversations = createConversationApi(client);

  await conversations.listConversations({ signal: "list-signal" });
  await conversations.createConversation({ type: "GROUP" }, { idempotencyKey: "conversation:create:123456" });
  await conversations.listConversationMessages("conversation/1", { afterSequenceNo: 8, limit: 80 });
  await conversations.sendConversationMessage("conversation/1", { text: "你好" }, { idempotencyKey: "conversation:message:123456" });

  assert.deepEqual(calls, [
    { method: "GET", path: "/conversations", options: { signal: "list-signal" } },
    { method: "POST", path: "/conversations", options: { headers: { "Idempotency-Key": "conversation:create:123456" }, json: { type: "GROUP" } } },
    { method: "GET", path: "/conversations/conversation%2F1/messages", options: { query: { afterSequenceNo: 8, limit: 80 } } },
    { method: "POST", path: "/conversations/conversation%2F1/messages", options: { headers: { "Idempotency-Key": "conversation:message:123456" }, json: { text: "你好" } } },
  ]);
});
