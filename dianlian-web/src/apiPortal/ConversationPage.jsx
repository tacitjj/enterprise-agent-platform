import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  IconAt,
  IconBriefcase,
  IconBuildingCommunity,
  IconCheck,
  IconCoinYuan,
  IconListCheck,
  IconMessageCircle2,
  IconMessages,
  IconPaperclip,
  IconPlus,
  IconRefresh,
  IconMessageReply,
  IconSend2,
  IconUsersGroup,
  IconX,
} from "@tabler/icons-react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { BrandLogo } from "../components/BrandLogo.jsx";
import {
  buildConversationMessagePayload,
  buildCreateAgentDirectPayload,
  buildCreateGroupPayload,
  CONVERSATION_PERMISSIONS,
  findAgentDirectConversation,
  mapConversationMessage,
  mapConversationMessagePage,
  mapConversationSummary,
  prepareStableConversationCommand,
} from "./conversationAdapters.js";
import "./conversation-page.css";

function errorText(error, fallback) {
  return error?.detail ?? error?.message ?? fallback;
}

function messageTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

const AI_STATUS_LABELS = Object.freeze({
  QUEUED: "AI 等待处理",
  RUNNING: "AI 正在处理",
  RESPONSE_RECEIVED: "AI 回复已生成，正在结算",
  USAGE_PENDING: "AI 回复待确认用量",
  COMPLETED: "AI 已完成",
  BLOCKED_ACCESS: "AI 因访问权限停止",
  BLOCKED_CONTEXT: "AI 因上下文不可用停止",
  FAILED_BILLING: "AI 因智点结算失败停止",
  FAILED_PROVIDER: "AI 模型调用失败",
  FAILED: "AI 处理失败",
  CANCELLED: "AI 已取消",
});

const AI_POLL_INTERVAL_MS = 3_000;
const AI_POLL_MAX_ATTEMPTS = 40;
const AI_POLL_MAX_FAILURES = 4;
const AI_POLL_MAX_BACKOFF_MS = 12_000;
const AI_POLL_MAX_DURATION_MS = 120_000;
const AI_PENDING_STATUSES = new Set(["QUEUED", "RUNNING", "RESPONSE_RECEIVED", "USAGE_PENDING"]);
const AI_FAILED_STATUSES = new Set([
  "BLOCKED_ACCESS",
  "BLOCKED_CONTEXT",
  "FAILED_BILLING",
  "FAILED_PROVIDER",
  "FAILED",
  "CANCELLED",
]);

function aiWaitOutcome(items, sourceMessageId) {
  const sourceMessage = items.find((message) => message.id === sourceMessageId);
  if (!sourceMessage?.aiStatus || AI_PENDING_STATUSES.has(sourceMessage.aiStatus)) {
    return { phase: "waiting", status: sourceMessage?.aiStatus ?? "QUEUED" };
  }
  if (sourceMessage.aiStatus === "COMPLETED") {
    return { phase: "completed", status: sourceMessage.aiStatus };
  }
  if (AI_FAILED_STATUSES.has(sourceMessage.aiStatus)) {
    return { phase: "failed", status: sourceMessage.aiStatus };
  }
  return { phase: "waiting", status: sourceMessage.aiStatus };
}

function aiPollFailure(error) {
  const status = Number(error?.status ?? 0);
  if (status === 401) return { retryable: false, message: "登录会话已失效，自动刷新已停止。请重新登录后继续。" };
  if (status === 403) return { retryable: false, message: "当前账号已无权读取该会话，自动刷新已停止。" };
  if (status === 404) return { retryable: false, message: "会话不存在或已不可见，自动刷新已停止。" };
  if (status === 429 || status >= 500 || ["NETWORK_ERROR", "REQUEST_TIMEOUT"].includes(error?.code)) {
    return { retryable: true, message: "网络或服务暂时不可用，正在降低刷新频率后重试。" };
  }
  return {
    retryable: false,
    message: `消息响应无法继续自动刷新：${errorText(error, "服务端响应不符合消息契约。")}。`,
  };
}

const KNOWLEDGE_STATE_LABELS = Object.freeze({
  PLATFORM: "平台岗位知识",
  ENTERPRISE: "企业授权知识",
  ENTERPRISE_AND_PLATFORM: "平台岗位 + 企业授权知识",
});

const MEMORY_STATE_LABELS = Object.freeze({
  AGENT: "员工独立记忆",
  CONVERSATION: "当前会话记忆",
  AGENT_AND_DIRECT_CONVERSATION: "员工独立 + 当前会话记忆",
  AGENT_AND_GROUP_CONVERSATION: "员工独立 + 当前群聊记忆",
});

function presentationLabel(labels, value) {
  if (!value) return null;
  return labels[value] ?? value;
}

function initials(name) {
  return String(name || "成员").trim().slice(0, 2);
}

function PersonAvatar({ src, name, className = "" }) {
  return src
    ? <img className={className} src={src} alt="" />
    : <span className={`conversation-avatar-fallback ${className}`}>{initials(name)}</span>;
}

function ConversationAvatar({ conversation }) {
  if (conversation.kind === "GROUP") {
    return <span className="conversation-group-avatar"><IconUsersGroup size={22} /></span>;
  }
  const person = conversation.agents[0] ?? conversation.otherHumans[0] ?? conversation.humans[0];
  return <PersonAvatar src={person?.avatarUrl} name={person?.name ?? conversation.title} />;
}

