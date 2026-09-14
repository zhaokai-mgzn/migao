# case_ids: OR-014
"""能力自我否定族（#3389/#3477/#3443/#3476/#3571）第 6 次复发的 **L0 静态不变式**。

## 为什么再加一层（本文件的证据）

OR-014（run `34856561459` · SHA `97668011` · B 端 mibao 腿）两次同指纹失败
（`no_success(order_create)`）：agent 在「商品线上下文」自称无提交订单能力并连续拒单。
根因链（已用零 LLM 复算钉死，见 `tests/test_or014_flow_owner_guard.py` 的文档头）：

  R1「帮我下单…」→ L1 `order_create` → `order` skill；R2 答规格卡=答卡轮（留 order）；
  **R3「不需要其他加工项」→ L1 规则命中 `product_inquiry`（关键词「加工项」）→
  `route_by_intent` 的「L1 高置信域切换」逃逸（#3625 G3/T2）清掉 order 锁 → `product` skill**
  （`PRODUCT_TOOLS` 无 `order_create`）→ 容器日志 `[product] … has_tools=False`；
  R5「确认」起模型只能自称「落单属于订单环节的操作 / 这不归我管」——而 **`order_create`
  在全局工具表里、同 run 的 OR-008/OR-010 真调成功**。

既有两道网都没拦住它：
  · 文本级能力误宣判据（`capability_denial_text_hit`）对 5 句否定**全部返回空**（改前实测）
    —— 它只认"否定动词/权限受限 × 下单动作词"，认不出**归属错位式**（把下单判给别的环节/
    工作台/人工）、产出式 `V不了`、「不具备…能力」，也不认 B 端动作词「落单」；
  · `_relock_order_skill` 把回锁目标**写死 C 端节点名**（`customer_order`）—— 米宝图里
    没有该节点，回锁会指向图中不存在的节点。

## 本文件锁什么（结构层，秒级、零 LLM、零依赖）

1. **判据常量必须是"形态/类别词"，不得是整句白名单**（该族红线：措辞一变即失效的复发机制）。
   把 R5/R7/R8/R9/R11 的原文塞进词表 → 本文件必红（长度/标点双判）。
2. **判据函数体内不得出现长字符串字面量**（防止绕开常量表、把整句写进 `if`）。
3. **回锁目标必须 derive 自注册表事实**（`SkillConfig.tool_names`）+ persona 可达集，
   且 `_relock_order_skill` / `_flow_owner_skill` 里**不得出现任何 skill 名字面量**
   （与 `test_capability_guard_invariants.py::test_guard_predicates_cannot_see_skill_name` 同源，
   那条盯"能力可达性判据"，本条盯"回锁目标"）。

行为面（真实 `execute_skill` / `route_by_intent`）由
`backend/ai-agent-service/tests/test_or014_flow_owner_guard.py` 覆盖。
"""

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_SKILL = (REPO_ROOT / "backend" / "ai-agent-service" / "app" / "graph"
              / "skills" / "base_skill.py")
SKILLS_DIR = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "graph" / "skills"

# skill 名的**单一事实源**：从各 skill 模块的 `SkillConfig(name="...")` 声明里现取
# （刻意不写死清单 —— 新增 skill 必须自动进入覆盖，那正是复发机制）。
_SKILL_DECL_RE = re.compile(r'^\s*name="([a-z][a-z0-9_]*)"\s*,\s*$', re.M)

# 判据用的**形态/类别词表**（不是句子表）：每条都该是短词条。
_VOCAB_TUPLES = (
    "_ORDER_ACTION_WORDS",
    "_INABILITY_STEMS",
    "_PERMISSION_NEGATIONS",
    "_ABILITY_WORDS",
    "CAPABILITY_DENIAL_PATTERNS",
    "_SCOPE_HANDOFF_MARKERS",
    "_SELF_SCOPE_COMPOUNDS",
)

# 判据函数体：里面不该出现长字符串（整句字面量会从这里溜进来）。
_JUDGMENT_FUNCS = (
    "capability_denial_text_hit",
    "_scope_misattribution_hit",
    "_clause_is_self_line",
    "_negation_positions",
    "_self_scoped_clause",
)

_PUNCT = "。！？；，、：\n「」【】（）"


def _module() -> ast.Module:
    return ast.parse(BASE_SKILL.read_text(encoding="utf-8"))


def _assignments(tree: ast.Module) -> dict:
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            out[node.targets[0].id] = node.value
    return out


