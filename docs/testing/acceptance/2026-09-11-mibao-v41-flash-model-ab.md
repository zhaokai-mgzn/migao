# 米宝（B 端）主推理模型 DeepSeek-V4.1-Flash 复测报告 2026-09-11

> **被测对象**：米宝 B 端 AI 客服 agent（`PERSONA=mibao`，租户 1 词元通达）
> **触发**：B 端评测任务遗留 P1 结论为「需模型迭代根治」→ 换模型复跑（issue #3319）
> **依据**：`docs/testing/acceptance-protocol.md`（v1.1）、`migao-dev-flow` §13/§14
> **定位（重要）**：本报告是**模型层 A/B 复测**（L1 机器断言 + 证据引用），
> **不是**完整验收——未做 UA 体验层判定、未做双 AI 交叉验证、全量基线非洁净环境（§4.6/§七）。
> 因此本报告**不下「验收通过」结论**，只给复测判定与后续动作。

## 一、结论（TL;DR）

| # | 结论 | 证据 |
|---|---|---|
| 1 | **「换模型」在 provider 侧早已自动发生**：DeepSeek 2026-09-10 发布 V4.1-Flash，官方把模型名改为 `deepseek-flash`，并把旧名 `deepseek-v4-flash` / `deepseek-v4-flash-vision-exp` **临时路由**到 V4.1-Flash | 实测响应体 `model` 字段回落为 `deepseek-flash`（§3.2） |
| 2 | **`deepseek-v4.1-flash` 不是合法模型名**，正确迁移目标是 `deepseek-flash` | API 报错原文（§3.3） |
| 3 | 遗留 **P1-2（PP-006「模型能力认知边界」）在 V4.1-Flash 上 3/3 通过**；但**对照臂 V4-Pro 同样 3/3** ⇒ 通过**不是换模型带来的**，而是代码层（路由 + `create_item` 引导）修复的成果——历史归因「模型能力边界」属**误归因** | §4.3 / §4.4 |
| 4 | 遗留 **P1-1（LLM 长序列波动）依旧存在，且与模型无关**：波动集中在建品长流程与下单加工项；PR-016 本次 2/3 与 Round 83 记录的 2/3 **完全一致** ⇒ 换模型没有改变该波动 | §4.3 |
| 5 | ⚠️ **发现一个与模型无关的不稳定：PR-014 三臂全败**（本地 flash 0/3、V4-Pro 1/3、线上亦失败），Round 78-82 时曾 ✅100% → 属**代码层**问题，已另立 issue **#3320** | §4.2 / §4.4 / §4.5 |
| 6 | 全量 normal 基线：**66/69（96%）**，落在历史波动区间（93%~98.6%）内，失败项与 Round 82 完全不同（PR-016 本轮反而通过）⇒ 无证据显示 V4.1-Flash 引入确定性回归 | §4.6 |

**一句话**：换到 V4.1-Flash **没有**消解遗留 P1（PP-006 的通过是代码修复的结果，长序列波动照旧），
但仓库模型名 canonical 化仍然必要——旧名只是**临时兼容路由**，随时下线。

## 二、遗留问题清单（最近一次 B 端评测任务的交接项）

### 2.1 来源一：生产就绪性验收报告（2026-09-10）

`docs/testing/acceptance/2026-09-10-agent-capability-final.md`，结论**有条件通过（P1×2）**：

| # | 级别 | 问题 | 证据（原文） | 对应 case |
|---|---|---|---|---|
| 1 | P1 | LLM 长序列波动：单跑通过、全量偶发失败 | 「Round 70 全量复测，各 case 独立会话跑」；报告原文「非代码可修（模型方差）；建议多次采样取多数评估」 | CR-001 / FN-004 / OR-014 / OR-015 / PP-001 / PR-005 / PR-007 / PR-011 / PR-012 |
| 2 | P1 | 模型能力认知：agent 反复宣称「新增加工项不在能力范围」 | 「Round 51-57 探针：路由+引导已修，LLM 顽固」；「通过受模型认知限制」 | PP-006 |

