# case_ids: MC-196
"""就绪探针的**读超时**判据（issue #8647）—— 「端口有监听但僵而不死」必须判**未就绪**，不得抛异常。

## 病（2026-11-04 实测，可复算）

`./verify-all.sh agent` 在 **collection 阶段**中止：本机 `localhost:8001` 上有一个 5 天前的 uvicorn
（`/health` 还能回 200，其它路径**接受连接却不回包**）。判定模块只 catch 了「连接失败」与 401，
**没 catch 读超时** ⇒ 探针抛 `TimeoutError` ⇒ import 它的用例文件（模块级判定）在**收集阶段**
炸掉整档 —— 报表里既不是失败也不是未就绪，看起来像基础设施偶发，于是被 `-k` 排除掉
（= 给自己发豁免）。

## 四条判据（每条都能单独变红，双向）

| # | 注入 | 期望 | 红证（怎么让它红） |
|---|---|---|---|
| 1 | 接受连接但永不回包 | 返回未就绪文案（带端口 + 出口），**不抛异常** | 摘掉读超时那一段 catch ⇒ 抛 `TimeoutError` |
| 2 | 连接被拒（端口没人听） | 仍未就绪（既有行为不回归） | 摘掉连接段的 catch ⇒ 抛 `ConnectionRefusedError` |
| 3 | 401 | 按既有口径（未就绪、带 HTTP 码、点明凭据） | 删 401 分支 ⇒ 判成「就绪」 |
| 4 | 200 | 就绪（空串） | 让函数恒返回文案 ⇒ 本条红 |

## 两条**类级**守卫（让同类进不来）

- **传输层异常矩阵**（超时 / 连接重置 / 对端提前断开 / 非 HTTP 响应 / 读不全 / `URLError(超时)`）：
  逐条注入 ⇒ **一律未就绪，绝不落「就绪」**。本单的病就是「枚举漏了一个」。
- **结构守卫**：读响应段必须 catch **基类**（`OSError` / `http.client.HTTPException`）——
  把「逐个列举具体异常」换成「整族」；改窄成具体类型 ⇒ 当场红。

## 顺带（同族，错桶）

就绪探针**自身**崩了此前是 `exit 1`，而 `exit 1` 在 `verify-all.sh` 的三态里是「**有面未就绪**」
⇒ 「探针坏了」被静默读成「环境没准备好」。现钉成 `exit 2`（无法判定 ⇒ 上游记 ❌）。

## 边界（照实登记）

- 判据**不**探真服务（环境相关、CI 上服务不在跑）：真服务读数由 issue / PR body 的红证给出。
- 判据只判「探得通不通」，**不**判业务断言：探通之后用例照常跑、照常判红绿。
"""
from __future__ import annotations

import ast
import http.client
import http.server
import importlib.util
import shutil
import socket
import subprocess
import sys
import threading
import urllib.error
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE = REPO_ROOT / "backend" / "ai-agent-service"
READINESS = SERVICE / "tests" / "live_service_readiness.py"
PROBE = REPO_ROOT / "scripts" / "ai-agent-e2e-readiness.py"


