# Folio implementation contracts — v1 frozen (2026-10-31)

Đọc cùng `README.md` trong thư mục này và `ASSIGNMENT.md` ở repo root. Foundation đã hoàn thành và freeze bản này trước Wave 1. Sau freeze chỉ coordinator đổi và thông báo cho tất cả worker.


## 1. Stack, deployment và đường dẫn

- Python 3.10+, FastAPI, Pydantic 2, SQLAlchemy 2 synchronous sessions, PostgreSQL 16+, psycopg 3, Alembic. Môi trường hiện có là Python 3.10.11; ưu tiên pin bộ thư viện còn tương thích, chỉ nâng Python nếu có lý do kỹ thuật được ghi lại. Không bắt buộc nâng runtime chỉ để đổi UI.
- Khóa phiên bản dependencies tương thích sau khi cài/test; không tự nâng toàn bộ stack legacy.
- `requirements.txt` cho runtime Phase 1 nhẹ; `requirements-dev.txt` cho tests; `requirements-legacy.txt` chứa requirements runtime + các ML/crawler dependencies hiện có. Ghi lại cách chạy legacy trong README.
- App server cùng origin phục vụ `/api/v1/*`, static UI và `/health`. Register API trước static mount `/`.
- `DATABASE_URL`, `TEST_DATABASE_URL`, `APP_SECRET`, `APP_ENV=development|production`, `ENABLE_LEGACY_SEARCH=false`, `COOKIE_SECURE=false` chỉ dùng local; production bắt buộc cookie secure và secret riêng.
- `.env.example` có placeholder, không credential production; bỏ `.env`, DB dumps, secret và virtualenv khỏi Git.
- Docker Compose là đường chạy PostgreSQL khuyên dùng; có hướng dẫn PostgreSQL local thay thế nếu Docker không có. Không thay bằng SQLite rồi tuyên bố đã test PostgreSQL.
- Frontend native ES modules và hash routes. Browser entry giữ ở `/`; không cần build framework.
- Local defaults: app 8000, database local theo compose; worker dùng port/DB riêng khi chạy đồng thời.
- `GET /health`: nhẹ, kiểm tra DB, trả `{status:"ok", database:"ok", legacy_search:"disabled|enabled"}` hoặc status 503 khi DB không sẵn sàng. Không khởi tạo model để health check.
- `GET /search` legacy: chỉ import/initialize service khi flag bật và endpoint thực sự cần; service được cache, không khởi tạo trùng đồng thời. Flag tắt hoặc optional dependencies/data thiếu trả 503 rõ ràng; không ảnh hưởng `/api/v1`.

## 2. Quy ước chung API

- Prefix `/api/v1`; ID là UUID string, role/permission key là snake_case string, timestamps RFC3339 UTC, dates `YYYY-MM-DD`.
- Với mọi collection: `page` mặc định 1, `page_size` mặc định 20, tối đa 100. Response `{items:[], page:1, page_size:20, total:0, total_pages:0}`. Trang vượt cuối trả `items:[]`, không tự nhảy trang.
- Sorting luôn có id tie-breaker. Các enum filter/sort phải allowlist, không nối SQL tùy ý.
- Create 201; read/update 200; delete/idempotent mutation 204 hoặc response được ghi rõ phía dưới.
- Error thống nhất `{error:{code:"FORBIDDEN", message:"...", fields:{}}}`; normalize cả FastAPI validation và HTTP exceptions. `fields` map field name -> string list, có thể rỗng.
- Status: 401 chưa login/session hết hạn khi route cần login; 403 thiếu quyền/CSRF; 404 không có hoặc không được public; 409 conflict; 422 validation; 429 hạn chế tần suất; 503 phụ thuộc chưa sẵn sàng.
- Các trường do server quản lý không được nhận qua mass assignment. Pydantic request schemas cấm fields thừa.
- SQL tham số hóa; keyword search escape `%`, `_` khi coi input là literal substring. Không đánh giá `ILIKE` là full-text ranking.
- List API public không trả full content. Public API không trả email, password hash, session token, audit payload hoặc SEO draft chưa published.
- Lengths tối thiểu thống nhất: title 1–240, summary 1–1000, query tối đa 200, comment 1–4000, username 3–30 theo `[a-z0-9_]`, display_name 1–80, bio tối đa 1000; password 10–128. Content giới hạn hợp lý, đề xuất 250k ký tự, validation thông báo rõ.
- Keyword và filters chỉ chạy trên published, non-deleted documents. Timestamp/date theo UTC; `date_from` inclusive 00:00, `date_to` inclusive hết ngày bằng predicate `< next_day`. from > to là 422.

