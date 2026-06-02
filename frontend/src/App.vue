<script setup>
import { computed as vueComputed, onMounted } from "vue";
import { useWorkspace } from "./composables/useWorkspace";
import AskPanel from "./components/AskPanel.vue";
import DocumentsPanel from "./components/DocumentsPanel.vue";
import GeneratePanel from "./components/GeneratePanel.vue";
import LoginScreen from "./components/LoginScreen.vue";
import SettingsPanel from "./components/SettingsPanel.vue";
import SidebarPanel from "./components/SidebarPanel.vue";
import WorkspaceTabs from "./components/WorkspaceTabs.vue";

const workspace = useWorkspace();
const { state, drafts, skillOptions, computed: derived, actions, utils } = workspace;
const {
  activeConversationId,
  activeConversationLabel,
  canAsk,
  canGenerate,
  filteredDocuments,
  recentKnowledgeBases,
  tokenExpiryText,
  visibleKnowledgeBases,
} = derived;

const runtimeStatus = vueComputed(() => utils.runtimeModelStatus(state.runtimeConfig));

onMounted(() => {
  actions.bootstrap();
});

async function safe(work) {
  try {
    await work();
  } catch (error) {
    actions.reportError(error);
  }
}
</script>

<template>
  <div class="app-root">
    <section v-if="!state.ready" class="loading-screen">
      <article class="panel loading-card">
        <p class="eyebrow">BoundaryRAG</p>
        <h1>正在连接本地工作台</h1>
        <p class="empty">读取账号体系、模型配置和会话状态中...</p>
      </article>
    </section>

    <LoginScreen
      v-else-if="!state.isAuthenticated"
      :state="state"
      :drafts="drafts"
      @login="safe(actions.loginFromDraft)"
    />

    <main v-else class="shell">
      <section class="hero panel">
        <div>
          <p class="eyebrow">Enterprise Knowledge Boundary</p>
          <h1>有边界感的 RAG 知识库</h1>
          <p class="hero-copy">
            选择一个知识库后，问答、写文档、生成内容都会被限制在当前知识库内。
            A 的资料不进 B 的上下文，B 的技能也不会借 A 的手。
          </p>
        </div>
        <div class="hero-actions">
          <div class="status-card">
            <span class="status-dot"></span>
            <span>{{ state.activeKb ? `${state.activeKb.name} · ${state.activeKb.id}` : "尚未选择知识库" }}</span>
          </div>
          <div class="identity-card">
            <span>用户：<strong>{{ state.identity.userId }}</strong></span>
            <span>角色：<strong>{{ state.identity.role === "admin" ? "管理员" : "普通用户" }}</strong></span>
            <span>租户：<strong>{{ state.identity.tenantId }}</strong></span>
            <span>权限：<strong>{{ state.identity.permissionTags?.join(", ") || "-" }}</strong></span>
          </div>
        </div>
      </section>

      <section class="grid">
        <SidebarPanel
          :state="state"
          :drafts="drafts"
          :skill-options="skillOptions"
          :visible-knowledge-bases="visibleKnowledgeBases"
          :recent-knowledge-bases="recentKnowledgeBases"
          @refresh="safe(actions.refreshWorkspace)"
          @select-kb="(kb) => safe(() => actions.switchKnowledgeBase(kb))"
          @delete-kb="(kb) => safe(() => actions.deleteKnowledgeBase(kb))"
          @create-kb="safe(actions.createKnowledgeBase)"
          @suggest-kb-id="actions.maybeSuggestKnowledgeBaseId"
        />

        <section class="workspace">
          <div class="panel boundary">
            <p class="eyebrow">Current Boundary</p>
            <div class="boundary-row">
              <strong>{{ state.activeKb ? `当前只使用：${state.activeKb.name}` : "选择知识库后开始" }}</strong>
              <span class="pill neutral">
                skills: {{ state.activeKb?.allowed_skills?.join(", ") || "-" }}
              </span>
            </div>
            <div :class="['model-status', runtimeStatus.className]">{{ runtimeStatus.text }}</div>
            <div class="identity-row" aria-label="当前身份">
              <span>认证：<strong>账号密码 / Redis Token</strong></span>
              <span>角色：<strong>{{ state.identity.role === "admin" ? "管理员" : "普通用户" }}</strong></span>
              <span>过期：<strong>{{ tokenExpiryText }}</strong></span>
            </div>
          </div>

          <WorkspaceTabs :active-tab="state.activeTab" @select="actions.setActiveTab" />

          <div :class="['operation-status', state.operationStatus.tone]" role="status" aria-live="polite">
            <span class="status-dot"></span>
            <span>{{ state.operationStatus.message }}</span>
          </div>

          <AskPanel
            v-show="state.activeTab === 'ask'"
            :state="state"
            :drafts="drafts"
            :active-conversation-id="activeConversationId"
            :active-conversation-label="activeConversationLabel"
            :can-ask="canAsk"
            :format-time="utils.formatTime"
            @submit-question="safe(actions.submitQuestion)"
            @new-conversation="safe(actions.newConversation)"
            @select-conversation="(conversation) => safe(() => actions.selectConversation(conversation))"
            @reload-conversations="safe(actions.loadConversations)"
          />

          <DocumentsPanel
            v-show="state.activeTab === 'documents'"
            :state="state"
            :drafts="drafts"
            :documents="filteredDocuments"
            :status-class="utils.statusClass"
            :format-time="utils.formatTime"
            @add-document="safe(actions.addTextDocument)"
            @upload-document="(file) => safe(() => actions.uploadDocument(file))"
            @preview-document="(docId) => safe(() => actions.previewDocument(docId))"
            @reindex-document="(doc) => safe(() => actions.reindexDocument(doc))"
            @delete-document="(doc) => safe(() => actions.deleteDocument(doc))"
            @reload-docs="safe(() => Promise.all([actions.loadDocuments(), actions.loadOperationEvents()]))"
          />

          <GeneratePanel
            v-show="state.activeTab === 'generate'"
            :state="state"
            :drafts="drafts"
            :skill-options="skillOptions"
            :can-generate="canGenerate"
            :format-time="utils.formatTime"
            @run-skill="safe(actions.runSkill)"
            @preview-artifact="(artifact) => safe(() => actions.previewArtifact(artifact))"
            @download-artifact="(artifact) => safe(() => actions.downloadArtifact(artifact))"
            @copy-artifact="(artifact) => safe(() => actions.copyArtifactLink(artifact))"
            @regenerate-artifact="(artifact) => safe(() => actions.regenerateArtifact(artifact))"
            @delete-artifact="(artifact) => safe(() => actions.deleteArtifact(artifact))"
            @reload-artifacts="safe(() => Promise.all([actions.loadArtifacts(), actions.loadOperationEvents()]))"
          />

          <SettingsPanel
            v-show="state.activeTab === 'settings'"
            :state="state"
            :token-expiry-text="tokenExpiryText"
            :format-time="utils.formatTime"
            @logout="safe(actions.logoutToLogin)"
            @reload-operations="safe(actions.loadOperationEvents)"
          />
        </section>
      </section>
    </main>

    <div :class="['toast', { show: state.toast.visible }]">{{ state.toast.message }}</div>
  </div>
</template>
