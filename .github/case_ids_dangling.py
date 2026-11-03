#!/usr/bin/env python3
"""用例 id 悬空引用的**全库报告**（报告型：只列、不拦）—— issue #8310 收尾。

## 病（2026-11-03 现取，不是推断）

批合工具在替在飞 PR 让号时会改 `.github/cases/*.yml` 里的用例块 id
（`git show 1524f1ce2 -- .github/cases/misc.yml` 可逐字看到 `-  - id: MC-154` / `+  - id: MC-155`），
但它**改不到源码侧的 `// case_ids:` 头** ⇒ main 上出现「测试声明了一个用例库里不存在的 id」。

既有判据（`growth_gate.case_trace_check`）**只看变更集**：一个只改 YAML 的批次提交不会触发它，
悬空引用可以**潜伏**到下一个碰那个文件的 PR 才爆 —— 而那时判红会指向**那个无辜的 PR**。

## 本工具做什么

把「测试文件声明的 `case_ids` 是否都真的在用例库里」**全库**做一次，并写成人读清单
（`docs/testing/case-ids-dangling.md`）：

- 解析与判定**复用** `growth_gate`（`extract_case_ids` / `load_case_index` / `_is_test_file`），
  **不复制第二份实现**（口径漂移是本仓被点名过多次的形态）；
- 每条具名：`文件:行` + **悬空 id** + **最近一次改动该文件的 commit**（`git log -1`）；
- 🔴 **报告型、不阻塞**（裁定：可能是历史遗留）；**变更集**里的悬空仍由 `growth_gate` 阻塞。

## 用法与退出码（三态：0 / 1 / 3）

    python3 .github/case_ids_dangling.py                                  # 打印清单
    python3 .github/case_ids_dangling.py --write docs/testing/case-ids-dangling.md
    python3 .github/case_ids_dangling.py --json

| 退出码 | 含义 |
|---|---|
| `0` | 全库**无**悬空引用 |
| `1` | **有**悬空引用（报告型 —— 调用方**不得**当成失败门禁） |
| `3` | 无法判定（用例库读不到 / git 不可用 / 扫描面为空）—— **不得当 0 读** |

## 边界（照实登记，§19.1）

- 扫描面 = `growth_gate._is_test_file` 的同一口径（`.py` / `.java` / `.ts` / `.tsx` 且文件名含 test/spec）
  ⇒ `.mjs` / `.js` 判据（`frontend/worker-h5/tests/*.test.mjs`）**不在**面内（与阻塞型判据的口径一致）；
- `case_ids:` 的解析规则（前 50 行 / 首个声明 / 注释起始）**全部沿用** `extract_case_ids`，本工具不改它；
- 「最近一次改动该文件的 commit」是**文件级**读数（不是行级 blame）—— 只作**归因入口**，不作结论；
  批量合并后它可能指向那个批次提交（正是本工具要暴露的形态）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
CASES_DIR = REPO_ROOT / ".github" / "cases"
DEFAULT_OUT = REPO_ROOT / "docs" / "testing" / "case-ids-dangling.md"
EXIT_CLEAN, EXIT_FOUND, EXIT_UNDECIDABLE = 0, 1, 3


def _growth_gate():
    """按**路径**加载 `.github/growth_gate.py`（同名模块可能已在 sys.modules 里被别处加载）。"""
    import importlib.util

    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    spec = importlib.util.spec_from_file_location("growth_gate_for_dangling", HERE / "growth_gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tracked_files(repo_root: Path) -> list[str]:
    """仓库跟踪的文件（相对路径）。git 不可用 ⇒ 空列表（调用方判 3）。"""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z"],
            capture_output=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return [p for p in out.decode("utf-8", "replace").split("\0") if p]


def declaration_line(path: Path, case_id: str) -> int:
    """该 id 出现在声明行的**行号**（1-based；找不到 ⇒ 0）。只扫前 50 行 —— 与解析口径一致。"""
    gg = _growth_gate()
    try:
        head = path.read_text(encoding="utf-8").split("\n")[:50]
    except OSError:
        return 0
    for no, line in enumerate(head, 1):
        m = gg.CASE_IDS_RE.match(line)
        if not m:
            continue
        ids = [t.strip().strip("'\"") for t in m.group(1).split(",")]
        if case_id in ids:
            return no
    return 0


def last_commit_for(repo_root: Path, rel: str) -> str:
    """最近一次改动该文件的 commit（`<短 sha> <YYYY-MM-DD>`）；未提交 / 无历史 ⇒ `未提交`。"""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "log", "-1", "--format=%h|%ad", "--date=short", "--", rel],
            capture_output=True,
            check=True,
        ).stdout.decode("utf-8", "replace").strip()
    except (OSError, subprocess.CalledProcessError):
        return "读不到"
    if not out:
        return "未提交"
    sha, _, date = out.partition("|")
    return f"`{sha}` {date}".strip()


def scan(repo_root: Path = REPO_ROOT, cases_dir: Path = CASES_DIR) -> dict:
    """全库扫描。返回 `{"status": str, "scanned": int, "corpus": int, "findings": [...]}`。"""
    gg = _growth_gate()
    index, err = gg.load_case_index(str(cases_dir))
    if err or not index:
        return {"status": "undecidable", "reason": err or "用例库为空", "scanned": 0, "corpus": 0, "findings": []}

    files = tracked_files(repo_root)
    if not files:
        return {"status": "undecidable", "reason": "git ls-files 读不到（不可判定）", "scanned": 0, "corpus": len(index), "findings": []}

    scanned = 0
    findings: list[dict] = []
    for rel in files:
        if not gg._is_test_file(rel):
            continue
        path = repo_root / rel
        if not path.is_file():
            continue
        declared = gg.extract_case_ids(str(path))
        if not declared:
            continue
        scanned += 1
        missing = [c for c in declared if c not in index]
        for case_id in missing:
            findings.append(
                {
                    "file": rel,
                    "line": declaration_line(path, case_id),
                    "case_id": case_id,
                    "last_commit": last_commit_for(repo_root, rel),
                }
            )
    if scanned == 0:
        return {"status": "undecidable", "reason": "扫描面为空（判据失明）", "scanned": 0, "corpus": len(index), "findings": []}
    return {
        "status": "found" if findings else "clean",
        "scanned": scanned,
        "corpus": len(index),
        "findings": findings,
    }


def render_markdown(report: dict, *, generated_on: str) -> str:
    lines = [
        "# 用例 id 悬空引用清单（全库，报告型）",
        "",
        "> 🔴 **本文件是读数快照，不是门禁**：悬空引用**不阻塞合并**（可能是历史遗留）。"
        "变更集里的悬空引用由 `growth_gate.case_trace_check` **阻塞**（`QA Growth Gate` 腿）。",
        "> 工具 = `.github/case_ids_dangling.py`（单一实现，解析规则全部复用 `growth_gate`）。",
        "",
        "## 本次读数",
        "",
        f"- 生成日期：**{generated_on}**",
        f"- 用例库：**{report['corpus']}** 条（`.github/cases/*.yml`）",
        f"- 扫描面：**{report['scanned']}** 个声明了 `case_ids` 的测试文件（`.py` / `.java` / `.ts` / `.tsx`，文件名含 test/spec）",
        f"- **悬空引用：{len(report['findings'])} 条**",
        "",
    ]
    if report["findings"]:
        lines += [
            "| 文件:行 | 悬空的 id | 最近一次改动该文件的 commit |",
            "|---|---|---|",
        ]
        for f in report["findings"]:
            lines.append(f"| `{f['file']}:{f['line']}` | `{f['case_id']}` | {f['last_commit']} |")
        lines += [
            "",
            "**怎么修**：① 若该用例被让号 / 重编号 ⇒ 把测试文件头改成用例库里**现存的** id；"
            "② 若该用例块被误删 ⇒ 补回用例块（走 `.github/cases/` 单一源 + 重渲染）。",
        ]
    else:
        lines.append("✅ 全库无悬空引用：每个测试文件声明的 `case_ids` 都能在用例库里找到对应用例。")
    lines += [
        "",
        "## 复算（零成本，一条命令）",
        "",
        "```bash",
        "python3 .github/case_ids_dangling.py            # 打印（退出码：0 无 / 1 有 / 3 无法判定）",
        "python3 .github/case_ids_dangling.py --write docs/testing/case-ids-dangling.md   # 重生成本文件",
        "```",
        "",
        "## 为什么需要这份全库读数（与既有判据的分工）",
        "",
        "| 面 | 判据 | 行为 |",
        "|---|---|---|",
        "| 变更集 | `growth_gate.case_trace_check`（`QA Growth Gate`，required） | 悬空 ⇒ **阻塞** |",
        "| 全库 | 本文件 + `.github/case_ids_dangling.py` | 悬空 ⇒ **只列出、不阻塞** |",
        "",
        "缺口（照实登记）：**只改 YAML 的批次提交**（让号）可能在不碰测试文件的前提下新增悬空引用 ⇒ "
        "变更集判据看不见；本清单是它的**可读承接面**（跑一次即现形），但**不自动**判红 —— "
        "要让「新增即红」成立需要一条 baseline 台账（未建，等裁定）。",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    args = argv[1:]
    as_json = "--json" in args
    write_to = None
    if "--write" in args:
        i = args.index("--write")
        write_to = Path(args[i + 1]) if i + 1 < len(args) else DEFAULT_OUT

    report = scan()
    if report["status"] == "undecidable":
        print(f"❓ 无法判定：{report['reason']}（不得当 0 读）", file=sys.stderr)
        return EXIT_UNDECIDABLE

    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"扫描 {report['scanned']} 个测试文件 / 用例库 {report['corpus']} 条 ⇒ "
            f"悬空引用 {len(report['findings'])} 条"
        )
        for f in report["findings"]:
            print(f"  · {f['file']}:{f['line']} 声明了不存在的用例 id {f['case_id']}（{f['last_commit']}）")
        if report["findings"]:
            print("ℹ️ 报告型 —— 不阻塞合并；变更集里的悬空由 QA Growth Gate 阻塞。")

    if write_to is not None:
        from datetime import date

        target = write_to if write_to.is_absolute() else REPO_ROOT / write_to
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_markdown(report, generated_on=date.today().isoformat()), encoding="utf-8")
        print(f"✅ 已写 {target.relative_to(REPO_ROOT) if target.is_relative_to(REPO_ROOT) else target}")

    return EXIT_FOUND if report["findings"] else EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main(sys.argv))
