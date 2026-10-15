# PaperWise

**Answers from your documents, with sources you can check.**

PaperWise is a local-first document question-answering app. Add PDF, Markdown, or text files, ask a question, and inspect the source passages used to form the answer. Files, extracted text, embeddings, and model calls stay on your computer when you run the included local stack.

## What works today

- Upload PDF, DOCX, Markdown, and plain-text documents into named collections.
- Process uploads in the Redis/Celery worker and show queued, processing, ready, or failed status.
- Split content into overlapping passages and create embeddings with Ollama.
- Retrieve hybrid keyword/vector matches locally, abstain when evidence is weak, and validate model citations against retrieved passages.
- Show cited source document, page where available, and the supporting passage alongside each answer.
- Store documents and vectors in local PostgreSQL with pgvector and full-text search.
- Remove documents and their indexed passages; prevent duplicate uploads by content hash.
- Keep recent chat history in this browser and filter files by name or collection.
- Run a small repeatable evaluation against the included sample handbook.

## Run it

### Requirements

- Docker Desktop with Docker Compose, or Python 3.11+ and Node.js 20.9+ for running the services directly.
- Ollama. The Docker Compose setup starts Ollama for you; running directly requires Ollama installed on your computer.
- About 5 GB of free disk space for the recommended models (model sizes vary).

### Docker Compose

```bash
docker compose up --build
```

Open [http://localhost:3000](http://localhost:3000). On its first start, Ollama downloads `nomic-embed-text` and `gemma3:4b`; this can take several minutes. PostgreSQL with pgvector, Redis, and a Celery worker start alongside the app. Services are published to localhost only. Add `examples/product-handbook.md`, wait until its status reads **ready**, then ask the sample question above. Change the model names in `docker-compose.yml` to use other Ollama models.

Run the sample evaluation while the stack is up:

```bash
docker compose exec api python scripts/evaluate.py
```

### Run services directly

1. Start PostgreSQL with pgvector and Redis. Install Tesseract OCR if you want scanned-PDF support. Install and start Ollama, then download the models:

   ```bash
   ollama pull nomic-embed-text
   ollama pull gemma3:4b
   ```

2. Set `DATABASE_URL` to your PostgreSQL connection string, then start the API:

   ```bash
   cd backend
   python -m venv .venv
   # Activate .venv, then:
   pip install -e '.[dev]'
   uvicorn app.main:app --reload --port 8000
   ```

3. In another terminal, start the web app:

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

4. In a third terminal, start the background worker:

   ```bash
   cd backend
   celery -A app.celery_app:celery worker --loglevel=INFO --concurrency=1
   ```

5. Open [http://localhost:3000](http://localhost:3000). The API docs are at [http://localhost:8000/docs](http://localhost:8000/docs).

## Configuration

The API reads these environment variables (all optional):

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | local Paperwise PostgreSQL URL | PostgreSQL connection string |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server address |
| `OLLAMA_CHAT_MODEL` | `gemma3:4b` | Local model used to answer questions |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Local model used to embed passages |
| `OLLAMA_EMBED_DIMENSIONS` | `768` | Vector size produced by the embedding model; match this to your chosen model (up to 2000 dimensions for the configured HNSW index) |
| `MAX_UPLOAD_MB` | `20` | Maximum size of an uploaded file |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | Allowed browser origin |
| `REDIS_URL` | `redis://localhost:6379/0` | Local task queue |
| `PAPERWISE_DATA_DIR` | `./data` | Local original-file storage for re-indexing |
| `PAPERWISE_ENABLE_OCR` | `false` | Enable PyMuPDF/Tesseract OCR for scanned PDFs |
| `MIN_RELEVANCE_SCORE` | `0.28` | Minimum semantic score before the assistant abstains |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | empty | Optional OTLP HTTP trace endpoint ending in `/v1/traces`; tracing stays off if unset |

## Run checks

```bash
cd backend
pip install -e '.[dev]'
pytest
```

The PostgreSQL/pgvector integration test runs when `PAPERWISE_TEST_DATABASE_URL` points to a disposable test database. GitHub Actions starts an isolated pgvector service for it. Frontend checks run with `npm ci`, `npm run typecheck`, and `npm run build`.

## Privacy and limitations

PaperWise does not need a paid API key or hosted service. The app sends document text only to the configured Ollama server; in Compose that server runs locally. Original uploads, extracted passages, embeddings, and database records remain in local Docker volumes so documents can be re-indexed. The browser keeps chat history in local storage. Scanned-PDF OCR is enabled in Compose; direct installs need Tesseract installed and `PAPERWISE_ENABLE_OCR=true`. Retrieved passages are shown so answers can be checked; citation IDs are validated against retrieval, though a valid citation does not prove that a model's claim is correct.

## Project plan

1. **Local RAG foundation (current):** background ingestion, chunking, embeddings, hybrid retrieval, abstention, citation validation, OCR, DOCX, and local chat/library usability.
2. **Quality and trust:** richer evaluation metrics, user feedback, retrieval diagnostics, and approval-gated actions with an auditable review trail.
3. **Portfolio finish:** optional OpenTelemetry/Langfuse traces, architecture and threat-model docs, screenshots, and reproducible evaluation.

See [`docs/architecture.md`](docs/architecture.md) for the first-pass architecture.

## Technology choices

The build follows the recommended stack while keeping the default experience free to run locally: Next.js, React, and TypeScript in the browser; Python, FastAPI, and Pydantic in the API; a custom state machine; Ollama for local models; PyMuPDF and python-docx for parsing; PostgreSQL with pgvector and full-text search; and Redis/Celery for background ingestion. GitHub Actions runs backend/database and frontend checks. Custom evaluation and tests are included; OpenTelemetry can export to a configured OTLP endpoint and remains disabled by default. Hosted model adapters and Ragas/DeepEval integrations can be added as optional tools, never required for the default path.

## License

PaperWise is proprietary and reserved for the project owner's personal use and
modification. No permission is granted to others to use, copy, modify, or
distribute it. See [`LICENSE`](LICENSE).
