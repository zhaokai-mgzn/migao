# case_ids: MC-055, MC-056
"""`deploy-reconcile.yml` 值守面（issue #5929）：**合并了但没上线**必须有人被叫醒。

## 病（现取读数，不是推断）

`deploy-reconcile.yml` 会判定「main HEAD 的代码状态有没有部署」，但**判出「没部署」之后它只做两件事**：
① 补一次 dispatch ② 在 step summary 里写一行 —— **没有人会被叫醒**。
实测（2026-10-01，issue #5929）：`deploy-frontend.yml` 的 push 触发在 10:18 之后再没跑过，
22:41 线上仍停在 `bef78e7`，而 main HEAD 已是 `1fbdfb0`（中间 `871db0c7f` 改了
`frontend/admin-web/**` 却没上线）—— 全仓只有 reconcile 的 `::notice::` 说了一句。

## 🔴 本单必须纠正的一个前提（判据把这件事也钉住）

issue 正文的判据写作「main HEAD 的 `sha-<head7>` 镜像**仍不存在** ⇒ 判红」。**这个判据今天恒为真**：
`#5814` 的 C′ 把构建搬到**服务器侧** ⇒ CI **不再推 ACR**（见 `.github/workflows/deploy-frontend.yml`
的 `Assert server-side build (no ACR push)` 步与 `deploy/scripts/swas-deploy-ci.sh` 的服务器侧
`docker build`）。⇒ 照字面实现 = **每个 tick 都报警**（噪声判据是缺陷，issue 验收判据 2）。
故本值守面的「已部署」由**三条**信号组成（与各部署腿自己的 C′ 判据**同一份**）：
① 镜像存在（保留：将来若恢复推 ACR 自动复活）② **同 sha 的部署 run 结论 = success**（C′ 之后的真判据）
③ **自上次成功部署起该服务的代码路径无改动**（漂移判据 = 该 commit 的代码状态已在线上）。

## 值守面判什么（判据本体只此一份，落在对账步 + 值守步）

**合并进 main 超过 N 秒后**，某条腿在**本轮对账开始时**既没有「已部署」信号、也没有**在途 run**
（queued / in_progress）⇒ **判红**（`::error::` + 非零退出 + step summary）**并自己开/更 P1 值班 issue**；
部署成功后同一逻辑**自动关闭**该 issue（清零不靠人记得）。

| 对账步落的状态 | 含义 | 值守面 |
|---|---|---|
| `deployed` | 镜像在 / 同 sha 结论 success / 无漂移 | ✅ 不报 |
| `inflight` | 同 sha 的 run 还没跑完（queued / in_progress） | ✅ 不报（在途） |
| `terminal` | 断路器：不可恢复终态 ⇒ **不会**再有自动部署 | 🔴 超期即报 |
| `dispatched` | 本轮才补 dispatch（= 对账开始时确实没部署） | 🔴 超期即报 |
| 缺失 / `notarget` | 判不了（状态文件没写出来 / 目标 workflow 不在 main 上） | 🔴 **fail-closed**（退出码 3） |

## N 的出处（现取复算，不写死别人的数字）

`N = 2700s`（45min）≥ 冷构建实测上界 **1782s**（29.7min，出处 = `.github/workflows/deploy-frontend.yml`
的 `timeout-minutes` 注释「冷构建实测 1782s」）+ 部署/探测余量 **600s**（出处 =
`deploy/scripts/swas-deploy-ci.sh` 的「3000s（= 构建上界 2400s + 部署余量 600s）」）= **2382s**（39.7min）。
判据**从这两个文件现取**这两个读数并断言 `N ≥ 1782 + 600`（把 N 改小 / 删掉那两个读数锚 ⇒ 红）。

## 本文件锁什么

1. **接线在**：值守面是 `deploy-reconcile.yml` 的一个 step（不是一句注释），且它**消费**对账步落下的
   每一类状态（登记 `wiring_claims_ledger.json` 的那条接线声明；⚠️ 本包**有意不写那个声明常量** ——
   YAML 接线锚不在该台账射程内，逐字理由见文件头「本文件锁什么」下方的说明）—— 「判据本体绿 ≠ 接线在」。
2. **执行式行为判据**：真跑两个 step 的 `run:` 正文（桩 `gh` / `docker` + 真 git 仓库），断言各场景的
   **动作与退出码**（下面逐个测试）。
3. **类级元守卫**：`reconcile_one` 的**每一条腿**都必须在 `deploy_watchdog_ledger.json` 里登记
   （`watched` 或**具名豁免**）—— 新加一条 deploy 腿却忘了接值守 ⇒ **未登记即红**；豁免只许缩短。
4. **无新增 schedule**：本腿沿用既有 `*/20` 与既有事件，`on.schedule` 必须仍是那一条。

⚠️ 桩化的诚实标注：`gh` / `docker` 是**桩**（记录调用、读预设 JSON），故本文件证明的是
「workflow 在给定输入下**会**做什么」，不是「GitHub 真的会开单」；后者只有真跑 CI 才能验证
（PR body 里如实标注）。本文件不联网、不碰真实 ACR、不写共享 `/tmp`（一切产物落 pytest `tmp_path`）。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-reconcile.yml"
LEDGER = Path(__file__).resolve().parent / "deploy_watchdog_ledger.json"
SWAS_DEPLOY_CI = REPO_ROOT / "deploy" / "scripts" / "swas-deploy-ci.sh"
FRONTEND_DEPLOY_WF = REPO_ROOT / ".github" / "workflows" / "deploy-frontend.yml"

RECONCILE_STEP = "Reconcile deploys"
WATCHDOG_STEP = "值守面（超时未部署 ⇒ 判红 + 开/清值守 issue）"
LIVENESS_STEP = "存活读数（本轮做了什么 / 为什么零动作）"

# ⚠️ 本文件**有意不写接线声明常量**（不是漏）：那条规范（§28.2 / 台账
# `tests/unit_ci_workflows/wiring_claims_ledger.json`）的判据 3 要求接线锚左端以 `.py` 结尾，
# 而本包的接线点在 **workflow YAML** 里（台账 `coverage_boundary` 逐字登记：「`.py` 之外的语言
# （本仓接线面在 Python）」不在射程）。⇒ 本包的接线面由**执行式判据**承担（下面真跑两个 step 的
# `run:` 正文 + 断言动作），它比「锚在不在」更强，但**是作者的一次动作、不是常驻机制** ——
# 该边界已如实写进 PR body 的「未固化项」。（写声明常量反而会被判「未登记即红」。）

ACR_REGISTRY = "acr.example.com"
ACR_NAMESPACE = "ns"

# 与 CI 的 shell 同形（`bash --noprofile --norc -e -o pipefail`）
BASH_SHELL = ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail"]

# 与 `reconcile_one` 的登记册一致（真值源 = workflow 文本；台账与之双向核对）
DEPLOY_WF = {
    "admin-api": "deploy-admin-api.yml",
    "ai-agent-service": "deploy-ai-agent-service.yml",
    "admin-web": "deploy-frontend.yml",
    "worker-h5": "worker-h5-publish.yml",
    "bmini-h5-hosting": "bmini-h5-publish.yml",
    "c-end-h5": "c-end-h5-publish.yml",
}

RECONCILE_CALL = re.compile(r"^\s*reconcile_one\s+(\S+)\s+(\S+)\s+", re.M)

# ── 桩：`gh`（run list / workflow view|run / issue list|view|create|comment|edit|close）──
# ⚠️ 必须**真的实现用到的 `--jq` 表达式**（真 `gh` 会先过 jq 再输出；桩若原样吐 JSON，
#    被测脚本的 `[ -n "$EXIST" ]` 会拿到整段 JSON ⇒ 那是**桩的缺陷**、不是 workflow 的缺陷）。
GH_STUB = r'''#!/usr/bin/env python3
import json, os, sys

args = sys.argv[1:]


def env(k, d=""):
    return os.environ.get(k, d)


with open(env("STUB_CALL_LOG", os.devnull), "a", encoding="utf-8") as fh:
    fh.write(" ".join(args) + "\n")


def jq(args):
    for i, a in enumerate(args):
        if a == "--jq":
            return args[i + 1]
        if a.startswith("--jq="):
            return a[len("--jq="):]
    return ""


def load_issues():
    p = env("STUB_ISSUES")
    return json.load(open(p, encoding="utf-8")) if p and os.path.exists(p) else []


def save_issues(items):
    json.dump(items, open(env("STUB_ISSUES"), "w", encoding="utf-8"), ensure_ascii=False)


if args[:2] == ["run", "list"]:
    wf = ""
    for i, a in enumerate(args):
        if a == "--workflow":
            wf = args[i + 1]
    path = os.path.join(env("STUB_RUNS_DIR"), wf)
    runs = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else []
    sys.stdout.write(json.dumps(runs))
    sys.exit(0)

if args[:2] == ["workflow", "view"]:
    absent = {w.strip() for w in env("STUB_WORKFLOW_ABSENT").split(",") if w.strip()}
    sys.exit(1 if (args[2] if len(args) > 2 else "") in absent else 0)

if args[:2] == ["workflow", "run"]:
    sys.exit(0)

if args[:2] == ["issue", "list"]:
    items = [i for i in load_issues() if i.get("state") == "open"]
    expr = jq(args)
    if "number" in expr:                      # `.[0].number // empty`
        sys.stdout.write(str(items[0]["number"]) if items else "")
    else:
        sys.stdout.write(json.dumps(items))
    sys.exit(0)

if args[:2] == ["issue", "view"]:
    num = int(args[2])
    for i in load_issues():
        if i["number"] == num:
            expr = jq(args)
            sys.stdout.write(i.get("body", "") if "body" in expr else json.dumps(i))
            sys.exit(0)
    sys.exit(1)

if args[:2] == ["issue", "create"]:
    items = load_issues()
    title = body = ""
    labels = []
    for i, a in enumerate(args):
        if a == "--title":
            title = args[i + 1]
        if a == "--body-file":
            body = open(args[i + 1], encoding="utf-8").read()
        if a == "--label":
            labels.append(args[i + 1])
    num = max([i["number"] for i in items] or [0]) + 1
    items.append({"number": num, "state": "open", "title": title, "body": body,
                  "labels": labels, "comments": []})
    save_issues(items)
    sys.stdout.write("https://example.invalid/issues/%d\n" % num)
    sys.exit(0)

if args[:2] == ["issue", "comment"]:
    num = int(args[2])
    body = ""
    for i, a in enumerate(args):
        if a == "--body-file":
            body = open(args[i + 1], encoding="utf-8").read()
        if a == "--body":
            body = args[i + 1]
    items = load_issues()
    for it in items:
        if it["number"] == num:
            it.setdefault("comments", []).append(body)
    save_issues(items)
    sys.exit(0)

if args[:2] == ["issue", "close"]:
    num = int(args[2])
    items = load_issues()
    for it in items:
        if it["number"] == num:
            it["state"] = "closed"
    save_issues(items)
    sys.exit(0)

if args[:2] == ["issue", "edit"]:
    num = int(args[2])
    items = load_issues()
    for it in items:
        if it["number"] == num:
            for i, a in enumerate(args):
                if a == "--add-label":
                    it.setdefault("labels", []).append(args[i + 1])
    save_issues(items)
    sys.exit(0)

sys.exit(3)
'''

DOCKER_STUB = r'''#!/usr/bin/env python3
import os, sys

args = sys.argv[1:]
if args[:2] == ["manifest", "inspect"]:
    existing = {t for t in os.environ.get("STUB_IMAGE_TAGS", "").split(",") if t}
    sys.exit(0 if args[2] in existing else 1)
sys.exit(3)
'''


# ══════════════════════════════════════════════════════════════════════════
# 基础设施
# ══════════════════════════════════════════════════════════════════════════

def _doc() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _steps() -> list:
    return _doc()["jobs"]["reconcile"]["steps"]


def step_body(name: str) -> str:
    """抽出某个 step 的 `run:` 正文，并把 `${{ env.X }}` 换成字面量（与执行式红证同一份读法）。"""
    body = None
    for s in _steps():
        if s.get("name") == name:
            body = s.get("run", "") or ""
            break
    assert body, f"反空跑锚点：`{WORKFLOW.name}` 里找不到 step `{name}` 的 run 正文"
    for key, value in (("ACR_REGISTRY", ACR_REGISTRY), ("ACR_NAMESPACE", ACR_NAMESPACE)):
        body = body.replace("${{ env.%s }}" % key, value)
    assert "${{" not in body, f"`{name}` 里还有没替换掉的 GitHub 表达式（判据已过期）"
    return body


def step_env(name: str) -> dict:
    for s in _steps():
        if s.get("name") == name:
            return s.get("env") or {}
    pytest.fail(f"找不到 step `{name}`")


def git(repo: Path, *args: str, env: dict | None = None) -> str:
    full = os.environ.copy()
    full.update(env or {})
    out = subprocess.run(
        ["git", "-c", "user.email=ci@example.com", "-c", "user.name=ci",
         "-c", "commit.gpgsign=false", *args],
        cwd=repo, capture_output=True, text=True, check=True, env=full,
    )
    return out.stdout.strip()


def make_stubs(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name, content in (("gh", GH_STUB), ("docker", DOCKER_STUB)):
        p = bin_dir / name
        p.write_text(content, encoding="utf-8")
        p.chmod(0o755)
    return bin_dir


def make_repo(tmp_path: Path, *, head_age_secs: int, drift: bool) -> dict:
    """真 git 仓库：`C1`（六条腿的代码路径都在）→（可选）`C2` 改 admin-web 源码 = HEAD。

    HEAD 的**提交时间**被钉成 `now - head_age_secs` ⇒ 「合并后 N 分钟」这条判据有可控输入。
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    # 可移植（macOS 的 `date` 没有 `-d`）：用标准库算「N 秒前」的时间戳
    stamp = (datetime.now(timezone.utc) - timedelta(seconds=head_age_secs)).strftime("%Y-%m-%dT%H:%M:%SZ")
    date_env = {"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}

    def touch(rel: str) -> None:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(rel, encoding="utf-8")

    for rel in ("backend/admin-api/a.py", "backend/ai-agent-service/a.py", "frontend/admin-web/a.ts",
                "frontend/worker-h5/a.mjs", "frontend/bmini-app/a.ts", "frontend/mini-app/a.ts"):
        touch(rel)
    # 六条腿的 workflow **真的**放进测试仓库（issue #5935）：对账步的前置判据问的是
    # 「main HEAD 这棵树里有没有这个 workflow」（`git cat-file -e HEAD:<path>`，见
    # scripts/deploy_reconcile_state.sh 的 `on_main`）。不放 ⇒ 六条腿全判「不在 main 上」，
    # 后面所有场景都跑不到判定本体（**假绿**：断言全过而那一段根本没执行）。
    touch(".github/workflows/.keep")
    for wf in sorted(set(DEPLOY_WF.values())):
        touch(f".github/workflows/{wf}")
    # 外置的状态机脚本（issue #5935）必须与 workflow 同批进测试仓库（= 真实检出的形态：
    # 对账步 `source scripts/deploy_reconcile_state.sh`）。⚠️ 只拷**这一份**（单文件），
    # **不**去枚举 `scripts/**` 语料 —— 枚举语料就要按 issue #5284 的元守卫声明并冻结射程，
    # 而本模块要的只是「这一份文件在场」，不为语料面背书。
    (repo / "scripts").mkdir(exist_ok=True)
    for sh in [STATE_SCRIPT]:
        (repo / "scripts" / sh.name).write_text(sh.read_text(encoding="utf-8"), encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "code C1", env=date_env)
    c1 = git(repo, "rev-parse", "HEAD")
    head = c1
    if drift:
        touch("frontend/admin-web/b.ts")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "code C2（admin-web 改动；部署触发被吞）", env=date_env)
        head = git(repo, "rev-parse", "HEAD")
    return {"repo": repo, "C1": c1, "head": head, "head7": head[:7]}


