#!/usr/bin/env python3
# case_ids: MC-131
"""预设搬运通道台账（`tests/unit_ci_workflows/preset_port_ledger.json`）的**唯一实现**（issue #6060）。

## 病（2026-10-02 实测，不是假说）

`.agent-presets/**`（研发模式：`migao-dev-flow` / `migao-acceptance` 技能 + `preset.yml` /
`agent.cordis.yml` + §15.7 承载体）从业务仓搬到独立仓 `zhaokai-mgzn/migao-agent-presets`。
S4（PR #6034 / 提交 `0e059836e`）在**删除业务仓那份之前**做「逐字节核对」，但核对用的是**过期基线**
（PR body 写「业务仓 1.102.0 vs 预设仓 1.103.0」，而业务仓 `origin/main` 当时**已是 1.104.0**）
⇒ 把「差一版」误判成「有意更新」⇒ **v1.104.0 从未被搬入即被删除**（已按 `b93fb8719` 补搬，预设仓 `42283c2`）。

**这类缺陷只能靠人回头发现** —— 没有任何判据回答「搬出去的东西，字节是不是真在目标仓里」。
本模块（`tests/unit_ci_workflows/preset_port_ledger.py`）+ 台账就是那个答案：**逐文件登记「业务仓最后承载的字节（blob）+ 搬入证据（预设仓 commit）」，
判据从业务仓 git 历史现取并与台账逐值相等**。

## 台账回答的两个问题（各自会红）

| # | 问题 | 判据 |
|---|---|---|
| 1 | **搬出去的文件集合**：「迁移退出的那一刻」业务仓 `.agent-presets/migao/**` 有哪些文件？ | 现取 `deletion.commit^` 的树 ⇄ 台账 `ports[].path` **双向相等**（多一个 / 少一个 ⇒ 红） |
| 2 | **每个文件的字节有没有到目标仓**：该文件最后承载的 blob 在预设仓哪个 commit 里？ | 台账逐条 `blob` / `last_commit` / `version` 与现取**逐值相等**；搬入证据字段必须齐备 |

另有「版本面」（`versions` / `version_ports`）：两份 `SKILL.md` 的**每一版**（版本号 + 版末 commit）都登记，
其中**在预设仓里按字节找得到**的那些登记搬入 commit；找不到的是**只许缩短**的缺口
（`version_evidence_gap.count` ≤ 判据侧镜像常量 `VERSION_EVIDENCE_GAP_MAX`）。

## 为什么判据读 **HEAD** 而不是只读 `origin/main`

「路径重新出现在业务仓」（反向迁移 / 回滚）会先在**分支**上出现。只读 `origin/main` ⇒ 该 PR 绿、
合并后才红（而 main 侧没有守护，见 `AGENTS.md` 铁律 9）⇒ 必然晚一拍。读 HEAD 让它在 **PR 面**就红。

## 用法

```bash
python3 tests/unit_ci_workflows/preset_port_ledger.py --write   # 现取两侧 git 重写台账（需预设仓镜像）
python3 tests/unit_ci_workflows/preset_port_ledger.py --check   # 只读判定，三态退出码 0/1/3
```

## 边界（照实登记；同时写进台账 `coverage_boundary`）

- **预设仓侧证据不在 CI 射程**：预设仓是私有仓、需网络 ⇒ CI 只核「业务仓侧逐值相等 + 证据字段形态」；
  证据的真实性由 `--write` 在**本机镜像**上按 blob 现取（`_preset_blob_map`），并可用 `--check` 复算
  （镜像存在时判据侧自动加强；镜像缺失时**不**报问题 —— 方向是「本机更严」，不是「本机假绿」）。
- 只覆盖「迁移退出那一刻存在的文件」；更早退场的预设文件不在面内。
- 判不了「预设仓里内容后来有没有被继续改坏」—— 那是活锚自检 / `scripts/drift_audit.py` 的射程。
- 依赖**非浅克隆**：浅克隆下 `git log` 会静默截断 ⇒ 环境判据直接判红（不是「无对象可判」）。

## 红证（注入式；见 `tests/unit_ci_workflows/test_preset_port_ledger.py`）

`problems()` 是纯函数（台账 × 现取 ⇒ 具名问题清单），判别力自证在内存里注入：多一个端口 / 少一个端口 /
blob 对不上 / 版本少一版 / 证据变长 / 证据字段缺失 / 路径重新出现在 HEAD —— 每种都**必须**报非空问题；
把这七个注入换成「恒绿」的 `problems()` ⇒ 自证判据当场红。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR.parent) not in sys.path:          # `tests/`（`from unit_ci_workflows import ...`）
    sys.path.insert(0, str(_THIS_DIR.parent))

from unit_ci_workflows import preset_corpus as pc  # noqa: E402  （唯一预设读取口径）

LEDGER_PATH = _THIS_DIR / "preset_port_ledger.json"

SCHEMA = "preset-port-ledger/v1"
#: 预设内容在**业务仓**里的前缀（S4 之前的位置 = 搬运的**源**）。
#: 🔴 **不自己定义**：唯一口径 = `preset_corpus.PRESET_PREFIX_IN_REPO`（剥前缀同样只走
#: `preset_corpus.preset_relative`）—— 二次定义会被 `test_single_preset_reader.py` 判红。
PRESET_PREFIX = pc.PRESET_PREFIX_IN_REPO
#: 预设仓里对应的根（S4 起 preset 仓的仓根**就是** preset 目录，不再有 `.agent-presets/migao/` 这层）。
PRESET_REPO = "zhaokai-mgzn/migao-agent-presets"
#: 迁移**退出点**：业务仓删除 `.agent-presets/**` 的那次提交（PR #6034 / S4）。
#: 🔴 它是台账的**坐标原点**：现取的「搬出去的文件集合」= 这次提交的**父**树。
DELETION_COMMIT = "0e059836e7efbf8326d12d9a78f0955110927ce1"
#: 预设仓镜像（活锚 = 预设仓检出的仓根；`MIGAO_PRESET_MIRROR` 可覆盖）。
PRESET_MIRROR_ENV = "MIGAO_PRESET_MIRROR"
DEFAULT_PRESET_MIRROR = Path.home() / "migao-dev-preset-anchor"

#: 每个**端口**（= 一个被搬出去的预设文件）的「为什么它必须存在」+「什么时候要重开这件事」。
#: 🔴 这是**人写**的语义字段；机械字段（blob / commit / version）一律由 `--write` 现取，不手抄。
PORTS = {
    ".gitignore": {
        "why": "预设内容的忽略规则（`__pycache__` 等）；丢了它，预设仓镜像与检出会把构建垃圾带进版本库，"
               "而「垃圾被提交」不会让任何判据变红。",
        "restart_condition": "预设仓改用自己的忽略策略（有意不再逐字节同步该文件）⇒ 删掉本条，"
                             "并在台账 `coverage_boundary` 写明理由与日期（不许静默少一条）。",
    },
    "README.md": {
        "why": "预设仓的接线与运维说明入口：活锚建镜像 / 换链 / 刷新自检的 ①~④ 就在这份文件里，"
               "丢了新会话就不知道该去哪拿研发模式（DSH 静默加载不到，且不报错）。",
        "restart_condition": "预设仓的接线口径整体改变（例如镜像路径约定 `$HOME/migao-dev-preset-anchor` 换名）"
                             "⇒ 先改预设仓 README，再回来重算本条 blob。",
    },
    "agent.cordis.yml": {
        "why": "观星台研发 preset 的 agent 接线（compaction 旋钮 `thresholdRatio` / `retainRatio`、技能清单）；"
               "丢版会让这类旋钮**静默回退**（§29 实测：旧臂继续跑旧配置且不报错）。",
        "restart_condition": "preset 的接线机制迁到新载体（例如 DSH realm 配置取代 agent.cordis.yml）"
                             "⇒ 本条必须随新载体重开，并把旧载体登记进 `coverage_boundary`。",
    },
    "preset.yml": {
        "why": "preset 元数据（`name` / `description` / `skills` 清单）；丢版 ⇒ DSH 发现不到该 preset，"
               "或加载到旧描述 —— 两种都不会让任何东西变红。",
        "restart_condition": "preset 发现口径变化（`USER_PRESET_DIR` / 拓扑 A·B 切换）⇒ 重新核对本条的落点。",
    },
    "skills/migao-acceptance/CHANGELOG.md": {
        "why": "验收协议的版本沿革；丢版 ⇒ 「这条纪律为什么存在」不可回溯，纪律退化成口号"
               "（`migao-acceptance` 的 L1/L2/UA 与红证口径都靠它溯源）。",
        "restart_condition": "沿革改由别的载体承载（例如并入业务仓 docs）⇒ 登记新载体后再删本条。",
    },
    "skills/migao-acceptance/SKILL.md": {
        "why": "验收协议本体（L1/L2/UA 断言降级、红证、双 AI 交叉验证、修复必须重放）；"
               "丢版 ⇒ 「验收通过」不再有可执行约束，只剩自然语义。",
        "restart_condition": "技能被拆分 / 改名（例如验收协议并入 dev-flow）⇒ 按新形态重登记，"
                             "不许让「有技能的仓里少一份技能」无人发现。",
    },
    "skills/migao-dev-flow/CHANGELOG.md": {
        "why": "研发流程沿革（v1.95.0 起移出加载面 = 每次加载不再付历史账，但**必须**仍然可回溯）；"
               "丢版 ⇒ 纪律的出处与引入时点全部消失（本单 #6060 的教训正是这一条：2026-10-02 那天丢了 1.104.0）。",
        "restart_condition": "沿革拆成多文件 / 移出预设仓 ⇒ 重登记新落点。",
    },
    "skills/migao-dev-flow/SKILL.md": {
        "why": "研发流程本体（铁律 1~13、§1~§33）；**2026-10-02 丢的就是它** —— v1.104.0（#6033）"
               "从未被搬入预设仓即被 S4 删除，靠人工发现才补搬（预设仓 `42283c2`）。",
        "restart_condition": "技能在本仓重新出现（反向迁移 / 回滚）⇒ 立刻重算：本台账的「已删除」前提不再成立。",
    },
    "skills/migao-dev-flow/scripts/ui-multimodal-acceptance.mjs": {
        "why": "§15.7「改 web 页面必跑一轮页面多模态验收」的**可执行承载体**；"
               "丢版 ⇒ 该硬约束只剩散文，没有任何东西会跑。",
        "restart_condition": "承载体改由别的脚本 / 服务承载 ⇒ 登记新路径并写明替换关系。",
    },
}

#: 版本号形态（台账 `versions[].version` / `version_ports[].version`）。
_VERSION_RE = re.compile(r"^version:\s*(\S+)\s*$", re.M)
#: **只许缩短**的版本证据缺口上限（起点 = 本单生成时的现取缺口）。
#: 🔴 判据侧 `tests/unit_ci_workflows/test_preset_port_ledger.py` 另有一份**同值**镜像常量，
#: 且判据会断言两者相等 ⇒ 放宽必须**同时改两处**（diff 里看得见），不许单边改数字消红。
VERSION_EVIDENCE_GAP_MAX = 97

#: git 对象 id（abbrev ≥ 7 即可，但台账里一律存**全** id）。
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class LedgerToolError(RuntimeError):
    """机具自身不可判定（浅克隆 / 坐标取不到）—— 调用方据此输出 `3`，**不得**当 `0` 读。"""


def _git(repo, *args: str) -> str | None:
    """→ stdout（strip）；失败 → None（刻意不抛：调用方要区分「取不到」与「取到空」）。"""
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="surrogateescape",
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def _git_out(repo, *args: str) -> str:
    out = _git(repo, *args)
    if out is None:
        raise LedgerToolError(f"git {' '.join(args)} 失败（repo={repo}）")
    return out


def _frontmatter_version(text: str) -> str | None:
    """→ YAML frontmatter 里的 `version:`（只认首个 `---` 块；取不到 ⇒ None）。"""
    lines = text.lstrip("\ufeff").splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        m = _VERSION_RE.match(line)
        if m:
            return m.group(1)
    return None


def mirror_root() -> Path | None:
    """→ 预设仓镜像仓根（存在且是 git 仓才算）；否则 None。"""
    raw = (os.environ.get(PRESET_MIRROR_ENV) or "").strip()
    root = Path(raw).expanduser() if raw else DEFAULT_PRESET_MIRROR
    return root if (root / ".git").exists() else None


def _preset_blob_map(mirror: Path, preset_path: str) -> dict[str, tuple[str, str]]:
    """→ {blob: (commit, date)} = 预设仓历史上该路径**每个**出现过的字节（首次出现的 commit + 日期）。

    「按字节找得到」是这套证据的**唯一**口径：blob 是内容寻址的 ⇒ 同名不同内容不会被误认。
    """
    out: dict[str, tuple[str, str]] = {}
    commits = (_git(mirror, "log", "--reverse", "--format=%H", "--", preset_path) or "").split()
    for commit in commits:
        if not commit:
            continue
        blob = _git(mirror, "rev-parse", f"{commit}:{preset_path}")
        if not blob or blob in out:
            continue
        date = _git(mirror, "show", "-s", "--format=%cs", commit) or ""
        out[blob] = (commit, date)
    return out


def _version_history(repo: Path, path: str) -> list[dict]:
    """→ 该路径**每一版**（版本号 → 版末 commit），按版本**首次出现**的时序排列。

    口径：`git log --reverse -- <path>` 逐提交读 frontmatter 的 `version:`；同一版本出现在多次提交里时，
    锚点取**版末**那次（`1.30.0` 实测两次提交、内容不同 ⇒ 取最后那次才是「这一版最终承载的字节」）。
    """
    commits = (_git_out(repo, "log", "--reverse", "--format=%H", "--", path)).split()
    order: list[str] = []
    anchor: dict[str, str] = {}
    for commit in commits:
        if not commit:
            continue
        text = _git(repo, "show", f"{commit}:{path}")
        if text is None:                       # 该提交里路径不存在（删除）
            continue
        version = _frontmatter_version(text)
        if version is None:
            continue
        if version not in anchor:
            order.append(version)
        anchor[version] = commit
    return [{"version": v, "commit": anchor[v]} for v in order]


def observe(repo: Path = REPO_ROOT) -> dict:
    """→ 现取读数（**只读 git 对象，禁读工作树**）。判据与机具共用这一份。"""
    shallow = (_git(repo, "rev-parse", "--is-shallow-repository") or "").strip() == "true"
    parent = f"{DELETION_COMMIT}^"
    if _git(repo, "rev-parse", "--verify", "--quiet", parent) is None:
        raise LedgerToolError(
            f"取不到迁移退出点 {DELETION_COMMIT[:9]} 的父提交 ⇒ 基线历史不完整（不可判定）"
        )
    paths = [
        p for p in
        (_git_out(repo, "ls-tree", "-r", "--name-only", parent, "--", PRESET_PREFIX)).splitlines()
        if p
    ]
    paths.sort()
    ports: dict[str, dict] = {}
    versions: list[dict] = []
    head_present: list[str] = []
    last_touch: dict[str, str] = {}
    for path in paths:
        blob = _git(repo, "rev-parse", f"{parent}:{path}")
        last_commit = _git(repo, "rev-list", "-1", parent, "--", path)
        text = _git(repo, "show", f"{parent}:{path}")
        ports[path] = {
            "last_commit": last_commit,
            "blob": blob,
            "version": _frontmatter_version(text) if text is not None else None,
        }
        if _git(repo, "rev-parse", "--verify", "--quiet", f"HEAD:{path}") is not None:
            head_present.append(path)
        touch = _git(repo, "rev-list", "-1", "HEAD", "--", path)
        if touch:
            last_touch[path] = touch
        for row in _version_history(repo, path):
            versions.append({"path": path, **row})
    return {
        "ref": (_git(repo, "rev-parse", "HEAD") or "").strip(),
        "shallow": shallow,
        "deletion_parent": parent,
        "paths": ports,
        "versions": versions,
        "head_present": head_present,
        "last_touch": last_touch,
    }


def build_ledger(observed: dict, mirror: Path, repo: Path = REPO_ROOT) -> dict:
    """→ 台账（**机械字段全部现取**；人写字段来自 `PORTS`）。`--write` 的唯一入口。"""
    ports = []
    version_ports = []
    for path in sorted(observed["paths"]):
        rel = pc.preset_relative(path)
        annotation = PORTS.get(rel)
        if annotation is None:
            raise LedgerToolError(
                f"未登记的预设端口：{path}\n"
                f"处置：在 {Path(__file__).name} 的 `PORTS` 里补 `why` / `restart_condition`，再跑 --write"
            )
        row = observed["paths"][path]
        blob_map = _preset_blob_map(mirror, rel)
        evidence = blob_map.get(row["blob"] or "")
        ports.append({
            "path": path,
            "preset_path": rel,
            "why": annotation["why"],
            "restart_condition": annotation["restart_condition"],
            "last_commit": row["last_commit"],
            "blob": row["blob"],
            "version": row["version"],
            "preset_repo_commit": evidence[0] if evidence else None,
            "ported_at": evidence[1] if evidence else None,
        })
        for vrow in [v for v in observed["versions"] if v["path"] == path]:
            blob = _git(repo, "rev-parse", f"{vrow['commit']}:{path}")
            hit = blob_map.get(blob or "")
            if hit is None:
                # 没有逐版搬入证据的版本**不进** version_ports —— 它是「缺口」，
                # 由下方 count 表达（只许缩短）；写进来会让缺口读数恒为 0（假绿）。
                continue
            version_ports.append({
                "path": path,
                "version": vrow["version"],
                "business_commit": vrow["commit"],
                "blob": blob,
                "preset_repo_commit": hit[0] if hit else None,
                "ported_at": hit[1] if hit else None,
            })
    total_versions = len(observed["versions"])
    gap = total_versions - len(version_ports)
    missing_ports = [p["path"] for p in ports if not p["preset_repo_commit"]]
    return {
        "schema": SCHEMA,
        "issue": 6060,
        "what": (
            "「业务仓 → 预设仓」这条**预设搬运通道**的台账：迁移退出点（S4 删除 `.agent-presets/**`）"
            "那一刻业务仓里**每个**预设文件，逐条登记「为什么它必须存在」「什么时候要重开这件事」"
            "+ **最后承载的字节（blob）与搬入证据（预设仓 commit）**；另登记两份 `SKILL.md` 的**每一版**。"
            "判据 = `tests/unit_ci_workflows/test_preset_port_ledger.py`（现取业务仓 git 历史，与台账**逐值相等**："
            "多一个端口 / 少一个端口 / blob 对不上 / 版本少一版 / 证据变长 ⇒ 红）。"
        ),
        "why": (
            "2026-10-02 S4（#6034 / `0e059836e`）删除业务仓 `.agent-presets/**` 之前用**过期基线**做逐字节核对："
            "PR body 写「业务仓 1.102.0 vs 预设仓 1.103.0」，而业务仓 `origin/main` 当时已是 **1.104.0** ⇒ "
            "把「差一版」误判成「有意更新」⇒ **v1.104.0（#6033）从未被搬入预设仓就被删**（事后按 `b93fb8719` 补搬，"
            "预设仓 `42283c2`）。⇒ 缺的不是流程文字，是「搬出去的东西字节是不是真在目标仓里」这个**读数**："
            "本台账把它变成会变红的东西 —— 未登记即红、登记了但现取没有即红、字节对不上即红、"
            "版本证据缺口只许缩短。"
        ),
        "judged_by": "tests/unit_ci_workflows/test_preset_port_ledger.py",
        "generated_by": "python3 tests/unit_ci_workflows/preset_port_ledger.py --write（现取两侧 git；机械字段**不手抄**）",
        "deletion": {
            "commit": DELETION_COMMIT,
            "date": "2026-10-02",
            "subject": "chore(ci): #6020 S4 —— 业务仓不再承载预设，链路改指预设仓（+ 台账/机具校正） (#6034)",
            "pr": 6034,
            "paths_from": PRESET_PREFIX,
        },
        "preset_repo": PRESET_REPO,
        "ports": ports,
        "versions": observed["versions"],
        "version_ports": version_ports,
        "version_evidence_gap": {
            "count": gap,
            "reason": (
                f"业务仓 {total_versions} 个版本条目里，只有 {len(version_ports)} 个能在预设仓按**字节**找回来："
                "预设仓 2026-09-14 才建立、且中途是**周期快照**形态（S1 的 `35f7cdf` 一次性迁回 "
                "≤v1.102.0 的改动，其中 1.100.0→1.102.0 的漏搬用 `0a82aa8` 补齐）⇒ 中间的多数版本没有"
                "「逐版」搬入 commit。**如实登记的缺口**：只许缩短（补出一版证据 ⇒ count 下降），不许变长"
                "（判据侧 `VERSION_EVIDENCE_GAP_MAX` 镜像同值，放宽要同时改两处，diff 里看得见）。"
            ),
            "restart_condition": "预设仓历史被重写（force-push / 重建仓）⇒ 全部证据失效，先重新跑 --write 并逐条人工核对，"
                                  "再决定是补证据（count 下降）还是把缺口原因写进 `coverage_boundary`。",
        },
        "evidence_note": {
            "no_evidence_ports": missing_ports,
            "quote": "`preset_repo_commit` = 预设仓历史上**首次**出现该 blob 的 commit（内容寻址 ⇒ 同字节才认）；"
                     "`ported_at` = 该 commit 的**提交日期**（`git show -s --format=%cs`，不是搬运决策日期）。",
        },
        "coverage_boundary": [
            {"face": "预设仓侧证据的真实性（`preset_repo_commit` 指向的字节）",
             "reason": "预设仓是**私有仓**、需要网络 ⇒ CI 侧判据只核「业务仓侧逐值相等 + 证据字段形态」；"
                       "证据由 `--write` 在**本机镜像**上按 blob 现取。镜像存在时 `--check` 会**加强**核验"
                       "（本机更严），镜像缺失时**不**报问题（CI 与无镜像机器口径一致）。",
             "recompute": "python3 scripts/preset_port_ledger.py --check（有镜像 ⇒ 逐条解析 commit:path 比 blob）"},
            {"face": "更早退场的预设文件",
             "reason": "只覆盖「迁移退出那一刻存在」的文件（`deletion.commit^` 的树）；2026-09-14 那次并入后又被删的"
                       "（如 `tdd-iron-law`）不在面内 —— 它们不在 S4 的搬运清单里。",
             "recompute": "git ls-tree -r --name-only <deletion>^ -- .agent-presets/"},
            {"face": "预设仓内容后来有没有被继续改坏",
             "reason": "本台账判「搬出去时的字节找到了」，判不了「之后有没有被改丢」—— 那是活锚自检与 "
                       "`scripts/drift_audit.py` 的 `sync-copy` 射程。",
             "recompute": "./scripts/preset-anchor-check.sh"},
            {"face": "「中间某一版丢了」的细粒度判定",
             "reason": "版本面用**冻结计数**表达缺口（`version_evidence_gap.count`，只许缩短），不逐版要求证据 —— "
                       "逐版要求会把 2026-09-14 之前的快照形态判成永久红。",
             "recompute": "python3 -m pytest tests/unit_ci_workflows/test_preset_port_ledger.py -q"},
            {"face": "预设内容本身的质量",
             "reason": "台账只裁**搬运关系**（文件集合 / 字节 / 证据），不为技能内容是否正确背书。",
             "recompute": "（无需复算：本表不是质量排行榜）"},
            {"face": "浅克隆对**版本面**的截断",
             "reason": "路径集合 / blob / 版末提交读的是 `deletion.commit^` 的树与提交，不受克隆深度影响；"
                       "只有「每一版」要从 `git log` 现取 ⇒ 浅克隆若把它截断，判据会以「版本缺失」判红并附 "
                       "`--unshallow` 提示（**不是**静默绿）。CI 侧由 `ci workflow helper unit tests` job 的 "
                       "`fetch-depth: 0` 承担。",
             "recompute": "git rev-parse --is-shallow-repository"},
        ],
    }


def _sha(value) -> bool:
    return isinstance(value, str) and bool(_SHA_RE.match(value))


def _problem_names(problems: list[str]) -> str:
    return "；".join(problems[:6]) + (f" …（共 {len(problems)} 条）" if len(problems) > 6 else "")


def problems(ledger: dict, observed: dict, mirror: Path | None = None) -> list[str]:
    """**纯函数**：台账 × 现取读数 ⇒ 具名问题清单（空 = 通过）。判据与 `--check` 共用这一份。"""
    out: list[str] = []
    if not isinstance(ledger, dict):
        return ["台账不是 JSON 对象（fail-closed）"]
    if ledger.get("schema") != SCHEMA:
        out.append(f"台账 schema 必须是 {SCHEMA}，现取 {ledger.get('schema')!r}")
    if not ledger.get("ports"):
        out.append("台账 `ports` 为空 —— 没登记的搬运关系不许当通过（fail-closed）")
    if (ledger.get("deletion") or {}).get("commit") != DELETION_COMMIT:
        out.append(f"台账 `deletion.commit` 必须等于迁移退出点 {DELETION_COMMIT[:9]}（坐标原点不许漂移）")

    observed_paths = set(observed["paths"])
    entries = [e for e in (ledger.get("ports") or []) if isinstance(e, dict)]
    registered = [e.get("path") for e in entries]

    # 判据 A：文件集合**双向相等** —— 这是「未登记即红」与「登记了但现取不存在即红」。
    for path in sorted(observed_paths - set(registered)):
        out.append(f"未登记即红：现存于 `deletion.commit^` 树里的预设端口没有台账条目 ⇒ {path}")
    for path in sorted(set(registered) - observed_paths):
        out.append(f"登记了但现取不存在：台账端口在 `deletion.commit^` 树里找不到 ⇒ {path}")
    if len(registered) != len(set(registered)):
        out.append("台账 `ports` 里有重复 path（同一端口登两次 ⇒ 台账失去一对一语义）")

    # 判据 B：逐条与真值**逐值相等**（path 映射 / blob / 版本 / why / 证据字段）。
    for entry in entries:
        path = entry.get("path")
        if path not in observed["paths"]:
            continue
        truth = observed["paths"][path]
        if entry.get("preset_path") != pc.preset_relative(path):
            out.append(f"`preset_path` 与源路径不同源：{path} ⇒ 现取 {pc.preset_relative(path)!r}")
        if entry.get("blob") != truth["blob"]:
            out.append(f"字节对不上（blob）：{path} 台账 {str(entry.get('blob'))[:9]} vs 现取 {str(truth['blob'])[:9]}")
        if entry.get("last_commit") != truth["last_commit"]:
            out.append(f"版末提交对不上：{path} 台账 {str(entry.get('last_commit'))[:9]} vs 现取 {str(truth['last_commit'])[:9]}")
        if entry.get("version") != truth["version"]:
            out.append(f"最后承载的版本对不上：{path} 台账 {entry.get('version')!r} vs 现取 {truth['version']!r}")
        for field in ("why", "restart_condition"):
            if not str(entry.get(field) or "").strip():
                out.append(f"端口条目缺 `{field}`：{path}（这两条是「为什么必须存在 / 什么时候重开」的唯一承载体）")
        if not _sha(entry.get("preset_repo_commit")):
            out.append(f"搬入证据缺失/非法：{path} 的 `preset_repo_commit` = {entry.get('preset_repo_commit')!r}")
        elif not _DATE_RE.match(str(entry.get("ported_at") or "")):
            out.append(f"搬入证据缺 `ported_at`（YYYY-MM-DD）：{path}")

    # 判据 C：删除是**真的**，且之后没人把路径塞回来。
    for path in sorted(observed_paths):
        if path in observed["head_present"]:
            out.append(f"路径重新出现在 HEAD：{path} ⇒ 台账「已搬走」的前提不成立，先重算再改台账")
        if observed["last_touch"].get(path) != DELETION_COMMIT:
            out.append(
                f"该路径在 migration 之后又被动过：{path} 最近一次改动 "
                f"{str(observed['last_touch'].get(path))[:9]} ≠ {DELETION_COMMIT[:9]}"
            )

    # 判据 D：版本面**逐值相等**（每版一条，多一版 / 少一版 / 对不上 ⇒ 红）。
    ledger_versions = [
        {"path": v.get("path"), "version": v.get("version"), "commit": v.get("commit")}
        for v in (ledger.get("versions") or []) if isinstance(v, dict)
    ]
    if ledger_versions != observed["versions"]:
        registered_v = {(v["path"], v["version"], v["commit"]) for v in ledger_versions}
        for row in observed["versions"]:
            key = (row["path"], row["version"], row["commit"])
            if key not in registered_v:
                out.append(f"未登记即红（版本）：{row['path']} 的 {row['version']}（{row['commit'][:9]}）不在台账里")
        text = {(v["path"], v["version"]) for v in ledger_versions}
        for row in observed["versions"]:
            if (row["path"], row["version"]) in text and row not in ledger_versions:
                out.append(f"版本对不上：{row['path']} 的 {row['version']} 现取 commit {row['commit'][:9]}")
        for row in ledger_versions:
            if row not in observed["versions"] and (row["path"], row["version"]) not in text:
                out.append(f"登记了但现取不存在（版本）：{row['path']} 的 {row['version']}")

    if observed.get("shallow") and (len(ledger_versions) != len(observed["versions"])):
        out.append(
            "环境提示：本仓是**浅克隆**且版本条目数对不上 ⇒ 先 `git fetch --unshallow` 再判"
            "（CI 侧 fetch-depth: 0，见 .github/workflows/pr-check.yml）"
        )

    # 判据 E：版本搬入证据 —— 每条都能落到「已登记的端口 + 已登记的版本 + 真实的业务 commit」。
    truth_versions = {(v["path"], v["version"]): v["commit"] for v in observed["versions"]}
    seen_versions: set[tuple] = set()
    for row in (ledger.get("version_ports") or []):
        key = (row.get("path"), row.get("version"))
        if key not in truth_versions:
            out.append(f"版本证据指向不存在的版本：{key[0]} {key[1]}")
            continue
        if key in seen_versions:
            out.append(f"版本证据重复登记：{key[0]} {key[1]}")
        seen_versions.add(key)
        if row.get("business_commit") != truth_versions[key]:
            out.append(
                f"版本证据的 business_commit 对不上：{key[0]} {key[1]} "
                f"台账 {str(row.get('business_commit'))[:9]} vs 现取 {truth_versions[key][:9]}"
            )
        if not _sha(row.get("preset_repo_commit")):
            out.append(f"版本证据缺 `preset_repo_commit`：{key[0]} {key[1]}")
        elif not _DATE_RE.match(str(row.get("ported_at") or "")):
            out.append(f"版本证据缺 `ported_at`（YYYY-MM-DD）：{key[0]} {key[1]}")

    # 判据 F：缺口**只许缩短**（现取 ⇄ 台账 ⇄ 判据侧镜像常量）。
    gap = len(observed["versions"]) - len(seen_versions)
    declared = (ledger.get("version_evidence_gap") or {}).get("count")
    if declared != gap:
        out.append(f"版本证据缺口读数对不上：台账 {declared!r} vs 现取 {gap}（不许手改这个数）")
    if gap > VERSION_EVIDENCE_GAP_MAX:
        out.append(
            f"版本证据缺口变长：{gap} > 冻结上限 {VERSION_EVIDENCE_GAP_MAX}"
            "（只许缩短；补证据会让它下降）"
        )

    # 判据 G（**可选加强**，镜像存在才跑）：证据指向的预设仓 commit 里，确实是那份字节。
    if mirror is not None:
        for entry in entries:
            commit = entry.get("preset_repo_commit")
            if not _sha(commit) or entry.get("path") not in observed["paths"]:
                continue
            preset_path = pc.preset_relative(entry["path"])
            blob = _git(mirror, "rev-parse", f"{commit}:{preset_path}")
            if blob is None:
                out.append(f"预设仓证据不可解析：{preset_path} 在 {str(commit)[:9]} 不存在（镜像刷新过？）")
            elif blob != observed["paths"][entry["path"]]["blob"]:
                out.append(f"预设仓证据字节不一致：{preset_path}@{str(commit)[:9]} = {blob[:9]} ≠ 业务仓版末 blob")
    return out



def check(repo: Path = REPO_ROOT, ledger_path: Path = LEDGER_PATH) -> tuple[int, list[str]]:
    """→ (rc, problems)。rc：0 = 通过 / 1 = 判红 / 3 = 不可判定（fail-closed，**不得**当 0 读）。"""
    try:
        observed = observe(repo)
    except LedgerToolError as exc:
        return 3, [f"不可判定：{exc}"]
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return 1, [f"台账不可读/不可解析（fail-closed）：{ledger_path}（{exc.__class__.__name__}）"]
    found = problems(ledger, observed, mirror=mirror_root())
    return (0 if not found else 1), found


def _write(repo: Path, ledger_path: Path) -> int:
    mirror = mirror_root()
    if mirror is None:
        print(
            "❌ 找不到预设仓镜像（`$MIGAO_PRESET_MIRROR` 或 `$HOME/migao-dev-preset-anchor`）—— "
            "没有镜像就无法按字节取搬入证据，拒绝生成（不猜、不手抄）。\n"
            "   处置：按 AGENTS.md「开发环境准备」建镜像；只想判红请用 --check。",
            file=sys.stderr,
        )
        return 3
    try:
        observed = observe(repo)
    except LedgerToolError as exc:
        print(f"❌ 不可判定：{exc}", file=sys.stderr)
        return 3
    try:
        ledger = build_ledger(observed, mirror, repo)
    except LedgerToolError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    ledger_path.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(
        f"✅ 已写 {ledger_path}\n"
        f"   端口 {len(ledger['ports'])} 条 · 版本 {len(ledger['versions'])} 条 · "
        f"版本证据 {len(ledger['version_ports'])} 条 · 证据缺口 {ledger['version_evidence_gap']['count']} 条"
        f" · 镜像 {mirror}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="预设搬运通道台账（issue #6060）")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="现取两侧 git，重写台账（需要预设仓镜像）")
    mode.add_argument("--check", action="store_true", help="只读判定（三态退出码 0/1/3）")
    args = parser.parse_args(argv)
    if args.write:
        return _write(REPO_ROOT, LEDGER_PATH)
    rc, found = check()
    if rc == 3:
        print(f"⏭️  {found[0]}", file=sys.stderr)
        return 3
    if rc:
        print(f"❌ 预设搬运通道台账判红（{len(found)} 条）：")
        for item in found:
            print(f"  · {item}")
        return 1
    print("✅ 预设搬运通道台账 ⇄ 业务仓 git 历史逐值相等（端口 / blob / 版本 / 证据缺口）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
