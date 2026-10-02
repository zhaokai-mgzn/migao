# 变更射程 → 必跑具名判据（Change Blast Radius）

> **唯一数据源** = [`.github/scripts/blast_radius.py`](../.github/scripts/blast_radius.py)；本页是它的人读镜像
> （逐面锚 `<code>面名</code>` ↔ 具名判据，双向由 `tests/unit_ci_workflows/test_blast_radius_registry.py` 核）。
> `growth_gate` 在每次提交时按**同一份数据**打印「你还欠这几张登记面」。

## 为什么有它（实证，不是臆测）

2026-10-02 这批并行开发给每个包下的硬约束是「**不跑全量套件**（`verify-all.sh` 各档不跑，重活锁归集成侧）」。
结果**四条 PR 全栽在同一处**，共 **17 条红**，形态完全相同 —— **判据只存在于全量单测里，窄跑看不见**：

| PR | 红 | 缺的面 |
|---|---|---|
| #5961 | 7 | 复位族登记 · 写点登记 · 产出键/断言规格 · 产出键快照 |
| #5963 | 1 | state 必需字段期望 |
| #5965 | 5 | 工具见证集 · 核定权限码映射 · 工具门面导出 · RBAC 单一源清单与上限 · 死能力 meta-guard 扫面 |
| #5967 | 4 | 迁移指纹 · bootstrap 建库面 · 事件通道基线 · 台账销账 |

**根因**：这些判据**不在任何窄测试文件里**，`growth_gate` 与 cases 面门禁**都不覆盖**它们
⇒ 只跑窄测试的包在这些面上是**结构性盲的**。

**口径（逐字）**：

> **「窄集」必须由「变更的射程」反推** —— 改了工具源码 ⇒ **所有扫工具源码的 meta 面都在射程内**；不是靠回忆清单。

## 主表：变更面 → 必跑具名判据 → 可复制命令

命令里 `<venv>` = 该服务的虚拟环境根（`ai-agent-service` 现场只有一个）：
`backend/ai-agent-service/.venv`（**每个 worktree 要自建**，见文末「未覆盖与风险」）。
Python 面优先 `.venv/bin/python`，缺失时退回 `python3`。设 `SVC=backend/ai-agent-service`。

