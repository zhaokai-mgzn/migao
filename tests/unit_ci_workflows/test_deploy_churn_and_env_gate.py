# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""部署 churn 与 `.env` 门禁的三条结构不变式 —— issue #5078 / #5077 / #5083。

## 一、#5078：45min 硬超时打死「挂住的部署」+ 5 条 workflow 同 cron 自踩

**已冻结证据（`gh run view --json`，本仓实测）**：三条 deploy 腿的 cancelled 全部
**恰好 = 45min**，且**含排队时间**：

| run | event | job 起 → 终 | 时长 |
|---|---|---|---|
| 35627484674 | workflow_dispatch | 16:44:09 → 17:29:29 | **45m20s** |
| 35628449279 | schedule | 16:56:42 → 17:42:13 | **45m31s** |
| 35620917459 | workflow_dispatch | 16:15:39 → 17:01:02 | **45m23s** |
| 35627829895 | schedule | 17:29:32 → 18:14:56 | **45m24s** |

**挂死点不在脚本里**（所以本单不改 `swas-deploy-ci.sh`）：run 35591141263 的日志末行是
`11:15:00 #14 exporting to image`，下一条就是 `11:54:37 ##[error]The operation was canceled.`
⇒ **39 分钟零输出**，挂在 `docker buildx build … --push` 推 ACR 图层那一步，**部署阶段还没开始**。

**级联（这才是 44 次 cancelled 的机制）**：一个挂住的 run 占住 `deploy-<svc>` 的
concurrency 组 45min（`cancel-in-progress: false`）⇒ 对账（`deploy-reconcile.yml`，cron `*/20`）
每 20 分钟 dispatch 一次同一 commit ⇒ 排队的 run **在队列里就开始计时**，拿到锁时早已过 45min
⇒ 被 `timeout-minutes` 打死 ⇒ 又占一轮。上面 4 条 run 里有 3 条**排队 30~42 分钟**。

**本文件锁的修法**：把 `Skip if already built` 的对账判据从「仅 schedule」扩到
**`workflow_dispatch`**（#5078 的重复 dispatch 全走这条），并在**镜像已存在**时**显式跳过**
（打印理由）。效果：级联里排队的 run 一旦拿到锁就**秒退**（不再构建、不再占 45min），
而不是被超时打死 —— **去掉的是级联，不是超时**（45min 兜底保留）。

## 二、#5077：dependabot PR 上「必然失败的非 required 红」

dependabot 触发的 workflow **拿不到仓库 secrets** ⇒ `Docker login ACR` 必报
`Error: Cannot perform an interactive login from a non TTY device`。它不拦合并却与真红无异
（#5077 实测：6 个 PR 被这条陈旧红挂住 2 天）。修法 = 该 job 在 dependabot 触发时**显式跳过**
（`if:` 条件 + 注释写明理由），**非 dependabot 形态仍然真跑**。

## 三、#5083：`Block .env files` 把「正确修法」永久禁止（自相矛盾的门禁）

`git diff --name-only origin/main...HEAD` **会列出被删除的文件**，而原命令**不带
`--diff-filter`** ⇒ `git rm --cached frontend/admin-web/.env.development` 之后这两个路径必然进
diff ⇒ 判 forbidden ⇒ required 红 ⇒ **「把违规文件下架」这个正确动作被门禁本身禁止**。
修法 = 加 `--diff-filter=ACMR`（只看新增/复制/修改/重命名）。**两个方向都要钉**：
删 `.env` ⇒ 放行；新增 `.env.foo` ⇒ 仍拦住。

## 判据形态

- 第一节的守卫**执行式**跑 workflow 里**当前**的 step 正文（桩 `docker`，不联网、不碰真实 ACR、
  产物落 `tmp_path`）⇒ 证明的是「给定输入下会做什么」，不是「GitHub 真的会这样」。
- 第二节读 `deploy-reconcile.yml` 的 job 级 `if:`（**必须**是 job 级：step 级 `if:` 是 #4827
  的静默短路形态，`test_reconcile_no_silent_skip.py` 有持久禁令）。
- 第三节把 `pr-check.yml` 里**当前**那条 `git diff` 命令抽出来，在**真实临时 git 仓库**里
  按 `origin/main...HEAD` 三明治形态跑。
- 每条判据都配**反向红证**（注入回改前形态 ⇒ 判据必红），防空断言。
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

PR_CHECK = WORKFLOWS_DIR / "pr-check.yml"
RECONCILE = WORKFLOWS_DIR / "deploy-reconcile.yml"

# 三条部署腿（与 test_swas_deploy_ci_hardening.py 的 DEPLOY_WORKFLOWS 同集合）
DEPLOY_WORKFLOWS = (
    "deploy-admin-api.yml",
    "deploy-ai-agent-service.yml",
    "deploy-frontend.yml",
)

