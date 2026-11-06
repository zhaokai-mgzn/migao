# case_ids: MC-320
"""`base_skill.py` 切片（issue #8725 最后一档）的**结构元守卫**：未登记即红。

## 为什么要有这个文件

切片最常见的失败形态**不是崩**，而是「**判据自己选择沉默**」（§19.1 形状判据）：
代码搬走了、行为判据还绿着，而某个 patch 接缝 / 再导出 / 模块头**静默失效** ——
没有任何东西会红。故本文件把「切片后的形状」逐条钉成判据，且每条都 fail-closed
（扫不到目标就报错，**不给「扫不到就通过」留口子**）。

## 七条（每条都能单独变红；负例见 `TestDiscriminatingPower`）

| # | 判据 | 变红的形态 |
|---|---|---|
| 1 | 切片面文件集合 == 登记表 | 新增一个未登记的 `app/graph/skills/*.py` 单元 ⇒ 红并打印文件名 |
| 2 | 每个符号在**登记的单元里恰好定义 1 次** | 符号丢失 / 被复制到两个单元 ⇒ 红并打印符号名 |
| 3 | `base_skill.py` **一处都不许再定义**它们 | 「搬完又抄回来一份」⇒ 红并打印符号名 |
| 4 | re-export 列表 == 登记全集且来源正确 | 删一条 re-export ⇒ 红（**外部 import 与 patch 会静默失效，这是唯一能提前发现的地方**） |
| 5 | 单元不得反向 `import base_skill`（模块顶层）+ 不得依赖 tests/scripts | 加载期成环 ⇒ 红 |
| 6 | 模块头必须声明单一职责 + 文件 **< 800 行** | 单元长过 800 行（要进 `loc_ratchet_exemptions`）⇒ 红 |
| 7 | 🔴 **patch 接缝不得被同族内部调用绕过** | 某符号既被 `patch("app.graph.skills.base_skill.X")` 打桩、又被**同一个单元里**的成员直接调用 ⇒ patch 静默失效 ⇒ 红 |

## 判据 7 的来历（本档唯一一次真实踩中）

`_order_capability_available` 与 `_tool_registered_globally` 同属 `capability_denial`。搬走后
把桩打回 base_skill 上**不报错**，只是不再影响那个同族内部调用 ⇒ `test_capability_needs_state_when_tool_not_local` 的第三条断言
变成**恒真的空断言**（它当时仍然"通过"了两条）。本判据把这类接缝**机械提取**出来钉死：
要么 patch 目标搬到新住址（同批改，并**同批断言 `mock.called`**），要么调用期经 `_base` 取。
"""
import ast
import re
from pathlib import Path

import pytest

SERVICE = Path(__file__).resolve().parents[1]
SKILLS = SERVICE / "app" / "graph" / "skills"
BASE_SKILL_PY = SKILLS / "base_skill.py"
TESTS_DIR = SERVICE / "tests"

