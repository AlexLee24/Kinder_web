# Private Area：Daily Trigger、ePessto++ Support Team、Documents、Lab Info、觀測目標與觀測日誌 API（private_area blueprint）

> **注意**：本章記錄的是重構前（commit `c7f91a4`，2026-09-21）的狀態，檔案路徑為舊位置（`app/routes/…`、`app/modules/…`）。新位置請對照 `docs/ARCHITECTURE.md` §6「新舊路徑對照」；功能與行為在重構後完全相同。

## 概要

### 這個區塊負責什麼

`private_area` blueprint（`app/routes/private_area/private_area_routes.py`，Blueprint 名稱 `private_area`，無 `url_prefix`，`template_folder='templates'`、`static_folder='static'`）是 GREAT Lab 成員的內部工作區，包含四個頁面與一組支援 API：

| 子區塊 | 頁面 | 功能 |
|---|---|---|
| Daily Trigger | `/daily_trigger` | 管理 SLT / LOT 觀測目標清單（`obs.targets`）、Pre-Trigger 檢查清單、產生 ACP trigger 腳本、附可見度圖送到 Slack Control Room、記錄「今日已送出」狀態、維護月曆式觀測日誌（`obs.logs`） |
| ePessto++ Support Team | `/epessto_support` | 以「房間（room）」為單位的協作工作區：上傳 ePessto++ pipeline 的 `.asci` 光譜檔、依檔名解析成目標、記錄每個目標的分類/紅移/主星系/階段/圖片/完成狀態，並匯出 PDF 報告；資料存在 JSON 檔與磁碟目錄，不進資料庫 |
| Documents | `/documents`、`/documents/<filename>` | Markdown 文件庫（`tutorials/*.md`）：檢視、admin 線上編輯、貼圖上傳、置頂與排序、`{{hide=KEY}}` 環境變數代換 |
| Lab Info | `/greatlab_info` | 可編輯的連結卡片版面（`app/data/greatlab_links.json`） |
| 共用 API | `/api/targets*`、`/api/observation_logs*`、`/api/members`、`/api/search_target`、`/api/auto_exposure` | 供 Daily Trigger 頁使用的觀測目標 CRUD、日誌 CRUD、成員清單、TNS 目標搜尋、自動曝光表 |
| 管理 API | `/api/admin/private_area/page_perms` | admin 設定「除 GREAT_Lab 外還有哪些群組可進入各私人頁面」，由 admin 頁的 `app/routes/auth/static/js/admin.js` 呼叫 |
| 殘留/除錯 | `/private/calendar|telescope|projects|resources`、`/debug/database` | 前四個指向不存在的模板（見「已知問題」）；後者為 admin 用的 DB 連線檢查 |

### 與其他區塊的關係

- 導覽：`app/routes/basic/templates/_navbar.html`（第 79-92 行）與 `home.html`（第 96-108、155-167 行）只在 `session.user.is_great_lab_member` 為真時顯示「Private」下拉，內含 `url_for('private_area.daily_trigger')`、`private_area.epessto_support_page`、`private_area.documents_list`、`private_area.greatlab_info`（以及 `detect.detect_results`）。
- Daily Trigger 前端依賴其他 blueprint 的端點：`POST /astronomy_tools/generate_trigger_script`、`POST /generate_plot`、`POST /api/visibility_data`（皆在 `astronomy_tools_bp`）；目標名稱連到 `/object/<name>`（`objects_bp`）。
- ePessto++ 前端依賴：`GET /api/classifications`、`POST /api/object/<name>/fetch_photometry`（`web_api_bp`）；`GET /api/object/<name>/photometry/plot`、`GET /api/ned/cone`、`POST /api/ned/set_host`、`POST /api/ned/unset_host`（`objects_bp`）。
- 全域 hook（`app/main.py`）對本區塊所有 route 生效：`_enforce_allowed_host`（Host 不符 → 404）、`refresh_user_session`（每次請求由 DB 重算 `session['user']` 的 `is_admin`、`is_great_lab_member`、`picture`）、`_block_pipe_in_api_params`（所有 `/api/` 路徑的 query/form/JSON 內含 `|` → 400 `{"error": "Invalid character '|' is not allowed"}`）、`ParamOutOfRangeError` 全域 handler（→ 400）。
- 靜態檔：模板用 `url_for('static', filename='css/...')`，由 `main.py` 的自訂 `/static/<path>` 處理器依序在各 blueprint 的 `static/` 目錄尋找（`routes/private_area/static` 在清單中）。

### 權限判定函式（routes 檔第 35-131 行）

| 函式 | 條件 | 用於 |
|---|---|---|
| `is_admin_user()` | `session['user']['is_admin']` 為真 | page_perms API、documents 的 admin 動作、`/debug/database` |
| `can_view_private_area()` | 已登入且 `is_great_lab_member` 或 `is_admin` | 全部 ePessto++ API |
| `can_access_page(page_key)` | 已登入；admin 或 GREAT_Lab 成員直接通過；否則 `session['user']['groups']` 與 `get_page_groups(page_key)`（讀 `auth.system_settings` 的 `page_perm:<page_key>` JSON 陣列）有交集 | 四個頁面 route、`/daily_trigger/send_status`、`/daily_trigger/send_message` |
| `can_view_documents()` | 已登入且 `can_access_page('documents')` | documents 的 API |
| `_PRIVATE_PAGES` | `['daily_trigger', 'greatlab_info', 'epessto_support', 'documents']`，標籤 `_PRIVATE_PAGE_LABELS` | page_perms API 的合法 page 值 |

`session['user']` 的欄位由 `app/routes/auth/auth_routes.py` 維護：`email`、`name`、`picture`、`is_admin`（`auth.users.roles >= 50`）、`is_great_lab_member`（群組含 `GREAT_Lab` 或 admin）、`groups`、`api_key`。

### ePessto++ 房間資料模型（routes 檔第 133-573 行）

- 儲存檔：`app/routes/private_area/data/epessto_sessions.json`，結構 `{"rooms": {"<ROOM_ID>": {...}}}`。`_load_epessto_store()` 會把舊版「單一房間」格式（頂層只有 `batches`/`target_state`）遷移成 `rooms.legacy`（`password_hash=''`，因此無法用密碼加入），並正規化每個房間的欄位。
- 房間欄位：`room_name`、`password_hash`（werkzeug `generate_password_hash`）、`created_by`、`updated_by`、`invite_token`（`secrets.token_urlsafe(24)`）、`members`（以小寫 email 為 key：`email`、`display_name`、`is_admin`、`joined_at`、`last_seen`）、`kicked_users`（小寫 email 陣列）、`created_at`、`updated_at`（UTC ISO）、`batches`（`[{batch_id, uploaded_at, files:[...]}]`）、`target_state`（以 `target_key` 為 key：`host`、`z_from_host`、`z_estimate`、`type`、`phase`、`app`、`images:[{filename}]`、`completed`、`discuss`）。
- 房間 ID：`_generate_epessto_room_id()` 由字母表 `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`（排除 0/O/1/I）產生 6 碼。
- 「目前房間」存在 Flask session 的 `epessto_room_id`（`_EPESSTO_ROOM_SESSION_KEY`）。
- 檔案目錄：`data/epessto_uploads/rooms/<ROOM_ID>/files/*.asci` 與 `.../images/*.png|jpg|...`（`_get_epessto_upload_dir` / `_get_epessto_image_dir`，皆 `makedirs`）。目錄根層另有舊版遺留的 `*.asci` 與空的 `images/`，現行程式不再讀取。
- 生命週期：`_EPESSTO_ROOM_LIVE_HOURS = 1`（首頁「Live Rooms」只列 1 小時內有更新者）；`_EPESSTO_ROOM_IDLE_DELETE_HOURS = 24`（`_cleanup_epessto_stale_rooms()` 在每次 API 呼叫時刪除 24 小時未更新的房間，並 `shutil.rmtree` 其目錄）。`_get_epessto_room_or_response()` 在每次讀取時都會 `_upsert_epessto_room_member()`（更新 `last_seen`）並 `_touch_epessto_room()`（更新 `updated_at/updated_by`），所以房間有人開著（含 10 秒自動刷新）就不會過期。
- 成員管理權：`_epessto_can_manage_members(room)` = 站台 admin 或 `created_by` 本人。被踢者列入 `kicked_users`；之後任何需要房間的 API 都回 403 並清掉 session 中的房間；用邀請連結重新加入會自動解除踢除。
- 檔名解析 `_parse_epessto_filename()`：`t{TransientName}_{YYYYMMDD}_{grism}_{...}.asci` → `target_name`、`observed_date`、`grism`、`obs_meta`；`target_key = target_name.lower()`。
- `_serialize_from_filenames()` 產生前端用的 payload：`summary{today_date,total_files,done_targets,total_targets,remaining_targets}`、`targets[{target_name,target_key,is_done_today,is_discuss,dates[],grisms[],files[{filename,observed_on,is_today,grism,obs_meta}],user_fields{...},file_count}]`，並順手刪除 `target_state` 中已無檔案的 key。
- `_normalize_epessto_target_state()`：`app` 為空時會由舊欄位 `app_selected`（陣列）與 `app_custom` 合併；`images` 只保留有 `filename` 的項目。

