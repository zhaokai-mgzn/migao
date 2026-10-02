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
import atexit
import copy
import hashlib
import json
import os
import pickle
import re
import subprocess
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
    # 用例语料解析的**工作量读数**（issue #5301）：与挂钟无关 ⇒ 不受 runner 负载影响。
    # 判据本体在 tests/unit_ci_workflows/test_cases_corpus_parse_memo.py；这里只让它**可见**
    # （「省了多少」必须长得像省了多少，不能只在 PR body 里）。
    _memo = corpus_memo_state()
    terminalreporter.write_line(
        f"[corpus-memo] 用例语料：真解析 = {_memo['misses']} 次 / 缓存命中 = {_memo['hits']} 次"
        f"（缓存条目 {_memo['cache_size']}；{_memo['reason']}）"
    )


# ══════════════════════════════════════════════════════════════════════════════════════
# 用例库全量解析的**内容级缓存**（issue #5301：把套件成本压回有明确余量的水平）
# ══════════════════════════════════════════════════════════════════════════════════════
# ## 病灶（#5301 实测，不是估算）
#
# `render_cases.load_case_dicts()` **每一次调用**都要把 `.github/cases/**`（25 文件 / ~1.9MB）
# 整体走一遍 `yaml_light` 解析 + 逐文件严格判定 —— 本机实测 **~160ms/次**（`yaml_light` 占绝大部分，
# `require_strict` 只占 ~11ms/25 文件）。而 `tests/unit_ci_workflows/**` 有 **75 处**调用点，
# 且其中不少是**每个测试各调一次**（如 `test_case_trust_gate.py` 的多处 `_live()` / `_cases()`）。
# ⇒ 同一份**内容根本没变**的语料，在一个 pytest 进程里被**重复解析数百次**。
# 插桩实测（5 个文件 / 262 个用例）：`load_case_dicts` **102 次**、累计 **152.6s**。
#
# ## 修法（沿用本仓既有先例，不新造机制）
#
# `.github/cases_yaml.py`（issue #5151）已经证明过这条路：「**键 = 内容 sha256**（不是路径、不是
# 时间戳）⇒ 内容变了键就变 ⇒ **不可能命中过期结论**」。这里对**取值**那一层做同一件事
# （那处缓存的是"严格判定的结论"，本处缓存的是"解析出来的用例"）。
#
# * **命中时返回深拷贝** ⇒ 与「现场重新解析一遍」**逐值等价、且对象互不共享** —— 语义一字不变
#   （这也正是今天的语义：每次调用拿到的都是全新的嵌套对象）；
# * **只缓存成功结果** ⇒ 解析抛错（`CasesYamlError`）时不写缓存，每次照旧现场抛；
# * **目录里任何 `.yml` 的内容或文件名变了 ⇒ 键变 ⇒ 重新解析**（新文件/删文件/改一个字都算）。
#
# ## 为什么装在 conftest（一处安装、全目录受益）
#
# 补丁打在 `render_cases.load_case_dicts` 上；`.github/case_trust_gate.py` 的
# `load_cases_from_dir()` 是**调用时**才 `from render_cases import load_case_dicts` ⇒ 它自动走同一份缓存，
# 不需要改 `.github/**` 一个字。conftest 在本目录任何测试模块**导入之前**执行 ⇒ 连
# `from render_cases import load_case_dicts` 这种模块级绑定也拿得到缓存版。
#
# 防回退判据（与负载无关的结构性读数，不是挂钟时长）：
# `tests/unit_ci_workflows/test_cases_corpus_parse_memo.py` —— 「同一内容重复加载 ⇒ 真解析 0 次」。
# 红证孔：`MIGAO_NO_CORPUS_MEMO=1`（**默认关闭**，只为让"把机制注回 ⇒ 必红"可复算）。
_GH_DIR = REPO_ROOT / ".github"
_CORPUS_CACHE: dict[str, list] = {}
_CORPUS_STATS = {"misses": 0, "hits": 0}
_CORPUS_CACHE_MAX = 64          # 纯防病态增长（套件里内容种类是个位数）
_UNCACHED_LOAD_CASE_DICTS = None
_MEMO_STATE = {"installed": False, "reason": "尚未安装"}


def _corpus_key(cases_dir) -> str | None:
    """目录内容的 sha256（文件名 + 逐文件内容都进键）；读不到 ⇒ `None` = 不缓存。"""
    try:
        names = sorted(n for n in os.listdir(cases_dir) if n.endswith(".yml"))
    except OSError:
        return None
    if not names:
        return None
    digest = hashlib.sha256()
    for name in names:
        try:
            with open(os.path.join(str(cases_dir), name), "rb") as fh:
                blob = fh.read()
        except OSError:
            return None
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(blob)
        digest.update(b"\0")
    return digest.hexdigest()


def _memoized_load_case_dicts(cases_dir, *args, **kwargs):
    """`render_cases.load_case_dicts` 的包装：同内容只真解析一次，返回**深拷贝**。"""
    key = _corpus_key(cases_dir)
    if key is not None and key in _CORPUS_CACHE:
        _CORPUS_STATS["hits"] += 1
        return copy.deepcopy(_CORPUS_CACHE[key])
    result = _UNCACHED_LOAD_CASE_DICTS(cases_dir, *args, **kwargs)   # 抛错 ⇒ 不写缓存
    if key is None:
        return result
    if len(_CORPUS_CACHE) >= _CORPUS_CACHE_MAX:
        _CORPUS_CACHE.clear()
    _CORPUS_CACHE[key] = result          # 缓存持有主副本；调用方拿到的是它的深拷贝
    _CORPUS_STATS["misses"] += 1
    return copy.deepcopy(result)


