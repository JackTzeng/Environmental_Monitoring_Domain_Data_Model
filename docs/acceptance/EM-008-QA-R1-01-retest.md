# EM-008 QA R1-01 定向覆驗

日期：2026-10-02（Asia/Taipei）。
結論：**R1-01 定向覆驗通過，建議階段接受本修補。** 結合 PM 已採納的第一輪其餘 11 項及重要保護證據，本次範圍沒有剩餘阻擋缺陷；可由 PM 決定啟動合成隔離 MVP 預覽。

只重播剩餘 P1、代表性缺核心欄、合法零、明確不同採樣與必要回歸，沿用 Ponytail full；沒有重開全產品稽核、代修或啟動服務。沒有讀寫正式 DB／公司來源／Google OAuth／ACL，也沒有繞過 Temp／staging／file:// 限制。

## 候選與基線保全

分支 codex/em-mvp-spec；HEAD 3b303050249585b633cff2601c4d6cc7b316cb47，未提交工作樹。
開始與完成覆驗的 12 檔候選 SHA 均符合 PM 指定值（清單見末尾），其他產品檔與第一輪覆驗基線一致。

原報告保持不變：
- EM-008-QA-adversarial-report.md：602c1ab675444055192ec7fe4dcd9b9565c6350929e37445b67751a5f02708d3
- EM-008-QA-round1-retest.md：efdff2bb1aca2a16a9fc2551aa7460fe575c95dda815448d2249fb5d09ad2fcc

## 獨立實測

| 定向項目 | 結果與實際證據 |
|---|---|
| 原反例：同廠同 B，前列 N空/O0，後列 N3/O3/Bacillus、F方法空 | PASS。API adapter→真實 GET /sheet-reconcile→真 store.adopt_sheet_candidate。兩群 pending、sample=None；預覽200、無採用／補值表單。直接採用抛 StaleRecord；手動POST302拒絕，records/adoptions/changes均0。 |
| 原反例：同上，後列 C年份空 | PASS。相同完整路徑與拒絕結果，records/adoptions/changes均0。 |
| 陽性原列與逐欄證據 | PASS。兩例均保存 related_pending_rows row3、N3/O3、U3=Bacillus、A3:Y3、完整25格原值、tab三廠管理者更新、sheetId0；field_sources包含同一關聯列。SQLite快照重讀後與API原列一致，未猜值或合併。 |
| 代表性缺核心欄 | PASS。缺月／日／點位／檢驗批次／房間／Grade的API與XLSX案例均待核；兩來源列各保留一次。既有同B衝突規則及新關聯檢查共同阻擋。 |
| 相容性與列重排 | PASS。缺值視為可能相關，已知日期／方法／批次／房間／Grade／點位明確不同時不相關；不同B／廠不相關。缺欄反序仍待核，原零群fingerprint不變、原列未遺失。 |
| 完整合法 N空/O0 | PASS。API／XLSX均new CFU0。真store採為單一draft，zero rule em008-cfu-v2及N2/O2來源保存；重送拒絕且只有1 record／1 adoption。 |
| 完整明確 N0/O0 | PASS。API／XLSX均一個new CFU0。 |
| 明確不同採樣 | PASS。不同B的合法0與陽性3、不同廠同B各有獨立new候選／fingerprint；無關陽性列不阻擋合法零。 |
| 多菌種／共同adapter | PASS。三個菌種子列：首列N3，其餘空、各O1，只有一採樣CFU3。本輪API／XLSX狀態、CFU、fingerprint、原列與子列數一致。 |

兩原反例的最小輸入維持第一輪報告：B001、2026/6/3、落菌法、環測、H001、C01/A/P01；前列N空/O0，後列N3/O3/U=Bacillus，僅方法或年份空。修後關鍵輸出：

~~~text
missing=method: pending, sample=null, preview_http=200,
related N=3/O=3/U3=Bacillus, source_range=A3:Y3, sheet_id=0,
post_http=302, records=0, sheet_adoptions=0, changes=0

missing=year: pending, sample=null, preview_http=200,
related N=3/O=3/U3=Bacillus, source_range=A3:Y3, sheet_id=0,
post_http=302, records=0, sheet_adoptions=0, changes=0

legal-zero: cfu=0, state=draft, records=1, sheet_adoptions=1,
rule=em008-cfu-v2；重送StaleRecord
~~~

