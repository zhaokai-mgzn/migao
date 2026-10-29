# 黄金策（B 端）能力审查 — 2026-10-29

> **性质**：能力面审查（结构 + 读数），**不是验收结论**。
> **基线**：`origin/main` @ `b91afe6d5`（2026-10-29 12:28 +0000）。
> **本次没有做的事**：没有派发任何真实 LLM 评测（#4262 用户裁定：默认不跑、不派发）、没有量线上延迟、
> 没有读生产会话数据。文中「评分」是**结构性判断**，不是测出来的分数——凡测出来的都给了命令。
> **配套**：[agent-feature-design.md](../agent-feature-design.md)（能力地图与推进状态）、
> [agent-capability-paradigm.md](../wiki/agent-capability-paradigm.md)（声明=投影范式）、
> [agent-write-boundary.md](../wiki/agent-write-boundary.md)（写面去留清单）。

---

## 0. 一句话结论

**广度已经做完，深度和"可度量"没做。**
40 个只读工具、6 个可达写工具、10 个 B 端 skill（9 业务域 + `general` 兜底）、4 条能力投影都已上线，但：
① **没有任何一条自动行为信号**（全仓真实 LLM 自动触发 = 0）且有 1 个写工具零用例、18 个工具只有 1 条用例；
② 能力边界是**按 persona 投影**而不是**按本轮 skill 投影** ⇒ 同一个 system prompt 里同时出现
「商品改名 ✅ 可直接办理」与「本域无可写工具」——模型只能靠后置守卫兜；
③ 数据分析停在「查出来 + 排版」，没有对比 / 归因 / 下一步。
⇒ 提升能力的正确顺序是 **先修尺子（P0）→ 再修投影粒度（P1）→ 再加深度（P1/P2）**，
而不是继续往 prompt 里加规则（现有 4346 行共享层已经是这个模式的天花板）。

---

## 1. 审查方法（读数全部可复算）

| 读数 | 命令 |
|---|---|
| 工具真值（53 个 = 40 只读 + 13 写） | `.venv/bin/python -c "from app.tools.registry import get_tool_registry as g; print([t.name for t in g().get_all_tools() if not t.read_only])"`（在 `backend/ai-agent-service`） |
| 每个 skill **实际绑定**的工具数 | 见 §3 表；复算脚本见本节末 |
| 系统提示词 / 工具 schema 体积 | 同上脚本（`_build_system_prompt` + `create_skill_registry`） |
| 用例覆盖 | `python3 scripts/mibao_coverage.py --md` |
| 评测触发面 | `grep -n "^on:" -A6 .github/workflows/{agent-eval,post-deploy-eval,agent-eval-adversarial}.yml` |
| 最近评测读数 | `gh run list --workflow=post-deploy-eval.yml`；artifact `post-deploy-eval-mibao.zip` |
| 守卫规模 | `wc -l app/graph/skills/base_skill.py`；`ls tests \| grep guard` |

复算脚本（只读，不调 LLM）：

```bash
cd backend/ai-agent-service && .venv/bin/python - <<'PY'
import sys; sys.path.insert(0,'.')
from app.graph.skills.base_skill import _build_system_prompt, create_skill_registry
from app.graph.skills.skill_registry import get_skill_registry
from app.agents.agents.mibao import MIBAO_CONFIG
from app.tools.registry import get_tool_registry
tr = get_tool_registry()
writes = {t.name for t in tr.get_all_tools() if not t.read_only}
for s in MIBAO_CONFIG.skill_names + ["general"]:
    cfg = get_skill_registry().get(s); reg = create_skill_registry(list(cfg.tool_names))
    print(s, len(cfg.tool_names), len(reg.get_tool_names()),
          sorted(n for n in reg.get_tool_names() if n in writes), len(_build_system_prompt(s)))
PY
```

---

## 2. 评分卡（1~5，结构性判断）

