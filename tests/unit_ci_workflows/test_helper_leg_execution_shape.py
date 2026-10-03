# case_ids: MC-050
"""本腿**执行形态**的登记与漂移守卫（issue #5814 判据；MC-050）。

## 治的形态（2026-09-30 实测，不是估算）

PR 反馈时长的**唯一关键路径**是 required job `ci workflow helper unit tests`
（`.github/workflows/pr-check.yml`）：run `36689037058` 实测该 job **997s**（其中 `Run ci workflow
helper tests` 一步 **989s**），而同一 run 其余 14 条腿**全部 < 60s**（最长 41s）⇒ PR 反馈 ≈ 该 job 时长。
它此前是**单进程**跑整套 `tests/unit_ci_workflows/**`（纯 CPU / 子进程绑定：281 处 `subprocess.*`）

⇒ 提速手段只有**并行化**（削断言 / 减覆盖面都不允许）。而并行化最容易出的坏形态不是"慢"，
是 **「变快」其实只是「少跑了」** —— worker 崩、收集被截断、整批静默 skip，三者都只让墙钟变小，
required 检查照旧**绿**。

## 本文件固化什么（**不是挂钟时长** —— §23 G6）

| # | 判据 | 回归时会怎么红 |
|---|---|---|
| 1 | 台账 `helper_leg_shape_ledger.json` 在册且 schema/字段齐备、谓词可判 | 台账被删空 / 字段被改成空 ⇒ fail-closed 红 |
| 2 | **两边声明同一个并行度**：CI 的 `pr-check.yml` 与本地 `verify-all.sh` 的 `-n` 取值必须都等于台账 `shape.parallel_workers` | 只改一边（或改了 `-n` 没同步台账）⇒ 红（"漂移即红"） |
| 3 | 台账声明的**消费点**逐字存在：`consumption_marker` == `conftest.CONSUMPTION_MARKER` **且** conftest 里真有那个函数 | 判定被删/改名（台账变成一张没人读的表）⇒ 红 |
| 4 | **冻结库存**是实值（`collected_total > 0`），且 `skipped_ceiling` 与 CI 的 `MIGAO_REQUIRE_REALDB=1` 口径一致（= 0） | 把基线填成 0 / 把 skip 上限放宽 ⇒ 判据退化成空断言 ⇒ 红 |
| 5 | **谓词有牙齿**（注入式红证：并行度漂移 / 本地腿漂移 / 库存塌陷 / skip 两个方向 / 台账缺字段，各能单独变红）+ **对照读数**（正常读数 ⇒ 不报） | 谓词恒真/恒假（空断言）⇒ 红 |
| 6 | 红证孔（`MIGAO_FAIL_HELPER_LEG_SHAPE=1`）在**判定读取处**真的存在 | 孔被删 ⇒ 「把机制注红 ⇒ 必红」不可复算 ⇒ 红 |
| 7 | **运行期牙齿**：本轮真收集到的库存 ≥ 冻结基线（`test_live_inventory_is_not_below_the_frozen_baseline`） | 收集面被截断 / worker 崩 / 整批判据消失 ⇒ 测试失败 ⇒ required 判红（**跑子集时不判**，见 §边界） |
| 8 | **分片三方一致**（issue #6164）：台账 `shape.shards` 的片名 == CI matrix 的 `shard` 取值 == 本地 `ci_helper_leg()` 里 `MIGAO_CI_HELPER_SHARD=` 的取值；且 env 名 / 盐 / 规则实现在位 | 只加一片 / 只删一片 / 改了盐没同步 / 台账没登记 ⇒ 红 |
| 9 | **分片是全划分**：按现取语料 + `conftest.shard_of` 复算 ⇒ 每个 `test_*.py` **恰好**落进一片（并集 == 目录全集、两两不相交、无空片） | 分片规则改成漏掉某类文件 / 只有一片拿到全部 ⇒ 红（这是「文件不属于任何片 ⇒ 静默少跑」的唯一堵法） |
| 10 | **每片都有冻结基线**：`frozen_inventory.shards` 的键集合 == 片名集合，且逐片 `collected_total > 0` | 加了片却没冻结该片基线 ⇒ 该片的库存牙齿会失效 ⇒ 红 |
| 11 | 判据 8~10 的**注入式红证**（各能单独变红）+ 对照读数 | 谓词恒真/恒假 ⇒ 红 |

## 未固化 / 边界（照实登记）

- 判据只钉**执行形态**（并行度 / 库存 / skip 上限），**不**为任何一条断言的覆盖面背书；
- **不**判 xdist 的 worker 分配（同一份代码两次运行的分配可能不同 ⇒ 那是有意的非确定性）；
- `collected_total` 是**冻结读数**（钉在 `frozen_inventory.commit`），**不**绑 `origin/main`
  （CI 的 pr-check 是 `fetch-depth: 1` ⇒ merge-base 取不到；§18.3 / #4313）；
- 真库族在并行下的**资源竞争概率**不在面内：只判"隔离手段在位"（各模块自己的 sockdir/datadir/
  `_free_port`），不判它会不会撞端口。
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest
import yaml

from unit_ci_workflows import conftest

REPO = pathlib.Path(__file__).resolve().parents[2]
LEDGER_REL = "tests/unit_ci_workflows/helper_leg_shape_ledger.json"
CI_REL = ".github/workflows/pr-check.yml"
VERIFY_REL = "verify-all.sh"
CI_JOB_NAME = "ci workflow helper unit tests"
PYTEST_TARGET = "tests/unit_ci_workflows"
#: 判定必须读到的红证孔（"把机制注红 ⇒ 必红" 的入口）
FAIL_PROOF_HOLE = "MIGAO_FAIL_HELPER_LEG_SHAPE"

_LEDGER = json.loads((REPO / LEDGER_REL).read_text(encoding="utf-8"))


# ── 纯函数（红证在内存里构造，不必改真文件）────────────────────────────────────────────

def _extract_function(text: str, name: str) -> str:
    """抽 `name() { … }` 到第 0 列的 `}`；抽不到 ⇒ 空串（调用方判红）。"""
    match = re.search(rf"^{re.escape(name)}\(\) \{{[\s\S]*?^\}}", text, re.M)
    return match.group(0) if match else ""


def pytest_argv(text: str, *, ci: bool) -> str:
    """现取那条 pytest 命令行（**只取 argv**：解释器名不参与比较 —— 同 MC-031 口径）。"""
    if ci:
        idx = text.find(CI_JOB_NAME)
        if idx < 0:
            return ""
        text = text[idx:]
    else:
        text = _extract_function(text, "ci_helper_leg")
    match = re.search(rf"-m\s+pytest\s+{re.escape(PYTEST_TARGET)}[^\n]*", text)
    return _argv_only(match.group(0)) if match else ""


#: argv 之后的 **shell 控制尾巴**（`|| rc=1` 等）不是 argv 的一部分（同 MC-031 的口径）：
#: 拆腿后本地每片都写成 `MIGAO_CI_HELPER_SHARD=N/M python3 -m pytest … -n 4 || ci_helper_rc=1`
#: —— 片号必须走 env、每片退出码必须逐片收集。
_ARGV_TAIL_RE = re.compile(r"\s*(?:\|\||&&|;).*$")


def _argv_only(line: str) -> str:
    """去掉 shell 控制尾巴后的 argv 原文。"""
    return _ARGV_TAIL_RE.sub("", line or "").strip()


def pytest_argv_lines(text: str) -> list[str]:
    """现取**全部** pytest 命令行（本地腿拆腿后有两片 ⇒ 两行）。

    🔴 取全部而不是第一条：本包实测过一处真退化 —— 只比第一条时，**只改第二片**
    （`-n 4 → -n 8`）判据毫无反应 ⇒ 「并行度三方一致」这条契约被钉住的只剩两片中的一片。
    """
    body = _extract_function(text, "ci_helper_leg")
    return [_argv_only(m.group(0))
            for m in re.finditer(rf"-m\s+pytest\s+{re.escape(PYTEST_TARGET)}[^\n]*", body)]


def parallel_flag(argv: str, flag: str) -> str | None:
    """argv 里 `-n <值>` 的取值（`-n` 与取值之间允许 `=`）；没写 ⇒ `None`。"""
    match = re.search(rf"(?:^|\s){re.escape(flag)}(?:=|\s+)(\S+)", argv or "")
    return match.group(1) if match else None


def ledger_shape_problems(ledger: dict, ci_argv: str, local_argv: str) -> list[str]:
    """判据 1/2/3/4 的**谓词本体**（两个臂共用同一份：真台账 / 内存构造的坏台账）。"""
    bad: list[str] = []
    shape = ledger.get("shape") or {}
    declared = shape.get("parallel_workers")
    flag = shape.get("parallel_flag")
    if not isinstance(declared, int) or declared < 2 or not flag:
        return [f"台账 `shape` 不可判：parallel_workers={declared!r} / parallel_flag={flag!r}"]
    if ledger.get("consumption_marker") != conftest.CONSUMPTION_MARKER:
        bad.append(
            f"台账声明的消费点 {ledger.get('consumption_marker')!r} != conftest.CONSUMPTION_MARKER "
            f"{conftest.CONSUMPTION_MARKER!r} ⇒ 台账成了一张没人读的表"
        )
    if not callable(getattr(conftest, conftest.CONSUMPTION_MARKER, None)):
        bad.append(f"conftest 里没有可调用的 {conftest.CONSUMPTION_MARKER}() ⇒ 判定本体不存在")
    holes = (REPO / "tests/unit_ci_workflows/conftest.py").read_text(encoding="utf-8")
    if FAIL_PROOF_HOLE not in holes:
        bad.append(f"红证孔 {FAIL_PROOF_HOLE} 不在 conftest 的判定读取处 ⇒ 「注红必红」不可复算")
    for label, argv in (("CI", ci_argv), ("本地", local_argv)):
        if not argv:
            bad.append(f"{label}侧现取失败：找不到 `-m pytest {PYTEST_TARGET} …`")
            continue
        got = parallel_flag(argv, flag)
        if got != str(declared):
            bad.append(
                f"{label}侧的 `{flag}` 取值 = {got!r}，台账声明 {declared} ⇒ 形态漂移"
                f"（改了没同步 ⇒ 红；argv = {argv}）"
            )
    inv = ledger.get("frozen_inventory") or {}
    floor = int(inv.get("collected_total") or 0)
    readings = inv.get("skipped_reading")
    if floor <= 0:
        bad.append(f"`frozen_inventory.collected_total` = {floor} ⇒ 库存判据是空断言")
    if not isinstance(readings, dict) or not readings:
        bad.append(f"`frozen_inventory.skipped_reading` 不是非空映射（= {readings!r}）⇒ skip 判据是空断言")
    else:
        if "MIGAO_REQUIRE_REALDB" not in readings or "default" not in readings:
            bad.append(
                "`skipped_reading` 必须同时给出 `MIGAO_REQUIRE_REALDB` 与 `default` 两态"
                f"（只给一态 ⇒ 另一环境无对象可判 ⇒ fail-closed 误红）：{readings!r}"
            )
        for key, value in readings.items():
            if not isinstance(value, int) or value < 0:
                bad.append(f"`skipped_reading.{key}` 不是非负整数（= {value!r}）")
        # CI 的形态（注入标记 ⇒ 真库族判红不跳过）的 skip 读数必然 **≤** 本地（不注入）的读数
        if isinstance(readings.get("MIGAO_REQUIRE_REALDB"), int) and isinstance(readings.get("default"), int) \
                and readings["MIGAO_REQUIRE_REALDB"] > readings["default"]:
            bad.append(
                "冻结读数自相矛盾：`MIGAO_REQUIRE_REALDB`（更严的形态）的 skip 读数大于 `default`"
                f"：{readings!r}"
            )
    return bad


def _run(ledger: dict, ci_argv: str, local_argv: str) -> list[str]:
    return ledger_shape_problems(ledger, ci_argv, local_argv)


def _set_floor(ledger: dict, value: int) -> dict:
    """把**本轮该用的**那条库存下界改成 `value`（分片感知：有片改片，无片改整套）。

    为什么不能直接写 `frozen_inventory.collected_total`：**本文件自己就跑在某一片里**
    （CI 上 `MIGAO_CI_HELPER_SHARD` 是设着的）⇒ 判定读的是**该片**的下界，改整套那个数改不到它
    ⇒ 红证会退化成空跑（这正是「判据不知道自己跑在哪一片」的形态）。
    """
    shard = conftest.active_shard()
    if shard is None:
        ledger["frozen_inventory"]["collected_total"] = value
    else:
        key = f"{shard[0]}/{shard[1]}"
        floors = ledger["frozen_inventory"].setdefault("shards", {})
        floors[key] = {**(floors.get(key) or {}), "collected_total": value}
    return ledger


@pytest.fixture(autouse=True)
def _red_proof_hole_off(monkeypatch):
    """红证孔**默认关闭**：本文件的判据自己不能被它注红（否则「注红必红」的实测会自伤）。

    孔的使用方式 = 在**外面**用 `MIGAO_FAIL_HELPER_LEG_SHAPE=1` 跑 pytest（见模块 docstring）。
    """
    monkeypatch.delenv(FAIL_PROOF_HOLE, raising=False)


# ── 真语料：台账 ⇄ 配置 ⇄ 消费点 三者一致 ────────────────────────────────────────────────

def test_ledger_and_both_configs_agree_on_the_execution_shape() -> None:
    """判据 1/2/3/4：真台账 + 真配置 ⇒ 必须零问题。"""
    ci_argv = pytest_argv((REPO / CI_REL).read_text(encoding="utf-8"), ci=True)
    local_argv = pytest_argv((REPO / VERIFY_REL).read_text(encoding="utf-8"), ci=False)
    problems = _run(_LEDGER, ci_argv, local_argv)
    assert problems == [], "执行形态判据报红：\n  - " + "\n  - ".join(problems)


def test_frozen_inventory_is_a_real_reading_with_provenance() -> None:
    """判据 4：冻结库存必须是**实值 + 可复算**（不是 0 / 不是空串）。"""
    inv = _LEDGER["frozen_inventory"]
    assert int(inv["collected_total"]) > 0, f"冻结库存未填：{inv}"
    assert inv.get("commit") and inv.get("recompute"), f"冻结读数缺出处/复算口径：{inv}"
    assert inv.get("measured_at"), f"冻结读数缺实测时点：{inv}"


def test_live_inventory_is_not_below_the_frozen_baseline(request) -> None:
    """**运行期牙齿**：本轮真收集到的判据库存不得低于冻结基线（issue #5814）。

    这是**唯一**在单进程与 `-n 4` 两种形态下都必定把判红传成非零退出码的通道
    （收口钩子里的 `exitstatus` / `pytest.exit` 在 xdist 下都传不上去 —— 逐条实测见
    `tests/unit_ci_workflows/conftest.py` 的判定段表格）。
    跑子集（`pytest tests/unit_ci_workflows/<某个文件>`）时**不判**（见
    `conftest.collection_floor_problems` 的结构性区分口径），所以研发日常不受影响。
    """
    session = request.session
    whole_suite = not (conftest.expected_test_files()
                       - {conftest._item_file(i) for i in session.items})
    if not whole_suite:
        return                     # 子集运行：库存判据不适用（不是"通过"—— 是"没这一问"）
    problems = conftest.collection_floor_problems(session, _LEDGER)
    assert problems == [], "运行期收集面判红：\n  - " + "\n  - ".join(problems)


def test_session_hook_is_wired_and_fires_on_a_short_inventory(monkeypatch, request, capsys) -> None:
    """**钩子在位且会红**（issue #5814）：收口钩子必须真驱动判定本体，且短库存时真判红。

    病灶（**本包自己踩过一次，记实**）：`#5825` 把「判定」写进 `pytest_sessionfinish`，随后重写
    那一段时**把钩子整个丢了**，而 5 条测试**照样全绿** —— 判据本体测到了，**消费点没人测**。
    所以这条测的是**接线**：直连真钩子、拿真 session、把台账换成"短库存"版 ⇒ 必须抛红。
    """
    session = request.session
    # ⚠️ 不能用 `session.items` 判"跑整套"：`-k` 过滤下 `items` **已被筛过**（实测：全量收集 +
    # `-k 本测试` ⇒ `items` 只剩 2 条）⇒ 那样会让本判据**在最该跑的注入形态下反而 skip**
    # （「判据自己可能不跑」的形态）。改用**收集规模**：本目录全量 ≈5.8k 条、聚焦运行 ≤ 20 条。
    # 🔴 口径必须与钩子**同源**（issue #5814）：钩子的早退判据是**结构性**的
    # （本轮是否覆盖目录下全部 `test_*.py`），不是"收集数小"。旧版这里用
    # `testscollected < 100` 这种启发式门 ⇒ 中等子集（实测 9 文件 / 145 条）越过它、
    # 而钩子仍结构性早退 ⇒ `DID NOT RAISE` **假红**。现统一走 `conftest.is_subset_run`。
    if conftest.is_subset_run(session):
        pytest.skip("子集运行（未覆盖目录下全部判据文件）⇒ 真钩子按结构性早退，本形态判不了接线")
    assert callable(getattr(conftest, "pytest_sessionfinish", None)), (
        "收口钩子不存在 ⇒ 判定本体没人消费（#5825 踩过的形态）")
    # "短库存"必须**相对本轮真实收集数**构造：台账现在的冻结值（5767）已**低于** main 的
    # 现取收集数（别的包在长判据）⇒ 直接 +1 会构造出一个**根本不短**的库存，判据退化成空跑
    # （**实测**：本文件初版就是这么写的，全量里 `DID NOT RAISE`）。
    strict = json.loads(json.dumps(_LEDGER))
    _set_floor(strict, int(session.testscollected) + 1)
    monkeypatch.setattr(conftest, "_helper_leg_ledger", lambda: strict)
    with pytest.raises(BaseException) as caught:
        conftest.pytest_sessionfinish(session, 0)
    assert caught.value.returncode == 1, (
        f"钩子没把判红传成退出码 1（拿到 {caught.value!r}）⇒ required 检查不会红")
    captured = capsys.readouterr()          # ⚠️ 只能读**一次**：第二次读会把缓冲取空（实测过）
    printed = captured.out + captured.err
    assert "库存塌了" in printed, f"钩子判红了但归因没打印（读数={printed[-200:]!r}）"
    monkeypatch.setattr(conftest, "_helper_leg_ledger", lambda: _LEDGER)
    conftest.pytest_sessionfinish(session, 0)      # 正常读数：不得抛（否则恒红 = 空断言）


def test_session_hook_returns_early_on_the_xdist_controller(monkeypatch, request) -> None:
    """控制器早退：`-n` 下控制器不收集用例 ⇒ 在它那里判库存会**假红整条腿**（issue #5814）。"""
    session = request.session
    monkeypatch.setattr(session.config.option, "numprocesses", 4, raising=False)
    if hasattr(session.config, "workerinput"):
        pytest.skip("本进程是 xdist worker（它**该**判）⇒ 控制器早退这一半不适用")
    strict = json.loads(json.dumps(_LEDGER))
    _set_floor(strict, int(session.testscollected) + 1000)
    monkeypatch.setattr(conftest, "_helper_leg_ledger", lambda: strict)
    conftest.pytest_sessionfinish(session, 0)      # 控制器早退 ⇒ 不得抛


