#!/usr/bin/env python3
"""#5159 红证驱动（后端真库）：对**实现源码**做单点变异 ⇒ 对应判据必须变红（然后原样恢复）。

判据自身没有判别力（改了实现也不红）= 空断言。本脚本逐条注入、逐条复跑、逐条恢复，
输出 `变异 → 预期红的用例 → 实测结果`。
"""
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAPPER = ROOT / "backend/admin-api/src/main/java/com/migao/admin/mapper/StockBatchConsumptionMapper.java"
DTO = ROOT / "backend/admin-api/src/main/java/com/migao/admin/dto/SavingMetricViews.java"
SVC = ROOT / "backend/admin-api/src/main/java/com/migao/admin/service/StockBatchConsumptionService.java"

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


def run(test):
    proc = subprocess.run(
        ["./mvnw", "-o", "-q", "test", "-Dtest=" + test, "-DfailIfNoTests=false"],
        cwd=ROOT / "backend/admin-api", capture_output=True, text=True)
    tail = "\n".join(
        line for line in proc.stdout.splitlines()
        if "Tests run" in line or "AssertionFailedError" in line or "expected" in line
        or "but was" in line or "ERROR]   " in line)
    return proc.returncode, tail


def main():
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
            rc, tail = run(test)
            red = rc != 0
            print(f"{'✅ 红（判据有判别力）' if red else '❌ 绿（空断言！）'} | {title} | {test} | rc={rc}",
                  flush=True)
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
    rc, tail = run("SavingMetricsBoardRealDbTest")
    print(f"恢复后 rc={rc} ({'全绿' if rc == 0 else '仍有红 ⇒ 恢复不干净'}）{tail}")
    if failures or rc != 0:
        sys.exit(1)


main()
