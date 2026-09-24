# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 —— 见
#   tests/unit_ci_workflows/test_issue_lifecycle_finish.py 的同款声明与 `.github/cases/misc.yml`
#   MC-012「CI workflow 结构由 pytest 单测验证」的登记。本 PR 不新建用例族。）
"""`scripts/issue-lifecycle.sh` 的 `land` / `reap-merged` —— 「落地」与「新工作前自动收尾」。

## 这守的是什么（用户裁定 2026-09-24，逐字）

「**我不希望每天要花 token 浪费在基建上和定期清理工作区**」。原形态 =
集成侧**逐个手工**做 `rebase` → `gate` → `gh pr ready` → 轮询等合并 → `finish` →
（改过预设再）`preset-anchor-refresh`，一晚重复十几次；`migao-wt/` 下堆了 **77** 个 worktree，
其中一批是「PR 已合并但没人收尾」，**没有任何机制会提醒或代办**（实测一晚手工清 15 个）。

⇒ 本单落两条：① `land <分支>` 一条命令走完那条固定序列 + 一段总结；
② `reap-merged` 在建新工作区前（`dev-worktree.sh add` 调一行）把「有已合并 PR 且无 open PR」
的自动收掉。仍是**事件驱动**（不新增 schedule / cron —— 用户 2026-09-21 裁定）。

## 用例分组（每组都要有能**单独**变红的注入）

① **顺序即安全顺序（本文件最重要的一条）**：`land` 必须按 `LAND_STEPS` 执行
   （`rebase → gate → ready → wait-ci → wait-merge → finish → preset-refresh`）。
   判据读的是「**实跑顺序**」—— 替身把真实调用**按序**写进同一个日志，不是读源码文本；
   红证 = 把 `LAND_STEPS` 里 `ready` 与 `gate` 对调（**精确替换 + 自证注入生效**）⇒ 同一条判据必红。
   为什么是安全序：`ready` **自己没有前置判据**，它唯一的保护就是「`gate` 必须先跑且必须绿」；
   把 `gh pr ready` 提到 `gate` 之前 = 把闸摘掉（红的分支会被推成 ready 并交给 auto-merge）。
② **gate 判红即停**：`verify-all.sh` 替身返回 1 ⇒ **不得**出现 `gh pr ready` / `gh pr checks`
   / `preset-refresh`，worktree 与分支原样保留；
③ **未观察到合并 ⇒ 不收尾**（fail-closed）：PR 仍 OPEN ⇒ 不删 worktree、不跑 preset-refresh，
   且出口必须**真可行动**（打印 `--from wait-merge` 续跑命令）；
④ **gh 取不到 ⇒ exit 3**（无法判定 ≠ 0）：`land` 与 `reap-merged` 都要，且零动作；
⑤ **reap-merged 的判定口径**：有已合并 PR **且** 无 open PR 才收；分支被复用（既 merged 又 open）/
   未合并 / 是某个 open PR 的 base（stacked）/ 有活跃会话锁 ⇒ **都不删**；
⑥ **活锚硬保护 + 负控**：活锚目标进清理半径 ⇒ 拒删并报警（exit 2），
   且「同一命令、同一形态、**没有活锚指向它**时确实会删」—— 证明上一条不是恒绿；
⑦ **dry-run 与「零动作出声」**：`reap-merged` 默认 dry-run（零删除）、`land --dry-run` 零动作；
   没有可收尾的 ⇒ 打印「本轮零动作 + 逐类原因计数」（G6：**不许静默**）；
⑧ **接线**：`dev-worktree.sh add` 里那一行调用必须还在（**按 `cmd_add()` 函数体定位**，
   不是全文 grep）；红证 = 删掉那一行 ⇒ 判据必红。**另有一条行为级判据**：把真脚本拷进 fixture
   跑一遍真 `add` ⇒ 「已合并但没人收尾」的被**真收掉**、新工作区照建（结构断言证不了「调用真的成功」）。

夹具一律是 `tmp_path` 下的**真 git 仓库 + 真 bare origin + 真 worktree**（不是 mock）：
判据本体就是 git 语义，mock 掉 git 等于把被测对象换成替身（`migao-acceptance` §19.1「绿了但没跑」）。
外部 CLI 用**替身可执行文件**注入（`MIGAO_GH_BIN` / `MIGAO_DEVTREE_BIN` / `MIGAO_VERIFY_BIN` /
`MIGAO_PRESET_REFRESH_BIN`，替身把真实调用**按序**写进 `$CALL_LOG`）—— 只换 CLI 边界，
不 mock 被测函数。
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "issue-lifecycle.sh"
MODULE = REPO_ROOT / "scripts" / "issue_lifecycle.py"
GUARD_MODULE = REPO_ROOT / "scripts" / "agent-presets-guard.py"
DEV_WORKTREE = REPO_ROOT / "scripts" / "dev-worktree.sh"
ANCHOR_REL = Path(".dsh") / ".agent-presets" / "migao"

BRANCH = "fix/land-me"
REAP_BRANCH = "fix/done"
MERGE_ROW = {"number": 101, "state": "MERGED", "isDraft": False, "url": "https://example.invalid/101",
             "mergedAt": "2026-09-24T13:00:00Z", "headRefName": BRANCH, "baseRefName": "main",
             "files": [{"path": "scripts/issue_lifecycle.py"}]}
OPEN_ROW = {"number": 101, "state": "OPEN", "isDraft": True, "url": "https://example.invalid/101",
            "mergedAt": None, "headRefName": BRANCH, "baseRefName": "main",
            "files": [{"path": "scripts/issue_lifecycle.py"}]}

# 注入锚点：**逐字**取自 scripts/issue_lifecycle.py（唯一命中 1 次才允许变异）
LAND_STEPS_ANCHOR = (
    'LAND_STEPS: tuple[str, ...] = (\n'
    '    "rebase", "gate", "ready", "wait-ci", "wait-merge", "finish", "preset-refresh",\n'
    ')'
)
# 注入锚点：**逐字**取自 scripts/dev-worktree.sh 的那一行接线
REAP_CALL_LINE = (
    '  bash "$REPO_ROOT/scripts/issue-lifecycle.sh" reap-merged --apply --no-artifacts '
    '--except "$branch" || echo "⚠️  自动收尾未完成（exit≠0 不阻塞建工作区；原因见上）"'
)


# ── 纯函数判据（红绿两侧共用 —— 红证才有判别力）────────────────────────────────

def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location("issue_lifecycle_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载被测模块（判定本体缺失即门禁空转）：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _log_lines(log: str) -> list[str]:
    return [line for line in log.splitlines() if line.strip()]


def _marker_index(log: str, marker: str) -> int:
    for i, line in enumerate(_log_lines(log)):
        if line.startswith(marker):
            return i
    return -1


def _land_markers(branch: str) -> list[str]:
    """`land` 的七步各对应替身日志里的一条标记（`finish` 的标记 = 它自己的合并判据 gh 调用）。"""
    return ["devtree:rebase", "gate:gate", "gh:pr ready", "gh:pr checks", "gh:pr view",
            f"gh:pr list --head {branch} --state merged", "preset-refresh"]


def _order_problems(log: str, markers: list[str]) -> list[str]:
    """顺序判据本体：① 标记必须**都出现**（否则是空断言）② 相对顺序必须等于给定顺序。"""
    problems: list[str] = []
    positions = [(m, _marker_index(log, m)) for m in markers]
    missing = [m for m, i in positions if i < 0]
    if missing:
        problems.append("这些标记根本没出现（判据未跑，不得当通过）：" + "、".join(missing))
    seen = [(m, i) for m, i in positions if i >= 0]
    for (m1, i1), (m2, i2) in zip(seen, seen[1:]):
        if i2 < i1:
            problems.append(f"顺序错：{m2} 出现在 {m1} 之前（顺序即安全顺序）")
    return problems


def _cmd_add_body(script_text: str) -> str:
    """**按函数体**取 `cmd_add()` 的内容（不用全文 grep —— 宽松锚会命中别处的同名文本）。"""
    start = script_text.index("\ncmd_add() {")
    end = script_text.index("\n}\n", start)
    return script_text[start:end]


def _wiring_problems(body: str) -> list[str]:
    """接线判据本体（② 的判据对象 = `cmd_add()` 的函数体）。"""
    problems: list[str] = []
    if "reap-merged" not in body:
        problems.append("`dev-worktree.sh add` 没有调用 `reap-merged` ⇒ 自动收尾未接线（存量只增不减）")
    if "issue-lifecycle.sh" not in body:
        problems.append("接线必须走仓内既有入口 issue-lifecycle.sh（不得另写第二套判定）")
    if "--apply" not in body:
        problems.append("add 路径必须带 --apply（否则自动收尾恒为空转）")
    if '--except "$branch"' not in body:
        problems.append('必须 --except "$branch"（本次要建的分支不能被自己收掉）')
    if "--no-artifacts" not in body:
        problems.append("必须 --no-artifacts（主工作区根是跨会话共享写面：别人的 pr-body-*.md 可能正在用）")
    return problems


def _mutate_module(dest_dir: Path, anchor: str, replacement: str) -> Path:
    """把真源码里的 `anchor` **逐字**替换成 `replacement`，落成一份可独立运行的副本。

    自证三件（§23 G7「红证前提要自证」）：① 锚点**恰好命中 1 次**（宽松锚会注入到别处）
    ② 替换后源码确实变了 ③ 变异后仍是**合法 Python**（否则"红"来自语法错，不来自判据）。
    """
    src = MODULE.read_text(encoding="utf-8")
    assert src.count(anchor) == 1, f"注入锚点必须恰好命中 1 次（源码漂移 ⇒ 红证失效）：{anchor!r}"
    mutated = src.replace(anchor, replacement)
    assert mutated != src, "变异没落到源码上"
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / "issue_lifecycle.py"
    target.write_text(mutated, encoding="utf-8")
    shutil.copy(GUARD_MODULE, dest_dir / "agent-presets-guard.py")
    compile(mutated, str(target), "exec")
    return target


# ── 夹具：真 git 仓库 + 真 bare origin + 替身 CLI ──────────────────────────────

_GH_STUB = r'''#!/usr/bin/env python3
"""替身 gh：按 argv 回放 STUB_GH_STATE 指定的读数，并把**真实调用按序**记进 CALL_LOG。"""
import json, os, sys

argv = sys.argv[1:]
log = os.environ.get("CALL_LOG")
if log:
    with open(log, "a", encoding="utf-8") as fh:
        fh.write("gh:" + " ".join(argv) + "\n")

with open(os.environ["STUB_GH_STATE"], encoding="utf-8") as fh:
    state = json.load(fh)


def opt(flag):
    return argv[argv.index(flag) + 1] if flag in argv else None


def emit(payload):
    print(json.dumps(payload))
    sys.exit(0)


if argv[:2] == ["pr", "list"]:
    if int(state.get("list_rc") or 0):
        sys.exit(int(state["list_rc"]))
    rows = list(state.get("rows") or [])
    head = opt("--head")
    if head:
        rows = [r for r in rows if r.get("headRefName") == head]
    wanted = opt("--state")
    if wanted and wanted != "all":
        rows = [r for r in rows if str(r.get("state", "")).lower() == wanted.lower()]
    emit(rows)

if argv[:2] == ["pr", "ready"]:
    sys.exit(int(state.get("ready_rc") or 0))

if argv[:2] == ["pr", "checks"]:
    sys.exit(int(state.get("checks_rc") or 0))

if argv[:2] == ["pr", "view"]:
    emit(state.get("view") or {})

sys.stderr.write("替身 gh：未实现的调用 " + " ".join(argv) + "\n")
sys.exit(1)
'''

_STUB_TMPL = (
    "#!/usr/bin/env bash\n"
    "# 替身：只换 CLI 边界（记一条调用日志 + 按 env 返回码退出）\n"
    'printf \'%s\\n\' "{marker}" >> "${{CALL_LOG:-/dev/null}}"\n'
    'exit "${{{rc_env}:-0}}"\n'
)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert proc.returncode == 0, f"git {' '.join(args)} 失败：{proc.stderr}"
    return proc


def _branches(cwd: Path) -> set[str]:
    out = _git(cwd, "branch", "--format=%(refname:short)").stdout
    return {line.strip() for line in out.splitlines() if line.strip()}


def _remote_branches(cwd: Path) -> set[str]:
    out = _git(cwd, "ls-remote", "--heads", "origin").stdout
    return {line.split("refs/heads/", 1)[1].strip() for line in out.splitlines() if "refs/heads/" in line}


def _worktree_paths(cwd: Path) -> set[str]:
    out = _git(cwd, "worktree", "list", "--porcelain").stdout
    return {line.split(" ", 1)[1] for line in out.splitlines() if line.startswith("worktree ")}


class Fixture:
    """真仓库夹具 + 替身 CLI 句柄。"""

    def __init__(self, base: Path):
        self.base = base
        base.mkdir(parents=True, exist_ok=True)
        self.origin = base / "origin.git"
        self.repo = base / "repo"
        self.wt_base = base / "migao-wt"
        self.outside = base / "outside"
        self.home = base / "home"
        self.bin = base / "bin"
        self.log = base / "calls.log"
        self.state_file = base / "gh-state.json"
        for d in (self.wt_base, self.outside, self.home, self.bin):
            d.mkdir(parents=True, exist_ok=True)

        _git(base, "init", "-q", "--bare", "-b", "main", str(self.origin))
        _git(base, "clone", "-q", str(self.origin), str(self.repo))
        _git(self.repo, "config", "user.email", "fixture@example.com")
        _git(self.repo, "config", "user.name", "fixture")
        (self.repo / "README.md").write_text("fixture\n", encoding="utf-8")
        _git(self.repo, "add", "README.md")
        _git(self.repo, "commit", "-q", "-m", "init")
        _git(self.repo, "push", "-q", "-u", "origin", "main")

        self.state: dict = {"rows": [], "view": {}, "ready_rc": 0, "checks_rc": 0, "list_rc": 0}
        self.set_state()
        self._write_stubs()

    # ── gh 替身的读数（tests 改完调 set_state()）──
    def set_state(self, rows: list | None = None, view: dict | None = None, **rc) -> None:
        if rows is not None:
            self.state["rows"] = rows
        if view is not None:
            self.state["view"] = view
        self.state.update(rc)
        self.state_file.write_text(json.dumps(self.state), encoding="utf-8")

    def _write_stubs(self) -> None:
        gh = self.bin / "gh"
        gh.write_text(_GH_STUB, encoding="utf-8")
        gh.chmod(0o755)
        for name, marker, rc_env in (("dev-worktree.sh", "devtree:$*", "STUB_REBASE_RC"),
                                     ("verify-all.sh", "gate:$*", "STUB_GATE_RC"),
                                     ("preset-anchor-refresh.sh", "preset-refresh", "STUB_PRESET_RC")):
            path = self.bin / name
            path.write_text(_STUB_TMPL.format(marker=marker, rc_env=rc_env), encoding="utf-8")
            path.chmod(0o755)

    # ── 仓库操作 ──
    def add_worktree(self, branch: str, name: str | None = None, base: Path | None = None) -> Path:
        path = (base or self.wt_base) / (name or branch.split("/", 1)[-1])
        _git(self.repo, "branch", branch, "main")
        _git(self.repo, "worktree", "add", "-q", str(path), branch)
        # 自证夹具真的造出了形态：否则后续那些「**不在** worktree list 里」的断言会变成**空断言**
        # （路径字符串两边对不上时就恒绿 —— 实测：`tempfile` 的 `/var` 与 git 报的 `/private/var`
        #  就是这种失配。pytest 的 tmp_path 已 resolve，本条把该前提钉死）。
        assert str(path) in _worktree_paths(self.repo), f"夹具没造出 worktree：{path}"
        return path

    def push_branch(self, branch: str) -> None:
        _git(self.repo, "push", "-q", "origin", f"{branch}:{branch}")

    def anchor_link(self, target: Path) -> Path:
        link = self.home / ANCHOR_REL
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(target)
        return link

    def lock(self, branch: str) -> Path:
        """登记一条**活跃**会话锁（PID 用本测试进程 —— kill -0 必然存活）。"""
        lock_dir = self.repo / ".git" / "sessions"
        lock_dir.mkdir(parents=True, exist_ok=True)
        path = lock_dir / (branch.replace("/", "-") + ".lock")
        path.write_text(f"{os.getpid()}|2026-09-24 22:00:00|{branch}|{self.wt_base}\n", encoding="utf-8")
        return path

    # ── 调用被测脚本 ──
    def env(self, extra: dict | None = None) -> dict:
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        env["CALL_LOG"] = str(self.log)
        env["STUB_GH_STATE"] = str(self.state_file)
        env["MIGAO_WT_BASE"] = str(self.wt_base)
        env["MIGAO_GH_BIN"] = str(self.bin / "gh")
        env["MIGAO_DEVTREE_BIN"] = str(self.bin / "dev-worktree.sh")
        env["MIGAO_VERIFY_BIN"] = str(self.bin / "verify-all.sh")
        env["MIGAO_PRESET_REFRESH_BIN"] = str(self.bin / "preset-anchor-refresh.sh")
        env["PATH"] = str(self.bin) + os.pathsep + env.get("PATH", "")
        env.pop("MIGAO_ANCHOR", None)
        env.update(extra or {})
        return env

    def run(self, *args: str, extra_env: dict | None = None, cwd: Path | None = None):
        """走**真入口** `issue-lifecycle.sh`（外壳 + 判定本体一起验）。"""
        return subprocess.run(["bash", str(SCRIPT), *args], cwd=str(cwd or self.repo),
                              capture_output=True, text=True, env=self.env(extra_env))

    def run_module(self, module: Path, *args: str, extra_env: dict | None = None):
        """直接跑指定副本的判定本体（变异注入用；与 run() 同一套替身环境）。"""
        return subprocess.run([sys.executable, str(module), *args], cwd=str(self.repo),
                              capture_output=True, text=True, env=self.env(extra_env))

    def log_text(self) -> str:
        return self.log.read_text(encoding="utf-8") if self.log.exists() else ""


@pytest.fixture()
def fx(tmp_path: Path) -> Fixture:
    return Fixture(tmp_path)


def _land_shape(fx: Fixture, *, draft: bool = True, files: list[str] | None = None,
                merged_only: bool = False, view: dict | None = None) -> Path:
    """造「在飞 PR + 已推送分支 + worktree」的形态（默认：draft PR 仍在飞，合并已发生）。"""
    path = fx.add_worktree(BRANCH)
    fx.push_branch(BRANCH)
    pr_files = [{"path": p} for p in (files or ["scripts/issue_lifecycle.py"])]
    open_row = dict(OPEN_ROW, isDraft=draft, files=pr_files)
    merged_row = dict(MERGE_ROW, files=pr_files)
    rows = [merged_row] if merged_only else [open_row, merged_row]
    fx.set_state(rows=rows, view=view if view is not None else
                 {"state": "MERGED", "mergedAt": "2026-09-24T13:00:00Z"})
    return path


def _mk(fx: Fixture, branch: str, *, name: str | None = None, base: Path | None = None,
        push: bool = True) -> Path:
    """造一个「分支 + worktree（可选推送）」；PR 读数由各用例自己 set_state。"""
    path = fx.add_worktree(branch, name=name, base=base)
    if push:
        fx.push_branch(branch)
    return path


def _merged_row(branch: str, number: int = 9) -> dict:
    return {"number": number, "state": "MERGED", "headRefName": branch, "baseRefName": "main"}


def _open_row(branch: str, number: int = 7, base: str = "main") -> dict:
    return {"number": number, "state": "OPEN", "headRefName": branch, "baseRefName": base}


# ── ① 顺序即安全顺序 ─────────────────────────────────────────────────────────

def test_land_plan_is_the_safety_sequence():
    """计划序 = 安全序；且 `--from` **不可能**跳过 rebase/gate/ready。"""
    module = _load_module(MODULE)
    assert list(module.LAND_STEPS) == [
        "rebase", "gate", "ready", "wait-ci", "wait-merge", "finish", "preset-refresh",
    ], f"计划序被改动（顺序即安全顺序）：{list(module.LAND_STEPS)}"
    assert list(module.LAND_RESUMABLE_FROM) == ["wait-ci", "wait-merge", "finish", "preset-refresh"]
    for step in ("rebase", "gate", "ready"):
        assert step not in module.LAND_RESUMABLE_FROM, f"--from 竟然允许跳过 {step}（顺序锁破）"


def test_land_executes_gate_before_ready(fx: Fixture):
    """实跑序必须等于安全序（读替身日志里**真实调用**的相对顺序）。

    ⚠️ 变更集带上 `.agent-presets/**`：让**七步全都真跑**（否则 `preset-refresh` 会被合法跳过，
    那条标记不出现 ⇒ 判据退化成空断言 —— 标记缺失由 `_order_problems` 显式判红）。
    """
    wt = _land_shape(fx, files=[".agent-presets/migao/preset.yml"])

    proc = fx.run("land", BRANCH)

    log = fx.log_text()
    problems = _order_problems(log, _land_markers(BRANCH))
    assert problems == [], f"实跑顺序不等于安全序：{problems}\n--- log ---\n{log}\n--- out ---\n{proc.stdout}"
    assert proc.returncode == 0, f"正常落地应 exit 0：\n{proc.stdout}\n{proc.stderr}"
    assert "land 完成" in proc.stdout, f"必须给一行结论：\n{proc.stdout}"
    assert str(wt) not in _worktree_paths(fx.repo), "已合并 ⇒ worktree 应收尾"
    assert BRANCH not in _branches(fx.repo), "已合并 ⇒ 本地分支应收尾"
    assert BRANCH not in _remote_branches(fx.repo), "已合并 ⇒ 远程分支应收尾"


def test_land_order_criterion_is_red_when_ready_moves_before_gate(tmp_path: Path):
    """**红证**：把 `ready` 提到 `gate` 之前（精确替换 `LAND_STEPS`）⇒ 同一条顺序判据必红。

    绿侧与红侧用**同一个** `_order_problems()` 判据、同一套夹具 ⇒ 判别力可归因。
    另：注入后先**自证注入生效**（加载变异模块、断言顺序真的换了）——§23 G7「前提要自证」。
    """
    mutated_dir = tmp_path / "mutated"
    mutated_dir.mkdir()
    src = MODULE.read_text(encoding="utf-8")
    assert src.count(LAND_STEPS_ANCHOR) == 1, "注入锚点必须**恰好命中 1 次**（宽松锚会注入到别处）"
    swapped = LAND_STEPS_ANCHOR.replace('"gate", "ready"', '"ready", "gate"')
    assert swapped != LAND_STEPS_ANCHOR, "替换没生效（锚点与源码漂移 ⇒ 本条红证会变成空断言）"
    mutated_src = src.replace(LAND_STEPS_ANCHOR, swapped)
    assert mutated_src != src, "变异没落到源码上"
    (mutated_dir / "issue_lifecycle.py").write_text(mutated_src, encoding="utf-8")
    shutil.copy(GUARD_MODULE, mutated_dir / "agent-presets-guard.py")

    mutated_module = _load_module(mutated_dir / "issue_lifecycle.py")
    steps = list(mutated_module.LAND_STEPS)
    assert steps.index("ready") < steps.index("gate"), f"注入未生效（顺序没换）：{steps}"

    green = Fixture(tmp_path / "green")
    _land_shape(green, files=[".agent-presets/migao/preset.yml"])
    green_proc = green.run("land", BRANCH)
    green_log = green.log_text()
    green_problems = _order_problems(green_log, _land_markers(BRANCH))
    assert green_problems == [], f"基线（真实现）必须绿：{green_problems}\n{green_log}"
    assert green_proc.returncode == 0, f"{green_proc.stdout}\n{green_proc.stderr}"

    red = Fixture(tmp_path / "red")
    _land_shape(red, files=[".agent-presets/migao/preset.yml"])
    red.run_module(mutated_dir / "issue_lifecycle.py", "land", BRANCH)
    red_log = red.log_text()
    red_problems = _order_problems(red_log, _land_markers(BRANCH))
    assert red_problems, f"把 ready 提到 gate 之前 ⇒ 顺序判据必须红（顺序即安全顺序）\n{red_log}"
    assert any("顺序错" in p for p in red_problems), f"红的必须是**顺序**这件事：{red_problems}"


# ── ② gate 判红即停 + ④ gh 取不到 ⇒ 3 ───────────────────────────────────────

def test_land_gate_red_stops_before_ready(fx: Fixture):
    """`gate` 判红 ⇒ 立即停：不 ready、不等 CI、不收尾，worktree 与分支原样保留。"""
    wt = _land_shape(fx)

    proc = fx.run("land", BRANCH, extra_env={"STUB_GATE_RC": "1"})

    log = fx.log_text()
    assert proc.returncode == 2, f"gate 判红必须 fail-closed（exit 2）：exit={proc.returncode}\n{proc.stdout}"
    assert "devtree:rebase" in log and "gate:gate" in log, f"判据未跑（步骤没执行）：\n{log}"
    assert "gh:pr ready" not in log, f"gate 判红后不得 ready（顺序即安全顺序）：\n{log}"
    assert "gh:pr checks" not in log, f"gate 判红后不得等 CI：\n{log}"
    assert "preset-refresh" not in log, f"gate 判红后不得刷活锚：\n{log}"
    assert str(wt) in _worktree_paths(fx.repo), "gate 判红却动了工作区"
    assert BRANCH in _branches(fx.repo), "gate 判红却删了本地分支"
    assert "gate" in (proc.stdout + proc.stderr), f"必须点明停在哪一步：\n{proc.stdout}"


def test_land_gh_unavailable_is_three_and_zero_action(fx: Fixture):
    """取不到 gh ⇒ exit 3（**无法判定 ≠ 0**），且**零动作**（rebase/gate/ready 一个都不许跑）。"""
    wt = _land_shape(fx)

    proc = fx.run("land", BRANCH, extra_env={"MIGAO_GH_BIN": "/nonexistent/gh"})

    assert proc.returncode == 3, f"gh 缺失必须 exit=3：exit={proc.returncode}\n{proc.stdout}"
    assert fx.log_text().strip() == "", f"判据未跑时不得有任何动作：\n{fx.log_text()}"
    assert str(wt) in _worktree_paths(fx.repo)


def test_land_dry_run_is_zero_action(fx: Fixture):
    """`land --dry-run` ⇒ 打印计划但**零动作**（判据 6：新子命令都要能 dry-run）。"""
    wt = _land_shape(fx)

    proc = fx.run("land", BRANCH, "--dry-run")

    log = fx.log_text()
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert "dry-run" in proc.stdout, f"必须自报 dry-run：\n{proc.stdout}"
    assert "rebase → gate → ready" in proc.stdout, f"必须打印计划序：\n{proc.stdout}"
    for marker in ("devtree:rebase", "gate:gate", "gh:pr ready", "gh:pr checks",
                   "gh:pr view", "preset-refresh"):
        assert marker not in log, f"dry-run 竟然执行了 {marker}：\n{log}"
    assert str(wt) in _worktree_paths(fx.repo), "dry-run 竟然动了工作区"


# ── ③ 未观察到合并 ⇒ 不收尾 ─────────────────────────────────────────────────

def test_land_does_not_finish_when_merge_not_observed(fx: Fixture):
    """checks 已结束但 PR 仍 OPEN ⇒ 不猜、不收尾，并给出**可续跑**的出口。"""
    wt = _land_shape(fx, view={"state": "OPEN", "mergedAt": ""})

    proc = fx.run("land", BRANCH)

    log = fx.log_text()
    assert proc.returncode == 2, f"未观察到合并必须 fail-closed：exit={proc.returncode}\n{proc.stdout}"
    assert "未观察到合并" in proc.stdout, f"必须如实说「未观察」：\n{proc.stdout}"
    assert "--from wait-merge" in proc.stdout, f"出口必须真可行动：\n{proc.stdout}"
    assert "preset-refresh" not in log, f"未确认合并不得刷活锚：\n{log}"
    assert str(wt) in _worktree_paths(fx.repo), "未确认合并就收尾了"
    assert BRANCH in _branches(fx.repo), "未确认合并就删了本地分支"


# ── ⑤（land 侧）已合并形态：跳过要出声；预设变更 ⇒ 刷活锚 ────────────────────

def test_land_merged_pr_shape_finishes_and_skips_with_reason(fx: Fixture):
    """「已合并但没人收尾」⇒ 只做 finish（不重跑 rebase/gate），跳过项必须**打印原因**。"""
    wt = _land_shape(fx, merged_only=True)

    proc = fx.run("land", BRANCH)

    log = fx.log_text()
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert "devtree:rebase" not in log and "gate:gate" not in log, f"已合并 ⇒ 不该重跑 rebase/gate：\n{log}"
    assert "gh:pr view" not in log, f"已合并 ⇒ 不必再看 CI/合并状态：\n{log}"
    assert f"gh:pr list --head {BRANCH} --state merged" in log, f"finish 的合并判据必须真跑：\n{log}"
    assert "preset-refresh" not in log, f"变更集不含预设 ⇒ 不该刷活锚：\n{log}"
    assert "跳过" in proc.stdout and ".agent-presets" in proc.stdout, f"跳过必须出声并给原因：\n{proc.stdout}"
    assert str(wt) not in _worktree_paths(fx.repo), "已合并 ⇒ 应收尾"
    assert BRANCH not in _branches(fx.repo)


def test_land_runs_preset_refresh_when_change_set_touches_presets(fx: Fixture):
    """变更集含 `.agent-presets/**` ⇒ 跑 preset-anchor-refresh，且**在收尾之后**（§18.2）。"""
    _land_shape(fx, files=[".agent-presets/migao/preset.yml", "scripts/issue_lifecycle.py"])

    proc = fx.run("land", BRANCH)

    log = fx.log_text()
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert "preset-refresh" in log, f"预设变更后必须刷活锚（否则 drift 面硬漂移）：\n{log}"
    assert _marker_index(log, "preset-refresh") > _marker_index(
        log, f"gh:pr list --head {BRANCH} --state merged"), "刷活锚必须在收尾**之后**（顺序即安全顺序）"
    assert "preset-anchor-refresh.sh" in proc.stdout, f"总结里要看得出做了什么：\n{proc.stdout}"


# ── ⑥ reap-merged：判定口径 ─────────────────────────────────────────────────

def test_reap_merged_reaps_merged_without_open_pr(fx: Fixture):
    """「有已合并 PR 且无 open PR」⇒ worktree + 本地分支 + 远程分支全清。"""
    wt = _mk(fx, REAP_BRANCH)
    fx.set_state(rows=[_merged_row(REAP_BRANCH)])
    # 先自证「形态确实存在」（否则"清理成功"可能是空断言）
    assert str(wt) in _worktree_paths(fx.repo), "夹具没造出 worktree"
    assert REAP_BRANCH in _branches(fx.repo), "夹具没造出本地分支"
    assert REAP_BRANCH in _remote_branches(fx.repo), "夹具没造出远程分支"

    proc = fx.run("reap-merged", "--apply")

    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert str(wt) not in _worktree_paths(fx.repo), "已合并且无 open PR ⇒ 应收掉 worktree"
    assert REAP_BRANCH not in _branches(fx.repo), "应收掉本地分支"
    assert REAP_BRANCH not in _remote_branches(fx.repo), "应收掉远程分支"
    assert "--state all" in fx.log_text(), f"PR 判据必须走 GitHub PR 状态：\n{fx.log_text()}"


def test_reap_merged_keeps_branch_with_open_pr(fx: Fixture):
    """分支被复用（既 merged 又 open）⇒ **不删**（否则会删掉正在飞的那条 PR）。"""
    wt = _mk(fx, REAP_BRANCH)
    fx.set_state(rows=[_open_row(REAP_BRANCH), _merged_row(REAP_BRANCH)])

    proc = fx.run("reap-merged", "--apply")

    assert proc.returncode == 0, f"零动作不是错误：exit={proc.returncode}\n{proc.stdout}"
    assert str(wt) in _worktree_paths(fx.repo), "有 open PR 却删了 worktree"
    assert REAP_BRANCH in _branches(fx.repo), "有 open PR 却删了本地分支"
    assert REAP_BRANCH in _remote_branches(fx.repo), "有 open PR 却删了远程分支"
    assert "有 open PR" in proc.stdout, f"必须点明拒绝原因：\n{proc.stdout}"
    assert "零动作" in proc.stdout, f"零动作必须出声（G6）：\n{proc.stdout}"


def test_open_pr_guard_is_red_when_that_check_is_removed(tmp_path: Path):
    """**红证（差分）**：把 `classify_candidate` 里的 open PR 闸摘掉 ⇒ 同一条判据必红。

    基线（真实现）= 有 open PR ⇒ 不删；变异 = 同一个形态会被删掉 ⇒ 判据「必须保留」在变异体上失败。
    """
    open_merged_rows = [_open_row(REAP_BRANCH), _merged_row(REAP_BRANCH)]
    mutant = _mutate_module(
        tmp_path / "mutated-open-pr",
        anchor=('    if c.branch in open_nums:\n'
                '        return False, "有 open PR", f"有 open PR（#{open_nums[c.branch]}）⇒ 在飞，不动"\n'),
        replacement="",
    )
    assert 'return False, "有 open PR"' not in mutant.read_text(encoding="utf-8"), "注入未生效（闸还在）"

    green = Fixture(tmp_path / "green")
    green_wt = _mk(green, REAP_BRANCH)
    green.set_state(rows=open_merged_rows)
    green.run("reap-merged", "--apply")
    assert str(green_wt) in _worktree_paths(green.repo), "基线：有 open PR 必须保留（这一条不能红）"

    red = Fixture(tmp_path / "red")
    red_wt = _mk(red, REAP_BRANCH)
    red.set_state(rows=open_merged_rows)
    red.run_module(mutant, "reap-merged", "--apply")
    assert str(red_wt) not in _worktree_paths(red.repo), (
        "摘掉 open PR 闸后竟然还是没删 ⇒ 这条判据没有判别力（红证失效）")
    assert REAP_BRANCH not in _branches(red.repo), "摘掉闸后本地分支也应被删（差分读数）"


def test_anchor_guard_is_red_when_that_check_is_removed(tmp_path: Path):
    """**红证（差分）**：把活锚保护那两行摘掉 ⇒ 同一条判据必红（活锚目标真的会被删）。

    与 `test_reap_merged_anchor_protection_is_negative_controlled` 互补：负控证明"没有活锚时会删"，
    本条证明"**判据的判别力来自那两行本身**"（摘掉就守不住）。
    """
    mutant = _mutate_module(
        tmp_path / "mutated-anchor",
        anchor=('        if why:\n'
                '            return False, "活锚保护", "**活锚保护**：" + why\n'),
        replacement="",
    )
    assert 'return False, "活锚保护"' not in mutant.read_text(encoding="utf-8"), "注入未生效（保护还在）"

    green = Fixture(tmp_path / "green")
    green_wt = _mk(green, REAP_BRANCH)
    green.anchor_link(green_wt)
    green.set_state(rows=[_merged_row(REAP_BRANCH)])
    green.run("reap-merged", "--apply")
    assert str(green_wt) in _worktree_paths(green.repo), "基线：活锚目标必须保留（这一条不能红）"

    red = Fixture(tmp_path / "red")
    red_wt = _mk(red, REAP_BRANCH)
    red.anchor_link(red_wt)
    red.set_state(rows=[_merged_row(REAP_BRANCH)])
    red.run_module(mutant, "reap-merged", "--apply")
    assert str(red_wt) not in _worktree_paths(red.repo), (
        "摘掉活锚保护后竟然还是没删 ⇒ 这条判据没有判别力（红证失效）")


def test_reap_merged_keeps_unmerged_branch(fx: Fixture):
    """从未有 PR / 未合并 ⇒ fail-closed（同一个「零动作」出口）。"""
    wt = _mk(fx, REAP_BRANCH)
    fx.set_state(rows=[_merged_row("fix/someone-else", number=3)])

    proc = fx.run("reap-merged", "--apply")

    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert str(wt) in _worktree_paths(fx.repo), "未合并却删了 worktree"
    assert REAP_BRANCH in _branches(fx.repo)
    assert "无已合并 PR" in proc.stdout, f"必须点明拒绝原因：\n{proc.stdout}"
    assert "零动作" in proc.stdout, f"零动作必须出声（G6）：\n{proc.stdout}"


def test_reap_merged_keeps_stacked_base_and_locked_branch(fx: Fixture):
    """stacked（是 open PR 的 base）与**活跃会话锁**两条保护各有一条读数。"""
    base_branch, locked_branch = "fix/stack-base", "fix/locked"
    base_wt = _mk(fx, base_branch, name="stack-base")
    locked_wt = _mk(fx, locked_branch, name="locked")
    fx.lock(locked_branch)
    fx.set_state(rows=[_merged_row(base_branch, number=11), _merged_row(locked_branch, number=12),
                       _open_row("fix/child", number=13, base=base_branch)])

    proc = fx.run("reap-merged", "--apply")

    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert str(base_wt) in _worktree_paths(fx.repo), "是 open PR 的 base（stacked）却删了"
    assert str(locked_wt) in _worktree_paths(fx.repo), "有活跃会话锁（可能正在用）却删了"
    assert base_branch in _branches(fx.repo) and locked_branch in _branches(fx.repo)
    assert "是 open PR 的 base" in proc.stdout, f"必须点明 stacked 原因：\n{proc.stdout}"
    assert "活跃会话锁" in proc.stdout, f"必须点明锁原因：\n{proc.stdout}"


def test_reap_merged_except_and_radius_guards(fx: Fixture):
    """`--except`（add 路径排除本次目标）与「半径外的 worktree」都不得被删；同轮该收的照收。"""
    keep_wt = _mk(fx, "fix/keep", name="keep")
    outside_wt = _mk(fx, "fix/outside", name="checkout", base=fx.outside)
    reap_wt = _mk(fx, REAP_BRANCH)
    fx.set_state(rows=[_merged_row("fix/keep", number=21), _merged_row("fix/outside", number=22),
                       _merged_row(REAP_BRANCH, number=23)])

    proc = fx.run("reap-merged", "--apply", "--except", "fix/keep")

    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert str(keep_wt) in _worktree_paths(fx.repo), "--except 的分支不许删（add 路径排除本次目标）"
    assert str(outside_wt) in _worktree_paths(fx.repo), "工作区根之外的检出不许删（半径外）"
    assert str(reap_wt) not in _worktree_paths(fx.repo), "同一轮里该收的仍要收（证明判据真跑了）"
    assert "半径外" in proc.stdout, f"必须点明半径外原因：\n{proc.stdout}"
    assert "本次调用的目标分支" in proc.stdout, f"必须点明 --except 原因：\n{proc.stdout}"


# ── ⑦ 活锚硬保护（判据 4-③）+ 负控 ──────────────────────────────────────────

def test_reap_merged_anchor_target_is_hard_protected(fx: Fixture):
    """活锚目标进清理半径 ⇒ 拒删 + 报警（#3956 形态：误删 ⇒ DSH 静默加载不到研发模式）。"""
    wt = _mk(fx, REAP_BRANCH)
    fx.anchor_link(wt)
    fx.set_state(rows=[_merged_row(REAP_BRANCH)])

    proc = fx.run("reap-merged", "--apply")

    out = proc.stdout + proc.stderr
    assert proc.returncode == 2, f"活锚保护命中必须报警（exit 2）：exit={proc.returncode}\n{out}"
    assert "活锚保护" in out, f"必须点明是活锚保护：\n{out}"
    assert str(wt) in _worktree_paths(fx.repo), "活锚目标被删了（DSH 会静默加载不到研发模式）"
    assert REAP_BRANCH in _branches(fx.repo), "活锚目标的本地分支被删了"


