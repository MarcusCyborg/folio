from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.backend.main import app
from src.backend.core.exceptions import AppException
from src.backend.services.admin.database_service import (
    admin_get_database_table_rows,
    admin_list_database_tables,
)


def test_docs_csp_allows_swagger_assets_while_root_is_strict():
    client = TestClient(app)

    docs_resp = client.get("/docs")
    assert docs_resp.status_code == 200
    docs_csp = docs_resp.headers.get("content-security-policy", "")
    assert "https://cdn.jsdelivr.net" in docs_csp
    assert "'unsafe-inline'" in docs_csp

    root_resp = client.get("/")
    assert root_resp.status_code == 200
    root_csp = root_resp.headers.get("content-security-policy", "")
    assert "script-src 'self';" in root_csp
    assert "cdn.jsdelivr.net" not in root_csp


def test_database_explorer_lists_tables_and_redacts_sensitive_columns():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO users (id, username, password_hash) VALUES (1, 'alice', 'super_secret_hash')"
            )
        )

    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as db:
        tables_res = admin_list_database_tables(db)
        assert tables_res["dialect"] == "sqlite"
        assert tables_res["tables"] == [
            {"name": "users", "column_count": 3, "row_count": 1}
        ]

        rows_res = admin_get_database_table_rows(db, "users", page=1, page_size=25)
        assert rows_res["table"] == "users"
        assert rows_res["total"] == 1
        assert rows_res["rows"] == [
            {"id": 1, "username": "alice", "password_hash": "[REDACTED]"}
        ]

        try:
            admin_get_database_table_rows(db, "nonexistent_table")
            assert False, "Expected AppException for missing table"
        except AppException as exc:
            assert exc.status_code == 404
            assert exc.code == "TABLE_NOT_FOUND"
