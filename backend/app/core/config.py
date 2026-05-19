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

    # OCR（可选）：扫描 PDF / 图片需 OCR_ENABLED=true，并 uv sync --extra ocr + 本机 Tesseract
    ocr_enabled: bool = False
    ocr_lang: str = "chi_sim+eng"
    ocr_tesseract_cmd: str = ""
    ocr_pdf_min_text_chars: int = 80
    ocr_pdf_max_pages: int = 30
    # 渲染页图分辨率；中文小字标准类 PDF 建议 300
    ocr_pdf_dpi: int = 300
    # 为 True 时忽略 pypdf 文字层，始终对 PDF 做渲染 + OCR（解决「有文字层但实为乱码」的国标/扫描混排）
    ocr_pdf_force_visual: bool = False
    # 大于 0 时：若文字层已够长但 CJK 占比低于该值，则改走 OCR（0 表示关闭此启发式）
    ocr_pdf_min_cjk_ratio: float = 0.0
    # 传给 Tesseract 的额外参数，例如 --psm 6（单块正文）；留空则使用 Tesseract 默认
    ocr_tesseract_config: str = ""
    # 识别前灰度 + 自动对比度，常能改善扫描件/浅字
    ocr_preprocess_autocontrast: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    def ensure_dirs(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
