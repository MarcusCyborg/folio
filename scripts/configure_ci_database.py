"""Configure CI database URLs using the PostgreSQL service's direct endpoint."""
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backend.core.test_db_guard import (
    sanitize_ambient_libpq_env,
    validate_test_database_target,
    verify_connected_identity,
)


def service_address(container_id):
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{json .NetworkSettings.Networks}}", container_id],
        check=True, capture_output=True, text=True,
    )
    networks = json.loads(result.stdout)
    if len(networks) != 1:
        raise RuntimeError("Expected exactly one network for the CI PostgreSQL service.")
    address = ipaddress.ip_address(next(iter(networks.values()))["IPAddress"])
    if address.is_loopback or address.is_unspecified or address.is_multicast:
        raise RuntimeError("Expected a direct PostgreSQL service address.")
    return str(address)


def main():
    sanitize_ambient_libpq_env()
    host = service_address(os.environ["POSTGRES_SERVICE_ID"])
    admin_url = URL.create(
        "postgresql+psycopg", username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"], host=host, port=5432, database="postgres",
    )
    urls = {
        "DATABASE_URL": admin_url.set(database="folio"),
        "TEST_DATABASE_URL": admin_url.set(database="folio_test"),
        "FOLIO_TEST_ADMIN_URL": admin_url,
    }
    target = validate_test_database_target(
        urls["TEST_DATABASE_URL"].render_as_string(hide_password=False),
        urls["DATABASE_URL"].render_as_string(hide_password=False),
    )
    engine = create_engine(admin_url, connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as connection:
            observed = connection.execute(text(
                "SELECT current_database(), inet_server_addr()::text, inet_server_port()"
            )).one()
            print(json.dumps({
                "expected_host": host, "expected_port": 5432,
                "connected_database": observed[0],
                "server_address": observed[1], "server_port": observed[2],
            }), flush=True)
            verify_connected_identity(connection, "postgres", target)
    finally:
        engine.dispose()

    # Publish only after the existing identity guard accepts the direct endpoint.
    with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as env_file:
        for name, url in urls.items():
            env_file.write(f"{name}={url.render_as_string(hide_password=False)}\n")


if __name__ == "__main__":
    main()
