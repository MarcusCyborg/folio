"""
Curates fixtures/folio/documents.jsonl:
- 100 published documents + 3 drafts = 103 records.
- Balanced across 6 categories:
    ai-machine-learning: 18
    computer-science-systems: 19 (18 pub + 1 draft)
    neuroscience-cognitive-science: 17 (16 pub + 1 draft)
    mathematics-optimization: 16 (16 pub)
    scientific-research-publishing: 16 (16 pub)
    technology-society: 17 (16 pub + 1 draft)
- Cleans summary debris across all records.
- Sets cover_image_url and cover_image_alt for 8 demo documents.
"""

import os
import sys
import json
import re
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.core.wiki_content import clean_wikipedia_content

RAW_DATA_PATH = PROJECT_ROOT / "data" / "raw" / "wiki_crawler_dataset.jsonl"
EXTRA_DATA_PATH = PROJECT_ROOT / "fixtures" / "folio" / "fetched_extra.json"
OUTPUT_FILE = PROJECT_ROOT / "fixtures" / "folio" / "documents.jsonl"

CATEGORY_DEFINITIONS = {
    "ai-machine-learning": {
        "name": "Artificial Intelligence & Machine Learning",
        "description": "Foundational neural network architectures, machine learning models, optimization, and cognitive robotics",
        "base_tags": ["artificial-intelligence", "machine-learning"]
    },
    "computer-science-systems": {
        "name": "Computer Science & Systems",
        "description": "Algorithms, complexity theory, data structures, operating systems, and distributed networks",
        "base_tags": ["computer-science", "systems"]
    },
    "neuroscience-cognitive-science": {
        "name": "Neuroscience & Cognitive Science",
        "description": "Biological neural dynamics, computational neuroscience, memory models, and cognitive architectures",
        "base_tags": ["neuroscience", "cognitive-science"]
    },
    "mathematics-optimization": {
        "name": "Mathematics & Optimization",
        "description": "Continuous and discrete optimization, probabilistic modeling, game theory, and mathematical programming",
        "base_tags": ["mathematics", "optimization"]
    },
    "scientific-research-publishing": {
        "name": "Scientific Research & Publishing",
        "description": "Scholarly peer review, open access initiatives, preprint repositories, and research dissemination",
        "base_tags": ["research", "publishing", "academic"]
    },
    "technology-society": {
        "name": "Technology & Society",
        "description": "Societal impacts of technology, labor economics, organizational structures, and workplace dynamics",
        "base_tags": ["technology", "society", "workplace"]
    }
}

DEMO_COVERS = {
    "Deep learning": {
        "cover_image_url": "/assets/demo/neural_network_architecture.svg",
        "cover_image_alt": "Diagram of a deep feedforward artificial neural network architecture with input, hidden, and output layers",
        "source_license": "CC BY-SA 4.0",
        "source_attribution": "Wikipedia contributors / Folio Research, available under CC BY-SA 4.0"
    },
    "Transformer (deep learning)": {
        "cover_image_url": "/assets/demo/transformer_attention.svg",
        "cover_image_alt": "Transformer multi-head self-attention mechanism diagram illustrating query, key, value projections and scaled dot-product attention",
        "source_license": "CC BY-SA 4.0",
        "source_attribution": "Wikipedia contributors / Folio Research, available under CC BY-SA 4.0"
    },
    "Binary search tree": {
        "cover_image_url": "/assets/demo/binary_search_tree.svg",
        "cover_image_alt": "Binary search tree node hierarchy demonstrating ordered left and right subtrees",
        "source_license": "CC BY-SA 4.0",
        "source_attribution": "Wikipedia contributors / Folio Research, available under CC BY-SA 4.0"
    },
    "B-tree": {
        "cover_image_url": "/assets/demo/b_tree_indexing.svg",
        "cover_image_alt": "Multi-way balanced B-tree index structure showing root, internal nodes, and leaf disk blocks",
        "source_license": "CC BY-SA 4.0",
        "source_attribution": "Wikipedia contributors / Folio Research, available under CC BY-SA 4.0"
    },
    "Gradient descent": {
        "cover_image_url": "/assets/demo/gradient_descent_optimization.svg",
        "cover_image_alt": "Loss surface contour plot with gradient descent optimization trajectory converging towards global minimum",
        "source_license": "CC BY-SA 4.0",
        "source_attribution": "Wikipedia contributors / Folio Research, available under CC BY-SA 4.0"
    },
    "Cognitive load": {
        "cover_image_url": "/assets/demo/cognitive_load_theory.svg",
        "cover_image_alt": "Cognitive Load Theory model separating intrinsic, extraneous, and germane cognitive load in working memory",
        "source_license": "CC BY-SA 4.0",
        "source_attribution": "Wikipedia contributors / Folio Research, available under CC BY-SA 4.0"
    },
    "Peer review": {
        "cover_image_url": "/assets/demo/peer_review_process.svg",
        "cover_image_alt": "Academic peer review workflow illustrating manuscript submission, editorial triage, referee critique, and revision lifecycle",
        "source_license": "CC BY-SA 4.0",
        "source_attribution": "Wikipedia contributors / Folio Research, available under CC BY-SA 4.0"
    },
    "Public-key cryptography": {
        "cover_image_url": "/assets/demo/public_key_cryptography.svg",
        "cover_image_alt": "Asymmetric public key cryptography diagram showing key pair generation, encryption with public key, and decryption with private key",
        "source_license": "CC BY-SA 4.0",
        "source_attribution": "Wikipedia contributors / Folio Research, available under CC BY-SA 4.0"
    }
}

