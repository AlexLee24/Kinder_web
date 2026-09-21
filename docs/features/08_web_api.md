# 第 8 章　Web API（`web_api` blueprint）

> **注意**：本章記錄的是重構前（commit `c7f91a4`，2026-09-21）的狀態，檔案路徑為舊位置（`app/routes/…`、`app/modules/…`）。新位置請對照 `docs/ARCHITECTURE.md` §6「新舊路徑對照」；功能與行為在重構後完全相同。

> 檔案：`app/routes/web_api/web_api_routes.py`（1,045 行）
> Blueprint：`web_api_bp = Blueprint('web_api', __name__, template_folder='templates', static_folder='static')`，**無 `url_prefix`**（每個 route 自行以 `/api/...` 開頭）。
> 註冊順序：`app/routes/__init__.py::register_routes()` 中第 6 個註冊（順序：`auth` → `admin` → `astronomy_tools` → `objects` → **`api`** → **`web_api`** → `private_area` → `basic` → `marshal` → `detect` → `web_log` → `database_status` → `games` → `planners`）。
> 本章所有結論皆逐行核對原始碼（含被呼叫的 `modules/*`），並以專案 `.venv`（Flask 3.1.3 / Werkzeug 3.1.8）實測路由衝突行為。

---

## 概要

`web_api` blueprint 是 Kinder Web 中「純 JSON」的雜項 API 集合，沒有任何頁面模板（`templates/`、`static/css`、`static/js` 三個資料夾都存在但**完全是空的**）。共 **23 個 route**（22 條 URL 規則，其中 `/api/objects` 分 GET / POST 兩個函式），依功能可分為八組：

| 組別 | 端點 | 認證方式 |
|---|---|---|
| A. 金鑰 / 測試 | `POST /api/generate_key`、`GET|POST /api/test` | 無 / API key |
| B. 觀測 API v1（給外部程式、望遠鏡端腳本） | `/api/v1/observation_targets`、`/api/v1/observation_logs` | API key |
| C. DETECT 觸發與影像 | `/api/object/<name>/detect_cross_match`、`.../detect_images`、`.../detect_images/generate` | **無**（公開） |
| D. 物件新增 / 查詢 / 標籤 / 分類 / 統計 | `POST /api/objects`、`GET /api/objects`、`POST /api/object-tags`、`GET /api/classifications`、`GET /api/stats` | session（部分公開） |
| E. flag / pin | `.../flag_status`、`.../toggle_flag`、`.../pin_status`、`.../toggle_pin` | session |
| F. 光度抓取 | `POST /api/object/<name>/fetch_photometry` | session |
| G. TNS 手動下載 / 搜尋 / 統計 | `/api/tns/manual-download`、`/api/tns/search`、`/api/tns/stats` | session |
| H. auto-snooze | `/api/auto-snooze/manual-run`、`/status`、`/stats` | session |

**兩種認證並存**：A、B 組用 API key（`X-API-Key` header 或 `?api_key=`），其餘用 Flask session（`session['user']`）。C 組三個 DETECT 端點**完全沒有任何認證**。

### 對本章所有端點都生效的全域行為（定義在 `app/main.py`）

| 機制 | 行為 | 影響 |
|---|---|---|
| `_enforce_allowed_host`（`before_request`） | `request.host` 不在 `{APP_BASE_URL 的 netloc}`（DEBUG 時另加 `HOST:PORT`、`localhost:PORT`、`127.0.0.1:PORT`）→ `abort(404)` | 直接以 IP 呼叫 API 會得到 404 |
| `_block_pipe_in_api_params`（`before_request`） | 路徑以 `/api/` 開頭時，只要 query string 值、form 值、或 JSON body（遞迴檢查 dict 值 / list 元素 / 字串）含 `\|` → `400 {"error": "Invalid character '\|' is not allowed"}` | 所有本章端點；只檢查「值」不檢查 key |
| `refresh_user_session`（`before_request`，來自 `routes/auth/auth_routes.py`） | 有 `session['user']` 時每個請求都以 `get_user(email)` 重讀 `auth.users` + `auth.usr_group`，同步 `is_admin`、`is_great_lab_member`、`picture` 進 session，並設 `g.current_user` | session 型權限判斷即時反映 DB；DB 掛掉時靜默略過 |
| `_handle_param_out_of_range`（`errorhandler`） | `modules.request_validation.ParamOutOfRangeError` → `400 {"error": "Parameter 'x' has an invalid value (...); expected a number between ..."}` | `GET /api/objects` 的數值參數錯誤走這條 |
| `_add_isolation_headers`（`after_request`） | 所有回應加 `Cross-Origin-Opener-Policy: same-origin`、`Cross-Origin-Resource-Policy: same-origin` | 未設任何 CORS header → 瀏覽器跨網域 `fetch` 會被擋；curl / `requests` 不受影響 |
| `_log_request_access`（`after_request`） | 僅 `ACCESS_LOG_ENABLED=1` 時記錄 method/path/status/duration/ip/user（不含 query string） | — |

---

## API 與動作端點

### 總表

權限欄位代號：**公開** = 無任何檢查；**需登入** = `'user' in session`（**含 `role='guest'` 的使用者**，本章沒有任何端點排除 guest）；**僅 admin** = `session['user']['is_admin']`；**API key** = `X-API-Key` header（`/api/v1/*` 另接受 `?api_key=`），以 `modules.database.auth.get_user_by_api_key()` 查 `auth.users.api_key` 精確比對。

