# case_ids: MC-112
"""**「job 里调用 `gh` 却没有 git 上下文」的类级判据**（issue #7051 —— 同一形态已咬三次）。

## 病（三次，逐字取自现场）

| # | 位置 | 现场 |
|---|---|---|
| 1 | `.github/workflows/automerge.yml::enable-auto-merge`（**#2929**，2026-09-05，已修） | `gh pr merge --auto` 报 `failed to run git: fatal: not a git repository` ⇒ **auto-merge 从未武装**，只能人工合 |
| 2 | `.github/workflows/pr-check.yml::clear-needs-changes`（**#7022**，2026-10-16，已修） | `gh pr view … --json labels --jq …` 同样报该错 ⇒ 在 `shell: /usr/bin/bash -e {0}` 下**整步 exit 1** |
| 3 | `.github/workflows/pr-check.yml::label-needs-changes`（同 #7022） | 同一 job 家族、同一缺法 |

**根因（三次逐字相同）**：这些 job **没有 `actions/checkout`**，而 `gh` 默认靠 git 远端推断仓库；
若也没有 `GH_REPO` 环境变量，`gh` 就无从知道要说哪个仓库。

## 为什么它特别难发现（#7022 的实证，值得单独记）

`clear-needs-changes` 那一步原来写的是：

```bash
HAS_LABEL=$(gh pr view "$PR_NUMBER" --json labels --jq '.labels[].name' 2>/dev/null | grep -c 'review/needs-changes' || echo "0")
```

`|| echo "0"` **恰好把非零退出码吞掉了** ⇒ 步报 **success**、标签**从不脱落**（#7022 的症状），
而 `gh` 那句错误被 `2>/dev/null` 藏了 ⇒ **「绿着但没干活」**。
⇒ **这个缺陷自己不会变红，它只是让某件事静默不生效。** 所以只能靠**静态判据**拦。

## 本判据锁什么（两条，各有能单独变红的注入点）

| # | 判据 | 取法 | 怎么红 |
|---|---|---|---|
| A | 凡 job 的某个 `run:` 里**调用 `gh`**，该 job 必须有 `actions/checkout` step，**或**该 job / 该 step 的 `env` 里有 `GH_REPO` | YAML 解析每个 workflow 的 `jobs`；`run:` 正文**先剥注释**再匹配 `gh` 命令词 | 摘掉 `automerge.yml::enable-auto-merge` 的 `Checkout` **且**摘掉该 step 的 `GH_REPO` ⇒ 红（**二者其一即可**，只摘 `Checkout` 不红 —— 该 step 自带 `GH_REPO`，见下）；摘掉 `pr-check.yml::clear-needs-changes` 的 `GH_REPO` ⇒ 红（两条都已实测） |
| B | **不静默空跑 + 判别力自证**：workflow 语料下限、`gh` 命中面下限、以及「注释里的 `gh` 不算数」 | 同上 + 内存构造的注入夹具 | 语料/命中面塌了 ⇒ 红；把 `# gh pr view …` 也算成调用 ⇒ 红（假阳性自证） |

## 边界（照实登记，§19.1）

- **只证「有 git 上下文」，不证「能访问到目标数据」**：权限面不在射程 ——
  例如 `branches/main/protection` 端点在 CI 里**即便有 `GH_REPO`** 也可能因**内置 token 非 admin** 而失败
  （#7022 的 `needs:` 判据就是因为这个改成了**冻结快照**）。本判据**不为**任何 `gh` 子命令的权限背书。
- **只认「`gh` 作为命令词」**：`run:` 里 `gh` 出现在**字符串/注释/变量名**中不算调用
  （剥注释 + 命令词边界匹配；实证：这三次的现场都是行首/管道后的真调用）。
- **`GH_REPO` 只认字面键**：`env` 里以**变量拼接**方式给出 `GH_REPO` 的写法（本仓现取 0 处）**看不见** ——
  如实登记，不写成恒真判据。
- **不判「该 job 该不该用 `gh`**」：那是设计问题，不是本判据的事。
- ⚠️ **写本判据时我自己踩过一次**：红证① 第一版**只摘了 `Checkout`**，判据**不红**，我一度以为判据漏检 ——
  实查是该 step **自带 `GH_REPO`**（#2929 留的双保险：job 级 `env` 里没有、在 **step 级**）⇒ 判据口径本就是
  「**二者其一即可**」。**判据是对的，错的是注入。** ⇒ 记在这里，免得下一个人重踩：
  **变异注入必须先自证「注入真的生效、且注入的是我以为的那个对象」**（铁律 8「核验前自证坐标」）。
- 本判据**不改任何门禁的通过条件、不新增豁免**。

## 判据 = 本文件；用例 = `MC-112`
"""

from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