| 变更面 | 必跑的具名判据（扫这一面的 meta 守卫） | 可复制命令 | 实测 |
|---|---|---|---|
| <code>tool</code> 新增/删除 tool（含 registry / 门面 / skill 绑定） | `backend/ai-agent-service/tests/test_tools_registry.py`（门面导出）· `backend/ai-agent-service/tests/test_tool_permission_codes.py`（核定权限码映射）· `backend/ai-agent-service/tests/test_readonly_cross_domain_sharing.py`（只读跨域见证集）· `backend/ai-agent-service/tests/test_skill_config_registry.py`（skill ↔ 工具绑定）· `tests/unit_ci_workflows/test_dead_capability_meta_guard.py`（死引用/死守卫/死绑定）· `tests/unit_ci_workflows/test_agent_permission_parity.py`（Agent 权限 ≡ 页面权限） | `<venv>/bin/python -m pytest backend/ai-agent-service/tests/test_tools_registry.py backend/ai-agent-service/tests/test_tool_permission_codes.py backend/ai-agent-service/tests/test_readonly_cross_domain_sharing.py backend/ai-agent-service/tests/test_skill_config_registry.py -q` <br> `python3 -m pytest tests/unit_ci_workflows/test_dead_capability_meta_guard.py tests/unit_ci_workflows/test_agent_permission_parity.py -q` | ✅ 红证 ① |
| <code>state</code> 新增/删除 graph state 字段 | `backend/ai-agent-service/tests/test_graph_state.py`（state 形状）· `backend/ai-agent-service/tests/test_agent_state.py`（初始状态**必需字段期望**） | `<venv>/bin/python -m pytest backend/ai-agent-service/tests/test_graph_state.py backend/ai-agent-service/tests/test_agent_state.py -q` | ✅ 红证 ② |
| <code>migration</code> 新增迁移 / 改 `db/init/schema.sql` | `tests/unit_ci_workflows/test_migration_immutability.py`（已发布迁移**内容指纹冻结** + 未登记即红）· `tests/unit_ci_workflows/test_migration_references_exist_in_schema.py`（引用的表/列在 schema 里存在） | `python3 -m pytest tests/unit_ci_workflows/test_migration_immutability.py tests/unit_ci_workflows/test_migration_references_exist_in_schema.py -q` | ✅ 红证 ③ |
| <code>batch</code> 新增/删除 **batch_type** / 写点 / 事件通道 | `tests/unit_ci_workflows/test_batch_stocktake_write_point.py`（写入点唯一 + 来源族列形状互斥）· `tests/unit_ci_workflows/test_eval_write_site_dispositions.py`（评测写点处置表）· `tests/unit_ci_workflows/test_case_machine_fail_channel.py`（事件通道基线快照） | `python3 -m pytest tests/unit_ci_workflows/test_batch_stocktake_write_point.py tests/unit_ci_workflows/test_eval_write_site_dispositions.py tests/unit_ci_workflows/test_case_machine_fail_channel.py -q` | ✅ 红证 ④ |
| <code>eval-fixture</code> 改夹具 / **复位族** / **产出键** | `tests/unit_ci_workflows/test_eval_preclean_registry.py`（pre/post_clean 登记 + 阶段一致性）· `tests/unit_ci_workflows/test_assertion_specs_wellformed.py`（产出键可生产 / 推导钉死 / 快照） | `python3 -m pytest tests/unit_ci_workflows/test_eval_preclean_registry.py tests/unit_ci_workflows/test_assertion_specs_wellformed.py -q` | ✅ 红证 ⑤ |
| <code>rbac</code> 改权限码 / 菜单码（`menu.ts` ↔ 后端注解） | `tests/unit_ci_workflows/test_rbac_single_source_manifest.py`（清单 == 生成物 == 现值 + 副本未登记即红）· `tests/unit_ci_workflows/test_agent_permission_parity.py`（菜单三源同构 + 岗位码面） | `python3 -m pytest tests/unit_ci_workflows/test_rbac_single_source_manifest.py tests/unit_ci_workflows/test_agent_permission_parity.py -q` | ✅ 红证 ⑥ |
| <code>casebook</code> 改用例面（`cases/**`、`templates/**`、生成物） | `tests/unit_ci_workflows/test_cases_yaml_strictness.py` · `tests/unit_ci_workflows/test_render_cases_domain_map.py` · `.github/render_cases.py`（重渲染）· `.github/truths.py`（真值引用完整性） | `python3 -m pytest tests/unit_ci_workflows/test_cases_yaml_strictness.py tests/unit_ci_workflows/test_render_cases_domain_map.py -q` <br> `python3 .github/render_cases.py --cases .github/cases --out-eval tests/agent_eval/eval_cases.py --out-md docs/testing/mibao-verification-cases.md` <br> `python3 .github/truths.py check --templates .github/templates --cases .github/cases` | ✅ 红证 ⑦（生成物新鲜度） |
| <code>web</code> 改 web 页面 | `check-ui-regression.sh`（neutral token vs `origin/main`）+ **Playwright 页面多模态验收**（真实登录 + 截图 + AI 读图） | `./check-ui-regression.sh` <br> 多模态验收的承载体与假绿清单见 **`migao-dev-flow` §15.7** | ✅ 文件存在 + 命令可跑 |

**为什么命令一律**从**仓根**用**仓库相对全路径**（不写「先 cd 进服务目录、再 pytest 相对路径」那种形态）：
本仓有判据 `tests/unit_ci_workflows/test_recomputable_command_paths.py`（M4）会逐字解析文档/注释里的
「可复算命令」并核**它指涉的路径是否存在** —— `cd` 之后写的相对路径它解析不到，会判红
（实测：本文件首版就是这么写的，`test_no_unregistered_stale_recomputable_paths` **4 failed**；改全路径后绿）。

### 通用三件套（与上表叠加，不是替代）

| 场景 | 命令 |
|---|---|
| 任何改动 | `./verify-all.sh gate`（拿机器级重活锁；同参数跑 CI 规则） |

## 写新判据时的两个**环境陷阱**（2026-10-02 各实测栽过一次）

> 两条都只在「**在射程内新增判据 / 改用例面**」时踩到，且都是**本地绿、CI 红**——本仓的经典假绿形态。
> 为什么写在这一页：主表指引你去跑这些判据；**而"照着跑"之前，你得先知道它们跑在什么环境里**。

### 陷阱 1 · 在 `tests/unit_ci_workflows/**` 新增判据，**不得依赖 ai-agent 运行时依赖**