def test_reap_merged_anchor_protection_is_negative_controlled(fx: Fixture):
    """负控：同一命令、同一形态、**没有活锚指向它**时确实会删 —— 证明上一条不是恒绿。"""
    wt = _mk(fx, REAP_BRANCH)
    fx.set_state(rows=[_merged_row(REAP_BRANCH)])

    proc = fx.run("reap-merged", "--apply")

    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert str(wt) not in _worktree_paths(fx.repo), "负控失败：无活锚指向时应正常收掉"


# ── ③/⑥ 其余安全出口：dry-run、gh 缺失 ─────────────────────────────────────

def test_reap_merged_defaults_to_dry_run(fx: Fixture):
    """默认 dry-run ⇒ 零删除；`--apply` 才删。"""
    wt = _mk(fx, REAP_BRANCH)
    fx.set_state(rows=[_merged_row(REAP_BRANCH)])

    dry = fx.run("reap-merged")

    assert dry.returncode == 0, f"{dry.stdout}\n{dry.stderr}"
    assert "dry-run" in dry.stdout, f"默认必须自报 dry-run：\n{dry.stdout}"
    assert str(wt) in _worktree_paths(fx.repo), "dry-run 竟然删了 worktree"
    assert REAP_BRANCH in _branches(fx.repo), "dry-run 竟然删了本地分支"

    applied = fx.run("reap-merged", "--apply")
    assert applied.returncode == 0, f"{applied.stdout}\n{applied.stderr}"
    assert str(wt) not in _worktree_paths(fx.repo), "--apply 未清 worktree"


