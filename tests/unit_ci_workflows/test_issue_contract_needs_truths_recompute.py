# case_ids: MC-127
"""`needs-truths` 标签的**生命周期**守卫（issue #8406）——「只算一次、永不重算」的陈旧误标。

## 病根（现取读数，非推断）

`.github/workflows/issue-contract-check.yml` 的 `on.issues.types` 只有 `[opened]`，而它判定的对象是
**issue body**（判据节 / `CONTRACT_JSON`）—— body 在创建之后还会变。于是：

- 事后补上判据节的 issue **不会**触发任何 run ⇒ `needs-truths` 一直挂着（2026-11-02 现取：
  51 条 open `needs-truths` 里 **2** 条按本 workflow 自己的判据已经满足：`#5052` / `#5061`）；
- 该标签被当作 backlog 规模读数用 ⇒ 陈旧条目**虚增**读数，且**没有任何东西会因此变红**；
- 现有唯一收敛路径是**人肉摘标签**（2026-11-02 在 #5511 对账时手工摘了那 2 条）。

同族第二处：摘标逻辑原先**嵌在**「刚加了 `needs-verification`」分支里面 ⇒ **两标签并存**的 issue
（补判据前被人工加过 `needs-verification`）永远摘不掉 —— 那正是陈旧形态本身。

## 修法

① `on.issues.types` 加 `edited`（保留 `opened`）；② 判定**双向**：判据满足 ⇒ `needs-verification` 在、
`needs-truths` **不在**；不满足 ⇒ `needs-truths` 在。摘标不再依赖「是否刚加了 needs-verification」；
③ 两个方向都**先比当前标签**（已存在 / 已不存在就不调用）⇒ 无关编辑重算后**零写请求**；
④ 提醒评论只在 `opened` 发一次（`edited` 在任何标题 / 正文编辑上都会触发，重复评论 = 噪音）。

## 判据（本文件，每条都能单独变红）

| # | 判据 | 红证（改回旧实现 ⇒ 必红） |
|---|---|---|
| ① | `on.issues.types` ⊇ {`opened`, `edited`} | 去掉 `edited` ⇒ `test_issue_events_recompute_on_body_edit` 红 |
| ② | 「判据满足 + 标签在」⇒ 发 `removeLabel('needs-truths')` | 删掉 removeLabel 那段 ⇒ `test_satisfied_issue_drops_stale_needs_truths` 红 |
| ③ | 幂等：「判据满足 + 标签已不在」⇒ **零** removeLabel 请求 | 改成无条件 remove ⇒ `test_satisfied_issue_does_not_remove_an_absent_label` 红 |
| ④ | 「判据不满足 + 标签不在」⇒ 补回 `needs-truths`，且 `edited` **不发**评论 | 去掉补标 / 去掉评论闸门 ⇒ 对应用例红 |

## 执行方式（为什么不是纯文本断言）

判据**不**对脚本文本做正则断言：它把 `with.script` 从 YAML 里取出来，**真的跑在 Node 里**，
`github` / `context` 用**内存替身**记录每一次 `addLabels` / `removeLabel` / `createComment`
（同目录先例 = `tests/unit_ci_workflows/test_pr_comment_claiming_marker.py`）。
`node` 不可用 ⇒ `pytest.fail`（不得读成通过）；步骤被改名 / script 被删 ⇒ `_check_script` 硬失败。

## 与 issue #8406「修法 A（单向：只摘不加）」的差异（有意取舍，照实登记）

#8406 的建议是 `edited` 分支**只摘不加**（避免作者顺手删一句判据就把 issue 打回缺真值）；
本包按施工单实现**双向**（不满足 ⇒ 确保 `needs-truths` 在），理由：标签是 body 的**纯函数**才谈得上
「幂等可复算」；且重算路径**不发评论**（只有 `opened` 发），所以「打回」不会产生噪音。
代价 = 作者删掉判据节时标签会回来（`verify-trigger` 会据此跳过该 issue 的 PR 自动验收）—— 这与
「issue 确实没有判据」的事实一致，故接受；要退回单向只需删掉 `test_unsatisfied_edited_body_…`
对应的补标分支（一处）。
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "issue-contract-check.yml"
STEP_NAME = "Check and remind"
NODE_TIMEOUT_SECONDS = 120

#: 判据**满足**的 body（走 workflow 自己的判据节识别；本文件**不抄** `TRUTH_VOCAB`，
#: 单一真值源与两侧同源由 `tests/unit_ci_workflows/test_label_guard.py::TestTruthVocabularySingleSource` 守）
BODY_WITH_TRUTHS = "## 验收标准\n- 补上判据节后 `needs-truths` 必须消失\n"
#: 判据**不满足**的 body（无判据节、无 CONTRACT_JSON、无问题描述列表）
BODY_WITHOUT_TRUTHS = "随手写的描述，既没有判据节，也没有 CONTRACT_JSON。\n"


# ── 读 workflow（`on` 在 PyYAML 1.1 里会被解析成布尔 True，两种键都兜住）──────────

def _on_block(wf: dict) -> dict:
    for key in (True, "on"):
        if key in wf:
            return wf[key] or {}
    return {}


def _issue_types() -> set:
    issues = _on_block(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")) or {}).get("issues") or {}
    types = issues.get("types") or []
    if isinstance(types, str):
        types = [types]
    return {str(t) for t in types}


def _check_script() -> str:
    """取 `Check and remind` 步骤的 `with.script`（判据对象本体；取不到 ⇒ 硬失败，不许空跑）。"""
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")) or {}
    for job in (wf.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            if step.get("name") == STEP_NAME:
                script = (step.get("with") or {}).get("script")
                if script and "hasTruths" in script:
                    return script
    pytest.fail(
        f"{WORKFLOW.name} 里找不到 `{STEP_NAME}` 步骤的 `with.script`（含 hasTruths 判定）——"
        "判据对象不存在 ⇒ 本文件未行使，不得读成通过"
    )


# ── Node 执行器：真的跑那段 github-script，github / context 用内存替身 ────────────

_PRELUDE = """\
const __calls = { added: [], removed: [], comments: [] };
const __labels = JSON.parse(process.env.STUB_LABELS || '[]');
const github = {
  rest: {
    issues: {
      addLabels: async (a) => { __calls.added.push(a.labels); },
      removeLabel: async (a) => { __calls.removed.push(a.name); },
      createComment: async (a) => { __calls.comments.push(a.body); },
    },
  },
};
const context = {
  repo: { owner: 'owner', repo: 'repo' },
  issue: { number: 7 },
  payload: {
    action: process.env.STUB_ACTION || 'opened',
    issue: {
      number: 7,
      title: '[flow] fixture',
      body: process.env.STUB_BODY || '',
      user: { type: 'User' },
      labels: __labels.map((name) => ({ name })),
    },
  },
};
async function __run() {
"""


def _run_script(*, action: str, labels=(), body: str) -> dict:
    """把真脚本跑在 Node 里，返回内存替身收到的调用：`{added, removed, comments}`。"""
    node = shutil.which("node")
    if node is None:
        pytest.fail("node 不可用 ⇒ 本判据未行使（不得读成通过；本仓 CI 与本机均依赖 node）")
    program = (
        _PRELUDE
        + "  const __script = " + json.dumps(_check_script()) + ";\n"
        + "  await (0, eval)('(async () => {' + __script + '\\n})()');\n"
        + "}\n__run().then(() => { console.log('__RESULT__' + JSON.stringify(__calls)); })\n"
        + "  .catch((e) => { console.error((e && e.stack) || String(e)); process.exit(1); });\n"
    )
    proc = subprocess.run(
        [node, "-"],
        input=program,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=NODE_TIMEOUT_SECONDS,
        check=False,
        env={
            # 只喂替身数据，**不**继承外环境（node 自身用绝对路径调用）
            "STUB_ACTION": action,
            "STUB_LABELS": json.dumps(list(labels)),
            "STUB_BODY": body,
        },
    )
    assert proc.returncode == 0, (
        "Node 执行 github-script 片段失败（真跑）⇒ 判据空转，故这里必须红：\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    m = re.search(r"__RESULT__(\{.*\})\s*$", proc.stdout.strip(), re.M | re.S)
    assert m, f"执行器没有回吐调用记录（空跑）：\n{proc.stdout}\n{proc.stderr}"
    return json.loads(m.group(1))


# ══════════════════════════════════════════════════════════════════════════════
# ① 触发面：body 会变，所以 `edited` 必须在
# ══════════════════════════════════════════════════════════════════════════════

def test_issue_events_recompute_on_body_edit():
    """① `on.issues.types` 必须含 `edited`（只有 `opened` ⇒ 标签只算一次、永不重算）。

    红证：把 `types:` 改回 `[opened]` ⇒ 本判据红（并具名报出缺的那个事件）。
    """
    types = _issue_types()
    assert "opened" in types, f"`on.issues.types` 丢了 `opened`（首判面丢失）；现取 {sorted(types)}"
    assert "edited" in types, (
        "`on.issues.types` 缺 `edited` ⇒ 本 workflow 判定的对象是 **issue body**，而 body 在 `opened` "
        "之后仍会变（补上判据节 / 删掉判据节）⇒ `needs-truths` 只算一次、永不重算（issue #8406 的陈旧误标）。"
        f"现取 {sorted(types)}；出口 = 在 .github/workflows/issue-contract-check.yml 的 "
        "`on.issues.types` 里加回 `edited`"
    )


# ══════════════════════════════════════════════════════════════════════════════
# ② 判据满足 ⇒ 摘掉陈旧的 `needs-truths`（含「两标签并存」这个陈旧形态本身）
# ══════════════════════════════════════════════════════════════════════════════

def test_satisfied_issue_drops_stale_needs_truths():
    """② 判据满足 + `needs-truths` 在 ⇒ 必须发 `removeLabel('needs-truths')`。

    红证：删掉 satisfied 分支里的 removeLabel 段（改回只加不摘）⇒ 本判据红。
    """
    calls = _run_script(action="edited", labels=["needs-truths"], body=BODY_WITH_TRUTHS)
    assert calls["removed"] == ["needs-truths"], (
        "判据已满足却没有摘掉 `needs-truths`（= issue #8406 的陈旧误标本身）："
        f"现取 remove 调用 {calls['removed']}"
    )
    assert calls["added"] == [["needs-verification"]], (
        f"判据满足时 `needs-verification` 应当补上；现取 {calls['added']}"
    )


def test_satisfied_issue_drops_stale_label_even_when_needs_verification_present():
    """② 的陈旧形态：**两标签并存**（补判据前被人工加过 `needs-verification`）也必须摘掉。

    修复前 removeLabel 藏在 `if (!labels.includes('needs-verification'))` 里面 ⇒ 这一态永远摘不掉。
    红证：把 removeLabel 挪回那个分支里 ⇒ 本判据红。
    """
    calls = _run_script(
        action="edited", labels=["needs-verification", "needs-truths"], body=BODY_WITH_TRUTHS)
    assert calls["removed"] == ["needs-truths"], (
        "两标签并存时没摘 `needs-truths`（摘标仍嵌在「刚加 needs-verification」分支里）⇒ "
        f"这条 issue 会永久挂着陈旧标签；现取 {calls['removed']}"
    )
    assert calls["added"] == [], f"已有 needs-verification 不应重复添加；现取 {calls['added']}"


# ══════════════════════════════════════════════════════════════════════════════
# ③ 幂等：状态一致 ⇒ 零写请求（无关编辑不产生任何 API 调用）
# ══════════════════════════════════════════════════════════════════════════════

def test_satisfied_issue_does_not_remove_an_absent_label():
    """③ 标签已不在 ⇒ **不得**再发 remove 请求（无条件 remove 会对不存在的标签发 404 写请求）。

    红证：把 removeLabel 改成无条件调用 ⇒ 本判据红。
    """
    calls = _run_script(action="edited", labels=["needs-verification"], body=BODY_WITH_TRUTHS)
    assert calls["removed"] == [], (
        "`needs-truths` 本来就不在，却仍发了 remove 请求 ⇒ 幂等面破了"
        f"（无关编辑每次都产生一条写请求）；现取 {calls['removed']}"
    )
    assert calls["added"] == [], f"状态已一致（已有 needs-verification）却仍写标签；现取 {calls['added']}"


# ══════════════════════════════════════════════════════════════════════════════
# ④ 双向的另一半 + 不刷评论：不满足 ⇒ 补标；`edited` 不重复提醒
# ══════════════════════════════════════════════════════════════════════════════

def test_unsatisfied_edited_body_restores_needs_truths_without_reposting_the_reminder():
    """④ 判据不满足 + 标签不在 ⇒ 补回 `needs-truths`；且 `edited` **不发**提醒评论。

    红证：去掉补标分支 ⇒ 本判据红；去掉评论闸门 ⇒ 本判据红（`comments` 非空）。
    """
    calls = _run_script(action="edited", labels=[], body=BODY_WITHOUT_TRUTHS)
    assert calls["added"] == [["needs-truths"]], (
        f"判据不满足却没有补回 `needs-truths`（双向的另一半丢失）；现取 {calls['added']}"
    )
    assert calls["comments"] == [], (
        "`edited` 在**任何**标题 / 正文编辑上都会触发 ⇒ 该分支不许发提醒评论（否则每次改错别字刷一条）；"
        f"现取 {len(calls['comments'])} 条"
    )
    assert calls["removed"] == [], f"不满足判据时不该有 remove 请求；现取 {calls['removed']}"


def test_unsatisfied_opened_body_reminds_exactly_once_and_is_idempotent():
    """④ 对照：`opened` 恰好发一条提醒；已带标签的重算 ⇒ 零写请求。"""
    opened = _run_script(action="opened", labels=[], body=BODY_WITHOUT_TRUTHS)
    assert len(opened["comments"]) == 1, (
        f"首判（`opened`）必须恰好发一条提醒评论；现取 {len(opened['comments'])} 条"
    )
    assert opened["added"] == [["needs-truths"]], f"现取 {opened['added']}"

    again = _run_script(action="edited", labels=["needs-truths"], body=BODY_WITHOUT_TRUTHS)
    assert again == {"added": [], "removed": [], "comments": []}, (
        "标签状态已正确时的重算必须**零写请求**（幂等）；"
        f"现取 {again}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# ⑤ 政策不变：`ai-draft` 的 issue 在 `edited` 分支上同样零动作
# ══════════════════════════════════════════════════════════════════════════════

def test_ai_draft_issues_are_invisible_to_the_edited_branch():
    """⑤ `ai-draft` ⇒ 质量门禁完全不可见（与既有政策逐字一致；`edited` 不例外）。

    红证：把 ai-draft 跳过段删掉 ⇒ 本判据红（会出现 remove/add 调用）。
    """
    calls = _run_script(
        action="edited", labels=["ai-draft", "needs-truths"], body=BODY_WITH_TRUTHS)
    assert calls == {"added": [], "removed": [], "comments": []}, (
        f"`ai-draft` issue 被动了（政策要求全程零动作）；现取 {calls}"
    )
