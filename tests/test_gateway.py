from __future__ import annotations

import asyncio
import json

import httpx

from fastapi.testclient import TestClient

from amazon_ai_platform.llm_gateway import (
    AnthropicProvider,
    ChatCompletionRequest,
    DeepSeekChatProvider,
    Message,
    ModelRouter,
    OpenAIResponsesProvider,
    ProviderResult,
    RegisteredSchema,
    RouteTarget,
    create_app,
)


VALID_VARIANT = {
    "title": "Hundeteppich – Waschbare Schmutzfangmatte aus Mikrofaser",
    "item_highlight": "Mikrofaser für Hundehaushalte; waschbar und pflegeleicht",
    "bullets": [
        f"Eigenschaft {index} – sachliche Produktinformation" for index in range(1, 6)
    ],
    "backend_keywords": ["hundeteppich"],
    "rationale": "Diese Variante priorisiert Material und Pflegehinweise.",
}


class FakeProvider:
    def __init__(self, name: str, result: str | Exception):
        self.name, self.result = name, result

    async def complete(self, request, *, model, schema):
        assert schema is not None
        if isinstance(self.result, Exception):
            raise self.result
        return ProviderResult(
            content=self.result, model=model, prompt_tokens=10, completion_tokens=20
        )


def structured_request() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        messages=[Message(role="user", content="generate")],
        response_format=RegisteredSchema(name="listing_variant"),
    )


def test_registered_schema_is_strict_for_provider_output() -> None:
    schema = ModelRouter._schema(structured_request())
    assert schema is not None
    assert schema["additionalProperties"] is False
    assert schema["required"] == list(schema["properties"])


def test_openai_provider_uses_responses_api_and_text_format() -> None:
    async def scenario() -> ProviderResult:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/responses"
            body = json.loads(request.content)
            assert body["input"] == [{"role": "user", "content": "generate"}]
            assert body["store"] is False
            assert body["max_output_tokens"] == 1500
            assert body["text"]["format"]["type"] == "json_schema"
            assert body["text"]["format"]["strict"] is True
            return httpx.Response(
                200,
                json={
                    "model": "gpt-5.6-terra",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(VALID_VARIANT),
                                }
                            ],
                        }
                    ],
                    "usage": {"input_tokens": 11, "output_tokens": 22},
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            provider = OpenAIResponsesProvider("secret", http)
            schema = ModelRouter._schema(structured_request())
            return await provider.complete(
                structured_request(), model="gpt-5.6-terra", schema=schema
            )

    result = asyncio.run(scenario())
    assert json.loads(result.content) == VALID_VARIANT
    assert (result.prompt_tokens, result.completion_tokens) == (11, 22)


