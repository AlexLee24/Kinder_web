# 第 6 章：天文工具、Planners 頁面、公開 REST API 與 API 文件頁、Games（astronomy_tools / games / planners blueprints）

> **注意**：本章記錄的是重構前（commit `c7f91a4`，2026-09-21）的狀態，檔案路徑為舊位置（`app/routes/…`、`app/modules/…`）。新位置請對照 `docs/ARCHITECTURE.md` §6「新舊路徑對照」；功能與行為在重構後完全相同。

> 原始碼依據：`app/routes/astronomy_tools/astronomy_tools_routes.py`（2372 行）、`app/routes/games/games_routes.py`、`app/routes/planners/planners_routes.py`、對應模板與 JS，以及 `app/main.py`、`app/routes/__init__.py`。本章所有 route 均逐一讀碼確認；共 **40 個 route**（astronomy_tools 36、games 3、planners 1）。

## 概要

### 這個區塊負責什麼

`astronomy_tools_bp`（Blueprint 名 `astronomy_tools`，無 `url_prefix`）是整站「公開工具」的集中地，包含五類功能：

1. **Astronomy Tools 首頁**（`/astronomy_tools`）：紅移→距離、絕對星等、RA/Dec 六十進位↔十進位、MJD/JD/日期轉換，背後是 5 個 POST 小端點。
2. **Planners 頁面群**：`/observation_planner`（ACP 觀測腳本產生器 + 靜態可見度圖）、`/interactive_planner`（Plotly 互動式可見度圖）、`/finding_chart`（尋星圖產生器）。這三頁的 **route 在 astronomy_tools blueprint，但模板與 CSS/JS 放在 `app/routes/planners/`**（見下方「模板與靜態檔如何被找到」）。`planners_bp` 本身只有一個 route：`/ov_plot/<filename>`，用來送出 `/generate_plot` 產生的 JPG。
3. **獨立工具頁**：`/lc_plotter`（光變曲線繪圖器，含分享連結）、`/telescope_simulator`（Aladin Lite 視野模擬）、`/mount_torque`（諧波赤道儀扭矩分析，純前端）、`/mount_3d`（WebGL 赤道儀模型，純前端）、`/exposure_time_calculator`（CASTOR 曝光時間計算器）。
4. **公開 REST API**（`/api`、`/api/distance`、`/api/coords`、`/api/date`、`/api/finding_chart/surveys`、`/api/finding_chart/image`、`/api/visibility/image`、`/api/objects/<name>`）：無需登入、以 IP 為單位做簡易速率限制；`/api/objects/<name>` 可附 `api_key` 取得光度/光譜。
5. **內部 JSON 端點**（供本章頁面與 private_area 的 Daily Trigger 頁使用）：`/api/visibility_data`、`/generate_plot`、`/api/target_autocomplete`、`/api/finding_chart`（POST）、`/api/finding_chart/fits`、`/astronomy_tools/get_followup_targets`、`/astronomy_tools/generate_script`、`/astronomy_tools/generate_trigger_script`、`/api/exposure_time_calculator*`、`/lc_plotter/*`。

`games_bp`（Blueprint 名 `games`）提供 `/games`（1A2B 猜數字遊戲，邏輯全在前端）與 `/api/games/leaderboard`（GET/POST，JSON 檔案排行榜）。

### 對應網站哪些頁面（導覽入口）

`app/routes/basic/templates/_navbar.html` 與 `home.html` 的選單：

| 選單 | 項目 | endpoint |
|---|---|---|
| Tools | Astronomy Tools | `astronomy_tools.astronomy_tools` |
| Tools | Telescope Simulator | `astronomy_tools.telescope_simulator` |
| Tools | LC Plotter | `astronomy_tools.lc_plotter` |
| Tools | Exposure Time Calculator | `astronomy_tools.exposure_time_calculator` |
| Tools | （已註解掉）3D Mount Simulator | `astronomy_tools.mount_3d` |
| Tools | Games | `games.games` |
| Planners | Visibility Plot | `astronomy_tools.interactive_planner` |
| Planners | Finding Chart | `astronomy_tools.finding_chart` |

**沒有任何選單入口**的頁面：`/observation_planner`（navbar 的 Planners 群組 active 判斷有列 `'/observation_planner'`，但沒有連結）、`/mount_torque`（只能從 Telescope Simulator 頁的「Mount Torque」按鈕進入）、`/mount_3d`（連結被註解）、`/api`（API 文件頁；全站無 `url_for('astronomy_tools.api_index')` 或 `href="/api"`）。

### 和其他區塊的關係

- **marshal**：`app/routes/marshal/static/js/object_detail.js` 以 `/finding_chart?object_name=&ra=&dec=&survey=DSS2+Red&fov=13&show_stars=0&auto=1` 與 `/interactive_planner?object_name=&ra=&dec=` 帶參數連進本章頁面（兩頁的 inline JS 會讀 URL 參數自動填表）。
- **private_area（Daily Trigger）**：`daily_trigger.js` 直接呼叫本章的 `/api/visibility_data`、`/generate_plot`、`/astronomy_tools/generate_trigger_script`。`private_area_routes.py` 註解明言 `planners/ov_plot` 是「全站共用、上限 10 張」的資料夾，所以 Daily Trigger 送 Slack 前會重新產圖而不信任先前的 `plot_url`。
- **web_api**：`api_docs.html`（本章）同時描述 web_api blueprint 的 `/api/test`、`/api/v1/observation_targets`、`/api/v1/observation_logs`（那些 route 屬其他章）。
- **modules/database**：`transient.objects`（搜尋/座標/metadata）、`transient.photometry`、`transient.spectroscopy`、`transient.object_source_permissions`、`transient.default_permissions`、`auth.users`、`auth.groups`。
- **modules/CASTOR**（git clone 的外部引擎，`sys.path` 加入 `app/modules/CASTOR/src`）與 **modules/DETECT**（`ext_M_calculator` 是 DETECT `function.module.calculator` 的 shim，提供 SFD 消光）。

### 全域前置處理（`app/main.py`，對本章所有 route 生效）

| 鉤子 | 行為 | 對本章的影響 |
|---|---|---|
| `_enforce_allowed_host`（before_request） | `request.host` 不在 `APP_BASE_URL`（DEBUG 時加 localhost/127.0.0.1）→ `abort(404)` | 所有 route |
| `refresh_user_session`（before_request，來自 auth_routes） | 若 session 有 `user`，查 `auth.users` 同步 `is_admin`/`is_great_lab_member`/`picture` 到 session，設 `g.current_user`；**不做任何權限阻擋** | 本章 route 全部公開，此鉤子只影響 navbar 顯示與 `lc_plotter` 的 `user_email` |
| `_block_pipe_in_api_params`（before_request） | 路徑以 `/api/` 開頭時，query string、form、JSON body 任一值含直線字元 `\|` → `{"error": "Invalid character '\|' is not allowed"}` 400 | `/api/*` 全部（含 `/api/objects/<name>?api_key=`、`/api/visibility_data` 的 JSON、ETC 的 JSON） |
| `errorhandler(ParamOutOfRangeError)` | 回 `{"error": "<msg>"}` 400 JSON | `get_float_arg`/`get_int_arg` 失敗時（`/api/finding_chart/image`、`/api/visibility/image` 因此會回 JSON 而非 text/plain） |
| `_add_isolation_headers`（after_request） | 加 `Cross-Origin-Opener-Policy: same-origin`、`Cross-Origin-Resource-Policy: same-origin` | 所有回應（含公開 API 的圖片） |
| `_log_request_access`（after_request，需 `ACCESS_LOG_ENABLED`） | 寫 `web.request` logger | — |

### 模板與靜態檔如何被找到（planners 目錄的特殊安排）

- `app/main.py`：`Flask(__name__, template_folder='html', static_folder=None)`。`app/html` 目錄**並不存在**，所以 app 層級沒有模板；Jinja 的 `DispatchingJinjaLoader` 會依「app 模板資料夾 → 各已註冊 blueprint 的 `template_folder`」順序搜尋。每個 blueprint 都宣告 `template_folder='templates'`，因此 `render_template('observation_planner.html')`（在 astronomy_tools 的 view 內呼叫）會在 `app/routes/planners/templates/` 找到；`_navbar.html`、`_favicon.html` 則來自 `app/routes/basic/templates/`。`planners_routes.py` 的 docstring 直接說明：「Registering this blueprint makes planners/templates/ discoverable by Flask.」`register_routes()` 的註冊順序：auth, admin, astronomy_tools, objects, api, web_api, private_area, basic, marshal, detect, web_log, database_status, games, planners（同名模板時先註冊者優先）。
- 靜態檔：app 層以 `@app.route('/static/<path:filename>', endpoint='static')` 自訂 `serve_static_files`，依序在 `_BLUEPRINT_STATIC_DIRS`（basic, auth, astronomy_tools, marshal, detect, games, private_area, planners, web_api）找第一個存在的檔案，再 fallback 到專案根 `photo/` 與 `basic/icon/`。所以 planners 模板寫 `url_for('static', filename='css/finding_chart.css')` 會在 `app/routes/planners/static/` 命中；`url_for('astronomy_tools.static', filename='css/etc.css')` 產生的 URL 同樣是 `/static/css/etc.css`，實際仍由同一個搜尋邏輯服務。**風險**：不同 blueprint 若有同名檔案（例如兩個 `css/style.css`），排序在前者會遮蔽後者。

---

## 頁面（HTML routes）

### 1. `/astronomy_tools` — Astronomy Tools 首頁

- **路徑 / 方法**：`GET /astronomy_tools`
- **endpoint**：`astronomy_tools.astronomy_tools`
- **權限**：公開
- **模板**：`app/routes/astronomy_tools/templates/astronomy_tools.html`
- **模板變數**：`current_path='/astronomy_tools'`
- **CSS/JS**：`css/astronomy_tools.css`、`js/astronomy_tools.js`
- **頁面區塊與互動**：

| 區塊 | 元素 | 呼叫 / 導向 |
|---|---|---|
| Distance & Magnitude Calculator | 輸入 `#redshift-value`（必填）、`#redshift-error`、`#apparent-magnitude`、`#extinction`（預設 0）、`#distance-unit`（km/ly/pc/Mpc/Gpc，預設 Mpc）；按鈕 Calculate → `calculateBoth()` | `POST /calculate_redshift`（redshift, redshift_error?, H0, Om0, Tcmb0）＋（若有 m）`POST /calculate_absolute_magnitude`（apparent_magnitude, redshift, extinction, H0, Om0, Tcmb0），`Promise.all` 後合併顯示於 `#combined-result` |
| 宇宙學參數 chip / Modal `#cosmo-modal-overlay` | `#cosmo-H0`（67.7）、`#cosmo-Om0`（0.309）、`#cosmo-Tcmb0`（2.725）；Reset to Planck 2018 / Apply | 純前端狀態 `cosmoParams`；Apply 後若已有結果會自動重算 |
| Coordinate Conversion | `#ra-hms` / `#ra-decimal` → Convert RA；`#dec-dms` / `#dec-decimal` → Convert DEC（輸入其一會自動清空另一欄） | `POST /convert_ra`（ra_hms 或 ra_decimal）、`POST /convert_dec`（dec_dms 或 dec_decimal） |
| Date Conversion | `#mjd` / `#jd` / `#common-date`（datetime-local）→ Convert Date | `POST /convert_date`（mjd 或 jd 或 common_date） |
| 促銷卡片 | LC Plotter、Exposure Time Calculator | `url_for('astronomy_tools.lc_plotter')`、`url_for('astronomy_tools.exposure_time_calculator')` |
| 單位切換 | `#distance-unit` change 事件 | 若已有結果則重新呼叫 `calculateBoth()` |

