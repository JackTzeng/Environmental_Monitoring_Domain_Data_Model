# EM-008 工程結果與 QA 第一輪修補候選

日期：2026-10-02。狀態：第一切片曾由獨立 QA 退回；QA 通過其餘 11 項，只餘 R1-01。依 PM 指示完成 R1-01 最小修補，現待定向 QA 重播，整體候選尚未接受。未啟用服務、未寫入正式 DB／Google Sheet、未 commit/push。

工單：[EM-008 管理者 Google Sheet 核對與缺欄補值](../work-orders/EM-008-google-sheet-reconciliation.md)。QA 原報告：[EM-008 第一輪對抗驗證](EM-008-QA-adversarial-report.md)，修補時保持原檔不變。

## 第一輪修補結果

| QA | 結果 |
|---|---|
| QA-01 | 先按 B、C/D/E、F、H、K、L、M 核心欄分群，再檢查 G；空白 G 不拆群，未對照 G 會整群待核並列出所有 N/O 與菌鑑子列證據。 |
| QA-02 | Word 配對比較 Sheet 候選中所有非空映射欄，包含監測類型、原始結果、型別、CFU、廠別、房間、Grade、批次、人員及點位；任何已填值衝突都阻擋補值並列欄位名稱。0、TNTC、<1、空白分開處理。 |
| QA-03 | 已採用指紋仍去重；後續來源重新比對採用紀錄的目前值，差異改顯示衝突，不隱藏、不覆寫。 |
| QA-04 | 新採用紀錄在來源證據保存 B；舊格式則由 A:Y 原列回讀 B。不同 B 的已採用 Sheet 樣本不再誤當作無 B 的 Word 候選；同日重採可分筆採用及去重。 |
| QA-05 | 快照內容與讀取事件分表。每次讀取都有獨立 ID；補值／採用只接受最新讀取。歷史頁面隱藏操作並提示刷新，後端交易仍再檢查最新 ID。 |
| QA-06 | API 與 XLSX 共用完整固定欄名檢查；覆蓋採樣識別、日期、方法、目的、批次、操作者、房間、Grade、點位、N/O 及菌鑑 S:Y 欄。已知方法／來源別名與全形字元正規化保留。 |
| QA-07 | 修正 `chart()` 對未定義 `snapshot` 的引用；兩個相鄰月份的 SVG、`/reports` 與 `/report.html` 均完成合成回歸。 |
| QA-08 | 同一核心採樣群的多種 G 目的不依賴列順序；矛盾群保留單一指紋、所有列及 N/O 證據並待核。 |
| QA-09 | XLSX 同時讀公式與計算值；使用 Excel 已保存的快取值，公式／快取一併保存為讀取證據。N/O 公式沒有快取時顯示待核原因，不推算或補 0。 |
| QA-10 | 同內容仍只存一份列資料，但每次讀取都追加來源、時間、完整性／依據、摘要及來源證據。內容摘要只依列號、廠別脈絡與有效儲存格值，API/XLSX 相同值可以共用內容。Schema v6 將舊快照回填為 legacy 讀取事件。 |
| QA-11 | 只有當前與先前讀取都完整時，才顯示「未再出現」提示；共用函式預設不產生刪列提示。 |
| QA-12 | 空補值表單回傳清楚訊息，不呼叫寫入流程、不新增備份；路由測試確認 HTTP redirect 與 DB 備份數不變。 |

## R1-01 最小修補結果

QA 第一輪回驗發現：同廠／同 B 的正數菌鑑子列若缺日期或方法會進入另一待核列，原 N 空白／O=0 列仍可被推成零並由後端採用。現在共用欄位相容性檢查，只在同廠、同 B 且既有欄位沒有明確衝突時，把其他來源列列為可能關聯待核證據；不合併列、不猜缺欄、不產生零候選。預覽與後端採用都重用 `sample_groups`，後端重新計算並拒絕 pending 群。

