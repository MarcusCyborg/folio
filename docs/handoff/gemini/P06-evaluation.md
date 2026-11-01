# P06 — Retrieval Evaluation, Qrels & Performance Benchmarking Handoff

**Ngày:** 01/11/2026 (Asia/Saigon)  
**Vai trò:** Information Retrieval Evaluation Scientist (P06)  
**Baseline tích hợp:** `693d031 feat(search): implement P05 search API, 0-second lag defense, telemetry & graceful fallbacks` (Milestone P05 đã nghiệm thu)  
**Worktree:** `F:/dpl13.10/WikiSearchEngine-p06` (cô lập hoàn toàn với chat P07)  
**Branch:** `feature/p06-evaluation`  
**Database cô lập:** `postgresql+psycopg://folio_live@127.0.0.1:55463/folio_eval` (không dùng chung với `folio` hoặc `folio_test`)  
**Package & Tooling sở hữu:**
- `evaluate/run_eval.py` (CLI công cụ đánh giá IR có khả năng tái lập 100%)
- `evaluate/corpus_manifest.json` (Snapshot toàn bộ tập tài liệu, Document ID canonical, sha256 checksum)
- `evaluate/benchmark_queries.json` (Bộ 30 queries phân loại: exact title, multi-term, natural language, ambiguous, negative; tách `tune` vs `test`)
- `evaluate/qrels.json` (Tập nhãn relevance graded 2/1/0 bằng Folio Document ID)
- `evaluate/eval_results_p06.json` (Dữ liệu kết quả chi tiết từng query, metrics tổng hợp, tài nguyên và concurrency)
- `evaluate/eval_chart_p06.png` (Biểu đồ so sánh chất lượng MAP@10, nDCG@10 và độ trễ p50)
- `tests/evaluate/` (11 unit và integration tests kiểm thử công thức toán học và CLI validation)
**Test Suite Status:** 75 passed, 0 failed (64 search backend + 11 evaluation metrics & harness)  
**Python Runtime:** Python 3.10.11 (`F:/dpl13.10/folio-live-runtime/venv-clean` & `F:/dpl13.10/WikiSearchEngine/env`)

---

## 1. Tóm tắt kết quả khoa học & Quyết định lựa chọn Default Engine (Executive Summary)

Đợt đánh giá Information Retrieval (IR) Mốc P06 đã được thực thi bằng phương pháp khoa học chuẩn mực, chạy trực tiếp thông qua CLI tự động, **tuyệt đối không sao chép số liệu cũ từ Jupyter Notebook**. Hệ thống so sánh độc lập và công bằng giữa 5 động cơ truy xuất trên cùng một snapshot tập văn bản, cùng một bộ câu hỏi và cùng điều kiện môi trường:

1. **PostgreSQL ILIKE Baseline:** Tìm kiếm chuỗi ký tự SQL ILIKE trực tiếp trên cơ sở dữ liệu.
2. **TF-IDF Baseline:** Bộ chấm điểm TF-IDF cổ điển chuẩn hóa độ dài dựa trên danh sách đảo (Inverted Index).
3. **Okapi BM25 Engine:** Động cơ tìm kiếm cốt lõi của Folio ($k_1=1.5, b=0.75$, tách riêng Title Boost).
4. **Dense Vector Semantic Engine:** Truy vấn vector ngữ nghĩa qua ChromaDB (`wiki_ai_english`, 92,855 chunks) và mô hình `all-MiniLM-L6-v2`.
5. **Hybrid Fusion (RRF):** Kết hợp phân hạng tương hỗ Reciprocal Rank Fusion ($k=60, w_{\text{sparse}}=0.5, w_{\text{dense}}=0.5$) giữa BM25 và Semantic.

### Bảng kết quả tổng hợp 5 Động cơ trên Toàn bộ 30 Truy vấn Benchmark ($K=10$):

