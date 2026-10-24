# case_ids: MC-012
"""`scripts/deps-lock-regen.sh` 的判据（issue #7688）。

## 病根（2026-10-25 一晚复现 5 次）

dependabot（与本机 node 24/npm 11）生成的 `package-lock.json` 比 CI 期望的少一批条目，而 admin-web
相关腿跑 **node 20.20.2 / npm 10.8.2** ⇒ `npm ci` 直接 `EUSAGE: … not in sync` ⇒ 三条腿全红；
更坑的是 **`gh pr update-branch` 会把补齐的条目再吃掉**（lock 冲突取 main 侧）⇒
「修 lock → update-branch → 又红」的死循环。

⇒ 两件事必须钉在**一条命令**里且**顺序固定**（铁律 10：一晚 ≥3 次的动作串要收敛成命令）：
① 先 `update-branch`；② 再用 CI 那个 npm 版本重生成 lock；③ 自证 `npm ci --dry-run` 通过才许推。

## 判据（本文件）

1. `--print-plan` 打印的步骤顺序必须 = 上面 ①②③（顺序即安全顺序）；
2. 当前分支 ≠ PR head ⇒ 拒绝（不许改到别的工作区）；
3. PR 没改任何 `package-lock.json` ⇒ 拒绝（不许拿它当通用 update-branch）；
4. 脚本本身要存在且可执行。

零网络：`gh` 用临时 stub（`STUB_BRANCH` / `STUB_DIRS` 注入），`--print-plan` 只读元数据、不写任何东西。
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "deps-lock-regen.sh"

GH_STUB = """#!/usr/bin/env bash
# 极简 gh stub：只服务 `gh pr view <n> --json headRefName|files`
if [ "$1" = "pr" ] && [ "$2" = "view" ]; then
  case "$*" in
    *headRefName*) printf '%s\\n' "${STUB_BRANCH:-}" ;;
    *files*)       printf '%s\\n' ${STUB_DIRS:-} ;;
  esac
  exit 0
fi
echo "stub gh: 未支持的命令：$*" >&2
exit 1
"""


def _run(tmp_path: Path, *args: str, branch: str = "", dirs: str = "") -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "gh"
    stub.write_text(GH_STUB, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["STUB_BRANCH"] = branch
    env["STUB_DIRS"] = dirs
    return subprocess.run(
        ["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env, cwd=REPO, timeout=120,
    )


def test_script_is_executable():
    assert SCRIPT.is_file(), f"缺脚本：{SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), "脚本没有可执行位（约定 ./scripts/*.sh 可直接跑）"


def test_plan_pins_the_safe_order(tmp_path: Path):
    """顺序即安全顺序：update-branch → 重生成 lock → 自证 → 提交推送。"""
    r = _run(tmp_path, "7107", "--print-plan", branch="dependabot/x", dirs="frontend/admin-web")
    assert r.returncode == 0, r.stderr
    plan = r.stdout
    i_update = plan.find("gh pr update-branch")
    i_install = plan.find("install --package-lock-only")
    i_verify = plan.find("ci --dry-run")
    i_push = plan.find("git push")
    assert min(i_update, i_install, i_verify, i_push) > 0, plan
    assert i_update < i_install < i_verify < i_push, (
        "步骤顺序被改了 —— update-branch 必须**最先**（它会把之前补的 lock 条目吃掉），"
        "自证必须在推之前（推一条 npm10 读不了的 lock = 又一轮假红）：\n" + plan
    )


def test_refuses_when_current_branch_is_not_the_pr_head(tmp_path: Path):
    # 写盘档（--dry-run）必须拒绝错误分支；--print-plan 是只读档，只打印步骤
    r = _run(tmp_path, "7107", "--dry-run", branch="someone-else", dirs="frontend/admin-web")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "不是 PR" in (r.stdout + r.stderr)


def test_refuses_when_pr_touches_no_lockfile(tmp_path: Path):
    r = _run(tmp_path, "7107", "--print-plan", branch="dependabot/x", dirs="")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "package-lock.json" in (r.stdout + r.stderr) or "lock" in (r.stdout + r.stderr)


def test_unknown_mode_is_rejected(tmp_path: Path):
    r = _run(tmp_path, "7107", "--wat", branch="dependabot/x", dirs="frontend/admin-web")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "未知参数" in (r.stdout + r.stderr)
