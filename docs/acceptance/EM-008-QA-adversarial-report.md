# EM-008 第一切片獨立 QA／對抗驗證報告

日期：2026-10-02（Asia/Taipei）。結論：**退回修補，不接受目前候選。**
本次有 7 項 P1、5 項 P2 的獨立合成反例。工程宣稱的 15／97 項測試通過不足以證明本候選可接受。

## 範圍與信任邊界

只審本專案 EM-008 及其必要的 EM-007 排除／製程／報表整合；沒有擴審 docs/research 或其他專案。先讀工單與工程結果，再獨立追查候選程式、執行既有可讀測試及新反例。沒有改候選程式、派工 Luna、建立 worktree、啟動 staging、file:// 或正式服務；沒有讀寫正式 DB、公司原始 Word／Sheet 明細、OAuth 秘密、Google Sheet、ACL 或憑證。

所有動態輸入均為 tests/test_em008.py 的合成 fixture 或純記憶體 XML／SQLite。SQLite 採用真實候選 transaction 函式，但 connection 指向記憶體，backup 回傳合成 Path；**磁碟備份、檔案持久化、正式 migration 未實測**。Flask test client 與 mock 不代表互動 GUI 或真實 OAuth／API 通過。

## 候選基線與漂移檢查

工作目錄：C:\Users\ES-QC-022\OneDrive\文件\ChatGPT\數位QA-子專案-EM系統建立
分支：codex/em-mvp-spec
HEAD：3b303050249585b633cff2601c4d6cc7b316cb47

工作樹含未提交 EM-007／EM-008；共享檔案按功能範圍判讀。開始與完成動態驗證後的 HEAD、分支及以下 11 個 SHA-256 均一致，且全部等於 PM 凍結值：

| 檔案 | 驗證前＝驗證後 SHA-256 |
|---|---|
| em_mvp/sheet_reconcile.py | e37511126ded3ff65d631916192d629dcc883bbd45a60915fabb7b6d9a5b9dd4 |
| em_mvp/store.py | 211ccc48ddcdb9ec74c74e4a3b208b59f02fc913702ee687f3b98ab4f934e032 |
| em_mvp/app.py | 2e07fe1782cd1e529682a10515b59228accaf09b2f8b47d2916b24eb33d791d3 |
| em_mvp/templates/sheet_reconcile.html | 34b65bdbff62d9bd73cb66c921d162e80900905494c5b6f95a3fcc4e977fc99a |
| em_mvp/templates/base.html | 1d1f8328a66cf3e1d0546f5069267d5743db1e784c3a23ea03ccddf039c669f5 |
| em_mvp/templates/input.html | c7404f14d8e7bfb0d225eff9f142bfda6c47085933450170e20388a213711ce6 |
| .gitignore | ce5cdb15d89144d3f11bfcde9277b185731c3fc2f1450e30abf4598b04e2f498 |
| README.md | d893247f28afc18412ad8646eacebfc8f5928fd7542fef004c831d86b9168167 |
| tests/test_em008.py | 8e65e0a45e67dfcb6e2e30662adaaa6bff5fef322a63469881e203dadc188577 |
| docs/work-orders/EM-008-google-sheet-reconciliation.md | 96ebd4505f47098ebc3d53dc6185185ac0374c0b2e7e21f742cf37885747e5be |
| docs/acceptance/EM-008-results.md | e45cf2633c1ef48de4d5f14acc05496db4ad09af1eefadc79a80c8c21f67cf87 |

## 實測結果

