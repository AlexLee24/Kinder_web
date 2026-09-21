# 領域運算模組：觀測規劃、觸發腳本、光度/光譜處理與繪圖、座標/日期轉換、消光與絕對星等、以及已無人使用的舊模組

> **注意**：本章記錄的是重構前（commit `c7f91a4`，2026-09-21）的狀態，檔案路徑為舊位置（`app/routes/…`、`app/modules/…`）。新位置請對照 `docs/ARCHITECTURE.md` §6「新舊路徑對照」；功能與行為在重構後完全相同。

本章涵蓋 `app/modules/` 下與天文領域運算直接相關的純運算 / 繪圖模組。所有描述均逐一比對原始碼（2026-09-21 工作樹，`master` 分支，最新 commit `c7f91a4`）。「被誰 import」一欄以 `grep -rn` 在 `app/routes`、`app/modules`、`app/main.py` 確認，排除 `app/modules/CASTOR`、`app/modules/DETECT`、`__pycache__`；另外也對整個 repo（含根目錄的 `test_*.py`）做過一次全域 grep，結果一致。

匯入路徑背景（`app/main.py` 第 15–28 行）：`sys.path` 依序加入 `app/modules`、`app/modules/DETECT_pipe/modules`、`app/modules/CASTOR/src`、`app/modules/DETECT`，並以 `os.environ.setdefault("DETECT_DATA_DIR", app/modules/DETECT/data)` 設定 DETECT 資料目錄。因此同一支檔案可能同時以 `modules.obsplan`（套件路徑）與 `obsplan`（頂層路徑）兩個名字被載入，下文會特別標注。

## 總覽表

行數為實體行數（`cat -n` 最後一行的編號；`obsplan.py`、`obsplan_old.py`、`date_converter.py`、`coordinate_converter.py`、`astronomy_calculator.py`、`config.py`、`object_data.py`、`TNS_object_fetch.py` 檔尾無換行，`wc -l` 會少算 1 行）。

| 模組 | 用途一句話 | 是否仍被使用（被誰 import） | 行數 |
|---|---|---|---|
| `obsplan.py` | 以 `ephem` + Matplotlib 產生整夜目標高度/可見度軌跡圖，並提供太陽/月亮/曙暮光/中天/角距離計算 | **使用中**：`app/routes/astronomy_tools/astronomy_tools_routes.py:36`（`from modules import obsplan as obs`）、`app/routes/private_area/private_area_routes.py:734`（函式內 `from modules import obsplan as obs`）、`app/modules/GCN_alert.py:27`（`import modules.obsplan as obs`；但 `main.py:258` 已註解掉 `start_gcn_listener`，GCN 目前未啟動）、`app/modules/trigger_script.py:7`（`import obsplan as obs`，頂層名） | 945 |
| `obsplan_old.py` | `obsplan.py` 的前一版（2026-03-03） | **無人使用**（全 repo 無 import） | 905 |
| `observation_script.py` | Observation Planner 頁面的 LOT/SLT ACP 腳本產生器、追蹤中目標 JSON、曝光時間表 | **使用中**：`astronomy_tools_routes.py:37`（`get_followup_targets_json`, `process_observation_request`）、`private_area_routes.py:1916`（函式內 `from modules.observation_script import exposure_time`） | 269 |
| `trigger_script.py` | Daily Trigger 頁面的 ACP 觸發腳本產生器（含座標正規化、多目標合併） | **使用中**：`astronomy_tools_routes.py:844`（函式內 `from modules import trigger_script` → `generate_full_script`）、`private_area_routes.py:782`（函式內 `from modules.trigger_script import exposure_time as _auto_exposure_time`） | 253 |
| `Trigger_LOT_SLT.py` | `trigger_script.py` 的祖先版本（2026-01-05） | **無人使用**（全 repo 無 import） | 220 |
| `trigger_send.py` | Slack 發送與每日觸發狀態檔（他章詳述） | **使用中**：`private_area_routes.py:648, 695, 714, 735, 781` | 165 |
| `data_processing.py` | `DataVisualization`：光度曲線（Plotly JSON）與光譜（Plotly HTML div）圖產生 | **使用中**：`app/routes/marshal/object_routes.py:29`、`app/routes/detect/detect_routes.py:16`、`app/routes/web_api/web_api_routes.py:31`（**僅 import，檔內無任何使用**） | 767 |
| `filter_colors.py` | 讀取 `app/data/filter_colors.json` 的濾鏡顏色查表 | **使用中**：`data_processing.py:25/27`（函式內）、`astronomy_tools_routes.py:91`（函式內 `all_colors`） | 37 |
| `ext_M_calculator.py` | 對 DETECT `function.module.calculator` 的 re-export shim（cosmology、消光、絕對星等） | **使用中**：`data_processing.py:12/15`、`object_routes.py:30`、`detect_routes.py:17`、`astronomy_tools_routes.py:112`（函式內） | 17 |
| `astronomy_calculator.py` | 紅移→光度距離、視星等→絕對星等（獨立 astropy 實作，可自訂宇宙學參數） | **使用中**：`astronomy_tools_routes.py:29`、`object_routes.py:229, 348`（函式內） | 107 |
| `coordinate_converter.py` | RA/Dec 的 HMS/DMS ↔ 十進位度轉換 | **使用中**：`astronomy_tools_routes.py:32, 2256`、`observation_script.py:245`（函式內） | 88 |
| `date_converter.py` | MJD/JD ↔ 一般日期轉換 | **使用中**：`astronomy_tools_routes.py:31` | 65 |
| `request_validation.py` | 查詢字串數值參數驗證（`get_int_arg`/`get_float_arg`）與 `ParamOutOfRangeError` | **使用中**：`app/main.py:48`、`object_routes.py:21`、`web_api_routes.py:21`、`private_area_routes.py:19`、`astronomy_tools_routes.py:30` | 45 |
| `spectral_lines.py` | NIST 譜線快取（他章詳述） | **使用中**：`app/main.py:266`、`object_routes.py:1122, 1141` | 274 |
| `object_data.py` | 舊 SQLite 光度/光譜/留言存取層 | **無人使用**（全 repo 無 import；`app/data/object_data.db` 不存在） | 258 |
| `detect_image.py` | 舊版 DETECT 交叉比對標記圖（DESI Legacy Survey cutout） | **無人使用**（唯一出現處是自身 docstring） | 231 |
| `TNS_object_fetch.py` | 舊版 TNS 每小時/每日下載與匯入常駐執行緒 | **無人使用**（`main.py:259/314` 改用 `auto_tns_download.start_auto_tns_downloader`） | 614 |
| `database_deprecated.py` | 舊 SQLite（`app/data/kinder.db`）使用者/群組/邀請/權限/設定層 | **無人使用**（全 repo 無 import；`kinder.db` 不存在） | 514 |
| `config.py` | 讀取 `kinder.env` 的 `Config` 物件（他章詳述） | **使用中**：`main.py:46`、`trigger_send.py:11` 等 | 37 |

---

## obsplan `app/modules/obsplan.py`

### 用途
移植自 Phil Cigan 的 `obsplanning`（模組 docstring 註明來源 <https://github.com/pjcigan/obsplanning>），以 `ephem` 做天體位置計算、`matplotlib`（第 19 行 `matplotlib.use('Agg')`，位於 `import matplotlib.pyplot` 之後）繪製「整夜目標高度 vs. 時間」圖。本模組**不含任何望遠鏡站點常數**；Lulin 的座標是由各呼叫端硬編碼傳入（見「被誰呼叫」）。

### 公開函式與類別

