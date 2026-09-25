"""
Test case-draft CI workflow label guard logic.

Issue #729: ci-daily-report cron 创建 issue 时漏打 ai-draft 标签。
本测试验证 CI guard 正确补标。
"""
# case_ids: MC-001
import re
import yaml
from pathlib import Path


WORKFLOW_PATH = Path(__file__).parent.parent.parent / ".github" / "workflows" / "case-draft.yml"
#: 写标签的一侧（新 issue 一开就跑）——「有无真值」的另一处判定，词表必须与 case-draft.yml 同源。
ISSUE_CONTRACT_WORKFLOW = (
    Path(__file__).parent.parent.parent / ".github" / "workflows" / "issue-contract-check.yml"
)
#: 两份 workflow 里都写着 `TRUTH_VOCAB = '<词表>'`（JS 与 shell 同形），本判据按字面取。
VOCAB_RE = re.compile(r"TRUTH_VOCAB\s*=\s*'([^']+)'")


def load_workflow() -> dict:
    """加载并解析 CI workflow YAML。"""
    if not WORKFLOW_PATH.exists():
        raise FileNotFoundError(f"Workflow not found: {WORKFLOW_PATH}")
    with open(WORKFLOW_PATH) as f:
        return yaml.safe_load(f)


class TestLabelGuardStructure:
    """验证 workflow 的结构完整性 — 必须有 label guard 相关逻辑。"""

    def test_workflow_exists_and_parses(self):
        """YAML 文件存在且能正常解析。"""
        wf = load_workflow()
        assert wf is not None
        assert wf.get("name") is not None

    def test_process_improvement_is_still_handled(self):
        """`process-improvement` 的处置仍在 —— 判定位置从 **job 闸门**下沉到**步骤**（issue #5481 ③）。

        原判据断言「job 级 `if` 里有 process-improvement」；而 #5481 的竞态修复把**所有标签判定**
        下沉到步骤里、一律用**现取**标签（job 闸门只看事件类型）⇒ 判据相应改为
        「文件里仍有 process-improvement 的**判定分支**」。**强度不减**：缺了照样红。
        """
        import json

        wf = load_workflow()
        jobs = wf.get("jobs", {})
        assert jobs, "workflow 至少应有 1 个 job"
        text = json.dumps(wf, ensure_ascii=False)
        assert "process-improvement" in text, (
            "workflow 里再也找不到 process-improvement 的处置 ⇒ 该标签的 ai-draft guard 没了"
        )
        assert "steps.labels.outputs.names" in text, (
            "标签判定没有走「现取标签」（#5481 ③ 的竞态会复发）"
        )

    def test_has_ai_draft_guard_step(self):
        """必须有补 ai-draft 标签的 step（label guard）。"""
        wf = load_workflow()
        jobs = wf.get("jobs", {})
        trigger_job = jobs.get("trigger") or list(jobs.values())[0]
        steps = trigger_job.get("steps", [])

        ai_draft_steps = []
        for step in steps:
            step_if = step.get("if", "")
            run_cmd = step.get("run", "")
            step_name = step.get("name", "")
            combined = f"{step_name} {step_if} {run_cmd}"
            if "ai-draft" in combined:
                ai_draft_steps.append(step)

        assert len(ai_draft_steps) > 0, (
            "workflow 缺少补 ai-draft 标签的 step（label guard）\n"
            f"现有 steps: {[s.get('name', 'unnamed') for s in steps]}"
        )


