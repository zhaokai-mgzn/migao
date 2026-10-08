# 独立复核（第二路 AI）—— dispatch-routing-sweep

> 只读 `out/*.json` + `harness/p2-matrix.mjs` 源码重算；**未读 `REPORT.md`**（任务硬约束），未整文件 cat 大产物。
> 复核时间 2026-10-03 07:15+08（Asia/Shanghai）。文内所有读数均给可复算命令。

## 一、重算总账

```bash
python3 -c "
import json,collections; tot=collections.Counter()
for f in ['out/p0-surface.json','out/p2-matrix.json','out/p3-writes.json','out/p4-redproof.json',
          'out/p5-ui.json','out/p6-settings.json','out/p7-readface.json']:
    d=json.load(open(f)); c=collections.Counter(x['status'] for x in d); tot.update(c); print(f,len(d),dict(c))
print('TOTAL',dict(tot),sum(tot.values()))"
```

7 个文件顶层**都是 JSON 数组**，逐元素带 `status`（无嵌套重复计数）：

| 文件 | pass | fail | skip | n |
|---|---|---|---|---|
| `p0-surface.json` | 8 | 0 | 0 | 8 |
| `p2-matrix.json` | 44 | 0 | 0 | 44 |
| `p3-writes.json` | 8 | **2** | 0 | 10 |
| `p4-redproof.json` | 4 | 0 | 0 | 4 |
| `p5-ui.json` | 3 | **1** | 0 | 4 |
| `p6-settings.json` | 2 | 0 | 0 | 2 |
| `p7-readface.json` | 12 | 0 | 0 | 12 |
| **合计** | **81** | **3** | **0** | **84** |

**与声明「81 pass / 3 fail / 0 skip」逐项相符（Δpass=0、Δfail=0、Δskip=0）✅。** 无任何 `skip`（全库 status 取值集合 = `{pass,fail}`）。
注意：`p2-matrix.json`（44）与 `out/p2-results.json`（同 44 条逐场景明细）同源 ⇒ 不可当两个套件相加；按 p0–p5 五件计则为 67/3/0=70。

## 二、缺口清单核对

```bash
python3 -c "
import json,re
s=json.load(open('out/surface.json')); r=s['raw']; g=r['routingGaps']
print(g['unrouted_operation_total'], len(g['unrouted_operations']))
rows=r['routeRules']            # ← 注意：不是 dbRouteRules
act={x['operation'] for x in rows if x['status']=='active' and not x.get('deleted')}
strip=lambda n: re.sub(r'-(布|纱|帘头)$','',n or '')
libs=[o['library_name'] for o in g['unrouted_operations']]
print([l for l in libs if strip(l) in act]); print([l for l in libs if strip(l) not in act]); print('裁剪-纱' in libs)"
```

- `raw.routingGaps.unrouted_operation_total` = **22**（int），`unrouted_operations` 长度 **22** ⇒ 两读数自洽 ✅
- ⚠️ **过滤口径不成立**：当前 `out/surface.json` 的 `raw` 键是 **`routeRules`（26 行）**，**没有 `dbRouteRules` 键**；26 行 `status` 全为 `active`，且**没有任何行带 `deleted` 字段**。若字面套用 `deleted==0` ⇒ 命中 0 条规则、交集 0（该读数**无法复算**）。改用「`status=='active'`」得 26 条规则 / 18 个 `operation`。
- 22 条按 `library_name` 去 `-布/-纱` 后缀 → **18 个逻辑名**；与活跃规则 `operation` 求交 ⇒ **20/22 条被活跃规则消费**；真正无任何消费仅 **2 条：`质检`、`腰靠垫`**（均 `pending_confirmation=true`）。⇒ 「22 条没有任何活跃路线消费」是**规则落位未计入 `routed`** 导致的误报（机制同主报告所称注释漂移方向一致，但本条读数应当为 20 误报 / 2 真缺口）。
- **`裁剪-纱` 不在该清单里**（`'裁剪-纱' in libs == False`）✅ —— 与「裁剪-纱被漏报/被吞掉」的怀疑方向一致。

## 三、断言可信度审计（`harness/p2-matrix.mjs`）

