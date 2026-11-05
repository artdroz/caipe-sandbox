import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from portal.telemetry import JsonFormatter, RequestTelemetry, Tracing, bind, operation


@pytest.fixture
def observed(caplog):
    exporter = InMemorySpanExporter()
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    app = FastAPI()
    app.add_middleware(
        RequestTelemetry, telemetry=SimpleNamespace(tracer=provider.get_tracer("test"))
    )
    events = []

    class Capture(logging.Handler):
        def emit(self, record):
            events.append(json.loads(JsonFormatter().format(record)))

    handler = Capture()
    logger = logging.getLogger("portal.telemetry")
    logger.addHandler(handler)
    caplog.set_level(logging.INFO)

    @app.post("/api/sandboxes/{name}")
    async def create(name: str, fail: bool = False):
        bind(actor="bob@example.com", actor_role="admin")
        record = SimpleNamespace(
            id=uuid4(),
            provider="future-runtime",
            scope="sandbox-test",
            operation=SimpleNamespace(
                kind="create",
                request_id=uuid4(),
                actor="alice@example.com",
                parameters={},
            ),
        )

        def perform():
            with operation(record):
                if fail:
                    raise HTTPException(503, "private-provider-token")

        await asyncio.to_thread(perform)
        return {"id": str(record.id), "operation_id": str(record.operation.request_id)}

    @app.get("/healthz")
    async def health():
        return {"ok": True}

    @app.get("/api/poll")
    async def poll():
        return {"ok": True}

    with TestClient(app) as client:
        yield client, exporter, events
    logger.removeHandler(handler)
    provider.shutdown()


def test_request_and_worker_operation_share_trace_without_sensitive_payloads(observed):
    client, exporter, events = observed
    trace_id = "12345678901234567890123456789012"
    response = client.post(
        "/api/sandboxes/friendly-fox?ticket=secret-query",
        headers={
            "Authorization": "Bearer secret-header",
            "Cookie": "session=secret-cookie",
            "traceparent": f"00-{trace_id}-1234567890123456-01",
            "baggage": "password=secret-baggage",
        },
        json={"password": "secret-body", "terminal": "secret-command"},
    )
    assert response.status_code == 200
    UUID(response.headers["x-request-id"])
    spans = exporter.get_finished_spans()
    request = next(s for s in spans if s.name.startswith("POST"))
    action = next(s for s in spans if s.name == "sandbox.create")
    assert action.parent.span_id == request.context.span_id
    assert request.context.trace_id == int(trace_id, 16)
    assert action.attributes["sandbox_id"] == response.json()["id"]
    assert action.attributes["operation_id"] == response.json()["operation_id"]
    assert action.attributes["provider"] == "future-runtime"
    assert action.attributes["actor"] == "bob@example.com"
    assert action.attributes["requested_by"] == "alice@example.com"
    assert {e["request_id"] for e in events} == {response.headers["x-request-id"]}
    assert {e["trace_id"] for e in events} == {trace_id}
    serialized = json.dumps(events) + str([dict(s.attributes) for s in spans])
    assert "secret-" not in serialized
    assert "friendly-fox" not in str([dict(s.attributes) for s in spans])
    assert request.attributes["http.route"] == "/api/sandboxes/{name}"


def test_export_uses_real_otlp_http_and_shutdown_flushes(monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
        ExportTraceServiceRequest,
    )
    from portal.telemetry import span

    received = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append((self.path, ExportTraceServiceRequest.FromString(body)))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT", f"http://127.0.0.1:{server.server_port}"
    )
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "always_on")
    runtime = Tracing()
    try:
        with span("sandbox.create", tracer=runtime.tracer, sandbox_id="synthetic-test"):
            pass
        runtime.close()
        assert received and received[0][0] == "/v1/traces"
        payload = received[0][1]
        assert (
            payload.resource_spans[0].scope_spans[0].spans[0].name == "sandbox.create"
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_unreachable_exporter_does_not_fail_api_requests(monkeypatch):
    from socket import socket

    with socket() as unused:
        unused.bind(("127.0.0.1", 0))
        port = unused.getsockname()[1]
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", f"http://127.0.0.1:{port}")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TIMEOUT", "0.1")
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "always_on")
    runtime = Tracing()
    app = FastAPI()
    app.add_middleware(RequestTelemetry, telemetry=runtime)

    @app.get("/api/check")
    async def check():
        return {"ok": True}

    try:
        with TestClient(app) as client:
            for _ in range(5):
                assert client.get("/api/check").json() == {"ok": True}
    finally:
        runtime.close()


