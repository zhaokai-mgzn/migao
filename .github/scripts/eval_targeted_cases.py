#!/usr/bin/env python3
"""部署后评测「diff → 定向用例 / 全量兜底」判定（issue #3654，用户裁定 2026-09-14）。

## 为什么需要

部署后全量是 CI 真实 LLM 成本主因之一（近 2.5h ≈ ¥135-295）。自动门禁不能降频，
但可以**收窄到受影响用例**（§16 迭代档语义）：部署触发时用
`git diff <被评SHA>^ <被评SHA> --name-only` 取本次部署的改动文件，
复用 `tests/agent_eval/behavior_mapping.py`（#3502 §13.2 映射表）把它映射成 case_ids，
只跑这些用例 + fast（--max-retries 0）。全量改由**每 3 天 schedule cron** 承担。

## 保守边界（宁多跑不少跑，安全优先——「定向」的边界）

- **宽爆炸半径命中 → 全量**：diff→用例映射对**跨切面/共享行为层文件**不精确
  （base_skill / nodes / references / registry / factory / app/graph/**），
  命中必须回退全量，不能因为映射窄就漏掉大范围回归；
- **无 AI 行为文件（docs/前端等）→ 全量**：case_ids 空 = 现状（全量 normal）兜底；
- **有 AI 行为文件但映射表未覆盖（default_net）→ 全量**：部署后拦截是**硬门禁**
  （失败去重建 issue），PR 层「default_net 只报告（无因果）」的语义**不适用于这里**——
  映射表没覆盖的域按全量处理（§13.2 盲区）；
- **规则命中但本 persona 无对应用例 → 本端跑默认网子集**（最窄主链路信号，
  DEFAULT_BEHAVIOR_CASES ∩ 本端可执行集；该子集也不存在才回退全量）——
  深度覆盖由每 3 天全量承担（这是「按改动点跑有限受影响用例」在 persona 维度的落地：
  受影响用例为空的一端不该烧全量，但也不静默消失）。

## 契约

- `compute_mode(diff_files, persona, persona_case_ids)` → `(mode, case_ids, reason)`：
  纯函数，L0 测试直接调用；`mode ∈ {"full", "targeted"}`；
- CLI：`--sha <被评SHA>`（git diff 派生）或 `--diff-file <路径>`（测试用）+
  `--persona mibao|xiaobu` + `--repo-root <仓根>`；输出 `mode=` / `case_ids=` / `reason=`
  三行并写 `GITHUB_OUTPUT`（若设）；
- **fail-open**：选择器自身任何异常（取 diff 失败 / persona 集加载失败 / 导入失败）→
  一律 `full`（宁可多跑，不可漏评）；**退出码恒 0**（选择器是省成本层，不因自身故障刷红）。

## 为什么零第三方依赖

workflow 里它在「Install eval runner deps」**之前**跑（任何真实成本之前），
只用系统 python3 + 仓库内零依赖模块（behavior_mapping / yaml_light / eval_case_filter）；
L0 单测同样秒级跑完（§16.1 静态层）。
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
# _SCRIPTS_DIR 已是 .github/scripts：parents[0]=.github、parents[1]=仓根
REPO_ROOT = _SCRIPTS_DIR.parents[1]

# ── 宽爆炸半径（跨切面/共享行为层文件）：diff→用例映射对这些文件**不精确**，
#    命中必须回退全量（不能因为映射窄就漏掉大范围回归）。
# 匹配语义 = 前缀匹配（仓根相对路径）。清单**可维护**：新增共享/行为层文件时在此登记；
# 清单本身由 tests/unit_ci_workflows/test_post_deploy_eval_targeted.py 的变异守卫锁住
# （从清单删掉任一文件 → 守卫红，证明清单没有被悄悄放宽）。 ──
WIDE_BLAST_RADIUS_PREFIXES = (
    "backend/ai-agent-service/app/graph/skills/base_skill.py",  # 守卫/共享 Skill 基类（B/C 共用）
    "backend/ai-agent-service/app/graph/nodes.py",              # 图节点路由（跨 skill 共享）
    "backend/ai-agent-service/app/graph/skills/references/",    # Skill 共享示例库
    "backend/ai-agent-service/app/tools/registry.py",           # 工具注册表（全部工具的路由面）
    "backend/ai-agent-service/app/llm/factory.py",              # LLM 工厂（模型/provider 路由）
    "backend/ai-agent-service/app/graph/",                      # graph 全家兜底（builder/state/skills/**）
)

# 复用 behavior_mapping 的映射表与默认网（同一口径，不新造标准）
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))
from behavior_mapping import DEFAULT_BEHAVIOR_CASES, map_changed_files_with_source  # noqa: E402


def _hits_wide_blast(path: str) -> bool:
    return any(path.startswith(p) for p in WIDE_BLAST_RADIUS_PREFIXES)


def compute_mode(diff_files: list, persona: str, persona_case_ids) -> tuple:
    """diff 文件列表 → (mode, case_ids, reason)。纯函数（L0 测试直接调用，零 repo 依赖）。

    Args:
        diff_files: `git diff --name-only` 输出行（仓根相对路径；空串/空白项忽略）。
        persona: mibao | xiaobu（决定本端可执行用例集）。
        persona_case_ids: 该 persona **实际可执行**的用例 ID 集（CLI 用
            `select_cases_for_persona` 同源算出；测试直接传入）。

    Returns:
        (mode, case_ids, reason)：
          - mode="full" → 跑 normal 全量（现状兜底）；case_ids 恒空；
          - mode="targeted" → 只跑 case_ids（fast：--max-retries 0）。
    """
    files = [f.strip() for f in diff_files if f and f.strip()]
    if not files:
        return "full", [], "空 diff（首提交/取 diff 失败）→ 全量兜底"

    hit = next((f for f in files if _hits_wide_blast(f)), None)
    if hit is not None:
        return "full", [], f"宽爆炸半径文件 {hit} → 全量（映射对共享行为层不精确）"

    mapped, source = map_changed_files_with_source(files)
    if source == "none":
        return "full", [], "无 AI 行为文件改动（docs/前端等）→ 全量兜底"
    if source == "default_net":
        return "full", [], "映射表未覆盖的域（§13.2 盲区）→ 保守回退全量"

    persona_ids = {str(x) for x in (persona_case_ids or ())}
    picked = sorted(x for x in mapped if x in persona_ids)
    if picked:
        return "targeted", picked, f"命中规则 → 定向 {len(picked)} 条（fast）"

    # 规则命中但本端无对应用例 → 默认网子集（最窄主链路信号，深度覆盖由每 3 天全量承担）
    net = sorted(x for x in DEFAULT_BEHAVIOR_CASES if x in persona_ids)
    if net:
        return "targeted", net, f"规则命中但本端无对应用例 → 默认网子集 {net}（fast）"

    return "full", [], "本端默认网子集为空（用例库异常）→ 全量兜底"


def _git_diff_files(repo_root: Path, sha: str) -> list:
    """被评 SHA 相对其父的变更文件列表；首提交无父 → 空列表（调用方按全量兜底）。"""
    parent = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", "--quiet", f"{sha}^"],
        capture_output=True, text=True)
    if parent.returncode != 0:
        return []
    r = subprocess.run(
        ["git", "-C", str(repo_root), "diff", "--name-only", f"{sha}^", sha],
        capture_output=True, text=True)
    if r.returncode != 0:
        return []
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def _load_persona_case_ids(repo_root: Path, persona: str) -> set:
    """该 persona 实际可执行的用例 ID 集——**复用 local_runner 同一过滤实现**
    （load_case_dicts + select_cases_for_persona），防口径漂移（#2855/#3266 单一源）。"""
    sys.path.insert(0, str(repo_root / ".github"))
    sys.path.insert(0, str(repo_root / "tests" / "agent_eval"))
    from render_cases import load_case_dicts
    from eval_case_filter import select_cases_for_persona
    cases = load_case_dicts(str(repo_root / ".github" / "cases"))
    return {str(c.get("id") or "") for c in select_cases_for_persona(cases, persona)}