| # | 方法 | 路徑 | endpoint | 權限（未通過時回應） | 輸入 | 成功回應 | 失敗回應 | 副作用 |
|---|---|---|---|---|---|---|---|---|
| 1 | POST | `/api/generate_key` | `web_api.generate_key`（**被 `api.generate_key` 遮蔽，實際不會執行**） | 公開 | 無 | 無（恆 403） | `403 {"success": false, "error": "Self-service key generation is disabled. ..."}`；**實際生效的是 `api_routes.py` 版本：`403 {"error": "..."}`（無 `success` 鍵）** | 無 |
| 2 | GET, POST | `/api/test` | `web_api.api_test` | API key（**僅 header**；缺 → `401 {"success": false, "error": "Missing API Key in headers (X-API-Key)"}`；錯 → `401 {"success": false, "error": "Invalid API Key"}`） | header `X-API-Key` | `{"success": true, "message": "API Authentication successful!", "user": {name, email, role, is_admin, groups}}`（`groups` **恆為 `[]`**） | 401 | 讀 `auth.users` |
| 3 | GET | `/api/v1/observation_targets` | `web_api.api_v1_observation_targets` | API key（header 或 `?api_key=`；缺 → `401 {"success": false, "error": "Missing API key. Use X-API-Key header or ?api_key= param."}`；錯 → `401 {"success": false, "error": "Invalid API key."}`） | query `telescope`（選填，`SLT`/`LOT`，不分大小寫；其他 → `400 telescope must be SLT or LOT`） | `{"success": true, "generated_at": "YYYY-MM-DDTHH:MM:SSZ", "requested_by": email, "SLT": [...], "LOT": [...]}`（有 filter 時只含該鍵） | `500 {"success": false, "error": "Database error: ..."}` | 讀 `obs.targets` ⋈ `auth.users`；**每次呼叫執行 `ALTER TABLE obs.targets ADD COLUMN IF NOT EXISTS auto_exposure`** |
| 3' | POST | `/api/v1/observation_targets` | 同上 | API key 且 `is_great_lab_member` **或** `is_admin`（否則 `403 {"success": false, "error": "Forbidden: requires GREAT Lab member or admin role"}`）。**實際上只有 admin 能過**（見「驗證與權限模型」） | JSON：`telescope`*、`name`*、`ra`*、`dec`*（**必須是字串**）、`mag`、`priority`（Normal/High/Urgent，預設 Normal）、`repeat_count`（int，預設 0）、`auto_exposure`（bool，LOT 強制 false）、`filters`、`plan`、`program`、`note_gl` | `201 {"success": true, "message": "Target X added to SLT", "id": target_id, "target": {id, telescope, name, ra, dec, mag, priority, repeat_count, auto_exposure}}` | `400`（欄位缺漏/非法值）；`500 {"success": false, "error": "Failed to save target"}`（RA/Dec 解析失敗等）；`500 {"success": false, "error": str(e)}`；**`ra`/`dec` 為 JSON 數字 → 未捕捉的 `AttributeError` → Flask 預設 500 HTML** | `INSERT INTO obs.targets ... ON CONFLICT (name, telescope) DO UPDATE`（**同名同望遠鏡會被靜默覆寫**）；讀 `auth.users` 取 `create_by`；DDL 同上 |
| 4 | GET | `/api/v1/observation_logs` | `web_api.api_v1_observation_logs` | API key（同 #3） | query `year`+`month`（int）或 `date`（`YYYY-MM-DD`，優先） | `{"success": true, "generated_at", "requested_by", "query_params": {year, month, date}, "logs": [...]}` | `400 {"success": false, "error": ...}`（缺參數 / 日期格式 / 非整數）；`500 {"success": false, "error": str(e)}` | 讀 `obs.logs` ⋈ `auth.users` ⋈ `obs.targets` |
| 4' | POST | `/api/v1/observation_logs` | 同上 | API key（**任何有效 key 即可寫入，無角色檢查**） | JSON：`action`（`upsert` 預設 / `delete`）、`target_name`*、`obs_date`*、`telescope`、`is_triggered`、`is_observed`、`trigger_filter`/`trigger_exp`/`trigger_count`、`observed_filter`/`observed_exp`/`observed_count`、`user_name`、`priority`、`program` | upsert：`{"success": true, "message": "Log saved", "log": {...回顯...}}`；delete：`{"success": true, "message": "Log deleted for X on D"}` | `400`（缺 `target_name`/`obs_date`、日期格式）；`500 {"success": false, "error": "Failed to save log"}` / `"Failed to delete log or log not found"` / `str(e)` | 讀 `auth.users`（by email **或** name）、`obs.targets`；`INSERT`/`UPDATE`/`DELETE obs.logs` |
| 5 | GET | `/api/object/<object_name>/detect_cross_match` | `web_api.trigger_detect_cross_match` | **公開（無任何檢查）** | path `object_name`（自動去掉 `AT`/`SN` 前綴、不分大小寫）；query `force=true` | `{"success": true, "ran_now": bool, "results": [...], "screen": {...}\|null, "detect_image_id": int\|null}` | `404 Object not found in database`；`503 DETECT is not enabled in this web instance (DETECT_IN_WEB=0)`；`500 str(e)` | 讀 `transient.objects`/`cross_matches`/`detect_screen`/`target_images`；**GET 有副作用**：未跑過或 `force=true` 時同步執行 DETECT pipeline（寫 `cross_matches`、`detect_screen`(+history)、`target_images`、`objects.tag/brightest_*`；外部 NOIRLab TAP、Legacy Survey cutout；`job_status`），然後 `_soft_invalidate_page_cache()` 啟動背景重建執行緒；`get_detect_results_for_target` 每次執行 4 條 `ALTER TABLE` |
| 6 | GET | `/api/object/<object_name>/detect_images` | `web_api.list_detect_images` | **公開** | path `object_name`（**精確比對**，不去前綴、區分大小寫） | `{"success": true, "images": [{"image_id", "source"}]}`（**最多 1 筆**） | `500 {"success": false, "error": str(e)}` | 讀 `transient.target_images` ⋈ `objects` |
| 7 | POST | `/api/object/<object_name>/detect_images/generate` | `web_api.generate_detect_images` | **公開** | path `object_name`（不分大小寫、不去前綴） | `{"success": true, "images": [...], "detect_image_id": int\|null}` | `404 Object not found`；`503`（DETECT 關閉）；`500` | 同步執行 DETECT pipeline（同 #5 的寫入與外部呼叫）；**不**使 DETECT 頁快取失效 |
| 8 | POST | `/api/objects` | `web_api.add_object` | 僅 admin（`403 {"error": "Access denied - Admin privileges required"}`） | JSON：`name`*（≥3 字）、`ra`*（0≤ra<360）、`dec`*（−90..90）、`type`（預設 `AT`）、`magnitude`（−5..30）、`discovery_date`（`YYYY-MM-DD`，預設今天）、`source`（預設 `Manual Entry`） | `{"success": true, "message": "Object X added successfully", "object_name", "objid"}` | `400 {"error": ...}`（缺欄位、範圍、格式、**已存在（子字串比對）**、`Invalid input data: ...`）；`500 {"error": "Database error: ..."}` | `INSERT INTO transient.objects`（`status='Object'`、`name_prefix=''`、`tag='{}'`、`discovery_date`=整數 MJD）；使用 raw pooled 連線，**例外時連線外洩** |
| 9 | GET | `/api/object/<path:object_name>/flag_status` | `web_api.get_flag_status` | 需登入（`401 {"error": "Unauthorized"}`） | path | `{"is_flagged": bool}` | — | `ALTER TABLE transient.cross_matches ADD COLUMN IF NOT EXISTS flag` + commit（每次）；讀 `cross_matches` ⋈ `objects` |
| 10 | POST | `/api/object/<path:object_name>/toggle_flag` | `web_api.update_flag_status` | 需登入（含 guest；`401 {"error": "Unauthorized"}`） | JSON `flag`*（任意值；`null`/缺 → `400 {"error": "Missing flag status"}`；非 JSON body → Flask 415） | `{"success": true, "is_flagged": <原樣回顯輸入>}` | `500 {"error": "Database error"}` | DDL 同 #9；`UPDATE transient.cross_matches SET flag=%s WHERE obj_id=(...)`（該物件**所有** cross-match 列；0 列亦回 success） |
| 11 | GET | `/api/object/<path:object_name>/pin_status` | `web_api.get_pin_status` | 公開（未登入回 `200 {"is_pinned": false}`） | path | `{"is_pinned": bool}` | — | 讀 `transient.objects.pin`（name 或 prefix+name） |
| 12 | POST | `/api/object/<path:object_name>/toggle_pin` | `web_api.toggle_pin_status` | 僅 admin（`403 {"error": "Access denied"}`） | 無 | `{"success": true, "is_pinned": bool}`（物件不存在亦回 success/false） | — | `UPDATE transient.objects SET pin = NOT pin ... RETURNING pin` |
| 13 | POST | `/api/auto-snooze/manual-run` | `web_api.manual_auto_snooze` | 僅 admin（`403 {"success": false, "error": "Admin access required"}`） | 無 | `{"success": true, "snoozed_count": <DB 內 Snoozed 總數>, "finished_count": <DB 內 Finish 總數>, "message": "Auto-snooze completed successfully"}` | `500 {"success": false, "error": "Auto-snooze failed"}` / `str(e)` | 同步執行 `auto_snoozed(now_utc, debug=True)`：`UPDATE transient.objects.status`（Follow-up→Finish、其他→Snoozed） |
| 14 | GET | `/api/stats` | `web_api.api_get_stats` | 公開（未登入回全 0） | 無 | `{"success": true, "stats": {inbox_count, followup_count, finished_count, snoozed_count, flag_count(恆 0), at_count, classified_count, total_count}}` | 預期 `500` JSON，**但 `web_api_bp.logger` 不存在 → AttributeError → Flask 預設 500** | 6 次 `COUNT` 讀 `transient.objects` |
| 15 | POST | `/api/object/<path:object_name>/fetch_photometry` | `web_api.fetch_photometry` | 需登入（含 guest；`403 {"error": "Access denied"}`） | 無 | `{"success": true, "message": "Photometry fetch completed for X"}`（**物件不存在或沒抓到資料也回成功**） | `500 {"success": false, "error": str(e)}` | 同步（阻塞）執行 `process_single_object_workflow`：TNS bot API、ATLAS/Pan-STARRS（Playwright headless Chromium 登入）、ALeRCE（ZTF/LSST）；寫 `transient.objects.internal_name`、`transient.photometry`、`objects.last_phot_date`；暫存檔 `app/data/phot_cache/<year>/<name>_photometry.txt`（用完刪除） |
| 16 | GET | `/api/objects` | `web_api.api_get_objects` | **公開（無任何檢查）** | query `page`、`per_page`、`sort_by`、`sort_order`、`search`、`classification`、`tag`、`date_from`、`date_to`、`app_mag_min/max`、`redshift_min/max`、`discoverer` | `{"objects": [...], "total", "total_pages", "page", "per_page", "stats": {total, object, followup, finished, snoozed}}` | 數值參數非法 → `400 {"error": ...}`（app 層 handler）；其他例外預期 `500` JSON，**但 `web_api_bp.logger` bug → Flask 預設 500** | 3 次查詢 `transient.objects`（`tag=flag` 時另 EXISTS `cross_matches`）；回傳含 `permission`、`groups` 欄，**未做任何權限過濾** |
| 17 | POST | `/api/object-tags` | `web_api.api_get_object_tags` | 需登入（`403 {"error": "Access denied"}`） | JSON `object_names`（list[str]） | `{"success": true, "tags": {name: "object"\|"followup"\|"finished"\|"snoozed"}, "object_tags": {name: "a, b"\|null}}` | 預期 `500` JSON，**但 `web_api_bp.logger` bug → Flask 預設 500** | 讀 `transient.objects`（`name IN (...)`）；raw 連線，**例外時外洩** |
| 18 | GET | `/api/classifications` | `web_api.api_get_classifications` | 公開（未登入回 `{"success": true, "classifications": []}`） | 無 | `{"success": true, "classifications": [distinct type ...]}` | 預期 `500` 附 fallback `['AT','Kilonova']`，**但 `web_api_bp.logger` bug → Flask 預設 500** | 讀 `transient.objects.type` |
| 19 | POST | `/api/tns/manual-download` | `web_api.manual_tns_download` | 僅 admin（`403 {"error": "Access denied"}`） | JSON `hour_offset`（int，預設 0，**未驗證型別**） | `{"success": true, "message": "Successfully downloaded and imported TNS data", "imported_count": 0, "updated_count": 0}`（**兩個數字恆為 0**） | `500 {"error": "Download failed"}` / `"Import failed"` / `str(e)` | 同步下載 TNS 小時檔（重試最多睡 10+30+60 s）→ 寫 `app/data/tns_api_download_work/`；`INSERT/UPDATE transient.download_logs`；批次 `INSERT`/`UPDATE transient.objects`（更新列的 `Snoozed`→`Inbox`）；`sync_kinder_ids()` 更新 `objects.kinder_id`；**不**觸發 DETECT |
| 20 | POST | `/api/tns/search` | `web_api.search_tns` | 需登入（`403 {"error": "Access denied"}`） | JSON `search_term`、`object_type`、`limit`（預設 100，上限 1000，**無下限**） | `{"success": true, "results": [...], "count": n}` | `500 {"error": str(e)}` | 讀 `transient.objects` |
| 21 | GET | `/api/tns/stats` | `web_api.tns_stats_api` | 需登入（`403`） | 無 | `{"success": true, "stats": {total, with_photometry, classified, with_redshift, follow, finished, snoozed}}` | `500 {"error": str(e)}` | 讀 `transient.objects`、`transient.photometry` |
| 22 | GET | `/api/auto-snooze/status` | `web_api.auto_snooze_status` | 僅 admin（`403 {"error": "Access denied"}`） | 無 | `{"success": true, "status": {snoozed_count, finished_count}}` | `500 {"error": str(e)}` | 2 次 `COUNT` 讀 `transient.objects` |
| 23 | GET | `/api/auto-snooze/stats` | `web_api.auto_snooze_stats_api` | 需登入（`403 {"error": "Access denied"}`） | 無 | `{"success": true, "stats": {snoozed_count, finished_count}}`（與 #22 同資料、不同鍵名） | `500 {"error": str(e)}` | 同 #22 |

