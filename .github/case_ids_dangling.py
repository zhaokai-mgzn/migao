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
| `0` | 全库**无**悬空引用，且与基线台账（`.github/case-ids-dangling-baseline.json`）**相等** |
| `1` | **有**悬空引用 / 基线判据不满足（**报告面**照列全貌；**阻塞面** = `tests/unit_ci_workflows/test_case_ids_dangling_report.py` 的 D7） |
| `3` | 无法判定（用例库读不到 / git 不可用 / 扫描面为空）—— **不得当 0 读** |

## 两面：报告（不阻塞）+ 基线（**新增即红，只许缩短**）

| 面 | 谁承担 | 行为 |
|---|---|---|
| 报告 | 本工具输出 + `docs/testing/case-ids-dangling.md` | 列出全貌，**不拦** |
| 基线 | `.github/case-ids-dangling-baseline.json` + `baseline_violations()`（**唯一实现**） | 实测 **>** 基线 ⇒ **红**（新增即红）；实测 **<** 基线 ⇒ **红**（要求同批下沉）；`history` 出现回升 ⇒ **红**（基线不得放宽） |

🔴 **为什么必须有基线这一面**（裁定 2026-11-03）：批合工具会把 main 上**已合入**的号也改掉 ⇒
悬空引用会**继续产生**；只 warn 的报告面 = 没人看 = 等于没有。「新增即红」才是唯一能拦住下一次的机制。

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
BASELINE_PATH = REPO_ROOT / ".github" / "case-ids-dangling-baseline.json"
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


def load_baseline(path: Path = BASELINE_PATH) -> dict:
    """读基线台账；缺失 / 不可解析 ⇒ `{}`（调用方**判红**，不得当 0 读）。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def baseline_violations(baseline: dict, actual: int) -> list[str]:
    """基线台账的**唯一判定实现**（阻塞面 = `test_case_ids_dangling_report.py` 的 D7）。

    三条规则（凡是条数**现取**，不写死）：
    1. **新增即红**：`actual > entries.dangling_total`；
    2. **只许缩短**：`actual < entries.dangling_total` ⇒ 要求同批下沉基线（`entries` + `history` 各追加一条）；
    3. **台账不得放宽 / 不得断链**：`history` 单调非增；`entries` 必须等于 `history` 末行。
    """
    problems: list[str] = []
    entries = baseline.get("entries") if isinstance(baseline, dict) else None
    history = baseline.get("history") if isinstance(baseline, dict) else None
    if not isinstance(entries, dict) or "dangling_total" not in entries:
        return ["基线台账未登记（缺 `entries.dangling_total`）⇒ **不得当 0 读**"]
    if not isinstance(history, list) or not history:
        return ["基线台账缺 `history` 读数链 ⇒ **不得当 0 读**（无法判断有没有放宽过）"]
    last = history[-1] if isinstance(history[-1], dict) else {}
    if "dangling_total" not in last:
        return ["`history` 末行缺 `dangling_total`"]
    if entries["dangling_total"] != last["dangling_total"]:
        problems.append(
            f"台账链断开：`entries.dangling_total` = {entries['dangling_total']}，"
            f"而 `history` 末行 = {last['dangling_total']}（两者必须相等）"
        )
    values = [row.get("dangling_total") for row in history if isinstance(row, dict)]
    for prev, cur in zip(values, values[1:]):
        if isinstance(prev, int) and isinstance(cur, int) and cur > prev:
            problems.append(f"**基线不得放宽**：`history` 出现 {prev} → {cur}（只许缩短）")
    expected = entries["dangling_total"]
    if isinstance(expected, int):
        if actual > expected:
            problems.append(
                f"**新增即红**：实测 {actual} 条 > 基线 {expected} 条 ⇒ "
                f"先修悬空引用（改测试文件头 / 补回用例块），不要调大基线"
            )
        elif actual < expected:
            problems.append(
                f"**只许缩短**：实测 {actual} 条 < 基线 {expected} 条 ⇒ 请**同批下沉**基线"
                f"（`entries.dangling_total` 改 {actual}，并在 `history` 追加一行带 note）"
            )
    return problems


def render_markdown(report: dict, *, generated_on: str, baseline_total: int | None = None) -> str:
    lines = [
        "# 用例 id 悬空引用清单（全库，报告型）",
        "",
        "> 🔴 **本文件是读数快照，不是门禁**：悬空引用**不阻塞合并**（可能是历史遗留）。"
        "变更集里的悬空引用由 `growth_gate.case_trace_check` **阻塞**（`QA Growth Gate` 腿）；"
        "**新增**的悬空引用由基线台账阻塞（新增即红，见下表）。",
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
        "| 全库 · 报告 | 本文件 + `.github/case_ids_dangling.py` | 悬空 ⇒ **只列出、不阻塞**（全貌） |",
        "| 全库 · 基线 | `.github/case-ids-dangling-baseline.json` + `baseline_violations()`（D7 断言） | **新增即红**；少于基线 ⇒ 要求同批下沉；`history` 回升 ⇒ **红**（不得放宽） |",
        "",
        f"基线台账现值：**{baseline_total if baseline_total is not None else '读不到'}** 条"
        "（实测必须与它相等 —— 多一条要修、少一条要同批下沉）。",
        "",
        "为什么需要它：**只改 YAML 的批次提交**（让号）可能在不碰测试文件的前提下新增悬空引用 ⇒ "
        "变更集判据看不见；报告面是**全貌**、基线面是**唯一的拦截机制**（只 warn = 没人看 = 等于没有）。",
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

    baseline = load_baseline()
    problems = baseline_violations(baseline, len(report["findings"]))

    if as_json:
        print(json.dumps({**report, "baseline_violations": problems}, ensure_ascii=False, indent=2))
    else:
        print(
            f"扫描 {report['scanned']} 个测试文件 / 用例库 {report['corpus']} 条 ⇒ "
            f"悬空引用 {len(report['findings'])} 条"
        )
        for f in report["findings"]:
            print(f"  · {f['file']}:{f['line']} 声明了不存在的用例 id {f['case_id']}（{f['last_commit']}）")
        for p in problems:
            print(f"  ❌ {p}")
        if report["findings"]:
            print("ℹ️ 报告面：全貌已列出（不阻塞合并）；变更集里的悬空由 QA Growth Gate 阻塞。")
        if not problems and not report["findings"]:
            print("✅ 与基线台账一致（新增即红 / 只许缩短两条规则都满足）。")

    if write_to is not None:
        from datetime import date

        target = write_to if write_to.is_absolute() else REPO_ROOT / write_to
        target.parent.mkdir(parents=True, exist_ok=True)
        entries = (baseline.get("entries") or {}) if isinstance(baseline, dict) else {}
        target.write_text(
            render_markdown(
                report,
                generated_on=date.today().isoformat(),
                baseline_total=entries.get("dangling_total"),
            ),
            encoding="utf-8",
        )
        print(f"✅ 已写 {target.relative_to(REPO_ROOT) if target.is_relative_to(REPO_ROOT) else target}")

    return EXIT_FOUND if (report["findings"] or problems) else EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main(sys.argv))