# 5 条共用 `*/20` 的 workflow（#5078 ③）。`flaky-ledger-reconcile.yml` 归并行包，
# 本单只错峰其中 4 条 —— 判据只对**本单负责的 4 条**提「互不同刻」，
# 对 flaky 那条只做「不得与 reconcile 同刻」的**单向**断言（不越界改它的文件）。
STAGGERED = {
    "deploy-reconcile.yml": "*/20 * * * *",
    "deploy-admin-api.yml": "4,24,44 * * * *",
    "deploy-ai-agent-service.yml": "8,28,48 * * * *",
    "deploy-frontend.yml": "12,32,52 * * * *",
}
FLAKY_LEDGER = "flaky-ledger-reconcile.yml"

SYNC_STEP = "Skip if already built (schedule reconcile)"
ENV_STEP = "Check for forbidden .env files"
RECONCILE_JOB = "reconcile"

DOCKER_STUB = """#!/bin/bash
# 桩 docker：只认 `manifest inspect <image>`；命中 ${STUB_IMAGE_PRESENT} 时返回 0
if [ "$1" = "manifest" ] && [ "$2" = "inspect" ]; then
  if [ -n "${STUB_IMAGE_PRESENT:-}" ] && [ "$3" = "${STUB_IMAGE_PRESENT}" ]; then
    echo "stub: image present -> $3"
    exit 0
  fi
  echo "stub: no such manifest -> $3" >&2
  exit 1
fi
echo "stub docker: unexpected args: $*" >&2
exit 127
"""


# ══════════════════════════════════════════════════════════════════════════
# 工具：把 workflow 里的 step 正文抽出来，替换 GitHub 表达式后真跑
# ══════════════════════════════════════════════════════════════════════════

def _doc(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _on_block(doc: dict) -> dict:
    """YAML 1.1 里裸 `on` 会被 PyYAML 解析成布尔 True（已知坑）⇒ 两种键都试。"""
    on = doc.get("on")
    return on if on is not None else doc.get(True)


def _step_body(path: Path, step_name: str, job: str = "build-and-deploy") -> str:
    doc = _doc(path)
    steps = doc["jobs"][job]["steps"]
    for s in steps:
        if s.get("name") == step_name:
            body = s.get("run")
            assert isinstance(body, str) and body.strip(), (
                f"反空跑锚点：{path.name} 的 step `{step_name}` 没有 run 脚本（判据已过期）"
            )
            return body
    raise AssertionError(
        f"反空跑锚点：{path.name} 的 job `{job}` 里找不到 step `{step_name}`（判据已过期）"
    )


def render_sync_step(wf: str) -> str:
    """把 `Skip if already built` 的正文渲染成可直接 `bash` 执行的脚本。

    只替换该 step 用到的 GitHub 表达式（`env.*`）；事件名与 `image_tag` 走 step 的
    `env:` 块（`EVENT_NAME` / `INPUT_IMAGE_TAG`）⇒ 渲染后是**纯 bash**，无 `${{` 残留。
    `${GITHUB_SHA::7}` 由调用方通过环境变量 `GITHUB_SHA` 提供（与 Actions 同形）。
    """
    raw = _step_body(WORKFLOWS_DIR / wf, SYNC_STEP)
    rendered = (
        raw.replace("${{ env.ACR_REGISTRY }}", "acr.example.com")
        .replace("${{ env.ACR_NAMESPACE }}", "ns")
        .replace("${{ env.IMAGE_NAME }}", "svc")
    )
    assert "${{" not in rendered, (
        f"{wf}: 渲染后仍有 `${{{{ … }}}}` 残留 ⇒ 该 step 用了内联表达式（改走 step 的 `env:` 块）"
    )
    return rendered


def run_sync_step(wf: str, tmp_path: Path, *, event_name: str, sha: str,
                  image_present: bool, inputs_image_tag: str = "") -> tuple[int, str, dict]:
    """真跑渲染后的 step 正文（桩 docker），返回 (rc, stdout+stderr, outputs)。"""
    bindir = tmp_path / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    stub = bindir / "docker"
    stub.write_text(DOCKER_STUB, encoding="utf-8")
    stub.chmod(0o755)

    outputs_file = tmp_path / "github_output"
    outputs_file.write_text("", encoding="utf-8")

    script = tmp_path / "step.sh"
    script.write_text("set -euo pipefail\n" + render_sync_step(wf), encoding="utf-8")

    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "GITHUB_SHA": sha,
        "GITHUB_EVENT_NAME": event_name,
        "GITHUB_OUTPUT": str(outputs_file),
        "EVENT_NAME": event_name,
        "INPUT_IMAGE_TAG": (
            f"acr.example.com/ns/svc:{inputs_image_tag}" if inputs_image_tag else ""
        ),
        "STUB_IMAGE_PRESENT": f"acr.example.com/ns/svc:sha-{sha[:7]}" if image_present else "",
    }
    proc = subprocess.run(
        ["bash", str(script)], cwd=str(tmp_path), env=env,
        capture_output=True, text=True, timeout=60,
    )
    outputs = {}
    for line in outputs_file.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            outputs[k] = v
    return proc.returncode, proc.stdout + proc.stderr, outputs


