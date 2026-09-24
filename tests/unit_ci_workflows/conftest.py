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
import hashlib
import os
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