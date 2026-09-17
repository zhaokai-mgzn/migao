# case_ids: CH-013, CH-014, CH-015
"""`execute_skill` 拆成「薄编排壳 + 三段实现」的结构守卫（issue #4049）。

被测契约（源头是「关联 #4043」的 S3 条）：
  · `base_skill.execute_skill` 曾是**单函数 1699 行**、内含 9 类职责 ⇒ #4043 的其余四个包
    （S-A/S-B/S-C/T-B）只能改同一个文件、只能串行排队。拆成 `execute_skill`（薄壳）+
    `app/graph/skills/execution/{prepare_turn,react_turn,finalize_turn}.py`（三段实现）后，
    四个包才可以各改一个文件。
  · 本文件是**结构判据**（静态可判、零 LLM）：壳必须继续变薄、三段实现必须真的在、
    搬迁**不得**顺手丢掉守卫、`nonlocal` 状态锚点不得静默丢失。

为什么单独立测：这类"拆分"最常见的失败形态不是崩，而是**判据自己选择沉默** ——
搬走了代码、壳也薄了，但某个守卫/状态锚点掉在地上没人发现（§19.1 形状判据）。
故每条断言都 fail-closed：扫描目标文件缺失 / 取不到真值时**报错**，不静默通过。

⚠️ 本文件只断言**结构**；行为面由既有用例（CH-013/CH-014/CH-015 等）与全量单测覆盖 ——
结构守卫**不替代**行为验证。
"""
import ast
import re
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[2] / "app"
SERVICE_DIR = Path(__file__).resolve().parents[2]
TESTS_DIR = SERVICE_DIR / "tests"
SKILLS_DIR = APP_DIR / "graph" / "skills"
BASE_SKILL_PY = SKILLS_DIR / "base_skill.py"
EXECUTION_DIR = SKILLS_DIR / "execution"

# ── 拆分后的目标结构（本包交付形态）──
SHELL_MAX_LINES = 300
EXECUTION_MODULES = {
    "prepare_turn.py": "prepare_turn",
    "react_turn.py": "react_turn",
    "finalize_turn.py": "finalize_turn",
}
# 每段实现的最小体量：低于此值说明"搬了个空壳"（原三段分别约 292 / 1185 / 208 行）
MIN_REGION_LINES = 50

# 留在 `base_skill.py` 的模块级助手（搬迁**不得**动它们；`_execute_tool_safe` 另有守卫）
STAYS_IN_BASE_SKILL = [
    "_execute_tool_safe",
    "_self_correct_retry",
    "confirm_value_for_fields",
    "confirm_card_fields",
    "_read_cached",
    "_build_system_prompt",
]

# 搬迁后仍必须活在**整个家族**里的守卫痕迹（少一个就是"搬丢了"）
GUARD_TOKENS = [
    "RATE LIMITED",                       # 0 节 速率限制
    "confirmation_required_no_card",      # 7 节 写门禁链
    "normalize_draft_state_reply",        # 8.6 草稿态回复归一
    "set_pending_skill",                  # 10 节 跨轮 pending_skill 持久化
    "clear_vision_analysis",              # 5/6 节 Vision 分支
    "<interact>",                         # 8.3b 补发确认卡兜底
]


def _read(path: Path) -> str:
    """读源码；文件缺失即**报错**（fail-closed，不给"扫不到就通过"留口子）。"""
    assert path.is_file(), f"结构守卫的被扫目标不存在：{path}（fail-closed，不静默跳过）"
    return path.read_text(encoding="utf-8")


def _module_ast(path: Path) -> ast.Module:
    return ast.parse(_read(path), filename=str(path))


def _find_func(tree: ast.Module, name: str):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} 未定义（结构守卫的被测对象不见了）")