`tests.test_em008.EM008Tests.test_r1_01_unresolved_same_batch_positive_rows_block_zero_through_api_preview_and_adoption` 使用 API adapter 和記憶體 SQLite 實際走過預覽路由及 `store.adopt_sheet_candidate`；缺方法、缺年份均顯示 N=3/O=3/Bacillus 來源證據，未新增 record 或 adoption。`test_r1_01_partial_other_core_fields_stay_separate_and_different_B_is_not_a_zero_blocker` 覆蓋點位、檢驗批次、房間、Grade 缺漏；不同 B 的合法零和正數各一筆，仍獨立成候選。完整合法零、多菌種同採樣只計一筆、重用 B 衝突原測試亦通過。

預覽資料包已建立於單一合成隔離目錄，詳見 [MVP 預覽包](EM-MVP-preview.md)。種子 10 筆，6 confirmed／4 draft／1 analysis-excluded；使用者指南、啟動／停止腳本、資料路徑識別已備妥。本機服務尚未啟動，未宣稱 GUI 或 loopback 已驗證。

修補後執行 `\.venv\Scripts\python.exe -m unittest tests.test_em008 -v`：29/29 通過；`git diff --check` exit 0（只有工作樹既有 LF／CRLF 提示）。PowerShell parser 對兩支啟停腳本回報 0 語法錯誤。已核對 `Resolve-Path` 與 manifest `data_dir` 完全一致，合成種子識別為 `EM-MVP-Preview-EM008-20261002`；8876 無 listener。未啟服務、未執行互動 GUI、未接觸正式 DB、真實來源或 OAuth。

每筆採用或補值歷程新增 `field_sources`：逐欄保存讀取 ID、spreadsheet ID、分頁／sheetId、來源列、欄／儲存格、原始值及公式快取。廠別值連回指定分頁脈絡；推定 0 額外記錄規則版本、N/O 來源及 S:Y 菌鑑證據。預覽畫面也可展開欄位來源儲存格。沒有公式引擎，缺失快取不會以 0 代替。

## 驗證

- `\.venv\Scripts\python.exe -m unittest tests.test_em008 -v`：27 項 EM-008 測試通過，包含 12 個 QA 反例、公式快取、欄名交換、讀取事件／內容去重、每欄來源追溯及舊預覽寫入阻擋。
- `\.venv\Scripts\python.exe -m unittest discover -s tests -v`：全套 109 項通過，包含 EM-005、EM-007、應用程式與匯入器回歸。
- `git diff --check`：通過。工作樹仍含先前尚未接受的 EM-007／EM-008 變更；本輪沒有建立 commit。
- QA-09 使用 stdlib 建立純記憶體 OOXML，不寫 XLSX 暫存檔。所有新例使用合成資料與暫存 SQLite。

## 未驗證及交付界線

- 尚待 PM／QA 對新候選獨立覆驗；這不是工單接受或啟用確認。
- 本輪沒有連接或重讀真實 Google Sheet、沒有 OAuth 實際授權／refresh 驗證，也沒有互動 GUI／本機正式服務覆驗。既有第一切片所記 connector 盤點是先前工程記錄，不能由本輪合成測試替代或宣稱重新驗證。
- Schema v6 migration 僅由隔離測試資料庫覆驗；正式 DB、磁碟備份、正式資料及服務均未觸碰。PM 接受修補後仍需依工單流程做正式啟用及受保護的來源處理。
- 本輪未 commit/push；PM 覆驗接受前不把修補候選送入已接受基線。

## EM-008 修補候選檔案

- `em_mvp/sheet_reconcile.py`
- `em_mvp/store.py`（同時含工作樹既有 EM-007 變更）
- `em_mvp/app.py`（同時含工作樹既有 EM-007 變更）
- `em_mvp/templates/sheet_reconcile.html`
- `tests/test_em008.py`
- `docs/work-orders/EM-008-QA-round1-fixes.md`
- `docs/acceptance/EM-008-results.md`

QA 凍結基線 SHA：`3b303050249585b633cff2601c4d6cc7b316cb47`。第一切片凍結檔案 SHA 及對抗證據保留在未修改的 `EM-008-QA-adversarial-report.md`；本輪新的候選檔案 SHA 另回報 PM，等待獨立覆驗。
