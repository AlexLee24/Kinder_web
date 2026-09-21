# 首頁、登入/OAuth、個人資料與相簿（basic / auth / api blueprints）

> **注意**：本章記錄的是重構前（commit `c7f91a4`，2026-09-21）的狀態，檔案路徑為舊位置（`app/routes/…`、`app/modules/…`）。新位置請對照 `docs/ARCHITECTURE.md` §6「新舊路徑對照」；功能與行為在重構後完全相同。

> 依據原始碼逐一確認（2026-09-21 快照，branch `master`，commit `c7f91a4`）。
> 涵蓋檔案：`app/routes/basic/basic_routes.py`、`app/routes/auth/auth_routes.py`、`app/routes/api_routes.py`、對應模板/JS/CSS、`app/modules/database/auth.py`、`app/modules/email_utils.py`、`app/main.py`（全域設定部分）、`app/routes/__init__.py`。
> 執行環境：Flask 3.1.3、Werkzeug 3.1.8、Authlib 1.8.0、Pillow 12.3.0（`uv.lock` / `.venv`）。

---

## 概要

### 這個區塊負責什麼

| Blueprint | 變數 / 名稱 | 檔案 | url_prefix | 負責內容 |
|---|---|---|---|---|
| `basic_bp` | `basic` | `app/routes/basic/basic_routes.py` | 無 | 首頁 `/`、登入頁 `/login`、個人資料頁 `/profile`、首頁幻燈片 API、首頁相簿（Gallery）API 與圖片檔案服務、（被遮蔽的）群組加入/退出 API |
| `auth_bp` | `auth` | `app/routes/auth/auth_routes.py` | 無 | Google OAuth 登入/回呼、登出、本機管理員帳密登入、更新個人資料、群組加入/退出 API（實際生效版）、API key 申請 |
| `api_blueprint` | `api` | `app/routes/api_routes.py` | `/api` | 只有一個已停用的 `/api/generate_key`（永遠 403） |

對應網站頁面：首頁（`/`）、登入頁（`/login`）、個人資料頁（`/profile`）。此外 `_navbar.html`（全站導覽列）與 `_favicon.html` 也放在 `basic/templates/`，被全站 27 個模板 `{% include %}`，是整站導向骨幹（詳見下方「_navbar.html 導覽結構」）。

### 和其他區塊的關係

- 其他 blueprint 的權限檢查失敗時幾乎都 `redirect(url_for('basic.login'))`（未登入）或 `redirect(url_for('basic.home'))`（權限不足），例如 `detect_routes.py`、`private_area_routes.py`、`admin_routes.py`、`web_log_routes.py`、`database_status_routes.py`。
- 個人資料頁發出的「群組加入申請」與「API key 申請」由 **管理面板章節**（`admin_bp`：`/admin/group-requests/<int:request_id>/<action>`、`/admin/api-key/issue`、`/admin/api-key/revoke`）處理。
- 「API key」權限類別（`X-API-Key` header 或 `?api_key=`，經 `get_user_by_api_key`）由 **web_api 章節** 使用；本章只負責使用者申請與 admin 發放的資料欄位。
- `admin_routes.py` 自己另外定義了一份 `update_user_session_groups()`；`auth_routes.py` 那一份（掛在 `auth_bp.update_user_session_groups`）沒有任何呼叫者。

### Blueprint 註冊順序（`app/routes/__init__.py::register_routes`）

```
auth_bp → admin_bp → astronomy_tools_bp → objects_bp → api_blueprint → web_api_bp
→ private_area_bp → basic_bp → marshal_bp → detect_bp → web_log_bp
→ database_status_bp → games_bp → planners_bp
```

Werkzeug 3.1 的 `StateMachineMatcher` 對相同 rule 做穩定排序，**先加入者先匹配**。已用專案 venv 以最小 Flask app 實測（相同 path + method）：

| 路徑 | 定義處 | 實際生效 endpoint | 永不執行的 endpoint |
|---|---|---|---|
| `POST /api/profile/join_group` | `auth_routes.py`、`basic_routes.py` | `auth.profile_join_group` | `basic.api_join_group` |
| `POST /api/profile/leave_group` | `auth_routes.py`、`basic_routes.py` | `auth.profile_leave_group` | `basic.api_leave_group` |
| `POST /api/generate_key` | `api_routes.py`、`web_api_routes.py` | `api.generate_key` | `web_api.generate_key` |
| `GET /static/<path:filename>` | `main.py`（app 層，endpoint `static`）+ 各 blueprint 的 `static_folder='static'` 自動產生 | app 層 `static` | `basic.static`、`auth.static` 等（只作為 `url_for` 別名，產生同樣的 `/static/...` URL） |

---

### 全站共用機制（`app/main.py`）

#### 1. Flask app 建立與 session cookie 設定

```python
app = Flask(__name__, template_folder='html', static_folder=None)   # app/html 目錄並不存在；模板全部來自各 blueprint 的 templates/
app.secret_key = config.SECRET_KEY                                   # 未設定時預設 'your-very-secure-secret-key'
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)           # 信任 1 層 proxy 的 X-Forwarded-Proto / X-Forwarded-Host
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = not config.DEBUG               # 非 DEBUG 才強制 HTTPS cookie
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
```

- Session 為 Flask 預設的 **客戶端簽章 cookie**（itsdangerous 簽章、未加密），內容可被持有者 base64 解碼閱讀；大小上限約 4 KB（因此程式多處刻意避免把 base64 頭像寫入 session）。
- 兩條登入路徑都設定 `session.permanent = True`；配合 Flask 預設 `SESSION_REFRESH_EACH_REQUEST=True`，**每個請求都會重新簽發 cookie**，所以對 `session['user'][...]` 的巢狀修改即使沒有 `session.modified = True` 也會被保存。

#### 2. 統一的 `/static/<path:filename>` 路由（endpoint 名 `static`）

`serve_static_files(filename)` 依序在下列目錄尋找第一個存在的檔案並以 `send_from_directory` 回傳：

1. `app/routes/basic/static`
2. `app/routes/auth/static`
3. `app/routes/astronomy_tools/static`
4. `app/routes/marshal/static`
5. `app/routes/detect/static`
6. `app/routes/games/static`
7. `app/routes/private_area/static`
8. `app/routes/planners/static`
9. `app/routes/web_api/static`
10. 若 `filename` 以 `photo/` 開頭 → 專案根目錄 `photo/`（`_PHOTO_DIR`；**目前不存在**）
11. 若 `filename` 以 `icon/` 開頭 → `app/routes/basic/icon/`（`Kinder_dark.png`、`Kinder_light.png`、`favicon.ico`）
12. 皆無 → `abort(404)`

因為先找到者勝，**不同 blueprint 若有同名靜態檔（例如都有 `css/style.css`）會被前面的目錄遮蔽**。各 blueprint 宣告 `static_folder='static'` 產生的 `<bp>.static` 端點 URL 與 app 層相同，實際由 app 層路由處理（已實測）。

#### 3. `before_request` 執行順序（依註冊順序）

| 順序 | 函式 | 行為 |
|---|---|---|
| 1 | `_enforce_allowed_host` | `request.host` 不在 `_ALLOWED_HOSTS` → 記 warning log 並 `abort(404)`。`_ALLOWED_HOSTS = {urlparse(config.APP_BASE_URL).netloc}`；DEBUG 時再加入 `HOST:PORT`、`localhost:PORT`、`127.0.0.1:PORT`。（經 ProxyFix，`request.host` 可來自 `X-Forwarded-Host`。） |
| 2 | `refresh_user_session`（來自 `auth_routes.py`，以 `app.before_request(refresh_user_session)` 全域註冊） | 見下方說明 |
| 3 | `_mark_request_start` | `g._req_start_monotonic = time.monotonic()`（給 access log 計時） |
| 4 | `_block_pipe_in_api_params` | 只對 `request.path.startswith('/api/')` 生效：query string、form 任一值含 `|`，或 JSON body（遞迴檢查 dict/list）含 `|` → 回 `{"error": "Invalid character '|' is not allowed"}`，HTTP 400。**不涵蓋 `/update-profile`、`/admin-login` 等非 `/api/` 路徑。** |

