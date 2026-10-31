# Folio Fixture Sources & Licensing

This document details the provenance, licensing, curation methodology, and schema mapping for the portable seed dataset located in `fixtures/folio/documents.jsonl`.

## 1. Overview & Provenance

- **Total Documents:** 103 records (100 published research articles + 3 internal working drafts).
- **Primary Source:** Curated and streamed from English Wikipedia and the project's web crawler corpus (`data/raw/wiki_crawler_dataset.jsonl`).
- **Domain Focus:** Enterprise Document & Research Repository spanning Artificial Intelligence & Machine Learning, Computer Science & Systems, Neuroscience & Cognitive Science, Mathematics & Optimization, Scientific Research & Publishing, and Technology & Society.
- **Portability:** The fixture dataset is completely self-contained and tracked in Git. It enables fresh environments, CI/CD runners, and ephemeral demo databases (`folio_demo`) to seed a complete, realistic document catalog without requiring external API dependencies or raw crawl corpora.
- **Demo Dates Notice:** All document `created_at` and `published_at` timestamps are synthetic demonstration dates spaced across calendar year 2026 to showcase chronological catalog filtering, timeline views, and date formatting during presentations.

## 2. Category Distribution

The fixture catalog is balanced across the 6 core taxonomy categories:

| Category Slug | Display Name | Published | Drafts | Total | Description |
|---|---|---|---|---|---|
| `ai-machine-learning` | Artificial Intelligence & Machine Learning | 18 | 0 | **18** | Deep architectures, transformers, neural computation, cognitive robotics |
| `computer-science-systems` | Computer Science & Systems | 18 | 1 | **19** | Data structures, algorithms, complexity theory, cryptography, OS & networks |
| `neuroscience-cognitive-science` | Neuroscience & Cognitive Science | 16 | 1 | **17** | Cognitive load theory, neuroplasticity, memory systems, neuroethics |
| `mathematics-optimization` | Mathematics & Optimization | 16 | 0 | **16** | Mathematical programming, Bayesian optimization, probability, graph theory |
| `scientific-research-publishing` | Scientific Research & Publishing | 16 | 0 | **16** | Peer review, open access initiatives, preprint repositories, metadata |
| `technology-society` | Technology & Society | 16 | 1 | **17** | Workplace ethics, work–life balance, labor economics, automation |
| **Total** | | **100** | **3** | **103** | |

### Key Classification Corrections
- Reclassified foundational CS systems articles (e.g. `Binary search tree`, `B-tree`, `Complexity class`, `Public-key cryptography`, `PPAD (complexity)`) into `computer-science-systems` (up from 3 to 19 total).
- Reclassified core AI/ML articles (e.g. `Deep learning`, `Transformer (deep learning)`, `Residual neural network`, `Long short-term memory`, `Cognitive robotics`) into `ai-machine-learning` (up from 6 to 18 total).
- Corrected misclassifications from early automated crawl passes:
  - `"Work ethic"` is assigned to `technology-society`.
  - `"Work–life balance"` is assigned to `technology-society` with normalized UTF-8 em-dash punctuation.
  - Repetitive labor and employment scraper duplicates were trimmed and balanced in favor of technical computer science and neuroscience research papers.

## 3. Data Cleaning Pipeline

Every document record underwent automated cleaning and curation:
1. **Summary Debris Removal:** Stripped all Wikipedia wiki-markup debris, including `[edit]`, `[citation needed]`, reference tags (`[1]`, `[2]`, `[note ...]`), coordinate headers, and navigational notices (`"Jump to navigation"`).
2. **Disambiguation & Lead Extraction:** Removed introductory disambiguation headers (e.g. `"For other uses, see..."`, `"This article is about..."`, `"XYZ redirects here."`) and raw markdown infobox tables (`| ... |`).
3. **Academic Abstract Normalization:** Summaries were compiled into clean, coherent 2–3 sentence academic abstracts (160–350 characters) defining the theoretical core, methodology, and relevance of each topic.
4. **Content Preservation:** Full article bodies are retained intact in Markdown/text format without truncation, enabling authentic reading views in the frontend document viewer.
5. **Deterministic Identifiers:** UUID v5 identifiers are deterministically generated from canonical `source_url` values, ensuring idempotency across repeated database seeding runs.

## 4. Local Demonstration Illustrations & Provenance

Eight documents feature local high-resolution SVG diagrams located in `src/frontend/assets/demo/`:

| Document Title | Category | Cover Image URL | Diagram Subject & Purpose | License |
|---|---|---|---|---|
| **Deep learning** | `ai-machine-learning` | `/assets/demo/neural_network_architecture.svg` | Multilayer feedforward perceptron with forward propagation & layer mapping | CC BY-SA 4.0 |
| **Transformer (deep learning)** | `ai-machine-learning` | `/assets/demo/transformer_attention.svg` | Multi-head self-attention mechanism and scaled dot-product core | CC BY-SA 4.0 |
| **Binary search tree** | `computer-science-systems` | `/assets/demo/binary_search_tree.svg` | Binary search tree node hierarchy, subtrees, and in-order traversal | CC BY-SA 4.0 |
| **B-tree** | `computer-science-systems` | `/assets/demo/b_tree_indexing.svg` | Multi-way balanced disk index structure with block nodes & leaf pointers | CC BY-SA 4.0 |
| **Gradient descent** | `ai-machine-learning` | `/assets/demo/gradient_descent_optimization.svg` | Loss surface contour plot with iterative gradient descent trajectory | CC BY-SA 4.0 |
| **Cognitive load** | `neuroscience-cognitive-science` | `/assets/demo/cognitive_load_theory.svg` | Working memory capacity model: intrinsic, extraneous, and germane load | CC BY-SA 4.0 |
| **Peer review** | `scientific-research-publishing` | `/assets/demo/peer_review_process.svg` | Scholarly peer review lifecycle: submission, triage, refereeing, revision | CC BY-SA 4.0 |
| **Public-key cryptography** | `computer-science-systems` | `/assets/demo/public_key_cryptography.svg` | Asymmetric encryption model: public key encryption and private key decryption | CC BY-SA 4.0 |

- **Asset Licensing:** Original technical vector diagrams created for the Folio project repository, licensed under Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0).
- **Serving:** Static assets are served directly through FastAPI from `src/frontend/assets/demo/`.

## 5. Licensing & Attribution

- **Wikipedia Content:** Wikipedia contributors, available under Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0) and GNU Free Documentation License (GFDL).
- **Source Attribution:** Retained in `source_attribution` (`"Wikipedia contributors, available under CC BY-SA 4.0"` or `"Wikipedia contributors / Folio Research, available under CC BY-SA 4.0"`).
- **Source URLs:** Every document retains its canonical permalink in `source_url`.
- **Working Drafts:** Internal research working drafts authored by `"Folio Research Working Group"`, licensed under CC BY 4.0.

## 6. Schema Mapping

| Field | Source / Derivation | Notes |
|---|---|---|
| `id` | Deterministic UUID v5 generated from `source_url` | Stable and idempotent across repeated seeds and migrations |
| `title` | Original normalized article title | Plain text string (max 240 chars) |
| `content` | Full markdown / plain text of article | Retained in full for server-side HTML rendering |
| `summary` | Clean 2–3 sentence academic abstract | Plain text (120–400 chars), zero wiki debris |
| `category_slug` | Curated research taxonomy slug | Mapped to Category entity (`ai-machine-learning`, etc.) |
| `category_name` | Human-readable category label | Display title for category |
| `tags` | Domain and subject keywords | Linked via `document_tags` join table (max 4 per doc) |
| `author` | "Wikipedia contributors" or "Folio Research Working Group" | Preserves actual copyright and provenance |
| `created_at` | RFC 3339 timestamp (UTC) | Synthetic presentation demo dates across 2026 |
| `published_at` | RFC 3339 timestamp (UTC) | Identical to `created_at` for published; null for drafts |
| `status` | `"published"` or `"draft"` | Drafts excluded from public catalog browsing |
| `cover_image_url` | Local static asset path (`/assets/demo/...`) | Null for documents without demo diagram |
| `cover_image_alt` | Descriptive accessibility alt text | Captions and screen-reader accessibility description |
| `source_url` | Canonical article URL | Wikipedia permalink or local draft URI |
| `source_license` | License identifier | `CC BY-SA 4.0` or `CC BY 4.0` |
| `source_attribution` | Full attribution string | Respects copyright and contributor attribution |
| `seo_title` | `[Title] — Folio Knowledge & Research Library` | Document title for search engines |
| `seo_description` | First 160 characters of clean summary | Meta description for search engines |
| `seo_keywords` | JSON array of tags and primary keywords | Keyword metadata for discoverability |