- **導向**：只連到 `/lc_plotter`、`/exposure_time_calculator`；外部連結 ADS（Planck 2018）。

### 2. `/observation_planner` — Observation Planner（ACP 腳本產生器）

- **路徑 / 方法**：`GET /observation_planner`
- **endpoint**：`astronomy_tools.observation_planner`
- **權限**：公開（注意：可讀取 DB 的 Follow-up 目標清單）
- **模板**：`app/routes/planners/templates/observation_planner.html`（由 planners blueprint 提供）
- **模板變數**：`current_path='/observation_planner'`
- **CSS/JS**：`css/observation_planner.css`、`css/observation_planner_extra.css`、`js/observation_planner.js`（皆在 planners/static）
- **頁面區塊與互動**：

| 區塊 | 元素 | 呼叫 / 導向 |
|---|---|---|
| Global Settings | `#telescope-select`（LOT/SLT）、`#observation-date`（預設今天 `YYYY/MM/DD`）、`#send-control`（checkbox，預設勾） | — |
| 按鈕列 | Fetch Follow-up Targets | `GET /astronomy_tools/get_followup_targets` → 以 `result.data.targets` 逐筆 `addTargetRow()`；若 `settings.IS_LOT` 存在則切換望遠鏡 |
| 按鈕列 | Fetch Custom Targets | `GET /api/custom_targets` — **後端不存在此 route**（見已知問題） |
| 按鈕列 | Add Manual Target / Clear All | 純前端（`<template id="row-template">`） |
| Target List 表格 | 每列：name、RA、Dec、Mag、Priority（Urgent/High/Normal/Medium/Low）、Auto by Mag checkbox 或手動 Filter/Exp/Count 列（`<template id="exposure-row-template">`，filter 值 up/gp/rp/ip/zp）、Repeat、Info、刪除 | — |
| Generate Script | `generateScript()` → `collectData()` | ① `POST /astronomy_tools/generate_script`（`{settings:{IS_LOT:"True"/"False", send_to_control_room}, targets:[{ "object name", RA, Dec, Mag, Priority, Filter, Exp_Time, Num_of_Frame, Repeat, Info, Exp_By_Mag }]}`）→ 填入 `#script-output`；② 若有日期再 `POST /generate_plot`（date, telescope, location 固定 `"120.873611 23.468611 2862"`, timezone `"8"`, targets:[{object_name, ra, dec}]，RA/Dec 先經 `formatForPlot()` 轉 H:M:S / D:M:S）→ `#visibility-plot.src = plot_url?t=` |
| Generated Output | textarea + Copy 按鈕（clipboard） | — |

- **導向**：無選單入口，僅能直接輸入 URL。

### 3. `/mount_torque` — Harmonic Analyzer（諧波赤道儀扭矩）

- **路徑 / 方法**：`GET /mount_torque`
- **endpoint**：`astronomy_tools.mount_torque`
- **權限**：公開
- **模板**：`app/routes/astronomy_tools/templates/mount_torque.html`（1029 行，CSS 與 JS 全部 inline；`<title>` 為 "Harmonic Analyzer v6.0 (Physics Engine)"）
- **模板變數**：`current_path='/mount_torque'`
- **頁面區塊與互動**：語言切換 `#langSelect`（en / zh-TW，存 `localStorage.harmonicAnalyzerLang`）、機型預設 `#presetSelect`（am5、nyx101、wd17、wd20、rst300）、Mount Geometry 滑桿（L1、Max Torque）、OTA 清單（口徑/重量/墊高）、Counterweights（重錘桿長/重、配重清單、Vixen 快速新增 1/1.9/2.8/3.7/5 kg）、`#simCanvas`（2D 繪圖，可拖曳/滾輪縮放）、`#stats` 儀表板（扭矩、質心、重量上限、建議文字）、`#torqueChart`（扭矩 vs RA 角度）、`#raRotation` 滑桿、Reset View、行動版 Controls 收合。**不呼叫任何後端 API。**
- **導向**：由 `/telescope_simulator` 頁的 Mount Torque 按鈕進入。

### 4. `/mount_3d` — 3D Equatorial Mount Simulator

- **路徑 / 方法**：`GET /mount_3d`
- **endpoint**：`astronomy_tools.mount_3d`
- **權限**：公開
- **模板**：`app/routes/astronomy_tools/templates/mount_3d.html`
- **模板變數**：`current_path='/mount_3d'`
- **CSS/JS**：`css/mount_3d.css`、`js/mount_3d.js`（純 WebGL，無外部函式庫）
- **頁面區塊與互動**：`#mount-canvas`（滑鼠拖曳環繞、滾輪縮放）、Coordinate Input（`#input-ra` hh:mm:ss 或度、`#input-dec`）→ `gotoCoordinate()`；Manual Control（±RA、±DEC 按住滑動，`#slew-speed` 1–30 °/s）；Quick Presets（North/South Pole、Equator 0h/6h、M1、M31、M87、Home/Park→`parkMount()`）；Current Position 顯示（度、HMS、DMS）。模擬 LST 以恆星時率前進，追蹤模式鎖定 HA。**不呼叫任何後端 API。**
- **導向**：navbar 連結已註解，只能直接輸入 URL。

### 5. `/lc_plotter` — LC Plotter（光變曲線 / 通用資料繪圖器）

- **路徑 / 方法**：`GET /lc_plotter`
- **endpoint**：`astronomy_tools.lc_plotter`
- **權限**：公開（登入者的 email 會注入頁面，用於 localStorage 鍵名）
- **模板**：`app/routes/astronomy_tools/templates/lc_plotter.html`
- **模板變數**：`current_path='/lc_plotter'`、`filter_colors`（`modules.filter_colors.all_colors()`，來自 `app/data/filter_colors.json` 的 `{filter: '#hex'}`，以 `<script type="application/json" id="filterColorsData">` 注入）、`user_email`（`session['user']['email']` 或 `''`，注入 `#lcpUserEmail`）
- **CSS/JS**：`css/lc_plotter.css`、`js/lc_plotter.js`（1503 行）、CDN Plotly 2.35.2
- **頁面區塊與互動**：

| 區塊 | 元素 | 呼叫 / 導向 |
|---|---|---|
| Plot Style | 預覽模式 Interactive/Static、標題、X/Y 標籤、Invert X/Y、Log X/Y、Grid、字級、Tick 間距、軸範圍、Live BG / Export BG、Legend 位置/大小/方向 | 純前端 |
| Data | `#dropZone` 拖放或點選檔案（.csv/.txt/.dat，自動分隔符；`#setting_key:value` 註解列會還原設定）、預覽前 5 列、Show all（Modal） | 純前端 `FileReader` |
| Axes | X/Y 主軸欄位與誤差欄、上方 X 副軸（Phase：`#lcExpMJD` + 單位；Date：MJD 欄；或任一資料欄）、右側 Y 副軸（Absolute Magnitude：`#lcRedshift`；或資料欄）、Group by | 純前端（距離模數以 JS 內建平坦 ΛCDM 積分 H0=67.7、Om0=0.309 計算） |
| LC Settings | Filter Color Map（`#lcFilterCol` + Auto Colors）、Upper Limits（flag 模式或 limit 欄）、MW Extinction（`#mwExtRA`、`#mwExtDec` + Auto-fill by coord） | `POST /lc_plotter/mw_extinction`（`{ra, dec, filters:[groupVal...]}`）→ 填各 series 的 `mwExt` |
| Series | 每個 series：可見、標籤、顏色（存 localStorage `lcp_filter_colors_<email>` 或 `_guest`）、形狀、大小、線、★ 點、A_MW；Legend Preview 可直接改文字；點擊圖上點切換 ★ | 純前端 |
| Actions | Render（`Plotly.react('#plotlyDiv')`）、PNG/SVG（離屏 1600×900 匯出）、CSV、DAT (w/ settings) | 純前端 |
| Share | Image link / Interactive link → `#shareModal`（密碼保護預設勾選，「Link expires in 60 days」）→ Create Link | `POST /lc_plotter/share`（`{traces, layout, isStatic, password}`）→ 以回傳 `id` 開新分頁 `/lc_plotter/shared/<id>` 並複製到剪貼簿 |
| 返回 | ← Astronomy Tools | `url_for('astronomy_tools.astronomy_tools')` |

### 6. `/lc_plotter/shared/<share_id>` — 分享的圖表頁（含密碼閘）

- **路徑 / 方法**：`GET|POST /lc_plotter/shared/<share_id>`
- **endpoint**：`astronomy_tools.lc_plotter_shared`
- **權限**：公開；若該分享檔有密碼，需以 POST 表單 `password` 通過 `check_password_hash` 後，於 session 設 `lcp_unlock_<share_id>=True` 才看得到圖（其他情況：`share_id` 不符 `^[a-f0-9]{24}$` → 404；檔案不存在 → 404；建立超過 60 天 → 410；對無密碼分享 POST → 400）
- **模板**：`app/routes/astronomy_tools/templates/shared_plot.html`（無 navbar、獨立版面，CDN Plotly）
- **模板變數**：`traces`、`layout`（未解鎖時為 `None`）、`is_static`、`share_id`、`has_password`、`password_error`、`unlocked`
- **頁面區塊與互動**：頂列「← LC Plotter」（`href="/lc_plotter"`）、badge（Static image / Interactive chart · shared/<前 8 碼> · 🔒）、Copy link、Download PNG（僅 static；`Plotly.downloadImage` 1600×900）；未解鎖時顯示密碼表單 `<form method="POST">`（`password` 欄），錯誤時顯示 "Incorrect password — try again"。解鎖後 `Plotly.newPlot('plot', traces, layout, {staticPlot: isStatic, ...})`。
- **導向**：POST 密碼正確 → `redirect(url_for('astronomy_tools.lc_plotter_shared', share_id=...))`（GET）。

### 7. `/telescope_simulator` — Telescope Simulator（Aladin Lite）

