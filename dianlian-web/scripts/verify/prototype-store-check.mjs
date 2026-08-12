import assert from "node:assert/strict";
import {
  createPrototypeInitialState,
  GROUP_MODE,
  PROTOTYPE_ACTION,
} from "../../src/data/prototypeData.js";
import {
  prototypeReducer,
  selectConversationViewModel,
} from "../../src/state/prototypeStore.jsx";

const base = createPrototypeInitialState();

const blocked = prototypeReducer(base, {
  type: PROTOTYPE_ACTION.ADVANCE_STEP,
  payload: { taskId: "task-contract-001" },
});
assert.equal(blocked, base, "合同人工确认阶段不能被手动推进绕过");

const guided = prototypeReducer(base, {
  type: PROTOTYPE_ACTION.GUIDE_TASK,
  payload: { taskId: "task-graphic-001", text: "增加方形尺寸", impact: "LOW" },
});
const guidedRun = guided.runsById[guided.tasksById["task-graphic-001"].currentRunId];
assert.equal(guidedRun.runNo, 2, "执行中引导必须产生新的 Run");
assert.equal(guidedRun.previousRunId, "run-graphic-001", "新 Run 必须保留上一轮引用");

const plain = prototypeReducer(base, {
  type: PROTOTYPE_ACTION.SEND_GROUP_MESSAGE,
  payload: {
    conversationId: "conversation-project",
    text: "普通群消息",
    targetAgentIds: [],
    commandId: "plain-1",
  },
});
assert.equal(plain.pointAccountsById["point-account-xinghai"].available, 12450, "普通群消息不能扣智点");

const single = prototypeReducer(base, {
  type: PROTOTYPE_ACTION.SEND_GROUP_MESSAGE,
  payload: {
    conversationId: "conversation-project",
    text: "请审核合同",
    targetAgentIds: ["agent-contract"],
    mode: GROUP_MODE.SINGLE_TARGET,
    commandId: "single-1",
  },
});
const singleConversation = selectConversationViewModel(single, "conversation-project");
assert.equal(single.pointAccountsById["point-account-xinghai"].available, 12415, "单员工调用应扣除 35 智点");
assert.equal(singleConversation.pendingInvocations.length, 0, "短对话调用不能永久停在 QUEUED");
assert.ok(singleConversation.messages.some((message) => message.senderType === "AGENT"), "单员工调用必须返回员工消息");

const duplicate = prototypeReducer(single, {
  type: PROTOTYPE_ACTION.SEND_GROUP_MESSAGE,
  payload: {
    conversationId: "conversation-project",
    text: "请审核合同",
    targetAgentIds: ["agent-contract"],
    mode: GROUP_MODE.SINGLE_TARGET,
    commandId: "single-1",
  },
});
assert.equal(duplicate, single, "相同命令 ID 不能重复建消息或扣智点");

const primary = prototypeReducer(base, {
  type: PROTOTYPE_ACTION.SEND_GROUP_MESSAGE,
  payload: {
    conversationId: "conversation-project",
    text: "协同准备提案",
    targetAgentIds: ["agent-graphic", "agent-quotation"],
    mode: GROUP_MODE.PRIMARY_SUMMARY,
    primaryAgentId: "agent-quotation",
    commandId: "primary-1",
  },
});
assert.equal(primary.pointAccountsById["point-account-xinghai"].available, 12355, "主责汇总应预占两位员工和汇总开销共 95 智点");
assert.equal(Object.keys(primary.tasksById).length, 4, "主责汇总必须创建一个受控协作任务");

console.log("prototype store gates: passed");
