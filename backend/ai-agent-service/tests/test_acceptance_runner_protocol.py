# case_ids: CH-010, OR-017, OR-018
"""验收 runner 的协议合规能力（issue #3367，acceptance-protocol §4/§5/§6.2）。

协议 §6.2 明确列了三处差距：
  1. 只渲染不判定 → 需要 L1/L2 断言执行；
  2. 场景 JSON 无验收点声明 → 需要 `checks: [{level,type,expect,ref}]`；
  3. 无报告输出 → 需要 §4.2 模板。
另有两条协议铁律要落到工具上：
  · §4.1「任何一轮的 AI 原文不得省略」→ 渲染不得截断；
  · §2 剧本要含**点卡 / 换窗口**等真实动作 → 需要 click 动作与新会话轮。

本测试只覆盖**可机器判定**的部分（断言求值、点卡协议、会话切换、报告骨架）；
UA（用户体验）判定按协议由 AI 用户代理完成，工具只负责把它标出来。
"""
import importlib.util
import json
from pathlib import Path

RUNNER = (Path(__file__).resolve().parents[3] / "tests" / "agent_eval"
          / "acceptance_runner.py")


def _ar():
    spec = importlib.util.spec_from_file_location("migao_acceptance_runner", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ar = _ar()


def _round(n, **kw):
    base = {"round": n, "user_text": "", "user_images": 0, "ai_text": "",
            "tools": [], "interactive": [], "error": None}
    base.update(kw)
    return base


class TestCheckEvaluation:
    """L1/L2 断言求值（协议 §3：关键行为必须机器可判）。"""

    def _eval(self, checks, rounds):
        return ar.evaluate_checks(checks, rounds)

    def test_tool_called_pass_and_fail(self):
        rounds = [_round(1, tools=[{"name": "order_create", "args": {}}])]
        assert self._eval([{"level": "L1", "type": "tool_called",
                            "expect": "order_create"}], rounds) == []
        bad = self._eval([{"level": "L1", "type": "tool_called",
                           "expect": "aftersale_create"}], rounds)
        assert bad and "aftersale_create" in bad[0]["detail"]

    def test_tool_not_called(self):
        rounds = [_round(1, tools=[{"name": "order_create", "args": {}}])]
        bad = self._eval([{"level": "L1", "type": "tool_not_called",
                           "expect": "order_create"}], rounds)
        assert bad, "写工具被调用了就必须报违规（越权/误操作下限）"

    def test_round_anchor_limits_scope(self):
        """`ref: R2` 只在该轮判定 —— 否则"任意一轮命中即过"（协议点名的旧缺陷）。"""
        rounds = [_round(1, tools=[{"name": "product_search", "args": {}}]),
                  _round(2, tools=[])]
        assert self._eval([{"level": "L1", "type": "tool_called",
                            "expect": "product_search", "ref": "R1"}], rounds) == []
        bad = self._eval([{"level": "L1", "type": "tool_called",
                           "expect": "product_search", "ref": "R2"}], rounds)
        assert bad, "轮次锚定必须生效（R2 没调用就不能算过）"

    def test_no_error_check(self):
        rounds = [_round(1, error="boom"), _round(2)]
        bad = self._eval([{"level": "L1", "type": "no_error"}], rounds)
        assert bad and "R1" in bad[0]["detail"]
        assert self._eval([{"level": "L1", "type": "no_error", "ref": "R2"}], rounds) == []

    def test_card_shown_check(self):
        rounds = [_round(1, interactive=[{"type": "confirm", "title": "请确认订单信息"}])]
        assert self._eval([{"level": "L1", "type": "card_shown",
                            "expect": "confirm"}], rounds) == []
        bad = self._eval([{"level": "L1", "type": "card_shown",
                           "expect": "form"}], rounds)
        assert bad

    def test_text_contains_and_forbidden(self):
        rounds = [_round(1, ai_text="您的订单已创建，订单号 20260101000000001")]
        assert self._eval([{"level": "L2", "type": "ai_text_contains",
                            "expect": "订单号"}], rounds) == []
        bad = self._eval([{"level": "L2", "type": "ai_text_contains",
                           "expect": "物流单号"}], rounds)
        assert bad
        bad2 = self._eval([{"level": "L2", "type": "ai_text_not_contains",
                            "expect": "订单已创建"}], rounds)
        assert bad2, "禁词断言必须生效（反模式话术）"

    def test_unknown_check_type_fails_closed(self):
        bad = self._eval([{"level": "L1", "type": "nonsense", "expect": "x"}], [_round(1)])
        assert bad and "不支持" in bad[0]["detail"], "未知断言类型必须报错，不得静默跳过"

    def test_ua_level_is_not_machine_judged(self):
        """UA 条目由 AI 用户代理判定（协议铁律 4），工具不得假装判过。"""
        out = self._eval([{"level": "UA", "type": "understandable", "ref": "R1"}], [_round(1)])
        assert out == [], "UA 条目不该被机器判失败"
        assert ar.ua_items([{"level": "UA", "type": "understandable", "ref": "R1"},
                            {"level": "L1", "type": "no_error"}]), "UA 条目要被单独列出待判"


class TestTranscriptAndReport:
    def test_render_does_not_truncate_ai_text(self):
        long_text = "句" * 400
        out = ar.render({"id": "C-A1", "title": "t", "domain": "order",
                         "rounds": [_round(1, user_text="你好", ai_text=long_text)]})
        assert long_text in out, "协议 §4.1：任何一轮的 AI 原文不得省略（不得截断）"

    def test_transcript_has_protocol_shape(self):
        out = ar.render({"id": "C-A1", "title": "t", "domain": "order",
                         "rounds": [_round(1, user_text="我要下单",
                                           tools=[{"name": "order_create", "args": {"items": []}}],
                                           interactive=[{"type": "confirm", "title": "请确认订单信息"}],
                                           ai_text="已为您创建")]})
        for token in ("R1 用户", "🃏", "🔧", "💬", "order_create", "请确认订单信息"):
            assert token in out, f"transcript 缺 {token}"

    def test_report_skeleton_has_five_sections(self):
        md = ar.build_report({"id": "C-A1", "title": "旅程", "domain": "order"},
                             [{"level": "L1", "type": "no_error"}],
                             [], "abc1234", "2026-09-13")
        for sec in ("## 结论", "## 验收矩阵", "## 问题清单", "## 复核验收抽验", "## 沉淀记录"):
            assert sec in md, f"报告缺章节 {sec}（协议 §4.2 五项齐全）"


class TestScenarioActions:
    """剧本真实动作：点卡（前端协议）与换窗口（新会话）。"""

    def test_click_confirm_uses_confirm_value(self):
        prev = [_round(1, interactive=[{"type": "confirm", "title": "请确认订单信息",
                                        "confirmValue": "确认下单"}])]
        assert ar.resolve_action({"click": "confirm"}, prev) == "确认下单"

    def test_click_choice_first_option(self):
        prev = [_round(1, interactive=[{"type": "choice", "title": "选颜色",
                                        "options": [{"label": "米白", "value": "c1"}]}])]
        assert ar.resolve_action({"click": "first_option"}, prev) == "米白"

    def test_click_multiselect_uses_frontend_prefix(self):
        prev = [_round(1, interactive=[{"type": "choice", "multiSelect": True,
                                        "multiSelectSubmitPrefix": "已选加工项：",
                                        "options": [{"label": "纳米圈打孔 ¥8/米", "value": "pi1"}]}])]
        out = ar.resolve_action({"click": "first_option"}, prev)
        assert out.startswith("已选加工项：") and "纳米圈打孔" in out, \
            "多选提交必须按前端协议（前缀+标签），否则模型看不懂选了什么"

    def test_no_card_click_falls_back_to_text(self):
        assert ar.resolve_action({"click": "confirm", "fallback": "确认"}, [_round(1)]) == "确认"

    def test_auto_click_answers_whatever_card_is_pending(self):
        """`click: "auto"`：**有什么卡答什么卡**（真实顾客行为）。

        为什么必须有：剧本用固定 `click` 时，卡的**顺序**随模型变化（本 session 实测
        C-A1：R5 期待 confirm 卡、实际是 form 卡 → 脚本答不上 → 后续轮次全错位，
        评测面变成"脚本对齐度"而不是"产品行为"）。
        评测 harness 早就用 `auto_respond` 协议解决了这个问题；验收剧本必须同样处理，
        否则剧本红灯会把**剧本问题**报成**产品问题**（归因方向错）。
        """
        # confirm 卡在 → 回 confirmValue
        prev = [_round(1, interactive=[{"type": "confirm", "confirmValue": "确认下单"}])]
        assert ar.resolve_action({"click": "auto", "fallback": "确认"}, prev) == "确认下单"
        # form 卡在 → 回 __FORM__|{json}（前端表单提交协议），字段取卡上自带值
        prev = [_round(1, interactive=[{"type": "form", "title": "请确认收货信息",
                                        "formFields": [{"key": "customer_name", "value": "张三", "label": "收货人"},
                                                       {"key": "customer_phone", "value": "13800138000"}]}])]
        out = ar.resolve_action({"click": "auto", "fallback": "确认"}, prev)
        assert out.startswith("__FORM__|"), f"form 卡必须按 __FORM__ 协议提交，实际 {out!r}"
        assert "张三" in out
        # choice 卡在 → 回首个选项标签
        prev = [_round(1, interactive=[{"type": "choice", "title": "选颜色",
                                        "options": [{"label": "白色", "value": "c1"}]}])]
        assert ar.resolve_action({"click": "auto", "fallback": "确认"}, prev) == "白色"
        # 无卡 → fallback 文本
        assert ar.resolve_action({"click": "auto", "fallback": "数量 3 米"}, [_round(1)]) == "数量 3 米"

    def test_auto_click_prefers_confirm_over_form(self):
        """一张轮里有多种卡时，优先答**最推进流程**的那张（confirm > choice > form）——
        与评测 harness 的优先级一致，避免两套优先级漂移。"""
        prev = [_round(1, interactive=[
            {"type": "form", "formFields": [{"key": "a", "value": "1"}]},
            {"type": "confirm", "confirmValue": "确认下单"},
        ])]
        assert ar.resolve_action({"click": "auto", "fallback": "x"}, prev) == "确认下单"

    def test_new_session_round_is_declared(self):
        assert ar.wants_new_session({"text": "我又来了", "session": "new"}) is True
        assert ar.wants_new_session({"text": "继续"}) is False


class TestScenarioFlow:
    """`run_scenario` 的动作流（点卡 / 换窗口）——用假 send 跑，不打网络。"""

    def _run(self, scenario, events):
        import asyncio
        seq = list(events)
        sent = []

        new_calls = []

        async def fake_new(token):
            new_calls.append(1)
            return f"sess-{len(new_calls)}"      # 按**建会话次数**编号（不是按发消息次数）

        async def fake_close(token, sid):
            sent.append(("__close__", sid))

        async def fake_send(sid, token, text, images=None, **kwargs):
            sent.append((sid, text))
            return seq.pop(0) if seq else {"text": "", "tool_calls": [],
                                           "tool_results": [], "interactive": [],
                                           "cards": [], "error": None, "done": True}

        orig = (ar._new_session, ar._close_session, ar.send)
        ar._new_session, ar._close_session, ar.send = fake_new, fake_close, fake_send
        try:
            return asyncio.run(ar.run_scenario(scenario, "tok")), sent
        finally:
            ar._new_session, ar._close_session, ar.send = orig

    def test_click_rounds_send_card_answers(self):
        sc = {"id": "C-A1", "title": "t", "rounds": [
            {"text": "我要下单"},
            {"click": "confirm", "fallback": "确认"},
        ]}
        events = [
            {"text": "请确认", "tool_calls": [], "tool_results": [],
             "interactive": [{"type": "confirm", "confirmValue": "确认下单"}],
             "cards": [], "error": None, "done": True},
            {"text": "已下单", "tool_calls": [], "tool_results": [], "interactive": [],
             "cards": [], "error": None, "done": True},
        ]
        res, sent = self._run(sc, events)
        assert sent[1][1] == "确认下单", f"点卡轮应发 confirmValue，实际 {sent[1][1]!r}"
        assert res["rounds"][1]["user_text"] == "确认下单"

    def test_new_session_closes_and_switches(self):
        sc = {"id": "C-A2", "title": "t", "rounds": [
            {"text": "第一窗口"},
            {"text": "我又回来了", "session": "new"},
        ]}
        res, sent = self._run(sc, [])
        assert ("__close__", "sess-1") in sent, "换窗口前必须关闭旧会话（协议 §2.2 生命周期）"
        assert res["sessions"] == ["sess-1", "sess-2"], f"应记录两个会话: {res['sessions']}"
        assert res["rounds"][1]["session"] == "sess-2"

    def test_render_shows_session_switch(self):
        out = ar.render({"id": "C-A2", "title": "t", "domain": "chat", "rounds": [
            {"round": 1, "session": "s1", "user_text": "a", "user_images": 0,
             "ai_text": "", "tools": [], "interactive": [], "error": None},
            {"round": 2, "session": "s2", "user_text": "b", "user_images": 0,
             "ai_text": "", "tools": [], "interactive": [], "error": None},
        ]})
        assert "换窗口" in out, "transcript 必须标出换窗口（证据要能看出会话边界）"


class TestRepeatUntilRound:
    """`repeat_until`：协作型顾客**一直答卡直到目标达成**（issue #3379 剧本方差）。

    为什么要它：剧本的轮数是**固定**的，而 agent 的卡序与轮数随模型变化 ——
    实测 C-A1 在 8 轮里有时走不到下单（同代码同剧本交替出现，验收 2 条违规：
    「confirm 卡未出现」「order_create 未调用」）。这类方差会训练人忽略验收红灯。
    `repeat_until` 把"轮数"从**剧本假设**变成**产品事实**：目标没达成就继续合作下去，
    达成就停（并记录实际用了多少轮 —— 那也是有价值的能力证据）。
    """

    def _run(self, scenario, events):
        import asyncio
        seq = list(events)
        sent = []

        async def fake_new(token):
            return "s1"

        async def fake_close(token, sid):
            return None

        async def fake_send(sid, token, text, images=None, **kwargs):
            sent.append(text)
            return seq.pop(0) if seq else {"text": "", "tool_calls": [], "tool_results": [],
                                           "interactive": [], "cards": [], "error": None, "done": True}

        orig = (ar._new_session, ar._close_session, ar.send)
        ar._new_session, ar._close_session, ar.send = fake_new, fake_close, fake_send
        try:
            return asyncio.run(ar.run_scenario(scenario, "tok")), sent
        finally:
            ar._new_session, ar._close_session, ar.send = orig

    def _ev(self, tools=(), cards=()):
        return {"text": "好的", "tool_calls": [{"name": t, "args": {}} for t in tools],
                "tool_results": [], "interactive": list(cards), "cards": [],
                "error": None, "done": True}

    def test_stops_when_goal_reached(self):
        sc = {"id": "C-A1", "title": "t", "rounds": [
            {"text": "我要买窗帘"},
            {"repeat_until": {"tool_called": "order_create", "max": 5},
             "click": "auto", "fallback": "确认"},
        ]}
        # 第 3 次重复时下单成功 → 应停止（总轮数 = 1 + 3）
        events = [self._ev(), self._ev(cards=[{"type": "confirm", "confirmValue": "确认下单"}]),
                  self._ev(cards=[{"type": "confirm", "confirmValue": "确认下单"}]),
                  self._ev(tools=["order_create"])]
        res, sent = self._run(sc, events)
        assert len(res["rounds"]) == 4, f"应在目标达成后停止，实际跑了 {len(res['rounds'])} 轮"
        assert res["rounds"][-1]["tools"][0]["name"] == "order_create"

    def test_stops_at_max_when_goal_unreachable(self):
        """目标始终未达成 → 不得无限循环（走满 max 就停，缺口由断言如实报出）。"""
        sc = {"id": "C-A1", "title": "t", "rounds": [
            {"repeat_until": {"tool_called": "order_create", "max": 3}, "click": "auto",
             "fallback": "确认"},
        ]}
        res, sent = self._run(sc, [self._ev()] * 6)
        assert len(res["rounds"]) == 3, f"max 未被遵守: {len(res['rounds'])}"

    def test_repeat_uses_cooperative_answers(self):
        """重复轮仍按 `click: auto` 作答（有什么卡答什么卡），不是无脑发同一句话。"""
        sc = {"id": "C-A1", "title": "t", "rounds": [
            {"repeat_until": {"tool_called": "order_create", "max": 2}, "click": "auto",
             "fallback": "确认"},
        ]}
        events = [self._ev(cards=[{"type": "choice", "options": [{"label": "纳米圈打孔", "value": "pi1"}]}]),
                  self._ev(tools=["order_create"])]
        _res, sent = self._run(sc, events)
        # 第 1 次重复时还没有卡 → 用 fallback；卡出现后**必须按卡作答**（不是无脑重发同一句）
        assert sent[0] == "确认", f"无卡时应走 fallback: {sent}"
        assert sent[1] == "纳米圈打孔", f"重复轮未按卡作答: {sent}"
