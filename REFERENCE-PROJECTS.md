# GitHub 參考專案：實際內容與 MVP 採用範圍

查核日期：2026-10-01。以實際檔案與程式判讀，不以最初提案描述替代驗證。只參考設計與一般統計構想；未將他人工作簿、圖檔、資料或原始程式複製進本儲存庫。

## thewaterloo/cleanroom-environmental-monitoring-dashboard

[固定查核版本 b7fd9c4](https://github.com/thewaterloo/cleanroom-environmental-monitoring-dashboard/tree/b7fd9c4f0c74ec2ea24855e0bc697e3d1b07744f)

實際是一份 .xlsx、模擬月報 PDF、README 及五張截圖，內容在雙層 project_3_cleanroom_environmental_monitoring_dashboard 資料夾。README 明確標示教育／作品集用途及模擬資料。

工作簿有六張表：Dashboard、Raw_Monitoring_Data、Excursion_Log、Room_Limits、Monthly_Trend_Summary、Data_Dictionary。150 筆模擬溫度／濕度／壓差／粒子資料；有公式及兩個原生柱狀圖。並沒有微生物 CFU、菌種、Word 匯入、資料庫或 VBA 巨集。

| 可参考內容 | 我們的改寫 |
|---|---|
| 摘要與房間異常比率 | GUI 顯示有效採樣數、陽性率、Alert／Action 及待核對數，附各指標分母 |
| 明細、限值與異常清單分開 | 資料庫分別管理來源結果、有效日期限值及待審閱事項 |
| 月報摘要與 QA 備註 | 可重現計算＋人工 QA 評語，記錄報告期間及版本 |
| 資料字典 | 明確定义欄位、單位、結果類型及原始來源 |
| 依資料範圍生成圖表 | GUI 圖表讀同一份報表計算結果；Excel 匯出若有圖則連結公式／資料 |

不能照搬：溫濕度／粒子示例限值；固定到第 153 列的公式範圍；比率分母為 0 時顯示 0；沒有期間篩選的「月摘要」。Excursion_Log 與 QA 備註是人工示例，不代表會由結果自動產生及保留歷程。

已獨立依工作簿規則計算：四種異常各 1／2／2／3，8 筆讀值需要審閱。月報截圖寫 120 筆，工作簿為 150 筆，因此截圖不是可靠的自動一致性證據。本版報表應從同一已提交資料集產生。

查核範圍是工作簿欄位／公式／原生圖表結構及截圖，不包含啟動 Excel 做完整重算。未找到 LICENSE 檔；不把它當成可直接複製的已授權模板。

## alyce0425/environmental-monitoring-analysis

[固定查核版本 0dd4ebd](https://github.com/alyce0425/environmental-monitoring-analysis/tree/0dd4ebd15c3ff737a78d8bb720ce616af79a3ff4)

實際為 README、一支 R、一份 12 列模擬 CSV 與四張 PNG。R 直接建立程式內資料，沒有讀 CSV；沒有 GUI、Word 匯入、校正流程、資料庫或持續更新的月報。

| 可参考內容 | 我們的改寫 |
|---|---|
| 按房間比較 CFU | 相同方法／單位／採樣条件下的點位與房間分析，附採樣數 |
| Air／Surface 時間趨勢 | 各方法分開的每月折線及柱狀圖 |
| 分組、排序、缺值檢查 | Python 固定計算與 GUI 篩選／待核對清單 |
| 溫濕度相關圖 | 非首版核心；將來有足夠對應資料再評估 |

資料只列 Room、Air_CFU、Surface_CFU、Temperature、Humidity、Date；缺方法單位、點位、採樣量、操作者、結果型態、限值版本及來源。我們仍以一筆實際採樣一列，不能把這份寬表直接當資料庫模型。

R 的 Air＋Surface Total_CFU、硬編碼 Higher 分類及模擬資料相關性不納入公司正式規則。圖表構想可用 Python／瀏覽器自行重作，不必導入 R／ggplot2。

來源：[分組／圖表程式](https://github.com/alyce0425/environmental-monitoring-analysis/blob/0dd4ebd15c3ff737a78d8bb720ce616af79a3ff4/environmental_monitoring_analysis.R#L47)、[示例加總／分類](https://github.com/alyce0425/environmental-monitoring-analysis/blob/0dd4ebd15c3ff737a78d8bb720ce616af79a3ff4/environmental_monitoring_analysis.R#L131)、[模擬資料](https://github.com/alyce0425/environmental-monitoring-analysis/blob/0dd4ebd15c3ff737a78d8bb720ce616af79a3ff4/data/environmental_monitoring_data.csv)。未找到 LICENSE 檔；不直接搬程式或圖檔。

## 採用結論

兩個專案納入第一版的設計參考，不作 production 程式基底。系統以 GUI 匯入、人工核對、來源追溯、既有 CRR／點位矩陣與固定規則為核心；Dashboard 摘要、異常清單及月度圖表從同一資料庫生成。
