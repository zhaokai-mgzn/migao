# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""部署挂死与 cron 自放大的两条修法 —— issue #5814 A / B / C。

## 事故（主会话已确证的读数，本文件不重新推导，只把它们钉成可执行判据）

| 事实 | 读数 |
|---|---|
| 挂死点 | `Build and push Docker image`：构建 1~2min 跑完 → `#14 pushing layers` → `#15 [auth] …aliyuncs.com pull,push token`（鉴权**成功**）⇒ **约 40 分钟零输出** ⇒ `##[error]The operation was canceled.`（被 `timeout-minutes: 45` 打死）。`exporting cache` **从未出现** ⇒ 不是 GHA cache 导出。run `36582359732` 的 job `109453551643` |
| 该步 32 个样本 | **双峰**：`2.0~4.2min`（健康）vs `11.7~43.4min`（病态，三条腿中位 `37.6~40.2min`） |
| 端到端 | 三条部署腿 `~10min → 40~45min`，大量 run 以 `cancelled` 收场（09-28/09-29 中位 `40.4m / 42.8m / 45.6m`） |
| 循环入口 | **超时打死报的是 `cancelled`，不是 `failure`** ⇒ 旧断路器（只认 failure）**不跳闸** ⇒ 每 20min 再补一次 ⇒ 又一个 run 挂 40min ⇒ **无限循环** |
| 排队 | `concurrency: cancel-in-progress: false` ⇒ 挂住的 run 攥锁 40min ⇒ 实测排队 `42.8 / 31.1 / 30.9 / 30.5` 分钟（正常 `0.1` 分钟） |

## 三条修法（本文件逐条钉住）

- **A**（`.github/workflows/deploy-ai-agent-service.yml` / `deploy-admin-api.yml` / `deploy-frontend.yml`
  的 `Build and push Docker image` / `Build and push`）：给**单次** push 尝试一个显式上界
  （`timeout`，coreutils）＋失败/超时后**重试一次**＋两次都不成时**点名卡在哪一步**（推送到 ACR）
  后非零退出。最坏墙钟 `2 × 720s = 24min`，**明显小于** job 的 `timeout-minutes: 45`。
- **B**（`.github/workflows/deploy-reconcile.yml` 的 `reconcile_one()`）：
  ① 断路器从「只认 `failure`」改成**允许名单**（可继续补部署的结论 = `success` / `skipped` /
  `neutral` / 空）⇒ **其余一切结论跳闸**（`failure` / `cancelled` / `timed_out` /
  `startup_failure` / `action_required` / `stale` / 将来新增的）；
  ② 同 sha 的 run **还没跑完**（`status != completed`）⇒ 也跳过（重复 dispatch 是**纯 churn**）。
- **C**（三条部署腿的 `Skip if already built (schedule reconcile)`）：同一道闸门 —— 镜像缺失
  **不等于**「该补一次构建」；该 sha 最近一次 run 的结论不可恢复 ⇒ 也 `skip=true`。

## 为什么用**允许名单**（本文件 ③ 是它的机械锁）

黑名单形态（`[ "$last" = "failure" ] || [ "$last" = "cancelled" ]`）在 GitHub **将来新增一种结论**时
会**静默退回 fail-open** ⇒ 本 bug 原样复发（这正是 #5814 的病灶：`cancelled` 当年没进黑名单）。
允许名单让**新结论默认跳闸**（fail-closed）。③ 的元守卫把这条性质钉成机械判据。

## fail-open 与人工出口（两条**保留**语义，各有判据）

- **fail-open 保留**：查询失败 / 无记录 / `gh` 报错 ⇒ **照旧补部署** —— 本检查自己出错**绝不**
  停掉对账/部署。判据 = ② 的 `test_sync_query_unavailable_fails_open` 与 ⑤ 的红证。
- **人工出口保留**：跳闸时**显式**打印 `gh workflow run <wf> --ref main`（stdout + `$GITHUB_STEP_SUMMARY`）；
  显式回滚（`workflow_dispatch -f image_tag=<tag>`，#4852 的逃生口）**永远放行**（④ 逐条跑三条腿）。

## 判据形态与诚实标注

- 全部判据都是**执行式**的：把 workflow 里**当前**的 step 正文抽出来，用桩 `gh` / `docker` / `timeout`
  在 `tmp_path` 里**真跑**，断言「给定输入下会做什么」。本文件**不联网、不碰真实 ACR、不写共享 `/tmp`**。
- ⚠️ **桩化的边界**：桩证明的是**判定逻辑在给定输入下的行为**，**不是**「GitHub 真的会这样」，
  也**不是**「真实 ACR 推送超时一定会被 `timeout` 掐断」。后者只有真跑 CI 才能验证。
- 三条**注入式红证**（防空断言）：① 断路器改回「只认 failure」⇒ 判据必红；② 改成黑名单形态
  ⇒ ③ 的类级元守卫必红；③ **只改注释** ⇒ 判据不动（对照读数）。
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

RECONCILE = "deploy-reconcile.yml"
# 三条部署腿（与 test_deploy_churn_and_env_gate.py 的 DEPLOY_WORKFLOWS 同集合）
DEPLOY_WORKFLOWS = ("deploy-admin-api.yml", "deploy-ai-agent-service.yml", "deploy-frontend.yml")
# 有 `Skip if already built (schedule reconcile)` 步骤的腿 —— 与 B 共用同一道闸门（issue #5814 C）
SYNC_LEGS = DEPLOY_WORKFLOWS

SYNC_STEP = "Skip if already built (schedule reconcile)"
RECONCILE_STEP = "Reconcile deploys"
BUILD_STEP = {"deploy-ai-agent-service.yml": "Build and push Docker image",
              "deploy-admin-api.yml": "Build and push Docker image",
              "deploy-frontend.yml": "Build and push"}

# 允许名单的**逐字**取值（`success` 之外的中性结论：`skipped` / `neutral`）。
# 空（= 查不到同 sha 记录）在两条判据里都由「不落进跳闸分支」体现。
ALLOWED_CONCLUSIONS = ("success", "skipped", "neutral")
FORBIDDEN_CONCLUSIONS = (
    "failure", "cancelled", "timed_out", "startup_failure", "action_required", "stale",
)

BASH_SHELL = ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail"]

# ── 桩（全部 bash，避免 heredoc 里出现 Python 三引号与 `${VAR}` 转义两套规则）──────────
GH_STUB = r'''#!/bin/bash
# 桩 gh：
#   `workflow view <wf> --ref main` ⇒ 恒 0（= 该 workflow 在 default branch 上）
#   `run list --workflow <wf>`      ⇒ 回放 ${STUB_RUNS_DIR}/<wf> 里的 JSON（行 2 = 该腿的"最新记录"）
#   `workflow run <wf>`             ⇒ 追加到 ${STUB_DISPATCH_LOG}
# STUB_RUNS_UNREADABLE=1 ⇒ `run list` 直接失败（模拟查询不可用 ⇒ 必须 fail-open）
if [ "$1" = "workflow" ] && [ "$2" = "view" ]; then
  exit 0
fi
if [ "$1" = "run" ] && [ "$2" = "list" ]; then
  if [ -n "${STUB_RUNS_UNREADABLE:-}" ]; then
    echo "stub gh: 查询不可用（注入）" >&2
    exit 1
  fi
  wf=""
  shift 2
  while [ $# -gt 0 ]; do
    if [ "$1" = "--workflow" ]; then wf="$2"; fi
    shift
  done
  cat "${STUB_RUNS_DIR}/${wf}"
  exit 0
fi
if [ "$1" = "run" ] || { [ "$1" = "workflow" ] && [ "$2" = "run" ]; }; then
  echo "${3:-unknown}" >> "${STUB_DISPATCH_LOG}"
  exit 0
fi
echo "stub gh: unexpected args: $*" >&2
exit 127
'''

