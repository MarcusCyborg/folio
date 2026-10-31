def test_health_check_no_ml_dependency(client):
    """Health check must return 200 without loading chromadb or sentence transformers."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["database"] == "ok"
    assert data["legacy_search"] == "disabled"

def test_legacy_search_flag_disabled(client):
    """When ENABLE_LEGACY_SEARCH is false, /search returns clear 503 error."""
    res = client.get("/search?q=quantum")
    assert res.status_code == 503
    data = res.json()
    assert data["error"]["code"] == "LEGACY_SEARCH_DISABLED"

def test_feature_routes_live_response(client):
    """Router routes return actual data once implemented."""
    res = client.get("/api/v1/documents")
    assert res.status_code == 200
    assert "items" in res.json()
