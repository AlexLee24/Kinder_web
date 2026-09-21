# 物件詳細頁與物件資料 API（`marshal_bp` blueprint，`app/routes/marshal/object_routes.py`）

> **注意**：本章記錄的是重構前（commit `c7f91a4`，2026-09-21）的狀態，檔案路徑為舊位置（`app/routes/…`、`app/modules/…`）。新位置請對照 `docs/ARCHITECTURE.md` §6「新舊路徑對照」；功能與行為在重構後完全相同。

> 本章依據原始碼逐一核對：`app/routes/marshal/object_routes.py`（2194 行、45 個 route）、`app/routes/marshal/templates/object_detail.html`（963 行）、`app/routes/marshal/static/js/object_detail.js`（6183 行），以及被呼叫的模組 `app/modules/database/transient.py`、`auth.py`、`catalog.py`、`app/modules/data_processing.py`、`ext_M_calculator.py`、`astronomy_calculator.py`、`spectral_lines.py`、`request_validation.py`、`app/modules/database/__init__.py`、`app/main.py`、`app/routes/__init__.py`。

## 概要

- **Blueprint 物件**：`objects_bp = Blueprint('marshal_bp', __name__)`（變數名 `objects_bp`，blueprint 名稱 **`marshal_bp`**，endpoint 一律為 `marshal_bp.<函式名>`）。沒有 `url_prefix`，也**沒有宣告 `template_folder`／`static_folder`**；`object_detail.html` 之所以找得到，是因為同目錄的 `marshal_routes.py` 另一個 blueprint `marshal`（`Blueprint('marshal', __name__, template_folder='templates', static_folder='static')`）把 `app/routes/marshal/templates` 掛進 Jinja 搜尋路徑；靜態檔則由 `app/main.py` 的全域 `/static/<path:filename>` route 逐一搜尋各 blueprint 的 `static` 目錄提供。
- **註冊順序**（`app/routes/__init__.py::register_routes`）：`auth_bp → admin_bp → astronomy_tools_bp → objects_bp → api_blueprint → web_api_bp → private_area_bp → basic_bp → marshal_bp → detect_bp → web_log_bp → database_status_bp → games_bp → planners_bp`。
- **負責的功能**：
  1. 物件詳細頁 `/object/<name>`（兩條平行路由）。
  2. 物件 JSON、狀態（Inbox / Follow-up / Finish / Snoozed）變更、欄位編輯（redshift / internal_name / tag）、刪除物件。
  3. 光度（photometry）資料的讀取、單點新增、批次上傳、刪除、`.dat` 下載、Plotly 光變曲線（含消光、K 修正、絕對星等軸、KN 模型距離模數）。
  4. 光譜（spectroscopy）資料的清單、原始資料、上傳、刪除、下載、Plotly 繪圖（rest-frame、normalise、stack），以及 NIST 光譜線表快取。
  5. 評論（comments）CRUD。
  6. 「資料來源權限」（source permissions：每個物件、每個 phot/spec 來源可設 public / login / groups / blocked）與「物件群組權限」（object permissions：`transient.objects.permission/groups`）。
  7. NED cone search 代理（含 `cat.ned` 快取）與 NED host 設定端點（**目前不持久化**）。
  8. KN（kilonova）模型光變曲線資料端點。
- **與其他區塊的關係**：
  - 入口：Marshal 列表頁 `marshal.html`（`url_for('marshal_bp.object_detail_tns_format', year=..., letters=...)` / `url_for('marshal_bp.object_detail_generic', object_name=...)`）、`marshal.js`、DETECT 頁（`detect_home.html`、`detect_results.html`、`detect_results.js`）、`admin.js`、private_area 的 `epessto_support.js`、`daily_trigger.js` 都以 `/object/<name>` 連進來。
  - 頁面 JS 另外呼叫 **`web_api_bp`** 的 `/api/object/<name>/detect_cross_match`、`/detect_images`、`/detect_images/generate`、`/pin_status`、`/toggle_pin`、`/fetch_photometry`（以及已停用的 `/flag_status`、`/toggle_flag`），與 **`detect_bp`** 的 `/detect_image_by_id/<id>`；這些端點細節由其他章記錄，本章只描述前端如何使用。
  - 外連頁面：`/marshal`（`marshal.marshal`）、`/finding_chart`（`astronomy_tools`）、`/interactive_planner`（`astronomy_tools`）。
- **全域 before/after_request（`app/main.py`）影響本章所有 `/api/` 端點**：
  - `_enforce_allowed_host`：Host header 不在 `APP_BASE_URL`（DEBUG 時加 localhost/127.0.0.1）→ `404`。
  - `_block_pipe_in_api_params`：`/api/` 開頭的請求，只要 query string、form 或 JSON body 任一值含 `|` → `400 {"error": "Invalid character '|' is not allowed"}`（影響評論內容、tags、上傳資料等）。
  - `@app.errorhandler(ParamOutOfRangeError)` → `400 {"error": "<訊息>"}`（`get_float_arg` 在 `try` 之外拋出時由此接手）。
  - `refresh_user_session`（auth blueprint）每個請求同步 `session['user']` 的 `is_admin`、`groups`、`is_great_lab_member`。
- **session 使用者欄位**（本章用到的）：`session['user']['email']`、`['name']`、`['picture']`、`['is_admin']`（`roles >= 50`）、`['role']`（`'admin'` / `'user'` / `'guest'`）、`['groups']`（群組**名稱**清單）。

---

## 頁面（HTML routes）

### 路徑總覽與 werkzeug 匹配優先順序（特別說明 2）

| 路徑規則 | endpoint | converter 組成 |
|---|---|---|
| `/object/<path:object_name>` | `marshal_bp.object_detail_generic` | `path`（regex `[^/].*?`，weight 200，非 part-isolating，final） |
| `/object/<int:year><string:letters>` | `marshal_bp.object_detail_tns_format` | `int`（`\d+`，weight 50）+ `string`（`[^/]+`，weight 100） |
| `/api/object/<int:year><alpha:letters>...` | 各 `*_tns_format` / 無後綴版 | `int` + 自訂 `alpha`（`app/main.py` 的 `AlphaConverter`，regex `[a-zA-Z]+`，weight 100） |
| `/api/object/<object_name>...` | 各 `*_generic` / `get_object_api` 等 | 預設 `string`（`[^/]+`） |
| `/api/object/<path:object_name>/toggle_pin` 等（`web_api_bp`，他章） | — | `path` + 靜態尾段 |

專案使用 **Werkzeug 3.1.8**（`uv.lock`），路由匹配採 `StateMachineMatcher`：先比對靜態片段，再依 `RulePart.weight = (-len(static_parts), static_weights, -len(argument_weights), argument_weights)` **由小到大**嘗試動態片段；某條動態片段匹配但後續片段對不上時會**回溯**到下一條動態片段。因此：

1. **頁面**：`/object/<int:year><string:letters>` 的片段 regex 為 `(\d+)([^/]+)\Z`，weight `(0, [], -2, [50, 100])`；`/object/<path:object_name>` 為 `([^/].*?)\Z`，weight `(0, [], -1, [200])`。前者排序在前，所以**只要最後一段以數字開頭且長度 ≥ 2、不含 `/`**（例如 `2025abc`、`2025ABC`、`20251`、甚至 `2024`），一律由 `object_detail_tns_format` 處理（因為函式內只做 `f"{year}{letters}"` 串回，數字/字母如何切分不影響結果）；以非數字開頭（`AT2025abc`、`SN2025abc`、`ZTF24aaa`、`EP250101a`）或含 `/` 的名稱才會落到 `object_detail_generic`。
2. **API**：`<int:year><alpha:letters>` 的片段 regex 為 `(\d+)([a-zA-Z]+)\Z`（嚴格 TNS 樣式），weight `(0, [], -2, [50, 100])` 排在 `<object_name>`（`([^/]+)\Z`，weight `(0, [], -1, [100])`）之前。純 TNS 名稱（`2025abc`）走 `*_tns_format` 版；帶前綴、含數字尾（`2025abc1`）或任何其他字串走 generic 版。**只存在 generic 版的端點**（`/edit`、`/delete`、`/comments`、`/sources`、`/source-permissions*`、`/permissions`）對 TNS 名稱仍可用：int+alpha 狀態沒有該靜態尾段時，matcher 回溯到 `<object_name>` 轉移。
3. `web_api_bp` 的 `<path:object_name>/toggle_pin` 等為 final 片段且含靜態尾段，weight 的 `-len(static_parts) = -1` 使其排在最前，但 regex 要求尾段精確為 `/toggle_pin` 等，與本章路徑不衝突。
4. 因為 `url_for('marshal_bp.object_detail_generic', object_name='2025abc')` 產生 `/object/2025abc`，generic 路由裡所有「redirect 到 canonical 名稱」的 302 **最終都會由 `object_detail_tns_format` 接手**（只要名稱以數字開頭）。

### 物件名稱解析規則（特別說明 1）

**URL → 物件列的解析（`object_detail_generic`）**，依序：

1. `urllib.parse.unquote(object_name)`。
2. 精確查詢 1：`(COALESCE(o.name_prefix,'') || COALESCE(o.name,'')) ILIKE %s`（完整名，例如 `AT2025abc`，不分大小寫）。
3. 精確查詢 2：`o.name ILIKE %s`（去前綴名）。
4. 若命中且 `name_prefix` 非空且 URL 字串（小寫）≠ `name`（小寫）→ **302** 到 `url_for('marshal_bp.object_detail_generic', object_name=name)`（canonical 無前綴 URL，如 `/object/AT2025abc → /object/2025abc`）。沒有前綴的物件（如 ZTF 名）不重導。
5. 未命中 → alias 查詢：`internal_name ILIKE '%<x>%'` **或** `tag` 陣列任一元素 `trim(v) ILIKE '<x>'`，`ORDER BY discovery_date DESC NULLS LAST LIMIT 1` → 302 到該物件的 `name`（處理 ZTF 內部名、EP 標籤名）。
6. 仍未命中 → 去前綴：regex `^(?:AT|SN|SLSN-I{1,2}|Ia|II)\s*(?=[0-9]{4})`（不分大小寫）去掉後以 `o.name ILIKE` 查 → 302 到 canonical（處理 AT→SN 已分類但 URL 仍是舊前綴的情況；注意步驟 2 其實已能以 `AT` 前綴命中 `AT` 物件，此步主要救 `SN2025x` 但 DB 前綴仍 `AT` 之類的錯配）。
7. 仍未命中 → `search_tns_objects(search_term=object_name, limit=50)`（`name` / `name_prefix||name` / `internal_name` / `other_name` 皆 `ILIKE '%x%'`，依 `discovery_date DESC`）取前 50 筆，找 `full_name` 或 `name` 完全相等（不分大小寫）者。
8. 都沒有 → `flash('Object <x> not found.', 'error')` → 302 `url_for('marshal.marshal')`。

