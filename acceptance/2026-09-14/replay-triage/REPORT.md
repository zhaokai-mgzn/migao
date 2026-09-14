# B 端剩余确定性失败重放归因：OR-015 / PP-006 / PR-007 / PR-016

> **issue**：#3520 ｜ **分支**：`infra/3520-replay-triage` ｜ **环境**：CI 独立栈（docker 标准考场，`persona=mibao`，真实 LLM + fast 档）
> **报告日期**：2026-09-14 ｜ **结论一句话**：
> **4 条用例中 0 条是「agent 能力做不到」**——3 条是**评测资产缺陷**（缺应答轮 / 点名了种子数据里不存在的商品），
> **但重放过程中撞出一个比这 4 条本身更严重的真实产品缺陷（P0，与 4 条用例无关地存在）：B 端「新增加工项」功能不可用。**
> PR-016 的 `applicable_category_id` 经仪器化取证判定为**真实行为缺口**（agent 未传该参数）。

---

## 0. 结论速览

| 用例 | R-verify 34805827043 | R1 复现 34806789461 | R2 仪器化 34807151893 | 归因层级 | 结论 | 处置 |
|---|---|---|---|---|---|---|
| **OR-015** | ❌ 0% | ❌ 0% | ⚠️ 50% | **引导**（脚本缺应答轮） | 评测资产缺陷（断言过严 + 脚本缺轮），非真实缺口 | 校准用例（补「米白」应答轮）；**无需新 issue** |
| **PR-007** | ❌ 50% | ❌ 50% | ❌ 50% | **数据 / 引导**（点名不存在的商品） | 评测资产缺陷（数据层），非真实缺口 | 补种子或归一化输入；**无需新 issue**（并入 #3522） |
| **PP-006** | ❌ 50% | ✅ 100% | ✅ 100% | **数据 + 工具（真缺口）** | 用例分数波动放行，**但底层 `create_processing_item` 真实不可用** | **新开 issue（P0）** ❗ |
| **PR-016** | ❌ 80% | ✅ 100% | ❌ 0% | **工具/引导（真缺口）+ 种子无判别力** | 分数波动；`applicable_category_id` 判定 = **真缺口** | 新开 issue（断言校准 + 种子补判别力） |

**基线说明**：`34805827043` 是同 topic 的**验证轮**（全量 70 条，非本次触发），其逐轮轨迹与本次 R1/R2 同源可比，故一并作为证据（R-verify）。
**⚠️ 不许把这 4 条当成"agent 不会干活"**：三条的核心证据都是 agent 的行为**合理且可解释**，卡点在用例脚本/数据。

---

## 1. 方法与环境

### 1.1 重放命令（真实 LLM + 独立栈，fast 档）

```bash
gh workflow run xiaobu-acceptance.yml --ref main \
  -f persona=mibao -f tier=normal -f case_ids=OR-015,PP-006,PR-007,PR-016 -f fast=true
```