def family_sources(execution_dir: Path = EXECUTION_DIR) -> dict:
    """**搬迁后的整个家族**源码：`base_skill.py` + `app/graph/skills/execution/*.py`。

    为什么必须扫家族而不是单文件：本包把 1699 行按职责搬到 `execution/`，任何"只扫
    base_skill.py"的文本判据**都会变成空跑但仍全绿**（§19.1「判据自己选择沉默」）。
    fail-closed：`execution/` 下必须**至少**有 3 个 .py（三段实现），否则报错。
    """
    sources = {str(BASE_SKILL_PY): _read(BASE_SKILL_PY)}
    assert execution_dir.is_dir(), f"拆分后的实现目录不存在：{execution_dir}"
    exec_files = sorted(execution_dir.glob("*.py"))
    assert len(exec_files) >= 3, (
        f"{execution_dir} 下的实现文件少于 3 个（实得 {[p.name for p in exec_files]}）"
        f"—— 家族扫描会静默漏掉搬走的守卫"
    )
    for path in exec_files:
        sources[str(path)] = _read(path)
    return sources


def base_skill_family_sources() -> dict:
    return family_sources()


class TestShellIsThin:
    """`execute_skill` 必须是薄编排壳（本包的**核心判据**）。"""

    def test_execute_skill_body_within_line_budget(self):
        """壳的体量上限：搬迁前实测 1699 行 ⇒ 必须收敛到 ≤ 300 行。"""
        func = _find_func(_module_ast(BASE_SKILL_PY), "execute_skill")
        lines = func.end_lineno - func.lineno + 1
        assert lines <= SHELL_MAX_LINES, (
            f"execute_skill 仍 {lines} 行（上限 {SHELL_MAX_LINES}）"
            f"—— 职责没有真正切出去，#4043 的其余四包还得排队改同一个文件"
        )

    def test_shell_has_no_loop_and_no_try(self):
        """壳里不得再出现循环 / 异常处理 —— 那些都属于三段实现。"""
        func = _find_func(_module_ast(BASE_SKILL_PY), "execute_skill")
        loops = [n for n in ast.walk(func) if isinstance(n, (ast.For, ast.AsyncFor, ast.While))]
        tries = [n for n in ast.walk(func) if isinstance(n, ast.Try)]
        assert (len(loops), len(tries)) == (0, 0), (
            f"壳内仍有 {len(loops)} 个循环 / {len(tries)} 个 try —— 职责未切净"
        )

    def test_shell_calls_the_three_regions(self):
        """壳必须**恰好**调用三段实现各一次（缺一即丢职责，多一即职责回流）。"""
        func = _find_func(_module_ast(BASE_SKILL_PY), "execute_skill")
        called = [
            n.func.id for n in ast.walk(func)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        ]
        for region in EXECUTION_MODULES.values():
            assert called.count(region) == 1, (
                f"壳调用 {region} 的次数是 {called.count(region)}（应为 1）：{sorted(called)}"
            )


class TestThreeRegionsExist:
    """三段实现必须真的在，且体量与职责相称（防"搬了个空壳"）。"""

    @pytest.mark.parametrize("filename,func_name", sorted(EXECUTION_MODULES.items()))
    def test_region_module_defines_its_entrypoint(self, filename, func_name):
        """每个目标模块都必须定义同名入口函数（fail-closed：文件缺失即报错）。"""
        func = _find_func(_module_ast(EXECUTION_DIR / filename), func_name)
        lines = func.end_lineno - func.lineno + 1
        assert lines >= MIN_REGION_LINES, (
            f"{filename}::{func_name} 只有 {lines} 行（下限 {MIN_REGION_LINES}）"
            f"—— 不像是「把原分节搬过来了」，更像空壳"
        )

    def test_prepare_turn_keeps_all_seventeen_sections_shape(self):
        """0~6 节的**职责痕迹**必须在 `prepare_turn` 里（含速率限制早退与 Vision 分支）。"""
        src = _read(EXECUTION_DIR / "prepare_turn.py")
        for token in ("RATE LIMITED", "Input truncated", "clear_vision_analysis"):
            assert token in src, f"prepare_turn 丢了 0~6 节的职责痕迹：{token!r}"

    def test_react_turn_keeps_write_gate_and_card_emission(self):
        """第 7 节的**职责痕迹**必须在 `react_turn` 里（写门禁链 / 卡片发射 / 纠偏）。"""
        src = _read(EXECUTION_DIR / "react_turn.py")
        for token in ("confirmation_required_no_card", "_run_one_tool",
                      "_STALL_CORRECTIVE", "_execute_tool_safe("):
            assert token in src, f"react_turn 丢了第 7 节的职责痕迹：{token!r}"

    def test_finalize_turn_keeps_the_four_closures(self):
        """8.3b/8.4/8.5/8.6 + 9/10 节的**职责痕迹**必须在 `finalize_turn` 里。"""
        src = _read(EXECUTION_DIR / "finalize_turn.py")
        for token in ('"final_answer"', "normalize_draft_state_reply",
                      "set_pending_skill", "pending_interact_skill"):
            assert token in src, f"finalize_turn 丢了 8.3b~10 节的职责痕迹：{token!r}"


