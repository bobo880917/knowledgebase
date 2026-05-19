import sqlite3

import httpx
import json

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from app.schemas import (
    ChatAppend,
    ChatMessageOut,
    CreateJobResponse,
    DocumentDetailOut,
    DocumentOut,
    DocumentTagsPatch,
    EmbeddingHealth,
    OcrHealth,
    ProjectCreate,
    ProjectIndexStats,
    ProjectOut,
    ProjectUpdate,
    ProviderHealth,
    JobListResponse,
    JobOut,
    ReindexJobCreate,
    SearchRequest,
    SearchResponse,
    SourceSummary,
    ReindexResult,
    TagCreate,
    TagOut,
    UploadResult,
)
from app.core.config import get_settings
from app.services import chat as chat_service
from app.services import tags as tags_service
from app.services.embeddings import EmbeddingService
from app.services.indexer import DocumentIndexer
from app.services.jobs import job_service
from app.services.llm_provider import LLMProvider
from app.services.ocr_engine import ocr_health
from app.services.projects import ProjectService
from app.services.retrieval import RetrievalService
from app.storage.database import get_db

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


@router.get("/ocr/health", response_model=OcrHealth)
def ocr_health_endpoint() -> OcrHealth:
    data = ocr_health()
    return OcrHealth(**data)


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


@router.post("/jobs/import", response_model=CreateJobResponse)
async def create_import_job(
    file: UploadFile = File(...),
    project_id: int = Form(default=1, ge=1),
    import_dedup_mode: str | None = Form(default=None),
) -> CreateJobResponse:
    _ensure_project(project_id)
    res = await job_service.create_import_job(
        project_id, file, import_dedup_mode=import_dedup_mode
    )
    return CreateJobResponse(job_id=res.job_id)


@router.post("/jobs/import-url", response_model=CreateJobResponse)
async def create_import_url_job(
    project_id: int = Form(default=1, ge=1),
    url: str = Form(...),
    import_dedup_mode: str | None = Form(default=None),
) -> CreateJobResponse:
    _ensure_project(project_id)
    try:
        res = await job_service.create_import_url_job(
            project_id, url, import_dedup_mode=import_dedup_mode
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=400, detail=f"抓取网页失败：{exc}") from exc
    return CreateJobResponse(job_id=res.job_id)


@router.post("/jobs/reindex", response_model=CreateJobResponse)
def create_reindex_job(req: ReindexJobCreate) -> CreateJobResponse:
    _ensure_project(req.project_id)
    res = job_service.create_reindex_job(req.project_id)
    return CreateJobResponse(job_id=res.job_id)


def _job_out_from_row(row) -> JobOut:
    data = dict(row)
    target_name = None
    try:
        params = json.loads(data.get("params_json") or "{}")
        if data.get("type") == "import_document":
            target_name = params.get("original_filename")
    except Exception:
        target_name = None
    data["target_name"] = target_name
    return JobOut(**data)