（* = 必填）

---

### A. 金鑰與測試

#### A1. `POST /api/generate_key` — `web_api.generate_key`（死程式碼）

- **路由衝突**：`app/routes/api_routes.py` 定義 `api_blueprint = Blueprint('api', __name__, url_prefix='/api')` 並註冊 `@api_blueprint.route('/generate_key', methods=['POST'])`（endpoint `api.generate_key`），在 `register_routes()` 中**先於** `web_api_bp` 註冊。Werkzeug 3.1.8 的 state-machine matcher 對完全相同的靜態規則採「先註冊者優先」——以專案 `.venv` 實測（兩個 blueprint 依相同順序註冊、`test_client().post('/api/generate_key')`）確認回應來自 `api` blueprint。
- 兩者都回 403、都是「自助產生金鑰已停用」，但 body 形狀不同：
  - 生效版（`api_routes.py`）：`{"error": "Self-service key generation is disabled. Please request a key from your profile page; an admin will issue it."}`
  - 被遮蔽版（本檔）：`{"success": false, "error": "...同文..."}`
- `url_for('web_api.generate_key')` 與 `url_for('api.generate_key')` 都能建 URL（endpoint 名不同，Flask 不會報重複），因此這個衝突在啟動時不會被發現。
- 前端沒有任何地方呼叫此路徑。

#### A2. `GET|POST /api/test` — `web_api.api_test`

- 認證：**只讀 `X-API-Key` header**（不接受 `?api_key=`，與 v1 端點不同）。
- 成功：`{"success": true, "message": "API Authentication successful!", "user": {"name", "email", "role": "admin"|"user"|"guest", "is_admin": bool, "groups": []}}`。
  - `role`/`is_admin` 由 `_user_row_to_dict` 依 `auth.users.roles`（≥50 admin、≥1 user、0 guest）計算。
  - `groups` **恆為 `[]`**：`get_user_by_api_key()` 只跑 `_USER_SELECT`，不像 `get_user()` 會多查 `auth.usr_group`；`_user_row_to_dict` 只 `setdefault('groups', [])`。
- 接受 POST 但 body 完全不使用。

### B. 觀測 API v1

#### B1. `GET /api/v1/observation_targets` — `web_api.api_v1_observation_targets`

- 認證：`X-API-Key` header **或** `?api_key=` query（header 優先）。任何有效 key 皆可讀。
- 流程：`get_observation_targets()`（預設 `active_only=True`，SQL 已 `WHERE t.active = TRUE`，route 再以 `is_active` 過濾一次）→ `_normalize_target_precision()` → 依 `telescope` 分成 `SLT`、`LOT` 兩組（其他望遠鏡值被**靜默丟棄**）。
- 每筆 target 欄位（來自 `obs._target_to_dict`）：`target_id`、`active`、`name`、`mag`、`ra`、`dec`（**十進位度的字串**，經 `_limit_decimal_4` 最多 4 位小數 ≈ 0.36″）、`telescope`、`program`、`priority`、`plan_filter/plan_count/plan_time` 被合併為 `filters: [{"filter", "count", "exp"}]`（`exp` 同樣截 4 位）、`repeat`、`plan`、`note`、`create_by`（usr_id）、`auto_exposure`、`created_by`（email）、以及別名 `id`、`is_active`、`repeat_count`、`note_gl`。
- `_limit_decimal_4` 規則：`bool`/`None` 原樣；`int`/`float` → `round(x, 4)`；純數字字串 → 4 位小數並去尾零；含 `:` 的字串（六十進位）原樣；其餘原樣。

#### B2. `POST /api/v1/observation_targets`

- 權限：`user.get('is_great_lab_member', False) or user.get('is_admin', False)`。因 `get_user_by_api_key()` 回傳的 dict **沒有 `is_great_lab_member` 鍵、`groups` 為空**，所以**只有 `roles ≥ 50`（admin）的 key 能通過**；GREAT_Lab 群組成員（非 admin）會得到 403。這與 docstring、`api_docs.html` 的「GREAT Lab member or admin」不符。
- 輸入處理（皆在 `try` **之外**）：
  - `telescope = (data.get('telescope') or '').strip().upper()`，必須 `SLT`/`LOT`。
  - `name` 必填。
  - `ra = _limit_decimal_4((data.get('ra') or '').strip())`、`dec` 同——**若 JSON 給數字（如 `"ra": 123.4`）會 `AttributeError: 'float' object has no attribute 'strip'`，未被捕捉 → Flask 預設 500（HTML）**。必須以字串傳（`"123.4568"` 或 `"12:34:56.7"`）。
  - `mag = _limit_decimal_4(data.get('mag'))`（數字或字串皆可；`_parse_mag_value` 另接受 `>` 前綴）。
  - `auto_exposure = bool(data.get('auto_exposure', False))`，`telescope == 'LOT'` 時強制 False（`save_observation_target` 內再強制一次）。
  - `priority` 預設 `Normal`，僅接受 `Normal`/`High`/`Urgent`（區分大小寫；注意 logs 端點另接受 `Filler`）。
  - `repeat_count`：`int(data.get('repeat_count') or 0)`（在 `try` 內；非數字 → 500 JSON）。
  - `filters`：list；元素為 dict 時取 `filter`、`count`（預設 1）、`exp`（或 `time`，預設 60）；非 dict 時 `str(f)`/1/60。
  - `plan`、`program`、`note_gl`（→ `note`）原樣；`user_email` → 查 `auth.users.usr_id` 作 `create_by`。
- 寫入：`INSERT INTO obs.targets (...) VALUES (TRUE, ...) ON CONFLICT (name, telescope) DO UPDATE SET mag, ra, dec, program, priority, plan_filter, plan_count, plan_time, repeat, plan, note, auto_exposure RETURNING target_id`。
  - 同名同望遠鏡已存在 → **靜默更新**並仍回 `201` 與 "added" 訊息；`active`、`create_by` 不更新（已停用的 target 仍停用）。
- 成功 `201`：`{"success": true, "message": "Target <name> added to <telescope>", "id": target_id, "target": {"id", "telescope", "name", "ra", "dec", "mag", "priority", "repeat_count", "auto_exposure"}}`。
- `save_observation_target` 內部任何例外（例如 RA/Dec 字串無法解析）只 log 並回 `None` → route 回 `500 {"success": false, "error": "Failed to save target"}`。

#### B3. `GET /api/v1/observation_logs` — `web_api.api_v1_observation_logs`

- query：`year`、`month`（`get_int_arg`；非整數 → `ParamOutOfRangeError` 在 route 內被捕捉 → `400 {"success": false, "error": "Parameter 'year' has an invalid value ..."}`），或 `date`（`YYYY-MM-DD`；給了就覆蓋 year/month，並在取回整月後以字串比對精確過濾）。兩者皆缺 → `400 year/month or a specific date query param is required`。
- 回傳 `logs` 每筆欄位（`obs._log_to_dict`）：`log_id`、`target_id`、`date`（`YYYY-MM-DD`）、`name`、`telescope`、`program`、`priority`、`repeat`、`trigger_by`（usr_id）、`trigger`、`observed`、`trigger_filters: [{"filter","count","exp"}]`、`trigger_filter`/`trigger_count`/`trigger_exp`（**逗號串接的字串**，如 `"rp,ip"`、`"300,300"`；無資料為 `null`）、`observed_filters`/`observed_filter`/`observed_count`/`observed_exp` 同、`triggered_by`（email）、`target_name`（JOIN `obs.targets` 的名字，否則 `l.name`）、`obs_date`、`telescope_use`、`repeat_count`、`is_triggered`、`is_observed`、`user_name`（= `triggered_by` 的 **email**，非顯示名）。
- 回傳外層：`{"success": true, "generated_at", "requested_by", "query_params": {"year", "month", "date"}, "logs": [...]}`。

#### B4. `POST /api/v1/observation_logs`

- 權限：**任何有效 API key 都能新增/修改/刪除**（無 admin / GREAT_Lab 檢查，與 targets POST 不一致）。
- 共同：`target_name`*、`obs_date`*（`YYYY-MM-DD`，否則 400）、`telescope`（`.upper()`，可空）。若 JSON 給 `"target_name": null` → `None.strip()` → 在 `try` 內 → `500 str(e)`。
- `action == "delete"`：`delete_observation_log(target_name, obs_date)`——**未傳 telescope** → `_resolve_target_id` 只以 name 找最新 active target → `DELETE FROM obs.logs WHERE target_id=%s AND date=%s`（**該日該 target 的所有望遠鏡紀錄一起刪**）。target 不在 `obs.targets`（孤兒 log）或無列被刪 → `500 Failed to delete log or log not found`。
- `action` 其他值（含預設 `upsert`）：
  - `trigger_filter`/`observed_filter`：list 時 `json.dumps` 成字串、字串原樣、空 → `None`；`upsert_observation_log` 透過 `_coerce_log_filters` 再 `json.loads` 回 list[dict]（此時 dict 內的 `exp`/`count` 優先，頂層 `trigger_exp`/`trigger_count` 被忽略）；純字串（`"rp"` 或 `"rp,ip"`）則搭配頂層 `trigger_exp`/`trigger_count`（可為單值或逗號串）逐項配對；`int()` 轉換失敗 → 例外 → `500 str(e)`。
  - `user_name = data.get('user_name') or user['name'] or user['email']` → 以 `email = %s OR name = %s` 查 `auth.users.usr_id` 作 `trigger_by`（查不到 → NULL，但回應仍回顯 `user_name`）。
  - `priority`：`"Normal - R01"` 形式會拆成 priority + `program`；否則 `program` 取自 `data['program']`；priority 不分大小寫對應 `Urgent/High/Normal/Filler`，其他值 `.title()` 後照存（DB 若有 CHECK constraint 會在 `upsert_observation_log` 內失敗 → 回 `None` → `500 Failed to save log`）。
  - 呼叫 `upsert_observation_log(target_name, obs_date, user_name, is_triggered, is_observed, trigger_filter, trigger_exp, trigger_count, observed_filter, observed_exp, observed_count, priority=..., telescope_use=..., program=...)`（走 `len(args) >= 7` 的 positional 分支）。
  - 唯一鍵為 `(name, date, telescope)`：**省略 `telescope` 會以空字串存**，與同日同名但 `telescope='LOT'` 的紀錄成為不同列。
  - target 不在 `obs.targets` → 以 `target_id = NULL` 存「孤兒」紀錄（log warning）。
