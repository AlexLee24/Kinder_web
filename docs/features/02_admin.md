# 管理後台：Admin Panel、Web Log、DB Status（`admin` / `web_log` / `database_status` blueprints）

> **注意**：本章記錄的是重構前（commit `c7f91a4`，2026-09-21）的狀態，檔案路徑為舊位置（`app/routes/…`、`app/modules/…`）。新位置請對照 `docs/ARCHITECTURE.md` §6「新舊路徑對照」；功能與行為在重構後完全相同。

## 概要

本章涵蓋三個 blueprint，全部位於 `app/routes/auth/` 底下，於 `app/routes/__init__.py::register_routes()` 中依序註冊（`admin_bp` 第 2 個、`web_log_bp` 第 11 個、`database_status_bp` 第 12 個），皆**沒有 `url_prefix`**：

| Blueprint | 檔案 | 主要頁面 | 用途 |
|---|---|---|---|
| `admin` | `app/routes/auth/admin_routes.py`（1005 行） | `/admin` | 使用者 / 群組 / API key / 群組申請 / 系統設定 / 資料來源預設權限 / 備份 / 光度抓取 / TNS 手動下載 / DETECT 手動執行 / 排程狀態 |
| `web_log` | `app/routes/auth/web_log_routes.py`（294 行） | `/admin/log` | 瀏覽 `app/log/YYYY-MM-DD.log` 的即時 log viewer |
| `database_status` | `app/routes/auth/database_status_routes.py`（322 行） | `/admin/database` | 讀取 `pg_stat_activity`、取消 / 終止 PostgreSQL 連線 |

三個頁面共用一條「Admin Hub」導覽列（`/admin` ↔ `/admin/database` ↔ `/admin/log`），並由全站 `_navbar.html`（`app/routes/basic/templates/_navbar.html` 第 114–132 行）在 `session.user.is_admin` 為真時提供「Manage」下拉選單連到這三頁；`home.html` 第 34 行也在 `is_admin` 時提供 `url_for('admin.admin_panel')`。

權限判斷全部直接讀 Flask `session['user']`（由 `auth_routes.py` 登入時寫入：`is_admin` = `auth.users.roles >= 50`、`role` = `admin`/`user`/`guest`、`is_great_lab_member` = 屬於 `GREAT_Lab` 群組或 `is_admin`）。沒有 decorator，每個 view 開頭各自檢查。

與其他區塊的關係：
- Admin Panel 的「Access Control」分頁直接呼叫 **private_area blueprint** 的 `/api/admin/private_area/page_perms`（GET/POST/DELETE，`app/routes/private_area/private_area_routes.py` 第 579–616 行）。
- DETECT 手動執行後呼叫 `routes.detect.detect_routes._soft_invalidate_page_cache()` 讓 `/detect` 頁面快取失效。
- TNS 手動任務重用背景 daemon 的模組函式（`modules/auto_tns_download.py`），並與該 daemon 共用工作目錄 `app/data/tns_api_download_work/`。
- 排程狀態面板讀取 `main.py` 建立的 APScheduler（透過 `modules/scheduler_state.scheduler`）與 `modules/job_status`（檔案 `app/log/.job_status.json`）。
- 全域 `before_request`（`main.py`）：`_enforce_allowed_host`（Host 不符 → 404）、`refresh_user_session`、`_block_pipe_in_api_params`（路徑以 `/api/` 開頭且任一參數含 `|` → 400 JSON）。後者適用於 `/api/log/*` 與 `/api/admin/database/*`，**不**適用於 `/admin/*`。
- `main.py` 第 168 行 `_ACCESS_SKIP_PREFIXES = ('/static/', '/api/log/content', '/api/log/daemon/content')`：存取記錄（logger `web.request`，需 `ACCESS_LOG_ENABLED=1`）刻意略過 log viewer 的輪詢請求，避免自我灌 log。

---

## 頁面（HTML routes）

### `/admin` — Admin Panel

| 項目 | 內容 |
|---|---|
| 路徑 / 方法 | `GET /admin` |
| endpoint | `admin.admin_panel` |
| 權限 | **僅 admin**（`session['user']['is_admin']`）。未通過：`flash('Access denied. Administrator privileges required.', 'error')` 後 `redirect(url_for('basic.home'))` |
| 模板 | `app/routes/auth/templates/admin.html`（747 行） |
| 模板變數 | `current_path='/admin'`、`users`（`get_users()`，`{email: user_dict}`）、`groups`（`get_groups()`，`{name: group_dict}`，含 `members` list）、`invitations`（`get_invitations()`，**模板未使用**）、`group_requests`（`get_group_requests('pending')`，見已知問題）、`api_key_requests`（`get_api_key_requests()`）、`current_user_email`（**模板未使用**，模板改用 `session.user.email`）、`open_registration`（`get_setting('open_registration','true') == 'true'`） |
| 讀取資料表 | `auth.users`、`auth.usr_group`、`auth.groups`、`auth.invitations`、`auth.system_settings` |
| 靜態資源 | `/static/css/admin.css`（實體 `app/routes/auth/static/css/admin.css`）、`/static/js/admin.js`；`{% include '_navbar.html' %}`、`{% include '_favicon.html' %}`（來自 basic blueprint） |

頁面載入時前端自動觸發（`admin.js` 的 `DOMContentLoaded` + 模板內嵌 script 的另一個 `DOMContentLoaded`）：
1. `loadUsersData()`：把使用者表格列讀進記憶體供搜尋。
2. 1 秒後 `checkDataConsistency()` → `GET /admin/check-consistency`。
3. `loadPrivatePagePerms()` → `GET /api/admin/private_area/page_perms`。
4. `loadDefaultSourcePermissions()` → `GET /admin/default-source-permissions` + `GET /admin/sources/all`。
5. `showTab(sessionStorage.adminActiveTab || 'overview')`；當分頁是 `overview` 時 `_startJobsPolling()`：立即並每 15 秒 `GET /admin/scheduled-jobs-status` + `GET /admin/detect-status`，切到其他分頁即停止。

版面：左側 sidebar 5 個分頁按鈕（`showTab()`，狀態存於 `sessionStorage['adminActiveTab']`）；右側 `main`。

**分頁 1：Overview（`#overview-tab`）**

| 區塊 | 元件 | 呼叫 / 導向 |
|---|---|---|
| 標題列 | `#consistencyStatus`、`#backupStatus` 狀態字 | 由 consistency / backup 動作更新 |
| Stats | Total Users / Administrators（`users.values() | selectattr('is_admin')`）/ Groups / Pending Requests（`group_requests|length`） | 純模板 |
| Database Health | 按鈕 **Check Consistency** → `checkDataConsistency()`；**Backup Now** → `triggerManualBackup()` | `GET /admin/check-consistency`；`POST /admin/backup-now` |
| Database Sessions | 連結 **Open DB Status** | `/admin/database` |
| System Log | 連結 **Open Web Log** | `/admin/log` |
| Registration Policy | checkbox **Open Registration** → `toggleOpenRegistration(this)` | `POST /admin/settings/save` `{key:'open_registration', value:<bool>}`；失敗時還原 checkbox |
| DETECT Pipeline | `#detectEnabledBadge`（ENABLED / CODE MISSING / DISABLED）、`#detectStatusGrid` 7 張卡（Now / Last run (this server) / Latest screening in DB / Last 24 h / Waiting for a person（含連結 `/detect`）/ Other writers / Code & data）、按鈕 **Re-screen Follow-ups**（`runDetect('followups')`）、**Run on recent (2 h)**（`runDetect('recent')`，`hours` 固定 2）、輸入框 `#detectRunNames` + **Run on objects**（`runDetect('names')`）、`#detectRunStatus` | `GET /admin/detect-status`（15 秒輪詢；執行中每 3 秒 `_detectPoll()`）；`POST /admin/detect-run` |
| Scheduled Jobs | `#scheduledJobsGrid`，每個 job 一張卡：名稱、排程描述、Running / Wait for next run at … / Not scheduled、Last run ✓/✗ | `GET /admin/scheduled-jobs-status`（15 秒輪詢） |

**分頁 2：Users（`#users-tab`）**

