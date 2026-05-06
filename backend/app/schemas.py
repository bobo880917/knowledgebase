from typing import Literal

from pydantic import BaseModel, Field


class CreateJobResponse(BaseModel):
    job_id: int


class JobOut(BaseModel):
    id: int
    project_id: int
    type: str
    status: str
    progress_current: int | None = None
    progress_total: int | None = None
    message: str
    target_name: str | None = None
    result_json: str
    error: str
    retry_count: int
    cancel_requested: int
    created_at: str
    updated_at: str


class JobListResponse(BaseModel):
    items: list[JobOut]
    total: int
    limit: int
    offset: int


class ReindexJobCreate(BaseModel):
    project_id: int = Field(default=1, ge=1)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)


class ProjectUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)


class ProjectOut(BaseModel):
    id: int
    name: str
    description: str
    created_at: str


class DocumentOut(BaseModel):
    id: int
    project_id: int
    filename: str
    file_type: str
    summary: str
    created_at: str


class UploadResult(BaseModel):
    document: DocumentOut
    section_count: int
    paragraph_count: int
    chunk_count: int


class EmbeddingHealth(BaseModel):
    provider: str
    model: str
    dimension: int
    semantic_enabled: bool
    ok: bool
    message: str


class ReindexResult(BaseModel):
    project_id: int
    section_count: int
    paragraph_count: int
    chunk_count: int
    embedding_count: int


class ProjectIndexStats(BaseModel):
    project_id: int
    document_count: int
    section_count: int
    paragraph_count: int
    chunk_count: int
    embedding_count: int
    indexed: bool


class SearchRequest(BaseModel):
    project_id: int = Field(default=1, ge=1)
    query: str = Field(min_length=1)
    mode: Literal["search", "rag"] = "search"
    top_k: int = Field(default=8, ge=1, le=30)


class SearchHit(BaseModel):
    project_id: int
    project_name: str
    document_id: int
    document_name: str
    section_title: str | None
    text: str
    score: float
    rank_score: float
    vector_score: float
    keyword_score: float
    match_type: str
    source_id: int


class SourceSummary(BaseModel):
    project_id: int
    project_name: str
    document_id: int
    document_name: str
    section_title: str | None
    match_type: str
    score: float


class SearchResponse(BaseModel):
    query: str
    mode: Literal["search", "rag"]
    hits: list[SearchHit]
    sources: list[SourceSummary] = []
    answer: str | None = None


class ProviderHealth(BaseModel):
    configured: bool
    ok: bool
    message: str
