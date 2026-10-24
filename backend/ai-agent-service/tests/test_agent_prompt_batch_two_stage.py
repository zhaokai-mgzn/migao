# case_ids: PR-108
"""批量改价的「两段确认 + 批次号随卡走」规则必须真的进 system prompt（issue #7027）。

2026-10-19 B 端基线（run 39185677169）里 `PR-108` 首跑红在
`required_args[product_batch_update.batch_id](R5): 缺失或为空: batch_id` ——
agent preview 出了批次、也发了确认卡，但商家确认后的 execute **没带 batch_id**，
于是被工具按 `batch_preview_required` 拒掉（工具侧无锅：`_preview` 的返回里带
`data['batchId']`、message 也逐字念了它）。

⇒ 修法是把「批次号随卡走」写成 prompt 规则。本判据守两件事（铁律 11：声明存在 ≠ 可达）：
① 规则文本在 `references/prompts/product.md` 里；
② 它出现在**真正组装出来的 system prompt** 里（分层拼装没把它吃掉）。
"""

from __future__ import annotations

import sys
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
REPO = SERVICE.parents[1]
sys.path.insert(0, str(SERVICE))

PRODUCT_PROMPT = SERVICE / "app" / "graph" / "skills" / "references" / "prompts" / "product.md"
#: 规则的**内核**（不锚整句措辞：改措辞不该红，丢内核才该红）
REQUIRED_MARKERS = ("batchId", "batch_id", "execute", "确认卡")


def test_rule_text_is_in_the_product_prompt():
    text = PRODUCT_PROMPT.read_text(encoding="utf-8")
    missing = [m for m in REQUIRED_MARKERS if m not in text]
    assert missing == [], f"product.md 缺批量两段规则的内核标记：{missing}"


def test_rule_reaches_the_assembled_system_prompt():
    from app.graph.skills.base_skill import _build_system_prompt

    prompt = _build_system_prompt("product")
    missing = [m for m in REQUIRED_MARKERS if m not in prompt]
    assert missing == [], (
        f"组装出来的 product system prompt 里读不到内核标记 {missing} —— "
        "规则写了但没进模型（分层拼装把它吃掉 / 换了 skill 名）"
    )


def test_red_proof_marker_absence_is_detectable():
    """判别力自证：把规则内核拿掉后，同一套标记检查必须报缺。"""
    stripped = PRODUCT_PROMPT.read_text(encoding="utf-8").replace("batchId", "").replace("batch_id", "")
    missing = [m for m in REQUIRED_MARKERS if m not in stripped]
    assert "batchId" in missing and "batch_id" in missing
