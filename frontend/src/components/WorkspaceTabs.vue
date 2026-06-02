<script setup>
defineProps({
  activeTab: { type: String, required: true },
});

const emit = defineEmits(["select"]);

const tabs = [
  { key: "ask", label: "问答" },
  { key: "documents", label: "文档" },
  { key: "generate", label: "生成" },
  { key: "settings", label: "设置" },
];
</script>

<template>
  <nav class="tabs" aria-label="工作区导航" role="tablist">
    <button
      v-for="tab in tabs"
      :id="`tab-${tab.key}`"
      :key="tab.key"
      :class="['tab', { active: activeTab === tab.key }]"
      type="button"
      role="tab"
      :aria-selected="activeTab === tab.key ? 'true' : 'false'"
      @click="emit('select', tab.key)"
    >
      {{ tab.label }}
    </button>
  </nav>
</template>
