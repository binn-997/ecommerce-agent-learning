"""Thin offline policy RAG demo with effective-date citations."""

from __future__ import annotations

import argparse
import asyncio
from datetime import date

from amazon_ai_platform.models import PolicyDocument
from amazon_ai_platform.rag import PolicyKnowledgeBase


DOCUMENTS = [
    PolicyDocument(
        document_id="listing-policy-de",
        version="2026.1",
        title="Amazon.de Listing-Regeln",
        text=(
            "Titel beschreiben das Produkt sachlich. Begriffe wie Guaranteed Best, "
            "Miracle oder unbelegte medizinische Aussagen sind gesperrt."
        ),
        effective_from=date(2026, 1, 1),
        marketplace="amazon.de",
        category="pet",
        language="de",
        access_scope="public",
        source_url="urn:synthetic:policy:listing-de:2026.1",
    )
]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    if not args.demo:
        raise SystemExit("Only the offline --demo composition is configured.")
    knowledge_base = PolicyKnowledgeBase()
    await knowledge_base.add_documents(DOCUMENTS)
    answer = await knowledge_base.answer(
        "Darf der Titel Guaranteed Best enthalten?",
        as_of=date(2026, 7, 16),
        marketplace="amazon.de",
        category="pet",
        scopes={"public"},
    )
    print(answer.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
