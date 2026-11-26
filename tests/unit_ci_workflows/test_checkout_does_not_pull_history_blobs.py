# case_ids: MC-369
"""只要 tree 的腿**不得**拉全史 blob（issue #9120 A 类减负；现取口径 = **全仓**工作流）。

## 病（现取）

8 条 A 类腿的预算（8–26s）**低于固定成本**，而固定成本的大头是 `actions/checkout@v7`（实测 14–24s）：
`fetch-depth: 0` 把 60 天历史**全部 blob** 拉下来（现取 `.git` 462 MiB），而它们的 git 用法只有
`git diff --name-only …`（**tree 级**，不需要任何历史 blob）。

## 判据（两条方向都要管）

1. **需要树的腿**：`git diff --name-only` / `--diff-filter` 这类只读**名字与状态**的 job，
   `fetch-depth: 0` 必须配 `filter: blob:none`；
2. **需要内容的腿**（反向锁）：**跑 `git log -p` / `git diff`（patch）/ `git grep` 的块**（现取 = gitleaks）
   **不得**用 `blob:none` —— 那些命令要 blob，partial clone 会把它们变成逐对象懒拉取（比全史更慢）。
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

#: 只读 tree 的 git 用法（不需要历史 blob）
TREE_ONLY = re.compile(r"git diff\s+(?:--diff-filter=\w+\s+)?(?:--name-only|--name-status)")
#: 需要 blob 的腿（**显式清单**，不靠正则猜）：这些腿的 git 用法要**历史内容**，
#: 抽掉 blob 会让每次读变成逐对象懒拉取（比全史更慢且要联网）。
#:
#: - `gitleaks-scan`：`gitleaks detect --log-opts=<base>..HEAD` 要逐 commit 的 **diff 内容**
NEEDS_BLOB_JOBS = {"gitleaks-scan"}


def _jobs() -> dict[tuple[str, str], dict]:
    """现取全仓工作流的每个 job ⇒ {(文件, job_id): job}。"""
    out: dict[tuple[str, str], dict] = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for jid, job in (doc.get("jobs") or {}).items():
            out[(path.name, jid)] = job or {}
    return out


def _body(job: dict) -> str:
    return "\n".join(str(s.get("run") or "") for s in job.get("steps") or [])


def test_tree_only_jobs_use_blobless_partial_clone():
    offenders: list[str] = []
    for (fname, jid), job in _jobs().items():
        body = _body(job)
        if jid in NEEDS_BLOB_JOBS or not TREE_ONLY.search(body):
            continue
        checkout = (job.get("steps") or [{}])[0]
        with_ = checkout.get("with") or {}
        if with_.get("fetch-depth") not in (0, None) or with_.get("fetch-depth") is None:
            continue                     # 浅克隆本来就快
        if with_.get("filter") != "blob:none":
            offenders.append(
                f"{fname}::{jid}：只做 `git diff --name-only`（tree 级）却拉全史 blob"
                f"（fetch-depth={with_.get('fetch-depth')}, filter={with_.get('filter')}）"
            )
    assert not offenders, (
        "这些腿的 git 用法只读 tree，历史 blob 是纯下载负担（现取 `.git` 462 MiB / checkout 14–24s）：\n  "
        + "\n  ".join(offenders)
    )


def test_content_reading_jobs_never_use_blobless():
    offenders: list[str] = []
    for (fname, jid), job in _jobs().items():
        if jid not in NEEDS_BLOB_JOBS:
            continue
        checkout = (job.get("steps") or [{}])[0]
        with_ = checkout.get("with") or {}
        if with_.get("filter") == "blob:none":
            offenders.append(
                f"{fname}::{jid}：跑内容级 git 命令（`git log -p` / patch `git diff` / `git grep`）却用 `filter: blob:none`"
                " ⇒ partial clone 会把每次读 blob 变成懒拉取（比全史更慢，且要联网）"
            )
    assert not offenders, "\n  ".join(offenders)


def test_the_needs_blob_list_is_not_stale():
    """反向锁：清单里的腿必须**真的**跑内容级 git 命令，否则清单会腐烂成「永远不用动」的借口。"""
    live = {jid: job for (_f, jid), job in _jobs().items()}
    stale = [jid for jid in NEEDS_BLOB_JOBS
             if jid not in live or not re.search(r"gitleaks\s+detect|git log -p|git grep", _body(live.get(jid) or {}))]
    assert not stale, f"这些腿在清单里但已不再跑内容级 git 命令 ⇒ 从 NEEDS_BLOB_JOBS 删掉：{stale}"


def test_the_known_content_leg_is_still_full_blob():
    """回归锁：`gitleaks-scan` 必须保持**全 blob**（它要逐 commit 的 diff 内容）。"""
    job = _jobs()[("pr-check.yml", "gitleaks-scan")]
    with_ = (job.get("steps") or [{}])[0].get("with") or {}
    assert with_.get("filter") != "blob:none", (
        "gitleaks 把历史 blob 抽掉后，`gitleaks detect --log-opts` 会逐对象懒拉取 ⇒ 比现在更慢且要联网；"
        "要减负应当改扫描面/缓存，而不是抽 blob"
    )
