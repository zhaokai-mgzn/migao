# case_ids: MC-344
"""冒烟登录「一次登录」契约（issue #8977）：短信验证码**单次消费** ⇒ 整档只许登录一次。

## 病（2026-11-21 生产实测，issue #8977）

`SMOKE_ENV=production pytest -m p0`（生产未配 `SMS_BYPASS_CODE`）整跑 ⇒ `1 failed, 10 passed, 10 errors`：

- `tests/smoke/test_02_auth.py::TestAuthLogin::test_login_success` **自己**发一次
  `POST /api/auth/sms/login`（用掉那条短信码）；
- 随后 session 级 fixture `auth_token` 用**同一个码**再发一次 ⇒ 401（码已消费）⇒ 依赖它的 10 条全 ERROR。

现行规避是手工 `--deselect test_login_success` —— **不可接受**：冒烟套件不能作为一个整体跑。

## 判据（每条都能单独变红；零网络、零真短信、零 LLM）

| # | 判什么 | 取法 | 回归时会怎么红 |
|---|---|---|---|
| 1 | **注入 token ⇒ 不发起登录请求**（`SMOKE_ADMIN_TOKEN` 非空时直接用，不发码） | 真调 `conftest.py::auth_token`，transport 换成记录器 | 分支被摘掉 / 仍发码 ⇒ 记录到 `POST /api/auth/sms/login` ⇒ 具名红 |
| 2 | **未注入 ⇒ 仍登录一次**（不许「为了绿而永远不登录」） | 同上，env 清空 | 0 次 ⇒ 红；≥2 次（又回到抢码形态）⇒ 红 |
| 3 | **`test_login_success` 复用 fixture 的同一次登录**（不再单独消费第二个码） | 真调用例 + AST 取签名/源码 | 用例再发登录 / 保留 `admin_client`/`config` 入参 ⇒ 红 |
| 4 | **P0 面上不许有「有效码消费者」**（类级元守卫：新增即红） | AST 扫 `tests/smoke/test_*.py`：函数体调登录接口**且**引用 `admin_sms_code` | 新增任意一条「自己用有效码登录」的 P0 用例 ⇒ 具名红 |
| 5 | **P0 之外的有效码消费者必须登记**（台账只许缩短：未登记即红、多登记也红） | 台账 `smoke_login_consumers.json` ⇄ 判据 4 的同一扫法 | 加/删消费者而不动台账 ⇒ 红 |
| 6 | **注入 token 模式下 refresh 用例是「不可判定」而不是假绿/假红** | 真调 `TestTokenRefresh::test_refresh_token` | 无条件跑（无 cookie ⇒ 假红）/ 无条件 skip（真登录也不覆盖）⇒ 红 |
| 7 | **fixture 不许靠 `SMS_BYPASS_CODE` 弱化登录**（issue #8977 的「禁止修法」） | conftest 源码面 | 出现 bypass 开关 ⇒ 红 |

## 边界（照实登记，别读成已覆盖）

- **不发真短信、不连生产**：判据钉的是「一次登录」的**行为契约**（桩化 transport），
  真机真短信的一次整跑仍须在部署机执行（命令与读数口径见 `tests/smoke/README.md`）；
- 判据 4/5 的扫法是**静态 + 名字无关**：只看「登录接口字面量 + `admin_sms_code` 引用」，
  判不了运行时拼出来的路径（登记为缺口，不假装覆盖）。
"""
from __future__ import annotations

import ast
import importlib.machinery
import importlib.util
import inspect
import json
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_DIR = REPO_ROOT / "tests" / "smoke"
CONFTEST_REL = "tests/smoke/conftest.py"
AUTH_TEST_REL = "tests/smoke/test_02_auth.py"
LOGIN_PATH = "/api/auth/sms/login"
TOKEN_ENV = "SMOKE_ADMIN_TOKEN"
LEDGER_PATH = Path(__file__).resolve().parent / "smoke_login_consumers.json"

#: 加载 `tests/smoke/*` 的**合成包名**：不 `import tests.smoke.*`（整目录收集时 `tests`
#: 这个包名会被别的判据抢先绑定到 `backend/ai-agent-service/tests` 之类的位置 ⇒ 见
#: `test_smoke_transient_retry.py::_retry_policy` 的实测）。
_PKG = "migao_smoke_one_login_uut"

ACCESS_TOKEN = "eyJhbGciOiJIUzI1NiJ9.injected.smoke.token"
REFRESH_COOKIE = "refresh_token=rt-from-login; Path=/; HttpOnly; Secure; SameSite=Strict"