function GroupConversationModal({
  humans,
  agents,
  canInvokeAgent,
  submitting,
  error,
  onClose,
  onSubmit,
}) {
  const [title, setTitle] = useState("");
  const [humanIds, setHumanIds] = useState([]);
  const [agentIds, setAgentIds] = useState([]);
  const selectedCount = humanIds.length + agentIds.length;

  const toggle = (setter, id) => setter((current) => (
    current.includes(id) ? current.filter((item) => item !== id) : [...current, id]
  ));

  return (
    <div className="conversation-modal-layer" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && !submitting && onClose()}>
      <section className="conversation-group-modal" role="dialog" aria-modal="true" aria-label="新建群聊">
        <header>
          <div><small>企业内部统一会话</small><strong>新建群聊</strong></div>
          <button type="button" aria-label="关闭新建群聊" disabled={submitting} onClick={onClose}><IconX size={18} /></button>
        </header>
        <div className="conversation-group-modal__body">
          <label className="conversation-group-title">
            <span>群聊名称</span>
            <input value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)} placeholder="例如：品牌发布项目协作群" />
          </label>

          <section>
            <div className="conversation-modal-section-title"><strong>真人成员</strong><small>仅显示当前会话中已返回的真实企业成员</small></div>
            {humans.length ? <div className="conversation-member-options">{humans.map((member) => (
              <button className={humanIds.includes(member.id) ? "is-selected" : ""} type="button" key={member.id} onClick={() => toggle(setHumanIds, member.id)}>
                <PersonAvatar src={member.avatarUrl} name={member.name} />
                <span><strong>{member.name}</strong><small>企业成员</small></span>
                {humanIds.includes(member.id) ? <IconCheck size={17} /> : null}
              </button>
            ))}</div> : <p className="conversation-contract-note">当前 API 未提供独立企业通讯录；尚无可从既有会话复用的真人成员。</p>}
          </section>

          <section>
            <div className="conversation-modal-section-title"><strong>数字员工</strong><small>只显示当前办公室接口返回的员工</small></div>
            {agents.length ? <div className="conversation-member-options">{agents.map((agent) => (
              <button className={agentIds.includes(agent.id) ? "is-selected" : ""} type="button" key={agent.id} disabled={!canInvokeAgent} onClick={() => toggle(setAgentIds, agent.id)}>
                <PersonAvatar src={agent.avatarUrl ?? agent.image} name={agent.name} />
                <span><strong>{agent.name}</strong><small>{agent.roleName ?? agent.capabilityLabel ?? "数字员工"}</small></span>
                {agentIds.includes(agent.id) ? <IconCheck size={17} /> : null}
              </button>
            ))}</div> : <p className="conversation-contract-note">当前办公室没有可加入群聊的数字员工。</p>}
            {!canInvokeAgent ? <p className="conversation-contract-note is-warning">当前身份没有调用数字员工权限，可创建纯真人群聊。</p> : null}
          </section>
          {error ? <p className="conversation-form-error" role="alert">{error}</p> : null}
        </div>
        <footer>
          <span>创建者会由服务端自动加入 · 当前选择 {selectedCount} 位成员</span>
          <div><button type="button" disabled={submitting} onClick={onClose}>取消</button><button className="is-primary" type="button" disabled={submitting || !title.trim() || selectedCount < 1} onClick={() => onSubmit({ title, participantUserIds: humanIds, enterpriseAgentIds: agentIds })}>{submitting ? "正在创建…" : "创建群聊"}</button></div>
        </footer>
      </section>
    </div>
  );
}

