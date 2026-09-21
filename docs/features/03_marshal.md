# Marshal 物件列表頁（marshal blueprint）

> **注意**：本章記錄的是重構前（commit `c7f91a4`，2026-09-21）的狀態，檔案路徑為舊位置（`app/routes/…`、`app/modules/…`）。新位置請對照 `docs/ARCHITECTURE.md` §6「新舊路徑對照」；功能與行為在重構後完全相同。

## 概要

### 位置與註冊
- 程式檔：`app/routes/marshal/marshal_routes.py`。
- Blueprint 物件：`marshal_bp = Blueprint('marshal', __name__, template_folder='templates', static_folder='static')`，blueprint 名稱為 **`marshal`**，無 `url_prefix`。所有 endpoint 名稱皆為 `marshal.<函式名>`。
- 註冊：`app/routes/__init__.py` 的 `register_routes(app)` 以 `app.register_blueprint(marshal_bp)` 註冊（順序在 `basic_bp` 之後、`detect_bp` 之前）。`app/routes/marshal/__init__.py` 為空檔。
- 同一套件目錄 `app/routes/marshal/` 內另有 `object_routes.py`（`objects_bp = Blueprint('marshal_bp', __name__)`，負責 `/object/<name>` 物件詳細頁與 `/api/object/*`）。兩者共用 `templates/` 與 `static/` 目錄，但是**不同 blueprint**（名稱分別是 `marshal` 與 `marshal_bp`），物件詳細頁由別章記錄。本章模板中的 `url_for('marshal_bp.object_detail_tns_format', ...)`／`url_for('marshal_bp.object_detail_generic', ...)` 指向的就是 `objects_bp`（已確認存在：`object_routes.py:40` 與 `:255`）。
- 靜態檔解析：`app/main.py` 以自訂 `@app.route('/static/<path:filename>', endpoint='static')` 依序掃描 `_BLUEPRINT_STATIC_DIRS`（含 `routes/marshal/static`），所以模板中 `url_for('static', filename='css/marshal/marshal.css')` 會解析到 `app/routes/marshal/static/css/marshal/marshal.css`；`_base.css` 的背景圖 `../../photo/background.png` 對應 `app/routes/marshal/static/photo/background.png`。

### 職責
- 網站的主要暫現源清單頁 **`/marshal`**（頁面標題「Transient Marshal」）：顯示總數、最後一次 TNS 同步狀態、AT/SN 與各狀態計數、搜尋列、進階篩選 modal、Cards/Table 兩種檢視、排序、分頁，以及右側四個儀表板 widget（Top Viewed、Pinned、Recent Comments、Recent TNS Updates）。
- 右側 widget 專用的 4 支 JSON API `/api/marshal/*`。
- 清單本身的資料載入（分頁/篩選/排序）、統計數字、分類清單、狀態標籤查詢與 tags 編輯，**都不在本 blueprint**，由 `marshal.js` 呼叫其他 blueprint：`web_api`（`/api/objects`、`/api/stats`、`/api/object-tags`、`/api/classifications`）與 `marshal_bp`（`/api/object/<name>/edit`）。本章只記錄 `marshal.js` 如何使用它們。

### 與其他區塊的關係
- 進入點：navbar「Marshal」（`app/routes/basic/templates/_navbar.html:35`）、首頁 `home.html:65`、`:119`、物件詳細頁的 breadcrumb（`object_detail.html:35`）、物件詳細頁找不到物件／載入錯誤時的 `redirect(url_for('marshal.marshal'))`（`object_routes.py:221, 253, 340, 372`）、物件刪除成功後 `window.location.href = '/marshal'`（`object_detail.js:4796`）。
- 出口：每個物件連結都以新分頁開啟 `/object/<year><letters>` 或 `/object/<name>`（`marshal_bp`，別章）。
- 資料來源：`app/modules/database/transient.py`（PostgreSQL `transient` schema）。

### 全域 hook（`app/main.py`，對本章所有 route 生效）
- `_enforce_allowed_host`：`request.host` 不在 `_ALLOWED_HOSTS`（`APP_BASE_URL` 的 netloc；DEBUG 時加上 localhost/127.0.0.1）→ `abort(404)`。
- `refresh_user_session`（來自 `routes/auth/auth_routes.py`，以 `app.before_request` 全域註冊）：已登入時每個請求由 DB 重新同步 `session['user']` 的 `is_admin`、`is_great_lab_member`、`picture`，並設定 `g.current_user`。
- `_block_pipe_in_api_params`：路徑以 `/api/` 開頭時，query string / form / JSON 任一值含 `|` → 400 `{"error": "Invalid character '|' is not allowed"}`。影響 `/api/marshal/top-viewed?mode=` 等。
- `_handle_param_out_of_range`：`ParamOutOfRangeError` → 400 `{"error": "<msg>"}`（`/api/objects` 的數值參數驗證會用到）。
- `_add_isolation_headers`：加上 `Cross-Origin-Opener-Policy: same-origin`、`Cross-Origin-Resource-Policy: same-origin`。

### 物件狀態（status）、tag、tags、pin、flag 概念

| 概念 | 儲存位置 | 值 | 對外欄位／UI |
|---|---|---|---|
| **狀態 status** | `transient.objects.status TEXT NOT NULL DEFAULT 'Inbox' CHECK (status IN ('Inbox','Snoozed','Follow-up','Finish'))`（`_Kinder_Database/SQL/transient.sql:26`；有 `objects_status_idx`） | `Inbox` / `Follow-up` / `Finish` / `Snoozed` | 對外以單值別名 **`tag`** 表示：`OBJECT_COMPAT_COLS`（`app/modules/database/__init__.py:439`）的 `CASE o.status WHEN 'Finish' THEN 'finished' WHEN 'Follow-up' THEN 'followup' WHEN 'Snoozed' THEN 'snoozed' ELSE 'object' END AS tag`；`/api/object-tags` 用同一個 CASE。UI 名稱：`object`→「Inbox」、`followup`→「DETECT Follow up」、`finished`→「Finished」（UI 以 Jinja 註解隱藏，DB 值保留）、`snoozed`→「Snoozed」。卡片／表格列加 class `tag-<alias>`，徽章 `.tag-badge.<alias>`。 |
| 狀態反向映射 | `transient.py:1292 _STATUS_MAP` | `'object'`/`'clear'`→`'Inbox'`、`'followup'`→`'Follow-up'`、`'finished'`→`'Finish'`、`'snoozed'`→`'Snoozed'`（也接受新式值本身） | 供 `update_object_status()`（`POST /api/object/<name>/status`，別章）。本頁不改狀態。 |
| 狀態計數 | `get_marshal_overview_stats()`（SSR）與 `get_tag_statistics()`（`/api/stats`） | 皆以 `status` 做 `COUNT(*) FILTER` | `#inboxCount`、`#followupCount`、`#snoozedCount`（`#finishedCount` 被註解） |
| 狀態篩選 | `_build_where(tag=...)`（`transient.py:1008`） | `object`→`o.status='Inbox'`、`followup`→`'Follow-up'`、`finished`→`'Finish'`、`snoozed`→`'Snoozed'`；`flag`→`EXISTS (SELECT 1 FROM transient.cross_matches c WHERE c.obj_id=o.obj_id AND c.status='Flagged')` | 狀態列點擊、`#tagFilter` 下拉 |
| **自訂標籤 tags** | `transient.objects.tag TEXT[] NOT NULL DEFAULT '{}'`（GIN index `objects_tag_idx`） | 任意字串陣列；寫入時 `api_edit_object` 以 `^[A-Za-z0-9,\s\-_]+$` 驗證 | 對外欄位 **`tags`** = `array_to_string(o.tag, ', ')`。前端 `buildObjectTags()` 把 `EP` 開頭者排前並加 class `ep`（Einstein Probe 別名），其餘 `custom-tag`／`mini-tag`。只有 `visibility.tags` 為真時 SSR 才輸出；admin 在 Table 檢視按 Edit 透過 `POST /api/object/<name>/edit` 修改。 |
| **pin** | `transient.objects.pin BOOL NOT NULL DEFAULT FALSE` | true/false | `OBJECT_COMPAT_COLS` 輸出 `o.pin::int AS pin`。切換：`toggle_object_pin()`（`transient.py:2368`，經 web_api `POST /api/object/<name>/toggle_pin`，admin，別章）。本章 `GET /api/marshal/pinned-objects` 列出 `pin = TRUE` 者。 |
| **flag** | 實際讀寫在 `transient.cross_matches.flag BOOLEAN`（由 `_ensure_cross_matches_flag_column()` 動態 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 補上；`get_object_flag_status()`／`update_object_flag_by_name()`／`get_flagged_objects()`） | true/false | 本頁沒有 flag 切換 UI，只有 `#tagFilter` 的「Flagged」選項。**三處定義不一致**：`get_marshal_overview_stats()` 的 `flag_count` 用 `objects.tag @> ARRAY['flag']`；`_build_where(tag='flag')` 用 `cross_matches.status = 'Flagged'`；真正的 flag 切換寫 `cross_matches.flag`。詳見「已知問題」。 |
| 瀏覽次數 | `transient.object_views`（`obj_id` PK、`counts`、`last_view`）、`transient.object_views_detail`（每次瀏覽一列：`obj_id`、`usr_id`、`view_time`） | — | 由物件詳細頁的 `TNSObjectDB.log_object_view()` 寫入（別章）；本章 Top Viewed／Pinned widget 讀取。 |