### 2.2 来源二：差距分析收尾（Round 81-83，`docs/design/agent-production-gap-analysis.md` §六十六~六十八）

- Round 82 最终基线 **68/69（98.6%），均分 99%**；
- **剩余 1 个**：PR-016（建品长流程 LLM 方差）；
- Round 83 三次采样 **PR-016 2/3 通过**，「波动确认（非确定性缺陷）」；
- **交接结论原文**：「剩余 1 个不稳定 case（PR-016）为 LLM 长流程方差，多次采样评估 + 重试放行覆盖，**需模型迭代根治**」→ 正是本次换模型复测的触发点。

### 2.3 波动台账（`agent-eval-flakes.json`，201 条）高频 case

`PR-016(17) / PP-006(15) / PR-005(15) / OR-014(14) / PR-014(14) / FN-004(13) / CR-001(12) / PR-007(12) / PR-015(12) / HR-003(11) / PP-001(10) / HR-002(8) / OR-015(7)`

→ 复测用例集 = 上述高频 case ∪ 验收报告 P1 清单，共 **15 条**（§4.2）。

## 三、模型事实核查（一手取证）

### 3.1 官方变更（api-docs.deepseek.com 更新日志，2026-09-10）

> 「DeepSeek V4.1 Flash 已同步上线 DeepSeek API，原生支持多模态，**将模型名称更改为 `deepseek-flash`** 即可调用最新的 V4.1 Flash 模型。旧版本模型 V4 Flash 与 V4 Flash Vision Exp 现已下线，出于兼容考虑，模型名 `deepseek-v4-flash`、`deepseek-v4-flash-vision-exp` 将被**暂时路由**到 V4.1 Flash。」

定价页脚注亦载：「模型名请使用 `deepseek-flash`。旧模型名 `deepseek-v4-flash`、`deepseek-v4-flash-vision-exp` 仍可调用，但对应模型已下线，请求将由 DeepSeek-V4.1-Flash 模型提供服务。」

### 3.2 实测：旧名回落（4 个模型名 × 1 次真实调用）

| 请求 `model` | 响应 `model` | 结论 |
|---|---|---|
| `deepseek-flash` | `deepseek-flash` | ✅ canonical |
| `deepseek-v4-flash` | `deepseek-flash` | 兼容路由生效 |
| `deepseek-v4-flash-vision-exp` | `deepseek-flash` | 兼容路由生效 |
| `deepseek-v4.1-flash` | — | ❌ 见 §3.3 |

### 3.3 实测：非法模型名（关键——避免把错名写进配置）

```
$ curl https://api.deepseek.com/chat/completions -d '{"model":"deepseek-v4.1-flash",...}'
{"error":{"message":"The supported API model names are deepseek-flash, deepseek-v4-pro,
 but you passed deepseek-v4.1-flash.","type":"invalid_request_error"}}
```

⇒ **「v41-flash」在 DeepSeek 官方 API 上的正确写法是 `deepseek-flash`**，不是 `deepseek-v4.1-flash`。

## 四、复测执行与证据

### 4.1 环境与方法

| 臂 | 代码 | 模型 | 端点 | 用途 |
|---|---|---|---|---|
| A（flash） | worktree `origin/main` `eda43dec` | `deepseek-flash` | `http://127.0.0.1:8002` | 主臂：换模型后效果 |
| B（线上） | 当前已部署版本 | 线上配置（未公开） | `https://ai-api.migaozn.com` | 现状对照 |
| C（对照） | 同 A（同代码） | `deepseek-v4-pro` | `http://127.0.0.1:8003` | 区分「模型相关」vs「代码相关」 |

- 三臂共用同一 `admin-api`（`https://api.migaozn.com`）与云 dev DB/Redis；
- runner：`tests/agent_eval/local_runner.py ... --cases .github/cases`（YAML 单一源），`PERSONA=mibao`；
- 每轮 pre_clean 生效（商品去重、员工恢复等），失败签名写入本地 flake 台账（gitignored）。