### Documents 儲存模型（routes 檔第 28-95 行）

- 目錄 `app/routes/private_area/tutorials/`：`*.md` 文件（目前僅 `Test.md`）、`images/`（貼圖上傳目的地，目前為空）、`metadata.json`（`{"pinned": [...], "order": [...]}`，目前不存在 → 預設空）、`.env`。
- `.env` 由 `read_documents_env()` 解析成 dict（預設 `DOCUMENTS_EDITABLE=true`、`IMPORTANT_MESSAGE=''`）；目前檔內只有 `glab_internet_acc`、`glab_internet_pwd`、`SLACK_BOT_TOKEN`、`SLACK_CHANNEL_ID_CONTROL_ROOM`、`SLACK_CHANNEL_ID_CONTROL_ROOM_TEST` 五個 key，作為文件內 `{{hide=KEY}}` 的代換來源（讓文件能顯示帳密而不把值寫進 markdown）。
- `write_documents_env(updates)` 只寫出 `DOCUMENTS_EDITABLE` 與 `IMPORTANT_MESSAGE` 兩行（見「已知問題」）。
- `sanitize_document_filename()`：`secure_filename` 後強制 `.md` 副檔名。
- `documents_editable()`：`DOCUMENTS_EDITABLE` 字串是否為 `true`（大小寫不拘）。

## 頁面（HTML routes）

### /daily_trigger — Daily Trigger

- 路徑 / endpoint：`GET /daily_trigger` → `private_area.daily_trigger`
- 權限：需登入（否則 `flash('Please log in to access daily trigger.', 'warning')` → redirect `basic.login`）；`can_access_page('daily_trigger')`（否則 `flash('Access denied.', 'error')` → redirect `basic.home`）。
- 模板：`app/routes/private_area/templates/daily_trigger.html`
- 模板變數：`current_path='/daily_trigger'`、`all_groups`（admin 時為 `get_groups()` 的 key 清單，否則 `[]`；模板未使用）、`api_key`（`session['user']['api_key']` 或 `''`，寫入 `<meta name="x-api-key">`）、`user_display_name`、`user_email`（寫入 meta，供送出流程 Step 1 顯示）、`app_debug=config.DEBUG`（寫入 meta，前端據此把 Slack 頻道標示為 Test / Control Room）。
- 載入的資源：`css/private_area.css`、`js/daily_trigger.js`、Plotly 2.35.2（CDN，async）、`_navbar.html`、`_favicon.html`。
- 頁面區塊與互動：

| 區塊 | 元件 | 行為 / 呼叫 |
|---|---|---|
| Daily Trigger（`.pa-trigger-section`） | Pre-Trigger Checklist：A. New Objects（ATLAS、TNS AstroNotes、group message & DETECT）、B. Follow-up（Urgent kilonova、High、Normal）、C. Target List & Notes（target-sync、note-greatlab、note-staff）。共 9 個 checkbox；`note-staff` 為 disabled，只能由「Check Urgent Notes」按鈕（`checkUrgentTargetNotes`）依 `allTargetsCache` 中 Urgent 且 active 的目標是否都有 `plan`（Note）來勾選 | 全部勾選才解鎖右欄（`updateTriggerChecklistProgress`）|
| 同上 | Trigger Script Message：SLT/LOT 分頁（`switchScriptTelescope`）、LOT 時顯示 Program 下拉（由 active LOT 目標的 `program` 去重）、Generate 按鈕、唯讀 textarea、Visibility 縮圖（點擊開 lightbox `scriptVisImageModal`）、已送出狀態 chips（`SLT: not sent` + 每個 LOT program 一顆）、Copy、Send Message | Generate → `POST /astronomy_tools/generate_trigger_script`、`POST /generate_plot`；Send → 三步 Modal（`sendStep1Modal`/`sendStep2Modal`/`sendStep3Modal`）→ `POST /daily_trigger/send_message`；chips 由 `GET /daily_trigger/send_status` 填入 |
| Observation Targets（`.pa-obs-section`） | SLT Targets / LOT Targets 分頁（`switchTab`）；工具列：Weather（`weatherModal`，meteoblue iframe，lazy-load）、Update Mag（`updateTargetMags`）、Calendar（`calendarModal`，Google Calendar iframe，lazy-load）、Visibility（`openVisibilityPlot`，Plotly modal `visibilityPlotModal`）、Add SLT / Add LOT（`openTargetModal`） | Update Mag → `POST /api/targets/update-mags` 後 2.5 秒 `loadTargets`；Visibility → `POST /api/visibility_data`，右側 checkbox 同時 `PUT /api/targets/<id>/toggle` |
| 同上 | 目標表格欄位：Target（連 `/object/<name>`，附 `[Mag]`、月距/中天/最高仰角、迷你可見度 SVG）、RA/DEC（點擊切換 sexagesimal/decimal）、Priority（可排序）、Filter/Exposure、Total Exp（可排序）、Note、Note for GREATLab、Actions（active 開關、刪除、Edit、Copy 到另一望遠鏡、Trigger） | 資料 `GET /api/targets`；天文資訊 `POST /api/visibility_data`（telescope `ALL`, `n_steps` 80）；開關 `PUT /api/targets/<id>/toggle`；刪除 `DELETE /api/targets/<id>`；Trigger → `openSingleTriggerModal` |
| New Target Modal（`targetModal`） | 表單 `add-target-form`：Target Name（自動完成下拉 + 名稱提示）、Newest Mag、RA、Dec、Priority（Normal/High/Urgent）、Repeat、hidden telescope、Program (LOT)（LOT 才顯示）、Auto Exposure 按鈕（SLT 才顯示）、Filter rows（up/gp/rp/ip/zp/custom + exp + count；Add Filter、add All ugriz）、Note、Note for GREATLab、Cancel / Save Target | 自動完成 `GET /api/search_target?q=`（僅 SN/AT 開頭才查）；Auto Exposure `GET /api/auto_exposure?mag=&telescope=`；送出 `POST /api/targets` 或 `PUT /api/targets/<id>`（`editingTargetId`）。前端驗證：survey ID（ATLAS/PS/…）阻擋、ZTF 或非 AT/SN/EP 需 confirm、Urgent 必填 Note、LOT 必填 Program、至少一個 filter |
| Observation Log（`.pa-obs-log-section`） | 年/月下拉、Today、Refresh、Data（開 Google Drive 資料夾）、Show Filter 切換、Search target；圖例；月曆式表格（列 = 目標，欄 = 日期；順序 Urgent → LOT → SLT → Inactive → Orphan → Discontinued → Calibration）；每格顯示成員頭像/名稱、priority(-program)、repeat、Trigger/Observed 勾叉與 filter 明細、編輯鉛筆 | `GET /api/observation_log_months`、`GET /api/members`、`GET /api/targets`、`GET /api/observation_logs?year=&month=`；快取 `logDataCacheByMonth` |
| Log Modal（`logModal`） | Member 下拉、Target 顯示、hidden date/target/telescope、Priority、Repeat、Program、Is Triggered / Is Observed、Trigger/Observed filter rows、Cancel / Delete / Save Log | `POST /api/observation_logs`（儲存或 `action:'delete'`）後 `renderLogGrid(false,false,true)` 強制重抓 |
| Single-target Trigger Modal（`singleTriggerConfirmModal`） | 腳本預覽、可見度圖、Cancel / Send Now | `POST /astronomy_tools/generate_trigger_script`、`POST /generate_plot`、`POST /daily_trigger/send_message`（`mark_sent:false`）|
| 其他 | 回到頂端按鈕；`openDataBtn` 開 Google Drive；Show Filter 按鈕切換 hidden checkbox | — |

- 導向：從 navbar / home「Private → Daily Trigger」進入；未登入 → `/login`；無權 → `/`。頁內外連：`/object/<name>`（新分頁）、Google Drive、Google Calendar、meteoblue。

### /greatlab_info — Lab Info

- `GET /greatlab_info` → `private_area.greatlab_info`
- 權限：需登入（`flash('Please log in to access this page.', 'warning')` → `basic.login`）；`can_access_page('greatlab_info')`（`flash('Access denied.', 'error')` → `basic.home`）。
- 模板：`greatlab_info.html`；變數僅 `current_path='/greatlab_info'`。模板內以 `session.get('user').is_admin or is_great_lab_member` 決定是否顯示 Edit Layout / Save Layout / Cancel 按鈕（注意：透過 page_perms 額外群組進來的人看不到編輯按鈕，且後端 POST 也會拒絕）。
- 頁面區塊：標題；`#links-container` 由內嵌 JS 依 `[{title, cards:[{title, links:[{url,title,desc}]}]}]` 渲染 section → card → link；編輯模式（`body.is-editing`）可改標題/新增刪除 section、card、link；「New Section Block」按鈕。
- 呼叫：`GET /api/greatlab_links`（載入）、`POST /api/greatlab_links {data}`（Save Layout）。
- 導向：navbar / home「Lab Info」。連結皆 `target="_blank"`。

### /epessto_support — ePessto++ Support Team

