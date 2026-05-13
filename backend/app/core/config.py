from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ImportDedupMode = Literal["ignore", "overwrite", "keep"]


class Settings(BaseSettings):
    app_name: str = "Local Knowledge Base"
    database_path: Path = Path("./data/knowledge_base.db")
    upload_dir: Path = Path("./data/uploads")

    embedding_provider: str = "hash"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_dimension: int = 384

    llm_provider: str = "openai_compatible"
    llm_base_url: str = "http://127.0.0.1:8642/v1"
    llm_api_key: str = "change-me-local-dev"
    llm_model: str = "hermes-agent"
    llm_timeout_seconds: int = 120

    # 同项目同文件内容指纹：ignore 跳过重复；overwrite 删除旧记录后重新导入；keep 每次新增一条（可多版本并存）
    import_dedup_mode: ImportDedupMode = "ignore"

    # 检索融合：向量 + BM25(FTS5) + 简单词面重合（三者之和应为 1）
    retrieval_vector_weight: float = 0.52
    retrieval_bm25_weight: float = 0.38
    retrieval_keyword_weight: float = 0.10

    # RAG：最佳命中 fused 分低于此阈值则不调 LLM，直接返回「未找到足够依据」
    rag_min_evidence_score: float = 0.14

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    def ensure_dirs(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
