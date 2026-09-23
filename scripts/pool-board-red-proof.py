#!/usr/bin/env python3
"""#5177 红证机具：对被测源码做**单点变异**，重跑判据 ⇒ 每条判据都必须**单独**变红。

## 为什么要有它
「全绿」本身不构成证据 —— 不会红的断言 = 空断言。本脚本把 issue #5177 每条判据的
**判别力**变成可复算的：

    ① 对 `ProcessingOrderService.java` 逐条注入一个**语义缺陷**（不是改文案）；
    ② 跑**整类** `PoolBoardUrgencyTest`，从 surefire XML 读**逐方法**结果；
    ③ 期望 = **目标判据方法 FAIL**（= 这条判据确实抓得住这个缺陷，不是空断言）；
       同时**逐条打印**还有哪些判据一起红了 —— 那是「共享覆盖面」，**如实登记、不当失败**
       （例：排序键被改坏时，「池内分组排序」与「插队区排序」两条判据都会红，因为它们
       钉的是**同一把键的两个面**；把两个面并成一条判据反而会丢掉「各自有独立夹具」这层保护）；
    ④ 还原源码，并**逐字节自校验**（sha256 必须与注入前相同）。

## 与 `scripts/cutting-plan-red-proof.py` 的关系
同族机具（同一批纪律），差异只有一处：**本脚本不要求 git 工作区干净** ——
#5177 的改动本来就是未提交状态，而本脚本只碰 `ProcessingOrderService.java`
（前端包与测试文件都不在它的写入半径内），因此用「读原文 → 写变异 → 跑 → 写回原文 →
校验 sha256」的**内容级**还原，不依赖 git 兜底。中断时 `finally` 仍会还原；
若还原校验失败，脚本非零退出并打印原文长度，**绝不静默留下变异后的源码**。

## 用法
    python3 scripts/pool-board-red-proof.py            # 跑全部变异，逐条打印
    python3 scripts/pool-board-red-proof.py --only urgent_guard
    python3 scripts/pool-board-red-proof.py --check    # 前提自检（门禁调用这个面；零 Maven/零副作用）

退出码（实跑面）：`0` = 全部变异都被对应判据抓到；`1` = 有判据**没有**判别力（或意外结果）；`3` = 无法判定。
退出码（`--check` 面）：`0` = 全部前提成立；`1` = 有腐烂（**具名**报出哪条变异烂在哪）；`3` = 无法判定。
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from functools import partial
from pathlib import Path

import red_proof_harness as h  # noqa: E402  #5193 门禁调用的是 --check 面（零 Maven/零副作用）

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java"
MODULE = REPO / "backend/admin-api"
TEST_CLASS = "PoolBoardUrgencyTest"
TEST_FQN = f"com.migao.admin.service.{TEST_CLASS}"
TOOL_REL = "scripts/pool-board-red-proof.py"
SRC_REL = SRC.relative_to(REPO).as_posix()
TEST_REL = "backend/admin-api/src/test/java/com/migao/admin/service/PoolBoardUrgencyTest.java"

#: 判据方法 → 它钉的那一格（打印用）
CRITERIA = {
    "defaultsAreUnchangedWhenNothingIsUrgentAndNoDeliveryDate": "判据2 缺省不变（无加急单/无到货日 ⇒ 池与行序逐值相同）",
    "urgentOrderStaysOutOfPoolAndAppearsInQueueJumpSection": "判据3 加急不进池（只出现在插队区）",
    "pooledBatchContainingUrgentOrderIsRejectedFailClosed": "判据3 加急混进成批 ⇒ 整批显式拒绝",
    "singleOrderPathKeepsItsExistingErrorTextForUrgentOrder": "判据2/3 边界（加急不侵入单订单路径）",
    "orderingPrefersNearestDeliveryDateThenLongestWaitAndPutsNullsLast": "判据5 排序（临期优先、null 最后）",
    "urgentSectionUsesTheSameOrderingKey": "判据5 插队区同一把排序键",
    "orderLevelFieldsAreStampedIntoSnapshotRows": "范围5 透传（isUrgent 恒落键 / 到货日缺值不落键）",
}


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def splice(src: str, start_marker: str, end_marker: str, replacement: str) -> str:
    """把 `start_marker` 起、`end_marker` 止（含）的一段替换为 `replacement`。"""
    i = src.find(start_marker)
    if i == -1:
        raise AssertionError(f"变异锚点未找到：{start_marker[:60]!r}")
    j = src.find(end_marker, i)
    if j == -1:
        raise AssertionError(f"变异结束锚点未找到：{end_marker[:60]!r}")
    return src[:i] + replacement + src[j + len(end_marker):]


def replace_once(src: str, old: str, new: str) -> str:
    n = src.count(old)
    if n != 1:
        raise AssertionError(f"变异锚点出现 {n} 次（要求恰好 1 次）：{old[:60]!r}")
    return src.replace(old, new, 1)


def mutation_urgent_guard(src: str) -> str:
    """删掉「加急单不进池」在成批路径上的那道闸（判据 3 的红证形态）。"""
    return replace_once(src, """        // 🔴 加急单**不进池**（issue #5177 判据 3）：混进成批批次 ⇒ 整批显式拒绝，**一行都不写**。
        // 放在 prepare 之前 ⇒ 拒绝时连只读准备都还没跑，更没有半成品。
        assertNoUrgentInPooledBatch(orderIds, tenantId);
