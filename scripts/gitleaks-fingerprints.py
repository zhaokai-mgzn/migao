#!/usr/bin/env python3
"""`.gitleaksignore` 指纹的**重算 / 校验**入口（issue #6197 的承载体工具）。

## 治的形态（实测两次）

`Secret Scan (gitleaks)` 判的是 PR 的**新增行**。验收承载体里的**测试夹具值**
（dev 测试 key `lb-…` / 本机 mock key `fsp-S3-…` / 被测件随机 hex `qr_token`·`part_token`）
会被默认规则的 `generic-api-key` 逐条误报，故按本仓既有形态（`.gitleaksignore` 的
`<commit>:<file>:<rule>:<line>` 指纹）登记豁免。

**但指纹绑定 commit SHA**：任何 **rebase / amend 都会让它整体失效**，11 处重新判红
（2026-10-03 实测：承载体 PR 两次 rebase ⇒ 两次手工重算）。⇒ 本脚本把那次手工动作降成
**一条命令**，并让「失效」在 CI 里**必然出声**（而不是靠人记得）。

## 为什么不改成路径 / 值级 allowlist

试过并**本地实测无效或过宽**（写入本文件，免得后人重走）：
- `.gitleaks.toml` 的 `paths = ["acceptance/.*"]`：gitleaks 8.24.3 在 git-history 扫描下
  **不生效**（单变量复算：清空 `.gitleaksignore` + 该 config ⇒ 仍 `leaks found: 11`）。
- 值级 `regexes` / `stopwords`：会把**仓库其余路径**的同形态值一并放行（刻意不做）。
⇒ 保留**精确**指纹，另配本工具 + 元守卫（`tests/unit_ci_workflows/test_gitleaks_ignore_hygiene.py`）。

## 用法

    ./scripts/gitleaks-fingerprints.py                 # 校验（默认 base = merge-base origin/main）
    ./scripts/gitleaks-fingerprints.py --apply         # 重算并写回 .gitleaksignore
    ./scripts/gitleaks-fingerprints.py --base <ref>    # 换基准
    ./scripts/gitleaks-fingerprints.py --print-only    # 只打印应加 / 应删，不判红（人读用）

**退出码**：`0` 一致 / `1` 不一致（应加 / 应删非空）/ `3` 无法判定（无 gitleaks、无报告、base 取不到）。
⚠️ `3` **不得当 0 读** —— 那是「没判」，不是「通过」。
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
from pathlib import Path

REPO_ROOT = Path(os.environ.get("GITLEAKS_FP_ROOT") or Path(__file__).resolve().parents[1]).resolve()
IGNORE = REPO_ROOT / ".gitleaksignore"
#: 指纹形态：`<commit>:<file>:<rule>:<line>`（本仓既有形态；见 #5528 / #6278）
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{7,64}:[^:]+:[^:]+:\d+$")
#: 注释行（`#` 开头）不进指纹集，但**保留**在文件里（说明为什么豁免）
COMMENT_RE = re.compile(r"^\s*#")


def _die(msg: str, code: int = 3) -> None:
    print(f"⛔ {msg}", file=sys.stderr)
    raise SystemExit(code)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True,
                          text=True, check=True).stdout.strip()


def default_base() -> str:
    """默认基准 = `origin/main` 与 HEAD 的 merge-base（取不到则 origin/main）。"""
    try:
        return _git("merge-base", "origin/main", "HEAD")
    except subprocess.CalledProcessError:
        return "origin/main"


def read_ignore() -> tuple[list[str], list[str]]:
    """返回 (指纹行, 全部行)。指纹行按出现顺序，去重保序。"""
    lines = IGNORE.read_text(encoding="utf-8").splitlines()
    seen, fps = set(), []
    for ln in lines:
        s = ln.strip()
        if not s or COMMENT_RE.match(s):
            continue
        if s not in seen:
            seen.add(s)
            fps.append(s)
    return fps, lines


def scan(base: str) -> list[str]:
    """对 `base^..HEAD` 跑 gitleaks，返回命中的指纹（升序去重）。取不到读数 ⇒ code 3。"""
    exe = shutil.which("gitleaks")
    if not exe:
        _die("找不到 gitleaks —— 无法判定（本工具不猜读数；装法见 .github/workflows/pr-check.yml）")
    try:
        head = _git("rev-parse", "HEAD")
        parent = _git("rev-parse", f"{base}^")
    except subprocess.CalledProcessError:
        _die(f"取不到 `{base}` 的父提交 —— 无法判定（base 传错时不许当『无命中』读）")
    with tempfile.TemporaryDirectory() as td:
        report = Path(td) / "gl.json"
        proc = subprocess.run(
            [exe, "detect", "--no-banner", "--report-format=json", f"--report-path={report}",
             "--log-opts", f"--no-merges --first-parent {parent}..{head}"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        if not report.exists():
            _die(f"gitleaks 没产出报告（rc={proc.returncode}）⇒ 无法判定\n{proc.stderr[-400:]}")
        findings = json.loads(report.read_text(encoding="utf-8") or "[]")
    return sorted({f"{f['Commit']}:{f['File']}:{f['RuleID']}:{f['StartLine']}" for f in findings})


def split_keep_comments(lines: list[str]) -> tuple[list[str], list[str]]:
    """把「注释及空行」与「指纹行」分开（写回时注释留在原位、指纹统一附在末尾）。"""
    comments = [ln for ln in lines if not ln.strip() or COMMENT_RE.match(ln.strip())]
    return comments, [ln.strip() for ln in lines if ln.strip() and not COMMENT_RE.match(ln.strip())]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=".gitleaksignore 指纹重算 / 校验（issue #6197）")
    ap.add_argument("--base", default=None, help="基准 ref（默认 merge-base origin/main HEAD）")
    ap.add_argument("--apply", action="store_true", help="重算并写回 .gitleaksignore")
    ap.add_argument("--print-only", action="store_true", help="只打印差异，不判红")
    args = ap.parse_args(argv)

    # 先查 gitleaks 在不在（缺工具时先跑 git 会把「没判」误报成 git 的崩溃读数）
    if not shutil.which("gitleaks"):
        _die("找不到 gitleaks —— 无法判定（本工具不猜读数；装法见 .github/workflows/pr-check.yml）")
    if not IGNORE.exists():
        _die(f"{IGNORE.relative_to(REPO_ROOT)} 不存在")
    base = args.base or default_base()
    found = set(scan(base))
    recorded, raw_lines = read_ignore()
    recorded_set = set(recorded)

    missing = sorted(found - recorded_set)      # 命中但未登记 ⇒ CI 会红
    stale = sorted(recorded_set - found)        # 已登记但本轮不再命中（rebase 后）
    print(f"基准 base = {base[:12]}｜命中 {len(found)} 处｜已登记 {len(recorded)} 条")
    if missing:
        print(f"\n应加（{len(missing)} 条）：")
        for fp in missing:
            print(f"  {fp}")
    if stale:
        print(f"\n应删（{len(stale)} 条，rebase/amend 后失效）：")
        for fp in stale:
            print(f"  {fp}")

    if missing or stale:
        print("\n⇒ 复算命令（与 CI 同参数）：")
        print(f"  ./scripts/gitleaks-fingerprints.py --base {base} --apply")
    else:
        print("✅ 指纹与实际命中一致")

    if args.print_only:
        return 1 if (missing or stale) else 0
    if args.apply:
        comments, _ = split_keep_comments(raw_lines)
        out = [ln for ln in comments if ln.strip()] + sorted(found)
        IGNORE.write_text("\n".join(out) + "\n", encoding="utf-8")
        print(f"✅ 已写回 .gitleaksignore（{len(found)} 条指纹）")
        return 0
    return 1 if (missing or stale) else 0


if __name__ == "__main__":
    raise SystemExit(main())
