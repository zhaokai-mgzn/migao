# case_ids: BM-027
r"""商家端 h5 的**字号下限**常驻判据 + 只许缩短的存量台账（issue #5721）。

## 为什么要有它

用户裁定逐字：「手机端的样式务必设计的方便用户操作和查看，**不能搞太小的字体**，而且要支持
响应式，方便不同屏幕尺寸的手机用起来都方便」。

登录页曾经的形态正是这条的实例：样式按「CSS px 尺」写（标签 13px / 输入 15px），而本仓样式管线是
**设计尺度**（750 设计宽，`1px = 1/40 rem`；root font-size 接线见 `frontend/bmini-app/src/index.html`）
⇒ 真机上字段标签只有 **5.2 CSS px**。

🔴 **只修登录页 = 没修**：同一个坑还留在其余 19 个样式文件里（开工时全库 **92** 处 sub-floor 声明，
本 PR 修掉登录页 7 处 ⇒ 存量 **85** 处）。所以这里落一条**会红**的类级判据，让「新写一个 12px/20px
的字号」当场拦下，存量走**只许缩短**的台账。

## 口径（现取，不写死）

- 语料 = `frontend/bmini-app/src/**/*.scss` 的 `font-size` 声明（行注释剔除，`// …` 不算）
- 单位 `px`（小写）⇒ **设计尺度**：下限 **24**（= 12.8 CSS px @390 宽、12.0 @375）
- 单位 `PX`（大写，`postcss-pxtransform` 不折算）⇒ **CSS 尺度**：下限 **12**
- 台账 = `bmini_typography_baseline.json`：
  · 出现台账外的违规 ⇒ **红**（新增超标字号进不来）
  · 台账里的条目已不再违规 ⇒ **红**（记了就要删，不留旧账 —— 与 §23 G1/G2 同口径）

## 出口（红时怎么办）

- **新违规**：把那个字号调到 ≥ 24（唯一正确的修法；**没有**「加进台账」的口子）
- **旧账已还**：`python3 tests/unit_ci_workflows/test_bmini_mobile_typography_floor.py --regen`
  —— 该命令**只允许缩短**：新集合必须是旧集合的子集，多一条即拒绝并打印多出来的条目。

⚠️ 边界（照实登记）：本判据只管 `font-size` 的**数值下限**，不判「字号是否成体系」
（同一层级东一个 24 一个 30 它看不出来），也不管 `height` / 行高 / 对比度 ——
那些面目前没有机械判据。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "frontend" / "bmini-app" / "src"
BASELINE_PATH = Path(__file__).resolve().parent / "bmini_typography_baseline.json"

DESIGN_PX_FLOOR = 24
CSS_PX_FLOOR = 12

# 只认 `font-size: <数字><单位>`；`@include` / 变量 / calc 一律不猜（漏项好过误伤）
_FONT_SIZE = re.compile(r"font-size\s*:\s*(\d+(?:\.\d+)?)\s*(px|PX)\b")


def _strip_line_comments(text: str) -> list[str]:
    """剔除 `//` 行注释（本仓样式无 `url(...//...)` 形态；注释掉的声明不该被计数）。"""
    return [line.split("//", 1)[0] for line in text.splitlines()]


def scan_violations() -> dict[str, int]:
    """全量扫描，返回 `{条目键: 1}`（键形如 `<仓库相对路径>::font-size: 22px#2`）。

    条目键用「文件 + 声明原文 + 该文件内第几次出现」而不是行号：
    行号会被上面任何一次编辑顶掉（活跃文件的裸行号几分钟就失效），而这三样在本判据的语义下是稳定的。
    """
    found: dict[str, int] = {}
    for path in sorted(SRC_ROOT.rglob("*.scss")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        occurrences: dict[str, int] = {}
        for line in _strip_line_comments(path.read_text(encoding="utf-8")):
            for match in _FONT_SIZE.finditer(line):
                value, unit = float(match.group(1)), match.group(2)
                floor = DESIGN_PX_FLOOR if unit == "px" else CSS_PX_FLOOR
                if value >= floor:
                    continue
                declaration = f"font-size: {match.group(1)}{unit}"
                occurrences[declaration] = occurrences.get(declaration, 0) + 1
                found[f"{rel}::{declaration}#{occurrences[declaration]}"] = 1
    return found


def _load_baseline() -> dict:
    assert BASELINE_PATH.is_file(), (
        f"缺台账 {BASELINE_PATH} —— 台账是判据的一半，不许缺（缺了就没法区分『存量』与『新增』）"
    )
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    assert isinstance(data.get("violations"), list), f"{BASELINE_PATH} 的 violations 必须是列表"
    return data


def _render_diff(title: str, entries: list[str], hint: str) -> str:
    lines = [title, ""]
    lines += [f"  · {entry}" for entry in entries[:40]]
    if len(entries) > 40:
        lines.append(f"  … 另有 {len(entries) - 40} 条（完整清单：`python3 {Path(__file__).name} --list`）")
    lines += ["", hint]
    return "\n".join(lines)


def test_no_new_below_floor_font_size() -> None:
    """台账外的 sub-floor 字号 ⇒ 红（这是「不能搞太小的字体」的机械判据）。

    红证（实跑过）：在 `frontend/bmini-app/src/pages/auth/login/index.scss` 里写回
    `font-size: 13px` ⇒ 本条红，并把该条目点名。
    """
    baseline = _load_baseline()
    known = set(baseline["violations"])
    current = scan_violations()
    added = sorted(set(current) - known)
    assert not added, _render_diff(
        f"❌ 新增 {len(added)} 处低于下限的字号（设计尺度 < {DESIGN_PX_FLOOR}px "
        f"≈ {DESIGN_PX_FLOOR * 0.52:.1f} CSS px @390 宽；大写 PX < {CSS_PX_FLOOR}px）：",
        added,
        "出口：把这些字号调到 ≥ 24（设计尺度）。台账**不接受新增**（只许缩短）。",
    )


def test_baseline_entries_still_violate() -> None:
    """台账里的条目必须仍然违规 ⇒ 已还清的旧账必须删掉（只许缩短，不许留旧账）。

    红证（实跑过）：把台账里任意一条对应的 `font-size` 调到达标 ⇒ 本条红，要求删除该条目。
    """
    baseline = _load_baseline()
    known = set(baseline["violations"])
    current = scan_violations()
    stale = sorted(known - set(current))
    assert not stale, _render_diff(
        f"❌ 台账里有 {len(stale)} 条**已不再违规**（旧账要销，否则台账会烂成『永远绿』）：",
        stale,
        "出口：`python3 tests/unit_ci_workflows/test_bmini_mobile_typography_floor.py --regen`"
        "（只允许缩短：新集合必须是旧集合的子集）。",
    )


def test_baseline_header_metrics_are_current() -> None:
    """台账头部的计数/口径必须与**现取**读数一致（防台账自述与现实脱节）。"""
    baseline = _load_baseline()
    current = scan_violations()
    assert baseline.get("floor_design_px") == DESIGN_PX_FLOOR, (
        f"{BASELINE_PATH} 的 floor_design_px={baseline.get('floor_design_px')!r} "
        f"≠ 现取 {DESIGN_PX_FLOOR} —— 口径改了台账必须同批重算"
    )
    assert baseline.get("count") == len(current), (
        f"{BASELINE_PATH} 的 count={baseline.get('count')!r} ≠ 现取 {len(current)}"
        "（头部计数陈旧 ⇒ 看台账的人拿到的是旧世界）"
    )


def _regen() -> int:
    """只允许**缩短**的台账重生成：新集合必须是旧集合的子集。"""
    current = scan_violations()
    if BASELINE_PATH.is_file():
        known = set(json.loads(BASELINE_PATH.read_text(encoding="utf-8"))["violations"])
        added = sorted(set(current) - known)
        if added:
            print(f"❌ 拒绝写入：本次扫描比台账多 {len(added)} 条（台账只许缩短）：")
            for entry in added[:40]:
                print(f"  · {entry}")
            print("   出口：把这些字号调到 ≥ 24，而不是把它们登记进台账。")
            return 1
    payload = {
        "_comment": (
            "商家端 h5 字号下限台账（issue #5721）。**只许缩短**："
            "新增条目会被 tests/unit_ci_workflows/test_bmini_mobile_typography_floor.py 拒绝写入，"
            "已还清的条目必须删除（该文件同时判『台账外的违规』与『台账里的旧账』）。"
        ),
        "rule": (
            f"frontend/bmini-app/src/**/*.scss 的 font-size：小写 px < {DESIGN_PX_FLOOR}（设计尺度，"
            f"≈{DESIGN_PX_FLOOR * 0.52:.1f} CSS px @390 宽）、大写 PX < {CSS_PX_FLOOR}（CSS 尺度）即违规"
        ),
        "floor_design_px": DESIGN_PX_FLOOR,
        "floor_css_px": CSS_PX_FLOOR,
        "count": len(current),
        "violations": sorted(current),
    }
    BASELINE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✅ 台账已写入 {BASELINE_PATH}（现取 {len(current)} 条）")
    return 0


if __name__ == "__main__":
    if "--regen" in sys.argv:
        raise SystemExit(_regen())
    if "--list" in sys.argv:
        for key in sorted(scan_violations()):
            print(key)
        raise SystemExit(0)
    print(__doc__)
    raise SystemExit(pytest.main([__file__, "-v"]))
