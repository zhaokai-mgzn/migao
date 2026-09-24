#!/usr/bin/env python3
"""#5314 红证机具（服务端包）：对批量更新服务做**单点变异**，重跑判据 ⇒ 每条判据都必须**单独**变红。

## 为什么要有它

「测试全绿」本身不构成证据 —— 不会红的断言 = 空断言。本脚本把 issue #5314 契约里
服务端那半边的每一条判据的**判别力**变成可复算的：

    ① 对 `AgentBatchService.java` 逐条注入一个**语义缺陷**（不是改文案）；
    ② 跑**整类** `AgentBatchServiceTest`，从 surefire XML 读**逐方法**结果；
    ③ 期望 = **目标判据方法 FAIL**（= 这条判据确实抓得住这个缺陷）；
       同时**逐条打印**还有哪些判据一起红了 —— 那是「共享覆盖面」，**如实登记、不当失败**；
    ④ 还原源码，并按 **sha256 内容指纹**自证与注入前逐字节相同。

## 四条变异各自钉的契约条款

| 变异 | 注入的缺陷 | 期望变红的判据 |
|---|---|---|
| `old_value_persistence` | 预览不再持久化 `old_value`（撤销依据丢失） | `persistsPreviewWithOldValueCollectedFromDb` |
| `revert_uses_new_value` | 撤销写回 `newValue`（而不是持久化的 `old_value`） | `revertRestoresPersistedOldValuePerItem` |
| `abort_whole_batch` | 单条失败即中断整批（破坏「部分失败逐条报告、不做整体回滚」） | `reportsPartialFailurePerItemWithoutRollback` |
| `drop_revert_guards` | 摘掉「不可撤销」的两道闸（状态非 done/partial、或已 reverted） | `alreadyRevertedBatchIsNotRevertibleAgain` |

🔴 **`old_value` 的两条变异合起来才是完整链条**：① 证明「预览阶段不落 old_value ⇒ 判据红」，
② 证明「撤销不用落库的那份 old_value ⇒ 判据红」。任一条单独都只覆盖链条的一半。

## 用法

    python3 scripts/product-batch-red-proof.py            # 跑全部变异（真注入 + 真跑判据）
    python3 scripts/product-batch-red-proof.py --only old_value_persistence
    python3 scripts/product-batch-red-proof.py --check    # 前提自检（门禁调用这个面；零 Maven/零副作用）

退出码（实跑面）：`0` = 全部变异都被对应判据抓到；`1` = 有判据**没有**判别力（或意外结果）；`3` = 无法判定。
退出码（`--check` 面）：`0` = 全部前提成立；`1` = 有腐烂（**具名**报出哪条变异烂在哪）；`3` = 无法判定。

## 报告卫生（issue #5216）

读数取自 `target/surefire-reports/**` ⇒ ① 跑 Maven **前先 `unlink`** 目标报告；
② 报告缺失 ⇒ **fail-closed 抛错**（无法判定），**绝不**回落读上一次变异的内容
（被并发抢 `target` / 编译失败打断时，旧报告会把环境事故读成「这条变异被抓到 / 没抓到」——
错误归因比没有红证更危险）。
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import xml.etree.ElementTree as ET
from functools import partial
from pathlib import Path

import red_proof_harness as h  # noqa: E402  #5193 门禁调用的是 --check 面（零 Maven/零副作用）

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "backend/admin-api/src/main/java/com/migao/admin/service/AgentBatchService.java"
MODULE = REPO / "backend/admin-api"
TEST_CLASS = "AgentBatchServiceTest"
TEST_FQN = f"com.migao.admin.service.{TEST_CLASS}"
TOOL_REL = "scripts/product-batch-red-proof.py"
SRC_REL = SRC.relative_to(REPO).as_posix()
TEST_REL = "backend/admin-api/src/test/java/com/migao/admin/service/AgentBatchServiceTest.java"

#: 判据方法 → 它钉的那一格（打印用）
CRITERIA = {
    "persistsPreviewWithOldValueCollectedFromDb": "判据 1 预览留 old_value（撤销的唯一依据）",
    "revertRestoresPersistedOldValuePerItem": "判据 2 撤销逐条还原 old_value",
    "reportsPartialFailurePerItemWithoutRollback": "判据 3 部分失败逐条报告、不整体回滚",
    "alreadyRevertedBatchIsNotRevertibleAgain": "判据 4 已撤销不可再撤销（不可撤销条件）",
}


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def replace_once(src: str, old: str, new: str) -> str:
    """锚点必须在源码里命中**恰好 1 次**（0 次 = 漂移；>1 次 = 注入不确定）⇒ 否则报「锚点」。"""
    n = src.count(old)
    if n != 1:
        raise AssertionError(f"变异锚点出现 {n} 次（要求恰好 1 次）—— 被测源码已漂移：{old[:70]!r}")
    return src.replace(old, new, 1)


def splice(src: str, start_marker: str, end_marker: str, replacement: str) -> str:
    """把 `start_marker` 起、`end_marker` 止（含）的一段替换为 `replacement`。"""
    i = src.find(start_marker)
    if i == -1:
        raise AssertionError(f"变异锚点未找到（起点）：{start_marker[:60]!r}")
    j = src.find(end_marker, i)
    if j == -1:
        raise AssertionError(f"变异锚点未找到（终点）：{end_marker[:60]!r}")
    return src[:i] + replacement + src[j + len(end_marker):]


# ── 四条单点变异（每一条都改语义，不是改文案）──────────────────────────────────

def mutation_old_value_not_persisted(src: str) -> str:
    """预览阶段不再落 old_value（撤销依据丢失）—— 判据 1 的红证形态。"""
    return replace_once(
        src,
        "                    // 🔴 落库的是 **DB 真值**，不是调用方字符串：撤销依据不能是调用方的一面之词\n"
        "                    .oldValue(current)\n",
        "                    // [RED-PROOF] 撤销依据不再落库\n"
        "                    .oldValue(null)\n")


def mutation_revert_uses_new_value(src: str) -> str:
    """撤销写回 newValue 而不是持久化的 old_value —— 判据 2 的红证形态。"""
    return replace_once(
        src,
        "                apply(tenantId, item, item.getOldValue());",
        "                apply(tenantId, item, item.getNewValue()); // [RED-PROOF] 还原成了改后值")


def mutation_abort_whole_batch(src: str) -> str:
    """单条失败即中断整批（= 整体回滚/中断，掩盖「哪几条真的改坏了」）—— 判据 3 的红证形态。"""
    return splice(
        src,
        "                String reason = errorText(item.getResourceId(), e);\n"
        "                item.setStatus(ITEM_FAILED);",
        "                        batchId, item.getResourceId(), reason);\n            }",
        "                throw new BusinessException(\"VALIDATION_ERROR\", \"批量执行中断：\"\n"
        "                        + item.getResourceId() + \" \" + errorText(item.getResourceId(), e));"
        " // [RED-PROOF] 单条失败即中断整批\n            }")


def mutation_drop_revert_guards(src: str) -> str:
    """摘掉「不可撤销」的两道闸（状态非 done/partial、或已 reverted）—— 判据 4 的红证形态。"""
    return splice(
        src,
        "        if (STATUS_REVERTED.equals(batch.getStatus())",
        "                    \"请先执行该批次（POST /api/admin/agent/batches/\" + batchId + \"/execute）\");\n        }",
        "        // [RED-PROOF] 不可撤销的两道闸被摘掉\n")


MUTATIONS = [
    ("old_value_persistence", "预览不再持久化 old_value（撤销依据丢失）",
     mutation_old_value_not_persisted, "persistsPreviewWithOldValueCollectedFromDb"),
    ("revert_uses_new_value", "撤销写回 newValue（而不是持久化的 old_value）",
     mutation_revert_uses_new_value, "revertRestoresPersistedOldValuePerItem"),
    ("abort_whole_batch", "单条失败即中断整批（破坏「部分失败逐条报告」）",
     mutation_abort_whole_batch, "reportsPartialFailurePerItemWithoutRollback"),
    ("drop_revert_guards", "摘掉「不可撤销」的两道闸",
     mutation_drop_revert_guards, "alreadyRevertedBatchIsNotRevertibleAgain"),
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


def run_suite() -> dict:
    """跑整类，返回 {方法名: 是否通过}。报告缺失 / 编译失败 ⇒ 抛错（**无法判定**，不是通过）。"""
    report = MODULE / "target/surefire-reports" / f"TEST-{TEST_FQN}.xml"
    if report.exists():
        report.unlink()
    proc = subprocess.run(
        ["./mvnw", "-o", "-q", "test", f"-Dtest={TEST_CLASS}", "-DfailIfNoTests=false"],
        cwd=MODULE, capture_output=True, text=True)
    if not report.exists():
        raise AssertionError("surefire XML 未产出 ⇒ **无法判定**（不是通过）：\n"
                             + (proc.stdout or "")[-2500:] + (proc.stderr or "")[-1500:])
    results: dict = {}
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

    failures: list = []
    try:
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
            others_red = sorted(k for k, v in others.items() if not v)
            if target_failed:
                print(f"   ✅ 判别力成立：{target} 变红")
                if others_red:
                    print(f"   ℹ️ 共享覆盖面（同一次变异也命中这几条，属预期，不当失败）：{others_red}")
                else:
                    print(f"   ✅ 且只有它一条红（其余 {len(others)} 条仍绿 ⇒ 该判据独立抓这一格）")
            else:
                print(f"   ❌ {target} **没有变红** ⇒ 这条判据没有判别力（空断言或未覆盖该缺陷）")
                if others_red:
                    print(f"   ℹ️ 反而有别的判据红了（红被别处抓走）：{others_red}")
                failures.append(name)
    finally:
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