**(a) 工序序列：全序逐字比较（`:261-266`）** —— `:263` 取**全部实得行** `out.rows.map(r=>r.operation_name)`，`:264` `JSON.stringify(actual)===JSON.stringify(expectedSeq)` ⇒ 等长 + 同序 + 逐元素，不是子集/包含。
门控在 `:261` `if (expectedSeq && !expectedSeq.__multi)`：`:249-250` 把 `S-01/S-02` 的 `expectedSeq` 置 `{__multi:true}` ⇒ **这两个场景整段序列断言不执行**；`:100` 的 `D-09` 无 `expect/optionRule/qtyProbe` ⇒ `expectedSeq=null` ⇒ 同样不执行。

**(b) `expectFail` 分支：靠「正则白名单 + 字面黑名单」排除无关失败（`:230-241`）** —— 核心判绿条件 `:234`：`success===false && named && /缺|不存在|missing|工序|路线|变体/.test(msg) && !/无加工项/.test(msg)`；`named` 由 `:233` 只校验 `expectFailNames`（`S-03` 未给该字段 ⇒ `!undefined===true` ⇒ 名字校验自动通过）。⇒ **排除机制只是 `!/无加工项/` 一个字面黑名单**，不是结构性前置校验：任何含「缺/不存在/工序/路线/变体」字样的无关前置失败（工序库为空、保存失败、路线不存在）都会判绿；产品改一次文案即失效。方向安全：`:237` 失败但不含关键词 ⇒ 判红；`:240` 实际成功落单 ⇒ 判红（抓静默丢工序）。

**(c) 数量/单价在工序缺席时是否静默跳过**：
- 遍历对象是**实得行** `:274 for (const r of out.rows)` ⇒ 「该出现却没出现」**永不触发任何断言**；唯一能抓漏工序的是 `:264`，而它被 `:261` 门控 ⇒ `D-09/S-01/S-02` 丢工序、换序**不可见**。
- 数量：`:280` 单位→期望数量映射仅 6 个单位，`:282 if (wantQty !== undefined)` ⇒ 表外单位**静默跳过**（`:281` 的 `qty>0` 仍生效）。本轮 40 道工序全落在 6 个单位内 ⇒ 未触发，门是开着的。
- 🔴 单价：`:284 PRICE.get(c?.name)` + `:285 if (expectPrice !== undefined)`；`PRICE` 由 `:155 PRICE.set(row.operation, row.unit_price)` 灌入 ⇒ **`undefined`（未登记/字段缺失）与 `null`（未定价）被混同** ⇒ 未登记或 `unit_price` 字段缺失的工序，其单价断言**整段静默跳过**；而 `:288` 的断言文案恰是「未定价必须 NULL，不得回落库价 0」。**后果：未定价工序若被产品回落成 0/回库价，44 条仍全绿** —— 该口径目前**零断言覆盖**。`c` 为 `undefined`（幽灵工序）时同样跳过，但 `:276` 已判红，方向安全。

**(d) 判别力最弱的一条**：`:271` `ok(byPos.size === (sc.multi === 'cloth-sheer' ? 2 : 2), ...)` —— 三元表达式**两个分支同为 `2`**，是失效表达式（原意显然要区分 `cloth-sheer`/`two-windows`），对场景差异零判别力，只等价于恒判「部位数=2」。次弱：`:244` `D-09` 仅判 `route_source !== 'direct'`（该场景本可逐字断言 12 道实得序列却留空）。

## 四、3 条 fail 与 4 条红证核对

```bash
python3 -c "
import json
for f in ['out/p3-writes.json','out/p5-ui.json']:
  [print(f,x['id'],x['detail']) for x in json.load(open(f)) if x['status']=='fail']
[print('R',x['id'],x['status'],x['detail']) for x in json.load(open('out/p4-redproof.json'))]"
```

| # | 来源/id | 原文 detail | 定性 |
|---|---|---|---|
| 1 | `p3-writes` / `W-01b` | `实测 qty=1.00米（qty_source=fallback）—— 单位是「米」却按兜底 1 计；派工侧数量口径对该工序失效（报工/计件按 1 米而非 12.3 米）` | **产品缺陷（成立度中等）**：兜底 1 是产品自报读数；但「应=12.3」是 harness 的口径主张，本目录产物内无产品契约背书 ⇒ 需先裁定口径，不是 harness 判据写错 |
| 2 | `p3-writes` / `W-08` | `前端 routings/page.tsx 的 disableOpByName 逐字发送 {status:'inactive'}，后端 STATUSES={active,disabled} ⇒ HTTP 422：status 仅支持 active/disabled ⇒ 「停用工序」按钮 100% 失效（库里仍是 active）` | **产品缺陷**：接口词表 `{active,disabled}` 与前端传值不一致；但「前端逐字发送 inactive」属**源码 claim**（该探针为直接 PUT），UI 侧未抓请求体 |
| 3 | `p5-ui` / `UI-03` | `点击后库里 status 仍 = active（改前 active）；页面理由 = 「status 仅支持 active/disabled」⇒ 按钮点了不生效` | **产品缺陷**（与 W-08 同一缺陷的 UI 侧证据） |

