# Kinder Web 功能與導向完整記錄（重構前基準快照）

> **快照基準**：branch `master`，commit `c7f91a4`（2026-09-21）。
> **用途**：這是重構前對整個網站「有什麼功能、怎麼導向、誰能用、資料流向哪裡」的完整備份。萬一重構後某個功能壞了，用這份文件核對原本的行為。
> **完整備份位置**（不在 git 內）：`../kinder_web_blueprint_backup_20260921_1835/`
> - `git_HEAD_c7f91a4.tar.gz`：git 追蹤檔案在 c7f91a4 的完整快照
> - `untracked_files.tar.gz`：所有 **git 沒有追蹤** 的重要檔案（`kinder.env`、`app/modules/download_phot.py`、`app/data/`、`tutorials/`、`gallery_uploads/`、`ov_plot/`、`private_area/data/`、`_spectral_lines_cache.json`、根目錄 `test_*.py` 等）
> - `HEAD_commit.txt`：快照 commit hash
>
> **各區塊的逐 route 細節**在 `docs/features/01_*.md` … `11_*.md`（見文末章節索引）。本文件是總覽與速查。
> **路徑說明**：本文件與各章節中的檔案路徑（`app/routes/…`、`app/modules/…`、`app/main.py`）都是重構前的位置；重構後的新位置見 `docs/ARCHITECTURE.md` §6，功能與行為不變。

---

## 0. 怎麼用這份文件

| 情境 | 步驟 |
|---|---|
| 某個頁面壞了 | §2 網站地圖找到頁面 → 對應章節找到該 route（路徑 / endpoint / 權限 / 模板 / 呼叫的 API）→ 對照 `docs/ARCHITECTURE.md` 的「新舊路徑對照表」找到新程式碼位置 |
| 某個 API 回應變了 | §9 路由總表確認 endpoint 名稱與方法 → 章節內的 API 表格核對輸入 / 輸出 / 失敗回應 |
| 權限行為變了 | §3 權限模型 + 章節內每個 route 的「權限」欄 |
| 背景工作沒跑 | §5 背景工作速查 + `docs/features/09_background_jobs.md` |
| 找不到某個資料檔 | §6 資料目錄總表 |
| 整個還原 | `git checkout c7f91a4`，再把 `untracked_files.tar.gz` 解壓回專案根目錄 |
| 重構前後行為比對 | §11 驗證基準（路由表比對 + 逐頁 GET 冒煙測試 + 既有 pytest） |

---

## 1. 系統總覽

| 項目 | 內容 |
|---|---|
| 框架 | Flask 3.1（Jinja2 模板、Blueprint 分區）、Werkzeug 3.1、Authlib（Google OIDC）、APScheduler（背景排程）、psycopg2 連線池 |
| Python | 3.12（`.python-version`），套件由 `uv` 管理（`pyproject.toml` / `uv.lock`），另有 `requirements.txt` 副本 |
| 入口（重構前） | `app/main.py`：模組層級直接建立 `app`，載入 `kinder.env`、設定 `sys.path`（`modules/`、`modules/CASTOR/src`、`modules/DETECT`）、初始化日誌 / DB 連線池 / OAuth、註冊 14 個 blueprint、啟動背景排程 |
| 啟動指令（重構前） | 開發：`uv run python app/main.py`（`DEBUG=True` 時背景工作全部停用）。正式：於 `app/` 目錄執行 `gunicorn --workers 4 --worker-class gthread --threads 4 --bind 127.0.0.1:8000 main:app`（`kinder.env` 註解），前方有 HTTPS 反向代理，公開網址 `https://kinder.astro.ncu.edu.tw` |
| 設定 | `kinder.env`（git-ignored，鍵名見 §7）；`modules/config.py` 的 `Config` 單例 |
| 資料庫 | PostgreSQL `Kinder`，schema：`auth`、`transient`、`obs`、`cat`（見 §8） |
| 內嵌第三方 | `app/modules/CASTOR/`：曝光時間計算引擎，**獨立 git clone**（`https://github.com/AlexLee24/CASTOR.git`，git-ignored）。`app/modules/DETECT/function/`：DETECT 交叉比對 / host rule / 篩選 pipeline 的 rsync 副本（`scripts/sync_detect.sh`，git 追蹤，`DETECT/VERSION` 記來源） |
| 外部服務 | Google OAuth、TNS（下載 CSV、API 查詢）、QUB ATLAS / Pan-STARRS（Playwright 登入抓光度）、ALeRCE（ZTF / LSST）、NED、NOIRLab / Legacy Survey / DSS / PS1 / VizieR / SIMBAD（尋星圖與 DETECT）、NIST ASD（譜線）、Slack（Daily Trigger、GCN）、SMTP（告警、邀請信）、SFD dust maps（GitHub 下載） |
| 日誌 | `app/log/YYYY-MM-DD.log`（UTC+8 換檔、保留 7 天、15 MiB 上限）；`print()` 亦導入日誌 |

---

## 2. 網站地圖（Sitemap）

導覽列 `_navbar.html`（`app/routes/basic/templates/`）被 27 個頁面 include；首頁有自己的精簡頂欄與底部導覽，內容相同。**權限欄**是「頁面本身」的門檻；頁面內的 API 各自有更細的檢查（見章節）。

```
Kinder（Logo → /）
├── Marshal                         /marshal                        公開（未登入看不到計數與側欄）          → 03
│     └── 物件詳細頁                 /object/<name>                  公開頁；資料依物件 permission / 來源權限  → 04
├── Tools ▾
│     ├── Astronomy Tools           /astronomy_tools                公開                                    → 06
│     ├── Telescope Simulator       /telescope_simulator            公開                                    → 06
│     ├── LC Plotter                /lc_plotter                     公開                                    → 06
│     │     └── 分享的圖             /lc_plotter/shared/<id>         公開（可設密碼）                          → 06
│     ├── Exposure Time Calculator  /exposure_time_calculator       公開（CASTOR）                           → 06
│     ├── (隱藏) 3D Mount Simulator /mount_3d                       公開（navbar 內已註解）                    → 06
│     └── Games                     /games                          公開（1A2B）                             → 06
├── Planners ▾
│     ├── Visibility Plot           /interactive_planner            公開                                    → 06
│     └── Finding Chart             /finding_chart                  公開                                    → 06
├── About Us ▾                      外部連結（GREAT Lab 網站、鹿林天文台氣象）
├── Private ▾（僅 session.user.is_great_lab_member）
│     ├── DETECT                    /detect、/detect?detect_results=<date>、/detect/archives   非 guest（審核僅 admin） → 05
│     ├── Daily Trigger             /daily_trigger                  can_access_page('daily_trigger')         → 07
│     ├── ePessto++ Support Team    /epessto_support                can_access_page('epessto_support')       → 07
│     ├── Documents                 /documents、/documents/<file>   can_access_page('documents')             → 07
│     └── Lab Info                  /greatlab_info                  can_access_page('greatlab_info')         → 07
├── 使用者選單（登入後）
│     ├── Profile                   /profile                        需登入                                  → 01
│     └── Logout                    /logout                                                                → 01
├── Manage ▾（僅 is_admin）
│     ├── Web Log                   /admin/log                      admin 或 GREAT_Lab                      → 02
│     ├── DB Status                 /admin/database                 僅 admin                                → 02
│     └── Admin Panel               /admin                          僅 admin                                → 02
└── Login                           /login                          公開                                    → 01
      ├── Sign in with Google       /auth/google → Google → /auth/google/callback → /                      → 01
      └── Direct Access（本機管理員） POST /admin-login → /                                                   → 01

沒有站內入口的頁面：/observation_planner（ACP 腳本產生器）、/mount_torque、/api（API 文件頁，HTML 或 JSON）
死路由（模板不存在 → 500）：/private/calendar、/private/telescope、/private/projects、/private/resources
```

**登入後導向規則**：Google / 本機登入成功一律回首頁 `/`（`session['next_url']` 全站沒有寫入者）。未登入存取受保護頁 → `redirect('/login')` + flash；權限不足 → `redirect('/')` + flash `Access denied...`。API 端點不 redirect，回 JSON 401 / 403（格式不統一，見 §3）。

---

## 3. 權限模型速查

### 3.1 使用者身分

| 概念 | 來源 | 說明 |
|---|---|---|
| 角色等級 | `auth.users.roles` ∈ {0 guest, 1 user, 50 admin, 99 super_admin} | 導出 `is_admin = roles >= 50`、`role = 'admin'/'user'/'guest'` |
| 首次 Google 登入 | `google_callback` | 新帳號預設 `guest`；email 等於 `ADMIN_EMAIL` 則 admin |
| 本機管理員 | `POST /admin-login`（`ADMIN_USERNAME` / `ADMIN_PASSWORD`） | session 以 `ADMIN_LOCAL_EMAIL` 建立 |
| 群組 | `auth.groups` + `auth.usr_group(status ∈ request/joined/rejected)` | 群組名 `GREAT_Lab` 特殊：`is_great_lab_member = 'GREAT_Lab' in groups or is_admin` |
| 頁面群組權限 | `auth.system_settings` key `page_perm:<page_key>`（JSON list） | `can_access_page(page_key)`：admin / GREAT_Lab / 額外群組 |
| API key | `auth.users.api_key`（48 字元）；使用者申請 `api_key_requested_at`，admin 發放 | `X-API-Key` header 或 `?api_key=`；`get_user_by_api_key()` **不載入群組** |
| 物件層級權限 | `transient.objects.permission ∈ public/login/groups` + `groups[]`；`check_object_access()` | 只在物件詳細頁部分 API 使用 |
| 來源權限 | `transient.object_source_permissions`（phot/spec × source → allowed_groups / is_public）；`filter_by_source_permissions()` | 只套用在光度 JSON 與光度繪圖 |

