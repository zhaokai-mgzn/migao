# case_ids: PG-090
"""issue #7507：B 端「生成加工单」指引必须指向**智能派单**（不是作业看板）。

用户 2026-10-23 裁定「为什么从订单可以直接生成加工单，而不是默认走智能派单流程？这里得限制下」
⇒ #7507 非加急走智能派单；#7634（用户 2026-10-24「一起收，也要统一走智能派单」）把所有订单都收进派单页。B 端 agent 的写能力自 #5247 起已下线
（`processing_order_generate` 无 skill 绑定、模型不可达），但**文案是会漂的那一半**：
`prompts/order.md` 与工具 description 必须与新口径同源，否则下一次恢复写能力时又把模型教错。

红证：
- 把 prompts/order.md 里「生成加工单…不可用」那两处指路改回「作业看板」⇒ 本文件红；
- 把 `ProcessingOrderGenerateTool.description` 的「智能派单 / 非加急」去掉 ⇒ 本文件红。
"""

from pathlib import Path

PROMPT = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "graph"
    / "skills"
    / "references"
    / "prompts"
    / "order.md"
)

TOOL = Path(__file__).resolve().parents[1] / "app" / "tools" / "processing_order_generate.py"


def _prompt_text() -> str:
    return PROMPT.read_text(encoding="utf-8")


def test_generate_guidance_points_to_pool_not_board() -> None:
    """「生成加工单不在能力内」的每一行指路都必须指向智能派单。"""
    lines = [
        line for line in _prompt_text().splitlines()
        if "生成加工单" in line and "不可用" in line
    ]
    assert lines, "order.md 丢了「生成加工单不在能力内」的指路行 —— 模型会以为可以代办"
    for line in lines:
        assert "智能派单" in line, f"指路没有指向智能派单：{line}"
        assert "作业看板" not in line, (
            f"旧指引（生成加工单 → 作业看板）必须退场：作业看板只能看、不能生成：{line}"
        )


def test_prompt_states_no_direct_dispatch_exception() -> None:
    """#7634：**不再有直派例外** —— 提示词里不许再出现「加急可直接生成」这类旧口径。

    红证：把 `prompts/order.md` 的指路改回「加急单可在订单详情直接生成」⇒ 本用例红。
    """
    text = _prompt_text()
    assert "智能派单" in text
    assert "加急" in text, "加急仍要在提示词里被讲到（模型要能回答商家「加急怎么办」）"
    assert "订单详情直接生成" not in text, (
        "旧口径（加急可在订单详情直接生成）必须退场：直派入口已对所有订单关闸（issue #7634）"
    )


def test_tool_description_carries_the_restriction() -> None:
    """工具语义同口径：所有订单（含待付款 / 加急）都去智能派单页，不再有直派例外。"""
    text = TOOL.read_text(encoding="utf-8")
    assert "智能派单" in text
    assert "所有" in text
    assert "加急" in text
    assert "可直接生成" not in text
