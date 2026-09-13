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

        async def fake_send(sid, token, text, images=None):
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
