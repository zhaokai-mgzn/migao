"""生成物出库（issue #8167 P1-1）的判定面：**不许入库** / **必须可复现** / **落盘副本必须最新**。

## 判据（每条都有红证；红证在**临时仓库**里跑**同一份实现**）

| # | 判据 | 会红的形态 |
|---|---|---|
| 1 | 两个出库产物**不许**被 git 跟踪（索引 + HEAD 两侧都查，逐文件具名） | 有人 `git add -f` 把它们塞回来 |
| 2 | `.gitignore` 必须覆盖这两个路径 | 删掉忽略条目 ⇒ 下一次 `git add -A` 又入库 |
| 3 | 判定本体在**出库形态下仍然会红** | 落盘副本陈旧/手改 ⇒ rc 1；两次渲染不同 ⇒ rc 1；渲染器坏了 ⇒ rc 3 |

🔴 **本文件存在的理由**（对 2026-10-30 那条「不做」裁定的正面回答）：出库最大的风险是
「渲染没跑 ⇒ 判据看不到文件 ⇒ 假绿」（与 `migao-acceptance` 的「空跑」同族）。所以这里
**逐个**证明：① 缺副本**不是**通过（判定转成可复现性，仍会红）；② 塞回 git 会红且具名；
③ 判定本体在坏渲染器上判 **3（不可判定）**，而 `3` 从不被当成 `0`。

⚖️ 判断标准（本单口径）：**能不能从别的文件 100% 重建** —— 能 ⇒ 出库；不能（含人手写的
历史/来由，如 `case_machine_fail_channel_baseline.json`）⇒ 留库。

# case_ids: MC-210
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from unit_ci_workflows.injection import inject

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "generated_artifacts_freshness.py"

#: 两个出库产物（与实现里的 `ARTIFACTS` 登记表同一口径；这里只用于**具名**断言）。
ARTIFACT_DIR = "tests/agent_eval/eval_cases"
ARTIFACT_MD = "docs/testing/mibao-verification-cases.md"

#: 渲染器写 casebook 的那一句 —— 红证注入锚点（漂了就由 `inject` 当场抛 `AnchorDrift`）。
RENDER_WRITE_MD = "        f.write(md)\n"


def _load():
    """按路径加载判定本体（`scripts/` 不是包；不往 `sys.path` 里塞东西，免遮蔽同名模块）。"""
    spec = importlib.util.spec_from_file_location("migao_genfresh_untracked", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module      # dataclass 处理要能从 sys.modules 取到模块（先登记再 exec）
    spec.loader.exec_module(module)
    return module


MOD = _load()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_AUTHOR_NAME": "case", "GIT_AUTHOR_EMAIL": "case@example.invalid",
           "GIT_COMMITTER_NAME": "case", "GIT_COMMITTER_EMAIL": "case@example.invalid"}
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, env=env)
    assert proc.returncode == 0, f"夹具 git {' '.join(args)} 失败：{proc.stderr[:300]}"
    return proc


def _mini_repo(root: Path, *, generate: bool = True) -> Path:
    """最小可判定仓库：真渲染器 + 真用例库（**不**复制产物，除非 `generate=True`）。

    `.gitignore` 也按**真文件**复制：判据 2 判的是「本仓库的忽略条目在不在」，
    夹具里给一份同样的，才能让 `.gitignore` 缺失**不是**默认状态。
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / ".github").mkdir(exist_ok=True)
    for src in sorted((REPO / ".github").glob("*.py")):
        shutil.copy2(src, root / ".github" / src.name)
    shutil.copytree(REPO / ".github" / "cases", root / ".github" / "cases")
    shutil.copy2(REPO / ".gitignore", root / ".gitignore")
    if generate:
        MOD.ensure_generated(root)
    return root


def _run(repo: Path, *extra: str) -> tuple[int, str]:
    """跑 CLI（真 subprocess）⇒ `(rc, 输出)`。"""
    proc = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), *extra],
                          capture_output=True, text=True, timeout=900)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


