#!/usr/bin/env python3
"""code_mass_report.py — 代码体量 / churn / 重复事实源，一条只读报告（issue #8165）。

## 这个脚本做什么（以及**不**做什么）

三张表，全部**现取读数**，**零网络、零 LLM、纯标准库、只读**（不写任何文件）：

① **分层体量**：按目录聚合 `.java` / `.py` / `.ts` / `.tsx` 的总行 / 注释行 / 空行 / 逻辑行
   （逻辑行 = 总行 − 注释 − 空行）。
② **大文件 × churn**：源码文件行数 top N × 最近 N 次提交里出现的次数
   （`git log -N --name-only`），交叉表用于挑切片目标。
③ **重复事实源核对**：脚本内 `REGISTRY` 登记表（事实源 → 副本），逐条核副本**存在**且与源
   **逐字节一致**；不一致列出首个差异位置。**只裁已登记项**，不做全仓语义去重。

**不**做什么：不判「代码该不该存在」（那是人的裁定）、不设默认阈值基线、不新增 required check。

## 口径（可复算）

- 排除目录：`node_modules` / `.venv` / `target` / `__pycache__` / `.next`，外加 `.git`
  （VCS 元数据，不是源码）。
- 注释判定（**行首**形态：`strip()` 之后）：
  - Java / TS：`//`、`/*`、`*`（块注释续行）。
  - Python：`#`；以及**三引号块**（`\"\"\"` / `'''`，含 docstring）——行首开块 ⇒ 块内每行都算注释。
- **空行优先**：空白行一律计入「空行」，即使它落在三引号块内（口径固定，一行只记一次）。
- churn 不可用（非 git 目录 / `git` 不在 PATH）⇒ **不谎报 0**：表中 churn 记 `-` 并附原因，
  退出码不受影响（三张表里只有它降级，其余读数仍然有效）。
- 读不到（root 不存在 / 不是目录）或源码文件集合为空 ⇒ 退出码 `3`（fail-closed，
  **不得**把「0 个」当正常读数）。

## 退出码（三态）

| 码 | 含义 |
|---|---|
| `0` | 正常（无超阈值项） |
| `1` | 有超阈值项（仅当显式给 `--max-file-lines` / `--max-dir-lines`）或登记表有漂移/缺副本 —— 报告型，**不拦合并** |
| `3` | 无法判定（工作树读不到 / 源码文件集合为空） |

## 用法

    python3 scripts/code_mass_report.py                        # 三张表
    python3 scripts/code_mass_report.py --json                 # 机读（判据 / CI 消费）
    python3 scripts/code_mass_report.py --max-file-lines 8000  # 显式阈值 ⇒ 超了 exit 1
    python3 scripts/code_mass_report.py --no-churn             # 跳过 git（夹具 / 非 git 目录）
    python3 scripts/code_mass_report.py --skip-registry        # 临时夹具无法核对登记表时显式跳过

## 边界（照实登记）

- 注释判定是**行首启发式**：行尾注释、字符串里的 `//` / `#`、Java 块注释里的空行都不细分；
  docstring 首行与收尾行都计入注释。
- churn 是「最近 N 次提交里出现过几次」，**不区分增删行数**；rename 只按新路径计数。
- 重复源登记表只覆盖**有意登记的副本**（当前是三端逐字节复制的 TS 文件），不是全仓语义去重。
- 阈值默认 **0 = 关闭**（issue #8165 的边界：不设阈值基线）⇒ 平常跑 exit 0；超阈值是**人显式要的**。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SOURCE_SUFFIXES = (".java", ".py", ".ts", ".tsx")
EXCLUDED_DIRS = frozenset({"node_modules", ".venv", "target", "__pycache__", ".next", ".git"})

EXIT_OK = 0
EXIT_FLAGGED = 1
EXIT_UNDECIDABLE = 3

# 重复事实源登记表：**事实源 → 副本**（只裁已登记项，不是全仓语义去重）。
# 每条的判据 = 副本存在 ∧ 与源**逐字节一致**；漂移 / 缺副本即列为项（exit 1）。
REGISTRY = (
    {
        "fact": "工艺规格展示映射（craft spec display）",
        "source": "frontend/admin-web/src/lib/craft-display.ts",
        "copies": (
            "frontend/mini-app/src/utils/craft-display.ts",
            "frontend/bmini-app/src/utils/craft-display.ts",
        ),
        "why": "文件头自称「单一真值定义，多处渲染共用」，实际是逐字节复制到两个小程序端",
    },
    {
        "fact": "SSE 流式客户端（小程序端）",
        "source": "frontend/mini-app/src/utils/sse.ts",
        "copies": ("frontend/bmini-app/src/utils/sse.ts",),
        "why": "小程序与 bmini 两端各一份实现，需保持同一份事件解析口径",
    },
    {
        "fact": "敏感信息脱敏（mask）",
        "source": "frontend/mini-app/src/utils/mask.ts",
        "copies": ("frontend/bmini-app/src/utils/mask.ts",),
        "why": "脱敏口径是合规面，两端逐字节复制",
    },
    {
        "fact": "确认卡（ConfirmCard）",
        "source": "frontend/mini-app/src/components/cards/ConfirmCard.tsx",
        "copies": ("frontend/bmini-app/src/components/cards/ConfirmCard.tsx",),
        "why": "端上交互卡逐字节复制",
    },
)


def count_source_text(text: str, kind: str) -> dict:
    """数一段源码文本的总行 / 注释行 / 空行 / 逻辑行（口径见模块 docstring）。

    `kind` ∈ `{"py", "jvm"}`：`jvm` = Java / TS / TSX（同一套行首注释形态）。
    """
    total = comment = blank = 0
    triple = ""  # Python：当前未闭合的三引号定界符（空 = 不在块内）
    for raw in text.splitlines():
        total += 1
        stripped = raw.strip()
        if not stripped:  # 空行优先：块内空白也算空行
            blank += 1
            continue
        if kind == "py":
            if triple:
                comment += 1
                if triple in stripped:
                    triple = ""
                continue
            if stripped.startswith("#"):
                comment += 1
                continue
            opened = next((d for d in ('"""', "'''") if stripped.startswith(d)), "")
            if opened:
                comment += 1
                if stripped.count(opened) == 1:  # 同一行没闭合 ⇒ 进入块内
                    triple = opened
            continue
        if stripped.startswith(("//", "/*", "*")):
            comment += 1
    return {"total": total, "comment": comment, "blank": blank, "logic": total - comment - blank}


