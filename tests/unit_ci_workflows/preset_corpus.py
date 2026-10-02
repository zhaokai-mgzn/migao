# case_ids: MC-012
"""**预设内容**的统一读法（S4 / issue #6020 起）。

## 为什么需要这个模块

S4 把预设内容（`SKILL.md` / `CHANGELOG.md` / `scripts/*.mjs` / `agent.cordis.yml`）整体迁到独立仓
`zhaokai-mgzn/migao-agent-presets`，业务仓**不再承载** `.agent-presets/**`。
而业务仓里有一批判据（技能面口径、persona 落点、承载体性质、台账所指章节）**必须读那份内容**
—— 否则它们要么读空、要么变成「读不到就跳过」的**静默绿**。

本模块 = 那批判据的**唯一读取口径**（别处不许再拼 `.agent-presets/...` 的字面路径）：

| 顺序 | 来源 | 何时命中 |
|---|---|---|
| ① | **本仓工作树** `.agent-presets/migao/` | 该路径若在本仓重新出现（反向验证 / 回滚），判据立即照旧判**它** |
| ② | **git 基线**（`origin/main` → `origin/main~1` → `HEAD~1` → `HEAD` 里第一个真带着该路径的） | 默认（CI 与**本机都走这条** —— 见下面的「为什么不是镜像优先」）|
| ③ | **预设仓镜像**（`$MIGAO_PRESET_MIRROR` / `~/.migao-dev-preset-anchor`） | 兜底（基线都取不到时）|

### 为什么**不是**镜像优先（本 PR 实测）

镜像会**落后** `origin/main`（实测：镜像 `0a211ed` = 技能 `1.103.0`，而业务仓 `origin/main` 已是 `1.104.0`）。
而本目录这些判据的**期望字面量**（逐字锚、章节标题、版本口径）是跟着**业务仓 main** 走的 ⇒ 拿落后镜像当语料
会让它们在本机**假红**，且与 CI（无镜像 ⇒ 只能走基线）**口径不一致** —— 「本机绿 / CI 红」正是本 PR
返工三轮的根因形态。⇒ 统一以**业务仓基线**为准（本机与 CI 同一份），镜像只在基线取不到时兜底。

## 硬规矩

- **取不到 ⇒ 判红（fail-closed）**，且报错要**能照着修**（告诉你去建镜像 / 去改基线）；
- **不许新增 `pytest.skip`**：`tests/unit_ci_workflows` 的 skip 读数是**冻结**的
  （`helper_leg_shape_ledger.json` ⇒ `frozen_inventory.skipped_reading`），新增 skip 会把
  「执行形态」判据自己打红；
- **不许静默绿**：「没东西可判」与「判过且通过」必须区分开。

⚠️ 实测教训（本 PR 第一轮 CI）：`origin/main~1` 在 `fetch-depth: 1` 的 `pull_request` 检出里
**根本不解析**（`fatal: Not a valid object name`）⇒ 候选表要**按可用性探**，且判据是
「**内容真读得到**」而不是「ref 解析得开」。
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 预设内容在**业务仓**里的前缀（S4 前的位置；也是 git 基线里的键）。
PRESET_PREFIX_IN_REPO = ".agent-presets/migao/"
#: 读预设内容的 git 基线候选（按序取第一个**真读得到**的）。
PRESET_BASELINE_REFS = ("origin/main", "origin/main~1", "HEAD~1", "HEAD")
#: 本机预设仓镜像（= 权威源）。`MIGAO_PRESET_MIRROR` 可覆盖，与 `scripts/preset-anchor-check.sh` 同源。
PRESET_MIRROR = Path(os.environ.get("MIGAO_PRESET_MIRROR")
                     or (Path.home() / "migao-dev-preset-anchor"))
#: 技能（相对**预设目录**）。
DEV_FLOW_SKILL_REL = "skills/migao-dev-flow/SKILL.md"
DEV_FLOW_CARRIER_REL = "skills/migao-dev-flow/scripts/ui-multimodal-acceptance.mjs"
PRESET_YML_REL = "preset.yml"

_CACHE: list = []


def _materialize_from_git() -> Path | None:
    """把 git 基线里的预设目录落到临时目录 ⇒ 返回它（取不到 ⇒ None）。"""
    for ref in PRESET_BASELINE_REFS:
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-tree", "-r", "--name-only", ref],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            continue
        rels = [x for x in proc.stdout.splitlines() if x.startswith(PRESET_PREFIX_IN_REPO)]
        if not rels:
            continue
        out = Path(tempfile.mkdtemp(prefix="migao-preset-corpus-"))
        for rel in rels:
            blob = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "show", f"{ref}:{rel}"],
                capture_output=True, text=True,
            )
            if blob.returncode != 0:
                continue
            dst = out / Path(rel).relative_to(PRESET_PREFIX_IN_REPO)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(blob.stdout, encoding="utf-8")
        if (out / "skills").is_dir():
            return out
    return None


def preset_root() -> Path | None:
    """→ 装着预设内容的目录（其下有 `preset.yml` / `skills/`）；都取不到 ⇒ None。"""
    if _CACHE:
        return _CACHE[0]
    local = REPO_ROOT / PRESET_PREFIX_IN_REPO
    root: Path | None = local if (local / "skills").is_dir() else None
    if root is None:
        # ② 业务仓 git 基线（本机与 CI **同一份** ⇒ 消掉「镜像落后」造成的口径漂移）
        root = _materialize_from_git()
    if root is None and (PRESET_MIRROR / "skills").is_dir():
        # ③ 兜底：基线取不到（例如无 git 历史的工作副本）时才用本机镜像
        root = PRESET_MIRROR
    _CACHE.append(root)
    return root


def preset_path(rel: str) -> Path | None:
    """→ 预设目录下 `rel` 的**真实路径**（文件不一定存在：调用方自己判）。

    预设内容取不到（三种来源都没有）⇒ None —— 调用方必须**判红**，不许当「通过」。
    """
    root = preset_root()
    return (root / rel) if root else None


def preset_text(rel: str) -> str | None:
    """→ 预设目录下 `rel` 的文本；文件不在 / 预设取不到 ⇒ None。"""
    p = preset_path(rel)
    if p is None or not p.is_file():
        return None
    return p.read_text(encoding="utf-8", errors="ignore")


def corpus_help(rel: str) -> str:
    """读不到时的**可行动**说明（所有判据共用，别各写一份）。"""
    return (
        f"读不到预设内容 `{rel}`（S4 / issue #6020 后预设已迁出业务仓）。两条正路：\n"
        f"  · 本机：建预设仓镜像 —— `{PRESET_MIRROR}`（见 AGENTS.md「开发环境准备」）；\n"
        f"  · CI：让 git 基线里带着 `{PRESET_PREFIX_IN_REPO}`"
        f"（已试 {list(PRESET_BASELINE_REFS)} —— 注意 `pull_request` 检出需要 `fetch-depth: 0`）。"
    )


def require_preset_text(rel: str) -> str:
    """→ 文本；取不到 ⇒ **抛 AssertionError**（fail-closed，不许静默跳过）。"""
    text = preset_text(rel)
    if text is None:
        raise AssertionError(corpus_help(rel))
    return text


def require_preset_path(rel: str) -> Path:
    """→ 真实路径（文件必须存在）；取不到 ⇒ **抛 AssertionError**（fail-closed）。"""
    p = preset_path(rel)
    if p is None or not p.is_file():
        raise AssertionError(corpus_help(rel))
    return p
