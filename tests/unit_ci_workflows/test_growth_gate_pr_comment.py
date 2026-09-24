# case_ids: MC-012
# （沿用同目录既有惯例：CI / 流程结构类 L0 不变式统一挂 MC-012 —— 见 `.github/cases/misc.yml`
#   的登记与 `test_merge_gate_job_if.py` / `test_growth_gate_fail_closed.py` 的同款声明。
#   本 PR 不新建用例族：塞进行为用例库会污染覆盖矩阵。**声明只在文件头出现一次**。）
"""QA Growth Gate 的 **PR 评论渲染**守卫（issue #5292）。

## 病根（实测 PR #5285，逐字）

`Post PR comment` step 读的是**它自己那一步**的 `$GITHUB_STEP_SUMMARY`（GitHub 的该变量是
**逐步**文件、每步一个 uuid），而 markdown 是 `check` step 里由 `growth_gate.py` 写进**那一步**
的 summary ⇒ 评论 step 读到空串 ⇒ 正文只剩标题 +「**Blockers**: 6」+「或在
`.github/qa-exemptions.yml` 中添加合法豁免项」：**看不见是哪 6 条，却被引向加豁免**
（本仓口径：豁免面只许缩短）。数据一直都在 `--json-file` 里，丢的只是「渲染进评论」这一步。

## 固化声明（owner 裁定「成果都要固化，不要出现定期优化」）

跑在哪：本文件在 `tests/unit_ci_workflows/**` ⇒ CI job = **`ci workflow helper unit tests`**
（required，**每个 PR 都跑**，`python -m pytest tests/unit_ci_workflows -q`）。

| 判据 | 常驻用例（文件名::测试名省略本文件前缀） | 注入点 → 失败形态（逐字，见各 `test_red_proof_*` 的断言消息） |
|---|---|---|
| 1 逐条列全 | `test_every_blocker_listed_with_its_missing_tests`、`test_g5_reason_blockers_are_actionable_too` | 渲染退回「只输出计数」→ `评论里列了 0 条，blocker_count=3：清单=[] 与 JSON blockers=[...] 不一致（判红清单必须逐条可见，issue #5292）` |
| 2 同源（禁第二数据源） | `test_renderer_takes_only_the_result_object`（签名 + 函数体 AST）、`test_renderer_ignores_other_data_sources`（诱饵结果文件 + 污染 step summary）、`test_cli_render_is_the_same_render_path`、`TestWorkflowWiring::test_render_step_shares_the_same_result_file_as_json_output` | 渲染函数里加一次 `open("growth-gate-result.json")` → `渲染函数不得自己读文件（第二数据源）` |
| 3 真跑必违规输入 | `test_real_violating_change_appears_verbatim_in_comment` | 条目行渲染成空 → `评论里没有出现必然违规的文件名 backend/.../issue5292_probe.py` |
| 4 零 blocker 不加噪音 | `test_zero_blockers_keeps_current_pass_shape` | 把诱导句搬回 `blocker_count == 0` 分支 → `0 blocker 时不得出现诱导加豁免的字样` |
| M1 元判据（类级） | `test_no_workflow_builds_its_own_growth_gate_comment` | 注入「在发布评论的 step 里按 `blocker_count` 自建正文」→ `在发布评论的 step 里自建正文（出现 ['blocker_count']）= 第二数据源` |
| M2 元判据（类级，参数化） | `test_meta_every_blocked_comment_is_attributable`（覆盖 6 种分支载荷） | 同判据 1 |
| 措辞面（诱导） | `TestWorkflowWiring::test_no_inducing_exemption_sentence_in_the_job`、`assert_no_exemption_pitch_without_list` | 计数 6 / 清单空时仍给豁免建议 → `评论没列全清单（0/6）却给了加豁免建议 —— 诱导扩豁免` |

**未固化（照实登记）**：`warnings` 清单仍**不逐条列出**（本单只治 blocker 判红不可归因）——
`blocker_count == 0 && warning_count > 0` 时评论形态与修前一致（只给「请尽快补充测试」）。
没有机械判据拦「warnings 不可见」，靠本条登记 + issue #5292 的边界段。
"""
import ast
import importlib.util
import inspect
import json
import re
import textwrap
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_PY = REPO_ROOT / ".github" / "growth_gate.py"
PR_CHECK = REPO_ROOT / ".github" / "workflows" / "pr-check.yml"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
TECH_STACK = REPO_ROOT / ".github" / "tech-stack.yml"
EXEMPTIONS = REPO_ROOT / ".github" / "qa-exemptions.yml"

