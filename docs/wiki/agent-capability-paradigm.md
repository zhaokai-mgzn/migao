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
| **1** | **声明 = 投影**：对模型可见的能力 / 权限 / 意图声明，必须由代码从真值源投影生成。prompt 文件只放领域知识（术语、默认值、展示格式、示例）。 | `tests/test_agent_capability_paradigm.py::test_no_handwritten_capability_matrix_in_prompts`（`✅ 支持` / `❌ 不支持` 出现在 `references/**` 即红） |
| **2** | **每个投影都有判据**：真值源 → 渲染缝 → 判据，三件套登记在 `tests/agent_projection_ledger.json`。 | `::test_projection_keys_are_frozen`（未登记即红）+ `::test_every_projection_has_resolvable_render_and_guard`（渲染缝不可解析 / 判据文件不存在即红） |
| **3** | **真值变化必须红**：投影的判据里要有「现实快照」—— 工具 / 权限一变就红，逼作者核对文案。 | `tests/test_capability_boundary.py::test_availability_snapshot_is_current` |

> 不变式 3 不是锦上添花：没有它，投影会在**下一次工具变更**时静默失真，
> 而「静默失真」正是 #7291 的成因（9 个文件一起错，没有任何东西会红）。

---

## 二、已登记的投影

| 投影 | 真值源 | 渲染缝 | 进模型？ |
|---|---|---|---|
| **能力索引** | `SkillConfig.tool_names` × `registry.read_only` | `app.graph.skills.base_skill::_capability_index` | ✅ Layer 2.6（域 → 写工具的地图） |
| **能力边界** | 注册表 action enum × mibao 绑定 skill | `app.agents.capability_boundary::render_capability_boundary` | ✅ Layer 2.7（能办什么 / 不能办去哪） |
| **权限范围** | admin-api 权限目录镜像 × 会话角色 | `app.graph.skills.base_skill::_inject_permission_scope` | ✅ 注入（B 端） |
| **意图归属** | `backend/ai-agent-service/app/ontology/schema.yaml::intent_ownership` | `scripts/check_ontology_contract.py` | ❌ CI 门禁（不进 prompt） |

> 能力索引与能力边界**同族不同题**：索引回答「哪个域有哪些写工具」（地图），
> 边界回答「用户能让我办什么、不能办时去哪」（口径）。两者都由注册表推导 ⇒ 不会互相矛盾。

---

## 三、新增 / 修改一条能力时的清单（照做，顺序即安全顺序）

1. **先定位**：它在 [agent-feature-design](../../agent-feature-design.md) §一 的哪一类？
   「页面做不到」/「明显更贵」/「用户不知道要做」——不满足的一律不做。
2. **工具先行**：`app/tools/` 里加 action，同时给全 `parameters.action.enum` / `read_only` /
   `read_only_actions`（这三个是投影的真值源）。
3. **绑定 persona**：`MIBAO_CONFIG.skill_names` / `SkillConfig.tool_names`（绑定面 = 可达性真值）。
4. **面向用户可见的能力**：在 `app/agents/capability_boundary.py` 的 `UNITS` 加一条
   （标签 + 探针 + 后台路径），**不要**改 prompt 文案。
5. **跑判据**：`pytest tests/test_capability_boundary.py` —— 现实快照会红，核对后更新快照。
6. **补评测用例**：`.github/cases/*.yml` + 测试文件头 `# case_ids:`（否则 QA Growth Gate block）。
7. **改 prompt 前的自问**：「这句话是不是在声明能力？」
   **是** ⇒ 去投影，不写这里；**否**（术语 / 默认值 / 格式 / 示例）⇒ 才写。

---

## 四、反模式（都真实发生过，不是假想）

| ❌ | 现场 | 正确形态 |
|---|---|---|
| 手抄能力矩阵到 N 个 prompt | #7291：9/10 与真值相反 | 投影 + 元守卫 |
| 共享层写 persona 专属声明 | `PROMPT-rules.md` 的 B 端能力段进了 C 端 prompt；C 端身份层写的是黄金策（#7292） | persona 门控（`_capability_boundary` 只给 mibao） |
| 只改工具不改声明 | #7054：裁定「上下架都 ❌」而 `product_batch_update` 仍提供 `product_status` | 边界按**产品裁定**渲染 ❌，工具侧缺口另单收口 |
| prompt 当限流器 | `general.md` 曾写「`processing_item_query` 只允许每轮调用一次」 | 代码兜底（限流/去重） |
| 声明只活在 issue 里 | 「#7050 要接回非单据对象创建」没有承载体 | 写进 `UNITS` 探针 + issue |

---

## 五、判据清单（文件 :: 测试名）

- `backend/ai-agent-service/tests/test_capability_boundary.py`
  - `::test_availability_matches_registry_truth`（渲染 == 独立复算）
  - `::test_availability_snapshot_is_current`（现实快照）
  - `::test_probe_flips_when_tool_gains_action`（判别力自证：内存注入 create ⇒ 判为可用）
  - `::test_no_handwritten_capability_claims_in_prompts`（类级防回流）
  - `::test_boundary_injected_for_mibao_only`（C 端零影响）
- `backend/ai-agent-service/tests/test_agent_capability_paradigm.py`
  - 台账形状 / 投影清单冻结 / 渲染缝与判据可解析 / 手写矩阵禁令 / 范式页与索引在位
- `backend/ai-agent-service/tests/test_capability_index_prompt.py`（#4125，既有）

---

## 六、边界（如实登记）

- 本范式**只判「有没有按范式接」**，不判「这条能力该不该有」——后者是业务裁定（铁律 12(c) 五类）。
- 已登记的已知缺口：**C 端身份层未按 persona 分流**（identity.md 是所有 persona 共享的，
  C 端首段写的是「黄金策」）—— 单独立单（issue #7292），**暂不施工**（用户 2026-10-19 裁定先做 B 端）。
- **本体**（`app/ontology/schema.yaml`）是另一类真值源：它目前只做 CI 契约（运行时零消费）。
  把它接到运行时（工具入参闸 / 前置条件闸）是独立议题，不在本范式射程内。
