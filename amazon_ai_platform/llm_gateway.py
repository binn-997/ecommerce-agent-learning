"""FastAPI multi-model gateway with validated outputs and provider failover."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections.abc import Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, ValidationError

from .models import ListingVariant
from .telemetry import configure_telemetry


TRACER = configure_telemetry("amazon-ai-llm-gateway")


class GatewayError(RuntimeError):
    pass


class ProviderUnavailable(GatewayError):
    pass


class ProviderEscalation(GatewayError):
    """Authentication, authorization and quota errors require human intervention."""


@dataclass
class GatewayMetrics:
    requests: int = 0
    provider_failures: int = 0
    fallbacks: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0
    latencies_ms: list[int] = field(default_factory=list)

    def prometheus(self) -> str:
        ordered = sorted(self.latencies_ms)
        p95 = ordered[max(0, int(len(ordered) * 0.95) - 1)] if ordered else 0
        values = {
            "amazon_ai_gateway_requests_total": self.requests,
            "amazon_ai_gateway_provider_failures_total": self.provider_failures,
            "amazon_ai_gateway_fallbacks_total": self.fallbacks,
            "amazon_ai_gateway_prompt_tokens_total": self.prompt_tokens,
            "amazon_ai_gateway_completion_tokens_total": self.completion_tokens,
            "amazon_ai_gateway_estimated_cost_usd_total": round(
                self.estimated_cost_usd, 8
            ),
            "amazon_ai_gateway_latency_p95_ms": p95,
        }
        return (
            "\n".join(
                f"# TYPE {name} gauge\n{name} {value}" for name, value in values.items()
            )
            + "\n"
        )


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=30_000)


class RegisteredSchema(BaseModel):
    """Only server-reviewed schemas are allowed; callers cannot inject arbitrary schemas."""

    type: Literal["json_schema"] = "json_schema"
    name: Literal["listing_variant"]


class ChatCompletionRequest(BaseModel):
    model: str = Field(default="listing-quality", max_length=100)
    messages: list[Message] = Field(min_length=1, max_length=30)
    temperature: float = Field(default=0.2, ge=0, le=1)
    max_tokens: int = Field(default=1500, ge=64, le=8000)
    response_format: RegisteredSchema | None = None


class ChoiceMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


class Choice(BaseModel):
    index: int = 0
    message: ChoiceMessage
    finish_reason: str = "stop"


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    provider: str
    choices: list[Choice]
    usage: Usage
    latency_ms: int
    fallback_count: int


@dataclass(frozen=True)
class ProviderResult:
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMProvider(Protocol):
    name: str

    async def complete(
        self,
        request: ChatCompletionRequest,
        *,
        model: str,
        schema: dict[str, Any] | None,
    ) -> ProviderResult: ...


def _strict_json_schema(value: Any) -> Any:
    """Adapt Pydantic JSON Schema to strict provider output requirements."""
    if isinstance(value, list):
        return [_strict_json_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    strict = {key: _strict_json_schema(item) for key, item in value.items()}
    properties = strict.get("properties")
    if strict.get("type") == "object" and isinstance(properties, dict):
        strict["additionalProperties"] = False
        strict["required"] = list(properties)
    return strict


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, http: httpx.AsyncClient) -> None:
        self.api_key, self.http = api_key, http

    async def complete(
        self,
        request: ChatCompletionRequest,
        *,
        model: str,
        schema: dict[str, Any] | None,
    ) -> ProviderResult:
        system_parts = [m.content for m in request.messages if m.role == "system"]
        messages = [m.model_dump() for m in request.messages if m.role != "system"]
        payload: dict[str, Any] = {
            "model": model,
            "system": "\n\n".join(system_parts),
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if schema:
            payload["output_config"] = {
                "format": {"type": "json_schema", "schema": schema}
            }
        response = await self.http.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        )
        if response.status_code in {401, 402, 403, 429}:
            raise ProviderEscalation(
                f"Anthropic requires operator review (HTTP {response.status_code})"
            )
        if response.status_code >= 400:
            raise ProviderUnavailable(f"Anthropic HTTP {response.status_code}")
        try:
            body = response.json()
            text_blocks = [
                part.get("text", "")
                for part in body.get("content", [])
                if part.get("type") == "text"
            ]
            usage = body.get("usage", {})
        except (ValueError, AttributeError, TypeError) as exc:
            raise ProviderUnavailable("Anthropic returned an invalid response") from exc
        return ProviderResult(
            content="".join(text_blocks),
            model=str(body.get("model", model)),
            prompt_tokens=int(usage.get("input_tokens", 0)),
            completion_tokens=int(usage.get("output_tokens", 0)),
        )


class OpenAIResponsesProvider:
    name = "openai"

    def __init__(self, api_key: str, http: httpx.AsyncClient) -> None:
        self.api_key, self.http = api_key, http

    async def complete(
        self,
        request: ChatCompletionRequest,
        *,
        model: str,
        schema: dict[str, Any] | None,
    ) -> ProviderResult:
        payload: dict[str, Any] = {
            "model": model,
            "input": [message.model_dump() for message in request.messages],
            "max_output_tokens": request.max_tokens,
            "store": False,
        }
        if schema:
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "listing_variant",
                    "strict": True,
                    "schema": schema,
                }
            }
        response = await self.http.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
        )
        if response.status_code in {401, 402, 403, 429}:
            raise ProviderEscalation(
                f"OpenAI requires operator review (HTTP {response.status_code})"
            )
        if response.status_code >= 400:
            raise ProviderUnavailable(f"OpenAI HTTP {response.status_code}")
        try:
            body = response.json()
            usage = body.get("usage", {})
            content = "".join(
                str(part.get("text", ""))
                for item in body.get("output", [])
                if item.get("type") == "message"
                for part in item.get("content", [])
                if part.get("type") == "output_text"
            )
            if not content:
                raise ValueError("response contained no output_text")
            return ProviderResult(
                content=content,
                model=str(body.get("model", model)),
                prompt_tokens=int(usage.get("input_tokens", 0)),
                completion_tokens=int(usage.get("output_tokens", 0)),
            )
        except (ValueError, TypeError, AttributeError) as exc:
            raise ProviderUnavailable("OpenAI returned an invalid response") from exc


class DeepSeekChatProvider:
    name = "deepseek"

    def __init__(self, api_key: str, http: httpx.AsyncClient) -> None:
        self.api_key, self.http = api_key, http

    async def complete(
        self,
        request: ChatCompletionRequest,
        *,
        model: str,
        schema: dict[str, Any] | None,
    ) -> ProviderResult:
        messages = [message.model_dump() for message in request.messages]
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if schema:
            payload["messages"] = [
                {
                    "role": "system",
                    "content": (
                        "Return only one valid JSON object matching this JSON Schema: "
                        + json.dumps(schema, ensure_ascii=False)
                    ),
                },
                *messages,
            ]
            payload["response_format"] = {"type": "json_object"}
        response = await self.http.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
        )
        if response.status_code in {401, 402, 403, 429}:
            raise ProviderEscalation(
                f"DeepSeek requires operator review (HTTP {response.status_code})"
            )
        if response.status_code >= 400:
            raise ProviderUnavailable(f"DeepSeek HTTP {response.status_code}")
        try:
            body = response.json()
            usage = body.get("usage", {})
            return ProviderResult(
                content=str(body["choices"][0]["message"].get("content", "")),
                model=str(body.get("model", model)),
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
            )
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise ProviderUnavailable("DeepSeek returned an invalid response") from exc


@dataclass
class CircuitState:
    failures: int = 0
    opened_at: float = 0.0


@dataclass(frozen=True)
class RouteTarget:
    provider: LLMProvider
    model: str


class ModelRouter:
    """Routes aliases through an ordered chain with basic circuit breaking."""

    def __init__(
        self,
        routes: dict[str, Sequence[RouteTarget]],
        *,
        max_concurrency: int = 50,
        failure_threshold: int = 3,
        recovery_seconds: float = 30,
        metrics: GatewayMetrics | None = None,
        input_cost_per_million: float = 0,
        output_cost_per_million: float = 0,
    ) -> None:
        self.routes = routes
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self.circuits: dict[str, CircuitState] = {}
        self.metrics = metrics or GatewayMetrics()
        self.input_cost_per_million = input_cost_per_million
        self.output_cost_per_million = output_cost_per_million

    def _available(self, provider_name: str) -> bool:
        state = self.circuits.setdefault(provider_name, CircuitState())
        if state.failures < self.failure_threshold:
            return True
        if time.monotonic() - state.opened_at >= self.recovery_seconds:
            state.failures = self.failure_threshold - 1  # half-open probe
            return True
        return False

    def _record_failure(self, provider_name: str) -> None:
        state = self.circuits.setdefault(provider_name, CircuitState())
        state.failures += 1
        if state.failures >= self.failure_threshold:
            state.opened_at = time.monotonic()

    def _record_success(self, provider_name: str) -> None:
        self.circuits[provider_name] = CircuitState()

    @staticmethod
    def _schema(request: ChatCompletionRequest) -> dict[str, Any] | None:
        if request.response_format is None:
            return None
        if request.response_format.name == "listing_variant":
            return _strict_json_schema(ListingVariant.model_json_schema())
        raise GatewayError("unregistered output schema")

    @staticmethod
    def _validate(content: str, request: ChatCompletionRequest) -> str:
        if request.response_format is None:
            return content
        try:
            data = json.loads(content)
            model = ListingVariant.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ProviderUnavailable(
                f"provider returned invalid structured output: {exc}"
            ) from exc
        return model.model_dump_json()

    async def complete(
        self, request: ChatCompletionRequest
    ) -> tuple[ProviderResult, str, int]:
        targets = self.routes.get(request.model)
        if targets is None:
            raise GatewayError(f"unknown model alias: {request.model}")
        if not targets:
            raise ProviderUnavailable(
                f"no providers configured for alias: {request.model}"
            )
        failures: list[str] = []
        async with self.semaphore:
            for fallback_count, target in enumerate(targets):
                if not self._available(target.provider.name):
                    failures.append(f"{target.provider.name}: circuit open")
                    continue
                try:
                    result = await target.provider.complete(
                        request, model=target.model, schema=self._schema(request)
                    )
                    validated = self._validate(result.content, request)
                    self._record_success(target.provider.name)
                    self.metrics.fallbacks += fallback_count
                    self.metrics.prompt_tokens += result.prompt_tokens
                    self.metrics.completion_tokens += result.completion_tokens
                    self.metrics.estimated_cost_usd += (
                        result.prompt_tokens * self.input_cost_per_million
                        + result.completion_tokens * self.output_cost_per_million
                    ) / 1_000_000
                    return (
                        ProviderResult(
                            content=validated,
                            model=result.model,
                            prompt_tokens=result.prompt_tokens,
                            completion_tokens=result.completion_tokens,
                        ),
                        target.provider.name,
                        fallback_count,
                    )
                except ProviderEscalation:
                    self.metrics.provider_failures += 1
                    raise
                except (
                    ProviderUnavailable,
                    httpx.HTTPError,
                    asyncio.TimeoutError,
                ) as exc:
                    self._record_failure(target.provider.name)
                    self.metrics.provider_failures += 1
                    failures.append(f"{target.provider.name}: {str(exc)[:120]}")
        raise ProviderUnavailable("all providers failed; " + "; ".join(failures))

    async def close(self) -> None:
        """Close shared provider transports exactly once during application shutdown."""
        closed: set[int] = set()
        for targets in self.routes.values():
            for target in targets:
                http = getattr(target.provider, "http", None)
                if http is not None and id(http) not in closed:
                    closed.add(id(http))
                    await http.aclose()


def create_app(router: ModelRouter) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await router.close()

    app = FastAPI(
        title="Amazon AI Platform LLM Gateway", version="1.0.0", lifespan=lifespan
    )
    app.state.router = router

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "routes": sorted(router.routes)}

    @app.get("/metrics", response_class=PlainTextResponse)
    async def metrics() -> PlainTextResponse:
        return PlainTextResponse(router.metrics.prometheus())

    @app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
    async def chat_completion(
        payload: ChatCompletionRequest, raw_request: Request
    ) -> ChatCompletionResponse:
        supplied_id = raw_request.headers.get("x-request-id", "")[:128]
        request_id = (
            supplied_id
            if supplied_id.replace("-", "").replace("_", "").isalnum()
            else str(uuid.uuid4())
        )
        started = time.perf_counter()
        router.metrics.requests += 1
        with TRACER.start_as_current_span("chat_completion") as span:
            span.set_attribute("request.id", request_id)
            span.set_attribute("model.alias", payload.model)
            try:
                result, provider, fallback_count = await router.complete(payload)
            except (GatewayError, ProviderEscalation) as exc:
                span.set_attribute("outcome", "failed")
                status = 400 if "unknown model" in str(exc) else 503
                raise HTTPException(
                    status_code=status,
                    detail={"code": "model_unavailable", "request_id": request_id},
                ) from exc
            span.set_attribute("provider", provider)
            span.set_attribute("fallback.count", fallback_count)
        total = result.prompt_tokens + result.completion_tokens
        latency_ms = int((time.perf_counter() - started) * 1000)
        router.metrics.latencies_ms.append(latency_ms)
        return ChatCompletionResponse(
            id=f"chatcmpl-{request_id}",
            created=int(time.time()),
            model=result.model,
            provider=provider,
            choices=[Choice(message=ChoiceMessage(content=result.content))],
            usage=Usage(
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                total_tokens=total,
            ),
            latency_ms=latency_ms,
            fallback_count=fallback_count,
        )

    return app


def app_from_environment() -> FastAPI:
    http = httpx.AsyncClient(timeout=httpx.Timeout(45, connect=10))
    targets: list[RouteTarget] = []
    if key := os.getenv("ANTHROPIC_API_KEY"):
        targets.append(
            RouteTarget(
                AnthropicProvider(key, http),
                os.getenv("ANTHROPIC_MODEL", "claude-sonnet-latest"),
            )
        )
    if key := os.getenv("DEEPSEEK_API_KEY"):
        targets.append(
            RouteTarget(
                DeepSeekChatProvider(key, http),
                os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            )
        )
    if key := os.getenv("OPENAI_API_KEY"):
        targets.append(
            RouteTarget(
                OpenAIResponsesProvider(key, http),
                os.getenv("OPENAI_MODEL", "gpt-5.6-terra"),
            )
        )
    return create_app(
        ModelRouter(
            {"listing-quality": targets},
            input_cost_per_million=float(
                os.getenv("MODEL_INPUT_COST_PER_MILLION_USD", "0")
            ),
            output_cost_per_million=float(
                os.getenv("MODEL_OUTPUT_COST_PER_MILLION_USD", "0")
            ),
        )
    )


app = app_from_environment()
