# case_ids: AS-003
"""写侧落库的 metadata 字段**必须能被读侧读出来**（issue #4097 的类级锁）。

## 这一格治什么（本 issue 的缺陷形态）

`metadata.tool_results` 由 #4052 落库（`app/api/chat.py` 的 SSE 桥 → `SessionMemory.save_message`），
**但读侧 `GET /api/chat/history/{session_id}` 一直没回传它** ⇒ 评测只能断言
「模型说它调了」，不能断言「确实调了 / 确实成了」（#4097 原话）。
形态名 = **只写不读的空字段**：字段落库了、没有任何消费路径，而且**没有任何东西会因此变红**。

## 为什么是「类级」而不是「加一行断言」

只给 `tool_results` 补一条读侧断言 = 修了这一处。下一格（任何新 metadata 字段）会以**同样的
静默方式**复发。故本判据锁的是**两侧的一致性**：

| 侧 | 真值怎么取（不抄快照、不硬编码清单） |
|---|---|
| 写侧 | `SessionMemory.save_message` 本体里 `meta_dict["<k>"] = …`（**单一写入口**）+ 所有 `save_message(extra_metadata={…})` 调用点的字面键（变量形态按同函数内的一次赋值展开） |
| 读侧 | `get_history` 函数体内对 metadata 的取值 `metadata.get("<k>")` / `meta_parsed.get("<k>")` |

`写侧键集 − 读侧键集 − INTERNAL_ONLY` 非空 ⇒ 判红，并逐键指名。

## 红证

`TestInjectedRedProof` 用**改前的 `chat.py` 形态**（写侧有 `tool_results`、读侧没有）
喂同一个检查器 ⇒ 必须报 `tool_results`。真文件上的红证见本 PR 汇报（注入式实测）。

⚠️ 边界（如实登记，不写成恒真判据）：
· 值**动态拼装**的 metadata 键（如 `meta_dict.update(**payload)`）静态不可枚举 ⇒ 本判据看不见；
  当前写侧无这种形态，若将来出现，须先把它落成字面量键（与本判据的 `INTERNAL_ONLY` 台账同款处置）。
· 本判据只管**键的存在性**，不管值形状（"读出来了但读错了"由 runner 侧
  `tests/unit_ci_workflows/test_eval_must_succeed_metadata_source.py` 的形状判据管）。
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHAT_PY = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "api" / "chat.py"
SESSION_MEMORY_PY = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "memory" / "session_memory.py"

#: 落库但**有意不回传**给客户端的 metadata 键 → 必须写明理由（空/过短即红）。
#: 本台账当前为空：写侧的每个键读侧都回传了（`images`/`tool_calls`/`tool_results`/
#: `interactive`/`interactive_answered`/`cards`）。新键要么补齐读侧，要么在这里**显式**登记。
INTERNAL_ONLY: dict = {}

#: `metadata.<键>` → 响应载荷里**改了名**的键（当前为空：既有全部同名回传）。
#: 为什么需要这一格：判据要求"读出来的键**真的出现在响应载荷里**"，改了名就得显式登记，
#: 否则会被判成"没暴露"（假红）—— 台账为空 = 现在没有任何改名。
EXPOSED_AS: dict = {}


def _kw_dict_keys(node: ast.AST, scope: ast.AST) -> list:
    """`extra_metadata=<dict>` 的键；变量形态按**同函数内的一次赋值**展开。"""
    if isinstance(node, ast.Dict):
        return [k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
    if isinstance(node, ast.Name):
        for sub in ast.walk(scope):
            if isinstance(sub, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == node.id for t in sub.targets):
                if isinstance(sub.value, ast.Dict):
                    return [k.value for k in sub.value.keys
                            if isinstance(k, ast.Constant) and isinstance(k.value, str)]
    return []


def written_metadata_keys(chat_src: str, session_src: str) -> set:
    """写侧会写进 `metadata` 的键集（见模块 docstring 的真值口径）。"""
    keys = set()
    # ① 单一写入口：SessionMemory.save_message 的 `meta_dict["<k>"] = …`
    tree = ast.parse(session_src)
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               if n.name == "save_message"]:
        for sub in ast.walk(fn):
            if (isinstance(sub, ast.Assign) and len(sub.targets) == 1
                    and isinstance(sub.targets[0], ast.Subscript)
                    and isinstance(sub.targets[0].value, ast.Name)
                    and sub.targets[0].value.id == "meta_dict"
                    and isinstance(sub.targets[0].slice, ast.Constant)
                    and isinstance(sub.targets[0].slice.value, str)):
                keys.add(sub.targets[0].slice.value)
    # ② 调用点：`save_message(..., extra_metadata={…})`（含变量形态）
    ctree = ast.parse(chat_src)
    for fn in [n for n in ast.walk(ctree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        for call in [n for n in ast.walk(fn) if isinstance(n, ast.Call)]:
            for kw in call.keywords or []:
                if kw.arg == "extra_metadata":
                    keys |= set(_kw_dict_keys(kw.value, fn))
    return keys


def payload_keys(chat_src: str) -> set:
    """`get_history` **真正回传给客户端**的载荷键（响应字典字面量的键）。

    🔴 为什么必须有这一格（**实测红证**）：只判"读侧从 metadata 里取过这个键"是不够的 ——
    把 `formatted_messages.append({... "tool_results": …})` 那一行删掉（取值仍在、
    只是**没进响应**）时，前者照样绿（实测：5 passed，判据失明）。
    真值 = 「取出来了」**且**「进了响应载荷」。
    """
    tree = ast.parse(chat_src)
    keys = set()
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               if n.name == "get_history"]:
        for call in [n for n in ast.walk(fn) if isinstance(n, ast.Call)]:
            if (isinstance(call.func, ast.Attribute) and call.func.attr == "append"
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "formatted_messages"
                    and call.args and isinstance(call.args[0], ast.Dict)):
                keys |= {k.value for k in call.args[0].keys
                         if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    return keys


def read_metadata_keys(chat_src: str, session_src: str = "") -> set:
    """`get_history` 从 metadata 取值、**且真的回传**的键集（读侧的真值）。

    两条暴露机制都算（少认一条就会把**已暴露**的键误判成"只写不读" = 假红）：
      a. **直读**：端点里 `metadata.get("<k>")` / `meta_parsed.get("<k>")`；
      b. **提升**：`SessionMemory.get_history` 把 `metadata.get("<k>")` 提升成行内字段，
         端点在响应里读它（`msg.get("<k>")` / `msg["<k>"]`）。
         实现 = 两侧**取交集**（"被提升过" ∧ "端点读过"）—— 只认单侧会误伤
         `content`/`role` 这类**本来就来自表列**的字段（它们不是 metadata 键）。
    最后统一与**响应载荷键**取交集（「取出来了」∧「进了响应」，缺一不算暴露）。
    """
    tree = ast.parse(chat_src)
    keys = set()
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               if n.name == "get_history"]:
        row_keys = set()
        for call in [n for n in ast.walk(fn) if isinstance(n, ast.Call)]:
            if not isinstance(call.func, ast.Attribute) or not call.args:
                continue
            if not (isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str)):
                continue
            if call.func.attr == "get" and isinstance(call.func.value, ast.Name) \
                    and call.func.value.id in ("metadata", "meta_parsed"):
                keys.add(call.args[0].value)
            if isinstance(call.func.value, ast.Name) and call.func.value.id == "msg":
                row_keys.add(call.args[0].value)
        for sub in ast.walk(fn):
            if (isinstance(sub, ast.Subscript) and isinstance(sub.value, ast.Name)
                    and sub.value.id == "msg" and isinstance(sub.slice, ast.Constant)
                    and isinstance(sub.slice.value, str)):
                row_keys.add(sub.slice.value)
        if session_src:
            keys |= (lifted_metadata_keys(session_src) & row_keys)
    payload = payload_keys(chat_src)
    return {k for k in keys if k in payload or EXPOSED_AS.get(k) in payload}


def lifted_metadata_keys(session_src: str) -> set:
    """`SessionMemory.get_history` 从 metadata 提升成行内字段的键。"""
    tree = ast.parse(session_src)
    keys = set()
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               if n.name == "get_history"]:
        for call in [n for n in ast.walk(fn) if isinstance(n, ast.Call)]:
            if (isinstance(call.func, ast.Attribute) and call.func.attr == "get"
                    and isinstance(call.func.value, ast.Name) and call.func.value.id == "metadata"
                    and call.args and isinstance(call.args[0], ast.Constant)
                    and isinstance(call.args[0].value, str)):
                keys.add(call.args[0].value)
    return keys


def agreement_findings(chat_src: str, session_src: str) -> list:
    """写侧落库、读侧不回传、且未登记为 internal-only 的键（每条带可行动出口）。"""
    written = written_metadata_keys(chat_src, session_src)
    read = read_metadata_keys(chat_src, session_src)
    findings = []
    for key in sorted(written - read - set(INTERNAL_ONLY)):
        findings.append(
            f"metadata.{key} 写侧落库了、读侧 get_history 没回传"
            f"（只写不读的空字段 —— issue #4097 的形态）")
    for key, reason in INTERNAL_ONLY.items():
        if key not in written:
            findings.append(f"INTERNAL_ONLY 里的 {key} 写侧已不写 ⇒ 过期豁免，请删除")
    return findings


class TestRealRepoIsInAgreement:
    """真文件上的常驻判据（本 issue 修好后必须绿；改前必红 —— 见下一类的注入式红证）。"""

    def test_every_persisted_metadata_key_is_exposed(self):
        findings = agreement_findings(CHAT_PY.read_text(encoding="utf-8"),
                                      SESSION_MEMORY_PY.read_text(encoding="utf-8"))
        assert not findings, "写侧/读侧不一致：\n  " + "\n  ".join(findings)

    def test_probe_can_see_both_sides(self):
        """防"判据恒真"：写侧/读侧各自都必须解析出**非空**键集，否则判据是空断言。

        只断言 `findings == []` 是不够的 —— 两侧都解析成空集时它同样成立（恒绿）。
        """
        chat_src = CHAT_PY.read_text(encoding="utf-8")
        session_src = SESSION_MEMORY_PY.read_text(encoding="utf-8")
        written = written_metadata_keys(chat_src, session_src)
        read = read_metadata_keys(chat_src, session_src)
        assert {"tool_calls", "tool_results"} <= written, f"写侧解析疑似失效：{sorted(written)}"
        assert {"tool_calls", "tool_results", "images", "cards"} <= read, (
            f"读侧解析疑似失效：{sorted(read)}")


class TestInjectedRedProof:
    """喂**改前的形态**（写侧有 `tool_results`、读侧没有）⇒ 必须报出来。

    这是"判据自己会红"的证据：若本类全绿，说明 `agreement_findings` 是空断言。
    """

    #: 写侧（save_message 本体）——与真文件同形的最小片段
    WRITE_SRC = (
        "async def save_message(self, session_id, role, content, tool_calls=None,\n"
        "                       extra_metadata=None, tool_results=None):\n"
        "    meta_dict = {}\n"
        "    if tool_calls:\n"
        "        meta_dict['tool_calls'] = tool_calls\n"
        "    if tool_results:\n"
        "        meta_dict['tool_results'] = tool_results\n"
        "    metadata = json.dumps(meta_dict) if meta_dict else '{}'\n"
    )

    #: 存储层的**提升**（真文件里 `SessionMemory.get_history` 把 tool_calls 从 metadata
    #: 提到行内字段，端点读的是行内那个 ⇒ 判据必须认这条路，否则把已暴露的键判成"没回传"）
    LIFT_SRC = (
        "async def get_history(self, session_id):\n"
        "    metadata = row[5] or {}\n"
        "    tool_calls = metadata.get('tool_calls')\n"
        "    return [{'tool_calls': tool_calls, 'metadata': metadata}]\n"
    )

    #: 读侧（get_history）——**改前**形态：只回传 tool_calls，不回传 tool_results
    READ_BEFORE = (
        "async def get_history(session_id):\n"
        "    formatted_messages = []\n"
        "    for msg in messages:\n"
        "        metadata = msg.get('metadata')\n"
        "        tool_calls = msg.get('tool_calls')\n"
        "        formatted_messages.append({'tool_calls': tool_calls})\n"
        "    return formatted_messages\n"
    )

    #: 读侧 —— 修后形态（+1 键）
    READ_AFTER = READ_BEFORE.replace(
        "        formatted_messages.append({'tool_calls': tool_calls})\n",
        "        tool_results = metadata.get('tool_results')\n"
        "        formatted_messages.append({'tool_calls': tool_calls,\n"
        "                                   'tool_results': tool_results})\n")

    def test_write_only_field_is_reported(self):
        findings = agreement_findings(self.READ_BEFORE, self.WRITE_SRC + self.LIFT_SRC)
        assert len(findings) == 1 and "metadata.tool_results" in findings[0], (
            f"改前形态（写侧落库、读侧不回传）必须被判红，实得 {findings}")

    def test_adding_the_read_side_clears_it(self):
        """同一份写侧 + 补上读侧 ⇒ 不报（防"加断言 = 恒红"）。"""
        assert agreement_findings(self.READ_AFTER, self.WRITE_SRC + self.LIFT_SRC) == []

    def test_value_read_from_metadata_but_not_returned_is_reported(self):
        """**取值仍在、只是没进响应载荷** ⇒ 必须判红（本判据第一版在这里失明，注入实测）。

        形态：`tool_results = metadata.get('tool_results')` 照旧，但 `formatted_messages.append({...})`
        里没有这个键 —— 客户端拿不到，评测也就断言不了。只判"从 metadata 取过"的版本
        对这一格恒绿（实测 5 passed），故本格是**判据自身的红证**。
        """
        read_but_not_returned = self.READ_AFTER.replace(
            "        formatted_messages.append({'tool_calls': tool_calls,\n"
            "                                   'tool_results': tool_results})\n",
            "        formatted_messages.append({'tool_calls': tool_calls})\n")
        assert read_but_not_returned != self.READ_AFTER, "注入目标没匹配上（红证无效）"
        findings = agreement_findings(read_but_not_returned, self.WRITE_SRC + self.LIFT_SRC)
        assert len(findings) == 1 and "metadata.tool_results" in findings[0], (
            f"取出来了却没进响应载荷 —— 必须判红，实得 {findings}")

    def test_payload_key_extraction_is_not_empty(self):
        """防"载荷键解析失效 ⇒ 判据恒红/恒绿"：修后形态必须能解析出两个键。"""
        assert {"tool_calls", "tool_results"} <= payload_keys(self.READ_AFTER)

    def test_internal_only_ledger_must_stay_alive(self):
        """豁免台账不许长生不老：写侧不再写该键 ⇒ 报过期（把"忘记删"变成红灯）。"""
        saved = dict(INTERNAL_ONLY)
        INTERNAL_ONLY["ghost_key"] = "（测试用）"
        try:
            findings = agreement_findings(self.READ_AFTER, self.WRITE_SRC)
        finally:
            INTERNAL_ONLY.clear()
            INTERNAL_ONLY.update(saved)
        assert any("过期豁免" in f for f in findings), findings