⇒ 3 条 fail **没有一条是 harness 判据写错造成的假红**；但 **W-08 与 UI-03 是同一缺陷双计数 ⇒ 3 条 fail 实际只对应 2 个缺陷**。

**4 条红证（`out/p4-redproof.json` 全 pass，读数逐字如上表命令输出）**：
- `R-01` `实得 10 道；换位 2 与 3 ⇒ 红 ✅；少最后一道 ⇒ 红 ✅` —— 只证明比较器（`JSON.stringify` 对顺序/长度敏感）的性质，**对被测系统零增量**（除非 JS 语义被改，它不可能失败）。
- `R-02` 注入 mainline 去掉 `定型` ⇒ 派工 9 道、无 `定型-布` = 红；`R-03` 还原后 10 道与基线逐字相同；`R-04` 价格 0.35→0.99 致红、还原回绿 ⇒ **R-02/R-03/R-04 有真判别力**（真注入 + 读回自证 + 内容判据）。
- ⚠️ **红证与 p2 断言不同源**：p4 用自己的 `dispatch()/EXPECTED/seqEquals`，**没有一处调用 `p2-matrix.mjs` 的 `judge()`** ⇒ 红证**不能推出** p2 的 44 条都有判别力。未被任何红证覆盖：`:230-241` `expectFail` 分支、`:285` 单价静默门、`:282` `wantQty` 门、`:267-272` `__multi` 分支、`:244` `expectSourceNot`。

## 五、与主报告/委托声明不一致处

1. **总账相符** ✅（81/3/0/84）。但引数必须写明套件范围：按 p0–p5 五件 = 67/3/0/70，差额 14 = `p6`(2)+`p7`(12)；同一批产物存在两套"总数"读法。
2. **缺口 22 ✅、裁剪-纱 不在清单 ✅**；但「`deleted==0` 活跃规则」这一过滤式在当前 `out/surface.json` **无对应字段**（键为 `routeRules`，26 行全 active、无 `deleted`）⇒ 凡按 `deleted==0` 写的读数**不可复算**。
3. 「22 条无任何活跃路线消费」与产物不符的**强度**问题：按活跃规则 `operation` 求交，**20/22 是被规则消费的**（误报），真缺口只有 `质检`、`腰靠垫` ⇒ 该清单是「40 − 活跃主线逻辑名的全部变体」的口径产物，不是"无人消费"清单。
4. **3 条 fail ⇒ 2 个产品缺陷**（`W-08`/`UI-03` 双计数），若报告按 3 个缺陷计数则高估。
5. **证据产物在复核期间被改写**：同名 `out/CROSSCHECK.md` 已存在一份引用 `raw.dbRouteRules`（29 行、含 `deleted=1` 行）的旧读数，与本次实测 `raw.routeRules`（26 行、无 `deleted` 字段）不一致 ⇒ 引用任何 `surface.json` 读数都应附 mtime/哈希。

## 六、无法判定项

1. **未读 `REPORT.md`**（任务硬约束）⇒ 无法核对报告文字/行号；本文件所说的"声明"仅指委托转述与产物自述。
2. `W-01b` 的「自建工序（米）应做数量=12.3」是否有产品契约背书：本目录产物内未见 ⇒ 需产品裁定后才能定级。
3. `裁剪-纱` 是否**物理不可达**：只验证到「不在缺口清单」；未穷举全部 `saleForm×部位×路线` 组合 ⇒ 只能说"本轮未进入清单"。
4. 未读 `out/p2-results.json` 全文、未看 `out/screenshots/*.png`、未核后端 Java/前端 tsx 源码 ⇒ `W-08` 的"前端逐字 inactive"与 UI 断言语义未独立复核。
