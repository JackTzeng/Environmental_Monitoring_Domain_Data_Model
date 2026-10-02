# EM-008 QA 第一輪修補覆驗

日期：2026-10-02（Asia/Taipei）。
階段結論：**退回；目前不能驗收 EM-008。** 原 12 項中 11 項通過本次指定合成覆驗；QA-01 的 G 空白／未知目的反例已修復，但同一完整性缺口仍可對缺方法／缺年份的陽性子列誤補並採用 CFU0。

依 PM 明確確認的第一輪凍結候選覆驗；套用 Ponytail full，只核原 QA-01～12、逐欄來源追溯及必要保護／整合，不新增功能或擴審其他專案。沒有代修、建立 worktree、讀公司明細／正式DB／憑證、啟動 staging／正式服務或繞過 Temp／file:// 限制。出現足以退回的 P1 後，完成指定檢查便停止擴搜。

## 基線

分支 codex/em-mvp-spec；HEAD 3b303050249585b633cff2601c4d6cc7b316cb47。
原 QA 報告保持不變，SHA-256：
602c1ab675444055192ec7fe4dcd9b9565c6350929e37445b67751a5f02708d3。

開始與完成覆驗的 PM 指定 12 檔 SHA-256 全部吻合（詳細清單見本報告末尾）。共享檔案含既有 EM-007 差異，按本工單範圍判讀；交付包等無關新增文件不當候選漂移。

## 逐項覆驗

| 原項目 | 本次結果 | 獨立實測證據 |
|---|---|---|
| QA-01 | **部分修復，仍有 P1** | G=IC 的 N3/O3/Bacillus 子列與前列零候選現在一群 pending，保留全部陽性證據；G空時一群 CFU3，無誤補0。但同B後列僅 F空或 C年空仍被分離，前列 new CFU0 且可由真 store 採用。見 R1-01。 |
| QA-02 | 通過 | Word CFU0／原結果0、不同監測類型、TNTC與Sheet3均 conflict、無補值；真正空欄仍可 supplement。0、TNTC、<1及空白維持不同結果。 |
| QA-03 | 通過 | 先採用 CFU0，再讀同指紋 CFU9：顯示 conflict／CFU差異，既有記錄保持0、不新增、不覆寫。 |
| QA-04 | 通過 | 不同 B 的同日重採可各自採用為兩筆；重新讀取指回正確記錄，不重複新增；後快照只見B002時不誤配B001。 |
| QA-05 | 通過 | 歷史頁隱藏採用及補值；舊POST被最新read ID檢查拒絕，前置拒絕不新增備份或資料。讀取在備份與交易間漂移亦由交易內檢查阻擋。 |
| QA-06 | 通過 | B:O及S:Y共21個消耗／菌鑑欄單獨改標題，API21/21、XLSX21/21均拒絕；原N/O交換不再讀錯CFU。 |
| QA-07 | 通過 | 相鄰兩月 chart產生SVG；真實test-client /reports及/report.html均HTTP200。 |
| QA-08 | 通過 | 同採樣環測／汙染後環測反序皆一群 pending、相同fingerprint，完整保留兩菌種子列及N/O，沒有任選分類。 |
| QA-09 | 通過 | XLSX O公式快取0／N公式快取3與API數值的sample、fingerprint及digest相同；N或O無快取皆明示缺快取、N2/O2位置並待核，不推0。 |
| QA-10 | 通過 | 相同列內容共用content ID但各次read ID不同，完整性、來源、時間與證據各自保留；未完整XLSX後完整API可使用完整讀取。legacy→v6只作記憶體隔離覆验。 |
| QA-11 | 通過 | 当前partial且previous完整時不報刪列；真頁面顯示未確認完整、missing=0，没有缺少採樣清單。 |
| QA-12 | 通過 | 無candidate、合法CSRF的POST回302并顯示明確未選候選；沒有呼叫採用／補值寫入或備份。 |

上述「通過」限於合成及記憶體邏輯，不代表正式部署或實際OAuth／GUI通過。QA-01 的精確 G 案例雖修復，不能據此接受仍不完整的整體補零保護。

## R1-01 [P1] QA-01 同根因尚未封住：缺關鍵欄的陽性子列仍允許補零及採用

### 最小輸入

完整兩分頁快照，三廠有以下兩列；一廠只有合法標題。

