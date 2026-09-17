# case_ids: CH-001
"""用例声明的 `error.code=<TOKEN>` 必须**能在真实 SSE 载荷里出现**（issue #4099，确定性层 / 零 LLM）。

## 这条判据治什么

CH-001（`.github/cases/chat.yml`）原先的机器计分项 `error.code=NOT_FOUND` **恒不可满足**：

1. runner 的 error-code 分支只读**轮级** `result["error"]`，而该字段**只在 `event: error`
   （异常路径）**被赋值；工具失败走 `event: tool_result` ⇒ 真值恒为 None。
   真跑实证：adversarial run 34650006175（main @7f2665ab）逐字
   `❌ error.code=NOT_FOUND → expected error not_found but got None`（score=33% = 1/3）；
2. 即便把取值面扩到工具级也取不到该字样：`product_detail` 的 NOT_FOUND 分支返回的 error
   文本是「商品不存在」（`app/tools/product_detail.py`），不含 `NOT_FOUND`。

⇒ 一条**永远不可能满足**的断言把该用例的 score 上限钉死，而它在报告里长得像「产品缺陷」。
形态名：`migao-acceptance`「空断言」的**恒红**一支（恒绿一支 = `scoring_assertion_count == 0`，
由 `.github/assertion_taxonomy.py` 的 `CASE-TRUST-EMPTY-ASSERTION` 管）。

## 判据（两侧都从**源码/单一源**取真值，不抄快照、不硬编码清单）

| 侧 | 事实（被断言的真值） | 怎么取 |
|---|---|---|
| runner 取值路径 | 轮级 `error` 的**唯一**来源是 `event: error` 载荷 | AST：`local_runner.py` 里每次 `result["error"] = …` 的**守卫**必须提到 `current_event` 与 `error` |
| 后端可达面 | `event: error` 载荷文本里**可能出现的字面量** | AST：`SSEEvent.error(...)` 调用点（排除 `sse.py` 的转发点）的字面串 + 字面 `code` 实参 + 载荷键名 |
| 声明面 | 用例库里**已声明**的 token | 单一源 = `.github/cases/*.yml`（生成物不参与判定）；机器计分口径复用 `.github/assertion_taxonomy.machine_scored_data_checks` |

两侧对不上 ⇒ 该声明**恒不可满足** ⇒ 本判据红。红证与负例见文件末尾两个测试类
（**判据自己也要能红**：喂 CH-001 改前的声明必红；喂可达声明不得红）。

## 边界（照实登记，不写成恒真判据）

· **动态插值段不计入可达集合**：如 `SSEEvent.error(result.message or "查询失败")`、
  `f"…{invalid_urls}"` 承载的是**运行期数据**，静态不可枚举。若确有 token 只可能来自动态段，
  本判据会误报「不可达」⇒ 修法是把该 token 的来源改成**字面量**（可枚举），**不是**放宽本判据。
  动态段数量由 `dynamic_message_sites()` 报出，供人工判读（不当成失败）。
· **非字面 `code` 实参 = 失败关闭**：可达集合无法判定 ⇒ 红（「无法判定 ≠ 通过」）。
· **本判据不判强弱**：只判「声明了 token 但该 token 不可达」。声明强弱（存在性 vs 效果层）
  归 `.github/assertion_taxonomy.py`，**不**在这里复制第二份口径。
· **不在范围**：只提到标记、却不含可解析 token 的条目（如散文里写 `error.code=`）——
  那是**另一条**形态（该条会被 runner 的标记过滤当成机器计分项，实证 PR-008 的 data_check），
  本判据不覆盖（改动它超出 #4099 的文件所有权，已在 #4099 汇报里登记）。
"""
from __future__ import annotations

import ast
import re
import sys
import warnings
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))

from render_cases import load_case_dicts  # noqa: E402

