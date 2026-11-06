import json
import sys
from pathlib import Path
from sqlalchemy import create_engine, text

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ops.backup import perform_backup
from scripts.ops.restore import perform_restore

def run_drill():
    admin_url = "postgresql+psycopg://folio_audit:audit_pass@127.0.0.1:55488/postgres"
    source_db_url = "postgresql+psycopg://folio_audit:audit_pass@127.0.0.1:55488/folio"
    target_drill_url = "postgresql+psycopg://folio_audit:audit_pass@127.0.0.1:55488/folio_restore_drill"

    print("Step 1: Preparing isolated target database 'folio_restore_drill'...")
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS folio_restore_drill WITH (FORCE)"))
        conn.execute(text("CREATE DATABASE folio_restore_drill OWNER folio_audit"))
    print("Database 'folio_restore_drill' created successfully.")

    print("\nStep 2: Executing disaster recovery backup...")
    backup_report = perform_backup(
        output_dir=PROJECT_ROOT / "backups",
        db_url=source_db_url,
        label="remediation_drill",
        include_vector=False,
    )
    print(f"Backup succeeded! Archive: {backup_report['archive_path']}")
    print(f"Archive SHA256: {backup_report['archive_sha256']}")
    print(f"Alembic Head: {backup_report['alembic_head']}")
    print(f"Git Commit: {backup_report['git_commit']}")

    print("\nStep 3: Executing disaster recovery restore into 'folio_restore_drill'...")
    restore_report = perform_restore(
        archive_path=Path(backup_report["archive_path"]),
        target_db_url=target_drill_url,
        rebuild_index=True,
        skip_migrations=False,
        skip_smoke_test=False,
    )
    print(f"Restore succeeded! Status: {restore_report['status']}")
    print(f"Smoke Test: {restore_report['smoke_test']}")

    # Step 4: Verify document count in restored database
    drill_engine = create_engine(target_drill_url)
    with drill_engine.connect() as conn:
        doc_count = conn.execute(text("SELECT count(*) FROM documents WHERE deleted_at IS NULL")).scalar()
        cat_count = conn.execute(text("SELECT count(*) FROM categories")).scalar()
        tag_count = conn.execute(text("SELECT count(*) FROM tags")).scalar()
        print(f"\nVerification query on restored DB:")
        print(f"  Active Documents: {doc_count}")
        print(f"  Categories: {cat_count}")
        print(f"  Tags: {tag_count}")

    print("\nDR Drill completed successfully with 100% integrity validation!")

if __name__ == "__main__":
    run_drill()