| 维度 | 分 | 依据（读数） |
|---|---|---|
| 能力广度（读） | 4 | 40 只读工具，B 端用例覆盖 39/40 |
| 能力深度（分析/决策） | 2 | `prompts/data.md` 只定义「查哪个 action + 怎么排版」；`dashboard_stats` 无环比/对比 action |
| 写能力（可逆变更） | 3 | 6 个可达写工具（改价/改名/批量/算料口径/通知已读/定时提醒）；创建与删除按裁定不做 |
| 可靠性（不编造 / 不空头承诺） | 3 | 机制很密（13 个 `*guard*.py` 测试），但守卫误判本身成为新的故障源（#7758 / #7347 / #7313） |
| 可度量性 | 1 | 自动行为信号 0 条；无绿色基线；最近一次 normal 全量失败在**建会话 500** |
| 成本 / 延迟 | 2 | 每轮绑定 34~38 个工具（schema 33~40KB）+ 系统提示词 5.7~15KB；`max_iterations=8` |
| 教学 / 步骤指引 | 2 | `nav_guide` 只答「在哪一页 / 有没有权限」，prompt 明写「我没有步骤级指引」（#5989 OPEN） |
| 界面体验一致性 | 4 | 2026-10 的修复集中在卡片/流式/文案，回归用例在涨 |

> 用法：这张表用来**选下一步投在哪**，不要当验收结论引用（见 §7）。

---

## 3. 能力地图（真值源 = 工具注册表 × skill 绑定）

**写面（13 个写工具里，B 端可达 6 个）**

| 域 | 可达写工具 | 形态 |
|---|---|---|
| product | `product_update`（改价/改名）、`sku_update`、`product_batch_update`（批量改价/库存/撤销）、`craft_calc_config_update`（算料口径） | 两段式：`validate_input` → `interact(confirm)` 卡 → 执行 |
| notification | `notification_manage`（标记已读 / 全部已读） | 变更类 |
| reminder | `scheduled_task_manage`（建/取消定时提醒） | 助手级，写工具 |

**未接线（按裁定）**：创建（商品/订单/各类单据）、删除/停用/作废、上下架、员工/角色/客户/分类/加工项/供应商的创建与变更。
口径见 [agent-write-boundary.md](../wiki/agent-write-boundary.md) 与 #5247 / #7050。

**读面**：40 个只读工具，按 persona 家族**跨域共享**（#4125，`create_skill_registry` 的
`_family_read_only_tool_names`）⇒ 任何一轮实际都能看到 34~38 个工具：

| skill | 声明工具 | 实际绑定 | 可达写工具 | 系统提示词 |
|---|---|---|---|---|
| product | 19 | 38 | 4 | 15,030 字符 |
| order | 11 | 34 | 0 | 15,039 字符 |
| general（兜底） | 27 | 34 | 0 | 8,402 字符 |
| data | 6 | 34 | 0 | 8,621 字符 |
| aftersales / customer / staff / knowledge | 3~6 | 34 | 0 | 7.1~9.8K 字符 |
| reminder / notification | 2 | 35 | 1 | 5,736 字符 |

> 结论：**skill 只切写面，不切读面**。所以路由精度只影响两件事：写能力是否可达、拿到哪份域 prompt。
> 这也解释了为什么"错域"的代价常常是**能力被误报为不可用**，而不是查不到数据。

---

## 4. 七个发现（按杠杆排序）

### F1 · 度量断链：没有"能力基线"，也没有快档覆盖写面（P0）

**读数**
- 全仓**自动**真实 LLM 触发 = **0 条**（三个 eval workflow 都只剩 `workflow_dispatch`；#3925/#4262/#4974 三次收敛的结果）。
- B 端用例 **100 条**（`scripts/mibao_coverage.py`）：smoke **8** / normal **76** / 其余 16。
- **smoke 的 8 条里没有任何一条写路径**（AS-001、CU-001、HR-001、HR-004、KN-003、OR-001、PR-001、PR-003）。
- 工具覆盖 **39/40**，**零覆盖 = `craft_calc_config_update`**（最新、也最需要确认链的写工具）。
- 薄覆盖（仅 1 条）= **18 个**工具。
- ✅ **本轮收口后的三档实读**（2026-10-29~30，全部手动 `workflow_dispatch`）：
  | 档 | run | sha | 结果 |
  |---|---|---|---|
  | smoke（mibao） | 40913618599 | f27e332 | **11/11**（PR-133 修后 = 1.0） |
  | adversarial（mibao） | 40922576406 | a8be1a5 | **17/17**（CH-054「连续无进展换策略」= 1.0） |
  | normal（mibao） | 40924392531 | cc5e119 | **79/79、0 失败**（MC-120 步骤级教学 = 1.0、DA-026 日报追问 = 1.0、DA-025 对比 = 1.0） |
  ⇒ 相对 P0 基线（76 条 / 75 过 / 1 失败）与本轮中段基线（77 条 / 76 过 / 1 失败）：
  **用例数 76 → 79，失败 1 → 0**，且新增的三条能力用例首跑即绿。