> **重要限制**：**旧模型（V4-Flash / V4-Flash-Vision-Exp）已下线，无法再调用**——
> 因此不存在「旧模型 vs 新模型」的直接 A/B，「换模型前」只能引用**历史记录的基线**
> （85% / 93% / 98.6%）。§4.4 的 V4-Pro 对照臂是唯一可用的**同代码异模型**对照。

### 4.2 遗留用例扫掠（15 条 × 1 次采样）

| case | 臂 A（`deepseek-flash`） | 臂 B（线上） |
|---|---|---|
| CR-001 | ✅ 100% | ✅ 100% |
| FN-004 | ✅ 100% | ✅ 100% |
| OR-014 | ❌ 50% | ❌ 50% |
| OR-015 | ✅ 100% | ✅ 100% |
| PP-001 | ✅ 100% | ✅ 100% |
| **PP-006** | **✅ 100%** | **✅ 100%** |
| PR-005 | ✅ 100% | ✅ 100% |
| PR-007 | ✅ 100% | ✅ 100% |
| PR-011 | ✅ 100% | ✅ 100% |
| PR-012 | ✅ 100% | ✅ 100% |
| PR-014 | ❌ 75% | ❌ 75% |
| PR-015 | ❌ 50% | ✅ 100% |
| PR-016 | ❌ 0% | ✅ 100% |
| HR-002 | ✅ 100% | ✅ 100% |
| HR-003 | ✅ 100% | ✅ 100% |
| **合计** | **11/15（73%）** | **13/15（87%）** |

**证据引用（失败项原文）**

- `OR-014`：`rounds=7 tools=['product_search','processing_item_query','product_detail'×4,'product_search'×2]`
  → `❌ order_create → unmatched expectation: order_create`（agent 未走到 `order_create`）
- `PR-014`：`rounds=6`，`R1 tools=category_manage,interact cards=form` … `R6 tools=product_manage,product_search`
  → `❌ interact(component=choice, multiSelect=True) → unmatched expectation`
- `PR-015`：`rounds=7`，`R7 tools=category_manage,interact cards=choice`（choice 卡在 R7 才出现，已超出用例轮次）
  → `❌ validate_input` / `❌ product_manage(action=create)`
- `PR-016`：`R5 tools=processing_item_query` → `❌ required_args[processing_item_query.applicable_category_id](R5): 缺失或为空`
  → 确定性断言失败（这是 PR-016 的**核心断言**，按 Round 82 记录「不宜放宽」）

### 4.3 多采样确认（臂 A，N=3，区分「确定性」vs「波动」）

| case | 臂 A pass | 判定 | 与历史记录对照 |
|---|---|---|---|
| **PP-006** | **3/3** | 稳定通过 | 历史 15 条台账记录（"能力误宣"）；Round 51-57 探针顽固 |
| OR-014 | 1/3 | **波动** | Round 80 曾 3/3（auto_fill 时机校准后） |
| PR-014 | **0/3** | **疑似确定性回归** ⚠️ | 验收矩阵曾 ✅100%（无重试） |
| PR-015 | 2/3 | 波动 | 台账 12 条 |
| PR-016 | 2/3 | 波动 | **Round 83 记录 2/3，完全一致** ⇒ 换模型未改变 |

### 4.4 对照臂（臂 C，同代码 + `deepseek-v4-pro`，N=3）

| case | 臂 A `deepseek-flash` | 臂 C `deepseek-v4-pro` | 结论 |
|---|---|---|---|
| PP-006 | 3/3 | 3/3 | **模型无关**（两模型都过） |
| OR-014 | 1/3 | 0/3 | 模型无关（两模型都大体失败） |
| PR-014 | 0/3 | 1/3 | 模型无关（两模型都不稳定） |
| PR-015 | 2/3 | 2/3 | 模型无关（**通过率完全相同**） |
| PR-016 | 2/3 | 2/3 | 模型无关（**通过率完全相同**） |