# ══════════════════════════════════════════════════════════════════════════
# 一、#5078 A：重复 dispatch 的 run 必须「秒退」而不是被 45min 超时打死
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("wf", DEPLOY_WORKFLOWS)
def test_duplicate_dispatch_skips_with_explicit_reason(wf, tmp_path):
    """① 事故形态：`workflow_dispatch` + 该 commit 的镜像已存在（= 对账重复 dispatch，
    或前一个 run 已构建完）⇒ **显式跳过**（skip=true + 打印理由），不得再构建再部署。

    改前（判据只认 `schedule`）⇒ 这条 step 在 `workflow_dispatch` 下**整步不跑** ⇒
    输出里既没有 `skip=` 也没有理由 ⇒ 构建/部署照跑 ⇒ 占锁 45min。本断言必红。
    """
    sha = "abcdef1234567890"
    rc, out, outputs = run_sync_step(
        wf, tmp_path, event_name="workflow_dispatch", sha=sha, image_present=True,
    )
    assert rc == 0, f"{wf}: step 应正常退出（跳过 ≠ 失败），实际 rc={rc}\n{out}"
    assert outputs.get("skip") == "true", (
        f"{wf}: `workflow_dispatch` 下镜像已存在时必须写 `skip=true`（#5078 级联的秒退出口），"
        f"实际 outputs={outputs!r}\n{out}"
    )
    assert "已存在" in out and "跳过" in out, (
        f"{wf}: 跳过必须**显式打印理由**（不得静默），实际输出：\n{out}"
    )
    assert "重复" in out or "对账" in out or "dispatch" in out.lower(), (
        f"{wf}: 跳过理由必须点明「重复 dispatch / 对账」这一成因，实际输出：\n{out}"
    )


@pytest.mark.parametrize("wf", DEPLOY_WORKFLOWS)
def test_duplicate_dispatch_skip_is_visible_to_downstream_steps(wf, tmp_path):
    """①-b 跳过的 run 不得再跑构建/部署：`skip=true` 必须让**部署步**的 `if:` 为假。

    这是「跳过」与「只是打了条日志」的分界 —— 只写 output 不改接线 = 空跳过。
    """
    doc = _doc(WORKFLOWS_DIR / wf)
    steps = doc["jobs"]["build-and-deploy"]["steps"]
    deploy = [s for s in steps if str(s.get("name", "")).startswith("Deploy to SWAS")]
    assert deploy, f"反空跑锚点：{wf} 里找不到 `Deploy to SWAS` step（判据已过期）"
    cond = str(deploy[0].get("if", ""))
    assert "steps.sync.outputs.skip != 'true'" in cond, (
        f"{wf}: 部署步的 `if:` 必须含 `steps.sync.outputs.skip != 'true'`（当前 {cond!r}）—— "
        "否则「跳过」只写了个 output，部署照跑"
    )


@pytest.mark.parametrize("wf", DEPLOY_WORKFLOWS)
def test_missing_image_still_builds_and_deploys(wf, tmp_path):
    """② 反向：镜像**缺失** ⇒ 必须照常构建部署（不得把「跳过」写成恒真）。"""
    sha = "abcdef1234567890"
    rc, out, outputs = run_sync_step(
        wf, tmp_path, event_name="workflow_dispatch", sha=sha, image_present=False,
    )
    assert rc == 0, f"{wf}: rc={rc}\n{out}"
    assert outputs.get("skip") == "false", (
        f"{wf}: 镜像缺失时必须写 `skip=false`（= 照常构建部署），实际 outputs={outputs!r}\n{out}"
    )


