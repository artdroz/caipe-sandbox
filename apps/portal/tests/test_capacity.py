"""Opt-in local forwarding benchmark; never connects to live sandbox providers."""

import asyncio
import json
import math
import os
import platform
import signal
import subprocess
import time
from collections import Counter
from importlib.metadata import version
from pathlib import Path

import httpx
import pytest
import sqlalchemy as sa
from test_portal import BASE, SETTINGS
from test_replicas import replicas as replicas
from test_storage import database as database
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed


def bounded(name, default, low, high):
    value = int(os.environ.get(name, default))
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


def distribution(values):
    ordered = sorted(values)
    return {
        "count": len(ordered),
        **{
            key: round(
                ordered[max(0, math.ceil(fraction * len(ordered)) - 1)] * 1000, 3
            )
            if ordered
            else None
            for key, fraction in {
                "p50_ms": 0.5,
                "p95_ms": 0.95,
                "p99_ms": 0.99,
                "max_ms": 1,
            }.items()
        },
    }


def metrics(ports, metadata):
    with httpx.Client(timeout=5, trust_env=False) as client:
        servers = []
        for port in ports:
            response = client.get(f"http://127.0.0.1:{port}/_test/capacity")
            response.raise_for_status()
            servers.append(response.json())
    with metadata.engine.connect() as connection:
        connections = dict(
            connection.execute(
                sa.text(
                    "SELECT state, count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() GROUP BY state"
                )
            ).all()
        )
    return {"replicas": servers, "database_connections": connections}


async def echo(ws, nonce):
    started = time.perf_counter()
    await ws.send(json.dumps({"type": "input", "data": nonce}))
    assert await asyncio.wait_for(ws.recv(), 8) == nonce, (
        "Echo identity changed or input/output was lost"
    )
    return time.perf_counter() - started


async def phase(
    sessions, http, ports, metadata, *, active, seconds, workers, payload_bytes
):
    import resource

    before = await asyncio.to_thread(metrics, ports, metadata)
    cpu_before = resource.getrusage(resource.RUSAGE_SELF)
    started = time.perf_counter()
    stopped = asyncio.Event()
    api, samples, errors = [], [before], Counter()

    async def produce(index):
        latencies, failures, sequence = [], Counter(), 0
        while not stopped.is_set():
            for offset in range(index, len(sessions), workers):
                if stopped.is_set():
                    break
                nonce = f"{offset}:{sequence}:" + "x" * payload_bytes
                try:
                    latencies.append(await echo(sessions[offset], nonce))
                except (
                    OSError,
                    ConnectionClosed,
                    TimeoutError,
                    AssertionError,
                ) as error:
                    failures[type(error).__name__] += 1
                    return latencies, failures
                sequence += 1
            await asyncio.sleep(0.1)
        return latencies, failures

    tasks = (
        [asyncio.create_task(produce(index)) for index in range(workers)]
        if active
        else []
    )
    try:
        next_sample = started + 1
        while time.perf_counter() - started < seconds:
            request_started = time.perf_counter()
            try:
                response = await asyncio.to_thread(http.get, BASE + "/sandboxes")
                if response.status_code == 200:
                    api.append(time.perf_counter() - request_started)
                else:
                    errors[f"HTTP {response.status_code}"] += 1
            except httpx.HTTPError as error:
                errors[type(error).__name__] += 1
            if time.perf_counter() >= next_sample:
                samples.append(await asyncio.to_thread(metrics, ports, metadata))
                next_sample = time.perf_counter() + 1
            await asyncio.sleep(0.2)
    finally:
        stopped.set()
    echoes = []
    for values, failures in await asyncio.gather(*tasks):
        echoes.extend(values)
        errors.update(failures)
    samples.append(await asyncio.to_thread(metrics, ports, metadata))
    elapsed = time.perf_counter() - started
    cpu_after = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "phase": "active" if active else "idle",
        "seconds": round(elapsed, 3),
        "api": distribution(api),
        "echo": distribution(echoes),
        "echoes_per_second": round(len(echoes) / elapsed, 2),
        "errors": dict(errors),
        "replicas": [
            {
                "cpu_percent_one_core": round(
                    100
                    * (
                        samples[-1]["replicas"][i]["cpu_seconds"]
                        - before["replicas"][i]["cpu_seconds"]
                    )
                    / elapsed,
                    2,
                ),
                "peak_rss_mib": round(
                    max(s["replicas"][i]["peak_rss_bytes"] for s in samples) / 1024**2,
                    2,
                ),
                "max_sampled_threads": max(
                    s["replicas"][i]["threads"] for s in samples
                ),
                "max_sampled_checked_out": max(
                    s["replicas"][i]["checked_out"] for s in samples
                ),
                "configured_pool_size": before["replicas"][i]["pool_size"],
                "management_queue_wait": distribution(
                    [s["replicas"][i]["management_queue_wait_seconds"] for s in samples]
                ),
                "terminal_queue_wait": distribution(
                    [s["replicas"][i]["terminal_queue_wait_seconds"] for s in samples]
                ),
                "configured_terminal_io_workers": before["replicas"][i][
                    "terminal_io_workers"
                ],
            }
            for i in range(len(ports))
        ],
        "max_sampled_database_connections": max(
            sum(s["database_connections"].values()) for s in samples
        ),
        "driver_cpu_seconds": round(
            cpu_after.ru_utime
            + cpu_after.ru_stime
            - cpu_before.ru_utime
            - cpu_before.ru_stime,
            3,
        ),
    }


