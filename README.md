# Environmental Monitoring MVP

第一版目標：GUI 讀取公司 Word 與 Google Sheet 匯出檔，人工核對後入庫，產出每月矩陣與趨勢圖；不依賴 LLM。2026-10-01 新增「未來多人使用」要求，建議採本機瀏覽器 GUI，後續可部署公司內網。

## 資料流程

公司 Word 資料夾（唯讀）＋Google Sheet 匯出 XLSX
→ Python 匯入暫存（建議方案）
→ 人工核對、重複／衝突處理
→ 系統資料庫的採樣明細／監測事件
→ 月報矩陣、月份趨勢圖、Excel／HTML／PDF 匯出。

## 規格

[GUI 可行性、技術債與多人擴充（最新建議）](EM-GUI-FEASIBILITY-v0.2.md)

[GitHub 參考專案審查與採用範圍](REFERENCE-PROJECTS.md)

[Excel／VBA MVP 規格與既有報表基準](EM-MVP-SPEC-v0.1.md)

原 v0.1 保留為 VBA 比較基準；GUI 尚屬架構評估，資料及驗收需求延續。例行環測與製程監測分開管理；Word 優先與 Sheet 補缺只適用於已確認的例行環測資料。月彙總不能反推成逐筆樣本。CRR 與點位矩陣定義見 v0.1 第 13 節。

## 目前狀態

已完成 PM 規格、匯入契約、驗收案例、兩個 GitHub 參考審查與 GUI／VBA／多人擴充比較。尚未交付 GUI、資料庫或可執行 .xlsm；尚未完成新系統的真實資料驗收或直接登入 Google Sheet。

## 下一個開發切片

一個月份、一廠、一種已知 Word 版型，使用真實 Word 與相應 Sheet 來源驗證 GUI 匯入、核對、提交、人工修正及兩張矩陣；月趨勢另用至少三個可取得的連續月份。開始前核對 QC Word 根目錄、來源 Sheet／分頁與資料粒度。

Google Sheet 首版以匯出檔輸入；直接線上讀取另需完成登入與權限管理。GUI 方案以系統資料庫為唯一寫入來源，Excel 用於核對與匯出；不做雙向同步。