- `GET /epessto_support` → `private_area.epessto_support_page`
- 權限：需登入（`flash('Please log in to access this page.', 'warning')`）；`can_access_page('epessto_support')`（`flash('Access denied.', 'error')` → home）。
- 模板：`epessto_support.html`；變數僅 `current_path='/epessto_support'`。資源：`css/private_area.css`、`css/epessto_support.css`、`js/epessto_support.js`、Plotly 2.35.2、jsPDF 2.5.1（CDN）。
- 頁面區塊：

| 區塊 | 元件 | 呼叫 |
|---|---|---|
| Home Panel（`#epHomePanel`） | Create Room 卡（Room Name、Password、Create Room、結果提示）；Live Rooms 卡（1 小時內更新的房間清單 + join 按鈕；直接輸入 Room ID + Join，密碼用 `prompt()` 取得） | `POST /api/epessto_support/rooms/create`、`GET /api/epessto_support/rooms/live`、`POST /api/epessto_support/rooms/join` |
| Workspace Panel（`#epWorkspacePanel`） | 工具列：房間徽章、Members（開 `epRoomMembersModal`）、Invite（複製 `?invite=<token>` 連結到剪貼簿）、Upload .asci（`<input type=file accept=.asci multiple>`）、Preview（產生 PDF 並在新分頁開啟）、Refresh、Clear（三次 confirm）、計數 `done/total`、Auto（每 10 秒 `loadSession`）、Leave | `GET room/members`、`POST room/kick`、`POST upload`、`GET session`、`DELETE clear`、`POST room/leave` |
| 狀態列 | 訊息 + 各 type 計數 | — |
| Targets 側欄 | 目標按鈕清單（done / discuss / pending 樣式） | — |
| Target widget | 標題連 `/object/<name>`、mark done / mark discuss / NED 按鈕；Reporting Group（API 找得到時唯讀，否則可輸入）；Host、z (From Host)、z (Estimate)、Type（`/api/classifications`，S 開頭優先）、Phase（Pre-Peak/Around Peak/Post-Peak）、Classification Method；Light curve（Extinction / K-correction 切換、Fetch、Refresh，Plotly）；檔案列表（filename/grism/date）；Images（貼上上傳，最多 4 張，點圖放大，delete）；Prev / Next / Remove（三次 confirm） | `POST target_state`、`GET /api/search_target`（解析 reporting group 與 API 名稱）、`GET /api/object/<name>/photometry/plot`、`POST /api/object/<name>/fetch_photometry`、`POST/DELETE target_image`、`GET image/<filename>`、`DELETE target` |
| Room Members Modal | 成員列表（creator/admin/you 標籤、last seen、kick 按鈕） | `GET room/members`、`POST room/kick` |
| NED Explorer Modal | Survey 下拉、Radius、Re-search；左側 Aladin Lite（以 `srcdoc` iframe 載入 jQuery + Aladin v3，postMessage 溝通）；右側 NED 結果表（Set as Host / Unset Host） | `GET /api/search_target`（解析座標）、`GET /api/ned/cone`、`POST /api/ned/set_host`、`POST /api/ned/unset_host`，並回寫 `POST target_state {host, z_from_host}` |

- 導向：navbar / home「ePessto++ Support Team」；邀請連結 `/epessto_support?invite=<token>` 於載入時自動 `POST rooms/join_by_invite` 並用 `history.replaceState` 清除參數；初始化順序：`loadTypeOptions` → invite join 或 `GET room/current` → `GET rooms/live` → 已加入則 `GET session`。

### /documents — Documents 列表

- `GET /documents` → `private_area.documents_list`
- 權限：需登入（`flash('Please log in to access documents.', 'warning')` → login）；`can_access_page('documents')`（`flash('Access denied.', 'error')` → home）。
- 副作用：`ensure_tutorials_dir()`（`makedirs`）；列出 `tutorials/*.md`；讀 `metadata.json`、`.env`。
- 模板：`documents.html`；變數：`current_path='/documents'`、`documents=[{filename, title (去 .md、底線→空白、Title Case), is_pinned, order_idx}]`（排序：置頂優先 → `order` 索引 → 標題）、`is_admin`、`documents_editable`、`important_message`（模板未渲染）。
- 頁面區塊：標題；admin 面板（`#docsAdminPanel`：新檔名輸入 + Create Document，`documents_editable` 為假時 disabled）；文件清單 `#docList`（每項：拖曳把手（admin 或 editable 時）、連到 `url_for('private_area.document_view', filename=...)`、置頂圖示、Pin 按鈕）；無文件時 "No documents available"；回頂按鈕。
- 呼叫（`documents.js`）：`POST /api/documents/create {filename}` → 成功後 `location.href='/documents/<filename>'`；拖曳結束或按 Pin → `POST /api/documents/metadata {order, pinned}`。

### /documents/<filename> — 文件檢視/編輯

- `GET /documents/<filename>` → `private_area.document_view`
- 權限：同上。`sanitize_document_filename` 失敗或檔案不存在 → `abort(404)`。
- 模板：`document_view.html`；變數：`current_path='/documents'`、`filename`（已淨化）、`title`、`is_admin`、`documents_editable`、`important_message`（未渲染）。資源：marked.js（CDN）、`js/document_view.js`。
- 頁面區塊：標題；「Back to Documents」（`url_for('private_area.documents_list')`）；`#content` markdown 渲染區；admin 專屬：Markdown Guide 提示（含 `{{hide=KEY}}` 說明）、雙欄編輯器（textarea + 即時預覽）、工具列 Edit Document / Save Changes / Cancel / 狀態文字；hidden `#documentMeta`（`data-filename`、`data-is-admin`、`data-editable`）。
- 呼叫（`document_view.js`）：`GET /api/documents/<filename>/content`（載入，顯示 `content`，編輯器使用 `raw_content`）；`PUT` 同路徑 `{content}`；在編輯器貼上圖片 → `POST /api/documents/upload-image`（multipart `image`）→ 把回傳的 `markdown` 插入游標處。

### /private/calendar、/private/telescope、/private/projects、/private/resources（模板不存在）

- endpoint：`private_area.private_calendar`、`private_telescope`、`private_projects`、`private_resources`（皆 GET）。
- 權限：`/private/calendar`：需登入（`flash('Please log in to access calendar.', 'warning')`）且 `is_great_lab_member` 或 `is_admin`（否則 `flash('Access denied.', 'error')` → home）。其餘三個：需登入（各自 flash 文字 `...telescope management` / `...projects` / `...resources`）；`user_exists(email)` 否則 `flash('Access denied.', 'error')`；再以 `get_users()` 查 DB 群組，須含 `'GREAT_Lab'`（否則 `flash('Access denied. GREAT Lab members only.', 'error')`；注意 admin 若非 GREAT_Lab 群組亦被拒）。
- 模板：`private_calendar.html`、`private_telescope.html`、`private_projects.html`、`private_resources.html` — 全站找不到這些檔案，通過權限者會得到 `TemplateNotFound`（500）。沒有任何模板或 JS 連到這四個路徑。

## API 與動作端點

權限欄縮寫：**登入** = `'user' in session`；**GL/admin** = `is_great_lab_member` 或 `is_admin`（`can_view_private_area()` 同義）；**page:<key>** = `can_access_page(key)`；**房間** = 需 GL/admin 且 session 已加入房間（`_get_epessto_room_or_response(require_room=True)`：無房間 → 401 `{"error":"No room joined"}`；被踢 → 403 `{"error":"You were removed from this room"}`）。所有 `/api/` 路徑另受全域 `|` 字元檢查（400）。

### 頁面群組權限管理

| 方法 | 路徑 | endpoint | 權限 | 輸入 | 成功回應 | 失敗回應 | 副作用 |
|---|---|---|---|---|---|---|---|
| GET | `/api/admin/private_area/page_perms` | `private_area.api_get_private_page_perms` | 僅 admin | 無 | `{success:true, perms:{<page>:[group,...]}, pages:[...], labels:{...}}` | 403 `{error:'Forbidden'}` | 讀 `auth.system_settings`（`page_perm:<page>`）×4 |
| POST | `/api/admin/private_area/page_perms` | `private_area.api_add_private_page_perm` | 僅 admin | JSON `page`（須在 `_PRIVATE_PAGES`）、`group_name`（非空；不檢查群組是否存在） | `{success:true}` | 403；400 `{error:'Invalid page or group'}`；500 `{error:'Failed to save'}` | `set_page_groups` → upsert `auth.system_settings` |
| DELETE | `/api/admin/private_area/page_perms` | `private_area.api_remove_private_page_perm` | 僅 admin | 同上 | `{success:true}` | 同上 | 同上（移除） |

呼叫者：`app/routes/auth/static/js/admin.js`（第 1575、1633、1656 行）。

### Daily Trigger 動作