- **路徑 / 方法**：`GET /telescope_simulator`
- **endpoint**：`astronomy_tools.telescope_simulator`
- **權限**：公開
- **模板**：`app/routes/astronomy_tools/templates/telescope_simulator.html`
- **模板變數**：`current_path='/telescope_simulator'`
- **CSS/JS**：`css/telescope_simulator_main.css`、`js/telescope_simulator.js`、CDN jQuery 3.6.0、Aladin Lite v3（`https://aladin.cds.unistra.fr/AladinLite/api/v3/latest/aladin.js`）
- **頁面區塊與互動**：標題列「Mount Torque」按鈕（→ `url_for('astronomy_tools.mount_torque')`）；Surveys 收合面板（Ground / Space 分組的 HiPS 按鈕，`changeSurvey(id)` → `aladin.setImageSurvey`）；Instrument 收合面板：Telescope 預設（Lulin LOT/SLT/LATTE）、焦長/口徑/減焦鏡、Camera 預設（LOT Sophia、SBIG ST-9XEI、SLT Andor iKon-M 934、Moravian C5-100M、PlayerOne 系列）、感光元件尺寸/解析度、Mosaic（tiles X/Y、overlap、rotation）、Target（Name Search → `aladin.gotoObject`（CDS 名稱解析）；RA/Dec → `aladin.gotoRaDec`）；資訊列（有效焦長、F 比、像素尺度、單張/總 FOV）、Tile Centers 清單；`#aladin-lite-div` 上以 SVG 疊加 FOV/馬賽克框（`createFixedFOVOverlay`），監聽 `zoomChanged`/`positionChanged` 重繪。**不呼叫任何 Kinder 後端 API**（所有外部呼叫由 Aladin Lite 對 CDS 進行）。

### 8. `/exposure_time_calculator` — Exposure Time Calculator（CASTOR）

- **路徑 / 方法**：`GET /exposure_time_calculator`
- **endpoint**：`astronomy_tools.exposure_time_calculator`
- **權限**：公開
- **模板**：`app/routes/astronomy_tools/templates/exposure_time_calculator.html`；view 以 `open(_CASTOR_ETC_BODY_PATH)` 每次請求把 `templates/castor_etc_body.html` **當純文字讀入**並以 `{{ castor_etc_body | safe }}` 注入（route 註解：因該檔的 HTML 註解含字面 `{% include 'castor_etc_body.html' %}`，若交給 Jinja 會遞迴 include）。
- **模板變數**：`current_path='/exposure_time_calculator'`、`castor_etc_body`（原始 HTML 字串）
- **CSS/JS**：`css/etc.css`、`js/etc.js`（defer）、CDN Plotly 2.35.2；inline `<script>` 設 `window.CASTOR_ETC_CONFIG = {apiUrl, batchUrl, presetsUrl}` 分別為 `url_for('astronomy_tools.api_exposure_time_calculator')`、`...batch`、`...presets`
- **頁面區塊與互動**（`castor_etc_body.html` + `etc.js`）：

| 區塊 | 元素 | 呼叫 |
|---|---|---|
| 左側表單 `#castor-form` 四個 tab | Instrument（Site `#select-profile` → Telescope/Camera/Filter 選單，各自 `<details>` 展開原始欄位：`instrument.telescope.*`、`instrument.camera.*`、`instrument.optic_filter.*`、`instrument.throughput_correction`）、Target（`target.ra`/`target.dec`、`target.morphology.type`、`target.brightness.type` + 對應動態欄位、`target.sed.type` 只剩 flat）、Conditions（FWHM 四項、`environment.auto_calc_background`、`environment.mu_dark`、隱藏的 `environment.zodiacal_share`、`environment.extinction_coeff`、`environment.location.*`）、Options（`options.single_exp_time`、`options.type` solve_snr/solve_time、`options.num_exposures` 或 `options.target_snr`、Sweep time range `#toggle-batch`、`environment.observing_time_utc`、`batch.start_time_utc`/`batch.end_time_utc`/`batch.time_step_minutes`、Photometry `<details>`：`options.aperture_factor`、`options.sky_annulus.inner_factor/outer_factor/estimator`） | 每個 `<input name>` 就是 `castor.schema` 的 dotted path；`PayloadBuilder.build()` 依 name 組成巢狀 JSON、跳過隱藏 `.dynamic-group`、`data-percent` 欄位除以 100、datetime-local 轉 ISO（UTC） |
| 工具列 | **EXECUTE**（Kinder 特有；上游 CASTOR 是即時重算）→ `recalculate()`；LOAD / SAVE（`<dialog id="json-dialog">`，JSON 文字、Choose file…、Import / Copy / Download `castor_request.json`） | EXECUTE → `POST apiUrl`（`ObservationRequest`）；若開啟 Sweep 再 `POST batchUrl`（`BatchObservationRequest`）。每類請求以 AbortController 取消前一個；單點 debounce 250 ms、批次 500 ms |
| 預設值載入 | 頁面載入即 `fetch(presetsUrl)` → 填 Site/Telescope/Camera/Filter；第一個 profile（`lulin`）為預設 | `GET /api/exposure_time_calculator/presets` |
| 右側結果 | Hero（SNR 或 Required Exposures；sweep 時改為「Best SNR in Window」）、`#error-box`、`#warning-box`、Signal & Noise Budget、Physical Diagnostics、Observation Limits、Observing Window（Plotly 三層圖：高度 / 單張 SNR 或所需張數 / 飽和時間） | — |
| 預設觀測時刻 | 固定為 2025-09-28T20:00Z（SN 2025wny 的 LOT 觀測夜）；sweep 18:00–22:00Z | — |
| 頁尾 | Bug Report → `https://github.com/AlexLee24/CASTOR`；作者連結 | 外部 |

### 9. `/interactive_planner` — Interactive Visibility Planner

- **路徑 / 方法**：`GET /interactive_planner`
- **endpoint**：`astronomy_tools.interactive_planner`
- **權限**：公開（含 DB 目標搜尋）
- **模板**：`app/routes/planners/templates/interactive_planner.html`（904 行，JS inline）
- **模板變數**：`current_path='/interactive_planner'`
- **CSS/JS**：`css/interactive_planner.css`（planners/static）、CDN Plotly 2.35.2；inline JS
- **URL 參數自動填表**：`object_name`、`ra`、`dec`（三者齊全才填入第一列並觸發更新）
- **頁面區塊與互動**：

| 區塊 | 元素 | 呼叫 |
|---|---|---|
| Observatory Settings | `#date`（預設今天）、`#telescope`（Other / Lulin（預設）/ LasCampanas / Palomar / KTO；選擇後自動填 `#location`「lon lat alt」與 `#timezone`） | — |
| Targets | DB 搜尋框 `#db-search-input`（≥2 字元、300 ms debounce、鍵盤上下/Enter/Esc；選取後填入第一個空列或新增列）、目標列（name/RA/Dec + 顏色 + 刪除）、Add Target | `GET /api/target_autocomplete?q=` |
| 自動更新 | 任一欄位變更 → 600 ms debounce `fetchVisibilityData()` | `POST /api/visibility_data`（`{date, location, timezone, telescope, targets:[{name, ra, dec}]}`，RA/Dec 先由 `parseAndFormatRA/Dec` 轉成 H:M:S / D:M:S） |
| Display Options | Sun / Moon / Twilight checkbox（只影響 Plotly 重繪）；≤1375 px 視窗以 CSS 隱藏並顯示「請改用靜態圖」警告，JS 亦不呼叫 `renderPlot()` | — |
| Generate Static Plot | `generateStaticPlot()` | `POST /generate_plot`（`{date, location, timezone, telescope, targets:[{object_name, ra, dec}]}`）→ `#static-plot-img.src = plot_url?t=`、下載連結 `href=plot_url` |
| 右側 | `#visibility-plot`（Plotly：twilight 區塊、Sun/Moon 軌跡、各目標高度曲線與編號、下 X 軸 UTC、上 X 軸當地時間、右 Y 軸 airmass、hover 顯示 Alt/Az/AM/Moon Sep）、Moon Info（相位、升/落 UTC/Local）、Target Details（transit UTC/Local、最大高度、月距） | — |

### 10. `/finding_chart` — Finding Chart Generator

- **路徑 / 方法**：`GET /finding_chart`
- **endpoint**：`astronomy_tools.finding_chart`
- **權限**：公開
- **模板**：`app/routes/planners/templates/finding_chart.html`（630 行，JS inline）
- **模板變數**：`current_path='/finding_chart'`
- **CSS/JS**：`css/finding_chart.css`（planners/static）；inline JS
- **URL 參數自動填表**：`object_name`、`ra`、`dec`、`fov`、`survey`（須為選單中的值）、`show_stars=0`（取消 show-mag/show-names）、`auto=1`（且有 ra 或 object_name 時自動按 Generate）
- **頁面區塊與互動**：

| 區塊 | 元素 | 呼叫 |
|---|---|---|
| Target | `#use-db-search` 勾選後顯示 DB 搜尋框（同 interactive_planner 的 autocomplete，選取後填 `#target-name`/`#target-ra`/`#target-dec`）；Object Name、RA、Dec 手動輸入 | `GET /api/target_autocomplete?q=` |
| Survey | `#survey-select`（DSS2 Red/Blue/IR、DSS1、DESI-color（預設）/g/r/z/i、PS1-color/g/r/i/z/y）；`#invert-check`（color survey 時隱藏並取消） | — |
| Field of View | Direct FOV `#fov-arcmin`（預設 15）或 Camera Setup（焦長/感光元件寬高 → 計算 FOV 並回填） | 純前端 |
| Other → Star Annotations | `#mag-limit`（15）、`#show-mag`、`#use-max-stars` + `#max-stars`（10）、`#show-names`、`#name-limit`（10） | — |
| Other → Spectrograph Slit | `#show-slit`、`#slit-pa`（64.4）、`#slit-width`（1.2"）、`#slit-length`（60"） | — |
| Generate Finding Chart | `generateChart()` | `POST /api/finding_chart`（`{name, ra, dec, survey, fov, invert, mag_limit, name_limit, show_mag, show_names, max_stars, show_slit, slit_pa, slit_width, slit_length}`）→ `#chart-image.src = data:image/png;base64,...`、`#chart-info`、日誌面板 `#log-panel` 顯示 `logs[]` |
| Download PNG | 以 `<a download>` 存 `#chart-image.src` | 純前端 |
| Download FITS | 以上一次的 payload | `POST /api/finding_chart/fits` → blob 下載（檔名取自 `Content-Disposition`） |

### 11. `/api` — API Reference 文件頁（HTML 或 JSON）

