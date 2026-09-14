# case_ids: MC-012
r"""「cancelled 的评测 run 不得被记成失败」的 L0 静态不变式（issue #3761）。

## 背景（实测，2026-09-14，全部锚定 run id）

`post-deploy-eval.yml` 的判定链在**被取消**时会走出一条错误的语义：

| 环节 | 原实现 | 后果 |
|---|---|---|
| eval job「判定（completion_verdict）」 | `if: always() && superseded != 'true'`（**缺 `!cancelled()`**） | run 被 cancel ⇒ 没有 `eval-summary-*.json` ⇒ 走「无汇总文件 → 判定失败」→ `exit 1`（实测 run 34855662092 的该步 `[failure]`） |
| report job「Create Issue on failure」 | `if: needs.eval.result == 'failure' \|\| needs.eval.result == 'cancelled'` | **取消被显式算作失败** → 建/追加 issue |

实证（`gh issue view 3534`，三条评论原文「同日同标题再次失败（新增 run）… 无汇总文件」）：

    runs/34854787236（cancelled）  runs/34855662092（cancelled）  runs/34856014641（cancelled）

三条 run 的 `conclusion` 都是 `cancelled`，且评论给出的归因（「栈/登录/依赖等环境问题」）是**错的**
—— 它们是被**派发侧并发互杀**取消的（该时段 10 个 cancelled run，其中 2 个已进到
`Start local stack` 跑了 ~1.6min）。

## 纪律（两条，缺一不可）

① **取消不是结果**：`cancelled` 不得判 failure、不得建 issue
   （`migao-dev-flow` §16.5「跳过不得算 failure」；`migao-acceptance`「cancelled 的 run 不构成结论」）。
② **但取消要可见**：`::warning::` annotation + step summary 抬头「本 run 被取消（未评测，不构成结论）」
   —— 只要"可见"不要"变红"（重复留红会让真失败与噪音同形，正是 #3534 那条 issue 的病灶）。

## 红证

检查器是**纯函数 over YAML dict**，测试用**改坏的副本**证明它会红（4 条注入 + 1 条反向）。
"""
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "post-deploy-eval.yml"

VERDICT_KW = "判定（completion_verdict"


def _load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _steps(doc: dict, job: str) -> list:
    return ((doc.get("jobs") or {}).get(job) or {}).get("steps") or []


def _by_name(steps: list, kw: str) -> list:
    return [s for s in steps if kw in (s.get("name") or "")]


def cancelled_violations(doc: dict) -> list:
    """「取消被记成失败 / 取消不可见」的违规清单（空 = 合规）。"""
    v = []
    eval_steps = _steps(doc, "eval")

    # ── ① 判定步骤不得在取消时执行到"无汇总文件 → 失败"分支 ──
    verdict = _by_name(eval_steps, VERDICT_KW)
    if len(verdict) != 1:
        v.append(f"eval job 的「判定」步骤不唯一（{len(verdict)} 个）—— 检查器锚点失效，"
                 "本测试会退化成空断言")
    elif "!cancelled()" not in (verdict[0].get("if") or ""):
        v.append("判定步骤没排除 `cancelled()` —— 被取消的 run 会走「无汇总文件 → 判定失败」"
                 "→ exit 1 → report job 把它记成「部署后回归失败」（#3761）")

    # ── ② 取消必须可见（eval job 侧） ──
    rec = _by_name(eval_steps, "被取消记录")
    if not rec:
        v.append("eval job 缺「被取消记录」步骤 —— 取消将无法与「评测通过」区分（静默跳过）")
    else:
        s = rec[0]
        if "cancelled()" not in (s.get("if") or ""):
            v.append("「被取消记录」步骤未挂在 `cancelled()` 上 —— 正常 run 也会打这条警告（噪音）")
        if "::warning::" not in (s.get("run") or ""):
            v.append("「被取消记录」未打 `::warning::` —— 取消在 run 列表上不可见")

    # ── ③ report job 的建 issue 条件 ──
    report_steps = _steps(doc, "report")
    issue = _by_name(report_steps, "Create Issue")
    if len(issue) != 1:
        v.append(f"report job 的建 issue 步骤不唯一（{len(issue)} 个）—— 锚点失效")
    else:
        cond = issue[0].get("if") or ""
        if "cancelled" in cond:
            v.append("建 issue 条件含 `cancelled` —— 取消会被记成「部署后回归失败」"
                     "（#3534 的 3 条假失败评论）")
        if "failure" not in cond:
            v.append("建 issue 条件丢了 `failure` —— 真失败不再留痕（反向假绿，同样有害）")

    # ── ④ 取消必须可见（report job / 结论档侧） ──
    trace = _by_name(report_steps, "被取消留档")
    if not trace:
        v.append("report job 缺「被取消留档」步骤 —— 取消在结论档上不可追踪")
    else:
        s = trace[0]
        if "cancelled" not in (s.get("if") or ""):
            v.append("「被取消留档」未以 `needs.eval.result == 'cancelled'` 为判据")
        if "::warning::" not in (s.get("run") or ""):
            v.append("「被取消留档」未打 `::warning::` —— 结论档上不可见")
    return v


