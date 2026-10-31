import pytest

def auth_login(client, email, password="FolioDemo2026!"):
    sess = client.get("/api/v1/auth/session").json()
    res = client.post(
        "/api/v1/auth/login",
        headers={"X-CSRF-Token": sess["csrf_token"]},
        json={"email": email, "password": password}
    )
    assert res.status_code == 200
    return res.json()["csrf_token"]


def test_preview_permissions_enforcement(client):
    """
    Test POST /api/v1/admin/documents/preview requires documents:write:
    - Guest (unauthenticated) -> 401
    - Member (reader@folio.test) -> 403
    - Super Admin (admin@folio.test) -> 200
    """
    # 1. Guest request -> 401
    sess_guest = client.get("/api/v1/auth/session").json()
    res_guest = client.post(
        "/api/v1/admin/documents/preview",
        headers={"X-CSRF-Token": sess_guest["csrf_token"]},
        json={"content": "# Test"}
    )
    assert res_guest.status_code == 401

    # 2. Member request (no documents:write) -> 403
    csrf_member = auth_login(client, "reader@folio.test")
    res_member = client.post(
        "/api/v1/admin/documents/preview",
        headers={"X-CSRF-Token": csrf_member},
        json={"content": "# Test"}
    )
    assert res_member.status_code == 403

    # 3. Super Admin (has documents:write) -> 200
    csrf_admin = auth_login(client, "admin@folio.test")
    res_admin = client.post(
        "/api/v1/admin/documents/preview",
        headers={"X-CSRF-Token": csrf_admin},
        json={"content": "# Hello Admin"}
    )
    assert res_admin.status_code == 200
    assert "<h1>Hello Admin</h1>" in res_admin.json()["rendered_content"]


def test_preview_sanitizes_xss_and_malicious_inputs(client):
    """
    Test POST /api/v1/admin/documents/preview sanitizes malicious content:
    - Harmless XSS payload: [hover me](https://example.invalid/"onpointerenter="document.title=123)
      -> output must NOT contain onpointerenter.
    - Script tags, iframe, onerror attributes -> completely sanitized.
    """
    csrf_admin = auth_login(client, "admin@folio.test")

    # 1. Harmless quote breakout / event handler injection in markdown link
    xss_link = '[hover me](https://example.invalid/"onpointerenter="document.title=123)'
    res1 = client.post(
        "/api/v1/admin/documents/preview",
        headers={"X-CSRF-Token": csrf_admin},
        json={"content": xss_link}
    )
    assert res1.status_code == 200
    rendered1 = res1.json()["rendered_content"]
    assert "onpointerenter" not in rendered1
    assert "document.title" not in rendered1

    # 2. Raw HTML tags and inline event attributes
    malicious_content = (
        "<script>alert('xss')</script>\n"
        "<iframe src=\"https://evil.invalid\"></iframe>\n"
        "<img src=\"x\" onerror=\"alert('img-xss')\">\n"
        "<svg onload=\"alert('svg-xss')\"></svg>\n"
        "<a href=\"https://good.com\" onclick=\"steal()\">Link</a>\n"
        "<style>body { display: none; }</style>\n"
    )
    res2 = client.post(
        "/api/v1/admin/documents/preview",
        headers={"X-CSRF-Token": csrf_admin},
        json={"content": malicious_content}
    )
    assert res2.status_code == 200
    rendered2 = res2.json()["rendered_content"]
    assert "<script>" not in rendered2
    assert "<iframe>" not in rendered2
    assert "onerror" not in rendered2
    assert "<svg" not in rendered2
    assert "onload" not in rendered2
    assert "onclick" not in rendered2
    assert "<style>" not in rendered2
    assert "https://good.com" in rendered2


def test_preview_renders_valid_markdown(client):
    """
    Test POST /api/v1/admin/documents/preview renders standard markdown structures:
    - Headings
    - Code (inline & fenced block)
    - Blockquotes
    - Tables
    - Bold and italic
    - Safe links
    """
    csrf_admin = auth_login(client, "admin@folio.test")

    valid_markdown = """# Main Title
## Subtitle

This is **bold text** and *italicized text*.

> Here is an inspiring quote from research.

Here is inline `print("code")`.

```python
def solve():
    return 42
```

[Folio Knowledge Base](https://example.org/folio)

| Metric | Target | Status |
|---|---|---|
| Latency | < 50ms | Met |
| Availability | 99.9% | Met |
"""

    res = client.post(
        "/api/v1/admin/documents/preview",
        headers={"X-CSRF-Token": csrf_admin},
        json={"content": valid_markdown}
    )
    assert res.status_code == 200
    rendered = res.json()["rendered_content"]

    assert "<h1>Main Title</h1>" in rendered
    assert "<h2>Subtitle</h2>" in rendered
    assert "<strong>bold text</strong>" in rendered
    assert "<em>italicized text</em>" in rendered
    assert "<blockquote>" in rendered
    assert "<code>" in rendered
    assert "<pre>" in rendered
    assert "<table" in rendered
    assert "<th>Metric</th>" in rendered
    assert "<td>Latency</td>" in rendered
    assert '<a href="https://example.org/folio"' in rendered
    assert 'rel="noopener noreferrer"' in rendered
    assert 'target="_blank"' in rendered


def test_preview_also_accessible_at_admin_root(client):
    """
    Verifies that the endpoint is also accessible as POST /admin/documents/preview.
    """
    csrf_admin = auth_login(client, "admin@folio.test")
    res = client.post(
        "/admin/documents/preview",
        headers={"X-CSRF-Token": csrf_admin},
        json={"content": "### Direct Admin Preview"}
    )
    assert res.status_code == 200
    assert "<h3>Direct Admin Preview</h3>" in res.json()["rendered_content"]
