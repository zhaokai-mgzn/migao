#!/usr/bin/env python3
"""#5159 红证驱动（后端真库）：对**实现源码**做单点变异 ⇒ 对应判据必须变红（然后原样恢复）。

判据自身没有判别力（改了实现也不红）= 空断言。本脚本逐条注入、逐条复跑、逐条恢复，
输出 `变异 → 预期红的用例 → 实测结果`。

## 🔴 先区分「跑起来了没有」再谈判别力（issue #5242，P1）

本脚本原来用 **`proc.returncode != 0`** 判「判据有判别力」—— 而**编译失败 / 环境事故同样 `rc != 0`**
（Maven 在编译期就退出时，测试**一行都没跑**）⇒ 事故被读成「变异被抓到了」。
**错误归因比没有红证更危险**：它让一条判据看起来有判别力，而实际上什么都没验证。

修法（与同族机具同款，不新发明）：
① **证据闸**：Maven 输出里必须出现「测试真的跑起来了」的证据（`BUILD SUCCESS` 或 `Tests run: N`）
   **才**进入判别力判定。⚠️ `-q` 会把这两样一起吞掉（实测：`-q` 下逐字节搜 `Tests run` /
   `BUILD SUCCESS` 在 125 行输出里**零命中**）⇒ 本脚本**不再带 `-q`** 跑 Maven
   （`cutting-plan-red-proof.py` 同款做法）；
② **判不出来就判「无法判定」**（`exit 3`，与 `#5216` / `#5193` 的三态同款语义），
   **不得**回落到「有判别力」；恢复后的复跑同样受这道闸约束（否则编译失败会被读成「恢复不干净」）。

同族对照：`auto-batch-red-proof.py` / `auto-batch-due-scan-red-proof.py` 走 **surefire 报告面**
（跑前 `unlink` + 报告缺失 ⇒ 无法判定，`#5216`）；`pool-board-red-proof.py` 同理；
`cutting-plan-red-proof.py` 走 **stdout 面**（缺 `BUILD SUCCESS` ⇒ fail-closed）。本脚本走 stdout 面。

## 用法
    python3 scripts/saving-metrics-red-proof-backend.py           # 实跑（需 Maven + JDK + PG 二进制）
    python3 scripts/saving-metrics-red-proof-backend.py --check   # 前提自检（门禁调用的面；零副作用）

退出码（实跑面）：`0` = 全部变异都被对应判据抓到且恢复后全绿；`1` = 有判据没有判别力 / 恢复不干净；
`3` = 无法判定（编译失败 / 环境事故 ⇒ 既不是「有判别力」也不是「没有判别力」）。
退出码（`--check` 面）：`0` = 全部前提成立；`1` = 有腐烂（**具名**）；`3` = 无法判定。
"""
import pathlib
import re
import shutil
import subprocess
import sys
from functools import partial

import red_proof_harness as h  # noqa: E402  #5193 门禁调用的是 --check 面（零 Maven/零副作用）

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAPPER = ROOT / "backend/admin-api/src/main/java/com/migao/admin/mapper/StockBatchConsumptionMapper.java"
DTO = ROOT / "backend/admin-api/src/main/java/com/migao/admin/dto/SavingMetricViews.java"
SVC = ROOT / "backend/admin-api/src/main/java/com/migao/admin/service/StockBatchConsumptionService.java"
TOOL_REL = "scripts/saving-metrics-red-proof-backend.py"
TEST_DIR = "backend/admin-api/src/test/java/com/migao/admin/service/"

MUTATIONS = [
    (
        "判据1 汇总一致：金额改成「整段求和再取整」（= 第二套口径）",
        MAPPER,
        "SUM(ROUND((c.formula_meters - c.planned_meters) * c.unit_cost, 2))",
        "ROUND(SUM((c.formula_meters - c.planned_meters) * c.unit_cost), 2)",
        "SavingMetricsBoardRealDbTest#boardTotalsEqualPerLineSum",
    ),
    (
        "判据2 存量单列：把 opening 并进 purchase（历史包袱混入切换后）",
        DTO,
        '        if (COHORT_OPENING.equals(source)) {\n            return COHORT_OPENING;\n        }\n',
        "",
        "SavingMetricsBoardRealDbTest#openingCohortIsListedSeparately",
    ),
    (
        "判据3 空数据：占比在分母为 0 时回落成 0（冒充「没有浪费」）",
        SVC,
        "        return total == 0 ? null\n",
        "        return total == 0 ? BigDecimal.ZERO\n",
        "SavingMetricsBoardRealDbTest#emptyTenantReturnsNoDataNotZero",
    ),
    (
        "判据5 单价口径：金额改读批次**现价**（而不是行内快照）",
        MAPPER,
        "(c.formula_meters - c.planned_meters) * c.unit_cost",
        "(c.formula_meters - c.planned_meters) * b.unit_cost",
        "SavingMetricsBoardRealDbTest#snapshotCostAndNoCustomerRegression",
    ),
    (
        "判据3 粒度：未知粒度静默回落 month（不显式拒绝）",
        SVC,
        '            default -> throw new BusinessException(ERR_GRANULARITY_UNKNOWN,\n'
        '                    String.format("未知的时间粒度：%s", raw), 400,\n'
        '                    String.format("可选值：%s（按月，YYYY-MM）/ %s（按 ISO 周，YYYY-Www）",\n'
        "                            SavingMetricViews.GRANULARITY_MONTH, SavingMetricViews.GRANULARITY_WEEK));\n",
        "            default -> SavingMetricViews.GRANULARITY_MONTH;\n",
        "SavingMetricsBoardRealDbTest#granularityIsValidatedAndWeekUsesIsoWeek",
    ),
]


