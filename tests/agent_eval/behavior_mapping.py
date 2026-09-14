"""行为改动 diff → 评测用例映射（issue #3502：把 migao-dev-flow §13.2 映射表落成可执行代码）。

## 为什么要 diff 驱动

`migao-dev-flow` §13.2 早就规定了「改动类型 → 必跑用例」的映射表（改下单引导/加工项 →
OR-016、改售后 → AS-007、改建品 → PR-019/PR-020、改交互卡 → CH-010/CH-019…），
但落地方式一直是**人工**：靠人（或 agent）记得读完 diff 再手敲
`local_runner.py case <ID>`。两个事实让它不可靠：

1. **漏跑没有信号**：§13 是铁律，却没有任何机制检查它跑没跑 —— 漏了不会有红灯，
   只有等下一轮验收/线上问题才暴露；
2. **PR 门禁太窄**：PR 上的 Agent Eval 只有 smoke 档 7 条（跨域抽样，回答的是"没崩"），
   改一行 `order_skill.py` 时可能一条订单用例都没跑到 → 行为回归要到合并之后才发现。

所以把那张表写成**纯函数**：输入 PR 的变更文件列表，输出该跑的用例 ID。
`.github/workflows/agent-behavior-eval.yml` 用它自动选用例（改哪测哪），
口径仍来自 §13.2，不新造标准。

## 契约

- `map_changed_files_to_case_ids(paths)` → 去重、按用例 ID 字典序稳定排序的列表；
- 命中多条规则取**并集**（同一文件既可能是 agent prompt 又是订单 skill）；
- 存在 AI 行为文件（`backend/ai-agent-service/app/`、`tests/agent_eval/`、`.github/cases/`）
  但无任何规则命中 → 返回 `DEFAULT_BEHAVIOR_CASES`（宁多跑几条，不漏跑）；
- 完全没有 AI 行为文件 → 返回 `[]`（非行为改动不该烧真实 LLM token）；
- **规则只锚定 agent 本体源码**（`BEHAVIOR_SOURCE_PREFIXES`）：用例/测试/文档路径
  （`tests/**`、`.github/cases/**`）永不进规则桶（阻塞），只能落兜底网（#3551 假阻塞修复）。

零第三方依赖是硬要求：workflow 的 map job 只装系统 python3（不 pip install），
单测也要秒级跑完（§16.1 的 L0 静态层）。
"""
import re

# ── AI 行为域（只有这些路径的改动才可能触发行为评测）──
# 与 workflow 的 `on.pull_request.paths` 保持一致：三处是同一口径的两种表达
# （workflow 用它做触发器过滤，这里用它决定"要不要跑/跑默认集"）。
AI_BEHAVIOR_PATH_PREFIXES = (
    "backend/ai-agent-service/app/",   # agent 本体：skills / tools / prompt / 交互卡
    "tests/agent_eval/",               # 评测基建（改了它，评测口径本身就需要复验）
    ".github/cases/",                  # 用例单一源（改用例 → 用例本身要真跑一遍）
)

# ── 规则作用域（#3551：规则只能锚定这些路径 = agent 本体源码）──
# 只有本体源码的改动才可能与用例有**因果**；用例/测试/文档路径一律走兜底网（不阻塞）。
# 详见 MAPPING_RULES 上方的「统一约定」注释与 TestRulesAnchorToSourcePaths。
BEHAVIOR_SOURCE_PREFIXES = (
    "backend/ai-agent-service/app/",
)