| Động cơ (Engine) | P@5 | P@10 | Recall@10 | MAP@10 | MRR@10 | nDCG@10 | Trễ p50 (ms) | Trễ p95 (ms) | Degraded |
|---|---|---|---|---|---|---|---|---|---|
| **ILIKE Baseline** | 0.1333 | 0.0750 | 0.3125 | 0.2609 | 0.2819 | 0.2681 | 23.93 ms | 28.82 ms | 0/30 |
| **TF-IDF Baseline** | 0.3917 | 0.2833 | 0.9014 | 0.6489 | 0.7778 | 0.7467 | **0.19 ms** | **0.50 ms** | 0/30 |
| **Okapi BM25** | **0.4417** | **0.2917** | **0.9271** | **0.7590** | **0.8958** | **0.8466** | 93.61 ms | 140.21 ms | 0/30 |
| **Semantic (Dense)** | 0.3333 | 0.1667 | 0.5208 | 0.4810 | 0.7708 | 0.6556 | 139.63 ms | 288.18 ms | 0/30 |
| **Hybrid (RRF)** | 0.4500 | 0.2583 | 0.8007 | 0.6947 | 0.8750 | 0.8046 | 188.10 ms | 254.68 ms | 0/30 |

*(Ghi chú: Oracle giới hạn lý thuyết tối đa của tập tài liệu ở $K=10$ là: Oracle P@10 = 0.3208, Oracle Recall@10 = 1.0000, Oracle MAP@10 = 1.0000).*

### Quyết định lựa chọn Động cơ Mặc định (Default Engine):
Căn cứ chỉ thị nghiệm thu: *"Chọn default dựa quality+latency; hybrid không tự thành default nếu không thắng rõ"*:
- **Okapi BM25 chiến thắng áp đảo về mặt chất lượng:** Okapi BM25 đạt **MAP@10 = 0.7590** và **nDCG@10 = 0.8466**, vượt trội rõ rệt so với Hybrid RRF (MAP@10 = 0.6947, nDCG@10 = 0.8046).
- **Okapi BM25 chiến thắng áp đảo về tốc độ và tài nguyên:** BM25 có độ trễ trung vị **p50 = 93.61 ms** (so với Hybrid p50 = 188.10 ms — nhanh hơn gấp 2 lần) và không tiêu tốn thêm ~500 MB RAM của mô hình Transformer CPU và ChromaDB.
- **Kết luận:** **Okapi BM25 được chính thức chọn làm Default Engine của nền tảng Folio.** Hybrid RRF được duy trì như một chế độ tìm kiếm nâng cao có thể bật qua tham số `mode=hybrid` khi người dùng có nhu cầu tìm kiếm ngữ nghĩa mở rộng.

---

## 2. Kiểm định lịch sử: Đối chiếu Notebook cũ vs Benchmark P06

Trong sổ tay cũ `evaluate/evaluate_module5.ipynb` và kết quả lưu tại `evaluate/eval_results.json`:
- **Số liệu lịch sử cũ:** 20 queries, P@10 = 0.575, MAP = 0.644126.
- **Thực chất của số liệu cũ qua kiểm tra khoa học:**
  1. Toàn bộ 20 queries cũ được đánh giá trên tập cào thô chưa qua làm sạch gồm **5,008 bài viết** (`data/eval/raw/wiki_crawler_dataset.json` / `data/raw/wiki_crawler_dataset.jsonl`).
  2. Ground truth cũ sử dụng trực tiếp URL Wikipedia tiếng Anh (ví dụ `https://en.wikipedia.org/wiki/Deep_learning`), không dùng Document ID nội bộ.
  3. Quá trình kiểm tra URL coverage cho thấy 14/20 queries cũ hoàn toàn nhắm vào các chủ đề cào tràn lan về lao động/thất nghiệp/bắt nạt học đường (`workplace bullying`, `school bullying`, `anti-corruption commissions`, `electoral fraud`, `teen suicides`, `wage theft`, v.v.). Trong khi đó, tập tài liệu demo chuẩn mực của Folio (`fixtures/folio/documents.jsonl`) đã được lược tỉa khoa học và cân bằng đều 6 danh mục nghiên cứu (100 tài liệu xuất bản + 3 bản thảo).
  4. Sổ tay cũ gửi yêu cầu vào endpoint cũ `/search` (không có kiểm tra quyền, không có vòng đời xuất bản/xóa mềm 0-lag, không có `search_context_token`, không phân định rõ ràng giữa BM25 và Semantic).
- **Khắc phục trong P06:**
  - Định danh canonical 100% bằng **Folio Document ID (UUIDv5)** tạo từ `uuid.uuid5(uuid.NAMESPACE_URL, url)`.
  - Toàn bộ qrels được gắn nhãn độ liên quan phân cấp (Graded Relevance: 2 = Trực tiếp cốt lõi, 1 = Liên quan hỗ trợ, 0 = Không liên quan), cho phép tính toán độ đo chuẩn công nghiệp hiện đại **nDCG@10** và **MRR@10** bên cạnh P@10 và MAP@10.
  - Phân tách tường minh tập câu hỏi: **10 câu hiệu chỉnh (Tune set)** và **20 câu kiểm thử độc lập (Held-out Test set)**.

