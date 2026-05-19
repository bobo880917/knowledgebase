# Local Knowledge Base（本地知识库）

一个本地知识库 MVP：支持上传文档（`md/txt/docx/pdf/html/xlsx/pptx` 及常见图片）或抓取网页 HTML，本地解析与索引检索（向量 + SQLite FTS5 BM25 融合），并可接入 **OpenAI-compatible** LLM 服务做带引用约束的 RAG 问答。扫描 PDF 与图片在启用 OCR 后由 Tesseract 识别为文本再入库。

后续优化清单见 [`ROADMAP.md`](ROADMAP.md)。

## 功能特性

- **文档管理**：上传/列表/删除（按项目）；支持 URL 导入网页正文；可选 OCR 导入扫描 PDF 与图片。
- **多轮对话（按项目）**：RAG 自动记录用户/助手消息，检索时可勾选携带近期对话摘要；切换项目后对话隔离。
- **文档标签与检索过滤**：项目内标签管理、文档打标；检索支持按标签（AND）、文件类型、创建日期区间过滤。
- **文档详情**：章节树与段落正文；从命中结果一键打开并高亮对应章节/段落。
- **本地索引与检索**：分层结构；向量相似度与 BM25 全文检索加权融合；命中展示段落/切片位置标签
- **RAG 问答**：证据不足或无命中时拒答（不调 LLM）；有证据时要求回答带 `[n]` 引用并与检索上下文对齐
- **Embedding 可选**：支持 `sentence-transformers`（默认模型示例为 `BAAI/bge-small-zh-v1.5`）

## 目录结构

- `backend/`：FastAPI 后端（上传、预处理、索引、检索、RAG 编排）
- `frontend/`：Vue 3 + Vite + TypeScript 前端（上传、检索、问答 UI）
- `backend/data/`：本地数据目录（SQLite、上传文件、索引数据等）

## 环境要求

- **Python**：3.11+
- **Node.js**：建议 18+（用于前端）
- （可选）本地或局域网内可访问的 **OpenAI-compatible** LLM 服务（例如 Hermes Agent）

> 提示：如果你本机 Python 版本较低（如 3.7/3.8），请先升级到 3.11+（例如使用 `pyenv` / `conda`），否则后端依赖无法正常安装。

## 快速开始（本地开发）

### 1）启动后端（FastAPI）

在 **`backend/`** 目录下执行（模块路径为 `app.main`）。