- **路徑 / 方法**：`GET /api`
- **endpoint**：`astronomy_tools.api_index`
- **權限**：公開
- **內容協商**：`Accept` 以 `application/json` 開頭或 `?format=json` → `jsonify(_API_DOCS)`（程式內的文件字典）；否則 `render_template('api_docs.html', current_path='/api')`
- **模板**：`app/routes/astronomy_tools/templates/api_docs.html`（樣式 inline + `css/astronomy_tools.css`）
- **頁面區塊**：Base URL 與 Authentication 說明框；Public API 卡片（`/api/distance`、`/api/coords`、`/api/date`、`/api/finding_chart/image`、`/api/visibility/image`、`/api/objects/{name}`）；Authenticated API 卡片（`/api/test`、`GET/POST /api/v1/observation_targets`、`GET/POST /api/v1/observation_logs` — 屬 web_api blueprint）；每張卡片可展開（`toggleCard`）、範例可 copy（`copyCode`）。`/api/finding_chart/surveys` 以連結形式出現。文件與實作的比對見「api_docs.html 宣稱 vs 實際 route」小節。
- **導向**：無入口連結。

### 12. `/games` — 1A2B Game

- **路徑 / 方法**：`GET /games`
- **endpoint**：`games.games`
- **權限**：公開
- **模板**：`app/routes/games/templates/games.html`
- **模板變數**：`current_path='/games'`
- **CSS/JS**：`css/games.css`、`js/games.js`
- **頁面區塊與互動**：規則說明；`#guess-input`（4 位不重複數字，Enter 或 Guess 按鈕 → `makeGuess()`）、Restart（`initGame()`）；`#game-status`；歷史表 `#history-body`（A/B 判定全在前端，`generateSecret()` 會 `console.log` 出答案）；猜中時 `submitScore(attempts)` → `POST /api/games/leaderboard`（`{attempts}`）→ 成功後 `loadLeaderboard()` → `GET /api/games/leaderboard` 填 `#leaderboard-body`（前三名 🥇🥈🥉）。頁面載入即 `initGame()` + `loadLeaderboard()`。

### 13. `/ov_plot/<path:filename>` — 觀測軌跡圖檔案（planners blueprint）

- **路徑 / 方法**：`GET /ov_plot/<path:filename>`
- **endpoint**：`planners.serve_ov_plot`
- **權限**：公開
- **行為**：`filename` 含 `..` 或以 `/` 開頭 → `abort(400)`；否則 `send_from_directory(app/routes/planners/ov_plot, filename)`（不存在 → 404）。非 HTML 頁面，但為 `/generate_plot` 回傳 `plot_url` 的唯一消費端點。

---

## API 與動作端點

> 權限欄：本章 **所有端點皆為「公開」**（無 `session`/角色檢查）。差異只在：`/api/objects/<name>` 的選擇性 API key、`/lc_plotter/shared/<id>` 的選擇性密碼。所有 `/api/` 開頭端點另受全域 `|` 字元檢查（400 JSON）。

### A. Astronomy Tools 首頁用的 JSON 端點

| 方法 | 路徑 | endpoint | 權限 | 輸入（JSON body） | 成功回應 | 失敗回應 | 副作用 |
|---|---|---|---|---|---|---|---|
| POST | `/calculate_redshift` | `astronomy_tools.calculate_redshift` | 公開 | `redshift`（float，預設 0）、`redshift_error`（float，可省）、`H0`（67.7）、`Om0`（0.309）、`Tcmb0`（2.725） | `{success:true, result:{distance_km, distance_ly, distance_pc, distance_mpc, distance_gpc, redshift[, distance_error_km/ly/pc/mpc/gpc]}}` | 任何例外 → `{error}` 400 | 無（純計算，`modules.astronomy_calculator.calculate_redshift_distance`） |
| POST | `/calculate_absolute_magnitude` | `astronomy_tools.calculate_absolute_magnitude_route` | 公開 | `apparent_magnitude`（必填）、`redshift`（必填）、`extinction`（0）、`H0`、`Om0`、`Tcmb0` | `{success:true, result:{absolute_magnitude, distance_modulus, k_correction, distance_mpc, extinction}}` | `{error}` 400 | 無 |
| POST | `/convert_date` | `astronomy_tools.convert_date` | 公開 | `mjd` 或 `jd` 或 `common_date`（ISO 字串；擇一，依此優先序；注意 `if mjd:` 判斷，值 0 視同未提供） | `{success:true, result:{mjd, jd, common_date:'YYYY-MM-DD HH:MM:SS', source}}` | 三者皆無 → `{error:'Please provide at least one date value'}` 400；解析錯誤 → `{error}` 400 | 無 |
| POST | `/convert_ra` | `astronomy_tools.convert_ra` | 公開 | `ra_hms`（'hh:mm:ss.s'）或 `ra_decimal`（float） | `{success:true, result:{ra_hms, ra_decimal, ra_hours, source}}` | 皆無 → 400；格式錯誤（`ValueError`）→ 400 | 無 |
| POST | `/convert_dec` | `astronomy_tools.convert_dec` | 公開 | `dec_dms`（'±dd:mm:ss'）或 `dec_decimal` | `{success:true, result:{dec_dms, dec_decimal, source}}` | 同上 | 無 |

### B. LC Plotter

| 方法 | 路徑 | endpoint | 權限 | 輸入 | 成功回應 | 失敗回應 | 副作用 |
|---|---|---|---|---|---|---|---|
| POST | `/lc_plotter/mw_extinction` | `astronomy_tools.lc_plotter_mw_extinction` | 公開 | JSON `ra`、`dec`（float，0≤ra≤360、-90≤dec≤90）、`filters`（字串陣列，最多取前 60 個，每個 ≤20 字） | `{"<filter>": A_mag(round 4) 或 null, ...}` | 缺 ra/dec → `{error:'ra and dec required'}` 400；非數字 → 400；超範圍 → 400 | 呼叫 `ext_M_calculator.get_extinction`（DETECT 的 SFD 塵埃圖，**首次使用會下載到 `DETECT_DATA_DIR`**） |
| POST | `/lc_plotter/share` | `astronomy_tools.lc_plotter_share` | 公開，無速率限制 | JSON `traces`（必）、`layout`（必）、`isStatic`（bool）、`password`（可省）；`Content-Length` > 8 MiB → 413 | `{id:'<24 hex>'}` | 缺欄位 → `{error:'Invalid payload'}` 400 | **寫檔** `app/data/shared_plots/<id>.json`（含 `created_at`、`password_hash`（werkzeug）） |
| GET/POST | `/lc_plotter/shared/<share_id>` | `astronomy_tools.lc_plotter_shared` | 公開／密碼閘 | POST form `password` | 渲染 `shared_plot.html`（見頁面 6） | 404 / 410 / 400（見頁面 6） | 讀 `app/data/shared_plots/<id>.json`；成功解鎖時寫 session `lcp_unlock_<id>` |

### C. Exposure Time Calculator（CASTOR）

| 方法 | 路徑 | endpoint | 權限 | 輸入 | 成功回應 | 失敗回應 | 副作用 |
|---|---|---|---|---|---|---|---|
| GET | `/api/exposure_time_calculator/presets` | `astronomy_tools.api_exposure_time_calculator_presets` | 公開 | 無 | 原始 bytes（保留 key 順序）`application/json`；結構 `{_comment, profiles:{lulin, vlt, other}}`，每個 profile 有 `name`、`environment`、`telescopes{}`、`cameras{}`、`filters{}`、選擇性 `caveat`、`median_seeing_fwhm` | 檔案不存在 → `{error:'Presets file not found'}` 404 | 讀 `app/modules/CASTOR/src/castorGUI/data/presets.json` |
| POST | `/api/exposure_time_calculator` | `astronomy_tools.api_exposure_time_calculator` | 公開 | JSON = `castor.schema.ObservationRequest`（`extra="forbid"`）：`instrument{telescope{primary_mirror_diameter, secondary_mirror_diameter, focal_length, optical_throughput}, camera{pixel_pitch, quantum_efficiency, dark_current_rate, readout_noise, full_well_capacity, background_flatness_fraction=0}, optic_filter{central_wavelength, filter_bandwidth, filter_transmission}, throughput_correction}`、`target{morphology{type:point/extended}, brightness{type:vega_mag(target_mag, zero_point_flux)/ab_mag(target_mag)/jansky_flux(flux_value)/wavelength_flux(flux_value)}, sed{type:flat/Temp}, ra[0,360), dec[-90,90]}`、`environment{location{latitude_deg, longitude_deg, elevation_m}, observing_time_utc(aware ISO), auto_calc_background, mu_dark, zodiacal_share?, extinction_coeff, seeing_fwhm, diffraction_fwhm, optical_fwhm, tracking_fwhm}`、`options{type:solve_snr(num_exposures)/solve_time(target_snr), aperture_factor, single_exp_time, sky_annulus?{inner_factor, outer_factor, estimator}}` | `ObservationResponse.model_dump()`：`core{total_snr, single_snr, required_exposures?, saturation_time_limit, optimal_exposure_time}`、`budget{source_count_rate, sky_count_rate, peak_pixel_rate}`、`diagnostics{total_fwhm, effective_area, pixel_scale, total_throughput, enclosed_flux_fraction, num_pixels_aperture, num_pixels_sky_estimate}`、`flags{is_saturated, warnings[]}` | 空 body → `{error:'No data provided'}` 400；pydantic 驗證錯誤 → `{error:'loc: msg; ...'}` 400；其他例外 → 400 | 呼叫 `castor.calculator.run_calculation`（astropy AltAz/Moon；`iers.conf.auto_download=False`） |
| POST | `/api/exposure_time_calculator/batch` | `astronomy_tools.api_exposure_time_calculator_batch` | 公開 | `BatchObservationRequest`：同上但 `environment` 為 `TimeSeriesEnvironment{location, start_time_utc, end_time_utc, time_step_minutes, mu_dark, zodiacal_share?, extinction_coeff, 四個 fwhm}`（無 `auto_calc_background`），`options` 為 `BatchSolveForSNR/BatchSolveForTime` | `BatchObservationResponse`：`core{timestamps_iso[], total_snr[], single_snr[], required_exposures[]?, saturation_time_limit[]}`、`ephemeris{target_elevation_deg[], moon_elevation_deg[], sun_elevation_deg[]}`、`flags` | 同上 | `castor.batch_calculator.run_batch_calculation` |

### D. 觀測規劃（可見度、腳本）

