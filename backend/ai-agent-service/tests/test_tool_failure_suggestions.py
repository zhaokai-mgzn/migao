# case_ids: CH-001, DF-011, DF-012
"""工具失败面必须带 `suggestion` — 常驻 L0 静态守卫（issue #4050，母单 #4043 的 T1 条）。

## 病灶形状（R5 明令禁止的「静默失效」形态）

`app/tools/base.py` 的 `ToolResult.suggestion` 被 docstring 写成硬要求
（「失败时必须填写，告诉 LLM 如何引导用户修复问题」），真值登记在
`.github/templates/ai-chat.yml` 的 `ai-chat.suggestion-on-fail`：

    [ai-chat.suggestion-on-fail] 工具失败必须返回 suggestion 字段（告诉 LLM 如何引导用户修复）

但**没有任何检查**。而 `app/graph/skills/base_skill.py` 的自愈闸门是
`_self_correct_retry()` 的**第二行**：

    suggestion = result_dict.get("suggestion", "")
    if not suggestion:
        return None            # ← 缺口在这里静默短路

`_execute_tool_safe` 早已把 `suggestion` 带进出口
（`"suggestion": getattr(result, "suggestion", None) or ""`）⇒ 缺口**全在工具侧**。
近一半失败面因此**永远进不了自愈路径**：工具失败 → suggestion 为空 → 不重试 →
把失败直接甩给模型（模型只能凭 error 文案猜下一步）。

**AST 精确口径**（`app/tools/*.py`，复算命令见本仓库 issue #4050）：
`ToolResult(success=False, …)` 字面量调用点 = **396**，
其中带非空 `suggestion=` 的 = **203**、缺口 = **193（48%）**、涉及 **31 个文件**。
（口径：只算 `success` 为**字面量 `False`** 的调用；`success=some_bool` 这类运行时取值
不计入 —— 它们不构成静态可判的缺口，登记在「不适用域」而非基线里。）

## 本文件锁的三条不变式（每条都有反例输入）

1. `test_every_failure_site_declares_a_suggestion` —— **存量缺口必须为空**
   （`.github/tool-suggestion-baseline.json` 只许缩短；本 PR 落地时基线**为空**）。
2. `TestThresholdGrowthIsRefused` —— **基线只许缩短**：新增违规必须报出，
   缩短必须放行（防「新写的失败点没给建议」被基线静默吸收 = R4 禁止新增豁免）。
3. `TestSuggestionDetectorIsNotVacuous` —— **判据自身可红 + 不恒真**（落盘夹具注入）：
   往临时目录写一个缺 `suggestion` 的 `ToolResult(success=False, …)` ⇒ 判据**必报**；
   补上 `suggestion=` ⇒ 判据**必不报**。这是本仓既有范式
   （见 `tests/test_contract_wiring.py::TestFieldCrossingDetectorIsNotVacuous`）。

## 不适用域（R1 要求声明适用域 + 负例，此处一并给出）

- **`success` 非字面量**（`success=ok` / `success=result.ok`）：静态不可判，不计入
  也不报红 —— 由 L2 单测在运行期断言（先例：`tests/test_piecework_query.py`、
  `tests/test_customer_manage.py` 已对各自工具断言 `result.suggestion` 非空）。
- **`suggestion` 是变量**（`suggestion=suggestion or "请检查必填字段是否完整"`）：
  静态不可判其运行期非空性，**刻意放行**（实测 `product_manage.py` 该形态已带非空
  fallback，判红即假红）。这是「不适用域」，不是「遗漏」——登记在此，不塞进基线。
- **`success=True` 的调用点**：`suggestion` 不是必需（成功路径无需引导修复）。
- **`tests/**` 下的构造**：只扫本体源码（`app/tools/*.py`），测试夹具不在此列。
- **阴性负例（不该被拦）**：`success=True`、`success` 为变量、非 `ToolResult` 的调用、
  带 fallback 的变量建议，在 `TestSuggestionDetectorIsNotVacuous` 里各有显式负例
  —— 守卫不得误伤它们（R2）。

## 为什么按 **AST** 而不是正则 / 文本 grep

要锁的正是「**工具侧失败面**」这个结构：正则数 `ToolResult(success=False` 会把
多行调用、注释里的示例、字符串里的片段一起算进来（实测口径差 3 处）。
AST 口径与 issue #4050 的复算脚本**逐字一致**，读数可互相校验。
"""

