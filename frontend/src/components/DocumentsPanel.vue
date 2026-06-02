<script setup>
import { ref } from "vue";

defineProps({
  state: { type: Object, required: true },
  drafts: { type: Object, required: true },
  documents: { type: Array, required: true },
  statusClass: { type: Function, required: true },
  formatTime: { type: Function, required: true },
});

const emit = defineEmits(["add-document", "upload-document", "preview-document", "reindex-document", "delete-document", "reload-docs"]);
const fileInput = ref(null);

function submitUpload() {
  const file = fileInput.value?.files?.[0] || null;
  emit("upload-document", file);
  if (fileInput.value) {
    fileInput.value.value = "";
  }
}

function deleteDocument(doc) {
  const confirmed = window.confirm(`确认删除「${doc.title}」吗？相关 chunks 会一起删除。`);
  if (confirmed) {
    emit("delete-document", doc);
  }
}
</script>

<template>
  <section class="tab-panel">
    <div class="document-grid">
      <article class="panel card">
        <div class="section-head">
          <div>
            <p class="eyebrow">Ingest</p>
            <h2>录入文本</h2>
          </div>
        </div>
        <form class="stack" @submit.prevent="emit('add-document')">
          <label>
            文档标题
            <input v-model="drafts.document.title" required placeholder="员工手册：报销制度" />
          </label>
          <label>
            文档内容
            <textarea v-model="drafts.document.content" required rows="7" placeholder="粘贴知识库文档内容..." />
          </label>
          <label>
            文档权限标签
            <input v-model="drafts.document.permissionTags" placeholder="hr, finance，可留空" />
          </label>
          <button type="submit" :disabled="!state.activeKb">写入并索引</button>
        </form>
      </article>

      <article class="panel card">
        <div class="section-head">
          <div>
            <p class="eyebrow">Upload</p>
            <h2>上传文件</h2>
          </div>
        </div>
        <form class="stack" @submit.prevent="submitUpload">
          <label>
            支持文件
            <input ref="fileInput" type="file" accept=".md,.markdown,.docx,.pptx" />
            <small class="field-hint">后端会做大小限制、Office zip 安全检查和解析超时控制。</small>
          </label>
          <label>
            文档权限标签
            <input v-model="drafts.upload.permissionTags" placeholder="hr, finance，可留空" />
          </label>
          <button type="submit" :disabled="!state.activeKb">上传并索引</button>
        </form>
      </article>
    </div>

    <div class="document-grid" style="margin-top: 1rem">
      <article class="panel card">
        <div class="section-head">
          <div>
            <p class="eyebrow">Documents</p>
            <h2>文档列表</h2>
          </div>
          <button class="ghost small" type="button" :disabled="!state.activeKb" @click="emit('reload-docs')">
            刷新
          </button>
        </div>

        <div class="document-toolbar">
          <label>
            搜索
            <input v-model="drafts.docFilters.search" placeholder="标题、ID、标签或错误信息" />
          </label>
          <label>
            状态
            <select v-model="drafts.docFilters.status">
              <option value="">全部</option>
              <option value="indexing">indexing</option>
              <option value="indexed">indexed</option>
              <option value="failed">failed</option>
            </select>
          </label>
          <label>
            权限标签
            <input v-model="drafts.docFilters.tag" placeholder="hr" />
          </label>
          <label>
            排序
            <select v-model="drafts.docFilters.sort">
              <option value="newest">创建时间：新到旧</option>
              <option value="oldest">创建时间：旧到新</option>
              <option value="status">状态</option>
              <option value="title">标题</option>
            </select>
          </label>
        </div>

        <div class="document-list">
          <p v-if="!state.activeKb" class="empty">选择知识库后会显示文档。</p>
          <p v-else-if="!state.documents.length" class="empty">当前知识库还没有文档。</p>
          <p v-else-if="!documents.length" class="empty">没有匹配筛选条件的文档。</p>
          <div v-for="doc in documents" :key="doc.id" class="document-item">
            <div>
              <strong>{{ doc.title }}</strong>
              <span>
                {{ doc.id }} ·
                <b :class="['status-badge', statusClass(doc.status)]">{{ doc.status }}</b>
                · chunks {{ doc.chunk_count }} · tags {{ doc.permission_tags?.join(", ") || "-" }} ·
                {{ formatTime(doc.created_at) }}
              </span>
              <p v-if="doc.error" class="error-text">失败原因：{{ doc.error }}</p>
            </div>
            <div class="document-actions">
              <button class="ghost small" type="button" @click="emit('preview-document', doc.id)">预览</button>
              <button class="ghost small" type="button" @click="emit('reindex-document', doc)">
                {{ doc.status === "failed" ? "重试索引" : "重建索引" }}
              </button>
              <button class="danger small" type="button" @click="deleteDocument(doc)">删除</button>
            </div>
          </div>
        </div>
      </article>

      <article class="panel card">
        <div class="section-head">
          <div>
            <p class="eyebrow">Preview</p>
            <h2>原文预览</h2>
          </div>
          <span class="pill neutral">{{ state.documentPreview.title || "未选择文档" }}</span>
        </div>
        <pre class="preview-box">{{ state.documentPreview.content }}</pre>
      </article>
    </div>
  </section>
</template>