- ✅ **P0 的三条冒烟写路径已全部实证**（2026-10-29 至 10-30，smoke 档 11/11）：`CH-053` 提醒建/取消、
  `ST-013` 通知标记已读、`PR-133` 改价闭环（首跑因"裸文本答卡"判红 ⇒ 改协作答卡范式后复验 **1.0**）、
  `PP-023` 算料口径写（normal 档单点复验 **success**）。
- 最近一次手动 normal 派发（2026-10-19 run `39247280095`）**失败在基建**：
  `❌ 创建会话失败: HTTP 500 b'Internal Server Error'`；此后 10-24/25 的 4 次 post-deploy-eval 虽 `success`，
  但 artifact 的 `eval-summary-mibao.json` 显示 **total=1**（单条 PR-074 flake 复验），**不是能力基线**。
- ✅ **2026-10-29 已补基线**（issue #8116 / PR #8117，run `40875358973`，sha `b91afe6d5`，B 端 normal）：
  **76 条 / 75 通过 / 1 失败**（avg 0.987，≈7.2 分钟）。唯一失败 `CU-003` 是**尺子错**
  （问「某客户有哪些标签」，旧期望 `list_tags` 返回的是**全店标签目录**；客户自己的 `tags` 在 `detail` 里）
  ⇒ 评测腿本身是好的，之前"没有基线"的直接原因是**没人派发**。

**影响**：现在无法回答「这次改动让黄金策变好还是变坏」。所有"能力提升"都只能靠个案感知。

**该落什么判据**
1. `craft_calc_config_update` 至少 1 条正向用例（含：改前→改后逐键、确认卡、失败不落库）。
2. smoke 档补 3 条写路径（改价 / 通知已读 / 定时提醒）——smoke 是唯一快档，不该 0 写面。
3. 一张**能力基线卡**（一次集中跑 normal，记录 pass/fail + 失败分类 + 耗时），落在 `acceptance/` 或 issue 评论；
   之后按 `migao-dev-flow` §13.2 只跑受影响用例，不重复全量。

---

### F2 · 能力边界按 persona 投影，而不是按本轮 skill 投影（P1，本审查最重要的一条）

**读数**（同一条 system prompt 里的两段话，`order` 回合）

- Layer 2.7（`render_capability_boundary()`，**全局 persona 视角**）首句：
  > 「【能力边界】…**与其它段落的能力口径冲突时以本段为准**」，正文含
  > 「✅ 可直接办理：**商品改价、商品改名**、单规格改价、批量改价 / 批量库存调整…」
- Layer 3（`prompts/order.md`，**本轮 skill 视角**）：
  > 「## 🔴 本域无可写工具（写能力未接线）…**都不在能力内**」

两段都在系统提示词里，且第一段声称"以我为准"。而**本轮确实没有** `product_update` 工具
（`order` 绑定写工具数 = 0，见 §3）⇒ 模型只剩两条坏路：**空头承诺**（说能改）或**误拒**（说不能改）。

**这不是新缺陷，而是 #7291 的同一形态换了位置**：投影做对了（内容跟注册表走），但**投影粒度太粗**
（persona 级而非 turn 级）。现有 `capability_denial_text_hit` / `_order_capability_available` /
`_product_image_denial_hit` 等后置守卫，本质是在**给这句话打补丁**（见 F4）。
近期真实缺陷同族：#7347（问"能否改名"被误拒）、#7758（图片/海报域被下单守卫误判 ⇒ 会话锁死 order）。

