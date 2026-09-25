#!/usr/bin/env python3
"""#5193 红证机具的**前提自检**（腐烂探测器）—— 零 Maven / 零 npm / 零 PG / 零副作用。

## 它治什么

六个红证机具（`scripts/*-red-proof.py`）此前**没有任何 CI/门禁调用** ⇒ 只能靠人手跑
⇒ 它们会**静默腐烂**：被测源码一重构，注入锚点（源码原文片段）就对不上；判据方法一改名，
「期望变红」的目标就不存在 —— 而**没有任何东西会因此变红**。腐烂后只有两种结局：
① 机具报「注入点不存在 ⇒ 无法判定」；② 更糟 —— 「这条判据没有判别力」被读成产品问题，
排查方向被带偏。

## 三个面（同一个机具，一个入口）

* **前提自检 `--check`**（本模块）：逐条变异核对前提 —— 被守卫文件可读 / 注入锚点命中**恰好 1 次** /
  期望判据方法**存在** / 变异**真的改变了源码**；并核对**登记表** `TOOLS`（声明条数**只许增**，
  删掉一条变异 = 机具被削弱 ⇒ 红）。**只读**，不写任何文件。
* **实跑**（机具本来的行为，不带 `--check`）：真注入 + 真跑判据 + 逐条核对「该条红、其余绿」。
  入口 `./verify-all.sh redproof`（需 JDK / npm / PG 二进制）。
* **统一报告行**：`前提自检：跑了 N 条 / 未跑 M 条（腐烂）｜实跑未跑 K 条（原因：需 <heavy>；入口 …）`
  —— 「没跑」必须长得像「没跑」（`migao-acceptance`：绿 ≠ 跑过）。

## 三态退出码（不许把「没跑」写成「通过」）

`0` = 全部声明的前提成立；`1` = 有腐烂（**具名报出**是哪一条变异、烂在哪）；`3` = 无法判定
（该机具没有任何可自检的声明）。

## 边界（如实登记，`migao-dev-flow` §19.1）

本自检**只覆盖「前提能否成立」这一层**。**「变异是否与实现语义等价」（= 跑了也不红）只能靠实跑
发现** —— 实证：`cutting-plan` 第一版 M4 与正确实现**语义等价**、恒绿；`saving-metrics` 的
mvn 增量编译假绿。故本模块**不假装**覆盖那一层；那一层由 `./verify-all.sh redproof` 承担，
各机具 `heavy` 文案里带**实测耗时**。

**并发假红（实测登记）**：`--check` 读的是**工作区原文** ⇒ 与**实跑**并发时，会把「实跑刚注入
进源码的那个变异」读成「腐烂」（实证：`cutting-plan` 跑 M5 期间，另一进程 `--check` 报
「M5 锚点命中 0 次」，而 `origin/main` 原文里该锚点命中 **1** 次 ⇒ 纯并发假红）。
`./verify-all.sh redproof` 内部**先前提自检、后实跑**（串行）⇒ 自身不会撞；CI 不跑实跑 ⇒ 也不会撞。
本机手工并发时请等实跑结束再定论。
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[1]

OK, ROT, UNKNOWN = 0, 1, 3

_AAPI_MAIN = "backend/admin-api/src/main/java/com/migao/admin/"
_AAPI_TEST = "backend/admin-api/src/test/java/com/migao/admin/"


@dataclass(frozen=True)
class ToolSpec:
    """一个机具的**登记面**：门禁 / 守卫需要知道的全部元数据（单一事实源）。

    * `floor`：声明的变异条数**下限（只许增）**。为什么需要：门禁调用的是 `--check` 面 ⇒
      若有人把某条变异从机具里**删掉**，前提自检照样全绿（「没有声明」=「没有可腐烂的东西」）
      ⇒ 机具被**静默削弱**。声明数低于登记 ⇒ 红。**加**变异不必改这里（加覆盖不是削弱），
      但请把新条目的**实跑耗时**补进 `heavy`（成本要可算，#5193 判据 2）。
    * `heavy`：实跑需要什么 + 实测耗时（打印给「实跑未跑」当原因）。
    * `impl` / `criteria`：被守卫的**被测源码** / 「期望变红」的**判据源码** ——
      守卫测试按它们注入腐烂（改名、标识符置换、删变异），证明 `--check` **真的会红**。
    """

    floor: int
    heavy: str
    impl: tuple[str, ...] = ()
    criteria: tuple[str, ...] = ()


TOOLS: dict[str, ToolSpec] = {
    "scripts/order-urgency-red-proof.py": ToolSpec(
        floor=5,
        heavy="Maven + JDK（admin-api 单测；5 条变异实测 570s≈9.5min）",
        impl=(_AAPI_MAIN + "service/OrderService.java",
              _AAPI_MAIN + "dto/OrderDetailResponse.java"),
        criteria=(_AAPI_TEST + "service/OrderUrgencyFieldsTest.java",),
    ),
    "scripts/pool-board-red-proof.py": ToolSpec(
        # issue #5550 新增 pi_null_guard（存量行 NPE 形态）⇒ 下限随声明**同批抬高**（只许增）
        floor=6,
        heavy="Maven + JDK（admin-api 单测；6 条变异实测 119s）",
        impl=(_AAPI_MAIN + "service/ProcessingOrderService.java",),
        criteria=(_AAPI_TEST + "service/PoolBoardUrgencyTest.java",),
    ),
    "scripts/cutting-plan-red-proof.py": ToolSpec(
        floor=5,
        heavy="Maven + JDK（admin-api 单测，逐条判据强制重编译；5 条变异 × 7 条判据实测 1762s≈29min）",
        impl=(_AAPI_MAIN + "service/CuttingPlanCalculator.java",),
        criteria=(_AAPI_TEST + "service/CuttingPlanCalculatorTest.java",),
    ),
    "scripts/auto-batch-red-proof.py": ToolSpec(
        floor=12,
        heavy="Maven + JDK + PG 二进制（含 1 条真库判据；12 条变异实测 807s≈13min）",
        impl=(
            _AAPI_MAIN + "service/ProcessingOrderService.java",
            _AAPI_MAIN + "service/AutoBatchDispatchListener.java",
            _AAPI_MAIN + "service/PoolChangeNotifier.java",
            _AAPI_MAIN + "service/OrderService.java",
            "backend/admin-api/src/main/resources/db/init/schema.sql",
        ),
        criteria=(
            _AAPI_TEST + "service/AutoBatchDispatchTest.java",
            _AAPI_TEST + "service/AutoBatchMountPointTest.java",
            _AAPI_TEST + "service/PoolChangeNotifierTest.java",
            _AAPI_TEST + "service/AutoBatchDispatchListenerTest.java",
            _AAPI_TEST + "service/AutoBatchDispatchRealDbTest.java",
        ),
    ),
    "scripts/auto-batch-due-scan-red-proof.py": ToolSpec(
        floor=7,
        heavy="Maven + JDK + PG 二进制（含 1 条真库判据；7 条变异实测 272s）",
        impl=(
            _AAPI_MAIN + "service/AutoBatchDueScanService.java",
            _AAPI_MAIN + "service/ProcessingOrderService.java",
            _AAPI_MAIN + "config/AutoBatchDueScanHealthIndicator.java",
        ),
        criteria=(
            _AAPI_TEST + "service/AutoBatchDueScanServiceTest.java",
            _AAPI_TEST + "service/AutoBatchDueScanRealDbTest.java",
        ),
    ),
    "scripts/saving-metrics-red-proof-backend.py": ToolSpec(
        floor=5,
        heavy="Maven + JDK + PG 二进制（真库判据；5 条变异实测 178s）",
        impl=(
            _AAPI_MAIN + "mapper/StockBatchConsumptionMapper.java",
            _AAPI_MAIN + "dto/SavingMetricViews.java",
            _AAPI_MAIN + "service/StockBatchConsumptionService.java",
        ),
        criteria=(_AAPI_TEST + "service/SavingMetricsBoardRealDbTest.java",),
    ),
    "scripts/saving-metrics-red-proof-web.py": ToolSpec(
        floor=5,
        heavy="node + npm（admin-web 依赖；5 条变异实测 12s）",
        impl=(
            "frontend/admin-web/src/lib/saving-board.ts",
            "frontend/admin-web/src/app/(dashboard)/production/saving-board/page.tsx",
        ),
        criteria=(
            "frontend/admin-web/tests/unit/components/SavingBoard.test.tsx",
            "frontend/admin-web/tests/unit/lib/saving-board.test.ts",
        ),
    ),
    "scripts/product-batch-red-proof.py": ToolSpec(
        floor=4,
        heavy="Maven + JDK（admin-api 单测；4 条变异 + 基线实测 189s）",
        impl=(_AAPI_MAIN + "service/AgentBatchService.java",),
        criteria=(_AAPI_TEST + "service/AgentBatchServiceTest.java",),
    ),
    "scripts/agent-batch-tenant-red-proof.py": ToolSpec(
        floor=5,
        heavy="Maven + JDK + PG 二进制（**真库判据**：一次性 initdb + pg_ctl 集群；5 条变异 + 基线实测 183s）",
        impl=(
            _AAPI_MAIN + "config/MybatisPlusConfig.java",
            _AAPI_MAIN + "service/AgentBatchService.java",
            "backend/admin-api/src/main/resources/db/init/schema.sql",
        ),
        criteria=(_AAPI_TEST + "service/AgentBatchCrossTenantRealDbTest.java",),
    ),
}


class Rot(Exception):
    """机具前提已腐烂 ⇒ 该条变异当下取不出红证（**不是**「通过」）。"""


@dataclass(frozen=True)
class Declaration:
    """一条变异的**声明面**：它叫什么、期望哪条判据变红、前提是否还成立。"""

    name: str
    target: str
    ok: bool
    detail: str = ""


# ── 前提探针（全部只读、零副作用）────────────────────────────────────────────

def read_source(rel: str, *, what: str) -> str:
    """读仓库内的被守卫文件；不存在 ⇒ 腐烂（被守卫的对象都没了，红证必然取不出来）。"""
    path = REPO / rel
    if not path.is_file():
        raise Rot(f"{what}：被守卫的文件不存在（{rel}）")
    return path.read_text(encoding="utf-8")


def require_anchor(text: str, anchor: str, *, what: str) -> None:
    """注入锚点必须在当前源码里命中**恰好 1 次**（0 次 = 源码漂移；>1 次 = 注入不确定）。"""
    n = text.count(anchor)
    if n != 1:
        raise Rot(f"{what}：注入锚点命中 {n} 次（须恰好 1 次）—— 被测源码已漂移，"
                  f"机具需重取锚点：{anchor[:70]!r}")


def require_method(text: str, method: str, *, what: str) -> None:
    """「期望变红」的判据方法必须真的存在 —— 否则该变异**永远红不了**（假绿证）。"""
    if not re.search(rf"(?<![\w.]){re.escape(method)}\s*\(", text):
        raise Rot(f"{what}：判据方法 {method} 在判据源码里找不到 —— 判据已改名/删除，"
                  f"该变异的「期望变红」目标不存在")


def require_file(rel: str, *, what: str) -> None:
    if not (REPO / rel).is_file():
        raise Rot(f"{what}：{rel} 不存在")


def declare(name: str, target: str, probe: Callable[[], None]) -> Declaration:
    """跑一条变异的前提探针。`probe()` **只读**；失败即抛 `Rot` / `AssertionError`。

    ⚠️ 探针**绝不**把变异写进源码 —— 那是实跑面（`./verify-all.sh redproof`）的事。
    """
    try:
        probe()
    except (Rot, AssertionError) as exc:
        return Declaration(name, target, False, str(exc) or exc.__class__.__name__)
    return Declaration(name, target, True)


# ── 报告 + 三态退出码 ────────────────────────────────────────────────────────

def counts_line(ok: int, bad: int, total: int, heavy: str) -> str:
    """统一报告行（守卫 `tests/unit_ci_workflows/test_redproof_harness_gate.py` 按它解析）。"""
    return (f"前提自检：跑了 {ok} 条 / 未跑 {bad} 条（腐烂）｜"
            f"实跑未跑 {total} 条（原因：需 {heavy}；入口 ./verify-all.sh redproof）")


def report_and_exit(tool: str, declarations: list[Declaration]) -> int:
    spec = TOOLS.get(tool)
    print(f"🔎 {tool} 前提自检（零 Maven/npm/PG，无副作用）")
    if spec is None:
        print(f"❌ 未登记：{tool} 不在 scripts/red_proof_harness.py 的 TOOLS 登记表里 ⇒ "
              f"门禁不知道它该有多少条变异，**无法判定它有没有被削弱**。"
              f"处置：在 TOOLS 里登记 floor / heavy / impl / criteria。")
        return ROT
    if spec.impl or spec.criteria:
        print("  被守卫对象：" + "、".join(spec.impl))
        print("  判据源码：" + "、".join(spec.criteria))
    if not declarations:
        print(f"❓ 无法判定：{tool} 没有声明任何可自检的变异（登记下限 {spec.floor} 条）")
        print(counts_line(0, 0, spec.floor, spec.heavy))
        return UNKNOWN
    for d in declarations:
        suffix = "" if d.ok else f"｜腐烂：{d.detail}"
        print(f"  {'✅' if d.ok else '❌'} [{d.name}] → 期望变红：{d.target}{suffix}")
    ok = sum(1 for d in declarations if d.ok)
    bad = len(declarations) - ok
    weakened = len(declarations) < spec.floor
    print(f"  登记表：声明 {len(declarations)} 条 / 登记下限 {spec.floor} 条"
          + ("✅" if not weakened else "❌ **有机具被削弱**（删掉变异 = 覆盖变少）"))
    print(counts_line(ok, bad, len(declarations), spec.heavy))
    if weakened:
        return ROT
    return ROT if bad else OK


def _self_test() -> int:
    """本模块自身的极小自检：三态 + 报告行可被解析（供 `--self-test`）。"""
    good = declare("probe_ok", "t", lambda: None)
    bad = declare("probe_rot", "t", lambda: require_anchor("abc", "zzz", what="夹具"))
    assert good.ok, "前提探针在无反例时应成立"
    assert not bad.ok, f"腐烂探针必须报出：{bad!r}"
    assert "命中 0 次" in bad.detail, f"腐烂原因必须具名：{bad.detail!r}"
    assert counts_line(1, 1, 2, "夹具").startswith("前提自检：跑了 1 条 / 未跑 1 条（腐烂）")
    assert set(TOOLS) >= {"scripts/pool-board-red-proof.py"}, "登记表不得为空"
    print("✅ red_proof_harness 自检：三态与报告行形态成立")
    return OK


def main() -> int:
    if "--self-test" in sys.argv[1:]:
        return _self_test()
    print("用法：本模块由各红证机具 import 使用（机具入口 = `python3 scripts/<机具> --check`）；"
          "`--self-test` 跑本模块自身自检（三态 + 报告行形态）。")
    return UNKNOWN


if __name__ == "__main__":
    sys.exit(main())
