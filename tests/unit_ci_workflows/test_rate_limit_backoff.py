# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI / 流程结构类 L0 不变式统一挂 MC-012。）
"""限流 ≠ 真红（issue #7549）—— 共享退避原语 + 四处接线。

## 病（2026-11-03 现网实测）

5 个在飞 PR（#8544 / #8545 / #8546 / #8549 / #8551）同时红在**同一组 4 条腿**：
`Danger Scan` / `Secret Scan (gitleaks)` / `QA Growth Gate` / `External Authorship Guard`。
逐字读数见 `.github/rate_limit_backoff.py` 的模块 docstring（PR #8551 的 job 日志）。
⇒ 四条腿里**没有一条**能分清「安装令牌限流（等一会儿就好）」与「真没权限 / 真扫到密钥」。

## 本文件守的 5 组（每组都配「注入后必红」的判别力自证，见第 ⑤ 组）

| # | 判据 | 红证（怎么让它红） |
|---|---|---|
| ① | 403 + `remaining=0` ⇒ 重试后成功 ⇒ 该步绿 | 把重试摘掉（一律判 `denied`）⇒ ①红 |
| ② | **403 且 `remaining>0`、报文非限流（真没权限）⇒ 一次也不重试、直接红** | 把「区分 remaining」摘掉（一律当限流重试）⇒ ②红 |
| ③ | gitleaks 无报告 ⇒ **无法判定**（exit 3：非零、但文案与「真 findings」分开） | 把 `exit 3` 改回 `exit 0` ⇒ ③红（未判定被当绿） |
| ④ | 重试**有界**：永远 403 的夹具 ⇒ 有限次后放弃（次数上限 + 总预算） | 把 `attempts`/`budget` 任一条摘掉 ⇒ ④红 |
| ⑤ | 判别力自证：上面 ①/② 的红证**在本文件里常驻**（`monkeypatch` 注入判定） | 判据退化成空断言 ⇒ ⑤红 |

零网络：全部用**假响应夹具**（`GithubError` 构造 + 临时 shell 脚本），一次也不碰 GitHub API。
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "pr-check.yml"
MODULE = REPO / ".github" / "rate_limit_backoff.py"
JS_BRIDGE = REPO / ".github" / "scripts" / "rate-limit-backoff.js"
AUTHORSHIP = REPO / "scripts" / "external_authorship_guard.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("rate_limit_backoff", MODULE)
    module = importlib.util.module_from_spec(spec)
    # ⚠️ 必须先登记进 `sys.modules`：`@dataclass` 会回头查 `sys.modules[cls.__module__]`
    #    （未登记 ⇒ `AttributeError: 'NoneType' object has no attribute '__dict__'`）。
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


rl = _load_module()


# ─────────────────────────── 夹具 ───────────────────────────
def _err(status, remaining=None, message="", headers=None):
    merged = dict(headers or {})
    if remaining is not None:
        merged["x-ratelimit-remaining"] = str(remaining)
    return rl.GithubError(status, merged, message)


class _Api:
    """按给定失败序列返回的假 API：第 N 次调用抛第 N 个错误，序列用尽后返回成功值。"""

    def __init__(self, errors, success="ok"):
        self.errors = list(errors)
        self.success = success
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return self.success


class _Clock:
    """假时钟：`sleep` 不真睡，只累计（判据要确定、要快）。"""

    def __init__(self):
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(float(seconds))
        self.now += float(seconds)


# ─────────────────── ① 限流 ⇒ 重试后成功（该步绿）───────────────────
def test_rate_limited_403_retries_then_succeeds():
    """① 403 + `remaining=0` ⇒ 退避重试后成功（判据：拿到成功值、只多打了一次、等了一次）。

    ⚠️ 夹具的报文**故意不含** `rate limit` 字样 —— 这样「重试」只可能来自 `remaining=0` 这个信号，
    组 ⑤ 的「摘掉 remaining 区分」注入才咬得住（否则两种信号互相遮蔽，红证是空的）。
    """
    clock = _Clock()
    api = _Api([_err(403, remaining=0, message="Resource not accessible by integration")])

    result = rl.call(api, label="列评论", sleep=clock.sleep, clock=clock)

    assert result == "ok", "限流是瞬时的：重试一次就该拿到结果（这正是不该判红的那一类）"
    assert api.calls == 2, f"应当只多打一次（实得 {api.calls} 次）"
    assert clock.slept == [rl.DEFAULT_BASE_DELAY], f"退避读数不符：{clock.slept}"


# ───────── ② 负控（本文件最重要）：真没权限 ⇒ 不重试、直接红 ─────────
def test_real_denial_is_never_retried():
    """② 403 但 `remaining>0` 且报文不是限流 ⇒ **一次也不重试**，原样抛出 ⇒ 调用方直接红。

    这是「限流 ≠ 真红」的**另一半**：只加退避、不加这条 ⇒ 真没权限会被重试 3 次后写进
    「限流」文案 ⇒ 下一个读红的人先去怀疑 token 配额，而真因（权限）被埋掉。
    """
    clock = _Clock()
    api = _Api([_err(403, remaining=4999, message="Resource not accessible by integration")] * 5)

    with pytest.raises(rl.GithubError) as caught:
        rl.call(api, label="列评论", sleep=clock.sleep, clock=clock)

    assert caught.value.outcome == rl.DENIED
    assert api.calls == 1, f"真没权限**不许**重试（实得 {api.calls} 次）—— 重试变不出权限"
    assert clock.slept == [], "也不许先睡一觉再放弃"


def test_secondary_rate_limit_with_remaining_is_retried():
    """② 的另一面：报文说限流（GitHub **二级限流**，此时 `remaining` 通常仍 >0）⇒ **必须**重试。

    「`remaining>0` 一律不重试」是错的：二级限流正是那个形态。判据看报文，不只看头。
    """
    clock = _Clock()
    api = _Api([_err(403, remaining=4999, message="You have exceeded a secondary rate limit")])

    assert rl.call(api, label="列评论", sleep=clock.sleep, clock=clock) == "ok"
    assert api.calls == 2


# ───────────────────── ④ 有界：次数 / 总预算 ─────────────────────
def test_retry_is_bounded_by_attempts():
    """④ 永远 403（`remaining=0`）⇒ 有限次后放弃，**绝不许**无限等。"""
    clock = _Clock()
    api = _Api([_err(403, remaining=0)] * 10)

    with pytest.raises(rl.RetryExhausted) as caught:
        rl.call(api, label="列评论", sleep=clock.sleep, clock=clock)

    assert api.calls == rl.DEFAULT_ATTEMPTS == 3, f"应为 3 次尝试（实得 {api.calls} 次）"
    assert caught.value.attempts == 3
    assert len(clock.slept) == 2, f"3 次尝试之间只该等 2 次（实得 {clock.slept}）"


def test_retry_is_bounded_by_total_budget():
    """④ 的另一半：单次要等 `retry-after=600s`、而总预算只有 10s ⇒ **立刻放弃**、一次也不睡。

    （去掉这条就是「有界」的假象：次数有界但每次可以睡 10 分钟。）
    """
    clock = _Clock()
    api = _Api([_err(403, remaining=0, headers={"retry-after": "600"})] * 10)

    with pytest.raises(rl.RetryExhausted) as caught:
        rl.call(api, label="列评论", policy=rl.Policy(attempts=3, budget=10.0),
                sleep=clock.sleep, clock=clock)

    assert caught.value.reason == "总时长上限"
    assert api.calls == 1 and clock.slept == [], "预算不够就立刻放弃（不许先睡 30s 再放弃）"


# ─────────────────────────── 判定矩阵 ───────────────────────────
def test_classify_matrix_is_the_single_decision_point():
    """判定只有一处实现 —— 八种形态各自归到哪里（含头名大小写不敏感）。"""
    assert rl.classify(429) == rl.RATE_LIMITED
    assert rl.classify(403, {"x-ratelimit-remaining": "0"}) == rl.RATE_LIMITED
    assert rl.classify(403, {"X-RateLimit-Remaining": "0"}) == rl.RATE_LIMITED
    assert rl.classify(403, {"x-ratelimit-remaining": "1"}, "Resource not accessible") == rl.DENIED
    assert rl.classify(403, {}, "Resource not accessible by integration") == rl.DENIED
    assert rl.classify(403, {}, "API rate limit exceeded for installation") == rl.RATE_LIMITED
    assert rl.classify(401, {}, "Bad credentials") == rl.DENIED
    assert rl.classify(500, {}, "boom") == rl.OTHER


# ───────────── CLI 面：真进程 + 假命令（仍然零网络、零 GitHub）─────────────
def _fake_gh(tmp_path, stderr_line):
    counter = tmp_path / "calls"
    script = tmp_path / "fake-gh.sh"
    script.write_text(
        "#!/bin/sh\n"
        f'echo x >> "{counter}"\n'
        f"echo '{stderr_line}' >&2\n"
        "exit 1\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script, counter


def test_exec_cli_gives_up_as_undecidable(tmp_path):
    """④ + ③ 的 CLI 面：永远限流的命令 ⇒ 有限次后以 **exit 3（未判定）** 放弃。"""
    script, counter = _fake_gh(
        tmp_path, "gh: API rate limit exceeded for installation (HTTP 403)")
    proc = subprocess.run(
        [sys.executable, str(MODULE), "exec", "--label", "夹具", "--attempts", "2",
         "--base-delay", "0", "--budget", "60", "--", str(script)],
        capture_output=True, text=True, check=False)

    assert proc.returncode == rl.EXIT_UNDECIDABLE, f"限流耗尽 = 未判定（实得 {proc.returncode}）"
    assert counter.read_text(encoding="utf-8").count("x") == 2, "重试次数必须有界"
    assert "未判定" in proc.stderr + proc.stdout, "钉不住「未判定」这句 ⇒ 读红的人又要把限流当代码问题"


def test_exec_cli_denial_fails_fast(tmp_path):
    """② CLI 面：真无权限 ⇒ **exit 1 且只跑一次**（不重试、也不冒充限流）。"""
    script, counter = _fake_gh(
        tmp_path, "gh: Resource not accessible by integration (HTTP 403)")
    proc = subprocess.run(
        [sys.executable, str(MODULE), "exec", "--label", "夹具", "--attempts", "3",
         "--base-delay", "0", "--", str(script)],
        capture_output=True, text=True, check=False)

    assert proc.returncode == rl.EXIT_FAILED
    assert counter.read_text(encoding="utf-8").count("x") == 1, "真没权限**一次也不许**重试"
    assert "非限流" in proc.stderr, "必须点明「非限流」，否则会被归因成 token 配额"


def test_exec_cli_best_effort_never_blocks_the_call_site(tmp_path):
    """预检专用：`--best-effort` 退避耗尽也 exit 0（预检**不许**额外判红，红由被保护的步骤判）。"""
    script, _ = _fake_gh(tmp_path, "gh: API rate limit exceeded for installation (HTTP 403)")
    proc = subprocess.run(
        [sys.executable, str(MODULE), "exec", "--best-effort", "--label", "夹具",
         "--attempts", "1", "--base-delay", "0", "--", str(script)],
        capture_output=True, text=True, check=False)
    assert proc.returncode == 0


# ─────────────────────── 接线（四处，逐处钉死）───────────────────────
def _danger_ack_block(text):
    return text.split("Resolve workflow-deletion acks", 1)[1].split("- name: Run danger scan", 1)[0]


def test_danger_scan_comment_read_goes_through_the_primitive():
    """接线 1/4：Danger Scan 的**评论读取**步 —— 原先读失败 `exit 0`（红得无声无息）。"""
    block = _danger_ack_block(WORKFLOW.read_text(encoding="utf-8"))
    # 只看**可执行行**（注释里会引用旧形态「读失败 ⇒ exit 0」，那是说明文字，不是控制流）
    code = [line.strip() for line in block.splitlines() if not line.strip().startswith("#")]

    assert "rate_limit_backoff.py exec" in block, "评论读取必须走共享原语"
    assert '--label "取 PR 评论"' in block
    assert "--output /tmp/pr-comments.json" in block, "重试途中不许写半成品（成功才落盘）"
    assert "exit 0" not in code, "读失败仍 `exit 0` = 确认通道静默死亡（本次修的形态之一）"
    assert "exit 3" in code, "限流耗尽 ⇒ 未判定（非零、但文案要说限流）"


def test_qa_growth_gate_comment_read_is_not_bare():
    """接线 2/4：QA Growth Gate 的 `listComments` 原先**裸调**（PR #8551 实测 403 直接判红）。"""
    text = WORKFLOW.read_text(encoding="utf-8")
    block = text.split("Render PR comment from growth-gate-result.json", 1)[1]
    block = block.split("# ============ Case Contract", 1)[0]

    assert "await github.rest.issues.listComments({" not in block, "不许再裸调（限流即判红）"
    assert "withRateLimitRetry('列评论'" in block
    assert ".github/scripts/rate-limit-backoff.js" in block


