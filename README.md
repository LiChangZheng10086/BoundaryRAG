# RAG Demo

这是一个 Python RAG MVP，重点验证“多知识库边界感”：

- 使用 `knowledge_base_id` 隔离文档、检索、引用和技能。
- 每个知识库只能执行自己声明过的技能。
- 检索结果会做边界校验，防止 A 知识库的问题拿到 B 的内容。
- 默认使用本地哈希向量和本地假 LLM，方便无 API Key 先跑通。
- 配置环境变量后可切换到千问向量和 DeepSeek。

## 快速启动

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn rag_demo.app:app --reload
```

启动后打开：

```text
http://127.0.0.1:8000/
```

前端工作台分为：

```text
问答：只在当前知识库内检索并回答
文档：粘贴录入、文件上传、文档管理、解析文本预览
生成：基于当前知识库生成 Markdown / Word / PPT，并查看生成历史
设置：查看当前演示身份和知识库边界
```

## 接入真实模型

复制 `.env.example` 为 `.env`，填入自己的密钥：

```bash
EMBEDDING_PROVIDER=dashscope
DASHSCOPE_API_KEY=你的 DashScope Key
DASHSCOPE_EMBEDDING_MODEL=tongyi-embedding-vision-flash-2026-03-06

LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的 DeepSeek Key
DEEPSEEK_MODEL=deepseek-v4-pro
DEEPSEEK_BASE_URL=https://api.deepseek.com

RAG_MAX_DOCUMENT_CHARS=200000
RAG_UPLOAD_PARSE_TIMEOUT_SECONDS=10

# 生产鉴权建议开启 JWT
RAG_AUTH_MODE=jwt
RAG_JWT_SECRET=换成足够长的随机密钥
```

`.env` 已加入 `.gitignore`，不要把真实密钥提交到仓库。

## 示例

默认 demo 模式会从请求头读取当前访问上下文：

```bash
AUTH_HEADERS=(-H "X-User-Id: demo-user" -H "X-Tenant-Id: default" -H "X-Permission-Tags: hr,finance")
```

如果设置 `RAG_AUTH_MODE=jwt`，所有接口必须改用 Bearer Token：

```bash
python - <<'PY'
from rag_demo.auth import sign_access_token
from rag_demo.config import get_settings
from rag_demo.models import AccessContext

print(sign_access_token(
    AccessContext(user_id="demo-user", tenant_id="default", permission_tags=["hr", "finance"]),
    get_settings(),
))
PY

AUTH_HEADERS=(-H "Authorization: Bearer <上一步生成的 token>")
```

创建 A 知识库：

```bash
curl -X POST http://127.0.0.1:8000/knowledge-bases \
  "${AUTH_HEADERS[@]}" \
  -H 'Content-Type: application/json' \
  -d '{"id":"kb_a","name":"A 知识库","tenant_id":"default","allowed_skills":["answer_question","write_document","write_markdown","write_word","write_ppt"]}'
```

写入 A 文档：

```bash
curl -X POST http://127.0.0.1:8000/knowledge-bases/kb_a/documents \
  "${AUTH_HEADERS[@]}" \
  -H 'Content-Type: application/json' \
  -d '{"title":"A制度","content":"A知识库规定：报销需要在30天内提交发票。","permission_tags":[]}'
```

上传 Markdown / Word / PPT 文件：

```bash
curl -X POST http://127.0.0.1:8000/knowledge-bases/kb_a/documents/upload \
  "${AUTH_HEADERS[@]}" \
  -F "file=@/path/to/file.md" \
  -F "permission_tags=hr,finance"
```

当前支持：

```text
.md / .markdown
.docx
.pptx
```

查看 A 文档：

```bash
curl "${AUTH_HEADERS[@]}" http://127.0.0.1:8000/knowledge-bases/kb_a/documents
```

重建文档索引：

```bash
curl -X POST http://127.0.0.1:8000/knowledge-bases/kb_a/documents/{document_id}/reindex \
  "${AUTH_HEADERS[@]}"
```

删除文档：

```bash
curl -X DELETE http://127.0.0.1:8000/knowledge-bases/kb_a/documents/{document_id} \
  "${AUTH_HEADERS[@]}"
```

查询 A：

```bash
curl -X POST http://127.0.0.1:8000/knowledge-bases/kb_a/query \
  "${AUTH_HEADERS[@]}" \
  -H 'Content-Type: application/json' \
  -d '{"question":"报销需要多久内提交？","top_k":3}'
```

让 A 按自己的资料写文档：

```bash
curl -X POST http://127.0.0.1:8000/knowledge-bases/kb_a/skills/write_document \
  "${AUTH_HEADERS[@]}" \
  -H 'Content-Type: application/json' \
  -d '{"instruction":"写一份报销提醒","top_k":3}'
```

## 边界设计

核心原则：所有入口都必须携带 `knowledge_base_id`，所有数据访问都必须被该 ID 过滤。

```text
API 请求
  -> 加载指定知识库配置
  -> 检查技能是否被该知识库允许
  -> 仅检索该知识库下的 chunks
  -> LLM Prompt 注入边界规则
  -> 引用结果二次校验 knowledge_base_id
  -> 返回答案和同库来源
```

## 运行测试

```bash
pytest
```
