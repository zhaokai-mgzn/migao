# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 `.github/cases/misc.yml` 的 MC-012 登记。本 PR **不新建用例族**。）
"""#5649：`reconcile` 与 `approval-queue` 对「台账分支不存在」**必须同判** —— 类级守卫。

## 病灶（实测读数，不是推断）

`Flaky Ledger Reconcile`（`.github/workflows/flaky-ledger-reconcile.yml`，**不在 required 集合**
⇒ 不拦合并）**对每个 PR 都红**。逐层取到 CI 日志原文（run `36237750162` / job `108392519736`）：

```
「台账欠账可见性（#5307）」步骤：
  ℹ️ 台账分支 `chore/flaky-ledger` 不存在 ⇒ 没有可对账的台账（非欠账）
  ##[notice]✅ 台账分支无欠账（reconcile 干净）          ← 这一步**已过** ✅
「审批队列读数（#5417）」步骤：
  ##[error]无法判定审批队列状态（approval-queue 退 3）   ← 真正红的是这一步 ❌
```

**同一个条件**（台账分支不存在）、**两套读数**：`reconcile --branch` 判 0（没有可对账的内容），
`approval-queue` 去取分支 tip（`GET /repos/{repo}/branches/{head_branch}`）撞 **404** ⇒ 与
「`gh` 真的失败」被读成同一件事 ⇒ 退 3。⇒ 长期假红持续稀释「红 = 有事」的信号。
（该 job 的工作区是 `ref: main` ⇒ 本修的效果随**合并**生效，判据随**本 PR** 生效 —— 见 PR body。）

## 本文件固化什么（两层 + 常驻红证）

| 层 | 判据 | 红了说明什么 |
|---|---|---|
| 一致性（实例） | 对**同一组输入**（`exists` / `absent` / `unknown`）断言两个子命令同判：`absent` ⇒ **都退 0** 且都打可读 notice；`unknown` ⇒ **都退 3** | 两个子命令又各给一套读数（本单要治的形态复发） |
| 类级（元守卫） | ① 存在性读数**只允许一处**（AST 数 `_git("ls-remote", …)` 调用点 = 1）② 两个子命令的处理块都**到达**同一个读数 `branch_presence`、且都查**同一张**口径表 `BRANCH_PRESENCE_VERDICT` | 又长出第二份判据 / 某个子命令绕过唯一口径自己判 |
| 常驻红证（`TestInjectionRedProofs`） | 在**内存里**注入三种坏形态，断言上面的谓词**必红** | 判据是空断言（怎么都不会红）—— 这正是「不会红的断言 = 空断言」 |

⚠️ **不许**把「无法判定」降级成「通过」：`absent`（**确定**不存在）才判「无内容」；
`unknown`（`git ls-remote` 真失败）与「分支存在但 `gh` 取 tip 失败」**照旧退 3**。

## 判据语料排除判据自身（§23.8 B1）

元守卫的语料 = **单个文件** `.github/scripts/flaky_ledger.py`（显式路径，不是全仓 glob）⇒
本守卫文件天然不在语料内；`TestInjectionRedProofs::test_guard_corpus_excludes_itself…` 把这条
**自证**成断言，并用内存注入证明计数器不是空断言。

## 判据**只有一处实现**（不复制规则）

每个判定都写成**谓词函数**（返回违规清单），直接用例与注入红证**共用同一个谓词** ——
红证跑的就是出货判据本身，不存在「红证测的是另一份副本」。
"""
from __future__ import annotations

import ast
import importlib.util
import io
import json
import subprocess
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / ".github" / "scripts" / "flaky_ledger.py"
#: **判据自身**：语料自证用（B1：判据语料必须排除判据自身）。
GUARD_FILE = Path(__file__).resolve()

BRANCH = "chore/flaky-ledger"
TIP = "b3ef1fbd31ba57d80c38cf77e5c8e0226710d5a4"


def _load_module(name: str, path: Path = SCRIPT):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FL = _load_module("migao_flaky_ledger_5649")

#: 合规且**干净**的台账（`ledger_violations` 为空、`reconcile` 三态全空 ⇒ 退 0）。
CLEAN_LEDGER = {"version": 2, "note": "guard", "_schema": {}, "entries": []}

