import time
import chromadb
from collections import defaultdict
from chromadb.utils import embedding_functions
from src.backend.config import VDB_PATH, EMBEDDING_MODEL_NAME, COLLECTION_NAME, JSON_PATH
from src.backend.utils.query_extraction import QueryExtraction
from src.backend.utils.bm25_kw_search import BM25Search
from src.backend.utils.scoring import calc_weighted_score, title_boost_score, asymmetric_weighted_rrf
from src.backend.utils.data_loader import load_articles

# initialize Hyperparameter
VECTOR_FETCH_N = 300
BM25_FETCH_N = 100

class SearchService:
    def __init__(self):
        self.client = chromadb.PersistentClient(path=VDB_PATH)
        self.ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL_NAME)
        self.collection = self.client.get_collection(name=COLLECTION_NAME,embedding_function=self.ef)
        self.extraction = QueryExtraction()
        self.bm25 = BM25Search(json_path=JSON_PATH)
        self._full_text_index = self._build_full_text_index()

    def _build_full_text_index(self) -> dict:
        index = {}
        try:
            data = load_articles(JSON_PATH)
            for article in data:
                url = article.get("url", "").strip()
                if url:
                    index[url] = {
                        "title": article.get("title", "Unknown title"),
                        "url": url,
                        "text": article.get("text", ""),
                    }
        except Exception as e:
            print(f"[SearchService] Warning: Can not load full-text index: {e}")
        return index

    @staticmethod
    def _merge_bm25_results(list_a: list, list_b: list, top_k: int) -> list:
        #Gop 2 danh sach ket qua tu BM25: 1 la list keyword, 2 la raw query
        #Viec gop 2 ds ket qua la can raw query quet sach lai nhung gi keyword bo lo
        merged: dict = {}
        for item in list_a + list_b:
            url = item.get("url", "")
            if not url:
                continue
            if url not in merged or item["bm25_score"] > merged[url]["bm25_score"]:
                merged[url] = item
        ranked = sorted(merged.values(), key=lambda x: x["bm25_score"], reverse=True)
        return ranked[:top_k]

    def search(self, query: str, top_k: int = 5) -> dict:
        start_time = time.time()

        extracted = self.extraction.extract(query)
        search_kw = extracted.get("search_keywords", query)

        collection_size = self.collection.count()
        fetch_n = min(VECTOR_FETCH_N, collection_size)
        res = self.collection.query(query_texts=[query],n_results=fetch_n)
 
        grouped: dict[str, dict] = defaultdict(lambda: {"distances": [], "chunk_texts": [], "title": "", "url": ""})
        if res["documents"] and len(res["documents"][0]) > 0:
            docs = res["documents"][0]
            metas = res["metadatas"][0]
            distances = res["distances"][0]
            for doc_text, meta, dist in zip(docs, metas, distances):
                url   = meta.get("url", "")
                title = meta.get("title", "Unknown")
                if not url:
                    continue
                grouped[url]["url"] = url
                grouped[url]["title"] =title
                grouped[url]["distances"].append(dist)
                grouped[url]["chunk_texts"].append(doc_text)
                
        scored_articles = []
        for url, group in grouped.items():
            score_info = calc_weighted_score(group["distances"])
            boost = title_boost_score(query, group["title"])
            score_info["weighted_score"] = round(score_info["weighted_score"] * boost, 4)
            score_info["title_boost"] = boost
            scored_articles.append({
                "url": url,
                "title":group["title"],
                "score_info": score_info,
                "chunk_texts": group["chunk_texts"],
            })  
        scored_articles.sort(key=lambda x: x["score_info"]["weighted_score"])

        for cosine_rank, art in enumerate(scored_articles, start=1):
            art["cosine_rank"] = cosine_rank

        bm25_kw_results = self.bm25.search(search_kw, top_k=BM25_FETCH_N)
        bm25_raw_results = self.bm25.search(query, top_k=BM25_FETCH_N) if query.strip().lower() != search_kw.strip().lower() else []
        bm25_results = self._merge_bm25_results(bm25_kw_results, bm25_raw_results, top_k=BM25_FETCH_N)
        for bm25_rank, item in enumerate(bm25_results, start=1):
            item["bm25_rank"] = bm25_rank

        top_articles = asymmetric_weighted_rrf(scored_articles, bm25_results, top_k, self._full_text_index)
        bm25_rank_map = {r["url"]:r["bm25_rank"] for r in bm25_results}

        formatted_res = []
        for rank, article in enumerate(top_articles, start=1):
            url = article["url"]
            si = article["score_info"]
            full_data = self._full_text_index.get(url)
            
            if full_data and full_data.get("text"):
                full_text = full_data["text"]
                title= full_data["title"]
                text_source = "full_article"
            elif article.get("full_text"):
                full_text = article["full_text"]
                title = article["title"]
                text_source = "bm25_only"
            else:
                full_text ="\n\n---\n\n".join(article["chunk_texts"])
                title=article["title"]
                text_source ="merged_chunks"
        
            cosine_score = article.get("cosine_best_score")
            if cosine_score is None or cosine_score >= 999:
                cosine_score = None
            bm25_score = article.get("bm25_score", 0.0)
            final_rrf = article.get("final_rrf_score", 0.0)
            cosine_rank=article.get("cosine_rank")
            bm25_rank = bm25_rank_map.get(url)
            
            formatted_res.append({
                "rank": rank,
                "title": title,
                "url": url,
                "content": full_text,
                "text_source": text_source,
                "final_rrf_score": final_rrf,
                "cosine_score": round(cosine_score, 4) if cosine_score is not None else None,
                "cosine_rank":   cosine_rank,
                "bm25_score": round(bm25_score, 4) if bm25_score is not None else None,
                "bm25_rank": bm25_rank,
                "matched_chunks": si["chunk_count"],
            })
        end_time = time.time()
        processing_time_ms = round((end_time - start_time) * 1000, 2)

        return {
            "query": query,
            "extracted_context": extracted.get("context", ""),
            "optimized_search_keyword": search_kw,
            "processing_time_ms": processing_time_ms,
            "total_results": len(formatted_res),
            "vector_pool_size": len(scored_articles),
            "bm25_pool_size": len(bm25_results),
            "data": formatted_res,
        }