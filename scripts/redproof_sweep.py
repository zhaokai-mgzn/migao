#!/usr/bin/env python3
"""#5328 红证**实跑**巡检 —— 对登记在册的红证逐条做「注入 → 断言必红 → 还原」。

## 它治什么（**类**：红证退化 = 「不红也过」）

本仓**已有**红证机具（`scripts/*-red-proof.py`）与它们的**前提自检**（锚点可命中 / 期望判据方法
存在，`scripts/red_proof_harness.py` 的 `--check` 面，每个 PR 都跑）。但**「期望判据方法**存在**」
≠「注入之后它**会红**」** —— 三例实测退化（`#5268` 判据 4 / `#5286` 判据 4 / `#5272` 既有红证）
都是「注入生效了，判据却不动」，而**没有任何机器会因此变红**：全靠人手工跑了一次变异才发现。
本巡检把那一次「人手工跑」变成**每轮真跑**。

## 它到底做什么（逐条，不许退化成「只查存在性」）

对登记册（`scripts/redproof_registry.json`）里的每条红证，在**临时副本**上：

    ① 坐标自证：被守卫源码里注入锚点**恰好命中 1 次**（0 次 ⇒ 报「注入点失配」，不是跳过）
    ② 基线：先跑一次判据，**必须绿**（且必须**真的跑起来了** —— surefire 报告里要有该方法）
    ③ 注入：锚点 → 逐字替换（`mutated != src` 自证），并按内容指纹证明**注入真的落到了文件上**
    ④ 断言必红：再跑一次判据，**必须红**，且红的形态要符合登记册声明的「期望失败文本/断言片段」
       —— 注入生效而判据不动 ⇒ **该红证已退化**（直接点明，不靠人对比两次日志）
    ⑤ 还原：逐字节写回 + 指纹自证；再跑一次判据（对照组：红是注入造成的，不是本来就红）

**它不做前提自检**（那是 `red_proof_harness.py --check` 的活，零依赖、已在 PR 面跑）——
本巡检管的是它**结构上够不着**的那一层：真注入 + 真跑 + 真红。

## 安全与成本（`migao-dev-flow` §23 G8 / G10）

* **注入只在临时副本上做**：副本 = `git archive <repo> HEAD | tar -x`（**HEAD 的树**，脏改动不进
  巡检）⇒ 工作区里的真实文件**一次都不被写**；本巡检另在开工前/收工后对**工作区**的被守卫文件
  做内容指纹对照，**前后不一致 ⇒ 报错**（「不许留脏改动」是读数，不是承诺）。
* **一定还原**：注入后的还原在 `finally` 里做（异常 / 超时 / Ctrl-C 都走这条路），并按 sha256 自证。
* **超时上限**：单次判据运行 `--timeout`（默认 600s）+ 本轮总预算 `--budget`（默认 3600s，
  超出后剩余条目**显式记为「超出本轮预算」并跳过**）。
* **判据与负载无关**：报告的是「登记条数 / 真跑条数 / 跳过条数（逐条原因）/ 注入次数 / 还原次数 /
  退化条数」—— **不拿挂钟时长当判据**（墙钟只作为预算止损的输入，不参与任何判定）。

## 三态退出码（「看不了」不得当「没问题」）

`0` = 登记且可跑的条目**全部**真跑且**全部**真红、且全部还原干净；`1` = 有退化 / 注入点失配 /
未还原 / 基线不绿 / 红形态不符 / 超时（**具名报出是哪一条**）；`3` = **无法判定**（登记册缺失或
不可读 / 一条都没真跑 —— 零动作也要出声，且**不是通过**）。

## 与既有机制的边界（照实登记，`migao-dev-flow` §19.1）

| 机制 | 管什么 | 不管什么 |
|---|---|---|
| `red_proof_harness.py --check`（PR 面，每 PR） | 机具**声明的前提**能否成立（锚点命中 / 判据方法存在） | 注入之后**是否真会红** |
| `red_proof.py` | 取红证动作的**缓存卫生 + 注入自证**（本巡检 import 复用它的 `content_fingerprint`） | 谁在什么时候真跑 |
| `verify-all.sh redproof`（手动入口） | 各机具**自己的**实跑（机具自报「该条红、其余绿」） | 机具**自报**对不对（判定权在机具手里） |
| **本巡检**（定时腿，报告型） | 用**登记册的注入点 + 判据**独立复算一次「注入 ⇒ 必红」，判定权在巡检手里 | 机具的**全部**变异（登记册逐条只收一条代表；全量仍靠 `verify-all.sh redproof`） |
| `scripts/drift_audit.py` 的 `heartbeat` | 本巡检**自己是否还在跑**（新定时 workflow 合并后自动纳入心跳判定） | —— |
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REGISTRY_DEFAULT = REPO / "scripts" / "redproof_registry.json"

OK, BAD, UNKNOWN = 0, 1, 3
DEFAULT_TIMEOUT = 600          # 单次判据运行的超时上限（秒）
DEFAULT_BUDGET = 3600          # 本轮总预算（秒）—— 只用来止损，**不作判据**（§23 G8）

# append（不是 insert）：只作兜底解析路径，避免遮蔽同名模块。
sys.path.append(str(REPO / "scripts"))

from red_proof import content_fingerprint  # noqa: E402  #4260 复用既有指纹口径，不另写一套


class Undecidable(Exception):
    """**无法判定**（登记册缺失/不可读、副本建不起来）—— 退出码 3，不得当成通过。"""


#: **确定的**病态态（红证真的坏了 ⇒ 退出码 1）
DEFINITE_BAD = ("degenerate", "red_form_mismatch", "anchor_mismatch",
                "not_restored", "injection_ineffective")
#: **无法判定**的病态态（工具链事故 / 超时 / 基线本来就红 ⇒ 退出码 3：没跑 ≠ 通过，也不是「红证坏了」）
UNDECIDABLE_STATES = ("not_running", "timeout", "baseline_red", "guarded_missing")


# ── 一条红证的读数 ───────────────────────────────────────────────────────────

@dataclass
class Verdict:
    """一条红证的巡检读数（`state` 取 `red` / `skipped` / 其余 = 病态态）。"""

    id: str
    state: str
    detail: str = ""
    injection: str = ""            # 注入前后内容指纹（「注入已生效」的逐字证据）
    skipped_reason: str = ""
    injected: bool = False         # 真的把变异写进过副本（读数里的「注入次数」按它数）

    @property
    def bad(self) -> bool:
        return self.state not in ("red", "skipped")

    @property
    def ran(self) -> bool:
        return self.state != "skipped"


@dataclass
class Sweep:
    """本轮巡检的**与负载无关**的读数（禁止挂钟时长参与判定，§23 G8）。"""

    registered: int = 0
    unfixed: int = 0
    ran: int = 0
    skipped: int = 0
    injections: int = 0
    restores: int = 0
    degenerated: int = 0
    verdicts: list[Verdict] = field(default_factory=list)
    worktree_untouched: str = "未核对"

    def readings(self) -> str:
        why: dict[str, int] = {}
        for v in self.verdicts:
            if v.state == "skipped":
                why[v.skipped_reason] = why.get(v.skipped_reason, 0) + 1
        reasons = "；".join(f"{k} ×{n}" for k, n in sorted(why.items())) or "无"
        return (f"巡检读数：登记 {self.registered} 条 / 真跑 {self.ran} 条 / 跳过 {self.skipped} 条"
                f"（原因：{reasons}）/ 未固化 {self.unfixed} 条（见 registry.unfixed）/ "
                f"注入 {self.injections} 次 / 还原 {self.restores} 次 / 退化 {self.degenerated} 条 / "
                f"工作区被守卫文件：{self.worktree_untouched}")


# ── 登记册 ──────────────────────────────────────────────────────────────────

def load_registry(path: Path) -> dict:
    if not path.is_file():
        raise Undecidable(f"登记册不存在或不可读：{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Undecidable(f"登记册解析失败（{exc.__class__.__name__}）：{path}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise Undecidable(f"登记册结构不对（缺 entries）：{path}")
    return data


def is_red_proof_tool(rel: str) -> bool:
    """该路径是不是**红证机具**（`scripts/*-red-proof*.py`）—— 与 `verify-all.sh` 的 `redproof_preflight` 同口径。

    登记册里有两种载体：① **机具**（`scripts/*-red-proof.py`，必须逐个人在册）；② **判据守卫**
    （`tests/unit_ci_workflows/*.py`，红证长在守卫自己身上）。只有 ① 进「未登记即红」那条判据。
    """
    return rel.startswith("scripts/") and "-red-proof" in Path(rel).name


def registry_problems(data: dict, tools: list[str], repo: Path = REPO) -> list[str]:
    """登记册的**结构**判据（纯函数 ⇒ 可对构造的缺陷载荷验证判别力，见 `test_redproof_live_sweep.py`）。

    ① 每个红证机具必须在册（`entries` 或 `unfixed` 二选一）——「号称有红证」而未登记 = 不许存在；
    ② 每条登记项的注入点必须**逐字可证**（`guarded` / `anchor` / `replacement` / `criteria` / `red_text`）；
    ③ 每条未固化项必须写清「原因 + 谁看」（**不许留白**）。
    """
    problems: list[str] = []
    seen_tools: set[str] = set()
    for e in data.get("entries", []):
        eid = e.get("id", "<无 id>")
        tool = e.get("tool", "")
        if is_red_proof_tool(tool):
            seen_tools.add(tool)
        if not (repo / tool).is_file():
            problems.append(f"[{eid}] 机具不存在：{tool}")
        if not str(e.get("criterion", "")).strip():
            problems.append(f"[{eid}] 缺 `criterion`（这条红证守的是哪条判据）")
        guarded = repo / str(e.get("guarded", ""))
        if not guarded.is_file():
            problems.append(f"[{eid}] 被守卫源码不存在：{e.get('guarded')}")
        anchor = e.get("anchor", "")
        if not anchor:
            problems.append(f"[{eid}] 缺 `anchor`（注入点必须逐字给出，不许只写文件）")
        elif guarded.is_file() and guarded.read_text(encoding="utf-8").count(anchor) != 1:
            problems.append(f"[{eid}] 注入锚点在 {e.get('guarded')} 里不命中**恰好 1 次**")
        if not e.get("replacement", ""):
            problems.append(f"[{eid}] 缺 `replacement`（注入点 = 精确替换，左值与右值都要有）")
        crit = e.get("criteria") or {}
        if not crit.get("cmd"):
            problems.append(f"[{eid}] 缺 `criteria.cmd`（要跑哪条判据）")
        if not str(crit.get("red_text", "")).strip():
            problems.append(f"[{eid}] 缺 `criteria.red_text`（**期望失败文本/断言片段** —— "
                            f"只写「期望存在」是弱前提，写不出红形态 = 判不动退化）")
        else:
            try:
                re.compile(crit["red_text"])
            except re.error as exc:
                problems.append(f"[{eid}] `criteria.red_text` 不是合法的正则：{exc}")
    for u in data.get("unfixed", []):
        uid = u.get("tool", u.get("id", "<无 id>"))
        if is_red_proof_tool(str(u.get("tool", ""))):
            seen_tools.add(u["tool"])
        if not str(u.get("reason", "")).strip():
            problems.append(f"[未固化 {uid}] 缺 `reason`（为什么结构上跑不了实跑）")
        if not str(u.get("owner", "")).strip():
            problems.append(f"[未固化 {uid}] 缺 `owner`（**谁看**）")
    for t in tools:
        if t not in seen_tools:
            problems.append(f"机具 {t} **未登记**（既不在 entries 也不在 unfixed）—— "
                            f"「号称有红证」而未登记的红证机具不许存在")
    return problems


# ── 临时副本（注入只在这里发生）──────────────────────────────────────────────

def materialize(repo: Path, dest: Path, timeout: int) -> str:
    """把 `repo` 的 **HEAD 树**展开成临时副本 —— **脏改动不进巡检**（巡检对象与 CI 一致）。"""
    arc = subprocess.run(["git", "-C", str(repo), "archive", "HEAD"],
                         capture_output=True, timeout=timeout)
    if arc.returncode != 0:
        raise Undecidable("副本建不起来（git archive HEAD 失败）："
                          + arc.stderr.decode("utf-8", "replace")[-400:])
    dest.mkdir(parents=True, exist_ok=True)
    tar = subprocess.run(["tar", "-x", "-C", str(dest)], input=arc.stdout,
                         capture_output=True, timeout=timeout)
    if tar.returncode != 0:
        raise Undecidable("副本解包失败：" + tar.stderr.decode("utf-8", "replace")[-400:])
    return f"git archive {repo} HEAD → {dest}"


def link_deps(repo: Path, copy: Path, rels: list[str]) -> list[str]:
    """把副本里缺的依赖目录**软链**到真实检出（依赖只读；缺它该条会**具名跳过**而不是假装跑过）。"""
    linked: list[str] = []
    for rel in rels:
        src, dst = repo / rel, copy / rel
        if src.exists() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(src.resolve(), dst, target_is_directory=src.is_dir())
            linked.append(rel)
    return linked


def missing_requirement(repo: Path, req: str) -> str | None:
    """`cmd:x` / `file:x` / `dir:x` 三种要求；缺了就**具名跳过**（不是通过）。"""
    kind, _, value = req.partition(":")
    if kind == "cmd":
        return None if shutil.which(value) else f"缺命令 {value}"
    if kind == "file":
        return None if (repo / value).is_file() else f"缺文件 {value}"
    if kind == "dir":
        return None if (repo / value).is_dir() else f"缺目录 {value}"
    return f"未知要求 {req!r}"


# ── 跑判据 + 取「真的跑起来了」的证据 ────────────────────────────────────────

@dataclass
class Run:
    rc: int
    out: str
    timed_out: bool = False


def run_criteria(copy: Path, entry: dict, timeout: int) -> Run:
    crit = entry["criteria"]
    cwd = copy / crit.get("cwd", ".")
    try:
        p = subprocess.run(list(crit["cmd"]), cwd=str(cwd), capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout if isinstance(exc.stdout, str) else ""
        return Run(-1, partial, timed_out=True)
    except OSError as exc:
        return Run(-1, f"判据起不来：{exc!r}")
    return Run(p.returncode, (p.stdout or "") + (p.stderr or ""))


def surefire_case(copy: Path, crit: dict) -> tuple[dict | None, str]:
    """目标方法在 surefire 报告里的那条 `testcase`；`None` = **没跑起来**（#5242 的证据闸）。"""
    fqn, method = crit.get("fqn", ""), crit.get("method", "")
    rel = Path(crit.get("cwd", ".")) / "target" / "surefire-reports"
    reports = sorted((copy / rel).glob(f"TEST-{fqn}*.xml")) if (copy / rel).is_dir() else []
    if not reports:
        return None, f"没有 surefire 报告（{rel.as_posix()}/TEST-{fqn}*.xml）⇒ 测试**没跑起来**"
    seen: list[str] = []
    for xml in reports:
        try:
            root = ET.parse(xml).getroot()
        except ET.ParseError as exc:
            return None, f"surefire 报告解析失败（{xml.name}）：{exc}"
        for case in root.iter("testcase"):
            seen.append(case.get("name") or "")
            if (case.get("name") or "") != method:
                continue
            bad = [c for c in case if c.tag in ("failure", "error")]
            return {"failed": bool(bad),
                    "text": "\n".join(f"{c.get('type') or ''} {c.get('message') or ''}\n"
                                      f"{c.text or ''}" for c in bad)}, ""
    return None, (f"surefire 报告（{[r.name for r in reports]}）里没有判据方法 {method} "
                  f"⇒ 测试**没跑起来**（报告里出现过的方法：{sorted(set(seen))[:8]}）")


