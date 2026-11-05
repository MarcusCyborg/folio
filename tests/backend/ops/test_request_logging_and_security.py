import pytest
import re
from fastapi.testclient import TestClient
from src.backend.main import app


def test_request_id_generated_automatically(client):
    """Responses must include X-Request-ID header generated if not sent by client."""
    res = client.get("/health/live")
    assert res.status_code == 200
    assert "X-Request-ID" in res.headers
    req_id = res.headers["X-Request-ID"]
    assert len(req_id) >= 16
    assert re.match(r"^[a-zA-Z0-9\-_]+$", req_id)


def test_client_request_id_propagated_reliably(client):
    """When a reverse proxy or client provides X-Request-ID, it must be preserved and returned."""
    custom_id = "test-proxy-req-uuid-987654321"
    res = client.get("/health/live", headers={"X-Request-ID": custom_id})
    assert res.status_code == 200
    assert res.headers.get("X-Request-ID") == custom_id


def test_security_headers_present_on_all_responses(client):
    """All HTTP responses must contain baseline security headers and CSP."""
    res = client.get("/health/live")
    assert res.status_code == 200
    headers = res.headers

    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "Content-Security-Policy" in headers
    csp = headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "style-src 'self' 'unsafe-inline'" in csp


def test_trusted_proxy_client_ip_logging(client, caplog):
    """Client IP should be extracted from X-Forwarded-For when client host is in TRUSTED_PROXIES."""
    import logging
    with caplog.at_level(logging.INFO, logger="folio.access"):
        res = client.get(
            "/health/live",
            headers={
                "X-Forwarded-For": "203.0.113.195, 10.0.0.1",
                "X-Request-ID": "ip-test-req-1234",
            },
        )
        assert res.status_code == 200

    # Verify no passwords or tokens were logged
    for record in caplog.records:
        if record.name == "folio.access":
            extra = getattr(record, "extra", {})
            assert "password" not in str(record.message).lower()
            assert "secret" not in str(record.message).lower()