def runs(sha: str, conclusion: str, status: str = "completed") -> list:
    return [{"headSha": sha, "conclusion": conclusion, "status": status}]


def write_runs(runs_dir: Path, per_wf: dict) -> None:
    """`per_wf` 的键必须是 **workflow 文件名**（`DEPLOY_WF.values()`）—— 服务名是另一套键，
    写错时 `gh run list` 会读到空列表 ⇒ 判据看到的是「没有部署记录」而不是它声称的场景。"""

    runs_dir.mkdir(exist_ok=True)
    for wf in DEPLOY_WF.values():
        (runs_dir / wf).write_text(json.dumps(per_wf.get(wf, [])), encoding="utf-8")


class Exec:
    """一次两段式执行（对账步 → 值守步）的结果。"""

    def __init__(self, tmp_path: Path, fx: dict, per_wf: dict, *,
                 image_tags: str = "", state: str | None = None,
                 event: str = "schedule"):
        self.tmp = tmp_path
        self.fx = fx
        self.bin_dir = make_stubs(tmp_path)
        self.runs_dir = tmp_path / "runs"
        write_runs(self.runs_dir, per_wf)
        self.calls = tmp_path / "gh-calls.log"
        self.issues_file = tmp_path / "issues.json"
        self.summary = tmp_path / "summary.md"
        self.state = state if state is not None else str(tmp_path / "watchdog-state.tsv")
        self.env = os.environ.copy()
        self.env.update({
            "PATH": f"{self.bin_dir}{os.pathsep}{self.env['PATH']}",
            "STUB_RUNS_DIR": str(self.runs_dir),
            "STUB_CALL_LOG": str(self.calls),
            "STUB_ISSUES": str(self.issues_file),
            "STUB_IMAGE_TAGS": image_tags,
            "STUB_WORKFLOW_ABSENT": "",
            "GITHUB_STEP_SUMMARY": str(self.summary),
            "GITHUB_EVENT_NAME": event,
            "GITHUB_REPOSITORY": "zhaokai-mgzn/migao",
            "GH_TOKEN": "stub-token",
            "WATCHDOG_STATE": self.state,
        })

    def _run(self, name: str, *, body: str | None = None) -> subprocess.CompletedProcess:
        safe = re.sub(r"[^0-9A-Za-z_.-]", "_", name)     # 步骤名含 `/` 与 `⇒` ⇒ 不能直接当文件名
        script = self.tmp / f"{safe}.sh"
        script.write_text(step_body(name) if body is None else body, encoding="utf-8")
        return subprocess.run(BASH_SHELL + [str(script)], cwd=self.fx["repo"], env=self.env,
                              capture_output=True, text=True)

    def reconcile(self) -> subprocess.CompletedProcess:
        return self._run(RECONCILE_STEP)

    def watchdog(self, *, body: str | None = None) -> subprocess.CompletedProcess:
        return self._run(WATCHDOG_STEP, body=body)

    def reconcile_with_body(self, body: str) -> subprocess.CompletedProcess:
        """跑**变异版**对账正文（红证用；`watchdog(body=...)` 只覆盖值守步）。"""
        return self._run(RECONCILE_STEP, body=body)

    # ── 读数 ──
    @property
    def gh_calls(self) -> list:
        return self.calls.read_text(encoding="utf-8").splitlines() if self.calls.exists() else []

    @property
    def issues(self) -> list:
        return json.loads(self.issues_file.read_text(encoding="utf-8")) if self.issues_file.exists() else []

    @property
    def summary_text(self) -> str:
        return self.summary.read_text(encoding="utf-8") if self.summary.exists() else ""

    def seed_open_issue(self, body: str, *, number: int = 7) -> None:
        self.issues_file.write_text(json.dumps([{
            "number": number, "state": "open", "title": "seed", "body": body,
            "labels": ["priority/P1"], "comments": [],
        }], ensure_ascii=False), encoding="utf-8")


