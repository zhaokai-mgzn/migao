"""CI workflow 辅助测试 conftest：共享 `EvalCase` 的跨文件污染防线（issue #4061）。

## 病灶

`tests/agent_eval/eval_cases.py`（生成物，源 = `.github/cases/**`）的 `ALL_CASES` 是
**模块级共享单例**：同进程内任何测试原地改写它（如 `x.namespaces = []`）都会污染其后
所有测试，而 **CI 判不出来** —— `pr-check.yml` 从仓库根按路径字母序收集，
`test_eval_case_asset_truth` 排在 `test_eval_namespace_isolation` **之前** ⇒
受害者先跑、投毒者后跑 ⇒ 恒绿；只有显式把投毒者排到前面才红（改前实测 1 failed）。
（形态属 `migao-acceptance` §19.1「不会红的假绿」：判据在 CI 上永不触发。）

## 两道防线（治**机制**，不是修那个点位）

1. **深拷贝句柄** `shared_eval_cases()` / `eval_cases_snapshot` fixture —— 要改造拿自己那份；
2. **常驻守卫**（本文件 `_shared_eval_cases_stay_pristine`，autouse + fail-closed）——
   每个测试跑完比对共享对象的内容指纹；变了 ⇒ 先就地恢复干净、再**判当前测试红**
   （指名道姓、不级联、不加豁免清单）。

红证与负例见 `tests/unit_ci_workflows/test_shared_eval_case_immutability.py`（喂真·原地改写 ⇒ 守卫必红）。
"""
import copy
import pickle
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
# append（**不是** insert）：只作兜底解析路径，避免遮蔽 app/ 或 site-packages 里的同名模块。
# 下面这个 `import eval_cases` 必须在**任何测试跑过之前**完成 —— 基线要钉在"无人改过"的时刻。
sys.path.append(str(REPO_ROOT / "tests" / "agent_eval"))

import eval_cases  # noqa: E402


def eval_cases_fingerprint(cases) -> bytes:
    """共享用例集合的**内容指纹**：任一字段被原地改写 ⇒ 指纹不同。"""
    return pickle.dumps(list(cases))


def shared_eval_cases() -> list:
    """共享 `ALL_CASES` 的**深拷贝** —— 用例可自由原地改写，污染不了同进程其它测试。"""
    return copy.deepcopy(list(eval_cases.ALL_CASES))


_CANONICAL = eval_cases.ALL_CASES                 # 原元组对象（元素即共享实例）
_PRISTINE = copy.deepcopy(list(_CANONICAL))       # 字段内容的基线
_BASELINE = eval_cases_fingerprint(_CANONICAL)


def restore_shared_eval_cases() -> None:
    """把共享对象**就地**还原成基线（保持对象身份 —— 持有引用的用例不受影响）。"""
    eval_cases.ALL_CASES = _CANONICAL             # 兜住"有人把模块全局换了"
    for live, pristine in zip(_CANONICAL, _PRISTINE):
        live.__dict__.clear()                     # 连测试私自加的属性一起清掉
        live.__dict__.update(copy.deepcopy(pristine.__dict__))


def guard_shared_eval_cases():
    """守卫判定**本体**（普通生成器）：setup 无事，teardown 比对指纹 + fail-closed。

    抽成生成器而不是把逻辑直接写进夹具，是为了让红证能驱动**同一份本体**
    （pytest 9 的 `@pytest.fixture` 返回 `FixtureFunctionDefinition`，直接调用会被拒）。
    """
    yield
    if eval_cases_fingerprint(eval_cases.ALL_CASES) == _BASELINE:
        return
    restore_shared_eval_cases()                   # 先恢复：只判红投毒者，不级联牵连后面的测试
    pytest.fail(
        "本测试**原地改写**了共享 `eval_cases.ALL_CASES` 对象（issue #4061）："
        "它会被同进程后续测试读到 ⇒ 产生与用例顺序相关、CI 判不出来的假红/假绿。\n"
        "取自己那份再改：`from unit_ci_workflows import conftest` → `conftest.shared_eval_cases()`，"
        "或用 `eval_cases_snapshot` fixture。\n"
        "（共享对象已恢复干净：本次判红，不牵连其它测试。）",
        pytrace=False)


@pytest.fixture(autouse=True)
def _shared_eval_cases_stay_pristine():
    """常驻守卫（L0 fail-closed）：本测试不得原地改写共享 `EvalCase`（issue #4061）。"""
    yield from guard_shared_eval_cases()


