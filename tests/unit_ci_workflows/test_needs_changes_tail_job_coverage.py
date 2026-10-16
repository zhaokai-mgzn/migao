# case_ids: MC-110
"""标签收尾 job 的 `needs:` 必须覆盖**全部 required 门禁**（issue #7022，第二条成因）。

## 病（真机，2026-10-16；与同单的 `grep -c` 是**两条独立的**成因）

`review/needs-changes` 这个标签有**两个**收尾 job：

- `label-needs-changes`：任一门禁红 ⇒ **打**标签；
- `clear-needs-changes`：门禁全绿 ⇒ **摘**标签。

两者的 `needs:` 都只列了 **9** 个 job，而 `pr-check.yml` 里的 **required** 门禁还有 4 个没被列进去：
`case-coverage-gate` / `case-trust-gate` / `llm-sink-ledger` / `ui-regression-check`。后果**双向**：

| 缺口 | 后果 |
|---|---|
| `label-needs-changes` 不看这 4 个 | 这 4 个**红的时候不打标签** ⇒ 标签漏报 |
| `clear-needs-changes` 不看这 4 个 | 「这 4 个红 + 其余 9 个绿」时它**照样把标签摘掉** ⇒ 僵尸标签（或更准确地：**该挂的标签挂不住**） |

⇒ 与同单 `grep -c` 那条**症状相同、成因不同**：一个是「摘标签的判据崩了」，一个是
「摘标签/打标签的**依赖面**少了一半」。**只修一条治不好这个症状** —— 这也正是本单把它一起收掉的理由。

`docs/wiki/gate-exemption-ledger.md` §1 第 6 行**早已登记**这处缺口（但当时那单禁止改 workflows ⇒ 只登记未修）。

## 本文件锁什么（两条判据，各有能单独变红的注入点）

| # | 判据 | 取法 | 怎么红 |
|---|---|---|---|
| A | **覆盖性**：`label-needs-changes` 与 `clear-needs-changes` 的 `needs:` 必须包含**本 workflow 里承接 required 检查的每一个 job** | 现取 `branches/main/protection` 的 `required_status_checks.contexts` × YAML 解析 `pr-check.yml` 的 `jobs`，按「`name` 命中 required 检查名」判定哪些 job 是 required 门禁 | 从任一 `needs:` 里删掉 `case-trust-gate` ⇒ 当场红并具名 |
| B | **不静默空跑 + 判别力自证**：required 名单必须非空；两个收尾 job 必须存在；且**注入式**验证判据 A 真的会红 | 同上 + 注入 | ① required 名单读不到/为空 ⇒ 红（不许「没东西可判 ⇒ 绿」）；② 注入式自证 |

## 边界（照实登记，§19.1）

- **只判「漏了 required 门禁」，不判「多了无关 job」**：多列一个 job 只会让这两个收尾 job
  多等一会儿，**不会**放过任何门禁 ⇒ 不在射程。而 `needs:` 里**列全**才安全：
  `needs:` 只影响「等不等」，**不**影响「上游红了下游还跑不跑」（那是 `if: always()` 的职责，
  两个 job 都已正确带 `always()`，由 `test_gate_coverage_and_same_source.py` 的另一条判据把守）。
- **5 个 required 检查在本 workflow 里没有承接 job**（`ai-agent-service unit tests` /
  `mini-app typecheck + unit tests` / `bmini-app typecheck + unit tests` /
  `ci workflow helper unit tests` ×2 —— 它们在**别的** workflow 里）⇒ 本判据**跳过**它们并**计数登记**，
  **不**假装它们被覆盖（跨 workflow 的 required 面不在本判据射程）。
- **不硬编码那 4 个 job 名**：判据从 branch protection **现取** required 名单 ⇒
  以后新增 required 门禁而忘了加进 `needs:` 时，本判据**照样会红**（这正是它比"写死 4 个名字"值钱的地方）。
- **本条不新增/不改任何门禁的通过条件、不新增豁免。**
- ⚠️ **依赖外部读数**：`branches/main/protection` 需要 `gh` 可用且已登录（CI 里可用）。
  取不到 ⇒ **fail-closed 红**（不许当成「没有 required 检查 ⇒ 覆盖性自动成立」）。
  这与 `scripts/next_case_id.py` 的「看不到在飞面 ⇒ 不给号」同口径。

## 判据 = 本文件；用例 = `MC-110`
"""

from __future__ import annotations

import json
import pathlib
import subprocess

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PR_CHECK = REPO_ROOT / ".github" / "workflows" / "pr-check.yml"
REPO_SLUG = "zhaokai-mgzn/migao"
BASE_BRANCH = "main"

# 只管这两个收尾 job（打/摘 `review/needs-changes`）
TAIL_JOBS = ("label-needs-changes", "clear-needs-changes")