**`object_detail_tns_format`**：`object_name = f"{year}{letters}"`（不 unquote），只做 `o.name ILIKE %s`（使用 `OBJECT_COMPAT_COLS`）；未命中 → `search_tns_objects(limit=50)` 三策略（`name` 相等、`full_name` 相等、`re.search(r'(\d{4})([a-zA-Z]+)$', name)` 擷取後相等）；再沒有 → flash + 302 `/marshal`。**沒有** alias / 去前綴 / canonical redirect 邏輯。

**API 的解析**：`get_object_api`：完整名 ILIKE → `name` ILIKE → fuzzy（full/name 相等）；`api_get_object_tns_format`：`name` ILIKE → fuzzy（`name` 相等或 regex `(\d{4})([a-zA-Z]+)$` 尾段年份、字母相等）。

**模組層（`app/modules/database/transient.py`）的名稱處理**——這是實際讀寫資料時的規則，和 URL 層**不一致**：

| 函式 | 規則 |
|---|---|
| `_resolve_obj_id(cur, name)` | `WHERE name = %s`（區分大小寫、不處理前綴） |
| `_resolve_obj_id_with_prefix(cur, name)` | regex `^(?:AT|SN|FRB|TDE|EP)(.+)$` 取 bare，`WHERE name = %s OR name = %s`（原字串或 bare，仍區分大小寫）。photometry / spectroscopy / comments 的新增、讀取都用它 |
| `TNSObjectDB.log_object_view` | 先以 `^(?:AT|SN)(\d.+)$` 去前綴再 `_resolve_obj_id`（失敗只寫 log，不拋錯） |
| `update_object_status`、`update_object_abs_mag` | `name = %s OR name ILIKE %s OR (COALESCE(name_prefix,'')||name) ILIKE %s` |
| `TNSObjectDB.get_comments`、`check_object_access`、`get_object_permissions`、`grant/revoke_object_permission` | `name = %s`（精確） |
| `_get_current_ned_host_name` | `name = %s OR (COALESCE(name_prefix,'')||name) = %s`（精確） |
| `get_source_permissions` / `filter_by_source_permissions` | `object_name = %s`（`transient.object_source_permissions.object_name` 為純文字，存的是前端傳來的字串） |

**前端（`object_detail.js`）的名稱變數**：
- `objectName`：URL 最後一段（`decodeURIComponent`）。
- `cleanObjectName = extractYearAndLetters(objectName)`：regex `(\d{4}[a-zA-Z0-9]+)` 擷取，例 `AT2024abc → 2024abc`；找不到則原字串。多數 API 呼叫用它。
- `getFullObjectName(objectData) = name_prefix + name`：用於 `/status`、`/edit`、`/delete`。
- 載入物件時依序嘗試 `/api/object/<objectName>`、`<cleanObjectName>`、去 `AT`、去 `SN` 四個候選，第一個 `success && object` 者勝出。

### `/object/<path:object_name>` — `marshal_bp.object_detail_generic`

| 項目 | 內容 |
|---|---|
| 方法 | GET |
| 權限 | **公開**（未登入也可看；頁面內容依 `visibility` 裁切） |
| 輸入 | 路徑 `object_name`（`path` converter，可含 `/`；會 `unquote`） |
| 模板 | `object_detail.html` |
| 模板變數 | `current_path='/object'`、`object_name`（URL 原字串，不是 DB canonical）、`object_data`（dict）、`visibility`（dict） |
| 成功 | 200 渲染；或 302 到 canonical URL |
| 失敗 | 找不到 → `flash('Object <x> not found.','error')` + 302 `/marshal`；任何例外 → `traceback.print_exc()` + `flash('Error loading object data.','error')` + 302 `/marshal` |
| 副作用 | `TNSObjectDB.log_object_view(object_name, user_email)`：INSERT `transient.object_views_detail(obj_id,name,usr_id)`、UPSERT `transient.object_views(obj_id,name,counts,last_view)`（每次瀏覽都寫）；`update_object_abs_mag(object_name)`：UPDATE `transient.objects.brightest_mag`（取 `transient.photometry` 中 `mag BETWEEN 5 AND 30 AND (mag_err IS NULL OR mag_err>0)` 最亮者，否則 `discovery_mag`）及 `brightest_abs_mag`（需 `redshift>0` 且 ra/dec 存在，呼叫 DETECT 的 `function.module.screening.absolute_magnitude`，含 SFD 消光與 K 修正）；讀 `transient.objects`；`calculate_redshift_distance(z)`（astropy `FlatLambdaCDM(H0=67.7, Om0=0.309, Tcmb0=2.725)`，無 astropy 時退回 Hubble law H0=70）→ `object_data['distance_mpc']` |

`visibility` 的計算（兩條頁面路由相同）：

```
role = session.user.role (預設 'guest'); is_admin = session.user.is_admin; is_logged_in = bool(session.user)
can_see_restricted = is_admin or role in ('user', 'admin')      # 登入且非 guest
visibility = { detect, spectroscopy, comments, tags, peak_abs_mag: can_see_restricted, phot_controls: is_logged_in }
```

`object_data` 欄位（generic 版的兩個精確查詢是**手寫欄位清單**，非 `OBJECT_COMPAT_COLS`）：`objid, name_prefix, name, ra, declination, redshift, typeid(NULL), type, reporting_groupid(NULL), reporting_group, source_groupid(NULL), source_group, discoverydate, discoverymag, discmagfilter, filter, reporters, time_received, internal_names(=COALESCE(internal_name,''))、discovery_ads_bibcode, class_ads_bibcodes, creationdate, lastmodified, brightest_mag, brightest_abs_mag, tags(=array_to_string(tag)), tag(status→finished/followup/snoozed/object)`，再加 `distance_mpc`。若走 fuzzy fallback（`search_tns_objects`）則欄位為 `OBJECT_COMPAT_COLS`（多 `obj_id, kinder_id, last_photometry_date, pin, status, inbox, snoozed, follow, finish_follow, permission, groups`，且 `internal_names` 會串上 `other_name`）。所有 `datetime` 值轉為 `'%Y-%m-%d %H:%M:%S'` 字串。

### `/object/<int:year><string:letters>` — `marshal_bp.object_detail_tns_format`

| 項目 | 內容 |
|---|---|
| 方法 | GET |
| 權限 | **公開** |
| 輸入 | 路徑 `year`（int）、`letters`（`[^/]+`）；`object_name = f"{year}{letters}"` |
| 模板 / 變數 / 失敗 / 副作用 | 與 generic 相同（`log_object_view`、`update_object_abs_mag`、`calculate_redshift_distance`） |
| 差異 | 精確查詢只有 `o.name ILIKE %s` 且使用 `OBJECT_COMPAT_COLS`；**不做** alias、去前綴、canonical redirect；fuzzy fallback 多一個「regex 擷取年+字母後相等」策略 |

**實際流量**：因匹配優先順序，所有 `/object/2025abc` 形式的請求（包含 Marshal 列表產生的連結與 generic 路由的 302）都由此函式處理；generic 只處理帶前綴 / 非 TNS 名稱與 alias 查詢，然後 302 過來。

### 頁面區塊與互動（`object_detail.html` + `object_detail.js`）

頁面載入流程（`DOMContentLoaded`）：隱藏 `#loadingOverlay` → 綁定「Upper Limit」checkbox → 由 URL 取 `objectName` / `cleanObjectName` → `_buildSpecChipsUI()` → `loadObjectData()`（依序嘗試 4 個候選呼叫 `GET /api/object/<name>`）→ 成功後 `updatePageContent()`：更新標題/徽章/標籤，然後**平行**啟動 `loadLocationImage()`（legacysurvey cutout）、`loadSpectrumPlot()`、`loadComments()`、`initializeAladinWhenReady()`、`loadDetectData()`、`loadDetectImages()`、`loadPhotometryPlot()`；另 `checkPinStatus()`；admin 才有的 `.perm-panel` 存在時 `loadPermissionsPanel()`。

隱藏的資料節點：`div[data-user-email]`（登入者 email）、`div[data-admin="true"]`（admin）、`#visibilityConfig[data-detect|data-spectroscopy|data-comments|data-phot-controls]`（JS 目前沒有讀取這個節點，僅存在）。

