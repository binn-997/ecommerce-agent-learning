"""Compatibility entrypoint: uvicorn examples.03_llm_gateway:app --port 8000."""

from amazon_ai_platform.llm_gateway import app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
