# 背景排程、每日/每小時工作與服務模組

> **注意**：本章記錄的是重構前（commit `c7f91a4`，2026-09-21）的狀態，檔案路徑為舊位置（`app/routes/…`、`app/modules/…`）。新位置請對照 `docs/ARCHITECTURE.md` §6「新舊路徑對照」；功能與行為在重構後完全相同。

> 本章所有內容均逐一對照 `app/main.py`、`app/modules/*.py`、`app/modules/database/*.py`、`app/routes/**/*.py`、`app/modules/DETECT/function/**` 原始碼確認（2026-09-21 工作樹，commit `c7f91a4`）。路徑一律相對於 `app/`（或標明相對於 repo 根目錄），凡由 `__file__` 推算出的路徑均標注「(由 `__file__` 推算)」。

---

## 排程總表

### 排程引擎與時區假設

| 項目 | 實際值（原始碼確認） |
| --- | --- |
| 引擎 | `apscheduler.schedulers.background.BackgroundScheduler(daemon=True)`（`app/main.py` L293），安裝版本 apscheduler 3.11.3 |
| 時區 | **未傳入 `timezone` 參數** → APScheduler 3.x 預設 `tzlocal.get_localzone()`，即**主機系統時區**。程式註解、`admin_routes._SCHEDULED_JOBS` 的文字標籤與 `_calc_next_run()` 皆假設 **UTC**；本開發機 `/etc/localtime -> Asia/Taipei`。若正式主機時區非 UTC，cron 類工作的實際觸發時間會與「UTC」標籤相差時差（例如 `hour=3` 在 Asia/Taipei 主機是台北 03:00 = UTC 前一日 19:00）。**需確認正式主機時區**。 |
| job 預設 | `misfire_grace_time=1` 秒、`coalesce=True`、`max_instances=1`；executor 為 `ThreadPoolExecutor(max_workers=10)`（APScheduler 預設） |
| 註冊條件 | 全部 `add_job` 都包在 `if not config.DEBUG:` 之內；`_scheduler.start()` 不論 DEBUG 都會執行（DEBUG 時是空排程器） |
| 包裝 | 每個 job 以 `_tracked(job_id, fn)` 包裝：執行前 `job_status.record_start(job_id)`，成功 `record_finish(job_id, True)`，例外 `record_finish(job_id, False, str(exc)[:200])` 後 re-raise |
| 狀態引用 | `scheduler_state.scheduler = _scheduler`（僅持有檔案鎖的行程有值） |

### APScheduler 註冊的 job（`app/main.py` L296–L308）

| job id | trigger | 時間（scheduler 時區，見上） | 呼叫函式 | DEBUG 模式 |
| --- | --- | --- | --- | --- |
| `daily_backup` | cron | 每日 03:00 | `modules.backup.run_daily_backup` | 停用 |
| `daily_phot_fetch` | cron | 每日 03:30 | `modules.phot_scheduler.fetch_inbox_photometry` | 停用 |
| （已註解）`hourly_missing_phot` | cron `minute=0` | 每小時 | `fetch_missing_photometry` | **未註冊**（L298 註解掉） |
| `daily_target_mag_update` | cron | 每日 05:00 | `modules.phot_scheduler.update_target_mags` | 停用 |
| `daily_retire_stale_followups` | cron | 每日 05:30 | `modules.phot_scheduler.retire_stale_followups` | 停用 |
| `daily_host_redshift_sync` | cron | 每日 06:00 | `modules.database.transient.sync_host_redshifts` | 停用 |
| `db_monitor` | interval | 每 10 分鐘 | `modules.db_monitor.check_and_alert` | 停用 |
| `db_recycle` | interval | 每 30 分鐘 | `modules.database.recycle_idle_connections` | 停用 |
| `detect_page_prewarm` | interval | 每 30 分鐘 | `routes.detect.detect_routes.prewarm_detect_page_cache`（無參數） | 停用 |
| `daily_detect_followups` | cron | 每日 04:00 | `modules.detect_pipeline.run_followups` | 停用；另需 `detect_pipeline.ENABLED` 為真（`DETECT_IN_WEB`） |

### 啟動時立即執行的工作（`app/main.py` L309–L319）

| 順序 | 條件 | 動作 | 同步/非同步 |
| --- | --- | --- | --- |
| 1 | 持有檔案鎖 | `_scheduler.start()` | – |
| 2 | `not DEBUG` | `_tracked('daily_backup', run_daily_backup)()` | **同步**（在 import `main.py` 時執行 `pg_dump`，timeout 300 s；當日檔已存在則跳過） |
| 3 | `not DEBUG` | `_tracked('detect_page_prewarm', prewarm_detect_page_cache)(prewarm_days=1, refresh_latest=True, force_latest=True, app_obj=app)` | 內部起 daemon thread |
| 4 | `not DEBUG` | `start_auto_tns_downloader(log_dir=app/log)` | daemon thread `auto_tns_download` |
| 5 | `not DEBUG` | `start_gap_filler(log_dir=app/log)` | daemon thread `tns_gap_filler` |
| – | `not DEBUG`（已註解） | `start_gcn_listener(log_dir=...)`（L313 註解、L258 import 也註解） | 未啟動 |
| 6 | **不論 DEBUG** | `_warm_spec_lines()` = `spectral_lines.warm_cache_async()` | daemon thread `nist-spec-lines` |

### 非 APScheduler 的常駐執行緒

| 執行緒名稱 | 啟動函式 | 週期 | 備註 |
| --- | --- | --- | --- |
| `auto_tns_download` | `auto_tns_download.start_auto_tns_downloader()` | 每 10 s 輪詢 `datetime.now(timezone.utc)`；分鐘 15/45 做 hourly，01/04/12 UTC 整點做 daily | **這條執行緒真正以 UTC 判斷**（與 APScheduler 不同） |
| `tns_gap_filler` | `tns_gap_filler.start_gap_filler()` | 啟動後等 10 分鐘，之後每 1 小時掃描一次 | 有 `_stop_event`；`stop_gap_filler()` 全站沒有呼叫點 |
| `gcn_alert` | `GCN_alert.start_gcn_listener()` | Kafka consumer 無限迴圈 | **已停用**（main.py 註解） |
| `nist-spec-lines` | `spectral_lines.warm_cache_async()` | 一次性（跑完即結束） | 每次行程啟動都會重建（見「已知問題」） |
| （臨時）`detect_manual`、TNS manual、phot fetch 等 | `admin_routes` / `private_area_routes` 內 `threading.Thread(daemon=True)` | 一次性 | 由管理頁按鈕觸發 |
| （臨時）DETECT page build | `detect_routes._start_detect_page_build()` | 一次性 | 快取重建 |

### `.background_jobs.lock` 檔案鎖與 gunicorn 多 worker

- 路徑：`app/log/.background_jobs.lock`（`os.path.join(current_dir, 'log', ...)`，由 `main.py` 的 `__file__` 推算）。以 `open(..., 'w')` 開啟（會清空為 0 byte）後 `fcntl.flock(fd, LOCK_EX | LOCK_NB)`；fd 存在模組全域 `_bg_lock_fd`，行程存活期間不關閉，所以鎖到行程結束才釋放。
- 取得鎖的行程：建立 scheduler、註冊 job、跑啟動工作、起常駐執行緒；失敗（`OSError`）的行程只印 `[PID n] Background jobs already running in another process, skipping.`。
- gunicorn 多 worker（未 `--preload`，每個 worker 各自 import `main.py`）：第一個 import 的 worker 擁有所有背景工作，其他 worker 純服務 HTTP。後果：
  - `scheduler_state.scheduler` 在其他 worker 為 `None` → `/admin/scheduled-jobs-status` 改用 `_calc_next_run()`（純 UTC 計算）估算下次執行時間。
  - `job_status.is_running()` 只在擁有 scheduler 的 worker 準確；已完成的紀錄透過 `.job_status.json` 跨 worker 共享。
  - `detect_pipeline._state`、`phot_scheduler._running`、`admin_routes._tns_task_status/_detect_manual` 都是行程內記憶體，管理頁看到的「是否執行中」取決於請求落到哪個 worker。
  - 若使用 `--preload`：master 會先 import、取得鎖並起執行緒，fork 後 worker 繼承已上鎖的 fd 但執行緒不會複製到子行程 → 背景工作可能只在 master 內、或根本不存在於任何 worker。repo 內**沒有** gunicorn 設定檔（只在 `pyproject.toml` 宣告 `gunicorn>=26.2.0`），啟動命令不明，需另行確認。
  - Werkzeug reloader（DEBUG）會 import 兩次，父行程先取得鎖；DEBUG 下反正 job 全停用。
- 其他 worker 依然會在 import 時執行 `check_db_connection()`、`init_connection_pool()`（含 `_ensure_extra_tables()`）、`setup_logging()`、以及 `auth.py` import 時的 `_ensure_api_key_request_col()`。

### `app/log/.job_status.json` 格式（`modules/job_status.py`）

```json
{
  "<job_id>": {
    "started_at":  "2026-09-14T11:26:53.560959+00:00",
    "finished_at": "2026-09-14T11:26:58.097521+00:00",
    "status":      "success" | "error",
    "message":     "objects 1, confirmed 1, review 0, none 0"
  }
}
```

- 只寫入**已完成**（有 `finished_at`）的項目；`record_start()` 不寫檔。寫入方式：先寫 `.job_status.json.tmp` 再 `os.replace()`（原子替換）。
- 讀取有 10 秒快取（`_FILE_CACHE_TTL`），`get_all()` = 檔案內容 ∪ 行程內 `_registry`（行程內優先）。
- 可能出現的 job id：上表 9 個 scheduler id，加上 `detect_pipeline._job_id(label)` 產生的 `detect_<label>`（label 小寫、空白與 `-` 換成 `_`）：`detect_tns_hourly`、`detect_tns_daily`、`detect_tns_hourly_(manual)`、`detect_tns_daily_(manual)`、`detect_follow_up`、`detect_object_<name>`、`detect_recent_<h>h`、`detect_manual`。
- 現況檔案內容只有 `detect_manual` 一筆（本機為 DEBUG 模式）。