#### 4. `after_request` 與其他全域設定

- `_add_isolation_headers`：所有回應加 `Cross-Origin-Opener-Policy: same-origin`、`Cross-Origin-Resource-Policy: same-origin`（因此 `/gallery/image/...`、`/slideshow/image/...` 無法被其他網站跨站嵌入）。
- `_log_request_access`：僅當環境變數 `ACCESS_LOG_ENABLED` 為 1/true/yes/on 時，對非 `/static/`、`/api/log/content`、`/api/log/daemon/content` 的請求以 logger `web.request` 記錄 `method/path/status/duration_ms/bytes/ip/user/ua`；`user` 取 `session['user']['email']`，否則 `anon`。
- `@app.errorhandler(ParamOutOfRangeError)` → `{'error': str(exc)}` 400。
- URL converter `alpha`（`[a-zA-Z]+`）、Jinja filter `regex_search`（供 marshal 章節用）。
- 啟動時：`check_db_connection()`、`init_connection_pool()`（失敗只印 WARNING，不中止）；`from routes.auth.auth_routes import oauth, refresh_user_session` 後 `oauth.init_app(app)`。
- 背景排程（APScheduler + 檔案鎖 `app/log/.background_jobs.lock`）與本章無直接關係，略。

#### 5. `session['user']` 內含哪些 key

| key | Google 登入（`auth.google_callback`） | 本機管理員登入（`auth.admin_login`，DB 有列） | 本機管理員登入（DB 無列 fallback） |
|---|---|---|---|
| `email` | Google userinfo email | `config.ADMIN_LOCAL_EMAIL` | `config.ADMIN_LOCAL_EMAIL` |
| `name` | DB `name`，否則 Google `name` | DB `name`（預設 `'Admin'`） | `'Admin'` |
| `picture` | DB `picture_url` 或 Google `picture`；若為 `data:image` base64 則改用 Google picture | DB `picture_url`；若為 base64 則 `None` | `None` |
| `is_admin` | DB `roles >= 50`；新使用者若 email == `config.ADMIN_EMAIL` 則 True | DB `is_admin`（預設 True） | `True` |
| `role` | DB 導出 `'admin' / 'user' / 'guest'`；新使用者 `'guest'`（ADMIN_EMAIL 為 `'admin'`） | DB `role`（預設 `'admin'`） | `'admin'` |
| `is_great_lab_member` | `'GREAT_Lab' in groups or is_admin` | `'GREAT_Lab' in groups or check_object_access('greatlab_routes', email)` | `True` |
| `groups` | DB 已 `joined` 的群組名稱 list | **（無此 key）** | **（無此 key）** |
| `api_key` | DB `api_key`（新使用者 `None`） | DB `api_key` | **（無此 key）** |

其他會出現在 session 的 key：`_flashes`（flash 訊息）、Authlib 的 `_state_google_<state>`（OAuth 進行中暫存 state / code_verifier / nonce）；程式有讀取但**從未寫入**的 key：`pending_invitation`、`next_url`。

#### 6. `refresh_user_session` 每次請求做什麼（`auth_routes.py:32-74`）

1. `'user' not in session` → 直接返回；`request.path.startswith('/static')` → 直接返回。
2. `get_user(session['user']['email'])`（2 個 SQL：`auth.users` 單列 + `auth.usr_group JOIN auth.groups WHERE status='joined'`）。DB 例外 → log warning 後返回（不影響請求）。
3. 查無此人 → 返回（**不設定 `g.current_user`**，session 保持登入狀態）。
4. `g.current_user = user_data`（完整 dict，含 `picture`（可能是 base64 data URI）、`api_key`、`has_api_key`、`api_key_request_pending`、`role`、`role_level`、`groups`、`is_super_admin`…）。模板用 `g.current_user.picture` 顯示頭像，避免 base64 進 cookie。
5. 同步到 session：`is_admin`、`is_great_lab_member`（`'GREAT_Lab' in groups or is_admin`）、`picture`（只在 DB 值非 `data:image` 且不同時覆寫；若 session 內意外存有 base64 則清成 `''`）。有變更才 `session.modified = True`。
6. **不同步** `role`、`groups`、`name`、`api_key` —— 這些只在登入當下寫入。

---

### 權限模型（`app/modules/database/auth.py` + `_Kinder_Database/SQL/auth.sql`）

