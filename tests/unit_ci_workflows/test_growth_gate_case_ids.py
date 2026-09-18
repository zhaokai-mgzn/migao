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
- `test_declaration_syntax_forms` / `test_wide_declaration_forms_*` /
  `test_no_ids_beyond_declared_lines` 是**防收窄过头 / 防凭空多出 ID** 的守门断言：
  其红证靠**注入缺陷**（正则退回只认 `#`）取得 —— 不会红的断言等于空断言。

## 全仓守门为什么**不用快照**（返工记录，CI run 35317165332）

首版用「改动前对全仓文件集的提取结果」落成 `_growth_gate_case_ids_snapshot.json` 做基准，
**必然腐烂**：基准按**可变键**（某时刻的文件集 + 每行 ID 的值）定位被测对象 ——
main 每新增/修改一条 `case_ids` 声明就误报（实证：`ProcessingOrderServiceTest.java` 的声明行
被 #4263 加上 `PG-022/PG-023` ⇒ merge commit 上「值与快照不同」⇒ 判成"未登记的回归"）。
这正是 `migao-dev-flow` §18「读的是快照，按可变键定位被测对象」与 §19.1「基于错误真相模型
写出的护栏 = 永远红」。现改为**运行期自算、与文件集/ID 值增减无关**的不变式：
逐行拿「宽口径声明形态全集」去要求新实现，反向再要求"不得多出声明行之外的 ID"。
"""
import importlib.util
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_PY = REPO_ROOT / ".github" / "growth_gate.py"

# 宽口径 = 「合法声明形态全集」（由全仓枚举得出，与被测正则**各自独立**）：
# `# case_ids:` / `// case_ids=` / `// case_ids=[...]` / JSDoc 块注释续行 ` * case_ids:`。
_WIDE_LINE_RE = re.compile(r"^\s*(?:#|//|\*)\s*case_ids\s*[:=]")
_WIDE_MARKERS = ("#", "//", "*")

# 已登记的**豁免**（impl 与宽口径参考的已知差异）：键 = 文件，值 = (期望 ID, 为什么那处不是合法声明)。
# 当前**为空**：两条候选实例在**新判据**下都不需要豁免 ——
#   · `test_behavior_mapping_tool_coverage.py` 的 docstring 示例行（`    case_ids = AS-003, …`）
#     **不是**宽口径声明行（无注释标记）⇒ 参考实现也不认它；
#   · `test_after_sales_manage.py` 的两处声明已合并为单行 ⇒ 首行即真声明。
# §19.1「存量基线只许缩短」：要新增豁免必须**同时下调** `_NARROWING_CEILING`，
# 使「放宽判据」成为一次显式、可评审的动作（而不是悄悄加一行让它变绿）。
_NARROWING: dict = {}
_NARROWING_CEILING = 0

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


# ── ⑤ 全仓不变式（运行期自算，与文件集 / ID 值增减无关）──

def _wide_line_ids(line):
    """从**宽口径声明行**取 ID —— **独立实现**（字符串切分，不复用被测正则）。"""
    s = line.lstrip()
    marker = next((m for m in _WIDE_MARKERS if s.startswith(m)), None)
    if marker is None:
        return None
    rest = s[len(marker):].lstrip()
    if not rest.startswith("case_ids"):
        return None
    rest = rest[len("case_ids"):].lstrip()
    if rest[:1] not in (":", "="):
        return None
    rest = rest[1:].lstrip().split("]")[0].lstrip()
    if rest.startswith("["):
        rest = rest[1:]
    return [t for t in (x.strip().strip("'\"") for x in rest.split(",")) if t]


def _declaration_lines(path):
    """文件**前 50 行**里的宽口径声明行 → [(行号, 行文本)]（`_WIDE_LINE_RE` 独立于被测正则）。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    return [(no, line) for no, line in enumerate(text.split("\n")[:50], 1) if _WIDE_LINE_RE.match(line)]


def _repo_test_files(gate):
    """全仓测试文件（判定复用单一事实源 `growth_gate._is_test_file`）。"""
    out = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True).stdout
    return [f for f in out.split("\n") if f and gate._is_test_file(f) and (REPO_ROOT / f).exists()]


def test_wide_declaration_forms_all_recognized_and_never_lost(tmp_path):
    """全仓每个**宽口径声明行**新实现都必须认，且含声明行的文件不得提取为空。

    运行期自算 ⇒ 与「某时刻的文件集 / 每行 ID 的具体值」无关（不再按可变键做基准）。
    """
    gate = _gate()
    files = _repo_test_files(gate)
    assert len(files) > 400, f"扫描集异常（{len(files)} 个测试文件）—— 判据空跑"
    assert len(_NARROWING) <= _NARROWING_CEILING, (
        f"豁免从 {_NARROWING_CEILING} 涨到 {len(_NARROWING)} —— §19.1 基线只许缩短，"
        "新增豁免必须同时下调 _NARROWING_CEILING")

    lines, declared = {}, []
    for rel in sorted(files):
        found = _declaration_lines(REPO_ROOT / rel)
        if found:
            declared.append(rel)
        for no, line in found:
            lines.setdefault(line, f"{rel}:{no}")
    assert len(declared) > 400, f"宽口径只找到 {len(declared)} 个已声明文件 —— 判据空跑"
    assert len(lines) > 100, f"宽口径只收集到 {len(lines)} 种声明行 —— 判据空跑"

    missed = []
    for i, (line, origin) in enumerate(sorted(lines.items(), key=lambda kv: kv[1])):
        probe = tmp_path / f"probe_{i}.py"
        probe.write_text(line + "\ndef test_probe():\n    x = 1\n", encoding="utf-8")
        actual, expected = gate.extract_case_ids(str(probe)), _wide_line_ids(line)
        if actual != expected:
            missed.append(f"{origin}  {line.strip()[:48]!r} → 期望 {expected}，实得 {actual}")
    assert missed == [], (
        f"宽口径声明行被漏掉（收窄过头）：{len(missed)}/{len(lines)} 种\n" + "\n".join(missed[:10]))

    lost = [rel for rel in declared if not gate.extract_case_ids(str(REPO_ROOT / rel))]
    assert lost == [], f"含声明行却提取为空（有声明 → 未声明）：{lost[:10]}"


def test_no_ids_beyond_declared_lines():
    """反向（假绿方向）：提取结果不得出现**任何声明行之外**的 ID。

    旧实现用全局 `search` 累积 ⇒ docstring 里的示例文本被当声明（实证
    `test_behavior_mapping_tool_coverage.py` 凭空多出 7 个 ID）。
    """
    gate = _gate()
    files = _repo_test_files(gate)
    assert len(files) > 400, f"扫描集异常（{len(files)} 个测试文件）—— 判据空跑"

    extra = []
    for rel in sorted(files):
        if rel in _NARROWING:
            continue
        allowed = set()
        for _no, line in _declaration_lines(REPO_ROOT / rel):
            allowed |= set(_wide_line_ids(line))
        extra += [f"{rel} → {cid}" for cid in gate.extract_case_ids(str(REPO_ROOT / rel))
                  if cid not in allowed]
    assert extra == [], "提取到声明行之外的 ID（提及被当成声明）：\n" + "\n".join(extra[:10])


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
