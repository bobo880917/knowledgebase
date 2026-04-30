from app.schemas import ProjectCreate, ProjectOut, ProjectUpdate
from app.storage.database import get_db


DEFAULT_PROJECT_ID = 1


class ProjectService:
    def list_projects(self) -> list[ProjectOut]:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, name, description, created_at FROM projects ORDER BY id ASC"
            ).fetchall()
        return [ProjectOut(**dict(row)) for row in rows]

    def create_project(self, data: ProjectCreate) -> ProjectOut:
        with get_db() as conn:
            cursor = conn.execute(
                "INSERT INTO projects(name, description) VALUES (?, ?)",
                (data.name.strip(), data.description.strip()),
            )
            row = conn.execute(
                "SELECT id, name, description, created_at FROM projects WHERE id = ?",
                (int(cursor.lastrowid),),
            ).fetchone()
        return ProjectOut(**dict(row))

    def update_project(self, project_id: int, data: ProjectUpdate) -> ProjectOut | None:
        with get_db() as conn:
            conn.execute(
                "UPDATE projects SET name = ?, description = ? WHERE id = ?",
                (data.name.strip(), data.description.strip(), project_id),
            )
            row = conn.execute(
                "SELECT id, name, description, created_at FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
        return ProjectOut(**dict(row)) if row else None

    def delete_project(self, project_id: int) -> bool:
        if project_id == DEFAULT_PROJECT_ID:
            raise ValueError("默认项目不可删除")

        with get_db() as conn:
            row = conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
            if not row:
                return False
            self._delete_project_embeddings(conn, project_id)
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        return True

    def exists(self, project_id: int) -> bool:
        with get_db() as conn:
            row = conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
        return row is not None

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
