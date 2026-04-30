import re
from dataclasses import dataclass

from app.schemas import SearchHit
from app.services.embeddings import EmbeddingService, cosine_similarity
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
    match_type: str
    source_id: int


class RetrievalService:
    def __init__(self) -> None:
        self.embedding = EmbeddingService()

    def search(self, query: str, project_id: int, top_k: int = 8) -> list[SearchHit]:
        query_vector = self.embedding.embed(query)
        tokens = _query_tokens(query)
        candidates: list[Candidate] = []

        with get_db() as conn:
            embedding_rows = conn.execute(
                "SELECT entity_type, entity_id, text, vector FROM embeddings"
            ).fetchall()

            for row in embedding_rows:
                vector_score = cosine_similarity(query_vector, self.embedding.loads(row["vector"]))
                keyword_score = _keyword_score(tokens, row["text"])
                weight = _entity_weight(row["entity_type"])
                rank_score = (vector_score * 0.72 + keyword_score * 0.28) * weight
                if rank_score <= 0:
                    continue
                candidate = self._hydrate_candidate(
                    conn,
                    row["entity_type"],
                    row["entity_id"],
                    project_id,
                    rank_score,
                    vector_score,
                    keyword_score,
                )
                if candidate:
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
                match_type=item.match_type,
                source_id=item.source_id,
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
                    s.summary
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
                "section",
                row["id"],
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
                "paragraph",
                row["id"],
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
                "chunk",
                row["id"],
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