# ══════════════════════════════════════════════════════════════════════════════
# 判据 1：产物不许被 git 跟踪（本仓库 + 注入式红证）
# ══════════════════════════════════════════════════════════════════════════════


def test_no_artifact_is_tracked_in_this_repo():
    """**判据 1（本仓库）**：`git ls-files` / `git ls-tree HEAD` 里都不许有出库产物。"""
    tracked, error = MOD.tracked_artifact_paths(REPO)
    assert error == "", f"取不到 git 事实 ⇒ **不可判定，不是合规**：{error}"
    assert tracked == [], (
        "出库产物**又被 git 跟踪了**（issue #8167 P1-1）—— 这是千行 diff / 合并冲突的根因。\n"
        f"命中：{tracked}\n"
        "处置：`git rm --cached <上列路径>`（保留工作区文件），并确认 `.gitignore` 仍有条目。")


def test_gitignore_covers_every_artifact():
    """**判据 2（本仓库）**：`.gitignore` 必须逐条覆盖 —— 缺一条 ⇒ 判据 1 的防线被绕过。"""
    gaps, error = MOD.gitignore_gaps(REPO)
    assert error == "", f"`.gitignore` 读不到 ⇒ 不可判定：{error}"
    assert gaps == [], f"`.gitignore` 缺出库产物条目：{gaps}"


def test_hygiene_is_applicable_in_the_real_repo():
    """**不许静默跳过**：真仓库上「是否被塞回 git」这一格必须**可判**（`applicable=True`）。"""
    hygiene = MOD.artifact_hygiene(REPO)
    assert hygiene["applicable"] is True, f"真仓库上这一格却不可判：{hygiene['note']}"
    assert hygiene["tracked"] == [] and hygiene["gitignore_gaps"] == [], hygiene


def test_git_add_f_turns_the_guard_red(tmp_path):
    """**红证（判据 1）**：`git add -f` 把产物塞回索引 ⇒ 守卫当场具名判红。"""
    repo = _mini_repo(tmp_path / "smuggled")
    _git(repo, "init", "-q")
    # 先有一个基线提交：真实仓库永远有 HEAD，而「没有 HEAD」是**无法判定**（不是合规）
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=case@example.invalid", "-c", "user.name=case",
         "commit", "-qm", "base")
    _git(repo, "add", "-f", "--", ARTIFACT_DIR, ARTIFACT_MD)
    tracked, error = MOD.tracked_artifact_paths(repo)
    assert error == "", error
    assert ARTIFACT_MD in tracked, f"塞回来的 casebook 没被认出来：{tracked}"
    assert any(p.startswith(ARTIFACT_DIR + "/") for p in tracked), \
        f"塞回来的 eval_cases 模块没被认出来：{tracked}"
    hygiene = MOD.artifact_hygiene(repo)
    assert hygiene["applicable"] is True and hygiene["tracked"], hygiene


# ══════════════════════════════════════════════════════════════════════════════
# 判据 3：判定本体在出库形态下**仍然会红**（红证逐条，全部真跑）
# ══════════════════════════════════════════════════════════════════════════════


def test_stale_on_disk_copy_is_red_and_named(tmp_path):
    """落盘副本陈旧（手改一行）⇒ **rc 1 + 具名到产物**（不是「文件在就算过」）。"""
    repo = _mini_repo(tmp_path / "stale")
    md = repo / ARTIFACT_MD
    md.write_text(md.read_text(encoding="utf-8") + "\n（手改一行）\n", encoding="utf-8")
    rc, out = _run(repo)
    assert rc == 1, f"副本与源不同步却没有判红（rc={rc}）：{out[-800:]}"
    assert "::error::" in out and ARTIFACT_MD in out, f"判红没具名到产物：{out[-800:]}"