| 檢查 | 獨立結果 |
|---|---|
| 既有 EM-008 中 10 項無顯式 TemporaryDirectory 的測試 | 9 通過；1 因 openpyxl Workbook.save(BytesIO) 內部仍建立 Temp 而環境阻擋 |
| EM-008 其餘 5 項依赖磁碟 DB／Temp 測試 | 未執行；未繞過既有政策限制 |
| 必要 EM-007 與 reporting 純記憶體回歸 | 20 項通過 |
| 本 QA 獨立實測既有測試合計 | 29 通過、1 環境阻擋；不是 15／97 全套通過 |
| 原子回滾 | 第 1 選項已 UPDATE 後第 2 選項缺失或版本 99，引發 StaleRecord；兩筆仍 v1、room 空、changes=0，通過 |
| 重送／版本保護 | 成功補值後以舊 record version 重送，StaleRecord；history 僅 1 筆，通過 |
| 人工清空／核對／排除／身份 | 人工先填再清空 room、operator checked／grade not_applicable、confirmed、analysis_included=0 與 reason、source_id/source_text 保持，通過 |
| 完整合法菌種群 | 3 子列、首列 N3、其餘 N 空、每列 O1，只有 1 採樣 CFU3，通過 |
| 其他核心分組邊界 | B 空待核、不同 B 初始分群兩採樣、同 B 不同核心鍵待核、I/J 多人一群待核、無效 CDE 待核，通過 |
| 欄位正確率 | checked=2/correct=1 -> 50%；全部未核對 None；manual 排除 parser accuracy，通過 |
| 第二目標來源失敗 | 第一目標已讀到 N空/O0，第二目標合成 ValueError；整次 read_google_targets 拋錯，沒有返回完整快照，通過 |
| 純記憶體 XLSX adapter | 以 stdlib ZIP/XML BytesIO 完成公式快取反例，沒有建立檔案；結果見 QA-09 |

Temp 阻礙的實際堆疊：tests/test_em008.py:70 -> openpyxl/worksheet/_writer.py:36 -> NamedTemporaryFile -> FileNotFoundError: No usable temporary directory found。此為環境未完成，未算產品 assertion 失敗或通過；未搬移 Temp、提升測試權限或繞過 staging 政策。沒有直接執行需要磁碟的完整 15／97 指令，也不宣稱重跑了全套。

## 發現（按嚴重度）

### QA-01 [P1] 同採樣的不完整陽性子列被剝離，仍可產生錯誤 0

最小重現：完整快照兩列，B/CDE/F/H/K/L/M 全相同。第 1 列 G=環測、N空、O0；第 2 列 G空（或 IC）、N3、O3、U=Bacillus。

預期：後列有 N 正數、O 正數及菌鑑證據，整個採樣待核，不允許補 0。
實際：第 1 列群 status=new、CFU0、reasons=[]；第 2 列分成另一 pending 群。完整快照仍顯示可採用的零候選。

證據：em_mvp/sheet_reconcile.py:167（167–172 移入 loose_rows）、:193（排除 pending）、:226（只檢查剩下的有效群）。完整可重跑片段見附錄 A。
影響：具陽性來源的同一採樣可能被採成陰性草稿；之後 confirmed 會污染陽性／CRR統計。後列並未被丟掉，但保留在另一 pending 群不能使前列零候選安全。

### QA-02 [P1] Word 與 Sheet 的非空結果／監測類型差異未列衝突

最小重現：Sheet CFU3；唯一 Word 同核心採樣，result_raw=0、result_type=count、cfu_count=0，room/grade/operator 空。另把 Word monitoring_type 設為製程監測而 Sheet 為環測也重現。

預期：不同非空 CFU／監測類型須顯示 conflict，阻擋「安全補值」。
實際：status=supplement、reasons=[]，建議並成功補 room/grade/operator；CFU差異被略過。非空結果不被覆寫，但不能宣称兩來源一致或安全候選。

證據：em_mvp/sheet_reconcile.py:284（compared_fields 僅 site/room/grade/batch_no/operator）、:304（304–316）；em_mvp/store.py:431、:445。附錄 A、B。
影響：陽性 Sheet／陰性 Word 差異沒有呈現，可能長期保留錯誤統計結果。monitoring_type 差異也會掩蓋採樣分類錯配。

### QA-03 [P1] 已採用 fingerprint 遮住新快照的結果變更

最小重現：完整 S1 的 B001、N0/O0 採為 draft；S2 同採樣 fingerprint、N9/O9，無新增採樣。

預期：維持一採樣，保護已有人工值及狀態，但顯示新來源 9 與原記錄 0 的差異／待核，不自動覆寫。
實際：S2 status=already_adopted、reasons=[]；原記錄 CFU0，沒有新CFU衝突或更新候選。採樣去重成功，但來源變更對帳被短路。

證據：em_mvp/sheet_reconcile.py:263（263–266），直接 continue；em_mvp/store.py:484（484–486）。附錄 B。
影響：Sheet後續修正陽性結果不會進入差異核對，可能維持過時陰性值。

### QA-04 [P1] Sheet 草稿被當成 Word，阻擋或誤併不同 B 的合法重採

