# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""`deploy-reconcile.yml`「兜底静默失效」的**执行式（桩化）红证** —— issue #4827。

## 被测对象与事故

`deploy-reconcile.yml` 是对账兜底（#2947）：检查 main HEAD 的镜像在不在，不在就
`gh workflow run deploy-<x>.yml` 补一次。实测（2026-09-20，run `35497126164` /
`35496618163` / `35496579037` …）它**每次都报 `completed success`、却一次都没 dispatch**，
每次都要主会话手动触发部署。

## 真根因（本文件用可执行判据钉死，不是推断）

改前 `Schedule code-change check` step 的判据是
`if git log --oneline -10 --name-only origin/main | grep -qE "…"; then CODE_CHANGED=1; fi`，
而 GitHub 的 `shell: bash` 是 `bash --noprofile --norc -e -o pipefail`（该 step 另有
`set -euo pipefail`）⇒ `grep -q` 首个命中即退出并关闭管道 ⇒ `git log` 死于 **SIGPIPE(141)**
⇒ **pipefail 把整条管道的退出码取为 141** ⇒ `if` 走**假**分支 ⇒ `CODE_CHANGED` **恒为 0**
⇒ 写 `SKIP_RECONCILE=1` ⇒ `Reconcile deploys` 被 `if: env.SKIP_RECONCILE != '1'` **整步跳过**
⇒ 每次 schedule/dispatch 对账都是 **success + 零动作**。

⇒ 所以 issue 原文猜的「HEAD 无代码改动」是**假结论**（`593504de9` 往前 10 个提交里有 24 个
代码路径文件）；真实形态是**结构性永远跳过**。

## 本文件锁什么（每一条都有「先绿」+「注入后必红」）

1. **改前形态（红证）**：在**浅克隆**（`fetch-depth: 1`，与 CI 同形）里逐字跑改前的 step
   正文 ⇒ `CODE_CHANGED=0` 且写出 `SKIP_RECONCILE=1`（= 对账 step 会被跳过）；
   对照组（同一仓库、只去掉 `pipefail`）⇒ `CODE_CHANGED=1` ⇒ 证明**是 pipefail 把
   SIGPIPE 变成了假分支**，不是「仓库里没有代码改动」。
2. **改后行为（桩化真跑 `run:` 正文）**：把 workflow 里**当前**的对账 `run:` 正文抽出来，
   在真实 git 仓库 + 桩 `gh`/`docker` 下执行，断言五个场景的**动作**与**判定依据**：
   - 注入「HEAD 镜像缺失 + 自上次成功部署起有代码改动」（= 事故形态）⇒ **真 dispatch**（3 条镜像腿
     + worker-h5 静态落地面腿，issue #5001）；
   - 「无漂移」（HEAD 是 docs 提交，但自上次成功部署起该服务代码没动）⇒ 零 dispatch
     **但 summary 明写依据**（不是静默 success）；
   - 「断路器命中」（同一 headSha 已 failure）⇒ 零 dispatch + 记明原因；
   - 「查询失败」⇒ **fail-open** 照旧补部署 + `::warning::`（#4767 语义不变）；
   - 「cancelled」⇒ **不**被当成 failure（fail-open 保持）。
3. 判据读的是**脚本当前文本 + 真实执行行为**，不是「与某个历史版本等值」。
   本文件**不联网、不碰真实云/真实 ACR、不写共享 `/tmp`**（一切产物落 pytest `tmp_path`）。