_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    """剥掉 ANSI 转义序列再匹配红形态。

    **为什么必须有**（2026-09-24 巡检首发日实测）：`npx vitest` 的输出**带颜色** ⇒
    转义码把 `Tests\s+\d+ failed \(\d+\)` 这类**精确**期望形态打散 ⇒ 判据**其实红了**
    却被判成 `red_form_mismatch`（"红证不成立"的误报）。归因方向必须准（§23 G3）：
    病根在**读法**（颜色码），不在判据。
    """
    return _ANSI_ESCAPE.sub("", text)


def red_evidence(entry: dict, copy: Path, run: Run) -> tuple[str, str]:
    """注入后那一次运行的红形态判定 ⇒ `(state, detail)`。

    **归因必须准**（§23 G3）：`degenerate`（注入生效而判据**根本没红**）与
    `red_form_mismatch`（判据红了但红形态与登记册的期望不符）是**两件事**，
    与 `not_running`（测试压根没跑起来，如编译失败 / 收集失败）也是两件事 ——
    三者混成一个「退化」会把排查方向带偏（本仓已踩过的错误归因形态）。
    """
    crit = entry["criteria"]
    if run.timed_out:
        return "timeout", "判据运行超时（已按超时上限掐断）"
    frag = str(crit.get("red_text", ""))
    if crit.get("kind", "surefire") == "surefire":
        case, why = surefire_case(copy, crit)
        if case is None:
            return "not_running", f"测试没跑起来：{why}"
        if not case["failed"]:
            return "degenerate", f"判据方法 {crit.get('method')} 在报告里**没有失败**（rc={run.rc}）"
        if frag and not re.search(frag, strip_ansi(case["text"] + run.out)):
            return "red_form_mismatch", (f"判据方法 {crit.get('method')} 已红，但失败文本与登记册的"
                                         f"期望不符（期望 /{frag}/；实测：{_snippet(case['text'])}）")
        return "red", (f"surefire：{crit.get('method')} 失败"
                       f"（逐字形态：{_snippet(case['text'])}）；期望 /{frag}/ 命中")
    if run.rc == 0:
        return "degenerate", "退出码 0（判据没有红）"
    if frag and not re.search(frag, strip_ansi(run.out)):
        return "red_form_mismatch", (f"判据已红（rc={run.rc}），但输出里没有登记册声明的红形态"
                                     f"（期望 /{frag}/；实测：{_snippet(run.out)}）")
    return "red", f"rc={run.rc} 且输出命中期望形态 /{frag}/"


