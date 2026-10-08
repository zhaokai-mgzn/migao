# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
r"""腿级失败反应守卫 —— issue #6526 B（**这一次 run 挂了** ⇒ 出声 + 首次自动重跑一次）。

## 病（issue #6526 B，逐条锚点）

三条部署腿的 `permissions` 只有 `contents: read` / `actions: read` ⇒ **失败不出声**：
没有 `issues: write`、没有 `if: failure()` 步。唯一出声面是 `deploy-reconcile.yml` 的
`[deploy-watchdog]`（判**状态**「合并了但没上线」，宽限 N=2700s + cron 被 GitHub 节流到
实测 **2.5~8.6 小时**）⇒ 「某一次 run 挂了」在最长 8.6 小时里**没有任何人会被叫醒**。
另一半：**失败不自愈** —— 两条闸门把非 success 结论当坏 commit 拒绝补部署
（`reconcile_one` 的断路器 + 各腿 `Skip if already built` 的终态闸门），而它们**一字不许动**。

## 承载面为什么是 `deploy-reconcile.yml`

它**已经**有 `on.workflow_run: types=[completed]`（监听六条腿）、**已经**有 `issues: write`
与 `actions: write` ⇒ **零新增权限、零新增 mechanism 登记**。给三条部署腿加 `issues: write`
会让它们变成「无人值守 × 写作用域」的维护类机制 ⇒ 被 `scripts/mechanism_liveness.py` 的发现
规则抓住 ⇒ 必须登记 + 发存活读数 —— 本单**有意避开**这条扩面。

## 判据

| # | 判什么 | 回归时会怎么红 |
|---|---|---|
| 1 | 反应步**接线在**：`if` 含 `always()` 与 `workflow_run`；`${{ }}` 一律走 `env:` | 把事件判据写进正文 / 去掉 `always()` ⇒ 红 |
| 2 | 四态逐条（**执行式**，桩 `gh` + fixture 日志）：① 失败+attempt1+无闸门 ⇒ 重跑+通知 ② 失败+attempt2 ⇒ 只通知 ③ 失败+attempt1+**具名闸门**（逐条各一个 fixture）⇒ 不重跑但仍通知 ④ success ⇒ 只清零 | 任一臂被摘掉 ⇒ 对应场景红 |
| 3 | 台账 ⇄ `on.workflow_run.workflows` **双向相等**，且 `c-end-h5` 的 `rerun=false` | 新腿没进台账 / 台账多一条 / c-end-h5 被改成 true ⇒ 红 |
| 4 | 台账**未登记即红**（脚本非零）+ 底座脚本缺失时反应步**弃权不红** | 台账被删 / 脚本被删后判红 ⇒ 红 |
| 5 | **判别力自证**：内存变异（摘掉重跑臂 / 摘掉通知臂 / 台账删一行 / 把 `source` 行改回 4 次）**各自判红**；**只改注释 ⇒ 不红** | 判据退化成空断言 ⇒ 红 |
| 6 | 反应步**绝不许**让对账 job 判红（脚本缺失 / 非零退出都被 `::warning::` 吞掉） | 有人在薄壳里去掉那层兜底 ⇒ 红 |

## 边界（照实登记）

- **`gh run rerun` 真的被 GitHub 接受**判不了（本机不联网）：判据只判「**发起了** `run rerun --failed`」
  与「`attempt==2` 时**不**发起」。真被拒时的处置写在通知正文里（`**自动重跑尝试失败**`）。
- **日志里「有没有闸门」**由 fixture 日志驱动：真日志的形态由 `gh run view --log-failed` 决定，
  本机拿不到 ⇒ 闸门**锚点清单**（`GATES`）的完整性与「这些字符串真的出现在真日志里」两条，
  前者由判据 2c 逐条覆盖，**后者不在射程内**（如实登记）。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
RECONCILE = REPO_ROOT / ".github" / "workflows" / "deploy-reconcile.yml"
SCRIPT = REPO_ROOT / "scripts" / "deploy_leg_failure_reaction.sh"
LEDGER = REPO_ROOT / "tests/unit_ci_workflows" / "deploy_leg_failure_reaction_ledger.json"
BASH = "/bin/bash"

STEP_NAME = "腿级失败反应（workflow_run ⇒ 出声 + 首次自动重跑一次）"
STATE_SCRIPT = "scripts/deploy_reconcile_state.sh"
C_END_LEG = "Publish C-end H5 (app.migaozn.com 根)"

# gh 桩：**接口尽量贴近真 gh**（行为完全由环境变量 / 桩状态文件决定）——
#  `.issue` 写成的行 = `编号<TAB>标题<TAB>状态`，`issue list` 据此答，`issue create` 据此记
#  ⇒ 「同标题已开 ⇒ 评论而不是重复开单」这条幂等臂**真的**走到。
GH_STUB = r"""#!/usr/bin/env bash
printf 'gh %s\n' "$*" >> "$GH_CALL_LOG"
s="$STUB_ISSUES"; [ -f "$s" ] || : > "$s"
cmd="$1 $2"
case "$cmd" in
  "issue list")
    last=""; prev=""
    for a in "$@"; do
      if [ "$prev" = "--search" ]; then last="$a"; fi
      case "$a" in --search=*) last="${a#--search=}";; esac
      prev="$a"
    done
    key="${last%% in:title*}"; key="${key#[}"; key="${key%]}"
    while IFS=$'\t' read -r n t st; do
      [ -n "$n" ] || continue
      [ "$st" = "open" ] || continue
      case "$t" in *"$key"*) echo "$n" ;; esac
    done < "$s" ;;
  "issue create")
    last=""; prev=""
    for a in "$@"; do
      if [ "$prev" = "--title" ]; then last="$a"; fi
      case "$a" in --title=*) last="${a#--title=}";; esac
      prev="$a"
    done
    n=1; [ -f "$s.count" ] && n=$(( $(cat "$s.count") + 1 )); printf '%s' "$n" > "$s.count"
    printf '%s\t%s\t%s\n' "$n" "$last" open >> "$s"
    echo "https://github.com/x/y/issues/$n" ;;
  "issue comment" | "issue close" | "issue edit")
    last=""; prev=""
    for a in "$@"; do [ "$prev" = "" ] && last="$a"; prev="$a"; done
    exit 0 ;;
  "run rerun")
    if [ -n "${STUB_RERUN_FAIL:-}" ]; then echo "cannot rerun" >&2; exit 1; fi
    exit 0 ;;
  *) exit 0 ;;
