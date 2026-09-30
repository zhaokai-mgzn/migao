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
    return match.group(0).strip() if match else ""


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
    whole_suite = not (conftest._current_test_files()
                       - {(getattr(i, "nodeid", "") or "").split("::", 1)[0].rsplit("/", 1)[-1]
                          for i in session.items})
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
    if int(getattr(session, "testscollected", 0) or 0) < 100:
        pytest.skip("聚焦运行（收集面 ≪ 整套）⇒ 真钩子按「跑整套才判」早退，本形态判不了接线")
    assert callable(getattr(conftest, "pytest_sessionfinish", None)), (
        "收口钩子不存在 ⇒ 判定本体没人消费（#5825 踩过的形态）")
    # "短库存"必须**相对本轮真实收集数**构造：台账现在的冻结值（5767）已**低于** main 的
    # 现取收集数（别的包在长判据）⇒ 直接 +1 会构造出一个**根本不短**的库存，判据退化成空跑
    # （**实测**：本文件初版就是这么写的，全量里 `DID NOT RAISE`）。
    strict = json.loads(json.dumps(_LEDGER))
    strict["frozen_inventory"]["collected_total"] = int(session.testscollected) + 1
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
    strict["frozen_inventory"]["collected_total"] = int(session.testscollected) + 1000
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
    floor = int(_LEDGER["frozen_inventory"]["collected_total"])
    strict = json.loads(json.dumps(_LEDGER))
    strict["frozen_inventory"]["collected_total"] = floor + 1

    class _Item:
        def __init__(self, nodeid):
            self.nodeid = nodeid

    whole = sorted(conftest._current_test_files())

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
    floor = int(_LEDGER["frozen_inventory"]["collected_total"])
    frozen_skips = int(_LEDGER["frozen_inventory"]["skipped_reading"]["MIGAO_REQUIRE_REALDB"])

    class _Item:
        def __init__(self, nodeid):
            self.nodeid = nodeid

    whole = sorted(conftest._current_test_files())

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