GATE_JOB = "qa-growth-gate"
CHECK_STEP = "Check test coverage in diff (data-driven)"
RENDER_STEP = "Render PR comment from growth-gate-result.json"
POST_STEP = "Post PR comment"

# 必然违规的输入：新增工具文件 + **没有**同名单测（tech-stack.yml 的 `app/tools/(.+)\.py` 规则）
PROBE_TOOL = "backend/ai-agent-service/app/tools/issue5292_probe.py"
PROBE_TEST = "tests/test_tools_issue5292_probe.py"

# ── 注入锚点（红证专用）：对**真源码文本**做单点变异，避开「判据被自己的文案喂绿」──
MUT_COUNT_ONLY = (
    "        blocks += [_blocker_entry(i, bl) for i, bl in enumerate(blockers, 1)]",
    "        blocks += []  # 注入：只输出计数（= issue #5292 的现网形态）",
)
MUT_ENTRY_EMPTY = (
    """    return f"{index}. `{blocker.get('file', '?')}` — {action}（模块：{blocker.get('module') or '—'}）\"""",
    '    return ""  # 注入：条目行渲染成空（= 评论那一块留白）',
)
MUT_SECOND_SOURCE = (
    """    mismatch = result_mismatch(payload)
    if mismatch:
        return (_RESULT_UNUSABLE_PREFIX""",
    """    payload = json.loads(open("growth-gate-result.json", encoding="utf-8").read())
    mismatch = result_mismatch(payload)
    if mismatch:
        return (_RESULT_UNUSABLE_PREFIX""",
)
MUT_PITCH_IN_PASS_BRANCH = (
    '        detail = ["> ✅ 所有检查通过！"]',
    '        detail = ["> ❌ **合并被阻塞**。请补充缺失的测试，或在 `.github/qa-exemptions.yml` '
    '中添加合法豁免项后重新请求 Review。"]',
)
MUT_NO_MISMATCH_GUARD = (
    "    if b != n_b:",
    "    if False:  # 注入：拆掉「计数 vs 清单」自相矛盾的守卫",
)
# workflow 侧注入：发布评论的 step 自建正文（第二数据源）
MUT_WORKFLOW_SECOND_SOURCE = (
    "body = fs.readFileSync('growth-gate-pr-comment.md', 'utf8');",
    "body = '**Blockers**: ' + String(blocker_count);",
)


@pytest.fixture(autouse=True)
def _no_step_summary(monkeypatch):
    """跑门禁前清掉 `$GITHUB_STEP_SUMMARY`。

    pytest 在 CI 里本身就跑在一个 step 内 ⇒ 该变量指向那个 step 的真 summary 文件；
    本文件的判据之一是「渲染**不**依赖它」，留着它会让「同源」判据失去意义（还会污染 CI 的 summary）。
    """
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)