| 概念 | 資料來源 | 說明 |
|---|---|---|
| 角色等級 | `auth.users.roles INT CHECK IN (0,1,50,99)` | 0=guest、1=user、50=admin、99=super_admin。`_user_row_to_dict` 導出：`is_admin = roles>=50`、`is_super_admin = roles>=99`、`role = 'admin'/'user'/'guest'`、`role_level`。 |
| 管理員 | `is_admin` | 模板/路由以 `session['user']['is_admin']` 判斷；`refresh_user_session` 每請求同步。 |
| Guest | `role == 'guest'` 且非 admin | 首次 Google 登入的新帳號預設 guest；多數功能頁（detect、marshal 物件操作）拒絕 guest；本章中 guest 不能申請 API key、profile 頁不顯示 API key 區塊、navbar 顯示「(Guest)」。 |
| 群組 | `auth.groups(group_id, name, description, joinable, create_by, manager)`、`auth.usr_group(usr_id, group_id, status IN ('request','joined','rejected'), created_at)` | 「加入申請」就是 `usr_group` 一列 `status='request'`（`create_group_request` = `add_user_to_group(status='request')`，`ON CONFLICT DO UPDATE SET status`）；退出 = 刪除該列。`joinable` 欄位目前未被本章使用。 |
| GREAT_Lab 成員 | 群組名稱 `'GREAT_Lab'` 或 admin | `is_great_lab_member` 控制 navbar「Private」選單與 private_area/detect 等頁面。 |
| API key | `auth.users.api_key TEXT UNIQUE`、`api_key_requested_at TIMESTAMPTZ`（後者由 `_ensure_api_key_request_col()` 在 **import 時** `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 建立） | 使用者 `request_api_key()` 標記申請時間；admin `generate_api_key_for_user()` 產生 48 字元英數 key 並清除申請；`revoke_api_key()` 清除。自助產生（`/api/generate_key`）已停用。web_api 以 `get_user_by_api_key()` 驗證。 |
| 邀請 | `auth.invitations`（由 `database/__init__.py::_ensure_extra_tables` 建表）；函式 `get_invitations / create_invitation / get_invitation / update_invitation / delete_invitation / clean_accepted_invitations`；`email_utils.send_invitation_email` | **目前沒有任何 route 呼叫這些函式或寄信**（admin_routes 只有 import 與 `get_invitations()` 顯示）。`google_callback` 內的 `pending_invitation` 分支指向不存在的 `admin.accept_invitation`。 |
| 自訂頁面群組權限 | `auth.system_settings` key `page_perm:<page_key>`（JSON list）；`get_page_groups / set_page_groups` | 由 private_area 章節使用，本章無。 |
| 物件權限 | `transient.objects.permission/groups`；`check_object_access` | marshal 章節使用；本章僅 `admin_login` 殘留呼叫 `check_object_access('greatlab_routes', email)`。 |
| 使用者頭像 | `auth.users.picture_url TEXT` | profile 頁上傳的頭像以 **base64 data URI 字串** 直接存入 `picture_url`；schema 另有 `auth.images(usr_id, image_data BYTEA)` 但程式完全未使用。 |

---

### `_navbar.html` 導覽結構（全站骨幹）

檔案：`app/routes/basic/templates/_navbar.html`（被 27 個模板 include；**首頁 `home.html` 不 include**，自有精簡頂欄）。內容依序為：

1. **`<head>` 片段**（注意：它是被 include 在各頁 `<body>` 內的，因此會產生第二個 `<head>`）：`<title>Kinder Web</title>`、載入 `css/_theme.css`、`css/_navbar.css`、定義 `--navbar-bg-image: url(/static/photo/navbar.jpg)`（檔案不存在，且 `_navbar.css` 未使用此變數）、`{% include '_favicon.html' %}`。
2. **`<header>`**：
   - Logo `<a href="/">`（`icon/Kinder_light.png` + 文字 Kinder）。
   - 漢堡按鈕（≤780px）。
   - **左側 `ul.nav-left`**（所有人可見）：

   | 項目 | 連結 / endpoint | 顯示條件 |
   |---|---|---|
   | Marshal | `url_for('marshal.marshal')` → `/marshal` | 永遠 |
   | Tools ▾ Astronomy Tools | `astronomy_tools.astronomy_tools` → `/astronomy_tools` | 永遠 |
   | Tools ▾ Telescope Simulator | `astronomy_tools.telescope_simulator` → `/telescope_simulator` | 永遠 |
   | Tools ▾ LC Plotter | `astronomy_tools.lc_plotter` → `/lc_plotter` | 永遠 |
   | Tools ▾ Exposure Time Calculator | `astronomy_tools.exposure_time_calculator` → `/exposure_time_calculator` | 永遠 |
   | Tools ▾ (3D Mount Simulator) | `astronomy_tools.mount_3d` → `/mount_3d` | **HTML 註解掉**，但 Jinja 仍會執行 `url_for`（endpoint 存在，不會出錯） |
   | Tools ▾ Games | `games.games` → `/games` | 永遠 |
   | Planners ▾ Visibility Plot | `astronomy_tools.interactive_planner` → `/interactive_planner` | 永遠（注意是 astronomy_tools 而非 planners blueprint） |
   | Planners ▾ Finding Chart | `astronomy_tools.finding_chart` → `/finding_chart` | 永遠 |
   | About Us ▾ About GREAT Lab | 外部 `https://sites.google.com/view/great-lab/home?authuser=0`（新分頁） | 永遠 |
   | About Us ▾ NCU Lulin Observatory | 外部 `https://www.lulin.ncu.edu.tw/weather/`（新分頁） | 永遠 |
   | Private ▾ DETECT | `detect.detect_results` → `/detect` | `session.user` 且 `is_great_lab_member` |
   | Private ▾ Daily Trigger | `private_area.daily_trigger` → `/daily_trigger` | 同上 |
   | Private ▾ ePessto++ Support Team | `private_area.epessto_support_page` → `/epessto_support` | 同上 |
   | Private ▾ Documents | `private_area.documents_list` → `/documents` | 同上 |
   | Private ▾ Lab Info | `private_area.greatlab_info` → `/greatlab_info` | 同上 |

   - **右側 `ul.nav-right`**：

   | 狀態 | 顯示內容 |
   |---|---|
   | 未登入 | `Login` 按鈕 → `url_for('basic.login')` → `/login` |
   | 已登入 | 使用者選單：頭像（`g.current_user.picture` 優先，否則 `session.user.picture`）+ `session.user.name`；若 `role == 'guest'` 且非 admin 額外顯示「(Guest)」。下拉：Profile → `basic.profile`（`/profile`）、Logout → `auth.logout`（`/logout`） |
   | 已登入且 `session.user.is_admin` | 額外分隔線 + `Manage ▾`：Web Log → `web_log.log_viewer`（`/admin/log`）、DB Status → `database_status.database_status_page`（`/admin/database`）、Admin Panel → `admin.admin_panel`（`/admin`） |

   所有 `url_for` 目標經全站路由清單逐一比對皆存在。
3. **Flash 訊息容器**：`get_flashed_messages(with_categories=true)` 逐條渲染 `div.flash-message.<category>`（類別：`success` / `error` / `warning` / `info`），內嵌 script 於 3 秒後隱藏 `#flash-message`。
4. **內嵌 script**：漢堡切換 `.main-nav.active`、點外部關閉；≤780px 時 dropdown 以點擊展開（`mobile-active`）；捲動 >20px 時 header 加 `scrolled` class。
5. `current_path` 變數用於「active」樣式判斷（Tools：`/astronomy_tools`、`/telescope_simulator`、`/mount_3d`、`/lc_plotter`、`/exposure_time_calculator`、`/games`；Planners：`/observation_planner`、`/interactive_planner`、`/finding_chart`；Private：`/detect_results`、`/private`、`/documents`、`/epessto_support`），但因 `<a>` 標籤同時已有 `class="dropdown-toggle"` 又再寫一個 `class="active"`（重複屬性，瀏覽器取第一個），實際上 active 樣式不會套用。

`_favicon.html`（單行）：`<link rel="icon" href="{{ url_for('basic.static', filename='icon/favicon.ico') }}">` → `/static/icon/favicon.ico` → 由 app 層 static 路由在 `basic/static/icon/favicon.ico` 找到。

---

## 頁面（HTML routes）

### GET `/` — `basic.home`

- **權限**：公開。
- **模板**：`app/routes/basic/templates/home.html`（不 include `_navbar.html`；include `_favicon.html`）。
- **模板變數**：`current_path='/'`、`db_offline = not is_db_available()`（`is_db_available()` 以 15 秒快取呼叫 `check_db_connection()`，會開一條新的 psycopg2 連線測試）。另使用全域 `session.user`、`g.current_user`。
- **副作用**：無資料寫入；若已登入則 `refresh_user_session` 讀 `auth.users`。
- **頁面區塊與互動**：

| 區塊 | 內容 | 呼叫 / 導向 |
|---|---|---|
| DB offline 橫幅 | `db_offline` 為真時顯示 `DB OFFLINE — the database connection is currently unavailable...` | — |
| 浮動頂欄 `.home-top-bar` | 未登入：`Sign In` → `/login`。已登入：頭像 + 名稱 chip，hover 下拉：Profile → `/profile`；Admin Panel → `/admin`（僅 `is_admin`）；Logout → `/logout` | `basic.login` / `basic.profile` / `admin.admin_panel` / `auth.logout` |
| 主橫幅 `.main-banner` | Logo + 「Kinder / Kilonova Finder」標題；背景 `css` 指向 `../photo/background.jpg`（`basic/static/photo/background.jpg`）；`home.js` 加上流星 canvas 動畫 | — |
| 手機漢堡 + 覆蓋層 `#home-mobile-nav` | 與 navbar 相同的 Marshal / Tools / Planners / About Us（/ Private 若 GREAT_Lab 成員）連結 | 同 `_navbar.html` 左側 |
| 底部快速導覽 `nav.home-nav` | 同上（桌面版 hover 下拉） | 同 `_navbar.html` 左側 |
| 底部資訊列 | 機構名稱、GREAT Lab 外部連結、背景圖說明與攝影者（Wang, Tong）、GitHub 連結 `https://github.com/AlexLee24/Kinder_web`、email（`home.js` 由 `data-user="kinder" data-domain="astro.ncu.edu.tw"` 組成 `kinder@astro.ncu.edu.tw`） | 外部 |
| Gallery 區 `.home-gallery-section` | 標題 + 副標；`is_admin` 時顯示 `Upload Image` 按鈕（`#homeUploadBtn`）；`#homeGalleryGrid` 由 `home_gallery.js` 以 `GET /api/gallery` 填入，每格套 `span` class（`col-span-N row-span-N`），點擊開 Lightbox | `GET /api/gallery` |
| Lightbox `#homeLightbox` | 大圖、標題、描述、`By <photographer>`、上一張/下一張、底部縮圖 dock、鍵盤 ←/→/Esc；`is_admin` 時有 `Edit`、`Delete` 按鈕 | Delete → `DELETE /api/gallery/<id>`（先 `confirm()`） |
| Edit Modal `#homeEditModal` | 表單 `title*`（≤100）、`description`（≤500）、`photographer`（≤50）、`span`（下拉 1x1/2x1/1x2/2x2） | `PUT /api/gallery/<id>`（JSON） |
| Upload Modal `#homeUploadModal` | 拖放/點擊選檔（`accept="image/*"`，前端檢查 `image/*` 與 ≤10MB）、預覽、`title*`、`description`、`photographer`、`span`；成功訊息後 2 秒自動關閉並重新載入 gallery | `POST /api/gallery/upload`（multipart） |
| 幻燈片（程式殘留） | `home.js` 會尋找 `.slideshow-img` 等元素並 `fetch('/api/slideshow')`，但 `home.html` **沒有任何 slideshow 標記**，`if (!imgEl) return;` 直接返回，所以不會發出請求 | （無） |

