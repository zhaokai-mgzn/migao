# case_ids: MC-021
"""**B 端米宝写面边界**的机械判据（issue #5247 只读化 → issue #5303 A 档可逆写补回）。

## 裁定一（2026-09-23 / issue #5247）

> 「B 端 agent 定位要求**侧重数据查询和分析**；当前具备的创建和更新能力以及 tools
> 都从 B 端 Agent 移除；把现在的商家后端功能模块能力添加进 B 端 Agent，**仅限查询和数据分析能力**。」

配套裁定：写工具处置 = **收窄为只读工具**（保留工具名与只读 action、`read_only=True`、
权限码改读码、删写 action）；**员工与岗位保留只读**；**系统设置不进 B 端对话面**；
C 端（小布）**零改动**。

## 裁定二（2026-09-24 / issue #5303，**A 档可逆写补回** —— 本判据的第二次改判）

> 按补回顺序把**最高 ROI 的可逆写**放回来：`product_update`（商品级统一定价）/
> `sku_update`（SKU 调价）—— 标注 `WRITE|IDEMPOTENT`（幂等 ⇒ 重放安全）+ **可逆**
> （价格能再调回去）+ 非对外承诺 + 不绕过审核门禁。

⇒ 白名单**只有这两条**（`A_TIER_REVERSIBLE_WRITES`），且必须
① **绑在且仅绑在** `product` skill（补回域唯一）；
② 带 `requires_confirmation`（否则写操作没有确认门禁）；
③ 先给商家看「改前 → 改后」预览才允许落库（该护栏落在工具层 fail-closed，
   机械判据见 `backend/ai-agent-service/tests/test_price_preview_guard.py`）。
其余写能力（建品 / 上下架 / 调库存 / 调订单状态 / 分类与加工项增删改 / 设置 / 通知）**一律仍不得绑**。
「按新裁定改判，不是删守卫」：判据 1/2/3/5 逐条保留，只把**白名单**这一格显式化，
并把能力文案的真值从"一律不得提改价"改成**双向一致**（判据 6）。

## 为什么必须有机械判据

「B 端写面边界」是**跨三个文件族的联合事实**，任何一处改动都不会有东西变红：

| 面 | 载体 | 漂移形态（本判据要拦的） |
|---|---|---|
| **S1 工具声明** | `backend/ai-agent-service/app/tools/*.py` 的 `read_only` / `VALID_ACTIONS` | 把某个 `read_only=True` 改回 `False`，或往 `VALID_ACTIONS` 里塞回写 action |
| **S2 skill 绑定** | `app/graph/skills/*.py` 的 `*_TOOLS` + `app/agents/agents/mibao.py` 的 `skill_names` | 把 `order_create` / `product_manage` / `validate_input` 重新绑回任一 B 端 skill（= 写能力静默复活） |
| **S3 能力文案** | `mibao.py` 的 `greeting` / `direct_replies.capabilities` | 文案承诺已下线能力（= **能力谎报**），或反过来**漏报**已补回的能力（商家不知道能找米宝改价） |

## 判据（每条都有**注入式红证**，见文件末尾 `test_every_judgement_can_go_red`）

1. **B 端可达的工具并集里不得有白名单外的 `read_only != True` 工具**（L0；含悬空绑定检查 ——
   绑了一个不存在的工具名也红，因为那说明解析面或绑定面已漂移）。白名单成员还必须在
   `product` skill 上且带 `requires_confirmation`。
2. **白名单外的写能力工具一个都不得绑在 B 端**（具名清单：`order_create` / `order_manage` /
   `product_manage` / `processing_item_manage` / `processing_order_generate` /
   `processing_order_update` / `settings_manage` / `notification_manage` / `validate_input`）。
3. **B 端可达工具的 action 集合 ⊆ 只读 action 集合**（写 action 名零命中；另加一份
   写 action **闭词表**兜底，防「工具把写 action 挪进 read_only_actions 洗白」）。
4. **能力文案不谎报**：`mibao.py` 的 `greeting` / `capabilities` 不得出现**白名单外**的
   能力承诺词（闭词表扫描 + 句级否定过滤）。#5303 改判：`改价` / `调价` 已从闭词表**移出**
   （该能力真实具备）—— 它们的真实性由判据 6 反向钉住，不是放任。
5. **共享工具与 C 端零改动**：与 C 端共享的 8 个工具必须**仍然存在**且**仍然绑在 C 端**
   （`order_create` / `validate_input` / `interact` / `knowledge_search` /
   `processing_item_query` / `product_search` / `product_detail` / `production_progress_query`）
   —— 「只解绑 B 端，绝不删除、不改 C 端行为」是用户裁定的硬边界。
6. **A 档写能力「文案 ↔ 绑定」双向一致**（#5303 新增）：文案承诺改价 ⇒ 两条工具必须真的绑在
   B 端；工具绑在 B 端 ⇒ 文案必须真的提到改价（**反向能力谎报**同样是缺陷）。

## 明确的边界（**不要**把本判据读成覆盖面更大）

- 本判据**只读源码文本**（零依赖：仅标准库 `ast` + `re`），不连库、不跑 LLM、不读端点。
  「工具码 ≡ 端点码 ≡ 菜单节点码」由 `tests/unit_ci_workflows/test_agent_permission_parity.py`
  （#5246）负责，本判据**不重复**它的规则。
- 本判据**不判提示词里的行为指令**（那些要靠真实 LLM 评测，按 `migao-dev-flow` §13 默认不派发）；
  它只判「**工具面 + 绑定面 + 能力文案**」这三处静态可判的事实。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_SERVICE = REPO_ROOT / "backend" / "ai-agent-service"
TOOLS_DIR = AI_SERVICE / "app" / "tools"
SKILLS_DIR = AI_SERVICE / "app" / "graph" / "skills"
AGENTS_DIR = AI_SERVICE / "app" / "agents" / "agents"

#: B 端**不得绑定**的写能力工具（用户裁定 2026-09-23：创建/更新能力从 B 端移除）。
#: `order_create` / `validate_input` 与 C 端共享 ⇒ 只解绑、**不删文件**（判据 5 反向钉住）。
#:
#: ⚠️ **2026-09-24 改判（issue #5303，A 档可逆写补回）**：`product_update` / `sku_update`
#: **已从本表移出** —— 它们被用户裁定为白名单（见 `A_TIER_REVERSIBLE_WRITES`），
#: 重新绑回 `product` skill。移出 ≠ 放宽：它们的可达性/确认门禁/补回域由判据 1 逐条钉住，
#: 且**本表其余条目一条都不许动**（`test_write_tools_bound` 的红证仍在跑）。
WRITE_TOOLS_UNBOUND_FROM_B_END: dict[str, str] = {
    "order_create": "建单（与 C 端共享：只解绑 B 端，文件与 C 端行为一字不动）",
    "order_manage": "改订单状态/发货/退款",
    "product_manage": "建品/上下架",
    "processing_item_manage": "加工项增删改",
    "processing_order_generate": "生成加工单",
    "processing_order_update": "加工单状态流转",
    "settings_manage": "系统设置（用户裁定：不进 B 端对话面）",
    "notification_manage": "通知配置（用户裁定：不进 B 端对话面）",
    "validate_input": "写操作前置校验（B 端无写操作 ⇒ 绑它只会把 A5「校验自己执行不了的写工具」引回来）",
}

#: **A 档可逆写白名单**（issue #5303，用户裁定 2026-09-24）：B 端**允许**存在的 `read_only=False` 工具。
#: 入册判据（缺一不可）：`WRITE|IDEMPOTENT`（重放安全）+ 可逆 + 非对外承诺 + 不绕过审核门禁。
#: ⚠️ 只许这两条：新增成员 = 改产品能力边界，必须显式改判本常量（判据 1 会立刻红）。
A_TIER_REVERSIBLE_WRITES: frozenset = frozenset({
    "product_update",   # 商品级统一定价（PATCH /api/admin/agent/products/{id} → basePrice）
    "sku_update",       # 单规格调价（PATCH …/skus/price）
})

#: A 档工具**必须**绑在的 skill（补回域唯一；漂移到别的域即红 —— 判据 1）
A_TIER_SKILL = "product"

#: 写 action **闭词表**（判据 3 的兜底）：action 名命中即视为写能力。
#: 口径 = 「动词表达『改数据』」，与 `read_only_actions` 的声明**无关** ——
#: 否则把写 action 挪进 `read_only_actions` 就能洗白（那正是本表要拦的形态）。
WRITE_ACTION_WORDS = frozenset({
    "create", "update", "delete", "adjust", "add_tag", "remove_tag", "create_tag",
    "update_tag", "delete_tag", "assign", "end", "toggle_status", "reset_password",
    "generate", "cancel", "refund", "confirm_payment", "update_status",
    "update_logistics", "create_transaction", "create_processing_item", "update_item",
    "delete_item", "create_role", "update_role", "delete_role", "create_user",
    "update_user", "delete_user", "create_category", "update_category", "delete_category",
    "create_ticket", "create_order", "mark_read", "create_notification",
})

#: 能力文案里的**写能力承诺词**（判据 4 闭词表）。命中即「AI 说得到、做不到」。
#:
#: ⚠️ **2026-09-24 改判（issue #5303）**：`改价` / `调价` **已移出本表** —— 改价是 A 档
#: 白名单能力（真实具备），留在闭词表里会把**正确的如实告知**判成谎报（假红）。
#: 它**不是被豁免**：文案提到改价而工具没绑 = 谎报，这一半由判据 6 反向钉住（双向一致）。
FORBIDDEN_CAPABILITY_PHRASES = (
    "创建商品", "创建订单", "创建工单", "创建员工", "创建角色", "创建分类", "创建加工项",
    "建单", "建品", "下单", "改状态", "修改订单", "取消订单", "退款",
    "调库存", "调整库存", "上下架", "删除商品", "删除员工", "删除角色", "重置密码",
    "商品管理", "订单处理", "库存管理", "通知管理", "修改配置", "系统配置",
    "图片识别", "创建商品记录",
)

#: 与 C 端共享的工具（判据 5）：必须仍存在、且仍被 C 端 skill 绑定。
SHARED_WITH_C_END = (
    "order_create", "validate_input", "interact", "knowledge_search",
    "processing_item_query", "product_search", "product_detail", "production_progress_query",
)


# ══════════════════════════════════════════════════════════════════════════════
# 一、读源（注入式红证 = 替换这里的某一项文本后重建 World）
# ══════════════════════════════════════════════════════════════════════════════


def _source_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(TOOLS_DIR.glob("*.py")):
        if p.name in ("__init__.py", "base.py", "registry.py", "langchain_adapter.py"):
            continue
        out[f"tool:{p.name}"] = p.read_text(encoding="utf8")
    for p in sorted(SKILLS_DIR.glob("*.py")):
        out[f"skill:{p.name}"] = p.read_text(encoding="utf8")
    for name in ("mibao", "xiaobu"):
        out[f"agent:{name}"] = (AGENTS_DIR / f"{name}.py").read_text(encoding="utf8")
    return out


def _literal(node: ast.AST):
    """字面量取值；`frozenset({'a','b'})` / `set()` / `tuple()` 这类包装自动拆一层。"""
    if isinstance(node, ast.Call):
        fn = getattr(node.func, "id", None)
        if fn in ("frozenset", "set", "tuple", "list"):
            if not node.args:
                return []
            return _literal(node.args[0])
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return None


def _module_literal(tree: ast.Module, name: str):
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            tgt = node.targets[0]
            if isinstance(tgt, ast.Name) and tgt.id == name:
                return _literal(node.value)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name and node.value is not None:
                return _literal(node.value)
    return None


def _class_literal(node: ast.ClassDef, attr: str):
    for st in node.body:
        if isinstance(st, ast.Assign) and len(st.targets) == 1:
            tgt = st.targets[0]
            if isinstance(tgt, ast.Name) and tgt.id == attr:
                return _literal(st.value)
    return None


def parse_tools(sources: dict[str, str]) -> dict[str, dict]:
    """`app/tools/*.py` → {tool_name: {read_only, valid_actions, read_only_actions, file}}。"""
    out: dict[str, dict] = {}
    for key, text in sorted(sources.items()):
        if not key.startswith("tool:"):
            continue
        tree = ast.parse(text)
        valid = _module_literal(tree, "VALID_ACTIONS")
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            name = _class_literal(node, "name")
            if not isinstance(name, str):
                continue
            ro = _class_literal(node, "read_only")
            roa = _class_literal(node, "read_only_actions")
            # `requires_confirmation`（#5303）：A 档白名单成员必须带确认门禁 —— 判据 1 要读它
            rc = _class_literal(node, "requires_confirmation")
            out[name] = {
                "file": f"app/tools/{key.split(':', 1)[1]}",
                "read_only": True if ro is None else bool(ro),
                "declared_read_only": ro is not None,
                "requires_confirmation": bool(rc) if rc is not None else False,
                "valid_actions": None if valid is None else [str(a) for a in valid],
                "read_only_actions": None if roa is None else [str(a) for a in roa],
            }
    assert out, "工具解析出 0 个声明 ⇒ 判据会空跑（fail-closed）"
    return out


def parse_skills(sources: dict[str, str]) -> dict[str, tuple[str, ...]]:
    """skill 名 → 工具清单（`SkillConfig(name=...)` + 同模块的 `*_TOOLS`）。"""
    out: dict[str, tuple[str, ...]] = {}
    for key, text in sorted(sources.items()):
        if not key.startswith("skill:"):
            continue
        tree = ast.parse(text)
        name = None
        tools: tuple[str, ...] = ()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = getattr(node.func, "id", None)
                if fn in ("SkillConfig", "create_skill_config"):
                    for kw in node.keywords:
                        if kw.arg == "name":
                            v = _literal(kw.value)
                            if isinstance(v, str):
                                name = v
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                tgt = node.targets[0]
                if isinstance(tgt, ast.Name) and re.fullmatch(r"[A-Z_]+_TOOLS", tgt.id):
                    v = _literal(node.value)
                    if isinstance(v, list) and all(isinstance(x, str) for x in v):
                        tools = tuple(v)
                        break
        if name and tools:
            out[name] = tools
    assert len(out) >= 12, f"skill 绑定解析出 {len(out)} 个 ⇒ 判据会空跑（fail-closed）：{sorted(out)}"
    return out


def parse_agent(sources: dict[str, str], agent: str) -> tuple[frozenset[str], str | None]:
    """某人格的 `skill_names` + `fallback_skill`（用 AST 读，避免注释里的引号被当成 skill 名）。"""
    tree = ast.parse(sources[f"agent:{agent}"])
    names: list[str] = []
    fallback: str | None = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", None) != "AgentConfig":
            continue
        for kw in node.keywords:
            if kw.arg == "skill_names":
                v = _literal(kw.value)
                if isinstance(v, list):
                    names = [str(x) for x in v]
            elif kw.arg == "fallback_skill":
                v = _literal(kw.value)
                if isinstance(v, str):
                    fallback = v
    assert names, f"`{agent}` 的 `skill_names` 解析为空 ⇒ 判据 fail-closed"
    return frozenset(names), fallback


def parse_agent_direct_replies(sources: dict[str, str], agent: str) -> dict[str, str]:
    """`AgentConfig.greeting` + `direct_replies` 的 键→文案（判据 4 的扫描面）。

    ⚠️ 两处**分开存键**（`greeting` vs `direct_replies.greeting`）：同名键互相覆盖会让
    「只改了一处」的注入在读数上被另一处盖掉 ⇒ 判据看着绿、注入就成了空断言（实测踩到）。"""
    tree = ast.parse(sources[f"agent:{agent}"])
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "direct_replies":
            for k, v in zip(node.value.keys, node.value.values):
                key = _literal(k)
                val = _literal(v)
                if isinstance(key, str) and isinstance(val, str):
                    out[f"direct_replies.{key}"] = val
        if isinstance(node, ast.keyword) and node.arg == "greeting":
            val = _literal(node.value)
            if isinstance(val, str):
                out["greeting"] = val
    return out


class World:
    """判据的全部输入（注入式红证 = 用改过的文本重建它）。"""

    def __init__(self, sources: dict[str, str]):
        self.sources = sources
        self.tools = parse_tools(sources)
        self.skills = parse_skills(sources)
        b_names, b_fallback = parse_agent(sources, "mibao")
        c_names, c_fallback = parse_agent(sources, "xiaobu")
        self.mibao_skills = b_names | ({b_fallback} if b_fallback else set())
        self.xiaobu_skills = c_names | ({c_fallback} if c_fallback else set())
        self.b_end_tools = frozenset(
            t for s in self.mibao_skills for t in self.skills.get(s, ())
        )
        self.c_end_tools = frozenset(
            t for s in self.xiaobu_skills for t in self.skills.get(s, ())
        )
        self.capability_text = parse_agent_direct_replies(sources, "mibao")
        # A 档白名单的"确认门禁"面（#5303）：从工具类声明现算，不抄清单
        self.confirmed_write_tools = frozenset(
            n for n, d in self.tools.items() if d.get("requires_confirmation")
        )
        assert self.b_end_tools, "B 端工具并集为空 ⇒ 判据会空跑（fail-closed）"
        assert self.c_end_tools, "C 端工具并集为空 ⇒ 判据会空跑（fail-closed）"


def world() -> World:
    return World(_source_map())


# ══════════════════════════════════════════════════════════════════════════════
# 二、五条判据（纯函数：输入 World，输出问题清单 —— 空 = 绿）
# ══════════════════════════════════════════════════════════════════════════════


def problems_union_is_read_only(w: World) -> list[str]:
    """判据 1：B 端可达工具的并集里，`read_only != True` 的只能是**白名单**成员（含悬空绑定）。

    #5303：白名单 = `A_TIER_REVERSIBLE_WRITES`（两条改价工具）。白名单成员另加两道：
    必须绑在 `A_TIER_SKILL`（补回域唯一）且必须带 `requires_confirmation`（写操作要有确认门禁）——
    否则"白名单"就成了任人往里塞写工具的橡皮图章。
    """
    out: list[str] = []
    for name in sorted(w.b_end_tools):
        decl = w.tools.get(name)
        if decl is None:
            out.append(f"`{name}` 被 B 端 skill 绑定，但**没有任何工具类声明该名字**（悬空绑定 ⇒ 模型必然撞 tool_not_found）")
            continue
        if decl["read_only"]:
            continue
        if name not in A_TIER_REVERSIBLE_WRITES:
            out.append(
                f"`{name}`（{decl['file']}）`read_only=False` 却仍在 B 端工具并集里 ⇒ "
                "B 端写能力复活（用户裁定：除 A 档可逆写白名单外，创建/更新能力全部从 B 端移除）"
            )
            continue
        if name not in w.skills.get(A_TIER_SKILL, ()):
            out.append(
                f"`{name}` 属 A 档可逆写白名单，却不在 `{A_TIER_SKILL}` skill 的工具集里 ⇒ "
                "补回域漂移（本单只补 product 域的改价）"
            )
        else:
            # 「**仅**绑在 product」：多绑一个 B 端域 = 补回范围悄悄超出本单裁定
            strays = sorted(s for s in w.mibao_skills
                            if s != A_TIER_SKILL and name in w.skills.get(s, ()))
            if strays:
                out.append(
                    f"`{name}` 属 A 档可逆写白名单，却还绑在其它 B 端 skill {strays} ⇒ "
                    f"补回范围超界（本单只在 `{A_TIER_SKILL}` 域补回这两条）"
                )
        if not decl.get("requires_confirmation"):
            out.append(
                f"`{name}` 属 A 档可逆写白名单，但未声明 `requires_confirmation` ⇒ "
                "写操作没有用户确认门禁（A 档入册判据：不绕过审核门禁）"
            )
    return out


def problems_write_tools_bound(w: World) -> list[str]:
    """判据 2：写能力工具一个都不得绑在 B 端（具名清单 + 双向陈旧检查）。"""
    out: list[str] = []
    for tool, why in sorted(WRITE_TOOLS_UNBOUND_FROM_B_END.items()):
        if tool in w.b_end_tools:
            out.append(f"写能力工具 `{tool}`（{why}）仍绑在 B 端 skill 里 ⇒ 必须解绑")
    return out


def problems_action_sets(w: World) -> list[str]:
    """判据 3：B 端可达工具的 action 集合 ⊆ 只读 action 集合（+ 写 action 闭词表）。"""
    out: list[str] = []
    for name in sorted(w.b_end_tools):
        decl = w.tools.get(name)
        if decl is None or decl["valid_actions"] is None:
            continue
        actions = set(decl["valid_actions"])
        roa = decl["read_only_actions"]
        if roa is not None:
            extra = sorted(actions - set(roa))
            if extra:
                out.append(
                    f"`{name}`：B 端可达的 action {extra} 不在它声明的只读 action "
                    f"{sorted(roa)} 里 ⇒ 写 action 没删干净"
                )
        hits = sorted(actions & WRITE_ACTION_WORDS)
        if hits:
            out.append(
                f"`{name}`：action 集合里出现写动作名 {hits}（闭词表命中）—— "
                "即把它写进 `read_only_actions` 也只是洗白，B 端不得再暴露写 action"
            )
    return out


#: 句级否定词（**与仓内同类守卫同口径**）：这些句子是「教用户别这么期待」，不是能力承诺。
#: 不做句级过滤会把「⚠️ 下单/建品/改价等操作米宝不做」这类**正确的如实告知**判成谎报（假红）。
#: ⚠️ 教训：本判据回归时第一版就是全文扫描 ⇒ 立刻误红了自家 capabilities 的否定句。
CAPABILITY_NEGATIONS = (
    "不做", "不提供", "不在能力内", "不得", "不能", "无法", "禁止", "切勿", "只读", "不支持",
)


def _claimed_sentences(text: str):
    """切句（。；换行）后**丢掉否定句** —— 剩下的才是「能力承诺」。"""
    for seg in re.split(r"[。；\n]", text):
        if any(neg in seg for neg in CAPABILITY_NEGATIONS):
            continue
        yield seg


def problems_capability_claims(w: World) -> list[str]:
    """判据 4：`mibao.py` 的 greeting / capabilities 不得**承诺**白名单外的能力（闭词表 + 句级否定过滤）。"""
    out: list[str] = []
    for key, text in sorted(w.capability_text.items()):
        for seg in _claimed_sentences(text):
            for phrase in FORBIDDEN_CAPABILITY_PHRASES:
                if phrase in seg:
                    out.append(
                        f"`mibao.py` 的 `{key}` 文案在**非否定句**里出现「{phrase}」⇒ **能力谎报**"
                        "（该能力已下线，承诺它就是 AI 说得到做不到）"
                        f"｜原句：{seg.strip()[:60]}"
                    )
    return out


#: A 档写能力在能力文案里的**承诺词**（判据 6 的扫描面）。
#: 与判据 4 的闭词表互补：判据 4 管"别承诺做不到的"，判据 6 管"做到了别不吭声"。
A_TIER_CLAIM_WORDS = ("改价", "调价")


def problems_a_tier_capability_parity(w: World) -> list[str]:
    """判据 6（#5303 新增）：A 档写能力的**文案 ↔ 绑定**双向一致（两侧都现算，不抄清单）。"""
    out: list[str] = []
    bound = sorted(t for t in A_TIER_REVERSIBLE_WRITES if t in w.b_end_tools)
    claimed: list[str] = []
    for key, text in sorted(w.capability_text.items()):
        for seg in _claimed_sentences(text):
            hit = next((w_ for w_ in A_TIER_CLAIM_WORDS if w_ in seg), None)
            if hit:
                claimed.append(f"{key}「{hit}」")
    if claimed and not bound:
        out.append(
            f"能力文案承诺了改价（{', '.join(claimed)}），但 A 档工具一条都不在 B 端工具并集里 "
            "⇒ **能力谎报**（说得到做不到）"
        )
    if bound and not claimed:
        out.append(
            f"A 档改价工具 `{'/'.join(bound)}` 已绑回 B 端，但 `mibao.py` 的 greeting / "
            "capabilities 一个字都没提改价 ⇒ **反向能力谎报**（商家不知道能找米宝改价；"
            "补回了却不说 = 白补）"
        )
    return out


