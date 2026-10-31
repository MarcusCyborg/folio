def test_frontend_static_files_resolve(client):
    """Verifies that index.html and all frontend core modules resolve properly."""
    res_index = client.get("/")
    assert res_index.status_code == 200
    assert "Folio" in res_index.text
    assert '<script type="module" src="app.js">' in res_index.text

    res_app = client.get("/app.js")
    assert res_app.status_code == 200
    assert "bootstrap" in res_app.text

    res_css = client.get("/style.css")
    assert res_css.status_code == 200
    assert "--color-bg" in res_css.text

    # Verify core modules
    assert client.get("/core/api.js").status_code == 200
    assert client.get("/core/session.js").status_code == 200
    assert client.get("/core/router.js").status_code == 200
    assert client.get("/core/ui.js").status_code == 200

    # Verify public lane views & assets
    assert client.get("/public/index.js").status_code == 200
    assert client.get("/public/public.css").status_code == 200
    assert client.get("/public/library_view.js").status_code == 200
    assert client.get("/public/detail_view.js").status_code == 200
    assert client.get("/public/auth_views.js").status_code == 200

    # Verify admin lane views & assets
    assert client.get("/admin/index.js").status_code == 200
    assert client.get("/admin/admin.css").status_code == 200
    assert client.get("/admin/admin_shell.js").status_code == 200
    assert client.get("/admin/content_views.js").status_code == 200
    assert client.get("/admin/moderation_views.js").status_code == 200
    assert client.get("/admin/governance_views.js").status_code == 200
    assert client.get("/admin/analytics_views.js").status_code == 200