def test_anthropic_provider_uses_native_output_config() -> None:
    async def scenario() -> ProviderResult:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/messages"
            body = json.loads(request.content)
            assert body["output_config"]["format"]["type"] == "json_schema"
            assert (
                body["output_config"]["format"]["schema"]["additionalProperties"]
                is False
            )
            assert "Return only JSON" not in body["system"]
            return httpx.Response(
                200,
                json={
                    "model": "claude-sonnet-latest",
                    "content": [{"type": "text", "text": json.dumps(VALID_VARIANT)}],
                    "usage": {"input_tokens": 12, "output_tokens": 24},
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            provider = AnthropicProvider("secret", http)
            schema = ModelRouter._schema(structured_request())
            return await provider.complete(
                structured_request(), model="claude-sonnet-latest", schema=schema
            )

    result = asyncio.run(scenario())
    assert json.loads(result.content) == VALID_VARIANT
    assert (result.prompt_tokens, result.completion_tokens) == (12, 24)


def test_deepseek_provider_uses_json_object_mode() -> None:
    async def scenario() -> ProviderResult:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/chat/completions"
            body = json.loads(request.content)
            assert body["response_format"] == {"type": "json_object"}
            assert body["messages"][0]["role"] == "system"
            assert "JSON Schema" in body["messages"][0]["content"]
            return httpx.Response(
                200,
                json={
                    "model": "deepseek-v4-flash",
                    "choices": [{"message": {"content": json.dumps(VALID_VARIANT)}}],
                    "usage": {"prompt_tokens": 13, "completion_tokens": 26},
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            provider = DeepSeekChatProvider("secret", http)
            schema = ModelRouter._schema(structured_request())
            return await provider.complete(
                structured_request(), model="deepseek-v4-flash", schema=schema
            )

    result = asyncio.run(scenario())
    assert json.loads(result.content) == VALID_VARIANT
    assert (result.prompt_tokens, result.completion_tokens) == (13, 26)


def test_router_falls_back_and_validates_pydantic_schema() -> None:
    from amazon_ai_platform.llm_gateway import ProviderUnavailable

    primary = FakeProvider("anthropic", ProviderUnavailable("temporary outage"))
    fallback = FakeProvider("deepseek", json.dumps(VALID_VARIANT))
    router = ModelRouter(
        {
            "listing-quality": [
                RouteTarget(primary, "claude"),
                RouteTarget(fallback, "deepseek-chat"),
            ]
        }
    )
    request = ChatCompletionRequest(
        messages=[Message(role="user", content="generate")],
        response_format=RegisteredSchema(name="listing_variant"),
    )
    result, provider, fallback_count = asyncio.run(router.complete(request))
    assert provider == "deepseek"
    assert fallback_count == 1
    content = json.loads(result.content)
    assert content["title"].startswith("Hundeteppich")
    assert content["item_highlight"].startswith("Mikrofaser")


def test_invalid_structured_output_also_triggers_fallback() -> None:
    legacy_one_part_output = dict(VALID_VARIANT)
    legacy_one_part_output.pop("item_highlight")
    invalid = FakeProvider("anthropic", json.dumps(legacy_one_part_output))
    fallback = FakeProvider("openai", json.dumps(VALID_VARIANT))
    router = ModelRouter(
        {
            "listing-quality": [
                RouteTarget(invalid, "claude"),
                RouteTarget(fallback, "gpt"),
            ]
        }
    )
    request = ChatCompletionRequest(
        messages=[Message(role="user", content="generate")],
        response_format=RegisteredSchema(name="listing_variant"),
    )
    _, provider, count = asyncio.run(router.complete(request))
    assert (provider, count) == ("openai", 1)


def test_openai_compatible_http_endpoint_returns_traceable_metadata() -> None:
    provider = FakeProvider("deepseek", json.dumps(VALID_VARIANT))
    app = create_app(
        ModelRouter({"listing-quality": [RouteTarget(provider, "deepseek-chat")]})
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            headers={"x-request-id": "interview-001"},
            json={
                "model": "listing-quality",
                "messages": [{"role": "user", "content": "generate"}],
                "response_format": {"type": "json_schema", "name": "listing_variant"},
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "chatcmpl-interview-001"
    assert body["provider"] == "deepseek"
    assert body["usage"]["total_tokens"] == 30


def test_all_providers_fail_with_safe_503_without_secret_or_stack() -> None:
    from amazon_ai_platform.llm_gateway import ProviderUnavailable

    provider = FakeProvider("anthropic", ProviderUnavailable("secret-api-key-value"))
    app = create_app(
        ModelRouter({"listing-quality": [RouteTarget(provider, "claude")]})
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "generate"}],
                "response_format": {"type": "json_schema", "name": "listing_variant"},
            },
        )
    assert response.status_code == 503
    assert "secret-api-key-value" not in response.text
    assert "traceback" not in response.text.casefold()


def test_registered_alias_without_provider_returns_safe_503() -> None:
    app = create_app(ModelRouter({"listing-quality": []}))
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "listing-quality",
                "messages": [{"role": "user", "content": "synthetic"}],
            },
        )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "model_unavailable"


def test_authentication_error_does_not_fall_back() -> None:
    from amazon_ai_platform.llm_gateway import ProviderEscalation

    primary = FakeProvider("anthropic", ProviderEscalation("operator review"))
    fallback = FakeProvider("openai", json.dumps(VALID_VARIANT))
    router = ModelRouter(
        {
            "listing-quality": [
                RouteTarget(primary, "claude"),
                RouteTarget(fallback, "gpt"),
            ]
        }
    )
    request = ChatCompletionRequest(
        messages=[Message(role="user", content="generate")],
        response_format=RegisteredSchema(name="listing_variant"),
    )
    try:
        asyncio.run(router.complete(request))
        raise AssertionError("ProviderEscalation not raised")
    except ProviderEscalation:
        assert router.metrics.provider_failures == 1


def test_provider_timeout_falls_back_and_metrics_are_exported() -> None:
    primary = FakeProvider("anthropic", httpx.ReadTimeout("synthetic timeout"))
    fallback = FakeProvider("deepseek", json.dumps(VALID_VARIANT))
    router = ModelRouter(
        {
            "listing-quality": [
                RouteTarget(primary, "claude"),
                RouteTarget(fallback, "deepseek"),
            ]
        }
    )
    app = create_app(router)
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "generate"}],
                "response_format": {"type": "json_schema", "name": "listing_variant"},
            },
        )
        metrics = client.get("/metrics")
    assert response.status_code == 200
    assert "amazon_ai_gateway_fallbacks_total 1" in metrics.text
