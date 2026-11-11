#!/usr/bin/env python3
"""
Folio Disaster Recovery & Operations: Backup Tool.
Creates consistent, verifiable backups containing:
1. PostgreSQL schema and data dump via pg_dump (fail-closed if unavailable or failing).
2. Search index generations, postings, and manifests (rebuildable component).
3. Media uploads and metadata (required component).
4. Optional ChromaDB vector snapshot.
5. Cryptographic checksums (SHA-256) and manifest metadata (Git SHA, Alembic head, timestamps).
"""

import os
import re
import sys
import json
import time
import shutil
import hashlib
import tarfile
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from src.backend.core.config import settings
from src.backend.search_index.storage import get_index_storage_root


def get_media_storage_root(media_dir: Optional[Path] = None, create: bool = False) -> Path:
    """
    Resolves effective media storage directory cleanly:
    explicit media_dir > MEDIA_DIR > MEDIA_UPLOAD_DIR > PROJECT_ROOT / 'data' / 'media'.
    """
    if media_dir is not None:
        root = Path(media_dir).resolve()
    else:
        env_path = os.getenv("MEDIA_DIR") or os.getenv("MEDIA_UPLOAD_DIR")
        if env_path and env_path.strip():
            root = Path(env_path.strip()).resolve()
        else:
            root = (PROJECT_ROOT / "data" / "media").resolve()
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


class DatabaseBackupError(RuntimeError):
    """Raised when PostgreSQL backup cannot be completed reliably."""


_SECRET_QUERY_PATTERN = re.compile(
    r"([?&](?:password|passwd|pwd|token|access_token|secret|api_key|apikey|key)=)([^&\s'\"]+)",
    re.IGNORECASE,
)
_URL_CREDENTIAL_PATTERN = re.compile(
    r"([a-zA-Z][a-zA-Z0-9+.-]*://[^:/\s@]+:)([^@\s]+)(@)"
)


def redact_db_url(raw_url: str) -> str:
    """Safely renders a database URL with password and sensitive query tokens masked."""
    if not raw_url:
        return "<unset>"
    try:
        parsed = make_url(raw_url)
        if parsed.query:
            redacted_query = {
                k: ("***" if k.lower() in {"password", "passwd", "pwd", "token", "access_token", "secret", "api_key", "apikey"} else v)
                for k, v in parsed.query.items()
            }
            parsed = parsed.set(query=redacted_query)
        return parsed.render_as_string(hide_password=True)
    except Exception:
        sanitized = _URL_CREDENTIAL_PATTERN.sub(r"\1***\3", str(raw_url))
        return _SECRET_QUERY_PATTERN.sub(r"\1***", sanitized)


def sanitize_diagnostic_text(message: str, raw_url: Optional[str] = None) -> str:
    """Strips database credentials and sensitive query tokens from diagnostic messages."""
    text_out = str(message or "")
    if raw_url:
        try:
            parsed = make_url(raw_url)
            if parsed.password:
                text_out = text_out.replace(parsed.password, "***")
            for k, v in (parsed.query or {}).items():
                if v and k.lower() in {"password", "passwd", "pwd", "token", "access_token", "secret", "api_key", "apikey"}:
                    text_out = text_out.replace(str(v), "***")
        except Exception:
            pass
    text_out = _URL_CREDENTIAL_PATTERN.sub(r"\1***\3", text_out)
    text_out = _SECRET_QUERY_PATTERN.sub(r"\1***", text_out)
    return text_out


def find_pg_tool(tool_name: str) -> Optional[str]:
    """
    Locates PostgreSQL client executables (pg_dump, psql, pg_restore) via:
    1. POSTGRES_BIN_PATH environment override
    2. System PATH
    3. Standard OS PostgreSQL installation directories
    """
    exe_suffix = ".exe" if sys.platform == "win32" else ""
    custom_bin = os.environ.get("POSTGRES_BIN_PATH")
    if custom_bin:
        cand = Path(custom_bin) / f"{tool_name}{exe_suffix}"
        if cand.is_file():
            return str(cand)

    found = shutil.which(tool_name)
    if found:
        return found

    standard_paths = [
        Path("/usr/lib/postgresql/17/bin") / tool_name,
        Path("/usr/lib/postgresql/16/bin") / tool_name,
        Path("/usr/bin") / tool_name,
        Path("/usr/local/bin") / tool_name,
        Path("C:/Program Files/PostgreSQL/17/bin") / f"{tool_name}.exe",
        Path("C:/Program Files/PostgreSQL/16/bin") / f"{tool_name}.exe",
    ]
    for p in standard_paths:
        if p.is_file():
            return str(p)
    return None