| 轮次 | run id | ref | 说明 |
|---|---|---|---|
| R-verify | [34805827043](https://github.com/zhaokai-mgzn/migao/actions/runs/34805827043) | main | 同 topic 验证轮（全量 70 条），提供同源逐轮轨迹 |
| R1 复现 | [34806789461](https://github.com/zhaokai-mgzn/migao/actions/runs/34806789461) | main | `--case-ids` 收窄 105→4，`EVAL_CONCURRENCY=6`，`max-retries 0` |
| R2 仪器化 | [34807151893](https://github.com/zhaokai-mgzn/migao/actions/runs/34807151893) | `infra/3520-replay-triage` | 同 R1 + **临时**只读入参取证补丁（见 §1.3） |

- CI 日志证明收窄生效：`🎯 --case-ids 收窄：105 → 4 条（OR-015,PP-006,PR-007,PR-016）`（R1 日志）。
- 重试预算：`--max-retries 0`（fast 档）→ 日志有 `⏳ 重试预算用尽（0 次）：后续失败用例按首次结果计入（不再重跑，标签标 no-retry-budget）`。

### 1.2 证据边界（必读，勿越界解读）

| 边界 | 说明 |
|---|---|
| **1 次重放 ≠ 确定性判据** | runner 把"确定性（reproducible）"定义为**两次重试后同指纹失败**（`local_runner.py:1565`）。fast 档 `max-retries 0` 时无分类证据，`completion_verdict` 把 `no-retry-budget` **保守**计入"确定性失败（必须修）"（`local_runner.py:3963`）——**这是保守归类，不是复现性证明**。本报告的复现性判断依据**跨 3 个独立 run 的行为签名一致**，而非 runner 的标签。 |
| **单轮 4 条 = 一次采样** | 每条用例在单 run 内只跑**一个** session；PP-006/PR-016 的跨轮分数分歧（下表）证明**这两个用例本身是 LLM 敏感的**。 |
| **轨迹只含摘要，非全文** | CI 轨迹含：逐轮 `you=`（实际发出消息）、`tools=`、`failed=`、`data=`（工具返回摘要）、`cards=`/`cardreq=`、`ai=`（回复片段，60 字截断）。**不含**完整 final_text、不含 SSE 原始事件、不含工具入参（除写工具）。 |
| **本轮补了一条入参证据** | PR-016 需要区分「agent 传了 `applicable_category_id` 但过滤是 no-op」与「agent 压根没传」。默认轨迹不含只读工具入参 → R2 用**临时补丁**在 `build_round_trace` 补记 `rargs=`（仅 `AGENT_EVAL_TRACE_ALL=1` 生效），**取得直接证据后已 `git reset --hard` 回退**（`grep -c read_args` = 0，最终 diff 仅本报告文件）。 |
| **未做** | 未做 UI 旅程 / 卡片渲染 / 前端持久化验证（本 topic 是 API 级评测归因）；未做 transcript 全文留档（workflow 的 acceptance 步骤 `if persona != 'mibao'`，B 端无 artifact，与 run 注释「B 端剧本 T3.2 补」一致）。 |
| **无 artifact** | 两次 run 的 artifact 上传均报 `No files were found`（flake 台账/证据目录未落盘）→ 本报告证据**全部取自 CI 日志原文**（已留存 `/tmp/run34806789461.log`、`/tmp/run34807151893.log` 副本路径见文末）。 |

### 1.3 临时取证明细（可审计、已回退）

```diff
# tests/agent_eval/local_runner.py，build_round_trace()（仅 R2 使用，已回退）
+            "read_args": ([{"tool": ..., "args": {keyword/applicable_category_id/category_id/...}}]
+                          if os.environ.get("AGENT_EVAL_TRACE_ALL") == "1" else []),
...
+        if ra: bits.append("rargs=" + ";".join(...))
```

---

## 2. 逐条归因

### 2.1 OR-015 —— order_create 前置校验必须真正执行

**结论**：**评测资产缺陷（纯脚本侧）**——用例的 4 轮台词里从来没有回答 agent 反复追问的"颜色"，轮次预算用尽即停在待确认态。**不是真实缺口，也不是断言过严**——`expectations: [validate_input, order_create]` 与 `order_before: ["validate_input before order_create"]` 都是合理且已实现的可执行断言（`local_runner.py:930` `check_order_before`），只是**流程在脚本用光轮次时还没走到那一步**。

**证据（逐轮引用）**

R2（仪器化轮）逐轮轨迹原文（`run 34807151893`）：

| 轮 | `you=`（脚本实际发出） | agent 动作 | agent 原文（片段） |
|---|---|---|---|
| R1 | `创建订单，张三 13800138000 遮光窗帘 3 米` | `product_search`（`rargs={"keyword":"遮光窗帘"}`）→ `product_detail`（price=168）→ `interact(choice)` | 「请点击上方卡片选择规格后，我继续为您办理～」`cards=choice` |
| R2 | `散剪，2.8米门幅` | `product_detail` → `interact(choice)` | 「『遮光窗帘』散剪（2.8 米门幅）有**两个颜色**可选，请点击选择颜色」 |
| R3 | `不添加加工项，确认下单` | `product_detail` → `interact(choice)` | 「还差最后一步：**颜色还没选**。…请点击选择：」 |
| R4 | `确认下单` | `product_detail` → **`validate_input`** → `interact(confirm)` | 「订单信息已核对完毕，请点击上方卡片确认」`cards=confirm` |

→ **`validate_input` 在 R4 真的执行了**（`validate_input(validated=True params{})`）；确凿的失败只剩 `order_create`（`❌ order_create → unmatched expectation`）。
即：**用例的 4 轮台词用光时，agent 恰好停在"待用户点确认卡"这一步**，脚本没有第 5 轮来点确认。

**R-verify / R1 同源**（断言更差，因 agent 措辞不同而在"颜色"上多卡一轮）：
- R-verify（`34805827043`）：R1-R4 全是 `interact(choice title=请选择遮光窗帘的颜色…)`，`rounds=4`，**`validate_input` 与 `order_create` 均未调用** → `score=0%`，两条 `❌ unmatched expectation`。
- R1（`34806789461`）：同样 4 轮全卡颜色（「还没收到颜色选择，我不能凭猜下单哦 🙏」），`score=0%`。

**归因层级**：**引导层（脚本侧）**。三个 run 的行为签名同构：agent 反复请求 `颜色`（因为 `product_detail` 返回 2 个颜色 → 交互卡是唯一取值路径），脚本从未提供。

**为什么这是断言/脚本问题而不是 agent 问题**：
1. 「颜色」是商品真实存在的必填 SKU 维度（种子 `product_colors`：米白 / 浅灰），不是 agent 编造的字段；
2. 同批用例里凡**给了颜色**的都过了：OR-014（R2 发 `米白 · 散剪 · 门幅2.8米` → R5 `order_create` 成功建单 `20260914981180002`）、PR-017、PR-021 同样 "第一个" 就往下走了；
3. 用例期望的 `validate_input before order_create`（`order_before`）与 `required_args[validate_input].fields=[target_tool,target_action]` 都是**可执行断言**，问题只在**轮次预算不够 + 缺一条应答**。

**建议处置（评测资产，改 cases 不改代码）**

1. **补一轮应答**（根因修复）：在 `user_inputs` 里把 R3 明确成颜色，例如
   `"米白，不添加加工项，确认下单"`，并在末尾补一轮 `"确认下单"` 用于点确认卡 —— 直接复用 OR-014 已被验证有效的形态。
2. **`order_before` 已生效且无需改**：`check_order_before` 已实现（`local_runner.py:930`，支持 `A before B` 与限定式 `A[comp:sem] before B[comp]`）；R2 里它没报错是因为 `order_create` 本轮压根未调用（R2 只报 `❌ order_create → unmatched expectation`，未报 `validate_input(R?) 晚于 order_create(R?)`）。**保持不动。**
3. **不要**放宽 `expectations`（不要把 `order_create` 从期望里删掉）：该用例的**真值内核**（`_VALIDATION_RULES[order_create]` 分层读取回归防线，issue #3029）必须保留 `validate_input` 真执行的断言。
4. **建议补"轮次用尽即判据"的可诊断性**（可选加固）：当前轮次用尽时轨迹只说 `unmatched expectation`，看不出"是 agent 不做还是脚本没给机会"——建议在失败详情里附"轮次预算 vs 期望工具缺口"的提示（属评测基础设施改进，非本 issue 必需）。

**是否需新 issue**：**否**。属 issue #3520 自身的"判为等价变体 → 校准断言"分支，改 `.github/cases/order.yml` 即可（另注意：改 cases 后必须跑 `python3 .github/render_cases.py` 重渲染生成物）。

---

### 2.2 PR-007 —— 商品上架（状态流转）

**结论**：**评测资产缺陷（数据层）**。用例点名「遮光窗帘**（100元的那件）**」，而独立栈种子里**只有 ¥168 的那一件**（`xiaobu_eval_seed.sql:52`）。三个 run 判定一致 → 复现性可信。

**证据**

R2（`34807151893`，仪器化，入参可见）：

| 轮 | `you=` | 工具与入参 | 结果 |
|---|---|---|---|
| R1 | `把遮光窗帘（100元的那件）下架` | `product_search` `rargs={"keyword": "遮光窗帘"}` → `data=product_search(products=1 total=1 page=1 size=5 total_pages=1)` | agent：「店里只有一件『遮光窗帘』，当前售价是 **¥168**，没有找到 100 元的那件。请确认一下：」 |
| R2 | `确认` | `interact(component=confirm, title=确认下架商品, confirmValue=确认：商品=遮光窗帘；当前价格=¥168；操作=下架…)` | agent 发**确认卡**（不是执行） |
| R3 | `再把它上架` | `product_detail(id=prod_eval_blackout, price=168.0)` | agent：「『遮光窗帘』当前已经是**在售**状态，无需再上架 ✅ 可能上一步的下架操作没有最终生效」 |
| R4 | `确认` | `product_detail(...)` | agent：「我又核实了一下…目前状态是**在售**…确实不需要再上架」 |

- ❌ 失败断言：`product_manage(action=toggle_status, status=on_sale)` → `unmatched expectation`。

R1 与 R-verify 同根因、措辞略异（R1 R1 轮起手就是「我先查一下这件商品…没有 100 元的那件，麻烦确认一下」，R2 直接发带 `⚠️ 请核对=您提到的是「100 元的那件」，系统内该商品为 ¥168` 的确认卡）。

**数据事实（单一事实源核对）**

- `tests/agent_eval/fixtures/xiaobu_eval_seed.sql:47-60`：`products` 只有 3 条 —— `prod_eval_blackout`(遮光窗帘, **168.00**)、`prod_eval_dark_green`(北欧风窗帘, 128.00)、`prod_eval_summer`(夏日清风窗帘, 158.00)。**无 ¥100 商品**。
- 用例声明的 `pre_clean: product_dedupe{product_keyword: 遮光窗帘, price: 100}` **只能删重复、不能造数据**（`local_runner.py:221-247`：`matched = [... and (price is None or p.get("price") == price)]`；`len(matched) <= 1 → 无需去重`）。R1/R2 日志实证：`🧹 pre_clean:「遮光窗帘」无重复（**0 件**），无需去重` —— 清理器明确报告命中 0 件，**数据缺失被静默吞掉**。
- 「100元的那件」是**云测试环境存量**遗留的写法（引入于 `#3205`/`#3208`/`#3212` 等校准提交，见 `git log -S'100元的那件' -- .github/cases/`）。迁到独立栈后这 6 条用例（CR-001 / PP-001 / PR-005 / PR-007 / PR-017 / PR-021）的输入全部与种子脱节。

**归因层级**：**数据层（种子缺口）**，并由此在**引导层**派生一个"agent 不敢动"的合理反应（价格对不上 → 确认卡二次核对 → 不执行）。

**建议处置**

1. **首选：种子补一件命中"100元"的商品**（一次性归一化 6 条用例），或
2. **次选：用例输入归一化** —— 去掉"（100元的那件）"，改为确定指代（如 `把遮光窗帘下架`，与该用例 `merge_log` 的自包含意图一致：`2026-09-10 校准：评测商品均已 on_sale…改自包含状态流转（下架→上架）`）。
3. **加固**：`pre_clean: product_dedupe` 命中 0 件时应**报错而非静默返回**（`local_runner.py:236` 的 `len(matched) <= 1 → 无需去重` 会把"数据缺失"吞掉，属**评测基础设施的静默失败**，建议单独提改进）。
4. **另一个真实观察（建议单独跟踪，不在本 issue 范围）**：R1/R2 里 agent 把"确认下架"卡发出后，用户答 `确认` 却**没有执行**（R3 说"可能上一步的下架操作没有最终生效"）。R-verify 的 PR-019 也是同形态（`interact(confirm)` 发了、用户答"确认创建"却没 `product_manage`）。**"确认卡后不执行"是跨用例重复出现的形态**，但本报告的单 run 证据不足以判定是 harness 的 `auto_select`/confirm 答复未落到 `confirmValue` 还是 agent 侧问题 → 见 §4 遗留不确定点。

**是否需新 issue**：**否**（并入"B 端种子/输入与独立栈对齐"这一条，见 §3.2）。

---

### 2.3 PP-006 —— 加工项计价方式 + 新增加工项 ⚠️ **撞出 P0 真缺口**

**结论（两层，必须分开看）**：
- **用例判定层**：**不稳定**（R-verify 50% → R1 100% → R2 100%）。**不要**把它当"已修好"——它是因为断言只到"工具被调用"才转绿的。
- **产品层：`create_processing_item` 真实不可用（P0 真缺口）**。三个 run 里**每一次真执行都失败**：
  - R-verify `34805827043`：`❌ processing_item_manage(action=create_processing_item) → tool 'processing_item_manage' matched but arg 'action' expected create_processing_item got list_categories`（该轮 agent 停在 `list_categories`，创建动作根本没发出）；
  - R1 `34806789461`：工具健康度 `processing_item_manage!参数校验失败 × 1`（`failed=processing_item_manage!参数校验失败`，`data=processing_item_manage(参数校验失败)`）；
  - R2 `34807151893`：工具健康度 `processing_item_manage!参数校验失败 × 2`（agent 拿"准确的分类 ID"重试一次仍失败）。

**证据（R2 逐轮，`34807151893`）**

| 轮 | `you=` | 工具 | 结果 |
|---|---|---|---|
| R1 | `查询打孔加工的计价方式` | `processing_item_query{"keyword": "打孔加工"}` → `processing_item_query{}` | `data=processing_item_query(items=0 total=0…)`（关键词无命中）→ `items=4 total=4`（改列全量）；agent：「没有搜到叫『打孔加工』的加工项，我换个方式再查一下全部加工项…但有一个功能相同的 **纳米圈打孔**」 |
| R2 | `新增加工项，计价方式选按个` | `tools=-` | agent 正确拒绝：「『按个』这种计价方式目前系统不支持。加工项支持的计价方式只有 4 种」（**符合用例 `data_checks` 第 2 条**：`per_piece 创建被拒绝`） |
| R3 | `名称叫测试加工，分类选打孔加工` | `processing_item_manage(categories=1)` | agent 如实报告：「加工分类里没有『打孔加工』，目前只有一个…」 |
| R4 | `计价方式按米，单价 8 元` | `processing_item_manage(categories=1)` → `interact(confirm)` | agent 发确认卡：`confirmValue=确认：加工分类=窗帘加工；单价=¥8.00 / 米；名称=测试加工；状态=启用` |
| R5 | `确认` | `processing_item_manage` ×3 | `failed=processing_item_manage!参数校验失败` ×2；`data=processing_item_manage(参数校验失败);processing_item_manage(categories=1);processing_item_manage(参数校验失败)`；agent 尝试"核对分类信息，拿到准确的分类 ID 后重试"仍失败 |

**真实缺陷定位（代码级，静态可判）**

- 工具 schema 的 properties 实测为：`['action','item_id','category_id','name','price','description','unit','processing_item_id','quantity','status']`（`app/tools/processing_item_manage.py`）——**没有 `pricing_method`**。
- 但同一文件的 description 写：`调 processing_item_manage(action=create_processing_item, name, category_id, **pricing_method**)`（第 39 行）→ **工具描述要求 LLM 传一个 schema 里不存在、`execute()` 也不接收的参数**。
- `_create_item()` 只向 admin-api POST `{"name", "categoryId", "price"}`（第 203-207 行）。
- admin-api 契约：`ProcessingItemCreateRequest` 有 `@NotBlank(message="计价方式不能为空") private String pricingMethod;` 与 `@NotNull(message="单价不能为空") private BigDecimal **unitPrice**;`（另有 `@NotBlank categoryId`）。
  ⇒ `pricingMethod` 缺失 + `unitPrice` 缺失 → Bean Validation 400 → 工具把 `error.error.message` 透出为 `参数校验失败`。
- 历史核对：`git log -p -- app/tools/processing_item_manage.py` 显示该文件**从未**发送过 `pricingMethod`（`grep -c pricingMethod` = **0**）；而 DTO 的 `pricingMethod @NotBlank` 由 `#3015`（"加工项回滚 per_piece 与每米数量"）引入 → **契约变更未同步到 ai-agent 侧**。
- 单测为何没拦住：`tests/test_tools_processing_item_manage.py` 只断言 `json_data["categoryId"] == "c1"`（第 70 行），**不断言 `pricingMethod`/`unitPrice`** —— 典型的"弱断言放过契约断裂"（acceptance-protocol §0 机制原因 3）。

**为什么 R1/R2 还判 100% 通过**：用例 `expectations` 只要求 `processing_item_manage(action=create_processing_item)` **被调用过**；写工具的 `success=false` 不进入这次评分（协议 §0 机制原因 1 的原形）。即**该用例现在是"假绿"**。

**归因层级**：**工具/契约层（真缺口）** + 数据层（"打孔加工"分类名不存在，agent 已合理降级到"窗帘加工"）。

**建议处置**

1. **新开 issue（P0）**：`processing_item_manage` 创建加工项打通 —— 修法方向二选一（需实现者定，**不要顺手在本 PR 改**）：
   - ① ai-agent 侧：`_create_item()` POST 补 `pricingMethod` 与把 `price` 映射为 `unitPrice`，并在 schema/description 间对齐参数名；
   - ② 或 admin-api 侧：`pricingMethod` 给默认值、`unitPrice` 兼容 `price` 别名 —— 但 ① 更符合"契约以 Java DTO 为准"的既有约定。
   - 两侧都要补**契约测试**（断言请求体含 `pricingMethod`/`unitPrice`），把 L1 层拦不住的东西前置拦（migao-dev-flow §16.1）。
2. **用例侧（不阻塞上面的修复）**：把 `data_checks: ["success=true"]` 升级成**可执行断言**（`processing_item_manage` 调用必须 `ok=true`，或补 `db_verify` 断言加工项落库）—— 否则这条永远"假绿"。
3. **数据侧**：种子里没有「打孔加工」这个**加工分类**（只有 `pcat_eval_curtain`「窗帘加工」）。用例输入 `分类选打孔加工` 是加工项名/分类名混淆。建议把输入改成「分类选窗帘加工」（该用例的真值内核是**计价方式枚举**，不是分类名）。

**是否需新 issue**：**是 → P0**（`create_processing_item` 契约断裂）。用例校准项并入本 report 的建议。

---

### 2.4 PR-016 —— 分类确认后按适用商品分类过滤/优先推荐加工项（`applicable_category_id` 判别）

**结论（三句话）**
1. **`applicable_category_id` 判别 = 真实行为缺口**（agent 未传该参数）。直接证据来自 R2 仪器化：`required_args[processing_item_query.applicable_category_id](R5): 缺失或为空`（agent 实发 `rargs=processing_item_query{"keyword": "高温定型"}`）。
2. **但该断言在独立栈里同时是"低判别力"的**：种子 3 个加工项的 `applicable_product_categories` 都是 `'[]'`（schema 默认，`docs/sql/schema.sql:256`）＝"适用所有分类"，**按分类过滤在该数据下是数学上的 no-op**。所以断言即使通过也证明不了过滤生效；不通过则可能是"传了别的等价值"。
3. **用例本身不稳定**：R-verify 80% → R1 100% → R2 0%（三个 run 三种结果）。

**证据：跨轮分数与失败签名**

| 轮 | 分数 | 失败断言 | 实际发出/动作 |
|---|---|---|---|
| R-verify `34805827043` | 80% | `❌ interact(component=choice, multiSelect=True) → unmatched expectation` | R3 `category_manage(tree=2)` → R4 `category_manage + processing_item_query(items=4)`，**未发 choice 多选卡**；R5 直接按脚本文本 `已选加工项：高温定型` 记录 |
| R1 `34806789461` | 100% | — | R3 发了 `interact(component=choice title=请选择要关联的加工项（可多选…） options=4 multiSelect=True multiSelectSubmitPrefix=已选加工项：)` ✅ |
| R2 `34807151893` | 0% | `❌ interact(…multiSelect=True)` + `❌ required_args[processing_item_query.applicable_category_id](R5): 缺失或为空` | R5 `rargs=processing_item_query{"keyword": "高温定型"}`（**仅 keyword**）；`category_manage` 入参恒为 `{}` |

**判别推理（agent 是否用了「其它等价过滤方式」）**

- R2 的 `rargs` 是**直接证据**：agent 对 `processing_item_query` 传的是 `{"keyword": "高温定型"}`（`items=1 total=1`），**没有 `applicable_category_id`**。R1 虽然 `required_args` 通过（说明那次传了非空值），但**同样没有发 choice 多选卡**，用户可见路径是"文本直说已选加工项"。
- **过滤是否真的生效？在该栈里不可观测**：种子 3 条加工项 `applicable_product_categories` 均为默认 `'[]'` → admin-api 侧 `(applicable_product_categories = '[]'::jsonb OR applicable_product_categories @> {0}::jsonb)`（`ProcessingItemService.java:58-63`）恒为真 → **传与不传都返回全部 4 条**。
  ⇒ 想用「items 数变少」证明"过滤生效"是**不可行的**（R2 R5 的 `items=1` 是 `keyword` 造成的，不是分类过滤造成的）。因此**不能**把 `required_args` 校准成"过滤生效的可执行证据"——那条路在当前种子下没有可判定的谓词。
- 同时**不能**据此说 agent"没能力做"：R1 确实传过 `applicable_category_id`，说明模型认识这个参数；R2 传 keyword 属**合法但不等价**的路径（keyword 能命中单个加工项，但**不具备"按分类过滤/推荐"语义**，也不覆盖用例 `data_checks` 第 2 条"适用分类为空的加工项仍展示"）。

**判定**：**保留 `required_args` 断言（真缺口）**，但**必须补种子的判别力**，否则该断言既拦不住真缺口（no-op 时通过也无意义），又会因 agent 措辞变化反复 flake。

**建议处置**

1. **保留断言**：`required_args[processing_item_query].fields=[applicable_category_id]` 不动（它抓到了 R2 的真缺口）。
2. **给断言加判别力（关键）**：种子里补 **≥1 个 `applicable_product_categories` 明确限定到某个商品分类的加工项**（另建一个商品分类，如"轻奢系列"，并让该加工项只适用它）。这样：
   - 过滤生效 ⇒ `items` 数在"传 vs 不传 `applicable_category_id`"下**可区分**（产生 acceptance-protocol 要求的可执行谓词）；
   - 同时覆盖 `data_checks` 第 2 条（适用分类为空的加工项仍展示）—— 现在这条**无法验证**（全是空）。
3. **断言升级为"值正确"而非"字段非空"**：`required_args` 只判 `bool(v)`；建议再加一条可执行断言，校验 `applicable_category_id == 已确认的商品分类 ID`（R2 显示 `category_manage` 入参恒为 `{}`，agent 手上有 `cat_eval_curtain` 却未透传，值级别校验能抓到）。
4. **顺带发现（建议单独提改进）**：
   - R2 R1 出现非法工具调用：`failed=interact!form 组件需要至少一个 formField`（agent 先发了一次空表单再修正）。属**模型单次失误**（同轮已自愈），建议记为观察项，不必单独开 issue。
   - `interact(component=choice, multiSelect=True)` 这条断言在 R-verify/R2 失败、R1 通过 —— 说明 agent 的"是否发多选卡"受措辞影响，属 §14.2 的"有效性漂移"候选：可考虑把断言放宽为 `interact(choice) 或 文本已选加工项`（**但必须先修种子判别力**，否则放宽 = 放弃覆盖）。

**是否需新 issue**：**是**（评测资产：种子判别力 + 断言升级为值校验）。**保留** `applicable_category_id` 真缺口判定的结论。

---

## 3. 需要新开的 issue 清单

### 3.1 🔴 P0（真实产品缺口，建议立即开）

**标题**：`fix(ai-agent): processing_item_manage 创建加工项不可用——请求缺 pricingMethod/unitPrice，admin-api 400「参数校验失败」`

**证据**：run [34807151893](https://github.com/zhaokai-mgzn/migao/actions/runs/34807151893) / [34806789461](https://github.com/zhaokai-mgzn/migao/actions/runs/34806789461) 的 `failed=processing_item_manage!参数校验失败`；run [34805827043](https://github.com/zhaokai-mgzn/migao/actions/runs/34805827043) 的 `❌ processing_item_manage(action=create_processing_item) got list_categories`（该轮 agent 连 action 都没到）。

**要点**：工具 description 承诺 `pricing_method` 但 schema 无此属性、`execute()` 不接收；`_create_item()` POST `{name,categoryId,price}` 缺 admin-api 必填的 `pricingMethod` 与 `unitPrice`；单测仅断言 `categoryId` 故未拦住；PP-006 因断言只到"调用过"而**假绿 100%**。

**修复方向**：ai-agent 侧补 `pricingMethod` + `price→unitPrice` 映射（或 admin-api 侧兼容），并补**请求体契约测试**（L1 层拦截）。

### 3.2 🟡 P1（评测资产：种子与输入对齐，建议开一条合并 issue）

**标题**：`chore(eval): 独立栈种子与 B 端用例输入对齐——6 条用例点名「遮光窗帘（100元的那件）」但种子无 ¥100 商品；加工分类「打孔加工」不存在`

**证据**：
- `xiaobu_eval_seed.sql:52` 遮光窗帘 = **168.00**，无 ¥100；`pre_clean: product_dedupe` 命中 0 件（`🧹「遮光窗帘」无重复（0 件），无需去重`）。
- 受影响用例（`grep -rn "100元的那件" .github/cases/`）：`cross.yml:24`(CR-001)、`processing.yml:21`、`product.yml:142`(PR-005)、`product.yml:203`(PR-007)、`product.yml:640`(PR-017)、`product.yml:804`(PR-021)。
- 加工分类种子只有 `pcat_eval_curtain`「窗帘加工」（`xiaobu_eval_seed.sql:24-25`），用例 `分类选打孔加工`（PP-006）无对应分类。
- **附带加固**：`local_runner.py:236` 的 `product_dedupe` 命中 ≤1 件时静默返回 → 建议改为**显式提示"数据缺失"**，避免同类缺口再次静默吞掉。

### 3.3 🟡 P1（评测资产：PR-016 断言判别力）

**标题**：`chore(eval): PR-016 断言缺判别力——种子加工项 applicable_product_categories 全为空（过滤为 no-op），required_args 应升级为值校验`

**证据**：R2 `required_args[processing_item_query.applicable_category_id](R5): 缺失或为空` + `rargs={"keyword": "高温定型"}`；`docs/sql/schema.sql:256` 默认 `'[]'`；`ProcessingItemService.java:58-63` 空数组恒命中。

**要点**：保留断言；补 ≥1 个限定分类的加工项使过滤可判定；断言从"字段非空"升级为"值 = 已确认分类 ID"。

### 3.4 ⚪ 观察项（建议先记录，暂不开 issue）

- **"确认卡后不执行"形态**：PR-007 R2→R3 与 PR-019（R-verify）都在发 `interact(confirm)` 后未执行预期写操作。需专门重放区分「harness 的 confirm 答复未落到 `confirmValue`」vs「agent 侧问题」——见 §4。
- **`interact!form 组件需要至少一个 formField`**（PR-016 R2 R1）：模型单次失误、同轮自愈，记为观察项。
- **B 端评测无 transcript artifact**（workflow `if persona != 'mibao'`）：证据只能取日志，与协议 §4.1"transcript 可下载留档"不符，B 端剧本 T3.2 待补。

---

## 4. 遗留不确定点（诚实标注）

1. **单 run 无法区分"波动"与"确定性"**：runner 的 `reproducible` 需要两次同指纹重试，fast 档 `max-retries 0` 拿不到。本报告的复现性判断基于**跨 3 个独立 run 的行为签名一致性**（OR-015/PR-007 三轮同构 ⇒ 可信；PP-006/PR-016 三轮分歧 ⇒ 不可判为确定性）。**PP-006 与 PR-016 需要 normal 档（含 3 次重试）重放才能给出 runner 口径的分类。**
2. **`create_processing_item` 失败的直接服务端日志未取到**：`参数校验失败` 是工具透出的 `error.error.message`，我未能取到 admin-api 的 400 响应体原文（diagnose 步骤只 `--tail=60`）。**契约断裂的定位基于静态代码 + 插值**（DTO 的 `@NotBlank pricingMethod` + `@NotNull unitPrice` vs 工具 POST 的 `{name,categoryId,price}`），建议修复者在本地栈用同一请求复现确认。
3. **PR-016 R1 那次"传了 `applicable_category_id`"的具体值未知**：R1 未做仪器化（那是 R2 才加的补丁），只能由 `required_args` 通过反推"非空"，**无法证明值 = 已选分类 ID**。
4. **"确认卡后不执行"的根因未定**：需要一次专项重放（读 harness 的 confirm 答复内容 + agent 侧 confirm 状态机日志）才能判定是评测 harness 还是产品行为。
5. **未做 UI/前端层验证**：本报告全部为 API 级评测归因，不覆盖卡片渲染、刷新重放、会话生命周期（协议 §0 机制原因 6 的盲区），故**本报告不对"用户看到的交互卡好不好用"下任何结论**。
6. **本次未改任何用例/代码**（`git diff` 最终仅新增本报告文件）；所有处置建议（校准断言 / 补种子 / 修契约）均**留给对应 issue**，未在本 PR 顺手改。

---

## 5. 证据留档

| 项 | 位置 |
|---|---|
| R-verify 日志（全量 70 条） | `gh run view 34805827043 --log`（本地副本 `/tmp/run34805827043.log`） |
| R1 日志（4 条收窄） | `gh run view 34806789461 --log`（本地副本 `/tmp/run34806789461.log`） |
| R2 日志（4 条 + 入参取证） | `gh run view 34807151893 --log`（本地副本 `/tmp/run34807151893.log`） |
| 临时取证补丁 | 未入库；已 `git reset --hard 466ecf83`，`grep -c read_args tests/agent_eval/local_runner.py` = 0 |

> 本报告由研发代理（DSH）自动生成，按 `docs/testing/acceptance-protocol.md` v1.3 §1.5/§1.7 要求逐条给证据引用；
> **未做双 AI 交叉验证**（本报告是归因/证据采集，不是"验收通过"结论，故不适用 §1.7 的复核裁判要求；若据此报告下"评测达标"结论，需另按 §1.6 跑 `completion_verdict` + §1.7 双裁判）。