- 成功：`{"success": true, "message": "Log saved", "log": {"target_name", "telescope": <hint or null>, "obs_date", "user_name", "is_triggered", "trigger_filter"(JSON 字串或原字串), "trigger_exp", "trigger_count", "is_observed", "observed_filter", "observed_exp", "observed_count", "priority"}}`（**不含 `log_id`、`program`**）。

### C. DETECT 觸發與影像

#### C1. `GET /api/object/<object_name>/detect_cross_match` — `web_api.trigger_detect_cross_match`

- **無認證**。`object_name` 用預設 converter（不含 `/`）；先 `urllib.parse.unquote` 再以 `^(?:AT|SN)\s*(\d.+)$` 去前綴，再 `SELECT obj_id, name, ra, dec FROM transient.objects WHERE lower(name)=lower(%s)` 取正規名稱。
- 決策：`screen = get_detect_screen_for_target(name)`；若 `force != 'true'` 且（`has_detect_run(name)`（`cross_matches` 有非 `DETECT_STATUS_RUN` 列）或 `screen` 非空）→ **DB-first** 直接回傳 `ran_now: false`。
- 否則：`detect_pipeline.ENABLED`（env `DETECT_IN_WEB`，預設開）為 False → 503；否則 `detect_pipeline.run_single(name)`（**同步、在 HTTP 請求內、持有 process-wide `threading.Lock`**；若排程的小時匯入 / 每日 Follow-up 重跑 / 其他使用者的 Run 正在跑，本請求會阻塞直到取得鎖）→ `function.run_detect.run_detect_single` → `run_cross_match_pipeline`。完成後 `routes.detect.detect_routes._soft_invalidate_page_cache()`（把 `_DETECT_PAGE_CACHE` 全部標為過期並對每個日期啟動背景重建執行緒 `_start_detect_page_build`；例外靜默）。
- 回應 `results[]` 欄位（`get_detect_results_for_target`）：`id`、`catalog_name`、`separation_arcsec`、`created_at`（ISO）、`is_host`、`flag`、`match_data`（JSONB）、`z`、`match_ra`、`match_dec`；依 separation 升冪。**此函式每次呼叫先執行 4 條 `ALTER TABLE transient.cross_matches ADD COLUMN IF NOT EXISTS ...`（flag、match_data、match_ra、match_dec）且從不 commit**（連線歸還池時被 rollback）。
- `screen` 欄位（`get_detect_screen_for_target`，讀 `transient.detect_screen`）：`score`、`host_status`、`tags`（濾掉 `Host-*`）、`z`、`z_source`、`abs_mag`、`abs_mag_band`、`abs_mag_source`、`abs_mag_discovery`、`peak_mag`、`peak_filter`、`peak_mjd`、`center_sep_arcsec`、`d_dlr`、`offset_kpc`、`host_targetid`、`run_date`（`YYYY-MM-DD HH:MM`）、以及由 `flags` JSON 攤平的 `host`、`host_user`、`host_user_by`、`tentative_host`、`tentative_d_dlr`、`morph`、`decline_rate`、`decline_filter`、`decline_days`、`decline_significant`、`kn_model_n`、`kn_model_in`、`kn_model_frac`、`kn_candidate`。
- `detect_image_id`：`get_detect_images(canonical_name)[0]['image_id']` 或 `null`。
- pipeline 寫入（依 `detect_pipeline` 模組 docstring 與 `run_detect`）：`transient.cross_matches`、`transient.detect_screen`（+ `detect_screen_history`）、`transient.target_images`、`transient.objects.tag` / `brightest_mag` / `brightest_abs_mag`；外部：NOIRLab Data Lab TAP（`https://datalab.noirlab.edu/tap/sync`）、Legacy Survey cutout（`https://www.legacysurvey.org/viewer/cutout.jpg`）；狀態：`modules.job_status.record_start/record_finish`、`detect_pipeline._state`；並以 `_pin_db_env()` 覆寫 `os.environ` 的 `PG_HOST/PG_PORT/PG_USER/PG_PASSWORD/PG_DATABASE`。

#### C2. `GET /api/object/<object_name>/detect_images` — `web_api.list_detect_images`

- **無認證**。`get_detect_images(name)`：`SELECT ti.image_id, ti.source FROM transient.target_images ti JOIN transient.objects o ... WHERE o.name = %s AND ti.source IN ('DESI','detect_combined') ORDER BY (ti.source='DESI') DESC, ti.image_id DESC LIMIT 1` → **最多 1 筆**（函式與 route 名稱都叫 list，docstring 說「只有 detect_combined」但 SQL 也含 `DESI` 並優先）。
- 名稱**精確比對**（不去 AT/SN 前綴、區分大小寫），與 C1/C3 的行為不同。

#### C3. `POST /api/object/<object_name>/detect_images/generate` — `web_api.generate_detect_images`

- **無認證**。`lower(name)=lower(%s)` 找正規名稱（不去前綴）→ 404 / 503 → `detect_pipeline.run_single(canonical_name)`（同 C1 的完整 pipeline，不是只重畫圖）→ 回 `{"success": true, "images": [...], "detect_image_id": ...}`。
- 與 C1 不同：**不呼叫 `_soft_invalidate_page_cache()`**，DETECT 頁快取（TTL `DETECT_PAGE_CACHE_TTL_SEC`，預設 600 s）可能顯示舊資料。

### D. 物件新增 / 查詢 / 標籤 / 分類 / 統計

#### D1. `POST /api/objects` — `web_api.add_object`（僅 admin）

- `data = request.get_json()`：非 JSON Content-Type → Werkzeug `415` 例外被 `except Exception` 捕捉 → `500 {"error": "Database error: 415 Unsupported Media Type: ..."}`（訊息誤導）。
- 驗證順序：必填 `name`/`ra`/`dec`（空值也算缺）→ `float(ra)`、`float(dec)`（失敗 → `except ValueError` → `400 Invalid input data`）→ `type` 預設 `AT` → `magnitude` 選填 float −5..30 → `len(name) >= 3` → **重複檢查 `search_tns_objects(search_term=name, limit=1)`**（`_build_where` 以 `ILIKE '%name%'` 比對 `name`、`name_prefix||name`、`internal_name`、`other_name`；因此新增 `2025a` 時若已有 `2025abc` 或任何 internal name 含該字串就會被拒 → `400 Object X already exists in database`）→ `discovery_date`（`YYYY-MM-DD`，預設今天）。
- MJD：`disc_mjd = (date - 1858-11-17).days`（**整數天，無小數**）、`received_date = last_modified_date = now_mjd`。
- `INSERT INTO transient.objects (name, name_prefix, type, ra, dec, discovery_mag, discovery_date, source_group, received_date, last_modified_date, status, tag) VALUES (..., '', ..., 'Object', '{}'::text[]) RETURNING obj_id`。
  - `status='Object'` 是**舊版狀態值**；其他模組的狀態詞彙是 `Inbox`/`Snoozed`/`Follow-up`/`Finish`。`OBJECT_COMPAT_COLS` 的 `CASE` 會把它顯示為 `tag='object'`、`inbox=1`，但 `get_tag_statistics`、`get_filtered_stats`、`_build_where(tag='object')` 都只算 `status='Inbox'` → **手動新增的物件不會出現在 Inbox 篩選與統計中**。
  - `name_prefix=''` → `classification=AT` 篩選（`name_prefix='AT'`）與 `at_count` 排除它、`Classified`（`name_prefix != 'AT'`）反而包含它。
  - `kinder_id` 不會被指派（只有 TNS 匯入後的 `sync_kinder_ids()` 才做）。
- 使用 raw `get_tns_db_connection()`（pool 連線包裝，`close()` = 歸還），但 `conn.close()` 只在成功路徑呼叫；INSERT 失敗（例如唯一鍵衝突）時**連線永久留在 checked-out 狀態**。
- 前端沒有任何頁面呼叫此端點（grep `routes/*/static/js`、templates 均無 POST `/api/objects`）。

#### D2. `GET /api/objects` — `web_api.api_get_objects`（**公開**）

- 參數：
  - `page`（int ≥1，預設 1）、`per_page`（int 1..500，預設 50）——`get_int_arg` 在 `try` 之外，非法 → app 層 `400 {"error": ...}`。
  - `sort_by`：`discoverydate`（預設）→ `o.discovery_date`；`lastmodified`→`last_modified_date`；`discoverymag`→`discovery_mag`；`name`；`time_received`→`received_date`；`last_photometry_date`→`COALESCE(last_phot_date, last_modified_date)`；`brightest_mag`；`brightest_abs_mag`；`redshift`；未知值 → `discovery_date`。`sort_order`：`asc` 以外一律 `DESC`；皆 `NULLS LAST`。
  - `search`：`ILIKE '%s%'` 於 `name`、`name_prefix||name`、`internal_name`、`other_name`。
  - `classification`：逗號分隔；`AT` → `name_prefix='AT'`；`Classified` → `name_prefix != 'AT'`；其他 → `type = 值`；多值 OR。
  - `tag`：`object`（`status='Inbox'`）/`followup`/`finished`/`snoozed`/`flag`（`EXISTS cross_matches c WHERE c.status='Flagged'`——**全專案沒有任何地方寫入 `'Flagged'`**，此篩選恆為空）；其他值忽略。
  - `date_from`/`date_to`：`YYYY-MM-DD` → 轉 MJD 比較 `discovery_date`（`date_to` 含當日 +1）；非法日期字串 → PostgreSQL 錯誤 → 進入有 bug 的 except（見下）。
  - `app_mag_min/max`（`discovery_mag`）、`redshift_min/max`（`get_float_arg`，NaN/inf 亦 400）。
  - `discoverer`：`ILIKE` 於 `source_group`、`report_group`、`array_to_string(reporters)`。