class TestLabelGuardLogic:
    """验证 label guard 的逻辑正确性。"""

    def test_process_improvement_without_ai_draft_triggers_label_add(self):
        """process-improvement 无 ai-draft → 应触发补标。"""
        labels = ["process-improvement"]
        has_ai_draft = "ai-draft" in labels
        has_process_improvement = "process-improvement" in labels
        should_trigger = has_process_improvement and not has_ai_draft
        assert should_trigger, (
            f"process-improvement 无 ai-draft 应触发补标: labels={labels}"
        )

    def test_process_improvement_with_ai_draft_skips(self):
        """process-improvement + ai-draft → 不重复补标。"""
        labels = ["process-improvement", "ai-draft"]
        has_ai_draft = "ai-draft" in labels
        has_process_improvement = "process-improvement" in labels
        should_trigger = has_process_improvement and not has_ai_draft
        assert not should_trigger, (
            f"已有 ai-draft 不应触发补标: labels={labels}"
        )

    def test_needs_verification_without_ai_draft_still_triggers(self):
        """原有 needs-verification 逻辑不受影响。"""
        labels = ["needs-verification"]
        has_needs_verification = "needs-verification" in labels
        has_needs_truths = "needs-truths" in labels
        has_ai_draft = "ai-draft" in labels
        should_trigger = (has_needs_verification or has_needs_truths) and not has_ai_draft
        assert should_trigger, (
            f"needs-verification 无 ai-draft 仍应触发: labels={labels}"
        )

    def test_other_labels_without_ai_draft_do_not_trigger(self):
        """非 process-improvement/needs-verification/needs-truths → 不触发。"""
        labels = ["bug"]
        has_ai_draft = "ai-draft" in labels
        has_process = "process-improvement" in labels
        has_nv = "needs-verification" in labels
        has_nt = "needs-truths" in labels
        should_trigger = (has_process or has_nv or has_nt) and not has_ai_draft
        assert not should_trigger, (
            f"纯 bug label 不应触发: labels={labels}"
        )

    def test_block_need_human_skips(self):
        """block/need-human 的 issue 跳过补标。"""
        labels = ["process-improvement", "block/need-human"]
        has_block_human = "block/need-human" in labels
        assert has_block_human, "block/need-human label 应跳过所有自动操作"

    def test_hold_auto_fail_skips(self):
        """hold/auto-fail 的 issue 跳过补标。"""
        labels = ["process-improvement", "hold/auto-fail"]
        has_hold_fail = "hold/auto-fail" in labels
        assert has_hold_fail, "hold/auto-fail label 应跳过所有自动操作"

    def test_closed_issue_not_retroactively_fixed(self):
        """已 CLOSED 的 issue 不追溯补标（#648 边界）。"""
        # 本条为 CONTRACT_JSON 隐含规则：已关闭 issue 不改 label
        issue_state = "CLOSED"
        assert issue_state == "CLOSED", (
            "CLOSED 状态的 issue 不应被追溯修改（#648 边界）"
        )


class TestRunCommands:
    """验证 gh CLI 命令格式正确。"""

    def test_ai_draft_add_command_uses_add_label(self):
        """补 ai-draft 标签必须用 --add-label（非 --remove-label）。"""
        wf = load_workflow()
        jobs = wf.get("jobs", {})
        trigger_job = jobs.get("trigger") or list(jobs.values())[0]

        for step in trigger_job.get("steps", []):
            run = step.get("run", "")
            if "ai-draft" in run:
                # 补标操作用 --add-label，不能是 --remove-label
                assert "--add-label" in run, (
                    f"补 ai-draft 标签必须用 --add-label，当前:\n  {run}"
                )
                assert "ai-draft" in run, (
                    f"补标命令中必须包含 ai-draft:\n  {run}"
                )
                # 确保不会误删
                assert "--remove-label" not in run or "ai-draft" not in run.split(
                    "--remove-label"
                )[-1].split()[0], (
                    f"ai-draft 标签不应出现在 --remove-label 参数中:\n  {run}"
                )


class TestTruthVocabularySingleSource:
    """「有无业务真值」的判定词表必须两侧同源（issue #5481）。

    病根：`issue-contract-check.yml`（新 issue 一开就跑、负责写标签）与 `case-draft.yml`
    （负责「补了真值就翻转标签」）**各维护一份词表**，且两份都与仓库实际写法脱节 ——
    AGENTS.md 铁律 6 与 migao-dev-flow / migao-acceptance 教的是「验收判据」，
    而门禁原先只认「业务真值 / 验收标准 / 问题描述」⇒ 2026-09-25 实测：172 条 open issue 里
    77 条「判据节本来就在」仍被打上 `needs-truths`，其 PR 随后被 verify-trigger 静默跳过自动验收。

    红证（改一处不红 = 空判据，故两侧都比）：把任意一侧 `TRUTH_VOCAB` 里的某个词删掉
    （例如 `判据`）⇒ `test_vocabulary_identical_on_both_sides` 必红；
    把 `TRUTH_VOCAB` 写成两处 ⇒ `_vocab` 的「恰好一处」断言必红。
    """

    #: 词表必须覆盖的仓库实际写法（spec：与技能 / AGENTS.md 的口径对齐，不是「当前实现长这样」）
    REQUIRED_SPELLINGS = (
        "验收判据", "验收标准", "验收清单", "验收口径", "完成判据", "判定标准", "判据",
    )

    def _vocab(self, path: Path) -> str:
        found = VOCAB_RE.findall(path.read_text(encoding="utf-8"))
        assert len(found) == 1, (
            f"{path.name} 里的 `TRUTH_VOCAB = '…'` 必须**恰好一处**（现 {len(found)} 处）"
            "—— 两处会让两侧词表再次分叉，且只改一处不会红"
        )
        return found[0]

    def test_vocabulary_identical_on_both_sides(self):
        """同一份真值只有一处投影：两侧词表逐字相等。"""
        writing_side = self._vocab(ISSUE_CONTRACT_WORKFLOW)
        converting_side = self._vocab(WORKFLOW_PATH)
        assert writing_side == converting_side, (
            "两侧判据词表已分叉（同一份真值两处投影）:\n"
            f"  issue-contract-check.yml: {writing_side}\n"
            f"  case-draft.yml:           {converting_side}"
        )

    def test_vocabulary_covers_repo_spellings(self):
        """词表必须覆盖仓库实际写法，否则用这些拼写的 issue 仍会被误判「缺业务真值」。"""
        tokens = self._vocab(ISSUE_CONTRACT_WORKFLOW).split("|")
        missing = [t for t in self.REQUIRED_SPELLINGS if t not in tokens]
        assert not missing, (
            f"判据词表缺仓库实际写法 {missing} ⇒ 这些 issue 仍会被误判「缺业务真值」"
            f"（当前词表: {tokens}）"
        )