def _probe(path, old: str, test: str, title: str) -> None:
    """一条变异的前提探针（**只读**）：注入锚点命中 1 次 + 目标判据方法存在。"""
    rel = path.relative_to(ROOT).as_posix()
    h.require_anchor(h.read_source(rel, what=f"变异 [{title}] 的被测源码"), old,
                     what=f"变异 [{title}] 的注入锚点")
    cls, method = test.split("#")
    h.require_method(h.read_source(f"{TEST_DIR}{cls}.java", what=f"变异 [{title}] 的判据源码"),
                     method, what=f"变异 [{title}] 的目标判据")


def check() -> int:
    """前提自检（`--check`）：不注入、不跑判据、不写任何文件。"""
    decls = [h.declare(title, test, partial(_probe, path, old, test, title))
             for title, path, old, _new, test in MUTATIONS]
    return h.report_and_exit(TOOL_REL, decls)


def run_evidence(out: str):
    """本次 Maven 调用「**测试真的跑起来了**」的证据；`None` = 没跑起来（⇒ **无法判定**）。

    issue #5242：编译失败 / 环境事故**同样** `rc != 0`，而那时测试一行都没跑 ——
    只看退出码会把事故读成「变异被抓到了」（**错误归因比没有红证更危险**）。
    与同族机具同款判据：`cutting-plan-red-proof.py` 缺 `BUILD SUCCESS` ⇒ fail-closed。
    """
    if "BUILD SUCCESS" in out:
        return "BUILD SUCCESS"
    match = re.search(r"Tests run: \d+", out)
    return match.group(0) if match else None


def run(test):
    # ⚠️ **不带 `-q`**（issue #5242）：`-q` 会把 `BUILD SUCCESS` 与 `Tests run: N` 一起吞掉
    # （实测零命中）⇒ 证据闸永远取不到证据 ⇒ 会把正常路径也判成「无法判定」。
    proc = subprocess.run(
        ["./mvnw", "-o", "test", "-Dtest=" + test, "-DfailIfNoTests=false"],
        cwd=ROOT / "backend/admin-api", capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    tail = "\n".join(
        line for line in proc.stdout.splitlines()
        if "Tests run" in line or "AssertionFailedError" in line or "expected" in line
        or "but was" in line or "ERROR]   " in line)
    return proc.returncode, tail, out


def main():
    if "--check" in sys.argv:
        sys.exit(check())
    failures = []
    for title, path, old, new, test in MUTATIONS:
        original = path.read_text(encoding="utf8")
        try:
            if old not in original:
                print(f"❌ 注入点失配（脚本本身坏了，不是判据红）：{title}")
                failures.append(title)
                continue
            # 变异：write_text 会把 mtime 刷新到「现在」⇒ Maven 增量编译一定会重编
            path.write_text(original.replace(old, new, 1), encoding="utf8")
            rc, tail, out = run(test)
            # 🔴 issue #5242 的证据闸：**先区分跑起来了没有，再谈判别力**。
            # 拿不到证据（编译失败 / 环境事故）⇒ 三态里的「无法判定」，**不得**回落到「有判别力」。
            if run_evidence(out) is None:
                print(f"❓ 无法判定（编译失败 / 环境事故 ⇒ 测试一行都没跑）"
                      f" | {title} | {test} | rc={rc}", flush=True)
                print("    （末尾输出如下 —— 不得据此判「判据有判别力」）", flush=True)
                print("    " + "\n    ".join(out.strip().splitlines()[-8:]), flush=True)
                sys.exit(h.UNKNOWN)
            red = rc != 0
            print(f"{'✅ 红（判据有判别力）' if red else '❌ 绿（空断言！）'} | {title} | {test} | rc={rc}",
                  flush=True)
            print(f"      跑起来了（证据：{run_evidence(out)}）", flush=True)
            if red and tail:
                print("      实测红读数: " + tail.replace("\n", " | ")[:400], flush=True)
            if not red:
                failures.append(title)
        finally:
            # 恢复也用 write_text（**不用 copy2**：copy2 会还原旧 mtime ⇒ Maven 增量编译
            # 认为「没变」⇒ 变异后的 class 留在 target 里，后续判据测的是变异体 —— 本脚本
            # 第一版就踩了这个坑：第 4 条因此假绿、最后一条全量复跑假红）
            path.write_text(original, encoding="utf8")
    print("\n=== 恢复后复跑全量（必须全绿）===", flush=True)
    rc, tail, out = run("SavingMetricsBoardRealDbTest")
    if run_evidence(out) is None:
        # issue #5242：这里的形态与上面同源 —— 编译失败同样 rc != 0，
        # 若不加闸就会被读成「恢复不干净」（错误归因），而真相是「这次根本没跑」。
        print(f"❓ 无法判定（恢复后复跑没跑起来：编译失败 / 环境事故）rc={rc}", flush=True)
        print("    " + "\n    ".join(out.strip().splitlines()[-8:]), flush=True)
        sys.exit(h.UNKNOWN)
    print(f"恢复后 rc={rc} ({'全绿' if rc == 0 else '仍有红 ⇒ 恢复不干净'}）{tail}")
    if failures or rc != 0:
        sys.exit(1)


main()
