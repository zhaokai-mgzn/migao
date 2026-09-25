# case_ids: MC-012
"""P0 冒烟的**瞬态判定口径**判据（issue #4182；与 #5575 同批交付：判据必须能被独立验证）。

## 为什么这里也有一条判据

issue #4182 的处置分两半：① **定性** —— `d5435e45`（2026-09-17）的 P0 红 = 部署滚动重启窗口的
瞬态（`Server disconnected` / `Expected 200, got 502`），**不是回归**；② 让这一类不再把窗口读成回归，
同时**不许**把真回归读成窗口。②里「哪算瞬态」是一处**判定**（不是实现细节）：
`502`/`503`/`504` 与传输层断开 = 还没就绪；`500` 与任何断言失败 = 回归。
判定若只写在注释里，改一行常量就**静默**改变放行口径（本仓最贵的形态：绿了但没跑）。

## 判据（全部读**行为**：零网络、零 httpx、秒级）

| # | 判据 | 红证（注入 ⇒ 必红） |
|---|---|---|
| 1 | 瞬态码**恰好**是 `502/503/504`；`500`/`401`/`200` 都不是 | 把 `500` 放进瞬态集 ⇒ 红（真回归会被"等"成绿） |
| 2 | 传输层断开（`RemoteProtocolError` 等）算瞬态；**断言/解析类异常不算** | 把 `AssertionError` 放进类名集 ⇒ 红 |
| 3 | 非瞬态响应**一次都不重试**（尝试次数 = 1）且原样返回 | 让 `500` 也走重试 ⇒ 红 |
| 4 | 瞬态突发后返回**后来的**正常响应（窗口自愈），且每次重试都出声 | 去掉重试 ⇒ 红 |
| 5 | 瞬态持续 ⇒ 尝试次数有界、等待 ≤ 单请求预算、把**最后一次的响应**交出去（上层断言照旧红） | 无限重试/无上限等待 ⇒ 红 |
| 6 | 会话等待预算用尽 ⇒ 后续瞬态**立即**失败（不再等待） | 去掉预算判断 ⇒ 红（坏服务被"等"成绿） |
| 7 | 接线：`SmokeTestClient` 的四个动词都走 `_request`（唯一出口），且 `_request` 用重试器 | 让某个动词绕过 `_request` ⇒ 红 |
| 8 | 重试预算**从容**放得进单条用例的 `--timeout`（下限 = 两次请求的等待量） | `smoke-test.yml` 改回 `--timeout=30` ⇒ 红 |
| 9 | 失败证据落到 run summary **与** artifact（issue #4182 第 2 条） | 删掉 tee / 删掉 upload 步 ⇒ 红 |

## 射程与未固化边界（照实登记，别读成"已覆盖"）

- 判的是**策略行为**（`tests/smoke/retry_policy.py` 的纯逻辑 + `tests/smoke/helpers.py` 的接线）；
  **不判**真实网络行为 —— 「真窗口能否自愈」只有部署腿能验（见 PR 的固化声明）；
- **不判** `stream_post`（SSE 流式：一次性上下文管理器，不可安全重发；P0 档不消费它）；
- 本判据**不证明** `29s`（单请求）/`180s`（会话）这两个数适合**将来**更长的部署窗口 ——
  那两个数是部署窗口的读数，不是判据能自证的（数值冻结见 `test_the_wait_budget_is_bounded`）。
"""
from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SMOKE_DIR_REL = "tests/smoke"
HELPERS_REL = f"{SMOKE_DIR_REL}/helpers.py"
CONFTEST_REL = f"{SMOKE_DIR_REL}/conftest.py"
POLICY_REL = f"{SMOKE_DIR_REL}/retry_policy.py"
WORKFLOW_REL = ".github/workflows/smoke-test.yml"


def _retry_policy():
    """按**文件路径**加载策略模块（不 `import tests.smoke.*`）。

    实测（本判据的首版就是被这条打红的）：整目录收集时 `tests` 这个包名会被别的判据抢先绑定到
    `backend/ai-agent-service/tests` 之类的位置 ⇒ `from tests.smoke.retry_policy import …` 报
    `ModuleNotFoundError: No module named 'tests.smoke'`（单文件跑却正常）。
    ⇒ 与 `tests/unit_ci_workflows/test_flake_history_index.py::_load` **同款**：按路径加载。
    """
    path = REPO / POLICY_REL
    spec = importlib.util.spec_from_file_location("migao_smoke_retry_policy", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"加载不了 {POLICY_REL}（本判据无从判定 ⇒ 大声失败，不静默通过）")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RP = _retry_policy()