### 3.2 `session['user']` 的 key

`email`、`name`、`picture`、`is_admin`、`role`、`is_great_lab_member`、`groups`（本機管理員登入時無此 key）、`api_key`。每個請求 `refresh_user_session` 從 DB 重新同步 **只有** `is_admin`、`is_great_lab_member`、`picture`，並把完整使用者 dict 放在 `g.current_user`；`role` / `groups` / `name` / `api_key` 停留在登入當下的值。

### 3.3 檢查方式與失敗回應（整站沒有 decorator，全是 route 內 inline 判斷，約 240 處）

| 檢查 | 典型寫法 | 未通過時（頁面） | 未通過時（API，常見格式） |
|---|---|---|---|
| 需登入 | `if 'user' not in session` | flash + `redirect(url_for('basic.login'))` | `{'error': 'Unauthorized'}` 401 / `{'success': False, 'message': 'Unauthorized'}` 401 / `{'error': 'Not logged in'}` 401 |
| 非 guest | `session['user'].get('role') == 'guest' and not is_admin` | flash `Access denied...` + `redirect(url_for('basic.home'))` | `{'error': 'Forbidden'}` 403 |
| GREAT_Lab 或 admin | `session['user'].get('is_great_lab_member') or is_admin` | redirect 首頁 | `{'success': False, 'error': 'Forbidden: requires GREAT Lab member or admin role'}` 403 |
| 僅 admin | `session['user'].get('is_admin')` | redirect 首頁 | `{'error': 'Access denied'}` 403（最常見，76 處）/ `{'error': 'Admin only'}` 403 |
| 頁面群組 | `can_access_page(key)`（private_area） | redirect 首頁 | 403 |
| API key | `get_user_by_api_key(key)` | – | 401 |

---

## 4. 全站共用機制（`app/main.py`）

| 機制 | 行為 |
|---|---|
| Flask app | `Flask(__name__, template_folder='html', static_folder=None)`；`app/html` 不存在，模板全部來自各 blueprint 的 `templates/`（Jinja 會搜尋所有已註冊 blueprint 的 template_folder，所以 `astronomy_tools` 的 route 可以渲染 `planners/templates/` 裡的模板） |
| Session cookie | 客戶端簽章 cookie；`SESSION_COOKIE_SAMESITE=Lax`、`SESSION_COOKIE_SECURE = not DEBUG`、`PERMANENT_SESSION_LIFETIME = 30 天`；`ProxyFix(x_proto=1, x_host=1)` |
| Host 白名單 | `before_request`：`request.host` 不在 `{APP_BASE_URL 的 netloc}`（DEBUG 另加 `HOST:PORT`、`localhost:PORT`、`127.0.0.1:PORT`）→ 404 |
| 統一靜態檔路由 | `GET /static/<path:filename>`（endpoint `static`）依序在 9 個 blueprint 的 `static/` 目錄找第一個存在的檔案：basic → auth → astronomy_tools → marshal → detect → games → private_area → planners → web_api；`photo/*` 另找專案根 `photo/`（不存在）；`icon/*` 找 `basic/icon/`。**同名檔會被前面的目錄遮蔽**（實際只有 `photo/background.jpg` 一組：basic 的生效，astronomy_tools 的永遠不會被服務）。各 blueprint 自動產生的 `<bp>.static` endpoint 只用來 `url_for`，URL 相同、由 app 層路由處理 |
| `before_request` 順序 | 1 `_enforce_allowed_host` → 2 `refresh_user_session` → 3 `_mark_request_start` → 4 `_block_pipe_in_api_params`（只對 `/api/` 路徑：query / form / JSON 內任何值含 `\|` → 400；影響含 Markdown 表格的文件儲存、含 `\|` 的評論與 tags） |
| `after_request` | 所有回應加 `Cross-Origin-Opener-Policy: same-origin`、`Cross-Origin-Resource-Policy: same-origin`；`ACCESS_LOG_ENABLED=1` 時以 logger `web.request` 記錄每個請求（略過 `/static/`、`/api/log/content`、`/api/log/daemon/content`） |
| 錯誤處理 | `ParamOutOfRangeError`（`modules/request_validation.py` 的 `get_int_arg` / `get_float_arg`）→ `{'error': ...}` 400。其他例外走 Flask 預設 500 HTML |
| URL converter / filter | `alpha`（`[a-zA-Z]+`，用於 `/object/<int:year><alpha:letters>`）；Jinja filter `regex_search` |
| 啟動時 | `check_db_connection()`、`init_connection_pool()`（含 `_ensure_extra_tables()` 的一批 `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE` / `CREATE INDEX`；失敗只 warning）；`oauth.init_app(app)`；astropy `iers.conf.auto_download = False` |
| Blueprint 註冊順序 | `auth → admin → astronomy_tools → marshal_bp(objects) → api → web_api → private_area → basic → marshal → detect → web_log → database_status → games → planners`。**同路徑重複註冊時先註冊者生效**：`/api/profile/join_group`、`/api/profile/leave_group` 由 `auth` 生效（`basic` 版死碼）；`/api/generate_key` 由 `api` 生效（`web_api` 版死碼） |

---

## 5. 背景工作速查（詳見 `docs/features/09_background_jobs.md`）

只有取得檔案鎖 `app/log/.background_jobs.lock` 的那個行程會跑背景工作（gunicorn 多 worker 時只有一個）。`DEBUG=True` 時 APScheduler job 與常駐執行緒全部停用，只有 NIST 譜線快取仍會在啟動時重建。**注意**：`BackgroundScheduler` 未指定時區，cron 以主機時區觸發，但程式註解與管理頁全標 UTC。

| 種類 | 名稱 | 時間 | 做什麼 |
|---|---|---|---|
| cron | `daily_backup` | 03:00 | `pg_dump` 整庫到 `app/data/backups/`（保留 15 份）；啟動時也同步跑一次 |
| cron | `daily_phot_fetch` | 03:30 | 對所有 Inbox 物件跑 `download_phot.process_single_object_workflow`（ATLAS / PS / ZTF / LSST / TNS） |
| cron | `daily_target_mag_update` | 05:00 | 更新 `obs.targets` 的最新星等（**目前寫到不存在的表，見已知問題**） |
| cron | `daily_retire_stale_followups` | 05:30 | Follow-up / Snoozed 物件退役成 Finish（**有 bug，見已知問題**） |
| cron | `daily_host_redshift_sync` | 06:00 | `sync_host_redshifts`：把 DETECT host 的紅移寫回物件 |
| cron | `daily_detect_followups` | 04:00 | DETECT 重新篩選所有 Follow-up 物件（需 `DETECT_IN_WEB` 啟用） |
| interval | `db_monitor` | 每 10 分 | 連線池 / `pg_stat_activity` 監控，超標寄 email（硬編碼收件人） |
| interval | `db_recycle` | 每 30 分 | 關閉池內閒置連線 |
| interval | `detect_page_prewarm` | 每 30 分 | 預建 DETECT 頁快取（**排程內無 app context，必失敗**；只有啟動那次有效） |
| 執行緒 | `auto_tns_download` | 每 10 s 輪詢（真 UTC） | 分鐘 15 / 45：下載 TNS 每小時 CSV → 匯入 `transient.objects` → 種發現點光度 → 新物件抓光度 → DETECT → auto snooze（Inbox 超過 15 天 → Snoozed）。01 / 04 / 12 UTC 整點：下載每日檔（今天、昨天、前天）→ 匯入 → DETECT（只新物件）→ auto snooze |
| 執行緒 | `tns_gap_filler` | 啟動 10 分後每小時 | 找當年 `kinder_id` 缺口，逐一向 TNS API 查詢補入 |
| 執行緒 | `nist-spec-lines` | 啟動時一次 | 重抓 NIST 24 個離子譜線到 `app/modules/_spectral_lines_cache.json` |
| （停用） | `gcn_alert` | – | GCN Kafka circular / Einstein Probe alert → Slack + email（`main.py` 已註解） |
| 手動（管理頁） | TNS hourly / daily 下載、auto-snooze、光度抓取、缺漏光度、目標星等、DETECT run、備份 | – | `/admin/*` 按鈕，各自另起 thread（狀態為 process 內變數） |

工作狀態記錄在 `app/log/.job_status.json`（只寫已完成項目），管理頁 `/admin/scheduled-jobs-status` 讀取。

---

## 6. 資料目錄總表（皆為 git-ignored 的執行期資料）