def two_step(tmp_path: Path, *, head_age_secs: int, drift: bool, per_wf: dict,
             image_tags: str = "", **kw) -> Exec:
    fx = make_repo(tmp_path, head_age_secs=head_age_secs, drift=drift)
    ex = Exec(tmp_path, fx, per_wf, image_tags=image_tags, **kw)
    rc = ex.reconcile()
    assert rc.returncode == 0, f"对账步非零退出（前置条件不成立）→ {rc.stderr}\n{rc.stdout}"
    return ex


TERMINAL_RUNS = lambda sha: {wf: runs(sha, "failure") for wf in DEPLOY_WF.values()}      # noqa: E731
INFLIGHT_RUNS = lambda sha: {wf: runs(sha, "", "in_progress") for wf in DEPLOY_WF.values()}  # noqa: E731
NO_RUNS = {}                                                                            # noqa: E731


# ══════════════════════════════════════════════════════════════════════════
# 一、静态面：接线在不在 / 台账是否双向登记 / N 的出处 / 无新增 schedule
# ══════════════════════════════════════════════════════════════════════════

def test_watchdog_step_is_wired_between_reconcile_and_liveness():
    """值守面必须**真的接在流程上**：位于对账步之后、存活读数步（必须是最后一步）之前。"""
    names = [s.get("name") for s in _steps()]
    assert RECONCILE_STEP in names and WATCHDOG_STEP in names, f"步骤名缺失 → {names}"
    assert names.index(RECONCILE_STEP) < names.index(WATCHDOG_STEP) < names.index(LIVENESS_STEP), (
        f"值守面必须夹在对账步与存活读数步之间（现状 {names}）"
    )
    assert names[-1] == LIVENESS_STEP, "存活读数步仍必须是最后一步（#5326）"
    step = next(s for s in _steps() if s.get("name") == WATCHDOG_STEP)
    assert step.get("if") == "always()", (
        "值守面必须 `if: always()`：对账步失败时**更要**判定（fail-closed），"
        f"否则「判定不可用」会被静默吞掉（现状 if={step.get('if')!r}）"
    )
    body = step_body(WATCHDOG_STEP)
    for token in ("gh issue create", "gh issue close", "exit ", "::error::"):
        assert token in body, f"值守面正文缺 `{token}`（开单 / 清零 / 判红三件必须齐全）"


def test_ledger_matches_workflow_legs_and_watchdog_lists():
    """**类级元守卫（未登记即红）**：对账腿 ⇄ 台账 ⇄ 值守面两个列表，三处必须逐项相等。"""
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    text = WORKFLOW.read_text(encoding="utf-8")
    legs = {m.group(1): m.group(2) for m in RECONCILE_CALL.finditer(text)}
    assert legs, "反空跑锚点：没解析到 `reconcile_one` 调用（判据已过期）"

    watched = re.search(r'^\s*WATCHED_LEGS="([^"]*)"', step_body(WATCHDOG_STEP), re.M)
    exempt = re.search(r'^\s*EXEMPT_LEGS="([^"]*)"', step_body(WATCHDOG_STEP), re.M)
    assert watched and exempt, "值守面里找不到 `WATCHED_LEGS` / `EXEMPT_LEGS` 声明（判据已过期）"
    w_set = set(watched.group(1).split())
    e_set = set(exempt.group(1).split())

    in_workflow = set(w_set) | set(e_set)
    assert in_workflow == set(legs), (
        f"值守面覆盖的腿与对账腿不一致：只在对账面 {sorted(set(legs) - in_workflow)} / "
        f"只在值守面 {sorted(in_workflow - set(legs))}"
    )
    assert not (w_set & e_set), f"同一条腿不能既受值守又是豁免：{sorted(w_set & e_set)}"

    entries = {e["svc"]: e for e in ledger["entries"]}
    assert set(entries) == set(legs), (
        f"台账与对账腿不一致（**新加 deploy 腿却忘了接值守 ⇒ 这里当场红**）："
        f"缺登记 {sorted(set(legs) - set(entries))} / 多余 {sorted(set(entries) - set(legs))}"
    )
    for svc, e in entries.items():
        assert e["wf"] == legs[svc], f"{svc}: 台账 workflow 与 `reconcile_one` 不一致（{e['wf']} vs {legs[svc]}）"
        expected = "watchdog" if e.get("watchdog") else "exempt"
        actual = "watchdog" if svc in w_set else "exempt"
        assert expected == actual, f"{svc}: 台账标 `{expected}`，值守面里却是 `{actual}` ⇒ 两处必须同源"


def test_exempt_entries_are_named_justified_and_only_shrink():
    """豁免必须**具名 + 有理由 + 有仓内锚**，且条数只许缩短（现取）。"""
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    text = WORKFLOW.read_text(encoding="utf-8")
    exempt = [e for e in ledger["entries"] if not e.get("watchdog")]
    assert len(exempt) <= ledger["frozen_max_exempt"], (
        f"豁免条数从冻结上限 {ledger['frozen_max_exempt']} 涨到 {len(exempt)} —— "
        "只许缩短（要新增豁免必须先改这个数并在 PR 里论证）"
    )
    for e in exempt:
        assert e.get("exempt_why"), f"{e['svc']}: 豁免必须写理由（`exempt_why`）"
        assert e.get("anchor"), f"{e['svc']}: 豁免必须给仓内锚（`anchor`），否则它就是一句无法核验的话"
        assert e["anchor"] in text, (
            f"{e['svc']}: 豁免锚 {e['anchor']!r} 在 `{WORKFLOW.name}` 里找不到 ⇒ 豁免依据已被删/改名"
        )
    for e in ledger["entries"]:
        assert e.get("why") or e.get("exempt_why"), f"{e['svc']}: 无论值守还是豁免都要写理由（`why` / `exempt_why`）"