⚠️ 桩化的诚实标注：`gh`/`docker` 是**桩**（记录调用、读预设 JSON），因此本文件证明的是
「**workflow 的判定逻辑在给定输入下会做什么**」，不是「GitHub 真的会 dispatch」；
后者只有真跑 CI 才能验证（PR 里如实标注）。
"""
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-reconcile.yml"
RECONCILE_STEP = "Reconcile deploys"

ACR_REGISTRY = "acr.example.com"
ACR_NAMESPACE = "ns"

# 与 CI 的 shell 同形（run 日志实测：`/usr/bin/bash --noprofile --norc -e -o pipefail {0}`）
BASH_SHELL = ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail"]

# ── 改前 step 正文的**逐字节内联片段**（§18.3：红证锚点禁读可变引用 `origin/main`）
# 出处：`.github/workflows/deploy-reconcile.yml` @ `593504de9`（= 事故 run 35497126164 的
# main HEAD）的 step `Schedule code-change check`；`{set_line}` 处的原文是
# `set -euo pipefail`（对照组故意把它换成 `set -eu`，用来证明 pipefail 是那个关键变量）。
PRE_FIX_BODY = '''{set_line}
CODE_CHANGED=0
if git log --oneline -10 --name-only origin/main 2>/dev/null | grep -qE "^(backend/admin-api|backend/ai-agent-service|frontend|apps|packages)/"; then
  CODE_CHANGED=1
fi
echo "🔍 schedule 检查：最近提交含代码改动=$CODE_CHANGED"
if [ "$CODE_CHANGED" -eq 0 ]; then
  echo "✅ 最近提交无代码改动——跳过部署对账（防 502 窗口）"
  echo "SKIP_RECONCILE=1" >> "$GITHUB_ENV"
fi
'''

GH_STUB = '''#!/usr/bin/env python3
import json, os, sys

args = sys.argv[1:]
if args[:2] == ["run", "list"]:
    if os.environ.get("STUB_GH_LIST_FAIL") == "1":
        sys.exit(1)          # 模拟查询失败 ⇒ 必须走 fail-open
    wf = ""
    for i, a in enumerate(args):
        if a == "--workflow":
            wf = args[i + 1]
    with open(os.path.join(os.environ["STUB_RUNS_DIR"], wf), encoding="utf-8") as fh:
        runs = json.load(fh)
    sys.stdout.write(json.dumps(runs))
    sys.exit(0)
if args[:2] == ["workflow", "run"]:
    with open(os.environ["STUB_DISPATCH_LOG"], "a", encoding="utf-8") as fh:
        fh.write(args[2] + "\\n")
    sys.exit(0)
sys.exit(3)
'''

DOCKER_STUB = '''#!/usr/bin/env python3
import os, sys

args = sys.argv[1:]
if args[:2] == ["manifest", "inspect"]:
    # 按**完整镜像引用**（`<registry>/<ns>/<repo>:<tag>`）判定 —— 与真实 ACR 同形：tag 是
    # **逐仓库**的，所以「没有镜像的腿」（worker-h5，静态落地面腿，issue #5001）在这里
    # 真的不存在 ⇒ 它只能落到漂移判据 ②。
    ref = args[2]
    existing = {t for t in os.environ.get("STUB_IMAGE_TAGS", "").split(",") if t}
    sys.exit(0 if ref in existing else 1)
sys.exit(3)
'''

# 有镜像的三条腿（真值源 = `deploy-*.yml`）；worker-h5 **不在其中**（它发布静态文件，不构建镜像）
IMAGE_LEGS = ("admin-api", "ai-agent-service", "admin-web")


def image_ref(svc: str, head7: str) -> str:
    return f"{ACR_REGISTRY}/{ACR_NAMESPACE}/{svc}:sha-{head7}"


DEPLOY_WF = {
    "admin-api": "deploy-admin-api.yml",
    "ai-agent-service": "deploy-ai-agent-service.yml",
    "admin-web": "deploy-frontend.yml",
    # worker-h5（issue #5001）：**静态落地面腿**（无镜像）⇒ 判据 ① 对它恒不成立，判定来自漂移
    # 判据 ②（自 `worker-h5-publish.yml` 上次成功发布起 `frontend/worker-h5/**` 有无改动）。
    "worker-h5": "worker-h5-publish.yml",
    # bmini-h5-hosting（issue #5668）：第二条静态落地面腿（`frontend/bmini-app/**` 的 h5 产物 → 静态根 `b/`）。
    # 有意的「腿名 ≠ 传输镜像名」：同名会让判据 ① 在「镜像已推、发布失败」时命中 ⇒ 静默不补发布。
    "bmini-h5-hosting": "bmini-h5-publish.yml",
}


# ══════════════════════════════════════════════════════════════════════════
# 基础设施：真实 git 仓库 + 桩 gh/docker 下执行 workflow 的 `run:` 正文
# ══════════════════════════════════════════════════════════════════════════

def git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-c", "user.email=ci@example.com", "-c", "user.name=ci",
         "-c", "commit.gpgsign=false", *args],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def reconcile_script() -> str:
    """抽出 `Reconcile deploys` 的 `run:` 正文，并把 `${{ env.X }}` 换成字面量。"""
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    body = None
    for s in doc["jobs"]["reconcile"]["steps"]:
        if s.get("name") == RECONCILE_STEP:
            body = s.get("run", "")
            break
    assert body, f"反空跑锚点：`{WORKFLOW.name}` 里找不到 step `{RECONCILE_STEP}` 的 run 正文"
    for key, value in (("ACR_REGISTRY", ACR_REGISTRY), ("ACR_NAMESPACE", ACR_NAMESPACE)):
        body = body.replace("${{ env.%s }}" % key, value)
    assert "${{" not in body, f"`{RECONCILE_STEP}` 里还有没替换掉的 GitHub 表达式（判据已过期）"
    return body


def make_stubs(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name, content in (("gh", GH_STUB), ("docker", DOCKER_STUB)):
        p = bin_dir / name
        p.write_text(content, encoding="utf-8")
        p.chmod(0o755)
    return bin_dir


def commit_repos(tmp_path: Path, drift_paths=("backend/admin-api/b.py",)) -> dict:
    """`C1(代码) → C2(代码，部署被吞；只改 `drift_paths`) → D1(docs) → D2(docs, HEAD)`。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")

    def touch(rel: str) -> None:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(rel, encoding="utf-8")

    for rel in ("backend/admin-api/a.py", "backend/ai-agent-service/a.py", "frontend/admin-web/a.ts",
                "frontend/worker-h5/a.mjs", "frontend/bmini-app/a.ts"):
        touch(rel)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "code C1")
    c1 = git(repo, "rev-parse", "HEAD")

    for rel in drift_paths:
        touch(rel)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "code C2（部署触发被吞）")
    c2 = git(repo, "rev-parse", "HEAD")

    touch("docs/D1.md")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "docs D1")
    d1 = git(repo, "rev-parse", "HEAD")

    touch("docs/D2.md")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "docs D2")
    d2 = git(repo, "rev-parse", "HEAD")

    assert (c1, c2, d1, d2) == tuple(dict.fromkeys([c1, c2, d1, d2])), "四个提交 sha 必须互不相同"
    return {"repo": repo, "C1": c1, "C2": c2, "D1": d1, "D2": d2, "head7": d2[:7]}