| 區塊 | 元件 | 呼叫 |
|---|---|---|
| 標題列 | **Add User** → `showAddUserModal()` | 開 `#addUserModal` |
| Toolbar | `#userSearch`（keyup `searchUsers()`）、`#adminFilter` Admins only、`#groupFilter`（選項為 `groups.keys()`）、**Clear**（`clearSearch()`）、`#searchResults` | 純前端過濾（隱藏 `<tr>`） |
| API key 申請 banner（僅 `api_key_requests` 非空） | 每列：`req.name <req.email>`、「Reset request / New key request」（`req.has_key`）、`req.api_key_requested_at[:16]`、**Assign Key** → `adminIssueApiKey(email, btn)`、**Dismiss** → `adminDismissApiKeyRequest(email, btn)` | `POST /admin/api-key/issue`；**Dismiss 也是 `POST /admin/api-key/revoke`**（見已知問題） |
| 使用者表格 | 欄：User（avatar `user.picture`，`onerror` 換 `/static/img/default-avatar.png`）/ Role pill（`user.role`）/ Groups badges / Joined（`user.invited_at or user.last_login` 取前 10 字）/ API Key（Requested / Active / None + **Assign|Reset** → `adminIssueApiKey`、**Revoke**（僅 `has_api_key`）→ `adminRevokeApiKey`）/ Actions（`<select class="role-select">` guest/user/admin，`onchange` → `changeUserRole(email, value)`）。自己那列顯示「You」且無 API key 與角色控制 | `POST /admin/api-key/issue`、`POST /admin/api-key/revoke`、`POST /admin/update-role` |

**分頁 3：Groups（`#groups-tab`）**

| 區塊 | 元件 | 呼叫 |
|---|---|---|
| 標題列 | **New Group** → `showCreateGroupModal()` | 開 `#createGroupModal` |
| 加入申請 banner（僅 `group_requests` 非空） | 每列 `req.user_email` → `req.group_name`、`req.created_at`、**Approve** / **Reject**（`data-rid="{{ req.id }}"` → `handleGroupRequest(+rid, action)`） | `POST /admin/group-requests/<rid>/approve|reject`（整條流程目前是壞的，見已知問題） |
| 群組卡片（每個 group） | 標題點擊 `toggleGroupDetails(name, idx)` 展開；刪除 icon → `deleteGroup(name)`；展開後：Members (n)、**+ Add** → `showAddMembersModal(name)`、成員列（avatar / name / email）+ 移除 icon → `removeFromGroup(email, name)` | `POST /admin/delete-group`；`GET /admin/available-users/<name>`；`POST /admin/remove-from-group` |

**分頁 4：Access Control（`#access-tab`）**

| 區塊 | 元件 | 呼叫 |
|---|---|---|
| Private Area — Per-Page Access | `#privatePagePermsTable`，由 `loadPrivatePagePerms()` 依 `pages`（`daily_trigger`、`greatlab_info`、`epessto_support`、`documents`）產生卡片：鎖定的 `GREAT_Lab` 標籤 + 已授權群組標籤（× → `removePrivatePagePerm(page, g)`）+ `<select id="pperm_select_{page}">`（`ADMIN_GROUPS` 去掉 `GREAT_Lab`）+ **Add** → `addPrivatePagePerm(page)` | `GET / POST / DELETE /api/admin/private_area/page_perms`（private_area blueprint，僅 admin，JSON `{page, group_name}`） |
| Default Source Permissions | `#sourceAddSelect`（`_allSourcesList` 扣掉已存在者；`onchange` → `addDefaultPermFromSelect`）、**Save All** → `saveDefaultSourcePermissions()`、表格 `#defaultPermsTable`（Source / Visibility select：Public、All logged-in、Specific groups、Blocked → `onDefaultPermVisChange` / Allowed Groups 標籤 + `+ group` select（`addDefaultPermGroup` / `removeDefaultPermGroup`）/ 移除列 `removeDefaultPermRow`）、`#defaultPermsSaveStatus` | 載入：`GET /admin/default-source-permissions`、`GET /admin/sources/all`；儲存：`POST /admin/default-source-permissions` `{permissions:[{source_name,is_public,allowed_groups,_vis?}]}` |

前端狀態編碼：`is_public=true` → Public；`is_public=false, allowed_groups=null` → All logged-in；`allowed_groups=[]` → Blocked；`allowed_groups=[names]` → Specific groups。`_vis` 只是前端暫存（切到 groups 但尚未加群組時避免被判成 Blocked），後端忽略。

**分頁 5：Operations（`#operations-tab`）**

| 面板 | 按鈕 / 元件 | 呼叫 |
|---|---|---|
| Inbox Photometry Fetch（文案：daily 09:00 UTC+8） | **Run Now** `#runPhotFetchBtn` → `runPhotometryFetch()`；`#photFetchStatus` | `POST /admin/run-photometry-fetch`；成功後每 3 秒 `GET /admin/photometry-fetch-status` 直到 `running=false`，顯示 `total/success/failed` |
| Missing Photometry Check（文案：hourly） | **Run Now** `#runMissingPhotBtn` → `runMissingPhotFetch()` | `POST /admin/run-missing-phot-fetch`（無狀態輪詢） |
| Update Target Magnitudes（文案：daily 05:00） | **Run Now** `#runTargetMagBtn` → `runUpdateTargetMags()` | `POST /admin/run-update-target-mags`（無狀態輪詢） |
| TNS Manual Operations | **Download Hourly** → `runTnsHourly()`；**Download Daily** + `<input type=date id=tnsDailyDate>` → `runTnsDaily()`；**Auto-Snooze** → `runTnsSnooze()`；`#tnsTaskStatus` | `POST /admin/tns-download-hourly`、`POST /admin/tns-download-daily` `{date?}`、`POST /admin/tns-auto-snooze`；成功後每 3 秒 `GET /admin/tns-task-status` 直到 `running=false`，三顆按鈕期間全部 disabled |
| Document Images | **Clean Unused Images** → `cleanDocumentImages()`（有 `confirm`） | `POST /admin/documents/clean-images` |
| Database Maintenance | **Check Consistency**、**Backup Now**（與 Overview 相同函式） | 同上 |

**Modal（模板內實際存在的）**

| id | 內容 | 送出 |
|---|---|---|
| `#consistencyModal` | `#consistencyResults`（由 `showConsistencyResults(issues)` 填入）、**Cancel**、**Clean Issues** → `cleanDataConsistency()` | `POST /admin/clean-consistency` → 成功後 1.5 秒 reload |
| `#addUserModal` | form：`#userEmail`（required，type=email）、`#userName`（可空，前端預設 email 前綴）、`#userRole`（guest/user/admin，預設 user）→ `addUser(event)` | `POST /admin/add-user` → 成功後 reload |
| `#createGroupModal` | form：`#groupName`（required）、`#groupDescription` → `createGroup(event)` | `POST /admin/create-group` → 成功後 reload |
| `#addMembersModal` | `#selectedGroupName`、`#memberSearch`（`filterAvailableUsers()`）、`#availableUsersContainer`（checkbox 列表）、**Add Selected** → `addSelectedMembers()` | `POST /admin/add-multiple-to-group` → 成功後 reload |

`closeModal(id)` 隱藏並 `form.reset()`；`window.onclick` 點擊遮罩關閉。通知：`admin.js::showNotification(msg,type)`（`.notification` 元素，3 秒）與內嵌 `showAdminNotification()`（右下角 fixed）。幾乎所有寫入動作成功後 `setTimeout(() => location.reload(), 800~1500)`。

### `/admin/log` — Web Log（System Log）

| 項目 | 內容 |
|---|---|
| 路徑 / 方法 | `GET /admin/log` |
| endpoint | `web_log.log_viewer` |
| 權限 | **GREAT_Lab 成員或 admin**（`_can_view()`：`session['user'].is_great_lab_member or is_admin`）。未通過：`redirect(url_for('basic.home'))`，**無 flash** |
| 模板 | `app/routes/auth/templates/log_viewer.html`（1125 行，CSS 與 JS 全部內嵌） |
| 模板變數 | `current_path='/admin/log'` |
| 靜態資源 | Google Fonts Inter、`/static/css/_navbar.css`（實體 `app/routes/basic/static/css/_navbar.css`）、背景 `/static/photo/background_planner.jpg`（實體 `app/routes/planners/static/photo/`） |

頁面區塊與互動（全部由內嵌 script 驅動，無外部 JS）：