---

## 模組詳述

### `app/main.py` 排程區塊（`# DAILY BACKUP SCHEDULER`）與 log 初始化

- **用途**：Flask 入口；載入 `kinder.env`、設定 `sys.path`（`modules/`、`modules/DETECT_pipe/modules`（**此目錄不存在**）、`modules/CASTOR/src`、`modules/DETECT`）、`os.environ.setdefault("DETECT_DATA_DIR", app/modules/DETECT/data)`、`iers.conf.auto_download = False`、`setup_logging(app/log)`、建 app、`check_db_connection()`、`init_connection_pool()`、註冊 blueprint，最後是背景工作區塊。
- **log 初始化順序**：`setup_logging(os.path.join(current_dir, 'log'))` 在 `from modules.config import config` 之前執行，確保後續所有 import 的 `print()` 都進入日誌。
- **access log**：`_ACCESS_LOG_ENABLED = os.getenv('ACCESS_LOG_ENABLED', '0')` ∈ `{'1','true','yes','on'}` 才啟用；logger 名稱 `web.request`；略過前綴 `/static/`、`/api/log/content`、`/api/log/daemon/content`；欄位 `event=http_access method path status duration_ms bytes ip(X-Forwarded-For 優先) user(session email 或 anon) ua(截 120 字)`。
- **觸發方式**：import 時執行（gunicorn worker 啟動或 `python app/main.py`）。
- **呼叫者**：無（入口）。
- **注意**：背景區塊 import 了 `routes.detect.detect_routes.prewarm_detect_page_cache` 與 `modules.database.transient.sync_host_redshifts`，因此 job 函式跨層直接綁到 route 模組。

### `app/modules/log_setup.py`

- **用途**：每日一檔的檔案 logger；把 `sys.stdout` 導入 logging。
- **公開函式**
  - `setup_logging(log_dir: str) -> None`：設定 root logger（INFO）、掛 `DailyFileHandler`、格式 `'%(asctime)s [%(name)s] %(levelname)s %(message)s'`（`datefmt='%Y-%m-%d %H:%M:%S'`，時間為**本機時間**的 `asctime`）、把 `werkzeug`/`apscheduler`/`urllib3`/`httpx` 設為 WARNING、`logging.captureWarnings(True)`、`sys.stdout = _StreamToLogger(logging.getLogger('app'), INFO)`。
  - `get_log_dir() -> str`：回傳 `setup_logging` 記下的目錄（供 `web_log_routes` 使用）。
  - `DailyFileHandler(log_dir, backup_count=7, max_file_bytes=15 MiB, max_line_chars=1600)`：檔名 `{YYYY-MM-DD}.log`，日期以 **UTC+8**（`_UTC_PLUS_8`）決定；每次 emit 檢查日期換檔並 `_cleanup()` 只保留最新 7 個符合 `len(f)==14` 的 `.log`；超過 `max_file_bytes` 時以 `'w'` **重新開檔清空**並寫一行警告；單行超過 `max_line_chars` 截斷加 ` ...[truncated]`。
  - `_StreamToLogger`：逐行緩衝，非空行才寫 log；`isatty()` False、`fileno()` 拋 `UnsupportedOperation`。
- **只重導 stdout**：程式碼只替換 `sys.stdout`；`sys.stderr` 未替換（docstring 寫「stdout / stderr」但實作沒有）。`traceback.print_exc()` 走 stderr，不會進日誌檔。
- **環境變數**：`LOG_MAX_FILE_BYTES`（預設 15728640）、`LOG_MAX_LINE_CHARS`（預設 1600）。
- **logger 命名慣例**：多數模組 `logging.getLogger(__name__)` → `modules.xxx` / `modules.database.xxx` / `routes.xxx.yyy`；顯式命名的有 `auto_tns_download`、`tns_gap_filler`、`gcn_alert`、`tns_fetch`（`TNS_object_fetch.py`）、`app`（所有 `print()`）、`web.request`（access log）、`py.warnings`（captureWarnings）。DETECT 內嵌套件全用 `print()` → 以 `[app]` 出現。
- **讀寫檔案**：`app/log/YYYY-MM-DD.log`。
- **呼叫者**：`main.py`（`setup_logging`）、`routes/auth/web_log_routes.py`（`get_log_dir`，四處）。
- **注意**：`web_log_routes._DAEMON_LOG_FILES = {gcn_alert.log, detect.log, tns_fetch.log}` 對應的檔案**沒有任何模組會寫**（各 `start_*` 函式的 `log_dir` 參數都被忽略，全部走 root logger），管理頁的 daemon log 分頁永遠是空的。

### `app/modules/job_status.py`、`app/modules/scheduler_state.py`

- **用途**：job 最近一次執行狀態的登錄簿（行程內 dict + 跨 worker 的 JSON 檔）；`scheduler_state` 只有一個全域變數 `scheduler = None` 供 route 查 `next_run_time`。
- **公開函式**（`job_status`）
  - `record_start(job_id)`：寫入 `started_at`（UTC ISO）、清空 `finished_at`。
  - `record_finish(job_id, success, message='')`：寫入 `finished_at`、`status`、`message`，並 `_persist()`。
  - `is_running(job_id) -> bool`：只看行程內 `_registry`。
  - `get_all() -> dict`：合併檔案與行程內紀錄。
- **檔案**：`app/log/.job_status.json`（`os.path.join(os.path.dirname(__file__), '..', 'log', '.job_status.json')`，由 `__file__` 推算）與暫存 `.job_status.json.tmp`。
- **鎖/狀態**：`_lock = threading.Lock()`、`_registry`、`_file_cache`、`_last_read_ts`。
- **呼叫者**：`main.py`（`_tracked`）、`modules/detect_pipeline.py`（`_Run` context manager）、`routes/auth/admin_routes.py`（`/admin/detect-status`、`/admin/scheduled-jobs-status`）。`scheduler_state`：`main.py`、`admin_routes.scheduled_jobs_status`。

### `app/modules/backup.py`

- **用途**：以 `pg_dump` 備份 `Kinder` 資料庫。
- **公開函式**：`run_daily_backup(force=False)`：對 `DATABASES = ['Kinder']` 逐一輸出 `Kinder_backup_{YYYYMMDD}.sql`（`datetime.now()` **本機日期**）；檔案已存在且非 `force` 則跳過；`pg_dump -h -p -U -F p -f <file> Kinder`，`PGPASSWORD` 透過環境傳入，`timeout=300`；失敗刪除半成品；最後 `_prune_old_backups()` 依檔名排序只保留 `KEEP_DAYS = 15` 份。
- **`_find_pg_dump()`**：依序找 `/usr/local/opt|/opt/homebrew/opt/postgresql*/bin/pg_dump` → Homebrew Cellar → `shutil.which` → `/usr/bin`、`/usr/local/bin`、`/opt/homebrew/bin`；找不到拋 `FileNotFoundError`（macOS/Homebrew 優先的搜尋順序）。
- **觸發**：排程 `daily_backup`（03:00）、啟動時同步執行一次、`POST /admin/backup-now`（`force=True`，同步）。
- **資料表**：整庫 dump（plain SQL）。
- **檔案**：`app/data/backups/`（`BACKUP_DIR = basedir/../data/backups`，由 `__file__` 推算；本機不存在，`app/data/` 整體被 `.gitignore`）。
- **環境變數**：`PG_HOST`、`PG_PORT`、`PG_USER`、`PG_PASSWORD`（模組自行 `load_dotenv(kinder.env)`）。
- **呼叫者**：`main.py`、`routes/auth/admin_routes.py:502`。
- **注意**：備份存在 web 主機同一顆磁碟的 `app/data/backups`，沒有異地/壓縮；`pg_dump` 版本需與伺服器相容。

### `app/modules/db_monitor.py`

- **用途**：監控 psycopg2 連線池使用率與伺服器端 `pg_stat_activity`，超過門檻寄 **email**（不是 Slack）。
- **公開函式**：`check_and_alert()`：`get_pool_stats()`（只看 `modules.database` 的池）+ `_query_pg_connections()`（`SELECT COUNT(*) ... FROM pg_stat_activity WHERE datname = current_database() AND usename = PG_USER`，分 active/idle/idle in transaction）；每次都 `logger.info` 一行統計；`usage_pct >= 85` → CRITICAL、`>= 60` → WARNING；同一等級 30 分鐘內只寄一封（`_should_alert`）。
- **告警送去哪**：SMTP（`SMTP_SERVER` 預設 smtp.gmail.com、`SMTP_PORT` 587、STARTTLS、`SENDER_EMAIL`/`SENDER_PASSWORD`）寄到**硬編碼** `ALERT_TO = ["m1139005@gm.astro.ncu.edu.tw"]`。憑證缺少時只 warning 不寄。
- **觸發**：排程 `db_monitor` 每 10 分鐘。
- **資料表**：只讀 `pg_stat_activity`。
- **鎖/狀態**：`_last_alert: dict[level -> datetime]`、`_lock`。
- **注意**：`_smtp_config()` 每次呼叫 `load_dotenv(kinder.env, override=True)`，會覆寫整個行程的環境變數（`detect_pipeline._pin_db_env` 的存在就是為了對抗這類覆寫）。

### `app/modules/auto_tns_download.py`

