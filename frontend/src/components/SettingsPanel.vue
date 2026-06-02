<script setup>
import { computed } from "vue";

const props = defineProps({
  state: { type: Object, required: true },
  tokenExpiryText: { type: String, default: "" },
  formatTime: { type: Function, required: true },
});

const emit = defineEmits(["logout", "reload-operations"]);

const runtimeItems = computed(() => {
  const config = props.state.runtimeConfig;
  if (!config) {
    return [];
  }
  return [
    ["Metadata", `${config.metadata_store} · ${config.metadata_store_uri}`],
    ["Vector", `${config.vector_store} · ${config.vector_store_collection}`],
    ["Session", `${config.session_store} · TTL ${config.session_ttl_seconds}s`],
    ["Cache", `${config.cache_store} · ${config.cache_ready ? "ready" : "unavailable/disabled"}`],
    ["LLM", `${config.llm_provider} · ${config.llm_model} · ${config.llm_ready ? "ready" : "missing key"}`],
    [
      "Embedding",
      `${config.embedding_provider} · ${config.embedding_model} · ${config.embedding_ready ? "ready" : "missing key"}`,
    ],
  ];
});
</script>

<template>
  <section class="tab-panel">
    <div class="settings-grid">
      <article class="panel card">
        <div class="section-head">
          <div>
            <p class="eyebrow">Session</p>
            <h2>登录状态卡片</h2>
          </div>
          <button class="danger small" type="button" @click="emit('logout')">退出登录</button>
        </div>
        <div class="runtime-grid" style="margin-top: 1rem">
          <div class="stat">
            <span>用户</span>
            <strong>{{ state.identity.userId }}</strong>
          </div>
          <div class="stat">
            <span>租户</span>
            <strong>{{ state.identity.tenantId }}</strong>
          </div>
          <div class="stat">
            <span>角色</span>
            <strong>{{ state.identity.role === "admin" ? "管理员" : "普通用户" }}</strong>
          </div>
          <div class="stat">
            <span>权限</span>
            <strong>{{ state.identity.permissionTags?.join(", ") || "-" }}</strong>
          </div>
          <div class="stat">
            <span>认证</span>
            <strong>账号密码 / Redis Token</strong>
          </div>
        </div>
        <p class="empty">{{ tokenExpiryText }}</p>

        <div class="boundary-mini">
          <span>当前知识库</span>
          <strong>{{ state.activeKb?.name || "未选择" }}</strong>
          <p v-if="state.activeKb">
            {{ state.activeKb.id }} · tenant {{ state.activeKb.tenant_id }} · skills
            {{ state.activeKb.allowed_skills?.join(", ") }}
          </p>
          <p v-else>选择知识库后会显示租户、权限标签和技能边界。</p>
        </div>
      </article>

      <article class="panel card">
        <div class="section-head">
          <div>
            <p class="eyebrow">Runtime</p>
            <h2>运行配置</h2>
          </div>
        </div>
        <div v-if="runtimeItems.length" class="runtime-grid" style="margin-top: 1rem">
          <div v-for="[label, value] in runtimeItems" :key="label" class="runtime-item">
            <span>{{ label }}</span>
            <strong>{{ value }}</strong>
          </div>
        </div>
        <p v-else class="empty">模型配置加载中...</p>
      </article>
    </div>

    <article class="panel card" style="margin-top: 1rem">
      <div class="section-head">
        <div>
          <p class="eyebrow">Operations</p>
          <h2>操作记录</h2>
        </div>
        <button class="ghost small" type="button" @click="emit('reload-operations')">刷新记录</button>
      </div>
      <div class="operation-list" style="margin-top: 1rem">
        <p v-if="!state.operationEvents.length" class="empty">
          {{ state.activeKb ? "当前知识库暂无操作记录。" : "选择知识库后会显示操作记录。" }}
        </p>
        <div v-for="event in state.operationEvents" :key="event.id" class="operation-item">
          <strong>{{ event.event_type }}</strong>
          <span>{{ event.message || "无说明" }} · {{ formatTime(event.created_at) }}</span>
          <small>{{ [event.knowledge_base_id, event.document_id, event.artifact_id].filter(Boolean).join(" / ") || "-" }}</small>
        </div>
      </div>
    </article>
  </section>
</template>