- **JS**：`/static/js/home.js`（`url_for('static')`）、`/static/js/home_gallery.js`（`url_for('basic.static')`，同一路由處理）。
- **導向**：見上表；沒有伺服器端 redirect。

### GET `/login` — `basic.login`

- **權限**：公開（已登入者仍可開啟，不會被轉走）。
- **模板**：`app/routes/auth/templates/login.html`（include `_navbar.html`、`_favicon.html`；CSS `css/login.css`，背景 `auth/static/photo/background_login.jpg`）。
- **模板變數**：`current_path='/login'`。
- **頁面區塊與互動**：

| 區塊 | 內容 | 呼叫 / 導向 |
|---|---|---|
| 標題 | Welcome to Kinder / Kilonova Finder | — |
| Google 登入 | `Sign in with Google` 連結 | `GET /auth/google`（`auth.google_login`） |
| Direct Access（本機管理員） | `<form method="POST" action="{{ url_for('auth.admin_login') }}">`：`username`（text, required）、`password`（password, required） | `POST /admin-login`（`auth.admin_login`） |
| 說明清單 | After logging in, you can: View your profile / Access more features / Get personalized experience | — |

- **無 JS 檔**（僅 `_navbar.html` 內嵌 script）。
- **導向**：flash 訊息（登入失敗、需要登入等）由 `_navbar.html` 顯示。

### GET `/profile` — `basic.profile`

- **權限**：需登入；未登入 → `flash('Please log in to view your profile.', 'warning')` → `redirect(url_for('basic.login'))`。
- **模板**：`app/routes/auth/templates/profile.html`（include `_navbar.html`、`_favicon.html`；CSS `css/profile.css`，背景 `auth/static/photo/background_profile.jpg`）。
- **模板變數**：`current_path='/profile'`、`user_groups`（list[str]，已 joined 群組名）、`user_data`（`get_user()` 結果 dict 或 `None`）、`all_groups`（list[dict]：`name`、`description`、`member_count`、`is_member`、`request_status`）。
- **伺服器端流程**：`user_exists(email)` 為真時：`get_user`（含 groups）、`get_user_group_requests`（list → 轉成 `{group_name: status}`）、`get_groups()`（含 members）；並把 `session['user']` 的 `name`、`picture`（非 base64 才寫）、`is_admin`、`is_great_lab_member` 更新。`user_exists` 為假（例如 DB 無列的 session 使用者）→ `user_data=None`、`all_groups=[]`，頁面改用 `session.user` 值。
- **讀取資料表**：`auth.users`、`auth.usr_group`、`auth.groups`。無寫入。
- **頁面區塊與互動**：

| 區塊 | 內容 | 呼叫 / 導向 |
|---|---|---|
| 使用者卡片（左） | 名稱 `#userName` + 編輯鉛筆（開 Edit Name Modal）；email；`Administrator` 徽章（`is_admin`）；頭像 `#profile-avatar-img`（`user_data.picture` 優先），點擊觸發隱藏的 `<input type="file" id="avatar-upload" accept=".jpg,.jpeg,.png,...">` | 頭像 → `uploadAvatar()` → `POST /update-profile`（JSON `{name, picture: <base64 data URI>}`） |
| Account Information | Email；Account Type（`role=='admin'` 或 `is_admin` → Administrator；`role=='guest'` → Guest；否則 User）；Groups 數量；`Member Since`（條件 `user_data.invited_at`，**此欄位不存在於 DB dict，永不顯示**） | — |
| API Key 區（`session.user.role != 'guest'` 才顯示） | (a) 有 key：`<input type="password" id="apiKeyDisplay">` + Show/Hide、Copy、以及 `Reset Requested`（disabled，若 `api_key_request_pending`）或 `Request Reset`；(b) 無 key 但申請中：提示文字；(c) 無 key：`Request API Key` | `requestApiKey()` → `POST /api/profile/request_api_key` |
| Groups 卡片（右） | `all_groups` 逐列：首字母圖示、名稱、成員數、描述；按鈕：`is_member` → `Leave`；`request_status == 'pending'` → `Pending...`（disabled；**DB 實際值為 `'request'`，此分支永不成立**）；否則 `Join` | `askToJoinGroup()` → `POST /api/profile/join_group`；`leaveGroup()` → `POST /api/profile/leave_group`；成功後 1.5 秒 `location.reload()` |
| Edit Name Modal `#editNameModal` | `newName`（required, `maxlength=50`）+ 字數計數；Cancel / Update Name | `updateName()` → `POST /update-profile`（JSON `{name}`） |
| 通知 `#notificationContainer` | `showNotification(msg, type)` 3 秒自動消失 | — |

- **JS**：`/static/js/profile.js`。

---

## API 與動作端點

