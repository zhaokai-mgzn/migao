# case_ids: MC-346
"""生产只读冒烟档（`tests/smoke/prod_readonly_profile.json`）的类级元守卫（issue #9082）。

## 病（2026-11-23 用户裁定）

逐字：「我们是 ai native 公司，冒烟都需要 AI 跑」+「以后还是需要先在测试机器上做充分验证，
只有要发布生产的时候才在发布前走一次生产环境的冒烟」。

⇒ 生产只跑**只读子集**（`--env prod`），日常充分验证在测试机跑完整档（`--env test`）。
只读子集**不能靠人记**：漏进一条写类用例，就在生产建单 / 建会话 / 烧 LLM 成本；改名一条，
就静默少跑（绿得没跑）。⇒ 本判据把这三件事都钉成会红的静态判据（零网络、零 LLM）：

| # | 判什么 | 取法 | 回归时会怎么红 |
|---|---|---|---|
| 1 | profile 每条 node id **真实存在** | AST 解 `tests/smoke/**` 的函数表 | 改名/删除后 ⇒ 具名红（防静默少跑） |
| 2 | profile 每条（**含 fixture 链**）不得对**非 auth 端点** `post/put/delete/patch` | AST 扫函数体 + fixture 递归；`/api/auth/**` 放行 | 塞入 `test_04_ai_chat::test_create_session` ⇒ 点名 `POST /api/chat/sessions` 红 |
| 3 | 每条必须写 `why`（一句「为什么只读」） | JSON 字段 | 加条目不带理由 ⇒ 红（否则「只读」不可复核） |
| 4 | `excluded` 里的 node id 也必须真实存在 | 同 1 | 写类用例改名 ⇒ 红 |
| 5 | P0 只读基线（`test_01_health` / `test_03_business`）不许被静默删条目 | profile ∪ excluded | 悄悄删条目 ⇒ 红 |
| 6 | **`--env prod` 不得出现在任何 `.github/workflows/**` 的 `schedule:` 里** | 静态扫 workflow 的 `on.schedule` + 脚本引用 | 有人把它挂上定时/部署腿 ⇒ 具名红 |
| 7 | 脚本契约：`bash -n` 通过；`--env prod` 缺凭据 ⇒ `rc=3` 且点名变量；假凭据 ⇒ `rc=1` 且**不泄漏密码** | 真跑脚本（缺凭据零网络；401 走本机 stub） | 缺 `rc=3` / 缺 `rc=1` / 回显密码 ⇒ 红 |

## 边界（照实登记，别读成已覆盖）

- **静态**：只看字面量路径（`"/api/admin/products"`）。拼接/运行时生成的路径**判不了** ⇒ 写动词的
  路径若是非字面量（f-string / 变量），一律**判红**（「判不了」不许当绿）。
- `--env prod` 的**执行时机**（「只在发版前一次」）判据只有两条：横幅在脚本输出里（可 grep）+ 不许挂
  schedule（判据 6）。**判不了**「人是否真的只在发版前跑」—— 登记为缺口，不假装覆盖。
- 本判据**不判断**某条用例是否**业务上**该进只读档（比如「对生产账号发错误验证码会累计风控计数」这类
  判断），那类排除理由写在 profile 的 `excluded[*].why` 里供人复核。
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_DIR = REPO_ROOT / "tests" / "smoke"
PROFILE = SMOKE_DIR / "prod_readonly_profile.json"
PROFILE_REL = "tests/smoke/prod_readonly_profile.json"
SCRIPT = REPO_ROOT / "scripts" / "smoke-prod-ai.sh"
SCRIPT_REL = "scripts/smoke-prod-ai.sh"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

NODE_PREFIX = "tests/smoke/"
AUTH_PREFIX = "/api/auth/"
WRITE_VERBS = {"post", "put", "delete", "patch"}

#: 判别力自证的**注入样本**：写类用例（POST /api/chat/sessions 建会话）。
WRITE_CASE = "tests/smoke/test_04_ai_chat.py::TestAIChatSSE::test_create_session"
#: P0 纯只读基线（不许被静默删条目）。
BASELINE_FILES = ("tests/smoke/test_01_health.py", "tests/smoke/test_03_business.py")
#: 生产闸门档的横幅（脚本里必须**逐字**存在，且只能在 prod 分支打印）。
PROD_BANNER = "⚠️ 本档只在「即将发生产」时跑一次；日常验证请在测试机跑 --env test"

BASH = shutil.which("bash")


# ── AST 小工具 ──────────────────────────────────────────────────────────────────
def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _test_functions(tree: ast.Module) -> dict[tuple[str | None, str], ast.AST]:
    """`{(类名或 None, 函数名): FunctionDef}`（只收 `test_*`）。"""
    found: dict[tuple[str | None, str], ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            found[(None, node.name)] = node
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    found[(node.name, sub.name)] = sub
    return found


def _fixture_functions(tree: ast.Module) -> dict[str, ast.AST]:
    """`{fixture 名: FunctionDef}`（`@pytest.fixture` / `@fixture` 都收）。"""
    found: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            name = getattr(target, "attr", None) or getattr(target, "id", None)
            if name == "fixture":
                found[node.name] = node
    return found


def _fixtures_for(test_path: Path) -> dict[str, ast.AST]:
    """conftest 的 fixture ⇄ 用例自己模块的 fixture（同名以**用例模块**为准，与 pytest 一致）。"""
    fixtures = dict(_fixture_functions(_tree(SMOKE_DIR / "conftest.py")))
    fixtures.update(_fixture_functions(_tree(test_path)))
    return fixtures


def _argument_names(function: ast.AST) -> list[str]:
    args = getattr(function, "args", None)
    if args is None:
        return []
    names = [arg.arg for arg in list(args.args) + list(args.kwonlyargs)]
    return [name for name in names if name not in ("self", "cls")]


def _dependency_chain(function: ast.AST, fixtures: dict[str, ast.AST], seen: set[int] | None = None) -> list[ast.AST]:
    """用例函数体 + 它（递归）依赖的 fixture 函数体。"""
    seen = seen if seen is not None else set()
    chain = [function]
    for name in _argument_names(function):
        fixture = fixtures.get(name)
        if fixture is None or id(fixture) in seen:
            continue
        seen.add(id(fixture))
        chain.extend(_dependency_chain(fixture, fixtures, seen))
    return chain


def _http_writes(function: ast.AST) -> list[tuple[str, str | None, int]]:
    """函数体里的 HTTP 写动词 ⇒ `[(动词, 字面量路径或 None, 行号)]`。"""
    calls: list[tuple[str, str | None, int]] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        verb: str | None = None
        path_node: ast.AST | None = None
        if isinstance(target, ast.Attribute) and target.attr in WRITE_VERBS:
            verb = target.attr.upper()
            path_node = node.args[0] if node.args else None
        elif isinstance(target, ast.Attribute) and target.attr == "request":
            first = node.args[0] if node.args else None
            if isinstance(first, ast.Constant) and str(first.value).upper() in {v.upper() for v in WRITE_VERBS}:
                verb = str(first.value).upper()
                path_node = node.args[1] if len(node.args) > 1 else None
        if verb is None:
            continue
        literal = path_node.value if isinstance(path_node, ast.Constant) and isinstance(path_node.value, str) else None
        calls.append((verb, literal, node.lineno))
    return calls


# ── profile 判据（纯函数：红证靠它，不说空话）──────────────────────────────────────
def check_profile(profile_path: Path = PROFILE) -> list[str]:
    """返回违规清单（`[]` = 绿）。每条都能单独变红，且**具名**（哪条 / 哪个动词 / 哪个路径）。"""
    problems: list[str] = []
    try:
        data = json.loads(Path(profile_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"{PROFILE_REL}: 读不了 / 不是合法 JSON（{exc}）"]

    entries = data.get("tests")
    if not isinstance(entries, list) or not entries:
        return [f"{PROFILE_REL}: 没有 tests 条目（空档 = 什么都没跑，不是绿）"]

    conftest_tree = _tree(SMOKE_DIR / "conftest.py")
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            problems.append(f"{PROFILE_REL}: 第 {index} 条不是对象: {entry!r}")
            continue
        node_id = str(entry.get("id", "")).strip()
        why = str(entry.get("why", "")).strip()
        if not node_id or not why:
            problems.append(f"{PROFILE_REL}: 第 {index} 条缺 `id` 或 `why`（每条都要一句「为什么只读」）: {entry!r}")
            continue
        if not node_id.startswith(NODE_PREFIX):
            problems.append(f"{node_id}: node id 必须写成 `{NODE_PREFIX}test_xx.py::…`（否则本判据解析不了文件）")
            continue

        file_rel, _, selector = node_id.partition("::")
        test_path = REPO_ROOT / file_rel
        if not test_path.is_file():
            problems.append(f"{node_id}: 文件不存在（{file_rel}）")
            continue
        parts = selector.split("::")
        key = (parts[0], parts[1]) if len(parts) == 2 else (None, parts[0])
        function = _test_functions(_tree(test_path)).get(key)
        if function is None:
            problems.append(
                f"{node_id}: `{file_rel}` 里没有这个测试函数 —— 改名/删除后这里必须红"
                f"（否则只读档会静默少跑）"
            )
            continue

        fixtures = dict(_fixture_functions(conftest_tree))
        fixtures.update(_fixture_functions(_tree(test_path)))
        for member in _dependency_chain(function, fixtures):
            for verb, literal, lineno in _http_writes(member):
                where = f"{node_id}（经由 {member.name}():{lineno}）"
                if literal is None:
                    problems.append(
                        f"{where} 的 {verb} 目标**不是字面量路径** ⇒ 判不了它是不是只读；"
                        f"改写成字面量路径，或移出只读档"
                    )
                elif literal.startswith(AUTH_PREFIX):
                    continue  # 登录 / 刷新这类 auth 面请求放行（不碰业务数据）
                else:
                    problems.append(f"{where} 对**非 auth 端点**发 {verb} {literal} ⇒ 写类用例不许进只读档")

    excluded = data.get("excluded")
    if not isinstance(excluded, list):
        problems.append(f"{PROFILE_REL}: 缺 `excluded` 清单（写类用例的排除理由要可供人复核）")
    else:
        for index, entry in enumerate(excluded, start=1):
            if not isinstance(entry, dict):
                problems.append(f"{PROFILE_REL}: excluded 第 {index} 条不是对象: {entry!r}")
                continue
            node_id = str(entry.get("id", "")).strip()
            why = str(entry.get("why", "")).strip()
            if not node_id or not why:
                problems.append(f"{PROFILE_REL}: excluded 第 {index} 条缺 `id` 或 `why`: {entry!r}")
                continue
            file_rel, _, selector = node_id.partition("::")
            test_path = REPO_ROOT / file_rel
            if not test_path.is_file():
                problems.append(f"{node_id}: excluded 条目指向的文件不存在（{file_rel}）")
                continue
            parts = selector.split("::")
            key = (parts[0], parts[1]) if len(parts) == 2 else (None, parts[0])
            if _test_functions(_tree(test_path)).get(key) is None:
                problems.append(f"{node_id}: excluded 条目在 `{file_rel}` 里不存在（改名后排除理由会失真）")
    return problems


def _profile_copy_with(tmp_path: Path, extra_ids: list[str], extra_excluded: list[str] | None = None) -> Path:
    data = json.loads(PROFILE.read_text(encoding="utf-8"))
    data["tests"] = list(data["tests"]) + [{"id": node, "why": "注入式红证样本"} for node in extra_ids]
    if extra_excluded:
        data["excluded"] = list(data["excluded"]) + [{"id": node, "why": "注入式红证样本"} for node in extra_excluded]
    copy = tmp_path / "profile_copy.json"
    copy.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return copy


# ── 判据 1~5：只读档本身 ──────────────────────────────────────────────────────────
def test_profile_is_read_only_and_every_node_id_exists():
    """正例：现行只读档**穿不过**任何一条判据（现状绿 ⇒ 有判别力，才谈得上守）。"""
    problems = check_profile()
    assert problems == [], "只读档违规：\n" + "\n".join(problems)


def test_injecting_a_write_case_turns_red(tmp_path):
    """判别力自证（塞入 ⇒ 必红）：`test_create_session` 的 POST /api/chat/sessions 要**点名**。

    复原 ⇒ 绿 = `test_profile_is_read_only_and_every_node_id_exists`（同一份实现、同一次跑）。
    """
    problems = check_profile(_profile_copy_with(tmp_path, [WRITE_CASE]))
    assert problems, "把写类用例塞进只读档却没判红 ⇒ 本判据没有判别力"
    joined = "\n".join(problems)
    assert "test_create_session" in joined, joined
    assert "/api/chat/sessions" in joined, joined


def test_renamed_node_id_turns_red(tmp_path):
    """改名/删函数后不许静默少跑：profile 引用的 node id 必须真实存在。"""
    problems = check_profile(_profile_copy_with(tmp_path, ["tests/smoke/test_03_business.py::TestProductAPI::test_no_such_case"]))
    assert problems, "node id 不存在却没判红 ⇒ 改名会静默少跑"
    assert "test_no_such_case" in "\n".join(problems)


def test_why_is_required(tmp_path):
    """每条都要一句「为什么只读」——否则「只读」不可复核。"""
    data = json.loads(PROFILE.read_text(encoding="utf-8"))
    data["tests"] = list(data["tests"]) + [{"id": "tests/smoke/test_01_health.py::TestHealthCheck::test_ai_agent_health"}]
    copy = tmp_path / "no_why.json"
    copy.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    problems = check_profile(copy)
    assert problems, "缺 why 却没判红"
    assert "why" in "\n".join(problems)


def test_baseline_read_only_cases_are_not_silently_dropped():
    """P0 只读基线（`test_01_health` / `test_03_business`）的每条都必须在 profile ∪ excluded 里被**点名**。

    否则「删一条条目」与「改名」看起来一样绿 —— 而生产只读档的价值就是这些条目的覆盖。
    """
    data = json.loads(PROFILE.read_text(encoding="utf-8"))
    declared = {str(entry.get("id", "")).strip() for entry in list(data.get("tests", [])) + list(data.get("excluded", []))}
    missing: list[str] = []
    for file_rel in BASELINE_FILES:
        tree = _tree(REPO_ROOT / file_rel)
        for (class_name, func_name) in _test_functions(tree):
            node_id = f"{file_rel}::{class_name}::{func_name}" if class_name else f"{file_rel}::{func_name}"
            if node_id not in declared:
                missing.append(node_id)
    assert not missing, "只读基线条目被静默丢掉（要么进 tests，要么进 excluded 并写理由）：\n" + "\n".join(missing)


# ── 判据 6：`--env prod` 不许挂 schedule（issue #9082 裁定第 4 条）──────────────────
def _has_schedule_trigger(workflow_path: Path) -> bool:
    """workflow 是否带 `schedule:` 触发（`on:`/`true:` 两种解析形态都认）。"""
    try:
        import yaml  # 局部导入：L0 只装 pytest+pyyaml，缺了就退回文本启发式
    except ImportError:  # pragma: no cover - CI 装了 pyyaml
        return any(line.lstrip().startswith("schedule:") for line in workflow_path.read_text(encoding="utf-8").splitlines())
    try:
        data = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return any(line.lstrip().startswith("schedule:") for line in workflow_path.read_text(encoding="utf-8").splitlines())
    if not isinstance(data, dict):
        return False
    for key in ("on", "true", True):  # PyYAML 把 `on` 解析成 True（YAML 1.1）
        trigger = data.get(key)
        if isinstance(trigger, dict) and "schedule" in trigger:
            return True
        if isinstance(trigger, list) and "schedule" in [str(item) for item in trigger]:
            return True
    return False


def test_prod_gate_is_not_on_any_schedule():
    """`--env prod` 只能由人（或发版流程）**显式**调用：任何带了 `schedule:` 的 workflow 都不许引用它。"""
    offenders: list[str] = []
    scanned = 0
    workflow_paths = sorted(WORKFLOWS_DIR.glob("*.y*ml"))
    assert workflow_paths, f"{WORKFLOWS_DIR} 下一个 workflow 都没有 ⇒ 本判据扫了空集（判不了，不许当绿）"
    for workflow_path in workflow_paths:
        scanned += 1
        text = workflow_path.read_text(encoding="utf-8")
        references_gate = SCRIPT_REL in text or f"{SCRIPT_REL} --env prod" in text or "--env prod" in text
        if references_gate and _has_schedule_trigger(workflow_path):
            offenders.append(f".github/workflows/{workflow_path.name}（带 schedule: 却引用了 {SCRIPT_REL} / --env prod）")
    assert scanned > 0
    assert not offenders, (
        "发版闸门档被挂到定时/无人值守触发上（它只能在发版前由人跑一次）：\n" + "\n".join(offenders)
    )


# ── 判据 7：脚本契约（真跑，零网络 / 本机 stub）────────────────────────────────────
def _clean_env(extra: dict[str, str]) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("MIGAO_SMOKE_")}
    env.pop("MIGAO_PROD_API_URL", None)
    env.pop("MIGAO_TEST_API_URL", None)
    env.pop("ADMIN_SMS_CODE", None)
    env.pop("ADMIN_PHONE", None)
    env.update(extra)
    return env


def _run_script(extra_env: dict[str, str], args: list[str] | None = None, timeout: int = 90) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BASH, str(SCRIPT), *(args if args is not None else ["--env", "prod"])],
        env=_clean_env(extra_env),
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(REPO_ROOT),
    )


class _LoginStub(BaseHTTPRequestHandler):
    """本机 401 stub：验证「登录失败 ⇒ rc=1 + 状态/文案」，**零外网、零生产流量**。"""

    def do_POST(self):  # noqa: N802 - http.server 约定
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        payload = '{"success": false, "message": "登录失败（账号或密码不对）"}'.encode("utf-8")
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # 静音
        return


@pytest.fixture()
def login_stub_url():
    server = HTTPServer(("127.0.0.1", 0), _LoginStub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.skipif(BASH is None, reason="没有 bash（脚本契约无从判）")
def test_script_syntax_passes():
    assert SCRIPT.is_file(), f"{SCRIPT_REL} 不存在"
    result = subprocess.run([BASH, "-n", str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert os.access(SCRIPT, os.X_OK), f"{SCRIPT_REL} 必须可执行（100755）"


@pytest.mark.skipif(BASH is None, reason="没有 bash")
def test_prod_without_credentials_exits_3_and_names_the_variables():
    """缺凭据 ⇒ rc=3（判不了），**点名**缺哪个变量，并指向「secret / 本机 export」出口。"""
    result = _run_script({})
    output = result.stdout + result.stderr
    assert result.returncode == 3, output
    assert "MIGAO_SMOKE_IDENTIFIER" in output, output
    assert "MIGAO_SMOKE_PASSWORD" in output, output
    assert "secret" in output, output
    assert "PROD-SMOKE rc=3" in output, output


@pytest.mark.skipif(BASH is None, reason="没有 bash")
def test_prod_login_failure_exits_1_and_never_leaks_password(login_stub_url):
    """假凭据 + 401 ⇒ rc=1；只打印 HTTP 状态与 message，**密码一次都不许出现**（也不许打印 token）。"""
    secret = "Pa55w0rd-MUST-NOT-BE-PRINTED-7f3a"
    result = _run_script(
        {
            "MIGAO_SMOKE_IDENTIFIER": "admin@migao",
            "MIGAO_SMOKE_PASSWORD": secret,
            "MIGAO_PROD_API_URL": login_stub_url,
        }
    )
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "401" in output, output
    assert "登录失败" in output, output
    assert "登录失败（账号或密码不对）" in output, output
    assert secret not in output, "密码被打印出来了（凭据泄漏）"
    assert "PROD-SMOKE rc=1" in output, output
    assert f"target=127.0.0.1:" in output, output


def test_script_uses_the_profile_as_the_single_source():
    """只读档是**单点来源**：脚本按它组参数，不许内联第二份清单，也不许内置任何默认凭据。"""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "prod_readonly_profile.json" in text, "脚本没有引用只读档 ⇒ 出现第二份清单（两份必然漂移）"
    # 只扫**可执行行**（注释里写「不跑 `-m p0`」是文档，不是运行指令）
    code_lines = [line.split("#", 1)[0] for line in text.splitlines() if not line.lstrip().startswith("#")]
    code = "\n".join(code_lines)
    assert "-m p0" not in code, "脚本里出现了 `-m p0` 整档：写类用例会跑进生产"
    for variable in ("MIGAO_SMOKE_IDENTIFIER", "MIGAO_SMOKE_PASSWORD"):
        assert variable in text, f"脚本没读 {variable}"
        # `${VAR:-}`（空默认）是 `set -u` 下的空值判断，不算默认值；**非空默认**才是内置凭据
        assert not re.search(r"\$\{" + variable + r":-[^}]+\}", text), (
            f"{variable} 有**非空默认值**：凭据绝不内置默认值（只许从环境变量 / secret 读）"
        )
    assert PROD_BANNER in text, "生产闸门档的醒目横幅被删了（它是「时机是判据」的唯一可 grep 证据）"
    assert '--env test' in text or "ENV_KIND=\"test\"" in text, "脚本没有测试机常态档"