DOCKER_STUB = r'''#!/bin/bash
# 桩 docker：只认 `manifest inspect <image>`；命中 ${STUB_IMAGE_PRESENT} 时 0，否则 1
if [ "$1" = "manifest" ] && [ "$2" = "inspect" ]; then
  if [ -n "${STUB_IMAGE_PRESENT:-}" ] && [ "$3" = "${STUB_IMAGE_PRESENT}" ]; then
    exit 0
  fi
  exit 1
fi
echo "stub docker: unexpected args: $*" >&2
exit 127
'''

# 只给**构建步**用的桩 docker：记录每次调用，前 ${STUB_FAIL_TIMES} 次非零退出
# （STUB_FAIL_RC 指定退出码；124 = `timeout` 的超时码，用来演「推 ACR 挂住」）
BUILD_DOCKER_STUB = r'''#!/bin/bash
echo "$*" >> "${STUB_DOCKER_LOG}"
COUNT_FILE="${STUB_COUNT_FILE}"
n=0
[ -f "$COUNT_FILE" ] && n=$(cat "$COUNT_FILE")
n=$((n + 1))
echo "$n" > "$COUNT_FILE"
if [ "$n" -le "${STUB_FAIL_TIMES:-0}" ]; then
  echo "stub docker: 第 ${n} 次调用失败（注入）" >&2
  exit "${STUB_FAIL_RC:-1}"
fi
echo "stub docker: 第 ${n} 次调用成功"
exit 0
'''

# `timeout`：本机（macOS）**没有** coreutils 的 `timeout`（`gtimeout` 也没有），
# 且 CI 的 ubuntu-latest 一定有。⇒ 统一用一个**透传桩**包住（它只负责把 `docker` 的退出码
# 原样传出），这样本文件在任何宿主上都是**零网络、零挂钟依赖**的，而「上界被真的施加了」
# 由下面 `test_build_step_has_explicit_bound_and_retries_once` 的**逐字断言** +
# `test_timeout_wrapper_is_actually_consulted`（命令前缀断言）钉住。
TIMEOUT_STUB = r'''#!/bin/bash
# 桩 timeout：吃掉 `[OPTION] DURATION`，把剩下的命令原样执行，透传退出码
if [ "$1" = "--" ]; then shift; fi
if [ $# -gt 0 ] && [ "${1#-}" = "$1" ]; then shift; fi
exec "$@"
'''

BUILD_STEP_ANCHORS = ("--cache-from type=gha", "--cache-to type=gha,mode=max")


# ══════════════════════════════════════════════════════════════════════════
# 工具
# ══════════════════════════════════════════════════════════════════════════

def _doc(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _step(name: str, step_name: str, job: str = "build-and-deploy") -> dict:
    """取某个 step 的 **dict**（不是只取正文）—— 判据也要看它的 `env:` 块。"""
    for s in _doc(name)["jobs"][job]["steps"]:
        if s.get("name") == step_name:
            return s
    raise AssertionError(f"反空跑锚点：{name} 的 job `{job}` 里找不到 step `{step_name}`（判据已过期）")


def _body(name: str, step_name: str, job: str = "build-and-deploy") -> str:
    body = _step(name, step_name, job).get("run")
    assert isinstance(body, str) and body.strip(), (
        f"反空跑锚点：{name} 的 step `{step_name}` 没有 run 正文（判据已过期）"
    )
    return body


def _render(name: str, step_name: str, job: str = "build-and-deploy") -> str:
    """把正文渲染成可执行的纯 bash：`${{ env.X }}` 换字面量，其余 `${{ … }}` 换 `EXPR`。"""
    raw = _body(name, step_name, job)
    for key, value in (
        ("ACR_REGISTRY", "acr.example.com"), ("ACR_NAMESPACE", "ns"), ("IMAGE_NAME", "svc"),
    ):
        raw = raw.replace("${{ env.%s }}" % key, value)
    rendered = re.sub(r"\$\{\{[^}]*\}\}", "EXPR", raw)
    assert "${{" not in rendered, f"{name}: 渲染后仍有 `${{{{ … }}}}` 残留（判据已过期）"
    return rendered


def _make_bin(tmp_path: Path, scripts: dict) -> Path:
    bindir = tmp_path / "stub-bin"
    bindir.mkdir(parents=True, exist_ok=True)
    for name, content in scripts.items():
        p = bindir / name
        p.write_text(content, encoding="utf-8")
        p.chmod(0o755)
    return bindir


def _run(script: str, tmp_path: Path, *, bindir: Path, env_extra: dict, tag: str,
         cwd: Path | None = None):
    """把正文落成脚本并真跑。`cwd` 默认 = `tmp_path`；对账正文**必须**在真实 git 仓库里跑
    （它开头就 `git rev-parse HEAD`，见 `deploy-reconcile.yml` 的 `Reconcile deploys`）。"""
    script_path = tmp_path / f"{tag}.sh"
    script_path.write_text(script, encoding="utf-8")
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", **env_extra}
    return subprocess.run(["bash", str(script_path)], cwd=str(cwd or tmp_path), env=env,
                          capture_output=True, text=True, timeout=120)


# ══════════════════════════════════════════════════════════════════════════
# B-① / B-②：对账断路器（`deploy-reconcile.yml`）
# ══════════════════════════════════════════════════════════════════════════

def reconcile_script() -> str:
    """抽出 `Reconcile deploys` 的正文并把 `${{ env.X }}` 换成字面量（与既有守卫同口径）。"""
    raw = _body(RECONCILE, RECONCILE_STEP, job="reconcile")
    for key, value in (("ACR_REGISTRY", "acr.example.com"), ("ACR_NAMESPACE", "ns")):
        raw = raw.replace("${{ env.%s }}" % key, value)
    assert "${{" not in raw, f"`{RECONCILE_STEP}` 里还有没替换掉的 GitHub 表达式（判据已过期）"
    return raw


def sync_script(name: str) -> str:
    return _render(name, SYNC_STEP)


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-c", "user.email=ci@example.com", "-c", "user.name=ci",
         "-c", "commit.gpgsign=false", *args],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def make_repo(tmp_path: Path) -> dict:
    """`C1`（各腿路径就位）→ `D2`（**只**改 docs = HEAD）：与事故同形（HEAD 是 docs 提交，
    但自上次成功部署起各腿代码**没有**改动）—— 这样「跳闸」必然是**闸门**造成的，
    而不是「无漂移判据顺手拦下了」。"""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    for rel in ("backend/admin-api/a.py", "backend/ai-agent-service/a.py",
                "frontend/admin-web/a.ts", "frontend/worker-h5/a.mjs",
                "frontend/bmini-app/a.ts", "frontend/mini-app/a.ts"):
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(rel, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "code C1")
    c1 = git(repo, "rev-parse", "HEAD")
    (repo / "docs").mkdir()
    (repo / "docs" / "D.md").write_text("docs", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "docs D2 (HEAD)")
    head = git(repo, "rev-parse", "HEAD")
    assert c1 != head
    return {"repo": repo, "C1": c1, "head": head, "head7": head[:7]}


RECONCILE_WF_NAMES = ("deploy-admin-api.yml", "deploy-ai-agent-service.yml", "deploy-frontend.yml",
                      "worker-h5-publish.yml", "bmini-h5-publish.yml", "c-end-h5-publish.yml")