- **用途**：常駐執行緒，定時從 TNS 下載公開物件 CSV（每小時檔 / 每日檔）匯入 `transient.objects`、種入發現點光度、自動 Snooze、觸發 DETECT 與光度抓取。
- **公開函式**
  - `download_TNS_api_hr(hr, debug=False) -> bool`：下載 `https://www.wis-tns.org/system/files/tns_public_objects/tns_public_objects_{HH}.csv.zip`。
  - `download_TNS_api(year, month, day, debug=False) -> bool`：下載 `tns_public_objects_{YYYYMMDD}.csv.zip`。
  - `download_TNS_api_with_fallback(year, month, day, debug=False) -> bool`：只試每日檔，失敗記 warning（沒有 hourly fallback，名稱已不符）。
  - `_download_and_extract(url, zip_path, renamed_csv, debug)`：POST（header `user-agent: tns_marker{"tns_id":..,"type":"bot","name":".."}`、data `api_key`）、timeout 60 s、重試延遲 `[10, 30, 60]` 共 4 次、404 直接 False；解壓到 `SAVE_DIR`，把 `zip_path.stem` 改名為 `tns_public_objects_WORK.csv`（舊檔先刪），zip 刪除。
  - `addin_database(filepath, debug=False, fetch_phot_for_new=False) -> bool`：見下。
  - `last_import_names(new_only=False) -> list`：上一次 `addin_database` 觸及的名稱（行程內 `_last_import`）。
  - `auto_snoozed(time_now_utc, debug=False) -> bool`：見下。
  - `_run_detect_after_import(new_only, label)`：DETECT 後處理。
  - `main()`：迴圈。`start_auto_tns_downloader(log_dir=None)`：起 daemon thread（`_auto_tns_thread_lock` 防重複）。`diagnose_csv_columns(...)`：診斷工具。
- **`main()` 流程**（`datetime.now(timezone.utc)`）
  1. `now.minute in (15, 45)`：`download_TNS_api_hr(f"{now.hour:02d}")` → `addin_database(work_csv, debug=True, fetch_phot_for_new=True)` → 成功則 `_run_detect_after_import(new_only=False, label="TNS-hourly")` → `auto_snoozed(now)`；若 `now.hour == 0` 再跑一次 `auto_snoozed`；`sleep(60)`。
  2. `now.hour in (1, 4, 12) and now.minute == 0`：對 `day_offset in (0, 1, 2)` 各下載每日檔 → `addin_database(work_csv, debug=True)`（**不**抓新物件光度）→ `_run_detect_after_import(new_only=True, label="TNS-daily")` → `auto_snoozed`；`sleep(60)`。
  3. 其他 `sleep(10)`；任何例外記 `logger.exception` 後 `sleep(10)`。
- **`addin_database` 細節**
  - 先 `log_download_attempt(filename)` 取得 `transient.download_logs.log_id`（status 'In Progress'），結束 `update_download_log(log_id, 'completed'|'failed', records_imported, records_updated, error_message)`。
  - CSV 第一行是日期範圍（`next(f)` 跳過），之後 `csv.DictReader`；值 `''`/`'NULL'` → None。
  - 以 **name** 查既有列（`SELECT ... FROM transient.objects WHERE name = %s`）。既有 → `_UPDATE_SQL`：所有欄位 `COALESCE(new, old)`（不以 NULL 覆蓋）；`status = CASE WHEN status='Snoozed' AND new_lastmodified > COALESCE(last_modified_date,0) THEN 'Inbox' ELSE status END`；`last_modified_date = GREATEST(new, old)`。比對 type/redshift/reporting_group/source_group/internal_names/discovery_mag/last_photometry_date 變化寫 audit。
  - 不存在 → `_INSERT_SQL`：`obj_id = kinder_id or objid`、`kinder_id`、`status='Inbox'`、`tag='{}'`、`ON CONFLICT DO NOTHING`；audit `['new_add']`。
  - 批次 `extras.execute_batch(..., page_size=1000)`，每 1000 筆 commit。
  - audit：`log_tns_update_batch([(objid, name, changed_fields, 'auto_tns_download')])` → `transient.tns_update_audit`（懶建表）。喚醒者前置 `'woke: Snoozed -> Inbox'`。
  - 發現點光度：每列 `(name, discoverydate_MJD, discoverymag, filter, source_group)` → `INSERT INTO transient.photometry (obj_id, name, "MJD", mag, mag_err=0.01, filter, source=f"{source_group} (TNS)"|"(TNS)") ON CONFLICT ON CONSTRAINT phot_uniq DO NOTHING`；再對每個 obj_id `UPDATE transient.objects SET last_phot_date=%s, status = CASE WHEN 'Snoozed' THEN 'Inbox' WHEN 'Finish' THEN 'Follow-up' ELSE status END WHERE last_phot_date IS NULL OR last_phot_date < %s`。
  - 結束：`_last_import` 更新、`sync_kinder_ids()`、若 `fetch_phot_for_new` 對每個新名稱呼叫 `download_phot.process_single_object_workflow`（逐一、失敗不中斷）。
- **`auto_snoozed` 規則**：`cutoff_mjd = MJD(今日 UTC) - 15`；只針對 `status = 'Inbox'`；條件 `(last_phot_date IS NOT NULL AND last_phot_date < cutoff) OR (last_phot_date IS NULL AND last_modified_date < cutoff)` → `status='Snoozed'`。**不碰 Follow-up / Finish**。
- **`_run_detect_after_import`**：`detect_pipeline.ENABLED` 且名單非空才跑 `detect_pipeline.run_for_names(names, label)`，之後 `routes.detect.detect_routes._soft_invalidate_page_cache()`（DETECT 頁快取全部標記過期並背景重建）。
- **觸發 `download_phot` 的條件**：只有 `main()` 的 hourly 分支傳 `fetch_phot_for_new=True`；daily 分支與 `admin_routes` 的手動 hourly/daily 都不傳（手動路徑不抓光度）。
- **資料表**：讀寫 `transient.objects`、`transient.photometry`、`transient.download_logs`、`transient.tns_update_audit`；間接（DETECT、download_phot）更多。
- **檔案**：`SAVE_DIR = app/data/tns_api_download_work/`（`_app_dir = dirname(dirname(__file__))`，由 `__file__` 推算；import 時 `mkdir(parents=True, exist_ok=True)`）；`tns_public_objects_{HH|YYYYMMDD}.csv.zip`（暫存後刪）、`tns_public_objects_WORK.csv`（每次覆蓋）。
- **環境變數**：`TNS_BOT_ID`、`TNS_BOT_NAME`、`TNS_API_KEY`（模組自行 `load_dotenv(kinder.env)`）。
- **執行緒/鎖/狀態**：`_auto_tns_thread`、`_auto_tns_thread_lock`、`_last_import`。沒有停止機制。
- **呼叫者**：`main.py`（`start_auto_tns_downloader`）、`routes/auth/admin_routes.py`（`/admin/tns-download-hourly`、`/admin/tns-download-daily`、`/admin/tns-auto-snooze` 各自 import `download_TNS_api_hr`/`download_TNS_api`/`addin_database`/`auto_snoozed`/`SAVE_DIR`/`_run_detect_after_import`）。
- **注意**：hourly 與 daily 共用同一個 `tns_public_objects_WORK.csv`，管理頁手動下載與常駐執行緒可能互相覆蓋；`admin_routes._tns_task_status` 只防手動之間互斥，不防與執行緒併發。

### `app/modules/tns_gap_filler.py`

- **用途**：補漏。`kinder_id = year*1_000_000 + 雙射 base-26 序（a=1…z=26, aa=27）`；找出當年 `[min..max]` 之間缺的 kinder_id，逐一以 TNS API 查詢並插入。
- **公開函式**
  - `fill_year_gaps(year, delay=60.0) -> int`：`sync_kinder_ids()` → `_find_gaps(year)` → 對每個 gap：`_search_tns_exists(name)`（`/api/get/search`）→ 存在則 `sleep(5)` 再 `_get_tns_object(name)`（`/api/get/object`, photometry/spectra 0）→ `_insert_tns_object(reply)`；每個 gap 之間 `sleep(delay)`（60 s）；最後再 `sync_kinder_ids()`。
  - `start_gap_filler(log_dir=None, delay=60.0)`、`stop_gap_filler()`。
  - `_main_loop(delay)`：`_stop_event.wait(600)` 後每小時（`wait(3600)`）對 `datetime.now(timezone.utc).year` 呼叫 `fill_year_gaps`。
- **`_insert_tns_object`**：`INSERT INTO transient.objects (obj_id=kinder_id, name_prefix, name, ra, dec, redshift, type, report_group, source_group, discovery_date, discovery_mag, discovery_filter, reporters, received_date, internal_name, discovery_ADS, class_ADS, creation_date, last_phot_date, last_modified_date, kinder_id, status='Inbox', tag='{}') ON CONFLICT DO NOTHING`；缺座標跳過；不種光度、不寫 audit、不觸發 DETECT。
- **資料表**：`transient.objects`。
- **檔案**：無。
- **環境變數**：`TNS_BOT_ID`、`TNS_BOT_NAME`、`TNS_API_KEY`。
- **執行緒/鎖**：`_gap_filler_thread`、`_gap_filler_lock`、`_stop_event`。
- **呼叫者**：`main.py`（`start_gap_filler`）。`stop_gap_filler` 無人呼叫。
- **注意**：gap 數量大時一輪要 `gaps × 60 s`；跨年後只掃「今年」，去年的缺口不再補；`_find_gaps` 若 DB 錯誤回傳空。

### `app/modules/Manual_tns_download_snoozed.py`（舊版，僅供 `/api/tns/manual-download`、`/api/auto-snooze/manual-run`）

- **與 `auto_tns_download` 的重複/差異**