def run_reconcile(tmp_path: Path, repo: Path, runs_by_wf: dict, *,
                  image_tags: str = "", list_fail: bool = False, head7: str) -> tuple:
    """在 `repo` 里执行改后的对账正文（桩 gh/docker），返回 (proc, summary, dispatches)。"""
    assert set(runs_by_wf) == set(DEPLOY_WF.values()), "必须给出全部五条对账腿的 run 列表"
    bin_dir = make_stubs(tmp_path)
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(exist_ok=True)
    for wf, runs in runs_by_wf.items():
        (runs_dir / wf).write_text(json.dumps(runs), encoding="utf-8")
    summary_path = tmp_path / "summary.md"
    dispatch_log = tmp_path / "dispatch.log"
    script = tmp_path / "reconcile.sh"
    script.write_text(reconcile_script(), encoding="utf-8")

    env = os.environ.copy()
    env.update({
        "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
        "STUB_RUNS_DIR": str(runs_dir),
        "STUB_DISPATCH_LOG": str(dispatch_log),
        "STUB_IMAGE_TAGS": image_tags,
        "GITHUB_STEP_SUMMARY": str(summary_path),
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REPOSITORY": "zhaokai-mgzn/migao",
        "GH_TOKEN": "stub-token",
    })
    if list_fail:
        env["STUB_GH_LIST_FAIL"] = "1"
    env["STUB_HEAD7"] = head7  # 供桩/断言侧引用（HEAD7 由被测脚本自己算，这里只做旁证）
    proc = subprocess.run(BASH_SHELL + [str(script)], cwd=repo, env=env,
                          capture_output=True, text=True)
    summary = summary_path.read_text(encoding="utf-8") if summary_path.exists() else ""
    dispatches = dispatch_log.read_text(encoding="utf-8").split() if dispatch_log.exists() else []
    return proc, summary, dispatches


