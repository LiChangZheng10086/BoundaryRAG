<script setup>
defineProps({
  state: { type: Object, required: true },
  drafts: { type: Object, required: true },
  activeConversationId: { type: String, default: "" },
  activeConversationLabel: { type: String, default: "新对话" },
  canAsk: { type: Boolean, default: false },
  formatTime: { type: Function, required: true },
});

const emit = defineEmits(["submit-question", "new-conversation", "select-conversation", "reload-conversations"]);
</script>

<template>
  <section class="tab-panel">
    <div class="ask-layout">
      <div class="ask-stack">
        <article class="panel card">
          <div class="section-head">
            <div>
              <p class="eyebrow">Ask</p>
              <h2>知识库问答</h2>
            </div>
            <span class="pill">answer_question</span>
          </div>
          <form class="stack" @submit.prevent="emit('submit-question')">
            <label>
              问题
              <textarea v-model="drafts.query.question" required rows="5" placeholder="比如：报销需要多久内提交？" />
            </label>
            <button type="submit" :disabled="!state.activeKb || !canAsk || state.ask.streaming">
              {{ state.ask.streaming ? "正在流式输出..." : "只在当前知识库中回答" }}
            </button>
            <small v-if="state.activeKb && !canAsk" class="field-hint">当前知识库没有授权问答技能。</small>
          </form>
        </article>

        <article class="panel result-panel">
          <div class="section-head">
            <div>
              <p class="eyebrow">Answer</p>
              <h2>流式回答</h2>
            </div>
            <span class="trace">{{ state.ask.traceId }}</span>
          </div>
          <pre>{{ state.ask.answer }}</pre>
        </article>
      </div>

      <article class="panel card conversation-panel">
        <div class="section-head">
          <div>
            <p class="eyebrow">History</p>
            <h2>历史对话</h2>
          </div>
          <button class="ghost small" type="button" :disabled="!state.activeKb" @click="emit('new-conversation')">
            新对话
          </button>
        </div>
        <div class="conversation-toolbar">
          <span class="pill">{{ activeConversationLabel }}</span>
          <button
            class="ghost small"
            type="button"
            :disabled="!state.activeKb"
            @click="emit('reload-conversations')"
          >
            刷新历史
          </button>
        </div>
        <div class="conversation-list">
          <p v-if="!state.activeKb" class="empty">选择知识库后会显示历史对话。</p>
          <p v-else-if="!state.conversations.length" class="empty">
            当前知识库还没有历史对话，发送一次问题后会自动保存。
          </p>
          <button
            v-for="conversation in state.conversations"
            :key="conversation.id"
            :class="['conversation-item', { active: conversation.id === activeConversationId }]"
            type="button"
            @click="emit('select-conversation', conversation)"
          >
            <strong>{{ conversation.title || "未命名对话" }}</strong>
            <span>{{ formatTime(conversation.updated_at) }}</span>
          </button>
        </div>
        <div class="conversation-messages">
          <p v-if="!state.activeKb" class="empty">选择知识库后会显示对话消息。</p>
          <p v-else-if="!activeConversationId" class="empty">正在准备新对话。</p>
          <p v-else-if="!state.conversationMessages.length" class="empty">这条会话暂无消息。</p>
          <div
            v-for="message in state.conversationMessages"
            :key="message.id"
            :class="['conversation-message', message.role]"
          >
            <strong>{{ message.role === "user" ? "用户" : "助手" }}</strong>
            <span>{{ formatTime(message.created_at) }}</span>
            <p>{{ message.content }}</p>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>