| 面向 | `auto_tns_download.py` | `Manual_tns_download_snoozed.py` |
| --- | --- | --- |
| 環境變數 | `TNS_BOT_ID` / `TNS_BOT_NAME` / `TNS_API_KEY` | `TNS_HOST` / `API_BASE_URL` / `BOT_ID` / `BOT_NAME` / `API_KEY` —— **kinder.env 中都不存在** → `bot_id`/`api_key` 為 `None` |
| 下載 | 共用 `_download_and_extract`，timeout 60 s | 兩個函式各自實作、`requests.post` **無 timeout** |
| 比對鍵 | `name` | `obj_id`（TNS objid） |
| 既有物件 | 一律 UPDATE（COALESCE），依 lastmodified 決定是否喚醒 | `new_lastmodified <= existing` 直接跳過；否則全欄位覆寫且 `Snoozed → Inbox` 無條件 |
| 新物件 | `obj_id = kinder_id`、寫 `kinder_id` | `obj_id = objid`、**不寫** `kinder_id`（靠事後 `sync_kinder_ids`） |
| 發現點光度 / audit / DETECT / 抓光度 | 有 | 無 |
| `auto_snoozed` | 只動 `Inbox` → `Snoozed` | `status != 'Snoozed'` 全部候選：`Follow-up → Finish`，其他（含 `Finish`、`Inbox`）→ `Snoozed` |
| `log_download_attempt` | `(filename=...)` | `(hour_utc, filename=...)` |

- **公開函式**：`download_TNS_api_hr(hr, debug)`、`download_TNS_api(year, month, day, debug)`、`addin_database(filepath, debug)`、`auto_snoozed(time_now_utc, debug)`、`main()`。
- **檔案**：同一個 `app/data/tns_api_download_work/tns_public_objects_WORK.csv`（`Path(__file__).resolve().parent.parent / "data" / ...`，由 `__file__` 推算）。
- **呼叫者**：`routes/web_api/web_api_routes.py:29` import 三個函式；`POST /api/tns/manual-download`（admin；`hour_offset` 參數）、`POST /api/auto-snooze/manual-run`（admin）。
- **注意**：因為讀不到 bot 憑證，`/api/tns/manual-download` 實務上無法通過 TNS 驗證；`/api/auto-snooze/manual-run` 會把 `Finish` 物件也 Snooze 掉，語意與常駐版不同。

### `app/modules/phot_scheduler.py`

- **用途**：光度批次抓取與觀測目標維護的四個工作。
- **公開函式與狀態**
  - `fetch_inbox_photometry() -> dict`：`search_tns_objects(tag='object', limit=9999, sort_by='name', sort_order='asc')`（`tag='object'` → `o.status = 'Inbox'`）；略過 `name_prefix == 'FRB'`；逐一 `download_phot.process_single_object_workflow(name)`；`_progress = {current, total, success, failed}` 每 50 筆記 log；`_running` + `_lock` 防併發（已在跑回 `{"skipped": True}`）。docstring 寫「UTC+8 09:00」已過時，實際 cron 03:30。
  - `is_running() -> bool`、`get_progress() -> dict`。
  - `fetch_missing_photometry() -> dict`：僅對 `transient.photometry` 筆數為 0 的 Inbox 物件跑 workflow；`_running_missing`/`_lock_missing`；若 `_running`（每日全抓進行中）則跳過；用 `get_tns_db_connection()` 原始池連線（手動 `close()`）。**未排程**（main.py 註解），只有 `POST /admin/run-missing-phot-fetch`。`is_missing_running()`。
  - `update_target_mags() -> dict`：`obs.get_observation_targets()`（讀 `obs.targets`，`is_active`/`id`/`name` 由 `_target_to_dict` 別名）→ 每個 active target：EP 開頭以 `internal_name ILIKE` / `tag` 找 bare name；否則以 `(name_prefix||name)=%s OR name=%s`；取最新非上限 `p.mag`（`CAST(p.mag AS TEXT) NOT LIKE '>%'`，`ORDER BY "MJD" DESC`）→ `UPDATE obs.observation_targets SET mag/name WHERE id` 與 `UPDATE obs.observation_logs SET target_name ...`（AT→SN 改名同步）。
  - `retire_stale_followups() -> dict`：`SELECT name, status, last_phot_date FROM transient.objects WHERE status IN ('Follow-up','Snoozed')`；`Snoozed` → 一律 `update_object_status(name, 'finished')`（→ `Finish`）；`Follow-up` 且 `last_phot_date IS NULL` → Finish；`Follow-up` 有 `last_phot_date` → 嘗試計算天數 > `_FOLLOWUP_RETIRE_DAYS = 2` 才 Finish。
- **觸發**：排程 `daily_phot_fetch`（03:30）、`daily_target_mag_update`（05:00）、`daily_retire_stale_followups`（05:30）；route：`POST /admin/run-photometry-fetch`、`GET /admin/photometry-fetch-status`、`POST /admin/run-missing-phot-fetch`、`POST /admin/run-update-target-mags`、`POST /api/targets/update-mags`（private_area，GREAT Lab 成員或 admin）。route 全部另起 daemon thread。
- **資料表**：`transient.objects`、`transient.photometry`、`obs.targets`（讀）、`obs.observation_targets`/`obs.observation_logs`（寫；見已知問題）。
- **呼叫者**：`main.py`、`routes/auth/admin_routes.py`（L567–L620）、`routes/private_area/private_area_routes.py:1863`。

### `app/modules/download_phot.py`（**未被 git 追蹤**，`.gitignore` 明列 `app/modules/download_phot.py`）

- **用途**：單一物件的光度抓取工作流；輸出到本地文字檔再上傳 `transient.photometry`。
- **公開函式**
  - `process_single_object_workflow(object_name)`：主流程（見下）。
  - `get_photometry(big_name_list, output_dir)`：批次派工到各資料源後逐檔 `bin_photometry_file`。
  - `init_photometry_file`、`write_photometry_to_txt`、`get_discover_mag_from_TNS`、`get_atlas_photometry`、`get_panstarrs_photometry`、`get_ztf_photometry`、`get_lsst_alerce_photometry`、`bin_photometry_file`、`get_tns_internal_name`、`get_object_coordinates`、`update_object_internal_names`、`upload_photometry_to_db`。
- **`process_single_object_workflow` 流程**
  1. `get_object_coordinates`：`SELECT ra, dec FROM transient.objects WHERE name=%s`；沒有 → `status=missing_object` 結束。
  2. 內部名稱：若 `TNSObjectDB.get_photometry(name)` 已有資料 → 讀 DB `internal_name`（**跳過 TNS API**）；否則 `get_tns_internal_name`（TNS `/api/get/object`）→ `update_object_internal_names` 寫回 `transient.objects.internal_name`。
  3. `get_photometry([[name, ra, dec, internal_names_str]], app/data/phot_cache)`：
     - `init_photometry_file` 建 `phot_cache/<YYYY>/<name>_photometry.txt`，表頭 `# Object: / # RA: / # DEC: / # MJD Mag Mag_err Filter Site`。
     - 從 internal names 找 `ATLAS*`、`PS*`、`ZTF*`、`LSST*`（或 ≥15 位純數字）；**四者皆無**才呼叫 `get_discover_mag_from_TNS`（發現點 `MJD mag 0.01 <filter> <family>(TNS)|TNS_Discovery`）。
     - **ATLAS forced photometry**：Playwright headless Chromium 登入 `https://star.pst.qub.ac.uk/sne/atlas4/accounts/login/`（`ATLAS_USER`/`ATLAS_PASS`）→ 搜尋 → 取 candidate id → `/sne/atlas4/lightcurve/<id>/` 的 `<pre>` 逗號分隔（mjd=欄11、mag=欄5、dmag=欄6、filter=欄8）→ Site `ATLAS`。
     - **Pan-STARRS**：同法登入 `https://star.pst.qub.ac.uk/sne/ps13pi/...`（`PANSTARRS_USER`/`PANSTARRS_PASS`）→ `/psdb/lightcurve/<id>/` 空白分隔（mjd,mag,dmag,_,_,filter）→ Site `PS`。
     - **ZTF**：`alerce.core.Alerce().query_lightcurve(ztf_oid, survey="ztf")`（`ZTF_SOURCE='alerce'`）；detections `magpsf/sigmapsf/fid(1=g,2=r,3=i)`；non-detections 距任一 detection ≤5 天者以 `diffmaglim`、err `0.0` 記為上限 → Site `ZTF(alerce)`。
     - **LSST/Rubin**：`query_lightcurve(oid, survey="lsst")`，detections+forced_photometry 的 `psfFlux`（nJy）換算 `m_AB = 31.4 - 2.5 log10(flux)`，非偵測 ≤5 天為上限 → Site `LSST(alerce)`。
     - `bin_photometry_file(path, bin_window=1.0)`：依 (Filter, Site) 分組、以 1 天為 bin；偵測以 flux 加權平均、誤差取 max(傳播, 散佈)；上限（`Mag_err` NaN/99/≤0）取最淺者、`Mag_err=0.0`；**整檔重寫**。
  4. `upload_photometry_to_db`：讀檔、與 `TNSObjectDB.get_photometry` 去重（同 filter+telescope 且 |ΔMJD|<0.001、|Δmag|<0.001）→ `TNSObjectDB.add_photometry_bulk([(name, mjd, mag, mag_err, filter, site)])`（→ `transient.photometry`，負星等剔除，`ON CONFLICT phot_uniq DO NOTHING`，`_mjd_update` 更新 `last_phot_date` 並 `Snoozed → Inbox`）→ `sync_last_photometry_date`。
  5. `phot_file.unlink()` 刪除本地檔（所以 `phot_cache/` 內殘留的檔案 = 上傳失敗或中斷的遺留）。
- **輸出格式**
  - 文字檔：`app/data/phot_cache/<YYYY>/<name>_photometry.txt`（`os.path.join(project_root, "..", "data", "phot_cache")`，`project_root = dirname(__file__)`，由 `__file__` 推算），每列 `MJD Mag Mag_err Filter Site`（binned 後為 `%.6f %.4f %.4f`）。
  - DB：`transient.photometry(obj_id, name, "MJD", mag, mag_err, filter, source)`；`source` = Site 字串（`ATLAS`、`PS`、`ZTF(alerce)`、`LSST(alerce)`、`<family>(TNS)`、`TNS_Discovery`）；唯一鍵 `phot_uniq (obj_id, "MJD", filter, source)`。
