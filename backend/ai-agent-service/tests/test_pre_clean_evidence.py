"""pre_clean 证据入用例结果/摘要 的单测（#3511 归因盲区修复）

背景（B 端独立栈首跑 run 34804430769，AS-004）：
    R1 `after_sales_manage(items=0)` → agent 如实回「系统里还没有任何售后工单」→ 无法关闭
    → 用例判红。而该用例声明了 `pre_clean: [{type: aftersales_ticket_prepare}]` ——
    **工单准备没生效**才是真因，但 pre_clean 结果此前**只 print**，报告里"数据准备失败"
    与"能力缺陷"同形（acceptance-protocol 五层归因要求数据层优先可判）。

本组锁定：pre_clean 消息（含失败信息）必须进入用例结果与 summary JSON。
"""
# case_ids: AS-004, HR-003, CU-003
import asyncio
import importlib.util
import json
import unittest.mock as mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER_PATH = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("migao_eval_runner_pc", RUNNER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lr = _load_runner()


def _case(cid="PC-001", pre_clean=None):
    return lr.EvalCase(
        id=cid, title="t", skill=lr.Skill.GENERAL, difficulty=lr.Difficulty.NORMAL,
        user_inputs=["hi"], expectations=[], data_checks=[],
        pre_clean=pre_clean or [],
    )


class TestPreCleanEvidence:
    def _run(self, cases, pre_clean_impl):
        """跑 run_suite（mock 网络层 + pre_clean 实现），返回 results。"""
        async def fake_login():
            return "tok"

        async def fake_sess(token, prefer_new=True, **kwargs):
            return "sess"

        async def fake_send(token, sid, message, images=None, **kwargs):
            return {"user_message": message, "images": images or [], "tool_calls": [],
                    "tool_results": [], "interactive": [], "final_text": "ok",
                    "error": None, "streamed": False, "done": True}

        with mock.patch.object(lr, "login", new=fake_login), \
             mock.patch.object(lr, "get_or_create_session", new=fake_sess), \
             mock.patch.object(lr, "send_message", new=fake_send), \
             mock.patch.object(lr, "_run_pre_clean", new=pre_clean_impl):
            return asyncio.run(lr.run_suite(cases, "t", classify=False, concurrency=1))

    def test_pre_clean_messages_recorded(self):
        """带 pre_clean 的用例：消息必须进结果（而非只 print）"""
        async def fake_pre_clean(token, spec):
            return "工单准备完成（1 条 pending）"

        results = self._run([_case(pre_clean=[{"type": "aftersales_ticket_prepare"}])],
                            fake_pre_clean)
        assert results[0]["pre_clean"] == ["工单准备完成（1 条 pending）"]

    def test_pre_clean_failure_recorded(self):
        """pre_clean 抛异常：失败信息也必须进结果（此前静默只有 print）"""
        async def boom(token, spec):
            raise RuntimeError("orders/mine 404")

        results = self._run([_case(pre_clean=[{"type": "aftersales_ticket_prepare"}])], boom)
        pc = results[0]["pre_clean"]
        assert pc and "pre_clean 失败" in pc[0] and "404" in pc[0], pc

    def test_case_without_pre_clean_records_empty(self):
        """无 pre_clean 的用例：字段为空列表（形状稳定，消费方不必判 None）"""
        async def fake_pre_clean(token, spec):
            return "x"

        results = self._run([_case()], fake_pre_clean)
        assert results[0]["pre_clean"] == []

    def test_summary_json_includes_pre_clean(self, tmp_path):
        """summary JSON 必须带 pre_clean（机器可读归因）"""
        async def fake_pre_clean(token, spec):
            return "客户「张三」不存在（共 0 位）"

        results = self._run([_case(pre_clean=[{"type": "customer_lookup"}])], fake_pre_clean)
        out = tmp_path / "summary.json"
        lr.write_summary_json(str(out), "t", "1", results)
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["cases"][0]["pre_clean"] == ["客户「张三」不存在（共 0 位）"]
