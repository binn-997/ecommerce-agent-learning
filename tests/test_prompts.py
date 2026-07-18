from __future__ import annotations

import json
from pathlib import Path

from amazon_ai_platform.listing_agent import ProductBrief
from amazon_ai_platform.prompts import (
    CaseOutput,
    GoldenCase,
    PromptRegistry,
    compare_evaluations,
    evaluate_prompt,
    listing_prompt,
)


FIXTURE = Path(__file__).parent / "fixtures" / "golden_listing_cases.json"
RULES = {
    "beste": "unbelegter Superlativ",
    "garantiert": "unbelegtes Garantieversprechen",
    "Nummer 1": "unbelegter Superlativ",
    "100%": "unbelegtes Garantieversprechen",
    "kostenlos": "preisbezogene Werbeaussage",
    "heilt": "medizinisches Heilversprechen",
    "Miracle": "medizinisches Heilversprechen",
}


def load_cases() -> tuple[list[GoldenCase], dict[str, CaseOutput]]:
    raw = json.loads(FIXTURE.read_text())
    cases: list[GoldenCase] = []
    outputs: dict[str, CaseOutput] = {}
    for item in raw:
        claim = item.get("forbidden_claim")
        brief = ProductBrief(
            sku=item["case_id"],
            product_name="Synthetisches Testprodukt",
            category=item["category"],
            material=item["material"],
            features=["pflegeleicht", "klar beschrieben", "synthetische Testgröße"],
            primary_keywords=[item["keyword"]],
            target_customer="Testhaushalte",
            manufacturer="Synthetic GmbH",
            eu_responsible_person="Synthetic GmbH, Berlin",
        )
        cases.append(
            GoldenCase(
                case_id=item["case_id"],
                category=item["category"],
                brief=brief,
                required_keywords=[item["keyword"]],
                expected_block_rules=[RULES[claim]] if claim else [],
                expected_citation_ids=[item["evidence"]],
            )
        )
        title = f"{item['keyword']} aus {item['material']} für synthetische Tests"
        if claim:
            title += f" {claim}"
        outputs[item["case_id"]] = CaseOutput(
            payload={
                "title": title,
                "item_highlight": (
                    f"{item['material']} für synthetische Vergleichs- und Suchtests"
                ),
                "bullets": [
                    f"Sachliche Eigenschaft {index} für den Test"
                    for index in range(1, 6)
                ],
                "backend_keywords": [item["keyword"]],
                "rationale": "Reproduzierbare synthetische Auswertung mit Quellenbezug.",
            },
            citation_ids=[item["evidence"]],
            human_preferred=True,
        )
    return cases, outputs


def test_prompt_registry_is_versioned_and_category_specific() -> None:
    registry = PromptRegistry()
    asset = listing_prompt("pet")
    registry.register(asset)
    assert registry.get("listing-de", "2.0.0", "pet") == asset
    assert asset.output_schema["properties"]["title"]["maxLength"] == 75
    assert asset.output_schema["properties"]["item_highlight"]["maxLength"] == 125


def test_forty_case_prompt_gates_are_reproducible() -> None:
    cases, outputs = load_cases()
    result = evaluate_prompt(listing_prompt("mixed"), cases, outputs)
    assert len(cases) == 40
    assert sum(case.category == "suit" for case in cases) == 20
    assert sum(case.category == "pet" for case in cases) == 20
    assert result.schema_pass_rate == 1
    assert result.hard_rule_pass_rate == 1
    assert result.block_misses == 0
    assert result.keyword_coverage == 1
    assert result.citation_accuracy == 1


def test_prompt_version_diff_identifies_regression() -> None:
    cases, outputs = load_cases()
    baseline = evaluate_prompt(listing_prompt("mixed"), cases, outputs)
    broken = dict(outputs)
    broken.pop("pet-01")
    candidate = evaluate_prompt(listing_prompt("mixed", version="2.1.0"), cases, broken)
    diff = compare_evaluations(baseline, candidate)
    assert diff["schema_pass_rate_delta"] < 0
    assert "pet-01" in candidate.failed_case_ids