DELAYS = RP.DELAYS
MAX_ATTEMPTS = RP.MAX_ATTEMPTS
SESSION_WAIT_BUDGET_S = RP.SESSION_WAIT_BUDGET_S
TransientRetrier = RP.TransientRetrier
WaitLedger = RP.WaitLedger
is_transient_status = RP.is_transient_status
is_transient_exception = RP.is_transient_exception


class _Resp:
    """最小响应替身（重试器只读 `.status_code`）。"""

    def __init__(self, status_code: int):
        self.status_code = status_code


class RemoteProtocolError(Exception):
    """与 `httpx.RemoteProtocolError` **同名**的替身（瞬态按**类名**判定 ⇒ 同口径可测）。"""


def _retrier(script, *, ledger=None, max_attempts=MAX_ATTEMPTS, delays=DELAYS):
    """按 `script` 依次给出响应/异常；返回 `(retrier, call, calls, sleeps, logs)`。

    `script` 的最后一项会被重复使用（模拟"一直这样"）；`sleep`/`log` 都被替换成记录器
    ⇒ **真睡眠为零、断言可复算**。
    """
    sleeps: list[float] = []
    logs: list[str] = []
    calls = {"n": 0}

    def call():
        item = script[min(calls["n"], len(script) - 1)]
        calls["n"] += 1
        if isinstance(item, Exception):
            raise item
        return _Resp(item)

    retrier = TransientRetrier(max_attempts=max_attempts, delays=delays,
                               ledger=WaitLedger() if ledger is None else ledger,
                               sleep=sleeps.append, log=logs.append)
    return retrier, call, calls, sleeps, logs


def _helpers_tree() -> ast.Module:
    return ast.parse((REPO / HELPERS_REL).read_text(encoding="utf-8"))


def _client_methods() -> dict[str, ast.FunctionDef]:
    tree = _helpers_tree()
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SmokeTestClient")
    return {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}


# ═══════════════════════════════════════════════════════════════════════════
# ① 判定面：什么算瞬态（这一处口径决定"放行还是判红"）
# ═══════════════════════════════════════════════════════════════════════════
def test_the_transient_status_class_is_exactly_the_gateway_set():
    """瞬态码恰好 `{502,503,504}`；`500` **不是**（真回归必须当场红，issue #4182）。"""
    transient = {code for code in range(100, 600) if is_transient_status(code)}
    assert transient == {502, 503, 504}, f"瞬态码集合漂移：{sorted(transient)}"
    assert is_transient_status(500) is False, "500 被当成瞬态 ⇒ 真回归会被等待掩盖（issue #4182 的红线）"
    assert is_transient_status(200) is False
    assert is_transient_status(401) is False


def test_transport_disconnects_are_transient_but_assertions_are_not():
    """传输层断开算瞬态；**断言/解析类异常不算**（重试绝不能吞掉真失败）。"""
    assert is_transient_exception(RemoteProtocolError("Server disconnected")) is True
    for name in ("ConnectError", "ConnectTimeout", "ReadTimeout", "ReadError",
                 "WriteError", "WriteTimeout", "PoolTimeout"):
        assert is_transient_exception(type(name, (Exception,), {})("boom")) is True, name
    assert is_transient_exception(AssertionError("Expected 200, got 502")) is False
    assert is_transient_exception(ValueError("bad json")) is False
    assert is_transient_exception(KeyError("data")) is False


# ═══════════════════════════════════════════════════════════════════════════
# ② 行为面：重试的位置与边界
# ═══════════════════════════════════════════════════════════════════════════
def test_a_real_500_is_returned_immediately_without_any_retry():
    """`500` ⇒ 尝试次数 **1**、零等待、零日志（照旧当场红；第 2 项是"若重试就会拿到"的诱饵）。"""
    retrier, call, calls, sleeps, logs = _retrier([500, 200])
    resp = retrier.run(call)
    assert resp.status_code == 500
    assert calls["n"] == 1
    assert retrier.attempts == 1
    assert sleeps == []
    assert logs == []


