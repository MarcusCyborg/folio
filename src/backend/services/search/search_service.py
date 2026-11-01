import time
import uuid
import re
from datetime import datetime, timezone, date, timedelta
from typing import Dict, List, Optional, Tuple, Any
from sqlalchemy.orm import Session
from sqlalchemy import text

from src.backend.core.config import settings
from src.backend.core.exceptions import AppException
from src.backend.models.document import Document
from src.backend.models.taxonomy import Category, Tag
from src.backend.models.event import InteractionLog
from src.backend.models.search_index import IndexGeneration
from src.backend.search.analyzer import default_analyzer
from src.backend.search.engine import SearchEngine, SearchQuery, CandidateHit
from src.backend.search.semantic import SemanticAdapter, SemanticCandidateHit
from src.backend.search.hybrid import fuse_candidates_rrf
from src.backend.search.snippets import generate_snippet
from src.backend.search.context_manager import SearchContextManager, compute_filters_hash
from src.backend.search_index.manager import GenerationManager
from src.backend.search_index.live_guard import filter_live_published_ids
from src.backend.schemas.search import (
    SearchItem,
    SearchTaxon,
    SearchResponse as SearchResponseSchema,
)

# Global singleton search engine and semantic adapter
search_engine = SearchEngine()
semantic_adapter = SemanticAdapter()


def is_valid_uuid(val: str) -> bool:
    try:
        uuid.UUID(str(val).strip())
        return True
    except (ValueError, AttributeError):
        return False


