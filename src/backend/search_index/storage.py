import os
import json
import shutil
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple, List

from src.backend.core.config import settings

def get_index_storage_root() -> Path:
    """Returns the base storage directory for index generations."""
    env_path = os.getenv("INDEX_STORAGE_DIR")
    if env_path:
        root = Path(env_path).resolve()
    else:
        root = settings.PROJECT_ROOT / "data" / "search_index" / "generations"
    root.mkdir(parents=True, exist_ok=True)
    return root


class GenerationStorage:
    """Manages physical files, manifests, and snapshots for an index generation."""

    def __init__(self, generation_id: str):
        self.generation_id = generation_id
        self.dir_path = get_index_storage_root() / generation_id
        self.manifest_path = self.dir_path / "manifest.json"
        self.postings_dir = self.dir_path / "postings"

    def exists(self) -> bool:
        return self.manifest_path.exists()

    def initialize(self, generation_num: int) -> Dict[str, Any]:
        """Creates the generation directory, empty postings directory, and base manifest."""
        self.dir_path.mkdir(parents=True, exist_ok=True)
        self.postings_dir.mkdir(parents=True, exist_ok=True)

        manifest = {
            "generation_id": self.generation_id,
            "generation_num": generation_num,
            "schema_version": "1.0.0",
            "analyzer_version": "1.0.0",  # Contract for P04
            "doc_count": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "checksum": hashlib.sha256(b"").hexdigest(),
            "docs": {},
        }
        self.save_manifest(manifest)
        return manifest

    def load_manifest(self) -> Optional[Dict[str, Any]]:
        if not self.manifest_path.exists():
            return None
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_manifest(self, manifest: Dict[str, Any]):
        # Recompute checksum based on deterministic sorted doc entries
        docs = manifest.get("docs", {})
        doc_count = len(docs)
        manifest["doc_count"] = doc_count

        hasher = hashlib.sha256()
        for doc_id in sorted(docs.keys()):
            entry = docs[doc_id]
            doc_line = f"{doc_id}:{entry.get('revision_hash', '')}:{entry.get('title', '')}"
            hasher.update(doc_line.encode("utf-8"))
        manifest["checksum"] = hasher.hexdigest()

        temp_path = self.manifest_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        temp_path.replace(self.manifest_path)

    def upsert_document(self, doc_id: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Adds or updates a document metadata entry in the generation manifest."""
        manifest = self.load_manifest()
        if manifest is None:
            manifest = self.initialize(0)

        manifest["docs"][doc_id] = {
            "id": doc_id,
            "title": metadata.get("title", ""),
            "summary": metadata.get("summary", ""),
            "category_slug": metadata.get("category_slug", ""),
            "tags": metadata.get("tags", []),
            "revision_hash": metadata.get("revision_hash", ""),
            "updated_at": metadata.get("updated_at", datetime.now(timezone.utc).isoformat()),
        }
        self.save_manifest(manifest)
        return manifest

    def delete_document(self, doc_id: str) -> Dict[str, Any]:
        """Removes a document from the generation manifest if present."""
        manifest = self.load_manifest()
        if manifest is None:
            return {}

        if doc_id in manifest["docs"]:
            del manifest["docs"][doc_id]
            self.save_manifest(manifest)
        return manifest

    def get_indexed_doc_ids(self) -> List[str]:
        manifest = self.load_manifest()
        if not manifest:
            return []
        return sorted(list(manifest.get("docs", {}).keys()))

    def verify_integrity(self) -> Tuple[bool, List[str]]:
        """Verifies manifest existence, structure, and internal checksum consistency."""
        errors = []
        if not self.dir_path.exists():
            return False, [f"Directory {self.dir_path} does not exist"]
        if not self.manifest_path.exists():
            return False, [f"Manifest {self.manifest_path} does not exist"]

        try:
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as e:
            return False, [f"Manifest JSON corrupt: {e}"]

        for key in ["generation_id", "generation_num", "schema_version", "doc_count", "checksum", "docs"]:
            if key not in manifest:
                errors.append(f"Missing required manifest key: {key}")

        docs = manifest.get("docs", {})
        if len(docs) != manifest.get("doc_count", -1):
            errors.append(f"doc_count mismatch: manifest says {manifest.get('doc_count')} but docs dict has {len(docs)}")

        # Verify checksum
        hasher = hashlib.sha256()
        for doc_id in sorted(docs.keys()):
            entry = docs[doc_id]
            doc_line = f"{doc_id}:{entry.get('revision_hash', '')}:{entry.get('title', '')}"
            hasher.update(doc_line.encode("utf-8"))
        expected_checksum = hasher.hexdigest()
        if manifest.get("checksum") != expected_checksum:
            errors.append(f"Checksum mismatch: manifest {manifest.get('checksum')} != expected {expected_checksum}")

        return len(errors) == 0, errors

    def purge(self):
        """Safely removes the generation directory from disk."""
        if self.dir_path.exists():
            shutil.rmtree(self.dir_path, ignore_errors=True)
