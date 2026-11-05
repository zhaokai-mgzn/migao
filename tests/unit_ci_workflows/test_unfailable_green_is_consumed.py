# case_ids: MC-224
"""`unfailable_green` 标记必须被**读到**（issue #5511 第四节 / 来源台账 #8300 残余①）。

## 病灶（台账原文 + 现取复核）

台账原文：「`unfailable_green` **只写不读**：`git grep -rn unfailable_green origin/main`
⇒ `tests/agent_eval/local_runner.py` 仅写标记，CI 不消费、无台账」。现取复核（`origin/main`）：

- 写：`_run_one_case` 算标记 → `_summary_case` 落 `entry["unfailable_green"] = True`（落 artifact）；
- 读：**除了判据自己**（`test_eval_verdict_trust.py` 断言它被写出来）**没有任何一处读它** ⇒
  「这条通过用例的绿没有可失败支撑」这个判断，**报告面根本看不见**（写的人以为它有效）。

## 修法（接一个消费面，**不**删标记、**不**改判定）

1. `local_runner.fake_green_ids(results)` —— 唯一的**读取口**：把带标记的用例 ID 取出来；
2. `run_suite` 的完成判定块**打印**它们（`🧪 假绿候选…`）⇒ 报告面 = CI 日志，人一眼能看到；
3. ⚠️ **`ok` / `reason` 一个字都不改**：把假绿候选直接判红会误伤存量用例（存量清账要
   基线/棘轮，属另一单）。本条治的是「标记没人读」，不是「标记不够严」。

## 判据（双向，各自会红）

1. `TestFakeGreenIdsReadsTheMarker` —— **标记真被读到**：带标记 ⇒ 出现在列表里；不带 / 为 False
   ⇒ 不出现（负控，防「凡通过用例都算假绿」的假红）。
2. `TestRunSuiteActuallyConsumesIt` —— **接线静态锁**：`run_suite` 必须调用 `fake_green_ids`
   且其返回值进入 `print`（拆掉任一环 ⇒ 红）；注入式红证：把调用换成常量字面量 ⇒ 判据当场
   点名，未注入 ⇒ 不报（判别力自证）。
"""
import ast
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))

RUNNER_PATH = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"


def _load_runner():
    """导入 `local_runner`（缺 httpx 时注入最小替身，单测不得真实 HTTP）。"""
    try:
        import httpx  # noqa: F401
    except ImportError:                      # pragma: no cover
        stub = types.ModuleType("httpx")

        class _AsyncClient:
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件的单测不得真实发起 HTTP")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)
    import local_runner
    return local_runner


lr = _load_runner()


class TestFakeGreenIdsReadsTheMarker:
    """读取口本身：带标记的用例进列表，未标记/标记为假的**不得**混进来。"""

    def test_marked_cases_are_returned(self):
        results = [
            {"case_id": "OR-010", "score": 1.0, "unfailable_green": True},
            {"case_id": "OR-011", "score": 1.0},
            {"case_id": "PG-013", "score": 1.0, "unfailable_green": True},
        ]
        assert lr.fake_green_ids(results) == ["OR-010", "PG-013"], (
            f"带标记的用例必须被读到（实测 {lr.fake_green_ids(results)}）"
        )

    def test_clean_run_returns_empty_list(self):
        """**负控**：没有任何标记 ⇒ 空列表（否则报告面每轮都喊狼来了）。"""
        results = [{"case_id": "OR-010", "score": 1.0},
                   {"case_id": "OR-011", "score": 0.0, "unfailable_green": False}]
        assert lr.fake_green_ids(results) == [], "未标记的用例不得被算成假绿候选"
        assert lr.fake_green_ids([]) == [], "空结果必须是空列表（零执行 ≠ 假绿）"


def _consumption_gaps(src: str) -> list:
    """纯函数内核：`run_suite` 是否真的**读**了标记并把它送进 `print`（报告面）。

    三种形态各报一处（fail-closed：找不到 `run_suite` 也算缺口 —— 判据坐标失效时不许空转）。
    """
    tree = ast.parse(src)
    run_suite = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_suite"),
        None,
    )
    if run_suite is None:
        return ["local_runner.py 里找不到 run_suite —— 判据坐标失效（fail-closed）"]

    gaps = []
    read_var = None
    for node in ast.walk(run_suite):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "fake_green_ids"
                and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
            read_var = node.targets[0].id
    if read_var is None:
        gaps.append("run_suite 没有调用 fake_green_ids —— 标记又变回「只写不读」")
        return gaps

    printed = any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print"
        and any(isinstance(m, ast.Name) and m.id == read_var for m in ast.walk(n))
        for n in ast.walk(run_suite)
    )
    if not printed:
        gaps.append(f"run_suite 读了标记（{read_var}）却没有送进 print —— 报告面看不见 = 等于没接")
    return gaps


class TestRunSuiteActuallyConsumesIt:
    """接线静态锁 + 判别力自证（注入式红证）。"""

    def test_real_runner_has_no_gap(self):
        gaps = _consumption_gaps(RUNNER_PATH.read_text(encoding="utf-8"))
        assert gaps == [], f"`unfailable_green` 的消费面被拆了：{gaps}"

    def test_removing_the_read_is_named(self):
        """注入式红证①：把调用换成常量字面量 ⇒ 判据点名「没有调用」。"""
        src = RUNNER_PATH.read_text(encoding="utf-8")
        mutated = src.replace("_fake_green = fake_green_ids(results)", "_fake_green = []")
        assert mutated != src, "变异没生效（锚点漂移）—— 不许把「注入失效」报成「判据没牙」"
        gaps = _consumption_gaps(mutated)
        assert any("没有调用 fake_green_ids" in g for g in gaps), f"注入后必须点名（实测 {gaps}）"

    def test_removing_the_report_is_named(self):
        """注入式红证②：读了但不打印 ⇒ 判据点名「报告面看不见」。"""
        src = RUNNER_PATH.read_text(encoding="utf-8")
        anchor = '              f"{\', \'.join(_fake_green)}")'
        assert anchor in src, "变异锚点漂移（先看 run_suite 里那行 print 的现在长什么样）"
        mutated = src.replace(anchor, '              "")')
        gaps = _consumption_gaps(mutated)
        assert any("报告面看不见" in g for g in gaps), f"注入后必须点名（实测 {gaps}）"
