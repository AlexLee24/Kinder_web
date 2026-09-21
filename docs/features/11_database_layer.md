# 資料庫存取層（app/modules/database）與 Kinder PostgreSQL schema

> **注意**：本章記錄的是重構前（commit `c7f91a4`，2026-09-21）的狀態，檔案路徑為舊位置（`app/routes/…`、`app/modules/…`）。新位置請對照 `docs/ARCHITECTURE.md` §6「新舊路徑對照」；功能與行為在重構後完全相同。

> 本章依據原始碼逐檔確認：`app/modules/database/__init__.py`（495 行）、`auth.py`（1060 行）、`catalog.py`（223 行）、`obs.py`（665 行）、`transient.py`（2405 行），以及 `_Kinder_Database/` 下的 `Schema - *.md`、各表 `.md` 與 `SQL/*.sql`。
> 文中「被誰呼叫」的檔名一律相對於 `app/`（例如 `routes/marshal/object_routes.py`），以 `grep -rn` 於 `app/routes` 與 `app/modules` 找出，**排除** `app/modules/CASTOR/`、`app/modules/DETECT/` 與 `modules/database_deprecated.py`。
> 公開函式（不含底線開頭）總數：`__init__.py` 8、`auth.py` 46、`catalog.py` 8、`obs.py` 9、`transient.py` 47 + `TNSObjectDB` 20 個方法 = **138**。

---

## 1. Schema 總覽

資料庫名稱固定為 `Kinder`（`DB_NAME = "Kinder"`，寫死於 `__init__.py`），分四個 schema：`auth`（帳號/群組/權限）、`transient`（暫現源核心資料）、`obs`（觀測排程與紀錄）、`cat`（外部星表快取）。DDL 原稿在 `_Kinder_Database/SQL/{auth,transient,observation,catalog}.sql`；除此之外還有三處會在**執行期**補建表/欄位/索引：

| 補建位置 | 觸發時機 |
| --- | --- |
| `__init__.py::_ensure_extra_tables()` | `init_connection_pool()` 第一次建池後（`main.py` 啟動時），用**獨立的 `psycopg2.connect`** 而非連線池執行，全部包在一個 try 內，任何一句失敗就整批不 commit 只記 warning |
| `auth.py::_ensure_api_key_request_col()` | **模組被 import 時**立即執行（模組層級呼叫） |
| `obs.py::_ensure_auto_exposure_column()` | 每次 `get_observation_targets()` / `save_observation_target()` 被呼叫時 |
| `transient.py::_ensure_cross_matches_flag_column(cur, conn)` | 每次 `get_cross_match_results` / `get_detect_page_data` / `update_cross_match_flag` / `get_flagged_objects` / `save_flag_objects` / `get_object_flag_status` / `update_object_flag_by_name` 被呼叫時 |
| `transient.py::_ensure_tns_update_audit_table(cur)` | 每次 `log_tns_update_batch` / `TNSObjectDB.get_recent_tns_updates` 被呼叫時 |
| `modules/detect_cross_match.py`、`modules/DETECT/function/database/*.py`（本章不展開） | DETECT 流程執行時補 `cross_matches` 的 `match_data`/`match_ra`/`match_dec`/`note`/`run_date`/`status`/`error_message`/`flag`，並建 `transient.detect_screen`、`transient.detect_screen_history` |

### 1.1 `auth` schema（`SQL/auth.sql`、`Schema - Authorization.md`）