_memoized_load_case_dicts.__corpus_memo__ = True      # type: ignore[attr-defined]


def install_corpus_memo() -> tuple[bool, str]:
    """把内容级缓存装到 `render_cases.load_case_dicts`（幂等）。返回 `(是否已装, 说明)`。

    `MIGAO_NO_CORPUS_MEMO=1` ⇒ **有意不装**（红证孔）：但仍记下补丁前的原函数，
    好让守卫的红证对照臂（"把机制注回"）在任何情况下都拿得到它。
    """
    global _UNCACHED_LOAD_CASE_DICTS
    try:
        if str(_GH_DIR) not in sys.path:
            sys.path.append(str(_GH_DIR))                   # append：只作兜底解析路径
        import render_cases                                  # noqa: PLC0415
    except Exception as exc:                                 # pragma: no cover
        _MEMO_STATE.update(installed=False, reason=f"render_cases 不可导入：{exc!r}")
        return False, _MEMO_STATE["reason"]
    current = render_cases.load_case_dicts
    if not getattr(current, "__corpus_memo__", False):
        _UNCACHED_LOAD_CASE_DICTS = current                  # 补丁前 = 红证的对照臂
    if os.environ.get("MIGAO_NO_CORPUS_MEMO") == "1":         # 红证孔：见模块末注释
        _MEMO_STATE.update(installed=False, reason="MIGAO_NO_CORPUS_MEMO=1 ⇒ 有意不装（红证）")
        return False, _MEMO_STATE["reason"]
    if getattr(current, "__corpus_memo__", False):
        _MEMO_STATE.update(installed=True, reason="已装（幂等复用）")
        return True, _MEMO_STATE["reason"]
    render_cases.load_case_dicts = _memoized_load_case_dicts
    _MEMO_STATE.update(installed=True, reason="已装到 render_cases.load_case_dicts")
    return True, _MEMO_STATE["reason"]


def corpus_memo_state() -> dict:
    """缓存安装状态 + 命中/未命中计数（**判据用它，不用挂钟时长**）。"""
    return {**_MEMO_STATE, **_CORPUS_STATS, "cache_size": len(_CORPUS_CACHE)}


def corpus_loader_uncached():
    """补丁**之前**的原函数（红证用：直连它 = 「把缓存注回」的对照臂）。"""
    return _UNCACHED_LOAD_CASE_DICTS


install_corpus_memo()


# ══════════════════════════════════════════════════════════════════════════════════════
# 本腿**执行形态**的 fail-closed 判定（issue #5814：并行化不得静默少跑）
# ══════════════════════════════════════════════════════════════════════════════════════
# ## 病灶（并行化最容易出的坏形态）
#
# 这条腿从**单进程**改成 `pytest-xdist -n 4` 之后，最危险的坏结果不是"跑得慢"，而是
# **「变快」其实只是「少跑了」**：worker 崩掉 / 收集面被截断 / 整批判据被静默跳过 —— 三者都只让
# 墙钟**变小**，而 required 检查照旧**绿**（「没跑」长得像「通过」）。⇒ 判定必须是
# **与负载无关的工作量读数**，不能是"看了 CI 绿"。
#
# ## 判定渠道（2026-09-30 逐条实测；选这个是因为前三条都**不成立**）
#
# | 尝试 | 实测结果 |
# |---|---|
# | 只 `session.exitstatus = 1` | pytest 仍退出 **0**（xdist 的 `DSession.pytest_sessionfinish` 是 trylast，之后回写它） |
# | 抛 `pytest.exit.Exception` | 单进程退出 **1**；`-n 4` 下每个 worker 退出 1，**控制器仍退出 0**（控制器只认 `workeroutput["shouldfail"]`，不看 worker 的 exitstatus） |
# | 在 worker 里设 `session.shouldfail` | 控制器仍退出 **0**（`remote.pytest_sessionfinish` 在本钩子**之前**就把 `workeroutput` 快照发走了） |
# | **本轮收集到的用例数**（`request.session.testscollected`，评测在**测试体内**） | **单进程与 `-n` 下都拿得到整套库存**（本机实测：子集 14 / 全量 5763，两种形态读数一致） |
#
# ⇒ 判据落在**测试体内**（`test_helper_leg_execution_shape.py::test_live_inventory_is_not_below_the_frozen_baseline`）：
# 测试失败是 pytest 里**唯一**在单进程与 xdist 两种形态下都必定传成非零退出码的通道。
#
# ## 只在"**这一轮跑的是整套**"时判库存（否则会把定位用的子集运行判红 = 假红）
#
# `pytest tests/unit_ci_workflows/<某个文件>` 是研发日常，它的库存当然远小于冻结基线。
# 区分口径是**结构性的、不是启发式的**：本轮收集里**有没有覆盖目录下全部的 `test_*.py`**。
# 只要有一份判据文件没进来（= 收集面被截断的形态），判定就**不早退**、照旧按基线判 —— fail-closed。
# 真值（"目录下有哪些判据文件"）**现取**，不写死清单（新增文件 ⇒ 自动进面）。
_LEDGER_PATH = Path(__file__).parent / "helper_leg_shape_ledger.json"

#: 台账 `consumption_marker` 必须逐字等于**判定本体**的函数名（删了 / 改名 ⇒ 判据红）。
CONSUMPTION_MARKER = "helper_leg_shape_problems"


