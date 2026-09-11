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
    # customer_product_skill
    "product_search", "product_detail",
    # customer_quote_skill
    "curtain_calc",
    # customer_aftersales_skill
    "aftersale_query", "aftersale_create", "validate_input",
    # customer_knowledge_skill
    "knowledge_search",
    # customer_general_skill（fallback）：product_search / product_detail /
    # customer_order_query / customer_logistics_track / human_handoff / interact
    # —— 均已在上方列出
})

# 评测 runner 侧的「非真实工具」伪期望（不计入工具集校验）
PSEUDO_TOOLS = frozenset({"direct_reply"})

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
    # 店员代客操作：给/帮 第三方 创建订单/建品（C 端顾客只为自己下单）
    re.compile(r"(给|帮|替)[^，,。\s]{1,10}(创建|建|下|生成|做)[^，,。]{0,6}(订单|商品|品)"),
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
    exps = c.get("expectations") if isinstance(c, dict) else getattr(c, "expectations", None)
    out = set()
    for exp in (exps or []):
        if isinstance(exp, dict):
            # dict 形态的 tool 字段本身也可能是 "A or B"（runner 的 OR 分支语义）
            branches = (exp.get("tool") or "").split(" or ")
        elif isinstance(exp, str):
            branches = exp.split(" or ")
        else:
            continue
        for br in branches:
            tool = re.split(r"[\(:\s]", br.strip(), 1)[0]
            if tool and tool not in PSEUDO_TOOLS and TOOL_NAME_RE.match(tool):
                out.add(tool)
    return out


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
