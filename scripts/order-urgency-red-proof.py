#!/usr/bin/env python3
"""#5177 订单加急 / 到货日（PR-079）红证机具：对被测源码做**单点变异**，重跑判据 ⇒ 每条判据都必须**单独**变红。

## 为什么要有它（issue #5195）

`.github/cases/product.yml` 的 `PR-079` 在 `data_checks` 散文里**逐条声称了红证**
（「红证 = 顺手多写一列即红」「红证 = 接上同一来源即红」「红证 = 静默回落成清空 ⇒ 拒绝断言红」
「红证 = 把 DTO 字段从 `Boolean` 改成原生 `boolean` ⇒ 前端读不到加急标记」），
而 `backend/.../OrderUrgencyFieldsTest.java` 里**只有正向断言** —— 「会不会红」此前只是**措辞**，
没有任何可复算的证据（`migao-acceptance`：不会红的断言 = 空断言）。

本机具把那些散文主张变成可复算的四步：

    ① 对被测源码逐条注入一个**语义缺陷**（不是改文案 / 不是改注释）；
    ② 跑**整类** `OrderUrgencyFieldsTest`，从 surefire XML 读**逐方法**结果；
    ③ 期望 = **目标判据方法 FAIL**（= 这条判据确实抓得住这个缺陷，不是空断言）；
       同时**逐条打印**还有哪些判据一起红了 —— 那是「共享覆盖面」，**如实登记、不当失败**；
    ④ 还原源码，并**逐字节自校验**（sha256 必须与注入前相同）。

## 与同族机具的关系

同族 = `scripts/pool-board-red-proof.py`（#5177 的另一半：池看板 / 加急插队）+ 同批纪律
（`scripts/red_proof_harness.py` 的登记表与 `--check` 前提自检、#5193 的门禁调用）。
差异只有一处：本机具同时守卫**两个**被测源文件（`OrderService.java` 的改单路径 +
`OrderDetailResponse.java` 的 wire 类型），故按 `(文件, 变异)` 逐条还原，而不是单文件。

**不要求 git 工作区干净**：本机具只碰上面两个被测源文件（测试文件不在写入半径内），
用「读原文 → 写变异 → 跑 → 写回原文 → 校验 sha256」的**内容级**还原，不依赖 git 兜底。
中断时 `finally` 仍会还原；若还原校验失败，脚本非零退出并打印原文长度，
**绝不静默留下变异后的源码**。

## 用法

    python3 scripts/order-urgency-red-proof.py             # 跑全部变异，逐条打印
    python3 scripts/order-urgency-red-proof.py --only wire_primitive_boolean
    python3 scripts/order-urgency-red-proof.py --check     # 前提自检（门禁调用这个面；零 Maven/零副作用）

退出码（实跑面）：`0` = 全部变异都被对应判据抓到；`1` = 有判据**没有**判别力（或意外结果）；`3` = 无法判定。
退出码（`--check` 面）：`0` = 全部前提成立；`1` = 有腐烂（**具名**报出哪条变异烂在哪）；`3` = 无法判定。
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
MODULE = REPO / "backend/admin-api"
TEST_CLASS = "OrderUrgencyFieldsTest"
TEST_FQN = f"com.migao.admin.service.{TEST_CLASS}"
TOOL_REL = "scripts/order-urgency-red-proof.py"

AAPI = "backend/admin-api/src/main/java/com/migao/admin/"
SVC_REL = AAPI + "service/OrderService.java"
DTO_REL = AAPI + "dto/OrderDetailResponse.java"
TEST_REL = "backend/admin-api/src/test/java/com/migao/admin/service/OrderUrgencyFieldsTest.java"

SRC_RELS = (SVC_REL, DTO_REL)

#: 判据方法 → 它钉的那一格（打印用）
CRITERIA = {
    "updateUrgencyWritesOnlyTheTwoOwnColumns": "判据1/6 改单只写「那两列 + 时间戳」（SET 白名单）",
    "updateUrgencyHasNoSharedSourceWithAfterSalesTicket": "判据1 源码级零联动（方法体不得出现售后字样）",
    "updateUrgencyTriState": "改单三态（null 不改 / \"\" 清空 / 日期设值）",
    "malformedOrBlankDateIsRejectedWithoutAnyWrite": "fail-closed（非法日期显式拒绝且零写入）",
    "wireKeysAreIsUrgentAndIsoDate": "wire 契约（JSON 键 = isUrgent）",
}


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def replace_once(src: str, old: str, new: str) -> str:
    n = src.count(old)
    if n != 1:
        raise AssertionError(f"变异锚点出现 {n} 次（要求恰好 1 次）：{old[:70]!r}")
    return src.replace(old, new, 1)


# ── 变异（每条 = 一个**语义缺陷**形态，逐条对应 `data_checks` 里声称的一条红证）─────────

def mutation_extra_column(src: str) -> str:
    """判据 1 红证：「顺手多写一列」（把 `status` 也写进去）⇒ SET 白名单断言红。"""
    return replace_once(
        src,
        "        update.set(Order::getUpdatedAt, OffsetDateTime.now());\n"
        "        orderMapper.update(null, update);",
        "        update.set(Order::getUpdatedAt, OffsetDateTime.now());\n"
        "        // [RED-PROOF] 顺手把订单状态也同步一行\n"
        "        update.set(Order::getStatus, order.getStatus());\n"
        "        orderMapper.update(null, update);",
    )


def mutation_shared_priority_source(src: str) -> str:
    """判据 1（源码级）红证：「把加急接到售后工单的同一来源」（值经 `priority` 这一路流转）。"""
    return replace_once(
        src,
        "        if (isUrgent != null) {\n"
        "            update.set(Order::getIsUrgent, isUrgent);\n",
        "        if (isUrgent != null) {\n"
        "            // [RED-PROOF] 与售后工单接上同一来源\n"
        "            boolean priority = Boolean.TRUE.equals(isUrgent);\n"
        "            update.set(Order::getIsUrgent, priority);\n",
    )


def mutation_blank_treated_as_unchanged(src: str) -> str:
    """三态红证：「把 `\"\"` 也当『不改』」⇒ 清空态断言红（界面显示已清空而库里还有日期）。"""
    return replace_once(
        src,
        "        if (requiredDeliveryDateRaw != null) {",
        "        if (requiredDeliveryDateRaw != null && !requiredDeliveryDateRaw.isEmpty()) {"
        " // [RED-PROOF] 空串被当成「不改」",
    )


def mutation_silent_clear_fallback(src: str) -> str:
    """fail-closed 红证：「非法日期静默回落成清空」⇒ 拒绝断言红（且「零写入」断言红）。"""
    return replace_once(
        src,
        "        } catch (DateTimeParseException e) {\n"
        "            throw BusinessException.validationError(\n"
        '                    "到货日格式不正确：" + raw + "（期望 YYYY-MM-DD，或传空串清空到货日）");\n'
        "        }",
        "        } catch (DateTimeParseException e) {\n"
        "            return null; // [RED-PROOF] 静默回落成「清空」（不拒绝、不报错）\n"
        "        }",
    )


def mutation_wire_key_drift(src: str) -> str:
    """wire 契约红证：**DTO 的线格式键名漂移** ⇒ 前端读不到加急标记（键名断言红）。

    ⚠️ **为什么不用散文里逐字写的那个形态**（「把字段从 `Boolean` 改成原生 `boolean`」）：
    实测该形态会让**判据自身编译不过**（Lombok 对原生 `boolean isX` 生成的是
    `isX()` / `setX()`，判据里的 `setIsUrgent(...)` / `getIsUrgent()` 立刻「找不到符号」）
    ⇒ 判据**一行都没跑**，机具按 #5242 的证据闸只能判「**无法判定**」——
    那不是「判别力成立」。故本机具用**语义等价、且能编译**的形态承载同一条判据：
    显式把该字段的 Jackson 属性名改成 `urgent`（= 散文红证要防的那个后果：
    线格式键不是 `isUrgent` ⇒ 前端读不到加急标记）。
    """
    return replace_once(
        src,
        "    private Boolean isUrgent;",
        '    @com.fasterxml.jackson.annotation.JsonProperty("urgent") // [RED-PROOF] 线格式键漂移\n'
        "    private Boolean isUrgent;",
    )


#: `(变异名, 说明, 被测源文件, 变异函数, 期望变红的判据方法)`
MUTATIONS = [
    ("extra_column", "顺手多写一列（SET 白名单被破）", SVC_REL, mutation_extra_column,
     "updateUrgencyWritesOnlyTheTwoOwnColumns"),
    ("shared_priority_source", "与售后工单接上同一来源（priority 进入方法体）", SVC_REL,
     mutation_shared_priority_source, "updateUrgencyHasNoSharedSourceWithAfterSalesTicket"),
    ("blank_as_unchanged", '把 "" 也当成「不改」（清空静默失效）', SVC_REL,
     mutation_blank_treated_as_unchanged, "updateUrgencyTriState"),
    ("silent_clear_fallback", "非法日期静默回落成「清空」（不 fail-closed）", SVC_REL,
     mutation_silent_clear_fallback, "malformedOrBlankDateIsRejectedWithoutAnyWrite"),
    ("wire_key_drift", "线格式键名漂移（isUrgent → urgent）", DTO_REL,
     mutation_wire_key_drift, "wireKeysAreIsUrgentAndIsoDate"),
]


def _probe(mutate, src_rel: str, target: str, name: str) -> None:
    """一条变异的前提探针（**只读**）：被守卫文件可读 + 注入锚点命中 1 次 + 目标判据存在。"""
    src = h.read_source(src_rel, what=f"变异 [{name}] 的被测源码")
    test = h.read_source(TEST_REL, what=f"变异 [{name}] 的判据源码")
    h.require_method(test, target, what=f"变异 [{name}] 的目标判据")
    if mutate(src) == src:
        raise h.Rot("变异没有改变源码（锚点失配，或它与原文语义等价）")


def check() -> int:
    """前提自检（`--check`）：不注入、不跑判据、不写任何文件。"""
    decls = [h.declare(name, target, partial(_probe, mutate, src_rel, target, name))
             for name, _label, src_rel, mutate, target in MUTATIONS]
    return h.report_and_exit(TOOL_REL, decls)


def run_suite() -> dict[str, bool]:
    """跑整类，返回 {方法名: 是否通过}。无法判定（无 XML / 编译失败）⇒ 抛错。"""
    report = MODULE / "target/surefire-reports" / f"TEST-{TEST_FQN}.xml"
    # #5216 报告卫生：报告由 Maven 在跑完后才重写；中断/编译失败时它会**保持上一次变异的内容**
    # ⇒ 先 unlink，跑完仍缺失就 fail-closed（读旧报告 = 把环境事故读成「抓到/没抓到」）。
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

    originals = {rel: (REPO / rel).read_text(encoding="utf-8") for rel in SRC_RELS}
    hashes = {rel: sha256(text) for rel, text in originals.items()}
    for rel in SRC_RELS:
        print(f"被测源码 = {rel}  sha256={hashes[rel][:16]}…  长度={len(originals[rel])}")
    print()

    selected = [m for m in MUTATIONS if args.only is None or m[0] == args.only]
    if not selected:
        print(f"❌ 没有匹配的变异：{args.only}", file=sys.stderr)
        return 3

    failures: list[str] = []
    unknown: list[str] = []
    try:
        # 基线：注入前整类必须全绿（否则红证会把"本来就在红"的判据算成有判别力）
        baseline = run_suite()
        not_green = sorted(k for k, v in baseline.items() if not v)
        print(f"基线：{len(baseline)} 条判据，{'全绿 ✅' if not not_green else '有红 ❌ ' + str(not_green)}")
        if not_green:
            print("❌ 基线不绿 ⇒ 无法取红证（先修基线）", file=sys.stderr)
            return 1

        for name, label, src_rel, mutate, target in selected:
            if target not in CRITERIA:
                print(f"❌ 变异 {name} 的目标方法不在判据表里：{target}", file=sys.stderr)
                return 3
            original = originals[src_rel]
            mutated = mutate(original)
            if mutated == original:
                print(f"❌ 变异 {name} 没有改变源码（锚点失配）—— **无法判定**", file=sys.stderr)
                return 3
            (REPO / src_rel).write_text(mutated, encoding="utf-8")
            print(f"\n── 变异 [{name}] {label}（{src_rel}）")
            print(f"   期望：{target} 变红，其余判据保持绿")
            try:
                try:
                    results = run_suite()
                except AssertionError as exc:
                    # #5242 证据闸：编译失败 / 收集失败同样 rc!=0，但那时判据一行没跑
                    # ⇒ **无法判定**（不得读成「这条变异被抓到了」）。
                    print(f"   ❓ 无法判定（判据没跑起来）：{str(exc)[:600]}", file=sys.stderr)
                    unknown.append(name)
                    continue
            finally:
                (REPO / src_rel).write_text(original, encoding="utf-8")
                if sha256((REPO / src_rel).read_text(encoding="utf-8")) != hashes[src_rel]:
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
        # 任何路径（含异常 / Ctrl-C）都要还原，且自校验
        for rel, original in originals.items():
            if (REPO / rel).read_text(encoding="utf-8") != original:
                (REPO / rel).write_text(original, encoding="utf-8")
            ok = sha256((REPO / rel).read_text(encoding="utf-8")) == hashes[rel]
            print(f"\n还原 {rel}：{'✅ 与注入前逐字节相同' if ok else '❌ 不一致 —— 人工核对 ' + rel}")

    if unknown:
        print(f"\n❓ 有 {len(unknown)} 个变异**无法判定**（判据没跑起来）：{unknown}", file=sys.stderr)
        return 3
    if failures:
        print(f"\n❌ 有 {len(failures)} 个变异没被对应判据抓到：{failures}", file=sys.stderr)
        return 1
    print(f"\n✅ 全部 {len(selected)} 个单点变异都被对应判据单独抓到（每条判据都有判别力）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