def run_reconcile(tmp_path: Path, repo: Path, *, head_sha: str, baseline: str | None = None,
                  conclusion: str = "success", status: str = "completed",
                  unreadable: bool = False, script_text: str | None = None, tag: str = "recon"):
    """在真实 git 仓库 + 桩 gh/docker 里真跑对账正文。

    每条腿的记录 = `[{head_sha, conclusion, status}]`，**外加**（`baseline` 非空时）
    `{baseline, "success", "completed"}` —— 后者是**漂移判据的基准**（上次成功部署）。
    · 闸门（B-①/B-②）只看 `[0]`（同 headSha 的最新一条）；
    · `baseline=None` ⇒ 漂移判据取不到基准 ⇒ 走 `?no-baseline` 的 **fail-open**（补部署）。
      「可继续 ⇒ 必须照旧补部署」这条判据要的正是这个形态：否则 HEAD 自己那条 `success`
      会被当成漂移基准 ⇒ 判「无漂移」⇒ 与闸门无关地不补部署（那会掩盖闸门本身的行为）。
    """
    bindir = _make_bin(tmp_path, {"gh": GH_STUB, "docker": DOCKER_STUB})
    runs_dir = tmp_path / f"runs-{tag}"
    runs_dir.mkdir()
    for wf in RECONCILE_WF_NAMES:
        records = ['{"headSha": "%s", "conclusion": "%s", "status": "%s"}'
                   % (head_sha, conclusion, status)]
        if baseline:
            records.append('{"headSha": "%s", "conclusion": "success", "status": "completed"}'
                           % baseline)
        (runs_dir / wf).write_text("[" + ", ".join(records) + "]", encoding="utf-8")
    dispatch_log = tmp_path / f"dispatch-{tag}.log"
    summary = tmp_path / f"summary-{tag}.md"
    env = {
        "STUB_RUNS_DIR": str(runs_dir),
        "STUB_DISPATCH_LOG": str(dispatch_log),
        "STUB_IMAGE_PRESENT": "",
        "GITHUB_STEP_SUMMARY": str(summary),
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REPOSITORY": "zhaokai-mgzn/migao",
        "GH_TOKEN": "stub-token",
    }
    if unreadable:
        env["STUB_RUNS_UNREADABLE"] = "1"
    proc = _run(script_text if script_text is not None else reconcile_script(),
                tmp_path, bindir=bindir, env_extra=env, tag=tag, cwd=repo)
    dispatches = dispatch_log.read_text(encoding="utf-8").split() if dispatch_log.exists() else []
    return proc, (summary.read_text(encoding="utf-8") if summary.exists() else ""), dispatches


# ── 行为判据（⑤ 对**这些函数**做注入式红证）───────────────────────────────

def audit_still_running_is_skipped(proc, summary, dispatches) -> None:
    assert proc.returncode == 0, f"对账正文非零退出 → {proc.stderr}\n{proc.stdout}"
    assert dispatches == [], f"同 commit 还在跑/排队时不该 dispatch（纯 churn）→ {dispatches}"
    assert "断路器跳过=6" in summary, f"应记入「跳过」而不是「补部署」→ {summary!r}"
    assert "在跑/排队" in proc.stdout and "status=in_progress" in proc.stdout, (
        f"跳过必须显式打印「已有同 commit 的 run 在跑/排队」+ 状态 → {proc.stdout}"
    )


def audit_unrecoverable_conclusion_is_skipped(proc, summary, dispatches) -> None:
    assert proc.returncode == 0, f"对账正文非零退出 → {proc.stderr}\n{proc.stdout}"
    assert dispatches == [], f"不可恢复终态不该 dispatch → {dispatches}"
    assert "断路器跳过=6" in summary, f"{summary!r}"
    assert "不可恢复的终态" in proc.stdout and "gh workflow run" in proc.stdout, (
        f"跳闸必须显式落 reason + **人工出口** → {proc.stdout}"
    )


def audit_recoverable_still_dispatches(proc, summary, dispatches) -> None:
    assert proc.returncode == 0, f"对账正文非零退出 → {proc.stderr}\n{proc.stdout}"
    assert sorted(dispatches) == sorted(RECONCILE_WF_NAMES), (
        f"允许名单内的结论（含空）必须照旧补部署（fail-open 不许被削弱）→ {dispatches}"
    )


@pytest.mark.parametrize("conclusion", FORBIDDEN_CONCLUSIONS)
def test_unrecoverable_conclusions_trip_the_breaker(tmp_path, conclusion):
    """🔴 B-①：**每一种**不可恢复的结论都跳闸（逐值参数化，不挑一个代表）。

    事故形态 = `cancelled`（被 `timeout-minutes: 45` 打死）——旧断路器只认 `failure`
    ⇒ 这条在改前**必红**（`cancelled` 那组会 dispatch 6 条腿）。
    """
    fx = make_repo(tmp_path)
    proc, summary, dispatches = run_reconcile(
        tmp_path, fx["repo"], head_sha=fx["head"], baseline=fx["C1"], conclusion=conclusion,
    )
    audit_unrecoverable_conclusion_is_skipped(proc, summary, dispatches)
    assert f"conclusion={conclusion}" in summary, f"跳闸原因必须点名结论 → {summary!r}"


def test_still_running_run_is_skipped_as_churn(tmp_path):
    """🔴 B-②：同 sha 的 run 还没跑完（`status=in_progress`）⇒ 跳过（churn 判据）。"""
    fx = make_repo(tmp_path)
    proc, summary, dispatches = run_reconcile(
        tmp_path, fx["repo"], head_sha=fx["head"], baseline=fx["C1"],
        conclusion="", status="in_progress",
    )
    audit_still_running_is_skipped(proc, summary, dispatches)


def test_recoverable_or_absent_conclusion_fails_open(tmp_path):
    """🔴 反向（**fail-open 不许被削弱**）：允许名单内的结论、以及**查不到记录**（空）
    ⇒ 照旧补部署。

    三种输入都对上同一条「可继续」路径：`success`（已成功过的同 sha）、`skipped`、`neutral`，
    外加「查询不可用」（下一节）。这条防的是「把闸门写成恒跳闸」。
    """
    # `success` **有意不在**这一组里：同 sha 已有 success 记录 ⇒ 镜像本就该在（判据 ① 管），
    # 闸门放行它、而漂移判据会把它读成基准 ⇒ 不是「闸门放行后该补部署」的形态。
    for conclusion in ("skipped", "neutral", ""):
        scratch = tmp_path / f"ok-{conclusion or 'empty'}"
        fx = make_repo(scratch)
        proc, summary, dispatches = run_reconcile(
            scratch, fx["repo"], head_sha=fx["head"],
            conclusion=conclusion, tag=f"ok-{conclusion or 'empty'}",
        )
        audit_recoverable_still_dispatches(proc, summary, dispatches)


def test_query_unavailable_fails_open(tmp_path):
    """🔴 **fail-open 的地基**（#4767/§B 明令保留）：`gh` 查询失败 ⇒ 照旧补部署 + 出声。

    这是「本检查自己出错**绝不**停掉对账」的机械形态。若有人把闸门写成
    「查不到 ⇒ 跳闸」，本判据必红。
    """
    fx = make_repo(tmp_path)
    proc, summary, dispatches = run_reconcile(
        tmp_path, fx["repo"], head_sha=fx["head"], baseline=fx["C1"],
        unreadable=True, tag="unreadable",
    )
    assert proc.returncode == 0, f"{proc.stderr}\n{proc.stdout}"
    assert sorted(dispatches) == sorted(RECONCILE_WF_NAMES), (
        f"查询不可用必须 fail-open 照旧补部署 → {dispatches}"
    )


