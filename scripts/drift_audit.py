#!/usr/bin/env python3
"""
统一漂移审计入口（单一真相源契约 · 实装包）。

**为什么存在**：2026-09 复盘里一整类返工的根因只有两条 ——
  ① **读的是陈旧快照**（版本可引/时效可验缺失）；
  ② **按可变键定位被测对象**（身份不可变缺失）。
两者此前由 **A~H 七处散装脚本/人工习惯**各自把关，口径不一 ⇒ 同一个漂移
在这处被抓住、在那处被放行。本脚本把七项检查收成**一条命令、一个报告**：
任何"哪里陈旧了/哪里会漂"的结论只以本报告为准。

契约（判定方式 + 违反处置）见 `docs/wiki/truth-source-contract.md`：
  I1 版本可引 / I2 身份不可变 / I3 世界自建 / I4 时效可验。

用法（仓根）：
  python3 scripts/drift_audit.py                       # 只报告（永远 exit 0，供人读）
  python3 scripts/drift_audit.py --check               # 门禁：**新增**漂移 ⇒ exit 1；存量放行
  python3 scripts/drift_audit.py --check --json out.json
  python3 scripts/drift_audit.py --regen-baseline --reason "PR #xxxx：销账 xxx"
  python3 scripts/drift_audit.py --list-checks         # 打印判据集合（护栏清单，机器可读）
  python3 scripts/drift_audit.py --repo <path> --base <rev> --offline   # 供 L0 夹具使用

**基线只许缩短**（防僵化，#4045 起=**全量对账** + burn-down 预算）：
  · 新增漂移（now > base，或出现新 key）⇒ `--check` 非零退出（fail-closed）；
  · 存量漂移（now == base）⇒ 打印放行；
  · 销账（base > now > 0）⇒ 打印并提示可 `--regen-baseline`；
  · 条目已归零但仍在清单里（base > 0 == now）⇒ **阻塞**（豁免一条不存在的漂移 = 未来的假真值）。
    ⚠️ **不限本次 diff 命中**：只要清单里还躺着一条已不再漂移的条目就红 —— 否则「没人再碰那个文件」
    就是永久豁免（旧口径的自述注释「沿用 `case_trust_gate` 的 `stale_baseline_entries` 口径」
    在 #4031 之后已成假真值，见 #4045）；
  · `--base` 清单里记着、现在**仍漂移**却被删掉 ⇒ **阻塞**（删条目 = 偷偷缩短）；
  · burn-down 预算：`scope=surface_touching_prs` 的 PR 每 PR 至少净缩 `per_pr_min` 条。
  **判据本体不在本文件**：调 `.github/case_trust_gate.py` 的 `reconcile_baseline` /
  `burn_down_verdict`（import 复用，避免第二份口径；本脚本只做 `{key: 计数}` ⇄ `{case_id: [码]}`
  的形态搬运）。
  `--regen-baseline` 必须带 `--reason`，理由写进基线 JSON（PR 里要说明为什么）。

**为什么不做「语义级引用命中」**（诚实登记，勿当已实装）：
  曾尝试用「引用同行反引号锚点串必须出现在目标行」判 `path:NNN` 是否过期，
  实测 26 条带锚引用里 **20 条误红**（多引用同行、锚点是另一条引用、锚点是整句散文）。
  按 `migao-acceptance`「断言形态」——**误红即坏断言**——故不做语义命中，只做
  可零误红判定的四族（悬空/越界/无 sha 限定/裸行号）。缺口见 `UNIMPLEMENTED`。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA = "migao.drift-audit/1"
BASELINE_SCHEMA = "migao.drift-audit-baseline/1"
POLICY_VERSION = 1
DEFAULT_BASELINE = "scripts/drift_audit_baseline.json"
REGEN_COMMAND = "python3 scripts/drift_audit.py --regen-baseline --reason '<理由>'"

# ── 受管引用面（引用新鲜度的判定范围）──────────────────────────────────────────
# 只覆盖「契约性引用」所在的目录；点时效快照类目录（历史审计报告 / 一次性验收报告 /
# 设计调研）**有意排除**：那里的行号是当时的读数，本来就该陈旧（登记为豁免面）。
REF_SURFACE = (
    "docs/wiki/",
    "docs/testing/",
    "tests/unit_ci_workflows/",
    ".github/workflows/",
    ".agent-presets/",
    "scripts/",
)
REF_SURFACE_EXEMPT = (
    "docs/audit-",            # 月度审计快照
    "acceptance/",            # 一次性验收报告
    "docs/design/",           # 设计调研（结论性文档，非契约）
    "docs/testing/acceptance/",
)
# 派生视图：内容由别的单一源生成，本面无写权限 ⇒ 只报告不阻塞（违规归因到源面）。
DERIVED_VIEWS = (
    "docs/testing/mibao-verification-cases.md",
    "tests/agent_eval/eval_cases.py",
)

SKILLS_DIR = ".agent-presets/migao/skills"
DEV_FLOW_SKILL = ".agent-presets/migao/skills/migao-dev-flow/SKILL.md"
DEV_FLOW_COPY = "docs/wiki/DEV-FLOW.md"
GEN_EVAL = "tests/agent_eval/eval_cases.py"
GEN_MD = "docs/testing/mibao-verification-cases.md"
CASES_DIR = ".github/cases"

LIVE_ANCHOR_DEFAULT = "~/.dsh/.agent-presets/migao"
LIVE_ANCHOR_ENV = "MIGAO_PRESET_LIVE"


# ═══════════════════════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class Finding:
    """一条漂移。key 必须**稳定**（不含行号）——否则改一行就换 key，"只许缩短"失效。

    `env=True` = **环境相关**（依赖本机状态：活锚是否安装 / 活锚落后多少提交）。
    此类**永不进基线**：它是"你本机读的快照比别人旧"的现场证据，一旦写进基线就等于
    永久豁免（且落后数还在变，基线里那个 1 会变成假真值）。CI runner 上活锚不存在 ⇒
    该项记『未知』，所以它不会在 CI 上假装通过。
    """

    key: str
    detail: str
    blocking: bool = True
    env: bool = False
    always: bool = False  # 永不进基线、也不允许"存量放行"（如版本单调性回退）


@dataclass
class CheckResult:
    check_id: str
    status: str = "ok"  # ok | known-drift | new-drift | unknown | error
    evaluated: int = 0
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class Check:
    id: str
    invariant: str
    title: str
    judgment: str  # 判定方式（机器可判的谓词）
    remedy: str  # 违反后的处置（必须给出"怎么改"）
    fn: Callable[["Audit"], CheckResult]
    network: bool = False
    # 判定为空 = 护栏失效（退化守卫 G1 会红）
    min_evaluated: int = 1


# ═══════════════════════════════════════════════════════════════════════════
# 工具
# ═══════════════════════════════════════════════════════════════════════════
def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def norm_text(text: str) -> str:
    """章节比对用的归一化：去掉空白与 markdown 强调符（两者差异不构成口径差异）。"""
    return re.sub(r"[\s*`_>]", "", text)


class Audit:
    def __init__(self, repo: Path, base: str = "origin/main", offline: bool = False,
                 now: datetime | None = None, live_anchor: Path | None = None,
                 gh_fixture: Path | None = None, verbose: bool = False):
        self.repo = repo.resolve()
        self.base = base
        self.offline = offline
        self.now = now or datetime.now(timezone.utc)
        self.verbose = verbose
        anchor = live_anchor or Path(
            os.path.expanduser(os.environ.get(LIVE_ANCHOR_ENV) or LIVE_ANCHOR_DEFAULT)
        )
        self.live_anchor = anchor
        self.gh_fixture = gh_fixture
        self._file_cache: dict[str, str] = {}
        self._tracked: list[str] | None = None

    # ── git / 文件 ────────────────────────────────────────────────────────
    def git(self, *args: str, check: bool = False) -> str:
        try:
            p = subprocess.run(["git", "-C", str(self.repo), *args],
                               capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover
            if check:
                raise
            return ""
        if check and p.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()}")
        return p.stdout if p.returncode == 0 else ""

    def git_ok(self, *args: str) -> bool:
        """`git cat-file -e` 这类**靠退出码**判定的命令 —— `git()` 返回 stdout，
        成功时是空串，与失败无法区分（这个坑会让"存在性"检查永远为假 = 假红/假绿）。"""
        try:
            return subprocess.run(["git", "-C", str(self.repo), *args],
                                  capture_output=True, text=True, timeout=60
                                  ).returncode == 0
        except (OSError, subprocess.TimeoutExpired):  # pragma: no cover
            return False

    def tracked(self) -> list[str]:
        if self._tracked is None:
            out = self.git("ls-files")
            self._tracked = [f for f in out.split("\n") if f]
        return self._tracked

    def read(self, rel: str, rev: str | None = None) -> str | None:
        """读工作树（rev=None）或某个 revision 的内容。"""
        if rev:
            txt = self.git("show", f"{rev}:{rel}")
            return txt if txt else None
        key = rel
        if key not in self._file_cache:
            p = self.repo / rel
            self._file_cache[key] = (
                p.read_text(encoding="utf-8", errors="ignore") if p.is_file() else ""
            )
        return self._file_cache[key] or None

    def exists_at(self, rel: str, rev: str | None = None) -> bool:
        if rev:
            return self.git_ok("cat-file", "-e", f"{rev}:{rel}")
        return (self.repo / rel).is_file()

    def line_count(self, rel: str, rev: str | None = None) -> int | None:
        txt = self.read(rel, rev)
        if txt is None:
            return None
        return len(txt.split("\n"))

    # ── 解引用：把 `foo.py` 这类简写补全成 tracked 路径 ─────────────────────
    def resolve_ref_path(self, ref: str) -> list[str]:
        files = self.tracked()
        if ref in files:
            return [ref]
        cand = [f for f in files if f.endswith("/" + ref)]
        if not cand:
            base = os.path.basename(ref)
            cand = [f for f in files if os.path.basename(f) == base]
        return sorted(set(cand))


# ═══════════════════════════════════════════════════════════════════════════
# C1 技能活锚新鲜度（I1 / I4）
# ═══════════════════════════════════════════════════════════════════════════
FM_VERSION = re.compile(r"^version:\s*([0-9][0-9A-Za-z.\-]*)\s*$", re.M)


def _skill_versions(skills_dir: Path) -> dict[str, str]:
    """`skills_dir` = 直接含 `<技能名>/SKILL.md` 的目录（仓库与活锚的布局不同，勿拼接）。"""
    out: dict[str, str] = {}
    d = skills_dir
    if not d.is_dir():
        return out
    for sk in sorted(d.glob("*/SKILL.md")):
        txt = sk.read_text(encoding="utf-8", errors="ignore")
        m = FM_VERSION.search(txt)
        out[sk.parent.name] = m.group(1) if m else "<缺失>"
    return out


def _ver_tuple(v: str) -> tuple:
    """`1.27.0` / `1.27` → 可比较元组；非数字段降级为 0（只为判方向，不做语义版本判定）。"""
    out = []
    for part in re.split(r"[.\-+]", v or ""):
        out.append(int(part) if part.isdigit() else 0)
    return tuple(out)


def check_skill_anchor(a: Audit) -> CheckResult:
    r = CheckResult("skill-anchor")
    repo_skills = _skill_versions(a.repo / SKILLS_DIR)
    r.evaluated = len(repo_skills)
    if not repo_skills:
        r.status = "error"
        r.error = f"{SKILLS_DIR} 下没解析到任何 SKILL.md（判据面为空 = 护栏失效）"
        return r
    for name, ver in repo_skills.items():
        r.notes.append(f"仓库 {name} = {ver}")

    anchor = a.live_anchor
    if not anchor.exists():
        # 显式"未安装"：不是漂移（CI runner / 未安装 preset 的机器），但必须可见。
        r.status = "unknown"
        r.notes.append(f"活锚未安装：{anchor} 不存在 ⇒ 无法判定活锚新鲜度（**不等于通过**）")
        return r

    live_skills = _skill_versions(anchor / "skills")
    for name, ver in repo_skills.items():
        lv = live_skills.get(name)
        if lv is None:
            r.findings.append(Finding(
                f"{name}|missing-in-live", f"活锚缺该技能：{anchor}/skills/{name} 不存在", env=True))
        elif lv != ver:
            # 方向必须判准：写反了就是「注释漂移 = 假绿来源」同族（读者按错误方向去修）
            if _ver_tuple(lv) > _ver_tuple(ver):
                detail = (f"活锚 {name}={lv} **比本工作副本的 {ver} 新** —— 本分支/工作副本"
                          f"落后于权威源（先 `git fetch origin main && git rebase origin/main`）")
            else:
                detail = (f"活锚 {name}={lv} **落后于仓库的 {ver}** —— 改技能后没重装活锚，"
                          f"加载器读到的是旧口径")
            r.findings.append(Finding(f"{name}|version", detail, env=True))
        else:
            r.notes.append(f"活锚 {name} = {lv}（与仓库一致）")

    # 内容哈希：版本号相同也可能内容漂移（version 不参与加载，是人工字段）
    for name in repo_skills:
        src = a.repo / SKILLS_DIR / name / "SKILL.md"
        dst = anchor / "skills" / name / "SKILL.md"
        if src.is_file() and dst.is_file():
            if sha256_text(src.read_text(encoding="utf-8", errors="ignore")) != \
               sha256_text(dst.read_text(encoding="utf-8", errors="ignore")):
                r.findings.append(Finding(
                    f"{name}|content", f"活锚 {name} 与仓库逐字节不同（版本号相同也不算新鲜）",
                    env=True))

    # 活锚若在 git 仓库里：给出落后提交数（"落后 N 个提交"是复盘里的真实形态）
    # ⚠️ 活锚通常是**软链**（`~/.dsh/.agent-presets/migao` → 某检出目录）；
    # 必须先 resolve 再向上找 `.git`，否则永远找不到、落后数永远报不出来（= 假绿）。
    live_root: Path | None = Path(os.path.realpath(anchor))
    for _ in range(6):
        if (live_root / ".git").exists():
            break
        if live_root.parent == live_root:
            live_root = None  # type: ignore[assignment]
            break
        live_root = live_root.parent
    if live_root is not None:
        # 脏 = 活锚内容不对应任何**已提交版本** ⇒ 比"落后"更糟（无法用 sha 引证）。
        dirty = subprocess.run(
            ["git", "-C", str(live_root), "status", "--porcelain", "--", ".agent-presets"],
            capture_output=True, text=True).stdout.strip()
        if dirty:
            n_dirty = len([x for x in dirty.split("\n") if x.strip()])
            r.findings.append(Finding(
                "live-anchor|uncommitted",
                f"活锚检出有 {n_dirty} 个未提交改动落在 `.agent-presets/` 下 —— 活锚内容"
                f"不对应任何已提交版本，加载器读到的规则**无法用 sha 引证**"
                f"（换链拓扑要求活锚指向**专职只读镜像**；#4026 已把 AGENTS.md/本目录 README 的"
                f"旧教法「指向主工作区」改掉，并给了 `scripts/preset-anchor-refresh.sh` 做刷新）",
                env=True))
        live_sha = subprocess.run(["git", "-C", str(live_root), "rev-parse", "HEAD"],
                                  capture_output=True, text=True).stdout.strip()
        if live_sha:
            base_sha = a.git("rev-parse", a.base).strip()
            if base_sha and a.git_ok("cat-file", "-e", f"{live_sha}^{{commit}}"):
                n = a.git("rev-list", "--count", f"{live_sha}..{base_sha}").strip()
                # ⚠️ 判据是**内容级**的，不是提交数：落后 N 个提交但 `落后区间` 没碰
                # `.agent-presets/migao/**` ⇒ 加载到的规则仍是最新的（否则每次主干合并
                # 都会把活锚判红 = 噪音红，正是本契约自己要躲的）。实测形态：落后 1 个提交
                # 且 `.agent-presets/` 无变化。
                touched = [x for x in a.git(
                    "diff", "--name-only", f"{live_sha}..{base_sha}",
                    "--", ".agent-presets/migao").split("\n") if x.strip()]
                if n and int(n) > 0 and touched:
                    r.notes.append(f"活锚仓库 {live_root} HEAD={live_sha[:8]} 落后 "
                                   f"{a.base}={base_sha[:8]} **{n} 个提交**")
                    # 口径分工（#4026）：本审计停在**内容级**（落后区间没碰 `.agent-presets/` ⇒
                    # 只记 note，避免"每次主干合并都判红"的噪音）；**开工/提交路径**另有 sha 级判据
                    # `./scripts/preset-anchor-check.sh`（落后即红，"先同步再动手"）+ 刷新
                    # `./scripts/preset-anchor-refresh.sh`。两处判据分工写在 guard 的 `anchor` 段注释里。
                    r.notes.append("（落后即先同步再动手：`./scripts/preset-anchor-check.sh` → "
                                   "`./scripts/preset-anchor-refresh.sh`；#4026）")
                    r.findings.append(Finding(
                        "live-anchor|commits-behind",
                        f"活锚检出落后 {a.base} **{n} 个提交**，且落后区间**动过** "
                        f"`.agent-presets/migao/**`（{len(touched)} 个文件，如 {touched[:3]}）"
                        f"⇒ 加载器读到的是旧快照（本会话实测过落后 25 个提交的形态）",
                        env=True))
                elif n and int(n) > 0:
                    r.notes.append(f"活锚仓库 {live_root} HEAD={live_sha[:8]} 落后 "
                                   f"{a.base}={base_sha[:8]} {n} 个提交，但落后区间**未改** "
                                   f"`.agent-presets/migao/**` ⇒ 加载到的规则仍是最新"
                                   f"（内容级判定，不以提交数判红）")
                else:
                    r.notes.append(f"活锚仓库 {live_root} HEAD={live_sha[:8]} 无提交落后")
            else:
                r.notes.append("活锚不在本仓库历史里 ⇒ 提交落后数无法判定（不谎报为 0）")
        else:
            r.notes.append(f"活锚仓库 {live_root} 无 HEAD ⇒ 提交落后数无法判定")
    else:
        r.notes.append("活锚不在任何 git 检出里 ⇒ 只能比较 version/sha256，提交落后数无法判定")
    return r


# ═══════════════════════════════════════════════════════════════════════════
# C1b 预设版本单调性（I1）：不得把技能版本**降级**
# ═══════════════════════════════════════════════════════════════════════════
def check_preset_monotonic(a: Audit) -> CheckResult:
    """`.agent-presets/**` 的 `version:` 相对 base **不得下降**；同版本不同内容 = 分叉。

    背景（2026-09-15 实证）：worktree 的 `.agent-presets/` 是**创建时刻的快照**；
    rebase 之后它可能仍是 v1.27.0 而 main 已是 1.28.0 —— 一条 `git add -A` 就把
    **旧预设提交上去 = 静默回退研发模式**，而测试不看文档 ⇒ **CI 不会红**。
    """
    r = CheckResult("preset-monotonic")
    base = a.base
    skills_dir = a.repo / SKILLS_DIR
    names = sorted(p.parent.name for p in skills_dir.glob("*/SKILL.md"))
    r.evaluated = len(names)
    if not names:
        r.status = "error"
        r.error = f"{SKILLS_DIR} 下 0 个 SKILL.md（判据面为空 = 护栏失效）"
        return r
    for name in names:
        rel = f"{SKILLS_DIR}/{name}/SKILL.md"
        cur_txt = a.read(rel)
        base_txt = a.read(rel, base)
        if cur_txt is None or base_txt is None:
            r.findings.append(Finding(f"{name}|missing",
                                      f"{rel} 在 {base} 或工作树上不存在", always=True))
            continue
        m_cur, m_base = FM_VERSION.search(cur_txt), FM_VERSION.search(base_txt)
        cur = m_cur.group(1) if m_cur else "<缺失>"
        old = m_base.group(1) if m_base else "<缺失>"
        r.notes.append(f"{name}: {base} = {old} → 工作树 = {cur}")
        if _ver_tuple(cur) < _ver_tuple(old):
            r.findings.append(Finding(
                f"{name}|version-decrease",
                f"**技能版本回退**：{name} 从 {base} 的 {old} **降到** {cur}"
                f"（worktree 的 `.agent-presets/` 是创建时的快照；`git add -A` 会把旧预设"
                f"提交上去 = 静默回退研发模式，而测试不看文档 ⇒ CI 不会红）",
                always=True))
        elif cur == old and norm_text(cur_txt) != norm_text(base_txt):
            r.findings.append(Finding(
                f"{name}|forked",
                f"{name} 版本号与 {base} 相同（{cur}）但**内容已分叉** —— 同版本不同内容"
                f"是分叉不是升级，无法用版本号引证", always=True))
    return r


# ═══════════════════════════════════════════════════════════════════════════
# C2 同步副本 diff（I1）
# ═══════════════════════════════════════════════════════════════════════════
COPY_VERSION = re.compile(r"当前版本：v?([0-9]+(?:\.[0-9]+)*)")
SEC_HEAD = re.compile(r"^##\s+([0-9]+(?:\.[0-9]+)*)\.?\s+(.*)$")
DECLARED_SOURCE = re.compile(r"权威源：`([^`]+)`")


def _sections(text: str) -> dict[str, str]:
    out: dict[str, list[str]] = {}
    cur: str | None = None
    for line in text.split("\n"):
        m = SEC_HEAD.match(line)
        if m:
            cur = m.group(1)
            out.setdefault(cur, [])
            continue
        if cur is not None:
            out[cur].append(line)
    return {k: "\n".join(v) for k, v in out.items()}


def check_sync_copy(a: Audit) -> CheckResult:
    r = CheckResult("sync-copy")
    src_txt = a.read(DEV_FLOW_SKILL)
    cp_txt = a.read(DEV_FLOW_COPY)
    if src_txt is None or cp_txt is None:
        r.status = "error"
        r.error = f"缺文件：{DEV_FLOW_SKILL} 或 {DEV_FLOW_COPY}"
        return r
    r.evaluated = 3

    m = FM_VERSION.search(src_txt)
    src_ver = m.group(1) if m else "<缺失>"
    mv = COPY_VERSION.search(cp_txt)
    cp_ver = mv.group(1) if mv else "<缺失>"
    r.notes.append(f"权威源 {DEV_FLOW_SKILL} = {src_ver}；副本 {DEV_FLOW_COPY} 声明 = v{cp_ver}")
    if cp_ver != src_ver:
        # 版本号是"目录名/篇章"级的比较；1.27.0 vs 1.27 视为一致
        if cp_ver.split(".")[:2] != src_ver.split(".")[:2]:
            r.findings.append(Finding(
                "version", f"同步副本声明 v{cp_ver}，权威源是 {src_ver}"
                f"（读者拿到的是旧口径 —— 副本自称『两份不一致时按技能执行』，但没人会去比）"))

    ds = DECLARED_SOURCE.search(cp_txt)
    if not ds:
        r.findings.append(Finding("declared-source", "副本未声明权威源路径（缺『权威源：`path`』）"))
    elif not (a.repo / ds.group(1)).is_file():
        r.findings.append(Finding("declared-source-dangling",
                                  f"副本声明的权威源不存在：{ds.group(1)}"))

    s_secs, c_secs = _sections(src_txt), _sections(cp_txt)
    orphan = sorted(k for k in c_secs if k not in s_secs)
    if orphan:
        r.findings.append(Finding("orphan-sections",
                                  f"副本有权威源没有的章节：{orphan}（凭空多出的口径）"))
    both = sorted(k for k in c_secs if k in s_secs)
    diverged = sorted(k for k in both if norm_text(c_secs[k]) != norm_text(s_secs[k]))
    r.notes.append(f"共有章节 {len(both)} 个：{both}；归一化后仍不同 {len(diverged)} 个：{diverged}")
    if diverged:
        r.findings.append(Finding(
            "sections-diverged", f"{len(diverged)} 个共有章节副本与权威源不一致：{diverged}",
            # 章节级差异是**已知存量形态**（副本是 165 行摘要、源是 986 行全文）
            # ⇒ 靠基线比较"是否变多"，而不是"是否为 0"。
        ))
    return r


# ═══════════════════════════════════════════════════════════════════════════
# C3 生成物新鲜度（I1：派生视图重生成 diff）
# ═══════════════════════════════════════════════════════════════════════════
def check_generated(a: Audit) -> CheckResult:
    r = CheckResult("generated-freshness")
    renderer = a.repo / ".github" / "render_cases.py"
    if not renderer.is_file():
        r.status = "error"
        r.error = ".github/render_cases.py 不存在"
        return r
    r.evaluated = 2
    with tempfile.TemporaryDirectory() as td:
        out_eval = Path(td) / "eval_cases.py"
        out_md = Path(td) / "casebook.md"
        p = subprocess.run(
            [sys.executable, str(renderer), "--cases", CASES_DIR,
             "--out-eval", str(out_eval), "--out-md", str(out_md)],
            capture_output=True, text=True, cwd=str(a.repo), timeout=300,
        )
        if p.returncode != 0:
            r.status = "error"
            r.error = f"重渲染失败：{(p.stderr or p.stdout).strip()[:400]}"
            return r
        renewed_eval = out_eval.read_text(encoding="utf-8")
        renewed_md = out_md.read_text(encoding="utf-8")

    for rel, renewed in ((GEN_EVAL, renewed_eval), (GEN_MD, renewed_md)):
        committed = a.read(rel)
        if committed is None:
            r.findings.append(Finding(f"{rel}|missing", f"生成物缺失：{rel}"))
            continue
        if committed != renewed:
            r.findings.append(Finding(
                f"{rel}|diverged",
                f"{rel} 与 `render_cases.py` 重渲染结果不一致 —— 改了 `.github/cases/` 但没提交生成物"
                f"（读的人看到的是旧快照）"))

    # 字段级新鲜度：**渲染器静默丢字段**是最隐蔽的陈旧快照形态。
    # 用 `pre_clean`（运行期复位声明）做哨兵：源里有，渲染结果里必须有。
    import yaml  # 延迟导入：只有本检查需要

    src_has_preclean = 0
    for f in sorted((a.repo / CASES_DIR).glob("*.yml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for c in d.get("cases") or []:
            if c.get("pre_clean"):
                src_has_preclean += 1
    if src_has_preclean and "pre_clean" not in renewed_eval:
        r.findings.append(Finding(
            "render-drops-pre_clean",
            f"用例库有 {src_has_preclean} 条 `pre_clean`，但渲染出的 {GEN_EVAL} 不含该字段"
            f"（派生视图丢了运行期复位声明 = 结构性陈旧快照）"))
    r.notes.append(f"用例库含 pre_clean 的用例：{src_has_preclean} 条")
    return r


# ═══════════════════════════════════════════════════════════════════════════
# C4 引用新鲜度（I1：结论必须绑定可判定引用）
# ═══════════════════════════════════════════════════════════════════════════
REF_PATH = re.compile(
    r"(?<![\w/])([A-Za-z0-9_][A-Za-z0-9_./\-]*\.(?:py|yml|yaml|java|ts|tsx|js|md|sh|sql|json)):(\d+)"
)
REF_SHA_QUAL = re.compile(r"@[0-9a-f]{7,40}")
BARE_LINE = re.compile(r"第\s*\d+(?:\s*[-–~]\s*\d+)?\s*行")
PATH_TOKEN = re.compile(
    r"[`\s(（\[][A-Za-z0-9_][A-Za-z0-9_./\-]*\.(?:py|yml|yaml|java|ts|tsx|js|md|sh|sql)\b"
)
HISTORY_MARK = ("旧副本", "历史值", "当时", "彼时", "旧值", "废弃路径")

# 夹具声明标记：**测试里的红证夹具必须是一个"失效的引用"字面量**（否则红证不成立），
# 因此测试文件里的引用字面量按定义就不该受引用新鲜度约束。声明方式 = 文件里任意位置
# 出现下面这一行（**只对 `tests/**` 生效**，文档/workflow 里加它无效）——
# 这样"误红"的修法是显式声明而不是把判据砍掉（判据对文档面照旧）。
FIXTURE_MARKER = "# drift-audit: refs-are-fixtures"


def _in_surface(rel: str) -> bool:
    if any(rel.startswith(x) for x in REF_SURFACE_EXEMPT):
        return False
    return rel.startswith(REF_SURFACE)


def _iter_surface_files(a: Audit) -> list[str]:
    exts = (".md", ".yml", ".yaml", ".py", ".sh", ".ts", ".tsx", ".js")
    return [f for f in a.tracked() if _in_surface(f) and f.endswith(exts)]


def check_refs(a: Audit) -> CheckResult:
    r = CheckResult("ref-freshness")
    base = a.base
    files = _iter_surface_files(a)
    r.evaluated = 0
    for rel in files:
        txt = a.read(rel)
        if txt is None:
            continue
        if rel.startswith("tests/") and FIXTURE_MARKER in txt:
            r.notes.append(f"{rel}: 声明了夹具标记 ⇒ 该文件的引用字面量不作判定（红证夹具按定义是失效引用）")
            continue
        for lineno, line in enumerate(txt.split("\n"), 1):
            sha_qual = bool(REF_SHA_QUAL.search(line))
            for m in REF_PATH.finditer(line):
                r.evaluated += 1
                ref_path, ref_line = m.group(1), int(m.group(2))
                # key 里**不出现 `路径:行号` 字面量**：`|` 分段。否则仅"提交一份基线"
                # 就会被别的 `path:NNN` 模式扫描（实证：case-trust 门禁的规则 G 扫 diff
                # 全部改动文件，把本基线的 key 判成悬空引用 ⇒ 本 PR 被别的门禁挡下）。
                key = f"{rel}|{ref_path}#{ref_line}"
                blocking = rel not in DERIVED_VIEWS
                cand = a.resolve_ref_path(ref_path)
                if not cand:
                    r.findings.append(Finding(
                        f"{key}|dangling",
                        f"{rel} 第 {lineno} 行引用 `{ref_path}:{ref_line}`，但仓库里没有这个文件",
                        blocking))
                    continue
                if len(cand) > 1:
                    r.notes.append(f"[歧义] {rel}:{lineno} `{ref_path}` 命中 {len(cand)} 个文件：{cand[:3]}")
                    continue
                target = cand[0]
                n = a.line_count(target, base)
                if n is not None and ref_line > n:
                    r.findings.append(Finding(
                        f"{key}|oor",
                        f"{rel} 第 {lineno} 行引用 `{ref_path}:{ref_line}`，但 {target} 在 {base} 上只有 {n} 行"
                        f"（**行越界 = 可证伪的失效引用**）",
                        blocking))
                    continue
                if not sha_qual:
                    r.findings.append(Finding(
                        f"{key}|bare",
                        f"{rel} 第 {lineno} 行 `{ref_path}:{ref_line}` 无 `@<sha>` 限定"
                        f"（活跃文件的裸行号几分钟就会失效 —— dev-flow §16.7『引用纪律』禁写 `path:NNN`）",
                        blocking))
            bare = BARE_LINE.search(line)
            if bare and PATH_TOKEN.search(line):
                r.evaluated += 1  # 计入判定面（否则"只写 `第 N 行`"的树会被判成空面）
            if bare and PATH_TOKEN.search(line) and not sha_qual \
                    and not any(h in line for h in HISTORY_MARK):
                key = f"{rel}|bare-line|{bare.group(0)}"
                r.findings.append(Finding(
                    key,
                    f"{rel} 第 {lineno} 行用裸行号 `{bare.group(0)}` 定位同行的文件，"
                    f"无 `@<sha>` 也无历史标记（改成符号/文本锚点，或写成 `第 N 行` + `@<sha>`）",
                    rel not in DERIVED_VIEWS))
    r.notes.append(f"受管引用面 {len(files)} 个文件；判定引用 {r.evaluated} 处")
    return r


# ═══════════════════════════════════════════════════════════════════════════
# C5 可变引用计数（I2：身份不可变）
# ═══════════════════════════════════════════════════════════════════════════
MUTABLE_KEY = re.compile(r"(name|keyword|index|idx|ordinal|position|title|tag)", re.I)
MUTABLE_KEY_EXEMPT = {"order_no", "ticket_no", "phone", "id", "product_id", "customer_id"}
ORDINAL_VALUE = re.compile(r"(第\s*[一二三四五六七八九十0-9]+\s*[个条次款]|最新|最后一个|第一个|前一个)")

# 哪些字段是**定位位置**（用来找到被测对象）。用户输入里的名字/序号是合理表达，永不在此列。
LOCATOR_FIELDS: dict[str, set[str]] = {
    "pre_clean": {"type", "price"},          # 排除项：这些不是定位键
    "db_verify": {"fetch", "source", "checks"},
    "precondition": {"type"},
    "post_session": {"fetch", "agent_type", "checks"},
    "output_verify": {"tool", "action", "expect"},
    "amount_verify": {"tool", "checks"},
}


def _is_mutable(key: str, value: Any) -> bool:
    if key in TURN_ORDINAL_KEYS:
        return True  # `auto_select` / `_index:` 这类**结构化选择器**本身就是可变键
    if key in MUTABLE_KEY_EXEMPT:
        return False
    if MUTABLE_KEY.search(key):
        return True
    return isinstance(value, str) and bool(ORDINAL_VALUE.search(value))


# 「回合指令」里的**结构化选择器**：`auto_select: true` = 点第一项（序数类定位）。
# ⚠️ 它常写在 `user_inputs` 列表里，与用户说的话**混在同一个列表**——
# 但两者性质完全不同：用户说「第一个」是**表达方式**（合理），
# `auto_select: true` 是**结构化定位指令**（点"首项"，无卡时还会退化成发字面量「第一个」）。
# dev-flow §18.3 明确把 `auto_select` 归入序数类禁止项（实证 #3160 / #2991 / #3568）。
TURN_ORDINAL_KEYS = {"auto_select", "_index", "index", "idx", "position", "ordinal", "seq"}


def _iter_locators(case: dict) -> list[tuple[str, str, Any]]:
    """产出 (分量名, 键名, 值) —— 只取"定位被测对象"的位置。"""
    out: list[tuple[str, str, Any]] = []
    # 回合指令里的结构化选择器（`user_inputs` 的 dict 项；字符串项 = 用户原话，不计）
    for item in case.get("user_inputs") or []:
        if isinstance(item, dict):
            for k, val in item.items():
                if k in TURN_ORDINAL_KEYS and val not in (False, None, 0, ""):
                    out.append((f"turn.{k}", k, val))
    for fieldname, skip in LOCATOR_FIELDS.items():
        v = case.get(fieldname)
        if not v:
            continue
        # amount_verify 的唯一可变键是 product_name（选择订单行）
        items = v if isinstance(v, list) else [v]
        for it in items:
            if not isinstance(it, dict):
                continue
            for k, val in it.items():
                if k in skip or k.startswith("expect_") or k.startswith("forbidden_"):
                    continue
                if fieldname == "amount_verify" and k != "product_name":
                    continue
                out.append((f"{fieldname}.{k}", k, val))
    for ns in case.get("namespaces") or []:
        if isinstance(ns, str) and ":" in ns:
            k, val = ns.split(":", 1)
            out.append((f"namespaces.{k}", k, val))
    return out


def check_mutable_locators(a: Audit) -> CheckResult:
    r = CheckResult("mutable-locator")
    import yaml

    cases_dir = a.repo / CASES_DIR
    per_key: dict[str, int] = {}
    per_case: dict[str, list[str]] = {}
    total_cases = 0
    for f in sorted(cases_dir.glob("*.yml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for c in d.get("cases") or []:
            total_cases += 1
            hits = [comp for comp, k, v in _iter_locators(c) if _is_mutable(k, v)]
            if hits:
                per_case[c.get("id", "?")] = hits
                for comp in hits:
                    per_key[comp] = per_key.get(comp, 0) + 1
    r.evaluated = total_cases
    if total_cases == 0:
        r.status = "error"
        r.error = f"{CASES_DIR} 下 0 条用例（判据面为空 = 护栏失效）"
        return r
    total = sum(per_key.values())
    r.notes.append(f"用例总数 {total_cases}；含可变定位键的用例 {len(per_case)} 条；"
                   f"定位位置合计 {total} 处（分量：{per_key}）")
    r.notes.append("**用户输入（user_inputs / data_checks 的自然语义）里的名字、序号不计**"
                   "—— 那是用户的表达方式，不是定位键")
    for comp, n in sorted(per_key.items()):
        r.findings.append(Finding(
            f"component|{comp}", f"{comp} 有 {n} 处用可变键定位被测对象"
            f"（用例自建唯一名 / 绑定 order_no 才能免疫，见契约 I2）"))
    if not per_key:
        r.notes.append("无任何可变定位键")
    return r


# ═══════════════════════════════════════════════════════════════════════════
# C6 无心跳的调度任务（I4）
# ═══════════════════════════════════════════════════════════════════════════
SCHED_LINE = re.compile(r"^\s*-?\s*cron:\s*['\"]?([^'\"\n]+)['\"]?", re.M)
PAUSED_SCHED = re.compile(r"^\s*#\s*(schedule:|-?\s*cron:)", re.M)


def _period_minutes(cron: str) -> int | None:
    parts = cron.split()
    if len(parts) != 5:
        return None
    mi, ho, dom, mon, dow = parts
    if mi.startswith("*/") and ho == "*" and dom == "*":
        return int(mi[2:])
    if mi.isdigit() and ho == "*":
        return 60
    if mi.isdigit() and ho.isdigit():
        if dom == "*" and mon == "*" and dow == "*":
            return 1440
        if dom.startswith("*/") and mon == "*" and dow == "*":
            return int(dom[2:]) * 1440
        if dom.isdigit() and mon == "*" and dow == "*":
            return 30 * 1440
        if dom == "*" and mon == "*" and dow.isdigit():
            return 7 * 1440
    return None


def _gh_runs(a: Audit, workflow: str, limit: int = 40) -> list[dict] | None:
    """返回 run 列表；不可达 ⇒ None（**降级为未知，不假装通过**）。

    `progress` 用**单次** `gh run list`（不带 `--workflow`）会把历史压成窗口 ——
    低频调度（月任务）会被挤出窗口而误判『从未跑过』，所以必须逐 workflow 取；
    逐次串行实测 ~11 × 3s 撞 60s 超时 ⇒ 用线程池并发（判据不变，只改取数方式）。
    """
    if a.gh_fixture is not None:
        try:
            data = json.loads(a.gh_fixture.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data.get(workflow)
    if a.offline or not shutil.which("gh"):
        return None
    try:
        p = subprocess.run(
            ["gh", "run", "list", f"--workflow={workflow}", f"--limit={limit}",
             "--json", "status,conclusion,createdAt,displayTitle"],
            capture_output=True, text=True, timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return None


def _parse_ts(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def check_heartbeat(a: Audit) -> CheckResult:
    r = CheckResult("heartbeat")
    wf_dir = a.repo / ".github" / "workflows"
    scheduled: list[tuple[str, list[str]]] = []
    paused: list[str] = []
    for f in sorted(wf_dir.glob("*.yml")):
        txt = f.read_text(encoding="utf-8", errors="ignore")
        head = txt.split("\njobs:")[0]
        crons = SCHED_LINE.findall(head)
        if crons:
            scheduled.append((f.name, [c.strip() for c in crons]))
        elif PAUSED_SCHED.search(txt):
            paused.append(f.name)
    r.evaluated = len(scheduled) + len(paused)
    for name in paused:
        r.findings.append(Finding(
            f"{name}|paused",
            f"{name} 的 `schedule:` 被**注释停用** —— 冻结的调度是「陈旧」最喜欢的藏身处："
            f"没有任何心跳会响，也没有任何红会因为停摆而红"))
    if not scheduled and not paused:
        r.status = "error"
        r.error = "仓里没有任何 `schedule:` 工作流（判据面为空 = 护栏失效）"
        return r

    unknown: list[str] = []
    # 本 PR **新增**的 workflow 在合并前 `gh run list --workflow=<file>` 必然解析不到
    # （`gh` 只认默认分支上的 workflow 文件）⇒ 记 `pending-merge` 备注，**不当成漂移**
    # （否则"监控自己"会在首次合并前后自造假红）。合并后它落到 main，判定自动生效。
    base_ok = a.git_ok("rev-parse", "--verify", f"{a.base}^{{commit}}")
    if not base_ok:
        r.notes.append(f"**基准 {a.base} 不可解析**（浅检出？）⇒ 无法判定哪些 workflow 是"
                       f"本 PR 新增的；本次跳过 pending-merge 规则（**不等于通过**）")
    pending = ({name for name in (n for n, _ in scheduled)
                if not a.exists_at(f".github/workflows/{name}", a.base)} if base_ok else set())
    from concurrent.futures import ThreadPoolExecutor
    workers = 1 if (a.offline or a.gh_fixture) else min(8, max(1, len(scheduled)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        fetched = list(pool.map(lambda n: _gh_runs(a, n), [n for n, _ in scheduled]))
    for (name, crons), runs in zip(scheduled, fetched):
        if name in pending:
            # 本 PR 新增的 workflow：`gh` 只认默认分支上的 workflow 文件，且它**自己的
            # 这次 run**（in_progress）会被 `gh run list` 看到 ⇒ 不能拿"自己的未完成"
            # 当"零成功"（首次上线时该 workflow 就是自己的心跳证据 = 自指假红）。
            r.notes.append(f"{name}: 本 PR 新增的 workflow（{a.base} 上不存在）⇒ "
                           f"**合并后才纳入心跳判定**（pending-merge）")
            continue
        if runs is None:
            unknown.append(name)
            r.notes.append(f"{name}: gh 不可达 ⇒ **未知**（不等同于通过）")
            continue
        if not runs:
            r.findings.append(Finding(f"{name}|never-ran", f"{name} 有 schedule 但**从未跑过**"))
            continue
        succ = [t for t in (_parse_ts(x.get("createdAt", "")) for x in runs
                            if x.get("conclusion") == "success") if t]
        period = min([p for p in (_period_minutes(c) for c in crons) if p] or [0]) or None
        if not succ:
            last = _parse_ts(runs[0].get("createdAt", ""))
            age = (a.now - last).days if last else "?"
            r.findings.append(Finding(
                f"{name}|never-succeeded",
                f"{name} 近 {len(runs)} 次运行**零成功**（最近一次 {runs[0].get('createdAt','?')} "
                f"→ {runs[0].get('conclusion')}，约 {age} 天前）—— 停在「一直在失败」的状态"
                f"却没有任何机制因它不心跳而红"))
            continue
        age = a.now - max(succ)
        threshold = timedelta(minutes=period * 3) if period else timedelta(days=3)
        if period and period >= 1440:
            threshold = timedelta(minutes=period + 2 * 1440)
        r.notes.append(f"{name}: 周期 {period}min，最近成功 {max(succ).date()}（{age.days} 天前），"
                       f"阈值 {threshold}")
        if age > threshold:
            r.findings.append(Finding(
                f"{name}|stale",
                f"{name} 最近成功在 {age.days} 天前（周期 {period}min，阈值 {threshold.days} 天）"
                f"—— 调度还挂着但已经不产出"))
    if unknown and len(unknown) == len(scheduled):
        # 全部未知 ⇒ 心跳判定整体不可用，必须显式标注（`--fail-on-unknown` 时按未知=坏处理）
        r.status = "unknown"
        r.notes.append(f"**全部 {len(unknown)} 个调度工作流的心跳都是未知（gh 不可达）** —— "
                       f"本项整体不构成结论")
    return r


# ═══════════════════════════════════════════════════════════════════════════
# C7 退化守卫（meta：护栏自身纳入 L0）
# ═══════════════════════════════════════════════════════════════════════════
def check_regression_guard(a: Audit) -> CheckResult:
    r = CheckResult("regression-guard")
    r.evaluated = len(CHECKS)
    if not CHECKS:
        r.status = "error"
        r.error = "判据集合为空 —— 审计退化成了空跑"
        return r
    for c in CHECKS:
        if not c.judgment.strip() or not c.remedy.strip():
            r.findings.append(Finding(
                f"{c.id}|missing-contract",
                f"判据 {c.id} 缺『判定方式』或『违反后的处置』—— 契约文档第 4 列不许留空"))
        if c.min_evaluated < 1:
            r.findings.append(Finding(f"{c.id}|empty-surface",
                                      f"判据 {c.id} 允许判定面为 0（空集恒真 = 空断言）"))
    r.notes.append(f"判据集合：{[c.id for c in CHECKS]}")
    r.notes.append(f"未实装登记：{[u['id'] for u in UNIMPLEMENTED]}")
    return r


# ═══════════════════════════════════════════════════════════════════════════
# 判据集合（护栏清单：每条必须写清判定方式与违反后的处置）
# ═══════════════════════════════════════════════════════════════════════════
CHECKS: list[Check] = [
    Check(
        id="skill-anchor", invariant="I1/I4",
        title="技能活锚新鲜度",
        judgment="逐技能比较仓库 `.agent-presets/**/SKILL.md` 的 `version:` + 逐字节 sha256 + "
                 "活锚仓库落后 `origin/main` 的提交数；活锚不存在 ⇒ 未知（不判通过）。",
        remedy="`cp -R .agent-presets /` 重装活锚（或重跑 preset 安装脚本），再重载技能；"
               "落后提交数 > 0 时先 `git -C <活锚仓库> pull`。",
        fn=check_skill_anchor, min_evaluated=1,
    ),
    Check(
        id="preset-monotonic", invariant="I1",
        title="预设版本单调性（技能版本不得降级）",
        judgment="对 `origin/main`（或 `--base`）与工作树的 `.agent-presets/migao/skills/*/SKILL.md` "
                 "比 `version:`：**下降 ⇒ 红**（不许存量放行）；**同版本但内容不同 ⇒ 红**（那是分叉）；"
                 "上升或相同且内容一致 ⇒ 绿。",
        remedy="你的 worktree 里的 `.agent-presets/` 是**创建时的快照**：`git fetch origin main && "
               "git rebase origin/main` 后再提交（`git checkout origin/main -- .agent-presets`），"
               "**不要**用 `git add -A` 把旧预设带上去。",
        fn=check_preset_monotonic, min_evaluated=1,
    ),
    Check(
        id="sync-copy", invariant="I1",
        title="同步副本 diff",
        judgment="`docs/wiki/DEV-FLOW.md` 声明的『当前版本』必须等于权威源 `migao-dev-flow/SKILL.md` 的 "
                 "`version:`；声明的权威源路径必须存在；副本不得有权威源没有的章节；"
                 "共有章节归一化后不同的**条数**与基线比较。",
        remedy="改流程**先改技能**再同步副本（副本自称『两份不一致时按技能执行』，但读者不会去比）；"
               "同步后 `--regen-baseline --reason`，并在 PR 里说明销账项。",
        fn=check_sync_copy, min_evaluated=3,
    ),
    Check(
        id="generated-freshness", invariant="I1",
        title="生成物新鲜度（派生视图重生成 diff）",
        judgment="重跑 `.github/render_cases.py` 后与提交的 `eval_cases.py` / `mibao-verification-cases.md` "
                 "逐字节比较；并断言用例库里的 `pre_clean` 字段在渲染结果里存在（渲染器静默丢字段）。",
        remedy="以 `.github/cases/` 为唯一源重渲染并提交生成物：`python3 .github/render_cases.py "
               "--cases .github/cases --out-eval tests/agent_eval/eval_cases.py "
               "--out-md docs/testing/mibao-verification-cases.md`；**不要手改生成物**。",
        fn=check_generated, min_evaluated=2,
    ),
    Check(
        id="ref-freshness", invariant="I1",
        title="引用新鲜度",
        judgment="受管引用面上每个 `path:NNN`：路径必须能解析（否则悬空）、行号不得超过目标文件行数"
                 "（否则越界）、且必须带 `@<sha>` 限定（否则裸行号）；带文件名的 `第 N 行` 同理。"
                 "派生视图（生成物）只报告不阻塞（违规归因到源面）。",
        remedy="把 `path:NNN` 改成**符号/文本锚点**（首选）或 `第 N 行` + `@<sha>`（限定值）；"
               "越界引用直接删掉行号只留符号（见 dev-flow §16.7『引用纪律』）。"
               "**例外**：若该字面量是**测试的红证夹具**（按定义必须是失效引用），"
               f"在 `tests/**` 文件里加一行 `{FIXTURE_MARKER}` 显式声明即可 —— "
               "**不要**为此放宽判据。",
        fn=check_refs, min_evaluated=1,
    ),
    Check(
        id="mutable-locator", invariant="I2",
        title="可变引用计数（用例层）",
        judgment="统计 `pre_clean` / `db_verify` / `precondition` / `post_session` / `output_verify` / "
                 "`amount_verify` / `namespaces` 里用**名字 / 序号 / 位置**定位被测对象的条数，"
                 "输出分量与总量并与基线比较。**用户输入里的名字/序号不计**（那是用户的表达方式）。",
        remedy="改用不可变标识：用例自建唯一名（含随机后缀）或绑定 `order_no`/`phone`/自建 id；"
               "`db_verify` 按 name 取首条会被同名种子商品顶替（实证 PR-019）。",
        fn=check_mutable_locators, min_evaluated=1,
    ),
    Check(
        id="heartbeat", invariant="I4",
        title="无心跳的调度任务",
        judgment="列出所有用 `schedule:` 的 workflow（含**被注释停用**的），比对最后一次**成功**运行的时间"
                 "与 cron 周期推出的阈值；零成功 / 从未跑过 / 超过阈值 ⇒ 漂移。"
                 "`gh` 不可达 ⇒ 该项记『未知』，**不假装通过**。",
        remedy="先看最近一次失败 job 日志定位根因；确因环境波动则修稳定再恢复 `schedule:`，"
               "不要长期挂着不产出的调度（停摆不会自己变红）。",
        fn=check_heartbeat, network=True, min_evaluated=1,
    ),
    Check(
        id="regression-guard", invariant="meta",
        title="退化守卫（护栏自身）",
        judgment="判据集合不得为空；每条判据必须写清判定方式与违反后的处置；每条判据的判定面不得为 0；"
                 "基线清单不得含『已不再漂移』的条目。**任一 ⇒ 红。**",
        remedy="补回判据 / 补 `judgment`+`remedy` / 删掉基线里已归零的条目（`--regen-baseline`）。",
        fn=check_regression_guard, min_evaluated=1,
    ),
]
CHECK_BY_ID = {c.id: c for c in CHECKS}

# ── 未实装登记（**如实登记，不用恒真判断凑数**）──────────────────────────────
UNIMPLEMENTED: list[dict[str, str]] = [
    {
        "id": "ref-semantic-hit",
        "invariant": "I1",
        "what": "引用的**语义**命中校验（`path:NNN` 指的那一行到底是不是被引用的东西）",
        "why": "唯一可机判的形态是『同行反引号锚点串必须出现在目标行』。2026-09-15 在 "
               "origin/main 受管引用面上实测：26 条带锚引用 **20 条误红**"
               "（多引用同行 / 锚点是另一条引用 / 锚点是整句散文）。"
               "按 migao-acceptance『误红即坏断言』，不做语义命中。",
        "missing": "需要引用方给出**结构化**的期望锚点（如 `path:NNN#symbol`），"
                   "或把引用改写成符号锚 —— 那是写法契约变更，属指令层（`.agent-presets/**`），本包不改。",
    },
    {
        "id": "hardcoded-count",
        "invariant": "I1",
        "what": "写死条数（如『C 端全量 ~40 条』『B 端 ~47 条』）随用例库漂移的检测",
        "why": "受管引用面上 `~?N 条` 命中 **63 处**，绝大多数是叙事/历史语境"
               "（『6 条确定性失败』『15 条 × 1 次采样』『此前写死 4 条』），"
               "**无零误红的判据**（无法区分『断言当下条数』与『复述历史读数』）。"
               "issue #3787 第 4 条正是此族。",
        "missing": "需要用例库给出**机器可读的条数声明位**（如 `truths_ref` 里的计数锚），"
                   "或把这类句子改成『以 X 为单一事实源』的无数字写法 —— 属 `cases/**` 与 "
                   "`tests/unit_ci_workflows/**`（#3787 单）。",
    },
    {
        "id": "section-pointer-semantic",
        "invariant": "I1",
        "what": "章节锚点引用（`§16.5` / `见 dev-flow 16.5`）指向的章节**内容**是否与引用语境相符",
        "why": "章节号存在性可判（当前 `16.5` 确实存在），但『该不该指 16.5 而不是 16.7』"
               "要读语义。issue #3787 第 1/2 条即此族。",
        "missing": "需要引用方写『`§16.7 派发后`』这类**带章节标题**的锚，"
                   "使存在性判定升级为标题命中判定 —— 属指令层写作规范。",
    },
    {
        "id": "runtime-fencing",
        "invariant": "I1/I3",
        "what": "运行期护栏：结论绑定 `(sha, cases_fingerprint, policy_version, 环境指纹)`、"
                "用例前置自断言 fail-closed（不成立即 fail-closed，不得退化成『agent 表现不好』的红）",
        "why": "实装点在 `tests/agent_eval/local_runner.py`（评测运行器），**由另一任务包落地**；"
               "本包按边界**不碰 runner**。本脚本已产出并落盘 `cases_fingerprint` / `base` / "
               "`policy_version` 三项，供那层直接引用。",
        "missing": "runner 侧在 summary 的 `run_key` 里写入四项指纹 + 前置断言失败走 fail-closed 分支。"
                   "契约口径见 `docs/wiki/truth-source-contract.md` §『运行期护栏』。",
    },
    {
        "id": "sync-copy-landing",
        "invariant": "I1",
        "what": "把 `docs/wiki/DEV-FLOW.md` 的『同步副本』claim **兑现**（由权威源渲染）"
                "或**撤回**（标注非权威）",
        "why": "两种落地都要改 `docs/wiki/DEV-FLOW.md` **正文**，而该文件正被别的包改"
               "（本包开工时主工作区里它已是 `M` 状态）⇒ 顺手重写会与在飞改动相撞"
               "（migao-dev-flow §17.3「多个 worker 改同一个文件」）。本包只做**判据**"
               "（版本戳一致性已落码并给出真实红例：页面 v1.3 / 权威源 1.28.0）。",
        "missing": "后续小单二选一：① 加 `scripts/render_dev_flow.py`（取 SKILL.md 去 frontmatter + "
                   "4 行页头 → 输出副本），于是『重生成后 diff == 0』成为合法判据；"
                   "② 删掉『同步副本』claim，页头改『非权威、可能滞后，流程口径以技能为准』"
                   "（保留版本戳检查）。方案写在 docs/wiki/truth-source-contract.md §4。",
    },
    {
        "id": "world-selfbuilt-namespace",
        "invariant": "I3",
        "what": "并发世界自建：写用例的**显式资源声明**（namespace 锁）覆盖率门禁",
        "why": "289 条用例里只有 **19 条**声明 `namespaces`。『哪些用例算写用例』本身无零误红判据"
               "（工具是读还是写由工具实现决定，不在用例声明里）。故当前只作**活指标**报告，不阻塞。",
        "missing": "需要用例 schema 补『写工具清单』或 runner 导出每轮的写工具事件，才能把"
                   "『写用例未声明 namespace』变成可判定的结构性缺失。",
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# 基线
# ═══════════════════════════════════════════════════════════════════════════
def load_baseline(path: Path) -> dict:
    if not path.is_file():
        return {"schema": BASELINE_SCHEMA, "policy_version": POLICY_VERSION, "entries": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"schema": BASELINE_SCHEMA, "policy_version": POLICY_VERSION, "entries": {}}


def _counts(findings: list[Finding]) -> dict[str, int]:
    """只统计**可基线化**的漂移（`env=True` 的永不进基线，见 `Finding` 文档）。"""
    out: dict[str, int] = {}
    for f in findings:
        if f.env or f.always:
            continue
        out[f.key] = out.get(f.key, 0) + 1
    return out


def _load_gate_module():
    """加载 `.github/case_trust_gate.py`（**判据的单一真相源**，#4045）。

    为什么 import 而不是复制：本脚本原先的 `stale_blocking` 注释自称「沿用
    `case_trust_gate` 的 `stale_baseline_entries` 口径」，而 #4031 已把那边改成
    **全量对账 + 反向对账 + burn-down 预算** ⇒ 两份口径**已分叉**，那句注释成了
    **假真值**。现在「陈旧即红」的判据只有一处（`case_trust_gate.reconcile_baseline` /
    `burn_down_verdict`），本脚本只做**形态搬运**（`{key: 计数}` ⇄ `{case_id: [码]}`）。

    用 `importlib` 按**路径**加载：不往 `sys.path` 里塞 `.github/`（那是 case-trust 自己的
    加载方式，本项目其余脚本没有这个约定），也不依赖当前工作目录。
    """
    path = Path(__file__).resolve().parents[1] / ".github" / "case_trust_gate.py"
    spec = importlib.util.spec_from_file_location("case_trust_gate", path)
    if spec is None or spec.loader is None:  # pragma: no cover —— 路径算错才会发生
        raise RuntimeError(f"加载不了判据单一源：{path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ⚠️ 「陈旧即红」的判据**不在本文件**：调 `case_trust_gate.reconcile_baseline`（#4045）。
# 本脚本只把 `{条目 key: 计数}` 摊平成那边认识的 `violations_by_case` 形态。
DRIFT_RECONCILE_HINT = (
    f"全量对账（#4045）—— 基线条目**只许缩短**：修法是机械的 `{REGEN_COMMAND}`；"
    "本 PR 若确实要保留某条，就得让它在**全库重算**里仍然真的漂移。"
)


def _codes_of(entries: dict[str, int]) -> dict[str, list[str]]:
    """`{key: 计数}` → `{key: [码, …]}`（每个计数展开成**互不相同**的码）。

    为什么要展开：计数是「豁免面」的真实大小，只写成 `{key}` 会让 `5 → 3` 的净缩
    变成「key 仍在 ⇒ 不陈旧」= **永久豁免**（#4031 治的正是这个）。展开后
    `5 - 3 = 2` 条码消失 ⇒ 全量对账如实判陈旧，与 case-trust 的码级差集**同构**。
    """
    out: dict[str, list[str]] = {}
    for k, n in (entries or {}).items():
        if n > 0:
            out[k] = [k if n == 1 else f"{k} × {i}" for i in range(1, n + 1)]
    return out


def _as_violations(codes: dict[str, list[str]]) -> dict[str, list[dict]]:
    """形态适配：case-trust 的**裁决输入**是 `{id: [{"code": …}]}`（`judge_case` 的产物），
    本脚本的码就是字符串 ⇒ 只做这一层包装，**不碰任何判据**。"""
    return {k: [{"code": c} for c in v] for k, v in codes.items()}


def _as_baseline(entries: dict[str, int]) -> dict:
    """形态适配：case-trust 的**清单**是 `{"violations": {id: {"codes": [...]}}}`，
    本脚本的是 `{条目 key: 计数}` ⇒ 只做这一层包装，**不碰任何判据**。

    ⚠️ 盲目传 `{id: [...]}`（不经 `violations` 包一层）会让 `_recorded_codes` 解析不到码 ⇒
    清单**看起来是空的** ⇒ 陈旧项静默消失（实测踩过一次：`recorded_entries: 0`）。
    """
    return {"violations": {k: {"codes": v} for k, v in _codes_of(entries).items()}}


def _budget_baseline(entries: dict[str, dict[str, int]], burn_down: Any = None) -> dict:
    """把 `{判据: {条目: 计数}}` 摊平成 `burn_down_verdict` 认识的清单形态。

    ⚠️ 这个包装不是可选的：`_count_exemptions` 只读 `violations` 键 ⇒ 直接喂本脚本的
    `{"entries": …}` 会让**豁免面恒为 0**，于是「每 PR 最低消减」永远显示"已清零、自动满足"
    = **预算形同虚设**（实测踩过一次：`in_scope=True` 却不红）。
    """
    flat: dict[str, int] = {}
    for check_entries in entries.values():
        for k, n in (check_entries or {}).items():
            flat[k] = flat.get(k, 0) + n
    out = _as_baseline(flat)
    if burn_down is not None:
        out["burn_down"] = burn_down
    return out


def reconcile_baseline(check_id: str, now_entries: dict[str, int],
                       cur_entries: dict[str, int],
                       base_entries: dict[str, int]) -> dict:
    """**全量对账**（#4045）：复用 `case_trust_gate.reconcile_baseline`，**不复制判据**。

    · `stale`（阻塞）：清单里记着、**全库重算**里已不漂移 ⇒ 必须移除。**不限本次 diff**：
      这正是「永久豁免」的来源（实证：基线 `…|local_runner.py#3899|bare` 在引用它的测试
      改掉后仍躺在清单里，旧口径 `--check` 只有告警，没人会因此变红）。
    · `dropped`（阻塞）：`--base` 清单里记着、**现在仍然漂移**，却被本 PR 删掉 ⇒
      **删条目 = 偷偷缩短**（没有这一条，「只许缩短」就退化成「随便删都算缩短」，而
      burn-down 预算恰恰在施压让人删条目）。

    `now_entries` = 本判据**全库**重算的 `{key: 计数}`；`cur_entries` = 当前清单里该判据的条目；
    `base_entries` = `--base`（`origin/main`）那一份。
    """
    now, cur, base = _codes_of(now_entries), _codes_of(cur_entries), _codes_of(base_entries)
    recon = _load_gate_module().reconcile_baseline(_as_baseline(cur_entries),
                                                  _as_violations(now),
                                                  _as_baseline(base_entries))
    stale_keys = {c for s in recon["stale"] for c in s["removed_codes"]}
    dropped_keys = {c for d in recon["dropped"] for c in d["dropped_codes"]}
    # 判据来自上面那次调用；这里只把结果**归位**到 drift_audit 的形态（`{key: 计数}`）并
    # 加上本门的修法文案 —— 不重算一遍「是否陈旧」（那才是第二份判据）。
    stale = [{"key": k, "count": cur_entries[k], "check": check_id,
              "hint": f"基线条目 `{k}` 已不再漂移（**全量对账**，不再限于本次 diff 命中）"
                      f"—— 请从 {DEFAULT_BASELINE} 移除或收窄，命令：{REGEN_COMMAND}"}
             for k in sorted(stale_keys)]
    dropped = [{"key": k, "count": base_entries[k], "check": check_id,
                "hint": f"`origin/main` 的清单里记着 `{k}`（{base_entries[k]} 处），"
                        f"且**现在仍然漂移**，却被本 PR 从清单删掉 ⇒ **新增豁免**（基线只许"
                        f"缩短；R4：新违规只有两个出口 —— 本次修掉 / 开独立 issue 登记）。"
                        f"请恢复该条，或在本次把漂移修掉。"}
               for k in sorted(dropped_keys)]
    return {"stale": stale, "dropped": dropped,
            "blocking": bool(stale or dropped),
            "gate_blocking": bool(recon["blocking"])}


def compare_baseline(result: CheckResult, base_entries: dict[str, int],
                     changed: set[str] | None = None,
                     recorded_entries: dict[str, int] | None = None,
                     base_check_entries: dict[str, int] | None = None,
                     unverifiable: bool = False) -> dict[str, list]:
    """返回 {new, known, paydown, stale, stale_blocking, dropped, reconcile}。
    **基线只许缩短**的判定全在这里。

    ⚠️ **`stale` 的阻塞口径 = 全量对账**（#4045）：清单里任何「已不再漂移」的条目都阻塞，
    **不再限于本次 diff 命中**（旧口径见 issue #4045 与未实装登记 `DRIFT-AUDIT-STALE-DIFF-SCOPED`，
    该登记已随本项落地撤销）。`changed` 仍用于**新增**漂移的面内/面外区分（`_in_scope`：
    面外新增不阻塞本 PR）与「本次有没有动判据面」（burn-down 的 `scope`），与陈旧判定无关。
    `changed=None`（`--stale-scope none`，无 PR 上下文的纯审计）⇒ 不判阻塞，只报告。

    `unverifiable`（本次**没能重算**这条判据）⇒ 条目进 `unverifiable_stale` 而**不进**
    `stale`：没重算 ≠ 已不漂移（"没跑"必须长得像"没跑"）。**实证**：`--offline` 时
    `heartbeat` 的 gh 查询全部返回「未知」⇒ `never-succeeded` 这类条目看起来归零，
    若无条件判陈旧就会**凭空判红**（全量对账的正确性依赖"输入真的重算过"）。

    四个入参各司其职，**混用任一个都会造出假红或永久豁免**（首个实现即踩，故写清）：
    · `base_entries` —— 新增/放行/销账的**计数参照**（新漂移的 delta 由它算）；
      同时充当 `recorded`/`base` 的缺省值（调用方没分别传时三者合一，见下）；
    · `recorded_entries` —— **正向对账（陈旧）** 的参照 = **本 PR 的清单**（记了却不再漂移）；
    · `base_check_entries` —— **反向对账（被删）** 的参照 = `--base` 那一份（缺省退回
      `recorded_entries`：`--base` 上还没有清单时不存在「相对 base 被删」这回事）。
    """
    recorded = recorded_entries if recorded_entries is not None else base_entries
    reconcile_base = base_check_entries if base_check_entries is not None else recorded
    now = _counts(result.findings)
    new, new_out, known, paydown, stale = [], [], [], [], []
    for k, n in sorted(now.items()):
        b = base_entries.get(k, 0)
        if b == 0:
            delta = n
        elif n > b:
            delta = n - b
        else:
            delta = 0
        if delta:
            (new if _in_scope(k, changed) else new_out).append((k, delta))
        elif n == b:
            known.append((k, n))
        else:
            paydown.append((k, b - n))
    recon = reconcile_baseline(result.check_id, now, recorded, reconcile_base)
    # ⚠️ **陈旧/被删一律以全量对账的结论为准**（`recon`），不在这里另算一套：
    # · 阻塞只在有 PR 上下文（`changed is not None`）时生效 —— `--stale-scope none` /
    #   `--regen-baseline` 声明了「没有 PR 上下文」，此时只报告；
    # · 且只认**本次真的跑过**的判据（`now` 为空 ⇒ 该判据本轮没跑 ⇒ 不得读成「已不漂移」：
    #   "没跑"必须长得像"没跑"，否则 `--only` 会凭空产出陈旧项 = 假红）。
    stale = [(s["key"], s["count"]) for s in recon["stale"]]
    unverifiable_stale = stale if unverifiable else []
    stale = [] if unverifiable else stale
    stale_blocking = stale if changed is not None else []
    return {"new": new, "new_out_of_scope": new_out, "known": known, "paydown": paydown,
            "stale": stale, "stale_blocking": stale_blocking,
            "unverifiable_stale": unverifiable_stale,
            "dropped": recon["dropped"], "reconcile": recon}


def _entry_file(key: str) -> str:
    """基线条目 key 的首段（各判据的 key 构造见对应 check）。"""
    return key.split("|")[0]


_PATHISH = re.compile(r"[/.]")


def _in_scope(key: str, changed: set[str] | None) -> bool:
    """该条目是否**属本 PR 的改动面**。

    文件型 key（首段像路径）⇒ 看是否在本 PR 改动集里；分量/调度名型 key ⇒ 一律算本 PR 面
    （它们没有可归因的文件，且变化本身就值得拦）。

    **为什么需要这条**：新增漂移若来自**并行包刚合并进 main 的文件**，把本 PR 判红就是
    `migao-acceptance` 说的「假红」—— 报错指向错误的对象，还会挡住无关的 PR
    （同款裁定见 #3846「基线陈旧项降级为告警」）。故：`--check` 只对**本 PR 改动面**
    的新增漂移 fail-closed；面外的记 ⚠️ 并在**定时腿**（`--strict-stale`）红。
    """
    if changed is None:
        return True
    first = _entry_file(key)
    if not _PATHISH.search(first):
        return True
    return first in changed


def changed_files(a: Audit) -> set[str]:
    """本 PR 相对 base 改动/新增的文件集（`base...HEAD` 三点 diff）。"""
    out = a.git("diff", "--name-only", f"{a.base}...HEAD")
    if not out.strip():
        out = a.git("diff", "--name-only", a.base)
    return {x.strip() for x in out.split("\n") if x.strip()}


def run_audit(a: Audit, baseline: dict, only: list[str] | None,
              changed: set[str] | None = None,
              base_baseline: dict | None = None) -> dict:
    """跑全部判据并做**全量对账 + burn-down 预算**（#4045）。

    `base_baseline` = `--base`（`origin/main`）那一份基线：反向对账（「记着、仍漂移、
    却被删掉」）与 burn-down 的**生效配置**都只认它（否则本 PR 改自己的清单就本次生效
    = 自证式豁免）。**`--base` 上没有基线时退回当前那份**（首次落地 / 新仓 / 夹具仓库的形态）：
    此时不存在"相对 base 被删"这回事，要把 `stale` 判成「只报告」而不是**凭空判红**。
    """
    cur_entries_all = dict(baseline.get("entries") or {})
    base_entries_all = dict((base_baseline or {}).get("entries") or {}) or None
    for c in CHECKS:
        cur_entries_all.setdefault(c.id, {})
    out = {
        "schema": SCHEMA,
        "policy_version": POLICY_VERSION,
        "generated_at": a.now.isoformat(),
        "base": a.git("rev-parse", a.base).strip() or a.base,
        "cases_fingerprint": cases_fingerprint(a.repo),
        "repo": str(a.repo),
        "changed_files": sorted(changed) if changed is not None else None,
        "checks": [],
        "unimplemented": UNIMPLEMENTED,
        "summary": {},
    }
    new_total = new_out_total = 0
    known_total = paydown_total = stale_total = stale_block_total = 0
    dropped_total = unverifiable_total = 0
    for c in CHECKS:
        if only and c.id not in only:
            continue
        try:
            res = c.fn(a)
        except Exception as exc:  # noqa: BLE001 —— 判据崩溃必须红，不能静默当通过
            res = CheckResult(c.id, status="error",
                              error=f"{type(exc).__name__}: {exc}")
        if res.status != "error" and res.status != "unknown" \
                and res.evaluated < c.min_evaluated:
            # `always=True`（永不进基线、也不允许存量放行）：它是**护栏自身退化**的信号
            # （判定面为空 ⇒ 该判据恒真 ⇒ 空断言），不是"某条漂移"。记进基线 = 把
            # 「我的护栏曾经空跑」变成永久豁免 —— 而 #4045 的全量对账会把它读成
            # 「已不再漂移的陈旧条目」⇒ 凭空判红（夹具实测：
            # `ref-freshness|empty-surface` 在判定面恢复后消失 ⇒ 被判陈旧）。
            res.findings.append(Finding(
                f"{c.id}|empty-surface",
                f"判定面为 {res.evaluated}（下界 {c.min_evaluated}）—— 空集会让护栏恒真",
                True, always=True))
        env_res = [f for f in res.findings if f.env or f.always]
        # 两个参照物（**别混用**，混用会造出假红/永久豁免）：
        # · 计数参照 `base_entries`：`--base` 上有基线就以它为准（新漂移的 delta 由它算）；
        #   没有就退回当前那份（首次落地 / 夹具仓库：还没有"相对 base 的删改"）；
        # · 正向对账参照 `recorded`：**清单本身**（陈旧 = 清单里记了却不再漂移）；
        # · 反向对账参照：`--base` 那一份（缺省退回清单本身）。
        recorded = cur_entries_all.get(c.id, {})
        base_entries = base_entries_all.get(c.id, {}) if base_entries_all is not None \
            else dict(recorded)
        # 本次**没能重算**这条判据 ⇒ 它的旧条目不得读成「已不漂移」（没跑 ≠ 陈旧）：
        # · 判定面为空（`empty-surface`）：这条判据的输入没了，结论无从谈起；
        # · 需要网络而本次离线：`heartbeat` 的 gh 查询全返「未知」⇒ `never-succeeded`
        #   这类条目看起来归零，无条件判陈旧就是**凭空判红**。
        unverifiable = c.network and a.offline
        cmp_ = compare_baseline(res, base_entries, changed, recorded_entries=recorded,
                                base_check_entries=(base_entries_all or {}).get(c.id, {}),
                                unverifiable=unverifiable)
        if res.status == "error":
            status = "error"
        elif cmp_["new"] or cmp_["stale_blocking"] or cmp_["dropped"] or env_res:
            status = "new-drift"
        elif res.status == "unknown":
            status = "unknown"
        elif cmp_["known"] or cmp_["stale"]:
            status = "known-drift"
        else:
            status = "ok"
        res.status = status
        new_total += len(cmp_["new"]) + len(env_res)
        new_out_total += len(cmp_["new_out_of_scope"])
        known_total += len(cmp_["known"])
        paydown_total += len(cmp_["paydown"])
        stale_total += len(cmp_["stale"])
        stale_block_total += len(cmp_["stale_blocking"])
        dropped_total += len(cmp_["dropped"])
        unverifiable_total += len(cmp_["unverifiable_stale"])
        out["checks"].append({
            "id": c.id,
            "invariant": c.invariant,
            "title": c.title,
            "judgment": c.judgment,
            "remedy": c.remedy,
            "network": c.network,
            "status": status,
            "evaluated": res.evaluated,
            "error": res.error,
            "notes": res.notes,
            "new_drift": [{"key": k, "delta": n} for k, n in cmp_["new"]],
            "new_drift_out_of_scope": [{"key": k, "delta": n}
                                       for k, n in cmp_["new_out_of_scope"]],
            "known_drift": [{"key": k, "count": n} for k, n in cmp_["known"]],
            "paydown": [{"key": k, "delta": n} for k, n in cmp_["paydown"]],
            "stale_baseline_entry": [
                {"key": k, "count": n, "check": c.id,
                 "hint": next((s["hint"] for s in cmp_["reconcile"]["stale"]
                               if s["key"] == k), "")}
                for k, n in cmp_["stale"]],
            "stale_baseline_unverifiable": [
                {"key": k, "count": n, "check": c.id}
                for k, n in cmp_["unverifiable_stale"]],
            "stale_baseline_blocking": [k for k, _ in cmp_["stale_blocking"]],
            "dropped_baseline_entry": cmp_["dropped"],
            "env_findings": [{"key": f.key, "detail": f.detail} for f in env_res],
            "findings": [{"key": f.key, "detail": f.detail, "blocking": f.blocking,
                          "env": f.env, "always": f.always} for f in res.findings],
            "new_findings_detail": [
                next((f.detail for f in res.findings if f.key == k), k)
                for k, _ in cmp_["new"]],
        })
    # ── burn-down 预算（#4045）：判据本体在 `case_trust_gate.burn_down_verdict` ──────
    # `scope=case_touching_prs` 的「命中」= 本 PR 动了**判据面**（基线文件本身，或引入了新的
    # 存量条目）—— 与 case-trust 的 `case_touching_prs`（改用例文件）同一条设计：范围太大 =
    # 每个 PR 都红 = 假红，范围太小 = 预算形同虚设。**取值必须落在 gate 认识的那两个里**。
    baseline_touched = (changed is None or DEFAULT_BASELINE in changed
                        or _new_in_scope(out))
    budget = _load_gate_module().burn_down_verdict(
        _budget_baseline(base_entries_all or {}, (base_baseline or {}).get("burn_down")),
        _budget_baseline(cur_entries_all, baseline.get("burn_down")),
        a.now.strftime("%Y-%m-%d"), baseline_touched,
        label=DEFAULT_BASELINE, hint_extra=f"（本门禁的修法：`{REGEN_COMMAND}`）")
    if not isinstance((base_baseline or {}).get("burn_down"), dict):
        # **机制尚未在 `--base` 生效**（`main` 的清单里还没有 `burn_down` 块 = 本次是引入 PR）：
        # 「清单不得增长」这条判据此刻没有可比的基线 —— 拿"没有配置"当"清单为空"会把
        # **给后续 PR 立预算的那一次重生成**判成「新增豁免」，那是**假红**（后续每个 PR
        # 都会栽在同一处）。此时只保留陈旧/被删（全量对账）与到期清零，不判净增长。
        # ⚠️ 一旦预算在 `main` 生效，增长立刻照红（R4），**不是把预算关掉**。
        budget["reasons"] = [r for r in budget["reasons"] if "基线**增长**了" not in r]
        budget["blocking"] = bool(budget["reasons"])
        budget["notes"].append(
            "⏳ `--base` 的清单里还没有 `burn_down` 块 ⇒ 本次**不判净增长**"
            "（引入 PR 的合法形态：它正是给后续 PR 立预算的那一次重生成）；"
            "陈旧/被删（全量对账）与到期清零仍然生效，下一次重生成后增长照红。")
    if not str((budget.get("config") or {}).get("deadline") or "").strip("0-"):
        # **本门禁有意不设到期日**（理由见基线 `_burn_down_note`：65 条跨目录存量没有单一
        # owner 能在某个日期前清零）⇒ 未设 = 该条不生效。gate 的 `_date()` 是给 case-trust 的
        # fail-closed 兜底（那边**总是**有到期日），照抄会把它读成 `0000-00-00` = **已到期**
        # ⇒ 每个 PR 都红（实测踩到）。到期日一旦真的写进配置，这里立刻照常判红。
        budget["reasons"] = [r for r in budget["reasons"] if "到期清零" not in r]
        budget["blocking"] = bool(budget["reasons"])
    out["summary"] = {
        "new_drift": new_total,
        "new_drift_out_of_scope": new_out_total,
        "known_drift": known_total,
        "paydown": paydown_total,
        "stale_baseline_entry": stale_total,
        "stale_baseline_blocking": stale_block_total,
        "dropped_baseline_entry": dropped_total,
        "stale_baseline_unverifiable": unverifiable_total,
        "burn_down": budget,
        "verdict": ("drift" if (new_total or new_out_total) else
                    ("crash" if any(c["status"] == "error" for c in out["checks"]) else
                     ("unknown" if any(c["status"] == "unknown" for c in out["checks"]) else "ok"))),
    }
    return out


def _new_in_scope(rep: dict) -> bool:
    """本 PR 的改动面里有没有**新增漂移**（burn-down 的 `scope=surface_touching_prs` 用）。"""
    return any(c.get("new_drift") for c in rep.get("checks", []))


# ═══════════════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════════════
def cases_fingerprint(repo: Path) -> str:
    h = hashlib.sha256()
    d = repo / CASES_DIR
    if not d.is_dir():
        return "<无用例库>"
    for f in sorted(d.glob("*.yml")):
        h.update(f.name.encode())
        h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()[:16]

def render_summary(rep: dict, baseline: dict) -> str:
    L: list[str] = []
    s = rep["summary"]
    L.append("=" * 78)
    L.append("统一漂移审计（真相源契约）  base=%s  cases_fingerprint=%s  policy=v%s"
             % (rep["base"][:12], rep["cases_fingerprint"], rep["policy_version"]))
    L.append("=" * 78)
    for c in rep["checks"]:
        mark = {"ok": "✅", "known-drift": "🟡", "new-drift": "❌", "unknown": "❔",
                "error": "💥"}[c["status"]]
        L.append(f"{mark} [{c['id']}] {c['title']}  (invariant {c['invariant']}, "
                 f"判定面 {c['evaluated']})")
        for n in c["notes"]:
            L.append(f"     · {n}")
        if c["error"]:
            L.append(f"     💥 {c['error']}")
        for d in c["new_findings_detail"]:
            L.append(f"     ❌ 新增漂移（本 PR 改动面）：{d}")
        for k in c.get("new_drift_out_of_scope", []):
            detail = next((f["detail"] for f in c["findings"] if f["key"] == k["key"]), k["key"])
            L.append(f"     ⚠️ 新增漂移（**面外**，多半来自并行包刚合并的文件；"
                     f"本 PR 改动面内无新增 ⇒ 不阻塞，定时腿会红）：{detail}")
        for d in c.get("env_findings", []):
            L.append(f"     ❌ 硬漂移（永不进基线 / 不可放行）：{d['detail']}")
        for k in c["known_drift"]:
            L.append(f"     🟡 存量（基线放行）：{k['key']} ×{k['count']}")
        blocking_stale = set(c.get("stale_baseline_blocking") or [])
        for k in c["stale_baseline_entry"]:
            if k["key"] in blocking_stale:
                L.append(f"     ❌ 基线条目已归零但未删（**全量对账**，不再限于本次 diff 命中）："
                         f"{k['key']} ⇒ 豁免一条不存在的漂移 = 未来的假真值")
                if k.get("hint"):
                    L.append(f"        {k['hint']}")
            else:
                L.append(f"     🧹 基线条目已归零（无 PR 上下文：只报告不阻塞）：{k['key']}")
        for k in c.get("stale_baseline_unverifiable", []):
            L.append(f"     ⏭️ 判据本轮**未能重算**（网络不可达 / 判定面为空）⇒ 该条目"
                     f"**不判陈旧**（没跑 ≠ 已不漂移）：{k['key']}")
        for k in c.get("dropped_baseline_entry", []):
            L.append(f"     ❌ 基线条目被删但**现在仍然漂移**（= 偷偷缩短/新增豁免）：{k['key']}")
            if k.get("hint"):
                L.append(f"        {k['hint']}")
        for k in c["paydown"]:
            L.append(f"     🧹 可销账：{k['key']} −{k['delta']}（可 `--regen-baseline --reason ...`）")
    L.append("-" * 78)
    L.append("本次相对基线的增减：新增漂移 %d（面内，阻塞） / 面外新增 %d（不阻塞，定时腿红） / "
             "存量放行 %d / 可销账 %d / 基线归零未删 %d（**全量对账 ⇒ 阻塞 %d**） / "
             "条目被删但仍漂移 %d（阻塞）⇒ %s"
             % (s["new_drift"], s["new_drift_out_of_scope"], s["known_drift"], s["paydown"],
                s["stale_baseline_entry"], s["stale_baseline_blocking"],
                s.get("dropped_baseline_entry", 0), s["verdict"].upper()))
    bd = s.get("burn_down") or {}
    if bd.get("active"):
        net = bd.get("net") or {}
        L.append("burn-down 预算（生效配置读 `--base` 那一份，`scope=%s` = 本 PR 动了判据面时"
                 "要求净消减）：条目 %s / 违规码 %s；现剩 条目 %s / 违规码 %s ⇒ %s"
                 % (bd["config"]["scope"], net.get("entries"), net.get("codes"),
                    bd["remaining"]["entries"], bd["remaining"]["codes"],
                    "❌ 未达标" if bd["blocking"] else "达标"))
    for n in bd.get("notes", []):
        L.append(f"· {n}")
    for r in bd.get("reasons", []):
        L.append(f"❌ [burn-down] {r}")
    if rep["unimplemented"]:
        L.append("未实装（**不用恒真判断凑数**）：" + "、".join(u["id"] for u in rep["unimplemented"]))
    L.append("-" * 78)
    if s["new_drift"] or s["stale_baseline_entry"]:
        L.append("怎么改（按判据逐条）：")
        for c in rep["checks"]:
            if c["new_drift"] or c.get("stale_baseline_entry"):
                L.append(f"  · [{c['id']}] {c['remedy']}")
        L.append("  · 若确认这些是**应接受的存量**（不是新增回归）："
                 f"`python3 scripts/drift_audit.py --regen-baseline --reason '<你在 PR 里写的理由>'`，"
                 f"并把基线变更一起提交。")
    return "\n".join(L)


def load_base_baseline(a: Audit, rel: str = DEFAULT_BASELINE) -> dict | None:
    """读 `--base`（通常是 `origin/main`）上的基线清单（不存在/读不出 → None）。

    为什么需要它：全量对账要回答两个方向的问题 ——「记了却不再漂移」（陈旧）与
    **「原本记了、现在仍漂移、却被删掉」**（偷偷缩短）。后者只能拿**基线那一份**当参照物
    （本 PR 的清单正是被审对象）。burn-down 的**生效配置**同样只认它（自证式豁免的反面）。
    """
    text = a.read(rel, a.base)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def build_baseline(rep: dict, reason: str) -> dict:
    """按本次审计的实测读数重建基线（`--regen-baseline` 的机械修复）。"""
    entries = {}
    for c in rep["checks"]:
        ent: dict[str, int] = {}
        for f in c["findings"]:
            if f["env"] or f["always"]:
                continue  # 环境漂移永不进基线（见 Finding 文档）
            ent[f["key"]] = ent.get(f["key"], 0) + 1
        entries[c["id"]] = ent
    return {
        "_comment": "漂移审计的**存量**违规清单（burn-down）。计数是「该 SHA 上判出的存量漂移」，"
                    "**不是**『这些永远豁免』。",
        "regenerate_command": REGEN_COMMAND,
        "_when_to_regen": "① 你修好了某条存量漂移（门禁会告诉你：**全量对账**，不再限于你 diff 命中的文件）；"
                          "② 别人合并了漂移修复 ⇒ 重跑审计后重生成，把已修好的条目删掉；"
                          "③ 判据集合本身变化（新增/改名）⇒ 必须重生成。",
        "_scope_note": "「已不再漂移 ⇒ 必须移除」是**全量对账**（#4045）：清单里任何条目都必须在"
                       "**全库重算**里仍然真的漂移，**不再限于本次 diff 命中的文件**；反向同样成立 ——"
                       "`origin/main` 记着、现在仍漂移却被删掉的条目会**阻塞**（删条目 = 偷偷缩短）。"
                       "判据本体在 `.github/case_trust_gate.py` 的 `reconcile_baseline`（本脚本 import 复用，"
                       "不复制第二套口径）。",
        "_burn_down_note": "`burn_down` 块 = 每 PR 最低净消减（默认 ≥1 条）。"
                           "**不设 `deadline` / `priority_deadline`**（未设 = 该两条不生效）："
                           "本门禁的存量是 65 条**跨目录**条目（`docs/**` / `tests/**` / "
                           "`scripts/**` / `.github/workflows/**` …），没有单一 owner 能在某个日期前"
                           "清零；照抄 case-trust 的到期日只会造出一条**必然红且无人能修**的判据"
                           "（到期日一旦写进 `--base` 那一份，按『只许收紧』还改不回来）。"
                           "何时设：存量缩到可归属的范围、或用户明确给定日期时。"
                           "（实证：首个版本照抄了 `_date()` 的 fail-closed 默认值 ⇒ 未设的日期被"
                           "当成 `0000-00-00` = **已到期** ⇒ 每个 PR 都红。）"
                           ""
                           "（**生效配置读 `--base` 那一份**，本 PR 改不动本次判定）。"
                           "`scope=case_touching_prs` 沿用 `case_trust_gate` 的**同一套取值**"
                           "（那边=『本 PR 改了用例文件』，这边=『本 PR 动了**判据面**』：基线文件本身，"
                           "或引入新的存量条目）—— 判据本体是 `case_trust_gate.burn_down_verdict`，"
                           "**本脚本不复制、也不另造 scope 名**（实证：自造一个 gate 不认识的 scope "
                           "名会被静默判成「不在范围内」= 预算形同虚设）。"
                           "范围放大到「任何改了受管面的 PR」会让无关 PR 全红（假红）。",
        "_entry_key_note": "条目 key 为 `<文件或分量>|<判据内部标识>`，**不含行号** —— "
                           "否则改一行就换 key，『只许缩短』会退化成随机红。",
        "schema": BASELINE_SCHEMA,
        "policy_version": POLICY_VERSION,
        "generated_at": rep["generated_at"],
        "anchor_sha": rep["base"],
        "cases_fingerprint": rep["cases_fingerprint"],
        "reason": reason,
        # 默认预算：每 PR ≥1 条净缩（`--base` 那一份生效；本 PR 写进清单的这份是**给后续 PR** 的）
        "burn_down": {"per_pr_min": 1, "metric": "entries_or_codes",
                      # 取值必须落在 `case_trust_gate.burn_down_verdict` 认识的那两个里
                      # （`all_prs` / `case_touching_prs`）；语义见上面的 `_burn_down_note`。
                      "scope": "case_touching_prs"},
        "entries": entries,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="统一漂移审计（真相源契约）")
    ap.add_argument("--repo", default=".", help="仓库根（默认当前目录）")
    ap.add_argument("--base", default="origin/main", help="比较基准 revision（默认 origin/main）")
    ap.add_argument("--baseline", default=None, help=f"基线 JSON（默认 {DEFAULT_BASELINE}）")
    ap.add_argument("--check", action="store_true", help="门禁模式：新增漂移 ⇒ 非零退出")
    ap.add_argument("--stale-scope", choices=["diff", "none"], default="diff",
                    help="是否按 PR 上下文判阻塞（默认 diff）；`none` = 无 PR 上下文"
                         "（纯审计 / 定时树）⇒ 陈旧条目与面外新增都只报告不阻塞")
    ap.add_argument("--regen-baseline", action="store_true", help="重生成基线（必须带 --reason）")
    ap.add_argument("--reason", default="", help="重生成基线的理由（写进基线 JSON，PR 里要说明）")
    ap.add_argument("--json", dest="json_out", default=None, help="机器可读报告输出路径")
    ap.add_argument("--only", default=None, help="只跑这些判据（逗号分隔）")
    ap.add_argument("--offline", action="store_true", help="跳过网络判据（心跳记未知）")
    ap.add_argument("--fail-on-unknown", action="store_true", help="未知也当失败（定时任务用）")
    ap.add_argument("--strict-stale", action="store_true",
                    help="**定时审计腿**：面外新增漂移也阻塞（陈旧条目自 #4045 起一律阻塞，"
                         "与本开关无关）。PR 门禁**不要**开：面外新增多半来自并行包刚合并进 "
                         "main 的文件，硬阻塞 = 假红（#3846 / 实证 run 34914147884）。")
    ap.add_argument("--live-anchor", default=None, help="活锚目录（默认 ~/.dsh/.agent-presets/migao）")
    ap.add_argument("--gh-fixture", default=None, help="gh run list 的假数据（L0 夹具用）")
    ap.add_argument("--now", default=None, help="基准时刻 ISO8601（L0 夹具用）")
    ap.add_argument("--list-checks", action="store_true", help="打印判据集合（机器可读）")
    args = ap.parse_args(argv)

    if args.list_checks:
        print(json.dumps({
            "checks": [{"id": c.id, "invariant": c.invariant, "title": c.title,
                        "judgment": c.judgment, "remedy": c.remedy,
                        "network": c.network, "min_evaluated": c.min_evaluated}
                       for c in CHECKS],
            "unimplemented": UNIMPLEMENTED,
        }, ensure_ascii=False, indent=2))
        return 0

    repo = Path(args.repo).resolve()
    baseline_path = Path(args.baseline) if args.baseline else repo / DEFAULT_BASELINE
    baseline = load_baseline(baseline_path)
    now = _parse_ts(args.now) if args.now else None
    a = Audit(repo, base=args.base, offline=args.offline, now=now,
              live_anchor=Path(args.live_anchor) if args.live_anchor else None,
              gh_fixture=Path(args.gh_fixture) if args.gh_fixture else None)
    only = [x.strip() for x in args.only.split(",")] if args.only else None
    # `--stale-scope none` = 无 PR 上下文（纯审计 / 定时树）：陈旧条目与面外新增都只报告；
    # 默认 `diff` = 门禁口径：**全量对账**的陈旧/被删条目一律阻塞（#4045），
    # 新增漂移只对**本 PR 改动面** fail-closed（见 `_in_scope`）。
    changed = changed_files(a) if args.stale_scope == "diff" else None
    base_baseline = load_base_baseline(a)
    rep = run_audit(a, baseline, only, changed, base_baseline)

    if args.regen_baseline:
        if not args.reason.strip():
            print("❌ --regen-baseline 必须带 --reason（PR 里要说明为什么重生成基线）")
            return 2
        new_baseline = build_baseline(rep, args.reason)
        entries = new_baseline["entries"]
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(
            json.dumps(new_baseline, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        total = sum(len(v) for v in entries.values())
        print(f"✓ 基线已重生成：{baseline_path}（{total} 条，anchor={rep['base'][:12]}，"
              f"reason={args.reason!r}）")
        return 0

    print(render_summary(rep, baseline))
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"（机器可读报告 → {args.json_out}）")

    s = rep["summary"]
    if not args.check:
        return 0
    if s["new_drift"]:
        return 1
    # 全量对账（#4045）：陈旧条目 / 被删但仍漂移的条目 ⇒ 阻塞（不再需要 `--strict-stale`）
    if s["stale_baseline_blocking"] or s["dropped_baseline_entry"]:
        return 1
    if (s.get("burn_down") or {}).get("blocking"):
        return 1
    if args.strict_stale and (s["stale_baseline_entry"] or s["new_drift_out_of_scope"]):
        return 1
    if any(c["status"] == "error" for c in rep["checks"]):
        return 1
    if args.fail_on_unknown and any(c["status"] == "unknown" for c in rep["checks"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