## 3. Data model thống nhất

Foundation sở hữu ORM models và migration; worker dùng models qua `src.backend.models` và không tự thêm cột.

| Table | Trường/chính sách |
|---|---|
| users | id, email, username, password_hash, display_name, bio, role_key FK, is_active, commenting_suspended_until nullable, created_at, updated_at; email/username normalized và unique case-insensitive |
| roles | key: member, content_manager, moderator, data_seo, super_admin; label; không cần tạo role tùy ý |
| permissions | key, description; catalog cố định |
| role_permissions | role_key + permission_key unique; editable cho các role trừ super_admin protected |
| sessions | id, token_hash unique, user_id nullable cho guest, actor_key opaque, csrf_token random, expires_at, created_at; raw session token chỉ trong cookie |
| categories | id, name, slug unique, description, created_at |
| tags | id, name, slug unique |
| documents | id, title, content, summary, category_id FK, author string, created_by FK nullable, created_at, updated_at, published_at nullable, views_count int default 0, status draft/published, deleted_at nullable, source_url nullable unique, source_license nullable, source_attribution nullable, cover_image_url nullable, cover_image_alt, seo_title, seo_description, seo_keywords JSON array |
| document_tags | document_id + tag_id unique; expose as `tags` array trên API |
| comments | id, document_id, user_id, body plain text, status visible/hidden/spam/deleted, created_at, updated_at; không hard-delete audit trail |
| comment_mentions | comment_id + mentioned_user_id unique; username immutable để mention không đổi nghĩa |
| document_likes | document_id + user_id unique, created_at |
| reports | id, comment_id, reporter_id, reason enum spam/abuse/other, details, status open/resolved/dismissed, resolution nullable, handled_by nullable, created_at, handled_at nullable; chặn duplicate report open cùng user/comment |
| interaction_logs | id, event_type search/click, user_id nullable, query_string, clicked_doc_id nullable FK, timestamp, search_event_id nullable FK self, actor_key, request_key nullable, result_doc_ids JSON array (chỉ search); request_key unique theo actor/event khi có |
| view_events | id, document_id, user_id nullable, actor_key, navigation_id UUID, timestamp; unique(actor_key, document_id, navigation_id) |
| audit_logs | id, actor_id nullable, action, entity_type, entity_id nullable string, before JSON nullable, after JSON nullable, timestamp; redact password/session/secrets |
| app_settings | key, value JSON; whitelist registration_enabled bool, comments_enabled bool, site_name string, site_description string |

Quyết định dữ liệu:

- `documents.content` là plain text/Markdown nguồn; API detail thêm `rendered_content` là HTML được backend render rồi sanitize bằng allowlist. Không chèn raw Markdown/HTML chưa sanitize vào DOM. Tắt raw HTML trong Markdown parser; sanitize cả URL protocols và HTML sinh ra.
- Import mapping: `title -> title`, `text -> content`, `url -> source_url`; sinh UUID ổn định từ source_url hoặc unique upsert theo source_url, không dùng id đếm của crawler làm global ID.
- `author` của bài import là `Wikipedia contributors`, không giả tác giả là người import. `created_by` ghi người thêm vào Folio nếu có.
- Nguồn chưa có ngày xuất bản: `created_at` là ngày thêm vào Folio, UI gọi là Added; không bịa ngày xuất bản gốc. Giữ source URL, attribution và license thực sự xác minh được.
- `summary` trích nội dung có nghĩa; category/tags có mapping kiểm chứng trên 100 bài, không random nhãn.
- DB normalize tags qua join table, API vẫn có trường `tags`; tài liệu schema ghi mapping để đáp ứng yêu cầu đề.
- Delete document là soft-delete; API DELETE + public exclusion vẫn phải hoạt động đầy đủ. Comments/likes/logs giữ quan hệ lịch sử; các mutation mới trên document ẩn/xóa bị chặn. Không có restore UI trong scope.
- Xóa category/tag đang được dùng trả 409 có thông báo thay vì cascade xóa nội dung. Cho đổi category/tags của document trước khi xóa taxonomy.
- Likes count và comments count tính từ dữ liệu, không cần cột counter riêng. `views_count` tăng atomic cùng transaction tạo `view_events` mới.
- Index cần có: document(status, deleted_at, created_at, id), category_id, join keys, comment(document_id,status,created_at), log(event_type,timestamp), log(search_event_id), report(status,created_at); unique constraints cho identity/likes/mentions/idempotency.
- Không ghi lại IP, password hoặc token trong analytics/audit. Text query là dữ liệu người dùng nhập, khi hiển thị phải escape.

## 4. Auth và RBAC

Session cookie `folio_session`: random opaque token ít nhất 256 bit, HttpOnly, SameSite=Lax, Path=/; Secure ở production. Server lưu hash token. Không dùng localStorage cho auth token. Không bật wildcard credentialed CORS; ưu tiên same-origin.

`GET /auth/session` tạo guest session nếu chưa có, trả user null cùng csrf_token. Guest dùng được search/view logging. Mọi POST/PATCH/PUT/DELETE từ browser cần `X-CSRF-Token`, kể cả login/register/anonymous events. Validate token với session và Origin khi có. Token không nằm trong URL.

Login/register rotate session cookie và csrf token; giữ actor_key nếu cần liên kết search cùng trình duyệt. Logout hủy session cũ, tạo guest session mới. Đổi mật khẩu hủy sessions còn lại và rotate session hiện tại. Không lưu password dạng plain; dùng Argon2id hoặc tương đương đã được thư viện hỗ trợ. Login có throttling cơ bản và error chung cho credential sai.

`get_current_user` đọc user active và quyền hiện tại từ DB mỗi request cần quyền. Thay role, permissions, disable hoặc commenting suspension có hiệu lực mà không phải đợi hết hạn token.

| Permission | member | content_manager | moderator | data_seo | super_admin |
|---|---|---|---|---|---|
| documents:write | - | yes | - | - | yes |
| taxonomy:write | - | yes | - | - | yes |
| moderation:manage | - | - | yes | - | yes |
| seo:write | - | - | - | yes | yes |
| analytics:read | - | - | - | yes | yes |
| users:manage | - | - | - | - | yes |
| roles:manage | - | - | - | - | yes |
| audit:read | - | - | - | - | yes |
| settings:write | - | - | - | - | yes |

Đây là defaults seed. Super Admin được chỉnh effective permissions của các role khác qua giao diện; mọi role staff vẫn có quyền đọc/like/comment/sửa profile như member. Không biến tên role thành điều kiện duy nhất trong UI/backend; dùng permission keys. Chặn demote/disable/delete active super_admin cuối cùng, kể cả hai request đồng thời. Super_admin có quyền quản trị được bảo vệ, không có toggle tự khóa toàn hệ thống.

Comment own-edit/delete dựa trên owner id, không phải quyền sửa mọi comment. Moderator chỉ quản lý trạng thái, không giả làm tác giả để sửa nội dung.

Dependency exports:

```python
get_db()                         # yield SQLAlchemy Session; rollback/close an toàn
get_session_context()            # session, actor_key, optional user
get_current_user()               # yêu cầu login + active
require_permission(key)          # FastAPI dependency factory
require_any_permission(*keys)    # cho danh sách nội dung staff dùng chung
write_audit(db, actor, action, entity_type, entity_id, before=None, after=None)
```

Mutation nghiệp vụ + audit commit chung transaction; helper audit không tự commit. Foundation ghi chính xác import paths và transaction convention vào status trước freeze.

