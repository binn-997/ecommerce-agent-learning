"""OpenTelemetry setup with safe attributes and pluggable production exporters."""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider


def configure_telemetry(
    service_name: str,
    *,
    span_processor: SpanProcessor | None = None,
) -> trace.Tracer:
    """Configure the SDK once; deployment injects an OTLP processor/exporter."""
    current = trace.get_tracer_provider()
    if not isinstance(current, TracerProvider):
        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        if span_processor is not None:
            provider.add_span_processor(span_processor)
        trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)