| 方法 | 路徑 | endpoint | 權限 | 輸入 | 成功回應 | 失敗回應 | 副作用 |
|---|---|---|---|---|---|---|---|
| GET | `/slideshow/image/<filename>` | `basic.slideshow_image` | 公開 | path `filename`（取 `os.path.basename` 防目錄穿越） | 200 檔案內容（`send_from_directory`） | 404（檔案不存在） | 讀 `app/routes/basic/slideshow/<filename>` |
| GET | `/api/slideshow` | `basic.get_slideshow` | 公開 | 無 | `{"slides":[{"url","title","caption","author","fit"}], "interval", "transition"}`；config 檔不存在 → `{"slides":[],"interval":6500,"transition":500}` | JSON 解析失敗 → 未捕捉 → 500 | 讀 `slideshow/slideshow_config.json`；對每張 `enabled != false` 且檔案存在的 slide 產生 `url_for('basic.slideshow_image')` |
| GET | `/api/gallery` | `basic.api_gallery_list` | 公開 | 無 | `{"items":[{"id","title","description","photographer","span","image_url","thumbnail_url"}], "success":true}` | 500 `{"items":[],"success":false,"error":str}` | 讀 `gallery_uploads/` 目錄與每個 `<file>.json` sidecar |
| POST | `/api/gallery/upload` | `basic.api_gallery_upload` | 僅 admin（`session['user']['is_admin']`）；否則 403 `{"success":false,"error":"Unauthorized"}` | multipart：`image`（必填；副檔名 ∈ png/jpg/jpeg/gif/webp；≤10 MB）、`title`（預設檔名）、`description`（''）、`photographer`（''）、`span`（`'col-span-1 row-span-1'`）；form 值含 `|` → 400（全域） | `{"success":true,"message":"Image uploaded successfully","filename":"<name>_<ts><ext>"}` | 400：`No image provided` / `No file selected` / `File type not allowed` / `File too large`；500 `{"success":false,"error":str}` | 寫 `gallery_uploads/<secure_filename 主檔名>_<unix秒><ext>`、縮圖 `<...>_thumb<ext>`（PIL 300×300 LANCZOS，`quality=85`）、sidecar `<file>.json`（`title, description, photographer, span, uploaded_by=session email, uploaded_at=time.time()`） |
| DELETE | `/api/gallery/<item_id>` | `basic.api_gallery_delete` | 僅 admin；否則 403 | path `item_id`（`secure_filename`） | `{"success":true,"message":"Image deleted"}` | 404 `File not found`；500 | 刪除主檔、`replace('.', '_thumb.')` 得到的縮圖、`<file>.json` |
| PUT | `/api/gallery/<item_id>` | `basic.api_gallery_update` | 僅 admin；否則 403 | path `item_id`；JSON 任意子集 `title`、`description`、`photographer`、`span`（無型別/長度驗證；含 `|` → 400） | `{"success":true,"message":"Image updated successfully","data":<metadata>}` | 404 `File not found`；非 JSON body → 415 例外被 `except Exception` 捕捉 → 500；500 | 重寫 `<file>.json`（`ensure_ascii=False, indent=2`） |
| GET | `/gallery/image/<filename>` | `basic.gallery_image` | 公開 | path `filename`（`secure_filename`） | 200 檔案 | 404 | 讀 `gallery_uploads/<filename>`（**任何存在的檔案都可下載，包含 `.json` sidecar**） |
| POST | `/api/profile/join_group` | `basic.api_join_group`（**被 auth 版遮蔽，永不執行**） | 需登入；否則 401 `{"success":false,"error":"Unauthorized"}` | JSON `group_name` | `{"success":true,"message":"Request to join <g> sent."}` | 400 `Invalid group name`（空或群組不存在）；200 `{"success":false,"error":"Request already exists or failed to create."}` | `create_group_request` → `auth.usr_group` upsert `status='request'` |
| POST | `/api/profile/leave_group` | `basic.api_leave_group`（**被遮蔽**） | 需登入；401 | JSON `group_name` | `{"success":true,"message":"Left <g>."}` | 400 `Group name required`；200 `{"success":false,"error":"Failed to leave group."}` | `remove_user_from_group` → DELETE `auth.usr_group` |
| GET | `/auth/google` | `auth.google_login` | 公開 | 無 | 302 → Google 授權頁（`redirect_uri = config.APP_BASE_URL.rstrip('/') + '/auth/google/callback'`，scope `openid email profile`，PKCE S256） | Google metadata 取不到 → 500 | session 寫入 Authlib state / code_verifier / nonce；外部：首次會抓 `https://accounts.google.com/.well-known/openid-configuration` |
| GET | `/auth/google/callback` | `auth.google_callback` | 公開（需 Google 帶回合法 `code`、`state`） | query `code`、`state`（Authlib 驗證） | 302 → `basic.home`（`/`）；flash `Welcome Administrator!` 或 `Welcome <name>!`（success）；`session['user']` 建立、`session.permanent=True` | 無 userinfo 或任何例外：flash `Login failed, please try again.`（error）→ 302 `/login`（**但 session 可能已建立**，見已知問題 1） | 外部：Google token endpoint 交換 code；讀 `auth.users`（`user_exists`、`get_users()` 全表）；既有使用者 `update_user(name, picture, last_login)`；新使用者 `save_user(...)`（**呼叫簽名錯誤 → TypeError**） |
| GET | `/logout` | `auth.logout` | 公開 | 無 | `session.clear()`；flash `You have been logged out.`（info）→ 302 `/` | — | 清除整個 session（含 OAuth state） |
| POST | `/admin-login` | `auth.admin_login` | 公開 | form `username`（trim、不分大小寫比對 `config.ADMIN_USERNAME`）、`password`（精確比對 `config.ADMIN_PASSWORD`） | `session['user']` 設為 `config.ADMIN_LOCAL_EMAIL` 的管理員（見 session 表）；flash `Welcome Administrator!` → 302 `session.pop('next_url')` 或 `/` | flash `Invalid admin credentials.`（error）→ 302 `/login` | 讀 `auth.users`（`get_user`）、`transient.objects`（`check_object_access('greatlab_routes')`）；DB 有列時 `update_user(last_login)` |
| POST | `/update-profile` | `auth.update_profile` | 需登入；JSON 請求 → 401 `{"success":false,"error":"Not logged in"}`；form 請求 → 302 `/login` | JSON 或 form：`name`（必填，trim）、`picture`（選填，trim；可為 base64 data URI，無大小限制） | JSON：`{"success":true,"message":"Profile updated successfully"}`；form：flash `Profile updated successfully!` → 302 `/profile` | 400 `Name cannot be empty.`（form：flash + 302 `/profile`）；404 `User not found.`；500 `Error updating profile.` | `get_users()` 全表；`update_user(email, name=, picture=<新值或原值>, is_admin=<原 is_admin>)` → **會重寫 `roles` 為 50/1**；session `name`、`picture`（非 base64）更新，`session.modified=True` |
| POST | `/api/profile/join_group` | `auth.profile_join_group`（**實際生效**） | 需登入；401 `{"error":"Not logged in"}` | JSON `group_name`（`(data or {}).get('group_name','').strip()`；非 JSON → 415） | `{"success":true,"message":"Request to join \"<g>\" sent. Admin will review."}` | 400 `Group name required`；404 `Group does not exist`；400 `Already a member of this group`；**其後 `get_user_group_requests()` 回傳 list 卻被當 dict `.get` → AttributeError → 500（正常路徑必發生）**；（預期的）400 `Request already pending`、500 `Failed to submit request` | 讀 `auth.groups`、`auth.usr_group`；寫 `auth.usr_group`（實際到不了） |
| POST | `/api/profile/leave_group` | `auth.profile_leave_group`（**實際生效**） | 需登入；401 | JSON `group_name`（trim） | `{"success":true,"message":"Left group \"<g>\""}` | 400 `Group name required`；400 `Not a member of this group`；500 `Failed to leave group` | `user_in_group` 讀；`remove_user_from_group` DELETE `auth.usr_group` |
| POST | `/api/profile/request_api_key` | `auth.profile_request_api_key` | 需登入且非 guest（以 **session** 的 `role` 判斷）；401 `{"error":"Not logged in"}`；403 `{"error":"Guests cannot request an API key"}` | 無 body | `{"success":true,"message":"Request submitted. An admin will review it."}` | 500 `{"error":"Failed to submit request"}` | `UPDATE auth.users SET api_key_requested_at = now()` |
| POST | `/api/generate_key` | `api.generate_key`（**實際生效**） | 公開（無檢查） | 無 | — | 永遠 403 `{"error":"Self-service key generation is disabled. Please request a key from your profile page; an admin will issue it."}` | 無 |
| POST | `/api/generate_key` | `web_api.generate_key`（**被遮蔽，永不執行**；屬 web_api 章節） | 公開 | 無 | — | 403 `{"success":false,"error":"Self-service key generation is disabled. ..."}` | 無 |

補充細節：