| 表 | 舊表名 | 用途 | 主要欄位 |
| --- | --- | --- | --- |
| `auth.users` | `users` | 使用者主檔（Google 登入） | `usr_id SERIAL PK`；`email TEXT NOT NULL UNIQUE`；`picture_url TEXT`；`name TEXT NOT NULL`；`roles INT DEFAULT 0 CHECK IN (0,1,50,99)`（0 guest / 1 user / 50 admin / 99 super_admin）；`last_login TIMESTAMPTZ`；`join_date TIMESTAMPTZ DEFAULT now()`；`api_key TEXT UNIQUE`。**執行期新增**：`api_key_requested_at TIMESTAMPTZ`（`auth.py` import 時 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`） |
| `auth.images` | `users` | 使用者頭像 BYTEA（1:1） | `usr_id INT PK FK users ON DELETE CASCADE`；`image_data BYTEA NOT NULL`。**目前 app 內沒有任何程式讀寫此表** |
| `auth.groups` | `groups` | 群組主檔 | `group_id SERIAL PK`；`name TEXT NOT NULL`（DDL **未加 UNIQUE**，但程式全以 name 當 key）；`description`；`joinable BOOL DEFAULT FALSE`；`create_by INT FK users SET NULL`；`manager INT FK users SET NULL` |
| `auth.usr_group` | （舊 `user_groups`） | 使用者 ↔ 群組，兼作加入申請 | `usr_id`、`group_id` 複合 PK（皆 CASCADE）；`status TEXT DEFAULT 'request' CHECK IN ('request','joined','rejected')`；`created_at TIMESTAMPTZ` |
| `auth.invitations` | `invitations` | 註冊邀請 token（**由 `_ensure_extra_tables` 建立**，不在 SQL 檔） | `token TEXT PK`；`email TEXT`；`is_admin BOOLEAN DEFAULT FALSE`；`role TEXT DEFAULT 'user'`；`invited_by INT FK users SET NULL`；`invited_at TIMESTAMPTZ DEFAULT now()`；`status TEXT DEFAULT 'pending'`（程式另用 `'accepted'`）；`accepted_at TIMESTAMPTZ` |
| `auth.system_settings` | `system_settings` | 通用 key/value（**由 `_ensure_extra_tables` 建立**） | `key TEXT PK`；`value TEXT`；`updated_at TIMESTAMPTZ`。private-area 頁面群組權限以 key `page_perm:<page_key>`、value = JSON list[群組名稱] 存放（`get_page_groups`/`set_page_groups`）；其他 admin 設定由 `routes/auth/admin_routes.py` 透過 `get_setting`/`set_setting` 存取 |

### 1.2 `transient` schema（`SQL/transient.sql`、`Schema - Transient.md`）

| 表 | 舊表名 | 用途 | 主要欄位 / 索引 |
| --- | --- | --- | --- |
| `transient.default_permissions` | `default_source_permissions` | 各資料來源（LOT/SLT/ATLAS…）的預設可見度 | `source TEXT PK`；`permissions_set TEXT DEFAULT 'public' CHECK IN ('public','login','groups')`；`groups INT[] DEFAULT '{}'`（group_id 陣列） |
| `transient.objects` | `tns_objects` | 暫現源主表（TNS 匯入 + 內部） | `obj_id BIGINT PK`；`status TEXT DEFAULT 'Inbox' CHECK IN ('Inbox','Snoozed','Follow-up','Finish')`；`pin BOOL`；`name_prefix TEXT`（AT/SN/FRB/TDE/EP…）；`name TEXT NOT NULL UNIQUE`（**不含前綴**，如 `2026abc`）；`internal_name`、`other_name TEXT`；`tag TEXT[] DEFAULT '{}'`；`ra`、`dec DOUBLE NOT NULL`；`redshift`；`type TEXT`；`report_group`、`source_group TEXT`；`discovery_date`、`received_date`、`creation_date`、`last_phot_date`、`last_modified_date DOUBLE`（**全部存 MJD**）；`discovery_mag`、`discovery_mag_err`、`discovery_filter`；`reporters TEXT[]`；`discovery_ADS`、`class_ADS TEXT`；`brightest_mag`、`brightest_abs_mag`；`host_name TEXT`；`permission TEXT DEFAULT 'public' CHECK IN ('public','login','groups')`；`groups INT[]`。DDL 索引：`objects_status_idx`、`objects_ra_dec_idx`、`objects_tag_idx (GIN)`、`objects_groups_idx (GIN)`、`objects_last_modified_idx`。**執行期新增**（`_ensure_extra_tables`）：欄位 `kinder_id BIGINT` + 部分唯一索引 `objects_kinder_id_idx WHERE kinder_id IS NOT NULL`；索引 `objects_discovery_date_idx (discovery_date DESC)`、`objects_name_prefix_idx`、`objects_type_idx WHERE type IS NOT NULL AND type != ''`、`objects_last_phot_date_idx (last_phot_date DESC)`、`objects_name_idx UNIQUE (name)`（與 DDL 的 UNIQUE 重複）；`tag` 加 `DEFAULT '{}'::text[]` 並把 NULL 回填為 `'{}'`。`discovery_mag_err`、`host_name` 在 database 套件內沒有任何函式讀寫（`host_name` 僅 `routes/marshal/object_routes.py` 直接 SQL 使用） |
| `transient.photometry` | `photometry` | 光度點 | `phot_id BIGSERIAL PK`；`obj_id BIGINT FK objects CASCADE`；`name TEXT`（反正規化快取）；`"MJD" DOUBLE NOT NULL`（**大寫、需加雙引號**）；`mag`、`mag_err`；`filter`；`source`（舊 `telescope`）；`permission TEXT DEFAULT 'default' CHECK IN ('default','public','login','groups')`；`groups INT[]`。索引 `photometry_obj_mjd_idx (obj_id,"MJD")`、`photometry_source_idx`、`photometry_groups_idx (GIN)`。**執行期新增**：唯一約束 `phot_uniq UNIQUE (obj_id,"MJD",filter,source)`（所有 INSERT 用 `ON CONFLICT ON CONSTRAINT phot_uniq DO NOTHING`） |
| `transient.spectroscopy` | `spectroscopy` | 光譜，**每個波長點一列** | `spec_id BIGSERIAL PK`；`obj_id`；`name`；`"MJD" DOUBLE NOT NULL`（觀測 epoch；<1000 視為舊制 phase）；`wavelength DOUBLE NOT NULL`（Å）；`intensity`；`source`（望遠鏡/儀器）；`permission`、`groups` 同上。一條「光譜」= 同 `(source,"MJD")` 的所有列，程式以 `spectrum_id = f'{source}@@{mjd:.6f}'` 識別。索引 `spectroscopy_obj_mjd_idx`、`spectroscopy_groups_idx` |
| `transient.cross_matches` | `cross_match_results` | DETECT 交叉比對結果 | `match_id BIGSERIAL PK`；`obj_id`；`name`；`catalog TEXT NOT NULL`（DESI / `Lens_XXXX` / `AGN_XXXX` / 程式另用 `FLAGGED_LIST`）；`separation`（arcsec）；`redshift`；`is_host BOOL`；`updated_date TIMESTAMPTZ`；`note`；`run_date`；`status`（Success/Error/Retry-Success；`_build_where` 另查 `'Flagged'`）；`error_message`。索引 `cross_matches_obj_catalog_idx`、`cross_matches_is_host_idx`。**執行期新增**：`flag BOOLEAN DEFAULT FALSE`（`transient.py` 與 DETECT 皆會補）、`match_data JSONB`（DETECT 補；本層在其中寫入 `host_user`/`host_user_by`/`host_user_at`）、`match_ra`、`match_dec DOUBLE`（`modules/detect_cross_match.py` 補） |
| `transient.target_images` | `target_images` | BYTEA 影像（DESI cutout、DETECT finder chart） | `image_id BIGSERIAL PK`；`obj_id`；`name`；`image_data BYTEA NOT NULL`；`source TEXT`（程式使用 `'DESI'`、`'detect_combined'`）。索引 `target_images_obj_idx` |
| `transient.download_logs` | `tns_download_log` | TNS 同步紀錄 | `log_id BIGSERIAL PK`；`download_date TIMESTAMPTZ DEFAULT now()`；`obj_import`、`obj_update INT`；`status TEXT NOT NULL`（程式先寫 `'In Progress'` 再更新）；`error_message`；`filename` |
| `transient.custom_targets` | `custom_targets` | 使用者自訂目標清單 | `obj_id`、`usr_id` 複合 PK；`name`；`save_date`；`note`。**目前 app 內沒有任何程式讀寫此表** |
| `transient.object_views` | `object_views` | 每物件累計瀏覽數 | `obj_id BIGINT PK`；`name`；`counts INT DEFAULT 0`；`last_view TIMESTAMPTZ` |
| `transient.object_views_detail` | `object_view_counts` | 瀏覽明細（設計上只留 30 天） | `view_id BIGSERIAL PK`；`obj_id`；`name`；`usr_id INT FK users SET NULL`；`view_time TIMESTAMPTZ`。索引 `object_views_detail_view_time_idx`、`object_views_detail_obj_usr_idx`。**沒有任何程式做 DELETE 清理**（DDL 註解要求定期 prune） |
| `transient.comments` | `comments` | 物件留言 | `comment_id BIGSERIAL PK`；`obj_id`；`name`；`usr_id INT FK users SET NULL`；`comment TEXT NOT NULL`；`comment_time TIMESTAMPTZ`。索引 `comments_obj_idx` |
| `transient.object_source_permissions` | （舊 `object_permissions` 的來源層版本） | 單一物件、單一資料類型（phot/spec）、單一來源的可見度覆寫（**由 `_ensure_extra_tables` 建立**） | `id SERIAL PK`；`object_name TEXT`；`data_type TEXT CHECK IN ('phot','spec')`；`source_name TEXT`；`allowed_groups INT[] NULL`（**NULL = 任何登入者可見；`{}` = 除 admin 外全部封鎖；`{ids}` = 指定群組**）；`is_public BOOL`；`updated_at`；`UNIQUE (object_name, data_type, source_name)` |
| `transient.tns_update_audit` | （新） | TNS 同步變更稽核，供首頁「Recent TNS Updates」與 DETECT 喚醒註記使用（**由 `transient.py::_ensure_tns_update_audit_table` 延遲建立**） | `audit_id BIGSERIAL PK`；`obj_id BIGINT NOT NULL`；`name TEXT NOT NULL`；`changed_fields TEXT[]`（實際值：`type`、`redshift`、`reporting_group`、`source_group`、`internal_names`、`discovery_mag`、`last_photometry_date`、`name_prefix`、`new_add`、`woke: Snoozed -> Inbox`）；`source TEXT DEFAULT 'tns_sync'`（實際值 `auto_tns_download`、`tns_object_fetch`）；`updated_at TIMESTAMPTZ`；索引 `idx_tns_update_audit_updated_at` |
| `transient.detect_screen`、`transient.detect_screen_history` | （新，DETECT 擁有） | DETECT 篩選結果（每物件一列，最新一次 run）與歷史 | 由 `modules/DETECT/function/database/upload_data.py::DataUploader.SCREEN_DDL` 建立；本層只**讀**：`obj_id PK`、`name`、`score`、`host_status`（confirmed/review/none）、`tags TEXT[]`、`flags JSONB`、`host_targetid`、`z`、`z_source`、`abs_mag`、`abs_mag_band`、`abs_mag_source`、`abs_mag_discovery`、`peak_mag`、`peak_filter`、`peak_mjd`、`center_sep_arcsec`、`d_dlr`、`offset_kpc`、`run_date` |

### 1.3 `obs` schema（`SQL/observation.sql`、`Schema - Observation.md`）

| 表 | 舊表名 | 用途 | 主要欄位 / 索引 |
| --- | --- | --- | --- |
| `obs.targets` | `observation_targets` | 觀測目標清單 | `target_id SERIAL PK`；`active BOOL DEFAULT TRUE`；`name TEXT NOT NULL`（不含前綴）；`mag`；`ra`、`dec DOUBLE NOT NULL`；`telescope TEXT NOT NULL`（LOT/SLT）；`program`（R01/R07…）；`priority TEXT DEFAULT 'Normal' CHECK IN ('Urgent','High','Normal','Filler')`；`plan_filter TEXT[]`、`plan_count INT[]`（重複次數）、`plan_time INT[]`（曝光秒）三個等長陣列；`repeat INT`；`plan TEXT`（給 staff）；`note TEXT`（給群組）；`create_by INT FK users`；`UNIQUE (name, telescope)`。DDL 索引 `obs_targets_active_tel_idx (active, telescope)`、`obs_targets_priority_idx`。**執行期新增**：欄位 `auto_exposure BOOLEAN NOT NULL DEFAULT FALSE`（`obs.py`）；索引 `obs_targets_active_idx (active, name)`（`_ensure_extra_tables`） |
| `obs.logs` | `observation_logs` | 每次觀測嘗試一列 | `log_id SERIAL PK`；`target_id INT FK targets SET NULL`（可為 NULL = orphan log）；`date TIMESTAMPTZ NOT NULL`；`name`；`telescope NOT NULL`；`program`；`priority CHECK`；`repeat`；`trigger_by INT FK users`；`trigger BOOL`；`observed BOOL`；`trigger_filter/trigger_count/trigger_time`、`observed_filter/observed_count/observed_time`（陣列三元組，同 targets）。DDL 索引 `obs_logs_target_date_idx`、`obs_logs_telescope_idx`。**執行期新增**：唯一約束 `obs_logs_target_date_uniq UNIQUE (target_id, date)`；索引 `obs_logs_date_idx (date)`、`obs_logs_name_idx (name)` |

> 文件不一致：`Observation/obs.logs.md` 把 `*_count` 寫成秒、`*_time` 寫成分鐘，但 DDL 註解與程式碼（`_log_to_dict` 把 count→`count`、time→`exp`）都是「count = 重複次數、time = 曝光秒」。`obs.targets.md` 列了 `obs_targets_name_uniq UNIQUE(name)`，DDL 實際是 `UNIQUE (name, telescope)`。

### 1.4 `cat` schema（`SQL/catalog.sql`、`Schema - Catalog.md`）

| 表 | 舊表名 | 用途 | 主要欄位 / 索引 |
| --- | --- | --- | --- |
| `cat.desi` | `desi_data` | DESI 光譜紅移星表 | `desi_target_id BIGINT PK`；`ra`、`dec DOUBLE NOT NULL`；`redshift`、`redshift_err`、`delta_chi_2`；`zwarn INT`（0 乾淨 / 1 ZWARN）。索引 `cat_desi_ra_dec_idx`。程式會偵測 `q3c` extension 存在時改用 `q3c_radial_query` |
| `cat.lens` | （合併多個 lens 星表） | 重力透鏡星表 | `lens_id SERIAL PK`；`ra`、`dec`；`z_lens`、`z_source`；`lens_probability`；`lens_grade`；`known TEXT CHECK IN ('known','unknown','candidate')`；`reference`。索引 `cat_lens_ra_dec_idx` |
| `cat.ned` | （新） | NED cone-search 結果快取（每 object+radius 一列） | `ned_id SERIAL PK`；`object_name TEXT`；`ra_center`、`dec_center`；`radius_arcsec DOUBLE DEFAULT 60`；`searched_at`；`result_count INT`；`results JSONB DEFAULT '[]'`；`UNIQUE (object_name, radius_arcsec)`。同時存在於 `SQL/catalog.sql` 與 `_ensure_extra_tables`（後者為 `IF NOT EXISTS`）。`Schema - Catalog.md` 未列出此表 |

`Schema - Catalog.md` 另註「cat. AGN / CV / VS ..? need to check」，目前沒有對應表或程式。`app/test_db.py` 仍查詢舊表 `lens_hsu`、`lens_karp`、`lens_catalogue`，這些不在新 schema 中。

---

## 2. 連線層（`app/modules/database/__init__.py`）

### 2.1 設定來源

- 以 `load_dotenv(<專案根>/kinder.env, override=True)` 載入；讀取 `PG_HOST`（預設 `localhost`）、`PG_PORT`（`5432`）、`PG_USER`（`postgres`）、`PG_PASSWORD`（空字串）、`DEBUG`。`DB_NAME` 寫死為 `"Kinder"`。
- 模組層級匯出 `DB_HOST`、`DB_PORT`、`DB_USER`、`DB_PASSWORD`、`DB_NAME`，被 `routes/auth/database_status_routes.py`（自行 `psycopg2.connect`，`application_name='kinder_db_status'`，**不走連線池**）、`modules/db_monitor.py`（`DB_USER` 用於 `pg_stat_activity` 過濾）、`modules/detect_pipeline.py`（傳給 DETECT 子行程）使用。
- 池大小：`DEBUG=true` → `_POOL_MIN=1, _POOL_MAX=10`；否則 `2 / 60`。

### 2.2 `init_connection_pool(minconn=_POOL_MIN, maxconn=_POOL_MAX)`

單例建立 `psycopg2.pool.ThreadedConnectionPool`，參數：`host/port/database/user/password`、`connect_timeout=5`、`options="-c idle_in_transaction_session_timeout=300000 -c statement_timeout=120000"`（伺服器端 5 分鐘 idle-in-transaction、2 分鐘單句逾時）、`keepalives=1, keepalives_idle=60, keepalives_interval=10, keepalives_count=5`。建池後呼叫 `_ensure_extra_tables()`。`main.py` 啟動時先 `check_db_connection()` 再 `init_connection_pool()`；`get_db_connection`/`get_tns_db_connection` 也會延遲呼叫它。

### 2.3 兩種取得連線的方式

| | `get_db_connection()` | `get_tns_db_connection()` |
| --- | --- | --- |
| 型態 | `@contextmanager`，用 `with get_db_connection() as conn:` | 一般函式，回傳 `_PooledConn`，**呼叫端必須在 `finally` 呼叫 `conn.close()`** |
| 取連線 | `p.getconn()`；若 `conn.closed`（伺服器端已關）則 `putconn(close=True)` 後重取一次 | `p.getconn()`，**不檢查 `closed`** |
| 執行中例外 | `psycopg2.OperationalError` → `putconn(conn, close=True)` 丟棄該連線再 re-raise | 無特別處理 |
| 歸還 | `finally` 呼叫 `_reset_conn`（有未結束/錯誤交易就 `rollback`）再 `putconn` | `close()` 被攔截：`_reset_conn` 成功才 `putconn`，失敗時 `_reset_conn` 已 `putconn(close=True)` |
| commit | **不自動 commit**；忘記 `conn.commit()` 會在歸還時被 rollback、寫入靜默消失 | 同上 |
| 使用者 | 本套件所有函式、`modules/*`（`db_monitor`、`phot_scheduler`、匯入器…）、`routes/auth/admin_routes.py`（別名 `tns_conn`）、`routes/marshal/marshal_routes.py`、`routes/private_area/private_area_routes.py`、`app/test_db.py` | `routes/marshal/object_routes.py`（10 處）、`routes/web_api/web_api_routes.py`（2）、`routes/astronomy_tools/astronomy_tools_routes.py`（2）、`modules/observation_script.py`（1）、`modules/phot_scheduler.py`（2）；grep 確認每處都有對應 `conn.close()` |

`_PooledConn`（`__slots__ = ('_conn','_pool')`）：`__getattr__`/`__setattr__` 全轉發到內部 psycopg2 connection，只覆寫 `close()`。**沒有 `__enter__`/`__exit__`**，所以 `with get_tns_db_connection() as conn:` 會失敗（目前無人這樣用）；對同一個物件呼叫兩次 `close()` 第二次會因 psycopg2 pool 已移除 key 而丟 `PoolError`。名稱裡的 `tns` 是舊 kinder_web 時代分庫留下的，現在與 `get_db_connection` 連的是同一個 Kinder 池。

`_reset_conn(conn, pool_ref) -> bool`：`conn.status` 為 `STATUS_IN_TRANSACTION`(2) 或 `STATUS_IN_ERROR`(4) 時 `rollback()`；rollback 本身失敗則 `putconn(conn, close=True)` 並回傳 False（呼叫端不得再 putconn）。

### 2.4 其他公開函式

| 函式 | 行為 | 被誰呼叫 |
| --- | --- | --- |
| `get_pool_stats() -> dict` | 回傳 `{pool_min, pool_max, in_use, idle, usage_pct}`；讀 psycopg2 **私有屬性** `p._used`、`p._pool`；池未建或例外時全 0 | `modules/db_monitor.py::check_and_alert`（排程每 10 分鐘，超閾值寄信） |
| `close_connection_pool()` | `closeall()` 並把單例設回 None | **無任何呼叫者** |
| `recycle_idle_connections()` | 用私有 `p._lock` 鎖住後把 `p._pool` 內所有 idle 連線取出、清空、逐一 `close()`；目的為避免長壽命連線 | `main.py` 排程 `id='db_recycle'` 每 30 分鐘（僅在非 DEBUG 且取得背景工作檔鎖的行程） |
| `check_db_connection() -> bool` | 用**獨立** `psycopg2.connect(connect_timeout=5)` 試連即關；成功 log info、失敗 log error | `main.py` 啟動、`is_db_available` |
| `is_db_available(force=False) -> bool` | 快取 `_status_cache`（`_STATUS_CACHE_SECONDS = 15`）；狀態翻轉時記錄「connection lost/restored」 | `routes/basic/basic_routes.py` 首頁 `db_offline` 橫幅 |
| `_ensure_extra_tables()` | 見 §1；建 `auth.invitations`、`auth.system_settings`、`transient.object_source_permissions`、`cat.ned`、`phot_uniq`、`obs_logs_target_date_uniq`、`kinder_id` 欄位與 10 個索引（`objects_kinder_id_idx`、`objects_discovery_date_idx`、`objects_name_prefix_idx`、`objects_type_idx`、`objects_last_phot_date_idx`、`objects_name_idx`、`obs_logs_date_idx`、`obs_logs_name_idx`、`obs_targets_active_idx`、`cat_ned_object_radius_idx`）、`tag` 預設值回填 | `init_connection_pool` |

補充：psycopg2 的 `ThreadedConnectionPool.putconn` 本身只保留至多 `minconn` 條 idle 連線（超出即真正關閉），因此正式環境 `recycle_idle_connections` 每次最多只會關 2 條；同時 psycopg2 歸還時也會對非 idle 交易自動 rollback，`_reset_conn` 是額外保險。

### 2.5 `OBJECT_COMPAT_COLS`

以 `o` 為 `transient.objects` 別名的 SELECT 欄位片段，讓 route 端仍能用舊 `tns_objects` 欄位名讀取。使用者：`transient.py::search_tns_objects`、`routes/marshal/object_routes.py`（3 處 f-string 查詢）、`routes/web_api/web_api_routes.py`、`routes/astronomy_tools/astronomy_tools_routes.py`（2 處）。

| 輸出欄位（別名） | 來源運算式 | 說明 |
| --- | --- | --- |
| `obj_id` | `o.obj_id` | |
| `objid` | `o.obj_id` | 舊 TNS `objid` 名稱 |
| `kinder_id` | `o.kinder_id` | |
| `name_prefix` | `o.name_prefix` | |
| `name` | `o.name` | 無前綴 |
| `ra` | `o.ra` | |
| `declination` | `o.dec` | |
| `redshift` | `o.redshift` | |
| `type` | `o.type` | |
| `typeid` | `NULL::int` | 舊欄位，固定 NULL |
| `reporting_group` | `o.report_group` | |
| `reporting_groupid` | `NULL::int` | 固定 NULL |
| `source_group` | `o.source_group` | |
| `source_groupid` | `NULL::int` | 固定 NULL |
| `discoverydate` | `to_char(TIMESTAMP '1858-11-17' + o.discovery_date * INTERVAL '1 day','YYYY-MM-DD HH24:MI:SS')` | MJD → 字串；NULL 保留 |
| `discoverymag` | `o.discovery_mag` | |
| `discmagfilter` | `o.discovery_filter` | |
| `filter` | `o.discovery_filter` | 同上再給一個別名 |
| `reporters` | `array_to_string(o.reporters, ', ')` | 陣列 → 逗號字串 |
| `time_received` | MJD→字串（`o.received_date`） | |
| `internal_names` | `COALESCE(o.internal_name,'') \|\| CASE WHEN o.other_name IS NOT NULL THEN ', ' \|\| o.other_name ELSE '' END` | 兩欄合併 |
| `discovery_ads_bibcode` | `o.discovery_ADS` | |
| `class_ads_bibcodes` | `o.class_ADS` | |
| `creationdate` | MJD→字串（`o.creation_date`） | |
| `last_photometry_date` | MJD→字串（`o.last_phot_date`） | |
| `lastmodified` | MJD→字串（`o.last_modified_date`） | |
| `brightest_mag` / `brightest_abs_mag` | 原欄位 | |
| `pin` | `o.pin::int` | BOOL → 0/1 |
| `tags` | `array_to_string(o.tag, ', ')` | **真正的 `tag TEXT[]` 欄位**，字串化 |
| `tag` | `CASE o.status WHEN 'Finish' THEN 'finished' WHEN 'Follow-up' THEN 'followup' WHEN 'Snoozed' THEN 'snoozed' ELSE 'object' END` | **由 status 推導的舊制標籤字串，遮蔽了同名的 `tag` 陣列欄位** |
| `status` | `o.status` | 新制值 |
| `inbox` | `CASE WHEN o.status NOT IN ('Snoozed') THEN 1 ELSE 0 END` | 注意：Inbox、Follow-up、Finish 都是 1 |
| `snoozed` | `status = 'Snoozed'` → 1/0 | |
| `follow` | `status = 'Follow-up'` → 1/0 | |
| `finish_follow` | `status = 'Finish'` → 1/0 | |
| `permission` / `groups` | 原欄位 | |

---

## 3. 各檔案函式清單

### 3.1 `auth.py`

範圍：`auth.*` 四表 + `auth.invitations`、`auth.system_settings`，以及存放在 `transient.objects.permission/groups`、`transient.object_source_permissions`、`transient.default_permissions` 的物件/來源權限。回傳 dict 使用舊 kinder_web 的 key 名稱。私有 helper：`_ensure_api_key_request_col()`（import 時執行 DDL）、`_user_row_to_dict(row)`（加 `is_admin`(roles≥50)、`is_super_admin`(≥99)、`role_level`、`role`('admin'/'user'/'guest')、`profile_picture`、`picture`、`display_name`、`groups=[]`、`has_api_key`、`api_key_request_pending`，時間欄位轉 ISO 字串）、`_group_row_to_dict(row)`（加 `group_name`、`manager_email`）、`_system_default_for_source(name)`（名稱含 `tns` → `'public'`，否則 `'login'`）。共用片段 `_USER_SELECT`、`_GROUP_SELECT`。

**使用者（`auth.users`）**

| 函式（簽名） | 用途 | 讀/寫的表 | 回傳結構 | 被誰呼叫 |
| --- | --- | --- | --- | --- |
| `get_user(email: str) -> dict \| None` | 依 email 取使用者，另查 joined 群組名稱填入 `groups` | 讀 `auth.users`、`auth.usr_group`、`auth.groups` | user dict（`_user_row_to_dict`）或 None；**例外不攔截** | `routes/auth/auth_routes.py`、`routes/basic/basic_routes.py` |
| `get_users() -> dict[str, dict]` | 全部使用者（`join_date DESC`）+ 一次查所有 joined 成員關係 | 讀同上 | `{email: user_dict}` | `routes/auth/admin_routes.py`、`routes/auth/auth_routes.py`、`routes/private_area/private_area_routes.py` |
| `user_exists(email: str) -> bool` | | 讀 `auth.users` | bool | `routes/auth/admin_routes.py`、`routes/auth/auth_routes.py`、`routes/basic/basic_routes.py`、`routes/api_routes.py`、`routes/private_area/private_area_routes.py` |
| `save_user(email, name='', picture_url='', is_admin=False) -> dict \| None` | 登入 upsert：新建時 `roles = 50 if is_admin else 1`；已存在則只更新 `name`、`picture_url`、`last_login=now()`（**roles 不動**） | 寫 `auth.users` | user dict 或 None | `routes/auth/admin_routes.py`、`routes/auth/auth_routes.py` |
| `update_user(email, **kwargs) -> bool` | 白名單 `name/picture_url/picture/profile_picture/display_name/roles/last_login`，`is_admin` 轉 roles 50/1 | 寫 `auth.users` | bool（rowcount>0） | `routes/auth/admin_routes.py`、`routes/auth/auth_routes.py` |
| `delete_user(email) -> bool` | 刪除（FK CASCADE 帶走 usr_group、images） | 寫 `auth.users` | bool | `routes/auth/admin_routes.py` |

**API key（`auth.users.api_key` / `api_key_requested_at`）**

| 函式（簽名） | 用途 | 讀/寫的表 | 回傳結構 | 被誰呼叫 |
| --- | --- | --- | --- | --- |
| `generate_api_key_for_user(email) -> str \| None` | 產生 48 字元 `secrets.choice` 明文 key 並清除申請時間 | 寫 `auth.users` | key 字串；使用者不存在回 None | `routes/auth/admin_routes.py`、`routes/api_routes.py`、`routes/web_api/web_api_routes.py` |
| `revoke_api_key(email) -> bool` | `api_key=NULL, api_key_requested_at=NULL` | 寫 | bool | `routes/auth/admin_routes.py` |
| `request_api_key(email) -> bool` | `api_key_requested_at=now()` | 寫 | bool | `routes/auth/auth_routes.py` |
| `get_api_key_requests() -> list[dict]` | 待處理申請（`api_key_requested_at IS NOT NULL`，時間升冪） | 讀 | `[{email, name, has_key, api_key_requested_at(ISO)}]` | `routes/auth/admin_routes.py` |
| `get_user_by_api_key(api_key) -> dict \| None` | 以明文 key 直接等值查詢 | 讀 | user dict 或 None | `routes/web_api/web_api_routes.py`、`routes/astronomy_tools/astronomy_tools_routes.py` |

**群組（`auth.groups`）**

| 函式（簽名） | 用途 | 讀/寫的表 | 回傳結構 | 被誰呼叫 |
| --- | --- | --- | --- | --- |
| `get_groups(user_email=None) -> dict[str, dict]` | 全部群組（或該使用者 joined 的群組）+ 每群組 `members`（email 清單） | 讀 `auth.groups`、`auth.users`、`auth.usr_group` | `{group_name: {group_id,name,description,joinable,create_by,manager,manager_email,manager_name,group_name,members[]}}` | `routes/auth/admin_routes.py`、`routes/basic/basic_routes.py`、`routes/private_area/private_area_routes.py` |
| `get_all_groups() -> list[dict]` | 直接回傳 `get_groups()`（**實際是 dict，型別註記錯誤**） | 同上 | dict | `routes/marshal/object_routes.py` |
| `create_group(name, description='', creator_email=None, manager_email=None, joinable=True) -> dict \| None` | 以 email 反查 usr_id 後 INSERT | 寫 `auth.groups`；讀 `auth.users` | group dict 或 None | `routes/auth/admin_routes.py` |
| `delete_group(name) -> bool` | 依 name 刪除 | 寫 `auth.groups` | bool | `routes/auth/admin_routes.py` |
| `group_exists(name) -> bool` | | 讀 | bool | `routes/auth/admin_routes.py`、`routes/auth/auth_routes.py`、`routes/basic/basic_routes.py` |

**成員關係與加入申請（`auth.usr_group`）**

| 函式（簽名） | 用途 | 讀/寫的表 | 回傳結構 | 被誰呼叫 |
| --- | --- | --- | --- | --- |
| `add_user_to_group(email, group_name, status='joined') -> bool` | upsert `(usr_id, group_id)`，衝突時覆寫 status | 寫 `auth.usr_group`；讀 users/groups | bool（找不到 user/group 回 False） | `routes/auth/admin_routes.py` |
| `remove_user_from_group(email, group_name) -> bool` | DELETE | 寫 | bool | `routes/auth/admin_routes.py`、`routes/auth/auth_routes.py`、`routes/basic/basic_routes.py` |
| `user_in_group(email, group_name) -> bool` | 僅 `status='joined'` 算在內 | 讀 | bool | `routes/auth/admin_routes.py`、`routes/auth/auth_routes.py` |
| `create_group_request(email, group_name) -> bool` | = `add_user_to_group(..., status='request')` | 寫 | bool | `routes/auth/auth_routes.py`、`routes/basic/basic_routes.py` |
| `get_group_requests(group_name=None) -> list[dict]` | `status='request'` 的列（可限定群組） | 讀 | `[{usr_id,group_id,status,created_at(ISO),email,user_name,group_name}]` | `routes/auth/admin_routes.py` |
| `get_group_request(email, group_name) -> dict \| None` | 該 user/group 的單列（不限 status；`created_at` 未轉字串） | 讀 | dict 或 None | `routes/auth/admin_routes.py` |
| `get_user_group_requests(email) -> list[dict]` | 使用者所有 usr_group 列（不限 status） | 讀 | list[dict] | `routes/auth/auth_routes.py`、`routes/basic/basic_routes.py` |
| `update_group_request_status(email, group_name, new_status) -> bool` | `'joined' / 'rejected' / 'request'` | 寫 | bool | `routes/auth/admin_routes.py` |
| `delete_group_request(email, group_name) -> bool` | = `remove_user_from_group` | 寫 | bool | `routes/auth/admin_routes.py` |

**邀請（`auth.invitations`）**

| 函式（簽名） | 用途 | 讀/寫的表 | 回傳結構 | 被誰呼叫 |
| --- | --- | --- | --- | --- |
| `get_invitations(status='pending') -> list[dict]` | 依 status 列出，`invited_at DESC` | 讀 | list[dict]（時間 ISO） | `routes/auth/admin_routes.py` |
| `create_invitation(email='', is_admin=False, role='user', invited_by_email=None) -> str \| None` | `secrets.token_urlsafe(32)`；空 email 存 NULL | 寫；讀 `auth.users` | token 或 None | `routes/auth/admin_routes.py` |
| `get_invitation(token) -> dict \| None` | `SELECT *` | 讀 | dict 或 None | `routes/auth/admin_routes.py` |
| `update_invitation(token, **kwargs) -> bool` | 白名單 `email/is_admin/role/status/accepted_at` | 寫 | bool | `routes/auth/admin_routes.py` |
| `delete_invitation(token) -> bool` | | 寫 | bool | `routes/auth/admin_routes.py` |
| `clean_accepted_invitations() -> int` | 刪 `status='accepted'` | 寫 | 刪除筆數 | `routes/auth/admin_routes.py` |

**頁面群組權限與系統設定（`auth.system_settings`）**

| 函式（簽名） | 用途 | 讀/寫的表 | 回傳結構 | 被誰呼叫 |
| --- | --- | --- | --- | --- |
| `get_page_groups(page_key) -> list[str]` | 讀 key `page_perm:<page_key>` 並 `json.loads` | 讀 | 群組名稱清單（解析失敗回 `[]`） | `routes/private_area/private_area_routes.py` |
| `set_page_groups(page_key, group_names) -> bool` | `json.dumps` 後 `set_setting` | 寫 | bool | `routes/private_area/private_area_routes.py` |
| `get_setting(key, default=None)` | | 讀 | `value` 字串或 default | `routes/auth/admin_routes.py`（及 `get_page_groups`） |
| `set_setting(key, value) -> bool` | upsert，`value` 一律 `str()` | 寫 | bool | `routes/auth/admin_routes.py`（及 `set_page_groups`） |

**物件層權限（`transient.objects.permission` / `.groups`）**

| 函式（簽名） | 用途 | 讀/寫的表 | 回傳結構 | 被誰呼叫 |
| --- | --- | --- | --- | --- |
| `get_object_permissions(object_name) -> dict` | 依 `name` 取 `{permission, groups}`；找不到回 `{'public', []}` | 讀 `transient.objects` | dict | `routes/marshal/object_routes.py` |
| `grant_object_permission(object_name, group_name, granted_by='') -> bool` | `permission='groups'`，`groups` 併入 group_id 並去重；`granted_by` 未使用 | 寫 `transient.objects`；讀 `auth.groups` | bool | `routes/marshal/object_routes.py` |
| `revoke_object_permission(object_name, group_name) -> bool` | `array_remove`（**不會把 permission 改回 public/login**） | 寫 `transient.objects` | bool | `routes/marshal/object_routes.py` |
| `check_object_access(object_name, user_email=None, user_roles=0) -> bool` | roles≥50 → True；物件不存在 → False；`public` → True；未登入 → False；`login` → True；`groups` → 使用者需 joined 任一 `groups` 內群組 | 讀 `transient.objects`、`auth.usr_group`、`auth.users` | bool | `routes/marshal/object_routes.py`、`routes/auth/auth_routes.py` |

**來源層權限（`transient.object_source_permissions` / `transient.default_permissions`）**

| 函式（簽名） | 用途 | 讀/寫的表 | 回傳結構 | 被誰呼叫 |
| --- | --- | --- | --- | --- |
| `get_source_permissions(object_name, data_type='phot') -> list[dict]` | 該物件/類型的所有覆寫列 | 讀 `object_source_permissions` | `[{id,object_name,data_type,source_name,allowed_groups,is_public,updated_at}]` | `routes/marshal/object_routes.py` |
| `get_default_source_permissions(source_name=None) -> list[dict]` | 全部或單一來源預設 | 讀 `default_permissions` | `[{source, permission(=permissions_set), groups}]` | `routes/marshal/object_routes.py`、`routes/auth/admin_routes.py` |
| `set_source_permissions_batch(object_name, data_type, permissions) -> bool` | 每項 `{source_name, is_public, allowed_groups}` upsert | 寫 `object_source_permissions` | bool | `routes/marshal/object_routes.py` |
| `set_default_source_permissions_batch(permissions) -> bool` | **先 `DELETE` 全表**再逐筆 INSERT `{source, permission, groups}` | 寫 `default_permissions` | bool | `routes/auth/admin_routes.py` |
| `filter_by_source_permissions(object_name, data_type, source_list, user_email=None, user_groups=None, is_admin=False)` | 過濾來源名稱清單或紀錄 dict 清單（以 `telescope`/`source`/`source_name` 取來源）：admin 全放行；有覆寫列 → `is_public` / `allowed_groups`(NULL 登入即可、`[]` 封鎖、ids 交集)；無覆寫但有預設 → `public`/`login`/`groups`（群組空集合視為登入即可）；都沒有 → `_system_default_for_source`。DB 錯誤時**回傳原清單（不過濾）** | 讀 `object_source_permissions`、`default_permissions`、`auth.groups` | 與輸入同型態的子集合 | `routes/marshal/object_routes.py`、`routes/astronomy_tools/astronomy_tools_routes.py` |

**相容 no-op**

| 函式（簽名） | 用途 | 讀/寫的表 | 回傳結構 | 被誰呼叫 |
| --- | --- | --- | --- | --- |
| `check_data_consistency() -> dict` | 固定 `{'status':'ok','issues':[]}` | 無 | dict | `routes/auth/admin_routes.py` |
| `clean_data_consistency() -> int` | 固定 `0` | 無 | int | `routes/auth/admin_routes.py` |

### 3.2 `catalog.py`

範圍：`cat.desi`、`cat.lens` 錐形搜尋與統計、`cat.ned` 快取。`cone_search_*` 每次先開一條連線查 `pg_extension` 是否有 `q3c`，有則用 `q3c_radial_query(ra, dec, ra0, dec0, r_deg)`，否則以 `cos(dec)` 修正的 bounding box 代替，然後再開第二條連線查詢。

| 函式（簽名） | 用途 | 讀/寫的表 | 回傳結構 | 被誰呼叫 |
| --- | --- | --- | --- | --- |
| `cone_search_desi(ra, dec, radius_arcsec=5.0, z_min=None, z_max=None) -> list[dict]` | DESI 錐形搜尋，`LIMIT 50`；可加紅移範圍 | 讀 `cat.desi`、`pg_extension` | `[{desi_target_id, ra, dec, redshift, redshift_err, delta_chi_2, zwarn}]`；錯誤回 `[]` | `modules/detect_cross_match.py` |
| `search_desi_by_targetid(target_id) -> dict \| None` | 依 PK 查 | 讀 `cat.desi` | dict 或 None | **無呼叫者** |
| `get_desi_statistics() -> dict` | `{'total', 'with_redshift'}` | 讀 `cat.desi` | dict | **無呼叫者** |
| `cone_search_lens(ra, dec, radius_arcsec=30.0) -> list[dict]` | 透鏡星表錐形搜尋，`LIMIT 20` | 讀 `cat.lens`、`pg_extension` | `[{lens_id, ra, dec, z_lens, z_source, lens_probability, lens_grade, known, reference}]` | `modules/detect_cross_match.py` |
| `get_lens_by_id(lens_id) -> dict \| None` | 依 PK 查 | 讀 `cat.lens` | dict 或 None | **無呼叫者** |
| `get_lens_statistics() -> dict` | 依 `known` 分組計數 | 讀 `cat.lens` | `{'total': n, 'known'/'unknown'/'candidate': n}` | **無呼叫者** |
| `get_ned_cache(object_name, radius_arcsec) -> dict \| None` | 讀快取 | 讀 `cat.ned` | `{result_count, results(list), searched_at(ISO), from_cache: True}` 或 None | `routes/marshal/object_routes.py` |
| `upsert_ned_cache(object_name, ra_center, dec_center, radius_arcsec, results) -> None` | `ON CONFLICT (object_name, radius_arcsec)` 更新，`results` 以 `json.dumps` 寫入 JSONB | 寫 `cat.ned` | None | `routes/marshal/object_routes.py` |

### 3.3 `obs.py`

範圍：`obs.targets`、`obs.logs`。私有 helper：`_ensure_auto_exposure_column()`、`_parse_mag_value(v)`（去掉上限記號 `>`；非數字回 None）、`_parse_ra_deg(v)`（接受度或 `HH:MM:SS`/空白分隔 HMS，結果 `% 360`）、`_parse_dec_deg(v)`（度或 DMS，範圍 ±90）、`_target_to_dict(row)`（把 `plan_filter/plan_count/plan_time` 三陣列 zip 成 `filters=[{filter,count,exp}]`，另加 `created_by`、`id`、`is_active`、`repeat_count`、`note_gl`、`auto_exposure`，**`ra`/`dec` 轉成字串**）、`_log_to_dict(row)`（`trigger_*`/`observed_*` 三陣列 → `trigger_filters`/`observed_filters` list 以及逗號字串 `trigger_filter`/`trigger_count`/`trigger_exp`；`date` → `'YYYY-MM-DD'`；加 `triggered_by`、`obs_date`、`target_name`（優先 JOIN 的 targets.name）、`telescope_use`、`repeat_count`、`is_triggered`、`is_observed`、`user_name`）、`_split_csv`、`_coerce_log_filters(filter, exp, count)`（接受 dict list / JSON 字串 / 逗號字串）、`_resolve_target_id(cur, name, telescope='')`（先 name+telescope，再只用 name；`active DESC, target_id DESC`）。

| 函式（簽名） | 用途 | 讀/寫的表 | 回傳結構 | 被誰呼叫 |
| --- | --- | --- | --- | --- |
| `get_observation_targets(active_only=True) -> list[dict]` | 先跑 `_ensure_auto_exposure_column()`；`ORDER BY priority, name`（`priority` 為文字排序，非 Urgent→Filler 語意順序） | 讀 `obs.targets`、`auth.users`；DDL 寫 | `_target_to_dict` 清單 | `routes/web_api/web_api_routes.py`、`routes/private_area/private_area_routes.py`、`modules/phot_scheduler.py` |
| `save_observation_target(name, ra, dec, mag=None, telescope='', program='', priority='Normal', filters=None, repeat=0, plan='', note='', created_by_email=None, auto_exposure=False, **legacy_kwargs) -> int \| None` | upsert `ON CONFLICT (name, telescope)`（更新時 `active` 不改）；接受舊參數 `repeat_count`/`note_gl`/`user_email`；`telescope=='LOT'` 強制 `auto_exposure=False`；`filters` 每項 dict `{filter,count,exp|time}` 或字串（預設 count 1、exp 60） | 寫 `obs.targets`；讀 `auth.users` | `target_id` 或 None（解析失敗亦回 None） | `routes/web_api/web_api_routes.py`、`routes/private_area/private_area_routes.py` |
| `update_observation_target(target_id, **kwargs) -> bool` | 白名單 `name/mag/ra/dec/telescope/program/priority/repeat/plan/note/auto_exposure` + `filters`；亦接受 `repeat_count`/`note_gl` | 寫 `obs.targets` | bool | `routes/private_area/private_area_routes.py` |
| `update_observation_target_status(target_id, active) -> bool` | 切換 `active` | 寫 | bool | `routes/private_area/private_area_routes.py` |
| `delete_observation_target(target_id) -> bool` | DELETE（logs 的 `target_id` 變 NULL） | 寫 | bool | `routes/private_area/private_area_routes.py` |
| `get_observation_log_months() -> list[dict]` | 有紀錄的年月 | 讀 `obs.logs` | `[{year, month}]` | `routes/private_area/private_area_routes.py` |
| `get_observation_logs(year_or_month=None, month=None, target_name=None, telescope=None) -> list[dict]` | 多型：`(2026, 3)` 或 `'2026-03'`；月份以 `date >= 首日 AND date < 次月首日` 的 sargable 範圍過濾；`target_name` 用 `t_obj.name ILIKE %<name>%` | 讀 `obs.logs`、`auth.users`、`obs.targets` | `_log_to_dict` 清單，`date DESC, log_id DESC` | `routes/web_api/web_api_routes.py`、`routes/private_area/private_area_routes.py` |
| `upsert_observation_log(target_id_or_name, date, name_or_user, *args, **kwargs) -> int \| None` | 多型簽名：第一參數為 int 時當 `target_id`（`name`、`telescope`、filters 由 kwargs 取）；為字串時當目標名，`name_or_user` 當觀測者（以 email 或 name 反查 `trigger_by`），`args` 依序 `trigger, observed, trigger_filter, trigger_exp, trigger_count, observed_filter, observed_exp, observed_count`。priority 正規化為 Title case。以 `(name, date, telescope)` 找既有列則 UPDATE，否則 INSERT；目標不在 `obs.targets` 時存 `target_id=NULL` 的 orphan log | 寫 `obs.logs`；讀 `auth.users`、`obs.targets` | `log_id` 或 None | `routes/web_api/web_api_routes.py`、`routes/private_area/private_area_routes.py` |
| `delete_observation_log(log_id_or_name, obs_date=None, telescope=None) -> bool` | int → 依 `log_id`；字串 → `_resolve_target_id` 後 `DELETE WHERE target_id AND date`（**不再以 telescope 限制**） | 寫 `obs.logs` | bool | `routes/web_api/web_api_routes.py`、`routes/private_area/private_area_routes.py` |

### 3.4 `transient.py`

範圍：`transient.objects`/`photometry`/`spectroscopy`/`cross_matches`/`target_images`/`download_logs`/`object_views(_detail)`/`comments`/`tns_update_audit`，以及唯讀 `transient.detect_screen`。回傳值使用舊 `tns_objects` 欄位別名。模組層快取：`_marshal_stats_cache`（30 s）、`_detect_metadata_cache`（120 s）、`_detect_overview_cache`（60 s），皆為行程內記憶體、`time.monotonic()` 計時。

私有 helper（route 端有直接匯入者以 ★ 標示）：`_ensure_cross_matches_flag_column(cur, conn)`、`_resolve_obj_id(cur, name)`（精確 name）、`_resolve_obj_id_with_prefix(cur, name)`（去掉 `^(AT|SN|FRB|TDE|EP)` 後 `name = %s OR name = %s`）、`_mjd_update(cur, obj_id, mjd)`（`last_phot_date` 只往後推，且 **Snoozed → Inbox**）、光譜命名：`_clean_spectrum_source_name`、`_infer_spectrum_source_name(filename)`、`_build_utc_datetime`、`_extract_spectrum_datetime(filename)`（從檔名抓 `YYYYMMDD[_HHMMSS]`）、`_parse_manual_observation_date`、`_datetime_to_mjd(dt)`（`timestamp/86400 + 40587`）、`_current_utc_mjd`、★`_phase_from_stored_value(v)`（`0 < v < 1000` 視為 phase）、★`_format_spectrum_observation_label(mjd)`、`_legacy_spectrum_source_label`、`_build_spectrum_id(source, mjd)`（`'{source}@@{mjd:.6f}'`）、★`_parse_spectrum_id`、★`_build_spectrum_label`、`_resolve_spectrum_source_and_mjd(...)`（來源優先序 telescope → spectrum_id → 檔名推斷 → `'Unknown'`；MJD 優先序 spectrum_id 內含 → 手動日期 → 檔名日期 → phase → 現在）、★`_tns_name_to_kinder_id(name)`（`modules/auto_tns_download.py` 匯入）、`_ensure_tns_update_audit_table(cur)`、`_build_where(params, ...)`（Marshal 查詢 WHERE 組裝；見 §4.2）、`_screen_row(r)`、`_host_decision_json(value, email)`、常數 `_DETECT_SCREEN_SELECT`、`_STATUS_MAP`。

**Kinder ID / 下載紀錄 / 稽核**

| 函式（簽名） | 用途 | 讀/寫的表 | 回傳結構 | 被誰呼叫 |
| --- | --- | --- | --- | --- |
| `sync_kinder_ids() -> int` | 對 `kinder_id IS NULL AND name ~ '^[0-9]{4}[a-zA-Z]+$'` 的列計算並批次寫入（大寫單字母名先 `lower()`） | 讀寫 `transient.objects` | 更新筆數 | `modules/auto_tns_download.py`、`modules/TNS_object_fetch.py`、`modules/Manual_tns_download_snoozed.py`、`modules/tns_gap_filler.py` |
| `log_download_attempt(hour_utc='', filename='') -> int \| None` | 新增 `status='In Progress'` 的列；`hour_utc` 未使用 | 寫 `download_logs` | `log_id` | `modules/auto_tns_download.py`、`modules/TNS_object_fetch.py`、`modules/Manual_tns_download_snoozed.py` |
| `update_download_log(log_id, status, records_imported=0, records_updated=0, error_message=None)` | 更新結果 | 寫 `download_logs` | None | 同上三檔 |
| `log_tns_update_batch(rows: list[tuple[int,str,list[str],str]])` | `(obj_id, name, changed_fields, source)` 批次寫入稽核表（先確保表存在） | 寫 `tns_update_audit`（DDL） | None | `modules/auto_tns_download.py`、`modules/TNS_object_fetch.py` |

**`class TNSObjectDB`（全部 `@staticmethod`；模組尾端有單例 `tns_object_db = TNSObjectDB()`，僅 `routes/detect/detect_routes.py` 用單例，其餘以類別名呼叫）**

| 方法（簽名） | 用途 | 讀/寫的表 | 回傳結構 | 被誰呼叫 |
| --- | --- | --- | --- | --- |
| `add_photometry_point(object_name, mjd, magnitude=None, magnitude_error=None, filter_name=None, telescope=None) -> int \| None` | 單點插入；負星等直接略過；`ON CONFLICT phot_uniq DO NOTHING`；成功則 `_mjd_update` | 寫 `photometry`、`objects` | `phot_id`（重複或找不到物件回 None） | `routes/marshal/object_routes.py` |
| `add_photometry_batch(object_name, points: list) -> int` | 每項 dict `{mjd, magnitude, magnitude_error, filter, telescope\|source}`；逐筆 INSERT；最後以最大 MJD `_mjd_update` | 寫 `photometry`、`objects` | 實際插入筆數 | `routes/marshal/object_routes.py` |
| `add_photometry_bulk(photometry_data)` | 多物件 tuple 清單 `(object_name, mjd, mag, mag_err, filter, telescope)`；先批次把 name→obj_id（**精確 name，不去前綴**），`execute_batch` 插入，逐物件 `_mjd_update` | 寫 `photometry`、`objects` | None | `modules/download_phot.py` |
| `sync_last_photometry_date(object_name)` | `last_phot_date = MAX("MJD")`（不做 un-snooze） | 讀 `photometry`；寫 `objects` | None | `routes/marshal/object_routes.py`、`modules/download_phot.py` |
| `get_photometry(object_name) -> list[dict]` | 過濾 `mag IS NULL OR mag >= 0`，`"MJD" ASC` | 讀 `photometry` | `[{id, object_name, mjd, magnitude, magnitude_error, filter, telescope}]` | `routes/marshal/object_routes.py`、`routes/astronomy_tools/astronomy_tools_routes.py`、`modules/download_phot.py` |
| `delete_photometry_point(point_id) -> bool` | 依 `phot_id` 刪除 | 寫 `photometry` | bool | `routes/marshal/object_routes.py` |
| `add_spectrum_data(object_name, wavelength_data, intensity_data, phase=None, telescope=None, spectrum_id=None, original_filename=None, observation_date=None)` | 由 `_resolve_spectrum_source_and_mjd` 決定 `(source, MJD)` 後每個波長點插一列；**無去重** | 寫 `spectroscopy` | 新的 `spectrum_id` 字串（物件不存在也回傳） | `routes/marshal/object_routes.py` |
| `get_spectroscopy(object_name) -> list[dict]` | 所有點，`ORDER BY source, wavelength` | 讀 `spectroscopy` | `[{id, object_name, observation_mjd, wavelength, intensity, telescope, phase, spectrum_id, spectrum_label, observation_date_label}]` | `routes/marshal/object_routes.py` |
| `get_spectrum_list(object_name) -> list[dict]` | 依 `(source, "MJD")` 彙總 | 讀 `spectroscopy` | `[{observation_mjd, min_wavelength, max_wavelength, point_count, observation_row_id, telescope, phase, spectrum_id, spectrum_label, observation_date_label}]` | `routes/marshal/object_routes.py`、`routes/astronomy_tools/astronomy_tools_routes.py` |
| `delete_spectrum(spectrum_id) -> bool` | 解析 `source@@mjd` 後 `DELETE WHERE source = %s AND ABS("MJD" - %s) < 1e-6`（無 MJD 時只以 source）；**沒有 obj_id 條件** | 寫 `spectroscopy` | bool | `routes/marshal/object_routes.py` |
| `get_object_details(object_name) -> dict \| None` | 精確 `name` 查基本欄位 | 讀 `objects` | `{name, ra, declination, discoverydate, internal_names, type, redshift, discoverymag, filter, status}` | `routes/detect/detect_routes.py`（經 `tns_object_db`） |
| `add_comment(object_name, user_email, user_name, user_picture, content) -> int \| None` | 以 email 反查 `usr_id`；`obj_id` 以去前綴解析；`name` 欄位存**傳入原字串**；`user_name`/`user_picture` 未使用 | 寫 `comments`；讀 `auth.users`、`objects` | `comment_id` | `routes/marshal/object_routes.py` |
| `get_comments(object_name) -> list[dict]` | `WHERE c.name = %s`（**以反正規化 name 比對，非 obj_id**），`comment_time ASC` | 讀 `comments`、`auth.users` | `[{id, object_name, user_email, user_name, user_picture, content, created_at(ISO)}]` | `routes/marshal/object_routes.py` |
| `get_recent_comments(limit=5) -> list[dict]` | 最新留言 + 物件 `name_prefix/type/internal_names/tags` | 讀 `comments`、`auth.users`、`objects` | list[dict] | `routes/marshal/marshal_routes.py` |
| `get_recent_tns_updates(limit=20) -> tuple[list[dict], bool]` | 先讀 2 天內稽核列（`type`/`name_prefix` 變動排前）；無資料則 fallback 到 `last_modified_date` 2 天內的物件；再無則最近 N 筆。每列加 `is_classified`、`is_new_add` | 讀 `tns_update_audit`（DDL）、`objects` | `(rows, is_fallback)` | `routes/marshal/marshal_routes.py` |
| `get_comment_by_id(comment_id) -> dict \| None` | | 讀 `comments`、`auth.users` | dict 或 None | `routes/marshal/object_routes.py` |
| `delete_comment(comment_id) -> bool` | | 寫 `comments` | bool | `routes/marshal/object_routes.py` |
| `update_comment(comment_id, content) -> bool` | | 寫 `comments` | bool | `routes/marshal/object_routes.py` |
| `log_object_view(object_name, user_email=None)` | 去掉 `^(AT|SN)` 前綴（僅這兩種）；寫明細 + upsert 計數；例外只 log | 寫 `object_views_detail`、`object_views`；讀 `auth.users`、`objects` | None | `routes/marshal/object_routes.py` |
| `get_top_viewed_objects(days=30, limit=5, mode='30days') -> list[dict]` | `mode='all'` 用累計表；否則從明細表算最近 N 天 | 讀 `object_views`、`object_views_detail`、`objects` | `[{object_name, view_count, object_type, name_prefix, internal_names, tags}]` | `routes/marshal/marshal_routes.py` |

**Marshal 物件查詢與統計（`transient.objects`）**

| 函式（簽名） | 用途 | 讀/寫的表 | 回傳結構 | 被誰呼叫 |
| --- | --- | --- | --- | --- |
| `get_objects_count(object_type=None, search_term='', tag=None, date_from=None, date_to=None, app_mag_min/max=None, redshift_min/max=None, discoverer=None, brightest_mag_min/max=None, brightest_abs_mag_min/max=None) -> int` | `_build_where` 後 `COUNT(*)` | 讀 `objects`（tag='flag' 時另查 `cross_matches`） | int | `routes/web_api/web_api_routes.py` |
| `get_tag_statistics() -> dict` | 四個 status 各 COUNT | 讀 `objects` | `{object, followup, finished, snoozed}` | `routes/web_api/web_api_routes.py` |
| `get_tns_statistics() -> dict` | 單句彙總 | 讀 `objects`、`photometry` | `{total, with_photometry, classified, with_redshift, follow, finished, snoozed}` | `routes/web_api/web_api_routes.py` |
| `get_marshal_overview_stats(cache_ttl=30) -> dict` | Marshal 首頁統計，30 s 快取；`flag_count` 用 `tag @> ARRAY['flag']` | 讀 `objects`、`photometry` | `{total_count, at_count, classified_count, inbox_count, followup_count, finished_count, snoozed_count, flag_count, tns_stats{...}}` | `routes/marshal/marshal_routes.py` |
| `search_tns_objects(search_term='', object_type='', limit=100, offset=0, sort_by='discoverydate', sort_order='desc', date_from=None, date_to=None, mag_min=None, mag_max=None, app_mag_min=None, app_mag_max=None, redshift_min=None, redshift_max=None, discoverer=None, tag=None, brightest_mag_min/max=None, brightest_abs_mag_min/max=None) -> list[dict]` | 主查詢：`SELECT {OBJECT_COMPAT_COLS} ... WHERE {_build_where} ORDER BY <sort_map[sort_by]> <ASC/DESC> NULLS LAST LIMIT/OFFSET`；`sort_by` 白名單 `discoverydate/lastmodified/discoverymag/name/time_received/last_photometry_date/brightest_mag/brightest_abs_mag/redshift`（`last_photometry_date` 用 `COALESCE(last_phot_date, last_modified_date)`）；`mag_min/max` 為 `app_mag_*` 的舊別名 | 讀 `objects`（`cross_matches`） | compat 欄位 dict 清單 | `routes/marshal/marshal_routes.py`、`routes/marshal/object_routes.py`、`routes/web_api/web_api_routes.py`、`routes/private_area/private_area_routes.py`、`routes/astronomy_tools/astronomy_tools_routes.py`、`modules/phot_scheduler.py` |
| `get_filtered_stats(search_term='', object_type='', tag=None, date_from=None, date_to=None, app_mag_min/max=None, redshift_min/max=None, discoverer=None) -> dict` | 同條件下四種 status 計數（**不接受 brightest_* 參數**） | 讀 `objects` | `{total, object, followup, finished, snoozed}` | `routes/web_api/web_api_routes.py` |
| `get_distinct_classifications() -> list[str]` | `DISTINCT type` | 讀 `objects` | list[str] | `routes/web_api/web_api_routes.py` |

**狀態 / 旗標**

| 函式（簽名） | 用途 | 讀/寫的表 | 回傳結構 | 被誰呼叫 |
| --- | --- | --- | --- | --- |
| `update_object_status(object_name, status) -> bool` | `_STATUS_MAP` 轉新制；`WHERE name = %s OR name ILIKE %s OR (COALESCE(name_prefix,'') \|\| name) ILIKE %s` | 寫 `objects` | bool（未知 status 回 False） | `routes/detect/detect_routes.py`、`routes/marshal/object_routes.py`、`routes/web_api/web_api_routes.py`、`modules/phot_scheduler.py`（`retire_stale_followups` 以 `'finished'`） |
| `update_object_activity(objid, activity_type=None)` | **no-op**，固定 True | 無 | True | `routes/marshal/object_routes.py`、`routes/web_api/web_api_routes.py` |
| `get_auto_snooze_stats() -> dict` | Snoozed / Finish 計數 | 讀 `objects` | `{snoozed_count, finished_count}` | `routes/web_api/web_api_routes.py` |
| `get_object_pin_status(object_name) -> bool` | `name = %s OR name_prefix\|\|name = %s` | 讀 `objects` | bool | `routes/web_api/web_api_routes.py` |
| `toggle_object_pin(object_name) -> bool` | `pin = NOT pin RETURNING pin` | 寫 `objects` | 新的 pin 值（找不到回 False） | `routes/web_api/web_api_routes.py` |
| `get_pinned_objects(limit=20) -> list[dict]` | `pin = TRUE`，依瀏覽數排序 | 讀 `objects`、`object_views` | `[{name, name_prefix, type, internal_names, tags, view_count}]` | `routes/marshal/marshal_routes.py` |

**Cross-match（`transient.cross_matches`）**

| 函式（簽名） | 用途 | 讀/寫的表 | 回傳結構 | 被誰呼叫 |
| --- | --- | --- | --- | --- |
| `get_daily_match_counts() -> list[dict]` | `generate_series` 每日 distinct obj_id 數與是否含 `Lens_%` | 讀 `cross_matches` | `[{date, count, has_lens}]` | `routes/detect/detect_routes.py` |
| `get_available_dates() -> list[str]` | `DISTINCT updated_date::date` | 讀 `cross_matches` | `['YYYY-MM-DD', ...]` | `routes/detect/detect_routes.py` |
| `get_cross_match_results(limit=1000, date=None) -> list` | 舊欄位名別名；有 `date` 時不套 LIMIT | 讀 `cross_matches`（DDL） | RealDict 列：`{id, target_name, catalog_name, separation_arcsec, is_host, created_at, status, flag, z, match_data, match_ra, match_dec}` | `routes/detect/detect_routes.py` |
| `get_photometry_batch(names) -> dict` | 多物件光度 | 讀 `photometry`、`objects` | `{name: [{id, mjd, magnitude, magnitude_error, filter, telescope}]}` | `routes/detect/detect_routes.py` |
| `get_object_details_batch(names) -> dict` | 多物件基本欄位 | 讀 `objects` | `{name: {name, ra, declination, discoverydate, internal_names, type, redshift, discoverymag, filter, status}}` | `routes/detect/detect_routes.py` |
| `get_latest_photometry_for_names(names) -> dict` | `DISTINCT ON (name)` 最新有效點 | 讀 `photometry`、`objects` | `{name: {name, magnitude, filter, mjd}}` | `routes/detect/detect_routes.py` |
| `get_detect_metadata(cache_ttl=120) -> dict` | 一條連線同時算 available_dates、daily_counts，再嘗試讀 `detect_screen` 每日 host_status 計數（表不存在則 rollback 略過） | 讀 `cross_matches`、`detect_screen` | `{available_dates, daily_counts[{date,count,has_lens,screen}], screen_counts}` | `routes/detect/detect_routes.py` |
| `get_detect_page_data(date) -> dict` | 一條連線：當日結果 + details + latest phot + `detect_screen` 批次（含當日只被篩選但無比對結果的 `screen_only`）+ 30 天內 `woke:%` 稽核註記 | 讀 `cross_matches`（DDL）、`objects`、`photometry`、`detect_screen`、`tns_update_audit` | `{results, details_batch, latest_phot, screen_batch, screen_only, wake_notes}`；錯誤回 `{}` | `routes/detect/detect_routes.py` |
| `get_detect_overview(cache_ttl=60) -> dict` | 最新一次 DETECT run 的 host_status 分布、待人工處理數（status='Inbox'）、前 8 高分 | 讀 `detect_screen`、`objects` | `{last_run, run_day, counts{...,total}, pending, top[]}` | `routes/detect/detect_routes.py` |
| `get_detect_lc_data(target_name) -> dict` | 一條連線取 details + 全部光度 | 讀 `objects`、`photometry` | `{details, photometry}` | `routes/detect/detect_routes.py` |
| `get_followup_objects_for_tracking() -> list` | 所有 Follow-up 物件 LEFT JOIN `is_host` 的比對列與 `detect_screen` | 讀 `objects`、`cross_matches`、`detect_screen` | list[dict]（含 `detect_*` 欄位） | `routes/detect/detect_routes.py` |
| `update_cross_match_flag(result_id, flag_value) -> bool` | 依 `match_id` 設 `flag` | 寫 `cross_matches`（DDL） | bool | `routes/detect/detect_routes.py` |
| `get_flagged_objects() -> list[list]` | `flag = TRUE` 的物件基本欄位（list of list） | 讀 `objects`、`cross_matches`（DDL） | `[[name_prefix, name, ra, dec, discoverydate, internal_name], ...]` | **無呼叫者**（DETECT 內有同名自帶版本） |
| `save_flag_objects(flag_list)` | 每項 `item[1]` 為 name；有比對列則全設 `flag=TRUE`，否則插一列 `catalog='FLAGGED_LIST'` | 寫 `cross_matches`（DDL） | None | **無呼叫者**（同上） |
| `save_cross_match_results(results_list)` | 每項 `{target_name, catalog_name, match_data{z}, separation_arcsec, is_host}` 插入（不寫 `match_data` 欄位本身） | 寫 `cross_matches` | None | **無呼叫者**（同上） |
| `get_object_flag_status(object_name) -> bool` | 該物件任一比對列 `flag = TRUE` | 讀（DDL） | bool | `routes/web_api/web_api_routes.py` |
| `update_object_flag_by_name(object_name, flag_value) -> bool` | 該物件所有比對列設 flag | 寫（DDL） | bool | `routes/web_api/web_api_routes.py` |
| `set_cross_match_host(match_id, target_name, user_email=None) -> bool` | 該物件所有列 `is_host=FALSE` 並寫 `match_data.host_user=false`，再把 `match_id` 設 `is_host=TRUE`/`host_user=true`（含 `host_user_by`、`host_user_at`） | 寫 `cross_matches.match_data` | bool | `routes/detect/detect_routes.py` |
| `unset_cross_match_host(target_name) -> bool` | 全部 `is_host=FALSE` 並移除 `host_user*` 三個 key | 寫 | bool | `routes/detect/detect_routes.py` |
| `release_cross_match_host(target_name) -> bool` | 只移除 `host_user*`，`is_host` 保留 | 寫 | bool | `routes/detect/detect_routes.py` |
| `reject_cross_match_hosts(target_name, user_email=None) -> bool` | 全部 `is_host=FALSE` 且 `host_user=false` | 寫 | bool | `routes/detect/detect_routes.py` |
| `sync_host_redshifts() -> int` | 把 `is_host=TRUE` 且 redshift 可轉數值的比對紅移寫回 `objects.redshift` | 寫 `objects`；讀 `cross_matches` | 更新筆數 | `main.py`（排程 `daily_host_redshift_sync` 每日 06:00） |

**影像（`transient.target_images`）**

| 函式（簽名） | 用途 | 讀/寫的表 | 回傳結構 | 被誰呼叫 |
| --- | --- | --- | --- | --- |
| `save_target_image(target_name, image_data: bytes) -> bool` | 該 obj_id **任一列**（`LIMIT 1`，不看 source）存在則 UPDATE，否則 INSERT `source='DESI'` | 寫 `target_images` | bool | **無呼叫者**（DETECT 內有同名自帶版本） |
| `get_target_image(target_name) -> bytes \| None` | 該物件任一列的 `image_data` | 讀 | bytes 或 None | `routes/detect/detect_routes.py` |
| `save_detect_image(target_name, source_label, image_data) -> int \| None` | 依 `(obj_id, source)` upsert | 寫 | `image_id` | **無呼叫者** |
| `get_detect_images(target_name) -> list` | `source IN ('DESI','detect_combined')`，DESI 優先，`LIMIT 1`（docstring 說只回 detect_combined，與 SQL 不符） | 讀 `target_images`、`objects` | `[{image_id, source}]`（最多 1 筆） | `routes/web_api/web_api_routes.py` |
| `get_detect_image_by_id(image_id) -> bytes \| None` | | 讀 | bytes | `routes/detect/detect_routes.py` |

**紅移與絕對星等**

| 函式（簽名） | 用途 | 讀/寫的表 | 回傳結構 | 被誰呼叫 |
| --- | --- | --- | --- | --- |
| `set_object_redshift(target_name, z) -> bool` | 只寫 `redshift`（`name = %s OR name ILIKE %s`），**不**重算絕對星等（DETECT 自己管） | 寫 `objects` | bool | `routes/detect/detect_routes.py` |
| `update_tns_redshift(target_name, redshift_str) -> bool` | 從字串抓第一個數字寫入，再呼叫 `update_object_abs_mag` | 寫 `objects` | bool | `routes/detect/detect_routes.py` |
| `update_object_abs_mag(target_name) -> bool` | 取 `mag BETWEEN 5 AND 30 AND (mag_err IS NULL OR mag_err > 0)` 最亮點（無則用 discovery_mag）寫 `brightest_mag`；有 z>0 與座標時以 `function.module.screening.absolute_magnitude`（DETECT 套件，需在 `sys.path`）算 `brightest_abs_mag` | 讀 `photometry`；寫 `objects` | bool | `routes/marshal/object_routes.py`（及 `update_tns_redshift`） |

---

## 4. 命名與相容性說明

### 4.1 舊 `tns_objects` 欄位 → 新 `transient.objects` 欄位

| 舊欄位（route / CSV / OBJECT_COMPAT_COLS 別名） | 新欄位 | 轉換 |
| --- | --- | --- |
| `objid` | `obj_id` | 匯入端：`auto_tns_download.py` 以 `kinder_id or TNS objid` 當 `obj_id`；`TNS_object_fetch.py`、`Manual_tns_download_snoozed.py` 直接用 TNS `objid`（`kinder_id` 之後由 `sync_kinder_ids()` 補） |
| `declination` | `dec` | |
| `typeid` / `reporting_groupid` / `source_groupid` | （無） | 固定 `NULL::int` |
| `reporting_group` | `report_group` | |
| `discoverydate` / `time_received` / `creationdate` / `lastmodified` / `last_photometry_date` | `discovery_date` / `received_date` / `creation_date` / `last_modified_date` / `last_phot_date` | 字串 ↔ MJD（見 §4.4） |
| `discoverymag` | `discovery_mag` | |
| `discmagfilter`、`filter` | `discovery_filter` | |
| `reporters`（逗號字串） | `reporters TEXT[]` | `array_to_string(..., ', ')` |
| `internal_names` | `internal_name` + `other_name` | 以 `', '` 串接 |
| `discovery_ads_bibcode` / `class_ads_bibcodes` | `discovery_ADS` / `class_ADS` | |
| `pin`（0/1） | `pin BOOL` | `::int` |
| `tags`（逗號字串） | `tag TEXT[]` | `array_to_string` |
| `tag`（`object`/`followup`/`finished`/`snoozed`）、`inbox`、`snoozed`、`follow`、`finish_follow`（0/1） | `status` | 由 `status` 推導（§4.2） |
| 光度 `id, object_name, mjd, magnitude, magnitude_error, filter, telescope` | `phot_id, name, "MJD", mag, mag_err, filter, source` | `TNSObjectDB.get_photometry` 等以 SQL 別名還原 |
| 光譜 `id, object_name, observation_mjd, wavelength, intensity, telescope, phase, spectrum_id` | `spec_id, name, "MJD", wavelength, intensity, source` | `phase`、`spectrum_id`、`spectrum_label`、`observation_date_label` 由程式推導 |
| 留言 `id, object_name, user_email, user_name, user_picture, content, created_at` | `comment_id, name, usr_id(JOIN users), comment, comment_time` | |
| cross-match `id, target_name, catalog_name, separation_arcsec, created_at, z` | `match_id, name, catalog, separation, updated_date, redshift` | |
| 觀測目標 `id, is_active, repeat_count, note_gl, created_by, filters[]` | `target_id, active, repeat, note, create_by(JOIN users), plan_filter/plan_count/plan_time` | `_target_to_dict` |
| 觀測紀錄 `obs_date, telescope_use, repeat_count, is_triggered, is_observed, triggered_by/user_name, trigger_filter/trigger_count/trigger_exp（逗號字串）` | `date, telescope, repeat, trigger, observed, trigger_by(JOIN users), trigger_filter/trigger_count/trigger_time（陣列）` | `_log_to_dict` |
| 使用者 `is_admin, is_super_admin, role, role_level, profile_picture/picture, display_name, groups[]` | `roles INT, picture_url, name, usr_group JOIN` | `_user_row_to_dict` |

### 4.2 `status` 值域與舊制標籤推導

- DB `CHECK`：`'Inbox' | 'Snoozed' | 'Follow-up' | 'Finish'`，預設 `'Inbox'`。
- `update_object_status` 透過 `_STATUS_MAP` 接受舊值：`'object'`、`'clear'` → `Inbox`；`'followup'` → `Follow-up`；`'finished'` → `Finish`；`'snoozed'` → `Snoozed`；也接受四個新值本身。其他字串回 False。
- 查詢端 `_build_where(tag=...)`：`'object'` → `status='Inbox'`；`'followup'`/`'finished'`/`'snoozed'` 對應新值；`'flag'` → `EXISTS (cross_matches WHERE status='Flagged')`；其他 tag 值被忽略（不過濾）。`object_type`：`'AT'` → `name_prefix='AT'`；`'Classified'` → `name_prefix != 'AT'`；其他 → `type = %s`；可逗號分隔多值（OR）。
- 輸出端 `OBJECT_COMPAT_COLS`：`tag` = `finished`/`followup`/`snoozed`/否則 `object`；`inbox = status NOT IN ('Snoozed')`（**Inbox、Follow-up、Finish 皆為 1**）；`snoozed`/`follow`/`finish_follow` 各自等值判斷。
- 自動轉換：`_mjd_update`（任何新光度點）與 `auto_tns_download.py`（`last_modified_date` 變新）、`TNS_object_fetch.py`（任何更新）都把 `Snoozed → Inbox`；`modules/phot_scheduler.py::retire_stale_followups` 以 `update_object_status(name, 'finished')` 把過期 Follow-up 收尾（排程每日 05:30）。

### 4.3 `name` / `name_prefix` / `kinder_id`

- `objects.name` 只存 TNS 名稱主體（`2026abc`、`2026A`），前綴（`AT`/`SN`/`FRB`/`TDE`/`EP`…）另存 `name_prefix`；完整顯示名 = `name_prefix || name`。
- 名稱解析：`_resolve_obj_id_with_prefix` 以正規式 `^(?:AT|SN|FRB|TDE|EP)(.+)$` 去前綴後 `name = 原字串 OR name = 去前綴`；`log_object_view` 只認 `^(?:AT|SN)(\d.+)$`；`update_object_status`、`update_object_abs_mag` 用 `name = %s OR name ILIKE %s OR (COALESCE(name_prefix,'') || name) ILIKE %s`；`get_object_pin_status`/`toggle_object_pin` 用 `name = %s OR name_prefix||name = %s`（精確）；`set_object_redshift`/`update_tns_redshift` 用 `name = %s OR name ILIKE %s`；`get_comments`、`get_target_image`、`get_detect_images`、`get_object_details`、`get_photometry_batch` 等以**精確 `name`** 比對（不去前綴）。
- `kinder_id = year * 1_000_000 + rank(suffix)`，`rank` 為 bijective base-26：`a=1 … z=26, aa=27`；範例 `2024ggi → 2024004923`、`2026zzzz → 2026475254`。`_tns_name_to_kinder_id` 只接受小寫（`^(\d{4})([a-z]+)$`），`sync_kinder_ids` 對大寫單字母名（`2026A`）先 `lower()` 再算 → `2026000001`；`modules/tns_gap_filler.py` 有反向的 `_kinder_id_to_name`（單字母還原為大寫）。`objects_kinder_id_idx` 為部分唯一索引。
- `obj_id` 與 `kinder_id` 在新資料（`auto_tns_download.py`）上相同；舊資料 `obj_id` 可能是 TNS 的 `objid`。

### 4.4 MJD 與日期轉換慣例

- `objects` 的五個日期欄與 `photometry`/`spectroscopy` 的 `"MJD"` 一律存 **MJD（double）**；`obs.logs.date`、`comments.comment_time`、`object_views*.{last_view,view_time}`、`cross_matches.{updated_date,run_date}`、`download_logs.download_date`、`invitations.*`、`auth.users.{last_login,join_date}` 為 `TIMESTAMPTZ`。
- SQL MJD → 字串：`to_char(TIMESTAMP '1858-11-17' + <mjd> * INTERVAL '1 day', 'YYYY-MM-DD HH24:MI:SS')`（`get_recent_tns_updates` fallback 另 cast 成 `timestamptz`；DETECT 相關只到 `'YYYY-MM-DD'`）。
- SQL 日期 → MJD（`_build_where`）：`date_from` → `discovery_date >= (DATE %s - DATE '1858-11-17')`（整數 MJD，0h UTC）；`date_to` → `<= (...) + 1`。
- Python：`_datetime_to_mjd(dt) = dt.timestamp()/86400 + 40587.0`（40587 = 1970-01-01 的 MJD）；反向 `datetime.fromtimestamp((mjd - 40587) * 86400, tz=utc)`。光譜 MJD 若 `0 < v < 1000` 視為舊制 phase（`_phase_from_stored_value`），不當作 epoch；`≤ 1` 不顯示日期。
- 回傳給 route 的時間：`TIMESTAMPTZ` 欄位多以 `.isoformat()` 轉字串（users、groups、invitations、comments、audit）；`obs.logs.date` 轉 `'YYYY-MM-DD'`；`detect_screen.run_date` 轉 `'YYYY-MM-DD HH:MM'`；`get_group_request`、`get_user_group_requests` 的 `created_at` **未**轉字串。

---

## 5. 已知問題與注意事項

1. **「flag」有三種互不相通的定義**：`_build_where(tag='flag')`（Marshal 篩選）查 `cross_matches.status = 'Flagged'`；`get_marshal_overview_stats().flag_count` 查 `objects.tag @> ARRAY['flag']`；而所有 flag 讀寫函式（`update_cross_match_flag`、`get_object_flag_status`、`update_object_flag_by_name`、`get_flagged_objects`、`save_flag_objects`）用的是 `cross_matches.flag BOOLEAN`。使用者按下 flag 後，Marshal 的 flag 篩選與計數都不會反映。
2. **`TNSObjectDB.delete_spectrum` 沒有 `obj_id` 條件**：只以 `(source, "MJD")` 刪除。只給日期上傳的光譜 MJD 會落在 00:00 UTC，同一台儀器同一晚兩個物件的光譜會有相同 `(source, MJD)`，刪其中一個會連另一個一起刪掉。
3. **`OBJECT_COMPAT_COLS` 的 `tag` 別名遮蔽了真正的 `tag TEXT[]` 欄位**（陣列以 `tags` 提供）；`inbox` 對 Follow-up/Finish 也回 1，與 `status='Inbox'` 的 `object` 計數語意不同。route 端若拿 `row['tag']` 當陣列會出錯。
4. **無呼叫者的函式**（app 端）：`close_connection_pool`、`search_desi_by_targetid`、`get_desi_statistics`、`get_lens_by_id`、`get_lens_statistics`、`save_detect_image`；`get_flagged_objects`、`save_flag_objects`、`save_cross_match_results`、`save_target_image` 只在 `modules/DETECT/function/database/` 有**同名自帶版本**（DETECT 匯入的是 `function.database`，不是 `modules.database`），因此 `transient.py` 內這四個實際上也沒人用。
5. **重複/重疊的函式**：`get_daily_match_counts` + `get_available_dates` 與 `get_detect_metadata` 內容相同；`get_photometry_batch` + `get_object_details_batch` + `get_latest_photometry_for_names` + `get_cross_match_results(date=...)` 與 `get_detect_page_data` 前三段相同；`TNSObjectDB.get_object_details` ≈ `get_object_details_batch` 單筆版；`get_tag_statistics`、`get_tns_statistics`、`get_auto_snooze_stats`、`get_filtered_stats` 都是 `get_marshal_overview_stats` 的子集；`set_object_redshift` 與 `update_tns_redshift` 只差是否重算絕對星等；`get_all_groups` = `get_groups()`（且型別註記 `list[dict]` 錯誤，實際 dict）；`create_group_request`/`delete_group_request` 是別名；`update_object_activity`、`check_data_consistency`、`clean_data_consistency` 為 no-op。`_ensure_extra_tables` 在 `modules/DETECT/function/database/__init__.py` 另有一份（多補 `cross_matches` 欄位、少補索引與 `cat.ned`）。
6. **私有名稱被外部匯入**：`routes/marshal/object_routes.py` 匯入 `_parse_spectrum_id`、`_build_spectrum_label`、`_format_spectrum_observation_label`、`_phase_from_stored_value`；`modules/auto_tns_download.py` 匯入 `_tns_name_to_kinder_id`；`get_pool_stats`/`recycle_idle_connections` 依賴 psycopg2 私有屬性 `_used`/`_pool`/`_lock`。
7. **熱路徑上執行 DDL**：`_ensure_auto_exposure_column`（每次列目標/存目標）、`_ensure_cross_matches_flag_column`（每次讀寫 cross-match）、`_ensure_tns_update_audit_table`（首頁 `get_recent_tns_updates` 每次）。`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 即使無事可做仍需先取得 ACCESS EXCLUSIVE 鎖，會排在長查詢後面並阻塞其他讀取。另外 `auth.py` 在 **import 時**就執行 DDL（`_ensure_api_key_request_col()` 模組層級呼叫），因此匯入 `modules.database.auth` 就會建池連 DB。
8. **`_ensure_extra_tables` 全有或全無**：所有語句共用一個交易與一個 `except Exception`，任一句失敗（例如權限不足）後續語句全跳過且不 commit，只留 warning；且每次啟動都執行 `UPDATE transient.objects SET tag='{}' WHERE tag IS NULL`（全表掃描）。
9. **ILIKE 未跳脫萬用字元的 UPDATE**：`update_object_status`、`set_object_redshift`、`update_tns_redshift`、`update_object_abs_mag` 以 `name ILIKE %s` 比對；若 `object_name` 含 `%` 或 `_`（例如 `'%'`），一次可改到多個物件。搜尋用的 `_build_where` 同樣不跳脫，但只影響查詢結果。值一律參數化，動態欄位名都來自白名單（`update_user`、`update_invitation`、`update_observation_target` 的 mapping、`search_tns_objects` 的 `sort_map`/direction），本層沒有直接把使用者輸入拼進 SQL 的情況；route 端自行以 `OBJECT_COMPAT_COLS` 組 f-string 查詢（`object_routes.py`、`web_api_routes.py`、`astronomy_tools_routes.py`）不在本層檢查範圍。
10. **連線層細節**：`get_tns_db_connection` 不像 `get_db_connection` 會檢查 `conn.closed`，DB 重啟後第一次取到的可能是死連線；`_PooledConn` 不支援 `with`；重複 `close()` 會拋 `PoolError`；`get_db_connection` 不自動 commit，忘記 commit 的寫入會在歸還時被 rollback。`cone_search_desi`/`cone_search_lens` 每次呼叫開兩條連線（先查 `pg_extension`）；`cone_search_desi` 開頭的 `params`/`clauses` 為未使用的死碼。`routes/auth/database_status_routes.py` 自行 `psycopg2.connect` 繞過連線池。
11. **API key 為明文**：`generate_api_key_for_user` 直接存 48 字元隨機字串，`get_user_by_api_key` 明文等值比對；`auth.users.md` 文件寫的是「save hash」。
12. **留言以反正規化 `name` 為 key**：`add_comment` 的 `name` 欄存傳入原字串（可能含前綴），`get_comments` 用 `c.name = %s`；`object_routes.py` 兩處用同一個 `object_name` 變數所以目前一致，但若不同入口傳入 `AT2026abc` 與 `2026abc`，留言會被拆成兩組。
13. **影像 upsert 不一致**：`save_target_image` 只看 `obj_id`（`LIMIT 1`，忽略 `source`），可能覆寫掉 `detect_combined` 那一列；`get_detect_images` docstring 與 SQL 行為不符（實際 DESI 優先、最多回 1 筆）。
14. **錯誤處理契約不一致**：`get_user`、`get_users`、`user_exists`、`get_groups`、`group_exists`、`user_in_group`、`get_group_requests`、`get_invitations`、`get_invitation`、`get_object_permissions`、`TNSObjectDB` 大部分方法、Marshal 查詢函式等**不攔截例外**（直接拋出）；其餘寫入函式攔截後回 `False`/`None`/`[]`/`0` 並 `logger.error`。`filter_by_source_permissions` 出錯時回傳**未過濾**的原清單（fail-open）。
15. **觀測紀錄的唯一鍵與程式不一致**：`_ensure_extra_tables` 建了 `UNIQUE (target_id, date)`，但 `upsert_observation_log` 以 `(name, date, telescope)` 判斷既有列；`delete_observation_log(name, date)` 解析 `target_id` 時若未給 `telescope`，同名同時排在 LOT/SLT 的目標會刪到「最近 active」那一台的紀錄。
16. **文件與 DDL / 程式的落差**：`obs.logs.md` 的 `*_count`（秒）/`*_time`（分）定義與 DDL/程式相反；`obs.targets.md` 的 `obs_targets_name_uniq` 不存在（實為 `UNIQUE (name, telescope)`）；`Schema - Catalog.md` 缺 `cat.ned`；`Schema - Transient.md` 缺 `object_source_permissions`、`tns_update_audit`、`detect_screen(_history)`；`catalog.py` docstring 只列 desi/lens；`app/test_db.py` 查的 `lens_hsu`/`lens_karp`/`lens_catalogue` 不在 schema。`auth.images`、`transient.custom_targets`、`objects.discovery_mag_err` 沒有任何程式讀寫；`transient.object_views_detail` 沒有任何清理，會無限成長。
17. **兩種匯入路徑並存**：多數程式用 `from modules.database ...`；`modules/download_phot.py` 只用 `from database.transient import TNSObjectDB`，`auto_tns_download.py`/`TNS_object_fetch.py`/`tns_gap_filler.py` 等以 `try/except ImportError` 同時支援兩者，前提是 `app/modules` 也在 `sys.path`。`update_object_abs_mag` 另需 DETECT 的 `function.module.screening` 可匯入。
18. 其他小地方：`save_user` 在 `ON CONFLICT` 時不更新 `roles`，`is_admin` 參數只對首次建立有效；`revoke_object_permission` 移除群組後不會把 `permission` 改回；`get_observation_targets` 的 `ORDER BY priority` 是字母序（Filler < High < Normal < Urgent）；`log_download_attempt` 的 `hour_utc` 參數與 `grant_object_permission` 的 `granted_by`、`add_comment` 的 `user_name`/`user_picture` 皆未使用；`sync_host_redshifts` 把 `DOUBLE PRECISION` 的 `c.redshift` 轉 `text` 再正規式檢查後轉 `numeric`，可運作但繞路。
