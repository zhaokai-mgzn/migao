# 03-1 报告①｜Skill 层审计（2026-09-17）

> **来源**：issue [#4041](https://github.com/zhaokai-mgzn/migao/issues/4041) 第一节 ①；
> 审计原文曾位于 `/tmp/migao_audit/TOOL_LAYER_AUDIT.md`（**已被清理，不可检索**）——
> 本文件**不是**那份原文的复制，而是**按 issue 正文 + 仓库内可复现事实重建**。
> **锚定 SHA**：`origin/main` @ `46c91d3c`（审计基线）
> **采集时间**：2026-09-18 03:00 (+0800)
> **性质**：**冻结快照（historical）** —— 行数/比例如 `base_skill.py` 演进立刻过期。
> 每个数字都附**复算命令**；与 issue 正文不一致的，以本文件实测值为准并保留差异说明（见 §5）。

---

## 1. 裁决（issue 原文的结论，此处照录）

> **怀疑成立，但归因需修正**：
> - **不成立于「Skill 层设计错了」**：`SkillConfig`（frozen dataclass）+ `SkillRegistry`（动态节点工厂）
>   是**干净的设计**；确认需求是**声明式**的；配置层有 3 条不变式 + 防不变式空转的厚度守卫。
> - **成立于「承载超额」**：`base_skill.py` 已从「Skill 执行器」退化为**共享业务规则总闸**。

⚠️ **证据等级说明**：「设计是干净的」这一半**本批未取证**（未做 SkillConfig/SkillRegistry 的设计评审）。
可查的锚点是文件存在与形式（下面 §2.1 的 class 计数、`.github/cases/` 的声明式需求），
**「设计干净」本身按「未取证」对待**，不写成已核事实。

## 2. 可复算断言（每条都真跑过，输出见 §3）

### 2.1 文件规模与形态

| # | 断言 | 复算命令 | 实测 @46c91d3c |
|---|---|---|---|
| A1 | `base_skill.py` 行数 | `git show 46c91d3c:backend/ai-agent-service/app/graph/skills/base_skill.py \| wc -l` | **5291** |
| A2 | 模块级函数数（列 0 的 `def`/`async def`） | `git show 46c91d3c:<path> \| grep -cE '^(async )?def '` | **112** |
| A3 | 类数 | `git show 46c91d3c:<path> \| grep -cE '^class '` | **0** |
| A4 | 文件内引用的 **distinct issue 号**数 | `git show 46c91d3c:<path> \| grep -oE '#[0-9]{3,5}' \| sort -u \| wc -l` | **46** |
| A5 | 单函数 `execute_skill` 函数体行数 | 见 §3 AST 命令 | **1699**（`ast` 的 `end_lineno - lineno + 1`，含签名与 docstring） |

> **差异说明（A5 vs issue「1665 行」）**：issue 写 1665，本批 AST 口径实测 1699。
> 两个口径的差别是「是否含签名行 + 装饰器 + docstring」——issue 的 1665 应是**函数体语句区间**口径。
> 本文件不猜它的口径，只登记：**1699 = 可复算值；1665 = 口径不同的历史读数**。

### 2.2 增长与 churn

| # | 断言 | 复算命令 | 实测 |
|---|---|---|---|
| B1 | 7 天膨胀 **3.86×** | 见 §3 S3（按日取当日最后一次提交） | 08-25 = **1090** 行 → 09-15 = **5240** 行 ⇒ **4.81×** |
| B2 | 09-17 复查值 | 同上 | 09-17 @`46c91d3c` = **5291** 行（与 issue 的「5291 行」**一致**） |
| B3 | 占全仓提交比 | `git log --oneline --no-merges 46c91d3c -- <path> \| wc -l` ÷ `git rev-list --no-merges --count 46c91d3c` | **217 / 2181 = 9.95%** |
| B4 | fix 占比 | `git log --no-merges --format=%s 46c91d3c -- <path> \| grep -cE '^fix'` | **140 / 217 = 64.5%** |
| B5 | fix:feat | 同上 + `grep -cE '^feat'` | fix **140** / feat **32** = **4.4 : 1**（与 issue 一致） |
| B6 | 确认卡代码同日 **+42 / −42 / +42** | 见 §3 S6b | **成立**：`47b08840` +42 → `821fb05a` −30 → `1e3c290e` −42 → `f1dd5d33` +42 |
| B7 | 一次净删 **829 行** | 见 §3 S6 | **成立**：`8759d4fa` +119/−948 = **net −829** |
| B8 | 能力误宣守卫 **24 小时内迭代 3 次** | 见 §3 S7 | **成立**：`92b59882` 21:19 → `735ccb6e` 21:55 → `55443207` 22:20（**61 分钟**内 3 次） |
| B8b | 次日（21h21m 后）「自我否定」 | 见 §3 S7 末段 | **形态成立**：`4e5b33db`(09-14 23:58) 落地形态判据 → `92b59882`(09-15 21:19) 删掉前一日的枚举常量、改「形态化」 |
| B9 | 「死循环」被宣布修好 **3 次** | 见 §3 S8 | **成立**（09-13 一天内 3 条自称「真因/终结/消除」） |

> **差异说明（B1 vs issue「3.86×」）**：issue 写 3.86×（1358→5240），本批按「按日取当日最后一次提交」
> 实测 08-25 是 **1090** 行 ⇒ **4.81×**。
> 差异来源是**起点取法**：issue 的 1358 行不在 08-25 的当日末次提交上（该日末次提交是 `f387dff5`，1090 行）。
> **两个都是历史读数，都不作点值引用**；要引用就重跑 §3 S3 并锚定 SHA。

### 2.3 「承载超额」的形态证据

| # | 断言 | 复算命令 | 实测 |
|---|---|---|---|
| C1 | 守卫类函数（名字含 `guard\|block\|denial\|refus\|forbid\|reject\|_hit\|gate`） | 见 §3 S9 | **12 个**（08-25 = 0） |
| C2 | 含中文的模块级常量 | 见 §3 S9 | **44 个**（08-25 = 4） |
| C3 | docstring 仍写着「已移除 Guard 体系」 | `git show 46c91d3c:<path> \| grep -n Guard` | 第 **3552** 行：`移除了 Pipeline/Hook/Guard 体系，把控制权还给 LLM。` |

> **差异说明（C1/C2 vs issue「13 个 / 36 个」）**：issue 写守卫类 **13**、中文词表常量 **36**；
> 本批用**显式枚举的类名/常量名正则**实测 **12 / 44**。两者**都是口径依赖的近似值**，
> 本文件只登记自己的口径与命令（§3 S9），**不把任一方的数字当点值**。

## 3. 实跑输出（逐字）

```bash
# ── S1/S2：规模与形态 ──
$ B=46c91d3c && F=backend/ai-agent-service/app/graph/skills/base_skill.py
$ git show $B:$F | wc -l
5291
$ git show $B:$F | grep -cE '^(async )?def '
112
$ git show $B:$F | grep -cE '^class '
0
$ git show $B:$F | grep -oE '#[0-9]{3,5}' | sort -u | wc -l
46
$ git show $B:$F | grep -n Guard
3552:    移除了 Pipeline/Hook/Guard 体系，把控制权还给 LLM。
```

```bash
# ── A5：execute_skill 函数体行数（AST 口径）──
$ git show 46c91d3c:$F > /tmp/bs_base.py
$ python3.11 -c "
import ast
t=ast.parse(open('/tmp/bs_base.py').read())
for n in ast.walk(t):
    if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name=='execute_skill':
        print('execute_skill', n.lineno, n.end_lineno, n.end_lineno-n.lineno+1)
    if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name=='_run_one_tool':
        print('_run_one_tool', n.lineno, n.end_lineno, n.end_lineno-n.lineno+1)
"
execute_skill 3543 5241 1699
_run_one_tool 4096 4771 676
```

```bash
# ── S3：历史行数（按日取当日最后一次提交）──
$ for d in 2026-08-25 2026-09-15 2026-09-17; do
    c=$(git rev-list -1 --before="$d 23:59:59" 46c91d3c)
    echo "$d $(git log -1 --format='%h' $c) $(git show $c:$F | wc -l | tr -d ' ') 行"
  done
2026-08-25 f387dff5 1090 行
2026-09-15 796ad786 5240 行
2026-09-17 46c91d3c 5291 行
```

```bash
# ── S4/S5：提交占比与 fix 比 ──
$ git log --oneline --no-merges 46c91d3c -- $F | wc -l
217
$ git log --no-merges --format=%s 46c91d3c -- $F | grep -cE '^fix'
140
$ git log --no-merges --format=%s 46c91d3c -- $F | grep -cE '^feat'
32
$ git rev-list --no-merges --count 46c91d3c
2181
```

```bash
# ── S6：净删峰值（把每个提交对**本文件**的增删聚合后排序；net = 增 − 删）──
$ git log --no-merges --numstat --format='%h|%ad|%s' --date=short 46c91d3c -- $F > /tmp/bs_numstat.txt
$ python3.11 - <<'PY'
rows=[]; cur=None; a=d=0
for line in open('/tmp/bs_numstat.txt'):
    line=line.rstrip('\n'); p=line.split('\t')
    if len(p)==3 and p[0].isdigit() and p[2]=='backend/ai-agent-service/app/graph/skills/base_skill.py':
        a+=int(p[0]); d+=int(p[1]); continue
    if cur and a+d: rows.append((a-d,a,d,cur))
    if line and '|' in line: cur=line; a=d=0
if cur and a+d: rows.append((a-d,a,d,cur))
rows.sort()
for net,a,d,c in rows[:3]: print(f"{a}\t{d}\t{net}\t{c}")
PY
119	948	-829	8759d4fa|2026-07-09|refactor(ai-agent): execute_skill 精简为纯 ReAct 循环 — 1732→903行
3	211	-208	d57783bb|2026-08-27|Merge PR #2575: feat   SKU
6	102	-96	df776d9c|2026-06-03|fix(ai-agent): DashScope endpoint/apikey 配置集中化，修复米宝 401
```

```bash
# ── S6b：同日 +42/−42/+42（仅计 base_skill.py 本文件）──
$ for c in 47b08840 821fb05a 1e3c290e f1dd5d33; do
    printf "%s  " $c
    git show --numstat --format='' $c -- $F | awk '{printf "+%s -%s\n",$1,$2}'
  done
47b08840  +42 -0
821fb05a  +0 -30
1e3c290e  +0 -42
f1dd5d33  +42 -0
# 接线存在性（build_confirm_interact_xml 在该提交的文件里出现几次）
#   41ed8f36=2  47b08840=2  821fb05a=1  1e3c290e=1  f1dd5d33=2
```

```bash
# ── S7：能力误宣守卫 3 次迭代（时间戳精确到分）──
$ for c in 92b59882 735ccb6e 55443207; do git log -1 --format='%h %ad %s' --date=iso $c; done
92b59882 2026-09-15 21:19:46 +0800 fix(ai-agent): 能力误宣守卫去过拟合——否定形态形态化替代枚举词表 + 商品域通用反拒绝原则（Closes #3936） (#3937)
735ccb6e 2026-09-15 21:55:35 +0800 fix(ai-agent): 能力误宣守卫迭代2——跨小句否定 + 形态扩展（Closes #3938） (#3939)
55443207 2026-09-15 22:20:42 +0800 fix(ai-agent): 能力误宣守卫迭代3——拒绝文本+工具调用同回合也触发纠正（Closes #3940） (#3941)
```

```bash
# ── B8 补：与「前一晚的判据」的关系（issue 的「次日自我否定」）──
$ git log -1 --format='%h %ad %s' --date=iso 4e5b33db
4e5b33db 2026-09-14 23:58:44 +0800 fix(ai-agent): OR-014 能力自我否定族第 6 次复发——归属错位/「V不了」形态判据 + 回锁目标改为注册表事实 (#3785)
$ git log -1 --format='%h %ad %s' --date=iso 92b59882
92b59882 2026-09-15 21:19:46 +0800 fix(ai-agent): 能力误宣守卫去过拟合——否定形态形态化替代枚举词表 + 商品域通用反拒绝原则（Closes #3936） (#3937)
$ git show 92b59882 -- $F | grep -E '^-[A-Za-z_]+ *= *[\[{(]'
-_PRODUCT_IMAGE_EXTRA_NEGATIONS = ("不包含", "拿不到", "传不了", "改不了", "设置不了", "上不了")
# ⇒ 09-14 23:58 落地的「形态判据」在 09-15 21:19（21 小时 21 分后）就被
#   「形态化替代枚举词表」再次重构：前一天的枚举常量被删。
#   「次日自我否定」= 这条 21 小时的往返（**形态成立**）；是否是「推翻」还是「收敛」
#   属语义判断，本批只登记 diff 事实，不下语义结论。
```

```bash
# ── S8：死循环「修好 3 次」（09-13 一天内）──
$ git log --no-merges --format='%h|%ad|%s' --date=short 46c91d3c | grep -E '死循环' | grep 2026-09-1
a4424f9c|2026-09-13|fix(ai-agent): confirm 卡指纹按内容而非标题措辞（消除"换措辞重发"的确认死循环）
fec259c7|2026-09-13|fix(agent): OR-017 确认死循环真因——加工项「已问过」跨轮记账 + 卡循环拦截 + 诊断证据（issue #3365） (#3366)
e56f3cd5|2026-09-13|fix(ai-agent): confirmValue 由实质内容确定，终结确认死循环（issue #3406） (#3407)
```

```bash
# ── S9：守卫类函数 / 中文常量 ──
$ python3.11 -c "
import ast,re
src=open('/tmp/bs_base.py').read(); t=ast.parse(src)
ns=[n.name for n in t.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]
pat=re.compile(r'(guard|block|denial|refus|forbid|reject|_hit|gate)')
print('guard-ish:', len([n for n in ns if pat.search(n)]))
cn=[n for n in t.body if isinstance(n,(ast.Assign,ast.AnnAssign))
    and re.search(r'[\u4e00-\u9fff]', ast.get_source_segment(src,n) or '')]
print('cn-consts:', len(cn))
"
guard-ish: 12
cn-consts: 44
# 同口径 @2026-08-25（f387dff5）：guard-ish = 0，cn-consts = 4
```

## 4. 7 条反证（issue 原文照录 + 证据等级标注）

issue 明确说这 7 条「同等重要」。**本批只有部分能落到仓库命令上**，逐条标等级：

| # | 反证 | 仓库内可查锚点 | 证据等级 |
|---|---|---|---|
| ① | 声明式内核是好的（`SkillConfig` frozen dataclass + 动态节点工厂） | `tests/unit_ci_workflows/test_l0_reachability_guards.py` 等守卫族在 main 上存在 | **部分取证**（「设计好」本身未评审） |
| ② | 存在真正的统一机制（声明式确认需求 = 改工具类一行） | `app/tools/base.py` 的 `read_only` / `requires_confirmation` 字段 | **部分取证** |
| ③ | 团队已正确定位根因并在收敛（skill 名白名单 → 注册表事实驱动） | `8fe99ee4`「能力自我否定族根治——守卫判据从 skill 名白名单改为状态/事实驱动」 | **取证**（提交信息可检索） |
| ④ | 会删过拟合补丁（一次净删 829 行） | `8759d4fa` net −829（§3 S6） | **取证** |
| ⑤ | vision 族确实收敛（09-06 后 0 提交） | 见下方命令 | **取证（收窄口径）** |
| ⑥ | churn 是脉冲式非均匀 | 见下方命令 | **取证** |
| ⑦ | 测试反馈环有效（有 mutation 红证） | 未在仓库定位到具体红证 artifact | **未取证** |

```bash
# 反证⑤：base_skill.py 里 vision 守卫三函数的改动计数（09-06 之后）
$ git log --no-merges --since=2026-09-07 -p --format='C %h' 46c91d3c -- $F \
    | grep -cE '^[+-].*(_is_degraded_vision_analysis|_vision_retry_needed|_usable_vision_analysis)'
0
# ⚠️ 收窄口径的必要性：按**提交信息含「vision/视觉」**算是 6 条（09-07 之后），
# 其中含 e2e 视觉基线、mini-app 视觉回归等**与 vision 模型链路无关**的提交。
# 「vision 族收敛」只在「vision 守卫函数未被改动」这个口径上成立。
```

```bash
# 反证⑥：churn 按日分布（top 6 天）
$ git log --no-merges --format=%ad --date=short 46c91d3c -- $F | sort | uniq -c | sort -rn | head -6
  33 2026-07-05
  22 2026-09-14
  18 2026-06-07
  14 2026-09-13
  12 2026-09-15
  12 2026-06-12
# ⇒ 217 次改动集中在少数几天，非均匀腐烂（脉冲式）
```

## 5. 与 issue 正文的差异汇总（**不静默覆盖**）

| 量 | issue 正文 | 本批实测 @46c91d3c | 差异来源 |
|---|---|---|---|
| `execute_skill` 行数 | 1665 | **1699** | 计数口径（是否含签名/docstring） |
| 7 天膨胀倍数 | 3.86×（1358→5240） | **4.81×**（1090→5240） | 起点取法（08-25 当日末次提交 = 1090） |
| 占全仓提交比 | 9.7% | **9.95%** | 分母口径（`--no-merges` 2181） |
| 守卫类函数 | 13 | **12** | 名字匹配正则口径 |
| 中文词表常量 | 36 | **44** | 「词表常量」定义口径 |
| 文件内 issue 号 | 44 | **46** | 去重口径（`#[0-9]{3,5}`） |
| fix 占比 | 66% | **64.5%** | 与 issue 自己标注的「口径不同」一致（issue 第五节已登记） |

## 6. 未取证 / 不可复算

- **「同一 ~42 行确认卡代码同日 +42/−42/+42」的「同一段代码」判定**：§3 S6 证的是**行数形态**；
  「是不是同一段」需要逐 diff 语义比对，本批未做 → 按「形态成立、语义未取证」对待。
- **反证⑦（mutation 红证）**：未在仓库定位到对应 artifact。
- **「9 类互不相干职责」**：issue 的分类是人工判断，**无机械判据** → 本批不复算、不登记数字。
- **原始审计报告原文**（`/tmp/migao_audit/TOOL_LAYER_AUDIT.md`）：**不可检索**，
  本文件是重建，不是原件。