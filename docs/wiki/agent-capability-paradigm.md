# Agent 能力研发范式（元元 / 黄金策共用）

> **为什么有这页**：issue #7291 的现取证据 —— 黄金策的「能力边界」被人工抄写到 **10 个 prompt 文件**，
> 其中 **9 处与工具真值相反**（`非单据对象创建 ✅ 支持`，而 `employee_manage` / `customer_manage`
> 的 action enum 里根本没有 `create`）。模型在**同一个 system prompt** 里同时看到互斥的两句话：
>
> ```
> Layer 2.5/3（手抄）：非单据对象创建 ✅ 支持（员工/角色/客户/标签/分类/加工项）
> Layer 2.6（投影）：【能力索引】写操作只有 notification / product 改价 / reminder 五个工具
> ```
>
> 本页把「怎么避免再发生」写成**机制**，不是写成倡议。

---

## 一、三条不变式

| # | 不变式 | 判据（会红） |
|---|---|---|
| **1** | **声明 = 投影**：对模型可见的能力 / 权限 / 意图声明，必须由代码从真值源投影生成。prompt 文件只放领域知识（术语、默认值、展示格式、示例）。 | `tests/test_agent_capability_paradigm.py::test_no_handwritten_capability_matrix_in_prompts`（旧 token 形态）+ `tests/test_capability_boundary.py::test_capability_prose_matches_registry_state`（**状态驱动**：单元 ✅ 出现拒绝话术 / 单元 ❌ 出现支持话术即红；覆盖 markdown 与 `SkillConfig.system_prompts` 内联 prompt） |
| **2** | **每个投影都有判据**：真值源 → 渲染缝 → 判据，三件套登记在 `tests/agent_projection_ledger.json`。 | `::test_projection_keys_are_frozen`（未登记即红）+ `::test_every_projection_has_resolvable_render_and_guard`（渲染缝不可解析 / 判据文件不存在即红） |
| **3** | **真值变化必须红**：投影的判据里要有「现实快照」—— 工具 / 权限一变就红，逼作者核对文案。 | `tests/test_capability_boundary.py::test_availability_snapshot_is_current` |

> **2026-10-29（issue #8119，按本轮 skill 投影）**：能力边界原先按 **persona 全局**给，
> 于是 `order` 回合的 system prompt 里既有「✅ 商品改名可直接办理（以本段为准）」、又有
> `prompts/order.md` 的「本域无可写工具」——而本轮**确实没有** `product_update` ⇒ 模型只能
> 空头承诺或误拒（同族 #7347 / #7758）。现在按 **本轮 skill 的声明面**分层：
> 「✅ 可直接办理 / ➡️ 本域不直接办 / ❌ 暂未接线 / ❌ 按裁定不做」。
> 判据 = `test_capability_boundary.py` 的 `::test_zero_write_skills_never_claim_direct_capability`
> （零写域不得宣称可直接办理）、`::test_every_mibao_skill_projects_its_own_scope`（类级：
> 漏传 `skill_name` 即红）、`::test_available_units_probe_are_write_tools`（判域前提：
> 可办单元的探针必须是写工具，否则「声明面 ∪ 家族只读」会让判域失效）。

> 不变式 3 不是锦上添花：没有它，投影会在**下一次工具变更**时静默失真，
> 而「静默失真」正是 #7291 的成因（9 个文件一起错，没有任何东西会红）。
>
> 不变式 1 在 #7334 补强：只禁 `✅ 支持` 这类 token 不够 —— 剩余 prompt 仍会用「不在能力内」
> 「写能力未接线」等自然语言声明能力；守卫改为**按当前真值双向判**，工具一变就红。

---

## 二、已登记的投影

| 投影 | 真值源 | 渲染缝 | 进模型？ |
|---|---|---|---|
| **能力索引** | `SkillConfig.tool_names` × `registry.read_only` | `app.graph.skills.base_skill::_capability_index` | ✅ Layer 2.6（域 → 写工具的地图） |
| **能力边界** | 注册表 action enum / 字段 `required_props` / 批量 `batch_type` 枚举值 × mibao 绑定 skill | `app.agents.capability_boundary::render_capability_boundary(skill_name=…)` | ✅ Layer 2.7（能办什么 / 不能办去哪；**按本轮 skill 投影**，issue #8119） |
| **权限范围** | admin-api 权限目录镜像 × 会话角色 | `app.graph.skills.base_skill::_inject_permission_scope` | ✅ 注入（B 端） |
| **意图归属** | `backend/ai-agent-service/app/ontology/schema.yaml::intent_ownership` | `scripts/check_ontology_contract.py` | ❌ CI 门禁（不进 prompt） |