CASES_DIR = REPO_ROOT / ".github" / "cases"
RUNNER_PATH = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"
APP_DIR = REPO_ROOT / "backend" / "ai-agent-service" / "app"
SSE_MODULE = APP_DIR / "api" / "sse.py"

FRAME_LITERAL = "event: error"
# 载荷键名：runner 用 `str(payload)` 整串匹配 ⇒ 键名本身也是可命中的子串（照实建模）
PAYLOAD_KEYS = ("message", "code")
CODE_DECL_RE = re.compile(r"error\.code\s*=\s*(\w+)", re.IGNORECASE)
# `SSEEvent.error(...)` 的接收者形态（含 builder/self 转发形态）；`logger.error` 不在内
_RECEIVER_HINTS = ("sse", "self", "builder", "stream")


# ── 侧 ①：runner 的取值路径（轮级 error 只能来自 event: error）──────────────────

def _guard_tokens(test: ast.AST) -> set[str]:
    """守卫表达式里的**字面字符串** ∪ **标识符名**（`current_event == "error"` → {current_event, error}）。

    刻意不用 `ast.unparse`：避免绑死 Python 版本；本判据只需要"守卫提到了什么"。
    """
    toks: set[str] = set()
    for n in ast.walk(test):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            toks.add(n.value)
        elif isinstance(n, ast.Name):
            toks.add(n.id)
    return toks


def _is_round_error_target(t: ast.AST) -> bool:
    """是否是 `result["error"]` 这个下标目标。"""
    return (isinstance(t, ast.Subscript)
            and isinstance(t.value, ast.Name) and t.value.id == "result"
            and isinstance(t.slice, ast.Constant) and t.slice.value == "error")


def round_error_assignments(tree: ast.AST) -> list[tuple[int, set[str]]]:
    """runner 里每次 `result["error"] = …` → [(行号, 该赋值所处**分支守卫**的 token 集)]。

    守卫语义按 AST 精确取：`if` 的 **body** 记自己的 test；`orelse` 只继承祖先
    （elif 链里下一个分支是 `orelse` 里的**另一个 If 节点**，由它自己带上 test）。

    ⚠️ 为什么 `orelse` **不**继承自己的 test（本判据的实现细节，已用样本锁住）：
    若按「body+orelse 同守卫」记账，`if current_event == "error": … else: result["error"] = …`
    的 **else 分支**会继承 test 里的 `error` 一词 ⇒ **在"不是 error 分支"的地方赋值也通过**
    （实测：union 写法对 `test_runner_else_branch_…` 的变异样本静默放过；精确写法判红）。
    本判据存在的意义就是把取值面钉死，故必须按「分支」而不是「祖先里出现过什么」记账。
    """
    found: list[tuple[int, set[str]]] = []

    def walk(node: ast.AST, guards: tuple[frozenset, ...]) -> None:
        if isinstance(node, ast.If):
            toks = frozenset(_guard_tokens(node.test))
            for st in node.body:
                walk(st, guards + (toks,))
            for st in node.orelse:
                walk(st, guards)
            return
        if isinstance(node, ast.Assign):
            if any(_is_round_error_target(t) for t in node.targets):
                found.append((node.lineno, set().union(*guards) if guards else set()))
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)) and _is_round_error_target(node.target):
            found.append((node.lineno, set().union(*guards) if guards else set()))
        for child in ast.iter_child_nodes(node):
            walk(child, guards)

    walk(tree, ())
    return found


