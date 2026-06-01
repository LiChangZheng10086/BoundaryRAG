const SESSION_PROFILE_KEY = "rag_demo_session_profile";
const state = {
  knowledgeBases: [],
  activeKb: null,
  activeKbId: "",
  documents: [],
  artifacts: [],
  conversations: [],
  conversationMessages: [],
  operationEvents: [],
  runtimeConfig: null,
  activeTab: "ask",
  authToken: "",
  storageNamespace: "",
  isAuthenticated: false,
  recentKbIds: [],
  conversationIds: {},
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
  docFilters: {
    search: "",
    status: "",
    tag: "",
    sort: "newest",
  },
  lastQueryText: "",
  lastGenerateText: "",
  queryAbortController: null,
  identity: {
    userId: "demo-user",
    tenantId: "default",
    permissionTags: ["hr", "finance", "salary"],
  },
};

const $ = (id) => document.getElementById(id);
const defaultIdentity = {
  userId: "demo-user",
  tenantId: "default",
  permissionTags: ["hr", "finance", "salary"],
};
const defaultDocFilters = {
  search: "",
  status: "",
  tag: "",
  sort: "newest",
};

function normalizeIdentity(identity) {
  return {
    userId: (identity.userId || defaultIdentity.userId).trim() || defaultIdentity.userId,
    tenantId: (identity.tenantId || defaultIdentity.tenantId).trim() || defaultIdentity.tenantId,
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
  if (!state.storageNamespace) {
    return "";
  }
  return `${state.storageNamespace}:${key}`;
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

function writeScopedJson(key, value) {
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

function hydrateScopedState() {
  state.recentKbIds = readScopedJson("recent_kbs", []);
  state.conversationIds = readScopedJson("conversations", {});
  state.activeKbId = readScopedJson("active_kb", "");
  state.activeTab = readScopedJson("active_tab", "ask");
  state.docFilters = {
    ...defaultDocFilters,
    ...readScopedJson("doc_filters", defaultDocFilters),
  };
}

function persistScopedState(key, value) {
  writeScopedJson(key, value);
}

const els = {
  activeKbLabel: $("activeKbLabel"),
  appShell: $("appShell"),
  answerBox: $("answerBox"),
  artifactBox: $("artifactBox"),
  artifactPreview: $("artifactPreview"),
  artifactList: $("artifactList"),
  authModeLabel: $("authModeLabel"),
  boundarySkills: $("boundarySkills"),
  boundaryTitle: $("boundaryTitle"),
  activeConversationLabel: $("activeConversationLabel"),
  conversationList: $("conversationList"),
  conversationMessages: $("conversationMessages"),
  docContent: $("docContent"),
  docForm: $("docForm"),
  docPermissionTags: $("docPermissionTags"),
  docSearch: $("docSearch"),
  docSort: $("docSort"),
  docStatusFilter: $("docStatusFilter"),
  docTagFilter: $("docTagFilter"),
  docTitle: $("docTitle"),
  documentList: $("documentList"),
  generateAnswerBox: $("generateAnswerBox"),
  generateArtifactBox: $("generateArtifactBox"),
  generateTraceId: $("generateTraceId"),
  instruction: $("instruction"),
  kbForm: $("kbForm"),
  kbId: $("kbId"),
  kbList: $("kbList"),
  kbName: $("kbName"),
  kbPermissionTags: $("kbPermissionTags"),
  kbSearch: $("kbSearch"),
  kbSkills: $("kbSkills"),
  kbTenantId: $("kbTenantId"),
  modelStatus: $("modelStatus"),
  loginForm: $("loginForm"),
  loginHint: $("loginHint"),
  loginPermissionTags: $("loginPermissionTags"),
  loginScreen: $("loginScreen"),
  loginSubmitBtn: $("loginSubmitBtn"),
  loginTenantId: $("loginTenantId"),
  loginToken: $("loginToken"),
  loginUserId: $("loginUserId"),
  logoutBtn: $("logoutBtn"),
  question: $("question"),
  queryForm: $("queryForm"),
  querySubmit: $("querySubmit"),
  identityUser: $("identityUser"),
  identityTenant: $("identityTenant"),
  identityTags: $("identityTags"),
  settingsIdentity: $("settingsIdentity"),
  settingsKnowledgeBase: $("settingsKnowledgeBase"),
  settingsKnowledgeBaseMeta: $("settingsKnowledgeBaseMeta"),
  sidebarActiveKb: $("sidebarActiveKb"),
  sidebarBoundaryMeta: $("sidebarBoundaryMeta"),
  operationStatus: $("operationStatus"),
  operationStatusText: $("operationStatusText"),
  operationList: $("operationList"),
  tokenExpiry: $("tokenExpiry"),
  documentPreview: $("documentPreview"),
  reloadDocsBtn: $("reloadDocsBtn"),
  reloadArtifactsBtn: $("reloadArtifactsBtn"),
  reloadConversationsBtn: $("reloadConversationsBtn"),
  reloadOperationsBtn: $("reloadOperationsBtn"),
  refreshBtn: $("refreshBtn"),
  newConversationBtn: $("newConversationBtn"),
  skillForm: $("skillForm"),
  skillName: $("skillName"),
  skillSubmit: $("skillSubmit"),
  selectedSkillPill: $("selectedSkillPill"),
  toast: $("toast"),
  traceId: $("traceId"),
  uploadFile: $("uploadFile"),
  uploadForm: $("uploadForm"),
  uploadPermissionTags: $("uploadPermissionTags"),
};

function showToast(message) {
  els.toast.textContent = message;
  els.toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => els.toast.classList.remove("show"), 2800);
}

function setOperationStatus(message, tone = "idle") {
  els.operationStatusText.textContent = message;
  els.operationStatus.classList.toggle("busy", tone === "busy");
  els.operationStatus.classList.toggle("error", tone === "error");
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

function requireActiveKb() {
  if (!state.activeKb) {
    throw new Error("请先选择一个知识库。");
  }
  return state.activeKb;
}

function selectedSkills() {
  return Array.from(els.kbSkills.querySelectorAll("input[type='checkbox']:checked")).map((input) => input.value);
}

function parseTags(value) {
  return value
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
}

function isValidKnowledgeBaseId(value) {
  return /^[a-zA-Z0-9_-]{2,64}$/.test(value);
}

function suggestKnowledgeBaseId(name) {
  const ascii = name
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
  const suffix = Date.now().toString(36).slice(-6);
  const stem = ascii && /[a-z0-9]/.test(ascii) ? ascii : "kb";
  return `${stem}-${suffix}`.slice(0, 64);
}

function accessPayload() {
  return {
    user_id: state.identity.userId,
    tenant_id: state.identity.tenantId,
    permission_tags: state.identity.permissionTags,
  };
}

function accessHeaders() {
  if (state.authToken) {
    return {
      Authorization: `Bearer ${state.authToken}`,
    };
  }

  const access = accessPayload();
  return {
    "X-User-Id": access.user_id,
    "X-Tenant-Id": access.tenant_id,
    "X-Permission-Tags": access.permission_tags.join(","),
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

function identityFromToken(token) {
  const payload = decodeTokenPayload(token);
  if (!payload) {
    throw new Error("JWT Token 格式不可读，无法登录。");
  }
  return normalizeIdentity({
    userId: payload.user_id || payload.sub || defaultIdentity.userId,
    tenantId: payload.tenant_id || defaultIdentity.tenantId,
    permissionTags: Array.isArray(payload.permission_tags) ? payload.permission_tags : defaultIdentity.permissionTags,
  });
}

function identityFromForm() {
  return normalizeIdentity({
    userId: els.loginUserId.value.trim() || defaultIdentity.userId,
    tenantId: els.loginTenantId.value.trim() || defaultIdentity.tenantId,
    permissionTags: parseTags(els.loginPermissionTags.value),
  });
}

function buildSessionProfile({ token, identity }) {
  return {
    token,
    identity,
    storageNamespace: storageNamespaceFor(identity),
  };
}

function restoreSessionProfile(profile) {
  if (!profile) {
    return false;
  }
  const identity = normalizeIdentity(profile.identity || defaultIdentity);
  const token = profile.token || "";
  state.isAuthenticated = true;
  state.authToken = token;
  state.identity = identity;
  state.storageNamespace = profile.storageNamespace || storageNamespaceFor(identity);
  hydrateScopedState();
  return true;
}

function activateSession({ token, identity }) {
  const normalizedIdentity = normalizeIdentity(identity);
  state.isAuthenticated = true;
  state.authToken = token;
  state.identity = normalizedIdentity;
  state.storageNamespace = storageNamespaceFor(normalizedIdentity);
  hydrateScopedState();
  state.activeKb = null;
  if (state.activeKbId) {
    state.activeKb = state.knowledgeBases.find((kb) => kb.id === state.activeKbId) || null;
  }
  if (state.activeKb && state.activeKb.tenant_id !== state.identity.tenantId) {
    state.activeKb = null;
  }
  writeSessionProfile(buildSessionProfile({ token, identity: normalizedIdentity }));
  renderShell();
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
  state.storageNamespace = "";
  state.recentKbIds = [];
  state.conversationIds = {};
  state.activeKbId = "";
  state.activeKb = null;
  state.documents = [];
  state.artifacts = [];
  state.conversations = [];
  state.conversationMessages = [];
  state.operationEvents = [];
  state.activeTab = "ask";
  state.docFilters = { ...defaultDocFilters };
  state.identity = { ...defaultIdentity };
  clearSessionProfile();
  renderShell();
}

function renderAuthStatus() {
  const payload = decodeTokenPayload(state.authToken);
  const modeLabel = state.authToken ? "Bearer Token 登录" : "演示登录";
  if (!state.isAuthenticated) {
    els.authModeLabel.textContent = "未登录";
    els.tokenExpiry.textContent = "请先在登录页完成身份验证。";
    return;
  }
  els.authModeLabel.textContent = payload ? modeLabel : "演示登录";
  if (!payload?.exp) {
    els.tokenExpiry.textContent = state.authToken
      ? "Token 已保存，但未发现过期时间。"
      : "当前会话使用演示身份，不依赖 Token。";
    return;
  }
  const expiresAt = new Date(payload.exp * 1000);
  const expired = expiresAt.getTime() <= Date.now();
  els.tokenExpiry.textContent = `${expired ? "已过期" : "过期时间"}：${formatTime(expiresAt.toISOString())}`;
}

function renderLoginHint() {
  if (!els.loginHint) {
    return;
  }
  const authMode = state.runtimeConfig?.auth_mode || "demo";
  const redis = state.runtimeConfig?.cache_store === "redis"
    ? (state.runtimeConfig.cache_ready ? "Redis 已连接，可撤销 JWT。" : "Redis 未连接，退出登录仅清本地。")
    : "Redis 未启用，退出登录仅清本地。";
  els.loginHint.textContent = authMode === "jwt"
    ? `当前后端要求 JWT 登录；请粘贴 Bearer Token 后进入。${redis}`
    : `当前后端允许演示身份登录；也可以粘贴 JWT 切换为 Bearer 鉴权。${redis}`;
}

function syncControlsFromState() {
  els.docSearch.value = state.docFilters.search;
  els.docStatusFilter.value = state.docFilters.status;
  els.docTagFilter.value = state.docFilters.tag;
  els.docSort.value = state.docFilters.sort;
}

function renderShell() {
  if (els.loginScreen) {
    els.loginScreen.hidden = state.isAuthenticated;
  }
  if (els.appShell) {
    els.appShell.hidden = !state.isAuthenticated;
  }
  document.body.classList.toggle("auth-locked", !state.isAuthenticated);
  if (!state.isAuthenticated) {
    els.loginUserId.value = defaultIdentity.userId;
    els.loginTenantId.value = defaultIdentity.tenantId;
    els.loginPermissionTags.value = defaultIdentity.permissionTags.join(", ");
    els.loginToken.value = "";
  } else {
    syncControlsFromState();
  }
  renderLoginHint();
  renderAuthStatus();
}

function renderModelStatus() {
  const config = state.runtimeConfig;
  if (!config) {
    els.modelStatus.textContent = "模型配置加载中...";
    els.modelStatus.className = "model-status";
    return;
  }

  const llmReady = config.llm_ready ? "ready" : "missing key";
  const embeddingReady = config.embedding_ready ? "ready" : "missing key";
  const cacheReady = config.cache_store === "disabled" ? "disabled" : (config.cache_ready ? "ready" : "unavailable");
  els.modelStatus.className = `model-status ${config.llm_provider === "deepseek" && config.llm_ready ? "ready" : "warn"}`;
  els.modelStatus.textContent = [
    `Metadata: ${config.metadata_store || "sqlite"} / ${config.metadata_store_uri || ".rag_data/boundaryrag.sqlite3"}`,
    `Vector: ${config.vector_store || "milvus-lite"} / ${config.vector_store_collection || "boundaryrag_chunks"}`,
    `Cache: ${config.cache_store || "redis"} / ${config.cache_store_uri || "redis://localhost:6379/0"} / ${cacheReady}`,
    `LLM: ${config.llm_provider} / ${config.llm_model} / ${llmReady}`,
    `Embedding: ${config.embedding_provider} / ${config.embedding_model} / ${embeddingReady}`,
  ].join(" · ");
}

function rememberKnowledgeBase(kbId) {
  state.activeKbId = kbId;
  state.recentKbIds = [kbId, ...state.recentKbIds.filter((id) => id !== kbId)].slice(0, 5);
  persistScopedState("active_kb", state.activeKbId);
  persistScopedState("recent_kbs", state.recentKbIds);
}

function activeConversationId(kbId) {
  return state.conversationIds[kbId] || "";
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

async function revokeAuthTokenOnServer() {
  if (!state.authToken) {
    return "";
  }
  try {
    await api("/auth/logout", { method: "POST" });
    return "Token 已在服务端撤销。";
  } catch (error) {
    const message = error.message || "";
    if (message.includes("Redis") || message.includes("disabled") || message.includes("unavailable")) {
      return "服务端未启用 Redis，已仅清理本地 Token。";
    }
    if (message.includes("JWT") || message.includes("expired") || message.includes("invalid")) {
      return "Token 已失效，已清理本地 Token。";
    }
    throw error;
  }
}

async function loadCurrentUserWorkspace() {
  await loadKnowledgeBases();
  await loadDocuments();
  await loadArtifacts();
  await loadConversations();
  await loadOperationEvents();
}

async function loginFromForm() {
  const token = els.loginToken.value.trim();
  if (!token && state.runtimeConfig?.auth_mode === "jwt") {
    throw new Error("当前环境要求 JWT 登录，请先粘贴 Bearer Token。");
  }

  const identity = token ? identityFromToken(token) : identityFromForm();
  const payload = token ? decodeTokenPayload(token) : null;
  if (payload?.exp && payload.exp * 1000 <= Date.now()) {
    throw new Error("JWT Token 已过期，请重新登录。");
  }

  activateSession({ token, identity });
  try {
    await loadCurrentUserWorkspace();
  } catch (error) {
    clearSession();
    throw error;
  }

  renderShell();
  setOperationStatus(`已登录为 ${state.identity.userId} / ${state.identity.tenantId}。`);
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
    renderShell();
    showToast(serverMessage || "已退出登录。");
    setOperationStatus("请先在登录页完成登录。");
  }
}

function forgetConversation(kbId) {
  const { [kbId]: _conversationId, ...remaining } = state.conversationIds;
  state.conversationIds = remaining;
  persistScopedState("conversations", state.conversationIds);
}

function renderKnowledgeBases() {
  els.kbList.innerHTML = "";

  const keyword = els.kbSearch.value.trim().toLowerCase();
  const filtered = state.knowledgeBases
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
      ].join(" ").toLowerCase();
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

  if (!state.knowledgeBases.length) {
    const empty = document.createElement("p");
    empty.className = "source";
    empty.textContent = "还没有知识库，先创建一个。";
    els.kbList.appendChild(empty);
    return;
  }

  if (!filtered.length) {
    const empty = document.createElement("p");
    empty.className = "source";
    empty.textContent = "没有匹配的知识库。";
    els.kbList.appendChild(empty);
    return;
  }

  for (const kb of filtered) {
    const item = document.createElement("div");
    item.className = `kb-item ${state.activeKb?.id === kb.id ? "active" : ""}`;
    const recentLabel = state.recentKbIds.includes(kb.id) ? " · 最近使用" : "";
    item.innerHTML = `
      <button class="kb-select" type="button">
        <strong>${escapeHtml(kb.name)}</strong>
        <small>${escapeHtml(kb.id)} · tenant ${escapeHtml(kb.tenant_id)}${recentLabel} · ${escapeHtml(kb.allowed_skills.join(", "))}</small>
      </button>
      <button class="kb-delete ghost" type="button" aria-label="删除 ${escapeHtml(kb.name)}">删除</button>
    `;
    item.querySelector(".kb-select").addEventListener("click", () => {
      state.activeKb = kb;
      state.requests.query += 1;
      state.requests.generate += 1;
      state.requests.conversations += 1;
      state.requests.conversationMessages += 1;
      if (state.queryAbortController) {
        state.queryAbortController.abort();
        state.queryAbortController = null;
      }
      rememberKnowledgeBase(kb.id);
      state.conversations = [];
      state.conversationMessages = [];
      els.documentPreview.textContent = "点击文档的“预览”查看解析后的入库文本。";
      els.answerBox.textContent = "问答结果会显示在这里。";
      els.generateAnswerBox.textContent = "生成结果会显示在这里。";
      els.artifactPreview.textContent = "点击生成历史的“预览”查看文件内容。";
      els.artifactBox.innerHTML = "";
      els.generateArtifactBox.innerHTML = "";
      loadDocuments().catch((error) => showToast(error.message));
      loadArtifacts().catch((error) => showToast(error.message));
      loadConversations().catch((error) => showToast(error.message));
      loadOperationEvents().catch((error) => showToast(error.message));
      setOperationStatus(`已切换到 ${kb.name}，边界已锁定。`);
      renderAll();
    });
    item.querySelector(".kb-delete").addEventListener("click", (event) => {
      handleButton(event.currentTarget, async () => {
        const confirmed = window.confirm(`确认删除「${kb.name}」吗？该知识库下的文档、chunks 和生成记录都会删除。`);
        if (!confirmed) {
          return;
        }
        await api(`/knowledge-bases/${encodeURIComponent(kb.id)}`, { method: "DELETE" });
        state.recentKbIds = state.recentKbIds.filter((id) => id !== kb.id);
        const { [kb.id]: _deletedConversationId, ...remainingConversationIds } = state.conversationIds;
        state.conversationIds = remainingConversationIds;
        persistScopedState("recent_kbs", state.recentKbIds);
        persistScopedState("conversations", state.conversationIds);
        if (state.activeKb?.id === kb.id) {
          state.activeKb = null;
          state.activeKbId = "";
          state.documents = [];
          state.artifacts = [];
          state.conversations = [];
          state.conversationMessages = [];
          state.operationEvents = [];
          persistScopedState("active_kb", "");
          if (state.queryAbortController) {
            state.queryAbortController.abort();
            state.queryAbortController = null;
          }
          els.answerBox.textContent = "问答结果会显示在这里。";
          els.generateAnswerBox.textContent = "生成结果会显示在这里。";
          els.documentPreview.textContent = "点击文档的“预览”查看解析后的入库文本。";
          els.artifactPreview.textContent = "点击生成历史的“预览”查看文件内容。";
        }
        await loadKnowledgeBases();
        await loadDocuments();
        await loadArtifacts();
        await loadConversations();
        await loadOperationEvents();
        showToast("知识库已删除。");
      });
    });
    els.kbList.appendChild(item);
  }
}

function renderBoundary() {
  const identityLabel = `${state.identity.userId} / ${state.identity.tenantId} / ${state.identity.permissionTags.join(", ") || "-"}`;
  els.identityUser.textContent = state.isAuthenticated ? state.identity.userId : "未登录";
  els.identityTenant.textContent = state.isAuthenticated ? state.identity.tenantId : "-";
  els.identityTags.textContent = state.isAuthenticated ? (state.identity.permissionTags.join(", ") || "-") : "-";
  els.settingsIdentity.textContent = state.isAuthenticated ? identityLabel : "请先登录";
  renderAuthStatus();
  renderModelStatus();

  if (!state.isAuthenticated) {
    els.activeKbLabel.textContent = "尚未登录";
    els.sidebarActiveKb.textContent = "未登录";
    els.sidebarBoundaryMeta.textContent = "请先在登录页完成身份认证。";
    els.boundaryTitle.textContent = "登录后开始";
    els.boundarySkills.textContent = "skills: -";
    els.settingsKnowledgeBase.textContent = "未登录";
    els.settingsKnowledgeBaseMeta.textContent = "登录后会显示当前知识库、租户和权限标签。";
    els.querySubmit.disabled = true;
    els.skillSubmit.disabled = true;
    els.skillSubmit.textContent = "执行技能";
    return;
  }

  if (!state.activeKb) {
    els.activeKbLabel.textContent = "尚未选择知识库";
    els.sidebarActiveKb.textContent = "未选择";
    els.sidebarBoundaryMeta.textContent = "选择知识库后，问答、文档和生成都会锁定到同一边界。";
    els.boundaryTitle.textContent = "选择知识库后开始";
    els.boundarySkills.textContent = "skills: -";
    els.settingsKnowledgeBase.textContent = "未选择";
    els.settingsKnowledgeBaseMeta.textContent = "选择知识库后会显示租户、技能和权限标签。";
    els.querySubmit.disabled = true;
    els.skillSubmit.disabled = true;
    els.skillSubmit.textContent = "执行技能";
    return;
  }

  els.activeKbLabel.textContent = `${state.activeKb.name} · ${state.activeKb.id}`;
  els.sidebarActiveKb.textContent = state.activeKb.name;
  els.sidebarBoundaryMeta.textContent = `${state.activeKb.id} · tenant ${state.activeKb.tenant_id} · ${state.activeKb.permission_tags.join(", ") || "无额外标签"}`;
  els.boundaryTitle.textContent = `当前只使用：${state.activeKb.name}`;
  els.boundarySkills.textContent = `skills: ${state.activeKb.allowed_skills.join(", ")}`;
  els.settingsKnowledgeBase.textContent = `${state.activeKb.name} / ${state.activeKb.id}`;
  els.settingsKnowledgeBaseMeta.textContent = `租户 ${state.activeKb.tenant_id} · 权限 ${state.activeKb.permission_tags.join(", ") || "-"} · 技能 ${state.activeKb.allowed_skills.join(", ")}`;

  const canAsk = state.activeKb.allowed_skills.includes("answer_question");
  const selectedSkill = els.skillName.value;
  const canWrite = state.activeKb.allowed_skills.includes(selectedSkill);
  els.querySubmit.disabled = !canAsk;
  els.skillSubmit.disabled = !canWrite;
  els.selectedSkillPill.textContent = selectedSkill;
  els.skillSubmit.textContent = canWrite ? "执行技能" : "当前知识库未授权该技能";
}

function renderTabs() {
  document.querySelectorAll("[data-tab]").forEach((button) => {
    const selected = button.dataset.tab === state.activeTab;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-selected", selected ? "true" : "false");
  });
  document.querySelectorAll("[data-panel]").forEach((panel) => {
    const selected = panel.dataset.panel === state.activeTab;
    panel.classList.toggle("active", selected);
    panel.toggleAttribute("hidden", !selected);
  });
}

function renderResult(result, options = {}) {
  const answerBox = options.answerBox || els.answerBox;
  const trace = options.trace || els.traceId;
  const artifactBox = options.artifactBox || els.artifactBox;

  answerBox.textContent = result.answer || "没有返回回答。";
  trace.textContent = result.trace_id || "";
  artifactBox.innerHTML = "";

  if (result.artifact) {
    const link = document.createElement("a");
    link.className = "artifact-link";
    link.href = "#";
    link.textContent = `下载生成文件：${result.artifact.filename}`;
    link.addEventListener("click", (event) => {
      event.preventDefault();
      downloadArtifact(result.artifact).catch((error) => showToast(error.message));
    });
    artifactBox.appendChild(link);
  }
}

function renderDocuments() {
  els.documentList.innerHTML = "";

  if (!state.activeKb) {
    els.documentList.textContent = "选择知识库后会显示文档。";
    return;
  }

  const documents = filteredDocuments();
  if (!state.documents.length) {
    els.documentList.textContent = "当前知识库还没有文档。";
    return;
  }

  if (!documents.length) {
    els.documentList.textContent = "没有匹配筛选条件的文档。";
    return;
  }

  for (const doc of documents) {
    const item = document.createElement("div");
    item.className = "document-item";
    const errorText = doc.error ? `<p class="error-text">${escapeHtml(doc.error)}</p>` : "";
    const retryLabel = doc.status === "failed" ? "重试索引" : "重建索引";
    item.innerHTML = `
      <div>
        <strong>${escapeHtml(doc.title)}</strong>
        <span>${escapeHtml(doc.id)} · <b class="status-badge ${statusClass(doc.status)}">${escapeHtml(doc.status)}</b> · chunks ${doc.chunk_count} · tags ${escapeHtml(doc.permission_tags.join(", ") || "-")} · ${escapeHtml(formatTime(doc.created_at))}</span>
        ${errorText}
      </div>
      <div class="document-actions">
        <button class="ghost" data-action="preview" data-id="${escapeHtml(doc.id)}" type="button">预览</button>
        <button class="ghost" data-action="reindex" data-id="${escapeHtml(doc.id)}" type="button">${retryLabel}</button>
        <button class="danger" data-action="delete" data-id="${escapeHtml(doc.id)}" type="button">删除</button>
      </div>
    `;
    els.documentList.appendChild(item);
  }
}

function filteredDocuments() {
  const search = state.docFilters.search.trim().toLowerCase();
  const tag = state.docFilters.tag.trim().toLowerCase();
  const status = state.docFilters.status;
  const documents = state.documents.filter((doc) => {
    const tags = (doc.permission_tags || []).join(", ");
    const haystack = [doc.id, doc.title, doc.status, doc.error, tags].join(" ").toLowerCase();
    return (!search || haystack.includes(search))
      && (!status || doc.status === status)
      && (!tag || tags.toLowerCase().includes(tag));
  });

  return documents.sort((left, right) => {
    if (state.docFilters.sort === "oldest") {
      return new Date(left.created_at) - new Date(right.created_at);
    }
    if (state.docFilters.sort === "title") {
      return left.title.localeCompare(right.title, "zh-CN");
    }
    if (state.docFilters.sort === "status") {
      return left.status.localeCompare(right.status);
    }
    return new Date(right.created_at) - new Date(left.created_at);
  });
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

function renderArtifacts() {
  els.artifactList.innerHTML = "";

  if (!state.activeKb) {
    els.artifactList.textContent = "选择知识库后会显示生成文件。";
    return;
  }

  if (!state.artifacts.length) {
    els.artifactList.textContent = "当前知识库还没有生成文件。";
    return;
  }

  for (const artifact of state.artifacts) {
    const item = document.createElement("div");
    item.className = "document-item";
    const canRegenerate = artifact.instruction ? "" : "disabled";
    item.innerHTML = `
      <div>
        <strong>${escapeHtml(artifact.filename)}</strong>
        <span>${escapeHtml(artifact.skill)} · ${escapeHtml(formatTime(artifact.created_at))} · tags ${escapeHtml(artifact.permission_tags.join(", ") || "-")}</span>
        <p>${escapeHtml(artifact.instruction || "历史记录缺少原始指令，无法重新生成。")}</p>
      </div>
      <div class="document-actions">
        <button class="ghost" data-artifact-action="preview" data-artifact-id="${escapeHtml(artifact.id)}" type="button">预览</button>
        <button class="ghost" data-artifact-action="download" data-artifact-id="${escapeHtml(artifact.id)}" type="button">下载</button>
        <button class="ghost" data-artifact-action="copy" data-artifact-id="${escapeHtml(artifact.id)}" type="button">复制链接</button>
        <button class="ghost" data-artifact-action="regenerate" data-artifact-id="${escapeHtml(artifact.id)}" type="button" ${canRegenerate}>重新生成</button>
        <button class="danger" data-artifact-action="delete" data-artifact-id="${escapeHtml(artifact.id)}" type="button">删除</button>
      </div>
    `;
    els.artifactList.appendChild(item);
  }
}

function renderConversations() {
  els.conversationList.innerHTML = "";

  if (!state.activeKb) {
    els.activeConversationLabel.textContent = "未选择知识库";
    els.conversationList.textContent = "选择知识库后会显示历史对话。";
    renderConversationMessages();
    return;
  }

  const selectedId = activeConversationId(state.activeKb.id);
  const selected = state.conversations.find((conversation) => conversation.id === selectedId);
  els.activeConversationLabel.textContent = selected ? selected.title : "新对话";

  if (!state.conversations.length) {
    els.conversationList.textContent = "当前知识库还没有历史对话，发送一次问题后会自动保存。";
    renderConversationMessages();
    return;
  }

  for (const conversation of state.conversations) {
    const button = document.createElement("button");
    button.className = `conversation-item ${conversation.id === selectedId ? "active" : ""}`;
    button.type = "button";
    button.dataset.conversationId = conversation.id;
    button.innerHTML = `
      <strong>${escapeHtml(conversation.title || "未命名对话")}</strong>
      <span>${escapeHtml(formatTime(conversation.updated_at))}</span>
    `;
    els.conversationList.appendChild(button);
  }

  renderConversationMessages();
}

function renderConversationMessages() {
  els.conversationMessages.innerHTML = "";

  if (!state.activeKb) {
    els.conversationMessages.textContent = "选择知识库后会显示对话消息。";
    return;
  }

  const selectedId = activeConversationId(state.activeKb.id);
  if (!selectedId) {
    els.conversationMessages.textContent = "正在准备新对话。";
    return;
  }

  if (!state.conversationMessages.length) {
    els.conversationMessages.textContent = "这条会话暂无消息。";
    return;
  }

  for (const message of state.conversationMessages) {
    const item = document.createElement("div");
    item.className = `conversation-message ${message.role}`;
    item.innerHTML = `
      <strong>${message.role === "user" ? "用户" : "助手"}</strong>
      <span>${escapeHtml(formatTime(message.created_at))}</span>
      <p>${escapeHtml(message.content)}</p>
    `;
    els.conversationMessages.appendChild(item);
  }
}

function renderOperationEvents() {
  els.operationList.innerHTML = "";

  if (!state.operationEvents.length) {
    els.operationList.textContent = state.activeKb
      ? "当前知识库暂无操作记录。"
      : "选择知识库后会显示操作记录。";
    return;
  }

  for (const event of state.operationEvents) {
    const item = document.createElement("div");
    item.className = "operation-item";
    item.innerHTML = `
      <strong>${escapeHtml(event.event_type)}</strong>
      <span>${escapeHtml(event.message || "无说明")} · ${escapeHtml(formatTime(event.created_at))}</span>
      <small>${escapeHtml([event.knowledge_base_id, event.document_id, event.artifact_id].filter(Boolean).join(" / ") || "-")}</small>
    `;
    els.operationList.appendChild(item);
  }
}

function renderAll() {
  renderKnowledgeBases();
  renderBoundary();
  renderDocuments();
  renderArtifacts();
  renderConversations();
  renderOperationEvents();
  renderTabs();
}

async function loadKnowledgeBases() {
  const requestId = ++state.requests.knowledgeBases;
  const knowledgeBases = await api("/knowledge-bases");
  if (requestId !== state.requests.knowledgeBases) {
    return;
  }
  state.knowledgeBases = knowledgeBases;
  const preferredKbId = state.activeKbId || state.activeKb?.id || "";
  state.activeKb = state.knowledgeBases.find((kb) => kb.id === preferredKbId) || state.knowledgeBases[0] || null;
  if (state.activeKb && state.activeKb.tenant_id !== state.identity.tenantId) {
    state.activeKb = null;
  }
  if (state.activeKb) {
    state.activeKbId = state.activeKb.id;
    persistScopedState("active_kb", state.activeKbId);
  } else if (preferredKbId) {
    state.activeKbId = "";
    persistScopedState("active_kb", "");
  }
  renderAll();
}

async function loadRuntimeConfig() {
  state.runtimeConfig = await api("/runtime-config");
  renderModelStatus();
  renderLoginHint();
}

async function loadDocuments() {
  if (!state.activeKb) {
    state.documents = [];
    renderDocuments();
    return;
  }
  const kbId = state.activeKb.id;
  const requestId = ++state.requests.documents;
  const documents = await api(`/knowledge-bases/${encodeURIComponent(kbId)}/documents`);
  if (requestId !== state.requests.documents || state.activeKb?.id !== kbId) {
    return;
  }
  state.documents = documents;
  renderDocuments();
}

async function loadArtifacts() {
  if (!state.activeKb) {
    state.artifacts = [];
    renderArtifacts();
    return;
  }
  const kbId = state.activeKb.id;
  const requestId = ++state.requests.artifacts;
  const artifacts = await api(`/knowledge-bases/${encodeURIComponent(kbId)}/artifacts`);
  if (requestId !== state.requests.artifacts || state.activeKb?.id !== kbId) {
    return;
  }
  state.artifacts = artifacts;
  renderArtifacts();
}

async function loadConversations() {
  if (!state.activeKb) {
    state.conversations = [];
    state.conversationMessages = [];
    renderConversations();
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

  const selectedId = activeConversationId(kbId);
  const selected = conversations.find((conversation) => conversation.id === selectedId) || conversations[0];
  if (selected) {
    rememberConversation(kbId, selected.id);
    renderConversations();
    await loadConversationMessages(selected.id);
    return;
  }

  forgetConversation(kbId);
  renderConversations();
}

async function loadConversationMessages(conversationId = "") {
  if (!state.activeKb) {
    state.conversationMessages = [];
    renderConversationMessages();
    return;
  }
  const kbId = state.activeKb.id;
  const selectedId = conversationId || activeConversationId(kbId);
  if (!selectedId) {
    state.conversationMessages = [];
    renderConversationMessages();
    return;
  }
  const requestId = ++state.requests.conversationMessages;
  const messages = await api(
    `/knowledge-bases/${encodeURIComponent(kbId)}/conversations/${encodeURIComponent(selectedId)}/messages`
  );
  if (
    requestId !== state.requests.conversationMessages
    || state.activeKb?.id !== kbId
    || activeConversationId(kbId) !== selectedId
  ) {
    return;
  }
  state.conversationMessages = messages;
  renderConversationMessages();
}

async function loadOperationEvents() {
  const kbId = state.activeKb?.id || "";
  const requestId = ++state.requests.operationEvents;
  const path = kbId
    ? `/operation-events?kb_id=${encodeURIComponent(kbId)}&limit=20`
    : "/operation-events?limit=20";
  const events = await api(path);
  if (requestId !== state.requests.operationEvents || (kbId && state.activeKb?.id !== kbId)) {
    return;
  }
  state.operationEvents = events;
  renderOperationEvents();
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

async function handleSubmit(form, handler) {
  const button = form.querySelector("button[type='submit']");
  button.disabled = true;
  try {
    await handler();
  } catch (error) {
    setOperationStatus(error.message, "error");
    showToast(error.message);
  } finally {
    button.disabled = false;
  }
}

async function handleButton(button, handler) {
  button.disabled = true;
  try {
    await handler();
  } catch (error) {
    setOperationStatus(error.message, "error");
    showToast(error.message);
  } finally {
    button.disabled = false;
  }
}

async function previewDocument(docId) {
  const kb = requireActiveKb();
  const document = await api(`/knowledge-bases/${encodeURIComponent(kb.id)}/documents/${encodeURIComponent(docId)}`);
  els.documentPreview.textContent = `# ${document.title}\n\n${document.content}`;
  setOperationStatus(`已加载「${document.title}」解析预览。`);
}

async function executeSkill(skillName, instruction) {
  const kb = requireActiveKb();
  const kbId = kb.id;
  const requestId = ++state.requests.generate;
  setOperationStatus(`正在执行 ${skillName}，生成交付物...`, "busy");
  state.lastGenerateText = instruction;
  const result = await api(`/knowledge-bases/${encodeURIComponent(kbId)}/skills/${encodeURIComponent(skillName)}`, {
    method: "POST",
    body: JSON.stringify({
      instruction,
      top_k: 5,
    }),
  });
  if (requestId !== state.requests.generate || state.activeKb?.id !== kbId) {
    return;
  }
  renderResult(result, {
    answerBox: els.generateAnswerBox,
    trace: els.generateTraceId,
    artifactBox: els.generateArtifactBox,
  });
  await loadArtifacts();
  setOperationStatus("生成完成，下载链接和历史记录已更新。");
  showToast("写文档技能执行完成。");
}

async function previewArtifact(artifact) {
  const kb = requireActiveKb();
  const preview = await api(
    `/knowledge-bases/${encodeURIComponent(kb.id)}/artifacts/${encodeURIComponent(artifact.id)}/preview`
  );
  els.artifactPreview.textContent = `# ${preview.filename}\n\n${preview.content}`;
  setOperationStatus(`已加载「${preview.filename}」生成预览。`);
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
  const confirmed = window.confirm(`确认删除「${artifact.filename}」吗？文件记录和磁盘文件都会删除。`);
  if (!confirmed) {
    return;
  }
  const kb = requireActiveKb();
  await api(`/knowledge-bases/${encodeURIComponent(kb.id)}/artifacts/${encodeURIComponent(artifact.id)}`, {
    method: "DELETE",
  });
  els.artifactPreview.textContent = "生成文件已删除。";
  await loadArtifacts();
  showToast("生成文件已删除。");
}

async function regenerateArtifact(artifact) {
  if (!artifact.instruction) {
    throw new Error("这条历史记录缺少原始指令，无法重新生成。");
  }
  els.skillName.value = artifact.skill;
  els.instruction.value = artifact.instruction;
  state.activeTab = "generate";
  renderTabs();
  await executeSkill(artifact.skill, artifact.instruction);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatTime(value) {
  if (!value) {
    return "-";
  }
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

document.querySelectorAll("[data-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    state.activeTab = button.dataset.tab;
    persistScopedState("active_tab", state.activeTab);
    renderTabs();
  });
});

els.refreshBtn.addEventListener("click", () => {
  loadKnowledgeBases()
    .then(loadDocuments)
    .then(loadArtifacts)
    .then(loadConversations)
    .then(loadOperationEvents)
    .then(() => showToast("知识库列表已刷新。"))
    .catch((error) => showToast(error.message));
});

els.kbSearch.addEventListener("input", renderKnowledgeBases);

els.kbName.addEventListener("input", () => {
  if (els.kbId.dataset.touched === "true" || els.kbId.value.trim()) {
    return;
  }
  els.kbId.value = suggestKnowledgeBaseId(els.kbName.value.trim());
});

els.kbId.addEventListener("input", () => {
  els.kbId.dataset.touched = "true";
});

[
  [els.docSearch, "search"],
  [els.docStatusFilter, "status"],
  [els.docTagFilter, "tag"],
  [els.docSort, "sort"],
].forEach(([control, key]) => {
  control.addEventListener("input", () => {
    state.docFilters[key] = control.value;
    persistScopedState("doc_filters", state.docFilters);
    renderDocuments();
  });
});

els.kbForm.addEventListener("submit", (event) => {
  event.preventDefault();
  handleSubmit(els.kbForm, async () => {
    const kbId = els.kbId.value.trim();
    if (!isValidKnowledgeBaseId(kbId)) {
      els.kbId.focus();
      throw new Error("知识库 ID 只能包含英文、数字、下划线、短横线，长度 2-64；中文请填在名称里。");
    }
    const payload = {
      id: kbId,
      name: els.kbName.value.trim(),
      tenant_id: els.kbTenantId.value.trim() || "default",
      permission_tags: parseTags(els.kbPermissionTags.value),
      allowed_skills: selectedSkills(),
    };
    if (!payload.allowed_skills.length) {
      throw new Error("请至少选择一个允许技能。");
    }
    const kb = await api("/knowledge-bases", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.activeKb = kb;
    els.kbForm.reset();
    delete els.kbId.dataset.touched;
    els.kbTenantId.value = "default";
    await loadKnowledgeBases();
    await loadDocuments();
    await loadArtifacts();
    await loadConversations();
    await loadOperationEvents();
    showToast("知识库已创建，并切换为当前边界。");
  });
});

els.docForm.addEventListener("submit", (event) => {
  event.preventDefault();
  handleSubmit(els.docForm, async () => {
    const kb = requireActiveKb();
    setOperationStatus("正在写入文本并生成向量...", "busy");
    await api(`/knowledge-bases/${encodeURIComponent(kb.id)}/documents`, {
      method: "POST",
      body: JSON.stringify({
        title: els.docTitle.value.trim(),
        content: els.docContent.value.trim(),
        permission_tags: parseTags(els.docPermissionTags.value),
      }),
    });
    els.docForm.reset();
    await loadDocuments();
    await loadOperationEvents();
    setOperationStatus("文本已入库并完成索引。");
    showToast(`文档已写入 ${kb.name}。`);
  });
});

els.uploadForm.addEventListener("submit", (event) => {
  event.preventDefault();
  handleSubmit(els.uploadForm, async () => {
    const kb = requireActiveKb();
    const file = els.uploadFile.files[0];
    if (!file) {
      throw new Error("请选择要上传的文件。");
    }
    setOperationStatus(`正在上传 ${file.name}...`, "busy");

    const formData = new FormData();
    formData.append("file", file);
    formData.append("permission_tags", els.uploadPermissionTags.value.trim());
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

    setOperationStatus("文件已解析并完成向量化。");
    els.uploadForm.reset();
    await loadDocuments();
    await loadOperationEvents();
    showToast(`文件已上传并写入 ${kb.name}。`);
  });
});

els.reloadDocsBtn.addEventListener("click", () => {
  loadDocuments()
    .then(loadOperationEvents)
    .then(() => showToast("文档列表已刷新。"))
    .catch((error) => showToast(error.message));
});

els.reloadArtifactsBtn.addEventListener("click", () => {
  loadArtifacts()
    .then(loadOperationEvents)
    .then(() => showToast("生成历史已刷新。"))
    .catch((error) => showToast(error.message));
});

els.reloadConversationsBtn.addEventListener("click", () => {
  loadConversations()
    .then(() => showToast("历史对话已刷新。"))
    .catch((error) => showToast(error.message));
});

els.reloadOperationsBtn.addEventListener("click", () => {
  loadOperationEvents()
    .then(() => showToast("操作记录已刷新。"))
    .catch((error) => showToast(error.message));
});

els.skillName.addEventListener("change", renderBoundary);

els.loginForm.addEventListener("submit", (event) => {
  event.preventDefault();
  handleButton(els.loginSubmitBtn, async () => {
    await loginFromForm();
  });
});

els.logoutBtn.addEventListener("click", () => {
  handleButton(els.logoutBtn, async () => {
    await logoutToLogin();
  });
});

els.newConversationBtn.addEventListener("click", () => {
  try {
    const kb = requireActiveKb();
    forgetConversation(kb.id);
    state.conversationMessages = [];
    els.answerBox.textContent = "新对话已准备好，输入问题后会自动保存。";
    els.traceId.textContent = "";
    renderConversations();
    els.question.focus();
    showToast("已切换到新对话。");
  } catch (error) {
    showToast(error.message);
  }
});

els.conversationList.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-conversation-id]");
  if (!button) {
    return;
  }
  handleButton(button, async () => {
    const kb = requireActiveKb();
    const conversationId = button.dataset.conversationId;
    rememberConversation(kb.id, conversationId);
    state.conversationMessages = [];
    renderConversations();
    await loadConversationMessages(conversationId);
    setOperationStatus("历史对话已加载，后续提问会接在这条上下文里。");
  });
});

els.documentList.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) {
    return;
  }
  handleButton(button, async () => {
    const kb = requireActiveKb();
    const docId = button.dataset.id;
    if (button.dataset.action === "delete") {
      const doc = state.documents.find((item) => item.id === docId);
      const confirmed = window.confirm(`确认删除「${doc?.title || docId}」吗？相关 chunks 会一起删除。`);
      if (!confirmed) {
        return;
      }
      await api(`/knowledge-bases/${encodeURIComponent(kb.id)}/documents/${encodeURIComponent(docId)}`, {
        method: "DELETE",
      });
      els.documentPreview.textContent = "文档已删除。";
      showToast("文档已删除，相关 chunks 也已清理。");
    }
    if (button.dataset.action === "reindex") {
      setOperationStatus("正在重建文档索引...", "busy");
      await api(`/knowledge-bases/${encodeURIComponent(kb.id)}/documents/${encodeURIComponent(docId)}/reindex`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      setOperationStatus("索引已重建。");
      showToast("索引已重建。");
    }
    if (button.dataset.action === "preview") {
      await previewDocument(docId);
    }
    await loadDocuments();
    await loadOperationEvents();
  });
});

els.artifactList.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-artifact-action]");
  if (!button) {
    return;
  }
  const artifact = state.artifacts.find((item) => item.id === button.dataset.artifactId);
  if (!artifact) {
    showToast("没有找到这个生成文件。");
    return;
  }
  handleButton(button, async () => {
    if (button.dataset.artifactAction === "preview") {
      await previewArtifact(artifact);
    }
    if (button.dataset.artifactAction === "download") {
      await downloadArtifact(artifact);
    }
    if (button.dataset.artifactAction === "copy") {
      await copyArtifactLink(artifact);
    }
    if (button.dataset.artifactAction === "regenerate") {
      await regenerateArtifact(artifact);
    }
    if (button.dataset.artifactAction === "delete") {
      await deleteArtifact(artifact);
    }
    await loadOperationEvents();
  });
});

