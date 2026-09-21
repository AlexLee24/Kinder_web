# Kinder Web 程式架構說明（2026-09 重構後）

> 目的：讓任何人在 5 分鐘內知道「某個功能的程式在哪裡」、「新增一個頁面要動哪些檔案」、「哪些東西不能亂動」。
> 重構前的功能與導向完整記錄在 `docs/FEATURES.md`（重構**未改變任何功能行為**，見 §7 驗證）。

---

## 1. 一張圖看懂

```
kinder_web_blueprint/
├── main.py / run.py       開發伺服器入口：uv run python main.py（log 同時輸出 terminal 與 app/log/）
├── wsgi.py                gunicorn 入口：gunicorn wsgi:app
├── kinder.env             設定與密碼（git 忽略；範本 kinder.env.example）
├── pyproject.toml         套件（uv）、pytest 設定
├── scripts/sync_detect.sh 從 DETECT 專案更新 app/vendor/DETECT
├── docs/                  FEATURES.md（功能記錄）、ARCHITECTURE.md（本文）、database/（schema）、baseline/（重構前基準）、features/（逐章細節）
├── tests/                 pytest；tools/ 內有路由表與冒煙測試工具；smoke_baseline.json 為回歸基準
└── app/                                   ← Flask 套件，一切從 create_app() 開始
    ├── __init__.py        create_app(start_jobs=True)：建 app、掛 hooks、註冊 blueprint、啟動背景工作
    ├── main.py            舊入口相容層（cd app && gunicorn main:app 仍可用）
    ├── config.py          Config 單例（讀 kinder.env）
    ├── paths.py           所有磁碟路徑常數 + 把 vendor 套件加進 sys.path（要第一個 import）
    ├── extensions.py      OAuth 物件與 Google 用戶端
    ├── core/              跨區塊的 web 基礎設施
    │   ├── auth.py            refresh_user_session、is_admin() 等判斷、login_required / admin_required 裝飾器
    │   ├── hooks.py           Host 白名單、'|' 阻擋、隔離 header、access log、錯誤處理（順序固定）
    │   ├── static_files.py    統一的 /static/<path> 路由（依固定順序在各 blueprint 的 static/ 找檔）
    │   ├── log_setup.py       每日 log 檔、stdout 導入 log
    │   ├── request_validation.py  get_int_arg / get_float_arg / ParamOutOfRangeError
    │   ├── converters.py      URL converter <alpha:>
    │   └── template_filters.py  Jinja filter regex_search
    ├── db/                PostgreSQL 存取層（原 modules/database）
    │   ├── __init__.py        連線池 get_db_connection()、get_tns_db_connection()、OBJECT_COMPAT_COLS
    │   ├── auth.py            auth.* 表：使用者、群組、API key、設定、權限
    │   ├── transient.py       transient.* 表：物件、光度、光譜、評論、DETECT 結果、TNSObjectDB
    │   ├── obs.py             obs.* 表：觀測目標、觀測日誌
    │   └── catalog.py         cat.* 表：DESI / Lens cone search、NED 快取
    ├── services/          領域邏輯（不碰 Flask request；依主題分包）
    │   ├── tns/               auto_tns_download（每小時/每日同步）、manual_tns_download、tns_gap_filler
    │   ├── photometry/        download_phot（私有檔，git 忽略）、phot_scheduler、data_processing（繪圖）
    │   ├── detect/            detect_pipeline（呼叫 vendor/DETECT）、detect_cross_match
    │   ├── planning/          obsplan（可見度圖）、observation_script / trigger_script（ACP 腳本）、trigger_send（Slack）
    │   ├── astro/             astronomy_calculator、coordinate_converter、date_converter、ext_M_calculator、filter_colors、spectral_lines
    │   ├── jobs/              scheduler（APScheduler + 常駐執行緒）、backup、db_monitor、job_status、scheduler_state
    │   └── notifications/     email_utils、gcn_alert（停用）
    ├── blueprints/        網站區塊：每個資料夾 = 路由 + templates/ + static/
    │   ├── __init__.py        register_blueprints(app)：註冊順序在這裡（有意義，見 §4）
    │   ├── basic/             首頁、登入頁、個人頁、相簿；_navbar.html / _favicon.html 全站共用
    │   ├── auth/              routes.py（Google OAuth、本機登入、profile 動作）、admin/（管理面板）、web_log.py、database_status.py
    │   ├── marshal/           routes.py（物件列表）、objects/（物件詳細頁 + 每物件 API，依主題拆：page / api / photometry / spectroscopy / comments / permissions / ned）
    │   ├── detect/            routes.py（頁面與審核 API）、cache.py（頁面/LC/tracker 快取）、payload.py（審核資料組裝）
    │   ├── astronomy_tools/   tools / planner / lc_plotter / exposure_time_calculator / finding_chart(+_render) / public_api
    │   ├── planners/          planner 頁面的 templates/static（route 在 astronomy_tools）+ /ov_plot 圖檔
    │   ├── private_area/      daily_trigger / epessto / documents / lab_info / targets / observation_logs / page_perms / debug
    │   ├── web_api/           objects / tns / detect / observation_v1 / keys / legacy_api（api blueprint）
    │   └── games/             1A2B
    ├── resources/         放在 git 內的小資料檔：kn_lc_mag.txt、filter_colors.json（後備）
    ├── vendor/            CASTOR/（git clone，忽略）、DETECT/（rsync 副本，追蹤）— 見 vendor/README.md
    ├── data/              執行期資料（忽略）：TNS 工作檔、phot_cache、shared_plots、backups、狀態 JSON、譜線快取
    └── log/               每日 log、.background_jobs.lock、.job_status.json（忽略）
```

