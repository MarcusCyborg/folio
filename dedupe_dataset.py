import json
import os
import shutil
import hashlib

PATH = os.path.join("data", "raw", "wiki_crawler_dataset.jsonl")


def main():
    if not os.path.exists(PATH):
        print(f"[LOI] Khong tim thay {PATH}")
        return

    by_url = {}
    total = 0
    bad = 0
    with open(PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                article = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            url = (article.get("url") or "").strip()
            if url:
                by_url[url] = article  # ban sau ghi de ban truoc

    # Buoc 2: gom theo hash noi dung
    by_content = {}
    empties = []
    collapsed = 0
    for article in by_url.values():
        text = (article.get("text") or "").strip()
        if not text:
            empties.append(article)          # giu bai rong (neu co)
            continue
        key = hashlib.md5(text.encode("utf-8")).hexdigest()
        if key in by_content:
            collapsed += 1                    # trung noi dung -> bo
        else:
            by_content[key] = article

    final_articles = list(by_content.values()) + empties

    # Backup truoc khi ghi de
    backup = PATH + ".bak"
    shutil.copy2(PATH, backup)

    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for article in final_articles:
            f.write(json.dumps(article, ensure_ascii=False) + "\n")
    os.replace(tmp, PATH)

    print(f"Tong dong doc duoc : {total}")
    print(f"Dong JSON hong : {bad}")
    print(f"Sau dedup theo URL : {len(by_url)}")
    print(f"Trung theo noi dung : {collapsed}")
    print(f"Con lai : {len(final_articles)}")
    print(f"Backup file cu : {backup}")


if __name__ == "__main__":
    main()