def test_collection_floor_guard_is_live_and_fail_closed() -> None:
    """元守卫：运行期判据**在位且会红**（空跑 = 没判据）。

    - 判据本体必须可调用（被删 / 改名 ⇒ 红）；
    - 抬高冻结基线 ⇒ 必红（"少跑了"可判）；
    - 子集形态（收集面缺文件）⇒ 不报（否则研发日常的子集运行会假红）；
    - 收集面缺一份文件时**不早退**（`_current_test_files()` 现取真值，不写死清单）。
    """
    assert callable(getattr(conftest, "collection_floor_problems", None)), (
        "运行期库存判据本体不存在（issue #5814）⇒ 「变快只是少跑」没人判")
    floor = conftest._frozen_floor(_LEDGER["frozen_inventory"], conftest.active_shard())
    strict = json.loads(json.dumps(_LEDGER))
    _set_floor(strict, floor + 1)

    class _Item:
        def __init__(self, nodeid):
            self.nodeid = nodeid

    whole = sorted(conftest.expected_test_files())

    class _Session:
        def __init__(self, collected, nodeids):
            self.testscollected = collected
            self.items = [_Item(n) for n in nodeids]

    assert conftest.collection_floor_problems(_Session(floor, whole), strict) != [], (
        "冻结基线抬高后运行期判据不报 ⇒ 库存塌陷判不出来")
    assert conftest.collection_floor_problems(_Session(floor, whole), _LEDGER) == [], (
        "正常读数被判红 ⇒ 运行期判据过严")
    subset = whole[:3]
    assert conftest.collection_floor_problems(_Session(3, subset), _LEDGER) == [], (
        "子集运行被判红 ⇒ 研发日常的子集运行会假红（判据会把定位工具本身打死）")


