# case_ids: MC-012
"""「PR 合并 → 自动评审/验收」链路（verify-trigger.yml）的触发可靠性守卫（issue #3608）。

## 背景（2026-09-14 实测，非推断）

`verify-trigger.yml` 是验收链路唯一入口：贴 `<!-- VERIFY_TRIGGER -->` 机器可读标记
（acceptance-protocol 的验收锚点）+ 打 `ai-verify/pending`（验收队列标记，同时是
`stale.yml` 的豁免标签）+ issue 若已关闭则 reopen。旧版触发源是 `on: pull_request: [closed]`。

auto-merge 由 `automerge.yml` 用 `secrets.GITHUB_TOKEN` 开启 ⇒ **合并者恒为 `app/github-actions`**
⇒ GitHub「GITHUB_TOKEN 引发的事件不创建新 run」的既有语义把这条链路**整条吞掉**：

| 证据 | 实测值 |
|---|---|
| 近 48h verify-trigger run 总数 | **18**（覆盖率 18/135 = 13%） |
| 其中由人工合并触发 | **18/18**（#3395 09:43:48Z→run 09:43:50Z，2s；#3385 06:17:49Z→06:17:51Z；#3382 04:50:05Z→04:50:08Z） |
| bot 合并触发 | **0**（#3547 05:13:11Z / #3552 05:14:27Z / #3554 05:14:34Z / #3555 05:19:44Z / #3580 05:38:43Z 全部零 run） |
| 48h bot 合并 PR 数 / 其中 body 带 `Closes #N` | 117（87%）/ **77** |
| 存量带 `ai-verify/pending` 的 issue 数 | **0** |
| 漏触发实证 | #3487（bot 合并 02:34:40Z，`#3486`）→ issue #3486 无标记、无标签、未 reopen |
| 另一段零 run 空窗 | 09-05 08:42Z → 09-12 21:16Z（**7 天整**） |

同一根因前两例：`deploy-reconcile.yml`（issue #3113，push 被吞）、
`close-linked-issues.yml`（issue #3585，closed 被吞）。本守卫是其第三例。

## 本守卫锁什么

可靠触发源 + 不把可靠事件一并 skip 的 job 闸 + 单 PR 模式与对账模式分离 +
批量取数防限流 + 突发流量三道节流。任一被改掉，链路会**静默**退回「合并了也不触发验收」，
只有真实合并（且 bot 合并是常态）才暴露——本次就是这样漏过 7 天的，故必须 L0 零成本拦住。
"""
import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS_DIR = Path(__file__).parent.parent.parent / ".github" / "workflows"
WORKFLOW = "verify-trigger.yml"

_REPO = "zhaokai-mgzn/migao"

# 触发/闸门表达式里用到的上下文键（长键在前，避免前缀替换相互破坏）
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
    return (d.get("jobs") or {})["trigger"]


def _script(d):
    return "\n".join(s.get("run") or "" for s in _job(d).get("steps") or [])


def _script_code(d):
    """去掉 bash 注释行后的**可执行**脚本（注释里提到 `gh pr view` 不算违规）。"""
    return "\n".join(
        ln for ln in _script(d).splitlines() if not ln.lstrip().startswith("#")
    )


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