| 方法 | 路徑 | endpoint | 權限 | 輸入 | 成功回應 | 失敗回應 | 副作用 |
|---|---|---|---|---|---|---|---|
| GET | `/daily_trigger/send_status` | `private_area.daily_trigger_send_status` | page:daily_trigger（未登入亦 403） | 無 | `{success:true, status:{day:'YYYY-MM-DD', SLT:{sent_by,sent_at}|null, 'LOT:<program>':{...}, ...}}` | 403 `{error:'Forbidden'}` | 讀 `app/data/trigger_send_status.json`；INFO log |
| POST | `/daily_trigger/send_message` | `private_area.daily_trigger_send_message` | 登入（401 `{success:false,error:'Please log in.'}`）+ page:daily_trigger（403 `'Access denied.'`） | JSON：`telescope`（upper，須 `SLT`/`LOT`）、`program`（str，LOT 用）、`greeting`（str）、`script`（str，非空）、`targets`（list of dict：`name, ra, dec, mag, priority, priority_message, repeat, auto_exp, program, filter_input, exp_time, count`）、`mark_sent`（bool，預設 true） | `{success:true, status:<send_status>, log_warnings:[...]}` | 400 `'Invalid telescope'` / `'Script message is empty'`；500 `{success:false,error:<Slack 錯誤>}` | 見下方流程說明 |

`send_message` 詳細步驟：
1. `_render_trigger_visibility_image(telescope, targets)`：對有 RA/Dec 的目標 `obsplan.create_ephem_target`，觀測者 `create_ephem_observer('Lulin Observatory','120:52:21.5','23:28:10.0',2800)`，時窗 = trigger day 17:00 至次日 09:00（Asia/Taipei），`plot_night_observing_tracks(..., simpletracks=True, n_steps=500, savepath=<NamedTemporaryFile .jpg>)`；無可畫目標或失敗 → `None`（仍送純文字）。
2. `trigger_send.send_to_slack(greeting, script, image_path)`：讀 `SLACK_BOT_TOKEN`；頻道 = `config.DEBUG` 時 `SLACK_CHANNEL_ID_test`，否則 `SLACK_CHANNEL_ID_CONTROL_ROOM`（皆來自 `kinder.env`）；三則獨立訊息：`chat.postMessage(greeting)`、`trigger_script.txt`（外部上傳三步驟 `files_getUploadURLExternal` → HTTP POST → `files_completeUploadExternal`）、`visibility_plot.jpg`。任何 `SlackApiError`/`requests` 例外 → `RuntimeError` → 500。`finally` 刪除暫存圖。
3. `mark_sent` 為真 → `trigger_send.mark_sent(telescope, sent_by, program)` 寫入 `trigger_send_status.json`（key `SLT` 或 `LOT:<program>`，值 `{sent_by, sent_at (Asia/Taipei)}`；`day` 不同即整份重置，trigger day 在 08:00 Asia/Taipei 換日）；否則只讀取現況。
4. `_log_triggered_targets(telescope, targets, sent_by)`：每個目標 → `auto_exp` 時用 `trigger_script.exposure_time(mag)` 換算 filter 清單（非 dict 結果 = 太暗/無效 → 略過不記錄）；否則由 `filter_input/exp_time/count` 逗號字串拆解；`upsert_observation_log(name, obs_date, sent_by, True, False, <filter JSON>, None, None, None, None, None, priority=..., telescope_use=telescope, repeat_count=..., program=...)`。失敗只收集到 `log_warnings`，不影響 200。

### ePessto++ Support API

| 方法 | 路徑 | endpoint | 權限 | 輸入 | 成功回應 | 失敗回應 | 副作用 |
|---|---|---|---|---|---|---|---|
| GET | `/api/epessto_support/rooms/live` | `api_epessto_support_live_rooms` | GL/admin | 無 | `{success, rooms:[{room_id, room_name, updated_by, updated_at}]}`（1 小時內更新，依 `updated_at` 降冪） | 403 `{error:'Forbidden'}` | 讀/清理/寫 `epessto_sessions.json`；若 session 已在房間則更新該房 `members.last_seen`、`updated_at` |
| POST | `/api/epessto_support/rooms/create` | `api_epessto_support_create_room` | GL/admin | JSON `room_name`（必填）、`password`（必填） | `{success, room_id, room_name, invite_token}` | 400 `'room_name is required'` / `'password is required'` | 新增房間（建立者為首位成員）；寫 JSON；`session['epessto_room_id']=room_id` |
| POST | `/api/epessto_support/rooms/join` | `api_epessto_support_join_room` | GL/admin | JSON `room_id`（轉大寫）、`password` | `{success, room_id, room_name, invite_token}` | 400 `'room_id and password are required'`；404 `'Room not found'`；401 `'Invalid password'`（含 `password_hash` 為空的 legacy 房） | touch 房間、寫 JSON、設 session（成員資料於下一次 API 呼叫時才加入；不檢查 `kicked_users`） |
| POST | `/api/epessto_support/rooms/join_by_invite` | `api_epessto_support_join_by_invite` | GL/admin | JSON `invite_token` | `{success, room_id, room_name, invite_token}` | 400 `'invite_token is required'`；404 `'Invalid invite link'` | 若在 `kicked_users` 則移除；加入成員；touch；寫 JSON；設 session |
| GET | `/api/epessto_support/room/current` | `api_epessto_support_current_room` | GL/admin | 無 | 未加入 `{success, joined:false, room_id:null}`；已加入 `{success, joined:true, room_id, room_name, invite_token, updated_at}` | 403 | 同 live |
| POST | `/api/epessto_support/room/leave` | `api_epessto_support_leave_room` | GL/admin | 無 | `{success:true}` | 403 | 只移除 session key，不更動房間成員 |
| GET | `/api/epessto_support/room/members` | `api_epessto_support_room_members` | 房間 | 無 | `{success, can_manage, members:[{email, display_name, is_owner, is_admin, joined_at, last_seen, is_self, can_kick}]}`（owner → admin → 名稱排序） | 401/403 | 讀寫 JSON（touch） |
| POST | `/api/epessto_support/room/kick` | `api_epessto_support_room_kick` | 房間 + 管理者（admin 或 creator） | JSON `member_email` | `{success:true}` | 403 `'Forbidden'`；400 `'member_email is required'` / `'Cannot kick room creator'` / `'Cannot kick yourself'` | 從 `members` 移除、加入 `kicked_users`；寫 JSON |
| POST | `/api/epessto_support/upload` | `api_epessto_support_upload` | 房間 | multipart `files`（多個；只收 `.asci`，`secure_filename`） | `{success, summary, targets, batches}` | 400 `'No files uploaded'` | 寫入 `rooms/<id>/files/`（同名覆蓋）；新增 batch；寫 JSON |
| GET | `/api/epessto_support/session` | `api_epessto_support_session` | 房間 | 無 | 無檔 `{success, summary:null, targets:[], batches:[]}`；否則 `{success, summary, targets, batches}` | 401/403 | 讀寫 JSON（touch） |
| POST | `/api/epessto_support/target_state` | `api_epessto_support_target_state` | 房間 | JSON `target_key`（小寫）、`updates`（物件；接受 `host, z_from_host, z_estimate, type, phase, app, completed, discuss`；其餘 key 忽略） | `{success, summary, targets, batches}` | 400 `'target_key is required'` / `'updates must be an object'` | `completed` 與 `discuss` 互斥（completed 優先）；寫 JSON |
| DELETE | `/api/epessto_support/target` | `api_epessto_support_remove_target` | 房間 | JSON `target_key` | `{success, removed:<n>, summary, targets, batches}` | 400 `'target_key is required'` | 刪除該目標所有 `.asci`（依檔名解析比對）與圖片檔、移除 `target_state[key]`、清空的 batch 移除；寫 JSON |
| POST | `/api/epessto_support/target_image` | `api_epessto_support_target_image_upload` | 房間 | form `target_key`、file `image`（`.png .jpg .jpeg .webp .gif`） | `{success, summary, targets, batches}` | 400 `'target_key is required'` / `'image is required'` / `'unsupported image type'` / `'max 4 images per target'` | 存 `rooms/<id>/images/<target_key>_<uuid>.<ext>`；寫 JSON |
| DELETE | `/api/epessto_support/target_image` | `api_epessto_support_target_image_delete` | 房間 | JSON `target_key`、`filename` | 同上 | 400 `'target_key and filename are required'` | 從 state 移除並刪檔（`basename` 防穿越）；寫 JSON |
| GET | `/api/epessto_support/image/<path:filename>` | `api_epessto_support_image_file` | 房間 | 路徑參數（取 `basename`） | `send_file` 圖片 | 404 `{error:'Not found'}` | 讀檔；touch 房間 |
| DELETE | `/api/epessto_support/clear` | `api_epessto_support_clear` | 房間 | 無 | `{success, removed:<n>}` | 401/403 | 刪除房間所有 `.asci` 與圖片、`batches=[]`、`target_state={}`；寫 JSON |

### Documents API

