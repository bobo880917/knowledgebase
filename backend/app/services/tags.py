import sqlite3


def list_tags(conn: sqlite3.Connection, project_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, project_id, name, created_at
        FROM tags
        WHERE project_id = ?
        ORDER BY name COLLATE NOCASE
        """,
        (project_id,),
    ).fetchall()


def create_tag(conn: sqlite3.Connection, project_id: int, name: str) -> sqlite3.Row:
    name = name.strip()
    if not name:
        raise ValueError("标签名不能为空")
    cur = conn.execute(
        """
        INSERT INTO tags(project_id, name)
        VALUES (?, ?)
        """,
        (project_id, name),
    )
    tid = int(cur.lastrowid)
    row = conn.execute("SELECT id, project_id, name, created_at FROM tags WHERE id = ?", (tid,)).fetchone()
    assert row
    return row


def delete_tag(conn: sqlite3.Connection, tag_id: int, project_id: int) -> bool:
    row = conn.execute(
        "SELECT id FROM tags WHERE id = ? AND project_id = ?",
        (tag_id, project_id),
    ).fetchone()
    if not row:
        return False
    conn.execute("DELETE FROM document_tags WHERE tag_id = ?", (tag_id,))
    conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
    return True


def set_document_tags(conn: sqlite3.Connection, document_id: int, project_id: int, tag_ids: list[int]) -> None:
    row = conn.execute(
        "SELECT id FROM documents WHERE id = ? AND project_id = ?",
        (document_id, project_id),
    ).fetchone()
    if not row:
        raise ValueError("文档不存在或不属于该项目")
    if tag_ids:
        placeholders = ",".join("?" * len(tag_ids))
        ok = conn.execute(
            f"""
            SELECT COUNT(*) AS c FROM tags
            WHERE project_id = ? AND id IN ({placeholders})
            """,
            (project_id, *tag_ids),
        ).fetchone()
        if int(ok["c"]) != len(tag_ids):
            raise ValueError("存在无效标签或非本项目的标签")
    conn.execute("DELETE FROM document_tags WHERE document_id = ?", (document_id,))
    for tid in tag_ids:
        conn.execute(
            "INSERT OR IGNORE INTO document_tags(document_id, tag_id) VALUES (?, ?)",
            (document_id, tid),
        )


def document_ids_for_filters(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    tag_ids: list[int] | None = None,
    file_types: list[str] | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
) -> set[int] | None:
    """返回需参与检索的文档 id 集合；无过滤条件时返回 None。"""
    tag_ids = tag_ids or []
    file_types = file_types or []
    has_tag = len(tag_ids) > 0
    has_ft = len(file_types) > 0
    has_after = bool((created_after or "").strip())
    has_before = bool((created_before or "").strip())
    if not (has_tag or has_ft or has_after or has_before):
        return None

    conditions: list[str] = ["d.project_id = ?"]
    params: list[object] = [project_id]

    if has_ft:
        ft_clean = [f.lstrip(".").lower() for f in file_types if f.strip()]
        if ft_clean:
            ph = ",".join("?" * len(ft_clean))
            conditions.append(f"d.file_type IN ({ph})")
            params.extend(ft_clean)

    if has_after:
        conditions.append("datetime(d.created_at) >= datetime(?)")
        params.append(created_after.strip())

    if has_before:
        conditions.append("datetime(d.created_at) <= datetime(?)")
        params.append(created_before.strip())

    where_sql = " AND ".join(conditions)

    if has_tag:
        ph = ",".join("?" * len(tag_ids))
        sql = f"""
            SELECT d.id
            FROM documents d
            WHERE {where_sql}
              AND (
                SELECT COUNT(DISTINCT dt.tag_id)
                FROM document_tags dt
                WHERE dt.document_id = d.id AND dt.tag_id IN ({ph})
              ) = ?
        """
        params.extend(tag_ids)
        params.append(len(tag_ids))
    else:
        sql = f"SELECT d.id FROM documents d WHERE {where_sql}"

    rows = conn.execute(sql, params).fetchall()
    return {int(r["id"]) for r in rows}