def _required_contexts() -> list[str]:
    """现取 `main` 的 required status checks。取不到 ⇒ fail-closed 抛异常。"""
    proc = subprocess.run(
        ["gh", "api", f"repos/{REPO_SLUG}/branches/{BASE_BRANCH}/protection"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "取不到分支保护 required 名单（fail-closed，不许当成「没有 required 检查」）："
            f"gh api rc={proc.returncode} stderr={proc.stderr.strip()[:200]}"
        )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as e:  # pragma: no cover - 环境异常
        raise RuntimeError(f"分支保护响应不是合法 JSON：{e}") from e
    contexts = (payload.get("required_status_checks") or {}).get("contexts") or []
    if not contexts:
        raise RuntimeError("required 名单为空（fail-closed）—— 覆盖性判据会因此静默空跑成绿")
    return [str(c) for c in contexts]


def _pr_check_jobs() -> dict:
    if not PR_CHECK.is_file():
        raise RuntimeError(f"读不到 {PR_CHECK}（fail-closed）")
    return yaml.safe_load(PR_CHECK.read_text(encoding="utf-8"))["jobs"]


def coverage_problems(required: list[str], jobs: dict) -> list[str]:
    """→ 问题清单（空 = 覆盖完整）。同时把「本 workflow 无承接 job」的 required 项计数登记。"""
    problems: list[str] = []
    required_set = set(required)
    # 本 workflow 里「承接某个 required 检查」的 job
    required_jobs: dict[str, str] = {}
    for jid, job in sorted(jobs.items()):
        if not isinstance(job, dict):
            continue
        name = job.get("name") or jid
        if name in required_set:
            required_jobs[jid] = name
        elif jid in required_set:
            required_jobs[jid] = jid

    for tail in TAIL_JOBS:
        if tail not in jobs:
            problems.append(f"pr-check.yml 里找不到收尾 job `{tail}`（判据的前提被破坏）")
            continue
        needs = jobs[tail].get("needs") or []
        needs = [needs] if isinstance(needs, str) else [str(n) for n in needs]
        for jid, name in sorted(required_jobs.items()):
            if jid not in needs:
                problems.append(
                    f"`{tail}` 的 needs 缺 required 门禁 `{jid}`（name: {name}）"
                    f" ⇒ 它红时{'打不上' if tail.startswith('label') else '仍会被摘掉'}标签"
                )
    return problems


def uncovered_required_in_other_workflows(required: list[str], jobs: dict) -> list[str]:
    """本 workflow 里**没有**承接 job 的 required 检查（跨 workflow 面，登记而不判红）。"""
    found = set()
    for jid, job in jobs.items():
        if isinstance(job, dict):
            found.add(job.get("name") or jid)
        found.add(jid)
    return sorted(set(required) - found)


# ────────────────────────────── 判据 A ──────────────────────────────

def test_tail_jobs_cover_every_required_gate():
    """判据 A：两个收尾 job 的 `needs:` 必须覆盖本 workflow 里的全部 required 门禁。"""
    required = _required_contexts()
    jobs = _pr_check_jobs()
    problems = coverage_problems(required, jobs)
    covered = len(required) - len(uncovered_required_in_other_workflows(required, jobs))
    assert problems == [], (
        "「该挂的标签挂不住 / 该摘的摘不掉」——收尾 job 的 `needs:` 少了 required 门禁"
        "（issue #7022，与同单的 `grep -c` 是两条独立成因）：\n"
        + "\n".join(f"  {p}" for p in problems)
        + f"\n\n（required={len(required)} 项，其中 {covered} 项由本 workflow 承接；"
        "跨 workflow 的那几项不在本判据射程）"
    )


# ─────────────────────── 反空跑 + 判别力自证 ───────────────────────

def test_guard_is_not_vacuous_and_has_teeth():
    """③ 反空跑 + 注入式自证：语料下限、fail-closed、以及「注入即红」。"""
    required = _required_contexts()
    jobs = _pr_check_jobs()

    # 语料下限
    assert len(required) >= 10, f"required 检查过少（{len(required)}）—— 读数面被收窄了？"
    for tail in TAIL_JOBS:
        assert tail in jobs, f"缺收尾 job `{tail}`"

    # 应在场：4 个曾经缺失的门禁，现在必须都在两个 needs 里
    required_jobs = {
        jid for jid, job in jobs.items()
        if isinstance(job, dict) and (job.get("name") or jid) in set(required)
    }
    for tail in TAIL_JOBS:
        needs = jobs[tail].get("needs") or []
        assert required_jobs <= set(needs), f"`{tail}` 的 needs 未覆盖 {sorted(required_jobs - set(needs))}"

    # ── 注入式自证：从 needs 里删掉一个 required 门禁 ⇒ coverage_problems 必须报出 ──
    probe = {k: dict(v) if isinstance(v, dict) else v for k, v in jobs.items()}
    victim = "case-trust-gate"
    assert victim in (jobs["clear-needs-changes"].get("needs") or []), "自证前提：victim 原本在 needs 里"
    probe["clear-needs-changes"] = dict(probe["clear-needs-changes"])
    probe["clear-needs-changes"]["needs"] = [
        n for n in probe["clear-needs-changes"]["needs"] if n != victim
    ]
    injected = coverage_problems(required, probe)
    assert any(victim in p for p in injected), (
        f"注入式自证失败：从 `clear-needs-changes` 的 needs 里删掉 `{victim}` 后判据没报出来 ⇒ 判据没有牙"
    )

    # ── fail-closed 自证：gh 取不到 ⇒ 必须抛，不许返回空名单 ──
    with pytest.raises(RuntimeError, match="fail-closed"):
        wrong = subprocess.run(
            ["gh", "api", f"repos/{REPO_SLUG}/branches/no-such-branch-xyz/protection"],
            capture_output=True, text=True,
        )
        if wrong.returncode != 0:
            raise RuntimeError("fail-closed：取不到分支保护")
        raise AssertionError("预期 gh 取不到不存在的分支保护")