# The 100 published titles allocated by category
TARGET_ARTICLES = [
    # AI / ML (18)
    ("ai-machine-learning", "Deep learning"),
    ("ai-machine-learning", "Transformer (deep learning)"),
    ("ai-machine-learning", "Gradient descent"),
    ("ai-machine-learning", "Geoffrey Hinton"),
    ("ai-machine-learning", "Residual neural network"),
    ("ai-machine-learning", "Long short-term memory"),
    ("ai-machine-learning", "Peter Dayan"),
    ("ai-machine-learning", "Terry Sejnowski"),
    ("ai-machine-learning", "Humanoid robot"),
    ("ai-machine-learning", "Swarm robotics"),
    ("ai-machine-learning", "Cognitive robotics"),
    ("ai-machine-learning", "Virtual assistant"),
    ("ai-machine-learning", "Neural engineering"),
    ("ai-machine-learning", "Neural decoding"),
    ("ai-machine-learning", "Dalle Molle Institute for Semantic and Cognitive Studies"),
    ("ai-machine-learning", "Brain–computer interface"),
    ("ai-machine-learning", "Workplace impact of artificial intelligence"),
    ("ai-machine-learning", "Open letter on artificial intelligence"),

    # Computer Science & Systems (18)
    ("computer-science-systems", "Binary search tree"),
    ("computer-science-systems", "B-tree"),
    ("computer-science-systems", "Public-key cryptography"),
    ("computer-science-systems", "PPAD (complexity)"),
    ("computer-science-systems", "Complexity class"),
    ("computer-science-systems", "PLS (complexity)"),
    ("computer-science-systems", "PPA (complexity)"),
    ("computer-science-systems", "PPP (complexity)"),
    ("computer-science-systems", "FNP (complexity)"),
    ("computer-science-systems", "Complete (complexity)"),
    ("computer-science-systems", "Electronic Colloquium on Computational Complexity"),
    ("computer-science-systems", "Open-source software movement"),
    ("computer-science-systems", "SIAM Journal on Computing"),
    ("computer-science-systems", "Computer network"),
    ("computer-science-systems", "Collaborative software"),
    ("computer-science-systems", "Desktop computer"),
    ("computer-science-systems", "Personal computer"),
    ("computer-science-systems", "Asynchrony (computer programming)"),

    # Neuroscience & Cognitive Science (16)
    ("neuroscience-cognitive-science", "Cognitive load"),
    ("neuroscience-cognitive-science", "Neuroscientist"),
    ("neuroscience-cognitive-science", "Nootropic"),
    ("neuroscience-cognitive-science", "Cognitive neuroscience"),
    ("neuroscience-cognitive-science", "Neuroplasticity"),
    ("neuroscience-cognitive-science", "Neuromodulation"),
    ("neuroscience-cognitive-science", "Neurogenesis"),
    ("neuroscience-cognitive-science", "Neurodiversity"),
    ("neuroscience-cognitive-science", "Neural circuit"),
    ("neuroscience-cognitive-science", "Social neuroscience"),
    ("neuroscience-cognitive-science", "Neuroethics"),
    ("neuroscience-cognitive-science", "Neuroeconomics"),
    ("neuroscience-cognitive-science", "Neurotechnology"),
    ("neuroscience-cognitive-science", "Mirror neuron"),
    ("neuroscience-cognitive-science", "Neural network (biology)"),
    ("neuroscience-cognitive-science", "Neuron doctrine"),

    # Mathematics & Optimization (16)
    ("mathematics-optimization", "Probability distribution"),
    ("mathematics-optimization", "Zero-sum game"),
    ("mathematics-optimization", "Kriging"),
    ("mathematics-optimization", "Bayesian optimization"),
    ("mathematics-optimization", "Gaussian process"),
    ("mathematics-optimization", "Constraint programming"),
    ("mathematics-optimization", "Semidefinite programming"),
    ("mathematics-optimization", "Second-order cone programming"),
    ("mathematics-optimization", "Comparison of optimization software"),
    ("mathematics-optimization", "MINOS (optimization software)"),
    ("mathematics-optimization", "HiGHS optimization solver"),
    ("mathematics-optimization", "List of optimization software"),
    ("mathematics-optimization", "GNU Linear Programming Kit"),
    ("mathematics-optimization", "Gekko (optimization software)"),
    ("mathematics-optimization", "Optimization problem"),
    ("mathematics-optimization", "Vertex (graph theory)"),

    # Scientific Research & Publishing (16)
    ("scientific-research-publishing", "Peer review"),
    ("scientific-research-publishing", "bioRxiv"),
    ("scientific-research-publishing", "arXiv"),
    ("scientific-research-publishing", "Open access"),
    ("scientific-research-publishing", "Open peer review"),
    ("scientific-research-publishing", "Directory of Open Access Journals"),
    ("scientific-research-publishing", "Registry of Open Access Repositories"),
    ("scientific-research-publishing", "Open Access Scholarly Publishing Association"),
    ("scientific-research-publishing", "Budapest Open Access Initiative"),
    ("scientific-research-publishing", "Berlin Declaration on Open Access to Knowledge in the Sciences and Humanities"),
    ("scientific-research-publishing", "History of open access"),
    ("scientific-research-publishing", "List of preprint repositories"),
    ("scientific-research-publishing", "Open data"),
    ("scientific-research-publishing", "Dover Publications"),
    ("scientific-research-publishing", "HarperCollins"),
    ("scientific-research-publishing", "The Independent"),

    # Technology & Society (16)
    ("technology-society", "Work ethic"),
    ("technology-society", "Work–life balance"),
    ("technology-society", "Whistleblowing"),
    ("technology-society", "Bullshit Jobs"),
    ("technology-society", "Post-work society"),
    ("technology-society", "Working poor"),
    ("technology-society", "Evil corporation"),
    ("technology-society", "Credentialism and degree inflation"),
    ("technology-society", "Great Recession"),
    ("technology-society", "Guaranteed minimum income"),
    ("technology-society", "Job guarantee"),
    ("technology-society", "Youth unemployment"),
    ("technology-society", "Structural unemployment"),
    ("technology-society", "Slow movement (culture)"),
    ("technology-society", "At-will employment"),
    ("technology-society", "Employee offboarding"),
]

