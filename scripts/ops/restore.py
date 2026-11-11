#!/usr/bin/env python3
"""
Folio Disaster Recovery & Operations: Restore & Recovery Tool.
Executes automated, verified restoration (fail-closed on any integrity, SQL, migration, index, or smoke error):
1. Validates archive integrity and SHA-256 checksums before applying any changes.
2. Restores PostgreSQL database dump into target database via psql with ON_ERROR_STOP=1 and --single-transaction.
3. Runs Alembic migrations to guarantee forward schema compatibility.
4. Restores index generations or performs automated clean index rebuild from PostgreSQL documents.
5. Restores media and vector snapshots if present.
6. Executes post-restore smoke test (schema tables, document counts, index verification, search retrieval).
"""

import os
import sys
import json
import time
import shutil
import hashlib
import tarfile
import argparse
import tempfile
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from src.backend.core.config import settings
from src.backend.search_index.storage import get_index_storage_root
from scripts.ops.backup import (
    compute_sha256,
    find_pg_tool,
    get_media_storage_root,
    has_executable_sql,
    is_db_reachable,
    redact_db_url,
    sanitize_diagnostic_text,
)


class BackupIntegrityError(Exception):
    """Raised when backup archive, manifest, dump, or checksums are invalid or missing."""


class DatabaseRestoreError(Exception):
    """Raised when PostgreSQL database restore, migration, or DB smoke check fails."""


class IndexRecoveryError(Exception):
    """Raised when search index recovery, verification, or smoke search fails."""