#: 切片单元登记表（`单元文件名` → `它必须定义的符号全集`）。**未登记的新单元 ⇒ 判据 1 红。**
UNITS = {
    "capability_denial.py": [
        "_ORDER_ACTION_WORDS", "_ORDER_UNABLE_RE", "ORDER_WRITE_TOOL", "_INABILITY_STEMS",
        "_ABILITY_WORDS", "_PERMISSION_NEGATIONS", "_SCOPE_HANDOFF_MARKERS",
        "_SELF_SCOPE_COMPOUNDS", "CAPABILITY_DENIAL_PATTERNS", "_AGENT_SELF_WORDS",
        "_NON_SELF_SUBJECT_WORDS", "_CLAUSE_SPLIT_RE", "_PRODUCT_IMAGE_ACTION_WORDS",
        "_PRODUCT_IMAGE_CAPABILITY_NEGATION_RE", "_PRODUCT_IMAGE_UNABLE_RE",
        "_normalize_clause", "_negation_positions", "_self_scoped_clause",
        "_clause_is_self_line", "_scope_misattribution_hit", "_product_image_denial_hit",
        "capability_denial_text_hit", "_STALL_CORRECTIVE", "_TEXT_DENIAL_CORRECTIVE_MIDORDER",
        "_TEXT_DENIAL_CORRECTIVE", "_TEXT_DENIAL_CORRECTIVE_BIZ",
        "_TEXT_DENIAL_CORRECTIVE_PRODUCT_IMAGE", "_stall_has_progress", "_registry_has_tool",
        "_LOGISTICS_CHAIN_CORRECTIVE", "_logistics_chain_incomplete",
        "_logistics_chain_corrective", "_order_write_tool_here", "_tool_registered_globally",
        "_order_capability_available", "PRODUCT_IMAGE_WRITE_TOOL",
        "_product_image_capability_available", "_registry_has_confirm_write_tool",
        "_handoff_guard_applies", "_capability_denial_reason",
    ],
    "order_flow_guard.py": [
        "_has_inflight_interactive_card", "_ORDER_INTENT_HINTS", "_has_ordering_intent",
        "_ORDER_WITHDRAWAL_ANCHORS", "_ORDER_WITHDRAWAL_NEGATIONS", "_ORDER_WITHDRAWAL_WINDOW",
        "_is_ordering_withdrawal", "_release_order_lock_on_withdrawal",
        "_flow_owner_skill", "_relock_order_skill", "_route_cross_skill_target",
        "_load_session_facts", "_order_flow_started", "_flow_state_in_progress",
        "_order_flow_in_progress",
    ],
    "phone_masking.py": [
        "KNOWN_RAW_PHONES_KEY", "KNOWN_ADDRESS_KEY", "_MASK_PLACEHOLDER_CHARS",
        "_MASK_FILLER_CHARS", "_PHONE_IN_TEXT_RE", "_phone_in_text_re", "raw_phones_in",
        "mask_variants", "_is_mask_shaped", "_phone_args", "_remember_known_value",
        "_known_raw_phones", "_remember_raw_phones", "_should_code_close_loop",
        "_is_customer_role", "_norm_ws",
    ],
    "injection_blocks.py": [
        "WRITE_INPUT_ERROR_KEY", "_INPUT_PARAM_LABELS", "user_supplied_param",
        "RECOGNIZABLE_INPUT_PARAMS", "_accepted_param_names", "_clear_write_input_error",
        "CARD_EMIT_COUNTS_KEY", "CARD_EMIT_LIMIT", "card_fingerprint",
        "_PREFILL_FIDELITY_FIELDS", "_QUANTITY_FRAME_WORDS", "_QUANTITY_INTENT",
        "_QUANTITY_PLAIN", "_DIMENSION_SEMANTIC", "_stated_purchase_quantities",
        "_quantity_choice_block", "_form_prefill_fidelity_block", "_masked_phone_write_block",
        "_masked_phone_block_result", "_write_input_recovery_block", "_card_loop_block",
        "_inject_write_input_recovery",
    ],
}

#: **本档之前就存在**的 `base_skill` 再导出子模块（不是本档切出来的单元，故不登记符号）。
#: 现取：`base_skill.py` 里那一行 `from app.graph.skills.tool_selection import (...)`（#8174 的收窄面）。
PRE_EXISTING_REEXPORT_MODULES = {"tool_selection.py"}

UNIT_MAX_LINES = 800


# ── 读源（fail-closed：目标不存在就报错，绝不静默跳过）────────────────────────
def _read(path: Path) -> str:
    assert path.is_file(), f"结构守卫的被扫目标不存在：{path}（fail-closed，不静默跳过）"
    return path.read_text(encoding="utf-8")


def _module_body_names(path: Path) -> set:
    """模块**定义**的顶层名字（函数 / 类 / 赋值目标）。"""
    names = set()
    for node in ast.parse(_read(path), filename=str(path)).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _module_imports(path: Path) -> list:
    """模块顶层 import 语句的 AST 节点。"""
    return [n for n in ast.parse(_read(path), filename=str(path)).body
            if isinstance(n, (ast.Import, ast.ImportFrom))]


def _reexports(base_py: Path = BASE_SKILL_PY) -> dict:
    """`base_skill.py` 从切片单元再导出的 `{符号: 单元模块名}`。"""
    out = {}
    for node in _module_imports(base_py):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        unit = node.module.rsplit(".", 1)[-1]
        if f"{unit}.py" not in UNITS:
            continue
        for alias in node.names:
            out[alias.asname or alias.name] = unit
    return out


