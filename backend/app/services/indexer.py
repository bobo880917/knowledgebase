import hashlib
from pathlib import Path

from fastapi import UploadFile

from app.core.config import get_settings
from app.schemas import DocumentOut, ProjectIndexStats, ReindexResult, UploadResult
from app.services.embeddings import EmbeddingService
from app.services.parsers import SUPPORTED_EXTENSIONS, parse_document
from app.services.text_utils import chunk_text, summarize_text
from app.storage.database import get_db


class DocumentIndexer:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.embedding = EmbeddingService()

    async def ingest_upload(self, file: UploadFile, project_id: int) -> UploadResult:
        original_name = file.filename or "untitled"
        suffix = Path(original_name).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
            raise ValueError(f"暂不支持 {suffix or '无扩展名'} 文件，当前支持：{supported}")

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

        sections = parse_document(target)
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

                for paragraph_index, paragraph in enumerate(section.paragraphs):
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

    def reindex_project(self, project_id: int) -> ReindexResult:
        with get_db() as conn:
            self._delete_project_embeddings(conn, project_id)
            section_count = self._reindex_sections(conn, project_id)
            paragraph_count = self._reindex_paragraphs(conn, project_id)
            chunk_count = self._reindex_chunks(conn, project_id)

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
            embedding_count = self._project_embedding_count(conn, project_id)

        expected_embedding_count = section_count + paragraph_count + chunk_count
        return ProjectIndexStats(
            project_id=project_id,
            document_count=document_count,
            section_count=section_count,
            paragraph_count=paragraph_count,
            chunk_count=chunk_count,
            embedding_count=embedding_count,
            indexed=expected_embedding_count > 0 and embedding_count == expected_embedding_count,
        )

    def _insert_embedding(self, conn, entity_type: str, entity_id: int, text: str) -> None:
        vector = self.embedding.embed(text)
        conn.execute(
            "INSERT INTO embeddings(entity_type, entity_id, text, vector) VALUES (?, ?, ?, ?)",
            (entity_type, entity_id, text, self.embedding.dumps(vector)),
        )

    def _reindex_sections(self, conn, project_id: int) -> int:
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
        for row in rows:
            self._insert_embedding(
                conn,
                "section",
                row["id"],
                f"{row['title']}\n{row['summary']}",
            )
        return len(rows)

    def _reindex_paragraphs(self, conn, project_id: int) -> int:
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
        for row in rows:
            self._insert_embedding(
                conn,
                "paragraph",
                row["id"],
                f"{row['section_title'] or ''}\n{row['summary']}",
            )
        return len(rows)

    def _reindex_chunks(self, conn, project_id: int) -> int:
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
        for row in rows:
            self._insert_embedding(
                conn,
                "chunk",
                row["id"],
                f"{row['section_title'] or ''}\n{row['text']}",
            )
        return len(rows)

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
    def _project_embedding_count(conn, project_id: int) -> int:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
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
            """,
            (project_id, project_id, project_id),
        ).fetchone()
        return int(row["count"])
