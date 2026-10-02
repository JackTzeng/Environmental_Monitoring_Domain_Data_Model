# EM-001 / EM-002 驗收交付

日期：2026-10-01  
版本：app `0.2.0`、parser `0.1.1`  
狀態：本文件記錄 EM-001／EM-002 初驗當時的版本與證據。實際七份 Word 的後續解析驗收已記錄於 [EM-003 驗收結果](EM-003-real-word-results.md)，目前分支版本為 app `0.3.0`、parser `0.1.3`。

## 驗收摘要

- EM-001 資料夾遞迴匯入及 EM-002 預設逐月點位矩陣已完成。
- 全套測試 `35` 項通過；GUI 使用全新暫存資料庫，沒有匯入公司歷史資料。
- 本機正式服務已安全更新至 app `0.2.0`。正式 SQLite 資料庫仍為 38 筆、1 個來源；重啟前後來源與紀錄內容指紋相同。重啟前建立備份：`C:\Users\ES-QC-022\Documents\Codex\Environmental_Monitoring_MVP-data\backups\20261001T084659920607.sqlite3`。
- PM 另行回報七種實際 Word 版型仍有欄位辨認缺漏；當時本交付未宣稱這些版型已通過。後續 EM-003 已唯讀解析指定來源並驗收舊資料重新解析保護，詳見 EM-003 文件。

## 2026-10-02 後續版本整合

- app `0.3.0`／parser `0.1.3` 完整測試 50 項通過；EM-003 修正後的專項證據另見[真實 Word 解析及重新解析驗收](EM-003-real-word-results.md)。
- 正式服務 `127.0.0.1:8765` 已啟動。SQLite schema 升級前先備份；正式資料仍為 38 筆、1 個來源，來源原始及目前解析版本均為 `0.1.0`，未重解析。與備份比對的核心資料指紋相同：`f10593fa7e8c218057441f7b08cc277e6a239b7e47269b0ebb58d6b241595dbe`。備份：`C:\Users\ES-QC-022\Documents\Codex\Environmental_Monitoring_MVP-data\backups\20261001T230744500774.sqlite3`。

## EM-001 資料夾匯入

| 案例 | 結果 | 驗證方式／證據 |
|---|---|---|
| A1 遞迴讀取兩層子資料夾並直接入庫 | 通過 | 單元測試 `test_a1_recurses_two_levels_and_writes_directly_to_database`；GUI 一次處理巢狀 Word。 |
| A2 重跑不覆蓋人工修正及歷程 | 通過 | 單元測試 `test_a2_rerun_preserves_manual_correction_and_history`。 |
| A3 壞檔繼續處理、暫存與不支援檔略過 | 通過 | 單元測試 `test_a3_bad_file_continues_and_temp_and_unsupported_files_are_skipped`、`test_a3_reparse_directories_are_not_recursed`；GUI 顯示 `bad.docx` 失敗原因，另略過 2 檔。 |
| A4 不存在／非資料夾／無法讀取路徑 | 通過 | 單元測試 `test_a4_invalid_nonfolder_and_unreadable_paths_are_explicit`。 |
| A5 大於 25 MB 的批次、單檔大小保護、重複啟動 | 通過 | 單元測試 `test_a5_batch_exceeds_25mb_single_file_guard_and_duplicate_start`。 |
| A6 Sheet 匯出檔選項 | 通過 | 單元測試 `test_a6_sheet_files_are_included_only_when_selected`；GUI 勾選 XLSX／UTF-8 CSV 後匯入 CSV。 |
| A7 來源可追溯、未核對不計為正確 | 通過 | 單元測試 `test_a7_database_source_and_accuracy_keep_import_pending`；GUI 月明細可開來源與修正頁，輸出頁 4 筆均為待核對、欄位正確率顯示「未評估」。 |

## EM-002 逐月點位矩陣

| 案例 | 結果 | 驗證方式／證據 |
|---|---|---|
| B1 開啟資料庫即顯示年度矩陣，包含待核對值 | 通過 | 單元測試 `test_b1_default_database_is_year_matrix_and_includes_pending`；GUI 預設 2026 矩陣，待核對標記可見，另有「原始明細」切換。 |
| B2 同點位 6/3=2、6/16=8，另月 0，無採樣顯示 — | 通過 | 單元測試 `test_b2_earliest_calendar_date_zero_and_no_sample_are_distinct`；GUI 六月顯示 2（共 2 筆），七月顯示 0，空月顯示 —。 |
| B3 同日衝突及 TNTC、<1、N/A、缺值 | 通過 | 單元測試 `test_b3_same_day_value_and_limit_conflicts_and_special_values`。 |
| B4 月格顯示當月所有採樣與來源 | 通過 | 單元測試 `test_b4_month_cell_links_to_every_sample_and_source`；GUI 點六月格後列出 6/3 與 6/16，含目前值、原始值、核對狀態、來源與「檢視／修正」。 |
| B5 年度／廠別／方法／類型／狀態篩選及排除作廢 | 通過 | 單元測試 `test_b5_filters_year_site_method_type_and_status_and_excludes_void_by_default`。 |
| B6 修正後保留原值；輸出限已確認資料 | 通過 | 單元測試 `test_b6_correction_updates_matrix_preserves_original_and_output_stays_confirmed_only`；GUI 報表不納入任何待核對資料，辨認正確率不虛報。 |

## GUI 驗收資料與結果

- 另建空白暫存資料庫：`%TEMP%\em001-em002-gui-acceptance-20261001-final\data`。
- 測試資料只有合成範例：3 份巢狀 Word、1 份 UTF-8 CSV、1 份損壞 Word、1 個 Office 暫存檔及 1 個不支援文字檔。
- 首次匯入：新增 4 個檔案／4 筆明細，失敗 1 檔並列出原因，略過 2 檔；完成後輸入頁自動刷新筆數及歷程。
- 同一資料夾重跑：新增 0 檔／0 筆明細，既有 4 檔，沒有重複資料。
- 矩陣及六月明細畫面已於 GUI 驗看；另以使用者提供的 Excel 核對矩陣欄位結構及「取當月最早採樣值」口徑，沒有將 Excel 範例列作原始採樣匯入。

## 正式資料保護與限制

- 正式資料庫重啟前後皆為 38 筆紀錄、1 個來源，完整紀錄／原始辨認值／目前值／核對欄位／歷程與來源 metadata 的 SHA-256 指紋一致：`1e9a2a870d71646be8cac56fda96b5a5675ae0b3d412985a5503151160c35210`。
- 原正式來源仍標示 parser `0.1.0`；相同檔案的 SHA-256 去重會保留既有修正，不會自動重跑新 parser。正式資料未刪除、重建或批次重匯。
- 指定公司 2026 年 6 月資料夾僅依 EM-003 工單唯讀解析，未匯入任何資料庫；parser `0.1.1` 初驗結果由 parser `0.1.2` 專項驗收補充。逐欄可用值數量不是人工正確率。
- 月矩陣是待核對資料的預覽；正式月報仍只納入已確認紀錄。本版不自動判定 Alert／Action，也不作正式簽署。

## 交付檔

- [README 操作與維護說明](../../README.md)
- [EM-001 工作單](../work-orders/EM-001-folder-import.md)
- [EM-002 工作單](../work-orders/EM-002-database-monthly-matrix.md)
- [舊版 GUI 可行性評估註記](../../EM-GUI-FEASIBILITY-v0.2.md)

本次變更仍在工作分支，尚未提交或推送。
