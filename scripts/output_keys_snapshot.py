#!/usr/bin/env python3
"""产出键快照生成器 / 刷新入口 / 新鲜度校验（issue #3729）。

## 这是什么

`output_verify: [{tool: …, expect: {<键名>: <值>}}]` 的 **L0 键名校验**要回答一个问题：
**「这个键名，是该工具能产出的键吗？」** 在 #3729 之前这个问题**不可回答** —— 工具源码里
没有产出 schema，唯一的候选源（「扫工具源码里 `data=` 的字面键并集」）**连正确答案都
表达不出来**（`data=<变量>` / `**response.get("data")` 形态在工具里是常态）。

本生成器把「产出键」变成**机器可读快照**（`tests/agent_eval/output_keys_snapshot.json`）：

    python3 scripts/output_keys_snapshot.py --refresh    # 刷新快照（改了工具产出键才跑）
    python3 scripts/output_keys_snapshot.py --check      # 新鲜度校验（快照 ≠ 源码推导 ⇒ 非零退出）
    python3 scripts/output_keys_snapshot.py --verdicts   # 逐条打印用例里 expect 键的判定
    python3 scripts/output_keys_snapshot.py --legacy-verdicts  # 复算 #3729 记录的旧口径误判

## 怎么推的（每个键的来源，逐条有出处）

输入 = `backend/ai-agent-service/app/tools/*.py` 的 **AST**（不是原文文本：注释与
docstring 不是 AST 节点 ⇒ 结构上不可能被读成声明）。

对每个工具类（`name = "<工具名>"`），扫**成功** `ToolResult(...)` 的 `data=` 实参，
按键的来源分三档解析（`**` 展开、`Name` 回指同函数赋值、`Call` 回指同模块函数返回值）：

| 形态 | 例（都在本仓工具里真的存在） | 解析结果 |
|---|---|---|
| 字面 dict | `data={"items": items, "total": total}` | 键 = `items` / `total` |
| `**` 展开 + 字面 | `data={**quote, "config_source": …}` | 递归进 `quote`（见下条） |
| `Name` → 同函数 dict | `data=quote`，`quote = {…}`（`curtain_calc.build_quote`） | `quote` 那个 dict 的字面键 |
| `Name` → 本地函数返回 | `quote = build_quote(…)` | 该函数 `return` 的 dict 键（同模块、有深度上限） |
| `Name` 下标写键 | `quote["panels"] = panels` | 补 `panels`（条件出键 ⇒ 该工具仍算「形状不定」） |
| 后端透传 | `ticket_data = response.get("data", {})` … `data=ticket_data` | **透传**：本工具从上游 payload 里**读过**的键（`.get("k")` / `["k"]`）算它能产出；整体标 `dynamic` |

**多 action 工具**按 action 归属：读 `execute()` 的 `if action == "<字面量>"` / `elif` 分支里
`self._method(...)` 的调用点（以及 `{<action>: self._method}` 字典派发表），把该方法内的产出键
记到该 action 名下（`actions: {<action>: {keys, dynamic}}`）；归属不出来的 action 进
`actions_unattributed`（**显式登记，不猜**）。

## 看不到什么（照实登记，不粉饰）

1. **后端 DTO 字段**：`data=<响应体>` 的键由 admin-api 的 Java DTO 决定，本生成器**不解析 Java**
   —— 只能给出「该工具从后端读过的键」+ `dynamic: true`。⇒ 声明了 `replayed`（来自
   `ClientRequestIdService.replay` 的快照字段，工具侧不读它）这类键时，判定只能是
   **unknown（形状不定）**，不是「不可能」。
2. **条件出键**：`if x: quote["k"] = v` 与 `**(…) if cond else {}` ⇒ 键可能缺席；本生成器把
   这类工具标 `dynamic: true`（**宁可说不知道，不伪造确定**）。
3. **运行期改名 / 后端裁剪**：工具把上游 dict 原样透传时，上游少给一个键 ⇒ 运行期没有该键，
   本快照**说不出**这件事（`output_verify` 运行期才是那一层的判据）。
4. **非 `ToolResult` 出口**：工具若通过别的数据结构产生产出（本仓当前没有），本生成器看不见。

## 与守卫的分工

生成器只负责「**能推的推出来，推不出的显式登记**」；判红在
`tests/unit_ci_workflows/test_assertion_specs_wellformed.py::TestOutputKeysAreProducible`：
快照不新鲜 ⇒ 红；声明的键「静态不可能」⇒ 红；「形状不定/工具不在快照里」⇒ 红**除非**在
`tests/agent_eval/output_keys_unknown_ledger.json` 里逐条登记（未登记即红，登记条目必须活着）。
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "tools"
SNAPSHOT_PATH = REPO_ROOT / "tests" / "agent_eval" / "output_keys_snapshot.json"
LEDGER_PATH = REPO_ROOT / "tests" / "agent_eval" / "output_keys_unknown_ledger.json"
TOOLS_REL = "backend/ai-agent-service/app/tools"
SCHEMA = 1

#: `Name` → 赋值的递归深度上限（`quote → build_quote → …`）：超过即判「形状不定」，不猜。
_MAX_DEPTH = 6
#: 每个工具保留的「形状不定」出处条数上限（快照要能被人读，不是日志转储）。
_MAX_NOTES = 4


# ══════════════════════════════════════════════════════════════════════════════
# 一、从 AST 推导产出键
# ══════════════════════════════════════════════════════════════════════════════
class _Keys:
    """一个 `data=` 出口（或一组出口）的键集合。`literal` 只留**字面写成**的键。"""

    __slots__ = ("keys", "literal", "dynamic", "notes", "sites")

    def __init__(self) -> None:
        self.keys: set = set()
        self.literal: set = set()
        self.dynamic = False
        self.notes: set = set()
        #: 见到过几个**成功**的 `data=` 出口（0 ⇒ 这一段根本没有产出面 ⇒ 不能判「静态」）
        self.sites = 0

    def merge(self, other: "_Keys") -> "_Keys":
        self.keys |= other.keys
        self.literal |= other.literal
        self.dynamic = self.dynamic or other.dynamic
        self.notes |= other.notes
        self.sites += other.sites
        return self

    def as_entry(self) -> dict:
        return {"keys": sorted(self.keys), "dynamic": self.dynamic}


def _module_functions(tree: ast.Module) -> dict:
    """模块级函数（`Name` → `Call` 回指的解析靶，如 `build_quote`）。"""
    return {n.name: n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _class_attr_str(cls: ast.ClassDef, name: str):
    """类体里 `name = "<字面量>"`（只认类体直接赋值，不钻方法体 —— 避免把普通局部变量读成声明）。"""
    for n in cls.body:
        if isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in n.targets):
            if isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
                return n.value.value
    return None


def _class_attr_str_set(cls: ast.ClassDef, name: str) -> set:
    """类体里 `VALID_ACTIONS = {…}` 的字面量成员。"""
    for n in cls.body:
        if isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in n.targets):
            v = n.value
            if isinstance(v, (ast.Set, ast.List, ast.Tuple)):
                return {e.value for e in v.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return set()


def _action_enum(cls: ast.ClassDef) -> set:
    """schema 里 `parameters.properties.action.enum` 的字面量（结构化下钻，不扫原文）。"""
    out = set()
    for n in cls.body:
        if not (isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "parameters" for t in n.targets)):
            continue
        node = n.value
        for part in ("properties", "action", "enum"):
            hit = None
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if isinstance(k, ast.Constant) and k.value == part:
                        hit = v
                        break
            if hit is None:
                return set()
            node = hit
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            out |= {e.value for e in node.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        return out
    return out


class _Extractor:
    """一个工具类的方法体 → 产出键。`resolve=False` 时退化成 #3729 记录的**旧口径**（只读字面键）。"""

    def __init__(self, fnmap: dict, resolve: bool = True) -> None:
        self.fnmap = fnmap
        self.resolve = resolve

    # ── 表达式 → 键 ──────────────────────────────────────────────────────────
    def keys_of(self, node, fn, depth: int = 0) -> _Keys:
        out = _Keys()
        if node is None or depth > _MAX_DEPTH:
            out.dynamic = True
            return out
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if k is None:                                  # `**expr`
                    if self.resolve:
                        sub = self.keys_of(v, fn, depth + 1)
                        out.merge(sub)                          # 显式展开的来源也标 dynamic
                        out.dynamic = True
                        out.notes.add(f"**{ast.unparse(v)[:60]}")
                    else:
                        out.dynamic = True
                elif isinstance(k, ast.Constant) and isinstance(k.value, str):
                    out.keys.add(k.value)
                    out.literal.add(k.value)
                else:
                    out.dynamic = True
            return out
        if not self.resolve:
            out.dynamic = True
            return out
        if isinstance(node, ast.Name):
            vals = [n.value for n in ast.walk(fn) if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == node.id for t in n.targets)]
            vals += [n.value for n in ast.walk(fn) if isinstance(n, ast.AnnAssign)
                     and isinstance(n.target, ast.Name) and n.target.id == node.id
                     and n.value is not None]
            if not vals:
                out.dynamic = True
                out.notes.add(f"{node.id}=<无本地赋值>")
                return out
            for v in vals:
                out.merge(self.keys_of(v, fn, depth + 1))
                # 赋值自响应体/上游 ⇒ 透传：整体形状不定
                if isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute):
                    out.dynamic = True
                    out.notes.add(f"{node.id} ← {ast.unparse(v)[:60]}")
            # `name["k"] = …`（条件出键）
            for n in ast.walk(fn):
                if isinstance(n, ast.Assign):
                    for t in n.targets:
                        if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) \
                                and t.value.id == node.id:
                            s = t.slice
                            if isinstance(s, ast.Constant) and isinstance(s.value, str):
                                out.keys.add(s.value)
                                out.dynamic = True
            return out
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            target = self.fnmap.get(node.func.id)
            if target is None:
                out.dynamic = True
                out.notes.add(f"data={ast.unparse(node)[:60]}")
                return out
            return self.returns_of(target, depth + 1)
        if isinstance(node, ast.IfExp):
            out.merge(self.keys_of(node.body, fn, depth + 1))
            out.merge(self.keys_of(node.orelse, fn, depth + 1))
            out.dynamic = True
            return out
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            out.merge(self.keys_of(node.left, fn, depth + 1))
            out.merge(self.keys_of(node.right, fn, depth + 1))
            return out
        out.dynamic = True
        out.notes.add(f"data={ast.unparse(node)[:60]}")
        return out

    def returns_of(self, fn, depth: int = 0) -> _Keys:
        out = _Keys()
        for n in ast.walk(fn):
            if isinstance(n, ast.Return) and n.value is not None:
                out.merge(self.keys_of(n.value, fn, depth + 1))
        return out

    def _passthrough_reads(self, fn, var: str) -> set:
        """`var` 是上游 payload 时，从它身上读过的**字面**键（读过 ⇒ 该键在产出里存在）。"""
        ks = set()
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                    and n.func.attr == "get" and isinstance(n.func.value, ast.Name) \
                    and n.func.value.id == var and n.args:
                a = n.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    ks.add(a.value)
            elif isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) \
                    and n.value.id == var:
                s = n.slice
                if isinstance(s, ast.Constant) and isinstance(s.value, str):
                    ks.add(s.value)
        return ks

    def collect(self, node: ast.AST) -> _Keys:
        """扫 `node` 里**成功** `ToolResult(...)` 的 `data=` 出口。

        `node` 是类 ⇒ **逐方法**扫；是函数 ⇒ 扫它自己。
        ⚠️ 搜索域必须**逐方法**：`Name` 回指（`data=quote` 找 `quote = …`）若在类级搜索，
        两个方法里的同名局部变量会互相串（`data`/`result` 这类名字在工具里到处都是）
        ⇒ **过度认领**（声明了产不出的键也会判 ✅，正是本快照最不该有的方向）。
        """
        scopes = [node] if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else [
            n for n in getattr(node, "body", [])
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        out = _Keys()
        for fn in scopes:
            out.merge(self.collect_fn(fn))
        return out

    def collect_fn(self, fn: ast.AST) -> _Keys:
        out = _Keys()
        for n in ast.walk(fn):
            if not isinstance(n, ast.Call):
                continue
            f = n.func
            if (f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)) != "ToolResult":
                continue
            kw = {k.arg: k.value for k in n.keywords}
            succ = kw.get("success") or (n.args[0] if n.args else None)
            if isinstance(succ, ast.Constant) and succ.value is False:
                continue                                        # 失败出口不算产出
            data = kw.get("data")
            if data is None and len(n.args) > 1:
                data = n.args[1]
            if data is None:
                continue
            if not (isinstance(succ, ast.Constant) and succ.value is True):
                out.dynamic = True                              # success 非字面量 ⇒ 判不准
            out.sites += 1
            sub = self.keys_of(data, fn, 0)
            out.merge(sub)
            if isinstance(data, ast.Name) and sub.dynamic:
                # 变量语义是「上游 payload」时才把「读过的键」算作产出
                # （本地字面 dict 的键已由 `keys_of` 给出，读它不新增产出面）。
                out.keys |= self._passthrough_reads(fn, data.id)
        return out