最小重現 A：同日同廠同方法同點位、H相同、其他值相同，但 B001/B002 兩採樣。初始兩群均 new；採 B001後採 B002。
實際 A：第二次 StaleRecord，只保存 1 採樣；B002成 pending，理由「Word 無 B」，但該紀錄實際 origin_kind=sheet，B已保存在 sheet_adoptions/source_text。

最小重現 B：先採 B001，後續完整快照只見 B002。實際 B：B002 status=matched、word_record_id 指向 B001；B002 fingerprint 未採用，卻不再顯示 new。

預期：不同 B 的已確認來源採樣身份不能誤併，兩筆合法重採都應能保留；Sheet来源不应丢弃已有B身份再套用Word無B規則。
證據：em_mvp/sheet_reconcile.py:269（269–283 所有 records 都當候選）、:301（301–316）；em_mvp/store.py:378、:486。附錄 B。
影響：合法重採漏採／被當成原採樣，採樣總數及日後分母錯誤；不能只靠初次 sample_groups 分成兩群來驗收。

### QA-05 [P1] 新來源快照存在後，舊預覽仍可直接採用／補值

最小重現 A：S1 N3/O3；S2 同身份 N9/O9 已保存；持舊 S1 id/fingerprint 採用。
實際 A：成功新增 draft CFU3，沒有來源版本漂移警告。

最小重現 B：唯一 Word結果空、v1；保存 S1 N3與S2 N9後，以舊 S1選項/v1補值。
實際 B：updated=1，CFU3。另 S1 roomC01／S2 roomC99時舊值也成功填 C01。

預期：採用前檢查來源快照版本／新快照差異；舊預覽有後續差異時應重新預覽或清楚阻擋，不能只檢查 Word version。
證據：em_mvp/store.py:398（398–406 只按 id 讀快照）、:429、:482。附錄 B。
影響：新來源已在本機，操作舊頁仍寫入過時候選；record version 保護無法防止此種來源漂移。若PM允許歷史快照採用，也須明確區分歷史採用並提示與新來源衝突，目前沒有此機制。

### QA-06 [P1] 關鍵欄標題錯置仍被當合法來源，CFU讀錯

最小重現：固定兩分頁，保持 C=年／F=檢測方式，但將 N/O 標題交換。資料在第14欄（O菌落數標題）=1，第15欄（N總菌數標題）=3。

預期：拒絕與固定欄 schema 不符的標題，或按驗證後的欄位對照取總菌數3；不能把菌落數1當總CFU。
實際：parse_api_ranges 接受；sample_groups status=new、cfu_count=1、reasons=[]。

證據：em_mvp/sheet_reconcile.py:99（只驗 C/F）、:93、:76、:209。附錄 A。
影響：匯出／來源欄位錯位可靜默產生錯CFU；API與XLSX都共用此不完整標題驗證。

### QA-07 [P1] 兩個相鄰有值月份使報表與匯出 HTTP 500

最小重現：chart(["2026-06","2026-07"], [3,4], "QA")；亦以兩個相鄰月份的合成 confirmed紀錄呼叫真實 /reports、/report.html。
預期：顯示／匯出SVG趨勢與報表。
實際：NameError: name 'snapshot' is not defined；兩個路由 HTTP500。

證據：em_mvp/app.py:132（未提交 diff把 if previous 改為 if previous and snapshot["complete"]，chart沒有snapshot）；呼叫點 :802、:810。附錄 C。
影響：必要既有月報及下載回歸失效，屬候選共享app整合問題，不是擴成其他工單稽核。

### QA-08 [P2] 合法 G 衝突依首列任選，列重排改變分類

最小重現：同採樣兩菌種列，首列 G環測/N3/O1，次列 G汙染後環測/N空/O1。
預期：同一採樣內G矛盾待核；排序不决定分類。
實際：兩種排序均一群、CFU3、status=new、reasons=[]，fingerprint相同；正序例行環測、反序污染後環測。

證據：em_mvp/sheet_reconcile.py:138（fingerprint不含G）、:174（保留首列identity）、:238。附錄 A。
影響：刷新／列排序造成監測分類改變；採用後又受 QA-03 短路遮住。修正應保留一採樣並標示群內衝突，不能新增第二採樣代替衝突處理。

### QA-09 [P2] 有效公式快取的 XLSX 與 API 不等價，快取缺失未清楚辨識