**找東西的規則**：
1. 頁面 / API → `docs/FEATURES.md` §2 的網站地圖告訴你是哪個 blueprint → `app/blueprints/<名稱>/`。大 blueprint 內依主題拆檔，檔名就是主題；`helpers.py` 是該區塊共用的內部函式；`__init__.py` 定義 blueprint 物件並 import 各主題模組（import 順序 = 路由註冊順序）。
2. 資料表存取 → `app/db/<schema>.py`。
3. 排程 / 背景工作 → `app/services/jobs/scheduler.py`（一張表列出所有 job）。
4. 路徑、環境變數 → `app/paths.py`、`app/config.py`、`kinder.env.example`。
5. 權限判斷 → `app/core/auth.py`。

---

## 2. 啟動流程（`app/__init__.py::create_app`）

與重構前 `app/main.py` 的順序完全相同，只是搬進函式：

1. `setup_logging(app/log)` — 之後所有 `print()` 都進日誌。
2. 建 `Flask(__name__, static_folder=None)`，設定 secret key、`ProxyFix(x_proto, x_host)`、session cookie（SameSite=Lax、非 DEBUG 才 Secure、30 天）。
3. `check_db_connection()`、`init_connection_pool()`（含 `_ensure_extra_tables()` 的啟動期 DDL，失敗只 warning）。
4. 註冊 `<alpha:>` converter、`/static/<path>` 路由、Jinja filter。
5. `oauth.init_app(app)`。
6. `register_hooks(app)`：before_request 順序 = Host 白名單 → `refresh_user_session` → 計時 → `/api/` 的 `|` 阻擋；errorhandler；after_request headers、access log。
7. `register_blueprints(app)`（順序固定）。
8. `start_background_jobs(app)`（`start_jobs=False` 可略過：測試、一次性腳本）。

入口：`run.py`（開發）、`wsgi.py`（gunicorn，從專案根目錄執行）、`app/main.py`（相容舊的 `cd app && gunicorn main:app`）。

---

## 3. 慣例

