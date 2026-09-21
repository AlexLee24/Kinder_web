# DETECT 篩選/審核頁與 Planners 靜態圖（detect / planners blueprints）

> **注意**：本章記錄的是重構前（commit `c7f91a4`，2026-09-21）的狀態，檔案路徑為舊位置（`app/routes/…`、`app/modules/…`）。新位置請對照 `docs/ARCHITECTURE.md` §6「新舊路徑對照」；功能與行為在重構後完全相同。

## 概要

**負責範圍**

- `app/routes/detect/detect_routes.py`（blueprint 名稱 `detect`，無 `url_prefix`，`template_folder='templates'`，`static_folder='static'`）：DETECT 每日 TNS 暫現源 vs. DESI/Lens 星系目錄交叉比對結果的「首頁 / 審核頁 / 封存頁」，以及審核動作 API（設定 host、撤回、標記無 host、改物件狀態、旗標）、追蹤器與光變曲線 API、頁面快取狀態 API、DETECT 圖檔輸出。
- `app/routes/planners/planners_routes.py`（blueprint 名稱 `planners`，無 `url_prefix`）：只有一條 route `/ov_plot/<path:filename>`，用來輸出觀測規劃（Observation Planner）產生的夜間可見度軌跡圖。blueprint 本身的主要目的是讓 `planners/templates/`（`finding_chart.html`、`observation_planner.html`、`interactive_planner.html`）與 `planners/static/` 可被 Flask 找到；這些頁面與 API 實際由 `astronomy_tools_routes.py` 處理（屬其他章節）。

**對應網站頁面**

| 頁面 | 路徑 | 說明 |
|---|---|---|
| DETECT 首頁 | `GET /detect`（無參數） | 最新一次 run 的統計、最高優先物件、各日期結果入口、Pipeline 說明、圖例 |
| DETECT 審核頁 | `GET /detect?detect_results=<YYYY-MM-DD>` | 某一天的審核佇列（摘要表 + 逐張卡片），一鍵決策 |
| DETECT 載入頁 | 同上（快取尚未建好時） | 輪詢 `/api/detect/cache_status`，建好後自動跳轉 |
| DETECT 封存頁 | `GET /detect/archives` | 所有日期的結果按鈕清單，可用文字過濾 |
| OV plot 靜態圖 | `GET /ov_plot/<filename>` | 觀測規劃器產生的 `observing_tracks_<uuid>.jpg` |

**與其他區塊的關係**

- 資料來源全部由 **DETECT pipeline**（`app/modules/DETECT/`，經 `app/modules/detect_pipeline.py` 包裝）寫入：`transient.cross_matches`（候選星系，每列一筆）、`transient.detect_screen`（每物件一筆的判定：`host_status`、`score`、`tags`、M、z…）、`transient.target_images`（LS DR10 finder）。本章節的 route **只讀** 這些表，僅在審核動作時寫回 `cross_matches.is_host / match_data / flag` 與 `objects.status / redshift`。
- Pipeline 的觸發點在其他章節：`modules/auto_tns_download.py`（每小時 TNS 匯入後跑 `detect_pipeline.run_for_names`）、`main.py` 排程（每日 04:00 `detect_pipeline.run_followups`）、`POST /admin/detect-run`（admin 手動）、`GET /api/object/<name>/detect_cross_match`（物件頁 Run 按鈕，`detect_pipeline.run_single`）。這四處跑完後都會回頭呼叫本檔的 `_soft_invalidate_page_cache()`。
- 物件頁（marshal `objects_bp`，`/object/<name>`）的 DETECT 分頁用本章的 `GET /detect_image_by_id/<id>` 顯示 finder chart（`image_id` 來自 web_api 的 `detect_cross_match` 回傳 `detect_image_id`）。
- 審核頁「Fetch LC」按鈕先呼叫 web_api 的 `POST /api/object/<name>/fetch_photometry`，再呼叫本章的 lightcurve API。
- 導覽列（`routes/basic/templates/_navbar.html`）在「Private」下拉（僅 `session.user.is_great_lab_member` 顯示）放 `url_for('detect.detect_results')`；首頁 `routes/basic/templates/home.html` 也有兩處連到 `detect.detect_results`；admin 面板 JS（`routes/auth/static/js/admin.js`）有 `/detect` 連結。
- `main.py` 排程 `detect_page_prewarm`（每 30 分鐘）與啟動時各呼叫一次本檔的 `prewarm_detect_page_cache()`。
- `/ov_plot/` 的圖由 `astronomy_tools.generate_plot`（`POST /generate_plot`）產生。

---

## 頁面（HTML routes）

### `/detect`（無 query string）— DETECT 首頁模式

| 項目 | 內容 |
|---|---|
| 路徑 / 方法 | `GET /detect` |
| endpoint | `detect.detect_results`（同一個 view function 依 `detect_results` 參數分三種模式） |
| 權限 | 需登入且非 guest。未登入 → `flash('Please log in to access Detect Results.', 'warning')` 後 `redirect(url_for('basic.login'))`；`role == 'guest'` 且非 `is_admin` → `flash('Access denied. This page is not available for Guest users.', 'error')` 後 `redirect(url_for('basic.home'))`。（程式中同一個 guest 判斷的 `elif` 重複寫了兩次，第二個永遠不會執行。） |
| 模板 | `detect_home.html` |
| 模板變數 | `latest_date`（`get_detect_metadata()['available_dates'][0]`，來自 `cross_matches.updated_date` 的最大日期，或 `None`）、`daily_counts`（list，每項 `{date, count, has_lens, screen}`，`screen` 為 `{confirmed, review, none, total, last_run}` 或 `None`）、`overview`（`get_detect_overview()` → `{last_run, run_day, counts:{confirmed,review,none,total}, pending, top:[detect_screen 列]}`，60 秒快取）、`current_path='/detect'` |
| 副作用 | 讀 `transient.cross_matches`、`transient.detect_screen`、`transient.objects`（皆經由 `get_detect_metadata`（120 秒模組級快取）與 `get_detect_overview`）。若 `latest_date` 存在且頁面快取沒有該日 payload 且未在建置中，**啟動背景執行緒** `_start_detect_page_build(latest_date)` 預建審核頁。 |

**頁面區塊與互動**（`detect_home.html`，CSS `css/detect_home.css`，無專屬 JS）

| 區塊 | 內容 | 導向 |
|---|---|---|
| 標題 + lead | 「DETECT — Daily Transient Event Cross-matching Tool」說明文字，「review page」連結 | `url_for('detect.detect_results', detect_results=latest_date)` → `/detect?detect_results=<latest_date>`；無日期時為 `#` |
| Latest run（`overview-section`） | `overview.last_run` 時間、`counts.total` objects screened；四個統計連結（need judgement / confirmed host / no host / waiting for a person，數值分別為 `c.review`、`c.confirmed`、`c.none`、`overview.pending`）；「Highest priority right now」表格（`overview.top` 最多 8 筆：Object / Score / Host badge / M / z / Tags） | 四個統計皆連到 `/detect?detect_results=<overview.run_day>`（注意 `run_day` 取自 `detect_screen.run_date`，`latest_date` 取自 `cross_matches.updated_date`，兩者可能不同日）；物件名連 `/object/<name>` |
| Results（`results-section`） | 「Latest · `<date>`」大按鈕（`daily_counts[0]`，顯示 `count` with candidates、`screen.total` screened、三個 host-status 小徽章、`LENS MATCH!`）；「Recent」格狀按鈕（`daily_counts[1:9]`）；超過 9 天時顯示「All Archives」 | 每個按鈕 → `/detect?detect_results=<date>`；`count == 0` 的按鈕 `href="#"` 並 `onclick="alert('No targets matched on this day.'); return false;"`；All Archives → `url_for('detect.detect_archives')` |
| Pipeline（七步流程說明） | 純說明文字（TNS ingest → Targets → HEALPix cross-match → Host rule v1 DLR → Screening & score → Image & upload → Review on Kinder），每步有 `<details>` | 第 7 步「Open the queue →」→ `/detect?detect_results=<latest_date>` |
| How to read it（三張 legend 卡） | Host status 圖例（`host_badge` macro）、Tags 圖例（`tag_chip` macro，依 tag 名稱分 `tag-hot / tag-cool / tag-veto / tag-warn`）、Decisions 快捷鍵說明（F/D/N/R/←/→/U） | 無 |

### `/detect?detect_results=<date>` — 審核模式