class TestVerifyTriggerChain:
    def test_issues_write_permission_declared(self):
        """缺 `issues: write` 会「run 成功但一条标记都贴不上」（403 被 `|| true` 吞掉）。"""
        assert (_load().get("permissions") or {}).get("issues") == "write", (
            "verify-trigger.yml 必须声明 permissions.issues: write，"
            "否则 gh issue comment/edit/reopen 全部 403"
        )

    def test_has_trigger_immune_to_github_token_suppression(self):
        """必须有**不依赖 PR 合并事件**的触发类型：bot 合并不触发 closed（issue #3608 真因）。

        旧版只有 `pull_request: [closed]` → bot 合并（本仓库 87% 的合并方式）100% 不触发。
        """
        types = set((_triggers(_load()).get("pull_request_target") or {}).get("types") or [])
        assert types & {"opened", "reopened"}, (
            f"pull_request_target.types={sorted(types)}：必须有 opened/reopened 这类"
            "「PR 打开即触发」的可靠事件，否则 auto-merge（GITHUB_TOKEN）合并的 PR 零触发"
        )

    def test_has_manual_dispatcher_entry(self):
        """保留 workflow_dispatch：既是运维补触发入口，也是本修复真实验证的入口。"""
        assert "workflow_dispatch" in _triggers(_load()), (
            "缺 workflow_dispatch，无法手动补触发/验证"
        )

    @pytest.mark.parametrize(
        "name,ctx,expected",
        [
            ("workflow_dispatch（手动补触发）", {"github.event_name": "workflow_dispatch"}, True),
            ("schedule（定时兜底）", {"github.event_name": "schedule"}, True),
            (
                "pull_request_target opened（可靠主路径，PR 未合并）",
                {
                    "github.event_name": "pull_request_target",
                    "github.event.action": "opened",
                    "github.event.pull_request.merged": None,
                },
                True,
            ),
            (
                "pull_request_target reopened（可靠主路径，PR 未合并）",
                {
                    "github.event_name": "pull_request_target",
                    "github.event.action": "reopened",
                    "github.event.pull_request.merged": None,
                },
                True,
            ),
            (
                "pull_request closed + merged（人工合并即时补偿）",
                {
                    "github.event_name": "pull_request",
                    "github.event.action": "closed",
                    "github.event.pull_request.merged": True,
                },
                True,
            ),
            (
                "pull_request closed 未合并（必须 skip）",
                {
                    "github.event_name": "pull_request",
                    "github.event.action": "closed",
                    "github.event.pull_request.merged": False,
                },
                False,
            ),
        ],
    )
    def test_job_gate_admits_reliable_events(self, name, ctx, expected):
        """job `if` 不得把 opened/reopened 一并 skip。

        旧版 job 无 `if`，只在 step 里跑 `MERGED != true → exit 0`；一旦给 job 加
        `if: github.event.pull_request.merged == true`（#3585 范式里最自然的写法），
        opened/reopened 的 `merged` 恒为 null/false ⇒ **可靠触发源被自己的闸门 skip 掉**，
        链路又静默失效。这是本修复里最容易写错的一行，故单独锁死。
        """
        cond = _job(_load()).get("if") or ""
        assert _eval_gate(cond, **ctx) is expected, f"{name} 的判定不符预期：if={cond!r}"

    def test_step_level_merged_guard_keeps_pull_request_target_alive(self):
        """step 级护栏同样不得把 pull_request_target 一并 exit 掉（与 job 闸双保险）。"""
        script = _script(_load())
        assert re.search(r'EVENT_NAME"?\s*=\s*"pull_request"\s*\]\s*&&', script) or \
               re.search(r'EVENT_NAME\s*=\s*"pull_request"', script), (
            "step 护栏必须**显式限定在 pull_request 事件**上判 merged（旧版裸判 merged，"
            "pull_request_target 的 merged 为 null 会被误判 exit）"
        )
        # 裸判（不含 event_name 限定）会让 pull_request_target 直接 exit
        assert not re.search(r'if\s+\[\s*"\$MERGED"\s*!=\s*"true"\s*\]\s*;\s*then\s*\n\s*echo\s+"⏭️', script), (
            "发现裸 `if [ \"$MERGED\" != \"true\" ]` 早退：pull_request_target(opened/reopened) "
            "的 merged 是 null ⇒ 可靠触发源会被这一步 exit 掉"
        )

    def test_non_closed_event_never_uses_single_pr_mode(self):
        """opened/reopened 事件里 `github.event.pull_request.number` 是**未合并** PR：
        若误入单 PR 模式，就会拿未合并 PR 的 `Closes #x` 去贴 VERIFY_TRIGGER / reopen issue
        （假验收）。故单 PR 模式只能由 dispatch 的 pr_number 或 closed 事件启用。"""
        script = _script(_load())
        assert "DISPATCH_PR" in script, "缺 workflow_dispatch 的 pr_number 单 PR 补触发入口"
        assert re.search(r'EVENT_ACTION"?\s*=\s*"closed"', script), (
            "单 PR 模式必须显式以 closed 事件为条件（否则 opened 事件会误用未合并 PR 号）"
        )
        assert re.search(r"gh pr list --state merged[\s\S]{0,300}?--limit", _script_code(_load())), (
            "缺「已合并 PR 对账」路径：可靠事件触发后必须能扫出被吞掉的历史合并"
        )
        assert "mergedAt" in _script_code(_load()) and "since" in _script_code(_load()), (
            "缺时间窗口过滤（mergedAt >= since）：对账无法界定范围 → 会每次全量扫（限流自毁）"
        )

    def test_reconcile_batches_data_fetch(self):
        """高频触发 + 近 48h 合并 PR 实测可达 135 个 ⇒ 必须 `gh pr list --json` 批量取 body；
        逐个 `gh pr view` 会打爆 GITHUB_TOKEN 1000 请求/小时/仓库限额，超限后 gh 静默失败
        → 又退回「合并了也不触发验收」。"""
        code = _script_code(_load())
        assert re.search(r"gh pr list[\s\S]{0,500}?--json number,mergeCommit[\S]*body", code), (
            "对账模式必须用 gh pr list --json ...body 批量取 body（禁逐 PR 取数）"
        )
        assert code.count("gh pr view") == 0, (
            "可执行脚本里不得出现逐 PR 取数的 `gh pr view`（对账分支会打爆限额）"
        )

    def test_batch_fetch_does_not_inline_candidate_list_into_jq(self):
        """取数必须**失败关闭**，且不得把候选号内联进 jq 表达式。

        两条都是本 PR 真实踩过的坑（run 34811018961：run 报 success 但 posted=0）：
        ① `gh ... --jq '... ('"$NUMS"' | split(",") | map(tonumber) | index($n) ...)'` ——
           只有 1 个候选时 `$NUMS` 是 `3487`，被 jq 词法解析成**数字** ⇒
           `split cannot be applied to: number` ⇒ 取数为 0，而 `|| true` 把错误吞掉；
        ② `gh` 的 `--jq` 只接受一个表达式，**不支持 `--argjson`/`--arg`**
           （实测报 `unknown arguments ["cand" ...]`）。
        ⇒ 取数要么用 python3 过滤（runner 自带），要么保证候选集是真正的 jq 数组；
        且有候选却取到 0 条时必须 **exit 1**（不得静默「处理了 0 个」）。
        """
        code = _script_code(_load())
        assert "index($n)" not in code, (
            "禁止把候选号内联进 jq 做 index() 过滤：单候选会被解析成数字 → 取数静默为 0"
        )
        assert "--argjson" not in code, (
            "gh 的 --jq 不支持 --argjson（实测 unknown arguments），不得使用"
        )
        assert re.search(r'NFETCH"?\s*-eq\s*0|\$\{?NFETCH\}?"?\s*-eq\s*0', code) and \
               re.search(r"exit 1", code), (
            "缺失败关闭：有候选却取到 0 条数据时必须 exit 1，而不是静默 success"
        )
        assert _script_code(_load()).count("gh pr view") == 0, (
            "可执行脚本里不得出现逐 PR 取数的 `gh pr view`（限流自毁）"
        )

    def test_collect_filters_candidates_by_merged_window(self):
        """候选收集必须**在收集时就按合并时间窗口过滤**（issue #3811 假红根因）。

        旧版 collect 只取 number（无 mergedAt），窗口过滤推迟到 processing：
        `gh pr list --state merged --limit N` 默认按**创建时间**倒序取最近 N 个 ——
        窗口内无新合并 PR 时（合法空窗），取到的 N 个候选全是窗口外旧 PR，
        processing 按 `mergedAt >= since` 全滤掉 ⇒ NFETCH=0 ⇒ 被 fail-closed
        误判为「取数链路缺陷」exit 1。实证：run 34945688461 / 34946361347
        （#3811 持续失败）「候选 5 取到 0」，失败窗口 07:12–08:12Z 内确实无合并
        （上一次 07:05 #3913，下一次 08:22 #3915）—— 合法空窗被报红。
        修复：collect 阶段 `gh pr list --json number,mergedAt` + python 按 since 过滤，
        窗口空 ⇒ 零候选 ⇒ 走「零候选 PR，结束」exit 0。
        """
        code = _script_code(_load())
        assert re.search(r"gh pr list --state merged[\s\S]{0,300}?--json number,mergedAt", code), (
            "候选收集必须带 mergedAt（`--json number,mergedAt`），否则无法在收集时按窗口过滤"
        )
        assert re.search(r"at\s*<\s*since", code), (
            "候选收集阶段必须有 mergedAt >= since 的窗口过滤（python 过滤行）"
        )
        # 窗口空 = 合法空窗：candidates.txt 为空时应走 exit 0，而不是 NFETCH=0 的 exit 1
        assert re.search(r'零候选 PR，结束[\s\S]{0,120}?exit 0', code), (
            "零候选必须显式 exit 0（合法空跑）—— 不得把空窗当作缺陷报红"
        )

    def test_collect_failure_still_fail_closed(self):
        """取数失败与空窗必须区分：`gh pr list` 返回 0 条 = 限流/权限/网络缺陷，
        必须 exit 1（fail-closed），不得被「零候选 exit 0」吞成静默成功。"""
        code = _script_code(_load())
        assert "candidates_raw.err" in code, (
            "缺候选收集 stderr 捕获：gh pr list 失败（限流/权限）必须可见"
        )
        assert "RAW_COUNT" in code, (
            "缺取数 0 条 vs 空窗的区分判据（RAW_COUNT）：0 条 = 取数缺陷，非空窗"
        )
        assert re.search(r"RAW_COUNT[\s\S]{0,200}?-eq\s*0[\s\S]{0,200}?exit 1", code), (
            "取数返回 0 条必须 exit 1（缺陷），与「窗口过滤后 0 条 = 空窗 exit 0」分开"
        )

    def test_burst_throttled(self):
        """修复后对账会一次扫出 77 个历史漏触发 PR ⇒ 必须幂等 + 限流，否则修复本身变资源黑洞。

        三道节流缺一不可：① 幂等（已贴标记/已有 ai-verify 标签 → skip）；
        ② 按事件类型收窄候选窗口（最频繁的 opened 只做轻量补漏）；
        ③ API 预算闸（剩余额度不足则停，不半途而废）。
        """
        code = _script_code(_load())
        assert re.search(r'pr_number\\":\s*"?\s*\+?\s*os\.environ\["PR_NUM"\]', code) or \
               re.search(r'VERIFY_TRIGGER" in .*pr_number', code), (
            "缺幂等判据：必须检查 issue 上是否已存在指向该 PR 号的 VERIFY_TRIGGER 标记"
        )
        assert "MARKED" in code and re.search(r'"\$\{?MARKED\}?"?\s*!=\s*"0"', code), (
            "缺幂等判据的可判定性守卫：取不到评论时不得当作「未处理过」"
        )
        assert re.search(r"grep\s+-qE\s+'\^ai-verify/'", code), (
            "缺第二道幂等：issue 已带 ai-verify/* 标签时不得重复入队"
        )
        assert "rate_limit" in code and "remaining" in code, (
            "缺 API 预算闸（gh api rate_limit）：长循环跑到一半被限流会静默失败"
        )
        assert re.search(r"LIMIT=5\b", code), (
            "缺「高频事件只做轻量补漏」的候选收窄（opened 是最频繁触发源，不得每次全量扫）"
        )

    def test_every_candidate_leaves_a_trace(self):
        """旧版 `No linked issue, skip` 没有任何输出 ⇒ 静默失效 7 天无人发现。
        每个候选 PR 在每个分支都必须打印一行日志（可对账是把静默失效变可视化的唯一手段）。"""
        script = _script(_load())
        for marker in ("无 linked issue", "幂等", "跳过", "✅ VERIFY_TRIGGER posted"):
            assert marker in script, f"缺对账痕迹输出：{marker}"
        assert "GITHUB_STEP_SUMMARY" in script, "缺 run summary 落盘（run 页面即可读处理结果）"

    def test_checkout_pins_main_not_pr_head(self):
        """`pull_request_target` 下执行 PR 代码 = 高危（可读 secrets）。
        本 workflow 只用 gh API，必须 checkout `main` 固定 ref（永不取 PR head）。"""
        steps = _job(_load()).get("steps") or []
        co = [s for s in steps if "checkout" in (s.get("uses") or "")]
        assert co, "缺 checkout：新版 gh CLI 在无 git 上下文时无法解析仓库（issue #2929）"
        for s in co:
            assert (s.get("with") or {}).get("ref") == "main", (
                "checkout 必须固定 ref: main（pull_request_target 下取 PR head = 高危）"
            )
        assert "${{ github.event.pull_request.head.sha }}" not in _script(_load()), (
            "脚本里不得引用 PR head sha"
        )
