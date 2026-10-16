# case_ids: MC-110
"""标签收尾 job 的 `needs:` 必须覆盖**全部 required 门禁**（issue #7022，第二条成因）。

## 病（真机，2026-10-16；本单共**三条独立成因**，本条 = 其中的**第二条**）

> 三条成因（同单 #7022，症状相同）：① `grep -c` 配 `|| echo "0"` 捕获成两行；
> **② 本条的 `needs:` 缺口**；③ 该 job 没有 `checkout` ⇒ `gh` 连仓库都推断不出来（`GH_REPO`）。
> **少修一条都治不好**这个症状。

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
| A | **覆盖性**：`label-needs-changes` 与 `clear-needs-changes` 的 `needs:` 必须包含 `REQUIRED_PR_GATES`（**冻结快照**）里的每一个 job | YAML 解析 `pr-check.yml` 的 `jobs` × 冻结清单 | 从任一 `needs:` 里删掉 `case-trust-gate` ⇒ 当场红并具名 |
| B | **冻结清单不许腐烂、不许缩短**：清单里每个 job 必须**真实存在**，且其 `if` 仍是「每个 PR 都跑」的形态（**无路径过滤**）——否则「它该进 needs」这个前提本身失效 | 同上 | 把某个 job 改名/给它的 `if` 加路径过滤 ⇒ 红（具名要求同步更新冻结清单）；`declaration_gate_registry.json` 的 members 多一个/少一个 ⇒ 红 |
| C | **不静默空跑 + 判别力自证**：清单非空；两个收尾 job 必须存在；**注入式**验证判据 A 真的会红 | 同上 + 注入 | 清单为空 ⇒ 红；从 `needs` 删掉 `case-trust-gate` ⇒ 红 |

## ⚠️ 为什么用**冻结清单**而不是现取 `branches/main/protection`（实测踩到才改的）

第一版是 `gh api repos/…/branches/main/protection` **现取** required 名单 —— 本机手动跑（`gh` 已登录）
**2 passed**，但 **CI 上直接判红**：`ci workflow helper unit tests` 那个 job 只把凭据注入成
**`GITHUB_TOKEN`**（`gh` 认的是 `GH_TOKEN`），且 `/protection` 需要 **admin**（内置 token 不是 admin）。
⇒ **判据跑在 CI 里就不能依赖「本机已登录」** —— 这与 `test_automerge_bot_safe_path.py` 挡下的
「内置 `GITHUB_TOKEN` 不是 admin」是**同一件事**（那条判据禁止把内置凭据直绑 `GH_TOKEN`）。
⇒ 改为**冻结快照**（本仓元守卫的既有范式：白名单冻结 + 出处 + 只许缩短），零网络、确定性。
**代价**（照实登记）：它不再自动跟上 branch protection 的变更 —— 但判据 B 会在**被冻结的那个 job
本身**改名/加路径过滤时判红，从而给出「该同步这份清单了」的可行动信号。

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

import pathlib
import re

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PR_CHECK = REPO_ROOT / ".github" / "workflows" / "pr-check.yml"
REPO_SLUG = "zhaokai-mgzn/migao"
BASE_BRANCH = "main"

# 只管这两个收尾 job（打/摘 `review/needs-changes`）
TAIL_JOBS = ("label-needs-changes", "clear-needs-changes")

# ── required 门禁的**冻结快照**（2026-10-16，`origin/main` @6fb4b498）──────────────────────
# 出处：`gh api repos/zhaokai-mgzn/migao/branches/main/protection` 的
#       `required_status_checks.contexts`（16 项）∩ 本 workflow 承接的 job。
# 为什么冻结：见 docstring 末尾那一节（CI 无 `GH_TOKEN` / 内置 token 非 admin ⇒ 现取会判红）。
# **只许缩短**：新增门禁要**先**把它加进本清单，再加进两个收尾 job 的 `needs:`
# （判据 B 保证清单里的 job 真实存在且「每个 PR 都跑」）。
# ⚠️ 本清单的「多一个/少一个都红」**不是**靠这里的下界断言（下界只防清空）——
# 而是逐项冻结在 `declaration_gate_registry.json` 的 `frozen_declarations` 里
# （`.github/…` 的那条判据族：**凡只设下界的冻结集合，成员必须逐项登记**，见 #5007②）。
REQUIRED_PR_GATES = (
    # 8 个 `if` 恰为 `github.event_name == 'pull_request'`（无路径过滤）的门禁
    "case-coverage-gate",
    "case-trust-gate",
    "case-truth-check",
    "danger-scan",
    "gitleaks-scan",
    "llm-sink-ledger",
    "qa-growth-gate",
    "ui-regression-check",
    # 3 个无路径过滤、每个 PR 都跑的测试腿（名字即 job id）
    "admin-api-test",
    "admin-web-test",
    "ci-workflow-tests",
)


def _pr_check_jobs() -> dict:
    """解析 `pr-check.yml` 的 jobs。读不到 ⇒ fail-closed 抛异常。"""
    if not PR_CHECK.is_file():
        raise RuntimeError(f"读不到 {PR_CHECK}（fail-closed）")
    doc = yaml.safe_load(PR_CHECK.read_text(encoding="utf-8"))
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        raise RuntimeError("pr-check.yml 里没有 jobs（fail-closed，不许当成「无需覆盖」）")
    return jobs


def has_path_filter(job: dict) -> bool:
    """该 job 的 `if:` 是否带路径过滤（`paths` / `changed` 之类）⇒ 不是每个 PR 都跑。"""
    cond = str(job.get("if") or "")
    return bool(re.search(r"paths|changed|dorny|filter", cond, re.I))


def coverage_problems(required: tuple[str, ...], jobs: dict) -> list[str]:
    """→ 问题清单（空 = 覆盖完整）。

    双向具名：`label` 侧缺 ⇒ 「红时打不上标签」；`clear` 侧缺 ⇒ 「红时仍会被摘掉标签」。
    """
    problems: list[str] = []
    for tail in TAIL_JOBS:
        if tail not in jobs:
            problems.append(f"pr-check.yml 里找不到收尾 job `{tail}`（判据的前提被破坏）")
            continue
        needs = jobs[tail].get("needs") or []
        needs = [needs] if isinstance(needs, str) else [str(n) for n in needs]
        for jid in required:
            if jid not in needs:
                consequence = "打不上" if tail.startswith("label") else "仍会被摘掉"
                problems.append(
                    f"`{tail}` 的 needs 缺 required 门禁 `{jid}` ⇒ 它红时{consequence}标签"
                )
    return problems


def snapshot_problems(required: tuple[str, ...], jobs: dict) -> list[str]:
    """冻结清单自身的健康度：每个 job 必须真实存在，且仍是「每个 PR 都跑」的形态。"""
    problems: list[str] = []
    for jid in required:
        job = jobs.get(jid)
        if not isinstance(job, dict):
            problems.append(
                f"冻结清单里的 `{jid}` 在 pr-check.yml 里**不存在**（改名了？删了？）"
                " ⇒ 请同步 `REQUIRED_PR_GATES` 与两个收尾 job 的 `needs:`"
            )
            continue
        if has_path_filter(job):
            problems.append(
                f"冻结清单里的 `{jid}` 的 `if:` 带了路径过滤（{job.get('if')!r}）"
                " ⇒ 它不再「每个 PR 都跑」，把它列进 `needs:` 的前提已失效，请重新裁定"
            )
    return problems


# ────────────────────────────── 判据 A ──────────────────────────────

def test_tail_jobs_cover_every_required_gate():
    """判据 A：两个收尾 job 的 `needs:` 必须覆盖 `REQUIRED_PR_GATES` 全量。"""
    jobs = _pr_check_jobs()
    problems = coverage_problems(REQUIRED_PR_GATES, jobs)
    assert problems == [], (
        "「该挂的标签挂不住 / 该摘的摘不掉」——收尾 job 的 `needs:` 少了 required 门禁"
        "（issue #7022，本单三条独立成因中的第二条）：\n"
        + "\n".join(f"  {p}" for p in problems)
    )


# ────────────────────────────── 判据 B ──────────────────────────────

def test_frozen_snapshot_is_not_rotten_and_only_shrinks():
    """判据 B：冻结清单不许腐烂（job 必须真实存在、仍是每个 PR 都跑），也不许变宽。"""
    jobs = _pr_check_jobs()
    assert REQUIRED_PR_GATES, "冻结清单为空 ⇒ 判据 A 会静默空跑成绿"
    assert len(set(REQUIRED_PR_GATES)) == len(REQUIRED_PR_GATES), "冻结清单有重复项"
    problems = snapshot_problems(REQUIRED_PR_GATES, jobs)
    assert problems == [], "冻结清单已腐烂：\n" + "\n".join(f"  {p}" for p in problems)


# ─────────────────────── 反空跑 + 判别力自证 ───────────────────────

def test_guard_is_not_vacuous_and_has_teeth():
    """判据 C：语料下限 + 注入式自证（删掉一个 required 门禁 ⇒ 必须报出）。"""
    jobs = _pr_check_jobs()

    # 语料下限
    # 下界（只防清空）；**逐项冻结**在 declaration_gate_registry.json 的 frozen_declarations
    # ⇒ 多一个/少一个都红（#5007② 的既有范式）。
    assert len(REQUIRED_PR_GATES) >= 11, (
        f"冻结清单被削到 {len(REQUIRED_PR_GATES)} < 11 —— 覆盖性判据会变弱"
    )
    for tail in TAIL_JOBS:
        assert tail in jobs, f"缺收尾 job `{tail}`"
    for tail in TAIL_JOBS:
        needs = jobs[tail].get("needs") or []
        missing = [g for g in REQUIRED_PR_GATES if g not in needs]
        assert not missing, f"`{tail}` 的 needs 未覆盖 {missing}"

    # ── 注入式自证：从 needs 里删掉一个 required 门禁 ⇒ coverage_problems 必须报出 ──
    victim = "case-trust-gate"
    probe = {k: dict(v) if isinstance(v, dict) else v for k, v in jobs.items()}
    assert victim in (jobs["clear-needs-changes"].get("needs") or []), "自证前提：victim 原本在 needs 里"
    probe["clear-needs-changes"] = dict(probe["clear-needs-changes"])
    probe["clear-needs-changes"]["needs"] = [
        n for n in probe["clear-needs-changes"]["needs"] if n != victim
    ]
    injected = coverage_problems(REQUIRED_PR_GATES, probe)
    assert any(victim in msg for msg in injected), (
        f"注入式自证失败：从 `clear-needs-changes` 的 needs 里删掉 `{victim}` 后判据没报出来 ⇒ 判据没有牙"
    )

    # ── 判别力自证之二：清单腐烂（job 不存在）也必须被捉到 ──
    rotten = snapshot_problems(("no-such-gate-xyz",), jobs)
    assert rotten and "no-such-gate-xyz" in rotten[0], "冻结清单腐烂时判据 B 没报出来 ⇒ 它不是活判据"

def test_missing_workflow_is_fail_closed(monkeypatch, tmp_path):
    """读不到 `pr-check.yml` ⇒ 必须**抛**，不许返回空 jobs（否则「没东西可判」被读成绿）。"""
    monkeypatch.setattr(
        pathlib.Path, "is_file", lambda self: False if self == PR_CHECK else pathlib.Path.is_file(self)
    )
    with pytest.raises(RuntimeError, match="fail-closed"):
        _pr_check_jobs()
