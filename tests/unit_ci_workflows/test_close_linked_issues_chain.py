# case_ids: MC-012
"""「PR 合并 → issue 自动关闭」链路的触发可靠性守卫（issue #3585）。

## 背景（2026-09-14 实测，非推断）

auto-merge 由 `automerge.yml` 用 `secrets.GITHUB_TOKEN` 开启，合并者恒为
`app/github-actions`。GitHub 规定 **GITHUB_TOKEN 引发的事件不创建新的 workflow run**
（防递归），于是 `close-linked-issues.yml` 的两条触发路径同时失灵：

| 触发 | 实测证据 | 后果 |
|---|---|---|
| `pull_request_target [closed]` | bot 合并 #3552/#3554（05:14Z）→ **零 run**；人工合并 #3395（09:43:48Z）→ run 09:43:51Z | 自动合并 **100%** 不触发 |
| `schedule '*/30'` | 近 7 天 57 个 run，相邻间隔实测 2~5.5h（21:01→23:20→01:23Z） | 「30 分钟兜底」是假象 |

同时 GitHub **原生** close-on-merge 也不生效：默认分支确为 `main`、body 第 1 行逐字节
即 `Closes #3548`、`closingIssuesReferences=[3548]` 已登记，合并后 issue 仍 OPEN 且
timeline 连 `closed` 事件都没有。

结果：`#3516/#3518/#3520/#3521/#3539/#3543/#3553/#3560` 共 8 个 issue 的 `Closes`
已随 PR 合入 main，却仍 OPEN，全靠人工回头对账——AGENTS.md §4/§2.2 的治理目标失效。

同一根因早被 `deploy-reconcile.yml` 记录（issue #3113）：native auto-merge 之后
`push` / `pull_request closed` 不再触发任何 workflow；只有 `pull_request opened/reopened`、
`issues`、`issue_comment`、`workflow_dispatch` 可靠。

## 本守卫锁什么

可靠触发源 + 关issue 权限 + 「非 closed 事件不得误用单 PR 号」+ 批量取 body 防限流 +
不对 PR 代码 checkout。这几项任一被改掉，链条会**静默**退回「写了 Closes 也不关」，
只有真实合并才暴露（本次就是这样漏过去的），故必须在 PR 阶段以零成本 L0 拦住。
"""
import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS_DIR = Path(__file__).parent.parent.parent / ".github" / "workflows"
WORKFLOW = "close-linked-issues.yml"

_REPO = "zhaokai-mgzn/migao"

# 触发门禁表达式里用到的上下文键（长键在前，避免前缀替换相互破坏）
_EXPR_KEYS = (
    "github.event.pull_request.head.repo.full_name",
    "github.event.pull_request.merged",
    "github.repository",
    "github.event_name",
    "github.event.action",
)


def _load():
    return yaml.safe_load((WORKFLOWS_DIR / WORKFLOW).read_text(encoding="utf-8")) or {}


def _triggers(d):
    # YAML 1.1 把裸 `on` 解析成布尔 True
    return d.get("on") or d.get(True) or {}


def _job(d):
    return (d.get("jobs") or {})["close-linked-issues"]


def _script(d):
    return "\n".join(s.get("run") or "" for s in _job(d).get("steps") or [])


def _eval_gate(cond, **ctx):
    """把 workflow 的 `if:` 表达式按上下文求值（受控 eval，表达式来自本仓库文件）。"""
    ctx.setdefault("github.repository", _REPO)
    ctx.setdefault("github.event.pull_request.head.repo.full_name", _REPO)
    expr = cond
    for key in _EXPR_KEYS:
        expr = expr.replace(key, repr(ctx.get(key)))
    assert "github." not in expr, f"表达式含未建模的上下文键：{expr}"
    expr = re.sub(r"\btrue\b", "True", expr)
    expr = re.sub(r"\bfalse\b", "False", expr)
    return eval(expr.replace("&&", " and ").replace("||", " or "))  # noqa: S307


