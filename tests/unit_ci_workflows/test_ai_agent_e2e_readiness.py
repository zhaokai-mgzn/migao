# case_ids: MC-012
"""`ai-agent e2e 前置就绪`（issue #6160）的判据：**探针本体 / 按现取 / 接线**。

## 病灶（2026-10-03 实测，集成方单变量已闭环）

`./verify-all.sh full` 把「服务在跑、但**鉴权不过**」报成 `ai-agent 全量` **失败**：
`tests/test_e2e_mibao_scenarios.py` **20 failed / 2.79s**，逐字
`AssertionError: chat 接口返回非 200：401, detail={"code":"AUTH_REQUIRED"}`；
同一读数**在主检出上逐字复现** ⇒ 不是代码回归，是本地环境红。而 `verify-all.sh` 早有
「未就绪（既不是通过也不是失败）」这一档，只是**覆盖不到**「服务在跑但凭据不被接受」。

## 三条判据（都会红）

1. **探针本体的判别力**（真跑 HTTP，本地桩，零 LLM）：凭据被接受（422 —— 鉴权先于请求体
   校验的**实测**形态）⇒ 就绪；401 ⇒ 未就绪且带读数；端口没人听 ⇒ 未就绪。
2. **按现取**：面清单来自 ai-agent 的 tests 树 + `pytest.ini` 的 `--ignore=`，契约由 `ast`
   现取（**不执行**模块代码、不需要 venv）—— 面清单为空 / 契约不是可解析字面量 ⇒ 退出码 2
   （**判不了 ≠ 就绪**：这种绿正是本单要消灭的形态）。
3. **接线**：`verify-all.sh` 的 quick / full / agent 各有一条 `report_env ai-agent-e2e`，
   `probe_ready()` 有该 key 的分支；行为面用假 ROOT + 桩探针演练**三态**
   （exit 1 ⇒ 未就绪 / READY=1 / FAIL=0；exit 0 ⇒ ✅；exit 2 ⇒ ❌「脚本配置错误」）。

## 边界（照实登记）

- 本判据**不**去探真服务（环境相关、且 CI 上服务不在跑）：真服务的读数由 PR body 的红证给出。
- 「**真失败仍红**」（夹住：探针通过之后判据照旧能红）由用例面自己的断言 + 上面的探针分类
  保证：探针只看「探得通不通」，**不看任何业务断言**（`not_ready_reason` 里没有业务分支）。
"""
from __future__ import annotations

import http.server
import importlib.util
import re
import shlex
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROBE = REPO_ROOT / "scripts" / "ai-agent-e2e-readiness.py"
SERVICE = REPO_ROOT / "backend" / "ai-agent-service"
READINESS = SERVICE / "tests" / "live_service_readiness.py"
FACE = SERVICE / "tests" / "test_e2e_mibao_scenarios.py"
SCRIPT = REPO_ROOT / "verify-all.sh"


