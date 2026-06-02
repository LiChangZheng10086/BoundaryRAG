import { computed, reactive, watch } from "vue";

const SESSION_PROFILE_KEY = "rag_demo_session_profile";

const DEFAULT_IDENTITY = {
  userId: "lcz10086",
  username: "lcz10086",
  role: "user",
  tenantId: "default",
  permissionTags: [],
};

const DEFAULT_DOC_FILTERS = {
  search: "",
  status: "",
  tag: "",
  sort: "newest",
};

const SKILL_OPTIONS = [
  { value: "answer_question", label: "问答" },
  { value: "write_document", label: "写文档" },
  { value: "write_markdown", label: "写 Markdown" },
  { value: "write_word", label: "写 Word" },
  { value: "write_ppt", label: "写 PPT" },
];

export function useWorkspace() {
  const state = reactive({
    ready: false,
    isAuthenticated: false,
    authToken: "",
    storageNamespace: "",
    identity: { ...DEFAULT_IDENTITY },
    runtimeConfig: null,
    knowledgeBases: [],
    activeKb: null,
    activeKbId: "",
    recentKbIds: [],
    documents: [],
    artifacts: [],
    conversations: [],
    conversationMessages: [],
    conversationIds: {},
    operationEvents: [],
    activeTab: "ask",
    sessionExpiresAt: 0,
    requests: {
      knowledgeBases: 0,
      documents: 0,
      artifacts: 0,
      conversations: 0,
      conversationMessages: 0,
      operationEvents: 0,
      query: 0,
      generate: 0,
    },
    ask: {
      answer: "问答结果会显示在这里。",
      traceId: "",
      streaming: false,
    },
    generate: {
      answer: "生成结果会显示在这里。",
      traceId: "",
      artifact: null,
      running: false,
    },
    documentPreview: {
      title: "",
      content: "点击文档的“预览”查看解析后的入库文本。",
    },
    artifactPreview: {
      title: "",
      content: "点击生成历史的“预览”查看文件内容。",
    },
    operationStatus: {
      message: "准备就绪。选择知识库后开始工作。",
      tone: "idle",
    },
    toast: {
      message: "",
      visible: false,
    },
    queryAbortController: null,
  });

  const drafts = reactive({
    login: {
      username: "lcz10086",
      password: "",
    },
    sidebar: {
      search: "",
    },
    knowledgeBase: {
      id: "",
      name: "",
      tenantId: "default",
      permissionTags: "",
      idTouched: false,
      idSuffix: Date.now().toString(36).slice(-6),
      skillFlags: Object.fromEntries(SKILL_OPTIONS.map((skill) => [skill.value, true])),
    },
    query: {
      question: "",
    },
    document: {
      title: "",
      content: "",
      permissionTags: "",
    },
    upload: {
      permissionTags: "",
    },
    generate: {
      skillName: "write_document",
      instruction: "",
    },
    docFilters: { ...DEFAULT_DOC_FILTERS },
  });

  const activeConversationId = computed(() => {
    if (!state.activeKb) {
      return "";
    }
    return state.conversationIds[state.activeKb.id] || "";
  });

  const activeConversation = computed(() => {
    if (!activeConversationId.value) {
      return null;
    }
    return state.conversations.find((conversation) => conversation.id === activeConversationId.value) || null;
  });

  const activeConversationLabel = computed(() => {
    if (!state.activeKb) {
      return "未选择知识库";
    }
    return activeConversation.value?.title || "新对话";
  });

  const canAsk = computed(() => {
    return Boolean(state.activeKb?.allowed_skills?.includes("answer_question"));
  });

  const canGenerate = computed(() => {
    return Boolean(state.activeKb?.allowed_skills?.includes(drafts.generate.skillName));
  });

  const recentKnowledgeBases = computed(() => {
    return state.recentKbIds
      .map((id) => state.knowledgeBases.find((kb) => kb.id === id))
      .filter(Boolean)
      .slice(0, 5);
  });

  const visibleKnowledgeBases = computed(() => {
    const keyword = drafts.sidebar.search.trim().toLowerCase();
    return [...state.knowledgeBases]
      .filter((kb) => {
        if (!keyword) {
          return true;
        }
        const haystack = [
          kb.id,
          kb.name,
          kb.tenant_id,
          kb.description,
          ...(kb.permission_tags || []),
          ...(kb.allowed_skills || []),
        ]
          .join(" ")
          .toLowerCase();
        return haystack.includes(keyword);
      })
      .sort((left, right) => {
        const leftRecent = state.recentKbIds.indexOf(left.id);
        const rightRecent = state.recentKbIds.indexOf(right.id);
        if (leftRecent !== -1 || rightRecent !== -1) {
          return (leftRecent === -1 ? 99 : leftRecent) - (rightRecent === -1 ? 99 : rightRecent);
        }
        return left.name.localeCompare(right.name, "zh-CN");
      });
  });

  const filteredDocuments = computed(() => {
    const search = drafts.docFilters.search.trim().toLowerCase();
    const tag = drafts.docFilters.tag.trim().toLowerCase();
    const status = drafts.docFilters.status;
    const documents = state.documents.filter((doc) => {
      const tags = (doc.permission_tags || []).join(", ");
      const haystack = [doc.id, doc.title, doc.status, doc.error, tags].join(" ").toLowerCase();
      return (
        (!search || haystack.includes(search)) &&
        (!status || doc.status === status) &&
        (!tag || tags.toLowerCase().includes(tag))
      );
    });

    return documents.sort((left, right) => {
      if (drafts.docFilters.sort === "oldest") {
        return new Date(left.created_at) - new Date(right.created_at);
      }
      if (drafts.docFilters.sort === "title") {
        return left.title.localeCompare(right.title, "zh-CN");
      }
      if (drafts.docFilters.sort === "status") {
        return left.status.localeCompare(right.status);
      }
      return new Date(right.created_at) - new Date(left.created_at);
    });
  });

  const tokenPayload = computed(() => decodeTokenPayload(state.authToken));

  const tokenExpiryText = computed(() => {
    if (!state.isAuthenticated) {
      return "请先完成身份验证。";
    }
    if (state.sessionExpiresAt) {
      const expiresAt = new Date(state.sessionExpiresAt * 1000);
      const expired = expiresAt.getTime() <= Date.now();
      return `${expired ? "已过期" : "过期时间"}：${formatTime(expiresAt.toISOString())}`;
    }
    const payload = tokenPayload.value;
    if (!payload?.exp) {
      return "Token 已保存，但未发现过期时间。";
    }
    const expiresAt = new Date(payload.exp * 1000);
    const expired = expiresAt.getTime() <= Date.now();
    return `${expired ? "已过期" : "过期时间"}：${formatTime(expiresAt.toISOString())}`;
  });

  watch(
    () => state.activeTab,
    (tab) => persistScopedState("active_tab", tab),
  );

  watch(
    () => drafts.docFilters,
    (filters) => persistScopedState("doc_filters", { ...filters }),
    { deep: true },
  );

  async function bootstrap() {
    try {
      await loadRuntimeConfig();
      const session = readSessionProfile();
      if (restoreSessionProfile(session)) {
        try {
          await loadCurrentUserWorkspace();
          setOperationStatus(`已恢复 ${state.identity.userId} / ${state.identity.tenantId} 的登录会话。`);
        } catch (error) {
          clearSession();
          showToast(`登录会话已失效：${messageFromError(error)}`);
        }
      }
    } catch (error) {
      showToast(messageFromError(error));
    } finally {
      state.ready = true;
    }
  }

  async function loadRuntimeConfig() {
    state.runtimeConfig = await api("/runtime-config");
  }

  async function loginFromDraft() {
    const username = drafts.login.username.trim();
    const password = drafts.login.password;
    if (!username || !password) {
      throw new Error("请输入用户名和密码。");
    }

    const result = await api("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    const identity = identityFromLoginResponse(result.user);
    activateSession({
      token: result.access_token,
      identity,
      expiresAt: result.expires_at,
    });
    drafts.login.password = "";
    try {
      await loadCurrentUserWorkspace();
    } catch (error) {
      clearSession();
      throw error;
    }
    setOperationStatus(`已登录为 ${state.identity.userId} / ${state.identity.role}。`);
    showToast(`已进入 ${state.identity.userId} 的独立工作区。`);
  }

  async function logoutToLogin() {
    let serverMessage = "";
    try {
      serverMessage = await revokeAuthTokenOnServer();
    } catch {
      serverMessage = "服务端退出登录失败，已仅清理本地会话。";
    } finally {
      clearSession();
      showToast(serverMessage || "已退出登录。");
      setOperationStatus("请先在登录页完成登录。");
    }
  }

  async function loadCurrentUserWorkspace() {
    await loadKnowledgeBases();
  }

  async function refreshWorkspace() {
    await loadKnowledgeBases();
    showToast("工作区已刷新。");
  }

  async function loadKnowledgeBases() {
    if (!state.isAuthenticated) {
      state.knowledgeBases = [];
      clearActiveKbWorkspace();
      return;
    }

    const requestId = ++state.requests.knowledgeBases;
    const knowledgeBases = await api("/knowledge-bases");
    if (requestId !== state.requests.knowledgeBases) {
      return;
    }

    const previousKbId = state.activeKb?.id || "";
    state.knowledgeBases = knowledgeBases;
    const preferredKbId = state.activeKbId || previousKbId;
    let nextKb = state.knowledgeBases.find((kb) => kb.id === preferredKbId) || state.knowledgeBases[0] || null;
    if (nextKb && nextKb.tenant_id !== state.identity.tenantId) {
      nextKb = null;
    }

    const nextKbId = nextKb?.id || "";
    if (nextKbId !== previousKbId) {
      invalidateActiveRequests();
      resetActiveOutputs();
    }

    state.activeKb = nextKb;
    state.activeKbId = nextKbId;
    persistScopedState("active_kb", nextKbId);

    if (!nextKb) {
      clearActiveKbWorkspace();
      return;
    }

    rememberKnowledgeBase(nextKb.id);
    await loadActiveKbWorkspace();
  }

  async function switchKnowledgeBase(kb) {
    if (!kb || state.activeKb?.id === kb.id) {
      return;
    }
    invalidateActiveRequests();
    resetActiveOutputs();
    state.activeKb = kb;
    state.activeKbId = kb.id;
    rememberKnowledgeBase(kb.id);
    setOperationStatus(`已切换到 ${kb.name}，边界已锁定。`);
    await loadActiveKbWorkspace();
  }

  async function loadActiveKbWorkspace() {
    if (!state.activeKb) {
      clearActiveKbWorkspace();
      return;
    }
    const results = await Promise.allSettled([
      loadDocuments(),
      loadArtifacts(),
      loadConversations(),
      loadOperationEvents(),
    ]);
    const rejected = results.find((result) => result.status === "rejected");
    if (rejected) {
      const message = messageFromError(rejected.reason);
      setOperationStatus(message, "error");
      showToast(message);
    }
  }

  async function loadDocuments() {
    if (!state.activeKb) {
      state.documents = [];
      return;
    }
    const kbId = state.activeKb.id;
    const requestId = ++state.requests.documents;
    const documents = await api(`/knowledge-bases/${encodeURIComponent(kbId)}/documents`);
    if (requestId !== state.requests.documents || state.activeKb?.id !== kbId) {
      return;
    }
    state.documents = documents;
  }

  async function loadArtifacts() {
    if (!state.activeKb) {
      state.artifacts = [];
      return;
    }
    const kbId = state.activeKb.id;
    const requestId = ++state.requests.artifacts;
    const artifacts = await api(`/knowledge-bases/${encodeURIComponent(kbId)}/artifacts`);
    if (requestId !== state.requests.artifacts || state.activeKb?.id !== kbId) {
      return;
    }
    state.artifacts = artifacts;
  }

  async function loadConversations() {
    if (!state.activeKb) {
      state.conversations = [];
      state.conversationMessages = [];
      return;
    }
    const kbId = state.activeKb.id;
    const requestId = ++state.requests.conversations;
    const conversations = await api(`/knowledge-bases/${encodeURIComponent(kbId)}/conversations`);
    if (requestId !== state.requests.conversations || state.activeKb?.id !== kbId) {
      return;
    }
    state.conversations = conversations;
    state.conversationMessages = [];

    const selectedId = activeConversationId.value;
    const selected = conversations.find((conversation) => conversation.id === selectedId) || conversations[0];
    if (selected) {
      rememberConversation(kbId, selected.id);
      await loadConversationMessages(selected.id);
      return;
    }

    forgetConversation(kbId);
  }

  async function loadConversationMessages(conversationId = "") {
    if (!state.activeKb) {
      state.conversationMessages = [];
      return;
    }
    const kbId = state.activeKb.id;
    const selectedId = conversationId || activeConversationId.value;
    if (!selectedId) {
      state.conversationMessages = [];
      return;
    }
    const requestId = ++state.requests.conversationMessages;
    const messages = await api(
      `/knowledge-bases/${encodeURIComponent(kbId)}/conversations/${encodeURIComponent(selectedId)}/messages`,
    );
    if (
      requestId !== state.requests.conversationMessages ||
      state.activeKb?.id !== kbId ||
      activeConversationId.value !== selectedId
    ) {
      return;
    }
    state.conversationMessages = messages;
  }

  async function loadOperationEvents() {
    const kbId = state.activeKb?.id || "";
    const requestId = ++state.requests.operationEvents;
    const path = kbId ? `/operation-events?kb_id=${encodeURIComponent(kbId)}&limit=20` : "/operation-events?limit=20";
    const events = await api(path);
    if (requestId !== state.requests.operationEvents || (kbId && state.activeKb?.id !== kbId)) {
      return;
    }
    state.operationEvents = events;
  }

  async function createKnowledgeBase() {
    const kbId = drafts.knowledgeBase.id.trim();
    if (!isValidKnowledgeBaseId(kbId)) {
      throw new Error("知识库 ID 只能包含英文、数字、下划线、短横线，长度 2-64；中文请填在名称里。");
    }
    const allowedSkills = selectedSkills();
    if (!allowedSkills.length) {
      throw new Error("请至少选择一个允许技能。");
    }
    const kb = await api("/knowledge-bases", {
      method: "POST",
      body: JSON.stringify({
        id: kbId,
        name: drafts.knowledgeBase.name.trim(),
        tenant_id: drafts.knowledgeBase.tenantId.trim() || state.identity.tenantId || "default",
        permission_tags: parseTags(drafts.knowledgeBase.permissionTags),
        allowed_skills: allowedSkills,
      }),
    });
    state.activeKb = kb;
    state.activeKbId = kb.id;
    rememberKnowledgeBase(kb.id);
    resetKnowledgeBaseDraft();
    await loadKnowledgeBases();
    showToast("知识库已创建，并切换为当前边界。");
  }

  async function deleteKnowledgeBase(kb) {
    await api(`/knowledge-bases/${encodeURIComponent(kb.id)}`, { method: "DELETE" });
    state.recentKbIds = state.recentKbIds.filter((id) => id !== kb.id);
    const { [kb.id]: _deletedConversationId, ...remainingConversationIds } = state.conversationIds;
    state.conversationIds = remainingConversationIds;
    persistScopedState("recent_kbs", state.recentKbIds);
    persistScopedState("conversations", state.conversationIds);
    if (state.activeKb?.id === kb.id) {
      state.activeKb = null;
      state.activeKbId = "";
      persistScopedState("active_kb", "");
      invalidateActiveRequests();
      resetActiveOutputs();
      clearActiveKbWorkspace();
    }
    await loadKnowledgeBases();
    showToast("知识库已删除。");
  }

  async function addTextDocument() {
    const kb = requireActiveKb();
    setOperationStatus("正在写入文本并生成向量...", "busy");
    await api(`/knowledge-bases/${encodeURIComponent(kb.id)}/documents`, {
      method: "POST",
      body: JSON.stringify({
        title: drafts.document.title.trim(),
        content: drafts.document.content.trim(),
        permission_tags: parseTags(drafts.document.permissionTags),
      }),
    });
    drafts.document.title = "";
    drafts.document.content = "";
    drafts.document.permissionTags = "";
    await Promise.all([loadDocuments(), loadOperationEvents()]);
    setOperationStatus("文本已入库并完成索引。");
    showToast(`文档已写入 ${kb.name}。`);
  }

  async function uploadDocument(file) {
    const kb = requireActiveKb();
    if (!file) {
      throw new Error("请选择要上传的文件。");
    }
    setOperationStatus(`正在上传 ${file.name}...`, "busy");
    const formData = new FormData();
    formData.append("file", file);
    formData.append("permission_tags", drafts.upload.permissionTags.trim());
    const response = await fetch(`/knowledge-bases/${encodeURIComponent(kb.id)}/documents/upload`, {
      method: "POST",
      body: formData,
      headers: accessHeaders(),
    });
    const text = await response.text();
    const data = parseResponseBody(text);
    if (!response.ok) {
      throw new Error(errorMessage(data, `上传失败：${response.status}`));
    }
    drafts.upload.permissionTags = "";
    await Promise.all([loadDocuments(), loadOperationEvents()]);
    setOperationStatus("文件已解析并完成向量化。");
    showToast(`文件已上传并写入 ${kb.name}。`);
  }

  async function previewDocument(docId) {
    const kb = requireActiveKb();
    const document = await api(`/knowledge-bases/${encodeURIComponent(kb.id)}/documents/${encodeURIComponent(docId)}`);
    state.documentPreview.title = document.title;
    state.documentPreview.content = `# ${document.title}\n\n${document.content}`;
    setOperationStatus(`已加载「${document.title}」解析预览。`);
  }

  async function deleteDocument(doc) {
    const kb = requireActiveKb();
    await api(`/knowledge-bases/${encodeURIComponent(kb.id)}/documents/${encodeURIComponent(doc.id)}`, {
      method: "DELETE",
    });
    state.documentPreview.content = "文档已删除。";
    await Promise.all([loadDocuments(), loadOperationEvents()]);
    showToast("文档已删除，相关 chunks 也已清理。");
  }

  async function reindexDocument(doc) {
    const kb = requireActiveKb();
    setOperationStatus("正在重建文档索引...", "busy");
    await api(`/knowledge-bases/${encodeURIComponent(kb.id)}/documents/${encodeURIComponent(doc.id)}/reindex`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    await Promise.all([loadDocuments(), loadOperationEvents()]);
    setOperationStatus("索引已重建。");
    showToast("索引已重建。");
  }

  async function submitQuestion() {
    const kb = requireActiveKb();
    if (!canAsk.value) {
      throw new Error("当前知识库未授权问答技能。");
    }
    const question = drafts.query.question.trim();
    if (!question) {
      throw new Error("请输入问题。");
    }

    const kbId = kb.id;
    const requestId = ++state.requests.query;
    const conversationId = activeConversationId.value;
    if (state.queryAbortController) {
      state.queryAbortController.abort();
    }
    const controller = new AbortController();
    state.queryAbortController = controller;
    state.ask.answer = "";
    state.ask.traceId = "流式输出中...";
    state.ask.streaming = true;
    setOperationStatus("正在当前知识库内流式生成回答...", "busy");

    let answer = "";
    let response = null;
    try {
      response = await streamText(
        `/knowledge-bases/${encodeURIComponent(kbId)}/query/stream`,
        {
          method: "POST",
          signal: controller.signal,
          body: JSON.stringify({
            question,
            top_k: 5,
            ...(conversationId ? { conversation_id: conversationId } : {}),
          }),
        },
        (chunk) => {
          if (requestId !== state.requests.query || state.activeKb?.id !== kbId) {
            controller.abort();
            return;
          }
          answer += chunk;
          state.ask.answer = answer;
        },
      );
    } catch (error) {
      if (error.name === "AbortError") {
        return;
      }
      throw error;
    } finally {
      if (state.queryAbortController === controller) {
        state.queryAbortController = null;
      }
      if (requestId === state.requests.query && state.activeKb?.id === kbId) {
        state.ask.streaming = false;
        state.ask.traceId = "";
      }
    }

    if (requestId !== state.requests.query || state.activeKb?.id !== kbId) {
      return;
    }
    if (!answer.trim()) {
      state.ask.answer = "没有返回回答。";
    }
    const responseConversationId = response?.headers.get("X-Conversation-Id") || conversationId;
    rememberConversation(kbId, responseConversationId);
    await Promise.all([loadConversations(), loadOperationEvents()]);
    setOperationStatus("问答完成。");
    showToast("已完成流式回答。");
  }

  async function selectConversation(conversation) {
    const kb = requireActiveKb();
    rememberConversation(kb.id, conversation.id);
    state.conversationMessages = [];
    await loadConversationMessages(conversation.id);
    setOperationStatus("历史对话已加载，后续提问会接在这条上下文里。");
  }

  function newConversation() {
    const kb = requireActiveKb();
    forgetConversation(kb.id);
    state.conversationMessages = [];
    state.ask.answer = "新对话已准备好，输入问题后会自动保存。";
    state.ask.traceId = "";
    showToast("已切换到新对话。");
  }

  async function runSkill(skillName = drafts.generate.skillName, instruction = drafts.generate.instruction) {
    const kb = requireActiveKb();
    const currentSkill = skillName || drafts.generate.skillName;
    const currentInstruction = instruction.trim();
    if (!currentInstruction) {
      throw new Error("请输入生成要求。");
    }
    if (!kb.allowed_skills.includes(currentSkill)) {
      throw new Error("当前知识库未授权该技能。");
    }

    const kbId = kb.id;
    const requestId = ++state.requests.generate;
    state.generate.running = true;
    state.generate.answer = "";
    state.generate.traceId = "";
    state.generate.artifact = null;
    setOperationStatus(`正在执行 ${currentSkill}，生成交付物...`, "busy");
    try {
      const result = await api(`/knowledge-bases/${encodeURIComponent(kbId)}/skills/${encodeURIComponent(currentSkill)}`, {
        method: "POST",
        body: JSON.stringify({
          instruction: currentInstruction,
          top_k: 5,
        }),
      });
      if (requestId !== state.requests.generate || state.activeKb?.id !== kbId) {
        return;
      }
      state.generate.answer = result.answer || "没有返回生成结果。";
      state.generate.traceId = result.trace_id || "";
      state.generate.artifact = result.artifact || null;
      await Promise.all([loadArtifacts(), loadOperationEvents()]);
      setOperationStatus("生成完成，下载链接和历史记录已更新。");
      showToast("写文档技能执行完成。");
    } finally {
      if (requestId === state.requests.generate && state.activeKb?.id === kbId) {
        state.generate.running = false;
      }
    }
  }

  async function previewArtifact(artifact) {
    const kb = requireActiveKb();
    const preview = await api(
      `/knowledge-bases/${encodeURIComponent(kb.id)}/artifacts/${encodeURIComponent(artifact.id)}/preview`,
    );
    state.artifactPreview.title = preview.filename;
    state.artifactPreview.content = `# ${preview.filename}\n\n${preview.content}`;
    setOperationStatus(`已加载「${preview.filename}」生成预览。`);
  }

  async function downloadArtifact(artifact) {
    const response = await fetch(artifact.download_url, {
      headers: accessHeaders(),
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || `下载失败：${response.status}`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = artifact.filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  async function copyArtifactLink(artifact) {
    const url = new URL(artifact.download_url, window.location.origin).href;
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(url);
    } else {
      const input = document.createElement("input");
      input.value = url;
      document.body.appendChild(input);
      input.select();
      document.execCommand("copy");
      input.remove();
    }
    showToast("下载链接已复制。");
  }

  async function deleteArtifact(artifact) {
    const kb = requireActiveKb();
    await api(`/knowledge-bases/${encodeURIComponent(kb.id)}/artifacts/${encodeURIComponent(artifact.id)}`, {
      method: "DELETE",
    });
    state.artifactPreview.content = "生成文件已删除。";
    await Promise.all([loadArtifacts(), loadOperationEvents()]);
    showToast("生成文件已删除。");
  }

  async function regenerateArtifact(artifact) {
    if (!artifact.instruction) {
      throw new Error("这条历史记录缺少原始指令，无法重新生成。");
    }
    drafts.generate.skillName = artifact.skill;
    drafts.generate.instruction = artifact.instruction;
    state.activeTab = "generate";
    await runSkill(artifact.skill, artifact.instruction);
  }

  function maybeSuggestKnowledgeBaseId() {
    if (drafts.knowledgeBase.idTouched) {
      return;
    }
    drafts.knowledgeBase.id = drafts.knowledgeBase.name.trim()
      ? suggestKnowledgeBaseId(drafts.knowledgeBase.name.trim(), drafts.knowledgeBase.idSuffix)
      : "";
  }

  function setActiveTab(tab) {
    state.activeTab = tab;
  }

  function reportError(error) {
    const message = messageFromError(error);
    setOperationStatus(message, "error");
    showToast(message);
  }

  function requireActiveKb() {
    if (!state.activeKb) {
      throw new Error("请先选择一个知识库。");
    }
    return state.activeKb;
  }

  function selectedSkills() {
    return SKILL_OPTIONS.filter((skill) => drafts.knowledgeBase.skillFlags[skill.value]).map((skill) => skill.value);
  }

  function resetKnowledgeBaseDraft() {
    drafts.knowledgeBase.id = "";
    drafts.knowledgeBase.name = "";
    drafts.knowledgeBase.tenantId = state.identity.tenantId || "default";
    drafts.knowledgeBase.permissionTags = "";
    drafts.knowledgeBase.idTouched = false;
    drafts.knowledgeBase.idSuffix = Date.now().toString(36).slice(-6);
    drafts.knowledgeBase.skillFlags = Object.fromEntries(SKILL_OPTIONS.map((skill) => [skill.value, true]));
  }

  function resetTransientDrafts() {
    drafts.sidebar.search = "";
    drafts.query.question = "";
    drafts.document.title = "";
    drafts.document.content = "";
    drafts.document.permissionTags = "";
    drafts.upload.permissionTags = "";
    drafts.generate.skillName = "write_document";
    drafts.generate.instruction = "";
  }

  function resetActiveOutputs() {
    state.ask.answer = "问答结果会显示在这里。";
    state.ask.traceId = "";
    state.ask.streaming = false;
    state.generate.answer = "生成结果会显示在这里。";
    state.generate.traceId = "";
    state.generate.artifact = null;
    state.generate.running = false;
    state.documentPreview.title = "";
    state.documentPreview.content = "点击文档的“预览”查看解析后的入库文本。";
    state.artifactPreview.title = "";
    state.artifactPreview.content = "点击生成历史的“预览”查看文件内容。";
  }

  function clearActiveKbWorkspace() {
    state.documents = [];
    state.artifacts = [];
    state.conversations = [];
    state.conversationMessages = [];
    state.operationEvents = [];
  }

  function resetWorkspaceForIdentitySwitch() {
    Object.keys(state.requests).forEach((key) => {
      state.requests[key] += 1;
    });
    if (state.queryAbortController) {
      state.queryAbortController.abort();
      state.queryAbortController = null;
    }
    state.knowledgeBases = [];
    state.activeKb = null;
    state.activeKbId = "";
    state.recentKbIds = [];
    state.conversationIds = {};
    state.activeTab = "ask";
    clearActiveKbWorkspace();
    resetActiveOutputs();
    Object.assign(drafts.docFilters, DEFAULT_DOC_FILTERS);
    resetTransientDrafts();
    resetKnowledgeBaseDraft();
    setOperationStatus("正在加载当前用户的独立工作区...", "busy");
  }

  function invalidateActiveRequests() {
    ["documents", "artifacts", "conversations", "conversationMessages", "operationEvents", "query", "generate"].forEach(
      (key) => {
        state.requests[key] += 1;
      },
    );
    if (state.queryAbortController) {
      state.queryAbortController.abort();
      state.queryAbortController = null;
    }
  }

  function rememberKnowledgeBase(kbId) {
    state.activeKbId = kbId;
    state.recentKbIds = [kbId, ...state.recentKbIds.filter((id) => id !== kbId)].slice(0, 5);
    persistScopedState("active_kb", state.activeKbId);
    persistScopedState("recent_kbs", state.recentKbIds);
  }

  function rememberConversation(kbId, conversationId) {
    if (!conversationId) {
      return;
    }
    state.conversationIds = {
      ...state.conversationIds,
      [kbId]: conversationId,
    };
    persistScopedState("conversations", state.conversationIds);
  }

  function forgetConversation(kbId) {
    const { [kbId]: _conversationId, ...remaining } = state.conversationIds;
    state.conversationIds = remaining;
    persistScopedState("conversations", state.conversationIds);
  }

  function activateSession({ token, identity, expiresAt = 0 }) {
    const normalizedIdentity = normalizeIdentity(identity);
    resetWorkspaceForIdentitySwitch();
    state.isAuthenticated = true;
    state.authToken = token || "";
    state.identity = normalizedIdentity;
    state.sessionExpiresAt = Number(expiresAt || 0);
    state.storageNamespace = storageNamespaceFor(normalizedIdentity);
    resetTransientDrafts();
    drafts.knowledgeBase.tenantId = normalizedIdentity.tenantId;
    hydrateScopedState();
    writeSessionProfile({
      token: state.authToken,
      identity: normalizedIdentity,
      expiresAt: state.sessionExpiresAt,
      storageNamespace: state.storageNamespace,
    });
  }

  function restoreSessionProfile(profile) {
    if (!profile) {
      return false;
    }
    if (profile.expiresAt && Number(profile.expiresAt) * 1000 <= Date.now()) {
      clearSessionProfile();
      return false;
    }
    const identity = normalizeIdentity(profile.identity || DEFAULT_IDENTITY);
    state.isAuthenticated = true;
    state.authToken = profile.token || "";
    state.identity = identity;
    state.sessionExpiresAt = Number(profile.expiresAt || 0);
    state.storageNamespace = profile.storageNamespace || storageNamespaceFor(identity);
    drafts.login.username = identity.username || identity.userId;
    drafts.login.password = "";
    drafts.knowledgeBase.tenantId = identity.tenantId;
    hydrateScopedState();
    return true;
  }

  function clearSession() {
    Object.keys(state.requests).forEach((key) => {
      state.requests[key] += 1;
    });
    if (state.queryAbortController) {
      state.queryAbortController.abort();
      state.queryAbortController = null;
    }
    state.isAuthenticated = false;
    state.authToken = "";
    state.sessionExpiresAt = 0;
    state.storageNamespace = "";
    state.identity = { ...DEFAULT_IDENTITY };
    state.knowledgeBases = [];
    state.activeKb = null;
    state.activeKbId = "";
    state.recentKbIds = [];
    state.conversationIds = {};
    state.activeTab = "ask";
    clearActiveKbWorkspace();
    resetActiveOutputs();
    Object.assign(drafts.docFilters, DEFAULT_DOC_FILTERS);
    drafts.login.password = "";
    resetTransientDrafts();
    resetKnowledgeBaseDraft();
    clearSessionProfile();
  }

  async function revokeAuthTokenOnServer() {
    if (!state.authToken) {
      return "";
    }
    try {
      await api("/auth/logout", { method: "POST" });
      return "Token 已在服务端撤销。";
    } catch (error) {
      const message = messageFromError(error);
      if (message.includes("Redis") || message.includes("disabled") || message.includes("unavailable")) {
        return "服务端未启用 Redis，已仅清理本地 Token。";
      }
      if (message.includes("JWT") || message.includes("expired") || message.includes("invalid")) {
        return "Token 已失效，已清理本地 Token。";
      }
      throw error;
    }
  }

  function hydrateScopedState() {
    state.recentKbIds = readScopedJson("recent_kbs", []);
    state.conversationIds = readScopedJson("conversations", {});
    state.activeKbId = readScopedJson("active_kb", "");
    state.activeTab = readScopedJson("active_tab", "ask");
    Object.assign(drafts.docFilters, {
      ...DEFAULT_DOC_FILTERS,
      ...readScopedJson("doc_filters", DEFAULT_DOC_FILTERS),
    });
  }

  function accessHeaders() {
    if (state.authToken) {
      return { Authorization: `Bearer ${state.authToken}` };
    }
    return {
      "X-User-Id": state.identity.userId,
      "X-Tenant-Id": state.identity.tenantId,
      "X-Permission-Tags": state.identity.permissionTags.join(","),
    };
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...accessHeaders(),
        ...(options.headers || {}),
      },
    });
    const text = await response.text();
    const data = parseResponseBody(text);
    if (!response.ok) {
      throw new Error(errorMessage(data, `请求失败：${response.status}`));
    }
    return data;
  }

  async function streamText(path, options = {}, onChunk) {
    const response = await fetch(path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...accessHeaders(),
        ...(options.headers || {}),
      },
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(errorMessage(parseResponseBody(text), `请求失败：${response.status}`));
    }

    if (!response.body) {
      onChunk(await response.text());
      return response;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }
        onChunk(decoder.decode(value, { stream: true }));
      }
      const tail = decoder.decode();
      if (tail) {
        onChunk(tail);
      }
    } finally {
      reader.releaseLock();
    }
    return response;
  }

  function setOperationStatus(message, tone = "idle") {
    state.operationStatus.message = message;
    state.operationStatus.tone = tone;
  }

  function showToast(message) {
    state.toast.message = message;
    state.toast.visible = true;
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => {
      state.toast.visible = false;
    }, 2800);
  }

  function parseTags(value) {
    return value
      .split(",")
      .map((tag) => tag.trim())
      .filter(Boolean);
  }

  function identityFromLoginDraft() {
    return normalizeIdentity({
      userId: drafts.login.username.trim() || DEFAULT_IDENTITY.userId,
      tenantId: DEFAULT_IDENTITY.tenantId,
      permissionTags: [],
    });
  }

  function identityFromLoginResponse(user) {
    return normalizeIdentity({
      userId: user.user_id || user.username,
      username: user.username,
      role: user.role,
      tenantId: user.tenant_id || DEFAULT_IDENTITY.tenantId,
      permissionTags: user.permission_tags || [],
    });
  }

  function identityFromToken(token) {
    const payload = decodeTokenPayload(token);
    if (!payload) {
      throw new Error("JWT Token 格式不可读，无法登录。");
    }
    return normalizeIdentity({
      userId: payload.user_id || payload.sub || DEFAULT_IDENTITY.userId,
      username: payload.username || payload.user_id || payload.sub || DEFAULT_IDENTITY.userId,
      role: payload.role || "user",
      tenantId: payload.tenant_id || DEFAULT_IDENTITY.tenantId,
      permissionTags: Array.isArray(payload.permission_tags) ? payload.permission_tags : DEFAULT_IDENTITY.permissionTags,
    });
  }

  function normalizeIdentity(identity) {
    return {
      userId: (identity.userId || DEFAULT_IDENTITY.userId).trim() || DEFAULT_IDENTITY.userId,
      username: (identity.username || identity.userId || DEFAULT_IDENTITY.userId).trim() || DEFAULT_IDENTITY.userId,
      role: identity.role === "admin" ? "admin" : "user",
      tenantId: (identity.tenantId || DEFAULT_IDENTITY.tenantId).trim() || DEFAULT_IDENTITY.tenantId,
      permissionTags: Array.from(new Set(identity.permissionTags || [])).filter(Boolean),
    };
  }

  function storageNamespaceFor(identity) {
    const normalized = normalizeIdentity(identity);
    const tags = [...normalized.permissionTags].sort().join(",");
    return [
      "rag_demo_state",
      encodeURIComponent(normalized.tenantId),
      encodeURIComponent(normalized.userId),
      encodeURIComponent(tags || "public"),
    ].join(":");
  }

  function scopedStorageKey(key) {
    return state.storageNamespace ? `${state.storageNamespace}:${key}` : "";
  }

  function readScopedJson(key, fallback) {
    const scopedKey = scopedStorageKey(key);
    if (!scopedKey) {
      return fallback;
    }
    try {
      const value = window.localStorage.getItem(scopedKey);
      return value ? JSON.parse(value) : fallback;
    } catch {
      return fallback;
    }
  }

  function persistScopedState(key, value) {
    const scopedKey = scopedStorageKey(key);
    if (!scopedKey) {
      return;
    }
    window.localStorage.setItem(scopedKey, JSON.stringify(value));
  }

  function readSessionProfile() {
    try {
      const value = window.sessionStorage.getItem(SESSION_PROFILE_KEY);
      return value ? JSON.parse(value) : null;
    } catch {
      return null;
    }
  }

  function writeSessionProfile(profile) {
    window.sessionStorage.setItem(SESSION_PROFILE_KEY, JSON.stringify(profile));
  }

  function clearSessionProfile() {
    window.sessionStorage.removeItem(SESSION_PROFILE_KEY);
  }

  return {
    state,
    drafts,
    skillOptions: SKILL_OPTIONS,
    computed: {
      activeConversationId,
      activeConversation,
      activeConversationLabel,
      canAsk,
      canGenerate,
      filteredDocuments,
      recentKnowledgeBases,
      tokenExpiryText,
      tokenPayload,
      visibleKnowledgeBases,
    },
    actions: {
      addTextDocument,
      bootstrap,
      copyArtifactLink,
      createKnowledgeBase,
      deleteArtifact,
      deleteDocument,
      deleteKnowledgeBase,
      downloadArtifact,
      loadArtifacts,
      loadConversations,
      loadDocuments,
      loadKnowledgeBases,
      loadOperationEvents,
      loginFromDraft,
      logoutToLogin,
      maybeSuggestKnowledgeBaseId,
      newConversation,
      previewArtifact,
      previewDocument,
      refreshWorkspace,
      regenerateArtifact,
      reindexDocument,
      reportError,
      runSkill,
      selectConversation,
      setActiveTab,
      showToast,
      submitQuestion,
      switchKnowledgeBase,
      uploadDocument,
    },
    utils: {
      formatTime,
      isValidKnowledgeBaseId,
      runtimeModelStatus,
      statusClass,
    },
  };
}

