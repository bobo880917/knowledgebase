import hashlib
import time
from pathlib import Path

from fastapi import UploadFile

from collections.abc import Callable

from app.core.config import get_settings
from app.schemas import DocumentOut, ProjectIndexStats, ReindexResult, UploadResult
from app.services.embeddings import EmbeddingService
from app.services.parsers import SUPPORTED_EXTENSIONS, parse_document
from app.services.text_utils import chunk_text, summarize_text
from app.storage.database import get_db


class CancelledError(RuntimeError):
    pass


ProgressCallback = Callable[[str, int | None, int | None], None]
CancelChecker = Callable[[], bool]

# 重建索引时若长时间未写入进度（例如单条 encode 较慢），仍可刷新更新时间以便区分「慢」与「无响应」。
_REINDEX_JOB_HEARTBEAT_SEC = 8.0


class DocumentIndexer:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.embedding = EmbeddingService()

    async def ingest_upload(
        self,
        file: UploadFile,
        project_id: int,
        *,
        job_id: int | None = None,
        progress_cb: ProgressCallback | None = None,
        should_cancel: CancelChecker | None = None,
    ) -> UploadResult:
        original_name = file.filename or "untitled"
        suffix = Path(original_name).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
            raise ValueError(f"暂不支持 {suffix or '无扩展名'} 文件，当前支持：{supported}")

        if job_id:
            self._update_job_progress(job_id, "读取文件…", None, None)
        elif progress_cb:
            progress_cb("读取文件…", None, None)
        content = await file.read()
        raw_content_hash = hashlib.sha256(content).hexdigest()
        content_hash = hashlib.sha256(f"{project_id}:{raw_content_hash}".encode("utf-8")).hexdigest()
        target = self.settings.upload_dir / f"project-{project_id}-{content_hash}{suffix}"
        if not target.exists():
            target.write_bytes(content)

        with get_db() as conn:
            existing = conn.execute(
                """
                SELECT id, project_id, filename, file_type, summary, created_at
                FROM documents
                WHERE project_id = ? AND content_hash = ?
                """,
                (project_id, content_hash),
            ).fetchone()
            if existing:
                return UploadResult(
                    document=DocumentOut(**dict(existing)),
                    section_count=self._count(conn, "sections", existing["id"]),
                    paragraph_count=self._count(conn, "paragraphs", existing["id"]),
                    chunk_count=self._count(conn, "chunks", existing["id"]),
                )

        if job_id:
            self._update_job_progress(job_id, "解析文档结构…", None, None)
        elif progress_cb:
            progress_cb("解析文档结构…", None, None)
        sections = parse_document(target)

        if should_cancel and should_cancel():
            raise CancelledError("cancel_requested")

        if job_id:
            self._update_job_progress(job_id, "统计切片数量…", None, None)
        elif progress_cb:
            progress_cb("统计切片数量…", None, None)
        expected_sections = len(sections)
        expected_paragraphs = sum(len(section.paragraphs) for section in sections)
        expected_chunks = 0
        for section in sections:
            for paragraph in section.paragraphs:
                expected_chunks += len(chunk_text(paragraph))
        expected_embeddings = expected_sections + expected_paragraphs + expected_chunks
        embedded_so_far = 0

        document_summary = summarize_text(" ".join(p for s in sections for p in s.paragraphs), 260)

        with get_db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO documents(project_id, filename, file_type, source_path, content_hash, summary)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (project_id, original_name, suffix.lstrip("."), str(target), content_hash, document_summary),
            )
            document_id = int(cursor.lastrowid)
            section_count = 0
            paragraph_count = 0
            chunk_count = 0

            for section_index, section in enumerate(sections):
                if should_cancel and (section_index % 10 == 0) and should_cancel():
                    raise CancelledError("cancel_requested")

                section_summary = summarize_text(" ".join(section.paragraphs), 220)
                section_cursor = conn.execute(
                    """
                    INSERT INTO sections(document_id, parent_id, title, level, summary, order_index)
                    VALUES (?, NULL, ?, ?, ?, ?)
                    """,
                    (document_id, section.title, section.level, section_summary, section_index),
                )
                section_id = int(section_cursor.lastrowid)
                section_count += 1
                self._insert_embedding(conn, "section", section_id, f"{section.title}\n{section_summary}")
                embedded_so_far += 1
                if job_id and (embedded_so_far % 20 == 0 or embedded_so_far == expected_embeddings):
                    self._update_job_progress_conn(
                        conn,
                        job_id,
                        "生成 embeddings（章节/段落/切片）…",
                        embedded_so_far,
                        expected_embeddings,
                    )
                elif progress_cb and (embedded_so_far % 20 == 0 or embedded_so_far == expected_embeddings):
                    progress_cb("生成 embeddings（章节/段落/切片）…", embedded_so_far, expected_embeddings)

                for paragraph_index, paragraph in enumerate(section.paragraphs):
                    if should_cancel and (paragraph_index % 20 == 0) and should_cancel():
                        raise CancelledError("cancel_requested")

                    paragraph_summary = summarize_text(paragraph, 180)
                    paragraph_cursor = conn.execute(
                        """
                        INSERT INTO paragraphs(document_id, section_id, text, summary, order_index)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (document_id, section_id, paragraph, paragraph_summary, paragraph_index),
                    )
                    paragraph_id = int(paragraph_cursor.lastrowid)
                    paragraph_count += 1
                    self._insert_embedding(conn, "paragraph", paragraph_id, f"{section.title}\n{paragraph_summary}")
                    embedded_so_far += 1
                    if job_id and (embedded_so_far % 20 == 0 or embedded_so_far == expected_embeddings):
                        self._update_job_progress_conn(
                            conn,
                            job_id,
                            "生成 embeddings（章节/段落/切片）…",
                            embedded_so_far,
                            expected_embeddings,
                        )
                    elif progress_cb and (embedded_so_far % 20 == 0 or embedded_so_far == expected_embeddings):
                        progress_cb("生成 embeddings（章节/段落/切片）…", embedded_so_far, expected_embeddings)

                    for text_chunk in chunk_text(paragraph):
                        chunk_cursor = conn.execute(
                            """
                            INSERT INTO chunks(document_id, section_id, paragraph_id, text, order_index)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (document_id, section_id, paragraph_id, text_chunk, chunk_count),
                        )
                        chunk_id = int(chunk_cursor.lastrowid)
                        chunk_count += 1
                        self._insert_embedding(conn, "chunk", chunk_id, f"{section.title}\n{text_chunk}")
                        embedded_so_far += 1
                        if job_id and (embedded_so_far % 20 == 0 or embedded_so_far == expected_embeddings):
                            self._update_job_progress_conn(
                                conn,
                                job_id,
                                "生成 embeddings（章节/段落/切片）…",
                                embedded_so_far,
                                expected_embeddings,
                            )
                        elif progress_cb and (embedded_so_far % 20 == 0 or embedded_so_far == expected_embeddings):
                            progress_cb("生成 embeddings（章节/段落/切片）…", embedded_so_far, expected_embeddings)

            row = conn.execute(
                """
                SELECT id, project_id, filename, file_type, summary, created_at
                FROM documents
                WHERE id = ?
                """,
                (document_id,),
            ).fetchone()
            return UploadResult(
                document=DocumentOut(**dict(row)),
                section_count=section_count,
                paragraph_count=paragraph_count,
                chunk_count=chunk_count,
            )

    def list_documents(self, project_id: int) -> list[DocumentOut]:
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT id, project_id, filename, file_type, summary, created_at
                FROM documents
                WHERE project_id = ?
                ORDER BY created_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [DocumentOut(**dict(row)) for row in rows]

    def delete_document(self, document_id: int, project_id: int) -> bool:
        with get_db() as conn:
            row = conn.execute(
                "SELECT source_path FROM documents WHERE id = ? AND project_id = ?",
                (document_id, project_id),
            ).fetchone()
            if not row:
                return False
            conn.execute("DELETE FROM embeddings WHERE entity_id IN (SELECT id FROM sections WHERE document_id = ?) AND entity_type = 'section'", (document_id,))
            conn.execute("DELETE FROM embeddings WHERE entity_id IN (SELECT id FROM paragraphs WHERE document_id = ?) AND entity_type = 'paragraph'", (document_id,))
            conn.execute("DELETE FROM embeddings WHERE entity_id IN (SELECT id FROM chunks WHERE document_id = ?) AND entity_type = 'chunk'", (document_id,))
            conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        source = Path(row["source_path"])
        if source.exists():
            source.unlink()
        return True

    def reindex_project(
        self,
        project_id: int,
        *,
        job_id: int | None = None,
        progress_cb: ProgressCallback | None = None,
        should_cancel: CancelChecker | None = None,
    ) -> ReindexResult:
        with get_db() as conn:
            if job_id:
                self._update_job_progress_conn(conn, job_id, "统计待重建 embeddings 数量…", None, None)
            elif progress_cb:
                progress_cb("统计待重建 embeddings 数量…", None, None)
            section_total = self._project_count(conn, "sections", project_id)
            paragraph_total = self._project_count(conn, "paragraphs", project_id)
            chunk_total = self._project_count(conn, "chunks", project_id)
            embedding_total = section_total + paragraph_total + chunk_total
            embedded_so_far = 0

            if job_id:
                self._update_job_progress_conn(conn, job_id, "清理旧 embeddings…", 0, embedding_total)
            elif progress_cb:
                progress_cb("清理旧 embeddings…", 0, embedding_total)
            self._delete_project_embeddings(conn, project_id)

            if should_cancel and should_cancel():
                raise CancelledError("cancel_requested")

            if job_id:
                self._update_job_progress_conn(conn, job_id, "重建章节 embeddings…", embedded_so_far, embedding_total)
            elif progress_cb:
                progress_cb("重建章节 embeddings…", embedded_so_far, embedding_total)
            section_count = self._reindex_sections(
                conn,
                project_id,
                progress_cb=progress_cb,
                should_cancel=should_cancel,
                offset=embedded_so_far,
                total=embedding_total,
                job_id=job_id,
            )
            embedded_so_far += section_count

            if should_cancel and should_cancel():
                raise CancelledError("cancel_requested")

            if job_id:
                self._update_job_progress_conn(conn, job_id, "重建段落 embeddings…", embedded_so_far, embedding_total)
            elif progress_cb:
                progress_cb("重建段落 embeddings…", embedded_so_far, embedding_total)
            paragraph_count = self._reindex_paragraphs(
                conn,
                project_id,
                progress_cb=progress_cb,
                should_cancel=should_cancel,
                offset=embedded_so_far,
                total=embedding_total,
                job_id=job_id,
            )
            embedded_so_far += paragraph_count

            if should_cancel and should_cancel():
                raise CancelledError("cancel_requested")

            if job_id:
                self._update_job_progress_conn(conn, job_id, "重建切片 embeddings…", embedded_so_far, embedding_total)
            elif progress_cb:
                progress_cb("重建切片 embeddings…", embedded_so_far, embedding_total)
            chunk_count = self._reindex_chunks(
                conn,
                project_id,
                progress_cb=progress_cb,
                should_cancel=should_cancel,
                offset=embedded_so_far,
                total=embedding_total,
                job_id=job_id,
            )
            embedded_so_far += chunk_count

        return ReindexResult(
            project_id=project_id,
            section_count=section_count,
            paragraph_count=paragraph_count,
            chunk_count=chunk_count,
            embedding_count=section_count + paragraph_count + chunk_count,
        )

    def get_project_index_stats(self, project_id: int) -> ProjectIndexStats:
        with get_db() as conn:
            document_count = self._project_count(conn, "documents", project_id)
            section_count = self._project_count(conn, "sections", project_id)
            paragraph_count = self._project_count(conn, "paragraphs", project_id)
            chunk_count = self._project_count(conn, "chunks", project_id)
            provider = self.settings.embedding_provider
            model = self.settings.embedding_model
            dimension = int(self.settings.embedding_dimension)
            version_seed = f"{provider}|{model}|{dimension}".encode("utf-8")
            current_version = hashlib.sha256(version_seed).hexdigest()[:12]

            embedding_count_total = self._project_embedding_count(conn, project_id)
            embedding_count_active = self._project_embedding_count(conn, project_id, version=current_version)
            dominant_version = self._project_dominant_embedding_version(conn, project_id)
            if dominant_version is None and embedding_count_total > 0:
                dominant_version = "legacy"

        expected_embedding_count = section_count + paragraph_count + chunk_count
        return ProjectIndexStats(
            project_id=project_id,
            document_count=document_count,
            section_count=section_count,
            paragraph_count=paragraph_count,
            chunk_count=chunk_count,
            embedding_count=embedding_count_active,
            embedding_count_total=embedding_count_total,
            embedding_provider=provider,
            embedding_model=model,
            embedding_dimension=dimension,
            embedding_version=current_version,
            dominant_embedding_version=dominant_version or "",
            matches_current_config=expected_embedding_count > 0 and embedding_count_active == expected_embedding_count,
            indexed=expected_embedding_count > 0 and embedding_count_active == expected_embedding_count,
        )

    def _insert_embedding(self, conn, entity_type: str, entity_id: int, text: str) -> None:
        vector = self.embedding.embed(text)
        provider = self.settings.embedding_provider
        model = self.settings.embedding_model
        dimension = int(self.settings.embedding_dimension)
        version_seed = f"{provider}|{model}|{dimension}".encode("utf-8")
        version = hashlib.sha256(version_seed).hexdigest()[:12]
        conn.execute(
            """
            INSERT INTO embeddings(entity_type, entity_id, text, vector, provider, model, dimension, version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (entity_type, entity_id, text, self.embedding.dumps(vector), provider, model, dimension, version),
        )

    def _reindex_sections(
        self,
        conn,
        project_id: int,
        *,
        job_id: int | None = None,
        progress_cb: ProgressCallback | None = None,
        should_cancel: CancelChecker | None = None,
        offset: int = 0,
        total: int | None = None,
    ) -> int:
        rows = conn.execute(
            """
            SELECT s.id, s.title, s.summary
            FROM sections s
            JOIN documents d ON d.id = s.document_id
            WHERE d.project_id = ?
            ORDER BY s.document_id, s.order_index
            """,
            (project_id,),
        ).fetchall()
        last_pulse = time.monotonic()
        for index, row in enumerate(rows):
            if should_cancel and (index % 50 == 0) and should_cancel():
                raise CancelledError("cancel_requested")
            self._insert_embedding(
                conn,
                "section",
                row["id"],
                f"{row['title']}\n{row['summary']}",
            )
            tick = total is not None and DocumentIndexer._reindex_emit_progress_tick(index, len(rows))
            if tick and job_id:
                self._update_job_progress_conn(conn, job_id, "重建章节 embeddings…", offset + index + 1, total)
                last_pulse = time.monotonic()
            elif tick and progress_cb:
                progress_cb("重建章节 embeddings…", offset + index + 1, total)
            elif job_id:
                now = time.monotonic()
                if now - last_pulse >= _REINDEX_JOB_HEARTBEAT_SEC:
                    DocumentIndexer._touch_job_updated_at(conn, job_id)
                    last_pulse = now
        return len(rows)

    def _reindex_paragraphs(
        self,
        conn,
        project_id: int,
        *,
        job_id: int | None = None,
        progress_cb: ProgressCallback | None = None,
        should_cancel: CancelChecker | None = None,
        offset: int = 0,
        total: int | None = None,
    ) -> int:
        rows = conn.execute(
            """
            SELECT p.id, p.summary, s.title AS section_title
            FROM paragraphs p
            JOIN documents d ON d.id = p.document_id
            LEFT JOIN sections s ON s.id = p.section_id
            WHERE d.project_id = ?
            ORDER BY p.document_id, p.order_index
            """,
            (project_id,),
        ).fetchall()
        last_pulse = time.monotonic()
        for index, row in enumerate(rows):
            if should_cancel and (index % 50 == 0) and should_cancel():
                raise CancelledError("cancel_requested")
            self._insert_embedding(
                conn,
                "paragraph",
                row["id"],
                f"{row['section_title'] or ''}\n{row['summary']}",
            )
            tick = total is not None and DocumentIndexer._reindex_emit_progress_tick(index, len(rows))
            if tick and job_id:
                self._update_job_progress_conn(conn, job_id, "重建段落 embeddings…", offset + index + 1, total)
                last_pulse = time.monotonic()
            elif tick and progress_cb:
                progress_cb("重建段落 embeddings…", offset + index + 1, total)
            elif job_id:
                now = time.monotonic()
                if now - last_pulse >= _REINDEX_JOB_HEARTBEAT_SEC:
                    DocumentIndexer._touch_job_updated_at(conn, job_id)
                    last_pulse = now
        return len(rows)

    def _reindex_chunks(
        self,
        conn,
        project_id: int,
        *,
        job_id: int | None = None,
        progress_cb: ProgressCallback | None = None,
        should_cancel: CancelChecker | None = None,
        offset: int = 0,
        total: int | None = None,
    ) -> int:
        rows = conn.execute(
            """
            SELECT c.id, c.text, s.title AS section_title
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            LEFT JOIN sections s ON s.id = c.section_id
            WHERE d.project_id = ?
            ORDER BY c.document_id, c.order_index
            """,
            (project_id,),
        ).fetchall()
        last_pulse = time.monotonic()
        for index, row in enumerate(rows):
            if should_cancel and (index % 100 == 0) and should_cancel():
                raise CancelledError("cancel_requested")
            self._insert_embedding(
                conn,
                "chunk",
                row["id"],
                f"{row['section_title'] or ''}\n{row['text']}",
            )
            tick = total is not None and DocumentIndexer._reindex_emit_progress_tick(index, len(rows))
            if tick and job_id:
                self._update_job_progress_conn(conn, job_id, "重建切片 embeddings…", offset + index + 1, total)
                last_pulse = time.monotonic()
            elif tick and progress_cb:
                progress_cb("重建切片 embeddings…", offset + index + 1, total)
            elif job_id:
                now = time.monotonic()
                if now - last_pulse >= _REINDEX_JOB_HEARTBEAT_SEC:
                    DocumentIndexer._touch_job_updated_at(conn, job_id)
                    last_pulse = now
        return len(rows)

    @staticmethod
    def _update_job_progress(job_id: int, message: str, current: int | None, total: int | None) -> None:
        with get_db() as conn:
            DocumentIndexer._update_job_progress_conn(conn, job_id, message, current, total)

    @staticmethod
    def _touch_job_updated_at(conn, job_id: int) -> None:
        conn.execute("UPDATE jobs SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (job_id,))
        conn.commit()

    @staticmethod
    def _reindex_emit_progress_tick(zero_based_index: int, phase_item_count: int) -> bool:
        """按阶段内条数节流上报进度，避免出现「已完成几十条但仍显示 0/N」的假象。"""
        if phase_item_count <= 0:
            return False
        if zero_based_index == 0 or (zero_based_index + 1) == phase_item_count:
            return True
        step = max(1, phase_item_count // 25)
        return (zero_based_index + 1) % step == 0

    @staticmethod
    def _update_job_progress_conn(
        conn,
        job_id: int,
        message: str,
        current: int | None,
        total: int | None,
    ) -> None:
        sets: list[str] = ["updated_at = CURRENT_TIMESTAMP", "message = ?"]
        values: list[object] = [message]
        if current is not None:
            sets.append("progress_current = ?")
            values.append(current)
        if total is not None:
            sets.append("progress_total = ?")
            values.append(total)
        conn.execute(
            f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?",
            (*values, job_id),
        )
        conn.commit()

    @staticmethod
    def _delete_project_embeddings(conn, project_id: int) -> None:
        conn.execute(
            """
            DELETE FROM embeddings
            WHERE entity_type = 'section'
              AND entity_id IN (
                  SELECT s.id
                  FROM sections s
                  JOIN documents d ON d.id = s.document_id
                  WHERE d.project_id = ?
              )
            """,
            (project_id,),
        )
        conn.execute(
            """
            DELETE FROM embeddings
            WHERE entity_type = 'paragraph'
              AND entity_id IN (
                  SELECT p.id
                  FROM paragraphs p
                  JOIN documents d ON d.id = p.document_id
                  WHERE d.project_id = ?
              )
            """,
            (project_id,),
        )
        conn.execute(
            """
            DELETE FROM embeddings
            WHERE entity_type = 'chunk'
              AND entity_id IN (
                  SELECT c.id
                  FROM chunks c
                  JOIN documents d ON d.id = c.document_id
                  WHERE d.project_id = ?
              )
            """,
            (project_id,),
        )

    @staticmethod
    def _count(conn, table: str, document_id: int) -> int:
        row = conn.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE document_id = ?", (document_id,)).fetchone()
        return int(row["count"])

    @staticmethod
    def _project_count(conn, table: str, project_id: int) -> int:
        if table == "documents":
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM documents WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            return int(row["count"])

        row = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM {table} item
            JOIN documents d ON d.id = item.document_id
            WHERE d.project_id = ?
            """,
            (project_id,),
        ).fetchone()
        return int(row["count"])

    @staticmethod
    def _project_embedding_count(conn, project_id: int, *, version: str | None = None) -> int:
        version_clause = ""
        params: list[object] = [project_id, project_id, project_id]
        if version is not None:
            version_clause = " AND e.version = ?"
            params = [project_id, version, project_id, version, project_id, version]
        row = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM embeddings e
            WHERE
                (e.entity_type = 'section'{version_clause} AND e.entity_id IN (
                    SELECT s.id
                    FROM sections s
                    JOIN documents d ON d.id = s.document_id
                    WHERE d.project_id = ?
                ))
                OR (e.entity_type = 'paragraph'{version_clause} AND e.entity_id IN (
                    SELECT p.id
                    FROM paragraphs p
                    JOIN documents d ON d.id = p.document_id
                    WHERE d.project_id = ?
                ))
                OR (e.entity_type = 'chunk'{version_clause} AND e.entity_id IN (
                    SELECT c.id
                    FROM chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE d.project_id = ?
                ))
            """,
            params,
        ).fetchone()
        return int(row["count"])

    @staticmethod
    def _project_dominant_embedding_version(conn, project_id: int) -> str | None:
        row = conn.execute(
            """
            SELECT e.version, COUNT(*) AS count
            FROM embeddings e
            WHERE
                (e.entity_type = 'section' AND e.entity_id IN (
                    SELECT s.id
                    FROM sections s
                    JOIN documents d ON d.id = s.document_id
                    WHERE d.project_id = ?
                ))
                OR (e.entity_type = 'paragraph' AND e.entity_id IN (
                    SELECT p.id
                    FROM paragraphs p
                    JOIN documents d ON d.id = p.document_id
                    WHERE d.project_id = ?
                ))
                OR (e.entity_type = 'chunk' AND e.entity_id IN (
                    SELECT c.id
                    FROM chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE d.project_id = ?
                ))
            GROUP BY e.version
            ORDER BY count DESC
            LIMIT 1
            """,
            (project_id, project_id, project_id),
        ).fetchone()
        if not row:
            return None
        value = str(row["version"] or "")
        return value or None