| 方法 | 路徑 | endpoint | 權限 | 輸入 | 成功回應 | 失敗回應 | 副作用 |
|---|---|---|---|---|---|---|---|
| POST | `/api/documents/metadata` | `api_documents_metadata` | admin **或** `documents_editable()` 為真（預設 true → 無需登入） | JSON（`request.json`，非 JSON 會由 Flask 回 415/400）`pinned:[]`、`order:[]` | `{success:true}` | 403 `'Forbidden'`（僅在 admin 為假且 editable 為假時）；400 `'Invalid request'`（空 body） | 寫 `tutorials/metadata.json` |
| GET | `/api/documents/settings` | `api_documents_settings` | `can_view_documents()` | 無 | `{success, documents_editable:bool, important_message, is_admin}` | 403 `'Forbidden'` | 讀 `tutorials/.env` |
| POST | `/api/documents/settings` | 同上 | `can_view_documents()` + admin | JSON `documents_editable`（bool，預設 true）、`important_message`（str） | `{success:true}` | 403 `'Forbidden'` / `'Admin only'` | `write_documents_env` **覆寫整個 `.env`，只留兩個 key**（見已知問題）。目前無任何前端呼叫此端點 |
| POST | `/api/documents/create` | `api_documents_create` | `can_view_documents()` + admin + editable | JSON `filename`（自動補 `.md`）、`content`（選填） | `{success, filename}` | 403 `'Admin only'` / `'Editing is disabled'`；400 `'Invalid filename'`；409 `'Document already exists'` | 建立 `tutorials/<filename>`（空內容時寫 `# <Title>\n\n`） |
| GET | `/api/documents/<filename>/content` | `api_documents_content` | `can_view_documents()` | 路徑參數 | `{success, content:<{{hide=KEY}} 已代換>, raw_content:<原文>}`；找不到 KEY 時代換成 `[KEY NOT FOUND IN ENV]` | 403；400 `'Invalid filename'`；404 `'Document not found'` | 讀 `.md`、必要時讀 `.env` |
| PUT | `/api/documents/<filename>/content` | 同上 | `can_view_documents()` + admin + editable | JSON `content` | `{success:true}` | 403 `'Admin only'` / `'Editing is disabled'`；400/404 同上 | 覆寫 `.md` |
| POST | `/api/documents/upload-image` | `api_documents_upload_image` | `can_view_documents()` + admin + editable | multipart `image`（副檔名 `.png .jpg .jpeg .gif .webp`） | `{success, image_url:'/tutorials/images/<name>', markdown:'![](<url>)'}` | 403；400 `'Missing image file'` / `'Unsupported image type'` | 存 `tutorials/images/<UTC yyyymmdd_HHMMSS>_<uuid8><ext>` |
| GET | `/tutorials/images/<path:filename>` | `serve_tutorial_image` | **公開（無任何檢查）** | 路徑參數（含 `..` 或以 `/` 開頭 → 400） | 圖檔（`send_from_directory`） | 400；404 | 讀檔 |

### 成員與 Lab Info API

| 方法 | 路徑 | endpoint | 權限 | 輸入 | 成功回應 | 失敗回應 | 副作用 |
|---|---|---|---|---|---|---|---|
| GET | `/api/members` | `api_members` | 登入（含 guest） | 無 | `{success, members:[{email, name, picture}]}`（依 name 排序；條件 `... or True` 使所有使用者都列出） | 401 `{error:'Unauthorized'}` | `get_users()` 讀 `auth.users` + `auth.usr_group` |
| GET | `/api/greatlab_links` | `api_greatlab_links` | 登入 | 無 | `{success, data:[{title, cards:[{title, links:[{url,title,desc}]}]}]}`；檔案不存在或 JSON 損壞 → 內建預設（Lulin weather 一筆） | 401 | 讀 `app/data/greatlab_links.json`（`private_area_bp.root_path/../../data`） |
| POST | `/api/greatlab_links` | 同上 | 登入 + GL/admin | JSON `data`（不驗證結構；`request.json` 非 silent） | `{success:true}` | 401；403 `'Forbidden. GREAT Lab members only.'` | 覆寫 `greatlab_links.json`（`indent=4`） |

### 觀測目標（obs.targets）API

| 方法 | 路徑 | endpoint | 權限 | 輸入 | 成功回應 | 失敗回應 | 副作用 |
|---|---|---|---|---|---|---|---|
| GET | `/api/targets` | `api_observation_targets` | 登入（含 guest） | 無 | `{success, targets:[...]}`（`get_observation_targets(active_only=False)`；每筆：`id/target_id, active/is_active, name, mag, ra(str), dec(str), telescope, program, priority, filters:[{filter,count,exp}], repeat/repeat_count, plan, note/note_gl, create_by, created_by(email), auto_exposure`；排序 active DESC, priority, name） | 401 | 讀 `obs.targets` LEFT JOIN `auth.users`；首次呼叫會 `ALTER TABLE` 補 `auto_exposure` 欄位（冪等） |
| POST | `/api/targets` | 同上 | 登入 + GL/admin | JSON `telescope, name, mag, ra, dec, priority, repeat_count(0), auto_exposure(false; LOT 強制 false), filters:[{filter,exp,count}], plan, program, note_gl` | `{success, id}` | 401；403 `'Forbidden'`；500 `'Database error'`（含 RA/Dec 解析失敗、CHECK 違反） | `save_observation_target`：`INSERT ... ON CONFLICT (name, telescope) DO UPDATE`（同名同望遠鏡會直接覆蓋既有列、保留其 `active`）；`create_by` 由 session email 查 `auth.users` |
| PUT | `/api/targets/<int:target_id>` | `api_observation_target_update` | 登入 + GL/admin | 同 POST | `{success:true}` | 401/403；500 `'Database error'`（含無異動列、unique 衝突） | `UPDATE obs.targets`（`repeat_count→repeat`、`note_gl→note`、filters → `plan_filter/plan_count/plan_time`） |
| DELETE | `/api/targets/<int:target_id>` | `api_observation_target_delete` | 登入 + GL/admin | 無 | `{success:true}` | 401/403；500 | `DELETE FROM obs.targets`（`obs.logs.target_id` FK `ON DELETE SET NULL` → 日誌變孤兒） |
| PUT | `/api/targets/<int:target_id>/toggle` | `api_observation_target_toggle` | 登入 + GL/admin | JSON `is_active`（必填） | `{success:true}` | 400 `'is_active field required'`；500 | `UPDATE obs.targets SET active` |
| POST | `/api/targets/update-mags` | `api_update_target_mags` | 登入 + GL/admin | 無 | 立即回 `{success, message:'Magnitude update started'}` | 401/403 | 啟動 daemon thread 執行 `phot_scheduler.update_target_mags()`（讀 TNS photometry DB、更新 active 目標的 `mag`、同步 AT→SN 前綴到 targets/logs；EP 名稱經 `transient.objects.internal_name/tag` 解析） |

### 搜尋與自動曝光

| 方法 | 路徑 | endpoint | 權限 | 輸入 | 成功回應 | 失敗回應 | 副作用 |
|---|---|---|---|---|---|---|---|
| GET | `/api/search_target` | `api_search_target` | 登入 | query `q`（< 2 字元 → `{results:[]}`） | `{results:[{name, prefix, reporting_group, source_group, ra, dec, redshift, mag(brightest_mag 或 discoverymag), type, internal_names}]}`（最多 15 筆，discoverydate desc） | 401；例外時記 log 並回 200 `{results:[]}` | `transient.search_tns_objects` 讀 `transient.objects` |
| GET | `/api/auto_exposure` | `api_auto_exposure` | 登入 | query `mag`（必填）、`telescope`（預設 `SLT`，僅原樣回傳，不影響查表） | `{success, filters:[{filter, exp, count}], telescope}` | 400 `'mag parameter required'`；查表回字串（`"Too faint to observe"` / `"Invalid magnitude"`）時回 **200** `{error:<str>}`；例外 500 | `observation_script.exposure_time(mag)`（12–22 等的固定表；`>22` 太暗；<12 用 12 等設定） |

### 除錯與觀測日誌

| 方法 | 路徑 | endpoint | 權限 | 輸入 | 成功回應 | 失敗回應 | 副作用 |
|---|---|---|---|---|---|---|---|
| GET | `/debug/database` | `debug_database` | 僅 admin（含未登入皆 403 `{error:'Access denied'}`） | 無 | `{total_objects:<int>, sample_objects:[[name_prefix,name,obj_id],...]}`（10 筆） | 500 `{error}` | `SELECT COUNT(*)`/`LIMIT 10` on `transient.objects` |
| GET | `/api/observation_log_months` | `api_get_observation_log_months` | 登入 | 無 | `{success, months:[{year, month}]}`（DISTINCT，降冪） | 401 `{success:false,error:'Unauthorized'}`；500 | 讀 `obs.logs` |
| GET | `/api/observation_logs` | `api_get_observation_logs` | 登入 | query `year`、`month`（`get_int_arg`；缺一 → 400 `'Year and month are required'`；非整數/超界 → `ParamOutOfRangeError` → 400） | `{success, logs:[...]}`（每筆：`log_id, target_id, date/obs_date('YYYY-MM-DD'), name/target_name, telescope/telescope_use, program, priority, repeat/repeat_count, trigger_by, triggered_by(email)/user_name, trigger/is_triggered, observed/is_observed, trigger_filter/trigger_count/trigger_exp（逗號字串）, trigger_filters[{filter,count,exp}], observed_* 同`） | 401；400；500 | 讀 `obs.logs` LEFT JOIN `auth.users`、`obs.targets`（月份範圍查詢） |
| POST | `/api/observation_logs` | 同上 | 登入（含 guest） | JSON：`action`（`'delete'` 時：`target_name`、`obs_date`、`telescope_use`）；否則 `target_name`（或舊版 `target_id` → 以 `get_observation_targets()` 反查名稱）、`obs_date`、`user_name`（預設 session name/email）、`is_triggered`、`is_observed`、`trigger_filter`（list → JSON 字串，或 csv 字串）、`trigger_exp`、`trigger_count`、`observed_filter/exp/count`、`priority`、`telescope_use`、`repeat_count`；**`program` 欄位被忽略** | 刪除 `{success:true}`；儲存 `{success:true}` | 400 `'Target Name and Date required'`；刪除失敗 404 `'Log not found or failed to delete'`；儲存失敗 500 `'Failed to save log'`；例外 500 | `delete_observation_log(name, date, telescope)`（先以 `obs.targets` 反查 `target_id`，孤兒日誌無法刪除）；`upsert_observation_log`（以 `(name, date, telescope)` 判斷更新或插入；`trigger_by` 以 email 或 name 查 `auth.users`；priority 只做 title-case 正規化） |