def test_reap_merged_gh_unavailable_is_three(fx: Fixture):
    """取不到 gh ⇒ exit 3（无法判定 ≠ 0），且零删除。"""
    wt = _mk(fx, REAP_BRANCH)
    fx.set_state(rows=[_merged_row(REAP_BRANCH)])

    proc = fx.run("reap-merged", "--apply", extra_env={"MIGAO_GH_BIN": "/nonexistent/gh"})

    assert proc.returncode == 3, f"gh 缺失必须 exit=3：exit={proc.returncode}\n{proc.stdout}"
    assert str(wt) in _worktree_paths(fx.repo), "无法判定却删了 worktree"
    assert REAP_BRANCH in _branches(fx.repo), "无法判定却删了本地分支"


def test_reap_merged_no_artifacts_protects_shared_write_surface(fx: Fixture):
    """`--no-artifacts`（`add` 自动收尾用的口径）不动主工作区根 —— 那是**跨会话共享写面**。

    别人的 `pr-body-*.md` 可能正躺在主工作区根用着；默认口径（无该 flag）与 `finish`/`prune` 一致，仍清。
    """
    _mk(fx, REAP_BRANCH)
    fx.set_state(rows=[_merged_row(REAP_BRANCH)])
    body = fx.repo / "pr-body-5422.md"
    body.write_text("别人的 PR body 正在用\n", encoding="utf-8")

    proc = fx.run("reap-merged", "--apply", "--no-artifacts")

    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert body.exists(), "--no-artifacts 竟然删了别人的 pr-body（跨会话共享写面）"
    assert "跳过过程产物清理" in proc.stdout, f"跳过必须出声：\n{proc.stdout}"

    other = fx.repo / "pr-body-5423.md"
    other.write_text("另一份\n", encoding="utf-8")
    fx.set_state(rows=[_merged_row("fix/second", number=31)])
    _mk(fx, "fix/second", name="second")
    plain = fx.run("reap-merged", "--apply")
    assert plain.returncode == 0, f"{plain.stdout}\n{plain.stderr}"
    assert not other.exists(), "默认口径应与 finish/prune 一致（清主工作区根的过程产物）"