## 5. Auth/profile endpoints — Foundation

`UserSelf = {id,email,username,display_name,bio,role_key,permissions:[],is_active,commenting_suspended_until,created_at}`.

| Method/path | Request | Response/behavior |
|---|---|---|
| GET /auth/session | none | `{user:UserSelf\|null,csrf_token}`; tạo guest session cần thiết |
| POST /auth/register | `{email,username,password,display_name}` | 201 `{user,csrf_token}`; role luôn member; chỉ khi registration_enabled |
| POST /auth/login | `{email,password}` | `{user,csrf_token}`; rotate session; generic invalid credentials |
| POST /auth/logout | none | `{user:null,csrf_token}`; rotate về guest |
| PATCH /auth/profile | `{display_name?,bio?}` | UserSelf; email/username/role không editable ở endpoint này |
| POST /auth/password | `{current_password,new_password}` | `{user,csrf_token}`; rotate + revoke other sessions |

Frontend phải refresh CSRF value từ response, không tái dùng token trước rotation. Staff thay đổi email không thuộc scope; admin quản lý active/role. Có thể thêm admin create user nếu cần nhưng chỉ sau khi coordinator cập nhật contract, không bắt buộc khi đã có register.

## 6. Library/engagement/events endpoints — Backend Library

`Taxon = {id,name,slug}`.

`DocumentSummary = {id,title,summary,author,created_at,updated_at,published_at,views_count,likes_count,comments_count,category:Taxon,category_id,tags:Taxon[],cover_image_url,cover_image_alt,source_url}`.

`DocumentDetail = DocumentSummary + {content,rendered_content,source_license,source_attribution,seo_title,seo_description,seo_keywords,liked_by_me}`. `liked_by_me=false` cho guest.

`CommentPublic = {id,document_id,author:{id,username,display_name},body,mentions:[{id,username,display_name}],created_at,updated_at,can_edit,can_delete}`. Public chỉ thấy visible, không leak trạng thái hidden/spam qua metadata/list count.

| Method/path | Request | Response/behavior |
|---|---|---|
| GET /settings/public | none | `{site_name,site_description,registration_enabled,comments_enabled}`; fields allowlisted |
| GET /categories | page,page_size | paginated Taxon + description + published_document_count |
| GET /tags | q?,page,page_size | paginated Taxon |
| GET /documents | q?, category_id?, tag_ids? CSV UUID, date_from?,date_to?,sort (newest/oldest/title),page,page_size | paginated DocumentSummary + `query`, `search_event_id` (UUID hoặc null); multi-tag là AND; q tìm title/summary/content case-insensitive |
| GET /documents/{id} | none | DocumentDetail, không tăng view bằng GET |
| POST /documents/{id}/views | `{navigation_id}` | `{views_count}`; idempotent theo actor/document/navigation; chỉ published |
| PUT /documents/{id}/like | none | `{liked_by_me:true,likes_count}`; login; idempotent |
| DELETE /documents/{id}/like | none | `{liked_by_me:false,likes_count}`; login; idempotent |
| GET /documents/{id}/comments | page,page_size | paginated CommentPublic, oldest first + id |
| POST /documents/{id}/comments | `{body}` | 201 CommentPublic; login; comments_enabled + không suspended; derive mentions server-side |
| PATCH /comments/{id} | `{body}` | CommentPublic; owner only, visible only; rederive mentions; same anti-spam checks |
| DELETE /comments/{id} | none | 204; owner only; soft-delete; owner được xóa cả khi đang suspended |
| GET /users/mentions | q minimum 2,page,page_size max 10 | login; only `{id,username,display_name}`, active users; không trả email |
| POST /comments/{id}/reports | `{reason,details?}` | 201 `{id,status:"open"}`; login; visible comment + published document; duplicate open -> 409 |
| POST /events/clicks | `{search_event_id,document_id,request_key}` | 201 `{id}`; idempotent retry trả cùng id; ràng buộc phía dưới |

Thứ tự động routes phải không nuốt literal routes. Comments/likes/report endpoints đều kiểm tra parent document published và chưa deleted trước trả dữ liệu hoặc ghi.

