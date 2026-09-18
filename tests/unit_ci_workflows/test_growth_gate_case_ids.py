# case_ids: MC-012
"""growth_gate 用例追溯：只认「声明行」，不认 docstring/正文里的「提及」（issue #4239）。

## 病根（代码级）

`extract_case_ids()` 曾这样扫前 50 行：`CASE_IDS_RE.search(line)` **逐行累积**所有命中
⇒ ① **假红**：docstring 里解释「必须声明 `case_ids:`」这条铁律本身即被当成声明，
`group(1)` 取到 `case_ids:` 之后的**剩余整行文本** ⇒ 垃圾令牌混入 ID 集合 ⇒ 合规 PR 被 block；
② **假绿**：**一个真声明都没有**的文件，只要前 50 行任意位置出现过 `case_ids: OR-001`
字面形态（如注释里贴示例）就被判「已声明」⇒ QA Growth Gate 失效。

## 修复口径（issue #4239 判据 1）

声明 = **注释起始**形态（`^\\s*(#|//|\\*)\\s*case_ids\\s*[:=]`，含 `//` 与 JSDoc 续行 ` * `：
全仓 637 个已声明测试文件的形态由枚举得出，不得误伤）；**取首个命中即停**，不再累积全文。
「必须在前 50 行内」的位置约束**不变**（#3555 的既有裁定，与本缺陷正交）。

## 本文件各断言的红证

- `test_declaration_only_first_hit_wins` / `test_false_positive_*` / `test_false_negative_*` /
  `test_own_file_declares_exactly_mc_012` 在**旧实现**下必红（红输出见 PR 报告）；
- `test_repo_wide_snapshot_no_regression` 与 `test_declaration_syntax_forms` 是**防收窄过头**
  的守门断言：其红证靠**注入收窄缺陷**（正则只留 `#`）取得 —— 不会红的断言等于空断言。

## 快照来源（`_growth_gate_case_ids_snapshot.json`）

**改动实现之前**用旧实现对全仓 `git ls-files` 里的测试文件（`_is_test_file` 过滤）跑一遍落盘：

    python3 -c "import sys,json,subprocess,os; sys.path.insert(0,'.github');
    import growth_gate as g;
    fs=[f for f in subprocess.run(['git','ls-files'],capture_output=True,text=True).stdout.split() if f and g._is_test_file(f) and os.path.exists(f)];
    json.dump({f:v for f,v in ((f,g.extract_case_ids(f)) for f in sorted(fs)) if v},
              open('tests/unit_ci_workflows/_growth_gate_case_ids_snapshot.json','w'),
              ensure_ascii=False, separators=(',',':'), sort_keys=True)"
"""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_PY = REPO_ROOT / ".github" / "growth_gate.py"
SNAPSHOT = Path(__file__).with_name("_growth_gate_case_ids_snapshot.json")

# 允许与改动前快照**不同**的文件：两者都是本缺陷的**活实例**，期望值 = 修复后的确切结果。
# 变化只允许是「收窄」（新 ⊆ 旧）且非空 —— 合法声明绝不允许退化成「未声明」。
_INTENDED_NARROWING = {
    # 第 10 行 docstring 里 `case_ids = AS-003, ...`（无注释标记的示例文本）被旧实现当声明累积。
    "tests/unit_ci_workflows/test_behavior_mapping_tool_coverage.py": ["PR-006", "PR-018"],
    # 曾**两处**声明（docstring 内 + 代码注释），旧实现取并集并留重复项；现合并为单一声明行，
    # ID 集合**一个不少**（DF-008 / AS-007 都保留）。
    "backend/ai-agent-service/tests/test_after_sales_manage.py":
        ["AS-001", "AS-002", "AS-004", "AS-007", "DF-008"],
}

# ── 样本文件（正文拼接构造：本文件自身要被 CI 的 --check-weak 扫描，不得出现字面弱断言）──