## 頁面（HTML routes）

### GET `/marshal` — `marshal.marshal`
- **路徑／方法**：`/marshal`，僅 GET（未指定 `methods`）。
- **權限**：**公開**（route 內沒有任何登入檢查，未登入也回 200）。頁面內容依 session 分級（判斷都在 route 與模板中）：

| 條件 | 判斷來源 | 開放的內容 |
|---|---|---|
| 匿名 | — | 標頭（標題、總數、最後同步）、搜尋列、Filters modal、Cards/Table 切換、排序、清單、分頁、通知、回頂端 |
| `session.user` 存在（任何已登入者，含 role=guest） | 模板 `{% if session.user %}` | AT/SN 數字列 `.type-stats-bar`、狀態列 `.status-list`、右側「Top Viewed + Pinned」widget |
| `visibility.comments_sidebar` | route：`can_see_restricted = is_admin or role in ('user', 'admin')` → **需登入且非 guest**（`role` 由 `auth.py:53 _user_row_to_dict` 依 `roles` 數值算出：≥50 `admin`、≥1 `user`、否則 `guest`；登入時寫入 `session['user']['role']`，`auth_routes.py:142`） | 右側「Recent Comments」與「Recent TNS Updates」widget（兩者包在同一個 `{% if visibility.comments_sidebar %}` 內） |
| `visibility.tags` | 同上條件 | SSR 卡片的 `.card-tags` 自訂標籤與 View 按鈕旁的 `.mini-tag` |
| `session.user.is_admin` | 模板 `{% if session.user and session.user.is_admin %}` → `<div data-admin="true">` → JS `window.isAdmin = true` | Table 檢視每列的「Edit」按鈕（編輯 tags） |

  未通過時沒有 redirect／flash，只是對應區塊不渲染。
- **輸入**：無。route 不讀任何 query string。（JS `performSearch()` 會用 `history.pushState` 在網址加上 `?search=<term>`，但沒有任何程式在載入時讀回它。）
- **處理流程**：
  1. `user = session.get('user', {})`；`role = user.get('role', 'guest')`；`is_admin = user.get('is_admin', False)`；`visibility = {'tags': can_see_restricted, 'comments_sidebar': can_see_restricted}`。（函式內又 `from flask import session` 一次，冗餘。）
  2. `stats = get_marshal_overview_stats()`（`transient.py:1127`，簽名 `get_marshal_overview_stats(cache_ttl: int = 30) -> dict`，無 docstring）。模組層 dict `_marshal_stats_cache = {'expires_at', 'value'}` 做 **30 秒 in-process 快取**，無任何失效鉤子。SQL：對 `transient.objects` 一次 `COUNT(*) FILTER`（`total_count`、`at_count`=`name_prefix='AT'`、`typed_count`=`type` 非空、`with_redshift`、`inbox_count`/`followup_count`/`finished_count`/`snoozed_count` 依 `status`、`flag_count`=`tag @> ARRAY['flag']`）；再一句 `SELECT COUNT(DISTINCT obj_id) FROM transient.photometry`。回傳 `total_count, at_count, classified_count(= total_count - at_count，注意不是 typed_count), inbox_count, followup_count, finished_count, snoozed_count, flag_count, tns_stats{total, with_photometry, classified(=typed_count), with_redshift, follow, finished, snoozed}`。
  3. 直接 SQL（`get_db_connection()`）讀 `transient.download_logs` 最新一列：`SELECT download_date, obj_import, obj_update, status, error_message ... ORDER BY download_date DESC LIMIT 1`。`download_date` 若無 tzinfo 視為 UTC，轉 UTC+8 後格式 `'%b%d %H:%M+08'`（例：`Sep21 14:30+08`）；`status` 小寫後含 `error` → `'failed'`，否則一律 `'completed'`（包含程式寫入的 `'In Progress'`；schema 註解的值為 `Success`/`Error`/`Retry-Success`）。組成 `last_sync_data = {time, status, imported(obj_import), updated(obj_update), errors(失敗時為 error_message，否則 None)}`。此段任何例外被 `except Exception: pass` 吞掉 → `last_sync=None`。
  4. 依 `total_count` 決定 SSR 預載策略：`<= 1000` → `initial_limit = min(total_count, 200)`、`use_api_mode = False`；`<= 5000` → `100`、`False`；`> 5000` → `0`、`True`（純 API 模式，不預載）。
  5. `initial_limit > 0` 時 `search_tns_objects(limit=initial_limit, sort_by='discoverydate', sort_order='desc')`；每筆若 `tag` 缺或 None 補 `'object'`（實際上 `OBJECT_COMPAT_COLS` 永遠有值，冗餘）。此段例外 → `initial_objects = []`、`use_api_mode = True`。
  6. `render_template('marshal.html', ...)`。
- **成功回應**：模板 `app/routes/marshal/templates/marshal.html`，HTTP 200。傳入變數：

| 變數 | 內容 | 模板實際使用 |
|---|---|---|
| `current_path` | `'/marshal'` | 模板本身未用；供 `_navbar.html` include 使用（navbar 的 Marshal 連結沒有 active 判斷，實際也沒用到） |
| `objects` | `search_tns_objects()` 回傳的 dict list（欄位見下） | 是：`{% for obj in objects %}` SSR 卡片；`{% if not objects %}` 決定是否輸出 `#loadingIndicator` |
| `tns_stats` | `stats['tns_stats']` | **否** |
| `at_count` / `classified_count` | AT 數／非 AT 數 | 是（`.type-stat.at` / `.type-stat.sn`） |
| `inbox_count` / `followup_count` / `snoozed_count` | 各狀態數 | 是（`#inboxCount` / `#followupCount` / `#snoozedCount`） |
| `finished_count` | Finish 數 | 只出現在 Jinja 註解 `{# ... #}` 內 → **未渲染** |
| `flag_count` | `tag @> ARRAY['flag']` 數 | **否** |
| `last_sync` | `None` 或 `{time, status: 'completed'|'failed', imported, updated, errors}` | 是（`#lastSync`、`.sync-status success/error/pending`；`pending` 分支實際不可達，因 status 只會是 completed/failed） |
| `total_count` | 物件總數 | 是（`.total-count`「N objects」；**JS 靠這段文字判斷載入模式**） |
| `use_api_mode` / `initial_limit` | 載入策略 | **否**（JS `checkObjectsCount()` 自行由 DOM 判斷） |
| `visibility` | `{'tags': bool, 'comments_sidebar': bool}` | 是 |

  `objects` 每筆 dict 的欄位由 `OBJECT_COMPAT_COLS` 定義：`obj_id, objid, kinder_id, name_prefix, name, ra, declination, redshift, type, typeid(NULL), reporting_group, reporting_groupid(NULL), source_group, source_groupid(NULL), discoverydate('YYYY-MM-DD HH24:MI:SS'，由 MJD 轉), discoverymag, discmagfilter, filter, reporters(逗號字串), time_received, internal_names(internal_name + ', ' + other_name), discovery_ads_bibcode, class_ads_bibcodes, creationdate, last_photometry_date, lastmodified, brightest_mag, brightest_abs_mag, pin(int), tags(逗號字串), tag(狀態別名), status, inbox(...)`。模板用到：`name, name_prefix, type, discoverydate, discoverymag, redshift, lastmodified, last_photometry_date, brightest_mag, brightest_abs_mag, tags, tag, ra, declination, source_group, time_received`。
