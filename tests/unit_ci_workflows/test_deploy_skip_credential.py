# case_ids: MC-058
r"""部署腿「跳过 / 终态」判据的**凭据 + 自证**类级守卫（issue #5941）。

## 病（现取读数，不是推断）

三条 deploy 腿的 `Skip if already built (schedule reconcile)` 步用**同一次** `gh run list`
查询判定两件事：① C′「同 sha 已成功 ⇒ 跳过」② 「同 sha 有不可恢复终态 / 仍在跑 ⇒ 不重复派」。
`gh` 在 Actions runner 上**不读**任何配置文件（只认 `GH_TOKEN`），而三条 workflow：
workflow 级只有 `permissions: contents: read`、step 里**没有** `GH_TOKEN`
⇒ 查询恒失败，而代码是 `2>/dev/null || echo "[]"` ⇒ 失败被**整层吞掉**（本机实测 stderr 为空、
stdout=`[]`）⇒ `LAST_STATUS/LAST_CONCLUSION` 恒空 ⇒ 跳过臂**从未生效**。

实测（2026-10-01，run `36939400575`，`sha=3fa84ab`，事件 `schedule`）：
该 run 的 step env 块里逐字**没有** `GH_TOKEN`，输出逐字是「最近一次同 sha 的 run 结论 = `无记录`」
⇒ 走 else 全量构建部署（6~8min）；而同一 sha 在 **19:04:47Z 已完整部署成功过一次**。

## 本文件锁的四件事

| # | 判据 | 变红的形态 |
|---|---|---|
| 1 | **凭据可用**（类级，自动发现面）：`.github/workflows/deploy-*.yml` 里**每一步**跑 `gh run list` 的 step，都必须「step 级有 `GH_TOKEN`/`GITHUB_TOKEN`」**且**「该 workflow 有 `actions: read|write`」 | 新接一条查询却不给凭据 ⇒ 红（**未接即红**，不靠人记得） |
| 2 | **自证输出**（跳过腿）：正文必须逐字含凭据自检 `gh auth status`、查询 `exit code`、**返回条数**、`::warning::`、fail-open **具名**（`跳过判据**不可用**`）与 `GITHUB_STEP_SUMMARY`；且 `gh run list` 那一行**不得**再挂 `2>/dev/null` | 把静默写回来 / 删掉任一条自证 ⇒ 红 |
| 3 | **登记面**：写 `skip=` 的跳过腿必须登记进 `deploy_skip_credential_ledger.json`（**双向**）；豁免只许缩短（上界冻结在 `EXEMPTIONS_FROZEN`，现取 0） | 新加跳过腿不登记 / 偷偷加豁免 ⇒ 红 |
| 4 | **行为面（执行式，桩 `gh`/`docker`）**：a) 无凭据 ⇒ **出声 + fail-open 具名 + `skip=false`**（照旧部署，不许改成停部署）b) 同 sha 已 success（且本轮 run 自己 in_progress）⇒ `skip=true` + step summary 写明 C′ 理由 c) 同 sha 另一条在跑 ⇒ `skip=true` | 见各测试：a 是「静默吞掉」的回归，b 是「跳过臂形同不存在」的回归 |

## 为什么 b) 里要塞一条「本轮 run 自己」

本机现取（2026-10-02）：`gh run list` 把**当前 in_progress 的 run** 排在 `[0]`
⇒ 不排除自己时 `[.. | select(.headSha == $s)][0]` **永远取到「自己」** ⇒ C′ 的
`completed + success` 恒不成立（会被「尚未跑完」闸门接住，**理由却是错的**：它把
`status=in_progress` 打成「不可恢复的终态」）。实测复算（同一份真实数据，改前正文 +
桩凭据）：`⛔ … 不可恢复的终态（结论=status=in_progress（尚未跑完））` 且 **step summary 为空**。
⇒ 「光注入凭据」不够，正文还必须排除本轮 run 自己（`databaseId` vs `GITHUB_RUN_ID`）。

## 桩化的诚实标注（§28.2 边界）

`gh` / `docker` 是**桩**（读预设 JSON、记录调用）⇒ 本文件证明的是「workflow 在给定输入下
**会**做什么」，**不是**「GitHub 真的会这样返回」。真实凭据面（`actions: read` 的 token 能否
读到 runs）只有**真跑一次 CI** 才能验 —— 合并后第一个 schedule tick 的 step summary
（`skip=true` + 判据来源）就是那条读数；PR body 里已写明复核命令。
本文件零网络、不碰真实 ACR、不写仓外共享路径（产物全部落 pytest `tmp_path`）。
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
WF_DIR = REPO_ROOT / ".github" / "workflows"
LEDGER_PATH = Path(__file__).with_name("deploy_skip_credential_ledger.json")

SKIP_STEP = "Skip if already built (schedule reconcile)"
SYNC_JOB = "build-and-deploy"

# ── 判据 3 的冻结上界（**只许缩短**）：现取 0 条豁免。台账改不动它。
EXEMPTIONS_FROZEN = 0

# ── 判据 2 的逐字锚点（自证面 = 本单的交付物，改写即红）
CRED_ENV_KEYS = ("GH_TOKEN", "GITHUB_TOKEN")
CRED_PERMISSION_SCOPES = ("read", "write")
AUTH_ANCHOR = "gh auth status exit=${AUTH_RC}"
QUERY_EXIT_ANCHOR = "gh run list exit=${QR_RC}"
ROWCOUNT_ANCHOR = "原始 ${RAW_ROWS} 条"
WARNING_ANCHOR = "::warning::"
FAIL_OPEN_NAMED_ANCHOR = "跳过判据**不可用**"
SUMMARY_ANCHOR = "GITHUB_STEP_SUMMARY"
SELF_RUN_EXCLUSION_ANCHOR = 'select((.databaseId // 0 | tostring) != $rid)'
SILENCE_MARKER = "2>/dev/null"

# 执行式判据用的桩（零网络）：`docker manifest inspect` 恒失败 = C′ 之后的实况（CI 不推 ACR）
DOCKER_STUB = """#!/bin/bash
# 桩 docker：C′ 之后 CI 不推 ACR ⇒ 镜像探针恒不命中（与生产实况同形）
exit 1
"""

# 桩 gh：三种形态由环境变量驱动 —— ① 无凭据（runner 实况：exit=4 + 逐字 stderr）
# ② 有凭据（cat 预设 JSON）③ auth status 自检
GH_STUB = """#!/bin/bash
set -u
case "${1:-} ${2:-}" in
  "auth status")
    if [ "${STUB_GH_CRED:-ok}" = "missing" ]; then
      echo "You are not logged into any GitHub hosts. To log in, run: gh auth login" >&2
      exit 1
    fi
    echo "github.com"
    echo "  ✓ Logged in to github.com account ci (GH_TOKEN)"
    exit 0
    ;;
  "run list")
    if [ "${STUB_GH_CRED:-ok}" = "missing" ]; then
      echo "To get started with GitHub CLI, please run:  gh auth login" >&2
      echo "Alternatively, populate the GH_TOKEN environment variable with a GitHub API authentication token." >&2
      exit 4
    fi
    cat "${STUB_GH_RUNS:-/dev/null}"
    exit 0
    ;;
