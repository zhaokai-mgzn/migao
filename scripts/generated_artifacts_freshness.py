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
| `tests/agent_eval/eval_cases.py` | `.github/cases/**` |
| `docs/testing/mibao-verification-cases.md` | `.github/cases/**` |

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
import json
import subprocess
import sys
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


@dataclass(frozen=True)
class Artifact:
    """一个生成物 + 它对应的 `render_cases.py` 输出开关。"""

    rel: str
    out_flag: str


ARTIFACTS: tuple[Artifact, ...] = (
    Artifact("tests/agent_eval/eval_cases.py", "--out-eval"),
    Artifact("docs/testing/mibao-verification-cases.md", "--out-md"),
)


def recompute_command() -> str:
    """**可复制**的复算命令（人读；与两个 workflow 实际跑的是同一份实现）。"""
    return "python3 scripts/generated_artifacts_freshness.py"


def rerender_command() -> str:
    """**可复制**的重渲染并提交命令（口径与 `scripts/drift_audit.py` 的 remedy 一致）。"""
    pairs = " ".join(f"{a.out_flag} {a.rel}" for a in ARTIFACTS)
    return f"python3 {RENDERER_REL} --cases {CASES_REL} {pairs}"


def build_render_argv(python: str, cases_rel: str, renderer_rel: str, outs: dict[str, Path]) -> list[str]:
    """调渲染器的 argv（**不重写渲染**；`--out-*` 由注册表驱动）。"""
    argv = [python, renderer_rel, "--cases", cases_rel]
    for art in ARTIFACTS:
        argv += [art.out_flag, str(outs[art.rel])]
    return argv


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


def error_annotation(drifted: list[tuple[str, int, int, int]], undecidable: list[str]) -> str:
    """**单行** `::error::` 注解：产物名 + 差量 + 复算命令（不许不具名）。"""
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


def evaluate(repo: Path, *, python: str | None = None, cases_rel: str = CASES_REL,
             renderer_rel: str = RENDERER_REL, window: int = DEFAULT_WINDOW,
             render_timeout: int = 300) -> dict:
    """跑一次判定，返回**机器可读报告**（`verdict` / `problems` / `drifted` / `undecidable` / …）。

    fail-closed 的每一条都在**渲染之前**判定，且**没有任何「跳过」出口**。
    """
    report: dict = {
        "schema": 1,
        "repo": str(repo),
        "cases": cases_rel,
        "renderer": renderer_rel,
        "verdict": "undecidable",
        "problems": [],
        "undecidable": [],
        "drifted": [],
        "artifacts": [a.rel for a in ARTIFACTS],
        "seen": 0,
        "acted": 0,
        "recompute_command": recompute_command(),
        "rerender_command": rerender_command(),
        "drift_window": [],
        "drift_window_note": "",
    }
    undecidable: list[str] = report["undecidable"]

    renderer = repo / renderer_rel
    cases_dir = repo / cases_rel
    if not renderer.is_file():
        undecidable.append(f"渲染器缺失：{renderer_rel}")
    if not cases_dir.is_dir():
        undecidable.append(f"用例库缺失：{cases_rel}/")
    missing = [a.rel for a in ARTIFACTS if not (repo / a.rel).is_file()]
    if missing:
        undecidable.append(f"生成物缺失：{'、'.join(missing)}")
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
        for art in ARTIFACTS:
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
        report["error_annotation"] = error_annotation(drifted, [])
    else:
        report["verdict"] = "fresh"
        report["problems"].append(
            f"✅ 生成物与 `{cases_rel}/**` 同步（检查 {report['seen']} 个产物："
            + "、".join(a.rel for a in ARTIFACTS) + "）")
    return report


def summary_line(report: dict) -> str:
    """机器可读的单行读数（存活读数用；**与负载无关**，不含任何时长）。"""
    why = ("全部新鲜" if report["verdict"] == "fresh"
           else ("陈旧：" + "、".join(d["artifact"] for d in report["drifted"])
                 if report["verdict"] == "drifted"
                 else "无法判定：" + "；".join(report.get("undecidable") or [])[:160]))
    return (f"MIGAO-GENFRESH-SUMMARY seen={report.get('seen', 0)} acted={report.get('acted', 0)} "
            f"verdict={report.get('verdict', '?')} why={why}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成物新鲜度判定（render + 逐字节比对；单一实现）")
    ap.add_argument("--repo", default=str(DEFAULT_REPO), help="仓根（缺省 = 本文件所在仓库）")
    ap.add_argument("--cases", default=CASES_REL, help=f"用例库目录（缺省 {CASES_REL}）")
    ap.add_argument("--renderer", default=RENDERER_REL, help=f"渲染器路径（缺省 {RENDERER_REL}）")
    ap.add_argument("--python", default=sys.executable, help="跑渲染器的解释器（缺省 = 本进程的）")
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW, help="漂移候选区间的提交数")
    ap.add_argument("--json", default="", help="把机器可读报告写到该路径")
    args = ap.parse_args(argv)

    report = evaluate(Path(args.repo), python=args.python, cases_rel=args.cases,
                      renderer_rel=args.renderer, window=args.window)
    for line in report["problems"]:
        print(line)
    if report["verdict"] != "fresh":
        print(report["error_annotation"])
    print(summary_line(report))
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"fresh": RC_FRESH, "drifted": RC_DRIFT}.get(report["verdict"], RC_UNDECIDABLE)


if __name__ == "__main__":
    raise SystemExit(main())