def test_real_portal_lifecycle_and_sharing_audits_link_actor_and_saved_intent(caplog):
    from test_portal import BASE, HEADERS, OWNER, Omnigent
    from test_profiles import store_for
    from portal.app import create_app

    store, _ = store_for()
    events = []

    class Capture(logging.Handler):
        def emit(self, record):
            events.append(json.loads(JsonFormatter().format(record)))

    handler = Capture()
    logger = logging.getLogger("portal.telemetry")
    logger.addHandler(handler)
    caplog.set_level(logging.INFO)
    try:
        with TestClient(create_app(store.settings, store, Omnigent())) as client:
            created = client.post(BASE + "/sandboxes", headers=HEADERS)
            assert created.status_code == 201
            row = created.json()
            name = row["id"]
            record = store.get(name, OWNER).record
            started = next(
                e for e in events if e["message"] == "operation_attempt_started"
            )
            finished = next(
                e for e in events if e["message"] == "operation_attempt_finished"
            )
            assert (
                started["request_id"]
                == finished["request_id"]
                == created.headers["x-request-id"]
            )
            assert finished["sandbox_id"] == str(record.id)
            assert finished["actor"] == OWNER
            assert finished["outcome"] == "completed"
            sharing = client.put(
                BASE + f"/sandboxes/{name}/sharing",
                headers=HEADERS,
                json={"members": {"bob@example.com": "view"}},
            )
            assert sharing.status_code == 200
            event = next(
                e for e in events if e["message"] == "namespace_sharing_changed"
            )
            assert event["request_id"] == sharing.headers["x-request-id"]
            assert event["actor"] == OWNER
            assert event["sandbox_id"] == str(record.id)
            assert event["members"] == {"bob@example.com": "view"}
    finally:
        logger.removeHandler(handler)


def test_unexpected_portal_error_returns_a_safe_correlatable_reference(
    monkeypatch, caplog
):
    from test_portal import BASE, HEADERS, Omnigent
    from test_profiles import store_for
    from portal.app import create_app

    store, _ = store_for()

    def failed(*_):
        raise RuntimeError("database-password-do-not-expose")

    monkeypatch.setattr(store, "shared_list", failed)
    with TestClient(
        create_app(store.settings, store, Omnigent()), raise_server_exceptions=False
    ) as client:
        response = client.get(BASE + "/sandboxes", headers=HEADERS)
    assert response.status_code == 500
    assert response.headers["x-request-id"] in response.json()["detail"]
    record = next(r for r in caplog.records if r.getMessage() == "unexpected_failure")
    event = json.loads(JsonFormatter().format(record))
    assert event["request_id"] == response.headers["x-request-id"]
    assert event["error_type"] == "RuntimeError"
    assert "database-password" not in json.dumps(event)


def test_concurrent_requests_keep_distinct_contexts_and_do_not_leak_operation_fields(
    observed,
):
    client, exporter, events = observed
    with ThreadPoolExecutor(max_workers=4) as workers:
        responses = list(
            workers.map(lambda _: client.post("/api/sandboxes/example"), range(8))
        )
    ids = {r.headers["x-request-id"] for r in responses}
    assert len(ids) == 8
    for response in responses:
        action = next(
            e
            for e in events
            if e["request_id"] == response.headers["x-request-id"]
            and e["message"] == "operation_attempt_started"
        )
        assert action["sandbox_id"] == response.json()["id"]
    requests = [e for e in events if e["message"] == "http_request"]
    assert len(requests) == 8
    assert all("sandbox_id" not in e and "operation_id" not in e for e in requests)
    assert len(exporter.get_finished_spans()) == 16


