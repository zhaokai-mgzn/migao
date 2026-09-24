# case_ids: MC-021
# （沿用 tests/unit_ci_workflows/** 既有惯例：本文件判的是 **B 端米宝只读化的能力面**
#   —— 与 tests/unit_ci_workflows/test_mibao_b_end_readonly.py 同族，故挂同一条用例 MC-021；
#   本 PR **不新建用例族**、**不新增 [backend-contract] 用例** ⇒ 不动任何账本。）
"""**能力下线后的「死引用 / 死守卫 / 死绑定」类级元守卫**（issue #5331，§23 G1 + G2）。

## 立案理由：这一族在同一场只读化（#5247）之后产出了 **5 个实例**，**没有一例是门禁发现的**

| # | 形态 | 来源 |
|---|---|---|
| 1 | 死守卫（门条件方向反 ⇒ 恒不触发） | #5318 / PR #5324 |
| 2 | 死引用（description 点名不可达工具） | #5315（图片面已修，**通用判据仍空**） |
| 3 | 恒假条件（`B_CREATE_PENDING_TOOL` 随解绑恒假） | #5318 交付方登记 |
| 4 | 射程逃逸（判据射程 ≠ 处置后的状态空间） | #5302 / PR #5341 |
| 5 | 死绑定（只读域还绑着写校验器 `validate_input`） | #5302 交付方登记 |

共同根因一句话：**「删能力」这件事，没有配套的「扫依赖它的守卫 / 引用 / 绑定」动作。**
⇒ 能力下线时，依赖它的东西**静默变成死物，且没有任何东西会因此变红**。
§23 的读数：**只修实例 = 没修**（同类缺陷 24h 内 ≥10 例）。故本文件落**三个面的常驻判据 + 燃尽靶**。

## 四个面的分工（**射程面不在这里，别重复建**）

| 面 | 判据 | 落点 |
|---|---|---|
| 引用面 | 模型可见文本点名不可达工具（死引用）/ skill 自述面点名域外工具。**射程面（issue #5437 扩面后）**＝ ① 工具**类级** `description` ② schema **参数 `description`** ③ 运行期 **`suggestion` / `message`** ④ prompt / references / agent 直答 | **本文件** `problems_dead_refs`（①②③④ **共用同一个判据本体与同一档不判表** —— 不另立第二套） |
| 守卫面 | 门条件引用的能力标志必须**可能为真**（恒假 = 死标志 / 死守卫） | **本文件** `problems_dead_guards` |
| 绑定面 | skill 绑的工具必须**在该域内有可用 action**（只读域不绑写校验器） | **本文件** `problems_dead_bindings` |
| 射程面 | 守卫射程必须覆盖「处置会实际产生的状态」（含**已解绑孤儿**） | 🔴 **复用** `test_mibao_b_end_readonly.py` 的**判据 7** —— 本文件**有意不建第二套**（`problems_range_face_is_reused` 既判它在上游**注册且带注入式红证**，又**直接调用**它） |

## 台账纪律（§23 G2「燃尽靶」；数据文件 `dead_object_ledger.json`，判据只读它）

① 台账 = **当前已知死物的冻结清单**，每条必须带 `reason` + 单号 `issue`；
② **未登记即红**：现取扫描发现的新死物必须**先修**（修不动才登记 —— 登记是**可见的欠账**，不是豁免）；
③ **只许缩短**：修好一处 ⇒ **同 PR 删除对应条目**（条目陈旧 ⇒ 红）；同一条目**命中数涨或跌** ⇒ 红；
④ 燃尽锚点（`anchor`：条数 + 命中数，**现取打印**）**不许被现取反超**。

## 红证（§23 G7：**前提自证**，不是「锚点可命中」）

`test_every_judgement_can_go_red` 的每条注入都自证两件事：
① **注入生效**（`mutation != base`）；② **判据真的看见了新对象**（`expect_key ∈ 现取键集`）—— 二者都过才断言判据变红。
另有一条**负控**（注入一条**被否定**的死工具点名 ⇒ 键集**不**新增、判据**仍绿**）：证明否定过滤有判别力 ——
本判据**不是**「见名就红」，否则会把本仓「反例式指路」文风整片喂红（§17.3「判据被自己的文案喂红」）。

## 未固化的边界（照实登记，§19.1）

- **ref 面已销账**（issue #5400）：9 条「工具 description 点名零绑定工具」逐条改成可达工具 / 改成
  「如实说明不在能力内 + 引导后台页面」，台账条目**同 PR 删除**、`anchor.ref` 下调到 0
  ⇒ 再出现即红（**未登记 + 超现取锚点**双闸，后者不依赖台账条目存在）；
- **射程已扩（issue #5437）**：引用面自本单起覆盖**同属「注入模型的文本」**的三层 ——
  ① 工具**类级** `description`；② 工具 schema 的**参数 `description`**（`validate_input` 的
  `target_tool` 描述这类，函数调用 schema 的一部分）；③ 运行期 `suggestion=` / `message=`
  回灌文本（`order_create` 的数量校验建议这类）。扩面时**存量现取为 0 处** ——
  #5400 已把那 2 处**人工收口**（此前它们不在任何判据射程内，正是本单立案的原因）
  ⇒ 台账 `anchor.ref` **保持 0**、无需新增条目；**再出现即在两个闸上都红**（未登记 + 超锚点）。
  扩面后现取读数（`-s` 打印）：参数 description **255 条**、运行期文本 **82 个构造点 / 675 处**；
- **新面自带的两个防「静默免检」装置（照实登记）**：
  ① **射程元守卫** `problems_unregistered_hint_builders` —— `suggestion=` 出现在
  `MODEL_VISIBLE_BUILDERS`（`ToolResult` / `admin_api_failure` / `permission_denied`）**之外**
  的构造点上 ⇒ 红（否则加个包装器就能把文本挪到面外）；
  ② **冻结账户** `UNRESOLVED_RUNTIME_SITES` —— 运行期**拼装**（`"\n".join(构建中的列表)`）
  取不到字面量的站点登记在册，**只许缩短**（新增即红、能取到文本的陈旧条目也红）。
  现取仅 **1 条**（`validate_input.message`，位置见判红文案）—— 登记 = **可见欠账，不是豁免**；
- **仍未覆盖（照实登记）**：`app/tools/base.py` 等**非工具模块**的文本不在面内
  （MC-021 的 `_source_map` 有意不含它们；本单不擅自改上游读源）。**实测读数**：该文件里带
  工具名的字符串**全在 24 条 docstring 内**（docstring 不进模型），而**真正回灌**的模板
  （`_args_error` 构造的 `message` / `suggestion`）文本由**工具模块的调用点**传入 ⇒
  那些调用点都在面内、当前**无漏项**；但**将来**若有人直接在 `base.py` 里写一个点名工具的
  字面量并回灌，本判据看不见它 —— **已知射程边界**（不假装覆盖）；
- **「不可达」口径 = 「不被任何 skill 绑定」**（静态事实）。运行期还有一层 persona 家族**只读共享**
  （`base_skill._family_read_only_tool_names`）已按同口径复算进「允许集」；`skill_names` 解绑但文件保留的
  **孤儿工具**（6 个，`test_burn_down_anchor_is_printed` 打印）**有意不删**、**不入燃尽靶**
  （MC-021 判据 5 的「只解绑、绝不删除」）；
- **否定过滤的已知假阴性（登记，本单不改）**：`_negated` 按**整句**取否定标记 ⇒ 同句内
  **前一个子句的否定**会遮蔽**后面的正向指路**。活例（#5400 **人工**发现并改掉的那 1 处；
  把树退到 #5400 的父提交即可复现）：`app/tools/order_create.py` 的数量校验 suggestion 原文是
  「不要用 -1 之类的占位值表示退款或扣减（退款请用 order_manage 的 refund）」——
  「不要」挂在**前半句**上，括号里其实是**正向指路**，但整句判定 ⇒ 该点名被当反例跳过。
  ⇒ **该形态仍是盲区**；修它要动 #5331 的过滤器本体（会波及本仓「反例式指路」文风），
  **不属本单**（本单只扩面、只处理「全局不可达」这一档）；
- **「域外点名」档不判**（显式不判表，读数打印）：工具 description / 参数 description / 运行期文本
  都由**多个域共享**一份，且本仓有**跨 persona「反例式指路」**的既定文风（如 B 端工具写
  「商户员工查用 `order_query`」），一刀切会把**正确文本**判红 ——
  只判「点名**全局不可达**工具」这一档（必然 `tool_not_found`）。本单扩面**继承同一条收窄**
  （新面走同一个 `not_judged` 通道），并有**注入式负控**钉住（`test_out_of_domain_mentions_are_not_judged`）。

复算（零依赖、秒级）：
`python3 -m pytest tests/unit_ci_workflows/test_dead_capability_meta_guard.py -q -s`
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from unit_ci_workflows import test_mibao_b_end_readonly as mc

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "graph" / "skills"
REFS_DIR = SKILLS_DIR / "references"
LEDGER_PATH = Path(__file__).with_name("dead_object_ledger.json")

#: 本文件负责的**三个面**（射程面**不在此表** —— 见 `problems_range_face_is_reused`）。
MY_FACES = ("ref", "guard", "bind")

#: 上游射程面判据的注册名（`test_mibao_b_end_readonly.py::JUDGEMENTS` 的键）。
RANGE_FACE_LABEL = "7 · 声明 persona 的 skill 工具面受控"

#: 否定标记（点名**之前**、**同一句内**命中任一 ⇒ 该点名是「禁止 / 反例」，不是指路）。
#: ⚠️ 句界 = `。！？；` + 换行：本仓反例文风常把否定写在前半句（「不要拆解成 a + b」）。
NEGATION_MARKERS = ("不得", "不要", "禁止", "勿", "无", "没有", "不在", "❌", "≠", "不是", "别", "不可", "不能")

#: 工具名最短长度（更短的名会与自然语言碰撞 ⇒ 只做**全词边界**匹配并设下限）。
MIN_TOOL_NAME_LEN = 4

#: **模型可见文本的构造点**：只有这三个上报点会把文本回灌给模型（issue #5437）。
#: `message=` 是通用名（`logger.*` 也用得起）⇒ `message` 只按本集合收；`suggestion=` 罕见
#: ⇒ 另有 `problems_unregistered_hint_builders` 钉住（出现在别处 = 该文本在面外）。
MODEL_VISIBLE_BUILDERS = ("ToolResult", "admin_api_failure", "permission_denied")

#: **运行期回灌**的关键字：`suggestion` = 可行动建议；`message` = 主提示文本。二者都注入模型。
RUNTIME_KWARGS = ("suggestion", "message")

#: **取不到字面量的运行期文本站点**（冻结账户，**只许缩短**：新增即红、能取到文本的陈旧条目也红）。
#: 键 = `「工具.关键字」`（**不含行号** —— 无关改动挪动行号不该把账户判成陈旧，§23.5）。
#: ⚠️ 登记 = **可见欠账，不是豁免**：销账方向 = 把文案改成**可静态取到**的形态（或扩展本判据的解析）。
UNRESOLVED_RUNTIME_SITES: tuple[str, ...] = (
    # `message=summary`，而 `summary = "\n".join(summary_lines)` 是**运行期拼装**（逐行 append）⇒ 静态取不到
    "validate_input.message",
)


# ══════════════════════════════════════════════════════════════════════════════
# 一、读源（注入式红证 = 替换这里的某一项文本后重建 Scan）
# ══════════════════════════════════════════════════════════════════════════════


def surface_sources() -> dict[str, str]:
    """判据面：工具类 + skill 模块 + agent 声明（复用 MC-021 的读源）**再加**注入模型的 references 层。"""
    out = dict(mc._source_map())
    for path in sorted(REFS_DIR.rglob("*.md")):
        out[f"ref:{path.relative_to(REFS_DIR)}"] = path.read_text(encoding="utf8")
    assert out, "判据面取空（读源失效）⇒ 本守卫会静默空跑成绿"
    return out


def _string_value(node: ast.AST, table: dict[str, str] | None = None) -> str | None:
    """赋值右值的**静态文本**：字面量 / f-string 的静态片段 / `+` 拼接 / 已解析的同作用域变量。

    ⚠️ **不能**用 `ast.literal_eval` 一刀切：f-string 会被它判非法 ⇒ 本仓 `suggestion = f"..."`
    这类赋值取不到，文本**静默留在面外**（实测 9 处）。也**不能**放宽成「节点里有没有字符串常量」
    —— dict / list 常量会被误当文本，判红文案就会指向**无关对象**。取不到 ⇒ `None`（保守）。
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in ast.walk(node)
                       if isinstance(v, ast.Constant) and isinstance(v.value, str))
    if isinstance(node, ast.Name):
        return (table or {}).get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _string_value(node.left, table)
        right = _string_value(node.right, table)
        if left is None or right is None:
            return None
        return left + right
    return None


