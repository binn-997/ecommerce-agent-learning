"""Offline-first RAG pipeline. Run: python 06_rag_knowledge_base.py --demo.

The hash embedder exists only to make the entire retrieval pipeline runnable without
network or API keys. In production, replace it with an embedding endpoint and store
vectors in pgvector/Qdrant; do not judge semantic quality from the hash demo.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import math
import re
from dataclasses import dataclass
from typing import Protocol

from litellm import aembedding


@dataclass(frozen=True)
class Document:
    document_id: str
    title: str
    text: str


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    document_id: str
    title: str
    text: str


@dataclass(frozen=True)
class SearchResult:
    chunk: Chunk
    score: float


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    """Deterministic offline embedding for testing chunking/retrieval mechanics."""
    def __init__(self, dimensions: int = 256) -> None:
        self.dimensions = dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dimensions
            for token in re.findall(r"[\w-]+", text.lower()):
                index = int(hashlib.sha256(token.encode()).hexdigest(), 16) % self.dimensions
                vector[index] += 1.0
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / norm for value in vector])
        return vectors


class LiteLLMEmbedder:
    """Real embedding adapter; model examples: openai/text-embedding-3-small."""
    def __init__(self, model: str) -> None:
        self.model = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        response = await aembedding(model=self.model, input=texts, timeout=45)
        return [item["embedding"] for item in response.data]


def chunk_document(document: Document, *, max_chars: int = 420, overlap_chars: int = 80) -> list[Chunk]:
    """Split at paragraph boundaries when possible, preserving an overlap for context."""
    paragraphs = [item.strip() for item in document.text.split("\n") if item.strip()]
    chunks: list[Chunk] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n{paragraph}".strip()
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(Chunk(f"{document.document_id}:{len(chunks)}", document.document_id, document.title, current))
        current = f"{current[-overlap_chars:]}\n{paragraph}".strip() if current else paragraph
        while len(current) > max_chars:
            chunks.append(Chunk(f"{document.document_id}:{len(chunks)}", document.document_id, document.title, current[:max_chars]))
            current = current[max_chars - overlap_chars:]
    if current:
        chunks.append(Chunk(f"{document.document_id}:{len(chunks)}", document.document_id, document.title, current))
    return chunks


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


class InMemoryRAG:
    def __init__(self, embedder: Embedder) -> None:
        self.embedder = embedder
        self.chunks: list[Chunk] = []
        self.vectors: list[list[float]] = []

    async def add_documents(self, documents: list[Document]) -> None:
        new_chunks = [chunk for document in documents for chunk in chunk_document(document)]
        self.chunks.extend(new_chunks)
        self.vectors.extend(await self.embedder.embed([chunk.text for chunk in new_chunks]))

    async def search(self, question: str, *, top_k: int = 3, min_score: float = 0.15) -> list[SearchResult]:
        query_vector = (await self.embedder.embed([question]))[0]
        ranked = sorted((SearchResult(chunk, cosine(query_vector, vector)) for chunk, vector in zip(self.chunks, self.vectors)), key=lambda item: item.score, reverse=True)
        return [item for item in ranked[:top_k] if item.score >= min_score]

    async def answer_context(self, question: str) -> str:
        results = await self.search(question)
        if not results:
            return "未找到足够依据；请转人工或补充知识库。"
        return "\n\n".join(f"[{item.chunk.chunk_id} | {item.chunk.title} | score={item.score:.3f}]\n{item.chunk.text}" for item in results)


DOCS = [
    Document("return-policy", "德国站退货 SOP", "客户可在收到商品后 30 天内申请退货。\n对于因商品质量问题产生的退货，先收集订单号、图片和问题描述，再由人工客服判定退款或补发。\n不要承诺平台政策未明确支持的补偿。"),
    Document("listing-policy", "Listing 文案规则", "标题应描述产品本身，不使用 BEST、Guaranteed 或 Miracle 等绝对化营销词。\n没有检测报告或品牌授权时，不得写 medical、organic 或 certified 等无法证明的声明。"),
    Document("inventory-sop", "库存预警 SOP", "当可售天数低于 14 天时创建库存预警。\n补货数量必须同时参考日均销量、在途库存和供应商交期，并由运营人员人工确认。"),
]


async def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--demo", action="store_true"); parser.add_argument("--model", default="openai/text-embedding-3-small"); args = parser.parse_args()
    rag = InMemoryRAG(HashEmbedder() if args.demo else LiteLLMEmbedder(args.model))
    await rag.add_documents(DOCS)
    question = "宠物地毯的标题能否写 Guaranteed Best？"
    print("QUESTION:", question)
    print("CONTEXT WITH CITATIONS:\n", await rag.answer_context(question))


if __name__ == "__main__": asyncio.run(main())