# ══════════════════════════════════════════════════════════════════════════
# C：三条部署腿的 `Skip if already built` 加上同一道闸门
# ══════════════════════════════════════════════════════════════════════════

def sync_runs_json(head_sha: str, conclusion: str, status: str = "completed") -> str:
    return '[{"headSha": "%s", "conclusion": "%s", "status": "%s"}]' % (
        head_sha, conclusion, status)


def run_sync(name: str, tmp_path: Path, *, event_name: str, head_sha: str,
             conclusion: str = "success", status: str = "completed",
             inputs_image_tag: str = "", runs_json: str | None = None,
             script_text: str | None = None, tag: str = "sync"):
    """真跑某条腿的 `Skip if already built`（桩 gh/docker），返回 (rc, out, outputs, summary)。

    `image_present` **恒为 False**（镜像缺失）—— 这正是本闸门唯一生效的场景：
    镜像在 ⇒ 走 #2947 的老路径（既有守卫 `test_schedule_reconcile_semantics_unchanged` 管）。
    """
    bindir = _make_bin(tmp_path, {"gh": GH_STUB, "docker": DOCKER_STUB})
    # 桩 gh 按 `${STUB_RUNS_DIR}/<workflow 名>` 取该腿的记录 ⇒ 文件名 = workflow 名；
    # 每个测试各自一个 `tmp_path` ⇒ 不同参数化之间不会串。
    runs_file = tmp_path / name
    runs_file.write_text(runs_json if runs_json is not None else sync_runs_json(head_sha, conclusion, status),
                         encoding="utf-8")
    outputs_file = tmp_path / f"out-{tag}"
    outputs_file.write_text("", encoding="utf-8")
    summary_file = tmp_path / f"summary-{tag}.md"
    dispatch_log = tmp_path / f"dispatch-{tag}.log"
    env = {
        "GITHUB_SHA": head_sha,
        "GITHUB_WORKFLOW": name,
        "GITHUB_OUTPUT": str(outputs_file),
        "GITHUB_STEP_SUMMARY": str(summary_file),
        "STUB_RUNS_DIR": str(tmp_path),
        "STUB_DISPATCH_LOG": str(dispatch_log),
        "EVENT_NAME": event_name,
        "INPUT_IMAGE_TAG": (
            f"acr.example.com/ns/svc:{inputs_image_tag}" if inputs_image_tag else ""
        ),
        "STUB_IMAGE_PRESENT": "",
    }
    script = script_text if script_text is not None else sync_script(name)
    proc = _run(script, tmp_path, bindir=bindir, env_extra=env, tag=tag)
    outputs = {}
    for line in outputs_file.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            outputs[k] = v
    return proc, proc.stdout + proc.stderr, outputs, (
        summary_file.read_text(encoding="utf-8") if summary_file.exists() else "")


def audit_sync_skips(rc, out, outputs, summary) -> None:
    """「不可恢复终态 ⇒ 跳过」的**全部**可判面（⑤ 对**这个函数**做注入式红证）。

    `rc` = `subprocess.CompletedProcess`（`run_sync` 的返回值原样传进来）。
    """
    assert rc.returncode == 0, f"跳过 ≠ 失败（应正常退出）→ rc={rc.returncode}\n{out}"
    assert outputs.get("skip") == "true", (
        f"不可恢复终态必须写 skip=true（否则照旧全量构建 ⇒ 挂死的 commit 被自己的 cron 反复重试）"
        f"→ outputs={outputs!r}\n{out}"
    )
    assert "不可恢复的终态" in out and "gh workflow run" in out, (
        f"跳过必须**显式**打印理由 + 人工出口（不许静默）→ {out}"
    )
    assert "不可恢复" in summary, f"跳闸原因必须落 `$GITHUB_STEP_SUMMARY` → {summary!r}"


@pytest.mark.parametrize("wf", SYNC_LEGS)
@pytest.mark.parametrize("conclusion", ("failure", "cancelled", "timed_out", "stale"))
def test_sync_leg_skips_on_unrecoverable_conclusion(wf, conclusion, tmp_path):
    """🔴 C：三条腿 × 四种不可恢复结论 ⇒ 都 `skip=true` + 显式理由 + summary。

    「镜像缺失」是**本闸门唯一生效的场景**（镜像在 ⇒ 走 #2947 的老路径）。改前（没有本闸门）
    这四种结论下都会写 `skip=false` ⇒ 全量重构建 ⇒ 挂死的 commit 被自己的 cron
    （`8,28,48` / `4,24,44` / `12,32,52`）无限重试。本判据在改前**必红**。
    """
    sha = "abcdef1234567890"
    rc, out, outputs, summary = run_sync(
        wf, tmp_path, event_name="workflow_dispatch", head_sha=sha,
        conclusion=conclusion, tag=f"{wf}-{conclusion}",
    )
    audit_sync_skips(rc, out, outputs, summary)
    assert conclusion in (out + summary), f"必须点名是哪一种结论 → {out}"


@pytest.mark.parametrize("wf", SYNC_LEGS)
def test_sync_leg_skips_while_same_commit_is_still_running(wf, tmp_path):
    """🔴 C（churn 面）：同 sha 的 run 还在跑/排队 ⇒ 也 `skip=true`。"""
    sha = "abcdef1234567890"
    rc, out, outputs, summary = run_sync(
        wf, tmp_path, event_name="workflow_dispatch", head_sha=sha,
        conclusion="", status="queued", tag=f"{wf}-queued",
    )
    audit_sync_skips(rc, out, outputs, summary)


@pytest.mark.parametrize("wf", SYNC_LEGS)
def test_sync_leg_still_builds_when_last_run_is_recoverable(wf, tmp_path):
    """🔴 反向（承重）：最近一次记录**可继续**（含查不到记录 = 空）⇒ 照旧构建（`skip=false`）。

    这条保证闸门**不是恒跳闸**：镜像缺失 + 无同 sha 记录 = 事故里「push 触发被吞 ⇒ 该补一次」
    的正规路径，必须继续可用（否则「部署触发被吞」会静默不部署）。
    """
    sha = "abcdef1234567890"
    for conclusion, status in (("success", "completed"), ("skipped", "completed"),
                               ("neutral", "completed"), ("", "completed")):
        rc, out, outputs, _summary = run_sync(
            wf, tmp_path, event_name="workflow_dispatch", head_sha=sha,
            conclusion=conclusion, status=status, tag=f"{wf}-recoverable-{conclusion or 'empty'}",
        )
        assert rc.returncode == 0, f"{wf}: rc={rc.returncode}\n{out}"
        assert outputs.get("skip") == "false", (
            f"{wf}: 结论={conclusion or '(空)'} 属允许名单 ⇒ 必须 skip=false（照常构建部署），"
            f"实际 {outputs!r}\n{out}"
        )


