import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.core.config import get_settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL DEFAULT 1,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    source_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    parent_id INTEGER,
    title TEXT NOT NULL,
    level INTEGER NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    order_index INTEGER NOT NULL,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(parent_id) REFERENCES sections(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS paragraphs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    section_id INTEGER,
    text TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    order_index INTEGER NOT NULL,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(section_id) REFERENCES sections(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    section_id INTEGER,
    paragraph_id INTEGER,
    text TEXT NOT NULL,
    order_index INTEGER NOT NULL,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(section_id) REFERENCES sections(id) ON DELETE CASCADE,
    FOREIGN KEY(paragraph_id) REFERENCES paragraphs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    vector TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

"""

INDEXES = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_project_hash ON documents(project_id, content_hash);
CREATE INDEX IF NOT EXISTS idx_documents_project ON documents(project_id);
CREATE INDEX IF NOT EXISTS idx_sections_document ON sections(document_id);
CREATE INDEX IF NOT EXISTS idx_paragraphs_document ON paragraphs(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_entity ON embeddings(entity_type, entity_id);
"""


def connect() -> sqlite3.Connection:
    path: Path = get_settings().database_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.commit()
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("PRAGMA legacy_alter_table = ON")
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO projects(id, name, description) VALUES (1, '默认项目', '历史文档和未分类文档')"
        )
        _migrate_existing_database(conn)
        _repair_legacy_document_foreign_keys(conn)
        conn.executescript(INDEXES)
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise sqlite3.IntegrityError(f"数据库外键检查失败：{[dict(row) for row in violations]}")
        conn.execute("PRAGMA legacy_alter_table = OFF")
        conn.execute("PRAGMA foreign_keys = ON")


def _migrate_existing_database(conn: sqlite3.Connection) -> None:
    document_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(documents)").fetchall()
    }
    has_project_id = "project_id" in document_columns
    has_global_hash_unique = _has_global_content_hash_unique(conn)
    if not has_project_id or has_global_hash_unique:
        _rebuild_documents_table(conn, has_project_id)


def _has_global_content_hash_unique(conn: sqlite3.Connection) -> bool:
    indexes = conn.execute("PRAGMA index_list(documents)").fetchall()
    for index in indexes:
        if not index["unique"]:
            continue
        columns = [
            row["name"]
            for row in conn.execute(f"PRAGMA index_info({index['name']})").fetchall()
        ]
        if columns == ["content_hash"]:
            return True
    return False


def _rebuild_documents_table(conn: sqlite3.Connection, has_project_id: bool) -> None:
    project_expression = "project_id" if has_project_id else "1"
    conn.execute("ALTER TABLE documents RENAME TO documents_old")
    conn.execute(
        """
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL DEFAULT 1,
            filename TEXT NOT NULL,
            file_type TEXT NOT NULL,
            source_path TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        f"""
        INSERT INTO documents(id, project_id, filename, file_type, source_path, content_hash, summary, created_at)
        SELECT id, {project_expression}, filename, file_type, source_path, content_hash, summary, created_at
        FROM documents_old
        """
    )
    conn.execute("DROP TABLE documents_old")


def _repair_legacy_document_foreign_keys(conn: sqlite3.Connection) -> None:
    if _table_references(conn, "sections", "documents_old"):
        _rebuild_sections_table(conn)
    if _table_references(conn, "paragraphs", "documents_old"):
        _rebuild_paragraphs_table(conn)
    if _table_references(conn, "chunks", "documents_old"):
        _rebuild_chunks_table(conn)


def _table_references(conn: sqlite3.Connection, table_name: str, referenced_table: str) -> bool:
    rows = conn.execute(f"PRAGMA foreign_key_list({table_name})").fetchall()
    return any(row["table"] == referenced_table for row in rows)


def _rebuild_sections_table(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE sections RENAME TO sections_old")
    conn.execute(
        """
        CREATE TABLE sections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            parent_id INTEGER,
            title TEXT NOT NULL,
            level INTEGER NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            order_index INTEGER NOT NULL,
            FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
            FOREIGN KEY(parent_id) REFERENCES sections(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        INSERT INTO sections(id, document_id, parent_id, title, level, summary, order_index)
        SELECT id, document_id, parent_id, title, level, summary, order_index
        FROM sections_old
        """
    )
    conn.execute("DROP TABLE sections_old")


def _rebuild_paragraphs_table(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE paragraphs RENAME TO paragraphs_old")
    conn.execute(
        """
        CREATE TABLE paragraphs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            section_id INTEGER,
            text TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            order_index INTEGER NOT NULL,
            FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
            FOREIGN KEY(section_id) REFERENCES sections(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        INSERT INTO paragraphs(id, document_id, section_id, text, summary, order_index)
        SELECT id, document_id, section_id, text, summary, order_index
        FROM paragraphs_old
        """
    )
    conn.execute("DROP TABLE paragraphs_old")


def _rebuild_chunks_table(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE chunks RENAME TO chunks_old")
    conn.execute(
        """
        CREATE TABLE chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            section_id INTEGER,
            paragraph_id INTEGER,
            text TEXT NOT NULL,
            order_index INTEGER NOT NULL,
            FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
            FOREIGN KEY(section_id) REFERENCES sections(id) ON DELETE CASCADE,
            FOREIGN KEY(paragraph_id) REFERENCES paragraphs(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        INSERT INTO chunks(id, document_id, section_id, paragraph_id, text, order_index)
        SELECT id, document_id, section_id, paragraph_id, text, order_index
        FROM chunks_old
        """
    )
    conn.execute("DROP TABLE chunks_old")