#: 合规但**确有欠账**的台账：`kind=flaky` / `status=open` / 无 `follow_up` ⇒ `new_events` 非空
#: ⇒ `reconcile` 退 1（**真欠账不许被本修吞掉**）。
DIRTY_LEDGER = {
    "version": 2, "note": "guard", "_schema": {},
    "entries": [{
        "workflow": "PR Check", "job": "unit tests", "run_id": 1,
        "rerun_result": "success", "kind": "flaky", "observed_at": "2026-09-26T00:00:00Z",
        "reason": "guard 语料：首次失败、重跑通过", "remedy": "登记跟踪单", "status": "open",
        "follow_up": None,
    }],
}


def _proc(rc: int, out: str = "", err: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["git"], rc, out, err)


class _Stub:
    """桩掉 `_git` / `_gh_api`（**零 IO、零网络**），跑一次 CLI。

    `presence` = 注入的**同一组输入**（`exists` / `absent` / `unknown`）—— 两个子命令用的是
    **同一个** `_git` 桩 ⇒ 这就是「同一组输入、两个子命令」的判据形态。
    """

    def __init__(self, ns, presence: str, ledger: dict | None = None, api_fails: bool = False,
                 tip: str | None = TIP):
        self.ns, self.presence = ns, presence
        self.ledger, self.api_fails, self.tip = ledger or CLEAN_LEDGER, api_fails, tip
        self.api_calls: list[str] = []

    def git(self, *args):
        if args[:1] == ("ls-remote",):
            if self.presence == "unknown":
                return _proc(128, "", "fatal: could not read from remote repository")
            if self.presence == "absent":
                return _proc(0, "", "")
            return _proc(0, f"{TIP}\trefs/heads/{BRANCH}\n", "")
        if args[:1] == ("fetch",):
            return _proc(0, "", "")
        if args[:1] == ("show",):
            return _proc(0, json.dumps(self.ledger), "")
        if args[:1] == ("rev-parse",):
            return _proc(0, TIP + "\n", "")
        return _proc(1, "", f"unexpected git call: {args!r}")

    def api(self, path):
        self.api_calls.append(path)
        if self.api_fails:
            raise subprocess.CalledProcessError(1, ["gh", "api", path], "", "HTTP 403")
        if "/branches/" in path:
            return {"commit": {"sha": self.tip}} if self.tip else {"name": BRANCH}
        return {"workflow_runs": []}

    def run(self, argv, ns=None):
        ns = ns or self.ns
        saved = {k: getattr(ns, k) for k in ("_git", "_gh_api") if hasattr(ns, k)}
        ns._git, ns._gh_api = self.git, self.api
        out, err, old = io.StringIO(), io.StringIO(), (sys.stdout, sys.stderr)
        sys.stdout, sys.stderr = out, err
        try:
            rc = ns.main(argv)
        finally:
            sys.stdout, sys.stderr = old
            for key, value in saved.items():
                setattr(ns, key, value)
        return rc, out.getvalue(), err.getvalue()


def _reconcile_argv():
    return ["reconcile", "--branch", BRANCH]


def _queue_argv():
    return ["approval-queue", "--repo", "o/r", "--head-branch", BRANCH, "--min-age-minutes", "0"]


def _mutant(*replacements) -> tuple[str, types.ModuleType]:
    """把出货源码做**内容级单点变异**（不写盘、不留变异产物）⇒ `(变异后源码, 变异后模块)`。

    注入锚点失配 ⇒ **立刻断言失败**（防「注入没生效 ⇒ 判据看起来是空的」这种假红证）。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    for old, new in replacements:
        assert old in src, f"注入锚点失效（先修本测试）：{old!r}"
        src = src.replace(old, new, 1)
    mod = types.ModuleType("migao_flaky_ledger_5649_mutant")
    mod.__file__ = str(SCRIPT)
    exec(compile(src, str(SCRIPT), "exec"), mod.__dict__)     # noqa: S102 —— 本仓既有红证形态
    return src, mod


# ══════════════════════════════════════════════════════════════════════════════════════
# 谓词（判定的**唯一实现**；直接用例与注入红证共用它）
# ══════════════════════════════════════════════════════════════════════════════════════


def consistency_violations(ns) -> list:
    """**一致性**：同一组输入 ⇒ `reconcile` 与 `approval-queue` 同判（issue #5649 的验收核心）。"""
    bad = []
    for state, expect in (("absent", 0), ("unknown", 3)):
        rc_rec, out_rec, err_rec = _Stub(ns, state).run(_reconcile_argv())
        rc_q, out_q, err_q = _Stub(ns, state).run(_queue_argv())
        if (rc_rec, rc_q) != (expect, expect):
            bad.append(f"状态 `{state}`：reconcile={rc_rec} / approval-queue={rc_q}，两边都应为 "
                       f"{expect}（rec stderr={err_rec!r} / queue stderr={err_q!r}）"
                       f"—— 同一条件两套读数，#5649 的病灶复发")
        if state == "absent":
            if "不存在" not in out_rec:
                bad.append(f"reconcile 没说清「分支不存在 ⇒ 非欠账」：{out_rec!r}")
            if "::notice::" not in out_q or "不存在" not in out_q or "无待批准 run" not in out_q:
                bad.append(f"approval-queue 判「无待批准 run」时**不许静默**（要一句可读 notice，"
                           f"且说清判成了什么）：{out_q!r}")
            if err_q.strip():
                bad.append(f"「确定无内容」不是错误，不该写 stderr：{err_q!r}")
        else:
            if "::notice::" in out_q:
                bad.append(f"无法判定**不许**打「无待批准 run」的 notice：{out_q!r}")
            if not err_q.strip():
                bad.append(f"无法判定必须写 stderr（不许静默）：{out_q!r}")
    return bad