esac
"""


def _doc():
    return yaml.safe_load(RECONCILE.read_text(encoding="utf-8")) or {}


def _on_block(doc) -> dict:
    """`on:` 在 PyYAML 里是**布尔 True**（YAML 1.1 的 `on` = true）—— 本仓既有判据同口径。"""
    return doc[True] if True in doc else doc["on"]


def _steps() -> list:
    return _doc()["jobs"]["reconcile"]["steps"]


def _step(name: str) -> dict:
    for s in _steps():
        if s.get("name") == name:
            return s
    pytest.fail(f"反空跑锚点：`{RECONCILE.name}` 里找不到 step `{name}` —— 判据已过期")


def reaction_body() -> str:
    """抽出反应步的 `run:` 正文，并把 `${{ … }}` 换成字面量（与执行式红证同一份读法）。"""
    body = _step(STEP_NAME).get("run", "") or ""
    assert body, f"反空跑锚点：step `{STEP_NAME}` 没有 run 正文"
    body = body.replace("${{ github.event_name }}", "workflow_run")
    assert "${{" not in body, f"`{STEP_NAME}` 里还有没替换掉的 GitHub 表达式（判据已过期）"
    return body


RECONCILE_BODY = None  # 对账步正文（惰性取，见 reconcile_body()）


def reconcile_body() -> str:
    global RECONCILE_BODY
    if RECONCILE_BODY is None:
        body = None
        for s in _steps():
            if s.get("name") == "Reconcile deploys":
                body = s.get("run", "") or ""
        assert body, "反空跑锚点：找不到 `Reconcile deploys` 的 run 正文"
        for key, value in (("ACR_REGISTRY", "reg.example.com"),
                           ("ACR_NAMESPACE", "ns")):
            body = body.replace("${{ env.%s }}" % key, value)
        RECONCILE_BODY = body
    return RECONCILE_BODY


# ══════════════════════════════════════════════════════════════════════════
# 一、静态面（接线 / 台账 / 尺寸）
# ══════════════════════════════════════════════════════════════════════════

def test_reaction_step_is_wired_after_watchdog_and_before_liveness():
    names = [s.get("name") for s in _steps()]
    assert STEP_NAME in names, f"反应步不在 `reconcile` job 里 → {names}"
    assert names[-1] == "存活读数（本轮做了什么 / 为什么零动作）", (
        "存活读数步仍必须是最后一步（#5326）—— 反应步要夹在它**之前**"
    )
    assert names.index("值守面（超时未部署 ⇒ 判红 + 开/清值守 issue）") < names.index(STEP_NAME), (
        "反应步应在值守面之后（同一 job 内，判定互不依赖）"
    )


def test_reaction_step_uses_env_not_expressions_in_body():
    """判据 1：事件判据在 `if:` / `${{ }}` 全走 `env:`（本仓有执行式守卫会逐字渲染正文）。"""
    step = _step(STEP_NAME)
    cond = str(step.get("if", ""))
    assert "always()" in cond, f"反应步必须 `always()`（否则上一步判红时它不跑）→ {cond!r}"
    assert "workflow_run" in cond, f"反应步只许在 `workflow_run` 事件跑 → {cond!r}"
    env = step.get("env") or {}
    for key in ("LEG_NAME", "LEG_CONCLUSION", "LEG_ATTEMPT", "LEG_RUN_ID", "LEG_HEAD_SHA", "LEG_RUN_URL"):
        assert key in env, f"反应步缺 env `{key}`（`${{ }}` 只许出现在 env 里）"
        assert env[key] == "${{ github.event.workflow_run.%s }}" % {
            "LEG_NAME": "name", "LEG_CONCLUSION": "conclusion", "LEG_ATTEMPT": "run_attempt",
            "LEG_RUN_ID": "id", "LEG_HEAD_SHA": "head_sha", "LEG_RUN_URL": "html_url"}[key], (
            f"env `{key}` 必须取自 `github.event.workflow_run.*`（现取 {env[key]!r}）"
        )
    assert "GH_TOKEN" in env, "反应步要调 gh（开单/评论/重跑）⇒ 必须显式给 GH_TOKEN"


def test_reaction_step_never_reds_the_job():
    """判据 6：脚本缺失 ⇒ 弃权；脚本非零 ⇒ 吞掉成 `::warning::`（反应步不许判红）。"""
    body = reaction_body()
    assert "[ ! -f scripts/deploy_leg_failure_reaction.sh ]" in body, (
        "缺「脚本不在检出里就弃权」的门（本腿 checkout 是 ref: main ⇒ 新增它的 PR 里取不到）"
    )
    assert re.search(r"deploy_leg_failure_reaction\.sh \|\| \{", body), (
        "缺非零退出兜底（`|| { … }`）—— 反应步自身**不得**让本 job 判红（issue #6526 B）"
    )
    assert body.count("exit 0") >= 2, f"两条兜底路径都必须 `exit 0`（现取 {body.count('exit 0')} 处）"
    assert "::warning::" in body, "弃权/兜底必须具名 `::warning::`（沉默不是处置）"


def test_source_state_script_exactly_once():
    """issue #6526 顺带修：`source scripts/deploy_reconcile_state.sh` **恰好一次**。"""
    body = reconcile_body()
    n = body.count("source scripts/deploy_reconcile_state.sh")
    assert n == 1, (
        f"`source scripts/deploy_reconcile_state.sh` 出现 {n} 次（必须恰好 1 次）——"
        "本步正文已顶到 GitHub 的 13,250 字符硬限（超了整份 workflow invalid、该腿完全不跑），"
        "连写 4 次当年恰好幂等，但是陷阱（没人会去数）"
    )