# ── 改动类型 → 必跑用例（逐条对应 migao-dev-flow §13.2 映射表；按声明顺序匹配，可命中多条）──
# 为什么是「文件名/路径」而不是「语义」：CI 里只能拿到 `git diff --name-only`，
# 没有 AST、也不该猜语义 —— 正则覆盖 §13.2 里列出的改动承载文件即可，
# 过细则漏（改 skills/ 别名也要跑），过宽则烧 token。
#
# ⚠️ 统一约定（#3551 追加，2026-09-14 实证的假阻塞红）：
#   **规则只锚定 agent 本体源码**（`BEHAVIOR_SOURCE_PREFIXES` 内的路径），
#   绝不允许匹配 `tests/**`、`.github/cases/**`、`docs/**` 等用例/测试/文档路径。
#   为什么：规则命中 = 阻塞型门禁，前提是「改动真的影响行为」；而按关键词匹配路径时，
#   一个**测试文件名**就能触发规则 —— 实证：新建 `tests/test_admin_api_client_kwargs_guard.py`
#   （文件名含 `guard`）让改 finance 工具的 PR 被判成"命中防御规则" → DF-011/DF-012 以阻塞强度
#   跑，与本 PR 改动无因果 → **假阻塞红**（每次都要人/agent 花时间证伪，还会诱使去修不该修的东西）。
#   假阻塞比没有门禁更糟（§16.5：规则桶阻塞的设计前提就是因果性）。
#   过滤在 `map_changed_files_with_source` 里**集中实现**（不是靠每条正则自觉）——
#   这样将来新增规则也不可能误触用例/测试路径。不变量测试见
#   `backend/ai-agent-service/tests/test_behavior_mapping.py::TestRulesAnchorToSourcePaths`。
MAPPING_RULES = [
    # 下单引导 / 加工项询问 / 金额计算 → OR-016、OR-028
    # （order_skill.py 是 Skill 本体，order_create/order_query 是下单与查单两个 Tool）
    # OR-028（#3666）：数量语义放宽为 DECIMAL(10,2) 的端到端金额回归网 ——
    #   改 order_create 的数量 schema（integer→number）必须真跑一次，否则"小数保真"只靠单测证明。
    (r"app/graph/skills/order_skill\.py|app/tools/order_create\.py|app/tools/order_query\.py",
     ["OR-016", "OR-028"]),
    # 换货 / 售后工单引导 → AS-007
    (r"aftersales|after_sales", ["AS-007"]),
    # 建品（属性 / 加工项价格 / 参数完整性）→ PR-019、PR-020
    # ⚠️ 关键词收窄（#3624）：原为 `processing_item`（裸词），把**加工项目录**的
    # `app/tools/processing_item_manage.py` / `processing_item_query.py` 一并吞进商品域
    # → 改加工项写路径推出的却是 PR-019/PR-020（断言 `product_manage(action=create)`，
    # 与目录 CRUD 无因果），而加工项目录自己的 PP-* 用例一条没跑（#3591 收口实测）。
    # 现在只锚「商品侧」加工项载体：product_processing_item_manage（商品挂载/摘除加工项）。
    # （另一载体 `app/tools/processing_items.py` 已在 #3588 随 schema 对齐清理删除，
    #   规则不再保留指向已删文件的死锚点。）
    (r"product_skill|product_manage|product_processing_item_manage",
     ["PR-019", "PR-020"]),
    # 交互卡渲染 / 前端 → CH-010、CH-019
    (r"interact\.py|interactive|card", ["CH-010", "CH-019"]),
    # 图片 / 视觉链路 → CH-021、CH-026
    (r"vision|image|图片", ["CH-021", "CH-026"]),
    # 防御 / 熔断降级 / 边界 → DF-011、DF-012
    # 两类载体都列出：① 真实承载防御逻辑的源码（否则该规则近乎空转 —— 实测全仓仅
    # `app/graph/clarify_guard.py` 命中，而熔断/降级所在的 `app/core/*` 反而落进兜底网 = 不阻塞，
    # 真信号比假阳性还弱）；② 历史关键词（guard/defense/injection）保留，防将来这些文件落地时漏掉。
    (r"clarify_guard\.py|circuit_breaker\.py|app/core/fallback\.py"
     r"|app/graph/skills/base_skill\.py|guard\.py|defense|injection|inject",
     ["DF-011", "DF-012"]),
    # agent 声明 / prompt（澄清、多轮、转人工口径）→ CH-003、CH-022
    (r"app/agents/|prompt", ["CH-003", "CH-022"]),
    # 客户档案（更新档案 / 标签 / 客户域引导词）→ CU-003、CU-004
    # §13.2 映射表原**缺客户域**（#3551 补齐）：改 `customer_manage.py` 写路径不映射任何用例 =
    # 客户域行为改动逃过映射门禁（旁路发现，与"姓名静默丢弃"同一轮修复）。
    # 承载文件 = 客户档案 Tool 本体 + 客户域 Skill/prompt/示例（相对 app/ 的路径）。
    (r"customer_(manage|skill|general_skill)|prompts/customer\.md|SKILL-customer|EXAMPLES-customer",
     ["CU-003", "CU-004"]),
    # 人事（员工 / 角色）Skill 本体 → HR-001（员工列表 → employee_manage(list)）、
    # HR-005（建角色 + 分配权限 → role_manage(create) + **确认卡轮**）—— #3624 补齐。
    # 为什么现在必须补：#3577（产品裁定「交互形态统一」）刚给 staff 绑上 `interact`
    # （写操作 confirm 卡），交互形态变了；此前改这个文件**零 HR 用例**（落兜底网 = 只报告）。
    # 为什么是这两条（读过用例真实内容）：HR-001 覆盖 employee_manage 绑定，HR-005 覆盖
    # role_manage 绑定 + validate→confirm→execute 的确认链。刻意**不**含 HR-002/HR-003
    # （employee_manage 写路径）：本地 flake 台账里它们是 `reproducible` 红（非波动），
    # 放进强信号集 = 每个改 staff 的 PR 恒红且与本 PR 无因果（假阻塞）。
    (r"app/graph/skills/staff_skill\.py", ["HR-001", "HR-005"]),
    # 系统配置（设置 / 站内通知）Skill 本体 → ST-003（改密码 → settings_manage(change_password)
    # + 确认）、ST-005（标已读 → notification_manage(mark_read)）—— #3624 补齐。
    # 两条分别覆盖该 skill 的两个需确认写工具（settings_manage / notification_manage），
    # 也就是 #3577 补绑 interact 后最需要真信号的两条写路径。
    (r"app/graph/skills/settings_skill\.py", ["ST-003", "ST-005"]),
    # 数据分析（看板 / 财务 / 会话）Skill 本体 → DA-004（会话监控 → session_manage(monitor)）、
    # FN-001（登记线下收款 → finance_api(create_transaction) + 确认）—— #3624 补齐。
    # 同样按「需确认写工具」挑：data 绑的写工具是 finance_api / session_manage，各取一条；
    # 不取 DA-001~DA-003（dashboard_stats 只读，改 skill 绑定与否不由它们判定）
    # 也不取 FN-004（台账里 `reproducible` 红，同 HR-002/HR-003 的理由）。
    (r"app/graph/skills/data_skill\.py", ["DA-004", "FN-001"]),
    # 加工项目录（PP-*）→ PP-002（分类/目录查询，期望 `processing_item_query or
    # processing_item_manage`）、PP-006（计价方式 + 新增加工项，期望
    # `processing_item_query(keyword=打孔)` + `processing_item_manage(action=create_processing_item)`
    # + 确认轮）—— #3624 补齐。这是**目录 CRUD** 与商品侧挂载（PR-019/PR-020）的分界。
    # 台账提示 PP-002/PP-006 历史上 `reproducible` 红（多为 #3555/#3591 旧契约缺陷余波），
    # 已按 §14.2 记入归因队列；本门禁现为「报告制」，不会阻塞合并。
    (r"app/tools/processing_item_manage\.py|app/tools/processing_item_query\.py",
     ["PP-002", "PP-006"]),
    # 加工单生成（PG-*）→ PG-013（「最近有没有已确认、需要加工的订单？」→ 生成加工单 + 确认轮）
    # —— #3624 补齐。PG-001~PG-012/PG-014 全部 skip（Java 单测验证），PG-013/PG-015/PG-016
    # 是该域唯三可跑的 LLM 用例，数据前置见 `tests/agent_eval/fixtures/mibao_eval_seed.sql`
    # （EVAL-MB-ORD-0002，confirmed + 带加工项）。
    (r"app/tools/processing_order_generate\.py", ["PG-013"]),
    # 加工单查询（PG-*）→ PG-015（生成 → 按订单号回查状态）—— #3658 补锚。
    # 前提变化：PG-015 随 #3568/#3589 落地（此前 query 零可跑用例，锚了 = 挂不相关
    # 用例 = 假阻塞；「刻意不锚」注释与不变量测试随本批同步反转/更新）。
    (r"app/tools/processing_order_query\.py", ["PG-015"]),
    # 加工单状态流转（PG-*）→ PG-016（完成加工，output_verify 核到 completed）
    # —— #3658 补锚，理由同 query。
    (r"app/tools/processing_order_update\.py", ["PG-016"]),
    # 商品侧加工项挂载 Tool（product_processing_item_manage）→ PP-001/PP-003 —— #3658 补充。
    # 覆盖核查结论：PP-001（normal，期望 `product_processing_item_manage(action=add)` +
    # `processing_item_query`）、PP-003（adversarial，confirm 卡 + action=add）**直接行使本工具**；
    # 此前只经商品规则（下方）锚到 PR-019/PR-020（`product_manage(action=create)` 建品价格，
    # 与本文件无因果）→ 并集：商品域保留，另补本工具的直测用例（改挂载路径必须真跑它们）。
    (r"app/tools/product_processing_item_manage\.py", ["PP-001", "PP-003"]),
    # 守卫代码的共享载体 `base_skill.py` → 转人工族 CH-013/CH-014/CH-015 —— #3624 追加。
    # 为什么：base_skill 的守卫判据（不满情绪→建议 interact 卡→用户确认后转人工；
    # 用户拒绝后本会话不再自动建议；显式「转人工」不经建议卡直接转）正是这三条用例的
    # 行为面，而此前改它只命中防御规则 DF-011/DF-012（幂等重试 #3564 收口实测）。
    # 与防御规则是**并集**（同一个文件两类守卫），不是替代。
    # ⚠️ 明确**不含** OR-016：该用例当前自相矛盾（`user_inputs[1]` 裸文本 vs `order_before`
    # 时序断言，另一包校准中），挂上去会让每个改 base_skill.py 的 PR 吃到规则命中红
    # （仓库级红，与 #3551 的 DF-011 假阻塞同型）—— 待校准合入后再补。
    (r"app/graph/skills/base_skill\.py", ["CH-013", "CH-014", "CH-015"]),
    # 转人工 Tool 本体 `human_handoff.py` → CH-008（建人工会话，客服工作台可见）/ CH-015
    # （显式「转人工」不经建议卡直接转）—— #3624 追加（写工具确认门禁包 #3606 交回）。
    # 为什么必须补：改这个文件此前落兜底网，而它"看起来命中规则"其实只是**测试文件名**
    # `*_confirm_guard.py` 撞上防御关键词 `guard` 的误报面（#3551 已集中过滤掉），
    # 真正该跑的转人工用例一条没跑。与 `base_skill.py` 的转人工族是**并集**：
    # 入口不同（Tool 本体 vs 守卫判据），故 CH-015 会同时被两条规则锚定（去重后只跑一次）。
    (r"app/tools/human_handoff\.py", ["CH-008", "CH-015"]),
]