def fail_closed_violations(ns) -> list:
    """**不许把「无法判定」降级成通过**（本单未放宽的那半边）。"""
    bad = []
    rc, out, err = _Stub(ns, "exists", api_fails=True).run(_queue_argv())
    if rc != 3:
        bad.append(f"分支存在但 `gh api` 真失败（HTTP 403）⇒ 必须退 3（无法判定），实际 {rc}"
                   f"（stdout={out!r}）")
    if not err.strip():
        bad.append("无法判定必须写 stderr")
    absent_rc = _Stub(ns, "absent").run(_queue_argv())[0]
    unknown_rc = _Stub(ns, "unknown").run(_queue_argv())[0]
    if absent_rc == unknown_rc:
        bad.append(f"`absent` 与 `unknown` 判成了同一个退出码 {absent_rc} ⇒ 要么放宽了无法判定、"
                   f"要么把「确定无内容」当成了失败")
    return bad


def semantics_violations(ns) -> list:
    """分支存在时**各按自己的语义**继续：真欠账不许被吞、干净台账不许被误判。"""
    bad = []
    rc_dirty, out_dirty, _ = _Stub(ns, "exists", ledger=DIRTY_LEDGER).run(_reconcile_argv())
    if rc_dirty != 1:
        bad.append(f"分支上确有欠账（kind=flaky/open/无 follow_up）⇒ reconcile 必须退 1，"
                   f"实际 {rc_dirty}（stdout={out_dirty!r}）—— 本修**不许**吞掉真欠账")
    rc_clean = _Stub(ns, "exists").run(_reconcile_argv())[0]
    if rc_clean != 0:
        bad.append(f"对照臂：干净台账应退 0，实际 {rc_clean}（防「一律退 1」）")
    rc_q = _Stub(ns, "exists").run(_queue_argv())[0]
    if rc_q != 0:
        bad.append(f"分支存在 ⇒ approval-queue 按既有语义退 0，实际 {rc_q}")
    stub = _Stub(ns, "absent")
    stub.run(_queue_argv())
    if stub.api_calls:
        bad.append(f"分支确定不存在时仍打了 API（{stub.api_calls}）⇒ 又出现第二处读数")
    return bad


def _ls_remote_call_sites(src: str) -> int:
    """AST 数 `_git("ls-remote", …)` 的**调用点**（注释 / docstring 里的「提及」不算）。"""
    n = 0
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_git" and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "ls-remote"):
            n += 1
    return n


def single_instrument_violations(src: str) -> list:
    """**唯一读数**：`ls-remote` 探针在模块里只允许一处（第二处 = 「同一真值两处投影」#4393）。"""
    sites = _ls_remote_call_sites(src)
    if sites != 1:
        return [f"`_git(\"ls-remote\", …)` 调用点 = {sites}，应为 1 —— 台账分支存在性必须有"
                f"**唯一读数**；多出来的那处请改调 `branch_presence()`"]
    return []


def _cmd_handler(src: str, cmd: str) -> ast.If:
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.If):
            continue
        t = node.test
        if (isinstance(t, ast.Compare) and isinstance(t.left, ast.Attribute)
                and t.left.attr == "cmd" and isinstance(t.left.value, ast.Name)
                and t.left.value.id == "args" and len(t.comparators) == 1
                and isinstance(t.comparators[0], ast.Constant)
                and t.comparators[0].value == cmd):
            return node
    raise AssertionError(f"源码里找不到 `args.cmd == {cmd!r}` 的处理块（先修本测试）")