- **環境變數**：`ATLAS_USER`、`ATLAS_PASS`、`PANSTARRS_USER`、`PANSTARRS_PASS`、`TNS_BOT_ID`、`TNS_BOT_NAME`、`TNS_API_KEY`（`load_dotenv(kinder.env, override=True)`）。
- **外部服務**：TNS API、QUB ATLAS/Pan-STARRS 網站（需 Playwright + Chromium，`uv run playwright install chromium`）、ALeRCE API。
- **觸發**：`phot_scheduler`（兩個工作）、`auto_tns_download._fetch_phot_for_new_objects`、`POST /api/object/<name>/fetch_photometry`（`web_api_routes:742`，任何登入者，**同步在請求內執行**）。
- **執行緒/鎖**：無（各呼叫者自行防併發；`process_single_object_workflow` 本身無鎖，多路徑可同時對同一物件抓取）。
- **注意**：模組以 `from database import ...`（裸套件名，靠 `sys.path` 的 `app/modules`）而非 `modules.database` → 見已知問題「雙連線池」。L584–L639 是 `get_lsst_alerce_photometry` `return` 之後的死碼（原 Lasair 函式殘骸），`download_dir = Path.cwd()/data/temp_downloads` 也只被死碼使用。

### `app/modules/detect_pipeline.py` 與 `app/modules/detect_cross_match.py`

**`detect_pipeline.py`（內嵌 DETECT 的薄包裝）**

- **與 DETECT 的關係**：`app/modules/DETECT/function/` 是 DETECT 專案 `function/` 套件的 rsync 副本（`scripts/sync_detect.sh`，排除 scheduler/daily/hourly/photometry 等 daemon 專用檔；`DETECT/VERSION` 記 `source:`、`synced:`）。`main.py` 把 `app/modules/DETECT` 加入 `sys.path`，因此以 `from function.run_detect import ...` 匯入。
- **環境變數**：`DETECT_IN_WEB`（預設啟用；`0/false/no/off` 停用 → `ENABLED=False`，所有 `run_*` 回 `{}`）；`DETECT_DATA_DIR`（`main.py` `setdefault` 為 `app/modules/DETECT/data`；DETECT `function/paths.py` 以此決定 `DATA_ROOT`）。
- **`_pin_db_env()`**：每次 run 前把 `PG_HOST/PG_PORT/PG_USER/PG_PASSWORD/PG_DATABASE` 寫回 `os.environ`（DETECT 的 `function/database/__init__.py` 每次連線都重新讀環境變數並嘗試載入自己的 `.env`/`detect.env`（內嵌副本中不存在）；web 端 DB 名稱硬編碼 `Kinder`）。
- **公開函式**：`run_for_names(names, label="Web") -> dict`、`run_single(name) -> dict`、`run_followups() -> dict`、`run_recent(hours=2.0) -> dict`、`is_running() -> bool`、`status() -> dict`。全部在 `_LOCK`（`threading.Lock`）與 `_Run` context manager 內執行；`_Run` 寫 `_state["running"/"last"]` 並呼叫 `job_status.record_start/record_finish('detect_<label>')`。
- **DETECT 實際做的事**（`function/run_detect.py` → `function/module/cross_match.run_cross_match_pipeline`）：以 `transient.objects` 的 ra/dec 為目標 → `desi_cross_match`（`cat.desi` HEALPix cone）→ `lens_cross_match`（`cat.lens`）→ host rule v1（DLR、shred 合併、使用者 host 決定覆寫）→ `screen_target`（分數/標籤/絕對星等/KN 模型 `function/data/kn_lc_mag.txt`）→ 產生 finder（LS DR10 / Legacy Survey / DSS2 / matplotlib fallback）→ `DataUploader.save_cross_match_results`（`transient.cross_matches`）、`save_screen_results`（`transient.detect_screen`、`transient.detect_screen_history`（`CREATE TABLE IF NOT EXISTS` 每次執行）、`transient.objects.tag`（只替換 `DETECT_TAG_VOCAB` 內的標籤）、`transient.objects.brightest_mag/brightest_abs_mag`）、finder 影像寫 `transient.target_images`。
- **SFD dust maps**：`function/module/calculator.py` import 時設定 `dustmaps` `data_dir = DETECT_DATA_DIR/dustmaps`；`_ensure_sfd_maps()` 在第一次查 extinction 時，若 `dustmaps/sfd/SFD_dust_4096_{ngp,sgp}.fits` 不存在則以 `urllib.request.urlretrieve` 從 `https://github.com/kbarbary/sfddata/raw/master/` 下載（各 67,115,520 bytes，共約 128 MiB）。`ext_M_calculator.py` 是同一 calculator 的 shim，因此 marshal 頁面計算絕對星等時也會觸發下載。
- **`status()`**：讀 `DETECT/VERSION`、`DETECT_DATA_DIR`、SFD 是否齊全、`_state`，並查 `transient.detect_screen`（24h 統計、`pending_review`）、`transient.objects`（Follow-up 數）、`transient.cross_matches`、`transient.detect_screen_history`。
- **檔案**：`DETECT_DATA_DIR/crossmatch_images/<name>.png`（`cross_match.py`）、`DETECT_DATA_DIR/marked_images/`（`Legacy_survey_img.py`）、`DETECT_DATA_DIR/dustmaps/sfd/*.fits`。
- **觸發**：排程 `daily_detect_followups`（04:00）；`auto_tns_download._run_detect_after_import`（hourly/daily）；`POST /admin/detect-run`（`kind = followups | recent | names`）；`GET /admin/detect-status`；`GET /api/object/<name>/detect_cross_match`（`force=true` 或從未跑過時 `run_single`）；`POST /api/object/<name>/detect_images/generate`（`run_single`）。
- **呼叫者**：`main.py`、`modules/auto_tns_download.py`、`routes/auth/admin_routes.py`、`routes/web_api/web_api_routes.py`。

**`detect_cross_match.py`（舊版單物件交叉比對，現在主要當讀取層）**

- **公開函式**：`desi_cross_match_single(ra, dec, search_radius=30)`（`cat.desi` cone）、`lens_cross_match_catalogue_single(...)`（`cat.lens`）、`comprehensive_lens_match_single(...)`（astroquery Vizier 線上 11 個透鏡目錄，`VIZIER_TIMEOUT_SEC` 預設 8 s）、`run_all_detect(target_name, ra, dec)`（legacy，docstring 明言已被 `detect_pipeline` 取代）、`has_detect_run(name)`、`save_detect_results(name, results)`、`get_detect_screen_for_target(name)`、`get_detect_results_for_target(name)`。
- **資料表**：`transient.cross_matches`（讀寫）、`transient.detect_screen`（讀）、`cat.desi`/`cat.lens`（讀，經 `database.catalog`）。
- **注意**：`save_detect_results` 與 `get_detect_results_for_target` 每次呼叫都執行 `ALTER TABLE transient.cross_matches ADD COLUMN IF NOT EXISTS ...`（讀取路徑上做 DDL）。錯誤以 `print` 輸出（進 `[app]`）。
- **呼叫者**：`routes/web_api/web_api_routes.py:424`（`has_detect_run`、`get_detect_results_for_target`、`get_detect_screen_for_target`）。

### `app/modules/trigger_send.py`

- **用途**：Daily Trigger 頁把觀測腳本送到 Slack，並記錄「今晚是否已送」。
- **公開函式**
  - `_trigger_day_key(now=None) -> 'YYYY-MM-DD'`：以 Asia/Taipei 為準，**08:00 前算前一天**（觀測夜的日期）。
  - `get_send_status() -> dict`：讀狀態檔，`day` 與目前 day_key 相同才沿用，否則視為新的一天（回 `{'day': key, 'SLT': None}`）。
  - `mark_sent(telescope, sent_by, program='') -> dict`：鍵 `SLT` 或 `LOT:<program>`，值 `{'sent_by', 'sent_at'(Asia/Taipei)}`，寫回檔案。
  - `send_to_slack(greeting, script_body, image_path=None)`：`chat_postMessage` 問候 → 以 Slack 三步外部上傳（`files_getUploadURLExternal` → HTTP POST bytes → `files_completeUploadExternal(channel_id=...)`）分享 `trigger_script.txt`（`snippet_type='text'`）與 `visibility_plot.jpg`；三則獨立訊息、非 thread；`SlackApiError`/`requests.RequestException` 轉成 `RuntimeError`。
- **狀態檔**：`app/data/trigger_send_status.json`（`_STATUS_DIR = dirname(dirname(__file__))/data`，由 `__file__` 推算）。現存內容：`{"day": "...", "SLT": {...}, "LOT": null}`。
- **環境變數**：`SLACK_BOT_TOKEN`；頻道 `config.DEBUG` 時 `SLACK_CHANNEL_ID_test`，否則 `SLACK_CHANNEL_ID_CONTROL_ROOM`。
- **觸發/呼叫者**：`routes/private_area/private_area_routes.py`：`GET /daily_trigger/send_status`、`POST /daily_trigger/send_message`（先以 `obsplan.plot_night_observing_tracks` 產生暫存 jpg，送出後刪除；`mark_sent` 可由 `mark_sent=false` 略過；再 `upsert_observation_log` 寫 `obs.logs`）、`_render_trigger_visibility_image`/`_log_triggered_targets` 用 `_trigger_day_key`。
- **注意**：狀態檔沒有鎖，兩個 worker 同時 `mark_sent` 可能互相覆蓋。

### `app/modules/email_utils.py`

