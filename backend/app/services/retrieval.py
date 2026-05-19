import re
from dataclasses import dataclass

from app.core.config import get_settings
from app.schemas import SearchHit
from app.services.embeddings import EmbeddingService, cosine_similarity
from app.services.fts_index import build_fts_match, build_fts_match_token_and, search_bm25
from app.storage.database import get_db


@dataclass(slots=True)
class Candidate:
    project_id: int
    project_name: str
    document_id: int
    document_name: str
    section_title: str | None
    text: str
    rank_score: float
    vector_score: float
    keyword_score: float
    bm25_score: float
    match_type: str
    source_id: int
    location_label: str | None


class RetrievalService:
    def __init__(self) -> None:
        self.embedding = EmbeddingService()
        self.settings = get_settings()

    def search(
        self,
        query: str,
        project_id: int,
        top_k: int = 8,
        doc_filter: set[int] | None = None,
    ) -> list[SearchHit]:
        if doc_filter is not None and len(doc_filter) == 0:
            return []
        query_vector = self.embedding.embed(query)
        tokens = _query_tokens(query)

        bm25_map: dict[tuple[str, int], float] = {}
        with get_db() as conn:
            match_expr = build_fts_match(query)
            fts_rows: list[tuple[str, int, float]] = []
            if match_expr:
                fts_rows = search_bm25(conn, project_id, match_expr, limit=120)
            if not fts_rows:
                alt = build_fts_match_token_and(query)
                if alt:
                    fts_rows = search_bm25(conn, project_id, alt, limit=120)
            max_bm25 = max((t[2] for t in fts_rows), default=0.0)
            for entity_type, entity_id, qual in fts_rows:
                key = (entity_type, entity_id)
                if key not in bm25_map or qual > bm25_map[key]:
                    bm25_map[key] = qual

            embedding_rows = conn.execute(
                """
                SELECT e.entity_type, e.entity_id, e.text, e.vector
                FROM embeddings e
                WHERE
                  (e.entity_type = 'section' AND e.entity_id IN (
                      SELECT s.id FROM sections s
                      JOIN documents d ON d.id = s.document_id
                      WHERE d.project_id = ?
                  ))
                  OR (e.entity_type = 'paragraph' AND e.entity_id IN (
                      SELECT p.id FROM paragraphs p
                      JOIN documents d ON d.id = p.document_id
                      WHERE d.project_id = ?
                  ))
                  OR (e.entity_type = 'chunk' AND e.entity_id IN (
                      SELECT c.id FROM chunks c
                      JOIN documents d ON d.id = c.document_id
                      WHERE d.project_id = ?
                  ))
                """,
                (project_id, project_id, project_id),
            ).fetchall()

            w_vec = float(self.settings.retrieval_vector_weight)
            w_bm25 = float(self.settings.retrieval_bm25_weight)
            w_kw = float(self.settings.retrieval_keyword_weight)
            total_w = w_vec + w_bm25 + w_kw
            if total_w <= 0:
                total_w = 1.0

            candidates: list[Candidate] = []
            for row in embedding_rows:
                vector_score = cosine_similarity(query_vector, self.embedding.loads(row["vector"]))
                keyword_score = _keyword_score(tokens, row["text"])
                key = (row["entity_type"], int(row["entity_id"]))
                raw_bm25 = bm25_map.get(key, 0.0)
                bm25_norm = raw_bm25 / max_bm25 if max_bm25 > 0 else 0.0
                weight = _entity_weight(row["entity_type"])
                fused = (
                    w_vec * vector_score + w_bm25 * bm25_norm + w_kw * keyword_score
                ) / total_w * weight
                if fused <= 0:
                    continue
                candidate = self._hydrate_candidate(
                    conn,
                    row["entity_type"],
                    int(row["entity_id"]),
                    project_id,
                    fused,
                    vector_score,
                    keyword_score,
                    bm25_norm,
                )
                if candidate:
                    if doc_filter is not None and candidate.document_id not in doc_filter:
                        continue
                    candidates.append(candidate)

        deduped = self._dedupe(candidates)
        ranked = sorted(deduped, key=lambda item: item.rank_score, reverse=True)[:top_k]
        return [
            SearchHit(
                project_id=item.project_id,
                project_name=item.project_name,
                document_id=item.document_id,
                document_name=item.document_name,
                section_title=item.section_title,
                text=item.text,
                score=round(float(item.rank_score), 4),
                rank_score=round(float(item.rank_score), 4),
                vector_score=round(float(item.vector_score), 4),
                keyword_score=round(float(item.keyword_score), 4),
                bm25_score=round(float(item.bm25_score), 4),
                match_type=item.match_type,
                source_id=item.source_id,
                location_label=item.location_label,
            )
            for item in ranked
        ]

    def _hydrate_candidate(
        self,
        conn,
        entity_type: str,
        entity_id: int,
        project_id: int,
        rank_score: float,
        vector_score: float,
        keyword_score: float,
        bm25_score: float,
    ) -> Candidate | None:
        if entity_type == "section":
            row = conn.execute(
                """
                SELECT
                    p.id AS project_id,
                    p.name AS project_name,
                    d.id AS document_id,
                    d.filename,
                    s.id,
                    s.title,
                    s.summary,
                    s.order_index
                FROM sections s
                JOIN documents d ON d.id = s.document_id
                JOIN projects p ON p.id = d.project_id
                WHERE s.id = ? AND d.project_id = ?
                """,
                (entity_id, project_id),
            ).fetchone()
            if not row:
                return None
            text = f"{row['title']}\n{row['summary']}".strip()
            loc = f"章节「{row['title']}」" if row["title"] else "章节"
            return Candidate(
                row["project_id"],
                row["project_name"],
                row["document_id"],
                row["filename"],
                row["title"],
                text,
                rank_score,
                vector_score,
                keyword_score,
                bm25_score,
                "section",
                row["id"],
                loc,
            )

        if entity_type == "paragraph":
            row = conn.execute(
                """
                SELECT
                    pr.id AS project_id,
                    pr.name AS project_name,
                    d.id AS document_id,
                    d.filename,
                    p.id,
                    p.text,
                    p.order_index,
                    s.title AS section_title
                FROM paragraphs p
                JOIN documents d ON d.id = p.document_id
                JOIN projects pr ON pr.id = d.project_id
                LEFT JOIN sections s ON s.id = p.section_id
                WHERE p.id = ? AND d.project_id = ?
                """,
                (entity_id, project_id),
            ).fetchone()
            if not row:
                return None
            ord_i = int(row["order_index"])
            sec = row["section_title"] or ""
            loc = f"{sec + ' · ' if sec else ''}段落 {ord_i + 1}"
            return Candidate(
                row["project_id"],
                row["project_name"],
                row["document_id"],
                row["filename"],
                row["section_title"],
                row["text"],
                rank_score,
                vector_score,
                keyword_score,
                bm25_score,
                "paragraph",
                row["id"],
                loc,
            )

        if entity_type == "chunk":
            row = conn.execute(
                """
                SELECT
                    p.id AS project_id,
                    p.name AS project_name,
                    d.id AS document_id,
                    d.filename,
                    c.id,
                    c.text,
                    c.order_index,
                    s.title AS section_title
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                JOIN projects p ON p.id = d.project_id
                LEFT JOIN sections s ON s.id = c.section_id
                WHERE c.id = ? AND d.project_id = ?
                """,
                (entity_id, project_id),
            ).fetchone()
            if not row:
                return None
            ord_i = int(row["order_index"])
            sec = row["section_title"] or ""
            loc = f"{sec + ' · ' if sec else ''}切片 {ord_i + 1}"
            return Candidate(
                row["project_id"],
                row["project_name"],
                row["document_id"],
                row["filename"],
                row["section_title"],
                row["text"],
                rank_score,
                vector_score,
                keyword_score,
                bm25_score,
                "chunk",
                row["id"],
                loc,
            )

        return None

    @staticmethod
    def _dedupe(candidates: list[Candidate]) -> list[Candidate]:
        best: dict[tuple[str, int], Candidate] = {}
        for candidate in candidates:
            key = (candidate.match_type, candidate.source_id)
            if key not in best or candidate.rank_score > best[key].rank_score:
                best[key] = candidate
        return list(best.values())


def _entity_weight(entity_type: str) -> float:
    if entity_type == "section":
        return 1.18
    if entity_type == "paragraph":
        return 1.08
    return 1.0


def _query_tokens(query: str) -> set[str]:
    lowered = query.lower()
    tokens = set(re.findall(r"[a-z0-9_]+", lowered))
    tokens.update(char for char in lowered if "\u4e00" <= char <= "\u9fff")
    return tokens


def _keyword_score(tokens: set[str], text: str) -> float:
    if not tokens:
        return 0.0
    lowered = text.lower()
    hits = sum(1 for token in tokens if token in lowered)
    return hits / len(tokens)
