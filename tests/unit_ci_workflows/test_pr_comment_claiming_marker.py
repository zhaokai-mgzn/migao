# case_ids: MC-012
# （沿用同目录既有惯例：CI / 流程结构类 L0 不变式统一挂 MC-012 —— 见 `.github/cases/misc.yml`
#   的登记与 `test_growth_gate_pr_comment.py` / `test_merge_gate_job_if.py` 的同款声明。
#   本 PR 不新建用例族：塞进行为用例库会污染覆盖矩阵。**声明只在文件头出现一次**。）
"""PR 机器人报告评论的 **认领依据** 守卫（issue #6423）。

## 病根（#6422 实测，逐字）

`.github/workflows/pr-check.yml` 的 `Post danger-scan comment` step 用**裸子串**认领自己的旧评论：

```js
const prev = comments.find(c => c.body.includes('Danger Scan'));
if (prev) { await github.rest.issues.updateComment({ …, comment_id: prev.id, body }); }
```

`issues.listComments` 默认**按创建序返回（旧 → 新）**，`Array.find` 取**第一个**命中
⇒ **更早**一条正文里含「Danger Scan」这几个字的**人类评论**会被选中并被 bot 报告**整条覆盖**
（作者仍是人类账号 ⇒ 页面上像是用户自己贴的报告）。同族第二处 = 同文件 `Post PR comment`
的 `c.body.includes('QA Growth Gate')`（`qa-growth-gate` job）。**这是销毁人类 durable trail，
不是一次性事故**：此后每次 run 都会再覆盖一次。

## 修法

认领条件换成**唯一 HTML marker**（本仓既有正确写法 = `.github/workflows/pr-issue-link.yml`
的 `<!-- pr-issue-link-check -->`）：`pr-check.yml` 两处认领 `body.includes('<!-- … -->')`，
且**写正文时必须把 marker 一起写进去**（`updateComment` 会整条替换 body ⇒ 漏写就是每轮新建）。

## 判据（本文件）

| 面 | 判据 | 怎么红 |
|---|---|---|
| 实例（真跑 JS） | `TestCommentClaiming::test_*` | 把认领条件换回裸子串并在 Node 里真跑 ⇒ 断言「被更新的是第一条评论（人类那条）」当场红 |
| 类级元守卫 | `test_no_workflow_claims_comments_by_prose_substring` | `.github/workflows/**.yml` 里任何 `body.includes('<散文串>')` 即红；只放行 `<!-- … -->` |
| 写正文必须带 marker | 同上（claim marker ⊆ write 正文） | 摘掉「写正文时补 marker」那行 ⇒ 「marker 没有写进任何正文」红 |

**执行器**：github-script 的片段真的在 **Node** 里跑（stub `github` / `context` / `fs`，
记录 `updateComment` / `createComment` 收到的 `comment_id` 与 `body`）—— 不是对脚本文本做正则断言。
（`node` 不可用 ⇒ `pytest.fail`，不得读成通过；本仓 CI 与本机均依赖 node 跑 playwright。）
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
PR_CHECK = WORKFLOWS_DIR / "pr-check.yml"
PR_ISSUE_LINK = WORKFLOWS_DIR / "pr-issue-link.yml"

# 认领面（job, step）——两处会覆盖人类评论的 bot 报告
CLAIMING_STEPS = [
    ("qa-growth-gate", "Post PR comment"),
    ("danger-scan", "Post danger-scan comment"),
]

MARKER_RE = re.compile(r"<!--.*?-->")
MARKER_VAR_USE_RE = re.compile(r"\.body\.includes\(\s*(\w+)\s*\)")
MARKER_VAR_DEF_RE = re.compile(r"(?:const|let|var)\s+(\w+)\s*=\s*(['\"])<!--.*?-->\2")
MARKER_LITERAL_CLAIM_RE = re.compile(r"\.body\.includes\(\s*(?:'|\")(<!--.*?-->)(?:'|\")\s*\)")
NODE_TIMEOUT_SECONDS = 120

HUMAN_BODY = (
    "落地步骤（人类操作说明）：\n"
    "1. 先看 Danger Scan / QA Growth Gate 的报告；\n"
    "2. 再按 body 里的关联关键词补上 issue 号。\n"
)


# ══════════════════════════════════════════════════════════════════════════════
# ① 纯函数面：从 github-script 片段里解析「认领依据」与「写出的正文」
# ══════════════════════════════════════════════════════════════════════════════

def _strip_js_comments(script):
    """剥掉 JS 注释（判据只读代码面，不吃说明文字 —— 同 `test_growth_gate_pr_comment.py`）。"""
    text = re.sub(r"/\*.*?\*/", "", script, flags=re.S)
    return "\n".join(ln.split("//")[0] for ln in text.splitlines())


def _claim_literals(code):
    """认领依据：`<某>.body.includes(<裸字面量>)` 里的字面量（不含引号）。"""
    return [mt.group(1) for mt in re.finditer(r"\.body\.includes\(\s*'([^'\n]*)'", code)]


def _claim_markers(code):
    """认领条件用的 HTML marker 值（`body.includes('<!-- … -->')` 与 `body.includes(VAR)` 两种形态）。"""
    markers = {mt.group(1) for mt in MARKER_LITERAL_CLAIM_RE.finditer(code)}
    if MARKER_VAR_USE_RE.search(code):
        markers.add(_marker_ref(code)[1])
    return markers


def _marker_reaches_a_write(code, marker):
    """marker 是否**真的被用于组装正文**（按「正文装配点」机械判定，不做数据流分析）。

    `updateComment` 整条替换 body ⇒ 只被认领、从不写进正文的 marker 会让下一轮 run 认不出
    自己的评论（每轮新建一条）。判据落在**装配点**上（marker 字面量 / 其承载变量出现在其中）：
      · 对 `body` 的赋值右值（danger-scan、qa-growth-gate 的 `body = MARKER + '\n' + body;`）；
      · 数组字面量（pr-issue-link 的 `lines = [ … , marker ];`，再由 `lines.join()` 进 body）。
    ⚠️ 判据**不得**落在「定义行」或「认领条件」上：两者天然含该字面量/变量名，拿它们凑数
    会让判据恒真（本 PR 实测踩过两次 —— 判据落点决定它有没有牙）。
    """
    assert _write_blocks(code), "找不到写评论调用（判据对象不完整）"
    carrier = [mt.group(1) for mt in MARKER_VAR_DEF_RE.finditer(code)]
    witnesses = []
    for mt in re.finditer(r"\bbody\s*=\s*", code):
        witnesses.append(code[mt.end():code.find(";", mt.end())])
    for mt in re.finditer(r"\blines?\s*=\s*\[", code):
        depth, i = 0, mt.end() - 1
        while i < len(code):
            if code[i] == "[":
                depth += 1
            elif code[i] == "]":
                depth -= 1
                if depth == 0:
                    witnesses.append(code[mt.end():i])
                    break
            i += 1
    for expr in witnesses:
        if marker in expr:
            return True
        if any(re.search(rf"(?<![\w$]){re.escape(name)}(?![\w$])", expr) for name in carrier):
            return True
    return False


def _write_blocks(code):
    """create/updateComment 调用区间（**括号配平**，含实参对象；带 `start()`/`end()`）。

    ⚠️ 必须从 `(` **之前**开始配平：从第一个 `{` 起算会把「实参对象的 `}`」当成调用结束
    ⇒ 取到的区间只到 `({` 为止（本 PR 实测过的坏形态：窗口里根本没有正文，判据空转）。
    """
    out = []
    for mt in re.finditer(r"issues\.(?:create|update)Comment", code):
        i = code.find("(", mt.end())
        if i < 0:
            continue
        depth = 0
        for j in range(i, len(code)):
            if code[j] == "(":
                depth += 1
            elif code[j] == ")":
                depth -= 1
                if depth == 0:
                    out.append((mt.start(), j + 1))
                    break
    return out


def assert_claiming_markers_are_used(scripts):
    """类级元守卫：认领条件**只许**用 HTML marker（`<!-- … -->`），且 marker 必须写进正文。

    三条判据（每条都能单独变红）：
      (a) 认领条件不得是裸散文串（本 issue 的病灶）；
      (b) 认领了评论就必须有 HTML marker（没有稳定身份的认领必然误伤人类评论）；
      (c) marker 必须**写进正文**（`updateComment` 整条替换 body，漏写 ⇒ 每轮新建一条）。

    `scripts` = `[(显示名, 代码文本)]`。任何一处违反 ⇒ 断言失败，并**具名**报出是哪个 step。
    """
    assert scripts, "扫描面为空 —— 判据对象不存在（不许把空集当通过）"
    problems = []
    for where, code in scripts:
        for lit in _claim_literals(code):
            if not MARKER_RE.fullmatch(lit):
                problems.append(
                    f"{where}：认领条件用了**裸子串** {lit!r} —— 任何早于 bot 评论、"
                    "正文里恰好含这几个字的人类评论都会被选中并被整条覆盖（issue #6423）"
                )
        markers = {mt.group(1) for mt in MARKER_LITERAL_CLAIM_RE.finditer(code)}
        var_claim = MARKER_VAR_USE_RE.search(code)
        if var_claim:
            markers |= _claim_markers(code) - markers
        if not markers:
            problems.append(
                f"{where}：认领了评论却**没有任何 HTML marker** —— 没有稳定身份的认领条件"
                "必然误伤人类评论（issue #6423）"
            )
            continue
        assert _write_blocks(code), f"{where}：认领了评论却没有任何 create/update 调用（判据不完整）"
        for marker in sorted(markers):
            if _marker_reaches_a_write(code, marker):
                continue
            problems.append(
                f"{where}：marker {marker!r} 出现在认领处，却**没有写进任何正文** —— "
                "`updateComment` 整条替换 body ⇒ 下一轮 run 找不到自己的评论，"
                "退化成每轮新建一条（issue #6423）"
            )
    assert not problems, "\n".join(["评论认领面判红："] + [f"  - {p}" for p in problems])


# ══════════════════════════════════════════════════════════════════════════════
# ② Node 执行器：把真的 github-script 片段跑起来（stub github/context/fs）
# ══════════════════════════════════════════════════════════════════════════════

_PRELUDE = """\
const __calls = { updated: [], created: [] };
const __files = JSON.parse(process.env.STUB_FILES || '{}');
const __comments = JSON.parse(process.env.STUB_COMMENTS || '[]');