- **失敗回應**：整個主體包在 `try` 內；任何例外 → `traceback.print_exc()`（stdout）、`flash('Error loading transient data.', 'error')`，仍回 **200** 並渲染同一模板：所有計數 0、`objects=[]`、`tns_stats={}`、`last_sync=None`、`total_count=0`、`use_api_mode=True`、`initial_limit=0`、`visibility` 照常。flash 由 `_navbar.html:151` 的 `get_flashed_messages(with_categories=true)` 顯示。
- **副作用**：只讀 `transient.objects`、`transient.photometry`、`transient.download_logs`；寫入 in-process 快取 `_marshal_stats_cache`。不寫檔、不呼叫外部服務、不啟動執行緒。

#### 頁面區塊與互動

| 區塊 | 元素 | 行為／呼叫／導向 |
|---|---|---|
| 標頭 `.panel-header` | `<h1>Transient Marshal</h1>`、`.total-count`「{{ total_count }} objects」、`.last-sync`（`#lastSync` 時間；`.sync-status.success`「(N new, M updated)」／`.sync-status.error`「(Failed)」；無紀錄時「Never」） | 純顯示。`.total-count` 之後會被 JS `updateCountersFromStats()`（`/api/stats`）及無篩選時的 `loadObjects()` 改寫。 |
| AT/SN 數字列 `.type-stats-bar`（需登入） | `.type-stat.at .type-number`、`.type-stat.sn .type-number` | JS 從 `/api/stats` 的 `at_count`/`classified_count` 更新。 |
| 狀態列 `.status-list`（需登入） | 三個 `.status-row.clickable`：Inbox（`#inboxCount`）、DETECT Follow up（`#followupCount`）、Snoozed（`#snoozedCount`）；Finished 列被 `{# #}` 註解 | `onclick="filterByStatus('object'|'followup'|'snoozed')"`：設定 `currentFilters.tag`、同步 `#tagFilter`、`currentPage=1`，API 模式 → `loadObjects(true)`（`/api/objects?tag=`）；DOM 模式 → `applyLocalStatusFilter()`。同一狀態再點 → `clearStatusFilter()`。顯示通知「Filtering <名稱> objects」。 |
| 搜尋列 `.search-input-group` | `#searchInput`（placeholder「Search by name」，Enter 觸發）、「Search」`performSearch()`、「Clear」`clearAllFilters()`、「Filters」`toggleAdvancedFilters()`（`#advancedToggle`） | 搜尋 → 強制 API 模式 → `/api/objects?search=`；Clear → 清空所有欄位與 `currentFilters` → `/api/stats` + 重載；Filters → 開關 `#advancedFilterModal`。 |
| `.advanced-filters`、`.admin-tools` | 空容器；`.admin-tools` 內只有一個空的 `{% if session.user and session.user.is_admin %}{% endif %}` | 死區塊。 |
| 檢視切換 `.view-toggle` | 「Cards」(`data-view="cards"`, 預設 active)、「Table」；「Compact」按鈕以 HTML 註解移除 | `switchView(view)`：切換 `#cardsView`(grid) / `#tableView`(block) / `#compactView` 顯示並重繪；純前端。 |
| 排序 `.sort-controls` | `#sortBy`：`lastmodified`「Last Update」(預設) / `last_photometry`「Last Photometry」/ `discovery_date`「Discovery Date」/ `magnitude`「Discovery Magnitude」/ `brightest_mag`「Brightest Mag」/ `brightest_abs_mag`「Brightest M」/ `redshift`「Redshift」；`#sortOrderBtn`（預設 desc） | `applySorting()` / `toggleSortOrder()`：API 模式 → `/api/objects?sort_by=<mapSortField()>&sort_order=`；DOM 模式 → `sortObjects()` 本地排序（redshift 缺值永遠排最後；magnitude 缺值以 99 代入）。 |
| 右側 widget「Top Viewed」（需登入） | `#topViewedMode`（`all`「All Time」/ `30days`「30 Days」；HTML 第一個 option 是 `all`，所以預設送 `mode=all`）、`#topViewedList` | `onchange="loadTopViewed()"` → `GET /api/marshal/top-viewed?mode=<mode>` → `renderTopViewed()`：排名、物件連結、`(type)`、mini-tags、眼睛圖示 + `view_count`。 |
| 右側 widget「Pinned」（需登入） | `#pinnedObjectsList` | `loadPinnedObjects()` → `GET /api/marshal/pinned-objects` → `renderPinnedObjects()`：排名、連結、type、mini-tags、view_count。 |
| 右側 widget「Recent Comments」（user/admin） | `#recentCommentsList` | `fetchDashboardWidgets()` → `GET /api/marshal/recent-comments` → `renderRecentComments()`：連結、type、mini-tags、日期、`"content" — user_name`。 |
| 右側 widget「Recent TNS Updates」（user/admin） | `#tnsWidgetTitle`、`#recentTnsUpdatesList` | `GET /api/marshal/recent-tns-updates` → `renderRecentTnsUpdates()`：`is_fallback` 為真時標題改「Recent TNS Objects」；每項顯示 `classified`／`new add` 徽章、「Classified as: <type>」／「Newly added」／「Updated: <changed_fields>」與相對時間（Nm ago / Nh ago / yesterday / 日期）。 |
| 上／下分頁列 `.pagination-container` | `#topPaginationInfo`／`#paginationInfo`「Showing a-b of N objects」、`#topPaginationControls`／`#paginationControls`（Prev / 頁碼（目前頁 ±3，最多 7 顆）/ … / Next）、`#topPageSizeSelect`／`#pageSizeSelect`（20 / 50(預設) / 100） | `changePage(n)`（會 `scrollIntoView` 到 `.view-controls`）、`changePageSize()`：API 模式 → `/api/objects?page=&per_page=`；DOM 模式本地切片。 |
| 載入指示 `#loadingIndicator.loading-overlay` | 只有 `objects` 為空時 SSR 輸出；否則 JS `showLoading(true)` 動態建立 | `loadObjects()` 期間顯示；15 秒逾時通知。 |
| 卡片檢視 `#cardsView.objects-grid` | SSR `.object-card.tag-<tag>`（`data-classification / data-discovery / data-tag / data-magnitude / data-redshift / data-lastmodified / data-lastphotometry / data-brightest-mag / data-brightest-abs-mag / data-tags`），或 API 模式由 `generateCardsView()` 以 innerHTML 重建。內容：物件名連結、分類徽章 `.classification-badge.<type>`、`.card-tags`（visibility.tags）、RA/Dec（3 位小數）、Discovery Mag / Brightest Mag / Redshift / Brightest M / Date / Source、狀態徽章 `.tag-badge`、`.last-update`（`time_received[:16]`）、View 按鈕（附 mini-tags） | 物件名與 View → 新分頁 `/object/...`（見「導向」）。DOM 模式下 `filterCardsView()` 以 `style.display`/`style.order` 控制 SSR 卡片的顯示與順序。 |
| 表格檢視 `#tableView` | `table.data-table`，`#tableBody` 由 `generateTableView()` 產生。欄位：Object Name（含 mini-tags）/ Class / RA (J2000) / Dec (J2000) / Discover Mag / Brightest Mag / Brightest M / Redshift / Discovery Date / Discoverer（截 30 字）/ Tag / Actions | Actions：「View」→ `/object/...`；`window.isAdmin` 時多一顆「Edit」→ `editTags(name)`。 |
| Compact 檢視 `#compactView` | 空容器；`generateCompactView()` 只在 `switchView('compact')` 時填入 | 入口按鈕被註解 → **UI 上到不了**。 |
| Advanced Filters modal `#advancedFilterModal`（`.modal-overlay.advanced-filter-overlay`） | Classification `#classificationFilter`（`multiple`，選項由 JS 填）、Status Tag `#tagFilter`（`''` All Status / `object` Inbox / `followup` DETECT Follow up / `snoozed` Snoozed / `flag` Flagged；`finished` 被註解）、Discovery Date Range `#dateFrom`/`#dateTo`（`type=date`）、Apparent Magnitude `#appMagMin`/`#appMagMax`（step 0.1）、Redshift Range `#redshiftMin`/`#redshiftMax`（step 0.001）、Discoverer/Survey `#discovererFilter`、Brightest Mag Range `#brightestMagMin`/`#brightestMagMax`、Brightest Abs Mag Range `#brightestAbsMagMin`/`#brightestAbsMagMax`、「Apply Filters」、「Clear All」、關閉 X | Apply → `applyAdvancedFilters(); toggleAdvancedFilters();` → 讀所有欄位進 `currentFilters` → `/api/objects?...`；Clear All → `clearAllFilters(); toggleAdvancedFilters();`；`#tagFilter` 另掛 `change` 事件直接呼叫 `filterByStatus()`/`clearStatusFilter()`（所以改下拉會立即重載，不必按 Apply）；點遮罩關閉。 |
| Upload TNS CSV modal `#uploadModalOverlay` | 「Upload TNS CSV Data」：說明文字、拖放區 `#fileDropZone`、`#csvFileInput`（accept .csv,.zip）、`#selectedFileInfo`、`#skipDuplicates`、`#validateData`、進度條 `#uploadProgress`、結果 `#uploadResult`、「Cancel」`closeUploadModal()`、「Start Upload」`startUpload()`（disabled）、「Remove」`clearSelectedFile()` | **死 HTML**：頁面上沒有任何開啟它的按鈕，且 `closeUploadModal`、`startUpload`、`clearSelectedFile` 在 `marshal.js` 中都**沒有定義**（若被觸發會 ReferenceError）。 |
| 通知 `#notificationContainer` | `showNotification(message, type)`：`.notification.notification-<info|success|warning|error>`，5 秒後移除 | — |
| 回頂端 `#backToTopBtn` | 捲動 > 300px 顯示，點擊平滑捲到頂 | — |
| 快捷鍵 | `Ctrl+Shift+R` → `forceRefreshAll()`（攔截並 `preventDefault`） | 清空所有篩選、強制 API 模式、重叫 `/api/stats` 與 `/api/objects`；通知「Forced complete refresh」。 |