| 項目 | 內容 |
|---|---|
| 路徑 / 方法 | `GET /detect?detect_results=<YYYY-MM-DD>` |
| endpoint | `detect.detect_results` |
| 權限 | 同首頁模式 |
| 輸入 | query `detect_results`（字串，不做格式驗證；任何非空字串都會當作日期去查 `updated_date::date = %s`，格式錯誤時 SQL 例外被 `get_detect_page_data` 吞掉並回 `{}`，頁面會顯示「No cross-match candidates on <date>」） |
| 模板 | 快取中有 payload（新鮮或過期皆可）→ `detect_results.html`，以 `render_template('detect_results.html', **payload)`；否則 → 載入模式（見下） |
| 模板變數（payload，由 `_assemble_detect_payload(selected_date)` 產生） | `results`（審核佇列，list of target dict，見下方欄位）、`summary_results`（**模板與 JS 都未使用**）、`cards_data`（JSON-safe 精簡版，**模板與 JS 都未使用**）、`none_list`（當天有 `detect_screen` 列但沒有任何 cross_match 候選、且發現日期在 60 天內的物件）、`old_list`（同上但發現超過 60 天，視為 TNS 修改舊報告）、`unmatched_recent_days`（常數 `UNMATCHED_RECENT_DAYS = 60`）、`counts`（`{targets, pending, review, confirmed, nohost, followup, done, screened, unmatched, old, last_run}`）、`current_path='/detect'`、`available_dates`、`daily_counts`（**模板未使用**）、`selected_date` |
| `results[i]` 欄位 | `target_name, id(best_match.id), tns_info{discoverydate, internal_names, ra, dec, type, tns_z}, matches[], best_match, host_match, is_flagged, flag_id, is_host, target_is_host, host_match_id, host_pinned, host_rejected, obj_status, host_status, score, screen(_screen_public), verdict{kind, headline, hint}, wake_note{at, fields, source}|None, z, abs_mag, hypothetical` |
| `matches[j]` 欄位 | cross_matches 列（`id, target_name, catalog_name, separation_arcsec, is_host, created_at, status, flag, z, match_data(dict), match_ra, match_dec`）加上 `tns_info, abs_mag, is_flagged, flag_id, rule(_match_rule)` |
| 副作用 | 讀快取；若快取過期（`built_at` 超過 `DETECT_PAGE_CACHE_TTL_SEC`，預設 600 秒）→ 先回舊 payload、同時**啟動背景重建執行緒**（stale-while-revalidate）。log `[DETECT] serving cached payload date=… fresh=…`。 |

**排序規則**（`final_target_list.sort`）：先未結案（`obj_status` 不在 `finished/snoozed`）→ 非 `followup` → `host_status` 依 `_HOST_STATUS_ORDER = {review:0, confirmed:1, none:2, unscreened:3}` → `score` 高者先 → 名稱。`none_list` 依 score 降冪；`old_list` 依 discoverydate 降冪。

**頁面區塊與互動**（`detect_results.html` + `js/detect_results.js`；CSS `css/marshal/marshal.css` + `css/detect_results.css`；Plotly 2.35.2 由 CDN `defer` 載入）

`<body data-can-edit>`：模板變數 `can_edit = session.user and session.user.is_admin` → JS 常數 `CAN_EDIT`。**只有 admin 看得到 ★ 欄、決策按鈕、Set host 按鈕與 F/D/N/R 快捷鍵**；非 admin 的 action bar 顯示「Sign in as an admin to review.」（但後端 API 只要求非 guest，見已知問題）。

| 區塊 | 元件 | 行為 / 呼叫 |
|---|---|---|
| 頁首 `detect-page-header` | 標題「DETECT」連結、`selected_date`、`counts.last_run`；`<select id="dateSelect" onchange="changeDate(this)">`（`available_dates`）；「Follow-up Tracker」按鈕（`toggleTracker()`，徽章 `#trackerCountBadge`）；「? How to review」（`toggleGuide()`） | 標題 → `url_for('detect.detect_results')` = `/detect`；換日期 → `window.location.href = '/detect?detect_results=<date>'`（空值 → `/detect`） |
| How to review `#reviewGuide` | 三步說明；開合狀態存 `localStorage['detect.guide']`（首次預設開啟） | 無 |
| Follow-up Tracker 面板 `#followupTrackerPanel` | 預設收合；開啟時 `loadTracker(false)`；↺ `loadTracker(true)`；✕ 收合。表格欄：Object / Score / Host / Tags / M / z / Catalog / Sep / Discovery / DETECT run | `GET /api/detect/followup_tracker`（頁面載入時也先打一次只為徽章數字；回 `building:true` 且空清單時每 3 秒重試）；物件名 → `/object/<name>`（新分頁） |
| Day at a glance `#dayStats` | `counts.screened / targets / pending(#statPending) / review / confirmed / nohost / followup(#statFollowup) / done(#statDone) / old` | 決策成功後 JS `_bumpStat` 就地增減 pending/followup/done |
| Review queue 過濾列 | All / Pending / Needs judgement / Confirmed host / No host / Follow-up / Done（`filterSummary(btn, filter)`，依 `tr[data-status]`、`tr[data-host-status]` 顯示/隱藏） | 純前端 |
| 摘要表 `#summaryTable` | 每列 `id="summary-row-<name>"`、`data-card-index / data-status / data-host-status / data-has-host`，點列 `jumpToCard(i)`；欄：★（admin，`toggleFlag(flag_id, this)`）/ Object / Type / Score chip / Host badge（`host-cell-<name>`）/ DETECT's verdict headline（+ wake chip）/ Tags / z（`hypothetical` 時標「if host」，`z_source=='tns'` 標「tns」）/ M（`render_abs_mag`）/ Status（`status-cell-<name>`）/ → | ★ → `POST /api/toggle_flag`；物件名 → `/object/<name>`；→ → 捲到 `#cardNavBar` 並顯示該卡 |
| Cards 導覽列 `#cardNavBar` | ← Prev / `n / total` + 物件名 / Next pending → (`nextUnreviewed`，找 `data-status == 'object'` 的下一張) / Next → / ↺（`location.reload()`） | 鍵盤：`←` `→` 移動、`U` 下一張 pending、`?` 開合說明、`Esc` 關燈箱、`F/D/N/R`（需 `CAN_EDIT`） |
| 卡片 `#card-<i>`（一次只顯示一張，其餘 `display:none`） | `data-name / data-status / data-host-status / data-host-match-id / data-host-z / data-host-pinned / data-host-rejected / data-verdict-kind`（**JS 狀態機完全以這些 data-* 為準**） | — |
| ‑ 卡片標題列 | 物件名（新分頁 → `/object/<name>`）、score chip、Type badge；meta：Discovery / Coords / Internal / TNS z / DETECT run / wake chip；右側狀態徽章 `#card-status-<name>` | — |
| ‑ Verdict band `#verdict-<name>` | host badge、`verdict.headline`、`verdict.hint`（`#verdict-hint-<name>`，pickHost 後改文字）；facts：M（附 `abs_mag_band`、peak/discovery 來源）、z（來源 DESI host / TNS / candidate #1）、fade（`decline_rate`，Kilonova? 時高亮，附 KN envelope 比數）、d_DLR（+ 角距、kpc）、Host（`spectype`、morph、log M*、W1−W2、fibre only）、tags | — |
| ‑ Action bar `#actions-<name>`（JS `_renderCard` 依狀態產生） | 非 admin：提示文字。已結案（`snoozed/finished`）：「Closed with host accepted / Closed as no host（— your decision）」+ ↺ Reopen。`followup`：「In follow-up …」+ ✓ Done + ↺ Reopen。pending：依 `pinned / hostId+hs=='confirmed' / hostId / hs=='review' / else` 給引導句 + ★ Follow-up `F` + ✓ Done `D` + ✗ No host `N` | Follow-up → `decideFollowup`；Done → `decideDone`；No host → `decideNoHost`；Reopen → `decideReopen`（各自呼叫的 API 見下方「審核動作」） |
| ‑ 影像欄 | `<img src|data-src="/detect_image/<name>" class="lazy-img" onclick="openImgModal(this)">`（第一張直接載入，其餘顯示時才把 `data-src` 搬到 `src`，含 spinner）；載入失敗 → 「Image unavailable」 | `GET /detect_image/<name>`；點圖開 `#imgModal` 燈箱（點背景或 ✕ 或 Esc 關閉） |
| ‑ 光變曲線欄 | 「Fetch LC」`fetchCardLightcurve`、「Refresh LC」`refreshCardLightcurve`、狀態字 `#lc-status-<i>`、Plotly div `#plotly-card-<i>`；顯示卡片時自動 `_autoFetchLC`（前端 `_lcCache` Map 先查） | 自動/Refresh → `GET /api/detect/lightcurve/<name>`（Refresh 加 `?refresh=1`）；Fetch LC → `POST /api/object/<name>/fetch_photometry`（web_api）成功後再 `GET …/lightcurve/<name>?refresh=1`；換卡片時 `Plotly.purge` 舊圖 |
| ‑ 候選表 `match-detail-table` | 每列 `data-match-id / data-match-z / data-match-catalog / data-target-name / data-is-host / data-rule-kind / data-rule-rank / data-host-user / data-host-user-by`；欄：Rule chip（`rule.label` + ambiguous / z-conflict 註記）/ Source（catalog + EDR）/ Spectrum（spectype、survey/program、zwarn、grade、P(lens)）/ z / Sep / d_DLR / limit（顏色 `dlr-in / dlr-tent / dlr-out`）/ M(z) / Galaxy（morph、log M*、r、W1−W2、WISE AGN、fibre only、shape source）/ Action（JS 產生） | Action：是 host → 「✓ HOST（· you）」徽章；admin 且未結案 → 「Set host」按鈕（`pickHost(name, matchId, z)`；無 host 時 `tentative/member` 或 rank 2 的 member 以 `btn-prominent` 突顯） |
| No host 摺疊區 `unmatched-section` | `none_list` 表（Object / Type / Discovery / Score / Tags / z (TNS) / M / Status），無 `results` 時預設展開 | 物件名 → `/object/<name>` |
| Old edits 摺疊區 `unmatched-old` | `old_list` 同欄位 | 同上 |
| 其他 | `#backToTopBtn`（捲動 >300px 顯示）、`#toast`（2.6 秒訊息）、`.card-busy-overlay`（送出中的遮罩） | — |