def green_evidence(entry: dict, copy: Path, run: Run) -> tuple[bool, str]:
    """基线 / 还原后那一次必须**真的绿**，且必须**真的跑起来了**（否则红证无从谈起）。"""
    crit = entry["criteria"]
    if run.timed_out:
        return False, "判据运行超时"
    if run.rc != 0:
        return False, f"rc={run.rc}（应全绿；编译失败 / 基线本来就是红的都走这里）"
    if crit.get("kind", "surefire") == "surefire":
        case, why = surefire_case(copy, crit)
        if case is None:
            return False, f"测试没跑起来：{why}"
        if case["failed"]:
            return False, f"判据方法 {crit.get('method')} 本来就是红的（基线不绿）"
    return True, "绿"


# ── 单条红证的巡检（注入 → 断言必红 → 还原）─────────────────────────────────

def sweep_entry(entry: dict, copy: Path, timeout: int) -> Verdict:
    eid = entry.get("id", "<无 id>")
    guarded_rel = entry["guarded"]
    path = copy / guarded_rel
    if not path.is_file():
        return Verdict(eid, "guarded_missing", f"副本里没有被守卫文件 {guarded_rel}")
    original = path.read_text(encoding="utf-8")
    anchor, replacement = entry["anchor"], entry["replacement"]
    hits = original.count(anchor)
    if hits != 1:
        return Verdict(eid, "anchor_mismatch",
                       f"注入点失配：锚点在 {guarded_rel} 里命中 {hits} 次（须恰好 1 次）—— "
                       f"这条红证**取不出红证**，须重取锚点")
    mutated = original.replace(anchor, replacement, 1)
    if mutated == original:
        return Verdict(eid, "anchor_mismatch", "注入没有改变源码（左值与右值逐字相同）")
    base_fp = content_fingerprint(path)

    base = run_criteria(copy, entry, timeout)
    ok, why = green_evidence(entry, copy, base)
    if not ok:
        return Verdict(eid, "baseline_red", f"基线不绿 ⇒ 无法取红证：{why}")

    restore_ok = True
    verdict: Verdict | None = None
    try:
        path.write_text(mutated, encoding="utf-8")
        inj_fp = content_fingerprint(path)
        if inj_fp == base_fp:
            return Verdict(eid, "injection_ineffective",
                           "注入未生效：内容指纹前后一致（**这不是「判据不会红」**，是注入没落到文件上）")
        state, detail = red_evidence(entry, copy, run_criteria(copy, entry, timeout))
        verdict = Verdict(eid, state, detail, injection=f"{base_fp[:14]} → {inj_fp[:14]}",
                          injected=True)
    finally:
        # 任何路径（含异常 / 超时）都还原，并按内容指纹自证
        path.write_text(original, encoding="utf-8")
        restore_ok = content_fingerprint(path) == base_fp
        if not restore_ok:
            print(f"❌ [{eid}] 还原失败：{guarded_rel} 与注入前不一致 —— **停手人工核对**",
                  file=sys.stderr)
    if not restore_ok:
        return Verdict(eid, "not_restored", f"注入后未还原回基线（{guarded_rel}）")
    # 对照组：还原后必须**回到绿** ⇒ 上面那条红是**注入造成的**，不是本来就红、也不是残留
    control = run_criteria(copy, entry, timeout)
    ok, why = green_evidence(entry, copy, control)
    if not ok:
        return Verdict(eid, "not_restored", f"还原后复跑没回到绿 ⇒ 红证不可信：{why}")
    assert verdict is not None
    return verdict


