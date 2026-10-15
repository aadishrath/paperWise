import os
import uuid

import pytest

from app.database import Database


@pytest.fixture
def pg_database():
    url = os.getenv("PAPERWISE_TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "Set PAPERWISE_TEST_DATABASE_URL to run PostgreSQL/pgvector integration tests."
        )
    database = Database(url, embedding_dimensions=768)
    document_id = uuid.uuid4()
    try:
        yield database, document_id
    finally:
        database.delete_document(str(document_id))


def test_document_lifecycle_and_hybrid_retrieval(pg_database):
    database, document_id = pg_database
    database.create_queued_document(
        {
            "id": document_id,
            "filename": "integration-handbook.txt",
            "content_type": "text/plain",
            "created_at": "2026-01-01T00:00:00+00:00",
            "sha256": uuid.uuid4().hex * 2,
            "file_path": "/tmp/paperwise-integration-test.txt",
            "collection_name": "Test collection",
        }
    )
    assert database.mark_processing(str(document_id))

    semantic = [1.0] + [0.0] * 767
    other = [0.0, 1.0] + [0.0] * 766
    database.save_chunks(
        str(document_id),
        [
            {
                "id": uuid.uuid4(),
                "ordinal": 0,
                "page_number": None,
                "content": "Returns are accepted within 30 days after delivery.",
                "embedding": semantic,
            },
            {
                "id": uuid.uuid4(),
                "ordinal": 1,
                "page_number": None,
                "content": "Nightly release review happens every Thursday.",
                "embedding": other,
            },
        ],
    )

    documents = database.list_documents("Test collection")
    results = database.hybrid_search(semantic, "nightly release review")
    assert any(row["id"] for row in documents)
    assert results
    assert any("Nightly release" in row["content"] for row in results)
    assert all("score" in row and "semantic_score" in row for row in results)