def scan_source_files(root: Path) -> tuple[list[dict], list[str]]:
    """→ (文件读数列表, 读不到的项)。排除目录见 `EXCLUDED_DIRS`。"""
    files: list[dict] = []
    errors: list[str] = []

    def _onerror(exc: OSError) -> None:
        errors.append(f"{exc}")

    for dirpath, dirnames, filenames in os.walk(root, onerror=_onerror):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS)
        for name in sorted(filenames):
            suffix = os.path.splitext(name)[1]
            if suffix not in SOURCE_SUFFIXES:
                continue
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                errors.append(f"{rel}: {exc}")
                continue
            counts = count_source_text(text, "py" if suffix == ".py" else "jvm")
            files.append({"path": rel, "dir": rel.rsplit("/", 1)[0] if "/" in rel else ".", **counts})
    return files, errors


def aggregate_layers(files: list[dict]) -> list[dict]:
    """按目录聚合（降序：总行），逻辑行恒等式在聚合后仍成立。"""
    layers: dict[str, dict] = {}
    for item in files:
        row = layers.setdefault(
            item["dir"],
            {"dir": item["dir"], "files": 0, "total": 0, "comment": 0, "blank": 0, "logic": 0},
        )
        row["files"] += 1
        for key in ("total", "comment", "blank", "logic"):
            row[key] += item[key]
    return sorted(layers.values(), key=lambda row: (-row["total"], row["dir"]))


def parse_name_only(text: str) -> Counter:
    """`git log --name-only --pretty=format:` 的输出 → {路径: 出现提交数}。空行忽略。"""
    counts: Counter = Counter()
    for line in text.splitlines():
        path = line.strip()
        if path:
            counts[path] += 1
    return counts