def problems_shared_tools_intact(w: World) -> list[str]:
    """判据 5：与 C 端共享的工具必须仍存在、且仍被 C 端 skill 绑定（只解绑 B，绝不删）。"""
    out: list[str] = []
    for tool in SHARED_WITH_C_END:
        if tool not in w.tools:
            out.append(f"共享工具 `{tool}` 的**工具类已消失** ⇒ 违反「只解绑 B、绝不删除」（C 端会直接失效）")
            continue
        if tool not in w.c_end_tools:
            out.append(
                f"共享工具 `{tool}` 不再被任何 C 端 skill 绑定 ⇒ 这是**改 C 端行为**的动作"
                "（用户裁定：C 端零改动），不得在本单里发生"
            )
    return out


JUDGEMENTS = {
    "1 · B 端工具并集白名单制": problems_union_is_read_only,
    "2 · 白名单外写工具零绑定": problems_write_tools_bound,
    "3 · action 集 ⊆ 只读集": problems_action_sets,
    "4 · 能力文案不谎报": problems_capability_claims,
    "5 · 共享工具与 C 端零改动": problems_shared_tools_intact,
    "6 · A 档能力文案↔绑定双向一致": problems_a_tier_capability_parity,
}


# ══════════════════════════════════════════════════════════════════════════════
# 三、断言
# ══════════════════════════════════════════════════════════════════════════════


