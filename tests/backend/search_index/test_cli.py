import json
from pathlib import Path
import pytest
from src.backend.search_index.cli import main


def test_cli_import_corpus_dry_run(tmp_path: Path, capsys):
    corpus_file = tmp_path / "sample_corpus.jsonl"
    corpus_file.write_text(
        json.dumps({
            "title": "CLI Test Doc",
            "content": "Content of CLI test doc.",
            "url": "https://en.wikipedia.org/wiki/CLI_Test_Doc",
        }),
        encoding="utf-8",
    )

    exit_code = main(["import-corpus", "--input", str(corpus_file), "--dry-run"])
    assert exit_code == 0

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["dry_run"] is True
    assert report["total_scanned"] == 1
    assert report["valid_records"] == 1


def test_cli_build_and_verify_index(capsys):
    # 1. Build index
    build_code = main(["build-index", "--force", "--verify"])
    assert build_code == 0
    build_out = json.loads(capsys.readouterr().out)
    assert build_out["status"] == "success"
    assert "generation_id" in build_out

    gen_id = build_out["generation_id"]

    # 2. Verify index
    verify_code = main(["verify-index", "--generation", gen_id])
    assert verify_code == 0
    verify_out = json.loads(capsys.readouterr().out)
    assert verify_out["valid"] is True
    assert verify_out["generation_id"] == gen_id


def test_cli_index_status(capsys):
    status_code = main(["index-status"])
    assert status_code == 0
    status_out = json.loads(capsys.readouterr().out)
    assert "active_generation" in status_out
    assert "outbox_jobs" in status_out
    assert "index_lag_seconds" in status_out
