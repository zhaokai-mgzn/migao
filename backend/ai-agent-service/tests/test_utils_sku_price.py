# case_ids: OR-014
"""`sku_price` 层间接缝守卫（issue #4057 S7）—— 静态层间判据 + 同一对象证明。

## 病灶

`app/tools/order_create.py` 用**函数级反向 import**
`from app.graph.skills.base_skill import unit_price_grounding_error / _match_sku_price /
_library_unit_price_grounded` 取「单价接地」判据 ⇒ 叶子模块（`app/tools/**`）依赖上层编排
模块（`app/graph/skills/**`）的**私有**实现。判据本身没错，错的是**分层方向**：它让
tools → graph.skills 成了隐式契约（skill 层一搬家/改私有名，工具层静默崩或拿到另一份口径）。

## 治法（本文件锁的形态）

判据搬到**中性模块** `app/utils/sku_price.py`（`app/utils/**` 不 import 任何上层模块），
两边都向下依赖它：

    app/graph/skills/base_skill.py   ── re-export ──▶ app/utils/sku_price.py
    app/tools/order_create.py        ─────────────────▶ app/utils/sku_price.py
    app/graph/skills/execution/react_turn.py ──(顶层 import base_skill)──▶ 同上（单一实现）

## 三条判据（每条都有反例输入）

| 用例 | 判据 | 反例输入（改这一处即红） |
|---|---|---|
| `test_tools_layer_does_not_import_skill_layer` | `app/tools/**` 里**没有** `app.graph.*` 的 import | 把 `order_create.py` 的 import 改回 `app.graph.skills.base_skill` |
| `test_base_skill_reexports_the_moved_symbols` | `base_skill.py` 顶层从 `app.utils.sku_price` 再导出 5 个同名符号 | 删掉 re-export（`react_turn.py` 顶层 import 会当场 ImportError） |
| `test_reexports_are_the_same_objects` | 再导出的是**同一个函数对象**（不是两份拷贝） | 在 base_skill 里复制一份函数体（算法会各自漂移） |
| `TestLayerSeamDetectorIsNotVacuous` | 判据自身可红 + 不恒真（注入式夹具） | —— |

⚠️ 判据 ①/② 是**静态 AST**（零 LLM、零 app 依赖）；判据 ③ 需要 import app（本文件跑在
ai-agent-service 的 pytest 套件里，与 `tests/test_order_price_grounding.py` 同层）。
"""

import ast
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[1]   # tests/<本文件> → ai-agent-service 根
APP_DIR = SERVICE_DIR / "app"
assert (APP_DIR / "utils").is_dir(), (   # fail-closed：路径基准解析错必须响亮失败，不许「扫不到就通过」
    f"测试路径基准解析错：{SERVICE_DIR} 下没有 app/utils —— 静态判据会退化成空跑"
)
TOOLS_DIR = APP_DIR / "tools"
BASE_SKILL_PY = APP_DIR / "graph" / "skills" / "base_skill.py"
NEUTRAL_MODULE = "app.utils.sku_price"

#: 搬走 + 再导出的符号（含私有依赖）—— 判据逐条钉住。
MOVED_SYMBOLS = (
    "unit_price_grounding_error",
    "_match_sku_price",
    "_library_unit_price_grounded",
    "_PRICE_TOLERANCE",
    "_to_float",
)

#: tools 层不得依赖的上层前缀（skill / 编排层）。
FORBIDDEN_IMPORT_PREFIX = "app.graph"


def _module_ast(path: Path) -> ast.Module:
    assert path.is_file(), f"守卫的被扫目标不存在：{path}（fail-closed，不静默跳过）"
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _graph_imports(path: Path) -> list[tuple[int, str]]:
    """文件里所有 `from app.graph…` / `import app.graph…` 的（行号, 模块名）。

    函数级 import 也算（`ast.walk` 扫全树）—— 反向依赖不因"写在函数里"而合法。
    """
    out: list[tuple[int, str]] = []
    for node in ast.walk(_module_ast(path)):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(FORBIDDEN_IMPORT_PREFIX):
            out.append((node.lineno, node.module or ""))
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(FORBIDDEN_IMPORT_PREFIX):
                    out.append((node.lineno, alias.name))
    return out


