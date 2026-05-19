import sqlite3


def list_messages(conn: sqlite3.Connection, project_id: int, limit: int = 40) -> list[sqlite3.Row]:
    limit = max(1, min(limit, 200))
    return conn.execute(
        """
        SELECT id, project_id, role, content, created_at
        FROM chat_messages
        WHERE project_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (project_id, limit),
    ).fetchall()[::-1]


def append_message(conn: sqlite3.Connection, project_id: int, role: str, content: str) -> None:
    role = role.strip().lower()
    if role not in ("user", "assistant", "system"):
        raise ValueError("role 须为 user、assistant 或 system")
    text = content.strip()
    if not text:
        raise ValueError("内容不能为空")
    conn.execute(
        """
        INSERT INTO chat_messages(project_id, role, content)
        VALUES (?, ?, ?)
        """,
        (project_id, role, text),
    )


def clear_messages(conn: sqlite3.Connection, project_id: int) -> None:
    conn.execute("DELETE FROM chat_messages WHERE project_id = ?", (project_id,))


def tail_for_prompt(rows: list[sqlite3.Row], max_turns: int = 8) -> str:
    """最近若干条消息，供 RAG 多轮拼接（从新到旧取 max_turns*2 条再正序）。"""
    if not rows:
        return ""
    slice_rows = rows[-max_turns * 2 :]
    lines: list[str] = []
    for row in slice_rows:
        r = str(row["role"])
        c = str(row["content"]).replace("\r\n", "\n").strip()
        if not c:
            continue
        label = "用户" if r == "user" else ("助手" if r == "assistant" else "系统")
        lines.append(f"{label}：{c}")
    return "\n".join(lines)