最小合成 XLSX：固定兩表／正常標題，N空，O2 XML為 <c r="O2"><f>0</f><v>0</v></c>，complete=True；API同來源 unformatted O=0。
預期：已有效計算的相同欄位值按共同採樣語意核對；未有快取時明確提示，並不推0。
實際：API new/CFU0；XLSX cached0仍把O當 "=0"，pending。無快取與有快取均只報O非數值。
另一實測：N公式SUM(1,2)、有效快取3，XLSX仍pending；API數值3則new/CFU3。

證據：em_mvp/sheet_reconcile.py:60（data_only=False）、:72、:216、:224。
影響：兩讀取方式對同有效快取資料產生不同候選，現行XLSX替代路徑不能涵蓋公式來源。安全性上未錯補0，但功能與錯誤訊息未達共同adapter要求。
本反例以 stdlib ZipFile(BytesIO)產生完整最小OOXML包，沒有用openpyxl.save或Temp；公式測試只讀合成包。

### QA-10 [P2] 相同內容去重吞掉後續完整性／讀取來源證據

最小重現：N空/O0，同rows先存 incomplete XLSX，後存 complete Google API。
預期：不重複採樣，但後續完整讀取證據應可用，且保留該次讀取的來源脈絡。
實際：第一次 id1/duplicate=False；第二次 id1/duplicate=True；persisted_complete=False、source_kind=xlsx，仍pending，合法完整性永遠不能升級。

證據：em_mvp/sheet_reconcile.py:103（digest只含rows_by_sheet）、em_mvp/store.py:338（338–340直接回舊id）。真實store函式以記憶體SQLite完成。
影響：初次未勾完整後，完整XLSX重送或API相同資料也不能產生正確零候選；最新成功讀取時間／來源證據亦沒有保留。不得簡單改成自動信任complete，須保留可追溯完整性證據。

### QA-11 [P2] 未完整來源仍報刪列

最小重現：上一完整快照有1採樣；當前 complete=False 且無明細，真實 GET /sheet-reconcile。
預期：部分／未確認完整來源不能作「採樣不再出現」的刪列證據。
實際：HTTP200，同時顯示「完整性：未確認」與「較早完整快照未再出現 1」。
證據：em_mvp/app.py:234（234–237 未檢目前完整性）；em_mvp/sheet_reconcile.py:332只檢上一快照。
影響：誤報需人工追查的刪列；沒有實際刪除DB資料。附錄 C。

### QA-12 [P2] 空補值選項造成 HTTP500

最小重現：合法CSRF，POST /sheet-reconcile/supplement，只給 snapshot_id=1、不給candidate。
預期：清楚未選候選／0筆或400錯誤，不寫入。
實際：真實store空選項分支無backup key，路由 KeyError:'backup'／HTTP500；沒有開啟DB。
證據：em_mvp/store.py:420（420–421）與 em_mvp/app.py:326。附錄 C。
影響：不完整請求無法明確回應；沒有證據顯示此反例導致資料遺失。

## 最小重現附錄

以下片段可在本專案以 .venv\Scripts\python.exe -B 純記憶體執行，沒有測試檔寫入。fixture全為合成；不要改成正式data_dir。

### A. 分群／Word差異／標題

~~~python
from tests.test_em008 import values, sheet_snapshot, word_record
from em_mvp.sheet_reconcile import (
    HEADER_ROW, SHEETS, sample_groups, parse_api_ranges,
    match_word_candidates
)

def brief(gs):
    return [(g["status"], g["sample"], g["reasons"]) for g in gs]

# QA-01: 實際第一群 new/CFU0；同採樣陽性後列另成 pending。
print(brief(sample_groups(sheet_snapshot([
    values(cfu="", colonies="0"),
    values(purpose="", cfu="3", colonies="3", organism="Bacillus")
]))))

# QA-02: 實際 supplement，沒有結果差異。
g = sample_groups(sheet_snapshot([values()]))
print(brief(match_word_candidates(g, [
    word_record(result_raw="0", result_type="count", cfu_count="0")
])))

# QA-08: 相同 fingerprint，反序使監測類型改變。
a = values(cfu="3", colonies="1", organism="A")
b = values(purpose="汙染後環測", cfu="", colonies="1", organism="B")
for rows in ([a, b], [b, a]):
    g = sample_groups(sheet_snapshot(rows))[0]
    print(g["fingerprint"], g["status"], g["sample"]["monitoring_type"])