def test_every_judgement_is_green() -> None:
    """五条判据在**当前仓库**上全绿（红 = B 端只读化已漂移，逐条问题见断言文案）。"""
    w = world()
    problems = {label: fn(w) for label, fn in JUDGEMENTS.items()}
    bad = {label: p for label, p in problems.items() if p}
    assert bad == {}, "B 端只读判据未通过：\n" + "\n".join(
        f"  【{label}】\n    - " + "\n    - ".join(items[:12]) for label, items in bad.items()
    )


def test_union_print_is_informative() -> None:
    """读数（供 PR/汇报引用）：B 端工具并集与它们的 `read_only` 声明。"""
    w = world()
    print("\n[B 端工具并集] " + str(sorted(w.b_end_tools)))
    print("[其中 read_only=False] " + str(sorted(
        n for n in w.b_end_tools if w.tools.get(n, {}).get("read_only") is not True
    )))
    print("[B 端 skill] " + str(sorted(w.mibao_skills)))


# ══════════════════════════════════════════════════════════════════════════════
# 四、注入式红证：**每一条**判据都要有能单独变红的负向夹具（否则它只是空断言）
# ══════════════════════════════════════════════════════════════════════════════


def _bind_into_b_skill(text: str, tool: str) -> str:
    """往某个 B 端 skill 的 `*_TOOLS` 列表里插一个工具名（模拟「写工具被重新绑回」）。"""
    m = re.search(r"^[A-Z_]+_TOOLS\s*=\s*\[", text, re.M)
    assert m, "注入锚点失配：该 skill 里没有 `*_TOOLS = [`（同步本判据）"
    return text[: m.end()] + f'\n    "{tool}",' + text[m.end():]


