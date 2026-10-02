# EM-007 工程與暫存庫驗證結果

日期：2026-10-02。實作由使用者已授權的 Luna 6.0 Max 工作視窗完成。狀態：PM 已接受程式修補階段，並已核對 Parser 0.1.7 隔離 clone 摘要及正式 DB 未變 SHA 邊界；PM 未直接讀取 clone，亦未完成互動 GUI／完整工單驗收。正式 DB／服務尚未遷移、重解析或啟用，EM-007 尚未 commit/push。

## 實作摘要

- SQLite schema v4 新增 `analysis_included` 及 `analysis_exclusion_reason`。旗標獨立於 `draft`／`confirmed`／`void`，原因最多 120 字；排除／還原以目前資料版本作並行檢查、寫入前備份，並追加 before／after、操作人與時間歷程。還原清空目前原因欄，但歷程保留排除及還原理由。
- 環測矩陣／趨勢、製程採樣矩陣、CRR 及正式月報都只統計納入分析的列；原始明細、月份明細及 CSV 仍保留資料，明示排除狀態與原因。辨認正確率不依排除旗標隱藏資料。
- Parser 0.1.7 僅將精確的「製程監測＋人員監測」雙勾組合分類為製程監測，將多選原文留在提醒中。其他多選仍待核對；製程來源沒有明確廠別時，即使房間是 C01–C06 也不推定廠別。Word 的表格局部操作者資料只作用在該表；同列多位操作者留空並提醒，不會複製採樣列。
- 輸入頁新增精確組合的動態批次重解析操作：逐一解析舊來源，只對 parser 實際辨認到精確雙勾組合的來源呼叫既有 `reparse_source`，沿用 source SHA、版本、original、current／人工修改、verified、state 保護及來源寫入前備份。目標數由執行時來源結果計算，未硬編碼 62／482。
- 新增製程草稿預覽、方法小計、期間合計、月格來源明細、人日 CRR 與追溯頁、待補資料清單及 Isolator 分組／待核對清單。採樣要求明確廠別、人員、日期、Grade A、落菌／接觸方法、點位、單位且相關衝突已核對；方法／房間／點位／單位不混併。不可加總結果不轉成 0。CRR 同廠同人同實際日合併；不可比較結果的人日標待核對且不進 A／B；正式月報只取 confirmed。
- Isolator 來源列 TRUE 欄位定義未確認前，設備統計納入筆數固定為 0；符合點位特徵者只分組並列來源待核對，不進人員 CRR。

## 真實來源唯讀盤點與暫存庫重解析

正式 DB 以 SQLite `mode=ro`／`query_only` 核對，PM 最新覆驗確認仍為 schema v3：3312 records、226 sources、1583 changes；檔案 SHA-256 `62bd60bfc656ccb8996816a6a9e144c6a938fa88f89ea6b5f3647e4a72895b48`，沒有 EM-007 欄位或資料變動。正式 DB 未由本輪程式操作。

Parser 0.1.7 逐一唯讀解析真實保留來源副本：226/226 sources，3312 parsed rows，精確雙勾來源 62/482 rows，缺檔／解析錯誤均為 0；掃描前後來源暫存 DB SHA 相同。正式庫原有這 482 列為 draft、site 空白、operator 非空 134 列；這些欄位覆蓋數不是辨認正確率。

為直接驗證正式基線的實際重解析效果，從正式 DB 的 SQLite 唯讀連線建立全新隔離 clone，並複製 226 份 SHA 已核對的來源 archive。只在 clone 以 Flask test client 呼叫既有 `/reparse-process-batch`；沒有啟動服務，也沒有將正式 DB 傳入 `create_app`。正式 DB SHA 在執行前後均為 `62bd60bfc656ccb8996816a6a9e144c6a938fa88f89ea6b5f3647e4a72895b48`。clone 的完成 DB SHA-256 為 `a880cdb24be85380d6b97cc1f02ab45cf3018b373be8753b93a4cde35ed639ce`。

| 正式基線 clone 驗證 | 結果 |
|---|---:|
| clone 起始／完成 schema | v3／v4（僅 clone 遷移） |
| 正式基線 records／sources／changes | 3312／226／1583 |
| clone 完成 records／sources／changes | 3312／226／2065 |
| 起始 source parser versions | 226 份均為 0.1.4 |
| 動態掃描／精確雙勾命中 | 226／62 sources、482 rows |
| source outcomes（成功／衝突／略過／失敗） | 62／0／0／0 |
| 完成後 source parser versions | 164 份 0.1.4；62 個目標來源 0.1.7 |
| 目標 current 變更 | 482 筆；僅 `monitoring_type` 欄位 |
| clone 寫入前 backups／來源 archive 缺檔或 SHA 不符 | 62／0 |
| 目標 records 的 original、source_location、source_text、初始解析版本、verified、state | 全數保留 |
| clone 新增的 analysis flags | 遷移後全數預設納入；重解析未更動 |
| 非目標 records 未預期變動 | 0 |
| 原有 changes 歷程 | 1583 筆逐筆相同；另新增 482 筆解析歷程 |
| 完成後全庫 state／analysis flags／verified 非空 | 3312 draft／3312 納入／0 |
| 目標製程列 site 空白／operator 非空 | 482／134 |
| clone SQLite `integrity_check` | `ok` |