def _scope_consts(body: list) -> dict[str, str]:
    """一个作用域内的字符串赋值（`NAME = ...` / `NAME += ...`）：**按源码顺序**、**不下潜嵌套函数**。

    ⚠️ 走**函数局部**不是可选项：本仓有 `suggestion = f"..."` 再 `suggestion=suggestion` 的写法
    （`app/tools/order_create.py`）—— 只认字面量/模块常量会把这类文本**静默留在面外**，
    而那正是 issue #5437 要治的病（判据射程 ≠ 注入面）。顺序必须按源码（`+=` 依赖前一次赋值）。
    """
    out: dict[str, str] = {}

    def visit(stmts) -> None:
        for node in stmts:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name):
                text = _string_value(node.value, out)
                if text is not None:
                    out[node.targets[0].id] = text
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                text = _string_value(node.value, out) if node.value is not None else None
                if text is not None:
                    out[node.target.id] = text
            elif isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add) \
                    and isinstance(node.target, ast.Name):
                text = _string_value(node.value, out)
                if text is not None:
                    out[node.target.id] = out.get(node.target.id, "") + text
            visit(list(ast.iter_child_nodes(node)))

    visit(body)
    return out


def _module_consts(text: str) -> dict[str, str]:
    """模块级字符串常量（`NAME = 「...」` / 带注解）——prompt 常以**常量名**传入 `SkillConfig`。"""
    return _scope_consts(ast.parse(text).body)


def _text_of(node: ast.AST, consts: dict[str, str], local: dict[str, str] | None = None) -> str:
    """节点的**注入文本**：字面量 / 隐式拼接 / f-string 的静态片段（含常量名与函数局部变量名）。

    f-string 只取**静态片段**（`f"请改用 {VAR}"` 取不到插值）⇒ 这是**保守**方向：取不到就不会误判红。
    """
    if isinstance(node, ast.Name):
        return (local or {}).get(node.id) or consts.get(node.id) or ""
    return "".join(v.value for v in ast.walk(node)
                   if isinstance(v, ast.Constant) and isinstance(v.value, str))


def _module_functions(sources: dict[str, str], include_methods: bool = False) -> dict[str, list]:
    """函数索引：参数 schema 常由**共享工厂函数**造 ⇒ 必须能追进去（否则新面自带静默空洞）。

    `include_methods=False` 只收模块级函数（schema 工厂的形态）；`True` 连**方法**一起收
    （运行期文本有 `message=self._build_message(...)` 这种同模块方法拼装）。
    """
    out: dict[str, list] = {}
    for key, text in sorted(sources.items()):
        if not key.startswith(("tool:", "skill:", "agent:")):
            continue  # `ref:` 是 markdown（不是 Python）—— 直接 parse 会炸
        tree = ast.parse(text)
        nodes = ast.walk(tree) if include_methods else [n for n in tree.body]
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.setdefault(node.name, []).append(node)
    return out


def _callee_text(node: ast.AST, funcs: dict[str, list]) -> str:
    """值是**调用**时，取被调函数**函数体里的字符串字面量**（运行期文案由它拼出来 = 单点来源）。

    命中本仓三种真实写法：`message=self._build_message(...)`（同模块方法）、
    `message=_model_message(plan)`（同模块函数）、`message=no_sku_stock_note(...)`
    （`app/tools/stock_semantics.py` 的共享函数）。它们把文案**在函数体里拼**再返回，
    只取 `return` 的值会得到 `"\\n".join(lines)` 这种**空文本** ⇒ 必须取整个函数体。
    """
    if not isinstance(node, ast.Call):
        return ""
    name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
    out = []
    for fn in (funcs.get(name) or ()) if isinstance(name, str) else ():
        out.append("".join(v.value for v in ast.walk(fn)
                           if isinstance(v, ast.Constant) and isinstance(v.value, str)))
    return "".join(out)


