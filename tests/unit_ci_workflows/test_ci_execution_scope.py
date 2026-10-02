# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012）
r"""CI 执行面分离的**类级元守卫**（issue #6015）。

## 治的形态

`ci workflow helper unit tests` 是 required 检查（不得 workflow 级 `paths:` 过滤 ⇒ 每个 PR 都上报），
于是**业务包的 PR 也要背整套研发模式/门禁判据集**（现取 358 个文件 / 冻结库存 5,767 条 / CI 实测 7m52s，
且实测它是 PR 反馈时长的**关键路径**）。用户 2026-10-02 裁定：**只做 CI 面分离**（不拆仓库）。

## 它判什么（五条不变量，各能单独变红）

| # | 断言 | 回归时会怎么红 |
|---|---|---|
| 1 | 让出名单（`ci_execution_scope_ledger.json` 的 `dev_only`）**逐条真实存在**且**每条带 why（≥10 字）** | 幽灵条目 / 空 why ⇒ 红 |
| 2 | 台账**不许清空**（清空不能消红） | `dev_only: []` ⇒ 红 |
| 3 | 未命中研发面时生成的 `--ignore` 集合 **== `dev_only` 集合**（双向），且都在判据目录内 | 少让 / 多让 / 让到别处 ⇒ 红 |
| 4 | **默认 always-run**：不在台账里的判据文件**一律不被 ignore** | 有人把「漏登记」当成「自动让出」⇒ 红（这是本单 fail-closed 的方向） |
| 5 | **判不了 ⇒ full**：取不到变更集 / 台账判不过 ⇒ 跑全量 | 判定失败被读成「可以让出」⇒ 红 |

另有接线判据：CI 必须**同时**保留① 全量命令逐字（同源契约，parity）② 让出分支 + **未跑条数**打印。
判不了就少跑一条也不行 —— 「没跑」必须长得像「没跑」。

## 边界（照实登记）

- 元守卫只裁「**有没有登记 / 登记得说不说得通**」，**不为分类正确性背书**：把一条 business-facing 判据
  误登成 dev-only ⇒ 它在业务 PR 上就真的不跑了，**没有任何判据会红**。缓解 = ① 默认 always-run
  ② 每条 why 必须写清它判的对象 ③ 探针（路径证据）只用来**提名**、人来**复核**（本台账 58 提名 → 撤出 8 条业务面）。
- 本判据**不判** CI 真的跑得快了（那是读数，见 PR body 的 before/after）。
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
LEDGER_REL = "tests/unit_ci_workflows/ci_execution_scope_ledger.json"
TEST_DIR_REL = "tests/unit_ci_workflows"
CI_REL = ".github/workflows/pr-check.yml"
CANONICAL = "python -m pytest tests/unit_ci_workflows -q --tb=short -p no:cacheprovider -n 4"

sys.path.insert(0, str(REPO / "scripts"))
import ci_helper_scope as scope  # noqa: E402


def _ledger() -> dict:
    return json.loads((REPO / LEDGER_REL).read_text(encoding="utf-8"))


def _test_files() -> set[str]:
    return {f"{TEST_DIR_REL}/{p.name}" for p in (REPO / TEST_DIR_REL).glob("test_*.py")}


# ── 判据 1 / 2：台账自身 ──────────────────────────────────────────────────────
def test_ledger_entries_are_real_and_justified():
    assert scope.ledger_problems(_ledger(), REPO) == []


def test_empty_ledger_cannot_silence_the_guard():
    """清空台账不能消红（否则「没跑」可以靠删除登记来取得合法性）。"""
    assert scope.ledger_problems({"dev_only": []}, REPO)


def test_ghost_and_unjustified_entries_are_red():
    good = _ledger()["dev_only"][0]
    cases = {
        "幽灵条目": [dict(good, path=f"{TEST_DIR_REL}/test_never_existed_xyz.py")],
        "空 why": [dict(good, why="")],
        "短 why": [dict(good, why="因为")],
        "目录外": [dict(good, path="backend/x.py")],
    }
    for name, entries in cases.items():
        assert scope.ledger_problems({"dev_only": entries}, REPO), f"{name} 竟然没判红"


# ── 判据 3 / 4：让出集合 ──────────────────────────────────────────────────────
def test_ignore_set_equals_the_ledger_and_stays_inside_the_dir():
    ledger = _ledger()
    ignore = scope.ignore_paths(ledger)
    assert ignore == [e["path"] for e in ledger["dev_only"]], "让出集合与台账不双向相等"
    assert ignore, "让出集合为空 ⇒ 本条判据是空断言"
    for p in ignore:
        assert p.startswith(TEST_DIR_REL + "/") and (REPO / p).is_file(), p


def test_default_is_always_run():
    """**不在台账里 ⇒ 一律照跑**（新增判据不会因漏登记而少跑）。"""
    ignore = set(scope.ignore_paths(_ledger()))
    always = _test_files() - ignore
    assert always, "判据目录里应当有大量 always-run 判据"
    assert not (always & ignore)
    # 现取一条 always-run 的文件，确认它不在让出集合里（不是空断言）
    sample = sorted(always)[0]
    assert sample not in ignore


# ── 判据 5：判不了 ⇒ full ────────────────────────────────────────────────────
def test_undecidable_falls_back_to_full():
    assert scope.decide(None) == "full", "取不到变更集必须按 full（fail-closed）"
    assert scope.decide([]) == "full"
    assert scope.decide(["backend/x.py"], {"dev_only": []}) == "full", "台账判不过也必须 full"
    assert scope.decide(["backend/x.py"], _ledger()) == "narrow"
    assert scope.decide([".github/workflows/pr-check.yml"], _ledger()) == "full"
    assert scope.decide([f"{TEST_DIR_REL}/test_x.py"], _ledger()) == "full"


def test_face_prefixes_are_same_source_as_the_local_helper():
    """研发面口径与本地 `verify-all.sh` 的 `ci_helper_face_paths()` 同源（不写第二份规则）。"""
    sh = (REPO / "verify-all.sh").read_text(encoding="utf-8")
    for pref in scope.DEV_FACE_PREFIXES:
        assert pref in sh, f"本地 helper 腿的触发面里没有 {pref} —— 两侧口径漂移了"


# ── 接线：CI 真调它，且全量命令与「未跑」打印都在 ─────────────────────────────
def test_ci_wiring_keeps_full_command_and_prints_what_it_skipped():
    ci = (REPO / CI_REL).read_text(encoding="utf-8")
    assert "scripts/ci_helper_scope.py --decide" in ci, "CI 没有调用执行面判定（接线断了）"
    assert "--run-narrow" in ci, "narrow 档没有真的起套件"
    assert CANONICAL in ci, "全量命令被改写了 —— 同源契约（test_ci_helper_leg.py）会红"
    # 🔴 全量命令在 CI 里**只许出现一次**：出现两次会让同源契约判据抓到 narrow 那条（argv 漂移假红）。
    assert ci.count(CANONICAL) == 1, f"canonical 命令出现 {ci.count(CANONICAL)} 次（应为 1）"
    assert "未跑" in ci, "让出时必须打印未跑条数（「没跑」必须长得像「没跑」）"


def test_cli_count_and_override():
    n = subprocess.run([sys.executable, str(REPO / "scripts/ci_helper_scope.py"), "--count"],
                       capture_output=True, text=True, cwd=str(REPO), timeout=60)
    assert n.returncode == 0 and int(n.stdout.strip()) == len(_ledger()["dev_only"])
    narrow = subprocess.run([sys.executable, str(REPO / "scripts/ci_helper_scope.py"), "--ignore-args"],
                            capture_output=True, text=True, cwd=str(REPO), timeout=60,
                            env={**os.environ, "MIGAO_CI_HELPER_SCOPE": "narrow"})
    assert narrow.returncode == 0
    lines = [ln for ln in narrow.stdout.split("\n") if ln.startswith("--ignore=")]
    assert len(lines) == len(_ledger()["dev_only"]), f"override=narrow 时应让出全部 dev_only，实得 {len(lines)}"
    full = subprocess.run([sys.executable, str(REPO / "scripts/ci_helper_scope.py"), "--ignore-args"],
                          capture_output=True, text=True, cwd=str(REPO), timeout=60,
                          env={**os.environ, "MIGAO_CI_HELPER_SCOPE": "full"})
    assert full.returncode == 0 and full.stdout.strip() == "", "override=full 时不许让出任何判据"


def _python_stub(tmp_path: pathlib.Path) -> pathlib.Path:
    """PATH 上放一个 `python` 桩 —— 用来接住 `--run-narrow` 真正 exec 出去的 argv。"""
    stub = tmp_path / "python"
    stub.write_text('#!/usr/bin/env bash\necho "ARGV: $*"\n', encoding="utf-8")
    stub.chmod(0o755)
    return stub


def test_run_narrow_really_passes_the_ignores(tmp_path):
    """🔴 接线真跑：narrow 档必须把 dev_only 全部作为 `--ignore=` 传给套件（不是只写在注释里）。"""
    stub = _python_stub(tmp_path)
    env = {**os.environ, "MIGAO_CI_HELPER_SCOPE": "narrow",
           "PATH": f"{tmp_path}:{os.environ.get('PATH', '')}"}
    p = subprocess.run([sys.executable, str(REPO / "scripts/ci_helper_scope.py"), "--run-narrow"],
                       capture_output=True, text=True, cwd=str(REPO), env=env, timeout=60)
    assert p.returncode == 0, p.stderr
    argv_line = [ln for ln in p.stdout.split("\n") if ln.startswith("ARGV: ")]
    assert argv_line, f"桩没被调用 —— narrow 档没有真起套件：{p.stdout}{p.stderr}"
    tokens = argv_line[-1].split()
    ignores = [t for t in tokens if t.startswith("--ignore=")]
    assert len(ignores) == len(_ledger()["dev_only"]), f"让出参数没传全：{len(ignores)}"
    assert "-m" in tokens and "pytest" in tokens, "窄档不是走同一份 canonical argv"
    assert "未跑" in p.stdout, "窄档必须出声（未跑条数）"


def test_run_narrow_with_full_override_passes_no_ignores(tmp_path):
    """对照读数：override=full ⇒ 同一条命令**一条 ignore 都不加**（证明上面那条不是恒真）。"""
    _python_stub(tmp_path)
    env = {**os.environ, "MIGAO_CI_HELPER_SCOPE": "full",
           "PATH": f"{tmp_path}:{os.environ.get('PATH', '')}"}
    p = subprocess.run([sys.executable, str(REPO / "scripts/ci_helper_scope.py"), "--run-narrow"],
                       capture_output=True, text=True, cwd=str(REPO), env=env, timeout=60)
    assert p.returncode == 0, p.stderr
    assert "--ignore=" not in p.stdout, p.stdout