@pytest.mark.parametrize("wf", SYNC_LEGS)
def test_sync_leg_query_unavailable_fails_open(wf, tmp_path):
    """🔴 fail-open：`gh` 查询失败 ⇒ **不跳闸**（照旧构建），且不许崩。

    这是与 B 同一口径的保留语义：本检查自己出错绝不停掉部署。
    """
    sha = "abcdef1234567890"
    rc, out, outputs, _summary = run_sync(
        wf, tmp_path, event_name="workflow_dispatch", head_sha=sha,
        runs_json='[{"headSha": "other", "conclusion": "cancelled", "status": "completed"}]',
        script_text=None, tag=f"{wf}-noquery",
    )
    assert rc.returncode == 0, f"{wf}: rc={rc.returncode}\n{out}"
    assert outputs.get("skip") == "false", (
        f"{wf}: 查不到**本 sha** 的记录 ⇒ fail-open（照旧构建），实际 {outputs!r}\n{out}"
    )

    # 真·查询失败（桩 gh 非零 + 空输出）
    bindir = _make_bin(tmp_path / "unreadable", {"gh": GH_STUB, "docker": DOCKER_STUB})
    outputs_file = tmp_path / "out-unreadable"
    outputs_file.write_text("", encoding="utf-8")
    env = {
        "GITHUB_SHA": sha, "GITHUB_WORKFLOW": wf, "GITHUB_OUTPUT": str(outputs_file),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "s.md"),
        "STUB_RUNS_DIR": str(tmp_path), "STUB_RUNS_UNREADABLE": "1",
        "STUB_DISPATCH_LOG": str(tmp_path / "d.log"),
        "EVENT_NAME": "workflow_dispatch", "INPUT_IMAGE_TAG": "", "STUB_IMAGE_PRESENT": "",
    }
    proc = _run(sync_script(wf), tmp_path, bindir=bindir, env_extra=env, tag=f"{wf}-unreadable")
    got = dict(ln.split("=", 1) for ln in outputs_file.read_text(encoding="utf-8").splitlines() if "=" in ln)
    assert proc.returncode == 0, f"{wf}: 查询失败不许让 step 崩 → {proc.stderr}"
    assert got.get("skip") == "false", (
        f"{wf}: `gh` 查询失败必须 fail-open（照旧构建）→ {got!r}\n{proc.stdout}{proc.stderr}"
    )


@pytest.mark.parametrize("wf", SYNC_LEGS)
def test_explicit_rollback_never_skips_even_with_unrecoverable_last_run(wf, tmp_path):
    """🔴 **边界（#4852 的逃生口）**：`workflow_dispatch -f image_tag=<tag>` ⇒ **永远放行**。

    ⚠️ 这条比既有守卫更严：即使「同 sha 最近一次结论不可恢复」，显式回滚也**必须**放行 ——
    回滚是人工接口，是跳闸之后**唯一**能恢复现场的动作；跳闸把它挡住 = 把机制变成黑箱。
    """
    sha = "abcdef1234567890"
    rc, out, outputs, _summary = run_sync(
        wf, tmp_path, event_name="workflow_dispatch", head_sha=sha,
        conclusion="cancelled", inputs_image_tag="sha-0000000", tag=f"{wf}-rollback",
    )
    assert rc.returncode == 0, f"{wf}: rc={rc.returncode}\n{out}"
    assert outputs.get("skip") == "false", (
        f"{wf}: MODE=rollback 必须 skip=false（不可恢复终态**不许**挡住显式回滚，#4852）"
        f"→ {outputs!r}\n{out}"
    )
    assert "回滚" in out, f"{wf}: 回滚路径必须说明为什么没跳过 → {out}"


# ══════════════════════════════════════════════════════════════════════════
# A：`Build and push` 的显式上界 + 一次重试 + 可归因报错
# ══════════════════════════════════════════════════════════════════════════

BUILD_ENV_STUB = {
    "PUSH_TIMEOUT_SECS": "3",
    "RETRY_SLEEP_SECS": "0",
}


def run_build(name: str, tmp_path: Path, *, fail_times: int, fail_rc: int = 1, tag: str = "build"):
    """真跑构建步（桩 docker/timeout）⇒ (rc, out, docker 调用日志)。

    `fail_times=1` = 第一次失败、第二次成功（**重试**路径）；
    `fail_times=9` = 两次都失败（**报错**路径）；
    `fail_rc=124` = 与 `timeout` 超时同码（演「推 ACR 挂住」）。
    """
    bindir = _make_bin(tmp_path, {"docker": BUILD_DOCKER_STUB, "timeout": TIMEOUT_STUB,
                                  "gh": GH_STUB})
    log = tmp_path / f"docker-{tag}.log"
    count = tmp_path / f"count-{tag}"
    env = {
        **BUILD_ENV_STUB,
        "STUB_DOCKER_LOG": str(log),
        "STUB_COUNT_FILE": str(count),
        "STUB_FAIL_TIMES": str(fail_times),
        "STUB_FAIL_RC": str(fail_rc),
        "GITHUB_ENV": str(tmp_path / f"genv-{tag}"),
        "GITHUB_SHA": "abcdef1234567890",
    }
    proc = _run(_render(name, BUILD_STEP[name]), tmp_path, bindir=bindir, env_extra=env, tag=tag)
    return proc, proc.stdout + proc.stderr, (log.read_text(encoding="utf-8") if log.exists() else "")


@pytest.mark.parametrize("wf", DEPLOY_WORKFLOWS)
def test_build_step_retries_once_after_first_failure(wf, tmp_path):
    """🔴 A-①：第 1 次失败 ⇒ **重试 1 次**且第 2 次成功 ⇒ step 成功（rc=0）。

    改前没有重试：一次推送抖动 = 该 commit 白挂 40min（事故读数）。
    """
    proc, out, log = run_build(wf, tmp_path, fail_times=1)
    assert proc.returncode == 0, f"{wf}: 第 1 次失败后重试成功应 rc=0（去做一次重试！）→ {out}"
    assert "重试 1 次" in out or "第 2 次尝试成功" in out, f"{wf}: 必须打印重试动作 → {out}"
    calls = [ln for ln in log.splitlines() if ln.strip()]
    assert len(calls) >= 2, f"{wf}: docker 只被调用 {len(calls)} 次 ⇒ 没有重试 → {log!r}"


@pytest.mark.parametrize("wf", DEPLOY_WORKFLOWS)
def test_build_step_exhausted_retries_fail_loud_and_nonzero(wf, tmp_path):
    """🔴 A-②：两次都不成 ⇒ **非零退出** + `::error::` **点名卡在哪一步**（推送到 ACR 挂住）。

    「40 分钟零输出 + 一个 cancelled」的坏形态被换成**可归因**的失败：结论不再是
    「不知道挂在哪」，而是「推送到 ACR 挂住了」。
    """
    proc, out, log = run_build(wf, tmp_path, fail_times=9, fail_rc=124)
    assert proc.returncode != 0, f"{wf}: 两次都失败必须非零退出（否则会被当成部署成功）→ {out}"
    assert "::error::" in out, f"{wf}: 必须用 `::error::` 让失败在 run 页面上可归因 → {out}"
    assert "推送到 ACR 挂住" in out, (
        f"{wf}: 超时（rc=124）时必须**点名**卡在「推送到 ACR」（issue #5814 的挂点）→ {out}"
    )
    assert "第 1 次" in out and "第 2 次" in out, f"{wf}: 两次尝试的读数都要有 → {out}"