def _helper_leg_ledger() -> dict:
    """读执行形态台账（读不到 ⇒ 返回 `{}`，判定按 fail-closed 判红）。"""
    try:
        return json.loads(_LEDGER_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 —— 读不到是判红的一种形态，不是崩溃
        return {}


def _frozen_skip_reading(inv: dict, require_realdb: bool) -> int | None:
    """按**当前环境**取冻结的 skip 读数（`skipped_reading` 的键 = 环境标记名）。

    键 = `MIGAO_REQUIRE_REALDB`（CI 的形态：注入该标记）或 `default`。取不到 ⇒ `None`（判红）。
    """
    table = inv.get("skipped_reading")
    if not isinstance(table, dict) or not table:
        return None
    key = "MIGAO_REQUIRE_REALDB" if require_realdb else "default"
    return None if key not in table else int(table[key])


def _current_test_files() -> set[str]:
    """本目录下**现取**的判据文件名集合（真值；不写死清单 —— 新增文件自动进面）。"""
    try:
        return {p.name for p in Path(__file__).parent.glob("test_*.py")}
    except OSError:
        return set()


def helper_leg_shape_problems(collected: int, skipped: int, ledger: dict | None = None,
                              collected_names=None,
                              require_realdb: bool | None = None) -> list[str]:
    """本腿执行形态的**纯函数**判定（红证可在内存里构造，不必跑整轮）。

    四条不变式（任一不成立 ⇒ 返回非空 ⇒ 判红）：

    | # | 不变式 | 回归时会怎么红 |
    |---|---|---|
    | ① | 台账在册（`shape.parallel_workers` + `frozen_inventory` 齐备） | 台账被删空 / 被改名 ⇒ 无对象可判 ⇒ 红（fail-closed） |
    | ② | **跑整套**时：`collected` ≥ `frozen_inventory.collected_total` | 收集面被截断 / worker 崩 / 整批判据消失 ⇒ 红（"变快"只是"少跑"） |
    | ③ | **跑整套**时：`skipped` == 该环境的冻结读数 | 静默跳过变多（真库族退回 skip 一族）/ 有判据没过收集面 ⇒ 红 |
    | ④ | 跑子集时**不早退的形态**也要能被判到（`collected_names` 里少一份文件 ⇒ 照旧按②③判） | 反过来的坏形态：把判据的早退条件写成"库存小就放过" ⇒ 真丢文件时也放过 |
    """
    book = _helper_leg_ledger() if ledger is None else ledger
    if not book:
        return [f"执行形态台账读不到或为空：{_LEDGER_PATH}（issue #5814 ⇒ fail-closed 判红）"]
    shape = book.get("shape") or {}
    inv = book.get("frozen_inventory") or {}
    if not shape.get("parallel_workers") or not inv:
        return [
            "执行形态台账缺 `shape.parallel_workers` 或 `frozen_inventory` ⇒ 无对象可判"
            f"（issue #5814）：shape={shape} / frozen_inventory={inv}"
        ]
    floor = int(inv.get("collected_total") or 0)
    if floor <= 0:
        return [f"冻结基线的 `collected_total` 未填（= {floor}）⇒ 判据是空断言（issue #5814）"]
    if require_realdb is None:
        require_realdb = pg_cluster.require_realdb()
    frozen_skips = _frozen_skip_reading(inv, bool(require_realdb))
    if frozen_skips is None:
        return [
            "冻结台账里取不到本环境的 `skipped_reading`（键 = `MIGAO_REQUIRE_REALDB` / `default`）"
            f"⇒ 无对象可判，fail-closed 判红（issue #5814）：{inv.get('skipped_reading')!r}"
        ]
    # 这一轮跑的是不是**整套**：结构判据 = 收集面覆盖了目录下全部判据文件（现取真值）
    if collected_names is None:
        collected_names = _current_test_files()
    missing_files = _current_test_files() - set(collected_names)
    whole_suite = not missing_files
    if not whole_suite:
        return []
    bad: list[str] = []
    if collected < floor:
        bad.append(
            f"判据库存塌了：本轮收集 {collected} < 冻结基线 {floor}（差 {floor - collected} 条）——"
            "并行化的收益若来自「少跑」，它是坏形态而不是优化（issue #5814）"
        )
    if skipped != frozen_skips:
        bad.append(
            f"skip 读数与冻结读数不符：本轮 skip {skipped} != 冻结 {frozen_skips}"
            f"（`MIGAO_REQUIRE_REALDB`={bool(require_realdb)}）—— 比冻结多 = 有判据退回静默跳过；"
            "比冻结少 = 有判据根本没过收集面（两者都让「变快」可能只是「少跑」，issue #5814）"
        )
    return bad


def is_subset_run(session) -> bool:
    """本轮是否**结构性子集**（未覆盖本目录下全部 `test_*.py`）。

    🔴 **单一真相源**（issue #5814）：`collection_floor_problems` 的**早退条件**与
    `test_helper_leg_execution_shape.py::test_session_hook_is_wired_and_fires_on_a_short_inventory`
    的 **skip 条件必须同口径**。两者曾经分家：钩子用**结构性**判据（覆盖不全部判据文件 ⇒ 早退），
    而测试用 `session.testscollected < 100` 这种**启发式**门 ⇒ **中等子集**（实测：9 个判据文件 /
    145 条）越过启发式门、而钩子仍按结构性早退 ⇒ 该测试拿到 `DID NOT RAISE` 的**假红**。
    ⇒ 判定只允许写在这里一处，两边都调它。
    """
    names = {(getattr(item, "nodeid", "") or "").split("::", 1)[0].rsplit("/", 1)[-1]
             for item in list(getattr(session, "items", []) or [])}
    return bool(_current_test_files() - names)


def collection_floor_problems(session, ledger: dict | None = None) -> list[str]:
    """**运行期**的收集面判定：只在「本轮跑的是整套」时按冻结基线判库存（其余形态早退）。

    区分口径是**结构性的**（不是启发式）：本轮 `session.items` 有没有覆盖目录下**全部**
    `test_*.py`（真值现取）。子集运行（`pytest tests/unit_ci_workflows/<某个文件>`，
    研发日常）⇒ 不判；一旦**少了一份判据文件**，既不是"整套"，也不是"合法的子集" ⇒
    照旧按基线判 —— fail-closed，不放过真实的收集面截断。
    """
    book = _helper_leg_ledger() if ledger is None else ledger
    inv = (book.get("frozen_inventory") or {})
    floor = int(inv.get("collected_total") or 0)
    if floor <= 0:
        return []
    if is_subset_run(session):
        return []                      # 子集运行（或本文件自己被筛掉）：库存判据不适用（口径见 is_subset_run）
    if os.environ.get("MIGAO_FAIL_HELPER_LEG_SHAPE") == "1":     # 红证孔（默认关闭）
        return ["（红证孔 MIGAO_FAIL_HELPER_LEG_SHAPE=1 有意注入）判据本体未被调用即判红"]
    collected = int(getattr(session, "testscollected", 0) or 0)
    if collected < floor:
        return [
            f"判据库存塌了：本轮收集 {collected} < 冻结基线 {floor}（差 {floor - collected} 条）——"
            f"并行化的收益若来自「少跑」，它是坏形态而不是优化（issue #5814；台账 = {_LEDGER_PATH.name}）"
        ]
    return []


# ══════════════════════════════════════════════════════════════════════════════════════
# **直连整目录** `pytest tests/unit_ci_workflows` 也拿机器级锁（issue #6019）
# ══════════════════════════════════════════════════════════════════════════════════════
# ## 病灶（2026-10-02 现场读数，不是推断）
#
# `scripts/machine-heavy-lock.sh` 的射程此前**只包 `verify-all.sh` 的档**；`heavy_entry_ledger.json`
# 的 `coverage_boundary` 与 `docs/wiki/Development.md` 的「机器级重活并发准入」节都逐字把这写成
# **盖不到的**缺口。当天实测：机器上**同时有 3 个**直连整目录 `pytest tests/unit_ci_workflows`
# （含 `--collect-only`）与持锁者抢 8 核，`load average` 一度 **21.6 / 43.6 / 61.3**；同日 7 个
# `gate` 同跑、最高排队 **已等 2354s / 上限 2400s**。用户裁定：**把这个口子收进锁**。
#
# ## 为什么落在 conftest（而不是再加一层入口纪律）
#
# 「绕过入口」的形态**没有入口可包** —— 纪律盖不住它（实测就是纪律登记着、事故照样发生）。
# 套件自己的 conftest 是**唯一**在「任何人直连整目录」时都必然被加载的东西 ⇒ 准入点放这里。
#
# ## 四条取值（每条都有判据，见 test_suite_self_lock.py）
#
# | # | 判定 | 理由 |
# |---|---|---|
# | ① | **只在目标覆盖整个目录时**拿锁（显式目录路径 / `::` 之前的目录部分 / pytest 关键字） | 跑子集（单文件 / `-k` 收窄）是研发日常且很轻 —— 拿锁会把日常动作串行化 |
# | ② | `MIGAO_HEAVY_LOCK_HELD=1` ⇒ **绝不 acquire** | 祖先（如 `verify-all.sh`）已持锁；再 acquire = 自己跟自己的进程抢同一把锁 = **死锁** |
# | ③ | `CI` 为真 ⇒ 不 acquire | 托管 runner 上跑的是同一套命令，但**不占本机资源**（本机锁的射程就是本机 CPU） |
# | ④ | xdist worker（`hasattr(config, "workerinput")`）⇒ 不 acquire | 只在控制器 / 单进程里拿一次，否则 N 个 worker 互相抢 |
#
# ## 拿不到锁 ⇒ fail-closed（与 `verify-all.sh` 同口径：**没跑**必须长得像**没跑**）
#
# `pytest.exit.Exception(..., returncode=1)`：非零退出 + 报文含**锁文件路径 / 持有者名字·pid·worktree /
# 怎么办**（`./scripts/machine-heavy-lock.sh status`）。默认**不排队**（与 `acquire` 默认语义一致）；
# `MIGAO_HEAVY_WAIT=<秒>` 存在时按它排队（与 `verify-all.sh` 的 `macquire` 同形）。
# 拿锁发生在 `pytest_collection` 钩子里 ⇒ 在**任何收集之前**，输出里不会出现正常收集汇总。
#
# ## 🔴 不得无限阻塞：有界等待 + 祖先已持锁 ⇒ 立即拒绝（issue #6074，纵深防御）
#
# 上面那条「`MIGAO_HEAVY_LOCK_HELD=1` ⇒ 不 acquire」是**豁免**；豁免依赖**上游接线**（`verify-all.sh`
# 拿锁成功后 export）。2026-10-02 实测的缺陷形态 = **上游漏了那一步**，而
# `scripts/batch-gate.sh` 又给 `verify-all.sh` 默认注入 `MIGAO_HEAVY_WAIT=2700`（子代**继承**）⇒
# 子进程 pytest 去抢**祖先手里的同一把锁** ⇒ **死等**（实测：阻塞 26 分钟、0% CPU、全程握着机器级锁）。
# ⇒ 两条出口把「豁免失效」从**挂死**降级成**立即红**：
#   ① **祖先已持锁 ⇒ 不排队**（`_lock_holder_is_an_ancestor`）：持有者要等本进程结束才释放 ⇒ 排队
#      是**结构性死等**，不是"可能等到"；
#   ② **墙钟预算**（`_suite_lock_timeout_seconds` = `MIGAO_HEAVY_WAIT` + 60 / 未设置时 60）⇒ 锁脚本
#      自己卡住也走不出去。
# 两条都走**同一个** fail-closed 出口（`pytest.exit.Exception(returncode=1)` + 可归因报文）。
#
# ## 释放面
#
# `pytest_sessionfinish`（正常 / 异常退出都到）+ 只释放**自己**持有的那份（`machine-heavy-lock.sh release`
# 自己按 pid 比对，非持有者 release 会非零退出且不删锁）。
LOCK_SCRIPT = REPO_ROOT / "scripts" / "machine-heavy-lock.sh"
SUITE_DIR = "tests/unit_ci_workflows"
#: pytest 位置参数的**形态**兜底：`tests/unit_ci_workflows` 前后各留一个空格（下一个匹配到才停）。
_SUITE_ARG_RE = re.compile(r"(?:^|\s)" + re.escape(SUITE_DIR) + r"(?=\s|$)")


#: `acquire_suite_lock` 在 `MIGAO_HEAVY_WAIT` **未设置**时的墙钟预算（秒）。
#: 未设置时锁脚本只试**一次**（`wait_seconds=0` ⇒ 立即 `return 1`），秒级足够；
#: 这个预算只兜「锁脚本自己卡住」那一路 —— 有它才谈得上「任何情况下都不得无限阻塞」。
_SUITE_LOCK_BASE_BUDGET_SECONDS = 60
#: 设置 `MIGAO_HEAVY_WAIT=<秒>` 时，在**它之上**再加的缓冲（给锁脚本打印具名超时报文）。
_SUITE_LOCK_BUDGET_GRACE_SECONDS = 60
#: `_ancestors_of` 的默认递归上限（PID 环 / 病态进程树兜底）。
_MAX_ANCESTOR_DEPTH = 64


def _process_parent_table() -> dict[int, int]:
    """`{pid: ppid}` 现取（`ps -Ao pid=,ppid=`）：取不到 ⇒ 空表（= 判不了，绝不猜）。"""
    try:
        run = subprocess.run(["ps", "-Ao", "pid=,ppid="], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return {}
    table: dict[int, int] = {}
    for line in run.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            table[int(parts[0])] = int(parts[1])
    return table


def _ancestors_of(pid: int, table: dict[int, int] | None = None,
                  *, depth: int = _MAX_ANCESTOR_DEPTH) -> list[int]:
    """`pid` 的**祖先链**（从 `pid` 自己开始，向上到 PID 1；带环保护与深度上限）。"""
    table = _process_parent_table() if table is None else table
    chain: list[int] = []
    seen: set[int] = set()
    cur = int(pid)
    while cur > 0 and cur not in seen and len(chain) <= depth:
        chain.append(cur)
        seen.add(cur)
        cur = table.get(cur, 0)
    return chain


def _lock_file_holder_pid(lock_file) -> int | None:
    """锁文件里记的**持有者 PID**（`machine-heavy-lock.sh` 的 `pid=` 字段）；读不到 ⇒ `None`。"""
    try:
        text = Path(lock_file).read_text(encoding="utf-8", errors="replace")[:65536]
    except OSError:
        return None
    match = re.search(r"^pid=(\d+)$", text, re.M)
    return int(match.group(1)) if match else None


def _lock_holder_is_an_ancestor(lock_file, env=None, *, table: dict[int, int] | None = None) -> str | None:
    """**纯函数 / 可注入**：锁文件的持有者是不是**本进程的祖先**？是 ⇒ 返回归因串，否 ⇒ `None`。

    治的形态（2026-10-02 实测）：`verify-all.sh` 已持锁、却**没给子代**设 `MIGAO_HEAVY_LOCK_HELD=1`
    而 `MIGAO_HEAVY_WAIT=<大数>` 又是**继承**来的 ⇒ 子进程 pytest 直连整目录时去抢**祖先手里的同一把锁**：
    祖先要等子进程结束才释放、子进程在等祖先 ⇒ **死等**（实测阻塞 26 分钟 + 握锁 0% CPU）。
    这一路**注定拿不到锁**（持有者是活的祖先）⇒ 排队等待不是"可能等到"，而是**结构性不可能** ⇒
    必须**立即**拒绝，而不是把 `MIGAO_HEAVY_WAIT` 走完。
    """
    env = os.environ if env is None else env
    pid = _lock_file_holder_pid(env.get("MIGAO_HEAVY_LOCK_FILE") or (REPO_ROOT / ".." / ".none"))
    if pid is None:
        return None
    table = _process_parent_table() if table is None else table
    if pid not in _ancestors_of(os.getpid(), table):
        return None
    if pid == os.getpid():
        return f"pid={pid}（= 本进程自己）"
    return f"pid={pid}（= 本进程的祖先）"


def _suite_lock_timeout_seconds(env=None) -> int:
    """`acquire_suite_lock` 的**墙钟上限**（有界等待的落点，代表 = `_suite_lock_timeout_seconds`）。

    `MIGAO_HEAVY_WAIT` 存在时 = 它 + `_SUITE_LOCK_BUDGET_GRACE_SECONDS`（真等满再看锁脚本自己的
    具名超时报文）；未设置时 = `_SUITE_LOCK_BASE_BUDGET_SECONDS`（其实秒级就够 —— 那一路锁脚本
    只试一次）。
    """
    env = os.environ if env is None else env
    base = _SUITE_LOCK_BASE_BUDGET_SECONDS
    raw = str(env.get("MIGAO_HEAVY_WAIT") or "").strip()
    if raw:
        try:
            base = max(0, int(raw)) + _SUITE_LOCK_BUDGET_GRACE_SECONDS
        except ValueError:
            pass        # 非法值由锁脚本自己判用法错误（rc=2）⇒ 这里只给预算，不改语义
    return max(1, base)


def _target_is_the_whole_suite(arg: str, scope: dict[str, bool] | None = None) -> bool:
    """单个 pytest **位置参数**是否指向**整个** `tests/unit_ci_workflows` 目录。

    判定是**结构性**的：`<任意前缀>/unit_ci_workflows` ⇒ 那个目录**必须真的在**
    （`Path.is_dir()`）且里面**至少有一个** `test_*.py`；`::` 之后的节点 id 不算（`…::TestFoo` 仍是整目录）。
    `scope=None` ⇒ 现场取（判据可注入 `{"files": …, "dir_children": …}` 假 scope 造坏形态）。
    """
    if scope is None:
        if not _suite_dir().is_dir():
            return False
        scope = {
            "files": {p.name for p in _suite_dir().glob("test_*.py")},
            "dir_children": {p.name for p in _suite_dir().iterdir()},
        }
    if not scope.get("files"):
        return False                        # 目录里没有判据文件 ⇒ 不是「整个套件」，别拿锁
    missing = set(scope["files"]) - set(scope.get("dir_children") or ())
    if scope.get("dir_children") and missing:
        return False                        # 目录里少了已登记的判据文件 ⇒ 「整套」不成立（fail-closed）
    text = str(arg).strip().strip("\"'").replace("\\", "/").rstrip("/")
    if not text:
        return False
    head = text.split("::", 1)[0]                       # `tests/unit_ci_workflows::TestFoo` 也是整目录
    parts = [p for p in head.split("/") if p not in ("", ".")]
    if parts and parts[-1] == "unit_ci_workflows":
        parts = parts[:-1]
        return not parts or "/".join(parts) == SUITE_DIR.rsplit("/", 1)[0]
    return bool(_SUITE_ARG_RE.search(" " + text + " "))


#: **确定吃一个取值**的选项；其余 `-x` 形态（`--collect-only` / `-q` / `--tb=short` …）
#: **不吃**取值。口径比「除白名单外都吃一个」更**窄**：后者会把 `--collect-only` 后面的
#: `tests/unit_ci_workflows` **当成它的取值剥掉** ⇒ 整目录运行反而判成「没有目标」⇒ 不拿锁。
_VALUE_OPTIONS = {
    "-k", "-m", "-p", "-n", "-c", "-o", "-r", "-W", "--deselect", "--ignore", "--ignore-glob",
    "--rootdir", "--basetemp", "--junitxml", "--import-mode", "--maxfail", "--timeout",
}


def _option_values(argv) -> set:
    """`argv` 里**属于选项取值**的 token（`-p no:cacheprovider` 的 `no:cacheprovider`、`-n 4` 的 `4` …）。

    为什么必须剥：pytest 的 `config.invocation_params.args` 是**原始 argv**（选项与取值混在一起，
    无结构化解析）⇒ 不剥就把 `no:cacheprovider` / `4` 当成**位置参数**，
    `_covers_whole_suite_dir` 的 `all()` 当场判成「子集运行」⇒ 该拿锁时不拿（假绿方向）。
    """
    values: set = set()
    for i, tok in enumerate(argv):
        tok = str(tok)
        if not tok.startswith("-") or tok == "-" or "=" in tok or i + 1 >= len(argv):
            continue
        if tok in _VALUE_OPTIONS:
            values.add(str(argv[i + 1]))
    return values


def _positional_targets(argv) -> list[str]:
    """pytest 位置参数 = argv 里既不是选项、也不是选项取值的 token。"""
    values = _option_values(argv)
    return [str(a) for a in argv
            if not str(a).startswith("-") and a not in values]


#: 「以**关键字**收窄」的选项（`-k expr` / `-m marker`）：目录仍是整目录，但**跑的判据是子集**
#: —— 研发日常（`pytest tests/unit_ci_workflows -k 某个测试`）很轻，拿锁会把日常动作串行化。
#: ⚠️ 这是**有意的收窄**（照 §19.1 登记在边界里）：这类运行偶发地可能仍拉起较重的一批，
#: 但「拿锁面只在**未收窄**的整目录」是本单与用户裁定的口径。
_KEYWORD_OPTIONS = ("-k", "-m")


def _covers_whole_suite_dir(args, scope: dict[str, bool] | None = None) -> bool:
    """除 pytest 选项与选项取值外，**每个**位置参数都必须指向整个目录，且**未被关键字收窄**。"""
    argv = [str(a) for a in args]
    if any(a == opt or a.startswith(opt + "=") for a in argv for opt in _KEYWORD_OPTIONS):
        return False                        # `-k` / `-m` 收窄 ⇒ 这一轮跑的是子集
    targets = _positional_targets(argv)
    if not targets:
        return False
    return all(_target_is_the_whole_suite(a, scope) for a in targets)


def _suite_dir() -> Path:
    return REPO_ROOT / SUITE_DIR


def suite_self_lock_wanted(args, *, config=None, env=None) -> bool:
    """**纯函数**（issue #6019）：本轮 pytest 是否该由**套件自己**拿机器级锁。

    `args` = pytest 的位置参数；`config` = pytest config（只读 `workerinput`，缺省视为单进程）；
    `env` = 环境（缺省 `os.environ`）。判据在 `test_suite_self_lock.py::TestPurePredicate` 逐条注入。
    """
    env = os.environ if env is None else env
    if env.get("MIGAO_HEAVY_LOCK_HELD") == "1":
        return False                    # ② 祖先已持锁 ⇒ 再 acquire 就是死锁
    if _env_truthy(env.get("CI")):
        return False                    # ③ 托管 runner：不占本机资源
    if config is not None and hasattr(config, "workerinput"):
        return False                    # ④ xdist worker：只在控制器 / 单进程里拿一次
    return _covers_whole_suite_dir(args)


def _env_truthy(value) -> bool:
    """`CI` 的「为真」判定（与 shell 口径一致：非空且不是 `0` / `false` / `no`）。"""
    text = str(value or "").strip().lower()
    return text not in ("", "0", "false", "no", "off")


def acquire_suite_lock(env=None) -> tuple[bool, str]:
    """拿套件自己的机器级锁。返回 `(是否拿到, 失败时的人类可读报文)`。

    ⚠️ 只**报告**，不在这里判红：拿不到时由 `pytest_collection` 钩子 `pytest.exit`（fail-closed），
    这样「拿不到 ⇒ 非零退出」这条路对任何调用者都成立，且判据可以直接调本函数看读数。
    """
    env = os.environ if env is None else env
    lock_file = env.get("MIGAO_HEAVY_LOCK_FILE") or "<$HOME/.migao-heavy.lock>"
    # 🔴 **纵深防御（issue #6074）**：无论豁免是否生效（= 祖先有没有设 `MIGAO_HEAVY_LOCK_HELD=1`），
    #    这条路都**不得无限阻塞**。两条出口，按顺序：
    #      ① **祖先已持锁 ⇒ 立即拒绝**（那一路排队注定等不到：持有者要等本进程结束才释放）；
    #      ② 超出墙钟预算（= `MIGAO_HEAVY_WAIT` + 缓冲 / 未设置时 60s）⇒ 同样 **fail-closed** 拒绝。
    #    两条都复用**同一份**拒绝报文出口（锁路径 / 持有者 / 怎么办），不新增第二套格式。
    ancestor = _lock_holder_is_an_ancestor(lock_file, env)
    if ancestor is not None:
        return False, (
            "⛔ 直连整目录 `pytest` 的**机器级重活准入被拒**（issue #6019 / #6074）—— 本次**没有跑**"
            "任何判据（这不是通过、也不是跳过）：\n"
            f"   锁文件 : {lock_file}\n"
            f"   持有者 : {ancestor} —— **祖先已持锁**，它要等本进程结束才释放 ⇒ 排队等待是"
            "**死等**（本形态实测：阻塞 26 分钟 / 0% CPU / 全程握着机器级锁）。\n"
            "   ⚠️ 形态归因：祖先（如 `verify-all.sh`）拿锁成功后**必须** `export MIGAO_HEAVY_LOCK_HELD=1`"
            "（子代继承 ⇒ 不再二次 acquire）；缺这一步时，**任何** `MIGAO_HEAVY_WAIT=<大数>`（如"
            " `scripts/batch-gate.sh` 默认的 2700）都会把「缺接线」放大成「本机挂死」。\n"
            "   怎么办 : 给祖先补上那行 export（本形态的根因，见 verify-all.sh 的 `macquire`）；"
            "或显式给本进程 MIGAO_HEAVY_LOCK_HELD=1（= 祖先已持锁，绝不能再 acquire）；"
            "或只跑子集（很轻、不拿锁）：`pytest tests/unit_ci_workflows/<单文件>`。\n"
            "   现场读取：./scripts/machine-heavy-lock.sh status（看谁在跑 / 已跑多久）"
        )
    # 锁脚本路径：`MIGAO_HEAVY_LOCK_SCRIPT` 覆盖**只为判据注入**（缺省 = 仓内那一份，行为一字不改）。
    lock_script = env.get("MIGAO_HEAVY_LOCK_SCRIPT") or str(LOCK_SCRIPT)
    cmd = [lock_script, "acquire", "pytest unit_ci_workflows（直连整目录）"]
    if env.get("MIGAO_HEAVY_WAIT"):
        cmd += ["--wait", str(env["MIGAO_HEAVY_WAIT"])]
    budget = _suite_lock_timeout_seconds(env)
    acquired = False
    try:
        run = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT), env=env,
                             timeout=budget)
        acquired = run.returncode == 0
        stdout = run.stdout
    except OSError as exc:
        return False, (
            f"机器级准入锁不可用（issue #6019）：无法执行 {lock_script}（{exc!r}）。\n"
            "本次**没有跑**任何判据（这不是通过）—— 先修锁脚本，或显式带着自己的锁再进来。"
        )
    except subprocess.TimeoutExpired:
        # ⚠️ `TimeoutExpired` **是** `SubprocessError` ⇒ 必须排在 `OSError` 之后、且不能被它吞掉；
        #    走到这里 = 锁脚本本身没在预算内退出（与「锁被占」是两回事）⇒ 按拒绝处理（fail-closed）。
        return False, (
            "⛔ 直连整目录 `pytest` 的**机器级重活准入被拒**（issue #6019 / #6074）—— 本次**没有跑**"
            "任何判据（这不是通过、也不是跳过）：\n"
            f"   锁文件 : {lock_file}\n"
            f"   锁脚本 : {lock_script} 在**有界预算 {budget}s** 内没有退出 ⇒ 不等了（有界等待的落点）。\n"
            "   怎么办 : ./scripts/machine-heavy-lock.sh status（看谁在跑 / 已跑多久）；"
            "要么等它跑完；要么排队的调用显式给 MIGAO_HEAVY_WAIT=<秒>；"
            "要么内部腿显式给 MIGAO_HEAVY_LOCK_HELD=1（= 祖先已持锁，绝不能再 acquire）。"
        )
    finally:
        if acquired:
            # acquire 记的持有者是**本进程**（锁脚本用 `$PPID`）⇒ 本进程被 Ctrl-C / 被杀也必须放掉，
            # 否则一次中断就把机器级锁永久占住（§27 的「一次异常退出就死锁」）。
            atexit.register(release_suite_lock, env)
    if run.returncode == 0:
        return True, stdout
    return False, (
        "⛔ 直连整目录 `pytest` 的**机器级重活准入被拒**（issue #6019）—— 本次**没有跑**任何判据"
        "（这不是通过、也不是跳过）：\n"
        f"   锁文件 : {lock_file}\n"
        f"   {stdout.strip()}\n"
        "   怎么办 : ./scripts/machine-heavy-lock.sh status（看谁在跑 / 已跑多久）\n"
        "            要么等它跑完；要么排队的调用显式给 MIGAO_HEAVY_WAIT=<秒>；"
        "要么内部腿显式给 MIGAO_HEAVY_LOCK_HELD=1（= 祖先已持锁，绝不能再 acquire）。\n"
        "   （只跑子集是研发日常且很轻 ⇒ 不拿锁：直接 `pytest tests/unit_ci_workflows/<单文件>`。）"
    )


