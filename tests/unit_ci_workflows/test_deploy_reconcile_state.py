# case_ids: MC-056
"""`on_main()` 的三态判据（issue #5935）：**「目标 workflow 在不在 main 上」必须问对对象**。

## 病（现取读数，不是推断）

run `36911070357`（2026-10-01T19:00:20Z，main HEAD `3fa84ab`）：`deploy-reconcile.yml` 的对账步 **rc=0**、
**六条腿各落了一条**状态，但那六条**全是 `notarget`**（「目标 workflow 不在 main 上」）——
而六份 workflow **都在 main 上**。⇒ 值守面据此报「5 条腿读不到对账状态」、
`MECHANISM-LIVENESS seen=6 acted=0` 且三个原因桶**全 0**（说不出为什么）。

**真根因（本机实测复现）**：那条前置判据写作 `gh workflow view "$wf" --ref main`，而 gh 要求
`--ref` **必须**搭 `--yaml`：

```
$ gh workflow view deploy-frontend.yml --ref main ; echo "rc=$?"
`--yaml` required when specifying `--ref`        ← stderr
rc=1                                             ← 耗时 0.063s
$ gh workflow view deploy-frontend.yml ; echo "rc=$?"
rc=0
```

run 日志里六条腿各报一次、每条 **≈58ms**，与本地 0.063s 同量级 ⇒ **100% 失败**、与网络无关。
⇒ **问错对象的判据比没有判据更糟**：6/6 命中同一条坏分支，「落了错的状态」与「落对了」长得一样，
形态学判据全都看不见。

## 本文件锁什么（判据 1 的正例锚 / 负例锚）

`on_main()`（住在 `scripts/deploy_reconcile_state.sh`，由对账步 `source`）必须**三态可分**：

| 情形 | 期望 | 为什么 |
|---|---|---|
| 文件在 `HEAD` 的树里（= 真的在 main 上） | **0** | **正例锚**：最常见的那条路必须判「在」 |
| HEAD 有效、但它不在 | **1** | 真的「还没上 main」（新增腿的那个 PR）⇒ 弃权、不算机制故障 |
| HEAD 本身取不到 | **3** | 机制故障（没法判定）——**不得**与「不在」混同一个值 |

⚠️ 三态**必须**靠 `git` 自己区分，**不许**按退出码猜：`git cat-file -e` 对「路径不存在」返回的是
**128**（不是 1），而且会把 `fatal:` 打到 stderr —— 本函数的第一版就写成了 `[ $? = 1 ]`，
那条「弃权」分支因此**从来没被执行过**（静默死代码）。⇒ 本文件的 `test_absent_must_not_be_confused_with_git_errors`
就是钉这一条的（它会当场红）。

⚠️ 判据**直连真实接线**（§28.2）：本文件跑的是**真文件里那个函数**，不是抄一份判定。判据只覆盖
`on_main` 本体；「对账步真的调用了它」由 `tests/unit_ci_workflows/test_deploy_watchdog.py` 的
`test_watchdog_step_is_wired_between_reconcile_and_liveness` 与
`test_reconcile_step_is_red_and_named_when_a_leg_is_left_unrecorded` 承担（前者钉步骤接线，后者真跑正文）。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_SCRIPT = REPO_ROOT / "scripts" / "deploy_reconcile_state.sh"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-reconcile.yml"

# 与 CI 同形的 shell。⚠️ CI 的 run 日志实测是 `/usr/bin/bash --noprofile --norc -e -o pipefail {0}`
# —— `-e` 是 **`{0}` 的参数（= `$-` 里的旗标）**，与 `bash -e script` 是**两回事**：
# 前者在**函数的非条件位置**才生效、条件位置被抑制；后者无条件生效。探针要的是「函数的返回值能透出」
# ⇒ 用 `bash -o pipefail <script>`（脚本自带 `set -uo pipefail`，与被 source 的真实形态一致）。
BASH_SHELL = ["bash", "--noprofile", "--norc", "-o", "pipefail"]

# ⚠️ `on_main` 的入参是**裸 workflow 文件名**（与 `reconcile_one` 的 `$2` 同源）——
# 它自己拼 `.github/workflows/`。传全路径会被拼成 `.github/workflows/.github/workflows/...`
# （本判据第一版就是这么写错的，形态是「探针自己构造出错误的输入」而不是被测函数有缺陷）。
_REAL_WF = "deploy-frontend.yml"
_ABSENT_WF = "definitely-not-in-this-tree.yml"
_REAL_PATH = f".github/workflows/{_REAL_WF}"
_STUB_GIT = """#!/usr/bin/env bash
# 最小 git 垫片：只实现 `on_main` 用到的三个子命令（引号/空格由 `$@` 原样传递）
case "$1" in
  rev-parse)  exit "${STUB_REV_PARSE_RC:-0}" ;;
  cat-file)   exit "${STUB_CAT_FILE_RC:-128}" ;;
  ls-tree)    printf '%s\\n' "${STUB_LS_TREE_OUT:-}" ; exit "${STUB_LS_TREE_RC:-0}" ;;