| 方法 | 路徑 | endpoint | 權限 | 輸入 | 成功回應 | 失敗回應 | 副作用 |
|---|---|---|---|---|---|---|---|
| POST | `/generate_plot` | `astronomy_tools.generate_plot` | 公開 | JSON `date`（`YYYY-MM-DD`/`YYYY/MM/DD`，必）、`telescope`（觀測者名，預設 'Observer'）、`location`（`"lon lat alt"` 空白分隔，lon/lat 可 `d:m:s` 或十進位，必）、`timezone`（整數 UTC 偏移，必，須在 `obsplan.get_timezone_name` 的 -12..12 表內）、`targets`（list of `{object_name, ra, dec}`，RA/Dec 支援 `h/m/s`、`d/°/′/″` 記法轉為冒號格式；必） | `{success:true, plot_url:'/ov_plot/observing_tracks_<uuid>.jpg', message}` | 缺欄位/格式錯誤 → `{error}` 400；產圖失敗或檔案未產生 → 500；資料夾準備失敗 → 500 | **先** `enforce_max_files(ov_plot, 10)` 刪最舊檔至剩 10 個，**再寫入** `app/routes/planners/ov_plot/observing_tracks_<uuid4 hex>.jpg`（`obs.plot_night_observing_tracks`，當地 17:00 → 次日 09:00，n_steps=1000，matplotlib Agg） |
| POST | `/api/visibility_data` | `astronomy_tools.visibility_data` | 公開 | JSON `date`、`location`、`timezone`（必）、`targets`（list of `{name, ra, dec}`；RA/Dec 支援十進位或 H:M:S/D:M:S/含 hms/dms 字母）、`telescope`（'Observer'）、`n_steps`（預設 300，上限 500） | `{success:true, times_utc[], times_local[], timezone_name, timezone_offset, sun_alts[], moon_alts[], moon_info{rise_utc, set_utc, rise_local, set_local, phase}, twilight_utc{sunset[2], civil[2], nautical[2], astronomical[2]}, twilight_local{...}, targets[{number, name, ra, dec, altitudes[], azimuths[], transit_time_utc, transit_time_local, moon_separation}], obs_date}`；targets 依 RA 升冪排序並編號；無法解析的目標**靜默略過** | 缺欄位 → 400；時區不支援 → 400；location 格式錯 → 400；日期格式錯 → 400；其他例外 → `{error}` 500（含 `n_steps` 非整數） | 無檔案寫入；純 ephem 計算 |
| GET | `/astronomy_tools/get_followup_targets` | `astronomy_tools.get_followup_targets_route` | 公開 | 無 | `{success:true, data:{settings:{IS_LOT:"True", send_to_control_room:"True"}, targets:[{"object name", RA, Dec, Mag(str 或 "unknown"), Priority:"Urgent", Exp_By_Mag:"True", Filter:"rp", Exp_Time:"300", Num_of_Frame:"3", Repeat:0}]}}` | `{success:false, error}` 500 | 讀 DB：`SELECT o.name, o.ra, o.dec, o.discovery_mag FROM transient.objects o WHERE o.status='Follow-up'`（`get_tns_db_connection`，用後 `conn.close()` 歸還池） |
| POST | `/astronomy_tools/generate_script` | `astronomy_tools.generate_script_route` | 公開 | JSON `{settings:{IS_LOT:"True"/"False"}, targets:[{"object name", RA, Dec, Mag, Priority, Exp_By_Mag:"True"/"False", Filter:"rp,gp", Exp_Time:"300,300", Num_of_Frame:"3,3", Repeat, Info}]}` | `{success:true, script:'<ACP 腳本文字>'}` | `{success:false, error}` 500 | 無；`observation_script.process_observation_request` → 逐目標 `generate_single_script`（十進位座標自動轉 HMS/DMS；自動曝光依星等表） |
| POST | `/astronomy_tools/generate_trigger_script` | `astronomy_tools.generate_trigger_script_route` | 公開（實際呼叫者為 private_area 的 Daily Trigger 頁） | JSON `telescope`（'SLT' 預設，或 'LOT'）、`targets`（非空 list，每項 `{name, ra, dec, mag, priority, priority_message, repeat, auto_exp, filter_input, exp_time, count}`） | `{success:true, script}`（各目標以 `TARGET_SEPARATOR=';====================\n\n'` 串接） | 無 targets → `{success:false, error:'No targets provided'}` 400；例外 → 500 | 寫 logger（`generate_trigger_script: ...`）；`trigger_script.generate_full_script` |

### E. 目標搜尋與尋星圖（頁面用）

| 方法 | 路徑 | endpoint | 權限 | 輸入 | 成功回應 | 失敗回應 | 副作用 |
|---|---|---|---|---|---|---|---|
| GET | `/api/target_autocomplete` | `astronomy_tools.target_autocomplete` | 公開 | query `q`（<2 字元 → `[]`） | JSON 陣列（≤10）`[{name(prefix+name), ra(str), dec(str), type, mag, internal_names}]` | **任何例外都回 `[]`（200）** | 讀 DB `search_tns_objects(search_term=q, limit=10)`（`transient.objects`） |
| POST | `/api/finding_chart` | `astronomy_tools.generate_finding_chart` | 公開，無速率限制 | JSON `name`（'Target'）、`ra`、`dec`（可十進位或六十進位；若解析失敗且有 `name` 則 `SkyCoord.from_name`）、`survey`（'DSS2 Red'）、`fov`（10，arcmin）、`invert`（false）、`mag_limit`（15）、`name_limit`（10）、`show_mag`（true）、`show_names`（true）、`max_stars`（int 或省略）、`show_slit`（false）、`slit_length`（20"）、`slit_width`（1.5"）、`slit_pa`（0°） | `{success:true, image:'<base64 PNG>', ra_deg, dec_deg, fov_arcmin, logs[]}` | 空 body → 400；座標無法解析 → `{error:'Cannot parse coordinates...'}` 400；影像抓取失敗 → `{error, logs}` 500；其他 → 500 | 外部 HTTP：DSS（archive.stsci.edu）/ DESI LS（legacysurvey.org）/ PS1（ps1images.stsci.edu）；VizieR I/259/tyc2 與 I/322A；SIMBAD；名稱解析（CDS Sesame）。matplotlib 產圖，無檔案寫入 |
| POST | `/api/finding_chart/fits` | `astronomy_tools.download_finding_chart_fits` | 公開 | JSON `name`、`ra`、`dec`、`survey`、`fov`（同上；其他欄位忽略） | 二進位 `application/fits`，`Content-Disposition: attachment; filename="<name>_<survey>_<fov>arcmin.fits"` | 座標錯 → 400；該 survey 無 FITS（PS1-color 取 r 波段、DESI-color 取 grz 三波段）或抓取失敗 → `{error, logs}` 400；其他 → 500 | 同上外部 HTTP |

### F. 公開 REST API（`_API_DOCS` / api_docs.html 所文件化）

速率限制實作：`_rate_ok(ip, key, interval)` 以 `(ip, key)` 為鍵記錄 `time.monotonic()`，同 IP 同端點在 `interval` 秒內第二次請求即拒絕；`_rl_store` 超過 20000 筆時清掉 120 秒前的舊鍵。**`_client_ip()` 優先讀 `X-Forwarded-For` 標頭**（見已知問題）。

| 方法 | 路徑 | endpoint | 權限 / 速率 | 輸入（query string） | 成功回應 | 失敗回應 | 副作用 |
|---|---|---|---|---|---|---|---|
| GET | `/api` | `astronomy_tools.api_index` | 公開，無限制 | `format=json` 或 `Accept: application/json` | JSON `_API_DOCS` 或 HTML 文件頁 | — | 無 |
| GET | `/api/distance` | `astronomy_tools.api_distance` | 公開；1 req/s/IP | `z`（必）、`z_err`、`m`、`A`（0）、`H0`（67.7）、`Om0`（0.309）、`Tcmb0`（2.725）；皆經 `get_float_arg`（NaN/Inf/超出 ±999999 → 錯） | `{success:true, result:{input{z, z_err, m, A}, cosmology{H0, Om0, Tcmb0, reference}, distance{...同 /calculate_redshift}, magnitude{...}(有 m 時)}}` | 429 `{error:'Rate limit exceeded — max 1 request/second per IP.'}`；缺 z → `{error, example}` 400；參數非數 → `{error:'Invalid parameter value: ...'}` 400；計算例外 → 500 | 無 |
| GET | `/api/coords` | `astronomy_tools.api_coords` | 公開；1 req/s/IP | `ra_hms` 或 `ra_deg`；`dec_dms` 或 `dec_deg`（至少一個） | `{success:true, result:{ra_hms, ra_decimal, ra_hours, dec_dms, dec_decimal, source}}`（兩個 dict `update` 合併，`source` 以後者為準） | 429；皆無 → `{error, example}` 400；轉換錯誤 → `{error}` 400 | 無 |
| GET | `/api/date` | `astronomy_tools.api_date` | 公開；1 req/s/IP | `mjd` 或 `jd` 或 `date`（ISO） | `{success:true, result:{mjd, jd, common_date, source}}` | 429；皆無 → 400；解析錯 → 400 | 無 |
| GET | `/api/finding_chart/surveys` | `astronomy_tools.api_finding_chart_surveys` | 公開，無限制 | 無 | `{success:true, default:'DESI-color', surveys:[{value, group, label[, default:true]}]}`（15 筆） | — | 無 |
| GET | `/api/finding_chart/image` | `astronomy_tools.api_finding_chart_image` | 公開；**1 req/30 s/IP** | `obj_name`（查 DB 取座標）或 `ra`+`dec`；`name`（顯示標籤；預設 DB 全名／obj_name／'Target'）、`survey`（'DESI-color'）、`fov`（10）、`invert`（'1' 才反相，僅單波段）、`mag_limit`（15）、`name_limit`（10）、`show_mag`（'0' 關）、`show_names`（'0' 關） | `image/png`，`Content-Disposition: inline; filename="finding_chart_<name>.png"` | 429 **text/plain**；`obj_name` 查無 → 404 text；缺座標 → 400 text（含範例）；座標無效 → 400 text；影像抓取失敗 → 500 text；其他 → 500 text；`fov`/`mag_limit`/`name_limit` 非數 → **JSON** 400（全域 handler） | 讀 DB（`_db_lookup_coords`：`transient.objects` ILIKE 全名或 name，再 fallback `search_tns_objects` 精確比對）；外部 HTTP 同 `/api/finding_chart` |
| GET | `/api/visibility/image` | `astronomy_tools.api_visibility_image` | 公開；**1 req/15 s/IP** | `date`（必，YYYY-MM-DD）、`obj_name` 或 `ra`+`dec`、`name`、`lon`（'120:52:21.5'）、`lat`（'23:28:10.0'）、`alt`（2800，float）、`tz`（8，int；只支援 -12..12） | `image/jpeg`，`Content-Disposition: inline; filename="visibility_<date>_<name>.jpg"` | 429 text；缺 date → 400 text；缺座標 → 400 text；日期格式 → 400 text；tz 不支援 → 400 text；產圖例外 → 500 text；`alt`/`tz` 非數 → JSON 400 | 讀 DB（同上）；寫 **暫存檔** `tempfile.NamedTemporaryFile(suffix='.jpg')`，讀回後 `os.unlink` 刪除；matplotlib |
| GET | `/api/objects/<path:object_name>` | `astronomy_tools.api_public_object` | 公開；1 req/s/IP；**選擇性 `api_key`（僅 query string，不讀 `X-API-Key` 標頭）** | path `object_name`（URL-decode 後 strip；ILIKE 比對 `COALESCE(name_prefix,'') \|\| COALESCE(name,'')` 或 `name`；fallback `search_tns_objects(limit=50)` 精確比對）；`api_key` | `{success:true, name, metadata{name, name_prefix, type, ra_deg, dec_deg, ra_hms, dec_dms, discovery_date, discovery_mag, reporting_group, redshift, distance_mpc, brightest_abs_mag, internal_names, status, tags}}`；有效 key 時另加 `photometry[]`（`TNSObjectDB.get_photometry` 欄位 `id, object_name, mjd, magnitude, magnitude_error, filter, telescope`，經 `filter_by_source_permissions(...,'phot',...)`）、`photometry_count`、`spectra[]`（`get_spectrum_list` 欄位 `telescope, observation_mjd, min_wavelength, max_wavelength, point_count, observation_row_id, phase, spectrum_id, spectrum_label, observation_date_label`，經 `'spec'` 權限過濾）、`spectra_count`、`requested_by`（email）；子查詢失敗時改放 `photometry_error`/`spectra_error`。NaN/Inf 以 `_san` 轉 `null` | 429；`api_key` 無效 → `{error:'Invalid API key.'}` 401；查無 → `{error:'Object "<name>" not found.'}` 404；其他 → 500 | 讀 DB：`auth.users`（`get_user_by_api_key`）、`transient.objects`、`transient.photometry`、`transient.spectroscopy`、`transient.object_source_permissions`、`transient.default_permissions`、`auth.groups`；無寫入 |

