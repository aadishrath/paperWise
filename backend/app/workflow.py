from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING

from app.citation_validation import InvalidCitations, cited_passages
from app.ollama import OllamaClient, OllamaError

if TYPE_CHECKING:
    from app.database import Database


class Stage(Enum):
    RETRIEVE = auto()
    GENERATE = auto()
    COMPLETE = auto()


@dataclass
class AnswerState:
    question: str
    stage: Stage = Stage.RETRIEVE
    passages: list[dict] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    answer: str = ""
    abstained: bool = False


class AnswerWorkflow:
    """Small explicit state machine: retrieve evidence, then generate a grounded answer."""

    def __init__(
        self,
        database: Database,
        ollama: OllamaClient,
        min_relevance_score: float = 0.28,
        embedding_dimensions: int = 768,
    ):
        self.database = database
        self.ollama = ollama
        self.min_relevance_score = min_relevance_score
        self.embedding_dimensions = embedding_dimensions

    async def run(self, question: str) -> AnswerState:
        state = AnswerState(question=question)
        while state.stage is not Stage.COMPLETE:
            if state.stage is Stage.RETRIEVE:
                vectors = await self.ollama.embed([state.question])
                if not vectors or not vectors[0]:
                    raise OllamaError(
                        "The embedding model returned no vector for the question."
                    )
                if len(vectors[0]) != self.embedding_dimensions:
                    raise OllamaError(
                        f"The embedding model returned {len(vectors[0])} dimensions; PaperWise is configured for {self.embedding_dimensions}."
                    )
                state.passages = self.database.hybrid_search(vectors[0], state.question)
                best_semantic_score = max(
                    (item["semantic_score"] for item in state.passages), default=0.0
                )
                best_keyword_score = max(
                    (item["keyword_score"] for item in state.passages), default=0.0
                )
                if not state.passages or (
                    best_semantic_score < self.min_relevance_score
                    and best_keyword_score <= 0
                ):
                    state.answer = "I couldn't find enough relevant information in your documents to answer that. Try a more specific question or add another source."
                    state.abstained = True
                    state.stage = Stage.COMPLETE
                else:
                    state.stage = Stage.GENERATE
            elif state.stage is Stage.GENERATE:
                generated = await self.ollama.answer(state.question, state.passages)
                try:
                    state.citations = cited_passages(generated, state.passages)
                    state.answer = generated
                except InvalidCitations:
                    state.answer = "I couldn't provide a grounded answer with verifiable citations. Try rephrasing your question."
                    state.abstained = True
                state.stage = Stage.COMPLETE
        return state
