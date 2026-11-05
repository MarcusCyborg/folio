"""
Folio Search Engine Interface.

Implements candidate retrieval, filtering, Okapi BM25 scoring, and deterministic tie-breaking.
Interface for P05:
- Accepts query string, taxonomy/date filters, generation_id, and scoring parameters
- Applies filters before or during candidate scoring
- Avoids scanning the entire document collection by traversing only posting lists of query terms
- Applies strict deterministic tie-breaking: score DESC, doc_id ASC
- Returns candidate IDs, scores, ranks, and corpus statistics; NEVER returns full document bodies
"""

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any
from sqlalchemy.orm import Session

from src.backend.search.analyzer import TextAnalyzer, default_analyzer
from src.backend.search.index import InvertedIndex, GenerationMismatchError
from src.backend.search.bm25 import BM25Scorer
from src.backend.search_index.storage import GenerationStorage, get_index_storage_root


@dataclass
class SearchQuery:
    """Retrieval parameters passed by the Search API layer (P05)."""
    query: str
    category_id: Optional[str] = None
    tag_ids: Optional[List[str]] = None
    date_from: Optional[datetime] = None  # Inclusive start in UTC
    date_to: Optional[datetime] = None    # Inclusive end in UTC
    generation_id: Optional[str] = None
    top_k: int = 100
    k1: float = 1.5
    b: float = 0.75
    enable_title_boost: bool = False
    title_weight: float = 0.0
    status_filter: str = "published"


@dataclass(frozen=True)
class CandidateHit:
    """Scored candidate item returned to P05 for live DB hydration."""
    doc_id: str
    score: float
    rank: int
    raw_bm25: float
    title_boost: float = 1.0


@dataclass
class SearchResponse:
    """Structured IR result returned to the Search API integration layer."""
    candidates: List[CandidateHit]
    total_matches: int
    query_terms: List[str]
    generation_id: str
    corpus_stats: Dict[str, Any]
    execution_time_ms: float