async def recover(cluster, sessions, terminal, *, seconds, workers, payload_bytes):
    first, _, start, ports, environments, _, http, metadata, _, _ = cluster
    affected = [
        ws for ws in sessions if int(ws.response.headers["x-test-replica"]) == ports[0]
    ]
    started = time.perf_counter()
    hook = subprocess.Popen(
        [os.sys.executable, "-m", "portal.drain"], env=environments[0]
    )
    api, errors = [], Counter()
    try:
        for ws in affected:
            assert (
                json.loads(await asyncio.wait_for(ws.recv(), 8))["type"] == "draining"
            )
        while hook.poll() is None:
            request_started = time.perf_counter()
            response = await asyncio.to_thread(http.get, BASE + "/sandboxes")
            if response.status_code == 200:
                api.append(time.perf_counter() - request_started)
            else:
                errors[f"HTTP {response.status_code}"] += 1
            assert time.perf_counter() - started < 15, "Drain hook exceeded test budget"
            await asyncio.sleep(0.1)
        assert hook.returncode == 0
        for ws in affected:
            try:
                await asyncio.wait_for(ws.recv(), 8)
            except ConnectionClosed as closed:
                assert closed.rcvd.code == 1012
            else:
                pytest.fail("Drained shell did not close")
            await ws.close()
        first.send_signal(signal.SIGTERM)
        assert await asyncio.to_thread(first.wait, timeout=15) in {0, -signal.SIGTERM}
    finally:
        if hook.poll() is None:
            hook.kill()
            hook.wait(timeout=5)
    latencies = []
    surviving = [ws for ws in sessions if ws not in affected]
    for index in range(len(affected)):
        attached = time.perf_counter()
        replacement = await terminal()
        latencies.append(time.perf_counter() - attached)
        assert int(replacement.response.headers["x-test-replica"]) == ports[1]
        surviving.append(replacement)
        await echo(replacement, f"replacement:{index}")
    single = await phase(
        surviving,
        http,
        [ports[1]],
        metadata,
        active=True,
        seconds=seconds,
        workers=workers,
        payload_bytes=payload_bytes,
    )
    startup = time.perf_counter()
    await asyncio.to_thread(start, 0)
    ready_seconds = time.perf_counter() - startup
    replacements = [await terminal() for _ in range(2)]
    assert {int(ws.response.headers["x-test-replica"]) for ws in replacements} == set(
        ports
    )
    return {
        "affected_shells": len(affected),
        "test_drain_seconds": 3,
        "total_seconds": round(time.perf_counter() - started, 3),
        "replacement_startup_seconds": round(ready_seconds, 3),
        "reattach": distribution(latencies),
        "api_during_drain": distribution(api),
        "single_replica": single,
        "errors": dict(errors),
    }


