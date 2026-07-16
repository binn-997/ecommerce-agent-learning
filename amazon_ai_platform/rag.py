"""Offline-testable policy RAG with version, effective-date and scope enforcement."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from pydantic import BaseModel, Field

from .models import Citation, GroundedAnswer, PolicyDocument


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    """Deterministic lexical embedder for mechanics and offline regression tests."""

    def __init__(self, dimensions: int = 512) -> None:
        self.dimensions = dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dimensions
            for token in re.findall(r"[\wäöüß-]+", text.casefold()):
                index = int(hashlib.sha256(token.encode()).hexdigest(), 16) % self.dimensions
                vector[index] += 1
            norm = math.sqrt(sum(value * value for value in vector)) or 1
            vectors.append([value / norm for value in vector])
        return vectors


class PolicyChunk(BaseModel):
    chunk_id: str
    document_id: str
    version: str
    text: str
    marketplace: str
    category: str
    language: str
    access_scope: str
    effective_from: date
    effective_to: date | None
    source_url: str


@dataclass(frozen=True)
class SearchHit:
    chunk: PolicyChunk
    score: float


def chunk_document(
    document: PolicyDocument, *, max_chars: int = 600, overlap_chars: int = 80
) -> list[PolicyChunk]:
    """Prefer paragraph boundaries, only splitting a paragraph when unavoidable."""
    if max_chars <= overlap_chars or overlap_chars < 0:
        raise ValueError("max_chars must exceed non-negative overlap_chars")
    paragraphs = [part.strip() for part in document.text.split("\n") if part.strip()]
    texts: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n{paragraph}".strip()
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            texts.append(current)
            current = f"{current[-overlap_chars:]}\n{paragraph}".strip()
        else:
            current = paragraph
        while len(current) > max_chars:
            texts.append(current[:max_chars])
            current = current[max_chars - overlap_chars :]
    if current:
        texts.append(current)
    return [
        PolicyChunk(
            chunk_id=f"{document.document_id}:{document.version}:{index}",
            document_id=document.document_id,
            version=document.version,
            text=text,
            marketplace=document.marketplace,
            category=document.category,
            language=document.language,
            access_scope=document.access_scope,
            effective_from=document.effective_from,
            effective_to=document.effective_to,
            source_url=document.source_url,
        )
        for index, text in enumerate(texts)
    ]


class PolicyKnowledgeBase:
    def __init__(self, embedder: Embedder | None = None) -> None:
        self.embedder = embedder or HashEmbedder()
        self.chunks: list[PolicyChunk] = []
        self.vectors: list[list[float]] = []

    async def add_documents(self, documents: list[PolicyDocument]) -> None:
        new_chunks = [chunk for document in documents for chunk in chunk_document(document)]
        identities = {(chunk.document_id, chunk.version, chunk.chunk_id) for chunk in self.chunks}
        new_chunks = [
            chunk
            for chunk in new_chunks
            if (chunk.document_id, chunk.version, chunk.chunk_id) not in identities
        ]
        self.chunks.extend(new_chunks)
        self.vectors.extend(await self.embedder.embed([chunk.text for chunk in new_chunks]))

    async def search(
        self,
        question: str,
        *,
        as_of: date,
        marketplace: str,
        category: str,
        scopes: set[str],
        language: str = "de",
        top_k: int = 5,
        min_score: float = 0.20,
    ) -> list[SearchHit]:
        query = (await self.embedder.embed([question]))[0]
        hits: list[SearchHit] = []
        for chunk, vector in zip(self.chunks, self.vectors, strict=True):
            active = chunk.effective_from <= as_of and (
                chunk.effective_to is None or as_of <= chunk.effective_to
            )
            allowed = chunk.access_scope in scopes or chunk.access_scope == "public"
            matches = (
                chunk.marketplace in {marketplace, "all"}
                and chunk.category in {category, "all"}
                and chunk.language == language
            )
            if active and allowed and matches:
                score = sum(left * right for left, right in zip(query, vector, strict=True))
                if score >= min_score:
                    hits.append(SearchHit(chunk, score))
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:top_k]

    async def answer(
        self,
        question: str,
        *,
        as_of: date,
        marketplace: str,
        category: str,
        scopes: set[str],
    ) -> GroundedAnswer:
        hits = await self.search(
            question,
            as_of=as_of,
            marketplace=marketplace,
            category=category,
            scopes=scopes,
        )
        if not hits:
            return GroundedAnswer(
                status="insufficient_evidence",
                answer="Keine ausreichende, aktuell gültige Evidenz gefunden; bitte menschlich prüfen.",
                requires_human_review=True,
            )
        citations = [
            Citation(
                chunk_id=hit.chunk.chunk_id,
                document_id=hit.chunk.document_id,
                version=hit.chunk.version,
                source_url=hit.chunk.source_url,
                score=hit.score,
            )
            for hit in hits
        ]
        context = "\n\n".join(hit.chunk.text for hit in hits)
        return GroundedAnswer(
            status="answered",
            answer=context,
            citations=citations,
            requires_human_review=False,
        )


class RetrievalQuestion(BaseModel):
    question_id: str
    question: str
    relevant_document_ids: list[str] = Field(default_factory=list)
    should_refuse: bool = False


class RetrievalEvaluation(BaseModel):
    total: int
    recall_at_5: float
    mrr: float
    citation_accuracy: float
    refusal_accuracy: float
    expired_leakage_rate: float


async def evaluate_retrieval(
    knowledge_base: PolicyKnowledgeBase,
    questions: list[RetrievalQuestion],
    *,
    as_of: date,
    marketplace: str,
    category: str,
    scopes: set[str],
) -> RetrievalEvaluation:
    recalled = 0
    reciprocal_ranks = 0.0
    correct_citations = 0
    citation_count = 0
    refusal_correct = 0
    expired_hits = 0
    total_hits = 0
    for question in questions:
        hits = await knowledge_base.search(
            question.question,
            as_of=as_of,
            marketplace=marketplace,
            category=category,
            scopes=scopes,
            top_k=5,
        )
        ids = [hit.chunk.document_id for hit in hits]
        relevant = set(question.relevant_document_ids)
        if relevant.intersection(ids):
            recalled += 1
            reciprocal_ranks += 1 / min(ids.index(item) + 1 for item in relevant if item in ids)
        if question.should_refuse == (not hits):
            refusal_correct += 1
        citation_count += len(ids)
        correct_citations += sum(item in relevant for item in ids)
        total_hits += len(hits)
        expired_hits += sum(
            hit.chunk.effective_to is not None and hit.chunk.effective_to < as_of for hit in hits
        )
    answerable = sum(not question.should_refuse for question in questions) or 1
    return RetrievalEvaluation(
        total=len(questions),
        recall_at_5=recalled / answerable,
        mrr=reciprocal_ranks / answerable,
        citation_accuracy=correct_citations / citation_count if citation_count else 1,
        refusal_accuracy=refusal_correct / len(questions) if questions else 1,
        expired_leakage_rate=expired_hits / total_hits if total_hits else 0,
    )
