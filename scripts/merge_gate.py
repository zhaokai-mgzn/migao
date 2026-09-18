#!/usr/bin/env python3
"""merge_gate.py — 关联 #4248「报告型判据判红**不拦**合并」的元判据 + 合并闸门判定。

## 病根（实测级，有前后对照）

本仓库用 GitHub **native auto-merge**：`automerge.yml` 在 PR `opened` 时 `gh pr merge --auto`，
之后 GitHub **在 required checks 全绿时自动 squash 合并**。判定依据 = **分支保护里的 required 集合**；
而 `Drift Audit (真相源契约)` / `Case Trust Gate (断言可信度)` 等**报告型**判据（打印结论 + 评论/开单）
**不在 required 集合** ⇒ **判红不拦合并**，而 PR 页面上红/绿与 required 判据长得一样
⇒ 极易被读成「绿 = 可以合」。

实证（只读读回，勿当"少了一道检查"读）：关联 #4214 的 `Drift Audit` = fail 而该 PR 仍 MERGED；
#4266 / #4267 / #4271 同款复发 —— 三条都带着 `Drift Audit` 红被合入。

## 两个子命令（三态退出码 0/1/3，**默认只读**）

    # ① 元判据：required 集合 vs 「实际存在且会判红」的 job 集合 的差集
    python3 scripts/merge_gate.py --required-diff
    # ② 合并闸门：某 PR 的 checks 里是否有「红了也照合」的裸判据
    python3 scripts/merge_gate.py --check <PR号> [--apply-label] [--no-disarm-auto]

    0 = 未命中（差集为空 / 无裸判据红 / 已被 required 拦 / 已有 block/merge）
    1 = **命中**（① 存在裸判据；② 裸判据红且 PR 处于可合并态，或已带红合入）
    3 = **无法判定**（gh 不可用 / API 报错 / 读不到 required 集合 / 读不到工作流 / mergeStateStatus 重算中）
        —— 「看不了」**绝不**谎报成 0（与 `scripts/red_proof.py` / `scripts/resolve_stale_bot_threads.py` 同口径）

## 报告型清单：**反推**，不硬编码（可自证、随仓库演化自适应）

「不在 required 集合里的、且实际会判红的 job」= 报告型 ⇒ **无需维护一份会腐烂的名单**：
新增一条判据、或某条被翻成 required，本脚本下次运行自动跟上。
若改成硬编码，必须同时加一条「清单里的每个名字都真实存在于工作流里」的断言 —— 本实现不选这条路。

## 写操作边界（不得越级）

- **默认 dry-run**：`--check` 只读，与 `scripts/delete_orders.py` / `resolve_stale_bot_threads.py` 同风格。
- `--apply-label` 才落闸（**只在命中 + PR 仍 OPEN** 时），且**绝不**把任何判据翻成 required、
  **绝不**改任何 workflow。
- **`--apply-label` 默认同时 disarm**（`gh pr merge <PR> --disable-auto`，仅在 auto-merge **已 arm** 时调用）
  —— 语义上「打 `block/merge`」= 「拦住合并」，只打标签等于**没拦住**。实测（关联 #4334）：
  关联 #4271 的 `autoMergeRequest.enabledAt = 07:03:18Z`、标签 `07:03:19Z`（晚 1 秒）、**合并 `07:07:22Z`**；
  关联 #4266 标签 `06:57:32Z`、**合并 `07:00:30Z`**（两条至今仍带着该标签却已 MERGED）。
  根因：`automerge.yml` 的 `if:`（含 `!contains(labels,'block/merge')`）**只在 arm 时**生效，
  `labeled` 事件重跑时 `if` 为假 ⇒ **什么也不做**（不会 disarm）。⇒ 只有 `--disable-auto` 能停住它。
- 未 arm 时**只打标签即可**（无需 disarm）：标签会让 `automerge.yml` 在后续事件上**永不 arm**。
- **逃生口 `--no-disarm-auto`**：只打标签、跳过 disarm，并在输出里**明写**
  「已 arm 的 auto-merge 不会被本标签拦住」（不做静默降级）。
- `--disarm-auto` 已被并入默认行为，但**仍被接受**（关联 #4325 登记的接线命令里含它，不破既有命令行）。

## 保留类登记（issue #4248 裁定 C；**本 PR 不改任何 workflow**）

本机 gh token **无 `workflow` scope**（实测 scopes = `repo / gist / read:org / admin:public_key`）
⇒ 创建/修改 `.github/workflows/**` 会被 GitHub 拒绝推送。故**判定本体落成可复用脚本**，
workflow 接线登记为**保留类**：

- **拿到 scope 后只需加这一步**（挂在 PR 事件上的独立 job，或并入 `drift-audit.yml` 同族）：
  ```yaml
  - name: 裸判据合并闸门
    if: always()
    env: { GH_TOKEN: '${{ github.token }}' }
    run: python3 scripts/merge_gate.py --check ${{ github.event.pull_request.number }} --apply-label
  ```
  （`--apply-label` 已含「打 `block/merge` + 解除已 arm 的 auto-merge」两步，无需再写 `--disarm-auto`；
  退出码 1 时该 job 判红、3 时判红 —— 判定本体 fail-closed，不靠 job 的 `continue-on-error`。）
- **不依赖 workflow 的替代路径**（今天就能用，无需 scope）：合并前由人 / 主会话直接跑
  `python3 scripts/merge_gate.py --check <PR>`（只读三态），命中则
  `python3 scripts/merge_gate.py --check <PR> --apply-label`；或把它接进 `verify-all.sh` 同族的本地检查
  （本 PR 不改该脚本）。

## 自测红证

`tests/unit_ci_workflows/test_merge_gate.py`（case_ids: MC-012）：夹具层 ①~⑧ 共 29 条
（裸判据红 ⇒ 1 / 全绿 ⇒ 0 / required 红 ⇒ 0 / 三态 ⇒ 3 / 元判据三态 / 不硬编码 /
写操作边界：默认 disarm + `--no-disarm-auto` 逃生口 + dry-run 零写），
`gh` 用**替身可执行文件**注入（CLI 边界即注入点，`MG_GH_BIN`）。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import namedtuple
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - 环境缺 PyYAML 时 fail-closed（退 3，不猜）
    yaml = None

EXIT_OK = 0
EXIT_HIT = 1
EXIT_UNDECIDABLE = 3

# 仓库的**人工闸**标签（`.github/workflows/automerge.yml` 的 `if:` 会跳过带该标签的 PR）。
BLOCKING_LABEL = "block/merge"

# 会判红的 bucket（`gh pr checks --json` 的 bucket 口径；`cancel` 与 fail 同处置）。
RED_BUCKETS = ("fail", "cancel")

PR_TRIGGERS = ("pull_request", "pull_request_target")

PR_FIELDS = "state,isDraft,mergeable,mergeStateStatus,labels,autoMergeRequest"

CheckVerdict = namedtuple(
    "CheckVerdict",
    "code form_matched reason bare_red required_red counts labels state draft mergeable "
    "merge_state_status auto_merge_armed undecidable",
)
DiffVerdict = namedtuple(
    "DiffVerdict", "code reason bare pr_job_count undecidable")


class Undecidable(Exception):
    """读不到关键输入（gh 缺失 / API 失败 / 工作流读不到）⇒ 退 3，绝不退 0。"""


# ── 纯函数（夹具可直调，无网络无副作用）──────────────────────────────────────

def is_red(check):
    """这条 check 是不是红的（bucket 口径，缺 bucket 时回落 state）。"""
    bucket = str(check.get("bucket") or "").lower()
    if bucket:
        return bucket in RED_BUCKETS
    return str(check.get("state") or "").upper() in ("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT")


def check_counts(checks):
    counts = {"pass": 0, "fail": 0, "pending": 0, "total": 0}
    for check in checks or []:
        counts["total"] += 1
        bucket = str(check.get("bucket") or "").lower()
        state = str(check.get("state") or "").upper()
        if bucket in RED_BUCKETS or state in ("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT"):
            counts["fail"] += 1
        elif bucket == "pending" or state in ("PENDING", "QUEUED", "IN_PROGRESS"):
            counts["pending"] += 1
        else:
            counts["pass"] += 1
    return counts


def parse_checks(raw):
    """`gh pr checks --json` 的 stdout → 列表；**读不到返回 None**（≠ 空列表）。"""
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, list):
        return None
    return [c for c in data if isinstance(c, dict)]


def parse_required(payload):
    """分支保护 `required_status_checks` 载荷 → required 名字集合。

    兼容两种形态：`{"contexts": [...]}`（旧）与 `{"checks": [{"context": ...}]}`（新）。
    两者都读不到 ⇒ 抛 `Undecidable`（**空集合不是"没有 required"**，是读不到 ⇒ 退 3）。
    """
    if not isinstance(payload, dict):
        raise Undecidable("分支保护载荷不是 JSON 对象")
    contexts = payload.get("contexts")
    if isinstance(contexts, list):
        return {str(c) for c in contexts}
    checks = payload.get("checks")
    if isinstance(checks, list):
        names = {str(c.get("context")) for c in checks if isinstance(c, dict) and c.get("context")}
        if names:
            return names
    raise Undecidable("分支保护载荷里读不到 contexts / checks 字段")


def classify(checks, required):
    """把 checks 分成「required 红」与「裸判据红」（不在 required 里 ⇒ 判红**不拦**合并）。

    **不硬编码任何判据名**：报告型清单由 required 集合**反推** ⇒ 新增判据 / 某条被翻成 required
    都会自动跟上（测试 ⑥ 用一个仓库里不存在的新 job 名守住这条）。
    """
    required_red, bare_red = [], []
    for check in checks or []:
        if not is_red(check):
            continue
        (required_red if str(check.get("name")) in required else bare_red).append(check)
    return required_red, bare_red


def build_check_snapshot(pr, checks, required):
    """`gh pr view` 载荷 + checks 读数 + required 集合 → 判定用的**归一化快照**。"""
    labels = [n.get("name") for n in (pr.get("labels") or []) if isinstance(n, dict)]
    return {
        "state": pr.get("state"),
        "draft": bool(pr.get("isDraft")),
        "mergeable": pr.get("mergeable"),
        "merge_state_status": pr.get("mergeStateStatus"),
        "labels": labels,
        "auto_merge_armed": bool(pr.get("autoMergeRequest")),
        "checks": checks,
        "required": set(required or ()),
        "undecidable": pr.get("undecidable"),
    }


def decide_check(snapshot):
    """合并闸门判定本体（纯函数）：返回三态退出码 + 证据 + 可行动的裸判据清单。"""
    checks = snapshot.get("checks")
    required = snapshot.get("required") or set()
    labels = snapshot.get("labels") or []
    state = snapshot.get("state")
    mergeable, merge_state = snapshot.get("mergeable"), snapshot.get("merge_state_status")
    armed = bool(snapshot.get("auto_merge_armed"))
    required_red, bare_red = classify(checks, required)
    counts = check_counts(checks)

    def verdict(code, form, reason, undecidable=""):
        return CheckVerdict(code, form, reason, bare_red, required_red, counts, labels, state,
                            bool(snapshot.get("draft")), mergeable, merge_state, armed, undecidable)

    if snapshot.get("undecidable"):
        return verdict(EXIT_UNDECIDABLE, False, "无法判定", str(snapshot["undecidable"]))
    if checks is None:
        return verdict(EXIT_UNDECIDABLE, False, "无法判定",
                       "读不到 checks 读数（gh pr checks 未返回可解析 JSON）")

    # ① required 红 ⇒ GitHub 自己会拦，**不重复报警**（裸判据红只作信息列出）
    if required_red:
        names = ", ".join(str(c.get("name")) for c in required_red)
        extra = f"；另有裸判据红 {len(bare_red)} 条（不拦合并，建议一并处理）" if bare_red else ""
        return verdict(EXIT_OK, False, f"required 判据红（{names}）⇒ 已被 required 拦住合并{extra}")
    # ② 无裸判据红 ⇒ 不是本形态（**不得恒红**：恒红的判据 = 空判据）
    if not bare_red:
        return verdict(EXIT_OK, False,
                       f"无裸判据红（{counts['pass']} pass / {counts['fail']} fail / "
                       f"{counts['pending']} pending）")
    # ③ 已合入/关闭 ⇒ 形态是**既成事实**，仍判 1（事后可追 + 供报告留痕）
    if state in ("MERGED", "CLOSED"):
        return verdict(EXIT_HIT, True,
                       f"PR 已 {state}：裸判据红**已经**随合并进了 main（既成事实，只能事后跟随修复）")
    # ④ 眼下不会合的情形 —— 逐个说清，不混成一个 0
    if snapshot.get("draft"):
        return verdict(EXIT_OK, False, "PR 是 draft（draft 不参与 auto-merge）")
    if BLOCKING_LABEL in labels:
        return verdict(EXIT_OK, False, f"已带 {BLOCKING_LABEL}（人工闸已生效，无需重复动作）")
    if mergeable in (None, "UNKNOWN") or merge_state in (None, "UNKNOWN"):
        return verdict(EXIT_UNDECIDABLE, False, "无法判定",
                       f"mergeable={mergeable} / mergeStateStatus={merge_state} —— GitHub 仍在计算"
                       "（§7.3：等 30~60s 再试）")
    if mergeable != "MERGEABLE":
        return verdict(EXIT_OK, False, f"mergeable={mergeable}（冲突/未就绪，眼下合不了）")
    return verdict(EXIT_HIT, True,
                   "裸判据红且 PR 处于可合并态 ⇒ 判红**不拦**合并（auto-merge 只看 required）")


def job_names_on_pull_requests(workflows_dir):
    """`.github/workflows/*.y*ml` → {job 显示名: "文件名:job_id"}，只收 **PR 事件会跑**的 job。

    检查名 = job 的 `name:`（缺省回落 job id）。读不到目录 / 没有可解析的工作流 ⇒ `Undecidable`。
    """
    if yaml is None:
        raise Undecidable("环境缺 PyYAML（pip install pyyaml）—— 无法解析工作流")
    root = Path(workflows_dir)
    if not root.is_dir():
        raise Undecidable(f"工作流目录不存在：{root}")
    files = sorted(root.glob("*.yml")) + sorted(root.glob("*.yaml"))
    if not files:
        raise Undecidable(f"工作流目录里没有 .yml/.yaml：{root}")

    jobs, parsed = {}, 0
    for path in files:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise Undecidable(f"工作流解析失败 {path.name}：{exc}") from exc
        if not isinstance(data, dict):
            continue
        parsed += 1
        triggers = data.get("on") or data.get(True) or {}
        if isinstance(triggers, str):
            triggers = {triggers}
        elif isinstance(triggers, list):
            set(triggers)
            triggers = set(triggers)
        elif isinstance(triggers, dict):
            triggers = set(triggers)
        else:
            triggers = set()
        if not (triggers & set(PR_TRIGGERS)):
            continue
        for job_id, job in (data.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            name = job.get("name") or job_id
            jobs[str(name)] = f"{path.name}:{job_id}"
    if not parsed:
        raise Undecidable(f"工作流目录里没有可解析的 YAML：{root}")
    return jobs


def bare_jobs(jobs, required):
    """「实际存在且会判红的 job」− required = **裸判据**（判红不拦合并）——按名字排序。"""
    return sorted(set(jobs) - set(required))


def decide_required_diff(jobs, required):
    """元判据判定本体（纯函数）：差集非空 ⇒ 1。"""
    bare = bare_jobs(jobs, required)
    if bare:
        return DiffVerdict(EXIT_HIT, f"存在 {len(bare)} 条**裸判据**（会判红但不拦合并）",
                           bare, len(jobs), "")
    return DiffVerdict(EXIT_OK, "差集为空：会判红的 job 都在 required 集合里", [], len(jobs), "")


# ── gh 取数（唯一的 IO 边界）─────────────────────────────────────────────────

def gh_run(args, gh_bin):
    try:
        return subprocess.run([gh_bin, *args], capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise Undecidable(f"找不到 gh 可执行文件 {gh_bin!r}（{exc}）") from exc
    except OSError as exc:
        raise Undecidable(f"无法执行 gh（{exc}）") from exc


def gh_repo(gh_bin):
    proc = gh_run(["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"], gh_bin)
    name = (proc.stdout or "").strip()
    if proc.returncode != 0 or not name:
        raise Undecidable(f"读不到仓库名（gh repo view 退出 {proc.returncode}）："
                          f"{(proc.stderr or '').strip()[:200]}")
    return name


def fetch_required(repo, branch, gh_bin):
    proc = gh_run(["api", f"repos/{repo}/branches/{branch}/protection/required_status_checks"], gh_bin)
    if proc.returncode != 0:
        raise Undecidable(f"读不到分支保护 required 集合（gh api 退出 {proc.returncode}）："
                          f"{(proc.stderr or proc.stdout or '').strip()[:200]}")
    try:
        payload = json.loads(proc.stdout or "")
    except ValueError:
        raise Undecidable(f"分支保护未返回 JSON（退出 {proc.returncode}）："
                          f"{(proc.stderr or proc.stdout or '').strip()[:200]}")
    return parse_required(payload)


def fetch_pr(pr, repo, gh_bin):
    proc = gh_run(["pr", "view", str(pr), "--json", PR_FIELDS, "--repo", repo], gh_bin)
    try:
        payload = json.loads(proc.stdout or "")
    except ValueError:
        raise Undecidable(f"gh pr view 未返回 JSON（退出 {proc.returncode}）："
                          f"{(proc.stderr or proc.stdout or '').strip()[:200]}")
    if not isinstance(payload, dict) or not payload.get("state"):
        raise Undecidable(f"gh pr view 未返回 PR 载荷（退出 {proc.returncode}）："
                          f"{(proc.stderr or '').strip()[:200]}")
    return payload


def fetch_checks(pr, repo, gh_bin):
    proc = gh_run(["pr", "checks", str(pr), "--json", "name,state,bucket,link", "--repo", repo], gh_bin)
    checks = parse_checks(proc.stdout)
    if checks is None:
        raise Undecidable(f"gh pr checks 未返回可解析 JSON（退出 {proc.returncode}）："
                          f"{(proc.stderr or proc.stdout or '').strip()[:200]}")
    return checks


def read_check_snapshot(pr, repo=None, branch="main", gh_bin="gh"):
    """取数 → 快照；任何读不到的关键输入都抛 `Undecidable`（由 main 转成 3）。"""
    repo = repo or gh_repo(gh_bin)
    required = fetch_required(repo, branch, gh_bin)
    node = fetch_pr(pr, repo, gh_bin)
    return build_check_snapshot(node, fetch_checks(pr, repo, gh_bin), required), repo


# ── 写操作（只有 --apply-label / --disarm-auto 才走到这里）────────────────────

def add_label(pr, repo, gh_bin):
    """打人工闸标签。`repo` 为 None 时**不加** `--repo` —— 这样 dry-run 打印的命令与真正执行的一致。"""
    args = ["pr", "edit", str(pr), "--add-label", BLOCKING_LABEL]
    if repo:
        args += ["--repo", repo]
    proc = gh_run(args, gh_bin)
    return proc.returncode == 0, (proc.stderr or proc.stdout or "").strip()[:200]


def disarm_auto(pr, repo, gh_bin):
    """`gh pr merge --disable-auto` —— 标签**停不住**已 arm 的 auto-merge，只有它能。"""
    args = ["pr", "merge", str(pr), "--disable-auto"]
    if repo:
        args += ["--repo", repo]
    proc = gh_run(args, gh_bin)
    return proc.returncode == 0, (proc.stderr or proc.stdout or "").strip()[:200]


# ── 输出（可行动：证据 + 一条能直接粘走的命令）───────────────────────────────

def render_check(verdict, pr, repo, apply_label=False, no_disarm_auto=False):
    counts = verdict.counts
    labels = ", ".join(verdict.labels) if verdict.labels else "(无)"
    tag = {EXIT_OK: "✅ 未命中该形态", EXIT_HIT: "🎯 命中该形态",
           EXIT_UNDECIDABLE: "⚠️ 无法判定"}[verdict.code]
    lines = [f"=== 关联 #4248 合并闸门判定 · PR #{pr} ===",
             f"判定：{tag} —— {verdict.reason}"]
    if verdict.undecidable:
        lines.append(f"原因：{verdict.undecidable}")
    lines.append(
        f"证据：checks {counts['pass']} pass / {counts['fail']} fail / {counts['pending']} pending"
        f" · state={verdict.state} · mergeable={verdict.mergeable}"
        f" · mergeStateStatus={verdict.merge_state_status} · labels={labels}"
        f" · auto-merge={'已 arm' if verdict.auto_merge_armed else '未 arm'}")
    if verdict.code == EXIT_UNDECIDABLE:
        return "\n".join(lines)

    if verdict.bare_red:
        lines.append(f"裸判据红 {len(verdict.bare_red)} 条（不在 required ⇒ 判红**不拦**合并）：")
        for c in verdict.bare_red:
            link = f"  {c['link']}" if c.get("link") else ""
            lines.append(f"  · {c.get('name')}  [{c.get('state') or c.get('bucket')}]{link}")
    if verdict.required_red:
        lines.append(f"required 判据红 {len(verdict.required_red)} 条（GitHub 会拦，不重复报警）：")
        for c in verdict.required_red:
            lines.append(f"  · {c.get('name')}  [{c.get('state') or c.get('bucket')}]")

    if verdict.code == EXIT_HIT:
        if verdict.auto_merge_armed:
            lines.append(
                "⚠️ 该 PR 的 auto-merge **已 arm**：实测标签**停不住**已 arm 的 auto-merge"
                "（关联 #4271 标签 07:03:19Z 晚于 enabledAt 07:03:18Z、合并 07:07:22Z；"
                "关联 #4266 标签 06:57:32Z、合并 07:00:30Z）⇒ 落闸必须 `--disable-auto`"
                "（`--apply-label` **默认**会做；关联 #4334）。")
        if verdict.state != "OPEN":
            lines.append(f"PR 已 {verdict.state} ⇒ **无法再落闸**（闸门只对未合并的 PR 有效）。"
                         "既成事实的处置：① 跟随修复带上 main 的那条红；② 用 "
                         "`python3 scripts/merge_gate.py --required-diff` 逐条清裸判据。")
            return "\n".join(lines)
        has_label = BLOCKING_LABEL in (verdict.labels or [])
        armed = bool(verdict.auto_merge_armed)
        lines.append("可行动（dry-run：只读，未做任何写操作）："
                     if not apply_label else "落闸动作（实际执行结果见下方 ✅/❌）：")
        lines.append(f"  python3 scripts/merge_gate.py --check {pr} --apply-label"
                     f"   # 一步落闸：打 {BLOCKING_LABEL} + 解除已 arm 的 auto-merge")
        lines.append(f"  gh pr edit {pr} --add-label {BLOCKING_LABEL}"
                     f"      # 手动等价（{'已带该标签' if has_label else '未打'}）")
        lines.append(f"  gh pr merge {pr} --disable-auto"
                     f"        # 手动等价；`--no-disarm-auto` 可跳过（"
                     f"{'auto-merge 未 arm ⇒ 只打标签即可' if not armed else ('已跳过' if no_disarm_auto else '默认执行')}）")
        if no_disarm_auto and armed:
            lines.append("⚠️ `--no-disarm-auto`：已 arm 的 auto-merge **不会被本标签拦住**"
                         "（实测关联 #4271 / #4266：标签在了、PR 还是合了）"
                         "⇒ 只有 `gh pr merge <PR> --disable-auto` 能停住它。")
        lines.append(f"  python3 scripts/merge_gate.py --required-diff   "
                     f"# 元判据：看还有哪些裸判据（repo={repo}）")
    return "\n".join(lines)


def render_required_diff(verdict, jobs, required, branch, repo):
    tag = {EXIT_OK: "✅ 差集为空", EXIT_HIT: "🎯 存在裸判据",
           EXIT_UNDECIDABLE: "⚠️ 无法判定"}[verdict.code]
    lines = [f"=== 关联 #4248 元判据 · required 集合 vs 会判红的 job 集合（{repo}@{branch}）===",
             f"判定：{tag} —— {verdict.reason}"]
    if verdict.undecidable:
        lines.append(f"原因：{verdict.undecidable}")
        return "\n".join(lines)
    lines.append(f"证据：分支保护 required {len(required)} 条 · PR 事件会跑的 job {verdict.pr_job_count} 条"
                 f" · 差集 {len(verdict.bare)} 条")
    if verdict.bare:
        lines.append("裸判据（**会判红但不拦合并** —— 别再以为它们在拦）：")
        for name in verdict.bare:
            lines.append(f"  · {name}   ({jobs[name]})")
        lines.append("处置：① 逐条决定「翻成 required（会阻塞所有人，先清债）」还是「保持报告型 + 判红打 "
                     f"{BLOCKING_LABEL}」；② 本脚本 `--check <PR> --apply-label --disarm-auto` 可对单个 PR 落闸。")
    else:
        lines.append("0 条裸判据：所有会判红的 job 都在 required 集合里。")
    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="merge_gate.py",
        description="关联 #4248：裸判据差集元判据（--required-diff）+ 报告型判据判红时的合并闸门"
                    "（--check，默认 dry-run）")
    parser.add_argument("--required-diff", action="store_true",
                        help="元判据：打印 required 集合与「会判红的 job」的差集（只读）")
    parser.add_argument("--check", type=int, metavar="PR", default=None,
                        help="合并闸门：判定该 PR 是否有「红了也照合」的裸判据")
    parser.add_argument("--repo", default=None, help="OWNER/NAME（默认取 gh repo view）")
    parser.add_argument("--branch", default="main", help="读哪条分支的分支保护（默认 main）")
    parser.add_argument("--workflows-dir", default=str(Path(__file__).resolve().parents[1]
                                                      / ".github" / "workflows"),
                        help="工作流目录（默认仓库 .github/workflows）")
    parser.add_argument("--apply-label", action="store_true",
                        help=f"落闸：打 {BLOCKING_LABEL} + **默认同时** `gh pr merge --disable-auto`"
                             "（默认只读；关联 #4334）")
    parser.add_argument("--no-disarm-auto", action="store_true",
                        help="逃生口：只打标签、跳过 disarm（输出会明写它拦不住已 arm 的 auto-merge）")
    parser.add_argument("--disarm-auto", action="store_true",
                        help="（已是 `--apply-label` 的默认行为；保留仅为兼容既有命令行）")
    args = parser.parse_args(argv)

    gh_bin = os.environ.get("MG_GH_BIN", "gh")
    if args.required_diff == (args.check is not None):
        print("用法：必须**恰好**给一个子命令 —— --required-diff 或 --check <PR号>\n"
              "（两者都给 / 都不给 ⇒ 无法判定，退 3）")
        return EXIT_UNDECIDABLE

    if args.required_diff:
        try:
            repo = args.repo or gh_repo(gh_bin)
            required = fetch_required(repo, args.branch, gh_bin)
            jobs = job_names_on_pull_requests(args.workflows_dir)
        except Undecidable as exc:
            verdict = DiffVerdict(EXIT_UNDECIDABLE, "无法判定", [], 0, str(exc))
            print(render_required_diff(verdict, {}, set(), args.branch, args.repo or "(未知)"))
            return verdict.code
        verdict = decide_required_diff(jobs, required)
        print(render_required_diff(verdict, jobs, required, args.branch, repo))
        return verdict.code

    try:
        snapshot, repo = read_check_snapshot(args.check, args.repo, args.branch, gh_bin)
    except Undecidable as exc:
        snapshot = {"undecidable": str(exc), "checks": None}
        repo = args.repo or "(未知)"
    verdict = decide_check(snapshot)
    print(render_check(verdict, args.check, repo, apply_label=args.apply_label,
                       no_disarm_auto=args.no_disarm_auto))

    # dry-run 语义：**不带 `--apply-label` 一律零写**（既不标签也不 disarm）。
    if verdict.code != EXIT_HIT or not args.apply_label:
        return verdict.code
    if verdict.state != "OPEN":
        print(f"⚠️ PR 状态 = {verdict.state} ⇒ **不发任何写操作**（闸门改不了既成事实）")
        return verdict.code

    failed = []
    if BLOCKING_LABEL not in (verdict.labels or []):
        ok, msg = add_label(args.check, args.repo, gh_bin)
        print(f"  {'✅' if ok else '❌'} 打 {BLOCKING_LABEL}：{msg}")
        failed += [] if ok else ["label"]
    # 「打 block/merge」= 「拦住合并」：已 arm 时必须 disarm，否则标签**拦不住**（关联 #4334）。
    # 未 arm 时无需 disarm —— 标签会让 automerge.yml 的 `if:` 在后续事件上永不 arm。
    if not verdict.auto_merge_armed:
        print("  ℹ️ auto-merge 未 arm ⇒ 只打标签即可（automerge.yml 的 if: 会让它永不 arm）")
    elif args.no_disarm_auto:
        print("  ⚠️ --no-disarm-auto：跳过 disarm —— 已 arm 的 auto-merge **不会被本标签拦住**")
    else:
        ok, msg = disarm_auto(args.check, args.repo, gh_bin)
        print(f"  {'✅' if ok else '❌'} --disable-auto：{msg}")
        failed += [] if ok else ["disable-auto"]
    if failed:
        print(f"❌ 写操作失败：{', '.join(failed)}")
    return verdict.code


if __name__ == "__main__":
    sys.exit(main())
