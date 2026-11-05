# Kế hoạch hoàn thiện Folio / WikiSearchEngine

Ngày lập: 31/10/2026.

Trạng thái: kế hoạch đề xuất để triển khai; các hạng mục dưới đây chưa được thực hiện trong lượt lập kế hoạch này.

Cập nhật 31/10/2026: GitHub remote `https://github.com/MarcusCyborg/folio.git` đã viết lại lịch sử. Checkout cũ đang ở `ab0f5fe`; remote `main` đã kiểm tra là `c4b19cffa676b4437e7346da2c410b198b04dc2c`. Workspace dành cho triển khai là clone mới `F:/dpl13.10/WikiSearchEngine-github`, sau khi xác minh theo `docs/handoff/gemini/CLONE-REPORT.md`. Checkout cũ có thay đổi chưa commit và được giữ nguyên; không pull/merge hai lịch sử trong bước chuyển workspace này.

So sánh trực tiếp cây file hai commit cho thấy chỉ đổi `.gitignore`, README và script chụp ảnh, đồng thời bỏ 8 ảnh public tracked. Runtime, tests, requirements và migrations không đổi; các commit import không đồng nghĩa với tính năng mới hoặc Phase 2 đã hoàn tất. Plan M0-M9 được giữ, chỉ điều chỉnh baseline, clean setup và nơi lưu evidence.

Mục tiêu: hoàn thiện ứng dụng Phase 1, đưa tìm kiếm Phase 2 vào luồng sử dụng thật, kiểm chứng trên môi trường sạch, triển khai public và bàn giao tài liệu có thể tái lập.

## 1. Căn cứ và phạm vi

Hiện trạng đã kiểm tra ở checkout cũ trong phiên làm việc. Các dòng test/database dưới đây là bằng chứng lịch sử; P00/P02 phải kiểm tra lại môi trường clone mới trước khi ghi PASS:

| Phần | Bằng chứng | Kết luận |
| --- | --- | --- |
| Backend Phase 1 | Chạy `python -m pytest tests/backend -q`: 58 passed, 15 warnings | Có nền chức năng hoạt động trong môi trường local hiện tại |
| Database local | `alembic current`: `20261031_click_unique (head)` | Local đã ở migration mới nhất |
| Tìm kiếm Folio | `catalog_service.py` dùng `ILIKE`; giao diện gọi `/api/v1/documents` | Chưa tích hợp xếp hạng retrieval |
| Search cũ | BM25, Chroma, embedding và RRF trong `search_service.py`, `utils/` | Có thể tái sử dụng, nhưng dùng JSON/URL thay vì Document Store/ID của Folio |
| Evaluation cũ | 20 query; P@10 = 0.575, MAP = 0.644126 trong `evaluate/eval_results.json` | Là kết quả đã lưu của legacy; chưa chạy lại và không phải baseline của Folio mới |
| Cấu hình production | `validate_production()` có định nghĩa nhưng chưa được gọi | Đã tái hiện việc import app production vẫn chấp nhận cấu hình cookie/secret không đạt yêu cầu |
| Môi trường test | `env/pyvenv.cfg` bật `include-system-site-packages`; admin browser tests chọn `channel="chrome"` | Cần chứng minh setup sạch và CI không phụ thuộc máy hiện tại |
| Dữ liệu legacy | JSONL khoảng 141 MB; một file Chroma SQLite khoảng 920 MB, chưa tính các file index khác; `data/` bị Git ignore | Cần quy trình phân phối hoặc dựng lại dữ liệu/index |
| UI | Có báo cáo desktop cũ; lần kiểm tra hiện tại chưa chạy lại frontend E2E | Mobile, accessibility và bằng chứng UI mới là công việc còn lại |
| Deploy | Compose hiện chỉ có PostgreSQL | Chưa có bộ triển khai ứng dụng đầy đủ |

Trong repository chưa tìm thấy đặc tả nghiệm thu Phase 2 độc lập. Kế hoạch lấy tokenization, inverted index, BM25 và retrieval evaluation làm phần bắt buộc theo định hướng đã ghi trong README/assignment cũ. Khi có rubric chính thức, đối chiếu trước khi đóng mốc Phase 2; không tự coi semantic search hay Learning to Rank là yêu cầu của môn học.

Các giả định dùng để lập kế hoạch:

- Giữ FastAPI, PostgreSQL, vanilla JavaScript và giao diện Folio hiện có.
- Corpus hiện tại chủ yếu tiếng Anh; chuẩn hóa Unicode nhưng không tuyên bố hỗ trợ tìm kiếm tiếng Việt chuyên sâu khi chưa có tokenizer/model và bộ đánh giá tương ứng.
- Giữ tối thiểu 100 tài liệu published và 3 draft làm bộ demo tái lập. Corpus lớn dùng cho benchmark là dữ liệu thật, có nguồn và thống kê riêng.
- Clone mới chỉ có file Git theo dõi; `.env`, virtualenv, database, `data/` và model cache không được mang sang mặc định. Dựng venv/DB test riêng; không sao chép nguyên môi trường hoặc secrets của checkout cũ.
- Mặc định đề xuất deploy Linux VPS bằng Docker Compose, HTTPS qua Caddy và database có volume riêng. Đây là lựa chọn lập kế hoạch; nhà cung cấp, domain và ngân sách chưa được chốt.
- Hoàn thiện responsive public và admin trong đợt này vì mục tiêu mới là toàn bộ dự án. Đây là phạm vi bổ sung so với đợt bàn giao desktop trước.
- Semantic/hybrid được tích hợp và kiểm thử như chế độ nâng cao. Chế độ mặc định chỉ được chọn sau khi có số liệu đánh giá.

## 2. Điều kiện để gọi là hoàn tất

1. Các chức năng Phase 1 dùng được từ giao diện thật, đúng quyền của cả 5 vai trò.
2. Người dùng tìm kiếm trên dữ liệu Folio bằng BM25, lọc và mở đúng tài liệu; thứ hạng và click log có thể đối chiếu.
3. Sửa, publish, unpublish hoặc xóa tài liệu được phản ánh vào search; tài liệu không còn public không xuất hiện dù index đang trễ.
4. Có inverted index thực sự, bộ đánh giá cố định và báo cáo so sánh các phương pháp trên cùng corpus.
5. Clone sạch có thể cài đặt, migrate, seed, build index và chạy test theo hướng dẫn.
6. Public/admin dùng được ở desktop và mobile; các luồng chính dùng được bằng bàn phím.
7. Có HTTPS, cấu hình production, tài khoản quản trị riêng, backup và cách khôi phục đã thử.
8. CI, báo cáo test, báo cáo retrieval và phiên bản đang deploy cùng trỏ tới một commit phát hành.

## 3. Kiến trúc đích

Luồng đọc: Browser -> FastAPI -> PostgreSQL và Search Service -> danh sách Document ID -> kiểm tra quyền/publication trong PostgreSQL -> response và interaction log.

Luồng ghi: Admin CRUD -> transaction PostgreSQL gồm thay đổi tài liệu và job index -> worker cập nhật index -> ghi revision đã xử lý.

Quyết định kỹ thuật đề xuất:

- PostgreSQL là nguồn dữ liệu chính. Mọi kết quả lexical/vector dùng `document_id` của Folio; URL chỉ còn là thông tin nguồn.
- BM25 có inverted index với posting list, term frequency, document length, document frequency và corpus statistics. Đề xuất lưu phần lexical trong các bảng PostgreSQL riêng để các process dùng chung trạng thái, dễ backup và kiểm tra thuật toán.
- Worker xử lý job từ bảng outbox trong PostgreSQL; chưa cần thêm Redis/Celery. Job được tạo cùng transaction với thao tác nội dung để tránh mất cập nhật khi process dừng.
- Chroma chạy như dịch vụ riêng nếu bật semantic/hybrid. Worker chịu trách nhiệm ghi; không để nhiều web process tự sửa cùng thư mục Chroma embedded.
- Index có version/generation, revision hoặc content hash. Build lại vào generation mới, kiểm tra rồi mới chuyển active; không xóa index đang phục vụ trước khi build thành công.
- Model và tài nguyên NLP được chuẩn bị ở bước build/bootstrap. Request của người dùng không kích hoạt download NLTK/model.
- Ứng dụng bắt đầu với cấu hình process vừa đủ cho VPS; tăng worker sau khi đo RAM, tải model và throughput. Không nhân bản model theo số worker một cách mặc định.
- API browse và search tách rõ: giữ `/api/v1/documents` cho catalog và tương thích cũ; thêm `/api/v1/search` cho ranking, filters, pagination và thông tin engine. `/search` legacy giữ sau feature flag với hướng dẫn chuyển đổi.

## 4. Lộ trình triển khai