def _install_httpx_stub():
    """本文件**自己**装 httpx 替身（不借别的判据的注入；L0 CI 只装 pytest+pyyaml）。

    只用到 import 期的 `Response` 名字（`helpers.py` 的注解）—— 本文件从不真实发起 HTTP：
    transport 一律是下面的 `_RecordingClient` 记录器。
    """
    stub = types.ModuleType("httpx")

    class _Client:  # pragma: no cover - 构造即失败：本文件不得真实发起 HTTP
        def __init__(self, *args, **kwargs):
            raise AssertionError("httpx 替身：本判据不得真实发起 HTTP")

    class Response:
        """`helpers.py` 的类型注解只需要这个名字存在（本文件从不构造真实响应）。"""

    stub.Client = _Client
    stub.Response = Response
    sys.modules.setdefault("httpx", stub)


def _load_smoke_module(stem: str):
    """按文件路径把 `tests/smoke/<stem>.py` 装进**合成包**（相对 import 才能解析）。"""
    _install_httpx_stub()
    if _PKG not in sys.modules:
        pkg_spec = importlib.machinery.ModuleSpec(_PKG, loader=None, is_package=True)
        pkg_spec.submodule_search_locations = [str(SMOKE_DIR)]
        sys.modules[_PKG] = importlib.util.module_from_spec(pkg_spec)
    name = f"{_PKG}.{stem}"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SMOKE_DIR / f"{stem}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _conftest():
    return _load_smoke_module("conftest")


def _auth_module():
    return _load_smoke_module("test_02_auth")


def _config():
    """fixture 只读 `admin_phone` / `admin_sms_code` 两个字段（用最小替身，不连任何环境）。"""
    return types.SimpleNamespace(admin_phone="13900001025", admin_sms_code="123456")


class _FakeResp:
    """登录响应替身：字段面按 `SmokeTestClient.post` 的消费点给足。"""

    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.text = json.dumps(self._payload, ensure_ascii=False)

    def json(self):
        return self._payload


class _RecordingClient:
    """**桩化 transport**：记录每一条请求与 `set_token`，零网络。"""

    def __init__(self, response=None):
        self.requests = []
        self.tokens = []
        self._response = response or _FakeResp(payload={"data": {
            "accessToken": "eyJhbGciOiJIUzI1NiJ9.from-login",
            "refreshToken": None,
        }}, headers={"set-cookie": REFRESH_COOKIE})

    def post(self, path, **kwargs):
        self.requests.append({"path": path, **kwargs})
        return self._response

    def set_token(self, access_token, refresh_token=None):
        self.tokens.append((access_token, refresh_token))

    def paths(self):
        return [r["path"] for r in self.requests]


def _login_calls(client):
    return [r for r in client.requests if r["path"] == LOGIN_PATH]


def _auth_token_fixture():
    fixture = getattr(_conftest(), "auth_token", None)
    wrapped = getattr(fixture, "__wrapped__", None)
    if wrapped is None:
        pytest.fail("conftest.auth_token 不是 pytest.fixture（取不到 __wrapped__）⇒ 本判据无从判定")
    return wrapped


# ═══════════════════════════════════════════════════════════════════════════
# ① 注入 token ⇒ 不发登录请求
# ═══════════════════════════════════════════════════════════════════════════
def test_injected_token_never_posts_sms_login(monkeypatch):
    """`SMOKE_ADMIN_TOKEN` 非空 ⇒ 直接用它：**一条登录请求都不发**（不消耗短信码）。"""
    monkeypatch.setenv(TOKEN_ENV, ACCESS_TOKEN)
    client = _RecordingClient()

    payload = _auth_token_fixture()(client, _config())

    assert client.paths() == [], (
        "设置了 SMOKE_ADMIN_TOKEN 却仍发起请求 ⇒ 生产复跑又要发一条短信码（issue #8977 未修）："
        f" {client.paths()}"
    )
    assert LOGIN_PATH not in client.paths(), f"注入 token 模式仍打了登录接口：{client.paths()}"
    assert payload["access_token"] == ACCESS_TOKEN, "注入的 token 没有被采用"
    assert payload["login_response"] is None, "注入模式没有发生登录 ⇒ 不应伪造登录响应"
    assert client.tokens == [(ACCESS_TOKEN, None)], (
        f"注入模式没有把注入 token 装进 client（实际 set_token 调用：{client.tokens}）"
    )