**JS 決策函式與 API 對應**（`detect_results.js`）

| 動作（鍵） | 函式 | 呼叫 | 成功後前端狀態 |
|---|---|---|---|
| Follow-up（F） | `decideFollowup(name)` → `_decide(name,'followup')` | 卡片有 `hostMatchId` 且 `hostPinned != 'true'` → `POST /api/set_host {match_id, target_name, redshift: data-host-z 或 null, status:'followup'}`；否則 → `POST /api/set_object_status {target_name, status:'followup'}` | `hostPinned='true'`、`_markPinnedRow`、`_applyStatus(card,'followup')`、toast |
| Done（D） | `decideDone(name)` → `_decide(name,'snoozed')` | 同上但 `status:'snoozed'`（**Done = DB 的 `Snoozed`，不是 `Finish`**） | 同上；350 ms 後自動 `nextUnreviewed()` |
| No host（N） | `decideNoHost(name)` | `POST /api/mark_no_host {target_name}` | 清 `hostMatchId/hostZ`、`hostRejected='true'`、所有候選列 `isHost=false, hostUser=false`（`ruleKind` host→member）、`_applyStatus(card,'snoozed')`、自動下一張 |
| Reopen（R） | `decideReopen(name)` | `POST /api/unset_host {target_name}`（若已是 pending 且未 pinned/rejected → 只 toast） | `hostPinned/hostRejected='false'`、候選列 `hostUser=''`、`_applyStatus(card,'object')` |
| Set host（按鈕） | `pickHost(name, matchId, z)` | `POST /api/set_host {match_id, target_name, redshift: z 或 null, status:'keep'}` | `hostMatchId=matchId`、`hostZ`、`hostPinned='true'`、`hostRejected='false'`、候選列 is-host/host-user 重設、hint 改為「Host chosen by you. Now Follow-up (F) or Done (D).」 |
| ★ 旗標 | `toggleFlag(id, el)` | `POST /api/toggle_flag {id, flag: !active}` | 切換 `.active` |

`_applyStatus` 同步更新卡片 `data-status`、摘要列 `data-status/data-has-host`、兩處狀態徽章（`_statusBadge`：`snoozed/finished` → 有 host「✓ Done」否則「✗ No host」；`followup` → 「⬤ Follow-up」；其餘「Pending」）、統計數字，並重繪 action bar 與候選列 Action 欄。

### `/detect?detect_results=<date>` — 載入模式（快取未就緒）

| 項目 | 內容 |
|---|---|
| 條件 | `_get_detect_page_payload_swr(selected_date)` 回 `None`（該日從未建過或已被 LRU 淘汰）。route 會先 `_start_detect_page_build(selected_date)`（若未在建置中）再渲染此頁 |
| 模板 | `detect_results_loading.html` |
| 模板變數 | `selected_date`、`available_dates`（**模板未使用**）、`current_path='/detect'` |
| 頁面 | 卡片「Preparing DETECT Results」+ spinner；inline script 立即並每 1.5 秒 `fetch('/api/detect/cache_status?detect_results=<date>')`，`data.success && data.ready` 時 `window.location.replace('/detect?detect_results=<date>')` |
| CSS | `css/marshal/marshal.css`、`css/detect_results.css` + inline style |

### `/detect/archives` — 封存頁

| 項目 | 內容 |
|---|---|
| 路徑 / 方法 | `GET /detect/archives` |
| endpoint | `detect.detect_archives` |
| 權限 | 需登入且非 guest。未登入 → `flash('Please log in to access Detect Archives.', 'warning')` → `redirect(url_for('basic.login'))`；guest → `flash('Access denied. This page is not available for Guest users.', 'error')` → `redirect(url_for('basic.home'))` |
| 模板 / 變數 | `detect_archives.html`；`daily_counts`（`get_detect_metadata()['daily_counts']`，包含 `cross_matches` 最早到最晚日期之間**每一天**，含 0 筆的日子）、`current_path='/detect/archives'` |
| 頁面區塊 | 標題；`<input id="dateFilter">` 文字過濾（inline script，依 `a.archive-btn[data-date]` 的子字串比對顯示/隱藏）；`#archiveGrid` 格狀按鈕（日期、`count` targets、`🔭 LENS` 小徽章）；無資料時「No Archives Available」 |
| 導向 | 按鈕 → `/detect?detect_results=<date>`；`count == 0` → `href="#"` + alert |
| 副作用 | 只讀（`get_detect_metadata`，120 秒快取） |

---

## API 與動作端點

所有 detect API 的權限判斷都是直接讀 `session['user']`（沒有 decorator）。「需登入且非 guest」的實作是：`'user' not in session` → 401；`session['user'].get('role','guest') == 'guest' and not session['user'].get('is_admin')` → 401。POST 端點用 `request.json`（body 非 JSON 時 Flask 會直接丟 415/400 的 HTML 錯誤，不是 JSON）。

