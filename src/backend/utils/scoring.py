import math
import re
from typing import List, Dict

#hyperparmeter
RRF_K = 60 #fixed
COSINE_THRESHOLD = 0.658 #goc cosine 70 -> gan nhu la xa ngu nghia
W_SPARSE_HIGH = 1.0
W_DENSE_HIGH = 1.0
W_SPARSE_LOW = 0.1
LAMBDA = 2.0932 

TITLE_BOOST_BETA = 0.35 #muc giam toi da cua weighted_score khi query trung khop hoan toan voi title
TITLE_STOP_WORDS = {'what', 'is', 'the', 'a', 'an', 'how', 'why', 'who', 'does', 'do', 'are', 'was', 'were', 'about', 'long', 'in', 'of', 'and', 'to', 'for'}
_TOKEN_RE = re.compile(r'[a-z0-9]+')

def title_boost_score(query: str, title: str, beta: float = TITLE_BOOST_BETA) -> float:
    query_words = {w for w in _TOKEN_RE.findall(query.lower()) if w not in TITLE_STOP_WORDS}
    title_words = {w for w in _TOKEN_RE.findall(title.lower()) if w not in TITLE_STOP_WORDS}
    if not query_words or not title_words:
        return 1.0
    coverage = len(query_words & title_words) / len(query_words)
    return round(1.0 - beta * coverage, 4)

def calc_weighted_score(distances: List[float]) -> dict:
    avg = sum(distances) / len(distances)
    best = min(distances)
    weighted = round(best * 0.6 + avg * 0.4, 6)
    return {
        "weighted_score": weighted,
        "avg_score": round(avg, 6),
        "best_score": round(best, 6),
        "chunk_count": len(distances),
    }

def _get_dense_weight(best_cosine: float) -> float:
    if best_cosine <= COSINE_THRESHOLD:
        return W_DENSE_HIGH
    return round(math.exp(-LAMBDA * best_cosine), 6)
def _get_sparse_weight(best_cosine: float, bm25_score: float = 0.0, max_bm25: float = 0.0) -> float:
    if best_cosine <= COSINE_THRESHOLD:
        return W_SPARSE_LOW
    if max_bm25 <= 0:
        return W_SPARSE_HIGH
    ratio = math.sqrt(max(bm25_score, 0.0) / max_bm25)
    return round(max(W_SPARSE_LOW, min(W_SPARSE_HIGH, ratio)), 6)

def asymmetric_weighted_rrf(vector_articles: List[dict], bm25_results: List[dict], top_k: int, full_text_index: dict) -> List[dict]:
    rrf_scores: Dict[str, float] = {}
    data: Dict[str, dict] = {}
    bm25_score_map = {r["url"]: r["bm25_score"] for r in bm25_results}
    max_bm25 = max((r["bm25_score"] for r in bm25_results), default=0.0)
 
    # xu ly vector
    for rank, art in enumerate(vector_articles, start=1):
        url = art["url"]
        best_cosine = art["score_info"]["best_score"]
        bm25_score_here = bm25_score_map.get(url, 0.0)
        w_dense = _get_dense_weight(best_cosine)
        w_sparse = _get_sparse_weight(best_cosine, bm25_score_here, max_bm25)
        dense_contrib = w_dense * (1.0 / (RRF_K + rank))
        bm25_rank = next((i + 1 for i, r in enumerate(bm25_results) if r["url"] == url), None)
        sparse_contrib = w_sparse * (1.0 / (RRF_K + bm25_rank)) if bm25_rank else 0.0
        rrf_scores[url] = dense_contrib + sparse_contrib
        data[url] = {
            **art,
            "cosine_best_score": best_cosine,
            "bm25_score": bm25_score_here
        }
    # xu ly bm25
    for rank, res in enumerate(bm25_results, start=1):
        url = res["url"]
        if url in data:
            continue
        fallback_cosine  = 1.0 
        w_dense = _get_dense_weight(fallback_cosine)
        w_sparse = _get_sparse_weight(fallback_cosine, res["bm25_score"], max_bm25)
        sparse_contrib  = w_sparse * (1.0 / (RRF_K + rank))
        rrf_scores[url] = sparse_contrib
        full = full_text_index.get(url, {})
        data[url] = {
            "url": url,
            "title": res["title"],
            "score_info": {"weighted_score": 999, "best_score": 999, "avg_score": 999, "chunk_count": 0},
            "chunk_texts": [],
            "full_text": full.get("text", res.get("text", "")),
            "text_source": "bm25_only",
            "cosine_best_score": fallback_cosine,
            "bm25_score": res["bm25_score"]
        }
    ranked_urls = sorted(rrf_scores, key=lambda u: rrf_scores[u], reverse=True)
    results = []
    for url in ranked_urls[:top_k]:
        item = data[url]
        item["final_rrf_score"] = round(rrf_scores[url], 8)
        results.append(item)
 
    return results