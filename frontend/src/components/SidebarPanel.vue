<script setup>
const props = defineProps({
  state: { type: Object, required: true },
  drafts: { type: Object, required: true },
  skillOptions: { type: Array, required: true },
  visibleKnowledgeBases: { type: Array, required: true },
  recentKnowledgeBases: { type: Array, required: true },
});

const emit = defineEmits(["refresh", "select-kb", "delete-kb", "create-kb", "suggest-kb-id"]);

function deleteKnowledgeBase(kb) {
  const confirmed = window.confirm(`确认删除「${kb.name}」吗？该知识库下的文档、chunks、会话和生成记录都会删除。`);
  if (confirmed) {
    emit("delete-kb", kb);
  }
}
</script>

<template>
  <aside class="panel sidebar">
    <div class="section-head">
      <div>
        <p class="eyebrow">Knowledge Bases</p>
        <h2>知识库</h2>
      </div>
      <button class="ghost small" type="button" @click="emit('refresh')">刷新</button>
    </div>

    <div class="boundary-mini">
      <span>当前边界</span>
      <strong>{{ state.activeKb?.name || "未选择" }}</strong>
      <p v-if="state.activeKb">
        {{ state.activeKb.id }} · tenant {{ state.activeKb.tenant_id }} ·
        {{ state.activeKb.permission_tags?.join(", ") || "无额外标签" }}
      </p>
      <p v-else>选择知识库后，问答、文档和生成都会锁定到同一边界。</p>
    </div>

    <label class="search-box">
      搜索知识库
      <input v-model="drafts.sidebar.search" placeholder="输入名称、ID、租户或技能" />
    </label>

    <div class="sidebar-block">
      <div class="section-head">
        <div>
          <p class="eyebrow">Recent</p>
          <h3>最近使用</h3>
        </div>
      </div>
      <div v-if="recentKnowledgeBases.length" class="recent-kbs">
        <button
          v-for="kb in recentKnowledgeBases"
          :key="kb.id"
          class="recent-chip"
          type="button"
          @click="emit('select-kb', kb)"
        >
          {{ kb.name }}
        </button>
      </div>
      <p v-else class="empty">还没有最近使用的知识库。</p>
    </div>

    <details class="create-kb">
      <summary>创建新知识库</summary>
      <form class="stack" @submit.prevent="emit('create-kb')">
        <label>
          知识库 ID
          <input
            v-model="drafts.knowledgeBase.id"
            required
            pattern="[a-zA-Z0-9_-]{2,64}"
            placeholder="kb_hr"
            title="只能包含英文、数字、下划线、短横线，长度 2-64"
            @input="drafts.knowledgeBase.idTouched = true"
          />
          <small class="field-hint">中文请填在“名称”，ID 只保留英文、数字、下划线、短横线。</small>
        </label>
        <label>
          名称
          <input
            v-model="drafts.knowledgeBase.name"
            required
            placeholder="人事制度库"
            @input="emit('suggest-kb-id')"
          />
        </label>
        <label>
          租户 ID
          <input v-model="drafts.knowledgeBase.tenantId" placeholder="default" />
        </label>
        <label>
          知识库权限标签
          <input v-model="drafts.knowledgeBase.permissionTags" placeholder="hr, finance，可留空" />
        </label>
        <div class="field">
          <span>允许技能</span>
          <div class="skill-checks" role="group" aria-label="允许技能">
            <label v-for="skill in skillOptions" :key="skill.value">
              <input v-model="drafts.knowledgeBase.skillFlags[skill.value]" type="checkbox" />
              {{ skill.label }}
            </label>
          </div>
          <small class="field-hint">可多选。未勾选的技能在该知识库内不可执行。</small>
        </div>
        <button type="submit">创建知识库</button>
      </form>
    </details>

    <div class="kb-list" aria-live="polite">
      <p v-if="!state.knowledgeBases.length" class="empty">还没有知识库，先创建一个。</p>
      <p v-else-if="!visibleKnowledgeBases.length" class="empty">没有匹配的知识库。</p>
      <div
        v-for="kb in visibleKnowledgeBases"
        :key="kb.id"
        :class="['kb-item', { active: state.activeKb?.id === kb.id }]"
      >
        <button class="kb-select" type="button" @click="emit('select-kb', kb)">
          <strong>{{ kb.name }}</strong>
          <span>
            {{ kb.id }} · tenant {{ kb.tenant_id }}
            <template v-if="state.recentKbIds.includes(kb.id)"> · 最近使用</template>
            · {{ kb.allowed_skills?.join(", ") }}
          </span>
        </button>
        <button class="ghost small kb-delete" type="button" @click="deleteKnowledgeBase(kb)">删除</button>
      </div>
    </div>
  </aside>
</template>