**建议修法（最小改动）**
- `render_capability_boundary(skill_name=...)`：**只投影本轮可达的写能力**；不可达但**全局存在**的，
  单独一节「本域不做、但黄金策能办（可改派）」；
- 配一条**改派通道**（B 端目前没有 C 端 `plan_rewrite` / `handoff` 的等价物）：
  模型输出结构化 `route_switch`，或共享层检测到「写意图 + 本域零写工具」⇒ 单次改派到目标 skill；
- 判据（会红）：
  - 静态：`order`（零写工具）的 system prompt 不得出现「✅ …改名」这类本域不可执行的支持话术；
  - 行为：一条用例「在订单查询后说『把这款商品改名为 X』」必须**改派或明确承接**，不得空头承诺、不得误拒。

---

### F3 · 工具选择靠 prompt 里逐条写规则（P1）

**读数**：每轮 34~38 个工具；`prompts/data.md` 出现「**收支汇总必须用 `finance_api(get_summary)`，不要拆解成
`order_query` + `after_sales_manage`** —— FN-004 实拍：agent 拆查导致结果不符」；`order.md` 出现
「加工项 ≠ 加工单，问加工单不得用 `processing_item_query` 冒充」；`product.md` 同类规则多条。
即：**每暴露一次错配，就往 prompt 加一条"不要用 A 做 B"**。

**根因**：工具的 `description` 只写「怎么用」，不写「什么时候**不该**用」；34 个工具并列时，模型只能靠长文规则纠偏。

**建议**
- 工具元数据补两个字段（真值源，可投影）：`triggers`（用户原话形态）、`not_for`（常见误用）；
  生成式"选工具小抄"（Layer 2.8，按本轮可用集合渲染）替代 9 份手写工具速查表（`prompts/*.md` 7 处 + `general_agent.py` / `product_skill.py` 内联各 1 处）；
- 判据：小抄与注册表**双向**一致（未登记即红）；从 prompt 删掉一条规则后，FN-004 类用例仍绿。

---

### F4 · 后置守卫层已经在承担"能力判断"，且缺冲突/死锁判据（P1）

**读数**：`app/graph/skills/base_skill.py` **4,346 行**；`tests/` 下 `*guard*.py` **13 个**；
`grep -n "guard\|corrective\|rewrite\|_hit(" base_skill.py` 命中 **15 行**（另有 `nodes.py` 6 行）。它们在**生成之后**改话术、拦工具、补链路。

**为什么这是问题**：每一层守卫都要自己判断"模型刚才是不是说错了"，而判断依据是正则 + 上下文特征
⇒ 误判即新故障（#7758 就是因为"下单守卫"把图片/海报域的请求判成下单流程）。
更麻烦的是**守卫之间互相不知道**，缺一张"谁和谁互斥、谁先谁后"的矩阵。

**建议（先做最小的一步）**
- **守卫台账**：每条守卫登记「防什么缺陷 / 触发条件 / 与谁冲突 / 判据文件」，未登记即红；
- **统一死锁出口**：同一会话连续 N 轮"无工具调用 + 未推进任何待办" ⇒ 主动换策略（澄清/改派/如实说明），
  这是 #7758「会话锁死」的类级出口，而不是再加一条话术拦截。

---

### F5 · "数据分析"停在查询 + 排版（P1，产品感知最强）

**读数**：`prompts/data.md` 给的是「哪个指标用哪个 action + 表格怎么排」；`dashboard_stats` 的 action 是
`overview / order_trend / order_status / recent_orders / active_sessions / product_ranking / pending_tasks / …`，
**没有**对比、同环比、目标达成；`finance_api` 是汇总/流水/对账三件套。
唯一有"归因 + 建议"的是**每日简报**（`app/briefing/generator.py` 的四区块，异步生成、不在对话内可追问）。

**影响**：商家问「为什么这周订单少了」，黄金策只能说"趋势是下降的"，说不出"因为哪一类商品/哪个客户群/哪一步卡住"。