#### 導向（連出）
- SSR 卡片（`marshal.html:289-306, 392-409`）：`obj.name` 長度 ≥ 4 且符合 `(\d{4})([a-zA-Z]+)` 且 **沒有** `name_prefix` → `url_for('marshal_bp.object_detail_tns_format', year=..., letters=...)`（`/object/<year><letters>`）；否則 `url_for('marshal_bp.object_detail_generic', object_name=obj.name)`（`/object/<name>`，用不含前綴的 `name`）；名稱長度 < 4 → 物件名連到 `url_for('marshal.marshal')`（本頁自己），View 按鈕仍連 `object_detail_generic`。皆 `target="_blank" rel="noopener noreferrer"`。
- JS 產生的連結（卡片／表格／compact／四個 widget）：以 `/(?:AT|SN)?(\d{4})([a-zA-Z]+)$/`（widget 用 `/(?:AT|SN)?(\d{4}[a-zA-Z]+)$/`）從完整名稱（`name_prefix + name`）擷取 → `/object/<year><letters>`；不符 → `/object/<encodeURIComponent(name)>`。皆新分頁。
- `quickView(name)`（未被呼叫）：`window.open('/object/...', '_blank')`。
- navbar（`_navbar.html`）連到其他頁。

## API 與動作端點

| 方法 | 路徑 | endpoint | 權限 | 輸入 | 成功回應 | 失敗回應 | 副作用 |
|---|---|---|---|---|---|---|---|
| GET | `/api/marshal/recent-comments` | `marshal.get_marshal_recent_comments` | **公開**（無任何檢查） | 無 | 200 `{"success": true, "comments": [ {…} ]}`，最多 5 筆 | 500 `{"success": false, "error": "<str(e)>"}` | 讀 `transient.comments` LEFT JOIN `auth.users`、`transient.objects`。無寫入。 |
| GET | `/api/marshal/recent-tns-updates` | `marshal.get_marshal_recent_tns_updates` | **公開** | 無 | 200 `{"success": true, "updates": [ {…} ], "is_fallback": bool}`，最多 6 筆 | 500 `{"success": false, "error"}` | 讀 `transient.tns_update_audit`（近 2 天）；無資料時 fallback 讀 `transient.objects`。每次呼叫先執行 DDL `CREATE TABLE IF NOT EXISTS transient.tns_update_audit (...)` 與 `CREATE INDEX IF NOT EXISTS idx_tns_update_audit_updated_at`（**未 commit**，離開 `get_db_connection()` 時被 rollback）。 |
| GET | `/api/marshal/top-viewed` | `marshal.get_marshal_top_viewed` | **公開** | query `mode`：str，預設 `'30days'`；只有 `'all'` 有特殊意義，其他任何值都當 30 天 | 200 `{"success": true, "targets": [ {…} ]}`，最多 5 筆 | 500 `{"success": false, "error"}` | 讀 `transient.object_views`、`transient.object_views_detail`、`transient.objects`。 |
| GET | `/api/marshal/pinned-objects` | `marshal.get_marshal_pinned_objects` | **需登入**（`'user' in session`）；未登入**不是 401/403**，而是 200 `{"success": true, "objects": []}` | 無 | 200 `{"success": true, "objects": [ {…} ]}`，最多 20 筆 | 500 `{"success": false, "error"}`（實務上 `get_pinned_objects()` 內部已 `try/except` 回 `[]`，幾乎不會到 500） | 讀 `transient.objects`（`pin = TRUE`）LEFT JOIN `transient.object_views`。 |

補充細節：

