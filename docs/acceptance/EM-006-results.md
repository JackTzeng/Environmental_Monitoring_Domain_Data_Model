# EM-006 矩陣加寬與上方捲動條工程結果

日期：2026-10-02。基線 app `0.4.0`／parser `0.1.4`，commit `32423de`。PM 初驗提出全方法矩陣上下範圍相差 1px；下列為依該回報修補後的工程核對，仍待 PM 獨立覆驗。

## 實作

只修改 `base.html` 與 `database.html`：矩陣頁使用視窗可用寬度，桌面左右留 24px；其他資料庫頁沿用既有 max-width。表格上方增加可鍵盤操作、垂直捲動時 sticky 的原生水平捲動區，與既有下方捲動區同步。上方內軌寬度直接取下方原生容器的 `scrollWidth`；ResizeObserver 與視窗 resize 時更新寬度，無溢出時隱藏上方 bar，列印時不顯示。未新增依賴，未改解析器、資料模型、矩陣內容或正式資料。

## 工程核對

- 使用既有 `Stop.ps1`／`Start.ps1` 重載本機服務；`/health` 回報 app `0.4.0`／parser `0.1.4`。
- 在 2026 一廠、全部方法矩陣操作原生捲軸。1440px viewport 下，上下容器均為 `scrollWidth=1626`、`clientWidth=1327`，計算範圍均為 299px；上方捲至右端時兩者 `scrollLeft=300`，再由下方捲回左端時兩者均為 0。瀏覽器回報的 300px 端點來自子像素版面取整，兩容器實際端點一致。
- 縮放為 1280px viewport 後，兩容器均為 `scrollWidth=1626`、`clientWidth=1167`、計算範圍 459px；上方捲至右端時兩者均為 `scrollLeft=460`。此 viewport 的 `documentElement.clientWidth` 與 `body.scrollWidth` 同為 1261px，沒有整頁水平溢出。
- 1440px viewport 的 `documentElement.clientWidth` 與 `body.scrollWidth` 同為 1421px，沒有整頁水平溢出。頁面文字顯示 1,492 筆、159 組矩陣；篩選為 2026、一廠、全部監測類型、全部方法、全部非作廢。
- `git diff --check` 通過。本次僅重新載入及唯讀操作頁面，沒有提交表單、重解析來源或寫入正式 DB。

## 交 PM 覆驗

請 PM 對最新服務版本獨立核對全方法矩陣兩端與雙向同步、resize 後尺寸、1440／1920／窄視窗、篩選後載入、空資料／無溢出、其他資料庫頁原寬、月格連結及列印隱藏。PM 最終判定與遠端備份 SHA 尚未完成；在接受前不提交或 push 本工單版本。