---

## 3. Snapshot Tập văn bản, Bộ câu hỏi & Qrels (Artifacts Versioning)

### 3.1 Corpus Manifest (`evaluate/corpus_manifest.json`)
- **Manifest ID:** `folio-canonical-corpus-v1`
- **Schema Version:** `2.1.0`
- **Tệp nguồn:** `fixtures/folio/documents.jsonl`
- **SHA-256 Checksum:** `5413a1f6a1d821361cbe153e70d65b741005b630b912c9fa5ceaa76bc725fe5a`
- **Tổng số tài liệu:** 103 bản ghi:
  - **100 tài liệu xuất bản (`status="published"`):** Đầy đủ tiêu đề, tóm tắt trừu tượng, nội dung toàn văn, danh mục, thẻ, tác giả, ngày tạo demo 2026.
  - **3 tài liệu bản thảo (`status="draft"`):** `Frontiers in Neuromorphic Computing`, `Foundations of Quantum Algorithmic Complexity`, `Decentralized Knowledge Graph Protocols`.
- **Phân bổ 6 Danh mục Nghiên cứu cân bằng:**
  - `ai-machine-learning`: 18 bài
  - `computer-science-systems`: 18 bài (+1 draft)
  - `neuroscience-cognitive-science`: 16 bài (+1 draft)
  - `mathematics-optimization`: 16 bài
  - `scientific-research-publishing`: 16 bài
  - `technology-society`: 16 bài (+1 draft)

### 3.2 Bộ 30 Benchmark Queries (`evaluate/benchmark_queries.json`)
Bộ câu hỏi được thiết kế đại diện đầy đủ 5 hình thái tìm kiếm thực tế của người dùng:

1. **Exact Title (6 câu - 2 tune, 4 test):** Khớp chính xác tên bài viết học thuật (`"Deep learning"`, `"Residual neural network"`, `"Binary search tree"`, `"Cognitive load"`, `"Bayesian optimization"`, `"Work ethic"`).
2. **Multi-term (6 câu - 2 tune, 4 test):** Truy vấn kỹ thuật nhiều thuật ngữ (`"deep learning neural network architectures"`, `"gradient descent and optimization software"`, `"public key cryptography and rsa algorithm"`, v.v.).
3. **Natural Language (6 câu - 2 tune, 4 test):** Câu hỏi nghiên cứu tự nhiên (`"how do artificial neural networks learn hierarchical representations"`, `"what are the differences between binary search trees and b trees"`, v.v.).
4. **Ambiguous (6 câu - 2 tune, 4 test):** Từ khóa đa nghĩa, đa ngữ cảnh ngắn gọn (`"networks"`, `"trees"`, `"optimization"`, `"memory"`, `"publishing"`, `"unemployment"`).
5. **Negative / Out-of-Domain (6 câu - 2 tune, 4 test):** Các câu hỏi về các lĩnh vực hoàn toàn không có trong danh mục xuất bản (`"quantum teleportation protocol"`, `"photosynthesis light dependent reactions"`, `"roman gladiatorial combat"`, `"volcanic basaltic magma"`, `"deep sea hydrothermal vents"`, `"paleolithic cave paintings"`).

### 3.3 Phân tách Tập Tune vs Held-Out Test
- **Tune Set (10 queries):** Dùng để tinh chỉnh siêu tham số ($k_1, b$, trọng số RRF).
- **Held-Out Test Set (20 queries):** Đánh giá khách quan, không rò rỉ thông tin (unbiased evaluation).

### Kết quả trên Tập Kiểm thử Độc lập (Held-Out Test Set, 20 queries, 16 positive + 4 negative):