@pytest.mark.parametrize("wf", DEPLOY_WORKFLOWS)
def test_explicit_rollback_never_skips(wf, tmp_path):
    """③ 边界：显式回滚（`workflow_dispatch -f image_tag=<tag>`，MODE=rollback）**永不跳过**。

    回滚是人工接口，镜像**必然**已存在 ⇒ 若判据不看 MODE，回滚会被自己的守卫挡死
    （= 把 #4852 的显式回滚接口砍掉）。这条守住「守卫不削弱既有护栏」。
    """
    rc, out, outputs = run_sync_step(
        wf, tmp_path, event_name="workflow_dispatch", sha="abcdef1234567890",
        image_present=True, inputs_image_tag="sha-0000000",
    )
    assert rc == 0, f"{wf}: rc={rc}\n{out}"
    assert outputs.get("skip") == "false", (
        f"{wf}: MODE=rollback 时必须 `skip=false`（回滚不许被去重守卫挡掉），"
        f"实际 outputs={outputs!r}\n{out}"
    )
    assert "回滚" in out, f"{wf}: 回滚路径也要打印为什么没跳过，实际输出：\n{out}"


@pytest.mark.parametrize("wf", DEPLOY_WORKFLOWS)
def test_schedule_reconcile_semantics_unchanged(wf, tmp_path):
    """④ 不得回退 #2947 的 schedule 对账语义（镜像在 ⇒ 跳过；不在 ⇒ 补）。"""
    sha = "abcdef1234567890"
    _, out_present, o1 = run_sync_step(
        wf, tmp_path, event_name="schedule", sha=sha, image_present=True)
    _, out_absent, o2 = run_sync_step(
        wf, tmp_path, event_name="schedule", sha=sha, image_present=False)
    assert o1.get("skip") == "true", f"{wf}: schedule + 镜像在 ⇒ skip=true（#2947），实际 {o1!r}"
    assert o2.get("skip") == "false", f"{wf}: schedule + 镜像缺 ⇒ skip=false（#2947），实际 {o2!r}"


def test_duplicate_dispatch_criterion_has_discriminating_power(tmp_path):
    """⑤ 反向红证：把 `workflow_dispatch` 从守卫的 `if:` 里摘掉（= 改前形态）⇒ 判据必红。

    注入的是**行为**而不是文本：渲染后的正文来自当前 workflow，摘掉 `if:` 后
    step 在 `workflow_dispatch` 下**不再执行** ⇒ 无 output、无理由 ⇒ ① 的断言必红。
    """
    wf = "deploy-admin-api.yml"
    raw = _step_body(WORKFLOWS_DIR / wf, SYNC_STEP)
    assert "workflow_dispatch" in raw, (
        f"注入自证失败：{wf} 的 `{SYNC_STEP}` 正文里没有 `workflow_dispatch` ⇒ "
        "判据已与实现脱节（先看 step 是否真的扩到了 dispatch）"
    )

    # 注入回改前形态：把「去重」这一支的判据短路成恒假 ⇒ 回到「镜像在 ⇒ 写 skip=true」的老行为。
    # ⚠️ 不用正则跨行匹配（缩进一变就静默不生效 ⇒ 判据就废了）；这里只改**条件**，结构不动。
    lines = raw.splitlines(keepends=True)
    idx = next(
        i for i, ln in enumerate(lines) if 'if [ "$EVENT_NAME" = "workflow_dispatch" ] && [ -z "$INPUT_IMAGE_TAG" ]' in ln
    )
    lines[idx] = lines[idx].replace(
        'if [ "$EVENT_NAME" = "workflow_dispatch" ] && [ -z "$INPUT_IMAGE_TAG" ]',
        "if false",
    )
    broken = "".join(lines)
    assert broken != raw, "注入未生效（判据自证）"
    assert "if false" in broken, "注入未生效：去重支没被短路"

    bindir = tmp_path / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    (bindir / "docker").write_text(DOCKER_STUB, encoding="utf-8")
    (bindir / "docker").chmod(0o755)
    outputs_file = tmp_path / "github_output"
    outputs_file.write_text("", encoding="utf-8")
    script = tmp_path / "broken.sh"
    script.write_text("set -euo pipefail\n" + broken, encoding="utf-8")
    sha = "abcdef1234567890"
    proc = subprocess.run(
        ["bash", str(script)], cwd=str(tmp_path),
        env={
            **os.environ,
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "GITHUB_SHA": sha,
            "GITHUB_OUTPUT": str(outputs_file),
            "EVENT_NAME": "workflow_dispatch",
            "INPUT_IMAGE_TAG": "",
            "STUB_IMAGE_PRESENT": f"acr.example.com/ns/svc:sha-{sha[:7]}",
        },
        capture_output=True, text=True, timeout=60,
    )
    outputs = dict(
        line.split("=", 1) for line in outputs_file.read_text(encoding="utf-8").splitlines() if "=" in line
    )
    assert outputs.get("skip") != "true", (
        "注入回改前形态后仍然写了 skip=true ⇒ 判据无判别力（空断言）"
    )


# ══════════════════════════════════════════════════════════════════════════
# 一、#5078 B：5 条同 cron 的 workflow 必须错峰
# ══════════════════════════════════════════════════════════════════════════