- **`/api/gallery` 回傳欄位**：`id` = 檔名；`title` 預設檔名；`photographer` 預設 `'Anonymous'`；`span` 預設 `'col-span-1 row-span-1'`；`image_url = url_for('basic.gallery_image', filename)`；`thumbnail_url` 的判斷式為 `filename + '_thumb' in os.listdir(GALLERY_DIR)`（找 `foo.jpg_thumb`，永遠不存在）→ **實際上永遠等於 `image_url`**。清單排除 `*_thumb.jpg`、`*_thumb.png`，但不排除 `_thumb.jpeg` / `_thumb.gif` / `_thumb.webp`。
- **`gallery_uploads/` 目前內容**（3 個檔案）：`Kinder_dark_jpg_1780826642.jpg`（主圖 2.7 MB）、`Kinder_dark_jpg_1780826642_thumb.jpg`（14 KB）、`Kinder_dark_jpg_1780826642.jpg.json`。Sidecar 格式：
  ```json
  {"title": "Kinder Logo", "description": "", "photographer": "", "span": "col-span-1 row-span-2",
   "uploaded_by": "admin@kinder", "uploaded_at": 1780826642.879717}
  ```
- **`slideshow_config.json` 結構**：`{"interval": 6500, "transition": 500, "slides": [{"filename", "title", "caption", "author", "fit": bool, "enabled": bool}, ...]}`（目前 6 張 slide；`slideshow/` 目錄另有 16 個圖檔）。
- **`google_callback` 詳細順序**：`google.authorize_access_token()` → `token['userinfo']` → 若 `user_exists`：從 `get_users()` 取列，`is_admin`/`role`/`groups` 來自 DB；否則 `role='guest'`，僅當 email 等於 `config.ADMIN_EMAIL` 時 `is_admin=True, role='admin'` → 決定顯示名稱/頭像（DB 優先）→ `session.permanent = True`，寫 `session['user']` → flash → 更新或建立 DB 列 → `pending_invitation` 分支（死碼）→ `next_url` 分支（死碼）→ `redirect(url_for('basic.home'))`。
- **`update_profile` 頭像**：`profile.js` 只允許 `image/jpeg|png|jpg`、≤10 MB，讀成 base64 data URI 後連同目前名稱 POST；伺服器把整個 data URI 存進 `auth.users.picture_url`。之後每個請求 `refresh_user_session` 都會把這個字串讀進 `g.current_user`，navbar 以 `g.current_user.picture` 顯示。

---

## 導向與流程

### A. Google 登入

1. 任一頁 navbar `Login` / 首頁 `Sign In` / 其他 blueprint 的 `redirect(url_for('basic.login'))` → `GET /login`。
2. 點 `Sign in with Google` → `GET /auth/google` → 302 到 Google（callback 固定為 `APP_BASE_URL + /auth/google/callback`）。
3. Google 302 回 `GET /auth/google/callback?code=&state=`。
   - **既有使用者**：session 建立、`update_user(name, picture, last_login)`、flash `Welcome ...!` → `/`。
   - **新使用者**：session 建立、flash `Welcome ...!` → `save_user(...)` 因多餘關鍵字參數丟 `TypeError` → 進入 `except` → 再 flash `Login failed, please try again.` → 302 `/login`。此時 navbar 已顯示為登入狀態（Guest），但 DB 無此人。
   - Google 未回 userinfo / state 驗證失敗 / DB 例外：flash `Login failed, please try again.` → `/login`。
4. `session['pending_invitation']`、`session['next_url']` 全站沒有任何地方寫入，因此登入後**永遠回首頁**。

### B. 本機管理員登入（Direct Access）

1. `/login` 表單 → `POST /admin-login`。
2. 帳密符合 → session 設為 `ADMIN_LOCAL_EMAIL` 管理員 → flash `Welcome Administrator!` → `/`。
3. 不符 → flash `Invalid admin credentials.` → `/login`。

### C. 登出

任一頁使用者選單 `Logout` → `GET /logout` → `session.clear()` → flash `You have been logged out.` → `/`。

### D. 個人資料

1. navbar / 首頁使用者選單 `Profile` → `GET /profile`；未登入 → flash 警告 → `/login`。
2. 改名：Modal → `POST /update-profile`（JSON）→ 成功通知並就地更新文字；失敗顯示 `Error: ...`。
3. 換頭像：選檔 → base64 → `POST /update-profile`（JSON）→ 成功就地更新 `#profile-avatar-img` 與 navbar `.user-avatar`。
4. 群組：`Join` → `confirm()` → `POST /api/profile/join_group` → 成功 1.5 秒後 reload（目前實際會 500，前端顯示 `An error occurred: ...`）；`Leave` → `confirm()` → `POST /api/profile/leave_group` → 成功 reload。管理員之後在 `/admin` 以 `POST /admin/group-requests/<id>/<approve|reject>` 處理（管理面板章節）。
5. API key：`Request API Key` / `Request Reset` → `confirm()` → `POST /api/profile/request_api_key` → 按鈕變為 `Request Pending` / `Reset Requested`；管理員在 `/admin` 以 `POST /admin/api-key/issue` 發放後，使用者重新整理 `/profile` 即可看到（頁面讀 DB 的 `user_data.api_key`，不用重新登入）。Show/Hide、Copy 皆為純前端。

### E. 首頁相簿（僅 admin 可寫）

1. `GET /` → `home_gallery.js` → `GET /api/gallery` → 渲染格狀圖。
2. `Upload Image` → Modal → `POST /api/gallery/upload` → 成功訊息、重新 `GET /api/gallery`、2 秒後關閉。
3. Lightbox `Edit` → Modal → `PUT /api/gallery/<id>` → 就地更新並重繪、`alert('Image updated successfully')`。
4. Lightbox `Delete` → `confirm()` → `DELETE /api/gallery/<id>` → 移除並重繪、`alert('Image deleted successfully')`。

### F. 其他 blueprint 進入本章的方式

- 未登入 → `basic.login`（`/login`），常伴隨 flash `Please log in to ...`。
- 已登入但權限不足（guest / 非 admin / 非 GREAT_Lab）→ `basic.home`（`/`），伴隨 flash `Access denied...`。
- 所有頁面的 navbar Logo → `/`。

---

## 依賴的模組、資料表、檔案與外部服務

### Python 模組

| 模組 | 使用的函式 / 物件 | 用途 |
|---|---|---|
| `modules.database` | `is_db_available()`、`get_db_connection()`（間接） | 首頁 DB offline 判斷；所有 auth DB 存取 |
| `modules.database.auth` | `get_user`、`get_users`、`user_exists`、`save_user`、`update_user`、`get_groups`、`group_exists`、`user_in_group`、`create_group_request`、`remove_user_from_group`、`get_user_group_requests`、`request_api_key`、`check_object_access`；`api_routes.py` 另 import 但未用 `generate_api_key_for_user`、`user_exists` | 使用者/群組/API key |
| `modules.config` | `SECRET_KEY`、`DEBUG`、`HOST`、`PORT`、`APP_BASE_URL`、`GOOGLE_CLIENT_ID`、`GOOGLE_CLIENT_SECRET`、`ADMIN_EMAIL`、`ADMIN_LOCAL_EMAIL`、`ADMIN_USERNAME`、`ADMIN_PASSWORD`（`kinder.env` 皆有設定；SMTP 相關 `SMTP_SERVER/SMTP_PORT/SENDER_EMAIL/SENDER_PASSWORD` 供未被呼叫的 `email_utils`） | 設定 |
| `modules.email_utils` | `send_invitation_email(email, invitation_link)`：以 SMTP STARTTLS 寄純文字邀請信；缺設定回 `False`，例外時印錯誤並回 `None` | **無任何呼叫者** |
| `modules.log_setup` | `setup_logging` | 將 `print()`/stdout 導入每日 log（本章 gallery 錯誤用 `print`） |
| `authlib.integrations.flask_client.OAuth` | `oauth.register('google', ...)`、`authorize_redirect`、`authorize_access_token` | Google OIDC |
| `PIL.Image` | `thumbnail`、`save` | 相簿縮圖 |
| `werkzeug.utils.secure_filename` | 檔名清洗 | 相簿 |