def test_grace_seconds_is_recomputed_from_repo_readings():
    """N 不许是凭空数字：必须 ≥ 冷构建上界 + 部署余量（两个读数**现取**自各自的真值源）。"""
    driver = SWAS_DEPLOY_CI.read_text(encoding="utf-8")
    cold = re.search(r"冷构建上界 (\d+)s", driver)
    margin = re.search(r"余量 (\d+)s", driver)
    lock_wait = re.search(r"远端锁等待上限 (\d+)s", driver)
    assert cold and margin and lock_wait, (
        "反空跑锚点：`deploy/scripts/swas-deploy-ci.sh` 里那句部署预算"
        "（远端锁等待上限 / 冷构建上界 / 余量）的读数锚不见了（判据已过期）"
    )
    cold_secs, margin_secs = int(cold.group(1)), int(margin.group(1))

    env = step_env(WATCHDOG_STEP)
    assert env.get("WATCHDOG_GRACE_SECONDS"), "值守面必须把 N 摆在 step env 里（可现取、可复算）"
    n = int(env["WATCHDOG_GRACE_SECONDS"])
    assert n >= cold_secs + margin_secs, (
        f"N={n}s < 冷构建上界 {cold_secs}s + 部署余量 {margin_secs}s = {cold_secs + margin_secs}s "
        "⇒ 正常冷构建还没跑完就可能报警（噪声判据）"
    )
    body = step_body(WATCHDOG_STEP)
    for anchor in (str(cold_secs), str(margin_secs), str(cold_secs + margin_secs), str(lock_wait.group(1))):
        assert anchor in body, (
            f"值守面正文里必须写明 N 的出处（缺读数 `{anchor}`）—— 复算命令："
            "`grep -n '冷构建上界' deploy/scripts/swas-deploy-ci.sh`"
        )
    assert "远端锁等待" in body, (
        "必须写明 **有意不计入** 远端锁等待上限的理由（排队中的 run 由 `inflight` 判据覆盖），"
        "否则读者会以为 N 是随手取的"
    )


def test_no_new_schedule_was_added():
    """铁律 10：**不新增 `schedule`**（沿用既有 `*/20` 对账）。

    ⚠️ 触发面**允许**的增量只有一条：`workflow_run`（判据 4，issue #5935 —— 用户 2026-10-02 逐字裁定
    「允许加 workflow_run：部署跑完就对账/清零」）。其余任何新增/改动一律红 —— 本条**只是**把
    那条已获批的增量登记进来，**不是**把「触发面随便改」放宽。"""
    on = _doc()[True] if True in _doc() else _doc().get("on")
    assert on["schedule"] == [{"cron": "*/20 * * * *"}], f"schedule 被改动了 → {on.get('schedule')!r}"
    assert set(on) == {"pull_request", "schedule", "workflow_dispatch", "workflow_run"}, (
        f"触发面被改动了（允许的集合 = 既有三条 + 已获批的 `workflow_run`）→ {sorted(on)}"
    )


# ══════════════════════════════════════════════════════════════════════════
# 二、执行式行为判据（真跑两步正文 + 桩 gh/docker）
# ══════════════════════════════════════════════════════════════════════════

def _assert_red_with_issue(ex: Exec, rc: subprocess.CompletedProcess) -> dict:
    assert rc.returncode != 0, f"超期未部署必须判红（现状 rc={rc.returncode}）→\n{rc.stdout}\n{rc.stderr}"
    blob = rc.stdout + rc.stderr + ex.summary_text
    assert ex.fx["head7"] in blob, f"判红必须**具名**报到 main HEAD（{ex.fx['head7']}）→\n{blob}"
    assert "admin-web" in blob, f"判红必须点名是**哪条腿**没上线 →\n{blob}"
    assert "::error::" in rc.stdout + rc.stderr, "判红必须给 ::error:: 注解（红而不留痕 = #3834 的形态）"
    created = [i for i in ex.issues if i["state"] == "open"]
    assert created, f"判红必须**自己开单**（issue 列表为空）→ calls={ex.gh_calls}"
    assert "priority/P1" in created[0]["labels"], f"值班单必须带 priority/P1 → {created[0]}"
    assert ex.fx["head7"] in created[0]["body"], "值班单正文必须含 main HEAD（可归因）"
    return created[0]


def test_overdue_undeployed_is_red_and_named(tmp_path):
    """**验收判据 1（注入式红证）**：**造假一个仓库里不存在的 sha**（该 commit 既没有镜像、
    也没有任何同 sha 的部署 run）+ 合并已超 N ⇒ 判据必须**红且具名**，并自己开单。"""
    fx = make_repo(tmp_path, head_age_secs=2700 + 600, drift=True)
    ghost = "deadbee" + "f" * 33           # 不存在的 sha：镜像 / run 历史里都没有它的痕迹
    assert ghost != fx["head"], "注入自证：ghost 必须不是真 HEAD"
    ex = Exec(tmp_path, fx, {wf: runs(ghost, "success") for wf in DEPLOY_WF.values()})
    assert ex.reconcile().returncode == 0
    _assert_red_with_issue(ex, ex.watchdog())


def test_breaker_terminal_state_is_red(tmp_path):
    """断路器把它挡住了（不可恢复终态 ⇒ **不会**再有自动补部署）⇒ 必须有人被叫醒
    —— 这正是「只有一行 `::notice::`」的那个洞（issue #5929 的现场形态）。"""
    fx = make_repo(tmp_path, head_age_secs=2700 + 600, drift=True)
    ex = Exec(tmp_path, fx, {wf: runs(fx["head"], "failure") for wf in DEPLOY_WF.values()})
    assert ex.reconcile().returncode == 0
    assert "断路器跳过=6" in ex.summary_text, f"前置条件：断路器必须跳闸 → {ex.summary_text}"
    _assert_red_with_issue(ex, ex.watchdog())


def test_image_present_is_not_red(tmp_path):
    """**判据 2（反向对照）**：镜像存在 ⇒ 该 commit 已构建过 ⇒ **不得**报警、**不得**开单。"""
    tags = ",".join(f"{ACR_REGISTRY}/{ACR_NAMESPACE}/{svc}:sha-HEAD" for svc in DEPLOY_WF)
    fx = make_repo(tmp_path, head_age_secs=2700 + 600, drift=True)
    tags = ",".join(f"{ACR_REGISTRY}/{ACR_NAMESPACE}/{svc}:sha-{fx['head7']}" for svc in DEPLOY_WF)
    ex = Exec(tmp_path, fx, TERMINAL_RUNS("x"), image_tags=tags)
    rc = ex.reconcile()
    assert rc.returncode == 0, f"对账步非零退出 → {rc.stderr}"
    wd = ex.watchdog()
    assert wd.returncode == 0, f"镜像已存在时**不得**报警（噪声判据是缺陷）→\n{wd.stdout}\n{wd.stderr}"
    assert not ex.issues, f"不报警时不得开任何单 → {ex.issues}"
    assert not [c for c in ex.gh_calls if c.startswith("issue create")], f"不得调用 create → {ex.gh_calls}"


def test_inflight_run_is_not_red(tmp_path):
    """在途（同 sha 的 run 还没跑完）⇒ 部署正在路上 ⇒ 不得报警。"""
    fx = make_repo(tmp_path, head_age_secs=2700 + 600, drift=True)
    ex = Exec(tmp_path, fx, INFLIGHT_RUNS(fx["head"]))
    assert ex.reconcile().returncode == 0
    wd = ex.watchdog()
    assert wd.returncode == 0, f"在途 run 存在时不得报警 →\n{wd.stdout}\n{wd.stderr}"
    assert not ex.issues, f"不得开单 → {ex.issues}"


def test_within_grace_is_not_red(tmp_path):
    """宽限期内（合并后还没到 N）⇒ 不得报警（这正是「N 分钟」这条判据的语义）。"""
    fx = make_repo(tmp_path, head_age_secs=60, drift=True)
    ex = Exec(tmp_path, fx, TERMINAL_RUNS(fx["head"]))
    assert ex.reconcile().returncode == 0
    wd = ex.watchdog()
    assert wd.returncode == 0, f"宽限期内不得报警 →\n{wd.stdout}\n{wd.stderr}"
    assert not ex.issues, f"不得开单 → {ex.issues}"