# ── ⑧ 接线：dev-worktree.sh add 的那一行 ────────────────────────────────────

def test_dev_worktree_add_wires_auto_reap():
    """判据对象 = `cmd_add()` 的**函数体**（不是全文 grep）。"""
    body = _cmd_add_body(DEV_WORKTREE.read_text(encoding="utf-8"))
    assert _wiring_problems(body) == [], f"接线缺失：{_wiring_problems(body)}"


def test_wiring_criterion_is_red_when_call_line_is_removed():
    """**红证**：删掉那一行接线 ⇒ 同一条判据必红。"""
    src = DEV_WORKTREE.read_text(encoding="utf-8")
    assert src.count(REAP_CALL_LINE) == 1, f"注入锚点必须**恰好命中 1 次**（源码漂移 ⇒ 红证会失效）"
    mutated = src.replace(REAP_CALL_LINE + "\n", "")
    assert mutated != src, "变异没落到源码上"

    assert _wiring_problems(_cmd_add_body(src)) == [], "基线（真源码）必须绿"
    red = _wiring_problems(_cmd_add_body(mutated))
    assert red, "删掉接线后判据必须红（否则本条是空断言）"
    assert any("没有调用" in p for p in red), f"红的必须是「未接线」这件事：{red}"


def test_dev_worktree_add_actually_reaps_a_merged_worktree(tmp_path: Path):
    """**行为级**接线判据：真 `dev-worktree.sh add` 跑一遍 ⇒ 已合并的被真收掉、新工作区照建。

    为什么结构断言不够：它只证明「那一行还在」，证不了「调用真的成功」—— 例如 `reap-merged` 的
    flag 一旦改名，`add` 只会打一行警告继续跑（**失败不阻塞**是设计），结构断言照样绿。
    """
    fx = Fixture(tmp_path)
    (fx.repo / ".agent-presets" / "migao").mkdir(parents=True, exist_ok=True)
    (fx.repo / ".agent-presets" / "migao" / "preset.yml").write_text("version: fixture\n", encoding="utf-8")
    _git(fx.repo, "add", ".agent-presets")
    _git(fx.repo, "commit", "-q", "-m", "add presets")
    _git(fx.repo, "push", "-q", "origin", "main")

    scripts = fx.repo / "scripts"
    scripts.mkdir(exist_ok=True)
    for name in ("dev-worktree.sh", "issue-lifecycle.sh"):
        shutil.copy(REPO_ROOT / "scripts" / name, scripts / name)
    shutil.copy(MODULE, scripts / "issue_lifecycle.py")
    shutil.copy(GUARD_MODULE, scripts / "agent-presets-guard.py")

    stale = _mk(fx, REAP_BRANCH)
    fx.set_state(rows=[_merged_row(REAP_BRANCH)])
    assert str(stale) in _worktree_paths(fx.repo), "夹具没造出「已合并但没人收尾」的形态"
    assert REAP_BRANCH in _remote_branches(fx.repo), "夹具没造出远程分支"

    new_branch = "fix/brand-new"
    _git(fx.repo, "branch", new_branch, "main")
    proc = subprocess.run(["bash", str(scripts / "dev-worktree.sh"), "add", new_branch],
                          cwd=str(fx.repo), capture_output=True, text=True, env=fx.env())

    assert proc.returncode == 0, f"add 本身不得被自动收尾影响：\n{proc.stdout}\n{proc.stderr}"
    assert (fx.wt_base / "brand-new").is_dir(), "新工作区没建出来"
    assert str(stale) not in _worktree_paths(fx.repo), "add 没有真收掉「已合并但没人收尾」的 worktree"
    assert REAP_BRANCH not in _branches(fx.repo), "add 没有真收掉本地分支"
    assert REAP_BRANCH not in _remote_branches(fx.repo), "add 没有真收掉远程分支"


# ── 相邻缺陷（本次实测）：finish 的「按路径收尾」曾经 AttributeError ───────────

def test_finish_accepts_a_worktree_path(fx: Fixture):
    """`finish <工作区路径>`（文档承诺的用法）必须可用。

    实测（2026-09-24）：原先 `resolve_target()` 调 `GUARD.wt_branch_of(...)`，而守卫模块
    **没有**这个函数（那是 dev-worktree.sh 的 bash 函数）⇒ 只走「按路径收尾」这条路必抛
    `AttributeError`，且既有单测只覆盖「按分支名收尾」⇒ 判据从未跑到它。
    """
    wt = _mk(fx, "fix/by-path", push=False)
    fx.set_state(rows=[_merged_row("fix/by-path")])

    proc = fx.run("finish", str(wt), "--dry-run")

    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"按路径收尾应可用：exit={proc.returncode}\n{out}"
    assert "AttributeError" not in out, f"不得再抛 AttributeError：\n{out}"
    assert "fix/by-path" in proc.stdout, f"必须解析出该路径所在的分支：\n{proc.stdout}"
    assert str(wt) in _worktree_paths(fx.repo), "dry-run 竟然动了工作区"