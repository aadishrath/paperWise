from pathlib import Path
import uuid

import psycopg

from app.celery_app import celery
from app.config import get_settings
from app.database import Database
from app.documents import extract_text, split_text
from app.ollama import OllamaClient, OllamaError

settings = get_settings()


@celery.task(
    bind=True,
    name="app.ingest_document",
    autoretry_for=(OllamaError, psycopg.OperationalError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    acks_late=True,
)
def ingest_document(self, document_id: str):
    database = Database(settings.database_url, settings.embed_dimensions)
    document = database.get_document(document_id)
    if not document or not database.mark_processing(document_id):
        return {"status": "skipped"}

    try:
        content = Path(document["file_path"]).read_bytes()
        pages = extract_text(
            document["filename"], content, enable_ocr=settings.ocr_enabled
        )
        passages = [
            (page.page_number, passage)
            for page in pages
            for passage in split_text(page.text)
        ]
        if not passages:
            raise ValueError(
                "No readable text was found. This PDF may be scanned; enable OCR and try again."
            )

        client = OllamaClient(
            settings.ollama_base_url, settings.embed_model, settings.chat_model
        )
        vectors = client.embed_sync([passage for _, passage in passages])
        if any(len(vector) != settings.embed_dimensions for vector in vectors):
            raise ValueError(
                f"The embedding model returned {len(vectors[0])} dimensions, but the database expects {settings.embed_dimensions}. "
                "Set OLLAMA_EMBED_DIMENSIONS to match the model and recreate the local database."
            )
        chunks = [
            {
                "id": uuid.uuid4(),
                "ordinal": index,
                "page_number": page_number,
                "content": passage,
                "embedding": vector,
            }
            for index, ((page_number, passage), vector) in enumerate(
                zip(passages, vectors)
            )
        ]
        database.save_chunks(document_id, chunks)
        return {"status": "ready", "chunk_count": len(chunks)}
    except ValueError as exc:
        database.mark_failed(document_id, str(exc))
        return {"status": "failed", "error": str(exc)}
    except (OllamaError, psycopg.OperationalError):
        if self.request.retries >= self.max_retries:
            database.mark_failed(
                document_id,
                "Indexing failed after multiple attempts. Check local model and database services.",
            )
        raise
    except Exception as exc:
        database.mark_failed(document_id, str(exc) or "Document processing failed.")
        return {"status": "failed", "error": str(exc)}