def test_unjudgeable_state_is_red_fail_closed(tmp_path):
    """**fail-closed**：读不到状态（状态文件缺失 / 判不了）⇒ 判红（退出码 3），**不得**静默 success。"""
    fx = make_repo(tmp_path, head_age_secs=2700 + 600, drift=True)
    ex = Exec(tmp_path, fx, TERMINAL_RUNS(fx["head"]), state=str(tmp_path / "nope" / "missing.tsv"))
    wd = ex.watchdog()          # 刻意**不跑**对账步 ⇒ 状态文件不存在
    assert wd.returncode == 3, (
        f"判不了必须是退出码 3（不是 0）—— 「读不到」与「已部署」必须长得不一样 → rc={wd.returncode}"
    )
    assert "机制故障" in wd.stdout + wd.stderr + ex.summary_text, (
        "必须明说这是**机制故障**（判据 3：与「确认未部署」两种东西）"
    )
    assert ex.issues and ex.issues[0]["state"] == "open", "判不了同样要开单（红而不留痕 = #3834 的形态）"


def test_alert_self_clears_after_successful_deploy(tmp_path):
    """**清零判据**：部署成功（镜像在 / 无漂移）⇒ 既有关单**自动关闭**，不依赖人记得。"""
    tags_probe = make_repo(tmp_path, head_age_secs=120, drift=False)
    ex = Exec(tmp_path, tags_probe, {wf: runs(tags_probe["head"], "success") for wf in DEPLOY_WF.values()})
    ex.seed_open_issue(body=f"上一轮判红：main HEAD `{tags_probe['head7']}` 超时未部署")
    assert ex.reconcile().returncode == 0
    wd = ex.watchdog()
    assert wd.returncode == 0, f"已部署 ⇒ 不得报警 →\n{wd.stdout}\n{wd.stderr}"
    assert any(c.startswith("issue close") for c in ex.gh_calls), (
        f"清零必须真的关闭告警单（未调用 `gh issue close`）→ calls={ex.gh_calls}"
    )
    assert ex.issues[0]["state"] == "closed", f"告警单必须被关闭 → {ex.issues[0]}"


def test_repeated_red_tick_does_not_spam_the_same_commit(tmp_path):
    """幂等：同一个 HEAD 反复判红时**不重复刷屏**（20min 一轮的评论风暴本身就是缺陷），
    但**必须**保留可归因的痕迹（issue 仍开着 + 标签在位）。"""
    fx = make_repo(tmp_path, head_age_secs=2700 + 600, drift=True)
    ex = Exec(tmp_path, fx, TERMINAL_RUNS(fx["head"]))
    assert ex.reconcile().returncode == 0
    first = ex.watchdog()
    assert first.returncode != 0 and len(ex.issues) == 1, "第一轮应开一张单"
    n_after_first = len(ex.issues[0].get("comments", []))
    assert ex.reconcile().returncode == 0
    second = ex.watchdog()
    assert second.returncode != 0, "第二轮同样超期 ⇒ 照样判红（红是状态，不是一次性事件）"
    assert len(ex.issues) == 1, f"同一个 HEAD 不得重复开单（去重靠标题检索）→ {ex.issues}"
    assert len(ex.issues[0].get("comments", [])) == n_after_first, (
        f"同一 HEAD 的重复轮次不得重复评论 → {ex.issues[0].get('comments')}"
    )


def test_alarm_surface_is_exactly_the_watched_legs(tmp_path):
    """**可归因 + 豁免腿不进告警面**：六条腿全都「没上线」时，计入告警的必须是**5 条**
    （受值守的腿），豁免的 `c-end-h5`（发布由人手动，用户裁定 B）不计入、也不能让它把噪声带进来。"""
    fx = make_repo(tmp_path, head_age_secs=2700 + 600, drift=True)
    ex = Exec(tmp_path, fx, {wf: runs(fx["head"], "failure") for wf in DEPLOY_WF.values()})
    assert ex.reconcile().returncode == 0
    wd = ex.watchdog()
    blob = wd.stdout + ex.summary_text
    assert "计入告警=5" in blob and "机制故障=0" in blob, f"告警面口径不对 →\n{blob}"
    assert "豁免腿" in blob and "c-end-h5" in blob, "豁免必须有具名说明（不是静默漏掉）"


# ══════════════════════════════════════════════════════════════════════════
# 三、判别力自证（判据本身会红；只改注释不红）
# ══════════════════════════════════════════════════════════════════════════

def test_red_proof_ledger_and_lists_are_discriminating(tmp_path, monkeypatch):
    """六种坏形态在**内存语料**上各自判红（判据不许是恒真式）。"""
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))

    def problems(ledger_obj, body_text):
        text = WORKFLOW.read_text(encoding="utf-8")
        legs = {m.group(1): m.group(2) for m in RECONCILE_CALL.finditer(text)}
        w = set(re.search(r'^\s*WATCHED_LEGS="([^"]*)"', body_text, re.M).group(1).split())
        e = set(re.search(r'^\s*EXEMPT_LEGS="([^"]*)"', body_text, re.M).group(1).split())
        out = []
        if (w | e) != set(legs):
            out.append("coverage-mismatch")
        entries = {x["svc"]: x for x in ledger_obj["entries"]}
        if set(entries) != set(legs):
            out.append("ledger-mismatch")
        for svc, x in entries.items():
            if x.get("watchdog") != (svc in w):
                out.append(f"kind-mismatch:{svc}")
            if not (x.get("why") or x.get("exempt_why")):
                out.append(f"no-why:{svc}")
            if not x.get("watchdog") and not (x.get("exempt_why") and x.get("anchor")):
                out.append(f"bad-exempt:{svc}")
            if not x.get("watchdog") and x.get("anchor") and x["anchor"] not in text:
                out.append(f"stale-anchor:{svc}")
        if len([x for x in ledger_obj["entries"] if not x["watchdog"]]) > ledger_obj["frozen_max_exempt"]:
            out.append("exempt-growth")
        return out

    real_body = step_body(WATCHDOG_STEP)
    assert problems(ledger, real_body) == [], "前提：真语料必须先绿（否则下面六条红证无判别力）"

    import copy
    # ① 新加一条 deploy 腿却忘了接值守 —— 用「腿没进两个列表」表达
    assert problems(ledger, real_body.replace("admin-web ", "")) != []
    # ② 台账条目被删
    broken = copy.deepcopy(ledger)
    broken["entries"] = [e for e in broken["entries"] if e["svc"] != "admin-api"]
    assert problems(broken, real_body) != []
    # ③ 台账把某条腿标成 watchdog，而值守面里它在豁免列表
    broken = copy.deepcopy(ledger)
    for e in broken["entries"]:
        if e["svc"] == "c-end-h5":
            e["watchdog"] = True
            e.pop("exempt_why", None)
    assert problems(broken, real_body) != []
    # ④ 豁免没写理由
    broken = copy.deepcopy(ledger)
    for e in broken["entries"]:
        e.pop("exempt_why", None)
    assert problems(broken, real_body) != []
    # ⑤ 豁免锚在 workflow 里找不到（依据被删/改名）
    broken = copy.deepcopy(ledger)
    for e in broken["entries"]:
        if not e["watchdog"]:
            e["anchor"] = "这句话在 workflow 里不存在"
    assert problems(broken, real_body) != []
    # ⑥ 豁免条数上涨（超过冻结上限）
    broken = copy.deepcopy(ledger)
    broken["frozen_max_exempt"] = 0
    assert problems(broken, real_body) != []


def test_comment_only_change_is_not_red(tmp_path, monkeypatch):
    """**对照读数**：只往值守面正文里加注释 ⇒ 上述静态判据**不得**变红（守卫不许被自己的文案喂红）。"""
    body = step_body(WATCHDOG_STEP) + "\n# 只加一行注释：main HEAD 超时未部署会判红\n"
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    legs = {m.group(1) for m in RECONCILE_CALL.finditer(WORKFLOW.read_text(encoding="utf-8"))}
    w = set(re.search(r'^\s*WATCHED_LEGS="([^"]*)"', body, re.M).group(1).split())
    e = set(re.search(r'^\s*EXEMPT_LEGS="([^"]*)"', body, re.M).group(1).split())
    assert (w | e) == legs, "加注释改变了覆盖集合（解析器写坏了）"
    assert {x["svc"] for x in ledger["entries"]} == legs



