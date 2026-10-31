import ast
from collections import Counter
import json
from pathlib import Path
import uuid
from sqlalchemy.engine import make_url

main = Path("F:/dpl13.10/WikiSearchEngine-github")
p02 = Path("F:/dpl13.10/WikiSearchEngine-p02")
tree = ast.parse((p02 / "tests/conftest.py").read_text(encoding="utf-8-sig"))
node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "validate_test_database_safety")
scope = {"make_url": make_url}
exec(compile(ast.Module(body=[node], type_ignores=[]), "tests/conftest.py", "exec"), scope)
guard = scope[node.name]
results = {"guard": []}
for label, test_url, main_url in [
    ("same_literal_target", "postgresql://review@127.0.0.1:5432/folio_test", "postgresql://review@127.0.0.1:5432/folio_test"),
    ("same_target_implicit_default_port", "postgresql://review@127.0.0.1/folio_test", "postgresql://review@127.0.0.1:5432/folio_test"),
    ("same_target_host_alias", "postgresql://review@localhost:5432/folio_test", "postgresql://review@127.0.0.1:5432/folio_test"),
    ("postgresql_query_target_override", "postgresql+psycopg://review@127.0.0.1:5432/review_test?dbname=folio", "postgresql+psycopg://review@127.0.0.1:5432/folio"),
    ("protected_main_name", "postgresql://review@127.0.0.1:5432/folio", "postgresql://review@127.0.0.1:5432/folio"),
]:
    try:
        guard(test_url, main_url)
        accepted = True
    except RuntimeError:
        accepted = False
    item = {"case": label, "accepted": accepted}
    if "query_target" in label:
        from sqlalchemy import create_engine
        engine = create_engine(test_url)
        args, kwargs = engine.dialect.create_connect_args(engine.url)
        item["actual_driver_dbname"] = kwargs.get("dbname")
        engine.dispose()
    results["guard"].append(item)

fixture = [json.loads(line) for line in (main / "fixtures/folio/documents.jsonl").read_text(encoding="utf-8-sig").splitlines() if line.strip()]
results["fixture"] = {"rows": len(fixture), "status_counts": dict(Counter(x.get("status") for x in fixture)),
    "id_versions": dict(Counter(uuid.UUID(x["id"]).version for x in fixture)),
    "unique_ids": len({x["id"] for x in fixture}), "unique_source_urls": len({x.get("source_url") for x in fixture})}
print(json.dumps(results, indent=2))