| 方法 | 路徑 | endpoint | 權限 | 輸入 | 成功回應 | 失敗回應 | 副作用 |
|---|---|---|---|---|---|---|---|
| GET | `/detect_image/<target_name>` | `detect.detect_image` | 需登入且非 guest（未通過 → 純文字 `"Unauthorized"` 401） | path `target_name` | `send_file(BytesIO, mimetype='image/png', download_name='<name>_marked.png')` | 無圖 → 純文字 `"Image not found"` 404 | 讀 `transient.target_images` JOIN `transient.objects`（`get_target_image`，取該物件任一列 LIMIT 1） |
| GET | `/detect_image_by_id/<int:image_id>` | `detect.detect_image_by_id` | **需登入即可（guest 也可）**；未登入 → `"Unauthorized"` 401 | path `image_id` int | PNG（`send_file`，無 download_name） | `"Image not found"` 404 | 讀 `transient.target_images WHERE image_id` |
| POST | `/api/set_host` | `detect.set_host` | 需登入且非 guest → `{"success":false,"message":"Unauthorized"}` 401 | JSON `match_id`（必填）、`target_name`（必填）、`redshift`（可選，`_parse_float_or_none`）、`status`（預設 `'followup'`；必須為 `followup`/`snoozed`/`keep`） | `{"success":true}`；若 `redshift` 無法解析 → `{"success":true,"message":"Host set, but no redshift to update"}` | 缺參數 → `{"success":false,"message":"Missing parameters"}` 200；status 不合法 → `{"success":false,"message":"Invalid status"}` 200；`set_cross_match_host` 失敗 → `{"success":false,"message":"Database error"}` 200 | 寫 `transient.cross_matches`（全物件列 `is_host=FALSE` + `match_data ||= {host_user:false, host_user_by:<email>, host_user_at}`；指定 `match_id` 列 `is_host=TRUE` + `{host_user:true,…}`）；`status != 'keep'` 時 `update_object_status` → `transient.objects.status`（`followup`→`Follow-up`、`snoozed`→`Snoozed`）；`_soft_invalidate_page_cache()`；`_TRACKER_CACHE['expires_at']=0` + `_start_tracker_build()`（背景執行緒）；有 z 時 `set_object_redshift` → `transient.objects.redshift = z`（不重算 abs mag） |
| POST | `/api/unset_host` | `detect.unset_host` | 需登入且非 guest → JSON 401 | JSON `target_name`（必填） | `{"success":true}` | 缺參數 → `{"success":false,"message":"Missing parameters"}`；`release_cross_match_host` 失敗 → `{"success":false,"message":"Database error"}` | 寫 `transient.cross_matches.match_data`（移除 `host_user/host_user_by/host_user_at`，**`is_host` 不動**）；`update_object_status(target,'object')` → `objects.status='Inbox'`；頁面快取 soft-invalidate；tracker 失效 + 背景重建 |
| GET | `/api/get_object_status` | `detect.get_object_status_api` | **需登入即可（guest 也可）**；未登入 → `{"success":false}` 401 | query `name`（strip 後必填） | `{"success":true,"obj_status":"object|followup|finished|snoozed"}`（DB 值經 `_NORM` 正規化，未知值取小寫，空值 → `object`） | 缺 name → `{"success":false,"message":"Missing name"}` 200 | 讀 `transient.objects`（`tns_object_db.get_object_details`）。**前端沒有任何地方呼叫此端點。** |
| POST | `/api/set_object_status` | `detect.set_object_status` | 需登入且非 guest → JSON 401 | JSON `target_name`（必填）、`status` ∈ `finished`/`followup`/`object`/`snoozed` | `{"success":true}` | 參數缺/不合法 → `{"success":false,"message":"Missing or invalid parameters"}`；DB 失敗或無列更新 → `{"success":false,"message":"Database error"}` | `update_object_status` → `transient.objects.status`（`_STATUS_MAP`：`finished`→`Finish`、`followup`→`Follow-up`、`object`→`Inbox`、`snoozed`→`Snoozed`；比對 `name = %s OR name ILIKE %s OR (name_prefix||name) ILIKE %s`）；頁面快取 soft-invalidate；tracker 失效 + 重建 |
| POST | `/api/mark_no_host` | `detect.mark_no_host` | 需登入且非 guest → JSON 401 | JSON `target_name`（必填） | `{"success":true}` | 缺參數 → `{"success":false,"message":"Missing parameters"}`；`update_object_status` 失敗 → `{"success":false,"message":"Database error"}` | `reject_cross_match_hosts`（全物件列 `is_host=FALSE` + `match_data ||= {host_user:false, host_user_by, host_user_at}`；**回傳值被忽略**）；`update_object_status(target,'snoozed')` → `objects.status='Snoozed'`；頁面快取 soft-invalidate；tracker 失效 + 重建 |
| GET | `/detect` | `detect.detect_results` | 需登入且非 guest（redirect + flash，見頁面章節） | query `detect_results`（可選） | 三種模式的 HTML | — | 見頁面章節；可能啟動背景建置執行緒 |
| GET | `/api/detect/followup_tracker` | `detect.followup_tracker_api` | 需登入且非 guest → `{"success":false}` 401 | 無 | 有快取（新鮮或過期）→ `{"success":true,"tracker":[…],"cached":true,"fresh":bool}`；冷快取 → `{"success":true,"tracker":[],"cached":false,"building":true,"message":"Building tracker, please retry shortly."}` | — | 讀 `_TRACKER_CACHE`；過期或冷快取時 `_start_tracker_build()`（背景執行緒；`get_followup_objects_for_tracking` 讀 `transient.objects`（`status='Follow-up'`）LEFT JOIN `cross_matches`（`is_host=TRUE`）LEFT JOIN `detect_screen`；濾掉 `Finish`；排序 score 降冪、再 abs_mag）；TTL `DETECT_TRACKER_CACHE_TTL`（預設 300 秒） |
| GET | `/api/detect/cache_status` | `detect.detect_cache_status_api` | 需登入且非 guest → `{"success":false,"message":"Unauthorized"}` 401 | query `detect_results`（strip 後必填） | `{"success":true,"ready":bool,"fresh":bool,"building":bool}` | 缺日期 → `{"success":false,"message":"Missing detect_results date"}` 400 | 若 payload 不存在且未在建置 → `_start_detect_page_build`（背景執行緒）；payload 過期時 SWR 也會觸發重建；log `[DETECT-CACHE] cache-status …` |
| GET | `/api/detect/lightcurve/<path:target_name>` | `detect.detect_lightcurve_api` | 需登入且非 guest → JSON 401 | path `target_name`（`urllib.parse.unquote` + strip）、query `refresh`（`1/true/yes` 強制重算） | 有光度資料 → `{"success":true,"plot_json":"<Plotly fig.to_json()>","data_count":n,"cached":bool}`；無資料 → `{"success":true,"plot_json":null,"data_count":0,"message":"No photometry data available","cached":bool}` | 空名稱 → `{"success":false,"message":"Missing target name"}` 400；例外 → `{"success":false,"message":"<str(e)>"}` 500 | 讀 `_DETECT_LC_CACHE`（LRU，上限 `DETECT_LC_CACHE_MAX_SIZE`=300，**無 TTL**）；miss 時 `get_detect_lc_data`（1 連線讀 `transient.objects` + `transient.photometry`，排除 `mag < 0`）→ `DataVisualization.create_photometry_plot_from_db(photometry, z, ra, dec, as_json=True)`（Plotly 圖，含消光/K 修正需要 ra/dec/z）→ 寫入快取；log `[DETECT-CACHE] lc-hit/lc-miss/lc-build-complete` |
| GET | `/detect/archives` | `detect.detect_archives` | 需登入且非 guest（redirect + flash） | 無 | `detect_archives.html` | — | 讀 `get_detect_metadata` |
| POST | `/api/toggle_flag` | `detect.toggle_flag` | 需登入且非 guest → JSON 401（guest 判斷同樣重複兩次） | JSON `id`（cross_matches.match_id）、`flag`（bool）；**無型別驗證** | `{"success":true}` | `{"success":false,"message":"Database error"}` 200 | `update_cross_match_flag`：先 `ALTER TABLE transient.cross_matches ADD COLUMN IF NOT EXISTS flag BOOLEAN DEFAULT FALSE`（每次都執行）再 `UPDATE … SET flag=%s WHERE match_id=%s`；**rowcount 不檢查，不存在的 id 也回 success**；**不會** soft-invalidate 頁面快取 |
| GET | `/ov_plot/<path:filename>` | `planners.serve_ov_plot` | **公開**（無任何登入檢查） | path `filename` | `send_from_directory(app/routes/planners/ov_plot, filename)`（JPEG） | `filename` 含 `..` 或以 `/` 開頭 → `abort(400)`；檔案不存在 → 404（`send_from_directory` 的 NotFound） | 讀檔案 `app/routes/planners/ov_plot/<filename>`。圖檔由 `astronomy_tools.generate_plot`（`POST /generate_plot`）以 `obs.plot_night_observing_tracks(..., savepath=…/ov_plot/observing_tracks_<uuid4 hex>.jpg)` 產生；每次產生前 `enforce_max_files(folder, max_files=10)` 會依 mtime 刪掉最舊的檔，使目錄最多保留 10 張（目前目錄有 11 個檔）。因此舊的 `plot_url` 在產生超過 10 張新圖後會變成 404。 |

**route 總數：14**（`detect` 13 條 + `planners` 1 條）。另外 Flask 因兩個 blueprint 都宣告 `static_folder='static'` 且無 `url_prefix`，會自動註冊 `detect.static` / `planners.static`（`/static/<path:filename>`），但 `main.py` 先以 `endpoint='static'` 註冊了自己的 `/static/<path:filename>`（依序搜尋 `routes/basic、auth、astronomy_tools、marshal、detect、games、private_area、planners、web_api` 的 `static/`），模板一律用 `url_for('static', …)`，所以實際由 `main.py` 的合併處理器服務。

### 補充細節

**`_assemble_detect_payload(selected_date)` 的資料流**（在背景執行緒、`app.app_context()` 內執行）

