# case_ids: MC-012
"""预设语料快照的完整性判据（S4 终态 / issue #6071）—— CI 无凭据可达的默认事实源。

## 病（本单的现场读数，不是推断）

`preset_corpus` 的 ②「git 基线带 `.agent-presets/migao/`」是**过渡态假设**：S4 迁移 PR 合并后
`origin/main` 自身不再带该目录 ⇒ 基线候选全空；预设仓 PRIVATE（CI actions 无凭据 clone）、
runner 也没有本地镜像 ⇒ `require_preset_*` fail-closed 抛「两条正路」—— 而那两条正路在 CI
一条都走不通（镜像建不了、基线已无物）。实测双爆：`ci workflow helper unit tests`（8m23s）与
`Post-Merge Verify (定向跑判据面)`（53s），均在**采集期** AssertionError
（`test_ui_multimodal_acceptance_carrier` 等 4 个消费方文件）。

## 本文件锁什么（每条都能单独变红；红证 = 内存注入，见文末）

| # | 判据 | 取法 |
|---|---|---|
| 1 | 快照文件与 `MANIFEST.json` 登记的 sha256 **逐字节一致**（快照不许被手改烂 / 登记不许过期） | hashlib 对照 |
| 2 | MANIFEST 记录来源 commit（40 位 hex）与预设仓仓名（可溯源到权威源） | 逐字锚 |
| 3 | `preset_corpus.preset_root()` 在本仓终态下确实命中**快照级**，且 4 个被判据读取的 rel 全读得到 | 行为断言 |

**红证**：改快照任一文件一个字节 ⇒ 判据 1 红；删 MANIFEST 登记条目 ⇒ 判据 1 红；
把 MANIFEST.source_commit 改成短哈希 ⇒ 判据 2 红；在仓库根重建 `.agent-presets/migao/skills/` 空目录
（① 抢占）⇒ 判据 3 红（说明取数级命中变了，反向验证场景可见）。

**镜像漂移说明**：本机镜像工作树天然可能落后预设仓 origin/main（S4 前的实测教训），
对比「镜像 vs 快照」会制造「本机红 / CI 绿」的新口径分裂 ⇒ 不判；快照来源以
MANIFEST.source_commit（预设仓 origin/main）为唯一事实，同步义务显式化在 preset_corpus 头注释。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

_TEST_DIR = Path(__file__).resolve().parent
sys.path.append(str(_TEST_DIR))

from unit_ci_workflows import preset_corpus  # noqa: E402

SNAPSHOT = _TEST_DIR / "preset_snapshot"
MANIFEST = SNAPSHOT / "MANIFEST.json"

#: 被判据读取的全部 rel（与 preset_corpus 消费方对齐；新增消费 rel 必须进快照并重新登记）
CONSUMED_RELS = (
    "preset.yml",
    "agent.cordis.yml",
    preset_corpus.DEV_FLOW_SKILL_REL,
    preset_corpus.DEV_FLOW_CARRIER_REL,
)


def test_manifest_is_traceable_source_of_truth():
    """判据 2：MANIFEST 溯源字段在场（来源仓 + 40 位 commit）。"""
    assert MANIFEST.is_file(), (
        "预设语料快照缺 MANIFEST.json ⇒ 快照无溯源（从预设仓 origin/main 物化后登记）"
    )
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data.get("source_repo") == "zhaokai-mgzn/migao-agent-presets", (
        f"MANIFEST.source_repo 不是权威源：{data.get('source_repo')!r}"
    )
    commit = data.get("source_commit") or ""
    assert len(commit) == 40 and all(c in "0123456789abcdef" for c in commit), (
        f"MANIFEST.source_commit 必须是 40 位完整哈希（溯源到具体提交）：{commit!r}"
    )


def test_snapshot_files_match_manifest_hashes():
    """判据 1：快照逐字节 = MANIFEST 登记（手改烂 / 登记过期都会红）。"""
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    files = data.get("files") or {}
    assert files, "MANIFEST.files 为空 ⇒ 快照未登记任何文件"
    for rel, meta in files.items():
        p = SNAPSHOT / rel
        assert p.is_file(), f"快照缺文件：{rel}（MANIFEST 登记了但文件不在）"
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        assert digest == (meta or {}).get("sha256"), (
            f"快照 {rel} 与 MANIFEST 哈希不一致（文件被手改 / 登记过期）⇒ 从预设仓 "
            f"origin/main 重物化并重新登记"
        )
    # 登记集必须覆盖全部消费 rel（否则 CI 上会退回 fail-closed 红）
    for rel in CONSUMED_RELS:
        assert rel in files, (
            f"消费 rel `{rel}` 未登记进快照（新增 preset_corpus 消费方必须同步物化 + 登记）"
        )


def test_preset_root_hits_snapshot_and_all_consumed_rels_readable():
    """判据 3：终态（本仓无 .agent-presets）下取数级命中快照，消费 rel 全部可读。"""
    legacy = preset_corpus.REPO_ROOT / preset_corpus.PRESET_PREFIX_IN_REPO
    if (legacy / "skills").is_dir():
        return  # ① 本仓重新出现预设目录（反向验证 / 回滚场景）：取数级判它，本判据不适用
    root = preset_corpus.preset_root()
    assert root is not None, preset_corpus.corpus_help("preset.yml")
    assert Path(root).resolve() == SNAPSHOT.resolve(), (
        f"取数级未命中快照：preset_root() = {root!r}（S4 终态默认应为 preset_snapshot/）"
    )
    for rel in CONSUMED_RELS:
        text = preset_corpus.preset_text(rel)
        assert text, f"快照级读不到 {rel}（消费判据在 CI 会退回 fail-closed 红）"