- **`/api/marshal/recent-comments`**：呼叫 `TNSObjectDB.get_recent_comments(limit: int = 5) -> list[dict]`（`transient.py:740`，無 docstring）。SQL：`SELECT c.comment_id AS id, c.name AS object_name, u.email AS user_email, u.name AS user_name, u.picture_url AS user_picture, c.comment AS content, c.comment_time AS created_at, o.name_prefix, o.type, COALESCE(o.internal_name,'') AS internal_names, array_to_string(o.tag,', ') AS tags FROM transient.comments c LEFT JOIN auth.users u ON c.usr_id = u.usr_id LEFT JOIN transient.objects o ON c.obj_id = o.obj_id ORDER BY c.comment_time DESC LIMIT %s`。route 再把 `content` 長度 > 50 者截為前 47 字 + `'...'`；`created_at` 為 ISO 8601 字串。每筆欄位：`id, object_name, user_email, user_picture, user_name, content, created_at, name_prefix, type, internal_names, tags`。
- **`/api/marshal/recent-tns-updates`**：呼叫 `TNSObjectDB.get_recent_tns_updates(limit: int = 20) -> tuple[list[dict], bool]`（`transient.py:766`，route 傳 `limit=6`）。docstring（原文）：「回傳 (updates, is_fallback)。只顯示 2 天內的變更；classified（type / name_prefix 變動）排最上面；is_fallback=True 代表 audit 表無近期資料，改用最近修改物件替代。」流程：(1) `_ensure_tns_update_audit_table(cur)`；(2) 查 `transient.tns_update_audit a LEFT JOIN transient.objects o`，`a.updated_at >= NOW() - INTERVAL '2 days'`，`'type'`/`'name_prefix'` 在 `changed_fields` 者 `sort_priority=0` 優先，再依 `updated_at DESC`；(3) 無資料 → `is_fallback=True`，改查 `transient.objects` 中 `last_modified_date`（MJD，`TIMESTAMP '1858-11-17' + n days`）在 2 天內者，`name_prefix='SN'` 優先；(4) 仍無 → 放寬為最近修改的前 N 筆。每筆欄位：`obj_id, object_name, changed_fields: list[str], updated_at: ISO, source('tns_sync' 等), name_prefix, type, tags, is_classified, is_new_add`。`is_classified` = `changed_fields` 含 `type`/`name_prefix`，或（fallback 且 `name_prefix='SN'`）；`is_new_add` = 非 classified 且（`changed_fields` 含 `new_add` 或 fallback 且非 SN）。
- **`/api/marshal/top-viewed`**：呼叫 `TNSObjectDB.get_top_viewed_objects(days: int = 30, limit: int = 5, mode: str = '30days') -> list[dict]`（`transient.py:931`，無 docstring）；route 固定 `days=30, limit=5`。`mode == 'all'` → `SELECT v.name AS object_name, v.counts AS view_count, COALESCE(o.type,'Unknown') AS object_type, o.name_prefix, COALESCE(o.internal_name,'') AS internal_names, array_to_string(o.tag,', ') AS tags FROM transient.object_views v LEFT JOIN transient.objects o ... ORDER BY v.counts DESC LIMIT %s`；否則 CTE 對 `transient.object_views_detail` 以 `view_time >= now() - (%s || ' days')::interval` 分組計數，JOIN `object_views` 取名稱。每筆欄位：`object_name, view_count, object_type, name_prefix, internal_names, tags`。
- **`/api/marshal/pinned-objects`**：呼叫 `get_pinned_objects(limit: int = 20) -> list[dict]`（`transient.py:2387`，無 docstring）：`SELECT o.name, o.name_prefix, o.type, COALESCE(o.internal_name,'') AS internal_names, array_to_string(o.tag,', ') AS tags, COALESCE(v.counts, 0) AS view_count FROM transient.objects o LEFT JOIN transient.object_views v ON v.obj_id = o.obj_id WHERE o.pin = TRUE ORDER BY view_count DESC LIMIT %s`。每筆欄位：`name, name_prefix, type, internal_names, tags, view_count`。
- 四支 API 都在 `/api/` 前綴下，受 `_block_pipe_in_api_params` 影響（例如 `?mode=a|b` → 400）。
- 四支 API 都沒有使用 `check_object_access()` 或 `filter_by_source_permissions()`（`app/modules/database/auth.py:803, 948`），亦即 `transient.objects.permission`/`groups` 不影響 widget 內容。

## 導向與流程

1. **進入 `/marshal`**：navbar「Marshal」／首頁兩處連結／物件詳細頁 breadcrumb／`object_routes.py` 找不到物件或載入錯誤時 `flash(...)` + `redirect(url_for('marshal.marshal'))`／物件刪除成功 3 秒後 `window.location.href='/marshal'`。
2. **伺服端渲染**：`get_marshal_overview_stats()`（30 秒快取）→ `download_logs` 最新一列 → 依 `total_count` 決定是否預載（`>5000` 不預載）→ 渲染。失敗 → flash「Error loading transient data.」+ 空頁（200）。
3. **前端初始化（`DOMContentLoaded`）**：
   1. `fetchDashboardWidgets()`：依序 `GET /api/marshal/recent-comments` → `GET /api/marshal/recent-tns-updates` → `loadTopViewed()`（`GET /api/marshal/top-viewed?mode=`）→ `loadPinnedObjects()`（`GET /api/marshal/pinned-objects`）。**不論 widget 是否存在於 DOM 都會呼叫**（render 函式在找不到 `<ul>` 時直接 return）。
   2. `currentFilters` 初始化（注意此處只有 10 個 key，沒有 `brightest_*`；`clearAllFilters()` 之後才會有 14 個 key）。
   3. `checkObjectsCount()`：解析 `.total-count` 文字；`count > 5000` 或 DOM 內沒有 `.object-card` → `useApiMode = true`。
   4. `loadInitialObjects()`：API 模式 → `loadObjects()`（`GET /api/objects`）；DOM 模式 → 解析 SSR 卡片成 `objectsFromDOM`（`tag` 一律先設 `'object'`）→ `fetchObjectTags()`（`POST /api/object-tags`）→ `updateDOMCardsWithTags()` → `refreshCurrentView()`。
   5. 1 秒後 `populateClassificationFilter()`：API 模式 → `GET /api/classifications`（失敗或未登入回空 → 改由已載入物件推導；仍為空 → 預設 `AT, SN Ia, SN II, SN Ib/c`）；DOM 模式 → 由卡片推導。
   6. `loadInitialStats()`：`GET /api/stats` → `updateCountersFromStats()`：更新狀態列計數、AT/SN、`.total-count`；`total_count === 0` 時清空 `#tableBody`/`#compactView`、記憶體陣列與篩選狀態。**匿名使用者**頁面沒有 `#inboxCount` 等元素，此函式第 907 行會拋 TypeError（見已知問題 #6）。
   7. `updatePagination()`、`switchView('cards')`。
4. **搜尋**：輸入 → Enter 或「Search」→ `performSearch()`：空字串 → 通知「Please enter search criteria」並 focus，不送出；否則 `useApiMode = true`、`currentFilters.search = term`、清除狀態篩選、`page = 1` → `loadObjects(true)` → 成功重繪 + 通知「Searching for "term"...」；`history.pushState` 加上 `?search=term`。失敗 → 通知「Loading error: <msg>」；訊息含 `404` → 退回 DOM 模式並重新初始化；15 秒逾時 → 通知「Loading timeout, please try again」。
5. **狀態篩選**：狀態列或 `#tagFilter` → `filterByStatus(status)`（同狀態再點 → `clearStatusFilter()`）→ API 模式 `GET /api/objects?tag=<status>&...`；DOM 模式 `applyLocalStatusFilter()`（`obj.tag === status`）。
6. **進階篩選**：Filters → modal → Apply → `applyAdvancedFilters()`：清除既有狀態篩選視覺、把所有欄位讀進 `currentFilters`（classification 為多選逗號串）、若 `tag` 有值則 `updateStatusFilterVisual()`；任一欄位非空 → 強制 API 模式 `loadObjects(true)`；全空 → API 模式重載或 DOM 模式還原全部。通知「Applying filters...」。
7. **清除**：「Clear」／「Clear All」→ `clearAllFilters()`：重置全部 UI 欄位與 `currentFilters`（14 key）、`GET /api/stats`、重載或還原、通知「All filters cleared」。
8. **分頁／每頁筆數／排序**：`changePage()`、`changePageSize()`、`applySorting()`、`toggleSortOrder()` → API 模式 `GET /api/objects`（page/per_page/sort_by/sort_order）；DOM 模式本地處理。
9. **Admin 編輯 tags**（僅 Table 檢視）：「Edit」→ `editTags(name)` 建立內嵌 modal `#_inlineTagEditModal`（輸入 `#_tagEditInput`，逗號分隔）→「Save」→ `_submitTagEdit(name)` → `POST /api/object/<encodeURIComponent(name)>/edit` JSON `{objid: null, tags: <string|null>, _name: name}` → `data.success` → 更新 `currentObjects`/`filteredObjects` 的 `tags`、重繪目前檢視、移除 modal、通知「Tags updated for <name>」；否則 modal 內顯示 `data.error` 或「Network error」。後端（`marshal_bp.api_edit_object`）：非 admin → 403 `{"error": "Access denied - Admin privileges required"}`；`objid` 為 null 時以 URL 名稱（`name` 或 `name_prefix||name`）解析 `obj_id`；`tags` 以 `^[A-Za-z0-9,\s\-_]+$` 驗證（不符 → 400 `Tags contain invalid characters`），拆成陣列寫入 `transient.objects.tag`（清空時寫 `[]`）；`_name` 被忽略。
10. **離開**：所有物件連結以新分頁開 `/object/...`；本頁保留狀態。

## 依賴的模組、資料表、檔案與外部服務