# ⚠️ 剥注释**复用全仓唯一实现**（`.github/danger_scan.py::strip_comment`），**不自己再写一把尺子**：
#   · 它按 YAML / shell 的真实规则处理引号内的 `#`（`run: echo "a # b"` 里的 `#` 不是注释起点）——
#     朴素实现（`.split("#")[0]` / `re.sub(r"#[^\n]*", "", line)`）会把字符串里的 `#` 一起吃掉 ⇒ **假绿**；
#   · 仓里有**三条**判据盯着这件事：`test_guard_parsing_is_comment_aware.py`（未登记的朴素 `#` 截断 ⇒ 红）、
#     `test_automerge_bot_safe_path.py::test_only_one_strip_comment_implementation_in_the_repo`（整仓同符号只有一处）、
#     以及其前缀族对照臂 —— 它们**当场**把我第一版那个自造的「复数版剥注释函数」判红了
#     （⚠️ 此处**刻意不写出它的定义字面量**：`test_automerge_bot_safe_path.py::test_the_predicate_itself_is_discriminating`
#      要按**原文**扫「前缀 + 空格 + 该符号名」来具名证明前缀谓词的射程 ⇒ 写进散文就会进它的读数）。
#   ⇒ 这就是「**先理解再爬梯**」：仓里已有这把尺子，造第二把只会让两条判定漂移。
sys.path.insert(0, str(REPO_ROOT / ".github"))
from danger_scan import strip_comment  # noqa: E402

#: `gh` **作为命令词**（行首 / 管道后 / `;` / `&&` / `||` / `$(` 之后）—— `gherkin` / `github` 之类不算。
GH_CALL = re.compile(r"(?:^|[|;&(]\s*|\$\(\s*)gh\s")
#: 语料下限（现取 41 个 workflow）——判定面塌了要出声，不许静默变绿。
WORKFLOW_FLOOR = 20
#: `gh` 命中面下限（现取 17 个 job）——`gh` 检测失效时要出声。
GH_JOB_FLOOR = 10

__all__ = ["mask_comments", "gh_context_problems", "scan_workflows", "workflow_problems"]


def mask_comments(text: str) -> str:
    """把注释**逐行涂白**（同长度空格，保持行结构），只留代码。

    复用 `strip_comment`（全仓唯一实现）——**先想清语义，再决定怎么用**：
      · 整行注释 ⇒ 涂成等长空白；
      · 行内注释 ⇒ 只涂白注释那一段（`strip_comment` 已按 YAML/shell 规则跳过引号内的 `#`，
        故 `echo "a # b"` 这类**不会被误当注释**）。

    为什么必须涂白而不是删行/截断：`run:` 正文常常是块标量，**行号与结构**是人复算的坐标；
    而且这三次现场（#2929 / #7022 ×2）的 `gh` 都是**真调用**，涂白注释既不会漏检、也不会误报。

    ⚠️ 本函数**不自己写**任何 `#` 截断模式（不出现 `.split("#")` / `re.sub` 之类形态）——
    那正是 `test_guard_parsing_is_comment_aware.py` 的 RULE_HASH 要拦的「第二把尺子」；
    这里只**调用**共享实现，命中面天然为 0。
    """
    out: list[str] = []
    for line in text.split("\n"):
        code = strip_comment(line)
        if not code.strip():
            out.append(" " * len(line))          # 整行（或纯空白 + 注释）⇒ 全涂白
        elif code == line:
            out.append(line)                     # 无注释
        else:
            out.append(code + " " * (len(line) - len(code)))  # 行内注释 ⇒ 只涂白尾部
    return "\n".join(out)


def _job_env(job: dict, step: dict) -> dict:
    return {**(job.get("env") or {}), **(step.get("env") or {})}


def _has_checkout(job: dict) -> bool:
    return any(
        "checkout" in str(s.get("uses") or "").lower()
        for s in (job.get("steps") or [])
        if isinstance(s, dict)
    )


