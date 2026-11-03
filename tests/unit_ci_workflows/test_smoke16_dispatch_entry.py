# case_ids: MC-187
"""#7743：冒烟旅程 16- 的「生成作业单」必须走**智能派单唯一入口**，不许退化成可跳过的空判据。

病（issue 逐字）：自 #7634（销售订单只读、直派入口全关）起，订单详情页**已没有任何生成/流转按钮**，
而 16- 仍在 `getByRole('button', { name: /生成加工单/ })` 上 `waitVisible` —— 不可见就静默跳过，
随后断言 `.po-print-area` 作业单块出现，而**没有生成 ⇒ 该块恒空**。
静态选择器守卫之所以假绿，是因为「文案存在 ≠ 按钮可达」（§19.1 的空判据形态）。

本判据钉三件：
① 16- 体内**不再**驱动「生成加工单」按钮（旧入口已删）；
② 16- 体内**必须**出现智能派单的唯一入口 `pool-dispatch-batch`（`/production/pool` 一键合并派单）；
③ 派单**每一步失败都必须 throw**，不许 `if (visible) click` 那种「不可见就当年过了」的形态。
"""
from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SPEC = REPO_ROOT / "scripts" / "ui-smoke-merchant" / "spec.mjs"

JOURNEY_16 = "16-order-detail-processing-order"


def _journey_body(spec_text: str, name: str) -> str:
    """取 `journey('<name>')` 之后到**下一个** `journey('` 注册点之前的整段（= 该旅程的实现体）。"""
    head = spec_text.find(f"journey('{name}')")
    assert head != -1, f"spec.mjs 里找不到旅程 {name} 的注册点"
    nxt = spec_text.find("journey('", head + len(name) + 12)
    return spec_text[head:] if nxt == -1 else spec_text[head:nxt]


def test_journey16_drives_the_pool_dispatch_entry():
    body = _journey_body(SPEC.read_text(encoding="utf-8"), JOURNEY_16)
    assert "pool-dispatch-batch" in body, (
        "16- 旅程没有走智能派单入口（`pool-dispatch-batch`）—— 自 #7634 起这是**生成作业单的唯一路径**"
    )
    assert "getByRole('button', { name: /生成加工单/ })" not in body, (
        "16- 旅程仍在驱动「生成加工单」按钮 —— 该按钮自 #7634 起已不在订单详情页上"
        "，`waitVisible` 只会静默跳过（issue #7743 的病根）"
    )


def test_journey16_fails_closed_at_every_dispatch_step():
    """派单链路的每一步都必须带 `throw`：不可见 ⇒ 失败，不是「本步无需做」。"""
    body = _journey_body(SPEC.read_text(encoding="utf-8"), JOURNEY_16)
    start, end = body.find("pool-line-"), body.find("pool-dispatch-error")
    assert start != -1 and end != -1, "16- 体内找不到作业单生成段的起止锚点"
    dispatch = body[start: end + 400]
    assert dispatch, "16- 体内找不到作业单生成段（pool-line- → pool-dispatch-batch）"
    throws = re.findall(r"throw new Error\(", dispatch)
    assert len(throws) >= 4, (
        "作业单生成段的 fail-closed 出口少于 4 个 —— 池里查不到本单 / 勾选框禁用 / 预览没出 / 派单按钮缺席"
        f"至少四条都要 throw，实测只有 {len(throws)} 条"
    )
    assert "if (await waitVisible(genBtn" not in body, "16- 仍是「可见就点、不可见就算过」的旧形态"
    # 真动作必须真发生：勾选 + 点派单，两个 await 都必须在（注释掉任一个 ⇒ 本判据红）
    assert re.search(r"^\s*await pick\.check\(\)\s*$", dispatch, re.M), (
        "16- 没有真的勾选待派行（`await pick.check()` 缺席或已被注释）—— 不勾选就点派单 = 空判据"
    )
    assert re.search(r"^\s*await batchBtn\.click\(\)\s*$", dispatch, re.M), (
        "16- 没有真的点「一键合并派单」（`await batchBtn.click()` 缺席或已被注释）—— 点都不点就断言作业单块 = 空判据"
    )
