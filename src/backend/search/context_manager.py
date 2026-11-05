import hashlib
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any
from sqlalchemy.orm import Session

from src.backend.core.config import settings
from src.backend.core.exceptions import AppException
from src.backend.models.search_index import SearchContext


def compute_filters_hash(
    category_id: Optional[str] = None,
    tag_ids: Optional[List[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> str:
    """Computes a deterministic SHA-256 hash representing the query filters."""
    cat_str = (category_id or "").strip().lower()
    clean_tags = sorted([t.strip().lower() for t in (tag_ids or []) if t.strip()])
    tags_str = ",".join(clean_tags)
    df_str = (str(date_from) if date_from is not None else "").strip()
    dt_str = (str(date_to) if date_to is not None else "").strip()

    raw = f"cat:{cat_str}|tags:{tags_str}|from:{df_str}|to:{dt_str}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SearchContextManager:
    """
    Manages creation, resolution, TTL lifecycle, and strict parameter binding
    for Server-Issued Actor-Bound Search Contexts (Contract v2.1.0).
    """

    @staticmethod
    def create_context(
        db: Session,
        actor_key: str,
        query: str,
        mode: str,
        filters_hash: str,
        page_size: int,
        index_generation_id: str,
        candidate_ids: List[str],
        candidate_scores: Optional[List[float]] = None,
        snapshot_total: Optional[int] = None,
        snapshot_candidate_count: Optional[int] = None,
        is_approximate_total: bool = False,
        engine_used: Optional[str] = None,
        is_degraded: bool = False,
        degraded_reason: Optional[str] = None,
        ttl_minutes: Optional[int] = None,
    ) -> SearchContext:
        """Creates and stores a fresh SearchContext with absolute TTL and fallback metadata."""
        ttl = ttl_minutes if ttl_minutes is not None else settings.SEARCH_CONTEXT_TTL_MINUTES
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=ttl)
        token = str(uuid.uuid4())
        cand_count = snapshot_candidate_count if snapshot_candidate_count is not None else len(candidate_ids)
        clean_mode = mode.strip().lower()
        actual_engine = (engine_used or clean_mode).strip().lower()

        context = SearchContext(
            token=token,
            actor_key=actor_key,
            query=query.strip(),
            mode=clean_mode,
            engine_used=actual_engine,
            is_degraded=bool(is_degraded),
            degraded_reason=degraded_reason,
            filters_hash=filters_hash,
            page_size=page_size,
            index_generation_id=index_generation_id,
            candidate_ids=candidate_ids,
            candidate_scores=candidate_scores,
            snapshot_total=snapshot_total,
            snapshot_candidate_count=cand_count,
            is_approximate_total=is_approximate_total,
            created_at=now,
            expires_at=expires_at,
        )
        db.add(context)
        db.commit()
        db.refresh(context)
        return context

    @staticmethod
    def get_and_validate_context(
        db: Session,
        token: str,
        actor_key: str,
        expected_query: Optional[str] = None,
        expected_mode: Optional[str] = None,
        expected_filters_hash: Optional[str] = None,
        expected_page_size: Optional[int] = None,
    ) -> SearchContext:
        """
        Retrieves and strictly validates a SearchContext.
        Validates:
        - Context exists -> 404/400
        - Actor binding -> 403 CONTEXT_ACTOR_MISMATCH
        - TTL expiration -> 410 SEARCH_CONTEXT_EXPIRED with reissue_search=true
        - Parameter binding -> 400 CONTEXT_PARAMETER_MISMATCH
        """
        context = db.query(SearchContext).filter(SearchContext.token == token).first()
        if not context:
            raise AppException(
                status_code=404,
                code="SEARCH_CONTEXT_NOT_FOUND",
                message="The specified search context token does not exist.",
            )

        # 1. Actor binding verification
        if context.actor_key != actor_key:
            raise AppException(
                status_code=403,
                code="CONTEXT_ACTOR_MISMATCH",
                message="Search context token does not belong to the current session actor.",
            )

        # 2. TTL expiration check (absolute 15 minutes)
        now = datetime.now(timezone.utc)
        exp = context.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)

        if now > exp:
            raise AppException(
                status_code=410,
                code="SEARCH_CONTEXT_EXPIRED",
                message="The search pagination context has expired (TTL 15m). Please reissue the search query.",
                fields={"reissue_search": ["true"], "search_context_token": [token]},
            )

        # 3. Parameter binding checks
        if expected_query is not None and expected_query.strip() != context.query:
            raise AppException(
                status_code=400,
                code="CONTEXT_PARAMETER_MISMATCH",
                message="Query parameter does not match the search context snapshot.",
            )

        if expected_mode is not None and expected_mode.strip().lower() != context.mode:
            raise AppException(
                status_code=400,
                code="CONTEXT_PARAMETER_MISMATCH",
                message="Mode parameter does not match the search context snapshot.",
            )

        if expected_filters_hash is not None and expected_filters_hash != context.filters_hash:
            raise AppException(
                status_code=400,
                code="CONTEXT_PARAMETER_MISMATCH",
                message="Filters parameter does not match the search context snapshot.",
            )

        if expected_page_size is not None and expected_page_size != context.page_size:
            raise AppException(
                status_code=400,
                code="CONTEXT_PARAMETER_MISMATCH",
                message="Page size parameter does not match the search context snapshot.",
            )

        return context