| 名稱 | 簽名 | 說明 / 回傳 |
|---|---|---|
| `wrap_pm180` | `(val)` | 角度包到 [-180, 180)，回傳 float |
| `Observer_with_timezone` | `class (ephem.Observer)` | 多一個 `timezone` 屬性（預設 `None`） |
| `autocalculate_observer_timezone` | `(observer)` | 以 `timezonefinder.TimezoneFinder().timezone_at(lng, lat)` 由經緯度求時區字串；每次呼叫都新建 `TimezoneFinder()` |
| `create_ephem_observer` | `(namestring, longitude, latitude, elevation, decimal_format='deg', timezone=None)` | 回傳 `Observer_with_timezone`。**數值**經緯度在 `decimal_format` 含 `'deg'` 時視為度→弧度；**字串**（如 `'120:52:21.5'`）原樣交給 `ephem` 解析。`timezone='auto'/'calculate'` 時自動推算，否則直接存入 |
| `create_ephem_target` | `(namestring, RA, DEC, decimal_format='deg')` | 回傳已 `compute()` 的 `ephem.FixedBody`。內部 `_to_radians_if_bare_decimal`：含 `:` 的字串視為六十進位原樣傳入；**不含 `:` 的數值字串**與數值一律當十進位度→弧度（這是相對舊版的修正，避免 `"159.6998"` 被 `ephem.hours` 當成 159.7 小時） |
| `alt2airmass` | `(altitude)` | `1/cos(90°-alt)` |
| `create_obstime_array` | `(timestart, timeend, timezone_string='UTC', output_as_utc=False, n_steps=100)` | 回傳 `n_steps` 個 tz-aware `datetime` list；字串格式 `'%Y/%m/%d %H:%M:%S'` |
| `compute_sun_tracks` / `compute_moon_tracks` | `(observer, obsstart, obsend, nsteps=1000)` | 回傳 `(np.array 高度度數, None)`；**會就地改動 `observer.date`** |
| `compute_moonphase` | `(obstime, return_fmt='percent')` | 月相百分比或 0–1 |
| `calculate_moon_times` | `(observer, startdate, outtype='dt')` | `[moonrise, moonset]`（`datetime` 或 `ephem.Date`）；**就地改動 `observer.date`** |
| `convert_ephem_datetime` | `(ephem_date_in)` | tz-aware UTC `datetime` |
| `fill_twilights` | `(axin, obsframe, startdate, offsetdatetime=0., timetype='offset', bgcolor='k')` | 以 alpha 0.1/0.3/0.5/0.7 疊四層 `axvspan`（日落、民用、航海、天文曙暮光）並標註時間文字 |
| `fill_twilights_light` | `(axin, obsframe, startdate, plottimerange, offsetdatetime=0., bgcolor='#95D0FC', timetype='offset')` | 淺色版；僅 `light_fill=True` 時用（目前無呼叫端傳 `True`） |
| `compute_target_altaz` | `(target, observer, t1, t2, nsteps=1000)` | `(alt_arr, az_arr)` 度；使用 `observer.copy()`/`target.copy()`，不污染輸入 |
| `calculate_transit_time_single` | `(target, observer, approximate_time, mode='nearest', return_fmt='str')` | 中天時刻：`'str'`→`'%Y/%m/%d %H:%M:%S'`、`'dt'`→`datetime`、其他→`ephem.Date`；目標永不升起（`neverup`）或早於 2000/01/01 回傳 `""` |
| `moonsep_single` / `sunsep_single` | `(target, observer, obstime)` | 與月/日角距離（度） |
| `calculate_targets_mean_transit_time` | `(target_list, observer, approximate_time, weights=None)` | （加權）平均中天時刻字串 |
| `dt_naive_to_dt_aware` | `(datetime_naive, local_timezone)` | `pytz.localize` |
| `tz_from_observer` | `(observer)` | `observer.timezone`，若 `None` 則自動推算 |
| `calculate_dtnaive_utcoffset` | `(datetime_naive, local_timezone)` | UTC 偏移小時數 |
| `compute_sidereal_time` | `(observer, t1, as_type='datetime')` | 地方恆星時（`datetime` 或 `ephem.Angle`） |
| `LST_from_local` | `(dt_local, observer_lon_deg)` | `[hour, minute]`；**內部呼叫 `compute_sidereal_time(None, ...)`，會在 `None.copy()` 觸發 `AttributeError`**。只有 `toptime='LMST'` 時才會走到，全站無人使用該模式（grep `LMST` 無結果），屬潛伏死路徑 |
| `calculate_twilight_times` | `(obsframe, startdate, verbose=False)` | 回傳四個 `np.array([previous_setting, next_rising])`（地平線 0°/-6°/-12°/-18°，`use_center=True`），單位 `ephem.Date` 浮點 |
| `plot_observing_tracks` | `(target_list, observer, obsstart, obsend, weights=None, mode='nearest', plotmeantransit=False, toptime='local', timezone='auto', n_steps=1000, simpletracks=False, azcmap='rainbow', light_fill=False, bgcolor='k', xaxisformatter=mdates.DateFormatter('%H:%M'), figsize=(14,8), dpi=200, savepath='', showplot=False)` | 回傳 `None`，副作用是 `plt.savefig(savepath, bbox_inches='tight', dpi=dpi)`。流程：`obsend<obsstart` 拋例外 → 目標**依 RA 升冪排序**並編號 1..N → 太陽/月亮軌跡（紅/灰虛線）→ `fill_twilights` → 每目標畫線（`simpletracks=True` 為 `plot`，否則 `scatter` 依方位角上色並加 colorbar）→ **每整點在曲線上標注目標編號**（高度 >0 時）→ 圖例（>5 個目標放右側外）→ 右 y 軸 airmass（10/30/50/70/90°）→ 上 x 軸本地時間（`toptime` 含 `'loc'`）或 LMST → 左上文字：月出/月沒/月相 → 存檔 → `plt.clf(); plt.close('all')` |
| `plot_night_observing_tracks` | 同上但無 `light_fill` 參數 | 包裝：固定 `light_fill=False`。**所有呼叫端都用這個** |
| `get_timezone_name` | `(offset)` | UTC 整數偏移 -12..12 → 時區名稱（`8: 'Asia/Taipei'`, `0: 'UTC'`, `9: 'Asia/Tokyo'`, `-8: 'America/Los_Angeles'` …），查無回傳 `None`（`timezone_dict.get(offset)`） |

### 內部重要常數
- 無望遠鏡常數；`get_timezone_name` 的 25 筆偏移→時區對照表是唯一查表。
- `plot_observing_tracks` 的 `timezone` 參數**從未被讀取**（第 864 行直接以 `tz_from_observer(observer)` 覆寫），呼叫端傳的 `timezone='calculate'` 無效；實際時區來自 observer 的 `timezone` 屬性，而呼叫端建 observer 時都沒給，因此每張圖都會跑一次 `TimezoneFinder`。

### 讀寫的檔案
- 不讀任何檔案。
- 只寫 `savepath`（由呼叫端決定）：
  - `POST /generate_plot`（`astronomy_tools_routes.py:422`）→ `app/routes/planners/ov_plot/observing_tracks_<uuid4 hex>.jpg`（`_PLANNERS_OV_PLOT_DIR`，`__file__` 相對），由 `app/routes/planners/planners_routes.py:13` 的 `/ov_plot/<path:filename>` 提供；寫入前 `enforce_max_files(plot_folder, max_files=10)` 依 mtime 刪最舊，**全站共用 10 檔上限**。
  - `GET /api/visibility/image`（`astronomy_tools_routes.py:2122`）→ `tempfile.NamedTemporaryFile(suffix='.jpg')`，讀回 bytes 後 `os.unlink`。
  - Daily Trigger 發送（`private_area_routes.py:_render_trigger_visibility_image`）→ 暫存 `.jpg`，Slack 發完即刪。
  - `GCN_alert.py:38` `PLOT_PATH = app/data/ep_observing_track.jpg`（目前 GCN listener 未啟動）。
  - `trigger_script.generate_img` / `Trigger_LOT_SLT.generate_img` → `os.getcwd()/obs_img/Trigger_observing_tracks.jpg`（**無呼叫端**）。

### 外部服務
無（`ephem`、`timezonefinder` 皆離線）。

