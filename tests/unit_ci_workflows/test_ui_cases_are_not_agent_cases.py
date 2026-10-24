# case_ids: UI-123, UI-124
"""UI 用例不得以 `direct_reply` 占位混进 agent 评测（issue #7027）。

2026-10-19 的 B 端基线（run 39185677169）里 `UI-123` 判红：
`expected direct_reply (no tool) but got tool calls` —— 而它根本**不是 Agent 用例**：
`user_inputs` 是用户 2026-10-18 的报障原文、4 条 data_checks 全是 admin-web 前端的路由/链接断言，
`expectations: tool: direct_reply` 只是占位。同一形态的还有 `UI-124`（设计系统按钮）。

判据：`ui.yml` 里凡是「期望只有一个 `direct_reply`」的用例，必须声明**非空**
`skip_reason`（仓里既有口径 = `[backend-contract] …`，UI-001 起沿用）—— 否则它会作为
LLM 用例被执行，用 agent 行为去判前端契约（必然误红，且把真回归淹掉）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

UI_CASES = REPO / ".github" / "cases" / "ui.yml"
REQUIRED_PREFIX = "["  # 仓里既有口径：非 agent 面用例标 [backend-contract]（UI-001 起沿用）


def direct_reply_only(case: dict) -> bool:
    """期望里只有 `tool: direct_reply` 一条（UI 用例的占位形态）。"""
    exp = case.get("expectations") or []
    return len(exp) == 1 and isinstance(exp[0], dict) and exp[0].get("tool") == "direct_reply"


def misfiled_ui_cases(cases: list[dict]) -> list[str]:
    """`direct_reply` 占位却没声明 frontend-contract 豁免的用例 id（判据的纯函数内核）。"""
    out = []
    for case in cases:
        if not direct_reply_only(case):
            continue
        reason = (case.get("skip_reason") or "").strip()
        if not reason.startswith(REQUIRED_PREFIX):
            out.append(str(case.get("id")))
    return out


def test_direct_reply_only_ui_cases_declare_frontend_contract():
    doc = yaml.safe_load(UI_CASES.read_text(encoding="utf-8")) or {}
    bad = misfiled_ui_cases(doc.get("cases") or [])
    assert bad == [], (
        f"这些 ui.yml 用例只有 `direct_reply` 占位、却没声明 {REQUIRED_PREFIX} 豁免：{bad} —— "
        "它们会被当成 LLM 用例执行（agent 行为判前端契约 ⇒ 误红，issue #7027）"
    )


def test_red_proof_misfiled_case_is_detectable():
    """判别力自证：去掉 skip_reason 的同形态用例必须被判据抓到。"""
    synthetic = [
        {"id": "UI-999", "expectations": [{"tool": "direct_reply"}], "skip_reason": ""},
        {"id": "UI-998", "expectations": [{"tool": "direct_reply"}],
         "skip_reason": "[backend-contract] 已豁免"},
        {"id": "UI-997", "expectations": [{"tool": "product_search"}], "skip_reason": ""},
    ]
    assert misfiled_ui_cases(synthetic) == ["UI-999"]
