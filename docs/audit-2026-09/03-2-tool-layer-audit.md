# 03-2 报告②｜Tool 层审计（D-01 ~ D-11，2026-09-17）

> **来源**：issue [#4041](https://github.com/zhaokai-mgzn/migao/issues/4041) 第一节 ②；
> 审计原文曾位于 `/tmp/migao_audit/TOOL_LAYER_AUDIT.md`（**已被清理，不可检索**）。
> 本文件**按 issue 正文 + 仓库内可复现事实重建**，不是原件复制。
> **锚定 SHA**：`origin/main` @ `46c91d3c`（审计基线）；**已修状态核验时点** `8e03e5b3`
> **采集时间**：2026-09-18 03:00 (+0800)
> **性质**：**冻结快照 + 已修状态注记**（「已修」那一列会继续变，但它有核验命令，可随时重跑）

---

## 1. 裁决（issue 原文照录）

> **主干路径是通的；Tool 层是「失败后无法自愈/无法解释」的原因，不是「下单失败」的第一因。**

D-01~D-11 里，本批能落到仓库命令上的逐条复算如下；**未能复算的照实登记**（§4）。

## 2. 逐条复算

| ID | issue 描述 | 复算命令 | 实测 @46c91d3c | @8e03e5b3（main） |
|---|---|---|---|---|
| **D-01** | `ToolResult.terminal` **死契约**：赋值 4 处、消费 1 处，构造点不传 ⇒ `reset_domain` 永不触发；`grep terminal tests/` = 0 | §3 T1 | **赋值 4 处**（`order_create:1116` / `aftersale_create:282` / `human_handoff:463,493`）；**`tests/` 命中 0 文件** | ✅ **已修**（#4018）：构造点补 `"terminal": False` + 消费点取值 + 判据指针 |
| **D-02** | 服务端 `suggestion` 被 4xx 分支丢弃；`product_manage` 读它是死代码 | §3 T2 | 4xx 分支只 `return {success, error, data}` | ✅ **已修**（#4022）：整份透传 `{**result, "success": False, ...}` |
| **D-03** | 无幂等键 + 失败话术诱导重试 ⇒ 重复下单风险 | — | — | ⏳ 已开包 **#4037**（本批不复算） |
| **D-05** | `suggestion` 缺口 **49.4%**（195 / 395 个失败构造点无 suggestion） | §3 T3 | **395 个 `ToolResult(success=False)`；200 带 suggestion；195 无（49.4%）** | ✅ 已修：**301 个失败构造点，301 个全带 suggestion，缺口 = 0** |
| **D-11** | `app/tools/__init__.py` **门面漂移** | §3 T4 | **注册 35 类 / 导出 25 类 / 缺 10 类** | ✅ **已修**（#4022）：**35 / 35 / 缺 0** |

### 2.1 `order_create` 契约撒谎（#4009 A1，本批补取）

| 断言 | 复算命令 | 实测 |
|---|---|---|
| schema `items.required` **未声明** `colorName`/`skuCode` | `git show 46c91d3c:backend/ai-agent-service/app/tools/order_create.py \| grep -n '"required"'` | 第 231 行：`["product_name", "quantity", "unit_price", "subtotal"]` |
| 运行时**必填**（多规格价商品，缺则 fail-closed 拒绝） | 同上文件第 765-775 行 | `if len(sku_prices) > 1:` → 缺 `colorName`/`skuCode` ⇒ `ToolResult(success=False, error="unit_price_not_grounded", ...)` |
| ⇒ **正确库价也拒**（schema 允许的合法入参被运行时拒绝） | 上两条组合 | **形态成立**（缺 `processing_info` 时，即使 `unit_price` = 库价，也在此分支被拒） |
| 是否已在 main 上修 | `git show 8e03e5b3:backend/ai-agent-service/app/tools/order_create.py \| grep -n '"required"'` | 第 378 行**仍是** `["product_name", "quantity", "unit_price", "subtotal"]` ⇒ **本批未观察到 schema 侧修复** |

> ⚠️ **不要从「schema 仍是四字段」直接推出「缺陷仍在」**：issue 把它列为 A1 并划入任务包 P2；
> 修法可能是**运行时判据**而非 schema 加必填。本批只登记**可观测事实**，不下「已修/未修」结论。

### 2.2 被推翻的假设（issue 原文 + 证据等级）

| 假设 | issue 结论 | 本批证据 |
|---|---|---|
| 注册与暴露不一致（33/33 一致） | **推翻** | ⚠️ **本批实测 35 注册**（见 §3 T4），非 33；「一致」的具体口径本批**未取证** |
| `read_only=True` 却写库（0 例） | **推翻** | **未取证**（需按 `read_only` 字段 × 实际写操作做全量对账） |
| 工具抛异常（0 处 raise） | **推翻** | **未取证**（需全量扫描 `raise`） |

### 2.3 测试侧（issue 原文 + 证据等级）

| 断言 | 复算命令 | 实测 |
|---|---|---|
| 写工具测试**全 mock**（`respx\|httpx_mock\|MockTransport` 零命中） | `git grep -cE 'respx\|httpx_mock\|MockTransport' 46c91d3c -- tests/` | 本批**未复算**（issue 写零命中）→ **未取证** |
| `order_create` 覆盖 86%，缺失行恰在 fail-closed 拒绝分支 | — | **未取证**（需覆盖率 artifact） |
| `grep terminal tests/` = 0 | `git grep -c terminal 46c91d3c -- tests/ \| wc -l` | **0**（与 issue 一致） |

## 3. 实跑输出（逐字）

```bash
# ── T1：D-01 terminal 赋值点 / 消费点 / tests 命中 ──
$ A=backend/ai-agent-service/app
$ git grep -n "terminal=True" 46c91d3c -- $A/tools
46c91d3c:backend/ai-agent-service/app/tools/aftersale_create.py:282:                terminal=True,
46c91d3c:backend/ai-agent-service/app/tools/human_handoff.py:463:                        terminal=True,
46c91d3c:backend/ai-agent-service/app/tools/human_handoff.py:493:                terminal=True,
46c91d3c:backend/ai-agent-service/app/tools/order_create.py:1116:                terminal=True,
$ git grep -c terminal 46c91d3c -- tests/ | wc -l
0
```

> ⚠️ **归档时的唯一一处非逐字改动**：上面 4 行把 shell 变量 `$A` **展开**成了
> `backend/ai-agent-service/app`（原文输出里是 `$A` 开头的缩写形式）。原因：那种「`$A` + 路径 + 冒号 + 行号」
> 的写法会被 `CASE-TRUST-STALE-LINE-REF` 规则当成**仓库路径引用**，解析出一个并不存在的路径
> ⇒ 门禁 fail-closed 判红（实证：PR #4410 首次 CI，4 处全中）。展开后路径真实、行号在 `origin/main` 上仍在界内，
> 机械校验通过。命令与输出内容未改，仅变量展开。

```bash
# ── T2：D-02 http_client 4xx 分支（基线 vs main）──
$ git show 46c91d3c:$A/utils/http_client.py | sed -n '164,170p'
            if 400 <= status < 500:
                result: Dict[str, Any] = response.json()
                return {
                    "success": False,
                    "error": result.get("error", {}),
                    "data": None,
                }
$ git show 8e03e5b3:$A/utils/http_client.py | grep -n '4xx' -A 12 | grep -E '\{\*\*result|success.*False|data.*None'
                return {**result, "success": False, "data": None,
```

```bash
# ── T3：D-05 suggestion 缺口（AST 口径：ToolResult(success=False) 构造点的关键字集）──
$ git ls-tree -r --name-only 46c91d3c -- $A/tools | grep '\.py$' > /tmp/toolfiles.txt
$ python3.11 - <<'PY'
import ast, subprocess
rev='46c91d3c'
files=[l for l in open('/tmp/toolfiles.txt').read().split() if l.endswith('.py')]
tot=with_sug=0; without=[]
for f in files:
    src=subprocess.run(['git','show',f'{rev}:{f}'],capture_output=True,text=True).stdout
    try: t=ast.parse(src)
    except SyntaxError: continue
    for n in ast.walk(t):
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='ToolResult':
            kw={k.arg for k in n.keywords}
            sv=[getattr(k.value,'value',None) for k in n.keywords if k.arg=='success']
            if sv and sv[0] is False:
                tot+=1
                if 'suggestion' in kw: with_sug+=1
                else: without.append((f,n.lineno))
print(f"ToolResult(success=False) 构造点: {tot}")
print(f"  带 suggestion=: {with_sug}")
print(f"  无 suggestion=: {len(without)}  ({len(without)/tot*100:.1f}%)")
PY
ToolResult(success=False) 构造点: 395
  带 suggestion=: 200
  无 suggestion=: 195  (49.4%)
# 同口径 @8e03e5b3（main）：
#   ToolResult(success=False)=301  带 suggestion=301  无=0
```

```bash
# ── T4：D-11 门面漂移（注册类 vs __init__ 导出）──
$ git show 46c91d3c:$A/tools/registry.py > /tmp/r.py
$ git show 46c91d3c:$A/tools/__init__.py > /tmp/i.py
$ python3.11 - <<'PY'
import re
reg=open('/tmp/r.py').read(); init=open('/tmp/i.py').read()
live=[l for l in reg.splitlines() if re.match(r'\s*registry\.register\(', l) and not l.strip().startswith('#')]
registered={re.search(r'register\((\w+)\(\)', l).group(1) for l in live}
exported=set(re.findall(r'^from app\.tools\.[a-z_]+ import ([A-Za-z_]+)', init, re.M))
print("注册=%d 导出=%d 缺=%d" % (len(registered),len(exported),len(registered-exported)))
print(sorted(registered-exported))
PY
注册=35 导出=25 缺=10
['AftersaleCreateTool', 'AftersaleQueryTool', 'CurtainCalcTool', 'CustomerAddressQueryTool',
 'FinanceApiTool', 'HumanHandoffTool', 'OrderCreateTool', 'PieceworkQueryTool',
 'ProductionProgressQueryTool', 'ValidateInputTool']
# 同口径 @8e03e5b3：注册=35 导出=35 缺=0
```

```bash
# ── T5：A1 schema vs 运行时必填 ──
$ git show 46c91d3c:$A/tools/order_create.py | grep -n '"required"'
231:                    "required": ["product_name", "quantity", "unit_price", "subtotal"],
235:        "required": ["customer_name", "customer_phone", "items"],
$ git show 46c91d3c:$A/tools/order_create.py | sed -n '766,776p'
            if len(sku_prices) > 1:
                pinfo = item.get("processing_info")
                if not isinstance(pinfo, dict) or not (pinfo.get("colorName") or pinfo.get("skuCode")):
                    return ToolResult(
                        success=False,
                        error="unit_price_not_grounded",
                        message=(
                            f"商品明细第 {i + 1} 项「{name}」存在**多个规格价**"
                            ...
```

## 4. 与 issue 正文的差异汇总（**不静默覆盖**）

| 量 | issue 正文 | 本批实测 @46c91d3c | 差异来源 |
|---|---|---|---|
| `suggestion` 缺口 | 「384 失败点 / 195 无」 | **195 无 / 395 构造点**（49.4%） | 分母口径：issue 的 384 与同页 A3 写的 396 不一致；本批用 AST 口径得 395 |
| 注册工具数 | 33 | **35** | 「注册」口径（本批 = 未被注释掉的 `registry.register(...)` 调用） |
| 未导出类数 | 8（`__all__` 漏 12） | **10**（缺 10 类） | 见上；`__all__` 口径本批未逐字复算 |

> **这四条差异都不是「谁对谁错」**，而是**同一件事的两套计数口径**（issue 自己也标注了多处口径差异）。
> 归档的价值在于：**给出命令，让下一个人能自己选口径重算**，而不是抄一个数。

## 5. 未取证 / 不可复算

- **D-03（幂等键）**：未复算（issue 说已开包 #4037）。
- **D-04 / D-06~D-10**：issue #4041 正文只列了 D-01/D-02/D-03/D-05/D-11 五条，
  其余条目在 **issue #4009 冻结清单**里（A1~A17），本批**不重复归档**，指向 #4009。
- **「注册与暴露 33/33 一致」「`read_only=True` 却写库 0 例」「工具抛异常 0 处 raise」**：
  三条「推翻的假设」本批**未复算** → `未取证`。
- **测试全 mock（`respx\|httpx_mock\|MockTransport` 零命中）/ `order_create` 覆盖 86%**：
  本批未复算 → `未取证`。
- **原始审计报告原文**：不可检索。