### 被誰呼叫（含用到的函式）
- `astronomy_tools_routes.py`：`/generate_plot`（`get_timezone_name`, `create_ephem_target`, `create_ephem_observer`, `dt_naive_to_dt_aware`, `plot_night_observing_tracks(simpletracks=True, toptime='local', n_steps=1000)`）；`/api/visibility_data`（另加 `compute_moonphase`, `calculate_twilight_times`, `calculate_moon_times`, `calculate_transit_time_single`, `moonsep_single`，回傳 JSON 不出圖）；`/api/visibility/image`（`n_steps=500`，預設站點 `lon='120:52:21.5'`, `lat='23:28:10.0'`, `alt=2800`, `tz=8`）。
- `private_area_routes.py:_render_trigger_visibility_image`：`create_ephem_observer('Lulin Observatory', '120:52:21.5', '23:28:10.0', 2800)`，觀測窗 `_trigger_day_key()` 當日 17:00 → 次日 09:00（`Asia/Taipei`），`n_steps=500`。
- `GCN_alert.py:204-213`：同樣的 Lulin 常數與 17:00→09:00 窗；另呼叫 `calculate_twilight_times(lulin, '2024/01/01 23:59:00')` 但**丟棄結果**。
- `trigger_script.py` / `Trigger_LOT_SLT.py`：`generate_img`（無呼叫端）。

### 注意事項
- 使用 pyplot 全域狀態（`plt.figure(1)` … `plt.close('all')`），**非執行緒安全**；Flask/gunicorn 若多執行緒同時打 `/generate_plot`、`/api/visibility/image`、Daily Trigger 發送，圖形可能互相污染或被關閉。
- 同一檔案被以 `modules.obsplan`（routes、GCN_alert）與 `obsplan`（`trigger_script`）兩個名稱載入，`sys.modules` 內會有兩份獨立模組物件（兩份 `Observer_with_timezone` 類別）。目前沒有跨模組 `isinstance` 比對，故無實際影響，但 import 成本加倍。
- 與 `obsplan_old.py` 的差異（`diff` 共 62 行）：加入 `logging`（取代 `print`）；`create_ephem_target` 對無冒號數值字串的修正；目標依 RA 排序；圖例加編號並每小時標注編號；其餘函式簽名完全相同。

---

## obsplan_old `app/modules/obsplan_old.py`

- **用途**：`obsplan.py` 的 2026-03-03 版（git 單一 commit `ad883b6 "add tools"`），28 個函式/類別名稱與新版一一對應。
- **差異**（相對新版）：`create_ephem_target` 只對「非字串」做度→弧度轉換，字串一律原樣交給 `ephem`（十進位度的字串 RA 會被誤讀為小時）；`plot_observing_tracks` 不排序、不編號、無每小時標注；用 `print` 而非 `logger`。
- **使用情況**：全 repo 無任何 import（含根目錄測試腳本、CASTOR、DETECT）。
- **可安全刪除的理由**：功能已被 `obsplan.py` 完整取代且修正了座標解析錯誤；沒有呼叫端；git 歷史仍保留內容。

---

## observation_script `app/modules/observation_script.py`

### 用途
Observation Planner 頁面（`GET /observation_planner`，前端 `app/routes/planners/static/js/observation_planner.js`）的後端：把「追蹤中」目標轉成 ACP 腳本區塊。頂層 `from modules.database import get_tns_db_connection`。

### 公開函式

**`exposure_time(mag)`** → `dict[filter, 'NNNsec*K']` | `"Too faint to observe"` | `"Invalid magnitude"`
- `mag = int(float(mag))`（**截斷**：18.9 → 18）；`>22` → `"Too faint to observe"`；`<12` → 回傳 12 等那列；否則查表。非數值：字串 `">22"` → too faint，其餘 → `"Invalid magnitude"`。
- 曝光時間表（三個腳本模組完全相同）：

| mag | up | gp | rp | ip | zp |
|---|---|---|---|---|---|
| ≤12 | 60s×1 | 30s×1 | 30s×1 | 30s×1 | 30s×1 |
| 13–14 | 60s×2 | 60s×1 | 60s×1 | 60s×1 | 60s×1 |
| 15–16 | 150s×2 | 150s×1 | 150s×1 | 150s×1 | 150s×1 |
| 17–19 | 300s×2 | 300s×1 | 300s×1 | 300s×1 | 300s×1 |
| 20 | – | – | 300s×6 | – | – |
| 21 | – | – | 300s×12 | – | – |
| 22 | – | – | 300s×36 | – | – |
| >22 | Too faint | | | | |

**`check_filter(filter)`**（SLT）：`up/gp/rp/ip/zp` → `up_Astrodon_2018 / gp_Astrodon_2018 / rp_Astrodon_2018 / ip_Astrodon_2018 / zp_Astrodon_2018`；其他名稱**原樣回傳**（`return filter`）。

**`check_filter_LOT(filter)`**：`up` → `up_Astrodon_2017`；`gp/rp/ip/zp` → `*_Astrodon_2019`；其他原樣回傳。

**`generate_single_script(name, ra, dec, mag, priority, is_lot="False", Repeat=0, auto_exp=True, filter_input=None, exp_time=None, count=None, info=None)`** → `str`
- `ra`/`dec` 若是 `coordinate_converter` 回傳的 dict，取 `ra_hms` / `dec_dms`。
- `is_lot == "True"`（字串比對）→ `LOT`，否則 `SLT`。
- `auto_exp=True`：查 `exposure_time`；錯誤以**註解列**回傳（`"; Error: Invalid magnitude entered for {name}."`、`"; Error: {name} is too faint to observe."`），不拋例外。
- `auto_exp=False`：`filter_input`/`exp_time`/`count` 以逗號切分（不截齊長度），濾鏡經 `check_filter*` 換名。
- 輸出格式：
  ```
  ;Info: <info>                      （有 info 才輸出）
  ;===SLT===                         priority 為 "None"/空
  ;===LOT_Urgent_priority. Immediately Observe When Possible ===   priority == "Urgent"
  ;===LOT_<priority>_priority===     其他
  (空行)
  #REPEAT n                          Repeat>0 時，位於 #BINNING 之前
  #BINNING 1, 1, ...
  #FILTER rp_Astrodon_2018, ...
  #INTERVAL 300, ...
  #COUNT 1, ...
  ;# mag: <mag> mag
  <name>\t<ra>\t<dec>
  #WAITFOR 1
  ```

**`get_followup_targets_json()`** → dict
- SQL：`SELECT o.name, o.ra, o.dec AS declination, o.discovery_mag AS discoverymag FROM transient.objects o WHERE o.status = 'Follow-up'`。
- 回傳結構：`{"settings": {"IS_LOT": "True", "send_to_control_room": "True"}, "targets": [{"object name", "RA"(DB 原值，十進位度), "Dec", "Mag": str(discovery_mag) 或 "unknown", "Priority": "Urgent", "Exp_By_Mag": "True", "Filter": "rp", "Exp_Time": "300", "Num_of_Frame": "3", "Repeat": 0}, ...]}`。`Priority`、`Filter`、`Exp_Time`、`Num_of_Frame` 為硬編碼預設值；`Mag` 用的是**發現星等**而非最新星等。

**`process_observation_request(data)`** → `str`
- `data = {"settings": {"IS_LOT": "True"/"False", ...}, "targets": [{"object name", "RA", "Dec", "Mag", "Priority", "Exp_By_Mag": "True"/"False", "Filter", "Exp_Time", "Num_of_Frame", "Repeat", "Info"}]}`（前端 `observation_planner.js:229-245` 即以此格式送出，`Repeat` 為 `parseInt` 數值）。
- RA/Dec 若為數值或不含 `:` 的字串 → 以 `coordinate_converter.convert_ra_decimal_to_hms` / `convert_dec_decimal_to_dms` 轉六十進位（函式內 import）；轉換失敗 `except: pass` 保留原值。
- 逐目標呼叫 `generate_single_script`，串接後回傳整段文字。

### 讀寫的檔案 / 外部服務
無檔案 I/O；只讀 PostgreSQL（`transient.objects`）。

### 被誰呼叫
- `GET /astronomy_tools/get_followup_targets` → `get_followup_targets_json`；`POST /astronomy_tools/generate_script` → `process_observation_request`（`astronomy_tools_routes.py:813-828`）。
- `GET /api/auto_exposure?mag=&telescope=`（`private_area_routes.py:1904`）→ `exposure_time`，把 `'NNNsec*K'` 拆成 `{'filter','exp','count'}` 給 Daily Trigger 前端（`daily_trigger.js:438`）。

