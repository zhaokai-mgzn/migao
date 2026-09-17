# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI / 结构类 L0 不变式统一挂 MC-012，
#   「静态结构由 pytest 单测验证」是 misc.yml 里已登记的形态）
"""L0 机制守卫：工具入参契约（issue #4080 = 母单 #4043 的 T-B 包）。

## 病灶形状（R5 明令禁止的「静默失效」）

| 事实 | 改前形态 |
|---|---|
| 工具**声明**了入参契约 | 每个工具类都有 `parameters`（`type/properties/required/enum/description`） |
| `BaseTool._get_args_schema()` | 实现体**字面 `return None`**（注释自述"简化实现"）⇒ 声明存在、零消费 |
| 执行入口 | 取到 `args` 直接执行，**没有任何一层**按声明校验 |
| 「缺哪个参数」 | 靠**中文错误原文子串匹配**（`WRITE_INPUT_ERROR_PARAMS` + `key in text`）—— 文案改一个字判据就静默失效 |

## 本文件锁的两条 L0 判据（纯 AST、零后端依赖、秒级）

1. **契约真的被消费**：`_get_args_schema()` 不得退回桩实现；`BaseTool` 必须有一个**真会失败**的
   `validate_args()`；**两条共享执行路径**（`base_skill._execute_tool_safe` 与
   `ToolRegistry.execute_tool`）必须真的调用它。缺任一条 ⇒ 报红（"声明了没人用"就是这个形态）。
2. **不得再新增「中文措辞匹配」式判据**：`app/**` 里「把中文措辞当判据」的站点数
   （① `<中文常量> in/not in <表达式>`；② 含 ≥2 个中文 key 的 dict 字面量）**只许缩短**，
   基线 `.github/tool-input-contract-baseline.json` 逐文件计数；新增站点 ⇒ 报红。

## 红证与不适用域（R1/R2）

- 每条判据都带**落盘夹具红证**：把「退回桩实现」「调用点不校验」「植入一条新的中文子串匹配」
  写进 `tmp_path` ⇒ 判据**必报**；去掉 ⇒ **必不报**（防"永远绿的空判据"，见 §19.1 元规则）。
- **fail-closed**：被扫文件/函数解析不到（改名、搬目录）⇒ 报错，**不静默通过**。
- **不适用域**：① 行为面（真的拦住缺参、真的带 `suggestion`）由
  `backend/ai-agent-service/tests/unit/test_tool_input_contract.py` 覆盖，本文件**不替代**它；
  ② 其余合法中文匹配（路由/规则匹配、ASR 文本、物流状态映射表）是**存量基线**，只锁"不新增"，
  不要求本次改造（R4：新违规的两个出口是「本次修掉」或「开独立 issue」）。
"""

import ast
import json
import re
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_DIR = REPO_ROOT / "backend" / "ai-agent-service"
APP_DIR = SERVICE_DIR / "app"
BASE_PY = APP_DIR / "tools" / "base.py"
BASE_SKILL_PY = APP_DIR / "graph" / "skills" / "base_skill.py"
REGISTRY_PY = APP_DIR / "tools" / "registry.py"
ORDER_CREATE_PY = APP_DIR / "tools" / "order_create.py"
BASELINE_PATH = REPO_ROOT / ".github" / "tool-input-contract-baseline.json"

_CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")


# ──────────────────────────────────────────────────────────────────────────────
# 判据本体（纯函数 —— 测试与夹具共用这一处，不写第二份口径）
# ──────────────────────────────────────────────────────────────────────────────


def _parse(source: str, origin: str = "<fixture>") -> ast.Module:
    return ast.parse(source, filename=origin)


def _function(tree: ast.Module, name: str) -> ast.AST:
    """按名取函数节点；取不到就**报错**（fail-closed：改名/搬走不得让判据静默通过）。"""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"被测函数 `{name}` 不存在（判据会空转 —— 宁可红）")


def stub_none_functions(source: str) -> list[str]:
    """模块里**体是桩**的函数名：「只有 docstring/`pass` + `return None`」。

    `BaseTool._get_args_schema()` 的改前形态就是它（注释自述"简化实现：返回 None"）——
    「声明了参数契约，却返回 None 让下游拿不到 schema」= 声明与实现各说各话。
    """
    names: list[str] = []
    for node in ast.walk(_parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = [st for st in node.body
                if not (isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant)
                        and isinstance(st.value.value, str))]
        body = [st for st in body if not isinstance(st, ast.Pass)]
        if len(body) == 1 and isinstance(body[0], ast.Return) \
                and isinstance(body[0].value, ast.Constant) and body[0].value.value is None \
                and node.returns is not None:
            names.append(node.name)
    return names


