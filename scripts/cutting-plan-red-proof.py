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

⚠️ 本脚本**只允许在 git 干净的工作区**跑（它写被测源码再还原）；`git status` 不干净时直接拒绝
（防止把别人的未提交改动还原掉）。还原 = 写回原文，跑完自校验（`git diff` 必须为空）。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
JAVA_DIR = REPO / "backend" / "admin-api"
SRC = JAVA_DIR / "src/main/java/com/migao/admin/service/CuttingPlanCalculator.java"
TEST_CLASS = "CuttingPlanCalculatorTest"
TEST_FQN = f"com.migao.admin.service.{TEST_CLASS}"

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
        {"resultIsIndependentOfInputOrder", "randomizedInvariantsHold"},
        "排料结果依赖入参顺序 ⇒ 顺序无关判据必须红（单行算例仍绿 = 红是这一条抓的）",
    ),
    (
        "M4 行长度只取第一块（丢掉 max）",
        "            if (meters.compareTo(length) > 0) {\n                length = meters;\n            }",
        "            if (length.signum() == 0) {\n                length = meters;\n            }",
        {"keepsWholePiecesUnmodifiedAndRowsWithinDoorWidth", "randomizedInvariantsHold"},
        "行长度 ≠ 行内最大沿卷长 ⇒ 不变式判据必须红",
    ),
    (
        "M5 去掉入参校验（非正数 / 超门幅照算）",
        "        requirePositive(piece.doorSpanMeters(), \"doorSpanMeters\", piece.pieceId());",
        "        // requirePositive(piece.doorSpanMeters(), \"doorSpanMeters\", piece.pieceId());",
        {"invalidInputsAreRejected"},
        "占门幅宽为 0 / 超门幅仍被静默接受 ⇒ fail-closed 判据必须红",
    ),
]


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
    for stale in (JAVA_DIR / "target/classes/com/migao/admin/service").glob("CuttingPlanCalculator*.class"):
        stale.unlink()
    for stale in (JAVA_DIR / "target/test-classes/com/migao/admin/service").glob(f"{TEST_CLASS}*.class"):
        stale.unlink()
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
    args = parser.parse_args()

    if run_git("status", "--porcelain").strip():
        print("❌ 工作区不干净（本脚本要改写被测源码再还原）——先 commit/stash 无关改动再跑。")
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
