import math
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
    source_url: Optional[str] = None


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

    def _create_client(
        self,
        chromadb_mod,
        chroma_host: str,
        chroma_port: int,
        timeout_sec: Optional[float] = None,
    ):
        """Creates Chroma PersistentClient or HttpClient with bounded HTTP I/O timeouts."""
        if not chroma_host:
            return chromadb_mod.PersistentClient(path=self.chroma_path)

        effective_timeout = max(
            1,
            int(math.ceil(timeout_sec if timeout_sec is not None else getattr(settings, "SEARCH_TIMEOUT_SECONDS", 5.0))),
        )
        try:
            from chromadb.config import Settings as ChromaSettings

            fields = getattr(ChromaSettings, "model_fields", None) or getattr(ChromaSettings, "__fields__", {})
            kwargs = {}
            for attr in (
                "chroma_query_request_timeout_seconds",
                "chroma_sysdb_request_timeout_seconds",
                "chroma_logservice_request_timeout_seconds",
            ):
                if attr in fields:
                    kwargs[attr] = effective_timeout
            if kwargs:
                return chromadb_mod.HttpClient(
                    host=chroma_host,
                    port=chroma_port,
                    settings=ChromaSettings(**kwargs),
                )
        except Exception:
            pass
        return chromadb_mod.HttpClient(host=chroma_host, port=chroma_port)

    def check_availability(self, load_model: bool = True) -> Tuple[bool, Optional[str]]:
        """
        Verifies whether ChromaDB library, model, and persistent directory (or HTTP host) are reachable.
        When load_model=False (used by lightweight readiness probes), checks package & store reachability
        without instantiating heavy SentenceTransformer weights on every probe.
        Returns (is_available, error_reason).
        """
        # 1. Check ChromaDB import
        try:
            import chromadb
            from chromadb.utils import embedding_functions
        except ImportError:
            return False, "ChromaDB service unreachable"
        except Exception:
            return False, "SentenceTransformer model unavailable"

        chroma_host = getattr(settings, "CHROMA_HOST", "") or os.getenv("CHROMA_HOST", "")
        chroma_port = int(getattr(settings, "CHROMA_PORT", 8000) or os.getenv("CHROMA_PORT", "8000") or 8000)

        # 2. Check path exists when using local persistent storage
        if not chroma_host:
            if not self.chroma_path or not Path(self.chroma_path).exists():
                return False, "ChromaDB service unreachable"

        # 3. Lightweight readiness mode (avoids loading heavy ML weights on every /health/ready ping)
        if not load_model:
            try:
                import sentence_transformers  # noqa: F401
            except Exception:
                return False, "SentenceTransformer model unavailable"
            try:
                client = self._create_client(chromadb, chroma_host, chroma_port, timeout_sec=2.0)
                client.get_collection(name=self.collection_name)
                return True, None
            except Exception as e:
                err_str = str(e).lower()
                if "model" in err_str or "sentence" in err_str or "transformer" in err_str or "oom" in err_str:
                    return False, "SentenceTransformer model unavailable"
                return False, "ChromaDB service unreachable"

        # 4. Full initialization for query execution
        try:
            if self._collection is None:
                self._client = self._create_client(chromadb, chroma_host, chroma_port)
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

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 1200, overlap: int = 150) -> List[str]:
        cleaned = (text or "").strip()
        if not cleaned:
            return []
        if len(cleaned) <= chunk_size:
            return [cleaned]
        chunks: List[str] = []
        step = max(1, chunk_size - overlap)
        for start in range(0, len(cleaned), step):
            piece = cleaned[start : start + chunk_size].strip()
            if piece:
                chunks.append(piece)
            if start + chunk_size >= len(cleaned):
                break
        return chunks

    def _ensure_writable_collection(self):
        """
        Returns a writable ChromaDB collection when Chroma is configured and installed,
        or None when semantic search is disabled/uninstalled in SQL-first environments.
        """
        if self._collection is not None:
            return self._collection

        chroma_host = getattr(settings, "CHROMA_HOST", "") or os.getenv("CHROMA_HOST", "")
        chroma_port = int(getattr(settings, "CHROMA_PORT", 8000) or os.getenv("CHROMA_PORT", "8000") or 8000)
        has_local_store = bool(self.chroma_path and Path(self.chroma_path).exists())
        if not chroma_host and not has_local_store:
            return None

        try:
            import chromadb
            from chromadb.utils import embedding_functions
        except Exception:
            if chroma_host:
                raise RuntimeError("CHROMA_HOST is configured but chromadb is not installed")
            return None

        self._client = self._create_client(chromadb, chroma_host, chroma_port)
        self._ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=self.model_name
        )
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=self._ef,
        )
        return self._collection

    def delete_document(self, doc_id: str) -> bool:
        """
        Deletes all vector chunks belonging to doc_id so unpublished or deleted
        documents are immediately evicted from semantic retrieval.
        """
        collection = self._ensure_writable_collection()
        if collection is None:
            return False
        collection.delete(where={"document_id": doc_id})
        return True

    def upsert_document(
        self,
        doc_id: str,
        title: str,
        summary: str,
        content: str,
        source_url: Optional[str] = None,
        revision_hash: Optional[str] = None,
    ) -> bool:
        """
        Replaces vector chunks for doc_id atomically (delete old chunks first, then upsert
        freshly chunked text with document_id and revision_hash metadata).
        """
        collection = self._ensure_writable_collection()
        if collection is None:
            return False

        collection.delete(where={"document_id": doc_id})
        combined = f"{title or ''}\n\n{summary or ''}\n\n{content or ''}".strip()
        chunks = self._chunk_text(combined)
        if not chunks:
            return True

        ids = [f"{doc_id}::chunk_{idx}" for idx in range(len(chunks))]
        metadatas = [
            {
                "document_id": doc_id,
                "chunk_index": idx,
                "url": (source_url or "").strip(),
                "revision_hash": (revision_hash or "").strip(),
            }
            for idx in range(len(chunks))
        ]
        collection.upsert(ids=ids, documents=chunks, metadatas=metadatas)
        return True

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
            doc_urls: Dict[str, str] = {}
            for doc_text, meta, dist in zip(docs, metas, distances):
                meta = meta or {}
                doc_id = meta.get("document_id") or meta.get("doc_id")
                url = (meta.get("url") or "").strip()
                if not doc_id:
                    if url:
                        doc_id = url_to_doc_id.get(url) or generate_doc_uuid_from_url(url)
                    else:
                        continue

                if doc_id not in grouped_chunks:
                    grouped_chunks[doc_id] = []
                grouped_chunks[doc_id].append(float(dist))
                if url and doc_id not in doc_urls:
                    doc_urls[doc_id] = url

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
                        source_url=doc_urls.get(doc_id),
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
                        source_url=hit.source_url,
                    )
                )

            return ranked_hits, None

        except Exception as e:
            err_str = str(e).lower()
            if "model" in err_str or "oom" in err_str:
                return [], "SentenceTransformer model unavailable"
            return [], "ChromaDB service unreachable"
