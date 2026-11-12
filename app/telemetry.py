"""OpenTelemetry bootstrap and shared metrics for the PPT Generation Service.

Import and call configure_telemetry() once in each process (API and worker).
OTLP export is controlled by OTEL_EXPORTER_OTLP_ENDPOINT and related env vars.
"""
from __future__ import annotations

import logging
import os
import time
from functools import wraps
from typing import Optional

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_configured = False
_tracer = None
_meter = None

# These are populated by configure_telemetry().
http_requests_total = None
http_request_duration = None
http_errors_total = None
llm_requests_total = None
llm_request_duration = None
llm_errors_total = None
pipeline_activity_duration = None
pipeline_activity_total = None


def configure_telemetry(service_name: Optional[str] = None) -> None:
    """Configure OTLP traces, metrics and logs. Safe to call more than once."""
    global _configured, _tracer, _meter
    global http_requests_total, http_request_duration, http_errors_total
    global llm_requests_total, llm_request_duration, llm_errors_total
    global pipeline_activity_duration, pipeline_activity_total
    if _configured:
        return

    service_name = service_name or os.getenv("OTEL_SERVICE_NAME", "ppt-generation-service")
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    insecure = os.getenv("OTEL_EXPORTER_OTLP_INSECURE", "true").lower() in {"1", "true", "yes"}
    resource = Resource.create({
        "service.name": service_name,
        "service.version": os.getenv("APP_VERSION", "2.2.0"),
        "deployment.environment": os.getenv("DEPLOYMENT_ENVIRONMENT", "development"),
    })

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=insecure)))
    trace.set_tracer_provider(tracer_provider)
    _tracer = trace.get_tracer("ppt_generation_service", "1.0.0")

    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=endpoint, insecure=insecure),
        export_interval_millis=int(os.getenv("OTEL_METRIC_EXPORT_INTERVAL", "10000")),
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)
    _meter = metrics.get_meter("ppt_generation_service", "1.0.0")

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoint, insecure=insecure)))
    set_logger_provider(logger_provider)
    # Bridge stdlib logging to OTel while retaining normal console/container logs.
    root = logging.getLogger()
    root.addHandler(LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider))
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

    http_requests_total = _meter.create_counter("http.server.requests", unit="{request}", description="HTTP requests handled")
    http_request_duration = _meter.create_histogram("http.server.request.duration", unit="s", description="HTTP request duration")
    http_errors_total = _meter.create_counter("http.server.errors", unit="{error}", description="HTTP requests ending in 4xx/5xx")
    llm_requests_total = _meter.create_counter("llm.client.requests", unit="{request}", description="LLM requests")
    llm_request_duration = _meter.create_histogram("llm.client.request.duration", unit="s", description="LLM request duration")
    llm_errors_total = _meter.create_counter("llm.client.errors", unit="{error}", description="Failed LLM requests")
    pipeline_activity_duration = _meter.create_histogram("ppt.pipeline.activity.duration", unit="s", description="Pipeline operation duration")
    pipeline_activity_total = _meter.create_counter("ppt.pipeline.activity.executions", unit="{execution}", description="Pipeline operation executions")
    _configured = True


def get_tracer():
    return _tracer or trace.get_tracer("ppt_generation_service")


def get_meter():
    return _meter or metrics.get_meter("ppt_generation_service")


def record_llm_request(role: str, model: str, duration_seconds: float, success: bool) -> None:
    """Record low-cardinality LLM metrics; don't use prompts or job IDs as labels."""
    attrs = {"llm.role": role, "llm.model": model, "outcome": "success" if success else "error"}
    if llm_requests_total is not None:
        llm_requests_total.add(1, attrs)
        llm_request_duration.record(max(0.0, duration_seconds), attrs)
    if not success and llm_errors_total is not None:
        llm_errors_total.add(1, {"llm.role": role, "llm.model": model})


def record_activity(name: str, duration_seconds: float, success: bool) -> None:
    attrs = {"activity.name": name, "outcome": "success" if success else "error"}
    if pipeline_activity_total is not None:
        pipeline_activity_total.add(1, attrs)
        pipeline_activity_duration.record(max(0.0, duration_seconds), attrs)


def traced_activity(name: str):
    """Trace one async Temporal activity and record duration/outcome metrics."""
    def decorate(fn):
        @wraps(fn)
        async def wrapped(*args, **kwargs):
            started = time.perf_counter()
            success = False
            with get_tracer().start_as_current_span(f"ppt.activity.{name}") as span:
                span.set_attribute("temporal.activity", name)
                try:
                    result = await fn(*args, **kwargs)
                    success = True
                    return result
                except Exception:
                    try:
                        from opentelemetry.trace import Status, StatusCode
                        span.set_status(Status(StatusCode.ERROR, "Temporal activity failed"))
                    except Exception:
                        pass
                    raise
                finally:
                    record_activity(name, time.perf_counter() - started, success)
        return wrapped
    return decorate
