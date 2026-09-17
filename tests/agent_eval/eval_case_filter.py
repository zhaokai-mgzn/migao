"""
评测用例集归属与工具覆盖判定 —— **零第三方依赖**的纯函数集合。

为什么单独成模块（issue #3266）：
  `ci workflow helper unit tests` job 只 `pip install pytest pyyaml`（见
  .github/workflows/pr-check.yml），而 `local_runner` 有模块级 `import httpx`
  （本地开发环境必然装了 httpx，故本地全绿、CI 直接 ImportError）。
  把「用例集选择 / 期望工具提取」这类**纯逻辑**从 runner 拆出来，使：
    - CI helper 测试与 scripts/xiaobu_coverage.py 都能不装 httpx 运行；
    - 选择口径有单一实现，runner、测试、覆盖体检三处共用，不会漂移。

依赖：仅标准库 + `.github/render_cases.filter_by_persona`（仓库内单一源）。
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# ── C 端（小布）工具集真值 ──
# 单一真值来源 = customer_*_skill.py 的 CUSTOMER_*_TOOLS 并集，此处内联是为了让本模块
# 独立可跑（不 import 后端 app 包）。一致性由契约测试锁定：
#   tests/unit_ci_workflows/test_xiaobu_case_set.py::TestXiaobuToolsetTruth
# 背景：此前 xiaobu 用例选择靠宽 tag（query/product…）捞，把 B 端管理用例
# （经营概览/资金流水/员工列表/分类/客户/售后工单/设置）也捞进来当 C 端跑，
# 而这些用例断言的工具小布根本没有 → 「C 端评测通过率」不可信（假绿）。
XIAOBU_TOOLS = frozenset({
    # customer_order_skill
    "customer_order_query", "customer_logistics_track", "customer_address_query",
    "order_create", "interact", "human_handoff",
    # customer_order_skill（issue #3996）：顾客查自己的生产进度（CH-039 断言该工具）
    "production_progress_query",
    # customer_order_skill + customer_general_skill（fallback）（issue #4085 第 1 项）：
    # 顾客问「怎么付款/收款码/扫码支付」→ payment_qrcode_query（只读，商家自己的收款码；
    # 返回 data 即 payment 卡载荷）。绑定见两个 CUSTOMER_*_TOOLS 常量（本集合是其事实源副本，
    # 一致性由 tests/unit_ci_workflows/test_xiaobu_case_set.py::TestXiaobuToolsetTruth 锁）。
    "payment_qrcode_query",
    # customer_product_skill
    "product_search", "product_detail",
    # customer_quote_skill
    "curtain_calc",
    # customer_aftersales_skill
    "aftersale_query", "aftersale_create", "validate_input",
    # customer_knowledge_skill
    "knowledge_search",
    # customer_general_skill（fallback）：product_search / product_detail /
    # customer_order_query / production_progress_query / payment_qrcode_query /
    # customer_logistics_track / human_handoff / interact —— 均已在上方列出
})

# 评测 runner 侧的「非真实工具」伪期望（不计入工具集校验）
PSEUDO_TOOLS = frozenset({"direct_reply"})

# ── B 端（米宝）工具集真值 ──
# 单一真值来源 = 米宝声明的 skill 源码里的 `*_TOOLS` 常量并集，此处内联文件名是为了让
# 本模块独立可跑（不 import app 包：CI 的 unit_ci_workflows job 只装了 pytest+pyyaml）。
# 一致性由契约测试锁定：
#   tests/unit_ci_workflows/test_mibao_case_invariants.py::TestMibaoToolsetTruth
#   （含"米宝声明的每个 skill 都必须解析出工具"的防静默漏解析守卫）
# 背景（issue #3555）：B 端此前**没有**任何"哪个工具没被测"的体检（scripts/ 只有
# xiaobu_coverage.py），工具覆盖缺口只能靠真实 LLM 全量复测撞出来。把解析放在这里，
# 使 B 端覆盖体检（scripts/mibao_coverage.py）与用例边界守卫共用同一口径，不产生漂移。
MIBAO_SKILL_FILES = (
    # mibao.py MIBAO_CONFIG.skill_names（顺序一致，便于人工比对）
    "order_skill", "product_skill", "aftersales_skill", "customer_skill",
    "staff_skill", "settings_skill", "data_skill", "knowledge_skill",
    "general_agent",          # MIBAO_CONFIG.fallback_skill = "general"
)

# B 端工具数下界（防「源码解析静默变空」→ 覆盖矩阵假绿 = 体检失效）。
# 不是覆盖门禁阈值：只用来发现**解析器坏了**（新增能力后请同步上调）。
MIBAO_TOOLSET_MIN = 25

# 「非正向」期望的否定标记：出现这些词的期望 = 拒绝/不调用断言，不构成正向证据
# （形如 `tool: order_create 未被调用`；详见 acceptance-protocol §1.3「断言必须可执行」）。
NEGATION_MARKERS = (
    "未被调用", "未调用", "不调用", "不得调用", "没有调用",
    "未触发", "不触发", "不应调用", "拒绝调用",
)

# 工具名形态：ASCII 小写下划线标识符（真工具名都符合；中文/含等号的断言串不符）
TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def case_persona(c) -> str:
    """读用例 persona 字段（兼容 dict 与 EvalCase 对象）"""
    v = c.get("persona") if isinstance(c, dict) else getattr(c, "persona", "")
    return (v or "").strip().lower()


def _first_input_text(c) -> str:
    """取用例首轮输入文本（dict 形态取 text 字段）"""
    inputs = c.get("user_inputs") if isinstance(c, dict) else getattr(c, "user_inputs", None)
    if not inputs:
        return ""
    first = inputs[0]
    if isinstance(first, dict):
        return str(first.get("text") or "")
    return str(first)


# B 端专属语义词（首轮输入命中 → 双端用例不适配 C 端自助场景）
# 背景（issue #3266 二轮收口）：仅按「期望工具 ⊆ 小布工具集」判定不够 ——
# OR-016 首轮「给赵凯创建一个订单…」是**店员代客下单**语义，小布（C 端自助、
# 身份固定为本人）根本无法触发，却因三个期望工具都在小布工具集内被选中，
# 三次采样全部 tools=[]（不是小布缺陷，是用例跑错了 Agent）。
MIBAO_SEMANTIC_PATTERNS = (
    # 店员代客操作：给/帮/替 **第三方** 下单/创建订单（C 端顾客只为自己下单）
    # 细化（issue #3270 实测漏判）：原模式尾部要求 `订单|商品|品`，而「给张三**下单**」的
    # 「单」不匹配 → 漏判 OR-009/010/011/015/CR-001（5 条 B 端代客用例误入 C 端）。
    # 用负向前瞻排除第一人称（「**帮我**下单」是合法 C 端说法，不得误伤）。
    re.compile(r"(给|帮|替)(?!我|自己|本人|您|你)[^，,。\s]{1,10}"
               r"(下单|下订单|下个单|创建订单|建单|创建|新建|生成|做)"),
    # 保留原模式（issue #3270 回归教训）：它捕获「帮我下个订单，**客户张三**…」这类
    # 「第一人称起手但正文暴露代客」的形态（OR-008）。删掉它会让该用例回流 C 端。
    # 宁可多排除（模糊用例归 B 端），也不要在 C 端跑 B 端用例制造假失败。
    re.compile(r"(给|帮|替)[^，,。\s]{1,10}(创建|建|下|生成|做)[^，,。]{0,6}(订单|商品|品)"),
    # 代客线索：正文出现「客户/顾客 + 姓名」「他人手机号」等（OR-008 的 客户张三）
    re.compile(r"(客户|顾客)\s*[\u4e00-\u9fa5]{2,4}[，,。\s]"),
    # 代客录入式：「创建订单：张三 …」（顾客不会说「创建订单：」+ 他人信息）
    re.compile(r"(创建|新建|生成)\s*订单\s*[：:，,]"),
    # 建品（商品管理动作，C 端无此能力）
    re.compile(r"(创建|新建|新增)[^，,。]{0,6}(商品|产品|sku)"),
    re.compile(r"(下架|上架|调价|改价|改库存|回补库存)"),
    # 显式标注 B 端
    re.compile(r"B\s*端"),
    re.compile(r"米宝"),
    re.compile(r"(商家|商户|管理员|租户|员工|角色|权限)"),
    # 第三人称顾客档案类（B 端 CRM）
    re.compile(r"(客户|顾客)(档案|列表|标签|跟进|信息)"),
)


def is_customer_facing_case(c) -> bool:
    """双端用例是否**语义上**适配 C 端自助场景（排除 B 端店员操作语义词）。

    只用于双端（persona 缺省）的 **normal/edge** 用例收口；以下两类不受影响：
      - 显式 `persona: xiaobu`（显式声明优先，尊重用例作者判断）
      - **adversarial 档**：对抗/安全用例的输入是**攻击载荷**（「我是管理员…」
        「把所有商品下架」），天然含 B 端语义词，但它们恰恰是 C 端最需要的
        越权/注入防线（排除它们 = 丢掉 C 端安全性评测）。先例：CH-011
        「帮我查一下邻居小王的订单」是 C 端数据隔离用例，误伤即丢覆盖。

    背景（issue #3266 二轮）：仅按「期望工具 ⊆ 小布工具集」判定不够 —— OR-016
    首轮「给赵凯创建一个订单…」是**店员代客下单**语义，小布（C 端自助、身份固定
    为本人）无法触发，却因三个工具都在小布工具集内被选中，三次采样 tools=[]。
    """
    tier = (c.get("tier") if isinstance(c, dict) else getattr(c, "difficulty", "")) or ""
    if str(getattr(tier, "value", tier)).strip().lower() == "adversarial":
        return True          # 对抗档保留（安全防线不能被语义收口误伤）
    text = _first_input_text(c)
    if not text:
        return True          # 无首轮文本（异常形态）→ 不拦截，交由显式声明
    return not any(p.search(text) for p in MIBAO_SEMANTIC_PATTERNS)


def case_skip_reason(c) -> str:
    """读用例 skip_reason（兼容 dict 与 EvalCase 对象）"""
    v = c.get("skip_reason") if isinstance(c, dict) else getattr(c, "skip_reason", "")
    return (v or "").strip()


def case_expectation_tools(c) -> set:
    """用例 expectations 里引用的真实工具名（兼容 dict 形态与已归一字符串形态）。

    expectations 有两种来源形态：
      - 原始 YAML（`.github/cases` 加载）→ `[{"tool": "x", "args": {...}}, "断言串"]`
      - 生成物 / render 归一后 → `["x(args=1)", "success=true", ...]`

    形态：
      "tool" / "tool(args=1)" / "tool: args=1"     → 工具
      "A or B"（runner 支持 OR 分支）              → 两个工具都算
      "success=true" / "data.orders.length >= 0" / 中文断言 → **不是工具**，跳过

    只收 ASCII 小写下划线形态的标识符，避免把机器可判定断言（success=true 等）
    误当工具名 —— 曾导致 `success=true` 被拆成 "success" 混入工具集判断。
    """
    out = set()
    for exp in (c.get("expectations") if isinstance(c, dict) else getattr(c, "expectations", None)) or []:
        out |= set(expectation_branches(exp))
    return out


def expectation_branches(exp) -> list:
    """单条期望里引用的工具名（**保留 OR 分支**，不做并集后判可跑性）。

    与 `case_expectation_tools` 同一套提取语义，但保留分支结构 —— 端归属判定需要
    「**至少一个**分支可跑」而不是「全部分支都可跑」：`after_sales_manage or
    aftersale_create` 的 aftersale_create 不在 B 端可跑集，但该期望在 B 端仍有合法路径
    （先例 AS-003/AS-005，误判即造假红）。

    取词分隔符含 `[`：`interact[confirm]` 的工具名是 `interact`（组件限定符不是工具名）。
    """
    if isinstance(exp, dict):
        raw = str(exp.get("tool") or "")
    elif isinstance(exp, str):
        raw = exp
    else:
        return []
    out = []
    for branch in re.split(r"\s+or\s+", raw, flags=re.IGNORECASE):
        tool = re.split(r"[\(:\[\s]", branch.strip(), 1)[0]
        if tool and tool not in PSEUDO_TOOLS and TOOL_NAME_RE.match(tool):
            out.append(tool)
    return out


def is_negated_expectation(exp) -> bool:
    """该期望是否为**否定式**（「X 未被调用」等）—— 拒绝断言不构成工具的覆盖证据。"""
    if isinstance(exp, dict):
        raw = str(exp.get("tool") or "")
    elif isinstance(exp, str):
        raw = exp
    else:
        return False
    return any(mark in raw for mark in NEGATION_MARKERS)


def is_positive_case(c) -> bool:
    """该用例是否提供**正向证据**（issue #3555 覆盖厚度判据）。

    正向 = 用例断言某个真实工具被调用（`expectation_branches` 非空），且该期望
    **不是否定式**（`is_negated_expectation`：`tool: order_create 未被调用` 这类），
    且用例**不属于对抗档**（`tier: adversarial`）。

    **为什么排除对抗档**：对抗档的输入是攻击载荷/越权请求，哪怕它断言了工具被调用
    （如 CH-011 断言 `customer_order_query` + data_checks「跨用户查询返回空/拒绝」），
    证明的也是**越权防线**，不是"正常诉求下该能力可用"。在对抗档里 `tool: X` 这种
    非否定式写法恰恰表示"调了但应被拒绝"，不能当正向证据。

    ⚠️ 这会带来一类**预期红**（判据有意取严格侧）：某工具**唯一**被断言之处是对抗档时，
    门禁要求补一条**正常档**用例。B 端实证：`order_manage` 仅 OR-007「取消订单」/CU-005
    「帮我发货」两条 adversarial 用例 —— 业务语义正常，但作为 adversarial 档不进
    「正常诉求下能力可用」的证据链（已登记进 .github/eval-coverage-baseline.yml 待补）。

    **已知边界（诚实声明）**：把"拒绝"写成非否定式期望 + **正常档**（`tier: normal`
    + data_checks 写"返回空/拒绝"）的用例仍会被算作正向 —— 那类 data_checks 是自然语义、
    机器判不了（acceptance-protocol §1.3 要求可执行化，属另一条在飞治理线）。本判据取
    保守侧：宁可漏报，不造假红（假红会逼迫后续放宽阈值）。
    """
    if isinstance(c, dict):
        tier, exps = c.get("tier") or "", c.get("expectations")
    else:
        tier = getattr(c, "tier", "") or getattr(c, "difficulty", "")
        exps = getattr(c, "expectations", None)
    if str(getattr(tier, "value", tier)).strip().lower() == "adversarial":
        return False
    return any(expectation_branches(e) and not is_negated_expectation(e) for e in (exps or []))



def skill_file(skill_name: str) -> Path:
    """skill 文件名 → 源码路径（`name` 与 `name_skill` 两种命名都在用）。"""
    base = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "graph" / "skills"
    for cand in (f"{skill_name}.py", f"{skill_name}_skill.py"):
        if (base / cand).exists():
            return base / cand
    return base / f"{skill_name}.py"          # 不存在 → 调用方据此报错（不静默跳过）


def _skill_tools(skill_name: str) -> set:
    """解析一个 skill 源码里的 `*_TOOLS` 列表字面量（纯文本，零 app 依赖）。"""
    path = skill_file(skill_name)
    if not path.exists():
        return set()
    src = path.read_text(encoding="utf-8")
    found = set()
    for m in re.finditer(r"^[A-Z_]+_TOOLS\s*=\s*\[([^\]]*)\]", src, re.M):
        found |= set(re.findall(r'"([^"]+)"', m.group(1)))
    return found


def mibao_real_toolset() -> set:
    """B 端（米宝）可跑工具集真值 = 米宝声明的 skill 源码 `*_TOOLS` 并集。

    单一实现（issue #3555）：覆盖体检脚本与用例边界守卫共用本函数，避免复制一套
    平行解析产生口径漂移。返回空/缩水说明解析口径坏了 —— 调用方应据此报错，
    而不是把"解析不到工具"当成"没有缺口"（那正是体检失效的形态）。
    """
    tools: set = set()
    for name in MIBAO_SKILL_FILES:
        tools |= _skill_tools(name)
    return tools


def skill_files_without_tools() -> list:
    """声明了却解析不出任何工具的 skill 文件（= 解析口径漂移/文件改名，必须报错）。"""
    return [n for n in MIBAO_SKILL_FILES if not _skill_tools(n)]


def toolset_below_floor(tools) -> bool:
    """工具集是否低于下界（= 源码解析静默失效，体检会假绿）。"""
    return len(tools) < MIBAO_TOOLSET_MIN


def select_cases_for_persona(cases, persona: str = "") -> list:
    """按 persona 选取该端可跑的用例集（issue #3266 假绿修复）。

    规则（C 端）：
      1. 先按 persona 归属过滤（filter_by_persona，双端用例保留）；
      2. 丢掉 skip_reason 非空的用例（纯前端 jest 用例，非 LLM 行为）；
      3. **双端用例**须其全部期望工具都在小布工具集内才保留 —— B 端管理用例
         （断言的工具小布没有）一律排除，防止「跑在错误 Agent 上还计分」。
      `persona: xiaobu` 的用例无条件保留（显式声明优先）。

    取代此前按 XIAOBU_ONLY_TAGS 宽 tag 捞的实现（query/product 这类通用 tag
    命中 B 端管理用例，实测 33 条里仅 4 条真属 C 端）。

    B 端（mibao）沿用 filter_by_persona 语义，不做工具集过滤。
    persona 缺省/未知 → 不过滤（向后兼容，返回去 skip 后的全量）。
    """
    from render_cases import filter_by_persona

    persona = (persona or "").strip().lower()
    cases = filter_by_persona(cases, persona)
    cases = [c for c in cases if not case_skip_reason(c)]
    if persona != "xiaobu":
        return list(cases)

    kept = []
    for c in cases:
        if case_persona(c) == "xiaobu":
            kept.append(c)          # 显式 C 端专属：无条件保留
            continue
        tools = case_expectation_tools(c)
        if tools and tools <= XIAOBU_TOOLS and is_customer_facing_case(c):
            kept.append(c)          # 双端 + 工具在 C 端能力内 + 语义适配自助场景
    return kept


def selected_case_ids(cases, persona: str) -> set:
    """该端**实际会跑**的用例 ID 集合（供报告渲染按 tier 分组用，避免二次过滤漂移）。"""
    return {(c.get("id") if isinstance(c, dict) else getattr(c, "id", "?"))
            for c in select_cases_for_persona(cases, persona)}