def test_a_transient_burst_heals_and_every_retry_is_visible():
    """瞬态突发（502 → 连接断开 → 200）⇒ 自愈；每次重试都有可见的一行（含累计等待/上限）。"""
    retrier, call, calls, sleeps, logs = _retrier(
        [502, RemoteProtocolError("Server disconnected"), 200])
    resp = retrier.run(call)
    assert resp.status_code == 200
    assert calls["n"] == 3
    assert sleeps == [2.0, 4.0]
    assert len(logs) == 2
    assert all(line.startswith("::warning::") for line in logs), logs
    assert all("累计等待" in line and "上限" in line for line in logs), logs


def test_a_persistent_transient_is_bounded_and_still_hands_back_the_failure():
    """瞬态持续 ⇒ **有界**：尝试 ≤ `MAX_ATTEMPTS`、等待 = `sum(DELAYS)`，且交回最后一次的 **502**。

    交回 502（而不是抛个新异常、也不是返回成功）是刻意的：上层 `assert resp.status_code == 200`
    照旧红，文案照旧 `Expected 200, got 502` —— 口径"等待只买时间，不买结论"。
    """
    ledger = WaitLedger()
    retrier, call, calls, sleeps, logs = _retrier([502], ledger=ledger)
    resp = retrier.run(call)
    assert resp.status_code == 502
    assert calls["n"] == MAX_ATTEMPTS
    assert sum(sleeps) == sum(DELAYS)
    assert ledger.waited == sum(DELAYS)
    assert ledger.retries == MAX_ATTEMPTS - 1
    assert ledger.transient_events == MAX_ATTEMPTS


def test_a_persistent_transport_break_is_raised_after_the_bounded_retries():
    """全程连接断开 ⇒ 重试耗尽后把**最后一次的异常**抛出去（不是静默返回 None、也不是吞掉）。"""
    retrier, call, calls, _sleeps, _logs = _retrier([RemoteProtocolError("Server disconnected")])
    try:
        retrier.run(call)
    except RemoteProtocolError as exc:
        assert "Server disconnected" in str(exc)
    else:
        raise AssertionError("瞬态耗尽后没有把异常抛出来 —— 上层会把它读成成功")
    assert calls["n"] == MAX_ATTEMPTS


def test_the_session_budget_stops_the_waiting():
    """预算用尽 ⇒ 后续瞬态**立即**失败（不再等待）：长时间坏掉的服务不会被"等"成绿。"""
    ledger = WaitLedger(budget_s=6.0)
    retrier, call, calls, sleeps, logs = _retrier([503], ledger=ledger)
    resp = retrier.run(call)
    assert resp.status_code == 503
    assert ledger.waited <= 6.0
    assert sum(sleeps) <= 6.0
    assert any("预算已耗尽" in line for line in logs), logs
    later, later_call, later_calls, later_sleeps, later_logs = _retrier([503], ledger=ledger)
    later_resp = later.run(later_call)
    assert later_resp.status_code == 503
    assert later_calls["n"] == 1, "预算已耗尽却还在重试 ⇒ 坏服务会被「等」掉"
    assert later_sleeps == []
    assert any("预算已耗尽" in line for line in later_logs), later_logs


def test_the_wait_budget_is_bounded():
    """上限必须**有界且自洽**：延迟表与尝试次数对齐、单请求等待与 job 超时留有余量。"""
    assert len(DELAYS) == MAX_ATTEMPTS - 1, f"延迟表 {DELAYS} 与尝试次数 {MAX_ATTEMPTS} 不匹配"
    assert sum(DELAYS) < 60, f"单请求最多多等 {sum(DELAYS)}s —— 超过 1 分钟就不再是「窗口」量级"
    assert 0 < SESSION_WAIT_BUDGET_S < 600, (
        f"会话预算 {SESSION_WAIT_BUDGET_S}s 必须为有限值且小于 job 的 timeout-minutes: 10")


