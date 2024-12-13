import obsplanning as obs
import ephem

# 建立鹿林天文台的觀測站位置（經度、緯度和海拔）
lulin_obs = obs.create_ephem_observer('Lulin Observatory', '120:52:21.5', '23:28:10.0', 2800)

# 設定觀測目標
a = obs.create_ephem_target('Crab Nebula', '05:34:31.94', '22:00:52.2')
b = obs.create_ephem_target('NGC 1052', '02:41:04.7985', '-08:15:20.751')
c = obs.create_ephem_target('NGC 3147', '10:16:53.65', '73:24:02.7')

# 設定觀測開始和結束時間
obs_start = ephem.Date('2024/11/14 17:00:00')  # 觀測開始（當地時間 17:00）
obs_end = ephem.Date('2024/11/15 09:00:00')    # 觀測結束（當地時間 09:00）

print(a)
total = [a, b, c]
# 使用 plot_night_observing_tracks 繪製多個目標的可見性軌跡Q
obs.plot_night_observing_tracks(
    total,  # 目標列表
    lulin_obs,                        # 觀測站
    obs_start,                        # 觀測開始時間
    obs_end,                          # 觀測結束時間
    simpletracks=True,                # 使用簡單軌跡圖
    toptime='local',                  # 時間顯示為當地時間
    timezone='Asia/Taipei',           # 設定當地時區為台北
    n_steps=1000,                     # 計算的步數
    savepath='lulin_observing_tracks.jpg'  # 保存圖片的路徑
)