def _call_scopes(tree: ast.Module) -> dict[int, dict[str, str]]:
    """`{构造点(Call) 的节点 id: 它所在函数作用域的局部常量表}`（模块级 ⇒ `{}`）。

    局部表按**最近的外层函数**归属（`ast.walk` 自外向内 ⇒ `setdefault` 不被内层覆盖）
    ⇒ 同名局部变量不跨函数串味（判红文案必须指向**真对象**）。
    """
    out: dict[int, dict[str, str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        table = _scope_consts(node.body)
        for sub in ast.walk(node):
            out.setdefault(id(sub), table)
    return out


def _collect_schema_desc(node: ast.AST, path: str, consts: dict[str, str], funcs: dict[str, list],
                         out: dict[str, str], depth: int = 0) -> None:
    """递归取 JSON-schema 形状 dict 里 `description` 的文本；`path` = **参数键路径**。

    · `properties` 这一层**不进路径**（它的子键就是参数名）⇒ 键形如 `target_tool` / `pageMeta.type`；
    · `Call` 追进**模块级工厂函数**：`app/tools/inventory_manage.py` 的 `threshold` 由
      `app/tools/stock_semantics.py` 的 `low_stock_alert_threshold_schema()` 造（参数 schema 的
      共享单点来源）—— 只扫字面量会给新面自带一个静默空洞，而那正是本单要治的病。
    """
    if isinstance(node, ast.Dict):
        for k, v in zip(node.keys, node.values):
            key = mc._literal(k)
            if key == "description":
                text = _text_of(v, consts)
                if text:
                    out[path] = out.get(path, "") + text
            elif key == "properties":
                _collect_schema_desc(v, path, consts, funcs, out, depth)
            elif isinstance(key, str):
                _collect_schema_desc(v, f"{path}.{key}" if path else key, consts, funcs, out, depth)
            else:
                _collect_schema_desc(v, path, consts, funcs, out, depth)
    elif isinstance(node, ast.Call):
        if depth < 1:
            name = getattr(node.func, "id", None)
            for fn in (funcs.get(name) or ()) if isinstance(name, str) else ():
                for sub in ast.walk(fn):
                    if isinstance(sub, ast.Return):
                        _collect_schema_desc(sub.value, path, consts, funcs, out, depth + 1)
    else:
        for sub in ast.iter_child_nodes(node):
            _collect_schema_desc(sub, path, consts, funcs, out, depth)


def _param_descriptions(sources: dict[str, str]) -> dict[str, str]:
    """`param:<工具>.<参数路径>` → **注入模型的 schema 参数 description** 文本（issue #5437）。

    与类级 `description` **同属注入模型的文本**（函数调用 schema 的一部分），但 #5331 的
    `_descriptions` 只取**类级** ⇒ 之前**没有任何判据**看得见它（#5400 才发现，且是**人工普查**所得）。
    """
    funcs = _module_functions(sources)
    out: dict[str, str] = {}
    for key, text in sorted(sources.items()):
        if not key.startswith("tool:"):
            continue
        consts = _module_consts(text)
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.ClassDef):
                continue
            name = mc._class_literal(node, "name")
            if not isinstance(name, str):
                continue
            for st in node.body:
                if not (isinstance(st, ast.Assign) and len(st.targets) == 1
                        and getattr(st.targets[0], "id", None) == "parameters"):
                    continue
                found: dict[str, str] = {}
                _collect_schema_desc(st.value, "", consts, funcs, found)
                for path, body in found.items():
                    out[f"param:{name}.{path}"] = body
    return out


def _runtime_texts(sources: dict[str, str]) -> tuple[dict[str, str], dict[str, int], dict[str, str]]:
    """`sugg:<工具>` / `msg:<工具>` → 运行期**回灌给模型**的提示文本。

    返回 `(文本, 处数, 取不到字面量的站点)`；末项 `{「工具.关键字」: 位置}` 是**冻结账户**
    `UNRESOLVED_RUNTIME_SITES`（**只许缩短**）的现取面 —— 按「工具.关键字」而非行号做键，
    免得**无关改动挪动行号**就把账户判成陈旧（§23.5 坐标漂移）。

    · 只收 `MODEL_VISIBLE_BUILDERS`（`message=` 是通用名，`logger.*` 也用得起 —— 不限定会把无关文本
      拖进判定面：**面取宽了比取窄了更危险**，判红文案会指向无关对象）；
    · 按 `(关键字, 工具)` 聚合而不按站点编号：键必须**稳定**（插一条 suggestion 不该让别的键改号）；
    · ⚠️ 站点之间必须用 `"\n"` 拼（`_negated` 把换行当句界）—— 直接首尾相接会让**上一条文本的
      「不要…」越界否定下一条的点名**（实测踩到：`sugg:order_create` 的注入式红证被邻条吞掉）；
    · ⚠️ 一个模块**声明多个工具类**时无法归因主体 ⇒ 不猜、跳过（`validator_tools` 同口径）。
    """
    out: dict[str, str] = {}
    sites: dict[str, int] = {}
    unresolved: dict[str, str] = {}
    funcs = _module_functions(sources, include_methods=True)
    for key, text in sorted(sources.items()):
        if not key.startswith("tool:"):
            continue
        fname = key.split(":", 1)[1]
        tree = ast.parse(text)
        consts = _module_consts(text)
        scopes = _call_scopes(tree)
        declared = [mc._class_literal(n, "name") for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        owner = declared[0] if len(declared) == 1 and isinstance(declared[0], str) else None
        if owner is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if called not in MODEL_VISIBLE_BUILDERS:
                continue
            for kw in node.keywords:
                if kw.arg not in RUNTIME_KWARGS:
                    continue
                body = _text_of(kw.value, consts, scopes.get(id(node))) or _callee_text(kw.value, funcs)
                surface = f"{'sugg' if kw.arg == 'suggestion' else 'msg'}:{owner}"
                if not body:
                    unresolved[f"{owner}.{kw.arg}"] = f"app/tools/{fname}:{kw.value.lineno}"
                    continue
                out[surface] = out.get(surface, "") + "\n" + body
                sites[surface] = sites.get(surface, 0) + 1
    return out, sites, unresolved


def _resolve_text(node: ast.AST, consts: dict[str, str]) -> str | None:
    """取字符串值：字面量 / 模块常量名（本仓 13 条 prompt **全部**走常量名）。"""
    value = mc._literal(node)
    if isinstance(value, str):
        return value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    return None


def prompt_texts(sources: dict[str, str]) -> dict[str, str]:
    """`skill:<文件>::<persona>` → 真正注入模型的 System Prompt 文本（**AST 取 prompt 值，不扫源码**）。

    ⚠️ 为什么必须走到常量名：`system_prompts={"mibao": SETTINGS_SYSTEM_PROMPT}` 这种写法下，
    只取字面量会得到 **0 条** ⇒ 判据就此**空跑且全绿**（实测踩到；§19.1「判据自己选择沉默」）。
    """
    out: dict[str, str] = {}
    for key, text in sorted(sources.items()):
        if not key.startswith("skill:"):
            continue
        fname = key.split(":", 1)[1]
        if fname == "base_skill.py" or not fname.endswith("_skill.py"):
            continue
        consts = _module_consts(text)
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "id", None) not in ("SkillConfig", "create_skill_config"):
                continue
            for kw in node.keywords:
                if kw.arg != "system_prompts":
                    continue
                keys = getattr(kw.value, "keys", None) or []
                vals = getattr(kw.value, "values", None) or []
                for k_node, v_node in zip(keys, vals):
                    persona = mc._literal(k_node)
                    body = _resolve_text(v_node, consts)
                    if isinstance(persona, str) and isinstance(body, str):
                        out[f"{key}::{persona}"] = body
    return out


def skill_of_surface(surface_key: str) -> str | None:
    """`skill:order_skill.py::mibao` → `order`（非 skill 面 ⇒ None）。"""
    if not surface_key.startswith("skill:"):
        return None
    fname = surface_key.split(":", 1)[1].split("::", 1)[0]
    return fname[:-3] if fname.endswith("_skill.py") else None


def tool_vocab(sources: dict[str, str]) -> frozenset:
    """工具词汇表（**绑定与判据共用的同一份**）：`app/tools/*.py` 里声明的工具名。"""
    out = frozenset(mc.parse_tools(sources))
    assert out, "工具词汇表解析出 0 个 ⇒ 引用面 / 守卫面会空跑（fail-closed）"
    return out


def tool_flags(sources: dict[str, str], vocab: frozenset) -> dict[str, dict]:
    """模块级「**工具名常量**」= 能力标志的声明面：`{相对路径::符号: {...}}`。

    ⚠️ 必须按**工具词汇表**过滤：skill 模块里还有大量别的字符串常量
    （prompt 常量、状态键、话术片段）—— 不过滤会得到 41 个"标志"，其中 38 个是噪声
    （实测踩到：面取宽了比取窄了更危险，判红文案会指向无关对象）。
    """
    out: dict[str, dict] = {}
    for key, text in sorted(sources.items()):
        if not key.startswith("skill:"):
            continue
        path = key.split(":", 1)[1]
        for node in ast.parse(text).body:
            tgt = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                tgt = node.targets[0].id
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                tgt = node.target.id
            if tgt is None or node.value is None:
                continue
            value = mc._literal(node.value)
            if isinstance(value, str) and value in vocab:
                out[f"{path}::{tgt}"] = {"symbol": tgt, "path": path, "tool": value,
                                         "lineno": node.lineno}
    return out


def capability_predicates(sources: dict[str, str], vocab: frozenset) -> dict[str, dict]:
    """「能力谓词」= 函数体里引用**工具名常量**的函数（`{相对路径::函数名: {...}}`）。

    `gate_refs` = 该谓词被**门条件**（`If` 的 test）引用的次数 —— 0 表示它不是门条件的一部分。
    """
    out: dict[str, dict] = {}
    symbols = {meta["symbol"] for meta in tool_flags(sources, vocab).values()}
    for key, text in sorted(sources.items()):
        if not key.startswith("skill:"):
            continue
        path = key.split(":", 1)[1]
        tree = ast.parse(text)
        gate_uses: dict[str, int] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            for sub in ast.walk(node.test):
                if isinstance(sub, ast.Call):
                    name = getattr(sub.func, "id", None) or getattr(sub.func, "attr", None)
                    if isinstance(name, str):
                        gate_uses[name] = gate_uses.get(name, 0) + 1
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            refs = sorted({n.id for n in ast.walk(node)
                           if isinstance(n, ast.Name) and n.id in symbols})
            if not refs:
                continue
            out[f"{path}::{node.name}"] = {
                "symbol": node.name, "path": path, "lineno": node.lineno,
                "refs": tuple(refs), "gate_refs": gate_uses.get(node.name, 0),
            }
    return out


def validator_tools(sources: dict[str, str], vocab: frozenset) -> dict[str, dict]:
    """「校验器类工具」= 模块里**恰好声明一个工具类**、且有一个**键全是工具名**的模块级字典。

    例：`validate_input.py` 的 `_VALIDATION_RULES` 键 = 它要校验的那些写工具
    ⇒ 它的**作用对象集**就是那些键 —— 拿它去校验一个**写不了任何东西**的域 = 死绑定。
    （一个模块多工具类 ⇒ 无法归因主体，**不猜**、不判。）
    """
    out: dict[str, dict] = {}
    for key, text in sorted(sources.items()):
        if not key.startswith("tool:"):
            continue
        fname = key.split(":", 1)[1]
        tree = ast.parse(text)
        names = [mc._class_literal(n, "name") for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        declared = [n for n in names if isinstance(n, str)]
        if len(declared) != 1:
            continue
        subjects: set[str] = set()
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)) or not isinstance(node.value, ast.Dict):
                continue
            keys = [k.value for k in node.value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            hit = {k for k in keys if k in vocab}
            if len(hit) >= 2:
                subjects |= hit
        if subjects:
            out[declared[0]] = {"tool": declared[0], "path": fname,
                                "subjects": frozenset(subjects)}
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 二、现取扫描（判据的**唯一**输入面）
# ══════════════════════════════════════════════════════════════════════════════


def _negated(text: str, start: int) -> bool:
    """该点名**之前**（同一句内）是否出现否定标记。"""
    cut = max(text.rfind(sep, 0, start) for sep in "。！？；\n")
    return any(marker in text[cut + 1:start] for marker in NEGATION_MARKERS)


def _mentions(text: str, vocab: list):
    """全词边界的工具名点名：`(tool, pos, ctx)`。"""
    for tool in vocab:
        if len(tool) < MIN_TOOL_NAME_LEN:
            continue
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(tool)}(?![A-Za-z0-9_])"
        for match in re.finditer(pattern, text):
            yield tool, match.start(), text[max(0, match.start() - 60):match.end() + 60].replace("\n", " ⏎ ")