def _load_gate():
    """从 `.github/growth_gate.py` 加载被测模块（零依赖，importlib 文件加载）。"""
    spec = importlib.util.spec_from_file_location("growth_gate_pr_comment_under_test", GATE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_mutated(tmp_path, *replacements):
    """把真源码**单点变异**后加载（红证用）：每条判据必须能**单独**变红。"""
    text = GATE_PY.read_text(encoding="utf-8")
    for old, new in replacements:
        hits = text.count(old)
        assert hits == 1, f"注入锚点必须唯一命中：{old!r}（实得 {hits} 次）—— 锚点漂移了"
        text = text.replace(old, new)
    path = tmp_path / f"growth_gate_mutated_{abs(hash(text)) % 10 ** 6}.py"
    path.write_text(text, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 判据本体（纯函数：绿色用例与红证**共用同一份断言**，红证才有判别力）──

def _listed_files(body):
    """机械解析评论正文的**条目行**（`<序号>. ` 起始），取第一个反引号里的路径（顺序敏感）。"""
    return [ln.split("`")[1] for ln in re.findall(r"^\d+\. .+$", body, re.M)]


def _entry_line(body, index):
    m = re.search(rf"^{index}\. .*$", body, re.M)
    assert m, f"评论里没有第 {index} 条条目行（判红不可归因）"
    return m.group(0)


def assert_lists_every_blocker(body, payload):
    """判据 1 / M2（元判据）：能判红 ⇒ 每条 blocker 的 `file` 都必须在正文里，
    顺序与 JSON `blockers` 一致，条目数 == `blocker_count`。"""
    n = int(payload.get("blocker_count") or 0)
    listed = _listed_files(body)
    files = [bl.get("file") for bl in (payload.get("blockers") or [])]
    assert listed == files, (
        f"评论里列了 {len(listed)} 条，blocker_count={n}：清单={listed!r} 与 JSON blockers={files!r} "
        "不一致（判红清单必须逐条可见，issue #5292）"
    )
    assert len(listed) == n, f"评论里列了 {len(listed)} 条，blocker_count={n}"


def assert_each_entry_actionable(body, payload):
    """判据 1 的**可操作性**面：每条至少含 `file` + 缺测清单（`required_tests`）/ G5 的 `reason`。"""
    for i, bl in enumerate(payload.get("blockers") or [], 1):
        line = _entry_line(body, i)
        assert bl.get("file") in line, f"第 {i} 条没列出 file：{line!r}"
        req = [t for t in (bl.get("required_tests") or []) if t]
        if req:
            missing = [t for t in req if t not in line]
            assert not missing, f"第 {i} 条缺测清单没列全：缺 {missing!r}（{line!r}）"
        elif bl.get("reason"):
            assert bl["reason"] in line, f"第 {i} 条没给出可操作说明：{line!r}"
        else:
            assert "未给出清单" in line, (
                f"第 {i} 条既无 required_tests 也无 reason，必须显式说明而不是留白：{line!r}"
            )


def assert_no_exemption_pitch_without_list(body, payload):
    """元判据（诱导面，issue #5292 判据 5）：**看不见清单时不得提豁免**；
    提了就必须写明本仓口径「豁免面只许缩短」。"""
    if "qa-exemptions" not in body:
        return
    n = int(payload.get("blocker_count") or 0)
    listed = _listed_files(body)
    detail = (f"评论没列全清单（{len(listed)}/{n}）却给了加豁免建议" if n > 0
              else "评论在没有任何阻塞项时仍给出加豁免建议")
    assert n > 0 and len(listed) == n, f"{detail} —— 诱导扩豁免（issue #5292）"
    assert "只许缩短" in body, "提豁免时必须写明本仓口径：豁免面只许缩短"


def assert_fail_closed_on_mismatch(body):
    """元判据（同族）：计数与清单自相矛盾 ⇒ 必须显式挡下，且不得提豁免。"""
    assert "结果文件不可用" in body, f"结果对象自相矛盾时必须显式挡下，实得正文：{body!r}"
    assert "qa-exemptions" not in body, "结论不可归因时不得给加豁免建议"


def assert_pass_shape(body):
    """判据 4：`blocker_count == 0` 维持既有形态（✅ 全部通过），不加噪音、不提豁免。"""
    assert body.startswith("## ✅ QA Growth Gate — PASSED"), f"0 blocker 的结论行变了：{body[:60]!r}"
    assert "**Blockers**: 0 | **Warnings**: 0" in body, "0 blocker 的计数行变了"
    assert "所有检查通过" in body, "0 blocker 的结论文案变了"
    assert _listed_files(body) == [], f"0 blocker 时不得加清单噪音：{_listed_files(body)!r}"
    assert "qa-exemptions" not in body, "0 blocker 时不得出现诱导加豁免的字样"
    assert "合并被阻塞" not in body, "0 blocker 时不得出现阻塞字样"


def assert_renderer_takes_only_the_payload(gate):
    """判据 2 的结构面：签名只有一个位置参数 + 函数体（**剥掉 docstring**）不得读文件/环境变量。

    剥 docstring 是必须的（#5118 ③）：该函数的说明文字里就写着「不读 `$GITHUB_STEP_SUMMARY`」
    ⇒ 不剥的话判据会被自己的文案喂绿。
    """
    params = list(inspect.signature(gate.render_pr_comment).parameters)
    assert params == ["payload"], f"渲染函数只许接受那份结果对象，实得参数 {params}"
    node = _function_ast(gate.render_pr_comment)
    open_calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Name) and n.func.id == "open"]
    assert not open_calls, "渲染函数不得自己读文件（第二数据源）"
    attrs = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
    assert not ({"environ", "getenv"} & attrs), f"渲染函数不得读环境变量（第二数据源）：{attrs}"
    names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
    assert "GITHUB_STEP_SUMMARY" not in names, "渲染函数不得碰逐步 summary（本 issue 的病根）"


def _function_ast(fn):
    node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    body = node.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        node.body = body[1:]          # 只读**代码面**
    return node