| 區塊 | 元件 | 行為 / API |
|---|---|---|
| Admin Hub nav | 連結 `/admin`、`/admin/database`、`/admin/log`（active） | 導向 |
| 控制列 | `#liveDot`（輪詢中閃爍）；`#dateSelect`（`switchDate(v)`）；Sources 多選 `#sourceList` + **All** / **Clear**（`selectAllSources` / `clearAllSources`）+ `#sourceSummary`；Level 按鈕 **All / ⚠ Warn+ / 🔴 Error**（`setLevelFilter`，純 CSS class 隱藏）；搜尋框 `#searchInput`（`oninput` → `applySearchMask()`，Enter / Shift+Enter 上下一筆，Ctrl/Cmd+F 聚焦，Esc 清除）+ ↑ ↓ + `#searchStatus` + ✕；**Follow tail** checkbox；**▶ Start Reading / ■ Stop Reading**（`toggleLogStream`）；**↺ Refresh**（`manualRefresh`）；**⎘ Copy Errors**（`copyErrors`：把 `.line-error/.line-warning` 文字複製到剪貼簿）；**✕ Clear**（`clearDisplay`）；統計 `#statDate / #statLines / #statErrors（可點→errors_only）/ #statWarns（可點→warn_up）/ #statBytes` | — |
| Log panel | `#logFileName`、`#logWrap`（含 `#loadingOverlay` spinner）、`<pre id="logPre">` | `colorize()` 依 `WEB_LOG_RE`（`YYYY-MM-DD HH:MM:SS [source] LEVEL msg`）或 `DAEMON_LOG_RE` 上色；`colorizeStructured()` 高亮 `event= status= duration_ms= method= path= user=`；DOM 最多保留 600 行（`MAX_DISPLAY_LINES`） |

流程：`init()` → `GET /api/log/files` → 預設選今天（**UTC+8** 日期，`utc8DateString()`；若無則清單第一個）→ `loadSources(date)`（`GET /api/log/sources?date=`；首次預設勾選全部但**排除 `web.request`**）→ `loadFull(date)`（`GET /api/log/content?date=&offset=0&sources=<all|a,b>&tail_lines=300&max_bytes=524288`，`truncated` 時在頂端插入「Showing recent lines only」提示）→ 若日期為今天且 `streamEnabled` → `startPoll()`：每 1 秒 `GET /api/log/content?date=&offset=<logOffset>&sources=…&max_bytes=65536` 追加新內容；每 30 次輪詢重新 `loadSources()` 自動勾選新出現的 source。`visibilitychange` 隱藏時停止、回到前景重啟；`pagehide` / `beforeunload` 停止。變更日期或 source 選擇時重新 `loadFull`。`sources` 參數：全選或全不選時送 `all`（避免空 filter 問題），否則逗號串接。

### `/admin/database` — Database Status

| 項目 | 內容 |
|---|---|
| 路徑 / 方法 | `GET /admin/database` |
| endpoint | `database_status.database_status_page` |
| 權限 | **僅 admin**（`_is_admin_user()`）。未通過：`redirect(url_for('basic.home'))`，**無 flash** |
| 模板 | `app/routes/auth/templates/database_status.html`（927 行，CSS/JS 內嵌） |
| 模板變數 | `current_path='/admin/database'`、`config_name=DB_NAME`（固定字串 `"Kinder"`，`modules/database/__init__.py`） |
| 特性 | 頁面本身不碰資料庫；所有狀態由前端 API 取得，DB 掛掉時頁面仍可開啟 |

頁面區塊與互動：

| 區塊 | 元件 | 行為 / API |
|---|---|---|
| Hero | **Refresh** `#refreshBtn` → `refreshStatus()` | `GET /api/admin/database/status`；載入時立即呼叫，之後 `setInterval(refreshStatus(true), 5000)` |
| `#statusBanner` | Database is reachable / currently unavailable + error | 由 `setConnectionPill()` 更新 |
| 4 張卡 | Connection pill（Connected / Unavailable）+ `#serverLabel`（`host:port → server_addr:server_port`）；Total Sessions + `Checked: <time>`；Active / Idle + Idle in transaction；Waiting + `server_version` | `updateCards(data)` |
| `#actionBanner` | 動作結果訊息（Attempted / succeeded / failed / skipped） | `setActionBanner` |
| Pressure Guide | `#pressureScore`（0–100）、`#pressureLevel`（LOW <25 / MODERATE / HIGH ≥50 / CRITICAL ≥75）、`#pressureReasons` | **純前端** `analyzePressure()`：`min(20,total)+min(20,active*2)+min(30,blockingWait*10)+min(25,idleTx*12)+min(20,longActive*8)`；DB 不可用固定 100 |
| Recommended Actions | 表格 `#recommendBody`（PID / State / Age / Suggested / Reason / 單列按鈕 → `singleAction`）；**Cancel Recommended** / **Terminate Recommended** → `runRecommended(op)` | 前端規則：`idle in transaction` ≥300 s → terminate；`active` 且 wait_event_type ∈ {Lock, LWLock, LWLockNamed, BufferPin, IO, IPC} 且 ≥60 s → cancel；`active` ≥1800 s → cancel。送 `POST /api/admin/database/action` |
| Toolbar | **Cancel selected** / **Terminate selected**（`bulkAction`）；`#idleMinutes`（1–1440，預設 15）+ **Terminate idle**（`terminateIdle`）；`#selectionInfo`；**Select all** / **Clear** | `POST /api/admin/database/action` `{operation:'cancel'|'terminate', pids:[…]}` 或 `{operation:'terminate_idle', idle_minutes}`；皆有 `confirm()` |
| Sessions 表 | 每列：checkbox（`data-pid`，self 列 disabled）、PID（self 加 `self` 標籤）、User、App、Client（`client_addr:client_port`）、State、Age（`formatAge`）、Wait（`wait_event_type / wait_event`）、Query（前 500 字）、Actions（**Cancel** / **Terminate** → `singleAction`；self 列顯示 Protected (self)） | `renderSessions()`；`submitAction()` 送出前會在前端剔除 `current_pid` |

---

## API 與動作端點

所有 `admin.*` 端點權限相同：**僅 admin**；未通過一律 `403 {'error': 'Access denied'}`（`admin_panel` 例外，見上）。表格中省略此欄的重複說明。JSON 輸入皆以 `request.get_json()`（無 `silent` 者遇到非 JSON body 會由 Flask 回 400/415；標註 `silent` 者容忍空 body）。

### `admin` blueprint（`app/routes/auth/admin_routes.py`）

