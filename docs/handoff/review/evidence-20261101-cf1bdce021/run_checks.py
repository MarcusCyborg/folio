import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

root = Path(__file__).resolve().parent
repo = Path("F:/dpl13.10/WikiSearchEngine-github")
env = os.environ.copy()
env.update(APP_ENV="test", COOKIE_SECURE="false", ENABLE_LEGACY_SEARCH="false",
    PYTHONDONTWRITEBYTECODE="1", PYTHON_DOTENV_DISABLED="1", PYTHONPATH=str(repo))
results = []
# Reserve an unlistened local port so no existing database can receive review commands.
with socket.socket() as reserved:
    reserved.bind(("127.0.0.1", 0))
    port = reserved.getsockname()[1]
    env["DATABASE_URL"] = f"postgresql+psycopg://review@127.0.0.1:{port}/ia_review_main_test?connect_timeout=1"
    env["TEST_DATABASE_URL"] = f"postgresql+psycopg://review@127.0.0.1:{port}/ia_review_suite_test?connect_timeout=1"
    checks = [
        ("migration-heads", ["-m", "alembic", "heads"]),
        ("migration-offline", ["-m", "alembic", "upgrade", "head", "--sql"]),
        ("migration-online-unavailable", ["-m", "alembic", "upgrade", "head"]),
        ("backend-collect", ["-m", "pytest", "tests/backend", "--collect-only", "-q", "-p", "no:cacheprovider"]),
        ("backend-suite-unavailable", ["-m", "pytest", "tests/backend", "-q", "--maxfail=1", "--tb=short", "-p", "no:cacheprovider", "--junitxml=" + str(root / "backend-junit.xml")]),
        ("frontend-collect", ["-m", "pytest", "tests/frontend", "--collect-only", "-q", "-p", "no:cacheprovider"]),
    ]
    for label, args in checks:
        cp = subprocess.run([sys.executable, *args], cwd=repo, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        (root / (label + ".log")).write_text(cp.stdout + cp.stderr, encoding="utf-8")
        result = {"check": label, "command": ["python", *args], "cwd": str(repo), "exit_code": cp.returncode}
        results.append(result)
        print(json.dumps(result), flush=True)

cp = subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True)
(root / "pip-freeze.txt").write_text(cp.stdout, encoding="utf-8")
(root / "checks.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