| 主題 | 規則 |
|---|---|
| import | 一律絕對匯入 `from app.db.transient import ...`、`from app.services.tns.auto_tns_download import ...`。不要再用 `sys.path` 技巧。vendor 套件維持原名（`castor`、`function`），由 `app/paths.py` 加入 sys.path。 |
| 路徑 | 磁碟路徑一律從 `app.paths` 取（`DATA_DIR`、`LOG_DIR`、`RESOURCES_DIR`、`TNS_WORK_DIR`…），不要再寫 `os.path.dirname(__file__), '..', 'data'`。blueprint 自己資料夾內的東西（`templates/`、`slideshow/`、`tutorials/`）才用 `__file__` 相對。 |
| 設定 | 環境變數集中在 `kinder.env`；程式讀 `app.config.config`。新的鍵要同步加進 `kinder.env.example` 與 `docs/FEATURES.md` §7。 |
| 權限 | JSON API 用 `@login_required` / `@admin_required`（`app.core.auth`），頁面用 `*_page` 版本。裝飾器放在 `@bp.route` 之下。既有 route 仍有 66 處樣式不一的 inline 判斷（回應格式各異），要改時先確認前端 JS 依賴的回應格式。 |
| 新增頁面 | 見 §5。 |
| 靜態檔 | 放在自己 blueprint 的 `static/`，模板用 `url_for('static', filename='css/x.css')`。**檔名在全站共用一個命名空間**（`css/x.css` 在 9 個 static 目錄中依 `core/static_files.py` 的順序找第一個），新檔名請加區塊前綴避免撞名。 |
| 模板 | 每個 blueprint 的 `templates/` 都在 Jinja 搜尋路徑內，所以模板名也是全站共用命名空間（`admin.html`、`detect_home.html`…）。共用 partial 在 `basic/templates/_navbar.html`、`_favicon.html`。 |
| DB | 讀寫用 `with get_db_connection() as conn:`（自動歸還、自動 rollback 髒交易）；`get_tns_db_connection()` 需手動 `close()`。 |
| 背景工作 | 加在 `services/jobs/scheduler.py` 的表裡，並用 `_tracked(job_id, fn)` 包起來，管理頁才看得到狀態。 |
| 死程式碼 | 不留「以防萬一」的舊檔；git 歷史有。本次已刪除 6 個無人引用的模組（§6）。 |
| 測試 / lint | `python -m pytest -q`；`ruff check app tests`（設定在 `pyproject.toml`）。改了路由行為就重新擷取 `tests/smoke_baseline.json`（git 忽略，含真實 email）並在 commit 訊息說明。 |

---

## 4. 需要小心的地方（不要亂動）

1. **Blueprint 註冊順序**（`app/blueprints/__init__.py`）：`/api/profile/join_group`、`/api/profile/leave_group` 同時定義在 `auth` 與 `basic`，`/api/generate_key` 同時定義在 `api` 與 `web_api`，先註冊者生效。順序改了行為就變。
2. **`/static` 搜尋順序**（`app/core/static_files.py`）：決定同名檔誰被服務。
3. **before_request 順序**（`app/core/hooks.py`）：Host 檢查必須最先。
4. **`app/paths.py` 必須是 `app` 套件第一個 import**（`app/__init__.py` 第一行），否則 `import castor` / `import function` 會失敗，`DETECT_DATA_DIR` 預設值也不會設好。
5. **`app/vendor/`**：CASTOR 用 `git -C app/vendor/CASTOR pull` 更新；DETECT 用 `scripts/sync_detect.sh`。不要手改裡面的檔案。
6. **`app/services/photometry/download_phot.py` 不在 git 內**（含外站爬取憑證邏輯）；部署與備份要另外攜帶。它現在改用 `from app.db import ...`（原本裸 `from database import` 會造成第二個連線池，已修正）。
7. **DEBUG=True** 會關掉所有背景工作、縮小連線池、關閉 Secure cookie、Slack 改打測試頻道。
8. `app/blueprints/marshal/objects` 的 blueprint 名稱是 `marshal_bp`（歷史因素），模板裡 `url_for('marshal_bp.object_detail_generic', ...)` 都指它；不要改名。