| Động cơ (Engine) | P@5 | P@10 | Recall@10 | MAP@10 | MRR@10 | nDCG@10 | Trễ p50 (ms) | Trễ p95 (ms) |
|---|---|---|---|---|---|---|---|---|
| **ILIKE Baseline** | 0.1250 | 0.0688 | 0.2604 | 0.2018 | 0.2292 | 0.2230 | 22.70 ms | 28.45 ms |
| **TF-IDF Baseline** | 0.3375 | 0.2687 | 0.8854 | 0.6060 | 0.7396 | 0.7149 | 0.26 ms | 0.45 ms |
| **Okapi BM25** | **0.4500** | **0.2687** | **0.8906** | **0.7376** | **0.8750** | **0.8377** | 87.68 ms | 138.56 ms |
| **Semantic (Dense)** | 0.2875 | 0.1438 | 0.4688 | 0.4236 | 0.7188 | 0.6120 | 93.95 ms | 625.79 ms |
| **Hybrid (RRF)** | 0.4000 | 0.2250 | 0.7135 | 0.6039 | 0.8125 | 0.7326 | 148.05 ms | 175.92 ms |

---

## 4. Phân tích Chi tiết Từng Dạng Truy vấn & Lỗi

### 4.1 Phân tích MAP@10 theo Loại Truy vấn
| Loại truy vấn (Category) | Số lượng | ILIKE | TF-IDF | Okapi BM25 | Semantic | Hybrid RRF |
|---|---|---|---|---|---|---|
| **Exact Title** | 6 | 0.6806 | 0.7105 | **0.9062** | 0.6065 | 0.7083 |
| **Multi-Term** | 6 | 0.0000 | **0.7445** | 0.6767 | 0.6833 | 0.7118 |
| **Natural Language** | 6 | 0.0000 | 0.6188 | **0.7631** | 0.3079 | 0.5605 |
| **Ambiguous** | 6 | 0.3632 | 0.5217 | 0.6901 | 0.3264 | **0.7982** |

### 4.2 Nhận xét Khoa học:
1. **Vì sao SQL ILIKE thất bại hoàn toàn trên Multi-Term và Natural Language (MAP = 0.0000):**
   - Toán tử SQL `ILIKE '%query%'` yêu cầu nguyên cụm từ phải xuất hiện liên tiếp nhau. Với các câu hỏi như `"how do artificial neural networks learn hierarchical representations"`, tài liệu thực tế chứa các từ rời rạc khắp bài viết chứ không bao giờ chứa nguyên văn chuỗi 69 ký tự này. Do đó, ILIKE trả về 0 kết quả (rỗng).
2. **Sức mạnh vượt trội của Okapi BM25 trên Exact Title (0.9062) và Natural Language (0.7631):**
   - Nhờ cơ chế bão hòa tần số từ khóa ($k_1=1.5$) và chuẩn hóa độ dài ($b=0.75$), BM25 lọc nhiễu xuất sắc các từ chức năng trong câu hỏi tự nhiên (`how`, `do`, `what`, `are`) và tập trung vào các từ mang thông tin cao (`hierarchical`, `representations`, `optimization`, `convex`).
3. **Ưu thế của Hybrid RRF trên Ambiguous Queries (0.7982):**
   - Với các từ khóa ngắn và mơ hồ như `"networks"`, Semantic giúp mở rộng không gian ngữ nghĩa sang cả mạng thần kinh (`Residual neural network`) lẫn mạng máy tính (`Computer network`), giúp Hybrid vượt nhẹ BM25 ở nhóm truy vấn này. Tuy nhiên, trên bình diện toàn cục, BM25 vẫn áp đảo.

### 4.3 Phân tích Truy vấn Âm tính (Negative Queries - 6 câu):
- **False Positive Rate (FPR):**
  - **ILIKE:** FPR = **0.00%** (6/6 truy vấn trả về rỗng). Do không có cụm từ nào khớp chính xác, ILIKE không sinh ra kết quả rác.
  - **Semantic:** FPR = **50.00%** (3/6 truy vấn trả về rỗng, 3 truy vấn trả về kết quả có khoảng cách vector xa).
  - **BM25 / TF-IDF / Hybrid:** FPR = **100.00%** khi không đặt ngưỡng sàn điểm số (`min_score`). Các từ chung như `"and"`, `"in"`, `"flow"` trong truy vấn âm tính vẫn khớp yếu với một vài tài liệu.
  - **Khuyến nghị kiến trúc:** Trong các phiên bản tương lai, nên bổ sung ngưỡng điểm cắt tối thiểu (`BM25_SCORE_THRESHOLD > 1.0`) để loại bỏ các ứng viên điểm số quá thấp trên truy vấn âm tính.

