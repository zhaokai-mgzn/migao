# case_ids: CH-021, API-004
"""同页填充的**瞬时通道**（issue #5368 包 2 · 硬约束 1 的后端半边）。

## 判据

| # | 判据 | 断言 |
|---|---|---|
| 1 | 载荷**只在 SSE 响应体**里（进不了 URL / access log / Referer） | `SSEEvent.page_fill` 恰好两行（`event:` + `data:`），载荷在 body 内 |
| 2 | 🔴 **不落库、不落盘** | `chat.py` 发 `page_fill` 的那段**不写 `last_interactive_payload`** —— 一旦写了，收尾 `save_message(interactive=…)` 就会把整张计划（含订单侧收货信息）**落进会话 metadata** |
| 3 | **值不进日志** | 该段只打 `log_summary(plan)`（target/计数/键名），不拼字段值 |

判据 2 的机械口径是本包**唯一的落盘面**，故用**窗口式读取**（按锚点取那段代码的可读窗口 +
窗口覆盖自证），注入式红证证明它有判别力：
往窗口里塞一行 `last_interactive_payload = data` ⇒ 本文件的断言必须变红。
⚠️ 不写「整份 chat.py 里没有某个串」那种全局断言 —— 那个串在**别处**合法存在（interact 路径），
全局口径只会得到一个恒绿的假判据（本仓已多次踩到「判据读错对象」）。
"""
from pathlib import Path

from app.api.sse import SSEEvent
from app.vision.deep_channel import log_summary

CHAT_PY = (
    Path(__file__).resolve().parents[1] / "app" / "api" / "chat.py"
)

#: 窗口锚点 —— `chat.py` 里同页填充那段的自陈标记（本文件按它取**位置性**证据）
ANCHOR = "同页填充（issue #5368"
WINDOW = 22


def page_fill_window(source: str) -> str:
    """取 `chat.py` 里同页填充那段的可读窗口（锚点上下各 WINDOW 行）。"""
    lines = source.split("\n")
    hits = [i for i, line in enumerate(lines) if ANCHOR in line]
    assert hits, f"锚点漂移：chat.py 里找不到 {ANCHOR!r} —— 先更新本用例的锚点，别让窗口空跑"
    start = hits[0]
    return "\n".join(lines[start:start + WINDOW])


class TestPayloadTravelsInTheResponseBody:
    def test_event_has_exactly_two_lines_and_the_payload_is_json(self):
        import json

        plan = {"component": "page_fill", "target_type": "product", "fields": []}
        raw = SSEEvent.page_fill(plan)
        lines = [line for line in raw.split("\n") if line]
        assert len(lines) == 2
        assert lines[0] == "event: page_fill"
        assert lines[1].startswith("data: ")
        assert json.loads(lines[1][len("data: "):]) == plan

    def test_event_is_body_only_never_a_query_string(self):
        """URL 形态的副作用（access log / Referer）在这里**结构性不可能**：
        载荷在 body，事件名是固定串，没有任何拼进 query 的通道。"""
        raw = SSEEvent.page_fill({"component": "page_fill", "target_type": "order", "fields": []})
        assert "?" not in raw
        assert raw.endswith("\n\n")


class TestPageFillIsTransientNeverPersisted:
    def test_the_emitting_block_never_touches_the_interactive_persistence_slot(self):
        window = page_fill_window(CHAT_PY.read_text(encoding="utf-8"))
        assert "SSEEvent.page_fill" in window, "窗口没盖住发射点 ⇒ 本断言是空跑（先修窗口）"
        assert "last_interactive_payload" not in window

    def test_the_emitting_block_logs_only_the_safe_summary(self):
        window = page_fill_window(CHAT_PY.read_text(encoding="utf-8"))
        assert "log_summary" in window
        assert "f\"[chat/page-fill]" in window

    def test_safe_summary_carries_no_field_value(self):
        plan = {
            "component": "page_fill",
            "target_type": "order",
            "fields": [
                {"key": "customer_phone", "label": "电话", "value": "13800138000",
                 "source": "[图片识别]", "reason": None, "candidates": [],
                 "note": None, "note_source": None},
            ],
        }
        summary = log_summary(plan)
        assert "13800138000" not in summary
        assert "customer_phone" in summary

    def test_window_reader_has_discriminative_power(self):
        """**注入式红证**：往窗口里塞一行持久化赋值 ⇒ 上面那条断言必须变红。"""
        source = CHAT_PY.read_text(encoding="utf-8")
        window = page_fill_window(source)
        injected = window.replace(
            "yield SSEEvent.page_fill(fill_plan)",
            "last_interactive_payload = fill_plan\n                yield SSEEvent.page_fill(fill_plan)",
            1,
        )
        assert injected != window, "注入没生效（锚点漂移）⇒ 先修注入点，别把「没变红」当绿"
        assert "last_interactive_payload" in injected