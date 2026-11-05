import json
import os
import re
import uuid
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backend.core.wiki_content import clean_wikipedia_content

RAW_DATA_PATH = "data/raw/wiki_crawler_dataset.jsonl"
OUTPUT_DIR = "fixtures/folio"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "documents.jsonl")
SOURCES_FILE = os.path.join(OUTPUT_DIR, "SOURCES.md")

TAXONOMY_RULES = [
    (
        "Artificial Intelligence & Machine Learning",
        "ai-machine-learning",
        [
            "deep learning", "neural network", "machine learning", "artificial intelligence",
            "gradient descent", "geoffrey hinton", "lstm", "transformer", "reinforcement learning",
            "computer vision", "natural language processing", "open letter on artificial intelligence",
            "workplace impact of artificial intelligence", "supervised learning", "backpropagation"
        ],
        ["machine-learning", "artificial-intelligence", "deep-learning"]
    ),
    (
        "Neuroscience & Cognitive Science",
        "neuroscience-cognitive-science",
        [
            "neuroscientist", "neuroscience", "peter dayan", "terry sejnowski", "nootropic",
            "cognitive", "brain", "neuron", "synapse", "cortex", "perception", "memory"
        ],
        ["neuroscience", "cognitive-science", "biology"]
    ),
    (
        "Computer Science & Systems",
        "computer-science-systems",
        [
            "ppad", "complexity", "algorithm", "operating system", "open-source software",
            "database", "compiler", "programming language", "software architecture",
            "cryptography", "distributed systems", "data structure", "concurrency"
        ],
        ["computer-science", "algorithms", "systems"]
    ),
    (
        "Mathematics & Optimization",
        "mathematics-optimization",
        [
            "probability distribution", "optimization", "kriging", "statistics", "calculus",
            "linear algebra", "stochastic", "graph theory", "game theory", "monte carlo"
        ],
        ["mathematics", "optimization", "statistics"]
    ),
    (
        "Scientific Research & Publishing",
        "scientific-research-publishing",
        [
            "biorxiv", "journal", "publishing", "peer review", "open access", "harpercollins",
            "dover publications", "citation", "academic", "preprint", "siam"
        ],
        ["research", "publishing", "academic"]
    ),
    (
        "Technology & Society",
        "technology-society",
        [
            "open-source", "evil corporation", "post-work", "bullshit jobs", "working poor",
            "automation", "whistleblowing", "digital culture", "intellectual property",
            "ethics", "labor", "sociology"
        ],
        ["technology", "society", "ethics"]
    )
]

def clean_summary(text: str) -> str:
    # Remove markdown headers and clean up first paragraph
    lines = text.split("\n")
    cleaned_paragraphs = []
    for l in lines:
        l = l.strip()
        if not l or l.startswith("#") or l.startswith("==") or l.startswith("*") or l.startswith("|") or l.startswith("```"):
            continue
        # Remove markdown links [anchor](url) -> anchor
        l = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', l)
        # Remove bold/italic markers
        l = re.sub(r'[*_]{1,3}', '', l)
        # Remove reference citations like [1], [2]
        l = re.sub(r'\[\d+\]', '', l)
        cleaned_paragraphs.append(l)
        if len(" ".join(cleaned_paragraphs)) >= 250:
            break
    
    summary = " ".join(cleaned_paragraphs).strip()
    if len(summary) > 600:
        # truncate cleanly to sentence boundary
        cut = summary[:600]
        last_dot = cut.rfind(".")
        if last_dot > 200:
            summary = cut[:last_dot + 1]
        else:
            summary = cut.rsplit(" ", 1)[0] + "..."
    return summary

def assign_taxonomy(title: str, text: str):
    combined = (title + " " + text[:1500]).lower()
    for cat_name, cat_slug, keywords, base_tags in TAXONOMY_RULES:
        for kw in keywords:
            if kw in title.lower():
                # Specific tag derivation
                tags = list(base_tags)
                clean_title_tag = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:30]
                if clean_title_tag and clean_title_tag not in tags:
                    tags.append(clean_title_tag)
                return cat_name, cat_slug, tags[:4]
    
    for cat_name, cat_slug, keywords, base_tags in TAXONOMY_RULES:
        for kw in keywords:
            if kw in combined:
                tags = list(base_tags)
                clean_title_tag = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:30]
                if clean_title_tag and clean_title_tag not in tags:
                    tags.append(clean_title_tag)
                return cat_name, cat_slug, tags[:4]
                
    return "Technology & Society", "technology-society", ["technology", "research", "reference"]

