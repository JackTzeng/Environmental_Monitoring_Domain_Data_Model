# EM-008 QA 第一輪修補

日期：2026-10-02。依獨立報告 `docs/acceptance/EM-008-QA-adversarial-report.md` 修正 QA-01–12；報告原檔不修改。R1-01 最小修補已完成，待定向覆驗；沿用 `codex/em-mvp-spec` 與目前 workspace。

## 範圍

- 修正共同 API／XLSX adapter、Sheet 候選配對、SQLite 快照讀取版本保護及欄位來源追溯。
- 保持原始來源值、原始欄位、Word 目前值、state、verified、人工修正、分析排除、source location／SHA 及原子批次回滾保護。
- 保留單筆樣本與菌鑑子列關係；未知 TNTC、`<1`、缺快取、缺目的或矛盾資料留待核，不轉 0、不宣稱準確率。
- 只用合成資料和隔離測試資料庫；不連正式 DB、公司來源、Google Sheet、OAuth token 或正式服務。

## 修補與驗收案例

| 項目 | 修補／可重跑案例 |
|---|---|
| QA-01 | `test_qa01_groups_unmapped_purpose_rows_before_assessing_positive_evidence`：G 空白／未對照列不拆核心樣本；N/O 和子列一起評估並保留待核。 |
| QA-02 | `test_qa02_word_nonblank_result_and_monitoring_conflicts_block_supplement`：包括監測類型與數值結果的非空衝突會阻擋補值。 |
| QA-03 | `test_qa03_adopted_record_surfaces_changed_source_result`：已採用指紋後來出現 CFU 差異，呈現衝突且不覆寫。 |
| QA-04 | `test_qa04_adopted_sheet_batch_identity_allows_distinct_B_repeats`：已採用 B 身分從逐欄證據回讀；不同 B 可分別採用且重讀指回正確紀錄。 |
| QA-05 | `test_qa05_old_snapshot_cannot_adopt_or_supplement_after_new_read`：較舊讀取不能新增／補值，紀錄、歷程與備份皆不變；UI 的歷史預覽隱藏操作並提示刷新。 |
| QA-06 | `test_qa06_swapped_total_and_colony_headers_are_rejected_by_both_adapters`：API、XLSX N/O 交換與菌鑑欄錯置都拒絕，不誤取 O 作 CFU。 |
| QA-07 | `test_qa07_chart_and_monthly_routes_render_adjacent_months`：兩月 chart、`/reports`、`/report.html` 無 NameError／500。 |
| QA-08 | `test_qa08_conflicting_purposes_stay_one_pending_group_in_any_row_order`：兩種 G 目的排序前後都是同一個待核樣本，列證據完整。 |
| QA-09 | `test_qa09_xlsx_formula_uses_cached_value_and_missing_cache_stays_pending`：有效快取與 API 數值一致；缺快取明確待核。OOXML 僅存在記憶體。 |
| QA-10 | `test_qa10_duplicate_content_keeps_each_read_completeness_and_origin`：相同 XLSX/API 值共用內容 ID、使用不同讀取 ID；完整性、來源、spreadsheet／sheetId 證據保留於各自讀取。 |
| QA-11 | `test_qa11_incomplete_current_read_does_not_report_removed_samples`：共用函式及 `/sheet-reconcile` 不以不完整當前讀取提示刪列。 |
| QA-12 | `test_qa12_empty_supplement_submission_is_clear_and_has_no_backup`：空 POST 顯示訊息、沒有資料或備份寫入。 |

## R1-01 定向修補

依 `docs/acceptance/EM-008-QA-round1-retest.md` 的兩個 P1 變體（同廠／同 B，另一列缺方法或年份但有 N=3、O=3、菌種 Bacillus），補零前共用 `_could_share_sample_context` 檢查快照內同廠、同 B 且已知採樣脈絡沒有明確衝突的其他來源列。可能相關的列維持獨立待核，不合併、不推零；CFU=0 群的原因與欄位追溯一併列出該列 N/O、菌種、分頁、列號及 A:Y 原始值。`store.adopt_sheet_candidate` 仍在交易中重算同一 `sample_groups`，所以即使呼叫真實採用函式，狀態為 pending 也會被拒絕。

新增回歸：

- `test_r1_01_unresolved_same_batch_positive_rows_block_zero_through_api_preview_and_adoption`：API adapter → 預覽頁 → 記憶體 SQLite 真實 `adopt_sheet_candidate`，覆蓋缺方法／缺年份；確認零候選不產生、陽性與菌種證據可見、採用被拒且沒有記錄／adoption。
- `test_r1_01_partial_other_core_fields_stay_separate_and_different_B_is_not_a_zero_blocker`：代表性點位／檢驗批次／房間／Grade 缺漏保持待核；不同 B 的完整合法零與正數樣本各保留一次，不互相阻擋。

完整合法 `N` 空白、`O=0`、無相關列的零候選仍可用；既有完整明確零、正數、多菌種子列與同 B 衝突規則另有回歸。

另由 `test_new_candidate_is_single_draft_and_repeated_snapshot_cannot_duplicate` 驗證採用記錄含 C/D/E、G、N/O 的分頁／儲存格／原值追溯及 CFU 來源規則。既有 `test_snapshot_dedup_and_version_protected_supplement_preserve_review_scope` 與 `test_supplement_does_not_restore_a_manually_cleared_blank` 確認人工修改、verified、state、分析排除及版本保護仍保留。

## 資料層變更

`sheet_snapshots` 繼續保存去重後的列內容；新增 `sheet_snapshot_reads` 保存每次來源讀取、時間、完整標記／依據、摘要與來源證據。使用者每次重新讀取即建立新讀取 ID；寫入操作在備份前和 transaction 內各檢查一次是否仍是最新讀取。`sheet_adoptions.snapshot_id` 仍指向內容 ID。初始化時為舊快照補一筆 legacy 讀取事件，Schema user_version 更新為 6。正式 migration／正式備份仍未執行。

XLSX 公式模式與快取模式各讀一次。快取與來源公式按讀取事件保存，摘要依有效的列值去重；讀取快照時用該事件的公式與 tab metadata 還原證據。沒有 cached value 的 N/O 公式標示待核，不推算或假定為零。

## 執行結果

- `\.venv\Scripts\python.exe -m unittest tests.test_em008 -v`：27 項通過。
- `\.venv\Scripts\python.exe -m unittest discover -s tests -v`：109 項通過。
- `git diff --check`：通過。
- 未啟用、未寫正式 DB／Sheet、未重載正式服務、未 commit／push。

## 待 PM 定向覆驗

請 PM 指定 QA 僅重播 R1-01 兩種缺核心欄案例及其 API／預覽／後端採用路徑；本修補完成後不執行正式來源重解析或正式 DB 寫入。OAuth 真實授權/API、互動 GUI、正式 schema migration 及磁碟備份不在本輪隔離測試中，結果文件明確列為未驗證。
