# case_ids: MC-012
"""`scripts/deps-lock-regen.sh` 的判据（issue #7688）。

## 病根（2026-10-25 一晚复现 5 次）

dependabot（与本机 node 24/npm 11）生成的 `package-lock.json` 比 CI 期望的少一批条目，而 admin-web
相关腿跑 **node 20.20.2 / npm 10.8.2** ⇒ `npm ci` 直接 `EUSAGE: … not in sync` ⇒ 三条腿全红；
更坑的是 **`gh pr update-branch` 会把补齐的条目再吃掉**（lock 冲突取 main 侧）⇒
「修 lock → update-branch → 又红」的死循环。

⇒ 两件事必须钉在**一条命令**里且**顺序固定**（铁律 10：一晚 ≥3 次的动作串要收敛成命令）：
① 先 `update-branch`；② **等远端 ref 真的前进**（issue #8843）；③ 快进拉取；④ 用 CI 那个 npm 版本
重生成 lock；⑤ 自证 `npm ci --dry-run` 通过才许推。

## 判据（本文件）

1. `--print-plan` 打印的步骤顺序必须 = 上面 ①②③④⑤（顺序即安全顺序）；
2. 当前分支 ≠ PR head ⇒ 拒绝（不许改到别的工作区）；
3. PR 没改任何 `package-lock.json` ⇒ 拒绝（不许拿它当通用 update-branch）；
4. 脚本本身要存在且可执行；
5. **issue #8843**：`gh pr update-branch` 是**异步**的 ⇒ `--print-plan` 必须含「等远端前进」，
   且脚本里 `git ls-remote` 轮询必须在 `git merge --ff-only` **之前**；裸 `git pull` 一律不许再出现
   （实测：它拿到旧 head ⇒ 本地在旧 head 上提交 ⇒ push 被 `(fetch first)` 拒，甚至让 lock 内容冲突）。

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


# ── issue #8843：`gh pr update-branch` 是**异步**的，必须等远端 ref 前进 ──────────
def test_plan_includes_remote_advance_wait_before_pull(tmp_path: Path):
    """顺序：update-branch → **等远端前进** → 快进拉取。

    红证（注入式）：把 `--print-plan` 里那行「git ls-remote 轮询等远端 ref 前进」删掉
    ⇒ 本断言 `min(i_update, i_wait, i_merge) > 0` 当场红。
    """
    r = _run(tmp_path, "8843", "--print-plan", branch="dependabot/x", dirs="frontend/admin-web")
    assert r.returncode == 0, r.stderr
    plan = r.stdout
    i_update = plan.find("gh pr update-branch")
    i_wait = plan.find("ls-remote")
    i_merge = plan.find("merge --ff-only")
    assert min(i_update, i_wait, i_merge) > 0, plan
    assert i_update < i_wait < i_merge, (
        "update-branch → **等远端前进** → 快进拉取 的顺序被改了：不等就会拿到旧 head，"
        "push 必被 `(fetch first)` 拒绝（issue #8843）：\n" + plan
    )


def test_script_never_pulls_right_after_update_branch():
    """静态守卫：脚本里不许再出现裸 `git pull`（issue #8843 的缺陷形态）。"""
    src = SCRIPT.read_text(encoding="utf-8")
    code_lines = [ln.strip() for ln in src.splitlines() if not ln.strip().startswith("#")]
    offending = [ln for ln in code_lines if ln.startswith("git pull")]
    assert offending == [], (
        "脚本里又出现裸 `git pull`：update-branch 是异步的，pull 会拿到旧 head ⇒ push 被拒（issue #8843）："
        + repr(offending)
    )
    i_ls = src.find("git ls-remote")
    i_merge = src.find("git merge --ff-only")
    assert 0 < i_ls < i_merge, "ls-remote 轮询必须出现在 merge --ff-only 之前（issue #8843）"


# ── issue #8843（第二个实测）：提交身份必须来自白名单，不许写死虚构身份 ──────────
def test_script_does_not_hardcode_a_commit_identity():
    """脚本**不许**用 `-c user.name/user.email` 写死身份（实测 #8830 被作者守卫判红）。

    红证（注入式）：把 `git -c user.name="migao-deps-lockfix" -c user.email="noreply@migao.local" commit …`
    加回脚本 ⇒ 本断言当场红，并指名它是 `.github/external-authorship-allow.json` 之外的身份。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    code_lines = [ln.strip() for ln in src.splitlines() if not ln.strip().startswith("#")]
    offenders = [
        ln for ln in code_lines
        if 'user.name="' in ln or 'user.email="' in ln
    ]
    assert offenders == [], (
        "脚本用写死身份提交 ⇒ External Authorship Guard / Contribution Gate 按提交作者判红 "
        f"（实测 PR #8830）：{offenders!r}"
    )
    assert "git config user.email" in src, (
        "缺前置自证：没有配置 user.email 时必须出声退出，不许静默用虚构身份提交"
    )