def test_missing_copy_still_runs_the_reproducibility_judgement(tmp_path):
    """🔴 **缺副本 ≠ 免检**：产物不在树里 ⇒ 判定转成**可复现性**（连渲两次），仍然真跑。

    反面形态（本仓明令禁止）：`if not exists: return 0`。这里同时钉住「跑了什么」与「凭什么算过」。
    """
    repo = _mini_repo(tmp_path / "absent", generate=False)
    rc, out = _run(repo, "--json", str(tmp_path / "absent.json"))
    assert rc == 0, f"可复现却被判红（rc={rc}）：{out[-800:]}"
    assert "可复现" in out, f"输出里没说清判定对象已换成可复现性：{out[-800:]}"
    report = __import__("json").loads((tmp_path / "absent.json").read_text(encoding="utf-8"))
    assert report["mode"] == "absent", report
    assert report["seen"] == 2 and report["verdict"] == "fresh", report
    # 缺副本时**确实**把产物造在了临时目录里（否则「可复现」是空话）
    assert (repo / ARTIFACT_MD).exists() is False, "夹具自称缺副本，却已经有一份落盘（断言无对象）"


def test_non_deterministic_render_is_red(tmp_path):
    """**红色形态**：渲染器不确定（每次输出都不同）⇒ rc 1 + 「不可复现」具名。"""
    repo = _mini_repo(tmp_path / "nondet", generate=False)
    renderer = repo / ".github" / "render_cases.py"
    mutated = inject(renderer.read_text(encoding="utf-8"),
                     RENDER_WRITE_MD,
                     "        import random\n        f.write(md + str(random.random()))\n",
                     where=".github/render_cases.py")
    renderer.write_text(mutated, encoding="utf-8")
    rc, out = _run(repo)
    assert rc == 1, f"两次渲染不同却没判红（rc={rc}）：{out[-800:]}"
    assert "不可复现" in out, f"判红没说清是「不可复现」：{out[-800:]}"


def test_broken_renderer_is_undecidable_not_a_pass(tmp_path):
    """**渲染器坏了 ⇒ rc 3**（不可判定）；`3` 绝不能被读成 `0`。"""
    repo = _mini_repo(tmp_path / "broken", generate=False)
    (repo / ".github" / "render_cases.py").write_text("import sys\nsys.exit(2)\n", encoding="utf-8")
    rc, out = _run(repo)
    assert rc == 3, f"渲染器坏了却不是「无法判定」（rc={rc}）：{out[-800:]}"
    assert "无法判定" in out and "::error::" in out, out[-800:]


def test_generation_failure_raises_instead_of_returning_empty(tmp_path):
    """生成腿失败 ⇒ **抛 `GenerationError`**（调用方不许把它降级成 skip）。"""
    repo = _mini_repo(tmp_path / "genfail", generate=False)
    (repo / ".github" / "render_cases.py").write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
    with pytest.raises(MOD.GenerationError) as excinfo:
        MOD.ensure_generated(repo)
    assert "渲染失败" in str(excinfo.value), str(excinfo.value)


def test_write_is_idempotent_and_generates_both_artifacts(tmp_path):
    """`--write` 幂等：连跑两次逐字节一致，且两个产物都落盘（缺一个都不行）。"""
    repo = _mini_repo(tmp_path / "write", generate=False)
    rc1, out1 = _run(repo, "--write")
    assert rc1 == 0, out1[-800:]
    first = {rel: (repo / rel).read_bytes() for rel in (ARTIFACT_MD,)}
    first_dir = {p.name: p.read_bytes() for p in (repo / ARTIFACT_DIR).glob("*.py")}
    assert first[ARTIFACT_MD] and first_dir, "`--write` 没产出（两个产物缺一）"
    rc2, out2 = _run(repo, "--write")
    assert rc2 == 0, out2[-800:]
    assert (repo / ARTIFACT_MD).read_bytes() == first[ARTIFACT_MD], "两次生成 casebook 不一致（非幂等）"
    assert {p.name: p.read_bytes() for p in (repo / ARTIFACT_DIR).glob("*.py")} == first_dir, \
        "两次生成 eval_cases 不一致（非幂等）"