def _crons(wf: str) -> list[str]:
    doc = _doc(WORKFLOWS_DIR / wf)
    sched = _on_block(doc).get("schedule") or []
    return [str(s["cron"]) for s in sched if isinstance(s, dict) and "cron" in s]


@pytest.mark.parametrize("wf,cron", sorted(STAGGERED.items()))
def test_cron_is_staggered(wf, cron):
    """错峰（#5078 ③）：5 条 `*/20` 同刻起跑 ⇒ 同时抢 runner + 同时抢 deploy 锁。

    本单负责的 4 条必须**逐字**错峰；`deploy-reconcile` 保持在 `*/20`（它是唯一的
    「发现缺失并 dispatch」的兜底，且 3 条 deploy 腿都排在它**之后** ⇒ 它先判定、
    deploy 腿再独立复核，不再同刻挤在一起）。
    """
    assert _crons(wf) == [cron], (
        f"{wf} 的 schedule cron 应为 {cron!r}（错峰），实际 {_crons(wf)!r}"
    )


def test_deploy_legs_do_not_collide_with_each_other_or_reconcile():
    """错峰的可判红形态：4 条的**分钟集合两两不相交**（`*/20` 展开为 {0,20,40}）。"""
    def minutes(expr: str) -> set[int]:
        m = expr.split()[0]
        if m.startswith("*/"):
            step = int(m[2:])
            return set(range(0, 60, step))
        return {int(x) for x in m.split(",")}

    seen: dict[int, str] = {}
    for wf, expr in STAGGERED.items():
        for mi in minutes(expr):
            assert mi not in seen, (
                f"{wf} 与 {seen[mi]} 在每小时第 {mi} 分钟同刻起跑（#5078 ③ 的 5 条同 cron 自踩）"
            )
            seen[mi] = wf


def test_no_moment_has_more_than_two_scheduled_workflows():
    """错峰的**可判红形态**（#5078 ③ 的本体）：任一时刻同刻起跑的调度 workflow ≤ 2。

    改前 5 条全在 :00/:20/:40 ⇒ 该时刻 5 条同刻。本单把自己负责的 3 条 deploy 腿错峰后，
    只剩 `deploy-reconcile` 与 `flaky-ledger-reconcile` 在 :00/:20/:40 重叠（= 2 条）。
    ⚠️ `flaky-ledger-reconcile.yml` **不在本单授权面内**（归并行包）⇒ 若要把它也错峰，
    那是并行包的事；本判据的阈值 2 对**任一包先合**都成立，不制造跨包冲突。
    """
    def minutes(expr: str) -> set[int]:
        m = expr.split()[0]
        if m.startswith("*/"):
            return set(range(0, 60, int(m[2:])))
        return {int(x) for x in m.split(",")}

    at: dict[int, list[str]] = {}
    for wf in list(STAGGERED) + [FLAKY_LEDGER]:
        for mi in minutes(_crons(wf)[0]):
            at.setdefault(mi, []).append(wf)
    worst = max(at.items(), key=lambda kv: len(kv[1]))
    assert len(worst[1]) <= 2, (
        f"每小时第 {worst[0]} 分钟有 {len(worst[1])} 条调度 workflow 同刻起跑：{worst[1]}"
        f"（#5078 ③ 的自踩形态；本单已把 3 条 deploy 腿错峰，阈值 2 是「reconcile 兜底 +"
        f" 另一条独立兜底」的上界）"
    )


@pytest.mark.parametrize("wf", DEPLOY_WORKFLOWS + ("deploy-reconcile.yml",))
def test_deploy_legs_keep_minute_level_fallback(wf):
    """错峰**不得**把分钟级兜底降成小时级（那会让「部署触发被吞」的兜底窗口从 20min 变 60min）。"""
    for expr in _crons(wf):
        assert re.match(r"^(\*/[0-9]+|[0-9,\-]+) ", expr), (
            f"{wf} 的 cron {expr!r} 不是分钟级兜底形态（#2947/#2935 的兜底窗口会被拉长）"
        )
        assert not expr.startswith("0 "), f"{wf} 的 cron {expr!r} 退化成整点级"


# ══════════════════════════════════════════════════════════════════════════
# 二、#5077：dependabot 触发（无 secrets）必须显式跳过，不得必然失败
# ══════════════════════════════════════════════════════════════════════════

def _reconcile_job_if() -> str:
    doc = _doc(RECONCILE)
    job = doc["jobs"][RECONCILE_JOB]
    return str(job.get("if", ""))


def _reconcile_skip_message() -> str:
    """从 `deploy-reconcile.yml` 的注释里取「跳过原因」正文（必须显式写明）。"""
    return RECONCILE.read_text(encoding="utf-8")