# 无规则命中时的默认集（兜底网）：§13.2 各核心域的代表用例 + 曾**不可达**的关键用例。
# 为什么给默认集而不是"不跑"：AI 行为文件（如 app/main.py、app/graph/graph.py）改了
# 却匹配不到任何规则，说明**映射表本身没覆盖到**，此时静默跳过 = 把漏测伪装成"无需测试"。
# 跑一组核心域用例至少能证明主链路没被改崩（覆盖面窄，但比零信号强）。
#
# ⚠️ 口径（issue #3725 补记）：**兜底网成员必须"可达"** —— 既在映射结果里（否则无论改什么
# 文件都选不中 = 结构性不可达），又能被 `select_cases_for_persona` 在至少一个 persona 下
# 选得中、且 `skip_reason` 为空（否则会进 workflow 的 unrunnable = 在网里也不会执行）。
# 这条不变式由 `tests/unit_ci_workflows/test_behavior_gate_reachability.py` 锁定
# （关键用例登记表 + 真实入口见证 + 注入式红证），别再让射程被无声缩小。
#
# ── 本次补充（issue #3725）：三条**修前不可达**的用例 ──
# 修前实测（origin/main @41c9a83a）：OR-015/OR-017/AS-003 **既不在 MAPPING_RULES、
# 也不在本默认集** ⇒ 无论改什么文件，门禁都选不中它们。实证危害：PR #3718（修 OR-015
# "模块越界拒绝"）的真实 LLM 迭代档选中的是 CH-003/CH-013/CH-014/CH-015/DF-011/DF-012
# —— **修 OR-015 的 PR，自己的门禁没跑 OR-015**，作者只能另写纯函数探针自证。
# 补充理由（逐条有据）：
#   · OR-015（mibao）：run 34841029062 的结论档 `completion.deterministic_failures` 含
#     `OR-015` —— 能红、且红的是真行为缺陷（高价值信号）；
#   · AS-003（双端）：同一次结论档的 `deterministic_failures` = `['AS-003','CR-001',
#     'OR-008','OR-015','PG-016','PP-007']`；
#   · OR-017（xiaobu）：OR-015/OR-016「加工项闭环」的 **C 端对位用例**（§13.2 订单域）；
#     全量 xiaobu 腿通过 ⇒ 未观测到失败，入选理由是消掉"结构性不可达"、保住 C 端对位信号。
# **只补兜底网（只报告、不阻塞）**：给 `app/graph/nodes.py` 之类路由层加**阻塞型**规则桶
# 是另一件事（须先校准稳定性）——`:55-62` 记录的 #3551「规则过宽 ⇒ 假阻塞红」教训仍在，
# 故本 PR 刻意不动规则桶（红线见测试 `TestLayeringUnchanged`）。
# 成本：命中兜底网的 PR 从 4 条 → 7 条，按 persona 分桶后实为 **mibao +2 / xiaobu +1**
# （AS-003/OR-015 归 mibao，OR-017 归 xiaobu；见 PR body 的触发频率实测）。
# 顺序：字典序（与 `map_changed_files_to_case_ids` 的"去重 + 字典序稳定排序"契约一致，
# 让 workflow 的 `case_ids` 输出可跨机器比对）。
DEFAULT_BEHAVIOR_CASES = ["AS-003", "AS-007", "CH-010", "OR-015", "OR-016", "OR-017", "PR-019"]


