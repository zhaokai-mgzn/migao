# case_ids: PR-006, PP-006
"""`must_succeed` 的 **OR 成功组**（`tool: "A or B"`）——#3781 的产品侧出口，PR-006 的病灶面。

## 症状（逐字读数，2026-10-16 复跑）

PR-006「低库存预警」的期望面自 2026-09-15（#3781）起就是**等价路径 OR**：

    expectations: ["inventory_manage(action=low_stock_alert) or product_search(stock_status=low_stock)"]

而效果层是**合取**的单工具声明 `must_succeed: [product_search]` ⇒ 同一条用例按 agent 选哪条
**等价路径**在 0% / 100% 之间跳：

| 运行 | agent 走的路径 | 读数 |
|---|---|---|
| `/tmp/eval-p4-after-1016-1850.log` | `inventory_manage(action=low_stock_alert)` | `score=0%` + `must_succeed: product_search 从未被调用` |
| `/tmp/eval-normal.log` | `inventory_manage` + `product_search` | `score=100%` |
| `/tmp/eval-p4-baseline-1016-1827.log` | `inventory_manage` | `score=0%` |

两条路径都是产品文档认可的低库存口径（单点来源 `app/tools/stock_semantics.py::LOW_STOCK_THRESHOLD`）
⇒ 那次红**不是** agent 做错，是断言层**过度指定实现路径**（用例注释自己写着"正解是补 runner 的
OR 成功组能力（runner 包），**不是**把这条 `must_succeed` 删掉"）。

## 判据（每条都有会红的注入点）

| # | 判据 | 怎么红 |
|---|---|---|
| 1 | 走分支 A 且 A 成功 ⇒ 通过 | 注入"只认第一分支" ⇒ 本格红 |
| 2 | 走分支 B（**另一条**）且 B 成功 ⇒ 通过 | 回退成单工具声明 ⇒ 本格红（= PR-006 病灶本身） |
| 3 | **反向**：两条分支都没被调用 ⇒ 判红（防"加 OR = 把断言洗空"） | 注入"OR 视为永不违规" ⇒ 本格红 |
| 4 | 分支被调用但**无一成功** ⇒ 判红（OR 不降效果层语义） | 注入"只看调用不看成功" ⇒ 本格红 |
| 5 | 无 ` or ` 的旧声明**逐字等价**（向后兼容） | 改坏单分支路径 ⇒ 既有用例红 |
| 6 | `only_if_called` / `min_successes` 在 OR 组下语义不变 | 见下面两格 |

## 为什么用单测

`check_must_succeed` 是**纯函数**（吃 results 列表、吐 issue 列表），零 LLM / 零网络
（`migao-dev-flow` §16.1：能下层不上层）。
⚠️ 本目录在 CI 只 `pip install pytest pytest-xdist pyyaml`，而 `local_runner` 有模块级
`import httpx` ⇒ 用下方最小替身（与 `test_eval_runner_conditional_effect.py` 同形）。
"""
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))


def _load_runner():
    """导入 `local_runner`（缺 httpx 时注入最小替身；一旦被调用即抛错）。"""
    try:
        import httpx  # noqa: F401
    except ImportError:                      # pragma: no cover - 本地 venv 有 httpx
        stub = types.ModuleType("httpx")

        class _AsyncClient:
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件的单测不得真实发起 HTTP")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)

    import local_runner
    return local_runner


lr = _load_runner()

#: PR-006 现行声明（逐字取自 `.github/cases/product.yml` 的 `must_succeed[0].tool`）
PR006_SPEC = [{"tool": "inventory_manage or product_search"}]


def _round(rnd, calls, results, text=""):
    """构造一轮 `results` 条目（与 `test_eval_runner_conditional_effect.py` 同形）。

    calls   : [(tool, args)]
    results : [(tool, success)]（与该轮**同名工具**的调用按顺序对应）
    """
    return {
        "__round": rnd,
        "tool_calls": [{"name": t, "args": a} for t, a in calls],
        "tool_results": [{"tool": t, "result": {"success": ok}} for t, ok in results],
        "final_text": text,
        "__all_tool_names": sorted({t for t, _ in calls}),
    }


def _low_stock_round(tool, ok=True, rnd=1):
    """PR-006 形态的一轮：`inventory_manage(action=low_stock_alert)` 或 `product_search`。"""
    args = {"action": "low_stock_alert"} if tool == "inventory_manage" else {
        "stock_status": "low_stock"}
    return _round(rnd, calls=[(tool, args)], results=[(tool, ok)],
                  text="当前没有库存不足的商品")


# ══════════════════════════════════════════════════════════════════════════════
# 一、OR 成功组的三态
# ══════════════════════════════════════════════════════════════════════════════