- 三次查詢：`search_tns_objects`（`SELECT {OBJECT_COMPAT_COLS} ... LIMIT/OFFSET`）、`get_objects_count`、`get_filtered_stats`。
- 每筆 object 欄位（`OBJECT_COMPAT_COLS`，`modules/database/__init__.py`）：`obj_id`、`objid`、`kinder_id`、`name_prefix`、`name`、`ra`、`declination`、`redshift`、`type`、`typeid`(null)、`reporting_group`、`reporting_groupid`(null)、`source_group`、`source_groupid`(null)、`discoverydate`、`discoverymag`、`discmagfilter`、`filter`、`reporters`、`time_received`、`internal_names`、`discovery_ads_bibcode`、`class_ads_bibcodes`、`creationdate`、`last_photometry_date`、`lastmodified`、`brightest_mag`、`brightest_abs_mag`、`pin`(int)、`tags`、`tag`、`status`、`inbox`、`snoozed`、`follow`、`finish_follow`、**`permission`、`groups`**（權限設定原樣輸出，但未據以過濾）。
- `stats`：`{"total", "object", "followup", "finished", "snoozed"}`（注意鍵名與 `/api/stats` 不同）。
- 例外路徑：`web_api_bp.logger.error(...)` — `flask.Blueprint` **沒有 `logger` 屬性**（實測 `hasattr(Blueprint('x', __name__), 'logger') == False`）→ 在 `except` 內再拋 `AttributeError` → 回應為 Flask 預設 500（DEBUG 關閉時為 HTML "Internal Server Error"），**不是**程式裡寫的那個含 `objects: []` 的 JSON。

#### D3. `POST /api/object-tags` — `web_api.api_get_object_tags`（需登入）

- JSON `object_names`（list[str]；空/缺 → `{"success": true, "tags": {}}`）。以 `%s` placeholder 逐一參數化（安全），`WHERE o.name IN (...)`（精確、區分大小寫）。
- 回 `tags[name]`（由 `status` 映射：`Finish`→`finished`、`Follow-up`→`followup`、`Snoozed`→`snoozed`、其他→`object`）與 `object_tags[name]`（`array_to_string(o.tag, ', ')`）；查不到的名字補 `object` / `null`。
- 與 D1 相同的 raw 連線外洩問題；例外路徑同樣踩到 `web_api_bp.logger`。

#### D4. `GET /api/classifications` — `web_api.api_get_classifications`

- 未登入 → `200 {"success": true, "classifications": []}`；登入 → `SELECT DISTINCT type ... WHERE type IS NOT NULL AND type != '' ORDER BY type`。
- 例外路徑本想回 `500` + fallback `['AT', 'Kilonova']`，但 `web_api_bp.logger` bug 使其變成 Flask 預設 500。

#### D5. `GET /api/stats` — `web_api.api_get_stats`

- 未登入 → 全 0（`success: true`）。
- 登入：`total_count = get_objects_count()`、`at_count = get_objects_count(object_type='AT')`（`name_prefix='AT'`）、`classified_count = total − at`、`get_tag_statistics()` 四個 `COUNT`（`Inbox`/`Follow-up`/`Finish`/`Snoozed`）→ `inbox_count`/`followup_count`/`finished_count`/`snoozed_count`；`flag_count = tag_stats.get('flag', 0)` — **`get_tag_statistics` 不產生 `flag` 鍵，恆為 0**（`get_marshal_overview_stats` 才有 `flag_count`，但本端點沒用它）。
- 例外路徑同樣踩 `web_api_bp.logger`。

### E. flag / pin

#### E1. `GET /api/object/<path:object_name>/flag_status` — `web_api.get_flag_status`（需登入，401）

- `get_object_flag_status(name)`：先 `_ensure_cross_matches_flag_column(cur, conn)`（`ALTER TABLE transient.cross_matches ADD COLUMN IF NOT EXISTS flag BOOLEAN DEFAULT FALSE` + `commit`，**每次呼叫**；`ALTER TABLE` 需取得表級鎖，與 DETECT 寫入競爭）→ `SELECT EXISTS(... WHERE o.name = %s AND c.flag = TRUE)`（精確名稱）。
- 回 `{"is_flagged": bool}`；任何例外由函式吞掉回 `False`。

#### E2. `POST /api/object/<path:object_name>/toggle_flag` — `web_api.update_flag_status`（需登入，含 guest）

- `data = request.get_json()`（無 `silent`）→ 非 JSON → Flask 415。`flag = data.get('flag')`；`None` → 400；**其他任何型別原樣傳入 SQL**（`UPDATE transient.cross_matches SET flag = %s WHERE obj_id = (SELECT obj_id FROM transient.objects WHERE name = %s LIMIT 1)`）並原樣回顯為 `is_flagged`。
- flag 存在**每一列 cross-match** 上而非物件本身；物件沒有 cross-match 列時 `rowcount = 0` 但仍回 `{"success": true}` → 前端顯示已標記，重新整理後 `flag_status` 又是 `false`。
- 名稱雖是 toggle，實際是「設為指定值」。

#### E3. `GET /api/object/<path:object_name>/pin_status` — `web_api.get_pin_status`

- 未登入回 `200 {"is_pinned": false}`（不是 401，與 E1 不一致）。`SELECT pin FROM transient.objects WHERE name = %s OR (COALESCE(name_prefix,'')||name) = %s`。

#### E4. `POST /api/object/<path:object_name>/toggle_pin` — `web_api.toggle_pin_status`（僅 admin，403）

- `UPDATE transient.objects SET pin = NOT pin WHERE name=%s OR prefix||name=%s RETURNING pin` → `{"success": true, "is_pinned": bool}`。物件不存在或 DB 錯誤時 `toggle_object_pin` 回 `False` → 仍 `success: true, is_pinned: false`，無法分辨。

### F. 光度抓取

#### F1. `POST /api/object/<path:object_name>/fetch_photometry` — `web_api.fetch_photometry`（需登入，含 guest；未登入 **403**）

- 同步呼叫 `modules.download_phot.process_single_object_workflow(object_name)`（回傳值恆 `None`，route 一律回 `{"success": true, "message": "Photometry fetch completed for X"}`，即使物件不存在（workflow 只 log `missing_object`）或沒有產生任何光度檔）。
- 工作流程（`download_phot.py:1014-1108`）：
  1. `get_object_coordinates(name)`：`SELECT o.ra, o.dec FROM transient.objects WHERE o.name = %s`（精確裸名）。
  2. 若 `TNSObjectDB.get_photometry(name)` 已有資料 → 從 `transient.objects.internal_name` 讀 internal names（避免 TNS bot 額度）；否則 `get_tns_internal_name(name)`：`POST https://www.wis-tns.org/api/get/object`（`User-Agent: tns_marker{...TNS_BOT_ID/TNS_BOT_NAME...}`、`api_key=TNS_API_KEY`）→ `update_object_internal_names()` 寫 `transient.objects.internal_name`。
  3. `get_photometry([[name, ra, dec, internal_names_str]], output_dir)`，`output_dir = app/data/phot_cache`：
     - `init_photometry_file` 建 `app/data/phot_cache/<year>/<name>_photometry.txt`；
     - 依 internal name 前綴分派：含 `ATLAS` → `get_atlas_photometry`（Playwright headless Chromium 登入 `https://star.pst.qub.ac.uk/sne/atlas4/accounts/login/`，抓 `.../atlas4/lightcurve/`；帳密 `ATLAS_USER`/`ATLAS_PASS`）；`PS*` → `get_panstarrs_photometry`（`.../sne/ps13pi/...`，`PANSTARRS_USER`/`PANSTARRS_PASS`）；`ZTF*` → `get_ztf_photometry`（`alerce.core.Alerce().query_lightcurve(oid, survey="ztf")`；`ZTF_SOURCE='alerce'`，Lasair 路徑被註解）；`LSST*` 或 ≥15 位純數字 → `get_lsst_alerce_photometry`（`survey="lsst"`）；**都沒有**時 → `get_discover_mag_from_TNS`（再打一次 TNS API 拿 discovery mag）；
     - `bin_photometry_file(..., bin_window=1.0)` 以 1 天分箱。
  4. 檔案存在 → `upload_photometry_to_db()`：`TNSObjectDB.get_photometry`（去重）→ `TNSObjectDB.add_photometry_bulk`（`INSERT transient.photometry`）→ `TNSObjectDB.sync_last_photometry_date`（`UPDATE transient.objects SET last_phot_date = MAX("MJD")`）→ 刪除本地檔。
- Playwright 下載目錄 `download_dir = Path.cwd()/"data"/"temp_downloads"`（模組載入時以**程序 CWD** 決定）。
- 整段在 HTTP 請求內執行，可能耗時數分鐘（gunicorn worker timeout 風險）；沒有背景執行緒、沒有去重/節流；三個前端頁面都可觸發（見「前端呼叫來源」）。

### G. TNS 手動下載 / 搜尋 / 統計

#### G1. `POST /api/tns/manual-download` — `web_api.manual_tns_download`（僅 admin）