### 注意事項
- 兩處 bare `except:`。
- `is_lot` 以字串 `"True"` 比對，傳布林 `True` 會被當 SLT。

---

## trigger_script `app/modules/trigger_script.py`

### 用途
Daily Trigger 頁面（`private_area`）的 ACP 腳本產生器；由 `POST /astronomy_tools/generate_trigger_script` 呼叫 `generate_full_script`。頂層 `import obsplan as obs`（**頂層名，依賴 `main.py:19` 的 `sys.path.append(app/modules)`**；若在其他進程直接 `import modules.trigger_script` 而沒設 sys.path 會 `ModuleNotFoundError`）；`matplotlib.use('Agg')`。

### 公開函式
- **`read_json(file)`** → dict（無呼叫端）。
- **`exposure_time(mag)`**：查表與 `observation_script` 完全相同，**唯一差異**是 `>22` 回傳 `"Too faint to observe, please use LOT for follow-up observation"`。
- **`check_filter` / `check_filter_LOT`**：對照表同上，但**未知濾鏡回傳 `None`**（沒有 fallthrough `return`）。
- **`generate_script(name, ra, dec, mag, priority, priority_message, is_lot="False", Repeat=0, auto_exp=True, filter_input=None, exp_time=None, count=None)`** → `str`
  - 先以 `obs.create_ephem_target(name, ra, dec)` 正規化座標，取 `str(_ra)`（`HH:MM:SS.ss`）與 `str(_dec)`（`±DD:MM:SS.s`）；失敗回傳註解列 `";= {name}: could not parse coordinates (...) =\n\n"`。
  - 手動模式：三個逗號清單**截齊到最短長度**；例外時退回單一濾鏡。
  - 輸出格式（與另兩支不同）：
    ```
    ;= <name> SLT_<priority>_priority <priority_message> =     （priority=="None" → Normal）
    (空行)
    #BINNING ...
    #FILTER ...
    #INTERVAL ...
    #COUNT ...
    ;= mag: <mag> mag =
    <name>\t<ra>\t<dec>
    #REPEAT n            ← Repeat>0 時，**放在目標列之後、#WAITFOR 之前**
    #WAITFOR 1
    ```
- **`TARGET_SEPARATOR = ";====================\n\n"`**
- **`generate_full_script(targets, telescope)`** → `str`：`telescope` 為 `"LOT"`/`"SLT"`；每個 target dict 鍵：`name, ra, dec, mag, priority, priority_message, repeat, auto_exp, filter_input, exp_time, count`。以 `TARGET_SEPARATOR` 連接並 `rstrip('\n')`。前端 `daily_trigger.js:_buildScriptPayloadTarget`（第 2762-2781 行）送出：`mag` 字串（`t.mag || ''`）、`priority`（預設 `'Normal'`）、`priority_message = t.plan`、`repeat = t.repeat_count || 0`（`parseInt` 數值）、`auto_exp` 布林、僅手動曝光時附 `filter_input/exp_time/count`（逗號串接字串）、另有 `program`（本模組忽略）。
- **`generate_img(date, target_list, plot_path=None)`** → `plot_path`：無呼叫端。`plot_path=None` 時寫到 `os.getcwd()/obs_img/Trigger_observing_tracks.jpg`（**唯一依賴 `os.getcwd()` 的地方**）；Lulin 常數硬編碼；同樣呼叫並丟棄 `calculate_twilight_times(lulin_obs, '2024/01/01 23:59:00')`。

### 與 `observation_script.py` 的重複程度（具體比較）

| 函式 | `observation_script.py` | `trigger_script.py` | `Trigger_LOT_SLT.py` |
|---|---|---|---|
| 曝光時間表（`exposure_time` 內的 dict） | 相同 | 相同 | 相同 |
| `exposure_time` 行為 | `>22` → `"Too faint to observe"`；非數值 → `"Invalid magnitude"` | `>22` → `"Too faint to observe, please use LOT for follow-up observation"` | `>22` → `"Too faint to observe"`；非數值且非 `">22"` → **回傳 `None`** |
| `check_filter` / `check_filter_LOT` 對照表 | 相同 | 相同 | 相同 |
| 未知濾鏡 | 原樣回傳 | `None` | `None` |
| 腳本產生 | `generate_single_script(... info=)`，`;===SLT===` 風格標頭，`Urgent` 特殊標頭，`#REPEAT` 在 `#BINNING` 前 | `generate_script(... priority_message)`，`;= name SLT_x_priority msg =` 標頭，座標正規化，`#REPEAT` 在目標列後 | `generate_script`，`;===SLT===` 風格，`#REPEAT` 在 `#BINNING` 前，錯誤回傳純字串（非註解） |
| 多目標合併 | `process_observation_request`（planner JSON 格式） | `generate_full_script` + `TARGET_SEPARATOR` | 無 |
| DB 查詢 | `get_followup_targets_json` | 無 | 無 |
| `read_json` / `generate_img` | 無 | 有 | 有（`generate_img` 與 `trigger_script` 逐字相同，僅空白差異） |

逐行 diff 佐證：`observation_script.py` 第 10–65 行（`exposure_time`+兩個 `check_filter`）對 `trigger_script.py` 第 24–78 行，只有 2 行訊息字串與 2 行 `return filter` 不同；`Trigger_LOT_SLT.py` 對 `trigger_script.py` 的 `diff` 共 139 行變動，全部集中在 `exposure_time` 訊息、`generate_script` 重寫與新增的 `generate_full_script`。

### 讀寫的檔案 / 外部服務
`generate_img` 才會寫圖（無呼叫端）；無外部服務。

### 被誰呼叫
- `POST /astronomy_tools/generate_trigger_script`（`astronomy_tools_routes.py:830-851`）→ `generate_full_script(targets, telescope)`。
- `private_area_routes.py:_log_triggered_targets`（發送後寫 Observation Log）→ `exposure_time`，以 `isinstance(exp_map, dict)` 判斷無效星等。

### 注意事項（含實際缺陷）
- **`exposure_time` 訊息與 `generate_script` 的比對不一致**：`generate_script` 第 102 行比對的是 `"Too faint to observe"`，但 `exposure_time` 回傳的是較長的字串，永遠不相等，於是落入 `else` 對字串呼叫 `.items()` → `AttributeError: 'str' object has no attribute 'items'`。結果：任一自動曝光目標 `mag > 22`（或 `mag == ">22"`）時，整個 `/astronomy_tools/generate_trigger_script` 回 500（路由以 `except Exception` 包住）。同樣邏輯在 `observation_script.py` 因訊息一致而正常。
- `Repeat > 0` 需要數值；前端送 `parseInt` 結果所以安全，但其他 API 呼叫者若送 `"2"` 會 `TypeError`。
- `#REPEAT` 放在目標列之後，與另兩支（放 `#BINNING` 之前）不同；請與 ACP 的 `#REPEAT` 語意確認哪個才正確。
- 未知濾鏡回傳 `None` 會產生 `#FILTER None`。

---

## Trigger_LOT_SLT `app/modules/Trigger_LOT_SLT.py`

- **用途**：`trigger_script.py` 的祖先版本（git 單一 commit `70a26c4 2026-01-05 "rebuild"`），與 `trigger_script.py` 同樣 `import obsplan as obs`。
- **與前兩者的關係**：`exposure_time`、`check_filter`、`check_filter_LOT`、`read_json`、`generate_img` 與 `trigger_script.py` 幾乎逐字相同；`generate_script` 是 `observation_script.generate_single_script` 與 `trigger_script.generate_script` 的共同雛形（四段 if/else 各自展開整段 f-string）。它既沒有 `observation_script` 的 `info`/`Urgent` 處理與 DB 查詢，也沒有 `trigger_script` 的座標正規化、`priority_message`、`generate_full_script`。
- **特有缺陷**：`exposure_time` 對非數值、非 `">22"` 的輸入回傳 `None`，`generate_script` 隨即 `None.items()` 崩潰；錯誤訊息（`"Invalid magnitude entered."`）不是 `;` 註解列，若直接貼進 ACP 會被當成目標列。
- **使用情況**：全 repo 無 import。
- **可安全刪除的理由**：所有功能都存在於 `trigger_script.py`（觸發）與 `observation_script.py`（規劃）中且更完整；`generate_img` 亦已由 `private_area_routes._render_trigger_visibility_image` 取代。