### Logging semantics đã chọn

- Mỗi GET `/documents` thành công có q không rỗng sau trim ghi một **search** event: query_string, current user_id hoặc null, timestamp UTC, clicked_doc_id=null, result_doc_ids của trang trả về, actor_key từ session.
- Pagination/filter với q được tính là một search request mới. Dashboard ghi nhãn **Search requests**, không gọi đó là unique searches hay unique users.
- Duyệt Library không có q không ghi search event; `search_event_id=null`.
- Search event id trả về cùng results; frontend gắn id vào link kết quả và route context. Click từ kết quả gọi `/events/clicks`; direct URL/category browsing không gửi fake click.
- Click endpoint xác minh search event đúng event_type, cùng actor_key, tài liệu thuộc result_doc_ids và vẫn published. query_string copy từ event gốc, không tin chuỗi do client gửi. user_id lấy session hiện tại.
- Click tạo **row riêng**, không overwrite search row: đủ query_string, clicked_doc_id, timestamp, user_id, search_event_id. Search và click đều có thể truy vết.
- request_key UUID cố định cho một thao tác click và retry; gửi lại không tăng duplicate. Frontend không chặn mở tài liệu nếu logging lỗi; có thể retry một lần với cùng key, không tạo key mới cho retry.
- View được ghi khi detail đã tải thành công và đang hiển thị. Một navigation dùng một navigation_id; rerender hoặc retry không tăng view lần nữa. F5 là navigation mới. Click không tự tăng view.
- Guest session vẫn có actor_key server-issued. Client không tự khai user_id hoặc actor_key.

## 7. Admin endpoints — Backend Admin

Tất cả prefix `/admin`. List endpoints dùng pagination chung. Không dựa vào việc ẩn nút để bảo vệ quyền.

### Content và taxonomy

`AdminDocument = DocumentDetail + {status,created_by,deleted_at}`.

`DocumentWrite = {title,content,summary,category_id,tag_ids:[],author,cover_image_url?,cover_image_alt?,source_url?,source_license?,source_attribution?}`. Create luôn draft. `author` mặc định display_name hiện tại nếu bỏ trống; chỉ có các fields cho phép. source/license không được bịa khi import.

| Method/path | Permission | Request/response |
|---|---|---|
| GET /admin/documents | documents:write OR seo:write | filters q,status,category_id,page,page_size; paginated summaries + status; exclude soft-deleted |
| GET /admin/documents/{id} | documents:write OR seo:write | AdminDocument |
| POST /admin/documents | documents:write | DocumentWrite -> 201 AdminDocument |
| PATCH /admin/documents/{id} | documents:write | subset DocumentWrite -> AdminDocument; status/SEO excluded |
| PATCH /admin/documents/{id}/status | documents:write | `{status:"draft"\|"published"}` -> AdminDocument; validate required content trước publish |
| DELETE /admin/documents/{id} | documents:write | 204 soft-delete + audit |
| GET /admin/categories | taxonomy:write OR documents:write OR seo:write | paginated categories gồm cả chưa có bài published |
| GET /admin/tags | taxonomy:write OR documents:write OR seo:write | q?, paginated tags gồm cả chưa dùng |
| POST /admin/categories | taxonomy:write | `{name,slug?,description?}` -> 201 category |
| PATCH /admin/categories/{id} | taxonomy:write | subset -> category |
| DELETE /admin/categories/{id} | taxonomy:write | 204 hoặc 409 đang được dùng |
| POST /admin/tags | taxonomy:write | `{name,slug?}` -> 201 tag |
| PATCH /admin/tags/{id} | taxonomy:write | subset -> tag |
| DELETE /admin/tags/{id} | taxonomy:write | 204 hoặc 409 đang được dùng |

### Users, permissions, audit, settings