- JSON `hour_offset`（預設 0；**未驗證**：字串 → `TypeError`、浮點 → `ValueError`（`:02d` 格式）→ 皆被 `except Exception` → `500 {"error": str(e)}`）。`utc_hr = (now_utc.hour − hour_offset) % 24`。
- `download_TNS_api_hr(utc_hr, debug=True)`：`POST https://www.wis-tns.org/system/files/tns_public_objects/tns_public_objects_{HH}.csv.zip`（header `user-agent: tns_marker{"tns_id":BOT_ID,"type":"bot","name":BOT_NAME}`，form `api_key=API_KEY`——來自 `kinder.env` 的 `BOT_ID`/`BOT_NAME`/`API_KEY`，與 `download_phot.py` 用的 `TNS_BOT_ID`/`TNS_BOT_NAME`/`TNS_API_KEY` 是**另一組變數名**）。非 200/404 時重試，睡 10 s、30 s、60 s（請求最長阻塞 >100 s）；404 直接失敗。成功則存 `app/data/tns_api_download_work/tns_public_objects_{HH}.csv.zip` → 解壓 → 改名為 `tns_public_objects_WORK.csv`（覆蓋舊檔）→ 刪 zip。
- route 以 `pathlib.Path(__file__).resolve().parent.parent.parent / "data" / "tns_api_download_work"` 重算同一路徑（`app/data/tns_api_download_work`，與模組的 `SAVE_DIR` 一致）。
- `addin_database(work_csv, debug=True)`：`log_download_attempt()` → `INSERT transient.download_logs`；逐列 `SELECT last_modified_date FROM transient.objects WHERE obj_id=%s`；較新者批次 `UPDATE transient.objects`（含 `status = CASE WHEN status='Snoozed' THEN 'Inbox' ELSE status END`——**更新到的 Snoozed 物件會自動回 Inbox**）；不存在者批次 `INSERT`（`status='Inbox'`、`tag='{}'`、`ON CONFLICT DO NOTHING`）；`update_download_log()`；`sync_kinder_ids()`（`UPDATE transient.objects SET kinder_id`）。
- 成功回應：`imported_count`/`updated_count` 取自 `get_tns_statistics().get('recent_downloads', [])[0]`——**`get_tns_statistics()` 沒有 `recent_downloads` 鍵**（只有 `total/with_photometry/classified/with_redshift/follow/finished/snoozed`），因此**恆為 0**。實際數字只寫在 `transient.download_logs` 與 log。
- 與排程的 `modules.auto_tns_download` 不同，這裡**不會**對新匯入物件觸發 DETECT，也不會使 DETECT 頁快取失效。

#### G2. `POST /api/tns/search` — `web_api.search_tns`（需登入）

- JSON `search_term`、`object_type`（語意同 D2 `classification`）、`limit`（`min(int(x), 1000)`；預設 100；負數 → SQL `LIMIT -1` 錯誤 → 500；非數字 → 500）。`request.get_json()` 非 JSON → 415 例外被捕捉 → `500 {"error": ...}`。
- `search_tns_objects(search_term, object_type, limit)` → 依 `discovery_date DESC`；回 `{"success": true, "results": [OBJECT_COMPAT_COLS...], "count": n}`。

#### G3. `GET /api/tns/stats` — `web_api.tns_stats_api`（需登入）

- `get_tns_statistics()`：單一聚合查詢 `transient.objects` + 子查詢 `COUNT(DISTINCT obj_id) FROM transient.photometry`。

### H. auto-snooze

#### H1. `POST /api/auto-snooze/manual-run` — `web_api.manual_auto_snooze`（僅 admin）

- `auto_snoozed(datetime.now(timezone.utc), debug=True)`：`cutoff_mjd = 今日 MJD − 15`；`SELECT ... FROM transient.objects WHERE status != 'Snoozed' AND ((last_phot_date IS NOT NULL AND last_phot_date < cutoff) OR (last_phot_date IS NULL AND last_modified_date < cutoff))`；`Follow-up` → `Finish`，其他 → `Snoozed`；單一 commit。函式回 `True`/`False`（不回數量；其 log 的 `snoozed_count` 把 finished 也算進去）。
- route 之後呼叫 `get_auto_snooze_stats()` 回**全庫** `Snoozed`/`Finish` 總數當作 `snoozed_count`/`finished_count`，並非本次變更數。
- `debug=True` → 每個物件一行 debug log。

#### H2. `GET /api/auto-snooze/status`（僅 admin）與 H3. `GET /api/auto-snooze/stats`（需登入）

- 同樣呼叫 `get_auto_snooze_stats()`（兩個 `COUNT`），只差外層鍵名 `status` vs `stats` 與權限等級；功能重複。

---

## 驗證與權限模型

### 1. Session 登入（D–H 組）

- 來源：Google OAuth（`routes/auth/auth_routes.py::google_callback`）在登入時寫入 `session['user'] = {email, name, picture, is_admin, role, is_great_lab_member, groups, api_key, ...}`；**未註冊使用者也會得到 `role='guest'` 的 session**。
- 角色來源：`auth.users.roles` 整數（`_user_row_to_dict`：≥50 → `is_admin`/`role='admin'`；≥1 → `user`；0 → `guest`；≥99 → `is_super_admin`）。
- 每個請求 `refresh_user_session` 以 DB 重新同步 `is_admin` 與 `is_great_lab_member`（`'GREAT_Lab' in groups or is_admin`）。
- 本章的檢查只有兩種寫法：
  - `if 'user' not in session` → 需登入（**guest 也通過**；沒有任何 route 檢查 `role != 'guest'` 或 `is_great_lab_member`）。
  - `if 'user' not in session or not session['user'].get('is_admin')` → 僅 admin。
- 未通過時的回應碼不一致：`401`（`flag_status`、`toggle_flag`）、`403`（`fetch_photometry`、`object-tags`、`tns/*`、`auto-snooze/stats`、admin 端點）、`200` 假資料（`pin_status`、`stats`、`classifications`）、完全不檢查（`GET /api/objects`、DETECT 三端點）。

### 2. API key（A、B 組）

- **儲存**：`auth.users.api_key`（明文、48 字元 `[A-Za-z0-9]`，以 `secrets.choice` 產生）、`auth.users.api_key_requested_at`（`_ensure_api_key_request_col()` 在 `auth.py` 模組載入時 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 建立）。
- **申請流程**（自助產生已停用）：
  1. 使用者在個人頁（`routes/auth/templates/profile.html` + `static/js/profile.js`）按「Request API key」→ `POST /api/profile/request_api_key`（`auth_bp`；需登入且 `role != 'guest'`）→ `request_api_key(email)`：`UPDATE auth.users SET api_key_requested_at = now()`。
  2. Admin 後台（`admin_routes.py`，`get_api_key_requests()` 列出待審）→ `POST /admin/api-key/issue` `{email}` → `generate_api_key_for_user(email)`：產生新 key、清除 `api_key_requested_at`（**同一使用者再次核發會直接覆蓋舊 key**）；`POST /admin/api-key/revoke` → `revoke_api_key(email)`：設 NULL。
  3. 使用者回個人頁看到 key（`profile.html` 直接渲染 `user_data.api_key`）。
  4. `POST /api/generate_key`（兩個 blueprint 都有）一律 403。
- **驗證**：`get_user_by_api_key(api_key)`：`SELECT u.usr_id, u.email, u.name, u.picture_url, u.roles, u.last_login, u.join_date, u.api_key, u.api_key_requested_at FROM auth.users u WHERE u.api_key = %s` → `_user_row_to_dict`。
  - 精確字串比對、無雜湊、無到期、無 scope、無最後使用時間、無速率限制。
  - **回傳 dict 沒有 `groups`（空 list）也沒有 `is_great_lab_member`** → 依賴群組的授權在 API key 路徑上失效（B2 只剩 admin 能 POST；A2 的 `groups` 永遠空）。
- **傳遞**：`X-API-Key` header（A2、B1–B4）或 `?api_key=`（僅 B1–B4；A2 不接受）。query string 形式會出現在反向代理 / 瀏覽器歷史中（app 自身的 access log 只記 path）。
- **前端注入**：`private_area` 的 `daily_trigger` 頁把 `session['user']['api_key']` 放進 `<meta name="x-api-key">`，`daily_trigger.js::_apiFetch` 對所有請求附 `X-API-Key` header——但它呼叫的都是 `private_area` 的 session 端點（`/api/targets`、`/api/observation_logs`、`/api/search_target`…），**沒有任何前端程式呼叫本章的 `/api/v1/*`**；`/api/v1/*` 純粹供外部程式（望遠鏡端腳本）使用。

### 3. 物件層 / 資料來源層權限（未在本章使用）

- `modules.database.auth.check_object_access(object_name, user_email, user_roles)`：admin 恆 True；讀 `transient.objects.permission`（`public`/`login`/`groups`）與 `groups`（INT[] group_id），`groups` 模式再查 `auth.usr_group`。
- `modules.database.auth.filter_by_source_permissions(object_name, data_type, source_list, user_email, user_groups, is_admin)`：admin 全放行；依 `transient.object_source_permissions`（per-object override：`is_public` / `allowed_groups` NULL=登入即可、`[]`=封鎖、`[ids]`=指定群組）→ `transient.default_permissions`（`permissions_set` public/login/groups）→ 系統預設（來源名含 `tns` 公開，其餘需登入）過濾光度/光譜來源。
- **這兩個函式在 `web_api_routes.py` 完全沒有被呼叫**；實際使用者是 `routes/marshal/object_routes.py`（光度/光譜/plot 端點）與 `astronomy_tools` 的 `/api/objects/<name>`（`api_docs.html` 所描述、含 `api_key` 選填的那個端點屬於 `astronomy_tools_bp`，不在本章）。本章的 `GET /api/objects`、`POST /api/tns/search` 直接輸出所有物件（含 `permission`/`groups` 欄位值），`fetch_photometry`/`toggle_flag` 也不檢查物件存取權。

---

## 依賴的模組、資料表、檔案與外部服務

### Python 模組（import 於檔頭或函式內）

