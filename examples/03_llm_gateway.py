"""Run with: uvicorn examples.03_llm_gateway:app --reload --port 8000."""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from litellm import acompletion
from pydantic import BaseModel, Field


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=30_000)


class ChatRequest(BaseModel):
    model: str = Field(examples=["openai/gpt-4.1-mini"])
    messages: list[Message] = Field(min_length=1)
    temperature: float = Field(default=0.2, ge=0, le=1)
    json_schema: dict | None = None


class ChatResponse(BaseModel):
    request_id: str
    model: str
    content: str
    latency_ms: int


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(title="E-commerce Multi-LLM Gateway", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    request_id, started = str(uuid.uuid4()), time.perf_counter()
    kwargs: dict = {"model": request.model, "messages": [message.model_dump() for message in request.messages], "temperature": request.temperature, "timeout": 45}
    if request.json_schema:
        kwargs["response_format"] = {"type": "json_schema", "json_schema": {"name": "ecommerce_output", "schema": request.json_schema, "strict": True}}
    try:
        result = await acompletion(**kwargs)
        content = result.choices[0].message.content or ""
    except Exception as exc:
        # Do not expose provider credentials or raw provider stack traces to callers.
        raise HTTPException(status_code=503, detail={"request_id": request_id, "error": "model_unavailable", "message": str(exc)[:300]}) from exc
    return ChatResponse(request_id=request_id, model=request.model, content=content, latency_ms=int((time.perf_counter() - started) * 1000))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