async def benchmark(replicas, shells):
    assert 1 <= shells <= 200, "Capacity benchmark supports 1–200 shells"
    (
        _,
        _,
        _,
        ports,
        _,
        _,
        http,
        metadata,
        record,
        audit_path,
    ) = replicas
    seconds = bounded("PORTAL_CAPACITY_SECONDS", "30", 1, 600)
    idle_seconds = bounded("PORTAL_CAPACITY_IDLE_SECONDS", str(seconds), 1, 600)
    workers = min(shells, bounded("PORTAL_CAPACITY_WORKERS", "32", 1, 64))
    payload = bounded("PORTAL_CAPACITY_PAYLOAD_BYTES", "256", 1, 8192)
    result = {
        "schema_version": 1,
        "portal_revision": os.environ.get(
            "PORTAL_CAPACITY_REVISION", "unrecorded working tree"
        ),
        "shells": shells,
        "replicas": 2,
        "scope": "Local portal forwarding; in-memory echo provider, test auth and readiness-aware proxy; excludes native compute/network/auth latency",
        "environment": {
            "os": platform.system(),
            "machine": platform.machine(),
            "logical_cpus": os.cpu_count(),
            "python": platform.python_version(),
            "packages": {
                name: version(name)
                for name in [
                    "uvicorn",
                    "starlette",
                    "SQLAlchemy",
                    "psycopg",
                    "websockets",
                ]
            },
        },
        "workload": {
            "phase_seconds": seconds,
            "idle_seconds": idle_seconds,
            "concurrent_producers": workers,
            "payload_bytes_plus_nonce": payload,
            "cycle_pause_seconds": 0.1,
            "access_recheck_seconds": 5,
        },
        "phases": [],
        "passed": False,
    }
    opened = []

    async def terminal():
        ws = await connect(
            str(http.base_url).replace("http://", "ws://").rstrip("/")
            + BASE
            + "/sandboxes/calm-fox/terminal",
            origin=SETTINGS.origin,
            additional_headers={"Cookie": "session=alice"},
            proxy=None,
            open_timeout=8,
            close_timeout=2,
            compression=None,
        )
        opened.append(ws)
        assert json.loads(await asyncio.wait_for(ws.recv(), 8))["type"] == "ready"
        return ws

    try:
        sessions, attachments = [], []
        for _ in range(shells):
            attached = time.perf_counter()
            sessions.append(await terminal())
            attachments.append(time.perf_counter() - attached)
        result["attach"] = distribution(attachments)
        for active in [False, True]:
            measured = await phase(
                sessions,
                http,
                ports,
                metadata,
                active=active,
                seconds=seconds if active else idle_seconds,
                workers=workers,
                payload_bytes=payload,
            )
            result["phases"].append(measured)
            assert not measured["errors"] and measured["api"]["count"] > 0
            if active:
                assert measured["echo"]["count"] >= shells
        result["recovery"] = await recover(
            replicas,
            sessions,
            terminal,
            seconds=seconds,
            workers=workers,
            payload_bytes=payload,
        )
        assert not result["recovery"]["errors"]
        assert not result["recovery"]["single_replica"]["errors"]
        assert result["recovery"]["single_replica"]["echo"]["count"] >= shells
        assert result["recovery"]["single_replica"]["api"]["count"] > 0
        saved = metadata.get_sandbox(record.id)
        assert (
            saved.manifest == record.manifest
            and saved.binding.key == "remote-42"
            and saved.operation is None
        )
        assert all(
            json.loads(line)["event"] == "exec"
            for line in audit_path.read_text().splitlines()
        )
        result["passed"] = True
    finally:
        await asyncio.gather(*(ws.close() for ws in opened), return_exceptions=True)
        destination = Path(
            os.environ.get("PORTAL_CAPACITY_REPORT", "/tmp/portal-capacity.jsonl")
        )
        with destination.open("a") as output:
            output.write(json.dumps(result, allow_nan=False) + "\n")
        print(json.dumps(result, allow_nan=False))


@pytest.mark.skipif(
    os.environ.get("PORTAL_CAPACITY_BENCHMARK") != "1",
    reason="Opt-in local capacity benchmark",
)
@pytest.mark.parametrize(
    "shells",
    [
        int(value)
        for value in os.environ.get("PORTAL_CAPACITY_SHELLS", "50,100,200").split(",")
    ],
)
def test_local_capacity(replicas, shells):
    asyncio.run(benchmark(replicas, shells))