程式證據：sheet_reconcile.py:201–207 共用欄位相容性、:286–287 收集同廠同B來源、:383–415 在補零前檢查相關列並保留證據、:262–263 加入field_sources。store.py未更動，採用仍在交易內重新計算sample_groups並拒絕pending。

## 必要回歸與未驗證

本QA實跑9項既有定向回歸，全部通過（含兩新增R1-01測試、補零完整性、菌種分組、B身份、排序、G分類、公式快取）；不是工程29/29的代述。git diff --check exit0，只有既有LF/CRLF提示。本次沒有重跑原12項全套或整個產品；PM已採納的第一輪證據沿用，未將未測範圍冒記通過。

動態採用使用真產品函式／SQL、合成SQLite記憶體DB；backup回傳合成Path，沒有磁碟備份驗證。拒絕pending的交易內流程可能呼叫backup函式；本測試只證實無record／adoption／changes寫入，不聲稱該函式未被呼叫。

未驗證仍為：真實OAuth授權／refresh／API、公司來源端到端、互動GUI／loopback服務、正式DB migration、磁碟備份／持久化。QA沒有啟動預覽包或正式服務；隔離可操作預覽由PM決定及安排。本階段接受不擴成GMP確效或正式資料啟用簽核。

## 已實跑的核心純記憶體重現

下列合成harness不建立Temp／磁碟DB；可在本專案以 .venv\Scripts\python.exe -B 執行。
~~~python
import ast, inspect, sqlite3, json
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from em_mvp import store
from em_mvp.app import create_app
from em_mvp.sheet_reconcile import HEADER_ROW,SHEETS,parse_api_ranges,sample_groups,snapshot_digest,summarize
from tests.test_em008 import values
schema=next(n.args[0].value for n in ast.walk(ast.parse(inspect.getsource(store.initialize))) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='executescript')
uri='file:em008_qa_r101_targeted?mode=memory&cache=shared'
anchor=sqlite3.connect(uri,uri=True);anchor.executescript(schema)
def connect(*a,**k):
    db=sqlite3.connect(uri,uri=True);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON');return db
with patch.object(store,'initialize'),patch.object(Path,'exists',return_value=True),patch.object(Path,'read_text',return_value='QA_MEMORY_SECRET'):
    app=create_app(Path('__QA_MEMORY_ONLY__'))
app.config.update(TESTING=True)
client=app.test_client()
with client.session_transaction() as session:session['csrf']='qa-token'
def counts():
    with closing(connect()) as db:
        return {t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('records','sheet_adoptions','changes')}