def runs(sha: str, conclusion: str) -> list:
    return [{"headSha": sha, "conclusion": conclusion}]


def runs_all(sha: str, conclusion: str) -> dict:
    return {wf: runs(sha, conclusion) for wf in DEPLOY_WF.values()}


# ══════════════════════════════════════════════════════════════════════════
# 一、改前形态（红证）：浅克隆 + 逐字跑改前正文 ⇒ 恒 CODE_CHANGED=0 ⇒ SKIP_RECONCILE=1
# ══════════════════════════════════════════════════════════════════════════

def make_shallow_repo(tmp_path: Path) -> Path:
    """造一个与 CI 同形的**浅克隆**（`fetch-depth: 1`）：HEAD 提交远大于管道缓冲。"""
    src = tmp_path / "src"
    src.mkdir()
    git(src, "init", "-q", "-b", "main")
    (src / "README.md").write_text("base", encoding="utf-8")
    git(src, "add", "-A")
    git(src, "commit", "-qm", "base")
    # 代码路径文件排在最前（保证 `grep -q` 早早命中），其后 ~5000 个文件把日志撑到
    # 远超管道缓冲（64KiB）⇒ `grep -q` 退出后 `git log` 必然吃到 SIGPIPE。
    (src / "backend" / "admin-api").mkdir(parents=True)
    (src / "backend" / "admin-api" / "a.py").write_text("x", encoding="utf-8")
    for i in range(5000):
        d = src / "zzz" / f"d{i % 50}"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"file{i:05d}.txt").write_text("", encoding="utf-8")
    git(src, "add", "-A")
    git(src, "commit", "-qm", "code: backend/admin-api + 5000 files")

    dst = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth=1", f"file://{src}", str(dst)],
                   capture_output=True, text=True, check=True)
    return dst


@pytest.fixture(scope="module")
def shallow_repo(tmp_path_factory) -> Path:
    """浅克隆 fixture 造一次即可（含 5000 个文件，函数级重建会白花数秒）。"""
    return make_shallow_repo(tmp_path_factory.mktemp("pre-fix-shallow"))


def run_pre_fix(repo: Path, set_line: str, tmp_path: Path, *,
                shell: tuple = ("bash",), tag: str = "") -> tuple:
    """跑改前正文。唯一变量 = 脚本自己的 `set` 行（CI 的 `-o pipefail` 与它重复，故两者等价）。"""
    name = tag or set_line.replace(" ", "_")
    script = tmp_path / f"pre-fix-{name}.sh"
    script.write_text(PRE_FIX_BODY.format(set_line=set_line), encoding="utf-8")
    github_env = tmp_path / f"github_env-{name}"
    env = os.environ.copy()
    env["GITHUB_ENV"] = str(github_env)
    proc = subprocess.run([*shell, str(script)], cwd=repo, env=env,
                          capture_output=True, text=True)
    marker = github_env.read_text(encoding="utf-8") if github_env.exists() else ""
    return proc, marker


def test_pre_fix_shallow_repo_premises_hold(shallow_repo):
    """前提自断言（防空跑）：浅克隆 + 日志长度 > 管道缓冲 + 窗口里**确有**代码路径文件。"""
    repo = shallow_repo
    assert git(repo, "rev-parse", "--is-shallow-repository") == "true", "fixture 不是浅克隆 ⇒ 红证无效"
    log = subprocess.run(["git", "log", "--oneline", "-10", "--name-only", "origin/main"],
                         cwd=repo, capture_output=True, text=True, check=True).stdout
    assert "backend/admin-api/a.py" in log, "fixture 前提不成立：窗口里没有代码路径文件"
    assert len(log.encode()) > 65536, (
        f"前提不成立：日志只有 {len(log.encode())} 字节（未超管道缓冲 64KiB）"
        "⇒ `grep -q` 早退不会让生产者吃到 SIGPIPE ⇒ 本红证会变成空跑"
    )