def is_ai_behavior_file(path: str) -> bool:
    """路径是否属于 AI 行为域（决定"要不要触发评测"，见模块 docstring 契约）。"""
    return path.startswith(AI_BEHAVIOR_PATH_PREFIXES)


def map_changed_files_to_case_ids(paths: list) -> list:
    """变更文件路径列表 → 该跑的评测用例 ID 列表（去重 + 字典序稳定排序）。

    等价于 `map_changed_files_with_source(paths)[0]`（用例集口径只有一份实现，
    见该函数）。需要知道结果**来自规则命中还是兜底网**时用那个。

    Args:
        paths: `git diff --name-only` 的输出行（仓根相对路径，如
            `backend/ai-agent-service/app/graph/skills/order_skill.py`）。
            空串/纯空白项被忽略（diff 输出常带尾随空行）。

    Returns:
        用例 ID 列表；稳定排序保证同一 diff 在任何机器/任何次数下结果一致
        （workflow 的 `case_ids` 输出与 PR 评论要可比对，不能随机序）。
        没有任何 AI 行为文件改动 → `[]`；有但无规则命中 → `DEFAULT_BEHAVIOR_CASES`。

    注意：规则**只对本体的源码路径（`BEHAVIOR_SOURCE_PREFIXES`）匹配**；
    AI 行为文件的**存在与否**只决定 "默认集 / 空" 这条分支 —— 非 AI 行为路径（如纯前端样式）
    不会单独触发评测；用例/测试/文档路径（`tests/**`、`.github/cases/**`）永不命中规则桶，
    只能落兜底网（#3551：否则一个测试文件名就能造出与改动无因果的**假阻塞红**）。
    """
    return map_changed_files_with_source(paths)[0]


