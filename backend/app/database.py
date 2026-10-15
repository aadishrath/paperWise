import psycopg
from psycopg.rows import dict_row


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in values) + "]"


class Database:
    def __init__(self, url: str, embedding_dimensions: int = 768):
        self.url = url
        if embedding_dimensions < 1 or embedding_dimensions > 2000:
            raise ValueError(
                "Embedding dimensions must be between 1 and 2000 for the configured HNSW index"
            )
        self.embedding_dimensions = embedding_dimensions
        self.initialize()

    def connect(self):
        return psycopg.connect(self.url, row_factory=dict_row)

    def initialize(self) -> None:
        with self.connect() as db:
            db.execute("CREATE EXTENSION IF NOT EXISTS vector")
            statements = [
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id UUID PRIMARY KEY,
                    filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'ready',
                    error_message TEXT,
                    sha256 TEXT,
                    file_path TEXT,
                    collection_name TEXT NOT NULL DEFAULT 'My documents'
                )
                """,
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'ready'",
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS error_message TEXT",
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS sha256 TEXT",
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_path TEXT",
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS collection_name TEXT NOT NULL DEFAULT 'My documents'",
                "CREATE TABLE IF NOT EXISTS collections (name TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT now())",
                "INSERT INTO collections(name) VALUES ('My documents') ON CONFLICT DO NOTHING",
                "INSERT INTO collections(name) SELECT DISTINCT collection_name FROM documents ON CONFLICT DO NOTHING",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_sha256 ON documents(sha256) WHERE sha256 IS NOT NULL",
                f"""
                CREATE TABLE IF NOT EXISTS chunks (
                    id UUID PRIMARY KEY,
                    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL,
                    page_number INTEGER,
                    content TEXT NOT NULL,
                    embedding vector({self.embedding_dimensions}) NOT NULL,
                    search_text tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
                )
                """,
                "CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id)",
                "CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops)",
                "CREATE INDEX IF NOT EXISTS idx_chunks_search ON chunks USING gin (search_text)",
            ]
            for statement in statements:
                db.execute(statement)

    def ping(self) -> bool:
        with self.connect() as db:
            return db.execute("SELECT 1 AS healthy").fetchone()["healthy"] == 1

    def create_queued_document(self, document: dict) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO documents(id, filename, content_type, created_at, status, sha256, file_path, collection_name) "
                "VALUES (%s, %s, %s, %s, 'queued', %s, %s, %s)",
                (
                    document["id"],
                    document["filename"],
                    document["content_type"],
                    document["created_at"],
                    document["sha256"],
                    document["file_path"],
                    document["collection_name"],
                ),
            )

    def find_document_by_hash(self, sha256: str) -> dict | None:
        with self.connect() as db:
            return db.execute(
                "SELECT id, filename, status FROM documents WHERE sha256 = %s",
                (sha256,),
            ).fetchone()

    def get_document(self, document_id: str) -> dict | None:
        with self.connect() as db:
            return db.execute(
                "SELECT * FROM documents WHERE id = %s", (document_id,)
            ).fetchone()

    def list_documents(self, collection_name: str | None = None) -> list[dict]:
        query = "SELECT id, filename, content_type, created_at, chunk_count, status, error_message, collection_name FROM documents"
        params: tuple = ()
        if collection_name:
            query += " WHERE collection_name = %s"
            params = (collection_name,)
        query += " ORDER BY created_at DESC"
        with self.connect() as db:
            return db.execute(query, params).fetchall()

    def list_collections(self) -> list[str]:
        with self.connect() as db:
            rows = db.execute("SELECT name FROM collections ORDER BY name").fetchall()
            return [row["name"] for row in rows]

    def create_collection(self, name: str) -> bool:
        with self.connect() as db:
            result = db.execute(
                "INSERT INTO collections(name) VALUES (%s) ON CONFLICT DO NOTHING",
                (name,),
            )
            return result.rowcount > 0

    def collection_exists(self, name: str) -> bool:
        with self.connect() as db:
            return (
                db.execute(
                    "SELECT 1 FROM collections WHERE name = %s", (name,)
                ).fetchone()
                is not None
            )

    def move_document_to_collection(
        self, document_id: str, collection_name: str
    ) -> bool:
        with self.connect() as db:
            result = db.execute(
                "UPDATE documents SET collection_name = %s WHERE id = %s",
                (collection_name, document_id),
            )
            return result.rowcount > 0

    def ready_document_count(self) -> int:
        with self.connect() as db:
            return db.execute(
                "SELECT count(*) AS total FROM documents WHERE status = 'ready'"
            ).fetchone()["total"]

    def delete_document(self, document_id: str) -> tuple[bool, str | None]:
        with self.connect() as db:
            with db.transaction():
                row = db.execute(
                    "SELECT file_path FROM documents WHERE id = %s FOR UPDATE",
                    (document_id,),
                ).fetchone()
                if not row:
                    return False, None
                db.execute("DELETE FROM documents WHERE id = %s", (document_id,))
                return True, row["file_path"]

    def mark_processing(self, document_id: str) -> bool:
        with self.connect() as db:
            result = db.execute(
                "UPDATE documents SET status = 'processing', error_message = NULL WHERE id = %s AND status IN ('queued', 'processing')",
                (document_id,),
            )
            return result.rowcount > 0

    def requeue_document(self, document_id: str) -> tuple[bool, str | None]:
        with self.connect() as db:
            with db.transaction():
                row = db.execute(
                    "SELECT file_path FROM documents WHERE id = %s AND status = 'failed' FOR UPDATE",
                    (document_id,),
                ).fetchone()
                if not row:
                    return False, None
                db.execute(
                    "UPDATE documents SET status = 'queued', error_message = NULL WHERE id = %s",
                    (document_id,),
                )
                return True, row["file_path"]

    def mark_failed(self, document_id: str, message: str) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE documents SET status = 'failed', error_message = %s WHERE id = %s",
                (message[:500], document_id),
            )

    def save_chunks(self, document_id: str, chunks: list[dict]) -> None:
        with self.connect() as db:
            with db.transaction():
                db.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
                for item in chunks:
                    db.execute(
                        "INSERT INTO chunks(id, document_id, ordinal, page_number, content, embedding) "
                        "VALUES (%s, %s, %s, %s, %s, %s::vector)",
                        (
                            item["id"],
                            document_id,
                            item["ordinal"],
                            item["page_number"],
                            item["content"],
                            vector_literal(item["embedding"]),
                        ),
                    )
                db.execute(
                    "UPDATE documents SET chunk_count = %s, status = 'ready', error_message = NULL WHERE id = %s",
                    (len(chunks), document_id),
                )

    def hybrid_search(
        self, query_embedding: list[float], query: str, limit: int = 5
    ) -> list[dict]:
        query_vector = vector_literal(query_embedding)
        with self.connect() as db:
            return db.execute(
                """
                WITH q AS (
                    SELECT %s::vector AS embedding, websearch_to_tsquery('english', %s) AS terms
                ),
                vector_candidates AS (
                    SELECT id FROM chunks ORDER BY embedding <=> (SELECT embedding FROM q) LIMIT 40
                ),
                keyword_candidates AS (
                    SELECT id FROM chunks, q
                    WHERE search_text @@ q.terms
                    ORDER BY ts_rank_cd(search_text, q.terms) DESC LIMIT 40
                ),
                candidates AS (
                    SELECT id FROM vector_candidates
                    UNION
                    SELECT id FROM keyword_candidates
                )
                SELECT c.id, c.document_id, d.filename, d.collection_name, c.ordinal, c.page_number, c.content,
                       (1 - (c.embedding <=> q.embedding))::float AS semantic_score,
                       ts_rank_cd(c.search_text, q.terms)::float AS keyword_score,
                       (0.75 * (1 - (c.embedding <=> q.embedding)) +
                        0.25 * ts_rank_cd(c.search_text, q.terms))::float AS score
                FROM candidates x
                JOIN chunks c ON c.id = x.id
                JOIN documents d ON d.id = c.document_id
                CROSS JOIN q
                WHERE d.status = 'ready'
                ORDER BY score DESC
                LIMIT %s
                """,
                (query_vector, query, limit),
            ).fetchall()