@router.get("/jobs", response_model=JobListResponse)
def list_jobs(
    project_id: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> JobListResponse:
    _ensure_project(project_id)
    rows, total = job_service.list_jobs(project_id, limit, offset)
    return JobListResponse(
        items=[_job_out_from_row(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int) -> JobOut:
    row = job_service.get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _job_out_from_row(row)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int) -> dict[str, bool]:
    res = job_service.request_cancel(job_id)
    if res is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"cancelled": bool(res)}


@router.post("/jobs/{job_id}/retry", response_model=CreateJobResponse)
def retry_job(job_id: int) -> CreateJobResponse:
    try:
        new_job_id = job_service.retry_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if new_job_id is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return CreateJobResponse(job_id=new_job_id)


@router.get("/projects/{project_id}/tags", response_model=list[TagOut])
def list_project_tags(project_id: int) -> list[TagOut]:
    _ensure_project(project_id)
    with get_db() as conn:
        rows = tags_service.list_tags(conn, project_id)
    return [TagOut(**dict(row)) for row in rows]


@router.post("/projects/{project_id}/tags", response_model=TagOut)
def create_project_tag(project_id: int, body: TagCreate) -> TagOut:
    _ensure_project(project_id)
    try:
        with get_db() as conn:
            row = tags_service.create_tag(conn, project_id, body.name)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail="标签名已存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TagOut(**dict(row))


@router.delete("/projects/{project_id}/tags/{tag_id}")
def delete_project_tag(project_id: int, tag_id: int) -> dict[str, bool]:
    _ensure_project(project_id)
    with get_db() as conn:
        ok = tags_service.delete_tag(conn, tag_id, project_id)
    if not ok:
        raise HTTPException(status_code=404, detail="标签不存在")
    return {"deleted": True}


@router.get("/projects/{project_id}/chat", response_model=list[ChatMessageOut])
def list_project_chat(project_id: int, limit: int = Query(default=40, ge=1, le=200)) -> list[ChatMessageOut]:
    _ensure_project(project_id)
    with get_db() as conn:
        rows = chat_service.list_messages(conn, project_id, limit)
    return [ChatMessageOut(**dict(row)) for row in rows]


@router.post("/projects/{project_id}/chat", response_model=ChatMessageOut)
def append_project_chat(project_id: int, body: ChatAppend) -> ChatMessageOut:
    _ensure_project(project_id)
    try:
        with get_db() as conn:
            chat_service.append_message(conn, project_id, body.role, body.content)
            row = conn.execute(
                """
                SELECT id, project_id, role, content, created_at
                FROM chat_messages
                WHERE project_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (project_id,),
            ).fetchone()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    assert row
    return ChatMessageOut(**dict(row))


@router.delete("/projects/{project_id}/chat")
def clear_project_chat(project_id: int) -> dict[str, bool]:
    _ensure_project(project_id)
    with get_db() as conn:
        chat_service.clear_messages(conn, project_id)
    return {"cleared": True}


@router.patch("/documents/{document_id}/tags", response_model=DocumentOut)
def patch_document_tags(
    document_id: int,
    project_id: int = Query(..., ge=1),
    body: DocumentTagsPatch | None = None,
) -> DocumentOut:
    _ensure_project(project_id)
    payload = body or DocumentTagsPatch()
    try:
        with get_db() as conn:
            tags_service.set_document_tags(conn, document_id, project_id, payload.tag_ids)
            row = conn.execute(
                """
                SELECT id, project_id, filename, file_type, summary, created_at, ocr_meta
                FROM documents
                WHERE id = ? AND project_id = ?
                """,
                (document_id, project_id),
            ).fetchone()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="文档不存在")
    with get_db() as conn:
        names = indexer._document_tag_names(conn, document_id)
    return DocumentOut(**{**dict(row), "tags": names})


@router.get("/documents/{document_id}/detail", response_model=DocumentDetailOut)
def get_document_detail(document_id: int, project_id: int = Query(..., ge=1)) -> DocumentDetailOut:
    _ensure_project(project_id)
    detail = indexer.get_document_detail(document_id, project_id)
    if not detail:
        raise HTTPException(status_code=404, detail="文档不存在")
    return detail


@router.get("/documents")
def list_documents(project_id: int = Query(default=1, ge=1)):
    _ensure_project(project_id)
    return indexer.list_documents(project_id)


@router.post("/documents", response_model=UploadResult)
async def upload_document(
    file: UploadFile = File(...),
    project_id: int = Form(default=1, ge=1),
    import_dedup_mode: str | None = Form(default=None),
) -> UploadResult:
    _ensure_project(project_id)
    try:
        return await indexer.ingest_upload(file, project_id, import_dedup_mode=import_dedup_mode)
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
    with get_db() as conn:
        doc_filter = tags_service.document_ids_for_filters(
            conn,
            request.project_id,
            tag_ids=request.tag_ids,
            file_types=request.file_types,
            created_after=request.created_after,
            created_before=request.created_before,
        )
    hits = retrieval.search(
        request.query,
        request.project_id,
        request.top_k,
        doc_filter,
    )
    sources = _build_sources(hits)
    answer = None
    rag_skipped_reason = None
    settings = get_settings()
    if request.mode == "rag":
        conv = ""
        if request.rag_use_chat_history:
            with get_db() as conn:
                rows = chat_service.list_messages(conn, request.project_id, 40)
                conv = chat_service.tail_for_prompt(rows)
        with get_db() as conn:
            chat_service.append_message(conn, request.project_id, "user", request.query)
        min_score = float(settings.rag_min_evidence_score)
        if not hits:
            answer = "未在知识库中找到与问题相关的可靠片段，无法作答。请确认当前项目已导入相关文档或换个问法。"
            rag_skipped_reason = "no_hits"
        elif hits[0].rank_score < min_score:
            answer = (
                "检索到的内容与问题关联度不足（低于系统可信度阈值），无法基于知识库给出可靠结论。"
                "建议补充关键词、缩小问题范围或导入更匹配的文档。"
            )
            rag_skipped_reason = "low_evidence_score"
        else:
            try:
                answer = await llm_provider.answer(request.query, hits, conv or None)
            except Exception as exc:
                answer = f"已完成检索，但调用 LLM Provider 失败：{exc}"
        with get_db() as conn:
            chat_service.append_message(conn, request.project_id, "assistant", answer or "")
    return SearchResponse(
        query=request.query,
        mode=request.mode,
        hits=hits,
        sources=sources,
        answer=answer,
        rag_skipped_reason=rag_skipped_reason,
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