### M0. Chốt baseline và hợp đồng nghiệm thu

Phụ thuộc: không có. Ước lượng: 0.5-1 ngày công.

- Ghi exact SHA/remote/branch từ clone mới và CLONE-REPORT, các thay đổi đang có và kết quả test thực tế. Checkout cũ cùng local screenshots được bảo toàn; không đưa lại các file ảnh GitHub đã chủ động bỏ vào bản mới.
- Tạo checklist thống nhất Phase 1, Phase 2 và release; tách yêu cầu chính thức khỏi các cải tiến đề xuất.
- Thống kê corpus: số tài liệu, dung lượng, ngôn ngữ, trùng URL, nguồn/license; xác định corpus demo, evaluation và benchmark.
- Chốt contract search, semantics filters/sort, ID và freshness trước khi sửa API/frontend.
- Ghi mặc định triển khai và các thông tin còn cần tại bước release: hosting, domain, ngân sách, người giữ admin/backup.

Đầu ra: `docs/completion-plan.md`, `docs/acceptance-matrix.md`, `docs/search-contract.md` và baseline evidence.

Nghiệm thu: từng yêu cầu có trạng thái, nơi triển khai, cách kiểm tra và điều kiện đạt; không dùng cụm "all phases complete" để mô tả riêng Wave 2 của Phase 1.

### M1. Hoàn thiện cấu hình và bảo mật production

Phụ thuộc: M0. Ước lượng: 1-2 ngày công.

- Gọi kiểm tra production trong startup/lifespan; fail sớm nếu secret mặc định, cookie không Secure hoặc biến bắt buộc thiếu/sai. Kiểm tra cả boot thực tế, không chỉ gọi trực tiếp validator.
- Chuẩn hóa cấu hình local/test/staging/production, origin được chấp nhận và trusted proxy khi chạy sau HTTPS reverse proxy.
- Viết CLI tạo admin đầu tiên và khôi phục quyền quản trị theo cơ chế có xác thực vận hành; nhập mật khẩu ẩn hoặc qua secret, không có password mặc định, không in token/password ra log.
- Giữ demo users ở môi trường demo; thêm kiểm tra phát hành để không mang tài khoản demo/mật khẩu công khai vào production.
- Bổ sung giới hạn login/register/search theo session/account/IP phù hợp; rate limit hoạt động nhất quán giữa các process. Giữ các kiểm tra CSRF, RBAC và comment anti-spam đã có.
- Chuẩn hóa lỗi public để không lộ connection string/stack trace; kiểm tra health endpoint khi DB lỗi. Bổ sung security headers phù hợp với assets thực tế và HTTPS.
- Thêm tác vụ dọn session hết hạn và chính sách lưu interaction log; xác định thời gian lưu trước khi public.

Vùng sửa: `src/backend/core/`, `main.py`, `api/auth.py`, script bootstrap và tests bảo mật.

Nghiệm thu: cấu hình production sai làm startup thất bại; cấu hình đúng chạy được qua HTTPS; admin khởi tạo từ DB mới; cookie/CSRF/logout/session revoke/RBAC đúng; abuse tests trả 429 theo chính sách.

### M2. Làm setup và test tái lập được

Phụ thuộc: M0; chạy cùng nhịp với M1. Ước lượng: 1-2 ngày công.

- Tạo venv sạch không dùng system-site-packages; kiểm chứng dependencies bằng cài đặt mới trên môi trường đích.
- Chọn và pin bộ phiên bản runtime/dev/legacy đã kiểm tra. Ghi rõ cách cài core và optional search dependencies, không ngầm dựa vào package có sẵn.
- Test DB riêng được tạo, migrate bằng Alembic và seed fixtures một cách tự động. Không chỉ `Base.metadata.create_all`, vì cách đó không chứng minh migration upgrade chạy đúng.
- Củng cố guard TEST_DATABASE_URL bằng parse URL và đối chiếu DB đích, thay vì chỉ tìm chuỗi `test` ở bất kỳ vị trí nào.
- Dùng Chromium do Playwright cài trong CI; chọn system Chrome chỉ như cấu hình tùy chọn. Thay các sleep chờ server cố định bằng readiness check có timeout.
- Cô lập dữ liệu từng test/nhóm test, dọn trạng thái đúng phạm vi; test không phụ thuộc thứ tự chạy hoặc tài khoản được seed thủ công từ trước.
- Tạo CI sớm với PostgreSQL service, migrate, seed, backend và browser tests. Public capture script trên GitHub hiện ghi `../screenshots/`, trong khi một số tests còn có đường dẫn khác: chuẩn hóa output path cấu hình được, tách theo run/worktree/commit và cập nhật artifact paths. Không ghi đè bộ ảnh bàn giao hoặc output của chat khác.