| Method/path | Permission | Request/response |
|---|---|---|
| GET /admin/users | users:manage | q,role_key,is_active,page,page_size -> paginated UserSelf; no hashes/sessions |
| PATCH /admin/users/{id} | users:manage | `{role_key?,is_active?}` -> user; invariant active admin cuối |
| GET /admin/roles | roles:manage | `{items:[{key,label,permissions:[],protected:boolean}]}` |
| GET /admin/permissions | roles:manage | `{items:[{key,description}]}` |
| PUT /admin/roles/{key}/permissions | roles:manage | `{permissions:[]}` -> role; validate catalog; protected super_admin không thể revoke |
| GET /admin/audit-logs | audit:read | actor_id?,action?,date_from?,date_to?,page,page_size -> redacted logs |
| GET /admin/settings | settings:write | object đúng 4 settings whitelisted |
| PATCH /admin/settings | settings:write | subset object -> object; type/length validation + audit |

Assign role và thay permission đều có audit. Permission update của role đang dùng phản ánh trên request kế tiếp; frontend refresh session khi mở trang admin/nhận 403.

### Moderation

| Method/path | Permission | Request/response |
|---|---|---|
| GET /admin/comments | moderation:manage | status?,q?,document_id?,page,page_size -> items có body, author, document title/id, status |
| PATCH /admin/comments/{id}/status | moderation:manage | `{status:"visible"\|"hidden"\|"spam",reason?}` -> comment; không resurrect owner-deleted |
| GET /admin/reports | moderation:manage | status?,page,page_size -> report + comment context + reporter safe identity |
| PATCH /admin/reports/{id} | moderation:manage | `{action:"dismiss"\|"hide_comment"\|"mark_spam",resolution?}` -> report; action và trạng thái comment thay đổi atomic |
| PATCH /admin/users/{id}/commenting | moderation:manage | `{suspended_until:timestamp\|null,reason}` -> `{id,commenting_suspended_until}`; không đổi role/is_active |

Spam control phải chạy thật: cấu hình server-side tối thiểu giới hạn tần suất comment, chặn comment trùng gần nhau và suspension. Bản local single-process có thể dùng limiter memory cho login, nhưng comment rate/duplicate kiểm tra DB để không mất trạng thái khi reload. Rate limit trả 429 + Retry-After. Không thêm captcha hoặc ML spam detection.

### SEO và analytics

| Method/path | Permission | Request/response |
|---|---|---|
| PATCH /admin/documents/{id}/seo | seo:write | `{seo_title?,seo_description?,seo_keywords?:[],cover_image_alt?}` -> SEO fields; không được đổi body/status |
| GET /admin/analytics/overview | analytics:read | date_from?,date_to?, mặc định 30 ngày UTC -> schema dưới |

Analytics response:

```json
{
  "period": {"date_from": "2026-10-01", "date_to": "2026-10-31", "timezone": "UTC"},
  "totals": {"published_documents": 100, "search_requests": 0, "result_clicks": 0, "document_views": 0},
  "daily": [{"date": "2026-10-01", "search_requests": 0, "result_clicks": 0, "document_views": 0}],
  "top_queries": [{"query_string": "machine learning", "search_requests": 1, "result_clicks": 1}],
  "top_documents": [{"id": "uuid", "title": "...", "document_views": 1, "result_clicks": 1}]
}
```

Ví dụ là schema minh họa, không được seed các con số trên thành analytics giả. `published_documents` là count hiện tại; các totals còn lại theo period. daily điền zero cho ngày không event. Giới hạn period tối đa 366 ngày. Top lists tối đa 10, thứ tự ổn định. Không tính CTR trong MVP để tránh nhầm request/page/click denominator. SEO title/meta description cập nhật khi mở detail; do hash routing client-rendered, không hứa khả năng crawl/index hoặc SSR. OG/social preview theo từng document nằm ngoài scope này.

## 8. Frontend core API — Foundation tạo trước khi chia nhánh

Module contracts cụ thể:

```javascript
// src/frontend/core/api.js
export class ApiError extends Error { /* status, code, fields */ }
export async function api(path, {method='GET', query, body, signal} = {}) {}
// path tương đối /api/v1, ví dụ api('/documents', {query:{page:1}})
// serialize query bỏ null/undefined/empty; credentials same-origin;
// JSON body; attach current CSRF cho unsafe methods; handle 204;
// abort không biến thành toast lỗi; không auto-retry non-idempotent writes.

// src/frontend/core/session.js
export async function refreshSession() {} // update in-memory state/CSRF
export function getSession() {} // {user, csrf_token}
export function can(permission) {} // effective permissions
export function subscribeSession(listener) {} // returns unsubscribe
// Foundation định nghĩa internal setter dùng bởi login/logout/core api;
// tránh cycle: token state tách module hoặc api nhận token getter.

// src/frontend/core/router.js
export function navigate(path) {} // '#/...' hash route, same-tab
// routeContext: {path, params, query:URLSearchParams, signal:AbortSignal}
// mỗi navigation abort route cũ; pages cần cleanup listeners/timers.

// src/frontend/core/ui.js
export function notify(message, {kind='info'} = {}) {}
export async function confirmAction({title, message, confirmLabel, destructive}) {}
export function renderPagination(container, {page,pageSize,total,onChange}) {}
export function renderError(container, error, {onRetry} = {}) {}
export function renderEmpty(container, {title,description,action} = {}) {}

// src/frontend/public/index.js và src/frontend/admin/index.js
export const routes = [
  // {path:'/library', render:async (container, routeContext) => cleanupOrVoid}
];
// Foundation router hỗ trợ :id segments. Pages dùng DOM APIs/textContent
// cho plain text. Chỉ rendered_content đã sanitize được insert HTML.
```

`app.js` merge cả hai routes manifests; shell lấy session/settings, cập nhật nav theo permissions và xử lý missing route. Foundation tạo stubs trong các index module để app chạy; từng worker sở hữu index của lane mình sau gate. Guard UI không thay cho backend authorization.

Routes:

```text
#/library?q=&category_id=&tag_ids=&date_from=&date_to=&sort=&page=
#/documents/:id?search_event_id=<optional>
#/login?next=<validated local hash route>
#/register
#/profile
#/admin                             # redirect đến route đầu tiên được phép
#/admin/documents
#/admin/documents/new
#/admin/documents/:id/edit
#/admin/taxonomy
#/admin/comments
#/admin/reports
#/admin/seo
#/admin/seo/:id
#/admin/analytics
#/admin/users
#/admin/roles
#/admin/audit
#/admin/settings
```

`next` chỉ cho path nội bộ bắt đầu `/`, chặn `//`, scheme và route lạ; không open redirect. API base dùng same-origin, giữ ý nghĩa thay đổi đang có ở app.js. Không hardcode `http://127.0.0.1:8000` trong links/API khi app phục vụ port khác.

### Shared visual interface

Foundation sở hữu tokens `--color-bg`, `--color-surface`, `--color-text`, `--color-muted`, `--color-accent`, `--color-border`, `--color-danger`, `--font-ui`, `--font-reading`, spacing/radii/focus tokens.

Shared CSS `.btn`, `.btn-primary`, `.btn-danger`, `.field`, `.input`, `.select`, `.badge`, `.table`, `.pagination`, `.notice`, `.dialog`, `.spinner`. Foundation ghi markup dùng các classes này trong `docs/ui-components.md`; hai frontend worker không tự định nghĩa lại cùng class.

- Public styles chỉ dưới `.public-page` hoặc prefix `.library-*`, `.document-*`, `.auth-*`.
- Admin styles chỉ dưới `.admin-page` hoặc prefix `.admin-*`.
- Không sửa global `body`, `button`, `input`, token `:root` từ lane CSS.
- File `style.css` import public/admin styles có sẵn stub. Các worker chỉ chỉnh file CSS lane mình.
- Modules render có `AbortSignal`, discard stale fetch, cleanup listener/subscriptions khi đổi route.
- Trước chuyển trang khỏi dirty editor, confirm; lưu thành công reset dirty; API lỗi không xóa input.
- Like click, comment submit và các mutations disable khi đang pending; thành công mới cập nhật state hoặc rollback khi optimistic thất bại.

## 9. Seed contract và portability