1. `get_detect_metadata()`（120 秒模組級快取）：`available_dates`（`SELECT DISTINCT updated_date::date FROM transient.cross_matches`）、`daily_counts`（`generate_series` 全日期 + `COUNT(DISTINCT obj_id)` + `has_lens`（`catalog LIKE 'Lens_%'`））、`screen_counts[date]`（`detect_screen` 依 `run_date::date, host_status` 計數與 `MAX(run_date)`）。
2. `get_detect_page_data(date)`（單一連線）：`_ensure_cross_matches_flag_column`（DDL）→ `cross_matches WHERE updated_date::date = date`（欄位別名 `match_id AS id, name AS target_name, catalog AS catalog_name, separation AS separation_arcsec, redshift AS z, …`）→ `objects` 批次明細 → `photometry` 每物件最新一點（`DISTINCT ON`）→ `detect_screen`（`screen_batch` 為有候選的物件、`screen_only` 為當天 run 但沒有候選的物件）→ `tns_update_audit`（30 天內 `changed_fields` 含 `woke:%` 的最新一筆，作為 `wake_notes`）。
3. 以 `target_name` 分組，`match_data` 由字串轉 dict；每列算 `rule = _match_rule(match_data, is_host)`；候選 z 依序取 `cross_matches.redshift`，否則 `match_data` 的 `Z/z/redshift/z(s)/z_spec/z_phot/z_lens`。
4. 每物件的視星等：`screen.peak_mag`（+`peak_filter`）優先，否則最新光度點，否則 TNS `discoverymag`（濾鏡預設 `V`）；`get_extinction(ra, dec, filter)`（SFD 塵埃圖，首次使用會下載到 `DETECT_DATA_DIR`）；每候選 `abs_mag = apm_to_abm(m, z, A)`（`z <= 0` 或缺值 → `None`；`apm_to_abm` 回傳 dict 代表錯誤，視為 `None`）。host 列若沒算出 M 但 `screen.abs_mag` 有值則沿用。
5. 候選排序 `{'host':0,'shred':1,'member':2,'tentative':3,'outside':4,'lens':5,'nomodel':6}` → `rule.rank` → 角距。`best_match = host_match or processed_matches[0]`。
6. 組 `target_obj`、`verdict = _detect_verdict(screen_raw, matches, host_match)`、`host_status`、`hypothetical`（無 host、`screen.z` 為空但候選 #1 有 z：畫面上的 z/M 是「假設 #1 是 host」）。
7. 佇列排序、`summary_results`、`none_list/old_list`（以 `discoverydate >= now-60d` 分流）、`counts`、`cards_data`；log `[DETECT-BUILD] date=… timings…`。

**`_screen_public(s)`**：把 `detect_screen` 列縮成頁面用的固定 key 集合 `_SCREEN_KEYS`（`score, host_status, tags(去掉 Host-* 開頭), abs_mag, abs_mag_band, abs_mag_source, abs_mag_discovery, peak_mag, peak_filter, peak_mjd, peak_source, n_phot, z, z_source, d_dlr, center_sep_arcsec, offset_kpc, host, host_user, host_user_by, morph, mass_cg, sfr_cg, known_galactic, known_agn, tns_type, lens_match, star_sep, decline_rate, decline_filter, decline_days, kn_model_in, kn_model_n, run_date`），多數來自 `detect_screen.flags` JSON。無列時全部 `None`（`score=0, tags=[], lens_match=0`）。

---

## DETECT 頁面上的概念

### `host_status`（物件層級，DETECT 的 host 判定）

| 值 | 來源 | 意義 / 頁面呈現 |
|---|---|---|
| `confirmed` | `transient.detect_screen.host_status` | 一個星系含有該暫現源且無爭議 → 「● Confirmed host」，`verdict.kind='confirmed'` |
| `review` | 同上 | 規則無法定案（ambiguous / z-conflict / tentative）→ 「? Needs judgement」，`verdict.kind='review'`，排在佇列最前 |
| `none` | 同上（或列存在但欄位空） | 沒有光譜星系包含它 → 「○ No host」 |
| `unscreened` | **頁面推導**：該物件在 `cross_matches` 有候選列但 `detect_screen` 沒有列 | 「· Not screened」：`is_host` 來自 marshal 舊版自動比對（`modules/detect_cross_match.run_all_detect`，已被 pipeline 取代），`verdict.kind='unscreened'` |

`_HOST_STATUS_ORDER = {review:0, confirmed:1, none:2, unscreened:3}` 決定佇列順序；`detect_home.html` 的 `host_badge` macro 沒有 `unscreened` 分支（顯示成 No host）。

### `rule.kind`（候選列層級，`_match_rule(match_data, is_host)`，讀 `cross_matches.match_data` JSON）

| kind | 判定條件（依序） | label |
|---|---|---|
| `host` | `match_data.host_user is True`（reviewer 選的）或 `is_host` 為真 | `HOST · chosen by <host_user_by>` / `HOST · rule v1` |
| `shred` | `shares_host_galaxy` 為真 | `part of the host galaxy` |
| `member` | `host_member` 為真 | `member #<host_rank>` |
| `tentative` | `host_tentative` 為真 | `tentative (just outside the limit)` |
| `outside` | `d_dlr` 與 `d_dlr_max` 都有值 | `outside (> 2×d_dlr_max d_DLR)` |
| `lens` | `origin_catalog_name` 非空，或 `match_data` 有 `z_lens` / `lens_probability` | `lens catalogue` |
| `nomodel` | 其餘 | `no galaxy model` |

`rule` 其他欄位：`rank(host_rank)、d_dlr、d_dlr_max、ambiguous(ambiguous_host)、z_conflict(host_z_conflict)、spectype、morph(tractor_type|morphtype)、survey、program、zwarn、release(data_release)、mag_r、logmass(log10 mass_cg)、w1w2(w1_w2_vega)、wise_agn(wise_agn_stern12)、fibre_only(ls_photometry is False)、center_sep(center_sep_arcsec)、offset_kpc、shape_source、host_user、host_user_by`。

### `verdict`（`_detect_verdict(screen, matches, host_match)` → `{kind, headline, hint}`）

| kind | 條件 |
|---|---|
| `unscreened` | `screen is None` |
| `user` | host 列 `rule.host_user is True`（「Host chosen by …」），或無 host 且任一列 `host_user is False`（「Marked as no host by …」） |
| `confirmed` | `host_status == 'confirmed'` 且有 host 列 |
| `review` | `host_status == 'review'`：依序判斷 host 列 `z_conflict`（列出衝突 z）→ `ambiguous`（比較 #1 與 rank 2 的 d_DLR）→ `flags.host_tentative` 或任一列 kind `tentative` → 通用「could not settle」 |
| `none` | 其餘：有候選 → 「N spectrum(s) within the search radius but none contains the transient, nearest d_DLR …」；無候選 → 「No spectroscopic galaxy near the transient.」 |

### `score`

`detect_screen.score`（int，pipeline 計算：Galactic −10、AGN −10、Classified −6、Star? −3；host +3(+2)、Luminous +3、SLSN? +1、TDE? +2、Too-bright +3、Lens +2、glSN? +3(+2)、Kilonova? +3，見首頁 Pipeline 第 5 步）。頁面 chip：`>=7` hi、`>=3` mid、`>=0` lo、`<0` neg。佇列與 tracker 皆以 score 降冪。

### `flag`

`transient.cross_matches.flag`（boolean，欄位由 `_ensure_cross_matches_flag_column` 動態新增）。摘要表 ★ 欄（admin 才顯示）切換的是 `t.flag_id` = `best_match.id`（host 列，否則排序後第一列）。只做標記，不影響狀態、排序或快取。

### `obj_status`（`transient.objects.status`）

DB 值 `Inbox / Follow-up / Finish / Snoozed` ↔ 頁面值 `object / followup / finished / snoozed`（`_STATUS_NORM`；反向 `transient._STATUS_MAP` 另接受 `clear`→`Inbox` 與 DB 原值）。頁面把 `finished` 與 `snoozed` 一律視為「已結案（Done）」：有 host 顯示「✓ Done」，無 host 顯示「✗ No host」。

### 審核動作 → 寫入對照

| 動作（UI） | API | `transient.cross_matches` | `transient.objects` | 其他 |
|---|---|---|---|---|
| Set host（候選列按鈕） | `POST /api/set_host` `status='keep'` | 全部列 `is_host=FALSE`、`match_data ||= {host_user:false, host_user_by, host_user_at}`；選定列 `is_host=TRUE`、`{host_user:true,…}`（`set_cross_match_host`） | `redshift = <該列 z>`（`set_object_redshift`，有 z 時） | 頁面快取 soft-invalidate；tracker 重建 |
| Follow-up（F）/ Done（D），卡片有 host 且尚未 pinned | `POST /api/set_host` `status='followup'|'snoozed'` | 同上（**接受規則的 host 也會記成 reviewer 選的**） | `status='Follow-up'` / `'Snoozed'`（`update_object_status`）+ `redshift` | 同上 |
| Follow-up / Done，無 host 或已 pinned | `POST /api/set_object_status` | 不動 | `status='Follow-up'` / `'Snoozed'` | 同上 |
| No host（N） | `POST /api/mark_no_host` | 全部列 `is_host=FALSE`、`{host_user:false,…}`（`reject_cross_match_hosts`） | `status='Snoozed'` | 同上 |
| Reopen（R） | `POST /api/unset_host` | 有 `host_user` 的列移除 `host_user/host_user_by/host_user_at`（`release_cross_match_host`；`is_host` 保留） | `status='Inbox'` | 同上 |
| ★ | `POST /api/toggle_flag` | 指定 `match_id` 的 `flag` | 不動 | 無快取失效 |