> 能力索引与能力边界**同族不同题**：索引回答「哪个域有哪些写工具」（地图），
> 边界回答「用户能让我办什么、不能办时去哪」（口径）。两者都由注册表推导 ⇒ 不会互相矛盾。
>
> ⚠️ **投影只覆盖已声明单元**：`UNITS` 的清单、标签、后台路径、产品裁定仍是手写面。
> 不能把它读成「全能力自动跟随」—— 新增能力仍需加单元，未加单元由
> `test_every_reachable_write_tool_is_probed` 红（或显式登记豁免）。

---

## 三、新增 / 修改一条能力时的清单（照做，顺序即安全顺序）

1. **先定位**：它在 [agent-feature-design](../../agent-feature-design.md) §一 的哪一类？
   「页面做不到」/「明显更贵」/「用户不知道要做」——不满足的一律不做。
2. **工具先行**：`app/tools/` 里加 action / 字段 / 批量枚举值，同时给全 `parameters.action.enum`、
   `required_props`、`batch_type.enum`、`read_only` / `read_only_actions`（这些是投影的真值源）。
3. **绑定 persona**：`MIBAO_CONFIG.skill_names` / `SkillConfig.tool_names`（绑定面 = 可达性真值）。
4. **面向用户可见的能力**：在 `app/agents/capability_boundary.py` 的 `UNITS` 加一条
   （标签 + 探针 + 字段/枚举值 + 后台路径），**不要**改 prompt 文案。
   多动作标签必须把动作**列全**（如「创建与变更」= create + update）；只接一半就先拆单元。
5. **跑判据**：`pytest backend/ai-agent-service/tests/test_capability_boundary.py` —— 现实快照会红，核对后更新快照。
6. **补评测用例**：`.github/cases/*.yml` + 测试文件头 `# case_ids:`（否则 QA Growth Gate block）。
7. **改 prompt 前的自问**：「这句话是不是在声明能力？」
   **是** ⇒ 去投影，不写这里；**否**（术语 / 默认值 / 格式 / 示例）⇒ 才写。

---

## 四、反模式（都真实发生过，不是假想）

| ❌ | 现场 | 正确形态 |
|---|---|---|
| 手抄能力矩阵到 N 个 prompt | #7291：9/10 与真值相反 | 投影 + 元守卫 |
| 共享层写 persona 专属声明 | `PROMPT-rules.md` 的 B 端能力段进了 C 端 prompt；C 端身份层写的是黄金策（#7292） | persona 门控（`_capability_boundary` 只给 mibao） |
| 只改工具不改声明 | #7054：裁定「上下架都 ❌」而 `product_update.status` / `product_batch_update.product_status` 仍可执行 | 2026-10-19 裁定 A：工具面移除（#7334）；判据 `test_decided_off_status_is_not_exposed_by_tools`（`forbidden_exposures` 反向真值） |
| prompt 当限流器 | `general.md` 曾写「`processing_item_query` 只允许每轮调用一次」 | 代码兜底（限流/去重） |
| 探测 / 投影函数改全局状态 | #7291 实证：可达性探测调 `create_skill_registry`（它按设计写 `tool_scope`）⇒ 执行域停在最后一个 skill，`order_create` 被误判越域 | 探测只读：保存并还原 `tool_scope`；判据 `test_reachability_probe_does_not_leak_tool_scope` |
| 声明只活在 issue 里 | 「#7050 要接回非单据对象创建」没有承载体 | 写进 `UNITS` 探针 + issue |

---

## 五、能力变更 → 用例库（防「尺子没跟上」）