> **关键推论**：PP-006 在**两个模型**上都 3/3 通过 ⇒ P1-2 的根因不在模型层，
> 而在「路由 + `create_item` 引导」这些**代码层**修复（#3214/#3215）。
> 也就是说：**换模型拿不到 P1-2 的收益，因为收益早已由代码修复兑现**；
> 历史把它归为「模型能力认知边界」是**误归因**（该文档自己已有 3 次误归因纠正先例）。

### 4.5 对照臂小结：五条用例全部「模型无关」

5 条关键用例在两模型上的通过率 **完全同构**（PR-015 / PR-016 逐字相同，
PP-006 双 3/3，OR-014 / PR-014 双失败）⇒ 本轮的通过/失败**都不由 V4.1-Flash 决定**。

**PR-014 的归属结论**：臂 A 0/3、臂 B（线上）失败、臂 C（V4-Pro）1/3 ⇒
**两模型都不稳定、线上也失败** → 与模型无关，属**代码层不稳定/回归**
（Round 78-82 时曾 ✅100%）。已按 §13.3 另立 issue **#3320** 归因，
重点怀疑 `interact(component=choice, multiSelect=True)` 在多选卡路径被确认门禁抢先
（失败轨迹 R5 出的是 **confirm 卡**、全程无 choice 多选卡），与 #3317（B 端 6 Skill 缺 `interact` 绑定）可能同源。

### 4.6 全量 normal 基线（臂 A，`deepseek-flash`，69 条）

```
每日回归（normal） 结果: 66/69 通过, 均分 96%
```

| 失败 case | 证据引用 | 性质 |
|---|---|---|
| CH-009 | `🔵 ❌ CH-009: EXCEPTION:`（异常体为空） | 基础设施/网络异常，非行为判定 |
| PP-005 | `rounds=1 tools=['category_manage','interact']` → `❌ processing_item_query → unmatched expectation`；`❌ required_args: 未调用 processing_item_query` | 一轮内发 choice 卡而未查加工项 |
| PR-008 | `rounds=6`，`R1..R6 category_manage × 6`，`R6 才出 interact cards=choice` → `❌ product_manage(action=create)` / `❌ validate_input` | 与 PR-014 同族（建品 `category_manage` 循环、多选卡迟到） |

**与文档基线对照**：Round 82 记录 **68/69（98.6%），均分 99%**（唯一失败 PR-016）。
本轮 **66/69（96%），均分 96%**。

**诚实归因（三点，缺一即误判）**：

1. **失败项完全不同**：Round 82 的失败是 PR-016，而**本轮 PR-016 通过（100%）**，
   本轮失败的是 CH-009/PP-005/PR-008 ⇒ 更像**运行间波动 + 数据状态**，而非模型引入的确定性回归；
   历史基线本身即在 93% → 94% → 98.6% 之间摆动（±5pp 量级）。
2. **本轮运行叠加了本次实验的数据扰动**：全量跑之前，同一套用例已被扫掠/多采样/对照臂反复执行
   （15 + 15 + 15 + 69 次），云 dev 库中商品/加工项/分类存量与文档基线时**不同**——
   本项目已被反复实证「同名商品歧义 / 存量状态消耗」是确定性失败的头号来源（Round 79/80/83）。
3. 本轮还出现 **3 条「重试放行」**（PR-014 / PR-019 / HR-002 标记 `🎲噪声·重试放行(已记账)`）
   —— 与「长序列波动」的既有结论一致。

⇒ **结论不变**：全量基线落在历史波动区间内，**没有证据显示 V4.1-Flash 引入确定性回归**；
但也不能据此宣称「换模型后基线提升」。

## 五、问题清单（含证据引用）