def _unbind_from_c_skill(text: str, tool: str) -> str:
    new, n = re.subn(rf'\n\s*"{re.escape(tool)}",', "", text, count=1)
    assert n == 1, f"注入锚点失配：该 C 端 skill 里没有 `{tool}`（同步本判据）"
    return new


def _injections() -> dict[str, tuple[str, "callable", "callable"]]:
    """`label` → (被判据读取的源键, 文本变异, 目标判据)。"""
    return {
        "① 把 `order_create` 重新绑回 order skill ⇒ 判据 2 红": (
            "skill:order_skill.py",
            lambda s: _bind_into_b_skill(s, "order_create"),
            problems_write_tools_bound,
        ),
        "①b 把 `settings_manage` 重新绑回 product skill ⇒ 判据 2 红": (
            "skill:product_skill.py",
            lambda s: _bind_into_b_skill(s, "settings_manage"),
            problems_write_tools_bound,
        ),
        "② 把 B 端工具改回 `read_only = False`（product_search）⇒ 判据 1 红": (
            "tool:product_search.py",
            lambda s: s.replace("read_only = True", "read_only = False", 1),
            problems_union_is_read_only,
        ),
        "②b 绑一个不存在的工具名（悬空绑定）⇒ 判据 1 红": (
            "skill:data_skill.py",
            lambda s: _bind_into_b_skill(s, "ghost_tool_never_declared"),
            problems_union_is_read_only,
        ),
        "③ 往 B 端工具的 action 集合塞回写 action（category_manage += create）⇒ 判据 3 红": (
            "tool:category_manage.py",
            lambda s: s.replace('VALID_ACTIONS = {"tree"}', 'VALID_ACTIONS = {"tree", "create"}', 1),
            problems_action_sets,
        ),
        "③b 把写 action 挪进 `read_only_actions` 洗白（category_manage）⇒ 判据 3 红（闭词表兜底）": (
            "tool:category_manage.py",
            lambda s: s.replace(
                'VALID_ACTIONS = {"tree"}', 'VALID_ACTIONS = {"tree", "create"}', 1
            ).replace('read_only_actions = {"tree"}', 'read_only_actions = {"tree", "create"}', 1),
            problems_action_sets,
        ),
        "④ 能力文案注入「我可以帮您创建商品」⇒ 判据 4 红": (
            "agent:mibao",
            lambda s: s.replace("我可以帮您**查数据、做分析**", "我可以帮您创建商品、", 1),
            problems_capability_claims,
        ),
        "④b greeting 单独注入写能力承诺 ⇒ 判据 4 红": (
            "agent:mibao",
            lambda s: s.replace(
                "我可以帮您**查数据、做分析**：订单与物流、生产进度与报工、",
                "我可以帮您处理商品管理、订单处理，",
                1,
            ),
            problems_capability_claims,
        ),
        "⑤ 共享工具的 C 端绑定被摘掉（customer_order 去 order_create）⇒ 判据 5 红": (
            "skill:customer_order_skill.py",
            lambda s: _unbind_from_c_skill(s, "order_create"),
            problems_shared_tools_intact,
        ),
        # ── #5303 新增（判据 6）：A 档能力「文案 ↔ 绑定」双向 ──
        "⑥ A 档工具**全部**被解绑、文案仍承诺改价 ⇒ 判据 6 红（谎报方向）": (
            "skill:product_skill.py",
            lambda s: _unbind_from_c_skill(_unbind_from_c_skill(s, "product_update"), "sku_update"),
            problems_a_tier_capability_parity,
        ),
        "⑥b 文案抹掉改价承诺、工具仍绑在 B 端 ⇒ 判据 6 红（漏报方向）": (
            "agent:mibao",
            lambda s: re.sub(r"改价|调价", "改款", s),
            problems_a_tier_capability_parity,
        ),
        # ── #5303 新增（判据 1）：白名单成员的两道护栏 ──
        "⑦ A 档工具摘掉确认门禁（product_update）⇒ 判据 1 红": (
            "tool:product_update.py",
            lambda s: s.replace("requires_confirmation = True", "requires_confirmation = False", 1),
            problems_union_is_read_only,
        ),
        "⑦b A 档工具被绑到别的 B 端域（product_update 进 order skill）⇒ 判据 1 红（补回域漂移）": (
            "skill:order_skill.py",
            lambda s: _bind_into_b_skill(s, "product_update"),
            problems_union_is_read_only,
        ),
    }