def _load_readiness():
    """判定本体（stdlib-only ⇒ 本 job 不装 ai-agent 依赖也能真跑）。"""
    spec = importlib.util.spec_from_file_location("_migao_live_service_readiness_under_test", READINESS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class StubChatService:
    """chat 端点桩：凭据不匹配 ⇒ 401；匹配 ⇒ 422（**实测**形态：鉴权先于请求体校验）。"""

    def __init__(self, token: str = "good-token"):
        stub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                status = 422 if self.headers.get("X-Service-Token") == stub.token else 401
                payload = b'{"detail": "stub"}'
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                return

        self.token = token
        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.endpoint = f"http://127.0.0.1:{self.httpd.server_address[1]}/api/chat/send"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


# ── 判据 1：探针本体的判别力（真跑 HTTP，零 LLM）─────────────────────────────

def test_probe_judges_ready_rejected_and_unreachable():
    readiness = _load_readiness()
    stub = StubChatService()
    try:
        ready = readiness.not_ready_reason(stub.endpoint, {"X-Service-Token": stub.token})
        rejected = readiness.not_ready_reason(stub.endpoint, {"X-Service-Token": "wrong-token"})
    finally:
        stub.close()
    unreachable = readiness.not_ready_reason(
        f"http://127.0.0.1:{_closed_port()}/api/chat/send", {}
    )
    print(f"[探针] 凭据被接受 ⇒ {ready!r}\n[探针] 凭据被拒 ⇒ {rejected!r}\n[探针] 连不上 ⇒ {unreachable!r}")
    assert ready == "", "凭据被接受（桩回 422）时必须判**就绪** —— 「判不了」不得等于「未就绪」"
    assert "401" in rejected and "凭据" in rejected, "凭据被拒必须判未就绪，且读数里带上 HTTP 码"
    assert unreachable and "运行" in unreachable, "服务不在跑必须判未就绪"


# ── 判据 2：按现取（面清单 / 契约 / 三态出口）────────────────────────────────

def _fake_service(
    root: Path,
    *,
    token: str,
    endpoint: str,
    under_ignore: bool = False,
    declare: bool = True,
    literal: bool = True,
) -> Path:
    """造一个最小 ai-agent-service 树：契约模块 + `pytest.ini`(--ignore) + 一个面模块。"""
    tests = root / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    shutil.copy(READINESS, tests / "live_service_readiness.py")
    (root / "pytest.ini").write_text("[pytest]\naddopts = --ignore=tests/hidden/\n", encoding="utf-8")
    if not declare:
        return root
    where = tests / "hidden" if under_ignore else tests
    where.mkdir(parents=True, exist_ok=True)
    if literal:
        source = (
            "LIVE_SERVICE_PROBE = {\n"
            f"    'endpoint': {endpoint!r},\n"
            f"    'headers': {{'X-Service-Token': {token!r}}},\n"
            "}\n"
        )
    else:
        source = "LIVE_SERVICE_PROBE = {'endpoint': ANOTHER_NAME, 'headers': {}}\n"
    (where / "test_face.py").write_text(source, encoding="utf-8")
    return root


def _run_probe(service_dir: Path):
    return subprocess.run(
        [sys.executable, str(PROBE), "--service-dir", str(service_dir)],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )


def test_probe_cli_reads_faces_from_source_and_maps_three_states(tmp_path):
    stub = StubChatService()
    try:
        good = _run_probe(_fake_service(tmp_path / "good", token=stub.token, endpoint=stub.endpoint))
        bad = _run_probe(_fake_service(tmp_path / "bad", token="wrong-token", endpoint=stub.endpoint))
    finally:
        stub.close()
    dead = "http://127.0.0.1:1/api/chat/send"
    hidden = _run_probe(_fake_service(tmp_path / "hidden", token="x", endpoint=dead, under_ignore=True))
    absent = _run_probe(_fake_service(tmp_path / "absent", token="x", endpoint=dead, declare=False))
    broken = _run_probe(_fake_service(tmp_path / "broken", token="x", endpoint=dead, literal=False))
    for name, reading in (("就绪", good), ("凭据被拒", bad), ("被 ignore", hidden), ("无面", absent), ("契约非字面量", broken)):
        print(f"[现取] {name} ⇒ exit {reading.returncode}：{reading.stdout.strip()}{reading.stderr.strip()}")
    assert good.returncode == 0, "凭据被接受的面必须判就绪（exit 0）"
    assert bad.returncode == 1 and "401" in bad.stdout, "凭据被拒的面必须判未就绪（exit 1）并带上读数"
    assert hidden.returncode == 2, (
        "被 pytest.ini --ignore 的面根本不收集 ⇒ 不该被探；此时面清单为空 ⇒ **判不了**（exit 2），不是「就绪」"
    )
    assert absent.returncode == 2, "没有声明契约的面 ⇒ 判不了（exit 2）"
    assert broken.returncode == 2, "契约不是可解析字面量 ⇒ 判不了（exit 2）"


def test_real_face_is_discovered_and_its_contract_is_readable():
    """真实服务目录：face 必须被扫到、契约必须可现取（exit 2 = 判不了 ⇒ 红）。"""
    reading = subprocess.run([sys.executable, str(PROBE)], capture_output=True, text=True, cwd=REPO_ROOT)
    print(f"[现取·真] exit {reading.returncode}：{reading.stdout.strip()}{reading.stderr.strip()}")
    assert reading.returncode in (0, 1), (
        "探针在真实服务目录上判「无法判定」—— 面清单为空 / 契约不可解析 ⇒ 门禁的「未就绪」"
        "与用例的 skip 会各说各话"
    )
    assert "test_e2e_mibao_scenarios.py" in reading.stdout, "探到的面里没有黄金策 e2e 面"


def test_face_uses_the_shared_judgement_and_declares_the_contract():
    """接线锚（§28.2）：用例面必须用**同一个**判定函数、并声明可现取的契约。"""
    source = FACE.read_text(encoding="utf-8")
    assert "from tests.live_service_readiness import not_ready_reason" in source
    assert "not_ready_reason(CHAT_ENDPOINT, HEADERS)" in source
    assert "LIVE_SERVICE_PROBE = {" in source


# ── 判据 3：接线（三档派发 + 三态行为）──────────────────────────────────────

def _extract(name: str) -> str:
    """从脚本里抽出 `name() { ... }`（结束于第 0 列的 `}`）。"""
    match = re.search(rf"^{name}\(\) \{{[\s\S]*?^\}}", SCRIPT.read_text(encoding="utf-8"), re.M)
    assert match, f"未能从 verify-all.sh 抽出 {name}() —— 结构变了就同步更新本判据"
    return match.group(0)


def _mode_branch(mode: str) -> str:
    lines = SCRIPT.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if 'case "$MODE" in' in line)
    begin = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == f"{mode})")
    end = next(i for i in range(begin + 1, len(lines)) if lines[i].strip() == ";;")
    return "\n".join(lines[begin:end])