---

## trigger_send `app/modules/trigger_send.py`

一句話交叉引用：負責把 Daily Trigger 的問候語、ACP 腳本（`.txt`）與可見度圖（`.jpg`）以三則獨立訊息貼到 Slack（`send_to_slack`），並在 `app/data/trigger_send_status.json` 記錄以 `Asia/Taipei` 08:00 為分界的每日發送狀態（`_trigger_day_key`、`get_send_status`、`mark_sent`）；`_trigger_day_key` 亦被 `private_area_routes` 借用來決定觸發圖的觀測日期。詳見「Daily Trigger / Slack」章。

---

## data_processing `app/modules/data_processing.py`

### 用途
`DataVisualization` 類別（全為 `@staticmethod`）：把資料庫取出的光度/光譜列表轉成 Plotly 圖。**本模組只用 Plotly（`plotly.graph_objects` + `plotly.offline`），不使用 Matplotlib。** 檔尾 `Data_Process = DataVisualization` 為向後相容別名（全 repo 無人使用）。頂層以 `try: from . import ext_M_calculator / except: from modules import ext_M_calculator / except: None` 取得消光與距離模組；若載入失敗會退化為 H0=70 的線性 Hubble 距離。

### 公開方法

**`get_filter_color(filter_name, alpha=1)`** → `'rgba(r,g,b,a)'`：委派給 `filter_colors.get_rgba`（函式內 import）。

**`_apply_unified_plot_style(layout, legend_right=True)`** → `layout`：統一深色面板風格——`paper_bgcolor`/`plot_bgcolor` 透明、字色 `#ccc`、hoverlabel 深底、圖例半透明深底（`legend_right` 且未設定位置時放右上）、四個軸線/格線顏色。

**`create_photometry_plot_from_db(photometry_data, redshift=None, ra=None, dec=None, as_json=False, apply_extinction=True, apply_k_corr=True)`** → `str`（`as_json=True` 為 `fig.to_json()`；否則 `pyo.plot(fig, output_type='div', include_plotlyjs=False)` 的 HTML div）| `None`（無資料或無 trace）
- **輸入格式**：`list[dict]`，每點讀取 `mjd`, `magnitude`, `magnitude_error`, `filter`, `telescope`（缺值容錯，皆轉 float；`filter`/`telescope` 預設 `'Unknown'`）。來源為 `TNSObjectDB.get_photometry`（marshal）或 DETECT 的 `lc_data['photometry']`。
- **TNS 去重**（`TNS_DEDUP_WINDOW = 1.0` 天；`telescope` 字串含 `'tns'` 視為 TNS 點）：規則 1——同濾鏡有非 TNS 點在 1 天內則捨棄 TNS 點；規則 2——同濾鏡的 TNS 點每 1 天窗只留第一筆（**只看 filter，不看 telescope**，程式註解說明是為了把 `"ZTF (TNS)"`/`"ZTF(TNS)"` 視為同源）。
- **分組**：key `f"{filter}_{telescope}"`；符號依望遠鏡循環 `['circle','square','diamond','cross','x','star']`，`'Unknown'` 固定 `circle`。
- **絕對星等軸**：`redshift>0` 且 `ext_M_calculator` 可用時，`distance_mpc, _ = ext_M_calculator.z_to_lmd(z)` → `DM = 5log10(d_pc) − 5`；`apply_k_corr` → `2.5log10(1+z)`；`apply_extinction` 且有 RA/Dec → 軸位移用 `get_extinction(ra, dec, 'V')`，每組 hover 的絕對星等再各自用 `get_extinction(ra, dec, filter)`。
- **Trace**：有誤差（`error>0`）的點畫 `markers`+`error_y`，`customdata=[abs_mag, err]`，hover 顯示 MJD/App. Mag ± err/Abs. Mag；誤差為 `None`/NaN/0 的點視為**上限**，`triangle-down-open`，名稱加 `" - Limit"`，hover `Abs. Mag: >...`。
- **座標軸**：x 為 MJD（最小跨度 5 天、跨度不足時 `dtick=1` 鎖格），`xaxis2` 上方 UTC 日期軸（MJD→date：`datetime(1970,1,1)+timedelta(days=mjd-40587)`）；y 為 App Mag 反向（最小跨度 3.0 mag、`dtick=0.2`），`yaxis2` 右側 `"Abs Mag"`（無紅移時標題 `"Abs Mag (z N/A)"` 並隱藏刻度）。以兩個 `opacity=0` 的假 trace 迫使 `xaxis2`/`yaxis2` 顯示。`title="Photometry Light Curve"`，`showlegend=False`，`template="plotly_white"` 再套 `_apply_unified_plot_style`。
- **KN model 疊圖不在本模組內**：`object_routes.py:1484-1500` 的 `_parse_kn_model()` 讀 `app/modules/web_data/kn_lc_mag.txt`（模組級快取 `_KN_MODEL_CACHE`）提供 KN 模型端點，且光度圖路由回傳 `distance_modulus`（由 `ext_M_calculator.z_to_lmd` 計算）給前端；疊圖動作在前端 JS 完成。

**`_yrange_from_window(all_wls, all_ints, w_min=4500, w_max=7000, pad=0.12)`** → `[lo, hi]` | `None`：取 4500–7000 Å 內 2/98 百分位加 12% 邊距。第 521–522 行有**重複的 `@staticmethod` 裝飾器**（無害）。

**`_window_norm_scale(wavelengths, intensities, w_min=5000, w_max=7000)`** → `float`：5000–7000 Å 內 |flux| 中位數；窗內無資料退回全譜 98 百分位。

**`create_spectrum_plot_from_db(spectrum_data, spectrum_id, rest_frame=False, redshift=None, normalise=False)`** → HTML div | `None`
- 輸入 `list[dict]`，鍵 `spectrum_id`, `wavelength`, `intensity`, `telescope`, `phase`, 可選 `spectrum_label`；只取 `spectrum_id` 相符的點並依波長排序。
- `rest_frame` 且有紅移 → `λ/(1+z)`；`normalise` → 除以 `_window_norm_scale`。
- 單一 `lines` trace 顏色 `#3ddc84`（註解：避開前端譜線標記色相）；標題 `"<label> (Phase: X days)"`；`hovermode='x unified'`；y 範圍用 `_yrange_from_window`。

**`create_spectrum_list_plot_from_db(spectrum_data, rest_frame=False, redshift=None, normalise=False, stack=False)`** → HTML div | `None`
- 依 `spectrum_id` 分組；**永遠正規化**（`normalise` 時用窗中位數，否則 98 百分位）；`stack=True` 時第 i 條加 `i*1.2` 位移並停用 y 範圍鎖定。
- 顏色循環 `['#3ddc84','#6c7bf0','#cf6be0','#f76a87','#28a866','#a9b2f7']`；圖例在右側外（`x=1.02`）；標題 `"All Available Spectra"`。

### 讀寫的檔案 / 外部服務
無直接檔案 I/O（`filter_colors.json` 由 `filter_colors` 模組載入）。間接透過 `ext_M_calculator` 觸發 SFD 塵埃圖首次下載（見下）。

### 被誰呼叫
- `object_routes.py:1192, 1440`（`create_photometry_plot_from_db(..., as_json=True)`）、`1260/1564`（`create_spectrum_plot_from_db`）、`1264/1568`（`create_spectrum_list_plot_from_db`）。
- `detect_routes.py:309`：`create_photometry_plot_from_db(photometry, z, ra, dec, as_json=True)`（位置參數）。
- `web_api_routes.py:31`：僅 import，未使用。

---

## filter_colors `app/modules/filter_colors.py`