def test_js_bridge_delegates_the_verdict_to_the_python_policy():
    """接线 2/4 的另一半：JS 桥**不许**自己写一套判定（两份策略必然漂移）。"""
    source = JS_BRIDGE.read_text(encoding="utf-8")

    assert "rate_limit_backoff.py" in source and "'classify'" in source, "判定必须问唯一的实现"
    assert "response.headers" in source, "octokit 的响应头要转交（`remaining=0` 是主信号）"
    assert "throw e" in source, "桥自己出错 ⇒ 原样抛出（不许吞、不许当成限流多试）"


def test_gitleaks_undecidable_is_three_state_and_never_green():
    """接线 3/4：gitleaks 无报告 = **未判定**（exit 3），且与「真 findings」文案分开。"""
    text = WORKFLOW.read_text(encoding="utf-8")
    block = text.split("Classify gitleaks outcome", 1)[1]
    no_report = block.split("GITLEAKS_NO_REPORT", 1)[1].split("GITLEAKS_FINDINGS", 1)[0]

    assert "exit 3" in no_report, "无报告 ⇒ 三态 3（不可判绿，也不得与「扫到密钥」同形）"
    assert "exit 0" not in no_report, "未判定**不许**当绿（那是比误判更危险的形态）"
    assert "GITLEAKS_NO_REPORT" in block and "GITLEAKS_FINDINGS" in block, "两种形态必须分开打印"