def _load_readiness():
    """判定本体（stdlib-only ⇒ 本 job 不装 ai-agent 依赖也能真跑）。"""
    spec = importlib.util.spec_from_file_location(
        "_migao_live_service_readiness_timeout_under_test", READINESS
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _SilentListener:
    """「僵而不死」的最小复刻：**接受连接、永不回包**（进程还在，服务已不可用）。"""

    def __init__(self):
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self._sock.settimeout(0.2)
        self.port = self._sock.getsockname()[1]
        self.endpoint = f"http://127.0.0.1:{self.port}/api/chat/send"
        self._held = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._accept_forever, daemon=True)
        self._thread.start()

    def _accept_forever(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:  # accept 超时（0.2s）/ 套接字已关：都不是缺陷
                continue
            self._held.append(conn)  # 只持有、不读不写 ⇒ 对端 getresponse() 只能等到超时

    def close(self):
        self._stop.set()
        self._thread.join(timeout=5)
        for conn in self._held:
            conn.close()
        self._sock.close()


class _HttpStub:
    """最小 chat 端点桩：**固定**回一个状态码（真跑 HTTP，零 LLM、零外部依赖）。"""

    def __init__(self, status: int):
        stub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                payload = b'{"detail": "stub"}'
                self.send_response(stub.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                return

        self.status = status
        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.endpoint = f"http://127.0.0.1:{self.httpd.server_address[1]}/api/chat/send"
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._thread.join(timeout=5)


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# ── 判据 1：接受连接但不回包 ⇒ 未就绪（不抛异常）────────────────────────────

def test_read_timeout_is_reported_as_not_ready_and_never_raised():
    model = _load_readiness()
    silent = _SilentListener()
    try:
        reason = model.not_ready_reason(silent.endpoint, {"X-Service-Token": ""}, timeout=0.5)
    finally:
        silent.close()
    print(f"[判据 1·读超时] port={silent.port} ⇒ {reason!r}")
    bad = []
    if not isinstance(reason, str) or not reason:
        bad.append("返回值不是非空字符串 —— 必须落「未就绪」，不许是「就绪」（空串）")
    for needed in (str(silent.port), "读超时", "lsof"):
        if needed not in reason:
            bad.append(f"未就绪文案缺少可行动读数 {needed!r}")
    if "未在" in reason:
        bad.append("把「有监听但读超时」误判成「服务没在跑」（两者的出口不同）")
    assert bad == []


# ── 判据 2：连接被拒 ⇒ 仍未就绪（既有行为不回归）──────────────────────────

def test_connection_refused_is_still_not_ready():
    model = _load_readiness()
    port = _closed_port()
    reason = model.not_ready_reason(f"http://127.0.0.1:{port}/api/chat/send", {}, timeout=0.5)
    print(f"[判据 2·连接被拒] port={port} ⇒ {reason!r}")
    bad = []
    if not reason:
        bad.append("连接被拒必须判未就绪（既有行为不许回归）")
    if "运行" not in reason:
        bad.append("既有文案应说明「服务未在运行」")
    assert bad == []


# ── 判据 3：401 ⇒ 按既有口径（服务活着、只是要鉴权）────────────────────────

def test_401_keeps_the_existing_verdict():
    model = _load_readiness()
    stub = _HttpStub(401)
    try:
        reason = model.not_ready_reason(stub.endpoint, {"X-Service-Token": "stub"}, timeout=3)
    finally:
        stub.close()
    print(f"[判据 3·401] ⇒ {reason!r}")
    bad = []
    if "401" not in reason:
        bad.append("401 必须落既有「凭据不被接受」口径并带上 HTTP 码")
    if "凭据" not in reason:
        bad.append("401 文案必须点明是凭据不一致（服务是活着的）")
    if "读超时" in reason:
        bad.append("401 不许被并进「读超时」口径 —— 它证明服务在回包")
    assert bad == []


# ── 判据 4：200 ⇒ 就绪 ────────────────────────────────────────────────────

def test_200_is_ready():
    model = _load_readiness()
    stub = _HttpStub(200)
    try:
        reason = model.not_ready_reason(stub.endpoint, {}, timeout=3)
    finally:
        stub.close()
    print(f"[判据 4·200] ⇒ {reason!r}")
    assert reason == "", f"HTTP 200 必须判**就绪**（返回空串），实测 {reason!r}"


# ── 类级守卫 A：传输层异常**整族**都不许上抛、也不许被读成「就绪」──────────

_RAISERS = (
    ("TimeoutError", lambda: TimeoutError("timed out")),
    ("socket.timeout", lambda: socket.timeout("timed out")),
    ("ConnectionResetError", lambda: ConnectionResetError(54, "Connection reset by peer")),
    ("BrokenPipeError", lambda: BrokenPipeError(32, "Broken pipe")),
    (
        "http.client.RemoteDisconnected",
        lambda: http.client.RemoteDisconnected("Remote end closed connection without response"),
    ),
    ("http.client.BadStatusLine", lambda: http.client.BadStatusLine("not-http")),
    ("http.client.IncompleteRead", lambda: http.client.IncompleteRead(b"partial", 64)),
    ("urllib.error.URLError(timeout)", lambda: urllib.error.URLError(TimeoutError("timed out"))),
    ("urllib.error.URLError(other)", lambda: urllib.error.URLError(OSError("boom"))),
)


@pytest.mark.parametrize("label, raiser", _RAISERS, ids=[name for name, _ in _RAISERS])
def test_every_transport_failure_lands_in_not_ready_never_in_ready(monkeypatch, label, raiser):
    """本单的病 = 「枚举漏了一个异常类型」。这里把整族逐条注入，缺一条就红。"""
    model = _load_readiness()
    silent = _SilentListener()  # 只用来让「连接阶段」过关，真正的注入在下面
    try:
        def _boom(*args, **kwargs):
            raise raiser()

        monkeypatch.setattr(model.request, "urlopen", _boom)
        reason = model.not_ready_reason(silent.endpoint, {}, timeout=0.2)
    finally:
        silent.close()
    print(f"[类级 A·{label}] ⇒ {reason!r}")
    bad = []
    if not isinstance(reason, str) or not reason:
        bad.append(f"{label}: 必须落「未就绪」（非空文案），实测 {reason!r}（空串 = 被读成「就绪」）")
    assert bad == []


# ── 类级守卫 B：读响应段必须 catch **基类**（改窄成具体类型即红）───────────

def test_read_phase_catches_transport_exceptions_as_a_family():
    tree = ast.parse(READINESS.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "not_ready_reason"
    )
    handled = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.ExceptHandler) or node.type is None:
            continue
        members = node.type.elts if isinstance(node.type, ast.Tuple) else [node.type]
        for member in members:
            handled.add(ast.unparse(member))
    print(f"[类级 B·结构] not_ready_reason 的 except 类型集合：{sorted(handled)}")
    missing = [name for name in ("OSError", "http.client.HTTPException") if name not in handled]
    assert missing == [], (
        "读响应段没有 catch 这些**基类** ⇒ 它们的子类（读超时只是其中一例）仍会上抛，"
        f"并在收集阶段打挂整档：{missing}"
    )


# ── 顺带：探针**自身**崩了 ⇒ 无法判定（exit 2），不许折成「未就绪」（exit 1）──

def test_readiness_probe_reports_undecidable_when_itself_crashes(tmp_path):
    service = tmp_path / "svc"
    tests = service / "tests"
    tests.mkdir(parents=True)
    shutil.copy(READINESS, tests / "live_service_readiness.py")
    # 语法错的文件 ⇒ 现取面清单时的 ast 解析崩溃（真实可达：测试树里任何一个坏文件）
    (tests / "test_broken.py").write_text("def broken(:\n", encoding="utf-8")
    reading = subprocess.run(
        [sys.executable, str(PROBE), "--service-dir", str(service)],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    print(f"[顺带·探针自崩] exit {reading.returncode}：{reading.stdout.strip()}{reading.stderr.strip()}")
    bad = []
    if reading.returncode != 2:
        bad.append(
            f"探针崩溃必须落「无法判定」exit 2，实测 exit {reading.returncode}"
            "（exit 1 会被上游读成「有面未就绪」= 错桶）"
        )
    if "无法判定" not in reading.stdout:
        bad.append("崩溃读数里必须明写「无法判定」+ 异常类型，而不是只丢一坨 traceback")
    assert bad == []
