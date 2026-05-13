"""SQLite FTS5 全文索引：与 embeddings 同步写入，供 BM25 检索。"""

from __future__ import annotations

import re
import sqlite3


def migrate_entity_fts(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS entity_fts USING fts5(
            project_id UNINDEXED,
            document_id UNINDEXED,
            entity_type UNINDEXED,
            entity_id UNINDEXED,
            body,
            tokenize = 'unicode61 remove_diacritics 1'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS fts_entity_links (
            fts_rowid INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            document_id INTEGER NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_fts_entity_links_document ON fts_entity_links(document_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_fts_entity_links_project ON fts_entity_links(project_id)"
    )


def insert_entity_row(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    document_id: int,
    entity_type: str,
    entity_id: int,
    body: str,
) -> None:
    text = (body or "").strip()
    if not text:
        return
    cur = conn.execute(
        """
        INSERT INTO entity_fts(project_id, document_id, entity_type, entity_id, body)
        VALUES (?, ?, ?, ?, ?)
        """,
        (project_id, document_id, entity_type, entity_id, text),
    )
    rowid = int(cur.lastrowid)
    conn.execute(
        """
        INSERT INTO fts_entity_links(fts_rowid, project_id, document_id, entity_type, entity_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (rowid, project_id, document_id, entity_type, entity_id),
    )


def delete_document_rows(conn: sqlite3.Connection, document_id: int) -> None:
    rows = conn.execute(
        "SELECT fts_rowid FROM fts_entity_links WHERE document_id = ?",
        (document_id,),
    ).fetchall()
    for row in rows:
        conn.execute("DELETE FROM entity_fts WHERE rowid = ?", (int(row["fts_rowid"]),))
    conn.execute("DELETE FROM fts_entity_links WHERE document_id = ?", (document_id,))


def delete_project_rows(conn: sqlite3.Connection, project_id: int) -> None:
    rows = conn.execute(
        "SELECT fts_rowid FROM fts_entity_links WHERE project_id = ?",
        (project_id,),
    ).fetchall()
    for row in rows:
        conn.execute("DELETE FROM entity_fts WHERE rowid = ?", (int(row["fts_rowid"]),))
    conn.execute("DELETE FROM fts_entity_links WHERE project_id = ?", (project_id,))


def search_bm25(
    conn: sqlite3.Connection,
    project_id: int,
    match_expression: str,
    *,
    limit: int = 80,
) -> list[tuple[str, int, float]]:
    """返回 (entity_type, entity_id, bm25_raw)。bm25 越大越好（已对 SQLite 返回值取负）。"""
    if not match_expression.strip():
        return []
    try:
        rows = conn.execute(
            """
            SELECT entity_type, entity_id, bm25(entity_fts) AS b
            FROM entity_fts
            WHERE entity_fts MATCH ? AND project_id = ?
            ORDER BY b
            LIMIT ?
            """,
            (match_expression, project_id, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    out: list[tuple[str, int, float]] = []
    for row in rows:
        raw = float(row["b"])
        # SQLite bm25() 越接近 0（负数中越大）表示越相关；转成越大越好
        quality = max(0.0, -raw)
        out.append((str(row["entity_type"]), int(row["entity_id"]), quality))
    return out


def build_fts_match(query: str) -> str | None:
    """构造 FTS5 MATCH 表达式（短语优先，失败时由调用方尝试备用策略）。"""
    cleaned = query.strip()
    if not cleaned:
        return None
    escaped = cleaned.replace('"', '""')
    return f'body : "{escaped}"'


def build_fts_match_token_and(query: str) -> str | None:
    """分词后 AND 连接，适合编号、英文术语。"""
    tokens = _fts_tokens(query)
    if not tokens:
        return None
    parts = []
    for t in tokens[:24]:
        te = t.replace('"', '""')
        if te:
            parts.append(f'body : "{te}"')
    if not parts:
        return None
    return " AND ".join(parts)


def _fts_tokens(query: str) -> list[str]:
    lowered = query.lower().strip()
    out: list[str] = []
    for m in re.finditer(r"[a-z0-9_]{2,}", lowered):
        out.append(m.group(0))
    for ch in lowered:
        if "\u4e00" <= ch <= "\u9fff":
            out.append(ch)
    return out
