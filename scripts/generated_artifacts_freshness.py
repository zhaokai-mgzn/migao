#!/usr/bin/env python3
"""生成物新鲜度的**判定本体**（单一实现；issue #5687 族的 main 侧守护）。

## 这个文件解决什么（病灶：同一个判定只有 `pull_request` 一个面在跑）

`生成物新鲜度（render + diff）` 原先只由 `pr-check.yml` 的
`Verify generated artifacts fresh (render + diff)` 步承担，而那个 job
（`Case Contract (truths_ref)`）**只在 `pull_request` 触发** ⇒

- **main 可以先漂移**（改了 `.github/cases/**` 却没提交生成物）；
- 而**第一个撞上它的无辜 PR 会红**，红的信息还指向**那个 PR 自己的 diff**
  （归因指向错误的对象 —— 实测：同一形态当天咬了两次，其中一次把归因写进了公开记录）。

本文件把那套判定收敛成**一份实现**，由两侧各自调用（谁都不许再内联第二份 render+diff）：

- `pull_request` 面：`.github/workflows/pr-check.yml`（判定语义逐字不变）；
- **main 侧**：`.github/workflows/main-freshness-guard.yml`（`push` + `schedule` + `workflow_dispatch`）。

## 判定对象（登记表 = `ARTIFACTS`；新增产物只需在这里加一行，两侧自动同源）

| 生成物 | 唯一源 |
|---|---|
| `tests/agent_eval/eval_cases/` | `.github/cases/**` |
| `docs/testing/mibao-verification-cases.md` | `.github/cases/**` |

## 出库形态（issue #8167 P1-1）：产物**不入库**，判定换成三条仍会红的

入库时代的判定 = 「提交版 vs 现取」（忘了提交 ⇒ rc 1）。出库后**没有提交版**，那条判定
失去对象 ⇒ 本文件换成三条**仍会红**的判定（口径只在这里实现一次，别处不许再写第二份）：

1. **不许塞回 git**（`git ls-files` / `git ls-tree HEAD` 命中即违规，逐文件具名）——
   有人 `git add -f` 把产物塞回来 ⇒ rc 1；
2. **可复现**：同一棵树连渲染两次**逐字节**相同（非确定性是最难查的失效形态，
   而它现在**就是**主判据；渲染失败 / 语料为空 ⇒ rc 3）；
3. **落盘副本必须是最新的**：本地已生成过一份、而源又改过 ⇒ rc 1（陈旧/手改都要重生成）。

🔴 **「产物不存在」不构成通过、也不是免检**：缺副本时判定落在第 2 条（渲染器真跑起来、
结果确定、非空），**不是** `return 0`。三态退出码语义不变 —— 唯一的变化是判定对象，
**没有任何一格被删掉**（判据 `tests/unit_ci_workflows/test_generated_artifacts_untracked.py`）。
`.gitignore` 必须覆盖这两条路径（缺一条 ⇒ 第 1 条防线被绕过 ⇒ 判红）。

渲染口径**不在这里重写**：一律调 `.github/render_cases.py`（渲染器本身就是单一源，
包括它自己的严格 YAML fail-closed，见 `.github/cases_yaml.py`）。

## 判红时说的是什么（这一节是本文件存在的一半理由）

判红输出必须**具名**，不许出现「生成物不同步」这类不具名的话：

1. **哪个产物**（仓库相对全路径）；
2. **差多少**（提交版 vs 现取的行数 + 不同行数 + 首个差异的行号与两侧原文）；
3. **复算命令原文**（可复制）；
4. **重渲染并提交的命令原文**（可复制）；
5. **漂移候选区间**（最近 N 个改了 `.github/cases/**` 的提交）—— 🔴 **只给读数，不下断言**：
   那个区间只是「可能性」，把它读成「凶手」正是本文件要治的归因错误。

## 出口（三态；**没有「跳过」这一态**）

| 码 | 含义 |
|---|---|
| `0` | 全部产物与源同步 |
| `1` | 有产物陈旧（具名报出） |
| `3` | **无法判定**（渲染器 / 语料 / 产物缺失、渲染失败、语料为空）—— fail-closed |

⚠️ `3` **不得当 `0` 读**：取不到依赖 / 渲染器跑不起来时**绝不允许**打印「跳过」然后成功
（那正是「没跑长得像通过」）。调用方（两个 workflow）一律把非零码带出去 = 判红。

## 复算

    python3 scripts/generated_artifacts_freshness.py          # 0/1/3
    python3 scripts/generated_artifacts_freshness.py --json /tmp/freshness.json
"""
from __future__ import annotations

import argparse
import difflib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

#: 仓根（本文件在 `<repo>/scripts/` 下）。`--repo` 可覆盖（夹具用）。
DEFAULT_REPO = Path(__file__).resolve().parents[1]

#: 用例库（唯一源）与渲染器的仓库相对路径。
CASES_REL = ".github/cases"
RENDERER_REL = ".github/render_cases.py"

#: 漂移候选区间的默认窗口（个提交）。
DEFAULT_WINDOW = 20

#: 三态退出码（语义见模块 docstring）。
RC_FRESH, RC_DRIFT, RC_UNDECIDABLE = 0, 1, 3

#: 判红/无法判定时打进日志的 GitHub 注解前缀（**单行**；多行注解会被截断）。
ERROR_PREFIX = "::error::"

#: 「一步归因」命令原文（`--base-probe`）：判红时**先问 base 是不是也陈旧**，再决定是不是本 PR 的事。
#: 本仓具名实例（2026-10-02，issue #6027）：main 侧漂移 11 分钟 ⇒ 窗口内两个**没碰过用例库**的 PR
#: 各自红一次，信息指向它们自己的 diff（归因指向错误的对象）。
BASE_PROBE_COMMAND = "python3 scripts/generated_artifacts_freshness.py --base-probe origin/main"


@dataclass(frozen=True)
class Artifact:
    """一个生成物 + 它对应的 `render_cases.py` 输出开关。

    `kind` 区分两种形态（issue #8188）：
      · `"file"` —— 单个文件，逐字节比对；
      · `"dir"`  —— **目录型生成物**（渲染器写一**目录**，如按域分包的 `eval_cases/`），
        逐模块逐字节比对；提交版里**多出来的模块文件**（手塞）与**缺的模块**都判红。
    """

    rel: str
    out_flag: str
    kind: str = "file"


ARTIFACTS: tuple[Artifact, ...] = (
    # issue #8188：`eval_cases` 从单文件（18000+ 行）拆成**按域分包的目录** ⇒ 目录型产物。
    Artifact("tests/agent_eval/eval_cases", "--out-eval", "dir"),
    Artifact("docs/testing/mibao-verification-cases.md", "--out-md"),
)


def recompute_command() -> str:
    """**可复制**的复算命令（人读；与两个 workflow 实际跑的是同一份实现）。"""
    return "python3 scripts/generated_artifacts_freshness.py"


def rerender_command() -> str:
    """**可复制**的重渲染并提交命令（口径与 `scripts/drift_audit.py` 的 remedy 一致）。"""
    pairs = " ".join(f"{a.out_flag} {a.rel}" for a in ARTIFACTS)
    return f"python3 {RENDERER_REL} --cases {CASES_REL} {pairs}"


