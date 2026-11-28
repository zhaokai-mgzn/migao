# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012。）
r"""「写了退役、其实没退役」的类级元守卫（issue #9280 收口，2026-11-28）。

## 病根（真实事故，不是假设）

`.github/cases/**` 里「退役」**没有专门的字段**：唯一有机械效果的是 `skip_reason`
（`tests/agent_eval/eval_cases/*` 的 `select_cases_for_persona` 与 runner 都按
`not c.skip_reason` 过滤）。而 2026-11-26 那次「C 端小程序删除 ⇒ 批量退役」是用**注释**写的：

    # 本条按「承载体删除」退役（条目不删、判据改指 …）

⇒ 27 条里 **21 条**同时写了非空 `skip_reason`（真退役），**6 条没有**（`CH-009` / `CH-010` /
`CH-011` / `CH-012` / `ST-011` / `ST-012`）—— 它们**照样进评测、照样占分母**，而读代码的人
从注释里读到的是「已退役」。实测后果（run `46086496186`）：`ST-011` 首跑指纹
`no_success(direct_reply)` 连续两个 run 复发 ⇒ `completion.ok=false`，而它的「退役」注释
让归因绕了一大圈。

## 判据（会红，且红得能行动）

扫描 `.github/cases/*.yml` 的**每个用例块**：块内出现退役标记短语 ⇒ `skip_reason` 必须非空。
- 红 = 具名 `文件::用例 id` + 一句「要么补 `skip_reason`（真退役），要么删掉退役注释（保持 active）」；
- **非空扫描面自证**：标记短语在仓内必须至少命中 1 条 —— 否则（改名 / 删光 / 路径搬走）
  本判据会变成**恒绿的空断言**，那比没有判据更坏；
- 注入式红证：三条合成块（标记+空 ⇒ 红 / 标记+非空 ⇒ 绿 / 无标记+空 ⇒ 绿）都走**同一个**
  `find_violations()`，证明判据不是「读着像在判」。

零网络、零时钟、零真实 LLM：读的都是仓内静态文本。
"""
from __future__ import annotations

import pathlib
import re

CASES_DIR = pathlib.Path(__file__).resolve().parents[2] / ".github" / "cases"

#: 退役标记短语（**唯一判定源**）。改这里必须同批改本文件顶部的病根说明与 `#9280` 收口评论。
RETIREMENT_MARKER = "按「承载体删除」退役"

#: 用例块起点（与 `.github/cases/*.yml` 的缩进约定一致：两空格 `- id:`）。
_BLOCK_START = re.compile(r"^  - id:\s*(\S+)\s*$")
_SKIP_LINE = re.compile(r"^\s{4}skip_reason:\s*(.*)$")


def iter_case_blocks(text: str):
    """把一份 cases YAML 切成 `(case_id, block_lines)`（**按文本**，因为要读注释）。

    不解析 YAML 的原因：`yaml.safe_load` **丢弃注释**，而退役标记恰恰只在注释里 ——
    用 YAML 解析会让本判据永远扫不到标记（= 恒绿空断言）。
    """
    current_id = None
    current: list[str] = []
    for line in text.splitlines():
        m = _BLOCK_START.match(line)
        if m:
            if current_id is not None:
                yield current_id, current
            current_id, current = m.group(1), [line]
            continue
        if current_id is not None:
            current.append(line)
    if current_id is not None:
        yield current_id, current


def _skip_reason_of(block: list[str]) -> str:
    value = ""
    for line in block:
        m = _SKIP_LINE.match(line)
        if m:
            value = m.group(1).strip()
            break
    # YAML 里 `skip_reason: ""` / `skip_reason: ''` 都是**空**（= 未退役）。
    return value.strip("\"'")


def find_violations(blocks) -> list[tuple[str, str]]:
    """返回 `[(case_id, reason)]`；纯函数，注入式红证与真实扫描共用（单一实现）。"""
    bad: list[tuple[str, str]] = []
    for case_id, block in blocks:
        body = "\n".join(block)
        if RETIREMENT_MARKER not in body:
            continue
        if _skip_reason_of(block):
            continue
        bad.append((case_id, "块内写了退役标记，但 `skip_reason` 为空 ⇒ 该用例仍在评测里跑"))
    return bad


def _all_blocks():
    files = sorted(CASES_DIR.glob("*.yml"))
    assert files, f"扫描面为空：{CASES_DIR} 下没有 *.yml"
    for path in files:
        for case_id, block in iter_case_blocks(path.read_text(encoding="utf-8")):
            yield path.name, case_id, block


def test_retirement_marker_implies_non_empty_skip_reason():
    """判据本体：写了「退役」就必须真的退役（`skip_reason` 非空）。"""
    violations = []
    for filename, case_id, block in _all_blocks():
        for bad_id, reason in find_violations([(case_id, block)]):
            violations.append(f"{filename}::{bad_id} —— {reason}")
    assert not violations, (
        "以下用例块**声称退役但从未退役**（仍在评测里跑、仍占分母）：\n  "
        + "\n  ".join(violations)
        + "\n　　出口二选一：① 真退役 ⇒ 写非空 `skip_reason`（含理由与重启条件）；"
        "② 保持 active ⇒ 删掉退役标记注释（不要留一句会骗人的话）。"
    )


def test_scan_surface_is_not_empty():
    """非空自证：标记短语必须还在仓内被命中（改名 / 删光都算形态变更，须同步改判据）。"""
    hits = sum(
        1
        for _filename, _case_id, block in _all_blocks()
        if RETIREMENT_MARKER in "\n".join(block)
    )
    assert hits >= 1, (
        f"退役标记短语 `{RETIREMENT_MARKER}` 在 `.github/cases/**` 里 0 命中 —— "
        "本判据的扫描面没了（改名 / 删光 / 迁移都会这样），此时它是恒绿空断言，不是通过。"
    )


def test_injection_red_proof():
    """注入式红证：三种合成块都走同一个 `find_violations()`。"""
    marker = f"    # 2026-11-26：本条**{RETIREMENT_MARKER}**（条目不删…）"
    bad = [("XX-001", ["  - id: XX-001", marker, "    title: 坏形态", '    skip_reason: ""'])]
    assert find_violations(bad), "标记 + 空 skip_reason 必须报出（否则判据没牙）"

    good_retired = [("XX-002", ["  - id: XX-002", marker, "    title: 真退役",
                                '    skip_reason: "[backend-contract] 承载体已删除"'])]
    assert find_violations(good_retired) == [], "标记 + 非空 skip_reason = 合法退役，不得误报"

    good_active = [("XX-003", ["  - id: XX-003", "    # 正常用例，没有退役标记",
                               "    title: 活用例", '    skip_reason: ""'])]
    assert find_violations(good_active) == [], "没有标记的活用例不得被本判据误报"
