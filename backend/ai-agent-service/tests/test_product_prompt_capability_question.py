# case_ids: CH-051
"""CH-051 的提示词面：能力询问（「能改商品名称吗」）先直接回答，不预调工具。

2026-10-19 单腿评测实测 CH-051 两次同指纹失败：`expected direct_reply but got tool calls`。
产品侧确认「商品名称可以改」（改名是 ✅）；本文件把修复固化在模型可见的**三处**：

① `prompts/product.md` 的能力询问规则；
② `MIBAO_CONFIG` 的 greeting/capabilities 直接回复点名「商品改名」；
③ `product_update` 工具描述的反例：只问「能不能改名」时直接回答，不调用
   `product_search` / `product_update`。

真实行为面由人工择时的 CH-051 定点评测验证（#4262：默认不自动跑真实 LLM）。
"""
from pathlib import Path

from app.agents.agents.mibao import MIBAO_CONFIG
from app.tools.product_update import ProductUpdateTool

PROMPT = (
    Path(__file__).resolve().parents[1]
    / "app" / "graph" / "skills" / "references" / "prompts" / "product.md"
)


def test_product_prompt_answers_capability_question_without_tools() -> None:
    text = PROMPT.read_text(encoding="utf-8")
    assert "能力询问" in text
    assert "可以改名" in text
    assert "product_search" in text and "product_update" in text
    assert "不要" in text
    assert "可以改名" in text


def test_mibao_direct_replies_name_product_rename() -> None:
    assert "商品改名" in MIBAO_CONFIG.direct_replies["capabilities"]
    assert "商品改名" in MIBAO_CONFIG.direct_replies["greeting"]
    assert "新名称" in MIBAO_CONFIG.direct_replies["capabilities"]


def test_product_update_tool_description_rejects_capability_tool_call() -> None:
    desc = ProductUpdateTool.description
    assert "能力询问" in desc
    assert "直接回答" in desc
    assert "product_search" in desc
    # 写执行路径仍必须保留（不能为了 CH-051 把真实改名流程删掉）
    assert "明确要求执行" in desc