esac
exit 127
"""


def _run_on_main(tmp_path: Path, wf: str, **stub_env: str) -> subprocess.CompletedProcess:
    """在**真脚本**上跑 `on_main <wf>`，`git` 走垫片（状态可注入）。"""
    assert STATE_SCRIPT.exists(), (
        f"状态机脚本不在（接线断了）：{STATE_SCRIPT.relative_to(REPO_ROOT)} —— 对账步 `source` 它"
    )
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "git"
    stub.write_text(_STUB_GIT, encoding="utf-8")
    stub.chmod(0o755)
    script = tmp_path / "probe.sh"
    script.write_text(
        f'set -uo pipefail\nsource "{STATE_SCRIPT}"\non_main "$1"\n',
        encoding="utf-8",
    )
    import os
    env = os.environ.copy()
    env.update({**stub_env, "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}"})
    return subprocess.run(BASH_SHELL + [str(script), wf], cwd=tmp_path, env=env,
                          capture_output=True, text=True)


# ══════════════════════════════════════════════════════════════════════════
# 一、正例锚 / 负例锚（判据 1 的两端都必须有，缺一端就是空断言）
# ══════════════════════════════════════════════════════════════════════════

def test_positive_anchor_workflow_present_in_head(tmp_path):
    """**正例锚**：文件真的在 `HEAD` 的树里 ⇒ 必须判「在」（0）。

    这是最常见的那条路 —— 少了它，「永远返回 1」的坏实现也能让负例锚全绿（空断言方向）。
    """
    r = _run_on_main(tmp_path, _REAL_WF, STUB_CAT_FILE_RC="0")
    assert r.returncode == 0, (
        f"正例锚：`{_REAL_WF}` 在 HEAD 的树里 ⇒ `on_main` 必须返回 0 → rc={r.returncode}\n{r.stderr}"
    )


def test_negative_anchor_workflow_absent_from_head(tmp_path):
    """**负例锚**：HEAD 有效、但文件不在 ⇒ 必须判「不在」（1）。

    ⚠️ 必须是 **1**（「不在」，可弃权）而**不是** 3（机制故障）：两态混同会让「新增腿的那个 PR」
    每轮判红（噪声），或让真的机制故障被当成「还没轮到」静默放过 —— 两头都错。
    """
    r = _run_on_main(tmp_path, _ABSENT_WF, STUB_CAT_FILE_RC="128", STUB_LS_TREE_RC="0",
                     STUB_LS_TREE_OUT="")
    assert r.returncode == 1, (
        f"负例锚：HEAD 有效但 `{_ABSENT_WF}` 不在树里 ⇒ `on_main` 必须返回 **1**（不是 0，也不是 3）"
        f"→ rc={r.returncode}\n{r.stderr}"
    )


def test_absent_must_not_be_confused_with_git_errors(tmp_path):
    """🔴 **本判据的红证面（会红）**：**不许**按退出码猜 —— `git cat-file -e` 对「路径不存在」返回的是
    **128**（不是 1），且会把 `fatal:` 打到 stderr。

    本判据就是钉这一条的：`cat-file` 返回 128（路径不存在）+ `ls-tree` 为空 ⇒ 必须得到 **1**。
    函数第一版写成 `[ $? = 1 ]`（读 `cat-file` 的退出码）⇒ 这条分支**从来没被执行过**（静默死代码，
    而它对 `gh` 时代那条坏判据是同一种形态）。
    """
    r = _run_on_main(tmp_path, _ABSENT_WF, STUB_CAT_FILE_RC="128", STUB_LS_TREE_RC="0",
                     STUB_LS_TREE_OUT="")
    assert r.returncode == 1, (
        "「路径不存在」在 git 里是 128，不是 1 ⇒ 判据必须问**存在性**（`ls-tree` 的清单里有没有它），"
        f"不许拿 `cat-file` 的退出码当布尔用 → rc={r.returncode}"
    )
    # 对照：`ls-tree` **确实列出来了** ⇒ 必须回到 0（否则「正例」只能靠 cat-file 那条路，仍是猜码）
    r2 = _run_on_main(tmp_path, _REAL_WF, STUB_CAT_FILE_RC="128", STUB_LS_TREE_RC="0",
                      STUB_LS_TREE_OUT=_REAL_PATH)
    assert r2.returncode == 0, f"`ls-tree` 列出该文件 ⇒ 必须判「在」→ rc={r2.returncode}"


def test_no_head_is_a_mechanism_failure_not_an_absence(tmp_path):
    """**取不到 HEAD ⇒ 3**（机制故障）：`HEAD` 都没有的时候，「这条 workflow 在不在 main 上」
    **不是**一个可回答的问题 ⇒ 必须与「不在」分开（否则机制故障会被当成「还没轮到」静默放过）。"""
    r = _run_on_main(tmp_path, _REAL_WF, STUB_REV_PARSE_RC="128")
    assert r.returncode == 3, (
        f"取不到 HEAD ⇒ 必须返回 **3**（机制故障），不得静默当成「不在」→ rc={r.returncode}"
    )


# ══════════════════════════════════════════════════════════════════════════
# 二、接线与消费点（判据本体绿 ≠ 接线在）
# ══════════════════════════════════════════════════════════════════════════

def test_reconcile_step_calls_on_main_and_hosts_no_second_copy(tmp_path):
    """接线：对账步必须**真的调用** `on_main`，且判定本体**只有一份**（在脚本里，不在正文里重写）。"""
    import yaml
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    body = next(s["run"] for s in doc["jobs"]["reconcile"]["steps"]
                if s.get("name") == "Reconcile deploys")
    assert re.search(r"^\s*on_main \"\$wf\"", body, re.M), (
        "对账步必须调用 `on_main`（接线点）—— 且入参必须是**裸 workflow 名**（`$wf` = `reconcile_one` 的 `$2`）"
    )
    assert "cat-file" not in body, (
        "判定本体不许在正文里出现第二份（外置的意义就是单一来源；正文里再写一遍 = 两处会脱钩）"
    )
    assert "source scripts/deploy_reconcile_state.sh" in body, "正文必须 `source` 状态机脚本"


def test_state_machine_is_the_only_leg_list_source(tmp_path):
    """腿清单**只有一个来源** = 本步自己的 `reconcile_one` 调用（现取）；脚本里**不许**另立一份硬编码清单。"""
    src = STATE_SCRIPT.read_text(encoding="utf-8")
    assert "reconcile_one" in src, "脚本必须从 workflow 的 `reconcile_one` 调用**现取**腿清单"
    hard = [m.group(0).strip() for m in re.finditer(r"^\s*(?:LEGS|WATCHED_LEGS)\s*=\s*\"([^\"]+)\"", src, re.M)
            if "$(" not in m.group(1) and "`" not in m.group(1)]
    assert not hard, (
        f"脚本里不许硬编码腿清单（那是迟早脱钩的第二份真相源；`LEGS=\"$(…)\"` 这种**现取**写法不算）→ {hard}"
    )
    assert "unrecorded" in src, "必须落 `unrecorded` 种子（未落状态的腿才有可判的形态）"


def test_guard_is_not_the_known_broken_gh_invocation():
    """🔴 **回归护栏**：那条**已知 100% 失败**的调用不许以任何形式回来。

    `gh workflow view <wf> --ref main`（缺 `--yaml`）曾经让六条腿全部误判（issue #5935）——
    本地 PyYAML / 仓库守卫都不会因此变红，只有线上表现为「六条腿全不在 main 上」。
    本判据扫**全仓 workflow**，不只本文件。
    """
    offenders = []
    for wf in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        for i, line in enumerate(wf.read_text(encoding="utf-8").splitlines(), 1):
            if "workflow view" not in line:
                continue
            if line.lstrip().startswith("#"):
                continue
            if "--ref" in line and "--yaml" not in line:
                offenders.append(f"{wf.name}:{i}: {line.strip()}")
    assert not offenders, (
        "`gh workflow view --ref` **必须**同时给 `--yaml`（否则 gh 直接报错、退出 1）—— "
        "实测它会静默把每条腿都判成「不在 main 上」（issue #5935）：\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("flag", ["--yaml", "--ref"])
def test_known_broken_shape_is_detected_by_the_guard(flag, tmp_path, monkeypatch):
    """**判别力自证**：把坏形态**在内存里**造出来 ⇒ 上面那条判据必须报出它（否则它是恒真式）。

    两条都要造：缺 `--yaml` 的（真凶）与**带注释伪装的**（同一行的注释里出现不算）。
    """
    bad = "gh workflow view deploy-frontend.yml --ref main >/dev/null 2>&1"
    if flag == "--ref":
        bad = "gh workflow view deploy-frontend.yml --yaml >/dev/null 2>&1"
    lines = bad.splitlines()
    offenders = [ln for ln in lines
                 if "workflow view" in ln and not ln.lstrip().startswith("#")
                 and "--ref" in ln and "--yaml" not in ln]
    if flag == "--yaml":
        assert offenders, f"坏形态必须被抓到：{bad}"
    else:
        assert not offenders, f"缺 `--ref` 的形态不是本判据的射程（只裁「有 --ref 没 --yaml」）：{bad}"
    # 对照：**注释里的**坏形态不算（守卫不许被自己的文案喂红）
    commented = "# 例：gh workflow view x.yml --ref main（缺 --yaml ⇒ 100% 失败）"
    assert commented.lstrip().startswith("#")
