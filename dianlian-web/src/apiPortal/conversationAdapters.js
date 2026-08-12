export const CONVERSATION_PERMISSIONS = Object.freeze({
  READ: "conversation.read",
  CREATE: "conversation.create",
  SEND: "conversation.message.send",
  INVOKE_AGENT: "conversation.agent.invoke",
});

const MESSAGE_TRIGGERS = new Set(["DIRECT", "MENTION", "SELECTION", "REPLY"]);

function requireObject(value, name) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  return value;
}

function requireText(value, name) {
  const normalized = String(value ?? "").trim();
  if (!normalized) throw new TypeError(`${name} is required`);
  return normalized;
}

function requirePositiveInteger(value, name) {
  const normalized = Number(value);
  if (!Number.isInteger(normalized) || normalized < 1) {
    throw new TypeError(`${name} must be a positive integer`);
  }
  return normalized;
}

function mapHumanMember(value) {
  const member = requireObject(value, "conversation human member");
  return {
    id: requireText(member.userId, "humanMember.userId"),
    name: requireText(member.displayName, "humanMember.displayName"),
    avatarUrl: member.avatarUrl ? String(member.avatarUrl) : null,
    role: requireText(member.role, "humanMember.role"),
  };
}

function mapAgent(value, officeAgentsById) {
  const agent = requireObject(value, "conversation agent");
  const id = requireText(agent.enterpriseAgentId, "agent.enterpriseAgentId");
  const officeAgent = officeAgentsById.get(id);
  return {
    id,
    name: requireText(agent.displayName, "agent.displayName"),
    roleName: requireText(agent.roleName, "agent.roleName"),
    avatarUrl: agent.avatarUrl ? String(agent.avatarUrl) : officeAgent?.image ?? null,
  };
}

export function mapConversationSummary(value, {
  currentUserId,
  officeAgents = [],
} = {}) {
  const conversation = requireObject(value, "conversation");
  const officeAgentsById = new Map(officeAgents.map((agent) => [String(agent.id), agent]));
  const type = requireText(conversation.type, "conversation.type");
  if (!["DIRECT", "GROUP"].includes(type)) throw new TypeError(`unsupported conversation type: ${type}`);
  const humans = (conversation.humanMembers ?? []).map(mapHumanMember);
  const agents = (conversation.agents ?? []).map((agent) => mapAgent(agent, officeAgentsById));
  const otherHumans = humans.filter((member) => member.id !== String(currentUserId ?? ""));
  const kind = type === "GROUP"
    ? "GROUP"
    : agents.length === 1
      ? "DIRECT_AGENT"
      : "DIRECT_HUMAN";

  return {
    id: requireText(conversation.conversationId, "conversation.conversationId"),
    type,
    kind,
    title: requireText(conversation.title, "conversation.title"),
    status: requireText(conversation.status, "conversation.status"),
    membershipVersion: requirePositiveInteger(conversation.membershipVersion, "conversation.membershipVersion"),
    humans,
    otherHumans,
    agents,
    lastMessagePreview: conversation.lastMessagePreview ? String(conversation.lastMessagePreview) : "",
    lastMessageAt: conversation.lastMessageAt ? String(conversation.lastMessageAt) : null,
    unreadCount: Math.max(0, Number(conversation.unreadCount) || 0),
    allowedActions: Array.isArray(conversation.allowedActions)
      ? conversation.allowedActions.map(String)
      : [],
  };
}

export function mapConversationMessage(value, { currentUserId } = {}) {
  const message = requireObject(value, "conversation message");
  const senderType = requireText(message.senderType, "message.senderType");
  return {
    id: requireText(message.messageId, "message.messageId"),
    conversationId: requireText(message.conversationId, "message.conversationId"),
    sequenceNo: requirePositiveInteger(message.sequenceNo, "message.sequenceNo"),
    senderType,
    senderUserId: message.senderUserId ? String(message.senderUserId) : null,
    senderAgentId: message.senderAgentId ? String(message.senderAgentId) : null,
    senderName: requireText(message.senderDisplayName, "message.senderDisplayName"),
    senderAvatarUrl: message.senderAvatarUrl ? String(message.senderAvatarUrl) : null,
    text: requireText(message.text, "message.text"),
    replyToMessageId: message.replyToMessageId ? String(message.replyToMessageId) : null,
    targetAgentIds: Array.isArray(message.targetAgentIds) ? message.targetAgentIds.map(String) : [],
    aiStatus: message.aiStatus ? String(message.aiStatus) : null,
    knowledgeState: message.knowledgeState ? String(message.knowledgeState) : null,
    memoryState: message.memoryState ? String(message.memoryState) : null,
    chargedPoints: String(message.chargedPoints ?? "0"),
    createdAt: requireText(message.createdAt, "message.createdAt"),
    isOwn: senderType === "HUMAN" && String(message.senderUserId ?? "") === String(currentUserId ?? ""),
  };
}

