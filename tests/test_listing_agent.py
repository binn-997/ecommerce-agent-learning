from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from amazon_ai_platform.listing_agent import (
    CompetitorEvidence,
    DeterministicGermanGenerator,
    GermanMarketplaceCompliance,
    InMemoryCompetitorSource,
    ListingOptimizationAgent,
    ProductBrief,
)
from amazon_ai_platform.models import ListingVariant


def brief() -> ProductBrief:
    return ProductBrief(
        sku="DE-PET-001",
        product_name="Schmutzfangmatte für Haustiere",
        category="Haustierbedarf",
        material="Mikrofaser",
        features=["waschbar", "saugfähig", "rutschhemmend", "weich", "pflegeleicht"],
        primary_keywords=["Hundeteppich"],
        target_customer="Hundehaushalte",
        manufacturer="Demo GmbH",
        eu_responsible_person="Demo GmbH, Berlin",
    )


def test_graph_generates_three_five_bullet_variants_with_sources() -> None:
    source = InMemoryCompetitorSource(
        [
            CompetitorEvidence(
                source_id="spapi:B0TEST",
                asin="B0TEST",
                observed_at="2026-07-16T00:00:00Z",
                title="Test",
                bullets=["A"],
                keywords=["Hundeteppich"],
            )
        ]
    )
    agent = ListingOptimizationAgent(source, DeterministicGermanGenerator())
    result = asyncio.run(agent.run(brief(), request_id="trace-1"))
    assert len(result.variants) == 3
    assert all(len(variant.bullets) == 5 for variant in result.variants)
    assert all(len(variant.title) <= 75 for variant in result.variants)
    assert all(10 <= len(variant.item_highlight) <= 125 for variant in result.variants)
    assert result.source_ids == ["spapi:B0TEST"]
    assert result.requires_human_review is True


def test_german_compliance_blocks_unsubstantiated_claims() -> None:
    variant = ListingVariant(
        title="Der beste Hundeteppich mit garantiertem Ergebnis",
        item_highlight="Mikrofaser für Hundehaushalte und garantiert beste Ergebnisse",
        bullets=[f"Sachliche Eigenschaft {index}" for index in range(5)],
        rationale="Absichtlich ungültige Werbeaussage für den Regeltest.",
    )
    issues = GermanMarketplaceCompliance.check(brief(), [variant])
    assert any(
        issue.severity == "block" and "Superlativ" in issue.rule for issue in issues
    )
    assert any(
        issue.severity == "block" and "Garantie" in issue.rule for issue in issues
    )
    assert any(issue.field.endswith("item_highlight") for issue in issues)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "T" * 76),
        ("item_highlight", "H" * 126),
    ],
)
def test_new_title_parts_reject_content_over_character_limits(
    field: str, value: str
) -> None:
    payload = {
        "title": "Hundeteppich aus Mikrofaser",
        "item_highlight": "Waschbare Mikrofaser für Hundehaushalte",
        "bullets": [f"Sachliche Eigenschaft {index}" for index in range(5)],
        "rationale": "Synthetischer Test für die neuen Zeichenlimits.",
        field: value,
    }
    with pytest.raises(ValidationError):
        ListingVariant.model_validate(payload)


def test_request_checkpoint_is_idempotent_and_human_review_never_publishes() -> None:
    source = InMemoryCompetitorSource([])
    agent = ListingOptimizationAgent(source, DeterministicGermanGenerator())

    async def scenario():
        first = await agent.run(brief(), request_id="checkpoint-1")
        second = await agent.run(brief(), request_id="checkpoint-1")
        review = await agent.review(
            "checkpoint-1",
            decision="approve",
            reviewer_id="synthetic-reviewer",
            note="draft approved for later manual publishing",
        )
        return first, second, review

    first, second, review = asyncio.run(scenario())
    assert first == second
    assert first.fact_sources
    assert review.publishes_listing is False
    assert set(agent.node_latencies_ms) == {
        "read_competitor_data",
        "generate_three_versions",
        "compliance_check",
    }
    assert agent.human_rejection_rate == 0