RUN_BODY_LIMIT = 13250


def test_no_step_body_exceeds_the_github_limit():
    """`run` 正文超 13,250 字符 ⇒ 整份 workflow invalid（该腿完全不跑）。"""
    over = [(len(s.get("run", "") or ""), s.get("name")) for s in _steps()
            if len(s.get("run", "") or "") > RUN_BODY_LIMIT]
    assert not over, f"以下 step 的 run 正文超过 {RUN_BODY_LIMIT} 字符：{over}"


# ══════════════════════════════════════════════════════════════════════════
# 二、台账 ⇄ workflow_run 清单（**双向相等**）
# ══════════════════════════════════════════════════════════════════════════

def ledger() -> dict:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def test_ledger_matches_workflow_run_legs_bidirectionally():
    legs = _on_block(_doc())["workflow_run"]["workflows"]
    led = [l["name"] for l in ledger()["legs"]]
    assert ledger().get("schema", "").startswith("deploy-leg-failure-reaction-ledger/"), (
        "台账缺 schema 标记（它就是本文件的登记表，别的台账的 `schema` 值在真语料里唯一可判）"
    )
    assert ledger()["legs"], "台账 `legs` 为空 ⇒ 有人清空台账「消红」（fail-closed：空表 ⇒ 红）"
    assert set(legs) == set(led), (
        "台账 ⇄ `on.workflow_run.workflows` 必须**双向相等**（未登记的新腿 ⇒ 红；"
        f"台账多出一条 ⇒ 红）\n  workflow_run = {legs}\n  ledger      = {led}"
    )
    assert len(led) == len(set(led)), f"台账里有重名腿：{led}"
    for l in ledger()["legs"]:
        assert l.get("reason"), f"台账条目 `{l.get('name')}` 缺理由（为什么是这个 rerun 值）"


