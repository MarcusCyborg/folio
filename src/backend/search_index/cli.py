import sys
import json
import argparse
from pathlib import Path
from typing import Optional

from src.backend.core.database import SessionLocal
from src.backend.search_index.importer import CorpusImporter
from src.backend.search_index.manager import GenerationManager, IndexBuildError, IndexVerificationError


def cmd_import_corpus(args) -> int:
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file does not exist: {input_path}", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        importer = CorpusImporter(db, dry_run=args.dry_run)
        report = importer.import_corpus(
            input_path,
            batch_size=args.batch_size,
            backfill_images=getattr(args, "backfill_images", False),
        )
        print(json.dumps(report, indent=2))
        return 0
    finally:
        db.close()


def cmd_build_index(args) -> int:
    db = SessionLocal()
    try:
        gen = GenerationManager.build_new_generation(db, force=args.force)
        res = {
            "status": "success",
            "generation_id": gen.id,
            "generation_num": gen.generation_num,
            "doc_count": gen.doc_count,
            "active_at": gen.active_at.isoformat() if gen.active_at else None,
        }
        if args.verify:
            verify_res = GenerationManager.verify_generation(db, gen.id)
            res["verification"] = verify_res

        print(json.dumps(res, indent=2))
        return 0
    except (IndexBuildError, IndexVerificationError) as err:
        print(json.dumps({"status": "failed", "error": str(err)}, indent=2), file=sys.stderr)
        return 1
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    finally:
        db.close()


def cmd_verify_index(args) -> int:
    db = SessionLocal()
    try:
        result = GenerationManager.verify_generation(db, generation_id=args.generation)
        print(json.dumps(result, indent=2))
        return 0 if result.get("valid") else 1
    finally:
        db.close()


def cmd_index_status(args) -> int:
    db = SessionLocal()
    try:
        status = GenerationManager.get_index_status(db)
        print(json.dumps(status, indent=2))
        return 0
    finally:
        db.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="search_index_cli",
        description="Folio Search Index Lifecycle & Operations Management CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. import-corpus
    p_import = subparsers.add_parser("import-corpus", help="Import legacy JSON/JSONL corpus idempotently")
    p_import.add_argument("--input", "-i", required=True, help="Path to input .json or .jsonl file")
    p_import.add_argument("--dry-run", action="store_true", help="Perform dry-run analysis without DB writes")
    p_import.add_argument(
        "--backfill-images",
        action="store_true",
        help="Match existing documents by source_url and backfill missing cover_image_url and cover_image_alt only",
    )
    p_import.add_argument("--batch-size", type=int, default=100, help="Batch commit size (default: 100)")
    p_import.set_defaults(func=cmd_import_corpus)

    # 2. build-index
    p_build = subparsers.add_parser("build-index", help="Build and atomically promote a new index generation")
    p_build.add_argument("--force", action="store_true", help="Force build even if another build is marked in-progress")
    p_build.add_argument("--verify", action="store_true", help="Automatically run verification after build")
    p_build.set_defaults(func=cmd_build_index)

    # 3. verify-index
    p_verify = subparsers.add_parser("verify-index", help="Verify integrity of specified or active index generation")
    p_verify.add_argument("--generation", "-g", default=None, help="Generation ID to verify (defaults to active)")
    p_verify.set_defaults(func=cmd_verify_index)

    # 4. index-status
    p_status = subparsers.add_parser("index-status", help="Display current generation, outbox queue, and lag status")
    p_status.set_defaults(func=cmd_index_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
