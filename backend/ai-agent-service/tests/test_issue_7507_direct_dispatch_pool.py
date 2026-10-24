# case_ids: PG-090
"""issue #7507：B 端「生成加工单」指引必须指向**智能派单**（不是作业看板）。

用户 2026-10-23 裁定「为什么从订单可以直接生成加工单，而不是默认走智能派单流程？这里得限制下」
⇒ 非加急订单默认走智能派单、加急订单保留直派。B 端 agent 的写能力自 #5247 起已下线
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


def test_prompt_states_urgent_exception() -> None:
    """加急例外必须在提示词里说清（否则模型会把加急单也一律劝去派单页）。"""
    assert "加急" in _prompt_text()


def test_tool_description_carries_the_restriction() -> None:
    """工具语义同口径：非加急 ⇒ 智能派单；加急 ⇒ 可直派。"""
    text = TOOL.read_text(encoding="utf-8")
    assert "智能派单" in text
    assert "非加急订单" in text
    assert "加急订单" in text
