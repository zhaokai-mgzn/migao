#!/usr/bin/env python3
"""#5182 红证机具：对被测源码做**单点变异**，重跑判据 ⇒ 每条判据都必须**单独**变红。

## 为什么要有它
「全绿」本身不构成证据 —— 不会红的断言 = 空断言（`migao-acceptance` 的硬要求）。
本脚本把 issue #5182 十条判据里的**判别力**变成可复算的：

    ① 对被测源码逐条注入一个**语义缺陷**（不是改文案，也不是改测试）；
    ② 跑**对应**的判据类（Java / 真库），从 surefire 报告读**逐方法**结果；
    ③ 期望 = **目标判据方法 FAIL/ERROR**（= 这条判据确实抓得住这个缺陷，不是空断言）；
    ④ 还原源码，并**逐字节自校验**（sha256 必须与注入前相同）—— 绝不静默留下变异后的源码。

## 与 `scripts/pool-board-red-proof.py` 的关系
同族机具（同一批纪律）。差异：本脚本的变异点跨 5 个文件（服务 / 监听器 / 通知点 /
迁移基线 schema / 挂载点），故每条变异自带 `file`；且其中一条跑**真 PG** 类。

## 报告卫生（issue #5216）—— 为什么跑前必须 `unlink` 目标报告

判据读数取自 `target/surefire-reports/<fqn>.txt`，而该文件由 **Maven 在测试跑完后才重写**
⇒ 运行**被打断**（并发抢 `target`）或**编译失败**时它**保持上一次变异的内容**，
`failed_methods()` 于是读到**上一条变异**的方法级失败集 ⇒ 把环境事故读成
「这条变异被抓到 / 没抓到」。**红证机具的错误归因比没有红证更危险**：它会让人相信一条判据有判别力。
⇒ 两道卫生（与 `scripts/pool-board-red-proof.py` 同款，不新发明）：
① 跑测试前 `unlink` 目标报告；② 跑完**报告缺失 ⇒ 判「无法判定」（exit 3）** ——
既不回落读上一次内容，也不当成「通过」。

## 用法
    python3 scripts/auto-batch-red-proof.py                 # 跑全部变异，逐条打印
    python3 scripts/auto-batch-red-proof.py --only default_off
    python3 scripts/auto-batch-red-proof.py --check         # 前提自检（门禁调用这个面；零副作用）

退出码（实跑面）：`0` = 全部变异都被对应判据抓到；`1` = 有判据**没有**判别力（或意外结果）；
`3` = 无法判定（工作区不干净 / 找不到注入点 / **surefire 报告未产出**）。
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
UNIT = "AutoBatchDispatchTest"
MOUNT = "AutoBatchMountPointTest"
NOTIFIER = "PoolChangeNotifierTest"
LISTENER = "AutoBatchDispatchListenerTest"
REALDB = "AutoBatchDispatchRealDbTest"

UNIT_FQN = f"com.migao.admin.service.{UNIT}"
MOUNT_FQN = f"com.migao.admin.service.{MOUNT}"
NOTIFIER_FQN = f"com.migao.admin.service.{NOTIFIER}"
LISTENER_FQN = f"com.migao.admin.service.{LISTENER}"
REALDB_FQN = f"com.migao.admin.service.{REALDB}"
TOOL_REL = "scripts/auto-batch-red-proof.py"
TEST_DIR = "backend/admin-api/src/test/java/com/migao/admin/service/"

#: 判据方法 → 它钉的那一格（打印用）
CRITERIA = {
    "defaultOffDoesNothingAtAll": "判据1 默认关（缺省关 ⇒ 零读零写）",
    "batchingHappensOnTheEventEvenWhenNothingIsDue": "判据2 事件驱动（不靠计时器、也不是只在兜底扫描里）",
    "triggerChainHasNoTimerAndIsAnAfterCommitEventListener": "判据2 结构性（无 @Scheduled + AFTER_COMMIT）",
    "noConditionMetMeansNoDispatch": "判据3 都不满足 ⇒ 不派（条件不得恒真）",
    "businessDueForcesDispatchEvenWhenNoConditionIsMet": "判据4 兜底必派（算式面）",
    "urgentOrderIsNeverPooledAndIsDispatchedImmediately": "判据5 加急永不入池 + 立即派",
    "secondTriggerAfterDispatchDoesNothing": "判据7 幂等（重复触发不重复派）",
    "failuresAreRecordedAndLeaveAnIncidentTrail": "判据10 失败可查（留 incident 痕迹）",
    "confirmPaymentStillSucceedsWhenTheNotifierThrows": "判据1/10 挂载点 fail-soft（通知抛异常不影响主流程）",
    "notifySafelyNeverThrowsAndLeavesAnIncidentTrail": "判据10 通知点 fail-soft + 留痕（通知点自身）",
    "perOrderFailuresAndSuccessesBothLeaveTrails": "判据10 监听器留痕（失败 INCIDENT / 成功 TRACE）",
    "evaluationFailureIsSwallowedAndLeavesAnIncidentTrail": "判据10 监听器吞掉异常（AFTER_COMMIT 会逸出到确认支付那侧）",
    "confirmPaymentNotifiesAfterBusinessIsDone": "挂载点纪律（既有业务之后才通知）",
    "eventTriggeredBatchingLandsInTheRealLedger": "PR-088 真库落账 + 口径一致 + 幂等 + 对称回补",
    "businessDueForcesDispatchOfAPoolThatCanNeverFillABatch": "PR-089 真库兜底必派（不压单可证明）",
    "injectedSignAsymmetricConstraintMakesReversalFail": "PR-088 注入式红证（V121 修的符号不对称）",
}

#: 每条变异：注入点（**源码原文**）+ 期望**单独变红**的判据方法 + 跑哪个类
MUTATIONS = [
    {
        "name": "default_off",
        "why": "缺省改成「总是自动成批」",
        "file": SVC + "ProcessingOrderService.java",
        "old": "public static final boolean AUTO_BATCH_DEFAULT_ENABLED = false;",
        "new": "public static final boolean AUTO_BATCH_DEFAULT_ENABLED = true; // [RED-PROOF]",
        "cls": UNIT, "fqn": UNIT_FQN,
        "expect": ["defaultOffDoesNothingAtAll"],
    },
    {
        "name": "trigger_only_in_fallback",
        "why": "把主触发改成「只在兜底扫描里」（条件判定恒不成立 ⇒ 只有到期的单才会被派）",
        "file": SVC + "ProcessingOrderService.java",
        "old": "        if (demand.compareTo(policy.minBatchMeters()) >= 0) {",
        "new": "        if (false && demand.compareTo(policy.minBatchMeters()) >= 0) { // [RED-PROOF]",
        "cls": UNIT, "fqn": UNIT_FQN,
        "expect": ["batchingHappensOnTheEventEvenWhenNothingIsDue"],
    },
    {
        "name": "condition_always_true",
        "why": "成批条件恒真",
        "file": SVC + "ProcessingOrderService.java",
        "old": "        BigDecimal demand = StockQuantity.orZero(group.requiredMeters());\n        if (demand.signum() <= 0) {\n            return null;\n        }",
        "new": "        BigDecimal demand = StockQuantity.orZero(group.requiredMeters());\n        if (demand.signum() <= 0) {\n            return null;\n        }\n        if (true) { return \"[RED-PROOF] always\"; }",
        "cls": UNIT, "fqn": UNIT_FQN,
        "expect": ["noConditionMetMeansNoDispatch"],
    },
    {
        "name": "no_business_fallback",
        "why": "去掉业务兜底（最晚派单日永不到期）",
        "file": SVC + "ProcessingOrderService.java",
        "old": "            if (latest == null || today.isBefore(latest)) {\n                continue;\n            }",
        "new": "            if (true) { // [RED-PROOF] 兜底被去掉\n                continue;\n            }",
        "cls": UNIT, "fqn": UNIT_FQN,
        "expect": ["businessDueForcesDispatchEvenWhenNoConditionIsMet"],
    },
    {
        "name": "urgent_in_pool",
        "why": "让加急单参与池化（不再单独立即派）",
        "file": SVC + "ProcessingOrderService.java",
        "old": "            boolean urgent = Boolean.TRUE.equals(order.getIsUrgent());",
        "new": "            boolean urgent = false; // [RED-PROOF] 加急也入池",
        "cls": UNIT, "fqn": UNIT_FQN,
        "expect": ["urgentOrderIsNeverPooledAndIsDispatchedImmediately"],
    },
    {
        "name": "no_idempotency_guard",
        "why": "池不再排除已有活跃加工单的订单（幂等的第一道结构性保证被拆）",
        "file": SVC + "ProcessingOrderService.java",
        "old": "            if (order.getId() == null || dispatched.contains(order.getId())) {",
        "new": "            if (order.getId() == null) { // [RED-PROOF] 不排除已派单",
        "cls": UNIT, "fqn": UNIT_FQN,
        "expect": ["secondTriggerAfterDispatchDoesNothing"],
    },
    {
        "name": "silent_failure",
        "why": "把失败改成静默（不留 incident 痕迹）",
        "file": SVC + "AutoBatchDispatchListener.java",
        "old": "        if (!outcome.failures().isEmpty()) {\n            log.error(\"{} tenant={}, trigger={}, failedOrderIds={}, failures={}\",\n                    INCIDENT_AUTO_BATCH_FAILED, event.tenantId(), event.trigger(),\n                    outcome.failedOrderIds(), outcome.failures());\n        }",
        "new": "        // [RED-PROOF] 失败被静默",
        "cls": UNIT, "fqn": UNIT_FQN,
        "expect": ["failuresAreRecordedAndLeaveAnIncidentTrail"],
    },
    {
        "name": "notify_not_fail_soft",
        "why": "去掉通知点的 fail-soft（通知抛异常就逸出到主流程）",
        "file": SVC + "PoolChangeNotifier.java",
        "old": "        try {\n            if (notifier != null) {\n                notifier.notify(tenantId, trigger);\n            }\n        } catch (RuntimeException e) {",
        "new": "        try {\n            if (notifier != null) {\n                notifier.notify(tenantId, trigger);\n            }\n        } catch (UnsupportedOperationException e) { // [RED-PROOF] 不再吞 RuntimeException",
        "cls": MOUNT, "fqn": MOUNT_FQN,
        "expect": ["confirmPaymentStillSucceedsWhenTheNotifierThrows"],
    },
    {
        "name": "mount_point_removed",
        "why": "把确认支付上的通知点整句删掉（事件不再到达）",
        "file": SVC + "OrderService.java",
        "old": "        PoolChangeNotifier.notifySafely(poolChangeNotifier, order.getTenantId(),\n                PoolChangeNotifier.TRIGGER_ORDER_CONFIRMED);",
        "new": "        // [RED-PROOF] 通知点被删",
        "cls": MOUNT, "fqn": MOUNT_FQN,
        "expect": ["confirmPaymentNotifiesAfterBusinessIsDone"],
    },
    {
        "name": "notify_fail_soft_only_at_call_site",
        "why": "通知点自身不再 fail-soft（静态入口不再吞异常）",
        "file": SVC + "PoolChangeNotifier.java",
        "old": "        } catch (RuntimeException e) {\n            log.error(\"{} 池化通知点失败",
        "new": "        } catch (UnsupportedOperationException e) { // [RED-PROOF] 不再吞 RuntimeException\n            log.error(\"{} 池化通知点失败",
        "cls": NOTIFIER, "fqn": NOTIFIER_FQN,
        "expect": ["notifySafelyNeverThrowsAndLeavesAnIncidentTrail"],
    },
    {
        "name": "listener_does_not_swallow",
        "why": "监听器不再吞掉评估异常（AFTER_COMMIT 的异常会逸出到确认支付那侧）",
        "file": SVC + "AutoBatchDispatchListener.java",
        "old": "        } catch (RuntimeException e) {\n            log.error(\"{} tenant={}, trigger={}, error={}\",\n                    INCIDENT_AUTO_BATCH_FAILED, event.tenantId(), event.trigger(), e.toString(), e);\n            return;\n        }",
        "new": "        } catch (UnsupportedOperationException e) { // [RED-PROOF] 不再吞 RuntimeException\n            return;\n        }",
        "cls": LISTENER, "fqn": LISTENER_FQN,
        "expect": ["evaluationFailureIsSwallowedAndLeavesAnIncidentTrail"],
    },
    {
        "name": "constraint_sign_asymmetry",
        "why": "把 V121 修好的约束换回 V119 的符号不对称原文（真库基线 schema）",
        "file": "docs/sql/schema.sql",
        "old": "    CHECK (abs(planned_meters) <= abs(formula_meters) AND formula_meters * planned_meters >= 0);",
        "new": "    CHECK (planned_meters <= formula_meters AND formula_meters * planned_meters >= 0); -- [RED-PROOF]",
        "cls": REALDB, "fqn": REALDB_FQN,
        "expect": ["eventTriggeredBatchingLandsInTheRealLedger"],
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


class Undecidable(Exception):
    """surefire 报告未产出 ⇒ **无法判定**（issue #5216：既不是「抓到」、也不是「没抓到」）。"""