def sweep(repo: Path, data: dict, only: list[str], timeout: int, budget: int,
          keep_copy: bool, copy_dir: Path | None) -> Sweep:
    sw = Sweep(registered=len(data["entries"]), unfixed=len(data.get("unfixed", [])))
    entries = [e for e in data["entries"] if not only or e.get("id") in only]
    if only:
        unknown = sorted(set(only) - {e.get("id") for e in data["entries"]})
        if unknown:
            raise Undecidable(f"--entry 指定的 id 不在登记册里：{unknown}")

    # 「不许碰工作区里的真实文件」：开工前记下工作区被守卫文件的指纹，收工后对照（读数，不是承诺）
    worktree: dict[str, str] = {}
    for e in entries:
        p = repo / e["guarded"]
        if p.is_file() and str(p) not in worktree:
            worktree[str(p)] = content_fingerprint(p)

    deps = sorted({d for e in entries for d in e.get("link_deps", [])})
    tmp = copy_dir or Path(tempfile.mkdtemp(prefix="redproof-sweep-"))
    made_copy = copy_dir is None
    try:
        print(f"[redproof_sweep] 临时副本：{materialize(repo, tmp, timeout)}")
        linked = link_deps(repo, tmp, deps)
        if linked:
            print(f"[redproof_sweep] 依赖软链到副本（只读）：{'、'.join(linked)}")

        started = time.monotonic()
        for e in entries:
            eid = e.get("id", "<无 id>")
            missing = [m for m in (missing_requirement(tmp, r) for r in e.get("requires", [])) if m]
            if missing:
                sw.skipped += 1
                v = Verdict(eid, "skipped", skipped_reason="；".join(missing))
                sw.verdicts.append(v)
                print(_entry_line(v))
                continue
            if time.monotonic() - started > budget:
                sw.skipped += 1
                v = Verdict(eid, "skipped",
                            skipped_reason=f"超出本轮预算 {budget}s（止损，非判据）")
                sw.verdicts.append(v)
                print(_entry_line(v))
                continue
            verdict = sweep_entry(e, tmp, timeout)
            sw.ran += 1
            # 注入次数 = 真的把变异写进副本的那几条（锚点失配 / 基线不绿的那几条没注入过）
            if verdict.injected:
                sw.injections += 1
                sw.restores += 1          # 还原在 `sweep_entry` 的 finally 里，指纹自证
            if verdict.state == "degenerate":
                sw.degenerated += 1
            sw.verdicts.append(verdict)
            print(_entry_line(verdict))
    finally:
        if keep_copy or copy_dir is not None:
            print(f"[redproof_sweep] 保留副本：{tmp}（--keep-copy / --copy-dir）")
        elif made_copy:
            shutil.rmtree(tmp, ignore_errors=True)

    intact = sum(1 for p, fp in worktree.items()
                 if Path(p).is_file() and content_fingerprint(Path(p)) == fp)
    sw.worktree_untouched = f"{intact}/{len(worktree)} 个 sha256 前后一致"
    return sw