### Python 模組
- `flask`：`render_template, redirect, url_for, session, flash, request, jsonify, Blueprint`（`redirect`、`url_for` 在 `marshal_routes.py` 中匯入但未使用）。
- `modules.database.transient`：
  - `get_marshal_overview_stats(cache_ttl: int = 30) -> dict`（見前述；30 秒 in-process 快取）。
  - `search_tns_objects(search_term='', object_type='', limit=100, offset=0, sort_by='discoverydate', sort_order='desc', date_from=None, date_to=None, mag_min=None, mag_max=None, app_mag_min=None, app_mag_max=None, redshift_min=None, redshift_max=None, discoverer=None, tag=None, brightest_mag_min=None, brightest_mag_max=None, brightest_abs_mag_min=None, brightest_abs_mag_max=None) -> list[dict]`（`transient.py:1180`，無 docstring）。以 `_build_where()` 組 WHERE（`search_term` → `ILIKE %term%` 比對 `o.name`、`o.name_prefix || o.name`、`o.internal_name`、`o.other_name`；`object_type` 逗號分隔多值，`AT` → `name_prefix='AT'`，`Classified` → `name_prefix != 'AT'`，其他 → `o.type = 值`；`tag` 見狀態篩選；`date_from`/`date_to` 為 ISO 日期字串，轉 MJD 比對 `discovery_date`（`date_to` 含當日 +1）；`app_mag_*` 比對 `discovery_mag`；`redshift_*`；`discoverer` → `ILIKE` 比對 `source_group`/`report_group`/`reporters`；`brightest_mag_*`、`brightest_abs_mag_*`）。排序對照 `sort_map`：`discoverydate→o.discovery_date`、`lastmodified→o.last_modified_date`、`discoverymag→o.discovery_mag`、`name`、`time_received→o.received_date`、`last_photometry_date→COALESCE(o.last_phot_date, o.last_modified_date)`、`brightest_mag`、`brightest_abs_mag`、`redshift`；未知值 → `discovery_date`；`NULLS LAST`；`sort_order` 非 `asc` 一律 DESC。`SELECT {OBJECT_COMPAT_COLS} FROM transient.objects o ... LIMIT %s OFFSET %s`。**不做任何權限過濾**。
  - `TNSObjectDB.get_recent_comments`、`TNSObjectDB.get_recent_tns_updates`、`TNSObjectDB.get_top_viewed_objects`、`get_pinned_objects`（簽名見 API 節）。
  - 模組層 `_marshal_stats_cache`、`_ensure_tns_update_audit_table(cur)`。
- `modules.database.get_db_connection()`：pooled psycopg2 連線的 context manager；離開時會 reset（有未結束交易則 rollback）後歸還池中，`OperationalError` 時丟棄連線。`OBJECT_COMPAT_COLS` 亦定義於 `app/modules/database/__init__.py:439`。
- `modules.database.auth`（`check_object_access(object_name, user_email=None, user_roles=0) -> bool`：admin(`user_roles>=50`) 直接 True，否則依 `transient.objects.permission` ∈ `public`/`login`/`groups` 與 `auth.usr_group` 判斷；`filter_by_source_permissions(object_name, data_type, source_list, user_email=None, user_groups=None, is_admin=False)`：依 `transient.object_source_permissions` 過濾資料來源）：**本 blueprint 與其呼叫的 `search_tns_objects` 都沒有使用**。
- `routes/auth/auth_routes.py` 的 `refresh_user_session`（全域 before_request）：決定模板看到的 `session.user.is_admin` 為 DB 最新值。

### 資料表（皆為讀取）
| 資料表 | 用途 |
|---|---|
| `transient.objects` | 物件主表（`status`、`tag[]`、`pin`、`name_prefix`、`name`、`type`、座標、星等、日期（MJD）、`permission`、`groups` …）；清單、統計、widget 的 JOIN 目標 |
| `transient.photometry` | `COUNT(DISTINCT obj_id)`（`tns_stats.with_photometry`，模板未顯示） |
| `transient.download_logs` | 最後同步資訊（`download_date, obj_import, obj_update, status, error_message`） |
| `transient.comments` + `auth.users` | Recent Comments widget |
| `transient.tns_update_audit` | Recent TNS Updates widget（若不存在會嘗試建立） |
| `transient.object_views`、`transient.object_views_detail` | Top Viewed／Pinned 的瀏覽次數 |
| （間接，經 `/api/objects?tag=flag`）`transient.cross_matches` | Flagged 篩選 |

### 檔案與外部服務
- 讀取的檔案：僅模板與靜態檔（見下節）。不寫任何檔案。
- 外部服務：無（TNS 同步、GCN 等在其他模組；本章只讀同步紀錄）。
- 背景執行緒：無。快取：`_marshal_stats_cache`（每個 worker process 各自一份，TTL 30 秒，無失效 API）。

## 前端檔案

### 模板
- `app/routes/marshal/templates/marshal.html`（671 行）。`include` 了 `_navbar.html`（`app/routes/basic/templates/_navbar.html`；載入 `css/_theme.css`、`css/_navbar.css`，並顯示 flash 訊息）與 `_favicon.html`。模板內另有一段 inline `<style>`（`.loading-overlay`）。
- 同目錄的 `object_detail.html` 屬物件詳細頁（別章）。

### CSS（`app/routes/marshal/static/css/marshal/`）
| 檔案 | 用途 |
|---|---|
| `marshal.css` | 進入點，依序 `@import` 下列 12 個 partial：`_variables, _base, _components, _layout, _filters, _cards, _table, _compact, _modals, _responsive, _left_redesign, _filter_modal_redesign` |
| `_variables.css` | `:root` 色彩／間距／圓角等 token，橋接到全站 `_theme.css` 的 `--kw-*` 變數 |
| `_base.css` | reset、`body` 字型與固定背景圖 `photo/background.png`、glass 效果基底 |
| `_components.css` | 按鈕、`.status-row`（含 `.active`）、舊版 `.small-stat-card` 系列、`.spinner`、通知等共用元件 |
| `_layout.css` | `.marshal-container`、`.top-section-split`（左控制面板 34% + 右側 widget 面板）、`.status-row` 佈局、`.side-widget` 版面 |
| `_filters.css` | 搜尋列、`.toggle-advanced`、進階篩選欄位群組樣式 |
| `_cards.css` | `.objects-grid`（`repeat(auto-fill, minmax(18%, 1fr))`）與 `.object-card` 卡片樣式 |
| `_table.css` | `.objects-table` / `.data-table` 表格檢視 |
| `_compact.css` | `.objects-compact` 精簡檢視（UI 入口已註解） |
| `_modals.css` | `.modal` / `.modal-overlay` / `.upload-modal` 通用 modal 與上傳 modal 樣式 |
| `_responsive.css` | 分頁列 `.pagination-container` 與各斷點的響應式規則 |
| `_left_redesign.css` | 左側控制面板重新設計（漸層面板、標頭 grid、`.small-stat-card` 覆寫） |
| `_filter_modal_redesign.css` | 進階篩選 modal 全螢幕重設計（`.advanced-filter-overlay`、`.advanced-filter-dialog` …） |

（`css/object_detail/*.css` 屬物件詳細頁，別章。）

### JavaScript
- `app/routes/marshal/static/js/marshal.js`（1849 行，全部為全域函式，無模組化）。主要全域狀態：`currentView('cards')`、`currentObjects[]`、`filteredObjects[]`、`currentPage(1)`、`pageSize(50)`、`totalPages`、`totalObjects`、`sortBy('lastmodified')`、`sortOrder('desc')`、`isLoading`、`currentFilters{}`、`useApiMode(false)`、`currentStatusFilter('')`、`window.isAdmin`、`ICONS`（inline SVG）。
- 主要函式群：初始化（`loadInitialStats, checkObjectsCount, loadInitialObjects, fetchObjectTags, updateDOMCardsWithTags`）、資料載入（`loadObjects, mapSortField, hasActiveFilters, showLoading`）、檢視（`switchView, generateCardsView, generateTableView, generateCompactView, filterCardsView, refreshCurrentView, getTagDisplayName, getTagIndicator, buildObjectTags`）、狀態篩選（`filterByStatus, applyStatusFilter, applyLocalStatusFilter, clearStatusFilter, updateStatusFilterVisual, clearStatusFilterVisual, updateCardStyling`）、計數（`updateCounters, updateCountersFromStats`）、分頁（`updatePagination, syncPageSizeSelectors, updatePaginationControls, changePage, scrollToContentTop, changePageSize`）、排序（`applySorting, toggleSortOrder, sortObjects`）、搜尋／篩選（`performSearch, toggleAdvancedFilters, applyAdvancedFilters, populateClassificationFilter, populateClassificationFilterFromAPI, populateClassificationFilterFromObjects, populateClassificationOptions, clearAllFilters`）、側欄（`fetchDashboardWidgets, loadPinnedObjects, renderPinnedObjects, loadTopViewed, renderTopViewed, renderRecentComments, renderRecentTnsUpdates`）、其他（`forceRefreshAll, quickView, editTags, _submitTagEdit, showNotification, getEpAliasBadge, buildEpTags`）。
- `object_detail.js` 屬物件詳細頁（別章）。