def verify_checksums(backup_root: Path) -> Dict[str, bool]:
    """Verifies all files against checksums.sha256. Raises BackupIntegrityError on mismatch."""
    checksum_file = backup_root / "checksums.sha256"
    if not checksum_file.is_file():
        raise BackupIntegrityError(f"Missing checksums file: {checksum_file}")

    results: Dict[str, bool] = {}
    with open(checksum_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                continue
            expected_hash, rel_path_str = parts[0], parts[1].strip()
            file_path = backup_root / rel_path_str
            if not file_path.is_file():
                raise BackupIntegrityError(f"Corrupt backup: missing file declared in checksums: {rel_path_str}")
            actual_hash = compute_sha256(file_path)
            if actual_hash.lower() != expected_hash.lower():
                raise BackupIntegrityError(
                    f"Checksum mismatch for {rel_path_str}: expected {expected_hash}, got {actual_hash}"
                )
            results[rel_path_str] = True

    if not results:
        raise BackupIntegrityError("Checksums file contained no verifiable entries.")

    return results


def _extract_archive_if_needed(archive_path: Path):
    """Extracts tar archive to a temporary directory and returns (backup_root, temp_dir)."""
    if not archive_path.exists():
        raise BackupIntegrityError(f"Backup archive or directory does not exist: {archive_path}")

    if archive_path.is_file():
        temp_dir = Path(tempfile.mkdtemp(prefix="folio_restore_"))
        try:
            with tarfile.open(archive_path, "r:*") as tar:
                tar.extractall(path=temp_dir)
        except Exception as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise BackupIntegrityError(f"Failed to extract backup archive {archive_path}: {exc}") from exc
        subdirs = [p for p in temp_dir.iterdir() if p.is_dir()]
        backup_root = subdirs[0] if subdirs else temp_dir
        return backup_root, temp_dir

    return archive_path, None


def verify_backup_artifact(archive_path: Path) -> Dict[str, Any]:
    """
    Offline artifact integrity check only (does NOT restore to a database).
    Returns explicit status 'verified_offline' so it cannot be mistaken for a live database restore.
    """
    backup_root, temp_dir = _extract_archive_if_needed(Path(archive_path))
    try:
        verified_files = verify_checksums(backup_root)
        manifest_file = backup_root / "manifest.json"
        if not manifest_file.is_file():
            raise BackupIntegrityError(f"Missing manifest.json in backup root: {backup_root}")
        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        db_rel = manifest.get("components", {}).get("database", {}).get("file", "database/folio_dump.sql")
        db_dump_file = backup_root / db_rel
        if not db_dump_file.is_file():
            raise BackupIntegrityError(f"Missing database dump file in archive: {db_rel}")
        if not has_executable_sql(db_dump_file):
            raise BackupIntegrityError(f"Database dump file contains no executable SQL statements: {db_rel}")

        return {
            "status": "verified_offline",
            "backup_id": manifest.get("backup_id", "unknown"),
            "manifest_git_commit": manifest.get("git_commit", "unknown"),
            "manifest_alembic_head": manifest.get("alembic_head", "unknown"),
            "verified_files_count": len(verified_files),
            "database_dump_bytes": db_dump_file.stat().st_size,
        }
    finally:
        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def restore_database(dump_file: Path, target_db_url: str, timeout_seconds: int = 120):
    """
    Restores database dump into target PostgreSQL database via psql with ON_ERROR_STOP=1.
    Fails closed if psql is missing, dump has no executable SQL, or any SQL error occurs.
    """
    safe_url = redact_db_url(target_db_url)
    if not dump_file.is_file() or not has_executable_sql(dump_file):
        raise DatabaseRestoreError(
            f"Database dump file is missing, empty, or contains no executable SQL: {dump_file}"
        )

    psql_bin = find_pg_tool("psql")
    if not psql_bin:
        raise DatabaseRestoreError(
            "Required PostgreSQL restore utility 'psql' was not found. "
            "Install postgresql-client matching the server major version or set POSTGRES_BIN_PATH."
        )

    parsed_url = make_url(target_db_url)
    env = os.environ.copy()
    if parsed_url.password:
        env["PGPASSWORD"] = parsed_url.password

    cmd = [
        psql_bin,
        "-v", "ON_ERROR_STOP=1",
        "--single-transaction",
        "-h", parsed_url.host or "127.0.0.1",
        "-p", str(parsed_url.port or 5432),
        "-U", parsed_url.username or "postgres",
        "-d", parsed_url.database or "folio",
        "-f", str(dump_file),
    ]

    try:
        res = subprocess.run(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise DatabaseRestoreError(
            f"psql restore timed out after {timeout_seconds}s on {safe_url}"
        ) from exc
    except FileNotFoundError as exc:
        raise DatabaseRestoreError(
            f"psql binary could not be executed ({psql_bin}): {sanitize_diagnostic_text(str(exc), target_db_url)}"
        ) from exc
    except Exception as exc:
        raise DatabaseRestoreError(
            f"psql restore failed on {safe_url}: {sanitize_diagnostic_text(str(exc), target_db_url)}"
        ) from exc

    if res.returncode != 0:
        err_detail = sanitize_diagnostic_text(res.stderr or res.stdout or "unknown error", target_db_url)
        raise DatabaseRestoreError(
            f"psql restore failed on {safe_url} with code {res.returncode}: {err_detail.strip()}"
        )


def run_post_restore_migrations(target_db_url: str):
    """Executes Alembic migrations to head on restored database."""
    import argparse as _argparse
    from alembic.config import Config
    from alembic import command

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", target_db_url.replace("%", "%%"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    cfg.cmd_opts = _argparse.Namespace(x=[f"db_url={target_db_url}"])
    old_db_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = target_db_url
    try:
        command.upgrade(cfg, "head")
    finally:
        if old_db_url is not None:
            os.environ["DATABASE_URL"] = old_db_url
        else:
            os.environ.pop("DATABASE_URL", None)


def perform_restore(
    archive_path: Path,
    target_db_url: Optional[str] = None,
    rebuild_index: bool = False,
    skip_migrations: bool = False,
    skip_smoke_test: bool = False,
    restore_timeout_seconds: int = 120,
    index_storage_dir: Optional[Path] = None,
    media_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Executes consistent, fail-closed system restore from a backup archive or directory.
    """
    start_time = time.time()
    db_url = target_db_url or settings.DATABASE_URL
    safe_url = redact_db_url(db_url)

    backup_root, temp_dir = _extract_archive_if_needed(Path(archive_path))
    engine = None
    old_index_dir_env = os.environ.get("INDEX_STORAGE_DIR")

    try:
        # Step 1: Verify Checksums
        verified_files = verify_checksums(backup_root)

        # Step 2: Load Manifest & validate dump entry
        manifest_file = backup_root / "manifest.json"
        if not manifest_file.is_file():
            raise BackupIntegrityError(f"Missing manifest.json in backup root: {backup_root}")
        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        backup_id = manifest.get("backup_id", "unknown")
        manifest_git = manifest.get("git_commit", "unknown")
        manifest_alembic = manifest.get("alembic_head", "unknown")

        db_rel = manifest.get("components", {}).get("database", {}).get("file", "database/folio_dump.sql")
        db_dump_file = backup_root / db_rel
        if not db_dump_file.is_file():
            raise BackupIntegrityError(f"Database dump file missing from archive: {db_rel}")
        if not has_executable_sql(db_dump_file):
            raise BackupIntegrityError(f"Database dump file contains no executable SQL: {db_rel}")

        # Step 2b: Target database MUST be reachable (fail-closed)
        if not is_db_reachable(db_url, timeout=3.0):
            raise DatabaseRestoreError(f"Target database is unreachable during restore: {safe_url}")

        # Step 3: Restore Database Dump
        restore_database(db_dump_file, db_url, timeout_seconds=restore_timeout_seconds)

        # Step 4: Run Migrations
        if not skip_migrations:
            try:
                run_post_restore_migrations(db_url)
            except Exception as exc:
                clean_exc = sanitize_diagnostic_text(str(exc), db_url)
                raise DatabaseRestoreError(f"Alembic migration failed post-restore: {clean_exc}") from exc

        # Step 5: Restore or Rebuild Search Index
        index_status: Dict[str, Any] = {}
        index_src = backup_root / "index" / "generations"
        index_storage_root = (
            Path(index_storage_dir).resolve()
            if index_storage_dir is not None
            else get_index_storage_root()
        )
        index_storage_root.mkdir(parents=True, exist_ok=True)

        if index_storage_dir is not None:
            os.environ["INDEX_STORAGE_DIR"] = str(index_storage_root)

        from src.backend.search_index.manager import GenerationManager

        engine = create_engine(db_url, connect_args={"connect_timeout": 3})
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()

        try:
            if rebuild_index or not index_src.exists():
                gen = GenerationManager.build_new_generation(
                    db,
                    force=True,
                )
                v_res = GenerationManager.verify_generation(
                    db,
                    gen.id,
                )
                if not v_res.get("valid", False):
                    raise IndexRecoveryError(f"Rebuilt search generation failed verification: {v_res}")
                index_status = {
                    "action": "rebuilt_from_postgres",
                    "generation_id": gen.id,
                    "generation_num": gen.generation_num,
                    "doc_count": gen.doc_count,
                    "valid": True,
                }
            else:
                shutil.copytree(index_src, index_storage_root, dirs_exist_ok=True)
                active_gen = GenerationManager.get_active_generation(db)
                if active_gen:
                    v_res = GenerationManager.verify_generation(
                        db,
                        active_gen.id,
                    )
                    if not v_res.get("valid", False):
                        raise IndexRecoveryError(f"Restored search generation failed verification: {v_res}")
                    index_status = {
                        "action": "restored_from_backup",
                        "generation_id": active_gen.id,
                        "generation_num": active_gen.generation_num,
                        "doc_count": active_gen.doc_count,
                        "valid": True,
                    }
                else:
                    gen = GenerationManager.build_new_generation(
                        db,
                        force=True,
                    )
                    v_res = GenerationManager.verify_generation(
                        db,
                        gen.id,
                    )
                    if not v_res.get("valid", False):
                        raise IndexRecoveryError(f"Fallback rebuilt search generation failed verification: {v_res}")
                    index_status = {
                        "action": "rebuilt_no_active_gen_in_db",
                        "generation_id": gen.id,
                        "generation_num": gen.generation_num,
                        "doc_count": gen.doc_count,
                        "valid": True,
                    }
        finally:
            db.close()

        # Step 6: Restore Media & Vector
        media_src = backup_root / "media"
        media_dest = get_media_storage_root(media_dir=media_dir, create=True)
        if media_src.exists():
            shutil.copytree(media_src, media_dest, dirs_exist_ok=True)

        vector_src = backup_root / "vector"
        if vector_src.exists():
            vector_dest = Path(os.getenv("CHROMA_PATH") or settings.CHROMA_PATH)
            shutil.copytree(vector_src, vector_dest, dirs_exist_ok=True)

        # Step 7: Post-Restore Smoke Test (fail-closed)
        smoke_results: Dict[str, Any] = {}
        if not skip_smoke_test:
            db = SessionLocal()
            try:
                row_doc = db.execute(
                    text("SELECT count(*) FROM documents WHERE status = 'published' AND deleted_at IS NULL")
                ).scalar() or 0
                role_count = db.execute(text("SELECT count(*) FROM roles")).scalar() or 0
                user_count = db.execute(text("SELECT count(*) FROM users")).scalar() or 0
                smoke_results["published_documents_count"] = int(row_doc)
                smoke_results["roles_count"] = int(role_count)
                smoke_results["users_count"] = int(user_count)

                from src.backend.search.engine import SearchEngine, SearchQuery
                search_eng = SearchEngine()
                active_gen = GenerationManager.get_active_generation(db)
                if not active_gen:
                    raise IndexRecoveryError("Post-restore smoke test failed: no active search generation found.")

                q = SearchQuery(query="search", generation_id=active_gen.id, top_k=5)
                s_resp = search_eng.search(q)
                hits = s_resp.candidates
                total = s_resp.total_matches
                gen_num = active_gen.generation_num
                smoke_results["search_smoke_test"] = {
                    "query": "search",
                    "hits_count": len(hits),
                    "total": total,
                    "generation_num": gen_num,
                    "status": "passed",
                }
            except (BackupIntegrityError, DatabaseRestoreError, IndexRecoveryError):
                raise
            except Exception as exc:
                clean_exc = sanitize_diagnostic_text(str(exc), db_url)
                raise DatabaseRestoreError(f"Post-restore smoke test failed: {clean_exc}") from exc
            finally:
                db.close()

        elapsed = round(time.time() - start_time, 2)
        return {
            "status": "success",
            "backup_id": backup_id,
            "target_db": safe_url,
            "manifest_git_commit": manifest_git,
            "manifest_alembic_head": manifest_alembic,
            "verified_files_count": len(verified_files),
            "storage_paths": {
                "index_storage_dir": str(index_storage_root),
                "media_dir": str(media_dest),
            },
            "index_recovery": index_status,
            "smoke_test": smoke_results,
            "elapsed_seconds": elapsed,
        }

    finally:
        if index_storage_dir is not None:
            if old_index_dir_env is not None:
                os.environ["INDEX_STORAGE_DIR"] = old_index_dir_env
            else:
                os.environ.pop("INDEX_STORAGE_DIR", None)
        if engine is not None:
            engine.dispose()
        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="Folio Disaster Recovery Restore Tool")
    parser.add_argument(
        "--archive",
        "-a",
        type=Path,
        required=True,
        help="Path to backup archive (.tar.gz) or extracted backup directory",
    )
    parser.add_argument(
        "--target-db-url",
        type=str,
        default=None,
        help="PostgreSQL target connection string (defaults to DATABASE_URL)",
    )
    parser.add_argument(
        "--rebuild-index",
        action="store_true",
        help="Force rebuild lexical search index from PostgreSQL documents instead of copying index files",
    )
    parser.add_argument(
        "--index-storage-dir",
        type=Path,
        default=None,
        help="Target directory for restored lexical search index generations (defaults to INDEX_STORAGE_DIR)",
    )
    parser.add_argument(
        "--media-dir",
        type=Path,
        default=None,
        help="Target directory for restored media files (defaults to MEDIA_DIR or ./data/media)",
    )
    parser.add_argument(
        "--skip-migrations",
        action="store_true",
        help="Skip executing Alembic migrations after database restore",
    )
    parser.add_argument(
        "--skip-smoke-test",
        action="store_true",
        help="Skip running post-restore smoke search and query validation",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify archive checksums, manifest, and dump SQL offline without touching a database",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Timeout in seconds for psql restore execution (default: 120)",
    )
    args = parser.parse_args()

    try:
        if args.verify_only:
            report = verify_backup_artifact(archive_path=args.archive)
        else:
            report = perform_restore(
                archive_path=args.archive,
                target_db_url=args.target_db_url,
                rebuild_index=args.rebuild_index,
                skip_migrations=args.skip_migrations,
                skip_smoke_test=args.skip_smoke_test,
                restore_timeout_seconds=args.timeout,
                index_storage_dir=args.index_storage_dir,
                media_dir=args.media_dir,
            )
        print(json.dumps(report, indent=2))
        return 0
    except Exception as err:
        safe_err = sanitize_diagnostic_text(str(err), args.target_db_url or settings.DATABASE_URL)
        print(json.dumps({"status": "failed", "error": safe_err}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