| 方法 | 路徑 | endpoint | 輸入 | 成功回應 | 失敗回應 | 副作用 |
|---|---|---|---|---|---|---|
| POST | `/admin/add-user` | `admin.add_user` | JSON `email`(必填, strip)、`role`(預設 `'user'`)、`name`(空則取 email `@` 前綴) | 既存：`{success, message:'User already existed, role updated.'}`；新建：`{success, message:'User added successfully'}` | 400 email 空；500 `save_user` 回 None | 既存 → `update_user(email, is_admin=(role=='admin'), role=role)`（`role` 被忽略）；新建 → `save_user(...)`（**目前必炸 TypeError → 500**，見已知問題） |
| GET | `/admin` | `admin.admin_panel` | — | 渲染 `admin.html` | flash + redirect `basic.home` | 讀 `auth.users/usr_group/groups/invitations/system_settings` |
| POST | `/admin/api-key/issue` | `admin.admin_issue_api_key` | JSON(silent) `email`(必填) | `{success, message:'API key issued for <email>'}`（**不回傳 key**） | 400 email 空；500 使用者不存在或 DB 失敗 | `generate_api_key_for_user`：`UPDATE auth.users SET api_key=<48 字英數>, api_key_requested_at=NULL` |
| POST | `/admin/api-key/revoke` | `admin.admin_revoke_api_key` | JSON(silent) `email` | `{success, message:'API key revoked for <email>'}` | 400；404 `revoke_api_key` 回 False | `UPDATE auth.users SET api_key=NULL, api_key_requested_at=NULL` |
| POST | `/admin/group-requests/<int:request_id>/<action>` | `admin.handle_group_request` | URL：`request_id` int、`action` 任意字串（僅 `approve` / `reject` 有效） | approve：`{success, message:'Request approved'}`；reject：`{success, message:'Request rejected'}` | 404 找不到；400 `Invalid action`；500 加入群組失敗 | 呼叫 `get_group_request(request_id)`、`add_user_to_group`、`update_group_request_status(request_id, 'approved'|'rejected')`（**函式簽名不符 → TypeError 500**，見已知問題） |
| POST | `/admin/settings/save` | `admin.save_settings` | JSON `key`(必填)、`value`(任意，`str()` 後存) | `{success:true}` | 400 key 空；500 | `set_setting` → `auth.system_settings` upsert |
| POST | `/admin/update-role` | `admin.update_user_role` | JSON `user_email`、`role` ∈ {guest,user,admin} | `{success, message:'Role updated to <role>'}` | 400 參數不合法 / 改自己；404 使用者不存在；500 | `update_user(email, role=…, is_admin=(role=='admin'))` → `auth.users.roles` = 50 或 1（`role` 參數被忽略） |
| POST | `/admin/toggle-admin` | `admin.toggle_admin_status` | JSON `user_email` | `{success, message:'User promoted to admin successfully'|'User removed from admin successfully'}` | 400 缺 email / 改自己 / 不存在；500 | `get_users()` 讀現況後 `update_user(is_admin=not current)`。**無前端呼叫者** |
| POST | `/admin/delete-user` | `admin.delete_user_route` | JSON `user_email` | `{success, message:'User deleted successfully'}` | 400 / 500 | `DELETE FROM auth.users`（`usr_group` ON DELETE CASCADE）。**無前端呼叫者** |
| POST | `/admin/create-group` | `admin.create_group_route` | JSON `name`(必填, strip)、`description` | `{success, message:'Group created successfully'}` | 400 name 空 / 已存在；500 | `create_group(name, desc, creator_email=session email)` → `INSERT auth.groups`（`joinable=True`，`create_by`=admin 的 `usr_id`） |
| POST | `/admin/delete-group` | `admin.delete_group_route` | JSON `group_name` | `{success, message:'Group deleted successfully'}` | 400 缺 / 不存在；500 | `DELETE FROM auth.groups`（成員關係 CASCADE） |
| POST | `/admin/add-to-group` | `admin.add_user_to_group_route` | JSON `user_email`、`group_name` | `{success, message:'User added to group successfully'}` | 400 缺參數 / 使用者或群組不存在 / 已在群組；500 | `INSERT ... ON CONFLICT DO UPDATE status='joined'` 於 `auth.usr_group`；若目標是目前登入者則 `update_user_session_groups()` 同步 `session['user']['groups']`。僅死 JS 呼叫 |
| POST | `/admin/remove-from-group` | `admin.remove_user_from_group_route` | JSON `user_email`、`group_name` | `{success, message:'User removed from group successfully'}` | 400；500 | `DELETE FROM auth.usr_group`；同步 session |
| GET | `/admin/user-groups/<user_email>` | `admin.get_user_groups` | URL `user_email` | `{success, user_groups:[…], available_groups:[…], all_groups:[…]}` | 400 使用者不存在 | 讀 users/groups。**無前端呼叫者**（僅死 JS） |
| POST | `/admin/batch-update-groups` | `admin.batch_update_groups` | JSON `user_email`、`groups:[names]`(預設 []) | `{success, message:'Groups updated successfully'}` | 400 | 差集比對後逐一 `remove_user_from_group` / `add_user_to_group`（不存在的群組名靜默略過）；同步 session。**無前端呼叫者** |
| GET | `/admin/available-users/<group_name>` | `admin.get_available_users` | URL `group_name` | `{success, available_users:[{email,name,picture}]}`（`picture` 預設 `/static/img/default-avatar.png`） | 400 群組不存在 | 讀 users/groups |
| POST | `/admin/add-multiple-to-group` | `admin.add_multiple_to_group` | JSON `group_name`、`user_emails:[…]` | `{success, message:'Successfully added N users to group[. M errors occurred.]', added_count, errors:[…]}` | 400 缺參數 / 群組不存在 / 一個都沒加成（`'No users were added. ' + errors`） | 逐一 `add_user_to_group`（不存在 / 已在群組者記入 `errors`）。**不**同步 session |
| GET | `/admin/check-consistency` | `admin.check_consistency` | — | `{success, issues:{status:'ok', issues:[]}, has_issues:false}` | — | `check_data_consistency()` 是 stub，永遠無問題 |
| POST | `/admin/clean-consistency` | `admin.clean_consistency` | — | `{success, message:'Cleaned 0 data consistency issues', cleaned_count:0}` | — | `clean_data_consistency()` 是 stub，永遠 0 |
| POST | `/admin/backup-now` | `admin.backup_now` | — | `{success, message:'Backup completed successfully'}` | 500 `{error:str(e)}`（例如 `pg_dump not found`） | **同步**執行 `modules.backup.run_daily_backup(force=True)`：`pg_dump -F p` 資料庫 `Kinder` → `app/data/backups/Kinder_backup_YYYYMMDD.sql`（覆蓋當日檔），timeout 300 s，之後只保留 15 份 |
| POST | `/admin/documents/clean-images` | `admin.clean_unused_images` | — | `{success, message:'Cleaned N unused image(s)', cleaned_count}` 或 `{success, message:'No images directory found', cleaned_count:0}` | 500 | 掃 `admin_bp.root_path/static/tutorials/*.md` 與 `images/`，刪除未被引用的圖檔。**路徑不存在，永遠 no-op**（見已知問題） |
| POST | `/admin/run-photometry-fetch` | `admin.run_photometry_fetch` | — | `{success, message:'Photometry fetch started in background'}` | 409 `{success:false, message:'Photometry fetch is already running'}` | 啟動 daemon thread 執行 `phot_scheduler.fetch_inbox_photometry()`（對所有 Inbox 物件抓光度，寫 `transient.photometry` 等） |
| GET | `/admin/photometry-fetch-status` | `admin.photometry_fetch_status` | — | `{running:bool, current, total, success, failed}` | — | 讀 `phot_scheduler._running/_progress`（**本 process 限定**） |
| POST | `/admin/run-missing-phot-fetch` | `admin.run_missing_phot_fetch` | — | `{success, message:'Missing photometry check started in background'}` | 409 `'Missing phot check is already running'` | thread 執行 `fetch_missing_photometry()`（只補零資料點的 Inbox 物件；若 daily fetch 進行中會自行 skip） |
| POST | `/admin/run-update-target-mags` | `admin.run_update_target_mags` | — | `{success, message:'Target magnitude update started in background'}` | — | thread 執行 `update_target_mags()`（更新 `observation_targets.mag`、同步 AT→SN prefix 到 `observation_targets` / `observation_logs`）。**無重複執行保護、無狀態端點** |
| GET | `/admin/default-source-permissions` | `admin.get_default_source_perms` | — | `{success, permissions:[{source_name, is_public, allowed_groups:null|[names]}]}` | — | 讀 `transient.default_permissions` + `auth.groups`（id→name） |
| POST | `/admin/default-source-permissions` | `admin.save_default_source_perms` | JSON(silent) `permissions:[{source_name(必填), is_public, allowed_groups:null|[]|[names]}]` | `{success:true}`（**不檢查 DB 是否成功**） | 400 `permissions` 非 list；缺 `source_name` → KeyError 500 | `set_default_source_permissions_batch`：**`DELETE FROM transient.default_permissions` 後全部重插**（`permissions_set` ∈ public/login/groups，`groups` INT[]；未知群組名被丟棄） |
| GET | `/admin/sources/search` | `admin.search_sources` | query `q`（空 → 空陣列） | `{success, sources:[…最多 20]}` | 例外也回 `{success:true, sources:[]}` | `SELECT DISTINCT source FROM transient.photometry WHERE source ILIKE %q%`。**無任何呼叫者** |
| GET | `/admin/sources/all` | `admin.all_sources` | — | `{success, sources:[…]}` | 例外也回 `{success:true, sources:[]}` | `transient.photometry ∪ transient.spectroscopy` 的 DISTINCT `source` |
| POST | `/admin/tns-download-hourly` | `admin.tns_download_hourly` | — | `{success, message:'TNS hourly download started in background'}` | 409 `'A TNS task is already running'` | thread：`download_TNS_api_hr(<目前 UTC 小時>)` → `addin_database(WORK.csv)` → `_run_detect_after_import(new_only=False, label='TNS-hourly (manual)')` → `auto_snoozed(now)`；進度寫 `_tns_task_status` |
| POST | `/admin/tns-download-daily` | `admin.tns_download_daily` | JSON(silent) `date`（`YYYY-MM-DD`，可省略 → 昨天 UTC） | `{success, message:'TNS daily download started in background'}` | 409 | thread：`download_TNS_api(y,m,d)` → `addin_database` → `_run_detect_after_import(new_only=True, label='TNS-daily (manual)')` → `auto_snoozed`。日期格式錯誤只在 thread 內設 message `'Invalid date format'` |
| POST | `/admin/tns-auto-snooze` | `admin.tns_auto_snooze` | — | `{success, message:'Auto-snooze started in background'}` | 409 | thread：`auto_snoozed(now)`：`transient.objects` 中 `status='Inbox'` 且 `last_phot_date`（或 `last_modified_date`）早於 15 天前 → `status='Snoozed'` |
| GET | `/admin/tns-task-status` | `admin.tns_task_status` | — | `{running:bool, message:str}` | — | 讀模組全域 `_tns_task_status`（**本 process 限定**） |
| GET | `/admin/detect-status` | `admin.detect_status` | — | `detect_pipeline.status()` 的 dict + `recent_jobs`（`job_status.get_all()` 中 key 以 `detect_` 開頭者）+ `manual:{running,message}` | — | 讀 `app/modules/DETECT/VERSION`、`DETECT_DATA_DIR/dustmaps/sfd/*.fits` 是否存在、查 `transient.detect_screen` / `transient.objects` / `transient.cross_matches` / `transient.detect_screen_history`；讀 `app/log/.job_status.json` |
| POST | `/admin/detect-run` | `admin.detect_run` | JSON(silent) `kind` ∈ {followups, recent, names}、`names`（以空白/逗號/分號分隔）、`hours`（float，預設 2） | `{success, message:'DETECT started: Follow-up re-screen' | 'objects TNS touched in the last N h' | 'N object(s)'}` | 503 `DETECT_IN_WEB=0`；409 執行中（`_detect_manual.running` 或 `detect_pipeline.is_running()`）；400 `names` 空 / `kind` 未知 | thread `detect_manual`：`detect_pipeline.run_followups()` / `run_recent(hours)` / `run_for_names(names, label='manual')`（寫 `transient.cross_matches`、`detect_screen`、`target_images`、`objects.tag/brightest_*`；`job_status` 記錄 `detect_follow_up` / `detect_recent_2h` / `detect_manual`）→ `_soft_invalidate_page_cache()`；message `'Done: k v, …'` |
| GET | `/admin/scheduled-jobs-status` | `admin.scheduled_jobs_status` | — | `{jobs:[{id,name,schedule,next_run,is_running,last_status,last_message,last_run_at}]}`（固定 9 個 job） | — | 讀 `scheduler_state.scheduler.get_job(id).next_run_time`（僅持有排程器的 process 有值），否則 `_calc_next_run()` 依 `_SCHEDULED_JOBS` 定義用純 Python 推算；`job_status.get_all()` / `is_running()` |

