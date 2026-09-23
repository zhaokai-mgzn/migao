#!/usr/bin/env python3
"""#5184 红证机具：对被测源码做**单点变异**，重跑判据 ⇒ 每条判据都必须**单独**变红。

## 为什么要有它
「全绿」本身不构成证据 —— 不会红的断言 = 空断言（`migao-acceptance` 的硬要求）。
本脚本把 issue #5184 各条判据的**判别力**变成可复算的：

    ① 对被测源码逐条注入一个**语义缺陷**（不是改文案，也不是改测试）；
    ② 跑**对应**的判据类（Java / 真库），从 surefire 报告读**逐方法**结果；
    ③ 期望 = **目标判据方法全部 FAIL/ERROR**（= 这条判据确实抓得住这个缺陷，不是空断言）；
    ④ 还原源码，并**逐字节自校验**（sha256 必须与注入前相同）—— 绝不静默留下变异后的源码。

## 与 `scripts/auto-batch-red-proof.py`（#5182）的关系
同族机具（同一批纪律、同一 `failed_methods` 口径）。差异：本脚本的变异点集中在**定时腿**
（载体 / 扫描服务 / 心跳面 / 复用的事件腿兜底段），且**要求 `expect` 里的每一条都变红**
（#5182 那份是「至少一条」）—— 因为本单的判据面更窄，宁可判定更严。

## 未实装（如实登记，§19.1）
**并发判据（PR-091）没有注入式红证**：它钉的是**库层闸门**（`selectActiveByOrderId` +
`uk_processing_orders_active` + `uk_batch_consumption_line`）。把闸门「拆掉」的变异是
**非确定的** —— `selectActiveByOrderId` 会在插入之前就把第二路短掉，于是同一个变异有时红、
有时绿，那种「红证」不构成证据。⇒ 该判据的判别力由真库用例的**不变量断言**（1 张加工单 /
1 笔扣减 / 余量只减一次）+ 既有 #5182 红证共同承担，此处**不假装**有一条注入式红证。

## 用法
    python3 scripts/auto-batch-due-scan-red-proof.py                 # 跑全部变异，逐条打印
    python3 scripts/auto-batch-due-scan-red-proof.py --only heartbeat
    python3 scripts/auto-batch-due-scan-red-proof.py --check         # 前提自检（门禁调用这个面）

退出码（实跑面）：`0` = 全部变异都被对应判据抓到；`1` = 有判据**没有**判别力（或意外结果）；
`3` = 无法判定（工作区不干净 / 找不到注入点）。
退出码（`--check` 面）：`0` = 全部前提成立；`1` = 有腐烂（**具名**）；`3` = 无法判定。
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from functools import partial
from pathlib import Path

import red_proof_harness as h  # noqa: E402  #5193 门禁调用的是 --check 面（零 Maven/零副作用）

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / "backend/admin-api"
SVC = "backend/admin-api/src/main/java/com/migao/admin/service/"
CFG = "backend/admin-api/src/main/java/com/migao/admin/config/"
UNIT = "AutoBatchDueScanServiceTest"
REALDB = "AutoBatchDueScanRealDbTest"

UNIT_FQN = f"com.migao.admin.service.{UNIT}"
REALDB_FQN = f"com.migao.admin.service.{REALDB}"
TOOL_REL = "scripts/auto-batch-due-scan-red-proof.py"
TEST_DIR = "backend/admin-api/src/test/java/com/migao/admin/service/"

#: 判据方法 → 它钉的那一格（打印用）
CRITERIA = {
    "defaultOffMeansZeroAction": "判据4 默认关（不启用 ⇒ 扫描腿零读零写）",
    "dueOrderIsDispatchedWithNoBusinessEvent": "判据1 到点自愈（无事件也派 + 痕迹 auto:due_scan）",
    "overdueButNotDueIsNotDispatched": "判据2 只查业务约束（超窗未到期 ⇒ 不派）",
    "scanOnlyChecksBusinessDueNotBatchConditions": "兜底不是第二主触发（不判优化条件）",
    "heartbeatIsVisibleOnTheActuatorHealthSurface": "判据5 心跳可见（/actuator/health details）",
    "tenantFailureDoesNotStopOthersAndContextIsRestored": "逐租户隔离 + 上下文还原（#3957）",
    "withoutTheBusinessDueJudgmentNothingIsEverDispatched": "PR-090 真库红证（停掉兜底 ⇒ 一张都不派）",
}

#: 每条变异：注入点（**源码原文**）+ 期望**全部**变红的判据方法 + 跑哪个类
MUTATIONS = [
    {
        "name": "default_off",
        "why": "把「缺省关 ⇒ 零动作」的闸拆掉（不启用也照扫、照记轮数）",
        "file": SVC + "AutoBatchDueScanService.java",
        "old": "        if (!processingOrderService.autoBatchPolicy().enabled()) {",
        "new": "        if (false) { // [RED-PROOF] 缺省关的闸被拆掉",
        "cls": UNIT, "fqn": UNIT_FQN,
        "expect": ["defaultOffMeansZeroAction"],
    },
    {
        "name": "no_business_due",
        "why": "去掉业务兜底判据（最晚派单日永不到期 ⇒ 该单永远不派）",
        "file": SVC + "ProcessingOrderService.java",
        "old": "            if (latest == null || today.isBefore(latest)) {\n                continue;\n            }",
        "new": "            if (true) { // [RED-PROOF] 兜底判据被去掉\n                continue;\n            }",
        "cls": UNIT, "fqn": UNIT_FQN,
        "expect": ["dueOrderIsDispatchedWithNoBusinessEvent"],
    },
    {
        "name": "window_as_deadline",
        "why": "把**池化窗口**（等待时长上限）当派单死线（用户逐字否掉的形态）",
        "file": SVC + "ProcessingOrderService.java",
        "old": "            if (latest == null || today.isBefore(latest)) {\n                continue;\n            }",
        "new": "            if (latest == null || (today.isBefore(latest) && !first.overdue())) {"
               "\n                continue;\n            } // [RED-PROOF] 用窗口当死线",
        "cls": UNIT, "fqn": UNIT_FQN,
        "expect": ["overdueButNotDueIsNotDispatched"],
    },
    {
        "name": "timer_dispatches_everything",
        "why": "定时腿改成「池里有什么派什么」（= 变成第二条主触发、不再只判业务约束）",
        "file": SVC + "ProcessingOrderService.java",
        "old": "            LocalDate latest = latestDispatchDate(first, policy.standardCycleDays());\n"
               "            if (latest == null || today.isBefore(latest)) {\n                continue;\n            }",
        "new": "            LocalDate latest = latestDispatchDate(first, policy.standardCycleDays());\n"
               "            if (false) { // [RED-PROOF] 定时腿见单就派\n                continue;\n            }",
        "cls": UNIT, "fqn": UNIT_FQN,
        "expect": ["scanOnlyChecksBusinessDueNotBatchConditions"],
    },
    {
        "name": "heartbeat_not_exposed",
        "why": "把心跳里的「最近成功时刻」从可观测面拿掉（停摆就再也看不出来）",
        "file": CFG + "AutoBatchDueScanHealthIndicator.java",
        "old": '        details.put("last_success_at", text(autoBatchDueScanService.getLastSuccessAt()));',
        "new": '        // [RED-PROOF] 最近成功时刻被拿掉',
        "cls": UNIT, "fqn": UNIT_FQN,
        "expect": ["heartbeatIsVisibleOnTheActuatorHealthSurface"],
    },
    {
        "name": "tenant_context_not_set",
        "why": "扫描时不给调度线程设租户上下文（#3957 的生产事故形态：整轮调度夭折）",
        "file": SVC + "AutoBatchDueScanService.java",
        "old": "                scanned++;\n                TenantContext.setTenantId(tenantId);\n                try {",
        "new": "                scanned++;\n                try { // [RED-PROOF] 租户上下文没设",
        "cls": UNIT, "fqn": UNIT_FQN,
        "expect": ["tenantFailureDoesNotStopOthersAndContextIsRestored"],
    },
    {
        "name": "realdb_no_business_due",
        "why": "同一条兜底判据在**真库**面上被去掉（无事件也不派 ⇒ 到点自愈不成立）",
        "file": SVC + "ProcessingOrderService.java",
        "old": "            if (latest == null || today.isBefore(latest)) {\n                continue;\n            }",
        "new": "            if (true) { // [RED-PROOF] 兜底判据被去掉（真库面）\n                continue;\n            }",
        "cls": REALDB, "fqn": REALDB_FQN,
        "expect": ["withoutTheBusinessDueJudgmentNothingIsEverDispatched"],
    },
]


def _probe(mut: dict) -> None:
    """一条变异的前提探针（**只读**）：注入点存在且唯一 + 目标判据方法存在。"""
    name = mut["name"]
    text = h.read_source(mut["file"], what=f"变异 [{name}] 的被测源码")
    h.require_anchor(text, mut["old"], what=f"变异 [{name}] 的注入锚点")
    test = h.read_source(f"{TEST_DIR}{mut['cls']}.java", what=f"变异 [{name}] 的判据源码")
    for method in mut["expect"]:
        h.require_method(test, method, what=f"变异 [{name}] 的期望判据")


def check() -> int:
    """前提自检（`--check`）：不注入、不跑判据、不写任何文件。"""
    decls = [h.declare(mut["name"], "、".join(mut["expect"]), partial(_probe, mut))
             for mut in MUTATIONS]
    return h.report_and_exit(TOOL_REL, decls)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_tests(fqn: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["./mvnw", "-o", "test", f"-Dtest={fqn.split('.')[-1]}", "-DfailIfNoTests=false"],
        cwd=MODULE, capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def report_of(fqn: str) -> str:
    path = MODULE / "target/surefire-reports" / f"{fqn}.txt"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def failed_methods(report: str) -> set[str]:
    return set(re.findall(r"^com\.migao\.admin\.service\.\w+\.(\w+) -- .*<<< (?:FAILURE|ERROR)!",
                          report, re.M))


def main() -> int:
    parser = argparse.ArgumentParser(description="#5184 红证机具（单点变异 ⇒ 逐条判据必须变红）")
    parser.add_argument("--only", help="只跑名字匹配的变异（子串）")
    parser.add_argument("--check", action="store_true",
                        help="只做前提自检（#5193 门禁调用的面）：零副作用、不注入")
    args = parser.parse_args()
    if args.check:
        return check()

    unknown = [m for mut in MUTATIONS for m in mut["expect"] if m not in CRITERIA]
    if unknown:
        print(f"❌ 判据方法名未登记（无法断言判别力）：{unknown}")
        return 3

    results = []
    for mutation in MUTATIONS:
        if args.only and args.only not in mutation["name"]:
            continue
        path = REPO / mutation["file"]
        original = path.read_text(encoding="utf-8")
        digest = sha256(original)
        if mutation["old"] not in original:
            print(f"❌ [{mutation['name']}] 注入点不存在（源码已漂移）：{mutation['file']}")
            results.append(False)
            continue
        if original.count(mutation["old"]) != 1:
            print(f"⚠️  [{mutation['name']}] 注入点出现 {original.count(mutation['old'])} 次"
                  f"（只替换第一处）")
        path.write_text(original.replace(mutation["old"], mutation["new"], 1), encoding="utf-8")
        try:
            code, output = run_tests(mutation["fqn"])
        finally:
            path.write_text(original, encoding="utf-8")
        restored = sha256(path.read_text(encoding="utf-8")) == digest
        if not restored:
            print(f"❌ [{mutation['name']}] 源码还原失败（sha256 不符）—— 停手，先人工核对")
            return 1
        reds = failed_methods(report_of(mutation["fqn"]))
        missing = [m for m in mutation["expect"] if m not in reds]
        if code == 0 and not reds:
            print(f"❌ [{mutation['name']}] 变异后**测试仍然全绿**（exit=0）—— "
                  f"判据没有判别力：{mutation['why']}")
            results.append(False)
            continue
        if missing:
            print(f"❌ [{mutation['name']}] 变异后变红的是 {sorted(reds) or '（没有方法级失败）'}"
                  f"，**未覆盖**目标判据 {missing} —— {mutation['why']}")
            if code != 0 and not reds:
                print("    （退出非 0 但无方法级失败：疑似编译失败 —— 末尾输出如下）")
                print("    " + "\n    ".join(output.strip().splitlines()[-8:]))
            results.append(False)
            continue
        print(f"✅ [{mutation['name']}] 判据有判别力：{mutation['why']}")
        for method in mutation["expect"]:
            print(f"     → 目标判据红：{method}（{CRITERIA[method]}）")
        shared = sorted(reds - set(mutation["expect"]))
        if shared:
            print(f"     （共享覆盖面，如实登记、不当失败：{shared}）")
        results.append(True)

    ok = all(results) and bool(results)
    print()
    print(f"{'✅ 全部变异都被对应判据抓到' if ok else '❌ 有判据没有判别力'}："
          f"{sum(1 for r in results if r)}/{len(results)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
