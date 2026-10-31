import json
import os


def load_articles(path: str) -> list:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Không tìm thấy dataset: {path}")

    if path.endswith(".jsonl"):
        by_url = {}
        no_url = []
        bad_lines = 0
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    article = json.loads(line)
                except json.JSONDecodeError:
                    bad_lines += 1
                    continue
                url = (article.get("url") or "").strip()
                if url:
                    by_url[url] = article
                else:
                    no_url.append(article)
        if bad_lines:
            print(f"[data_loader] Cảnh báo: bỏ qua {bad_lines} dòng JSON hỏng trong {path}")
        return list(by_url.values()) + no_url

    # định dạng lại .json truyền thống
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
