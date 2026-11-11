"""
Folio Inverted Index Data Structures and Persistence.

Maintains:
- Posting lists mapping term -> list of (doc_id, tf)
- Term dictionary mapping term -> document frequency (df)
- Document lengths mapping doc_id -> |d|
- Document metadata for candidate-level filtering (category_id, tag_ids, created_at, status, title)
- Corpus-level statistics: total_docs (N), total_tokens, avg_doc_len (avgdl)
- Atomic disk serialization and deserialization
"""

import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Set, Optional, Any

from src.backend.search.analyzer import TextAnalyzer, default_analyzer, ANALYZER_VERSION


class GenerationMismatchError(Exception):
    """Raised when an index generation on disk does not match requested generation or schema."""
    pass


@dataclass
class DocumentMetadata:
    """Document attributes preserved in the index for rapid filtering and scoring."""
    doc_id: str
    title: str
    category_id: Optional[str] = None
    tag_ids: List[str] = field(default_factory=list)
    created_at: Optional[str] = None  # ISO 8601 UTC
    status: str = "published"
    doc_len: int = 0


@dataclass
class CorpusStats:
    """Corpus-level statistics required for BM25 and TF-IDF scoring."""
    total_docs: int = 0
    total_tokens: int = 0
    avg_doc_len: float = 0.0
    vocabulary_size: int = 0
    analyzer_version: str = ANALYZER_VERSION
    generation_id: str = ""