class Scan:
    """一次取数的全部读数（§23 G4：判据内部**不许**一半现取一半台账快照）。"""

    def __init__(self, sources: dict[str, str], ledger: dict) -> None:
        self.ledger = ledger
        world = mc.World(sources)
        self.tools = world.tools
        self.skills = dict(world.skills)
        self.personas = {s: set(p) for s, p in world.skill_personas.items()}
        self.tool_names = sorted(self.tools)
        self.binders: dict[str, set] = {}
        for skill, bound in self.skills.items():
            for tool in bound:
                self.binders.setdefault(tool, set()).add(skill)
        #: 全局不可达工具 = **不被任何 skill 绑定**（静态事实；运行期只读共享也要「有人绑」才成立）
        self.dead_tools = frozenset(t for t in self.tools if t not in self.binders)
        self.vocab = tool_vocab(sources)
        self.prompts = prompt_texts(sources)
        self.descriptions = self._descriptions(sources)
        #: issue #5437 扩进来的两个**注入模型的文本面**（只收**被绑定**的工具 —— 零绑定工具的文件
        #: 从不注入，与 `_descriptions` 同口径：面取宽了会把文本判红在无关对象上）。键前缀：
        #: `param:` = 工具 schema 的参数 description（函数调用 schema 的一部分）；
        #: `sugg:` / `msg:` = 运行期回灌给模型的 suggestion / message 文本。
        self.params = {k: v for k, v in _param_descriptions(sources).items()
                       if k.split(":", 1)[1].split(".", 1)[0] in self.binders}
        live_runtime, sites, unresolved = _runtime_texts(sources)
        self.runtime = {k: v for k, v in live_runtime.items() if k.split(":", 1)[1] in self.binders}
        self.runtime_sites = {k: n for k, n in sites.items() if k.split(":", 1)[1] in self.binders}
        self.unresolved_runtime = {k: v for k, v in unresolved.items()
                                   if k.split(".", 1)[0] in self.binders}
        self.flags = tool_flags(sources, self.vocab)
        self.flags_by_symbol: dict[str, dict] = {}
        for meta in self.flags.values():
            seen = self.flags_by_symbol.get(meta["symbol"])
            assert seen is None or seen["tool"] == meta["tool"], (
                f"同名能力标志 `{meta['symbol']}` 在不同模块里指向不同工具 ⇒ 守卫面无法归因（fail-closed）"
            )
            self.flags_by_symbol[meta["symbol"]] = meta
        self.predicates = capability_predicates(sources, self.vocab)
        self.validators = validator_tools(sources, self.vocab)
        self.ref_hits, self.ref_not_judged = self._scan_refs(sources)
        self.guard_dead = self._scan_guards()
        self.bind_dead = self._scan_bindings()

    # ── 允许集：绑定 ∪ persona 家族只读共享（与 `base_skill._family_read_only_tool_names` 同口径）──

    def family_readonly(self, skill: str) -> frozenset:
        personas = self.personas.get(skill) or set()
        if len(personas) != 1:
            return frozenset()
        persona = next(iter(personas))
        out = set()
        for other, ps in self.personas.items():
            if persona in ps:
                out |= {t for t in self.skills.get(other, ())
                        if self.tools.get(t, {}).get("read_only") is True}
        return frozenset(out)

    def allowed_for_skill(self, skill: str) -> frozenset:
        return frozenset(set(self.skills.get(skill, ())) | set(self.family_readonly(skill)))

    def allowed_for_agent(self, skills) -> frozenset:
        out: set = set()
        for skill in skills:
            out |= set(self.allowed_for_skill(skill))
        return frozenset(out)

    def _allowed_of_tool(self, tool: str) -> frozenset:
        """该工具**被绑定到的那些域**里可达的工具并集 —— 模型可见文本由这些域**共享**一份。"""
        allowed: set = set()
        for skill in self.binders.get(tool, ()):
            allowed |= set(self.allowed_for_skill(skill))
        return frozenset(allowed)

    def reachable_in_scope(self, personas, skills) -> frozenset:
        """声明作用域内**可达**的工具（personas ⇒ 该 persona 可达的 skill 并集，∪ 显式点名的 skills）。"""
        scope_skills = {s for s in (skills or ()) if s in self.skills}
        for skill, ps in self.personas.items():
            if set(personas or ()) & ps:
                scope_skills.add(skill)
        out: set = set()
        for skill in scope_skills:
            out |= set(self.skills.get(skill, ()))
        return frozenset(out)

    # ── 工具 description（只有**被绑定**的工具的描述才会注入模型）──

    @staticmethod
    def _descriptions(sources: dict[str, str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for key, text in sorted(sources.items()):
            if not key.startswith("tool:"):
                continue
            consts = _module_consts(text)
            for node in ast.walk(ast.parse(text)):
                if not isinstance(node, ast.ClassDef):
                    continue
                name = None
                desc = None
                for st in node.body:
                    if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
                        if st.targets[0].id == "name":
                            name = mc._literal(st.value)
                        elif st.targets[0].id == "description":
                            desc = _resolve_text(st.value, consts)
                if isinstance(name, str) and isinstance(desc, str):
                    out[name] = desc
        return out

    # ── 引用面：注入模型的文本面 ──

    def _surfaces(self, sources: dict[str, str]):
        """`(surface_key, allowed, text, kind)` —— 只收**真正注入模型**的文本（注释/文档字符串不算）。"""
        rows = []
        for key, text in sorted(self.prompts.items()):
            skill = skill_of_surface(key)
            allowed = (self.allowed_for_skill(skill) if skill in self.skills
                       else frozenset(self.binders))
            rows.append((key, allowed, text, "skill"))
        for key, text in sorted(sources.items()):
            if not key.startswith("ref:"):
                continue
            stem = Path(key[4:]).stem
            found = re.fullmatch(r"EXAMPLES-(.+)", stem)
            owner = found.group(1) if found else stem
            allowed = (self.allowed_for_skill(owner) if owner in self.skills
                       else frozenset(self.binders))  # 共享层（base/*.md、PROMPT-rules.md）
            rows.append((key, allowed, text, "skill" if owner in self.skills else "shared"))
        for agent in ("mibao", "xiaobu"):
            names, fallback = mc.parse_agent(sources, agent)
            skills = set(names) | ({fallback} if fallback else set())
            allowed = self.allowed_for_agent(skills)
            replies = mc.parse_agent_direct_replies(sources, agent)
            for reply_key, body in sorted(replies.items()):
                rows.append((f"agent:{agent}::{reply_key}", allowed, body, "agent"))
        for tool in sorted(self.binders):
            rows.append((f"tool:{tool}", self._allowed_of_tool(tool),
                         self.descriptions.get(tool, ""), "tool"))
        # issue #5437：射程从**类级 description** 扩到**同属注入模型的文本** —— schema 参数
        # description 与运行期 suggestion / message。复用**同一套 `allowed`**、**同一档不判表**
        # （`kind="tool"` ⇒ 域外点名进 `not_judged`）与**同一个判据本体** `_scan_refs`，
        # 不另立第二套（§17.3「同一真值两处投影」）。
        for surface, text in sorted({**self.params, **self.runtime}.items()):
            rows.append((surface, self._allowed_of_tool(surface.split(":", 1)[1].split(".", 1)[0]),
                         text, "tool"))
        return rows

    def _scan_refs(self, sources: dict[str, str]):
        """死引用：① 点名**全局不可达**工具（必然 `tool_not_found`）；② skill 自述面点名**域外**工具。

        返回 `(hits, not_judged)`：`hits` = **未登记即红**的现取集；
        `not_judged` = **显式不判表**（工具 description 的域外点名：由多域共享 + 反例文风，一刀切会喂红正确文本）。
        """
        hits: dict[str, list] = {}
        not_judged: dict[str, list] = {}
        for surface, allowed, text, kind in self._surfaces(sources):
            if not text:
                continue
            for tool, pos, ctx in _mentions(text, self.tool_names):
                if _negated(text, pos):
                    continue
                if tool in self.dead_tools:
                    hits.setdefault(f"{surface}::{tool}", []).append(ctx)
                elif tool not in allowed:
                    target = not_judged if kind == "tool" else hits
                    target.setdefault(f"{surface}::{tool}", []).append(ctx)
        return hits, not_judged

    # ── 守卫面：能力标志恒假 ⇒ 引用它的门条件恒不触发 ──

    def _scan_guards(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for key, meta in sorted(self.flags.items()):
            if meta["tool"] in self.dead_tools:
                out[key] = dict(meta, kind="flag",
                                reason_kind="它点名的工具**全局不可达**（不被任何 skill 绑定）⇒ 标志恒假")
        for key, meta in sorted(self.predicates.items()):
            scope = (self.ledger.get("scopes") or {}).get(key)
            if not scope:
                continue  # 未声明作用域 ⇒ 按全局判（上面 flag 那条已覆盖它引用的标志）
            reachable = self.reachable_in_scope(scope.get("personas"), scope.get("skills"))
            tools = {self.flags_by_symbol[r]["tool"] for r in meta["refs"] if r in self.flags_by_symbol}
            if tools and tools.isdisjoint(reachable):
                out[key] = dict(meta, kind="predicate", scope=scope, tools=tuple(sorted(tools)),
                                reason_kind="**声明作用域内**它引用的工具**全部**不可达 ⇒ 谓词恒假（死守卫）")
        return out

    # ── 绑定面：只读域绑写校验器 ──

    def _scan_bindings(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for tool, meta in sorted(self.validators.items()):
            for skill, bound in sorted(self.skills.items()):
                if tool not in bound:
                    continue
                writable = {t for t in bound if self.tools.get(t, {}).get("read_only") is not True}
                if writable:
                    continue
                out[f"{skill}::{tool}"] = {
                    "skill": skill, "tool": tool, "path": meta["path"],
                    "subjects_here": tuple(sorted(set(bound) & set(meta["subjects"]))),
                    "reason_kind": "该域**无任何写能力工具** ⇒ 校验器没有可校验的写目标（空转绑定）",
                }
        return out

    # ── 键集（红证的「前提自证」读的就是它们）──

    @property
    def ref_keys(self) -> frozenset:
        return frozenset(self.ref_hits)

    @property
    def guard_keys(self) -> frozenset:
        return frozenset(self.guard_dead)

    @property
    def bind_keys(self) -> frozenset:
        return frozenset(self.bind_dead)

    def keys_of(self, face: str) -> frozenset:
        return {"ref": self.ref_keys, "guard": self.guard_keys, "bind": self.bind_keys}[face]


def ledger() -> dict:
    data = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    assert isinstance(data.get("entries"), list), "台账 `entries` 必须是数组"
    assert isinstance(data.get("anchor"), dict), "台账必须有 `anchor`（燃尽锚点）"
    return data


def scan(sources: dict[str, str] | None = None, book: dict | None = None) -> Scan:
    return Scan(sources if sources is not None else surface_sources(),
                book if book is not None else ledger())


def _ledger_of(book: dict, face: str) -> dict[str, dict]:
    """`face` 下的台账条目：`{现取键: 条目}`（键与现取键**同构** ⇒ 陈旧/涨跌都能逐条比对）。"""
    return {str(e.get("key")): e for e in book["entries"] if e.get("face") == face}


# ══════════════════════════════════════════════════════════════════════════════
# 三、判据（纯函数：Scan → 问题清单；空 = 绿）
# ══════════════════════════════════════════════════════════════════════════════

_REPRO = "复算：python3 -m pytest tests/unit_ci_workflows/test_dead_capability_meta_guard.py -q -s"


def _describe(value) -> str:
    """现取对象的人话描述（`ref` 面是上下文清单；`guard` / `bind` 面是元数据字典）。"""
    if isinstance(value, dict):
        return " ".join(f"{k}={value[k]!r}" for k in sorted(value)[:5])
    return "\n".join(f"      {ctx}" for ctx in list(value)[:4])


def _unledgered(face: str, live: dict, book: dict) -> list[str]:
    out = []
    for key in sorted(set(live) - set(_ledger_of(book, face))):
        out.append(f"**未登记**的死物 `{key}`（命中 {live_hit_counts(face, live)[key]} 处）：\n"
                   f"      {_describe(live[key])}")
    return out


def live_hit_counts(face: str, live: dict) -> dict[str, int]:
    """现取命中数：`ref` 面是**上下文清单**（长度 = 处数）；`guard` / `bind` 面每键 = 一个死物（计 1）。"""
    return {key: (len(value) if isinstance(value, (list, tuple)) else 1)
            for key, value in live.items()}


def _count_mismatch(face: str, live: dict, book: dict) -> list[str]:
    counts = live_hit_counts(face, live)
    out = []
    for key, entry in sorted(_ledger_of(book, face).items()):
        hits = counts.get(key)
        if hits is None:
            out.append(f"台账条目 `{key}` **已陈旧** —— 现取命中 0 ⇒ **删除该条目**（台账只许缩短）")
            continue
        if hits != int(entry.get("hits", -1)):
            direction = "涨" if hits > int(entry.get("hits", -1)) else "跌"
            out.append(f"台账条目 `{key}` 命中数**{direction}**了 —— 台账记 {entry.get('hits')}，"
                       f"现取 {hits}：{_describe(live[key])}")
    return out


def problems_dead_refs(sc: Scan) -> list[str]:
    """**引用面**：模型可见文本点名不可达工具 / skill 自述面点名域外工具 ⇒ **未登记即红**。

    射程（issue #5437 扩面后）＝ ① 工具**类级** `description`；② 工具 schema 的**参数 description**；
    ③ 运行期 `suggestion=` / `message=` 回灌文本；④ prompt / references / agent 直答面。
    ②③ 与 ① **同属注入模型的文本**，且共用同一个判据本体（不另立第二套）。
    """
    bad = _unledgered("ref", sc.ref_hits, sc.ledger)
    if not bad:
        return []
    return [
        "引用面：模型可见文本点名了**任何 skill 都调不到**的工具（模型必然撞 tool_not_found）：\n"
        + "\n".join(f"  - {item}" for item in bad)
        + "\n修法（二选一）：① **改文本** —— 删掉点名，或改成「如实说明已下线 + 引导到后台页面」；"
          "② 确属**有意保留的历史说明** ⇒ 才登记到 `dead_object_ledger.json`（登记 = 可见欠账，不是豁免）。\n"
          "实测读数：死工具（全局不可达）=" + str(sorted(sc.dead_tools)) + "\n" + _REPRO
    ]


def problems_dead_guards(sc: Scan) -> list[str]:
    """**守卫面**：门条件引用的能力标志必须**可能为真**；恒假（工具不可达）⇒ 死标志 / 死守卫。"""
    bad = _unledgered("guard", sc.guard_dead, sc.ledger)
    if not bad:
        return []
    detail = []
    for key in sorted(set(sc.guard_dead) - set(_ledger_of(sc.ledger, "guard"))):
        meta = sc.guard_dead[key]
        detail.append(f"  · `{key}`（{meta.get('kind')}｜{meta.get('reason_kind')}）"
                      f" → 工具={meta.get('tool') or meta.get('tools')}"
                      f"，门条件引用次数={meta.get('gate_refs', 0)}")
    return [
        "守卫面：能力标志**恒假** ⇒ 引用它的门条件**永不触发**（死守卫：静默失效）：\n"
        + "\n".join(detail)
        + "\n修法：① 让被点名的工具**重新可达**（绑回某个 skill）；② 或**删掉恒假的门**"
          "（当常量处理，别留一个永不触发的分支）；③ 确属**有意取反**（如 #5318 后的图片面）"
          "⇒ 登记台账，并在 `reason` 里写明「恒假是有意的」+ 销账方向。\n"
          "实测读数：标志=" + str(sorted(sc.flags)) + "\n" + _REPRO
    ]


def problems_dead_bindings(sc: Scan) -> list[str]:
    """**绑定面**：skill 绑的工具必须**在该域内有可用 action**（只读域不绑写校验器）。"""
    bad = _unledgered("bind", sc.bind_dead, sc.ledger)
    if not bad:
        return []
    detail = [f"  · `{key}`：{meta['reason_kind']}；该域内校验对象={list(meta['subjects_here'])}"
              for key, meta in sorted(sc.bind_dead.items())]
    return [
        "绑定面：校验器被绑在一个**没有可校验写目标**的域上（空转绑定）：\n"
        + "\n".join(detail)
        + "\n修法：**解绑**（该域用不到它），或把工具**收窄为只读**后重新定义它的作用面；"
          "只有在「确属有意保留」时才登记台账。\n"
          "实测读数：校验器=" + str(sorted(sc.validators)) + "\n" + _REPRO
    ]


def problems_ledger_only_shrinks(sc: Scan) -> list[str]:
    """**燃尽靶**：台账 = 冻结清单，**只许缩短**（陈旧条目 / 命中数涨跌 / 锚点被反超 都红）。"""
    problems: list[str] = []
    book = sc.ledger
    live_by_face = {"ref": sc.ref_hits, "guard": sc.guard_dead, "bind": sc.bind_dead}
    for face in MY_FACES:
        problems += _count_mismatch(face, live_by_face[face], book)
    for entry in book["entries"]:
        key = str(entry.get("key"))
        reason = str(entry.get("reason") or "").strip()
        issue = str(entry.get("issue") or "").strip()
        origin = str(entry.get("origin") or "").strip()
        if entry.get("face") not in MY_FACES:
            problems.append(f"台账条目 `{key}`：`face` 非法（{entry.get('face')!r}）—— 只认 {list(MY_FACES)}")
        if len(reason) < 8:
            problems.append(f"台账条目 `{key}`：`reason` 缺失或过短（{reason!r}）")
        if not re.fullmatch(r"#\d{3,}", issue):
            problems.append(f"台账条目 `{key}`：`issue` 缺失或不是单号（{issue!r}）")
        if not re.fullmatch(r"#\d{3,}", origin):
            problems.append(f"台账条目 `{key}`：`origin` 缺失或不是单号（{origin!r}）"
                            "—— 必须写明**造成该死物**的单号（不是冻结来源）")
        if not isinstance(entry.get("hits"), int) or int(entry["hits"]) < 1:
            problems.append(f"台账条目 `{key}`：`hits` 必须是 ≥1 的整数（现取条数）")
    anchor = book["anchor"]
    for face in MY_FACES:
        entries = len(_ledger_of(book, face))
        hits = sum(live_hit_counts(face, live_by_face[face]).values())
        if entries > int(anchor.get(face, -1)):
            problems.append(
                f"燃尽靶 [{face}]：台账条数 **{entries} > 锚点 {anchor.get(face)}** —— 台账只许缩短；"
                "确需登记**新债务** ⇒ 同 PR 显式上调 `anchor`（一次可评审的动作），否则先修掉它")
        if hits > int(anchor.get(f"{face}_hits", -1)):
            problems.append(
                f"燃尽靶 [{face}]：现取命中数 **{hits} > 锚点 {anchor.get(f'{face}_hits')}** —— 现取涨了，先修再谈登记")
    if not problems:
        return []
    return ["燃尽靶（台账只许缩短，涨跌都红）：\n" + "\n".join(f"  - {p}" for p in problems)
            + "\n（修好一处 ⇒ **同 PR 删除/下调对应条目**；台账不是豁免，是欠账清单。）\n" + _REPRO]


def problems_unregistered_hint_builders(sources: dict[str, str]) -> list[str]:
    """**新面的射程元守卫**（issue #5437）：`suggestion=` 只应出现在**模型可见的上报点**上。

    射程 = `MODEL_VISIBLE_BUILDERS`。若有人新造一个包装器（`my_hint(suggestion=...)`）而该
    `suggestion` 又**真的注入模型**，它就落在面外 ⇒ 本判据判红、逼作者**登记那个构造点**
    （而不是让文本静默免检 —— §23 G5「判定面之外 = 永久免检」）。
    """
    out: list[str] = []
    for key, text in sorted(sources.items()):
        if not key.startswith("tool:"):
            continue
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.Call):
                continue
            if not any(kw.arg == "suggestion" for kw in node.keywords):
                continue
            called = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if called not in MODEL_VISIBLE_BUILDERS:
                out.append(
                    f"`app/tools/{key.split(':', 1)[1]}` 的 `{called}(suggestion=...)` 不在射程声明 "
                    f"{list(MODEL_VISIBLE_BUILDERS)} 里 ⇒ 该 suggestion 文本**不在引用面射程内**。"
                    "出口：把该构造点加进 `MODEL_VISIBLE_BUILDERS`（那是射程声明），或改走已登记的构造点")
    return out


def problems_range_face_is_reused(judgements: dict, injections: dict, own_ledger: dict) -> list[str]:
    """**射程面不得重造**（验收判据 4）：上游 `MC-021 判据 7` 必须**在位且带注入式红证**，
    且本文件的判据表 / 台账**都不含射程面**。

    参数化（judgements / injections / own_ledger 作入参）⇒ 可用**负控**证明它真会红
    （见 `test_range_face_reuse_check_can_go_red`）。
    """
    out = []
    fn = judgements.get(RANGE_FACE_LABEL)
    if fn is None:
        out.append(f"上游射程面判据 `{RANGE_FACE_LABEL}` 不在 `JUDGEMENTS` 里 —— 射程面失守")
    covered = {f for _k, _m, f in injections.values()}
    if fn is not None and fn not in covered:
        out.append("上游射程面判据没有**注入式红证**（上游不完整 ⇒ 它可能是空断言）")
    if "range" in MY_FACES:
        out.append("本文件把射程面又建了一遍 —— `MY_FACES` 里不得出现射程面")
    for entry in own_ledger.get("entries", []):
        if "range" in str(entry.get("face", "")) or "射程" in str(entry.get("key", "")):
            out.append(f"台账里出现射程面条目 `{entry.get('key')}` —— 射程面归 MC-021 判据 7 管")
    return out


JUDGEMENTS = {
    "引用面 · 死引用（点名不可达工具）": problems_dead_refs,
    "守卫面 · 死标志 / 死守卫（恒假门条件）": problems_dead_guards,
    "绑定面 · 死绑定（只读域绑写校验器）": problems_dead_bindings,
    "燃尽靶 · 台账只许缩短": problems_ledger_only_shrinks,
}


# ══════════════════════════════════════════════════════════════════════════════
# 四、断言
# ══════════════════════════════════════════════════════════════════════════════


def test_every_judgement_is_green() -> None:
    """四条判据在**当前仓库**上全绿（红 ⇒ 出现新死物 / 台账该销账了；逐条问题见断言文案）。"""
    sc = scan()
    bad = {label: fn(sc) for label, fn in JUDGEMENTS.items()}
    bad = {label: items for label, items in bad.items() if items}
    assert not bad, "能力下线族判据未通过：\n" + "\n".join(
        f"  【{label}】\n" + "\n".join(f"    - {item}" for item in items) for label, items in bad.items())


def test_surfaces_are_fail_closed() -> None:
    """判定面必须**非空且可解释**（取不到 ⇒ 报错，不许静默空跑成绿 —— 本文件最大的自伤形态）。"""
    sc = scan()
    readout = {
        "工具类": len(sc.tools), "skill 绑定": len(sc.skills),
        "注入模型的 prompt 文本": len(sc.prompts), "工具 description（类级）": len(sc.descriptions),
        "schema 参数 description": len(sc.params),
        "运行期 suggestion / message 文本": sum(sc.runtime_sites.values()),
        "references md": len([k for k in surface_sources() if k.startswith("ref:")]),
        "工具名常量（能力标志）": len(sc.flags), "能力谓词": len(sc.predicates),
        "校验器类工具": len(sc.validators),
    }
    print("[判据面读数] " + str(readout))
    empty = [name for name, n in readout.items() if n < 1]
    assert not empty, f"判定面取空（glob/解析失效）⇒ 本守卫会静默空跑成绿：缺 {empty}"
    assert len(sc.prompts) >= 12, (
        f"注入模型的 prompt 文本只解析出 {len(sc.prompts)} 条（<12）⇒ 引用面射程不足："
        "prompt 经**模块常量名**传入时必须走 `_resolve_text`，否则得到 0 条而判据全绿"
    )
    assert len(sc.descriptions) >= 40, f"工具 description 只解析出 {len(sc.descriptions)} 条（<40）⇒ 射程不足"
    assert len(sc.params) >= 200, (
        f"schema 参数 description 只解析出 {len(sc.params)} 条（<200）⇒ **新面空跑成绿**："
        "`parameters` 字面量**和它调用的模块级工厂函数**（`app/tools/stock_semantics.py` 的 "
        "`low_stock_alert_threshold_schema`，参数 schema 的共享单点来源）都要走到"
    )
    assert sum(sc.runtime_sites.values()) >= 250, (
        f"运行期 suggestion / message 只解析出 {sum(sc.runtime_sites.values())} 处（<250）⇒ 新面空跑成绿："
        "文本常经**局部变量**传入（`suggestion=suggestion`）⇒ 必须按所在函数作用域解析"
    )
    frozen = set(UNRESOLVED_RUNTIME_SITES)
    live = set(sc.unresolved_runtime)
    assert live <= frozen, (
        "有运行期文本取不到字面量 ⇒ 判据看不见它（**静默免检**）："
        f"{sorted(live - frozen)}（位置 { {k: sc.unresolved_runtime[k] for k in sorted(live - frozen)} }）"
        " —— 出口：把文本**内联**到构造点，或扩展本判据的解析（**不要**登记豁免）"
    )
    assert frozen <= live, (
        f"冻结账户已**陈旧**（这些站点现在能取到文本了）⇒ 只许缩短，删掉 {sorted(frozen - live)}"
    )


def test_burn_down_anchor_is_printed() -> None:
    """**现取打印**燃尽锚点（§23 G2）：台账条数 / 命中数 / 现取命中数 / 死工具与不判表读数。"""
    sc = scan()
    for face in MY_FACES:
        live = {"ref": sc.ref_hits, "guard": sc.guard_dead, "bind": sc.bind_dead}[face]
        print(f"[燃尽锚点 {face}] 台账条数={len(_ledger_of(sc.ledger, face))} / "
              f"台账命中数={sum(int(e['hits']) for e in _ledger_of(sc.ledger, face).values())} / "
              f"现取条数={len(live)} / 现取命中数={sum(live_hit_counts(face, live).values())}")
    print("[引用面 · 各文本面现取读数] " + str({
        "tool.description（类级，注入模型）": len(sc.descriptions),
        "param.description（schema 注入）": len(sc.params),
        "runtime.suggestion / message（运行期回灌）": f"{len(sc.runtime)} 个构造点 / "
                                                     f"{sum(sc.runtime_sites.values())} 处",
        "skill.prompt（各 persona）": len(sc.prompts),
        "skill.references（md）": len([k for k in surface_sources() if k.startswith("ref:")]),
    }))
    print("[死工具（全局不可达；**有意保留文件**，不入燃尽靶）] " + str(sorted(sc.dead_tools)))
    by_face: dict[str, int] = {}
    for key in sc.ref_not_judged:
        by_face[key.split(":", 1)[0]] = by_face.get(key.split(":", 1)[0], 0) + 1
    print("[显式不判表 · 域外点名（域内可达但不在本工具作用域；跨 persona 反例文风 / 多域共享文本）] "
          f"{len(sc.ref_not_judged)} 条："
          + " / ".join(f"{k}={v}" for k, v in sorted(by_face.items())))
    for key in sorted(sc.ref_not_judged):
        print(f"    - {key} × {len(sc.ref_not_judged[key])}")
    assert len(sc.dead_tools) >= 1, (
        "「全局不可达工具」现取为 0 ⇒ 引用面 / 守卫面的**前提**消失（读源坏了？还是全被绑回去了？）。"
        "出口（二选一，都是显式动作）：① 若绑回是**真的**（产品能力回来了）⇒ 同 PR 清空台账的 ref / guard 条目"
        "+ 删除本断言（判据已无对象）；② 否则先修读源 —— 不要靠加台账条目吸收"
    )


def test_range_face_is_reused_not_rebuilt() -> None:
    """**不重复建射程面**（验收判据 4）：判它在上游在位 + 带红证，并**直接调用**它（不是抄一份）。"""
    problems = problems_range_face_is_reused(mc.JUDGEMENTS, mc._injections(), ledger())
    assert not problems, "射程面复用检查失败：\n" + "\n".join(f"  - {p}" for p in problems)
    assert mc.problems_declared_persona_tools_are_controlled(mc.world()) == [], (
        "上游射程面判据在当前树上判红 ⇒ 先修它（本文件不接管它的职责）"
    )
    assert mc.JUDGEMENTS[RANGE_FACE_LABEL] is mc.problems_declared_persona_tools_are_controlled, (
        "上游 `JUDGEMENTS` 的那个键不再是射程面判据函数（被替换 / 改名）⇒ 复用前提失效"
    )


def test_range_face_reuse_check_can_go_red() -> None:
    """负控 + **前提自证**：复用的三个前提任一被破坏时，上面那条检查**真的会红**。"""
    assert problems_range_face_is_reused(mc.JUDGEMENTS, mc._injections(), ledger()) == [], (
        "对照组：未破坏时复用检查必须全绿（否则红证无从归因）"
    )
    trimmed = {k: v for k, v in mc.JUDGEMENTS.items() if k != RANGE_FACE_LABEL}
    assert problems_range_face_is_reused(trimmed, mc._injections(), ledger()), (
        "把射程面判据从上游判据表摘掉 ⇒ 复用检查必须红（否则它是空检查）"
    )
    no_proof = {k: v for k, v in mc._injections().items()
                if v[2] is not mc.problems_declared_persona_tools_are_controlled}
    assert problems_range_face_is_reused(mc.JUDGEMENTS, no_proof, ledger()), (
        "把射程面判据的红证摘掉 ⇒ 复用检查必须红（否则「上游有红证」这个前提是空的）"
    )
    booked = dict(ledger())
    booked["entries"] = list(booked["entries"]) + [
        {"face": "range", "key": "range|孤儿|负控示例", "hits": 1, "reason": "负控用条目", "issue": "#5331"}]
    assert problems_range_face_is_reused(mc.JUDGEMENTS, mc._injections(), booked), (
        "台账里出现射程面条目 ⇒ 复用检查必须红（射程面归上游管）"
    )


def test_ledger_entries_are_registered_with_reason_and_issue() -> None:
    """台账每条必须带 `reason` + 单号（**登记是可见欠账，不是豁免**）—— 由燃尽靶判据统一执行。"""
    sc = scan()
    print(f"台账现取条数={len(sc.ledger['entries'])}（锚点={sc.ledger['anchor']}）")
    problems = [p for p in problems_ledger_only_shrinks(sc)
                if any(f in p for f in ("reason", "issue", "origin"))]
    assert not problems, "台账条目不合规：\n" + "\n".join(f"  - {p}" for p in problems)


# ══════════════════════════════════════════════════════════════════════════════
# 五、注入式红证（§23 G7：**前提自证** —— 注入生效 + 判据真的看见了新对象 + 判据真红）
# ══════════════════════════════════════════════════════════════════════════════


def _point_at(surface_key: str, text: str, phrase: str) -> str:
    """在某条注入文本里加一句**非否定**的指路 —— 模拟「又有人点了不可达工具的名」。"""
    assert phrase in text, f"注入锚点失配：{surface_key} 里没有 {phrase!r}（同步本判据）"
    return text.replace(phrase, f"需要时用 order_manage 处理。{phrase}", 1)


def _with_ref_entry(book: dict, key: str, hits: int) -> dict:
    """**台账侧注入**：给 `key` 加一条格式合规的 `ref` 条目（只用于红证，**不写进真台账**）。

    ⚠️ 为什么红证要能从**台账侧**造（issue #5400）：ref 面 9 条已**全量销账** ⇒
    「条目陈旧 / 命中数涨」这两种红证**不能**再靠「现取的存量死引用」制造 ——
    那样 red proof 与被测缺陷**同生共死**（缺陷修好 ⇒ 红证自己失效）。
    台账侧注入把前提自证换成「台账变了 + 该键现取为 0」，与现取面是否干净无关。
    """
    out = json.loads(json.dumps(book, ensure_ascii=False))
    out["entries"] = list(out["entries"]) + [{
        "face": "ref", "key": key, "hits": hits,
        "reason": "红证用条目（台账侧注入，不得写进真台账）", "issue": "#5400", "origin": "#5247",
    }]
    return out


def _injections() -> dict[str, tuple]:
    """`label` → (源键, 源内变异, 红证形态, 面, 现取键[, 台账变异])。

    · 形态 `new`   = 判据必须在现取集里**看见新对象**并变红（面判据）；
    · 形态 `stale` = 台账条目**已陈旧**（该键现取 0）⇒ 燃尽靶判据必须红；
    · 形态 `grown` = 同一条目**命中数上涨**（台账记 1、现取 2）⇒ 燃尽靶判据必须红。
    「面 + 现取键」是红证**前提自证**比对的**不可变标识**（不看措辞、不看锚点是否存在）。
    第 6 项（可选）= 台账变异：给了它 ⇒ 前提自证改为「台账确实变了」（见 `_with_ref_entry`）。
    """
    return {
        "① 工具 description 又点名 `order_manage`（死引用）⇒ 引用面红": (
            "tool:briefing_query.py",
            lambda s: _point_at("tool:briefing_query.py", s, "【标注】READONLY"),
            "new", "ref", "tool:briefing_query::order_manage",
        ),
        "①b skill 自述提示词点名域外工具 ⇒ 引用面红": (
            "skill:knowledge_skill.py",
            lambda s: s.replace("## 核心原则", "需要时用 order_manage 处理。\n\n## 核心原则", 1),
            "new", "ref", "skill:knowledge_skill.py::mibao::order_manage",
        ),
        "② 新增一个恒假标志（指向不可达工具）⇒ 守卫面红": (
            "skill:base_skill.py",
            lambda s: s.replace('ORDER_WRITE_TOOL = "order_create"',
                                'LEGACY_WRITE_TOOL = "order_manage"\nORDER_WRITE_TOOL = "order_create"', 1),
            "new", "guard", "base_skill.py::LEGACY_WRITE_TOOL",
        ),
        "②b 把一个**可达**标志改指不可达工具（`ORDER_WRITE_TOOL` → product_manage）⇒ 守卫面红": (
            "skill:base_skill.py",
            lambda s: s.replace('ORDER_WRITE_TOOL = "order_create"',
                                'ORDER_WRITE_TOOL = "product_manage"', 1),
            "new", "guard", "base_skill.py::ORDER_WRITE_TOOL",
        ),
        "③ 只读域新增一条校验器绑定（knowledge 域绑 validate_input）⇒ 绑定面红": (
            "skill:knowledge_skill.py",
            lambda s: re.sub(r"(KNOWLEDGE_TOOLS\s*=\s*\[)", r'\1\n    "validate_input",', s, count=1),
            "new", "bind", "knowledge::validate_input",
        ),
        "④ 台账条目**陈旧**（把 settings 的 validate_input 解绑 ⇒ 该条目现取命中 0）⇒ 燃尽靶红": (
            "skill:settings_skill.py",
            lambda s: s.replace('"validate_input", ', "", 1),
            "stale", "bind", "settings::validate_input",
        ),
        "④b 台账命中数**涨**（台账记 1、现取 2）⇒ 燃尽靶红": (
            "tool:order_query.py",
            lambda s: _point_at(
                "tool:order_query.py", _point_at("tool:order_query.py", s, "【链条】"), "【链条】"),
            "grown", "ref", "tool:order_query::order_manage",
            lambda book: _with_ref_entry(book, "tool:order_query::order_manage", hits=1),
        ),
        "④c 台账条目**陈旧**（ref 面已销账、条目还在）⇒ 燃尽靶红": (
            "tool:order_query.py",
            lambda s: s,
            "stale", "ref", "tool:order_query::order_manage",
            lambda book: _with_ref_entry(book, "tool:order_query::order_manage", hits=1),
        ),
        "⑥ **schema 参数 description** 点名 `order_manage`（本单新面）⇒ 引用面红": (
            "tool:validate_input.py",
            lambda s: _point_at("tool:validate_input.py", s, "要校验的目标写工具，如 order_create"),
            "new", "ref", "param:validate_input.target_tool::order_manage",
        ),
        "⑦ 运行期 **suggestion** 点名 `order_manage`（本单新面）⇒ 引用面红": (
            "tool:order_create.py",
            lambda s: _point_at("tool:order_create.py", s, "请向顾客确认单价后填写大于 0 的金额（如 168）"),
            "new", "ref", "sugg:order_create::order_manage",
        ),
        "⑦b 运行期 **message**（提示文本，与 suggestion 同面）点名 `order_manage` ⇒ 引用面红": (
            "tool:order_create.py",
            lambda s: _point_at("tool:order_create.py", s, "服务端要求单价必须大于 0 元"),
            "new", "ref", "msg:order_create::order_manage",
        ),
    }


_FACE_JUDGEMENT = {
    "ref": "引用面 · 死引用（点名不可达工具）",
    "guard": "守卫面 · 死标志 / 死守卫（恒假门条件）",
    "bind": "绑定面 · 死绑定（只读域绑写校验器）",
    "ledger": "燃尽靶 · 台账只许缩短",
}


def test_every_judgement_can_go_red() -> None:
    """**每条**判据都要有能单独变红的注入，且**前提自证**：注入生效 + 判据看见了新对象 + 判据真红。"""
    base_sources = surface_sources()
    base = scan(base_sources, ledger())
    green = {label: fn(base) for label, fn in JUDGEMENTS.items()}
    assert all(not v for v in green.values()), (
        "对照组：未注入时四条判据必须全绿（否则红证无从归因）：\n"
        + "\n".join(f"  【{k}】{v[:2]}" for k, v in green.items() if v)
    )
    covered = {_FACE_JUDGEMENT["ledger" if spec[2] in ("stale", "grown") else spec[3]]
               for spec in _injections().values()}
    orphans = sorted(set(JUDGEMENTS) - covered)
    assert not orphans, f"判据表里有**没有红证**的判据（= 空断言）：{orphans}"
    for label, spec in _injections().items():
        key, mutate, kind, face, live_key = spec[:5]
        book_mutate = spec[5] if len(spec) > 5 else None
        sources = dict(base_sources)
        assert key in sources, f"{label}：源键 {key} 不在判据面内（注入打在面外 = 空注入）"
        sources[key] = mutate(sources[key])
        book = book_mutate(ledger()) if book_mutate else ledger()
        if book_mutate is None:
            assert sources[key] != base_sources[key], f"{label}：**注入没生效**（锚点失配）—— 同步本判据"
        else:
            assert book != ledger(), f"{label}：**台账注入没生效**（锚点失配）—— 同步本判据"
        mutated = scan(sources, book)
        if kind == "stale":
            assert live_key not in mutated.keys_of(face), (
                f"{label}：期望 `{live_key}` 从现取集里**消失**（那才是陈旧），但它还在"
            )
            problems = problems_ledger_only_shrinks(mutated)
            assert any("陈旧" in p for p in problems), (
                f"{label}：陈旧条目没让燃尽靶判据**按「陈旧」**判红 ⇒ 空断言：{problems}")
            continue
        if kind == "grown":
            assert len(mutated.ref_hits.get(live_key, ())) > 1, (
                f"{label}：命中数没涨到 ≥2（现取 {len(mutated.ref_hits.get(live_key, ()))}）⇒ 注入是空的"
            )
            problems = problems_ledger_only_shrinks(mutated)
            assert any("涨" in p for p in problems), (
                f"{label}：命中数涨了但燃尽靶判据没**按「涨」**判红 ⇒ 空断言：{problems}")
            continue
        added = mutated.keys_of(face) - base.keys_of(face)
        assert live_key in added, (
            f"{label}：判据**没看见**期望的新对象 `{live_key}`（现取新增={sorted(added)}）—— "
            "注入生效了但没落进判定面（面取窄了）"
        )
        fn = {"ref": problems_dead_refs, "guard": problems_dead_guards,
              "bind": problems_dead_bindings}[face]
        assert fn(mutated), f"{label}：判据没有变红 ⇒ 它是空断言"


def test_negation_filter_is_discriminating() -> None:
    """负控：**被否定**的死工具点名**不**进现取集（证明本判据不是「见名就红」）。

    本仓的反例文风（「不得改用 `aftersale_create`」/「本 skill 无 knowledge_search」）若被一刀切，
    会把**正确文本**整片喂红（§17.3「判据被自己的文案喂红」）—— 故否定过滤本身必须有判别力。
    """
    base_sources = surface_sources()
    key = "tool:briefing_query.py"
    sources = dict(base_sources)
    sources[key] = sources[key].replace(
        "【标注】READONLY", "不要用 order_manage 处理；【标注】READONLY", 1)
    assert sources[key] != base_sources[key], "负控注入没生效（锚点失配）—— 同步本判据"
    mutated = scan(sources, ledger())
    assert "tool:briefing_query::order_manage" not in mutated.ref_keys, (
        "被否定的点名进了现取集 ⇒ 否定过滤失效（会把反例文风整片判红）"
    )


def test_suggestion_kwarg_is_only_on_registered_builders() -> None:
    """**射程元守卫 + 负控**：新造一个带 `suggestion=` 的构造点 ⇒ 必须判红。

    没有它，新面的射程可以被**静默缩小**（有人加个包装器把 suggestion 挪到面外 ⇒ 判据不再看得见它）。
    """
    sources = surface_sources()
    problems = problems_unregistered_hint_builders(sources)
    assert not problems, "有 `suggestion=` 落在**未登记**的构造点上：\n" + "\n".join(f"  - {p}" for p in problems)
    key = "tool:order_create.py"
    mutated = dict(sources)
    mutated[key] = sources[key] + (
        "\n\ndef _unregistered_hint(text: str):\n"
        "    return my_hint(suggestion=text)\n")
    assert mutated[key] != sources[key], "负控注入没生效（锚点失配）"
    red = problems_unregistered_hint_builders(mutated)
    assert any("my_hint" in p for p in red), (
        f"未登记的 `suggestion=` 构造点没判红 ⇒ 射程元守卫是空断言：{red}")


def test_out_of_domain_mentions_are_not_judged() -> None:
    """**验收判据 5（不误伤「域外点名」档）**：域内**可达**但不在本工具作用域的点名 ⇒ 进**显式不判表**，不判红。

    本仓有跨 persona「反例式指路」的既定文风，且**注入模型的文本多域共享**（工具 description /
    `parameters` 的参数描述 / 运行期 suggestion 都由多个域共用一份）⇒ 一刀切会把**正确文本**整片喂红
    （§17.3「判据被自己的文案喂红」）。故 #5331 有意**只判「全局不可达」这一档**（点了必然 `tool_not_found`）；
    本单把射程扩到参数 description 与运行期文本时**继承同一条收窄**，不另立第二套口径。
    """
    base_sources = surface_sources()
    base = scan(base_sources, ledger())
    # 活例取 #5400 / PR #5435 明写「**一字未动**」的那一档（C 端只读工具描述里的 `order_query`）
    live = "tool:customer_address_query::order_query"
    assert live in base.ref_not_judged, (
        f"活例 `{live}` 不在显式不判表里 ⇒ 域外点名档被误判红"
        f"（现取不判表={sorted(base.ref_not_judged)}）"
    )
    assert live not in base.ref_keys, "活例进了判红集 ⇒ 域外点名被一刀切"
    assert problems_dead_refs(base) == [], "域外点名被误判红（本仓反例文风会被整片喂红）"
    # 注入式负控（**本单新面**）：往**参数 description** 里再加一个「可达但域外」的工具 ⇒ 仍不判红，只是不判表多一条
    key = "tool:validate_input.py"
    phrase = "要校验的目标写工具，如 order_create"
    assert phrase in base_sources[key], "负控注入锚点失配（同步本判据）"
    sources = dict(base_sources)
    sources[key] = sources[key].replace(phrase, f"{phrase}，或 sku_update", 1)
    assert sources[key] != base_sources[key], "负控注入没生效（锚点失配）"
    mutated = scan(sources, ledger())
    added = set(mutated.ref_not_judged) - set(base.ref_not_judged)
    assert added == {"param:validate_input.target_tool::sku_update"}, (
        f"新增的域外点名没进**不判表**（现取新增={sorted(added)}）⇒ 收窄档被破坏"
    )
    assert not (mutated.ref_keys & added), "域外点名进了判红集 ⇒ 会喂红正确文本"
    assert problems_dead_refs(mutated) == [], "域外点名让引用面判红 ⇒ 判据 5 失守"
    assert not problems_dead_refs(mutated), "被否定的点名让引用面判红 ⇒ 同上"