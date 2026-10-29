# case_ids: API-010
"""`api.yml` 的用例必须声明契约标记（issue #8127）。

## 为什么

`.github/cases/api.yml` 判的是**接口契约**（mock 登录、租户隔离、DTO 字段、SSE 帧），
真值在 `traces.tests` 指向的 Java/TS 单测里，**不是 LLM 行为**。

没有 `skip_reason: "[backend-contract] …"` 标记时，agent-eval 会把用例里的**占位期望**
（`expectations: direct_reply`）当成行为断言计分 ⇒ 模型做对也可能判红：
- 实证（run 40895378323，2026-10-29）：`API-010` 被判「期望直答却调了工具」，
  而模型实际给了正确解释（「这属于系统内部的开发细节…」），只是顺带查了
  `settings_manage(get_settings/login_logs)`。它不是能力缺陷，是**计分通道错**。

## 判据

- `api.yml` 里**每一条**用例的 `skip_reason` 都必须以契约标记开头；
  新增未标记即红（`ALLOWLIST` 为空 ⇒ 没有"默认放行"）。
- **非空转**：文件里必须真的有 ≥20 条用例（否则本判据可能因为"一条都没读到"而假绿）。
- **判别力**：合成一条未标记用例 ⇒ 检测函数必须报出它。
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))

from assertion_taxonomy import CONTRACT_MARKERS  # noqa: E402

API_CASES = REPO_ROOT / ".github" / "cases" / "api.yml"

#: 允许的例外（必须逐条写明理由 + 跟单）。**空集** = 没有默认放行面。
ALLOWLIST: frozenset[str] = frozenset()


def _load_api_cases() -> list[dict]:
    data = yaml.safe_load(API_CASES.read_text(encoding="utf-8"))
    return list((data or {}).get("cases") or [])


def _unmarked(cases: list[dict]) -> list[str]:
    """没有契约标记的用例 id（`skip_reason` 不以任一标记开头）。"""
    return sorted(
        str(case.get("id"))
        for case in cases
        if str(case.get("skip_reason") or "").strip().startswith(CONTRACT_MARKERS)
        is False
    )


def test_api_file_really_has_cases() -> None:
    """防空转下界：读不到用例时，下面的"全部已标记"是假绿。"""
    cases = _load_api_cases()
    assert len(cases) >= 20, f"api.yml 只读到 {len(cases)} 条用例 —— 下界失效，判据可能空转"


def test_every_api_case_is_contract_marked() -> None:
    bad = [cid for cid in _unmarked(_load_api_cases()) if cid not in ALLOWLIST]
    assert bad == [], (
        "这些 api 域用例没有契约标记 ⇒ 会被 agent-eval 按行为断言计分（假红，实证 API-010）："
        f"{bad}\n修法：`skip_reason` 以 `[backend-contract]` 开头并写清真值载体"
        "（`traces.tests` 指向哪条单测）+ 为什么不是 LLM 行为。"
    )


def test_detector_has_red_power() -> None:
    """判别力自证：未标记的合成用例必须被检出（否则本文件是空判据）。"""
    fake = [
        {"id": "FAKE-1", "skip_reason": ""},
        {"id": "FAKE-2", "skip_reason": "[backend-contract] 真值在 Java 单测"},
        {"id": "FAKE-3", "skip_reason": None},
    ]
    assert _unmarked(fake) == ["FAKE-1", "FAKE-3"]