### marshal.js 呼叫的 API 清單

| 呼叫函式 | 方法／路徑 | 送出參數 | 所屬 blueprint / endpoint | 前端如何處理回應 |
|---|---|---|---|---|
| `loadInitialStats()`（初始化、`clearAllFilters`、`forceRefreshAll`、404 退回 DOM 模式時） | GET `/api/stats` | 無 | `web_api.api_get_stats`（未登入回 `success:true` 且全 0；登入後以 `get_objects_count()`/`get_tag_statistics()` 計） | `data.stats.{inbox_count, followup_count, finished_count, snoozed_count, flag_count, at_count, classified_count, total_count}` → 更新 `#inboxCount/#followupCount/#finishedCount/#snoozedCount/#flagCount`（後兩者不存在時略過）、AT/SN 數字、`.total-count`；`total_count===0` 時清空檢視與篩選。失敗 → 全部設 0。 |
| `fetchObjectTags(objects)`（僅 DOM 模式） | POST `/api/object-tags`，JSON `{"object_names": [<卡片顯示名稱>...]}` | 名稱為 `name_prefix + name`（例 `AT2025abc`） | `web_api.api_get_object_tags`（需登入，否則 403；以 `o.name IN (...)` 比對） | `data.tags[name]`（狀態別名）與 `data.object_tags[name]`（tags 字串）合併進物件；任何錯誤 → 所有物件 `tag='object'`。 |
| `loadObjects(resetPage)` | GET `/api/objects` | `page, per_page, sort_by(mapSortField: name/type/discoverydate/discoverymag/redshift/lastmodified/last_photometry_date/brightest_mag/brightest_abs_mag), sort_order, search, classification(逗號串), tag, date_from, date_to, app_mag_min, app_mag_max, redshift_min, redshift_max, discoverer, brightest_mag_min, brightest_mag_max, brightest_abs_mag_min, brightest_abs_mag_max`（空值以空字串送出） | `web_api.api_get_objects`（公開；`page` int ≥1、`per_page` int 1–500 由 `get_int_arg` 驗證，浮點數由 `get_float_arg` 驗證，不合法 → 400 `{"error"}`；空字串視為未提供；**`brightest_*` 四個參數後端未讀取**） | `data.objects[]` 映射為 `{name(name_prefix+name), type, classification, discovery_date(discoverydate), tag, magnitude(discoverymag), redshift, ra, dec(declination), source(source_group), last_update(time_received||lastmodified), lastmodified, last_photometry(last_photometry_date), brightest_mag, brightest_abs_mag, internal_names}`（**沒有映射 `tags`**）；`data.total`、`data.total_pages`；忽略 `data.stats`；無篩選時更新 `.total-count`。15 秒逾時；404 → 切回 DOM 模式。 |
| `populateClassificationFilterFromAPI()` | GET `/api/classifications` | 無 | `web_api.api_get_classifications`（未登入回 `[]`） | `data.classifications[]` → `#classificationFilter` 選項（`AT` 排最前，其餘字母序）；失敗 → 由物件推導。 |
| `fetchDashboardWidgets()` | GET `/api/marshal/recent-comments` | 無 | `marshal.get_marshal_recent_comments` | `renderRecentComments(data.comments)` |
| `fetchDashboardWidgets()` | GET `/api/marshal/recent-tns-updates` | 無 | `marshal.get_marshal_recent_tns_updates` | `renderRecentTnsUpdates(data.updates, data.is_fallback)` |
| `loadTopViewed()` | GET `/api/marshal/top-viewed?mode=<all|30days>` | `mode` 取自 `#topViewedMode`（元素不存在時 `'30days'`） | `marshal.get_marshal_top_viewed` | `renderTopViewed(data.targets)` |
| `loadPinnedObjects()` | GET `/api/marshal/pinned-objects` | 無 | `marshal.get_marshal_pinned_objects` | `renderPinnedObjects(data.objects)`；非 2xx → 「Unavailable」 |
| `_submitTagEdit(name)`（admin） | POST `/api/object/<encodeURIComponent(name)>/edit`，JSON `{"objid": null, "tags": "<逗號字串>" 或 null, "_name": name}` | — | `marshal_bp.api_edit_object`（admin only → 否則 403） | `data.success` → 更新記憶體、重繪、通知；否則顯示 `data.error`。 |

`marshal.js` **沒有**呼叫下列端點（雖與本頁概念相關，實際使用者是物件詳細頁 `object_detail.js`，別章）：`POST /api/objects`（新增物件；`/marshal` 頁面上沒有任何「新增物件」UI）、`POST /api/object/<name>/status`（狀態切換）、`POST /api/object/<name>/toggle_pin`、`POST /api/object/<name>/toggle_flag`。

## 已知問題與注意事項