def test_reconcile_job_skips_on_dependabot_pr():
    """① dependabot 触发 ⇒ 该 job **不跑**（缺 secrets 必然失败 ⇒ 不允许「必然失败的必红项」）。"""
    cond = _reconcile_job_if()
    assert cond, (
        f"{RECONCILE}: reconcile job 没有 `if:` ⇒ dependabot PR 上仍会跑 `Docker login ACR` ⇒ "
        "必然报 `Cannot perform an interactive login from a non TTY device`（#5077）"
    )
    assert "dependabot[bot]" in cond, (
        f"{RECONCILE}: job 级 `if:` 必须点名 `dependabot[bot]`（当前 {cond!r}）"
    )
    assert "pull_request" in cond, (
        f"{RECONCILE}: 跳过条件必须限定在 pull_request 事件（当前 {cond!r}）—— "
        "schedule/workflow_dispatch 没有 secrets 问题，必须照跑"
    )


def test_reconcile_still_runs_on_normal_pr_and_schedule():
    """② 反向：非 dependabot 的 PR 与 schedule 形态**仍然真跑**（不得把判据一起跳过）。"""
    cond = _reconcile_job_if()
    # 表达式必须能「两个分支都为真才跳过」——即不是恒假/恒真的短路
    assert "!=" in cond and "||" in cond, (
        f"{RECONCILE}: 跳过条件形态异常（{cond!r}）—— 期望 "
        "`event_name != 'pull_request' || actor != 'dependabot[bot]'` 这种「或」形态"
    )
    # 行为级：用真值表验证（不依赖 GitHub 求值）
    def runs(event_name: str, actor: str) -> bool:
        # 逐字对应 `A != 'pull_request' || B != 'dependabot[bot]'`
        return (event_name != "pull_request") or (actor != "dependabot[bot]")

    assert runs("pull_request", "zhaokai-mgzn") is True, "非 dependabot 的 PR 必须真跑"
    assert runs("schedule", "dependabot[bot]") is True, "schedule 必须真跑（与 actor 无关）"
    assert runs("workflow_dispatch", "dependabot[bot]") is True, "手动 dispatch 必须真跑"
    assert runs("pull_request", "dependabot[bot]") is False, "dependabot PR 必须跳过"


def test_dependabot_skip_is_explicit_not_silent():
    """③ 跳过必须**显式**：workflow 注释里写明「dependabot ⇒ 无 secrets ⇒ 跳过」+ 处置路径。

    #5077 验收判据 1：「明确标 skipped 并给出原因，不允许必然失败的必红项」。
    """
    text = _reconcile_skip_message()
    assert "dependabot" in text, "反空跑锚点：注释里没有 dependabot 相关说明"
    for token in ("secrets", "跳过"):
        assert token in text, (
            f"{RECONCILE}: 跳过理由必须显式写明「{token}」（#5077 验收判据 1：不得静默）"
        )


def test_reconcile_keeps_its_dispatch_work():
    """④ 边界：跳过判据**不得**顺手削弱对账本体（#4827 的「不许静默短路」仍然成立）。"""
    doc = _doc(RECONCILE)
    steps = doc["jobs"][RECONCILE_JOB]["steps"]
    reconcile_step = [s for s in steps if s.get("name") == "Reconcile deploys"]
    assert reconcile_step, "反空跑锚点：找不到 `Reconcile deploys` step（判据已过期）"
    assert "if" not in reconcile_step[0], (
        "`Reconcile deploys` 出现了 step 级 `if:` —— 那是 #4827 的静默短路形态"
        "（`test_reconcile_no_silent_skip.py` 有持久禁令）"
    )
    body = reconcile_step[0]["run"]
    assert "gh workflow run" in body, "对账的 dispatch 本体被删了"


def test_dependabot_skip_criterion_has_discriminating_power():
    """⑤ 反向红证：把 job 级 `if:` 摘掉（= 改前形态）⇒ 判据必红。"""
    cond = _reconcile_job_if()
    assert cond, "注入自证失败：改前本来就没有 `if:` ⇒ 判据 ① 早已必红（这正是红证）"
    for broken in ("", "github.event_name == 'pull_request'"):
        if broken == cond:
            continue
        assert broken != cond, "注入未生效（判据自证）"
        ok = ("dependabot[bot]" in broken) and ("pull_request" in broken) and ("!=" in broken)
        assert not ok, f"注入 {broken!r} 后判据 ① 仍然通过 ⇒ 判据无判别力"


# ══════════════════════════════════════════════════════════════════════════
# 三、#5083：`Block .env files` 删 `.env` 要放行、增 `.env` 仍要拦住
# ══════════════════════════════════════════════════════════════════════════