| 路徑 | 寫入者 | 讀取者 |
|---|---|---|
| `app/data/tns_api_download_work/tns_public_objects_WORK.csv` | `auto_tns_download`、`Manual_tns_download_snoozed`、admin 手動下載 | `addin_database` |
| `app/data/phot_cache/<YYYY>/<name>_photometry.txt` | `download_phot`（上傳 DB 後即刪；殘留 = 失敗遺留） | `download_phot.upload_photometry_to_db` |
| `app/data/shared_plots/<24hex>.json` | `POST /lc_plotter/share` | `GET /lc_plotter/shared/<id>`（60 天，讀取時才檢查過期；無清理排程） |
| `app/data/filter_colors.json` | 手動維護 | `modules/filter_colors.py`（濾鏡顏色） |
| `app/data/trigger_send_status.json` | `trigger_send.mark_sent` | `trigger_send.get_send_status`（Daily Trigger 今晚是否已送） |
| `app/data/backups/Kinder_backup_YYYYMMDD.sql` | `backup.run_daily_backup` | 人工 |
| `app/data/gcn.json`、`ep.json`、`ep_observing_track.jpg` | `GCN_alert`（停用） | 無 |
| `app/data/1a2b_leaderboard.json`、`app/data/greatlab_links.json` | **孤兒**：程式實際讀寫的是 `<repo>/data/1a2b_leaderboard.json`（目錄不存在）與 `app/routes/private_area/data/greatlab_links.json` | – |
| `app/data/tns_public_objects_FULL.csv`、`tns_public_objects.csv.zip` | 一次性全量同步遺留（只有根目錄 `test_tns_full_sync.py` 引用） | – |
| `app/log/` | 每日 log、`.background_jobs.lock`、`.job_status.json` | `/admin/log` 相關 API |
| `app/modules/DETECT/data/`（= `DETECT_DATA_DIR`） | DETECT finder 圖（`crossmatch_images/`、`marked_images/`）、SFD dust maps（`dustmaps/sfd/`，首次使用自 GitHub 下載約 128 MiB） | DETECT、`ext_M_calculator` |
| `app/modules/_spectral_lines_cache.json` | `spectral_lines` | `GET /api/spectral-lines` |
| `app/modules/web_data/kn_lc_mag.txt` | git 追蹤（與 `DETECT/function/data/kn_lc_mag.txt` 相同內容） | `object_routes._parse_kn_model`（`/api/kn_model`） |
| `app/routes/planners/ov_plot/observing_tracks_<uuid>.jpg` | `POST /generate_plot`（最多保留 10 張，依 mtime 淘汰） | `GET /ov_plot/<file>` |
| `app/routes/basic/gallery_uploads/` | 首頁相簿上傳（原圖、`_thumb` 縮圖、`.json` sidecar） | `GET /api/gallery`、`/gallery/image/<f>` |
| `app/routes/basic/slideshow/` + `slideshow_config.json` | 手動 | `GET /api/slideshow`（首頁已不使用） |
| `app/routes/private_area/data/` | `epessto_sessions.json`（房間 / 工作階段）、`epessto_uploads/rooms/<room>/{files,images}` | ePessto++ API |
| `app/routes/private_area/tutorials/` | Documents：`*.md`、`metadata.json`、`images/`、`.env`（`DOCUMENTS_EDITABLE`、`IMPORTANT_MESSAGE`；**目前也放了 Slack token 與 Lab 帳密供 `{{hide=KEY}}` 代換**） | Documents 頁與 API |
| `kinder.env` | 手動 | `modules/config.py` 與多個模組各自 `load_dotenv` |

---

## 7. 環境變數總表（`kinder.env`）