esac
echo "stub gh: unexpected args: $*" >&2
exit 127
"""


# ══════════════════════════════════════════════════════════════════════════
# 现取面：deploy-*.yml 里每一步「跑 gh run list」的 step
# ══════════════════════════════════════════════════════════════════════════

def _on_block(doc: dict) -> dict:
    """YAML 1.1 里裸 `on` 被 PyYAML 解析成布尔 True（已知坑）⇒ 两种键都试。"""
    on = doc.get("on")
    return on if on is not None else doc.get(True, {})


def load_ledger() -> dict:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def query_steps(docs: dict[str, dict] | None = None) -> list[dict]:
    """现取：`deploy-*.yml` 里每一步**跑 `gh run list`** 的 step。

    返回 [{workflow, job, step, writes_skip, env_keys, permissions, run}]。
    射程 = 文件名字面 `deploy-*.yml`（本仓现取 5 步：3 条跳过腿 + reconcile 2 步）。
    """
    if docs is None:
        docs = {f".github/workflows/{p.name}": yaml.safe_load(p.read_text(encoding="utf-8"))
                for p in sorted(WF_DIR.glob("deploy-*.yml"))}
    out = []
    for name, doc in sorted(docs.items()):
        if not isinstance(doc, dict):
            continue
        for job, jd in (doc.get("jobs") or {}).items():
            if not isinstance(jd, dict):
                continue
            for s in (jd.get("steps") or []):
                if not isinstance(s, dict) or not isinstance(s.get("run"), str):
                    continue
                if "gh run list" not in s["run"]:
                    continue
                out.append({
                    "workflow": name,   # 仓库相对路径（与台账 / 引用纪律同一形态）
                    "job": job,
                    "step": str(s.get("name")),
                    "writes_skip": bool(re.search(r"\bskip=", s["run"])),
                    "env_keys": sorted((s.get("env") or {}).keys()),
                    "permissions": {k: str(v) for k, v in (doc.get("permissions") or {}).items()}
                    if isinstance(doc.get("permissions"), dict) else {},
                    "run": s["run"],
                })
    return out


def skip_legs(steps: list[dict]) -> list[dict]:
    """「跳过腿」= 既查 `gh run list` 又写 `skip=` 的 step（现取 3 条）。"""
    return [s for s in steps if s["writes_skip"]]


# ══════════════════════════════════════════════════════════════════════════
# 判据本体（纯函数，可在内存变异上重放 —— 注入式红证即调它）
# ══════════════════════════════════════════════════════════════════════════

def credential_problems(steps: list[dict]) -> list[str]:
    """判据 1：每条查询步都必须「step 有 token env」+「workflow 有 actions 权限」。"""
    problems = []
    for s in steps:
        tag = f"{s['workflow']} :: {s['job']} :: {s['step']}"
        if not any(k in s["env_keys"] for k in CRED_ENV_KEYS):
            problems.append(
                f"{tag}：该 step 跑 `gh run list` 却**没有**凭据 env（需 {' / '.join(CRED_ENV_KEYS)}）"
                f"—— `gh` 在 Actions 环境只认 GH_TOKEN（runner 上没有 hosts.yml）⇒ 查询恒失败")
        scope = s["permissions"].get("actions")
        if scope not in CRED_PERMISSION_SCOPES:
            problems.append(
                f"{tag}：该 workflow 的 `permissions` 里 `actions` = {scope!r}（需 read 或 write）"
                f"—— workflow 级 permissions 一旦显式声明，未列出的作用域一律为 none ⇒ "
                f"即使注入了 token 也读不到 runs")
    return problems


def query_statement(body: str) -> str:
    """取出第一条 `gh run list` 语句（含续行 `\\`）—— 静默检查必须看**整条语句**：
    改前那条 `2>/dev/null` 落在**续行**上，逐行扫会漏（本判据自己的第一版就漏了）。"""
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if "gh run list" not in line:
            continue
        stmt = [line]
        j = i
        while stmt[-1].rstrip().endswith("\\") and j + 1 < len(lines):
            j += 1
            stmt.append(lines[j])
        return "\n".join(stmt)
    return ""


def self_proof_problems(steps: list[dict]) -> list[str]:
    """判据 2：跳过腿的正文必须带自证面，且不得再把失败静默掉。"""
    problems = []
    anchors = (AUTH_ANCHOR, QUERY_EXIT_ANCHOR, ROWCOUNT_ANCHOR, WARNING_ANCHOR,
               FAIL_OPEN_NAMED_ANCHOR, SUMMARY_ANCHOR, SELF_RUN_EXCLUSION_ANCHOR)
    for s in skip_legs(steps):
        tag = f"{s['workflow']} :: {s['job']} :: {s['step']}"
        for a in anchors:
            if a not in s["run"]:
                problems.append(f"{tag}：正文里找不到自证锚点 {a!r}（issue #5941 判据 1/3）")
        stmt = query_statement(s["run"])
        if not stmt:
            problems.append(f"{tag}：正文里找不到 `gh run list` 查询语句（判据已过期）")
        elif SILENCE_MARKER in stmt:
            problems.append(
                f"{tag}：`gh run list` 这条语句仍挂着 {SILENCE_MARKER}（静默吞掉失败 = 本单的病）："
                f"{stmt.strip()}")
    return problems


def ledger_problems(ledger: dict, steps: list[dict]) -> list[str]:
    """判据 3：跳过腿 ⇄ 台账**双向**登记；豁免只许缩短且必须具名理由。"""
    problems = []
    live = {(s["workflow"], s["job"], s["step"]) for s in skip_legs(steps)}
    registered = {(e.get("workflow"), e.get("job"), e.get("step")) for e in ledger.get("legs", [])}
    for missing in sorted(live - registered):
        problems.append(f"跳过腿未登记进 {LEDGER_PATH.name}（未登记即红）：{missing}")
    for stale in sorted(registered - live):
        problems.append(f"台账登记了一条**不存在**的跳过腿（陈旧登记）：{stale}")
    exemptions = ledger.get("exemptions", [])
    if len(exemptions) > EXEMPTIONS_FROZEN:
        problems.append(
            f"豁免条数 {len(exemptions)} > 冻结上界 {EXEMPTIONS_FROZEN}（**只许缩短**；"
            f"加豁免 = 把凭据/自证面绕过去）")
    for e in exemptions:
        key = (e.get("workflow"), e.get("job"), e.get("step"))
        if not e.get("why") or not e.get("exit_if"):
            problems.append(f"豁免必须写明 `why` + `exit_if`（何时必须修）：{key}")
        if key in live:
            problems.append(f"豁免与登记自相矛盾（同一条腿既登记又被豁免）：{key}")
    for entry in ledger.get("coverage_boundary", []):
        if not all(entry.get(k) for k in ("face", "reason", "recompute")):
            problems.append(f"coverage_boundary 条目缺 face/reason/recompute：{entry!r}")
    return problems


# ══════════════════════════════════════════════════════════════════════════
# 判据 1~3 的真语料
# ══════════════════════════════════════════════════════════════════════════

def test_real_corpus_is_present_and_wired():
    """①~③ 在**当前语料**上全绿 + 反空跑锚点（现取 5 条查询步 / 3 条跳过腿）。"""
    steps = query_steps()
    assert len(steps) >= 5, (
        f"反空跑锚点：只取到 {len(steps)} 条 `gh run list` 查询步（判据已过期）—— "
        f"现取应为 3 条跳过腿 + reconcile 的 2 步")
    assert len(skip_legs(steps)) == 3, (
        f"反空跑锚点：写 `skip=` 的跳过腿现取应为 3 条，实际 {len(skip_legs(steps))}")
    assert not credential_problems(steps), "\n".join(credential_problems(steps))
    assert not self_proof_problems(steps), "\n".join(self_proof_problems(steps))
    assert not ledger_problems(load_ledger(), steps), "\n".join(ledger_problems(load_ledger(), steps))


def test_reconcile_query_steps_also_have_credentials():
    """① 的**具名**读数：reconcile 那两步（不在跳过腿里）也必须已有凭据 —— 本判据不是空跑。"""
    steps = query_steps()
    by_name = {s["step"]: s for s in steps}
    assert "Reconcile deploys" in by_name, f"现取面里应含 reconcile 的查询步：{sorted(by_name)}"
    for s in steps:
        if s["workflow"] == ".github/workflows/deploy-reconcile.yml":
            assert "GH_TOKEN" in s["env_keys"] and s["permissions"].get("actions") in CRED_PERMISSION_SCOPES, (
                f"{s['step']}：reconcile 的凭据面被拆掉了 ⇒ {credential_problems([s])}")


# ══════════════════════════════════════════════════════════════════════════
# 判别力自证：在**真文件文本**上做内存变异 ⇒ 判据必须红；只改注释 ⇒ 不红
# ══════════════════════════════════════════════════════════════════════════

LEG = ".github/workflows/deploy-frontend.yml"


def _mutate(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, f"注入锚点命中 {text.count(old)} 次（期望 1）：{old!r}"
    return text.replace(old, new)


def _audit_text(text: str, name: str = LEG) -> list[str]:
    """把变异后的这一份**替换进真语料**再审计：else 双向登记判据会因为「只剩一条腿」而噪声红
    （那不是变异造成的，会让「只改注释 ⇒ 不红」的对照读数失效）。"""
    docs = {f".github/workflows/{p.name}": yaml.safe_load(p.read_text(encoding="utf-8"))
            for p in sorted(WF_DIR.glob("deploy-*.yml"))}
    assert name in docs, f"变异对象不在现取面里：{name} ∈ {sorted(docs)}"
    docs[name] = yaml.safe_load(text)
    steps = query_steps(docs)
    return (credential_problems(steps) + self_proof_problems(steps)
            + ledger_problems(load_ledger(), steps))


def _red_proof(old: str, new: str, expect: str):
    """拿掉/注入某个形态 ⇒ 判据必须**具名**报出它（且注入确实生效）。"""
    text = (REPO_ROOT / LEG).read_text(encoding="utf-8")
    mutated = _mutate(text, old, new)
    assert mutated != text, "注入未生效（判别力自证）"
    problems = _audit_text(mutated)
    assert any(expect in p for p in problems), (
        f"注入后判据未报出 {expect!r}（= 空断言）⇒ problems={problems}")


@pytest.mark.parametrize("old,new,expect", [
    # ① 拿掉 step 级凭据注入 ⇒ 凭据判据必须红
    ("          GH_TOKEN: ${{ github.token }}\n", "",
     "却**没有**凭据 env"),
    # ① 拿掉 workflow 级 actions 权限（改成 actions: none）⇒ 凭据判据必须红
    ("  actions: read\n", "  actions: none\n",
     "`actions` = 'none'"),
    # ② 删掉「返回条数」自证 ⇒ 自证判据必须红
    ('            echo "gh run list exit=${QR_RC} · 原始 ${RAW_ROWS} 条 · 排除本轮 run（${GITHUB_RUN_ID:-?}）后 ${ROWS} 条"\n', "",
     "找不到自证锚点"),
    # ② 删掉 fail-open 具名 ⇒ 自证判据必须红
    ('                echo "::warning::跳过判据**不可用**（gh run list exit=${QR_RC}，返回 ${ROWS} 条，stderr 见上）⇒ **本轮全量部署**（fail-open：本检查自己出错绝不停掉部署）"\n',
     "",
     "找不到自证锚点"),
    # ② 把 `2>/dev/null` 静默写回去 ⇒ 自证判据必须红
    ('2>"$QR_ERR_FILE") || QR_RC=$?', "2>/dev/null) || QR_RC=$?" ,
     "仍挂着 2>/dev/null"),
    # ② 删掉「排除本轮 run 自己」⇒ 自证判据必须红（锚点消失）
    (SELF_RUN_EXCLUSION_ANCHOR, "select(true)",
     "找不到自证锚点"),
])
def test_injections_turn_the_criteria_red(old, new, expect):
    """🔴 注入式红证（**在真文件文本上**做内存变异）：六种坏形态各自判红且**具名**。"""
    _red_proof(old, new, expect)


def test_comment_only_change_stays_green():
    """✅ 对照读数：只加一条注释 ⇒ 判据**不**红（防判据被自己的文案喂红）。"""
    text = (REPO_ROOT / LEG).read_text(encoding="utf-8")
    mutated = _mutate(text, "permissions:\n", "# 无关注释（对照）\npermissions:\n")
    assert _audit_text(mutated) == [], f"只加注释不该判红：{_audit_text(mutated)}"


def test_ledger_exemption_growth_is_red():
    """🔴 台账豁免只许缩短：凭空加一条豁免 ⇒ 红（防「绕过去」）。"""
    ledger = dict(load_ledger())
    ledger["exemptions"] = [{"workflow": LEG, "job": SYNC_JOB, "step": SKIP_STEP,
                             "why": "凭空加", "exit_if": "永不"}]
    problems = ledger_problems(ledger, query_steps())
    assert any("只许缩短" in p for p in problems), problems


# ══════════════════════════════════════════════════════════════════════════
# 判据 4：行为面（执行式 —— 真跑 step 正文 + 桩 gh/docker）
# ══════════════════════════════════════════════════════════════════════════

SHA = "3fa84ab89eb9f5670f58a019506c7567c44f17a6"      # 真实读数里的 sha（run 36939400575）
RUN_ID = "36939400575"                                  # 真实 run id（本轮 run 自己）
WORKFLOW_NAME = "Build and Deploy frontend (admin-web)"

LEGS = ("deploy-admin-api.yml", "deploy-ai-agent-service.yml", "deploy-frontend.yml")


def _step_body(leg: str) -> str:
    doc = yaml.safe_load((WF_DIR / leg).read_text(encoding="utf-8"))
    for s in doc["jobs"][SYNC_JOB]["steps"]:
        if s.get("name") == SKIP_STEP:
            body = s.get("run")
            assert isinstance(body, str) and body.strip(), f"{leg}: 跳过步没有正文（判据已过期）"
            return body
    raise AssertionError(f"{leg}: 找不到跳过步 `{SKIP_STEP}`（判据已过期）")


def render(leg: str, body: str | None = None) -> str:
    """把跳过步正文渲染成可直接跑的 bash（只替换 `${{ env.* }}`，其余靠环境变量）。"""
    raw = _step_body(leg) if body is None else body
    rendered = (raw.replace("${{ env.ACR_REGISTRY }}", "acr.example.com")
                   .replace("${{ env.ACR_NAMESPACE }}", "ns")
                   .replace("${{ env.IMAGE_NAME }}", "svc"))
    assert "${{" not in rendered, f"{leg}: 渲染后仍有 `${{{{ … }}}}` 残留（判据已过期）"
    return rendered


def run_step(leg: str, tmp_path: Path, *, cred: str, runs: list | None = None,
             body: str | None = None) -> tuple[int, str, str, dict]:
    """真跑渲染后的正文（桩 gh/docker）。返回 (rc, 输出, step summary, outputs)。"""
    bindir = tmp_path / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    for name, content in (("docker", DOCKER_STUB), ("gh", GH_STUB)):
        p = bindir / name
        p.write_text(content, encoding="utf-8")
        p.chmod(0o755)
    runs_file = tmp_path / "runs.json"
    runs_file.write_text(json.dumps(runs if runs is not None else []), encoding="utf-8")
    outputs_file = tmp_path / "github_output"
    outputs_file.write_text("", encoding="utf-8")
    summary_file = tmp_path / "summary.md"
    script = tmp_path / "step.sh"
    script.write_text("set -euo pipefail\n" + render(leg, body), encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_SHA": SHA,
        "GITHUB_WORKFLOW": WORKFLOW_NAME,
        "GITHUB_RUN_ID": RUN_ID,
        "GITHUB_EVENT_NAME": "schedule",
        "GITHUB_OUTPUT": str(outputs_file),
        "GITHUB_STEP_SUMMARY": str(summary_file),
        "EVENT_NAME": "schedule",
        "INPUT_IMAGE_TAG": "",
        "STUB_GH_CRED": cred,
        "STUB_GH_RUNS": str(runs_file),
    }
    proc = subprocess.run(["bash", str(script)], cwd=str(tmp_path), env=env,
                          capture_output=True, text=True, timeout=120)
    outputs = {}
    for line in outputs_file.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            outputs[k] = v
    summary = summary_file.read_text(encoding="utf-8") if summary_file.exists() else ""
    return proc.returncode, proc.stdout + proc.stderr, summary, outputs


def self_record(sha: str = SHA, rid: str = RUN_ID, status: str = "in_progress",
                conclusion: str = "") -> dict:
    return {"databaseId": int(rid), "headSha": sha, "status": status, "conclusion": conclusion}


@pytest.mark.parametrize("leg", LEGS)
def test_no_credentials_must_speak_up_and_stay_fail_open(leg, tmp_path):
    """🔴 判据 4-a：**无凭据**（runner 实况：`gh` 两个子命令都失败）⇒ 必须**出声**且**照旧部署**。

    该形态就是本单的病：改前 `2>/dev/null || echo "[]"` 把 exit=4 + stderr 全吞掉 ⇒ 只有一行
    「无记录」⇒ 全量部署。本测试要求：① 打出凭据自检与查询 exit code、② 把 stderr **原文**
    打出来（`::warning::`）、③ 具名写出「跳过判据不可用 ⇒ 本轮全量部署」并落 step summary、
    ④ **`skip=false`（fail-open 保持：本检查自己出错绝不停掉部署）** —— 四者缺一即红。
    """
    rc, out, summary, outputs = run_step(leg, tmp_path, cred="missing")
    assert rc == 0, f"{leg}: 判据不可用不得让 step 失败（fail-open），实际 rc={rc}\n{out}"
    assert outputs.get("skip") == "false", (
        f"{leg}: 判据不可用时必须照旧全量部署（skip=false），实际 {outputs!r}\n{out}")
    assert "gh auth status exit=1" in out, f"{leg}: 必须打印凭据自检的 exit code（且它是 1）\n{out}"
    assert "gh run list exit=4" in out, f"{leg}: 必须打印查询的 exit code（runner 实测 = 4）\n{out}"
    assert "To get started with GitHub CLI" in out, (
        f"{leg}: 必须把 gh 的 stderr **原文**打出来（不许再静默）\n{out}")
    assert "::warning::" in out and FAIL_OPEN_NAMED_ANCHOR in out, (
        f"{leg}: fail-open 必须**具名**（`跳过判据**不可用**` + `::warning::`）\n{out}")
    assert "原始 0 条" in out, f"{leg}: 必须打印返回条数（0 条 = 判据不可用）\n{out}"
    assert "跳过判据" in summary and "fail-open" in summary, (
        f"{leg}: step summary 必须写明「判据不可用 ⇒ 本轮全量部署」\n{summary!r}")
    assert "执行完整构建部署" in out, f"{leg}: 仍要照旧走全量部署路径\n{out}"


@pytest.mark.parametrize("leg", LEGS)
def test_same_sha_already_deployed_skips_with_summary(leg, tmp_path):
    """🔴 判据 4-b：同 sha **已 success** ⇒ `skip=true` + summary 写明 C′ 理由。

    数据 = 真实读数的形状：本轮 run 自己（`databaseId` = `$GITHUB_RUN_ID`）是 `in_progress`，
    同 sha 上一条（run 36911623109，19:04:47Z）`completed + success`。
    ⚠️ 若正文不排除「本轮 run 自己」，`[0]` 就是自己 ⇒ C′ 臂恒不成立（改前实测 = 落到
    「不可恢复的终态」那一臂、**summary 为空**、理由还是错的）⇒ 本测试即那条回归的红证。
    """
    runs = [self_record(),
            {"databaseId": 36911623109, "headSha": SHA, "status": "completed",
             "conclusion": "success"}]
    rc, out, summary, outputs = run_step(leg, tmp_path, cred="ok", runs=runs)
    assert rc == 0, f"{leg}: rc={rc}\n{out}"
    assert outputs.get("skip") == "true", (
        f"{leg}: 同 sha 的部署已成功 ⇒ 必须 skip=true（否则每次 cron 都全量重建重部署），"
        f"实际 {outputs!r}\n{out}")
    assert "已成功" in out and "C′" in out, f"{leg}: 跳过理由必须点名 C′ 与「已成功」\n{out}"
    assert "原始 2 条" in out and "后 1 条" in out, (
        f"{leg}: 自证面必须显示「排除了本轮 run 自己」（2 → 1）\n{out}")
    assert "跳过" in summary and "C′" in summary, (
        f"{leg}: C′ 跳过的理由必须落 step summary（判据 4 的验收读数）\n{summary!r}")


@pytest.mark.parametrize("leg", LEGS)
def test_same_sha_sibling_still_running_is_not_dispatched_again(leg, tmp_path):
    """🔴 判据 4-c：同 sha 的**另一条** run 还在跑 ⇒ 不重复派（`skip=true`），语义不许被削弱。"""
    runs = [self_record(),
            {"databaseId": 36911623109, "headSha": SHA, "status": "in_progress",
             "conclusion": ""}]
    rc, out, _summary, outputs = run_step(leg, tmp_path, cred="ok", runs=runs)
    assert rc == 0, f"{leg}: rc={rc}\n{out}"
    assert outputs.get("skip") == "true", (
        f"{leg}: 同 sha 已有 run 在跑 ⇒ 重复 dispatch 是纯 churn，必须跳过；实际 {outputs!r}\n{out}")
    assert "尚未跑完" in out, f"{leg}: 必须点名「在跑」这个理由\n{out}"


@pytest.mark.parametrize("leg", LEGS)
def test_self_run_exclusion_injection_turns_the_criterion_red(leg, tmp_path):
    """🔴 **注入式红证（同文件、行为面）**：拿掉「排除本轮 run 自己」⇒ 判据 4-b 必红。

    注入 = 把 `select((.databaseId // 0 | tostring) != $rid)` 换成 `select(true)`
    （= 改前形态：`[0]` 就是本轮 run 自己；⚠️ **不能**换成裸 `true` —— 那会得到
    `[.[] | true]` = `[true, true]`，记录被 jq 打烂，不是「改前形态」）。
    注入后**必须**复现「C′ 臂不成立、summary 为空」这一形态 —— 否则 4-b 的断言就是空断言。
    """
    body = _step_body(leg)
    injected = body.replace(SELF_RUN_EXCLUSION_ANCHOR, "select(true)")
    assert injected != body, f"{leg}: 注入未生效（自排除锚点已漂移）"
    runs = [self_record(),
            {"databaseId": 36911623109, "headSha": SHA, "status": "completed",
             "conclusion": "success"}]
    rc, out, summary, outputs = run_step(leg, tmp_path, cred="ok", runs=runs, body=injected)
    assert rc == 0, f"{leg}: rc={rc}\n{out}"
    assert "C′" not in summary, (
        f"{leg}: 注入后**不该**再有 C′ 的 summary（说明注入没生效 / 判据 4-b 是空断言）\n{summary!r}")
    assert "不可恢复的终态" in out, (
        f"{leg}: 注入后应复现改前形态（[0] = 自己在跑 ⇒ 落到「不可恢复的终态」那一臂，"
        f"**理由错**：in_progress 不是终态）\n{out}")
    assert "已成功" not in out, f"{leg}: 注入后不该出现 C′ 的「已成功」理由\n{out}"