| 區塊 | 顯示條件 | 元素 / 按鈕 / Modal | 呼叫的 API 或導向 |
|---|---|---|---|
| 頂部導覽列 | 一律 | 「Marshal」麵包屑 | `url_for('marshal.marshal')` → `/marshal` |
| | 一律 | 「Finding Chart」`openFindingChart()` | `window.open('/finding_chart?object_name&ra&dec&survey=DSS2+Red&fov=13&show_stars=0&auto=1')` |
| | 一律 | 「Visibility」`openVisibilityPlot()` | `window.open('/interactive_planner?object_name&ra(HMS)&dec(DMS)')` |
| 標題列 | 一律 | `#objectName`、`#classificationBadge`（type 或 AT）、`#statusBadge`（tag）、`#tagsContainer`（`visibility.tags` 且有 tags 才在模板渲染；JS `renderCustomTags` 之後又會依 API 回傳重建，**guest 也會看到**，見已知問題） | — |
| Comments 迷你面板 | `visibility.comments` | `#commentsMiniPanel`：`+`（登入者）`openCommentsModal(true)`、展開 `openCommentsModal()`；`#commentsList` | `GET /api/object/<clean>/comments` |
| DETECT 迷你面板 | `visibility.detect` | `#detectMiniPanel`：展開 `openDetectModal()`；`#detectBody` 顯示 DETECT verdict（host_status、score、tags、M、z、decline rate、KN envelope）與 cross-match 候選清單 | `GET /api/object/<clean>/detect_cross_match`（web_api）；若 screen.tags 含 `Kilonova?` 自動 `toggleKnModel()` |
| Pin | admin | `#pinBtn` `togglePin()` | `GET .../pin_status`、`POST .../toggle_pin`（web_api） |
| Metadata & Info 面板 | 一律 | Internal Name、RA/Dec（`toggleCoordMode()` HMS↔deg）、Discovery Date、Reporting Group、Redshift `#redshiftValue`、Luminosity Distance、Peak Abs Mag（`visibility.peak_abs_mag`；JS 會補上「at MJD … (filter)」） | 資料來自模板變數與 `GET /api/object/<name>` |
| | admin | 「Edit」`editObjects()` → 動態建立 `#editObjectModal`（Object Name 唯讀、Redshift、Internal Names、Tags）→ `submitEditObject()` | `POST /api/object/<full>/edit`；成功後 2.5 秒 `location.reload()` |
| | 一律 | 快速連結：TNS `openTNSPage()`、NED `openNED()`、DESI LS `openDESI()`、Extinction `openExtinction()`、Copy Coords `copyCoordinates()` | 外站：`https://www.wis-tns.org/object/<clean>`、`https://ned.ipac.caltech.edu/conesearch?...radius=0.5`、`https://www.legacysurvey.org/viewer?ra&dec&layer=ls-dr10-grz`、`https://ned.ipac.caltech.edu/cgi-bin/nph-calc?...`；剪貼簿 |
| | admin | 「DETECT Follow up」`changeStatus('followup')`、「Snooze」`changeStatus('snoozed')`（「Finished」按鈕已被 Jinja 註解掉） | `POST /api/object/<full>/status`；`confirm()` 後送出；`clear` 時 `location.reload()` |
| DESI Legacy Survey 面板 | 一律 | `#locationImageSrc`（點擊 `openDESI()`）、`#locationMarker` | 外站 `https://www.legacysurvey.org/viewer/cutout.jpg?ra&dec&pixscale=0.1&layer=ls-dr10-grz&size=600` |
| Aladin 面板 `#star-map` | 一律 | `#surveySelect`（DSS2 / DESI-LS-DR10 / PanSTARRS / Rubin / HSC / HST / JWST / Euclid / NSNS）`changeSurvey()`；「NED Explorer」`openNEDExplorer()`；`#aladin-lite-div` 內以 `srcdoc` iframe 載入 Aladin Lite v3（`postMessage` 通訊：`changeSurvey`、`addNEDCatalog`、`toggleNEDCatalog`、`aladinReady`） | 外站 CDS HiPS |
| Photometry 面板 | 一律 | `#lastPhotometryDate`；toggles `#applyExtinction`、`#applyKCorr`（皆 `loadPhotometryPlot()`）；`#telescopeToggles`、`#photLegend`（JS 建立的望遠鏡 / filter 開關，`Plotly.restyle visible`）；主圖 `#phot-plotly-div`；子圖 Color Index（`#colorFilterA/B`，配對 0.5 天內）、Δ Magnitude（`#magDeltaFilter`、`#magDeltaBin` 0.5–14 天中位數差） | `GET /api/object/<clean>/photometry/plot?extinction=&k_corr=`、`GET /api/object/<clean>/photometry`（`Promise.all`，逾時 120 s） |
| | `visibility.phot_controls`（任何登入者） | 「Fetch」`fetchPhotometry()`（`confirm` 後）、「Upload」`uploadPhotometry()`、「Edit」`togglePhotometryEditMode()` | `POST /api/object/<objectName>/fetch_photometry`（web_api，成功後 reload）；Upload / Edit 見下方 Modal |
| | 一律 | 「Download」`openDownloadModal()`、「Refresh」`loadPhotometryPlot()`、「KN Model」`toggleKnModel()` + `#knModelControls`（Peak MJD slider `onKnSliderInput`、`#knDistModLabel` μ） | `GET /api/kn_model`（一次後快取於 `_knModelData`）；g/r/i band 依 `distance_modulus` 位移，`Plotly.addTraces` |
| Spectroscopy 面板 | `visibility.spectroscopy` | toggles `#specRestFrame`（預設勾）、`#specNormalise`（預設勾）、`#specStackOffset` → `onSpecToggle()`；「Upload」`uploadSpectrum()`、「Download」`downloadCurrentSpectrum()`、「Refresh」`loadSpectrumPlot()`；`#specChipsGrid` 光譜線 chip（H/He/Ca/Si/O/Na/Fe/S/C/Mg/N/Ti/Ba + Tel 大氣吸收帶）；`#specLineSourceBadge`（Built-in / Building… / NIST）；trial-z `#specLineRedshift`、波長範圍 `#specWaveMin/Max`；圖 `#spectrumPlot`（後端回傳 Plotly HTML div，JS 手動執行內嵌 `<script>`） | `GET /api/object/<clean>/spectrum/plot?rest_frame=1&normalise=1&stack=1`；`GET /api/spectral-lines`；下載：`GET /api/object/<clean>/spectroscopy` 取第一筆 `spectrum_id` → `GET /api/spectrum/<id>/download` |
| Data Source Permissions 面板 `.perm-panel` | admin | Tabs Photometry / Spectroscopy `switchPermTab`；每個來源一張卡：Public / Members / Groups / Blocked pill（`onPermVisChange`）、群組 chips（`addPermGroup` / `removePermGroup`）；批次選取 `_permSelectAll` / `batchApplyPerm`；「Refresh Sources」`refreshPermSources()`、「Save now」`savePermissions(false)`；**修改後 1.5 秒自動儲存**；含 `TNS` 的來源鎖定為「Always public」 | `GET /api/object/<clean>/sources`、`GET /api/object/<clean>/source-permissions`、`GET /api/groups`、`POST /api/object/<clean>/source-permissions/batch` |
| Comments Modal `#commentsModal` | `visibility.comments` | 「+ Comment」`showAddCommentForm()`（登入者）、`#addCommentForm`（textarea maxlength 1000、`#charCounter`、Cancel `cancelAddComment()`、Post `submitComment()`）；`#commentsContainer` 在開啟時被 DOM 搬進 `#commentsModalSlot`；每則評論有 Edit（作者或 admin）`startEditComment/saveEditComment`、Delete（作者或 admin 顯示；後端只允許 admin）`deleteComment` | `POST /api/object/<clean>/comments`、`PUT /api/comments/<id>`、`DELETE /api/comments/<id>` |
| DETECT Modal `#detectModal` | `visibility.detect` | Data / Chart tab `switchDetectTab`；「Run/Refresh」`forceDetectRun()`；「Generate Chart」`generateDetectImages()`；`#detectBody` DOM 搬入 `#detectModalSlot` | `GET .../detect_cross_match?force=true`（失敗時退回無 force 的快取結果）、`POST .../detect_images/generate`、`GET .../detect_images`；圖片 `<img src="/detect_image_by_id/<image_id>">`（detect_bp） |
| Edit Photometry Modal `#editPhotometryModal` | 一律存在（由 Edit 按鈕開啟） | 望遠鏡 / filter 篩選、排序、勾選、「Delete Selected」、每列刪除/復原 `markForDeletion`、「+ Add Point」`showAddPhotometryForm()`、「Save Changes」`savePhotometryChanges()`、Cancel | Save 只會對 `toDelete` 逐一 `DELETE /api/photometry/<id>`（`toAdd` 永遠為空，因為 Add Point 直接送出）；完成後 `loadPhotometryPlot()` |
| Add Photometry Point Modal `#addPhotometryModal` | 一律存在 | MJD、Magnitude、Upper Limit checkbox（勾選則 error 欄停用）、Magnitude Error、Filter、Telescope（預設帶入最後一筆望遠鏡）；「Add Point」`addPhotometryPoint()` | 前端驗證：MJD 50000–70000、mag 5–30、非上限時 error ≥ 0、filter 非空且 ≤ 10 字 → `POST /api/object/<clean>/photometry` |
| Upload Photometry Modal `#uploadPhotometryModal` | 一律存在 | 拖放區 `#fileDropZone`（`.txt/.dat/.csv`）、欄位對應 UI `#columnMappingSection`（自動偵測失敗才顯示）、「▶ Preview」`applyColumnMapping()`、預覽表 `#previewTable`（MJD / Magnitude / Error / Filter / Telescope / Status）、「Upload Data」`uploadPhotometryData()` | `POST /api/object/<clean>/photometry/batch`；成功後 0.9 秒 `loadPhotometryPlot()` + 關閉 |
| Upload Spectrum Modal `#uploadSpectrumModal` | 一律存在 | Telescope/Instrument（可由檔名推斷）、Observation Date（可由檔名推斷）、拖放區（`.txt/.dat/.ascii/.csv`）、預覽表（Wavelength / Intensity）、「Upload Spectrum」`submitSpectrumData()` | `POST /api/object/<clean>/spectroscopy`；成功後 `loadSpectrumPlot()` |
| Download Photometry Modal `#downloadPhotometryModal` | 一律存在 | MJD range、Include non-detections、Telescopes / Filters checkbox（All / None）、「Download .dat」`doDownloadPhotometry()` | 以 `<a download>` 觸發 `GET /api/object/<clean>/photometry/download?telescopes=&filters=&mjd_min=&mjd_max=&include_nondet=false` |
| NED Explorer Modal `#nedExplorerModal` | 一律存在 | 左：獨立 Aladin iframe（`#ned-aladin-iframe`，`postMessage`：`addNEDSources`、`changeSurvey`、`highlightNED`、`nedHover`、`nedAladinReady`）；右：結果表（#、Name、Phys Type、RA、Dec、z、cz、z flag、Action）；`#nedSurveySelect`、Radius(") `#nedRadiusInput`（1–600，預設 30）、「Re-search」`rerunNEDSearch()`（force=1）；每列「Set as Host」`setNEDHost` / 「Unset Host」`unsetNEDHost`；NED 逾時（502 且訊息含 timeout）→ 10 秒倒數自動重試 | `GET /api/ned/cone?ra&dec&radius_arcsec&object_name=<objectName>&force=0|1`、`POST /api/ned/set_host`、`POST /api/ned/unset_host` |
| 其他 | 一律 | `#loadingOverlay`（`showLoading`）、`#notificationContainer`（`showNotification`，5 秒自動消失）、`#kinder-tooltip`（`[data-tip]` hover） | — |

外部腳本：`https://cdn.plot.ly/plotly-2.27.0.min.js`（SRI）、`https://code.jquery.com/jquery-3.6.0.min.js`（SRI）、`https://aladin.cds.unistra.fr/AladinLite/api/v3/latest/aladin.js`（async；主頁面載入但實際 Aladin 在 iframe 內再載一次）。

### 導向（頁面層）

- 進入：`/object/<name>`（Marshal 列表、DETECT 頁、admin 頁、private_area 頁、瀏覽器直接輸入）。
- 302：帶前綴 / alias / 舊前綴 → canonical `/object/<name>`；找不到或例外 → `/marshal`（帶 flash）。
- 離開：麵包屑 `/marshal`；刪除成功後（JS，僅 dead code 可觸發）`/marshal`；新分頁：`/finding_chart`、`/interactive_planner`、TNS、NED、DESI、NED extinction。

---

## API 與動作端點

權限欄位用語：**公開** = 不檢查 session；**需登入** = `'user' in session`；**僅 admin** = `session['user']['is_admin']`；**物件層級** = `check_object_access(object_name, user_email)`；**來源權限過濾** = `filter_by_source_permissions(...)`；**需登入且非 guest** = `role != 'guest' or is_admin`。未通過時的回應寫在「失敗回應」欄。表格內 `<Y><L>` 代表 `<int:year><alpha:letters>`。