| 模組 | 使用到的符號 | 備註 |
|---|---|---|
| `modules.database.transient` | `get_tns_statistics`、`get_objects_count`、`search_tns_objects`、`get_tag_statistics`、`get_filtered_stats`、`get_distinct_classifications`、`get_auto_snooze_stats`、`get_object_flag_status`、`update_object_flag_by_name`、`get_object_pin_status`、`toggle_object_pin`、`get_detect_images` | `update_object_status`、`update_object_activity` 被 import 但**未使用**（後者本身是 no-op） |
| `modules.database` | `get_db_connection`（context manager，自動歸還/rollback）、`get_tns_db_connection`（raw `_PooledConn`，需手動 `close()`） | `OBJECT_COMPAT_COLS` 被 import 但**未使用** |
| `modules.request_validation` | `get_int_arg`、`get_float_arg`、`ParamOutOfRangeError` | — |
| `modules.database.auth` | `get_user_by_api_key` | `generate_api_key_for_user` 被 import 但**未使用** |
| `modules.database.obs` | `get_observation_targets`、`save_observation_target`、`get_observation_logs`、`upsert_observation_log`、`delete_observation_log` | — |
| `modules.Manual_tns_download_snoozed` | `download_TNS_api_hr`、`addin_database`、`auto_snoozed` | 模組載入時 `SAVE_DIR.mkdir(...)`、`load_dotenv(kinder.env)` |
| `modules.download_phot` | `process_single_object_workflow` | 模組載入時 import `playwright.sync_api`、`alerce`、`load_dotenv(kinder.env, override=True)` |
| `modules.data_processing` | `DataVisualization` | **import 後完全未使用**（死 import，且會拉進整個 `data_processing` 模組） |
| `modules.detect_cross_match`（函式內 import） | `has_detect_run`、`get_detect_results_for_target`、`get_detect_screen_for_target` | — |
| `modules.detect_pipeline`（函式內 import） | `ENABLED`、`run_single` | 包裝 `modules/DETECT/function/run_detect.py` |
| `routes.detect.detect_routes`（函式內 import） | `_soft_invalidate_page_cache` | 跨 blueprint 依賴（私有函式） |
| `modules.job_status`（間接） | `record_start` / `record_finish` | 由 `detect_pipeline._Run` 呼叫 |

### 資料表

| Schema.table | 讀 | 寫 | 端點 |
|---|---|---|---|
| `auth.users` | key 查詢；`create_by` / `trigger_by` 解析 | — | A2、B1–B4 |
| `auth.usr_group`、`auth.groups` | 僅經 `refresh_user_session`（session 使用者） | — | 全部 session 端點 |
| `obs.targets` | B1、B3（JOIN）、B4（解析 target_id） | B2 upsert；B1/B2 DDL `ADD COLUMN auto_exposure` | B 組 |
| `obs.logs` | B3 | B4 INSERT/UPDATE/DELETE | B 組 |
| `transient.objects` | 幾乎所有端點 | D1 INSERT；E4 `pin`；H1 `status`；G1 批次 INSERT/UPDATE + `kinder_id`；F1 `internal_name`、`last_phot_date`；C1/C3（DETECT）`tag`、`brightest_mag`、`brightest_abs_mag` | — |
| `transient.cross_matches` | C1、E1、D2（`tag=flag`） | E2 `flag`；C1/C3 DETECT 寫入；E1/E2/C1 DDL | — |
| `transient.detect_screen`（+ `detect_screen_history`） | C1 | C1/C3 DETECT 寫入 | — |
| `transient.target_images` | C1、C2、C3 | C1/C3 DETECT 寫入（finder 影像 bytes） | — |
| `transient.photometry` | G3（COUNT DISTINCT）、F1（去重） | F1 bulk INSERT | — |
| `transient.download_logs` | — | G1 INSERT/UPDATE | — |
| `transient.object_source_permissions`、`transient.default_permissions` | **未使用** | — | — |

### 檔案 / 目錄

| 路徑 | 用途 | 端點 |
|---|---|---|
| `app/data/tns_api_download_work/tns_public_objects_{HH}.csv.zip` → `tns_public_objects_WORK.csv` | TNS 小時檔下載、解壓、改名（覆蓋）、刪 zip | G1 |
| `app/data/phot_cache/<year>/<name>_photometry.txt` | 光度暫存（建立 → 分箱 → 上傳 DB → 刪除） | F1 |
| `<CWD>/data/temp_downloads` | Playwright 下載目錄（依程序 CWD） | F1 |
| `app/modules/DETECT/`（`function/`、`VERSION`、`data/dustmaps/sfd/*`；可由 `DETECT_DATA_DIR` 覆寫） | 內嵌 DETECT 程式碼與資料 | C1、C3 |
| `kinder.env`（專案根） | `TNS_HOST`、`API_BASE_URL`、`BOT_ID`、`BOT_NAME`、`API_KEY`（TNS 小時檔）；`TNS_BOT_ID`、`TNS_BOT_NAME`、`TNS_API_KEY`（TNS object API）；`ATLAS_USER/PASS`、`PANSTARRS_USER/PASS`；`DETECT_IN_WEB`；`DETECT_PAGE_CACHE_TTL_SEC`、`DETECT_PAGE_CACHE_MAX_SIZE` | G1、F1、C 組 |

### 外部服務

| 服務 | URL / 方式 | 端點 |
|---|---|---|
| TNS 公開物件小時檔 | `POST https://www.wis-tns.org/system/files/tns_public_objects/tns_public_objects_{HH}.csv.zip`（bot user-agent + `api_key`） | G1 |
| TNS object API | `POST https://www.wis-tns.org/api/get/object`（bot；取 internal names / discovery mag） | F1 |
| ATLAS forced photometry | `https://star.pst.qub.ac.uk/sne/atlas4/accounts/login/`、`.../lightcurve/`（Playwright headless Chromium 登入） | F1 |
| Pan-STARRS (ps13pi) | `https://star.pst.qub.ac.uk/sne/ps13pi/accounts/login/`、`.../psdb/lightcurve/`（Playwright） | F1 |
| ALeRCE | Python client `alerce.core.Alerce().query_lightcurve(oid, survey="ztf"|"lsst")` | F1 |
| Lasair | `https://lasair-ztf.lsst.ac.uk/objects/`（程式碼存在但 `ZTF_SOURCE='alerce'`，未啟用） | — |
| NOIRLab Data Lab TAP | `https://datalab.noirlab.edu/tap/sync`（Legacy Survey DR10 host 查詢） | C1、C3 |
| Legacy Survey viewer | `https://www.legacysurvey.org/viewer/cutout.jpg`（finder 底圖） | C1、C3 |

### 背景執行緒 / 鎖 / 快取

- `detect_pipeline._LOCK`（`threading.Lock`，**每個 gunicorn worker 各一把**）：C1/C3 的 DETECT 執行在請求執行緒內同步進行；跨 worker 無法互斥。
- `_soft_invalidate_page_cache()`（C1 成功執行後）：把 `routes/detect/detect_routes._DETECT_PAGE_CACHE` 所有日期標為過期並逐一 `_start_detect_page_build(date)` 啟動背景重建執行緒。C3 不做這件事。
- 本章沒有自己啟動任何背景執行緒；F1、G1、H1 都是同步阻塞。

---

## 前端呼叫來源

| 前端檔案 | 呼叫的本章端點 |
|---|---|
| `routes/marshal/static/js/marshal.js` | `GET /api/stats`（L115）、`POST /api/object-tags`（L263）、`GET /api/objects?…`（L364）、`GET /api/classifications`（L1307） |
| `routes/marshal/static/js/object_detail.js` | `GET /api/object/<name>/detect_cross_match[?force=true]`（L244、269、437）、`GET .../detect_images`（L504）、`POST .../detect_images/generate`（L533）、`POST .../fetch_photometry`（L5145）、`GET .../flag_status`（L5343）、`GET .../pin_status`（L5364）、`POST .../toggle_pin`（L5386）、`POST .../toggle_flag`（L5424） |
| `routes/detect/static/js/detect_results.js` | `POST /api/object/<name>/fetch_photometry`（L171）。（其 L365 的 `POST /api/toggle_flag` 打的是 `detect_bp.toggle_flag`，不屬本章。） |
| `routes/private_area/static/js/epessto_support.js` | `POST /api/object/<name>/fetch_photometry`（L528）、`GET /api/classifications`（L853） |

沒有任何前端 JS / 模板呼叫：`POST /api/generate_key`、`/api/test`、`/api/v1/observation_targets`、`/api/v1/observation_logs`、`POST /api/objects`、`/api/tns/manual-download`、`/api/tns/search`、`/api/tns/stats`、`/api/auto-snooze/manual-run`、`/api/auto-snooze/status`、`/api/auto-snooze/stats`。也沒有任何模板使用 `url_for('web_api.…')`。

---

## `api_docs.html` 與實作不一致之處

`routes/astronomy_tools/templates/api_docs.html`（由 `astronomy_tools_routes.py:1871` 以 `/api` 頁面渲染）「Authenticated API」段落描述了 A2、B1–B4；比對結果：