def assert_violation_visible(body, payload):
    """判据 3：必然违规的改动，其文件名必须**逐字**出现在评论里。"""
    assert PROBE_TOOL in body, f"评论里没有出现必然违规的文件名 {PROBE_TOOL}"
    assert PROBE_TEST in body, f"评论里没有给出该文件缺的测试 {PROBE_TEST}"
    assert_lists_every_blocker(body, payload)


# ── 数据夹具（含 PR #5285 的真实形态）──

PR5285_TOOLS = ["briefing_query", "order_lookup", "inventory_check",
                "customer_profile", "after_sales_status", "logistics_trace"]


def _blocker(file, tests=(), reason=None, module="ai-agent-service"):
    item = {"file": file, "kind": "block", "module": module}
    if tests:
        item["required_tests"] = list(tests)
    if reason:
        item["reason"] = reason
    return item


def _payload(blockers, warnings=()):
    blockers, warnings = list(blockers), list(warnings)
    return {"blocker_count": len(blockers), "warning_count": len(warnings),
            "blockers": blockers, "warnings": warnings, "results": []}


def _pr5285_payload(count=6):
    return _payload([
        _blocker(f"backend/ai-agent-service/app/tools/{name}.py",
                 tests=[f"tests/test_tools_{name}.py", f"tests/test_{name}.py"])
        for name in PR5285_TOOLS[:count]
    ])


@pytest.fixture
def stub_repo(tmp_path):
    """最小仓库：**真** tech-stack.yml 规则 + 一个没有同名单测的新工具文件（必然违规）。"""
    root = tmp_path / "repo"
    (root / "backend/ai-agent-service/app/tools").mkdir(parents=True)
    (root / PROBE_TOOL).write_text("def handler():\n    return 1\n", encoding="utf-8")
    return root


def _run_gate_real(gate, stub_repo, tmp_path):
    """真跑 `growth_gate.py` 的 main()（同一脚本、同一 `--json-file`），返回写出的结果对象。"""
    out = tmp_path / "growth-gate-result.json"
    rc = gate.main(["--files", PROBE_TOOL, "--tech-stack", str(TECH_STACK),
                    "--exemptions", str(EXEMPTIONS), "--json", "--json-file", str(out),
                    "--repo-root", str(stub_repo)])
    assert rc == 0, "违规文件由 JSON 判定，门禁脚本本身不该非零"
    return json.loads(out.read_text(encoding="utf-8"))


# ── ① 判据 1：逐条列全 + 每条可操作 ──────────────────────────────────────────

def test_every_blocker_listed_with_its_missing_tests():
    gate = _load_gate()
    payload = _pr5285_payload()
    body = gate.render_pr_comment(payload)
    assert_lists_every_blocker(body, payload)
    assert_each_entry_actionable(body, payload)
    assert "6 处缺测" in body, "条数标题必须与实际条数一致"


def test_g5_reason_blockers_are_actionable_too():
    """G5（用例追溯）类 blocker 没有 `required_tests`，只有 `reason` —— 同样必须逐条给出。"""
    gate = _load_gate()
    payload = _payload([_blocker("tests/unit_ci_workflows/test_x.py", module="Case Contract",
                                 reason="新增测试未声明 case_ids（头部加 # case_ids: <用例ID>）")])
    body = gate.render_pr_comment(payload)
    assert_lists_every_blocker(body, payload)
    assert_each_entry_actionable(body, payload)


# ── ② 判据 2：与 `--json-file` 同源（禁第二数据源）────────────────────────────

def test_renderer_takes_only_the_result_object():
    assert_renderer_takes_only_the_payload(_load_gate())