| # | 级别 | 问题 | 证据引用 | 归属 | 建议动作 |
|---|---|---|---|---|---|
| 1 | **P1** | **PR-014 不稳定（非模型）**：加工项多选一次性提交链路不达 —— agent 走 `category_manage` 多轮后直接 `product_manage`，从未下发 `interact(component=choice, multiSelect=True)`（R5 出的是 confirm 卡） | 臂 A `rounds=6` 且 3 次采样 `0/3`；臂 C（V4-Pro）`1/3`；臂 B（线上）失败（75%）。签名 `interact(component=choice, multiSelect=True)\|unmatched expectation` | **代码层**（非本次模型迁移）→ issue **#3320** | 按 §13.3 归因 + 补 case 有效性验证；重点查 `interact` 绑定与确认门禁（#3317 同源怀疑） |
| 2 | P2 | OR-014 波动（1/3）：agent 7 轮内未达 `order_create` | `rounds=7 … ❌ order_create → unmatched expectation` | LLM 长序列方差（P1-1 残余）+ auto_fill 时序敏感 | 保持台账采样；不单次定论 |
| 3 | P2 | PR-015 / PR-016 波动（各 2/3） | PR-016 `required_args[applicable_category_id](R5) 缺失`；PR-015 `R7 才出 choice 卡` | LLM 长流程方差（与 Round 83 一致） | 已有台账；模型迭代范畴 |
| 4 | — | **历史归因纠正**：PP-006（P1-2）不是模型能力问题 | 双模型均 3/3（§4.4） | 归因层 | 更新验收报告/差距分析的归因表述 |
| 5 | — | 命名风险：旧模型名随时下线 | §3.1 官方原文「暂时路由」 | 配置层 | 本次 PR 已 canonical 化到 `deepseek-flash` |

## 六、沉淀与后续动作

1. **已落地（本 PR #3319）**：仓库内模型名 canonical 化到 `deepseek-flash`
   （`config.py` 默认值 / `.env.example` / 4 个 CI workflow / `deploy/docker-compose.yml` /
   README / wiki 模型表 / E2E 裁判 / 单测断言）；
   顺带修复 `scripts/dev-worktree.sh` 的 `--track` 参数解析缺陷（本地开发脚本，见 PR body）。
2. **待办（另立 issue #3320）**：PR-014 不稳定归因与修复（含 case 有效性验证：
   旧失败重放必 fail、修复后重放必 pass）；重点查 `interact` 绑定 / 确认门禁抢先
   （与 #3317「B 端 6 Skill 缺 `interact` 绑定」可能同源）。
3. **待办**：把 PP-006 的归因从「模型能力边界」更正为「代码层路由/引导修复」
   （避免后续再以「换模型」为由重复投入）。
4. **上线动作（非本 PR 自动生效）**：生产模型名由**服务器侧** `/opt/migao-deploy/.env.ai-agent`
   的 `PRIMARY_MODEL` 决定，仓库改动不会自动改生产 env。若要**显式**钉住 canonical 名，
   需把该文件的值从 `deepseek-v4-flash` 更新为 `deepseek-flash`（行为等价，仅去掉临时路由依赖）。

## 七、诚实边界（未覆盖项，禁止当作验收结论引用）

- ⚠️ **全量基线已跑但非洁净环境**：66/69（96%）是在**被本次实验反复扰动过的云 dev 库**上取得
  （§4.6），与文档 68/69（98.6%）**不构成严格 A/B**；要拿到可对比的基线，需在洁净数据状态、
  且**两模型同环境**下各跑一次全量。
- ❌ **无 UA 体验层判定**：话术可懂度、卡片可用性等体验类断言本轮未做；
- ❌ **无双 AI 交叉验证**：未做独立复核 AI 抽样；
- ❌ **无法与旧模型直接对照**：旧模型已下线（§4.1），「换模型前」只能引用历史记录；
- ⚠️ 臂 B（线上）的**模型身份未知**：仓库无从读取服务器 `.env.ai-agent`；
  臂 A/臂 B 结果高度一致（13/15 同判）是「线上亦在跑 V4.1-Flash」的**弱证据**，非确证；
- ⚠️ **对「波动」的采样量偏小**：N=3 只能区分「明显确定性」与「明显波动」，
  不足以给出通过率置信区间。