export function mapConversationMessagePage(value, options) {
  const page = requireObject(value, "conversation message page");
  return {
    items: (page.items ?? []).map((message) => mapConversationMessage(message, options)),
    upToSequenceNo: Math.max(0, Number(page.upToSequenceNo) || 0),
    hasMore: Boolean(page.hasMore),
    membershipVersion: requirePositiveInteger(page.membershipVersion, "messagePage.membershipVersion"),
  };
}

export function buildCreateGroupPayload({ title, participantUserIds = [], enterpriseAgentIds = [] }) {
  return {
    type: "GROUP",
    title: requireText(title, "title"),
    participantUserIds: [...new Set(participantUserIds.map((id) => requireText(id, "participantUserId")))],
    enterpriseAgentIds: [...new Set(enterpriseAgentIds.map((id) => requireText(id, "enterpriseAgentId")))],
  };
}

export function buildCreateAgentDirectPayload({ enterpriseAgentId, title }) {
  return {
    type: "DIRECT",
    title: requireText(title, "title"),
    participantUserIds: [],
    enterpriseAgentIds: [requireText(enterpriseAgentId, "enterpriseAgentId")],
  };
}

export function findAgentDirectConversation(conversations, enterpriseAgentId) {
  const agentId = requireText(enterpriseAgentId, "enterpriseAgentId");
  if (!Array.isArray(conversations)) throw new TypeError("conversations must be an array");
  return conversations.find((conversation) => (
    conversation?.kind === "DIRECT_AGENT"
      && Array.isArray(conversation.agents)
      && conversation.agents.some((agent) => String(agent.id) === agentId)
  )) ?? null;
}

export function buildConversationMessagePayload({
  clientMessageId,
  text,
  targets = [],
  membershipVersion,
  replyToMessageId = null,
}) {
  const targetIds = new Set();
  const normalizedTargets = targets.map((value) => {
    const target = requireObject(value, "message target");
    const enterpriseAgentId = requireText(target.enterpriseAgentId, "target.enterpriseAgentId");
    const triggerType = requireText(target.triggerType, "target.triggerType");
    if (!MESSAGE_TRIGGERS.has(triggerType)) throw new TypeError(`unsupported message trigger: ${triggerType}`);
    if (targetIds.has(enterpriseAgentId)) throw new TypeError("message targets must be unique");
    targetIds.add(enterpriseAgentId);
    const targetReplyId = triggerType === "REPLY"
      ? requireText(target.replyToMessageId ?? replyToMessageId, "target.replyToMessageId")
      : null;
    return { enterpriseAgentId, triggerType, replyToMessageId: targetReplyId };
  });

  return {
    clientMessageId: requireText(clientMessageId, "clientMessageId"),
    text: requireText(text, "text"),
    targets: normalizedTargets,
    collaborationMode: normalizedTargets.length > 1 ? "PARALLEL_SEPARATE" : "SINGLE_TARGET",
    primaryAgentId: null,
    replyToMessageId: replyToMessageId ? requireText(replyToMessageId, "replyToMessageId") : null,
    expectedMembershipVersion: requirePositiveInteger(membershipVersion, "membershipVersion"),
  };
}

export function prepareStableConversationCommand(previous, {
  prefix,
  payload,
  randomUUID = globalThis.crypto?.randomUUID?.bind(globalThis.crypto),
}) {
  const fingerprint = JSON.stringify(payload);
  if (previous?.fingerprint === fingerprint) return previous;
  if (typeof randomUUID !== "function") throw new Error("crypto.randomUUID is required to create conversation commands");
  const id = randomUUID();
  return Object.freeze({
    fingerprint,
    idempotencyKey: `${requireText(prefix, "prefix")}:${id}`,
    clientMessageId: `web:${id}`,
  });
}