def test_pre_fix_pipeline_dies_with_sigpipe_under_pipefail(shallow_repo):
    """真根因直接读数：`… | grep -q` 在 `-o pipefail` 下退出码 = **141**（SIGPIPE）。"""
    repo = shallow_repo
    pipe = subprocess.run(
        BASH_SHELL + ["-c", 'git log --oneline -10 --name-only origin/main | grep -qE "^backend/"'],
        cwd=repo, capture_output=True, text=True,
    )
    assert pipe.returncode == 141, (
        f"期望 SIGPIPE(141)，实得 {pipe.returncode} —— 若这不是 141，说明本红证的前提变了"
    )


def test_pre_fix_body_is_always_zero_and_writes_skip_marker(shallow_repo, tmp_path):
    """🔴 红证：改前正文在 CI 同形环境下**恒** `CODE_CHANGED=0` ⇒ 写 `SKIP_RECONCILE=1`。

    两种调用形态都跑：① CI 声明的 shell（`bash -e -o pipefail`）② 裸 `bash`（脚本自带
    `set -euo pipefail`）——两者都恒 0 ⇒ 说明坑**在脚本自己的 `set` 行 + `grep -q`**，
    与调用形态无关（这正是它「结构性永远跳过」的原因）。
    """
    repo = shallow_repo
    ci, ci_marker = run_pre_fix(repo, "set -euo pipefail", tmp_path,
                               shell=tuple(BASH_SHELL), tag="ci-shell")
    plain, plain_marker = run_pre_fix(repo, "set -euo pipefail", tmp_path, tag="plain-bash")
    for label, proc, marker in (("CI shell", ci, ci_marker), ("plain bash", plain, plain_marker)):
        assert proc.returncode == 0, f"[{label}] 改前正文应「成功」退出（这就是静默）→ {proc.stderr}"
        assert "最近提交含代码改动=0" in proc.stdout, (
            f"[{label}] 期望恒 0（SIGPIPE + pipefail）→ 实得 stdout：{proc.stdout!r}"
        )
        assert "SKIP_RECONCILE=1" in marker, (
            f"[{label}] 改前正文没写出短路标记 ⇒ 与事故读数（step `Reconcile deploys` = skipped）不符"
        )


def test_pre_fix_zero_is_caused_by_pipefail_not_by_missing_code(shallow_repo, tmp_path):
    """对照红证：同一仓库只去掉 `pipefail` ⇒ `CODE_CHANGED=1` ⇒ 0 是 pipefail 造成的。"""
    repo = shallow_repo
    proc, marker = run_pre_fix(repo, "set -eu", tmp_path, tag="no-pipefail")
    assert "最近提交含代码改动=1" in proc.stdout, (
        f"去掉 pipefail 后应能看见代码改动（证明仓库里确有代码路径文件）→ {proc.stdout!r}"
    )
    assert "SKIP_RECONCILE=1" not in marker, "对照组的 marker 不该被写出"


def non_comment_lines(text: str) -> str:
    """只保留**可执行**行（丢掉整行注释）——注释里解释旧机制不算「用了它」。"""
    return "\n".join(
        ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")
    )


def test_current_workflow_has_no_pipefail_grep_q_construct():
    """改后的正文里不得再有 `… | grep -q …`（真根因的载体已被整体删除）。"""
    body = reconcile_script()
    assert "grep -q" not in body, f"`{RECONCILE_STEP}` 里又出现 `grep -q`（issue #4827 会复发）"
    assert "SKIP_RECONCILE" not in non_comment_lines(WORKFLOW.read_text(encoding="utf-8")), (
        "workflow 的可执行行里又出现短路标记（静默 success 会跟着回来）"
    )
    assert "declare -A" not in body, (
        "对账正文用了 bash4 关联数组（`declare -A`）：macOS 自带 bash 3.2 跑不起来 ⇒ "
        "本文件的执行式红证会退化成 CI-only（改用函数参数，见 step 内的注释）"
    )