def test_gitleaks_has_a_bounded_retry_before_the_scan():
    """接线 3/4 的退避面：扫描前先对**同一个** license 校验调用做有界退避（best-effort）。"""
    text = WORKFLOW.read_text(encoding="utf-8")
    preflight = text.split("Preflight gitleaks license check", 1)[1]
    preflight = preflight.split("- name: Run gitleaks secret scan", 1)[0]

    assert "rate_limit_backoff.py exec --best-effort" in preflight
    assert "gh api" in preflight and "users/" in preflight, "要复用 action 内部那一次同样的调用"


def test_authorship_guard_routes_gh_through_the_primitive():
    """接线 4/4：External Authorship Guard 的取数原先无限流退避 ⇒ 一次 403 就 exit 3。"""
    source = AUTHORSHIP.read_text(encoding="utf-8")
    body = source.split("def _gh(", 1)[1].split("\ndef ", 1)[0]

    assert "import rate_limit_backoff" in source, "必须复用共享原语（不许第二份判定）"
    assert "rate_limit_backoff.call_command" in body, "取数必须走原语，否则限流 = 恒 exit 3"
    assert 'subprocess.run(["gh"' not in body, "不许再有**裸** gh 调用（那条路径没有任何退避）"
    assert "subprocess.CompletedProcess" in body, "适配层行为不变（调用方仍按 returncode 判三态）"