Đầu ra: dependency files/lock, fixture bootstrap, `.github/workflows/ci.yml` và hướng dẫn clean setup.

Nghiệm thu: một checkout sạch chạy được test trong CI trên Linux; baseline 58 backend tests tiếp tục pass, frontend tests có kết quả mới và lỗi phát hiện được xử lý, không chỉ sao chép báo cáo cũ.

### M3. Thống nhất dữ liệu và vòng đời index

Phụ thuộc: M0, M2. Ước lượng: 2-3 ngày công.

- Viết adapter/importer từ JSON/JSONL cũ sang Document Store, map URL -> Document ID, xử lý trùng lặp và lưu attribution/license. Chạy dry-run trước khi import thật.
- Seed/import phải idempotent, không ghi đè nội dung người dùng đã chỉnh; có thống kê inserted/skipped/conflict/rejected.
- Thiết kế schema index, generation, content revision và outbox; thêm migration nâng cấp DB hiện có.
- Thêm job index cho create/edit/publish/unpublish/delete và thay đổi taxonomy ảnh hưởng search. Worker có retry, backoff, trạng thái lỗi và khả năng tiếp tục sau restart.
- Kiểm tra revision trước khi áp dụng job để một job cũ không ghi đè nội dung mới. Rebuild có watermark/replay hoặc khóa chuyển generation phù hợp để không bỏ mất cập nhật phát sinh trong lúc build.
- Cung cấp lệnh build/rebuild/status/verify. Không xóa dữ liệu hoặc collection đang dùng như bước đầu của rebuild.
- Chốt giới hạn độ trễ: mục tiêu ban đầu bài publish/edit có thể tìm thấy trong 60 giây ở tải demo; unpublish/delete bị loại khỏi response ngay sau transaction commit nhờ kiểm tra live DB.

Vùng sửa: `models/`, `services/admin/content_service.py`, `src/indexing/`, migrations và scripts import.

Nghiệm thu: crash/retry không mất job, không nhân đôi tài liệu; bài unpublished/deleted không lộ title/snippet; rebuild lỗi vẫn giữ index cũ; mọi process đọc cùng generation hợp lệ.

### M4. Hoàn thiện retrieval: inverted index và BM25

Phụ thuộc: M3. Ước lượng: 2-3 ngày công.

- Tách tokenizer, index builder, candidate retrieval và scoring thành module có interface rõ.
- Định nghĩa chuẩn hóa chữ hoa/thường, Unicode, dấu câu, số, từ rỗng và stopwords; document/query dùng cùng một phiên bản analyzer.
- Thay vòng quét mọi document bằng posting list cho các term có trong query; lưu document length để không tính lại mỗi request.
- Implement BM25 với k1/b cấu hình; nếu có title boost, mô tả chính xác công thức và kiểm chứng, không gắn nhãn BM25F khi chưa triển khai BM25F.
- Thêm TF-IDF baseline đơn giản để đối chiếu; nếu rubric không cần thì chỉ giữ trong evaluation, không đưa thêm chế độ ra giao diện người đọc.
- Filter category/tag/date phải tác động lên tập kết quả đúng; xếp hạng ổn định với tie-break theo ID, không chỉ lọc top-k cuối cùng rồi coi đó là toàn bộ kết quả.
- Chốt contract phân trang: lexical có thể đếm exact; semantic/hybrid phải mô tả cửa sổ candidates và `has_more`, không bịa tổng số toàn corpus. Giữ thứ tự giữa các trang trong cùng search session/generation.

Đầu ra: module search lexical, bảng index và tests thuật toán/API.

Nghiệm thu: score khớp ví dụ tính tay; xử lý corpus rỗng, từ không có trong index, query lặp, tài liệu dài và update/delete đúng; BM25 chạy độc lập khi không cài hoặc không bật ML.

### M5. Tích hợp semantic/hybrid, API, giao diện và logging

Phụ thuộc: M3, M4. Ước lượng: 2-3 ngày công.