# ══════════════════════════════════════════════════════════════════════════
# 二、改后行为（桩化真跑）：注入各场景 ⇒ 断言动作 + 判定依据
# ══════════════════════════════════════════════════════════════════════════

ALL_DRIFT_PATHS = ("backend/admin-api/b.py", "backend/ai-agent-service/b.py", "frontend/admin-web/b.ts",
                   "frontend/worker-h5/b.mjs", "frontend/bmini-app/b.ts")


def test_incident_shape_now_dispatches(tmp_path):
    """🔴 事故形态（镜像缺失 + 自上次成功部署起该服务有代码改动）⇒ 改后**真 dispatch**。

    且**只补被吞的那条腿**（fixture 里 C2 只改了 admin-api）——这正是「无漂移判据」的价值：
    不做这个判定就会 3 条全量重建重部署（502 窗口 + 覆盖回滚风险）。
    """
    fx = commit_repos(tmp_path)
    proc, summary, dispatches = run_reconcile(
        tmp_path, fx["repo"], runs_all(fx["C1"], "success"), head7=fx["head7"],
    )
    assert proc.returncode == 0, f"对账正文非零退出 → {proc.stderr}\n{proc.stdout}"
    assert dispatches == ["deploy-admin-api.yml"], (
        f"应只 dispatch 被吞的那条腿（事故里一条都没动）→ 实得 {dispatches}\n{proc.stdout}"
    )
    assert "**结论**：dispatch=1 · 无漂移=4" in summary, f"summary 结论行不对 → {summary!r}"
    assert "已 dispatch 补部署" in summary and "backend/admin-api 有代码改动" in summary, (
        f"summary 没写清「为什么补」（判定依据）→ {summary!r}"
    )


def test_all_reconciled_legs_dispatch_when_code_changed(tmp_path):
    """五条对账腿都有代码改动（+ 镜像缺失）⇒ 五条都补（事故里 3 个服务的镜像都没构建）。"""
    fx = commit_repos(tmp_path, drift_paths=ALL_DRIFT_PATHS)
    proc, summary, dispatches = run_reconcile(
        tmp_path, fx["repo"], runs_all(fx["C1"], "success"), head7=fx["head7"],
    )
    assert proc.returncode == 0, f"{proc.stderr}"
    assert sorted(dispatches) == sorted(DEPLOY_WF.values()), f"→ {dispatches}\n{proc.stdout}"
    assert "**结论**：dispatch=5" in summary, f"{summary!r}"


def test_docs_head_without_drift_does_not_dispatch_but_explains(tmp_path):
    """docs HEAD + 无漂移 ⇒ 零 dispatch，**但必须显式给出依据**（不许静默 success）。"""
    fx = commit_repos(tmp_path)
    proc, summary, dispatches = run_reconcile(
        tmp_path, fx["repo"], runs_all(fx["D1"], "success"), head7=fx["head7"],
    )
    assert proc.returncode == 0, f"{proc.stderr}"
    assert dispatches == [], f"无漂移不该 dispatch（否则每个 docs 提交都空转重建）→ {dispatches}"
    assert "**结论**：dispatch=0 · 无漂移=5" in summary, f"{summary!r}"
    assert summary.count("无漂移：自") == 5, f"四条「无漂移」依据都要落表 → {summary!r}"
    assert "::notice::" in proc.stdout, "零 dispatch 时必须给一条 notice（可观测）"


