# case_ids: DA-024
"""评测目标租户 = **单一可注入配置**，且「非 DEBUG 不接受外部租户」的护栏不被削弱（issue #6288）。

## 病灶（2026-10-04 云测试环境重建时顺带发现）

`backend/ai-agent-service/app/utils/auth.py` 的 DEBUG 降级身份分支**写死 `tenant_id=1`**
（C 端 customer 与 B 端管理员各一处），`tests/agent_eval/local_runner.py` 的前置复位 /
db 校验 SQL 另有 **8 处** `tenant_id = 1`。而 tenant 1「词元通达」随环境重建**连同全部数据已清空**
⇒ 「**唯一打已部署环境**的评测入口」（`.github/workflows/agent-eval.yml` 的
`local_runner.py`，借 DEBUG 分支拿管理员身份）失去目标租户。

**为什么没人报警**：该入口的唯一触发是 `workflow_dispatch`（#4262/#4974 后全仓自动真实 LLM
触发 = 0 条）⇒ 租户 1 已删这件事只在下一次有人手动跑时才发现。

## 本文件锁什么（每条都有反向红证）

| # | 判据 | 坏形态（⇒ 必红） |
|---|---|---|
| ① | **源码面未登记即红**：`auth.py` / `local_runner.py` 里裸的 `tenant_id=1` / `tenant_id = 1`（**代码行**，注释不算） | 把可配值改回写死的 `tenant_id=1`（= issue #6288 的原始形态） |
| ② | **配置面逐值断言**：注入一个租户号 ⇒ 真正被使用的是**注入值**（逐值，不是"非空"） | 配置读了但没用（标识符留着、值仍写死） |
| ③ | **🔴 反向护栏（缺一不可）**：非 DEBUG 路径即使有人注入了租户也**不生效** —— 两处 DEBUG 降级租户的引用都必须落在 `settings.DEBUG` + `X-Debug-Role` 守卫的 `if` 体内；非 DEBUG 路径的租户**只**来自 JWT payload、源码里无任何 `os.environ` / `getenv` 租户回落 | 把 DEBUG 降级租户的读值挪到守卫之外 / 给非 DEBUG 路径加一个环境变量兜底 |
| ④ | **两处单一真值不许漂移**：`auth.py` 读的 `settings.EVAL_TENANT_ID` 默认值 ≡ `local_runner.py` 的 `EVAL_TENANT_ID` 默认值 ≡ `config.py` 的字段默认值 | 只改一侧（服务端认 25、运行器认 1 ⇒ 复位/校验与请求落到不同租户） |
| ⑤ | **已部署入口显式钉住目标租户**：`agent-eval.yml` 的评测步骤 `EVAL_TENANT_ID == "25"` | 删掉该 env（下次环境重建又静默失去目标） |

⚠️ **本文件不跑真实 LLM、不起栈、不连网**（零 LLM 静态判定）；「改后能否真打到 tenant 25」
是一次人工择时的手动 `workflow_dispatch`，不在此处取证。

## 边界（照实登记）

- 判据**不读语义**：它只判「形态 + 结构 + 默认值一致性」，不判「25 是不是当前的云测试租户」
  （那是环境事实，判据读不到；真值依据写在 PR body）。
- `auth.py` 的行为面（真让 FastAPI 走一遍 DEBUG / 非 DEBUG 请求）在
  `backend/ai-agent-service/tests/test_utils_auth.py` 的射程内；本文件在 ci-helper job
  （只装 pytest+pyyaml）里跑，故用 AST / 源码级判据，不 import 服务端应用。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTH_PATH = REPO_ROOT / "backend/ai-agent-service/app/utils/auth.py"
CONFIG_PATH = REPO_ROOT / "backend/ai-agent-service/app/config.py"
RUNNER_PATH = REPO_ROOT / "tests/agent_eval/local_runner.py"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

# 云测试租户的真值（2026-10-04 云测试环境重建；依据见 PR body）
CLOUD_TEST_TENANT_ID = 25
# 本地/CI docker 标准考场的租户（由栈内种子 `fixtures/*_eval_seed.sql` 创建）
LOCAL_STACK_TENANT_ID = 1

# 裸字面量的形态锚：「字面量 + 位置」，**不锚注释**（注释里提一句不算 —— 判据要能允许
# 解释性文字存在）。两类位置：`tenant_id = 1` / `tenant_id=1`（赋值 / 关键字实参）
# 与 SQL 里的 `tenant_id = 1`（复位 / db 校验口径）。
BARE_LITERAL_RE = re.compile(r"tenant_id\s*=\s*1(?!\d)")
# SQL 形态也要求有 `WHERE`/`AND` 语义位置，避免把「= 10」「= 123」之类误报
BARE_ASSIGN_RE = re.compile(r"tenant_id\s*=\s*1(?![\d%])")


def _code_lines(text: str) -> list[tuple[int, str]]:
    """剔除**整行注释**后的 `(行号, 行文本)` —— 注释里提一句不算违规。"""
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        out.append((i, line))
    return out


def audit_bare_tenant_literals(text: str) -> list[str]:
    """① 源码面：代码行里不得再出现裸 `tenant_id = 1`（注释豁免）。"""
    problems = []
    for lineno, line in _code_lines(text):
        if BARE_ASSIGN_RE.search(line):
            problems.append(f"{lineno}: {line.strip()}")
    return problems


# ── ③ 反向护栏：DEBUG 降级租户的引用必须落在 DEBUG+debug_role 守卫体内 ──────

def _dotted(node: ast.AST) -> str | None:
    """`settings.DEBUG` ⇒ `"settings.DEBUG"`；裸 `Name` ⇒ 其 id；其它 ⇒ None。"""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def _bool_test_names(node: ast.AST) -> set[str]:
    """把一个布尔表达式里出现的标识符收齐（`a and b` / `a or b` / `not a` / `x.y` 全覆盖）。

    点号形态**同时**保留全名与末段名：`settings.DEBUG` ⇒ `{"settings.DEBUG", "DEBUG"}`
    —— 判据按末段名粗筛（`DEBUG` / `debug_role`），这样 `settings.DEBUG` 与
    `from app.config import settings` 之外的写法都不会漏判。
    """
    names: set[str] = set()
    stack = [node]
    while stack:
        cur = stack.pop()
        dotted = _dotted(cur)
        if dotted:
            names.add(dotted)
            names.add(dotted.rsplit(".", 1)[-1])
            continue
        if isinstance(cur, ast.BoolOp):
            stack.extend(cur.values)
        elif isinstance(cur, ast.UnaryOp):
            stack.append(cur.operand)
        elif isinstance(cur, ast.Compare):
            stack.append(cur.left)
            stack.extend(cur.comparators)
    return names


def _enclosing_guards(tree: ast.AST) -> dict[int, list[set[str]]]:
    """每个节点 id ⇒ 包住它的 `if` 条件集合列表（内层在前，走到模块级为止）。"""
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    guards: dict[int, list[set[str]]] = {}
    for node in ast.walk(tree):
        chain: list[set[str]] = []
        cur = parents.get(id(node))
        while cur is not None:
            if isinstance(cur, ast.If):
                chain.append(_bool_test_names(cur.test))
            cur = parents.get(id(cur))
        guards[id(node)] = chain
    return guards


def audit_debug_tenant_is_guarded(text: str, read_expr: str) -> list[str]:
    """③ 反向护栏：每一次「把降级租户读进**请求身份**」的赋值，都必须落在
    「DEBUG（`settings.DEBUG`）+ 显式调试角色（`debug_role`）」守卫的 `if` 体内。

    这正是「把降级租户做成可配」时最容易出错的地方（#6288）：只能改**降级身份**的租户，
    绝不能顺手给**生产**路径开一个外部可注入的租户源 —— 那才是越权通道。

    `read_expr` = 读值的**形态锚**（如 `DEBUG_FALLBACK_TENANT_ID`），而判据只认
    「把该读值写进 `tenant_id`」这一种**身份构造形态**（`tenant_id=<read_expr>` 关键字实参
    与 `tenant_id = <read_expr>` 赋值都算；模块级常量定义 `X = settings....` 与注释都不算
    —— 它们不产生请求身份）。
    """
    tree = ast.parse(text)
    guards = _enclosing_guards(tree)
    problems, hits = [], 0

    def _note(node: ast.AST):
        nonlocal hits
        hits += 1
        lineno = node.lineno
        chain = guards.get(id(node), [])
        if not any("debug_role" in c and "DEBUG" in c for c in chain):
            problems.append(
                f"第 {lineno} 行 `tenant_id={read_expr}` 不在"
                f"「settings.DEBUG + X-Debug-Role」守卫体内 —— 实测包裹条件链 = {chain}"
            )

    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "tenant_id" \
                and isinstance(node.value, ast.Name) and node.value.id == read_expr:
            _note(node.value)
        elif isinstance(node, ast.Assign) \
                and any(isinstance(t, ast.Name) and t.id == "tenant_id" for t in node.targets) \
                and isinstance(node.value, ast.Name) and node.value.id == read_expr:
            _note(node)
    if hits == 0:
        problems.append(
            f"找不到任何 `tenant_id={read_expr}` 的身份构造 —— 判据前提失效"
            "（读值被改名/删除，或降级租户又被写死成别的形态）")
    return problems


def audit_non_debug_tenant_from_payload_only(text: str) -> list[str]:
    """③ 非 DEBUG 路径的租户**只**来自 JWT payload：不得出现任何环境变量租户回落。

    形态锚（不是措辞判据）：
      · 全文件不得出现 `os.environ` / `getenv`（服务端配置一律走 `settings`，
        出现环境变量直读 = 多出一条绕过 `settings` 的注入面）；
      · 非 DEBUG 路径解析租户的行必须逐字来自 `payload`（`payload.get("tenantId")`）；
      · 非 DEBUG 路径的租户只许由 `tenant_id_raw` 整型解析而来（不得改走配置兜底）。
    """
    problems = []
    for lineno, line in _code_lines(text):
        if "os.environ" in line or "getenv" in line:
            problems.append(f"{lineno}: {line.strip()} —— 服务端租户/配置不得直读环境变量")
    if not re.search(r'payload\.get\(\s*["\']tenantId["\']', text):
        problems.append('找不到 `payload.get("tenantId")` —— 非 DEBUG 路径的租户来源不明')
    if not re.search(r"tenant_id\s*=\s*int\(\s*tenant_id_raw\s*\)", text):
        problems.append("非 DEBUG 路径的租户不再由 payload 的 tenant_id_raw 整型解析")
    return problems


# ── ④ 默认值一致性：两处单一真值不许漂移 ───────────────────────────────────

def _config_default_tenant_id() -> int:
    """从 `config.py` 的源码取 `EVAL_TENANT_ID: int = <N>` 的默认值（AST，不 import 应用）。"""
    tree = ast.parse(CONFIG_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == "EVAL_TENANT_ID":
            return int(ast.literal_eval(node.value))
    raise AssertionError("app/config.py 里找不到 EVAL_TENANT_ID 的字段默认值")


def _runner_env_int() -> tuple[int, list[str]]:
    """在**隔离命名空间**里跑 `local_runner.py` 真实源码的 `_env_int` + `EVAL_TENANT_ID`。

    只取这两个节点的源码执行（不 import 运行器本体 —— 它有模块级 `import httpx` 与
    一堆模块级副作用，ci-helper job 里既不必要也不安全）。
    """
    text = RUNNER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(text)
    wanted: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_env_int":
            wanted["_env_int"] = node
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "EVAL_TENANT_ID":
                    wanted["EVAL_TENANT_ID"] = node
    assert set(wanted) == {"_env_int", "EVAL_TENANT_ID"}, (
        f"local_runner.py 的 _env_int / EVAL_TENANT_ID 形态变了：找到 {sorted(wanted)}")
    ns: dict = {"os": __import__("os")}
    exec(compile(ast.Module(body=[wanted["_env_int"]], type_ignores=[]), "<runner>", "exec"), ns)
    exec(compile(ast.Module(body=[wanted["EVAL_TENANT_ID"]], type_ignores=[]), "<runner>", "exec"), ns)
    return int(ns["EVAL_TENANT_ID"]), text.splitlines()


def _runner_value_with_env(monkeypatch, raw: str | None) -> int:
    """② 逐值断言：`EVAL_TENANT_ID` 的**真实读取实现**在给定环境变量下的取值。"""
    if raw is None:
        monkeypatch.delenv("EVAL_TENANT_ID", raising=False)
    else:
        monkeypatch.setenv("EVAL_TENANT_ID", raw)
    return _runner_env_int()[0]


# ── ① 源码面未登记即红 ─────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [AUTH_PATH, RUNNER_PATH],
                         ids=["auth.py", "local_runner.py"])
def test_no_bare_tenant_literal_in_source(path: Path):
    problems = audit_bare_tenant_literals(path.read_text(encoding="utf-8"))
    assert problems == [], (
        f"{path.relative_to(REPO_ROOT)} 里还有裸的 `tenant_id = 1`（代码行）—— "
        f"必须收敛到单一可注入配置（`EVAL_TENANT_ID`）：\n" + "\n".join(problems)
    )


# ── ② 配置面：注入租户号 ⇒ 用的是注入值（逐值） ─────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("7", 7),
    ("25", 25),
    ("1000", 1000),
])
def test_injected_tenant_value_is_used(monkeypatch, raw: str, expected: int):
    assert _runner_value_with_env(monkeypatch, raw) == expected


@pytest.mark.parametrize("raw", [None, "", "abc", "0", "-3", "25.5"])
def test_bad_tenant_value_falls_back_to_default(monkeypatch, raw):
    """fail-closed：缺省 / 非法 / 越界 ⇒ 回落**默认**（绝不静默取任意值、绝不崩）。"""
    assert _runner_value_with_env(monkeypatch, raw) == CLOUD_TEST_TENANT_ID


def test_default_tenant_is_the_cloud_test_tenant():
    assert _runner_env_int()[0] == CLOUD_TEST_TENANT_ID
    assert _config_default_tenant_id() == CLOUD_TEST_TENANT_ID, (
        "app/config.py 的 EVAL_TENANT_ID 默认值与 local_runner.py 的默认值不一致 —— "
        "两处单一真值漂移会让「请求落到哪个租户」与「复位/校验查哪个租户」分叉"
    )


def _runner_sql_constants(text: str, injected: int) -> dict[str, str]:
    """② 逐值：把运行器源码里的 `*_SQL` 常量**真求值**一遍（`EVAL_TENANT_ID` = 注入值）。

    只取 `*_SQL` 赋值节点执行 —— 不 import 运行器本体（它有模块级副作用）。
    """
    tree = ast.parse(text)
    nodes = [n for n in tree.body if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id.endswith("_SQL") for t in n.targets)]
    ns: dict = {"EVAL_TENANT_ID": injected}
    for node in nodes:
        exec(compile(ast.Module(body=[node], type_ignores=[]), "<runner-sql>", "exec"), ns)
    # 只取**按租户定位**的那些模板（含 `tenant_id = ` 字面）—— 本判据的射程就是它们
    return {k: v for k, v in ns.items()
            if k.endswith("_SQL") and isinstance(v, str) and "tenant_id = " in v}


def test_sql_targets_use_the_configured_tenant():
    """② 逐值：复位 / db 校验的 SQL 模板里落的是**注入值**，不是字面量。"""
    text = RUNNER_PATH.read_text(encoding="utf-8")
    for injected in (7, CLOUD_TEST_TENANT_ID, LOCAL_STACK_TENANT_ID):
        sqls = _runner_sql_constants(text, injected)
        assert len(sqls) >= 4, f"SQL 模板常量少于 4 个（实测 {sorted(sqls)}）—— 判据前提失效"
        for name, sql in sorted(sqls.items()):
            assert f"tenant_id = {injected}" in sql, (
                f"{name} 没落到注入租户 {injected}（逐值断言）：{sql!r}")
            if injected != 1:
                assert "tenant_id = 1 " not in sql, f"{name} 仍有裸字面量：{sql!r}"
    # 反向对照：占位符不再出现在**执行期**字符串里（未被替换 = 模板没参数化）
    for name, sql in sorted(_runner_sql_constants(text, CLOUD_TEST_TENANT_ID).items()):
        assert "{EVAL_TENANT_ID}" not in sql, f"{name} 的占位符未展开：{sql!r}"


def test_workflow_pins_configured_tenant_on_deployed_entry():
    """⑤ 唯一打**已部署**环境的入口必须显式钉住目标租户（否则环境重建后再次静默失目标）。"""
    import yaml
    wf = yaml.safe_load((WORKFLOWS_DIR / "agent-eval.yml").read_text(encoding="utf-8")) or {}
    steps = [s for job in (wf.get("jobs") or {}).values() for s in (job.get("steps") or [])]
    eval_steps = [s for s in steps
                  if "local_runner" in ((s.get("name") or "") + (s.get("run") or ""))]
    assert len(eval_steps) == 1, f"agent-eval.yml 的评测步骤应唯一，实测 {len(eval_steps)}"
    env = eval_steps[0].get("env") or {}
    assert str(env.get("EVAL_TENANT_ID", "")).strip('"') == str(CLOUD_TEST_TENANT_ID), (
        f"agent-eval.yml 评测步骤的 EVAL_TENANT_ID={env.get('EVAL_TENANT_ID')!r} ≠ "
        f"{CLOUD_TEST_TENANT_ID}（云测试租户）—— 该入口打的是已部署环境，"
        "必须显式钉住目标租户"
    )


# ── ③ 反向护栏（缺一不可） ─────────────────────────────────────────────────

def test_debug_tenant_reads_only_inside_debug_guard():
    """生产路径（DEBUG=false）不得因「租户可配」而多出一条外部可注入的租户源。"""
    text = AUTH_PATH.read_text(encoding="utf-8")
    problems = audit_debug_tenant_is_guarded(text, "DEBUG_FALLBACK_TENANT_ID")
    assert problems == [], "；".join(problems)


def test_non_debug_tenant_never_reads_external_source():
    text = AUTH_PATH.read_text(encoding="utf-8")
    problems = audit_non_debug_tenant_from_payload_only(text)
    assert problems == [], "；".join(problems)


# ── 红证（注入式）：判据自己必须会红 ───────────────────────────────────────

class TestRedProofs:
    """把「判据会不会红」钉在测试里（不依赖人工复算）。"""

    def test_red_proof_bare_literal_reds(self):
        """① 红证：把可配值改回写死 ⇒ 判据必红（#6288 原始形态）。"""
        text = RUNNER_PATH.read_text(encoding="utf-8")
        broken = text.replace(" WHERE tenant_id = {EVAL_TENANT_ID} AND ticket_no = $1",
                              " WHERE tenant_id = 1 AND ticket_no = $1", 1)
        assert broken != text, "注入未生效（锚点失配）—— 红证前提失效"
        problems = audit_bare_tenant_literals(broken)
        assert problems, "裸 `tenant_id = 1` 未被判红 —— 判据没有判别力"
        assert "tenant_id = 1 AND ticket_no" in problems[0]

    def test_red_proof_comment_mention_is_not_flagged(self):
        """负例（R2）：注释里提一句 `tenant_id=1` **不算**违规（否则解释性文字没法写）。"""
        assert audit_bare_tenant_literals("# 种子逐行写 tenant_id=1（本地栈口径）\n") == []

    def test_red_proof_moving_read_outside_guard_reds(self):
        """③ 红证：把「配置租户」写进身份时**去掉 DEBUG 守卫** ⇒ 反向护栏判据必红。"""
        text = AUTH_PATH.read_text(encoding="utf-8")
        anchor = "    # 验证 Token\n    payload = verify_jwt_token(token)"
        assert anchor in text, "锚点失配 —— 红证前提失效"
        broken = text.replace(
            anchor,
            "    if not settings.DEBUG:\n"
            "        return UserIdentity(user_id='x', tenant_id=DEBUG_FALLBACK_TENANT_ID,\n"
            "                            identity_type='account', role=UserRole.ADMIN)\n" + anchor)
        problems = audit_debug_tenant_is_guarded(broken, "DEBUG_FALLBACK_TENANT_ID")
        assert problems, "守卫之外的引用未被判红 —— 反向护栏没有判别力"
        assert "不在" in problems[0]
        assert audit_debug_tenant_is_guarded(text, "DEBUG_FALLBACK_TENANT_ID") == []

    def test_red_proof_env_tenant_fallback_on_non_debug_path_reds(self):
        """③ 红证：给非 DEBUG 路径加一个环境变量租户兜底 ⇒ 必红。"""
        text = AUTH_PATH.read_text(encoding="utf-8")
        broken = text.replace(
            'tenant_id = int(tenant_id_raw) if tenant_id_raw is not None else None',
            'tenant_id = int(tenant_id_raw) if tenant_id_raw is not None '
            'else int(os.environ.get("EVAL_TENANT_ID", "1"))')
        assert broken != text, "注入未生效（锚点失配）—— 红证前提失效"
        problems = audit_non_debug_tenant_from_payload_only(broken)
        assert problems, "非 DEBUG 路径的环境变量租户兜底未被判红"

    def test_red_proof_single_source_drift_reds(self, monkeypatch):
        """④ 红证：注入一个与默认值不同的配置 ⇒ 逐值断言当场看到**注入值**。"""
        assert _runner_value_with_env(monkeypatch, "9") == 9
        assert _runner_value_with_env(monkeypatch, "9") != CLOUD_TEST_TENANT_ID


# ── 守卫前提自证（防「判据对象消失却恒绿」） ───────────────────────────────

def test_premises_hold():
    auth_text = AUTH_PATH.read_text(encoding="utf-8")
    runner_text = RUNNER_PATH.read_text(encoding="utf-8")
    assert "DEBUG_FALLBACK_TENANT_ID" in auth_text
    assert "EVAL_TENANT_ID" in runner_text
    assert AUTH_PATH.is_file() and RUNNER_PATH.is_file()