evidence={'source_kind':'google-api','spreadsheet_id':'synthetic','completeness_basis':'synthetic complete read','tabs':{t:{'sheet_id':cfg['sheet_id']} for t,cfg in SHEETS.items()}}
with patch.object(store,'connection',side_effect=connect),patch.object(store,'backup',return_value=Path('MEMORY_BACKUP')),patch('em_mvp.sheet_reconcile.google_oauth_status',return_value={'configured':False,'authorized':False}):
    for missing in ('method','year'):
        positive=values(cfu='3',colonies='3',organism='Bacillus',**{missing:''})
        snapshot=parse_api_ranges({t:[HEADER_ROW,values(cfu='',colonies='0'),positive] if t=='三廠管理者更新' else [HEADER_ROW] for t in SHEETS},complete=True,evidence=evidence)
        groups=sample_groups(snapshot)
        zero=next(g for g in groups if any(r['row_number']==2 for r in g['rows']))
        assert zero['status']=='pending' and zero['sample'] is None
        rel=zero['related_pending_rows'][0]
        assert rel['row_number']==3 and rel['N_total_cfu']=='3' and rel['O_colony_count']=='3'
        assert rel['species_cells_S_Y']==[{'cell':'U3','raw_value':'Bacillus'}]
        assert rel['cells_A_Y'][13:15]==['3','3'] and rel['cells_A_Y'][20]=='Bacillus'
        assert zero['field_sources']['related_pending_rows']==zero['related_pending_rows']
        saved=store.add_sheet_snapshot('.',missing,snapshot_digest(snapshot),'google-api',True,snapshot['rows_by_sheet'],summarize(snapshot,groups),snapshot['evidence'])
        page=client.get('/sheet-reconcile?snapshot='+str(saved['id']))
        html=page.get_data(as_text=True)
        assert page.status_code==200 and 'related_pending_rows' in html and 'Bacillus' in html
        assert 'action="/sheet-reconcile/adopt"' not in html
        assert 'action="/sheet-reconcile/supplement"' not in html
        stored=store.sheet_snapshot('.',saved['id'])
        assert stored['rows_by_sheet']['三廠管理者更新'][2]['values']==snapshot['rows_by_sheet']['三廠管理者更新'][2]['values']
        before=counts()
        try:store.adopt_sheet_candidate('.',saved['id'],zero['fingerprint'])
        except store.StaleRecord:pass
        else:raise AssertionError('adoption accepted')
        assert before==counts()=={'records':0,'sheet_adoptions':0,'changes':0}
        response=client.post('/sheet-reconcile/adopt',data={'csrf':'qa-token','snapshot_id':saved['id'],'fingerprint':zero['fingerprint']})
        assert response.status_code==302 and counts()==before
        print('R101_PASS',json.dumps({'missing':missing,'group_status':zero['status'],'sample':zero['sample'],'preview_http':page.status_code,'related_N':rel['N_total_cfu'],'related_O':rel['O_colony_count'],'species':rel['species_cells_S_Y'],'source_range':rel['source_range'],'tab':rel['tab'],'sheet_id':rel['sheet_id'],'post_http':response.status_code,'counts':counts()},ensure_ascii=True))
    # Complete valid inferred zero remains adoptable and idempotent.
    snapshot=parse_api_ranges({t:[HEADER_ROW,values(cfu='',colonies='0')] if t=='三廠管理者更新' else [HEADER_ROW] for t in SHEETS},complete=True,evidence=evidence)
    group=sample_groups(snapshot)[0]
    saved=store.add_sheet_snapshot('.','legal-zero',snapshot_digest(snapshot),'google-api',True,snapshot['rows_by_sheet'],{},snapshot['evidence'])
    assert group['status']=='new' and group['sample']['cfu_count']=='0'
    result=store.adopt_sheet_candidate('.',saved['id'],group['fingerprint'])
    row=store.get('.',result['record_id']);trace=json.loads(row['source_text'])
    assert row['current']['cfu_count']=='0' and row['state']=='draft'
    assert trace['zero_inference']['rule_version']=='em008-cfu-v2' and [c['cell'] for c in trace['field_sources']['cfu_count']['cells']]==['N2','O2']
    try:store.adopt_sheet_candidate('.',saved['id'],group['fingerprint'])
    except store.StaleRecord:pass
    else:raise AssertionError('duplicate adoption accepted')
    assert counts()['records']==counts()['sheet_adoptions']==1
    print('LEGAL_ZERO_PASS',json.dumps({'cfu':row['current']['cfu_count'],'state':row['state'],'counts':counts(),'rule':trace['zero_inference']['rule_version']}))
anchor.close()

~~~

## 候選 SHA-256（前＝後）

- em_mvp/sheet_reconcile.py：24871146f08dd8d7ed756b09dbe29330e61abb69dcd5ece04eedfca908acf597
- em_mvp/store.py：0a03fc925d05e4ac0fbb8b45c0a6ecfe1730ee668cfb7628ec47836bf3adf734
- em_mvp/app.py：f3c0c7780c7bc47e76eafd44d1e4d62a114d149e5303ce505fcc77e220c9c4c8
- em_mvp/templates/sheet_reconcile.html：83ec852766c49f7f909104a4d06875f690912f7b12872f7d396e779b0ccabf2e
- em_mvp/templates/base.html：1d1f8328a66cf3e1d0546f5069267d5743db1e784c3a23ea03ccddf039c669f5
- em_mvp/templates/input.html：c7404f14d8e7bfb0d225eff9f142bfda6c47085933450170e20388a213711ce6
- .gitignore：ce5cdb15d89144d3f11bfcde9277b185731c3fc2f1450e30abf4598b04e2f498
- README.md：d893247f28afc18412ad8646eacebfc8f5928fd7542fef004c831d86b9168167
- tests/test_em008.py：cbbc7ca1c093661c51950397bcd1258ee50058eb9bc41f97efbadcc0ec448430
- docs/work-orders/EM-008-google-sheet-reconciliation.md：96ebd4505f47098ebc3d53dc6185185ac0374c0b2e7e21f742cf37885747e5be
- docs/work-orders/EM-008-QA-round1-fixes.md：910df846da9aed69f5d943b0f8e28f553a0dddea5767a13d785acc3c51846e4a
- docs/acceptance/EM-008-results.md：bf7ee5229a003687da2f87e13da3da42cf252f8fbeac867dec8a2bb54cc61346