def tools_layer_graph_imports(tools_dir: Path = TOOLS_DIR) -> list[str]:
    """`app/tools/**` 里对 `app.graph.*` 的 import 清单（`文件:行 → 模块`）。"""
    hits: list[str] = []
    for path in sorted(tools_dir.rglob("*.py")):
        hits += [f"{path.name}:{lineno} → {mod}" for lineno, mod in _graph_imports(path)]
    return hits


def reexported_symbols(path: Path, source_module: str = NEUTRAL_MODULE) -> set:
    """模块顶层 `from <source_module> import …` 的符号集合。"""
    return {
        alias.name
        for node in _module_ast(path).body
        if isinstance(node, ast.ImportFrom) and node.module == source_module
        for alias in node.names
    }


def defined_symbols(path: Path) -> set:
    """模块顶层**定义**的函数名 / 赋值名（`def` / `x = …`）。"""
    names = set()
    for node in _module_ast(path).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return names


# ──────────────────────────────────────────────────────────────────────────────
# 判据 ①：工具层不得反向依赖 skill / 编排层
# ──────────────────────────────────────────────────────────────────────────────


def test_tools_layer_does_not_import_skill_layer():
    """`app/tools/**` 不得出现任何 `app.graph.*` 的 import（正向依赖只许向下）。

    反例输入：把 `order_create.py` 的 import 改回 `app.graph.skills.base_skill` ⇒ 必红。
    """
    scanned = sorted(TOOLS_DIR.rglob("*.py"))
    assert len(scanned) >= 10, (
        f"只扫到 {len(scanned)} 个 tools 文件 —— 扫描面塌了，判据会变成空跑（fail-closed）"
    )
    hits = tools_layer_graph_imports()
    assert hits == [], (
        f"工具层出现对上层模块的 import（分层倒置，issue #4057 S7）：{hits}\n"
        f"→ 判据定义在 `{NEUTRAL_MODULE}`（中性层），两边都从那里取；"
        f"工具的叶子模块身份不得依赖 `app/graph/**`。"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 判据 ②：base_skill 必须再导出搬走的符号（兼容既有 import 路径）
# ──────────────────────────────────────────────────────────────────────────────


def test_base_skill_reexports_the_moved_symbols():
    """`base_skill.py` 顶层从 `app.utils.sku_price` 再导出 5 个同名符号。

    反例输入：删掉 re-export ⇒ 必红（`execution/react_turn.py` 顶层
    `from app.graph.skills.base_skill import …, unit_price_grounding_error, …` 也会 ImportError）。
    """
    got = reexported_symbols(BASE_SKILL_PY)
    missing = sorted(set(MOVED_SYMBOLS) - got)
    assert missing == [], (
        f"`base_skill.py` 没有从 `{NEUTRAL_MODULE}` 再导出：{missing}\n"
        f"  实测已导出 = {sorted(got & set(MOVED_SYMBOLS))}\n"
        f"→ 判据搬走后必须再导出同名符号：`execution/react_turn.py` 与既有测试的 import 路径"
        f"都还挂在这里，删掉即当场 ImportError。"
    )


def test_neutral_module_actually_defines_the_symbols():
    """中性模块必须**自己定义**这些符号（防「re-export 一个空壳/不存在的名」）。"""
    neutral = APP_DIR / "utils" / "sku_price.py"
    defined = defined_symbols(neutral)
    assert "unit_price_grounding_error" in defined, (
        f"`{NEUTRAL_MODULE}` 没有定义 `unit_price_grounding_error`（实测 {sorted(defined)}）"
    )
    # base_skill 里**不得**再有一份定义（那样就又成了两份会各自漂移的实现）
    base_defined = defined_symbols(BASE_SKILL_PY)
    duplicated = sorted(set(MOVED_SYMBOLS) & base_defined)
    assert duplicated == [], (
        f"这些符号在 `base_skill.py` 里**又被定义了**（与中性模块成为两份实现）：{duplicated}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 判据 ③：再导出的是**同一个对象**（不是拷贝）—— 需要 import app
# ──────────────────────────────────────────────────────────────────────────────


class TestReexportsAreTheSameObjects:
    """单一实现点：`base_skill` 的这些名字必须**就是** `app.utils.sku_price` 里的对象。

    反例输入：在 `base_skill.py` 里复制一份 `def unit_price_grounding_error(...)` ⇒ 必红
    （复制品会与中性模块各自漂移 —— 正是本包要消除的「两份口径」形态）。
    """

    def test_functions_are_identical_objects(self):
        import app.utils.sku_price as neutral
        from app.graph.skills import base_skill

        for name in ("unit_price_grounding_error", "_match_sku_price",
                     "_library_unit_price_grounded", "_to_float"):
            assert getattr(base_skill, name) is getattr(neutral, name), (
                f"`base_skill.{name}` 与 `{NEUTRAL_MODULE}.{name}` 不是同一对象 —— "
                f"存在两份实现（口径会各自漂移）"
            )

    def test_price_tolerance_is_the_same_value(self):
        import app.utils.sku_price as neutral
        from app.graph.skills import base_skill

        assert base_skill._PRICE_TOLERANCE == neutral._PRICE_TOLERANCE, (
            "容差常量出现两份（再导出的必须是同一个定义点）"
        )

    def test_skill_layer_call_site_still_works_from_base_skill(self):
        """skill 层消费点（`react_turn.py` 顶层 import 的那个名字）行为不变。"""
        from app.graph.skills.base_skill import unit_price_grounding_error

        err = unit_price_grounding_error(
            [{"product_name": "遮光窗帘", "unit_price": 150.0}],
            {"product_id": "p1", "name": "遮光窗帘", "price": 168.0, "skus": []},
        )
        assert err and "150.0" in err and "168.0" in err, (
            f"搬走后判据行为变了（应仍报单价不一致）：{err!r}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 判据 ④：判据自身可红 + 不恒真（注入式夹具）
# ──────────────────────────────────────────────────────────────────────────────


class TestLayerSeamDetectorIsNotVacuous:
    """**:red_circle: 红证**（注入式）+ **负例**。"""

    def test_detector_reports_a_planted_reverse_import(self, tmp_path):
        """植入「工具叶子模块反向 import skill 层」的文件 ⇒ **必须报出**。"""
        (tmp_path / "fake_tool.py").write_text(
            "def _check():\n"
            "    from app.graph.skills.base_skill import unit_price_grounding_error\n"
            "    return unit_price_grounding_error\n",
            encoding="utf-8")
        assert tools_layer_graph_imports(tmp_path) == [
            "fake_tool.py:2 → app.graph.skills.base_skill"
        ], "植入反向 import 后判据仍不报 —— 这是空判据"

    def test_detector_stays_quiet_on_a_neutral_import(self, tmp_path):
        """负例：合法的中性层 import ⇒ **必须不报**（防恒红）。"""
        (tmp_path / "fake_tool.py").write_text(
            "from app.utils.sku_price import unit_price_grounding_error\n"
            "import json\n",
            encoding="utf-8")
        assert tools_layer_graph_imports(tmp_path) == []

    def test_reexport_detector_reports_a_planted_missing_symbol(self, tmp_path):
        """植入「只再导出两个符号」的源码 ⇒ 缺的那三个必须被报出。"""
        planted = tmp_path / "planted_base.py"
        planted.write_text(
            "from app.utils.sku_price import unit_price_grounding_error, _to_float\n",
            encoding="utf-8")
        got = reexported_symbols(planted)
        assert sorted(set(MOVED_SYMBOLS) - got) == [
            "_PRICE_TOLERANCE", "_library_unit_price_grounded", "_match_sku_price"
        ]