def test_every_judgement_can_go_red() -> None:
    """**每条**判据都要有能单独变红的注入（改坏必红、还原必绿）。"""
    _covered = {fn for _key, _mutate, fn in _injections().values()}
    _missing = sorted(label for label, fn in JUDGEMENTS.items() if fn not in _covered)
    _orphan = sorted(
        label for label, (_k, _m, fn) in _injections().items() if fn not in JUDGEMENTS.values()
    )
    assert not _missing and not _orphan, (
        "判据表与注入表必须**互相覆盖**：缺注入 ⇒ 该判据永远不会红（空断言）；"
        f"\n  仅有判据、无注入：{_missing}\n  注入指向未登记的判据：{_orphan}"
    )
    base_sources = _source_map()
    base_world = World(base_sources)
    green = {label: fn(base_world) for label, fn in JUDGEMENTS.items()}
    assert all(not v for v in green.values()), (
        "对照组：未注入时五条判据必须全绿（否则红证无从归因）：\n"
        + "\n".join(f"  【{k}】{v[:2]}" for k, v in green.items() if v)
    )
    for label, (key, mutate, judgement) in _injections().items():
        sources = dict(base_sources)
        sources[key] = mutate(sources[key])
        assert sources[key] != base_sources[key], f"{label}：注入没生效（锚点失配）—— 同步本判据"
        mutated = World(sources)
        assert judgement(mutated), f"{label}：判据没有变红 ⇒ 它是空断言"