# ══════════════════════════════════════════════════════════════════════════
# 五、issue #5935：**「落状态」本身有判据 + 分级 + 事件驱动清零 + 防自激**
# ══════════════════════════════════════════════════════════════════════════
# 现场（run `36911070357`，2026-10-01T19:00:20Z，main HEAD `3fa84ab`）：对账步 rc=0、六条腿**各落了一条**
# 状态，但**落的是错的**（全 `notarget`）⇒ 值守面报「5 条腿读不到对账状态」、`seen=6 acted=0` 且三桶全 0。
# 真因 = 那条前置判据写作 `gh workflow view "$wf" --ref main`，而 gh 要求 `--ref` **必须**搭 `--yaml`
# ⇒ **100% 失败**（本机实测：stderr `--yaml required when specifying --ref`、退出 1、0.063s；
# run 日志里六条腿各报一次、每条 ≈58ms）⇒ 六条腿**全部**被误记成「不在 main 上」。
# ⇒ 下面这批判据钉两件事：① **问对了对象**（`on_main` 的三态，正例锚 + 负例锚都要有）
#    ② **落了错的状态也必须有人报**（机制自证：`unrecorded` 种子位没被替换 ⇒ 本步自己判红并具名）。

STATE_SCRIPT = REPO_ROOT / "scripts" / "deploy_reconcile_state.sh"



def _state_rows(ex: "Exec") -> list:
    """读对账步落下的状态台账（每条腿一行，`腿\\t状态\\t依据`）。"""
    p = Path(ex.state)
    if not p.exists():
        return []
    return [ln.split("\t") for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip() != ""]


def _legs_in_workflow() -> set:
    return {m.group(1) for m in RECONCILE_CALL.finditer(WORKFLOW.read_text(encoding="utf-8"))}


# ── 判据 1：每条腿恰好一行状态；未落的腿**具名**判红（机制自证，不靠下游兜）──────────────

def test_every_leg_gets_exactly_one_state_row_with_a_seeded_placeholder(tmp_path):
    """**判据 1 的一半**：六条腿各**恰好一行**，且**先落 `unrecorded` 种子**
    （种子位没被替换 = 本轮从未记过这条腿 ⇒ 可判、可具名）。"""
    fx = make_repo(tmp_path, head_age_secs=60, drift=True)
    ex = Exec(tmp_path, fx, TERMINAL_RUNS(fx["head"]))
    assert ex.reconcile().returncode == 0, "前置条件：对账步必须成功"
    rows = _state_rows(ex)
    legs = [r[0] for r in rows]
    assert set(legs) == _legs_in_workflow(), f"台账必须覆盖全部腿且无多余 → {sorted(legs)}"
    assert len(legs) == len(set(legs)), f"**每条腿恰好一行**（整行替换，不是追加）→ {sorted(legs)}"
    assert _legs_in_workflow() == set(DEPLOY_WF), "反空跑锚点：`reconcile_one` 的腿集与 DEPLOY_WF 不一致"
    # 种子是 `unrecorded`（调用方 watchdog_note 之后才不是）—— 从**外置脚本**的正文现取该字面量
    src = STATE_SCRIPT.read_text(encoding="utf-8")
    assert "unrecorded" in src, "种子状态值必须是 `unrecorded`（判据 2 的具名口径依赖它）"


def test_reconcile_step_is_red_and_named_when_a_leg_is_left_unrecorded(tmp_path):
    """**判据 1 的另一半（机制自证，会红）**：造一条**没落状态**的腿 ⇒ **对账步自己**判红
    （不是让下游 fail-closed 兜），且**具名到腿**。

    造法：对账步**每条腿都会**（a）被种下 `unrecorded`（b）走判定并调 `watchdog_note` 覆盖它
    —— 所以「预置一个假腿名」没用（正文开头会把状态文件**重建**）。真正让一条腿**从未被记过**的
    形态 = 它在**走到任何 `watchdog_note` 之前就返回**：把它的 workflow 从 HEAD 的树里删掉，
    `on_main` 就会……**不**，那走的是 `notarget`（有状态）。⇒ 用**机制层**的形态：让该腿的
    `reconcile_one` 调用**不存在**（= 新加了一条腿却忘了接状态机）——
    本判据直接**构造**那个状态文件形态（其余腿已记、一条未记），再让**末道闸**去读它。
    ✅ 判据的射程如实登记：它证明的是「末道闸会具名判红」，**不是**「种子位在真实崩溃下一定会被留下」
    （后者由 `test_every_leg_gets_exactly_one_state_row_with_a_seeded_placeholder` 的种子面覆盖）。
    """
    fx = make_repo(tmp_path, head_age_secs=60, drift=True)
    state = tmp_path / "watchdog-state.tsv"
    state.write_text("admin-api\tdeployed\t手工预置\nghost-leg\tunrecorded\t本轮未落状态\n",
                     encoding="utf-8")
    ex = Exec(tmp_path, fx, TERMINAL_RUNS(fx["head"]), state=str(state))
    # 注入点必须在**对账循环之后**：循环里每条腿都会调 `watchdog_note` 覆盖种子（提前注入会被覆盖）；
    # 循环后、末道闸前注入 ⇒ 正好是「有腿的种子位没被替换」的形态（例如新加了一条腿却忘了接状态机）。
    body = step_body(RECONCILE_STEP)
    inject = ('printf %s\\n "admin-api\\tdeployed\\t手工预置" "ghost-leg\\tunrecorded\\t本轮未落状态"'
              ' > "$WATCHDOG_STATE"')
    broken = body.replace("watchdog_missing_gate || exit $?", inject + "\n          watchdog_missing_gate || exit $?", 1)
    assert broken != body, "变异注入未生效（找不到末道闸 `watchdog_missing_gate`）"
    rc = ex.reconcile_with_body(broken)
    assert rc.returncode == 3, (
        f"有腿没落状态 ⇒ **对账步自己**必须判红（退出码 3，不是 0）→ rc={rc.returncode}\n{rc.stdout}\n{rc.stderr}"
    )
    blob = rc.stdout + rc.stderr + ex.summary_text
    assert "ghost-leg" in blob, f"判红必须**具名到腿**（不许只说「有腿缺状态」）→\n{blob}"
    assert "::error::" in rc.stdout + rc.stderr, "判红必须给 ::error:: 注解（红而不留痕 = #3834 的形态）"
    assert "机制故障" in blob, f"缺状态属**机制故障**类（判据 3）→\n{blob}"


# ── 判据 2：`seen=N acted=0` 且原因桶全 0 ⇒ 必须归因（不留「说不出为什么」）──────────────

def test_liveness_why_accounts_for_every_leg_when_acted_is_zero(tmp_path):
    """**判据 2**：零动作（`acted=0`）时 `why` 必须把每一条腿都**落进一个可读的桶**——
    六条腿全 `terminal`（断路器）时 `dispatch=0`，`why` 仍须给得出 `不在main=` / `未落状态=` 两个读数
    （run `36911070357` 的形态恰恰是**三桶全 0 且说不出为什么**）。"""
    fx = make_repo(tmp_path, head_age_secs=2700 + 600, drift=True)
    ex = Exec(tmp_path, fx, TERMINAL_RUNS(fx["head"]))
    assert ex.reconcile().returncode == 0
    body = step_body(RECONCILE_STEP)
    assert "mechanism_liveness_declare" in body, "对账步必须发存活读数（issue #5326 判据 1）"
    assert "watchdog_missing" in body, (
        "存活读数的 `why` 必须带上「未落状态的腿**具名**清单」（判据 2：归因，不是只报计数）"
    )
    src = STATE_SCRIPT.read_text(encoding="utf-8")
    assert "MISS" in src and "unrecorded" in src, "外置脚本必须提供具名清单（`MISS`）的现取实现"


# ── 判据 3：分级 —— `读不到状态` 与 `确认未部署` **不得**压成同一种告警 ──────────────────

