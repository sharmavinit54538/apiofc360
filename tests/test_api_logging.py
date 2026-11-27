"""Regression tests for terminal API request logging, uvicorn formatter safety, and duplicate listener checks."""

from __future__ import annotations

import logging
import logging.config
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from uvicorn.config import LOGGING_CONFIG

from app.core.structured_logging import PIIRedactionFilter
from app.main import _find_duplicate_windows_listeners, configure_logging
from app.middleware.request_id import RequestIDMiddleware
from app.middleware.timing import TimingMiddleware


@pytest.mark.asyncio
async def test_timing_middleware_logs_api_requests_and_errors(caplog):
    """TimingMiddleware logs normal API requests at INFO, 500s at ERROR, and keeps noisy probes at DEBUG."""
    test_app = FastAPI()
    test_app.add_middleware(TimingMiddleware)
    test_app.add_middleware(RequestIDMiddleware)

    @test_app.get("/api/v1/ping")
    async def ping():
        return {"ok": True}

    @test_app.get("/api/v1/fail")
    async def fail():
        return JSONResponse(status_code=500, content={"detail": "boom"})

    @test_app.get("/health/live")
    async def health_live():
        return {"status": "alive"}

    with caplog.at_level(logging.INFO, logger="app.timing"):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r_ok = await client.get("/api/v1/ping", headers={"X-Request-ID": "req-123"})
            r_err = await client.get("/api/v1/fail", headers={"X-Request-ID": "req-456"})
            r_live = await client.get("/health/live")
            r_opt = await client.options("/api/v1/ping")

    assert r_ok.status_code == 200
    assert "x-process-time" in r_ok.headers
    assert r_err.status_code == 500
    assert r_live.status_code == 200
    assert r_opt.status_code == 405 or r_opt.status_code == 200

    messages = [(r.levelname, r.getMessage()) for r in caplog.records if r.name == "app.timing"]
    assert any(lvl == "INFO" and "API GET /api/v1/ping -> 200" in msg and "req=req-123" in msg for lvl, msg in messages)
    assert any(lvl == "ERROR" and "API GET /api/v1/fail -> 500" in msg and "req=req-456" in msg for lvl, msg in messages)
    assert not any("/health/live" in msg for _, msg in messages)
    assert not any("OPTIONS /api/v1/ping" in msg for _, msg in messages)


@pytest.mark.asyncio
async def test_timing_middleware_logs_unhandled_exception():
    """TimingMiddleware still logs a 500 error if an inner ASGI app raises before sending response headers."""

    async def broken_app(scope, receive, send):
        raise RuntimeError("boom before response start")

    wrapped = TimingMiddleware(broken_app)
    scope = {"type": "http", "method": "GET", "path": "/api/v1/crash", "headers": []}

    records: list[logging.LogRecord] = []

    class CaptureHandler(logging.Handler):
        def emit(self, record):
            records.append(record)

    timing_logger = logging.getLogger("app.timing")
    handler = CaptureHandler()
    timing_logger.addHandler(handler)
    try:
        with pytest.raises(RuntimeError, match="boom before response start"):
            await wrapped(scope, lambda: None, lambda _msg: None)
    finally:
        timing_logger.removeHandler(handler)

    assert any(r.levelno == logging.ERROR and "API GET /api/v1/crash -> 500" in r.getMessage() for r in records)


def test_configure_logging_sets_levels_and_keeps_uvicorn_access_intact():
    """configure_logging sets INFO on root/app even when handlers pre-exist and preserves uvicorn.access args."""
    root = logging.getLogger()
    prev_level = root.level
    prev_handlers = list(root.handlers)
    try:
        logging.config.dictConfig(LOGGING_CONFIG)
        root.setLevel(logging.WARNING)
        if not root.handlers:
            root.addHandler(logging.StreamHandler())

        configure_logging()
        configure_logging()

        assert root.level <= logging.INFO
        assert logging.getLogger("app").level <= logging.INFO

        for h in root.handlers:
            assert sum(isinstance(f, PIIRedactionFilter) for f in h.filters) == 1

        access_logger = logging.getLogger("uvicorn.access")
        assert access_logger.level <= logging.INFO
        assert access_logger.handlers
        for h in access_logger.handlers:
            assert not any(isinstance(f, PIIRedactionFilter) for f in h.filters)
            record = access_logger.makeRecord(
                "uvicorn.access",
                logging.INFO,
                __file__,
                1,
                '%s - "%s %s HTTP/%s" %d',
                ("127.0.0.1:5000", "GET", "/api/v1/employees", "1.1", 200),
                None,
            )
            for flt in h.filters:
                assert flt.filter(record)
            formatted = h.format(record)
            assert "GET /api/v1/employees HTTP/1.1" in formatted
            assert "200" in formatted
    finally:
        root.setLevel(prev_level)
        root.handlers[:] = prev_handlers


def test_find_duplicate_windows_listeners_detects_stale_socket():
    """_find_duplicate_windows_listeners identifies stale LISTENING PIDs sharing our port."""
    sample_netstat = "\n".join(
        [
            "Active Connections",
            "  Proto  Local Address          Foreign Address        State           PID",
            "  TCP    127.0.0.1:8000         0.0.0.0:0              LISTENING       12924",
            "  TCP    127.0.0.1:8000         0.0.0.0:0              LISTENING       34276",
            "  TCP    127.0.0.1:5432         0.0.0.0:0              LISTENING       2000",
        ]
    )
    fake_res = SimpleNamespace(returncode=0, stdout=sample_netstat)

    with patch("app.main.subprocess.run", return_value=fake_res):
        duplicates = _find_duplicate_windows_listeners({12924, 39216})

    assert len(duplicates) == 1
    assert duplicates[0]["port"] == 8000
    assert duplicates[0]["stale_socket_pids"] == [34276]