def _functions(tree: ast.Module) -> dict:
    return {n.name: n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _body_without_docstring(fn: ast.AST) -> list:
    """去掉首行 docstring 后的语句体（docstring 里写历史/skill 名是允许的，判定里不行）。"""
    body = list(getattr(fn, "body", []) or [])
    if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        return body[1:]
    return body


def _skill_names() -> set:
    names = set()
    for path in sorted(SKILLS_DIR.glob("*_skill.py")):
        names |= set(_SKILL_DECL_RE.findall(path.read_text(encoding="utf-8")))
    assert names, "未能从 skill 模块解析出任何 skill 名 —— 不变式失去意义"
    return names


# ────────────────── 不变式 1：判据是形态，不是句子白名单 ──────────────────

def test_denial_vocab_exists_and_is_morphology_not_sentences():
    """判据词表的每条都必须是**短词条**（形态/类别），不得是整句原文。

    红线来源：该族 5 次复发的共同机制就是"判据跟着措辞走"—— 把 R5/R7/R8/R9/R11 的原文
    贴进词表属于同一形态（换一句就漏，且让下一个人的"最省事路径"变成继续贴句子）。
    判据：每条 ≤ 8 字、不含任何标点/空白。退化演示：把
    「落单（提交订单）属于订单环节的操作」写进 `_SCOPE_HANDOFF_MARKERS` → 本测试必红。
    """
    assigns = _assignments(_module())
    offenders = []
    checked = 0
    for name in _VOCAB_TUPLES:
        node = assigns.get(name)
        assert node is not None, f"判据词表 {name} 不存在（被删/改名 → 本不变式失去意义）"
        entries = [e.value for e in getattr(node, "elts", [])
                   if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        assert entries, f"判据词表 {name} 解析不出字符串条目"
        for entry in entries:
            checked += 1
            if len(entry) > 8 or any(ch in entry for ch in _PUNCT) or " " in entry:
                offenders.append(f"{name}: {entry!r}（长度 {len(entry)}）")
    assert checked >= 20, f"只检查到 {checked} 条词条 —— 词表被大幅删减，不变式稀释"
    assert not offenders, (
        "判据词表里出现整句/长句（= 把句子白名单当判据，该族复发形态）：\n"
        + "\n".join(offenders)
    )


def test_judgment_functions_hold_no_sentence_literals():
    """判据函数体内不得出现长字符串字面量（防止绕开词表、把整句写进 `if`）。

    允许 docstring（说明历史/证据）—— 只扫非 docstring 的语句。
    """
    funcs = _functions(_module())
    offenders = []
    for fname in _JUDGMENT_FUNCS:
        fn = funcs.get(fname)
        assert fn is not None, f"判据函数 {fname} 不存在（被删/改名 → 本不变式失去意义）"
        body = list(fn.body)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            body = body[1:]
        for node in body:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str) \
                        and len(sub.value) > 12:
                    offenders.append(f"{fname}: L{sub.lineno} {sub.value[:30]!r}…")
    assert not offenders, (
        "判据函数体里出现长字符串（整句字面量判据，该族复发形态）：\n" + "\n".join(offenders)
    )


# ────────────────── 不变式 2：回锁目标 derive 自事实，不写死节点名 ──────────────────

def test_relock_target_is_fact_derived_and_named_nothing():
    """`_flow_owner_skill` 必须读**注册表声明**（`tool_names`），且两处都不得含 skill 名字面量。

    实证（OR-014）：`_relock_order_skill` 曾写死 `"customer_order"` —— 米宝（B 端）图里
    只有 `order/product/…`，回锁会指向**图中不存在的节点**（`route_by_intent` 把 pending 名
    原样返回，条件边映射缺失）⇒ 修好判据的那一步自己把会话打坏。
    """
    funcs = _functions(_module())
    owner_src = ast.unparse(funcs["_flow_owner_skill"])
    for token in ("get_skill_registry", "tool_names", "agent_type"):
        assert token in owner_src, (
            f"`_flow_owner_skill` 不再读事实 {token!r}（疑似退回落名字/落单点判据）"
        )
    names = _skill_names()
    offenders = []
    for fname in ("_flow_owner_skill", "_relock_order_skill"):
        for node in _body_without_docstring(funcs[fname]):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    for skill in names:
                        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(skill)}(?![A-Za-z0-9_])",
                                     sub.value):
                            offenders.append(
                                f"{fname}: L{sub.lineno} {skill!r} in {sub.value!r}")
    assert not offenders, (
        "回锁路径又出现 skill 名字面量（白名单复发形态，OR-014 实证形态）：\n"
        + "\n".join(offenders)
    )
