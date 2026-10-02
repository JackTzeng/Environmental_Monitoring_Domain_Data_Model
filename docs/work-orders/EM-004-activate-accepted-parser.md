# EM-004：啟用已驗收解析器

負責執行：同一個 Luna 6.0 Max 對話；PM僅覆驗。

EM-003 app0.3.0／parser0.1.3 已通過 PM 獨立覆驗。現有 localhost8765仍在執行 parser0.1.2，因此使用者尚無法在現行服務使用已修正版本。

## 執行範圍

1. 唯讀記錄現有正式庫筆數、來源、changes、版本與原始紀錄摘要。預期38筆／1來源／0變更／來源0.1.0。
2. 啟用前以 SQLite backup 建立一致性備份。保留來源副本及原始值；備份失敗不啟用。
3. 用既有 Stop.ps1／Start.ps1 停止確認屬於此專案的本機程序並啟動已驗收版本。背景程序用 Hidden；不得停止不明程序。以現有 schema 遷移補 original_parser_version，不重建DB，不改其他程式。
4. GET /health 確認 app0.3.0／parser0.1.3；確認來源重新解析入口與資料庫頁可正常開啟。
5. 正式庫仍38筆、1來源、0changes；sources.parser_version／latest_parser_version仍0.1.0，原始紀錄摘要仍與基線一致。38筆 original_parser_version應0.1.0。備份可讀。
6. 寫入簡短啟用證據後交PM覆驗。不提交任何正式匯入／重新解析表單，不批量灌入七份檔案，不改人工核對狀態，不 commit／push。

基線 SHA-256（SELECT id,source_id,original ORDER BY id 的 JSON ensure_ascii=False）：`ed8e3da362f5e25524333db6906fdd48d19b6b376a02d3ee08e602e9cde99a77`。

本工單只啟用驗收版本；正式舊來源的補值由使用者透過「輸入 → 已匯入來源與重新解析」執行。不要因啟用成功宣稱38筆已補值。