- Map chunk vector về Document ID/revision; chọn kích thước chunk và phương án gộp chunk theo document. Chặn cùng bài xuất hiện nhiều lần.
- Pin model/revision và chuẩn bị cache NLP/model trước runtime. Gỡ download NLTK ở import/request path.
- Tái sử dụng RRF legacy qua interface mới; đo và cấu hình các trọng số thay vì mặc định coi các hằng số cũ là tối ưu cho corpus Folio.
- Thêm `/api/v1/search` nhận query, filters, mode và phân trang; trả document summaries, search_event_id, engine thực dùng, index version và thời gian xử lý. Không trả body đầy đủ cho mọi result.
- Khi vector không sẵn sàng, hybrid có thể hạ về BM25 và ghi rõ `engine_used`/trạng thái degraded. Chế độ semantic thuần không được âm thầm giả thành semantic thành công.
- Nối ô search của Folio với API mới. Có query thì mặc định sắp xếp liên quan; khi browse không query vẫn dùng newest/title như hiện tại. URL giữ query, filters, sort và trang khi back/refresh.
- Dùng summary/snippet an toàn; highlight không phá HTML hoặc tạo đường XSS. UI có loading, empty, lỗi retry, timeout và kết quả dự phòng.
- Mở rộng log với mode/engine, index version, filters, thứ tự result IDs và thời gian; log chỉ chứa các ID thực trả cho người dùng sau bước kiểm tra live DB. Tính rank của click ở server từ event gốc, không tin rank client gửi.
- Giữ idempotency click và phân biệt search/click/view. Không ghi click khi chỉ reload trang detail.

Vùng sửa: `services/search/`, schemas/API mới, `library_view.js`, `detail_view.js`, event models/services và analytics.

Nghiệm thu: từ UI tìm bài, đổi filter, sang trang, mở detail và back đều đúng; click gắn đúng result; service vector lỗi vẫn có hành vi rõ ràng; tài liệu không public bị chặn ở mọi chế độ và cả trang tiếp theo.

### M6. Đánh giá retrieval và hiệu năng có thể chạy lại

Phụ thuộc: M4, M5; chuẩn bị queries/qrels từ M3. Ước lượng: 1.5-2.5 ngày công.

- Chuyển evaluation từ notebook thành CLI có cấu hình, notebook chỉ dùng phân tích/biểu đồ.
- Tạo corpus snapshot và qrels dùng Document ID; kiểm tra tất cả ID tồn tại trong snapshot. Tái dùng 20 query cũ chỉ khi relevance mapping còn đúng.
- Đề xuất 40-60 query gồm exact title, nhiều từ khóa, diễn đạt tự nhiên, mơ hồ và không có kết quả. Tách tập chỉnh tham số và tập đánh giá giữ lại; không tune trên toàn bộ test set.
- So sánh ILIKE, TF-IDF, BM25, semantic và hybrid trên cùng corpus, query, filter và top-k. Ghi rõ baseline ILIKE dùng thứ tự nào.
- Báo cáo P@5/P@10, Recall@10, MAP@10, MRR@10, nDCG@10; mô tả rõ cách tính khi qrels không có positive. Báo riêng truy vấn negative, timeout và lỗi; không loại chúng khỏi báo cáo để làm đẹp số liệu.
- Đo p50/p95, RAM, thời gian build, số tài liệu/chunks và concurrent requests; phân biệt cold start với warm query.
- Mục tiêu kỹ thuật ban đầu để đo: warm BM25 p95 <= 300 ms, hybrid p95 <= 1.5 s trên corpus 5.000 tài liệu thật và 10 người dùng mô phỏng, máy tham chiếu 4 vCPU/8 GB RAM. Đây là mục tiêu đề xuất, chưa phải kết quả hay cam kết; chốt lại một lần khi chọn hạ tầng/corpus, trước vòng nghiệm thu.
- Chọn default theo chất lượng và độ trễ. Hybrid vẫn có thể là chế độ nâng cao nếu không cải thiện rõ BM25; không bắt buộc bật mặc định để được coi là hoàn thành tích hợp.

Đầu ra: `evaluate/run_eval.py`, queries/qrels versioned, manifest corpus, metrics JSON/CSV và `docs/search-evaluation.md`.

Nghiệm thu: người khác chạy lại được báo cáo từ cùng commit/snapshot/model; không thiếu qrels IDs; failures được tính rõ; kết quả cùng các đánh đổi quyết định default engine.

### M7. Hoàn thiện trải nghiệm và responsive