def validate_args_call_sites(source: str) -> list[str]:
    """**调用了 `validate_args`** 的函数名（共享执行路径必须在这里面）。

    认两种形态（都是本仓真实写法）：
      ① 属性调用 `tool.validate_args(args)`（`ToolRegistry.execute_tool`）；
      ② `getattr(tool, "validate_args", None)` + 调用（`_execute_tool_safe` —— 对鸭子类型
         替身 fail-open，不能直接属性取用）。
    """
    sites: list[str] = []
    for node in ast.walk(_parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute) \
                    and inner.func.attr == "validate_args":
                sites.append(node.name)
                break
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name) \
                    and inner.func.id == "getattr" \
                    and any(isinstance(a, ast.Constant) and a.value == "validate_args"
                            for a in inner.args):
                sites.append(node.name)
                break
    return sites


def functions_returning_tool_result(source: str) -> set:
    """模块里**直接** `return ToolResult(...)` 的函数名集合。"""
    names = set()
    for node in ast.walk(_parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Return) and isinstance(inner.value, ast.Call) \
                    and isinstance(inner.value.func, ast.Name) \
                    and inner.value.func.id == "ToolResult":
                names.add(node.name)
    return names


def function_returns_a_failure_result(source: str, name: str) -> bool:
    """函数是否**真会失败**：`return ToolResult(...)`，或 `return <本模块内返回 ToolResult 的助手>(...)`。

    为什么允许一跳（实测形态）：`BaseTool.validate_args()` 的失败出口是
    `return self._args_error(...)`，而 `_args_error()` 才是构造 `ToolResult` 的那一处 ——
    只认直接形态会把**真会失败的**校验器判成空判据（假红，§19.1 元规则）。
    """
    producers = functions_returning_tool_result(source)
    for inner in ast.walk(_function(_parse(source), name)):
        if not isinstance(inner, ast.Return) or not isinstance(inner.value, ast.Call):
            continue
        fn = inner.value.func
        fn_name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
        if fn_name == "ToolResult" or fn_name in producers:
            return True
    return False


def chinese_wording_sites(source: str) -> list[tuple]:
    """把**中文措辞当判据**的站点：`(形态, 行号)`，形态 ∈ {`in`, `dict`}。

    - `in`：`<中文常量> in/not in <表达式>` —— 子串匹配（`WRITE_INPUT_ERROR_PARAMS` 的消费方式）；
    - `dict`：含 **≥2 个中文 key** 的 dict 字面量 —— 「措辞 → 语义」映射表。
    """
    sites: list[tuple] = []
    for node in ast.walk(_parse(source)):
        if isinstance(node, ast.Compare) and len(node.ops) == 1 \
                and isinstance(node.ops[0], (ast.In, ast.NotIn)):
            left = node.left
            if isinstance(left, ast.Constant) and isinstance(left.value, str) \
                    and _CHINESE_RE.search(left.value):
                sites.append(("in", node.lineno))
        if isinstance(node, ast.Dict):
            chinese_keys = [k for k in node.keys
                            if isinstance(k, ast.Constant) and isinstance(k.value, str)
                            and _CHINESE_RE.search(k.value)]
            if len(chinese_keys) >= 2:
                sites.append(("dict", node.lineno))
    return sites


def app_source_files(app_dir: Path = APP_DIR) -> list[Path]:
    files = sorted(app_dir.rglob("*.py"))
    if not files:
        raise AssertionError(f"`{app_dir}` 下扫不到任何 .py —— 判据会空转（fail-closed）")
    return files


def live_chinese_wording_counts(app_dir: Path = APP_DIR) -> dict:
    """当前每个文件的中文措辞判据站点数（相对 `app/` 的路径 → 计数）。"""
    counts: Counter = Counter()
    for path in app_source_files(app_dir):
        n = len(chinese_wording_sites(path.read_text(encoding="utf-8")))
        if n:
            counts[path.relative_to(app_dir).as_posix()] = n
    return dict(counts)