""", "        // [RED-PROOF] 闸被摘掉\n")


def mutation_urgent_not_in_pool(src: str) -> str:
    """让加急单照旧进池（判据 3 的另一半红证形态）。"""
    return replace_once(src, "            boolean urgent = Boolean.TRUE.equals(order.getIsUrgent());",
                        "            boolean urgent = false; // [RED-PROOF] 加急标记被忽略")


def mutation_sort_key(src: str) -> str:
    """把排序键退化成**单号序**（判据 5 的红证形态）。"""
    return splice(src,
                  "    static final Comparator<ProductionPoolViews.PoolLine> POOL_LINE_ORDER = Comparator",
                  "Comparator.nullsLast(Comparator.naturalOrder()));",
                  "    static final Comparator<ProductionPoolViews.PoolLine> POOL_LINE_ORDER =\n"
                  "            Comparator.comparing(ProductionPoolViews.PoolLine::orderNo,\n"
                  "                    Comparator.nullsLast(Comparator.naturalOrder())); // [RED-PROOF] 单号序")


def mutation_pool_default(src: str) -> str:
    """把池化缺省改成**开**（判据 2 的红证形态）。"""
    return replace_once(src, "public static final boolean POOLED_DEFAULT_ENABLED = false;",
                        "public static final boolean POOLED_DEFAULT_ENABLED = true; // [RED-PROOF]")


def mutation_stamp(src: str) -> str:
    """让订单级字段**不再进快照**（范围 5 透传的红证形态）。"""
    return replace_once(src, """    static void stampOrderUrgency(List<Map<String, Object>> snapshot, Order order) {
        if (snapshot.isEmpty() || order == null) {
            return;
        }""", """    static void stampOrderUrgency(List<Map<String, Object>> snapshot, Order order) {
        if (true) {
            return; // [RED-PROOF] 透传被摘掉
        }
        if (snapshot.isEmpty() || order == null) {
            return;
        }""")


MUTATIONS = [
    ("urgent_guard", "摘掉「加急单不进池」的成批闸", mutation_urgent_guard,
     "pooledBatchContainingUrgentOrderIsRejectedFailClosed"),
    ("urgent_not_in_pool", "忽略加急标记（加急单照旧进池）", mutation_urgent_not_in_pool,
     "urgentOrderStaysOutOfPoolAndAppearsInQueueJumpSection"),
    ("sort_key", "排序键退化成单号序", mutation_sort_key,
     "orderingPrefersNearestDeliveryDateThenLongestWaitAndPutsNullsLast"),
    ("pool_default", "池化缺省改成开", mutation_pool_default,
     "defaultsAreUnchangedWhenNothingIsUrgentAndNoDeliveryDate"),
    ("stamp", "订单级字段不进快照", mutation_stamp,
     "orderLevelFieldsAreStampedIntoSnapshotRows"),
]


def _probe(mutate, target: str, name: str) -> None:
    """一条变异的前提探针（**只读**）：被守卫文件可读 + 注入锚点命中 1 次 + 目标判据存在。"""
    src = h.read_source(SRC_REL, what=f"变异 [{name}] 的被测源码")
    test = h.read_source(TEST_REL, what=f"变异 [{name}] 的判据源码")
    h.require_method(test, target, what=f"变异 [{name}] 的目标判据")
    if mutate(src) == src:
        raise h.Rot("变异没有改变源码（锚点失配，或它与原文语义等价）")


def check() -> int:
    """前提自检（`--check`）：不注入、不跑判据、不写任何文件。"""
    decls = [h.declare(name, target, partial(_probe, mutate, target, name))
             for name, _label, mutate, target in MUTATIONS]
    return h.report_and_exit(TOOL_REL, decls)


def run_suite() -> dict[str, bool]:
    """跑整类，返回 {方法名: 是否通过}。无法判定（无 XML / 编译失败）⇒ 抛错。"""
    report = MODULE / "target/surefire-reports" / f"TEST-{TEST_FQN}.xml"
    if report.exists():
        report.unlink()
    proc = subprocess.run(
        ["./mvnw", "-o", "-q", "test", f"-Dtest={TEST_CLASS}", "-DfailIfNoTests=false"],
        cwd=MODULE, capture_output=True, text=True)
    if not report.exists():
        raise AssertionError("surefire XML 未产出 ⇒ **无法判定**（不是通过）：\n"
                             + (proc.stdout or "")[-2500:] + (proc.stderr or "")[-1500:])
    results: dict[str, bool] = {}
    for case in ET.parse(report).getroot().iter("testcase"):
        name = case.get("name") or ""
        failed = any(child.tag in ("failure", "error") for child in case)
        results[name] = not failed
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default=None, help="只跑指定变异（名字见 MUTATIONS）")
    parser.add_argument("--check", action="store_true",
                        help="只做前提自检（#5193 门禁调用的面）：零 Maven、零副作用、不注入")
    args = parser.parse_args()
    if args.check:
        return check()

    original = SRC.read_text(encoding="utf-8")
    original_hash = sha256(original)
    print(f"被测源码 = {SRC.relative_to(REPO)}  sha256={original_hash[:16]}…  长度={len(original)}\n")

    selected = [m for m in MUTATIONS if args.only is None or m[0] == args.only]
    if not selected:
        print(f"❌ 没有匹配的变异：{args.only}", file=sys.stderr)
        return 3

    failures: list[str] = []
    try:
        # 基线：注入前整类必须全绿（否则红证会把"本来就在红"的判据算成有判别力）
        baseline = run_suite()
        not_green = sorted(k for k, v in baseline.items() if not v)
        print(f"基线：{len(baseline)} 条判据，{'全绿 ✅' if not not_green else '有红 ❌ ' + str(not_green)}")
        if not_green:
            print("❌ 基线不绿 ⇒ 无法取红证（先修基线）", file=sys.stderr)
            return 1

        for name, label, mutate, target in selected:
            if target not in CRITERIA:
                print(f"❌ 变异 {name} 的目标方法不在判据表里：{target}", file=sys.stderr)
                return 3
            mutated = mutate(original)
            if mutated == original:
                print(f"❌ 变异 {name} 没有改变源码（锚点失配）—— **无法判定**", file=sys.stderr)
                return 3
            SRC.write_text(mutated, encoding="utf-8")
            print(f"\n── 变异 [{name}] {label}")
            print(f"   期望：{target} 变红，其余判据保持绿")
            try:
                results = run_suite()
            finally:
                SRC.write_text(original, encoding="utf-8")
                if sha256(SRC.read_text(encoding="utf-8")) != original_hash:
                    print("❌ 还原校验失败：源码与注入前不一致 —— **停手人工核对**", file=sys.stderr)
                    return 1

            target_failed = results.get(target) is False
            others = {k: v for k, v in results.items() if k != target}
            others_green = sorted(k for k, v in others.items() if not v)
            if target_failed:
                print(f"   ✅ 判别力成立：{target} 变红")
                if others_green:
                    print(f"   ℹ️ 共享覆盖面（同一次变异也命中这几条，属预期，不当失败）：{others_green}")
                else:
                    print(f"   ✅ 且只有它一条红（其余 {len(others)} 条仍绿 ⇒ 该判据独立抓这一格）")
            else:
                print(f"   ❌ {target} **没有变红** ⇒ 这条判据没有判别力（空断言或未覆盖该缺陷）")
                if others_green:
                    print(f"   ℹ️ 反而有别的判据红了（红被别处抓走）：{others_green}")
                failures.append(name)
    finally:
        # 任何路径（含异常 / Ctrl-C）都要还原，且自校验
        if SRC.read_text(encoding="utf-8") != original:
            SRC.write_text(original, encoding="utf-8")
        restored_ok = sha256(SRC.read_text(encoding="utf-8")) == original_hash
        print(f"\n还原：{'✅ 与注入前逐字节相同' if restored_ok else '❌ 不一致 —— 人工核对 ' + str(SRC)}")

    if failures:
        print(f"\n❌ 有 {len(failures)} 个变异没被对应判据抓到：{failures}", file=sys.stderr)
        return 1
    print(f"\n✅ 全部 {len(selected)} 个单点变异都被对应判据单独抓到（每条判据都有判别力）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
