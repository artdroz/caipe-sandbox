"""Control-plane telemetry without request bodies, credentials or terminal data."""

import json
import logging
import os
import time
import traceback
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from uuid import uuid4

from opentelemetry import trace
from opentelemetry.trace import SpanKind, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

_fields = ContextVar("portal_log_fields", default={})
_tracer = ContextVar("portal_tracer", default=trace.NoOpTracer())
logger = logging.getLogger(__name__)


def bind(**fields):
    _fields.set({**_fields.get(), **fields})


def event(name, **fields):
    logger.info(name, extra={"event_fields": fields})


class JsonFormatter(logging.Formatter):
    def format(self, record):
        result = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "service": os.getenv("OTEL_SERVICE_NAME", "caipe-sandbox-portal"),
            "logger": record.name,
            "message": record.getMessage(),
            "actor": "system",
            **_fields.get(),
        }
        result.update(getattr(record, "event_fields", {}))
        span = trace.get_current_span().get_span_context()
        if span.is_valid:
            result.update(
                trace_id=f"{span.trace_id:032x}", span_id=f"{span.span_id:016x}"
            )
        if record.exc_info and record.exc_info[0] is not None:
            result["error_type"] = record.exc_info[0].__name__
            result["stack"] = [
                {"file": frame.filename, "line": frame.lineno, "function": frame.name}
                for frame in traceback.extract_tb(record.exc_info[2])
            ]
        return json.dumps(result, default=str, ensure_ascii=True)


class Tracing:
    """Use standard OTLP/HTTP and SDK environment settings when configured."""

    def __init__(self):
        self.provider = None
        self.tracer = trace.NoOpTracer()
        if os.getenv("OTEL_SDK_DISABLED", "").lower() == "true" or not (
            os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
            or os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        ):
            return
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        self.provider = TracerProvider(
            resource=Resource.create(
                {"service.name": os.getenv("OTEL_SERVICE_NAME", "caipe-sandbox-portal")}
            ),
            shutdown_on_exit=False,
        )
        self.provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        self.tracer = self.provider.get_tracer("portal")

    def close(self):
        if self.provider is not None:
            self.provider.shutdown()


@contextmanager
def span(name, *, tracer=None, kind=SpanKind.INTERNAL, context=None, **fields):
    token = _fields.set({**_fields.get(), **fields})
    tracer_token = _tracer.set(tracer or _tracer.get())
    started = time.monotonic()
    try:
        with _tracer.get().start_as_current_span(
            name,
            context=context,
            kind=kind,
            attributes=fields,
            record_exception=False,
            set_status_on_exception=False,
        ) as current:
            try:
                yield current
            except Exception as exc:
                current.set_status(StatusCode.ERROR)
                current.set_attribute("error.type", type(exc).__name__)
                logger.warning(
                    "action_failed",
                    extra={
                        "event_fields": {
                            "action": name,
                            "outcome": "error",
                            "error_type": type(exc).__name__,
                            "status_code": getattr(exc, "status_code", 500),
                            "duration_ms": round(
                                (time.monotonic() - started) * 1000, 2
                            ),
                        }
                    },
                )
                raise
    finally:
        _tracer.reset(tracer_token)
        _fields.reset(token)


@contextmanager
def operation(record):
    action = record.operation
    if action is None:
        yield
        return
    with span(
        "sandbox." + action.kind,
        operation_id=str(action.request_id),
        sandbox_id=str(record.id),
        provider=record.provider,
        namespace=record.scope,
        requested_by=action.actor,
        actor=_fields.get().get("actor", action.actor),
        action=action.kind,
        integration=action.parameters.get("integration", ""),
        category="audit",
    ):
        logger.info("operation_attempt_started")
        yield


class RequestTelemetry:
    def __init__(self, app, telemetry):
        self.app, self.telemetry = app, telemetry

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            request_id = str(uuid4())
            scope.setdefault("state", {})["request_id"] = request_id
            token = _fields.set({"request_id": request_id, "actor": "anonymous"})
            try:
                return await self.app(scope, receive, send)
            finally:
                _fields.reset(token)
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if "/api/" not in path and "/auth/" not in path:
            return await self.app(scope, receive, send)
        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        fields_token = _fields.set({"request_id": request_id, "actor": "anonymous"})
        status = 500
        started = time.monotonic()
        # Propagate traceparent only; arbitrary caller baggage is not telemetry.
        parent = TraceContextTextMapPropagator().extract(
            {
                k.decode("latin1"): v.decode("latin1")
                for k, v in scope.get("headers", [])
                if k in {b"traceparent", b"tracestate"}
            }
        )
        try:
            with span(
                "http.request",
                tracer=self.telemetry.tracer,
                kind=SpanKind.SERVER,
                context=parent,
                request_id=request_id,
            ) as current:
                context = current.get_span_context()
                if context.is_valid:
                    scope["state"]["trace_id"] = f"{context.trace_id:032x}"

                async def response(message):
                    nonlocal status
                    if message["type"] == "http.response.start":
                        status = message["status"]
                        message["headers"] = [
                            (k, v)
                            for k, v in message.get("headers", [])
                            if k.lower() != b"x-request-id"
                        ] + [(b"x-request-id", request_id.encode())]
                    await send(message)

                try:
                    await self.app(scope, receive, response)
                finally:
                    route = getattr(scope.get("route"), "path", "unmatched")
                    method = scope.get("method", "")
                    current.update_name(f"{method} {route}")
                    current.set_attributes(
                        {
                            "http.request.method": method,
                            "http.route": route,
                            "http.response.status_code": status,
                        }
                    )
                    if status >= 500:
                        current.set_status(StatusCode.ERROR)
                    logger.log(
                        logging.WARNING
                        if status >= 500
                        else logging.INFO
                        if method not in {"GET", "HEAD"} or status >= 400
                        else logging.DEBUG,
                        "http_request",
                        extra={
                            "event_fields": {
                                "method": method,
                                "route": route,
                                "status_code": status,
                                "category": "audit"
                                if method in {"POST", "PUT", "PATCH", "DELETE"}
                                else "access",
                                "sandbox": scope.get("path_params", {}).get("name", ""),
                                "outcome": "denied"
                                if status in {401, 403}
                                else "error"
                                if status >= 400
                                else "accepted",
                                "duration_ms": round(
                                    (time.monotonic() - started) * 1000, 2
                                ),
                            }
                        },
                    )
        finally:
            _fields.reset(fields_token)