class TestCloseLinkedIssuesChain:
    def test_issues_write_permission_declared(self):
        """`pull_request_target` 默认只读 → 缺 issues: write 会「run 成功但一个 issue 都关不掉」。"""
        assert (_load().get("permissions") or {}).get("issues") == "write", (
            "close-linked-issues.yml 必须声明 permissions.issues: write，"
            "否则 gh issue close 全部 403（run 仍报 success，静默失效）"
        )

    def test_has_trigger_immune_to_github_token_suppression(self):
        """必须有**不依赖合并事件**的触发类型：bot 合并不触发 closed（issue #3585 真因）。"""
        types = set((_triggers(_load()).get("pull_request_target") or {}).get("types") or [])
        assert types & {"opened", "reopened"}, (
            f"pull_request_target.types={sorted(types)} 只有合并/关闭类事件时，"
            "native auto-merge（GITHUB_TOKEN）合并 100% 不触发本 workflow → issue 不会自动关闭"
        )

    @pytest.mark.parametrize(
        "name,ctx,expected",
        [
            ("schedule", {"github.event_name": "schedule"}, True),
            ("workflow_dispatch", {"github.event_name": "workflow_dispatch"}, True),
            (
                "pr_target opened（可靠兜底路径）",
                {"github.event_name": "pull_request_target", "github.event.action": "opened"},
                True,
            ),
            (
                "pr_target reopened（可靠兜底路径）",
                {"github.event_name": "pull_request_target", "github.event.action": "reopened"},
                True,
            ),
            (
                "pr_target closed+merged+同仓库（人工合并即时补偿）",
                {
                    "github.event_name": "pull_request_target",
                    "github.event.action": "closed",
                    "github.event.pull_request.merged": True,
                    "github.event.pull_request.head.repo.full_name": "zhaokai-mgzn/migao",
                },
                True,
            ),
            (
                "pr_target closed 未合并（必须 skip）",
                {
                    "github.event_name": "pull_request_target",
                    "github.event.action": "closed",
                    "github.event.pull_request.merged": False,
                    "github.event.pull_request.head.repo.full_name": "zhaokai-mgzn/migao",
                },
                False,
            ),
            (
                "pr_target closed+merged 但 fork（必须 skip）",
                {
                    "github.event_name": "pull_request_target",
                    "github.event.action": "closed",
                    "github.event.pull_request.merged": True,
                    "github.event.pull_request.head.repo.full_name": "someone/fork",
                },
                False,
            ),
        ],
    )
    def test_job_gate_admits_reliable_events(self, name, ctx, expected):
        """job `if` 不得把 opened/reopened 一并 skip（旧写法要求 merged==true 正是这个坑）。"""
        cond = _job(_load()).get("if") or ""
        assert _eval_gate(cond, **ctx) is expected, f"{name} 的判定不符预期：if={cond!r}"

    def test_non_closed_event_never_uses_single_pr_mode(self):
        """opened/reopened 事件里 `github.event.pull_request.number` 是**未合并** PR：
        若误入单 PR 模式，就会拿未合并 PR 的 `Closes #x` 去关 issue（假关闭）。
        故单 PR 模式只能由 dispatch 的 pr_number 或 closed 事件启用，其余走 48h 对账。"""
        script = _script(_load())
        assert "DISPATCH_PR" in script, "缺 workflow_dispatch 的 pr_number 单 PR 补偿入口"
        assert re.search(r'EVENT_ACTION"?\s*=\s*"closed"', script), (
            "单 PR 模式必须显式以 closed 事件为条件（否则 opened 事件会误用未合并 PR 号）"
        )
        assert "--state merged" in script and "hours ago" in script, (
            "缺「近 48h 已合并 PR 对账」路径：可靠事件触发后必须能扫出被吞掉的历史合并"
        )

    def test_reconcile_batches_body_fetch(self):
        """高频触发 + 近 48h 合并 PR 实测可达 135 个 ⇒ 必须一次 list 批量取 body；
        逐个 `gh pr view` 会打爆 GITHUB_TOKEN 1000 请求/小时/仓库限额，
        超限后 gh 静默失败 → 又退回「写了 Closes 也不关」。"""
        script = _script(_load())
        assert re.search(r"gh pr list[\s\S]{0,400}?--json number,mergeCommit,body", script), (
            "对账模式必须用 gh pr list --json ...body 批量取 body"
        )
        assert script.count("gh pr view") <= 1, (
            "脚本里出现多处 gh pr view：对账分支不得逐 PR 取 body（限流自毁）"
        )

    def test_does_not_checkout_pr_code(self):
        """`pull_request_target` 下执行 PR 代码 = 高危（可读取 secrets）。
        本 workflow 只应通过 API 读 body / 关 issue，不得出现 actions/checkout。"""
        steps = _job(_load()).get("steps") or []
        offenders = [s.get("uses") for s in steps if "checkout" in (s.get("uses") or "")]
        assert not offenders, f"pull_request_target workflow 不得 checkout：{offenders}"
