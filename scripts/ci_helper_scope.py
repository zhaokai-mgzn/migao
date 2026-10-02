#!/usr/bin/env python3
"""ci_helper_scope.py — `Run ci workflow helper tests` 这一格**跑多大范围**的单一实现（issue #6015）。

## 治的形态

`ci workflow helper unit tests` 是 required 检查（不得有 workflow 级 `paths:` 过滤 ⇒ **每个 PR 都上报**），
于是**业务包的 PR 也要背整套研发模式/门禁判据集**（现取 358 个文件 / 冻结库存 5,767 条 / CI 实测 **7m52s**，
且它是 PR 反馈时长的**关键路径**）。用户 2026-10-02 裁定：**只做 CI 面分离**（不拆仓库）。

## 口径（三条，缺一不可）

1. **默认 always-run**：只有登记在 `tests/unit_ci_workflows/ci_execution_scope_ledger.json`
   的 `dev_only` 条目才让出；**没登记的一律照跑** ⇒ 新增判据不会因为漏登记而少跑（fail-closed 方向）。
2. **未命中研发面 ⇒ narrow**（跳过 dev_only），**必须显式打印「未跑 N 条」**——「没跑」必须长得像「没跑」。
3. **判不了 ⇒ full**：拿不到变更集（git 失败 / 空输出）一律跑全量，宁可贵，不许静默少跑。

## 用法

    python3 scripts/ci_helper_scope.py --decide        # 打印 full | narrow
    python3 scripts/ci_helper_scope.py --ignore-args   # narrow 用：每行一个 --ignore=<path>
    python3 scripts/ci_helper_scope.py --count         # dev_only 条数（打印「未跑 N 条」用）
    python3 scripts/ci_helper_scope.py --changed       # 打印判定依据（命中研发面的那几行），给人复算

环境变量 `MIGAO_CI_HELPER_SCOPE=full|narrow` 可**显式**覆盖判定（红证 / 排障用；非法值 ⇒ 不覆盖）。

三态退出码：`0` 判定成功 / `3` 无法判定（调用方**必须**按 full 处理）。
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
LEDGER_REL = "tests/unit_ci_workflows/ci_execution_scope_ledger.json"
TEST_DIR_REL = "tests/unit_ci_workflows"
#: 研发面的触发前缀 —— 与 `verify-all.sh` 的 `ci_helper_face_paths()` **同一口径**（同源，不写第二份规则）
DEV_FACE_PREFIXES = (".github/", "tests/unit_ci_workflows/")
MIN_WHY = 10
#: 全量命令的 argv（**单一来源**：CI 的 `Run ci workflow helper tests` 在 full 档用的就是它，
#: 同源契约判据 = tests/unit_ci_workflows/test_ci_helper_leg.py；narrow 档只是**追加** `--ignore=`）。
CANONICAL_ARGV = ("python", "-m", "pytest", TEST_DIR_REL, "-q", "--tb=short",
                  "-p", "no:cacheprovider", "-n", "4")


def load_ledger(path: pathlib.Path | None = None) -> dict:
    p = path or (REPO / LEDGER_REL)
    return json.loads(p.read_text(encoding="utf-8"))


def ledger_problems(ledger: dict, repo: pathlib.Path | None = None) -> list[str]:
    """台账自身的判据（纯函数，供元守卫注入式红证复用）。

    四条：① 不许清空 ② 条目 path 必须真实存在（幽灵即红）③ 每条必须写 why（≥10 字）
    ④ path 必须落在判据目录内（不许把别处的文件登记成 dev-only）。
    """
    root = repo or REPO
    bad: list[str] = []
    entries = ledger.get("dev_only")
    if not isinstance(entries, list) or not entries:
        return ["`dev_only` 为空 ⇒ 台账空转（清空台账不能消红）"]
    seen: set[str] = set()
    for e in entries:
        path = (e or {}).get("path") or ""
        why = ((e or {}).get("why") or "").strip()
        if not path.startswith(TEST_DIR_REL + "/"):
            bad.append(f"条目不在判据目录内：{path!r}")
            continue
        if path in seen:
            bad.append(f"重复登记：{path}")
        seen.add(path)
        if not (root / path).is_file():
            bad.append(f"幽灵条目（文件不存在）：{path}")
        if len(why) < MIN_WHY:
            bad.append(f"缺 why（<{MIN_WHY} 字，让出必须有理由）：{path}")
    return bad


def dev_face_hit(changed_files: list[str]) -> bool:
    """变更集是否命中研发面（与本地 `ci_helper_face_paths()` 同口径）。"""
    return any(f.startswith(DEV_FACE_PREFIXES) for f in changed_files)


def changed_files(repo: pathlib.Path | None = None, base: str = "origin/main") -> list[str] | None:
    """`base...HEAD` 的变更集；**取不到 ⇒ None**（调用方按 full 处理，fail-closed）。"""
    root = repo or REPO
    proc = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-only", f"{base}...HEAD"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return None
    files = [ln.strip() for ln in proc.stdout.split("\n") if ln.strip()]
    return files or None


def ignore_paths(ledger: dict) -> list[str]:
    """narrow 时要跳过的判据文件（= 台账 dev_only 逐条）。"""
    return [e["path"] for e in (ledger.get("dev_only") or []) if e.get("path")]


def decide(files: list[str] | None, ledger: dict | None = None, override: str | None = None) -> str:
    """`full` / `narrow`。**显式覆盖优先**；否则判不了（files 为 None 或台账坏）⇒ **full**。"""
    if override in ("full", "narrow"):
        return override
    if not files:
        return "full"
    if ledger_problems(ledger if ledger is not None else load_ledger()):
        return "full"
    return "full" if dev_face_hit(files) else "narrow"


def run_narrow() -> int:
    """narrow 档：以**同一份** canonical argv 起套件，只**追加** `--ignore=`（不写第二条命令）。"""
    ledger = load_ledger()
    verdict = decide(changed_files(), ledger, os.environ.get("MIGAO_CI_HELPER_SCOPE"))
    argv = list(CANONICAL_ARGV)
    if verdict == "narrow":
        ignored = ignore_paths(ledger)
        argv += [f"--ignore={p}" for p in ignored]
        print(f"⏭️ 未命中研发面 ⇒ 只跑 always-run 判据；**dev-only 判据未跑**：{len(ignored)} 条"
              f"（这不是「通过」）", flush=True)
    os.execvp(argv[0], argv)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="CI helper 腿的执行面判定（issue #6015）")
    ap.add_argument("--decide", action="store_true", help="打印 full | narrow")
    ap.add_argument("--ignore-args", action="store_true", help="打印 --ignore=<path>（每行一个）")
    ap.add_argument("--run-narrow", action="store_true",
                    help="narrow 档真起套件（同一份 canonical argv + --ignore=…）")
    ap.add_argument("--count", action="store_true", help="打印 dev_only 条数")
    ap.add_argument("--changed", action="store_true", help="打印命中研发面的变更行（判定依据）")
    ap.add_argument("--base", default="origin/main")
    args = ap.parse_args(argv)

    if args.run_narrow:
        return run_narrow()

    ledger = load_ledger()
    problems = ledger_problems(ledger)
    files = changed_files(base=args.base)
    override = os.environ.get("MIGAO_CI_HELPER_SCOPE")
    verdict = decide(files, ledger, override)

    if args.count:
        print(len(ignore_paths(ledger)))
        return 0
    if args.ignore_args:
        if verdict != "narrow":
            return 0
        for p in ignore_paths(ledger):
            print(f"--ignore={p}")
        return 0
    if args.changed:
        for f in (files or []):
            if f.startswith(DEV_FACE_PREFIXES):
                print(f)
        return 0
    if args.decide:
        print(verdict)
        if problems:
            print("⚠️ 台账判据不过 ⇒ 按 full 跑：" + "；".join(problems[:3]), file=sys.stderr)
        elif files is None:
            print("⚠️ 取不到变更集 ⇒ 按 full 跑（fail-closed）", file=sys.stderr)
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