| # | 方法 | 路徑 | endpoint（`marshal_bp.`） | 權限 | 輸入 | 成功回應 | 失敗回應 | 副作用 |
|---|---|---|---|---|---|---|---|---|
| 1 | GET | `/api/object/<Y><L>` | `api_get_object_tns_format` | 公開 | 路徑 year/letters | `200 {success:true, object:{OBJECT_COMPAT_COLS…}}` | `404 {success:false,error:'Object not found'}`；例外 `500 {success:false,error}` | 讀 `transient.objects`（**不**呼叫 `update_object_abs_mag`） |
| 2 | POST | `/api/object/<Y><L>/status` | `api_update_object_status_tns_format` | 僅 admin | JSON `status` ∈ `object/followup/finished/snoozed`（**不含 clear**） | `200 {success:true, message:'Status updated to <s>'}` | 403 `{error:'Access denied'}`；400 `{error:'Invalid status'}`；404 `{error:'Object not found'}`；500 `{error:'Failed to update status'}` / `{success:false,error}` | `search_tns_objects(limit=10)` + regex 找物件 → `update_object_status(full_name)` UPDATE `transient.objects.status` |
| 3 | GET | `/api/object/<object_name>` | `get_object_api` | 公開 | 路徑（unquote） | `200 {success:true, object:{…}, full_name}` | 404 `{error:'Object not found'}`；500 `{success:false,error}` | **`update_object_abs_mag(object_name)`（寫 DB）**；讀 `transient.objects` |
| 4 | POST | `/api/object/<object_name>/edit` | `api_edit_object` | 僅 admin | JSON `objid?`(int)、`redshift?`(float≥0 或 null/'')、`internal_names?`(str)、`tags?`(str，逗號分隔，regex `^[A-Za-z0-9,\s\-_]+$`) | `200 {success:true, message:'Object updated successfully', updated_fields:[…]}` | 403 `{error:'Access denied - Admin privileges required'}`；400 `Invalid request body` / `Object ID (objid) is required and could not be resolved` / `Redshift must be positive` / `Invalid redshift value` / `Tags contain invalid characters` / `No valid fields to update`；404 `Object not found`；500 `Database error: …` | UPDATE `transient.objects SET redshift / internal_name / tag WHERE obj_id`；`objid` 缺時以 `name = %s OR prefix||name = %s` 解析 |
| 5 | DELETE | `/api/object/<object_name>/delete` | `api_delete_object` | 僅 admin | 路徑（unquote） | `200 {success:true, message, object_name}` | 403（同上）；404 `Object not found`；500 `Failed to delete object` / `Database error: …` | DELETE `transient.objects WHERE prefix||name = x OR name = x`；後續對 photometry/spectroscopy/comments 的清理子查詢**因物件已刪除而為空**（實際依賴 FK CASCADE）；同一連線 `close()` 兩次（見已知問題） |
| 6 | POST | `/api/object/<object_name>/status` | `api_update_object_status_generic` | 僅 admin | JSON `status` ∈ `object/followup/finished/snoozed/clear` | `200 {success:true, message}` | 403；400 `Invalid status`；500 `Failed to update status in database` / `{success:false,error}` | `update_object_status(name, status)`：`_STATUS_MAP` → `Inbox/Follow-up/Finish/Snoozed`（`clear`→`Inbox`）UPDATE `transient.objects.status` |
| 7 | GET | `/api/object/<Y><L>/photometry` | `get_object_photometry` | 公開 + 來源權限過濾 | 路徑 | `200 {success:true, photometry:[{id,object_name,mjd,magnitude,magnitude_error,filter,telescope}], count}` | 500 `{error}` | `TNSObjectDB.sync_last_photometry_date`（UPDATE `objects.last_phot_date` = MAX(MJD)）；讀 `transient.photometry`（`mag IS NULL OR mag>=0`）；`sanitize_for_json`（NaN/Inf→null）；讀 `object_source_permissions`、`default_permissions`、`auth.groups` |
| 8 | GET | `/api/object/<Y><L>/spectroscopy` | `get_object_spectroscopy` | 需登入 | 路徑 | `200 {success:true, spectra:[{telescope,observation_mjd,min_wavelength,max_wavelength,point_count,observation_row_id,phase,spectrum_id,spectrum_label,observation_date_label}], count}` | 403 `{error:'Access denied'}`；500 | 讀 `transient.spectroscopy` GROUP BY source,"MJD"（**無**來源權限過濾） |
| 9 | GET | `/api/object/<object_name>/spectroscopy` | `get_object_spectroscopy_generic` | 需登入 | 路徑（unquote） | 同 #8 | 同 #8 | 同 #8 |
| 10 | GET | `/api/object/<Y><L>/spectrum/<spectrum_id>` | `get_spectrum_data` | 需登入 | 路徑 `spectrum_id`＝`SOURCE@@MJD` 或純 source | `200 {success:true, wavelength:[…], intensity:[…], spectrum_id}` | 403；500 | 讀 `transient.spectroscopy JOIN objects WHERE o.name ILIKE AND s.source = [AND ABS("MJD"-mjd)<1e-6]`；**前端未使用** |
| 11 | POST | `/api/object/<Y><L>/photometry` | `upload_photometry` | 僅 admin | JSON `mjd`(必要, float)、`magnitude?`、`magnitude_error?`、`filter?`、`telescope?` | `200 {success:true, message:'Photometry point added successfully', id:<phot_id 或 null>}` | 403；500 `{error}`（`mjd` 缺→`float(None)` TypeError→500） | `TNSObjectDB.add_photometry_point`：負星等直接回 `None`；INSERT `transient.photometry(obj_id,name,"MJD",mag,mag_err,filter,source)` `ON CONFLICT ON CONSTRAINT phot_uniq DO NOTHING`；`_mjd_update`（更新 `last_phot_date`、`Snoozed→Inbox`） |
| 12 | POST | `/api/object/<Y><L>/photometry/batch` | `upload_photometry_batch` | 僅 admin | JSON `points:[{mjd,magnitude,magnitude_error,filter,telescope|source}]` | `200 {success:true, inserted, total}` | 403；400 `No points provided`；500 | `add_photometry_batch`：逐筆 INSERT（同上，跳過負星等；`telescope` 缺→`source`→`'Unknown'`），`_mjd_update(max_mjd)`；物件不存在→`inserted=0` |
| 13 | POST | `/api/object/<string:object_name>/spectroscopy` | `upload_spectroscopy_generic` | 僅 admin | JSON `wavelength:[]`、`intensity:[]`、`phase?`、`telescope?`、`spectrum_id?`、`original_filename?`、`observation_date?`(YYYY-MM-DD) | `200 {success:true, message:'Spectrum data added successfully', spectrum_id:'SOURCE@@MJD'}` | 403；500 | `add_spectrum_data`：`_resolve_spectrum_source_and_mjd` 決定 source/MJD；`execute_batch` INSERT `transient.spectroscopy(obj_id,name,"MJD",wavelength,intensity,source)`；物件不存在仍回 success 但不寫入 |
| 14 | POST | `/api/object/<Y><L>/spectroscopy` | `upload_spectroscopy` | 僅 admin（委派） | 同 #13 | 同 #13 | 同 #13 | 直接 `return upload_spectroscopy_generic(f"{year}{letters}")` |
| 15 | DELETE | `/api/photometry/<int:point_id>` | `delete_photometry_point` | 僅 admin | 路徑 `point_id` | `200 {success:true, message}` | 403；404 `Photometry point not found`；500 | DELETE `transient.photometry WHERE phot_id`（不檢查所屬物件） |
| 16 | DELETE | `/api/spectrum/<spectrum_id>` | `delete_spectrum` | 僅 admin | 路徑 `spectrum_id` | `200 {success:true, message}` | 403；404 `Spectrum not found`；500 | DELETE `transient.spectroscopy WHERE source = [AND ABS("MJD"-mjd)<1e-6]`（**不限定物件**，跨物件同 source+MJD 會一起刪） |
| 17 | GET | `/api/object/<Y><L>/photometry/download` | `download_photometry` | 需登入（**無**來源權限過濾、無物件層級檢查） | query `telescopes`(逗號)、`filters`(逗號)、`mjd_min`/`mjd_max`(float, `get_float_arg`)、`include_nondet`(預設 true，`'false'` 才排除) | `200 text/plain`，`Content-Disposition: attachment; filename="<name>_phot.dat"`；格式見下 | 403；400（`ParamOutOfRangeError`，由全域 handler）；500 | 讀 `transient.photometry` |
| 18 | GET | `/api/spectrum/<path:spectrum_id>/download` | `download_spectrum_file` | 需登入 | 路徑 `spectrum_id` | `200 text/plain` 附件 `<obj>_spec_<label>.dat` | 403；404 `Spectrum not found`；500 | 讀 `spectroscopy JOIN objects WHERE s.source = [AND MJD]`（**不限定物件**） |
| 19 | GET | `/api/spectral-lines` | `get_spectral_lines` | 需登入 | — | `200 {success:true, source:'nist'|'building', count, lines:[{w,label,ion,group}]}` | 403；例外時 **`200`** `{success:false, lines:[], source:'error'}` | 讀 `app/modules/_spectral_lines_cache.json`（TTL 30 天）；快取冷時**啟動背景執行緒 `nist-spec-lines`**（astroquery → NIST）並回空陣列 |
| 20 | POST | `/api/spectral-lines/rebuild` | `rebuild_spectral_lines` | 僅 admin | — | `200 {success:true, message:'Rebuild started in background'}` | 403；500 | `warm_cache_async()`：若無執行中執行緒則啟動背景重建（寫 `_spectral_lines_cache.json`）；**前端未使用** |
| 21 | GET | `/api/object/<Y><L>/photometry/plot` | `get_object_photometry_plot` | 公開；**登入者**才做物件層級檢查；來源權限過濾 | query `extinction`(預設 true)、`k_corr`(預設 true)；非 `'true'` 即 false | `200 {success:true, plot_json:<Plotly fig JSON>, data_count, distance_modulus, redshift}` | 登入但 `check_object_access` 失敗 → `200 {success:true, plot_html:null, message:'Access denied.'}`；無資料 → `200 {…plot_html:null, message:'No photometry data available'}`；過濾後為空 → `200 {…plot_json:null, message:'Login to view photometry', data_count:0}`；500 `{error}` | `search_tns_objects(limit=1)` 取 redshift/ra/dec（**模糊比對第一筆**）；`get_photometry`；`DataVisualization.create_photometry_plot_from_db(as_json=True)`（呼叫 `ext_M_calculator.z_to_lmd`、`get_extinction`）；`ext_M_calculator.z_to_lmd` 算距離模數 |
| 22 | GET | `/api/object/<Y><L>/spectrum/plot` | `get_object_spectrum_plot` | 需登入 + 物件層級 | query `spectrum_id?`、`rest_frame`、`normalise`、`stack`（`'1'`/`'true'`） | `200 {success:true, plot_html:<div+script>, data_count}` | 403；物件層級失敗 → `200 {success:true, plot_html:null, message:'Access denied.'}`；無資料 → `200 {…message:'No spectrum data available'}`；500 | `search_tns_objects(limit=1)` 取 redshift；`get_spectroscopy`；`create_spectrum_plot_from_db` / `create_spectrum_list_plot_from_db` |
| 23 | GET | `/api/object/<object_name>/photometry` | `get_object_photometry_generic` | 公開 + 來源權限過濾 | 路徑（unquote） | 同 #7 | 同 #7 | 同 #7 |
| 24 | POST | `/api/object/<object_name>/photometry` | `upload_photometry_generic` | 僅 admin | 同 #11 | 同 #11 | 同 #11 | 同 #11 |
| 25 | POST | `/api/object/<object_name>/photometry/batch` | `upload_photometry_batch_generic` | 僅 admin | 同 #12 | 同 #12 | 同 #12 | 同 #12 |
| 26 | GET | `/api/object/<object_name>/photometry/download` | `download_photometry_generic` | 需登入（無權限過濾） | 同 #17 | 同 #17 | 同 #17 | 同 #17 |
| 27 | GET | `/api/object/<object_name>/photometry/plot` | `get_object_photometry_plot_generic` | 同 #21 | 同 #21 | 同 #21 | 同 #21，另 `search_tns_objects` 無結果 → `404 {success:false,error:'Object <x> not found'}`；例外 `500 {success:false,error}` | 同 #21 |
| 28 | GET | `/api/kn_model` | `api_kn_model` | 需登入 | — | `200 {success:true, model:{g:{time,min,median,max}, r:{…}, i:{…}}}` | 403；500 | 讀 `app/modules/web_data/kn_lc_mag.txt`（程序層級快取 `_KN_MODEL_CACHE`） |
| 29 | GET | `/api/object/<object_name>/spectrum/plot` | `get_object_spectrum_plot_generic` | 需登入 + 物件層級 | 同 #22 | 同 #22 | 同 #22，另物件不存在 → `404 {success:false,error}`；`500 {success:false,error}` | 同 #22 |
| 30 | GET | `/api/object/<object_name>/comments` | `get_object_comments` | 公開（未登入回空）+ 物件層級 | 路徑（unquote） | `200 {success:true, comments:[{id,object_name,user_email,user_name,user_picture,content,created_at(ISO)}], count}` | 未登入 → `200 {success:true, comments:[], count:0}`；物件層級失敗 → `200 {…count:0, message:'Access denied'}`；500 `{error:'Failed to get comments'}` | 讀 `transient.comments LEFT JOIN auth.users WHERE c.name = %s` |
| 31 | POST | `/api/object/<object_name>/comments` | `add_object_comment` | 需登入 | JSON `content`(1–1000 字，trim) | `200 {success:true, message, comment_id}`（物件不存在時 `comment_id:null` 仍 success） | 403；400 `Comment content is required` / `Comment is too long (maximum 1000 characters)`；500 `Failed to add comment` | INSERT `transient.comments(obj_id,name,usr_id,comment)`（`usr_id` 由 `auth.users.email` 查） |
| 32 | DELETE | `/api/comments/<int:comment_id>` | `delete_comment` | 僅 admin | 路徑 | `200 {success:true, message}` | 403；404 `Comment not found`；500 | DELETE `transient.comments WHERE comment_id` |
| 33 | PUT / PATCH | `/api/comments/<int:comment_id>` | `update_comment` | 需登入且（admin 或評論作者 email 相符） | JSON `content`(1–1000) | `200 {success:true, message}` | 403 `Access denied` / `Access denied: You can only edit your own comments`；404；400（同 #31）；500 | UPDATE `transient.comments.comment` |
| 34 | GET | `/api/object/<object_name>/sources` | `get_object_sources` | 僅 admin | 路徑 | `200 {success:true, phot_sources:[…], spec_sources:[…]}` | 403；500 | 讀 `photometry.source` / `spectroscopy.source` DISTINCT（`COALESCE(...,'Unknown')`，`o.name ILIKE`） |
| 35 | GET | `/api/object/<object_name>/source-permissions` | `get_source_permissions_api` | 僅 admin | 路徑 | `200 {success:true, permissions:[{id,object_name,data_type,source_name,allowed_groups:<null|[群組名]>,is_public,updated_at}], defaults:[{source,permission:'public'|'login'|'groups',allowed_groups:<null|[群組名]>}]}` | 403；500 | 讀 `object_source_permissions`（phot+spec）、`default_permissions`、`auth.groups`（id→name） |
| 36 | POST | `/api/object/<object_name>/source-permissions/batch` | `set_source_permissions_batch_api` | 僅 admin | JSON `permissions:[{data_type:'phot'|'spec'(預設 phot), source_name, is_public:bool, allowed_groups:<null|[群組名]>}]` | `200 {success:true}` | 403；400 `Missing permissions list`；500（如缺 `source_name` → KeyError） | 群組名→id；每筆 UPSERT `transient.object_source_permissions` `ON CONFLICT (object_name,data_type,source_name)` |
| 37 | GET | `/api/groups` | `get_groups_api` | 需登入 | — | `200 {success:true, groups:[{name, group_id, group_name, description, manager_email, created_at, members:[email…], …}]}` | 403；500 | 讀 `auth.groups`、`auth.usr_group`、`auth.users` |
| 38 | GET | `/api/object/<object_name>/permissions` | `get_object_permissions_api` | 需登入 | 路徑 | `200 {success:true, permissions:{permission:'public'|'login'|'groups', groups:[group_id…]}}`（**是 dict，不是 list**） | 403；500 | 讀 `transient.objects.permission, groups WHERE name = %s`；找不到回 `{'permission':'public','groups':[]}` |
| 39 | POST | `/api/object/<object_name>/permissions` | `add_object_permission_api` | 僅 admin | JSON `group_name` | `200 {success:true, message:'Permission granted successfully'}` | 403；400 `Group name is required` / `Failed to grant permission (maybe already exists)`（群組不存在或 DB 錯誤）；500 | UPDATE `transient.objects SET permission='groups', groups = groups ∪ {gid} WHERE name = %s` |
| 40 | DELETE | `/api/object/<object_name>/permissions` | `remove_object_permission_api` | 僅 admin | JSON `group_name` | `200 {success:true, message:'Permission revoked successfully'}`（即使物件無此群組也回成功） | 403；400；404 `Permission not found`（僅群組名不存在或 DB 錯誤時）；500 | UPDATE `transient.objects SET groups = array_remove(groups, gid)`（**不會**把 `permission` 改回 public/login） |
| 41 | GET | `/api/ned/cone` | `ned_cone_search` | 公開 | query `ra`(float, 預設 0)、`dec`(預設 0)、`radius_arcsec`(預設 60)、`object_name?`、`force`(`0/false/''` 以外皆 true) | `200 {success:true, count, results:[{objname,ra,dec,type,redshift,redshift_type,distance_arcmin}], from_cache:bool, searched_at?(快取時), current_host:<host_name 或 null>}` | 502 `{success:false,error:'NED request timed out: …'}` / `'NED request failed: …'`；400 `ParamOutOfRangeError`；500 | 讀 `transient.objects.host_name`；`get_ned_cache(object_name, radius)` 讀 `cat.ned`；未命中或 force → HTTP GET `https://ned.ipac.caltech.edu/cgi-bin/objsearch`（ascii_bar、list_limit=500、timeout 60 s、UA `KinderWeb/1.0`）→ 解析 → `upsert_ned_cache` 寫 `cat.ned`（有 `object_name` 時） |
| 42 | POST | `/api/ned/set_host` | `ned_set_host` | 需登入且非 guest | JSON `target_name`、`host_name`（必要）、`redshift?`、`redshift_type?`（其餘欄位忽略） | `200 {success:true, host_name, updated_redshift:bool, redshift:<float|null>, z_flag}` | 401 `{success:false,error:'Unauthorized'}`（未登入或 guest）；400 `Missing target_name or host_name`；500 | **無任何寫入**（只 log）。docstring 稱「僅存 session」但程式碼並未寫 session |
| 43 | POST | `/api/ned/unset_host` | `ned_unset_host` | 需登入且非 guest | JSON `target_name` | `200 {success:true}` | 401；400 `Missing target_name`；500 | 無任何寫入（只 log） |