@pytest.mark.parametrize("wf", DEPLOY_WORKFLOWS)
def test_build_step_has_explicit_bound_and_retries_once(wf):
    """🔴 A-③（**上界本身**的机械锁）：正文必须**真的**在命令前面挂 `timeout <上界>`。

    ⚠️ 这条是「显式上界」这个**性质**的判据 —— 桩化的行为判据证明不了它（宿主没有 coreutils
    `timeout` 时会被跳过）⇒ 用逐字断言钉住：① 出现 `timeout "${PUSH_TIMEOUT_SECS}"` 前缀；
    ② 上界 × 2 **明显小于** job 的 `timeout-minutes`（否则仍会被 job 打死 ⇒ cancelled ⇒ 循环）。
    """
    body = _render(wf, BUILD_STEP[wf])
    assert 'timeout "${PUSH_TIMEOUT_SECS}"' in body, (
        f"{wf}: 构建/推送命令前必须挂 `timeout ${{PUSH_TIMEOUT_SECS}}`（显式上界）—— "
        "否则又会「挂 40min 被 job 超时打死」（issue #5814 A）"
    )
    # `timeout` 必须包住 `docker`（而不是包住别的命令）
    wrapped = re.findall(r'timeout "\$\{PUSH_TIMEOUT_SECS\}"\s+(\S+)', body)
    assert wrapped, f"{wf}: 找不到 `timeout … docker` 的调用点（判据已过期）"
    assert set(wrapped) == {"docker"}, (
        f"{wf}: `timeout` 包的应是 docker 命令（实得 {sorted(set(wrapped))}）"
    )
    env = _step(wf, BUILD_STEP[wf]).get("env") or {}
    bound_secs = int(str(env.get("PUSH_TIMEOUT_SECS", "")))
    job_timeout_mins = int(_doc(wf)["jobs"]["build-and-deploy"]["timeout-minutes"])
    assert bound_secs * 2 < job_timeout_mins * 60, (
        f"{wf}: 最坏墙钟 = 2 × {bound_secs}s = {bound_secs * 2 // 60}min，不满足「明显小于 job 的 "
        f"timeout-minutes={job_timeout_mins}min（= {job_timeout_mins * 60}s）」"
        "（否则 job 仍会先超时 ⇒ cancelled ⇒ 无限循环）"
    )
    # 重试必须**恰好一次**：`attempt_build_and_push` 的两个调用点（首次 + 重试 1 次）；
    # 三次以上 = 把抖动放大成占锁（`cancel-in-progress: false` 下尤其糟）。
    assert body.count("if attempt_build_and_push; then") == 2, (
        f"{wf}: 期望「首次 + 重试 1 次」两个调用点，实得 {body.count('if attempt_build_and_push; then')}"
    )
    assert "重试 1 次" in body, f"{wf}: 重试必须被显式命名（可读性 = 可维护性）"
    assert "第 2 次尝试成功" in body, f"{wf}: 第二次成功的读数必须在（否则看不出重试发生没发生）"


@pytest.mark.parametrize("wf", DEPLOY_WORKFLOWS)
def test_build_step_keeps_existing_semantics(wf):
    """🔴 **不降门禁 / 不砍护栏**：既有语义逐字保留。

    · ai-agent 腿的 buildx 语义（`--provenance=false` / `--cache-from` / `--cache-to type=gha`）
      一字不动（**注意**：`exporting cache` 从未出现在事故 run 里 ⇒ 本单**不主张**改 cache）；
    · 三条腿的 `if:` 条件、镜像名/两个 tag、`--push`、`IMAGE_FULL` 的导出全保留；
    · **不新增任何 `secrets.*` 引用**（`Danger Scan` 会 BLOCK）。
    """
    body = _body(wf, BUILD_STEP[wf])
    cond = str(_step(wf, BUILD_STEP[wf]).get("if", ""))
    assert cond == "steps.tag.outputs.MODE == 'build' && steps.sync.outputs.skip != 'true'", (
        f"{wf}: 构建步的 `if:` 被改动了（当前 {cond!r}）"
    )
    assert "--push" in body or "docker push" in body, f"{wf}: 推送动作不见了"
    assert ":latest" in body, f"{wf}: `latest` tag 必须照推（既有语义）"
    if wf == "deploy-ai-agent-service.yml":
        for anchor in BUILD_STEP_ANCHORS + ("--provenance=false", "--build-arg PIP_INDEX_URL="):
            assert anchor in body, f"{wf}: 既有 buildx 语义 `{anchor}` 被删/改动了"
    if wf == "deploy-frontend.yml":
        for anchor in ("NEXT_PUBLIC_API_BASE_URL", "NEXT_PUBLIC_AI_API_BASE_URL",
                       "NEXT_PUBLIC_COOKIE_DOMAIN"):
            assert anchor in body, f"{wf}: 构建期 baked 的 `{anchor}` 丢了"
    added_secrets = set(re.findall(r"secrets\.([A-Za-z0-9_]+)", body))
    original = set(re.findall(
        r"secrets\.([A-Za-z0-9_]+)",
        subprocess.run(["git", "show", "origin/main:.github/workflows/" + wf],
                       cwd=str(REPO_ROOT), capture_output=True, text=True).stdout,
    ))
    assert added_secrets <= original, (
        f"{wf}: 新增了 secret 引用 {sorted(added_secrets - original)}（Danger Scan 会 BLOCK）"
    )


# ══════════════════════════════════════════════════════════════════════════
# ③ 类级元守卫 + 三条注入式红证
# ══════════════════════════════════════════════════════════════════════════

CASE_PATTERN = 'success | skipped | neutral) is_recoverable="true" ;;'
# 允许名单出现处的**逐字**左界（两处的变量名不同 ⇒ 只锚「`in` + 换行 + 空格 + success」）
CASE_HEAD = re.compile(r'case "\$([A-Za-z_]+)" in\s*\n\s*')


def allowed_conclusions(text: str) -> tuple[set[str], str]:
    """从「允许名单」形态里**现取**可继续的结论集合 + `case` 的主语变量名。

    这是 ③ 的机械读数：**「哪些结论能继续」是被枚举出来的**（而不是「哪些要跳闸」）。
    """
    assert CASE_PATTERN in text, (
        f"找不到允许名单逐字形态 `{CASE_PATTERN}` ⇒ 断路器不是「允许名单」形态"
        f"（黑名单形态在 GitHub 新增结论时会**静默退回 fail-open** = #5814 原样复发）"
    )
    head = CASE_HEAD.search(text)
    assert head, "找不到 `case \"$<变量>\" in` 的允许名单头（判据已过期）"
    subject = head.group(1)
    block = text[head.end():text.index(CASE_PATTERN) + len(CASE_PATTERN)]
    allowed = {t for t in re.findall(r"\b([a-z_]+)(?=\s*[)|])", block)}
    return allowed, subject


def audit_allowlist_form(text: str, what: str) -> None:
    """类级元守卫：断路器必须落成**允许名单**形态（三个面，缺一即红）。

    1. **允许名单**：出现逐字形态 `success | skipped | neutral) is_recoverable="true"`，
       且**现取的允许集合** == {success, skipped, neutral} —— 「哪些能继续」是**枚举出来**的；
    2. **禁止名单侧**：`failure` / `cancelled` / `timed_out` / `startup_failure` /
       `action_required` / `stale` **一律不出现**在可继续侧，也**不得**以 `= "<结论>"` 的
       比较形态出现在正文里 —— 它们由**兜底分支**接住；
    3. **决定式形态**：`[ "$is_recoverable" != "true" ]` 出现（判定由那个布尔量驱动）。
       一个没被任何分支赋值的变量会让 ① 自然失效；而**非枚举的**新结论必落兜底 ⇒ 默认跳闸。
    """
    allowed, _subject = allowed_conclusions(text)
    assert allowed == set(ALLOWED_CONCLUSIONS), (
        f"{what}: 可继续的结论集合 = {sorted(allowed)}，期望 {sorted(ALLOWED_CONCLUSIONS)}"
        f"（多一个 = 把不可恢复的结论放行了；少一个 = 把可恢复的结论挡住了）"
    )
    for bad in FORBIDDEN_CONCLUSIONS:
        assert bad not in allowed, f"{what}: `{bad}` 出现在**可继续侧**（黑名单形态，#5814 明确否决）"
        assert not re.search(rf'=\s*"{bad}"', text), (
            f"{what}: 正文里出现 `= \"{bad}\"` 的**结论比较** ⇒ 黑名单形态"
            f"（正确形态 = 只在允许名单里枚举「能继续的」，其余由兜底分支跳闸）"
        )
    assert '*)$' in text or '*)\n' in text or re.search(r"^\s*\*\)", text, re.M), (
        f"{what}: 允许名单缺 `*`（兜底）分支 ⇒ 未被枚举的结论会**静默穿过**，而不是默认跳闸"
    )
    assert '[ "$is_recoverable" != "true" ]' in text, (
        f"{what}: 跳闸条件必须由 `is_recoverable` 布尔量驱动（= 允许名单的判定结果）"
    )


