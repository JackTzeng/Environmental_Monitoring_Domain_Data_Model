# EM MVP 合成預覽

狀態：PM 判定「MVP 試用候選可交付」。EM-008 核心修補、核心五檔 SHA、啟停封裝修補均已階段接受；預覽保留運行中。QA 已實看矩陣、製程 CRR、輸出、Sheet 核對頁並完成四檔合成資料夾匯入。其餘有限 runtime 覆驗仍等待平台核准；確切待核准動作與理由尚未取得，因此不宣稱完整驗收。正式 OAuth 未驗證，正式資料庫未升版或啟用。

## 預覽入口與隔離範圍

預覽目前運行中，可在 [http://127.0.0.1:8876](http://127.0.0.1:8876) 檢視。已完成一次停止、確認埠釋放、再啟動循環；目前啟動證據：

- `/health`：app `0.6.0`、parser `0.1.7`。
- 啟動器 PID `21916`（專案 `.venv` Python）；其直接子程序 PID `10084`（Codex runtime Python）執行 `-m em_mvp.app --port 8876`。
- `netstat` 唯一 listener：`127.0.0.1:8876`、PID `10084`。
- 合成資料庫固定於：

```text
C:\Users\ES-QC-022\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\Codex\EM-MVP-Preview-EM008-20261002
```

啟動驗證時的隔離資料庫有 10 筆合成紀錄（6 confirmed、4 draft、1 analysis-excluded）。QA 驗收只可在此合成庫新增資料，紀錄數之後可能增加。

如需自行重啟，在專案目錄執行：

```powershell
.\preview\Start-MVP-Preview.ps1
```

啟動器會核對合成資料識別、完整資料路徑、健康版本、launcher／listener 父子程序、啟動記錄及唯一 loopback listener；埠已占用或任一項不符便停止。服務 log、SQLite 備份、來源副本、session key、啟動識別檔都留在隔離資料夾。Repo 不含正式資料庫、公司來源副本、憑證或服務 log。

只停止這個已識別的預覽服務：

```powershell
.\preview\Stop-MVP-Preview.ps1
```

停止腳本會先核對 launcher／listener 父子 PID、解譯器、app 命令、port、loopback listener 及資料路徑；只停止通過核對的程序，保留資料與備份。

## 版本與合成資料

隔離庫使用 app `0.6.0`／parser `0.1.7`。首次建庫 manifest 為 `preview-seed.json`，三份 seed CSV 建立 10 筆合成紀錄，含 2026 年 6、7 月、`<5`／`<10` 限值、`3(1mold)`、警戒／行動案例、人員監測日期、待核對草稿及可還原的排除案例。

管理者 XLSX 範例為 [`preview/fixtures/manager-sheet-preview.xlsx`](../../preview/fixtures/manager-sheet-preview.xlsx)，兩個指定分頁均為合成列，含一廠匹配／補空欄、新採樣候選及未映射待核對列。資料夾匯入範例在 `preview/fixtures/folder-import/`，含兩份合成 DOCX（環測、製程）及兩份 CSV；DOCX 已由現行 parser 實讀並核對主要欄位值。Seed CSV 在 `preview/fixtures/seed/`。

`seed_preview.py` 遇到既有目標資料夾會停止，不會重建或覆寫。一般啟動器也會核對預覽 ID、`synthetic_only` 標記及完整資料路徑。QA 正在覆驗期間請勿重新建庫或清除預覽資料。

## GUI 檢視步驟

1. 在「輸入資料」頁將資料夾路徑填為 `preview\fixtures\folder-import`，勾選「一併讀取 XLSX／UTF-8 CSV」，執行資料夾匯入。系統會批次讀取兩份 Word（環測、製程）及兩份 CSV；所有匯入只寫入合成預覽庫並留備份。
2. 開「資料庫」`/records?view=matrix&year=2026`，查看 6、7 月環測值與趨勢。`3(1mold)` 保留原文，支援的數值總 CFU 是 3。
3. 開 `/records?view=process&start=2026-06&end=2026-07`，檢視合成人員的兩個月 Grade A 人日與 CRR，再點入月份／人日明細。
4. 開 `/records?view=excluded`，查看合成排除案例，可用頁面操作還原；資料與歷程仍只寫預覽庫。
5. 開 `/reports?start=2026-06&end=2026-07`，再點 HTML 報表。正式輸出路由只含已確認紀錄。
6. 開 `/sheet-reconcile` 上傳 `preview\fixtures\manager-sheet-preview.xlsx` 並標示完整快照，查看可補空欄案例及待核對 IC 列。

這個預覽只連到上列合成庫，不會讀寫正式資料庫。啟動程序會停用 Google OAuth；正式 OAuth 尚未驗證，Sheet 對帳驗收請使用合成 XLSX。不得在此流程匯入公司 Word、正式 Sheet 快照或其他真實來源。

## 工程檢查與待驗項目

啟停腳本 PowerShell 語法檢查通過；兩份 DOCX 已經 parser 實讀，日期、廠別、監測類型、方法及 CFU 核對通過。停止／埠釋放／重新啟動循環及 `/health`、程序父子關係、唯一 loopback listener 和合成資料路徑均已實證。QA 在 GUI 實匯兩份 Word 與兩份 CSV，各新增一筆草稿；`3(1mold)` 原文及 Word 表格來源位置保留。其餘重匯去重、Sheet 補值與磁碟備份持久性覆驗尚未完成，QA 回報目前等待平台核准；平台待核准事項與理由未知，不會以其他方式繞過。