## 導向與流程

### Daily Trigger 完整流程

1. 進入：navbar/home「Private → Daily Trigger」→ `GET /daily_trigger`。未登入 → flash + `/login`；無權 → flash + `/`。
2. 頁面載入（`DOMContentLoaded`）：
   - `loadTargets()` → `GET /api/targets` → 快取 `allTargetsCache` → `_rebuildSentChips()`（依 active LOT 目標的 program 建 `LOT <P>: not sent` chips）→ `sortTargets('SLT'|'LOT','priority')` 渲染兩張表 → 400ms 後 `loadAstroInfoForTargets()` → `POST /api/visibility_data`（date = 中午前算前一天；location `120:52:21 23:28:10 2862`；timezone 8；telescope `ALL`；`n_steps` 80）→ 填月距/中天/最高仰角與迷你 SVG。
   - `initObservationLog()` → `GET /api/observation_log_months`（自動補上當月）→ `fetchMembers()`（`GET /api/members`，建立 `membersMap`，含舊名稱對照 `LOG_USER_NAME_MAP`）→ `renderLogGrid(true)` → `GET /api/targets` + `GET /api/observation_logs?year&month` → 建表並捲到今天。
   - `initTriggerChecklist()`、`loadSentStatus()` → `GET /daily_trigger/send_status` → `renderSentStatus`。
3. 維護目標：Add SLT/LOT 或 Edit/Copy → `targetModal`；名稱輸入觸發 `GET /api/search_target?q=`（僅 SN/AT 前綴）與名稱提示；Auto Exposure → `GET /api/auto_exposure?mag=&telescope=`；儲存 → `POST /api/targets`（新增）或 `PUT /api/targets/<id>`（編輯）→ `loadTargets()`。切換 active → `PUT /api/targets/<id>/toggle`；刪除 → `DELETE /api/targets/<id>`；Update Mag → `POST /api/targets/update-mags`（背景執行緒）→ 2.5 秒後重新載入。Visibility 按鈕 → `POST /api/visibility_data`（依目前分頁）→ Plotly；右側 checkbox 同時 `PUT .../toggle` 並 `loadTargets()`。
4. 檢查清單：勾滿 9 項（第 9 項由「Check Urgent Notes」自動判定）→ 解鎖 Generate 與腳本欄。
5. 產生腳本：選 SLT 或 LOT（LOT 需選 program，選單來自 active LOT 目標）→ 篩出該範圍 active 目標並依 Urgent→High→Normal→名稱排序 → `_buildScriptPayloadTarget`（`priority_message` 取自 Note，「Note for GREATLab」不進腳本；非 auto_exp 時展開 `filter_input/exp_time/count` 逗號字串）→ `POST /astronomy_tools/generate_trigger_script {telescope, targets}` → textarea = 中英問候語 + `data.script`；同時 `renderScriptVisibilityImage()` → `POST /generate_plot`（`targets:[{object_name, ra, dec}]`）→ 顯示 `plot_url`（`/ov_plot/<uuid>.jpg`）縮圖。Copy 按鈕複製 textarea。
6. 送出：`startSendTriggerFlow()` 要求已產生腳本且 `scriptVisPlotUrl` 已存在（圖仍在渲染時拒絕）→ Step 1 確認帳號（meta 的 name/email）→ Step 2 檢視望遠鏡/目標/圖 → Step 3 確認頻道（DEBUG 時「Test」，否則「Control Room」）→ `POST /daily_trigger/send_message {telescope, program, greeting, script, targets}`。
7. 後端：重新渲染可見度圖（不信任前端的 plot_url，因 `/generate_plot` 的共享資料夾只保留 10 張）→ Slack 三則訊息 → `mark_sent()` 寫 `trigger_send_status.json`（chip 變「sent by X at HH:MM」，08:00 Asia/Taipei 重置）→ 每個目標 `upsert_observation_log(..., is_triggered=True, is_observed=False, trigger_filter=<JSON>, priority, telescope_use, repeat_count, program)` → 回傳 `status` 與 `log_warnings`。
8. 前端顯示「Sent to Slack for SLT/LOT (P).」（附 log warnings）並更新 chips；Observation Log 表格不會自動刷新（需按 Refresh 或切月份）。
9. 單一目標 Trigger（表格列的「Trigger」）：`openSingleTriggerModal(id)` → 以 Edit 模式開啟 `targetModal`（標題改為 Confirm & Trigger Target、按鈕 Next: Generate Script）→ 儲存（`POST`/`PUT /api/targets`）→ `startSingleTargetTriggerFlow()` → `POST /astronomy_tools/generate_trigger_script`（單一目標）→ 預覽 + `POST /generate_plot` → Send Now → `POST /daily_trigger/send_message {..., mark_sent:false}`（不改 chips，但仍寫 `obs.logs`）→ 1.2 秒後關閉。
10. 觀測日誌手動維護：點格子鉛筆 → `openLogModalEdit(uniqueKey, date)` 預填（priority/program/repeat 來自既有日誌或目標）→ Save Log → `POST /api/observation_logs`（`priority` 會被組成 `"<Priority> - <Program>"`，見已知問題）→ 成功後強制重抓；Delete → `POST /api/observation_logs {action:'delete', target_name, obs_date, telescope_use}`。

### ePessto++ Support 流程

1. 進入 `GET /epessto_support`（權限同上）。若 URL 帶 `?invite=<token>` → `POST rooms/join_by_invite` → 成功即進工作區並清掉參數；否則 `GET room/current` 決定顯示首頁或工作區；接著 `GET rooms/live`。
2. 首頁：Create Room（`POST rooms/create` → 立即進入工作區並 `GET session`）或 Join（輸入 Room ID / 點 Live Rooms 的 join → `prompt()` 密碼 → `POST rooms/join` → `GET session`）。
3. 工作區：Upload .asci（`POST upload` → 依檔名解析為目標）→ 左側選目標 → widget 內編輯欄位（`change` 事件即 `POST target_state`）、mark done / mark discuss（互斥）、貼圖（`POST target_image`）、刪圖（`DELETE target_image`）、Light curve（`GET /api/object/<name>/photometry/plot`；Fetch → `POST /api/object/<name>/fetch_photometry`）、NED（`GET /api/search_target` 解析座標 → `GET /api/ned/cone` → Set/Unset Host → `POST /api/ned/set_host|unset_host` + `POST target_state`）。
4. 協作：Members（`GET room/members`；creator/admin 可 kick → `POST room/kick`）、Invite（複製邀請連結）、Auto（每 10 秒 `GET session`，不刷新 widget）、Refresh。被踢者下一次呼叫收到 403 並被踢回首頁（`loadSession` 只處理 401 → 顯示首頁；403 時 `applySessionData` 不會執行，狀態文字顯示「Please upload .asci files.」）。
5. 收尾：Preview → jsPDF 產生報告（摘要表 + 每目標一頁圖片，圖片經 `GET image/<filename>` 轉 dataURL）於新分頁開啟；Clear（三次 confirm → `DELETE clear`）；Remove 目標（三次 confirm → `DELETE target`）；Leave（`POST room/leave` → 回首頁）。房間 24 小時無人更新即被自動刪除（含檔案）。

### Documents 流程

- `GET /documents` → 清單 → 點文件 → `GET /documents/<filename>` → JS `GET /api/documents/<filename>/content` 渲染。admin：Create Document（`POST /api/documents/create` → 導向新文件頁）；Edit Document → 編輯器 → 貼圖 `POST /api/documents/upload-image` → Save Changes `PUT .../content` → 重新載入；Cancel 回檢視。Pin / 拖曳排序 → `POST /api/documents/metadata`。`documents_editable` 為假時前端按鈕 disabled，後端亦回 403。

### Lab Info 流程

- `GET /greatlab_info` → JS `GET /api/greatlab_links` → 渲染；GL/admin 可 Edit Layout → 修改 → Save Layout `POST /api/greatlab_links {data}` → 成功即退出編輯；Cancel 還原 `originalData`。

### 頁面群組權限流程

- admin 於 admin 頁（`admin.js`）`GET/POST/DELETE /api/admin/private_area/page_perms` 維護 `auth.system_settings` 的 `page_perm:<page>`；被加入群組的非 GREAT_Lab 使用者即可通過 `can_access_page()` 進入對應頁面（但看不到 navbar 的 Private 選單，且 ePessto++/targets 等 API 仍會 403）。

## 依賴的模組、資料表、檔案與外部服務

### Python 模組