**API key 驗證方式細節（`/api/objects/<name>`）**：`request.args.get('api_key')` → `modules.database.auth.get_user_by_api_key(api_key)`（`SELECT ... FROM auth.users u WHERE u.api_key = %s`，回傳 `_user_row_to_dict`：`email`、`groups`（由 `get_users()` 填，此處 `setdefault('groups', [])` 可能為空）、`is_admin`（`roles >= 50`）等）。若提供了 key 但查無使用者 → 401，**不會**退回公開模式。之後 `filter_by_source_permissions(object_name, data_type, records, user_email, user_groups, is_admin)`：admin 全放行；否則依 `transient.object_source_permissions`（`is_public` / `allowed_groups`：NULL=任何登入者、[]=封鎖、[ids]=指定群組）→ `transient.default_permissions`（`public`/`login`/`groups`）→ 系統預設（TNS 來源公開、其餘需登入）決定每個 `telescope`/`source` 是否可見。

### G. Games

| 方法 | 路徑 | endpoint | 權限 | 輸入 | 成功回應 | 失敗回應 | 副作用 |
|---|---|---|---|---|---|---|---|
| GET | `/api/games/leaderboard` | `games.get_leaderboard` | 公開 | 無 | JSON 陣列，依 `attempts` 升冪取前 10：`[{name, attempts, date}]`（檔案不存在或損毀 → `[]`） | 記錄缺 `attempts` 鍵 → 500（未處理 KeyError） | 讀 `LEADERBOARD_FILE` |
| POST | `/api/games/leaderboard` | `games.submit_score` | 公開 | JSON `attempts`（必須為非零 int） | `{success:true}` | `{success:false, error:'Invalid attempts'}` 400；非 JSON → Flask 415/400 | **寫檔** `LEADERBOARD_FILE`（append 一筆 `{name: session.user.name 或 'User', attempts, date}`，整檔重寫，無鎖） |

`LEADERBOARD_FILE = os.path.join(dirname(__file__), '..', '..', '..', 'data', '1a2b_leaderboard.json')` → 解析為 **`<專案根>/data/1a2b_leaderboard.json`**（`app/routes/games` 往上三層是專案根）。見已知問題。

### H. 靜態圖檔

| 方法 | 路徑 | endpoint | 權限 | 輸入 | 成功回應 | 失敗回應 | 副作用 |
|---|---|---|---|---|---|---|---|
| GET | `/ov_plot/<path:filename>` | `planners.serve_ov_plot` | 公開 | path | 圖檔 | `..` 或開頭 `/` → 400；不存在 → 404 | 讀 `app/routes/planners/ov_plot/` |

---

## 導向與流程（使用者從哪裡進來、成功/失敗去哪裡）

### 流程 1：紅移 / 座標 / 日期換算
1. navbar Tools → Astronomy Tools（`/astronomy_tools`）。
2. 填 z（+ m）→ Calculate → `POST /calculate_redshift`（+ `POST /calculate_absolute_magnitude`）→ 結果在同頁 `#combined-result`；錯誤顯示 `.error-message`。
3. 齒輪/chip → Cosmology Modal → Apply → 若已有結果自動重算。
4. 卡片可跳到 LC Plotter 或 ETC。

### 流程 2：Observation Planner（ACP 腳本）
1. 直接輸入 `/observation_planner`（無選單）。
2. Fetch Follow-up Targets → `GET /astronomy_tools/get_followup_targets`（DB `status='Follow-up'`）→ 表格；或 Add Manual Target；Fetch Custom Targets 會失敗（端點不存在）。
3. Generate Script → `POST /astronomy_tools/generate_script` → 腳本進 textarea；再 `POST /generate_plot`（固定鹿林座標）→ `/ov_plot/<file>.jpg` 顯示；產圖失敗不阻擋腳本顯示（只 `console.error`）。
4. Copy → 剪貼簿。

### 流程 3：Interactive Visibility Planner
1. navbar Planners → Visibility Plot；或 marshal 物件頁「visibility」連結帶 `?object_name&ra&dec` 進入自動填表並計算。
2. 任何欄位變更 600 ms 後 `POST /api/visibility_data` → Plotly 重繪（桌機）＋ Moon Info / Target Details（含手機）。失敗 → `#plot-status` 顯示錯誤（桌機）。
3. DB 搜尋 → `GET /api/target_autocomplete` → 選取加入列。
4. Generate Static Plot → `POST /generate_plot` → `#static-plot-img` 與下載連結（`/ov_plot/...`）；失敗 → status + `alert`。

### 流程 4：Finding Chart
1. navbar Planners → Finding Chart；或 marshal 物件頁帶 `?object_name&ra&dec&survey=DSS2+Red&fov=13&show_stars=0&auto=1` 自動產圖。
2. Generate → `POST /api/finding_chart`（10–30 s）→ 顯示 base64 PNG，日誌面板顯示 `logs`；失敗 → status 紅字 + `[ERROR]` 日誌。
3. Download PNG（前端）／Download FITS → `POST /api/finding_chart/fits` → blob 下載；失敗讀 JSON `error`/`logs`。

### 流程 5：LC Plotter 與分享
1. Tools → LC Plotter。上傳檔 → 自動偵測欄位 → Render。
2. MW Extinction → Auto-fill → `POST /lc_plotter/mw_extinction`。
3. Share → Modal（密碼）→ `POST /lc_plotter/share` → 新分頁 `/lc_plotter/shared/<id>`；有密碼者先看到密碼表單（POST 同 URL），正確 → 302 回 GET 顯示圖；錯誤 → 同頁紅字；過期 → 410；壞 id → 404。
4. 分享頁「← LC Plotter」回 `/lc_plotter`。

### 流程 6：Exposure Time Calculator
1. Tools → Exposure Time Calculator。載入即 `GET /api/exposure_time_calculator/presets`，套用 `lulin` profile 的第一個 Telescope/Camera/Filter（LOT + Sophia + Sloan_r）。
2. 改欄位（只更新 UI 與 specs 卡片）→ 按 EXECUTE → `POST /api/exposure_time_calculator`；若 Sweep 開啟再 `POST .../batch` 畫 Observing Window。驗證錯誤顯示於 `#error-box`（400 的 `error` 字串）。
3. SAVE/LOAD 以 JSON 對話框存取（不經後端）。

### 流程 7：Telescope Simulator / Mount Torque / Mount 3D
- Tools → Telescope Simulator（Aladin Lite 直連 CDS）；頁內按鈕 → `/mount_torque`。`/mount_3d` 僅 URL 直達。皆不呼叫 Kinder 後端。

### 流程 8：公開 REST API
- 外部程式直接呼叫 `/api/...`；`/api` 為文件頁（無站內入口）。`/api/objects/<name>?api_key=` 取得私有光度/光譜。

### 流程 9：Games
- Tools → Games；猜中 → `POST /api/games/leaderboard` → `GET /api/games/leaderboard` 更新排行榜。

### 流程 10（跨章）：Daily Trigger（private_area）
- `daily_trigger.js` 呼叫本章的 `/api/visibility_data`、`/generate_plot`、`/astronomy_tools/generate_trigger_script`；這三個端點本身公開，不檢查 GREAT_Lab 身分。

---

## 依賴的模組、資料表、檔案與外部服務

### Python 模組（`app/modules`）

| 模組 | 使用的函式 | 用途 |
|---|---|---|
| `astronomy_calculator.py` | `calculate_redshift_distance(redshift, redshift_error=None, H0=67.7, Om0=0.309, Tcmb0=2.725)`、`calculate_absolute_magnitude(apparent_magnitude, redshift, extinction=0, H0, Om0, Tcmb0)` | 距離、絕對星等（含 k 修正 `2.5 log10(1+z)`） |
| `date_converter.py` | `convert_mjd_to_date(mjd)`、`convert_jd_to_date(jd)`、`convert_common_date_to_jd(common_date)`（`MJD_OFFSET=2400000.5`；`datetime.fromisoformat`） | 日期換算 |
| `coordinate_converter.py` | `convert_ra_hms_to_decimal`、`convert_ra_decimal_to_hms`（`% 360`）、`convert_dec_dms_to_decimal`、`convert_dec_decimal_to_dms`（範圍檢查，`ValueError`） | 座標換算；也被 `observation_script`、`api_public_object` 用 |
| `request_validation.py` | `get_int_arg(name, default, min_val=-999999, max_val=999999)`、`get_float_arg(...)`、`ParamOutOfRangeError(ValueError)` | 公開 API query 參數驗證 |
| `ext_M_calculator.py` | `get_extinction(ra, dec, filter_name)`（re-export 自 `app/modules/DETECT/function/module/calculator.py`；SFD98 E(B-V) × SF11 比值；塵埃圖存 `DETECT_DATA_DIR`） | LC Plotter 銀河消光 |
| `filter_colors.py` | `all_colors()`（讀 `app/data/filter_colors.json`，import 時載入一次） | LC Plotter 濾鏡顏色 |
| `obsplan.py`（Phil Cigan obsplanning 改寫） | `create_ephem_observer(namestring, longitude, latitude, elevation, decimal_format='deg', timezone=None)`、`create_ephem_target(namestring, RA, DEC, decimal_format='deg')`、`dt_naive_to_dt_aware(datetime_naive, local_timezone)`、`plot_night_observing_tracks(target_list, observer, obsstart, obsend, ..., toptime='local', timezone='auto', n_steps=1000, simpletracks=False, ..., savepath='', showplot=False)`、`compute_moonphase(obstime, return_fmt='percent')`、`calculate_twilight_times(obsframe, startdate, verbose=False)`、`calculate_moon_times(observer, startdate, outtype='dt')`、`calculate_transit_time_single(target, observer, approximate_time, mode='nearest', return_fmt='str')`、`moonsep_single(target, observer, obstime)`、`get_timezone_name(offset)`（-12..12 → tz 名稱，否則 `None`） | 可見度計算與靜態軌跡圖 |
| `observation_script.py` | `get_followup_targets_json()`、`process_observation_request(data)` → `generate_single_script(name, ra, dec, mag, priority, is_lot='False', Repeat=0, auto_exp=True, filter_input, exp_time, count, info)`；`exposure_time(mag)` 星等→曝光表；`check_filter` / `check_filter_LOT` 濾鏡全名 | ACP 腳本 |
| `trigger_script.py` | `generate_full_script(targets, telescope)` → `generate_script(name, ra, dec, mag, priority, priority_message, is_lot, Repeat, auto_exp, filter_input, exp_time, count)`；`TARGET_SEPARATOR` | Daily Trigger 腳本 |
| `database/__init__.py` | `get_tns_db_connection()`（池化連線，需 `conn.close()`）、`OBJECT_COMPAT_COLS`（`transient.objects` 相容欄位別名，如 `o.dec AS declination`、`o.report_group AS reporting_group`） | 直接 SQL |
| `database/transient.py` | `search_tns_objects(search_term, limit, ...)`、`TNSObjectDB.get_photometry(name)`、`TNSObjectDB.get_spectrum_list(name)` | 目標搜尋、光度、光譜 |
| `database/auth.py` | `get_user_by_api_key(api_key)`、`filter_by_source_permissions(object_name, data_type, source_list, user_email, user_groups, is_admin)` | API key 與來源權限 |
| CASTOR（`app/modules/CASTOR/src`，git clone） | `castor.schema.ObservationRequest` / `BatchObservationRequest`（pydantic，`extra="forbid"`）、`castor.calculator.run_calculation`、`castor.batch_calculator.run_batch_calculation` | ETC 引擎；README 指出以 `git -C app/modules/CASTOR pull` 更新 |