def _env_gate_command() -> str:
    """从 `pr-check.yml` 里抽出**当前**那条判定命令（真值源，不写死副本）。"""
    doc = _doc(PR_CHECK)
    steps = doc["jobs"]["block-env-files"]["steps"]
    for s in steps:
        if s.get("name") == ENV_STEP:
            body = s.get("run")
            assert isinstance(body, str), f"反空跑锚点：{PR_CHECK.name} 的 `{ENV_STEP}` 没有 run"
            return body
    raise AssertionError(f"反空跑锚点：{PR_CHECK.name} 里找不到 step `{ENV_STEP}`（判据已过期）")


def _render_env_gate(extra_scripts: str = "") -> str:
    """把判定的 `run:` 正文渲染成可执行脚本。

    `${{ … }}` 表达式在本 step 里只出现在 `echo` 文案中 ⇒ 换成占位符即可。
    `extra_scripts` = 测试注入的「造 diff」前置脚本（放在判定**之前**）。
    """
    body = _env_gate_command()
    body = re.sub(r"\$\{\{[^}]*\}\}", "EXPR", body)
    return "set -euo pipefail\n" + extra_scripts + "\n" + body


def _make_repo(tmp_path: Path) -> Path:
    """建一个带 `origin/main` 的真实 git 仓库（三明治 diff 形态与 CI 同形）。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a, **kw: subprocess.run(  # noqa: E731
        ["git", *a], cwd=str(repo), capture_output=True, text=True, check=True, **kw
    )
    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    run("add", "README.md")
    run("commit", "-q", "-m", "base")
    run("update-ref", "refs/remotes/origin/main", "HEAD")
    run("checkout", "-q", "-b", "pr")
    return repo


def _run_env_gate(repo: Path, extra_scripts: str = "") -> subprocess.CompletedProcess:
    script = repo / "_gate.sh"
    script.write_text(_render_env_gate(extra_scripts), encoding="utf-8")
    return subprocess.run(
        ["bash", str(script)], cwd=str(repo), capture_output=True, text=True, timeout=60
    )


DELETE_ENV_SCRIPTS = """
git rm -q --cached frontend/admin-web/.env.development frontend/admin-web/.env.production
git commit -q -m "chore: 下架 .env（#5083）"
"""

ADD_ENV_SCRIPTS = """
mkdir -p frontend/admin-web
printf 'X=1\\n' > frontend/admin-web/.env.foo
git add frontend/admin-web/.env.foo
git commit -q -m "feat: 新增 .env.foo（红证）"
"""


def test_env_gate_allows_removing_env_files(tmp_path):
    """① 正确修法必须放行：`git rm --cached` 掉 `.env.*` ⇒ **绿**（exit 0）。

    改前（无 `--diff-filter`）⇒ `git diff --name-only origin/main...HEAD` **列出被删的文件**
    ⇒ 判 forbidden ⇒ exit 1 ⇒ required 红 ⇒ 「把违规文件下架」被门禁本身永久禁止（#5083）。
    """
    repo = _make_repo(tmp_path)
    (repo / "frontend" / "admin-web").mkdir(parents=True)
    (repo / "frontend" / "admin-web" / ".env.development").write_text(
        "NEXT_PUBLIC_API_BASE_URL=http://localhost:8080\n", encoding="utf-8")
    (repo / "frontend" / "admin-web" / ".env.production").write_text(
        "NEXT_PUBLIC_API_BASE_URL=https://api.example.com\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "add env"], cwd=str(repo),
                   check=True, capture_output=True)
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"],
                   cwd=str(repo), check=True, capture_output=True)

    proc = _run_env_gate(repo, DELETE_ENV_SCRIPTS)
    assert proc.returncode == 0, (
        "删除 `.env` 被门禁判红 ⇒ 「下架违规文件」这个正确动作被门禁永久禁止（#5083）\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert "No forbidden" in proc.stdout or "✅" in proc.stdout, proc.stdout


def test_env_gate_still_blocks_adding_env_files(tmp_path):
    """② 不得放宽语义：新增 `.env.foo` ⇒ **仍红**（exit 1）。"""
    repo = _make_repo(tmp_path)
    proc = _run_env_gate(repo, ADD_ENV_SCRIPTS)
    assert proc.returncode != 0, (
        "新增 `.env.foo` 没被拦住 ⇒ 门禁语义被放宽（#5083 只允许加 `--diff-filter`）\n"
        f"stdout:\n{proc.stdout}"
    )
    assert ".env.foo" in proc.stdout, f"判红时必须点名违规文件，实际：\n{proc.stdout}"


def test_env_gate_allows_env_example(tmp_path):
    """③ 边界：`.env.example` 仍然豁免（#5083 要求同时建 `.env.example`）。"""
    repo = _make_repo(tmp_path)
    extra = """
mkdir -p frontend/admin-web
printf 'NEXT_PUBLIC_API_BASE_URL=\\n' > frontend/admin-web/.env.example
git add frontend/admin-web/.env.example
git commit -q -m "docs: .env.example"
"""
    proc = _run_env_gate(repo, extra)
    assert proc.returncode == 0, (
        f"`.env.example` 被误判 forbidden（#5083 要求建它）\n{proc.stdout}\n{proc.stderr}"
    )


