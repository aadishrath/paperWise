from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import psycopg

from app.config import get_settings
from app.database import Database
from app.documents import ALLOWED_EXTENSIONS
from app.ollama import OllamaClient, OllamaError
from app.tasks import ingest_document
from app.telemetry import configure_telemetry
from app.workflow import AnswerWorkflow

settings = get_settings()
database = Database(settings.database_url, settings.embed_dimensions)
ollama = OllamaClient(
    settings.ollama_base_url, settings.embed_model, settings.chat_model
)
workflow = AnswerWorkflow(
    database, ollama, settings.min_relevance_score, settings.embed_dimensions
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(title="PaperWise API", version="0.2.0", lifespan=lifespan)
configure_telemetry(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["GET", "POST", "DELETE", "PATCH"],
    allow_headers=["*"],
)


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


class CollectionInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)


@app.get("/api/health")
async def health():
    try:
        database_ok = database.ping()
    except psycopg.Error:
        database_ok = False
    model_health = await ollama.model_health()
    all_ready = (
        database_ok
        and model_health["reachable"]
        and model_health["chat_model"]
        and model_health["embed_model"]
    )
    return {
        "status": "ok" if all_ready else "degraded",
        "database": database_ok,
        "ollama": model_health["reachable"],
        "chat_model": {
            "name": settings.chat_model,
            "available": model_health["chat_model"],
        },
        "embed_model": {
            "name": settings.embed_model,
            "available": model_health["embed_model"],
        },
    }


@app.get("/api/documents")
def get_documents(collection_name: str | None = None):
    return database.list_documents(collection_name)


@app.get("/api/collections")
def get_collections():
    return database.list_collections()


@app.post("/api/collections", status_code=201)
def create_collection(payload: CollectionInput):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Collection name cannot be blank.")
    if name.casefold() == "all collections":
        raise HTTPException(
            status_code=422, detail="Choose a different name for this collection."
        )
    if not database.create_collection(name):
        raise HTTPException(
            status_code=409, detail="A collection with that name already exists."
        )
    return {"name": name}


@app.post("/api/documents", status_code=202)
async def upload_document(
    file: UploadFile = File(...),
    collection_name: str = Form(default="My documents", min_length=1, max_length=80),
):
    filename = (file.filename or "").replace("\\", "/").split("/")[-1].strip()[:255]
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        await file.close()
        raise HTTPException(
            status_code=415, detail="Upload a PDF, DOCX, Markdown, or TXT file."
        )

    try:
        content = await file.read(settings.max_upload_bytes + 1)
    finally:
        await file.close()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413, detail="File exceeds the configured upload limit."
        )
    if not content:
        raise HTTPException(status_code=422, detail="The uploaded file is empty.")

    sha256 = hashlib.sha256(content).hexdigest()
    existing = database.find_document_by_hash(sha256)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"This file is already in PaperWise as '{existing['filename']}' ({existing['status']}).",
        )

    collection_name = collection_name.strip()
    if not collection_name:
        raise HTTPException(status_code=422, detail="Collection name cannot be blank.")
    if not database.collection_exists(collection_name):
        raise HTTPException(
            status_code=422, detail="Choose an existing collection before uploading."
        )

    document_id = uuid.uuid4()
    upload_dir = settings.data_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / f"{document_id}{extension}"
    document = {
        "id": document_id,
        "filename": filename,
        "content_type": file.content_type or "application/octet-stream",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sha256": sha256,
        "file_path": str(file_path),
        "collection_name": collection_name,
    }

    temporary_path = file_path.with_suffix(file_path.suffix + ".part")
    try:
        temporary_path.write_bytes(content)
        temporary_path.replace(file_path)
        database.create_queued_document(document)
    except psycopg.errors.UniqueViolation as exc:
        file_path.unlink(missing_ok=True)
        temporary_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=409, detail="This file has already been added."
        ) from exc
    except OSError as exc:
        file_path.unlink(missing_ok=True)
        temporary_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=500, detail="Could not save this file to local storage."
        ) from exc
    except psycopg.Error as exc:
        file_path.unlink(missing_ok=True)
        temporary_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=503,
            detail="Could not save document details to the local database.",
        ) from exc

    try:
        ingest_document.delay(str(document_id))
    except Exception as exc:
        database.mark_failed(
            str(document_id),
            "The local processing queue is unavailable. Restart Redis and try again.",
        )
        raise HTTPException(
            status_code=503,
            detail="The local processing queue is unavailable. Start Redis and try again.",
        ) from exc

    return {
        "id": document_id,
        "filename": filename,
        "created_at": document["created_at"],
        "status": "queued",
        "collection_name": collection_name,
    }


@app.delete("/api/documents/{document_id}", status_code=204)
def remove_document(document_id: str):
    deleted, file_path = database.delete_document(document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found.")
    if file_path:
        Path(file_path).unlink(missing_ok=True)


@app.patch("/api/documents/{document_id}/collection")
def move_document(document_id: str, payload: CollectionInput):
    collection_name = payload.name.strip()
    if not collection_name:
        raise HTTPException(status_code=422, detail="Collection name cannot be blank.")
    if not database.collection_exists(collection_name):
        raise HTTPException(status_code=404, detail="Collection not found.")
    if not database.move_document_to_collection(document_id, collection_name):
        raise HTTPException(status_code=404, detail="Document not found.")
    return {"id": document_id, "collection_name": collection_name}


@app.post("/api/documents/{document_id}/retry", status_code=202)
def retry_document(document_id: str):
    queued, file_path = database.requeue_document(document_id)
    if not queued:
        raise HTTPException(
            status_code=404, detail="No failed document with that ID was found."
        )
    if not file_path or not Path(file_path).is_file():
        database.mark_failed(
            document_id,
            "The local original file is missing. Remove the record and upload the file again.",
        )
        raise HTTPException(
            status_code=410, detail="The original file is missing from local storage."
        )
    try:
        ingest_document.delay(document_id)
    except Exception as exc:
        database.mark_failed(
            document_id,
            "The local processing queue is unavailable. Restart Redis and try again.",
        )
        raise HTTPException(
            status_code=503,
            detail="The local processing queue is unavailable. Start Redis and try again.",
        ) from exc
    return {"id": document_id, "status": "queued"}


@app.post("/api/chat")
async def chat(payload: Question):
    if not database.ready_document_count():
        documents = database.list_documents()
        if documents:
            raise HTTPException(
                status_code=409,
                detail="Your documents are still indexing or need attention. Check their status in the library.",
            )
        raise HTTPException(
            status_code=409, detail="Add a document before asking a question."
        )
    try:
        state = await workflow.run(payload.question)
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "answer": state.answer,
        "abstained": state.abstained,
        "citations": [
            {
                "number": item["citation_number"],
                "document_id": item["document_id"],
                "filename": item["filename"],
                "page_number": item["page_number"],
                "passage": item["content"],
                "relevance": round(item["score"], 4),
            }
            for item in state.citations
        ],
    }