| 模組 | 使用的函式 |
|---|---|
| `modules.database.auth` | `get_users()`、`user_exists(email)`、`get_groups()`、`get_page_groups(page_key)`、`set_page_groups(page_key, group_names)`（後兩者透過 `get_setting/set_setting` 存取 `auth.system_settings`） |
| `modules.database.obs` | `get_observation_targets(active_only)`、`save_observation_target(...)`、`update_observation_target(target_id, **kwargs)`、`update_observation_target_status(target_id, active)`、`delete_observation_target(target_id)`、`get_observation_log_months()`、`get_observation_logs(year, month)`、`upsert_observation_log(target_name, date, user, is_triggered, is_observed, trigger_filter, trigger_exp, trigger_count, observed_filter, observed_exp, observed_count, priority=, telescope_use=, repeat_count=, program=)`、`delete_observation_log(target_name, obs_date, telescope)` |
| `modules.database.transient` | `search_tns_objects(search_term, limit, sort_by, sort_order)` |
| `modules.database` | `get_db_connection()`（`/debug/database`） |
| `modules.trigger_send` | `get_send_status()`、`mark_sent(telescope, sent_by, program)`、`send_to_slack(greeting, script_body, image_path)`、`_trigger_day_key()` |
| `modules.trigger_script` | `exposure_time(mag)`（日誌記錄用）；`generate_full_script` 由 `astronomy_tools_bp` 呼叫 |
| `modules.observation_script` | `exposure_time(mag)`（`/api/auto_exposure`） |
| `modules.obsplan` | `create_ephem_target`、`create_ephem_observer`、`dt_naive_to_dt_aware`、`plot_night_observing_tracks` |
| `modules.phot_scheduler` | `update_target_mags()` |
| `modules.request_validation` | `get_int_arg`、`ParamOutOfRangeError`（`get_float_arg` 有匯入未使用） |
| `modules.config` | `config.DEBUG` |
| 第三方 | `werkzeug.security`（房間密碼雜湊）、`werkzeug.utils.secure_filename`、`ephem`、`slack_sdk`、`requests`、`pytz`、`matplotlib`（經 obsplan） |

### 資料表

| 資料表 | 讀 / 寫 | 使用處 |
|---|---|---|
| `obs.targets` | 讀寫 | `/api/targets*`、`_log_triggered_targets`（反查 target_id）、`update_target_mags` |
| `obs.logs` | 讀寫 | `/api/observation_logs*`、`send_message` |
| `auth.users` | 讀 | `/api/members`、`/private/*`（`get_users`）、`create_by`/`trigger_by` 反查 |
| `auth.usr_group`、`auth.groups` | 讀 | `get_users`、`get_groups`、`/private/*` 群組檢查 |
| `auth.system_settings` | 讀寫 | `page_perm:<page>`（page_perms API 與 `can_access_page`） |
| `transient.objects` | 讀 | `/api/search_target`、`/debug/database`、`update_target_mags` |
| TNS photometry（`get_tns_db_connection`） | 讀 | `update_target_mags` |

### 檔案與目錄

| 路徑 | 用途 |
|---|---|
| `app/routes/private_area/data/epessto_sessions.json` | 房間狀態（讀寫） |
| `app/routes/private_area/data/epessto_uploads/rooms/<ROOM_ID>/files/`、`.../images/` | `.asci` 與目標圖片（讀寫、刪除、`rmtree`） |
| `app/routes/private_area/data/epessto_uploads/*.asci`、`images/` | 舊版單房間遺留檔，現行程式不讀 |
| `app/routes/private_area/tutorials/*.md`、`images/`、`metadata.json`、`.env` | 文件、貼圖、置頂排序、`{{hide=KEY}}` 與設定 |
| `app/data/greatlab_links.json` | Lab Info 版面 |
| `app/data/trigger_send_status.json` | 每日送出狀態 `{day, SLT:{sent_by,sent_at}|null, 'LOT:<P>':{...}}` |
| 系統暫存目錄 | `send_message` 的可見度 `.jpg` 與 `trigger_script.txt`（用後即刪） |
| `kinder.env`（repo 根） | `SLACK_BOT_TOKEN`、`SLACK_CHANNEL_ID_CONTROL_ROOM`、`SLACK_CHANNEL_ID_test`、`DEBUG` |

### 外部服務

- Slack Web API（`chat.postMessage`、`files.getUploadURLExternal`、`files.completeUploadExternal` 與上傳 URL 的 HTTP POST）。
- 前端 CDN：Plotly 2.35.2、jsPDF 2.5.1、marked.js（無版本鎖定、無 SRI）、Aladin Lite v3 + jQuery 3.6.0（在 `srcdoc` iframe 內）。
- iframe：Google Calendar embed、meteoblue 氣象 widget；Google Drive 資料夾連結。

## 前端檔案

### 模板（`app/routes/private_area/templates/`）

`daily_trigger.html`（932 行）、`epessto_support.html`（275 行）、`documents.html`（275 行）、`document_view.html`（314 行）、`greatlab_info.html`（588 行，內嵌全部 JS）。共用 include：`_navbar.html`、`_favicon.html`（位於 `app/routes/basic/templates/`）。

### CSS（`app/routes/private_area/static/css/`）

`private_area.css`（2177 行；四個頁面皆載入，含 Daily Trigger 的 `.pa-trigger-*`、`.dt-*`、`.pa-sent-chip` 等樣式）、`epessto_support.css`（933 行；僅 ePessto 頁載入）、`daily_trigger.css`（1227 行；**沒有任何模板引用**，為舊版樣式副本）。另有 `static/photo/background_private.jpg`。

### JS 與其呼叫的 API

`daily_trigger.js`（3275 行；所有 fetch 經 `_apiFetch` 加上 `X-API-Key` 標頭，數值經 `_apiStringify` 截到 4 位小數）：

| API | 方法 | 用途 |
|---|---|---|
| `/api/targets` | GET / POST | 載入目標 / 新增 |
| `/api/targets/<id>` | PUT / DELETE | 編輯 / 刪除 |
| `/api/targets/<id>/toggle` | PUT | active 開關（表格與 Visibility modal） |
| `/api/targets/update-mags` | POST | Update Mag |
| `/api/search_target?q=` | GET | 名稱自動完成 |
| `/api/auto_exposure?mag=&telescope=` | GET | Auto Exposure |
| `/api/visibility_data` | POST（astronomy_tools） | 表格天文資訊、Visibility modal |
| `/api/observation_log_months` | GET | 年月選單 |
| `/api/observation_logs?year=&month=` | GET | 日誌表 |
| `/api/observation_logs` | POST | 儲存 / `action:'delete'` |
| `/api/members` | GET | 成員頭像與 Log modal 下拉 |
| `/astronomy_tools/generate_trigger_script` | POST（astronomy_tools） | 產生腳本（整批與單一目標） |
| `/generate_plot` | POST（astronomy_tools） | 靜態可見度圖預覽 |
| `/daily_trigger/send_status` | GET | 送出狀態 chips |
| `/daily_trigger/send_message` | POST | 送 Slack（整批 `mark_sent` 預設 true；單一目標 `false`） |
| `/object/<name>` | 連結 | 目標名稱 |

`epessto_support.js`（2001 行）：

| API | 方法 | 用途 |
|---|---|---|
| `/api/epessto_support/rooms/live` | GET | Live Rooms |
| `/api/epessto_support/rooms/create` | POST | 建房 |
| `/api/epessto_support/rooms/join` | POST | 密碼加入 |
| `/api/epessto_support/rooms/join_by_invite` | POST | 邀請連結加入 |
| `/api/epessto_support/room/current` | GET | 還原目前房間 |
| `/api/epessto_support/room/leave` | POST | 離開 |
| `/api/epessto_support/room/members` | GET | 成員列表 |
| `/api/epessto_support/room/kick` | POST | 踢人 |
| `/api/epessto_support/upload` | POST | 上傳 `.asci` |
| `/api/epessto_support/session` | GET | 載入/自動刷新 |
| `/api/epessto_support/target_state` | POST | 欄位、done/discuss、NED host 回寫（亦會送 `reporting_group`，後端忽略） |
| `/api/epessto_support/target` | DELETE | 移除目標 |
| `/api/epessto_support/target_image` | POST / DELETE | 貼圖 / 刪圖 |
| `/api/epessto_support/image/<filename>` | GET | 顯示與 PDF 內嵌 |
| `/api/epessto_support/clear` | DELETE | 清空 |
| `/api/search_target?q=` | GET | 解析 API 名稱、reporting group、NED 座標 |
| `/api/classifications` | GET（web_api） | Type 選單 |
| `/api/object/<name>/photometry/plot?extinction=&k_corr=` | GET（objects_bp） | 光變曲線 |
| `/api/object/<name>/fetch_photometry` | POST（web_api） | 抓 TNS 測光 |
| `/api/ned/cone?ra=&dec=&radius_arcsec=&object_name=&force=` | GET（objects_bp） | NED 錐搜尋 |
| `/api/ned/set_host`、`/api/ned/unset_host` | POST（objects_bp） | 設定/取消主星系 |
| `/object/<name>` | 連結 | 目標標題 |

`documents.js`（146 行）：`POST /api/documents/create`、`POST /api/documents/metadata`。
`document_view.js`（185 行）：`GET/PUT /api/documents/<filename>/content`、`POST /api/documents/upload-image`。
`greatlab_info.html` 內嵌 JS：`GET/POST /api/greatlab_links`。

