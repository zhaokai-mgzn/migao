# case_ids: MC-012, CH-015
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012；
#   CH-015 是本次被改造的「显式转人工」用例 —— 它现在断言的正是本文件锁的行为）
"""转人工工具（`human_handoff`）退场的 **L0 反回退判据**（用户裁定 2026-09-19）。

## 裁定原文（本判据的唯一理由）

> 「**不应该存在 human_handoff 这种东西，以后全是 AI 来判断**」

⇒ 把「转人工」这个**模型可达能力**下线（阶段一：不销毁数据、不删后端能力）。

## 病根：为什么"删掉绑定"这件事必须有判据

退场的动作分散在**五处可以各自漂移的清单**里，而它们**都不会自己变红**：

| 面 | 载体 | 退场后仍可被谁加回去 |
|---|---|---|
| 工具集 | 各 skill 的 `*_TOOLS` 常量 | 下一个认为"兜底该给个人工出口"的人 |
| 注册表 | `registry.py::create_default_registry` 的 `registry.register(...)` | 同 #3917 的 `processing_order_*` 形态 |
| 门面 | `app/tools/__init__.py` 的 import / `__all__` | 门面漂移（`test_tools_registry` 家族） |
| **prompt** | `references/**` + skill 内联 prompt | **最危险**：模型被告知一个按不动的出口 |
| 运行时处方 | `chat` 降级建议、`validate_input` 建议、澄清兜底话术 | 同上：模型把失败答成"已转人工" |

**prompt 面为什么比没有更糟**：工具不在工具集里 ⇒ 模型调不动它；但 prompt 里写着
「需要人工介入时改走 human_handoff」，模型就会**用自然语言承诺**"已为您转接人工客服"
—— 顾客拿到一个不存在的入口，比一开始就说明"我这边办不了"更伤（`migao-acceptance`
「假承诺」族）。故本判据把 prompt 面与工具集**同等**锁死。

## 四条判据（全部**结构**判据，不扫"人工"这类中文措辞）

1. `test_no_skill_binds_the_retired_tool` —— 任何 skill 的 `tool_names` 都不含该工具；
2. `test_registry_does_not_register_the_retired_tool` —— 默认注册表不注册该工具类；
3. `test_facade_does_not_export_the_retired_tool` —— 门面不导出（与注册表同口径）；
4. `test_prompt_surfaces_do_not_point_at_the_retired_tool` ——
   **模型可见的文案**（`references/**` 全部 `.md` + skill 内联 prompt 字符串 +
   运行时处方字符串）里**不得出现该工具名**。

### 为什么判据建在"结构"上（不扫中文关键词）

「转人工」「人工客服」这些**中文措辞**在退场后**仍然合法**：prompt 必须继续告诉模型
「顾客说『转人工』时**如实说明没有人工转接通道**，然后自己接着办」—— 这是本次改造
**新增**的必需文案。所以：

* 判据的锚 = **工具名**（`human_handoff` / `HumanHandoffTool` / `human-handoff`）
  出现在**会被送进模型或回给用户的字符串**里；
* 「人工」这类措辞**不判**（否则合法文案必红，判据只能靠豁免活着 = 空判据）。

### 为什么只扫 `app/graph/skills/*.py` 的**字符串字面量**（不扫整文件文本）

* 注释**不是** AST 字面量 ⇒ 判据不会因为"注释里记着历史（CH-012 实证的 tools 列表、
  #3917 的处置说明）"而红 —— 那些历史必须留档；
* 守卫代码里比对工具名的**字面量**（`react_turn.py` 的
  `if tool_name == "human_handoff"`、`base_skill.py` 的守卫 docstring）**刻意保留**：
  与"保留工具类文件"同口径 —— 它们是**禁止**该调用，不是**处方**；
* 处方面（prompt / 降级建议 / 校验建议）同样只是字面量检查，覆盖面精确。

## 每条的**反例输入**（红证，命令见 PR body）

| 用例 | 改这一处即红 |
|---|---|
| `test_no_skill_binds_the_retired_tool` | 把 `"human_handoff"` 加回 `CUSTOMER_GENERAL_TOOLS` |
| `test_registry_does_not_register_the_retired_tool` | 取消注释 `registry.register(HumanHandoffTool())` |
| `test_facade_does_not_export_the_retired_tool` | 取消注释门面里的 import |
| `test_prompt_surfaces_do_not_point_at_the_retired_tool`（references） | 在 `EXAMPLES-customer_general.md` 写回「✗ 应调 human_handoff」 |
| `test_prompt_surfaces_do_not_point_at_the_retired_tool`（内联） | 在 `CUSTOMER_GENERAL_SYSTEM_PROMPT` 写回「复杂投诉 → 用 human_handoff」 |
| `test_model_facing_guidance_does_not_point_at_the_retired_tool` | 把 `app/core/fallback.py` 的 suggestion 写回「C 端可用 human_handoff 转人工」 |
| `TestGuardIsNotVacuous` | 注入夹具：植入绑定/处方必须报出；**合法文案必须不报**（负例） |

## 为什么是**纯静态**（不 import 后端 app 包）

本文件跑在 CI 的 `ci workflow helper unit tests` job 里，该 job 只 `pip install pytest pyyaml`
（见 `.github/workflows/pr-check.yml`）—— **没有** pydantic/langchain 等后端依赖。
运行时行为（默认注册表里确实没有该工具、skill 工具集确实不含它）由
`backend/ai-agent-service/tests/test_tools_registry.py` /
`tests/test_skill_config_registry.py` 的行为用例覆盖。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = REPO_ROOT / "backend" / "ai-agent-service"
APP_DIR = SERVICE_ROOT / "app"
SKILLS_DIR = APP_DIR / "graph" / "skills"
EXECUTION_DIR = SKILLS_DIR / "execution"
REF_DIR = SKILLS_DIR / "references"
REGISTRY_PY = APP_DIR / "tools" / "registry.py"
FACADE_PY = APP_DIR / "tools" / "__init__.py"
TOOL_FILE = APP_DIR / "tools" / "human_handoff.py"
BASE_SKILL_PY = SKILLS_DIR / "base_skill.py"
INTENT_CONFIG_PY = APP_DIR / "router" / "intent_config.py"
#: **用户可见的"主动建议"文案载体**（handoff_offer 节点：卡片标题/选项 + 安抚文案）。
#: 该文件里的字符串字面量**会直接发给顾客**（SSE text 事件 + interactive 卡片）⇒
#: 退场后不得再出现"邀约人工转接"的措辞（详见 test_offer_copy_does_not_invite_a_handoff）。
OFFER_NODE_PY = APP_DIR / "graph" / "handoff_offer.py"

#: 「邀约/指向人工转接」的措辞（**只用于这份用户可见文案**，不扫全仓中文措辞）。
#: 为什么这三条而不是更宽的词表：它们是**邀约形态**（"为您转接"/"转人工"/"人工专员跟进"）；
#: 诚实文案用的是另一套措辞（"系统已无人工转接通道"）—— 后者**不含**下列任何一条
#: （见负例 `test_detector_quiet_on_honest_no_channel_wording`）。
HANDOFF_INVITE_PHRASES = ("转人工", "转接人工", "人工客服专员", "为您转接", "帮您转接")

# 注册表真值解析器**复用** `test_l0_reachability_guards.registered_tools()`（A13 守卫的
# 单一实现）—— 不复制平行实现（复制 = 双源漂移：改了一处口径另一处照样绿）。
# 该函数返回 `{tool_name: is_write}`（AST 反解 registry.py → 工具模块 → `name = "..."`）。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_l0_reachability_guards import registered_tools as _registered_tool_table  # noqa: E402


def registered_tool_names() -> set[str]:
    """默认注册表里的**工具名**（不是类名）—— 转发 A13 守卫的解析器，并自证非空。"""
    table = _registered_tool_table()
    assert table, "注册表 AST 解析器返回空表 —— 判据会空转（fail-closed）"
    return set(table)

#: 退场工具名 —— **判据的唯一锚点**（不扫中文措辞，见模块 docstring）。
RETIRED_TOOL = "human_handoff"
RETIRED_TOOL_CLASS = "HumanHandoffTool"
#: 同一件事的三种写法都算「指向该工具」（改写成 `human-handoff` 端点名同样是出口）。
RETIRED_ALIASES = (RETIRED_TOOL, RETIRED_TOOL_CLASS, "human-handoff")

#: **模型/用户可见的处方文案**所在的文件（工具名出现在这些文件的字符串字面量里 =
#: 一个按不动的出口被写给了模型）。清单**显式登记**（不 glob 全 app/）：这三处的
#: 字符串会进 ToolResult.message/suggestion、进 direct_reply、进兜底话术，
#: 其余文件的字面量（日志前缀、错误码、SQL、配置键）不面向模型。
MODEL_FACING_GUIDANCE_FILES = (
    APP_DIR / "core" / "fallback.py",                 # 熔断/降级 suggestion
    APP_DIR / "tools" / "validate_input.py",          # 校验失败 suggestion
    APP_DIR / "graph" / "clarify_guard.py",           # 澄清兜底话术（direct_reply）
    APP_DIR / "agents" / "agents" / "xiaobu.py",      # capabilities 直接回复
)

#: 内联 prompt 的**绑定名/关键字名**特征（prompt 文本在源码里的落脚点）。
_PROMPT_BINDING_RE = re.compile(r"PROMPT")
_PROMPT_KWARG_NAMES = frozenset({
    "xiaobu_prompt", "mibao_prompt", "system_prompt", "system_prompts",
    "inline_prompt", "prompt",
})


def _module_ast(path: Path) -> ast.Module:
    """读源码 AST；文件缺失即**报错**（fail-closed，不给"扫不到就通过"留口子）。"""
    assert path.is_file(), f"L0 守卫的被扫目标不存在：{path}（fail-closed，不静默跳过）"
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def skill_modules() -> list[Path]:
    """`app/graph/skills/**.py`（含搬迁家族 `execution/`）—— 与既有守卫同一口径。"""
    files = sorted(SKILLS_DIR.glob("*.py")) + sorted(EXECUTION_DIR.glob("*.py"))
    assert files, f"{SKILLS_DIR} 下解析出 0 个 skill 模块 —— 判据会空转（fail-closed）"
    return files


# ──────────────────────────────────────────────────────────────────────────────
# 判据内核（纯函数：供注入式红证驱动，与被测真值解耦）
# ──────────────────────────────────────────────────────────────────────────────


def mentions_retired(text: str) -> bool:
    """文本是否**指向**退场工具（三种写法任一，词边界匹配）。

    纯函数：注入式红证/负例都驱动它（见 `TestGuardIsNotVacuous`）。
    """
    for alias in RETIRED_ALIASES:
        if re.search(r"(?<![A-Za-z0-9_])" + re.escape(alias) + r"(?![A-Za-z0-9_])", text):
            return True
    return False


def invites_handoff(text: str) -> bool:
    """用户可见文案是否在**邀约/指向人工转接**（纯函数，供注入式红证/负例驱动）。

    只用于 `handoff_offer.py` 这类"用户可见文案载体"——**不扫全仓中文措辞**：
    诚实文案（"系统已无人工转接通道，我继续帮您处理"）不含下表中的任何短语。
    """
    return any(p in str(text) for p in HANDOFF_INVITE_PHRASES)


def _literal_tool_names(value: ast.AST) -> list[str] | None:
    """从字面量容器解析工具名；**非字面量返回 `None`**（调用方决定是否 fail-closed）。

    接受：`[...]` / `(...)` / `{...}` / `frozenset({...})`（`SMS_GATED_WRITE_TOOLS` 的形态）。
    """
    if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
        container = value.elts
    elif (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
          and value.func.id in {"frozenset", "set", "tuple", "list"} and len(value.args) == 1):
        inner = value.args[0]
        if not isinstance(inner, (ast.List, ast.Tuple, ast.Set)):
            return None
        container = inner.elts
    else:
        return None
    names: list[str] = []
    for el in container:
        if not (isinstance(el, ast.Constant) and isinstance(el.value, str)):
            return None      # 含变量/拼接 ⇒ 不是字面量（交给调用方 fail-closed）
        names.append(el.value)
    return names


def module_tool_constants(tree: ast.Module) -> dict[str, list[str]]:
    """模块级 `*_TOOLS` 常量 → `{常量名: [工具名]}`（纯静态）。

    非字面量写法（`X_TOOLS = BASE + [...]`）会让判据看不见真实工具集 ⇒ **fail-closed 报错**
    （"解析不到 ≠ 没违规"，同 `test_l0_reachability_guards` 的口径）。
    """
    out: dict[str, list[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if not targets or not targets[0].endswith("_TOOLS"):
            continue
        names = _literal_tool_names(node.value)
        if names is None:
            raise AssertionError(
                f"`{targets[0]}` 不是字面量容器（{ast.dump(node.value)[:60]}）"
                f"—— 工具集无法反解，宁可红（fail-closed）"
            )
        out[targets[0]] = names
    return out


def bound_tool_constants(path: Path) -> dict[str, list[str]]:
    """该 skill 模块**实际绑定**的工具集：`{「模块::常量」: [工具名]}`。

    真值 = `tool_names=` 实参解析出的常量（那才是"这个 skill 绑了什么"）。
    **不**扫未被绑定的 `*_TOOLS`（守卫表如 `SMS_GATED_WRITE_TOOLS` 不是模型可达面）。

    fail-closed 三档：
      · 大写下划线名（模块常量形态）指不到声明 ⇒ 报错；
      · 声明了 `*_TOOLS` 却一个绑定都没解析到 ⇒ 报错（整 skill 被漏掉 = 判据静默缩射程）；
      · 其他形态（关键字内的函数形参透传，如 `skill_config.py` 的 `tool_names=tool_names`）⇒ 跳过。
    """
    tree = _module_ast(path)
    consts = module_tool_constants(tree)
    out: dict[str, list[str]] = {}
    has_site = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg != "tool_names":
                continue
            has_site = True
            value = kw.value
            if isinstance(value, ast.Name) and value.id in consts:
                out[f"{path.name}::{value.id}"] = consts[value.id]
            elif isinstance(value, ast.Name) and not re.match(r"^[A-Z][A-Z0-9_]*$", value.id):
                continue          # 形参透传（`tool_names=tool_names`）—— 非声明点
            elif isinstance(value, ast.Name):
                raise AssertionError(
                    f"{path.name}: `tool_names={value.id}` 指不到模块级常量"
                    f"（本模块声明的 `*_TOOLS` = {sorted(consts)}）—— fail-closed"
                )
            else:
                names = _literal_tool_names(value)
                if names is None:
                    raise AssertionError(
                        f"{path.name}: `tool_names=` 的实参既不是常量名也不是字面量容器"
                        f"（{ast.dump(value)[:60]}）—— 判据会漏掉这个 skill（fail-closed）"
                    )
                out[f"{path.name}::<inline>"] = names
    if consts and has_site and not out:
        raise AssertionError(
            f"{path.name} 声明了 `*_TOOLS`（{sorted(consts)}）且带 `tool_names=` 调用点，"
            f"却解析不出任何绑定 —— 整个 skill 被漏掉，判据射程被无声缩小（fail-closed）"
        )
    return out


def skill_tool_bindings() -> dict[str, list[str]]:
    """全量 skill 工具集：`{「模块::常量」: [工具名]}`。"""
    out: dict[str, list[str]] = {}
    for path in skill_modules():
        out.update(bound_tool_constants(path))
    assert out, "未解析出任何 skill 工具集 —— 判据空转（fail-closed）"
    return out


def registered_tool_classes(path: Path = REGISTRY_PY) -> list[str]:
    """`create_default_registry()` 里**活的** `registry.register(<Class>())` 类名。

    注释掉的注册不算（AST 只看活代码）—— 这正是"退场"的实现形态
    （`# registry.register(HumanHandoffTool())`）。
    """
    tree = _module_ast(path)
    classes: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "register" or not node.args:
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
            classes.append(arg.func.id)
    assert classes, f"{path} 里解析出 0 个 `registry.register(...)` —— 解析链断了（fail-closed）"
    return classes


def facade_names(path: Path = FACADE_PY) -> set[str]:
    """门面（`app/tools/__init__.py`）暴露的类名：活 import + `__all__` 字面量。"""
    tree = _module_ast(path)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names |= {a.name for a in node.names}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            continue
        if isinstance(node.value, (ast.List, ast.Tuple)):
            names |= {
                el.value for el in node.value.elts
                if isinstance(el, ast.Constant) and isinstance(el.value, str)
            }
    assert names, f"{path} 解析出 0 个导出名 —— fail-closed"
    return names


def prompt_reference_files(ref_dir: Path = REF_DIR) -> list[Path]:
    """**模型可见的参考层文案**：`references/**` 全部 `.md`（递归）。

    为什么扫整棵树而不是"只扫加载器点名的文件"：加载器（`_build_system_prompt`）
    只从**单一目录** `_ref_dir` 读三层（`_REQUIRED_PROMPT_FILES` / `prompts/<skill>.md`
    / `EXAMPLES-<skill>.md`）⇒ 整棵树是注入面的**超集**。
    超集在这里是**优点**：漏扫一个文件就是漏掉一个静默出口，多扫只会多拦。
    （加载器仍从 `_ref_dir` 读这件事由 `test_prompt_reference_tree_is_the_loader_source` 锁。）
    """
    files = sorted(ref_dir.rglob("*.md"))
    assert files, f"{ref_dir} 下解析出 0 个参考文案文件 —— 判据会空转（fail-closed）"
    return files


def prompt_literal_strings(path: Path) -> list[tuple[int, str]]:
    """skill 模块里**会进 prompt 的字符串字面量**：`[(行号, 文本)]`。

    覆盖面（全部是"prompt 文本在源码里的落脚点"）：
      ① 模块级 `*PROMPT*` 常量（`CUSTOMER_X_SYSTEM_PROMPT` 等）；
      ② `xiaobu_prompt=` / `system_prompts=` / `system_prompt=` 等关键字的字符串值；
      ③ `system_prompts={"xiaobu": <字面量>}` 的字典值。

    **不含**注释、不含守卫代码里比对工具名的字面量（见模块 docstring 的口径）。
    """
    tree = _module_ast(path)
    out: list[tuple[int, str]] = []

    def add(node: ast.AST) -> None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append((getattr(node, "lineno", 0), node.value))

    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if targets and _PROMPT_BINDING_RE.search(targets[0]):
                add(node.value)
        if isinstance(node, ast.AnnAssign):
            tgt = node.target
            if isinstance(tgt, ast.Name) and _PROMPT_BINDING_RE.search(tgt.id):
                add(node.value)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg not in _PROMPT_KWARG_NAMES:
                continue
            if isinstance(kw.value, ast.Dict):
                for v in kw.value.values:
                    add(v)
            else:
                add(kw.value)
    return out


def guidance_literal_strings(path: Path) -> list[tuple[int, str]]:
    """模型/用户可见处方文件里的**全部字符串字面量**：`[(行号, 文本)]`。

    这些文件的字面量就是会被回给模型/用户的文本（message / suggestion / 直接回复）。
    ⚠️ **docstring 也算字面量**（它同样是源码里的字符串）：想留档历史就写**注释**
    —— 那正是本判据想要的区分（注释不会进模型的上下文）。
    """
    tree = _module_ast(path)
    return [
        (getattr(n, "lineno", 0), n.value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


def stray_mentions(items, label: str) -> list[str]:
    """`[(行号, 文本)]` 里指向退场工具的条目 → `["label:行号"]`（纯函数，供红证驱动）。"""
    return [f"{label}:{lineno}" for lineno, text in items if mentions_retired(text)]


def intent_tool_hints(tree: ast.Module) -> set[str]:
    """`INTENT_TOOL_MAP` 里的全部工具名字符串（纯静态）。

    fail-closed：常量不存在 / 不是字面量字典 / 解析出 0 个名字 ⇒ 报错，不静默返回空集
    （空集会让"没有幽灵工具"退化成恒真空判据）。
    """
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]          # `X: dict[...] = {...}` 的形态
            value = node.value
        else:
            continue
        if "INTENT_TOOL_MAP" not in targets:
            continue
        if not isinstance(value, ast.Dict):
            raise AssertionError("`INTENT_TOOL_MAP` 不再是字面量字典 —— 判据无法反解，宁可红")
        names: set[str] = set()
        for v in value.values:
            if not isinstance(v, (ast.List, ast.Tuple)):
                raise AssertionError(
                    f"`INTENT_TOOL_MAP` 的某个值是 {ast.dump(v)[:50]}（非字面量列表）"
                    f"—— 判据会漏项（fail-closed）"
                )
            for el in v.elts:
                if not (isinstance(el, ast.Constant) and isinstance(el.value, str)):
                    raise AssertionError("`INTENT_TOOL_MAP` 的值里有非字符串元素 —— fail-closed")
                names.add(el.value)
        return names
    raise AssertionError(f"{INTENT_CONFIG_PY} 里找不到 `INTENT_TOOL_MAP` —— 判据真相源消失")


# ──────────────────────────────────────────────────────────────────────────────
# 判据 ①：工具集面
# ──────────────────────────────────────────────────────────────────────────────


def test_no_skill_binds_the_retired_tool():
    """**核心不变式**：任何 skill 的 `tool_names` 都不含退场工具（加回去 ⇒ 必红）。

    反例输入：把 `"human_handoff"` 加回 `CUSTOMER_GENERAL_TOOLS`（app/graph/skills/
    customer_general_skill.py）⇒ 必红。
    """
    bindings = skill_tool_bindings()
    offenders = sorted(k for k, names in bindings.items() if RETIRED_TOOL in names)
    assert not offenders, (
        f"以下 skill 工具集重新绑定了已退场工具 `{RETIRED_TOOL}`：{offenders}\n"
        f"→ 用户裁定 2026-09-19：「不应该存在 human_handoff 这种东西，以后全是 AI 来判断」"
        f"—— 该工具已不在默认注册表（`create_default_registry`），绑定它只会让模型\n"
        f"   拿到一个 `Tool not found` 的出口（或又把它当兜底手段写进话术）。\n"
        f"→ 正确做法：让本 skill 自己受理（查清事实/落成工单/如实说明能力边界）。"
    )
    # 上界自证：判据确实扫到了足够多的 skill（否则"没有绑定"可能是"没扫到"）
    assert len(bindings) >= 10, (
        f"只解析出 {len(bindings)} 个 skill 工具集（{sorted(bindings)}）—— "
        f"解析口径疑似失效，判据可能恒真"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 判据 ②③：注册表面 + 门面面
# ──────────────────────────────────────────────────────────────────────────────


def test_registry_does_not_register_the_retired_tool():
    """默认注册表不得注册该工具类（取消注释注册行 ⇒ 必红）。"""
    classes = registered_tool_classes()
    assert RETIRED_TOOL_CLASS not in classes, (
        f"`create_default_registry()` 又把 `{RETIRED_TOOL_CLASS}` 注册回来了\n"
        f"→ 注册表是「模型能看见什么工具」的**唯一**开关（`get_schema()` 由它派生）⇒ "
        f"等于撤销本次退场。工具类文件保留不代表要注册它。"
    )
    assert len(classes) >= 30, f"只解析出 {len(classes)} 个注册类 —— 解析疑似失效（判据会空转）"


def test_facade_does_not_export_the_retired_tool():
    """门面（`app/tools/__init__.py`）不得导出该工具类（与注册表同口径，防两清单漂移）。"""
    names = facade_names()
    assert RETIRED_TOOL_CLASS not in names, (
        f"`app/tools/__init__.py` 又导出了 `{RETIRED_TOOL_CLASS}`\n"
        f"→ 门面清单的契约是「与 `create_default_registry()` 注册的类一致」"
        f"（`tests/test_tools_registry.py::TestToolsFacadeCompleteness`）；\n"
        f"   退场后它既不该注册、也不该导出。"
    )


def test_tool_class_file_is_kept_with_a_retirement_notice():
    """阶段一**保留**工具类文件，但文件头必须写明"已下线（模型不可达）"。

    这是"保留 vs 删除"的**显式表态**判据：文件在时的唯一合法形态 = 带退场说明
    （否则下一个人会以为它还在服役，照着它写 prompt/绑定）。
    阶段二完全删除时，本用例随文件一起删（见汇报的阶段二清单）。
    """
    assert TOOL_FILE.is_file(), (
        f"阶段一**不删**工具类文件（{TOOL_FILE.name}）——只下线模型可达性；"
        f"完全删除属阶段二（DB/前端/用例/文档同批），单独删文件会让直测类单测与\n"
        f"存量数据读写路径失去对象。"
    )
    head = TOOL_FILE.read_text(encoding="utf-8")[:1200]
    assert "已按用户裁定下线" in head and "模型不可达" in head, (
        f"{TOOL_FILE.name} 的文件头没有写明退场状态（缺「已按用户裁定下线」/「模型不可达」）\n"
        f"→ 「保留文件」必须配一句显式表态，否则读者无法区分"
        f"「还在服役」与「仅为兼容存量数据保留」。"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 判据 ④：prompt 面（模型可见文案不得指向退场工具）
# ──────────────────────────────────────────────────────────────────────────────


def test_prompt_reference_tree_is_the_loader_source():
    """自证：加载器确实只从 `references/` 读（否则本判据扫的树不等于注入面）。

    反例输入：把 `_build_system_prompt` 改成从别的目录读 ⇒ 必红（提示同步本判据）。
    """
    tree = _module_ast(BASE_SKILL_PY)
    anchors = [
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]
    assert any(a.endswith("references") for a in anchors), (
        "`base_skill.py` 里找不到 `references` 目录锚点 —— 参考层换目录了，"
        "本判据扫的树不再等于注入面（fail-closed，请同步）"
    )
    assert REF_DIR.is_dir(), f"参考目录不存在：{REF_DIR}"
    # 必需层清单也必须仍能被解析（它同样从 _ref_dir 读）
    required = [
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and n.value.endswith(".md")
    ]
    assert required, "`base_skill.py` 里解析不出任何 `.md` 相对路径 —— 加载器口径已变（fail-closed）"


def test_prompt_surfaces_do_not_point_at_the_retired_tool():
    """**模型可见文案不得出现退场工具名**（prompt 加回处方 ⇒ 必红）。

    覆盖：`references/**` 全部 `.md` + 各 skill 模块的 prompt 字面量。
    反例输入（两条中的任一条即可）：
      · `references/EXAMPLES-customer_general.md` 写回「❌ 应调 human_handoff」；
      · `CUSTOMER_GENERAL_SYSTEM_PROMPT` 写回「复杂投诉 → 用 human_handoff 转人工」。
    """
    offenders: list[str] = []

    ref_files = prompt_reference_files()
    for path in ref_files:
        text = path.read_text(encoding="utf-8")
        if mentions_retired(text):
            hits = [
                f"第 {i} 行" for i, line in enumerate(text.splitlines(), 1)
                if mentions_retired(line)
            ]
            offenders.append(f"{path.relative_to(REPO_ROOT)}（{', '.join(hits[:5])}）")

    literal_total = 0
    for path in skill_modules():
        literals = prompt_literal_strings(path)
        literal_total += len(literals)
        offenders += stray_mentions(literals, str(path.relative_to(REPO_ROOT)))

    assert not offenders, (
        f"以下模型可见文案仍在把模型导向已退场工具 `{RETIRED_TOOL}`：\n  "
        + "\n  ".join(offenders)
        + f"\n→ 工具已经调不到了，但 prompt 里写着它 = 模型会用自然语言承诺"
        f"「已为您转接人工」（假承诺），比一开始就说「我这边办不了」更伤。\n"
        f"→ 正确写法：如实说明系统已无人工转接通道，然后自己受理（不出现工具名）。"
    )
    # 上界自证：字面量解析确实扫到了东西（否则判据恒真）
    assert literal_total >= 10, (
        f"skill 模块的 prompt 字面量只解析出 {literal_total} 条 —— 解析口径疑似失效"
    )


def test_offer_copy_does_not_invite_a_handoff():
    """**用户可见的建议卡文案不得邀约人工转接**（把旧文案加回去 ⇒ 必红）。

    背景（2026-09-19 用户裁定「不应该存在 human_handoff 这种东西，以后全是 AI 来判断」的
    **追加收口**）：`handoff_offer` 节点的卡片**直接发给顾客**（SSE text + interactive 卡），
    它原先问「需要为您转接人工客服吗？」并给「👩‍💼 转人工客服」选项 —— 转人工能力退场后，
    这等于**用户可见面在邀约一个不存在的能力**（点下去只会得到"无人工通道"的诚实回答 =
    自相矛盾，本 PR 自己就留着一条"承诺做不到的事"）。
    处置：**只改文案与选项语义**（节点与卡片机制保留，子系统删除属阶段二）——
    「要不要转人工」→「要不要我把您的情况整理成售后工单跟进」= **继续受理**。

    判据锚 = **本文件的字符串字面量**（卡片标题/选项/安抚文案都在这里）：
    不得出现 `HANDOFF_INVITE_PHRASES`（邀约形态）。**不扫全仓中文措辞** ——
    诚实文案（"系统已无人工转接通道，我继续帮您处理"）不含这些短语（见负例）。

    反例输入：把 `_OFFER_OPTIONS` 的 label/value 改回 `"转人工客服"`（或把
    `_COMFORT_*` 写回「建议转人工客服专员为您处理」）⇒ 必红。
    """
    literals = guidance_literal_strings(OFFER_NODE_PY)
    offenders = [
        f"{OFFER_NODE_PY.relative_to(REPO_ROOT)}:{lineno} → {text[:60]!r}"
        for lineno, text in literals if invites_handoff(text)
    ]
    assert not offenders, (
        f"建议卡/安抚文案仍在**邀约人工转接**（该能力已退场，顾客点了只会得到"
        f"「无人工通道」的诚实回答 = 自相矛盾）：\n  " + "\n  ".join(offenders) + "\n"
        f"→ 正确形态：改成「继续受理」（如「要我把您的情况整理成售后工单跟进吗」），"
        f"选项 value 走 `rule_matcher` 的售后关键词，点下去真的进入受理链路。\n"
        f"→ 断言清单：{list(HANDOFF_INVITE_PHRASES)}"
    )
    # 上界自证：字面量解析确实扫到了这张卡的全部文案（否则判据恒真 = 空跑）
    assert len(literals) >= 8, (
        f"{OFFER_NODE_PY.name} 只解析出 {len(literals)} 条字面量 —— 解析口径疑似失效"
    )
    # 反向自证：**卡片确实还在、且仍承载"继续受理"出路**（防"直接删卡了事"通过判据）
    text = OFFER_NODE_PY.read_text(encoding="utf-8")
    assert "component" in text and "choice" in text, (
        "建议卡被删掉了 —— 本次口径是**只改文案与选项语义**（保留确定性节点与卡片机制，"
        "子系统删除属阶段二）；直接删卡会让这条判据变成空跑"
    )
    assert "售后工单" in text, (
        "卡片不再提供任何'继续受理'的出路（只是把邀约删掉了）—— 顾客侧会失去下一步"
    )


def test_intent_tool_hints_never_name_unreachable_tools():
    """`INTENT_TOOL_MAP`（给模型的工具提示表）里的工具名**必须真的可达**。

    这是同一病根的另一张表：`INTENT_TOOL_MAP[COMPLAINT]` 曾写着 `human_handoff` ——
    工具退场后，这张表仍在**给模型推荐一个拿不到的工具**（hint 进了
    `RouteDecision.tool_hint` → state），模型会照着去调 ⇒ `Tool not found`。
    唯一合法形态 = 表里的名字都在默认注册表里。

    已知且**显式登记**的例外：`knowledge_manage`（旧 RAG 写侧工具，`# [RAG 禁用]`
    起就不注册；知识管理在 admin-web 后台操作，不经 Agent —— 见 `tools/registry.py`
    的注释）。例外表**必须恰好**是它：再冒出新的幽灵名字即红（防"例外表变垃圾场"）。
    """
    unreachable_by_design = {"knowledge_manage"}
    tree = _module_ast(INTENT_CONFIG_PY)
    hinted = intent_tool_hints(tree)
    registered = set(registered_tool_names())
    ghosts = sorted(set(hinted) - registered - unreachable_by_design)

    assert hinted, "`INTENT_TOOL_MAP` 解析出 0 个工具名 —— 判据会空转（fail-closed）"
    assert not ghosts, (
        f"`INTENT_TOOL_MAP` 给模型推荐了 {len(ghosts)} 个**不可达**工具：{ghosts}\n"
        f"→ 判据：hint 里的名字必须 ∈ 默认注册表（或已显式登记的例外 "
        f"{sorted(unreachable_by_design)}）。\n"
        f"→ 修法：把退场工具从表里移除（值置空 `[]`），不要让模型照着 hint 去调一个"
        f"`Tool not found` 的工具。"
    )
    # 例外表自证：登记的名字必须**真的**仍不可达（否则例外是僵尸登记）
    stale_excuses = sorted(unreachable_by_design & registered)
    assert not stale_excuses, (
        f"例外表里的 {stale_excuses} 其实已经可达 —— 陈旧例外应删除"
    )


def test_model_facing_guidance_does_not_point_at_the_retired_tool():
    """运行时**处方文案**不得出现退场工具名（降级建议/校验建议/澄清话术/能力清单）。

    反例输入：把 `app/core/fallback.py` 的 suggestion 写回
    「需要人工介入时改走当前端可用的人工入口（C 端可用 human_handoff 转人工）」⇒ 必红。
    """
    offenders: list[str] = []
    total = 0
    for path in MODEL_FACING_GUIDANCE_FILES:
        literals = guidance_literal_strings(path)
        total += len(literals)
        offenders += stray_mentions(literals, str(path.relative_to(REPO_ROOT)))

    assert not offenders, (
        f"以下模型/用户可见的处方文案仍指向退场工具：\n  " + "\n  ".join(offenders) + "\n"
        f"→ suggestion / 直接回复是**模型下一步行动的依据**：写着它，模型就会"
        f"「把用户转人工」当成合法出路（哪怕工具根本调不到）。"
    )
    assert total >= 5, f"处方文案只解析出 {total} 条字面量 —— 解析疑似失效（判据会空转）"


# ──────────────────────────────────────────────────────────────────────────────
# 判据自身可红 + 不恒真（注入式夹具，含**负例**）
# ──────────────────────────────────────────────────────────────────────────────


class TestGuardIsNotVacuous:
    """:red_circle: **红证**（注入式）+ **负例**：判据必须能报出，也必须能不报。"""

    def test_detector_fires_on_an_instruction_that_points_at_the_tool(self):
        """**红证①**：把"改走该工具"的处方文案注入 ⇒ 必须报出。"""
        planted = (
            "需要人工介入时改走当前端可用的人工入口（C 端可用 human_handoff 转人工），"
            "否则建议用户稍后再试同一请求。"
        )
        assert mentions_retired(planted), "处方文案里的工具名没有被判据看见 —— 判据失效"

    def test_detector_fires_on_every_alias(self):
        """**红证②**：三种写法（工具名/类名/端点名）都必须报出（改个写法绕过判据 = 假绿）。"""
        for alias in RETIRED_ALIASES:
            assert mentions_retired(f"请调用 {alias} 处理"), f"别名漏判：{alias}"

    def test_detector_fires_on_every_handoff_invite_phrase(self):
        """**红证③（建议卡）**：每一种"邀约转人工"措辞都必须被看见（漏一种 = 假绿）。"""
        for phrase in HANDOFF_INVITE_PHRASES:
            assert invites_handoff(f"这个问题比较特殊，{phrase}吗？"), f"邀约措辞漏判：{phrase}"

    def test_offer_red_proof_old_copy_is_reported(self):
        """**红证④（建议卡）**：把**旧卡片文案原文**喂进判据 ⇒ 必须报出。

        旧文案（origin/main 的 `_OFFER_TITLE`/`_OFFER_OPTIONS`/`_COMFORT_DEFAULT`）：
        「这个问题比较特殊，需要为您转接人工客服吗？」/「👩‍💼 转人工客服」/
        「建议转人工客服专员为您处理。」
        """
        old_copy = [
            "这个问题比较特殊，需要为您转接人工客服吗？",
            "👩‍💼 转人工客服",
            "建议转人工客服专员为您处理。",
            "有些情况由人工客服专员跟进会更高效。",
        ]
        missed = [t for t in old_copy if not invites_handoff(t)]
        assert not missed, f"旧建议卡文案没被判据看见（判据失效）：{missed}"

    def test_detector_quiet_on_honest_no_channel_wording(self):
        """**负例（建议卡）**：**诚实文案**不得被报 —— 判据不能扫成"见人工二字就红"。

        「如实说明系统已无人工转接通道，我继续帮您处理」是本退场改造**新增**的必需文案；
        若判据扫的是"人工"这类措辞，它必红 ⇒ 判据只能靠豁免活着（= 空判据）。
        """
        honest = [
            "该系统已无人工转接通道，我继续帮您处理可以吗？",
            "抱歉，我没法把您转接给人工，但我可以现在就把问题整理成售后工单跟进。",
            "要我把您的情况整理成售后工单跟进吗？",
            "继续咨询小布",
        ]
        reported = [t for t in honest if invites_handoff(t)]
        assert not reported, (
            f"诚实文案被误报 → 判据在扫「人工」这类措辞（会把必需文案判红）：{reported}"
        )

    def test_detector_stays_quiet_on_honest_unavailable_wording(self):
        """**负例**：合法的「如实告知该功能暂时不可用」文案（不含工具名）⇒ **不得报**。

        这条防的是"判据扫中文措辞"的坏形态：退场后 prompt **必须**继续写
        「顾客说转人工时，如实说明没有人工转接通道，然后自己受理」—— 那是本次新增的
        **必需**文案，扫「人工」二字会让它必红，判据只能靠豁免活着（= 空判据）。
        """
        legit = (
            "请把 message 如实告知用户「该功能暂时不可用」，并给出可执行的替代路径 —— "
            "建议用户稍后再试同一请求，或改用当前端确实可用的其它功能入口。"
            "顾客说「转人工/找人工」时：如实说明系统已无人工转接通道，然后自己继续受理。"
        )
        assert not mentions_retired(legit), (
            "合法文案（不含工具名）被误报 —— 判据在扫中文措辞（会把必需文案判红）"
        )

    def test_tool_list_parser_reports_a_planted_binding(self, tmp_path):
        """**解析器自证**：植入"绑定了该工具"的 skill 源码 ⇒ 工具集解析必须看得见它。"""
        planted = tmp_path / "planted_skill.py"
        planted.write_text(
            'PLANTED_TOOLS = [\n    "order_create",\n    "human_handoff",\n]\n'
            'CONFIG = build(name="planted", tool_names=PLANTED_TOOLS)\n',
            encoding="utf-8")
        consts = bound_tool_constants(planted)
        key = next((k for k in consts if k.endswith("PLANTED_TOOLS")), None)
        assert key, f"植入的绑定没有被工具集解析看见（解析出的键 = {sorted(consts)}）"
        assert RETIRED_TOOL in consts[key], "植入的绑定没有被工具集解析看见"

    def test_tool_list_parser_is_fail_closed_on_non_literal(self, tmp_path):
        """**fail-closed**：工具集写成非字面量（拼接/变量）⇒ 报错，不静默返回空。"""
        planted = tmp_path / "weird_skill.py"
        planted.write_text(
            'BASE = ["order_create"]\nWEIRD_TOOLS = BASE + ["human_handoff"]\n',
            encoding="utf-8")
        try:
            bound_tool_constants(planted)
        except AssertionError:
            return
        raise AssertionError(
            "非字面量工具集被静默跳过 —— 「解析不到 ≠ 没违规」，判据会变成空跑"
        )

    def test_prompt_literal_collector_sees_a_planted_prompt(self, tmp_path):
        """**prompt 面自证**：内联 prompt 里写回该工具 ⇒ 采集器必须看得见。"""
        planted = tmp_path / "planted_general_skill.py"
        planted.write_text(
            'X_SYSTEM_PROMPT = """你是小布。\n复杂投诉 → 用 human_handoff 转人工。\n"""\n'
            'CONFIG = build(system_prompts={"xiaobu": X_SYSTEM_PROMPT}, xiaobu_prompt="备用")\n',
            encoding="utf-8")
        hits = stray_mentions(prompt_literal_strings(planted), "planted")
        assert hits, "植入的内联 prompt 处方没有被采集器看见 —— prompt 面判据失效"

    def test_guidance_collector_sees_a_planted_suggestion(self, tmp_path):
        """**处方面自证**：suggestion 里写回该工具 ⇒ 采集器必须看得见。"""
        planted = tmp_path / "planted_fallback.py"
        planted.write_text(
            'def f():\n'
            '    return ToolResult(suggestion="C 端可用 human_handoff 转人工")\n',
            encoding="utf-8")
        hits = stray_mentions(guidance_literal_strings(planted), "planted")
        assert hits, "植入的 suggestion 处方没有被采集器看见 —— 处方面判据失效"

    def test_real_registry_and_skills_are_the_guard_subject(self):
        """**真值自证**：判据扫的是真仓库文件，且真值面非空（不是对着 tmp 空转）。"""
        assert REGISTRY_PY.is_file() and FACADE_PY.is_file() and BASE_SKILL_PY.is_file()
        assert len(prompt_reference_files()) >= 20, (
            "参考层文案文件数异常偏少 —— 扫描面疑似被收窄（判据射程被无声缩小）"
        )