class SearchService:
    """
    Search Service orchestrating:
    - Input validation (query length, mode, UUID format, date ranges)
    - Search Context pagination stability and absolute TTL (15m)
    - Retrieval via BM25, Semantic, or Hybrid
    - Graceful fallback with transparent engine declaration (no fake success)
    - Live publication / deleted check (0-second lag defense) with fixed rank-window pruning (no backfill)
    - HTML-safe snippet generation with <em> highlighting
    - Search event logging storing exact returned Document IDs
    """

    def __init__(
        self,
        engine: Optional[SearchEngine] = None,
        adapter: Optional[SemanticAdapter] = None,
    ):
        self.engine = engine or search_engine
        self.adapter = adapter or semantic_adapter

    def _execute_ilike_fallback(
        self,
        db: Session,
        query_str: str,
        category_id: Optional[str] = None,
        tag_ids: Optional[List[str]] = None,
        date_from_utc: Optional[datetime] = None,
        date_to_utc: Optional[datetime] = None,
        top_k: int = 100,
    ) -> List[CandidateHit]:
        """Fallback to database ILIKE when inverted index generation is missing or corrupt."""
        q = db.query(Document).filter(
            Document.status == "published",
            Document.deleted_at.is_(None),
        )

        # Keyword matching on title, summary, or content
        pattern = f"%{query_str}%"
        q = q.filter(
            (Document.title.ilike(pattern))
            | (Document.summary.ilike(pattern))
            | (Document.content.ilike(pattern))
        )

        if category_id:
            q = q.filter(Document.category_id == category_id)

        if tag_ids:
            for t_id in tag_ids:
                q = q.filter(Document.document_tags.any(tag_id=t_id))

        if date_from_utc:
            q = q.filter(Document.created_at >= date_from_utc)

        if date_to_utc:
            q = q.filter(Document.created_at <= date_to_utc)

        # Stable ordering: newest first, tie-break doc_id ASC
        q = q.order_by(Document.created_at.desc(), Document.id.asc()).limit(top_k)
        docs = q.all()

        hits = []
        for idx, doc in enumerate(docs, start=1):
            hits.append(
                CandidateHit(
                    doc_id=doc.id,
                    score=round(1.0 / idx, 6),
                    rank=idx,
                    raw_bm25=1.0,
                    title_boost=1.0,
                )
            )
        return hits

    def search(
        self,
        db: Session,
        query: Optional[str] = None,
        search_context_token: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        mode: str = "bm25",
        category_id: Optional[str] = None,
        tag_ids_raw: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        actor_key: str = "public-actor",
        user_id: Optional[str] = None,
    ) -> SearchResponseSchema:
        start_time = time.perf_counter()

        # 1. Parameter Validation
        mode_cleaned = (mode or "bm25").strip().lower()
        if mode_cleaned not in ("bm25", "semantic", "hybrid"):
            raise AppException(
                status_code=422,
                code="INVALID_MODE",
                message=f"Unsupported search mode '{mode}'. Must be one of: 'bm25', 'semantic', 'hybrid'.",
            )

        if page < 1:
            raise AppException(
                status_code=422,
                code="INVALID_PAGE",
                message="Page must be greater than or equal to 1.",
            )

        if page_size < 1 or page_size > 100:
            raise AppException(
                status_code=422,
                code="INVALID_PAGE_SIZE",
                message="Page size must be between 1 and 100.",
            )

        # Validate pagination context token on subsequent pages
        if page >= 2 and not search_context_token:
            raise AppException(
                status_code=400,
                code="MISSING_SEARCH_CONTEXT_TOKEN",
                message="Parameter 'search_context_token' is required for pagination on page >= 2.",
            )

        clean_query = (query or "").strip()
        if not search_context_token:
            if not clean_query:
                raise AppException(
                    status_code=422,
                    code="EMPTY_QUERY",
                    message="Query parameter 'q' must not be empty or whitespace only.",
                )
            if len(clean_query) > 200:
                raise AppException(
                    status_code=422,
                    code="QUERY_TOO_LONG",
                    message="Query string must not exceed 200 characters.",
                )

        # Validate category_id format
        clean_category_id: Optional[str] = None
        if category_id and category_id.strip():
            clean_cat = category_id.strip()
            if not is_valid_uuid(clean_cat):
                raise AppException(
                    status_code=422,
                    code="INVALID_CATEGORY_ID",
                    message="category_id must be a valid UUID string.",
                )
            # Check existence in DB
            cat_exists = db.query(Category.id).filter(Category.id == clean_cat).first()
            if not cat_exists:
                # Unknown category: return empty results early (200 OK)
                now_utc = datetime.now(timezone.utc)
                return SearchResponseSchema(
                    items=[],
                    page=page,
                    page_size=page_size,
                    search_context_token=str(uuid.uuid4()),
                    expires_at=(now_utc + timedelta(minutes=settings.SEARCH_CONTEXT_TTL_MINUTES)).isoformat(),
                    snapshot_total=0,
                    snapshot_candidate_count=0,
                    is_approximate_total=False,
                    has_more=False,
                    query=clean_query,
                    mode=mode_cleaned,
                    engine_requested=mode_cleaned,
                    engine_used=mode_cleaned,
                    is_degraded=False,
                    degraded_reason=None,
                    index_generation="none",
                    search_event_id=str(uuid.uuid4()),
                    latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                )
            clean_category_id = clean_cat

        # Validate tag_ids format
        clean_tag_ids: Optional[List[str]] = None
        if tag_ids_raw and tag_ids_raw.strip():
            raw_tags = [t.strip() for t in tag_ids_raw.split(",") if t.strip()]
            for t in raw_tags:
                if not is_valid_uuid(t):
                    raise AppException(
                        status_code=422,
                        code="INVALID_TAG_ID",
                        message=f"tag_ids contains invalid UUID string: '{t}'.",
                    )
            # Check all tags exist in DB (strict AND semantics)
            existing_tags = db.query(Tag.id).filter(Tag.id.in_(raw_tags)).all()
            if len(existing_tags) < len(raw_tags):
                # Unknown tag: return empty results early (200 OK)
                now_utc = datetime.now(timezone.utc)
                return SearchResponseSchema(
                    items=[],
                    page=page,
                    page_size=page_size,
                    search_context_token=str(uuid.uuid4()),
                    expires_at=(now_utc + timedelta(minutes=settings.SEARCH_CONTEXT_TTL_MINUTES)).isoformat(),
                    snapshot_total=0,
                    snapshot_candidate_count=0,
                    is_approximate_total=False,
                    has_more=False,
                    query=clean_query,
                    mode=mode_cleaned,
                    engine_requested=mode_cleaned,
                    engine_used=mode_cleaned,
                    is_degraded=False,
                    degraded_reason=None,
                    index_generation="none",
                    search_event_id=str(uuid.uuid4()),
                    latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
                )
            clean_tag_ids = sorted(raw_tags)

        # Date range validation
        date_from_utc: Optional[datetime] = None
        date_to_utc: Optional[datetime] = None
        if date_from is not None and date_to is not None and date_from > date_to:
            raise AppException(
                status_code=422,
                code="INVALID_DATE_RANGE",
                message="date_from must not be greater than date_to.",
            )

        if date_from is not None:
            date_from_utc = datetime(
                date_from.year, date_from.month, date_from.day, 0, 0, 0, tzinfo=timezone.utc
            )
        if date_to is not None:
            date_to_utc = datetime(
                date_to.year, date_to.month, date_to.day, 23, 59, 59, 999999, tzinfo=timezone.utc
            )

        filters_hash = compute_filters_hash(
            category_id=clean_category_id,
            tag_ids=clean_tag_ids,
            date_from=str(date_from) if date_from else None,
            date_to=str(date_to) if date_to else None,
        )

        # 2. Context Resolution or Execution
        context = None
        engine_requested = mode_cleaned
        engine_used = mode_cleaned
        is_degraded = False
        degraded_reason: Optional[str] = None
        index_generation_id = "unknown"
        candidate_ids: List[str] = []
        candidate_scores_map: Dict[str, float] = {}
        snapshot_total: Optional[int] = None
        snapshot_candidate_count: int = 0
        is_approximate_total: bool = False
        context_token: str = ""
        expires_at_iso: str = ""
        effective_query: str = clean_query

        if search_context_token:
            # Subsequent page: resolve context
            context = SearchContextManager.get_and_validate_context(
                db=db,
                token=search_context_token,
                actor_key=actor_key,
                expected_query=clean_query if clean_query else None,
                expected_mode=mode_cleaned if mode else None,
                expected_filters_hash=filters_hash if (clean_category_id or clean_tag_ids or date_from or date_to) else None,
                expected_page_size=page_size,
            )
            context_token = context.token
            effective_query = context.query
            engine_requested = context.mode
            engine_used = context.mode
            index_generation_id = context.index_generation_id
            candidate_ids = context.candidate_ids or []
            scores = context.candidate_scores or []
            for cid, sc in zip(candidate_ids, scores):
                candidate_scores_map[cid] = sc
            snapshot_total = context.snapshot_total
            snapshot_candidate_count = context.snapshot_candidate_count
            is_approximate_total = context.is_approximate_total
            exp_dt = context.expires_at
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            expires_at_iso = exp_dt.isoformat()
        else:
            # Initial search (page 1): execute IR retrieval
            active_gen = GenerationManager.get_active_generation(db)
            index_generation_id = active_gen.id if active_gen else "fallback-none"

            # Execute based on requested mode
            if mode_cleaned == "bm25":
                if not active_gen:
                    # Inverted index missing -> Fallback to PostgreSQL ILIKE
                    hits = self._execute_ilike_fallback(
                        db=db,
                        query_str=clean_query,
                        category_id=clean_category_id,
                        tag_ids=clean_tag_ids,
                        date_from_utc=date_from_utc,
                        date_to_utc=date_to_utc,
                        top_k=100,
                    )
                    engine_used = "ilike_fallback"
                    is_degraded = True
                    degraded_reason = "Lexical index generation unavailable; serving ILIKE"
                    candidate_ids = [h.doc_id for h in hits]
                    for h in hits:
                        candidate_scores_map[h.doc_id] = h.score
                    snapshot_total = len(candidate_ids)
                    snapshot_candidate_count = len(candidate_ids)
                    is_approximate_total = False
                else:
                    try:
                        sq = SearchQuery(
                            query=clean_query,
                            category_id=clean_category_id,
                            tag_ids=clean_tag_ids,
                            date_from=date_from_utc,
                            date_to=date_to_utc,
                            generation_id=active_gen.id,
                            top_k=100,
                        )
                        sres = self.engine.search(sq)
                        candidate_ids = [h.doc_id for h in sres.candidates]
                        for h in sres.candidates:
                            candidate_scores_map[h.doc_id] = h.score
                        snapshot_total = sres.total_matches
                        snapshot_candidate_count = len(candidate_ids)
                        is_approximate_total = False
                    except Exception as e:
                        # Corrupted or unreadable index generation -> Fallback to ILIKE
                        hits = self._execute_ilike_fallback(
                            db=db,
                            query_str=clean_query,
                            category_id=clean_category_id,
                            tag_ids=clean_tag_ids,
                            date_from_utc=date_from_utc,
                            date_to_utc=date_to_utc,
                            top_k=100,
                        )
                        engine_used = "ilike_fallback"
                        is_degraded = True
                        degraded_reason = "Lexical index generation unavailable; serving ILIKE"
                        candidate_ids = [h.doc_id for h in hits]
                        for h in hits:
                            candidate_scores_map[h.doc_id] = h.score
                        snapshot_total = len(candidate_ids)
                        snapshot_candidate_count = len(candidate_ids)
                        is_approximate_total = False

            elif mode_cleaned == "semantic":
                sem_hits, sem_error = self.adapter.query(clean_query, top_k=100, db=db)
                if sem_error is not None:
                    # Semantic failure: ChromaDB offline or SentenceTransformer unavailable
                    # Fallback to BM25! Declare fallback_bm25, NO fake success!
                    engine_used = "fallback_bm25"
                    is_degraded = True
                    degraded_reason = sem_error

                    if active_gen:
                        try:
                            sq = SearchQuery(
                                query=clean_query,
                                category_id=clean_category_id,
                                tag_ids=clean_tag_ids,
                                date_from=date_from_utc,
                                date_to=date_to_utc,
                                generation_id=active_gen.id,
                                top_k=100,
                            )
                            sres = self.engine.search(sq)
                            candidate_ids = [h.doc_id for h in sres.candidates]
                            for h in sres.candidates:
                                candidate_scores_map[h.doc_id] = h.score
                            snapshot_total = sres.total_matches
                            snapshot_candidate_count = len(candidate_ids)
                            is_approximate_total = False
                        except Exception:
                            hits = self._execute_ilike_fallback(db, clean_query, clean_category_id, clean_tag_ids, date_from_utc, date_to_utc)
                            candidate_ids = [h.doc_id for h in hits]
                            for h in hits:
                                candidate_scores_map[h.doc_id] = h.score
                            snapshot_total = len(candidate_ids)
                            snapshot_candidate_count = len(candidate_ids)
                    else:
                        hits = self._execute_ilike_fallback(db, clean_query, clean_category_id, clean_tag_ids, date_from_utc, date_to_utc)
                        candidate_ids = [h.doc_id for h in hits]
                        for h in hits:
                            candidate_scores_map[h.doc_id] = h.score
                        snapshot_total = len(candidate_ids)
                        snapshot_candidate_count = len(candidate_ids)
                else:
                    # Semantic succeeded
                    candidate_ids = [h.doc_id for h in sem_hits]
                    for h in sem_hits:
                        candidate_scores_map[h.doc_id] = h.score
                    snapshot_total = None
                    snapshot_candidate_count = len(candidate_ids)
                    is_approximate_total = True

            elif mode_cleaned == "hybrid":
                # Execute BM25 candidates
                bm25_hits: List[CandidateHit] = []
                if active_gen:
                    try:
                        sq = SearchQuery(
                            query=clean_query,
                            category_id=clean_category_id,
                            tag_ids=clean_tag_ids,
                            date_from=date_from_utc,
                            date_to=date_to_utc,
                            generation_id=active_gen.id,
                            top_k=100,
                        )
                        sres = self.engine.search(sq)
                        bm25_hits = sres.candidates
                    except Exception:
                        bm25_hits = self._execute_ilike_fallback(db, clean_query, clean_category_id, clean_tag_ids, date_from_utc, date_to_utc)
                else:
                    bm25_hits = self._execute_ilike_fallback(db, clean_query, clean_category_id, clean_tag_ids, date_from_utc, date_to_utc)

                # Execute Semantic candidates
                sem_hits, sem_error = self.adapter.query(clean_query, top_k=100, db=db)
                if sem_error is not None:
                    # Vector component unavailable -> Fallback to pure Okapi BM25
                    engine_used = "fallback_bm25"
                    is_degraded = True
                    degraded_reason = "Vector component unavailable; serving BM25"
                    candidate_ids = [h.doc_id for h in bm25_hits]
                    for h in bm25_hits:
                        candidate_scores_map[h.doc_id] = h.score
                    snapshot_total = len(candidate_ids)
                    snapshot_candidate_count = len(candidate_ids)
                    is_approximate_total = False
                else:
                    # Fuse using RRF
                    fused_hits = fuse_candidates_rrf(bm25_hits, sem_hits, top_k=100)
                    candidate_ids = [h.doc_id for h in fused_hits]
                    for h in fused_hits:
                        candidate_scores_map[h.doc_id] = h.score
                    snapshot_total = None
                    snapshot_candidate_count = len(candidate_ids)
                    is_approximate_total = True

            # If no active generation existed in DB, create placeholder generation for context FK if needed
            db_gen = db.query(IndexGeneration).filter(IndexGeneration.id == index_generation_id).first()
            if not db_gen:
                index_generation_id = "idx-gen-fallback"
                fallback_gen = db.query(IndexGeneration).filter(IndexGeneration.id == index_generation_id).first()
                if not fallback_gen:
                    fallback_gen = IndexGeneration(
                        id=index_generation_id,
                        generation_num=0,
                        status="active",
                        doc_count=len(candidate_ids),
                    )
                    db.add(fallback_gen)
                    db.commit()

            # Create SearchContext snapshot
            context_record = SearchContextManager.create_context(
                db=db,
                actor_key=actor_key,
                query=clean_query,
                mode=mode_cleaned,
                filters_hash=filters_hash,
                page_size=page_size,
                index_generation_id=index_generation_id,
                candidate_ids=candidate_ids,
                candidate_scores=[candidate_scores_map.get(cid, 0.0) for cid in candidate_ids],
                snapshot_total=snapshot_total,
                snapshot_candidate_count=snapshot_candidate_count,
                is_approximate_total=is_approximate_total,
            )
            context_token = context_record.token
            exp_dt = context_record.expires_at
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            expires_at_iso = exp_dt.isoformat()

        # 3. Candidate Window & Fixed-Rank Prune Without Backfill
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size

        if start_idx >= len(candidate_ids):
            # Page beyond candidate window
            page_slice_candidates: List[str] = []
        else:
            page_slice_candidates = candidate_ids[start_idx:end_idx]

        # Defense-in-depth: Live PostgreSQL publication and soft-delete verification (0s lag)
        live_published_ids = filter_live_published_ids(db, page_slice_candidates)

        # Evaluate has_more: strictly based on candidate window remaining beyond this page rank
        has_more = (page * page_size) < snapshot_candidate_count

        # 4. Hydrate Document Metadata from PostgreSQL
        items: List[SearchItem] = []
        query_terms = default_analyzer.tokenize(effective_query)

        if live_published_ids:
            from src.backend.models.document import DocumentLike
            from sqlalchemy import func
            likes_map = dict(
                db.query(DocumentLike.document_id, func.count(DocumentLike.id))
                .filter(DocumentLike.document_id.in_(live_published_ids))
                .group_by(DocumentLike.document_id)
                .all()
            )

            doc_rows = (
                db.query(Document)
                .filter(Document.id.in_(live_published_ids))
                .all()
            )
            docs_by_id = {doc.id: doc for doc in doc_rows}

            for rank_offset, doc_id in enumerate(live_published_ids, start=1):
                doc = docs_by_id.get(doc_id)
                if not doc:
                    continue

                abs_rank = start_idx + rank_offset
                item_score = candidate_scores_map.get(doc.id, 0.0)

                cat_obj = None
                if doc.category:
                    cat_obj = SearchTaxon(
                        id=doc.category.id,
                        name=doc.category.name,
                        slug=doc.category.slug,
                    )

                tag_objs = []
                if doc.document_tags:
                    for dt in doc.document_tags:
                        if dt.tag:
                            tag_objs.append(
                                SearchTaxon(
                                    id=dt.tag.id,
                                    name=dt.tag.name,
                                    slug=dt.tag.slug,
                                )
                            )

                snippet = generate_snippet(
                    text=doc.content,
                    query_terms=query_terms,
                    summary=doc.summary,
                    max_length=180,
                )

                created_str = (
                    doc.created_at.replace(tzinfo=timezone.utc).isoformat()
                    if doc.created_at.tzinfo is None
                    else doc.created_at.isoformat()
                )
                published_str = None
                if doc.published_at:
                    published_str = (
                        doc.published_at.replace(tzinfo=timezone.utc).isoformat()
                        if doc.published_at.tzinfo is None
                        else doc.published_at.isoformat()
                    )

                items.append(
                    SearchItem(
                        id=doc.id,
                        title=doc.title,
                        summary=doc.summary or "",
                        snippet=snippet,
                        score=item_score,
                        rank=abs_rank,
                        author=doc.author or "Folio Contributor",
                        category=cat_obj,
                        tags=tag_objs,
                        created_at=created_str,
                        published_at=published_str,
                        views_count=doc.views_count or 0,
                        likes_count=likes_map.get(doc.id, 0),
                        cover_image_url=doc.cover_image_url,
                        cover_image_alt=doc.cover_image_alt,
                        source_url=doc.source_url,
                    )
                )

        # 5. Search Event Logging
        returned_doc_ids = [item.id for item in items]
        search_event = InteractionLog(
            event_type="search",
            query_string=effective_query,
            actor_key=actor_key,
            user_id=user_id,
            result_doc_ids=returned_doc_ids,
            clicked_doc_id=None,
            search_event_id=None,
            timestamp=datetime.now(timezone.utc),
        )
        db.add(search_event)
        db.commit()
        db.refresh(search_event)
        search_event_id = search_event.id

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

        return SearchResponseSchema(
            items=items,
            page=page,
            page_size=page_size,
            search_context_token=context_token,
            expires_at=expires_at_iso,
            snapshot_total=snapshot_total,
            snapshot_candidate_count=snapshot_candidate_count,
            is_approximate_total=is_approximate_total,
            has_more=has_more,
            query=effective_query,
            mode=mode_cleaned,
            engine_requested=engine_requested,
            engine_used=engine_used,
            is_degraded=is_degraded,
            degraded_reason=degraded_reason,
            index_generation=index_generation_id,
            search_event_id=search_event_id,
            latency_ms=elapsed_ms,
        )
