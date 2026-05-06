import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import sqlite3
from fastapi import UploadFile

from app.core.config import get_settings
from app.storage.database import get_db
from app.services.indexer import CancelledError, DocumentIndexer


JobType = Literal["import_document", "reindex_project"]
JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


@dataclass(frozen=True)
class CreateJobResult:
    job_id: int


class JobService:
    def __init__(self) -> None:
        self._indexer = DocumentIndexer()
        self._executor = ThreadPoolExecutor(max_workers=2)
        self._start_lock = threading.Lock()

    async def create_import_job(self, project_id: int, upload_file: UploadFile) -> CreateJobResult:
        job_id = self._create_job_row(
            project_id=project_id,
            job_type="import_document",
            params={"original_filename": upload_file.filename or "upload"},
        )

        file_path = self._job_upload_path(job_id, upload_file.filename or "upload")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        content = await upload_file.read()
        file_path.write_bytes(content)

        self._update_job(
            job_id,
            params={"file_path": str(file_path), "original_filename": upload_file.filename or "upload"},
            message="已接收文件，等待执行…",
        )
        self._submit(job_id)
        return CreateJobResult(job_id=job_id)

    def create_reindex_job(self, project_id: int) -> CreateJobResult:
        job_id = self._create_job_row(
            project_id=project_id,
            job_type="reindex_project",
            params={},
        )
        self._submit(job_id)
        return CreateJobResult(job_id=job_id)

    def resume_pending_jobs(self) -> int:
        with get_db() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = 'queued',
                    message = '服务重启，重新排队…',
                    updated_at = CURRENT_TIMESTAMP
                WHERE status = 'running'
                  AND cancel_requested = 0
                """
            )
            rows = conn.execute(
                """
                SELECT id
                FROM jobs
                WHERE status = 'queued'
                  AND cancel_requested = 0
                ORDER BY id ASC
                """,
            ).fetchall()
            job_ids = [int(r["id"]) for r in rows]

        for jid in job_ids:
            self._submit(jid)
        return len(job_ids)

    def request_cancel(self, job_id: int) -> bool | None:
        with get_db() as conn:
            row = conn.execute(
                "SELECT status FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if not row:
                return None
            status = row["status"]
            if status in ("succeeded", "failed", "cancelled"):
                return False
            conn.execute(
                "UPDATE jobs SET cancel_requested = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (job_id,),
            )
        return True

    def retry_job(self, job_id: int) -> int | None:
        with get_db() as conn:
            row = conn.execute(
                "SELECT project_id, type, status, params_json, retry_count FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if not row:
                return None
            if row["status"] != "failed":
                raise ValueError("仅 failed 任务允许重试")
            params = _safe_json_loads(row["params_json"], default={})
            new_job_id = self._create_job_row(
                project_id=int(row["project_id"]),
                job_type=row["type"],
                params=params,
                retry_count=int(row["retry_count"]) + 1,
            )
        self._submit(new_job_id)
        return new_job_id

    def list_jobs(self, project_id: int, limit: int = 20, offset: int = 0) -> tuple[list[sqlite3.Row], int]:
        with get_db() as conn:
            total_row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM jobs
                WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()
            rows = conn.execute(
                """
                SELECT *
                FROM jobs
                WHERE project_id = ?
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (project_id, limit, offset),
            ).fetchall()
        return rows, int(total_row["count"])

    def get_job(self, job_id: int) -> sqlite3.Row | None:
        with get_db() as conn:
            return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()

    def _submit(self, job_id: int) -> None:
        self._executor.submit(self._run_job, job_id)

    def _run_job(self, job_id: int) -> None:
        with self._start_lock:
            claimed = self._claim_job(job_id)
        if not claimed:
            return

        try:
            row = self.get_job(job_id)
            if not row:
                return

            if int(row["cancel_requested"] or 0) == 1:
                self._update_job(job_id, status="cancelled", message="已取消")
                return

            job_type: str = row["type"]
            project_id = int(row["project_id"])
            params = _safe_json_loads(row["params_json"], default={})

            if job_type == "import_document":
                self._run_import(job_id, project_id, params)
            elif job_type == "reindex_project":
                self._run_reindex(job_id, project_id)
            else:
                raise RuntimeError(f"未知 job type：{job_type}")
        except Exception as exc:
            self._update_job(job_id, status="failed", error=str(exc), message="执行失败")

    def _run_import(self, job_id: int, project_id: int, params: dict[str, Any]) -> None:
        file_path = params.get("file_path")
        original_filename = params.get("original_filename") or "upload"
        if not file_path:
            raise RuntimeError("缺少 file_path，无法执行导入任务")

        if self._is_cancel_requested(job_id):
            self._update_job(job_id, status="cancelled", message="已取消")
            return

        self._update_job(job_id, message="开始导入：读取/解析/生成 embeddings…", progress_current=0, progress_total=None)
        path = Path(file_path)
        if not path.exists():
            raise RuntimeError("上传文件不存在，可能已被清理")

        with path.open("rb") as f:
            upload = UploadFile(filename=original_filename, file=f)
            try:
                result = asyncio.run(
                    self._indexer.ingest_upload(
                        upload,
                        project_id,
                        job_id=job_id,
                        should_cancel=lambda: self._is_cancel_requested(job_id),
                    )
                )
            except CancelledError:
                self._update_job(job_id, status="cancelled", message="已取消", progress_current=0, progress_total=0)
                return

        self._update_job(
            job_id,
            status="succeeded",
            progress_current=1,
            progress_total=1,
            message="导入完成",
            result=result.model_dump_json(ensure_ascii=False),
        )

    def _run_reindex(self, job_id: int, project_id: int) -> None:
        if self._is_cancel_requested(job_id):
            self._update_job(job_id, status="cancelled", message="已取消")
            return

        self._update_job(job_id, message="开始重建索引…", progress_current=0, progress_total=None)
        try:
            result = self._indexer.reindex_project(
                project_id,
                job_id=job_id,
                should_cancel=lambda: self._is_cancel_requested(job_id),
            )
        except CancelledError:
            self._update_job(job_id, status="cancelled", message="已取消", progress_current=0, progress_total=0)
            return
        self._update_job(
            job_id,
            status="succeeded",
            progress_current=1,
            progress_total=1,
            message="重建完成",
            result=result.model_dump_json(ensure_ascii=False),
        )

    def _claim_job(self, job_id: int) -> bool:
        with get_db() as conn:
            res = conn.execute(
                """
                UPDATE jobs
                SET status = 'running',
                    message = '已开始执行…',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND status = 'queued'
                """,
                (job_id,),
            )
            return res.rowcount == 1

    def _is_cancel_requested(self, job_id: int) -> bool:
        with get_db() as conn:
            row = conn.execute(
                "SELECT cancel_requested FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            return bool(row and int(row["cancel_requested"] or 0) == 1)

    def _create_job_row(
        self,
        project_id: int,
        job_type: JobType,
        params: dict[str, Any],
        retry_count: int = 0,
    ) -> int:
        with get_db() as conn:
            cur = conn.execute(
                """
                INSERT INTO jobs(project_id, type, status, progress_current, progress_total, message, params_json, retry_count, cancel_requested)
                VALUES (?, ?, 'queued', NULL, NULL, '', ?, ?, 0)
                """,
                (project_id, job_type, json.dumps(params, ensure_ascii=False), retry_count),
            )
            return int(cur.lastrowid)

    def _update_job(
        self,
        job_id: int,
        *,
        status: JobStatus | None = None,
        progress_current: int | None = None,
        progress_total: int | None = None,
        message: str | None = None,
        params: dict[str, Any] | None = None,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        sets: list[str] = ["updated_at = CURRENT_TIMESTAMP"]
        values: list[Any] = []
        if status is not None:
            sets.append("status = ?")
            values.append(status)
        if progress_current is not None:
            sets.append("progress_current = ?")
            values.append(progress_current)
        if progress_total is not None:
            sets.append("progress_total = ?")
            values.append(progress_total)
        if message is not None:
            sets.append("message = ?")
            values.append(message)
        if params is not None:
            sets.append("params_json = ?")
            values.append(json.dumps(params, ensure_ascii=False))
        if result is not None:
            sets.append("result_json = ?")
            values.append(result)
        if error is not None:
            sets.append("error = ?")
            values.append(error)

        with get_db() as conn:
            conn.execute(
                f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?",
                (*values, job_id),
            )

    def _job_upload_path(self, job_id: int, filename: str) -> Path:
        safe_name = filename.replace("/", "_").replace("\\", "_")
        upload_dir = get_settings().upload_dir
        return upload_dir / "jobs" / f"{job_id}__{safe_name}"


def _safe_json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


job_service = JobService()

