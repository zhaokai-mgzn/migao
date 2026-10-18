# case_ids: OR-030, DF-003, DF-010
"""B 端用例只能引用**可达**工具（issue #6984 / #7291 的范式判据）。

病灶（2026-10-19 现取）：三条 B 端用例的 expectations 写成
`tool: direct_reply or validate_input`，而 `validate_input` **不在 mibao 可达集**
（绑定 skill ∪ 兜底 general 的 `tool_names` 均不含）⇒ 第二条支**恒假**：
看起来断言了两条，实际只剩一条 —— 空断言。

本判据把「用例期望」也纳入「声明 = 投影」的射程：
- 正向引用（`expectations[].tool` / `must_succeed[].tool` / `required_args` 键 /
  `order_before`）必须是 mibao 真实可达的工具，或哨兵 `direct_reply`；
- **不覆盖** `forbidden_tools` / `must_fail`（负向引用）；「对不可达工具的禁区」是
  恒真断言，属另一族问题（#4043 跟踪），不在本判据射程内。

判别力自证：`test_discriminating_power` 用一条合成坏用例（引用不可达工具）跑同一函数，
必须报出它 —— 防止判据退化成「永远绿」。
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

_CASES_DIR = pathlib.Path(__file__).resolve().parents[3] / ".github" / "cases"

#: 不是工具、但可以出现在 expectations.tool 里的哨兵（runner 的 direct 分支语义）。
_SENTINELS = frozenset({"direct_reply"})

_POSITIVE_FIELDS = ("expectations", "must_succeed")


def _split_tool(value: object) -> list[str]:
    return [p.strip() for p in str(value).replace(" or ", "|").split("|") if p.strip()]


def _strip_annotation(raw: str) -> str:
    """`interact[choice:processing_items]` → `interact`（方括号是 runner 的语义注解，不是工具名）。"""
    return raw.split("[", 1)[0].strip()


def _positive_refs(case: dict) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for field in _POSITIVE_FIELDS:
        for entry in case.get(field) or []:
            if isinstance(entry, dict) and entry.get("tool"):
                refs.append((field, str(entry["tool"])))
    # required_args 有两种形态：dict（键=工具名）或 list[dict]（条目里带 tool）
    required = case.get("required_args")
    if isinstance(required, dict):
        refs.extend(("required_args", str(k)) for k in required)
    elif isinstance(required, list):
        for entry in required:
            if isinstance(entry, dict) and entry.get("tool"):
                refs.append(("required_args", str(entry["tool"])))
            elif isinstance(entry, str):
                refs.append(("required_args", entry))
    for item in case.get("order_before") or []:
        for part in str(item).split(" before "):
            if part.strip():
                refs.append(("order_before", _strip_annotation(part)))
    return refs


def find_unreachable_cases(cases: list[dict], reachable: frozenset) -> list[str]:
    """返回形如 `file::case::field::tool` 的违规清单（纯函数，便于判别力自证）。"""
    allowed = set(reachable) | _SENTINELS
    bad: list[str] = []
    for case in cases:
        if case.get("persona") != "mibao":
            continue
        for field, raw in _positive_refs(case):
            for tool in _split_tool(raw):
                if tool not in allowed:
                    bad.append(f"{case.get('_file', '?')}::{case.get('id', '?')}::{field}::{tool}")
    return bad


def _load_b_end_cases() -> list[dict]:
    cases: list[dict] = []
    for path in sorted(_CASES_DIR.glob("*.yml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            continue
        for case in data.get("cases") or []:
            case = dict(case)
            case["_file"] = path.name
            cases.append(case)
    return cases


def test_b_end_cases_only_expect_reachable_tools():
    from app.agents.capability_boundary import mibao_reachable_tool_names

    offenders = find_unreachable_cases(_load_b_end_cases(), mibao_reachable_tool_names())
    assert not offenders, (
        "B 端用例引用了 mibao **不可达**的工具（空断言，看起来断言了实际恒假）：\n"
        + "\n".join(offenders)
        + "\n处理：要么改成真实可达的工具，要么收窄断言（如 direct_reply）。"
    )


def test_discriminating_power():
    """判别力自证：合成一条引用不可达工具的用例 ⇒ 必须被判出。"""
    reachable = frozenset({"product_search", "order_query"})
    fake = {
        "_file": "synthetic.yml",
        "id": "XX-999",
        "persona": "mibao",
        "expectations": [{"tool": "direct_reply or validate_input"}],
        "must_succeed": [{"tool": "order_create"}],
        "order_before": ["validate_input before order_create"],
    }
    bad = find_unreachable_cases([fake], reachable)
    assert "synthetic.yml::XX-999::expectations::validate_input" in bad
    assert any("must_succeed::order_create" in b for b in bad)
    assert any("order_before::validate_input" in b for b in bad)
    # 反控：可达工具 + 哨兵不报
    ok = {"_file": "synthetic.yml", "id": "XX-998", "persona": "mibao",
          "expectations": [{"tool": "direct_reply or product_search"}]}
    assert find_unreachable_cases([ok], reachable) == []