`match_data.host_user` 是 DETECT pipeline 每日重跑 Follow-up 時讀回的「人為決定」：`true` = 人選的 host（規則不覆蓋），`false` = 人拒絕的候選。`objects.status` 由 pipeline 永不更動。`objects.redshift` 另有每日 06:00 的 `sync_host_redshifts` 排程（`main.py`）會把所有 `is_host=TRUE` 列的 z 回寫。

---

## 頁面快取機制（`_DETECT_PAGE_CACHE` / `_DETECT_LC_CACHE` / `_TRACKER_CACHE`）

三個快取都是**每個 Python process 各自一份的記憶體物件**（`OrderedDict` / dict），共用同一把 `_DETECT_PAGE_CACHE_LOCK`（`threading.Lock`）。

**`_DETECT_PAGE_CACHE`（審核頁 payload，key = 日期字串）**

- 項目：`{'payload': dict, 'built_at': time.time()}`。環境變數：`DETECT_PAGE_CACHE_TTL_SEC`（預設 600 秒）、`DETECT_PAGE_CACHE_MAX_SIZE`（預設 8，LRU：`move_to_end` on hit，超量 `popitem(last=False)`，log `[DETECT-CACHE] page LRU evicted`）、`DETECT_PAGE_PREWARM_DAYS`（預設 3）。統計 `_DETECT_PAGE_CACHE_STATS{hits,misses,evictions}`，由 `_log_detect_cache_stats(context, …)` 以 `[DETECT-CACHE] <context> … page(hit=…%) lc(hit=…%)` 記錄。
- `_DETECT_PAGE_BUILDING`（set）記錄建置中的日期，避免同一日期重複開執行緒。
- `_start_detect_page_build(date, app_obj=None, force=False)`：非 force 且快取新鮮 → 不做事；標記建置中 → 開 daemon thread（`app_obj.app_context()` 內 `_assemble_detect_payload` → `_set_detect_page_cache`），失敗只寫 log `Background DETECT cache build failed`，finally 取消建置標記。
- `_get_detect_page_payload_swr(date)` → `(payload|None, is_fresh)`；過期則順手 `_start_detect_page_build`（stale-while-revalidate）。
- **`prewarm_detect_page_cache(prewarm_days=None, refresh_latest=True, force_latest=True, app_obj=None)`**：本身再開一個 daemon thread；取 `available_dates`，`refresh_latest` 時對最新日期 `force=force_latest` 重建，再對前 `prewarm_days` 天中不新鮮者啟動建置；log `[DETECT-PREWARM] queued=…`。回傳 `{'success': True, 'prewarm_days', 'refresh_latest', 'force_latest'}`。**呼叫者**：`app/main.py` — (1) APScheduler job `detect_page_prewarm`，`interval minutes=30`（只在非 DEBUG 且該 process 取得 `log/.background_jobs.lock` 檔鎖時註冊）；(2) 啟動時立即呼叫一次 `prewarm_detect_page_cache(prewarm_days=1, refresh_latest=True, force_latest=True, app_obj=app)`（非 DEBUG）。
- **`_soft_invalidate_page_cache()`**：把快取內所有日期的 `built_at` 設為 0（標記過期但保留舊 payload 可服務），再對每個日期 `_start_detect_page_build`；log `[DETECT-CACHE] page cache soft-invalidated for N dates`。**呼叫者**：本檔 `set_host`、`unset_host`、`set_object_status`、`mark_no_host`；`modules/auto_tns_download.py::_run_detect_after_import`（每小時/每日 TNS 匯入後跑完 embedded DETECT）；`routes/auth/admin_routes.py::detect_run`（`POST /admin/detect-run`，背景執行緒跑完 pipeline 後）；`routes/web_api/web_api_routes.py::trigger_detect_cross_match`（`GET /api/object/<name>/detect_cross_match` 執行 `detect_pipeline.run_single` 後）。三個外部呼叫都用 `try/except: pass` 包住 import。
- 首頁模式：若最新日期沒有 payload 且未在建置 → 啟動預建。審核模式：有 payload（不管新舊）→ 立即渲染；沒有 → 啟動建置並回 loading 頁，由 `/api/detect/cache_status` 輪詢。

**`_DETECT_LC_CACHE`（光變曲線 Plotly JSON，key = target_name）**

- LRU，上限 `DETECT_LC_CACHE_MAX_SIZE`（預設 300），**沒有 TTL**；只有 `?refresh=1`、LRU 淘汰或 process 重啟才會更新。前端另有 `_lcCache`（Map），Fetch/Refresh LC 時會先 `delete` 再帶 `refresh=1`。

**`_TRACKER_CACHE`（Follow-up tracker）**

- `{'expires_at', 'value'}`，TTL `DETECT_TRACKER_CACHE_TTL`（預設 300 秒）。`_start_tracker_build()` 背景重建（`_build_tracker_data`：`get_followup_objects_for_tracking` → 濾掉 `Finish` → 取 `match_z` 或 `objects.redshift` → 直接用 `detect_screen` 的 `abs_mag/score/host_status/tags/run_date`，不重算）；四個審核 API 都會 `expires_at=0` + 重建；冷快取回 `building:true`。

另有 `modules/database/transient.py` 內的 `_detect_metadata_cache`（120 秒）與 `_detect_overview_cache`（60 秒），**不受** `_soft_invalidate_page_cache` 影響。

---

## 導向與流程

**進入點**

- 導覽列 Private ▸ DETECT（僅 `is_great_lab_member`）→ `/detect`；首頁 `home.html` 兩處 DETECT 連結 → `/detect`；admin 面板 DETECT 卡片「review page」→ `/detect`。
- 未登入 → flash + `basic.login`；guest → flash + `basic.home`。

**首頁 → 審核頁**

1. `/detect` 首頁：點「review page」/「Open the queue」/ Latest 按鈕 / Recent 按鈕 / Latest run 統計 → `/detect?detect_results=<date>`；All Archives → `/detect/archives` → 任一日期按鈕 → `/detect?detect_results=<date>`。
2. 審核頁 route：快取命中 → 直接渲染；未命中 → loading 頁，每 1.5 秒查 `/api/detect/cache_status`，`ready` 後 `location.replace` 回同一 URL（此時快取已有 payload）。
3. 進入審核頁後：`DOMContentLoaded` → 所有卡片 `_renderCard`、讀 localStorage 決定 guide 開合、tracker 面板收合、`GET /api/detect/followup_tracker`（徽章）、`_showCard(0)`（載第一張圖、`GET /api/detect/lightcurve/<name>`）。

**審核一張卡片（admin）**

1. 讀 verdict band、看 LS DR10 圖（點圖放大）與光變曲線（必要時 Fetch LC：`POST /api/object/<name>/fetch_photometry` → `GET …/lightcurve?refresh=1`）。
2. 決策：
   - `F` / `D`：有 host 且未 pinned → `POST /api/set_host`（pin + 狀態 + z）；否則 `POST /api/set_object_status`。成功 → 卡片/摘要列/統計就地更新、toast；`D` 350 ms 後跳下一張 pending。失敗 → toast「Failed: <message>」。
   - `N` → `POST /api/mark_no_host` → 狀態 snoozed、候選列全部取消 host → 自動下一張。
   - `R` → `POST /api/unset_host` → 回 pending。
   - Set host → `POST /api/set_host status='keep'` → 卡片變 pinned，hint 提示按 F/D。
3. 後端每次成功變更都 soft-invalidate 頁面快取 + 重建 tracker；重新整理（↺）後會拿到新 payload（若背景重建已完成，否則拿到 `built_at=0` 的舊 payload 並再觸發重建）。
4. `←/→/U` 或摘要表點列切換卡片；換日期用 `<select>`；標題「DETECT」回首頁。

**物件頁與 DETECT 的交會**：卡片與表格的物件名都連 `/object/<name>`（marshal）；物件頁 DETECT 分頁以 `/detect_image_by_id/<id>` 取圖。

**OV plot**：使用者在 Observation Planner（`astronomy_tools` 章節）送出 `POST /generate_plot` → 伺服器寫 `ov_plot/observing_tracks_<uuid>.jpg`，回 `plot_url="/ov_plot/<file>"` → 前端 `<img>` 讀 `planners.serve_ov_plot`。

---

## 依賴的模組、資料表、檔案與外部服務

**Python 模組**