def load_chinese_wording_baseline(path: Path = BASELINE_PATH) -> dict:
    """存量基线（**只许缩短**）。文件缺失 = 空基线（任何站点都会报红，fail-closed）。

    形态是 `files: [{path, count}, …]` —— **刻意不用「路径 + 冒号 + 数字」那种写法**：
    该文本形态会被 Case Trust Gate 的 `CASE-TRUST-STALE-LINE-REF` 当成行号引用扫描
    （实测 7 条假红）。属**引用格式**问题，改格式即可，判据一条不动。
    """
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("files", [])
    assert isinstance(entries, list), f"{path} 的 `files` 必须是列表（fail-closed）"
    baseline = {}
    for entry in entries:
        assert isinstance(entry, dict) and "path" in entry and "count" in entry, (
            f"基线条目形态必须是 {{path, count}}：{entry!r}"
        )
        baseline[str(entry["path"])] = int(entry["count"])
    return baseline


def chinese_wording_growth(current: dict, baseline: dict) -> dict:
    """**新增**的中文措辞判据站点（计数超过基线的文件 → 超出量）。只许缩短。"""
    return {rel: n - baseline.get(rel, 0) for rel, n in current.items()
            if n > baseline.get(rel, 0)}


# ──────────────────────────────────────────────────────────────────────────────
# 判据 ①：契约真的被消费（schema 生成 + 两条共享执行路径都校验）
# ──────────────────────────────────────────────────────────────────────────────