def test_breaker_is_allowlist_shaped_in_both_places():
    """🔴 ③ 类级元守卫（承重）：**两处**（对账 + 三条部署腿）都必须是允许名单形态。

    为什么两处都要：`deploy-reconcile.yml` 的对账与三条部署腿**各自的 `on.schedule`**
    是两个**独立**的 retry 入口（事故里两条路都在重试同一个挂死的 commit）。
    只把一处改成允许名单 ⇒ 另一处照旧 fail-open ⇒ bug 未修。
    """
    audit_allowlist_form(reconcile_script(), "deploy-reconcile.yml::reconcile_one")
    for wf in SYNC_LEGS:
        audit_allowlist_form(sync_script(wf), f"{wf}::{SYNC_STEP}")


def test_allowlist_guard_red_on_blacklist_form():
    """🔴 红证②（**元守卫的判别力**）：把实现改成**黑名单**形态 ⇒ ③ 必红。

    注入的是把「允许名单」那一支换成**逐字黑名单**（`failure)` / `cancelled)` ⇒ `*) is_recoverable="true"`），
    即 #5814 明确否决的形态。证明 ③ 不是空断言。
    """
    good = reconcile_script()
    audit_allowlist_form(good, "基线")  # 前提：真文本先绿
    case_block = (
        '            if [ -n "$last_conclusion" ]; then\n'
        '              case "$last_conclusion" in\n'
        '                failure) is_recoverable="false" ;;\n'
        '                cancelled) is_recoverable="false" ;;\n'
        '                *) is_recoverable="true" ;;\n'
        '              esac\n'
        '            fi\n'
    )
    start = good.index('is_recoverable="true"\n')
    end = good.index('if [ "$is_recoverable" != "true" ]; then')
    blacklist = good[:start] + case_block + good[end:]
    assert blacklist != good, "注入未生效（判据自证）"
    assert CASE_PATTERN not in blacklist, "注入未生效：允许名单形态仍在"
    with pytest.raises((AssertionError, ValueError)):
        audit_allowlist_form(blacklist, "黑名单注入")
    # 加上「只认 failure」的**降低覆盖**形态（少了 cancelled）⇒ 同样必红
    fewer = blacklist.replace('                cancelled) is_recoverable="false" ;;\n', "")
    assert fewer != blacklist
    with pytest.raises((AssertionError, ValueError)):
        audit_allowlist_form(fewer, "只认 failure 注入")


def test_sync_allowlist_guard_red_on_blacklist_form():
    """🔴 红证②-b：**部署腿**那一处同样 —— 黑名单形态 ⇒ ③ 必红。"""
    wf = "deploy-admin-api.yml"
    good = sync_script(wf)
    audit_allowlist_form(good, f"{wf} 基线")
    start = good.index('is_recoverable="true"\n')
    end = good.index('if [ "$is_recoverable" != "true" ]; then')
    blacklist = good[:start] + (
        '            is_recoverable="false"\n'
        '            if [ "$LAST_CONCLUSION" = "success" ] || [ "$LAST_CONCLUSION" = "skipped" ] '
        '|| [ "$LAST_CONCLUSION" = "neutral" ]; then\n'
        '              is_recoverable="true"\n'
        '            fi\n'
    ) + good[end:]
    assert blacklist != good, "注入未生效（判据自证）"
    # 形态 1：把「能继续」写成**比较式**（没有 `case` 允许名单）⇒ 必红
    with pytest.raises((AssertionError, ValueError)):
        audit_allowlist_form(blacklist, f"{wf} 比较式注入")
    # 形态 2：黑名单 case（`failure)` / `cancelled)` ⇒ 其余 `*)` 放行）⇒ 必红
    case_block = (
        '            if [ -n "$LAST_CONCLUSION" ]; then\n'
        '              case "$LAST_CONCLUSION" in\n'
        '                failure) is_recoverable="false" ;;\n'
        '                cancelled) is_recoverable="false" ;;\n'
        '                *) is_recoverable="true" ;;\n'
        '              esac\n'
        '            fi\n'
    )
    blacklist2 = good[:start] + case_block + good[end:]
    assert blacklist2 != good and CASE_PATTERN not in blacklist2
    with pytest.raises((AssertionError, ValueError)):
        audit_allowlist_form(blacklist2, f"{wf} 黑名单注入")


def test_comment_only_edit_does_not_trip_any_criterion():
    """🔴 对照读数：**只改注释** ⇒ 全部判据照旧（行为不变）。

    防空断言的**负控**：若「只改注释」也能让判据变红，说明判据在断言字面文本而不是行为。
    （③ 的 `audit_allowlist_form` 读的是**代码面**：把注释剥掉后两个面都必须与基线一致；
    ② 的执行式判据在同一输入下必须给出同一输出。）
    """
    def strip_comment_lines(text: str) -> str:
        return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))

    good = reconcile_script()
    audit_allowlist_form(good, "基线")
    bare = strip_comment_lines(good)
    audit_allowlist_form(bare, "剥掉整行注释后")
    assert bare != good, "注入未生效（判据自证：注释确实存在）"

    # 只改注释（把注释文本整个换掉）⇒ 行为判据的读数必须**逐字不变**。
    # ⚠️ 这里**不用**朴素的 `#` 截断正则：本仓 `tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py`
    #    把「未先清空字符串就按 `#` 截断」判为假绿形态（字符串里的 `#` 会吃掉行尾）⇒ 逐行判前缀。
    retext = "".join(
        "# (注释已改写 —— 负控)\n" if ln.lstrip().startswith("#") else ln
        for ln in good.splitlines(keepends=True)
    )
    assert retext != good and strip_comment_lines(retext) == strip_comment_lines(good), (
        "负控自证失败：注释改写没有保持**代码面**逐字一致"
    )
    audit_allowlist_form(retext, "注释改写后")