| 欄 | 第2列 | 第3列 |
|---|---|---|
| B | B-001 | B-001 |
| C/D/E | 2026/6/3 | 2026/6/3 |
| F | 落菌法 | 空白 |
| G | 環測 | 環測 |
| H | H-001 | H-001 |
| I/J | 合成同一操作者／空 | 同左 |
| K/L/M | C01/A/P01 | 同左 |
| N/O | 空白／0 | 3／3 |
| U | 空白 | Bacillus |

另一已實測變體：第3列 F正常，只把 C年改空白，其餘陽性證據不變。

### 預期

後列與前列有相同 B/H 及其他採樣脈絡，但方法或日期缺失，不能證明完整且無矛盾的採樣群。須保留陽性待核證據並阻擋前列推0／採0，不能自行判定後列與前列無關。

### 實際

- F空：第2列群 new、CFU0、reasons=[]；第3列另成pending「F方法空白」。
- C年空：第3列pending「C/D/E日期缺漏或不合法」；第2列群仍new、CFU0。
- 兩例均以真實 API adapter／store採用函式及記憶體SQLite確認：成功新增 draft，CFU0。
- 採用來源證據只包含第2列；field_sources.cfu_count只有N2/O2；zero_inference.species_cells_S_Y=[]。第3列 N3/O3/Bacillus仍在整份快照中，卻未進入採用群的零值判定或採用證據。

### 位置與影響

- em_mvp/sheet_reconcile.py:245：245–256將缺CDE/F/M的列放進loose_rows。
- em_mvp/sheet_reconcile.py:281：同B上下文檢查排除pending fingerprint。
- em_mvp/sheet_reconcile.py:332：332–347只檢查剩下的有效群，仍產生零推定。
- em_mvp/store.py:562：562–581重新計算後仍接受new群，建立錯誤CFU0 draft。

影響與原 QA-01 相同：完整來源中有未解的同B陽性子列，陰性候選仍可落入草稿。之後確認會造成陽性／CFU與統計錯誤。本輪已用兩個缺欄變體證實，足以退回，不再擴搜其他缺欄排列。

### 可重跑的純記憶體重現

~~~python
import ast, inspect, sqlite3, json
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
from em_mvp import store
from em_mvp.sheet_reconcile import (
    HEADER_ROW, SHEETS, parse_api_ranges, sample_groups, snapshot_digest
)
from tests.test_em008 import values

tree = ast.parse(inspect.getsource(store.initialize))
schema = next(n.args[0].value for n in ast.walk(tree)
              if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute)
              and n.func.attr == "executescript")
uri = "file:em008_qa_round1_remaining?mode=memory&cache=shared"
anchor = sqlite3.connect(uri, uri=True)
anchor.executescript(schema)