class TestInputContractIsConsumed:
    """`parameters` 的声明必须有**真的消费点**（不是 `return None` 的桩 + 没人调）。"""

    def test_get_args_schema_is_not_a_stub(self):
        """`BaseTool._get_args_schema()` 不得退回 `return None` 的桩实现。"""
        stubs = stub_none_functions(BASE_PY.read_text(encoding="utf-8"))

        assert "_get_args_schema" not in stubs, (
            "`BaseTool._get_args_schema()` 又是「只有 docstring + `return None`」的桩 —— "
            "工具声明的 `parameters` 在这一层没有消费者（`to_langchain_tool()` 会把 None "
            "当 `args_schema` 传下去）"
        )

    def test_base_tool_exposes_a_validator_that_can_fail(self):
        """`BaseTool.validate_args()` 必须存在，且**体里真有一条失败返回**（不是恒放行）。"""
        source = BASE_PY.read_text(encoding="utf-8")
        body_present = "validate_args" in [n.name for n in ast.walk(_parse(source))
                                          if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

        assert body_present, "`BaseTool` 没有 `validate_args()` —— 入参契约没有校验器"
        assert function_returns_a_failure_result(source, "validate_args"), (
            "`validate_args()` 里没有任何 `return ToolResult(...)` 路径 —— 恒放行的空判据"
        )

    def test_shared_execution_paths_call_the_validator(self):
        """两条共享执行路径都必须调用校验器（R1：不逐工具手写，判据落在共享入口）。"""
        agent_path = validate_args_call_sites(BASE_SKILL_PY.read_text(encoding="utf-8"))
        registry_path = validate_args_call_sites(REGISTRY_PY.read_text(encoding="utf-8"))

        assert "_execute_tool_safe" in agent_path, (
            "`base_skill._execute_tool_safe`（小布/米宝的共享执行入口）没有调用 "
            f"`validate_args` —— 声明的 required 在执行前不会被校验（实测调用点：{agent_path}）"
        )
        assert "execute_tool" in registry_path, (
            "`ToolRegistry.execute_tool`（内部/直调入口）没有调用 `validate_args`"
            f"（实测调用点：{registry_path}）"
        )

    def test_role_conditional_required_is_not_widened(self):
        """R2 锁：`order_create` 的角色条件必填（`sms_code`）**不得**被塞进 `required`。

        判据来源是工具自己的声明（`description` 写着「customer角色必填，admin/agent不需要」）——
        一旦有人把它当必填，B 端（admin/agent）下单流程会被**全拦死**。
        """
        source = ORDER_CREATE_PY.read_text(encoding="utf-8")
        required = None
        for node in ast.walk(_parse(source)):
            if not isinstance(node, ast.ClassDef):
                continue
            for st in node.body:
                if isinstance(st, ast.Assign) \
                        and any(getattr(t, "id", None) == "parameters" for t in st.targets):
                    value = ast.literal_eval(st.value)
                    required = list(value.get("required") or [])

        assert required == ["customer_name", "customer_phone", "items"], (
            f"`order_create.parameters['required']` 变了（实测 {required}）—— "
            "`sms_code` 是**角色条件**必填（customer 才要），进 `required` 会把 B 端流程全拦死；"
            "确实需要变更时请连同本判据与 R2 负例一起改，不要单方面放宽"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 判据 ②：不得再新增「中文措辞匹配」式判据（只许缩短）
# ──────────────────────────────────────────────────────────────────────────────


class TestNoNewChineseWordingJudgement:
    """R5：靠中文措辞语料承载判据 ⇒ 改一个字判据就静默失效。基线只许缩短。"""

    def test_no_file_exceeds_its_baseline(self):
        current = live_chinese_wording_counts()
        baseline = load_chinese_wording_baseline()
        growth = chinese_wording_growth(current, baseline)

        assert growth == {}, (
            "以下文件**新增**了「中文措辞当判据」的站点（`<中文串> in <文本>` 或 "
            f"中文 key 的映射表）：{growth}\n"
            f"  当前逐文件计数 = {current}\n"
            f"  基线（只许缩短）= {baseline}\n"
            "→ 缺参/失败语义请走**结构化字段**（`ToolResult.missing_params` / `error` 码），"
            "不要在错误文案上做子串匹配；确有必要时开独立 issue 讨论，不要就地放宽基线。"
        )

    def test_baseline_shrinks_or_accepts_the_past_but_never_grows(self):
        """基线本身**只许缩短**：当前总量不得超过基线条数对应的总量。"""
        current = live_chinese_wording_counts()
        baseline = load_chinese_wording_baseline()

        assert sum(current.values()) <= sum(baseline.values()), (
            "中文措辞判据站点总量超过了基线 —— 基线只许缩短，不得为了让守卫变绿而扩容"
        )
        assert sum(baseline.values()) > 0, (
            "基线为空时本判据退化成「零容忍」—— 与存量现实不符；"
            "若确实已清零，请连同本断言一起改成「必须为 0」的强判据"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 判据自身的红证 + 阴性负例（落盘夹具注入：真写文件、真扫目录）
# ──────────────────────────────────────────────────────────────────────────────

_STUB_FIXTURE = '''"""夹具：`_get_args_schema` 退回桩实现（判据必须报出）。"""
from typing import Optional


class BaseTool:
    def _get_args_schema(self) -> Optional[type]:
        """获取参数 Pydantic Schema（用于 LangChain）"""
        return None
'''

_REAL_FIXTURE = '''"""夹具：同一函数真的生成 schema（判据必须不报）。"""
from typing import Optional


class BaseTool:
    def _get_args_schema(self) -> Optional[type]:
        """获取参数 Pydantic Schema（用于 LangChain）"""
        return build_args_schema(self.name, self.parameters)
'''

_NO_CALL_FIXTURE = '''"""夹具：共享执行路径不调用校验器（判据必须报出）。"""
async def _execute_tool_safe(tool, tool_args, tool_context, state):
    result = await tool.execute(tool_context, **tool_args)
    return result
'''

_WITH_CALL_FIXTURE = '''"""夹具：共享执行路径调用校验器（判据必须不报）。"""
async def _execute_tool_safe(tool, tool_args, tool_context, state):
    failure = tool.validate_args(tool_args)
    if failure is not None:
        return failure
    return await tool.execute(tool_context, **tool_args)
'''

_GETATTR_CALL_FIXTURE = '''"""夹具：getattr 形态取校验器（判据必须认，见 _execute_tool_safe 的真实写法）。"""
async def _execute_tool_safe(tool, tool_args, tool_context, state):
    check = getattr(tool, "validate_args", None)
    if callable(check):
        failure = check(tool_args)
        if failure is not None:
            return failure
    return await tool.execute(tool_context, **tool_args)
'''

_ALWAYS_PASS_VALIDATOR = '''"""夹具：恒放行的校验器（判据必须报出「不是真会失败」）。"""
class BaseTool:
    def validate_args(self, args):
        """永远放行"""
        return None
'''

_HELPER_VALIDATOR = '''"""夹具：失败出口是助手（判据必须认一跳，实测形态）。"""
class BaseTool:
    def validate_args(self, args):
        """校验"""
        if not args:
            return self._args_error("missing_required_args")
        return None

    def _args_error(self, code):
        return ToolResult(success=False, error=code)
'''

_PLANTED_CHINESE_FIXTURE = '''"""夹具：植入一条**新的**中文措辞匹配（判据必须报出）。"""


def is_missing_code(error_text):
    return "缺少短信验证码" in error_text
'''

_CLEAN_FIXTURE = '''"""夹具：同一语义走结构化字段（判据必须不报）。"""


def is_missing_code(result_dict):
    return "sms_code" in (result_dict.get("missing_params") or [])
'''


class TestGuardsAreNotVacuous:
    """**:red_circle: 红证**（注入式）+ **负例**：每条判据都必须能报，也必须能不报。"""

    def test_stub_detector_reports_a_planted_stub(self):
        assert "BaseTool" not in stub_none_functions(_STUB_FIXTURE)  # 类名不构成判据
        assert stub_none_functions(_STUB_FIXTURE) == ["_get_args_schema"]

    def test_stub_detector_stays_quiet_on_a_real_implementation(self):
        assert stub_none_functions(_REAL_FIXTURE) == []

    def test_call_site_detector_reports_a_missing_call(self):
        assert validate_args_call_sites(_NO_CALL_FIXTURE) == []

    def test_call_site_detector_stays_quiet_when_the_call_is_present(self):
        assert validate_args_call_sites(_WITH_CALL_FIXTURE) == ["_execute_tool_safe"]

    def test_call_site_detector_recognises_the_getattr_form(self):
        """`getattr(tool, "validate_args", None)` 形态同样算「真的调用了」（生产写法之一）。"""
        assert validate_args_call_sites(_GETATTR_CALL_FIXTURE) == ["_execute_tool_safe"]

    def test_failure_result_detector_reports_a_always_pass_validator(self):
        """恒放行的校验器（只 `return None`）不得被当成"真会失败"。"""
        assert function_returns_a_failure_result(_ALWAYS_PASS_VALIDATOR, "validate_args") is False

    def test_failure_result_detector_accepts_the_one_hop_helper(self):
        """`return self._args_error(...)`（助手构造 ToolResult）算「真会失败」（实测形态）。"""
        assert function_returns_a_failure_result(_HELPER_VALIDATOR, "validate_args") is True

    def test_chinese_wording_detector_reports_a_planted_site(self, tmp_path):
        """植入**一条新的中文子串匹配** ⇒ 守卫必报（issue #4080 的机制守卫 ②）。"""
        planted_dir = tmp_path / "app"
        planted_dir.mkdir()
        (planted_dir / "planted_probe.py").write_text(_PLANTED_CHINESE_FIXTURE, encoding="utf-8")

        current = live_chinese_wording_counts(planted_dir)
        growth = chinese_wording_growth(current, {})

        assert current == {"planted_probe.py": 1}, f"植入的站点没被扫到：{current}"
        assert growth == {"planted_probe.py": 1}, "植入新中文判据后守卫没报 —— 这是空判据"

    def test_chinese_wording_detector_stays_quiet_on_the_structured_form(self, tmp_path):
        """阴性负例：同一语义走**结构化字段**时不得被误报。"""
        clean_dir = tmp_path / "app"
        clean_dir.mkdir()
        (clean_dir / "clean_probe.py").write_text(_CLEAN_FIXTURE, encoding="utf-8")

        assert live_chinese_wording_counts(clean_dir) == {}

    def test_growth_is_computed_per_file(self):
        """计数口径：同一文件里的**新增**站点必须能与基线区分开（只比文件存在与否是不够的）。"""
        assert chinese_wording_growth({"a.py": 3}, {"a.py": 2}) == {"a.py": 1}
        assert chinese_wording_growth({"a.py": 2}, {"a.py": 2}) == {}
        assert chinese_wording_growth({"b.py": 1}, {"a.py": 2}) == {"b.py": 1}

    def test_live_tree_is_scanned(self):
        """守卫不得空转：真树上必须扫到足量文件与站点（口径失效时**报错**而不是静默通过）。"""
        files = app_source_files()

        assert len(files) >= 50, f"`app/**` 只扫到 {len(files)} 个 .py —— 路径口径已失效"
        assert sum(live_chinese_wording_counts().values()) >= 10, (
            "真树上几乎扫不到中文措辞判据站点 —— 探测口径可能已失效（基线也就失去意义）"
        )