**建议**：「分析三件套」——① **对比**（本期 vs 上期 / 同目标）② **归因**（按已有维度拆：商品/客户/状态/客服）
③ **下一步**（带页面落点或可执行动作）。①②需要 admin-api 数据面（新字段/新 action，跨模块 ⇒ 单独包），
③在 agent 侧即可（复用 §九 的"引导必须可追溯"）。

---

### F6 · 教学只到"在哪一页"，不答"怎么做"（P2）

**读数**：`general_agent.py` 的导航段逐条写死「**如实说『我没有步骤级指引』**」；`nav_guide` 只返回
菜单路径 + 权限码 + 可见性（#5989 OPEN，用户 2026-10-02 已定 P1）。
**根因**：页面步骤没有真值源，让模型说就是编。**建议**：建"页面动作登记表"（route + 关键按钮 + 前置条件），
用投影生成指引，覆盖高频 5 个动作；未登记 ⇒ 保持现状（如实说没有）。

---

### F7 · 成本与提示词噪声（P2，但改起来最便宜）

**读数**：每轮 input ≈ 系统提示词 5.7~15KB + 工具 schema 33~40KB（实测字符数，未换算 token）；
`max_iterations=8`；此外每轮还有一次意图分类 LLM 调用（短消息/答卡轮已跳过）。

**噪声**：模型可见的 prompt 面里，`#NNNN` 形态的 issue 号共 **53 处**（`product.md` 9、`EXAMPLES-product.md` 6、
`order.md` 5、`EXAMPLES-order.md` 5、`PROMPT-rules.md` 4 …）；还有 `CR-001 实拍`、`run 348…` 这类内部编号。
对人体工程有用，对模型是**无信息量 token**（也可能被当成用户可见文案的素材）。

**建议**：① issue 号/run id 移出 prompt（留在代码注释与文档）；② 工具表改成生成式（F3）；
③ 共享层按 skill 按需注入（如 P&E 段只给有写工具的域）。收益可测：`_build_system_prompt` 字符数 + 工具 schema 字符数。

---

## 5. 优化路线图（建议顺序）

```text
P0 修尺子（1~2 天，零/低成本，不动产品行为）
 ├─ P0-1 补 craft_calc_config_update 用例（写面零覆盖）
 ├─ P0-2 smoke 档补 3 条写路径（改价 / 通知已读 / 定时提醒）
 └─ P0-3 跑一次 B 端 normal 基线（76 条；历史读数：70 条约 48 分钟，见 `.github/workflows/agent-eval.yml` 头部）+ 记录失败分类；顺带确认"建会话 500"是否还在

P1 修结构（每项 1 个包，可并行 ≤3）
 ├─ P1-1 能力边界按本轮 skill 投影 + 跨域改派通道（F2，含静态判据 + 1 条行为用例）  ✅ 投影已落地（#8121）；改派通道仍待做
 ├─ P1-2 工具元数据（triggers / not_for）+ 生成式选工具小抄，替换 9 份手写表（F3）
 ├─ P1-3 分析三件套 · 数据面（admin-api 对比/环比）+ agent 侧归因/下一步（F5，拆 2 包）  🔄 对比已做（Python 侧确定性环比，无需改 Java，#8123）；归因/下一步待做
 └─ P1-4 守卫台账 + 连续无进展的统一出口（F4）

P2 加深度 / 降成本
 ├─ P2-1 页面动作登记表 → 步骤级教学（F6，#5989）
 ├─ P2-2 prompt 去噪 + 共享层按需注入（F7，判据 = 字符数下降 + 用例不回退）
 └─ P2-3 日报条目带追问入口 → 对话内执行闭环（族 1 × 族 4）
```

**每项的验收口径**（照 `migao-acceptance`：断言必须能红）
- P0：用例存在且**注入式红证**能红（删掉确认卡 ⇒ 用例红）；基线卡有 pass/fail 与失败分类。
- P1-1：静态判据（域 prompt 不得出现本域不可执行的支持话术）+ 行为判据（写请求错域必须改派/承接）。
- P1-2：小抄 ⇄ 注册表双向一致；删掉一条"不要用 A 做 B"规则后对应用例仍绿。
- P1-3：对比数据的**真值来自服务端**（前端/agent 只格式化，不重算，§22 基线①）；无数据时如实说"没有对比口径"。
- P1-4：台账未登记即红；死锁用例（连续 3 轮无工具推进）必然触发换策略。