def build():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    seen_titles = set()
    seen_urls = set()
    documents = []

    with open(RAW_DATA_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            title = data.get("title", "").strip()
            text = data.get("text", "").strip()
            url = data.get("url", "").strip()
            text = clean_wikipedia_content(text, url)

            if not title or not text or not url:
                continue
            if title in seen_titles or url in seen_urls:
                continue
            if len(text) < 1500 or title.startswith("List of ") or "disambiguation" in title.lower():
                continue

            summary = clean_summary(text)
            if len(summary) < 80:
                continue

            cat_name, cat_slug, tags = assign_taxonomy(title, text)
            # deterministic UUID v5 from url
            doc_id = str(uuid.uuid5(uuid.NAMESPACE_URL, url))

            # Realistic created_at between 2026-01-01 and 2026-10-25
            day_offset = (len(documents) * 3) % 280
            created_at = f"2026-{(day_offset // 30) + 1:02d}-{(day_offset % 28) + 1:02d}T10:00:00Z"

            doc_entry = {
                "id": doc_id,
                "title": title,
                "summary": summary,
                "content": text,
                "category_name": cat_name,
                "category_slug": cat_slug,
                "tags": tags,
                "author": "Wikipedia contributors",
                "created_at": created_at,
                "published_at": created_at,
                "status": "published",
                "source_url": url,
                "source_license": "CC BY-SA 4.0",
                "source_attribution": "Wikipedia, The Free Encyclopedia",
                "cover_image_url": None,
                "cover_image_alt": f"Illustration for {title}",
                "seo_title": f"{title} — Folio Knowledge & Research Library",
                "seo_description": summary[:160],
                "seo_keywords": tags + [title.lower()]
            }

            seen_titles.add(title)
            seen_urls.add(url)
            documents.append(doc_entry)

            if len(documents) == 100:
                break

    # Add 3 draft documents clearly marked as draft for demo and testing
    draft_templates = [
        ("Frontiers in Neuromorphic Computing", "Neuroscience & Cognitive Science", "neuroscience-cognitive-science", ["neuromorphic", "hardware", "brain-inspired"]),
        ("Foundations of Quantum Algorithmic Complexity", "Computer Science & Systems", "computer-science-systems", ["quantum", "algorithms", "complexity"]),
        ("Decentralized Knowledge Graph Protocols", "Technology & Society", "technology-society", ["knowledge-graph", "protocols", "open-data"])
    ]
    for d_title, d_cat, d_slug, d_tags in draft_templates:
        d_url = f"https://folio.local/drafts/{d_slug}/{re.sub(r'[^a-z0-9]+', '-', d_title.lower())}"
        doc_id = str(uuid.uuid5(uuid.NAMESPACE_URL, d_url))
        d_summary = f"Draft research paper exploring {d_title.lower()} and its implications for modern computing."
        d_content = f"# {d_title}\n\n*Working Draft — Not yet peer reviewed.*\n\n## Abstract\n{d_summary}\n\n## Introduction\nThis document outlines preliminary findings and methodologies in {d_title.lower()}."
        doc_entry = {
            "id": doc_id,
            "title": d_title,
            "summary": d_summary,
            "content": d_content,
            "category_name": d_cat,
            "category_slug": d_slug,
            "tags": d_tags,
            "author": "Folio Research Working Group",
            "created_at": "2026-10-30T15:00:00Z",
            "published_at": None,
            "status": "draft",
            "source_url": d_url,
            "source_license": "CC BY 4.0",
            "source_attribution": "Folio Working Draft",
            "cover_image_url": None,
            "cover_image_alt": f"Draft diagram for {d_title}",
            "seo_title": f"{d_title} (Draft)",
            "seo_description": d_summary,
            "seo_keywords": d_tags
        }
        documents.append(doc_entry)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
        for doc in documents:
            out.write(json.dumps(doc, ensure_ascii=False) + "\n")

    published_count = sum(1 for d in documents if d["status"] == "published")
    draft_count = sum(1 for d in documents if d["status"] == "draft")
    print(f"Successfully generated {OUTPUT_FILE} with {published_count} published documents and {draft_count} draft documents.")

if __name__ == "__main__":
    build()