def test_c_end_h5_never_autoreruns():
    """`Publish C-end H5` 的 `rerun` 必须是 `false`（发布由人手动，用户 2026-09-27 裁定 B）。"""
    entry = {l["name"]: l for l in ledger()["legs"]}[C_END_LEG]
    assert entry["rerun"] is False, (
        f"`{C_END_LEG}` 的发布只在 `workflow_dispatch` + `inputs.publish=='true'` 时发生"
        "（用户 2026-09-27 裁定 B：发布由人手动）⇒ 自动重跑没有任何发布效果，只能刷噪声"
    )
    others = [l["name"] for l in ledger()["legs"] if l["name"] != C_END_LEG]
    assert all({l["name"]: l for l in ledger()["legs"]}[n]["rerun"] is True for n in others), (
        f"其余五条腿应为 rerun=true（现取 {[(l['name'], l['rerun']) for l in ledger()['legs']]}）"
    )


# ══════════════════════════════════════════════════════════════════════════
# 三、四态（执行式：桩 `gh` + fixture 日志）
# ══════════════════════════════════════════════════════════════════════════

# 具名确定性闸门 —— 逐条各一个 fixture（与脚本的 `GATES` 表同锚点）。
GATE_LOGS = {
    "磁盘水位闸门": "构建前水位检查：磁盘可用 812 MB < 4096 MB\n::error::中止构建\n",
    "磁盘水位闸门-BUILD_MIN_FREE_MB": "BUILD_MIN_FREE_MB=4096 未满足\n磁盘水位闸门：跳过\n",
    "不可恢复终态闸门": "::error::该 commit 的部署落在不可恢复的终态（conclusion=failure）\n",
    "skip 自证": "同 sha 已有 success 的 run ⇒ 跳过本轮构建部署\n",
    "C 端产物陈旧判定": "线上产物 与 main HEAD 不一致（陈旧 33 天）\n",
    "依赖升级跳过": "dependabot[bot] 触发的 workflow 拿不到 secrets ⇒ 跳过\n",
}