class SearchEngine:
    """
    Search retrieval engine supporting multi-generation index caching,
    automatic disk-version invalidation across processes,
    postings-based candidate aggregation, exact taxonomy/date filtering,
    and deterministic Okapi BM25 scoring.
    """

    def __init__(
        self,
        analyzer: Optional[TextAnalyzer] = None,
    ):
        self.analyzer = analyzer or default_analyzer
        # Cache of loaded InvertedIndex by generation_id
        self._index_cache: Dict[str, InvertedIndex] = {}
        # Disk signature (index_version, checksum, mtime, size) per generation_id
        self._index_signatures: Dict[str, Optional[Tuple[Any, ...]]] = {}
        # Remembered storage directory per generation_id
        self._index_dirs: Dict[str, Path] = {}

    def get_or_load_index(
        self,
        generation_id: str,
        storage_dir: Optional[Path] = None,
    ) -> InvertedIndex:
        """
        Loads and caches the inverted index for generation_id.
        Automatically detects on-disk updates (via atomic index_stats.json version/checksum signature)
        and reloads the index when modified by an external worker process or save operation.
        """
        if storage_dir is not None:
            effective_dir = Path(storage_dir)
            self._index_dirs[generation_id] = effective_dir
        elif generation_id in self._index_dirs:
            effective_dir = self._index_dirs[generation_id]
        else:
            storage = GenerationStorage(generation_id)
            effective_dir = storage.postings_dir

        disk_sig = InvertedIndex.read_disk_signature(effective_dir)

        if generation_id in self._index_cache:
            cached_sig = self._index_signatures.get(generation_id)
            if disk_sig is None:
                if cached_sig is None:
                    # Purely in-memory registered index without disk backing
                    return self._index_cache[generation_id]
                # Previously disk-backed index whose files were removed/corrupted
                self._index_cache.pop(generation_id, None)
                self._index_signatures.pop(generation_id, None)
            elif cached_sig == disk_sig:
                return self._index_cache[generation_id]

        index = InvertedIndex.load(effective_dir, expected_generation_id=generation_id)
        new_sig = InvertedIndex.read_disk_signature(effective_dir)
        self._index_cache[generation_id] = index
        self._index_signatures[generation_id] = new_sig
        self._index_dirs[generation_id] = effective_dir
        return index

    def register_index(self, index: InvertedIndex, storage_dir: Optional[Path] = None):
        """Registers an in-memory InvertedIndex into the engine cache."""
        self._index_cache[index.generation_id] = index
        if storage_dir is not None:
            effective_dir = Path(storage_dir)
            self._index_dirs[index.generation_id] = effective_dir
            self._index_signatures[index.generation_id] = InvertedIndex.read_disk_signature(effective_dir)
        else:
            self._index_signatures[index.generation_id] = None

    def clear_cache(self, generation_id: Optional[str] = None):
        """Clears memory cache for a single generation or all generations."""
        if generation_id:
            self._index_cache.pop(generation_id, None)
            self._index_signatures.pop(generation_id, None)
            self._index_dirs.pop(generation_id, None)
        else:
            self._index_cache.clear()
            self._index_signatures.clear()
            self._index_dirs.clear()

    def _matches_filters(
        self,
        doc_id: str,
        index: InvertedIndex,
        query: SearchQuery,
    ) -> bool:
        """
        Validates whether a candidate document satisfies all taxonomy, status,
        and date filters.
        """
        meta = index.documents.get(doc_id)
        if not meta:
            return False

        # Status filter (published by default)
        if query.status_filter and meta.status != query.status_filter:
            return False

        # Category filter
        if query.category_id is not None:
            if meta.category_id != query.category_id:
                return False

        # Tag filter: strict AND semantics (candidate must possess all query tags)
        if query.tag_ids:
            doc_tag_set = set(meta.tag_ids)
            if not set(query.tag_ids).issubset(doc_tag_set):
                return False

        # Date range filters on created_at (UTC)
        if query.date_from is not None or query.date_to is not None:
            if not meta.created_at:
                return False
            try:
                # Normalize doc_dt to timezone-aware UTC
                doc_dt = datetime.fromisoformat(meta.created_at)
                if doc_dt.tzinfo is None:
                    doc_dt = doc_dt.replace(tzinfo=timezone.utc)
            except ValueError:
                return False

            if query.date_from is not None:
                q_from = query.date_from
                if q_from.tzinfo is None:
                    q_from = q_from.replace(tzinfo=timezone.utc)
                if doc_dt < q_from:
                    return False

            if query.date_to is not None:
                q_to = query.date_to
                if q_to.tzinfo is None:
                    q_to = q_to.replace(tzinfo=timezone.utc)
                if doc_dt > q_to:
                    return False

        return True

    def search(
        self,
        query: SearchQuery,
        index: Optional[InvertedIndex] = None,
    ) -> SearchResponse:
        """
        Executes query retrieval against the specified inverted index.
        - Tokenizes query using versioned analyzer
        - Gathers candidate documents solely from query term posting lists (no full-table scan)
        - Applies metadata and taxonomy filters
        - Scores candidates with Okapi BM25 and optional Title Boost
        - Sorts by score DESC, doc_id ASC (deterministic tie-breaking)
        - Returns structured candidate IDs, scores, ranks, and corpus statistics
        """
        start_time = time.perf_counter()

        # Validate date range
        if query.date_from and query.date_to and query.date_from > query.date_to:
            raise ValueError("date_from must not be greater than date_to")

        # Resolve index
        if index is None:
            if not query.generation_id:
                raise ValueError("Must provide either index or query.generation_id")
            index = self.get_or_load_index(query.generation_id)

        gen_id = index.generation_id
        corpus_stats = {
            "total_docs": index.total_docs,
            "total_tokens": index.total_tokens,
            "avg_doc_len": index.avg_doc_len,
            "vocabulary_size": len(index.df),
            "analyzer_version": index.analyzer_version,
            "generation_id": gen_id,
        }

        # Tokenize query
        query_terms = self.analyzer.tokenize(query.query)
        if not query_terms or index.total_docs == 0:
            elapsed = (time.perf_counter() - start_time) * 1000.0
            return SearchResponse(
                candidates=[],
                total_matches=0,
                query_terms=query_terms,
                generation_id=gen_id,
                corpus_stats=corpus_stats,
                execution_time_ms=round(elapsed, 3),
            )

        # Candidate selection: ONLY traverse postings for terms present in query
        candidate_term_freqs: Dict[str, Dict[str, int]] = {}
        for term in query_terms:
            plist = index.postings.get(term)
            if not plist:
                continue
            for doc_id, tf in plist:
                if doc_id not in candidate_term_freqs:
                    candidate_term_freqs[doc_id] = {}
                candidate_term_freqs[doc_id][term] = tf

        if not candidate_term_freqs:
            elapsed = (time.perf_counter() - start_time) * 1000.0
            return SearchResponse(
                candidates=[],
                total_matches=0,
                query_terms=query_terms,
                generation_id=gen_id,
                corpus_stats=corpus_stats,
                execution_time_ms=round(elapsed, 3),
            )

        # Scorer setup
        scorer = BM25Scorer(k1=query.k1, b=query.b, analyzer=self.analyzer)
        title_weight = query.title_weight if query.enable_title_boost else 0.0

        scored_candidates: List[CandidateHit] = []

        # Filter and score candidates
        for doc_id, tfs in candidate_term_freqs.items():
            if not self._matches_filters(doc_id, index, query):
                continue

            doc_score = scorer.score_candidate(
                doc_id=doc_id,
                term_freqs=tfs,
                index=index,
                query_terms=query_terms,
                title_weight=title_weight,
            )

            if doc_score.final_score > 0.0:
                scored_candidates.append(
                    CandidateHit(
                        doc_id=doc_id,
                        score=round(doc_score.final_score, 6),
                        rank=0,  # Assigned after sorting
                        raw_bm25=round(doc_score.raw_bm25, 6),
                        title_boost=round(doc_score.title_boost, 4),
                    )
                )

        # Deterministic Tie-Breaking: Primary sort = score DESC, Secondary sort = doc_id ASC
        scored_candidates.sort(key=lambda hit: (-hit.score, hit.doc_id))

        total_matches = len(scored_candidates)

        # Assign 1-based ranks to top_k slice
        ranked_top_k: List[CandidateHit] = []
        for rank_idx, hit in enumerate(scored_candidates[:query.top_k], start=1):
            ranked_top_k.append(
                CandidateHit(
                    doc_id=hit.doc_id,
                    score=hit.score,
                    rank=rank_idx,
                    raw_bm25=hit.raw_bm25,
                    title_boost=hit.title_boost,
                )
            )

        elapsed = (time.perf_counter() - start_time) * 1000.0
        return SearchResponse(
            candidates=ranked_top_k,
            total_matches=total_matches,
            query_terms=query_terms,
            generation_id=gen_id,
            corpus_stats=corpus_stats,
            execution_time_ms=round(elapsed, 3),
        )