# QA-06: 來源標題總菌數在第15欄，實際卻讀第14欄菌落數1。
header = list(HEADER_ROW)
header[13], header[14] = header[14], header[13]
payload = {t: [header, values(cfu="1", colonies="3")]
           if t == "三廠管理者更新" else [HEADER_ROW] for t in SHEETS}
g = sample_groups(parse_api_ranges(payload, complete=True))[0]
print(g["status"], g["sample"]["cfu_count"], g["reasons"])
~~~

### B. 真實Store函式的純記憶體隔離及採用反例

~~~python
import ast, inspect, sqlite3, json
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
from em_mvp import store
from tests.test_em008 import values, sheet_snapshot, word_record
from em_mvp.sheet_reconcile import (
    sample_groups, snapshot_digest, match_word_candidates
)

tree = ast.parse(inspect.getsource(store.initialize))
schema = next(n.args[0].value for n in ast.walk(tree)
              if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute)
              and n.func.attr == "executescript")
uri = "file:em008_report_qa?mode=memory&cache=shared"
anchor = sqlite3.connect(uri, uri=True)
anchor.executescript(schema)

def connect(*args, **kwargs):
    db = sqlite3.connect(uri, uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db

def reset():
    with closing(connect()) as db, db:
        for table in ("sheet_adoptions", "changes", "records",
                      "sheet_snapshots", "sources"):
            db.execute("DELETE FROM " + table)

def save(rows, complete=True, kind="xlsx"):
    s = sheet_snapshot(rows, complete=complete)
    return store.add_sheet_snapshot(
        ".", "synthetic", snapshot_digest(s), kind,
        complete, s["rows_by_sheet"], {})

def fp(rows):
    return sample_groups(sheet_snapshot(rows))[0]["fingerprint"]

def word(current):
    stamp = store.now()
    with closing(connect()) as db, db:
        db.execute("""INSERT INTO sources(
            id,name,sha256,parser_version,created_at)
            VALUES(1,'synthetic.docx','synthetic','test',?)""", (stamp,))
        return db.execute("""INSERT INTO records(
            source_id,source_location,source_text,original,current,
            verified,warnings,created_at,updated_at)
            VALUES(1,'table1-row2','synthetic',?,?,'{}','[]',?,?)""",
            (json.dumps(current), json.dumps(current), stamp, stamp)
        ).lastrowid

with patch.object(store, "connection", side_effect=connect), \
     patch.object(store, "backup", return_value=Path("MEMORY_BACKUP")):
    # QA-03
    reset()
    old = [values(cfu="0", colonies="0")]
    sid = save(old)["id"]
    rid = store.adopt_sheet_candidate(".", sid, fp(old))["record_id"]
    new = [values(cfu="9", colonies="9")]
    sid2 = save(new)["id"]
    gs = sample_groups(store.sheet_snapshot(".", sid2))
    match_word_candidates(gs, store.records("."), store.sheet_adoptions("."))
    print("QA-03", gs[0]["status"], gs[0]["reasons"],
          store.get(".", rid)["current"]["cfu_count"])

    # QA-04 A：第二筆不同B重採失敗。
    reset()
    rows = [values(), values(batch_id="B-002")]
    sid = save(rows)["id"]
    gs = sample_groups(sheet_snapshot(rows))
    store.adopt_sheet_candidate(".", sid, gs[0]["fingerprint"])
    try:
        store.adopt_sheet_candidate(".", sid, gs[1]["fingerprint"])
    except store.StaleRecord as error:
        print("QA-04A", type(error).__name__, len(store.records(".")))

    # QA-04 B：只有第二B的新快照被誤配至第一B。
    sid2 = save([values(batch_id="B-002")])["id"]
    gs = sample_groups(store.sheet_snapshot(".", sid2))
    match_word_candidates(gs, store.records("."), store.sheet_adoptions("."))
    print("QA-04B", gs[0]["status"], gs[0].get("word_record_id"))

    # QA-05 A：新N9存在後，採用舊N3仍成功。
    reset()
    rows = [values(cfu="3", colonies="3")]
    sid = save(rows)["id"]
    save([values(cfu="9", colonies="9")])
    rid = store.adopt_sheet_candidate(".", sid, fp(rows))["record_id"]
    print("QA-05A", store.get(".", rid)["current"]["cfu_count"])

    # QA-05 B：唯一Word結果空，舊來源補值仍成功。
    reset()
    rid = word(word_record(
        result_raw="", result_type="", cfu_count="")["current"])
    sid = save(rows)["id"]
    save([values(cfu="9", colonies="9")])
    result = store.apply_sheet_supplements(".", sid, [
        {"fingerprint": fp(rows), "record_id": rid, "version": 1}])
    print("QA-05B", result["updated"],
          store.get(".", rid)["current"]["cfu_count"])

    # QA-10：後續完整API讀取去重後仍 incomplete/xlsx。
    reset()
    z = [values(cfu="", colonies="0")]
    a = save(z, complete=False)
    b = save(z, complete=True, kind="google-api")
    saved = store.sheet_snapshot(".", b["id"])
    print("QA-10", a, b, saved["complete"], saved["source_kind"])
anchor.close()
~~~

備份為mock；上述程式不驗證磁碟備份。另實際QA對apply第2選項故意缺失／錯版本回查，全部UPDATE與changes回滾；詳見實測表。

### C. 真實Flask路由的記憶體反例

~~~python
from pathlib import Path
from unittest.mock import patch
from em_mvp.app import create_app, chart
from tests.test_em008 import word_record, sheet_snapshot, values

with patch("em_mvp.store.initialize"), \
     patch.object(Path, "exists", return_value=True), \
     patch.object(Path, "read_text", return_value="QA_MEMORY_SECRET"):
    app = create_app(Path("__QA_MEMORY_ONLY__"))
app.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)
app.logger.disabled = True
client = app.test_client()
with client.session_transaction() as session:
    session["csrf"] = "qa-token"

