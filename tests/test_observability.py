from amazon_ai_platform.observability import safe_event, stable_hash


def test_log_allowlist_drops_prompt_tokens_and_buyer_pii() -> None:
    event = safe_event(
        trace_id="trace-1",
        seller_id_hash=stable_hash("seller"),
        operation="sync",
        authorization="Bearer secret",
        buyer_email="buyer@example.invalid",
        prompt="private prompt",
    )
    assert "trace-1" in event
    assert "secret" not in event
    assert "buyer@" not in event
    assert "private prompt" not in event