import ast
import json
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[1]
TOOLS_DIR = SERVICE_DIR / "app" / "tools"
BASELINE_PATH = SERVICE_DIR.parents[1] / ".github" / "tool-suggestion-baseline.json"

REQUIRED_KWARG = "suggestion"


# ──────────────────────────────────────────────────────────────────────────────
# 判据本体（纯函数、零依赖、单一来源）—— 测试与夹具共用这一处，不写第二份
# ──────────────────────────────────────────────────────────────────────────────


def _is_false_literal(node: ast.AST | None) -> bool:
    """仅当 `success` 是**字面量 `False`** 时才算失败点（口径见文件头「不适用域」）。"""
    return isinstance(node, ast.Constant) and node.value is False


def _declares_suggestion(node: ast.Call) -> bool:
    """该调用是否声明了**非空**的 `suggestion=`。

    判据与 issue #4050 的复算口径**逐字对齐**（读数必须可互相校验）：

    - `suggestion=` 未出现 ⇒ **缺口**（193 处全是这一形态）；
    - `suggestion=None` / `suggestion=""` ⇒ **缺口**（与「没写」等价，
      `_self_correct_retry` 对三者一视同仁地短路）；
    - 其余（字面量非空串 / f-string / 拼接 / **变量**）⇒ 放行。

    ⚠️ **为什么变量也放行**（这是**刻意**收窄，不是漏判）：实测 `product_manage.py`
    第 242 行有 `suggestion=suggestion or "请检查必填字段是否完整"` —— 变量已带非空
    fallback，静态判红就是**假红**（R2：判据不得拦掉原本合法的输入）。变量的运行期
    非空性由 L2 单测承担（先例：`tests/test_piecework_query.py`、
    `tests/test_customer_manage.py` 已对各自工具断言 `result.suggestion` 非空）。
    """
    for kw in node.keywords:
        if kw.arg != REQUIRED_KWARG:
            continue
        value = kw.value
        if isinstance(value, ast.Constant):
            if value.value is None:
                return False
            if isinstance(value.value, str):
                return value.value.strip() != ""
            return True  # 非常量字面量（理论上不会出现）—— 不判红，交由 L2
        return True
    return False


def failure_sites_missing_suggestion(source: str) -> list[int]:
    """源码里**缺 `suggestion` 的 `ToolResult(success=False, …)`** 行号（升序、1-based）。

    非 `ToolResult` 的调用、`success=True` 的调用、以及 `success` 为非字面量的调用
    一律不计入 —— 它们是本判据的**不适用域**（阴性负例见 `TestSuggestionDetectorIsNotVacuous`）。
    """
    tree = ast.parse(source)
    missing: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.id
            if isinstance(func, ast.Name)
            else (func.attr if isinstance(func, ast.Attribute) else None)
        )
        if name != "ToolResult":
            continue
        keywords = {kw.arg: kw.value for kw in node.keywords if kw.arg}
        if not _is_false_literal(keywords.get("success")):
            continue
        if not _declares_suggestion(node):
            missing.append(node.lineno)
    return sorted(missing)


def tool_source_files() -> list[Path]:
    """本体源码清单（`app/tools/*.py`）—— 不递归、不扫 `tests/**`。"""
    return sorted(TOOLS_DIR.glob("*.py"))


def live_violations() -> list[str]:
    """当前本体源码里的缺口，形如 `"文件名:行号"`（升序）。"""
    violations: list[str] = []
    for path in tool_source_files():
        for lineno in failure_sites_missing_suggestion(path.read_text(encoding="utf-8")):
            violations.append(f"{path.name}:{lineno}")
    return sorted(violations)


def total_failure_sites() -> int:
    """失败面总数（分母）—— 用于「守卫不得空转」的自证。"""
    total = 0
    for path in tool_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else (func.attr if isinstance(func, ast.Attribute) else None)
            )
            if name != "ToolResult":
                continue
            keywords = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            if _is_false_literal(keywords.get("success")):
                total += 1
    return total


def load_baseline() -> list[str]:
    """存量基线（**只许缩短**）。

    文件不存在 = 空基线（本 PR 的目标形态：193 处全部补齐 ⇒ 无需任何豁免）。
    """
    if not BASELINE_PATH.exists():
        return []
    payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    entries = payload.get("entries", [])
    assert isinstance(entries, list), f"{BASELINE_PATH} 的 `entries` 必须是列表（fail-closed）"
    return sorted(str(e) for e in entries)


