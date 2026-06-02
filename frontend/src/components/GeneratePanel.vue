<script setup>
defineProps({
  state: { type: Object, required: true },
  drafts: { type: Object, required: true },
  skillOptions: { type: Array, required: true },
  canGenerate: { type: Boolean, default: false },
  formatTime: { type: Function, required: true },
});

const emit = defineEmits([
  "run-skill",
  "preview-artifact",
  "download-artifact",
  "copy-artifact",
  "regenerate-artifact",
  "delete-artifact",
  "reload-artifacts",
]);

function deleteArtifact(artifact) {
  const confirmed = window.confirm(`确认删除「${artifact.filename}」吗？文件记录和磁盘文件都会删除。`);
  if (confirmed) {
    emit("delete-artifact", artifact);
  }
}
</script>

<template>
  <section class="tab-panel">
    <div class="generate-grid">
      <article class="panel card">
        <div class="section-head">
          <div>
            <p class="eyebrow">Generate</p>
            <h2>写文档 / 生成</h2>
          </div>
          <span class="pill">{{ drafts.generate.skillName }}</span>
        </div>
        <form class="stack" @submit.prevent="emit('run-skill')">
          <label>
            技能
            <select v-model="drafts.generate.skillName">
              <option v-for="skill in skillOptions" :key="skill.value" :value="skill.value">
                {{ skill.label }} / {{ skill.value }}
              </option>
            </select>
          </label>
          <label>
            生成要求
            <textarea
              v-model="drafts.generate.instruction"
              required
              rows="6"
              placeholder="比如：基于当前知识库，生成一份报销制度培训 PPT"
            />
          </label>
          <button type="submit" :disabled="!state.activeKb || !canGenerate || state.generate.running">
            {{ state.generate.running ? "正在生成..." : "执行技能" }}
          </button>
          <small v-if="state.activeKb && !canGenerate" class="field-hint">当前知识库未授权该技能。</small>
        </form>
      </article>

      <article class="panel result-panel">
        <div class="section-head">
          <div>
            <p class="eyebrow">Result</p>
            <h2>生成结果</h2>
          </div>
          <span class="trace">{{ state.generate.traceId }}</span>
        </div>
        <pre>{{ state.generate.answer }}</pre>
        <div v-if="state.generate.artifact" class="artifact-box">
          <a href="#" class="artifact-link" @click.prevent="emit('download-artifact', state.generate.artifact)">
            下载生成文件：{{ state.generate.artifact.filename }}
          </a>
          <button class="ghost small" type="button" @click="emit('copy-artifact', state.generate.artifact)">
            复制链接
          </button>
        </div>
      </article>
    </div>

    <div class="generate-grid" style="margin-top: 1rem">
      <article class="panel card">
        <div class="section-head">
          <div>
            <p class="eyebrow">Artifacts</p>
            <h2>生成历史</h2>
          </div>
          <button class="ghost small" type="button" :disabled="!state.activeKb" @click="emit('reload-artifacts')">
            刷新
          </button>
        </div>

        <div class="artifact-list">
          <p v-if="!state.activeKb" class="empty">选择知识库后会显示生成文件。</p>
          <p v-else-if="!state.artifacts.length" class="empty">当前知识库还没有生成文件。</p>
          <div v-for="artifact in state.artifacts" :key="artifact.id" class="artifact-item">
            <div>
              <strong>{{ artifact.filename }}</strong>
              <span>
                {{ artifact.skill }} · {{ formatTime(artifact.created_at) }} · tags
                {{ artifact.permission_tags?.join(", ") || "-" }}
              </span>
              <p class="empty">{{ artifact.instruction || "历史记录缺少原始指令，无法重新生成。" }}</p>
            </div>
            <div class="artifact-actions">
              <button class="ghost small" type="button" @click="emit('preview-artifact', artifact)">预览</button>
              <button class="ghost small" type="button" @click="emit('download-artifact', artifact)">下载</button>
              <button class="ghost small" type="button" @click="emit('copy-artifact', artifact)">复制链接</button>
              <button
                class="ghost small"
                type="button"
                :disabled="!artifact.instruction"
                @click="emit('regenerate-artifact', artifact)"
              >
                重新生成
              </button>
              <button class="danger small" type="button" @click="deleteArtifact(artifact)">删除</button>
            </div>
          </div>
        </div>
      </article>

      <article class="panel card">
        <div class="section-head">
          <div>
            <p class="eyebrow">Preview</p>
            <h2>生成预览</h2>
          </div>
          <span class="pill neutral">{{ state.artifactPreview.title || "未选择生成物" }}</span>
        </div>
        <pre class="preview-box">{{ state.artifactPreview.content }}</pre>
      </article>
    </div>
  </section>
</template>
