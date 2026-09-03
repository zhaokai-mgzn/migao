"""
agent-eval 图片消息支持 — 自测脚本（issue #2794）

守护 local_runner 的图片链路改动：
1. send_message 纯文本路径 body 不含 images（向后兼容）
2. send_message 带图路径 body 含 images（透传后端 ChatSendRequest.images）
3. run_case 轮次解析：str → 纯文本；dict{text, images} → 带图消息
4. YAML 加载带图 case（CH-021）且纯文本用例兼容

运行（仓库根）：
    python3 tests/agent_eval/selftest_images.py
退出码：0=通过，1=失败
"""
# case_ids: CH-021

import asyncio
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]

_spec = importlib.util.spec_from_file_location("local_runner", _HERE / "local_runner.py")
lr = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(lr)
except SystemExit:
    pass  # main() 在 import 时不执行


class _FakeResp:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_lines(self):
        yield "event: done"
        yield "data: {}"


class _FakeClient:
    """httpx.AsyncClient 替身：捕获 POST body"""

    def __init__(self):
        self.bodies = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False  # 不吞异常

    def stream(self, *a, **kw):
        self.bodies.append(kw.get("json"))
        return _FakeResp()


async def _test_send_message():
    fc = _FakeClient()
    with patch.object(lr.httpx, "AsyncClient", return_value=fc):
        await lr.send_message("tok", "s1", "查订单")
        assert "images" not in fc.bodies[0], "纯文本路径不应带 images"
        await lr.send_message(
            "tok", "s1", "看看这个",
            images=["https://picsum.photos/seed/curtain/800/600"],
        )
        assert fc.bodies[1]["images"] == [
            "https://picsum.photos/seed/curtain/800/600"
        ], "带图路径应透传 images"
    print("✅ send_message 纯文本/带图路径")


class _Difficulty:
    def __init__(self, v):
        self.value = v


class _FakeCase:
    id = "T-IMG"
    title = "图片测试"
    tags = ["image"]
    expectations = []
    data_checks = []
    difficulty = _Difficulty("normal")
    user_inputs = [
        "第一轮纯文本",
        {"text": "看看这个窗帘",
         "images": ["https://picsum.photos/seed/curtain/800/600"]},
    ]


async def _test_run_case_rounds():
    sent = []

    async def _fake_send(token, sid, msg, images=None):
        sent.append((msg, images))
        return {"tool_calls": [], "final_text": "好的", "error": None}

    with patch.object(lr, "send_message", side_effect=_fake_send):
        r = await lr.run_case(_FakeCase(), "tok", "s1")
        assert sent[0] == ("第一轮纯文本", []), sent[0]
        assert sent[1] == (
            "看看这个窗帘",
            ["https://picsum.photos/seed/curtain/800/600"],
        ), sent[1]
        assert r["rounds"] == 2
    print("✅ run_case 轮次解析（str/dict 混合）")


def _test_yaml_load():
    cases = lr.load_cases_from_yaml(str(_REPO / ".github" / "cases"))
    ch21 = [c for c in cases if c.id == "CH-021"]
    assert ch21, "CH-021 应存在于用例库"
    first = ch21[0].user_inputs[0]
    assert isinstance(first, dict) and "images" in first, "CH-021 应为 dict 带图形态"
    str_only = [
        c for c in cases if all(isinstance(m, str) for m in c.user_inputs)
    ]
    assert len(str_only) == len(cases) - 1, "仅 CH-021 一条带图，其余纯文本兼容"
    print(f"✅ YAML 加载：{len(cases)} 条，纯文本 {len(str_only)} 条兼容")


async def _main():
    await _test_send_message()
    await _test_run_case_rounds()
    _test_yaml_load()
    print("\n全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