def release_suite_lock(env=None) -> None:
    """释放**自己**持有的那份（非法持有者由锁脚本自己拒绝，本函数不让异常逃出去）。"""
    try:
        subprocess.run([str(LOCK_SCRIPT), "release"], capture_output=True, text=True,
                       cwd=str(REPO_ROOT), env=os.environ if env is None else env)
    except OSError:
        pass


def pytest_collection(session):  # noqa: ARG001 —— 只需 session.config；钩子体在 collection 之前
    """套件自带准入：**直连整目录**时先拿机器级锁，拿不到 ⇒ `pytest.exit` 非零（issue #6019）。

    ⚠️ 钩子签名只收 `session`（pytest 8 的 hookspec 是 `firstresult=True`）；**返回值必须是 `None`**
    —— `firstresult=True` 下**非 None** 的返回值会**停掉**那个实现 `perform_collect` 的默认插件 ⇒
    **一条判据都收集不到**（实测：本函数初版 `return True` ⇒ `no tests collected`，整条腿变成空跑）。
    拿不到锁时抛 `Exit` 已足够：异常本来就让后续实现不执行，而**收集发生在这一步之内**
    （`--collect-only` 是收集**参数**，不是在 `pytest_collection` **之后**才生效的阶段）⇒
    这条路同样被拦在收集之前。
    """
    config = session.config
    try:
        args = list(config.invocation_params.args)
    except Exception:  # noqa: BLE001 —— 取不到参数 = 「不可判定」，按**最宽**面判（fail-closed）
        args = [SUITE_DIR]
    if not suite_self_lock_wanted(args, config=config, env=os.environ):
        return None
    ok, detail = acquire_suite_lock(os.environ)
    if not ok:
        raise pytest.exit.Exception(detail, returncode=1)
    return None


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    """会话收口：① 释放本套件**自己**拿的机器级锁（issue #6019）② 收集面判在整轮读数上
    （fail-closed，不依赖某条测试是否被跑到，issue #5814）。

    ⚠️ 两者必须在**同一个**钩子函数里：同一模块定义两个同名 `pytest_sessionfinish`，后者会把
    前者**整个覆盖掉**（实测：本包首轮实现就是这么写的 ⇒ `helper-leg-shape` 的收口整个丢了，
    而判据照样绿 —— 同 issue #5829 的形态）。
    """
    release_suite_lock(os.environ)
    _helper_leg_shape_sessionfinish(session)