- `fixtures/folio/documents.jsonl`: đúng 100 bài nội dung thật, schema normalized, source_url/author/summary/category/tags đầy đủ. Không cần commit 140MB data gốc hoặc vector DB.
- Core tests và fixture phải chạy được ở worktree chỉ có tracked files; không đọc ngầm `data/raw` của checkout gốc. Chỉ bước chuẩn bị fixture ở Foundation dùng dataset lớn hiện có.
- Có thể thêm 3–5 draft riêng để demo workflow, tách fixture hoặc status rõ; không tính vào 100 bài published.
- Không invent image nguồn. Giữ cover nullable; bổ sung một vài hình liên quan có license được ghi hoặc sơ đồ tự tạo được ghi rõ, lưu local để demo detail có images. Không đặt ảnh ngẫu nhiên chỉ để đủ trường.
- `fixtures/folio/SOURCES.md` ghi nguồn bài/hình, cách trích xuất, attribution/license xác minh được. Nếu thiếu license info, thực hiện xác minh trước bàn giao và ghi unresolved nếu chưa được.
- `scripts/seed_folio.py` mặc định đọc fixture portable, chỉ thêm record chưa có theo stable id/source_url. Không overwrite tài liệu đã sửa; flags destructive không có mặc định.
- Seed có transactions, kiểm tra taxonomy, schema/summary/content không rỗng; chạy hai lần không tăng count users/docs/tags/likes/logs.
- Role/permission seed tách policy: lần đầu thêm defaults; lần chạy sau không reset các thay đổi permission do admin đã lưu.
- Tài khoản local demo cho 5 roles, địa chỉ dưới domain `.test`, password lấy `DEMO_PASSWORD` môi trường. Seed demo accounts từ chối chạy production; không in password trong log test/audit.
- Không cần fake search logs. Seed có thể thêm vài comment/report demo ghi rõ; analytics proof tạo từ thao tác test/demo thật.

## 10. Kiểm thử và migration contract

- Foundation tạo tests dùng `TEST_DATABASE_URL` trỏ DB có tên riêng mang hậu tố/prefix test; guard chống chạy DDL/reset vào DATABASE_URL hoặc database không xác nhận test.
- Worker dùng DB test riêng theo lane, không chạy migrations/reset đồng thời trên một DB.
- Mọi test route đều đi qua app thực/TestClient và DB PostgreSQL thật; fake search model được chấp nhận chỉ để bảo đảm legacy không init.
- Fixtures auth dùng session cookie/CSRF flow thật hoặc helpers có test riêng kiểm chứng. Negative RBAC tests gọi API trực tiếp.
- Alembic initial migration chứa mọi model đã freeze. Sau Wave 1 chỉ Integrator sinh migration bổ sung; không bốn Alembic heads độc lập.
- Tests quan trọng: register role escalation; expired/disabled session; CSRF missing; cross-user comment edit; draft visibility trên mọi related endpoints; last admin concurrency; duplicate like/seed/click/view; search/click ownership; hidden/spam comments; SEO role không sửa body/status; migration fresh DB; app không có ML.
- UI test ít nhưng có ý nghĩa: search -> detail; auth -> profile/comment; create -> publish; moderation; roles forbidden; runtime errors. Screenshots desktop bổ trợ functional tests, không thay thế.

## 11. Freeze checklist của Foundation

- [ ] Endpoint naming, schema, enum, permission keys và response errors có trong code/stubs hoặc OpenAPI draft.
- [ ] Toàn bộ ORM models, relations, FK/index/unique constraints và migration tồn tại.
- [ ] Audit transaction, auth dependency và session/CSRF flow đã được worker dùng thử qua ví dụ/test.
- [ ] Frontend imports/helpers/routes signatures và component classes tồn tại, không chỉ prose.
- [ ] Fixture portable, source notes, seed idempotent và setup test DB xong.
- [ ] Status ghi baseline commit/hash nếu có, changed contract notes và READY hoặc blocker thật.

Khi tất cả pass, đổi nhãn đầu tài liệu từ `v1 proposal` thành `v1 frozen` kèm ngày/commit. Sau đó mới bắt đầu bốn prompt song song.