# ═══════════════════════════════════════════════════════════════════════════
# ② 未注入 ⇒ 仍登录**一次**（防止「为了绿而永远不登录」）
# ═══════════════════════════════════════════════════════════════════════════
def test_without_injected_token_logs_in_exactly_once(monkeypatch):
    """未设 `SMOKE_ADMIN_TOKEN` ⇒ 保持原逻辑：发码登录**恰好一次**（session 级复用）。"""
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    config = _config()
    client = _RecordingClient()

    payload = _auth_token_fixture()(client, config)

    logins = _login_calls(client)
    assert len(logins) == 1, (
        f"未注入 token 时应恰好登录一次（fixture 独占那条码），实际 {len(logins)} 次：{client.paths()}"
    )
    assert logins[0]["json"] == {"phone": config.admin_phone, "code": config.admin_sms_code}, (
        f"登录请求体不是「配置里的手机号 + 短信码」：{logins[0].get('json')}"
    )
    assert payload["access_token"].startswith("eyJ"), "登录成功却没有取到 JWT access token"
    assert payload["login_response"] is not None, "登录发生后应把登录响应交给用例复用（判据 ③）"
    assert client.tokens == [("eyJhbGciOiJIUzI1NiJ9.from-login", "")], (
        f"登录成功后没有把 token 装进 client（实际：{client.tokens}）"
    )


# ═══════════════════════════════════════════════════════════════════════════
# ③ test_login_success 复用 fixture 的同一次登录（不再消费第二个码）
# ═══════════════════════════════════════════════════════════════════════════
def test_login_success_reuses_fixture_login(monkeypatch):
    """先由 fixture 登录一次，再把同一结果交给 `test_login_success` ⇒ 总登录数仍为 1。"""
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    client = _RecordingClient()
    payload = _auth_token_fixture()(client, _config())
    assert len(_login_calls(client)) == 1, "前置不成立：fixture 没有登录"

    _auth_module().TestAuthLogin().test_login_success(payload)

    assert len(_login_calls(client)) == 1, (
        "test_login_success 又自己发了一次登录 ⇒ 生产上第二条码必 401（issue #8977 原形）："
        f" {client.paths()}"
    )

    # 注入模式：用例同样不得发码，且仍能校验注入凭据的形态
    monkeypatch.setenv(TOKEN_ENV, ACCESS_TOKEN)
    injected_client = _RecordingClient()
    injected = _auth_token_fixture()(injected_client, _config())
    _auth_module().TestAuthLogin().test_login_success(injected)
    assert injected_client.paths() == [], f"注入模式下 test_login_success 仍在发请求：{injected_client.paths()}"


def test_login_success_has_no_own_login_call():
    """静态面：`test_login_success` 不许再持有登录调用/登录所需入参（名字无关）。"""
    text = (REPO_ROOT / AUTH_TEST_REL).read_text(encoding="utf-8")
    tree = ast.parse(text)
    fn = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "TestAuthLogin":
            fn = next((n for n in node.body
                       if isinstance(n, ast.FunctionDef) and n.name == "test_login_success"), None)
    if not isinstance(fn, ast.FunctionDef):
        pytest.fail(f"{AUTH_TEST_REL} 里找不到 TestAuthLogin::test_login_success（判据无对象 ⇒ 大声失败）")

    params = [a.arg for a in fn.args.args]
    assert "auth_token" in params, f"test_login_success 没有复用 auth_token fixture，入参={params}"
    assert "admin_client" not in params and "config" not in params, (
        f"test_login_success 仍持有登录所需入参（会自己发第二个码），入参={params}"
    )
    segment = ast.get_source_segment(text, fn) or ""
    assert LOGIN_PATH not in segment, (
        f"test_login_success 的函数体里仍有 {LOGIN_PATH} 字面量 ⇒ 它又在自己消费一条码"
    )


# ═══════════════════════════════════════════════════════════════════════════
# ④ / ⑤ 类级元守卫：P0 面不许有「有效码消费者」；P0 之外必须登记
# ═══════════════════════════════════════════════════════════════════════════
def _marked(node, name: str) -> bool:
    return any(f"mark.{name}" in ast.unparse(dec) for dec in getattr(node, "decorator_list", []))