# 3 Draft Documents
DRAFTS = [
    (
        "Frontiers in Neuromorphic Computing",
        "neuroscience-cognitive-science",
        ["neuromorphic", "hardware", "brain-inspired", "neuroscience"],
        "Working draft investigating event-driven spiking neural networks and analog neuromorphic architectures for sub-milliwatt cognitive inference. Evaluates synaptic plasticity models implemented on physical silicon substrates."
    ),
    (
        "Foundations of Quantum Algorithmic Complexity",
        "computer-science-systems",
        ["quantum", "algorithms", "complexity", "systems"],
        "Working draft establishing complexity boundaries for bounded-error quantum polynomial-time (BQP) algorithms against classic class separations. Reviews fault-tolerant circuit models and asymptotic query lower bounds."
    ),
    (
        "Decentralized Knowledge Graph Protocols",
        "technology-society",
        ["knowledge-graph", "protocols", "open-data", "governance"],
        "Working draft outlining decentralized semantic protocols and verifiable schema registries for open research repositories. Analyzes community governance incentives and persistent knowledge graphs."
    )
]

def clean_academic_summary(title: str, text: str) -> str:
    """
    Produces a clean, 2-3 sentence academic abstract devoid of crawler debris,
    disambiguation tags, bracketed citations, and infobox artifacts.
    """
    cleaned = text
    # Remove markdown tables
    cleaned = re.sub(r'\|[^\n|]+\|', ' ', cleaned)
    # Remove links [anchor](url) -> anchor
    cleaned = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', cleaned)
    # Remove citations [edit], [citation needed], [1], [note 2], [a]
    cleaned = re.sub(r'\[[^\]]*\]', '', cleaned)
    # Remove bold, italics, code markers
    cleaned = re.sub(r'[*_`]{1,3}', '', cleaned)
    cleaned = re.sub(r'---\s*', ' ', cleaned)
    # Normalize unicode spaces and hyphens
    cleaned = cleaned.replace('\u00a0', ' ').replace('\u200b', '')
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    # Find the title occurrence to skip infobox metadata
    # Strip parenthetical disambiguation from title for matching (e.g. "Transformer (deep learning)" -> "Transformer")
    base_title = title.split('(')[0].strip()
    idx = cleaned.find(base_title)
    if idx != -1 and idx < 500:
        lead = cleaned[idx:]
    else:
        lead = cleaned

    # Strip phrases like 'This article is about...', 'For other uses, see...', etc.
    lead = re.sub(r'\bThis article is about [^\.]+\.', '', lead, flags=re.IGNORECASE)
    lead = re.sub(r'\bFor other uses, see [^\.]+\.', '', lead, flags=re.IGNORECASE)
    lead = re.sub(r'\bFor the [^\.]+, see [^\.]+\.', '', lead, flags=re.IGNORECASE)
    lead = re.sub(r'\bNot to be confused with [^\.]+\.', '', lead, flags=re.IGNORECASE)
    lead = re.sub(r'\"[^\"]+\" redirects here\.', '', lead, flags=re.IGNORECASE)
    lead = re.sub(r'\s+', ' ', lead).strip()

    # Split into candidate sentences
    raw_sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z0-9])', lead)
    good_sentences = []
    total_len = 0
    for s in raw_sentences:
        s = s.strip()
        if not s or len(s) < 25:
            continue
        # Skip sentences with crawler debris
        if any(debris in s.lower() for debris in ['redirects here', 'see also', 'may refer to', 'isbn', 'doi:', 'coordinates:', 'jump to']):
            continue
        # Avoid sentences that are just lists of authors or institutions
        if s.count(',') > 8 and not any(v in s for v in ['is', 'are', 'was', 'were', 'provides', 'serves', 'describes']):
            continue
        good_sentences.append(s)
        total_len += len(s)
        if len(good_sentences) >= 2 and total_len >= 170:
            break
        if len(good_sentences) >= 3:
            break

    summary = ' '.join(good_sentences).strip()
    # Final sanitize: remove any lingering brackets, e.g. [citation needed]
    summary = re.sub(r'\[[^\]]*\]', '', summary)
    summary = re.sub(r'\s+', ' ', summary).strip()
    # Fallback if lead extraction was too short
    if len(summary) < 80:
        summary = f"{title} is a subject in research literature. This document examines its theoretical principles, formal methodologies, and systemic applications."

    return summary