外加 2 個頁面 route（`object_detail_generic`、`object_detail_tns_format`），本 blueprint 共 **45 個 route**。

### 表格補充細節

**物件 JSON（#1、#3）**：`#3` 每次被呼叫都會先執行 `update_object_abs_mag()`；`#1`（純 TNS 名稱會匹配到的版本）則不會。因此非 TNS 樣式名稱（如 ZTF 名）的頁面每次載入會寫兩次 `brightest_mag`（頁面 route 一次、JS 的 `/api/object/<name>` 一次），TNS 名稱只寫一次。回傳的 `object` 為 `OBJECT_COMPAT_COLS` 全欄位（含 `permission`、`groups`、`pin`、`status`），對未登入者也一樣。

**狀態（#2、#6）**：DB `transient.objects.status` 實值為 `Inbox` / `Follow-up` / `Finish` / `Snoozed`；API 收舊式代碼 `object/followup/finished/snoozed/clear`（`_STATUS_MAP` 也接受新式字串）。前端 `changeStatus` 用 `fullObjectName`（含前綴）所以永遠打到 generic 版（#6）。`#2` 用 `search_tns_objects(search_term, limit=10)` 再以 regex `(\d{4})([a-zA-Z]+)` 在 full_name 內搜尋（非錨定），理論上可能對到另一物件。

**編輯（#4）**：`tags` 空字串或 null → `tag = []`（維持 NOT NULL）；`internal_names` 寫入 `internal_name` 欄。前端表單以 `/api/object/<name>` 回傳的 `internal_names`（＝`internal_name || ', ' || other_name`）預填，**原樣存回會把 `other_name` 併進 `internal_name`**。

**光度上傳格式（特別說明 3）**：
- 檔案：`.txt` / `.dat` / `.csv`，空白或逗號分隔（以第一行資料是否含 `,` 判斷）。`#` 開頭行忽略，但資料前的 `# MJD magnitude error filter telescope` 這種含非數字 token 的註解行會被當表頭；否則第一行資料若含非數字 token 亦當表頭；都沒有時以 `col_1…col_N` 位置對應並顯示欄位對應 UI。
- 表頭自動對應（不分大小寫）：`mjd|jd`→MJD；`filter|band|flt|passband`→Filter；`mag|magnitude`→Magnitude；`err|magerr|mag_err|error|dmag|*err|*error|*_err`→Error；`telescope|tel|instrument|observer`→Telescope。必要：MJD、Magnitude、Filter；Error、Telescope 可為「not used」（Telescope 預設 `Unknown`）。
- 上限（non-detection）判定：星等以 `>` 開頭，或 Error 欄有對應但值為 `nan/none/null/''/-`，或 Error 解析為 NaN / 負數 → `magnitude_error = null`，狀態 `warning: Upper Limit`。
- 列驗證：MJD 20000–100000；magnitude 數值；filter 非空且 ≤ 10 字。任何 `error` 列會讓「Upload Data」停用；上傳時只送 `status != 'error'` 的列。
- Payload：`{points:[{mjd, magnitude, magnitude_error, filter, telescope}]}` → #12/#25。後端唯一鍵 `phot_uniq(obj_id,"MJD",filter,source)`，重複點 `DO NOTHING`（`inserted` 會小於 `total`）。
- 單點新增（#11/#24）前端限制：MJD 50000–70000、mag 5–30；後端另外拒絕負星等（回 `id:null` 但 `success:true`）；`magnitude`/`magnitude_error` 為 `0` 時因 falsy 會被當成 `None`。
- 下載格式（#17/#26）：
  ```
  # <name> photometry
  # MJD magnitude error filter telescope
  60000.123456  18.240000  0.050000  g  SLT
  60001.567000  >19.100000  nan  r  LOT      ← 上限：mag 前加 >，error 為 nan
  ```