export function ConversationPage({ session, office, dataSource }) {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedAgentId = String(searchParams.get("agentId") ?? "").trim();
  const requestedConversationId = String(searchParams.get("conversationId") ?? "").trim();
  const [resource, setResource] = useState({ phase: "loading", conversations: [], error: null });
  const [activeTab, setActiveTab] = useState("DIRECT");
  const [activeId, setActiveId] = useState(null);
  const [messageResource, setMessageResource] = useState({ phase: "idle", items: [], membershipVersion: null, hasMore: false, error: null });
  const [composer, setComposer] = useState("");
  const [targetPickerOpen, setTargetPickerOpen] = useState(false);
  const [targets, setTargets] = useState([]);
  const [replyTo, setReplyTo] = useState(null);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState(null);
  const [groupModalOpen, setGroupModalOpen] = useState(false);
  const [creatingGroup, setCreatingGroup] = useState(false);
  const [creatingDirect, setCreatingDirect] = useState(false);
  const [createError, setCreateError] = useState(null);
  const [aiWait, setAiWait] = useState(null);
  const messageRequestRef = useRef(0);
  const sendCommandRef = useRef(null);
  const createCommandRef = useRef(null);
  const historyRef = useRef(null);
  const activeConversationIdRef = useRef(activeId);
  activeConversationIdRef.current = activeId;

  const permissions = session.permissions ?? [];
  const canCreate = permissions.includes(CONVERSATION_PERMISSIONS.CREATE);
  const canInvokeAgent = permissions.includes(CONVERSATION_PERMISSIONS.INVOKE_AGENT);
  const requestedAgent = requestedAgentId
    ? office.agents.find((agent) => String(agent.id) === requestedAgentId) ?? null
    : null;

  const loadConversations = useCallback(async ({ preferId = null } = {}) => {
    setResource((current) => ({ ...current, phase: "loading", error: null }));
    try {
      const response = await dataSource.listConversations();
      const conversations = (Array.isArray(response) ? response : []).map((item) => mapConversationSummary(item, {
        currentUserId: session.user.id,
        officeAgents: office.agents,
      }));
      conversations.sort((left, right) => String(right.lastMessageAt ?? "").localeCompare(String(left.lastMessageAt ?? "")));
      setResource({ phase: "ready", conversations, error: null });
      const preferredConversation = preferId
        ? conversations.find((item) => item.id === preferId) ?? null
        : null;
      const queryConversation = requestedConversationId
        ? conversations.find((item) => item.id === requestedConversationId) ?? null
        : null;
      const agentConversation = requestedAgentId
        ? findAgentDirectConversation(conversations, requestedAgentId)
        : null;
      const requested = preferredConversation ?? queryConversation ?? agentConversation;
      if (requested) setActiveTab(requested.type);
      else if (requestedAgentId) setActiveTab("DIRECT");
      setActiveId((current) => {
        if (requested) return requested.id;
        if (requestedAgentId) return null;
        if (current && conversations.some((item) => item.id === current)) return current;
        return conversations.find((item) => item.type === activeTab)?.id ?? null;
      });
      return conversations;
    } catch (error) {
      setResource((current) => ({ ...current, phase: "error", error }));
      return [];
    }
  }, [activeTab, dataSource, office.agents, requestedAgentId, requestedConversationId, session.user.id]);

  const loadMessages = useCallback(async (conversation, {
    signal,
    silent = false,
    afterSequenceNo = 0,
    merge = false,
  } = {}) => {
    if (!conversation) {
      setMessageResource({ phase: "idle", items: [], membershipVersion: null, hasMore: false, error: null });
      return null;
    }
    const requestId = messageRequestRef.current + 1;
    messageRequestRef.current = requestId;
    if (!silent) setMessageResource((current) => ({ ...current, phase: "loading", error: null }));
    try {
      const response = await dataSource.listConversationMessages(conversation.id, {
        afterSequenceNo,
        limit: 200,
        signal,
      });
      if (requestId !== messageRequestRef.current || signal?.aborted) return null;
      const page = mapConversationMessagePage(response, { currentUserId: session.user.id });
      if (merge) {
        setMessageResource((current) => {
          const byId = new Map(current.items.map((message) => [message.id, message]));
          page.items.forEach((message) => byId.set(message.id, message));
          const items = [...byId.values()].sort((left, right) => left.sequenceNo - right.sequenceNo);
          return {
            ...current,
            phase: "ready",
            items,
            upToSequenceNo: Math.max(current.upToSequenceNo ?? 0, page.upToSequenceNo),
            hasMore: current.hasMore || page.hasMore,
            membershipVersion: page.membershipVersion,
            error: null,
          };
        });
      } else {
        setMessageResource({ phase: "ready", ...page, error: null });
      }
      return page;
    } catch (error) {
      if (requestId !== messageRequestRef.current || signal?.aborted) return null;
      if (silent) throw error;
      setMessageResource({ phase: "error", items: [], membershipVersion: null, hasMore: false, error });
      return null;
    }
  }, [dataSource, session.user.id]);

  useEffect(() => { void loadConversations(); }, [loadConversations]);

  const activeConversation = useMemo(
    () => resource.conversations.find((item) => item.id === activeId) ?? null,
    [activeId, resource.conversations],
  );

  useEffect(() => {
    setComposer("");
    setTargets([]);
    setReplyTo(null);
    setTargetPickerOpen(false);
    setSendError(null);
    setAiWait((current) => current?.conversationId === activeConversation?.id ? current : null);
    sendCommandRef.current = null;
    const controller = new AbortController();
    void loadMessages(activeConversation, { signal: controller.signal });
    return () => {
      controller.abort();
      messageRequestRef.current += 1;
    };
  }, [activeConversation?.id, loadMessages]);

  useEffect(() => {
    if (!aiWait || aiWait.phase !== "waiting" || aiWait.conversationId !== activeConversation?.id) return undefined;

    let stopped = false;
    let timer = null;
    let requestController = null;
    let attempts = 0;
    let failures = 0;

    const clearTimer = () => {
      if (timer !== null) window.clearTimeout(timer);
      timer = null;
    };
    const abortRequest = () => {
      requestController?.abort();
      requestController = null;
    };
    const updateCurrentWait = (updates) => {
      setAiWait((current) => (
        current?.conversationId === aiWait.conversationId
          && current?.sourceMessageId === aiWait.sourceMessageId
          ? { ...current, ...updates }
          : current
      ));
    };
    const stopWithError = (message, status = null, resumable = false) => {
      updateCurrentWait({
        phase: "error",
        message,
        resumable,
        ...(status ? { status } : {}),
      });
    };
    const schedule = (delayMs) => {
      clearTimer();
      if (stopped || document.visibilityState !== "visible") return;
      timer = window.setTimeout(() => { void poll(); }, delayMs);
    };
    const poll = async () => {
      if (stopped || document.visibilityState !== "visible") return;
      if (attempts >= AI_POLL_MAX_ATTEMPTS || Date.now() - aiWait.startedAt >= AI_POLL_MAX_DURATION_MS) {
        stopWithError("数字员工处理时间较长，自动刷新已停止。可以继续等待或稍后手动刷新。", null, true);
        return;
      }

      attempts += 1;
      requestController = new AbortController();
      const currentController = requestController;
      try {
        const page = await loadMessages(activeConversation, {
          signal: currentController.signal,
          silent: true,
          afterSequenceNo: Math.max(0, aiWait.sourceSequenceNo - 1),
          merge: true,
        });
        if (stopped || currentController.signal.aborted) return;
        requestController = null;
        if (!page) {
          schedule(AI_POLL_INTERVAL_MS);
          return;
        }

        failures = 0;
        const outcome = aiWaitOutcome(page.items, aiWait.sourceMessageId);
        if (outcome.phase === "completed") {
          setAiWait((current) => (
            current?.conversationId === aiWait.conversationId
              && current?.sourceMessageId === aiWait.sourceMessageId
              ? null
              : current
          ));
          void loadConversations({ preferId: aiWait.conversationId });
          return;
        }
        if (outcome.phase === "failed") {
          stopWithError(`${presentationLabel(AI_STATUS_LABELS, outcome.status)}，请查看消息状态或重新发起。`, outcome.status);
          return;
        }
        updateCurrentWait({ status: outcome.status, message: null });
        schedule(AI_POLL_INTERVAL_MS);
      } catch (error) {
        if (stopped || currentController.signal.aborted) return;
        requestController = null;
        const failure = aiPollFailure(error);
        if (!failure.retryable) {
          stopWithError(failure.message);
          return;
        }
        failures += 1;
        if (failures >= AI_POLL_MAX_FAILURES) {
          stopWithError("消息服务连续多次不可用，自动刷新已停止。请检查网络后继续等待。", null, true);
          return;
        }
        const retryDelayMs = Math.min(
          AI_POLL_INTERVAL_MS * (2 ** (failures - 1)),
          AI_POLL_MAX_BACKOFF_MS,
        );
        updateCurrentWait({ message: `${failure.message} 下次刷新约 ${retryDelayMs / 1_000} 秒后进行。` });
        schedule(retryDelayMs);
      }
    };
    const handleVisibilityChange = () => {
      if (document.visibilityState !== "visible") {
        clearTimer();
        abortRequest();
        return;
      }
      schedule(0);
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    schedule(AI_POLL_INTERVAL_MS);
    return () => {
      stopped = true;
      clearTimer();
      abortRequest();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [
    activeConversation?.id,
    aiWait?.conversationId,
    aiWait?.phase,
    aiWait?.sourceMessageId,
    aiWait?.sourceSequenceNo,
    aiWait?.startedAt,
    loadConversations,
    loadMessages,
  ]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      if (historyRef.current) historyRef.current.scrollTop = historyRef.current.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activeId, messageResource.items.length]);

  const directConversations = resource.conversations.filter((item) => item.type === "DIRECT");
  const groupConversations = resource.conversations.filter((item) => item.type === "GROUP");
  const visibleConversations = activeTab === "DIRECT" ? directConversations : groupConversations;
  const messageById = new Map(messageResource.items.map((message) => [message.id, message]));
  const activeAgentsById = new Map((activeConversation?.agents ?? []).map((agent) => [agent.id, agent]));
  const canSend = Boolean(
    activeConversation?.status === "ACTIVE"
      && activeConversation.allowedActions.includes("SEND")
      && permissions.includes(CONVERSATION_PERMISSIONS.SEND)
      && (activeConversation.kind !== "DIRECT_AGENT" || canInvokeAgent),
  );
  const activeAiWait = aiWait?.conversationId === activeConversation?.id ? aiWait : null;

  const knownHumans = useMemo(() => {
    const members = new Map();
    resource.conversations.forEach((conversation) => conversation.otherHumans.forEach((member) => members.set(member.id, member)));
    return [...members.values()];
  }, [resource.conversations]);

  const availableAgents = useMemo(() => {
    return office.agents.map((agent) => ({
      id: String(agent.id),
      name: agent.name,
      roleName: agent.capabilityLabel,
      image: agent.image,
      avatarUrl: agent.image,
    }));
  }, [office.agents]);

  const openTab = (type) => {
    setActiveTab(type);
    const first = resource.conversations.find((item) => item.type === type);
    setActiveId(first?.id ?? null);
    setSearchParams({}, { replace: true });
  };

  const openConversation = (conversation) => {
    setActiveId(conversation.id);
    setSearchParams({ conversationId: conversation.id }, { replace: true });
  };

  const removeTarget = (target) => {
    setTargets((current) => current.filter((item) => item.enterpriseAgentId !== target.enterpriseAgentId));
    if (target.triggerType === "REPLY") setReplyTo(null);
  };

  const chooseTarget = (agent, triggerType) => {
    setReplyTo(null);
    setTargets((current) => {
      const remaining = current.filter((target) => target.enterpriseAgentId !== agent.id);
      const existing = current.find((target) => target.enterpriseAgentId === agent.id);
      return existing?.triggerType === triggerType
        ? remaining
        : [...remaining, { enterpriseAgentId: agent.id, triggerType, name: agent.name }];
    });
    if (triggerType === "MENTION" && !composer.includes(`@${agent.name}`)) {
      setComposer((current) => `${current}${current && !current.endsWith(" ") ? " " : ""}@${agent.name} `);
    }
  };

  const replyToAgent = (message) => {
    const agent = activeAgentsById.get(message.senderAgentId);
    if (!agent) return;
    setReplyTo(message);
    setTargets([{
      enterpriseAgentId: agent.id,
      triggerType: "REPLY",
      replyToMessageId: message.id,
      name: agent.name,
    }]);
    setComposer("");
  };

  const submitMessage = async () => {
    const text = composer.trim();
    if (!activeConversation || !text || !canSend || sending || !messageResource.membershipVersion) return;
    const basePayload = {
      text,
      targets,
      membershipVersion: messageResource.membershipVersion,
      replyToMessageId: replyTo?.id ?? null,
    };
    sendCommandRef.current = prepareStableConversationCommand(sendCommandRef.current, {
      prefix: "conversation-message",
      payload: basePayload,
    });
    const payload = buildConversationMessagePayload({
      ...basePayload,
      clientMessageId: sendCommandRef.current.clientMessageId,
    });
    setSending(true);
    setSendError(null);
    try {
      const response = await dataSource.sendConversationMessage(activeConversation.id, payload, {
        idempotencyKey: sendCommandRef.current.idempotencyKey,
      });
      sendCommandRef.current = null;
      if (activeConversationIdRef.current !== activeConversation.id) return;
      setComposer("");
      setTargets([]);
      setReplyTo(null);
      setTargetPickerOpen(false);
      let accepted = null;
      if (response?.resource) {
        accepted = mapConversationMessage(response.resource, { currentUserId: session.user.id });
        setMessageResource((current) => ({ ...current, phase: "ready", items: [...current.items.filter((item) => item.id !== accepted.id), accepted] }));
      }
      const queuedInvocationIds = Array.isArray(response?.queuedInvocationIds)
        ? response.queuedInvocationIds.map(String).filter(Boolean)
        : [];
      if (accepted && queuedInvocationIds.length > 0) {
        setAiWait({
          conversationId: activeConversation.id,
          sourceMessageId: accepted.id,
          sourceSequenceNo: accepted.sequenceNo,
          invocationCount: queuedInvocationIds.length,
          phase: "waiting",
          status: accepted.aiStatus ?? "QUEUED",
          message: null,
          startedAt: Date.now(),
        });
      }
      const [refreshedPage] = await Promise.all([
        accepted
          ? loadMessages(activeConversation, {
            afterSequenceNo: Math.max(0, accepted.sequenceNo - 1),
            merge: true,
          })
          : loadMessages(activeConversation),
        loadConversations({ preferId: activeConversation.id }),
      ]);
      if (accepted && queuedInvocationIds.length > 0 && refreshedPage) {
        const outcome = aiWaitOutcome(refreshedPage.items, accepted.id);
        setAiWait((current) => {
          if (current?.conversationId !== activeConversation.id || current?.sourceMessageId !== accepted.id) return current;
          if (outcome.phase === "completed") return null;
          if (outcome.phase === "failed") {
            return {
              ...current,
              phase: "error",
              status: outcome.status,
              resumable: false,
              message: `${presentationLabel(AI_STATUS_LABELS, outcome.status)}，请查看消息状态或重新发起。`,
            };
          }
          return { ...current, status: outcome.status };
        });
      }
    } catch (error) {
      setSendError(errorText(error, "消息发送失败，请刷新会话后重试。"));
    } finally {
      setSending(false);
    }
  };

  const createGroup = async (form) => {
    const payload = buildCreateGroupPayload(form);
    createCommandRef.current = prepareStableConversationCommand(createCommandRef.current, {
      prefix: "conversation-create",
      payload,
    });
    setCreatingGroup(true);
    setCreateError(null);
    try {
      const response = await dataSource.createConversation(payload, {
        idempotencyKey: createCommandRef.current.idempotencyKey,
      });
      const createdId = response?.resource?.conversationId;
      createCommandRef.current = null;
      setGroupModalOpen(false);
      setActiveTab("GROUP");
      await loadConversations({ preferId: createdId ? String(createdId) : null });
    } catch (error) {
      setCreateError(errorText(error, "群聊创建失败，请检查成员权限后重试。"));
    } finally {
      setCreatingGroup(false);
    }
  };

  const createDirectConversation = async () => {
    if (!requestedAgent || !canCreate || !canInvokeAgent || creatingDirect) return;
    const payload = buildCreateAgentDirectPayload({
      enterpriseAgentId: requestedAgent.id,
      title: requestedAgent.name,
    });
    createCommandRef.current = prepareStableConversationCommand(createCommandRef.current, {
      prefix: "conversation-direct",
      payload,
    });
    setCreatingDirect(true);
    setCreateError(null);
    try {
      const response = await dataSource.createConversation(payload, {
        idempotencyKey: createCommandRef.current.idempotencyKey,
      });
      const createdId = String(response?.resource?.conversationId ?? "").trim();
      createCommandRef.current = null;
      setActiveTab("DIRECT");
      if (createdId) setSearchParams({ conversationId: createdId }, { replace: true });
      await loadConversations({ preferId: createdId || null });
    } catch (error) {
      setCreateError(errorText(error, "一对一会话创建失败，请检查员工与会话权限后重试。"));
    } finally {
      setCreatingDirect(false);
    }
  };

  return (
    <div className="conversation-page">
      <header className="conversation-event-header">
        <button type="button" className="conversation-event-brand" onClick={() => navigate("/office")}><BrandLogo /></button>
        <strong className="conversation-event-product">企业数字办公大厅</strong>
        <span className="conversation-event-tenant"><small>当前企业</small><strong>{session.tenant.name}</strong></span>
        <span className="conversation-event-user"><small>当前用户</small><strong>{session.user.name}</strong></span>
        <span className="conversation-event-metric"><IconMessages size={18} /><small>真实会话</small><strong>{resource.phase === "ready" ? resource.conversations.length : "—"}</strong><em>未读 {resource.phase === "ready" ? resource.conversations.reduce((total, item) => total + item.unreadCount, 0) : "—"}</em></span>
      </header>

      <nav className="conversation-event-nav" aria-label="工作入口">
        <button type="button" onClick={() => navigate("/office")}><IconBuildingCommunity size={21} /><span>组织大厅</span></button>
        <button className="is-active" type="button" aria-current="page"><IconMessages size={21} /><span>消息</span></button>
        <button type="button" onClick={() => navigate("/employees")}><IconBriefcase size={21} /><span>数字员工</span></button>
        <button type="button" onClick={() => navigate("/tasks")}><IconListCheck size={21} /><span>当前任务</span></button>
        <button type="button" disabled title="当前 API 门户尚未提供智点明细路由"><IconCoinYuan size={21} /><span>智点明细</span></button>
      </nav>

      <section className="conversation-event-stage" aria-label={`${session.tenant.name}组织大厅背景`}>
        <div className="conversation-event-stage__veil" />
      </section>

      <main className="conversation-workspace" aria-label="消息中心">
        <header className="conversation-workspace__header">
          <div><IconMessageCircle2 size={21} /><strong>消息中心</strong><small>真实历史 · 数字员工回复自动刷新</small></div>
          <span>
            <button type="button" disabled={resource.phase === "loading" || messageResource.phase === "loading"} onClick={() => void Promise.all([
              loadConversations({ preferId: activeId }),
              activeConversation ? loadMessages(activeConversation) : Promise.resolve(),
            ])}><IconRefresh size={17} />刷新消息</button>
            <button type="button" aria-label="关闭消息中心" onClick={() => navigate("/office")}><IconX size={18} /></button>
          </span>
        </header>

        <div className="conversation-workspace__body">
          <aside className="conversation-sidebar" aria-label="会话列表">
            <div className="conversation-tabs" role="tablist">
              <button className={activeTab === "DIRECT" ? "is-active" : ""} type="button" role="tab" aria-selected={activeTab === "DIRECT"} onClick={() => openTab("DIRECT")}>一对一 <span>{directConversations.length}</span></button>
              <button className={activeTab === "GROUP" ? "is-active" : ""} type="button" role="tab" aria-selected={activeTab === "GROUP"} onClick={() => openTab("GROUP")}>群聊 <span>{groupConversations.length}</span></button>
            </div>
            {activeTab === "GROUP" && canCreate ? <button className="conversation-create-group" type="button" onClick={() => { setCreateError(null); setGroupModalOpen(true); }}><IconPlus size={15} />新建群聊</button> : null}

            <div className="conversation-list">
              {resource.phase === "loading" ? <div className="conversation-list-state">正在读取会话…</div> : null}
              {resource.phase === "error" ? <div className="conversation-list-state is-error"><strong>会话加载失败</strong><span>{errorText(resource.error, "暂时无法读取会话。")}</span><button type="button" onClick={() => void loadConversations()}>重试</button></div> : null}
              {resource.phase === "ready" && !visibleConversations.length ? <div className="conversation-list-state"><IconMessages size={24} /><strong>{activeTab === "GROUP" ? "还没有群聊" : "还没有一对一会话"}</strong><span>这里只展示服务端返回的真实会话。</span></div> : null}
              {visibleConversations.map((conversation) => (
                <button className={`conversation-list-item ${conversation.id === activeId ? "is-active" : ""}`} type="button" key={conversation.id} onClick={() => openConversation(conversation)}>
                  <ConversationAvatar conversation={conversation} />
                  <span className="conversation-list-item__copy"><strong>{conversation.title}{conversation.kind === "DIRECT_AGENT" ? <em>AI</em> : conversation.kind === "DIRECT_HUMAN" ? <em>真人</em> : null}</strong><small>{conversation.lastMessagePreview || (conversation.kind === "GROUP" ? `${conversation.humans.length + conversation.agents.length} 名成员` : "还没有消息")}</small></span>
                  <span className="conversation-list-item__meta"><time>{messageTime(conversation.lastMessageAt)}</time>{conversation.unreadCount > 0 ? <em>{conversation.unreadCount > 99 ? "99+" : conversation.unreadCount}</em> : null}</span>
                </button>
              ))}
            </div>
            <p className="conversation-sidebar-boundary">未读数来自会话摘要；当前 API 尚未开放读取位置写入，页面不会伪造已读。数字员工一对一可从员工档案建立，真人一对一仍需真实成员目录。</p>
          </aside>

          <section className="conversation-thread" aria-label={activeConversation ? `${activeConversation.title}消息` : "消息内容"}>
            {!activeConversation ? (requestedAgent ? (
              <div className="conversation-thread-empty conversation-direct-start">
                <PersonAvatar src={requestedAgent.image} name={requestedAgent.name} />
                <strong>与 {requestedAgent.name} 开始一对一对话</strong>
                <span>{requestedAgent.capabilityLabel} · 会话将使用该员工独立的岗位配置、企业知识范围和你与该员工的会话记忆。</span>
                {canCreate && canInvokeAgent ? <button type="button" disabled={creatingDirect} onClick={() => void createDirectConversation()}><IconMessageCircle2 size={17} />{creatingDirect ? "正在建立会话…" : "建立真实 AI 会话"}</button> : <small>当前身份缺少会话创建或数字员工调用权限，不能建立新会话。</small>}
                {createError ? <p className="conversation-send-error" role="alert">{createError}</p> : null}
              </div>
            ) : (
              <div className="conversation-thread-empty"><IconMessageCircle2 size={30} /><strong>选择一个会话</strong><span>消息历史、成员和数字员工目标都以服务端返回为准。</span></div>
            )) : (
              <>
                <header className="conversation-thread__header">
                  <ConversationAvatar conversation={activeConversation} />
                  <div><strong>{activeConversation.title}</strong><small>{activeConversation.kind === "GROUP" ? `${activeConversation.humans.length} 位真人 · ${activeConversation.agents.length} 位数字员工` : activeConversation.kind === "DIRECT_AGENT" ? `${activeConversation.agents[0]?.roleName ?? "数字员工"} · 发送消息会调用该员工` : "真人直接会话 · 不调用模型"}</small></div>
                  <span className={activeConversation.status === "ACTIVE" ? "" : "is-disabled"}>{activeConversation.status === "ACTIVE" ? "会话有效" : "会话已停用"}</span>
                </header>

                {activeConversation.kind === "GROUP" ? (
                  <div className="conversation-target-bar">
                    <div><strong>群内 AI 目标</strong><small>{targets.length ? `已结构化选择 ${targets.length} 位数字员工` : "普通群消息：targets=[]，不会调用 AI 或扣智点"}</small></div>
                    <button type="button" disabled={!canInvokeAgent || !activeConversation.agents.length} aria-expanded={targetPickerOpen} onClick={() => setTargetPickerOpen((open) => !open)}><IconAt size={16} />选择 / @ 数字员工</button>
                    {targetPickerOpen ? <div className="conversation-target-picker">{activeConversation.agents.map((agent) => {
                      const selected = targets.find((target) => target.enterpriseAgentId === agent.id);
                      return <div key={agent.id}><PersonAvatar src={agent.avatarUrl} name={agent.name} /><span><strong>{agent.name}</strong><small>{agent.roleName}</small></span><button className={selected?.triggerType === "SELECTION" ? "is-active" : ""} type="button" onClick={() => chooseTarget(agent, "SELECTION")}>选择</button><button className={selected?.triggerType === "MENTION" ? "is-active" : ""} type="button" onClick={() => chooseTarget(agent, "MENTION")}>@提及</button></div>;
                    })}</div> : null}
                    {!canInvokeAgent ? <p>当前身份没有数字员工调用权限，仍可发送 targets=[] 的普通群消息。</p> : null}
                  </div>
                ) : null}

                <div className="conversation-history" ref={historyRef}>
                  {messageResource.phase === "loading" ? <div className="conversation-history-state">正在读取权威消息历史…</div> : null}
                  {messageResource.phase === "error" ? <div className="conversation-history-state is-error"><strong>消息加载失败</strong><span>{errorText(messageResource.error, "暂时无法读取消息。")}</span><button type="button" onClick={() => void loadMessages(activeConversation)}>重新读取</button></div> : null}
                  {messageResource.phase === "ready" && !messageResource.items.length ? <div className="conversation-history-state"><IconMessageCircle2 size={25} /><strong>还没有消息</strong><span>{activeConversation.kind === "GROUP" ? "直接发送是普通群消息；需要 AI 时先结构化选择目标。" : "发送第一条真实消息。"}</span></div> : null}
                  {messageResource.items.map((message) => {
                    const replied = message.replyToMessageId ? messageById.get(message.replyToMessageId) : null;
                    const targetNames = message.targetAgentIds.map((id) => activeAgentsById.get(id)?.name ?? id);
                    return <article className={`conversation-message is-${message.senderType.toLowerCase()} ${message.isOwn ? "is-own" : ""}`} key={message.id}>
                      {!message.isOwn ? <PersonAvatar src={message.senderAvatarUrl} name={message.senderName} /> : null}
                      <div className="conversation-message__content">
                        <small>{message.senderName} · {messageTime(message.createdAt)}</small>
                        <div className="conversation-message__bubble">
                          {replied ? <span className="conversation-reply-preview">回复 {replied.senderName}：{replied.text}</span> : null}
                          {targetNames.length ? <span className="conversation-target-summary">目标：{targetNames.map((name) => `@${name}`).join("、")}</span> : null}
                          <p>{message.text}</p>
                          {message.aiStatus ? <span className="conversation-ai-state">{presentationLabel(AI_STATUS_LABELS, message.aiStatus)}</span> : null}
                          {message.senderType === "AGENT" && (message.knowledgeState || message.memoryState || Number(message.chargedPoints) > 0) ? <span className="conversation-message-facts">{message.knowledgeState ? `知识：${presentationLabel(KNOWLEDGE_STATE_LABELS, message.knowledgeState)}` : ""}{message.memoryState ? ` · 记忆：${presentationLabel(MEMORY_STATE_LABELS, message.memoryState)}` : ""}{Number(message.chargedPoints) > 0 ? ` · 智点 ${message.chargedPoints}` : ""}</span> : null}
                        </div>
                        {message.senderType === "AGENT" && activeConversation.kind === "GROUP" && activeAgentsById.has(message.senderAgentId) && canInvokeAgent ? <button className="conversation-reply-button" type="button" onClick={() => replyToAgent(message)}><IconMessageReply size={13} />回复并再次调用 {message.senderName}</button> : null}
                      </div>
                    </article>;
                  })}
                  {activeAiWait ? (
                    <div className={`conversation-ai-wait is-${activeAiWait.phase}`} role={activeAiWait.phase === "waiting" ? "status" : "alert"}>
                      <span className="conversation-ai-wait__icon" aria-hidden="true"><IconRefresh size={18} /></span>
                      <div>
                        <strong>{activeAiWait.phase === "waiting" ? "等待数字员工回复" : "数字员工回复自动刷新已停止"}</strong>
                        <small>{activeAiWait.message ?? `${presentationLabel(AI_STATUS_LABELS, activeAiWait.status)} · 已进入 ${activeAiWait.invocationCount} 个真实执行队列。消息正文仍以服务端 GET 为准。`}</small>
                      </div>
                      {activeAiWait.phase === "waiting" ? (
                        <button type="button" onClick={() => setAiWait(null)}>停止等待</button>
                      ) : activeAiWait.resumable ? (
                        <button type="button" onClick={() => setAiWait((current) => current?.conversationId === activeConversation.id ? { ...current, phase: "waiting", message: null, resumable: false, startedAt: Date.now() } : current)}>继续等待</button>
                      ) : (
                        <button type="button" onClick={() => void loadMessages(activeConversation)}>重新读取</button>
                      )}
                    </div>
                  ) : null}
                  {messageResource.hasMore ? <p className="conversation-history-boundary">当前仅加载前 200 条可见消息；请等待历史分页交互补齐。</p> : null}
                </div>

                <div className="conversation-composer">
                  {replyTo ? <div className="conversation-composer-reply"><span><IconMessageReply size={14} /><strong>回复 {replyTo.senderName}</strong><small>{replyTo.text}</small></span><button type="button" aria-label="取消回复" onClick={() => { setReplyTo(null); setTargets([]); }}><IconX size={15} /></button></div> : null}
                  {targets.length ? <div className="conversation-selected-targets">{targets.map((target) => <button type="button" key={target.enterpriseAgentId} onClick={() => removeTarget(target)}><span>{target.triggerType === "MENTION" ? "@" : target.triggerType === "REPLY" ? "回复" : "选择"} {target.name}</span><IconX size={12} /></button>)}</div> : null}
                  <textarea value={composer} disabled={!canSend || sending} aria-label="发送消息" placeholder={activeConversation.kind === "GROUP" ? "发送群消息；仅输入 @文字不会触发 AI，请使用上方结构化选择…" : activeConversation.kind === "DIRECT_AGENT" ? `给 ${activeConversation.agents[0]?.name ?? "数字员工"} 发消息…` : "像给同事一样发送消息…"} onChange={(event) => { setComposer(event.target.value); sendCommandRef.current = null; }} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submitMessage(); } }} />
                  <button className="conversation-attachment-boundary" type="button" disabled title="当前统一会话 API 尚未提供附件字段"><IconPaperclip size={16} /><span>附件未开放</span></button>
                  <small>回车发送 · Shift+回车换行</small>
                  <button className="conversation-send-button" type="button" disabled={!canSend || sending || !composer.trim() || messageResource.phase !== "ready"} onClick={() => void submitMessage()}><IconSend2 size={16} />{sending ? "发送中…" : "发送"}</button>
                  {sendError ? <p className="conversation-send-error" role="alert">{sendError}<button type="button" onClick={() => void loadMessages(activeConversation)}>刷新成员版本</button></p> : null}
                  {!canSend ? <p className="conversation-send-boundary">{activeConversation.kind === "DIRECT_AGENT" && !canInvokeAgent ? "当前身份没有调用该数字员工的权限。" : "服务端未允许当前身份在此会话发送消息。"}</p> : null}
                </div>
              </>
            )}
          </section>
        </div>
      </main>

      {groupModalOpen ? <GroupConversationModal humans={knownHumans} agents={availableAgents} canInvokeAgent={canInvokeAgent} submitting={creatingGroup} error={createError} onClose={() => { if (!creatingGroup) { setGroupModalOpen(false); createCommandRef.current = null; } }} onSubmit={createGroup} /> : null}
    </div>
  );
}