`_SCHEDULED_JOBS`（與 `main.py` 第 296–308 行 `add_job` 的 id 一一對應）：`daily_backup`（03:00 UTC）、`daily_phot_fetch`（03:30）、`daily_target_mag_update`（05:00）、`daily_retire_stale_followups`（05:30）、`daily_host_redshift_sync`（06:00）、`db_monitor`（10 min）、`db_recycle`（30 min）、`detect_page_prewarm`（30 min）、`daily_detect_followups`（04:00，僅 `detect_pipeline.ENABLED` 時註冊）。`main.py` 在 `config.DEBUG` 時完全不註冊任何 job，且只有拿到 `app/log/.background_jobs.lock`（`fcntl.flock`）的 process 會建立排程器。

補充細節：
- `update_user_session_groups(user_email)`（`admin_routes.py` 第 28 行）：僅當被改的 email 等於目前登入者時，重讀 `get_users()` 並覆寫 `session['user']['groups']`；其他使用者的 session 要等 `refresh_user_session` 下次請求時同步。
- `add_user` / `update_user_role` / `toggle_admin_status` 最終都經 `modules.database.auth.update_user(**kwargs)`；其 mapping 只接受 `name/picture_url/picture/roles/profile_picture/display_name/last_login` 與特殊鍵 `is_admin`（→ `roles` 50/1），其他鍵（含 `role`）靜默忽略。
- `detect_run` 與 `tns_download_*` 的 thread 內若丟例外，message 設為 `'Error: …'`，前端以紅字顯示（`_detectPoll` 用 `/^Error/` 判斷）。

### `web_log` blueprint（`app/routes/auth/web_log_routes.py`）

權限皆為 **GREAT_Lab 成員或 admin**；API 未通過 → `403 {'error': 'Access denied'}`。

| 方法 | 路徑 | endpoint | 輸入 | 成功回應 | 失敗回應 | 副作用 |
|---|---|---|---|---|---|---|
| GET | `/api/log/files` | `web_log.api_log_files` | — | `{dates:['YYYY-MM-DD', …]}`（降冪；只列檔名長度 14 且符合 `^\d{4}-\d{2}-\d{2}$` 的 `.log`） | log dir 未設或不存在 → `{dates:[]}` | `os.listdir(get_log_dir())` |
| GET | `/api/log/content` | `web_log.api_log_content` | query `date`（必填，`YYYY-MM-DD`）、`offset`（int，預設 0，負數歸 0）、`sources`（`all`/空 = 不過濾；否則逗號白名單）或 `source`（單一）、`tail_lines`（int，僅 `offset==0` 時生效，夾在 1–2000）、`max_bytes`（預設 131072，上限 2 MiB） | tail 模式：`{content, offset:<file_size>, returned_lines, truncated, file_size}`；一般模式：`{content, offset:<新位置>, returned_lines, truncated, file_size}`；`offset >= file_size` → 空 content；檔案不存在 → `{content:'', offset:0}` | 400 `Invalid date format`；403 路徑跳脫（`realpath` 不在 log dir 內）；500 讀檔例外 | 只讀 `app/log/<date>.log`。tail 模式從檔尾以 64 KiB 區塊反向掃描（最多 4 MiB），再依 source 過濾取最後 N 行 |
| GET | `/api/log/sources` | `web_log.api_log_sources` | query `date` | `{sources:[…排序去重]}`（掃描最多 120000 行，抓 `[name]` 標籤） | 400 / 403 / 500；檔案不存在 → `{sources:[]}` | 只讀 |
| GET | `/api/log/daemon/content` | `web_log.api_daemon_log_content` | query `source` ∈ {gcn_alert, detect, tns_fetch}、`offset`、`max_bytes` | `{content, offset}` | 400 `Invalid source`；403；500 | 讀 `app/log/gcn_alert.log` / `detect.log` / `tns_fetch.log`。**目前無任何程式寫這些檔、前端也不呼叫**（回 `{content:'', offset:0}`） |

log 檔格式由 `modules/log_setup.py::setup_logging(app/log)` 決定：`%(asctime)s [%(name)s] %(levelname)s %(message)s`（`YYYY-MM-DD HH:MM:SS`），檔名為 **UTC+8** 日期，保留最近 7 個檔案（`backup_count=7`），單檔達 15 MiB（`LOG_MAX_FILE_BYTES`）時**原地清空**並寫一行 WARNING，單行超過 1600 字（`LOG_MAX_LINE_CHARS`）截斷；`sys.stdout` 被導向 logger `app`。`_SRC_RE` 只認這種格式，其他行（例如 traceback 續行）在 source 過濾模式下會被濾掉。

### `database_status` blueprint（`app/routes/auth/database_status_routes.py`）

權限皆為 **僅 admin**；API 未通過 → `403 {'error': 'Access denied'}`。所有 DB 存取用 `_db_connect()`：**不經連線池**，每次 `psycopg2.connect(connect_timeout=4, application_name='kinder_db_status', options='-c statement_timeout=4000')`，用完即關。

| 方法 | 路徑 | endpoint | 輸入 | 成功回應 | 失敗回應 | 副作用 |
|---|---|---|---|---|---|---|
| GET | `/api/admin/database/status` | `database_status.api_database_status` | — | 200 `{available:true, error:null, checked_at, server:{host,port,name,server_addr,server_port,current_user}, summary:{total,active,idle,idle_in_transaction,waiting}, current_pid, server_version, sessions:[{pid,usename,application_name,client_addr,client_port,backend_type,state,wait_event_type,wait_event,xact_start,query_start,state_change,state_age_seconds,query(≤500 字),is_self}]}` | DB 不可用 → **503** 同結構（`available:false, error:<msg>`，summary 全 0） | 查 `pg_stat_activity WHERE datname='Kinder'`（active 優先、依 `state_change` 降冪） |
| POST | `/api/admin/database/action` | `database_status.api_database_action` | JSON(silent) `operation` ∈ {terminate(預設), cancel, terminate_idle}；`pids`（int、逗號字串、list 皆可；≤0 與非數字丟棄，去重排序）；`terminate_idle` 用 `idle_minutes`（int，夾 1–1440，預設 15） | cancel/terminate：`{attempted, succeeded, failed, skipped, results:[{pid,ok,skipped,message}], operation, pids}`；terminate_idle：同結構 + `operation:'terminate_idle', idle_minutes`（無目標時 attempted 0） | 400 `Invalid operation` / `No pids supplied` / `idle_minutes must be an integer`；terminate_idle 時 DB 不可用 → 503（status payload）或 503 `{error}`；cancel/terminate 連線失敗 → **200** 且 payload 含 `error` | `SELECT pg_cancel_backend(pid)` / `pg_terminate_backend(pid)`（autocommit）；自身 `pg_backend_pid()` 一律 `skipped`。terminate_idle 先選 `backend_type='client backend' AND state='idle' AND now()-state_change >= N min` 的 pid |