# ── 判据 5：注入式红证（4 条各能单独变红）+ 对照读数 ──────────────────────────────────────

def test_criteria_are_not_vacuous_injected_red_proofs() -> None:
    """判据 5：每条不变式**各自**能单独变红；且正常读数**不报**（判别力的另一臂）。"""
    ci_argv = pytest_argv((REPO / CI_REL).read_text(encoding="utf-8"), ci=True)
    local_argv = pytest_argv((REPO / VERIFY_REL).read_text(encoding="utf-8"), ci=False)
    assert ci_argv and local_argv, "真配置里现取不到 argv ⇒ 下面的红证会退化成空跑"

    # 对照读数：正常台账 ⇒ 不报（否则"怎么都红"= 空断言）
    assert _run(_LEDGER, ci_argv, local_argv) == [], "正常台账被判红 ⇒ 判据恒真，不是判据"

    # ① 并行度漂移：CI 侧改小一格（其余一字不动）⇒ 必红
    drifted = re.sub(r"-n\s+(\d+)", lambda m: f"-n {max(1, int(m.group(1)) - 1)}", ci_argv, count=1)
    assert drifted != ci_argv, "变异点没命中 ⇒ 本红证会退化成空跑"
    assert _run(_LEDGER, drifted, local_argv) != [], "CI 侧的并行度漂移居然不报 ⇒ 形态没有被钉住"

    # ② 本地腿漂移：本地侧去掉 `-n <n>` ⇒ 必红
    assert _run(_LEDGER, ci_argv, re.sub(r"\s-n\s+\d+", "", local_argv)) != [], (
        "本地腿少了并行度居然不报 ⇒ 本地会按串行跑（与 CI 不同源）而无人发现")

    # ③ 库存塌陷：**跑整套**时本轮收集数 < 冻结基线 ⇒ 运行期判定必须报（"少跑了"可判）
    floor = conftest._frozen_floor(_LEDGER["frozen_inventory"], conftest.active_shard())
    frozen_skips = int(_LEDGER["frozen_inventory"]["skipped_reading"]["MIGAO_REQUIRE_REALDB"])

    class _Item:
        def __init__(self, nodeid):
            self.nodeid = nodeid

    whole = sorted(conftest.expected_test_files())

    class _Session:
        def __init__(self, collected, nodeids):
            self.testscollected = collected
            self.items = [_Item(n) for n in nodeids]

    assert conftest.collection_floor_problems(_Session(floor - 1, whole), _LEDGER) != [], (
        "本轮收集数低于冻结基线而运行期判定不报 ⇒ 「变快只是少跑」判不出来")
    assert conftest.collection_floor_problems(_Session(floor, whole), _LEDGER) == [], (
        "本轮读数 == 冻结读数却报红 ⇒ 判定过严（正常读数必须不报）")
    assert conftest.collection_floor_problems(_Session(floor - 10, whole), _LEDGER) != [], (
        "库存塌了 10 条（≥ 一条判据文件的量级）仍不报 ⇒ 库存判据无效")
    assert conftest.collection_floor_problems(_Session(3, whole[:3]), _LEDGER) == [], (
        "子集运行被判红 ⇒ 研发日常的 `pytest <某个文件>` 会把定位工具自己打死（假红）")

    # ④ 全量形态下的 skip 判据（同一个谓词的另一条不变式）
    assert conftest.helper_leg_shape_problems(floor, frozen_skips, _LEDGER, whole,
                                              require_realdb=True) == [], (
        "全量 + 冻结读数却报红 ⇒ 判定过严")
    assert conftest.helper_leg_shape_problems(floor, frozen_skips + 1, _LEDGER, whole,
                                              require_realdb=True) != [], (
        "skip 变多却不报 ⇒ 静默跳过有了口子")
    assert conftest.helper_leg_shape_problems(floor, max(0, frozen_skips - 1), _LEDGER, whole,
                                              require_realdb=True) != [], (
        "skip 变少却不报 ⇒ 「有判据没过收集面」可以溜过去")

    # ④ 台账缺字段 / 消费点对不上 / skip 读数被放宽 ⇒ 各自必红
    assert _run({}, ci_argv, local_argv) != [], "空台账不报 ⇒ fail-closed 破了"
    assert _run({**_LEDGER, "consumption_marker": "nobody_calls_this"}, ci_argv, local_argv) != [], (
        "消费点对不上却不报 ⇒ 台账可以随便改名")
    eased = json.loads(json.dumps(_LEDGER))
    eased["frozen_inventory"]["skipped_reading"]["MIGAO_REQUIRE_REALDB"] = frozen_skips + 1
    assert _run(eased, ci_argv, local_argv) != [], (
        "台账里更严形态的 skip 读数被抬到超过 default 却不报 ⇒ 冻结读数自相矛盾没人管")
    # 放宽后的读数与本轮真实读数不符 ⇒ 判定必须报（台账不许被"顺手改宽"）
    assert conftest.helper_leg_shape_problems(floor, frozen_skips, eased, whole,
                                              require_realdb=True) != [], (
        "台账被改宽后判定不报 ⇒ 冻结读数成了可随便改的数")
    # `default` 态（本地无 MIGAO_REQUIRE_REALDB）也必须可判、且逐值相等
    default_skips = int(_LEDGER["frozen_inventory"]["skipped_reading"]["default"])
    assert conftest.helper_leg_shape_problems(floor, default_skips, _LEDGER, whole,
                                              require_realdb=False) == [], (
        "本地形态的正常读数被判红 ⇒ 判定过严")
    assert conftest.helper_leg_shape_problems(floor, default_skips + 1, _LEDGER, whole,
                                              require_realdb=False) != [], (
        "本地形态 skip 变多却不报 ⇒ 静默跳过有了口子")
    missing_state = json.loads(json.dumps(_LEDGER))
    del missing_state["frozen_inventory"]["skipped_reading"]["default"]
    assert _run(missing_state, ci_argv, local_argv) != [], (
        "`skipped_reading` 少一态却不报 ⇒ 那个环境会静默无对象可判（fail-closed 破了）")
    assert conftest.helper_leg_shape_problems(floor, frozen_skips, missing_state, whole,
                                              require_realdb=False) != [], (
        "缺本环境的冻结读数却不报 ⇒ 另一个环境会静默无对象可判")