_REAL_DECL_PLUS_MENTION = (
    "# case_ids: OR-001, OR-002\n"
    '"""守卫（假红样本）：docstring 解释铁律本身——测试文件头部必须声明 `case_ids:`'
    "（对应 .github/cases/ 用例），否则 QA Growth Gate block。\n"
    '"""\n'
    "def test_sample():\n"
    "    x = 1\n"
)

_MENTION_ONLY = (
    '"""守卫（假绿样本）：本文件**没有**任何真实声明。\n'
    "\n"
    "写法参考：声明形如 `case_ids: [OR-001]`，须落在文件前 50 行内。\n"
    '"""\n'
    "def test_sample():\n"
    "    x = 1\n"
)

_TWO_DECLARATIONS = (
    "# case_ids: OR-001\n"
    "# case_ids: OR-002\n"
    "def test_sample():\n"
    "    x = 1\n"
)


def _gate():
    """从 .github/growth_gate.py 加载被测模块（零依赖，importlib 文件加载）。"""
    spec = importlib.util.spec_from_file_location("growth_gate_case_ids_under_test", GATE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write(tmp_path, text):
    f = tmp_path / "test_sample.py"
    f.write_text(text, encoding="utf-8")
    return f


# ── ① 口径：取首个声明行即停，不累积全文 ──

def test_declaration_only_first_hit_wins(tmp_path):
    """仅第 1 个声明行生效（旧实现：逐行累积 ⇒ 并集 + 重复项）。"""
    ids = _gate().extract_case_ids(str(_write(tmp_path, _TWO_DECLARATIONS)))
    assert ids == ["OR-001"], f"第二个声明行不得生效，实得 {ids}"


# ── ② 红证·假红：docstring 提及不得混入 ID 集合 ──

def test_false_positive_docstring_mention_not_a_declaration(tmp_path):
    """第 1 行是真声明 + docstring 提及 `case_ids:` ⇒ 提取结果**恰为**真声明的那几个 ID。"""
    ids = _gate().extract_case_ids(str(_write(tmp_path, _REAL_DECL_PLUS_MENTION)))
    assert ids == ["OR-001", "OR-002"], f"docstring 提及被当成声明（假红）：{ids}"


# ── ③ 红证·假绿：无真实声明即未声明（哪怕正文提过 ID）──

def test_false_negative_mention_only_is_undeclared(tmp_path):
    """无真实声明 + docstring 提及 `case_ids: [OR-001]` ⇒ 提取结果为空（门禁判它未声明）。"""
    ids = _gate().extract_case_ids(str(_write(tmp_path, _MENTION_ONLY)))
    assert ids == [], f"仅提及的文件被判「已声明」（假绿）：{ids}"


def test_own_file_declares_exactly_mc_012():
    """本文件自身即假红样本：docstring 里解释铁律（含 `case_ids:` 字面形态）不得混入 ID。"""
    ids = _gate().extract_case_ids(__file__)
    assert ids == ["MC-012"], f"本文件的 ID 集合被 docstring 污染：{ids}"


# ── ④ 不误伤：全仓真实声明形态逐一枚举 ──

@pytest.mark.parametrize("line,expected", [
    ("# case_ids: OR-001, OR-002", ["OR-001", "OR-002"]),   # Python / YAML 注释
    ("// case_ids=OR-001", ["OR-001"]),                     # TS/Java 注释
    ("// case_ids=[OR-001, OR-002]", ["OR-001", "OR-002"]),  # 方括号形态
    (" * case_ids: OR-001", ["OR-001"]),                    # JSDoc 块注释续行（全仓 2 处）
    ("   # case_ids: OR-001", ["OR-001"]),                  # 有前导空白
    ('# case_ids: "OR-001"', ["OR-001"]),                   # 引号包裹
])
def test_declaration_syntax_forms(tmp_path, line, expected):
    """六种真实声明形态（由全仓枚举得出）都必须被识别 —— 收窄不得误伤合法声明。"""
    ids = _gate().extract_case_ids(str(_write(tmp_path, line + "\ndef test_sample():\n    x = 1\n")))
    assert ids == expected, f"声明形态被漏掉：{line!r} → {ids}"


# ── ⑤ 不回归（关键）：全仓逐值对比改动前快照 ──

def test_repo_wide_snapshot_no_regression():
    """全仓测试文件的提取结果与**改动前**快照逐值相同（防「收窄过头把合法声明也漏掉」）。

    快照 = 旧实现对 712 个测试文件的提取结果（生成命令见模块 docstring）。
    只允许 `_INTENDED_NARROWING` 里的文件变化，且必须是**收窄且非空**：有声明绝不允许
    退化成未声明（那正是本断言要拦的形态）。新增/删除的文件不在快照里，天然不影响本断言。
    """
    gate = _gate()
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert len(snapshot) > 500, f"快照可疑（仅 {len(snapshot)} 个文件）"
    changed, unchanged, gone = [], 0, []
    for rel, before in sorted(snapshot.items()):
        path = REPO_ROOT / rel
        if not path.exists():
            gone.append(rel)
            continue
        after = gate.extract_case_ids(str(path))
        if after == before:
            unchanged += 1
        else:
            changed.append((rel, before, after))

    unregistered = [rel for rel, _, _ in changed if rel not in _INTENDED_NARROWING]
    assert unregistered == [], f"未登记的提取结果变化（回归）：{unregistered}"
    assert len(changed) == len(_INTENDED_NARROWING), (
        f"预期 {len(_INTENDED_NARROWING)} 个收窄，实得 {len(changed)}：{[c[0] for c in changed]}")
    for rel, before, after in changed:
        assert after == _INTENDED_NARROWING[rel], f"{rel}: 期望 {_INTENDED_NARROWING[rel]}，实得 {after}"
        assert after, f"{rel}: 合法声明被漏掉（收窄过头）"
        assert set(after) <= set(before), f"{rel}: 收窄不得新增 ID：{set(after) - set(before)}"
    assert unchanged >= 600, f"逐值相同的文件数异常偏低（{unchanged}），疑似大范围误伤"
    assert len(gone) < 50, f"快照里大量文件已不存在（{len(gone)}），快照需重生成"


# ── ⑥ 门禁级端到端：真声明 → pass；仅提及 → 判「未声明」 ──

def test_gate_end_to_end_declared_passes_mention_only_blocked(tmp_path, monkeypatch):
    """直接调 growth_gate.case_trace_check：合法声明的测试文件通过，仅提及的被判未声明。"""
    repo = tmp_path / "repo"
    (repo / "cases").mkdir(parents=True)
    (repo / "cases" / "demo.yml").write_text(
        "cases:\n  - id: OR-001\n    tier: normal\n  - id: OR-002\n    tier: normal\n",
        encoding="utf-8")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    (repo / "tests").mkdir()
    declared = repo / "tests" / "test_declared.py"
    declared.write_text(_REAL_DECL_PLUS_MENTION, encoding="utf-8")
    mention_only = repo / "tests" / "test_mention_only.py"
    mention_only.write_text(_MENTION_ONLY, encoding="utf-8")

    def git(*argv):
        subprocess.run(["git", *argv], cwd=repo, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "gate@example.com")
    git("config", "user.name", "gate")
    git("add", "cases", "seed.txt")
    git("commit", "-q", "-m", "base")
    git("add", "tests")
    git("commit", "-q", "-m", "add tests")

    monkeypatch.chdir(repo)  # get_added_files() 用 cwd 跑 git diff
    blocks, _warns, report = _gate().case_trace_check(
        {}, ["tests/test_declared.py", "tests/test_mention_only.py"],
        str(repo), str(repo / "cases"), "HEAD~1")

    passed = [r for r in report if r.get("level") == "pass"]
    assert [r["case_ids"] for r in passed] == [["OR-001", "OR-002"]], report
    assert passed[0]["file"] == str(declared), report
    blocked = {b["file"]: b["reason"] for b in blocks}
    assert str(mention_only) in blocked, f"仅提及的文件必须被判未声明：{blocks}"
    assert "未声明 case_ids" in blocked[str(mention_only)], blocked