def unbaselined(violations: list[str], baseline: list[str]) -> list[str]:
    """按「**文件 + 是否命中基线**」判增量（行号会漂移，故只做粗粒度对账）。

    返回**不在基线覆盖范围内**的违规（= 新增违规 ⇒ 必须报红）。
    """
    baselined_files = {e.split(":")[0] for e in baseline}
    return [v for v in violations if v.split(":")[0] not in baselined_files]


# ──────────────────────────────────────────────────────────────────────────────
# ① 存量缺口必须为空（本次修复后）
# ──────────────────────────────────────────────────────────────────────────────


class TestNoFailureSiteIsMissingASuggestion:
    """`ToolResult(success=False, …)` 必须带非空 `suggestion=`。"""

    def test_every_failure_site_declares_a_suggestion(self):
        """全量失败面逐个检查 —— 缺口必须为空（基线只许缩短，目标为空）。"""
        violations = live_violations()
        baseline = load_baseline()
        new_ones = unbaselined(violations, baseline)
        assert new_ones == [], (
            f"{len(new_ones)} 处失败点缺 `suggestion=`（不在基线内 ⇒ 阻塞）：\n  "
            + "\n  ".join(new_ones[:40])
            + f"\n\n共 {len(violations)} 处缺口 / 基线 {len(baseline)} 条"
            "\n修法：给每个 `ToolResult(success=False, …)` 补一句**可执行下一步**中文短句，"
            "如 suggestion=\"请用 product_detail 查该商品的可选规格后再重试\"。"
        )

    def test_live_inventory_is_not_vacuous(self):
        """守卫不得空转：本体里必须解析出足量失败面，否则解析口径已经失效（fail-closed）。"""
        total = total_failure_sites()
        assert total >= 300, (
            f"`app/tools/*.py` 只解析出 {total} 个 `ToolResult(success=False, …)` 调用点 "
            "—— 解析口径已失效（守卫会空转通过）。请核对 `app/tools/` 是否被移动/重命名。"
        )

    def test_baseline_shrinks_or_accepts_the_past_but_never_grows(self):
        """基线**只许缩短**（R4 禁止新增豁免）：当前缺口数不得超过基线条数。"""
        assert len(live_violations()) <= len(load_baseline()), (
            "缺口数超过了基线 —— 基线只许缩短，不得为了让守卫变绿而扩容"
        )


# ──────────────────────────────────────────────────────────────────────────────
# ② 判据自身可红 + 不恒真（落盘夹具注入：真写文件、真扫目录）
# ──────────────────────────────────────────────────────────────────────────────

_MISSING_FIXTURE = '''"""夹具：一个缺 suggestion 的失败点（判据必须报出）。"""
from app.tools.base import ToolResult


def bad_tool():
    return ToolResult(
        success=False,
        error="缺少必填参数 wechatNickname",
        message="查询顾客时必须提供 wechatNickname",
    )
'''

_FIXED_FIXTURE = '''"""夹具：同一失败点补上 suggestion 后（判据必须不报）。"""
from app.tools.base import ToolResult


def good_tool():
    return ToolResult(
        success=False,
        error="缺少必填参数 wechatNickname",
        message="查询顾客时必须提供 wechatNickname",
        suggestion="缺少必填参数 wechatNickname，请向用户询问微信号后重试",
    )
'''