class InvertedIndex:
    """
    In-memory Inverted Index with posting lists, term dictionary,
    document metadata, and corpus collection statistics.
    """

    def __init__(
        self,
        generation_id: str = "",
        analyzer: Optional[TextAnalyzer] = None,
    ):
        self.generation_id = generation_id
        self.analyzer = analyzer or default_analyzer
        self.analyzer_version = self.analyzer.version

        # Term -> list of (doc_id, term_frequency)
        self.postings: Dict[str, List[Tuple[str, int]]] = {}

        # Term -> Document frequency (number of documents containing term)
        self.df: Dict[str, int] = {}

        # doc_id -> DocumentMetadata (including doc_len, category_id, tag_ids, created_at, status, title)
        self.documents: Dict[str, DocumentMetadata] = {}

        # Corpus aggregate metrics
        self.total_docs: int = 0
        self.total_tokens: int = 0
        self.avg_doc_len: float = 0.0
        self.index_version: str = ""
        self.checksum: str = ""

    def _recalculate_corpus_stats(self):
        """Updates corpus-level metrics (N, total_tokens, avgdl)."""
        self.total_docs = len(self.documents)
        self.total_tokens = sum(doc.doc_len for doc in self.documents.values())
        if self.total_docs > 0:
            self.avg_doc_len = self.total_tokens / self.total_docs
        else:
            self.avg_doc_len = 0.0
        self.index_version = f"mem-{uuid.uuid4().hex[:12]}"

    def upsert_document(
        self,
        doc_id: str,
        text: str,
        title: str = "",
        category_id: Optional[str] = None,
        tag_ids: Optional[List[str]] = None,
        created_at: Optional[str] = None,
        status: str = "published",
    ):
        """
        Indexes or updates a document in the inverted index:
        1. If doc_id already exists, safely removes its previous postings.
        2. Analyzes combined title and text using the versioned analyzer.
        3. Appends (doc_id, tf) to each unique term's posting list.
        4. Updates term frequencies, document frequencies, and corpus statistics.
        """
        # Remove old occurrence if updating
        if doc_id in self.documents:
            self.delete_document(doc_id)

        analysis = self.analyzer.analyze(text)
        term_freqs = analysis.term_frequencies
        doc_len = analysis.doc_len

        meta = DocumentMetadata(
            doc_id=doc_id,
            title=title,
            category_id=category_id,
            tag_ids=list(tag_ids or []),
            created_at=created_at,
            status=status,
            doc_len=doc_len,
        )
        self.documents[doc_id] = meta

        # Add to posting lists
        for term, tf in term_freqs.items():
            if term not in self.postings:
                self.postings[term] = []
                self.df[term] = 0
            self.postings[term].append((doc_id, tf))
            self.df[term] += 1

        self._recalculate_corpus_stats()

    def delete_document(self, doc_id: str) -> bool:
        """
        Removes a document from the inverted index and all associated posting lists.
        Decrements term frequencies and cleans up orphan terms.
        """
        if doc_id not in self.documents:
            return False

        del self.documents[doc_id]

        terms_to_delete = []
        for term, plist in self.postings.items():
            new_plist = [p for p in plist if p[0] != doc_id]
            if len(new_plist) != len(plist):
                self.postings[term] = new_plist
                self.df[term] = len(new_plist)
                if self.df[term] == 0:
                    terms_to_delete.append(term)

        for term in terms_to_delete:
            del self.postings[term]
            del self.df[term]

        self._recalculate_corpus_stats()
        return True

    def get_corpus_stats(self) -> CorpusStats:
        """Returns snapshot of current corpus statistics."""
        return CorpusStats(
            total_docs=self.total_docs,
            total_tokens=self.total_tokens,
            avg_doc_len=self.avg_doc_len,
            vocabulary_size=len(self.df),
            analyzer_version=self.analyzer_version,
            generation_id=self.generation_id,
        )

    def get_candidate_doc_ids(self, query_terms: List[str]) -> Set[str]:
        """
        Retrieves candidate document IDs matching ANY of the query terms.
        Guarantees that query execution traverses ONLY term posting lists,
        never scanning the entire document collection.
        """
        candidate_ids: Set[str] = set()
        for term in query_terms:
            plist = self.postings.get(term)
            if plist:
                for doc_id, _ in plist:
                    candidate_ids.add(doc_id)
        return candidate_ids

    def save(self, storage_dir: Path):
        """
        Atomically saves the inverted index, posting lists, document metadata,
        and corpus statistics to the target postings directory.
        Write order guarantees readers never observe half-written state:
        1. doc_entries.json (via unique temp file + atomic replace)
        2. postings.json (via unique temp file + atomic replace)
        3. index_stats.json (commit/version marker written last via unique temp file + atomic replace)
        """
        storage_dir = Path(storage_dir)
        storage_dir.mkdir(parents=True, exist_ok=True)

        doc_entries = {
            doc_id: {
                "doc_id": m.doc_id,
                "title": m.title,
                "category_id": m.category_id,
                "tag_ids": m.tag_ids,
                "created_at": m.created_at,
                "status": m.status,
                "doc_len": m.doc_len,
            }
            for doc_id, m in self.documents.items()
        }
        docs_bytes = json.dumps(doc_entries, indent=2, sort_keys=True).encode("utf-8")
        docs_sha256 = hashlib.sha256(docs_bytes).hexdigest()

        postings_payload = {
            "postings": self.postings,
            "df": self.df,
        }
        postings_bytes = json.dumps(postings_payload, sort_keys=True).encode("utf-8")
        postings_sha256 = hashlib.sha256(postings_bytes).hexdigest()

        checksum = hashlib.sha256(f"{docs_sha256}:{postings_sha256}".encode("utf-8")).hexdigest()
        now_utc = datetime.now(timezone.utc)
        index_version = f"{now_utc.strftime('%Y%m%d%H%M%S%f')}-{uuid.uuid4().hex[:8]}"
        self.checksum = checksum
        self.index_version = index_version

        stats = {
            "generation_id": self.generation_id,
            "analyzer_version": self.analyzer_version,
            "total_docs": self.total_docs,
            "total_tokens": self.total_tokens,
            "avg_doc_len": self.avg_doc_len,
            "vocabulary_size": len(self.df),
            "updated_at": now_utc.isoformat(),
            "index_version": index_version,
            "checksum": checksum,
            "docs_sha256": docs_sha256,
            "postings_sha256": postings_sha256,
        }
        stats_bytes = json.dumps(stats, indent=2, sort_keys=True).encode("utf-8")

        tmp_suffix = f".{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"

        # 1. Write doc metadata first
        docs_tmp = storage_dir / f".doc_entries.json{tmp_suffix}"
        with open(docs_tmp, "wb") as f:
            f.write(docs_bytes)
            f.flush()
        os.replace(docs_tmp, storage_dir / "doc_entries.json")

        # 2. Write postings and df second
        postings_tmp = storage_dir / f".postings.json{tmp_suffix}"
        with open(postings_tmp, "wb") as f:
            f.write(postings_bytes)
            f.flush()
        os.replace(postings_tmp, storage_dir / "postings.json")

        # 3. Write stats / version marker last
        stats_tmp = storage_dir / f".index_stats.json{tmp_suffix}"
        with open(stats_tmp, "wb") as f:
            f.write(stats_bytes)
            f.flush()
        os.replace(stats_tmp, storage_dir / "index_stats.json")

    @classmethod
    def read_disk_signature(cls, storage_dir: Path) -> Optional[Tuple[Any, ...]]:
        """
        Reads a lightweight version/checksum signature from index_stats.json
        to detect cross-process or same-generation disk updates without loading full postings.
        """
        storage_dir = Path(storage_dir)
        stats_file = storage_dir / "index_stats.json"
        docs_file = storage_dir / "doc_entries.json"
        postings_file = storage_dir / "postings.json"

        if not stats_file.exists() or not docs_file.exists() or not postings_file.exists():
            return None

        for _ in range(3):
            try:
                st = stats_file.stat()
                docs_st = docs_file.stat()
                postings_st = postings_file.stat()
                with open(stats_file, "r", encoding="utf-8") as f:
                    stats = json.load(f)
                return (
                    stats.get("generation_id", ""),
                    stats.get("index_version", ""),
                    stats.get("checksum", ""),
                    stats.get("total_docs", 0),
                    stats.get("total_tokens", 0),
                    stats.get("updated_at", ""),
                    st.st_mtime_ns,
                    st.st_size,
                    docs_st.st_mtime_ns,
                    docs_st.st_size,
                    postings_st.st_mtime_ns,
                    postings_st.st_size,
                )
            except Exception:
                time.sleep(0.005)
        return None

    @classmethod
    def load(cls, storage_dir: Path, expected_generation_id: Optional[str] = None) -> "InvertedIndex":
        """
        Loads an InvertedIndex from disk.
        Validates presence of files, generation consistency, and cross-file checksum integrity.
        """
        storage_dir = Path(storage_dir)
        stats_file = storage_dir / "index_stats.json"
        docs_file = storage_dir / "doc_entries.json"
        postings_file = storage_dir / "postings.json"

        if not stats_file.exists() or not docs_file.exists() or not postings_file.exists():
            raise FileNotFoundError(f"Missing required index files in {storage_dir}")

        stats: Dict[str, Any] = {}
        doc_entries: Dict[str, Any] = {}
        postings_data: Dict[str, Any] = {}

        last_err: Optional[Exception] = None
        for attempt in range(4):
            try:
                stats_bytes = stats_file.read_bytes()
                docs_bytes = docs_file.read_bytes()
                postings_bytes = postings_file.read_bytes()

                stats = json.loads(stats_bytes)
                expected_docs_sha = stats.get("docs_sha256")
                expected_postings_sha = stats.get("postings_sha256")

                if expected_docs_sha:
                    actual_docs_sha = hashlib.sha256(docs_bytes).hexdigest()
                    if actual_docs_sha != expected_docs_sha:
                        raise GenerationMismatchError("Transient or corrupt doc_entries.json checksum mismatch")

                if expected_postings_sha:
                    actual_postings_sha = hashlib.sha256(postings_bytes).hexdigest()
                    if actual_postings_sha != expected_postings_sha:
                        raise GenerationMismatchError("Transient or corrupt postings.json checksum mismatch")

                doc_entries = json.loads(docs_bytes)
                postings_data = json.loads(postings_bytes)
                last_err = None
                break
            except Exception as e:
                last_err = e
                if attempt < 3:
                    time.sleep(0.005)

        if last_err is not None:
            raise last_err

        gen_id = stats.get("generation_id", "")
        if expected_generation_id and gen_id != expected_generation_id:
            raise GenerationMismatchError(
                f"Generation mismatch: index contains {gen_id}, expected {expected_generation_id}"
            )

        index = cls(generation_id=gen_id)
        index.analyzer_version = stats.get("analyzer_version", ANALYZER_VERSION)
        index.total_docs = stats.get("total_docs", 0)
        index.total_tokens = stats.get("total_tokens", 0)
        index.avg_doc_len = stats.get("avg_doc_len", 0.0)
        index.index_version = stats.get("index_version", "")
        index.checksum = stats.get("checksum", "")

        # Reconstruct doc metadata
        for doc_id, d in doc_entries.items():
            index.documents[doc_id] = DocumentMetadata(
                doc_id=d["doc_id"],
                title=d.get("title", ""),
                category_id=d.get("category_id"),
                tag_ids=d.get("tag_ids", []),
                created_at=d.get("created_at"),
                status=d.get("status", "published"),
                doc_len=d.get("doc_len", 0),
            )

        # Reconstruct postings and df (preserve decoded 2-element [doc_id, tf] pairs directly to avoid cold-load tuple copy overhead)
        raw_postings = postings_data.get("postings")
        index.postings = raw_postings if isinstance(raw_postings, dict) else {}
        raw_df = postings_data.get("df")
        index.df = raw_df if isinstance(raw_df, dict) else {}

        return index