| 模組 | 用到的符號 | 用途 |
|---|---|---|
| `modules.database.transient` | `get_detect_metadata`、`get_detect_page_data`、`get_detect_lc_data`、`get_detect_overview`、`get_followup_objects_for_tracking`、`get_target_image`、`get_detect_image_by_id`、`set_cross_match_host`、`release_cross_match_host`、`reject_cross_match_hosts`、`update_object_status`、`set_object_redshift`、`update_cross_match_flag`、`tns_object_db.get_object_details` | 所有 DB 存取（`get_db_connection` 連線池）。另 import 但**未使用**：`get_cross_match_results`、`get_available_dates`、`get_daily_match_counts`、`update_tns_redshift`、`unset_cross_match_host`、`get_photometry_batch`、`get_object_details_batch`、`get_latest_photometry_for_names` |
| `modules.data_processing.DataVisualization` | `create_photometry_plot_from_db(photometry, redshift, ra, dec, as_json=True)` | 光變曲線 Plotly 圖（TNS 去重、消光、K 修正；`as_json=True` 回 `fig.to_json()` 字串） |
| `modules.ext_M_calculator` | `apm_to_abm(apparent_mag, redshift, extinction=0)`（回 float，錯誤時回 `{'error':…}` dict）、`get_extinction(ra, dec, filter_name)`（SFD98 × SF11） | 每候選 M(z)。此模組是 `app/modules/DETECT/function/module/calculator.py` 的 shim（Planck 2018 cosmology `cosmo`，SFD 塵埃圖存 `DETECT_DATA_DIR`） |
| `modules.detect_pipeline`（本檔不直接 import，但是資料的生產者） | `ENABLED`（`DETECT_IN_WEB` 非 `0/false/no/off`）、`run_for_names(names, label)`、`run_single(name)`、`run_followups()`、`run_recent(hours)`、`is_running()`、`status()`；全域 `_LOCK` 保證一次只跑一個 run，`_state{running,last}` 給 admin 面板 | 包裝 `app/modules/DETECT/function/run_detect.py` 的 `run_detect_for_names(names, group_name)`、`run_detect_single(name)`、`run_detect_followups()`、`run_detect_recent(hours)`（皆呼叫 `function.module.cross_match.run_cross_match_pipeline`，寫 `cross_matches`、`detect_screen`、`target_images`、`objects.tag/brightest_*`） |
| `modules.detect_cross_match` | `run_all_detect`（舊版最近鄰比對，docstring 註明已被 pipeline 取代）、`has_detect_run`、`get_detect_screen_for_target`、`get_detect_results_for_target`、`save_detect_results` | 本檔不使用；web_api 的 `detect_cross_match` 端點用它讀取結果。「unscreened」物件的 `is_host` 即來自這條舊路徑 |
| `flask` | `render_template, request, jsonify, flash, redirect, url_for, session, send_file, Blueprint, current_app` | — |
| 標準庫 | `threading`（背景建置）、`OrderedDict`（LRU）、`time`、`json`、`io`、`urllib.parse`、`math`、`datetime` | — |

**資料表**

| 表 | 讀 | 寫 |
|---|---|---|
| `transient.cross_matches`（`match_id, obj_id, name, catalog, separation, is_host, updated_date, status, flag, redshift, match_data(jsonb), match_ra, match_dec`） | 審核頁、metadata、tracker | `is_host`、`match_data`（`host_user*`）、`flag`；DDL `ADD COLUMN IF NOT EXISTS flag` |
| `transient.detect_screen`（`obj_id, name, score, host_status, tags, flags(jsonb), host_targetid, z, z_source, abs_mag*, peak_*, center_sep_arcsec, d_dlr, offset_kpc, run_date`） | 審核頁、首頁 overview、metadata、tracker | 無 |
| `transient.objects`（`name, name_prefix, ra, dec, discovery_date(MJD), internal_name, other_name, type, redshift, discovery_mag, discovery_filter, status, obj_id`） | 審核頁明細、LC、tracker、`get_object_status` | `status`、`redshift` |
| `transient.photometry`（`phot_id, obj_id, "MJD", mag, mag_err, filter, source`） | LC API、審核頁最新一點 | 無 |
| `transient.target_images`（`image_id, obj_id, name, image_data, source`） | 兩個圖片 route | 無 |
| `transient.tns_update_audit`（`name, changed_fields[], source, updated_at`） | 審核頁 wake notes | 無 |

**檔案**

- 讀：`app/routes/planners/ov_plot/*.jpg`（`serve_ov_plot`）；SFD 塵埃圖 `DETECT_DATA_DIR/dustmaps/sfd/*.fits`（`get_extinction`，首次會從網路下載約 130 MB）；`log/.background_jobs.lock`（`main.py` 決定誰跑 prewarm）。
- 寫：本章節的 route 不寫任何檔案（ov_plot 圖由 `astronomy_tools.generate_plot` 寫入並以 `enforce_max_files(…, 10)` 輪替）。

**外部服務**

- 瀏覽器端：`https://cdn.plot.ly/plotly-2.35.2.min.js`（帶 SRI）。
- 伺服器端：無直接外呼；間接：SFD 塵埃圖首次下載（dustmaps），`fetch_photometry`（web_api）會去 TNS 抓光度。

**環境變數**：`DETECT_PAGE_CACHE_TTL_SEC`、`DETECT_PAGE_CACHE_MAX_SIZE`、`DETECT_PAGE_PREWARM_DAYS`、`DETECT_LC_CACHE_MAX_SIZE`、`DETECT_TRACKER_CACHE_TTL`（以上僅在程式碼中出現，無 `.env` 範例或文件）；`DETECT_IN_WEB`、`DETECT_DATA_DIR`（pipeline）。

---

## 前端檔案

**模板（`app/routes/detect/templates/`）**

| 檔案 | 用於 | include / 外部 |
|---|---|---|
| `detect_home.html` | `/detect` 首頁 | `_favicon.html`、`_navbar.html`；CSS `css/detect_home.css`；無 JS（只有 `onclick alert`） |
| `detect_results.html` | `/detect?detect_results=` 審核頁 | `_favicon.html`、`_navbar.html`；CSS `css/marshal/marshal.css`、`css/detect_results.css`；Plotly CDN；JS `js/detect_results.js`；macro：`render_abs_mag`、`tag_chip`、`status_badge`、`wake_chip`、`host_badge` |
| `detect_results_loading.html` | 快取未就緒 | `_favicon.html`、`_navbar.html`；CSS 同上 + inline；inline 輪詢 script |
| `detect_archives.html` | `/detect/archives` | `_favicon.html`、`_navbar.html`；CSS `css/detect_home.css` + inline；inline 過濾 script |

**CSS（`app/routes/detect/static/css/`）**：`detect_home.css`（背景引用 `../photo/detect_background.jpg`）、`detect_results.css`（同樣引用該背景圖）、`detect_shared.css`（**未被任何模板引用**）。

**圖片（`app/routes/detect/static/photo/`）**：`detect_background.jpg`（約 25 MB，三個 CSS 都用作全頁背景）、`DETECT.png`（**未被引用**）。

**JS（`app/routes/detect/static/js/detect_results.js`）呼叫的 API**

| 呼叫 | 方法 | 所屬 blueprint |
|---|---|---|
| `/api/detect/followup_tracker` | GET | detect |
| `/api/detect/lightcurve/<name>[?refresh=1]` | GET | detect |
| `/api/object/<name>/fetch_photometry` | POST | web_api（`web_api.fetch_photometry`，需登入，跑 `process_single_object_workflow`） |
| `/api/toggle_flag` | POST | detect |
| `/api/set_host` | POST | detect |
| `/api/set_object_status` | POST | detect |
| `/api/mark_no_host` | POST | detect |
| `/api/unset_host` | POST | detect |
| `/detect?detect_results=<date>`、`/detect` | 導頁 | detect |
| `/object/<name>` | 連結 | marshal `objects_bp` |

模板直接引用的 route：`/detect_image/<name>`（`url_for('detect.detect_image')`）、`/api/detect/cache_status`（loading 頁）、`url_for('detect.detect_results')`、`url_for('detect.detect_archives')`。

**Planners blueprint 的前端檔案**（本章只列清單；頁面邏輯屬 astronomy_tools 章節）：`templates/finding_chart.html`、`templates/observation_planner.html`、`templates/interactive_planner.html`；`static/css/finding_chart.css`、`interactive_planner.css`、`observation_planner.css`、`observation_planner_extra.css`；`static/js/observation_planner.js`；`static/photo/background_observation.png`、`background_planner.jpg`；資料目錄 `ov_plot/`（執行期產生，目前 11 個 `observing_tracks_*.jpg`）。

**測試**：`test_detect_pages.py`（以假 admin session 打 `/detect`、`/detect/archives`、`/detect?detect_results=<latest>`（先手動 `_assemble_detect_payload` + `_set_detect_page_cache`）、`/api/detect/followup_tracker`、`/admin/detect-status`，並驗證 `host_status ∈ {confirmed, review, none, unscreened}`、`rule.kind` 集合、`ext_M_calculator` 的數值）。`test_detect.py` 與 `test_detect_abs_mag.py` 則 import 已不存在的 `app.modules.postgres_database` 與舊表 `tns_objects`，已失效。