**光譜上傳格式（特別說明 3）**：
- 檔案 `.txt/.dat/.ascii/.csv`，每行 `wavelength intensity`，分隔為空白/Tab/逗號；`#` 開頭或**以字母開頭**的行忽略；任一欄非數字的行記錄錯誤但不阻擋上傳。
- Telescope/Instrument（選填，前端預設 `Unknown`；可由檔名第一個 token 的字母部分 2–10 字推得，大寫），Observation Date（選填 `YYYY-MM-DD`；可由檔名 `YYYYMMDD[T_-]?HHMMSS` / `YYYY-MM-DD` 推得）。
- Payload：`{wavelength:[…], intensity:[…], telescope, original_filename, observation_date|null}` → #13/#14。
- 後端 `_resolve_spectrum_source_and_mjd`：source = `_clean_spectrum_source_name(telescope)` → `spectrum_id` 解析出的 source → 檔名推斷 → `'Unknown'`（清理規則：`/\` 轉 `-`，只保留 `0-9A-Za-z ._()+-`，長度 ≤ 80）；MJD = `spectrum_id` 中 `>1` 的 MJD → `observation_date` → 檔名日期 → `phase`（0 < v < 1000 時**直接把 phase 當 MJD 存**）→ 目前 UTC MJD。`spectrum_id = f"{source}@@{mjd:.6f}"`。同一 source+MJD 的第二次上傳會**追加**資料列（無唯一鍵），下次繪圖會合併成一條曲線。
- 下載格式（#18）：
  ```
  # <obj> spectrum  id=<spectrum_id>
  # Label: <spectrum_label>
  # Telescope: <source>
  # Phase: <phase>            ← 或 # Observation date: YYYY-MM-DD
  # wavelength intensity
  6562.8000  1.2345e-16
  ```

**光度繪圖（#21/#27，`DataVisualization.create_photometry_plot_from_db(photometry_data, redshift, ra, dec, as_json, apply_extinction, apply_k_corr)`）**：TNS 點去重（同 filter 1 天內有非 TNS 點則捨棄 TNS 點；TNS 自身同 filter 1 天內只留一點）；依 `filter_telescope` 分組，trace 名 `"{filter} - {telescope}"`、上限 `"… - Limit"`（前端 `_telFromTraceName` 依此解析）；`magnitude_error` 為 None/NaN/0 視為上限（`triangle-down-open`）；`total_shift = 距離模數 + K(=2.5log10(1+z), 若 k_corr) + V-band 消光(若 extinction)`，各 filter hover 的 Abs. Mag 用該 filter 的消光；右側 `yaxis2` 絕對星等軸（無 z 時標「Abs Mag (z N/A)」）；上方 `xaxis2` 日期軸；X 最少 5 天、Y 最少 3 mag 視窗。回傳 `fig.to_json()`；前端另加 `enforceMinLcXAxisSpan`、隱藏 legend 改用自建 `#photLegend`。`distance_modulus` 由 route 以 `ext_M_calculator.z_to_lmd(z)`（DETECT Planck18 cosmology）計算，供 KN 疊圖。

**光譜繪圖（#22/#29）**：`spectrum_id` 有值 → `create_spectrum_plot_from_db`（單條，y 範圍取 4500–7000 Å 2–98 百分位）；否則 `create_spectrum_list_plot_from_db`（全部，98 百分位正規化，`normalise` 改用 5000–7000 Å 中位數，`stack` 每條 +1.2 offset）。`rest_frame` 需 `redshift`（來自 `search_tns_objects` 第一筆）。回傳 `plotly.offline.plot(output_type='div', include_plotlyjs=False)` 的 HTML 字串，前端 `innerHTML` 後手動重新執行 `<script>`。

**KN 模型（#28）**：`kn_lc_mag.txt` 格式：`# Filter: sdss::g` 區塊標頭（取 `::` 後字串當 filter 名），資料列 4 欄 `time min median max`（絕對星等，時間為相對峰值天數）。前端以 `peakMjd + t`、`M + μ` 疊上 g/r/i 的 min–max 填色帶與 median 虛線。

**光譜線（#19/#20，`app/modules/spectral_lines.py`）**：24 個離子（H I、He I/II、Ca I/II、Si II/III、O I/II/III、Na I、Fe II/III、S II/III、C II/III/IV、Mg I/II、N II/III、Ti II、Ba II）3000–10000 Å（air）；保留有相對強度、禁線（M1/E2）或有傳統名稱者，2 Å 內去重取最強；`_TRAD` 表提供 Hα 等傳統標籤。快取 `app/modules/_spectral_lines_cache.json`（`{built_at,count,lines}`），TTL 30 天；`app/main.py` 啟動時也會 `warm_cache_async()`。前端 chip 只依 `_SPEC_LINES_BUILTIN` 的 label 建立，NIST 資料只替換 label 相同的線的波長，label 不在內建清單的 NIST 線永遠不會顯示。

**評論（#30–#33）**：`created_at` 為 ISO 字串（`comment_time`）；前端顯示 UTC。前端 `canEdit = isAdmin || 作者`，非 admin 作者看得到 Delete 按鈕但後端 #32 只允許 admin（會得到 403）。

**來源權限模型（特別說明 4）**：

- 表 `transient.object_source_permissions(id, object_name TEXT, data_type 'phot'|'spec', source_name TEXT, allowed_groups INT[] NULL, is_public BOOL DEFAULT false, updated_at, UNIQUE(object_name,data_type,source_name))`（由 `_ensure_extra_tables` 建立）。
- 表 `transient.default_permissions(source, permissions_set 'public'|'login'|'groups', groups INT[])`（系統層預設，由 admin 章節維護；本章只讀）。
- 語意（`filter_by_source_permissions`，admin 直接全通過）：
  1. 有 per-object override → `is_public` → 通過；否則未登入拒絕；`allowed_groups IS NULL` → 任何登入者通過（Members）；`= []` → 只有 admin（Blocked）；`[ids]` → 使用者 `session.groups` 名稱與 id→name 後的集合有交集才通過（Groups）。
  2. 無 override 但 `default_permissions` 有該 source → `public` 通過；`login` 登入即通過；`groups` 登入且（預設群組為空或有交集）通過。
  3. 都沒有 → `_system_default_for_source`：source 名含 `tns`（不分大小寫）→ public，否則 login。
- API（#35/#36）對外用**群組名稱**，DB 存 **group_id**；前端 UI 四態對應：Public=`{is_public:true, allowed_groups:null}`、Members=`{false,null}`、Groups=`{false,[names]}`、Blocked=`{false,[]}`。儲存時把 `_permData` 內**所有**來源（含 TNS 與從 defaults 預填者）都寫成 override。
- **實際套用範圍**：只有 #7/#23（photometry JSON）與 #21/#27（photometry plot）呼叫 `filter_by_source_permissions`；光譜相關端點（#8–#10、#18、#22、#29）與光度下載（#17/#26）**完全沒有套用**。

**物件群組權限模型（特別說明 4）**：

- 欄位 `transient.objects.permission`（`'public'|'login'|'groups'`）與 `transient.objects.groups INT[]`。
- `check_object_access(object_name, user_email=None, user_roles=0)`：`user_roles >= 50` 直接通過（**本章所有呼叫都沒傳 `user_roles`，所以 admin 不會自動通過**）；查 `WHERE name = %s`（精確）無列 → False；`public` → True；未登入 → False；`login` → True；`groups` 且 groups 非空 → 查 `auth.usr_group`（`status='joined'`）；其餘 False（含 `permission='groups'` 但 `groups` 為空）。
- `grant_object_permission` 會把 `permission` 設為 `'groups'` 並加入 gid；`revoke_object_permission` 只移除 gid，**不會**回復 `permission`。
- 套用端點：#21/#27（僅登入者）、#22/#29、#30。前端沒有任何可用 UI 修改此權限（`togglePermissionManager` 等為 dead code）。

**NED（#41–#43）**：解析 NED `ascii_bar` 輸出時自動偵測表頭欄位（`No.`/`Object Name`/`RA`/`DEC`/`Type`/`Redshift`/`Redshift Flag`），RA/Dec 支援十進位或 sexagesimal。`cat.ned(ned_id, object_name, ra_center, dec_center, radius_arcsec, searched_at, result_count, results JSONB)`，唯一鍵 `(object_name, radius_arcsec)`。`current_host` 讀 `transient.objects.host_name`，**整個程式碼庫（含 DETECT）沒有任何地方寫入該欄位**，所以除非 DB 外部寫入，`current_host` 永遠為 null。

---

## 導向與流程

1. **瀏覽物件**：Marshal / DETECT / 其他頁面連到 `/object/<name>` → （若帶前綴或 alias）302 → `/object/<canonical>` → 頁面渲染（同時寫入瀏覽紀錄、更新 brightest mag）→ JS 依序打 `/api/object/<name>` 直到成功 → 平行載入 DESI 圖、Aladin、光度、光譜、評論、DETECT、pin 狀態。找不到 → flash + `/marshal`。
2. **改狀態（admin）**：按鈕 → `confirm` → `POST /api/object/<full>/status` → 成功更新徽章（`clear` 則 reload）；失敗顯示通知。
3. **編輯欄位（admin）**：Edit → Modal → `POST /api/object/<full>/edit` → 成功 → 1 秒關 Modal、覆蓋層、再 1.5 秒 `location.reload()`（重新載入時頁面 route 會再算 abs mag）。
4. **光度**：Fetch（登入）→ `POST .../fetch_photometry`（web_api）→ reload；Upload（登入者看得到、admin 才能成功）→ 解析/對應/預覽 → `POST .../photometry/batch` → 重繪；Edit → Modal 勾選刪除 → Save → 逐筆 `DELETE /api/photometry/<id>` → 重繪；Add Point → `POST .../photometry` → 重繪；Download → Modal 條件 → 瀏覽器下載 `.dat`。
5. **光譜（登入且非 guest 才看得到面板）**：Upload（admin 才能成功）→ `POST .../spectroscopy` → 重繪；Download → 取清單第一筆 → `/api/spectrum/<id>/download`；toggles → 重新 `GET .../spectrum/plot`；光譜線 chip → 純前端 `Plotly.relayout`（第一次會 `GET /api/spectral-lines`）。
6. **評論**：`GET` 載入 → 「+」開表單 → `POST` → 重新載入；Edit → `PUT`；Delete → `confirm` → `DELETE`。
7. **來源權限（admin）**：頁面載入時 `sources` + `source-permissions` + `groups` → 卡片；任何變更 1.5 秒後自動 `POST .../source-permissions/batch`，或手動 Save now；Refresh Sources 重新載入。
8. **NED Explorer**：開啟 → `GET /api/ned/cone`（DB 快取優先）→ 表格 + Aladin 疊圖；Re-search → `force=1` 重新查 NED 並更新快取；Set as Host → `POST /api/ned/set_host`（**不持久化**）→ 前端更新本地 redshift 顯示與 HOST 徽章；逾時 → 10 秒自動重試。
9. **刪除物件**：`deleteObjects()` 存在於 JS 但**沒有任何按鈕呼叫**；若被呼叫：`prompt('DELETE')` + `confirm` → `DELETE /api/object/<full>/delete` → 3 秒後 `/marshal`。
10. **權限不足時的體驗**：未登入者能看頁面、公開來源的光度、DESI/Aladin；`guest` 角色登入者看不到 DETECT / 光譜 / 評論 / tags / Peak Abs Mag，但看得到 Fetch/Upload/Edit 光度按鈕（Upload/Edit 送出後 403）；非 admin 的 `user` 看得到光譜 Upload 按鈕（送出後 403）。