---

## 導向與流程

**進入點**
- 登入後 `_navbar.html`「Manage」下拉（僅 `session.user.is_admin`）：Web Log → `web_log.log_viewer`、DB Status → `database_status.database_status_page`、Admin Panel → `admin.admin_panel`。`home.html` 使用者選單另有 Admin Panel。
- 三頁頂端 Admin Hub 列互相連結（`/admin`、`/admin/database`、`/admin/log`）。
- Admin Panel Overview 的「Open DB Status」「Open Web Log」按鈕；DETECT 卡片「review page」連到 `/detect`（`detect.detect_results`）。
- GREAT_Lab 非 admin 成員可開 `/admin/log`，但**導覽列不提供入口**（Manage 選單只給 admin），且該頁 Admin Hub 上的另外兩個連結對其會被 redirect 回首頁。

**權限失敗去向**
- `/admin` → flash error + `basic.home`；`/admin/log`、`/admin/database` → 直接 `basic.home`（無 flash）。
- 所有 JSON 端點 → 403 `{'error':'Access denied'}`；前端多半以 `showNotification('Error: ' + result.error)` 顯示。
- 未登入者一樣 403 / redirect（沒有導去登入頁再返回的機制）。

**Admin Panel 典型流程**
1. 新增使用者：Users → Add User → `#addUserModal` → `POST /admin/add-user` → 成功 reload。（新使用者分支目前 500，見已知問題。）
2. 改角色：Users 表 role select → `POST /admin/update-role` → 成功或失敗都在 1–1.5 秒後 reload（失敗 reload 是為了把 select 復原）。
3. API key：Assign/Reset → confirm → `POST /admin/api-key/issue` → reload；Revoke / Dismiss → `POST /admin/api-key/revoke` → reload。使用者端在 Profile 申請（`auth_routes.request_api_key`）後才會出現在 banner。
4. 群組：New Group → `POST /admin/create-group`；卡片展開 → + Add → `GET /admin/available-users/<g>` → 勾選 → `POST /admin/add-multiple-to-group`；成員 × → `POST /admin/remove-from-group`；刪除群組 → `POST /admin/delete-group`。皆 reload。
5. 群組加入申請：使用者在 Profile（`basic_routes` / `auth_routes` 的 `create_group_request`）建立 `auth.usr_group(status='request')` → 理論上出現在 Groups banner → Approve/Reject。**目前 banner 永遠空、端點會 500**（見已知問題）。
6. Access Control：頁面權限即時 POST/DELETE（不用 Save）；Default Source Permissions 需按 Save All 一次整批覆寫。
7. Operations：各 Run Now → 立即回應「started in background」→ 有狀態端點者輪詢（photometry 3 秒、TNS 3 秒、DETECT 3 秒），無狀態端點者（missing phot、target mags）僅顯示啟動訊息。
8. 備份：Backup Now → 請求會卡住直到 `pg_dump` 完成（最長 300 秒）。

**Web Log 流程**：開頁 → 取日期清單 → 取 source 清單 → 載入最後 300 行 → 今天則每秒增量輪詢；切換日期 / source 重新載入；非今天日期不輪詢。

**DB Status 流程**：開頁 → 立即 + 每 5 秒 `GET /api/admin/database/status` → 前端算 pressure 與建議 → 任何動作 → confirm → `POST /api/admin/database/action` → 顯示結果 → 立即靜默刷新。

---

## 依賴的模組、資料表、檔案與外部服務

**Python 模組**
- `modules/database/auth.py`：`get_users`、`user_exists`、`save_user(email, name='', picture_url='', is_admin=False)`、`update_user(email, **kwargs)`、`delete_user`、`generate_api_key_for_user`、`revoke_api_key`、`get_api_key_requests`、`get_groups(user_email=None)`、`create_group(name, description='', creator_email=None, manager_email=None, joinable=True)`、`delete_group`、`group_exists`、`add_user_to_group(email, group_name, status='joined')`、`remove_user_from_group`、`user_in_group`、`get_group_requests(group_name=None)`、`get_group_request(email, group_name)`、`update_group_request_status(email, group_name, new_status)`、`get_invitations(status='pending')`、`get_setting(key, default=None)`、`set_setting(key, value)`、`get_default_source_permissions(source_name=None)`、`set_default_source_permissions_batch(permissions)`、`check_data_consistency()`（stub）、`clean_data_consistency()`（stub）。模組 import 時會執行 `_ensure_api_key_request_col()`（`ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS api_key_requested_at`）。
- `modules/database/__init__.py`：`get_db_connection()`（連線池 context manager，離開時 rollback/reset）、`DB_HOST/DB_PORT/DB_USER/DB_PASSWORD`（`PG_*` 環境變數，`kinder.env`）、`DB_NAME='Kinder'`。
- `modules/backup.py`：`run_daily_backup(force=False)`、`_find_pg_dump()`（Homebrew opt/Cellar → PATH → `/usr/bin` 等）、`BACKUP_DIR=app/data/backups`、`KEEP_DAYS=15`、`DATABASES=['Kinder']`。
- `modules/phot_scheduler.py`：`fetch_inbox_photometry()`、`is_running()`、`get_progress()`、`fetch_missing_photometry()`、`is_missing_running()`、`update_target_mags()`（以及 `retire_stale_followups()` 供排程）。
- `modules/auto_tns_download.py`：`SAVE_DIR=app/data/tns_api_download_work`、`download_TNS_api_hr(hr)`、`download_TNS_api(y,m,d)`、`addin_database(filepath, debug=False, fetch_phot_for_new=False)`、`auto_snoozed(time_now_utc)`、`_run_detect_after_import(new_only, label)`、`last_import_names()`。需要 `TNS_BOT_ID/TNS_BOT_NAME/TNS_API_KEY`。
- `modules/detect_pipeline.py`：`ENABLED`（`DETECT_IN_WEB`，預設開）、`DETECT_DIR=app/modules/DETECT`、`status()`、`is_running()`、`run_followups()`、`run_recent(hours)`、`run_for_names(names, label)`；內部 `_pin_db_env()` 會把 `PG_*` 與 `PG_DATABASE` 寫進 `os.environ`。
- `modules/job_status.py`：`get_all()`（合併 `app/log/.job_status.json` 與 process 內 registry，檔案快取 10 秒）、`is_running(job_id)`（僅本 process 可靠）。
- `modules/scheduler_state.py`：`scheduler`（由 `main.py` 在取得檔案鎖的 process 中設定）。
- `modules/log_setup.py`：`get_log_dir()`（`main.py` 設為 `app/log`）。
- `routes/detect/detect_routes.py`：`_soft_invalidate_page_cache()`。
- `routes/private_area/private_area_routes.py`：`/api/admin/private_area/page_perms`（前端直接呼叫）。
- 第三方：`psycopg2`（含 `RealDictCursor`）、`apscheduler`（間接）、`authlib`（`generate_token` 匯入但未用）。

**資料表**
- `auth.users`（`usr_id, email, name, picture_url, roles{0,1,50,99}, last_login, join_date, api_key, api_key_requested_at`）
- `auth.groups`（`group_id, name, description, joinable, create_by, manager`）
- `auth.usr_group`（`usr_id, group_id, status ∈ {request, joined, rejected}, created_at`；PK (usr_id, group_id)）
- `auth.invitations`（讀取但未使用）、`auth.system_settings`（`key, value, updated_at`；鍵 `open_registration`、`page_perm:<page>`）
- `transient.default_permissions`（`source PK, permissions_set ∈ {public, login, groups}, groups INT[]`）
- `transient.photometry`、`transient.spectroscopy`（讀 `source`）
- `transient.objects`、`transient.detect_screen`、`transient.detect_screen_history`、`transient.cross_matches`、`transient.target_images`（DETECT / TNS / snooze 寫入）
- `observation_targets`、`observation_logs`（`update_target_mags`）
- PostgreSQL 系統視圖 `pg_stat_activity`，函式 `pg_cancel_backend`、`pg_terminate_backend`、`pg_backend_pid`、`version()`、`inet_server_addr/port`