def test_mechanism_failure_gets_its_own_bucket_and_does_not_open_a_business_issue(tmp_path):
    """**判据 3（注入式红证）**：造一条**缺状态**的腿 ⇒ 走「机制故障」分支，
    **不**开 `[deploy-watchdog]` 那种业务单，但仍**出声**（::error:: + 非零退出 + 单上可归因）。"""
    fx = make_repo(tmp_path, head_age_secs=2700 + 600, drift=True)
    state = tmp_path / "watchdog-state.tsv"
    state.write_text(
        "".join(f"{svc}\tdeployed\t手工预置\n" for svc in DEPLOY_WF if svc != "admin-web")
        + "admin-web\tunrecorded\t本轮未落状态\n", encoding="utf-8")
    ex = Exec(tmp_path, fx, TERMINAL_RUNS(fx["head"]), state=str(state))
    wd = ex.watchdog()          # 刻意**不跑**对账步 ⇒ 状态保持注入形态
    assert wd.returncode == 3, f"机制故障必须判红 → rc={wd.returncode}\n{wd.stdout}\n{wd.stderr}"
    blob = wd.stdout + wd.stderr + ex.summary_text
    assert "机制故障" in blob and "admin-web" in blob, f"必须具名到腿且标明是机制故障 →\n{blob}"
    assert "::error::" in wd.stdout + wd.stderr, "必须给 ::error::（红而不留痕 = #3834 的形态）"
    created = [i for i in ex.issues if i["state"] == "open"]
    assert created, f"机制故障也要留痕（不能只打一行日志）→ calls={ex.gh_calls}"
    titles = [i["title"] for i in created]
    assert not any(t.startswith("[deploy-watchdog] main HEAD 超时未部署") for t in titles), (
        f"机制故障**不得**开成「确认未部署」那种业务单（判据 3）→ {titles}"
    )
    assert any("机制故障" in t for t in titles), f"应当开的是机制故障单 → {titles}"
    assert "priority/P1" not in created[0]["labels"], (
        f"机制故障单不得打业务告警标签 priority/P1 → {created[0]['labels']}"
    )


def test_leg_not_on_main_is_not_collapsed_into_mechanism_failure(tmp_path):
    """**判据 3 的反向对照**：`notarget`（目标 workflow 还没在 main 上 —— **新增腿的那个 PR** 的形态）
    是「还没轮到它」，**不得**与「确认未部署」或「机制故障」压成同一个桶。"""
    fx = make_repo(tmp_path, head_age_secs=2700 + 600, drift=True)
    state = tmp_path / "watchdog-state.tsv"
    state.write_text(
        "".join(f"{svc}\tdeployed\t手工预置\n" for svc in DEPLOY_WF if svc != "admin-web")
        + "admin-web\tnotarget\t目标 workflow deploy-frontend.yml 不在 main 上\n", encoding="utf-8")
    ex = Exec(tmp_path, fx, TERMINAL_RUNS(fx["head"]), state=str(state))
    wd = ex.watchdog()
    blob = wd.stdout + wd.stderr + ex.summary_text
    assert "机制故障=0" in blob, f"`notarget` **不得**计进机制故障桶（判据 3：三态三分）→\n{blob}"
    assert "机制故障「" not in blob and "::error::值守面机制故障" not in blob, (
        f"`notarget` 不得被判成机制故障 →\n{blob}"
    )
    assert "尚未轮到这个腿" in blob and "尚未轮到=1" in blob, f"`notarget` 必须有自己的可读口径 →\n{blob}"


def test_deployed_legs_stay_out_of_both_alert_buckets(tmp_path):
    """**判据 3 的正向对照**：`deployed` / `inflight` 既不进业务告警、也不进机制故障。

    ⚠️ 前置条件必须给足「已部署」信号（同 sha 结论 success）：**只给空 run 列表**的话六条腿落的是
    `dispatched`（= 本轮才补 dispatch，属**真阳性**）⇒ 报警是**对的**，拿它当正例是判据自己写错了。
    """
    fx = make_repo(tmp_path, head_age_secs=2700 + 600, drift=True)
    ex = Exec(tmp_path, fx, {wf: runs(fx["head"], "success") for wf in DEPLOY_WF.values()})
    assert ex.reconcile().returncode == 0
    wd = ex.watchdog()
    blob = wd.stdout + ex.summary_text
    assert wd.returncode == 0, f"全部已部署/在途时不得报警 →\n{wd.stdout}\n{wd.stderr}"
    assert "机制故障=0" in blob and "计入告警=0" in blob, f"三桶计数必须各自可见 →\n{blob}"
    assert not ex.issues, f"不得开任何单 → {ex.issues}"


# ── 判据 4：清零不依赖「下一轮 cron」—— 部署完成这一**事件**要能触发 ─────────────────────

def test_workflow_run_is_wired_as_the_deploy_completion_event():
    """**判据 4（接线）**：`workflow_run` 必须监听**全部** deploy 腿的 `completed`，
    并限定 `branches: [main]`（否则 PR 分支的部署完成也会触发，判出来的 HEAD 还不是 main 的）。"""
    on = _doc()[True] if True in _doc() else _doc().get("on")
    assert "workflow_run" in on, (
        "判据 4：部署成功这个**事件**必须能触发清零（实测 19:00Z 之后 ~12h 没有 reconcile run）"
    )
    assert on["schedule"] == [{"cron": "*/20 * * * *"}], f"既有 cron 不得动 → {on['schedule']!r}"
    wr = on["workflow_run"]
    assert wr["types"] == ["completed"], f"只关心终态 → {wr['types']!r}"
    assert wr["branches"] == ["main"], f"只关心 main 上的部署 → {wr['branches']!r}"
    # ⚠️ `workflows:` 写的是各腿 workflow 的 **`name:`**（不是文件名）—— 逐个现取核对：
    # 写文件名 / 拼错 ⇒ 该兜底面**静默脱钩**（本 workflow 永不触发，清零永远等下一轮 cron）。
    names = {}
    for fn in sorted(set(DEPLOY_WF.values())):
        text = (REPO_ROOT / ".github" / "workflows" / fn).read_text(encoding="utf-8")
        m = re.search(r"^name:\s*(.+)$", text, re.M)
        assert m, f"{fn} 没有顶层 `name:`"
        names[m.group(1).strip()] = fn
    assert set(wr["workflows"]) == set(names), (
        f"`workflow_run.workflows` 必须逐条命中已登记腿的 `name:`："
        f"写不中的 {sorted(set(wr['workflows']) - set(names))} / 没被监听的腿 "
        f"{sorted(set(names) - set(wr['workflows']))}"
    )


def test_workflow_run_and_schedule_share_one_judgement_body():
    """**判据 4（解耦）**：事件只决定「**什么时候**跑」，不决定「**怎么判**」——
    `workflow_run` 与 `schedule` 必须走**同一套**判定（只有 `pull_request` 不判定）。"""
    body = step_body(WATCHDOG_STEP)
    assert '= "pull_request"' in body, "必须显式分流 `pull_request`（PR 面没有 main HEAD 的部署对象）"
    assert "${{ github.event_name }}" not in body and 'EVENT_NAME' in body, (
        "事件名必须经 step env 传入（判定本体不读事件名 ⇒ 新事件自动同口径）"
    )
    assert body.count("if [") >= 1 and "退出 0" not in body, "反空跑锚点：分流逻辑必须在位"
    env = step_env(WATCHDOG_STEP)
    assert env.get("EVENT_NAME") == "${{ github.event_name }}", f"事件名接线不对 → {env!r}"


def test_reconciliation_step_body_stays_within_the_github_limit():
    """本包**改的是那条全仓最长的正文**（`Reconcile deploys`）：超限 ⇒ **整份 workflow invalid**
    ⇒ 该腿**完全不跑**（`push` 只留一条 0 job 的 failure run）。⇒ 逐条现取并把最长的那个点名。"""
    bodies = run_bodies()
    over = [b for b in bodies if b[0] > RUN_BODY_LIMIT]
    assert not over, "超限的 step 正文：" + "".join(
        f"\n  · {n} 字符：{wf} :: {job} :: {name}" for n, wf, job, name in sorted(over, reverse=True))
    longest = max(bodies)
    assert longest[0] > 4000, f"对照读数：最长 run 正文只有 {longest[0]} 字符（判据可能扫错对象）"


# ── 防自激（派单硬要求）：部署刚成功 ⇒ 不得再 dispatch ────────────────────────────────────

