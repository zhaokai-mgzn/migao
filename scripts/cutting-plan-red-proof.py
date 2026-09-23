#!/usr/bin/env python3
"""#5142 红证机具：对被测源码做**单点变异**，重跑判据 ⇒ 每条判据都必须**单独**变红。

## 为什么要有它
「全绿」本身不构成证据 —— 不会红的断言 = 空断言。本脚本把每条判据的**判别力**变成可复算的：
① 对 `CuttingPlanCalculator.java` 逐条注入一个**语义缺陷**（不是改文案）；
② 只把**该判据的测试方法**跑起来（`-Dtest=Class#method`）⇒ 期望 = **FAIL**；
③ 同时跑**其余判据** ⇒ 期望 = **PASS**（证明红是这一条判据抓的，不是"一起红"）。

## 用法
    python3 scripts/cutting-plan-red-proof.py            # 默认：跑全部变异，逐条打印
    python3 scripts/cutting-plan-red-proof.py --keep     # 保留变异后的源码（人工复核用）
    python3 scripts/cutting-plan-red-proof.py --check    # 前提自检（门禁调用这个面；零 Maven/零副作用）

退出码（实跑面）：`0` = 每条判据都「该条红、其余绿」；`1` = 有判据没有判别力；`2` = 被测文件有未提交改动。
退出码（`--check` 面）：`0` = 全部前提成立；`1` = 有腐烂（**具名**）；`3` = 无法判定。

⚠️ 本脚本**只允许在 git 干净的工作区**跑（它写被测源码再还原）；`git status` 不干净时直接拒绝
（防止把别人的未提交改动还原掉）。还原 = 写回原文，跑完自校验（`git diff` 必须为空）。
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from functools import partial
from pathlib import Path

import red_proof_harness as h  # noqa: E402  #5193 门禁调用的是 --check 面（零 Maven/零副作用）

REPO = Path(__file__).resolve().parents[1]
JAVA_DIR = REPO / "backend" / "admin-api"
SRC = JAVA_DIR / "src/main/java/com/migao/admin/service/CuttingPlanCalculator.java"
TEST_CLASS = "CuttingPlanCalculatorTest"
TEST_FQN = f"com.migao.admin.service.{TEST_CLASS}"
TOOL_REL = "scripts/cutting-plan-red-proof.py"
SRC_REL = SRC.relative_to(REPO).as_posix()
TEST_REL = "backend/admin-api/src/test/java/com/migao/admin/service/CuttingPlanCalculatorTest.java"

#: 判据方法 → 它钉的那一格（打印用）
CRITERIA = {
    "fixedHeightTallWindowsPairIntoOneRow": "定高买宽并排（算例：1 行 / 3m）",
    "fixedWidthSinglePanelNarrowWindowsPairIntoOneRow": "定宽买高 P=1 窄窗互补",
    "piecesThatDoNotFitTogetherKeepTheirOwnRows": "不倒退（排不下时逐值相同）",
    "keepsWholePiecesUnmodifiedAndRowsWithinDoorWidth": "完整布不变式",
    "resultIsIndependentOfInputOrder": "顺序无关",
    "randomizedInvariantsHold": "反空跑随机不变式",
    "invalidInputsAreRejected": "非法入参 fail-closed",
}

#: 单点变异：(名字, 原文片段, 变异片段, {期望红的判据方法}, 缺陷语义)
#
# ⚠️ **变异必须"语义可达"**：第一版里有一条「静默丢掉排不下的料」（`if span > doorWidth: continue`），
# 实测**恒绿** —— 那个分支**不可达**（调方校验已把「单块超门幅」挡在装箱之前），
# 即它根本没制造缺陷 ⇒ 已删除。"少算"这个风险由 M2（行内 Σ 越界）与 M4（行长度少算）两条覆盖。
MUTATIONS: list[tuple[str, str, str, set[str], str]] = [
    (
        "M1 禁止一切并排",
        "            if (target < 0) {",
        "            if (true) {",
        {"fixedHeightTallWindowsPairIntoOneRow", "fixedWidthSinglePanelNarrowWindowsPairIntoOneRow",
         "keepsWholePiecesUnmodifiedAndRowsWithinDoorWidth", "resultIsIndependentOfInputOrder"},
        "两块料占门幅 1.4 + 1.4 = 2.8 ≤ 门幅，却各占一行 ⇒ 两条并排判据必须红"
        "（不变式/顺序无关里也有「并排必须发生」的断言，同步红）",
    ),
    (
        "M2 去掉行内 Σ占门幅宽 守卫（改成恒真 ⇒ 所有料挤一行）",
        "                if (rowSpans.get(i).add(span).compareTo(maxRowSpan) <= 0) {",
        "                if (true) {",
        {"piecesThatDoNotFitTogetherKeepTheirOwnRows", "keepsWholePiecesUnmodifiedAndRowsWithinDoorWidth",
         "resultIsIndependentOfInputOrder", "randomizedInvariantsHold"},
        "1.7 + 1.7 = 3.4 > 门幅 2.8 仍被排进同一行 ⇒ 「不倒退/切不出货」判据必须红。"
        "⚠️ 单行算例（两条并排判据）此时**仍绿**：两块挤成一行与并排成一行在本例里行长度相同（3.0）"
        "—— 这正是「不倒退」要靠**多行**算例才判得出来的原因，故那两条**不**列进期望红。",
    ),
    (
        "M3 排序键方向反转（降序 → 升序）",
        "            int byMeters = Double.compare(b.meters(), a.meters());",
        "            int byMeters = Double.compare(a.meters(), b.meters());",
        {"resultIsIndependentOfInputOrder", "keepsWholePiecesUnmodifiedAndRowsWithinDoorWidth"},
        "排料结果依赖入参顺序 ⇒ 顺序无关判据必须红。不变式判据也红：它自己也钉了行构成"
        "（行的料与顺序与输入顺序无关），升序后 A/C 与 B 的行归属翻转 ⇒ 构成断言先红。\n"
        "    ⚠️ `randomizedInvariantsHold` 仍绿是**有意的**：它只比较「换顺序后应领米数是否相同」，"
        "对「排序方向」不敏感（逆序+升序恰好互为镜像）—— 判别力的那一格由 J5 承担。",
    ),
    (
        "M4 行长度取行内最后一块（丢掉 max）",
        "            if (meters.compareTo(length) > 0) {\n                length = meters;\n            }",
        "            if (true) {\n                length = meters;\n            }",
        {"keepsWholePiecesUnmodifiedAndRowsWithinDoorWidth", "randomizedInvariantsHold",
         "resultIsIndependentOfInputOrder"},
        "行长度 ≠ 行内最大沿卷长（A 5.0 + B 3.0 同行 ⇒ 应领 5.0 被算成 3.0 = **少算**）"
        " ⇒ 不变式判据红；顺序无关判据也红（它的行长度/构成断言随之不等）。\n"
        "    ⚠️ 两条**等长**的并排算例（J1/J2）此时仍绿：两块都是 3.0，「取首块」与「取末块」同值"
        " ⇒ 它们对「取错哪一块」这种缺陷**结构上不敏感**；真正设防的是 J4（同行两块 5.0 / 3.0）。\n"
        "    ⚠️ 本变异的第一版是「改成 `length.signum()==0` 才赋值」（= 取行内**第一块**）："
        "实测**恒绿**且**原理上不可能红** —— 规范序按沿卷长降序，行内第一块**必然是该行最大值**"
        " ⇒ 那个变异与正确实现**语义等价**。已换成真正可观测的缺陷（取最后一块）。",
    ),
    (
        "M5 去掉入参校验（非正数 / 超门幅照算）",
        "        requirePositive(piece.doorSpanMeters(), \"doorSpanMeters\", piece.pieceId());",
        "        // requirePositive(piece.doorSpanMeters(), \"doorSpanMeters\", piece.pieceId());",
        {"invalidInputsAreRejected"},
        "占门幅宽为 0 / 超门幅仍被静默接受 ⇒ fail-closed 判据必须红",
    ),
]


def _probe(before: str, expect_red: set, name: str) -> None:
    """一条变异的前提探针（**只读**）：注入锚点命中 1 次 + 每条期望判据都真的存在。"""
    src = h.read_source(SRC_REL, what=f"变异 [{name}] 的被测源码")
    test = h.read_source(TEST_REL, what=f"变异 [{name}] 的判据源码")
    h.require_anchor(src, before, what=f"变异 [{name}] 的注入锚点")
    for method in sorted(expect_red):
        h.require_method(test, method, what=f"变异 [{name}] 的期望判据")


def check() -> int:
    """前提自检（`--check`）：不注入、不跑判据、不删编译产物、不写任何文件。"""
    decls = [h.declare(name, "、".join(sorted(expect_red)),
                       partial(_probe, before, expect_red, name))
             for name, before, _after, expect_red, _sem in MUTATIONS]
    return h.report_and_exit(TOOL_REL, decls)


def run_git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True,
                          check=True).stdout


def run_test(method: str | None) -> bool:
    """跑一条（或整类）判据 ⇒ True = 全绿。

    ⚠️ **每次都必须强制重编译**：`mvn test` 的增量编译按**时间戳**判新旧，而本脚本在
    同一秒内「改源 → 跑测 → 再改源」⇒ 亲测会出现「源码变了但编译没跟上」，
    于是变异后的判据照旧全绿 —— 那是**机具自己的假绿**（本脚本第一版就踩了：M3~M6
    全被读成「无判别力」）。故先删编译产物再跑，让「编译了没有」不再靠时间戳。
    """
    selector = f"{TEST_CLASS}" + (f"#{method}" if method else "")
    # ⚠️ **必须整棵构建树删掉**，不能只删 `*.class` 再靠 `mvn test` 增量编译：
    # 实测同一秒内「改源 → 跑测 → 再改源」时 maven 的增量判定会认定「没有改动」而**跳过编译**，
    # 于是变异后的判据照旧全绿 —— 那是**机具自己的假绿**（本脚本第一版就踩了：M3~M5 全被读成
    # 「无判别力」，而真相是「根本没编译变异后的源码」）。删 target/classes + target/test-classes
    # 让「编译了没有」不再靠时间戳。（不用 `mvn clean`：它要联网拉插件，离线环境会失败。）
    for tree in (JAVA_DIR / "target/classes", JAVA_DIR / "target/test-classes"):
        if tree.exists():
            shutil.rmtree(tree)
    proc = subprocess.run(
        ["./mvnw", "-o", "test", f"-Dtest={selector}", "-DfailIfNoSpecifiedTests=false"],
        cwd=JAVA_DIR, capture_output=True, text=True,
    )
    out = proc.stdout + proc.stderr
    if re.search(r"Tests run:.*(Failures: [1-9]|Errors: [1-9])", out) or "BUILD FAILURE" in out:
        return False
    if "BUILD SUCCESS" not in out:
        print(f"    ⚠️ 无法判定（既非成功也非失败）⇒ fail-closed 判红：\n{out[-800:]}")
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="保留最后一次变异（人工复核）")
    parser.add_argument("--check", action="store_true",
                        help="只做前提自检（#5193 门禁调用的面）：零 Maven、零副作用、不注入")
    args = parser.parse_args()
    if args.check:
        return check()

    # 只关心**被测那两个文件**干不干净：本仓工作区常有与它无关的未跟踪文件
    # （PR body 草稿、构建产物），一刀切要求「整棵树干净」会让机具没法用。
    # 但它仍必须 fail-closed —— 被它改写的那个文件若有**未提交改动**，还原就等于毁掉它们。
    watched = [str(SRC.relative_to(REPO)), str((JAVA_DIR / "src/test/java/com/migao/admin/service"
                                                / f"{TEST_CLASS}.java").relative_to(REPO))]
    dirty = run_git("status", "--porcelain", "--", *watched).strip()
    if dirty:
        print(f"❌ 被测文件有未提交改动（本脚本要改写它再还原）——先提交：\n{dirty}")
        return 2

    original = SRC.read_text(encoding="utf8")
    failures: list[str] = []
    try:
        for name, before, after, expect_red, semantics in MUTATIONS:
            if original.count(before) != 1:
                print(f"❌ {name}：锚点命中 {original.count(before)} 次（须恰好 1 次）⇒ 变异无效，判为失败")
                failures.append(f"{name}（锚点失效）")
                continue
            print(f"\n▶ {name}：{semantics}")
            SRC.write_text(original.replace(before, after), encoding="utf8")
            red: list[str] = []
            green_but_expected_red: list[str] = []
            others_red: list[str] = []
            for method in CRITERIA:
                passed = run_test(method)
                if not passed:
                    red.append(method)
                if method in expect_red and passed:
                    green_but_expected_red.append(method)
                if method not in expect_red and not passed:
                    others_red.append(method)
            print(f"    变红的判据 = {[m for m in CRITERIA if m in red]}")
            if green_but_expected_red:
                failures.append(f"{name}：期望红却仍绿 {green_but_expected_red}")
                print(f"    ❌ 期望红却仍绿：{green_but_expected_red}")
            if others_red:
                failures.append(f"{name}：波及未预期判据 {others_red}")
                print(f"    ❌ 波及未预期判据（红不是这一条抓的）：{others_red}")
            if not green_but_expected_red and not others_red:
                print("    ✅ 判别力成立（该条红、其余绿）")
    finally:
        if args.keep:
            print("\n⚠️ --keep：变异后的源码**保留在工作区**（请人工核对后自行还原）")
        else:
            SRC.write_text(original, encoding="utf8")
            dirty = run_git("diff", "--name-only", "--", str(SRC.relative_to(REPO))).strip()
            print(f"\n还原自校验：git diff（被测文件）= {dirty!r} ⇒ {'✅ 干净' if not dirty else '❌ 未还原'}")

    print("\n===== 红证总表 =====")
    if failures:
        print("❌ 有判据无判别力：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print(f"✅ {len(MUTATIONS)} 个单点变异、每条判据逐条复核 —— 均「该条红、其余绿」。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