**檔案 / 目錄**
- `app/log/YYYY-MM-DD.log`（讀）、`app/log/.job_status.json`（讀）、`app/log/.background_jobs.lock`（排程器歸屬）、`app/log/{gcn_alert,detect,tns_fetch}.log`（daemon 端點，實際不存在）
- `app/data/backups/Kinder_backup_YYYYMMDD.sql`（寫、刪）
- `app/data/tns_api_download_work/tns_public_objects_{hr|YYYYMMDD}.csv.zip`、`tns_public_objects_WORK.csv`（寫）
- `app/modules/DETECT/VERSION`、`DETECT_DATA_DIR/dustmaps/sfd/SFD_dust_4096_{ngp,sgp}.fits`（讀）
- `app/routes/auth/static/tutorials/`（`clean_unused_images` 期望但不存在；實際文件圖在 `app/routes/private_area/tutorials/images/`）
- `kinder.env`（`PG_*`、`TNS_*`、`DETECT_IN_WEB`、`DETECT_DATA_DIR`、`ACCESS_LOG_ENABLED`、`LOG_MAX_FILE_BYTES`、`LOG_MAX_LINE_CHARS`）

**外部服務**
- TNS：`https://www.wis-tns.org/system/files/tns_public_objects/tns_public_objects_{HH|YYYYMMDD}.csv.zip`
- 本機 `pg_dump` 執行檔
- 光度來源（`fetch_inbox_photometry` 內部的各望遠鏡 / 巡天 API，由 phot_scheduler 章節說明）

---

## 前端檔案

| 類型 | 路徑 | 用於 |
|---|---|---|
| 模板 | `app/routes/auth/templates/admin.html` | `/admin` |
| 模板 | `app/routes/auth/templates/log_viewer.html` | `/admin/log`（CSS/JS 內嵌） |
| 模板 | `app/routes/auth/templates/database_status.html` | `/admin/database`（CSS/JS 內嵌） |
| CSS | `app/routes/auth/static/css/admin.css` | `admin.html`（同目錄的 `login.css`、`profile.css` 屬 auth 章節） |
| CSS（共用） | `app/routes/basic/static/css/_navbar.css` | `log_viewer.html`、`database_status.html` |
| 圖片（共用） | `app/routes/planners/static/photo/background_planner.jpg` | 兩頁背景 |
| JS | `app/routes/auth/static/js/admin.js`（1872 行） | `admin.html` |

靜態檔全部經 `main.py` 的 `/static/<path:filename>`（endpoint `static`）依 `_BLUEPRINT_STATIC_DIRS` 順序搜尋 9 個 blueprint 的 `static/`。

**`admin.js` / `admin.html` 內嵌 script 呼叫的 API 清單**

實際會被 UI 觸發：
`POST /admin/add-user`、`POST /admin/create-group`、`POST /admin/delete-group`、`POST /admin/remove-from-group`、`GET /admin/available-users/<g>`、`POST /admin/add-multiple-to-group`、`POST /admin/update-role`、`POST /admin/api-key/issue`、`POST /admin/api-key/revoke`、`POST /admin/group-requests/<id>/<action>`、`POST /admin/settings/save`、`GET /admin/check-consistency`、`POST /admin/clean-consistency`、`POST /admin/backup-now`、`POST /admin/documents/clean-images`、`POST /admin/run-photometry-fetch`、`GET /admin/photometry-fetch-status`、`POST /admin/run-missing-phot-fetch`、`POST /admin/run-update-target-mags`、`GET/POST /admin/default-source-permissions`、`GET /admin/sources/all`、`POST /admin/tns-download-hourly`、`POST /admin/tns-download-daily`、`POST /admin/tns-auto-snooze`、`GET /admin/tns-task-status`、`GET /admin/detect-status`、`POST /admin/detect-run`、`GET /admin/scheduled-jobs-status`、`GET/POST/DELETE /api/admin/private_area/page_perms`。

只存在於未被 HTML 掛接的死函式中：
`GET /admin/user-groups/<email>`（`loadUserGroups`、`loadBatchGroupsData`）、`POST /admin/batch-update-groups`（`saveBatchGroups`）、`POST /admin/add-to-group`（`addToGroup`）、`POST /admin/toggle-admin`（`toggleAdminStatus`）、`POST /admin/delete-user`（`deleteUser`）、`POST /admin/clean-invitations`（`cleanAcceptedInvitations`，**後端不存在**）、`POST /admin/delete-invitation`（`deleteInvitation`，**後端不存在**）、`GET/POST/DELETE /api/object/greatlab_routes/permissions`（`loadGreatLabPermissions` 等，**後端不存在**）。

**`log_viewer.html` 呼叫**：`GET /api/log/files`、`GET /api/log/sources`、`GET /api/log/content`。
**`database_status.html` 呼叫**：`GET /api/admin/database/status`、`POST /api/admin/database/action`。

---

## 已知問題與注意事項

### 功能性錯誤（會導致 500 或行為不符）

1. **群組加入申請流程整條壞掉（三處）**
   - `admin_panel` 呼叫 `get_group_requests('pending')`，但該函式的第一個參數是 `group_name`，等於查「名為 `pending` 的群組」的申請 → banner 永遠空、Pending Requests 統計永遠 0。
   - `admin.html` 第 364、370 行使用 `req.user_email` 與 `req.id`，但 `get_group_requests()` 回傳的 dict 只有 `usr_id, group_id, status, created_at, email, user_name, group_name` → 即使有資料，email 顯示空白、`data-rid=""` → `+''` = 0。
   - `handle_group_request` 呼叫 `get_group_request(request_id)`（實際簽名 `(email, group_name)`）與 `update_group_request_status(request_id, 'approved')`（實際簽名 `(email, group_name, new_status)`）→ `TypeError` → 500。此外 `'approved'` 也不是 `auth.usr_group.status` 的合法值（CHECK 只允許 `request/joined/rejected`）。整個設計仍停留在舊版「以 id 為主鍵的 group_requests 表」。

2. **`POST /admin/add-user` 新增新使用者必定 500**：呼叫 `save_user(email=…, name=…, picture=…, is_admin=…, role=…, invited_at=…, last_login=None)`，但 `modules/database/auth.py::save_user` 只接受 `(email, name, picture_url, is_admin)` → `TypeError: unexpected keyword argument 'picture'`。前端 `response.json()` 解析 HTML 500 頁失敗，只顯示「An error occurred」。（`auth_routes.py` 第 159 行首次登入的 `save_user(...)` 也用同樣錯誤的關鍵字，屬 auth 章節範圍，此處交叉提醒。）

3. **`/admin/update-role` 無法把使用者設成 guest**：`update_user()` 忽略 `role` 鍵，只依 `is_admin` 寫 `roles=50` 或 `1`；選 guest 實際存成 `1`（= user），回應卻說 `Role updated to guest`。同時任何角色變更都會把 `roles=99`（super_admin）降成 50。`add_user` 對既存使用者的「role updated」也同樣只動 `is_admin`。

4. **Open Registration 開關是死設定且顯示錯誤**：前端送 JSON 布林，`set_setting` 存 `str(True)` = `'True'`；`admin_panel` 用 `== 'true'` 比較 → 打開後重新整理 checkbox 顯示為關。而且整個程式碼只有 `admin_panel` 讀 `open_registration`，登入流程完全不檢查它。

5. **`POST /admin/default-source-permissions` 忽略 DB 結果**：`set_default_source_permissions_batch()` 回傳 False 時仍回 `{success:true}`；且該函式先 `DELETE` 全表再重插，若失敗會 rollback，前端卻顯示「Saved」。缺 `source_name` 時 `p['source_name']` KeyError → 500。

6. **`POST /admin/documents/clean-images` 永遠 no-op**：目標目錄 `admin_bp.root_path/static/tutorials` = `app/routes/auth/static/tutorials`，不存在；文件圖片實際在 `app/routes/private_area/tutorials/images/`（由 `private_area` 的 `/tutorials/images/<filename>` 提供）。

7. **Dismiss API key request 會撤銷既有 key**：`adminDismissApiKeyRequest()` 呼叫 `/admin/api-key/revoke`，該端點同時把 `api_key` 設為 NULL；對「Reset request」（使用者已有 key）按 Dismiss 會直接刪掉使用者現有的 key，而非只清除申請。

