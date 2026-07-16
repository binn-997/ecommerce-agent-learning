from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

from amazon_ai_platform.models import PolicyDocument
from amazon_ai_platform.rag import (
    PolicyKnowledgeBase,
    RetrievalQuestion,
    chunk_document,
    evaluate_retrieval,
)


FIXTURES = Path(__file__).parent / "fixtures"


def documents() -> list[PolicyDocument]:
    common = {
        "effective_from": date(2026, 1, 1),
        "marketplace": "amazon.de",
        "category": "pet",
        "language": "de",
        "access_scope": "public",
    }
    return [
        PolicyDocument(
            document_id="listing-current",
            version="2",
            title="Listing",
            text="Guaranteed Best Titel Regel medizinische Aussage Miracle Werbung sachlicher Produkttitel unbelegte Garantie Hundeteppich absolute Aussage verboten Produkt sachlich beschreiben medizinische Heilung behaupten Garantie ohne Beleg",
            source_url="urn:synthetic:listing-current",
            **common,
        ),
        PolicyDocument(
            document_id="return-current",
            version="2",
            title="Return",
            text="Retoure Frist 30 Tage Rückgabe innerhalb Frist Bestellung prüfen Rückerstattung Freigabe Kunde manuell Bestellnummer Prozess Erstattung Entscheidung Rücksende-Frist",
            source_url="urn:synthetic:return-current",
            **common,
        ),
        PolicyDocument(
            document_id="gpsr-current",
            version="2",
            title="GPSR",
            text="GPSR Hersteller Metadaten verantwortliche Person EU Hersteller Kontakt Produkt Rückverfolgung Responsible Person Angaben Listing Produktsicherheit",
            source_url="urn:synthetic:gpsr-current",
            **common,
        ),
        PolicyDocument(
            document_id="inventory-private",
            version="1",
            title="Inventory SOP",
            text="Bestand Reichweite 14 Tage Nachbestellung Lieferzeit Bestandsrisiko Freigabe",
            source_url="urn:synthetic:inventory-private",
            access_scope="brand:pet",
            **{key: value for key, value in common.items() if key != "access_scope"},
        ),
        PolicyDocument(
            document_id="listing-expired",
            version="1",
            title="Old Listing",
            text="veraltete Sonderregel Hundeteppich Guaranteed Best",
            effective_to=date(2025, 12, 31),
            source_url="urn:synthetic:listing-expired",
            **common,
        ),
    ]


def test_paragraph_chunking_preserves_metadata() -> None:
    chunks = chunk_document(documents()[0], max_chars=80, overlap_chars=10)
    assert len(chunks) > 1
    assert all(chunk.version == "2" for chunk in chunks)
    assert all(chunk.source_url.startswith("urn:") for chunk in chunks)


def test_expired_and_unauthorized_documents_are_filtered() -> None:
    async def scenario():
        kb = PolicyKnowledgeBase()
        await kb.add_documents(documents())
        public = await kb.search(
            "Bestand Reichweite 14 Tage",
            as_of=date(2026, 7, 16),
            marketplace="amazon.de",
            category="pet",
            scopes={"public"},
            min_score=0.05,
        )
        private = await kb.search(
            "Bestand Reichweite 14 Tage",
            as_of=date(2026, 7, 16),
            marketplace="amazon.de",
            category="pet",
            scopes={"brand:pet"},
            min_score=0.05,
        )
        return public, private

    public, private = asyncio.run(scenario())
    assert all(hit.chunk.document_id != "inventory-private" for hit in public)
    assert private[0].chunk.document_id == "inventory-private"
    assert all(hit.chunk.document_id != "listing-expired" for hit in private)


def test_grounded_answer_contains_citations_or_refuses() -> None:
    async def scenario():
        kb = PolicyKnowledgeBase()
        await kb.add_documents(documents())
        answer = await kb.answer(
            "Guaranteed Best Titel Regel",
            as_of=date(2026, 7, 16),
            marketplace="amazon.de",
            category="pet",
            scopes={"public"},
        )
        refusal = await kb.answer(
            "Quantenphysik Galaxie",
            as_of=date(2026, 7, 16),
            marketplace="amazon.de",
            category="pet",
            scopes={"public"},
        )
        return answer, refusal

    answer, refusal = asyncio.run(scenario())
    assert answer.status == "answered"
    assert answer.citations[0].document_id == "listing-current"
    assert refusal.status == "insufficient_evidence"
    assert refusal.requires_human_review is True


def test_fifty_question_retrieval_acceptance_set() -> None:
    raw = json.loads((FIXTURES / "rag_questions.json").read_text())
    questions = [RetrievalQuestion.model_validate(item) for item in raw]

    async def scenario():
        kb = PolicyKnowledgeBase()
        await kb.add_documents(documents())
        return await evaluate_retrieval(
            kb,
            questions,
            as_of=date(2026, 7, 16),
            marketplace="amazon.de",
            category="pet",
            scopes={"public", "brand:pet"},
        )

    result = asyncio.run(scenario())
    assert len(questions) == 50
    assert sum(question.should_refuse for question in questions) == 15
    assert result.recall_at_5 >= 0.90
    assert result.refusal_accuracy >= 0.90
    assert result.expired_leakage_rate == 0
