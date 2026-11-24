# case_ids: MC-358
"""`check-ui-regression.sh` 的 `git fetch origin main` 必须**按仓库形态**加 `--depth=1`（issue #9120）。

## 病（2026-11-24 实测，CI 读数）

把该腿的 `fetch-depth: 0` 去掉之后（#9146），checkout 从 **16–20s → 6s**（符合预期），
但脚本里那句**不带 depth 的** `git fetch origin main` 在浅仓库里会把 main 的**全史**拉下来：

| 步骤 | 去掉 fetch-depth 后 |
|---|---|
| `actions/checkout@v7` | **6s** ✅（原 16–20s） |
| `Check UI token regression vs origin/main` | **26s** ❌（原 1s，其中就是那次全史 fetch） |
| 整腿 | **36s**（原 21–30s ⇒ **反而更慢**） |

⇒ 只去掉 `fetch-depth: 0` 不够：**取 tip 的那次 fetch 也必须 depth=1**，否则减负变成增负。

## 判据

1. 脚本里对 `origin/main` 的 fetch 必须**按 `git rev-parse --is-shallow-repository` 分支**：
   浅仓库走 `git fetch --depth=1 origin main`，全史仓库走普通 fetch；
2. `pr-check.yml` 的 `UI Regression Check` 步骤里**不得**再出现裸的 `git fetch origin main --quiet`
   （那是第二次全史拉取；脚本自己会取）。

红证：把脚本改回裸 fetch、或把 job 里的裸 fetch 加回去 ⇒ 对应判据具名红。
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "check-ui-regression.sh"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr-check.yml"
JOB_NAME = "UI Regression Check"


def test_script_fetches_the_tip_with_depth_when_shallow():
    body = SCRIPT.read_text(encoding="utf-8")
    assert "--is-shallow-repository" in body, (
        "脚本没有判断仓库形态 ⇒ 浅仓库会拉 main 全史（实测 26s，判据本体只要 1s）"
    )
    assert re.search(r"git fetch --depth=1 origin main", body), (
        "浅仓库分支里没有 `git fetch --depth=1 origin main` ⇒ tip 取法不对，减负会变成增负"
    )
    # 必须**分支**，不能无条件 depth：对全史仓库强行 depth 会把本地仓变浅
    shallow_branch = re.search(
        r'if \[ "\$\(git rev-parse --is-shallow-repository.*?\)" = "true" \]; then(.*?)else(.*?)fi',
        body, re.S,
    )
    assert shallow_branch, "拿不到「浅 / 非浅」分支代码（判据靠它保证不把全史仓库变浅）"
    assert "--depth=1" in shallow_branch.group(1), "浅分支里没有 --depth=1"
    assert "--depth=1" not in shallow_branch.group(2), "非浅分支不该带 --depth=1（会把本地全史仓库变浅）"


def test_job_does_not_do_a_second_full_fetch():
    text = WORKFLOW.read_text(encoding="utf-8")
    m = re.search(rf"^    name: {re.escape(JOB_NAME)}$", text, re.M)
    assert m, f"找不到 job `{JOB_NAME}`"
    rest = text[m.start():]
    nxt = re.search(r"^    name: ", rest[1:], re.M)
    block = rest[: nxt.start() + 1] if nxt else rest
    effective = "\n".join(ln for ln in block.splitlines() if not ln.lstrip().startswith("#"))
    assert not re.search(r"^\s*git fetch origin main\s", effective, re.M), (
        "job 里又出现裸的 `git fetch origin main` 了 —— 那是**第二次**全史拉取"
        "（脚本自己会按仓库形态取），实测让这条腿从 21s 抬到 36s（issue #9120）。"
    )