- **用途**：寄邀請信。
- **公開函式**：`send_invitation_email(email, invitation_link) -> bool | None`：`config.SENDER_EMAIL`/`SENDER_PASSWORD` 缺少回 False；`smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT)` + `starttls()` + `login` + `send_message`；成功 True；**例外時只 print，回傳 None**。
- **SMTP 設定**：全部來自 `modules.config`（`SMTP_SERVER` 預設 smtp.gmail.com、`SMTP_PORT` 587、`SENDER_EMAIL`、`SENDER_PASSWORD`）。
- **呼叫者**：`routes/auth/admin_routes.py:25` import，但全站 **沒有任何 `send_invitation_email(` 呼叫點**（grep 確認）。

### `app/modules/GCN_alert.py`（已停用）

- **用途**：以 `gcn_kafka.Consumer` 訂閱 `gcn.circulars` 與 `gcn.notices.einstein_probe.wxt.alert`。
- **會做的事**
  - Circular：`_format_circular` 轉成 Slack 文字（去除 skymap 欄位）→ `chat_postMessage` 到 `SLACK_CHANNEL_ID_GCN` → 追加到 `app/data/gcn.json`（只留最後 `MAX_ENTRIES = 5` 筆；欄位 `received_at, text(≤2000), subject, circularId`）；以 `circularId` 去重（啟動時從 JSON 預載）。
  - EP WXT alert：解析 ra/dec/trigger_time → 命名 `EP{yymmdd}{a,b,c…}`（同日計數 `suffix_state`）→ `_generate_slt_script`（SLT URGENT、`rp_Astrodon_2018`、`#INTERVAL 300 #COUNT 24`）→ `_generate_obs_plot` 以 `modules.obsplan` 畫鹿林可見度圖到 `app/data/ep_observing_track.jpg` → Slack 到 `SLACK_CHANNEL_ID_ToO`（與 `SLACK_CHANNEL_ID_GCN` 不同時兩邊都發，附圖用 `files_upload_v2`）→ email 到**硬編碼** `['kinder@astro.ncu.edu.tw', 'amar@astro.ncu.edu.tw']`（主旨 "Attention! EP Alert"，內容為原始 JSON）→ 追加 `app/data/ep.json`（最後 5 筆）。
- **檔案**：`app/data/gcn.json`、`app/data/ep.json`（目前不存在）、`app/data/ep_observing_track.jpg`（`_DATA_DIR = dirname(__file__)/../data`，由 `__file__` 推算）。
- **環境變數**：`GCN_CLIENT_ID`、`GCN_CLIENT_SECRET`（缺少則 log error 並不啟動）、`SLACK_BOT_TOKEN`、`SLACK_CHANNEL_ID_GCN`、`SLACK_CHANNEL_ID_ToO`、`SMTP_SERVER`、`SMTP_PORT`、`SENDER_EMAIL`、`SENDER_PASSWORD`。
- **執行緒/鎖**：`_thread`、`_thread_lock`；`start_gcn_listener(log_dir=None)`（`log_dir` 未使用）。
- **呼叫者**：只有 `main.py` 的兩行註解；`gcn.json`/`ep.json`/`ep_observing_track.jpg` 全站沒有其他讀取者（.py/.html/.js 皆 grep 確認）。

### `app/modules/spectral_lines.py`

- **用途**：以 `astroquery.nist.Nist.query` 抓 24 個離子（`_IONS`）在 3000–10000 Å 的譜線，過濾（有相對強度、或禁線 M1/E2、或在 `_TRAD` 傳統名稱表內）、2 Å 內去重、加傳統標籤，快取成 JSON 供光譜檢視器。
- **公開函式**：`get_spectral_lines() -> list[dict]`（快取有效直接回；否則 `warm_cache_async()` 並回 `[]`）、`warm_cache_async()`（若 build thread 未在跑就**無條件**起 `nist-spec-lines` thread 重建）、`rebuild_cache()`（同步、先刪檔）。
- **快取檔**：`app/modules/_spectral_lines_cache.json`（`Path(__file__).parent / '_spectral_lines_cache.json'`，由 `__file__` 推算；git-ignored）；格式 `{"built_at": epoch, "count": n, "lines": [{"w": Å, "label", "ion", "group"}]}`；TTL `_CACHE_TTL = 30 天`（只在 `_load_cache` 檢查）。現況 4207 條、約 7 天前建立。
- **外部服務**：NIST ASD（每個離子間 `sleep(0.5)`）。
- **觸發/呼叫者**：`main.py` 啟動時（不論 DEBUG）；`GET /api/spectral-lines`（`object_routes:1113`，登入者）；`POST /api/spectral-lines/rebuild`（admin → `warm_cache_async`）。
- **注意**：`main.py` 註解「no-op if cache is fresh」與實作不符：每次行程啟動都會重新抓 NIST 並覆寫快取（多 worker 只有持鎖 worker 會做）。

### `app/modules/database/__init__.py`

- **連線池**：`psycopg2.pool.ThreadedConnectionPool(minconn, maxconn)`，`_POOL_MIN/MAX = 1/10`（DEBUG）或 `2/60`；`host/port/user/password` 來自 `PG_*`，`database = "Kinder"`（硬編碼，不讀 `PG_DATABASE`）；`connect_timeout=5`；`options="-c idle_in_transaction_session_timeout=300000 -c statement_timeout=120000"`（5 分鐘 / 2 分鐘）；`keepalives=1, keepalives_idle=60, keepalives_interval=10, keepalives_count=5`。模組 import 時 `load_dotenv(kinder.env, override=True)`。
- **公開函式**
  - `init_connection_pool(minconn, maxconn)`：懶初始化，成功後呼叫 `_ensure_extra_tables()`。
  - `get_pool_stats() -> dict`：`pool_min, pool_max, in_use(len(p._used)), idle(len(p._pool)), usage_pct`（用 psycopg2 私有屬性）。
  - `close_connection_pool()`。
  - `recycle_idle_connections()`：在 `p._lock` 下把 `p._pool` 的閒置連線全部取出關閉（排程 `db_recycle` 每 30 分鐘）。
  - `get_db_connection()`（context manager）：取連線；`conn.closed` 則丟棄重取；`OperationalError` 時 `putconn(close=True)`；離開前 `_reset_conn` 對 `STATUS_IN_TRANSACTION/IN_ERROR` 做 rollback，失敗則丟棄。
  - `get_tns_db_connection() -> _PooledConn`：原始池連線包裝，`close()` 攔截為 `putconn`。
  - `check_db_connection() -> bool`：獨立 `psycopg2.connect`（非池）。
  - `is_db_available(force=False) -> bool`：`_status_cache` 15 秒快取（`_STATUS_CACHE_SECONDS`），狀態翻轉時 log；首頁 `db_offline` 橫幅用。
  - `OBJECT_COMPAT_COLS`：舊 `tns_objects` 欄位別名 SQL 片段（MJD → 字串日期、status → tag/inbox/snoozed/follow/finish_follow 旗標等）。
- **`_ensure_extra_tables()` 啟動時建立/保證的物件**（獨立連線；任何例外只 `logger.warning`）
  1. `CREATE TABLE IF NOT EXISTS auth.invitations (token PK, email, is_admin, role, invited_by → auth.users(usr_id) ON DELETE SET NULL, invited_at, status, accepted_at)`
  2. `CREATE TABLE IF NOT EXISTS auth.system_settings (key PK, value, updated_at)`
  3. `CREATE TABLE IF NOT EXISTS transient.object_source_permissions (id, object_name, data_type CHECK IN ('phot','spec'), source_name, allowed_groups INT[], is_public, updated_at, UNIQUE(object_name, data_type, source_name))`
  4. `ALTER TABLE transient.photometry ADD CONSTRAINT phot_uniq UNIQUE (obj_id, "MJD", filter, source)`（`duplicate_table` 例外忽略）
  5. `ALTER TABLE obs.logs ADD CONSTRAINT obs_logs_target_date_uniq UNIQUE (target_id, date)`
  6. `ALTER TABLE transient.objects ADD COLUMN IF NOT EXISTS kinder_id BIGINT`
  7. 索引：`objects_kinder_id_idx`（UNIQUE, partial `kinder_id IS NOT NULL`）、`objects_discovery_date_idx (discovery_date DESC)`、`objects_name_prefix_idx`、`objects_type_idx`（partial）、`objects_last_phot_date_idx (last_phot_date DESC)`、`obs_logs_date_idx (obs.logs.date)`、`obs_logs_name_idx`、`obs_targets_active_idx (obs.targets.active, name)`、`objects_name_idx`（UNIQUE on `transient.objects(name)`）
  8. `ALTER TABLE transient.objects ALTER COLUMN tag SET DEFAULT '{}'::text[]` + `UPDATE ... SET tag='{}' WHERE tag IS NULL`
  9. `CREATE TABLE IF NOT EXISTS cat.ned (ned_id, object_name, ra_center, dec_center, radius_arcsec, searched_at, result_count, results JSONB)` + `cat_ned_object_radius_idx` UNIQUE
- **其他 import 期 / 執行期 DDL**（同套件）：`auth.py` import 時 `_ensure_api_key_request_col()`（`auth.users ADD COLUMN IF NOT EXISTS api_key_requested_at`）；`obs.get_observation_targets()` 每次呼叫 `_ensure_auto_exposure_column()`（`obs.targets ADD COLUMN auto_exposure`）；`transient._ensure_tns_update_audit_table`（`transient.tns_update_audit` + 索引）；`transient._ensure_cross_matches_flag_column`。DETECT 側：`DataUploader.save_screen_results` 每次執行 `SCREEN_DDL`/`SCREEN_HISTORY_DDL`；DETECT 自己的 `_ensure_extra_tables()` 只由 `init_tns_database()` 呼叫（web 端未呼叫）。
- **呼叫者**：幾乎所有 route 與模組；`recycle_idle_connections` 只在 `main.py`；`is_db_available` 只在 `routes/basic/basic_routes.py`；`get_pool_stats` 只在 `db_monitor`。

### `app/modules/config.py`