---

## 6.8 本轮收口（P0 → P2 全量交付，2026-10-29 ~ 10-30）

| 路线项 | 交付物 | 合并 | 会红的判据（红证） | 真实读数 |
|---|---|---|---|---|
| **P0 修尺子** | 算料口径写用例 + preclean/restore 机具 | #8117 | `test_craft_calc_config_restore`（改 PUT 载荷/去回读/去幂等短路各红） | `PP-023` normal 单点 **success** |
| P0 smoke 三条写路径 | CH-053 / ST-013 / PR-133 | #8117 / #8144 | 冒烟冻结集合 + 答卡形态判据 | smoke **11/11**（PR-133 修后 1.0） |
| **P1-1 能力边界按 skill 投影** | `capability_boundary.render(..., skill_name)` | #8121 | 26 条（零写 skill 不得自称可办 / 逐 skill 投影 / 单元清单无分隔符） | 26 passed；跨域交接话术由 #8137 补 |
| **P1-2 工具选择元数据** | 6 个易混工具 `【不要用于】` | #8133 | `test_tool_selection_metadata`（删 order_query 那行 ⇒ 4 failed） | 100 passed |
| **P1-3 分析三件套·对比** | `dashboard_stats(trend_compare)` | #8123 | 439 passed（窗口截断/上期 0/非有限数） | `DA-025` **1.0** |
| **P1-3 分析三件套·归因** | 独立只读工具 `sales_attribution` | #8158 | 三段判据（端点权限码 / 核定映射 / L0 名单）+ 聚合红证 | `DA-027` 单点 **1.0** |
| **P1-4 守卫台账** | 75 条（13 后端 + 59 CI + 3 类级） | #8141 | 台账把自身也枚举进去；陈旧/缺失双向红 | 5 passed |
| **P1-4 无进展出口** | `MAX_NO_PROGRESS_ROUNDS=3` | #8152 | 常量改 8 ⇒ 3 failed（`assert 8 == 4`） | `CH-054` adversarial **1.0** |
| **P2-1 步骤级教学** | 5 动作登记表 + `nav_guide(how_to)` | #8149 | 路由真实性 / 权限码真实性 / 未登记必如实 | `MC-120` **1.0**；`lookup` 直调 5/5 |
| **P2-2 prompt 去噪** | 渲染后编号 130→0、字符 −1,584 | #8137 | `test_prompt_denoise`（段首回潮 ⇒ 11 failed；交接话术删掉 ⇒ 1 failed） | 各域长度全部变小 |
| **P2-3 日报追问闭环** | `follow_up{prompt, tool_hint}` + 六类映射 | #8156 | 键集双向相等（删 low_stock ⇒ 6 failed）+ 未知 rule_id fail-closed | `DA-026` **1.0** |

**整体基线**：P0 起点 76 条 / 75 过 / 1 失败 → 收口 **79 条 / 79 过 / 0 失败**；smoke 11/11、adversarial 17/17。

## 6.7 边界合规自查（本轮执行面，逐条对照第 6 节）

| 冻结裁定 | 本轮是否守住 | 证据 |
|---|---|---|
| 不做创建型写（#5247/#5954：商品/订单/单据创建仍在页面） | ✅ | 能力边界 `decided_off` 组原样保留（`创建商品 / 订单 / 各类单据` 仍在「按裁定不做」段）；本轮所有写用例只碰**已接回的 A 档可逆写**（改价 / 算料口径） |
| 不加自动真实 LLM 触发（#3925/#4262/#4974） | ✅ | 本轮 5 次评测全部 `workflow_dispatch` 手动派发；仓库自动触发数仍为 0（未新增任何 `schedule`/`workflow_run`） |
| 不降测试门禁 | ✅ | 唯一被改动的是**新增判据**与生成物刷新；prompt 长度棘轮一处未上调（去噪后整体变小）；`smoke` 冻结集合是**显式**改动并写明理由 |
| 不绕过分支保护 | ✅ | 16 项 required 全绿才合并；非 required 的存量红（Flaky Ledger Reconcile，#8118）没有用 `--admin` 绕过，而是换成「只看 required」的落地器 |
| 不改生成物手写 | ✅ | 所有 `eval_cases.py` / casebook / `output_keys_snapshot.json` 冲突均以**重跑渲染/刷新**解决 |

