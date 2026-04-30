# Local Knowledge Base

本项目是一个本地知识库系统 MVP：Mac 负责开发、文档解析、索引与检索，Windows 11 上的 Hermes Agent 或其他 OpenAI-compatible 服务负责 RAG 回答生成。

## 架构

- `backend/`：FastAPI 后端，负责上传、预处理、索引、检索、RAG 编排。
- `frontend/`：Vue 3 + TypeScript 前端，负责文档上传、检索和问答界面。
- `backend/data/`：本地 SQLite、上传文件和索引数据目录。

## 第一阶段范围

- 文档格式：`md`、`txt`、`docx`、`pdf`
- 检索模式：标题/摘要/段落/正文分层检索
- 问答模式：通过 OpenAI-compatible Provider 调用 Hermes Agent 或其他模型 API

## 后端启动

建议使用 Python 3.11+。

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

## 前端启动

```bash
cd frontend
npm install
npm run dev
```

## Hermes Agent 配置示例

Windows 11 建议在 WSL2 中运行 Hermes Agent，并开启 API Server：

```env
API_SERVER_ENABLED=true
API_SERVER_HOST=0.0.0.0
API_SERVER_PORT=8642
API_SERVER_KEY=your-local-secret
```

后端 `.env`：

```env
LLM_BASE_URL=http://<windows-ip>:8642/v1
LLM_API_KEY=your-local-secret
LLM_MODEL=hermes-agent
```