try:
    chart(["2026-06", "2026-07"], [3, 4], "QA")
except NameError as error:
    print("QA-07", error)

records = []
for i, day in enumerate(("2026-06-03", "2026-07-03")):
    r = word_record(sample_date=day, room="C01", grade="A",
                    unit="CFU/plate", operator="QA")
    r.update(id=i+1, state="confirmed")
    records.append(r)
with patch("em_mvp.store.records", return_value=records):
    print("QA-07 routes", client.get("/reports").status_code,
          client.get("/report.html").status_code)

print("QA-12", client.post("/sheet-reconcile/supplement", data={
    "csrf": "qa-token", "snapshot_id": "1"}).status_code)

older = dict(sheet_snapshot([values()]), id=1, source_name="QA-old",
             sha256="a"*64, created_at="QA", source_kind="xlsx")
partial = dict(sheet_snapshot([], complete=False), id=2,
               source_name="QA-partial", sha256="b"*64,
               created_at="QA", source_kind="xlsx")
with patch("em_mvp.store.sheet_snapshots", return_value=[partial, older]), \
     patch("em_mvp.store.sheet_snapshot",
           side_effect=lambda path, sid: {1:older, 2:partial}.get(sid)), \
     patch("em_mvp.store.records", return_value=[]), \
     patch("em_mvp.store.sheet_adoptions", return_value={}), \
     patch("em_mvp.sheet_reconcile.google_oauth_status",
           return_value={"configured":False, "authorized":False}):
    html = client.get("/sheet-reconcile?snapshot=2").get_data(as_text=True)
    print("QA-11", "完整性：未確認" in html,
          "較早完整快照未再出現 1" in html)
~~~


### D. 公式快取的最小完整 XLSX（只用記憶體 ZIP/XML）

~~~python
import io, zipfile
from xml.etree.ElementTree import Element, SubElement, tostring
from tests.test_em008 import values
from em_mvp.sheet_reconcile import (
    HEADER_ROW, SHEETS, parse_xlsx_targets, parse_api_ranges, sample_groups
)
ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

def xml(rows):
    root = Element("worksheet", xmlns=ns)
    data = SubElement(root, "sheetData")
    for ri, row in enumerate(rows, 1):
        rr = SubElement(data, "row", r=str(ri))
        for ci, val in enumerate(row):
            ref = f"{chr(65+ci)}{ri}"
            if isinstance(val, tuple):
                cell = SubElement(rr, "c", r=ref)
                SubElement(cell, "f").text = val[0]
                if val[1] is not None:
                    SubElement(cell, "v").text = str(val[1])
            elif val != "":
                cell = SubElement(rr, "c", r=ref, t="inlineStr")
                SubElement(SubElement(cell, "is"), "t").text = str(val)
    return tostring(root, encoding="utf-8")