def test_failed_operation_is_correlated_and_exception_text_is_not_exported(observed):
    client, exporter, events = observed
    response = client.post("/api/sandboxes/example?fail=true")
    assert response.status_code == 503
    failure = next(e for e in events if e["message"] == "action_failed")
    assert failure["request_id"] == response.headers["x-request-id"]
    assert failure["error_type"] == "HTTPException"
    assert failure["status_code"] == 503
    assert "private-provider-token" not in json.dumps(events)
    spans = exporter.get_finished_spans()
    assert all(s.status.status_code == StatusCode.ERROR for s in spans)
    assert all(not s.events and not s.status.description for s in spans)


def test_health_checks_do_not_generate_telemetry(observed):
    client, exporter, events = observed
    assert client.get("/healthz").status_code == 200
    assert events == []
    assert exporter.get_finished_spans() == ()


def test_successful_polling_does_not_flood_info_logs(observed):
    client, exporter, events = observed
    for _ in range(10):
        assert client.get("/api/poll").status_code == 200
    assert not events
    assert len(exporter.get_finished_spans()) == 10


def test_exception_formatter_omits_exception_message_and_local_values():
    try:
        raise RuntimeError("database-password-do-not-log")
    except RuntimeError:
        import sys

        record = logging.LogRecord(
            "portal",
            logging.ERROR,
            __file__,
            1,
            "unexpected_failure",
            (),
            sys.exc_info(),
        )
    result = json.loads(JsonFormatter().format(record))
    assert result["error_type"] == "RuntimeError"
    assert result["stack"]
    assert "database-password" not in json.dumps(result)


def test_tracing_is_optional_and_can_be_disabled(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    disabled = Tracing()
    assert disabled.provider is None
    disabled.close()
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:1")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    assert Tracing().provider is None


def test_standard_sdk_sampling_and_resources_are_honoured(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:1")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "custom-portal")
    monkeypatch.setenv(
        "OTEL_RESOURCE_ATTRIBUTES", "service.version=example,k8s.namespace.name=test"
    )
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "always_off")
    runtime = Tracing()
    try:
        assert runtime.provider.resource.attributes["service.name"] == "custom-portal"
        assert runtime.provider.resource.attributes["service.version"] == "example"
        with runtime.tracer.start_as_current_span("not-sampled") as current:
            assert not current.is_recording()
    finally:
        runtime.close()


def test_background_operations_inherit_the_maintenance_tracer():
    from portal.telemetry import span

    exporter = InMemorySpanExporter()
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    record = SimpleNamespace(
        id=uuid4(),
        provider="future-runtime",
        scope="background-test",
        operation=SimpleNamespace(
            kind="mode", request_id=uuid4(), actor="alice@example.com", parameters={}
        ),
    )
    try:
        with span("maintenance", tracer=provider.get_tracer("test"), actor="system"):
            with operation(record):
                pass
        child, parent = exporter.get_finished_spans()
        assert child.parent.span_id == parent.context.span_id
        assert child.context.trace_id == parent.context.trace_id
        assert child.attributes["actor"] == "system"
        assert child.attributes["requested_by"] == "alice@example.com"
    finally:
        provider.shutdown()


def test_denied_terminal_connection_has_anonymous_actor_and_user_visible_reference(
    caplog,
):
    from test_portal import BASE, SETTINGS, Omnigent
    from test_profiles import store_for
    from portal.app import create_app

    store, _ = store_for()
    events = []

    class Capture(logging.Handler):
        def emit(self, record):
            events.append(json.loads(JsonFormatter().format(record)))

    handler = Capture()
    logger = logging.getLogger("uvicorn.error")
    logger.addHandler(handler)
    try:
        with TestClient(create_app(store.settings, store, Omnigent())) as client:
            with client.websocket_connect(
                BASE + "/sandboxes/example/terminal",
                headers={"Origin": SETTINGS.origin},
            ) as ws:
                packet = json.loads(ws.receive_bytes())
        event = next(e for e in events if e["message"].startswith("terminal_error"))
        assert event["actor"] == "anonymous"
        assert event["category"] == "audit"
        assert event["request_id"] == packet["request_id"]
    finally:
        logger.removeHandler(handler)
