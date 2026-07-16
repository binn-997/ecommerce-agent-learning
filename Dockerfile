FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY amazon_ai_platform ./amazon_ai_platform

USER 65532:65532
EXPOSE 8000
STOPSIGNAL SIGTERM
CMD ["uvicorn", "amazon_ai_platform.llm_gateway:app", "--host", "0.0.0.0", "--port", "8000"]