class TestSuggestionDetectorIsNotVacuous:
    """**:red_circle: 红证**（注入式）+ **负例**：判据必须能报出，也必须能不报。"""

    def test_injected_missing_suggestion_is_reported(self, tmp_path):
        """把缺 `suggestion` 的失败点**落盘**再扫 ⇒ **必须报出**（否则判据是空的）。"""
        fixture = tmp_path / "fixture_tool_missing.py"
        fixture.write_text(_MISSING_FIXTURE, encoding="utf-8")
        violations = failure_sites_missing_suggestion(fixture.read_text(encoding="utf-8"))
        assert violations == [6], (
            f"注入的负例夹具未被报出（判据是空的）：{violations!r}；"
            "期望恰好命中第 6 行的 `ToolResult(success=False, …)`"
        )

    def test_injected_fixed_suggestion_is_not_reported(self, tmp_path):
        """负例：补上建议后**必须不报**（防恒红 —— 修好后守卫必须让路）。"""
        fixture = tmp_path / "fixture_tool_fixed.py"
        fixture.write_text(_FIXED_FIXTURE, encoding="utf-8")
        assert failure_sites_missing_suggestion(fixture.read_text(encoding="utf-8")) == []

    def test_empty_or_none_suggestion_counts_as_missing(self, tmp_path):
        """`suggestion=None` / `suggestion=""` 与「没写」等价 —— 自愈闸门对三者一视同仁。"""
        for i, value in enumerate(('None', '""', '"   "')):
            fixture = tmp_path / f"fixture_empty_{i}.py"
            fixture.write_text(
                "from app.tools.base import ToolResult\n"
                "def t():\n"
                "    return ToolResult(success=False, error='x', message='y', "
                f"suggestion={value})\n",
                encoding="utf-8",
            )
            assert failure_sites_missing_suggestion(fixture.read_text(encoding="utf-8")) == [3], (
                f"`suggestion={value}` 必须算缺口（否则空串能冒充建议）"
            )

    def test_legal_inputs_are_not_flagged(self, tmp_path):
        """**阴性负例（R2：证明没有拦掉原本合法的输入）** —— 五类合法形态一律不得报出。"""
        fixture = tmp_path / "fixture_legal.py"
        fixture.write_text(
            "from app.tools.base import ToolResult\n"
            "def t(ok: bool):\n"
            "    a = ToolResult(success=True)\n"                      # 成功路径无需建议
            "    b = ToolResult(success=ok, error='x')\n"             # success 非字面量 ⇒ 不可判
            "    c = Other(success=False)\n"                          # 非 ToolResult
            "    d = ToolResult(success=False, error='x', suggestion='请补齐参数后重试')\n"
            "    e = ToolResult(success=False, error='x',\n"
            "                   suggestion=f'请先用 {a} 查询后再重试')\n"  # f-string
            "    s = 'x'\n"
            "    f = ToolResult(success=False, error='x', suggestion=s or '请稍后重试')\n"  # 变量+fallback
            "    return a, b, c, d, e, f\n",
            encoding="utf-8",
        )
        assert failure_sites_missing_suggestion(fixture.read_text(encoding="utf-8")) == [], (
            "判据误伤了合法输入（R2 负例证据：success=True / success 变量 / 非 ToolResult / "
            "已带建议 / 带 fallback 的变量 五类都必须放行）"
        )

    def test_the_guard_reads_the_real_source_tree(self):
        """守卫的真相源必须真实存在且非空（fail-closed，不得静默跳过）。"""
        files = tool_source_files()
        assert len(files) >= 30, f"`{TOOLS_DIR}` 只找到 {len(files)} 个 .py —— 真相源消失（fail-closed）"
        assert (TOOLS_DIR / "base.py").exists(), "`app/tools/base.py` 不见了（fail-closed）"


# ──────────────────────────────────────────────────────────────────────────────
# ③ 基线机制自身可红（防「基线扩容」这条豁免被静默使用）
# ──────────────────────────────────────────────────────────────────────────────


class TestThresholdGrowthIsRefused:
    """基线**只许缩短**：新增违规必须报出，缩短必须放行（R4 / §19.1 元规则）。"""

    def test_a_new_violation_outside_the_baseline_is_refused(self):
        """**红证**：新文件出现缺口 ⇒ `unbaselined` 必报。"""
        baseline = ["customer_manage.py:248"]
        assert unbaselined(["customer_manage.py:248", "brand_new_manage.py:42"], baseline) == [
            "brand_new_manage.py:42"
        ]

    def test_shrinking_the_baseline_is_accepted(self):
        """**负例**：把缺口全部修掉（违规变空）⇒ 必须放行（防恒红）。"""
        assert unbaselined([], ["customer_manage.py:248"]) == []
        assert unbaselined([], []) == []

    def test_an_absent_baseline_file_means_no_exemption(self):
        """空基线 = 唯一合法终态：它**不放行**任何违规。"""
        assert unbaselined(["anything.py:1"], []) == ["anything.py:1"]

    def test_an_empty_baseline_is_the_declared_target(self):
        """本 PR 的落地形态：基线为空（193 处已全部补齐，无任何豁免）。"""
        with open(BASELINE_PATH, encoding="utf-8") as fh:
            payload = json.load(fh)
        assert payload["entries"] == [], (
            "基线非空 ⇒ 存在未修完的失败面。首选把缺口全部补齐、让基线保持为空"
            "（R4：新违规只有「本次修掉」和「开独立 issue」两个出口）"
        )
        # 不得借基线声明把守卫本身关掉（否则「基线为空」这句话没有约束力）
        assert payload.get("enforced") is True, "基线必须处于 enforced 状态（不得声明为仅报告）"