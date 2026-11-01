import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from sqlalchemy.orm import Session

from src.backend.core.config import settings


def generate_doc_uuid_from_url(url: str) -> str:
    """Generates canonical reproducible UUIDv5 from URL namespace."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, url.strip()))


@dataclass(frozen=True)
class SemanticCandidateHit:
    """Scored vector retrieval candidate hit."""
    doc_id: str
    score: float
    rank: int
    raw_distance: float
    chunk_count: int


class SemanticAdapter:
    """
    Adapter for ChromaDB vector store and SentenceTransformer embedding model.
    Guarantees:
    - Never fakes semantic success if ChromaDB or the model is unavailable.
    - Explicitly reports degradation reason for fallback to BM25.
    - Maps chunk vectors to canonical Folio Document IDs and revisions.
    - Deduplicates multi-chunk documents with deterministic tie-breaking (score DESC, doc_id ASC).
    """

    def __init__(
        self,
        chroma_path: Optional[str] = None,
        collection_name: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        self.chroma_path = chroma_path or settings.CHROMA_PATH
        self.collection_name = collection_name or settings.CHROMA_COLLECTION_NAME
        self.model_name = model_name or settings.EMBEDDING_MODEL_NAME

        self._client = None
        self._collection = None
        self._ef = None
        self._initialized = False
        self._init_error: Optional[str] = None

    def check_availability(self) -> Tuple[bool, Optional[str]]:
        """
        Verifies whether ChromaDB library, model, and persistent directory are reachable.
        Returns (is_available, error_reason).
        """
        # 1. Check ChromaDB import
        try:
            import chromadb
            from chromadb.utils import embedding_functions
        except ImportError as e:
            return False, "ChromaDB service unreachable"
        except Exception as e:
            return False, "SentenceTransformer model unavailable"

        # 2. Check path exists
        if not self.chroma_path or not Path(self.chroma_path).exists():
            return False, "ChromaDB service unreachable"

        # 3. Try initializing client and collection
        try:
            if self._collection is None:
                self._client = chromadb.PersistentClient(path=self.chroma_path)
                try:
                    self._ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                        model_name=self.model_name
                    )
                except Exception:
                    return False, "SentenceTransformer model unavailable"

                self._collection = self._client.get_collection(
                    name=self.collection_name,
                    embedding_function=self._ef,
                )
            return True, None
        except Exception as e:
            err_str = str(e).lower()
            if "model" in err_str or "sentence" in err_str or "transformer" in err_str or "oom" in err_str:
                return False, "SentenceTransformer model unavailable"
            return False, "ChromaDB service unreachable"

    def query(
        self,
        query_text: str,
        top_k: int = 100,
        db: Optional[Session] = None,
    ) -> Tuple[List[SemanticCandidateHit], Optional[str]]:
        """
        Executes dense vector search against ChromaDB.
        Returns:
            (candidates, None) on success
            ([], degraded_reason) when unavailable
        """
        is_avail, error_reason = self.check_availability()
        if not is_avail:
            return [], error_reason

        try:
            count = self._collection.count()
            if count == 0:
                return [], None

            fetch_n = min(300, max(top_k * 2, count))
            res = self._collection.query(
                query_texts=[query_text],
                n_results=fetch_n,
            )

            if not res or not res.get("documents") or not res["documents"][0]:
                return [], None

            docs = res["documents"][0]
            metas = res.get("metadatas", [[]])[0]
            distances = res.get("distances", [[]])[0]

            # Build URL to Document ID mapping cache from DB if available
            url_to_doc_id: Dict[str, str] = {}
            if db:
                from src.backend.models.document import Document
                db_docs = db.query(Document.id, Document.source_url).filter(Document.source_url.is_not(None)).all()
                for d_id, s_url in db_docs:
                    if s_url:
                        url_to_doc_id[s_url.strip()] = d_id

            # Group chunks by document_id
            grouped_chunks: Dict[str, List[float]] = {}
            for doc_text, meta, dist in zip(docs, metas, distances):
                meta = meta or {}
                doc_id = meta.get("document_id") or meta.get("doc_id")
                if not doc_id:
                    url = meta.get("url", "").strip()
                    if url:
                        doc_id = url_to_doc_id.get(url) or generate_doc_uuid_from_url(url)
                    else:
                        continue

                if doc_id not in grouped_chunks:
                    grouped_chunks[doc_id] = []
                grouped_chunks[doc_id].append(float(dist))

            scored_candidates: List[SemanticCandidateHit] = []
            for doc_id, dist_list in grouped_chunks.items():
                best_dist = min(dist_list)
                avg_dist = sum(dist_list) / len(dist_list)
                weighted_dist = best_dist * 0.6 + avg_dist * 0.4
                # Convert distance to similarity score in [0.0, 1.0]
                similarity = max(0.0, 1.0 - weighted_dist)

                scored_candidates.append(
                    SemanticCandidateHit(
                        doc_id=doc_id,
                        score=round(similarity, 6),
                        rank=0,
                        raw_distance=round(weighted_dist, 6),
                        chunk_count=len(dist_list),
                    )
                )

            # Deterministic Tie-Breaking: Primary sort = score DESC, Secondary sort = doc_id ASC
            scored_candidates.sort(key=lambda hit: (-hit.score, hit.doc_id))

            ranked_hits: List[SemanticCandidateHit] = []
            for rank_idx, hit in enumerate(scored_candidates[:top_k], start=1):
                ranked_hits.append(
                    SemanticCandidateHit(
                        doc_id=hit.doc_id,
                        score=hit.score,
                        rank=rank_idx,
                        raw_distance=hit.raw_distance,
                        chunk_count=hit.chunk_count,
                    )
                )

            return ranked_hits, None

        except Exception as e:
            err_str = str(e).lower()
            if "model" in err_str or "oom" in err_str:
                return [], "SentenceTransformer model unavailable"
            return [], "ChromaDB service unreachable"
