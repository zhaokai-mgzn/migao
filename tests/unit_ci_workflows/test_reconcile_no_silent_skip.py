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
   🔴 **前提是构造的，不是「历史恰好很大」**（issue #6202）：改前形态的 producer 由
   `keepalive_git_env` 挂一条**非匹配的有限尾巴** ⇒ consumer 一退出 producer 必然还在写 ⇒
   141 只取决于 pipeline 形态。旧版靠「日志 > 64KiB（管道缓冲）」那一版押的是**环境常量**：
   本机 30/30 = 141，而 CI run `37101030830` 两次尝试都是 0 —— 同一腿里 `> 65536` 的前提
   断言照样通过 ⇒ 夹具会随 runner 的管道容量 / 调度漂移（那次漂移挡住了**所有** PR）。
2. **改后行为（桩化真跑 `run:` 正文）**：把 workflow 里**当前**的对账 `run:` 正文抽出来，
   在真实 git 仓库 + 桩 `gh`/`docker` 下执行，断言五个场景的**动作**与**判定依据**：
   - 注入「HEAD 镜像缺失 + 自上次成功部署起有代码改动」（= 事故形态）⇒ **真 dispatch**（3 条镜像腿
     + worker-h5 静态落地面腿，issue #5001 + bmini-h5-hosting / c-end-h5 两条静态落地面腿，issue #5668 / #4184）；
   - 「无漂移」（HEAD 是 docs 提交，但自上次成功部署起该服务代码没动）⇒ 零 dispatch
     **但 summary 明写依据**（不是静默 success）；
   - 「断路器命中」（同一 headSha 落在**不可恢复的终态** —— `failure` / **`cancelled`** /
     `timed_out` / …，见 issue #5814 B 的允许名单）⇒ 零 dispatch + 记明原因；
   - 「查询失败」⇒ **fail-open** 照旧补部署 + `::warning::`（#4767 语义不变）；
   - 「`cancelled` 结论」⇒ **跳闸**（#5814 B **有意**改判 #4767 的旧读数：挂死的 run 报的就是
     cancelled，旧断路器只认 failure ⇒ 每 20min 再补一次 ⇒ 无限循环）。**人工出口保留**
     （`gh workflow run <wf> --ref main` / 重跑永远放行）。⚠️ 与本仓另一条同名措辞的判据
     `tests/unit_ci_workflows/test_eval_cancelled_not_failure.py`（**评测 run**：取消 ≠ 结果、
     不得建失败 issue）判的是**另一件事** —— 那条管「报告/建 issue 语义」，本条管
     「要不要自动重试同一个不可变 commit」，两者的正确默认**相反**。
3. 判据读的是**脚本当前文本 + 真实执行行为**，不是「与某个历史版本等值」。
   本文件**不联网、不碰真实云/真实 ACR、不写共享 `/tmp`**（一切产物落 pytest `tmp_path`）。

⚠️ 桩化的诚实标注：`gh`/`docker` 是**桩**（记录调用、读预设 JSON），因此本文件证明的是
「**workflow 的判定逻辑在给定输入下会做什么**」，不是「GitHub 真的会 dispatch」；
后者只有真跑 CI 才能验证（PR 里如实标注）。
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-reconcile.yml"
RECONCILE_STEP = "Reconcile deploys"
# 外置的状态机脚本（issue #5935）：对账步 `source` 它 ⇒ harness 的执行式仓库里必须有同一份
STATE_SCRIPT = REPO_ROOT / "scripts" / "deploy_reconcile_state.sh"

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


def absent_workflows():
    return {w.strip() for w in os.environ.get("STUB_WORKFLOW_ABSENT", "").split(",") if w.strip()}


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
if args[:2] == ["workflow", "view"]:
    # `gh workflow view <wf> --ref main`：workflow 必须**在 default branch 上**才 200
    # （新增腿的那个 PR 里它还没有 ⇒ 404，见 issue #5668 首轮实测）
    wf = args[2] if len(args) > 2 else ""
    sys.exit(1 if wf in absent_workflows() else 0)
if args[:2] == ["workflow", "run"]:
    wf = args[2] if len(args) > 2 else ""
    if wf in absent_workflows():
        # 与真 gh 同形：default branch 上不存在 ⇒ HTTP 404 + 非零退出
        sys.stderr.write("HTTP 404: workflow %s not found on the default branch\\n" % wf)
        sys.exit(1)
    with open(os.environ["STUB_DISPATCH_LOG"], "a", encoding="utf-8") as fh:
        fh.write(wf + "\\n")
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