def xlsx(rows):
    out = io.BytesIO()
    pkg = "http://schemas.openxmlformats.org/package/2006"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    ct = "application/vnd.openxmlformats-officedocument.spreadsheetml"
    with zipfile.ZipFile(out, "w") as z:
        types = (f'<Types xmlns="{pkg}/content-types">'
                 '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                 '<Default Extension="xml" ContentType="application/xml"/>'
                 f'<Override PartName="/xl/workbook.xml" ContentType="{ct}.sheet.main+xml"/>')
        for i in (1, 2):
            types += (f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
                      f'ContentType="{ct}.worksheet+xml"/>')
        z.writestr("[Content_Types].xml", types + "</Types>")
        z.writestr("_rels/.rels",
            f'<Relationships xmlns="{pkg}/relationships">'
            f'<Relationship Id="rId1" Type="{rel}/officeDocument" '
            'Target="xl/workbook.xml"/></Relationships>')
        book = Element("workbook", xmlns=ns)
        tabs = SubElement(book, "sheets")
        for i, title in enumerate(SHEETS, 1):
            SubElement(tabs, "sheet", name=title, sheetId=str(i),
                       attrib={f"{{{rel}}}id": f"rId{i}"})
        z.writestr("xl/workbook.xml", tostring(book, encoding="utf-8"))
        links = f'<Relationships xmlns="{pkg}/relationships">'
        for i in (1, 2):
            links += (f'<Relationship Id="rId{i}" Type="{rel}/worksheet" '
                      f'Target="worksheets/sheet{i}.xml"/>')
        z.writestr("xl/_rels/workbook.xml.rels", links + "</Relationships>")
        z.writestr("xl/worksheets/sheet1.xml", xml(rows))
        z.writestr("xl/worksheets/sheet2.xml", xml([HEADER_ROW]))
    return out.getvalue()

for cached in (0, None):
    row = values(cfu="", colonies="0")
    row[14] = ("0", cached)
    s = parse_xlsx_targets(xlsx([HEADER_ROW, row]), complete=True)
    g = sample_groups(s)[0]
    print("QA-09 XLSX", cached, g["status"], g["reasons"])
s = parse_api_ranges({
    title: [HEADER_ROW, values(cfu="", colonies="0")]
    if title == "三廠管理者更新" else [HEADER_ROW]
    for title in SHEETS
}, complete=True)
g = sample_groups(s)[0]
print("QA-09 API", g["status"], g["sample"]["cfu_count"])
~~~

附錄 A/B/C 已以本候選在 QA 記憶體環境完整重跑，輸出符合各項「實際」記錄；附錄 D 亦用純 ZIP/XML 完成相同公式反例。所有附錄只輸出合成資料，不需磁碟DB／Temp。

## 未驗證範圍與接受門檻

- 真實本機 OAuth 授權、token refresh、真實 API／公司資料端到端：未驗證。用戶端未設定，亦不在本次允許的公司明細／秘密讀取範圍內。工程 connector真實盤點僅是工程宣稱，QA未重讀或背書。
- 互動瀏覽器／視覺版面、staging啟動、file://預覽：未驗證；保留此前政策限制。
- 磁碟DB migration、真實備份、正式服務／資料：未驗證且沒有碰觸。不能以記憶體transaction的成功代替持久化／备份驗收。
- 全套15／97：未獨立完成。必要讀取測試的29項通過與1項環境阻擋已如實列出。
- 逐欄來源追溯還需PM檢視：目前store._sheet_evidence只保存snapshot/sha/source_kind與site/row_number/cells_A_Y；after_json列auto_updated_fields與完整新舊值，沒有明確field-to-cell映射／sheetId/tab／補零rule。保留原列可人工重算，但此輪不把它宣稱為完整逐欄位置驗收通過。

建議PM退回目前凍結候選，優先處理7項P1，再處理影響共同adapter與錯誤提示的P2；修補由PM決定及派工。新候選應重新凍結SHA，至少重跑上述反例及必要整合回歸，確認仍只有一採樣、多菌種子列不增分母、人工狀態及原子回滾維持。未設定OAuth與GUI／磁碟環境仍須明列實際限制；本QA不要求黃金資料集簽核或工時估算。

本報告由QA回報PM；沒有接受、提交、推送、啟用或代修產品。