- `Config` 類別在 import 時 `load_dotenv(basedir/../../kinder.env)`（不 override）後讀取：`DEBUG`（`'true'` 才真）、`HOST`（127.0.0.1）、`PORT`（5000）、`APP_BASE_URL`（預設 `http://{HOST}:{PORT}`；`main.py` 用其 netloc 做 Host 白名單）、`SECRET_KEY`（預設 `'your-very-secure-secret-key'`）、`GOOGLE_CLIENT_ID`、`GOOGLE_CLIENT_SECRET`、`SMTP_SERVER`、`SMTP_PORT`、`SENDER_EMAIL`、`SENDER_PASSWORD`、`ADMIN_EMAIL`、`ADMIN_LOCAL_EMAIL`、`ADMIN_USERNAME`、`ADMIN_PASSWORD`。`config = Config()` 單例。

#### 環境變數總表（`kinder.env` 現有鍵 + 各模組 `os.getenv`/`os.environ.get` grep 結果）

| 名稱 | 用途 | 使用的模組 | 必填 | 在 kinder.env |
| --- | --- | --- | --- | --- |
| `DEBUG` | 停用背景工作、縮小連線池、Secure cookie、Slack 測試頻道 | `config.py`、`database/__init__.py` | 否（預設 False） | 是 |
| `HOST` / `PORT` | Flask 綁定、允許的 Host | `config.py` | 否 | 是 |
| `APP_BASE_URL` | 公開網址（Host 白名單、OAuth redirect） | `config.py`、`main.py` | 正式環境必填 | 是 |
| `SECRET_KEY` | Flask session | `config.py` | 必填（預設值不安全） | 是 |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google OAuth | `config.py` → `routes/auth` | 登入必填 | 是 |
| `SMTP_SERVER` / `SMTP_PORT` | SMTP 主機 | `config.py`、`db_monitor.py`、`GCN_alert.py` | 否（預設 gmail:587） | 是 |
| `SENDER_EMAIL` / `SENDER_PASSWORD` | 寄信帳密 | `config.py`（`email_utils`）、`db_monitor.py`、`GCN_alert.py` | 寄信功能必填 | 是 |
| `ADMIN_EMAIL` / `ADMIN_LOCAL_EMAIL` / `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 管理者帳號 | `config.py` | 依 auth 流程 | 是 |
| `PG_HOST` / `PG_PORT` / `PG_USER` / `PG_PASSWORD` | PostgreSQL | `database/__init__.py`、`backup.py`、`detect_pipeline._pin_db_env` → DETECT | 必填 | 是 |
| `PG_DATABASE` | DB 名稱（**只有 DETECT 讀**；web 硬編碼 `Kinder`，`_pin_db_env` 會覆寫成 `Kinder`） | DETECT `function/database/__init__.py` | 否 | 是 |
| `TNS_BOT_ID` / `TNS_BOT_NAME` / `TNS_API_KEY` | TNS bot | `auto_tns_download.py`、`tns_gap_filler.py`、`download_phot.py`、`TNS_object_fetch.py` | TNS 同步必填 | 是 |
| `TNS_HOST` / `API_BASE_URL` / `BOT_ID` / `BOT_NAME` / `API_KEY` | 舊版 TNS 設定 | `Manual_tns_download_snoozed.py` | – | **否（缺）** |
| `ATLAS_USER` / `ATLAS_PASS` | QUB ATLAS 登入 | `download_phot.py` | ATLAS 光度必填 | 是 |
| `PANSTARRS_USER` / `PANSTARRS_PASS` | QUB Pan-STARRS 登入 | `download_phot.py` | PS 光度必填 | 是 |
| `SLACK_BOT_TOKEN` | Slack bot | `trigger_send.py`、`GCN_alert.py` | Trigger 送出必填 | 是 |
| `SLACK_CHANNEL_ID_CONTROL_ROOM` / `SLACK_CHANNEL_ID_test` | Trigger 目標頻道（正式 / DEBUG） | `trigger_send.py` | 是 / DEBUG 時 | 是 |
| `SLACK_CHANNEL_ID_GCN` / `SLACK_CHANNEL_ID_ToO` | GCN/EP 通知頻道 | `GCN_alert.py` | （停用） | 是 |
| `GCN_CLIENT_ID` / `GCN_CLIENT_SECRET` | GCN Kafka | `GCN_alert.py` | （停用） | 是 |
| `ACCESS_LOG_ENABLED` | HTTP access log | `main.py` | 否（預設 0） | 否 |
| `LOG_MAX_FILE_BYTES` / `LOG_MAX_LINE_CHARS` | 日誌大小/行長上限 | `log_setup.py` | 否（15 MiB / 1600） | 否 |
| `DETECT_IN_WEB` | 是否在 web 內跑 DETECT | `detect_pipeline.py` | 否（預設啟用） | 否 |
| `DETECT_DATA_DIR` | DETECT 資料目錄 | `main.py`（setdefault）、`detect_pipeline.status`、DETECT `paths.py`/`calculator.py` | 否 | 否 |
| `VIZIER_TIMEOUT_SEC` | Vizier 逾時 | `detect_cross_match.py` | 否（8） | 否 |
| `DETECT_LC_CACHE_MAX_SIZE` / `DETECT_PAGE_CACHE_TTL_SEC` / `DETECT_PAGE_CACHE_MAX_SIZE` / `DETECT_PAGE_PREWARM_DAYS` / `DETECT_TRACKER_CACHE_TTL` | DETECT 頁快取參數 | `routes/detect/detect_routes.py` | 否（300 / 600 / 8 / 3 / 300） | 否 |
| `HEALPIX_NSIDE` | DETECT HEALPix 解析度 | DETECT `database/healpix_index.py` | 否 | 否 |

---

## 資料目錄總表

### `app/data/`（整個目錄 git-ignored：`.gitignore` 的 `app/data/` 與 `data/`）

| 路徑 | 寫入者 | 讀取者 | 備註 |
| --- | --- | --- | --- |
| `tns_public_objects_FULL.csv`（107 MB, 2026-05-06） | 無 app 程式碼；只有 repo 根目錄的 `test_tns_full_sync.py`（git-ignored 測試腳本）引用 | 同左 | 一次性全量同步的原始檔，可視為歷史遺留 |
| `tns_public_objects.csv.zip`（13 MB） | 同上 | 同上 | 同上 |
| `tns_api_download_work/` | `auto_tns_download`（`_download_and_extract`）、`Manual_tns_download_snoozed`、`TNS_object_fetch`（未使用）、admin 手動路徑 | `addin_database`（三個模組各自的版本）、`web_api_routes.manual_tns_download` | 只有 `tns_public_objects_WORK.csv`（每次覆蓋）與暫時的 `.csv.zip` |
| `phot_cache/<YYYY>/<name>_photometry.txt` | `download_phot.init_photometry_file` / `write_photometry_to_txt` / `bin_photometry_file` | `download_phot.upload_photometry_to_db`（讀後 `unlink`） | 正常流程結束即刪；現存 4 檔為失敗遺留（含只有表頭者） |
| `shared_plots/<24 hex>.json` | `astronomy_tools_routes.lc_plotter_share`（`POST /lc_plotter/share`） | `lc_plotter_shared`（`GET/POST /lc_plotter/shared/<id>`，60 天 TTL 只在讀取時檢查 → 410） | `{traces, layout, isStatic, created_at, password_hash}`；沒有清理排程 |
| `gcn.json` | `GCN_alert._append_entry`（停用） | 無 | 最後 5 筆 circular |
| `ep.json` | `GCN_alert`（停用） | 無 | 目前不存在 |
| `ep_observing_track.jpg` | `GCN_alert._generate_obs_plot`（停用） | 無 | – |
| `greatlab_links.json` | **無**（`private_area_routes.get_greatlab_links_path()` 指向 `app/routes/private_area/data/greatlab_links.json`） | 無 | `app/data/` 這份是孤兒；實際路徑檔案不存在時 route 回傳內建預設值 |
| `filter_colors.json` | 無（手動維護） | `modules/filter_colors.py`（import 時載入）→ `data_processing`、`astronomy_tools_routes` | 濾鏡→hex 色表 |
| `trigger_send_status.json` | `trigger_send.mark_sent` | `trigger_send.get_send_status` | 每個觀測夜（08:00 Asia/Taipei 換日）重置 |
| `1a2b_leaderboard.json` | **無**（`games_routes.LEADERBOARD_FILE` = `dirname(__file__)/../../../data/1a2b_leaderboard.json` → **repo 根目錄 `data/`**，不在 `app/` 內） | 無 | `app/data/` 這份是孤兒；`POST /api/games/leaderboard` 會在 `<repo>/data/` 建新檔 |
| `backups/Kinder_backup_YYYYMMDD.sql` | `backup.run_daily_backup` | 人工 | 保留 15 份；本機不存在（DEBUG 從未執行） |

### 其他資料/日誌目錄

| 路徑 | 用途 / 寫入者 / 讀取者 |
| --- | --- |
| `app/log/YYYY-MM-DD.log` | `log_setup.DailyFileHandler` 寫（UTC+8 日期、保留 7 天、15 MiB 上限）；`web_log_routes`（`/admin/log`、`/api/log/files`、`/api/log/content`、`/api/log/sources`）讀 |
| `app/log/.background_jobs.lock` | `main.py` flock（0 byte） |
| `app/log/.job_status.json`（+ `.tmp`） | `job_status._persist` 寫；`job_status._read_file` 讀（admin 頁） |
| `app/log/{gcn_alert,detect,tns_fetch}.log` | `web_log_routes._DAEMON_LOG_FILES` 期望的檔案；**沒有程式會寫** |
| `app/modules/DETECT/data/`（git-ignored；= `DETECT_DATA_DIR`） | `crossmatch_images/<name>.png`（DETECT finder 輸出，`cross_match.py`）、`marked_images/`（`Legacy_survey_img.py`）、`dustmaps/sfd/SFD_dust_4096_{ngp,sgp}.fits`（`calculator._ensure_sfd_maps` 首次使用時自 GitHub 下載） |
| `app/modules/DETECT/function/data/kn_lc_mag.txt` | DETECT `screening.py` 的 KN 模型（git 追蹤，`.gitignore` 有例外） |
| `app/modules/web_data/kn_lc_mag.txt` | `routes/marshal/object_routes._parse_kn_model` 用的同一份 KN 模型（與上者 `diff` 完全相同的複本，git 追蹤） |
| `app/modules/_spectral_lines_cache.json` | `spectral_lines` 讀寫（git-ignored） |
| `app/routes/planners/ov_plot/observing_tracks_<uuid>.jpg` | `astronomy_tools_routes.generate_plot`（`POST /generate_plot`）寫，`enforce_max_files(..., 10)` 依 mtime 只留 10 張；`planners_routes.serve_ov_plot`（`GET /ov_plot/<file>`）讀；`.gitignore` `app/routes/planners/ov_plot/*` |
| `app/routes/basic/gallery_uploads/` | `basic_routes`（`GALLERY_DIR`；import 時 `makedirs`）：原圖、`_thumb` 縮圖、`<file>.json` 中繼資料；git-ignored |
| `app/routes/private_area/data/` | `epessto_sessions.json`（ePESSTO 房間/工作階段狀態）、`epessto_uploads/{files,images}` 與 `epessto_uploads/rooms/<room_id>/{files,images}`（房間閒置 24 h 於請求時 `_cleanup_epessto_stale_rooms` `rmtree`）；`greatlab_links.json` 應在此（目前不存在）；被 `.gitignore` 的 `data/` 規則忽略 |
| `app/routes/private_area/tutorials/` | Documents 功能：`*.md` 文件、`metadata.json`（pinned/order）、`images/`、`.env`（`DOCUMENTS_EDITABLE`、`IMPORTANT_MESSAGE`）；`.gitignore` `app/routes/private_area/tutorials/*`。注意 `admin_routes.clean_unused_images` 卻指向不存在的 `app/routes/auth/static/tutorials/` |
| `<repo>/photo/` | `main.py` `_PHOTO_DIR` 的靜態圖片來源（`/static/photo/...`）；本機不存在 |
| `<repo>/data/` | `games_routes` 排行榜實際寫入位置；本機不存在 |

---

## 已知問題與注意事項

1. **`retire_stale_followups` 的「過期」判斷永遠失敗**：`transient.objects.last_phot_date` 是 `DOUBLE PRECISION`（MJD，見 `_Kinder_Database/SQL/transient.sql:49`），psycopg2 回傳 `float`；程式以 `hasattr(x, 'tzinfo')` 判斷後走 `datetime(last_phot_date.year, ...)` → `AttributeError`，被逐物件 `except` 吞掉並記入 `errors`。結果：有光度的 Follow-up 永遠不會因 >2 天無新資料而退役，只有「Snoozed → Finish」與「Follow-up 且無光度 → Finish」兩條規則有效。
2. **每日 05:30 所有 `Snoozed` 物件都會變成 `Finish`**：`retire_stale_followups` 的查詢是 `status IN ('Follow-up','Snoozed')` 且 `Snoozed` 一律 retire，並非只針對「曾是 Follow-up」的物件。搭配每小時的 `auto_snoozed`（Inbox 超過 15 天 → Snoozed），等於陳舊 Inbox 物件在一天內會變成 `Finish`。需確認是否為預期行為。
3. **`update_target_mags` 寫入不存在的資料表**：`UPDATE obs.observation_targets ...` / `UPDATE obs.observation_logs ...`，但 DDL（`observation.sql`）與 `obs.py` 都只有 `obs.targets`、`obs.logs`。第一個需要更新的目標會拋 `UndefinedTable`，被外層 `except` 捕捉 → 整個工作回 `{"error": ...}`。`daily_target_mag_update` 與 `/api/targets/update-mags` 很可能從未成功更新過（請對照正式 DB 確認是否有同名 view）。
4. **`detect_page_prewarm` 每 30 分鐘的排程必定失敗**：`prewarm_detect_page_cache()` 無 `app_obj` 時呼叫 `current_app._get_current_object()`，APScheduler 執行緒沒有 Flask app context → `RuntimeError: Working outside of application context`，被 `_tracked` 記為 error。只有啟動時傳 `app_obj=app` 的那一次有效。
5. **時區標籤與實際觸發時間可能不一致**：`BackgroundScheduler` 未指定 `timezone`，cron 以主機本地時區觸發；程式註解、管理頁 `_SCHEDULED_JOBS` 與 `_calc_next_run` 全部標示/計算 UTC。`auto_tns_download` 執行緒則是真 UTC。若正式主機為 Asia/Taipei，APScheduler 工作比註解早 8 小時。
6. **`download_phot.py` 造成第二個連線池**：以 `from database import ...` 匯入（裸套件名），Python 視 `database` 與 `modules.database` 為不同模組 → 各自一個 `ThreadedConnectionPool`（正式環境各 2–60 條），`_ensure_extra_tables` 執行兩次；`db_monitor`/`get_pool_stats`/`recycle_idle_connections` 只看得到 `modules.database` 那個池。
7. **`Manual_tns_download_snoozed.py` 讀取的環境變數名稱與 `kinder.env` 不符**（`BOT_ID`/`API_KEY` 等），`/api/tns/manual-download` 無法向 TNS 驗證；其 `auto_snoozed`（`/api/auto-snooze/manual-run`）會把 `Finish` 也 Snooze、把 `Follow-up` 直接 Finish，與常駐版語意衝突。
8. **`warm_cache_async()` 每次行程啟動都重抓 NIST**（`main.py` 註解稱 no-op 不正確）；多 worker 下由持鎖 worker 執行，24 次外部查詢 + 覆寫快取。
9. **啟動時同步備份**：`run_daily_backup()` 在 import `main.py` 時同步跑 `pg_dump`（最長 300 s），會延遲持鎖 worker 對外服務；備份放在同一台機器的 `app/data/backups`，無壓縮、無異地。`_find_pg_dump` 以 Homebrew 路徑優先，Linux 主機依賴 `PATH`。
10. **日誌**：`_StreamToLogger` 只接管 stdout，`traceback.print_exc()`（`Manual_tns_download_snoozed`、`web_api_routes` 多處）走 stderr 不會進日誌；`DailyFileHandler` 達 15 MiB 時直接清空當日檔（資料遺失而非輪替）；`asctime` 用本機時間但檔名用 UTC+8，主機時區不同時會錯位；daemon log 分頁對應的三個檔案沒有寫入者。
11. **`auto_tns_download.main()` 時序**：以 10 s 輪詢，hourly 任務（含新物件光度抓取 Playwright 登入與 DETECT）若從 :45 跑超過 15 分鐘，01/04/12 UTC 的 daily 任務會錯過整點；hour 0 時 `auto_snoozed` 在 :15、:45 各跑兩次。沒有停止/健康檢查機制，執行緒死掉（非例外的 hang）不會被偵測。
12. **資料檔路徑不一致**：`1a2b_leaderboard.json` 實際寫到 repo 根目錄 `data/`；`greatlab_links.json` 實際位置是 `app/routes/private_area/data/`；`app/data/` 內兩份都是孤兒。`admin_routes.clean_unused_images` 指向不存在的 `app/routes/auth/static/tutorials`。
13. **同步且無鎖的重工作路由**：`POST /api/object/<name>/fetch_photometry` 在請求執行緒內跑完整 Playwright 流程（任何登入者可觸發，可能數分鐘），且與排程/hourly 抓取沒有互斥；`POST /admin/backup-now` 同步 `pg_dump`。
14. **讀取路徑執行 DDL**：`detect_cross_match.get_detect_results_for_target` / `save_detect_results` 每次 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`；`obs.get_observation_targets` 每次 `ALTER TABLE obs.targets`；DETECT `save_screen_results` 每次 `CREATE TABLE IF NOT EXISTS`。需要 DDL 權限的帳號，且在高併發下會競爭 catalog lock。
15. **`load_dotenv(override=True)` 散落多處**（`database/__init__.py`、`download_phot.py`、`db_monitor._smtp_config` 每次呼叫）會覆寫整個行程環境；`detect_pipeline._pin_db_env` 是為此打的補丁。
16. **硬編碼收件人**：`db_monitor.ALERT_TO`、`GCN_alert.email_receivers`。
17. **死碼/孤兒模組**：`TNS_object_fetch.py`（`auto_tns_download` 的舊版複本，`start_tns_fetcher` 無人呼叫）、`Manual_tns_download_snoozed.py`（僅兩個 route）、`detect_cross_match.run_all_detect`、`download_phot.py` L584–L639、`email_utils.send_invitation_email`（import 但未呼叫）、`sys.path` 中不存在的 `modules/DETECT_pipe/modules`、`phot_scheduler.fetch_missing_photometry`（未排程）。
18. **`_ensure_extra_tables` 靜默失敗**：DB 啟動時不可達（如本機 2026-09-21 12:29 日誌所示）只記 warning，之後不會重試；索引/約束（含 `phot_uniq`，`ON CONFLICT ON CONSTRAINT phot_uniq` 依賴它）可能缺失導致後續 INSERT 失敗。
19. **私密檔未入版控**：`download_phot.py` 是 git-ignored 的私有檔（含外站爬取邏輯），部署或備份時必須另外攜帶；`app/modules/DETECT/data/`、`app/data/`、`app/log/` 亦然。
20. **`fetch_inbox_photometry` `limit=9999`**：Inbox 超過 9999 筆時後段物件不會被抓取。
21. **`tns_gap_filler`**：每個缺口固定等待 60 s；跨年後只處理當年；`_insert_tns_object` 不種光度、不寫 audit、不跑 DETECT，與 `addin_database` 路徑產生的物件狀態不一致。