---

## 5. 新增一個頁面 / API 的步驟

1. 決定屬於哪個區塊，在 `app/blueprints/<區塊>/` 加一個主題模組（或加進既有主題檔）。
2. 在檔頭 `from . import <區塊>_bp`（大區塊）或直接用 `routes.py` 內的 bp（小區塊）；寫 `@<bp>.route(...)`，下面加 `@login_required` / `@admin_required` 等。
3. 若是大區塊（有 `__init__.py` 列 import 的），把新模組加進 `__init__.py` 最後那行 `from . import ...`。
4. 模板放 `templates/`，靜態檔放 `static/css|js|photo/`，檔名加區塊前綴。
5. 需要 DB：在 `app/db/<schema>.py` 加函式；需要領域邏輯：放 `app/services/<主題>/`。
6. 需要導覽入口：改 `app/blueprints/basic/templates/_navbar.html`（以及首頁 `home.html` 的行動版選單）。
7. 跑 `python -m pytest -q`；`tests/test_app_factory.py::test_route_count_is_stable` 的數字要跟著更新，並重新擷取冒煙基準。
8. 在 `docs/FEATURES.md` 對應章節補一行。

---

## 6. 新舊路徑對照

### 6.1 模組

| 舊（`app/modules/...`） | 新 |
|---|---|
| `config.py` | `app/config.py` |
| `log_setup.py`、`request_validation.py` | `app/core/log_setup.py`、`app/core/request_validation.py` |
| `database/{__init__,auth,catalog,obs,transient}.py` | `app/db/…`（內容不變） |
| `auto_tns_download.py`、`tns_gap_filler.py` | `app/services/tns/…` |
| `Manual_tns_download_snoozed.py` | `app/services/tns/manual_tns_download.py`（改名） |
| `download_phot.py`（未追蹤）、`phot_scheduler.py`、`data_processing.py` | `app/services/photometry/…` |
| `detect_pipeline.py`、`detect_cross_match.py` | `app/services/detect/…` |
| `obsplan.py`、`observation_script.py`、`trigger_script.py`、`trigger_send.py` | `app/services/planning/…` |
| `astronomy_calculator.py`、`coordinate_converter.py`、`date_converter.py`、`ext_M_calculator.py`、`filter_colors.py`、`spectral_lines.py` | `app/services/astro/…` |
| `backup.py`、`db_monitor.py`、`job_status.py`、`scheduler_state.py` | `app/services/jobs/…`；`main.py` 的排程區塊 → `app/services/jobs/scheduler.py` |
| `email_utils.py`、`GCN_alert.py` | `app/services/notifications/email_utils.py`、`gcn_alert.py`（改名） |
| `web_data/kn_lc_mag.txt` | `app/resources/kn_lc_mag.txt` |
| `_spectral_lines_cache.json` | `app/data/_spectral_lines_cache.json` |
| `CASTOR/`、`DETECT/` | `app/vendor/CASTOR/`、`app/vendor/DETECT/` |
| `database_deprecated.py`、`obsplan_old.py`、`Trigger_LOT_SLT.py`、`object_data.py`、`detect_image.py`、`TNS_object_fetch.py` | **刪除**（無任何引用；git 歷史 `c7f91a4` 可取回） |
| `main.py` 的 `refresh_user_session` / OAuth 設定（原在 `routes/auth/auth_routes.py`） | `app/core/auth.py`、`app/extensions.py` |
| `main.py` 的 hooks / static route / converter / filter | `app/core/hooks.py`、`static_files.py`、`converters.py`、`template_filters.py` |
| `_Kinder_Database/` | `docs/database/` |

### 6.2 路由檔（`app/routes/...` → `app/blueprints/...`）