# ── #5814：**「是否子集运行」只允许一处判定**（假红的根因就是它被写成了两份口径）────

class _FakeSession:
    """最小假 session：只需要 `items`（每个 item 带 `nodeid`）。"""

    def __init__(self, nodeids):
        self.items = [type("I", (), {"nodeid": n})() for n in nodeids]


def test_is_subset_run_classifies_by_structure_not_by_count() -> None:
    """行为级：覆盖全部判据文件 ⇒ 非子集；少一份文件 ⇒ 子集（**与收集数无关**）。"""
    all_files = sorted(conftest.expected_test_files())
    assert all_files, "本目录应当有判据文件（否则本判据是空断言）"
    full = _FakeSession([f"{n}::test_x" for n in all_files])
    assert conftest.is_subset_run(full) is False, "覆盖全部文件 ⇒ 不该判成子集"
    part = _FakeSession([f"{n}::test_x" for n in all_files[:-1]])
    assert conftest.is_subset_run(part) is True, "少一份文件 ⇒ 必须判成子集"
    # 🔴 关键：**收集数多**不等于"不是子集"。旧实现用 `testscollected < 100` 当门 ⇒
    # 9 个文件 / 145 条会越过它、而钩子仍结构性早退 ⇒ `DID NOT RAISE` 假红（实测）。
    many = _FakeSession([f"{all_files[0]}::test_x{i}" for i in range(500)])
    assert conftest.is_subset_run(many) is True, "500 条但只来自 1 个文件 ⇒ 仍是子集"