| 文件敘述 | 實作 |
|---|---|
| 「Generate your key from the account settings page (authorized users only)」 | 自助產生已停用（`/api/generate_key` 403）；流程是「個人頁**申請** → admin 核發」 |
| `/api/test` 標示 `GET`，範例回應 `"groups": ["GREAT Lab"]` | 亦接受 `POST`；`groups` 恆為 `[]`（見驗證模型）；群組名在 DB 為 `GREAT_Lab`（底線） |
| `/api/test`、`/api/v1/*` 皆說可用 `?api_key=` | `/api/test` **只接受 header** |
| `GET /api/v1/observation_targets` 範例：`"ra": "12:34:56.7"`（六十進位）、每筆只有 `name/ra/dec/mag/priority/filters` | 回傳十進位度字串（4 位小數）及 ~20 個欄位（`target_id`、`active`、`plan`、`note`、`create_by`、`created_by`、`auto_exposure`、`repeat`、`program`、`id`、`is_active`、`repeat_count`、`note_gl`…） |
| `POST /api/v1/observation_targets`「Requires GREAT Lab member or admin」；`ra`/`dec`「decimal ° or hh:mm:ss」 | 實際只有 admin key 能過；`ra`/`dec` **必須是字串**（JSON 數字 → 500）；文件未提 `auto_exposure` 輸入、回應中的 `id`/`repeat_count`/`auto_exposure`、以及「同名同望遠鏡會被覆寫」 |
| `GET /api/v1/observation_logs` 範例：`"trigger_exp": 300`（數字）、`"user_name": "Alex"` | `trigger_exp`/`trigger_count`/`trigger_filter` 是逗號串接**字串**；`user_name` 是 email；另有十餘個未列欄位（`log_id`、`target_id`、`date`、`name`、`program`、`priority`、`repeat`、`trigger_by`、`trigger`、`observed`、`trigger_filters`、`observed_filters`、`triggered_by`、`telescope_use`、`repeat_count`） |
| `POST /api/v1/observation_logs` 欄位表 | 未列 `program`、`"Priority - Program"` 複合寫法；未說明 `delete` 忽略 `telescope`、且 target 不在 `obs.targets` 時無法刪除；未說明 `telescope` 省略時以空字串作唯一鍵 |
| 全文 | 未提及所有 `/api/` 請求禁止 `\|` 字元；未提及回應加 `Cross-Origin-*: same-origin`、瀏覽器跨域不可用 |
| 文件列出的 `GET /api/objects/{name}`（含 `api_key` 選填、依來源權限過濾光度/光譜） | 屬 `astronomy_tools_bp`，非本章；本章的 `GET /api/objects`（列表）與其餘 session 端點在文件中完全未描述 |

---

## 已知問題與注意事項

### 死程式碼 / 重複註冊
1. **`/api/generate_key` 重複註冊**：`api_routes.py`（`api.generate_key`）與本檔（`web_api.generate_key`）都註冊 `POST /api/generate_key`；`api_blueprint` 先註冊，實測請求由它處理，本檔版本永遠不會執行；兩者 403 body 形狀不同（`{"error"}` vs `{"success": false, "error"}`）。
2. **5 個未使用的 import**：`DataVisualization`（會載入整個 `modules.data_processing`）、`OBJECT_COMPAT_COLS`、`update_object_status`、`update_object_activity`（本身為 no-op）、`generate_api_key_for_user`。
3. `web_api/templates/`、`web_api/static/css`、`web_api/static/js` 皆為空目錄，但 blueprint 宣告了 `template_folder`/`static_folder`，`main.py` 也把 `routes/web_api/static` 列入 `_BLUEPRINT_STATIC_DIRS`。
4. `/api/auto-snooze/status`（admin）與 `/api/auto-snooze/stats`（登入）回同一份資料，僅鍵名不同。

### 會實際出錯的程式碼
5. **`web_api_bp.logger` 不存在**（`flask.Blueprint` 無 `logger` 屬性）：`api_get_stats`、`api_get_objects`、`api_get_object_tags`、`api_get_classifications` 的 `except` 區塊會再拋 `AttributeError`，前端拿到的是 Flask 預設 500（HTML），而非程式裡寫好的 fallback JSON（`marshal.js` 依賴這些 JSON 結構）。
6. **`POST /api/v1/observation_targets` 對 JSON 數字型 `ra`/`dec` 會崩潰**（`.strip()` 在 `try` 之外）→ 未捕捉例外 → 500 HTML。
7. **`manual_tns_download` 的 `imported_count`/`updated_count` 恆為 0**（`get_tns_statistics()` 沒有 `recent_downloads`）。
8. **`/api/stats` 的 `flag_count` 恆為 0**（`get_tag_statistics()` 沒有 `flag` 鍵）。
9. **`GET /api/objects?tag=flag` 恆為空**：`_build_where` 查 `cross_matches.status = 'Flagged'`，但全專案沒有任何程式寫入 `'Flagged'`；flag 功能實際寫的是 `cross_matches.flag` 布林欄。「flag」在專案裡有三種互不相通的定義（`cross_matches.status='Flagged'`、`cross_matches.flag`、`objects.tag @> ARRAY['flag']`（`get_marshal_overview_stats` 用））。
10. **`toggle_flag` 在物件沒有 cross-match 列時仍回 `success: true`**（`rowcount = 0` 不檢查）；flag 存於每列 cross-match 而非物件，且 `toggle_flag` 實際是「設值」而非切換。
11. **Raw 連線外洩**：`add_object`、`api_get_object_tags` 用 `get_tns_db_connection()` 但 `conn.close()` 不在 `finally`；任何例外都會讓一條 pool 連線永久 checked-out。
12. **`add_object` 寫入舊版 `status='Object'` 與 `name_prefix=''`**：手動新增的物件不會出現在 Inbox 篩選/統計（`status='Inbox'`），`classification=AT` 也找不到它（`name_prefix='AT'`），反而被歸入 `Classified`；`discovery_date` 只有整數天；`kinder_id` 不會被指派。
13. **`add_object` 重複檢查是子字串 `ILIKE`**（跨 `name`/`internal_name`/`other_name`）→ 合法的新名稱可能被誤判為已存在。

### 安全 / 權限
14. **DETECT 三個端點完全無認證**：任何人（含未登入）可用 `GET .../detect_cross_match?force=true` 或 `POST .../detect_images/generate` 觸發完整 DETECT pipeline（外部 TAP 查詢、影像下載、多表寫入），且 GET 帶副作用（非冪等；瀏覽器預抓/爬蟲即可觸發）。
15. **`GET /api/objects` 與 `POST /api/tns/search` 不做物件權限過濾**，且 `GET /api/objects` 連登入都不要求，還原樣輸出 `permission`、`groups` 欄位；`check_object_access`/`filter_by_source_permissions` 在本章零使用。
16. **guest 角色被視為已登入**：`toggle_flag`（寫入）、`fetch_photometry`（重外部呼叫、耗時）、`object-tags`、`tns/search`、`tns/stats`、`auto-snooze/stats`、`flag_status` 都只檢查 `'user' in session`。
17. **API key 授權失真**：`get_user_by_api_key()` 不載入群組 → `is_great_lab_member` 永遠缺席；B2 實際 admin-only、A2 的 `groups` 永遠空；B4 則對任何有效 key 開放寫入/刪除（無角色檢查）——兩個 v1 寫入端點的門檻互相矛盾。
18. API key 明文儲存、無到期/scope/速率限制；`?api_key=` 形式會進入代理/瀏覽器紀錄；`daily_trigger.html` 把使用者 key 直接渲染進 HTML meta。
19. `fetch_photometry`、`manual_tns_download`、`manual_auto_snooze`、DETECT 觸發都在請求內同步執行（可達數分鐘 / >100 s 重試睡眠），沒有去重、佇列或速率限制；`fetch_photometry` 由三個頁面可觸發，且無論結果一律回成功。

### 每次呼叫都執行 DDL
20. `flag_status`/`toggle_flag` → `_ensure_cross_matches_flag_column`（`ALTER TABLE` + commit）；`detect_cross_match` → `get_detect_results_for_target` 執行 4 條 `ALTER TABLE`（且從不 commit，每次被 rollback）；`observation_targets` GET/POST → `_ensure_auto_exposure_column`（POST 執行兩次）。`ALTER TABLE ... IF NOT EXISTS` 即使欄位已存在仍需取得表級鎖，會與 DETECT / 匯入的寫入互相等待。

### 行為不一致 / 易誤用
21. 未登入回應碼四種並存：401、403、200 假資料、無檢查（見「驗證與權限模型」）。
22. `detect_cross_match` 會去 `AT`/`SN` 前綴並不分大小寫；`detect_images/generate` 只不分大小寫；`detect_images` 精確比對——同一物件三種名稱解析規則。`get_detect_images` 名為 list 卻 `LIMIT 1`，docstring 說只回 `detect_combined` 但 SQL 也回並優先 `DESI`。
23. `generate_detect_images` 跑完 DETECT 卻不呼叫 `_soft_invalidate_page_cache()`（`trigger_detect_cross_match` 有）。
24. `manual_tns_download` 不像排程匯入那樣對新物件觸發 DETECT / 失效快取；`hour_offset` 未驗證型別。
25. `manual_auto_snooze` 回傳的是全庫 `Snoozed`/`Finish` 總數，不是本次變更數；`debug=True` 產生逐物件 debug log。
26. `observation_targets` POST 對既有 `(name, telescope)` 是靜默 upsert（仍回 201「added」），且不會重新啟用已停用的 target；`observation_logs` POST 省略 `telescope` 會以 `''` 當唯一鍵、`delete` 會刪掉該日該 target 所有望遠鏡的紀錄、孤兒紀錄無法經 API 刪除；`user_name` 以 `email OR name` 反查 `auth.users`。
27. `_normalize_target_precision` 把 RA/Dec 截到 4 位小數（≈0.36″），API 消費者拿不到 DB 內的完整精度；`observation_logs` 的 `trigger_exp`/`trigger_count` 以逗號串接字串輸出，型別與輸入不對稱。
28. `search_tns` 的 `limit` 沒有下限（負數 → SQL 錯誤 → 500）；`toggle_flag` 的 `flag` 值不驗證型別、原樣回顯。
29. `api_get_objects` 的 `date_from`/`date_to` 不驗證格式，非法值會走到有 bug 的 except（#5）。
30. `detect_pipeline._LOCK` 只在單一程序內互斥；多 worker gunicorn 下兩個 worker 可同時跑 DETECT。
31. `Manual_tns_download_snoozed.py` 與 `download_phot.py` 各自在模組載入時 `load_dotenv(kinder.env)`（後者 `override=True`），且 TNS bot 憑證使用兩套不同的環境變數名（`BOT_ID/BOT_NAME/API_KEY` vs `TNS_BOT_ID/TNS_BOT_NAME/TNS_API_KEY`）。
32. 檔內沒有 TODO/FIXME 標記（`grep -i "todo\|fixme"` 無結果）。