def compute_churn(root: Path, commits: int) -> tuple[Counter | None, str]:
    """最近 `commits` 次提交的路径出现次数；不可用 ⇒ (None, 原因)，**不谎报 0**。"""
    cmd = ["git", "-C", str(root), "log", f"-{commits}", "--name-only", "--pretty=format:"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"git 不可用：{exc}"
    if proc.returncode != 0:
        return None, f"git log 失败（rc={proc.returncode}）：{proc.stderr.strip()[:200]}"
    return parse_name_only(proc.stdout), ""


def largest_files(files: list[dict], churn: Counter | None, top: int) -> list[dict]:
    rows = sorted(files, key=lambda item: (-item["total"], item["path"]))[: max(top, 0)]
    out = []
    for item in rows:
        row = dict(item)
        row["churn"] = None if churn is None else churn.get(item["path"], 0)
        out.append(row)
    return out


def _read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def _describe_difference(src: bytes | None, copy: bytes | None) -> str:
    if src is None:
        return "源文件缺失"
    if copy is None:
        return "副本缺失"
    src_lines = src.decode("utf-8", "replace").splitlines()
    copy_lines = copy.decode("utf-8", "replace").splitlines()
    for no, (left, right) in enumerate(zip(src_lines, copy_lines), 1):
        if left != right:
            return f"第 {no} 行起不同（源 {len(src_lines)} 行 / 副本 {len(copy_lines)} 行）"
    return f"行数不同（源 {len(src_lines)} 行 / 副本 {len(copy_lines)} 行）"


def check_duplicates(root: Path, registry=REGISTRY) -> list[dict]:
    """逐条核登记表：副本存在 + 与源**逐字节一致**。不一致/缺失的给出位置说明。"""
    results: list[dict] = []
    for item in registry:
        source_bytes = _read_bytes(root / item["source"])
        for copy_rel in item["copies"]:
            copy_bytes = _read_bytes(root / copy_rel)
            identical = (
                source_bytes is not None and copy_bytes is not None and source_bytes == copy_bytes
            )
            results.append(
                {
                    "fact": item["fact"],
                    "source": item["source"],
                    "copy": copy_rel,
                    "source_exists": source_bytes is not None,
                    "copy_exists": copy_bytes is not None,
                    "identical": identical,
                    "detail": "" if identical else _describe_difference(source_bytes, copy_bytes),
                }
            )
    return results


def build_report(
    root,
    *,
    top: int = 20,
    churn_commits: int = 400,
    max_file_lines: int = 0,
    max_dir_lines: int = 0,
    registry=REGISTRY,
    with_registry: bool = True,
) -> dict:
    """三张表的读数。`status` ∈ `{"ok", "flagged", "undecidable"}`（见 `exit_code_for`）。"""
    root = Path(root).resolve()
    if not root.is_dir():
        return {"status": "undecidable", "root": str(root), "reason": f"工作树读不到：{root} 不是目录"}

    files, errors = scan_source_files(root)
    if not files:
        return {
            "status": "undecidable",
            "root": str(root),
            "reason": "源码文件集合为空（.java/.py/.ts/.tsx 一个都没扫到）",
            "errors": errors,
        }

    if churn_commits > 0:
        churn, churn_reason = compute_churn(root, churn_commits)
    else:
        churn, churn_reason = None, "未计算（--no-churn）"

    layers = aggregate_layers(files)
    totals = {
        key: sum(item[key] for item in files) for key in ("total", "comment", "blank", "logic")
    }
    totals["files"] = len(files)

    duplicates = check_duplicates(root, registry) if with_registry else []

    flags: list[dict] = []
    if max_file_lines > 0:
        for item in files:
            if item["total"] > max_file_lines:
                flags.append(
                    {
                        "kind": "file_lines",
                        "path": item["path"],
                        "value": item["total"],
                        "threshold": max_file_lines,
                    }
                )
    if max_dir_lines > 0:
        for row in layers:
            if row["total"] > max_dir_lines:
                flags.append(
                    {
                        "kind": "dir_lines",
                        "dir": row["dir"],
                        "value": row["total"],
                        "threshold": max_dir_lines,
                    }
                )
    for item in duplicates:
        if item["identical"]:
            continue
        flags.append(
            {
                "kind": "duplicate_drift" if item["copy_exists"] else "duplicate_missing",
                "fact": item["fact"],
                "source": item["source"],
                "copy": item["copy"],
                "detail": item["detail"],
            }
        )

    return {
        "status": "flagged" if flags else "ok",
        "root": str(root),
        "scanned_files": len(files),
        "totals": totals,
        "layers": layers,
        "largest": largest_files(files, churn, top),
        "churn": {
            "commits": churn_commits,
            "available": churn is not None,
            "reason": churn_reason,
        },
        "duplicates_checked": bool(with_registry),
        "duplicates": duplicates,
        "flags": flags,
        "errors": errors,
    }


def exit_code_for(report: dict) -> int:
    return {"ok": EXIT_OK, "flagged": EXIT_FLAGGED, "undecidable": EXIT_UNDECIDABLE}.get(
        report.get("status"), EXIT_UNDECIDABLE
    )


def _print_table(header: list[str], rows: list[list], align_right: set[int]) -> None:
    widths = [len(str(cell)) for cell in header]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(str(cell)))
    widths = [min(width, 96) for width in widths]

    def _fmt(row: list) -> str:
        cells = []
        for idx, cell in enumerate(row):
            text = str(cell)
            text = text[: widths[idx]] if len(text) > widths[idx] else text
            cells.append(text.rjust(widths[idx]) if idx in align_right else text.ljust(widths[idx]))
        return "  ".join(cells).rstrip()

    print(_fmt(header))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print(_fmt(row))