Phụ thuộc: contract M0; ghép cuối với M5. Ước lượng: 1.5-2.5 ngày công.

- Giữ tên Folio, màu sắc, typography và cấu trúc hiện có; tập trung vào luồng đọc/tìm kiếm và tác vụ quản trị.
- Public: search nhìn thấy rõ, kết quả liên quan dễ đọc, filter thu gọn trên mobile, nội dung dài/ảnh/công thức/bảng không phá trang.
- Admin: sidebar chuyển sang drawer ở màn hình nhỏ; bảng có vùng cuộn hoặc chuyển layout hợp lý; menu hành động không bị cắt; editor và Save/Publish dùng được khi bàn phím ảo mở.
- Kiểm tra form dirty guard cho sidebar/header/back/refresh; label Save/Unpublish khớp trạng thái thực; mất mạng không làm mất nội dung đang nhập.
- Kiểm tra focus, keyboard navigation, label, error association, dialog focus restore, contrast theo WCAG AA và reduced motion cho luồng chính.
- Viewports: 360, 390, 768, 1280, 1440 và 1920 px. Kiểm tra zoom trình duyệt thực hoặc phương pháp layout tương đương; không coi `device_scale_factor` là bằng chứng browser zoom.
- Kiểm tra loading/empty/error/forbidden/long-text bằng dữ liệu thật; lưu ảnh cùng viewport, route, commit và dataset theo cấu hình output của M2. Không phục hồi 8 ảnh cũ vào `docs/screenshots/` hoặc ghi đè thư mục screenshot ngoài repo dùng chung.

Nghiệm thu: hoàn thành search -> đọc -> tương tác trên điện thoại và bằng bàn phím; admin thực hiện CRUD/moderation được ở màn hình nhỏ; không tràn ngang toàn trang ngoài vùng bảng/code chủ đích; không còn console/network lỗi chưa xử lý trong luồng nghiệm thu.

SEO công khai: quản lý metadata hiện tại là chức năng Phase 1. Nếu mục tiêu bao gồm Google index/share preview cho từng bài, thêm route public đọc trực tiếp có HTML metadata phía server, canonical/sitemap/robots và 404 đúng; dữ liệu unpublished không nằm trong sitemap/cache. Hạng mục này được tách thành phần mở rộng có điều kiện, không mặc định chuyển toàn bộ SPA sang framework mới.

### M8. Đóng gói, staging và khôi phục

Phụ thuộc: M1, M2; hoàn tất sau M5-M7. Ước lượng: 1.5-2.5 ngày công.

- Tạo Dockerfile, `.dockerignore`, compose development/production và Caddy config. Các service gồm app, worker, PostgreSQL; Chroma theo profile khi bật ML.
- Chạy container không phải root; secrets không nằm trong image/repo; PostgreSQL/Chroma chỉ mở mạng nội bộ, volume tách khỏi vòng đời container.
- Có migration job riêng, chạy một lần trước rollout; không để mọi worker tự migrate. Seed taxonomy/settings và tạo admin theo quy trình rõ ràng.
- Dữ liệu lớn/model được cung cấp qua artifact hoặc quy trình download/build có checksum, version và hướng dẫn license. Không phụ thuộc `F:\...`, env cũ hoặc tự crawl 50.000 bài lúc boot.
- Tách liveness, readiness và trạng thái degraded của search; log request ID, error, latency, index revision/lag và failed jobs, tránh ghi secret/session token.
- Thiết lập backup PostgreSQL, manifest/model/index config và file media nếu có. Index có thể dựng lại từ DB; nếu chọn backup index thì phải ghi cách đồng bộ snapshot.
- Mục tiêu vận hành ban đầu: backup hằng ngày, giữ 7 ngày, bản sao ngoài máy; RPO <= 24 giờ, RTO <= 2 giờ. Đây là mục tiêu để kiểm chứng qua restore drill, điều chỉnh theo hosting trước release.
- Test khôi phục DB mới + build/recover index + health/search; test rollback app image với migration tương thích. Không dùng rollback schema phá dữ liệu như đường mặc định.
- Dựng staging cùng cấu hình production, chạy smoke/E2E và quan sát log trong một chu kỳ sử dụng đại diện.

Nghiệm thu: từ máy sạch dựng được staging; restart/recreate không mất dữ liệu; HTTPS/login/search/index worker chạy đúng; khôi phục và rollback có lệnh, kết quả và thời gian thực đo.

### M9. Phát hành và bàn giao