def _dispatch_map(cls: ast.ClassDef) -> dict:
    """action → 处理方法的归属表（两种声明形态都认；认不出就空着，不猜）。

    ⚠️ 只走**本分支的 `body`**，不走 `orelse`：`if action == "a": … elif action == "b": …`
    的 `elif` 挂在 `orelse` 上 ⇒ 走 `ast.walk(if_node)` 会把**后面每个分支**的处理方法都算进
    `a`（实测：`list` 认领了全工具 6 个键、`helper` 认领了 3 个）⇒ 过度认领 = 假绿（本快照最忌）。
    """
    out: dict = {}
    for n in ast.walk(cls):
        if isinstance(n, ast.If):
            t = n.test
            if isinstance(t, ast.Compare) and isinstance(t.left, ast.Name) \
                    and t.left.id == "action" and len(t.comparators) == 1 \
                    and isinstance(t.comparators[0], ast.Constant) \
                    and isinstance(t.comparators[0].value, str):
                methods = [c.func.attr for stmt in n.body for c in ast.walk(stmt)
                           if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                           and isinstance(c.func.value, ast.Name) and c.func.value.id == "self"]
                if methods:
                    out.setdefault(t.comparators[0].value, set()).update(methods)
        elif isinstance(n, ast.Dict):                            # `{<action>: self._method}`
            for k, v in zip(n.keys, n.values):
                if isinstance(k, ast.Constant) and isinstance(k.value, str) \
                        and isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name) \
                        and v.value.id == "self":
                    out.setdefault(k.value, set()).add(v.attr)
    return out