## 6. 明确不做（沿用既有裁定，本审查不改口径）

- ❌ 创建类（建单/建品/各类单据）、删除/停用/作废 —— #5247 / #5954 / agent-write-boundary。
- ❌ B 档「草稿 + 跳页面」—— 用户 2026-10-02 裁定不做。
- ❌ 让 agent 当表单（多字段逐步收集）、通用 SQL / 自由 join。
- ❌ **不新增自动真实 LLM 触发**（#3925/#4262/#4974）；评测只能人显式派发。
- ❌ 不为了"看起来聪明"增加 prompt 规则条数 —— 规则已经到边际收益递减。

---

## 6.5 执行登记（2026-10-29，本轮落地过程）

| 单 | 内容 | 状态 |
|---|---|---|
| #8116 / #8117 | P0 修尺子：算料写用例 + smoke 写路径 + 配置复位类型 + 基线（75/76） | ✅ 已合并 |
| #8119 / #8121 | P1-1 能力边界**按本轮 skill 投影**（零写域不再宣称「可直接办理」）｜类级守卫：漏传 skill_name 即红、可办探针必须是写工具 | ✅ 已合并 |
| #8120 / #8123 | P1-3 对比：`dashboard_stats(trend_compare)` / `finance get_summary(compare=true)` 由工具确定性计算 | ✅ 已合并 |
| #8118 | Flaky 台账分支欠账（非 required，但与 PR 无关的常态红） | 开单待修 |
| #8124 | CU-003 问句与期望不自洽（`list_tags` = 全店标签目录；客户标签在 `detail`） | 开单待裁定（资产真值守卫拦着） |
| #8125 | 测试顺序依赖：`test_graph_skills` 先跑 ⇒ 能力边界判据红（main 3 条 / P1-1 分支 9 条） | 开单待定位 |
| #8132 / #8133 | P1-2 工具选择真值单源化：6 个易混工具加 `【不要用于】`，删一条同义手写规则 | ✅ 已合并 |
| #8135 / #8137 | P2-2 prompt 去噪：渲染后内部编号 130→**0**，11 个 skill 字符 120,543→**118,959（−1,584）**，并补 `➡️` 段交接话术 | ✅ 已合并 |
| #8136 / #8138 | API-010 补 `[backend-contract]` 标记 + `api.yml` 全量契约标记类级守卫（契约用例不再被行为计分） | ✅ 已合并 |
| #8139 / #8141 | P1-4 前半 守卫台账：75 条（13 后端 + 59 CI + 3 类级），双向相等判据 | ✅ 已合并 |
| #8142 / #8144 | PR-133 冒烟改价用例修答卡形态（裸文本「确认」不放行写）+ 换种子商品 | ✅ 已合并；**smoke 复验 11/11 全绿（PR-133 = 1.0）** |
| #8125 | 测试顺序依赖：`test_graph_skills` 先跑 ⇒ 能力边界判据红（main 3 条 / P1-1 分支 9 条） | 开单待定位 |
| #8147 / #8149 | P2-1 页面动作登记表 → 步骤级教学（5 个高频动作，route/按钮文案全部现取真值） | 待合并 |
| #8150 / #8152 | P1-4 后半 工具循环「连续 3 轮无进展即提前换策略」（循环在 `react_turn.py`，非 `base_skill.py`） | 待合并 |
| #8155 / #8156 | P2-3 日报条目带 `follow_up`（prompt + tool_hint）→ 对话内闭环；未登记 rule_id fail-closed | ✅ 已合并 |
| #8157 / #8158 | P1-3 后半 归因：独立只读工具 `sales_attribution`（`order:list`）按商品聚合两等长窗口、涨跌 Top N；截断披露 + 结构异常 fail-closed。**形态由一道真判据逼出来**：原实现挂在 `dashboard_stats` 上会与订单端点权限码分歧，登记例外会让 `product_manager`/`knowledge_editor` 静默 403 ⇒ 改独立工具、零例外 | ✅ 已合并；`DA-027` 单点复验 = **1.0** |

