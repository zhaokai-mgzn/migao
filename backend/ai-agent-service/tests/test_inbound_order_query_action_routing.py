# case_ids: PR-005
"""`inbound_order_query` 的 action 选择必须是**确定口径**（issue #8300 PR-005 两次实测）。

## 现场

全档 run `41285244288` + 定点 `41286316979`：问「再看看这批货是哪几张入库单入的库」，
模型两次都给了 `action=list`（用例要的是 `batches`）—— 旧说明只写「list（入库单列表）/
batches（批次视图）」，**没写什么问法对应哪个 action**，于是靠猜、且每轮猜得不一样。

## 判据

工具说明必须写明三类问法各自的 action（批次来源 ⇒ batches / 最近列表 ⇒ list / 单张明细 ⇒ detail），
且三类都在同一段里（模型读的是整段说明，分散写会被忽略）。
红证：摘掉这段 ⇒ 本判据红（已实跑）。
"""
from pathlib import Path

TOOL = (Path(__file__).resolve().parents[1] / "app" / "tools" / "inbound_order_query.py")


def _routing_line() -> str:
    text = TOOL.read_text(encoding="utf-8")
    for line in text.splitlines():
        if "选 action 的硬口径" in line:
            return line
    raise AssertionError("工具说明缺「选 action 的硬口径」—— 模型会退回靠猜（PR-005 的现场）")


def test_routing_rule_names_all_three_actions():
    line = _routing_line()
    for action in ("batches", "list", "detail"):
        assert action in line, f"路由口径没点名 action={action}"


def test_routing_rule_pins_batch_origin_question_to_batches():
    line = _routing_line()
    assert "哪几张入库单" in line and "batches" in line, (
        "「这批货是哪几张入库单入的库」必须明确落到 batches（PR-005 就死在这里）")