def map_changed_files_with_source(paths: list) -> tuple:
    """同 `map_changed_files_to_case_ids`，但额外给出结果**来源**（门禁分层用）。

    Returns:
        `(case_ids, source)`，`source` ∈：
          - `"rules"`：命中 MAPPING_RULES —— 改动确实落在该行为域，失败是**真信号**；
          - `"default_net"`：无规则命中、走 `DEFAULT_BEHAVIOR_CASES` 兜底网；
          - `"none"`：没有 AI 行为文件改动（不触发评测）。

    ★ 为什么要区分来源（issue #3502 门禁分层，2026-09-14 dogfooding 首跑实证）：
      规则命中的用例与"本 PR 改了什么"有**因果**（改 order_skill.py → OR-016 红 = 真回归），
      失败必须拦合并；而兜底网是"映射表没覆盖到"时的**网**，与本 PR 改动**无因果** ——
      实证：只改 `tests/agent_eval/behavior_mapping.py`（评测基建）就被兜底网里的
      CH-010（小布下单表单化交互）判红，属无因果阻塞。故 workflow 对两者分层：
      `rules` → 阻塞；`default_net` → 只报告（PR 评论显式标注）。
      兜底网本身**不取消**：无规则命中时静默跳过才是更坏的选择（把漏测伪装成"无需测试"）。
    """
    changed = [p.strip() for p in paths if p and p.strip()]

    if not any(is_ai_behavior_file(p) for p in changed):
        return [], "none"  # 非行为改动：不触发评测（省真实 LLM 成本）

    # ★ 规则作用域：只有 agent 本体源码才可能"与本 PR 改动有因果"。
    #   用例/测试/文档路径（tests/**、.github/cases/**）在此被排除 → 永远不会进规则桶（阻塞），
    #   只能落兜底网（不阻塞）。#3551 实证：测试文件名含 `guard` 曾让 DF-011/DF-012 假阻塞。
    rule_scope = [p for p in changed if p.startswith(BEHAVIOR_SOURCE_PREFIXES)]

    matched: set = set()
    for pattern, case_ids in MAPPING_RULES:
        rx = re.compile(pattern)
        if any(rx.search(p) for p in rule_scope):
            matched.update(case_ids)  # 并集：一个文件可能同时命中多条规则

    if not matched:
        return list(DEFAULT_BEHAVIOR_CASES), "default_net"

    return sorted(matched), "rules"
