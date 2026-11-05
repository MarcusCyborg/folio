"""CI endpoint setup must preserve connected-identity checks before publishing URLs."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.engine import make_url

from scripts import configure_ci_database as ci
from src.backend.core.test_db_guard import ConnectedIdentityMismatchError


@pytest.mark.parametrize("networks", [
    {},
    {"one": {"IPAddress": "172.18.0.2"}, "two": {"IPAddress": "172.19.0.2"}},
    {"one": {"IPAddress": ""}},
    {"one": {"IPAddress": "127.0.0.1"}},
])
def test_service_address_rejects_ambiguous_or_invalid_endpoint(monkeypatch, networks):
    monkeypatch.setattr(ci.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(networks)))
    with pytest.raises((RuntimeError, ValueError)):
        ci.service_address("service-container-id")


@pytest.mark.parametrize("database,address,port,accepted", [
    ("postgres", "172.18.0.2/32", 5432, True),
    ("postgres", "172.18.0.3/32", 5432, False),
    ("postgres", "172.18.0.2/32", 5433, False),
    ("folio", "172.18.0.2/32", 5432, False),
])
def test_ci_urls_published_only_after_identity_check(monkeypatch, tmp_path, capsys, database, address, port, accepted):
    env_file = tmp_path / "github-env"
    env_file.write_text("EXISTING=value\n", encoding="utf-8")
    for key, value in {
        "GITHUB_ENV": str(env_file), "POSTGRES_SERVICE_ID": "service-container-id",
        "POSTGRES_USER": "postgres", "POSTGRES_PASSWORD": "test-password",
    }.items():
        monkeypatch.setenv(key, value)
    inspect = MagicMock(return_value=SimpleNamespace(stdout=json.dumps({
        "github-network": {"IPAddress": "172.18.0.2"},
    })))
    monkeypatch.setattr(ci.subprocess, "run", inspect)
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.one.return_value = (database, address, port)
    connection.execute.return_value.fetchone.return_value = (database, "postgres", address, port)
    monkeypatch.setattr(ci, "create_engine", lambda *args, **kwargs: engine)
    if accepted:
        ci.main()
        entries = dict(line.split("=", 1) for line in env_file.read_text(encoding="utf-8").splitlines())
        for name, expected_database in {
            "DATABASE_URL": "folio", "TEST_DATABASE_URL": "folio_test", "FOLIO_TEST_ADMIN_URL": "postgres",
        }.items():
            url = make_url(entries[name])
            assert (url.host, url.port, url.database, url.password) == (
                "172.18.0.2", 5432, expected_database, "test-password",
            )
    else:
        with pytest.raises(ConnectedIdentityMismatchError):
            ci.main()
        assert env_file.read_text(encoding="utf-8") == "EXISTING=value\n"
    assert inspect.call_args.args[0][-1] == "service-container-id"
    engine.dispose.assert_called_once()
    assert "test-password" not in capsys.readouterr().out