CI 的 `ci workflow helper unit tests` 这个 job **只装 `pytest` + `pyyaml`**（不装 `pydantic` / `langchain_core` / `fastapi`）。
新判据若在**模块层** `import app.*` ⇒ **CI 直接红**（实测 6 failed：`ModuleNotFoundError: No module named 'pydantic'` / `'langchain_core'`），
而你在本地用主工作区 venv 跑是**全绿**的。

- ✅ **正确修法**：把这些判据写成**静态的**（AST 反解类属性 / 扫源码文本 / 两边源码对照），
  照 `tests/unit_ci_workflows/test_agent_permission_parity.py` 里"重解析调用点"的既有机具；
  **需要真 import 的行为级判据** ⇒ 放 `backend/ai-agent-service/tests/`（那里有依赖，且本来就跑）。
- 🔴 **禁止** `try/except ImportError: pytest.skip(...)` —— 该判据在 CI 里**永远是空的**（"绿了但没跑"，见 `migao-dev-flow` §2.1）。
- **怎么自证「无依赖也绿」**（实测可用的造法）：毒化 `PYTHONPATH`
  （放 `pydantic.py` / `langchain_core.py` / `app/__init__.py` 三个 `raise ImportError` 的模块）
  \+ `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，再跑该文件。

### 陷阱 2 · **生成物新鲜度判据跑在「`head + main` 合并态」**

`Case Contract (truths_ref)` 的新鲜度腿判的是**合并态**，不是你的分支态：
main 在你的 merge-base 之后进了新用例 ⇒ **你分支上"自己新鲜"的用例书，在合并态下就是陈旧的**
（实测：`提交版 8987 行 / 现取 8987 行，不同 2 行` ⇒ `verdict=drifted`，CI 红）。

⇒ **改用例面（`casebook` 面）之后，先 `rebase origin/main` + 重渲染，再去依赖"fresh"这个结论**；
**不要**用"我分支上 fresh"推断 CI 会绿。
| 跨模块 / 跨端契约 | `./contract-check.sh` |
| 改 web 页面 | `./check-ui-regression.sh` + 上表 `web` 行的多模态验收 |
| 改 `.github/growth_gate.py`（**本页的宿主**） | `python3 -m pytest tests/unit_ci_workflows -q -n 4`（与 CI job `ci workflow helper unit tests` 同参数） |

## 红证（7 行实测：故意破坏 ⇒ 必红；还原 ⇒ 绿）

方法：在**独立 worktree** 里改一处 → 跑该行命令 → 记读数 → `git checkout --` 还原 → 复跑记绿。
每条都是「**注入式**」证明，命令与读数可复算。

| # | 变更面 | 注入（故意破坏，临时改动、已还原） | 红读数（实测） | 还原后 |
|---|---|---|---|---|
| ① | `tool` | 新建 `backend/ai-agent-service/app/tools/redproof_probe.py` **且**在 `create_default_registry` 里注册它（新增工具的**两处**），但不同步任何登记面 | 矩阵那条命令 **2 failed / 115 passed**：`test_tools_registry.py::TestToolsFacadeCompleteness::test_registry_classes_are_all_exported`（门面漏导出）+ `test_tool_permission_codes.py::…::test_b_side_tools_without_a_catalog_code_are_registered`（`以下 B 端工具既没有权限码、也不在登记表里：['redproof_probe']`）；同一次改动下 `growth_gate` 亦 `❌ BLOCKED（缺 tests/test_tools_redproof_probe.py, tests/test_redproof_probe.py）` | 全部绿 |
| ② | `state` | 把 `AgentState` 的 `pending_interact_skill` 改名（等价于「加字段却没同步初始状态期望」） | `test_graph_state.py` **1 failed / 14 passed**：`AssertionError: Missing field: pending_interact_skill` | 15 passed |
| ③ | `migration` | 往**已登记**的 `V144__add_proactive_status_to_daily_briefings.sql` 追加一行注释（内容指纹变） | 矩阵那条命令 **1 failed / 22 passed**：`test_migration_immutability.py::test_registered_migrations_are_byte_identical` —— `已登记迁移的内容被修改…['V144__add_proactive_status_to_daily_briefings.sql']` | 23 passed |
| ④ | `batch` | 给 `tests/agent_eval/local_runner.py` 加一条未登记的写调用 `await client.post("/api/redproof-probe")` | `test_eval_write_site_dispositions.py` **1 failed / 3 passed**：`新增了未登记的写操作 —— 请回答「这条写操作怎么算成功、失败是否可见」` | 4 passed |
| ⑤ | `eval-fixture` | 往 `_CLEAN_TYPES` 注册一个没有实现分支的新类型 `redproof_probe_restore` | `test_eval_preclean_registry.py` **3 failed / 24 passed**：`注册表里有但没实现分支的 type：['redproof_probe_restore']` + `两张表条数不等：table=15 runner=16` | 27 passed |
| ⑥ | `rbac` | 把 `frontend/admin-web/src/config/menu.ts` 里「售后工单」节点的 `permissionCode: 'after_sales:view'` 改成 `'order:view'` | 矩阵那条命令 **9 failed / 22 passed**（`test_agent_permission_parity.py` 9 条红，含 `权限对账判据未通过`、`前提：当前树判据 12 全绿`） | 31 passed |
| ⑦ | `casebook` | 改 `.github/cases/misc.yml` 的一条 `merge_log` 后**不重渲染** | 重跑 `python3 .github/render_cases.py --cases .github/cases --out-eval tests/agent_eval/eval_cases.py --out-md docs/testing/mibao-verification-cases.md` 后，`git diff --exit-code <两个生成物>` **rc=1**（`mibao-verification-cases.md` 差 1 行） | diff rc=0 |

> ⚠️ **口径提醒（① 行实测得到的教训）**：**只新建工具文件、不注册**时工具面判据**全绿**
> （`registry_tools()` 由 `create_default_registry()` 显式构造 ⇒ 未注册的类不进入判据射程）。
> ⇒ 工具面真正的射程是**「文件 + 注册」两处**；而 `growth_gate` 的**缺测**判定在**只有文件**时就会响。
> 两者互补：缺测门禁管「有没有配套测试」，射程提示管「还有哪些 meta 面要一起跑」。

> ⚠️ **红线**：`eval_cases.py` 与 `docs/testing/mibao-verification-cases.md` 是**生成物**，
> 带 `GENERATED — DO NOT EDIT` 头 —— **禁手改**，一律改 `.github/cases/*.yml` 后重跑
> `python3 .github/render_cases.py --cases .github/cases --out-eval tests/agent_eval/eval_cases.py --out-md docs/testing/mibao-verification-cases.md`。

## 提示形态（`growth_gate` 的「B」半）

命中射程路径时，`growth_gate` 在**控制台 + `$GITHUB_STEP_SUMMARY`** 上追加（PR 评论**不含**）：

```
## ⚠️ 变更射程提示（非阻塞，不计入 blocker）

你的变更射程命中了 2 个面 ⇒ 疑似还欠下面这几张登记面（窄跑看不见，判据都在全量单测里）：
### · `tool` — 工具源码被 6 个 meta 面扫：…
- **工具门面导出 / 注册器契约**
  ```bash
  cd backend/ai-agent-service && … -m pytest tests/test_tools_registry.py -q
  ```
```

🔴 **它不改 `blocker_count` 语义**：提示是**独立段** + `--json` 的新字段 `blast_radius`
（与 `blockers` / `warnings` 零交集）；判据 = `tests/unit_ci_workflows/test_growth_gate_blast_radius.py`
（含注入式反面：射程表清空 ⇒ 提示消失、`blocker_count` 仍为 0）。

## 未覆盖与风险（照实登记）

1. **`<venv>` 要自己建**：新 worktree 里 `backend/ai-agent-service/.venv` 常缺 —— 提示里的命令是
   `<venv>/bin/python`（缺失时渲染成 `python3`），**不保证依赖已装**。这是「命令可复制」的代价，不是假绿。
2. **语义射程判不了**：`blast_radius.py` 只认**路径形态**。改了工具**行为**却没改任何路径、
   或把改动藏在生成物之外的别处 ⇒ 提示不会响，也没有东西会红。
3. **人绕过门禁时不响**：不跑 `growth_gate`（如直接在仓外手工改）⇒ 提示不出现。
4. **`web` 行的多模态验收没有机械入口**：承载体是 Playwright 剧本 + AI 读图判定（`migao-dev-flow` §15.7），
   本条只给「命令/指引」，**不是常驻判据**。
5. **文档镜像靠判据维持**：本页与 `blast_radius.py` 的一致性由
   `tests/unit_ci_workflows/test_blast_radius_registry.py` 双向核（面锚 ↔ 表行 ↔ 具名判据）；
   判据**不跑**那些被引用的测试（否则提示会退化成再跑一遍全量套件）。