class TestGuardsSurviveTheMove:
    """搬迁**不得**顺手丢守卫 —— 判据扫整个家族，并且 fail-closed。"""

    def test_execute_tool_safe_still_lives_in_base_skill(self):
        """`_execute_tool_safe` 的 `result_dict` 字面量是 `test_contract_wiring.py` 的真相源。

        ⚠️ 该守卫用 AST 在 `base_skill.py` 里找 `result_dict = {...}` 字面量，找不到就
        fail-closed 报错 ⇒ `_execute_tool_safe` **必须留在 base_skill.py**（本包不可搬走它）。
        """
        func = _find_func(_module_ast(BASE_SKILL_PY), "_execute_tool_safe")
        literals = [
            n for n in ast.walk(func)
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "result_dict" for t in n.targets)
            and isinstance(n.value, ast.Dict)
        ]
        assert len(literals) == 1, (
            f"base_skill.py 里 `_execute_tool_safe` 的 result_dict 字面量有 {len(literals)} 个"
            f"（应为 1）—— test_contract_wiring.py 的真相源被搬走了"
        )

    @pytest.mark.parametrize("name", STAYS_IN_BASE_SKILL)
    def test_module_level_helpers_stay_in_base_skill(self, name):
        """模块级助手留在原文件（三段实现顶层 import 它们，搬走会与 import 方向成环）。"""
        defined = {
            n.name for n in _module_ast(BASE_SKILL_PY).body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert name in defined, f"{name} 不在 base_skill.py 的模块级（助手被搬走了）"

    @pytest.mark.parametrize("token", GUARD_TOKENS)
    def test_guard_token_survives_somewhere_in_the_family(self, token):
        """守卫痕迹必须仍在**家族**里（只扫 base_skill.py 会在搬迁后变成空判据）。"""
        hits = [path for path, src in base_skill_family_sources().items() if token in src]
        assert hits, f"守卫痕迹 {token!r} 在搬迁后的整个家族里都找不到 —— 疑似搬丢了"

    def test_family_scan_is_fail_closed_on_missing_region_file(self, tmp_path):
        """负例（§19.1）：家族扫描**真的会红** —— 不是"永远绿"的空判据。

        用替身目录（只放 1 个实现文件）跑**同一个** `family_sources` 判据 ⇒ 必须报错；
        再接上一条：把 3 个文件补齐后同一判据不再报错（证明红的原因是"少文件"本身）。
        """
        fake_dir = tmp_path / "execution"
        fake_dir.mkdir()
        (fake_dir / "prepare_turn.py").write_text("x = 1\n", encoding="utf-8")
        with pytest.raises(AssertionError, match="少于 3 个"):
            family_sources(fake_dir)

        for extra in ("react_turn.py", "finalize_turn.py"):
            (fake_dir / extra).write_text("y = 2\n", encoding="utf-8")
        assert sorted(family_sources(fake_dir)) != [], "补齐实现文件后家族扫描仍应为非空"


class TestNonlocalStateAnchors:
    """第 7 节的 `nonlocal` 状态锚点不得静默丢失（跨函数后它们应成为参数）。"""

    def test_nonlocal_targets_are_parameters_of_react_turn(self):
        """`_run_one_tool` 的 3 条 `nonlocal` 目标必须是 `react_turn` 的**参数**。

        为什么：`nonlocal` 只在"目标名是外层函数的局部绑定"时合法。搬迁后若改成在
        `react_turn` 内**重新初始化**，写门禁的置位就只落在新函数里、编排侧永远读不到
        （`_no_card_blocked_args` 读不到 ⇒ 补发确认卡兜底失效；`_write_ok` 读不到 ⇒
        草稿态归一误判）—— 这正是注释里记着的那次"不加 nonlocal"事故的同型复发。
        """
        func = _find_func(_module_ast(EXECUTION_DIR / "react_turn.py"), "react_turn")
        params = {a.arg for a in func.args.args} | {a.arg for a in func.args.kwonlyargs}
        nonlocals = set()
        for node in ast.walk(func):
            if isinstance(node, ast.Nonlocal):
                nonlocals |= set(node.names)
        assert nonlocals, "react_turn 里找不到 nonlocal 声明 —— _run_one_tool 的锚点丢了"
        missing = sorted(nonlocals - params)
        assert missing == [], (
            f"nonlocal 目标 {missing} 不是 react_turn 的参数 —— 状态会静默丢失"
        )

    def test_react_turn_returns_the_four_cross_region_state_anchors(self):
        """跨到 8~10 节的状态必须**显式交回**编排壳（返回值键名逐条钉住）。"""
        src = _read(EXECUTION_DIR / "react_turn.py")
        for key in ('"final_content"', '"_executed_tools"', '"_no_card_blocked_args"',
                    '"_write_ok"', '"_relocked_this_round"', '"new_messages"'):
            assert key in src, f"react_turn 没有把 {key} 交回编排壳 —— 8~10 节会读到空"

# ── patch 缝：从测试源码里**机械提取**（自动跟随将来新增的 patch 点）──────────────
# 形如 `patch("a.b.c.NAME")` / `patch.object(<alias>, "NAME")`，其中 alias 来自
# `import a.b.c as <alias>`。判据：execution/*.py 的**模块顶层** import 不得冻住这些名字。
_PATCH_DOTTED_RE = re.compile(
    r"patch(?:\.object)?\(\s*[\"']([A-Za-z_][\w.]*)\.([A-Za-z_]\w*)[\"']")
_IMPORT_ALIAS_RE = re.compile(
    r"^import\s+([A-Za-z_][\w.]*)\s+as\s+([A-Za-z_]\w*)", re.M)
#: `patch.object(<alias>, "NAME")` —— alias 必须是某个 `import X as alias`
_PATCH_OBJECT_RE = re.compile(r"patch\.object\(\s*([A-Za-z_]\w*)\s*,\s*[\"']([A-Za-z_]\w*)[\"']")


def _patched_attributes() -> set:
    """全仓测试源码里打到 (`模块全名`, `属性名`) 的 patch 点集合。"""
    patched = set()
    for path in sorted(TESTS_DIR.rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        patched |= {(mod, name) for mod, name in _PATCH_DOTTED_RE.findall(src)}
        aliases = dict((alias, mod) for mod, alias in _IMPORT_ALIAS_RE.findall(src))
        for alias, name in _PATCH_OBJECT_RE.findall(src):
            if alias in aliases:
                patched.add((aliases[alias], name))
    return patched


def _module_level_from_imports(path: Path) -> set:
    """某模块**顶层** `from M import N` 的 (`M`, `N`) 集合（模块级 = 冻结点）。"""
    out = set()
    for node in _module_ast(path).body:
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                out.add((node.module, alias.name))
    return out


def _frozen_patch_seams(execution_dir: Path = EXECUTION_DIR) -> set:
    """「被测试 patch、却在搬走的模块顶层被 import 冻住」的接缝清单（空 = 通过）。

    抽成纯函数是为了能喂**负例夹具**（证明它真的会红，而不是永远绿的空判据）。
    """
    patched = _patched_attributes()
    return {
        (path.name, mod, name)
        for path in sorted(execution_dir.glob("*.py"))
        for mod, name in _module_level_from_imports(path)
        if (mod, name) in patched
    }


class TestPatchSeamsStayAlive:
    """`patch.object(base_skill, "<name>")` 必须继续影响**搬走之后**的代码。

    为什么：拆分前这些名字是 base_skill 的**模块全局**、调用期解析 ⇒ patch 生效。
    模块顶层 `from ... import <name>` 会把绑定**冻在 import 那一刻** ⇒ patch 静默失效
    （本仓最忌讳的「判据自己选择沉默」；实证：搬迁后 `patch.object(base_skill, "get_skill_llm")`
    不再影响 0~6 节的取 LLM 调用，15 条行为用例当场变红）。故 execution/*.py 里这些名字
    一律在**函数入口处**从源模块动态取（见各模块的「patch 点」注释）。
    判据**机械提取** patch 目标 ⇒ 将来新增的 patch 点自动被覆盖。
    """

    def test_patch_targets_are_extracted_and_non_empty(self):
        """fail-closed：抽不到 patch 点时判据就是空跑 —— 直接报错。"""
        patched = _patched_attributes()
        anchors = {
            ("app.graph.skills.base_skill", "get_skill_llm"),
            ("app.graph.skills.base_skill", "_execute_tool_safe"),
            ("app.memory.session_memory", "SessionMemory"),
        }
        assert anchors <= patched, (
            f"patch 点提取漏了已知锚点：{sorted(anchors - patched)}"
            f"（判据静默变空跑，宁可红）"
        )

    def test_no_patch_seam_is_frozen_at_module_level(self):
        """execution/*.py 顶层 import 与全仓 patch 点的交集必须为空。"""
        frozen = _frozen_patch_seams()
        assert frozen == set(), (
            f"这些 patch 点在搬迁后被**模块顶层 import 冻住** ⇒ 守卫静默失效：{sorted(frozen)}"
            f"（应在函数入口处从源模块动态取，见各模块「patch 点」注释）"
        )

    def test_guard_reports_a_planted_frozen_seam(self, tmp_path):
        """负例：把「顶层 import 冻住接缝名」的模块塞进替身目录 ⇒ 判据必报。

        没有这条，上面那条判据完全可能是"永远绿的空判据"（§19.1 形状判据）。
        """
        (tmp_path / "react_turn.py").write_text(
            "from app.graph.skills.base_skill import _execute_tool_safe\n"
            "from app.memory.session_memory import SessionMemory\n"
            "\n"
            "def react_turn():\n"
            "    return _execute_tool_safe, SessionMemory\n",
            encoding="utf-8")
        assert _frozen_patch_seams(tmp_path) == {
            ("react_turn.py", "app.graph.skills.base_skill", "_execute_tool_safe"),
            ("react_turn.py", "app.memory.session_memory", "SessionMemory"),
        }, "植入「冻住的接缝」后判据仍不报 —— 这是空判据"

    def test_seam_binding_happens_at_call_time(self):
        """反向：被 patch 的名字必须真的在**函数体内**重新绑定（否则上面的空集是假绿）。"""
        src = _read(EXECUTION_DIR / "react_turn.py")
        func_src = ast.get_source_segment(src, _find_func(_module_ast(EXECUTION_DIR / "react_turn.py"),
                                                          "react_turn"))
        for name in ("_execute_tool_safe", "get_breaker", "logger", "SessionMemory"):
            assert f"{name} = _base.{name}" in func_src or f"import SessionMemory" in func_src, (
                f"{name} 没有在 react_turn 入口处调用期绑定 —— patch 会失效"
            )
