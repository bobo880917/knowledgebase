import sqlite3

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from app.schemas import (
    EmbeddingHealth,
    ProjectCreate,
    ProjectIndexStats,
    ProjectOut,
    ProjectUpdate,
    ProviderHealth,
    SearchRequest,
    SearchResponse,
    SourceSummary,
    ReindexResult,
    UploadResult,
)
from app.services.embeddings import EmbeddingService
from app.services.indexer import DocumentIndexer
from app.services.llm_provider import LLMProvider
from app.services.projects import ProjectService
from app.services.retrieval import RetrievalService

router = APIRouter(prefix="/api")
indexer = DocumentIndexer()
retrieval = RetrievalService()
llm_provider = LLMProvider()
embedding_service = EmbeddingService()
projects = ProjectService()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/provider/health", response_model=ProviderHealth)
async def provider_health() -> ProviderHealth:
    return await llm_provider.health()


@router.get("/embedding/health", response_model=EmbeddingHealth)
def embedding_health() -> EmbeddingHealth:
    return embedding_service.health()


@router.get("/projects", response_model=list[ProjectOut])
def list_projects() -> list[ProjectOut]:
    return projects.list_projects()


@router.post("/projects", response_model=ProjectOut)
def create_project(project: ProjectCreate) -> ProjectOut:
    try:
        return projects.create_project(project)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail="项目名称已存在") from exc


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, project: ProjectUpdate) -> ProjectOut:
    try:
        updated = projects.update_project(project_id, project)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail="项目名称已存在") from exc
    if not updated:
        raise HTTPException(status_code=404, detail="项目不存在")
    return updated


@router.delete("/projects/{project_id}")
def delete_project(project_id: int) -> dict[str, bool]:
    try:
        deleted = projects.delete_project(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"deleted": True}


@router.post("/projects/{project_id}/reindex", response_model=ReindexResult)
def reindex_project(project_id: int) -> ReindexResult:
    _ensure_project(project_id)
    try:
        return indexer.reindex_project(project_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/projects/{project_id}/index-stats", response_model=ProjectIndexStats)
def project_index_stats(project_id: int) -> ProjectIndexStats:
    _ensure_project(project_id)
    return indexer.get_project_index_stats(project_id)


@router.get("/documents")
def list_documents(project_id: int = Query(default=1, ge=1)):
    _ensure_project(project_id)
    return indexer.list_documents(project_id)


@router.post("/documents", response_model=UploadResult)
async def upload_document(
    file: UploadFile = File(...),
    project_id: int = Form(default=1, ge=1),
) -> UploadResult:
    _ensure_project(project_id)
    try:
        return await indexer.ingest_upload(file, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/documents/{document_id}")
def delete_document(
    document_id: int,
    project_id: int = Query(default=1, ge=1),
) -> dict[str, bool]:
    _ensure_project(project_id)
    deleted = indexer.delete_document(document_id, project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"deleted": True}


@router.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest) -> SearchResponse:
    _ensure_project(request.project_id)
    hits = retrieval.search(request.query, request.project_id, request.top_k)
    sources = _build_sources(hits)
    answer = None
    if request.mode == "rag" and hits:
        try:
            answer = await llm_provider.answer(request.query, hits)
        except Exception as exc:
            answer = f"已完成检索，但调用 LLM Provider 失败：{exc}"
    return SearchResponse(
        query=request.query,
        mode=request.mode,
        hits=hits,
        sources=sources,
        answer=answer,
    )


def _ensure_project(project_id: int) -> None:
    if not projects.exists(project_id):
        raise HTTPException(status_code=404, detail="项目不存在")


def _build_sources(hits) -> list[SourceSummary]:
    seen: set[tuple[int, str | None, str]] = set()
    sources: list[SourceSummary] = []
    for hit in hits:
        key = (hit.document_id, hit.section_title, hit.match_type)
        if key in seen:
            continue
        seen.add(key)
        sources.append(
            SourceSummary(
                project_id=hit.project_id,
                project_name=hit.project_name,
                document_id=hit.document_id,
                document_name=hit.document_name,
                section_title=hit.section_title,
                match_type=hit.match_type,
                score=hit.rank_score,
            )
        )
    return sources