def main() -> None:
    ap = argparse.ArgumentParser(description="部署后评测 diff→定向用例/全量兜底判定（#3654）")
    ap.add_argument("--sha", default="", help="被评 SHA（git diff <sha>^ <sha> 派生 diff）")
    ap.add_argument("--diff-file", default="", help="diff 文件列表（每行一个路径，测试钩子）")
    ap.add_argument("--persona", default="mibao", help="mibao | xiaobu")
    ap.add_argument("--repo-root", default=str(REPO_ROOT))
    args = ap.parse_args()

    repo_root = Path(args.repo_root)
    try:
        if args.diff_file:
            with open(args.diff_file, encoding="utf-8") as fh:
                files = [ln.strip() for ln in fh if ln.strip()]
        elif args.sha:
            files = _git_diff_files(repo_root, args.sha)
        else:
            files = []
        persona_ids = _load_persona_case_ids(repo_root, args.persona)
    except Exception as exc:  # noqa: BLE001 —— 选择器自身故障 → fail-open 全量（绝不漏评/刷红）
        mode, case_ids, reason = "full", [], f"定向选择器异常（{exc}）→ fail-open 全量"
    else:
        mode, case_ids, reason = compute_mode(files, args.persona, persona_ids)

    print(f"mode={mode}")
    print(f"case_ids={','.join(case_ids)}")
    print(f"reason={reason}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"mode={mode}\n")
            fh.write(f"case_ids={','.join(case_ids)}\n")
            fh.write(f"reason={reason}\n")
    # 退出码恒 0：选择器失败/兜底都不是失败（fail-open 语义，同 eval_supersede.sh）


if __name__ == "__main__":
    main()