能力的**声明**投影了，如果**评测期望**没跟上，同样会产出"看起来在测、实际恒假"的假绿/假红。
**教训（2026-10-19，本范式自己踩过，照实登记）**：一度把三条用例的
`direct_reply or validate_input` 判成空断言，依据是「手搓可达集（`skill_names` 的
`tool_names` 并集）」—— 而真实工具集还要并入**同一 persona 家族的只读工具**（#4125，
实现点是 `create_skill_registry`）⇒ `validate_input` / `settings_manage` 其实**可达**。
方向整个反了：差点把三条正确用例改成更弱的断言。
**结论：可达性只许走真实现**（`create_skill_registry(...).get_tool_names()`），
手搓并集就是下一处漂移。

| 规则 | 判据 |
|---|---|
| 能力增删 ⇒ **同 PR** 更新 `.github/cases/`，跑 `render_cases.py` 并提交生成物 | CI `Main Freshness Guard` + `Case Contract` |
| B 端用例的**正向工具引用**（`expectations` / `must_succeed` / `required_args` / `order_before`）必须落在 **mibao 可达集**（`direct_reply` 是唯一哨兵） | `tests/test_b_end_case_tool_reachability.py::test_b_end_cases_only_expect_reachable_tools` |
| 负向引用（`forbidden_tools` / `must_fail`）**不在**上条射程：对不可达工具的禁区恒真，属 #4043 族 | 已登记 |
| 能力状态翻转（✅↔❌）⇒ 同 PR 补**真实说法**用例（#7334：CH-051「改名不得被误拒」/ CH-052「批量下架不得谎称已下架」） | `agent-eval.yml`（手动集中跑）；确定性红证在 `test_capability_boundary.py` |
| 没有绿色基线，不下「能力变好了」的结论（#7027）；真实 LLM 评测按 #4262 **只在显式要求时集中跑** | 评测流水线 |

> 这条与 §一 是同一条不变式在两个面的实例：**声明面**是 prompt，**度量面**是用例库。
> 两处都由真值投影/判据守住，能力变更才不需要"记得改十个地方"。

## 六、判据清单（文件 :: 测试名）

- `backend/ai-agent-service/tests/test_capability_boundary.py`
  - `::test_availability_matches_registry_truth`（渲染 == 独立复算）
  - `::test_availability_snapshot_is_current`（现实快照）
  - `::test_probe_flips_when_tool_gains_action`（内存注入 create+update ⇒ 判为可用）
  - `::test_partial_action_does_not_flip`（只加一半 ⇒ 仍不可用）
  - `::test_field_probe_distinguishes_price_and_name`（字段级真值）
  - `::test_every_reachable_write_tool_is_probed`（写工具全覆盖；`sku_update` 曾漏网）
  - `::test_decided_off_status_is_not_exposed_by_tools`（`decided_off` 反向真值）
  - `::test_capability_prose_matches_registry_state`（状态驱动话术守卫）
  - `::test_next_steps_match_frozen_navigation_snapshot`（后台路径完整快照 + 首级真实节点）
  - `::test_no_handwritten_capability_claims_in_prompts`（类级防回流）
  - `::test_boundary_injected_for_mibao_only`（C 端零影响）
- `backend/ai-agent-service/tests/test_agent_capability_paradigm.py`
  - 台账形状 / 投影清单冻结 / 渲染缝与判据可解析 / 手写矩阵禁令 / 范式页与索引在位
- `backend/ai-agent-service/tests/test_b_end_case_tool_reachability.py`（用例 ↔ 可达集）
- `backend/ai-agent-service/tests/test_capability_index_prompt.py`（#4125，既有）

---

## 七、边界（如实登记）

- 本范式**只判「有没有按范式接」**，不判「这条能力该不该有」——后者是业务裁定（铁律 12(c) 五类）。
- 已登记的已知缺口：**C 端身份层未按 persona 分流**（identity.md 是所有 persona 共享的，
  C 端首段写的是「黄金策」）—— 单独立单（issue #7292），**暂不施工**（用户 2026-10-19 裁定先做 B 端）。
- **本体**（`app/ontology/schema.yaml`）是另一类真值源：它目前只做 CI 契约（运行时零消费）。
  把它接到运行时（工具入参闸 / 前置条件闸）是独立议题，不在本范式射程内。
