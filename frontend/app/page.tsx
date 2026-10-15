"use client";

import { DragEvent, FormEvent, useCallback, useEffect, useRef, useState } from "react";
import Image from "next/image";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type DocumentItem = {
  id: string;
  filename: string;
  created_at: string;
  chunk_count: number;
  status: "queued" | "processing" | "ready" | "failed";
  error_message: string | null;
  collection_name: string;
};
type Citation = {
  number: number;
  document_id: string;
  filename: string;
  page_number: number | null;
  passage: string;
  relevance: number;
};
type Exchange = {
  id?: string;
  question: string;
  answer: string;
  citations: Citation[];
  pending?: boolean;
  failed?: boolean;
};
type UploadNotice = {
  kind: "indexing" | "success" | "failure";
  message: string;
  documentIds: string[];
  issue?: string;
};

export default function Home() {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [history, setHistory] = useState<Exchange[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [collectionFilter, setCollectionFilter] = useState("All collections");
  const [collections, setCollections] = useState<string[]>([]);
  const [collectionsOpen, setCollectionsOpen] = useState(false);
  const [creatingCollection, setCreatingCollection] = useState(false);
  const [newCollectionName, setNewCollectionName] = useState("");
  const [draggedDocument, setDraggedDocument] = useState<string | null>(null);
  const [dropTargetCollection, setDropTargetCollection] = useState<string | null>(null);
  const [documentSearch, setDocumentSearch] = useState("");
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadNotice, setUploadNotice] = useState<UploadNotice | null>(null);
  const [error, setError] = useState("");
  const [connected, setConnected] = useState<boolean | null>(null);
  const chatScrollRef = useRef<HTMLDivElement>(null);

  const refresh = useCallback(async () => {
    try {
      const [docs, status, collectionResponse] = await Promise.all([
        fetch(`${API}/api/documents`),
        fetch(`${API}/api/health`),
        fetch(`${API}/api/collections`),
      ]);
      if (!docs.ok || !status.ok || !collectionResponse.ok) {
        throw new Error("PaperWise could not reach its local service.");
      }
      setDocuments(await docs.json());
      setCollections(await collectionResponse.json());
      const statusData = await status.json();
      setConnected(
        Boolean(
          statusData.database &&
            statusData.ollama &&
            statusData.chat_model.available &&
            statusData.embed_model.available,
        ),
      );
    } catch {
      setConnected(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem("paperwise.history.v1");
      if (saved) setHistory(JSON.parse(saved) as Exchange[]);
    } catch {
      window.localStorage.removeItem("paperwise.history.v1");
    } finally {
      setHistoryLoaded(true);
    }
  }, []);

  useEffect(() => {
    if (historyLoaded) {
      window.localStorage.setItem(
        "paperwise.history.v1",
        JSON.stringify(history.filter((item) => !item.pending && !item.failed)),
      );
    }
  }, [history, historyLoaded]);

  useEffect(() => {
    const chat = chatScrollRef.current;
    if (!chat || history.length === 0) return;
    window.requestAnimationFrame(() =>
      chat.scrollTo({ top: chat.scrollHeight, behavior: "smooth" })
    );
  }, [history]);

  useEffect(() => {
    if (
      !documents.some(
        (document) =>
          document.status === "queued" || document.status === "processing",
      )
    ) {
      return;
    }
    const timer = window.setInterval(() => {
      void refresh();
    }, 1800);
    return () => window.clearInterval(timer);
  }, [documents, refresh]);

  useEffect(() => {
    if (
      !uploadNotice ||
      uploadNotice.kind !== "indexing" ||
      uploading ||
      uploadNotice.documentIds.length === 0
    ) {
      return;
    }

    const tracked = uploadNotice.documentIds.map((id) =>
      documents.find((document) => document.id === id)
    );
    if (
      tracked.some(
        (document) =>
          document?.status === "queued" || document?.status === "processing",
      )
    ) {
      return;
    }

    const readyCount = tracked.filter((document) => document?.status === "ready").length;
    const failed = tracked.filter((document) => document?.status === "failed");
    const missingCount = tracked.length - readyCount - failed.length;
    const hasFailure = failed.length > 0 || missingCount > 0 ||
      Boolean(uploadNotice.issue);
    const countLabel = (count: number) => `${count} file${count === 1 ? "" : "s"}`;
    const message = hasFailure
      ? [
        readyCount > 0
          ? `${countLabel(readyCount)} ready.`
          : "No files were indexed.",
        failed.length > 0
          ? `${countLabel(failed.length)} failed; check the library to retry.`
          : "",
        missingCount > 0
          ? `${countLabel(missingCount)} were removed before indexing finished.`
          : "",
        uploadNotice.issue ? `Upload stopped: ${uploadNotice.issue}` : "",
      ]
        .filter(Boolean)
        .join(" ")
      : `${countLabel(readyCount)} indexed and ready.`;

    setUploadNotice((current) =>
      current?.kind === "indexing" &&
        current.documentIds.join(",") === uploadNotice.documentIds.join(",")
        ? {
          kind: hasFailure ? "failure" : "success",
          message,
          documentIds: current.documentIds,
        }
        : current
    );
  }, [documents, uploadNotice, uploading]);

  const hasReadyDocument = documents.some(
    (document) => document.status === "ready",
  );
  const visibleDocuments = documents.filter((document) => {
    const matchesCollection = collectionFilter === "All collections" ||
      document.collection_name === collectionFilter;
    const matchesSearch = document.filename
      .toLowerCase()
      .includes(documentSearch.toLowerCase());
    return matchesCollection && matchesSearch;
  });

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    const uploadedIds: string[] = [];
    let uploadIssue: string | undefined;
    setUploading(true);
    setError("");
    setUploadNotice({
      kind: "indexing",
      message: `Adding ${files.length} file${files.length === 1 ? "" : "s"}…`,
      documentIds: [],
    });
    try {
      for (const file of Array.from(files)) {
        const body = new FormData();
        body.append("file", file);
        body.append(
          "collection_name",
          collectionFilter === "All collections"
            ? "My documents"
            : collectionFilter,
        );
        const response = await fetch(`${API}/api/documents`, {
          method: "POST",
          body,
        });
        if (!response.ok) {
          const details = await response.json().catch(() => null);
          throw new Error(details?.detail ?? `Could not add ${file.name}.`);
        }
        const uploaded = await response.json();
        uploadedIds.push(uploaded.id);
        setUploadNotice({
          kind: "indexing",
          message: `Indexing ${uploadedIds.length} file${
            uploadedIds.length === 1 ? "" : "s"
          }…`,
          documentIds: [...uploadedIds],
        });
      }
    } catch (cause) {
      uploadIssue = cause instanceof Error
        ? cause.message
        : "Something went wrong while adding files.";
      if (uploadedIds.length > 0) {
        setUploadNotice({
          kind: "indexing",
          message: `Indexing ${uploadedIds.length} file${
            uploadedIds.length === 1 ? "" : "s"
          }…`,
          documentIds: [...uploadedIds],
          issue: uploadIssue,
        });
      } else {
        setUploadNotice({
          kind: "failure",
          message: uploadIssue,
          documentIds: [],
        });
      }
    } finally {
      await refresh();
      setUploading(false);
      if (uploadedIds.length > 0 && uploadIssue) {
        setUploadNotice({
          kind: "indexing",
          message: `Indexing ${uploadedIds.length} file${
            uploadedIds.length === 1 ? "" : "s"
          }…`,
          documentIds: [...uploadedIds],
          issue: uploadIssue,
        });
      }
    }
  }

  async function createCollection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = newCollectionName.trim();
    if (!name) return;
    setError("");
    try {
      const response = await fetch(`${API}/api/collections`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(data?.detail ?? "Could not create this collection.");
      }
      setCollectionFilter(name);
      setNewCollectionName("");
      setCreatingCollection(false);
      setCollectionsOpen(false);
      await refresh();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Could not create this collection.",
      );
    }
  }

  async function moveDocumentToCollection(
    documentId: string,
    collection: string,
  ) {
    setError("");
    try {
      const response = await fetch(
        `${API}/api/documents/${documentId}/collection`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: collection }),
        },
      );
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(data?.detail ?? "Could not move this file.");
      }
      setCollectionFilter(collection);
      setCollectionsOpen(false);
      await refresh();
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not move this file.",
      );
    } finally {
      setDraggedDocument(null);
      setDropTargetCollection(null);
    }
  }

  function startDocumentDrag(
    event: DragEvent<HTMLDivElement>,
    documentId: string,
  ) {
    if ((event.target as HTMLElement).closest("button")) {
      event.preventDefault();
      return;
    }
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", documentId);
    setDraggedDocument(documentId);
    setCollectionsOpen(true);
  }

  async function remove(id: string) {
    setError("");
    try {
      const response = await fetch(`${API}/api/documents/${id}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        setError("Could not remove this file.");
        return;
      }
      await refresh();
    } catch {
      setError("Could not reach the local service to remove this file.");
    }
  }

  async function retry(id: string) {
    setError("");
    try {
      const response = await fetch(`${API}/api/documents/${id}/retry`, {
        method: "POST",
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(data?.detail ?? "Could not retry indexing.");
      }
      await refresh();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Could not reach the local service to retry indexing.",
      );
    }
  }

  async function ask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const submittedQuestion = question.trim();
    if (!submittedQuestion || loading) return;
    const exchangeId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setHistory((items) => [
      ...items,
      {
        id: exchangeId,
        question: submittedQuestion,
        answer: "",
        citations: [],
        pending: true,
      },
    ]);
    setQuestion("");
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: submittedQuestion }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail ?? "Could not answer this question.");
      }
      setHistory((items) =>
        items.map((item) =>
          item.id === exchangeId
            ? {
              ...item,
              answer: data.answer,
              citations: data.citations,
              pending: false,
            }
            : item
        )
      );
    } catch (cause) {
      const message = cause instanceof Error
        ? cause.message
        : "Something went wrong while answering.";
      setError(message);
      setHistory((items) =>
        items.map((item) =>
          item.id === exchangeId
            ? {
              ...item,
              answer:
                "I couldn't answer this just now. Check the notice above, then try again.",
              pending: false,
              failed: true,
            }
            : item
        )
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#">
          <span className="brand-mark">
            <Image src="/app-logo.svg" alt="" width={29} height={29} priority />
          </span>
          <span>PaperWise</span>
        </a>
        <div className="workspace-label">YOUR WORKSPACE</div>
        <button className="nav-active">
          <span className="nav-icon">▤</span> My documents{" "}
          <span className="nav-count">{documents.length}</span>
        </button>
        <div className="side-section">
          <div className="side-heading">
            <span>LIBRARY</span>
            <label className="upload-mini" title="Add documents">
              ＋
              <input
                type="file"
                accept=".pdf,.docx,.md,.txt"
                multiple
                disabled={uploading}
                onChange={(event) => {
                  void upload(event.target.files);
                  event.currentTarget.value = "";
                }}
              />
            </label>
          </div>
          <input
            className="library-search"
            aria-label="Search files"
            placeholder="Find a file…"
            value={documentSearch}
            onChange={(event) => setDocumentSearch(event.target.value)}
          />
          <div className="collection-picker">
            <button
              className="collection-picker-button"
              type="button"
              aria-label="Choose a collection"
              aria-expanded={collectionsOpen}
              onClick={() => setCollectionsOpen((open) => !open)}
            >
              <span>{collectionFilter}</span>
              <span className="collection-chevron">⌄</span>
            </button>
            {collectionsOpen && (
              <div
                className="collection-menu"
                role="listbox"
                aria-label="Collections"
              >
                <button
                  className={`collection-option ${
                    collectionFilter === "All collections" ? "selected" : ""
                  }`}
                  type="button"
                  role="option"
                  aria-selected={collectionFilter === "All collections"}
                  onClick={() => {
                    setCollectionFilter("All collections");
                    setCollectionsOpen(false);
                  }}
                >
                  <span>All collections</span>
                  <span className="collection-count">{documents.length}</span>
                </button>
                {collections.map((collection) => (
                  <button
                    className={`collection-option ${
                      collectionFilter === collection ? "selected" : ""
                    } ${
                      dropTargetCollection === collection ? "drop-target" : ""
                    }`}
                    key={collection}
                    type="button"
                    role="option"
                    aria-selected={collectionFilter === collection}
                    onClick={() => {
                      setCollectionFilter(collection);
                      setCollectionsOpen(false);
                    }}
                    onDragEnter={(event) => {
                      if (draggedDocument) {
                        event.preventDefault();
                        setDropTargetCollection(collection);
                      }
                    }}
                    onDragOver={(event) => {
                      if (draggedDocument) {
                        event.preventDefault();
                        event.dataTransfer.dropEffect = "move";
                      }
                    }}
                    onDragLeave={() =>
                      setDropTargetCollection((current) =>
                        current === collection ? null : current
                      )}
                    onDrop={(event) => {
                      event.preventDefault();
                      const id = event.dataTransfer.getData("text/plain") ||
                        draggedDocument;
                      if (id) void moveDocumentToCollection(id, collection);
                    }}
                  >
                    <span>{collection}</span>
                    <span className="collection-count">
                      {documents.filter(
                        (document) => document.collection_name === collection,
                      ).length}
                    </span>
                  </button>
                ))}
                {creatingCollection
                  ? (
                    <form
                      className="collection-create-form"
                      onSubmit={(event) => void createCollection(event)}
                    >
                      <input
                        autoFocus
                        aria-label="New collection name"
                        maxLength={80}
                        placeholder="Collection name"
                        value={newCollectionName}
                        onChange={(event) =>
                          setNewCollectionName(event.target.value)}
                      />
                      <button
                        type="submit"
                        disabled={!newCollectionName.trim()}
                      >
                        Create
                      </button>
                    </form>
                  )
                  : (
                    <button
                      className="collection-create-button"
                      type="button"
                      onClick={() => setCreatingCollection(true)}
                    >
                      ＋ Create collection
                    </button>
                  )}
              </div>
            )}
          </div>
          <p className="collection-hint">
            Select a collection to view or upload files. Drag a file to move it.
          </p>
          <div className="library-files">
            {documents.length === 0
              ? <p className="empty-library">Your files will appear here.</p>
              : visibleDocuments.length === 0
              ? (
                <p className="empty-library">
                  {collectionFilter === "All collections"
                    ? "No files match this search."
                    : "No files in this collection yet."}
                </p>
              )
              : (
                visibleDocuments.map((doc) => (
                  <div className="file-row" key={doc.id} title={doc.filename}>
                    <div
                      className="file-row-drag"
                      draggable
                      onDragStart={(event) =>
                        startDocumentDrag(event, doc.id)}
                      onDragEnd={() => {
                        setDraggedDocument(null);
                        setDropTargetCollection(null);
                      }}
                      aria-label={`Drag ${doc.filename} to move it`}
                    >
                      <span className="file-icon">
                        {doc.filename.toLowerCase().endsWith(".pdf")
                          ? "PDF"
                          : doc.filename.toLowerCase().endsWith(".docx")
                          ? "DOC"
                          : "TXT"}
                      </span>
                      <span className="file-name">
                        {doc.filename}
                        <small>
                          {doc.status === "ready"
                            ? `${doc.chunk_count} passages · ${doc.collection_name}`
                            : doc.status === "failed"
                            ? doc.error_message || "Indexing failed"
                            : `${
                              doc.status === "queued"
                                ? "Waiting to index"
                                : "Indexing"
                            } · ${doc.collection_name}`}
                        </small>
                      </span>
                    </div>
                    {doc.status === "failed" && (
                      <button
                        className="retry-button"
                        onClick={() => void retry(doc.id)}
                        aria-label={`Retry indexing ${doc.filename}`}
                      >
                        ↻
                      </button>
                    )}
                    <button
                      className="remove-button"
                      onClick={() =>
                        void remove(doc.id)}
                      aria-label={`Remove ${doc.filename}`}
                    >
                      ×
                    </button>
                  </div>
                ))
              )}
          </div>
        </div>
        <div className="sidebar-bottom">
          <span className={`status-dot ${connected ? "online" : "offline"}`} />
          <span>
            {connected ? "Local models ready" : "Local model unavailable"}
          </span>
          <span className="lock">▣</span>
        </div>
      </aside>

      <section className="main-area">
        <header className="topbar">
          <div className="crumb">
            Workspace <span>/</span> <strong>Ask your files</strong>
          </div>
          <div className="local-badge">
            <span>●</span> Private · runs on your computer
          </div>
        </header>
        <div className="content">
          <div className="chat-scroll" ref={chatScrollRef}>
            <div className="intro">
              <div className="eyebrow">
                <span className="sparkle">✳</span> YOUR DOCUMENTS, UNDERSTOOD
              </div>
              <h1>
                Find the answer
                <br />
                in your <em>own words.</em>
              </h1>
              <p>
                Add your files, ask a question, and follow every answer back to
                its source.
              </p>
            </div>

            {documents.length === 0 && history.length === 0
              ? (
                <div className="welcome-card">
                  <div className="upload-illustration">
                    <div className="paper paper-back" />
                    <div className="paper paper-front">
                      <span>⌁</span>
                    </div>
                    <div className="upload-arrow">↑</div>
                  </div>
                  <h2>Start with a few files</h2>
                  <p>
                    PDFs, text files, or Markdown. PaperWise keeps everything on
                    this computer.
                  </p>
                  <label className="primary-button">
                    {uploading ? "Adding files…" : "Choose documents"}
                    <input
                      type="file"
                      accept=".pdf,.docx,.md,.txt"
                      multiple
                      disabled={uploading}
                      onChange={(event) => {
                        void upload(event.target.files);
                        event.currentTarget.value = "";
                      }}
                    />
                  </label>
                  <div className="file-hint">
                    PDF · DOCX · TXT · MD <span>—</span> up to 20 MB each
                  </div>
                </div>
              )
              : (
                <div className="conversation">
                  {history.length > 0 && (
                    <div className="history-toolbar">
                      <span>Saved on this device</span>
                      <button onClick={() => setHistory([])}>
                        Clear conversation
                      </button>
                    </div>
                  )}
                  {history.map((item, index) => (
                    <article
                      className="exchange"
                      key={item.id ?? `${index}-${item.question}`}
                    >
                      <div className="question-line">
                        <span className="avatar">Y</span>
                        <div>
                          <small>YOU ASKED</small>
                          <p>{item.question}</p>
                        </div>
                      </div>
                      <div className="answer-line">
                        <span className="answer-mark">p.</span>
                        <div className="answer-body">
                          <small>
                            {item.pending
                              ? "PAPERWISE IS THINKING"
                              : item.failed
                              ? "PAPERWISE COULDN'T ANSWER"
                              : "PAPERWISE FOUND"}
                          </small>
                          {item.pending
                            ? (
                              <div className="thinking">
                                <span className="pulse" />{" "}
                                Looking through your files…
                              </div>
                            )
                            : (
                              <>
                                <p className="answer-text">{item.answer}</p>
                                {item.citations.length > 0 && (
                                  <>
                                    <div className="sources-title">
                                      Sources{" "}
                                      <span>{item.citations.length}</span>
                                    </div>
                                    <div className="sources">
                                      {item.citations.map((citation) => (
                                        <details
                                          className="source-card"
                                          key={`${citation.document_id}-${citation.number}`}
                                        >
                                          <summary>
                                            <span className="source-number">
                                              {citation.number}
                                            </span>
                                            <span>
                                              {citation.filename}
                                              {citation.page_number
                                                ? ` · page ${citation.page_number}`
                                                : ""}
                                            </span>
                                            <span className="chevron">⌄</span>
                                          </summary>
                                          <p>{citation.passage}</p>
                                        </details>
                                      ))}
                                    </div>
                                  </>
                                )}
                              </>
                            )}
                        </div>
                      </div>
                    </article>
                  ))}
                </div>
              )}
          </div>

          <div className="ask-area">
            {error && (
              <div className="error-banner" role="alert">
                <span>{error}</span>
                <button
                  className="notice-close"
                  type="button"
                  aria-label="Dismiss error message"
                  onClick={() => setError("")}
                >
                  ×
                </button>
              </div>
            )}
            {uploadNotice && (
              <div
                className={`upload-notice ${uploadNotice.kind}`}
                role={uploadNotice.kind === "failure" ? "alert" : "status"}
                aria-live={uploadNotice.kind === "failure"
                  ? "assertive"
                  : "polite"}
              >
                <span className="upload-notice-icon" aria-hidden="true">
                  {uploadNotice.kind === "indexing"
                    ? <span className="notice-spinner" />
                    : uploadNotice.kind === "success"
                    ? (
                      "✓"
                    )
                    : (
                      "!"
                    )}
                </span>
                <span>{uploadNotice.message}</span>
                <button
                  className="notice-close"
                  type="button"
                  aria-label="Dismiss upload message"
                  onClick={() => setUploadNotice(null)}
                >
                  ×
                </button>
              </div>
            )}
            <form className="ask-box" onSubmit={ask}>
              <textarea
                aria-label="Ask your documents"
                rows={2}
                placeholder={hasReadyDocument
                  ? "Ask anything about your files…"
                  : documents.length
                  ? "Your files are still indexing…"
                  : "Add a document to get started…"}
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                disabled={!hasReadyDocument || loading}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    event.currentTarget.form?.requestSubmit();
                  }
                }}
              />
              <div className="ask-footer">
                <span>
                  Answers include source passages so you can check them.
                </span>
                <button
                  className="send-button"
                  aria-label="Send question"
                  disabled={!question.trim() || loading || !hasReadyDocument}
                >
                  {loading ? "…" : "↑"}
                </button>
              </div>
            </form>
            <div className="disclaimer">
              PaperWise can make mistakes. Check important details against the
              original files.
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
