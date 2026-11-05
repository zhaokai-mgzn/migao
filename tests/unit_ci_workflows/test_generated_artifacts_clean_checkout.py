"""生成物出库（issue #8167 P1-1）的**接线判据**：干净检出能跑，摘掉生成腿就红。

## 为什么这条判据是本档的核心（不是「顺手加的」）

出库把「产物在不在树里」从**事实**变成了**运行期前置**。风险因此从「忘了提交」变成
「**没人去生成**」—— 而那正是 2026-10-30 那条「不做」裁定点名的那类失效（渲染没跑 ⇒
判据看不到文件 ⇒ 假绿）。所以本文件**真跑**一次干净检出，并且**反过来**证明：
把生成腿摘掉之后，同一棵树**当场红**。

| 判据 | 形态 | 红证 |
|---|---|---|
| 干净检出可跑 | `git archive HEAD` 解出的树（**不含**出库产物）里跑一个消费者 | 摘掉 conftest 的生成腿 ⇒ 同一棵树 `ModuleNotFoundError` |
| 生成腿不许改名/删除 | CI 两处 + `verify-all.sh` + 三个 conftest + `local_runner` 都跑**同一条命令** | 删掉任一处的命令文本 ⇒ 接线判据具名判红 |

⚠️ 本文件**不**证明「产物内容对不对」（那是 `test_generated_artifacts_untracked.py` 的射程）；
它只证明**接线还在**、且**没跑时会红**。

# case_ids: MC-210
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from unit_ci_workflows.injection import inject

REPO = Path(__file__).resolve().parents[2]

#: 出库的两个产物（仓库相对全路径）。
ARTIFACTS = ("tests/agent_eval/eval_cases", "docs/testing/mibao-verification-cases.md")

#: 生成腿的**脚本**（入口里必须有它）。
GEN_SCRIPT = "generated_artifacts_freshness.py"

#: 生成腿的**动作**（入口里必须有它；缺任一半 ⇒ 接线断）。
GEN_FLAG = "--write"

#: shell 入口里它长这样（CI / `verify-all.sh` / 守护腿；用于数「有几条腿真的带生成」）。
GEN_COMMAND_SHELL = "scripts/" + GEN_SCRIPT + " " + GEN_FLAG

#: 消费者：它**逐个读** casebook 里的汇总与块（干净检出里最初没有这个文件）。
CONSUMING_TEST = "tests/unit_ci_workflows/test_casebook_summary_is_derived.py"

#: `tests/unit_ci_workflows/conftest.py` 里那段生成调用（红证注入锚点；漂了 `inject` 会抛）。
CONFTEST_GEN_CALL = '''subprocess.run(
    [sys.executable, str(REPO_ROOT / "scripts" / "generated_artifacts_freshness.py"), "--write"],
    check=True, cwd=str(REPO_ROOT),
)'''

#: 必须跑生成腿的入口（文件 → 它为什么需要）。
ENTRIES = {
    ".github/workflows/pr-check.yml":
        "两条消费腿（`ci workflow helper unit tests` 的套件在 import 期就要 eval_cases；"
        "`Case Contract (truths_ref)` 的判定步本身）",
    ".github/workflows/main-freshness-guard.yml": "main 侧守护腿：不生成就只能判「无法判定」",
    "verify-all.sh": "本地 cases 面门禁（与 CI 同脚本同参数）",
    "tests/unit_ci_workflows/conftest.py": "最大的消费套件（收集前生成，失败即抛）",
    "tests/agent_eval/conftest.py": "`local_runner` 在 import 期就 `from eval_cases import …`",
    "tests/agent_eval/local_runner.py": "直接跑脚本的入口（不经 pytest）",
    "backend/ai-agent-service/tests/conftest.py": "后端套件里的模块级消费者",
}


def _extract_clean_tree(dest: Path) -> Path:
    """把 `HEAD` 解成**干净检出**（只有 tracked 文件 ⇒ 不含出库产物，这是判据的前提）。

    不用 `git worktree`：`git archive` 的树**没有 `.git`**，因此「产物不在树里」是**构造事实**
    而不是断言出来的巧合；同时也不会在共享仓库里留下 worktree 注册。
    """
    proc = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=str(REPO),
                          capture_output=True, timeout=600)
    assert proc.returncode == 0, (proc.stderr or b"")[:400]
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tf:
        tf.extractall(dest)
    return dest


def _pytest_in(tree: Path, target: str) -> subprocess.CompletedProcess:
    """在干净树里跑一个消费者（清掉会串味的 `PYTHONPATH` / `PYTEST_ADDOPTS`）。"""
    # ⚠️ 必须清掉继承来的 `MIGAO_*`：CI 的那条腿会设 `MIGAO_CI_HELPER_SHARD=N/2`，
    # 内层 pytest 会据此把**目标用例 deselected** ⇒ 退化成「8 deselected / rc 5」，
    # 而断言会读成「干净检出跑不过」（归因指向错误的对象）。
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONPATH", "PYTEST_ADDOPTS") and not k.startswith("MIGAO_")}
    return subprocess.run([sys.executable, "-m", "pytest", target, "-q", "-p", "no:cacheprovider"],
                          cwd=str(tree), capture_output=True, text=True, env=env, timeout=1800)


def test_clean_checkout_runs_a_consuming_test(tmp_path):
    """**判据（行为级）**：干净检出（无产物、无 `.git`）里跑消费者 ⇒ 生成腿自动补上 ⇒ 全绿。"""
    tree = _extract_clean_tree(tmp_path / "clean")
    for rel in ARTIFACTS:
        assert not (tree / rel).exists(), f"干净检出里竟然有产物（前提不成立）：{rel}"

    proc = _pytest_in(tree, CONSUMING_TEST)
    out = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, out[-2000:]
    assert "passed" in out, out[-2000:]
    for rel in ARTIFACTS:
        assert (tree / rel).exists(), f"生成腿没把产物造出来：{rel}"


def test_removing_the_generation_step_turns_the_same_tree_red(tmp_path):
    """**红证**：把 conftest 里的生成腿摘掉 ⇒ **同一棵树**当场红（不是「文件不存在所以跳过」）。"""
    tree = _extract_clean_tree(tmp_path / "mutant")
    conftest = tree / "tests" / "unit_ci_workflows" / "conftest.py"
    mutant = inject(conftest.read_text(encoding="utf-8"), CONFTEST_GEN_CALL,
                    "pass  # 变异：生成腿被摘掉（出库形态下这必须是红的）",
                    where="tests/unit_ci_workflows/conftest.py")
    conftest.write_text(mutant, encoding="utf-8")
    for rel in ARTIFACTS:                       # 双保险：确保产物仍不在树里（否则红因会被顶掉）
        assert not (tree / rel).exists(), f"变异树上居然有产物：{rel}"

    proc = _pytest_in(tree, CONSUMING_TEST)
    out = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode != 0, f"摘掉生成腿之后仍然绿 ⇒ 判据没有牙：\n{out[-2000:]}"
    assert "No module named 'eval_cases'" in out, \
        f"红因不是「产物没生成」（归因要指向病因）：\n{out[-2000:]}"


@pytest.mark.parametrize("rel", sorted(ENTRIES))
def test_every_entry_runs_the_generation_command(rel):
    """**接线判据**：每个消费入口都必须跑**同一条**生成命令（删掉/改名 ⇒ 具名判红）。"""
    text = (REPO / rel).read_text(encoding="utf-8")
    assert GEN_SCRIPT in text and GEN_FLAG in text, (
        f"{rel} 不再跑生成腿（`{GEN_SCRIPT} {GEN_FLAG}`）—— 出库产物不在 git 里，"
        f"少了这一步它就会在干净检出里缺失。该入口的角色：{ENTRIES[rel]}")


def test_pr_check_covers_both_consuming_legs():
    """`pr-check.yml` 里**两条**消费腿都要先生成（少一条 ⇒ 那条腿在干净检出里必炸）。"""
    text = (REPO / ".github/workflows/pr-check.yml").read_text(encoding="utf-8")
    assert text.count(GEN_COMMAND_SHELL) == 2, (
        "`pr-check.yml` 里生成命令的出现次数不是 2（`ci workflow helper unit tests` + "
        f"`Case Contract (truths_ref)`）：{text.count(GEN_COMMAND_SHELL)}")