def round_error_path_violations(tree: ast.AST) -> list[str]:
    """取值路径契约：每次 `result["error"] = …` 都必须位于 `event: error` 分支内。

    空列表 = 合契约。**找不到任何赋值也报违规**（前提消失 = 判据失去目标，
    「判据静默空转」与「跑过了」必须可辨）。
    """
    sites = round_error_assignments(tree)
    if not sites:
        return ["runner 里找不到 `result[\"error\"] = …` 赋值 —— 本判据的前提消失"
                "（取值路径已重构？请把新形态加进本判据，**不要**删判据）"]
    bad = []
    for lineno, toks in sites:
        if not ({"current_event", "error"} <= toks):
            bad.append(
                f"local_runner.py 第 {lineno} 行的 `result[\"error\"]` 赋值不在 "
                f"`event: error` 分支内（分支守卫 token={sorted(toks)}）—— 轮级 error 的取值面变了，"
                "`error.code=` 声明的可达性必须重算（若新面可达，扩 `reachable_payload_tokens`；"
                "若只是改了写法（如取反分支），把该形态加进本判据）")
    return bad


# ── 侧 ②：后端 `event: error` 载荷的可达字面量 ────────────────────────────────

def _callee_receiver_name(func: ast.AST) -> str:
    """调用表达式的"接收者名"（`SSEEvent.error` → SSEEvent；`logger.opt().error` → opt）。"""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Call):
        return _callee_receiver_name(func.func)
    return ""


def _is_sse_error_emitter(call: ast.Call) -> bool:
    """是否是往 `event: error` 载荷里塞内容的调用点（`X.error(...)`，X 形如 SSEEvent/builder/self）。"""
    func = call.func
    if not (isinstance(func, ast.Attribute) and func.attr == "error"):
        return False
    recv = _callee_receiver_name(func.value).lower()
    return any(h in recv for h in _RECEIVER_HINTS)


def _literal_code_arg(call: ast.Call) -> tuple[bool, str]:
    """调用的 `code` 实参 → (是否可判定, 字面值)。无该实参 = 可判定（空串）。"""
    node = call.args[1] if len(call.args) >= 2 else None
    for kw in call.keywords:
        if kw.arg == "code":
            node = kw.value
    if node is None:
        return True, ""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True, node.value
    return False, ""


def _arg_strings(nodes: list[ast.AST]) -> tuple[list[str], bool]:
    """实参里的字面串 + 是否存在**动态段**（f-string 插值 / 变量 / 调用）。"""
    out: list[str] = []
    dynamic = False
    for n in nodes:
        for sub in ast.walk(n):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                out.append(sub.value)
            elif isinstance(sub, (ast.JoinedStr, ast.Name, ast.Call, ast.Attribute, ast.Subscript)):
                dynamic = True
    return out, dynamic