# 有镜像的三条腿（真值源 = `deploy-*.yml`）；三条**静态落地面腿**（worker-h5 / bmini-h5-hosting /
# c-end-h5）**不在其中**（它们发布静态文件，不构建镜像）
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
    # c-end-h5（issue #4184）：**第三条静态落地面腿**（`frontend/mini-app/**` 的 h5 产物 → 静态根**本身**）。
    # 同样无镜像（判据 ① 对它恒不成立 ⇒ 走漂移判据 ②）；它的发布步骤只在手动 `publish=true` 时执行
    # （用户裁定 B）⇒ 本对账的兜底 dispatch **只报告、不发布**。
    "c-end-h5": "c-end-h5-publish.yml",
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


def commit_repos(tmp_path: Path, drift_paths=("backend/admin-api/b.py",),
                 absent_workflows: tuple = ()) -> dict:
    """`C1(代码) → C2(代码，部署被吞；只改 `drift_paths`) → D1(docs) → D2(docs, HEAD)`。

    `absent_workflows` = 模拟「**还没合并到 default branch** 的 workflow」（新增腿的那个 PR 的形态）：
    这些 workflow **从一开始就不写进仓库** ⇒ 它们真的不在 HEAD 的树里（issue #5935 换用
    `git cat-file -e HEAD:<path>` 之后，「在不在 main 上」问的就是这棵树）。
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")

    def touch(rel: str) -> None:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(rel, encoding="utf-8")

    for rel in ("backend/admin-api/a.py", "backend/ai-agent-service/a.py", "frontend/admin-web/a.ts",
                "frontend/worker-h5/a.mjs", "frontend/bmini-app/a.ts", "frontend/mini-app/a.ts"):
        touch(rel)
    # 六条腿的 workflow 与状态机脚本**同批**放进测试仓库（issue #5935）：
    # 对账步的前置判据 = `on_main`（`git cat-file -e HEAD:.github/workflows/<wf>`，见
    # scripts/deploy_reconcile_state.sh）⇒ 不放就是「六条腿全不在 main 上」，
    # 后面每个场景都跑不到判定本体（断言全过 = **假绿**）。
    for wf in sorted(set(DEPLOY_WF.values()) - set(absent_workflows)):
        touch(f".github/workflows/{wf}")
    (repo / "scripts").mkdir(exist_ok=True)
    (repo / "scripts" / STATE_SCRIPT.name).write_text(STATE_SCRIPT.read_text(encoding="utf-8"),
                                                      encoding="utf-8")
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
                  image_tags: str = "", list_fail: bool = False, head7: str,
                  absent_workflows: tuple = (), script_text: str = None) -> tuple:
    """在 `repo` 里执行改后的对账正文（桩 gh/docker），返回 (proc, summary, dispatches)。

    `absent_workflows` = 模拟「还没合并到 default branch 的 workflow」（新增腿的那个 PR 的形态）：
    此时 `gh workflow view` 返回 404、`gh workflow run` 也返回 404（与真 gh 同形）。
    `script_text` = 跑变异版正文（红证用）。
    """
    assert set(runs_by_wf) == set(DEPLOY_WF.values()), "必须给出全部五条对账腿的 run 列表"
    bin_dir = make_stubs(tmp_path)
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(exist_ok=True)
    for wf, runs in runs_by_wf.items():
        (runs_dir / wf).write_text(json.dumps(runs), encoding="utf-8")
    summary_path = tmp_path / "summary.md"
    dispatch_log = tmp_path / "dispatch.log"
    script = tmp_path / "reconcile.sh"
    script.write_text(script_text if script_text is not None else reconcile_script(), encoding="utf-8")

    env = os.environ.copy()
    env.update({
        "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
        "STUB_RUNS_DIR": str(runs_dir),
        "STUB_DISPATCH_LOG": str(dispatch_log),
        "STUB_IMAGE_TAGS": image_tags,
        "STUB_WORKFLOW_ABSENT": ",".join(absent_workflows),
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


def runs(sha: str, conclusion: str, status: str = "completed") -> list:
    return [{"headSha": sha, "conclusion": conclusion, "status": status}]


def runs_all(sha: str, conclusion: str, status: str = "completed") -> dict:
    return {wf: runs(sha, conclusion, status) for wf in DEPLOY_WF.values()}


# ══════════════════════════════════════════════════════════════════════════
# 一、改前形态（红证）：浅克隆 + 逐字跑改前正文 ⇒ 恒 CODE_CHANGED=0 ⇒ SKIP_RECONCILE=1
#    前提 = **构造的**（`keepalive_git_env` 让 producer 在 consumer 退出时仍在写），
#    不靠历史大小 / 管道容量 / 调度（issue #6202）。
# ══════════════════════════════════════════════════════════════════════════

# ── 改前 pipeline 的**逐字形态**（红证主体 —— issue #6202 只动「前提」，不动这个形态）──
PRE_FIX_PIPELINE = 'git log --oneline -10 --name-only origin/main | grep -qE "^backend/"'

# 确定性前提（issue #6202）：`grep -q` 首命中即退出 ⇒ `git log` 会不会吃到 SIGPIPE，取决于
# 「producer 写完 vs consumer 退出」这场竞态。旧夹具用「把历史造得足够大（日志 > 管道缓冲
# 64KiB）」去押它 —— **押不住**：那个字节数是**环境常量**，与 pipeline 形态无关。实测
# （2026-10-03）：本机 30/30 = 141（管道容量 65536 / 夹具日志 109,078 B），而 CI run
# `37101030830` 两次尝试都是 **0**（同一腿里 `> 65536` 的前提断言照样通过）⇒ 判据随 runner
# 的管道容量 / 调度漂移，且那次漂移挡住了**所有** PR。
# ⇒ 把前提改成**构造性事实**：`git` 垫片在真实输出之后挂一条**非匹配的有限尾巴** ——
#   consumer 打卡即退 ⇒ producer 必然还有几乎全部数据要写 ⇒ 必然 SIGPIPE。
#   「有限」是为反面服务：换成不早退的 `grep -c` 时 producer 要能自然写完（不挂死）。
KEEPALIVE_TAIL_LINES = 300000          # ≈2MB：远大于任何管道容量（Linux 上限 1MB）+ 早退窗口


def keepalive_git_env(tmp_path: Path) -> dict:
    """PATH 前置一个 `git` 垫片（只在 `log` 之后挂非匹配尾巴）⇒ 141 只取决于 pipeline 形态。

    垫片不碰 body 正文与 pipeline 形态（`PRE_FIX_BODY` / `PRE_FIX_PIPELINE` 逐字节不变），
    只把「producer 在 consumer 退出时仍在写」从**碰运气**改成**构造性事实**。
    """
    real_git = shutil.which("git")
    assert real_git, "找不到真 git —— 红证的 producer 必须是真 git（不是桩）"
    bin_dir = tmp_path / "keepalive-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    shim = bin_dir / "git"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        "# issue #6202：`log` 挂一条**纯数字**尾巴（不匹配任何被测 pattern）；其余子命令透传。\n"
        'if [ "$1" = "log" ]; then\n'
        f'  {real_git} "$@" || exit $?\n'
        f"  seq 1 {KEEPALIVE_TAIL_LINES}\n"
        "else\n"
        f'  exec {real_git} "$@"\n'
        "fi\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    return env


def make_shallow_repo(tmp_path: Path) -> Path:
    """造一个与 CI 同形的**浅克隆**（`fetch-depth: 1`）：窗口里**确有**代码路径文件。"""
    src = tmp_path / "src"
    src.mkdir()
    git(src, "init", "-q", "-b", "main")
    (src / "README.md").write_text("base", encoding="utf-8")
    git(src, "add", "-A")
    git(src, "commit", "-qm", "base")
    # 代码路径文件排在最前（保证 `grep -q` 早早命中）；其后 ~5000 个文件只是把现场造得
    # 「像事故时的 main」—— **不再是红证的前提**（靠输出量去押 SIGPIPE 正是 #6202 的病根，
    # 确定性已改由 `keepalive_git_env` 的构造性尾巴承担）。
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
                shell: tuple = ("bash",), tag: str = "", env: dict = None) -> tuple:
    """跑改前正文。唯一变量 = 脚本自己的 `set` 行（CI 的 `-o pipefail` 与它重复，故两者等价）。

    `env` = 调用方指定的运行环境（红证传 `keepalive_git_env(tmp_path)`：给 producer 挂确定性
    尾巴）；不传则用当前环境。`GITHUB_ENV` 由本函数补，调用方不必带。
    """
    name = tag or set_line.replace(" ", "_")
    script = tmp_path / f"pre-fix-{name}.sh"
    script.write_text(PRE_FIX_BODY.format(set_line=set_line), encoding="utf-8")
    github_env = tmp_path / f"github_env-{name}"
    run_env = dict(env) if env is not None else os.environ.copy()
    run_env["GITHUB_ENV"] = str(github_env)
    proc = subprocess.run([*shell, str(script)], cwd=repo, env=run_env,
                          capture_output=True, text=True)
    marker = github_env.read_text(encoding="utf-8") if github_env.exists() else ""
    return proc, marker


def test_pre_fix_shallow_repo_premises_hold(shallow_repo):
    """前提自断言（防空跑）：浅克隆 + 窗口里**确有**代码路径文件（⇒ `grep -q` 一定会命中）。

    ⛔ **刻意不再断言**「日志长度 > 管道缓冲（64KiB）」（issue #6202）：那是**环境常量**，
    与本判据要判的 pipeline 形态无关 —— 实测它在 CI 上通过、141 照样不成立。确定性已改由
    `keepalive_git_env` 的**构造性尾巴**承担（producer 不再由「历史够大」保证）。
    """
    repo = shallow_repo
    assert git(repo, "rev-parse", "--is-shallow-repository") == "true", "fixture 不是浅克隆 ⇒ 红证无效"
    log = subprocess.run(["git", "log", "--oneline", "-10", "--name-only", "origin/main"],
                         cwd=repo, capture_output=True, text=True, check=True).stdout
    assert "backend/admin-api/a.py" in log, "fixture 前提不成立：窗口里没有代码路径文件"


def test_pre_fix_pipeline_dies_with_sigpipe_under_pipefail(shallow_repo, tmp_path):
    """真根因直接读数：`… | grep -q` 在 `-o pipefail` 下退出码 = **141**（SIGPIPE）。

    🔴 确定性是**构造**出来的（`keepalive_git_env` 给 producer 挂非匹配尾巴 ⇒ consumer 一退出
    producer 必然还有数据要写），**不是**「夹具历史恰好很大」—— 后者是环境常量：本机 30/30 = 141，
    CI run `37101030830` 两次都是 0（issue #6202）。
    """
    pipe = subprocess.run(
        BASH_SHELL + ["-c", PRE_FIX_PIPELINE],
        cwd=shallow_repo, env=keepalive_git_env(tmp_path), capture_output=True, text=True,
    )
    assert pipe.returncode == 141, (
        f"期望 SIGPIPE(141)，实得 {pipe.returncode} —— 前提已构造化仍非 141 ⇒ 被测机制变了"
    )


def test_pre_fix_sigpipe_reading_is_not_vacuous(shallow_repo, tmp_path):
    """两侧夹住（issue #6202 要求 2①）：同一条 pipeline 换个形态 ⇒ **141 不再成立**。

    ① 去掉 `pipefail`（流水线状态取 `grep` 的 0）；② 换 `grep -c`（consumer 读到 EOF **不早退**
    ⇒ producer 不会丢 SIGPIPE）。两条都证明上面那条断言判的是「SIGPIPE 被 pipefail 取为管道状态」
    这个机制，不是恒真。
    """
    env = keepalive_git_env(tmp_path)
    no_pf = subprocess.run(["bash", "--noprofile", "--norc", "-e", "-c", PRE_FIX_PIPELINE],
                           cwd=shallow_repo, env=env, capture_output=True, text=True)
    assert no_pf.returncode != 141, "去掉 pipefail 仍得 141 ⇒ 该断言与 pipefail 无关（假红证）"
    assert no_pf.returncode == 0, f"去掉 pipefail 后状态应由 `grep` 决定(=0)，实得 {no_pf.returncode}"
    counted = subprocess.run(
        BASH_SHELL + ["-c", 'git log --oneline -10 --name-only origin/main | grep -cE "^backend/"'],
        cwd=shallow_repo, env=env, capture_output=True, text=True,
    )
    assert counted.returncode != 141, (
        f"consumer 不早退（`grep -c` 读到 EOF）时 producer 不该丢 SIGPIPE → {counted.returncode}"
    )
    assert counted.returncode == 0 and counted.stdout.strip() == "1", (
        f"`grep -c` 应读到 1 个代码路径（读的是同一条 `git log`，也证明尾巴**不匹配**）→ "
        f"rc={counted.returncode} out={counted.stdout.strip()!r}"
    )


def test_pre_fix_body_is_always_zero_and_writes_skip_marker(shallow_repo, tmp_path):
    """🔴 红证：改前正文在 CI 同形环境下**恒** `CODE_CHANGED=0` ⇒ 写 `SKIP_RECONCILE=1`。

    两种调用形态都跑：① CI 声明的 shell（`bash -e -o pipefail`）② 裸 `bash`（脚本自带
    `set -euo pipefail`）——两者都恒 0 ⇒ 说明坑**在脚本自己的 `set` 行 + `grep -q`**，
    与调用形态无关（这正是它「结构性永远跳过」的原因）。
    """
    repo = shallow_repo
    env = keepalive_git_env(tmp_path)
    ci, ci_marker = run_pre_fix(repo, "set -euo pipefail", tmp_path,
                               shell=tuple(BASH_SHELL), tag="ci-shell", env=env)
    plain, plain_marker = run_pre_fix(repo, "set -euo pipefail", tmp_path, tag="plain-bash", env=env)
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
    # 同一个 producer（`keepalive_git_env`）⇒ 与上一条只差 `pipefail` 一个变量
    proc, marker = run_pre_fix(repo, "set -eu", tmp_path, tag="no-pipefail",
                               env=keepalive_git_env(tmp_path))
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


def test_missing_state_script_does_not_kill_the_whole_step(tmp_path):
    """🔴 **回归护栏（issue #5935 的本 PR 首轮 CI 实测）**：对账步 checkout 的是 **`ref: main`**
    ⇒ 「新增这条腿的那个 PR」里 `scripts/deploy_reconcile_state.sh` **还不在 main 上**
    ⇒ 裸 `source` 会 `No such file or directory` 并把**整个对账步**打成 rc=1，而同轮其它五条腿
    本来是对的（实测 run `36943682332`，逐字报错见下）。

    这与 issue #5668 那条前置判据治的是**同一形态**：「**还轮不到我**」不许让机制本身停摆。
    修法 = 取仓库既有姿势（同 `.github/scripts/mechanism_liveness.sh`）：**存在才 source + 出声**。

    复算（把脚本从 fixture 里拿走）：
      `python3 -m pytest tests/unit_ci_workflows/test_reconcile_no_silent_skip.py -q -k missing_state_script`
    """
    fx = commit_repos(tmp_path, drift_paths=ALL_DRIFT_PATHS)
    # 把状态机脚本从检出里拿走 = 「本腿还没上 main」的形态（checkout 固定 ref: main）
    (fx["repo"] / "scripts" / "deploy_reconcile_state.sh").unlink()
    proc, summary, dispatches = run_reconcile(
        tmp_path, fx["repo"], runs_all(fx["C1"], "success"), head7=fx["head7"],
    )
    assert proc.returncode == 0, (
        f"状态机不在检出里**不许**把整个对账步打死（`source` 失败的原始报错 = "
        f"`scripts/deploy_reconcile_state.sh: No such file or directory`）→ {proc.stdout}\n{proc.stderr}"
    )
    assert "No such file or directory" not in proc.stderr, f"裸 `source` 的形态还在 → {proc.stderr}"
    assert "::warning::" in proc.stdout, (
        f"「本轮不落状态」必须**出声**（不许静默 success）→ {proc.stdout}"
    )
    assert "on_main: command not found" not in proc.stderr, (
        f"函数没定义就跑 = 「只加 `if [ -f ]`」那种半修 → {proc.stderr}"
    )
    assert not dispatches, (
        f"弃权 = **本轮整体不对账**（不落状态就判不了，判不了就不许动线上）→ {dispatches}"
    )


# ══════════════════════════════════════════════════════════════════════════
# 二、改后行为（桩化真跑）：注入各场景 ⇒ 断言动作 + 判定依据
# ══════════════════════════════════════════════════════════════════════════

ALL_DRIFT_PATHS = ("backend/admin-api/b.py", "backend/ai-agent-service/b.py", "frontend/admin-web/b.ts",
                   "frontend/worker-h5/b.mjs", "frontend/bmini-app/b.ts", "frontend/mini-app/b.ts")


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
    assert "**结论**：dispatch=1 · 无漂移=5" in summary, f"summary 结论行不对 → {summary!r}"
    assert "已 dispatch 补部署" in summary and "backend/admin-api 有代码改动" in summary, (
        f"summary 没写清「为什么补」（判定依据）→ {summary!r}"
    )


def test_all_reconciled_legs_dispatch_when_code_changed(tmp_path):
    """六条对账腿都有代码改动（+ 镜像缺失）⇒ 六条都补（事故里 3 个服务的镜像都没构建）。"""
    fx = commit_repos(tmp_path, drift_paths=ALL_DRIFT_PATHS)
    proc, summary, dispatches = run_reconcile(
        tmp_path, fx["repo"], runs_all(fx["C1"], "success"), head7=fx["head7"],
    )
    assert proc.returncode == 0, f"{proc.stderr}"
    assert sorted(dispatches) == sorted(DEPLOY_WF.values()), f"→ {dispatches}\n{proc.stdout}"
    assert "**结论**：dispatch=6" in summary, f"{summary!r}"


def test_docs_head_without_drift_does_not_dispatch_but_explains(tmp_path):
    """docs HEAD + 无漂移 ⇒ 零 dispatch，**但必须显式给出依据**（不许静默 success）。"""
    fx = commit_repos(tmp_path)
    proc, summary, dispatches = run_reconcile(
        tmp_path, fx["repo"], runs_all(fx["D1"], "success"), head7=fx["head7"],
    )
    assert proc.returncode == 0, f"{proc.stderr}"
    assert dispatches == [], f"无漂移不该 dispatch（否则每个 docs 提交都空转重建）→ {dispatches}"
    assert "**结论**：dispatch=0 · 无漂移=6" in summary, f"{summary!r}"
    assert summary.count("无漂移：自") == 6, f"六条「无漂移」依据都要落表 → {summary!r}"
    assert "::notice::" in proc.stdout, "零 dispatch 时必须给一条 notice（可观测）"


def test_head_image_present_does_not_dispatch(tmp_path):
    """HEAD 的镜像已存在 ⇒ 零 dispatch + 记明依据（镜像名）。

    ⚠️ 三条**静态落地面腿**（worker-h5 / bmini-h5-hosting / c-end-h5，issue #5001 / #5668 / #4184）
    **没有镜像** ⇒ 判据 ① 对它们恒不成立，它们这一轮的「无漂移」来自**漂移判据 ②**——
    这是这些腿的结构事实，不是本测试的偶然。
    """
    fx = commit_repos(tmp_path)
    proc, summary, dispatches = run_reconcile(
        tmp_path, fx["repo"], runs_all(fx["D1"], "success"),
        # 只让**有镜像**的三条腿的镜像存在（三条静态落地面腿无镜像 —— 这正是 #5001/#5668/#4184 的结构事实）
        image_tags=",".join(image_ref(svc, fx["head7"]) for svc in IMAGE_LEGS),
        head7=fx["head7"],
    )
    assert proc.returncode == 0, f"{proc.stderr}"
    assert dispatches == []
    assert "**结论**：dispatch=0 · 无漂移=6" in summary
    assert summary.count("镜像已存在") == 3 and f"sha-{fx['head7']}" in summary, f"{summary!r}"
    assert summary.count("无漂移：自") == 3 and "| worker-h5 |" in summary \
        and "| bmini-h5-hosting |" in summary and "| c-end-h5 |" in summary, (
        f"三条无镜像的静态落地面腿（worker-h5 / bmini-h5-hosting / c-end-h5）必须落到漂移判据"
        f"（而不是「镜像已存在」）→ {summary!r}"
    )


def test_breaker_skips_and_records_reason(tmp_path):
    """#4767 断路器（#5814 B 之后 = **不可恢复终态**断路器）：同一 headSha 已 `failure`
    ⇒ 零 dispatch + 记明原因。

    ⚠️ 本单（#5814 B）把判定从「只认 failure」扩成**允许名单** ⇒ 判据文本随之改准
    （`已失败过（conclusion=failure）` → `落在不可恢复终态（conclusion=…）`）。
    **承重语义一字未动**：命中 ⇒ 零 dispatch + summary 逐服务给出原因 + 人工出口
    （`gh workflow run <wf> --ref main`）。fail-open 由同文件
    `test_query_failure_fails_open_with_warning` / `test_git_history_loss_fails_open_not_silent`
    与新增的 `tests/unit_ci_workflows/test_deploy_breaker_allowlist.py` 承接。
    """
    fx = commit_repos(tmp_path)
    proc, summary, dispatches = run_reconcile(
        tmp_path, fx["repo"], runs_all(fx["D2"], "failure"), head7=fx["head7"],
    )
    assert proc.returncode == 0, f"{proc.stderr}"
    assert dispatches == [], f"断路器命中后不该 dispatch → {dispatches}"
    assert "**结论**：dispatch=0 · 无漂移=0 · 断路器跳过=6" in summary, f"{summary!r}"
    assert summary.count("断路器：") == 6 and "不可恢复的终态" in proc.stdout, f"{summary!r}"
    assert "gh workflow run" in proc.stdout and "gh workflow run" in summary, (
        "跳闸必须给出**人工出口**（跳闸而不给出路 = 把机制变成黑箱）"
    )


def test_cancelled_conclusion_trips_the_breaker(tmp_path):
    """#5814 B：`cancelled` 结论 ⇒ **跳闸**（不再自动补部署）—— 这正是事故的循环入口。

    ## 为什么改判（本单**有意**改掉 #4767 的旧读数，不是削弱它）
    #4767 当时把 `cancelled` 当 fail-open（「取消不是结论」）是**合理的**：那时没有
    「同一 commit 被反复自动重试」这条回路。但 #5814 的实测把因果关系反过来了：

    · 挂死点（推 ACR 约 40min）**不是**部署脚本报错，而是被 job 的 `timeout-minutes: 45`
      **打死** ⇒ GitHub 报的结论就是 **`cancelled`**（**不是** failure）；
    · 旧断路器只认 `failure` ⇒ **不跳闸** ⇒ `deploy-reconcile.yml` 每 20min 对同一个 commit
      再补一次 ⇒ 又一个 run 挂 40min ⇒ **无限循环**（三条腿各自的 `on.schedule` 也在独立重试）。

    ⇒ 结论：**在「部署腿」这条路上**，`cancelled` 对同一个不可变 sha 而言是**不可恢复的终态**
    （不由部署脚本自己结束）⇒ 必须跳闸。**这不是「把 cancelled 记成失败」**——本条与
    `tests/unit_ci_workflows/test_eval_cancelled_not_failure.py`（**评测 run**：取消 ≠ 结果、
    不得建失败 issue）判的是**两件事**：那条管**报告/建 issue 语义**，本条管
    **「要不要自动重试同一个不可变 commit」**，两者的正确默认**恰好相反**（刻意不混）。

    **人工出口保留**：`gh workflow run <wf> --ref main`（或重跑）永远放行 —— 跳闸只挡自动重试。
    **fail-open 保留**：查询失败 / 无记录 ⇒ 照旧补部署（见 `test_query_failure_fails_open_with_warning`）。
    """
    fx = commit_repos(tmp_path, drift_paths=ALL_DRIFT_PATHS)
    proc, summary, dispatches = run_reconcile(
        tmp_path, fx["repo"], runs_all(fx["D2"], "cancelled"), head7=fx["head7"],
    )
    assert proc.returncode == 0, f"{proc.stderr}"
    assert dispatches == [], (
        f"`cancelled` 结论必须跳闸（#5814：挂死的 run 报的就是 cancelled）→ {dispatches}"
    )
    assert "**结论**：dispatch=0 · 无漂移=0 · 断路器跳过=6" in summary, f"{summary!r}"
    assert "conclusion=cancelled" in summary, f"跳闸原因必须点名结论 → {summary!r}"
    assert "gh workflow run" in summary, f"跳闸必须给人工出口 → {summary!r}"


def test_still_running_same_commit_is_skipped_as_churn(tmp_path):
    """#5814 B：同 sha 的 run **还没跑完**（`status != completed`）⇒ 跳过 + 打印理由。

    理由 = 重复 dispatch 是**纯 churn**：`deploy-<svc>` 是
    `concurrency: {cancel-in-progress: false}` ⇒ 新 run 只会在队列里白等（事故实测排队 30~42min，
    正常 0.1min）。这条也是「挂死循环」最直接的一环：在跑的 run 还没出终态时，
    对账**每 20min** 就再压一个进去。
    """
    fx = commit_repos(tmp_path, drift_paths=ALL_DRIFT_PATHS)
    proc, summary, dispatches = run_reconcile(
        tmp_path, fx["repo"], runs_all(fx["D2"], "", status="in_progress"), head7=fx["head7"],
    )
    assert proc.returncode == 0, f"{proc.stderr}"
    assert dispatches == [], f"同 commit 有 run 在跑时不该再 dispatch（纯 churn）→ {dispatches}"
    assert "**结论**：dispatch=0 · 无漂移=0 · 断路器跳过=6" in summary, f"{summary!r}"
    assert "在跑/排队" in proc.stdout and "status=in_progress" in proc.stdout, (
        f"跳过必须显式打印「已有同 commit 的 run 在跑/排队」+ 状态 → {proc.stdout}"
    )
    assert "仍在跑/排队" in summary, f"{summary!r}"


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
    assert "判定失败=6" in summary, f"{summary!r}"


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
    assert "判定失败=6" in summary and "::warning::" in proc.stdout, f"{summary!r}"


# ══════════════════════════════════════════════════════════════════════════
# 三、「新增腿的那个 PR」：目标 workflow 还没合并到 main（issue #5668 首轮实测）
# ══════════════════════════════════════════════════════════════════════════

def test_new_leg_whose_workflow_is_not_on_main_is_skipped_loudly(tmp_path):
    """新增腿的那个 PR：被对账的 workflow 还没在 default branch 上 ⇒ `gh` 会 404。

    **实测**（issue #5668 的 PR 首轮，run 36251452618）：没有这条前置判据时
    `gh workflow run bmini-h5-publish.yml --ref main` 返回
    「HTTP 404: workflow … not found on the default branch」⇒ `set -euo pipefail` 下
    **整个对账 step 非零退出** —— 而它同轮判对的其它四条腿被一起染红。

    ⇒ 判据三面：① 该腿**不 dispatch**；② **出声**（`::warning::` + summary 明写原因与去向）；
    ③ 其它四条腿照常补部署、整步 rc=0（一个刚落地的腿不许让对账机制本身停摆）。
    """
    fx = commit_repos(tmp_path, drift_paths=ALL_DRIFT_PATHS,
                      absent_workflows=("bmini-h5-publish.yml",))
    others = sorted(w for w in DEPLOY_WF.values() if w != "bmini-h5-publish.yml")
    # 基准 = C1（代码提交 C2 之前）⇒ 自上次成功部署起五条腿**都有**漂移，缺了前置判据就会去 dispatch
    proc, summary, dispatches = run_reconcile(
        tmp_path, fx["repo"], runs_all(fx["C1"], "success"),
        absent_workflows=("bmini-h5-publish.yml",), head7=fx["head7"],
    )
    assert proc.returncode == 0, f"新增腿尚未在 main 上时不许让整步红 → {proc.stdout}\n{proc.stderr}"
    assert sorted(dispatches) == others, f"其它四条腿必须照常补部署 → {dispatches}"
    assert "::warning::" in proc.stdout and "不在 main 上" in proc.stdout, (
        f"必须出声（warning + 原因）→ {proc.stdout}"
    )
    assert "不在 main=1" in summary and "尚未在 main 上" in summary, f"{summary!r}"
    # issue #5935：这条腿必须留下**它自己的**状态（`notarget` = 主动弃权）—— 与「状态机没记它」
    # （`unrecorded` ⇒ 末道闸判红）**必须是两个值**，否则「新增腿的那个 PR」每轮判红（#5668 的契约）。
    # ⚠️ 本 harness **不设** `WATCHDOG_STATE` ⇒ 走外置脚本的默认值（仓库根下的相对路径）
    state = (tmp_path / "repo" / ".deploy-watchdog-state.tsv").read_text(encoding="utf-8")
    rows = dict(ln.split("\t")[:2] for ln in state.splitlines() if ln.strip())
    assert rows.get("bmini-h5-hosting") == "notarget", f"弃权的腿必须落 `notarget` → {rows}"
    assert "unrecorded" not in state, f"没有腿该留在 `unrecorded`（那会让末道闸判红）→ {state}"


def test_not_on_main_criterion_has_discriminating_power(tmp_path):
    """🔴 红证：去掉那条前置判据 ⇒ 同一输入下 `gh workflow run` **真的 404、整步非零退出**
    （复现 #5668 首轮 CI 的真实形态，不是纸面推断）。"""
    fx = commit_repos(tmp_path, drift_paths=ALL_DRIFT_PATHS,
                      absent_workflows=("bmini-h5-publish.yml",))
    text = reconcile_script()
    broken = text.replace(
        'on_main "$wf" || { _g=$?; if [ "$_g" = 1 ]; then NOTARGET=$((NOTARGET + 1)); on_main_absent "$svc" "$wf"; fi; return 0; }',
        ":",
    )
    assert broken != text, "变异注入未生效（找不到「workflow 是否在 main 上」的前置判据 `on_main`）"
    proc, _summary, _dispatches = run_reconcile(
        tmp_path, fx["repo"], runs_all(fx["C1"], "success"),
        absent_workflows=("bmini-h5-publish.yml",), head7=fx["head7"], script_text=broken,
    )
    assert proc.returncode != 0, (
        f"变异版竟判绿 —— 说明该判据的判别力没有被证明（空断言方向）→ {proc.stdout}"
    )
    assert "404" in (proc.stdout + proc.stderr), f"期望复现 gh 的 404 → {proc.stdout}\n{proc.stderr}"