def report_path(fqn: str) -> Path:
    return MODULE / "target/surefire-reports" / f"{fqn}.txt"


def run_tests(fqn: str) -> tuple[int, str]:
    # 报告卫生①（issue #5216）：跑前删掉目标类的报告 —— 否则运行被打断（并发抢 target）或
    # 编译失败时，读到的是**上一次变异**留下的报告（同款做法见 scripts/pool-board-red-proof.py）。
    report = report_path(fqn)
    if report.exists():
        report.unlink()
    proc = subprocess.run(
        ["./mvnw", "-o", "test", f"-Dtest={fqn.split('.')[-1]}", "-DfailIfNoTests=false"],
        cwd=MODULE, capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def report_of(fqn: str) -> str:
    """报告卫生②（issue #5216）：**缺失 ⇒ 无法判定**，不回落读上一次内容、也不当成「通过」。"""
    path = report_path(fqn)
    if not path.exists():
        raise Undecidable(
            f"surefire 报告未产出（{path.relative_to(REPO)}）—— 疑似运行被打断 / 编译失败"
            f"（环境事故）⇒ **无法判定**：既不是「判据有判别力」，也不是「判据没有判别力」")
    return path.read_text(encoding="utf-8")


def failed_methods(report: str) -> set[str]:
    return set(re.findall(r"^com\.migao\.admin\.service\.\w+\.(\w+) -- .*<<< (?:FAILURE|ERROR)!",
                          report, re.M))


def main() -> int:
    parser = argparse.ArgumentParser(description="#5182 红证机具（单点变异 ⇒ 逐条判据必须变红）")
    parser.add_argument("--only", help="只跑名字匹配的变异（子串）")
    parser.add_argument("--check", action="store_true",
                        help="只做前提自检（#5193 门禁调用的面）：零副作用、不注入")
    args = parser.parse_args()
    if args.check:
        return check()

    unknown = [m["expect"][0] for m in MUTATIONS if m["expect"][0] not in CRITERIA]
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
        try:
            reds = failed_methods(report_of(mutation["fqn"]))
        except Undecidable as exc:
            print(f"❓ [{mutation['name']}] {exc}")
            print("    （末尾输出如下 —— 不得据此判「判据没有判别力」）")
            print("    " + "\n    ".join(output.strip().splitlines()[-8:]))
            return 3
        caught = [m for m in mutation["expect"] if m in reds]
        if code == 0 and not reds:
            # 编译失败 / 真库异常等 ⇒ 从输出里找线索，别当「通过」
            print(f"❌ [{mutation['name']}] 变异后**测试仍然全绿**（exit=0）—— "
                  f"判据没有判别力：{mutation['why']}")
            results.append(False)
            continue
        if not caught:
            print(f"❌ [{mutation['name']}] 变异后变红的是 {sorted(reds) or '（没有方法级失败）'}"
                  f"，**不含**目标判据 {mutation['expect']} —— {mutation['why']}")
            if code != 0 and not reds:
                print("    （退出非 0 但无方法级失败：疑似编译失败 —— 末尾输出如下）")
                print("    " + "\n    ".join(output.strip().splitlines()[-8:]))
            results.append(False)
            continue
        shared = sorted(reds - set(mutation["expect"]))
        print(f"✅ [{mutation['name']}] 判据有判别力：{mutation['why']}")
        for method in mutation["expect"]:
            print(f"     → 目标判据红：{method}"
                  f"（{CRITERIA.get(method, '')}）")
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