els.queryForm.addEventListener("submit", (event) => {
  event.preventDefault();
  handleSubmit(els.queryForm, async () => {
    const kb = requireActiveKb();
    const kbId = kb.id;
    const requestId = ++state.requests.query;
    const question = els.question.value.trim();
    state.lastQueryText = question;
    const conversationId = activeConversationId(kbId);
    if (state.queryAbortController) {
      state.queryAbortController.abort();
    }
    const controller = new AbortController();
    state.queryAbortController = controller;
    setOperationStatus("正在当前知识库内流式生成回答...", "busy");
    els.answerBox.textContent = "";
    els.traceId.textContent = "流式输出中...";

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
          els.answerBox.textContent = answer;
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
        els.traceId.textContent = "";
      }
    }

    if (requestId !== state.requests.query || state.activeKb?.id !== kbId) {
      return;
    }
    if (!answer.trim()) {
      els.answerBox.textContent = "没有返回回答。";
    }
    rememberConversation(kbId, response?.headers.get("X-Conversation-Id") || conversationId);
    await loadConversations();
    setOperationStatus("问答完成。");
    showToast("已完成流式回答。");
    await loadOperationEvents();
  });
});

els.skillForm.addEventListener("submit", (event) => {
  event.preventDefault();
  handleSubmit(els.skillForm, async () => {
    const skillName = els.skillName.value;
    await executeSkill(skillName, els.instruction.value.trim());
    await loadOperationEvents();
  });
});

async function bootstrap() {
  await loadRuntimeConfig();
  const session = readSessionProfile();
  if (restoreSessionProfile(session)) {
    renderShell();
    try {
      await loadCurrentUserWorkspace();
      setOperationStatus(`已恢复 ${state.identity.userId} / ${state.identity.tenantId} 的登录会话。`);
      return;
    } catch (error) {
      clearSession();
      showToast(`登录会话已失效：${error.message}`);
    }
  }
  renderShell();
  renderBoundary();
}

bootstrap().catch((error) => showToast(error.message));