def test_subset_predicate_has_exactly_one_source() -> None:
    """类级守卫：两个消费点必须调**同一个**判定，且不得回退成数值启发式。

    会怎么红：钩子内联第二份子集判定 / 本文件把 skip 改回数值阈值 / 共享判定被删。
    """
    import inspect
    assert callable(getattr(conftest, "is_subset_run", None)), (
        "共享判定 `conftest.is_subset_run` 不存在 ⇒ 两个消费点又会各自写一份口径")
    floor_src = inspect.getsource(conftest.collection_floor_problems)
    assert "is_subset_run(session)" in floor_src, "库存判据必须走共享判定"
    assert "_current_test_files() - names" not in floor_src, (
        "库存判据不得内联第二份子集判定（口径分家 = #5814 假红根因）")
    me = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert "conftest.is_subset_run(session)" in me, "本文件的 skip 必须走共享判定"
    # ⚠️ 只扫**代码行**（去注释）：注释里引用旧阈值是**正当的**（说明历史），
    # 而"逐字写在断言里"会让判据扫到它自己（自指假红 —— 这两条本会话都实测踩过）。
    code = "\n".join(l for l in me.splitlines() if not l.strip().startswith("#"))
    # 禁用串用拼接构造，避免本判据自身成为命中源
    for bad in ("or 0) < 1" + "00", "testscollected < 1" + "00"):
        assert bad not in code, f"不得用数值启发式判子集（{bad!r}）—— 那是假红的根因"