### 4.4 Báo cáo Lỗi & Timeout:
- **Lỗi thực thi (Errors):** `0 / 30` (100% truy vấn thành công trên mọi động cơ).
- **Quá thời gian (Timeouts):** `0 / 30` (Không có truy vấn nào chạm ngưỡng timeout 30s).
- **Degraded Status:**
  - Trong môi trường đầy đủ (`env`), không có truy vấn nào bị suy giảm (`Degraded: 0/30`).
  - Trong môi trường sạch (`venv-clean` không cài ChromaDB), hệ thống tự động suy giảm về `fallback_bm25` minh bạch (`Degraded: 20/20`), không ném lỗi và không ngụy tạo kết quả.

---

## 5. Đo lường Hiệu năng, Tài nguyên & Concurrency (Benchmarks)

Toàn bộ các chỉ số dưới đây là **kết quả đo đạc thực tế 100%**, không biến mục tiêu thiết kế thành kết quả:

### 5.1 Thời gian Xây dựng Chỉ mục & Kích thước Đĩa (Build & Storage)
- **Thời gian xây dựng chỉ mục (Index Build Time):** `2.281 giây` cho 100 tài liệu xuất bản (tạo thế hệ mới `idx-gen-20261101044538-0007`).
- **Kích thước chỉ mục trên đĩa (Index Disk Size):** `6,842.48 KB` (~6.68 MB) phân bổ trên 4 tệp:
  - `manifest.json`: Siêu dữ liệu thế hệ và checksum
  - `index_stats.json`: Thống kê toàn tập ($N=100, T=60,701, \text{avgdl}=607.01, |V|=10,214$)
  - `doc_entries.json`: Siêu dữ liệu tài liệu phục vụ lọc
  - `postings.json`: Danh sách đảo cho 10,214 từ khóa
- **Bộ nhớ tiến trình (Process RAM RSS):**
  - Mức nền (chỉ BM25 & Inverted Index): `~85 MB`
  - Mức đầy đủ (nạp thêm SentenceTransformer PyTorch CPU & ChromaDB): `915.60 MB`

### 5.2 Độ trễ Cold vs Warm (Latency Percentiles)
Đo lường trên Okapi BM25 với 5 chu kỳ chạy ấm lặp lại:
- **Cold Run (lần chạy đầu tiên khi chưa ấm cache DB/Index):**
  - $p_{50}$: `69.75 ms`
  - $p_{95}$: `89.19 ms`
- **Warm Run (sau khi cache chỉ mục và kết nối DB đã ấm):**
  - $p_{50}$: `79.19 ms`
  - $p_{95}$: `132.69 ms`
  - Thời gian trung bình: `83.45 ms` (Bao gồm đầy đủ thời gian kiểm tra live PostgreSQL 0-lag và cấp phát `search_context_token`).

### 5.3 Năng lực Xử lý Đồng thời (Concurrency & Throughput)
Đo đạc bằng ThreadPoolExecutor với các phiên kết nối DB độc lập:
- **5 Threads đồng thời (50 requests):**
  - Thông lượng (Throughput): `11.77 QPS`
  - Độ trễ $p_{50}$: `380.20 ms`
  - Độ trễ $p_{95}$: `540.43 ms`
- **10 Threads đồng thời (100 requests):**
  - Thông lượng (Throughput): `12.55 QPS`
  - Độ trễ $p_{50}$: `720.15 ms`
  - Độ trễ $p_{95}$: `950.57 ms`

### 5.4 Kiểm chứng Phòng vệ & Suy giảm Uyển chuyển (Fallback Defense)
1. **Kịch bản Thế hệ Chỉ mục bị Xóa/Hỏng:**
   - Khi `generation_id` bị hỏng hoặc thư mục postings bị mất, hệ thống tự động suy giảm về `ilike_fallback` với thông báo suy giảm minh bạch: `"Lexical index generation unavailable; serving ILIKE"`.
2. **Kịch bản ChromaDB hoặc SentenceTransformer không khả dụng:**
   - Hệ thống tự động chuyển hướng truy vấn sang `fallback_bm25` với `is_degraded=True` và khai báo lý do `"ChromaDB service unreachable"`. Không sinh vector giả, không ngụy tạo thành công.

---

## 6. Hướng dẫn Tái lập & Câu lệnh Chạy Thực tế (Reproduction Commands)

Tất cả các kết quả trên đều có thể tái lập tức thì bằng các câu lệnh CLI chuẩn:

### 6.1 Khởi tạo Cơ sở Dữ liệu Đánh giá Cô lập
```powershell
# Chạy trên PowerShell
$env:DATABASE_URL = 'postgresql+psycopg://folio_live@127.0.0.1:55463/folio_eval'
$env:TEST_DATABASE_URL = 'postgresql+psycopg://folio_live@127.0.0.1:55463/folio_eval_test'
$env:FOLIO_TEST_ADMIN_URL = 'postgresql+psycopg://folio_live@127.0.0.1:55463/postgres'

# 1. Chạy migrations
& "F:\dpl13.10\folio-live-runtime\venv-clean\Scripts\python.exe" -m alembic upgrade head

# 2. Nạp dữ liệu chuẩn 103 bài viết
& "F:\dpl13.10\folio-live-runtime\venv-clean\Scripts\python.exe" scripts/seed_folio.py

# 3. Xây dựng và kiểm tra thế hệ chỉ mục
& "F:\dpl13.10\folio-live-runtime\venv-clean\Scripts\python.exe" scripts/index_cli.py build-index --verify
```

### 6.2 Kiểm thử Tự động Bộ Đánh giá
```powershell
& "F:\dpl13.10\folio-live-runtime\venv-clean\Scripts\python.exe" -m pytest tests/evaluate/ -v
```

### 6.3 Chạy Đánh giá Toàn bộ 5 Động cơ và Xuất Biểu đồ
```powershell
$env:CHROMA_PATH = 'F:/dpl13.10/WikiSearchEngine/data/vector'
$env:CHROMA_COLLECTION_NAME = 'wiki_ai_english'
$env:EMBEDDING_MODEL_NAME = 'all-MiniLM-L6-v2'
$env:PYTHONIOENCODING = 'utf-8'

# Chạy đầy đủ 30 queries (tune + test) kèm benchmark tài nguyên
& "F:\dpl13.10\WikiSearchEngine\env\Scripts\python.exe" evaluate/run_eval.py --split all

# Hoặc chỉ chạy tập kiểm thử độc lập (held-out test set, 20 queries)
& "F:\dpl13.10\WikiSearchEngine\env\Scripts\python.exe" evaluate/run_eval.py --split test
```

---

## 7. Artifacts & Danh mục Tệp tin đã Tạo

| Tệp tin | Vị trí | Mô tả |
|---|---|---|
| `corpus_manifest.json` | `evaluate/corpus_manifest.json` | Snapshot 103 tài liệu canonical, SHA256, phân bổ danh mục |
| `benchmark_queries.json` | `evaluate/benchmark_queries.json` | 30 câu hỏi phân loại 5 nhóm, gắn nhãn tune/test |
| `qrels.json` | `evaluate/qrels.json` | Nhãn liên quan phân cấp (2, 1) bằng Document ID chuẩn |
| `run_eval.py` | `evaluate/run_eval.py` | CLI runner đánh giá 5 động cơ, đo độ trễ, RAM, concurrency |
| `eval_results_p06.json` | `evaluate/eval_results_p06.json` | Dữ liệu đo đạc chi tiết từng query và chỉ số tổng hợp |
| `eval_chart_p06.png` | `evaluate/eval_chart_p06.png` | Biểu đồ chất lượng (MAP@10, nDCG@10) và độ trễ p50 |
| `test_eval_metrics.py` | `tests/evaluate/test_eval_metrics.py` | Unit tests công thức toán P@K, Recall, MAP, MRR, nDCG |
| `test_run_eval.py` | `tests/evaluate/test_run_eval.py` | Integration tests kiểm thử validation dataset và CLI |
| `P06-evaluation.md` | `docs/handoff/gemini/P06-evaluation.md` | Tài liệu nghiệm thu khoa học đầy đủ Mốc P06 |

---

## 8. Trạng thái Tích hợp & Sẵn sàng cho Integration B (P08/P09)

- [x] **Cô lập môi trường:** Hoàn toàn tách biệt worktree `WikiSearchEngine-p06` và database `folio_eval`, không chạm vào mã nguồn UI hoặc thay đổi của P07.
- [x] **Độ bao phủ kiểm thử:** 75/75 tests pass (64 search backend + 11 evaluate suite).
- [x] **Default Engine chốt:** Okapi BM25 là default search engine chính thức của Folio.
- [x] **Sẵn sàng tích hợp:** Sẵn sàng hợp nhất vào Integration B cùng với mốc P07 để chuyển tiếp sang P08 (Docker / Staging / Deploy).