def _parse(path: Path) -> ast.Module:
    """解析源文件为 AST（**不执行**）。

    屏蔽 `SyntaxWarning`：业务源码里存在 `"\\d"` 这类旧转义（`ast.parse` 会编译触发告警），
    那是既存现状、与本判据无关 —— 让本判据的输出只剩它自己的结论。
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        warnings.simplefilter("ignore", DeprecationWarning)
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _rel(path: Path) -> str:
    """展示用相对路径（注入样本落在 tmp 目录时退回绝对路径，不因展示失败而误判）。"""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _frame_literal_lines(path: Path) -> list[int]:
    """该文件里**代码**（非 docstring 的字面量）拼出 `event: error` 的行号。

    为什么要排除 docstring：`app/api/chat.py` 的接口说明里就写着 `- event: error - 错误信息`
    —— 那是文档，不是帧生产者。光按文本搜会把文档当第二个生产者（假红面）。
    """
    tree = _parse(path)
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))
    return [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and FRAME_LITERAL in n.value and id(n) not in docstrings]


def sse_error_payloads(app_dir: Path = APP_DIR) -> dict:
    """扫 `app/` 下所有 `event: error` 载荷发射点 → 可达字面量 + 无法判定的来源。

    返回 `{"tokens": [...], "dynamic_sites": [...], "unknown": [...], "sites": [...]}`。
    · 排除 `sse.py` 自身：那一处是**转发点**（载荷就在这里组装），把参数原样传下去，
      可达性由它的**调用方**决定（见 `sse_frame_contract_violations` 对它的形状前提）；
    · `unknown`：非字面 `code` 实参（无法判定可达集合）⇒ 调用方按**失败关闭**处理。
    """
    tokens: list[str] = list(PAYLOAD_KEYS)
    dynamic_sites: list[str] = []
    unknown: list[str] = []
    sites: list[str] = []
    for path in sorted(app_dir.rglob("*.py")):
        if path == (app_dir / "api" / "sse.py"):
            continue
        tree = _parse(path)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and _is_sse_error_emitter(node)):
                continue
            rel = f"{_rel(path)}#{node.lineno}"
            sites.append(rel)
            strs, dynamic = _arg_strings(list(node.args) + [k.value for k in node.keywords])
            tokens.extend(strs)
            if dynamic:
                dynamic_sites.append(rel)
            ok, code = _literal_code_arg(node)
            if not ok:
                unknown.append(f"{rel}: `code` 实参不是字面量 ⇒ 可达集合无法判定")
            elif code:
                tokens.append(code)
    return {"tokens": tokens, "dynamic_sites": dynamic_sites, "unknown": unknown, "sites": sites}


def sse_frame_contract_violations(app_dir: Path = APP_DIR,
                                  sse_path: Path | None = None) -> list[str]:
    """`event: error` 帧的**唯一生产者**与载荷形状前提（形状变了 ⇒ 本判据要重算）。

    `app_dir`/`sse_path` 可注入（注入式样本用**同一个实现**，不复制第二份口径）。
    """
    sse_path = sse_path or (app_dir / "api" / "sse.py")
    bad = []
    owned = _frame_literal_lines(sse_path)
    if len(owned) != 1:
        bad.append(f"{sse_path.name} 里代码拼 `{FRAME_LITERAL}` 的行数 = {len(owned)}（应为 1）"
                   " —— 帧生产者不再是唯一一处，可达集合的取法要重算")
    others = [p for p in sorted(app_dir.rglob("*.py"))
              if p != sse_path and _frame_literal_lines(p)]
    if others:
        bad.append("除 sse.py 外还有文件在**代码**里拼 `event: error` 帧："
                   + "、".join(_rel(p) for p in others)
                   + " —— 可达集合的取法要重算（漏扫 = 把可达 token 判成不可达 = 假红）")
    tree = _parse(sse_path)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "error"), None)
    if fn is None:
        bad.append("sse.py 里找不到 `error` 方法 —— 帧生产者形态变了")
    else:
        consts = {n.value for n in ast.walk(fn)
                  if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        missing = [k for k in PAYLOAD_KEYS if k not in consts]
        if missing:
            bad.append(f"sse.py 的 `error` 载荷里找不到键 {missing} —— 载荷形状变了"
                       f"（本判据按 {list(PAYLOAD_KEYS)} 建模可达集合）")
    return bad


def reachable_payload_tokens(app_dir: Path = APP_DIR) -> list[str]:
    """可达字面量集合（供契约判定与注入样本共用同一实现）。"""
    return sse_error_payloads(app_dir)["tokens"]


# ── 侧 ③：用例库的声明面 + 契约判定 ──────────────────────────────────────────

def error_code_declarations(cases: list[dict]) -> list[tuple[str, str]]:
    """用例库里**会进计分**的 `error.code=<TOKEN>` 声明 → [(case_id, token)]。

    计分面口径与 runner 同源：`expectations` 全部计分；`data_checks` 只认机器计分型
    （标记集合的**单一源** = `.github/assertion_taxonomy.MACHINE_DATA_CHECK_MARKERS`）。
    """
    out: list[tuple[str, str]] = []
    for case in cases:
        checks = [str(e) for e in (case.get("expectations") or [])]
        for dc in (case.get("data_checks") or []):
            s = str(dc)
            if "error.code=" in s.lower():
                checks.append(s)
        for chk in checks:
            for token in CODE_DECL_RE.findall(chk):
                out.append((str(case.get("id") or "?"), token))
    return out


def unreachable_error_code_declarations(cases: list[dict],
                                       app_dir: Path = APP_DIR) -> list[str]:
    """契约：每个声明的 token 都必须能在真实 `event: error` 载荷里出现。空 = 合契约。"""
    tokens = reachable_payload_tokens(app_dir)
    bad = []
    for cid, token in error_code_declarations(cases):
        if not any(token.lower() in t.lower() for t in tokens):
            bad.append(
                f"{cid}: 声明 `error.code={token}`，但该字样在真实链路里**不可达** —— "
                "runner 的 error-code 分支只读轮级 SSE error（只在 `event: error` 赋值），"
                "而后端所有 error 帧的字面量里都没有这个 token ⇒ 该断言**恒不可满足**（永久红）。"
                "改法：换成现有能力可判的形态（#4099 对 CH-001 的处置 = `must_fail[{tool}]`），"
                "或把错误码来源改成字面量（可枚举）而后端确实会发它")
    return bad


def _cases() -> list[dict]:
    return load_case_dicts(str(CASES_DIR))


# ── 常驻契约（真实仓库）──────────────────────────────────────────────────────

class TestPayloadContractPremises:
    """两侧真值的前提：前提消失要**响**（否则判据静默空转 = 另一种空断言）。"""

    def test_round_error_only_from_sse_error_event(self):
        tree = _parse(RUNNER_PATH)
        assert round_error_path_violations(tree) == []

    def test_sse_error_frame_contract(self):
        assert sse_frame_contract_violations() == []

    def test_extraction_is_live(self):
        got = sse_error_payloads()
        assert len(got["sites"]) >= 1, "一个 error 帧发射点都没扫到 —— 提取器失效（判据空转）"
        assert got["unknown"] == [], "可达集合无法判定：\n  " + "\n  ".join(got["unknown"])


class TestDeclaredErrorCodesAreReachable:
    """**常驻判据本体**：用例库声明的 token 必须可达。"""

    def test_no_case_declares_an_unreachable_error_code(self):
        assert unreachable_error_code_declarations(_cases()) == []


# ── 判据自己的红证 / 负例（注入式变异样本）──────────────────────────────────

class TestJudgeIsNotVacuous:
    """判据必须**双向**可判：喂改前的形态必红，喂合法声明不得红（R2）。"""

    def test_pre_fix_form_is_red(self):
        """红证 ①：CH-001 改前的声明（`error.code=NOT_FOUND`）必须被判红。"""
        cases = [{"id": "CH-001", "expectations": ["product_detail"],
                  "data_checks": ["error.code=NOT_FOUND", "suggestion 非空且包含 product_search"]}]
        bad = unreachable_error_code_declarations(cases)
        assert len(bad) == 1 and "NOT_FOUND" in bad[0], bad

    def test_reachable_declaration_is_not_red(self, tmp_path: Path):
        """负例（R2）：token 确实可达时**不得**判红 —— 本判据不是「禁止声明 error.code」。"""
        (tmp_path / "emitters.py").write_text(
            'SSEEvent.error("会话已关闭", code="SESSION_CLOSED")\n', encoding="utf-8")
        cases = [{"id": "XX-001", "expectations": ["error.code=SESSION_CLOSED"]}]
        assert unreachable_error_code_declarations(cases, app_dir=tmp_path) == []

    def test_message_literal_is_reachable(self, tmp_path: Path):
        """负例（R2）：token 出现在**报文正文**里同样可达（runner 是整串子串匹配）。"""
        (tmp_path / "emitters.py").write_text(
            'SSEEvent.error("商品不存在（NOT_FOUND）", code="X")\n', encoding="utf-8")
        cases = [{"id": "XX-002", "data_checks": ["error.code=NOT_FOUND"]}]
        assert unreachable_error_code_declarations(cases, app_dir=tmp_path) == []

    def test_unknown_code_arg_fails_closed(self, tmp_path: Path):
        """非字面 `code` 实参 ⇒ 可达集合无法判定 ⇒ 失败关闭（不是静默放过）。"""
        (tmp_path / "emitters.py").write_text(
            'SSEEvent.error("出错了", code=some_dynamic_code)\n', encoding="utf-8")
        got = sse_error_payloads(tmp_path)
        assert len(got["unknown"]) == 1, got

    def test_runner_path_mutation_is_caught(self):
        """红证 ②：把「轮级 error 的来源」改到 tool_result 分支 ⇒ 判据必红。"""
        mutated = ast.parse(
            "async def send_message():\n"
            "    result = {'error': None}\n"
            "    async for line in resp:\n"
            "        if current_event == 'tool_result':\n"
            "            result['error'] = str(payload)\n"
        )
        bad = round_error_path_violations(mutated)
        assert len(bad) == 1 and "event: error" in bad[0], bad

    def test_runner_path_mutation_inside_real_elif_chain_is_caught(self):
        """红证 ②′：在 runner **真实的 elif 链**形状里把赋值挪到 `tool_result` 分支
        （样本逐字复刻 `send_message` 的链形状）⇒ 判据必红，且点名 tool_result。"""
        mutated = ast.parse(
            "async def send_message():\n"
            "    result = {'error': None}\n"
            "    async for line in resp:\n"
            "        if line.startswith('event:'):\n"
            "            current_event = line[6:].strip()\n"
            "        elif line.startswith('data:'):\n"
            "            payload = json.loads(data_str)\n"
            "            if current_event == 'text':\n"
            "                result['final_text'] += payload.get('content', '')\n"
            "            elif current_event == 'tool_result':\n"
            "                result['tool_results'].append(payload)\n"
            "                result['error'] = str(payload)\n"
            "            elif current_event == 'error':\n"
            "                pass\n"
        )
        bad = round_error_path_violations(mutated)
        assert len(bad) == 1, bad
        assert "tool_result" in bad[0], bad

    def test_runner_else_branch_of_error_check_is_caught(self):
        """红证 ②″：赋值落在 `if current_event == 'error': … else: …` 的 **else** 分支 ⇒
        必红。**这条样本是"守卫必须按分支记账"的判据**：若把 orelse 也按 same-test 记账
        （本判据初版写法），else 分支会继承 `error` 一词 ⇒ 该样本被静默放过（已实测）。"""
        mutated = ast.parse(
            "async def send_message():\n"
            "    result = {'error': None}\n"
            "    async for line in resp:\n"
            "        if current_event == 'error':\n"
            "            result['error'] = str(payload)\n"
            "        else:\n"
            "            result['error'] = str(payload.get('result'))\n"
        )
        bad = round_error_path_violations(mutated)
        assert len(bad) == 1, bad
        assert "第 7 行" in bad[0], bad

    def test_runner_path_premise_loss_is_caught(self):
        """红证 ③：runner 里不再有该赋值（被重构）⇒ 判据的**前提消失**也要红。"""
        assert len(round_error_path_violations(ast.parse("x = 1\n"))) == 1

    def test_frame_literal_move_is_caught(self, tmp_path: Path):
        """红证 ④：`event: error` 帧出现第二个生产者 ⇒ 可达集合取法失效，判据必红。"""
        api = tmp_path / "api"
        api.mkdir()
        (api / "sse.py").write_text(
            'def error(message, code=None):\n'
            '    data = {"message": message}\n'
            '    if code:\n'
            '        data["code"] = code\n'
            '    return f"event: error\\ndata: {data}\\n\\n"\n', encoding="utf-8")
        (tmp_path / "raw.py").write_text(
            'RAW = "event: error\\ndata: {}\\n\\n"\n', encoding="utf-8")
        bad = sse_frame_contract_violations(tmp_path)
        assert any("除 sse.py 外" in b for b in bad), bad
        assert not any("行数 = " in b for b in bad), bad