- `_DATA_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'filter_colors.json')` → `app/data/filter_colors.json`（`__file__` 相對）；**import 時載入一次**存 `_COLORS`，改 JSON 需重啟進程。鍵以 `_` 開頭者（`_comment`）被過濾。
- `get_hex(filter_name)` → `'#rrggbb'`，未知 → `'#808080'`；`get_rgba(filter_name, alpha=1.0)` → `'rgba(r,g,b,a)'`；`all_colors()` → dict 副本（注入 `lc_plotter.html` 模板）。
- **`app/data/filter_colors.json` 格式**：單層 JSON 物件，`"_comment"` 說明字串加上「濾鏡名 → 六位 hex（無 alpha）」，大小寫視為不同鍵。現有內容：`uvw2 #311432`、`uvm2 #4b0082`、`uvw1 #8a2be2`、`u/U #800080`、`B/b #0000ff`、`g #00a86b`、`V/v #9acd32`、`c/C #00ffff`、`w/W #eeb861`、`o #ffa500`、`r/R #ff0000`、`i/I #8b0000`、`z/Z #4a0000`、`y/Y #cc6600`、`J #a0522d`、`H #8b4513`、`K/Ks #5c4033`、`L #362511`。
- 注意：Lulin ACP 濾鏡名（`up/gp/rp/ip/zp`）與 TNS 名稱（`cyan`、`orange`、`Clear`、`Other`…）不在表內，會以灰色顯示。

---

## ext_M_calculator `app/modules/ext_M_calculator.py`

### 用途
17 行的 shim：`from function.module.calculator import cosmo, setup_filter_mapping, sf11_extinction, get_extinction, z_to_lmd, apm_to_abm, normalize_filter_name, TNS_FILTER_IDS`，讓 marshal、DETECT 頁面與 DETECT pipeline 共用同一套宇宙學與消光表。`function` 套件可解析是因 `main.py:27` 把 `app/modules/DETECT` 加進 `sys.path`；`app/modules/DETECT/` 由 `scripts/sync_detect.sh` 以 `rsync --delete` 從本機 DETECT checkout 同步（**手動改動會在下次同步被覆蓋**）。

### 底層實作（`app/modules/DETECT/function/module/calculator.py`）
- `cosmo = FlatLambdaCDM(H0=67.4, Om0=0.315, Tcmb0=2.7255, name="DETECT-Planck18")`。
- `TNS_FILTER_IDS`：TNS `discmagfilter` 數字代碼 → 名稱（如 `'21':'g'`, `'22':'r'`, `'71':'cyan'`, `'72':'orange'`, `'73':'wide'`），註明取自 2026-09-14 的完整公開清單。
- `normalize_filter_name(raw)` → 純數字走 `TNS_FILTER_IDS`，空值 → `'unknown'`。
- `setup_filter_mapping()` → 名稱對應到消光表鍵（`y→Y`, `w→V`, `L→BVR_avg`, `cyan/c→B`, `orange/o→gr_avg`, `G/gaia_g→g`, `Clear→BVR_avg`, `unfiltered/unknown/wide/Other/V-crts→V`, `BG-q/gr/VR→gr_avg`, `BG-i→i`, `BG-u→u`, `r-SM/g-SM/i-SM→r/g/i`, `r2/i2→r/i`, `Ha→R`, `TESS→I`）。
- `sf11_extinction(ebv, filter_name)`：Schlafly & Finkbeiner 2011 比值 `U 4.107, B 3.641, V 2.682, R 2.119, I 1.516, J 0.709, H 0.449, K 0.302, u 4.239, g 3.303, r 2.285, i 1.698, z 1.263, Y 1.087, W1 0.184, W2 0.113`；`BVR_avg`/`gr_avg` 取平均；未知鍵印警告並用 V。
- `get_extinction(ra, dec, filter_name)` → `float`（A_filter）：`SkyCoord(icrs)` → `SFDQuery` 求 E(B−V) → mapping → SF11。`SFDQuery` 每進程建立一次；首次使用若 `DETECT_DATA_DIR/dustmaps/sfd/SFD_dust_4096_{ngp,sgp}.fits` 不存在，會從 `https://github.com/kbarbary/sfddata/raw/master/` **下載**（`_ensure_sfd_maps`）。`DETECT_DATA_DIR` 預設 `app/modules/DETECT/data`（`main.py:28`；`function/paths.py` 以環境變數優先）。
- `z_to_lmd(redshift, redshift_error=None)` → `(d_L_Mpc 三位小數, error|None)`；失敗**回傳** `{'error': str, 'timestamp': iso}` dict 而非拋例外。
- `apm_to_abm(apparent_mag, redshift, extinction=0)` → `float`（三位小數）或錯誤 dict：`M = m − (5log10(d_pc) − 5) − 2.5log10(1+z) − A`。

### 被誰呼叫
`data_processing`（`z_to_lmd`, `get_extinction`）、`object_routes.py:1209, 1457`（`z_to_lmd` 算 `distance_modulus`）、`detect_routes.py:284, 831`（`apm_to_abm`, `get_extinction`）、`astronomy_tools_routes.py:112-118`（`/lc_plotter/mw_extinction` 每濾鏡 `get_extinction`）。

### 注意事項
- 錯誤以 dict 回傳，呼叫端必須 `isinstance` 檢查（`data_processing` 有做）。
- 與 `astronomy_calculator.py` 存在**兩套宇宙學參數**（67.4/0.315/2.7255 vs 67.7/0.309/2.725）。
- SFD 首次下載需對外網路，且是在 request 內同步進行。

---

## astronomy_calculator `app/modules/astronomy_calculator.py`

- **`calculate_redshift_distance(redshift, redshift_error=None, H0=67.7, Om0=0.309, Tcmb0=2.725)`** → dict `{'distance_km','distance_ly','distance_pc','distance_mpc','distance_gpc','redshift'}`，有 `redshift_error` 時再加 `distance_error_km/ly/pc/mpc/gpc`（以 dz=0.001 數值微分）。用函式內 `from astropy.cosmology import FlatLambdaCDM`；`ImportError` 時退回線性 Hubble 且**固定 H0=70（忽略傳入值）**。
- **`calculate_absolute_magnitude(apparent_magnitude, redshift, extinction=0, H0=67.7, Om0=0.309, Tcmb0=2.725)`** → `{'absolute_magnitude','distance_modulus','k_correction','distance_mpc','extinction'}`（兩位小數）。`redshift=0` 會在 `log10(0)` 拋 `ValueError`（未防護）。
- 被 `astronomy_tools_routes.py` 的 `/calculate_redshift`、`/calculate_absolute_magnitude`、`/api/distance`、`/api/objects/<name>` 與 `object_routes.py:232, 351` 使用。無檔案/外部服務。未使用的 `from datetime import datetime`。

---

## coordinate_converter `app/modules/coordinate_converter.py`

| 函式 | 輸入 | 輸出 |
|---|---|---|
| `convert_ra_hms_to_decimal(ra_hms)` | 字串 `'hh:mm:ss.ss'`（冒號或空白分隔，恰三段；0≤h<24, 0≤m<60, 0≤s<60，否則 `ValueError`） | `{'ra_hms', 'ra_decimal'(6 位), 'ra_hours'(6 位), 'source': 'hms'}` |
| `convert_ra_decimal_to_hms(ra_decimal)` | 數值（先 `% 360`） | `{'ra_hms': 'HH:MM:SS.SS', 'ra_decimal', 'ra_hours', 'source': 'decimal'}` |
| `convert_dec_dms_to_decimal(dec_dms)` | 字串 `'±dd:mm:ss.ss'`（0≤d≤90，否則 `ValueError`） | `{'dec_dms', 'dec_decimal'(6 位), 'source': 'dms'}` |
| `convert_dec_decimal_to_dms(dec_decimal)` | 數值（超出 ±90 → `ValueError`） | `{'dec_dms': '±DD:MM:SS.SS', 'dec_decimal', 'source': 'decimal'}` |

被 `astronomy_tools_routes.py`（`/convert_ra`, `/convert_dec`, `/api/coords`, `/api/objects`）與 `observation_script.process_observation_request` 使用。注意：秒數格式化 `05.2f` 無進位處理（59.999 → `"60.00"`）；不接受 `12h34m56s` 字母格式（`/generate_plot` 等路由自行以 regex 先清理）。

