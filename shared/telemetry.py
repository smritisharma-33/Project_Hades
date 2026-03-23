"""Shared OpenTelemetry initialization for all services."""

import logging
import structlog
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.trace import get_current_span
from fastapi import FastAPI


def _add_trace_context(logger, method_name, event_dict):
    """Structlog processor that injects trace_id and span_id into log entries."""
    span = get_current_span()
    if span and span.is_recording():
        ctx = span.get_span_context()
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    else:
        event_dict["trace_id"] = "0" * 32
        event_dict["span_id"] = "0" * 16
    return event_dict


def init_telemetry(
    app: FastAPI,
    service_name: str,
    otlp_endpoint: str = "http://otel-collector:4317",
) -> tuple[trace.Tracer, metrics.Meter]:
    """Initialize OpenTelemetry tracing, metrics, and structured logging.

    Returns a (Tracer, Meter) tuple for custom instrumentation.
    """
    resource = Resource.create({SERVICE_NAME: service_name})

    # --- Tracing ---
    tracer_provider = TracerProvider(resource=resource)
    span_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)

    # --- Metrics ---
    prometheus_reader = PrometheusMetricReader()
    otlp_metric_exporter = OTLPMetricExporter(endpoint=otlp_endpoint, insecure=True)
    otlp_metric_reader = PeriodicExportingMetricReader(
        otlp_metric_exporter, export_interval_millis=5000
    )
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[prometheus_reader, otlp_metric_reader],
    )
    metrics.set_meter_provider(meter_provider)

    # --- Structured Logging ---
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            _add_trace_context,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(format="%(message)s", level=logging.INFO)

    # --- Auto-instrumentation ---
    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()

    tracer = trace.get_tracer(service_name)
    meter = metrics.get_meter(service_name)
    return tracer, meter