def _valid_code_consumers() -> dict[str, dict]:
    """扫 `tests/smoke/test_*.py`：函数体调登录接口**且**引用 `admin_sms_code` = 有效码消费者。

    取「最外层测试函数/类方法」整段源码（含内嵌 helper），所以 `def do_login(): …` 这类
    被包在用例里的写法也会归到该用例名下（不会漏、也不会错记到 helper）。
    """
    found: dict[str, dict] = {}
    for path in sorted(SMOKE_DIR.glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for top in tree.body:
            if isinstance(top, ast.ClassDef):
                owners = [(n, top) for n in top.body if isinstance(n, ast.FunctionDef)]
            elif isinstance(top, ast.FunctionDef):
                owners = [(top, None)]
            else:
                continue
            for fn, cls in owners:
                segment = ast.get_source_segment(text, fn) or ""
                if LOGIN_PATH not in segment or "admin_sms_code" not in segment:
                    continue
                rel = f"{path.relative_to(REPO_ROOT).as_posix()}::{fn.name}"
                found[rel] = {
                    "p0": _marked(fn, "p0") or (cls is not None and _marked(cls, "p0")),
                }
    return found


def test_p0_has_no_valid_code_consumer_outside_fixture():
    """**P0** 档里除 `conftest.auth_token` 外，任何用例都不许拿有效短信码自己登录（新增即红）。"""
    p0 = {name: meta for name, meta in _valid_code_consumers().items() if meta["p0"]}
    assert p0 == {}, (
        "P0 冒烟里出现了「自己用有效短信码登录」的用例 ⇒ 它会先消费掉那条单次码，"
        "session fixture 再登录必 401，整档 10 条 ERROR（issue #8977 原形）。\n"
        f"  违规用例：{sorted(p0)}\n"
        "  修法：改成接收 `auth_token` fixture（复用同一次登录），负路径用**无效码/空 body**。"
    )


def test_valid_code_consumer_ledger_is_exact():
    """P0 之外的有效码消费者必须逐条登记（未登记即红、台账多登记也要删 —— 只许缩短）。"""
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    entries = ledger.get("allowed") or []
    assert entries, f"{LEDGER_PATH.name} 里 allowed 为空 ⇒ 本判据会恒绿（空断言）"
    for entry in entries:
        assert entry.get("test") and entry.get("why"), f"台账条目缺 test/why：{entry}"

    registered = {e["test"] for e in entries}
    observed = set(_valid_code_consumers())
    assert observed == registered, (
        "有效短信码消费者与台账不一致：\n"
        f"  未登记（新增消费者必须先证明不破坏「一次登录」）：{sorted(observed - registered)}\n"
        f"  台账多登记（已不是消费者 ⇒ 按「只许缩短」删掉）：{sorted(registered - observed)}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# ⑥ 注入模式下 refresh 用例 = 不可判定（显式 skip，且只在这一个条件下）
# ═══════════════════════════════════════════════════════════════════════════
def test_refresh_skips_only_in_injected_token_mode(monkeypatch):
    """注入 token 没有 refresh cookie ⇒ refresh 用例必须显式 skip（不是假红、也不是无条件不覆盖）。"""
    monkeypatch.setenv(TOKEN_ENV, ACCESS_TOKEN)
    client = _RecordingClient()
    payload = _auth_token_fixture()(client, _config())

    with pytest.raises(pytest.skip.Exception):
        _auth_module().TestTokenRefresh().test_refresh_token(client, payload)
    assert client.requests == [], f"注入模式下 refresh 用例在执行 skip 前就发了请求：{client.paths()}"

    text = (REPO_ROOT / AUTH_TEST_REL).read_text(encoding="utf-8")
    assert text.count("pytest.skip(") == 1, (
        f"{AUTH_TEST_REL} 里的 skip 只能有「注入 token ⇒ refresh 不可判定」这一处"
    )
    assert "login_response" in text, (
        "refresh 的 skip 必须以「本轮有没有发生登录」（login_response）为条件 —— "
        "否则真登录的跑法里 refresh 也不再被覆盖"
    )


# ═══════════════════════════════════════════════════════════════════════════
# ⑦ fixture 不许用 bypass 码弱化登录（issue #8977 的「禁止修法」）
# ═══════════════════════════════════════════════════════════════════════════
def _read_env_names(tree) -> set[str]:
    """conftest 里真正被**读**的环境变量名（`os.getenv("X")` / `os.environ.get("X")`）。

    也解析「先定义模块常量、再 `os.getenv(常量)`」的形态（fixture 就是这么写的）。
    """
    consts = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name) and isinstance(node.value.value, str):
                    consts[target.id] = node.value.value
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        fn = node.func
        fname = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        if fname not in ("getenv", "get"):
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant):
            names.add(str(arg.value))
        elif isinstance(arg, ast.Name) and arg.id in consts:
            names.add(consts[arg.id])
    return names


def test_fixture_does_not_introduce_sms_bypass():
    """生产不许配 `SMS_BYPASS_CODE`（= 弱化登录）；fixture 也不许自己长一个 bypass 开关。"""
    tree = ast.parse((REPO_ROOT / CONFTEST_REL).read_text(encoding="utf-8"))
    read_names = _read_env_names(tree)
    bypass = sorted(n for n in read_names if "BYPASS" in n.upper())
    assert bypass == [], (
        f"{CONFTEST_REL} 读了 bypass 环境变量 {bypass} —— 生产弱化登录不是本单的修法"
        "（issue #8977 建议 ③ 已否决）"
    )
    assert TOKEN_ENV in read_names, (
        f"{CONFTEST_REL} 没有读 {TOKEN_ENV} ⇒ 注入 token 分支被摘掉/改名，判据 ① 会失去对象"
    )
