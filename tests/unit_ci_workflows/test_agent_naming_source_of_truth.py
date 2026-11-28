# case_ids: AG-014
"""Agent 内部 id ↔ 产品名的**单一事实源**元守卫（issue #9301）。

## 病（一类缺陷，不是一个缺陷）

内部 id 与产品名**本来就不一一对应**，而没有任何东西记录「为什么」：

| 内部 id | 产品名 | 侧 | 形态 |
|---|---|---|---|
| `mibao` | 黄金策 | B 端经营侧 | agent |
| `xiaobu` | 智能客服 | C 端 | 技术能力（**无对外 agent 形态**） |

两条都是历史遗留（来历写在 `backend/ai-agent-service/app/agents/naming.py`）。没有守卫时，
下一个人看到 `name="xiaobu"` / `display_name="智能客服"` 很可能「顺手改回对齐」—— 改的是路由键 /
会话状态键 / 评测用例 `persona` 的同一批标识，**而没有任何东西会当场变红**。

## 判据（三条，逐条可红）

| # | 判什么 | 怎么红 |
|---|---|---|
| 1 | 每个 agent 声明的 `name` / `display_name` / `persona` 与 `AGENT_NAMING` **逐字一致**；`DEFAULT_BOT_NAME` 与映射表一致 | 改一侧另一侧不变 ⇒ 具名打出 `文件:行 + 两个值` |
| 2 | C 端身份面（`xiaobu.py` 的**全部字符串**，含 docstring / `direct_replies`）+ C 端 prompt 面（`identity-xiaobu.md`、`customer_*_skill.py` 的 system prompt、`EXAMPLES-customer_*.md`）**不得出现「米宝」** | 出现即红，点名 `文件:行` |
| 3 | 映射表每条都带 `note`，且说清**为什么 id 与产品名不同**（`side` / `form` 必须合法） | 缺 note / note 太短 / 枚举外 ⇒ 红 |

## 红证（读数见 PR body）

- `xiaobu.py` 的 `display_name` 改回「米宝」⇒ 判据 1 + 判据 2 具名红；
- `naming.py` 的 `xiaobu.display_name` 改成「米宝」⇒ 判据 1 具名红（判据 2 仍绿 —— 两侧是**独立真值**，
  不是同源复制；否则判据 1 会退化成恒真断言）。

## 边界（照实登记）

- 判据 1 读**源码 AST**（`ast.parse`），不 import `app.*`：`app.agents.__init__` 会拉起
  LangChain / LangGraph 依赖链，CI 的 helper 腿没有那些依赖；「读源码」也正是本守卫要钉的对象。
  ⇒ 代价是它只认 `AgentConfig(...)` 的关键字字面量；写成变量 / 拼接 ⇒ 判据 **fail-loud**（不静默通过）。
- 判据 2 的 prompt 面是**静态面**；模型真正拿到的组装 prompt 由
  `backend/ai-agent-service/tests/test_persona_identity_split.py` 的行为判据覆盖 —— 两条互补。
- 不在面内：B 端 prompt 里对 C 端的旁称（`references/EXAMPLES-aftersales.md` 等）、前端文案、
  存量 DB 数据（边界见 issue #9301）。
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_AGENT = REPO_ROOT / "backend" / "ai-agent-service"
NAMING_PATH = AI_AGENT / "app" / "agents" / "naming.py"
AGENT_DECL_DIR = AI_AGENT / "app" / "agents" / "agents"
XIAOBU_PATH = AGENT_DECL_DIR / "xiaobu.py"
SKILLS_DIR = AI_AGENT / "app" / "graph" / "skills"

#: C 端（顾客侧）自 2026-11-28 起统一称「智能客服」，不得再出现旧人格名。
BANNED_C_END_NAME = "米宝"

#: C 端 prompt 面：身份层 + 各 skill 的 few-shot 示例 + 域内 prompt 片段。
C_END_PROMPT_MD = (
    [SKILLS_DIR / "references" / "base" / "identity-xiaobu.md"]
    + sorted((SKILLS_DIR / "references").glob("EXAMPLES-customer*.md"))
    + sorted((SKILLS_DIR / "references" / "prompts").glob("customer*.md"))
)

#: C 端 skill 的 system prompt 载体。
C_END_SKILL_FILES = tuple(sorted(SKILLS_DIR.glob("customer_*_skill.py")))


def _module_tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _agent_declaration(path: Path):
    """返回 `(常量名, {kwarg: (值, 行号)})`；文件里没有 `AgentConfig(...)` 则返回 None。"""
    for node in _module_tree(path).body:
        if not (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            continue
        call = node.value
        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "AgentConfig"
        ):
            continue
        kwargs = {}
        for kw in call.keywords:
            if kw.arg not in {"name", "display_name", "persona"}:
                continue
            try:
                value = ast.literal_eval(kw.value)
            except ValueError as exc:  # 非字面量：读不到真值就别装成通过
                raise AssertionError(
                    f"{path}:{kw.value.lineno} 的 `{kw.arg}` 不是字面量（{exc}）—— "
                    "判据读不到真值，拒绝静默通过"
                ) from exc
            kwargs[kw.arg] = (value, kw.value.lineno)
        return node.targets[0].id, kwargs
    return None


def _module_str_constant(path: Path, const_name: str):
    """模块级 `NAME = "..."` 的字面量 → `(值, 行号)`；缺失 / 非字面量 ⇒ 具名报错。"""
    for node in _module_tree(path).body:
        if not (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == const_name
        ):
            continue
        try:
            return ast.literal_eval(node.value), node.value.lineno
        except ValueError as exc:
            raise AssertionError(
                f"{path}:{node.value.lineno} 的 `{const_name}` 不是字面量（{exc}）"
            ) from exc
    raise AssertionError(f"{path}: 没找到模块级常量 `{const_name}`")


def _naming_table() -> dict:
    for node in _module_tree(NAMING_PATH).body:
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "AGENT_NAMING"
                for target in node.targets
            )
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(
        f"{NAMING_PATH}: 没找到 `AGENT_NAMING` —— 单一事实源不存在，判据无对象可判"
    )


def _string_hits(path: Path, needle: str):
    """模块里**所有**字符串常量（含 docstring / 隐式拼接）中的命中 → `[(行号, 片段)]`。"""
    hits = []
    for node in ast.walk(_module_tree(path)):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        value = node.value
        index = value.find(needle)
        while index >= 0:
            line = node.lineno + value[:index].count("\n")
            hits.append((line, value.splitlines()[value[:index].count("\n")].strip()[:80]))
            index = value.find(needle, index + len(needle))
    return hits


def _line_hits(path: Path, needle: str):
    """纯文本（Markdown）里按行命中 → `[(行号, 片段)]`。"""
    hits = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if needle in line:
            hits.append((line_no, line.strip()[:80]))
    return hits


def test_agent_declarations_match_the_naming_table():
    """判据 1：`name` / `display_name` / `persona` 必须与映射表逐字一致（两侧独立写）。"""
    table = _naming_table()

    declarations = {}
    for path in sorted(AGENT_DECL_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        declaration = _agent_declaration(path)
        if declaration is None:
            continue
        declarations[path] = declaration

    declared_ids = {kwargs["name"][0] for _, kwargs in declarations.values()}
    assert {"mibao", "xiaobu"} <= declared_ids, (
        f"扫面里没有找到声明的 agent（扫到 {sorted(declared_ids)}）—— 路径写错，判据等于没跑"
    )

    for path, (_, kwargs) in declarations.items():
        name, name_line = kwargs["name"]
        display_name, display_line = kwargs["display_name"]
        persona, persona_line = kwargs["persona"]

        assert name in table, (
            f"{path}:{name_line} 的 name={name!r} 不在 {NAMING_PATH.name} 的 AGENT_NAMING 里 "
            "—— 新 agent 必须先登记 id ↔ 产品名映射（否则「为什么不同」会再次失传）"
        )
        expected = table[name]["display_name"]
        assert display_name == expected, (
            f"{path}:{display_line} 的 display_name={display_name!r} 与 "
            f"{NAMING_PATH.name} 的 AGENT_NAMING[{name!r}]['display_name']={expected!r} 不一致 "
            "—— 改一侧必须同批改另一侧"
        )
        assert persona == name, (
            f"{path}:{persona_line} 的 persona={persona!r} 与 name={name!r} 不同 —— "
            "persona 是 system prompt 的选择键，与 name 不同会让两侧身份层串线（先确认再放宽本判据）"
        )

    assert set(table) == declared_ids, (
        f"映射表与代码声明的 agent 集合不一致：表里 {sorted(set(table) - declared_ids)} "
        f"在代码里没有声明，代码里 {sorted(declared_ids - set(table))} 在表里没有登记"
    )

    bot_name, bot_line = _module_str_constant(XIAOBU_PATH, "DEFAULT_BOT_NAME")
    assert bot_name == table["xiaobu"]["display_name"], (
        f"{XIAOBU_PATH}:{bot_line} 的 DEFAULT_BOT_NAME={bot_name!r} 与映射表的 "
        f"xiaobu display_name={table['xiaobu']['display_name']!r} 不一致 "
        "—— C 端兜底默认名必须与产品名同源（商家自定义能力不受影响）"
    )


def test_c_end_identity_surface_never_uses_the_old_persona_name():
    """判据 2：C 端身份面与 C 端 prompt 面不得再出现旧人格名（出现即红，点名文件:行）。"""
    assert C_END_PROMPT_MD and C_END_SKILL_FILES, (
        "扫面为空 —— 路径写错，判据等于没跑"
    )

    violations = []
    for path, hits in (
        (XIAOBU_PATH, _string_hits(XIAOBU_PATH, BANNED_C_END_NAME)),
        *((path, _line_hits(path, BANNED_C_END_NAME)) for path in C_END_PROMPT_MD),
        *((path, _string_hits(path, BANNED_C_END_NAME)) for path in C_END_SKILL_FILES),
    ):
        rel = path.relative_to(REPO_ROOT)
        violations.extend(f"{rel}:{line} → {snippet}" for line, snippet in hits)

    assert violations == [], (
        "C 端仍在自称「米宝」（用户 2026-11-28 裁定：C 端只提供技术能力，统一称「智能客服」，"
        "不拟人、不自称名字）：\n  " + "\n  ".join(violations)
    )


def test_every_naming_entry_explains_why_id_differs():
    """判据 3：映射表每条都要写清**为什么 id 与产品名不同**（防后人「顺手改回对齐」）。"""
    table = _naming_table()
    for agent_id, entry in table.items():
        note = entry.get("note", "")
        assert isinstance(note, str) and len(note.strip()) >= 20, (
            f"AGENT_NAMING[{agent_id!r}] 缺 note（或太短）—— 必须说清为什么 id 与产品名不同，"
            "否则下一个人只会看到「不一致」并把它改回对齐"
        )
        assert entry.get("side") in {"B", "C"}, (
            f"AGENT_NAMING[{agent_id!r}] 的 side={entry.get('side')!r} 不在 B / C 内"
        )
        assert entry.get("form") in {"agent", "capability"}, (
            f"AGENT_NAMING[{agent_id!r}] 的 form={entry.get('form')!r} 不是 agent / capability "
            "—— 形态本身就是产品口径（C 端无 agent 形态）"
        )