def test_head_image_present_does_not_dispatch(tmp_path):
    """HEAD 的镜像已存在 ⇒ 零 dispatch + 记明依据（镜像名）。

    ⚠️ worker-h5 **没有镜像**（静态落地面腿，issue #5001）⇒ 判据 ① 对它恒不成立，
    它这一轮的「无漂移」来自**漂移判据 ②**——这是该腿的结构事实，不是本测试的偶然。
    """
    fx = commit_repos(tmp_path)
    proc, summary, dispatches = run_reconcile(
        tmp_path, fx["repo"], runs_all(fx["D1"], "success"),
        # 只让**有镜像**的三条腿的镜像存在（worker-h5 无镜像 —— 这正是 #5001 的结构事实）
        image_tags=",".join(image_ref(svc, fx["head7"]) for svc in IMAGE_LEGS),
        head7=fx["head7"],
    )
    assert proc.returncode == 0, f"{proc.stderr}"
    assert dispatches == []
    assert "**结论**：dispatch=0 · 无漂移=5" in summary
    assert summary.count("镜像已存在") == 3 and f"sha-{fx['head7']}" in summary, f"{summary!r}"
    assert summary.count("无漂移：自") == 2 and "| worker-h5 |" in summary \
        and "| bmini-h5-hosting |" in summary, (
        f"两条无镜像的静态落地面腿（worker-h5 / bmini-h5-hosting）必须落到漂移判据"
        f"（而不是「镜像已存在」）→ {summary!r}"
    )


def test_breaker_skips_and_records_reason(tmp_path):
    """#4767 断路器：同一 headSha 已 `failure` ⇒ 零 dispatch + 记明原因（fail-open 未削弱）。"""
    fx = commit_repos(tmp_path)
    proc, summary, dispatches = run_reconcile(
        tmp_path, fx["repo"], runs_all(fx["D2"], "failure"), head7=fx["head7"],
    )
    assert proc.returncode == 0, f"{proc.stderr}"
    assert dispatches == [], f"断路器命中后不该 dispatch → {dispatches}"
    assert "**结论**：dispatch=0 · 无漂移=0 · 断路器跳过=5" in summary, f"{summary!r}"
    assert summary.count("断路器：") == 5 and "已失败过" in proc.stdout, f"{summary!r}"


def test_cancelled_is_not_treated_as_failure(tmp_path):
    """#4767 的 fail-open：`cancelled` **不是** failure ⇒ 照旧补部署（语义未被削弱）。"""
    fx = commit_repos(tmp_path, drift_paths=ALL_DRIFT_PATHS)
    proc, summary, dispatches = run_reconcile(
        tmp_path, fx["repo"], runs_all(fx["D2"], "cancelled"), head7=fx["head7"],
    )
    assert proc.returncode == 0, f"{proc.stderr}"
    assert sorted(dispatches) == sorted(DEPLOY_WF.values()), (
        f"`cancelled` 被当成了 failure（= 削弱 #4767 的 fail-open）→ {dispatches}"
    )
    assert "断路器跳过=0" in summary, f"{summary!r}"


def test_query_failure_fails_open_with_warning(tmp_path):
    """查询失败 ⇒ **fail-open**：照旧补部署 + `::warning::` + 记入「判定失败」。"""
    fx = commit_repos(tmp_path, drift_paths=ALL_DRIFT_PATHS)
    proc, summary, dispatches = run_reconcile(
        tmp_path, fx["repo"], runs_all(fx["D1"], "success"), list_fail=True, head7=fx["head7"],
    )
    assert proc.returncode == 0, f"{proc.stderr}"
    assert sorted(dispatches) == sorted(DEPLOY_WF.values()), (
        f"查询失败必须 fail-open 照旧补部署（本检查出错绝不停掉对账）→ {dispatches}"
    )
    assert "::warning::" in proc.stdout, "判据不可用必须出声（warning），不许静默"
    assert "判定失败=5" in summary, f"{summary!r}"


def test_git_history_loss_fails_open_not_silent(tmp_path):
    """`P` 不可达（历史被截断）时，`git log P..HEAD` 报错 ⇒ fail-open + warning（不许静默放过）。"""
    fx = commit_repos(tmp_path, drift_paths=ALL_DRIFT_PATHS)
    fake = "0" * 40  # 取不到的成功部署记录（不在本仓库里）
    proc, summary, dispatches = run_reconcile(
        tmp_path, fx["repo"], runs_all(fake, "success"), head7=fx["head7"],
    )
    assert proc.returncode == 0, f"{proc.stderr}"
    assert sorted(dispatches) == sorted(DEPLOY_WF.values()), (
        f"git 判不了时必须 fail-open（按兜底补部署）→ {dispatches}\n{proc.stdout}"
    )
    assert "判定失败=5" in summary and "::warning::" in proc.stdout, f"{summary!r}"