# ─────── ⑤ 判别力自证：把修复摘掉 ⇒ ①/② 必红（常驻，不靠人记得跑）───────
def test_mutation_always_retry_turns_the_negative_control_red(monkeypatch):
    """⑤ 注入 A：把「区分 remaining」摘掉（一律当限流）⇒ **② 必红**。

    ② 期望「`GithubError` 且只调 1 次」；注入后真没权限被重试 3 次、抛 `RetryExhausted`
    ⇒ ② 的断言当场不成立。**本判据证明了 ② 不是空断言。**
    """
    monkeypatch.setattr(rl, "classify", lambda *a, **k: rl.RATE_LIMITED)
    clock = _Clock()
    api = _Api([_err(403, remaining=4999, message="Resource not accessible by integration")] * 5)

    with pytest.raises(rl.RetryExhausted):
        rl.call(api, label="列评论", sleep=clock.sleep, clock=clock)
    assert api.calls == rl.DEFAULT_ATTEMPTS > 1, "注入必须生效（否则本判据自身是空断言）"


def test_mutation_no_retry_turns_the_positive_control_red(monkeypatch):
    """⑤ 注入 B：把重试摘掉（一律判 `denied`）⇒ **① 必红**（① 期望拿到 `ok`，注入后抛错）。"""
    monkeypatch.setattr(rl, "classify", lambda *a, **k: rl.DENIED)
    clock = _Clock()
    api = _Api([_err(403, remaining=0)])

    with pytest.raises(rl.GithubError):
        rl.call(api, label="列评论", sleep=clock.sleep, clock=clock)
    assert api.calls == 1, "注入必须生效（否则本判据自身是空断言）"