# ── 判据 1~6 ────────────────────────────────────────────────────────────────
class TestStructure:
    def test_no_unregistered_unit_on_the_slice_face(self):
        """判据 1：`base_skill.py` 从哪个 `app/graph/skills/*` 子模块 import，那个子模块就必须登记。

        为什么用「被谁 import」当切片面（而不是扫目录）：`app/graph/skills/` 下还有 20 多个
        **与切片无关**的业务 skill 模块 —— 扫目录会逼着维护一张随时间腐烂的白名单。
        真正的风险面是「**base_skill 多引了一个未登记的子模块**」（再导出面 / patch 面被悄悄改了）。
        """
        imported = set()
        for node in _module_imports(BASE_SKILL_PY):
            if isinstance(node, ast.ImportFrom) and node.module \
                    and node.module.startswith("app.graph.skills."):
                imported.add(node.module.rsplit(".", 1)[-1] + ".py")
        unregistered = sorted(imported - set(UNITS) - PRE_EXISTING_REEXPORT_MODULES)
        assert unregistered == [], (
            f"base_skill.py 从这些**未登记**的 skills 子模块 import：{unregistered}"
            f" —— 新单元必须登记进 UNITS（含符号全集），否则「搬完又长回来」无人看见")
        missing = sorted(u for u in UNITS if not (SKILLS / u).is_file())
        assert missing == [], f"登记的切片单元文件不存在：{missing}"

    @pytest.mark.parametrize("unit", sorted(UNITS))
    def test_each_symbol_is_defined_exactly_once_in_its_unit(self, unit):
        """判据 2：登记的每个符号都必须在**该单元里**定义，且只定义一次。"""
        src = _read(SKILLS / unit)
        tree = ast.parse(src, filename=str(unit))
        counts = {}
        for node in tree.body:
            for name in _module_body_names_of(node):
                counts[name] = counts.get(name, 0) + 1
        missing = [s for s in UNITS[unit] if counts.get(s, 0) == 0]
        assert missing == [], f"{unit} 丢了这些登记符号：{missing}"
        dup = [s for s in UNITS[unit] if counts.get(s, 0) > 1]
        assert dup == [], f"{unit} 里这些符号被定义了不止一次：{dup}"

    def test_base_skill_no_longer_defines_any_moved_symbol(self):
        """判据 3：搬走的符号**一处都不许**再定义在 base_skill.py 里（防「搬完又抄回来」）。"""
        moved = {s for syms in UNITS.values() for s in syms}
        still = sorted(_module_body_names(BASE_SKILL_PY) & moved)
        assert still == [], (
            f"base_skill.py 仍在定义这些已搬走的符号：{still} —— 「搬完又抄回来一份」"
            f"会让两份实现静默漂移")

    def test_reexport_list_equals_the_registered_set(self):
        """判据 4：再导出列表 == 登记全集，且**来源单元正确**。

        为什么这条最要紧：删掉一条再导出，`from app.graph.skills.base_skill import X` 与
        `patch("app.graph.skills.base_skill.X")` 都会**静默失效**（patch 打在不存在的属性上
        **不报错**），这是唯一能提前发现的地方。
        """
        got = _reexports()
        want = {s: u[:-3] for u, syms in UNITS.items() for s in syms}
        assert set(got) == set(want), (
            f"再导出集合与登记集不一致：多了 {sorted(set(got) - set(want))} / "
            f"少了 {sorted(set(want) - set(got))}")
        wrong = {s: (got[s], want[s]) for s in want if got[s] != want[s]}
        assert wrong == {}, f"这些符号的再导出**来源单元**不对：{wrong}"

    @pytest.mark.parametrize("unit", sorted(UNITS))
    def test_unit_never_imports_base_skill_at_module_level(self, unit):
        """判据 5：单元不得在**模块顶层** import base_skill（加载期成环）+ 不得依赖 tests/scripts。

        允许**函数体内** import（= 调用期取，`execution/*.py` 的既成写法）。
        """
        for node in _module_imports(SKILLS / unit):
            mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                    else [node.module or ""])
            for m in mods:
                assert not m.startswith("app.graph.skills.base_skill"), (
                    f"{unit} 在模块顶层 import 了 base_skill（{m}）—— 加载期成环："
                    f"base_skill → 本单元 → base_skill（后者只加载到一半）")
                assert not m.startswith(("tests", "scripts")), (
                    f"{unit} 依赖了 {m} —— 实现代码不得依赖 tests/scripts")

    @pytest.mark.parametrize("unit", sorted(UNITS))
    def test_unit_declares_single_responsibility_and_stays_under_800_lines(self, unit):
        """判据 6：模块头必须写清单一职责 + 文件 < 800 行（否则要进 `loc_ratchet_exemptions`）。"""
        src = _read(SKILLS / unit)
        assert src.startswith('"""'), f"{unit} 缺模块 docstring（单一职责要写在头里）"
        doc = src.split('"""')[1]
        assert "单一职责" in doc, f"{unit} 的模块头没有声明「单一职责」"
        assert "依赖方向" in doc, f"{unit} 的模块头没有声明「依赖方向」"
        lines = len(src.splitlines())
        assert lines < UNIT_MAX_LINES, (
            f"{unit} 已 {lines} 行（上限 {UNIT_MAX_LINES - 1}）—— 该再切一刀，"
            f"而不是往 loc_ratchet_exemptions 里塞新条目")

    @pytest.mark.parametrize("unit", sorted(UNITS))
    def test_unit_docstring_documents_the_patch_seam(self, unit):
        """判据 6b：**用了** `logger` 接缝的单元必须把口径写进模块头（否则会被「顺手整理」掉）。"""
        src = _read(SKILLS / unit)
        if "_base.logger" not in src:
            pytest.skip(f"{unit} 不使用 logger 接缝（零 loguru 依赖）")
        doc = src.split('"""')[1]
        assert "patch" in doc and "logger" in doc, (
            f"{unit} 的模块头没有写明 patch 缝口径 —— 下一个人会把它「整理」成模块顶层 import，"
            f"patch 随即静默失效")