### 6.6 已接受的缺口（如实登记 + 重启条件，铁律 12(d)）

| 缺口 | 为什么本轮不做 | 重启条件 |
|---|---|---|
| **确定性跨域改派**（P1-1 后半）：模型现在会说「本域不直接办 + 给一句可直接说的话」，但没有一条代码路径把**同一轮**转给能办的 skill | 后半句已由 #8137 的「交接话术」覆盖；长句本来就会重新判意图（`intent_router_node` 的长度分支），真正缺的只是"同一轮内改派"，收益/风险比不佳（误判会把只读问句改写成写请求） | 真实会话里出现「商家按提示说了那句话，下一轮仍被路由回原域」的实证（>=2 次）⇒ 开包做确定性改派，判据 = 只读问句不得改派 + 写请求错域必须改派 |
| **共享层按需注入**（P2-2 后半）：prompt 已去噪（−1,584 字符），但仍是"全量注入"，没有按本轮 skill 只注入相关层 | P1-1 已把能力边界按 skill 投影；其余共享层（权限/记忆/能力索引）体量小、按需注入的编排复杂度高于收益 | 单轮 prompt 超过 20KB 或某层出现"本域不可用"的误用实证 ⇒ 开包做按需注入，判据 = 注入层集合 = 本轮 skill 必需层 |
| **多窗口工具的「截断」元守卫**（P1-3 后半自报）：`trend_compare` / `product_attribution` 都披露了 `truncated`，但没有类级判据强制"以后新增的多窗口工具也必须披露" | 跨工具元判据需要一个"多窗口"的机器判据（现在只能靠 description 关键词猜），先登记观察 | 出现第三个多窗口工具，或任一多窗口工具在真实评测里给出"看起来完整"的截断排名 ⇒ 开包，判据 = 注册表里声明 `multi_window=True` 的工具必须返回 `truncated` 字段 |

**本轮新读出的两个结构性事实**（喂给后续包）：
1. **能力边界的投影缝已经"按回合"化**，但**改派通道仍缺**：模型现在会如实说「本域不直接办」，却没有一条确定性路径把这一轮转给能办的 skill ⇒ 用户仍需自己换场景。这是 P1-1 的剩余一半。
2. **工具循环的位置**已不是 `base_skill.py`：`execute_skill` 是薄壳，真正的模型-工具循环在
   `app/graph/skills/execution/react_turn.py::react_turn`（#4049 逐字搬迁）—— 后续凡要动「循环退出条件/
   迭代上限/无进展判据」的包，改这一处（`max_iterations` 默认 8 未变）。
3. **测试顺序依赖**证明「共享单例 + 全局注册表」在评测/守卫层也在泄漏 —— 与 F4「守卫碎片化」同族，优先级应高于新增守卫。

## 7. 边界（如实登记）

1. **本次没跑真实 LLM**：F2 的"模型会怎么答"是**结构性推断**（同一 prompt 内互斥 + 工具缺失），
   不是实测。要落成事实，需要 §4 F2 的两条判据（静态可立即做，行为需一次显式派发）。
2. **没有线上延迟/失败率读数**：§2 的成本分是按 prompt/schema 体积与迭代上限的**结构估计**，不是测量。
3. **没有生产会话取证**：近期真实缺陷靠 issue/commit 反推（#7758 / #7347 / #7313 / #7236 / #7112），
   不代表失败分布。
4. **评分卡不是评分**：它是"下一刀切哪里"的排序工具；任何"能力已达标"的说法仍需按 `migao-acceptance` 取证。
5. **薄覆盖 ≠ 没能力**：18 个工具只有 1 条用例，是**尺子问题**，不要读成"这些能力坏了"。