@pytest.fixture
def eval_cases_snapshot():
    """共享用例集合的深拷贝（夹具形态，供需要改写的测试使用）。"""
    return shared_eval_cases()


# ══════════════════════════════════════════════════════════════════════════════════════
# 真库（PG）判据的**收口夹具** + skip 可见性（issue #5203）
# ══════════════════════════════════════════════════════════════════════════════════════
# 病灶：13 个真库模块各自带一份「PG 二进制探测」，只认 `PATH`（`shutil.which`），而 CI runner 的
# PG 二进制在 `/usr/lib/postgresql/16/bin`（**不在 PATH**）⇒ 每次 CI 都 `pytest.skip` 成绿
# （实测 87 条 skip，其中 83 条由「只藏 PG 三个二进制」精确复现）。
# ⇒ 发现 + 处置**收口到一处**：`pg_cluster.py` 定候选目录与「缺 PG 判红/skip」的唯一判定，
#   本文件只提供夹具（任何模块**不得**自备探测或 skip 分支 —— 复制逻辑 = 下一份拷贝各自演化）。
from . import pg_cluster  # noqa: E402  （收口件：BIN_DIRS / require_pg / REALDB_TEST_MODULES）


@pytest.fixture(scope="session")
def realdb_binaries() -> dict:
    """三个 PG 二进制的**绝对路径**（缺 PG ⇒ CI 判**红** / 本机显式 skip，收口在 `pg_cluster`）。

    ⚠️ 为什么是 **session 级**：`test_schema_bootstrap_order.py` / `test_v81_compensating_backfill.py`
    的真库夹具是 `scope="module"`，function 级夹具会触发 `ScopeMismatch`；而「候选目录 + 缺 PG
    处置」本就与用例无关，一次决策即可（skip 仍逐条上报，**计数口径不变**）。

    ⚠️ 为什么返回**绝对路径**：argv 里写 `["initdb", …]` 要靠 `PATH` 解析 —— runner 上必然
    `FileNotFoundError`（PG 不在 PATH）⇒ 本 issue 的修法必须同时覆盖「**发现**」与「**调用**」。
    """
    pg_cluster.require_pg()
    return pg_cluster.binaries()


def _skip_reason(report) -> str:
    """从 skip 报告里取出**原因原文**（pytest 的 `longrepr` 有 tuple / 其它两种形态）。"""
    lr = getattr(report, "longrepr", None)
    if isinstance(lr, tuple) and len(lr) >= 3:      # (path, lineno, reason)
        return str(lr[2])
    return str(lr) if lr is not None else "<无原因>"


def _realdb_reports(reports) -> list:
    """哪些 skip 落在**真库模块**里（按收口件的冻结登记表判，不按文案猜）。"""
    return [
        rep for rep in reports
        if rep.nodeid.split("::", 1)[0].rsplit("/", 1)[-1] in pg_cluster.REALDB_TEST_MODULES
    ]


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """把**每条 skip 的 nodeid + 原因**打进终端摘要（issue #5203）。

    病灶：`-q` 让「哪 87 条被跳过」在 CI 日志里**完全不可见** —— 这正是「13 个真库模块一直
    静默 skip 成绿」能藏这么久的**直接原因**。本钩子**不改变任何判定**，只让「没跑」在日志里
    **长得像没跑**。

    末行 `[realdb-summary]` **总是**打印（哪怕一条 skip 都没有）—— 它是 CI 侧的**正证锚点**：
    真库族「**执行 = N** / skip = 0」同时给出，直接回答「这批判据到底跑没跑」
    （改前 CI 上真库族 87 条全是 skip，日志里却什么都看不到）。
    """
    skipped = list(terminalreporter.stats.get("skipped") or [])
    passed = list(terminalreporter.stats.get("passed") or [])
    realdb_skipped = _realdb_reports(skipped)
    realdb_passed = _realdb_reports(passed)
    if skipped:
        terminalreporter.write_sep("=", f"skip 明细（{len(skipped)} 条）—— skip ≠ pass")
        for rep in skipped:
            terminalreporter.write_line(f"  SKIP {rep.nodeid}")
            terminalreporter.write_line(f"       ↳ {_skip_reason(rep)}")
    terminalreporter.write_line(
        f"[realdb-summary] 真库(PG)族：执行 = {len(realdb_passed)} / skip = {len(realdb_skipped)}"
        f"（全部 skip = {len(skipped)}）"
        "—— CI 注入了 MIGAO_REQUIRE_REALDB ⇒ 真库族 skip 必须是 0"
    )