def _module_body_names_of(node) -> list:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


# ── 判据 7：patch 接缝（机械提取，自动跟随将来新增的 patch 点）─────────────────
_PATCH_DOTTED_RE = re.compile(
    r"patch(?:\.object)?\(\s*[\"']app\.graph\.skills\.base_skill\.([A-Za-z_]\w*)[\"']")
_PATCH_OBJECT_RE = re.compile(
    r"patch\.object\(\s*base_skill\s*,\s*[\"']([A-Za-z_]\w*)[\"']")


def patched_at_base_skill(tests_dir: Path = TESTS_DIR) -> set:
    """全仓测试源码里打到 `app.graph.skills.base_skill.<X>` 的符号集合。"""
    out = set()
    for path in sorted(tests_dir.rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        out |= set(_PATCH_DOTTED_RE.findall(src))
        out |= set(_PATCH_OBJECT_RE.findall(src))
    return out


def _loads(node) -> set:
    return {n.id for n in ast.walk(node)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def seam_violations(units: dict, tests_dir: Path = TESTS_DIR, skills_dir: Path = SKILLS) -> set:
    """「被 patch 打桩、又被**同一个单元里**的成员直接调用」的符号清单（空 = 通过）。

    抽成纯函数是为了能喂**负例夹具**（证明它真的会红，而不是永远绿的空判据）。
    """
    patched = patched_at_base_skill(tests_dir)
    moved = {s for syms in units.values() for s in syms}
    out = set()
    for unit, syms in units.items():
        path = skills_dir / unit
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=unit)
        for node in tree.body:
            name = _module_body_names_of(node)
            if not name:
                continue
            refs = _loads(node) & (set(syms) & patched)
            refs.discard(name[0])
            if refs:
                out |= {(unit, name[0], r) for r in refs}
    return out


class TestPatchSeamsAreNotBypassed:
    """判据 7：patch 接缝不得被**同族内部调用**绕过。"""

    def test_patch_targets_are_extracted_and_non_empty(self):
        """fail-closed：抽不到 patch 点 ⇒ 本判据就是空跑，直接报错。"""
        patched = patched_at_base_skill()
        anchors = {"get_skill_llm", "_execute_tool_safe", "logger", "_auto_resolve_ids"}
        assert anchors <= patched, (
            f"patch 点提取漏了已知锚点：{sorted(anchors - patched)}（判据静默变空跑，宁可红）")

    def test_no_moved_symbol_is_both_patched_and_intra_unit_called(self):
        """同族内部调用会绕过 `base_skill` 的 patch —— 一处都不许有。"""
        bad = seam_violations(UNITS)
        assert bad == set(), (
            f"这些符号既被 `patch(\"app.graph.skills.base_skill.X\")` 打桩、又被同一单元里的成员"
            f"直接调用 ⇒ 那个 patch **静默失效**：{sorted(bad)}"
            f"（出口：patch 目标同批搬到新住址并断言 `mock.called`，或调用期经 `_base` 取）")

    def test_guard_reports_a_planted_violation(self, tmp_path):
        """负例：植入「同族内部直接调用一个被 patch 的符号」⇒ 判据必报。

        没有这条，上面那条完全可能是"永远绿的空判据"（§19.1 形状判别力）。
        """
        fake_skills = tmp_path / "skills"
        fake_skills.mkdir()
        (fake_skills / "fake_unit.py").write_text(
            "def _flag():\n    return True\n"
            "\n"
            "def _caller():\n    return _flag()\n",
            encoding="utf-8")
        fake_tests = tmp_path / "tests"
        fake_tests.mkdir()
        (fake_tests / "test_x.py").write_text(
            'from unittest.mock import patch\n'
            'patch.object(base_skill, "_flag")\n',
            encoding="utf-8")
        got = seam_violations({"fake_unit.py": ["_flag", "_caller"]},
                              tests_dir=fake_tests, skills_dir=fake_skills)
        assert got == {("fake_unit.py", "_caller", "_flag")}, (
            f"植入「被 patch 的符号被同族内部直接调用」后判据仍不报 —— 这是空判据（实得 {got}）")

    def test_planted_violation_disappears_when_seam_moves_to_the_new_home(self, tmp_path):
        """负控：把 patch 目标改到新住址（不再打 base_skill）⇒ 同一判据**不再报**。

        这一条证明上一条的红**确实来自"接缝被绕过"本身**，不是来自"扫到文件就红"。
        """
        fake_skills = tmp_path / "skills"
        fake_skills.mkdir()
        (fake_skills / "fake_unit.py").write_text(
            "def _flag():\n    return True\n\ndef _caller():\n    return _flag()\n",
            encoding="utf-8")
        fake_tests = tmp_path / "tests"
        fake_tests.mkdir()
        (fake_tests / "test_x.py").write_text(
            'from unittest.mock import patch\n'
            'patch.object(fake_unit, "_flag")\n',
            encoding="utf-8")
        assert seam_violations({"fake_unit.py": ["_flag", "_caller"]},
                               tests_dir=fake_tests, skills_dir=fake_skills) == set()


# ── 判据 8：`logger` 接缝**真的**在调用期解析（同批断言 mock.called）──────────
def test_logger_seam_is_resolved_at_call_time_not_frozen():
    """`patch("app.graph.skills.base_skill.logger")` 必须**仍然**影响搬走的代码。

    做法 = 真 patch + 真调用 + **断言 `mock.called`**：
    `patch()` 打在不存在的属性上**不会报错**，只让 mock 失效 ⇒ 不查 `called` 就分不清
    「判据通过」和「判据空跑」。这里驱动的是搬进 `injection_blocks` 的
    `_masked_phone_block_result`（纯同步、无存储依赖，命中即写一条 warning）。
    """
    from unittest.mock import patch

    from app.graph.skills import base_skill, injection_blocks

    with patch("app.graph.skills.base_skill.logger") as mock_logger:
        out = injection_blocks._masked_phone_block_result(
            "order_create", "items[0].phone", "138****8000", "13800138000",
            "sess-x", "order", because="含掩码字符")
    assert isinstance(out, tuple) and len(out) == 3, f"返回值形态变了：{out!r}"
    assert mock_logger.warning.called, (
        "patch 失效：搬走后的代码没有经 base_skill.logger 记日志 ⇒ 既有 6 处 "
        "`patch(\"app.graph.skills.base_skill.logger\")` 会全部静默空跑")
    assert "write_blocked_masked_phone" in out[1], (
        f"拦截码变了（既有行为漂移）：{out[1][:120]!r}")
    assert "_masked_phone_block_result" in dir(injection_blocks)
    assert "def _masked_phone_block_result(" not in _read(BASE_SKILL_PY), (
        "base_skill.py 里又长回一份 `_masked_phone_block_result` 定义")