def compute_sha256(file_path: Path) -> str:
    """Computes SHA-256 hex digest of a file in chunks."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def compute_directory_hash(dir_path: Path) -> str:
    """Computes a deterministic composite hash for all files in a directory."""
    if not dir_path.exists():
        return hashlib.sha256(b"").hexdigest()
    h = hashlib.sha256()
    for root, _, files in sorted(os.walk(dir_path)):
        for f in sorted(files):
            fp = Path(root) / f
            rel = fp.relative_to(dir_path).as_posix()
            h.update(rel.encode("utf-8"))
            h.update(compute_sha256(fp).encode("utf-8"))
    return h.hexdigest()


def is_db_reachable(db_url: str, timeout: float = 2.0) -> bool:
    """Fast check whether PostgreSQL instance responds within timeout."""
    engine = None
    try:
        engine = create_engine(db_url, connect_args={"connect_timeout": max(1, int(timeout))})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1;"))
        return True
    except Exception:
        return False
    finally:
        if engine is not None:
            engine.dispose()


def resolve_git_commit() -> str:
    """Attempts to resolve the exact HEAD commit SHA."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(PROJECT_ROOT),
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return out.strip()
    except Exception:
        return "unknown"


def resolve_alembic_head() -> str:
    """Resolves the current linear Alembic head revision."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
        script = ScriptDirectory.from_config(cfg)
        return script.get_current_head() or "unknown"
    except Exception:
        return "unknown"


def has_executable_sql(dump_file: Path) -> bool:
    """Verifies that a SQL dump contains actual executable SQL statements, not only comments."""
    if not dump_file.is_file() or dump_file.stat().st_size == 0:
        return False
    with open(dump_file, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            stripped = line.strip()
            if stripped and not stripped.startswith("--"):
                return True
    return False


def dump_postgresql_database(dump_file: Path, target_db_url: str, timeout_seconds: int = 120) -> Dict[str, Any]:
    """
    Executes pg_dump against target_db_url and validates non-empty executable SQL output.
    Fails closed if DB is offline, pg_dump is missing, times out, or returns non-zero.
    """
    safe_url = redact_db_url(target_db_url)
    if not is_db_reachable(target_db_url, timeout=3.0):
        raise DatabaseBackupError(f"PostgreSQL target is unreachable during backup: {safe_url}")

    pg_dump_bin = find_pg_tool("pg_dump")
    if not pg_dump_bin:
        raise DatabaseBackupError(
            "Required PostgreSQL backup utility 'pg_dump' was not found. "
            "Install postgresql-client matching the server major version or set POSTGRES_BIN_PATH."
        )

    parsed_url = make_url(target_db_url)
    env = os.environ.copy()
    if parsed_url.password:
        env["PGPASSWORD"] = parsed_url.password

    cmd = [
        pg_dump_bin,
        "-h", parsed_url.host or "127.0.0.1",
        "-p", str(parsed_url.port or 5432),
        "-U", parsed_url.username or "postgres",
        "-d", parsed_url.database or "folio",
        "-F", "p",
        "--no-owner",
        "--no-acl",
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
        raise DatabaseBackupError(
            f"pg_dump timed out after {timeout_seconds}s on {safe_url}"
        ) from exc
    except FileNotFoundError as exc:
        raise DatabaseBackupError(
            f"pg_dump binary could not be executed ({pg_dump_bin}): {sanitize_diagnostic_text(str(exc), target_db_url)}"
        ) from exc
    except Exception as exc:
        raise DatabaseBackupError(
            f"pg_dump execution failed on {safe_url}: {sanitize_diagnostic_text(str(exc), target_db_url)}"
        ) from exc

    if res.returncode != 0:
        err_detail = sanitize_diagnostic_text(res.stderr or res.stdout or "unknown error", target_db_url)
        raise DatabaseBackupError(
            f"pg_dump exited with code {res.returncode} on {safe_url}: {err_detail.strip()}"
        )

    if not has_executable_sql(dump_file):
        raise DatabaseBackupError(
            f"pg_dump produced an empty or comment-only dump file on {safe_url}; refusing to mark backup successful."
        )

    return {
        "tool": Path(pg_dump_bin).name,
        "target": safe_url,
    }


def perform_backup(
    output_dir: Path,
    db_url: Optional[str] = None,
    include_vector: bool = False,
    label: Optional[str] = None,
    dump_timeout_seconds: int = 120,
    index_storage_dir: Optional[Path] = None,
    media_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Executes consistent system backup and writes a compressed .tar.gz bundle.
    Fails closed if database dump or required artifacts cannot be captured.
    """
    start_time = time.time()
    now_utc = datetime.now(timezone.utc)
    timestamp_str = now_utc.strftime("%Y%m%d_%H%M%S_%f")
    backup_id = f"folio_backup_{timestamp_str}"
    if label:
        safe_label = re.sub(r"[^a-zA-Z0-9_-]", "_", label.strip())
        if safe_label:
            backup_id += f"_{safe_label}"

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    staging_dir = output_dir / backup_id
    staging_dir.mkdir(parents=True, exist_ok=True)

    target_db_url = db_url or settings.DATABASE_URL
    git_sha = resolve_git_commit()
    alembic_head = resolve_alembic_head()

    components: Dict[str, Any] = {}
    checksums: Dict[str, str] = {}
    archive_path = output_dir / f"{backup_id}.tar.gz"

    try:
        # 1. PostgreSQL Database Dump (Required, fail-closed)
        db_dir = staging_dir / "database"
        db_dir.mkdir(parents=True, exist_ok=True)
        dump_file = db_dir / "folio_dump.sql"

        dump_meta = dump_postgresql_database(
            dump_file=dump_file,
            target_db_url=target_db_url,
            timeout_seconds=dump_timeout_seconds,
        )

        db_sha256 = compute_sha256(dump_file)
        rel_dump = dump_file.relative_to(staging_dir).as_posix()
        checksums[rel_dump] = db_sha256
        components["database"] = {
            "file": rel_dump,
            "format": "sql",
            "size_bytes": dump_file.stat().st_size,
            "sha256": db_sha256,
            "status": "dumped",
            "required": True,
            "rebuildable": False,
            "tool": dump_meta["tool"],
        }

        # 2. Search Index Snapshot (Rebuildable from PostgreSQL)
        index_dir = staging_dir / "index"
        index_storage_root = (
            Path(index_storage_dir).resolve()
            if index_storage_dir is not None
            else get_index_storage_root()
        )
        index_files_count = 0
        active_gen_info: Dict[str, Any] = {}

        if index_storage_root.exists():
            shutil.copytree(index_storage_root, index_dir / "generations", dirs_exist_ok=True)
            for r, _, fls in os.walk(index_dir):
                index_files_count += len(fls)
                for f in fls:
                    fp = Path(r) / f
                    rel = fp.relative_to(staging_dir).as_posix()
                    checksums[rel] = compute_sha256(fp)

        try:
            from sqlalchemy.orm import sessionmaker
            from src.backend.search_index.manager import GenerationManager

            eng = create_engine(target_db_url, connect_args={"connect_timeout": 3})
            try:
                SessionLocal = sessionmaker(bind=eng)
                db = SessionLocal()
                try:
                    active_gen = GenerationManager.get_active_generation(db)
                    if active_gen:
                        active_gen_info = {
                            "generation_id": active_gen.id,
                            "generation_num": active_gen.generation_num,
                            "doc_count": active_gen.doc_count,
                            "status": active_gen.status,
                        }
                finally:
                    db.close()
            finally:
                eng.dispose()
        except Exception:
            pass

        index_sha256 = compute_directory_hash(index_dir)
        components["index"] = {
            "files_count": index_files_count,
            "composite_sha256": index_sha256,
            "active_generation": active_gen_info,
            "required": False,
            "rebuildable": True,
        }

        # 3. Media Uploads (Required if present)
        media_src = get_media_storage_root(media_dir=media_dir, create=False)
        media_staging_dir = staging_dir / "media"
        media_files_count = 0
        if media_src.exists():
            shutil.copytree(media_src, media_staging_dir, dirs_exist_ok=True)
            for r, _, fls in os.walk(media_staging_dir):
                media_files_count += len(fls)
                for f in fls:
                    fp = Path(r) / f
                    rel = fp.relative_to(staging_dir).as_posix()
                    checksums[rel] = compute_sha256(fp)

        components["media"] = {
            "files_count": media_files_count,
            "composite_sha256": compute_directory_hash(media_staging_dir),
            "required": True,
            "rebuildable": False,
        }

        # 4. Semantic / Vector Data (Optional)
        vector_src = Path(os.getenv("CHROMA_PATH") or settings.CHROMA_PATH)
        components["semantic"] = {
            "included": False,
            "status": "disabled",
            "required": False,
            "rebuildable": True,
        }
        if include_vector:
            if not vector_src.exists():
                raise DatabaseBackupError(
                    f"--include-vector was requested, but CHROMA_PATH does not exist: {vector_src}"
                )
            vector_dir = staging_dir / "vector"
            shutil.copytree(vector_src, vector_dir, dirs_exist_ok=True)
            vec_count = 0
            for r, _, fls in os.walk(vector_dir):
                vec_count += len(fls)
                for f in fls:
                    fp = Path(r) / f
                    rel = fp.relative_to(staging_dir).as_posix()
                    checksums[rel] = compute_sha256(fp)
            components["semantic"] = {
                "included": True,
                "status": "backed_up",
                "files_count": vec_count,
                "composite_sha256": compute_directory_hash(vector_dir),
                "required": False,
                "rebuildable": True,
            }

        # 5. Write Checksums File
        checksum_file = staging_dir / "checksums.sha256"
        with open(checksum_file, "w", encoding="utf-8") as f:
            for path_str in sorted(checksums.keys()):
                f.write(f"{checksums[path_str]}  {path_str}\n")

        # 6. Write Manifest
        manifest = {
            "version": "2.0.0",
            "backup_id": backup_id,
            "created_at": now_utc.isoformat(),
            "git_commit": git_sha,
            "alembic_head": alembic_head,
            "components": components,
            "required_components": ["database", "media"],
            "rebuildable_components": ["index"],
            "checksums_file": "checksums.sha256",
        }
        manifest_file = staging_dir / "manifest.json"
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        # 7. Create Archive (.tar.gz) atomically via temp file
        tmp_archive = output_dir / f".{backup_id}.tar.gz.tmp"
        with tarfile.open(tmp_archive, "w:gz") as tar:
            tar.add(staging_dir, arcname=backup_id)
        tmp_archive.replace(archive_path)

        # Clean up staging directory
        shutil.rmtree(staging_dir)

        elapsed = round(time.time() - start_time, 2)
        archive_sha = compute_sha256(archive_path)

        return {
            "status": "success",
            "backup_id": backup_id,
            "archive_path": str(archive_path),
            "archive_sha256": archive_sha,
            "archive_size_bytes": archive_path.stat().st_size,
            "git_commit": git_sha,
            "alembic_head": alembic_head,
            "elapsed_seconds": elapsed,
            "storage_paths": {
                "index_storage_dir": str(index_storage_root),
                "media_dir": str(media_src),
            },
            "manifest": manifest,
        }

    except Exception as exc:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        tmp_archive = output_dir / f".{backup_id}.tar.gz.tmp"
        if tmp_archive.exists():
            tmp_archive.unlink(missing_ok=True)
        if archive_path.exists():
            archive_path.unlink(missing_ok=True)
        clean_err = sanitize_diagnostic_text(str(exc), target_db_url)
        if isinstance(exc, DatabaseBackupError):
            raise DatabaseBackupError(clean_err) from exc
        raise DatabaseBackupError(f"Backup failed: {clean_err}") from exc


