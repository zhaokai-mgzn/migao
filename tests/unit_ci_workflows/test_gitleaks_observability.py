# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012。）
"""`Secret Scan (gitleaks)` 的**可观测性**（issue #7208）—— 让失败能归因到"真扫到密钥"还是"未判定"。

## 这守的是什么（实测事故，不是设想）

2026-10-18 上午，这条腿在**多条无关 PR** 上判红，而日志里：
- `Run gitleaks secret scan` 在**启动约 1 秒**就结束；
- **没有** leak / RuleID / finding 行，只有 node 弃用警告；
- 与"真扫到密钥"的日志形态**完全同形**。

我据此在 issue #7208 里误判成"这条腿系统性坏了"；独立核查后才发现真正原因是我自己 PR 的历史提交
（`acceptance/**` 里的活 JWT）—— 判定用了 20 分钟，代价全在"读不出原因"上。

## 修法（三步，缺一不可）与判据

| # | 形态 | 为什么不可省 | 判据（会红） |
|---|---|---|---|
| ① | 扫描步骤 `continue-on-error: true` + `id` | 否则失败即收尾，归因步骤**永远跑不到** | 去掉 `continue-on-error` ⇒ `test_scan_step_continues_on_error` |
| ② | 报告**一律上传**（`if: always()`） | 失败也要能事后取证据（否则只能靠猜） | 去掉上传步 / 改成 `if: success()` ⇒ `test_report_uploaded_always` |
| ③ | 归因步骤区分两种形态（`GITLEAKS_FINDINGS` / `GITLEAKS_NO_REPORT`） | 这是本次误判的**唯一根因**：无报告被读成"没有密钥" | 删掉任一支 ⇒ `test_classification_distinguishes_both_cases` |

## 为什么用静态判据而不是"跑一遍看日志"

CI workflow 结构不是 LLM/业务真值（真值由 `tests/unit_ci_workflows/` 这类结构判据承担，见 MC-012 的
`truths_ref: []` 登记）。跑真 workflow 需要 PR 事件 + 真 token，成本远高于它此刻能证明的东西；
而"步骤是否存在、条件是否为 always、两种形态是否都判"**完全可以静态读出**，且删一条就红。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr-check.yml"


@pytest.fixture(scope="module")
def job() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    jobs = data.get("jobs", {})
    assert "gitleaks-scan" in jobs, f"{WORKFLOW} 里没有 gitleaks-scan job（被判据引用的对象没了）"
    return jobs["gitleaks-scan"]


def _step(job: dict, name_prefix: str) -> dict:
    for step in job.get("steps", []):
        if str(step.get("name", "")).startswith(name_prefix):
            return step
    raise AssertionError(f"找不到步骤 `{name_prefix}`（判据对象缺失 ⇒ 判定不得当通过）")


def test_scan_step_continues_on_error(job):
    """① 扫描步骤必须 `id` + `continue-on-error: true`，否则后续归因步骤永远跑不到。

    红证 = 删掉 `continue-on-error: true` ⇒ 本用例必红（这正是修法前的形态）。
    """
    scan = _step(job, "Run gitleaks secret scan")
    assert scan.get("id") == "gitleaks", "扫描步骤必须有 id，供归因步骤读 outcome"
    assert scan.get("continue-on-error") is True, (
        "扫描步骤必须 continue-on-error: true —— 否则它一失败整个 job 就收尾，"
        "「上传报告」「归因」两步永远跑不到（issue #7208 的实测形态）")
    assert scan.get("uses", "").startswith("gitleaks/gitleaks-action"), "扫描本体仍是官方 action（不另造判定）"


def test_report_uploaded_always(job):
    """② 报告上传必须 `if: always()`（失败时也要能取证据）。"""
    upload = _step(job, "Upload gitleaks report")
    assert str(upload.get("if", "")).strip() == "always()", (
        "上传步骤必须 `if: always()` —— 换成 success() 等于「失败时最需要证据却拿不到」")
    paths = str(upload.get("with", {}).get("path", ""))
    assert "results.sarif" in paths, f"必须上传 action 产出的 results.sarif（现取：{paths!r}）"
    assert upload.get("with", {}).get("if-no-files-found") == "warn", (
        "找不到报告要 warn 而不是静默跳过 —— 静默正是本次误判的土壤")


def test_classification_distinguishes_both_cases(job):
    """③ 归因步骤必须**两种形态都判**：有 findings / 无报告（未判定）。

    红证 = 删掉 `GITLEAKS_NO_REPORT` 分支（即把"无报告"读成"没有密钥"）⇒ 本用例必红。
    """
    step = _step(job, "Classify gitleaks outcome")
    assert "steps.gitleaks.outcome == 'failure'" in str(step.get("if", "")), (
        "归因步骤只在扫描**失败**时跑（成功时不必多花一步）")
    body = str(step.get("run", ""))
    assert "GITLEAKS_NO_REPORT" in body, "必须区分「无报告 ⇒ 未判定」这一形态（本次误判的根因）"
    assert "GITLEAKS_FINDINGS" in body, "必须打印「真扫到 N 处」的具名清单（可归因）"
    assert "exit 1" in body, "两种形态都必须判红（fail-closed）—— 未判定不得当绿"
    # 反修过头：不许把「无报告」当绿
    no_report_block = body.split("GITLEAKS_NO_REPORT", 1)[1]
    assert "exit 1" in no_report_block.split("GITLEAKS_FINDINGS", 1)[0], (
        "「无报告」分支必须 exit 1（若改成 exit 0 = 把未判定读成通过，比误判更危险）")