---

## date_converter `app/modules/date_converter.py`

- `MJD_OFFSET = 2400000.5`。
- **`convert_mjd_to_date(mjd)`** → `{'mjd', 'jd'(6 位), 'common_date': 'YYYY-MM-DD HH:MM:SS', 'source': 'mjd'}`（Meeus 演算法；秒數 `int()` 截斷）。
- **`convert_jd_to_date(jd)`** → 委派 `convert_mjd_to_date(jd − MJD_OFFSET)`，因此 **`source` 仍是 `'mjd'`**。
- **`convert_common_date_to_jd(common_date)`** → 輸入 ISO 字串（`'YYYY-MM-DD HH:MM:SS'` 或含 `T`，`datetime.fromisoformat`），回傳 `{'mjd', 'jd', 'common_date', 'source': 'common_date'}`；只處理格里曆，無時區概念（視為 UTC）。
- 被 `astronomy_tools_routes.py:31`（`/convert_date`, `/api/date`）使用。

---

## request_validation `app/modules/request_validation.py`

- `DEFAULT_MIN = -999999`, `DEFAULT_MAX = 999999`。
- **`ParamOutOfRangeError(ValueError)`**：`__init__(name, value, min_val, max_val)`，訊息 `"Parameter '<name>' has an invalid value (<repr>); expected a number between <min> and <max>"`，屬性 `.name`。
- **`get_int_arg(name, default=None, min_val=DEFAULT_MIN, max_val=DEFAULT_MAX)`**：讀 `flask.request.args`（**只看查詢字串，不看 JSON/form**）；缺值或空字串 → `default`（不驗證 default）；`int()` 失敗 → 拋 `ParamOutOfRangeError`（`'1.5'` 也算失敗）；超界 → 拋。
- **`get_float_arg(...)`**：同上，另拒絕 NaN/inf。
- **`main.py:209-211`**：`@app.errorhandler(ParamOutOfRangeError)` → `jsonify({'error': str(exc)}), 400`，因此路由不必自行 try/except。
- 被 `object_routes`、`web_api_routes`、`private_area_routes`、`astronomy_tools_routes`（例：`/api/visibility/image` 的 `alt`、`tz`）使用。

---

## spectral_lines `app/modules/spectral_lines.py`

一句話交叉引用：以 `astroquery.nist` 抓取 `_IONS` 清單的原子譜線，快取在 `app/modules/_spectral_lines_cache.json`（`Path(__file__).parent`，TTL 30 天），`main.py:266` 啟動時 `warm_cache_async`，`object_routes` 以 `get_spectral_lines` 供光譜檢視器疊線；詳見「光譜檢視器」章。

---

## object_data `app/modules/object_data.py`（已無人使用）

- **原本用途**：`ObjectDataDB` 類別，在 `app/data/object_data.db`（`Path(__file__).parent.parent/'data'`）建立 SQLite 表 `photometry`、`spectroscopy`、`comments` 與索引，提供 `add_photometry_point`、`add_spectrum_data`、`get_photometry`、`get_spectroscopy`、`get_spectrum_list`、`delete_photometry_point`、`delete_spectrum`、`add_comment`、`get_comments`、`delete_comment`、`get_comment_by_id`。檔尾 `object_db = ObjectDataDB()` 會在 **import 時就建立資料庫檔案與表**。
- **確認無人使用**：全 repo 無 import；`app/data/object_data.db` 不存在，證明此模組從未在現行進程被載入。git 僅一個 commit（`c4bcf43 2025-06-15`）。
- **取代者**：`app/modules/database/transient.py` 的 `TNSObjectDB.get_photometry`（542 行）、`get_spectroscopy`（602）、`add_comment`（697）、`get_comments`（718），皆走 PostgreSQL。
- **可安全刪除**：無呼叫端、資料檔不存在、功能已完整移植。

---

## detect_image `app/modules/detect_image.py`（已無人使用）

- **原本用途**：`create_marked_image(obj_name, target_ra, target_dec, coord_list, output_path=None, fov_arcsec=90)` → PNG bytes 或存檔路徑。向 `https://www.legacysurvey.org/viewer/cutout.jpg?ra&dec&pixscale=0.1&layer=ls-dr10-grz&size=` 下載 DESI Legacy Survey 影像（最多重試 3 次），用 Matplotlib 標出目標（青色 ×）與交叉比對來源（`_TYPE_STYLE`：`DESI` 圓、`Lens` 菱形、`VizieR` 三角，各自顏色循環）、5″ 比例尺、圖例含 z 與角距離；下載失敗改畫黑底 "Image unavailable"。
- **確認無人使用**：`create_marked_image` 唯一出現處是本檔 docstring；`/detect_image/<target_name>` 與 `/detect_image_by_id/<id>` 路由改由資料庫讀取影像 bytes（`modules/database/transient.py:2150 get_target_image`、`:2224 get_detect_image_by_id`）。git 僅一個 commit（`daeb78b 2026-04-28`）。
- **可安全刪除**：無呼叫端；影像產生已改由 DETECT pipeline（`app/modules/DETECT`）寫入 DB。

---

## TNS_object_fetch `app/modules/TNS_object_fetch.py`（已無人使用）

- **原本用途**：舊版 TNS 公開物件清單下載/匯入常駐執行緒。`download_TNS_api_hr(hr)` / `download_TNS_api(year, month, day)` 以 `TNS_BOT_ID`/`TNS_BOT_NAME`/`TNS_API_KEY`（自行 `load_dotenv(<repo>/kinder.env)`）POST `https://www.wis-tns.org/system/files/tns_public_objects/tns_public_objects_<hr|YYYYMMDD>.csv.zip`，解壓到 `app/data/tns_api_download_work/tns_public_objects_WORK.csv`（`SAVE_DIR`，**import 時即 `mkdir`**）；`addin_database(filepath)` 批次 upsert `transient.objects`（`BATCH_SIZE=1000`，比較 `last_modified_date` MJD，`Snoozed`→`Inbox`，寫 `log_tns_update_batch` 來源 `'tns_object_fetch'`，最後 `sync_kinder_ids`）；`auto_snoozed(now)` 把 15 天無光度更新者標 `Snoozed`（`Follow-up`→`Finish`）；`main()` 迴圈於每小時 15/45 分與每日 01:00 執行；`start_tns_fetcher(log_dir)` 起 daemon thread。
- **確認無人使用**：全 repo 無 import；`main.py:259/314` 啟動的是 `modules.auto_tns_download.start_auto_tns_downloader`，該模組已含同名的 `download_TNS_api_hr`、`download_TNS_api`、`addin_database`、`auto_snoozed`、`main` 與相同的 `SAVE_DIR`，並新增 fallback 下載、匯入後抓光度與觸發 DETECT。git 5 個 commit，最後 `ff33594 2026-05-26`。
- **可安全刪除**：功能被 `auto_tns_download.py`（＋`tns_gap_filler.py`）完整取代；保留只會造成兩套匯入邏輯漂移的風險。

---

## database_deprecated `app/modules/database_deprecated.py`（已無人使用）

- **原本用途**：SQLite 版帳號/權限層。`DATABASE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'kinder.db')` → `app/data/kinder.db`。`init_database` 建 `users`、`groups`、`user_groups`、`invitations`、`object_permissions`、`system_settings`；`get_db_connection` 為 `contextmanager`（與現行 `modules.database.get_db_connection` 同名，易混淆）；函式含 `get_user`、`get_users`、`save_user`、`update_user`、`delete_user`、`user_exists`、`get_groups`、`create_group`、`delete_group`、`group_exists`、`add_user_to_group`、`remove_user_from_group`、`user_in_group`、`get_invitations`、`create_invitation`、`get_invitation`、`update_invitation`、`delete_invitation`、`clean_accepted_invitations`、`check_data_consistency`、`clean_data_consistency`、`get_all_groups`、`get_object_permissions`、`grant_object_permission`、`revoke_object_permission`、`check_object_access`（無權限設定時預設只有 admin 可見）、`get_setting`、`set_setting`。
- **`data/kinder.db` 確認已不存在**：`ls app/data/kinder.db`、`ls data/kinder.db`、`find . -name kinder.db` 皆無結果；全 repo 只有本檔提到 `kinder.db`。
- **取代者**：`app/modules/database/auth.py`（`get_user` 89 行、`save_user` 140、`get_setting` 710、`set_setting` 722、`check_object_access` 803 等），PostgreSQL。git 僅一個 commit（`7494726 2026-01-25`）。
- **可安全刪除**：無 import、無資料檔、功能已移植。