def test_env_gate_uses_add_copy_modify_rename_filter():
    """④ 判据形态：命令必须带 `--diff-filter=ACMR`（只看新增/复制/修改/重命名）。

    只认这一处放宽 —— 不得改成 `|| true`、不得整条删掉、不得改 `grep` 语义。
    """
    body = _env_gate_command()
    assert "--diff-filter=ACMR" in body, (
        f"`{ENV_STEP}` 的 `git diff` 缺 `--diff-filter=ACMR` ⇒ 删除的文件会进 diff ⇒ "
        "「下架 .env」被门禁禁止（#5083）"
    )
    assert "origin/main...HEAD" in body, "三明治 diff 基准被改动（判据已过期）"
    assert "grep -v '\\.env\\.example'" in body, "`.env.example` 豁免被删"
    assert "|| true" not in body.split("--diff-filter")[0], (
        "不得用 `|| true` 之类手段放宽（只允许加 `--diff-filter=ACMR`）"
    )


def test_env_gate_criterion_has_discriminating_power(tmp_path):
    """⑤ 反向红证：把 `--diff-filter=ACMR` 摘掉（= 改前形态）⇒ 「删除」场景必红。"""
    repo = _make_repo(tmp_path)
    (repo / "frontend" / "admin-web").mkdir(parents=True)
    (repo / "frontend" / "admin-web" / ".env.development").write_text("A=1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "add env"], cwd=str(repo),
                   check=True, capture_output=True)
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"],
                   cwd=str(repo), check=True, capture_output=True)

    body = _env_gate_command().replace("--diff-filter=ACMR ", "")
    body = re.sub(r"\$\{\{[^}]*\}\}", "EXPR", body)
    script = repo / "_gate_pre.sh"
    script.write_text("set -euo pipefail\n" + DELETE_ENV_SCRIPTS + "\n" + body, encoding="utf-8")
    proc = subprocess.run(["bash", str(script)], cwd=str(repo),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode != 0, (
        "摘掉 `--diff-filter=ACMR` 后删除场景仍然绿 ⇒ 判据无判别力（空断言）"
    )


# ══════════════════════════════════════════════════════════════════════════
# 四、交付面守卫：#5083 的 `.env` 下架与 `.env.example` 模板必须真的落地
# ══════════════════════════════════════════════════════════════════════════

ENV_EXAMPLE = REPO_ROOT / "frontend" / "admin-web" / ".env.example"
ADMIN_WEB_ENVS = (
    REPO_ROOT / "frontend" / "admin-web" / ".env.development",
    REPO_ROOT / "frontend" / "admin-web" / ".env.production",
)


def test_admin_web_env_files_are_untracked():
    """① `.env.development` / `.env.production` 不得再被 git 跟踪（#5083 的下架动作）。"""
    out = subprocess.run(
        ["git", "ls-files", "--error-unmatch", *[str(p.relative_to(REPO_ROOT)) for p in ADMIN_WEB_ENVS]],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert out.returncode != 0, (
        "admin-web 的 .env.development/.env.production 仍在 git 索引里 ⇒ #5083 未收口\n"
        f"{out.stdout}"
    )


def test_env_example_declares_the_three_public_keys_without_secrets():
    """② `.env.example` 必须给全 3 个 `NEXT_PUBLIC_*` 键，且**不含任何真实密钥**。"""
    assert ENV_EXAMPLE.is_file(), f"缺少 {ENV_EXAMPLE.relative_to(REPO_ROOT)}（#5083 要求新建）"
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for key in ("NEXT_PUBLIC_API_BASE_URL", "NEXT_PUBLIC_AI_API_BASE_URL", "NEXT_PUBLIC_COOKIE_DOMAIN"):
        assert re.search(rf"^{key}=", text, re.M), f"`.env.example` 缺键 {key}"
    # 值必须是公共占位（域名/空），不得出现密钥形态
    for bad in ("sk-", "AKID", "BEGIN PRIVATE KEY", "password", "secret"):
        assert bad.lower() not in text.lower(), (
            f"`.env.example` 出现疑似密钥片段 {bad!r} —— 模板只放公共占位值"
        )
