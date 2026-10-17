# case_ids: UI-079
"""客户端打字机：揭示层**不得绑流式生命周期**的类级元守卫（issue #7086）。

## 病（2026-10-17 实测）

黄金策电脑端的打字机（#5952）**实际是空转**：正文是一个 SSE `text` 事件**整段**到达、紧随 `done`
（后端 `backend/ai-agent-service/app/api/chat.py` 走节点级 `graph.astream(stream_mode="updates")`），
而揭示层把「流式结束 ⇒ 立刻等于全文」当不变量 ⇒ 揭示窗口只有几十~两百毫秒、**一帧都播不完**
（本机实测：`done` 之后第一次读数已是 37/37 全文）⇒ 用户看到「一次性刷出」。

存量用例之所以全绿：它们的夹具让流**长期开着**，从未重放「整段到达 + 紧随结束」这一真实事件序
—— 这就是本条要固化的**类**：判据与真实事件序不符 ⇒ 绿着空转。

## 本守卫守什么（让同类进不来）

1. **揭示层不得再读任何外部生命周期开关**：`frontend/admin-web/src/hooks/use-typewriter.ts` 的
   **代码**（去掉注释块后）里不得出现 `streaming` 标识符 —— 揭示只能由「内容是否在长」驱动
   （挂载即完整 ⇒ 首帧全文；否则逐字到完）。
2. **真实事件序判据必须在场**：组件用例文件里必须保留「整段到达 + 紧随结束」那一条
   （用例名含「真实事件序」），且它必须同时断言「中途可见 < 全长」与「最终 == 全长」。

红证（注入式，见 `test_guard_has_teeth`）：把旧行 `const snap = !streaming || …` 注入 hook 源码 ⇒ 判据 1 红；
把「中途可见 < 全长」那条断言从组件用例里删掉 ⇒ 判据 2 红；未注入时两条都不报（反向对照）。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / "frontend/admin-web/src/hooks/use-typewriter.ts"
COMPONENT_TEST = REPO_ROOT / "frontend/admin-web/tests/unit/components/MessageList-typewriter.test.tsx"

#: 真实事件序判据必须在场的最小标记集（用例名 + 两个关键读数）
_REAL_ORDER_MARKERS = (
    "真实事件序",
    "isStreaming: false",
    "expect(visibleText().length).toBeLessThan(FULL_TEXT.length)",
    "expect(visibleText()).toBe(FULL_TEXT)",
)

_BLOCK_COMMENT = re.compile(r"/\*[\s\S]*?\*/")
_LINE_COMMENT = re.compile(r"(?m)//[^\n]*")
_LIFECYCLE_TOKEN = re.compile(r"\bstreaming\b")


def _code_only(src: str) -> str:
    """去掉注释（块注释 + 行注释）—— 只留下**代码**。

    目的：本守卫禁的是「代码里读生命周期开关」，**不是**禁止在注释里解释这段历史
    （否则讲清楚病因的注释反而会把守卫喂红）。
    """
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", src))


def _lifecycle_gate_lines(src: str) -> list[str]:
    """代码里出现 `streaming` 标识符的行（空列表 = 揭示层不读任何生命周期开关）"""
    return [ln.strip() for ln in _code_only(src).splitlines() if _LIFECYCLE_TOKEN.search(ln)]


def _real_order_marker_gaps(src: str) -> list[str]:
    """真实事件序判据缺席的标记（空列表 = 判据在场）"""
    return [m for m in _REAL_ORDER_MARKERS if m not in src]


def test_hook_reveal_is_not_bound_to_lifecycle_switch() -> None:
    """判据 1：揭示层代码里不得出现 `streaming`（外部生命周期开关）"""
    hook_src = HOOK.read_text(encoding="utf-8")
    hits = _lifecycle_gate_lines(hook_src)
    assert hits == [], (
        "use-typewriter.ts 的代码里又出现了外部生命周期开关 `streaming` —— "
        "正文是整段到达、紧随 done（窗口几十~两百毫秒），把揭示绑在它上面会让打字机再次空转"
        f"（issue #7086）。命中行：{hits}"
    )


def test_component_test_replays_real_event_order() -> None:
    """判据 2：组件用例必须保留「整段到达 + 紧随结束」的真实事件序判据"""
    src = COMPONENT_TEST.read_text(encoding="utf-8")
    gaps = _real_order_marker_gaps(src)
    assert gaps == [], (
        "组件用例里缺了真实事件序判据的关键部分（#7086 的同类空转正是这样回来的）："
        f"缺失标记 = {gaps}；文件 = {COMPONENT_TEST.relative_to(REPO_ROOT)}"
    )


def test_guard_has_teeth() -> None:
    """判别力自证：两种坏形态在内存里各自判红；未注入 ⇒ 不报（反向对照）"""
    hook_src = HOOK.read_text(encoding="utf-8")
    test_src = COMPONENT_TEST.read_text(encoding="utf-8")

    # 反向对照：真实仓库状态两条都不报
    assert _lifecycle_gate_lines(hook_src) == []
    assert _real_order_marker_gaps(test_src) == []

    # 坏形态 ①：把旧设计的生命周期收敛行注入 hook ⇒ 判据 1 红
    injected_hook = hook_src.replace(
        "const snap = instant",
        "const snap = !streaming || instant",
        1,
    )
    assert injected_hook != hook_src, "注入点失效（源码结构变了）—— 守卫需同步维护"
    assert _lifecycle_gate_lines(injected_hook) != []

    # 坏形态 ②：把「中途可见 < 全长」这条断言摘掉 ⇒ 判据 2 红
    mutated_test = test_src.replace(
        "expect(visibleText().length).toBeLessThan(FULL_TEXT.length)",
        "",
    )
    assert mutated_test != test_src, "注入点失效（用例结构变了）—— 守卫需同步维护"
    assert _real_order_marker_gaps(mutated_test) != []