Phụ thuộc: tất cả release gates. Ước lượng: 0.5-1 ngày công.

- Chốt release candidate và chạy CI/evaluation/smoke trên đúng commit; sửa các lỗi còn lại và chạy lại phần liên quan.
- Cập nhật README, architecture, checklist, API/search contract, test report, evaluation report và demo script. Sửa đường dẫn model/test đã lỗi thời và các số liệu không còn khớp.
- Ghi rõ hai cấu hình core/BM25 và hybrid; tài nguyên cần thiết, cách bootstrap tài khoản, migrate, reindex, backup, restore và xử lý lỗi.
- Tạo release/tag sau khi code và bằng chứng đã được rà soát. Chuẩn bị domain, tài khoản hosting, DNS và cấu hình chi phí trước bước triển khai public.
- Deploy artifact đã thử ở staging, chạy smoke test production bằng tài khoản/dữ liệu kiểm tra có kiểm soát và xác nhận rollback vẫn khả dụng.
- Bàn giao URL, phiên bản, báo cáo, runbook và hướng dẫn demo 8-10 phút bao gồm cả search ranking, cập nhật index và analytics.

Nghiệm thu: người nhận có thể mở bản public, làm demo theo script và dựng lại dự án từ README mà không cần môi trường riêng của người phát triển.

## 5. Thứ tự phụ thuộc và cách chia công việc

Đường chính: M0 -> M3 -> M4 -> M5 -> M6 -> M8 -> M9.

M1 và M2 được làm sớm, không để sát ngày deploy. Nếu làm song song, review/tích hợp cả hai branch và chạy regression chung trước M3. Tương tự, P06 evaluation và P07 frontend phải được tích hợp, kiểm tra chung trước bước staging cuối. Hai handoff READY ở hai branch riêng không thay thế kết quả integration. M7 bắt đầu sau khi contract search được chốt, rồi tích hợp khi M5 có API thật. Packaging/CI ở M8 có thể chuẩn bị từ M2, nhưng release gate chỉ đóng sau kiểm thử đầy đủ.

Nếu về sau triển khai bằng nhiều người hoặc agent, ownership nên tách thành: nền tảng/bảo mật; dữ liệu/index; search/evaluation; frontend/QA. Chỉ làm đồng thời sau khi shared schemas, API contract và migrations có một người điều phối. Không khởi chạy agent hay tạo worktree chỉ vì tài liệu này đề cập cách chia việc.

Các đơn vị review/commit hợp lý:

| Đợt | Nội dung | Điều kiện ghép |
| --- | --- | --- |
| A | Production config, admin bootstrap, giới hạn truy cập | Security/startup tests |
| B | Dependencies sạch, test DB lifecycle, CI/browser portability | CI sạch pass |
| C | Search schema, importer, outbox và index lifecycle | Migration + CRUD/index tests |
| D | Tokenizer, inverted index, BM25/TF-IDF | Unit scoring + retrieval correctness |
| E | Semantic/hybrid, API và logging | Failure/fallback/privacy tests |
| F | Search UI, responsive và accessibility | Browser flows + ảnh thực tế |
| G | Evaluation và performance | Báo cáo tái lập cùng manifest |
| H | Containers, staging, backup/restore, release docs | Restore drill + release smoke |

## 6. Ma trận kiểm thử bắt buộc

| Nhóm | Những tình huống cần chứng minh |
| --- | --- |
| Startup/config | Production thiếu secret/cookie/DB; core không có ML; model/index chưa sẵn sàng |
| Migration/setup | DB trắng; nâng từ revision hiện tại; seed 2 lần; checkout sạch trên Linux |
| Security | 5 vai trò, revoke quyền, last-admin, CSRF, sanitizer, login/register limit, cookie sau proxy |
| Index | Publish/edit/unpublish/delete; job trùng; job đảo thứ tự; process crash; rebuild khi có ghi mới; generation swap |
| Retrieval | Score tính tay; query rỗng/Unicode/không khớp; filter trước ranking; tie-break; phân trang không lặp; ẩn draft |
| Hybrid | Chunk gộp đúng document; timeout Chroma; model thiếu; fallback có khai báo; mismatch model/index version |
| Logging | Thứ tự result IDs; click membership; actor; idempotency concurrent; refresh không thêm click |
| UI | 5 vai trò, dirty form, back/forward, trạng thái lỗi, mobile, keyboard, nội dung dài |
| Performance | Cold/warm; p50/p95; concurrency; RAM; build time; index lag; kích thước corpus thực |
| Operations | Restart, database unavailable, full disk cảnh báo nếu có hỗ trợ hạ tầng, backup, restore, app rollback |