def test_no_self_excitation_when_deploy_just_succeeded(tmp_path):
    """**防自激（会红的对照）**：`workflow_run` 让「部署完成 → 对账」成链 ⇒ 必须证明它**收敛**：
    部署刚刚成功（同 sha 结论 success，无漂移）⇒ 对账**不得**再 dispatch（否则事件自激成环）。

    注意本判据的射程（**如实登记**）：它证明的是「同 sha 判据在位 ⇒ 该场景不重复派」，
    **不是**「任何时序下都不可能成环」—— 环的另一半（断路器对 failure/cancelled 的跳闸）由
    `test_breaker_terminal_state_is_red` 与 `test_terminal_state_does_not_redispatch` 承担。
    """
    fx = make_repo(tmp_path, head_age_secs=120, drift=False)
    success = {wf: runs(fx["head"], "success") for wf in DEPLOY_WF.values()}
    ex = Exec(tmp_path, fx, success)
    rc = ex.reconcile()
    assert rc.returncode == 0, f"前置条件：对账步必须成功 → {rc.stderr}"
    dispatched = [c for c in ex.gh_calls if c.startswith("workflow run")]
    assert not dispatched, (
        f"部署刚刚成功（同 sha 结论 success）⇒ **不得**再 dispatch（`workflow_run` 自激成环）→ {dispatched}"
    )
    assert "dispatch=0" in ex.summary_text, f"读数必须自证零动作 → {ex.summary_text}"


def test_terminal_state_does_not_redispatch(tmp_path):
    """**防自激的另一半**：部署落在不可恢复终态（failure / cancelled …）⇒ 断路器跳闸、**不再** dispatch
    —— 没有它，「部署失败完成 → 对账 → 再补一次 → 再失败」就是**无限环**（事件触发把环的转速拉满）。"""
    fx = make_repo(tmp_path, head_age_secs=2700 + 600, drift=True)
    ex = Exec(tmp_path, fx, {wf: runs(fx["head"], "cancelled") for wf in DEPLOY_WF.values()})
    rc = ex.reconcile()
    assert rc.returncode == 0, f"前置条件：对账步必须成功 → {rc.stderr}"
    dispatched = [c for c in ex.gh_calls if c.startswith("workflow run")]
    assert not dispatched, f"断路器跳闸后**不得**再 dispatch → {dispatched}"
    assert "断路器跳过=6" in ex.summary_text, f"前置条件：六条腿都必须被断路器挡住 → {ex.summary_text}"


# ── 类级元守卫：`workflow_run` 的上游清单未登记即红 ──────────────────────────────────────

def test_watchdog_ledger_records_the_event_trigger_contract():
    """**类级元守卫（未登记即红）**：台账必须把「事件触发面」也登记成一个**可核对**的契约 ——
    `workflow_run` 的每条上游都必须同时是**已登记的对账腿**（新加一条 deploy 腿却忘了让它的
    `completed` 触发清零 ⇒ 当场红，而不是等「部署成功了单还挂着」）。"""
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    on = _doc()[True] if True in _doc() else _doc().get("on")
    wr = on.get("workflow_run") or {}
    ups = set(wr.get("workflows") or [])
    assert ups, "反空跑锚点：`workflow_run.workflows` 为空（判据已过期）"
    # 上游是 `name:`，台账登记的是文件名 ⇒ 用「现取的 name: ⇄ 文件名」映射把两者对上（双向）
    name_to_file = {}
    for e in ledger["entries"]:
        f = REPO_ROOT / ".github" / "workflows" / e["wf"]
        m = re.search(r"^name:\s*(.+)$", f.read_text(encoding="utf-8"), re.M)
        assert m, f"{e['wf']} 没有顶层 `name:`"
        name_to_file[m.group(1).strip()] = e["wf"]
    legs = set(name_to_file)
    assert ups == legs, (
        f"`workflow_run` 的上游（各腿 `name:`）与台账登记的腿必须**双向相等**"
        f"（漏登记 ⇒ 事件清零对那条腿静默失效）："
        f"只在上游 {sorted(ups - legs)} / 只在台账 {sorted(legs - ups)}"
    )
    for e in ledger["entries"]:
        assert e.get("clearing_event") is True, (
            f"{e['svc']}: 每条腿都必须声明「部署完成事件会触发清零」（`clearing_event: true`）——"
            "判据 4 的承载体，漏了就没有东西会因此变红"
        )
    contract = ledger.get("event_trigger_contract") or {}
    assert "workflow_run" in contract.get("source", ""), (
        f"台账必须写明事件触发面的来源（现取命令），否则读者无法复核 → {contract!r}"
    )

# ══════════════════════════════════════════════════════════════════════════
# 四、**新发现的硬约束**：单个 step 的 `run` 正文长度上限（超限 ⇒ 整份 workflow 判 invalid）
# ══════════════════════════════════════════════════════════════════════════
# 本包实测（临时分支 `probe/5929-yaml-bisect` 的 11 个变体，全部以 `deploy-reconcile.yml` 为底）：
#   · `Reconcile deploys` 正文 **≤ 13,303 字符 ⇒ 有效**；**≥ 13,399 ⇒ invalid**；
#   · 与整份文件大小无关（同批「+9KB 新 step」的探针有效）、与行数无关（22 行有效 / 21 行无效）。
# 形态极隐蔽：本地 PyYAML 与仓库守卫**全绿**，GitHub 侧表现为「该 workflow 根本不建 run」
# （push 只留一条 0 job 的 failure run，`name` 回落成文件路径）。
# ⇒ 阈值取 **13,250**（**低于**已知有效读数 13,303，留 53 字符差）。
#   🔴 **现取读数（2026-10-02）**：`Reconcile deploys` —— **改前**（`origin/main` 3fa84ab89）= **13,125**
#   （距本上限只剩 **125 字符**，**不是** ~2.3K；订正「12,524」那一处转述：它是 PR #5931 **合并前**的
#   起草读数）；**本包（issue #5935）外置状态机之后** = **12,847**（仍全仓最长）。
#   全仓 **238** 条 `run` 正文，次长 = `.github/workflows/automerge.yml` 的 `Classify bot PR … and arm on` **10,975**。
#   复算 = `python3 -m pytest tests/unit_ci_workflows/test_deploy_watchdog.py -q -k run_body`（或直接调 `run_bodies()`）。
#   ⚠️ 出口：真要往这条正文里加东西 ⇒ **先把实现体外置**（`source scripts/deploy_reconcile_state.sh` ——
#   #5935 就是这么做的），不要靠「再加一点点应该没事」（这正是 #5929 踩到的形态）。
#   ⚠️ 本段**只点名** shell 语料（说明「出口是外置成脚本」），**不扫描**它 ⇒ 按 `kind=mentions`
#   登记在 `guard_scope_ledger.json`（issue #5284 的元守卫：引用语料即须入册）。
RUN_BODY_LIMIT = 13250


def run_bodies() -> list:
    """现取：全仓 workflow 里每条 `run:` 正文（(长度, 文件, job, step)）。"""
    out = []
    for wf in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            continue
        for job, jd in (doc.get("jobs") or {}).items():
            if not isinstance(jd, dict):
                continue
            for s in (jd.get("steps") or []):
                if isinstance(s, dict) and isinstance(s.get("run"), str):
                    out.append((len(s["run"]), wf.name, job, str(s.get("name"))[:40]))
    return out


def test_run_body_stays_under_the_github_limit():
    """**类级守卫（本包新发现的硬约束）**：任何 step 的 `run` 正文超长 ⇒ **整份 workflow 文件**
    被 GitHub 判 invalid（那条腿**完全不跑**：push 只留一条 0 job 的 failure run）。"""
    bodies = run_bodies()
    assert len(bodies) > 30, f"反空跑锚点：只取到 {len(bodies)} 条 run 正文（判据已过期）"
    over = [b for b in bodies if b[0] > RUN_BODY_LIMIT]
    assert not over, (
        f"以下 step 的 run 正文超过实测上限 {RUN_BODY_LIMIT} 字符（GitHub 会把**整份** workflow 判 "
        f"invalid ⇒ 该腿静默不跑）："
        + "".join(f"\n  · {n} 字符：{wf} :: {job} :: {name}" for n, wf, job, name in sorted(over, reverse=True))
        + "\n  出口：把实现体外置成 `.github/scripts/*.sh` 再 `source`（**注意**：外置要同批把执行式"
          " harness 的临时仓库里也放一份，否则它们跑的是「文件不存在」的形态）"
    )
    longest = max(bodies)
    assert longest[0] > 4000, (
        f"对照读数：现取最长的 run 正文只有 {longest[0]} 字符（{longest[1]}）—— "
        "判据可能扫错了对象（空跑）"
    )