def _method_keys(entry_method: str, methods: dict, extractor: "_Extractor") -> _Keys:
    """一个 action 名下的产出键 = 入口方法 + 它**类内调用**到的方法（递归，防环）。

    为什么必须跟随（实测）：`update_item` 的入口 `_update_item(...)` 自己一个成功 `ToolResult`
    都没有，真正的产出出口在它调用的 `_put_item_full(...)`（`data={"item_id": …,
    **response.get("data")…}`）里 ⇒ 不跟随就会把该 action 读成「静态、零键」，
    于是**产得出的键被判 impossible**（假红 —— 本快照最不能出的方向）。
    """
    seen: set = set()
    stack = [entry_method]
    agg = _Keys()
    while stack:
        name = stack.pop()
        if name in seen or name not in methods:
            continue
        seen.add(name)
        fn = methods[name]
        agg.merge(extractor.collect(fn))
        for c in ast.walk(fn):
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) \
                    and isinstance(c.func.value, ast.Name) and c.func.value.id == "self":
                stack.append(c.func.attr)
    return agg


def _tool_name(cls: ast.ClassDef):
    return _class_attr_str(cls, "name")


def _method_map(cls: ast.ClassDef) -> dict:
    return {n.name: n for n in cls.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def derive_tool(cls: ast.ClassDef, fnmap: dict) -> dict:
    name = _tool_name(cls)
    methods = _method_map(cls)
    actions = _class_attr_str_set(cls, "VALID_ACTIONS") | _action_enum(cls)
    full = _Extractor(fnmap).collect(cls)
    literal = _Extractor(fnmap, resolve=False).collect(cls)
    if not full.sites:
        full.dynamic = True
        full.notes.add("未找到成功产出出口")
    entry = {
        "keys": sorted(full.keys),
        "literal_keys": sorted(literal.literal),
        "dynamic": full.dynamic,
        "actions": None,
    }
    if full.notes:
        entry["shape_notes"] = sorted(full.notes)[:_MAX_NOTES]
    dispatch = _dispatch_map(cls)
    per_action, unattributed = {}, []
    for act in sorted(actions):
        targets = [m for m in dispatch.get(act, set()) if m in methods]
        if not targets:
            unattributed.append(act)
            continue
        agg = _Keys()
        for m in targets:
            agg.merge(_method_keys(m, methods, _Extractor(fnmap)))
        if not agg.sites:
            # 该 action 名下**没有任何成功的产出出口** ⇒ 不能声称「静态且无键」（那是假红）。
            agg.dynamic = True
            agg.notes.add(f"{act}: 未找到成功产出出口")
        per_action[act] = agg.as_entry()
    if per_action:
        entry["actions"] = per_action
    if unattributed:
        entry["actions_unattributed"] = sorted(unattributed)
    return name, entry


def derive_module(src: str, rel_path: str = f"{TOOLS_REL}/<fixture>.py") -> dict:
    """**单份**工具源码 → `{工具名: 条目}`（`derive()` 与单测共用同一条解析路径）。

    拆出来是为了让「口径」可被合成源码钉死：不拆就只能靠改真工具源码来测生成器，
    而那是「用被测对象证明被测对象」。
    """
    tree = ast.parse(src)
    fnmap = _module_functions(tree)
    sha = hashlib.sha256(src.encode("utf-8")).hexdigest()
    out: dict = {}
    for cls in tree.body:
        if not isinstance(cls, ast.ClassDef) or not _tool_name(cls):
            continue
        name, entry = derive_tool(cls, fnmap)
        entry["file"] = rel_path
        entry["source_sha256"] = sha
        out[name] = entry
    return out


def derive(repo_root: pathlib.Path = REPO_ROOT) -> dict:
    """从工具源码推导整份快照（**纯函数**：同一源码 ⇒ 逐字节同一结果）。"""
    tools_dir = repo_root / TOOLS_REL if repo_root != REPO_ROOT else TOOLS_DIR
    tools: dict = {}
    for f in sorted(tools_dir.glob("*.py")):
        tools.update(derive_module(f.read_text(encoding="utf-8"), f"{TOOLS_REL}/{f.name}"))
    return {
        "schema": SCHEMA,
        "generated_by": "scripts/output_keys_snapshot.py",
        "refresh": "python3 scripts/output_keys_snapshot.py --refresh",
        "tools": tools,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 二、判定（L0 键名校验的唯一口径）
# ══════════════════════════════════════════════════════════════════════════════
PRODUCIBLE = "producible"
IMPOSSIBLE = "impossible"
UNKNOWN = "unknown"


def key_verdict(entry, action: str, key: str) -> tuple:
    """`(status, detail)`：声明的 `expect` 键名 vs 该工具（该 action）的产出键快照。"""
    head = str(key).split(".", 1)[0]                 # 运行期支持点号路径 ⇒ 只看首段
    if entry is None:
        return UNKNOWN, ("工具不在快照里（快照覆盖 app/tools/*.py 的产出面）—— 拼写错误或新工具"
                         "未被推导到")
    scope = None
    if action and isinstance(entry.get("actions"), dict):
        if action in entry["actions"]:
            scope = entry["actions"][action]
        elif action in (entry.get("actions_unattributed") or []):
            scope = None                              # 归属不出来的 action ⇒ 退回工具级并记原因
        else:
            return UNKNOWN, (f"action={action} 不在该工具的产出归属里（快照按 action 归属，"
                             f"已知动作：{sorted(entry['actions'])}）—— 拼写错误或该动作无产出声明")
    keys = set((scope or entry).get("keys") or [])
    dynamic = bool((scope or entry).get("dynamic"))
    if head in keys:
        return PRODUCIBLE, ""
    if not dynamic:
        return IMPOSSIBLE, "快照里该工具（该 action）的产出形状是**静态**的，且没有这个键"
    why = "；".join(entry.get("shape_notes") or []) or "含动态/条件出键"
    if action and not scope:
        why = f"action={action} 的产出未能归属（快照只到工具级）；{why}"
    return UNKNOWN, f"产出形状不定（{why}）"


def ledger_entries(path: pathlib.Path = LEDGER_PATH) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in (data.get("entries") or {}).items()}


def spec_key_verdicts(cases, snapshot: dict, *, legacy: bool = False) -> list:
    """用例里每一条 `output_verify` 声明的键 → 一条判定记录。"""
    tools = (snapshot or {}).get("tools") or {}
    out = []
    for c in cases:
        for spec in c.get("output_verify") or []:
            if not isinstance(spec, dict):
                continue
            tool = str(spec.get("tool") or "")
            action = str(spec.get("action") or "").strip()
            entry = tools.get(tool)
            if legacy and entry is not None:
                entry = {"keys": entry.get("literal_keys") or [], "dynamic": False}
            for key in (spec.get("expect") or {}):
                status, detail = key_verdict(entry, action, key)
                out.append({"case": c.get("id"), "tool": tool, "action": action,
                            "key": key, "status": status, "detail": detail,
                            "ledger_id": f"{c.get('id')}:{tool}:{key}"})
    return out


def freshness_diff(committed, derived) -> list:
    """快照与源码推导的差异（空 = 新鲜）。逐条给出**可行动**的位置。"""
    diff = []
    ct = (committed or {}).get("tools") or {}
    dt = derived.get("tools") or {}
    for name in sorted(set(ct) | set(dt)):
        a, b = ct.get(name), dt.get(name)
        if a is None:
            diff.append(f"工具 {name}：快照里没有（源码里存在）")
            continue
        if b is None:
            diff.append(f"工具 {name}：源码里没有（快照里有）")
            continue
        for field in ("keys", "literal_keys", "dynamic", "actions", "actions_unattributed",
                      "source_sha256", "file"):
            if a.get(field) != b.get(field):
                diff.append(f"工具 {name}.{field}：快照={_brief(a.get(field))} "
                            f"≠ 源码推导={_brief(b.get(field))}")
    return diff


def _brief(value) -> str:
    s = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return s if len(s) <= 160 else s[:157] + "…"


def load_snapshot(path: pathlib.Path = SNAPSHOT_PATH):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def dump_snapshot(snapshot: dict) -> str:
    return json.dumps(snapshot, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


# ══════════════════════════════════════════════════════════════════════════════
# 三、CLI
# ══════════════════════════════════════════════════════════════════════════════
def _load_cases(cases_dir=None):
    sys.path.insert(0, str(REPO_ROOT / ".github"))
    from render_cases import load_case_dicts  # noqa: E402  （与既有 L0 守卫同一个用例读取口径）
    return load_case_dicts(str(cases_dir or (REPO_ROOT / ".github" / "cases")))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="产出键快照（issue #3729）")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--refresh", action="store_true", help="重新生成快照")
    g.add_argument("--check", action="store_true", help="新鲜度校验（不写文件）")
    g.add_argument("--verdicts", action="store_true", help="逐条打印用例 expect 键的判定")
    g.add_argument("--legacy-verdicts", action="store_true",
                   help="按 #3729 记录的旧口径（只读 data= 字面键）复算，用于 before/after 对比")
    ap.add_argument("--cases", default=None,
                    help="用例目录（缺省 .github/cases；用于复算历史用例集）")
    args = ap.parse_args(argv)

    derived = derive()
    if args.refresh:
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(dump_snapshot(derived), encoding="utf-8")
        n_keys = sum(len(t["keys"]) for t in derived["tools"].values())
        print(f"✅ 已刷新 {SNAPSHOT_PATH.relative_to(REPO_ROOT)}："
              f"{len(derived['tools'])} 个工具 / {n_keys} 个产出键")
        return 0
    if args.check:
        diff = freshness_diff(load_snapshot(), derived)
        if diff:
            print("❌ 快照不新鲜（工具产出键变了但快照没刷新）：")
            for d in diff:
                print(f"  · {d}")
            print("   修法：python3 scripts/output_keys_snapshot.py --refresh")
            return 1
        print("✅ 产出键快照新鲜（与工具源码推导逐字段一致）")
        return 0
    if args.verdicts or args.legacy_verdicts:
        rows = spec_key_verdicts(_load_cases(args.cases), load_snapshot(),
                                 legacy=args.legacy_verdicts)
        for r in rows:
            mark = {PRODUCIBLE: "✅", IMPOSSIBLE: "❌", UNKNOWN: "⚠️"}[r["status"]]
            extra = f" —— {r['detail']}" if r["detail"] else ""
            print(f"{mark} {r['case']:8s} {r['tool']:22s} {r['key']:16s} {r['status']}{extra}")
        bad = [r for r in rows if r["status"] == IMPOSSIBLE]
        unknown = [r for r in rows if r["status"] == UNKNOWN]
        print(f"\n共 {len(rows)} 条声明键：可产出 {len(rows) - len(bad) - len(unknown)} / "
              f"不可能 {len(bad)} / 形状不定 {len(unknown)}"
              f"{'（旧口径：dynamic 一律当静态读）' if args.legacy_verdicts else ''}")
        return 1 if bad else 0
    n = len(derived["tools"])
    dyn = sum(1 for t in derived["tools"].values() if t["dynamic"])
    keys = sum(len(t["keys"]) for t in derived["tools"].values())
    print(f"{n} 个工具 / {keys} 个产出键；其中形状不定 {dyn} 个（dyn tool 的键仍逐条有出处）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