def main():
    parser = argparse.ArgumentParser(description="Folio Disaster Recovery Backup Tool")
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=PROJECT_ROOT / "backups",
        help="Directory to save backup archives (default: ./backups)",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help="PostgreSQL connection string (defaults to DATABASE_URL)",
    )
    parser.add_argument(
        "--include-vector",
        action="store_true",
        help="Include ChromaDB semantic vector storage directory in backup",
    )
    parser.add_argument(
        "--label",
        type=str,
        default=None,
        help="Optional label to append to backup identifier",
    )
    parser.add_argument(
        "--index-storage-dir",
        type=Path,
        default=None,
        help="Search index generations directory to snapshot (defaults to INDEX_STORAGE_DIR)",
    )
    parser.add_argument(
        "--media-dir",
        type=Path,
        default=None,
        help="Media storage directory to snapshot (defaults to MEDIA_DIR or ./data/media)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Timeout in seconds for pg_dump execution (default: 120)",
    )
    args = parser.parse_args()

    try:
        report = perform_backup(
            output_dir=args.output_dir,
            db_url=args.db_url,
            include_vector=args.include_vector,
            label=args.label,
            dump_timeout_seconds=args.timeout,
            index_storage_dir=args.index_storage_dir,
            media_dir=args.media_dir,
        )
        print(json.dumps(report, indent=2))
        return 0
    except Exception as err:
        safe_err = sanitize_diagnostic_text(str(err), args.db_url or settings.DATABASE_URL)
        print(json.dumps({"status": "failed", "error": safe_err}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