class TestOrSuccessGroupSemantics:
    """`tool: "A or B"` = 「等价路径里**任一条真的成功**」。"""

    def test_either_branch_succeeding_passes(self):
        """判据 1 + 2：**两条分支各自**成功都要能通过（对称性 = 本单的全部意义）。

        只测一条会让"只认第一分支"的坏实现蒙混过关。
        """
        for tool in ("inventory_manage", "product_search"):
            r = _low_stock_round(tool)
            assert lr.check_must_succeed([r], PR006_SPEC) == [], (
                f"分支 {tool} 真的成功了却判红 —— 这正是 PR-006 病灶"
                f"（期望面是 OR、效果层绑死单工具）")

    def test_neither_branch_called_is_red(self):
        """判据 3（**反向**）：加 OR **不**等于把断言洗空 —— 一条都没调必须仍判红。"""
        only_text = [_round(1, [], [], text="请告诉我您想查什么～")]
        issues = lr.check_must_succeed(only_text, PR006_SPEC)
        assert len(issues) == 1, f"应恰好 1 条违规，实得 {issues}"
        assert "从未被调用" in issues[0], issues[0]

    def test_branch_called_but_failed_is_red(self):
        """判据 4：OR **不降**效果层语义 —— 调了但 `success=false` 仍判红（#3778）。"""
        r = _low_stock_round("inventory_manage", ok=False)
        issues = lr.check_must_succeed([r], PR006_SPEC)
        assert len(issues) == 1 and "无一成功" in issues[0], issues

    def test_second_branch_recovers_after_first_failed(self):
        """跨轮：第一轮分支 A 失败、第二轮分支 B 成功 ⇒ 通过（等价路径的真实形态）。"""
        r1 = _low_stock_round("inventory_manage", ok=False, rnd=1)
        r2 = _low_stock_round("product_search", ok=True, rnd=2)
        assert lr.check_must_succeed([r1, r2], PR006_SPEC) == []


# ══════════════════════════════════════════════════════════════════════════════
# 二、向后兼容（无 ` or ` 的声明逐字等价）
# ══════════════════════════════════════════════════════════════════════════════

class TestBackwardCompatibility:
    """既有声明（单工具 / 字符串形态 / action 作用域）语义一字不变。"""

    def test_single_tool_declaration_unchanged(self):
        r = _low_stock_round("product_search")
        assert lr.check_must_succeed([r], [{"tool": "product_search"}]) == []
        only_text = [_round(1, [], [], text="好的")]
        issues = lr.check_must_succeed(only_text, [{"tool": "product_search"}])
        assert len(issues) == 1 and "从未被调用" in issues[0], issues

    def test_string_spec_still_works(self):
        r = _low_stock_round("product_search")
        assert lr.check_must_succeed([r], ["product_search"]) == []

    def test_or_group_with_only_if_called_still_releases_when_untouched(self):
        """`only_if_called` 在 OR 组下语义不变：两条分支都没碰过 ⇒ 放过（可选写分支）。"""
        only_text = [_round(1, [], [], text="请告诉我想要的商品～")]
        spec = [{"tool": "order_create or aftersale_create", "only_if_called": True}]
        assert lr.check_must_succeed(only_text, spec) == []

    def test_or_group_min_successes_counts_across_branches(self):
        """`min_successes` 按**分支并集**计数：同键重试形态（成功 2 次）在 OR 组下仍要真成功 2 次。

        反向那一半同样要测：只成功 1 次 ⇒ 判红（不能因 OR 就把次数下界吞掉）。
        """
        spec = [{"tool": "inventory_manage or product_search", "min_successes": 2}]
        two_ok = [_low_stock_round("inventory_manage", rnd=1),
                  _low_stock_round("product_search", rnd=2)]
        assert lr.check_must_succeed(two_ok, spec) == []
        one_ok = [_low_stock_round("inventory_manage", rnd=1)]
        issues = lr.check_must_succeed(one_ok, spec)
        assert len(issues) == 1 and "成功 1 次 < 要求 2 次" in issues[0], issues


# ══════════════════════════════════════════════════════════════════════════════
# 三、末节：用例里**声明的**就是本文件判的（接线）
# ══════════════════════════════════════════════════════════════════════════════

class TestPr006DeclarationIsWired:
    """PR-006 的 YAML 声明 ⇄ 本文件的判据**同一个对象**（不是两套各自漂移的口径）。"""

    def test_pr006_declares_the_or_group(self):
        import yaml

        doc = yaml.safe_load(
            (REPO_ROOT / ".github" / "cases" / "product.yml").read_text(encoding="utf-8"))
        case = next(c for c in doc["cases"] if c.get("id") == "PR-006")
        specs = case.get("must_succeed") or []
        assert len(specs) == 1, f"PR-006 的效果层应恰好 1 条（合取语义）: {specs}"
        declared = str(specs[0].get("tool") if isinstance(specs[0], dict) else specs[0])
        assert " or " in declared, (
            f"PR-006 的效果层必须声明 OR 成功组（否则走另一条等价路径的运行恒红）: {declared!r}")
        # 声明的两条分支必须与期望面的两条**同集**（防"只改一边"留下不对称）
        expected = str((case.get("expectations") or [""])[0])
        for branch in ["inventory_manage", "product_search"]:
            assert branch in declared, f"效果层缺分支 {branch}: {declared!r}"
            assert branch in expected, f"期望面缺分支 {branch}: {expected!r}"