# ── ① 现状：真实 workflow 必须合规 ──────────────────────────────────────────

class TestWorkflowTreatsCancelledAsNoConclusion:
    def test_current_workflow_is_clean(self):
        v = cancelled_violations(_load())
        assert v == [], "取消语义退化：\n" + "\n".join(v)

    def test_failure_still_files_issue(self):
        """反向守卫：不能为了"取消不建 issue"把真失败也放过（否则是另一种假绿）。"""
        issue = _by_name(_steps(_load(), "report"), "Create Issue")[0]
        assert "needs.eval.result == 'failure'" in (issue.get("if") or ""), \
            "真失败（needs.eval.result == failure）不再建 issue —— 失败会静默"

    def test_supersede_semantics_untouched(self):
        """本改动只动"取消"，不得影响"被抑制"（§16.6 的 force_eval / 可见性口径）。"""
        eval_steps = _steps(_load(), "eval")
        verdict = _by_name(eval_steps, VERDICT_KW)[0]
        assert "superseded != 'true'" in (verdict.get("if") or ""), \
            "判定步骤丢了抑制门 —— 被抑制的 run 会判失败（把省成本变成刷假红灯）"
        assert _by_name(eval_steps, "被抑制记录"), "缺「被抑制记录」步骤（审计链断）"


# ── ② 红证：改坏的副本必须被抓到 ────────────────────────────────────────────

class TestCheckerGoesRedOnMutations:
    """每条判据都要有「喂坏数据必报」的证明（migao-acceptance 铁律 2：不会红的断言=空断言）。"""

    @staticmethod
    def _mutated():
        return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

    def test_red_when_verdict_runs_on_cancel(self):
        doc = self._mutated()
        v = _by_name(_steps(doc, "eval"), VERDICT_KW)[0]
        v["if"] = "always() && steps.supersede.outputs.superseded != 'true'"   # 去掉 !cancelled()
        assert any("!cancelled" in m for m in cancelled_violations(doc)) or \
            any("cancelled()" in m for m in cancelled_violations(doc)), \
            "去掉 !cancelled() 后检查器没报 —— 取消又会被判失败"

    def test_red_when_issue_step_counts_cancelled(self):
        doc = self._mutated()
        issue = _by_name(_steps(doc, "report"), "Create Issue")[0]
        issue["if"] = "needs.eval.result == 'failure' || needs.eval.result == 'cancelled'"
        assert any("cancelled" in m for m in cancelled_violations(doc)), \
            "把 cancelled 写回建 issue 条件后检查器没报 —— 假失败噪音会复发"

    def test_red_when_issue_step_drops_failure(self):
        doc = self._mutated()
        issue = _by_name(_steps(doc, "report"), "Create Issue")[0]
        issue["if"] = "always()"
        assert any("failure" in m for m in cancelled_violations(doc)), \
            "去掉 failure 条件后检查器没报 —— 真失败静默"

    def test_red_when_cancel_trace_removed(self):
        doc = self._mutated()
        steps = _steps(doc, "eval")
        doc["jobs"]["eval"]["steps"] = [s for s in steps if "被取消记录" not in (s.get("name") or "")]
        assert any("被取消记录" in m for m in cancelled_violations(doc)), \
            "删掉「被取消记录」后检查器没报 —— 取消变成静默"

    def test_red_when_warning_marker_removed(self):
        doc = self._mutated()
        s = _by_name(_steps(doc, "report"), "被取消留档")[0]
        s["run"] = (s.get("run") or "").replace("::warning::", "::notice::")
        assert any("::warning::" in m for m in cancelled_violations(doc)), \
            "去掉 ::warning:: 后检查器没报 —— 取消在结论档上不再可见"