def _snippet(text: str, limit: int = 160) -> str:
    """一条失败文本的**逐字**片段（报告里贴它，而不是只写「跑了就红了」）。"""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


def _entry_line(v: Verdict) -> str:
    if v.state == "skipped":
        return f"⏭️ [{v.id}] 跳过（{v.skipped_reason}）—— 跳过 ≠ 通过"
    if v.state == "red":
        return f"✅ [{v.id}] 注入生效（{v.injection}）+ 判据变红：{v.detail}"
    if v.state == "degenerate":
        return (f"❌ [{v.id}] **该红证已退化**（注入已生效，见 fingerprint 差异 {v.injection}；"
                f"但判据没有变红）—— {v.detail}")
    if v.state == "red_form_mismatch":
        return (f"❌ [{v.id}] 判据已红，但红形态与登记册**期望不符**（注入已生效 {v.injection}）"
                f"—— {v.detail}")
    if v.state in UNDECIDABLE_STATES:
        return f"❓ [{v.id}] 无法判定（没跑 ≠ 通过）：{v.detail}"
    return f"❌ [{v.id}] {v.state}：{v.detail}"


# ── CLI ─────────────────────────────────────────────────────────────────────

def _default_tools(repo: Path = REPO) -> list[str]:
    """红证机具的**现取**清单（仓库相对路径 —— 与登记册同一套口径，「别记数字」§19.2 ③）。"""
    return sorted(p.relative_to(repo).as_posix() for p in (repo / "scripts").glob("*-red-proof*.py"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="redproof_sweep.py",
                                description="红证实跑巡检：注入 → 断言必红 → 还原（#5328）")
    p.add_argument("--registry", default=str(REGISTRY_DEFAULT))
    p.add_argument("--repo", default=str(REPO), help="副本的来源仓库（巡检对象 = 它的 HEAD 树）")
    p.add_argument("--entry", action="append", default=[], help="只巡检指定 id（可重复）")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="单次判据运行超时（秒）")
    p.add_argument("--budget", type=int, default=DEFAULT_BUDGET, help="本轮总预算（秒，仅止损）")
    p.add_argument("--copy-dir", default=None, help="把副本建在这里（不自动删）")
    p.add_argument("--keep-copy", action="store_true", help="保留临时副本（排障用）")
    p.add_argument("--list", action="store_true", help="只列登记册（零动作，不跑任何判据）")
    p.add_argument("--json", default=None, help="把机器可读报告写到该路径")
    args = p.parse_args(argv)
    repo = Path(args.repo).resolve()

    try:
        data = load_registry(Path(args.registry))
    except Undecidable as exc:
        print(f"⚠️ 无法判定：{exc}", file=sys.stderr)
        return UNKNOWN

    problems = registry_problems(data, _default_tools(repo), repo)
    if args.list:
        for e in data["entries"]:
            print(f"  · [{e['id']}] {e['criterion']} ← {e['tool']}（{e.get('mutation', '?')}）")
        for u in data.get("unfixed", []):
            print(f"  ⏳ [未固化] {u.get('id') or u.get('tool')}｜{u.get('what', '')}｜"
                  f"原因：{u['reason']}｜谁看：{u['owner']}")
        print(f"登记 {len(data['entries'])} 条 / 未固化 {len(data.get('unfixed', []))} 条；"
              f"登记册结构判据：{'✅ 无问题' if not problems else '❌ ' + repr(problems)}")
        return OK if not problems else BAD
    if problems:
        print("❌ 登记册结构判据未过（未登记的红证机具 / 注入点写不逐字 / 未固化项留白）：",
              file=sys.stderr)
        for pr in problems:
            print(f"  · {pr}", file=sys.stderr)
        return BAD

    try:
        sw = sweep(repo, data, args.entry, args.timeout, args.budget,
                   args.keep_copy, Path(args.copy_dir) if args.copy_dir else None)
    except Undecidable as exc:
        print(f"⚠️ 无法判定：{exc}", file=sys.stderr)
        return UNKNOWN

    print("")
    print(sw.readings())
    if sw.ran == 0:
        print("⚠️ 本轮**零动作**：一条红证都没真跑（原因见上面的跳过读数）—— "
              "「一条都没跑」不是「通过」（`migao-acceptance`：绿 ≠ 跑过）", file=sys.stderr)
    bad = [v for v in sw.verdicts if v.bad]
    definite = [v for v in bad if v.state in DEFINITE_BAD]
    undecidable = [v for v in bad if v.state in UNDECIDABLE_STATES]
    if bad:
        print(f"\n❌ 有 {len(bad)} 条红证不成立（退化 / 失配 / 未还原 / 基线不绿）："
              f"{[v.id for v in bad]}", file=sys.stderr)
    if args.json:
        Path(args.json).write_text(json.dumps({
            "issue": 5328, "readings": sw.readings(),
            "summary": {"registered": sw.registered, "ran": sw.ran, "skipped": sw.skipped,
                        "unfixed": sw.unfixed, "injections": sw.injections,
                        "restores": sw.restores, "degenerated": sw.degenerated,
                        "undecidable": len(undecidable),
                        "worktree_untouched": sw.worktree_untouched},
            "entries": [{"id": v.id, "state": v.state, "detail": v.detail,
                         "injection": v.injection, "skipped_reason": v.skipped_reason}
                        for v in sw.verdicts],
            "unfixed": data.get("unfixed", []),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if definite:
        return BAD
    if undecidable or sw.ran == 0:
        print(f"⚠️ {len(undecidable)} 条**无法判定**（没跑 ≠ 通过）—— 「看不了」不得当「没问题」",
              file=sys.stderr)
        return UNKNOWN
    print(f"\n✅ 登记且可跑的 {sw.ran} 条红证全部**真跑**且**真红**（注入 {sw.injections} 次 / "
          f"还原 {sw.restores} 次）")
    return OK


if __name__ == "__main__":
    sys.exit(main())