@pytest.mark.parametrize("mode", ["quick", "full", "agent"])
def test_leg_is_wired_in_every_tier_that_runs_the_ai_agent_tests(mode):
    """跑 ai-agent 腿的三档都必须有这条前置（否则那档仍会把「凭据不认」报成失败）。"""
    branch = _mode_branch(mode)
    assert re.search(r'^[ ]{4}report_env ai-agent-e2e "', branch, re.M), (
        f"{mode} 档没有 `report_env ai-agent-e2e` 前置 —— 该档的 ai-agent 腿无法把"
        "「服务在跑但凭据不被接受」判成未就绪"
    )


def test_probe_key_is_declared_in_probe_ready():
    assert re.search(r"^\s{4}ai-agent-e2e\)", _extract("probe_ready"), re.M), (
        "probe_ready() 里没有 ai-agent-e2e 分支 ⇒ 运行时会记「脚本配置错误」"
    )


def _leg_harness(root: Path, probe_exit: int, *, venv: bool = True) -> str:
    """最小 harness：假 ROOT（venv 占位可执行 + 桩探针）+ 脚本里**真实的**三态包装。"""
    venv_path = root / "backend" / "ai-agent-service" / ".venv" / "bin" / "python"
    if venv:
        venv_path.parent.mkdir(parents=True, exist_ok=True)
        venv_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        venv_path.chmod(0o755)
    stub = root / "scripts" / "ai-agent-e2e-readiness.py"
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text(f"import sys\nprint('桩探针读数')\nsys.exit({probe_exit})\n", encoding="utf-8")
    return (
        "set -uo pipefail\n"
        f"ROOT={shlex.quote(str(root))}\n"
        "PASS=0; FAIL=0; READY=0; declare -a FAILED; declare -a NOT_READY\n"
        + _extract("probe_ready") + "\n" + _extract("report") + "\n" + _extract("report_env") + "\n"
        + 'report_env ai-agent-e2e "ai-agent e2e 前置就绪" bash -c "true"\n'
        + 'echo "COUNTERS PASS=$PASS FAIL=$FAIL READY=$READY"\n'
        # 只清本 harness 自己 PID 的日志（勿通配：会删掉别的 worktree 正在用的日志）
        + "rm -f /tmp/verify-all-$$-*.log\n"
    )


@pytest.mark.parametrize(
    ("probe_exit", "marker", "counters"),
    [
        (1, "未就绪", "PASS=0 FAIL=0 READY=1"),
        (0, "✅", "PASS=1 FAIL=0 READY=0"),
        (2, "❌", "PASS=0 FAIL=1 READY=0"),
    ],
)
def test_wiring_maps_probe_exit_code_to_the_three_states(tmp_path, probe_exit, marker, counters):
    reading = subprocess.run(["bash", "-c", _leg_harness(tmp_path / "root", probe_exit)],
                             capture_output=True, text=True)
    print(f"[接线] 探针 exit={probe_exit}：\n{reading.stdout}{reading.stderr}")
    assert f"COUNTERS {counters}" in reading.stdout, "三态计数与预期不符"
    assert marker in reading.stdout, f"exit={probe_exit} 没有落到「{marker}」那一态"
    if probe_exit == 1:
        assert "准备：" in reading.stdout, "未就绪必须给出**可行动**的一行「准备」"


def test_missing_venv_still_reports_not_ready_with_the_venv_hint(tmp_path):
    """**既有形态不许改坏**：worktree 缺 `.venv` ⇒ 仍是 ⏭️ + 建 venv 的准备命令（不是 ❌）。"""
    reading = subprocess.run(["bash", "-c", _leg_harness(tmp_path / "root", 0, venv=False)],
                             capture_output=True, text=True)
    print(f"[接线·缺 venv]：\n{reading.stdout}{reading.stderr}")
    assert "COUNTERS PASS=0 FAIL=0 READY=1" in reading.stdout, "缺 venv 必须记「未就绪」而不是「通过」"
    assert "❌" not in reading.stdout, "缺 venv 被记成 ❌（假红）—— 环境缺依赖不是缺陷"
    assert "python3 -m venv .venv" in reading.stdout, "未就绪必须给出建 venv 的准备命令"