### 第三方 Python 套件
`ephem`、`pytz`、`numpy`、`matplotlib`（Agg）、`PIL`、`requests`、`astropy`（`SkyCoord`、`units`、`io.fits`、`wcs`、`visualization`）、`astroquery`（`Vizier`、`Simbad`）、`scipy.ndimage.rotate`、`werkzeug.security`、`pydantic`（CASTOR）。

### 資料表（PostgreSQL）

| 表 | 讀/寫 | 使用處 |
|---|---|---|
| `transient.objects` | 讀 | `get_followup_targets_json`（`status='Follow-up'`）、`search_tns_objects`（autocomplete、fallback 搜尋）、`_db_lookup_coords`、`api_public_object`（`OBJECT_COMPAT_COLS`，`ILIKE`） |
| `transient.photometry` | 讀 | `TNSObjectDB.get_photometry`（`api_key` 模式） |
| `transient.spectroscopy` | 讀 | `TNSObjectDB.get_spectrum_list`（`api_key` 模式） |
| `transient.object_source_permissions`、`transient.default_permissions`、`auth.groups` | 讀 | `filter_by_source_permissions` |
| `auth.users` | 讀 | `get_user_by_api_key`；全域 `refresh_user_session` |

本章 **不寫入任何資料表**。

### 檔案系統

| 路徑 | 讀/寫 | 說明 |
|---|---|---|
| `app/routes/planners/ov_plot/observing_tracks_<uuid>.jpg` | 寫（`/generate_plot`）、讀（`/ov_plot/<f>`）、刪（`enforce_max_files` 保留最新 10 個） | `.gitignore` 已忽略 `app/routes/planners/ov_plot/*`；全站共用 |
| `app/data/shared_plots/<24hex>.json` | 寫（`/lc_plotter/share`）、讀（`/lc_plotter/shared/<id>`） | `app/data/` 已 gitignore；無自動清理 |
| `<專案根>/data/1a2b_leaderboard.json` | 讀/寫（games） | 見已知問題（路徑疑似錯誤，且未被 gitignore） |
| `app/modules/CASTOR/src/castorGUI/data/presets.json` | 讀 | ETC presets |
| `app/routes/astronomy_tools/templates/castor_etc_body.html` | 讀（每次 GET `/exposure_time_calculator` 以 `open()` 讀） | 注入模板 |
| `app/data/filter_colors.json` | 讀（import 時） | LC Plotter |
| `DETECT_DATA_DIR`（預設 `app/modules/DETECT/data`） | 讀/首次下載 | SFD 塵埃圖 |
| 系統暫存目錄 `*.jpg` | 寫後刪 | `/api/visibility/image` |

### 外部服務（後端發出的 HTTP）

| 服務 | URL | 使用端點 |
|---|---|---|
| STScI DSS | `https://archive.stsci.edu/cgi-bin/dss_search?v=<poss2ukstu_red / poss2ukstu_blue / poss2ukstu_ir / poss1_red>&r=&d=&e=J2000&h=&w=&f=fits&c=gz` | finding chart（DSS*） |
| DESI Legacy Survey DR10 | `https://www.legacysurvey.org/viewer/cutout.jpg` / `cutout.fits?layer=ls-dr10&size=900&pixscale=...&bands=` | finding chart（DESI-*） |
| Pan-STARRS PS1 | `https://ps1images.stsci.edu/cgi-bin/ps1filenames.py`、`fitscut.cgi` | finding chart（PS1-*） |
| VizieR（astroquery） | 目錄 `I/259/tyc2`（Tycho-2）、`I/322A`（UCAC4） | 星點標註 |
| SIMBAD（astroquery，`TIMEOUT=25`） | `query_region` | 星名 |
| CDS Sesame（`SkyCoord.from_name`） | — | 僅給名稱不給座標時 |
| IERS | 已在 `main.py` 關閉自動下載 | CASTOR |

### 前端 CDN
Plotly 2.35.2（`cdn.plot.ly`，含 SRI）：lc_plotter、shared_plot、exposure_time_calculator、interactive_planner；jQuery 3.6.0（code.jquery.com）與 Aladin Lite v3（aladin.cds.unistra.fr）：telescope_simulator；Google Fonts（Inter、JetBrains Mono）：多數頁面。

---

## 前端檔案

### 模板

| 檔案 | 使用的 route | 備註 |
|---|---|---|
| `app/routes/astronomy_tools/templates/astronomy_tools.html` | `/astronomy_tools` | |
| `app/routes/astronomy_tools/templates/api_docs.html` | `/api` | 樣式 inline，JS inline（`toggleCard`、`copyCode`） |
| `app/routes/astronomy_tools/templates/castor_etc_body.html` | `/exposure_time_calculator`（以文字注入） | 來自 CASTOR `src/castorGUI/frontend`，含 Kinder 特有 `#btn-execute` |
| `app/routes/astronomy_tools/templates/exposure_time_calculator.html` | `/exposure_time_calculator` | |
| `app/routes/astronomy_tools/templates/lc_plotter.html` | `/lc_plotter` | |
| `app/routes/astronomy_tools/templates/mount_3d.html` | `/mount_3d` | |
| `app/routes/astronomy_tools/templates/mount_torque.html` | `/mount_torque` | CSS/JS 全 inline |
| `app/routes/astronomy_tools/templates/shared_plot.html` | `/lc_plotter/shared/<id>` | 無 navbar；JS inline |
| `app/routes/astronomy_tools/templates/telescope_simulator.html` | `/telescope_simulator` | |
| `app/routes/planners/templates/observation_planner.html` | `/observation_planner` | route 在 astronomy_tools |
| `app/routes/planners/templates/interactive_planner.html` | `/interactive_planner` | JS inline；route 在 astronomy_tools |
| `app/routes/planners/templates/finding_chart.html` | `/finding_chart` | JS inline；route 在 astronomy_tools |
| `app/routes/games/templates/games.html` | `/games` | |
| （共用）`app/routes/basic/templates/_navbar.html`、`_favicon.html` | 所有頁面 include | |

### CSS（僅列檔名）
`app/routes/astronomy_tools/static/css/`：`astronomy_tools.css`、`etc.css`、`lc_plotter.css`、`mount_3d.css`、`telescope_simulator_main.css`
`app/routes/planners/static/css/`：`finding_chart.css`、`interactive_planner.css`、`observation_planner.css`、`observation_planner_extra.css`
`app/routes/games/static/css/`：`games.css`
圖片：`astronomy_tools/static/photo/background.jpg`、`background_telescope.jpg`、`background_telescope_1.png`；`planners/static/photo/background_observation.png`、`background_planner.jpg`；`games/static/photo/background_games.jpg`

### JS 與其呼叫的 API

| 檔案 | 呼叫的 API（方法 路徑 → 主要參數） |
|---|---|
| `astronomy_tools/static/js/astronomy_tools.js`（544 行） | `POST /calculate_redshift` {redshift, redshift_error?, H0, Om0, Tcmb0}；`POST /calculate_absolute_magnitude` {apparent_magnitude, redshift, extinction, H0, Om0, Tcmb0}；`POST /convert_date` {mjd 或 jd 或 common_date}；`POST /convert_ra` {ra_hms 或 ra_decimal}；`POST /convert_dec` {dec_dms 或 dec_decimal} |
| `astronomy_tools/static/js/etc.js`（1419 行） | `GET CONFIG.presetsUrl`（= `/api/exposure_time_calculator/presets`）；`POST CONFIG.apiUrl`（= `/api/exposure_time_calculator`，body 由表單 `name` 組成的 `ObservationRequest`，去掉 `batch.*`）；`POST CONFIG.batchUrl`（= `/api/exposure_time_calculator/batch`，body 為 `BatchObservationRequest`，`environment` 由 `batch.start_time_utc/end_time_utc/time_step_minutes` + 單點環境欄位拼成） |
| `astronomy_tools/static/js/lc_plotter.js`（1503 行） | `POST /lc_plotter/mw_extinction` {ra, dec, filters[]}；`POST /lc_plotter/share` {traces, layout, isStatic, password}；開啟 `/lc_plotter/shared/<id>` |
| `astronomy_tools/static/js/mount_3d.js`（592 行） | 無 |
| `astronomy_tools/static/js/telescope_simulator.js`（953 行） | 無 Kinder API（Aladin Lite → CDS） |
| `planners/static/js/observation_planner.js`（408 行） | `GET /astronomy_tools/get_followup_targets`；`GET /api/custom_targets`（**不存在**）；`POST /astronomy_tools/generate_script` {settings{IS_LOT, send_to_control_room}, targets[...]}；`POST /generate_plot` {date, telescope, location:"120.873611 23.468611 2862", timezone:"8", targets[{object_name, ra, dec}]} |
| `planners/templates/interactive_planner.html`（inline） | `POST /api/visibility_data` {date, location, timezone, telescope, targets[{name, ra, dec}]}；`POST /generate_plot`；`GET /api/target_autocomplete?q=` |
| `planners/templates/finding_chart.html`（inline） | `POST /api/finding_chart` {name, ra, dec, survey, fov, invert, mag_limit, name_limit, show_mag, show_names, max_stars, show_slit, slit_pa, slit_width, slit_length}；`POST /api/finding_chart/fits`（同 payload）；`GET /api/target_autocomplete?q=` |
| `astronomy_tools/templates/shared_plot.html`（inline） | 無（POST 表單 `password` 至同 URL） |
| `astronomy_tools/templates/api_docs.html`（inline） | 無 |
| `games/static/js/games.js`（149 行） | `GET /api/games/leaderboard`；`POST /api/games/leaderboard` {attempts} |