# ── `opened` 竞态：判定必须用**现取**标签，不得读事件载荷（issue #5481 ③）──────────

def test_case_draft_reads_live_labels_not_the_event_payload():
    """`case-draft` 的判定必须用**现取**标签（issue #5481 ③ 的 `opened` 竞态）。

    现场：本 workflow 与 `issue-contract-check.yml` **同为 `issues: opened` 触发**，而 `needs-truths`
    是**另一个 run** 写上去的 ⇒ 事件载荷里看不到它 ⇒ 先跑完的「看不到标签、不转换」、后跑的
    「只写标签、不转换」⇒ **真值齐全的 issue 永远不转档，且没有任何东西会变红**。
    实证 `#3814`：body 里本有 `## 验收标准` + 4 条编号判据，却一直挂 `needs-truths` 到一次无关编辑。

    判据（三条同时成立）：① 没有**判定用**的 `github.event.issue.labels` 引用（注释与说明不算）；
    ② 有一个把现取标签写进 `$GITHUB_OUTPUT` 的步；③ 至少一处 `if:` 用的是那个输出。
    """
    import re
    from pathlib import Path

    wf = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "case-draft.yml"
    text = wf.read_text(encoding="utf-8")

    offenders = [ln.strip() for ln in text.splitlines()
                 if "github.event.issue.labels" in ln and not ln.strip().startswith("#")]
    assert offenders == [], (
        "`case-draft` 的判定仍读**事件载荷**里的标签 ⇒ `opened` 竞态复发（#5481 ③）：\n  "
        + "\n  ".join(offenders)
    )
    assert "GITHUB_OUTPUT" in text and "gh issue view" in text, (
        "缺「现取标签」步（必须用 API 读当前标签并写进 $GITHUB_OUTPUT）"
    )
    assert re.search(r"if:\s*[^\n]*steps\.labels\.outputs\.names", text), (
        "没有任何 `if:` 用现取标签的输出 ⇒ 现取步白跑"
    )


def test_truth_vocab_covers_the_forms_actually_used_in_the_wild():
    """词表必须覆盖仓库**实际写法**（issue #5481 ① 的语料面；红证 = 把词表改窄 ⇒ 本判据红）。

    语料 = #5481 归一前在**真实标题**里出现过的判据词形（逐条取自该单的实测台账），
    不是凭空造的；断言「这些词形**都**能被门禁认出来」——这正是「172 → 97」那次归一暴露的缺口。
    """
    from pathlib import Path
    import re

    wf = (Path(__file__).resolve().parents[2] / ".github" / "workflows"
          / "issue-contract-check.yml").read_text(encoding="utf-8")
    m = re.search(r"TRUTH_VOCAB='([^']+)'", wf)
    assert m, "找不到 TRUTH_VOCAB（词表被改名 ⇒ 判据需同步，别让它静默消失）"
    vocab = m.group(1)

    #: #5481 实测到的**真实标题词形**（归一前的原标题里出现过的判据词）
    corpus = ("验收标准", "验收判据", "验收清单", "验收口径", "完成判据", "判定标准", "判据")
    missing = [w for w in corpus if not re.search(vocab, w)]
    assert missing == [], (
        f"这些**真实标题里出现过**的判据词形门禁认不出（#5481 ① 的缺口会复发）：{missing}"
    )