def make_stub(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(GH_STUB, encoding="utf-8")
    gh.chmod(0o755)
    return bin_dir, gh


class React:
    """一次反应步执行的结果（读数：调用记录 / 退出码 / stdout）。"""

    def __init__(self, tmp_path: Path, *, conclusion: str, attempt: str,
                 leg: str = "Build and Deploy admin-api",
                 log_text: str | None = None, ledger_path: Path | None = None,
                 rerun_fail: bool = False):
        self.tmp = tmp_path
        self.bin_dir, _ = make_stub(tmp_path)
        self.calls = tmp_path / "gh-calls.log"
        self.issues = tmp_path / "issues.tsv"
        log_file = None
        if log_text is not None:
            log_file = tmp_path / "run.log"
            log_file.write_text(log_text, encoding="utf-8")
        env = os.environ.copy()
        env.update({
            "PATH": f"{self.bin_dir}{os.pathsep}{env['PATH']}",
            "GH_CALL_LOG": str(self.calls),
            "STUB_ISSUES": str(self.issues),
            "REACT_LEDGER": str(ledger_path if ledger_path is not None else LEDGER),
            "LEG_NAME": leg,
            "LEG_CONCLUSION": conclusion,
            "LEG_ATTEMPT": attempt,
            "LEG_RUN_ID": "999",
            "LEG_HEAD_SHA": "deadbeefcafe",
            "LEG_RUN_URL": "https://github.com/x/y/actions/runs/999",
        })
        if log_file is not None:
            env["REACT_LOG_FILE"] = str(log_file)
        if rerun_fail:
            env["STUB_RERUN_FAIL"] = "1"
        self.proc = subprocess.run([BASH, str(SCRIPT)], env=env,
                                   capture_output=True, text=True, timeout=120)

    @property
    def gh_calls(self) -> list:
        return self.calls.read_text(encoding="utf-8").splitlines() if self.calls.exists() else []

    def ran(self, needle: str) -> bool:
        return any(needle in c for c in self.gh_calls)

    @property
    def opened(self) -> list:
        if not self.issues.exists():
            return []
        return [l for l in self.issues.read_text(encoding="utf-8").splitlines() if l.strip()]

    @property
    def out(self) -> str:
        return self.proc.stdout + self.proc.stderr


def test_state1_failure_attempt1_no_gate_reruns_and_notifies(tmp_path):
    """① 失败类 + attempt1 + 日志无确定性闸门 ⇒ **重跑 + 通知**。"""
    r = React(tmp_path, conclusion="failure", attempt="1",
              log_text="普通失败：npm ci 超时\n")
    assert r.proc.returncode == 0, f"反应步必须 rc=0（不许判红）→ {r.proc.returncode}\n{r.out}"
    assert r.ran("run rerun 999"), f"没发起自动重跑 → {r.gh_calls}"
    assert r.ran("issue create"), f"没开值守单 → {r.gh_calls}"
    assert any("priority/P1" in c for c in r.gh_calls), f"值守单缺 priority/P1 → {r.gh_calls}"
    assert "已自动重跑一次" in r.out, f"动作行缺读数：{r.out!r}"


def test_state2_failure_attempt2_notifies_but_never_reruns(tmp_path):
    """② 失败类 + attempt2 ⇒ **只通知、不重跑**（自动重跑只做一次）。"""
    r = React(tmp_path, conclusion="failure", attempt="2", log_text="普通失败\n")
    assert r.proc.returncode == 0, f"→ {r.proc.returncode}"
    assert not r.ran("run rerun 999"), f"attempt2 仍重跑 ⇒ 断路器语义被破坏 → {r.gh_calls}"
    assert r.ran("issue create"), f"仍必须通知 → {r.gh_calls}"
    assert "不自动重跑" in r.out and "attempt" in r.out, f"动作行未说明原因：{r.out!r}"


@pytest.mark.parametrize("label", sorted(GATE_LOGS))
def test_state3_named_gate_suppresses_rerun_but_still_notifies(tmp_path, label):
    """③ 失败类 + attempt1 + 日志含**具名闸门** ⇒ **不重跑、但仍通知**（逐条 fixture）。"""
    r = React(tmp_path, conclusion="failure", attempt="1", log_text=GATE_LOGS[label])
    assert r.proc.returncode == 0, f"{label}: → {r.proc.returncode}"
    assert not r.ran("run rerun 999"), f"{label}: 命中具名闸门却仍重跑 → {r.gh_calls}"
    assert r.ran("issue create"), f"{label}: 仍必须通知 → {r.gh_calls}"
    assert "命中具名确定性闸门" in r.out, f"{label}: 动作行缺闸门读数：{r.out!r}"


def test_state4_success_clears_only(tmp_path):
    """④ success ⇒ **只清零**（不开单、不重跑）；已有开放单 ⇒ 评论 + 关闭。"""
    # 4a：无开放单 ⇒ 不开单、不评论、不重跑
    r = React(tmp_path / "a", conclusion="success", attempt="2")
    assert r.proc.returncode == 0, f"→ {r.proc.returncode}"
    assert not r.ran("issue create") and not r.ran("issue comment"), f"success 不该开单 → {r.gh_calls}"
    assert not r.ran("run rerun 999"), f"success 不该重跑 → {r.gh_calls}"
    assert "无开放单需要清零" in r.out, f"{r.out!r}"
    # 4b：**先种一张开放单**（标题与腿名匹配）⇒ 必须评论清零说明 + 关闭（清零不靠人记得）
    r2 = React(tmp_path / "b", conclusion="success", attempt="2")
    r2.issues.write_text(
        "7\t[deploy-leg] Build and Deploy admin-api 部署失败（合并后未上线）\topen\n",
        encoding="utf-8")
    proc = subprocess.run([BASH, str(SCRIPT)], env=r2_env(r2), capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, f"→ {proc.returncode}\n{proc.stdout}{proc.stderr}"
    calls = r2.calls.read_text(encoding="utf-8")
    assert "issue comment 7" in calls, f"success + 已有开放单 ⇒ 必须评论清零说明 → {calls!r}"
    assert "issue close 7" in calls, f"success + 已有开放单 ⇒ 必须关闭（清零不靠人记得）→ {calls!r}"
    assert "issue create" not in calls, f"已有开放单时不许重复开单（幂等）→ {calls!r}"


def r2_env(r) -> dict:
    """复用一次 `React` 的环境（同一份桩状态）—— 便于「先种单、再跑」的时序场景。"""
    env = os.environ.copy()
    env.update({
        "PATH": f"{r.bin_dir}{os.pathsep}{env['PATH']}",
        "GH_CALL_LOG": str(r.calls), "STUB_ISSUES": str(r.issues),
        "REACT_LEDGER": str(LEDGER),
        "LEG_NAME": "Build and Deploy admin-api", "LEG_CONCLUSION": "success",
        "LEG_ATTEMPT": "2", "LEG_RUN_ID": "999", "LEG_HEAD_SHA": "deadbeefcafe",
        "LEG_RUN_URL": "https://github.com/x/y/actions/runs/999",
    })
    return env


# ══════════════════════════════════════════════════════════════════════════
# 四、台账 fail-closed / 离线驱动面
# ══════════════════════════════════════════════════════════════════════════

def test_unregistered_leg_is_red(tmp_path):
    """判据 4：腿不在台账里 ⇒ 脚本**非零退出并具名**（未登记即红）。"""
    mini = tmp_path / "ledger.json"
    mini.write_text(json.dumps({"legs": [{"name": "Some Other Leg", "rerun": True, "reason": "x"}]}),
                    encoding="utf-8")
    r = React(tmp_path / "run", conclusion="failure", attempt="1", log_text="boom\n",
              leg="Unregistered Leg", ledger_path=mini)
    assert r.proc.returncode != 0, f"未登记的腿必须判红 → {r.proc.returncode}\n{r.out}"
    assert "未登记" in r.out, f"必须具名报出是哪条腿：{r.out!r}"
    assert not r.ran("run rerun 999"), f"未登记时不许有任何动作 → {r.gh_calls}"


def test_rerun_false_leg_notifies_without_rerun(tmp_path):
    """台账 `rerun=false` 的腿（c-end-h5）⇒ 通知但**不**重跑（发布由人手动）。"""
    r = React(tmp_path, conclusion="failure", attempt="1", log_text="Manual gate 判红\n",
              leg=C_END_LEG)
    assert r.proc.returncode == 0, f"→ {r.proc.returncode}"
    assert not r.ran("run rerun 999"), f"rerun=false 的腿不许自动重跑 → {r.gh_calls}"
    assert r.ran("issue create"), f"仍必须通知 → {r.gh_calls}"


def test_gate_detection_is_offline_and_calls_no_gh(tmp_path):
    """闸门检出走 `REACT_LOG_FILE` ⇒ **一次 `gh` 都不调**（可离线驱动）。"""
    log = tmp_path / "run.log"
    log.write_text("磁盘可用 12 MB\n::error::中止构建\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # 故意**不提供** `gh`：若脚本在闸门判定时调 `gh`，会走 `gh: command not found` ⇒ 判决变化
    # ⚠️ 但 `awk`/`grep`/`sed`/`tail` 是脚本解析台账与找锚点的**基本工具**（第 1 节实测踩过：
    #    只给一个空目录当 PATH ⇒ `awk: command not found` ⇒ 判据把「缺基本工具」当成「调了 gh」）。
    env = os.environ.copy()
    env.update({
        "PATH": f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin",
        "REACT_LEDGER": str(LEDGER), "REACT_LOG_FILE": str(log),
        "LEG_NAME": "Build and Deploy admin-api", "LEG_CONCLUSION": "failure",
        "LEG_ATTEMPT": "1", "LEG_RUN_ID": "999",
    })
    proc = subprocess.run([BASH, str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f"→ {proc.returncode}\n{proc.stdout}{proc.stderr}"
    out = proc.stdout + proc.stderr
    assert "命中具名确定性闸门" in out, f"没检出闸门（或以调 gh 的方式去取日志）→ {out!r}"
    assert "gh: command not found" not in out, f"闸门判定去调 `gh` 了（REACT_LOG_FILE 离线面失效）→ {out!r}"


# ══════════════════════════════════════════════════════════════════════════
# 五、判别力自证（内存变异 ⇒ 各自判红；只改注释 ⇒ 不红）
# ══════════════════════════════════════════════════════════════════════════

def _mut_run(body: str, tmp_path: Path, *, ledger_text: str | None = None,
             leg: str = "Build and Deploy admin-api", conclusion: str = "failure",
             attempt: str = "1", log_text: str = "普通失败\n") -> subprocess.CompletedProcess:
    """跑**变异版**反应步正文（红证用）。"""
    tmp_path.mkdir(parents=True, exist_ok=True)
    bin_dir, _ = make_stub(tmp_path)
    calls = tmp_path / "gh-calls.log"
    issues = tmp_path / "issues.tsv"
    script = tmp_path / "variant.sh"
    script.write_text(body, encoding="utf-8")
    env = os.environ.copy()
    env.update({
        "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
        "GH_CALL_LOG": str(calls), "STUB_ISSUES": str(issues),
        "REACT_LEDGER": str(LEDGER), "LEG_NAME": leg, "LEG_CONCLUSION": conclusion,
        "LEG_ATTEMPT": attempt, "LEG_RUN_ID": "999",
    })
    return subprocess.run([BASH, str(script)], env=env, capture_output=True, text=True, timeout=120)


def test_mutation_dropping_rerun_arm_is_detected(tmp_path):
    """判据 5a：摘掉**重跑臂** ⇒ 「重跑发生了」这条读数**当场变红**（对变异后的脚本真跑一次）。"""
    r = React(tmp_path / "real", conclusion="failure", attempt="1", log_text="普通失败\n")
    assert r.ran("run rerun 999"), f"前置不成立：真语料上重跑臂没生效 → {r.gh_calls}"
    # 变异：把 `_rerun_rc=0` 改成 `1`（= 旧形态：**失败不自愈**，只出声）
    old = SCRIPT.read_text(encoding="utf-8")
    broken = old.replace("  _rerun_rc=0\n", "  _rerun_rc=1\n", 1)
    assert broken != old, "注入未生效：脚本里找不到重跑那一行"
    variant = tmp_path / "no-rerun.sh"
    variant.write_text(broken, encoding="utf-8")
    env = r2_env(r)
    env.update({"LEG_CONCLUSION": "failure", "LEG_ATTEMPT": "1"})
    r.calls.unlink(missing_ok=True)   # 清掉真语料那一轮的读数（否则「摘掉后没有重跑」会被前一轮的记录掩盖）
    proc = subprocess.run([BASH, str(variant)], env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, f"反应步必须 rc=0 → {proc.returncode}"
    calls = r.calls.read_text(encoding="utf-8")
    assert "run rerun 999" not in calls, (
        f"摘掉重跑臂后**仍**发起了重跑 ⇒ 「重跑发生了」那条判据是空断言 → {calls!r}"
    )
    assert "已自动重跑一次" not in (proc.stdout + proc.stderr), "动作行仍宣称已重跑 ⇒ 读数与事实不符"


def test_rerun_refusal_is_reported_not_swallowed(tmp_path):
    """附加：`gh run rerun` 被拒（`actions: write` 不可用 / run 太旧）⇒ 进通知正文 + 不判红。"""
    r = React(tmp_path, conclusion="failure", attempt="1", log_text="普通失败\n", rerun_fail=True)
    assert r.proc.returncode == 0, f"反应步必须 rc=0 → {r.proc.returncode}"
    assert "**自动重跑尝试失败**" in r.out, f"重跑被拒必须如实写在通知正文里：{r.out!r}"
    assert r.ran("issue create"), f"重跑被拒仍必须通知 → {r.gh_calls}"


def test_mutation_dropping_notify_arm_is_detected(tmp_path):
    """判据 5b：摘掉**通知臂** ⇒ 调用记录里不再有 `issue create/comment`（判据 2 的读数锚）。"""
    r_normal = React(tmp_path / "normal", conclusion="failure", attempt="1", log_text="普通失败\n")
    assert r_normal.ran("issue create"), "前置不成立：真语料上通知臂没生效"
    # 变异：把 `notify "$ACTION"` 那一行摘掉（= notice-only 的旧形态）
    script_old = SCRIPT.read_text(encoding="utf-8")
    broken = script_old.replace('notify "$ACTION"', '', 1)
    assert broken != script_old, "注入未生效：脚本里找不到 `notify \"$ACTION\"`"
    variant = tmp_path / "no-notify.sh"
    variant.write_text(broken, encoding="utf-8")
    bin_dir, _ = make_stub(tmp_path / "no-notify")
    calls = tmp_path / "no-notify" / "gh-calls.log"
    log = tmp_path / "no-notify" / "run.log"
    log.write_text("普通失败\n", encoding="utf-8")
    env = os.environ.copy()
    env.update({
        "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}", "GH_CALL_LOG": str(calls),
        "STUB_ISSUES": str(tmp_path / "no-notify" / "issues.tsv"), "REACT_LEDGER": str(LEDGER),
        "LEG_NAME": "Build and Deploy admin-api", "LEG_CONCLUSION": "failure",
        "LEG_ATTEMPT": "1", "LEG_RUN_ID": "999", "REACT_LOG_FILE": str(log),
    })
    proc = subprocess.run([BASH, str(variant)], env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0
    text = calls.read_text(encoding="utf-8") if calls.exists() else ""
    assert "issue create" not in text and "issue comment" not in text, (
        f"摘掉通知臂后仍有开单/评论调用 ⇒ 「通知」那条判据是空断言 → {text!r}"
    )


def test_mutation_dropping_one_ledger_row_is_detected(tmp_path):
    """判据 5c：台账**删一行** ⇒ 双向相等判据当场红并具名报出缺哪条腿。"""
    real = ledger()
    legs_wf = _on_block(_doc())["workflow_run"]["workflows"]
    dropped = json.loads(json.dumps(real))
    dropped["legs"] = [l for l in dropped["legs"] if l["name"] != "Build and Deploy admin-api"]
    led = [l["name"] for l in dropped["legs"]]
    assert set(legs_wf) != set(led), "删一行后台账与 workflow_run 竟然还相等 ⇒ 那条判据是空断言"
    missing = set(legs_wf) - set(led)
    assert missing == {"Build and Deploy admin-api"}, f"缺的腿具名可见（现取 {missing}）"
    # 脚本侧：该腿未登记 ⇒ 非零退出（fail-closed）
    mini = tmp_path / "ledger.json"
    mini.write_text(json.dumps(dropped, ensure_ascii=False), encoding="utf-8")
    r = React(tmp_path / "run", conclusion="failure", attempt="1", log_text="boom\n",
              leg="Build and Deploy admin-api", ledger_path=mini)
    assert r.proc.returncode != 0, "台账里没有这条腿 ⇒ 脚本必须判红"


def test_mutation_four_source_lines_is_detected():
    """判据 5d：把 `source` 行改回 4 次 ⇒ 判据「恰好一次」当场红。"""
    body = reconcile_body()
    assert body.count("source scripts/deploy_reconcile_state.sh") == 1
    broken = body.replace("source scripts/deploy_reconcile_state.sh",
                          "source scripts/deploy_reconcile_state.sh\n" * 4, 1)
    assert broken.count("source scripts/deploy_reconcile_state.sh") == 4, "注入未生效"
    assert broken.count("source scripts/deploy_reconcile_state.sh") != 1, (
        "改回 4 次后计数仍等于 1 ⇒ 那条判据是空断言"
    )


def test_comment_only_change_does_not_red():
    """判据 5e（对照）：**只改注释 ⇒ 不红**（守卫不许被自己的文案喂红）。"""
    body = reconcile_body()
    mutated = body.replace("set -euo pipefail", "set -euo pipefail\n# 只加一行注释：source 仍然是 1 次",
                           1)
    assert mutated != body, "注入未生效"
    assert mutated.count("source scripts/deploy_reconcile_state.sh") == \
        body.count("source scripts/deploy_reconcile_state.sh") == 1, (
        "只加注释不该改变 `source` 计数"
    )
    # 尺寸面同理：注释不该把任何 step 顶过硬限
    assert len(mutated) < RUN_BODY_LIMIT, "加一行注释就把正文顶过 13,250 ⇒ 该 step 早该外置"
