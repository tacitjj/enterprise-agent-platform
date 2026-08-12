import assert from "node:assert/strict";
import test from "node:test";
import { createModelManagementApi } from "../src/api/modelManagementApi.js";
import {
  adaptModelDefinition,
  adaptModelDefinitionList,
  adaptPlatformDefaultRouteList,
  buildModelDefinitionPayload,
  buildPlatformRoutePayload,
  classifyModelManagementError,
  formatMicroCreditAsPoints,
  nextCommandIntent,
} from "../src/apiPortal/modelManagementAdapters.js";

test("model management API uses the published routes and exposes idempotency replay", async () => {
  const requests = [];
  const client = {
    get(path, options) {
      requests.push({ method: "GET", path, options });
      return Promise.resolve({ items: [] });
    },
    post(path, options) {
      requests.push({ method: "POST", path, options });
      return Promise.resolve({
        data: { modelDefinitionId: "model-1" },
        status: 200,
        headers: new Headers({ "Idempotency-Replayed": "true" }),
      });
    },
  };
  const api = createModelManagementApi(client);

  await api.listModelDefinitions({ signal: "list-signal" });
  await api.listPlatformDefaultRoutes({ signal: "route-list-signal" });
  const createResult = await api.registerModelDefinition(
    { modelCode: "GENERIC_CHAT" },
    { idempotencyKey: "model-definition:00000000-0000-4000-8000-000000000001" },
  );
  const routeResult = await api.setPlatformDefaultRoute(
    "TEXT_CHAT",
    { modelDefinitionId: "model-1" },
    { idempotencyKey: "model-route:00000000-0000-4000-8000-000000000002" },
  );

  assert.deepEqual(requests.map(({ method, path }) => `${method} ${path}`), [
    "GET /platform/model-definitions",
    "GET /platform/model-routes/defaults",
    "POST /platform/model-definitions",
    "POST /platform/model-routes/TEXT_CHAT/default",
  ]);
  assert.equal(requests[2].options.headers["Idempotency-Key"], "model-definition:00000000-0000-4000-8000-000000000001");
  assert.equal(requests[2].options.withResponse, true);
  assert.deepEqual(requests[3].options.json, { modelDefinitionId: "model-1" });
  assert.equal(createResult.replayed, true);
  assert.equal(routeResult.status, 200);
});

test("platform route list adapter keeps only the public route receipt fields", () => {
  const [route] = adaptPlatformDefaultRouteList({
    items: [{
      routeBindingId: "route-1",
      capabilityType: "TEXT_CHAT",
      modelDefinitionId: "model-1",
      stateVersion: 3,
      status: "ACTIVE",
      createdAt: "2026-08-11T00:00:00Z",
      credentialRef: "env:DIANLIAN_MODEL_SHOULD_NOT_SURVIVE",
    }],
  });

  assert.equal(route.capabilityLabel, "文本对话");
  assert.equal(route.modelDefinitionId, "model-1");
  assert.equal(Object.hasOwn(route, "credentialRef"), false);
  assert.throws(() => adaptPlatformDefaultRouteList({ rows: [] }), /items 数组/);
});

test("model payload stays provider-neutral and keeps monetary values as JSON strings", () => {
  const payload = buildModelDefinitionPayload({
    modelCode: "generic_chat_v1",
    displayName: "通用文本模型",
    providerCode: "provider_x",
    protocol: "OPENAI_COMPATIBLE",
    baseUrl: "https://models.example.test/v1/",
    providerModelName: "text-model-v1",
    credentialRef: "env:DIANLIAN_MODEL_PROVIDER_X_KEY",
    capabilityType: "TEXT_CHAT",
    temperature: "0.2",
    maxOutputTokens: "4096",
    inputRateMicroCreditPerMillionTokens: "9223372036854775806",
    outputRateMicroCreditPerMillionTokens: "0",
    reservationCeilingMicroCredit: "1000000",
  });

  assert.equal(payload.modelCode, "GENERIC_CHAT_V1");
  assert.equal(payload.providerCode, "PROVIDER_X");
  assert.equal(payload.baseUrl, "https://models.example.test/v1");
  assert.equal(typeof payload.inputRateMicroCreditPerMillionTokens, "string");
  assert.equal(payload.inputRateMicroCreditPerMillionTokens, "9223372036854775806");
  assert.equal(payload.credentialRef, "env:DIANLIAN_MODEL_PROVIDER_X_KEY");
  assert.deepEqual(Object.keys(buildPlatformRoutePayload("model-1")), ["modelDefinitionId"]);
});

