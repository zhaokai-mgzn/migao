# 03-4 「为什么越修越多」—— 六机制 + 五组测量（2026-09-17）

> **来源**：issue [#4041](https://github.com/zhaokai-mgzn/migao/issues/4041) 第二节
> （原文标注「**此前只在对话里**」——即**从来没有落到任何文件**，包括 `/tmp`）。
> **锚定 SHA**：`origin/main` @ `46c91d3c`（审计基线）
> **采集时间**：2026-09-18 03:00 (+0800)
> **性质**：**混合** ——
> · **§2 六机制 = 活的分析框架**（不随数字过期；它是「怎么读这些数字」的方法）；
> · **§3 五组测量 = 冻结快照**（每个数字都随主线演进过期，逐条附复算命令）。

---

## 1. 为什么这一节必须归档

issue #4041 的原话：

> **六机制 + 五组测量（此前只在对话里）**

「只在对话里」= 下一次会话开始时它**不存在**。而这一节恰恰是**唯一解释「为什么修了 179 个 fix
还在涨」的东西** —— 缺了它，后来者只能看到一堆缺陷条目，看不到**生成这些条目的机器**。

## 2. 六机制（活的分析框架，**无数字，不随主线过期**）

照录 issue 原文，逐条补「仓库内可查锚点」与证据等级。

| # | 机制 | 仓库内可查锚点 | 证据等级 |
|---|---|---|---|
| ① | **反馈信号单维**（只有「能不能变绿」）⇒ 修复压力与**可观测性**成正比、与**危害**无关 | `metadata` 仅 4 键、无执行结果字段（[03-3](03-3-eval-system-audit.md) §2.6 E15） | **取证** |
| ② | 默认修法是「在事故点加一道门」⇒ 门数增长 ≠ 缺陷收敛，而是**逃逸面增长** | `base_skill.py` 守卫类函数 08-25 = **0** → 09-15 = **12**（[03-1](03-1-skill-layer-audit.md) §3 S9） | **取证（形态）** |
| ③ | **修复本身是新缺陷来源**（单价闸门为修错价而生，却把正确价也拒） | `order_create.py` 多规格价 fail-closed 分支（[03-2](03-2-tool-layer-audit.md) §2.1） | **取证** |
| ④ | **门禁会被洗白且不可逆**：「已不再违规⇒必须移除」**只对本次 diff 命中的用例生效** ⇒ 没人碰的用例**永久豁免** | 基线 `case_trust_gate.stale_baseline_entries` 的判定范围 = `changed_ids ∩ baseline.violations`（§4 复算）；**已在 `#4031` 修**（`8cca7664`：全量对账 + burn-down 预算） | **取证（且已修）** |
| ⑤ | 基础错误**不会立刻致痛** ⇒ 永远排不上优先级（问题被**搬走**而非消灭） | 无机械判据（属归因判断） | **未取证（分析框架）** |
| ⑥ | **账本与真相源漂移** ⇒ 每轮从错误前提出发 | 本仓已有专门判据与工具：`docs/wiki/truth-source-contract.md` + `scripts/drift_audit.py`（**issue #4041 本身就是为了治这一条**） | **取证（机制已落码）** |

> **口径声明**：§2 是**分析框架**，不是可判红的断言。把它当门禁读 = 违反 `migao-dev-flow` §19
> 「照实登记，不把『写进技能』写成『有门禁』」。**只有 ⑥ 已有落码工具。**

## 3. 五组测量（冻结快照，逐条复算）

### 3.1 第一组：`base_skill.py` 规模 / 守卫类函数 / 中文词表常量

issue 给的三行表：

| 时点 | `base_skill.py` | 守卫类函数 | 中文词表常量 |
|---|---|---|---|
| 08-25 | 1090 行 | **0** | **3** |
| 09-15 | 5240 行 | **13** | **36** |
| 09-17 复查 | 5291 行 | 13 | 36 |

**本批复算**（§5 V1）：

| 时点 | 提交 | `base_skill.py` | 守卫类函数 | 含中文的模块级常量 |
|---|---|---|---|---|
| 2026-08-25 | `f387dff5` | **1090** ✅ 与 issue 一致 | **0** ✅ 一致 | **4**（issue 写 3） |
| 2026-09-15 | `796ad786` | **5240** ✅ 一致 | **12**（issue 写 13） | **44**（issue 写 36） |
| 2026-09-17 | `46c91d3c` | **5291** ✅ 一致 | **12** | **44** |

> ⚠️ **行数三行全对，两个计数列全部对不上** —— 这就是「口径不明的数字不可引用」的现场样本。
> 本文件只认**自己给了正则/命令的那一列**（§5 V1），issue 的 0/13/36 按**历史读数，不可复算**对待。
> **结论方向不变**：0 → 12（门在长）、4 → 44（词表在长），机制②的形态照样成立。

### 3.2 第二组：用例「数量 vs 强度」

| 时点 | 用例数 | 效果层断言 |
|---|---|---|
| 08-25 | 113 条 | 效果层断言 **0** |
| 09-17 | 312 条 | `must_succeed` **40** |

**本批复算**（§5 V2，用仓内单一判据源 `.github/assertion_taxonomy.py`）：

| 时点 | 渲染后用例数 | 含效果层断言 | `must_succeed` | `db_verify` | `amount_verify` |
|---|---|---|---|---|---|
| 2026-09-17 @`46c91d3c` | **310** | **52**（16.8%） | **40** ✅ 与 issue 一致 | 13 | 11 |
| 2026-08-25 @`f387dff5` | **117**（issue 写 113） | **9**（7.7%；issue 写 0） | **0** ✅ | **0** | — |

> **08-25 的 `must_succeed` = 0，本批复算通过** —— 这是「用例在长、判据没长」的**起点证明**：
> 今天 B 端下单用例的「调了 ≠ 成了」缺口，在 08-25 是**整个用例库一条都没有**。
>
> **但「113 条 / 效果层断言 0」两列本批未复现**：
> · 用例数：本批在 `f387dff5` 上实跑渲染器得 **117**（渲染器自打印 `ALL_CASES=117`）；
> · 效果层断言：本批按仓内 `EFFECT_FIELDS` 口径得 **9 条**（7.7%），非 0 ——
>   但这 9 条**不含任何 `must_succeed`**（= 0），所以 issue 的「0」应是指
>   **`must_succeed` 这一列**，而不是整个效果层集合。
> ⇒ **issue 的 113/0 按历史读数（口径不明）对待；本批用 `117 / 9 / must_succeed=0` 三个可复算值代替。**

### 3.3 第三组：豁免清单净生命期进度 = **缩短 1 条**

| 阶段 | 条数 |
|---|---|
| 建账 | **110** |
| 加规则涨到 | **143** |
| 缩到 | **142** |
| 冻结 | 142（2 天） |

**本批复算**（§5 V3）：基线 `.github/case-trust-baseline.json` 的 `violation_case_count` = **142** ✅
（`anchor_sha: 44615b6c`、`case_total: 289`）。
**建账 110 → 143 的历史值本批未逐条回溯** ⇒ 那两个数按历史读数。

> 这条机制**已经在 `#4031` 被收口**：`origin/main` 的 `case_trust_gate.py` 改「全量对账 + burn-down 预算」，
> 并新增**反向对账**（删掉仍在违规的条目 ⇒ 判红，防「随便删都算缩短」）。
> 判据落在 `tests/unit_ci_workflows/test_case_trust_gate.py`（L0，见 §5 V4）。

### 3.4 第四组：fix 占比（**issue 自己已登记口径分歧**）

| 月 | `backend/ai-agent-service/` 月度窗口 + `grep -cE "^fix"` | 全仓 `--no-merges` 口径 |
|---|---|---|
| 6 月 | 56% | 65% |
| 7 月 | 66% | 43% |
| 8 月 | 32%（低产月） | 40% |
| 9 月 | 61% | — |

issue 自己写明：

> **两者测的不是同一个量，均不作点值引用**

**本批立场：尊重这条自我限制 —— 不复算、不引用、只登记口径分歧本身。**
（这也是本批唯一一处**主动不复算**的测量，理由是 issue 已判定它不可作点值。）

### 3.5 第五组：返工热点（本批**可复算，且跑了**）

复算工具：仓内 `scripts/rework_hotspot_scan.py`（报告型，永远 exit 0，**不阻塞**）。

| 量 | issue 读数 | 本批实测（§5 V5） |
|---|---|---|
| 非 merge 提交 | 2184 | **2221** |
| fix 提交 | 1262 | **1284** |
| fix 占比 | **57.8%** | **57.8%** ✅ **一致** |
| `base_skill.py` 文件级 fix | **156** | **163** |
| 全仓 fix 最多的函数 | `unit_price_grounding_error` = **24 次** | **未复现**（见下） |

> **`57.8%` 两处完全一致** —— 这是本批最强的一条交叉验证：issue 与归档在不同时点、
> 用同一脚本得到同一比例。
>
> ⚠️ **「`unit_price_grounding_error` = 24 次」本批未复现**：本批在 `origin/main` 上跑同一脚本，
> 函数级 TOP 15 里没有它（最高 15 次）。两种可能：① 时点差异；② 脚本头部自己声明的
> **「函数级是近似」**（用今天的 AST 区间回溯历史行号，函数被大改时会漂）。
> ⇒ 该数字按 **`未取证`** 对待，**但「被修最多的函数正是造成本次线上死锁的那个」这个方向
> 有另一条独立证据**：`unit_price_grounding_error` 就在 `base_skill.py`（全仓返工第一的文件）里，
> 且它正是 [03-2](03-2-tool-layer-audit.md) §2.1 提到的单价闸门族。

## 4. 机制④ 的复算（基线代码）

```bash
$ git show 46c91d3c:.github/case_trust_gate.py | sed -n '223,246p'
def stale_baseline_entries(baseline: dict, changed_ids: set[str],
                           violations_by_case: dict[str, list[dict]]) -> list[dict]:
    """基线清单里「**本次 diff 命中且已不再命中原违规码**」的项 ⇒ 必须从清单移除。

    ⚠️ **只对本次 diff 涉及的用例生效**（关键，避免假红）：
    ...
    故判定范围 = `changed_ids ∩ baseline.violations`。
    ...
    base_violations = baseline.get("violations") or {}
    stale = []
    for cid in sorted(set(changed_ids) & set(base_violations)):
        ...
```

```bash
# 该口径的「永久豁免」后果，已在 #4031 修 —— 反证测试在 L0：
$ grep -n "test_full_reconciliation_prunes_entries_outside_the_diff" -B 12 \
    tests/unit_ci_workflows/test_case_trust_gate.py | head -20
    def test_full_reconciliation_prunes_entries_outside_the_diff(self):
        """**全量对账**（#4031）：判定范围不再限于「本次 diff 命中的用例」。

        旧口径的病（#4009 裁定 1）：`stale_baseline_entries` 只看 `changed_ids ∩ 清单`，
        于是**只要没人再碰那条用例**，它记的陈旧违规码就永远躺着 = **永久豁免**
        （实测：清单建账 110 → 加规则涨到 143 → **净缩 1 条后冻结**；
        本轮实测存量陈旧码 3 条：`CH-019` / `PG-013` / `PG-015`）。
```

> ⇒ **「110 → 143 → 142 冻结」这三个数在仓库里有第二条独立记录**（L0 测试的 docstring），
> 与 §3.3 的基线 JSON（142）互相印证。这是本批**证据链最完整**的一条。

## 5. 实跑输出（逐字）

```bash
# ── V1：三行测量表（规模 / 守卫类函数 / 中文常量）──
$ git show f387dff5:backend/ai-agent-service/app/graph/skills/base_skill.py | wc -l
1090
$ git show 796ad786:backend/ai-agent-service/app/graph/skills/base_skill.py | wc -l
5240
$ git show 46c91d3c:backend/ai-agent-service/app/graph/skills/base_skill.py | wc -l
5291
# 守卫类函数 / 含中文模块级常量（AST 口径，脚本见 03-1 §3 S9）：
#   2026-08-25 f387dff5 → guard-ish 0  / cn-consts 4
#   2026-09-15 796ad786 → guard-ish 12 / cn-consts 44
#   2026-09-17 46c91d3c → guard-ish 12 / cn-consts 44
```

```bash
# ── V2：用例「数量 vs 强度」（08-25 起点）──
$ c=$(git rev-list -1 --before="2026-08-25 23:59:59" 46c91d3c)   # = f387dff5
$ rm -rf /tmp/cases_0825 && mkdir -p /tmp/cases_0825
$ git archive $c .github/cases | tar -x -C /tmp/cases_0825
$ python3.11 .github/render_cases.py --cases /tmp/cases_0825/.github/cases \
    --out-eval /tmp/ec_0825.py --out-md /tmp/cb_0825.md
✓ eval_cases.py → /tmp/ec_0825.py（117 条）
✓ casebook → /tmp/cb_0825.md（117 条）
✓ 生成物自检通过（ALL_CASES=117）
# 效果层断言（assertion_taxonomy.has_effect_assertion 口径）：
#   2026-08-25 @f387dff5 → 用例 117；含效果层断言 9（7.7%）；must_succeed 0；db_verify 0
#   2026-09-17 @46c91d3c → 用例 310；含效果层断言 52（16.8%）；must_succeed 40；db_verify 13
```

```bash
# ── V3：豁免清单（case-trust-baseline）──
$ git show 46c91d3c:.github/case-trust-baseline.json | python3.11 -c "
import json,sys; d=json.load(sys.stdin)
print('anchor_sha =', d['anchor_sha'])
print('case_total =', d['case_total'])
print('violation_case_count =', d['violation_case_count'])
print('violations 条目数 =', len(d['violations']))
"
anchor_sha = 44615b6c9be18d23709a92c0c7e027da259f0836
case_total = 289
violation_case_count = 142
violations 条目数 = 142
```

```bash
# ── V4：机制④ 的 L0 反证已落 main ──
$ git log --oneline 46c91d3c..8e03e5b3 -- .github/case_trust_gate.py
8cca7664 fix(ci): 断言可信度门禁改「全量对账 + burn-down 预算」—— 豁免清单不再有永久豁免（#4031 P11） (#4048)
cb5254d8 fix(eval): 未登记违规 fail-closed（#4046）+ F16 剩余装饰性断言 + 共享夹具写方复位（#4075 用例侧） (#4091)
```

```bash
# ── V5：返工热点（仓内脚本，报告型）──
$ python3.11 scripts/rework_hotspot_scan.py 2>&1 | head -14
══════════════════════════════════════════════════════════════════════════════
返工高频扫描（issue #4012 追加）—— 同一文件/函数在 git 历史里被 fix 的次数
══════════════════════════════════════════════════════════════════════════════
扫描范围：2221 个非 merge 提交，其中 fix 1284 个（占比 57.8%）
阈值：≥5 次 fix 命中即报告（建议值，来自 issue #4012）

── 文件级（精确：该提交 diff 触及该文件）TOP 15 ──
  163 次 fix / 227 次改动  backend/ai-agent-service/app/graph/skills/base_skill.py
   56 次 fix /  73 次改动  backend/ai-agent-service/app/graph/skills/product_skill.py
   50 次 fix /  77 次改动  backend/ai-agent-service/app/graph/plan_executor.py
   49 次 fix /  78 次改动  backend/ai-agent-service/app/api/chat.py
   38 次 fix /  61 次改动  scripts/agent-poll.sh
   37 次 fix /  79 次改动  .github/cases/order.yml
```

```bash
# ── V6（补）：基线时点的文件级 fix 计数（与 issue 的 156 对照）──
$ git log --no-merges --format=%s 46c91d3c -- backend/ai-agent-service/app/graph/skills/base_skill.py | grep -cE '^fix'
140
```

## 6. 未取证 / 不可复算

- **机制⑤「基础错误不会立刻致痛」**：无机械判据（分析框架）。
- **§3.4 fix 占比四个月份数字**：issue 已自行判定「均不作点值引用」⇒ 本批不复算、不引用。
- **`unit_price_grounding_error` = 24 次**：本批未复现（§3.5）。
- **「建账 110 → 加规则 143」**：基线 JSON 仍能看到 142（终点），但**中间态的 110/143 本批未逐条回溯**；
  它们的第二条记录在 L0 测试 docstring 里（§4），**可引但不可复算**。
- **「08-25 113 条 / 效果层断言 0」**：本批复算得 **117 条 / 9 条效果层 / `must_succeed` 0**（§5 V2）——
  **只有 `must_succeed = 0` 这一列对得上**；用例数与效果层总数按历史读数对待。