---

## config `app/modules/config.py`

一句話交叉引用：以 `__file__` 相對路徑 `load_dotenv(app/modules/../../kinder.env)` 載入環境變數並暴露 `config = Config()`（`DEBUG`、`HOST`、`PORT`、`APP_BASE_URL`、`SECRET_KEY`、Google OAuth、SMTP、admin 設定）；`trigger_send` 用 `config.DEBUG` 決定 Slack 測試/正式頻道。詳見「設定與環境」章。

---

## `kn_lc_mag.txt`：`app/modules/web_data/` 與 `app/modules/DETECT/function/data/`

- **是否相同**：兩檔皆 6336 bytes、162 行，MD5 `73f85d3228f5c3d7294a22e4ec8a7398`，`diff` 無差異——**目前完全相同**（mtime 分別為 5/29 與 9/15）。
- **格式**：註解標頭 `# Light Curve Summary Data from lcs`、`# Generated on: 2025-05-10 15:47:35`，接著每個濾鏡一段 `# Filter: sdss::g` + `# time	min	median	max`，資料列為 tab 分隔的 `time(天)  min  median  max`（絕對星等）。
- **誰用哪一份**（`grep -rn kn_lc_mag`）：
  - `app/routes/marshal/object_routes.py:1488` `_parse_kn_model()` → **`web_data` 這份**（`os.path.join(dirname(__file__), '..', '..', 'modules', 'web_data', 'kn_lc_mag.txt')`），解析 `# Filter: sdss::g` 取 `::` 後的濾鏡名，供 marshal 光度圖 KN 模型疊圖。
  - `app/modules/DETECT/function/module/screening.py:45` `KN_MODEL_FILE = Path(__file__).resolve().parents[1] / "data" / "kn_lc_mag.txt"` → **DETECT 這份**，供 DETECT 篩選流程。
- **注意**：DETECT 那份會被 `scripts/sync_detect.sh` 的 `rsync --delete` 覆蓋；`web_data` 那份是手動維護。若上游 DETECT 更新模型，兩份會分歧，marshal 疊圖與 DETECT 篩選將使用不同模型。

---

## 已知問題與注意事項

1. **三份幾乎重複的腳本產生模組**：`observation_script.py`、`trigger_script.py`、`Trigger_LOT_SLT.py` 各自複製了同一張曝光時間表、同一組 SLT/LOT 濾鏡對照與同構的 ACP 區塊組裝碼；差異只在錯誤訊息、標頭格式與 `#REPEAT` 位置。`Trigger_LOT_SLT.py` 可直接刪除；前兩者宜抽出共用的 `exposure_time`/`check_filter*`/曝光表。
2. **`trigger_script.generate_script` 對 mag > 22 的自動曝光目標會崩潰**（`exposure_time` 回傳的長訊息與 `"Too faint to observe"` 比對不符 → 對字串 `.items()`），造成 `/astronomy_tools/generate_trigger_script` 500。`observation_script` 沒這個問題。
3. **`#REPEAT` 位置不一致**：`trigger_script` 把它放在目標列之後，另兩支放在 `#BINNING` 之前；需與 ACP 語法確認正確版本。
4. **`__file__` 相對路徑**（部署搬移時要一起搬）：`filter_colors._DATA_FILE`（`app/data/filter_colors.json`）、`trigger_send._STATUS_PATH`（`app/data/trigger_send_status.json`）、`spectral_lines._CACHE_PATH`（`app/modules/_spectral_lines_cache.json`）、`GCN_alert._DATA_DIR`（`app/data/`）、`config`/`TNS_object_fetch` 的 `kinder.env`、`object_routes` 的 `web_data/kn_lc_mag.txt`、`astronomy_tools_routes._PLANNERS_OV_PLOT_DIR`（`app/routes/planners/ov_plot/`）、DETECT `paths.DATA_ROOT`（`DETECT_DATA_DIR` 環境變數優先）。
5. **`os.getcwd()` 依賴**：只有 `trigger_script.generate_img` 與 `Trigger_LOT_SLT.generate_img`（`cwd/obs_img/`），目前無呼叫端；其餘模組皆不依賴工作目錄。
6. **頂層 `import obsplan`**（`trigger_script`、`Trigger_LOT_SLT`）依賴 `main.py` 的 `sys.path` 注入，且與 `modules.obsplan` 形成兩份模組物件；建議改成 `from modules import obsplan`。
7. **Matplotlib 全域狀態非執行緒安全**：`obsplan.plot_observing_tracks` 用 `plt.figure(1)`/`plt.close('all')`；多執行緒 WSGI 下並行出圖可能互相干擾。
8. **`/generate_plot` 的共用輸出資料夾** `app/routes/planners/ov_plot/` 上限 10 檔、依 mtime 淘汰，任何使用者的新請求都可能刪掉他人尚未取用的圖（`private_area_routes` 的註解已指出此風險，Daily Trigger 因此改用暫存檔）。
9. **`obsplan` 潛伏問題**：`plot_observing_tracks(timezone=...)` 參數無效；`LST_from_local` 會對 `None.copy()` 崩潰（僅 `toptime='LMST'` 觸發，無人使用）；`calculate_moon_times`/`compute_*_tracks` 會改動傳入 observer 的 `date`；`generate_img` 與 `GCN_alert` 都呼叫並丟棄 `calculate_twilight_times(..., '2024/01/01 23:59:00')`。
10. **兩套宇宙學參數**：`astronomy_calculator`（預設 H0=67.7, Om0=0.309, Tcmb0=2.725，ImportError 時退回 H0=70 並忽略參數）與 DETECT `cosmo`（67.4/0.315/2.7255）；同一物件在不同頁面得到的距離/絕對星等會有微小差異。`calculate_absolute_magnitude(z=0)` 會 `log10(0)` 拋錯。
11. **DETECT 消光需要對外網路**：`get_extinction` 首次使用會同步下載兩個 SFD FITS 到 `DETECT_DATA_DIR/dustmaps/sfd/`，在 request 內進行可能逾時。
12. **`filter_colors.json` 大小寫敏感且缺 ACP/TNS 濾鏡名**，缺項一律灰色；載入後不會重讀。
13. **`data_processing`** 的 `web_api_routes.py` import 未使用、`Data_Process` 別名無人用、`_yrange_from_window` 重複裝飾器；TNS 去重規則 2 只以濾鏡分組。KN 模型疊圖邏輯散落在 `object_routes` 與前端，不在本模組。
14. **`get_followup_targets_json`** 以 `discovery_mag` 當 `Mag`、`Priority` 固定 `"Urgent"`、`Filter/Exp_Time/Num_of_Frame` 固定 `rp/300/3`，RA/Dec 由 `process_observation_request` 才轉六十進位。
15. **`request_validation`** 只驗證查詢字串參數；JSON body 的數值另需各路由自行檢查。`date_converter.convert_jd_to_date` 回傳的 `source` 為 `'mjd'`。
16. **可安全刪除的舊模組**（皆無 import、功能已移植、git 保留歷史）：`obsplan_old.py`、`Trigger_LOT_SLT.py`、`object_data.py`（另可避免誤 import 時在 `app/data/` 建 SQLite）、`detect_image.py`、`TNS_object_fetch.py`（另可避免 import 時 `mkdir` 與重複載入 `kinder.env`）、`database_deprecated.py`。
17. **`kn_lc_mag.txt` 雙份維護**：目前相同，但 DETECT 份會被 `sync_detect.sh` 覆蓋、`web_data` 份需手動同步，兩者可能分歧。