# ══════════════════════════════════════════════════════════════════════════════════════
# #6164：**分片**（一条 required 腿 → 两条并行腿）的判据 8~11
# ══════════════════════════════════════════════════════════════════════════════════════
# 为什么单独一组：分片把「这条腿跑多大范围」从**一个**命令变成**两片**命令，而三处声明
# （CI matrix / 本地 `ci_helper_leg()` / 台账 `shape.shards`）**任何一处少一片**，后果都不是
# 「变慢」而是**静默少跑那一半**（required 检查照旧绿）。所以这三处必须**逐字三方一致**，
# 且「分片是全划分」必须按**现取语料**复算 —— 规则一改成漏掉某类文件，两片合起来就不等于全集。

SHARD_ENV = conftest.SHARD_ENV


def ci_shard_names(ci_text: str) -> list[str]:
    """现取 CI 侧的分片清单（`jobs.ci-workflow-tests.strategy.matrix.include[].shard`）。"""
    try:
        doc = yaml.safe_load(ci_text) or {}
    except yaml.YAMLError:
        return []
    job = ((doc.get("jobs") or {}).get("ci-workflow-tests") or {})
    matrix = ((job.get("strategy") or {}).get("matrix") or {})
    return [str(e["shard"]) for e in (matrix.get("include") or [])
            if isinstance(e, dict) and e.get("shard")]


def local_shard_names(verify_text: str) -> list[str]:
    """现取本地的分片清单（`ci_helper_leg()` 里 `MIGAO_CI_HELPER_SHARD=<N/M>` 的取值，按出现序）。"""
    body = _extract_function(verify_text, "ci_helper_leg")
    return re.findall(rf"{re.escape(SHARD_ENV)}=([0-9]+/[0-9]+)", body)