| 舊 | 新 |
|---|---|
| `routes/__init__.py::register_routes` | `blueprints/__init__.py::register_blueprints` |
| `basic/basic_routes.py` | `basic/routes.py` |
| `auth/auth_routes.py` | `auth/routes.py`（OAuth 物件與 session 同步函式移出） |
| `auth/admin_routes.py`（1004 行） | `auth/admin/`：`panel`、`users`、`groups`、`api_keys`、`settings`、`maintenance`、`tns`、`detect`、`scheduled_jobs`、`helpers` |
| `auth/web_log_routes.py`、`auth/database_status_routes.py` | `auth/web_log.py`、`auth/database_status.py` |
| `marshal/marshal_routes.py` | `marshal/routes.py` |
| `marshal/object_routes.py`（2194 行） | `marshal/objects/`：`page`、`api`、`photometry`、`spectroscopy`、`comments`、`permissions`、`ned`、`helpers` |
| `detect/detect_routes.py`（1192 行） | `detect/`：`routes`、`cache`、`payload`、`helpers` |
| `astronomy_tools/astronomy_tools_routes.py`（2371 行） | `astronomy_tools/`：`tools`、`planner`、`lc_plotter`、`exposure_time_calculator`、`finding_chart`、`finding_chart_render`、`public_api`、`helpers` |
| `private_area/private_area_routes.py`（2154 行） | `private_area/`：`daily_trigger`、`epessto`、`documents`、`lab_info`、`targets`、`observation_logs`、`page_perms`、`legacy_pages`、`helpers` |
| `web_api/web_api_routes.py`（1044 行） | `web_api/`：`objects`、`tns`、`detect`、`observation_v1`、`keys`、`helpers` |
| `api_routes.py` | `web_api/legacy_api.py`（blueprint 名稱仍是 `api`） |
| `games/games_routes.py`、`planners/planners_routes.py` | `games/routes.py`、`planners/routes.py` |

拆檔規則：route 函式依主題分到各模組；非 route 的共用函式與模組層級狀態（快取 dict、速率限制表…）放 `helpers.py`；用 `global` 改寫的狀態變數與該函式同檔。endpoint 名稱（blueprint 名 + 函式名）全部不變，所以模板與 JS 不用改。

### 6.3 部署指令

| 舊 | 新 |
|---|---|
| `python app/main.py` | `python run.py`（`python app/main.py` 仍可用） |
| `cd app && gunicorn ... main:app` | 在專案根目錄 `gunicorn ... wsgi:app`（舊指令仍可用） |
| `python -m pytest test_detect_pages.py` | `python -m pytest -q`（測試在 `tests/`） |

---

## 7. 重構做了什麼、沒做什麼

**做了（結構）**：application factory；`app` 成為正規套件、絕對匯入、移除 `sys.path` 技巧；路徑集中在 `paths.py`；模組依主題分包；6 個 1000–2400 行的路由檔拆成 45 個主題模組；OAuth / session 同步 / hooks / 靜態檔路由從 `main.py` 與 `auth_routes.py` 抽到 `core/`、`extensions.py`；背景排程獨立成 `services/jobs/scheduler.py`；vendor 套件集中到 `app/vendor/`；schema 文件移到 `docs/database/`；新增 `tests/`、`kinder.env.example`、`run.py`、`wsgi.py`；`.gitignore` 依新路徑重寫並停止忽略 `tests/`。

**做了（程式內容）**：85 個 route 開頭一模一樣的 inline 權限判斷改成 `@admin_required` / `@login_required`（回應 byte 級相同）；刪除 6 個無人引用的模組與 4 條無模板的 `/private/*` 死路由；`download_phot.py` 改用正規匯入（消除第二個連線池）；`filter_colors.json` 加 git 內後備檔；Games 排行榜路徑改為 `app/data/`；ruff 移除未使用 / 重複的 import；`web_api` blueprint 不再宣告不存在的 templates/static。