def connect(*args, **kwargs):
    db = sqlite3.connect(uri, uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db

with patch.object(store, "connection", side_effect=connect), \
     patch.object(store, "backup", return_value=Path("MEMORY_BACKUP")):
    for missing in ("method", "year"):
        with closing(connect()) as db, db:
            for table in ("sheet_adoptions", "records",
                          "sheet_snapshot_reads", "sheet_snapshots"):
                db.execute("DELETE FROM " + table)
        rows = [
            values(cfu="", colonies="0"),
            values(cfu="3", colonies="3", organism="Bacillus",
                   **{missing: ""}),
        ]
        snapshot = parse_api_ranges({
            title: [HEADER_ROW, *rows] if title == "三廠管理者更新"
            else [HEADER_ROW] for title in SHEETS
        }, complete=True)
        groups = sample_groups(snapshot)
        for g in groups:
            print(missing, [r["row_number"] for r in g["rows"]],
                  g["status"], g["sample"], g["reasons"])
        candidate = next(g for g in groups if g["status"] == "new")
        saved = store.add_sheet_snapshot(
            ".", "synthetic", snapshot_digest(snapshot), "google-api",
            True, snapshot["rows_by_sheet"], {}, snapshot["evidence"])
        result = store.adopt_sheet_candidate(
            ".", saved["id"], candidate["fingerprint"])
        record = store.get(".", result["record_id"])
        evidence = json.loads(record["source_text"])
        print("ADOPTED", missing, record["state"],
              record["current"]["cfu_count"],
              [r["row_number"] for r in evidence["rows"]],
              evidence["zero_inference"]["evidence"]["species_cells_S_Y"])
        # 現候選實際：draft 0 [2] []；修後不應存在可採用的零群。
anchor.close()
~~~

實際關鍵輸出：method及year兩例均「ADOPTED ... draft 0 [2] []」。此重現沒有磁碟DB、Temp或真正備份，未修改候選程式。

## 逐欄追溯及重要保護

- 合成API metadata的兩廠tab／sheetId分别0、526085303，已檢查field_sources C2/D2/E2、G2、N2/O2、原值／公式快取、廠別與監測映射／count衍生來源。採用及補值證據保存read ID、content ID、spreadsheet ID與原始列；推0有規則版本與N/O、S:Y證據。真Jinja頁能展開field_sources並顯示C2/N2。
- XLSX無法證實Google原sheetId／spreadsheet ID時保留未知（sheet_id=None、spreadsheet_id空），沒有捏造；tab及儲存格位置仍可追溯。此為來源限制。
- R1-01使逐欄證據只追到被選群而漏掉相同B未決陽性列，所以追溯結構存在仍不等於補零完整性通過。
- 原子回滾、重送拒絕、人工清空、verified、state、analysis排除及來源身份保護，均在真實產品SQL／記憶體交易覆驗；磁碟backup以mock替代，未宣稱備份I/O通過。
- legacy→v6 初始化僅使用合成記憶體schema及資料；未操作正式DB或正式migration。

## 必要回歸與限制

本QA實跑既有測試35項，全部通過：EM008可無Temp執行的15項、EM007必要只讀12項、reporting8項。
EM008另12項磁碟／TemporaryDirectory測試沒有原樣執行；其對應必要行為以上述memory／test-client覆驗。EM007另2項磁碟測試也未原樣執行。不能把替代覆驗寫成27/27或109/109全套獨立重跑。
git diff --check exit0，僅有既有LF/CRLF提示，沒有新增產品修改。

未驗證：真實本機OAuth授權／refresh／API、公司Word/Sheet明細端到端、互動GUI、staging／正式服務、磁碟migration／備份／持久化。此前政策限制仍有效；本輪未再次嘗試受拒路徑。

建議PM只針對剩餘P1補齊零推定的跨未決子列保護，再凍結新SHA覆驗；其他指定已通過項目不無故擴搜／重測。現候選不能作EM008接受或正式資料採用版本。使用者檢視MVP啟動包由PM統一安排，本QA沒有啟動或代修產品。

## 12檔候選 SHA-256（驗證前＝驗證後）


- em_mvp/sheet_reconcile.py：68482e55723785bdffdecd3cfa39750f657d3601551f8009167f375793abbae3
- em_mvp/store.py：0a03fc925d05e4ac0fbb8b45c0a6ecfe1730ee668cfb7628ec47836bf3adf734
- em_mvp/app.py：f3c0c7780c7bc47e76eafd44d1e4d62a114d149e5303ce505fcc77e220c9c4c8
- em_mvp/templates/sheet_reconcile.html：83ec852766c49f7f909104a4d06875f690912f7b12872f7d396e779b0ccabf2e
- em_mvp/templates/base.html：1d1f8328a66cf3e1d0546f5069267d5743db1e784c3a23ea03ccddf039c669f5
- em_mvp/templates/input.html：c7404f14d8e7bfb0d225eff9f142bfda6c47085933450170e20388a213711ce6
- .gitignore：ce5cdb15d89144d3f11bfcde9277b185731c3fc2f1450e30abf4598b04e2f498
- README.md：d893247f28afc18412ad8646eacebfc8f5928fd7542fef004c831d86b9168167
- tests/test_em008.py：76067b8112ab1d8a96cca6a47098ec6320cf1af1c2e719878b7d3e29c6878ea8
- docs/work-orders/EM-008-google-sheet-reconciliation.md：96ebd4505f47098ebc3d53dc6185185ac0374c0b2e7e21f742cf37885747e5be
- docs/work-orders/EM-008-QA-round1-fixes.md：d31bd3d7e97de0fe20625b7c6ad6e069849bacf2fd8c7bca315077925efe41ff
- docs/acceptance/EM-008-results.md：0e685337f9b9cacd7c3b6905bc8e1f9ab9f0cd8ee58c240fa1eff23709827a42