### 資料表

| 資料表 | 讀 | 寫 | 由誰 |
|---|---|---|---|
| `auth.users` | `refresh_user_session`（每請求）、`/profile`、`google_callback`、`admin_login`、`update_profile`、`user_in_group` 等 | `google_callback`（`last_login`、`name`、`picture_url`；新使用者 INSERT 失敗）、`admin_login`（`last_login`）、`update_profile`（`name`、`picture_url`、`roles`）、`request_api_key`（`api_key_requested_at`） | auth / basic |
| `auth.groups` | `/profile`（`get_groups`）、`group_exists`、`user_in_group` | 無 | basic / auth |
| `auth.usr_group` | `get_user`（groups）、`get_user_group_requests`、`user_in_group`、`get_groups`（members） | `create_group_request`（upsert `status='request'`）、`remove_user_from_group`（DELETE） | auth（basic 版被遮蔽） |
| `transient.objects` | `check_object_access('greatlab_routes', ...)` | 無 | `admin_login` |
| `auth.invitations`、`auth.system_settings`、`auth.images` | 本章未直接使用（invitations/system_settings 由 `_ensure_extra_tables` 建立；`images` 在 DDL 中但程式未用） | | |

### 檔案 / 目錄

| 路徑 | 用途 |
|---|---|
| `app/routes/basic/slideshow/slideshow_config.json` + 16 個圖檔 | `/api/slideshow`、`/slideshow/image/<f>`（目前無前端使用） |
| `app/routes/basic/gallery_uploads/` | 相簿主圖、`_thumb` 縮圖、`.json` sidecar；`os.makedirs(..., exist_ok=True)` 於 import 時建立 |
| `app/routes/basic/icon/` | Logo / favicon（透過 `/static/icon/...` fallback） |
| `app/routes/basic/static/photo/background.jpg`、`app/routes/auth/static/photo/background_login.jpg`、`background_profile.jpg` | 頁面背景 |
| `app/log/` | logging（`log_setup`） |
| `kinder.env` | 環境變數 |

### 外部服務

- Google：`https://accounts.google.com/.well-known/openid-configuration`、授權頁、token endpoint（Authlib）。
- PostgreSQL（`Kinder` 資料庫，`PG_HOST/PG_PORT/PG_USER/PG_PASSWORD`）。
- SMTP（`SMTP_SERVER:SMTP_PORT`）：僅 `email_utils` 定義，未被呼叫。
- 外部連結：GREAT Lab Google Sites、Lulin Observatory weather、GitHub repo。

---

## 前端檔案

### 模板

| 檔案 | 說明 |
|---|---|
| `app/routes/basic/templates/home.html` | 首頁；不含 navbar；載入 `css/home.css`、`js/home.js`、`js/home_gallery.js` |
| `app/routes/basic/templates/_navbar.html` | 全站導覽列 + flash + 內嵌 script；載入 `css/_theme.css`、`css/_navbar.css` |
| `app/routes/basic/templates/_favicon.html` | favicon `<link>` |
| `app/routes/auth/templates/login.html` | 登入頁；載入 `css/login.css` |
| `app/routes/auth/templates/profile.html` | 個人資料頁；載入 `css/profile.css`、`js/profile.js` |

### CSS

| 檔案 | 行數 | 備註 |
|---|---|---|
| `app/routes/basic/static/css/_theme.css` | 87 | 全站設計 token（TASA Explorer 字型 via Google Fonts、金色 accent `#C5A059`）；註解明言「除首頁外每頁載入」 |
| `app/routes/basic/static/css/_navbar.css` | 723 | header 固定 60px；未使用 `--navbar-bg-image` |
| `app/routes/basic/static/css/home.css` | 1669 | 首頁；`.db-offline-banner`；背景 `../photo/background.jpg`；無 slideshow 樣式 |
| `app/routes/auth/static/css/login.css` | 227 | 背景 `../photo/background_login.jpg`；`.admin-login-*` |
| `app/routes/auth/static/css/profile.css` | 889 | 背景 `../photo/background_profile.jpg` |

### JS 與其呼叫的 API

| 檔案 | 呼叫的 API | 其他行為 |
|---|---|---|
| `app/routes/basic/static/js/home.js` | `GET /api/slideshow`（**因缺少 `.slideshow-img` 元素而提前 return，實際不會呼叫**） | email 去混淆、手機導覽開關、子選單手風琴、流星 canvas 動畫（`requestAnimationFrame`，10–300 秒隨機生成） |
| `app/routes/basic/static/js/home_gallery.js` | `GET /api/gallery`、`POST /api/gallery/upload`（multipart）、`PUT /api/gallery/<id>`（JSON）、`DELETE /api/gallery/<id>` | Lightbox / dock / 鍵盤導覽、編輯與上傳 Modal、拖放上傳、前端檔案型別與 10 MB 檢查、`alert()` / `confirm()` |
| `app/routes/auth/static/js/profile.js` | `POST /update-profile`（JSON：`{name}` 或 `{name, picture}`）、`POST /api/profile/join_group`、`POST /api/profile/leave_group`、`POST /api/profile/request_api_key` | Edit Name Modal、字數計數、頭像 base64 轉換、通知系統、API key Show/Hide/Copy（`document.execCommand('copy')`）；`askToJoinCustomGroup()` 參照不存在的 `#joinGroupName`/`#joinReason` 且未呼叫任何 API（死碼） |
| `_navbar.html` 內嵌 script | 無 | 漢堡/下拉/scrolled/flash 自動隱藏 |

---

## 已知問題與注意事項

### 高嚴重度（功能性錯誤）

1. **新使用者 Google 登入必定寫入失敗，且造成「幽靈登入」。** `auth_routes.py:159` 呼叫 `save_user(email=, name=, picture=, is_admin=, role=, last_login=, invited_at=)`，但 `modules/database/auth.py:140` 的簽名是 `save_user(email, name='', picture_url='', is_admin=False)`，`picture`/`role`/`last_login`/`invited_at` 皆為未知關鍵字 → `TypeError` → 被外層 `except Exception` 捕捉 → flash `Login failed` 並轉回 `/login`。但 `session['user']` 在第 137 行已寫入，所以使用者實際處於登入狀態（Guest、無 DB 列、`g.current_user` 不存在、`/profile` 顯示不到群組）。`admin_routes.py:69` 的 `add_user` 也用同樣錯誤簽名（管理面板章節）→ **目前網頁上沒有任何可用路徑能新增 `auth.users` 列**，只能直接操作資料庫。
2. **群組加入申請 API 必回 500。** 實際生效的 `auth.profile_join_group` 在第 318–319 行把 `get_user_group_requests()`（回傳 `list[dict]`）當 dict 呼叫 `.get(group_name)` → `AttributeError`。凡群組存在且使用者尚非成員的正常請求都會 500。`basic.api_join_group` 雖能運作但永遠不會被路由到。
3. **群組申請狀態字串不一致，流程整條斷裂。** DB 的 `usr_group.status` 只允許 `'request'/'joined'/'rejected'`，但 `profile.html:146` 與 `auth_routes.py:319` 檢查 `'pending'` → 「Pending...」按鈕永不顯示，使用者可重複送出。管理面板端 `handle_group_request(request_id:int, action)` 以整數呼叫 `get_group_request(email, group_name)`、`update_group_request_status(email, group_name, status)` 並使用 `'approved'` 狀態 → 簽名與 CHECK 皆不符（屬管理面板章節，但起點在本章）。
4. **`/update-profile` 造成權限變更。** `update_user(..., is_admin=current_data.get('is_admin'))` 會把 `roles` 重寫為 50 或 1：guest（0）改名/換頭像後升為 user（1）；super_admin（99）會被降為 50。session 的 `role` 不會同步，效果在下次登入或 API key 驗證（讀 DB）時生效。