function decodeTokenPayload(token) {
  if (!token) {
    return null;
  }
  const parts = token.split(".");
  if (parts.length !== 3) {
    return null;
  }
  try {
    const base64 = parts[1].replaceAll("-", "+").replaceAll("_", "/");
    const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
    return JSON.parse(decodeURIComponent(escape(window.atob(padded))));
  } catch {
    return null;
  }
}

function parseResponseBody(text) {
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function errorMessage(data, fallback) {
  if (!data) {
    return fallback;
  }
  if (typeof data === "string") {
    return data;
  }
  if (typeof data.detail === "string") {
    return data.detail;
  }
  if (Array.isArray(data.detail)) {
    return data.detail.map((item) => item.msg || JSON.stringify(item)).join("; ");
  }
  return fallback;
}

function messageFromError(error) {
  return error?.message || String(error || "未知错误");
}

function formatTime(value) {
  if (!value) {
    return "-";
  }
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function statusClass(status) {
  if (status === "indexed") {
    return "ok";
  }
  if (status === "failed") {
    return "bad";
  }
  return "busy";
}

function isValidKnowledgeBaseId(value) {
  return /^[a-zA-Z0-9_-]{2,64}$/.test(value);
}

function suggestKnowledgeBaseId(name, suffix) {
  const ascii = name
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
  const stem = ascii && /[a-z0-9]/.test(ascii) ? ascii : "kb";
  return `${stem}-${suffix}`.slice(0, 64);
}

function runtimeModelStatus(config) {
  if (!config) {
    return {
      className: "",
      text: "模型配置加载中...",
    };
  }
  const llmReady = config.llm_ready ? "ready" : "missing key";
  const embeddingReady = config.embedding_ready ? "ready" : "missing key";
  const cacheReady = config.cache_store === "disabled" ? "disabled" : config.cache_ready ? "ready" : "unavailable";
  return {
    className: config.llm_provider === "deepseek" && config.llm_ready ? "ready" : "warn",
    text: [
      `Metadata: ${config.metadata_store || "sqlite"} / ${config.metadata_store_uri || ".rag_data/boundaryrag.sqlite3"}`,
      `Vector: ${config.vector_store || "milvus-lite"} / ${config.vector_store_collection || "boundaryrag_chunks"}`,
      `Session: ${config.session_store || "redis"} / TTL ${config.session_ttl_seconds || 86400}s`,
      `Cache: ${config.cache_store || "redis"} / ${config.cache_store_uri || "redis://localhost:6379/0"} / ${cacheReady}`,
      `LLM: ${config.llm_provider} / ${config.llm_model} / ${llmReady}`,
      `Embedding: ${config.embedding_provider} / ${config.embedding_model} / ${embeddingReady}`,
    ].join(" · "),
  };
}