def shard_problems(ledger: dict, ci_text: str, verify_text: str, census=None) -> list[str]:
    """判据 8/9/10 的**谓词本体**（真台账 + 内存构造的坏台账/坏配置共用同一份）。"""
    bad: list[str] = []
    shards = ((ledger.get("shape") or {}).get("shards") or {})
    if not shards:
        return ["台账缺 `shape.shards` ⇒ 分片形态下**无对象可判**（issue #6164，fail-closed）"]
    names = [str(n) for n in (shards.get("names") or [])]
    if not names:
        bad.append("台账 `shape.shards.names` 为空 ⇒ 分片清单无对象可判")
    if int(shards.get("count") or 0) != len(names):
        bad.append(f"台账 `shape.shards.count` = {shards.get('count')!r} != 片名条数 {len(names)}")
    if shards.get("env") != SHARD_ENV:
        bad.append(f"台账 `shape.shards.env` = {shards.get('env')!r} != 判定本体用的 {SHARD_ENV!r}")
    if int(shards.get("salt") or 0) != int(conftest.SHARD_SALT):
        bad.append(
            f"台账 `shape.shards.salt` = {shards.get('salt')!r} != `conftest.SHARD_SALT` = "
            f"{conftest.SHARD_SALT} ⇒ **改了盐没同步**（改盐 = 改分片，两片的成员全变）"
        )
    if "conftest.py::shard_of" not in str(shards.get("rule_impl") or ""):
        bad.append(f"台账 `shape.shards.rule_impl` = {shards.get('rule_impl')!r} ⇒ 指向的规则实现不是 "
                   "`conftest.py::shard_of`（规则没有单一实现 = 下一份拷贝各自演化）")

    # ② 三方一致（CI matrix / 本地腿 / 台账）
    for label, got in (("CI matrix", ci_shard_names(ci_text)),
                       ("本地 `ci_helper_leg()`", local_shard_names(verify_text))):
        if not got:
            bad.append(f"{label} 里现取不到分片清单 ⇒ 分片形态无从判定（fail-closed 判红）")
        elif sorted(got) != sorted(names):
            bad.append(f"{label} 的片名 {sorted(got)} != 台账 {sorted(names)} ⇒ 只改了一边（静默少跑那一半）")

    # ③ 全划分：并集 == 现取语料、两两不相交、无空片
    files = set(conftest._current_test_files() if census is None else census)
    if not files:
        bad.append("现取语料为空 ⇒ 「并集 == 全集」是空断言（fail-closed）")
    elif names:
        buckets: dict[str, set[str]] = {}
        for name in names:
            try:
                index, count = (int(x) for x in name.split("/"))
            except ValueError:
                bad.append(f"片名形态不合规（应为 `N/M`）：{name!r}")
                continue
            buckets[name] = {f for f in files if conftest.shard_of(f, count) == index}
        if buckets:
            union = set().union(*buckets.values())
            total = sum(len(b) for b in buckets.values())
            if union != files:
                bad.append(f"分片**不是全划分**：并集 {len(union)} != 语料 {len(files)}（差 "
                           f"{len(files) - len(union)} 个文件不属于任何片 ⇒ 静默少跑）")
            if total != len(union):
                bad.append(f"两片**相交**：各片条数合计 {total} > 并集 {len(union)}（同一文件被跑两次）")
            for name, bucket in buckets.items():
                if not bucket:
                    bad.append(f"分片 {name} 是**空片** ⇒ 那条腿什么都没跑（而 required 照旧绿）")

    # ④ 每片都有冻结基线
    floors = ((ledger.get("frozen_inventory") or {}).get("shards") or {})
    for name in names:
        value = int(((floors.get(name) or {}).get("collected_total")) or 0)
        if value <= 0:
            bad.append(f"分片 {name} 没有冻结基线（`frozen_inventory.shards[{name!r}].collected_total`）"
                       "⇒ 该片的运行期库存牙齿无对象可判")

    # ⑤ **本地腿的每一条** pytest 行都要合规（#6164 补的真退化）：行数 == 片数，且每条的
    #    `-n` 都等于台账声明的并行度 —— 只比第一条 ⇒ 只改第二片就没人拦（本包实测过）。
    shape = ledger.get("shape") or {}
    flag = str(shape.get("parallel_flag") or "-n")
    declared = shape.get("parallel_workers")
    lines = pytest_argv_lines(verify_text)
    if len(lines) != len(names):
        bad.append(f"本地腿里现取到 {len(lines)} 条 pytest 行，而台账声明 {len(names)} 片"
                   " ⇒ 少一条 = 本地少跑一片（而 CI 照旧两片）")
    for i, argv in enumerate(lines):
        got = parallel_flag(argv, flag)
        if declared is not None and str(got) != str(declared):
            bad.append(f"本地腿第 {i + 1} 条 pytest 行的 `{flag}` = {got!r}，台账声明 {declared}"
                       f" ⇒ 形态漂移（**只比第一条**是放走这条的写法；argv = {argv}）")
    return bad


def test_shards_are_declared_consistently_everywhere() -> None:
    """判据 8/9/10：真台账 + 真 CI matrix + 真本地腿 + 真语料 ⇒ 必须零问题。"""
    ci_text = (REPO / CI_REL).read_text(encoding="utf-8")
    verify_text = (REPO / VERIFY_REL).read_text(encoding="utf-8")
    problems = shard_problems(_LEDGER, ci_text, verify_text)
    assert problems == [], "分片判据报红：\n  - " + "\n  - ".join(problems)


def test_shard_partition_is_recomputed_from_the_live_corpus() -> None:
    """判据 9 的**读数**臂：现取语料下，两片的条数必须合计 == 语料（不是「大致相等」）。"""
    names = [str(n) for n in _LEDGER["shape"]["shards"]["names"]]
    files = conftest._current_test_files()
    buckets = {}
    for name in names:
        index, count = (int(x) for x in name.split("/"))
        buckets[name] = {f for f in files if conftest.shard_of(f, count) == index}
    assert sum(len(b) for b in buckets.values()) == len(files), (
        f"分片条数合计 {sum(len(b) for b in buckets.values())} != 语料 {len(files)}"
    )
    assert buckets, "一片都没算出来 ⇒ 本判据是空断言"
    for name, bucket in buckets.items():
        assert bucket, f"分片 {name} 是空片"


