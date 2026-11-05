#!/usr/bin/env python3
"""
Folio Search Index Lifecycle Worker Runner CLI.
Polls outbox index_jobs table and synchronizes document mutations into active lexical index.
"""
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.search_index.worker import main

if __name__ == "__main__":
    sys.exit(main())
