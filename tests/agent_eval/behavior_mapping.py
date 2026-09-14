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
- 完全没有 AI 行为文件 → 返回 `[]`（非行为改动不该烧真实 LLM token）。

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

# ── 改动类型 → 必跑用例（逐条对应 migao-dev-flow §13.2 映射表；按声明顺序匹配，可命中多条）──
# 为什么是「文件名/路径」而不是「语义」：CI 里只能拿到 `git diff --name-only`，
# 没有 AST、也不该猜语义 —— 正则覆盖 §13.2 里列出的改动承载文件即可，
# 过细则漏（改 skills/ 别名也要跑），过宽则烧 token。
MAPPING_RULES = [
    # 下单引导 / 加工项询问 / 金额计算 → OR-016
    # （order_skill.py 是 Skill 本体，order_create/order_query 是下单与查单两个 Tool）
    (r"app/graph/skills/order_skill\.py|app/tools/order_create\.py|app/tools/order_query\.py",
     ["OR-016"]),
    # 换货 / 售后工单引导 → AS-007
    (r"aftersales|after_sales", ["AS-007"]),
    # 建品（属性 / 加工项价格 / 参数完整性）→ PR-019、PR-020
    (r"product_skill|product_manage|processing_item", ["PR-019", "PR-020"]),
    # 交互卡渲染 / 前端 → CH-010、CH-019
    (r"interact\.py|interactive|card", ["CH-010", "CH-019"]),
    # 图片 / 视觉链路 → CH-021、CH-026
    (r"vision|image|图片", ["CH-021", "CH-026"]),
    # 防御 / Prompt 注入 / 边界 → DF-011、DF-012
    (r"guard|defense|injection|inject", ["DF-011", "DF-012"]),
    # agent 声明 / prompt（澄清、多轮、转人工口径）→ CH-003、CH-022
    (r"app/agents/|prompt", ["CH-003", "CH-022"]),
]

# 无规则命中时的默认集（§13.2 的四个核心域各取一条）。
# 为什么给默认集而不是"不跑"：AI 行为文件（如 app/main.py、app/graph/graph.py）改了
# 却匹配不到任何规则，说明**映射表本身没覆盖到**，此时静默跳过 = 把漏测伪装成"无需测试"。
# 跑一组核心域用例至少能证明主链路没被改崩（覆盖面窄，但比零信号强）。
DEFAULT_BEHAVIOR_CASES = ["CH-010", "OR-016", "PR-019", "AS-007"]


def is_ai_behavior_file(path: str) -> bool:
    """路径是否属于 AI 行为域（决定"要不要触发评测"，见模块 docstring 契约）。"""
    return path.startswith(AI_BEHAVIOR_PATH_PREFIXES)


def map_changed_files_to_case_ids(paths: list) -> list:
    """变更文件路径列表 → 该跑的评测用例 ID 列表（去重 + 字典序稳定排序）。

    Args:
        paths: `git diff --name-only` 的输出行（仓根相对路径，如
            `backend/ai-agent-service/app/graph/skills/order_skill.py`）。
            空串/纯空白项被忽略（diff 输出常带尾随空行）。

    Returns:
        用例 ID 列表；稳定排序保证同一 diff 在任何机器/任何次数下结果一致
        （workflow 的 `case_ids` 输出与 PR 评论要可比对，不能随机序）。
        没有任何 AI 行为文件改动 → `[]`；有但无规则命中 → `DEFAULT_BEHAVIOR_CASES`。

    注意：规则对所有输入路径匹配，AI 行为文件的**存在与否**只决定
    "默认集 / 空" 这条分支 —— 即非 AI 行为路径（如纯前端样式）不会单独触发评测。
    """
    changed = [p.strip() for p in paths if p and p.strip()]

    if not any(is_ai_behavior_file(p) for p in changed):
        return []  # 非行为改动：不触发评测（省真实 LLM 成本）

    matched: set = set()
    for pattern, case_ids in MAPPING_RULES:
        rx = re.compile(pattern)
        if any(rx.search(p) for p in changed):
            matched.update(case_ids)  # 并集：一个文件可能同时命中多条规则

    if not matched:
        return list(DEFAULT_BEHAVIOR_CASES)

    return sorted(matched)
