# case_ids: MC-012
# （CI/流程结构类 L0 不变式统一挂 MC-012 —— 同 `test_merge_gate.py` / `test_lifecycle_land_and_reap.py`
#  的既有惯例；本 PR 不新建用例族：塞进行为用例库会污染覆盖矩阵。）
"""`scripts/wait-checks.sh` —— 「CI 全绿了吗」的**不可假绿**等待入口（issue #7009）。

## 这守的是什么（PR #7003 实测两次，不是推测）

`gh pr checks <PR> --watch` 在两种形态下都 **rc=0** 退出，而此刻**并未全绿**：

| 形态 | watch 的行为 | 后果 |
|---|---|---|
| `PR Check` 还没**上报** check（later-created run / 刚 push） | 认为「没有待跑的」⇒ rc=0 | 「还没跑」被读成「已全绿」 |
| `Post graphql: read: connection reset by peer` | **仍 rc=0**，required 还 pending | 同上，且更隐蔽（有错误字样却仍 0） |

⇒ **退出码不是「全绿」的判据**。本入口只认数据：required 集合里**每一条**都拿到**终态 SUCCESS** 才 0。

## 判据分组（每组都能**单独**变红，红证见 `test_criteria_have_discriminating_power`）

① **全绿 ⇒ 0**，且输出必须自报**读数来源**（PR 号 + head sha + required 条数 + 每条 state + 采样次数 +
   读数时刻）—— 没有读数来源的「绿」等于无法复核；
② **pending / 未上报 ⇒ 3**（**绝不 0**）：前者是「还在跑」，后者是「还没来」（later-created run），
   两者都**不是**绿（`land` 的 wait-ci 在这两处都会 rc=0 假完成）；
③ **required 终态非 SUCCESS ⇒ 1**：红 / 取消 / 超时 **以及 `SKIPPED` / `NEUTRAL`** 都不算绿（宁可报红也不假绿）；
④ **网络 / API 报错 ⇒ 3**，**与退出码无关**：输出里出现 `connection reset by peer` 等字样即判定「这次读数不可信」；
⑤ **required 集合读不到 / 为空 ⇒ 3**：空集合 ≠ 没有 required（拿空集合宣告全绿正是本单要治的假绿）；
⑥ **等 ≠ 轮询猜**：pending 后继续采样，直到全绿（0）或到点（3）；`--once` 只采样一次；
⑦ **接线**：实际跑的是**命名的入口** `scripts/wait-checks.sh`（不是直接调 python），
   且未给 PR 号 / `--help` 都不许退 0（「看不了」不得当「通过」）。

替身口径：`gh` 用**替身可执行文件**（`WC_GH_BIN`，沿用 `merge_gate.py` 的 `MG_GH_BIN` 先例）注入；
替身把**每次真实调用按序**写进 `$WC_CALL_LOG` ⇒ 判据读的是实跑调用，不是源码文本。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "scripts" / "wait-checks.sh"
JUDGE = REPO_ROOT / "scripts" / "merge_gate.py"

PR = "7003"
REQ_A = "ci workflow helper unit tests"
REQ_B = "PR Check"
SHA = "b" * 40


# ── 替身 gh ────────────────────────────────────────────────────────────────────

_GH_STUB = r'''#!/usr/bin/env python3
"""替身 gh：按 WC_STATE 回放读数，并把每次调用按序记进 WC_CALL_LOG。"""
import json, os, sys

argv = sys.argv[1:]
log = os.environ.get("WC_CALL_LOG")
if log:
    with open(log, "a", encoding="utf-8") as fh:
        fh.write("gh " + " ".join(argv) + "\n")

with open(os.environ["WC_STATE"], encoding="utf-8") as fh:
    state = json.load(fh)


def save():
    with open(os.environ["WC_STATE"], "w", encoding="utf-8") as fh:
        json.dump(state, fh)


if argv[:2] == ["pr", "checks"]:
    seq = state.get("checks_sequence") or [[]]
    row = seq.pop(0) if len(seq) > 1 else seq[0]
    save()
    if isinstance(row, list):          # 简写：这一"帧"就是 checks 列表本身
        row = {"checks": row}
    if row.get("stderr"):
        sys.stderr.write(str(row["stderr"]) + "\n")
    if row.get("rc"):
        sys.exit(int(row["rc"]))
    print(json.dumps(row.get("checks") or []))
    sys.exit(0)

if argv[:1] == ["api"]:
    if int(state.get("api_rc") or 0):
        sys.stderr.write(str(state.get("api_stderr") or "HTTP 403: Resource not accessible"))
        sys.exit(int(state["api_rc"]))
    print(json.dumps(state.get("required") or {"contexts": []}))
    sys.exit(0)

if argv[:2] == ["pr", "view"]:
    print(json.dumps(state.get("pr") or {"state": "OPEN", "headRefOid": "b" * 40}))
    sys.exit(0)

if argv[:2] == ["repo", "view"]:
    print(state.get("repo") or "acme/migao")
    sys.exit(0)

sys.stderr.write("替身 gh：未实现的调用 " + " ".join(argv) + "\n")
sys.exit(9)
'''


def _row(name, state="SUCCESS", bucket=None):
    if bucket is None:
        bucket = "pass" if state == "SUCCESS" else ("pending" if state == "PENDING" else "fail")
    return {"name": name, "state": state, "bucket": bucket, "link": f"https://example.invalid/{name}"}


class Runner:
    """一套替身 + 状态文件；每次跑都从同一份状态出发（`checks_sequence` 会被逐步消耗）。"""

    def __init__(self, base: Path):
        self.base = base
        base.mkdir(parents=True, exist_ok=True)
        self.bin = base / "bin"
        self.bin.mkdir()
        self.gh = self.bin / "gh"
        self.gh.write_text(_GH_STUB, encoding="utf-8")
        self.gh.chmod(0o755)
        self.log = base / "calls.log"
        self.state_file = base / "state.json"
        self.set_state()

    def set_state(self, **state):
        self.state = state
        self.state_file.write_text(json.dumps(self.state), encoding="utf-8")

    def run(self, *args, wrapper: Path | None = None, cwd: Path | None = None):
        env = dict(os.environ)
        env["WC_GH_BIN"] = str(self.gh)
        env["WC_CALL_LOG"] = str(self.log)
        env["WC_STATE"] = str(self.state_file)
        env.pop("MG_GH_BIN", None)
        return subprocess.run(["bash", str(wrapper or WRAPPER), *args],
                              cwd=str(cwd or REPO_ROOT), capture_output=True, text=True, env=env)

    def calls(self) -> str:
        return self.log.read_text(encoding="utf-8") if self.log.exists() else ""


@pytest.fixture()
def run(tmp_path: Path) -> Runner:
    return Runner(tmp_path)


def _green_run(run: Runner):
    """基线安全形态：两条 required 全绿。"""
    run.set_state(required={"contexts": [REQ_A, REQ_B]},
                  checks_sequence=[[_row(REQ_A), _row(REQ_B)]])
    return run


# ── ① 全绿 ⇒ 0，且自报读数来源 ────────────────────────────────────────────────

def test_all_required_success_exits_zero_with_a_readable_source(run: Runner):
    """对照臂（别把功能改瘫）：真全绿 ⇒ 0，且**读数来源**必须能一眼复核。"""
    _green_run(run)

    proc = run.run(PR)

    out = proc.stdout
    assert proc.returncode == 0, f"全绿必须 exit 0：exit={proc.returncode}\n{out}\n{proc.stderr}"
    for needle in (f"PR #{PR}", SHA, REQ_A, REQ_B, "SUCCESS", "读数来源", "读数时刻", "全部终态 SUCCESS"):
        assert needle in out, f"输出缺少读数来源要素 {needle!r}（无读数来源的「绿」不可复核）：\n{out}"
    assert f"required（2 条" in out, f"必须自报 required 条数（现取，不写死）：\n{out}"
    assert "gh pr checks" in run.calls() and "gh api" in run.calls(), (
        f"判据未真的去读数据（空断言）：\n{run.calls()}")


# ── ② pending / 未上报 ⇒ 3（**绝不 0**）────────────────────────────────────────

def test_pending_required_exits_three_never_zero(run: Runner):
    """还在跑 ⇒ 3。**这条就是本单的地雷**：`--watch` 在这种形态下会 rc=0。"""
    run.set_state(required={"contexts": [REQ_A, REQ_B]},
                  checks_sequence=[[_row(REQ_A), _row(REQ_B, "PENDING")]])

    proc = run.run(PR, "--once")

    assert proc.returncode == 3, f"pending 必须 3（无法判定）：exit={proc.returncode}\n{proc.stdout}"
    assert REQ_B in proc.stdout and "仍 pending" in proc.stdout, f"必须**具名**点出谁还在跑：\n{proc.stdout}"
    assert "这不是绿" in proc.stdout, f"必须明写「不是绿」（防空值被读成通过）：\n{proc.stdout}"
    assert "第 1 次" in proc.stdout, f"--once 必须只采样一次（不等待）：\n{proc.stdout}"


def test_unreported_required_exits_three_never_zero(run: Runner):
    """`PR Check` 还没**上报**（later-created run）⇒ 3，不是 0（形态 ①）。"""
    run.set_state(required={"contexts": [REQ_A, REQ_B]},
                  checks_sequence=[[_row(REQ_A)]])

    proc = run.run(PR, "--once")

    assert proc.returncode == 3, f"没上报必须 3：exit={proc.returncode}\n{proc.stdout}"
    assert REQ_B in proc.stdout and "尚未上报" in proc.stdout, f"必须点明「还没来」≠「绿」：\n{proc.stdout}"


# ── ③ required 终态非 SUCCESS ⇒ 1 ─────────────────────────────────────────────

@pytest.mark.parametrize("state", ["FAILURE", "SKIPPED"])
def test_required_not_terminal_success_exits_one(run: Runner, state: str):
    """红 / 跳过都**不是** SUCCESS ⇒ 1（宁可报红也不假绿）。"""
    run.set_state(required={"contexts": [REQ_A]}, checks_sequence=[[_row(REQ_A, state)]])

    proc = run.run(PR, "--once")

    assert proc.returncode == 1, f"{state} 必须 1：exit={proc.returncode}\n{proc.stdout}"
    assert REQ_A in proc.stdout and state in proc.stdout, f"必须具名 + 给出 state：\n{proc.stdout}"


# ── ④ 网络/API 报错 ⇒ 3，**与退出码无关** ─────────────────────────────────────

def test_network_error_text_with_zero_exit_code_exits_three(run: Runner):
    """形态 ②：`connection reset` + **rc=0** ⇒ 仍必须 3（这正是「有错误字样却退出 0」）。"""
    run.set_state(required={"contexts": [REQ_A]},
                  checks_sequence=[{"rc": 0, "stderr": "Post graphql: read: connection reset by peer",
                                    "checks": [_row(REQ_A)]}])

    proc = run.run(PR, "--once")

    assert proc.returncode == 3, f"读数里出现网络错误 ⇒ 3（不许 rc=0 当绿）：exit={proc.returncode}\n{proc.stdout}"
    assert "connection reset by peer" in proc.stdout, f"必须把**原始错误字样**打出来（可复核）：\n{proc.stdout}"


def test_api_failure_exits_three(run: Runner):
    """required 集合读不到 ⇒ 3（不是「没有 required ⇒ 全绿」）。"""
    run.set_state(required={"contexts": [REQ_A]}, api_rc=1,
                  checks_sequence=[[_row(REQ_A)]])

    proc = run.run(PR, "--once")

    assert proc.returncode == 3, f"读不到分支保护必须 3：exit={proc.returncode}\n{proc.stdout}"
    assert "403" in (proc.stdout + proc.stderr), f"必须带上原始错误读数：\n{proc.stdout}\n{proc.stderr}"


def test_gh_unavailable_exits_three(run: Runner, tmp_path: Path):
    """gh 不可用 ⇒ 3（「看不了」绝不谎报成 0）。"""
    run.set_state(required={"contexts": [REQ_A]}, checks_sequence=[[_row(REQ_A)]])

    broken = subprocess.run(
        ["bash", str(WRAPPER), PR, "--once"], capture_output=True, text=True,
        cwd=str(REPO_ROOT),
        env={**os.environ, "WC_GH_BIN": str(tmp_path / "nope" / "gh"),
             "WC_STATE": str(run.state_file)})

    assert broken.returncode == 3, f"gh 缺失必须 3：exit={broken.returncode}\n{broken.stdout}"


# ── ⑤ required 集合为空 ⇒ 3 ───────────────────────────────────────────────────

def test_empty_required_set_is_three_not_zero(run: Runner):
    """空集合 ≠ 没有 required：拿它宣告全绿正是本单要治的假绿。"""
    run.set_state(required={"contexts": []}, checks_sequence=[[]])

    proc = run.run(PR, "--once")

    assert proc.returncode == 3, f"required 为空必须 3：exit={proc.returncode}\n{proc.stdout}"
    assert "空集合不是绿" in proc.stdout, f"必须讲清为什么不是绿：\n{proc.stdout}"


# ── ⑥ 等（不是猜）：pending → 绿 ⇒ 0；到点仍 pending ⇒ 3 ─────────────────────

def test_pending_then_green_polls_to_zero(run: Runner):
    """等 ≠「一次读数就下结论」：第一次采样 pending ⇒ 继续采，第二次全绿 ⇒ 0。"""
    run.set_state(required={"contexts": [REQ_A]},
                  checks_sequence=[[_row(REQ_A, "PENDING")], [_row(REQ_A)]])

    proc = run.run(PR, "--poll-seconds", "0", "--timeout", "60")

    assert proc.returncode == 0, f"等到全绿应 0：exit={proc.returncode}\n{proc.stdout}"
    assert "第 2 次" in proc.stdout, f"必须自报采样次数（证明真的等了，不是一次就下结论）：\n{proc.stdout}"
    assert run.calls().count("gh pr checks") >= 2, f"只采样一次 ⇒ 不是「等」：\n{run.calls()}"


def test_timeout_while_pending_exits_three(run: Runner):
    """到点仍 pending ⇒ 3（超时 ≠ 绿）。"""
    run.set_state(required={"contexts": [REQ_A]}, checks_sequence=[[_row(REQ_A, "PENDING")]])

    proc = run.run(PR, "--poll-seconds", "0", "--timeout", "0")

    assert proc.returncode == 3, f"超时必须 3：exit={proc.returncode}\n{proc.stdout}"
    assert "这不是绿" in proc.stdout, f"超时也要明写不是绿：\n{proc.stdout}"


# ── ⑦ 接线：跑的是命名入口；没有 PR 号不许退 0 ───────────────────────────────

def test_entry_is_wired_to_the_single_judgment(run: Runner):
    """接线判据：入口真的把读数交给判定本体（不是「脚本存在」就算交付）。"""
    _green_run(run)

    proc = run.run(PR, "--once")

    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    calls = run.calls()
    assert calls.count("gh pr checks") == 1, f"入口应恰好读一次 checks：\n{calls}"
    assert "branches/main/protection/required_status_checks" in calls, (
        f"入口必须现取 required 集合（不写死清单）：\n{calls}")
    head = subprocess.run(["bash", str(WRAPPER)], capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert head.returncode == 3, f"没给 PR 号 ⇒ 3（未判定不得当通过）：exit={head.returncode}"


# ── 红证：每条判据各自能单独变红（+ 只改注释的对照）────────────────────────────

_WAIT_ANCHORS = {
    # ② 的坏形态：把 pending 当绿（= 旧 `--watch` 假完成的行为）
    "pending_as_green": (
        '        return WaitVerdict(code=EXIT_UNDECIDABLE,\n'
        '                           reason="required 判据还没跑完（"',
        '        return WaitVerdict(code=EXIT_OK,\n'
        '                           reason="required 判据还没跑完（"',
        "test_pending_required_exits_three_never_zero",
    ),
    # ④ 的坏形态：不看网络错误字样（形态 ② 的原样复发）
    "ignore_network_errors": (
        "    hits = [m for m in NETWORK_ERROR_MARKERS if m in text]",
        "    hits = []  # 变异：不看网络/API 错误字样",
        "test_network_error_text_with_zero_exit_code_exits_three",
    ),
    # ③ 的坏形态：任何终态都算绿
    "any_state_is_green": (
        "        if state in WAIT_GREEN_STATES:",
        "        if True:  # 变异：任何 state 都算绿",
        "test_required_not_terminal_success_exits_one",
    ),
    # 对照：只改注释 ⇒ 三条判据必须照旧
    "comment_only": (
        "#: 只有终态 SUCCESS 才算绿",
        "#: （只改措辞，语义不变）只有终态 SUCCESS 才算绿",
        "",
    ),
}


def _mutated_copy(dest: Path, anchor: str, replacement: str) -> Path:
    """把真判定本体逐字替换一处，落成可独立运行的一份副本（自证：唯一命中 / 真的变了 / 仍是合法 Python）。"""
    src = JUDGE.read_text(encoding="utf-8")
    assert src.count(anchor) == 1, f"注入锚点必须**恰好命中 1 次**（源码漂移 ⇒ 红证失效）：{anchor!r}"
    mutated = src.replace(anchor, replacement)
    assert mutated != src, "变异没落到源码上"
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / "merge_gate.py"
    target.write_text(mutated, encoding="utf-8")
    compile(mutated, str(target), "exec")
    wrapper = dest / "wait-checks.sh"
    shutil.copy(WRAPPER, wrapper)
    return wrapper


def test_criteria_have_discriminating_power(run: Runner, tmp_path: Path):
    """**红证**：三处各改坏一处 ⇒ 对应判据必红；**只改注释** ⇒ 三条都照旧（证明判的是语义）。"""
    cases = {
        "pending_as_green": ({"required": {"contexts": [REQ_A, REQ_B]},
                              "checks_sequence": [[_row(REQ_A), _row(REQ_B, "PENDING")]]},
                             ("--once",), 3),
        "ignore_network_errors": ({"required": {"contexts": [REQ_A]},
                                   "checks_sequence": [{"rc": 0, "stderr":
                                                        "Post graphql: read: connection reset by peer",
                                                        "checks": [_row(REQ_A)]}]},
                                  ("--once",), 3),
        "any_state_is_green": ({"required": {"contexts": [REQ_A]},
                                "checks_sequence": [[_row(REQ_A, "SKIPPED")]]},
                               ("--once",), 1),
    }
    for key, (state, args, expect) in cases.items():
        anchor, replacement, _ = _WAIT_ANCHORS[key]
        wrapper = _mutated_copy(tmp_path / f"mut-{key}", anchor, replacement)
        run.set_state(**state)
        proc = run.run(PR, *args, wrapper=wrapper)
        assert proc.returncode != expect, (
            f"注入 `{key}` 之后判定必须翻转（否则该判据是空断言）：仍 {proc.returncode}\n{proc.stdout}")
        assert proc.returncode in (0, 1, 3), f"变异体必须仍给合法三态：{proc.returncode}"

    # 对照读数：只改注释 ⇒ 三个形态都必须照旧
    anchor, replacement, _ = _WAIT_ANCHORS["comment_only"]
    wrapper = _mutated_copy(tmp_path / "mut-comment", anchor, replacement)
    for key, (state, args, expect) in cases.items():
        run.set_state(**state)
        proc = run.run(PR, *args, wrapper=wrapper)
        assert proc.returncode == expect, (
            f"只改注释 ⇒ `{key}` 必须照旧 {expect}（得 {proc.returncode}）：判据在判文本不是判语义\n{proc.stdout}")