---

## 已知問題與注意事項

**死程式碼 / 未使用**

1. `detect_image`（第 326–329 行）、`set_host`（360–363）、`detect_results`（503–508）、`toggle_flag`（1180–1183）各有一段一模一樣的 guest 判斷 `elif` 重複兩次，第二段永遠不會執行。
2. 未使用的 import：`get_cross_match_results`、`get_available_dates`、`get_daily_match_counts`、`update_tns_redshift`、`unset_cross_match_host`、`get_photometry_batch`、`get_object_details_batch`、`get_latest_photometry_for_names`。
3. `GET /api/get_object_status` 沒有任何模板或 JS 呼叫（整個 app 內 grep 不到）。
4. payload 中的 `summary_results`、`cards_data`、`daily_counts` 在 `detect_results.html` 與 `detect_results.js` 都沒用到（每次建置與快取都白算白存，`cards_data` 尤其是整份資料的第二個副本）；`detect_results_loading.html` 未使用傳入的 `available_dates`。
5. `_assemble_detect_payload` 內 `host_status = screen.get('host_status') or ('unscreened' if screen_raw is None else ('confirmed' if target_has_host else 'none'))`：因 `_screen_public` 對存在的列一律回非空 `host_status`，`('confirmed' if … else 'none')` 分支不可達。
6. `detect_shared.css`、`photo/DETECT.png` 無人引用。
7. `set_object_status` 的 docstring 寫「Accepts 'finished' or 'followup'」，實際接受 4 個值。

**權限不一致**

8. 模板/JS 只讓 `is_admin` 看到與觸發決策（`can_edit`），但後端 `set_host / unset_host / set_object_status / mark_no_host / toggle_flag` 只要求「非 guest」；`role='user'` 的登入者可直接呼叫 API 改狀態與 host。
9. `detect_image_by_id` 與 `get_object_status_api` 只檢查是否登入，guest 也可用；同檔的 `detect_image` 卻擋 guest。
10. 導覽列只對 `is_great_lab_member` 顯示 DETECT 入口，但 route 對所有非 guest 開放；反之非 admin 的 GREAT_Lab 成員進到頁面只能看不能審。
11. `planners.serve_ov_plot` 完全公開（檔名為 uuid，實務上不可猜）。手動的 `'..'` 檢查與 `send_from_directory` 的保護重複，無害。

**邏輯與資料一致性**

12. `mark_no_host` 忽略 `reject_cross_match_hosts` 的回傳值：cross_matches 更新失敗時仍會把狀態改成 Snoozed 並回 `success:true`。`set_host` 同樣忽略 `update_object_status` 與 `set_object_redshift` 的回傳值。
13. `toggle_flag`：不驗證 `id`/`flag` 型別；`update_cross_match_flag` 不看 `rowcount`，不存在的 id 也回 success；且**不** soft-invalidate 頁面快取，重新整理後（TTL 內）★ 會顯示舊值。
14. `_ensure_cross_matches_flag_column` 在每次建頁、每次 toggle_flag 都執行 `ALTER TABLE … ADD COLUMN IF NOT EXISTS`（DDL 需要表擁有者權限，且即使欄位已存在 PostgreSQL 仍會短暫取得 ACCESS EXCLUSIVE lock，可能與 pipeline 寫入互相等待）。web_api 的 `get_detect_results_for_target` 也做同樣的事。
15. 「Done」（D）寫入的是 `Snoozed`，不是 `Finish`；頁面把兩者都當「done」。無 host 的物件按 D（走 `set_object_status`）與按 N（走 `mark_no_host`）事後在畫面上都顯示「✗ No host」，但只有 N 會在 `match_data` 記錄 `host_user:false`；重新整理後無法從畫面分辨。
16. 按 F/D 接受「規則選的 host」時會經 `set_host` 把該列記成 `host_user:true, host_user_by:<reviewer>`，之後 verdict 會顯示「Host chosen by <reviewer>」而非「rule v1」。
17. `cross_matches` 列的 `updated_date` 會在 pipeline 每日重跑 Follow-up 物件時更新，因此物件會「搬到」最新日期，舊日期的審核頁與 `daily_counts` 會逐漸減少（程式註解已承認：counts decay for older days）；封存頁不是穩定快照。`detect_screen` 每物件只有一列，同理。
18. 首頁「review page」連結用 `latest_date`（`cross_matches` 最大日期），「Latest run」四個統計用 `overview.run_day`（`detect_screen` 最大 `run_date`），兩者可能指向不同日期。
19. `_detect_page_is_building` 只在同一 process 內有效；若背景建置拋例外，`cache_status` 每次輪詢都會發現「沒 payload 且沒在建」而再開一條執行緒（每個開著的 loading 分頁每 1.5 秒觸發一次完整重建），loading 頁本身永遠不會顯示錯誤。
20. 三個快取與 `_DETECT_PAGE_BUILDING` 都是 process-local：在 gunicorn 多 worker 下，`_soft_invalidate_page_cache` 只清處理該請求的 worker，其他 worker 在 TTL（600 秒）內繼續服務舊 payload；`prewarm` 排程只在持有檔鎖的 worker 執行，其他 worker 第一次進審核頁會看到 loading 頁。`transient.py` 的 `_detect_metadata_cache`（120 秒）與 `_detect_overview_cache`（60 秒）在審核動作後也不會失效，首頁計數與新日期最多延遲 2 分鐘。
21. `_DETECT_LC_CACHE` 沒有 TTL：排程每日抓的新光度點不會反映在審核卡片上，除非按 Refresh LC（`?refresh=1`）、被 LRU 淘汰或重啟。
22. `_start_detect_page_build` / `_start_tracker_build` / `prewarm` 每次都 `threading.Thread(daemon=True)`，沒有上限；`_soft_invalidate_page_cache` 會一次對快取中所有日期（最多 8）各開一條執行緒重建，每條都會跑 `get_extinction`（SFD 查詢）×候選數。
23. `get_detect_page_data` 對 `detect_results` 參數不做日期格式驗證；非日期字串會讓 SQL 例外被吞掉、頁面顯示「No cross-match candidates」，同時該字串會被當 key 放進頁面快取（佔用 LRU 名額）。
24. `detect_results.html` 的 `url_for('detect.detect_image', target_name=…)` 對含特殊字元的名稱沒問題，但 JS 的 `onclick="pickHost('${name}', …)"`、`toggleFlag('{{ t.flag_id }}', this)` 等以字串內插產生 inline handler；`toggleFlag` 內用未宣告的全域 `event`（`window.event`，非標準）。
25. `_navbar.html` 的 Private 下拉 active 判斷是 `current_path in ['/detect_results', …]`，而本章 route 傳的是 `/detect` 與 `/detect/archives`，所以 DETECT 頁面上導覽列永遠不會標示為 active。
26. `detect_background.jpg` 約 25 MB，三個 DETECT 頁面都以 CSS 背景載入（首次載入成本高）。
27. `POST` 端點以 `request.json` 讀 body，非 JSON 請求會得到 Flask 的 HTML 415/400 而不是 `{"success":false}`；錯誤情況（缺參數、DB error）一律回 HTTP 200。
28. 環境變數 `DETECT_PAGE_CACHE_TTL_SEC / DETECT_PAGE_CACHE_MAX_SIZE / DETECT_PAGE_PREWARM_DAYS / DETECT_LC_CACHE_MAX_SIZE / DETECT_TRACKER_CACHE_TTL` 未在任何 `.env` 範例或 README 中記載。
29. `test_detect.py`、`test_detect_abs_mag.py` 引用已移除的 `app.modules.postgres_database` 與舊表 `tns_objects`，無法執行；只有 `test_detect_pages.py` 與現況相符。
30. `planners_routes.py` docstring 明言頁面與 API 在 `astronomy_tools_routes.py`；`generate_plot` 的 `enforce_max_files(…, 10)` 只在「產生新圖之前」清理，因此目錄可短暫存在 11 個檔，且任何回傳給前端的 `plot_url` 在 10 次新產生後即失效（404）。

**無重複註冊的路徑**：整個 app 中 `/detect`、`/detect/archives`、`/detect_image/*`、`/detect_image_by_id/*`、`/api/set_host`、`/api/unset_host`、`/api/get_object_status`、`/api/set_object_status`、`/api/mark_no_host`、`/api/toggle_flag`、`/api/detect/*`、`/ov_plot/*` 都只在本章兩個檔案定義；模板內所有 `url_for` 目標（`detect.detect_results`、`detect.detect_archives`、`detect.detect_image`、`basic.login`、`basic.home`、`static`）與 JS 呼叫的外部端點（`web_api.fetch_photometry`、`objects_bp` 的 `/object/<path:object_name>`）皆存在。