| 名稱 | 用途 | 使用處 | 必填 |
|---|---|---|---|
| `DEBUG` | 停用背景工作、縮小連線池（1–10 vs 2–60）、關閉 Secure cookie、Slack 改用測試頻道 | `config.py`、`database/__init__.py` | 否（預設 False） |
| `HOST` / `PORT` | Flask 綁定位址、Host 白名單 | `config.py`、`main.py` | 否（127.0.0.1:5000） |
| `APP_BASE_URL` | 公開網址：Host 白名單、OAuth redirect_uri | `config.py`、`main.py`、`auth_routes` | 正式必填 |
| `SECRET_KEY` | session 簽章 | `config.py` | 必填 |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google OAuth | `auth_routes` | 登入必填 |
| `ADMIN_EMAIL` | 首次 Google 登入即為 admin 的 email | `auth_routes` | 否 |
| `ADMIN_LOCAL_EMAIL` / `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 本機管理員登入 | `auth_routes` | 否 |
| `SMTP_SERVER` / `SMTP_PORT` / `SENDER_EMAIL` / `SENDER_PASSWORD` | 寄信（DB 告警、邀請信、GCN） | `email_utils`、`db_monitor`、`GCN_alert` | 寄信功能必填 |
| `PG_HOST` / `PG_PORT` / `PG_USER` / `PG_PASSWORD` | PostgreSQL（DB 名稱硬編碼 `Kinder`） | `database/__init__.py`、`backup.py`、DETECT | 必填 |
| `PG_DATABASE` | 只有 DETECT 讀（web 端會覆寫成 `Kinder`） | DETECT | 否 |
| `TNS_BOT_ID` / `TNS_BOT_NAME` / `TNS_API_KEY` | TNS bot | `auto_tns_download`、`tns_gap_filler`、`download_phot` | TNS 同步必填 |
| `ATLAS_USER` / `ATLAS_PASS`、`PANSTARRS_USER` / `PANSTARRS_PASS` | QUB 網站登入（Playwright） | `download_phot` | 光度抓取必填 |
| `SLACK_BOT_TOKEN`、`SLACK_CHANNEL_ID_CONTROL_ROOM`、`SLACK_CHANNEL_ID_test` | Daily Trigger 送 Slack（DEBUG 用 test 頻道） | `trigger_send` | Trigger 必填 |
| `SLACK_CHANNEL_ID_GCN` / `SLACK_CHANNEL_ID_ToO`、`GCN_CLIENT_ID` / `GCN_CLIENT_SECRET` | GCN 監聽（停用） | `GCN_alert` | 否 |
| `ACCESS_LOG_ENABLED` | HTTP access log | `main.py` | 否（預設關） |
| `LOG_MAX_FILE_BYTES` / `LOG_MAX_LINE_CHARS` | 日誌上限 | `log_setup` | 否 |
| `DETECT_IN_WEB` | `0/false` 時停用 web 內 DETECT | `detect_pipeline` | 否（預設啟用） |
| `DETECT_DATA_DIR` | DETECT 資料目錄（`main.py` 預設 `app/modules/DETECT/data`） | `main.py`、DETECT | 否 |
| `DETECT_PAGE_CACHE_TTL_SEC` / `DETECT_PAGE_CACHE_MAX_SIZE` / `DETECT_PAGE_PREWARM_DAYS` / `DETECT_LC_CACHE_MAX_SIZE` / `DETECT_TRACKER_CACHE_TTL` | DETECT 頁快取參數 | `detect_routes` | 否（600 / 8 / 3 / 300 / 300） |
| `VIZIER_TIMEOUT_SEC`、`HEALPIX_NSIDE` | Vizier 逾時、HEALPix 解析度 | `detect_cross_match`、DETECT | 否 |
| （舊名，未設定）`TNS_HOST` / `API_BASE_URL` / `BOT_ID` / `BOT_NAME` / `API_KEY` | 只有 `Manual_tns_download_snoozed.py` 讀 → 該模組無法通過 TNS 驗證 | – | – |

---

## 8. 資料庫 schema 速查（詳見 `docs/features/11_database_layer.md` 與 `docs/database/`，原 `_Kinder_Database/`）

| Schema | 表 | 用途 |
|---|---|---|
| `auth` | `users`（`usr_id, email, name, picture_url, roles, api_key, api_key_requested_at, last_login, join_date`）、`groups`、`usr_group`（成員 / 申請狀態）、`images`（未使用）、`invitations`（執行期建，未使用）、`system_settings`（key/value：`open_registration`、`page_perm:*`） | 使用者 / 群組 / 設定 |
| `transient` | `objects`（TNS 物件主表：`obj_id, kinder_id, name_prefix, name, ra, dec, redshift, type, status ∈ Inbox/Follow-up/Snoozed/Finish, tag[], pin, permission, groups, brightest_mag, brightest_abs_mag, host_name, last_phot_date, ...` 日期欄位皆為 MJD double）、`photometry`（唯一鍵 `obj_id, "MJD", filter, source`）、`spectroscopy`、`comments`、`cross_matches`（DETECT 候選 host，`is_host / flag / match_data JSON`）、`detect_screen` / `detect_screen_history`（DETECT 分數、`host_status`）、`target_images`（finder 圖 BYTEA）、`download_logs`、`tns_update_audit`、`object_views` / `object_views_detail`、`custom_targets`、`default_permissions`、`object_source_permissions` | 暫現源資料 |
| `obs` | `targets`（觀測目標：`name, telescope, program, priority, plan_filter/count/time, auto_exposure, active`；唯一 `(name, telescope)`）、`logs`（觀測 / 觸發日誌；唯一 `(target_id, date)`；`priority` CHECK ∈ Urgent/High/Normal/Filler） | 觀測規劃 |
| `cat` | `desi`（HEALPix 索引）、`lens`、`ned`（NED cone search 快取） | 目錄 |

`OBJECT_COMPAT_COLS`（`modules/database/__init__.py`）把 `transient.objects` 映射成舊 `tns_objects` 欄位名（`declination`、`discoverydate` 字串、`tag`（由 status 導出的 `object/followup/snoozed/finished`）、`tags`（真正的 `tag[]`）、`inbox/snoozed/follow/finish_follow` 旗標…），大量 route 依賴這些別名。

---

## 9. 路由總表（自動產生）

見文末「附錄 A」（由 `tests/tools/dump_url_map.py` 產生，250 條規則、14 個 blueprint）。

---

## 10. 已知問題總表（重構前就存在；依嚴重度排序。✅ 標記 = 2026-09-21 清理階段已修正，其餘仍待處理）

各章節末尾都有更完整的清單，這裡只列跨章節最重要的。**重構的原則是行為不變**，所以這些問題在重構後仍然存在，需另外排程修復。

### A. 會直接 500 或功能整條斷裂
1. ✅ **已修正（2026-09-21 清理階段）** — ：`auth_routes.google_callback` 與 `admin_routes.add_user` 以 `picture= / role= / last_login= / invited_at=` 呼叫 `save_user()`，但簽名是 `save_user(email, name, picture_url, is_admin)` → `TypeError`。首次 Google 登入者變成「幽靈登入」（session 有、DB 無列）。目前網頁上沒有任何路徑能新增 `auth.users`。（01、02）
2. ✅ **已修正** — ：`auth.profile_join_group` 把 list 當 dict `.get()` → 500；管理端 `handle_group_request` 以錯誤簽名呼叫 `get_group_request` / `update_group_request_status`；狀態字串 `'pending'` / `'approved'` 與 DB CHECK（`request/joined/rejected`）不符。（01、02）
3. ✅ **已修正**（`update_user` 支援 `role`，不再降級 super_admin；`/update-profile` 不再改寫 roles）— ：`update_user()` 忽略 `role`，只依 `is_admin` 寫 `roles=50/1` → `/admin/update-role` 無法設 guest、super_admin 被降級；`/update-profile` 改名 / 換頭像也會重寫 `roles`。（01、02）
4. ✅ **已修正**（MJD 浮點數的 `AttributeError` 已修；「所有 Snoozed → Finish」規則已移除，只退役 Follow-up）— （每日 05:30）：對 `last_phot_date`（float MJD）取 `.year` → `AttributeError`，「>2 天無光度」規則從未生效；同時把**所有** Snoozed 物件改成 Finish。（09）
5. ✅ **已修正**（改寫到 `obs.targets` / `obs.logs`）— （每日 05:00 與 `/api/targets/update-mags`）寫入不存在的表 `obs.observation_targets` / `obs.observation_logs`（實際是 `obs.targets` / `obs.logs`）→ 從未成功。（09）
6. ✅ **已修正**（排程改傳 `app_obj`）—  每 30 分鐘排程在無 app context 的執行緒呼叫 `current_app` → 必失敗。（09）
7. ✅ **已修正** — ：mag > 22 的自動曝光目標比對字串不符 → 對字串 `.items()` → `/astronomy_tools/generate_trigger_script` 500。（10）
8. ✅ **已修正** — ：`/api/stats`、`/api/objects`、`/api/object-tags`、`/api/classifications` 的例外路徑再拋 `AttributeError` → 前端拿到 HTML 500 而非 fallback JSON。（08）
9. ✅ **已移除**這四條死路由 —  渲染不存在的模板 → 500（無入口，殘留死路由）。（07）
10. ✅ **已修正** — 寫到 `<repo>/data/1a2b_leaderboard.json`（目錄不存在、未 gitignore），`app/data/` 那份是孤兒；GET 永遠 `[]`。（06）
11. ✅ **部分修正**（環境變數名已改用 `TNS_*`；`auto_snoozed` 語意未改）— **`manual_tns_download.py`** 原本讀舊環境變數名（`BOT_ID` 等）→ `/api/tns/manual-download` 無法通過 TNS 驗證；其 `auto_snoozed` 會把 Finish 也 Snooze。（09）
12. ✅ **已修正**（`write_documents_env` 保留所有 key）— ：`write_documents_env()` 只寫回兩個 key，admin 一按 `POST /api/documents/settings` 就抹掉 `tutorials/.env` 裡的 Slack token 與 Lab 帳密。（07）
13. ✅ **已修正**（priority 與 program 分開送）— 把 Program 併入 `priority`（`"High - R01"`）→ 違反 CHECK → 500。（07）
14. ⚠️ 部分處理（`admin.accept_invitation` 死分支已移除；其餘前端死呼叫未動）— 前端呼叫但後端不存在：`GET /api/custom_targets`（Observation Planner「Fetch Custom Targets」）、`POST /admin/delete-invitation`、`POST /admin/clean-invitations`、`/api/object/greatlab_routes/permissions`；Python 端 `url_for('admin.accept_invitation')` 指向不存在的 endpoint（潛伏）。（02、06）
15. **在請求內同步跑重工作**：`POST /api/object/<name>/fetch_photometry`（Playwright 登入、數分鐘、任何登入者可觸發）、`POST /admin/backup-now`（`pg_dump` 最長 300 s）、DETECT 觸發端點。（08、09）

### B. 安全 / 權限
16. **DETECT 三個端點完全無認證**：`GET /api/object/<n>/detect_cross_match?force=true`（GET 有副作用）、`POST .../detect_images/generate`、`GET .../detect_images`。（08）
17. `GET /api/objects`、`POST /api/tns/search` 不需登入、不做物件權限過濾、原樣輸出 `permission` / `groups`；`/api/marshal/recent-comments` 公開輸出留言者 email。（03、08）
18. Documents：`GET /api/documents/<f>/content` 會把 `{{hide=KEY}}` 代換成 `.env` 真實值並附 `raw_content`；`/tutorials/images/*` 完全公開；`POST /api/documents/metadata` 預設未登入也能寫。（07）
19. 來源權限只套用在光度 JSON / 繪圖；光度下載與所有光譜端點未過濾（admin 面板的 Spectroscopy 權限設定無效）。`check_object_access` 對 admin 不生效（未傳 `user_roles`）。（04）
20. DETECT 審核 API（set_host / unset_host / set_object_status / mark_no_host / toggle_flag）後端只擋 guest，前端卻只給 admin 看按鈕。（05）
21. 任何登入者（含 guest）可讀 `/api/targets`、`/api/members`（全站 email）、可寫 / 刪 `obs.logs`。（07）
22. API key 明文儲存、寫入 session cookie、`daily_trigger.html` 渲染進 `<meta name="x-api-key">`；`get_user_by_api_key` 不載入群組 → `/api/v1/observation_targets` 實際 admin-only、`/api/v1/observation_logs` 對任何 key 開放寫入。（07、08）
23. XSS 向量：`marshal.js` 的最近留言、`greatlab_links` 以 `innerHTML` 未跳脫。（03、07）
24. `_client_ip()` 信任 `X-Forwarded-For`（ProxyFix 未設 `x_for`）→ 公開 API 速率限制可繞過；`POST /lc_plotter/share` 無登入、無限流、每次最多 8 MiB、無清理。（06）

### C. 資料正確性
25. **flag 三種定義互不相通**：`objects.tag @> ['flag']`（首頁計數）、`cross_matches.status='Flagged'`（Marshal 篩選；從未寫入）、`cross_matches.flag` 布林（實際按鈕寫入）→ 按 flag 後篩選與計數都不反映；`/api/stats.flag_count` 恆 0。（03、08、11）
26. NED「Set as Host」不持久化（`ned_set_host` 只 log）；`transient.objects.host_name` 全專案沒有寫入者。（04）
27. `TNSObjectDB.delete_spectrum` 沒有 `obj_id` 條件，只以 `(source, "MJD")` 刪 → 可能一併刪掉別的物件的光譜。（11）
28. `POST /api/objects`（手動新增）寫入舊版 `status='Object'`、`name_prefix=''` → 不出現在 Inbox。（08）
29. Marshal API 模式（>5000 筆）漏映射 `tags` → 列表看不到自訂標籤，admin Edit 會整個覆蓋 `tag[]`；Brightest Mag / Abs Mag 進階篩選參數後端未讀取。（03）
30. 兩套宇宙學參數（`astronomy_calculator` vs DETECT `cosmo`）→ 不同頁面的距離 / 絕對星等有微小差異。（10）
31. `trigger_script` 與 `observation_script` 各自一份曝光時間表與濾鏡對照（`Trigger_LOT_SLT.py` 第三份為死碼），`#REPEAT` 位置不一致。（10）

### D. 架構 / 維運（重構會改善其中一部分，見 `docs/ARCHITECTURE.md`）
32. **讀取路徑執行 DDL**（`ALTER TABLE ... IF NOT EXISTS` / `CREATE TABLE IF NOT EXISTS`）：每次建 DETECT 頁、toggle_flag、`get_observation_targets`、`get_recent_tns_updates` 都做 → 需要 DDL 權限且會搶表鎖（本次建立基準時就因此互相卡死過一次）。（05、08、09、11）
33. **process-local 狀態**：DETECT 頁 / LC / tracker 快取、`_tns_task_status`、`detect_pipeline._LOCK`、`phot_scheduler._running` 都是行程內變數，gunicorn 多 worker 下互看不到，「already running」防呆只在同一 worker 有效。（02、05、08）
34. **APScheduler 未指定時區**（cron 依主機時區）但註解 / 管理頁全標 UTC；`auto_tns_download` 執行緒才是真 UTC。（09）
35. **`download_phot.py` 以裸 `from database import` 匯入** → 第二個獨立連線池、`_ensure_extra_tables` 跑兩次、`db_monitor` 看不到。（09）
36. **`load_dotenv(override=True)` 散落多處**（`database/__init__.py`、`download_phot.py`、`db_monitor` 每次呼叫）覆寫整個行程環境。（09）
37. **死模組**（無任何 import）：`database_deprecated.py`、`obsplan_old.py`、`Trigger_LOT_SLT.py`、`object_data.py`、`detect_image.py`、`TNS_object_fetch.py`；另有大量未使用 import 與死 JS 函式（見各章）。（10）
38. `_block_pipe_in_api_params` 讓所有 `/api/` JSON 不能含 `|`（Markdown 表格文件無法儲存）。（07）
39. 三處以 `os.getcwd()` 或 `__file__` 相對路徑找檔案（搬檔即壞），詳見各章「檔案」小節。（10）

---

## 11. 驗證基準（重構前）

見文末「附錄 B」：既有 `test_detect_pages.py` 結果、逐頁 GET 冒煙測試對 4 種身分（匿名 / guest / GREAT_Lab 成員 / admin）的狀態碼，以及重構後的比對結果。

---

## 12. 章節索引（`docs/features/`）

| 章 | 檔案 | 範圍 |
|---|---|---|
| 01 | `01_basic_auth.md` | 首頁、登入 / OAuth / 本機管理員登入、個人資料、相簿、群組申請、API key 申請；全站共用機制；`_navbar.html` 完整導覽結構；session 內容 |
| 02 | `02_admin.md` | Admin Panel（使用者 / 群組 / API key / 設定 / 維護 / TNS / DETECT / 排程狀態）、Web Log、DB Status |
| 03 | `03_marshal.md` | Marshal 物件列表：篩選 / 分頁 / 狀態 / tag / pin / flag 概念、側欄 API、`marshal.js` 呼叫的所有端點 |
| 04 | `04_object_detail.md` | 物件詳細頁：兩種 URL 形式與名稱解析、光度 / 光譜上傳下載繪圖、評論、來源權限、物件群組權限、NED、KN model、譜線 |
| 05 | `05_detect_planners.md` | DETECT 首頁 / 審核 / 封存頁、審核動作寫入對照、三層快取機制、`/ov_plot` |
| 06 | `06_astronomy_tools_games.md` | Astronomy Tools、Observation Planner、LC Plotter 與分享、Telescope Simulator、CASTOR ETC、Visibility Planner、Finding Chart、公開 REST API 與 API 文件頁比對、Games |
| 07 | `07_private_area.md` | Daily Trigger 完整流程、ePessto++ 房間模型、Documents、Lab Info、觀測目標 / 日誌 API、頁面群組權限 |
| 08 | `08_web_api.md` | web_api blueprint 全部端點（API 參考）：物件 CRUD、flag / pin、TNS 下載 / 搜尋、統計、光度抓取、DETECT 觸發、觀測 API v1；session vs API key 驗證模型 |
| 09 | `09_background_jobs.md` | 排程總表、每個服務模組的函式 / 觸發 / 資料表 / 檔案 / 環境變數、`download_phot` 流程、資料目錄總表、環境變數總表 |
| 10 | `10_domain_modules.md` | 觀測規劃 / 腳本產生 / 光度光譜繪圖 / 座標日期轉換 / 消光 / 死模組 |
| 11 | `11_database_layer.md` | Kinder schema 逐表說明、連線池、`OBJECT_COMPAT_COLS` 40 個別名、138 個 DB 函式清單與呼叫者、命名相容規則 |


---

## 附錄 A：路由總表（重構前 commit `c7f91a4`，共 250 條規則；重構後經比對完全相同）

Blueprint 對照章節：basic/auth/api→01、admin/web_log/database_status→02、marshal→03、marshal_bp（物件詳細頁）→04、detect/planners→05、astronomy_tools/games→06、private_area→07、web_api→08。同一路徑出現兩次表示被兩個 blueprint 註冊，先註冊者生效（見 §4）。

| 路徑 | 方法 | endpoint | 章 |
|---|---|---|---|
| `/` | GET | `basic.home` | 01 |
| `/admin` | GET | `admin.admin_panel` | 02 |
| `/admin-login` | POST | `auth.admin_login` | 01 |
| `/admin/add-multiple-to-group` | POST | `admin.add_multiple_to_group` | 02 |
| `/admin/add-to-group` | POST | `admin.add_user_to_group_route` | 02 |
| `/admin/add-user` | POST | `admin.add_user` | 02 |
| `/admin/api-key/issue` | POST | `admin.admin_issue_api_key` | 02 |
| `/admin/api-key/revoke` | POST | `admin.admin_revoke_api_key` | 02 |
| `/admin/available-users/<group_name>` | GET | `admin.get_available_users` | 02 |
| `/admin/backup-now` | POST | `admin.backup_now` | 02 |
| `/admin/batch-update-groups` | POST | `admin.batch_update_groups` | 02 |
| `/admin/check-consistency` | GET | `admin.check_consistency` | 02 |
| `/admin/clean-consistency` | POST | `admin.clean_consistency` | 02 |
| `/admin/create-group` | POST | `admin.create_group_route` | 02 |
| `/admin/database` | GET | `database_status.database_status_page` | 02 |
| `/admin/default-source-permissions` | GET | `admin.get_default_source_perms` | 02 |
| `/admin/default-source-permissions` | POST | `admin.save_default_source_perms` | 02 |
| `/admin/delete-group` | POST | `admin.delete_group_route` | 02 |
| `/admin/delete-user` | POST | `admin.delete_user_route` | 02 |
| `/admin/detect-run` | POST | `admin.detect_run` | 02 |
| `/admin/detect-status` | GET | `admin.detect_status` | 02 |
| `/admin/documents/clean-images` | POST | `admin.clean_unused_images` | 02 |
| `/admin/group-requests/<int:request_id>/<action>` | POST | `admin.handle_group_request` | 02 |
| `/admin/log` | GET | `web_log.log_viewer` | 02 |
| `/admin/photometry-fetch-status` | GET | `admin.photometry_fetch_status` | 02 |
| `/admin/remove-from-group` | POST | `admin.remove_user_from_group_route` | 02 |
| `/admin/run-missing-phot-fetch` | POST | `admin.run_missing_phot_fetch` | 02 |
| `/admin/run-photometry-fetch` | POST | `admin.run_photometry_fetch` | 02 |
| `/admin/run-update-target-mags` | POST | `admin.run_update_target_mags` | 02 |
| `/admin/scheduled-jobs-status` | GET | `admin.scheduled_jobs_status` | 02 |
| `/admin/settings/save` | POST | `admin.save_settings` | 02 |
| `/admin/sources/all` | GET | `admin.all_sources` | 02 |
| `/admin/sources/search` | GET | `admin.search_sources` | 02 |
| `/admin/tns-auto-snooze` | POST | `admin.tns_auto_snooze` | 02 |
| `/admin/tns-download-daily` | POST | `admin.tns_download_daily` | 02 |
| `/admin/tns-download-hourly` | POST | `admin.tns_download_hourly` | 02 |
| `/admin/tns-task-status` | GET | `admin.tns_task_status` | 02 |
| `/admin/toggle-admin` | POST | `admin.toggle_admin_status` | 02 |
| `/admin/update-role` | POST | `admin.update_user_role` | 02 |
| `/admin/user-groups/<user_email>` | GET | `admin.get_user_groups` | 02 |
| `/api` | GET | `astronomy_tools.api_index` | 06 |
| `/api/admin/database/action` | POST | `database_status.api_database_action` | 02 |
| `/api/admin/database/status` | GET | `database_status.api_database_status` | 02 |
| `/api/admin/private_area/page_perms` | POST | `private_area.api_add_private_page_perm` | 07 |
| `/api/admin/private_area/page_perms` | GET | `private_area.api_get_private_page_perms` | 07 |
| `/api/admin/private_area/page_perms` | DELETE | `private_area.api_remove_private_page_perm` | 07 |
| `/api/auto-snooze/manual-run` | POST | `web_api.manual_auto_snooze` | 08 |
| `/api/auto-snooze/stats` | GET | `web_api.auto_snooze_stats_api` | 08 |
| `/api/auto-snooze/status` | GET | `web_api.auto_snooze_status` | 08 |
| `/api/auto_exposure` | GET | `private_area.api_auto_exposure` | 07 |
| `/api/classifications` | GET | `web_api.api_get_classifications` | 08 |
| `/api/comments/<int:comment_id>` | DELETE | `marshal_bp.delete_comment` | 04 |
| `/api/comments/<int:comment_id>` | PATCH,PUT | `marshal_bp.update_comment` | 04 |
| `/api/coords` | GET | `astronomy_tools.api_coords` | 06 |
| `/api/date` | GET | `astronomy_tools.api_date` | 06 |
| `/api/detect/cache_status` | GET | `detect.detect_cache_status_api` | 05 |
| `/api/detect/followup_tracker` | GET | `detect.followup_tracker_api` | 05 |
| `/api/detect/lightcurve/<path:target_name>` | GET | `detect.detect_lightcurve_api` | 05 |
| `/api/distance` | GET | `astronomy_tools.api_distance` | 06 |
| `/api/documents/<filename>/content` | GET,PUT | `private_area.api_documents_content` | 07 |
| `/api/documents/create` | POST | `private_area.api_documents_create` | 07 |
| `/api/documents/metadata` | POST | `private_area.api_documents_metadata` | 07 |
| `/api/documents/settings` | GET,POST | `private_area.api_documents_settings` | 07 |
| `/api/documents/upload-image` | POST | `private_area.api_documents_upload_image` | 07 |
| `/api/epessto_support/clear` | DELETE | `private_area.api_epessto_support_clear` | 07 |
| `/api/epessto_support/image/<path:filename>` | GET | `private_area.api_epessto_support_image_file` | 07 |
| `/api/epessto_support/room/current` | GET | `private_area.api_epessto_support_current_room` | 07 |
| `/api/epessto_support/room/kick` | POST | `private_area.api_epessto_support_room_kick` | 07 |
| `/api/epessto_support/room/leave` | POST | `private_area.api_epessto_support_leave_room` | 07 |
| `/api/epessto_support/room/members` | GET | `private_area.api_epessto_support_room_members` | 07 |
| `/api/epessto_support/rooms/create` | POST | `private_area.api_epessto_support_create_room` | 07 |
| `/api/epessto_support/rooms/join` | POST | `private_area.api_epessto_support_join_room` | 07 |
| `/api/epessto_support/rooms/join_by_invite` | POST | `private_area.api_epessto_support_join_by_invite` | 07 |
| `/api/epessto_support/rooms/live` | GET | `private_area.api_epessto_support_live_rooms` | 07 |
| `/api/epessto_support/session` | GET | `private_area.api_epessto_support_session` | 07 |
| `/api/epessto_support/target` | DELETE | `private_area.api_epessto_support_remove_target` | 07 |
| `/api/epessto_support/target_image` | DELETE | `private_area.api_epessto_support_target_image_delete` | 07 |
| `/api/epessto_support/target_image` | POST | `private_area.api_epessto_support_target_image_upload` | 07 |
| `/api/epessto_support/target_state` | POST | `private_area.api_epessto_support_target_state` | 07 |
| `/api/epessto_support/upload` | POST | `private_area.api_epessto_support_upload` | 07 |
| `/api/exposure_time_calculator` | POST | `astronomy_tools.api_exposure_time_calculator` | 06 |
| `/api/exposure_time_calculator/batch` | POST | `astronomy_tools.api_exposure_time_calculator_batch` | 06 |
| `/api/exposure_time_calculator/presets` | GET | `astronomy_tools.api_exposure_time_calculator_presets` | 06 |
| `/api/finding_chart` | POST | `astronomy_tools.generate_finding_chart` | 06 |
| `/api/finding_chart/fits` | POST | `astronomy_tools.download_finding_chart_fits` | 06 |
| `/api/finding_chart/image` | GET | `astronomy_tools.api_finding_chart_image` | 06 |
| `/api/finding_chart/surveys` | GET | `astronomy_tools.api_finding_chart_surveys` | 06 |
| `/api/gallery` | GET | `basic.api_gallery_list` | 01 |
| `/api/gallery/<item_id>` | DELETE | `basic.api_gallery_delete` | 01 |
| `/api/gallery/<item_id>` | PUT | `basic.api_gallery_update` | 01 |
| `/api/gallery/upload` | POST | `basic.api_gallery_upload` | 01 |
| `/api/games/leaderboard` | GET | `games.get_leaderboard` | 06 |
| `/api/games/leaderboard` | POST | `games.submit_score` | 06 |
| `/api/generate_key` | POST | `api.generate_key` | 01 |
| `/api/generate_key` | POST | `web_api.generate_key` | 08 |
| `/api/get_object_status` | GET | `detect.get_object_status_api` | 05 |
| `/api/greatlab_links` | GET,POST | `private_area.api_greatlab_links` | 07 |
| `/api/groups` | GET | `marshal_bp.get_groups_api` | 04 |
| `/api/kn_model` | GET | `marshal_bp.api_kn_model` | 04 |
| `/api/log/content` | GET | `web_log.api_log_content` | 02 |
| `/api/log/daemon/content` | GET | `web_log.api_daemon_log_content` | 02 |
| `/api/log/files` | GET | `web_log.api_log_files` | 02 |
| `/api/log/sources` | GET | `web_log.api_log_sources` | 02 |
| `/api/mark_no_host` | POST | `detect.mark_no_host` | 05 |
| `/api/marshal/pinned-objects` | GET | `marshal.get_marshal_pinned_objects` | 03 |
| `/api/marshal/recent-comments` | GET | `marshal.get_marshal_recent_comments` | 03 |
| `/api/marshal/recent-tns-updates` | GET | `marshal.get_marshal_recent_tns_updates` | 03 |
| `/api/marshal/top-viewed` | GET | `marshal.get_marshal_top_viewed` | 03 |
| `/api/members` | GET | `private_area.api_members` | 07 |
| `/api/ned/cone` | GET | `marshal_bp.ned_cone_search` | 04 |
| `/api/ned/set_host` | POST | `marshal_bp.ned_set_host` | 04 |
| `/api/ned/unset_host` | POST | `marshal_bp.ned_unset_host` | 04 |
| `/api/object-tags` | POST | `web_api.api_get_object_tags` | 08 |
| `/api/object/<int:year><alpha:letters>` | GET | `marshal_bp.api_get_object_tns_format` | 04 |
| `/api/object/<int:year><alpha:letters>/photometry` | GET | `marshal_bp.get_object_photometry` | 04 |
| `/api/object/<int:year><alpha:letters>/photometry` | POST | `marshal_bp.upload_photometry` | 04 |
| `/api/object/<int:year><alpha:letters>/photometry/batch` | POST | `marshal_bp.upload_photometry_batch` | 04 |
| `/api/object/<int:year><alpha:letters>/photometry/download` | GET | `marshal_bp.download_photometry` | 04 |
| `/api/object/<int:year><alpha:letters>/photometry/plot` | GET | `marshal_bp.get_object_photometry_plot` | 04 |
| `/api/object/<int:year><alpha:letters>/spectroscopy` | GET | `marshal_bp.get_object_spectroscopy` | 04 |
| `/api/object/<int:year><alpha:letters>/spectroscopy` | POST | `marshal_bp.upload_spectroscopy` | 04 |
| `/api/object/<int:year><alpha:letters>/spectrum/<spectrum_id>` | GET | `marshal_bp.get_spectrum_data` | 04 |
| `/api/object/<int:year><alpha:letters>/spectrum/plot` | GET | `marshal_bp.get_object_spectrum_plot` | 04 |
| `/api/object/<int:year><alpha:letters>/status` | POST | `marshal_bp.api_update_object_status_tns_format` | 04 |
| `/api/object/<object_name>` | GET | `marshal_bp.get_object_api` | 04 |
| `/api/object/<object_name>/comments` | POST | `marshal_bp.add_object_comment` | 04 |
| `/api/object/<object_name>/comments` | GET | `marshal_bp.get_object_comments` | 04 |
| `/api/object/<object_name>/delete` | DELETE | `marshal_bp.api_delete_object` | 04 |
| `/api/object/<object_name>/detect_cross_match` | GET | `web_api.trigger_detect_cross_match` | 08 |
| `/api/object/<object_name>/detect_images` | GET | `web_api.list_detect_images` | 08 |
| `/api/object/<object_name>/detect_images/generate` | POST | `web_api.generate_detect_images` | 08 |
| `/api/object/<object_name>/edit` | POST | `marshal_bp.api_edit_object` | 04 |
| `/api/object/<object_name>/permissions` | POST | `marshal_bp.add_object_permission_api` | 04 |
| `/api/object/<object_name>/permissions` | GET | `marshal_bp.get_object_permissions_api` | 04 |
| `/api/object/<object_name>/permissions` | DELETE | `marshal_bp.remove_object_permission_api` | 04 |
| `/api/object/<object_name>/photometry` | GET | `marshal_bp.get_object_photometry_generic` | 04 |
| `/api/object/<object_name>/photometry` | POST | `marshal_bp.upload_photometry_generic` | 04 |
| `/api/object/<object_name>/photometry/batch` | POST | `marshal_bp.upload_photometry_batch_generic` | 04 |
| `/api/object/<object_name>/photometry/download` | GET | `marshal_bp.download_photometry_generic` | 04 |
| `/api/object/<object_name>/photometry/plot` | GET | `marshal_bp.get_object_photometry_plot_generic` | 04 |
| `/api/object/<object_name>/source-permissions` | GET | `marshal_bp.get_source_permissions_api` | 04 |
| `/api/object/<object_name>/source-permissions/batch` | POST | `marshal_bp.set_source_permissions_batch_api` | 04 |
| `/api/object/<object_name>/sources` | GET | `marshal_bp.get_object_sources` | 04 |
| `/api/object/<object_name>/spectroscopy` | GET | `marshal_bp.get_object_spectroscopy_generic` | 04 |
| `/api/object/<object_name>/spectrum/plot` | GET | `marshal_bp.get_object_spectrum_plot_generic` | 04 |
| `/api/object/<object_name>/status` | POST | `marshal_bp.api_update_object_status_generic` | 04 |
| `/api/object/<path:object_name>/fetch_photometry` | POST | `web_api.fetch_photometry` | 08 |
| `/api/object/<path:object_name>/flag_status` | GET | `web_api.get_flag_status` | 08 |
| `/api/object/<path:object_name>/pin_status` | GET | `web_api.get_pin_status` | 08 |
| `/api/object/<path:object_name>/toggle_flag` | POST | `web_api.update_flag_status` | 08 |
| `/api/object/<path:object_name>/toggle_pin` | POST | `web_api.toggle_pin_status` | 08 |
| `/api/object/<string:object_name>/spectroscopy` | POST | `marshal_bp.upload_spectroscopy_generic` | 04 |
| `/api/objects` | POST | `web_api.add_object` | 08 |
| `/api/objects` | GET | `web_api.api_get_objects` | 08 |
| `/api/objects/<path:object_name>` | GET | `astronomy_tools.api_public_object` | 06 |
| `/api/observation_log_months` | GET | `private_area.api_get_observation_log_months` | 07 |
| `/api/observation_logs` | GET,POST | `private_area.api_get_observation_logs` | 07 |
| `/api/photometry/<int:point_id>` | DELETE | `marshal_bp.delete_photometry_point` | 04 |
| `/api/profile/join_group` | POST | `auth.profile_join_group` | 01 |
| `/api/profile/join_group` | POST | `basic.api_join_group` | 01 |
| `/api/profile/leave_group` | POST | `auth.profile_leave_group` | 01 |
| `/api/profile/leave_group` | POST | `basic.api_leave_group` | 01 |
| `/api/profile/request_api_key` | POST | `auth.profile_request_api_key` | 01 |
| `/api/search_target` | GET | `private_area.api_search_target` | 07 |
| `/api/set_host` | POST | `detect.set_host` | 05 |
| `/api/set_object_status` | POST | `detect.set_object_status` | 05 |
| `/api/slideshow` | GET | `basic.get_slideshow` | 01 |
| `/api/spectral-lines` | GET | `marshal_bp.get_spectral_lines` | 04 |
| `/api/spectral-lines/rebuild` | POST | `marshal_bp.rebuild_spectral_lines` | 04 |
| `/api/spectrum/<path:spectrum_id>/download` | GET | `marshal_bp.download_spectrum_file` | 04 |
| `/api/spectrum/<spectrum_id>` | DELETE | `marshal_bp.delete_spectrum` | 04 |
| `/api/stats` | GET | `web_api.api_get_stats` | 08 |
| `/api/target_autocomplete` | GET | `astronomy_tools.target_autocomplete` | 06 |
| `/api/targets` | GET,POST | `private_area.api_observation_targets` | 07 |
| `/api/targets/<int:target_id>` | DELETE | `private_area.api_observation_target_delete` | 07 |
| `/api/targets/<int:target_id>` | PUT | `private_area.api_observation_target_update` | 07 |
| `/api/targets/<int:target_id>/toggle` | PUT | `private_area.api_observation_target_toggle` | 07 |
| `/api/targets/update-mags` | POST | `private_area.api_update_target_mags` | 07 |
| `/api/test` | GET,POST | `web_api.api_test` | 08 |
| `/api/tns/manual-download` | POST | `web_api.manual_tns_download` | 08 |
| `/api/tns/search` | POST | `web_api.search_tns` | 08 |
| `/api/tns/stats` | GET | `web_api.tns_stats_api` | 08 |
| `/api/toggle_flag` | POST | `detect.toggle_flag` | 05 |
| `/api/unset_host` | POST | `detect.unset_host` | 05 |
| `/api/v1/observation_logs` | GET,POST | `web_api.api_v1_observation_logs` | 08 |
| `/api/v1/observation_targets` | GET,POST | `web_api.api_v1_observation_targets` | 08 |
| `/api/visibility/image` | GET | `astronomy_tools.api_visibility_image` | 06 |
| `/api/visibility_data` | POST | `astronomy_tools.visibility_data` | 06 |
| `/astronomy_tools` | GET | `astronomy_tools.astronomy_tools` | 06 |
| `/astronomy_tools/generate_script` | POST | `astronomy_tools.generate_script_route` | 06 |
| `/astronomy_tools/generate_trigger_script` | POST | `astronomy_tools.generate_trigger_script_route` | 06 |
| `/astronomy_tools/get_followup_targets` | GET | `astronomy_tools.get_followup_targets_route` | 06 |
| `/auth/google` | GET | `auth.google_login` | 01 |
| `/auth/google/callback` | GET | `auth.google_callback` | 01 |
| `/calculate_absolute_magnitude` | POST | `astronomy_tools.calculate_absolute_magnitude_route` | 06 |
| `/calculate_redshift` | POST | `astronomy_tools.calculate_redshift` | 06 |
| `/convert_date` | POST | `astronomy_tools.convert_date` | 06 |
| `/convert_dec` | POST | `astronomy_tools.convert_dec` | 06 |
| `/convert_ra` | POST | `astronomy_tools.convert_ra` | 06 |
| `/daily_trigger` | GET | `private_area.daily_trigger` | 07 |
| `/daily_trigger/send_message` | POST | `private_area.daily_trigger_send_message` | 07 |
| `/daily_trigger/send_status` | GET | `private_area.daily_trigger_send_status` | 07 |
| `/debug/database` | GET | `private_area.debug_database` | 07 |
| `/detect` | GET | `detect.detect_results` | 05 |
| `/detect/archives` | GET | `detect.detect_archives` | 05 |
| `/detect_image/<target_name>` | GET | `detect.detect_image` | 05 |
| `/detect_image_by_id/<int:image_id>` | GET | `detect.detect_image_by_id` | 05 |
| `/documents` | GET | `private_area.documents_list` | 07 |
| `/documents/<filename>` | GET | `private_area.document_view` | 07 |
| `/epessto_support` | GET | `private_area.epessto_support_page` | 07 |
| `/exposure_time_calculator` | GET | `astronomy_tools.exposure_time_calculator` | 06 |
| `/finding_chart` | GET | `astronomy_tools.finding_chart` | 06 |
| `/gallery/image/<filename>` | GET | `basic.gallery_image` | 01 |
| `/games` | GET | `games.games` | 06 |
| `/generate_plot` | POST | `astronomy_tools.generate_plot` | 06 |
| `/greatlab_info` | GET | `private_area.greatlab_info` | 07 |
| `/interactive_planner` | GET | `astronomy_tools.interactive_planner` | 06 |
| `/lc_plotter` | GET | `astronomy_tools.lc_plotter` | 06 |
| `/lc_plotter/mw_extinction` | POST | `astronomy_tools.lc_plotter_mw_extinction` | 06 |
| `/lc_plotter/share` | POST | `astronomy_tools.lc_plotter_share` | 06 |
| `/lc_plotter/shared/<share_id>` | GET,POST | `astronomy_tools.lc_plotter_shared` | 06 |
| `/login` | GET | `basic.login` | 01 |
| `/logout` | GET | `auth.logout` | 01 |
| `/marshal` | GET | `marshal.marshal` | 03 |
| `/mount_3d` | GET | `astronomy_tools.mount_3d` | 06 |
| `/mount_torque` | GET | `astronomy_tools.mount_torque` | 06 |
| `/object/<int:year><string:letters>` | GET | `marshal_bp.object_detail_tns_format` | 04 |
| `/object/<path:object_name>` | GET | `marshal_bp.object_detail_generic` | 04 |
| `/observation_planner` | GET | `astronomy_tools.observation_planner` | 06 |
| `/ov_plot/<path:filename>` | GET | `planners.serve_ov_plot` | 05 |
| `/private/calendar` | GET | `private_area.private_calendar` | 07 |
| `/private/projects` | GET | `private_area.private_projects` | 07 |
| `/private/resources` | GET | `private_area.private_resources` | 07 |
| `/private/telescope` | GET | `private_area.private_telescope` | 07 |
| `/profile` | GET | `basic.profile` | 01 |
| `/slideshow/image/<filename>` | GET | `basic.slideshow_image` | 01 |
| `/static/<path:filename>` | GET | `admin.static` | 02 |
| `/static/<path:filename>` | GET | `astronomy_tools.static` | 06 |
| `/static/<path:filename>` | GET | `auth.static` | 01 |
| `/static/<path:filename>` | GET | `basic.static` | 01 |
| `/static/<path:filename>` | GET | `detect.static` | 05 |
| `/static/<path:filename>` | GET | `games.static` | 06 |
| `/static/<path:filename>` | GET | `marshal.static` | 03 |
| `/static/<path:filename>` | GET | `planners.static` | 05 |
| `/static/<path:filename>` | GET | `private_area.static` | 07 |
| `/static/<path:filename>` | GET | `static` | §4 |
| `/static/<path:filename>` | GET | `web_api.static` | 08 |
| `/telescope_simulator` | GET | `astronomy_tools.telescope_simulator` | 06 |
| `/tutorials/images/<path:filename>` | GET | `private_area.serve_tutorial_image` | 07 |
| `/update-profile` | POST | `auth.update_profile` | 01 |

---

## 附錄 B：驗證基準（重構前 commit `c7f91a4`，2026-09-21）

### B.1 既有測試 `test_detect_pages.py`

6 passed, 1 failed — 失敗項為 `test_embedded_detect_importable` 中過期的常數斷言（`LENS_SEARCH_RADIUS_ARCSEC == 5.0`，DETECT 同步後實際值為 10.0），與程式行為無關；重構後的 `tests/test_detect_pages.py` 已更新該常數。

### B.2 逐頁 GET 冒煙測試（`tests/tools/smoke_pages.py`）

對 4 種身分各發出 133 個 GET 請求（所有安全的 GET 路由 + 16 個帶參數的變體；排除登出、OAuth、有副作用的 `detect_cross_match`、需外部網路的 NED / Legacy Survey 影像）。樣本參數：物件 `2026gzf`、DETECT 日期 `2026-09-21`。原始結果：`docs/baseline/smoke_2026-09-21_c7f91a4.json`；`tests/smoke_baseline.json` 為同一份，供 `tests/test_smoke_pages.py` 回歸比對。

| 身分 | 200 | 302 | 400 | 401 | 403 | 404 | 410 | 例外 |
|---|---|---|---|---|---|---|---|---|
| anon | 48 | 16 | 5 | 20 | 42 | 1 | 1 | 0 |
| guest | 69 | 15 | 8 | 7 | 31 | 2 | 1 | 0 |
| member | 89 | 5 | 12 | 6 | 17 | 2 | 1 | 1 |
| admin | 108 | 3 | 12 | 6 | 0 | 2 | 1 | 1 |

（例外 = `/private/calendar` 的 `TemplateNotFound`，見已知問題 9。）

**重構後比對結果**：532 組（身分 × URL）的狀態碼、Content-Type、渲染模板、redirect 目標 **全部相同**；路由表 250 條規則與 endpoint→函式名稱對應 **完全相同**。唯二內容長度差異：`/api/games/leaderboard`（重構後讀到 `app/data/` 內既有的排行榜檔，原本因路徑錯誤永遠為空）與 `/api/log/*`（日誌本身變長）。

### B.3 逐 URL 狀態碼（重構前）

| URL | anon | guest | member | admin |
|---|---|---|---|---|
| `/` | 200 | 200 | 200 | 200 |
| `/admin` | 302 | 302 | 302 | 200 |
| `/admin/available-users/GREAT_Lab` | 403 | 403 | 403 | 200 |
| `/admin/check-consistency` | 403 | 403 | 403 | 200 |
| `/admin/database` | 302 | 302 | 302 | 200 |
| `/admin/default-source-permissions` | 403 | 403 | 403 | 200 |
| `/admin/detect-status` | 403 | 403 | 403 | 200 |
| `/admin/log` | 302 | 302 | 200 | 200 |
| `/admin/photometry-fetch-status` | 403 | 403 | 403 | 200 |
| `/admin/scheduled-jobs-status` | 403 | 403 | 403 | 200 |
| `/admin/sources/all` | 403 | 403 | 403 | 200 |
| `/admin/sources/search` | 403 | 403 | 403 | 200 |
| `/admin/tns-task-status` | 403 | 403 | 403 | 200 |
| `/admin/user-groups/m1129008@gm.astro.ncu.edu.tw` | 403 | 403 | 403 | 200 |
| `/api` | 200 | 200 | 200 | 200 |
| `/api/admin/database/status` | 403 | 403 | 403 | 200 |
| `/api/admin/private_area/page_perms` | 403 | 403 | 403 | 200 |
| `/api/auto-snooze/stats` | 403 | 200 | 200 | 200 |
| `/api/auto-snooze/status` | 403 | 403 | 403 | 200 |
| `/api/auto_exposure` | 401 | 400 | 400 | 400 |
| `/api/classifications` | 200 | 200 | 200 | 200 |
| `/api/coords` | 400 | 400 | 400 | 400 |
| `/api/date` | 400 | 400 | 400 | 400 |
| `/api/detect/cache_status` | 401 | 401 | 400 | 400 |
| `/api/detect/followup_tracker` | 401 | 401 | 200 | 200 |
| `/api/detect/lightcurve/2026acna` | 401 | 401 | 200 | 200 |
| `/api/distance` | 400 | 400 | 400 | 400 |
| `/api/documents/Test.md/content` | 403 | 403 | 200 | 200 |
| `/api/documents/settings` | 403 | 403 | 200 | 200 |
| `/api/epessto_support/image/tAT2026kiz_20260504_Gr13_Free_slit1.0_1_f.asci` | 403 | 403 | 401 | 401 |
| `/api/epessto_support/room/current` | 403 | 403 | 200 | 200 |
| `/api/epessto_support/room/members` | 403 | 403 | 401 | 401 |
| `/api/epessto_support/rooms/live` | 403 | 403 | 200 | 200 |
| `/api/epessto_support/session` | 403 | 403 | 401 | 401 |
| `/api/exposure_time_calculator/presets` | 200 | 200 | 200 | 200 |
| `/api/finding_chart/surveys` | 200 | 200 | 200 | 200 |
| `/api/gallery` | 200 | 200 | 200 | 200 |
| `/api/games/leaderboard` | 200 | 200 | 200 | 200 |
| `/api/get_object_status` | 401 | 200 | 200 | 200 |
| `/api/greatlab_links` | 401 | 200 | 200 | 200 |
| `/api/groups` | 403 | 200 | 200 | 200 |
| `/api/kn_model` | 403 | 200 | 200 | 200 |
| `/api/log/content` | 403 | 403 | 400 | 400 |
| `/api/log/daemon/content` | 403 | 403 | 400 | 400 |
| `/api/log/files` | 403 | 403 | 200 | 200 |
| `/api/log/sources` | 403 | 403 | 400 | 400 |
| `/api/marshal/pinned-objects` | 200 | 200 | 200 | 200 |
| `/api/marshal/recent-comments` | 200 | 200 | 200 | 200 |
| `/api/marshal/recent-tns-updates` | 200 | 200 | 200 | 200 |
| `/api/marshal/top-viewed` | 200 | 200 | 200 | 200 |
| `/api/members` | 401 | 200 | 200 | 200 |
| `/api/object/2026gzf` | 200 | 200 | 200 | 200 |
| `/api/object/2026gzf/photometry` | 200 | 200 | 200 | 200 |
| `/api/object/2026gzf/photometry/download` | 403 | 200 | 200 | 200 |
| `/api/object/2026gzf/photometry/plot` | 200 | 200 | 200 | 200 |
| `/api/object/2026gzf/spectroscopy` | 403 | 200 | 200 | 200 |
| `/api/object/2026gzf/spectrum/96689` | 403 | 200 | 200 | 200 |
| `/api/object/2026gzf/spectrum/plot` | 403 | 200 | 200 | 200 |
| `/api/object/2026gzf/comments` | 200 | 200 | 200 | 200 |
| `/api/object/2026gzf/detect_images` | 200 | 200 | 200 | 200 |
| `/api/object/2026gzf/permissions` | 403 | 200 | 200 | 200 |
| `/api/object/2026gzf/source-permissions` | 403 | 403 | 403 | 200 |
| `/api/object/2026gzf/sources` | 403 | 403 | 403 | 200 |
| `/api/object/2026gzf/flag_status` | 401 | 200 | 200 | 200 |
| `/api/object/2026gzf/pin_status` | 200 | 200 | 200 | 200 |
| `/api/objects` | 200 | 200 | 200 | 200 |
| `/api/objects/2026gzf` | 200 | 200 | 200 | 200 |
| `/api/observation_log_months` | 401 | 200 | 200 | 200 |
| `/api/observation_logs` | 401 | 400 | 400 | 400 |
| `/api/search_target` | 401 | 200 | 200 | 200 |
| `/api/slideshow` | 200 | 200 | 200 | 200 |
| `/api/spectral-lines` | 403 | 200 | 200 | 200 |
| `/api/spectrum/96689/download` | 403 | 404 | 404 | 404 |
| `/api/stats` | 200 | 200 | 200 | 200 |
| `/api/target_autocomplete` | 200 | 200 | 200 | 200 |
| `/api/targets` | 401 | 200 | 200 | 200 |
| `/api/test` | 401 | 401 | 401 | 401 |
| `/api/tns/stats` | 403 | 200 | 200 | 200 |
| `/api/v1/observation_logs` | 401 | 401 | 401 | 401 |
| `/api/v1/observation_targets` | 401 | 401 | 401 | 401 |
| `/api/visibility/image` | 400 | 400 | 400 | 400 |
| `/astronomy_tools` | 200 | 200 | 200 | 200 |
| `/astronomy_tools/get_followup_targets` | 200 | 200 | 200 | 200 |
| `/daily_trigger` | 302 | 302 | 200 | 200 |
| `/daily_trigger/send_status` | 403 | 403 | 200 | 200 |
| `/debug/database` | 403 | 403 | 403 | 200 |
| `/detect` | 302 | 302 | 200 | 200 |
| `/detect/archives` | 302 | 302 | 200 | 200 |
| `/detect_image/2026acna` | 401 | 401 | 200 | 200 |
| `/detect_image_by_id/7692` | 401 | 200 | 200 | 200 |
| `/documents` | 302 | 302 | 200 | 200 |
| `/documents/Test.md` | 302 | 302 | 200 | 200 |
| `/epessto_support` | 302 | 302 | 200 | 200 |
| `/exposure_time_calculator` | 200 | 200 | 200 | 200 |
| `/finding_chart` | 200 | 200 | 200 | 200 |
| `/gallery/image/Kinder_dark_jpg_1780826642.jpg` | 200 | 200 | 200 | 200 |
| `/games` | 200 | 200 | 200 | 200 |
| `/greatlab_info` | 302 | 302 | 200 | 200 |
| `/interactive_planner` | 200 | 200 | 200 | 200 |
| `/lc_plotter` | 200 | 200 | 200 | 200 |
| `/lc_plotter/shared/406f8e2fe8c446039e302cb9` | 410 | 410 | 410 | 410 |
| `/login` | 200 | 200 | 200 | 200 |
| `/marshal` | 200 | 200 | 200 | 200 |
| `/mount_3d` | 200 | 200 | 200 | 200 |
| `/mount_torque` | 200 | 200 | 200 | 200 |
| `/object/2026gzf` | 200 | 200 | 200 | 200 |
| `/observation_planner` | 200 | 200 | 200 | 200 |
| `/ov_plot/observing_tracks_06a82275ce9a411ea9a3e84e4842480e.jpg` | 200 | 200 | 200 | 200 |
| `/private/calendar` | 302 | 302 | EXC | EXC |
| `/private/projects` | 302 | 302 | 302 | 302 |
| `/private/resources` | 302 | 302 | 302 | 302 |
| `/private/telescope` | 302 | 302 | 302 | 302 |
| `/profile` | 302 | 200 | 200 | 200 |
| `/slideshow/image/6888.jpg` | 200 | 200 | 200 | 200 |
| `/static/css/_theme.css` | 200 | 200 | 200 | 200 |
| `/telescope_simulator` | 200 | 200 | 200 | 200 |
| `/tutorials/images/nope.png` | 404 | 404 | 404 | 404 |
| `/marshal?status=followup` | 200 | 200 | 200 | 200 |
| `/marshal?page=2` | 200 | 200 | 200 | 200 |
| `/api/objects?limit=5` | 200 | 200 | 200 | 200 |
| `/api/objects?status=followup&limit=5` | 200 | 200 | 200 | 200 |
| `/detect?detect_results=2026-09-21` | 302 | 302 | 200 | 200 |
| `/api/target_autocomplete?q=2026` | 200 | 200 | 200 | 200 |
| `/api/search_target?q=2026` | 401 | 200 | 200 | 200 |
| `/api/log/content?date=2026-09-21` | 403 | 403 | 200 | 200 |
| `/api/log/sources?date=2026-09-21` | 403 | 403 | 200 | 200 |
| `/api/marshal/top-viewed?mode=week` | 200 | 200 | 200 | 200 |
| `/api/distance?z=0.1` | 200 | 200 | 200 | 200 |
| `/api/coords?ra=10.5&dec=-20.25` | 400 | 400 | 400 | 400 |
| `/api/date?mjd=60000` | 200 | 200 | 200 | 200 |
| `/admin/sources/search?q=ATLAS` | 403 | 403 | 403 | 200 |
| `/api/observation_logs?month=2026-09` | 401 | 400 | 400 | 400 |
| `/api/auto_exposure?mag=18&telescope=LOT&filter=r` | 401 | 200 | 200 | 200 |
