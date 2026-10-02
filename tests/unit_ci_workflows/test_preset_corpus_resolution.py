# case_ids: MC-012
"""`preset_corpus` 的语料解析判据（issue #6058）。

## 病（2026-10-02 实测：S4 合并后 main 侧守护腿红）

`preset_corpus` 的 git 基线候选原来**只有固定回退** `("origin/main", "origin/main~1", "HEAD~1", "HEAD")`。
S4（#6034）把预设迁出业务仓后，`origin/main` **不再带** `.agent-presets/migao/**`（正是那次合并删的），
`~1` 这个「回退一格」也不成立 ⇒ 基线全落空 ⇒ ③ 镜像兜底（**CI 上没有镜像**）⇒ `preset_root() is None`
⇒ 依赖它的 5 个判据 **fail-closed 判红**。而本机有镜像 ⇒ 绿 —— 又是「本机绿 / CI 红」。

## 本文件锁什么

| # | 判据 | 取法 |
|---|---|---|
| 1 | 候选生成：`rev-list` 输出 ⇒ **每个提交 + 它的父提交**，且去重保序 | 纯函数（喂样本串） |
| 2 | **禁掉镜像**后仍能从业务仓历史取到预设内容（= 今天那条红的等价形态，本机可复现） | 行为级（真仓 + 改 `PRESET_MIRROR`） |
| 3 | 取到的语料**不是镜像**（否则判据 2 会被镜像兜底蒙混过去） | 行为级 |
| 4 | 历史候选**有上限**（每个候选都要 `ls-tree` ⇒ 不设上限会让本腿变慢/挂死） | 常量读数 |

⚠️ 不含：完全没有该路径历史对象的检出（`fetch-depth: 1`）⇒ 仍 fail-closed 判红（**有意**，不是静默绿）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from unit_ci_workflows import preset_corpus as pc  # noqa: E402


def test_history_candidates_include_parents_and_keep_order():
    got = pc._history_baseline_refs("aaa\nbbb\nccc\n")
    assert got == ["aaa", "aaa^", "bbb", "bbb^", "ccc", "ccc^"], got
    assert pc._history_baseline_refs("aaa\naaa\n") == ["aaa", "aaa^"], "重复提交必须去重"


def test_candidate_list_puts_fixed_refs_first_and_appends_history():
    refs = pc._baseline_candidate_refs()
    assert refs[: len(pc.PRESET_BASELINE_REFS)] == list(pc.PRESET_BASELINE_REFS), (
        "固定候选必须仍在最前（口径：业务仓当前状态优先）"
    )
    assert len(refs) >= len(pc.PRESET_BASELINE_REFS), "历史候选没被追加 ⇒ 今天的红会复现"
    assert len(refs) == len(set(refs)), "候选必须去重"


def test_history_candidates_are_bounded():
    assert 0 < pc.HISTORY_CANDIDATES_MAX <= 40, (
        "历史候选必须有上限（每个候选一次 `ls-tree`）——无上限会让本腿变慢甚至挂死"
    )


def test_preset_content_is_readable_without_the_mirror():
    """🔴 今天 main 侧那条红的等价形态：**禁掉镜像**也必须读得到。"""
    saved = pc.PRESET_MIRROR
    cached = list(pc._CACHE)
    try:
        pc._CACHE.clear()
        pc.PRESET_MIRROR = Path("/nonexistent-mirror-6058")
        root = pc.preset_root()
        assert isinstance(root, Path), (
            "禁掉镜像后仍必须能从业务仓历史里取到预设内容 —— 否则 main 侧守护腿（CI 上无镜像）会判红"
        )
        assert pc.preset_text(pc.DEV_FLOW_SKILL_REL), "技能正文读不到 ⇒ 依赖它的 5 个判据会 fail-closed 判红"
    finally:
        pc.PRESET_MIRROR = saved
        pc._CACHE[:] = cached


def test_resolved_corpus_is_not_the_mirror():
    saved = pc.PRESET_MIRROR
    cached = list(pc._CACHE)
    try:
        pc._CACHE.clear()
        fake = Path("/nonexistent-mirror-6058")
        pc.PRESET_MIRROR = fake
        root = pc.preset_root()
        assert isinstance(root, Path), "取不到语料根 ⇒ 本判据无从对照"
        assert fake not in root.parents and root != fake, (
            "取到的语料是镜像 ⇒ 判据 2 会被镜像兜底蒙混（今天本机绿就是这个原因）"
        )
    finally:
        pc.PRESET_MIRROR = saved
        pc._CACHE[:] = cached