## 已知問題與注意事項

### 壞掉或死掉的 route / 程式碼

1. `/private/calendar`、`/private/telescope`、`/private/projects`、`/private/resources` 渲染的 `private_calendar.html` 等四個模板在整個專案中不存在；有權限者會遇到 `TemplateNotFound`（500）。無任何連結指向它們，屬殘留死碼；`private_calendar` 內的 `user_email`、`is_great_lab` 變數也未使用。
2. `api_members` 的條件 `if u.get('role') in [...] or True` 永遠為真（死條件）。
3. `daily_trigger` 傳給模板的 `all_groups` 未被模板使用（額外查一次 `get_groups()`）。
4. 已註解的 `/api/debug-object-tag/<object_name>` 路由；檔頭 docstring 仍寫 "Calendar routes"；`urllib.parse`、`get_float_arg`、`Response` 匯入未使用；`read_documents_env()` 內的區域變數 `config` 遮蔽了模組層的 `modules.config.config`（僅區域，無實害）。
5. `static/css/daily_trigger.css` 未被任何模板引用（Daily Trigger 樣式實際在 `private_area.css`）。
6. `epessto_support.js` 內 `generateReportPdf(false)`（下載）、`buildSummaryText`、`buildReportMarkdown`、`downloadBlob` 皆未被呼叫（只有 Preview 按鈕）。
7. `document_view.js`：`editing` 變數未宣告即賦值（隱式全域，strict mode 下會拋錯）；`editToggle` 取 `#documentsEditableToggle` 元素但模板沒有；`editable` 變數無用。
8. `/api/documents/settings` 沒有任何前端呼叫者；`important_message` 雖傳入 `documents.html` / `document_view.html`，兩個模板都沒有渲染它。

### 權限與安全

9. `POST /api/documents/metadata` 的檢查是 `if not is_admin_user() and not documents_editable()`：只要 `DOCUMENTS_EDITABLE` 為 true（預設值，且目前 `.env` 沒有此 key），**未登入者也能改寫置頂/排序**。
10. `GET /tutorials/images/<path>` 完全公開（僅擋 `..` 與開頭 `/`），私人文件的貼圖任何人知道檔名即可存取。
11. `GET /api/documents/<filename>/content` 會把 `{{hide=KEY}}` 代換成 `tutorials/.env` 的真實值（該檔含 `SLACK_BOT_TOKEN`、Lab 網路帳密等）；任何可看 Documents 的人都能取得被引用的秘密，且 `raw_content` 也一併回傳。
12. 兩套權限模型並存：頁面用 `can_access_page()`（admin / GREAT_Lab / 額外群組），但 ePessto++ 全部 API、`/api/targets` 的寫入、`update-mags`、`/api/greatlab_links` POST 只認 `is_great_lab_member/is_admin`。透過 page_perms 額外群組獲准的人：能開 `/epessto_support` 但每個 API 都 403；能開 `/daily_trigger` 但無法新增/編輯目標（send_message 反而允許）。navbar/home 也只在 `is_great_lab_member` 時顯示 Private 選單，這些人沒有入口。`/private/telescope|projects|resources` 又改用 DB 群組硬查 `'GREAT_Lab'`，admin 若不在該群組也被拒。
13. 任何已登入者（含 guest 角色）都能：`GET /api/targets`（含 Note、Program）、`GET /api/members`（全站使用者 email/姓名/頭像）、`POST /api/observation_logs`（新增/刪除 `obs.logs`）、`GET /api/observation_logs`、`GET /api/greatlab_links`、`GET /api/search_target`、`GET /api/auto_exposure`。
14. `daily_trigger.html` 把使用者的 `api_key` 寫進 `<meta name="x-api-key">`，JS 對所有請求附 `X-API-Key`；本 blueprint 沒有任何端點讀取此標頭（皆以 session 判斷），只是把金鑰暴露在頁面原始碼中。
15. `POST /api/greatlab_links` 不驗證 `data` 結構，前端以 `innerHTML` 插入 `title/url/desc`（同一群組內的 stored XSS 風險）。

### 邏輯與資料一致性

16. `write_documents_env()` 只寫出 `DOCUMENTS_EDITABLE` 與 `IMPORTANT_MESSAGE` 兩行，會把 `tutorials/.env` 原有的 `glab_internet_acc`、`glab_internet_pwd`、`SLACK_BOT_TOKEN`、`SLACK_CHANNEL_ID_*` 全部抹掉；只要 admin 呼叫一次 `POST /api/documents/settings`，所有 `{{hide=KEY}}` 都會變成 `[KEY NOT FOUND IN ENV]`。
17. 全域 `_block_pipe_in_api_params` 讓 `PUT /api/documents/<f>/content` 無法儲存含 Markdown 表格（`|`）的文件（400 `Invalid character '|' is not allowed`）；同樣影響 `POST /api/documents/create`、`/api/greatlab_links`、`/api/epessto_support/target_state`、page_perms 群組名等所有 `/api/` JSON。
18. Observation Log 手動儲存：`saveObservationLog()` 把 Program 併入 priority 成 `"High - R01"` 送出，後端 `upsert_observation_log` 只做 title-case 正規化；依 `_Kinder_Database/SQL/observation.sql`，`obs.logs.priority` 有 `CHECK (priority IN ('Urgent','High','Normal','Filler'))`，填了 Program 就會插入失敗 → 500 `Failed to save log`。後端 POST 也完全忽略 `program` 欄位（只有 `send_message` 走的 `_log_triggered_targets` 會寫 `program`）。前端 `openLogModalEdit` 仍保留解析 `"Priority - Program"` 舊格式的相容碼。
19. `delete_observation_log` 先用 `obs.targets` 反查 `target_id`，所以「目標已刪除」的孤兒日誌（表格中的 Orphan/Discontinued 列）無法從 UI 刪除（404）。
20. `POST /api/targets` 底層是 `INSERT ... ON CONFLICT (name, telescope) DO UPDATE`：用「新增」建立同名同望遠鏡的目標會直接覆蓋既有列（含 filters/priority/notes）並回傳既有 id，前端不會提示。`PUT` 允許改 `telescope`，若與另一列衝突 → 500 `Database error`。刪除目標時 `obs.logs.target_id` 設 NULL，日誌保留但變孤兒。
21. `send_message` 中望遠鏡與可見度圖的 Lulin 座標寫死兩處且不一致：後端 `'120:52:21.5','23:28:10.0',2800`，前端 `'120:52:21 23:28:10 2862'`（海拔 2800 vs 2862）。
22. 兩份相同的曝光表：`trigger_script.exposure_time`（日誌）與 `observation_script.exposure_time`（`/api/auto_exposure`），「太暗」訊息文字不同；修改其一容易漏掉另一份。`/api/auto_exposure` 的 `telescope` 參數不影響結果，且查表失敗時以 HTTP 200 回 `{error}`。
23. `/api/search_target` 吞掉所有例外並回 200 `{results:[]}`，DB 故障時前端只看到「No results」。
24. `daily_trigger_send_status` 每次輪詢都以 INFO 記錄完整狀態，會製造 log 噪音。
25. ePessto++：`rooms/join`（密碼）不檢查 `kicked_users`，被踢者可成功「加入」，但下一個請求就被 `_get_epessto_room_or_response` 判為被踢（403）並清 session；用邀請連結則會自動解除踢除（設計如此，但形同踢人無效）。`room/leave` 不移除成員紀錄。
26. ePessto++ 前端會送 `reporting_group` 到 `target_state`，後端白名單不含此欄位，使用者手動輸入的 Reporting Group 永遠不會被保存（重新載入即消失）。
27. `_serialize_from_filenames()` 會就地修剪 `target_state`，但在 `GET /session` 中修剪結果並未寫回 JSON（store 在呼叫前已儲存）；無實害，只是每次都重算。
28. 房間自動清理是「被動」的（只在有人呼叫 ePessto API 時執行）；上傳同名 `.asci` 會覆蓋磁碟檔但新增一個 batch 紀錄；`_load_epessto_store` 產生的 `legacy` 房間無法加入（`password_hash=''`），其檔案路徑 `rooms/legacy/files` 也不存在，舊根層 `.asci` 檔實際上已成孤兒。
29. `epessto_support.js` 的 `loadSession` 只處理 401；被踢的 403 不會把 UI 切回首頁，僅顯示「Please upload .asci files.」。
30. `_navbar.html` 的 active 判斷清單 `['/detect_results','/private','/documents','/epessto_support']` 不含 `/daily_trigger`、`/greatlab_info`；且該 `<a>` 有兩個 `class` 屬性（第二個被瀏覽器忽略），Private 選單實際上永遠不會標示 active。
31. `page_perms` POST 不驗證 `group_name` 是否為既有群組，可寫入任意字串。
32. `send_message` 的 `targets` 若缺 `name` 只會被略過（不報錯）；若 Slack 成功但 `mark_sent`/`obs.logs` 失敗，前端顯示成功並附 `log_warnings`，狀態檔仍可能未更新（`mark_sent` 例外會直接 500，但此時 Slack 訊息已送出，重送會重複）。