def test_break_criterion_has_discriminating_power(tmp_path):
    """🔴 红证①（**最承重的那条**）：把断路器改回「**只认 failure**」（= 改前形态）⇒ 判据必红。

    注入 = 把允许名单那一支短路掉，换成逐字对应改前的
    `if [ "$last" = "failure" ]; then … 不补 …`。在**同一输入**（`cancelled` + 镜像缺失）下：
    · 改后：0 dispatch（跳闸）；
    · 改前：6 dispatch（照旧补部署 —— 这就是无限循环的入口）。
    """
    good = reconcile_script()
    # 逐字还原**改前的判定** = 只认 `failure`（用现役变量名 `$last_conclusion`）。
    # bash 不在乎缩进 ⇒ 锚点只取子串、不硬编码缩进（YAML 块标量会被去缩进）。
    pre_fix = (
        'is_recoverable="true"\n'
        'if [ "$last_conclusion" = "failure" ]; then\n'
        '  is_recoverable="false"\n'
        'fi\n'
    )
    start = good.index('is_recoverable="true"')
    end = good.index('if [ "$is_recoverable" != "true" ]; then')
    broken = good[:start] + pre_fix + good[end:]
    assert broken != good, "注入未生效（判据自证）"
    assert CASE_PATTERN not in broken, "注入未生效：允许名单形态没被移除"

    fx = make_repo(tmp_path)
    proc, summary, dispatches = run_reconcile(
        tmp_path, fx["repo"], head_sha=fx["head"],
        conclusion="cancelled", script_text=broken, tag="prefix",
    )
    assert sorted(dispatches) == sorted(RECONCILE_WF_NAMES), (
        f"改回「只认 failure」后 `cancelled` 竟然没补部署 ⇒ 注入失效（红证无效）→ {dispatches}"
    )
    assert "断路器跳过=6" not in summary, f"改前形态不该记「跳过」→ {summary!r}"
    with pytest.raises(AssertionError):
        audit_unrecoverable_conclusion_is_skipped(proc, summary, dispatches)


def test_cancelled_criterion_has_discriminating_power(tmp_path):
    """🔴 红证①-b：把允许名单**收窄**成「只认 success」（= 把 cancelled 之外的结论也跳闸）
    ⇒ 反向判据（允许名单内的结论必须照常补部署）必红。

    证明 `test_recoverable_or_absent_conclusion_fails_open` 有判别力：它真的在验「哪些能继续」，
    而不是「什么都没改所以绿」。
    """
    good = reconcile_script()
    narrowed = good.replace(
        CASE_PATTERN, 'success) is_recoverable="true" ;;'
    )
    assert narrowed != good, "注入未生效（判据自证）"
    fx = make_repo(tmp_path)
    proc, summary, dispatches = run_reconcile(
        tmp_path, fx["repo"], head_sha=fx["head"], baseline=fx["C1"],
        conclusion="neutral", script_text=narrowed, tag="narrowed",
    )
    assert dispatches == [], f"收窄成只认 success 后 `neutral` 竟仍补部署 ⇒ 注入失效 → {dispatches}"
    with pytest.raises(AssertionError):
        audit_recoverable_still_dispatches(proc, summary, dispatches)


def test_sync_criterion_has_discriminating_power(tmp_path):
    """🔴 红证①-c：把**部署腿**的闸门改回改前形态（无条件 `skip=false`）⇒ C 的判据必红。"""
    wf = "deploy-admin-api.yml"
    good = sync_script(wf)
    # 改前形态 = **没有这道闸门** ⇒ 镜像缺失一律全量构建（`skip=false`）。
    # 最小等价注入 = 把闸门判定短路成恒假 ⇒ 落到下面的 `else`（`skip=false`）；
    # 与缩进无关（YAML 块标量会被去缩进 ⇒ 硬编码缩进的切片锚点会失效）。
    broken = good.replace('if [ "$is_recoverable" != "true" ]; then', "if false; then", 1)
    assert broken != good, "注入未生效（判据自证）"
    assert "if false; then" in broken, "注入未生效：闸门没被短路"
    assert broken != good, "注入未生效（判据自证）"
    sha = "abcdef1234567890"
    rc, out, outputs, summary = run_sync(
        wf, tmp_path, event_name="workflow_dispatch", head_sha=sha,
        conclusion="cancelled", script_text=broken, tag="sync-prefix",
    )
    assert outputs.get("skip") == "false", (
        f"改前形态应照旧全量构建（skip=false）—— 若这里不是 false，说明注入没生效 → {outputs!r}\n{out}"
    )
    with pytest.raises(AssertionError):
        audit_sync_skips(rc, out, outputs, summary)


def test_build_retry_criterion_has_discriminating_power(tmp_path):
    """🔴 红证①-d：把构建步的重试**去掉**（只做一次）⇒ A-① 必红。

    「重试」是 A 的核心动作；去掉它 ⇒ 一次推送抖动仍 = 该 commit 白挂 40min。
    """
    wf = "deploy-admin-api.yml"
    good = _render(wf, BUILD_STEP[wf])
    # 改前形态 = **只有一次尝试**（`set -euo pipefail` ⇒ 失败即整体非零退出）。
    first = good.index("if attempt_build_and_push; then")
    broken = good[:first] + "attempt_build_and_push\n"
    assert broken != good, "注入未生效（判据自证）"
    assert "if attempt_build_and_push; then" not in broken, (
        "注入未生效：重试调用点仍在（改前形态应只有一次尝试）"
    )

    bindir = _make_bin(tmp_path, {"docker": BUILD_DOCKER_STUB, "timeout": TIMEOUT_STUB})
    log = tmp_path / "docker-pre.log"
    env = {**BUILD_ENV_STUB, "STUB_DOCKER_LOG": str(log),
           "STUB_COUNT_FILE": str(tmp_path / "cnt-pre"), "STUB_FAIL_TIMES": "1",
           "STUB_FAIL_RC": "1", "GITHUB_ENV": str(tmp_path / "genv-pre")}
    proc = _run(broken, tmp_path, bindir=bindir, env_extra=env, tag="build-prefix")
    calls = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(calls) == 1, f"改前形态应只推一次，实得 {len(calls)} 次 ⇒ 注入失效"
    assert proc.returncode != 0, "改前形态第 1 次失败即整体失败（无重试）"


def test_timeout_wrapper_is_actually_consulted(tmp_path):
    """🔴 A-④：`timeout` **真的**被调用（不是写了个没人用的变量）。

    用桩 `timeout` 把它的 argv 落到一个文件里 ⇒ 断言**每个** docker 调用都被 `timeout` 包着。
    这条补上了「宿主没有 coreutils `timeout` 时行为判据会退化」的缺口。
    """
    bindir = tmp_path / "stub-bin-timeout"
    bindir.mkdir(parents=True, exist_ok=True)
    argv_log = tmp_path / "timeout-argv.log"
    (bindir / "timeout").write_text(
        "#!/bin/bash\n"
        f'echo "$*" >> "{argv_log}"\n'
        'if [ "$1" = "--" ]; then shift; fi\n'
        'if [ $# -gt 0 ] && [ "${1#-}" = "$1" ]; then shift; fi\n'
        'exec "$@"\n',
        encoding="utf-8",
    )
    (bindir / "timeout").chmod(0o755)
    (bindir / "docker").write_text(BUILD_DOCKER_STUB, encoding="utf-8")
    (bindir / "docker").chmod(0o755)

    env = {**BUILD_ENV_STUB, "STUB_DOCKER_LOG": str(tmp_path / "d2.log"),
           "STUB_COUNT_FILE": str(tmp_path / "c2"), "STUB_FAIL_TIMES": "0",
           "GITHUB_ENV": str(tmp_path / "g2")}
    proc = _run(_render("deploy-admin-api.yml", BUILD_STEP["deploy-admin-api.yml"]),
                tmp_path, bindir=bindir, env_extra=env, tag="build-timeout")
    assert proc.returncode == 0, f"{proc.stdout}{proc.stderr}"
    lines = [ln for ln in argv_log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines, "`timeout` 一次都没被调用 ⇒ 显式上界是纸面的（判据已过期）"
    assert all(ln.startswith(f"{BUILD_ENV_STUB['PUSH_TIMEOUT_SECS']} docker") for ln in lines), (
        f"每次调用都应是 `timeout <上界> docker …`，实得 {lines}"
    )
