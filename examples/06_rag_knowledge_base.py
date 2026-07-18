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
        version="2026.2",
        title="Amazon.de Listing-Regeln",
        text=(
            "Ab 27. Juli 2026 haben Nicht-Medien-Titel höchstens 75 Zeichen inklusive "
            "Leerzeichen. Ein Item Highlight hat höchstens 125 Zeichen und nennt Material "
            "oder empfohlene Verwendung. Titel beschreiben das Produkt sachlich. "
            "Begriffe wie Guaranteed Best, "
            "Miracle oder unbelegte medizinische Aussagen sind gesperrt."
        ),
        effective_from=date(2026, 7, 27),
        marketplace="amazon.de",
        category="pet",
        language="de",
        access_scope="public",
        source_url="urn:synthetic:policy:listing-de:2026.2",
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
        "Wie lang dürfen Titel sein und was ist ein Item Highlight?",
        as_of=date(2026, 7, 27),
        marketplace="amazon.de",
        category="pet",
        scopes={"public"},
    )
    print(answer.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