def _helper_leg_shape_sessionfinish(session):
    """会话收口：把**收集面**判在整轮读数上（fail-closed，不依赖某条测试是否被跑到）。

    ⚠️ **为什么判定要写在测试体外、又要有一条测试体内的同款**（2026-09-30 实测）：

    - 收口钩子**不依赖任何单条测试被跑到**（xdist 下测试会被分到别的 worker ⇒ 只写成测试，
      就是"判据自己可能不跑"的形态）；
    - 而收口钩子里的判红**在 xdist 下传不成退出码**（三条实测见上方判定渠道表）⇒
      最后的 fail-closed 落点仍是**测试失败**（`test_helper_leg_execution_shape.py::
      test_live_inventory_is_not_below_the_frozen_baseline`）。
    ⇒ 两条都留：钩子负责"不依赖某条测试是否被跑到"，测试负责"把判红变成非零退出码"。
    本钩子只在**真收集过用例的进程**里判（xdist 控制器按设计不收集 ⇒ 在那里 `testscollected`
    恒为 0，判它会假红整条腿）。

    🔴 **本钩子曾经被整个丢掉过**（PR #5825 重写判定段时漏掉；5 条判据文件测试**照样全绿**
    ⇒ 缺陷落进 main，由本 PR 补回）：所以接线本身有判据 ——
    `test_helper_leg_execution_shape.py::test_session_hook_is_wired_and_fires_on_a_short_inventory`
    直连本钩子、把台账换成"短库存"版 ⇒ 必须 `pytest.exit.Exception(..., returncode=1)`。
    ⚠️ `Exit` 的签名是 `(msg, returncode=None)` —— 写成 `Exception(1, "说明")` 会让 `returncode`
    变成那句说明（**实测**），判红就拿不到退出码。
    """
    numprocesses = getattr(session.config.option, "numprocesses", None) or 0
    if numprocesses and not hasattr(session.config, "workerinput"):
        return                     # xdist 控制器：不收集、不执行 ⇒ 它没有可判的读数
    problems = collection_floor_problems(session)
    if not problems:
        return
    print("\n[helper-leg-shape] 本腿收集面判红（issue #5814，" + CONSUMPTION_MARKER + "）：")
    for item in problems:
        print("  - " + item)
    if numprocesses:
        session.shouldfail = "helper-leg-shape 判红（issue #5814）"   # xdist：worker 报给控制器
        return
    raise pytest.exit.Exception("helper-leg-shape 判红（issue #5814）：见上方逐条归因",
                                returncode=1)