---

## 依賴的模組、資料表、檔案與外部服務

### 模組函式（簽名）

`app/modules/database/transient.py`
- `search_tns_objects(search_term='', object_type='', limit=100, offset=0, sort_by='discoverydate', sort_order='desc', …) -> list[dict]`（`OBJECT_COMPAT_COLS`，`ILIKE '%term%'` 於 name / prefix||name / internal_name / other_name）
- `update_object_status(object_name, status) -> bool`；`update_object_activity(objid, activity_type=None)`（no-op，**已 import 未使用**）
- `update_object_abs_mag(target_name) -> bool`（依賴 `function.module.screening.absolute_magnitude`，DETECT 不可 import 時回 False）
- `_parse_spectrum_id(spectrum_id) -> (source, mjd|None)`、`_build_spectrum_label(source, mjd) -> str`、`_format_spectrum_observation_label(mjd) -> str`、`_phase_from_stored_value(value) -> float|None`
- `class TNSObjectDB`（staticmethods）：`add_photometry_point(object_name, mjd, magnitude=None, magnitude_error=None, filter_name=None, telescope=None) -> int|None`、`add_photometry_batch(object_name, points) -> int`、`sync_last_photometry_date(object_name)`、`get_photometry(object_name) -> list[dict]`、`delete_photometry_point(point_id) -> bool`、`add_spectrum_data(object_name, wavelength_data, intensity_data, phase=None, telescope=None, spectrum_id=None, original_filename=None, observation_date=None) -> str`、`get_spectroscopy(object_name) -> list[dict]`、`get_spectrum_list(object_name) -> list[dict]`、`delete_spectrum(spectrum_id) -> bool`、`add_comment(object_name, user_email, user_name, user_picture, content) -> int|None`、`get_comments(object_name) -> list[dict]`、`get_comment_by_id(comment_id) -> dict|None`、`delete_comment(comment_id) -> bool`、`update_comment(comment_id, content) -> bool`、`log_object_view(object_name, user_email=None)`
- 內部：`_resolve_obj_id`、`_resolve_obj_id_with_prefix`、`_mjd_update`、`_resolve_spectrum_source_and_mjd`、`_build_spectrum_id`、`_STATUS_MAP`

`app/modules/database/__init__.py`：`get_tns_db_connection() -> _PooledConn`（**呼叫端必須 `close()`** 才會歸還 pool）、`get_db_connection()`（context manager，**已 import 未使用**）、`OBJECT_COMPAT_COLS`

`app/modules/database/auth.py`：`get_all_groups() -> dict[name, info]`（註解型別寫 `list[dict]`，實際回 dict；route 有轉換）、`get_object_permissions(object_name) -> {'permission','groups'}`、`grant_object_permission(object_name, group_name, granted_by='') -> bool`、`revoke_object_permission(object_name, group_name) -> bool`、`check_object_access(object_name, user_email=None, user_roles=0) -> bool`、`get_source_permissions(object_name, data_type='phot') -> list[dict]`、`get_default_source_permissions(source_name=None) -> list[dict]`、`set_source_permissions_batch(object_name, data_type, permissions) -> bool`、`filter_by_source_permissions(object_name, data_type, source_list, user_email=None, user_groups=None, is_admin=False)`

`app/modules/database/catalog.py`：`get_ned_cache(object_name, radius_arcsec) -> dict|None`、`upsert_ned_cache(object_name, ra_center, dec_center, radius_arcsec, results) -> None`

`app/modules/data_processing.py::DataVisualization`：`create_photometry_plot_from_db(photometry_data, redshift=None, ra=None, dec=None, as_json=False, apply_extinction=True, apply_k_corr=True)`、`create_spectrum_plot_from_db(spectrum_data, spectrum_id, rest_frame=False, redshift=None, normalise=False)`、`create_spectrum_list_plot_from_db(spectrum_data, rest_frame=False, redshift=None, normalise=False, stack=False)`、`get_filter_color(filter_name, alpha=1)`（`app/data/filter_colors.json`）

`app/modules/ext_M_calculator.py`：DETECT `function.module.calculator` 的 re-export：`z_to_lmd(z) -> (d_Mpc, …)`、`get_extinction(ra, dec, filter)`（SFD 塵埃圖，首次使用時下載到 `DETECT_DATA_DIR`）、`cosmo`（Planck 2018）等

`app/modules/astronomy_calculator.py`：`calculate_redshift_distance(redshift, redshift_error=None, H0=67.7, Om0=0.309, Tcmb0=2.725) -> dict`

`app/modules/spectral_lines.py`：`get_spectral_lines() -> list[dict]`、`warm_cache_async() -> None`（背景執行緒 `nist-spec-lines`）

`app/modules/request_validation.py`：`get_float_arg(name, default=None, min_val=-999999, max_val=999999)`、`get_int_arg`（**已 import 未使用**）、`ParamOutOfRangeError`

### 資料表

| 表 | 讀 | 寫 |
|---|---|---|
| `transient.objects` | 物件查詢（多欄）、`permission/groups`、`host_name`、`status` | `status`、`redshift`、`internal_name`、`tag`、`brightest_mag`、`brightest_abs_mag`、`last_phot_date`（`_mjd_update` 亦可能 `Snoozed→Inbox`）、`permission`、`groups`、DELETE |
| `transient.photometry` | 光度、來源清單 | INSERT（`phot_uniq`）、DELETE by `phot_id` |
| `transient.spectroscopy` | 光譜、清單、下載 | INSERT、DELETE by source(+MJD) |
| `transient.comments` | 評論 | INSERT / UPDATE / DELETE |
| `transient.object_views`、`transient.object_views_detail` | — | 每次頁面瀏覽 |
| `transient.object_source_permissions` | 過濾、admin 面板 | UPSERT |
| `transient.default_permissions` | 過濾、admin 面板 | — |
| `auth.users` | `usr_id`、評論作者 | — |
| `auth.groups`、`auth.usr_group` | 群組 id/name、成員 | — |
| `cat.ned` | NED 快取 | UPSERT |

### 檔案與外部服務

- 讀：`app/modules/web_data/kn_lc_mag.txt`；讀/寫：`app/modules/_spectral_lines_cache.json`（由背景執行緒寫）。
- 伺服器端外部服務：NED `https://ned.ipac.caltech.edu/cgi-bin/objsearch`（cone search 代理）；NIST ASD（`astroquery.nist`，背景）；DETECT 套件（`app/modules/DETECT`，abs mag / 消光 / 宇宙學）；astropy。
- 瀏覽器端外部服務：`legacysurvey.org`（cutout、viewer）、CDS Aladin Lite + HiPS、`wis-tns.org`、NED 網頁（cone search、extinction calculator）、`cdn.plot.ly`、`code.jquery.com`。
- 背景執行緒：`nist-spec-lines`（#19 冷快取、#20）。
- 快取：`_KN_MODEL_CACHE`（程序記憶體，永不失效）、`_spectral_lines_cache.json`（30 天）、`cat.ned`（永久，`force=1` 覆寫）、`_knModelData`／`_specLinesNist`／`nedData`（瀏覽器記憶體）。

---

## 前端檔案

- 模板：`app/routes/marshal/templates/object_detail.html`（include `_favicon.html`、`_navbar.html`，兩者位於 `app/routes/basic/templates/`）。
- CSS：`app/routes/marshal/static/css/object_detail/object_detail_main.css`（模板直接引用；內部 `@import` `base.css`、`layout.css`、`components.css`、`modal.css`、`responsive.css`）、`responsive.css`（模板另外再直接引用一次）；目錄內檔案清單：`base.css`、`components.css`、`layout.css`、`modal.css`、`object_detail_main.css`、`responsive.css`。
- JS：`app/routes/marshal/static/js/object_detail.js`；模板尾端另有一段內嵌 tooltip 腳本。

### `object_detail.js` 呼叫的端點清單