def normalize_title(title: str) -> str:
    # Normalize unicode encoding issues, e.g. em dash
    if "Work" in title and "life" in title:
        return "Work–life balance"
    if "Brain" in title and "computer" in title:
        return "Brain–computer interface"
    return title.strip()

def run_curation():
    print("Loading raw crawler dataset and extra fetched articles...")
    articles_by_title = {}

    # 1. Load from EXTRA_DATA_PATH if present
    if EXTRA_DATA_PATH.exists():
        with open(EXTRA_DATA_PATH, "r", encoding="utf-8") as f:
            extras = json.load(f)
            for item in extras:
                t = normalize_title(item["title"])
                articles_by_title[t] = {
                    "title": t,
                    "url": item["url"],
                    "text": item["text"]
                }
        print(f"Loaded {len(extras)} articles from fetched_extra.json")

    # 2. Load from RAW_DATA_PATH
    with open(RAW_DATA_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            t = normalize_title(data.get("title", ""))
            if t and t not in articles_by_title:
                articles_by_title[t] = {
                    "title": t,
                    "url": data.get("url", ""),
                    "text": data.get("text", "")
                }

    print(f"Total source corpus size: {len(articles_by_title)} articles.")

    # Build the 100 published documents
    curated_records = []
    seen_ids = set()

    for idx, (cat_slug, req_title) in enumerate(TARGET_ARTICLES):
        norm_req = normalize_title(req_title)
        art = articles_by_title.get(norm_req)
        if not art:
            # Try fuzzy search in articles_by_title
            for k, v in articles_by_title.items():
                if norm_req.lower() == k.lower() or norm_req.lower() in k.lower():
                    art = v
                    break
        
        if not art:
            raise RuntimeError(f"Missing required article in raw corpus: {req_title}")

        url = art["url"]
        content = clean_wikipedia_content(art["text"], url)
        title = norm_req
        doc_id = str(uuid.uuid5(uuid.NAMESPACE_URL, url))

        summary = clean_academic_summary(title, content)
        cat_info = CATEGORY_DEFINITIONS[cat_slug]

        # Generate tags: combine category base tags with title slug
        slug_tag = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:25]
        tags = list(cat_info["base_tags"])
        if slug_tag and slug_tag not in tags:
            tags.append(slug_tag)

        # Realistic created_at demo dates spaced through 2026
        day_offset = (idx * 2) % 270 + 1
        month = (day_offset // 28) + 1
        day = (day_offset % 28) + 1
        created_at = f"2026-{month:02d}-{day:02d}T10:00:00Z"

        # Check demo covers
        cover_info = DEMO_COVERS.get(title)
        cover_url = cover_info["cover_image_url"] if cover_info else None
        cover_alt = cover_info["cover_image_alt"] if cover_info else f"Illustration for {title}"
        license_str = cover_info["source_license"] if cover_info else "CC BY-SA 4.0"
        attrib_str = cover_info["source_attribution"] if cover_info else "Wikipedia contributors, available under CC BY-SA 4.0"

        doc_entry = {
            "id": doc_id,
            "title": title,
            "summary": summary,
            "content": content,
            "category_name": cat_info["name"],
            "category_slug": cat_slug,
            "tags": tags[:4],
            "author": "Wikipedia contributors",
            "created_at": created_at,
            "published_at": created_at,
            "status": "published",
            "source_url": url,
            "source_license": license_str,
            "source_attribution": attrib_str,
            "cover_image_url": cover_url,
            "cover_image_alt": cover_alt,
            "seo_title": f"{title} — Folio Knowledge & Research Library",
            "seo_description": summary[:160],
            "seo_keywords": tags[:4] + [title.lower()]
        }
        curated_records.append(doc_entry)
        seen_ids.add(doc_id)

    assert len(curated_records) == 100, f"Expected 100 published records, got {len(curated_records)}"

    # Add 3 draft documents
    for d_title, d_slug, d_tags, d_summary in DRAFTS:
        d_url = f"https://folio.local/drafts/{d_slug}/{re.sub(r'[^a-z0-9]+', '-', d_title.lower())}"
        doc_id = str(uuid.uuid5(uuid.NAMESPACE_URL, d_url))
        d_content = f"# {d_title}\n\n*Working Draft — Folio Research Working Group — Not yet peer reviewed.*\n\n## Abstract\n{d_summary}\n\n## Introduction & Problem Statement\nThis document investigates key theoretical models, engineering challenges, and formal proofs in {d_title.lower()}.\n\n## Methodology & Architecture\nPreliminary evaluations demonstrate empirical stability across benchmarking workloads.\n\n## Conclusion & Open Problems\nFuture revisions will incorporate empirical measurements and peer referee feedback."
        cat_info = CATEGORY_DEFINITIONS[d_slug]

        doc_entry = {
            "id": doc_id,
            "title": d_title,
            "summary": d_summary,
            "content": d_content,
            "category_name": cat_info["name"],
            "category_slug": d_slug,
            "tags": d_tags,
            "author": "Folio Research Working Group",
            "created_at": "2026-10-30T15:00:00Z",
            "published_at": None,
            "status": "draft",
            "source_url": d_url,
            "source_license": "CC BY 4.0",
            "source_attribution": "Folio Working Draft, available under CC BY 4.0",
            "cover_image_url": None,
            "cover_image_alt": f"Draft diagram for {d_title}",
            "seo_title": f"{d_title} (Draft)",
            "seo_description": d_summary[:160],
            "seo_keywords": d_tags
        }
        curated_records.append(doc_entry)

    assert len(curated_records) == 103, f"Expected 103 records, got {len(curated_records)}"

    # Write curated records to fixtures/folio/documents.jsonl
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for doc in curated_records:
            f.write(json.dumps(doc, ensure_ascii=False) + "\n")

    print(f"Wrote {len(curated_records)} curated documents to {OUTPUT_FILE}.")

    # Category counts summary
    counts = {}
    pub_counts = {}
    covers_count = 0
    for d in curated_records:
        cat = d["category_slug"]
        counts[cat] = counts.get(cat, 0) + 1
        if d["status"] == "published":
            pub_counts[cat] = pub_counts.get(cat, 0) + 1
        if d.get("cover_image_url"):
            covers_count += 1

    print("\nCurated Category Distribution:")
    for cat, total in counts.items():
        print(f"  - {cat}: {total} (published: {pub_counts.get(cat, 0)})")
    print(f"\nTotal documents: {len(curated_records)} (100 published + 3 drafts)")
    print(f"Documents with cover illustrations: {covers_count}")

if __name__ == "__main__":
    run_curation()