def test_renderer_ignores_other_data_sources(tmp_path, monkeypatch):
    """诱饵探针：工作区摆一份**不同**的结果文件 + 污染 step summary ⇒ 正文仍只反映传入的对象。"""
    gate = _load_gate()
    decoy = _payload([_blocker("backend/decoy/other.py", tests=["tests/test_other.py"])])
    monkeypatch.chdir(tmp_path)
    (tmp_path / "growth-gate-result.json").write_text(json.dumps(decoy), encoding="utf-8")
    summary = tmp_path / "step_summary.md"
    summary.write_text("| 伪造的 step summary |\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    payload = _payload([_blocker("backend/real/target.py", tests=["tests/test_target.py"])])
    body = gate.render_pr_comment(payload)
    assert_lists_every_blocker(body, payload)
    assert "decoy" not in body, "正文吃到了工作区里的**另一份**结果文件（第二数据源）"
    assert "伪造的 step summary" not in body, "正文吃到了 step summary（本 issue 的病根）"


def test_cli_render_is_the_same_render_path(tmp_path, capsys):
    """`--render-pr-comment <json>` 的 stdout 必须 == 对那份 JSON 对象渲染的结果（同一份数据）。"""
    gate = _load_gate()
    payload = _pr5285_payload(3)
    out = tmp_path / "growth-gate-result.json"
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    rc = gate.main(["--render-pr-comment", str(out)])
    printed = capsys.readouterr().out
    assert rc == 0, "结果文件正常时渲染必须退 0"
    assert printed.rstrip("\n") == gate.render_pr_comment(payload).rstrip("\n"), (
        "CLI 渲染与 JSON 对象渲染不是同一条路"
    )
    assert_lists_every_blocker(printed, payload)


def test_unreadable_result_file_fails_closed(tmp_path, capsys):
    """结果文件缺失 ⇒ 打印**可发布**的「结果文件不可用」正文 + ::error:: + 非零（绝不发空评论）。"""
    gate = _load_gate()
    rc = gate.main(["--render-pr-comment", str(tmp_path / "nope.json")])
    captured = capsys.readouterr()
    assert rc != 0, "结果文件读不到必须非零（fail-closed）"
    assert "::error::" in captured.err, "必须输出明确错误"
    assert captured.out.strip(), "必须打印可发布的正文（空正文 = 本 issue 的现网形态）"
    assert_fail_closed_on_mismatch(captured.out)


def test_mismatched_result_file_fails_closed(tmp_path, capsys):
    """计数说有 6 处、清单却 0 条（= #5292 的现网形态本身）⇒ 显式挡下，不得渲染成「看起来正常」。"""
    gate = _load_gate()
    out = tmp_path / "growth-gate-result.json"
    out.write_text(json.dumps({"blocker_count": 6, "warning_count": 0,
                              "blockers": [], "warnings": [], "results": []}),
                   encoding="utf-8")
    rc = gate.main(["--render-pr-comment", str(out)])
    captured = capsys.readouterr()
    assert rc != 0, "自相矛盾的结果对象必须非零"
    assert "::error::" in captured.err
    assert_fail_closed_on_mismatch(captured.out)


# ── ③ 判据 3：真跑一次门禁（必然违规输入）⇒ 评论含该文件名 ────────────────────

def test_real_violating_change_appears_verbatim_in_comment(stub_repo, tmp_path):
    gate = _load_gate()
    payload = _run_gate_real(gate, stub_repo, tmp_path)
    assert payload["blocker_count"] >= 1, f"夹具应当必然违规，实得 {payload['blocker_count']} 处"
    assert PROBE_TOOL in [b.get("file") for b in payload["blockers"]], (
        f"门禁没把新增工具文件判成缺测：{[b.get('file') for b in payload['blockers']]}"
    )
    assert_violation_visible(gate.render_pr_comment(payload), payload)


# ── ④ 判据 4：`blocker_count == 0` 维持现状（不加噪音）───────────────────────

def test_zero_blockers_keeps_current_pass_shape():
    assert_pass_shape(_load_gate().render_pr_comment(
        {"blocker_count": 0, "warning_count": 0, "blockers": [], "warnings": [], "results": []}))


def test_zero_blockers_with_warnings_keeps_current_warning_shape():
    """`blocker_count == 0 && warning_count > 0`：仍是既有 ⚠️ 形态（本单不把 warnings 变成清单）。"""
    gate = _load_gate()
    body = gate.render_pr_comment({"blocker_count": 0, "warning_count": 2, "blockers": [],
                                   "warnings": [{"file": "a.py"}, {"file": "b.py"}], "results": []})
    assert body.startswith("## ⚠️ QA Growth Gate — WARNINGS"), body[:60]
    assert "**Blockers**: 0 | **Warnings**: 2" in body
    assert _listed_files(body) == [], "本单不含 warnings 逐条渲染（见模块 docstring 的未固化登记）"
    assert "qa-exemptions" not in body, "warnings 分支不得出现加豁免建议"


# ── M2 元判据（类级）：**任何**判红渲染都必须逐条可归因 + 不诱导扩豁免 ─────────

META_CASES = {
    "single-classify-blocker": _payload([_blocker("backend/x/tools/one.py", tests=["tests/test_tools_one.py"])]),
    "pr5285-six-tools": _pr5285_payload(),
    "twenty-five-blockers": _payload([_blocker(f"backend/x/tools/t{i}.py", tests=[f"tests/test_tools_t{i}.py"])
                                      for i in range(25)]),
    "blocked-with-warnings": _payload([_blocker("backend/x/tools/one.py", tests=["tests/test_tools_one.py"])],
                                      warnings=[{"file": "backend/y/other.py", "kind": "warn"}]),
    "g5-reason-only": _payload([_blocker("tests/unit_ci_workflows/test_x.py", module="Case Contract",
                                         reason="新增测试未声明 case_ids")]),
    "blocker-without-any-action": _payload([_blocker("backend/x/tools/one.py")]),
}


@pytest.mark.parametrize("payload", META_CASES.values(), ids=list(META_CASES))
def test_meta_every_blocked_comment_is_attributable(payload):
    """元判据：**只要能判红**，评论正文就必须逐条可归因（+ 每条可操作 + 不诱导扩豁免）。

    这是「防别人再犯」的那条：新增渲染分支 / 新增失败种类时，本参数化会立刻覆盖到。
    """
    gate = _load_gate()
    body = gate.render_pr_comment(payload)
    assert_lists_every_blocker(body, payload)
    assert_each_entry_actionable(body, payload)
    assert_no_exemption_pitch_without_list(body, payload)


def test_meta_mismatched_result_cannot_be_rendered_as_blocked_or_passed():
    """元判据（同族）：计数与清单不一致时**两条路都不许静默**（不可归因 / 假绿）。"""
    gate = _load_gate()
    for b, listed in ((6, 0), (0, 3)):
        payload = {"blocker_count": b, "warning_count": 0,
                   "blockers": [{"file": f"f{i}.py", "kind": "block"} for i in range(listed)],
                   "warnings": [], "results": []}
        body = gate.render_pr_comment(payload)
        assert_fail_closed_on_mismatch(body)


# ── M1 元判据（类级）：全仓「消费结果文件」的 job 只许走同一条渲染路 ──────────

def _shared_strip_comment():
    """**共享**剥注释实现（`.github/danger_scan.py::strip_comment`，issue #5268 的纯函数）。

    为什么不用本地 `ln.split("#")[0]`：那是**朴素截断** —— 字符串里的 `#`（如 `echo "#x"`）
    会把该行后半截一起吃掉 ⇒ 判据漏读代码，属**假绿**（`#5323` 第 7 类；判据 =
    `tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py`）。
    也**不能**先把引号内容清空再剥 `#`：本判据要读的正是引号里的 `--render-pr-comment`
    与文件名 ⇒ 清空字符串等于把判据弄空。
    ⇒ 用那份**引号感知**的实现（`#` 在行首/前接空白才算注释起点；引号内的 `#` 不是注释）。
    """
    import importlib.util
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "migao_danger_scan_for_tests", root / ".github" / "danger_scan.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.strip_comment


def _code_only(text, js):
    """剥掉注释后的代码面（#5118 ③：判据只读代码，不吃说明文字）。"""
    if js:
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        return "\n".join(ln.split("//")[0] for ln in text.splitlines())
    strip_comment = _shared_strip_comment()
    return "\n".join(strip_comment(ln) for ln in text.splitlines())


def assert_no_second_render_path(workflows):
    """元判据 M1：**任何**消费 `growth-gate-result.json` 的 job，其发布 PR 评论的 step 必须读
    `--render-pr-comment` 产出的正文；不得在 JS/bash 里按计数自建正文（第二数据源）。"""
    assert workflows, "没有任何 workflow 消费 growth-gate-result.json（判据对象不存在？）"
    for path, text in workflows:
        doc = yaml.safe_load(text) or {}
        consumers = {jid: job for jid, job in (doc.get("jobs") or {}).items()
                     if "growth-gate-result.json" in json.dumps(job, ensure_ascii=False)}
        assert consumers, f"{path.name} 提到结果文件，却没有任何 job 消费它"
        for jid, job in consumers.items():
            steps = job.get("steps") or []
            renders = [s for s in steps if "--render-pr-comment" in (s.get("run") or "")]
            assert renders, f"{path.name}:{jid} 消费结果文件却没有渲染步（评论无处取正文）"
            for step in steps:
                js = (step.get("with") or {}).get("script")
                code = _code_only(js if js else (step.get("run") or ""), js=bool(js))
                if not re.search(r"issues\.(create|update)Comment|gh pr comment", code):
                    continue
                leftovers = [w for w in ("blocker_count", "blockers") if w in code]
                assert not leftovers, (
                    f"{path.name}:{jid}:{step.get('name')} 在发布评论的 step 里自建正文"
                    f"（出现 {leftovers}）= 第二数据源（issue #5292）"
                )


def test_no_workflow_builds_its_own_growth_gate_comment():
    """M1 判绿：当前全仓只有 qa-growth-gate 消费结果文件，且它只走 `--render-pr-comment`。"""
    workflows = [(p, p.read_text(encoding="utf-8")) for p in sorted(WORKFLOWS_DIR.glob("*.yml"))
                 if "growth-gate-result.json" in p.read_text(encoding="utf-8")]
    assert_no_second_render_path(workflows)
    assert [p.name for p, _ in workflows] == ["pr-check.yml"], (
        "消费结果文件的 workflow 集合变了 —— 请确认新消费方也走同一条渲染路"
    )


# ── workflow 接线（评论渲染链：同一份数据 / 不读逐步 summary / 不为空）────────

def _gate_job():
    doc = yaml.safe_load(PR_CHECK.read_text(encoding="utf-8")) or {}
    return (doc.get("jobs") or {})[GATE_JOB]


def _step(name):
    for step in _gate_job().get("steps") or []:
        if step.get("name") == name:
            return step
    raise AssertionError(f"{GATE_JOB} job 里没有 step {name!r}（评论渲染链断了）")


class TestWorkflowWiring:
    def test_render_step_shares_the_same_result_file_as_json_output(self):
        check = _step(CHECK_STEP)["run"]
        render = _step(RENDER_STEP)["run"]
        written = set(re.findall(r"--json-file\s+(\S+)", check))
        rendered = set(re.findall(r"--render-pr-comment\s+(\S+)", render))
        assert len(written) == 1 and len(rendered) == 1, "结果文件参数必须各恰好一处"
        assert written == rendered, f"渲染读的不是写出的那份：{rendered} vs {written}"
        assert _step(RENDER_STEP).get("if") == "always()", "判红/前面步骤失败时也要渲染出正文"

    def test_poster_reads_the_rendered_body_and_never_a_second_source(self):
        script = (_step(POST_STEP).get("with") or {})["script"]
        code = _code_only(script, js=True)
        assert "GITHUB_STEP_SUMMARY" not in code, "评论 step 又去读逐步 summary 了（#5292 的病根）"
        assert "blocker_count" not in code and "blockers" not in code, (
            "评论 step 自建正文 = 第二数据源"
        )
        render_out = set(re.findall(r">\s*([\w.\-]+\.md)", _step(RENDER_STEP)["run"]))
        assert len(render_out) == 1, f"渲染步的正文文件名必须恰好一个：{render_out}"
        assert render_out.pop() in code, "发布步读的不是渲染步产出的那份正文"
        assert re.search(r"if \(!\w+\.trim\(\)\)\s*\{", code), (
            "缺少「正文为空 ⇒ 改用说明文案」的守卫 ⇒ 空评论会重现"
        )

    def test_blocker_and_warning_outputs_come_from_the_json(self):
        """单一来源：`$GITHUB_OUTPUT` 的 BLOCKERS/WARNINGS 只能从结果 JSON 读；
        修前的「空变更集旁路直接 echo BLOCKERS=0」= 双源（issue #5292 的同款病根）。"""
        check = _step(CHECK_STEP)["run"]
        # 只看**行首赋值**（`echo "BLOCKERS=$BLOCKERS"` 那种透传不算数据来源）
        assigns = re.findall(r"^\s*BLOCKERS=(.*)$", check, re.M) \
            + re.findall(r"^\s*WARNINGS=(.*)$", check, re.M)
        assert assigns, "check step 不再写 BLOCKERS/WARNINGS 输出了？"
        for value in assigns:
            assert "growth-gate-result.json" in value, f"输出不是从结果文件读的：{value!r}"

    def test_no_inducing_exemption_sentence_in_the_job(self):
        """措辞面：诱导句「或在 … 中添加合法豁免项」不得留在 qa-growth-gate job 里。"""
        job_text = json.dumps(_gate_job(), ensure_ascii=False)
        assert "添加合法豁免项" not in job_text, "空清单 + 加豁免建议 = 诱导扩豁免（#5292）"
        assert "只许缩短" in job_text, "提豁免时必须写明本仓口径「豁免面只许缩短」"


# ── 注入式红证：每条判据都能**单独**变红（共用上面的断言函数）──────────────

def test_red_proof_count_only_rendering(tmp_path):
    """注入「只输出计数」（= 修前现网形态）⇒ 判据 1 / M2 **必红**。"""
    gate = _load_mutated(tmp_path, MUT_COUNT_ONLY)
    payload = _pr5285_payload(3)
    body = gate.render_pr_comment(payload)
    with pytest.raises(AssertionError) as excinfo:
        assert_lists_every_blocker(body, payload)
    assert "评论里列了 0 条" in str(excinfo.value), str(excinfo.value)


def test_red_proof_empty_rendering_hides_the_violation(tmp_path, stub_repo):
    """注入「条目行渲染成空」⇒ 判据 3（真跑）**必红**。"""
    gate = _load_mutated(tmp_path, MUT_ENTRY_EMPTY)
    payload = _run_gate_real(gate, stub_repo, tmp_path)
    with pytest.raises(AssertionError) as excinfo:
        assert_violation_visible(gate.render_pr_comment(payload), payload)
    assert PROBE_TOOL in str(excinfo.value), str(excinfo.value)


def test_red_proof_second_data_source_is_caught(tmp_path):
    """注入「渲染函数自己读结果文件」⇒ 判据 2 的结构面**必红**。"""
    gate = _load_mutated(tmp_path, MUT_SECOND_SOURCE)
    with pytest.raises(AssertionError) as excinfo:
        assert_renderer_takes_only_the_payload(gate)
    assert "第二数据源" in str(excinfo.value), str(excinfo.value)


def test_red_proof_pitch_without_list_is_caught(tmp_path):
    """注入「0 blocker 也照发加豁免建议」⇒ 判据 4 + 元判据（诱导面）**必红**。"""
    gate = _load_mutated(tmp_path, MUT_PITCH_IN_PASS_BRANCH)
    payload = {"blocker_count": 0, "warning_count": 0, "blockers": [], "warnings": [], "results": []}
    body = gate.render_pr_comment(payload)
    with pytest.raises(AssertionError):
        assert_pass_shape(body)
    with pytest.raises(AssertionError) as excinfo:
        assert_no_exemption_pitch_without_list(body, payload)
    assert "诱导扩豁免" in str(excinfo.value), str(excinfo.value)


def test_red_proof_missing_mismatch_guard_is_caught(tmp_path):
    """注入「拆掉计数 vs 清单的守卫」⇒ 元判据（自相矛盾）**必红**。"""
    gate = _load_mutated(tmp_path, MUT_NO_MISMATCH_GUARD)
    payload = {"blocker_count": 6, "warning_count": 0, "blockers": [], "warnings": [], "results": []}
    body = gate.render_pr_comment(payload)
    with pytest.raises(AssertionError):
        assert_fail_closed_on_mismatch(body)
    with pytest.raises(AssertionError) as excinfo:
        assert_no_exemption_pitch_without_list(body, payload)
    assert "诱导扩豁免" in str(excinfo.value), str(excinfo.value)


def test_red_proof_workflow_second_render_path_is_caught():
    """注入「发布评论的 step 自建正文」⇒ M1 元判据**必红**。"""
    text = PR_CHECK.read_text(encoding="utf-8")
    old, new = MUT_WORKFLOW_SECOND_SOURCE
    assert text.count(old) == 1, f"workflow 注入锚点必须唯一命中（实得 {text.count(old)} 次）"
    with pytest.raises(AssertionError) as excinfo:
        assert_no_second_render_path([(PR_CHECK, text.replace(old, new))])
    assert "第二数据源" in str(excinfo.value), str(excinfo.value)


def test_red_proof_mutation_anchors_still_hit():
    """锚点自检：所有注入锚点在当前源码里必须**恰好命中一次**（否则红证是空转）。"""
    gate_text = GATE_PY.read_text(encoding="utf-8")
    wf_text = PR_CHECK.read_text(encoding="utf-8")
    for label, (old, _new), text in (
        ("count-only", MUT_COUNT_ONLY, gate_text),
        ("entry-empty", MUT_ENTRY_EMPTY, gate_text),
        ("second-source", MUT_SECOND_SOURCE, gate_text),
        ("pitch-in-pass-branch", MUT_PITCH_IN_PASS_BRANCH, gate_text),
        ("no-mismatch-guard", MUT_NO_MISMATCH_GUARD, gate_text),
        ("workflow-second-source", MUT_WORKFLOW_SECOND_SOURCE, wf_text),
    ):
        assert text.count(old) == 1, f"注入锚点 {label} 命中 {text.count(old)} 次（应为 1）"