### 重複註冊 / 路由遮蔽

5. `POST /api/profile/join_group`、`POST /api/profile/leave_group`：`auth_bp` 先註冊 → `auth.*` 生效；`basic.api_join_group` / `basic.api_leave_group` 為死碼。兩版行為差異：basic 版回 `{"success":false,"error":...}`（200）且不檢查是否已是成員；auth 版回 `{"error":...}` 並帶 400/404/500 狀態碼、檢查成員與待審狀態（但有第 2 點的 bug）。
6. `POST /api/generate_key`：`api_blueprint` 先於 `web_api_bp` 註冊 → `api.generate_key` 生效（回 `{"error": ...}` 403）；`web_api.generate_key`（回 `{"success": false, "error": ...}` 403）永不執行。兩者都只是「已停用」訊息。
7. `/static/<path:filename>`：app 層 `static` 與 `basic.static`、`auth.static`（及其他 blueprint）重複；app 層生效。`_favicon.html`、`home.html` 混用 `url_for('static')` 與 `url_for('basic.static')`，結果相同。

### 死程式碼 / 不存在的目標

8. `google_callback` 的 `session['pending_invitation']` 分支：全站沒有任何地方設定此 key，且 `url_for('admin.accept_invitation')` **端點不存在**（若被觸發會 `BuildError` → 被 except 吃掉 → 顯示 `Login failed`）。
9. `session['next_url']`：`google_callback`、`admin_login` 都會 `pop`，但全站沒有任何地方設定 → 登入後永遠回首頁。
10. `auth_routes.update_user_session_groups()`（掛在 `auth_bp.update_user_session_groups`）無呼叫者；`admin_routes.py` 有另一份同名實作。
11. `api_routes.py` import 了 `request`、`session`、`generate_api_key_for_user`、`user_exists` 但都未使用。
12. `home.js` 的 slideshow 區段、`/api/slideshow`、`/slideshow/image/<filename>` 與 `slideshow/` 目錄的 16 張圖：`home.html` 已無 slideshow 標記，前端不會呼叫。
13. `profile.js::askToJoinCustomGroup()`：對應表單元素不存在、只 `setTimeout` 假成功。
14. `modules/email_utils.py::send_invitation_email` 與 `auth.invitations` 相關 DB 函式：無任何路由呼叫（`admin_routes` 僅 import 及列出 `get_invitations()`）。
15. `auth.images` 資料表（BYTEA 頭像）未被程式使用；頭像以 base64 存於 `auth.users.picture_url`。
16. `admin_login` 內 `check_object_access('greatlab_routes', admin_email)` 查詢 `transient.objects` 中名為 `greatlab_routes` 的物件，為舊制殘留；下一請求 `refresh_user_session` 會因 `is_admin` 重新算出 `is_great_lab_member=True`。
17. `profile.html` 的 `Member Since` 區塊依賴 `user_data.invited_at`，但 `_user_row_to_dict` 不產生此鍵（DB 欄位為 `join_date`）→ 永不顯示。

### 相簿（Gallery）邏輯

18. `thumbnail_url` 判斷式錯誤（`filename + '_thumb' in os.listdir(...)`）→ 永遠回傳原圖 URL，格狀圖與 dock 都載入全尺寸圖（目前 2.7 MB）；縮圖檔實際存在卻從未被使用。另 `os.listdir` 在迴圈內重複呼叫。
19. 縮圖命名用 `image_path.replace('.', '_thumb.')`（取代**所有**點）：檔名含多個點或目錄路徑含點時會產生錯誤路徑；列表只排除 `_thumb.jpg`/`_thumb.png`，`.jpeg`/`.gif`/`.webp` 的縮圖會被當成獨立作品列出。
20. `GET /gallery/image/<filename>` 不限制副檔名 → `.json` sidecar 可被任何人下載（含 `uploaded_by` 管理員 email）。
21. 上傳 `title` 前端必填但後端允許空字串；`PUT` 更新無任何型別/長度驗證；非 JSON body 的 415 例外被轉為 500。
22. 沒有設定 `MAX_CONTENT_LENGTH`，上傳大小僅靠程式內 `file.tell()` 檢查（已讀入記憶體/暫存後才檢查）。

### Session / 權限同步

23. `refresh_user_session` 只同步 `is_admin`、`is_great_lab_member`、`picture`；`role`、`groups`、`name`、`api_key` 停留在登入當下的值。管理員變更某人 role 後，該使用者在重新登入前仍被視為原角色（例如仍是 guest → `/api/profile/request_api_key` 403、navbar 仍顯示 (Guest)）。
24. `session['user']['api_key']` 被寫入客戶端 cookie（簽章但未加密），且程式沒有任何地方讀它（profile 頁讀 DB）。
    - 附帶（跨章節）：`update_user()` 的欄位對應表沒有 `role` 鍵，`update_user(email, role=..., is_admin=...)` 中的 `role=` 會被靜默忽略，只有 `is_admin` 生效（→ `roles` 50/1）。因此管理面板 `/admin/update-role` 選 `guest` 實際會寫成 `roles=1`（user）；`roles=0`（guest）只會出現在 DB 預設值或手動設定的列。
25. `admin_login` 產生的 session 沒有 `groups` key（目前沒有模板/路由讀 `session.user.groups`，暫無影響）。
26. `open_registration` 系統設定（管理面板可切換）在 `google_callback` 中完全未被檢查，登入流程不受其影響。
27. `admin_login`：若 `ADMIN_USERNAME`/`ADMIN_PASSWORD` 環境變數缺失（`None → ''`），直接 POST 空 `username`/`password` 即可通過比對；密碼比對為一般 `==`（非常數時間）。目前 `kinder.env` 有設定這兩個值。
28. `refresh_user_session` 每個非 `/static` 請求對登入使用者做 2 次 SQL（包含 `/api/*`、圖片路由），並整列讀入含 base64 頭像的 `picture_url`（最大可達約 13 MB）。`google_callback`、`update_profile` 使用 `get_users()` 載入全部使用者只為取一列。

### 模板 / 前端小問題

29. `_navbar.html` 含 `<head>`，被 include 在 `<body>` 內 → 每頁產生第二個 `<head>`（瀏覽器可容忍）。
30. `_navbar.html` dropdown-toggle 重複 `class` 屬性 → active 樣式失效；Private 的 active 判斷用 `/detect_results`，實際路徑為 `/detect`；`--navbar-bg-image` 指向不存在的 `photo/navbar.jpg`（未被 CSS 使用，故無 404 請求）。
31. HTML 註解內的 `{{ url_for(...) }}`（`_navbar.html` 的 `astronomy_tools.mount_3d`、`home.html` 的 wordmark）仍會被 Jinja 執行，若日後移除對應 endpoint 會讓全站 500。
32. 名稱長度限制不一致：`profile.html` input `maxlength=50`、`profile.js` 檢查 >100、字數顏色門檻 75/90、後端無限制。
33. `login.html` 在已登入狀態仍顯示登入表單與 Google 按鈕；`/login`、`/profile` 定義在 `basic_bp`，模板卻在 `auth/templates/`（僅命名分散，功能正常）。
34. `_block_pipe_in_api_params` 使相簿標題/描述/攝影者或群組名含 `|` 的請求一律 400；而 `/update-profile`（非 `/api/`）不受此限制。
35. `modules/database/auth.py` 於 import 時執行 DDL（`ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS api_key_requested_at`），需要 DB 帳號具備 ALTER 權限；失敗只記 warning。
36. 本章檔案內沒有任何 `TODO` / `FIXME` 標記。