def _module_call_graph(tree: ast.Module) -> dict:
    """模块级函数 → 它直接调用的**模块级函数名**（`ast` 不看注释 ⇒「注释里提及」不算）。"""
    graph: dict = {}
    for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef)]:
        graph[fn.name] = {c.func.id for c in ast.walk(fn)
                          if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    return graph


def _reaches(graph: dict, starts, target: str) -> bool:
    seen, stack = set(), list(starts)
    while stack:
        cur = stack.pop()
        if cur == target:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(graph.get(cur, ()))
    return False


def shared_route_violations(src: str) -> list:
    """两个子命令的处理块都必须**到达**唯一读数，并查**同一张**口径表。

    到达 = 沿模块内调用图可达（`reconcile` 经 `read_branch_ledger` 到达、`approval-queue` 直呼）
    —— 判据不绑死调用层次，只要求「不许自己判分支存在性」。
    """
    graph = _module_call_graph(ast.parse(src))
    bad = []
    for cmd in ("reconcile", "approval-queue"):
        handler = _cmd_handler(src, cmd)
        used = {n.id for n in ast.walk(handler) if isinstance(n, ast.Name)}
        direct = {c.func.id for c in ast.walk(handler)
                  if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        if "branch_presence" not in used and not _reaches(graph, direct, "branch_presence"):
            bad.append(f"`{cmd}` 的处理块**到不了**唯一读数 `branch_presence()` ⇒ 它自己判分支"
                       f"存在性（= 又一套口径，#5649 的病灶）")
        if "BRANCH_PRESENCE_VERDICT" not in used:
            bad.append(f"`{cmd}` 的处理块没有查唯一口径表 `BRANCH_PRESENCE_VERDICT` ⇒ 判定散在两处")
    return bad


def verdict_table_violations(ns) -> list:
    """口径表的内容本身是判据：`absent ⇒ 0`、`unknown ⇒ 3`，且 `exists` **不在表里**。"""
    got = dict(getattr(ns, "BRANCH_PRESENCE_VERDICT", {}) or {})
    want = {getattr(ns, "BRANCH_ABSENT", "absent"): 0, getattr(ns, "BRANCH_UNKNOWN", "unknown"): 3}
    if got != want:
        return [f"口径表被改动：{got} —— `absent` 必须判「无内容」（0）、`unknown` 必须判"
                f"「无法判定」（3）；`exists` 不许进表（各子命令按自己的语义继续）"]
    return []


def three_state_violations(ns) -> list:
    """唯一读数必须是**三态**（防把它简化成布尔 —— 布尔会把「读不出」并进「不存在」）。"""
    bad = []
    for state in ("exists", "absent", "unknown"):
        stub = _Stub(ns, state)
        saved = getattr(ns, "_git")
        ns._git = stub.git
        try:
            got = ns.branch_presence(BRANCH)
        finally:
            ns._git = saved
        if got != state:
            bad.append(f"注入 {state} ⇒ 唯一读数应返回 {state}，实际 {got!r}")
    return bad


# ══════════════════════════════════════════════════════════════════════════════════════
# 出货判据（谓词必须为空）
# ══════════════════════════════════════════════════════════════════════════════════════


class TestShippedJudgements:
    """出货代码上，每条谓词都必须为空（= 判据成立）。"""

    def test_consistency_both_subcommands_agree_on_the_same_inputs(self):
        assert consistency_violations(FL) == []

    def test_fail_closed_unknown_is_never_downgraded_to_pass(self):
        assert fail_closed_violations(FL) == []

    def test_each_subcommand_keeps_its_own_semantics_when_branch_exists(self):
        assert semantics_violations(FL) == []

    def test_single_branch_presence_reading_instrument(self):
        assert single_instrument_violations(SCRIPT.read_text(encoding="utf-8")) == []

    def test_both_subcommands_route_through_shared_probe_and_table(self):
        assert shared_route_violations(SCRIPT.read_text(encoding="utf-8")) == []

    def test_verdict_table_only_covers_absent_and_unknown(self):
        assert verdict_table_violations(FL) == []

    def test_branch_presence_is_three_state(self):
        assert three_state_violations(FL) == []


# ══════════════════════════════════════════════════════════════════════════════════════
# 常驻红证：把坏形态注回 ⇒ 上面的谓词**必红**（每条都带「注入生效自证」）
# ══════════════════════════════════════════════════════════════════════════════════════


class TestInjectionRedProofs:
    """「注入 ⇒ 必红」做成**常驻判据**（不是只在 PR body 里的手工动作）。"""

    def test_redproof_absent_reverted_to_unknown_verdict(self):
        """① 把 `approval-queue` 对「分支不存在」的处置改回退 3（= 本单的原始病灶）⇒ 必红。"""
        src, mod = _mutant((
            "        verdict = BRANCH_PRESENCE_VERDICT.get(presence)\n",
            "        verdict = 3 if presence == BRANCH_ABSENT else BRANCH_PRESENCE_VERDICT.get(presence)\n"))
        rc, out, _ = _Stub(mod, "absent").run(_queue_argv())
        assert rc == 3 and "::notice::" not in out, f"注入未生效（应退 3 且无 notice）：{rc} {out!r}"
        bad = consistency_violations(mod)
        assert bad, "注入了原始病灶，一致性谓词却没红 ⇒ 它是空断言"
        assert src != SCRIPT.read_text(encoding="utf-8")

    def test_redproof_reconcile_reverted_to_unknown_verdict(self):
        """② 对称方向：把 `reconcile` 对「分支不存在」的处置改回退 3 ⇒ 必红（两个方向都钉住）。"""
        _, mod = _mutant(("                return BRANCH_PRESENCE_VERDICT[BRANCH_ABSENT]\n",
                          "                return 3\n"))
        rc, _, _ = _Stub(mod, "absent").run(_reconcile_argv())
        assert rc == 3, f"注入未生效（应退 3）：{rc}"
        bad = consistency_violations(mod)
        assert bad, "注入了对称病灶，一致性谓词却没红"
        assert any("absent" in b for b in bad)

    def test_redproof_unknown_downgraded_to_absent(self):
        """③ 把「读不出」降级成「不存在」（= 把无法判定放宽成通过）⇒ 必红。"""
        _, mod = _mutant(("    if ls.returncode != 0:\n        return BRANCH_UNKNOWN\n",
                          "    if ls.returncode != 0:\n        return BRANCH_ABSENT\n"))
        assert _Stub(mod, "unknown").run(_queue_argv())[0] == 0, "注入未生效（应变成退 0）"
        assert consistency_violations(mod) or fail_closed_violations(mod), \
            "注入了「无法判定降级成通过」，谓词却没红 ⇒ 红线没被钉住"
        assert three_state_violations(mod), "三态谓词没红"

    def test_redproof_second_branch_presence_probe(self):
        """④ 注入第二处 `ls-remote` 探针（= 「同一真值两处投影」）⇒ 元守卫必红。"""
        src, _ = _mutant((
            "\ndef branch_presence(branch: str = LEDGER_BRANCH) -> str:",
            '\ndef _injected_second_probe(branch: str = LEDGER_BRANCH):\n'
            '    return _git("ls-remote", "--heads", "origin", branch)\n\n\n'
            "def branch_presence(branch: str = LEDGER_BRANCH) -> str:"))
        assert _ls_remote_call_sites(src) == 2, "注入未生效（调用点应为 2）"
        assert single_instrument_violations(src), "注入了第二处探针，元守卫却没红"

    def test_redproof_subcommand_bypassing_the_shared_verdict_table(self):
        """⑤ 让 `approval-queue` 绕过唯一口径表（自己写死判定）⇒ 元守卫必红。"""
        src, _ = _mutant(("        verdict = BRANCH_PRESENCE_VERDICT.get(presence)\n",
                          "        verdict = {BRANCH_ABSENT: 0, BRANCH_UNKNOWN: 3}.get(presence)\n"))
        assert "BRANCH_PRESENCE_VERDICT.get" not in src
        assert shared_route_violations(src), "绕过了唯一口径表，元守卫却没红"

    def test_guard_corpus_excludes_itself_and_counter_can_go_red(self):
        """**B1 自证**：语料 = 单文件（本守卫不在其中）；且计数器**不是空断言**（注入 ⇒ 必 +1）。"""
        corpus = [SCRIPT]
        assert GUARD_FILE not in corpus, (
            "判据语料把**判据自身**算进去了 ⇒ 注入的探针会被自己计数（红证变空断言，§23.8 B1）")
        assert GUARD_FILE != SCRIPT
        src = SCRIPT.read_text(encoding="utf-8")
        injected = src + ('\n\ndef _injected_probe():\n'
                          '    return _git("ls-remote", "--heads", "origin", "x")\n')
        assert _ls_remote_call_sites(injected) == _ls_remote_call_sites(src) + 1, (
            "往语料里注入第二处探针，计数器却没变 ⇒ `single_instrument_violations` 是空断言")