Các lệnh hiện có để giữ làm regression: `python -m pytest tests/backend -q`, `python -m pytest tests/frontend -q`, `alembic upgrade head`, `python scripts/seed_folio.py`. Test phải dùng database riêng và cấu hình test an toàn.

Các lệnh cần tạo trong quá trình triển khai: bootstrap-admin, import-corpus --dry-run, build-index, verify-index, run-evaluation và deployment-smoke. Tên CLI cuối cùng được ghi trong README khi thực sự tồn tại, không trình bày chúng như công cụ đã có sẵn.

## 7. Release gates

| Gate | Điều kiện được đóng |
| --- | --- |
| G1: Phase 1 | Clean setup, migrations, backend/browser flows và config production pass |
| G2: Phase 2 core | Inverted index/BM25 trên Document Store; index lifecycle; search UI/logging; evaluation tái lập |
| G3: Advanced search | Semantic/hybrid cùng Document ID, filter/publication đúng, model bootstrap và fallback được kiểm thử |
| G4: UI | Desktop/mobile/keyboard và các trạng thái lỗi chính đã kiểm tra trực tiếp |
| G5: Deploy | HTTPS, secrets, admin, persistence, staging smoke, backup restore và rollback đã xác minh |
| G6: Delivery | Checklist đối chiếu yêu cầu, báo cáo cùng commit và demo từ bản public hoạt động |

Không dùng số lượng test pass đơn lẻ để thay cho các gate. Không gọi một gate pass nếu chỉ có code hoặc báo cáo cũ mà chưa có kết quả thực thi tương ứng.

## 8. Ước lượng và quyết định còn mở

Tổng sơ bộ: khoảng 14-23 ngày công triển khai và kiểm chứng cho một người đã quen codebase; nên dự trù 20-30% cho lỗi tích hợp, dữ liệu và hạ tầng. Đây không phải lịch cam kết. Có thể rút thời gian lịch bằng phân công độc lập sau M0, nhưng không bỏ các gate.

Những thông tin cần chốt khi bắt đầu hạng mục liên quan:

- Rubric Phase 2 chính thức: có yêu cầu tự cài thuật toán, TF-IDF, corpus tối thiểu hoặc loại metrics cụ thể hay không.
- Hosting/domain/ngân sách: quyết định trước M8; kế hoạch vẫn thực hiện được các mốc trước đó với local/staging.
- SEO crawler thực tế: nếu là yêu cầu phát hành thì thêm public HTML routes ở M7; nếu chỉ là rubric quản lý metadata thì không tự mở rộng thành dự án SSR.
- Quy mô corpus và ngôn ngữ: phải chốt trước khi đóng benchmark và đánh giá chất lượng; không suy ra mục tiêu 50.000 bài chỉ từ script legacy.

Các mở rộng chưa có căn cứ bắt buộc: Learning to Rank, chatbot/RAG, email marketing, native mobile, đổi framework frontend, Kubernetes và microservices. Chỉ thêm khi gắn với yêu cầu cụ thể; chúng không phải điều kiện để kết thúc dự án theo phạm vi hiện có.

## 9. Mốc bắt đầu được đề xuất

### Preflight — Clone GitHub mới nhất

Đây là bước trước M0. Clone từ `https://github.com/MarcusCyborg/folio.git` vào `F:/dpl13.10/WikiSearchEngine-github`, không đụng checkout cũ đang dirty. Ghi exact commit SHA, branch, remote, status và đối chiếu nội dung trong `docs/handoff/gemini/CLONE-REPORT.md`. Sau xác minh, đưa bản plan và prompt pack cập nhật vào clone. Ba file bàn giao mới là thay đổi local có chủ đích, chưa commit/push; source code vẫn ở baseline GitHub.

### Sau preflight

Bắt đầu M0-M2: sửa production validation, bổ sung bootstrap admin, làm môi trường/test/CI sạch và chốt search contract. Sau đó mới nối Phase 2, để mọi thay đổi Phase 2 đều có regression gate bảo vệ Phase 1.

Nếu clone mới có cấu trúc hoặc contract khác bản local đã audit, chạy lại M0 từ đầu và coi các kết luận cũ là historical evidence cho đến khi kiểm chứng lại.