482 個目標 record 的逐欄辨認狀態仍是每欄 total 482、checked 0、correct 0、incorrect 0、pending 482、not applicable 0；accuracy 未評估。482 列沒有明確 site，故不猜廠別，也沒有自動確認。原有 1583 筆歷程逐筆未改寫；482 筆新增解析歷程均記錄自動更新欄位為 `monitoring_type`。正式 DB、正式服務均未升版、重解析或啟用。

clone 的 SQLite DB、Word source archives、62 份寫入前 backups 及 session key 均留在系統 Temp，不在 repo。PM 的獨立程序對該 Temp 目錄回報 Access Denied；本文件提供無列級個資摘要供覆驗，未改 ACL、複製公司資料到 repo 或嘗試繞過限制。PM 可另以正式庫唯讀 SHA 及表格計數獨立核對其未變更狀態。

## 測試與頁面檢視

- `.venv\Scripts\python.exe -m unittest discover -s tests`：82 tests passed。新增回歸涵蓋 PM 反例：三勾且檔名含製程的 C06D 不推廠別；多人來源不 last-win；表格局部操作者不外洩到其他表；同列多人字串不論點位是否含方法前綴均留空待核；點位人員衝突不進 CRR；選廠範圍套用到 pending／Isolator／排除；Grade A 正規化後採樣月格只取該格 record IDs；目前 CFU 與「結果原文（目前值）」分開顯示，未把可人工編輯的 current 值稱為不可變原值；CRR 月格明細保留參與／待核來源及返回期間，包含「全部廠別」空篩選返回；製程兩矩陣各有獨立捲動條，明細不使用寬版。
- `.venv\Scripts\python.exe -m compileall -q em_mvp tests`、`git diff --check`：通過。
- 另以唯讀 SQLite URI 對原始暫存副本逐一解析保留來源：Parser 0.1.7、226/226 source、3312 parsed rows、精確雙勾 62/482 rows、缺檔／解析錯誤 0；唯讀檢查前後原始暫存 DB SHA 相同。這項 memory parse 沒寫 DB；正式 reparse 另在上節新 clone 執行。
- Flask test client 以臨時合成資料產生頁面內容，確認製程矩陣、標準化 Grade A 採樣明細、CRR 月份明細；HTTP 渲染及路由回歸通過。另以範本輸出檢查每張主矩陣的上方軌道與原生下方容器按 panel 配對、同步腳本讀取下方實際 `scrollWidth`／`clientWidth`，並對明細頁使用一般寬度。這些是程式、靜態 HTML 及 test-client 核對，並非互動 GUI／實際 resize 視覺驗收。
- 另以合成資料渲染排除清單、逐筆恢復表單及排除後報表頁面；合成資料不在 3312 筆正式資料副本內。新的三張製程回歸預覽亦以一次性臨時 DB 合成，不使用公司來源。
- 可檢視的靜態 HTML 預覽存於 `C:\Users\ES-QC-022\AppData\Local\Temp\em007-stage-cn24znpv\previews`，未加入 repo；包括 `em007-process-matrix-regression.html`、`em007-process-sample-detail-regression.html`、`em007-process-person-month-regression.html`、`em007-process-person-day-return-regression.html`。三種明細都測試從「全部廠別」進入後保留空的返回廠別篩選。
- 互動 staging 啟動限制：先前 `functions.exec` 內的 `exec_command` 呼叫 PowerShell `Start-Process`，嘗試以隱藏程序啟動既有 Flask staging，監聽 `127.0.0.1:8766`。執行回覆摘要為 `exec_command failed: CreateProcess ... Rejected(... "blocked by policy")`。目前保留的執行紀錄沒有完整 CreateProcess payload，因此無法提供被拒絕命令的逐字全文；已能確認的是上述工具、PowerShell 啟動方式、hidden 參數與 localhost:8766 目標。沒有改用其他 launcher、瀏覽器或 HTTP 方式再試。PM 的唯讀靜態 `file://` 預覽另遭瀏覽器 URL 政策拒絕；依要求未繞過。互動 GUI／視覺 resize 驗收仍未完成。

## PM 驗收與正式啟用界線

PM 已明確接受 EM-007 程式修補階段，並核對本文件中的隔離 clone 計數／版本摘要與正式 DB 未變 SHA 邊界。PM 無法直接讀 Temp clone，所以此核對不是對 clone 檔案的直接資料庫覆驗。完整 EM-007 尚未接受：正式 DB 尚未升版、未重解析 62 個來源，正式服務未啟用或重載。正式 D6 仍暫緩；互動 staging 啟動及 `file://` 預覽均遭政策拒絕，不能以直接正式啟用取代 staging。PM 完成實際 GUI 唯讀驗收及最終接受後，才正常 commit/push，並提供 SHA。

PM 曾嘗試將程式階段接受記錄留言至 GitHub issue #6，回覆 `401 Requires authentication`；留言沒有成功。本地驗收文件已更新；未改憑證、ACL 或改用其他身分代發，因此此結果尚未備份至 GitHub。
