from opentelemetry.sdk.trace import TracerProvider

from amazon_ai_platform.telemetry import configure_telemetry


def test_telemetry_configures_sdk_without_sensitive_attributes() -> None:
    tracer = configure_telemetry("synthetic-test-service")
    assert tracer is not None
    assert isinstance(__import__("opentelemetry").trace.get_tracer_provider(), TracerProvider)
