# Environmental Monitoring MVP

第一版：Windows 桌面 Excel／Word、VBA、單人操作，不依賴 LLM。

## 資料流程

公司 Word 資料夾（唯讀）＋Google Sheet 匯出 XLSX
→ VBA 匯入暫存
→ 人工核對、重複／衝突處理
→ Excel 結構化明細表／監測事件表
→ 月報矩陣、動態原生圖表、PDF。

## 規格

[EM MVP 規格與可行性評估](EM-MVP-SPEC-v0.1.md)

第 12 節為最新決策：以既有 Word＋Google Sheet 流程為基礎。例行環測與製程監測分開管理；Word 優先與 Sheet 補缺只適用於已確認的例行環測資料。月彙總不能反推成逐筆樣本。

## 目前狀態

已完成 PM 規格、資料模型、匯入契約、必要驗收案例與技術可行性評估。尚未交付可執行 .xlsm；尚未測試 VBA 解析真實報告或直接登入 Google Sheet。

## 下一個開發切片

一個月份、一廠、一種方法，使用真實 Word 與相應 Sheet 來源完成匯入、核對、提交、人工修正及動態圖表。開始前核對目前 QC Word 根目錄、來源 Sheet／分頁與資料粒度。

Google Sheet 首版以匯出檔輸入；直接線上讀取另需完成登入與權限管理。Excel 為唯一寫入主檔，不做雙向同步。
