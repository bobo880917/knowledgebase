# Local Knowledge Base（本地知识库）

一个本地知识库 MVP：支持上传文档（`md/txt/docx/pdf`），本地解析与索引检索，并可接入 **OpenAI-compatible** LLM 服务做 RAG 问答。

## 功能特性

- **文档管理**：上传/列表/删除（按项目维度组织）
- **本地索引与检索**：基于分层结构（标题/段落等）进行检索，返回命中片段与来源摘要
- **RAG 问答**：检索命中后，调用 OpenAI-compatible Provider 生成答案
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

```bash
cd backend
python -m venv .venv
source .venv/bin/activate

# 基础依赖
pip install -e .

# 如果要使用 sentence-transformers embedding（推荐语义检索）
pip install -e ".[embedding]"

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

### Embedding（语义检索）

开发验证也可以用简单 hash；正式语义检索建议开启 `sentence_transformers`：

```env
EMBEDDING_PROVIDER=sentence_transformers
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
EMBEDDING_DIMENSION=512
```

> 如果你没有安装 embedding 依赖，请执行：`pip install -e ".[embedding]"`。

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
- **项目**
  - `GET /api/projects`
  - `POST /api/projects`
  - `PATCH /api/projects/{project_id}`
  - `DELETE /api/projects/{project_id}`
  - `POST /api/projects/{project_id}/reindex`
  - `GET /api/projects/{project_id}/index-stats`
- **文档**
  - `GET /api/documents?project_id=1`
  - `POST /api/documents`（multipart/form-data：`file` + `project_id`）
  - `DELETE /api/documents/{document_id}?project_id=1`
- **检索 / 问答**
  - `POST /api/search`（`mode=search|rag`）

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