1. **Brightest Mag / Brightest Abs Mag 篩選完全無效**：進階篩選 modal 的 `#brightestMagMin/Max`、`#brightestAbsMagMin/Max` 會由 `marshal.js` 以 `brightest_mag_min/max`、`brightest_abs_mag_min/max` 送到 `GET /api/objects`，但 `web_api_routes.py:765 api_get_objects` **沒有讀取**這四個參數（`search_tns_objects()`／`_build_where()` 本身有支援，只是 route 沒傳）。使用者填了也不會過濾。
2. **flag 定義三頭馬車**：(a) SSR 的 `flag_count` 用 `transient.objects.tag @> ARRAY['flag']`；(b) `#tagFilter` 的「Flagged」→ `/api/objects?tag=flag` → `_build_where` 用 `transient.cross_matches.status = 'Flagged'`（該欄 schema 註解值為 `Success/Error/Retry-Success`，未見寫入 `'Flagged'` 的程式）；(c) 真正的 flag 切換（`toggle_flag`）寫 `cross_matches.flag BOOLEAN`。另外 `/api/stats` 的 `flag_count` 來自 `get_tag_statistics()`，該函式根本沒有 `flag` key → **永遠 0**；模板也沒有 `#flagCount` 元素、`flag_count` 變數未使用。`filterByStatus('flag')`（由 `#tagFilter` change 觸發）會顯示通知「Filtering undefined objects」（`statusNames['flag']` 未定義）。
3. **Upload TNS CSV modal 是死 HTML**：`#uploadModalOverlay` 沒有任何開啟按鈕，且 `closeUploadModal()`、`clearSelectedFile()`、`startUpload()` 在 `marshal.js` 中不存在（模板 `onclick` 指向未定義函式）。`.admin-tools` 內的 `{% if ... is_admin %}{% endif %}` 為空區塊，推測原本放上傳按鈕。
4. **JS 仍在找已被移除的 `.small-stat-card`**：`filterByStatus()`、`clearAllFilters()` 以 `.small-stat-card.clickable` 切換 `active`，但模板已改為 `.status-row`（CSS 註解也寫「replaces small-stat-card active」）。結果：點狀態列**不會**得到 `.status-row.active` 高亮（只有走 `applyAdvancedFilters()` → `updateStatusFilterVisual()` 那條路才會）。`_components.css`、`_responsive.css`、`_left_redesign.css` 中的 `.small-stat-card*` 規則為死 CSS。
5. **DOM 模式（`total_count ≤ 5000`）的狀態標籤會全部變成 Inbox**：`loadInitialObjects()` 把卡片顯示名稱（`name_prefix + name`，例 `AT2025abc`）送到 `POST /api/object-tags`，但該 API 以 `o.name IN (...)` 比對（`name` 無前綴），全部比對不到 → 回傳預設 `'object'` 與 `null` → `updateDOMCardsWithTags()` 把 SSR 已正確標示的卡片全部改成「Inbox」，`applyLocalStatusFilter('followup'|'snoozed')` 也永遠是空的。匿名使用者更因 403 得到相同結果。此外 DOM 模式初始順序是伺服端的 `discoverydate desc`，但排序下拉預設顯示「Last Update」，兩者不一致。實務上 TNS 物件數 > 5000 時走 API 模式，此問題屬潛伏。
6. **匿名使用者每次載入都會在 console 出現未捕捉的 TypeError**：`updateCountersFromStats()`（`marshal.js:907, 908, 911`）對 `#inboxCount`、`#followupCount`、`#snoozedCount` 沒有 null guard，而這三個元素只在 `{% if session.user %}` 內渲染。匿名時 `loadInitialStats()` 的 `.then` 拋錯 → 進 `.catch` → 再呼叫 `updateCountersFromStats({...0})` 又拋錯 → unhandled promise rejection；`.total-count`、AT/SN 因在出錯行之後而不會被更新。`clearAllFilters()`、`forceRefreshAll()`、404 fallback 也都會經過同一條路。若日後補上 guard，要注意 `api_get_stats` 對匿名回 `total_count: 0` 且 `success: true`，屆時 `total_count === 0` 分支會把 `.total-count` 改成「0 objects」並清空記憶體陣列與 `#tableBody`（不清 `#cardsView`），分頁會顯示「Showing 1-0 of 0 objects」。
7. **`?search=` 只寫不讀**：`performSearch()` 以 `history.pushState` 把 `?search=` 放進網址，但沒有任何程式在載入時讀 `location.search`，重新整理即失去搜尋條件，網址有誤導性。
8. **未使用的模板變數**：`tns_stats`、`use_api_mode`、`initial_limit`、`flag_count`；`finished_count` 只在 Jinja 註解中。`current_path` 傳給 navbar 但 navbar 對 Marshal 連結沒做 active 判斷。
9. **死程式碼（JS）**：`quickView()`、`applyStatusFilter()`、`updateCounters()`、`getEpAliasBadge()`（註解自稱 deprecated）、`buildEpTags()`（"backward compat"）從未被呼叫；`generateCompactView()` 僅在 `switchView('compact')` 可達，而 Compact 按鈕已註解。`loadInitialStats()` 失敗分支的物件字面值有重複 key `flag_count`（第 131–132 行）。`forceRefreshAll()` 重設的 `currentFilters` 只有 10 個 key（缺 `brightest_*`），與 `clearAllFilters()` 的 14 個不一致（`loadObjects` 用 `|| ''` 所以不會出錯）。
10. **`/api/marshal/recent-comments` 為公開 API 但側欄對 guest/匿名隱藏**：任何人不用登入即可取得最近 5 則留言的 `user_email`、`user_name`、`user_picture`、留言前 50 字、物件 `internal_names`、`tags`，形同資訊外洩；`/api/marshal/recent-tns-updates`、`/api/marshal/top-viewed` 同樣公開。前端不論 widget 是否存在都會打這四支 API（匿名使用者每次載入多 3–4 個無用請求）。
11. **讀取型 GET 內含 DDL**：`get_recent_tns_updates()` 每次呼叫都執行 `CREATE TABLE IF NOT EXISTS transient.tns_update_audit` 與 `CREATE INDEX IF NOT EXISTS`，且沒有 `conn.commit()`（`get_db_connection()` 歸還連線時 rollback）。表若真的不存在，這條路徑永遠建不起來（靠寫入端 `log_tns_update_batch()` 的 commit 才會建立）。
12. **統計快取與一致性**：`get_marshal_overview_stats()` 的 30 秒快取為每個 worker process 各自持有、無失效鉤子；狀態變更後 SSR 標頭最多 30 秒過期，而 `/api/stats` 無快取，兩邊數字可能短暫不同；多 worker（gunicorn）下不同請求可能落在不同快取。`classified_count` 用 `total - AT` 而 `tns_stats.classified` 用 `type` 非空，兩種「classified」定義並存。
13. **最後同步狀態判斷過寬**：`status` 只要不含 `error` 就當 `completed`，`'In Progress'` 進行中也會顯示為「(0 new, 0 updated)」；`.sync-status.pending` 分支不可達；`{% if last_sync.errors %}` 在 completed 分支永遠為 None，屬死分支。
14. **XSS 風險（innerHTML 未跳脫）**：`renderRecentComments()` 直接把 `c.content`（留言內容，登入者可寫）與 `c.user_name` 塞進 innerHTML；`renderRecentTnsUpdates()`／`renderTopViewed()`／卡片與表格也把 `obj.name`、`obj.source`、`obj.classification`、tags 等未跳脫地寫入。留言內容是最直接的儲存型 XSS 向量（且此 API 公開）。`editTags()` 只對物件名稱跳脫單引號。
15. **`changePageSize()` 依賴全域 `window.event`**（函式未接收 `event` 參數），在不支援的環境會拋錯。
16. **`Ctrl+Shift+R` 被攔截**改為 `forceRefreshAll()`，覆蓋瀏覽器的強制重新整理快捷鍵。
17. **物件清單不做權限過濾**：`search_tns_objects()` 與 `/api/objects` 忽略 `transient.objects.permission`（`public`/`login`/`groups`）與 `groups`，`check_object_access()`／`filter_by_source_permissions()` 在本章完全未使用；因此 `/marshal` 與 `/api/objects` 對匿名使用者列出所有物件（含 `permission='login'/'groups'` 者），只有進入詳細頁時才可能被擋（別章）。
18. **名稱長度 < 4 的物件連回 `/marshal`**（SSR 模板 fallback）；JS 產生的卡片則一律連 `/object/...`，行為不一致。
19. **`/api/marshal/pinned-objects` 對未登入回 200 空陣列**而非 401/403，前端會顯示「No pinned objects」；`get_pinned_objects()` 內部吞掉所有例外也回 `[]`，DB 故障時無法從回應區分。
20. **`/api/marshal/top-viewed` 的 `mode` 未驗證**（任意字串都被當 30 天）；`days` 固定 30，`#topViewedMode` 的「30 Days」文字與後端一致，但 HTML 第一個 option 是 `all`，所以頁面初次載入實際送的是 `mode=all`，與 JS 註解「without mode argument uses default '30days'」不符。
21. 小型冗餘：`marshal()` 內重複 `from flask import session`；`obj['tag']` 補值邏輯永遠不會觸發；`marshal_routes.py` 匯入但未用的 `redirect`、`url_for`；`applyAdvancedFilters()` 讀取 `#searchInput` 但 `performSearch()` 才會強制 API 模式（在 DOM 模式只填搜尋字不填其他欄位時，仍會因「任一欄位非空」切到 API 模式，行為一致，只是路徑重複）。
22. `object_detail.js` 在物件刪除後導向 `'/marshal'` 為寫死字串（非 `url_for`），若日後改路徑需同步。
23. **API 模式下自訂 tags 永遠不顯示，且 Edit 會蓋掉既有 tags**：`loadObjects()` 把 `/api/objects` 回傳的物件映射成前端格式時（`marshal.js:373-390`）**沒有映射 `tags` 欄位**（後端 `OBJECT_COMPAT_COLS` 有回傳 `tags`）。因此在正式環境（`total_count > 5000`，純 API 模式）`generateCardsView()`／`generateTableView()` 的 `buildObjectTags(obj.tags)` 永遠得到空字串，EP 等自訂標籤在列表上看不到（只有 SSR 卡片、以及四個 widget 會顯示）。連帶 admin 的 `editTags()` 以 `obj.tags || ''` 起始 → modal 輸入框永遠是空的，按 Save 會以使用者新輸入的值**整個覆蓋** DB 中原有的 `tag[]`（清空時後端寫 `[]`）。