def gh_context_problems(path: str, doc: dict) -> list[str]:
    """判据 A 的纯函数：→ 问题清单（空 = 该 workflow 干净）。"""
    problems: list[str] = []
    for jid, job in (doc.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        steps = [s for s in (job.get("steps") or []) if isinstance(s, dict)]
        has_checkout = _has_checkout(job)
        for step in steps:
            body = mask_comments(str(step.get("run") or ""))
            if not GH_CALL.search(body):
                continue
            if has_checkout or any(k == "GH_REPO" for k in _job_env(job, step)):
                continue
            problems.append(
                f"{path}::{jid}（step `{step.get('name') or '(未命名)'}`）里调用了 `gh`，"
                "但该 job 既没有 `actions/checkout` 也没有 `GH_REPO`，"
                "  ⇒ `gh` 无从知道仓库（`failed to run git: fatal: not a git repository`）"
            )
    return problems


def scan_workflows(directory: pathlib.Path = WORKFLOW_DIR) -> list[tuple[str, dict]]:
    """扫全部 workflow。读不到 / 零文件 / 解析不了 ⇒ **抛**（fail-closed，不许静默变绿）。"""
    if not directory.is_dir():
        raise ValueError(f"workflow 目录不存在：{directory}（fail-closed，不许当成「零违规」）")
    files = sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")])
    if len(files) < WORKFLOW_FLOOR:
        raise ValueError(f"workflow 文件只有 {len(files)} 个（< {WORKFLOW_FLOOR}）⇒ 判定面塌了")
    out: list[tuple[str, dict]] = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError as e:  # pragma: no cover - 环境异常
            raise ValueError(f"{f} 解析失败：{e}") from e
        if not isinstance(doc, dict) or "jobs" not in doc:
            raise ValueError(f"{f} 没有 jobs（fail-closed，不许当成「无需覆盖」）")
        out.append((str(f.relative_to(REPO_ROOT)), doc))
    return out


def workflow_problems(corpus: list[tuple[str, dict]]) -> list[str]:
    problems: list[str] = []
    for path, doc in corpus:
        problems.extend(gh_context_problems(path, doc))
    return problems


# ────────────────────────────── 判据 A ──────────────────────────────

def test_every_gh_calling_job_has_git_context():
    """判据 A：全仓凡 `run:` 里调用 `gh` 的 job，必须有 `checkout` 或 `GH_REPO`。"""
    corpus = scan_workflows()
    problems = workflow_problems(corpus)
    assert problems == [], (
        "「job 里调用 gh 却没有 git 上下文」——`gh` 会因 `not a git repository` 失败，"
        "而若那一步还带 `|| true` / `2>/dev/null` 就会**绿着但没干活**（issue #2929 / #7022 的同族）：\n"
        + "\n".join(f"  {p}" for p in problems)
        + "\n\n修法：给该 job 加 `actions/checkout`，或在 step 的 `env` 里加 "
          "`GH_REPO: ${{ github.repository }}`。"
    )


# ─────────────────── 反空跑 + 判别力自证（判据 B）───────────────────

def test_guard_is_not_vacuous():
    """判据 B：语料下限 + `gh` 命中面下限 + fail-closed（读不到 ⇒ 抛，不许静默变绿）。"""
    corpus = scan_workflows()
    assert len(corpus) >= WORKFLOW_FLOOR, f"workflow 语料过少（{len(corpus)}）"
    gh_jobs = sum(
        1
        for _path, doc in corpus
        for _jid, job in (doc.get("jobs") or {}).items()
        if isinstance(job, dict)
        and any(
            GH_CALL.search(mask_comments(str(s.get("run") or "")))
            for s in (job.get("steps") or [])
            if isinstance(s, dict)
        )
    )
    assert gh_jobs >= GH_JOB_FLOOR, (
        f"全仓只扫到 {gh_jobs} 个「调用 gh」的 job（< {GH_JOB_FLOOR}）⇒ `gh` 检测疑似失效，判据在空跑"
    )
    # fail-closed 自证：不存在的目录必须抛，而不是返回空清单
    import pytest  # 局部导入：本文件只有这一处需要
    with pytest.raises(ValueError, match="fail-closed"):
        scan_workflows(REPO_ROOT / "no-such-workflow-dir-xyz")


def test_criterion_has_discriminating_power():
    """判据 B：注入式自证 —— 缺上下文 ⇒ 报出；有上下文 / 注释里的 `gh` ⇒ 不报。"""
    def doc(*, uses: str | None, envs: dict, body: str) -> dict:
        step: dict = {"name": "s", "run": body}
        if envs:
            step["env"] = envs
        steps: list[dict] = []
        if uses:
            steps.append({"uses": uses})
        steps.append(step)
        return {"jobs": {"j": {"steps": steps}}}

    # ❌ 缺上下文 ⇒ 必须报
    bad = gh_context_problems("wf.yml", doc(uses=None, envs={}, body='gh pr view 1 --json labels'))
    assert bad and "wf.yml::j" in bad[0], "缺 checkout/GH_REPO 时没报出来 ⇒ 判据没有牙"

    # ✅ 两个方向各自的合法形态
    assert gh_context_problems("wf.yml", doc(uses="actions/checkout@v7", envs={}, body="gh pr view 1")) == []
    assert gh_context_problems("wf.yml", doc(uses=None, envs={"GH_REPO": "${{ github.repository }}"}, body="gh pr view 1")) == []

    # ✅ 注释里的 `gh` 不算调用（假阳性自证 —— 本会话反复踩到这个坑）
    assert gh_context_problems("wf.yml", doc(uses=None, envs={}, body="# gh pr view 1 只是说明")) == []

    # ✅ 词边界：`github` / `gherkin` 不是 `gh`
    assert gh_context_problems("wf.yml", doc(uses=None, envs={}, body="echo github; echo gherkin")) == []

    # ✅ 管道 / 命令替换后的 `gh` 也算调用（三次现场都是这种形态）
    for form in ("X=$(gh pr view 1)", "true | gh pr view 1", "a && gh pr view 1"):
        assert gh_context_problems("wf.yml", doc(uses=None, envs={}, body=form)), f"漏检：{form}"