| 端點 | 函式 | 所屬 |
|---|---|---|
| `GET /api/object/<name>` | `searchObjectByName`（4 個候選名） | 本章 #1/#3 |
| `POST /api/object/<full>/status` | `changeStatus` | #6 |
| `POST /api/object/<full>/edit` | `submitEditObject` | #4 |
| `DELETE /api/object/<full>/delete` | `deleteObjects`（無呼叫者） | #5 |
| `GET /api/object/<clean>/photometry/plot?extinction&k_corr` + `GET /api/object/<clean>/photometry` | `loadPhotometryPlot` | #21/#27、#7/#23 |
| `POST /api/object/<clean>/photometry` | `addPhotometryPoint`、`savePhotometryChanges`（toAdd 恆空） | #11/#24 |
| `DELETE /api/photometry/<id>` | `savePhotometryChanges` | #15 |
| `POST /api/object/<clean>/photometry/batch` | `uploadPhotometryData` | #12/#25 |
| `GET /api/object/<clean>/photometry/download?…` | `doDownloadPhotometry`（`<a download>`） | #17/#26 |
| `GET /api/kn_model` | `_applyKnModelOverlay` | #28 |
| `GET /api/object/<clean>/spectrum/plot?rest_frame&normalise&stack` | `loadSpectrumPlot` | #22/#29 |
| `GET /api/object/<clean>/spectroscopy` → `GET /api/spectrum/<id>/download` | `downloadCurrentSpectrum` | #8/#9、#18 |
| `POST /api/object/<clean>/spectroscopy` | `submitSpectrumData` | #13/#14 |
| `GET /api/spectral-lines` | `_fetchNistSpecLines` | #19 |
| `GET/POST /api/object/<clean>/comments`、`PUT/DELETE /api/comments/<id>` | `loadComments`、`submitComment`、`saveEditComment`、`deleteComment` | #30–#33 |
| `GET /api/object/<clean>/sources`、`GET …/source-permissions`、`GET /api/groups`、`POST …/source-permissions/batch` | `loadPermissionsPanel`、`savePermissions` | #34–#37 |
| `GET /api/groups`、`GET/POST/DELETE /api/object/<objectName>/permissions` | `loadGroups`、`loadPermissions`、`grantPermission`、`revokePermission`（dead code） | #37–#40 |
| `GET /api/ned/cone?ra&dec&radius_arcsec&object_name&force` | `fetchNEDData` | #41 |
| `POST /api/ned/set_host`、`POST /api/ned/unset_host` | `setNEDHost`、`unsetNEDHost` | #42、#43 |
| `GET /api/object/<clean>/detect_cross_match[?force=true]` | `loadDetectData`、`forceDetectRun` | `web_api_bp`（他章） |
| `GET /api/object/<clean>/detect_images`、`POST …/detect_images/generate` | `loadDetectImages`、`generateDetectImages` | `web_api_bp` |
| `GET /detect_image_by_id/<image_id>` | `_renderDetectChartView`（`<img>`） | `detect_bp` |
| `GET /api/object/<clean>/pin_status`、`POST …/toggle_pin` | `checkPinStatus`、`togglePin` | `web_api_bp` |
| `POST /api/object/<objectName>/fetch_photometry` | `fetchPhotometry` | `web_api_bp` |
| `GET …/flag_status`、`POST …/toggle_flag` | `checkFlagStatus`、`toggleFlag`（整段註解掉） | `web_api_bp` |
| `/finding_chart?…`、`/interactive_planner?…`、`/marshal` | `openFindingChart`、`openVisibilityPlot`、`deleteObjects` | `astronomy_tools`、`marshal` |

---

## 已知問題與注意事項

### 安全 / 權限
1. **來源權限只套用在光度 JSON 與光度繪圖**：`download_photometry`／`download_photometry_generic`（#17/#26）只要登入就回傳**全部**光度點，繞過 source permissions；所有光譜端點（#8–#10、#18、#22、#29）從未呼叫 `filter_by_source_permissions`，因此 admin 面板的「Spectroscopy」分頁設定沒有任何效果。
2. **物件層級權限對 admin 不生效**：`check_object_access` 只在 `user_roles >= 50` 時略過檢查，但本 blueprint 呼叫時從未傳 `user_roles`，所以 `permission='groups'` 的物件連 admin（若不在群組）也會被光譜圖、評論、光度圖拒絕；而**未登入者**在光度圖端點完全不做物件層級檢查（只做來源過濾）。
3. `revoke_object_permission` 不會把 `permission` 從 `'groups'` 改回，群組清空後 `check_object_access` 對所有人回 False（物件變成無人可看光譜/評論）。
4. `check_object_access`、`get_comments`、`get_object_permissions` 用 `name = %s` 精確比對，URL 層卻是 `ILIKE`：`/object/2025ABC` 能開頁面，但 JS 以 `2025ABC` 打光度/光譜/評論端點時 `_resolve_obj_id_with_prefix` 精確比對失敗 → 空資料；`check_object_access` 查無列 → 「Access denied.」。
5. `/api/object/<name>`（#3）對未登入者也回傳 `permission`、`groups`、`pin`、`status` 等內部欄位；頁面 route 的 `tagsContainer` 雖依 `visibility.tags` 裁切，但 JS `renderCustomTags(objectData.tags)` 會用 API 結果重建，guest 仍看得到 tags。
6. `delete_spectrum`（#16）與 `download_spectrum_file`（#18）以 `source (+MJD)` 全表操作，不限定物件：不同物件若上傳時只給日期（MJD 相同）且 telescope 相同，刪其中一個會一併刪掉另一個；下載則可能混入他物件資料。
7. `visibility.phot_controls = is_logged_in`，`guest` 角色也看得到 Upload / Edit（後端 admin-only → 403）；光譜 Upload 對所有非 guest 顯示，後端也 admin-only。評論 Delete 按鈕對作者顯示但後端只准 admin。

### 資料正確性
8. **NED「Set as Host」不持久化**：`ned_set_host`／`ned_unset_host` 只驗證與 log，不寫 DB 也不寫 session（docstring 與實作不符）；`ned_cone_search` 的 `current_host` 讀 `transient.objects.host_name`，但整個程式碼庫沒有任何寫入者，所以重開 Modal 後 HOST 徽章與前端暫改的 redshift 都會消失，`redshift` 也從未寫回 `transient.objects`。
9. 頁面每次瀏覽都會執行 `update_object_abs_mag` 寫 `brightest_mag/brightest_abs_mag`（非 TNS 樣式名稱時 JS 打到 #3 會再寫一次），並寫 `object_views*`；未登入者也會觸發。
10. 光度/光譜繪圖端點以 `search_tns_objects(search_term=object_name, limit=1)`（`ILIKE '%name%'`、依 discovery_date DESC）取 redshift/ra/dec，名稱為他物件子字串時（如 `2025a` vs `2025ab`）可能取到錯誤物件的參數；`#2` 的 regex 搜尋亦非錨定。
11. `api_edit_object` 以 `OBJECT_COMPAT_COLS` 回傳的 `internal_names`（`internal_name || ', ' || other_name`）預填表單，原樣儲存會把 `other_name` 併入 `internal_name`。
12. `upload_photometry*`：`magnitude` / `magnitude_error` 為 `0` 時被 falsy 判斷成 `None`（0 誤差會被存成上限）；`mjd` 缺少時 `float(None)` → 500 而非 400。`add_photometry_point` 遇負星等回 `None`，route 仍回 `success:true, id:null`。
13. `add_spectrum_data` 在物件不存在時仍回 `success:true`（實際未寫入）；同 source+MJD 重複上傳會追加資料列（無唯一鍵），繪圖時合併；phase 值（0–1000）與真實 MJD 共用 `"MJD"` 欄。
14. `api_delete_object`：先 `DELETE transient.objects`，之後清理 photometry/spectroscopy/comments 的子查詢 `WHERE name = %s` 已查不到物件，清理為 no-op（依賴 FK CASCADE）；且同一 `_PooledConn` `close()` 兩次並在 `close()` 後 `commit()`，依 psycopg2 pool 行為第二次會拋 `PoolError`（或連線已實體關閉時 `InterfaceError`），被外層 `except` 接住後**即使刪除已 commit 仍回 500**。目前只有 dead code `deleteObjects()` 會呼叫此端點。
15. 兩條頁面 route 在例外路徑不會 `conn.close()`（`get_tns_db_connection` 需手動歸還），例外頻繁時會耗盡連線池（maxconn 60）。
16. `get_object_photometry_plot`（#21）在 `search_tns_objects` 無結果時 `obj_data = {}` 繼續繪圖（無 z），generic 版（#27）則回 404；兩版行為不一致。`#2` 不接受 `clear`，`#6` 接受。

### 死程式碼 / 不存在的對應
17. `object_detail.js` 中無任何呼叫者的函式：`deleteObjects`、`exportObject`、`togglePermissionManager`、`loadGroups`、`loadPermissions`、`grantPermission`、`revokePermission`（引用的 DOM `#permissionManager`、`#groupSelect`、`#permissionStatus`、`#currentPermissionsList` 皆不存在，且 `loadPermissions` 把 #38 回傳的 dict 當 list 用 `.length`/`perm.group_name`）、`refreshStarMap`、`updateKnModelOverlay`、`getNotificationIcon`、`getTimeAgo`、`getTimeAgoSimple`、`_validatePhotometryData_legacy`；`checkFlagStatus`／`toggleFlag` 整段註解。
18. JS 更新但模板不存在的元素（皆有 null 保護）：`breadcrumbCurrent`、`objectType`、`discoveryDate`、`raDecimal`、`decDecimal`、`discoveryMag`、`redshift`、`hostGalaxy`、`hostRedshift`、`reportingGroup`、`discoverySurvey`、`timeReceived`、`remarks`、`bibcode`、`externalId`、`detectChipSummary`、`aladinLoading`、`uploadProgressSection/Bar/Text`、`flagBtn`；`matchStarMapHeight` 查 `.detail-left .info-card:first-child` 永遠為 null（no-op）；`#visibilityConfig` 的 data 屬性沒有被 JS 讀取。
19. 後端存在但前端未使用：`GET /api/object/<Y><L>/spectrum/<spectrum_id>`（#10）、`POST /api/spectral-lines/rebuild`（#20）、`/permissions` 三端點（僅 dead code 呼叫）、`/delete`（僅 dead code）。
20. `object_routes.py` 未使用的 import：`get_db_connection`、`get_int_arg`、`update_object_activity`；`update_object_activity` 本身為 no-op。
21. 「Edit Photometry」的 Save Changes 只會處理刪除（`photometryChanges.toAdd` 永不填入）；「Finished」狀態按鈕以 Jinja 註解停用。
22. `get_spectral_lines` 例外時回 HTTP 200 且 `success:false`（前端當「builtin」處理）。

### 路由結構
23. 同一 URL 以不同 converter 重複定義（非錯誤，但造成程式碼重複）：頁面 2 條；API 對 photometry（GET/POST/batch/download/plot）、spectroscopy（GET/POST）、spectrum/plot、object JSON、status 各有 `<int:year><alpha:letters>` 與 `<object_name>` 兩版，邏輯幾乎相同但細節（404 vs 空物件、`clear`）不同；`upload_spectroscopy` 只是委派。`/api/object/<string:object_name>/spectroscopy`（POST）與 `/api/object/<object_name>/spectroscopy`（GET）是同一規則不同寫法。
24. `objects_bp` 未宣告 `template_folder`，模板可用完全依賴 `marshal_bp`（`marshal_routes.py`）的宣告；若日後拆開註冊，`render_template('object_detail.html')` 會 `TemplateNotFound`。
25. `url_for('marshal_bp.object_detail_generic', object_name='2025abc')` 產生的 URL 實際由 `object_detail_tns_format` 處理（見匹配優先順序），generic 的 canonical redirect 因此「跳到另一個函式」；`marshal.html` 對無前綴 TNS 名用 `object_detail_tns_format`、其餘用 `object_detail_generic`，兩者皆正確存在。
26. 全域 `_block_pipe_in_api_params` 會讓含 `|` 的評論、tags、上傳資料一律 400；`get_float_arg` 的通用範圍 ±999999 對 MJD 過濾足夠，但 `radius_arcsec` 沒有額外上限（前端限制 1–600，後端只受 ±999999 限制，可對 NED 發出極大半徑查詢）。
27. 沒有 TODO / FIXME 註解；程式碼內以 `print`／`traceback.print_exc()` 與 `logger` 混用輸出錯誤。