# ═══════════════════════════════════════════════════════════════════════════
# ③ 接线面：客户端只有一个出口；读数两态都要出声
# ═══════════════════════════════════════════════════════════════════════════
def test_all_client_verbs_route_through_the_single_retrying_exit():
    """四个动词都必须走 `_request`，且 `_request` 用重试器；别处不许直连底层 client。"""
    methods = _client_methods()
    assert "self._retrier.run" in ast.unparse(methods["_request"]), (
        "`_request` 没用重试器 ⇒ 瞬态策略没接线（`retry_policy.py` 成死代码）")
    for verb, method in (("get", "GET"), ("post", "POST"), ("put", "PUT"), ("delete", "DELETE")):
        forwarded = [c for c in ast.walk(methods[verb]) if isinstance(c, ast.Call)
                     and isinstance(c.func, ast.Attribute) and c.func.attr == "_request"]
        assert forwarded, f"`{verb}` 没走 `_request` ⇒ 该动词没有瞬态重试"
        first_arg = forwarded[0].args[0] if forwarded[0].args else None
        assert isinstance(first_arg, ast.Constant) and first_arg.value == method, (
            f"`{verb}` 转发到 `_request` 的 HTTP 方法不是 {method}（实测 "
            f"{getattr(first_arg, 'value', first_arg)!r}）")
    for name, node in methods.items():
        if name == "_request":
            continue
        src = ast.unparse(node)
        for verb in ("request", "get", "post", "put", "delete"):
            assert f"self._client.{verb}(" not in src, (
                f"`{name}` 直接调用了底层 client.{verb}() ⇒ 绕过了唯一出口（瞬态重试对它是盲区）")


def test_the_retry_readout_speaks_in_both_states():
    """读数：`pytest_sessionfinish` 必须**两态都打印**（"零瞬态"与"读数坏了"不许同形）。"""
    src = (REPO / CONFTEST_REL).read_text(encoding="utf-8")
    tree = ast.parse(src)
    hook = next((n for n in tree.body
                 if isinstance(n, ast.FunctionDef) and n.name == "pytest_sessionfinish"), None)
    assert isinstance(hook, ast.FunctionDef), f"{CONFTEST_REL} 没有 `pytest_sessionfinish` 读数钩子"
    body = ast.unparse(hook)
    assert "SESSION_LEDGER.retries" in body, "读数钩子没读会话账本 ⇒ 打印的是常量，不是本轮读数"
    assert body.count("print(") >= 2, "读数钩子只有一个分支会出声 ⇒ 另一态与「读数缺失」同形"


# ═══════════════════════════════════════════════════════════════════════════
# ④ 部署腿面：预算放得进单条用例超时；失败证据落到 summary + artifact
# ═══════════════════════════════════════════════════════════════════════════
def _smoke_workflow() -> dict:
    return yaml.safe_load((REPO / WORKFLOW_REL).read_text(encoding="utf-8"))


def test_the_retry_budget_fits_inside_the_per_test_timeout():
    """单条用例的 `--timeout` 必须**从容**放得进瞬态等待。

    P0 档多条用例会连发 2~3 个请求、每个请求各自最多等 `sum(DELAYS)` ⇒ 下限取**两次**请求的
    等待量（实测教训：首版写成 `> sum(DELAYS)` 时，`--timeout=30` 恰好卡在 29 < 30 通过 ⇒
    这条判据几乎无判别力，注入式红证当场把它抓出来了）。
    """
    runs = "\n".join(step.get("run", "") for step in _smoke_workflow()["jobs"]["smoke-test"]["steps"])
    match = re.search(r"--timeout=(\d+)", runs)
    assert match, f"{WORKFLOW_REL} 的 pytest 命令里读不到 `--timeout=…`（判定面不见了，不许静默通过）"
    per_test = int(match.group(1))
    floor = 2 * sum(DELAYS)
    assert per_test >= floor, (
        f"单条用例超时 {per_test}s < 两次请求的瞬态等待量 {floor}s ⇒ "
        f"窗口内的重试会被 pytest-timeout 提前掐死（「重试了但仍红」与真回归无法区分）")


def test_the_failure_evidence_lands_in_the_summary_and_in_an_artifact():
    """issue #4182 第 2 条：证据要在 run summary **和** artifact 里（不能只在 job log —— 当时取不到）。"""
    text = (REPO / WORKFLOW_REL).read_text(encoding="utf-8")
    assert "GITHUB_STEP_SUMMARY" in text, "冒烟腿没有把输出摊到 run summary（失败仍然只能靠 job log）"
    steps = [s for job in _smoke_workflow()["jobs"].values() for s in job.get("steps", [])]
    uploads = [s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact")]
    assert uploads, "冒烟腿没有上传 artifact ⇒ 失败证据取不到（issue #4182 的病灶）"
    assert any(s.get("if") == "always()" for s in uploads), (
        "artifact 必须 `if: always()` —— 红了才更需要证据")