test("model payload rejects a literal credential instead of an environment reference", () => {
  assert.throws(() => buildModelDefinitionPayload({
    modelCode: "GENERIC_CHAT",
    displayName: "通用文本模型",
    providerCode: "PROVIDER_X",
    protocol: "OPENAI_COMPATIBLE",
    baseUrl: "https://models.example.test/v1",
    providerModelName: "text-model-v1",
    credentialRef: "literal-credential-is-not-allowed",
    capabilityType: "TEXT_CHAT",
    temperature: "0.2",
    maxOutputTokens: "4096",
    inputRateMicroCreditPerMillionTokens: "1",
    outputRateMicroCreditPerMillionTokens: "1",
    reservationCeilingMicroCredit: "1",
  }), /环境变量引用/);
});

test("response adapter drops credentialRef, preserves exact amounts and labels unknown enums", () => {
  const model = adaptModelDefinition({
    modelDefinitionId: "model-1",
    modelCode: "GENERIC_CHAT",
    displayName: "通用文本模型",
    providerCode: "PROVIDER_X",
    protocol: "FUTURE_PROTOCOL",
    credentialRef: "env:DIANLIAN_MODEL_PROVIDER_X_KEY",
    capabilityType: "FUTURE_CAPABILITY",
    inputRateMicroCreditPerMillionTokens: "9223372036854775806",
    outputRateMicroCreditPerMillionTokens: "2",
    reservationCeilingMicroCredit: "3",
    status: "FUTURE_STATUS",
  });

  assert.equal(Object.hasOwn(model, "credentialRef"), false);
  assert.equal(model.inputRateMicroCreditPerMillionTokens, "9223372036854775806");
  assert.equal(model.capabilityLabel, "未知值（FUTURE_CAPABILITY）");
  assert.equal(model.protocolLabel, "未知值（FUTURE_PROTOCOL）");
  assert.equal(model.statusLabel, "未知值（FUTURE_STATUS）");
  assert.equal(formatMicroCreditAsPoints("9223372036854775806"), "9223372036854.775806");
});

test("list adapter rejects a malformed envelope and reports monetary contract drift", () => {
  assert.throws(() => adaptModelDefinitionList({ rows: [] }), /items 数组/);
  const [model] = adaptModelDefinitionList({
    items: [{
      modelDefinitionId: "model-1",
      inputRateMicroCreditPerMillionTokens: 1,
      outputRateMicroCreditPerMillionTokens: "0",
      reservationCeilingMicroCredit: "0",
    }],
  });
  assert.deepEqual(model.contractIssues, ["输入费率不是整数字符串", "预占上限不是正整数字符串"]);
});

test("command intent reuses a key only for the same canonical payload", () => {
  let sequence = 0;
  const uuidFactory = () => `00000000-0000-4000-8000-${String(++sequence).padStart(12, "0")}`;
  const first = nextCommandIntent(null, "model-definition", { b: 2, a: 1 }, uuidFactory);
  const replay = nextCommandIntent(first, "model-definition", { a: 1, b: 2 }, uuidFactory);
  const changed = nextCommandIntent(replay, "model-definition", { a: 1, b: 3 }, uuidFactory);

  assert.equal(replay.key, first.key);
  assert.notEqual(changed.key, first.key);
});

test("401 and 403 remain distinct page boundary states", () => {
  assert.equal(classifyModelManagementError({ status: 401 }), "unauthenticated");
  assert.equal(classifyModelManagementError({ status: 403 }), "forbidden");
  assert.equal(classifyModelManagementError({ status: 500 }), "error");
});