const github = {
  rest: {
    issues: {
      listComments: async () => ({ data: __comments.map(c => ({ id: c.id, body: c.body })) }),
      updateComment: async (a) => { __calls.updated.push({ comment_id: a.comment_id, body: a.body }); },
      createComment: async (a) => { __calls.created.push({ body: a.body }); },
    },
  },
};
const context = {
  repo: { owner: 'o', repo: 'r' },
  issue: { number: 1 },
  payload: { pull_request: { number: 1, body: '' } },
};
const fs = {
  readFileSync: (p) => {
    if (!(p in __files)) { throw new Error('ENOENT ' + p); }
    return __files[p];
  },
};
const core = { setFailed: (m) => { console.log('core.setFailed: ' + m); } };
const require = (name) => {
  if (name === 'fs') return fs;
  if (name === '@actions/github') return { getOctokit: () => github, context };
  throw new Error('unexpected require: ' + name);
};
async function __run() {
"""


def _run_script(script, comments, files=None, timeout=NODE_TIMEOUT_SECONDS):
    """把一段 github-script 代码**真跑**在 Node 里，返回 `{updated, created}`。

    `eval` 是**故意**的：github-script 的片段按 CommonJS 写（`require('fs')`、自由变量
    `github` / `context`），只能求值在**已注入 stub 的同一作用域**里；`new Function` 会切断
    闭包、模板串插入会在 `${…}` 上报错。片段是**本仓自己的源码**（不是不可信输入）。
    """
    node = shutil.which("node")
    if node is None:
        pytest.fail("node 不可用 ⇒ 认领面判据未行使（不得读成通过）")
    program = (
        _PRELUDE
        + "  const __script = " + json.dumps(_strip_js_comments(script)) + ";\n"
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
        timeout=timeout,
        check=False,
        env={
            # 判据只吃 stub 注入的文件/评论，**不**继承外环境（node 自身用绝对路径调用）
            "STUB_FILES": json.dumps(files or {}, ensure_ascii=False),
            "STUB_COMMENTS": json.dumps(comments, ensure_ascii=False),
        },
    )
    assert proc.returncode == 0, (
        "Node 执行 github-script 片段失败（真跑）⇒ 判据空转，故这里必须红：\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    m = re.search(r"__RESULT__(\{.*\})\s*$", proc.stdout.strip(), re.M | re.S)
    assert m, f"执行器没有回吐调用记录（空跑）：\n{proc.stdout}\n{proc.stderr}"
    return json.loads(m.group(1))


def _workflow(path=PR_CHECK):
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _script(job_id, step_name, path=PR_CHECK):
    steps = ((_workflow(path).get("jobs") or {}).get(job_id) or {}).get("steps") or []
    for step in steps:
        if step.get("name") == step_name:
            script = (step.get("with") or {}).get("script")
            assert script, f"{path.name}:{job_id}:{step_name} 不是 actions/github-script（无 with.script）"
            return script
    raise AssertionError(f"{path.name}:{job_id} 里没有 step {step_name!r}（认领面没了？）")


def _code_of(where):
    job_id, step_name = where.split("::")
    path = PR_ISSUE_LINK if job_id == "issue-link-check" else PR_CHECK
    return _strip_js_comments(_script(job_id, step_name, path))


def _marker_of(where):
    markers = _claim_markers(_code_of(where))
    assert markers, f"{where} 的认领条件里没有 HTML marker（issue #6423）"
    return sorted(markers)[0]


def _all_claiming_scripts():
    return [(f"{job}::{step}", _code_of(f"{job}::{step}")) for job, step in CLAIMING_STEPS]


# 夹具：**更早**一条人类评论（正文含报告标题字样）+ 更晚一条带 marker 的 bot 评论
def _comments(marker, human_body=HUMAN_BODY, prepend=()):
    return list(prepend) + [
        {"id": 1, "body": human_body, "author": "zhaokai-mgzn"},
        {"id": 2, "body": f"{marker}\n## bot 旧报告\n", "author": "github-actions[bot]"},
    ]


DANGER_FILES = {
    "danger-scan-result.json": json.dumps(
        {"blocker_count": 0, "warning_count": 1, "blockers": [], "warnings": ["修改 workflow（测试夹具）"]}),
}
GROWTH_FILES = {"growth-gate-pr-comment.md": "## ✅ QA Growth Gate — PASSED\n\n**Blockers**: 0 | **Warnings**: 0\n"}


def _assert_claimed_not_human(calls, human_id=1):
    assert len(calls["updated"]) == 1, (
        f"必须**恰好**更新一条评论，实得 updated={calls['updated']} / created={calls['created']}"
    )
    assert calls["updated"][0]["comment_id"] != human_id, (
        f"把**人类**评论（id={human_id}）当成自己的报告覆盖了 —— 人类 durable trail 被销毁（issue #6423）"
    )
    assert not calls["created"], f"已有自己的报告却新建了重复评论：{calls['created']}"


# ══════════════════════════════════════════════════════════════════════════════
# ③ 实例判据（真跑 JS）
# ══════════════════════════════════════════════════════════════════════════════

class TestCommentClaiming:
    @pytest.mark.parametrize("where", ["danger-scan::Post danger-scan comment",
                                       "qa-growth-gate::Post PR comment"])
    def test_claims_marked_comment_not_earlier_human_one(self, where):
        """人类评论（含报告标题字样）**更早** ⇒ 被更新的必须是带 marker 的 bot 评论。"""
        job_id = where.split("::")[0]
        files = DANGER_FILES if job_id == "danger-scan" else GROWTH_FILES
        calls = _run_script(_script(*where.split("::")), _comments(_marker_of(where)), files)
        _assert_claimed_not_human(calls)

    @pytest.mark.parametrize("where", ["danger-scan::Post danger-scan comment",
                                       "qa-growth-gate::Post PR comment"])
    def test_write_body_carries_the_marker(self, where):
        """**写正文必须带 marker**：`updateComment` 整条替换 body ⇒ 漏写就是每轮新建一条。

        两条分支都钉：既有 marker 评论被更新（marker 必须仍在）、无 marker 评论（新建，marker 必须在）。
        """
        job_id, _step = where.split("::")
        marker = _marker_of(where)
        files = DANGER_FILES if job_id == "danger-scan" else GROWTH_FILES
        script = _script(job_id, _step)

        existing = _run_script(script, _comments(marker), files)
        assert marker in existing["updated"][0]["body"], (
            f"{where}：更新自己的评论时正文丢了 marker ⇒ 下一轮 run 认不出它（issue #6423）"
        )
        fresh = _run_script(script, [{"id": 9, "body": "无关评论"}], files)
        assert len(fresh["created"]) == 1, f"{where}：没有自己的评论时必须新建一条，实得 {fresh}"
        assert marker in fresh["created"][0]["body"], (
            f"{where}：新建的评论正文缺 marker ⇒ 以后永远认不出自己的评论（issue #6423）"
        )

    @pytest.mark.parametrize("where", ["danger-scan::Post danger-scan comment",
                                       "qa-growth-gate::Post PR comment"])
    def test_human_comment_alone_is_not_claimed(self, where):
        """只有一条含报告字样的**人类**评论（无 marker）⇒ 必须**新建**，绝不动它（兼容旧无 marker 评论）。"""
        job_id, _step = where.split("::")
        files = DANGER_FILES if job_id == "danger-scan" else GROWTH_FILES
        calls = _run_script(_script(job_id, _step), [{"id": 7, "body": HUMAN_BODY}], files)
        assert calls["updated"] == [], f"{where}：认领了没有 marker 的人类评论：{calls['updated']}"
        assert len(calls["created"]) == 1, f"{where}：应新建一条报告，实得 {calls}"


# ══════════════════════════════════════════════════════════════════════════════
# ④ 类级元守卫（本单重点）
# ══════════════════════════════════════════════════════════════════════════════

def test_no_workflow_claims_comments_by_prose_substring():
    """全仓 workflow 的 github-script 评论认领只许用 HTML marker（负控含 pr-issue-link）。"""
    scripts = _all_claiming_scripts()
    scripts.append(("pr-issue-link::Check PR body", _code_of("issue-link-check::Check PR body issue reference")))
    assert_claiming_markers_are_used(scripts)


def test_every_workflow_body_includes_claim_site_is_covered():
    """扫描面自证：全仓 workflow 里所有 `<x>.body.includes(` 都落在上面的判据射程内。"""
    found = [p.name for p in sorted(WORKFLOWS_DIR.glob("*.yml"))
             if re.search(r"\.body\.includes\(", _strip_js_comments(p.read_text(encoding="utf-8")))]
    assert found == ["pr-check.yml", "pr-issue-link.yml"], (
        f"认领 `body.includes(` 的 workflow 集合变了（现取 {found}）—— 新面必须并入本判据（issue #6423）"
    )


def test_negative_pr_issue_link_form_is_not_flagged():
    """负控：`pr-issue-link.yml` 的 `<!-- pr-issue-link-check -->` 形态**不得**被判红。"""
    code = _code_of("issue-link-check::Check PR body issue reference")
    assert "<!-- pr-issue-link-check -->" in code, "pr-issue-link 的 marker 没了（负控对象不存在）"
    assert_claiming_markers_are_used([("pr-issue-link::Check PR body", code)])


# ══════════════════════════════════════════════════════════════════════════════
# ⑤ 红证（每条判据都能**单独**变红；旧实现下必须红 —— issue #6423）
# ══════════════════════════════════════════════════════════════════════════════

def _marker_ref(code):
    """返回 `(认领点变量名, marker 字面量)`；两者都必须恰好一处，否则说明锚点漂移。"""
    uses = MARKER_VAR_USE_RE.findall(code)
    defs = MARKER_VAR_DEF_RE.findall(code)
    assert len(uses) == 1, f"marker 认领点不是恰好一处（实得 {uses}）"
    assert len(defs) == 1, f"marker 定义点不是恰好一处（实得 {defs}）"
    assert uses[0] == defs[0][0], f"认领的变量 {uses[0]!r} 不是 marker 变量 {defs[0][0]!r}"
    return uses[0], MARKER_RE.search(code).group(0)


def _mutate_claim_to_old_prose(where, prose):
    """把**真源码**的 marker 认领点换成旧形态的裸子串认领（注入红证用，锚点唯一性当场自证）。"""
    code = _code_of(where)
    var, _marker = _marker_ref(code)
    mutated = code.replace(f".body.includes({var})", f".body.includes('{prose}')", 1)
    assert mutated != code, f"{where}：注入没生效（锚点漂移）"
    return mutated


def test_red_proof_old_substring_claiming_picks_the_human_comment():
    """红证（旧实现，真跑）：同一夹具下旧认领条件命中**更早的人类**评论 ⇒ 被覆盖的是它（逐字）。"""
    comments = _comments("<!-- danger-scan-report -->")
    mutated = _mutate_claim_to_old_prose("danger-scan::Post danger-scan comment", "Danger Scan")
    calls = _run_script(mutated, comments, DANGER_FILES)
    assert len(calls["updated"]) == 1, f"旧实现应更新一条，实得 {calls}"
    got = calls["updated"][0]
    # ↓ 这就是旧实现的现网形态：人类评论（id=1，正文含「落地步骤 … Danger Scan …」）被整条覆盖
    assert got["comment_id"] == 1, f"旧实现本该覆盖人类那条，实得 {got}"
    assert "落地步骤" in HUMAN_BODY and "## ✅ Danger Scan — PASSED" in got["body"], (
        f"旧实现写出的正文必须与人类原文不同（覆盖发生了）：{got['body']!r}"
    )
    # 新实现下同一夹具不许再选中它
    _assert_claimed_not_human(_run_script(_script("danger-scan", "Post danger-scan comment"),
                                          comments, DANGER_FILES))


def test_red_proof_prose_claim_is_caught_verbatim():
    """注入「认领条件换回裸子串」⇒ 类级元守卫**逐字**报出该处（判别力证明）。"""
    mutated = _mutate_claim_to_old_prose("danger-scan::Post danger-scan comment", "Danger Scan")
    with pytest.raises(AssertionError) as excinfo:
        assert_claiming_markers_are_used([("danger-scan::Post danger-scan comment", mutated)])
    msg = str(excinfo.value)
    assert "Danger Scan" in msg and "#6423" in msg, msg


def test_red_proof_marker_missing_from_body_is_caught():
    """注入「认领用了 marker，却忘了写进正文」⇒ 元守卫必红，且报出 marker 没复现。"""
    # 形态 = marker 只用于**定义 + 认领**，正文装配（`body`）从不带它
    # ⇒ 下一轮 run 读到的评论里没有 marker，必然每轮新建一条。
    code = (
        "const MARKER = '<!-- danger-scan-report -->';\n"
        "const body = '## 报告';\n"
        "const { data: comments } = await github.rest.issues.listComments({});\n"
        "const prev = comments.find(c => c.body.includes(MARKER));\n"
        "if (prev) { await github.rest.issues.updateComment({ comment_id: prev.id, body }); }\n"
        "else { await github.rest.issues.createComment({ body }); }\n"
    )
    with pytest.raises(AssertionError) as excinfo:
        assert_claiming_markers_are_used([("faux.yml::Post", code)])
    assert "没有写进任何正文" in str(excinfo.value), str(excinfo.value)


def test_red_proof_dropping_the_marker_prefix_is_caught():
    """注入真源码：**摘掉「写正文时补 marker」那行** ⇒ 元守卫必红（本单最容易写错的那一处）。"""
    where = "qa-growth-gate::Post PR comment"
    code = _code_of(where)
    prefix_line = "if (!body.includes(MARKER)) body = MARKER + \'\\n\' + body;"
    assert code.count(prefix_line) == 1, f"注入锚点必须唯一命中（实得 {code.count(prefix_line)} 次）"
    mutated = code.replace(prefix_line, "")
    with pytest.raises(AssertionError) as excinfo:
        assert_claiming_markers_are_used([(where, mutated)])
    assert "没有写进任何正文" in str(excinfo.value), str(excinfo.value)


def test_negative_injection_anchor_matches_real_source():
    """锚点自检：红证依赖的注入锚点在真源码里必须存在且唯一（否则红证是空转）。"""
    for job_id, step_name in CLAIMING_STEPS:
        where = f"{job_id}::{step_name}"
        _marker_ref(_code_of(where))   # 认领点/定义点各恰好一处（内部断言即红证锚点自检）
        assert _mutate_claim_to_old_prose(where, "X") != _code_of(where)