def print_report(report: dict) -> None:
    if report["status"] == "undecidable":
        print("⚠ 无法判定（fail-closed，不输出「0 个」当正常）：")
        print(f"  root = {report['root']}")
        print(f"  原因 = {report['reason']}")
        for err in report.get("errors", []):
            print(f"  读不到：{err}")
        return

    churn = report["churn"]
    churn_note = (
        f"churn 可用（最近 {churn['commits']} 次提交）"
        if churn["available"]
        else f"churn 不可用：{churn['reason']}"
    )
    print(f"代码体量报告 —— root = {report['root']}")
    print(f"扫描 {report['scanned_files']} 个源码文件（.java/.py/.ts/.tsx）；{churn_note}")
    print()

    print("① 分层体量（按目录；逻辑行 = 总行 − 注释 − 空行）")
    rows = [
        [row["dir"], row["files"], row["total"], row["comment"], row["blank"], row["logic"]]
        for row in report["layers"]
    ]
    totals = report["totals"]
    rows.append(["合计", totals["files"], totals["total"], totals["comment"], totals["blank"], totals["logic"]])
    _print_table(["目录", "文件", "总行", "注释", "空行", "逻辑"], rows, {1, 2, 3, 4, 5})
    print()

    print(f"② 大文件 × churn（行数 top {len(report['largest'])}；churn = 最近 N 次提交里出现的次数）")
    rows = [
        [item["path"], item["total"], item["comment"], item["logic"],
         "-" if item["churn"] is None else item["churn"]]
        for item in report["largest"]
    ]
    _print_table(["文件", "总行", "注释", "逻辑", "churn"], rows, {1, 2, 3, 4})
    print()

    if not report["duplicates_checked"]:
        print("③ 重复事实源核对：**已显式跳过**（--skip-registry）—— 这里的空不是通过")
    else:
        print(f"③ 重复事实源核对（已登记 {len(report['duplicates'])} 条 源→副本）")
        rows = []
        for item in report["duplicates"]:
            verdict = "一致" if item["identical"] else "不一致"
            rows.append([item["fact"], item["copy"], verdict, item["detail"]])
        _print_table(["事实源", "副本", "判定", "差异"], rows, set())
    print()

    if report["flags"]:
        print(f"⚠ 有超阈值项 / 登记项不一致（{len(report['flags'])} 项，报告型——不拦合并）：")
        for flag in report["flags"]:
            if flag["kind"] == "file_lines":
                print(f"  · 文件过大 {flag['path']}：{flag['value']} 行 > 阈值 {flag['threshold']}")
            elif flag["kind"] == "dir_lines":
                print(f"  · 目录过大 {flag['dir']}：{flag['value']} 行 > 阈值 {flag['threshold']}")
            else:
                print(f"  · {flag['kind']}：{flag['fact']} → {flag['copy']}（{flag['detail']}）")
    else:
        print("✅ 无超阈值项（阈值默认关闭；未核对到的项已在上面留白）")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="代码体量 / churn / 重复事实源只读报告（issue #8165）")
    parser.add_argument("--root", default=str(REPO_ROOT), help="工作树根目录（默认：本脚本所在仓库）")
    parser.add_argument("--json", action="store_true", help="输出机读 JSON（否则三张人读表）")
    parser.add_argument("--top", type=int, default=20, help="大文件榜条数（默认 20）")
    parser.add_argument("--churn-commits", type=int, default=400, help="churn 窗口提交数（默认 400）")
    parser.add_argument("--no-churn", action="store_true", help="跳过 git（夹具 / 非 git 目录）")
    parser.add_argument("--max-file-lines", type=int, default=0, help="单文件总行阈值（0 = 关闭，默认）")
    parser.add_argument("--max-dir-lines", type=int, default=0, help="目录总行阈值（0 = 关闭，默认）")
    parser.add_argument(
        "--skip-registry", action="store_true", help="显式跳过重复事实源登记表（临时夹具用）"
    )
    args = parser.parse_args(argv)

    report = build_report(
        args.root,
        top=args.top,
        churn_commits=0 if args.no_churn else args.churn_commits,
        max_file_lines=args.max_file_lines,
        max_dir_lines=args.max_dir_lines,
        with_registry=not args.skip_registry,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)
    return exit_code_for(report)


if __name__ == "__main__":
    sys.exit(main())
