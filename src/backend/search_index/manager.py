import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from src.backend.models.document import Document
from src.backend.models.taxonomy import Category
from src.backend.models.search_index import (
    IndexGeneration,
    IndexJob,
    SearchContext,
    DocumentRevision,
)
from src.backend.search_index.hashing import compute_doc_instance_hash
from src.backend.search_index.storage import GenerationStorage, get_index_storage_root


class IndexBuildError(Exception):
    pass


class IndexVerificationError(Exception):
    pass


class GenerationManager:
    """
    Manages the lifecycle of search index generations:
    creation, concurrent catch-up, integrity verification, atomic swapping, and lease-safe GC.
    """

    @staticmethod
    def get_active_generation(db: Session) -> Optional[IndexGeneration]:
        """Returns the currently active generation, or None if none is active."""
        return db.query(IndexGeneration).filter(IndexGeneration.status == "active").first()

    @staticmethod
    def get_generation_by_id(db: Session, gen_id: str) -> Optional[IndexGeneration]:
        return db.query(IndexGeneration).filter(IndexGeneration.id == gen_id).first()

    @classmethod
    def build_new_generation(
        cls,
        db: Session,
        force: bool = False,
        sim_fail_at: Optional[str] = None,
    ) -> IndexGeneration:
        """
        Builds a new index generation, snapshots all published documents,
        catches up concurrent mutations that occurred during the build,
        verifies integrity against PostgreSQL, and atomically promotes it to active.

        If build or verification fails, the new generation is marked 'failed'
        and the previously active generation remains completely untouched.
        """
        now = datetime.now(timezone.utc)

        # Check for in-progress builds
        existing_building = db.query(IndexGeneration).filter(IndexGeneration.status == "building").first()
        if existing_building and not force:
            raise IndexBuildError(f"Another generation build is currently in progress: {existing_building.id}")

        # Compute next generation number
        max_num = db.query(func.coalesce(func.max(IndexGeneration.generation_num), 0)).scalar() or 0
        next_num = max_num + 1
        timestamp_str = now.strftime("%Y%m%d%H%M%S")
        gen_id = f"idx-gen-{timestamp_str}-{next_num:04d}"

        gen_record = IndexGeneration(
            id=gen_id,
            generation_num=next_num,
            status="building",
            doc_count=0,
            created_at=now,
            updated_at=now,
        )
        db.add(gen_record)
        db.commit()

        storage = GenerationStorage(gen_id)
        storage.initialize(next_num)

        rebuild_started_at = datetime.now(timezone.utc)

        try:
            # 1. Snapshot all published, non-deleted documents in PostgreSQL
            docs = (
                db.query(Document)
                .filter(
                    Document.status == "published",
                    Document.deleted_at.is_(None),
                )
                .all()
            )

            for doc in docs:
                tag_slugs = [dt.tag.slug for dt in doc.document_tags if dt.tag] if doc.document_tags else []
                category_slug = doc.category.slug if doc.category else ""
                rev_hash = compute_doc_instance_hash(doc)
                storage.upsert_document(
                    doc.id,
                    {
                        "title": doc.title,
                        "summary": doc.summary,
                        "category_slug": category_slug,
                        "tags": tag_slugs,
                        "revision_hash": rev_hash,
                        "updated_at": (doc.updated_at or now).isoformat(),
                    },
                )

            if sim_fail_at == "build":
                raise IndexBuildError("Simulated index build failure")

            # 2. Catch up concurrent updates that occurred since rebuild_started_at
            concurrent_jobs = (
                db.query(IndexJob)
                .filter(IndexJob.created_at >= rebuild_started_at)
                .order_by(IndexJob.created_at.asc())
                .all()
            )

            for job in concurrent_jobs:
                current_doc = db.query(Document).filter(Document.id == job.document_id).first()
                if current_doc and current_doc.status == "published" and current_doc.deleted_at is None:
                    tag_slugs = [dt.tag.slug for dt in current_doc.document_tags if dt.tag] if current_doc.document_tags else []
                    category_slug = current_doc.category.slug if current_doc.category else ""
                    rev_hash = compute_doc_instance_hash(current_doc)
                    storage.upsert_document(
                        current_doc.id,
                        {
                            "title": current_doc.title,
                            "summary": current_doc.summary,
                            "category_slug": category_slug,
                            "tags": tag_slugs,
                            "revision_hash": rev_hash,
                            "updated_at": (current_doc.updated_at or now).isoformat(),
                        },
                    )
                else:
                    storage.delete_document(job.document_id)

            if sim_fail_at == "verify":
                raise IndexVerificationError("Simulated index verification failure")

            # 3. Verify generation integrity
            valid_storage, storage_errors = storage.verify_integrity()
            if not valid_storage:
                raise IndexVerificationError(f"Generation storage validation failed: {'; '.join(storage_errors)}")

            # Verify against database published count
            live_published_count = db.query(Document).filter(
                Document.status == "published",
                Document.deleted_at.is_(None),
            ).count()

            manifest = storage.load_manifest()
            if manifest["doc_count"] != live_published_count:
                raise IndexVerificationError(
                    f"Document count mismatch: index has {manifest['doc_count']}, live DB has {live_published_count}"
                )

            # 4. Atomic Swap: Promote to active in a single transaction
            swap_time = datetime.now(timezone.utc)
            previous_active = db.query(IndexGeneration).filter(IndexGeneration.status == "active").all()
            for old_gen in previous_active:
                old_gen.status = "draining"
                old_gen.updated_at = swap_time

            gen_record.status = "active"
            gen_record.active_at = swap_time
            gen_record.updated_at = swap_time
            gen_record.doc_count = manifest["doc_count"]
            gen_record.manifest = manifest

            # Mark processed concurrent jobs as completed
            for job in concurrent_jobs:
                if job.state == "pending":
                    job.state = "completed"
                    job.completed_at = swap_time

            db.commit()
            db.refresh(gen_record)
            return gen_record

        except Exception as exc:
            db.rollback()
            # In a clean separate transaction, mark generation as failed to preserve audit trail
            try:
                failed_gen = db.query(IndexGeneration).filter(IndexGeneration.id == gen_id).first()
                if failed_gen:
                    failed_gen.status = "failed"
                    failed_gen.updated_at = datetime.now(timezone.utc)
                    failed_gen.manifest = {"error": str(exc)}
                    db.commit()
            except Exception:
                db.rollback()
            raise exc

    @classmethod
    def verify_generation(
        cls,
        db: Session,
        generation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Verifies the specified (or active) generation against physical storage and live PostgreSQL.
        Returns a structured report.
        """
        if generation_id:
            gen_rec = db.query(IndexGeneration).filter(IndexGeneration.id == generation_id).first()
        else:
            gen_rec = cls.get_active_generation(db)

        if not gen_rec:
            return {
                "valid": False,
                "generation_id": generation_id or "active",
                "errors": ["Generation not found in database"],
            }

        errors = []
        checks = []

        # 1. Storage checks
        storage = GenerationStorage(gen_rec.id)
        valid_storage, storage_errs = storage.verify_integrity()
        if not valid_storage:
            errors.extend(storage_errs)
        else:
            checks.append("manifest_integrity_valid")

        manifest = storage.load_manifest() or {}
        indexed_doc_ids = set(manifest.get("docs", {}).keys())

        # 2. Live database comparison
        live_published_docs = db.query(Document).filter(
            Document.status == "published",
            Document.deleted_at.is_(None),
        ).all()
        live_published_ids = {d.id for d in live_published_docs}

        # Check for missing documents
        missing_in_index = live_published_ids - indexed_doc_ids
        if missing_in_index:
            errors.append(f"{len(missing_in_index)} published document(s) missing from index")

        # Check for extraneous / draft / deleted documents
        extra_in_index = indexed_doc_ids - live_published_ids
        if extra_in_index:
            errors.append(f"{len(extra_in_index)} document(s) in index are not published or are soft-deleted")

        # Check hash consistency
        docs_dict = manifest.get("docs", {})
        hash_mismatches = 0
        for doc in live_published_docs:
            if doc.id in docs_dict:
                expected_hash = compute_doc_instance_hash(doc)
                index_hash = docs_dict[doc.id].get("revision_hash")
                if expected_hash != index_hash:
                    hash_mismatches += 1

        if hash_mismatches > 0:
            errors.append(f"{hash_mismatches} document(s) have hash mismatches between index and database")
        else:
            checks.append("revision_hashes_consistent")

        return {
            "valid": len(errors) == 0,
            "generation_id": gen_rec.id,
            "status": gen_rec.status,
            "doc_count": gen_rec.doc_count,
            "indexed_count": len(indexed_doc_ids),
            "live_published_count": len(live_published_ids),
            "checks": checks,
            "errors": errors,
        }

    @classmethod
    def get_index_status(cls, db: Session) -> Dict[str, Any]:
        """Collects complete operational status of index generations and outbox queues."""
        active_gen = cls.get_active_generation(db)
        draining_gens = db.query(IndexGeneration).filter(IndexGeneration.status == "draining").all()
        failed_gens = db.query(IndexGeneration).filter(IndexGeneration.status == "failed").all()

        now = datetime.now(timezone.utc)
        draining_info = []
        for dg in draining_gens:
            active_leases = db.query(SearchContext).filter(
                SearchContext.index_generation_id == dg.id,
                SearchContext.expires_at > now,
            ).count()
            draining_info.append({
                "id": dg.id,
                "generation_num": dg.generation_num,
                "doc_count": dg.doc_count,
                "active_leases": active_leases,
                "created_at": dg.created_at.isoformat(),
            })

        # Outbox stats
        job_counts = {
            "pending": db.query(IndexJob).filter(IndexJob.state == "pending").count(),
            "processing": db.query(IndexJob).filter(IndexJob.state == "processing").count(),
            "completed": db.query(IndexJob).filter(IndexJob.state == "completed").count(),
            "failed": db.query(IndexJob).filter(IndexJob.state == "failed").count(),
        }

        oldest_pending = (
            db.query(IndexJob.created_at)
            .filter(IndexJob.state == "pending")
            .order_by(IndexJob.created_at.asc())
            .first()
        )
        lag_seconds = 0.0
        if oldest_pending and oldest_pending[0]:
            created = oldest_pending[0]
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            lag_seconds = max(0.0, (now - created).total_seconds())

        return {
            "active_generation": {
                "id": active_gen.id,
                "generation_num": active_gen.generation_num,
                "status": active_gen.status,
                "doc_count": active_gen.doc_count,
                "active_at": active_gen.active_at.isoformat() if active_gen and active_gen.active_at else None,
            } if active_gen else None,
            "draining_generations": draining_info,
            "failed_generations_count": len(failed_gens),
            "outbox_jobs": job_counts,
            "index_lag_seconds": round(lag_seconds, 2),
        }

    @classmethod
    def garbage_collect_generations(
        cls,
        db: Session,
        max_retention_hours: float = 1.0,
    ) -> List[str]:
        """
        Safely purges draining generations whose search context leases have all expired,
        or that exceed the maximum safety drain duration.
        """
        now = datetime.now(timezone.utc)
        draining = db.query(IndexGeneration).filter(IndexGeneration.status == "draining").all()
        purged = []

        for gen in draining:
            # Check for active context leases
            active_leases = db.query(SearchContext).filter(
                SearchContext.index_generation_id == gen.id,
                SearchContext.expires_at > now,
            ).count()

            gen_created = gen.created_at
            if gen_created.tzinfo is None:
                gen_created = gen_created.replace(tzinfo=timezone.utc)
            is_overdue = (now - gen_created) > timedelta(hours=max_retention_hours)

            if active_leases == 0 or is_overdue:
                # Safe to purge
                gen.status = "archived"
                gen.updated_at = now
                storage = GenerationStorage(gen.id)
                storage.purge()
                purged.append(gen.id)

        if purged:
            db.commit()
        return purged