---

## api_docs.html 宣稱 vs 實際 route 逐一比對

| 文件宣稱 | 實際 | 判定 |
|---|---|---|
| Base URL 框：「`success: true/false` is always present」 | 公開 API 的錯誤回應只有 `{error: ...}`（無 `success`）；`/api/finding_chart/image`、`/api/visibility/image` 的錯誤是 text/plain；`ParamOutOfRangeError` 回 `{error}` | **不一致** |
| Authentication 框：Authenticated API 可用 `X-API-Key` 標頭**或** `?api_key=` | `/api/test`（web_api）**只讀標頭**，缺標頭回 401「Missing API Key in headers」；`/api/v1/observation_targets`、`/api/v1/observation_logs` 兩者皆可；`/api/objects/<name>` **只讀 query**，不讀標頭 | **不一致**（各端點行為不同，文件一概而論） |
| 「Generate your key from the account settings page」 | `/api/generate_key`（`api` 與 `web_api` 兩個 blueprint 各註冊一次）皆回 403「Self-service key generation is disabled」 | **不一致**（需 admin 核發） |
| Public API「1 req/s per IP per endpoint」 | `/api/finding_chart/surveys`、`/api` 無限制；image 端點 30 s / 15 s（卡片內有註明） | 部分不一致 |
| `GET /api/distance` 參數與範例 | 參數一致；範例回應 `cosmology` 少了實際會回的 `reference` 欄位 | 小差異 |
| `GET /api/coords` 範例回應 | 實際多 `ra_hours`、`source` | 小差異 |
| `GET /api/date` 範例 `common_date: "2020-08-02 12:00:00 UTC"` | 實際無 " UTC" 後綴，且多 `source` 欄位 | 小差異 |
| `GET /api/finding_chart/image` 參數表 | 少列了實際支援的 `name_limit`（預設 10）；其餘（obj_name、ra、dec、name、survey、fov、invert、mag_limit、show_mag、show_names）一致 | 小差異 |
| `GET /api/visibility/image`：`tz` 「−12 to +14」 | `get_timezone_name` 只支援 -12..12，13/14 → 400 | **不一致** |
| `GET /api/objects/{name}`：photometry 範例含 `is_upper_limit` | `get_photometry` 回 `id, object_name, mjd, magnitude, magnitude_error, filter, telescope`，無 `is_upper_limit` | **不一致** |
| `GET /api/objects/{name}`：spectra 範例 `{source, mjd, label}` | 實際欄位 `telescope, observation_mjd, min_wavelength, max_wavelength, point_count, observation_row_id, phase, spectrum_id, spectrum_label, observation_date_label` | **不一致** |
| `GET /api/objects/{name}` Python 範例用 `https://your-domain.com` | 其他範例用 `https://kinder.astro.ncu.edu.tw` | 文件不一致 |
| `GET /api/test`、`/api/v1/observation_targets`、`/api/v1/observation_logs` | 存在於 `web_api_bp`（他章） | 一致（存在） |
| `GET /api/finding_chart/surveys`（僅以連結提及） | 存在 | 一致 |
| JSON 版 `_API_DOCS`（`GET /api?format=json`） | 只列 6 個端點；未列 `/api/finding_chart/surveys`、`/api/test`、`/api/v1/*`；finding_chart/image 與 visibility/image 未列 `obj_name`、`name_limit` | 與 HTML 版**不同步** |
| 未在任何文件出現但存在的 `/api/*`：`/api/target_autocomplete`、`/api/visibility_data`、`POST /api/finding_chart`、`/api/finding_chart/fits`、`/api/exposure_time_calculator*`、`/api/games/leaderboard` | 內部用途 | 未文件化（可接受，但皆公開可呼叫） |

---

## 已知問題與注意事項

### 前端呼叫但後端不存在的端點
1. **`GET /api/custom_targets`**（`observation_planner.js` `fetchCustomTargets()`，「Fetch Custom Targets」按鈕）：全 app 無此 route（`grep custom_targets` 只命中該 JS）。按下後永遠 `alert('Error fetching custom targets')`。

### 路徑 / 註冊相關
2. 本章內無重複註冊；跨章：`/api/generate_key` 同時由 `api_blueprint`（`url_prefix='/api'`）與 `web_api_bp` 註冊（兩者皆回 403），Flask 依註冊順序以 `api` 版本生效。`/api/objects`（web_api，GET/POST）與 `/api/objects/<path:object_name>`（本章 GET）路徑不衝突，但 `<path:>` 會吃掉含 `/` 的名稱。
3. 頁面孤島：`/observation_planner`、`/mount_3d`、`/api`（文件頁）沒有站內入口；navbar 對 `/observation_planner` 仍做 active 判斷。
4. 靜態檔服務以「第一個命中的 blueprint 目錄」為準（`_BLUEPRINT_STATIC_DIRS`），同名檔會互相遮蔽；planners 的 CSS/JS 靠此機制被找到。

### 死程式碼 / 無效邏輯
5. `astronomy_tools.js`：`calculateDistance()`、`calculateMagnitude()`、`showDistanceResult()`、`showMagnitudeOnlyResult()` 無任何呼叫者（HTML 只用 `calculateBoth()`）；`hideLoading()` 是空函式；全域 `keypress` Enter 處理器以 `.input-section`、`#date-grid`、`.coordinate-section` 尋找區塊，這些 selector 在 `astronomy_tools.html` 都不存在（實際 class 為 `.settings-section`/`.at-tool-grid`），結果是 **Enter 被 `preventDefault()` 吞掉而什麼都不做**。
6. `telescope_simulator.js`：`gotoObject()`、`toggleCard()`、`autoUpdateFOV()` 未被 HTML 使用；`changeSurvey()` 的 `#surveySelect` fallback 元素不存在。
7. `lc_plotter.js`：`collectSettings()`/`_applySettingsUI()` 列出 `magErrCol`，HTML 無此元素（安全略過）；HTML 中「Extinction A」欄位（`#lcExtinction`）已註解，`getDistanceModulus()` 固定傳 0。
8. `observation_script.get_followup_targets_json` 回傳的 `settings.IS_LOT` 寫死 `"True"`，前端因此每次 Fetch 都把望遠鏡切回 LOT。
9. `exposure_time_calculator` route 註解宣稱 `castor_etc_body.html` 與 CASTOR repo「byte-for-byte identical」，但該檔案自身註解與 `etc.js` 都標明 `#btn-execute`/EXECUTE 是「Kinder-specific deviation」——若日後真的 verbatim 覆蓋，Execute 按鈕會消失且 `etc.js` 的 `el('btn-execute')` 會拋錯。

### 資料檔路徑
10. **Games 排行榜路徑疑似錯誤**：`LEADERBOARD_FILE` 解析為 `<專案根>/data/1a2b_leaderboard.json`（往上三層），但現況專案根沒有 `data/`，而 `app/data/1a2b_leaderboard.json`（2026-03-17，128 bytes）存在——後者與本章其他資料（`shared_plots`、`filter_colors.json`）同在 `app/data/`。結果：GET 回 `[]`；第一次 POST 會在專案根建立 `data/`（**未被 `.gitignore` 涵蓋**，`.gitignore` 只排除 `app/data/`）。

### 安全 / 資源
11. `_client_ip()` 直接信任 `X-Forwarded-For`，而 `ProxyFix` 只設 `x_proto=1, x_host=1`（未設 `x_for`）；直接連到後端者可偽造標頭繞過所有 `/api/*` 速率限制。
12. `POST /lc_plotter/share`：無登入、無速率限制，每次最多 8 MiB 寫入 `app/data/shared_plots/`；過期檔案只在被存取時回 410，**沒有任何清理排程**（目前 10 個檔）。
13. `POST /api/finding_chart`、`/api/finding_chart/fits`、`/api/visibility_data`、`/generate_plot`、ETC 端點皆無速率限制，卻會觸發外部 HTTP（DSS/DESI/PS1/VizieR/SIMBAD，timeout 45 s）或 matplotlib/astropy 重運算。
14. `/generate_plot` 的 `enforce_max_files` 在寫入前才清到 10 個（實際最多 11 個檔案，與目前目錄內 11 個相符），任何使用者都可能把別人的 `plot_url` 擠掉（private_area 已為此在送 Slack 前重新產圖）。
15. `api_public_object` / `_db_lookup_coords` 以 `ILIKE %s` 直接比對使用者輸入：參數化故無注入，但 `%`、`_` 會被當萬用字元（`/api/objects/%` 會回傳任意第一筆物件）。
16. `/astronomy_tools/get_followup_targets`（Follow-up 清單含座標與星等）與 `/astronomy_tools/generate_trigger_script` 是公開端點，雖主要由 GREAT_Lab 專用的 Daily Trigger 頁使用。
17. Games：`attempts` 由前端計算後直接採信（可任意 POST 1 次成績）；JSON 檔讀改寫無鎖；`get_leaderboard` 對缺 `attempts` 鍵的紀錄會 500；`generateSecret()` 把答案 `console.log` 出來。
18. `/api/target_autocomplete` 把所有例外吞成 `[]` 200，DB 故障時前端只會看到「No results found」。

### 回應格式不一致
19. `/api/finding_chart/image`、`/api/visibility/image` 的錯誤為 text/plain，但 `fov`/`mag_limit`/`name_limit`/`alt`/`tz` 非數字時由全域 handler 回 JSON 400。
20. `/api/visibility_data` 對 `n_steps` 非整數回 500 而非 400；`/convert_date` 的 `if mjd:` 使 `mjd=0`/`jd=0` 被視為未提供。
21. `/api/coords` 同時給 RA 與 Dec 時 `source` 欄位被後者覆蓋。

### 其他
22. `interactive_planner.html`、`finding_chart.html` 的 `<html lang="zh-TW">` 但內容全英文；`mount_torque.html` 的 `<title>` 為 "Harmonic Analyzer v6.0 (Physics Engine)"（無 "Kinder" 字樣）。
23. 程式碼中沒有 `TODO`/`FIXME`/`XXX`/`HACK` 標記（已 grep 本章三個 blueprint 的 py/js/html）。
24. `refresh_user_session` 對每個非 `/static` 請求（含公開 API）在登入狀態下都做一次 `auth.users` 查詢。