8. **`url_for('admin.accept_invitation')` 指向不存在的 endpoint**（`auth_routes.py` 第 170 行）：`admin` blueprint 沒有 `accept_invitation`；一旦 `session['pending_invitation']` 存在會 `BuildError` → 500。目前沒有任何程式寫入 `pending_invitation`，所以是未觸發的地雷。

9. **`tns_download_daily` 的日期驗證在 thread 內**：`date` 格式錯誤時 HTTP 仍回 `success:true, 'started in background'`，之後輪詢得到 `running:false, message:'Invalid date format'`，前端用綠色 ✓ 呈現。

10. **`/static/img/default-avatar.png` 不存在於任何 static 目錄**：`admin.html` 的 `onerror` 後備、`get_available_users` 的預設 `picture`、`add_user` 的預設圖都會 404。

### 死程式碼 / 重複 / 不一致

11. `admin_routes.py` 未使用的 import：`generate_token`（authlib）、`current_app`、`re`（函式內另 `import re as _re`）、`send_invitation_email`、`create_invitation`、`get_invitation`、`update_invitation`、`delete_invitation`、`clean_accepted_invitations`、`delete_group_request`。`admin_panel` 多做一次 `get_invitations()` 查詢並傳 `invitations`、`current_user_email` 給模板，但模板都沒用。

12. 後端存在但**沒有任何活的呼叫者**的端點：`POST /admin/toggle-admin`、`POST /admin/delete-user`、`GET /admin/user-groups/<email>`、`POST /admin/batch-update-groups`、`POST /admin/add-to-group`、`GET /admin/sources/search`、`GET /api/log/daemon/content`。（前五個只被未掛接的 JS 函式引用。）

13. 前端呼叫但**後端不存在**：`POST /admin/clean-invitations`、`POST /admin/delete-invitation`、`GET/POST/DELETE /api/object/greatlab_routes/permissions`、以及 `copyInvitationLink()` 組出的 `/invitation/<token>`。皆位於未掛接的 JS 函式（`cleanAcceptedInvitations`、`deleteInvitation`、`loadGreatLabPermissions`、`addGreatLabPermission`、`removeGreatLabPermission`、`copyInvitationLink`）。

14. `admin.js` 內重複定義（JS 後者覆蓋前者）：`addToGroup` ×2（第 278、434 行）、`removeFromGroup` ×3（第 307、461、794 行；最後一個生效，成功後 reload）、`deleteGroup` ×2（第 551、825 行）。另有引用不存在 DOM 的函式：`showGroupModal`/`showBatchGroupModal`/`saveBatchGroups`/`updateGroupsModalDisplay`/`updateBatchGroupsDisplay`（`#manageGroupsModal`、`#batchGroupsModal`、`#selectedUserEmail`、`#currentGroupsList`、`#availableGroupsList`、`#batchGroupsContainer`）、`loadGreatLabPermissions`（`#active-permissions`、`#new-permission-group`）；`updateGroupsDisplay()` 是空函式。`admin.js` 與 `log_viewer.html` 各自定義 `clearSearch()`（不同頁面，無衝突）。

15. `check_data_consistency` / `clean_data_consistency` 在新單一 DB 設計下是 stub（永遠 ok / 0）；`admin.js::showConsistencyResults()` 期待的 `orphaned_user_groups` / `orphaned_group_users` 永遠不會出現，`#consistencyModal` 實務上開不了。每次開 Admin Panel 仍會自動打一次 `/admin/check-consistency`。

16. `admin_bp = Blueprint('admin', __name__, template_folder='templates', static_folder='../static')`：`static_folder` 解析為 `app/routes/static`（不存在），且會註冊一條 `admin.static` → `/static/<path:filename>`，與 `main.py` 第 126 行的 app 層 `static` 規則路徑完全相同；因 app 層先註冊、werkzeug 排序穩定，`admin.static` 永遠被遮蔽，屬無害死規則。

17. `web_log` 的 daemon log 端點與 `_DAEMON_LOG_FILES`：目前 TNS 下載器、gap filler、DETECT 都改走 root logger 寫進每日檔（`start_auto_tns_downloader` 註解明言），`gcn_alert.log/detect.log/tns_fetch.log` 沒有 writer；`log_viewer.html` 也宣告 `currentMode = 'web'; // only web log`。

18. `admin.html` 文案與實際排程不符：
    - 「Inbox Photometry Fetch — Auto-runs daily at 09:00 UTC+8」：`main.py` 排在 03:30 UTC（= 11:30 UTC+8）。
    - 「Missing Photometry Check — Auto-runs hourly」：`main.py` 第 298 行該 job 已被註解掉，現在只能手動。
    - 「TNS … daemon at :15/:45 (hourly) and 01:00 UTC (daily)」：daemon `main()` 的每日任務其實在 01:00、04:00、12:00 UTC 各跑一次並回補今天/昨天/前天。
    - 「Update Target Magnitudes — Auto-runs daily at 05:00」正確（UTC）。

19. `admin.html` Joined 欄讀 `user.invited_at`，但 `_user_row_to_dict` 從不產生該鍵，實際顯示 `last_login`；可用的 `join_date` 未被使用。`admin.js::loadUsersData` 註解寫 5 欄，實際 6 欄（索引 1、2 仍正確）。

20. `handle_group_request` 的 `<action>` 是自由字串（非 approve/reject 回 400），`request_id` 用 `<int:>` 轉換器。

### 併發 / 多 process / 效能注意事項

21. **狀態全是 process 內全域變數**：`_tns_task_status`、`_detect_manual`、`phot_scheduler._running/_progress/_running_missing`、`detect_pipeline._state`、`job_status._registry`（`is_running`）。若 gunicorn 多 worker（repo 內未見 worker 數設定），輪詢請求可能落到別的 worker 而顯示 Idle / 舊訊息，409「already running」防呆也只在同一 worker 內有效，可能重複啟動。`job_status` 只把**已完成**的紀錄寫進 `app/log/.job_status.json` 供跨 worker 讀取。排程器與 `next_run_time` 只存在於持有 `.background_jobs.lock` 的 process；其他 worker 由 `_calc_next_run()` 推算，因此 DEBUG 模式或 DETECT 停用時仍會顯示「Wait for next run at …」（含未註冊的 `daily_detect_followups`）。

22. 手動 TNS 任務與背景 daemon 共用 `SAVE_DIR/tns_public_objects_WORK.csv`，兩者之間沒有共同的鎖（`_tns_task_status` 只擋手動任務），時間重疊時可能互相覆蓋工作檔。另外手動 hourly 呼叫 `addin_database(str(work_csv))` 使用預設 `fetch_phot_for_new=False`，而 daemon 的 hourly 用 `True`，行為不一致。

23. `/admin/backup-now` 在請求執行緒內同步跑 `pg_dump`（最長 300 秒），期間佔用 worker；前端無 timeout 處理。

24. `/api/admin/database/status` 每 5 秒開一條新的非池化連線（`application_name='kinder_db_status'`），多個管理者同時開頁會在 `pg_stat_activity` 看到多條 self 連線；`_apply_backend_action` 亦另開連線，因此「self」pid 在 status 與 action 之間並非同一條，伺服器端保護的是 action 連線自己的 pid，前端保護的是 status 回傳的 `current_pid`。

25. `/api/admin/database/action` 對 cancel/terminate 的連線失敗回 HTTP 200 並在 payload 帶 `error`，與 terminate_idle 的 503 不一致；前端以 `data.error` 判斷所以可運作。

26. `search_sources` / `all_sources` 捕捉所有例外並回 `{success:true, sources:[]}`，DB 錯誤會被遮蔽成「沒有來源」。

27. `POST /admin/run-update-target-mags` 沒有重入保護與狀態端點；連按會啟動多個 thread。

28. 存取記錄：`_ACCESS_SKIP_PREFIXES` 略過 `/api/log/content` 與 `/api/log/daemon/content`，但 **不略過** `/api/log/sources` 與 `/api/log/files`（每 30 秒一次），開啟 `ACCESS_LOG_ENABLED` 時仍會有少量自我記錄。

29. `admin_issue_api_key` 產生的 key 不回傳給管理者，使用者需自行到 Profile 查看。

30. `/admin/log` 允許 GREAT_Lab 非 admin 讀取完整伺服器 log（含 `web.request` 存取紀錄中的 email、IP、UA），屬設計決定但需留意資訊揭露範圍。
