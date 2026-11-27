# case_ids: MC-012
"""静态 CI 结构用例必须带 ``skip_reason``（issue #9220）。

## 病（run 45647252503 实测）

`MC-355` ~ `MC-370` 是**纯静态** CI 结构判据：`traces.tests` 全在
`tests/unit_ci_workflows/`，`expectations` 只有占位 `direct_reply`，判定完全由
pytest 承担。它们却缺 `skip_reason` ⇒ 真实 LLM 的 normal 档把它们当行为用例跑
（input 是标题、没有 `user_inputs`），`direct_reply` 必然红 —— 16 条假红把
`completion.ok` 直接拖成 false。

同族 `MC-354` 早已带 `[backend-contract]`，说明缺口是**漏登记**而非口径分歧。

## 判据

一条用例同时满足下列全部条件 ⇒ 视为「静态 CI 结构用例」，必须有非空 `skip_reason`：

1. `traces.tests` 非空，且**每一条**都在 `tests/unit_ci_workflows/` 下；
2. `expectations` 只含 `direct_reply`（或为空），且**没有**结构化断言面
   （`assertion_taxonomy.NON_TOOL_ASSERTION_FACES`，现取 = `kf_judge`）；
3. 没有 `must_succeed` / `db_verify` / `forbidden_tools` / `required_args` / `order_before`
   这些只对真实 LLM 跑有意义的断言。

现取 170 条命中，**全部已 skip**（本判据只为防新增漏登记）；把任一条的
`skip_reason` 删掉 ⇒ 本判据具名红。
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / ".github"))

from assertion_taxonomy import expectation_faces  # noqa: E402
CASES = REPO / ".github" / "cases"

#: 只对真实 LLM 跑有意义的断言键；出现任一 ⇒ 不属「纯静态」用例。
LLM_ONLY_KEYS = (
    "must_succeed", "db_verify", "forbidden_tools", "required_args", "order_before",
)


def _cases() -> list[dict]:
    out = []
    for path in sorted(CASES.glob("*.yml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        items = data.get("cases", []) if isinstance(data, dict) else data
        assert isinstance(items, list), f"{path.name}: 不是用例列表"
        out.extend(items)
    assert out, f"{CASES} 下没有读到任何用例（fail-closed）"
    return out


def test_static_ci_structure_cases_are_skipped():
    offenders = []
    for case in _cases():
        tests = (case.get("traces") or {}).get("tests") or []
        if not tests or not all(str(t).startswith("tests/unit_ci_workflows/") for t in tests):
            continue
        tools = [str(e.get("tool") or "") for e in (case.get("expectations") or [])
                 if isinstance(e, dict)]
        if any(t and t != "direct_reply" for t in tools):
            continue
        # 结构化断言面（现取 = `kf_judge`，微信客服判定 JSON 面）同样**只对真实 LLM 跑有意义**
        # ⇒ 有它就不是"纯静态 CI 结构用例"（否则真行为用例会被逼着标 skip = 把评测面越缩越小；
        # 2026-11-27 实测 KF-031~035 命中本条件）。未登记的面名不算（fail-closed）。
        if expectation_faces(case):
            continue
        if any(case.get(key) for key in LLM_ONLY_KEYS):
            continue
        if not str(case.get("skip_reason") or "").strip():
            offenders.append(f"{case.get('id')}（traces={tests[:2]}…）")
    assert not offenders, (
        "这些静态 CI 结构用例缺 skip_reason ⇒ 真实 LLM 评测会把它们当行为用例跑并必然红：\n  "
        + "\n  ".join(offenders)
        + "\n修法：补 `skip_reason: \"[backend-contract] …\"`（机器判红通道写进 traces.tests）"
    )