**推荐（使用 [uv](https://docs.astral.sh/uv/)）：**

```bash
cd backend
uv sync --extra embedding
# 可选：扫描 PDF / 图片 OCR 需 `uv sync --extra ocr` 与本机 Tesseract。
# 若暂不安装语义模型（体积较大），可先用 `uv sync`，并将 `.env` 中 `EMBEDDING_PROVIDER` 设为 `hash`。

cp .env.example .env
uv run uvicorn app.main:app --reload --port 8000
```

**或使用 venv + pip：**

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -e .
# pip install -e ".[embedding]"

cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

后端启动后：
- 健康检查：`GET /api/health`
- CORS 默认允许：`http://localhost:5173`

### 2）启动前端（Vue 3 + Vite）

```bash
cd frontend
npm install
npm run dev
```

默认访问：`http://localhost:5173`

## 配置说明（后端 `.env`）

后端配置文件位于 `backend/.env`，可以从 `backend/.env.example` 拷贝并修改。

### 数据与上传目录

```env
DATABASE_PATH=./data/knowledge_base.db
UPLOAD_DIR=./data/uploads
```

### 导入去重（可选）

同项目、同文件字节指纹下的行为，默认 `ignore`（跳过重复）。也可在「文档管理」上传时按次选择。

```env
# ignore | overwrite | keep
IMPORT_DEDUP_MODE=ignore
```

### 全文检索（BM25）

升级后若数据库中仍是旧版本数据，请在对应项目执行一次 **重建索引**，以便为既有切片/段落生成 SQLite FTS5 全文索引（否则 BM25 分数长期为 0，主要依赖向量与词面分）。

### Embedding（语义检索）

开发验证也可以用简单 hash；正式语义检索建议开启 `sentence_transformers`：

```env
EMBEDDING_PROVIDER=sentence_transformers
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
EMBEDDING_DIMENSION=512
```

> 如果你没有安装 embedding 依赖，请执行：`pip install -e ".[embedding]"`。

### OCR（扫描 PDF / 图片）

1. 本机安装 [Tesseract](https://github.com/tesseract-ocr/tesseract) 及所需语言包（例如中文简体 `chi_sim`）。
2. 安装 Python 可选依赖：`uv sync --extra ocr` 或 `pip install -e ".[ocr]"`。
3. 在 `.env` 中启用并按需调整：

```env
OCR_ENABLED=true
OCR_LANG=chi_sim+eng
# 可选：非默认路径时指定 tesseract 可执行文件
# OCR_TESSERACT_CMD=/opt/homebrew/bin/tesseract
# 正文少于该字符数则对 PDF 走渲染+OCR（可调大以减少误判）
OCR_PDF_MIN_TEXT_CHARS=80
OCR_PDF_MAX_PAGES=30
OCR_PDF_DPI=300
```

识别结果会写入 `documents.ocr_meta`（JSON，便于回溯），并在 `UPLOAD_DIR/ocr_cache/` 下按内容哈希缓存。健康检查：`GET /api/ocr/health`。

#### 中文 PDF / 国标类「乱码」排查

1. **先确认是不是文字层假阳性**：部分电子版用 pypdf 能抽出「很长一段」但实为乱码，系统会误判为「已有正文」而不走 OCR。可在 `.env` 设置 **`OCR_PDF_FORCE_VISUAL=true`**（须 **`OCR_ENABLED=true`**），删除旧文档后重新导入，强制按页渲染再识别。
2. **语言包**：`tesseract --list-langs` 中需包含 **`chi_sim`**（简体）。macOS 常见为 `brew install tesseract-lang`。
3. **分辨率**：将 **`OCR_PDF_DPI`** 提到 **300** 或 **400**（更慢但更清晰）。
4. **启发式**：若不想全局强制视觉 OCR，可设 **`OCR_PDF_MIN_CJK_RATIO=0.06`** 等：文字层够长但汉字占比过低时自动改走 OCR（纯英文长文请勿设过高，或临时把 `OCR_LANG` 改为 `eng`）。
5. **清缓存**：改过 DPI/语言/Tesseract 参数后，删除 `UPLOAD_DIR/ocr_cache/` 下对应缓存或整目录，再重新导入。

### LLM Provider（OpenAI-compatible）

```env
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=http://127.0.0.1:8642/v1
LLM_API_KEY=change-me-local-dev
LLM_MODEL=hermes-agent
LLM_TIMEOUT_SECONDS=120
```

#### Hermes Agent（示例）

Windows 11 建议在 WSL2 中运行 Hermes Agent，并开启 API Server（示例）：

```env
API_SERVER_ENABLED=true
API_SERVER_HOST=0.0.0.0
API_SERVER_PORT=8642
API_SERVER_KEY=your-local-secret
```

然后把后端 `.env` 指向该服务：

```env
LLM_BASE_URL=http://<windows-ip>:8642/v1
LLM_API_KEY=your-local-secret
LLM_MODEL=hermes-agent
```

## 常用接口（后端）

所有接口带统一前缀：`/api`

- **健康检查**
  - `GET /api/health`
  - `GET /api/provider/health`
  - `GET /api/embedding/health`
  - `GET /api/ocr/health`
- **项目**
  - `GET /api/projects`
  - `POST /api/projects`
  - `PATCH /api/projects/{project_id}`
  - `DELETE /api/projects/{project_id}`
  - `POST /api/projects/{project_id}/reindex`
  - `GET /api/projects/{project_id}/index-stats`
  - `GET /api/projects/{project_id}/tags` · `POST /api/projects/{project_id}/tags` · `DELETE /api/projects/{project_id}/tags/{tag_id}`
  - `GET /api/projects/{project_id}/chat` · `POST /api/projects/{project_id}/chat` · `DELETE /api/projects/{project_id}/chat`
- **文档**
  - `GET /api/documents?project_id=1`
  - `POST /api/documents`（multipart/form-data：`file` + `project_id`）
  - `DELETE /api/documents/{document_id}?project_id=1`
  - `GET /api/documents/{document_id}/detail?project_id=1`（章节树 + 段落）
  - `PATCH /api/documents/{document_id}/tags?project_id=1`（JSON：`{ "tag_ids": [1,2] }`）
- **检索 / 问答**
  - `POST /api/search`（`mode=search|rag`；可选 `tag_ids`、`file_types`、`created_after`、`created_before`、`rag_use_chat_history`）

## 常见问题

### 1）为什么 `embedding/health` 不正常？

通常是没有安装可选依赖或模型下载失败。请确认已安装：

```bash
pip install -e ".[embedding]"
```

### 2）前端请求后端跨域？

后端默认允许 `http://localhost:5173` 与 `http://127.0.0.1:5173`。如果你改了端口或域名，需要同步调整后端 CORS 配置（见 `backend/app/main.py`）。

## License

如需开源 License，可在此补充（例如 MIT / Apache-2.0）。