def test_shard_criteria_are_not_vacuous_injected_red_proofs() -> None:
    """判据 11：8/9/10 每条**各自**能单独变红；且真读数**不报**（判别力的另一臂）。"""
    ci_text = (REPO / CI_REL).read_text(encoding="utf-8")
    verify_text = (REPO / VERIFY_REL).read_text(encoding="utf-8")
    assert ci_shard_names(ci_text) and local_shard_names(verify_text), (
        "真配置里现取不到片名 ⇒ 下面的红证会退化成空跑"
    )
    assert shard_problems(_LEDGER, ci_text, verify_text) == [], "真读数被判红 ⇒ 谓词恒真，不是判据"

    # ① 台账只登记一片（而 CI / 本地跑两片）⇒ 必红：三方一致没有被钉住
    one_shard_ledger = json.loads(json.dumps(_LEDGER))
    one_shard_ledger["shape"]["shards"]["names"] = ["1/2"]
    one_shard_ledger["shape"]["shards"]["count"] = 1
    assert shard_problems(one_shard_ledger, ci_text, verify_text) != [], (
        "台账只登记一片（而 CI/本地跑两片）⇒ 不报 ⇒ 三方一致没有被钉住"
    )

    # ② 本地腿少一片（把 2/2 那条改成 1/2）⇒ 必红
    one_local = verify_text.replace(f"{SHARD_ENV}=2/2", f"{SHARD_ENV}=1/2")
    assert local_shard_names(one_local) != local_shard_names(verify_text), "变异点没命中 ⇒ 本红证会退化成空跑"
    assert shard_problems(_LEDGER, ci_text, one_local) != [], (
        "本地腿少了 2/2 那一片 ⇒ 不报 ⇒ 本地覆盖缩水（CI 两片、本地一片）会溜过去"
    )

    # ③ CI 少一片 ⇒ 必红（去掉 matrix 的第二条 include）
    one_ci = ci_text.replace('          - shard: "2/2"\n            shard_suffix: "（后半）"\n', "")
    assert ci_shard_names(one_ci) != ci_shard_names(ci_text), "变异点没命中 ⇒ 本红证会退化成空跑"
    assert shard_problems(_LEDGER, one_ci, verify_text) != [], (
        "CI matrix 少一片 ⇒ 不报 ⇒ 「只加一片」的形态（关键路径没减半）会溜过去"
    )

    # ④ 盐漂移（改盐 = 改分片）⇒ 必红
    salted = json.loads(json.dumps(_LEDGER))
    salted["shape"]["shards"]["salt"] = int(conftest.SHARD_SALT) + 1
    assert shard_problems(salted, ci_text, verify_text) != [], (
        "台账的盐与判定实现不一致 ⇒ 不报 ⇒ 两片成员与冻结基线静默对不上"
    )

    # ⑤ 某片没有冻结基线 ⇒ 必红（那一片的库存牙齿会失效）
    no_floor = json.loads(json.dumps(_LEDGER))
    del no_floor["frozen_inventory"]["shards"]["2/2"]
    assert shard_problems(no_floor, ci_text, verify_text) != [], (
        "少了某片的冻结基线 ⇒ 不报 ⇒ 那一半「少跑」没有任何读数"
    )

    # ⑥ 台账整个 `shards` 块被删 ⇒ fail-closed 必红
    assert shard_problems({"shape": {"parallel_workers": 4}}, ci_text, verify_text) != [], (
        "台账没有分片块 ⇒ 不报 ⇒ 分片形态无对象可判"
    )

    # ⑦ 片名与规则的**值域**对不上（`3/2` 这个片号永远分不到文件）⇒ 一整半文件不属于任何片
    #    ⇒ 必红。这是「静默少跑」的**真实**形态：规则没改，但声明的片名漏了一片。
    holes = json.loads(json.dumps(_LEDGER))
    holes["shape"]["shards"]["names"] = ["1/2", "3/2"]
    holes_problems = shard_problems(holes, ci_text, verify_text)
    assert any("全划分" in p for p in holes_problems), (
        f"片名与规则值域对不上 ⇒ 必须报「不是全划分」，实际：{holes_problems}"
    )

    # ⑧ **只改第二片**那行的 `-n` ⇒ 必红（#6164 补的真退化：只比第一条 ⇒ 放走它）
    idx = verify_text.find("ci_helper_leg()")
    assert idx >= 0, "找不到本地腿函数（注入点漂移）"
    body = verify_text[idx:]
    matches = list(re.finditer(rf"-m\s+pytest\s+{re.escape(PYTEST_TARGET)}[^\n]*", body))
    assert len(matches) == 2, f"本地腿里现取到 {len(matches)} 条 pytest 行（应为 2）"
    second = matches[1]
    at = second.start() + second.group(0).rfind("-n 4")
    assert at > second.start(), f"第二条 pytest 行里找不到 `-n 4`：{second.group(0)!r}"
    second_only = verify_text[:idx] + body[:at] + "-n 8" + body[at + len("-n 4"):]
    assert pytest_argv_lines(second_only)[1] != pytest_argv_lines(verify_text)[1], "变异没命中第二片"
    assert any("第 2 条" in p or "条 pytest" in p for p in shard_problems(_LEDGER, ci_text, second_only)), (
        "只改第二片的 `-n` ⇒ 不报 ⇒ 并行度契约只钉住了两片中的一片（本包实测过的真退化）"
    )