**清理階段修正的 bug**（`docs/FEATURES.md` §10 打 ✅ 的項目）：新使用者建檔（`save_user` 簽名）、群組申請整條流程（API、狀態字串、管理面板按鈕）、角色寫入（`update_user(role=)`，不降級 super_admin）、`retire_stale_followups` 的 MJD 處理、`update_target_mags` 的資料表名、`detect_page_prewarm` 排程的 app context、`trigger_script` 太暗目標的崩潰、`web_api` 的 logger、Documents 設定抹掉 `.env`、Observation Log 的 priority/program、手動 TNS 下載的環境變數名、`admin.accept_invitation` 死分支。

**刻意沒做**：§10 其餘項目（安全 / 權限政策、flag 三種定義、NED host 持久化、同步重任務等）需要決定行為才能改；剩餘 66 處樣式不一的 inline 權限判斷；未合併 `observation_script` / `trigger_script` 的重複邏輯；前端只改了群組申請按鈕與 Observation Log 的送出欄位。

**驗證**（詳見 `docs/FEATURES.md` 附錄 B）：
- 路由表：重構後 245 條規則（250 − 4 條死頁面 − 1 條無效的 `web_api.static` − 群組申請 URL 由 `/admin/group-requests/<id>/<action>` 改為 `/admin/group-requests/<action>`），其餘 endpoint → 函式對應完全相同（`tests/tools/dump_url_map.py`；兩份路由表在 `docs/baseline/`）。
- 逐頁 GET 冒煙測試：4 種身分 × 133 個 URL = 532 組回應的狀態碼 / Content-Type / 渲染模板 / redirect 目標完全相同（`tests/tools/smoke_pages.py --compare`），拆檔後與加裝飾器後各比對一次。
- `tests/`：17 個結構 / 頁面測試通過（含原 `test_detect_pages.py` 的 7 個）；`ruff check --select F` 無未定義名稱。
- 只有 GET 被自動驗證；POST / DELETE 端點靠「程式碼逐函式原樣搬移 + endpoint 對應相同」保證，建議在正式環境部署後手動點一輪管理面板與 Daily Trigger。

---

## 8. 視覺設計系統（2026-09）

依 Apple Human Interface Guidelines（`apple-design-skill`）與 UI/UX Pro Max 的「Data-Dense Dashboard」建議重新設計外觀，原則：系統字體（SF / Inter）、4/8pt 間距、44pt 觸控目標、每個畫面只有一個醒目主要動作（金色）、藍色連結、可見的鍵盤 focus、`prefers-reduced-motion`、深色玻璃材質。

| 檔案 | 內容 |
|---|---|
| `app/blueprints/basic/static/css/_theme.css` | 所有 design token（顏色、字級、間距、圓角、動效、陰影）＋ 共用元件層：按鈕角色（`.btn-primary` / `.btn-secondary` / `.btn-danger`、`.btn-approve` / `.btn-reject`）、表單控制項、focus ring、捲軸。每個頁面都載入（透過 `_navbar.html`；首頁直接載入）。 |
| `_navbar.css` / `_navbar.html` | 固定玻璃工具列：左 Logo、主要導覽（Marshal / Tools / Planners / About / Private）、右側依狀態顯示 Log In（主要動作）或 Manage + 使用者選單；≤900px 變成下拉式選單面板。`current_path` 會標示目前頁面。 |
| `home.css` / `home.html` | 首頁：全螢幕 hero（兩個 CTA）、Quick access 卡片（登入身分不同卡片不同）、Gallery、頁尾；lightbox 與上傳/編輯 modal 的 DOM id 與 `home_gallery.js` 相同。 |
| `login.css` / `login.html` | 登入卡片：Google 為主要動作，本機管理員登入收在「Direct access」展開區。 |

其他頁面沿用各自的 CSS，只透過 token 與共用元件層取得一致的按鈕 / 輸入框 / 導覽列外觀；要逐頁改版時，先把該頁 CSS 裡的硬編碼顏色換成 `--kw-*` token。