def generate_command() -> str:
    """**可复制**的生成命令（出库后产物的唯一来源；幂等，CI / 本地 / pytest 起动都调它）。"""
    return "python3 scripts/generated_artifacts_freshness.py --write"


# ── 出库形态（issue #8167 P1-1）：生成腿 + 三条判定 ─────────────────────────────────────────

#: `.gitignore` 里每个出库产物**必须**有的条目（缺一条 ⇒ 判据 1 的防线被绕过）。
IGNORE_PATTERNS: dict[str, str] = {
    "tests/agent_eval/eval_cases": "/tests/agent_eval/eval_cases/",
    "docs/testing/mibao-verification-cases.md": "/docs/testing/mibao-verification-cases.md",
}

#: `.gitignore` 文件（相对于仓根）。
GITIGNORE_REL = ".gitignore"


class GenerationError(RuntimeError):
    """生成腿失败。调用方**不许**把它降级成 skip/return 0（那正是「没跑长得像通过」）。"""


def _out_paths(repo: Path) -> dict[str, Path]:
    """每个产物在**仓库里**的正式落点（目录型产物按其路径建目录）。"""
    return {a.rel: repo / a.rel for a in ARTIFACTS}


def ensure_generated(repo: Path, *, python: str | None = None, cases_rel: str = CASES_REL,
                     renderer_rel: str = RENDERER_REL, render_timeout: int = 300) -> str:
    """把出库产物**就地生成**到仓库里的正式路径（幂等；issue #8167 P1-1）。

    失败一律抛 `GenerationError` —— **没有**「跳过」出口：产物不在 git 里，生成腿就是
    它们唯一的来源，生成失败 ⇒ 消费者（pytest / local_runner / 判据）必须当场红，而不是
    拿着一份不存在的文件继续跑。
    """
    renderer = repo / renderer_rel
    cases_dir = repo / cases_rel
    if not renderer.is_file():
        raise GenerationError(f"渲染器缺失：{renderer_rel}（生成腿无法执行 —— 这不是「产物可选」）")
    if not cases_dir.is_dir():
        raise GenerationError(f"用例库缺失：{cases_rel}/")
    outs = _out_paths(repo)
    for art in ARTIFACTS:
        # 目录型产物建目录；单文件产物建**父目录**（干净检出里 docs/testing/ 可能根本不存在
        # —— 不建就直接 open() 失败，那会把「生成腿没建路径」伪装成「渲染器坏了」）
        outs[art.rel].mkdir(parents=True, exist_ok=True) if art.kind == "dir" \
            else outs[art.rel].parent.mkdir(parents=True, exist_ok=True)
    argv = build_render_argv(python or sys.executable, cases_rel, renderer_rel, outs)
    try:
        proc = subprocess.run(argv, cwd=str(repo), capture_output=True, text=True,
                              timeout=render_timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise GenerationError(f"渲染器无法执行（{type(exc).__name__}: {exc}）") from exc
    if proc.returncode != 0:
        tail = ((proc.stderr or "") + (proc.stdout or "")).strip().replace("\n", " ")[:600]
        raise GenerationError(f"渲染失败（rc={proc.returncode}）：{tail}")
    # 非空自证：rc=0 却**产出空**是最隐蔽的假绿（消费者会 import 到一个空包 / 读到空 casebook）
    empty: list[str] = []
    for art in ARTIFACTS:
        path = outs[art.rel]
        if art.kind == "dir":
            if not any(path.glob("*.py")):
                empty.append(art.rel + "/（没有任何模块）")
        elif not (path.is_file() and path.stat().st_size > 0):
            empty.append(art.rel + "（不存在或为空）")
    if empty:
        raise GenerationError(f"渲染器 rc=0 但**没有产出**：{'、'.join(empty)}")
    return proc.stdout.strip()


def tracked_artifact_paths(repo: Path) -> tuple[list[str], str]:
    """出库产物里**仍被 git 跟踪**的路径（空列表 = 合规）。`(paths, error)`；error 非空 ⇒ 无法判定。

    索引与 HEAD 两侧都查：`git add -f` 之后**还没提交**时索引里就已经有了它 ——
    那正是「悄悄塞回来」的第一个时点，只查 HEAD 会漏掉。
    """
    specs = [a.rel for a in ARTIFACTS]
    found: set[str] = set()
    errors: list[str] = []
    for label, argv in (("index", ("ls-files", "--cached", "--")),
                        ("HEAD", ("ls-tree", "-r", "--name-only", "HEAD", "--"))):
        proc = subprocess.run(["git", *argv, *specs], cwd=str(repo),
                              capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            errors.append(f"{label} 侧取不到（git rc={proc.returncode}）："
                          f"{(proc.stderr or '').strip().splitlines()[-1:][0][:120] if (proc.stderr or '').strip() else '（无输出）'}")
            continue
        found.update(ln.strip() for ln in proc.stdout.splitlines() if ln.strip())
    return sorted(found), "；".join(errors)


def gitignore_gaps(repo: Path) -> tuple[list[str], str]:
    """`.gitignore` 里**缺的**出库产物条目（空列表 = 合规）。`(gaps, error)`。"""
    try:
        lines = {ln.strip() for ln in (repo / GITIGNORE_REL).read_text(encoding="utf-8").splitlines()}
    except OSError as exc:
        return [], f"{GITIGNORE_REL} 读不到（{type(exc).__name__}）"
    return [f"{rel}（缺条目 {pattern}）" for rel, pattern in IGNORE_PATTERNS.items()
            if pattern not in lines], ""


def artifact_hygiene(repo: Path) -> dict:
    """出库形态的**卫生判定**（判据 1）：谁把它塞回 git / `.gitignore` 漏了条目。

    `applicable=False` 只出现在**临时提取树**（合并探测把 `git archive` 的内容解到非仓库目录）——
    那里没有 git 索引可查，本格**不判**并由调用方**显式报出**（不是静默跳过：真树永远 applicable）。
    """
    out: dict = {"applicable": False, "tracked": [], "gitignore_gaps": [], "undecidable": [], "note": ""}
    inner = _git_rc(repo, "rev-parse", "--is-inside-work-tree")
    if inner.returncode != 0 or inner.stdout.strip() != b"true":
        out["note"] = "不是 git 工作树（临时提取树）—— 本格不判；PR / main 的真树上会判"
        return out
    out["applicable"] = True
    tracked, err = tracked_artifact_paths(repo)
    out["tracked"] = tracked
    if err:
        out["undecidable"].append(f"「产物是否被塞回 git」无法判定：{err}")
    gaps, gerr = gitignore_gaps(repo)
    out["gitignore_gaps"] = gaps
    if gerr:
        out["undecidable"].append(f"`.gitignore` 覆盖判定无法执行：{gerr}")
    return out


def _base_report(repo: Path, cases_rel: str, renderer_rel: str, window: int,
                 mode: str) -> dict:
    """机器可读报告的**骨架**（两种 mode 共用；单一来源，别处不许再拼一份）。"""
    return {
        "schema": 1,
        "repo": str(repo),
        "cases": cases_rel,
        "renderer": renderer_rel,
        "mode": mode,
        "verdict": "undecidable",
        "problems": [],
        "undecidable": [],
        "drifted": [],
        "violations": [],
        "artifacts": [a.rel for a in ARTIFACTS],
        "seen": 0,
        "acted": 0,
        "recompute_command": recompute_command(),
        "rerender_command": rerender_command(),
        "generate_command": generate_command(),
        "drift_window": [],
        "drift_window_note": "",
        "window": window,
    }


def build_render_argv(python: str, cases_rel: str, renderer_rel: str, outs: dict[str, Path]) -> list[str]:
    """调渲染器的 argv（**不重写渲染**；`--out-*` 由注册表驱动）。"""
    argv = [python, renderer_rel, "--cases", cases_rel]
    for art in ARTIFACTS:
        argv += [art.out_flag, str(outs[art.rel])]
    return argv


# ── 目录型生成物（issue #8188）：逐模块逐字节 + 「未登记 / 缺模块」都判红 ─────────────────────


def _module_bytes(directory: Path) -> dict[str, bytes]:
    """目录里的**模块文件**（`*.py`，不递归）→ `{文件名: 字节}`。

    只看 `*.py`：生成物目录里可以出现 `__pycache__/`（导入时产生、不入库），
    那不是生成物的一部分 ⇒ 不参与比对（否则「跑过一次测试」会伪造漂移）。
    """
    return {p.name: p.read_bytes() for p in sorted(directory.glob("*.py")) if p.is_file()}


def _artifact_bytes_equal(committed: dict[str, bytes], renewed: dict[str, bytes]) -> bool:
    """目录型产物是否**逐模块逐字节**相同 —— 判定的**单一比较点**（红证变异锚点）。

    独立成函数是为了让「把比较换成恒绿 ⇒ 同一夹具变绿」这条判别力自证有一个**唯一**、
    可逐字替换的锚点（目录型产物不能用单文件那处 `if committed == renewed:`）。
    """
    return committed == renewed


def _compare_dir_artifact(repo: Path, art: Artifact, renewed_dir: Path):
    """目录型生成物 vs 提交版：`(drifted_row | None, problems, undecidable)`。

    判红三种形态（**逐条具名到模块文件**）：
      ① 同名模块字节不同（改完用例库没重渲染）；
      ② 提交版有、渲染结果没有 ⇒ **未登记模块**（手塞进生成物目录的 `.py`）；
      ③ 渲染结果有、提交版没有 ⇒ **缺模块**（生成了却没提交）。
    `drifted_row` 仍是**产物级**的一行（产物名 + 总行数差），逐模块明细进 `problems`。
    """
    problems: list[str] = []
    undecidable: list[str] = []
    if not renewed_dir.is_dir():
        undecidable.append(f"渲染产物不是目录：{art.rel}/（渲染器新版应写目录；旧版才写单文件）")
        return None, problems, undecidable
    renewed = _module_bytes(renewed_dir)
    committed = _module_bytes(repo / art.rel) if (repo / art.rel).is_dir() else {}
    if not renewed:
        undecidable.append(f"渲染产物目录里没有任何模块文件：{art.rel}/")
        return None, problems, undecidable
    if not committed:
        undecidable.append(f"生成物目录不存在或没有模块文件：{art.rel}/")
        return None, problems, undecidable
    if _artifact_bytes_equal(committed, renewed):
        return None, problems, undecidable

    extra = sorted(set(committed) - set(renewed))
    missing = sorted(set(renewed) - set(committed))
    for name in extra:
        problems.append(f"   📦 未登记模块：{art.rel}/{name}（提交版有、渲染结果没有 "
                        f"⇒ 生成物目录**不许手塞**：删掉它）")
    for name in missing:
        problems.append(f"   📦 缺模块：{art.rel}/{name}（渲染结果有、提交版没有 "
                        f"⇒ 重渲染并提交生成物）")

    n_committed = n_renewed = n_changed = 0
    for name in sorted(set(committed) | set(renewed)):
        c_bytes = committed.get(name, b"")
        r_bytes = renewed.get(name, b"")
        c_text = c_bytes.decode("utf-8", "replace")
        r_text = r_bytes.decode("utf-8", "replace")
        c_lines, r_lines, changed = _changed_line_count(c_text, r_text)
        n_committed += c_lines
        n_renewed += r_lines
        n_changed += changed
        if c_bytes == r_bytes:
            continue
        if name in extra or name in missing:
            # 缺/多模块已经有**具名**的一行（上面的 📦）；这里只补行数读数，不重复印 diff
            problems.append(f"      行数：提交版 {c_lines} 行 / 现取 {r_lines} 行")
            continue
        problems += [f"   📄 模块：{art.rel}/{name}"] + divergence_report(
            f"{art.rel}/{name}", c_text, r_text)

    if not (extra or missing or n_changed):
        return None, problems, undecidable
    # 产物级差量行（与单文件产物的 `divergence_report` 同形：产物名 + 两侧行数 + 不同行数）
    # ⇒ 「差量是现取的真数、不是模板」这条判据对**目录型产物**同样有对象可判。
    header = [
        f"❌ 产物：{art.rel}（目录型产物：逐模块比对，共 {len(set(committed) | set(renewed))} 个模块）",
        f"   差量：提交版 {n_committed} 行 / 现取 {n_renewed} 行；不同 {n_changed} 行",
    ]
    return (art.rel, n_committed, n_renewed, n_changed), header + problems, undecidable


def _changed_line_count(committed: str, renewed: str) -> tuple[int, int, int]:
    """`(提交版行数, 现取行数, 不同的行数)`；不同的行数按 opcode 逐块累加（不读挂钟、不看大小）。"""
    a = committed.splitlines()
    b = renewed.splitlines()
    changed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag != "equal":
            changed += max(i2 - i1, j2 - j1)
    return len(a), len(b), changed


def _first_diff_excerpt(committed: str, renewed: str, limit: int = 3) -> list[str]:
    """首个（及后续至多 `limit` 个）差异块的**两侧原文**（带 1-based 行号）。"""
    a = committed.splitlines()
    b = renewed.splitlines()
    out: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        out.append(f"第 {i1 + 1} 行起：")
        if i1 < i2:
            out.append(f"  - 提交版（{i2 - i1} 行）：{a[i1][:200]}")
        else:
            out.append("  - 提交版：**该行不存在**（现取比提交版多出来）")
        if j1 < j2:
            out.append(f"  + 现取　（{j2 - j1} 行）：{b[j1][:200]}")
        else:
            out.append("  + 现取　：**该行不存在**（提交版比现取多出来）")
        if len(out) >= limit * 3:
            break
    return out


def divergence_report(rel: str, committed: str, renewed: str) -> list[str]:
    """**具名**的漂移报告（产物名 + 差量 + 两侧原文 + 两条可复制命令）。纯函数，夹具可直接喂。"""
    n_committed, n_renewed, n_changed = _changed_line_count(committed, renewed)
    lines = [
        f"❌ 产物：{rel}",
        f"   差量：提交版 {n_committed} 行 / 现取 {n_renewed} 行；不同 {n_changed} 行",
    ]
    lines += ["   " + ln for ln in _first_diff_excerpt(committed, renewed)]
    lines.append(f"   复算（可复制）：{recompute_command()}")
    lines.append(f"   重渲染并提交（可复制）：{rerender_command()}")
    lines.append("   注意：生成物**不许手改** —— 改 `.github/cases/**` 后重渲染并提交重渲染结果。")
    return lines


def error_annotation(drifted: list[tuple[str, int, int, int]], undecidable: list[str],
                     violations: list[str] | None = None) -> str:
    """**单行** `::error::` 注解：产物名 + 差量 + 复算命令（不许不具名）。"""
    if violations:
        return (f"{ERROR_PREFIX}出库形态判红（issue #8167 P1-1）：{'；'.join(violations)[:300]}"
                " —— 处置：见 stdout 的具名明细（被跟踪 ⇒ `git rm --cached`；不可复现 ⇒ 修渲染器）")
    if undecidable:
        why = "；".join(undecidable)[:300]
        return (f"{ERROR_PREFIX}生成物新鲜度**无法判定**（fail-closed，绝不当「通过/跳过」读）：{why}"
                f" —— 复算：{recompute_command()}")
    parts = [f"{rel}（提交版 {c} 行 / 现取 {r} 行，不同 {d} 行）" for rel, c, r, d in drifted]
    return (f"{ERROR_PREFIX}生成物新鲜度：{len(drifted)} 个产物与 `{CASES_REL}/**` 不同步 —— "
            + "；".join(parts) + f" —— 复算：{recompute_command()}")


def drift_window(repo: Path, window: int, cases_rel: str = CASES_REL) -> tuple[list[str], str]:
    """漂移候选区间：最近 `window` 个**改了用例库**的提交。返回 `(行, 说明)`。

    🔴 **只给读数，不下断言**：这里列出的是「可能性区间」，不是「凶手」——
    提交级读数不能证明因果（用它下断言正是本文件要治的归因错误）。
    取不到（浅检出 / 无 git / 非仓库）⇒ 返回空 + 说明，**不影响判定**（这是辅助读数，不是判据）。
    """
    try:
        proc = subprocess.run(
            ["git", "log", f"-{window}", "--format=%h %ad %s", "--date=short", "--", cases_rel],
            cwd=str(repo), capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - 环境相关
        return [], f"取不到（{type(exc).__name__}）—— 不影响判定"
    if proc.returncode != 0:
        return [], (f"取不到（git rc={proc.returncode}：{(proc.stderr or '').strip()[:120]}）—— 不影响判定")
    rows = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    return rows, f"最近 {window} 个提交里改了 `{cases_rel}/` 的：{len(rows)} 个"


def _violation_block(report: dict) -> list[str]:
    """出库形态判红的**具名**明细（两种 mode 共用；处置命令可复制）。"""
    lines = ["", f"🔴 出库形态判红（issue #8167 P1-1）：命中 {len(report['violations'])} 处"]
    lines += [f"     - {v}" for v in report["violations"]]
    lines.append("     处置（可复制）：① 被跟踪 ⇒ `git rm --cached <上列路径>`（**保留工作区文件**）"
                 f"；② 不可复现 ⇒ 修渲染器（不是重试）；③ 生成：{generate_command()}")
    return lines


def _out_of_git_problems(report: dict, repo: Path, *, python: str, cases_rel: str,
                         renderer_rel: str, render_timeout: int,
                         first: dict[str, bytes] | None = None) -> dict[str, bytes]:
    """出库形态的**确定性判定**（issue #8167 P1-1），两种 mode 共用（单一实现，别处不许再写）。

    渲染**确定性**：同一棵树连渲两次**逐字节**相同。不同 ⇒ `violations`（判红，具名到产物）。

    ⚠️ 为什么必须**显式**判：入库时代它被「提交版 vs 现取」间接兜住（提交版存在 ⇒ 有人跑过），
    出库后那一步没有了 —— 只剩「磁盘副本 vs 本次渲染」，而那一步是**自指**的（刚 `--write` 过必然相等）。
    取不到 ⇒ `undecidable`（**不是**「通过」）。
    ⚠️ 另一半（产物**不许被 git 跟踪** / `.gitignore` 必须覆盖）是对**本仓库形态**的判定，不放这里
    —— 见 `artifact_hygiene()` 的专用判据 `tests/unit_ci_workflows/test_generated_artifacts_untracked.py`。

    返回**第一次**渲染的字节投影（调用方复用它判「落盘副本是否陈旧」，省一次全量渲染）；
    渲染没成 ⇒ `{}`（原因已进 `report["undecidable"]`）。
    """
    # ⚠️ 「产物是否被塞回 git / `.gitignore` 是否覆盖」**不在这里**判：那是**本仓库**的形态事实
    # （夹具树与合并探测的提取树都不是仓库，没有索引可查）⇒ 由 `artifact_hygiene()` 的**专用判据**
    # 在真仓库上判：`tests/unit_ci_workflows/test_generated_artifacts_untracked.py`（required 腿里跑）。
    # 本函数只判**树内可判**的那一半：渲染确定性。
    if first is None:
        first, err = _render_once(repo, python, cases_rel, renderer_rel, render_timeout, "det1")
        if err:
            report["undecidable"].append(f"确定性判定：第 1 次{err}")
            return {}
    second, err = _render_once(repo, python, cases_rel, renderer_rel, render_timeout, "det2")
    if err:
        report["undecidable"].append(f"确定性判定：第 2 次{err}")
        return first
    diff = sorted(rel for rel in set(first) | set(second) if first.get(rel) != second.get(rel))
    if diff:
        report["violations"].append(
            f"渲染**不可复现**：同一棵树连渲染两次，以下产物不同：{'、'.join(diff)}"
            "（结果依赖了非源输入：时间戳 / 集合顺序 / 环境 ⇒ 修渲染器，不是重试）")
    return first


def evaluate(repo: Path, *, python: str | None = None, cases_rel: str = CASES_REL,
             renderer_rel: str = RENDERER_REL, window: int = DEFAULT_WINDOW,
             render_timeout: int = 300) -> dict:
    """跑一次判定，返回**机器可读报告**（`verdict` / `problems` / `drifted` / `undecidable` / …）。

    fail-closed 的每一条都在**渲染之前**判定，且**没有任何「跳过」出口**。
    `mode="on-disk"` = 树里已有一份副本（本地跑过生成）⇒ 判「副本是不是最新的」；
    副本不存在 ⇒ 转 `evaluate_untracked()`（判可复现性），**不是** `return 0`。
    """
    report: dict = _base_report(repo, cases_rel, renderer_rel, window, mode="on-disk")
    undecidable: list[str] = report["undecidable"]

    renderer = repo / renderer_rel
    cases_dir = repo / cases_rel
    if not renderer.is_file():
        undecidable.append(f"渲染器缺失：{renderer_rel}")
    if not cases_dir.is_dir():
        undecidable.append(f"用例库缺失：{cases_rel}/")
    missing = [a.rel + ("/" if a.kind == "dir" else "") for a in ARTIFACTS
               if not ((repo / a.rel).is_dir() if a.kind == "dir" else (repo / a.rel).is_file())]
    if missing:
        # 出库形态（issue #8167 P1-1）：产物**本来就不在树里**。但「不在」**不是**「通过」也
        # **不是**「免检」—— 判定转交给 `evaluate_untracked()`（可复现性 + 没被塞回 git），
        # 仍然会红。这里**不是** `return 0` 的入口。
        return evaluate_untracked(repo, python=python, cases_rel=cases_rel,
                                  renderer_rel=renderer_rel, render_timeout=render_timeout,
                                  window=window, missing=missing)
    if undecidable:
        report["problems"] = [
            f"{ERROR_PREFIX}生成物新鲜度**无法判定**（fail-closed）：{'；'.join(undecidable)}",
            f"   复算（可复制）：{recompute_command()}",
        ]
        report["error_annotation"] = error_annotation([], undecidable)
        return report

    report["seen"] = len(ARTIFACTS)
    python = python or sys.executable
    with tempfile.TemporaryDirectory() as td:
        outs = {a.rel: Path(td) / Path(a.rel).name for a in ARTIFACTS}
        argv = build_render_argv(python, cases_rel, renderer_rel, outs)
        try:
            proc = subprocess.run(argv, cwd=str(repo), capture_output=True, text=True,
                                  timeout=render_timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            undecidable.append(f"渲染器无法执行（{type(exc).__name__}: {exc}）")
            report["problems"] = [
                f"{ERROR_PREFIX}生成物新鲜度**无法判定**（fail-closed）：{undecidable[-1]}",
                f"   复算（可复制）：{recompute_command()}",
            ]
            report["error_annotation"] = error_annotation([], undecidable)
            return report
        if proc.returncode != 0:
            tail = ((proc.stderr or "") + (proc.stdout or "")).strip().replace("\n", " ")[:400]
            undecidable.append(f"渲染失败（rc={proc.returncode}）：{tail}")
            report["problems"] = [
                f"{ERROR_PREFIX}生成物新鲜度**无法判定**（fail-closed，渲染器 rc={proc.returncode}）：{tail}",
                f"   复算（可复制）：{recompute_command()}",
            ]
            report["error_annotation"] = error_annotation([], undecidable)
            return report

        drifted: list[tuple[str, int, int, int]] = []
        # 出库形态的两条新判定（issue #8167 P1-1）—— 复用本步已渲染的 `outs` 当"第一次渲染"，
        # 只多渲一次就够判确定性（省一次全量渲染）。
        _out_of_git_problems(report, repo, python=python, cases_rel=cases_rel,
                             renderer_rel=renderer_rel, render_timeout=render_timeout,
                             first={a.rel: _bundle(outs[a.rel], a) for a in ARTIFACTS})
        for art in ARTIFACTS:
            if art.kind == "dir":
                row, problems, undec = _compare_dir_artifact(repo, art, outs[art.rel])
                undecidable += undec
                if row is not None:
                    drifted.append(row)
                    report["problems"] += problems
                continue
            renewed = outs[art.rel].read_text(encoding="utf-8")
            if not renewed.strip():
                undecidable.append(f"渲染产物为空：{art.rel}")
                continue
            committed = (repo / art.rel).read_text(encoding="utf-8")
            if committed == renewed:
                continue
            n_c, n_r, n_d = _changed_line_count(committed, renewed)
            drifted.append((art.rel, n_c, n_r, n_d))
            report["problems"] += divergence_report(art.rel, committed, renewed)

    if undecidable:
        report["problems"] = [
            f"{ERROR_PREFIX}生成物新鲜度**无法判定**（fail-closed）：{'；'.join(undecidable)}",
            f"   复算（可复制）：{recompute_command()}",
        ]
        report["error_annotation"] = error_annotation([], undecidable)
        return report

    report["drifted"] = [{"artifact": rel, "committed_lines": c, "renewed_lines": r, "changed_lines": d}
                         for rel, c, r, d in drifted]
    report["acted"] = len(drifted)
    if report["violations"]:
        # 出库形态的违规（被塞回 git / 渲染不可复现）比「副本陈旧」更根本：陈旧一条命令就好，
        # 违规要改仓库形态 ⇒ 先报它（旧的漂移读数仍留在 problems 里，不丢）。
        report["verdict"] = "drifted"
        report["problems"] += _violation_block(report)
        report["error_annotation"] = error_annotation([], [], report["violations"])
        return report
    if drifted:
        report["verdict"] = "drifted"
        rows, note = drift_window(repo, window, cases_rel)
        report["drift_window"] = rows
        report["drift_window_note"] = note
        report["problems"].append("")
        report["problems"].append(
            f"🔎 漂移候选区间（**只给读数，不下断言** —— 这里列出的是可能性区间，不是「凶手」）：{note}")
        report["problems"] += [f"     {row}" for row in rows] or ["     （取不到提交级读数）"]
        report["problems"].append(
            f"     处置：{rerender_command()} 后提交生成物（**不要手改生成物**）；")
        report["problems"].append(
            "     若无人在 PR 上改了 `.github/cases/**`，说明漂移是**直接落在 main 上**的"
            "（本腿存在的理由）—— 归因看提交级读数，不要指向某个 PR。")
        report["problems"].append(
            f"     一步归因（**先做这个再动手**，issue #6027）：{BASE_PROBE_COMMAND}"
            "  ⇒ base 侧同样陈旧 = 漂移不是本 PR 引入（别在这里重渲染去顶）；"
            "base 新鲜 = 漂移由本树引入；无法判定 ≠ 本树引入。")
        report["error_annotation"] = error_annotation(drifted, [])
    else:
        report["verdict"] = "fresh"
        report["problems"].append(
            f"✅ 生成物与 `{cases_rel}/**` 同步（检查 {report['seen']} 个产物："
            + "、".join(a.rel for a in ARTIFACTS) + "）")
    return report


def _bundle(path: Path, art: Artifact) -> bytes | None:
    """产物的**可比字节投影**：单文件 = 全文；目录 = 排序后 `模块名\\0内容` 的拼接。

    目录里**多出的模块**（手塞）与**缺的模块**都会让投影不同 —— 这正是要判的两种形态。
    不是目录/文件 ⇒ `None`（= 该产物不在树里）。
    """
    if art.kind == "dir":
        if not path.is_dir():
            return None
        parts = [p.name.encode() + b"\0" + p.read_bytes() for p in sorted(path.glob("*.py"))]
        return b"\0\0".join(parts) if parts else None
    return path.read_bytes() if path.is_file() else None


def _render_once(repo: Path, python: str, cases_rel: str, renderer_rel: str,
                 render_timeout: int, tag: str) -> tuple[dict[str, bytes], str]:
    """渲染到一个临时目录，返回 `({产物: 字节投影}, 错误)`。错误非空 ⇒ 渲染没成。"""
    with tempfile.TemporaryDirectory() as td:
        outs = {a.rel: Path(td) / tag / Path(a.rel).name for a in ARTIFACTS}
        argv = build_render_argv(python, cases_rel, renderer_rel, outs)
        try:
            proc = subprocess.run(argv, cwd=str(repo), capture_output=True, text=True,
                                  timeout=render_timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            return {}, f"渲染器无法执行（{type(exc).__name__}: {exc}）"
        if proc.returncode != 0:
            tail = ((proc.stderr or "") + (proc.stdout or "")).strip().replace("\n", " ")[:400]
            return {}, f"渲染失败（rc={proc.returncode}）：{tail}"
        return {a.rel: _bundle(outs[a.rel], a) for a in ARTIFACTS}, ""


def _finish_untracked(report: dict) -> dict:
    """出库形态的收口（三态判定；**没有「跳过」这一态**）。"""
    undecidable = report["undecidable"]
    if undecidable:
        report["verdict"] = "undecidable"
        report["problems"] = [
            f"{ERROR_PREFIX}生成物判定**无法判定**（fail-closed，绝不当「通过/跳过」读）："
            + "；".join(undecidable),
            f"   生成（可复制）：{generate_command()}",
        ]
        report["error_annotation"] = error_annotation([], undecidable)
        return report
    if report["violations"]:
        report["verdict"] = "drifted"
        report["problems"] += _violation_block(report)
        report["error_annotation"] = error_annotation([], [], report["violations"])
        return report
    if report["drifted"]:
        report["verdict"] = "drifted"
        report["error_annotation"] = error_annotation(report["drifted"], [])
        return report
    report["verdict"] = "fresh"
    report["seen"] = len(ARTIFACTS)
    report["problems"].append(
        f"✅ 出库产物可复现（{report['seen']} 个产物：" + "、".join(a.rel for a in ARTIFACTS)
        + "；两次渲染逐字节相同、未被 git 跟踪；缺副本不构成免检 —— 本判定就是它的替代）")
    return report


def evaluate_untracked(repo: Path, *, python: str | None = None, cases_rel: str = CASES_REL,
                       renderer_rel: str = RENDERER_REL, render_timeout: int = 300,
                       window: int = DEFAULT_WINDOW, missing: list[str] | None = None) -> dict:
    """**出库形态**的判定本体（issue #8167 P1-1）：`evaluate()` 发现产物不在树里时转到这里。

    判三条（模块 docstring「出库形态」节），**没有「跳过」出口**：

    1. 产物不许被 git 跟踪、`.gitignore` 必须覆盖；
    2. 连渲染两次**逐字节**相同（非确定性 / 渲染失败 / 空产出 ⇒ 非零）；
    3. 磁盘上若已有副本，它必须与本次渲染一致（陈旧或手改 ⇒ rc 1）。

    🔴 与入库形态的**唯一**差别：没有「提交版」这个比较对象。**不是**少了一条判据 ——
    换上来的是「能不能稳定重建」，那是产物出库后**唯一**还有意义的陈述。
    """
    report = _base_report(repo, cases_rel, renderer_rel, window, mode="absent")
    problems: list[str] = report["problems"]
    if missing:
        problems.append(
            "ℹ️ 出库形态：产物不在树里属**预期**（不是错误），判定改为**可复现性**"
            f"（缺：{'、'.join(missing)}）—— 生成：{generate_command()}")
    if not (repo / renderer_rel).is_file():
        report["undecidable"].append(f"渲染器缺失：{renderer_rel}")
    if not (repo / cases_rel).is_dir():
        report["undecidable"].append(f"用例库缺失：{cases_rel}/")
    report["seen"] = len(ARTIFACTS)
    # ①② 与「副本存在」那条路径**共用同一实现**（单一来源），返回值复用为第 1 次渲染
    first = _out_of_git_problems(report, repo, python=python or sys.executable,
                                 cases_rel=cases_rel, renderer_rel=renderer_rel,
                                 render_timeout=render_timeout)
    empty = [a.rel for a in ARTIFACTS if not first.get(a.rel)]
    if first and empty:
        report["undecidable"].append(
            f"渲染 rc=0 但产出为空：{'、'.join(empty)}（语料或渲染器形态变了？）")

    # ③ 副本**存在**的产物必须与本次渲染一致（缺副本不判这一条：那是出库形态的预期）
    for art in ARTIFACTS:
        on_disk = _bundle(repo / art.rel, art)
        if on_disk is None or not first.get(art.rel) or on_disk == first.get(art.rel):
            continue
        n_disk = len(on_disk.decode("utf-8", "replace").splitlines())
        n_new = len(first[art.rel].decode("utf-8", "replace").splitlines())
        report["drifted"].append((art.rel, n_disk, n_new, abs(n_disk - n_new)))
        problems += [
            f"❌ 落盘副本与本次渲染**不一致**：{art.rel}（陈旧或手改）",
            f"   差量：落盘 {n_disk} 行 / 现取 {n_new} 行",
            f"   处置（可复制）：{generate_command()}",
        ]
    return _finish_untracked(report)


def summary_line(report: dict) -> str:
    """机器可读的单行读数（存活读数用；**与负载无关**，不含任何时长）。"""
    if report["verdict"] == "fresh":
        why = "全部新鲜"
    elif report["verdict"] == "drifted":
        names = [d["artifact"] for d in report.get("drifted") or []]
        names += [v.split("（")[0].split("：")[0] for v in report.get("violations") or []]
        why = "陈旧/违规：" + "、".join(dict.fromkeys(names))
    else:
        why = "无法判定：" + "；".join(report.get("undecidable") or [])[:160]
    return (f"MIGAO-GENFRESH-SUMMARY seen={report.get('seen', 0)} acted={report.get('acted', 0)} "
            f"verdict={report.get('verdict', '?')} mode={report.get('mode', '?')} why={why}")


# ── 合并探测（`FM-E22`）：把「本树 × 基线」的**合并结果**物化出来，对**它**再判一次 ────────────
#
# 病灶（issue #5741 的机制，台账 `FM-E18`）：两个**各自新鲜**的分支合并后，块 hunk 取并集、而两侧
# **同值的汇总 hunk 干净合并不重算** ⇒ **落地的那份生成物比源陈旧**；而 PR 面的新鲜度判定跑在
# 「发起时的快照」上 ⇒ 它看不到**合并结果**这一面（`FM-E18` 的时序根因）。
# 本探测把「合到 `<ref>` 之后的那棵树」取出来，对**它**再判一次 ⇒ 这一面变成**PR 面可拦**。
#
# 🔴 **只读**：`git merge-tree --write-tree`（不落工作区、不改索引）+ `git archive <tree> <判定面路径>`
#    经 `tarfile` 解到临时目录（**不写仓内对象**）。判定面只需用例库 / 渲染器 / 两个生成物。

#: 合并探测要物化的路径（够跑 `evaluate()` 即可；整仓 `git archive` 太重）。
#:   🔴 issue #8167 P1-1 之后两个生成物**不在树里**（`git archive` 对不存在的 pathspec 直接
#:   报错）⇒ 只取 `.github`（用例库 + 渲染器），到提取树里**现场生成**再判「能不能稳定重建」。
#:   代价：`FM-E18/E22`（合并结果里「提交版生成物陈旧」）**整类**随出库消失 —— 已经没有
#:   「提交版」可以被合并 hunk 顶旧；剩下的可判面 = 合并后的用例库还渲不渲得出来。
MERGE_PROBE_PATHS: tuple[str, ...] = (".github",)


def _git_rc(repo: Path, *args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    """**判 rc 的** git 调用（`check=False` 的 stdout 不作证据 —— 台账 `NS` 口径）。"""
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, timeout=timeout)


def probe_merge(repo: Path, ref: str, *, python: str | None = None, window: int = DEFAULT_WINDOW,
                render_timeout: int = 300, tree_report: dict | None = None) -> dict:
    """判「**把本树合并到 `<ref>` 之后**，`render_cases.py` 还能不能稳定渲染」（`FM-E22`）。返回机器可读报告。

    出库形态（issue #8167 P1-1）之后**判定对象变了**（如实登记）：原来判「提交版生成物会不会被
    合并 hunk 顶旧」—— 产物出库后**没有提交版**，那一类失败形态结构性消失；现在判的是
    「合并后的用例库（两侧各加了用例）还能不能渲染出**确定**的产物」。

    三态 `verdict` ∈ {`fresh`, `drifted`, `undecidable`}；`undecidable` 含「取不到 `<ref>`」与
    「与 `<ref>` 冲突」（后者 GitHub 侧本来就会拦合并 ⇒ 不在此重复下判定，但**出声**、不当通过）。
    `attribution` 给「本树 / 合并结果」两侧读数 ⇒ **归因不指向错误的对象**（`FM-E4` 的教训）。
    """
    report: dict = {
        "schema": 1, "ref": ref, "base_sha": "", "merge_tree": "", "verdict": "undecidable",
        "tree_verdict": "", "merge_verdict": "", "attribution": "", "problems": [],
        "recompute_command": f"{recompute_command()} --merge-probe {ref}",
    }
    head = _git_rc(repo, "rev-parse", "--verify", "HEAD")
    if head.returncode != 0:
        report["problems"].append(f"{ERROR_PREFIX}合并探测**无法判定**：本检出没有 HEAD")
        return report
    base = _git_rc(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    if base.returncode != 0:
        report["problems"].append(
            f"{ERROR_PREFIX}合并探测**无法判定**：取不到 `{ref}` —— 先 `git fetch origin {ref}`；"
            "**取不到 ≠ 通过**（三态 3 不得当 0 读）")
        return report
    report["base_sha"] = base.stdout.decode().strip()

    merged = _git_rc(repo, "merge-tree", "--write-tree", "HEAD", ref)
    out_text = merged.stdout.decode("utf-8", "replace")
    lines = out_text.strip().splitlines()
    # `git merge-tree --write-tree`：**rc=0 干净**；**rc=1 = 有冲突**（仍会写出带冲突标记的 tree，
    # 首行是 tree oid）；rc>1 才是调用失败。⇒ **先判冲突**，再取 tree（否则会把冲突读成「工具坏了」）。
    if merged.returncode == 1 or "CONFLICT" in out_text:
        report["problems"].append(
            f"{ERROR_PREFIX}合并探测**无法判定**：本树与 `{ref}`（{report['base_sha'][:8]}）**冲突** "
            f"⇒ 合并结果不存在（GitHub 侧此刻也会拦合并）⇒ 先 rebase 到最新 `{ref}` 再重判")
        return report
    if merged.returncode != 0 or not lines:
        tail = (merged.stderr.decode("utf-8", "replace") or out_text).strip()
        report["problems"].append(f"{ERROR_PREFIX}合并探测**无法判定**：`git merge-tree` 退出 "
                                  f"{merged.returncode}：{tail[:200]}")
        return report
    report["merge_tree"] = lines[0].strip()

    with tempfile.TemporaryDirectory() as td:
        dest = Path(td)
        arc = _git_rc(repo, "archive", report["merge_tree"], *MERGE_PROBE_PATHS)
        if arc.returncode != 0 or not arc.stdout:
            why = (arc.stderr.decode("utf-8", "replace") or "").strip()[:200]
            report["problems"].append(f"{ERROR_PREFIX}合并探测**无法判定**：`git archive` 退出 "
                                      f"{arc.returncode}：{why}")
            return report
        try:
            with tarfile.open(fileobj=io.BytesIO(arc.stdout)) as tf:
                tf.extractall(dest)
        except (tarfile.TarError, OSError) as exc:
            report["problems"].append(f"{ERROR_PREFIX}合并探测**无法判定**：解包失败（{type(exc).__name__}）")
            return report
        tree = tree_report or evaluate(repo, python=python, window=window, render_timeout=render_timeout)
        # 出库形态（issue #8167 P1-1）：提取树取自 `git archive` ⇒ 真实现场里**没有**产物
        # （它们不在 git 里）⇒ `evaluate()` 自动落到 absent 分支（判合并后的用例库还渲不渲得出来、
        # 且渲得**稳定**）。`FM-E18/E22` 的「提交版被合并 hunk 顶旧」随出库整类消失 —— 没有提交版了。
        # ⚠️ 产物**仍在**树里的夹具树仍按「与提交版比对」判：两条路径由同一份实现决定，不是两套。
        merge = evaluate(dest, python=python, window=window, render_timeout=render_timeout)

    report["tree_verdict"] = str(tree.get("verdict") or "")
    report["merge_verdict"] = str(merge.get("verdict") or "")
    if merge["verdict"] == "drifted":
        report["verdict"] = "drifted"
        report["problems"] += [
            f"❌ 合并探测：把本树合并到 `{ref}`（{report['base_sha'][:8]}）之后，"
            f"`{CASES_REL}/**` **渲不出稳定的生成物** —— 落地的那棵树无法自证可重建",
            *merge["problems"],
        ]
    elif merge["verdict"] == "undecidable":
        report["problems"].append(
            f"{ERROR_PREFIX}合并探测**无法判定**（合并结果这一侧）："
            f"{'；'.join(merge.get('undecidable') or [])[:200]} —— 取不到 ≠ 通过")
        return report
    else:
        report["verdict"] = "fresh"
        report["problems"].append(f"✅ 合并探测：把本树合并到 `{ref}`（{report['base_sha'][:8]}）之后，"
                                  f"生成物仍与 `.github/cases/**` 同源")
    if report["tree_verdict"] == "drifted":
        hint = "本树自己就不新鲜 ⇒ **重渲染并提交生成物**（不许手改）；"
    elif report["merge_verdict"] != "fresh":
        hint = ("合并结果**渲不出确定的产物** ⇒ 合到该 ref 之后**重跑生成腿**"
                "（两个各自可重建的分支，合并后的用例库/渲染器组合不稳定）；")
    else:
        hint = ("两侧都新鲜 ⇒ 合并结果**仍可稳定重建**"
                "（出库后 `FM-E18`「提交版生成物被合并 hunk 顶旧」整类消失 —— 没有提交版了）。")
    report["attribution"] = (
        f"归因（别指向错误的对象）：本树 = **{report['tree_verdict']}** / 合并结果 = "
        f"**{report['merge_verdict']}** ⇒ " + hint)
    return report


def base_probe(repo: Path, ref: str, *, python: str | None = None) -> dict:
    """在**临时 worktree** 上复算 `ref` 的同一判定本体 ⇒ 回答「漂移是不是本树引入的」。

    三态：`fresh`（base 新鲜 ⇒ 漂移由**本树**引入）/ `drifted`（base 同样陈旧 ⇒ **不是**本树引入）/
    `undecidable`（取不到 ref / worktree 建不起来 / 复算失败）—— **`undecidable` 绝不允许读成「本树引入」**。

    与 `probe_merge` 的分工：那个回答「把本树合到 ref 之后是否新鲜」（`FM-E22`），本函数回答
    「**ref 自己**是否已经陈旧」（`FM-E4` 的归因纪律：别把 main 侧漂移记到下一个撞上的 PR 头上）。
    🔴 判定本体**只有一份**：本函数不写 render+diff，只在临时 worktree 里调同一份 `evaluate()`。
    """
    tmp = Path(tempfile.mkdtemp(prefix="migao-base-probe-"))
    wt = tmp / "base"
    out = {"ref": ref, "verdict": "undecidable", "problems": [], "attribution": "", "base_sha": ""}
    try:
        add = _git_rc(repo, "worktree", "add", "--detach", str(wt), ref)
        if add.returncode != 0:
            err = (add.stderr or add.stdout or "").strip().splitlines()
            out["problems"].append(
                f"{ERROR_PREFIX}base 归因**无法判定**：取不到 `{ref}`（git worktree add rc={add.returncode}）"
                f"：{err[-1][:160] if err else '（无输出）'}")
            out["attribution"] = (f"归因：**无法判定**（取不到 `{ref}`）—— 不许读成「本树引入」；"
                                  f"先 `git fetch origin main` 再复算。")
            return out
        sha = _git_rc(wt, "rev-parse", "HEAD")
        out["base_sha"] = sha.stdout.strip() if sha.returncode == 0 else ""
        report = evaluate(wt, python=python or sys.executable)
        verdict = report.get("verdict")
        if verdict not in ("fresh", "drifted"):
            out["problems"].append(
                f"{ERROR_PREFIX}base 归因**无法判定**：`{ref}` 上复算未得出结论（verdict={verdict}）")
            out["attribution"] = "归因：**无法判定**（base 侧复算没出结论）—— 不许读成「本树引入」。"
            return out
        out["verdict"] = verdict
        if verdict == "drifted":
            out["problems"].append(
                f"🔎 base 归因结果：`{ref}`（{out['base_sha'][:8] or '?'}）**自己也是陈旧的** "
                f"⇒ 漂移**不是本树/本 PR 引入**（本仓具名实例：2026-10-02 的 11 分钟窗口，issue #6027）。")
            out["attribution"] = (
                f"归因：**base 侧同样陈旧** ⇒ 不要在这个 PR 上重渲染生成物去顶；"
                f"按 main-freshness-guard 的面处置（或等 base 修复后重跑）。")
        else:
            out["problems"].append(
                f"🔎 base 归因结果：`{ref}`（{out['base_sha'][:8] or '?'}）**是新鲜的** "
                f"⇒ 漂移由**本树**引入。")
            out["attribution"] = f"归因：**本树引入** ⇒ 在本 PR 上 {rerender_command()} 并提交生成物。"
        return out
    finally:
        _git_rc(repo, "worktree", "remove", "--force", str(wt))
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成物新鲜度判定（render + 逐字节比对；单一实现）")
    ap.add_argument("--repo", default=str(DEFAULT_REPO), help="仓根（缺省 = 本文件所在仓库）")
    ap.add_argument("--cases", default=CASES_REL, help=f"用例库目录（缺省 {CASES_REL}）")
    ap.add_argument("--renderer", default=RENDERER_REL, help=f"渲染器路径（缺省 {RENDERER_REL}）")
    ap.add_argument("--python", default=sys.executable, help="跑渲染器的解释器（缺省 = 本进程的）")
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW, help="漂移候选区间的提交数")
    ap.add_argument("--json", default="", help="把机器可读报告写到该路径")
    ap.add_argument("--write", action="store_true",
                    help="先**就地生成**出库产物（幂等），再判定 —— CI / verify-all / 本地入口用这一档")
    ap.add_argument("--merge-probe", default="", metavar="REF",
                    help="额外判「把本树合并到该 ref 之后」生成物是否新鲜（`FM-E22`；缺省不跑）")
    ap.add_argument("--base-probe", default="", metavar="REF",
                    help="额外判「该 ref 自己是否也陈旧」⇒ 一步归因（issue #6027；缺省不跑）")
    args = ap.parse_args(argv)

    repo = Path(args.repo)
    if args.write:
        # 出库形态的**生成腿**：产物不在 git 里 ⇒ 任何「判定」之前必须先把它们造出来。
        # 失败 ⇒ rc 3（fail-closed），**不许**继续跑一个没有被测对象的判定。
        try:
            print(ensure_generated(repo, python=args.python, cases_rel=args.cases,
                                   renderer_rel=args.renderer))
        except GenerationError as exc:
            print(f"{ERROR_PREFIX}生成失败（fail-closed）：{exc}")
            # 🔴 机读面**在失败路径上也要有**：读报告的人/脚本不该因为「这一步红了」拿不到任何结构
            # （那会让「红的形状」与「绿的形状」不同 ⇒ 归因只能靠猜）。rc 仍是 3（不可判定）。
            if args.json:
                Path(args.json).write_text(json.dumps({
                    "schema": 1, "repo": str(repo), "mode": "write-failed",
                    "verdict": "undecidable", "problems": [f"生成失败（fail-closed）：{exc}"],
                    "undecidable": [str(exc)], "drifted": [], "violations": [],
                    "artifacts": [a.rel for a in ARTIFACTS], "seen": 0, "acted": 0,
                    "generate_command": generate_command(), "exit_code": RC_UNDECIDABLE,
                }, ensure_ascii=False, indent=1), encoding="utf-8")
            return RC_UNDECIDABLE

    report = evaluate(repo, python=args.python, cases_rel=args.cases,
                      renderer_rel=args.renderer, window=args.window)
    for line in report["problems"]:
        print(line)
    if report["verdict"] != "fresh":
        print(report["error_annotation"])
    print(summary_line(report))
    rc = {"fresh": RC_FRESH, "drifted": RC_DRIFT}.get(report["verdict"], RC_UNDECIDABLE)

    probe: dict | None = None
    if args.merge_probe:
        probe = probe_merge(Path(args.repo), args.merge_probe, python=args.python,
                            window=args.window, tree_report=report)
        for line in probe["problems"]:
            print(line)
        if probe.get("attribution"):
            print(f"   {probe['attribution']}")
        print(f"MIGAO-GENFRESH-PROBE ref={probe['ref']} base={probe['base_sha'][:8] or '?'} "
              f"tree={probe['tree_verdict'] or '?'} merged={probe['merge_verdict'] or '?'} "
              f"verdict={probe['verdict']}")
        if probe["verdict"] == "drifted":
            rc = RC_DRIFT
        elif probe["verdict"] == "undecidable" and rc == RC_FRESH:
            rc = RC_UNDECIDABLE

    if args.base_probe:
        bp = base_probe(Path(args.repo), args.base_probe, python=args.python)
        for line in bp["problems"]:
            print(line)
        if bp.get("attribution"):
            print(f"   {bp['attribution']}")
        print(f"MIGAO-GENFRESH-BASE ref={bp['ref']} base={bp['base_sha'][:8] or '?'} verdict={bp['verdict']}")
        # 诊断档：结论已给出 ⇒ 0；**无法判定 ⇒ 3**（不许读成「本树引入」）
        if bp["verdict"] == "undecidable" and rc == RC_FRESH:
            rc = RC_UNDECIDABLE

    if args.json:
        payload = dict(report)
        # 🔴 验收 P2-3：只带 `--merge-probe` 时，**退出码可能是 1 而顶层 `verdict` 仍是本树的 `fresh`**
        #    ⇒ 机读面必须自带「合起来看」的那一格，否则读的人会把合并结果的结论漏掉。
        payload["verdict_overall"] = {RC_FRESH: "fresh", RC_DRIFT: "drifted"}.get(rc, "undecidable")
        payload["exit_code"] = rc
        if probe is not None:
            payload["merge_probe"] = probe
        Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
