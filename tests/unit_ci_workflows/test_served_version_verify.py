# case_ids: MC-105
"""**「线上就是本次构建」必须可判读**（issue #6951；同族 #6611 / #6746 / #6554）。

## 病（现取读数，不是推断）

1. **`Post-Deploy Smoke Test` 被跳过**：`Build and Deploy admin-api` run `38681309878`
   （`2026-10-15T04:24:40Z`，sha `b4e63119` = 当时 main）⇒ `build-and-deploy: success` /
   **`Post-Deploy Smoke Test: skipped`**。门是
   `if: github.event_name != 'schedule' || needs.build-and-deploy.outputs.deployed == 'false'`
   ⇒ **schedule 兜底跑 + 未发生实际同步时冒烟不跑** ⇒ 那个 `success` **不含任何线上验证**。
2. **没有可读的版本端点**：`https://api.migaozn.com/actuator/{health,info}` 都是 **nginx 404**
   （`deploy/swas/nginx.conf` 的 `location ~ ^/(actuator|v3/api-docs|swagger-ui)(/|$)` ⇒ `return 404`）
   ⇒ 线上只能探到「服务活着且行为正常」，**探不到「跑的是哪个 build」**。
3. **同族实证**：#6746（兜底判据是「**镜像存在**」而非「**线上是它**」——实测只跑 22 秒也报 success）、
   #6611（`index.html` 字节哈希**跨版本相同** ⇒ 只证 chunk 图、不证部署了哪份代码）、
   #6554（断言说在跑 tag `046298d`，而线上前端实际停在 `03b1132`）。

## 本文件锁什么

判据本体 = `deploy/scripts/served-version-verify.sh`（同族先例 = `deploy/scripts/worker-h5-verify-served.sh`
的判别力口径：**探线上真正响应的内容**，不是探「推没推」）：

1. **红证（会红才算判据）**：注入一个**错误的期望 sha** ⇒ **退出码 1** + 输出里同时有
   「探到什么 / 期望什么 / 可复制复算命令」三件（issue #6951 判据 1 逐字）。
2. **绿（同口径的对照臂）**：期望 sha == 线上 sha ⇒ 退出码 0 + `SERVED_VERSION=match`。
3. **探不到 ⇒ fail-closed**：连不上 / 非 200（404 面被挡、429 限流）/ body 不是 JSON /
   `sha` 为空（**老镜像没有构建期注入面**）/ 期望 sha 形态不合法 ⇒ **退出码 3**，
   **不得**当「一致」（老镜像那条尤其关键：把它当绿会让判据在「镜像没换」时变**空断言**）。
4. **结构判据（判据 1 的另一半）**：`deploy-admin-api.yml` 的**通过条件**不再可能是
   「产物/镜像存在」——它必须真的调用 served-version 断言，且**期望值来自本次部署**
   （`github.sha` → `EXPECTED_SHA`），退出码**原样透传**（不许把 3 归一化成 0）。
5. **schedule 兜底档两态分开**：`skip=true`（本轮未部署）时必须有**显式出声**的声明步
   ——「本轮未部署 ⇒ 未跑冒烟」不得与「已部署且已验证」共用同一个静默 `success`
   （issue #6951 判据 2 逐字）。
6. **接线（注入面五跳同源）**：`deploy-admin-api.yml`（`BUILD_SHA` / `BUILD_TAG` / `BUILT_AT`）
   → **workflow 的远程调用参数**（`swas-deploy-ci.sh` 的第 9/10 位）
   → **驱动脚本的 BOOTSTRAP 渲染**（`export …;` + `__PLACEHOLDER__`）
   → `deploy/swas/deploy.sh`（`MIGAO_BUILD_SHA` 等 `--build-arg`）
   → `backend/admin-api/Dockerfile`（`ARG` + `ENV`）→ `VersionController`（读同名环境变量）。
   任一环改名 / 摘掉 ⇒ 具名判红（这是「端点报出的真是这次构建」的必要条件，不是装饰）。
   后两跳由**执行式**断言加钉：真跑 `render_bootstrap` + `deploy_attempt`（只桩 `run_cmd`/`nap`），
   捕获**实际发给远端的命令内容** —— 纯文本断言能被「模板里有占位符、渲染点却空转」骗过。
   🔴 第 2/3 跳是 issue #6951 补的：改前只覆盖**同一侧**四层，**没覆盖机器边界**（runner → ssh → 服务器）
7. **端点的泄露面白名单**：`VersionController` 的响应体**只许**有 5 个非敏感键
   （`app` / `sha` / `tag` / `builtAt`）⇒ 有人往里塞主机名 / 路径 / 环境变量 / 配置
   就判红（逼一次「它会不会泄露」的复核）。
8. **`/api/version` 落在已放行的路径面**：`SecurityConfig` 的 `permitAll` 必须含它，
   而 `nginx.conf` 必须**仍然**屏蔽 actuator 面 —— 后者是「探活面 ≠ 探版本面」这个前提本身，
   被悄悄放开会让本判据的设计前提消失（也不该顺带把 actuator 详情面暴露出去）。

## 桩的诚实标注（照实登记，§19.1）

- 本文件**不联网**：`/api/version` 由**本进程内**的 `http.server` 提供，脚本以
  `BASE_URL=http://127.0.0.1:<port>` + `SERVED_VERSION_PATH` / `SERVED_VERSION_RETRIES` 驱动。
  ⇒ 本文件证的是「**脚本在给定输入下会做什么**」，**不是**「线上真的会这么回」。
- **未覆盖（照实登记）**：① **线上真机复探**需要一次真实部署（由集成侧触发；本包**不在真机上跑**）
  —— 这是本条判据的**唯一终判**，命令逐字：
  `bash deploy/scripts/served-version-verify.sh 'https://api.migaozn.com' "$(git rev-parse origin/main)"`
  （要求 rc=0 + `SERVED_VERSION=match`）；
  ② 本文件只判 **admin-api** 腿的 served-version 断言；另两条腿的**构建身份接线**不在本文件射程内，
  逐腿登记在 `tests/unit_ci_workflows/test_swas_server_side_build.py` 的 `BUILD_IDENTITY_LEGS`
  （`deploy-frontend.yml` 由 issue #6611 接入、`deploy-ai-agent-service.yml` 由 issue #8203 接入 ⇒
  三条腿现已全部接线），逐跳（现取 → 位置参数 → BOOTSTRAP → `--build-arg` → Dockerfile `ENV`）
  由 `tests/unit_ci_workflows/test_synthetic_probe.py` 钉住；ai-agent 端点语义见
  `backend/ai-agent-service/tests/test_version_probe.py`；
  ③ Java 侧只做**静态接线判据**，本包**未**跑 `mvn test`（worktree 无构建产物、且那属于全量档）。
- **执行式探针的边界**：`_captured_remote_command()` 桩掉 `run_cmd`（拦住 `aliyun` CLI）与 `nap`，
  被桩化的是外部依赖，被测的是**驱动脚本自己的渲染编排**；它**不证**「阿里云会真的执行这条命令」。
"""
from __future__ import annotations

import json
import os
import re
import shlex
import socket
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

# 剥注释的**唯一**实现（`.github/danger_scan.py`，issue #5268）—— **复用，不复制**。
# `tests/unit_ci_workflows/conftest.py` 已把 `.github` 挂进 `sys.path`（与 `test_danger_scan.py` 同一机制）。
from danger_scan import strip_comment  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVED_VERIFY = REPO_ROOT / "deploy" / "scripts" / "served-version-verify.sh"
DEPLOY_SH = REPO_ROOT / "deploy" / "swas" / "deploy.sh"
DOCKERFILE = REPO_ROOT / "backend" / "admin-api" / "Dockerfile"
CONTROLLER = (
    REPO_ROOT
    / "backend"
    / "admin-api"
    / "src"
    / "main"
    / "java"
    / "com"
    / "migao"
    / "admin"
    / "controller"
    / "VersionController.java"
)
SECURITY_CONFIG = (
    REPO_ROOT
    / "backend"
    / "admin-api"
    / "src"
    / "main"
    / "java"
    / "com"
    / "migao"
    / "admin"
    / "security"
    / "SecurityConfig.java"
)
NGINX_CONF = REPO_ROOT / "deploy" / "swas" / "nginx.conf"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-admin-api.yml"
# ── 第 5 跳（issue #6951）的载体：CI → 驱动脚本 → 服务器 ─────────────────────────
CI_SCRIPT = REPO_ROOT / "deploy" / "scripts" / "swas-deploy-ci.sh"
# 驱动脚本「参数面」上的构建身份实参（**逐字**，第 9/10 个位置参数）
BUILD_SHA_ARG = '"$BUILD_SHA"'
BUILT_AT_ARG = '"$BUILT_AT"'
# BUILD_TAG **有意不**走参数面（远端 `TAG` 已携带同一个值）⇒ 它成实参即判红
BUILD_TAG_ARG = '"$BUILD_TAG"'
# 执行式断言（判据 6 的 ③b）用的部署期时钟读数
_BUILT_AT_PROBE = "2026-10-16T00:00:00Z"

# 与 CI 的 shell 同形（`bash --noprofile --norc -e -o pipefail`）
BASH_SHELL = ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail"]

# 判据 1 的红证锚点（注入一个**错误的期望 sha**）与判据 2 的对照臂
TARGET_SHA = "6f3aec2b8c0d9e1f2a3b4c5d6e7f8091a2b3c4d5"
WRONG_SHA = "deadbee" + "0" * 33


def read(path: Path) -> str:
    assert path.is_file(), f"反空跑锚点：文件不存在 → {path}"
    return path.read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════
# 进程内 `/api/version` 桩：状态码 / body 全部由用例给定（零网络、零外部依赖）
# ══════════════════════════════════════════════════════════════════════════

class _VersionHandler(BaseHTTPRequestHandler):
    status = 200
    body = b""
    content_type = "application/json"

    def do_GET(self):  # noqa: N802（http.server 的协议方法名）
        self.server.hits.append(self.path)  # type: ignore[attr-defined]
        self.send_response(self.status)
        self.send_header("Content-Type", self.content_type)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):  # 静音（判据输出只留被测脚本自己的读数）
        return


class VersionStub:
    """起一个只服务 `/api/version` 的本地 HTTP 桩，供脚本以真实 curl 打它。"""

    def __init__(self, body: bytes, status: int = 200, content_type: str = "application/json"):
        self.body = body
        self.status = status
        self.content_type = content_type
        self.hits: list[str] = []

    def __enter__(self) -> "VersionStub":
        handler = type(
            "Handler", (_VersionHandler,),
            {"status": self.status, "body": self.body, "content_type": self.content_type,
             "hits": self.hits},
        )
        self.httpd = HTTPServer(("127.0.0.1", 0), handler)
        self.httpd.hits = self.hits  # type: ignore[attr-defined]
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        return False

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def version_body(sha: str, app: str = "admin-api", tag: str = "sha-6f3aec2",
                 built_at: str = "2026-10-16T00:00:00Z") -> bytes:
    return json.dumps(
        {"app": app, "sha": sha, "tag": tag, "builtAt": built_at}
    ).encode("utf-8")


def run_verify(base_url: str, expected: str, **env_extra: str) -> subprocess.CompletedProcess:
    """跑**真脚本**（不是复制一段逻辑来测），只把 BASE_URL / 路径 / 重试参数换成桩。"""
    env = dict(os.environ)
    env.update({
        "SERVED_VERSION_RETRIES": "1",
        "SERVED_VERSION_RETRY_DELAY": "0",
        "SERVED_VERSION_PATH": "/api/version",
        # 桩上没有 CI 变量；显式清掉以免「本机跑」与「CI 跑」不同形
        "GITHUB_SHA": "",
    })
    env.update(env_extra)
    return subprocess.run(
        BASH_SHELL + [str(SERVED_VERIFY), base_url, expected],
        capture_output=True, text=True, env=env, timeout=120,
    )


def free_port_that_is_closed() -> int:
    """占一个端口再放掉 ⇒ 后续连接必然被拒（用来造「连不上」那一态，不依赖外网）。"""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


# ══════════════════════════════════════════════════════════════════════════
# 判据 1 / 2：红证 + 对照臂（同一场景、同一个脚本，只换期望 sha）
# ══════════════════════════════════════════════════════════════════════════

def test_served_sha_mismatch_is_red_and_names_both_sides():
    """🔴 红证：注入一个**错误的期望 sha** ⇒ 退出码 1，且三件（探到什么 / 期望什么 / 复算命令）都在。"""
    with VersionStub(version_body(TARGET_SHA)) as stub:
        proc = run_verify(stub.base_url, WRONG_SHA)

    assert proc.returncode == 1, (
        "注入错误期望 sha 却**没有**判红 ⇒ 判据不具判别力（正是 issue #6951 的形态）\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    out = proc.stdout
    # ① 探到什么
    assert TARGET_SHA in out, f"判红输出里没有**实测** sha（探到什么）：\n{out}"
    # ② 期望什么
    assert WRONG_SHA in out, f"判红输出里没有**期望** sha：\n{out}"
    # ③ 可复制复算命令（同族先例的「具名 + 可复算」口径）
    assert "served-version-verify.sh" in out, f"判红输出里没有可复制复算命令：\n{out}"
    assert "curl" in out, f"判红输出里没有可直接粘贴的 curl 复算命令：\n{out}"
    # 机读读数（判据的下游消费面）
    assert "SERVED_VERSION=mismatch" in out, f"缺机读读数 SERVED_VERSION=mismatch：\n{out}"
    assert "::error::" in out, f"判红没有落成 GitHub 注解（::error::）：\n{out}"


def test_served_sha_match_is_green_control_arm():
    """对照臂：同一场景、只把期望 sha 换回真的 ⇒ 退出码 0 + `SERVED_VERSION=match`。

    ⚠️ 这一条是红证的**必要性对照**：没有它，「恒红」也能过上面那条 ⇒ 红证本身不成立。
    """
    with VersionStub(version_body(TARGET_SHA)) as stub:
        proc = run_verify(stub.base_url, TARGET_SHA)

    assert proc.returncode == 0, f"期望 sha 与线上一致却判红：\n{proc.stdout}\n{proc.stderr}"
    assert "SERVED_VERSION=match" in proc.stdout
    assert "SERVED_VERSION=mismatch" not in proc.stdout


def test_full_sha_from_endpoint_matches_seven_char_tag_prefix():
    """端点报 40 位、镜像 tag 是 7 位 ⇒ 比前 7 位（本仓全链路既有口径），不许因位宽不同误红。"""
    with VersionStub(version_body(TARGET_SHA)) as stub:
        proc = run_verify(stub.base_url, TARGET_SHA[:7])

    assert proc.returncode == 0, f"7 位期望 sha 与 40 位实测 sha 同源却判红：\n{proc.stdout}"


# ══════════════════════════════════════════════════════════════════════════
# 判据 3：探不到 ⇒ 退出码 3（fail-closed，**绝不当绿**）
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "name, stub_kwargs, expected_sha, expect_recompute_cmd",
    [
        ("sha 为空（老镜像没有构建期注入面）", {"body": version_body("")}, TARGET_SHA, True),
        ("body 不是 JSON", {"body": b"<html>404 not found</html>"}, TARGET_SHA, True),
        ("HTTP 404（该路径没被放行 / 端点不存在）", {"body": b"", "status": 404}, TARGET_SHA, True),
        ("HTTP 429（nginx 的 /api/ 限流档拦了探针）", {"body": b"", "status": 429}, TARGET_SHA, True),
        ("sha 不是 hex（形态不符）", {"body": version_body("not-a-sha")}, TARGET_SHA, True),
        # 这两条坏的**是期望值本身**（判据的前置没成立）⇒ 给复算命令是无意义的
        # （"再跑一次同一个坏期望" 不解决问题）⇒ 它们只要求三态正确 + 机读读数正确。
        ("期望 sha 形态不合法", {"body": version_body(TARGET_SHA)}, "not-a-sha", False),
        ("期望 sha 太短（<7 位）", {"body": version_body(TARGET_SHA)}, "6f3aec", False),
        ("app 不是目标服务", {"body": version_body(TARGET_SHA, app="ai-agent")}, TARGET_SHA, True),
    ],
)
def test_unverifiable_is_exit_3_never_green(name, stub_kwargs, expected_sha, expect_recompute_cmd):
    """「探不到」必须长得像「探不到」：退 3 + `SERVED_VERSION=unknown`，**不得**退 0。

    🔴 其中「sha 为空」这一条是**本判据最容易退化成空断言**的路径：老镜像（没有注入面）时，
    把空 sha 当绿会让判据在每一次「镜像没换」的部署上悄悄通过。
    """
    env_extra = {"SERVED_VERSION_APP": "admin-api"}
    with VersionStub(**stub_kwargs) as stub:
        proc = run_verify(stub.base_url, expected_sha, **env_extra)

    assert proc.returncode == 3, (
        f"[{name}] 期望 fail-closed(3)，实际 {proc.returncode} ⇒ 「取不到」被当成了别的语义\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert "SERVED_VERSION=unknown" in proc.stdout, f"[{name}] 缺机读读数 SERVED_VERSION=unknown"
    assert "SERVED_VERSION=match" not in proc.stdout, f"[{name}] 探不到却报了 match"
    if expect_recompute_cmd:
        assert "served-version-verify.sh" in proc.stdout, f"[{name}] 探不到时没给可复制复算命令"


def test_unreachable_endpoint_is_exit_3():
    """连不上（端口没人听）⇒ 退 3（不是 0、也不是 1）。"""
    port = free_port_that_is_closed()
    proc = run_verify(f"http://127.0.0.1:{port}", TARGET_SHA)

    assert proc.returncode == 3, f"连不上应判「探不到」(3)，实际 {proc.returncode}:\n{proc.stdout}"
    assert "SERVED_VERSION=unknown" in proc.stdout
    assert "curl -sS" in proc.stdout, "「探不到」时也要给可直接粘贴的复算命令"


# ══════════════════════════════════════════════════════════════════════════
# 判据 4 / 5 / 6：发布腿的**结构**判据（通过条件不再可能是「产物存在」）
# ══════════════════════════════════════════════════════════════════════════

def workflow_text() -> str:
    return read(WORKFLOW)


SERVED_STEP = "Assert served sha == deployed sha (线上就是本次构建，issue #6951)"
SMOKE_DECL_STEP = "Declare smoke verification state (schedule 兜底档，issue #6951)"
# ⚠️ 步名逐字 = `Resolve build identity (issue #6951)`（**ASCII 收尾括号**；别写成全角 `）` ——
#    本包实测踩到：全角形态按名字取步恒取空，判据静默空跑）。
#    🔴 该步名改前**没加引号**，而 YAML 把 ` #` 当**注释起点** ⇒ 解析出来的步名被截断成
#    `"Resolve build identity (issue"`（真跑读数，不是推断）⇒ 已顺手加引号（行为等价、只让读数忠实），
#    并在 `test_workflow_yaml_still_parses_after_the_value_source_change` 里补了形态守卫。
RESOLVE_STEP = "Resolve build identity (issue #6951)"

# ── issue #7015 的类级面：workflow 的 run 正文里**默认注入**的环境变量清单 ────────────
# 只列**本判据真正要用**（= 会被当默认值使用的）那些：漏列一条只会让守卫更严（宁可误报复核），
# 而多列一条不存在的默认变量会让守卫失明 ⇒ 这里刻意只放「GitHub 确定注入、且本仓确实在用」的。
DEFAULT_GITHUB_ENV_LITERALS = {
    "GITHUB_ACTIONS", "GITHUB_ACTION", "GITHUB_ACTOR", "GITHUB_API_URL",
    "GITHUB_ENV", "GITHUB_EVENT_NAME", "GITHUB_EVENT_PATH", "GITHUB_GRAPHQL_URL",
    "GITHUB_JOB", "GITHUB_OUTPUT", "GITHUB_PATH", "GITHUB_REF", "GITHUB_REF_NAME",
    "GITHUB_REPOSITORY", "GITHUB_RUN_ATTEMPT", "GITHUB_RUN_ID", "GITHUB_RUN_NUMBER",
    "GITHUB_SERVER_URL", "GITHUB_SHA", "GITHUB_STEP_SUMMARY", "GITHUB_TOKEN",
    "GITHUB_TRIGGERING_ACTOR", "GITHUB_WORKFLOW", "GITHUB_WORKFLOW_REF", "GITHUB_WORKFLOW_SHA",
    "GITHUB_WORKSPACE",
}
# 允许的例外（**只许缩短**：清空 ⇒ 下面那条 fail-closed 自证会判红）。
# 加例外 = 有人要给某个 `GITHUB_*` 名字一个自定义 env ⇒ 那一刻必须显式登记到这里并写理由。
GITHUB_ENV_LITERAL_EXEMPTIONS: dict[str, str] = {}


def _literal_github_env_defaults(workflow_path: Path) -> set[str]:
    """workflow 里**当默认值用 / 直接展开**的自定义 `GITHUB_*` 字面量。

    只看**非注释**的 shell 正文（找根因的注释里一定会提到那个编造的名字 —— 那不是「还在用它」）：
      · `${GITHUB_X:-…}` / `$GITHUB_X` ⇒ 报出 `GITHUB_X`；
      · `env:` 块里 `GITHUB_X: <字面量>` ⇒ 报出 `GITHUB_X`（有人定义过它）；
      · 含 `${{ … }}` 的行跳过（那是 Actions 的 context 表达式，由 Actions 自己求值，**不在射程内**）。

    ⚠️ 剥注释**复用** `.github/danger_scan.py::strip_comment`（**唯一**一份实现，issue #5268 / #5944）
    —— 不在这里另写一把尺子（`test_deploy_leg_run_undefined_vars.py` 的判据 4d 会判红「第二把尺子」）。
    """
    names: set[str] = set()
    for raw in workflow_path.read_text(encoding="utf-8").splitlines():
        line = strip_comment(raw)          # 行尾注释先剥掉（**未定义的变量名一定会出现在注释里**）
        if "${{" in line:
            continue
        if re.search(r"^\s*[-A-Za-z0-9_]*GITHUB_[A-Z0-9_]+\s*:", line):
            m = re.search(r"(GITHUB_[A-Z0-9_]+)\s*:", line)
            if m:
                names.add(m.group(1))
            continue
        names.update(re.findall(r"\$\{?(GITHUB_[A-Z0-9_]+)", line))
    return names

# 从驱动脚本里抽函数体用的段界（与既有探针 tests/unit_ci_workflows/test_swas_deploy_no_downgrade.py
# 的 PROBE_START/PROBE_END **同一对锚点** —— 不复制判据，只借它的抽取面）
_CI_PROBE_START = "# ⑤ 部署脚本**自己**也必须与镜像 tag 同源"
_CI_PROBE_END = "# ── 主流程 "
# 渲染编排的调用链（缺任一个 ⇒ 显式失败，不是「通过」）
_CI_PROBE_FUNCS = ("bootstrap_tag_to_sha", "bootstrap_ref_for_tag", "render_bootstrap", "deploy_attempt")
# 桩：把真正要执行的命令落盘，并回「三次都没 InvokeId」⇒ `deploy_attempt` 早退但**命令已捕获**
_CI_RUN_CMD_STUB = """
run_cmd() {
  local k=$1 c=$2; shift 2
  local arg prev=""
  for arg in "$@"; do
    if [ "$prev" = "--command-content" ]; then printf '%s' "$arg" > "$CAPTURED_CMD"; fi
    prev=$arg
  done
  printf '%s' '{"InvokeId": ""}'
  return 0
}
nap() { return 0; }
"""


def _function_body(text: str, name: str) -> str:
    """取 shell 函数体（`name() {` 到配对收尾 `}` 那一行）。取不到 ⇒ **显式失败**（不是空跑）。"""
    m = re.search(rf"^{re.escape(name)}\(\) \{{$", text, re.M)
    assert m, f"反空跑锚点：驱动脚本里找不到函数 `{name}()`（判据已过期）"
    end = text.find("\n}\n", m.end())
    assert end != -1, f"函数 `{name}()` 没有配对的收尾 `}}`（脚本语法已坏）"
    return text[m.end():end]


def _captured_remote_command(ci_text: str, build_sha: str) -> str:
    """**真跑** `render_bootstrap` + `deploy_attempt`（只桩 `run_cmd` / `nap`），返回实际发给远端的命令。

    这是「第 5 跳」的执行式判据：文本断言能被「模板里有占位符、渲染点却空转」骗过，
    捕获实发命令不会 —— 身份变量必须在**渲染后**的字符串里。

    ⚠️ `BOOTSTRAP=` 这一行**在抽取段之外**（它定义在「③ 回滚点」那一节、渲染函数之前）
    ⇒ 必须**逐字带上它自己的模板**（`^BOOTSTRAP="…"$` 单行形态，与既有两条守卫同级），
    否则探针拿到空模板、命令内容恒 0 字节 ⇒ 判据变成**空跑**（本包第一版实测踩到：
    `命令内容 0 字节` / 捕获到空串 —— 看起来像「身份没送达」，其实是抽取面漏了模板）。
    """
    tmpl = re.search(r'^BOOTSTRAP=".*"$', ci_text, re.M)
    assert tmpl, "反空跑锚点：驱动脚本里找不到 `BOOTSTRAP=\"…\"` 模板（判据已过期）"
    start = ci_text.find(_CI_PROBE_START)
    assert start >= 0, f"反空跑锚点：找不到驱动脚本的渲染编排段头 {_CI_PROBE_START!r}（判据已过期）"
    end = ci_text.find(_CI_PROBE_END, start)
    assert end > start, f"反空跑锚点：找不到主流程段 {_CI_PROBE_END!r}（判据已过期）"
    region = ci_text[start:end]

    parts = [
        "set -uo pipefail",
        # ⚠️ **顺序有意义**：`REGISTRY_SETUP` 必须**先定义**再求值 BOOTSTRAP —— 模板里那一处
        #    `${REGISTRY_SETUP}` 是**本地展开**的（脚本里第 406 行就求值，本探针同形）。
        #    反过来写 ⇒ `set -u` 当场 `unbound variable`（本包实测踩到：探针 RC 127、零捕获）。
        'IMAGE_TAG="sha-1a1a1a1"',
        'INSTANCE_ID="i-probe"',
        'REGION="cn-probe"',
        'REGISTRY_SETUP=""',
        tmpl.group(0),                      # ← 被测的模板本身（逐字取自脚本当前文本）
        # 与真实调用点同形：两个身份值来自**参数面**（第 9/10 个位置参数）
        f"BUILD_SHA={shlex.quote(build_sha)}",
        f"BUILT_AT={shlex.quote(_BUILT_AT_PROBE)}",
        'DEPLOY_TIMEOUT_SECONDS=1',
        'CLI_TIMEOUT_SECONDS=1',
        'POLL_INTERVAL_SECONDS=0',
        'RETRY_PAUSE_SECONDS=0',
        'DEADLINE=$(( $(date +%s) + DEPLOY_TIMEOUT_SECONDS ))',
        'remaining_seconds() { echo $(( DEADLINE - $(date +%s) )); }',
    ]
    for name in _CI_PROBE_FUNCS:
        parts.append(f"{name}() {{{_function_body(region, name)}\n}}")
    # ⚠️ 桩必须定义在**真函数之后**（shell 是「后定义覆盖先定义」）
    parts.append(_CI_RUN_CMD_STUB)
    parts.append('deploy_attempt "$IMAGE_TAG" 0')   # allow=0 = 普通部署（#4852 的对照读数）

    with tempfile.TemporaryDirectory() as tmp:
        captured = Path(tmp) / "captured-cmd"
        env = {**os.environ, "CAPTURED_CMD": str(captured)}
        proc = subprocess.run(["bash", "-c", "\n".join(parts)],
                              capture_output=True, text=True, timeout=60, env=env)
        assert captured.is_file(), (
            "没捕获到远端命令 ⇒ `deploy_attempt` 在把命令交给远端**之前**就 fail-closed 早退了"
            f"（这本身就是「身份没送达」的一种形态）\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
        content = captured.read_text(encoding="utf-8")
        assert content.strip(), (
            "捕获到的远端命令是**空串** ⇒ 探针空跑（模板没带上 / 渲染段抽取错位），"
            f"不得据此判绿\nstdout:\n{proc.stdout[:800]}"
        )
        return content


def test_deploy_leg_asserts_served_sha_not_artifact_existence():
    """判据 4：发布腿必须**真的**断言「线上 sha == 本次部署的 sha」，且期望值来自本次部署。"""
    text = workflow_text()
    assert SERVED_STEP in text, "部署腿里没有 served-version 断言步 ⇒ 通过条件仍停在「产物存在」"
    assert "deploy/scripts/served-version-verify.sh" in text, (
        "没有调用共享判据本体 ⇒ 要么判据缺失、要么被内联复制（两条都不许）"
    )
    assert "EXPECTED_SHA: ${{ github.sha }}" in text, (
        "期望 sha 不是本次部署的 commit ⇒ 判据比的是别的东西（#6554 的形态）"
    )
    # 退出码**原样透传**：3（探不到）不许被归一化成 0（那正是本单要治的假绿）
    assert "exit \"$rc\"" in text, "served-version 断言没有把退出码原样透传 ⇒ 三态会退化成两态"


def test_deploy_leg_never_keys_pass_on_artifact_existence():
    """判据 4（类级形态）：served-version 断言的**生效条件**不得绑在「产物/结论」面上。

    允许 `steps.sync.outputs.skip` 继续决定「**要不要下载/构建**」（那是省算力，不是判据）；
    不允许它出现在 served-version 断言的 `if:` 里 —— 一旦有人把它改成
    `if: steps.sync.outputs.skip != 'true'`（= 跳过档不验证），当场判红。
    """
    text = workflow_text()
    steps = re.split(r"\n      - name: ", text)
    served = [s for s in steps if s.startswith(f'"{SERVED_STEP}"')]
    assert len(served) == 1, f"期望恰好 1 个 served-version 断言步，实测 {len(served)}"
    body = served[0]
    if_match = re.search(r"^\s*if:\s*(.+)$", body, re.M)
    assert if_match, "served-version 断言步没有 `if:` ⇒ 无法判定它在哪条路径上生效"
    condition = if_match.group(1)
    assert "steps.sync.outputs.skip" not in condition, (
        "served-version 断言的生效条件绑在 `steps.sync.outputs.skip` 上 ⇒ "
        "跳过档（schedule 兜底）就不再验证线上是不是目标构建 —— 那正是 issue #6951 的形态"
    )
    # 它必须**两条路径都跑**：跳过档也要探一次（否则「本轮未部署」就没有任何线上读数）
    assert "always()" in condition, (
        f"served-version 断言不是 `always()` ⇒ 可能在跳过档整步不跑（实测条件：{condition}）"
    )


def test_schedule_skip_path_declares_that_no_smoke_ran():
    """判据 5：schedule 兜底档（skip=true ⇒ 本轮未部署）必须**显式出声**，不得静默 success。"""
    text = workflow_text()
    assert SMOKE_DECL_STEP in text, "没有「本轮未部署 ⇒ 未跑冒烟」的声明步 ⇒ success 仍会被读成「已验证」"
    assert "::notice::" in text, "声明步没有落成可见注解（::notice::）"
    assert "未跑 Post-Deploy Smoke Test" in text, "声明步没有逐字写出「未跑冒烟」"
    assert "GITHUB_STEP_SUMMARY" in text.split(SMOKE_DECL_STEP, 1)[1], (
        "声明步没有落 run summary ⇒ 只活在日志里（会被截断）"
    )
    # `deployed` 的语义必须自洽：存在「真的部署了」这一真值，且它**不是** skip 的同一串
    assert "deployed: ${{ steps.sync.outputs.skip != 'true' }}" in text, (
        "`deployed` 仍写成 `steps.sync.outputs.skip` ⇒ 名字与含义相反（本轮未部署却报 deployed=true）"
    )
    smoke_if = re.search(r"needs: build-and-deploy\n(?:.*\n)*?\s*if: (.+)$", text, re.M)
    assert smoke_if and "deployed == 'true'" in smoke_if.group(1), (
        "冒烟 job 的条件与订正后的 `deployed` 语义不一致"
    )


def test_build_identity_wiring_is_same_source_across_five_hops():
    """判据 6（升级为**五跳**同源）：注入面从「本次部署的 sha」到「端点读到的环境变量」共 **5 跳**，
    断任何一跳 ⇒ 端点报的就不是这次构建（`sha` / `builtAt` 恒为空）。

    | 跳 | 载体 | 逐字形态 |
    |---|---|---|
    | 1 | `deploy-admin-api.yml` 解算 build identity + 部署步 env | `id: build_id` · `BUILD_SHA=$SHA` · 三项 env |
    | **2** | **workflow 的远程调用**（`swas-deploy-ci.sh` 的第 9/10 个位置参数） | `admin-api "$BUILD_SHA" "$BUILT_AT"` |
    | **3** | **驱动脚本的 BOOTSTRAP**（`export …;` 串 + `__PLACEHOLDER__` 渲染点） | `BUILD_SHA=__BUILD_SHA__ BUILT_AT=__BUILT_AT__` + 显式渲染 + 未渲染即 fail-closed |
    | 4 | `deploy/swas/deploy.sh` | `BUILD_SHA=${BUILD_SHA:-}` → `--build-arg MIGAO_BUILD_SHA=${BUILD_SHA:-}` |
    | 5 | `backend/admin-api/Dockerfile` → `VersionController` | `ARG`/`ENV MIGAO_BUILD_SHA` → `@Value("${MIGAO_BUILD_SHA:}")` |

    🔴 **跳 2 / 3 是本单（issue #6951）补上的**：改前本判据只覆盖**同一侧**的四个文件
    （workflow env → deploy.sh → Dockerfile → 控制器），**没有覆盖机器边界**（runner → ssh → 服务器）
    ⇒ 单元级「四层同源」全绿，而真机读数逐字为
    `{"app":"admin-api","sha":"","tag":"sha-bab9538","builtAt":""}`，部署 run `38835344964`
    判红在 `Assert served sha == deployed sha`（exit 3 = 探不到）。
    **跨边界的东西必须在边界上判** —— 所以跳 3 除文本断言外还带**执行式**断言（见 ③b）。
    """
    wf = workflow_text()
    ci = read(CI_SCRIPT)
    deploy_sh = read(DEPLOY_SH)
    dockerfile = read(DOCKERFILE)
    controller = read(CONTROLLER)

    # ① 跳 1 — workflow：解算 build identity 并交给部署步（env 名 → deploy.sh 的变量名）
    assert "id: build_id" in wf, "workflow 没有解算构建身份（git rev-parse HEAD）"
    assert 'echo "BUILD_SHA=$SHA" >> "$GITHUB_OUTPUT"' in wf, "构建身份没有落成 step output"
    for env_name, source in (
        ("BUILD_SHA: ${{ steps.build_id.outputs.BUILD_SHA }}", "step output"),
        ("BUILD_TAG: ${{ steps.tag.outputs.IMAGE_TAG }}", "镜像 tag（与 compose 同源）"),
        ("BUILT_AT: ${{ steps.build_id.outputs.BUILT_AT }}", "部署期时钟"),
    ):
        assert env_name in wf, f"部署步没有把构建身份传下去：{env_name}（来源 {source}）"

    # ② 跳 2 — workflow 的**远程调用**：构建身份必须过**参数面**（不是只留在 runner 的步骤 env）
    call = re.search(r"bash deploy/scripts/swas-deploy-ci\.sh \\\n((?:.*\\\n)*.*)", wf)
    assert call, "workflow 里找不到 `swas-deploy-ci.sh` 的调用（判据锚点已漂移）"
    call_args = call.group(1).replace("\\\n", " ").split()
    assert "admin-api" in call_args, f"远程调用里找不到服务键（判据锚点已漂移）：{call_args}"
    for token in (BUILD_SHA_ARG, BUILT_AT_ARG):
        assert token in call_args, (
            f"workflow 的远程调用**没有把构建身份交给驱动脚本**（实参缺 {token}）⇒ "
            "这一跳就是本单的病根：`BUILD_SHA` / `BUILT_AT` 只活在 runner 的步骤 env 里，"
            "而构建发生在**服务器上** ⇒ 远端读到空串 ⇒ `/api/version` 的 `sha` / `builtAt` 恒空"
        )
    # BUILD_TAG **有意不过参数面**（远端 `TAG` 已携带同一个值）⇒ 双向钉住：值仍与镜像 tag 同源 + 没多传实参
    assert "BUILD_TAG: ${{ steps.tag.outputs.IMAGE_TAG }}" in wf, (
        "BUILD_TAG 不再来自镜像 tag ⇒ 与 compose 的 `image:` 脱钩（两条会漂的口径）"
    )
    assert BUILD_TAG_ARG not in call_args, (
        f"`{BUILD_TAG_ARG}` 被当实参传了 —— 它**有意**不走参数面（远端 `TAG` 已是同一个值），"
        "再送一份就是第二条会漂的口径"
    )

    # ③ 跳 3 — 驱动脚本：模板里带占位符 + 从**参数面**读 + **显式渲染** + 未渲染即 fail-closed
    for ph in ("BUILD_SHA", "BUILT_AT"):
        assert f"{ph}=__{ph}__" in ci, (
            f"BOOTSTRAP 没有把 `{ph}` 送往远端（`export …;` 串里没有占位符 `__{ph}__`）"
            " ⇒ 远端 `deploy.sh` 读到空串 ⇒ 端点那两个字段恒空（issue #6951 的第 5 跳）"
        )
    for var in ("BUILD_SHA", "BUILT_AT"):
        assert re.search(rf"^{var}=\$\{{(9|10)[:]", ci, re.M), (
            f"驱动脚本没有从**位置参数**取 `{var}`（第 9/10 位）⇒ 参数面这一跳没接上"
        )
        assert re.search(rf"out=\$\{{out//__{var}__/\$\{{", ci), (
            f"占位符 `__{var}__` 没有在 render_bootstrap 里被显式渲染 ⇒ 远端会拿到字面量"
        )
    for ph in ("__BUILD_SHA__", "__BUILT_AT__"):
        assert re.search(rf"\*{ph}\*", ci), (
            f"渲染后没有自证「占位符 `{ph}` 已替换」（fail-closed）⇒ 漏渲染会静默把字面量发给服务器"
        )
    # 有意不送 BUILD_TAG ⇒ BOOTSTRAP 里不该有它的占位符（免得与远端 `$TAG` 形成两条口径）
    assert "__BUILD_TAG__" not in ci, (
        "驱动脚本把 `BUILD_TAG` 也送下去了 ⇒ 与远端 `TAG`（渲染进 BOOTSTRAP 的那个）成为两条口径"
    )

    # ③b **执行式**同源（本判据的注入点）：真跑 `render_bootstrap` + `deploy_attempt`
    # （只桩 `run_cmd` / `nap`），捕获**实际发给远端的命令内容** —— 身份必须在里面。
    # 纯文本断言会被「模板里有占位符、渲染点却空转」骗过；这一条不会。
    captured = _captured_remote_command(ci, TARGET_SHA)
    for expected in (f"BUILD_SHA={TARGET_SHA}", f"BUILT_AT={_BUILT_AT_PROBE}"):
        assert expected in captured, (
            f"渲染后的远端命令里没有 `{expected}` ⇒ 身份**没有真的送达远端**（这一跳是空转）。\n"
            f"实得命令内容（前 600 字节）：\n{captured[:600]}"
        )
    assert "__BUILD_SHA__" not in captured and "__BUILT_AT__" not in captured, (
        f"渲染后的命令里仍留占位符 ⇒ 远端会拿到字面量：\n{captured[:400]}"
    )
    # 对照读数：同一次渲染里 `ALLOW_DOWNGRADE` 仍是普通部署的 0（#4852 的渲染织体未被本单改坏）
    assert "ALLOW_DOWNGRADE=0" in captured, (
        "同一次渲染里 `ALLOW_DOWNGRADE` 不再是 0（普通部署）⇒ 本单改坏了 #4852 的许可面"
    )

    # ④ 跳 4 — deploy.sh：三个变量 → `--build-arg MIGAO_BUILD_*`
    for var in ("BUILD_SHA", "BUILD_TAG", "BUILT_AT"):
        assert re.search(rf"^{var}=\$\{{{var}:-", deploy_sh, re.M), (
            f"deploy.sh 没有 `${var}` 的入口（`set -u` 下裸引用会当场炸；且会静默丢注入面）"
        )
    for arg in ("MIGAO_BUILD_SHA=${BUILD_SHA:-}", "MIGAO_BUILD_TAG=${BUILD_TAG:-$TAG}",
                "MIGAO_BUILT_AT=${BUILT_AT:-}"):
        assert arg in deploy_sh, f"deploy.sh 没有把 `{arg}` 交给 docker build"

    # ⑤ 跳 5 — Dockerfile：ARG 必须在**两个 stage** 各声明一次（ARG 作用域是 per-stage），
    #    并由 ENV 落到运行时容器（消费面读的是环境变量）
    for name in ("MIGAO_BUILD_SHA", "MIGAO_BUILD_TAG", "MIGAO_BUILT_AT"):
        assert dockerfile.count(f"ARG {name}=") == 2, (
            f"Dockerfile 的 `ARG {name}=` 必须出现 **2** 次（builder + runtime 两个 stage 各一次）"
            f"，实测 {dockerfile.count(f'ARG {name}=')} 次"
        )
        assert f"ENV {name}=${name}" in dockerfile, f"Dockerfile 没有把 `{name}` 落成容器环境变量"

    # ⑥ 跳 5（消费点）— 控制器：读的必须是**同名**环境变量（改名 ⇒ 端点报空串 ⇒ 判据恒「探不到」）
    for name in ("MIGAO_BUILD_SHA", "MIGAO_BUILD_TAG", "MIGAO_BUILT_AT"):
        assert f'@Value("${{{name}:}}")' in controller, (
            f"VersionController 没有读环境变量 `{name}`（五跳里这一环断了）"
        )


def test_version_endpoint_field_whitelist_blocks_accidental_leaks():
    """判据 7：端点的泄露面 = 4 个非敏感字段；加字段就判红（逼一次安全复核）。"""
    controller = read(CONTROLLER)
    keys = re.findall(r'body\.put\("([^"]+)"', controller)
    assert keys == ["app", "sha", "tag", "builtAt"], (
        f"响应字段白名单变了（实测 {keys}）⇒ 重新过一遍「它会不会泄露」："
        "主机名 / 路径 / 环境变量 / 依赖版本 / 配置都不许上屏"
    )
    # 端点是只读的（不给写面）
    assert "@GetMapping" in controller and "@PostMapping" not in controller, (
        "版本端点必须是 `@GetMapping`（只读）；出现写映射 ⇒ 立刻停下复核"
    )


def test_version_endpoint_is_under_the_already_allowed_api_prefix():
    """判据 8：端点挂在**已放行**的 `/api/` 前缀下，且 actuator 面**仍然**被 nginx 屏蔽。"""
    controller = read(CONTROLLER)
    assert '@GetMapping(value = "/api/version"' in controller, (
        "端点路径不在 `/api/` 前缀下 ⇒ 要么状态码被 nginx 挡成 404，要么得新增放行面"
    )
    security = read(SECURITY_CONFIG)
    assert '"/api/version",' in security, (
        "`/api/version` 不在 SecurityConfig 的 permitAll 名单里 ⇒ 探针（无凭据）会拿到 401 ⇒ 判据退化"
    )
    nginx = read(NGINX_CONF)
    actuator_block = re.search(
        r"location ~ \^/\(actuator\|v3/api-docs\|swagger-ui\)\(/\|\$\) \{\s*return (\d+);",
        nginx,
    )
    assert actuator_block, (
        "nginx.conf 里那条 actuator/swagger 屏蔽块不见了 ⇒ 「探活面 ≠ 探版本面」这个前提消失了"
        "（也说明 actuator 详情面可能被顺带放开）"
    )
    assert actuator_block.group(1) == "404", (
        f"actuator 面的屏蔽码从 404 改成了 {actuator_block.group(1)} ⇒ 本判据的设计前提变了，停下来复核"
    )


def test_shared_script_is_executable_and_self_describing():
    """反空跑 + 可执行：脚本必须带 shebang、可执行位、且**不**依赖调用方 cwd。"""
    assert SERVED_VERIFY.is_file(), "判据本体脚本不存在"
    text = read(SERVED_VERIFY)
    assert text.startswith("#!/usr/bin/env bash"), "缺 shebang"
    mode = SERVED_VERIFY.stat().st_mode
    assert mode & 0o111, f"脚本不可执行（mode={oct(mode)}）⇒ CI 里 `bash <path>` 之外的形式会失败"
    for anchor in ('SERVED_VERSION=match', 'SERVED_VERSION=mismatch', 'SERVED_VERSION=unknown'):
        assert anchor in text, f"缺机读读数 {anchor}（下游消费面会失去三态区分）"


def test_shared_script_parses_and_has_no_unquoted_cjk_adjacent_expansion():
    """`bash -n` + **中文紧贴裸变量**的形态守卫（本包实测踩过，见下）。

    🔴 实测（本包第一版）：`echo "…：$EXPECTED（前 7 位 $EXPECTED7）"` —— 中文全角括号紧跟 `$EXPECTED`
    ⇒ bash 把 `（` 的字节并进**变量名** ⇒ `set -u` 下报
    `line 85: EXPECTED\\ufffd: unbound variable`，而真正的坏点在**几行之外**（诊断成本极高）。
    同一形态还能造成**未闭合引号**（`echo "SERVED_VERSION=mismatch` 少了右引号 ⇒ 整段被吞）。
    ⇒ 本判据把两类都钉住：脚本必须能被 `bash -n` 解析，且**不许**出现裸 `$VAR` 紧跟非 ASCII。
    """
    text = read(SERVED_VERIFY)
    syntax = subprocess.run(BASH_SHELL[:1] + ["-n", str(SERVED_VERIFY)],
                            capture_output=True, text=True, timeout=60)
    assert syntax.returncode == 0, f"脚本语法不过 `bash -n`：\n{syntax.stderr}"

    # 逐行扫裸 `$VAR` / `$1` 紧跟非 ASCII（`${VAR}` 形态是安全的，跳过）
    offenders = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in re.finditer(r"\$[A-Za-z_][A-Za-z0-9_]*|\$[0-9]", line):
            end = match.end()
            if end < len(line) and ord(line[end]) > 127:
                offenders.append(f"{lineno}: {line.strip()[:120]}")
    assert not offenders, (
        "出现「裸 `$VAR` 紧跟非 ASCII」⇒ bash 会把中文字节并进变量名（`set -u` 下报 unbound variable，"
        "且报错行号与实际坏点不一致）⇒ 改成 `${VAR}` 形态：\n" + "\n".join(offenders)
    )


# ══════════════════════════════════════════════════════════════════════════
# 判据 12：`builtAt` 面的具名判据（issue #7015）—— 「探到了、值是空」必须判红
# ══════════════════════════════════════════════════════════════════════════

def test_empty_builtat_is_red_when_required_and_names_the_value_source():
    """🔴 **红证**：`sha` 与期望一致、但线上自报的 `builtAt` 是**空串** ⇒ 退出码 **1** 且**点名取值源未接**。

    这是 issue #7015 的**实例判据**：改前 `builtAt` 恒空而**没有任何东西会红**（空串既不是
    「探到非空」、也不是「探不到 ⇒ 退 3」）⇒ 一条**恒真的空断言**。本判据把「探到了、值是空」
    单独立成一条**会红的**判据，且**不许**与「探不到（退 3）」混桶。
    """
    with VersionStub(version_body(TARGET_SHA, built_at="")) as stub:
        proc = run_verify(stub.base_url, TARGET_SHA, SERVED_VERSION_REQUIRE_BUILT_AT="1")

    assert proc.returncode == 1, (
        "`builtAt` 为空却**没有**判红 ⇒ 仍是空断言（issue #7015 的形态）\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    out = proc.stdout
    assert "#7015" in out, f"判红没有点名 issue #7015（归因面）：\n{out}"
    assert "取值源未接" in out, f"判红没有点名「取值源未接」这个具体病灶：\n{out}"
    # 语义必须与「探不到」分开（两者处置不同：一个是取值源写错，一个是网络/面被挡）
    assert "SERVED_VERSION=unknown" not in out, (
        f"「探到了、值是空」被报成了「探不到」（unknown）⇒ 两种语义被混桶：\n{out}"
    )
    assert "SERVED_VERSION=mismatch" in out, f"缺机读读数 SERVED_VERSION=mismatch：\n{out}"
    assert "::error::" in out, f"判红没有落成 GitHub 注解（::error::）：\n{out}"
    # 可复制复算命令（同族口径：判红必须可复算）
    assert "curl" in out and "served-version-verify.sh" in out, f"判红缺可复制复算命令：\n{out}"


def test_empty_builtat_is_green_when_not_required():
    """对照臂（**必要性**）：同一场景、**不**要求判 `builtAt` ⇒ 退 0。

    没有它，上面那条「恒红也能过」；而这一条同时钉住「新判据是**opt-in** 的」——
    没接这个面的调用方（如本地手动复探）不会被一条它没要求过的判据误判红。
    """
    with VersionStub(version_body(TARGET_SHA, built_at="")) as stub:
        proc = run_verify(stub.base_url, TARGET_SHA)

    assert proc.returncode == 0, (
        f"未要求判 `builtAt` 却判红 ⇒ 新判据不是 opt-in：\n{proc.stdout}\n{proc.stderr}"
    )
    assert "SERVED_VERSION=match" in proc.stdout


def test_nonempty_builtat_is_green_when_required():
    """对照臂（**判别力**）：要求判 `builtAt`、而它**非空** ⇒ 退 0。

    与上面那条合起来 = 红证的两侧都成立：判据既**会红**、也**能绿**（不是恒定输出）。
    """
    with VersionStub(version_body(TARGET_SHA, built_at="2026-10-16T03:27:11Z")) as stub:
        proc = run_verify(stub.base_url, TARGET_SHA, SERVED_VERSION_REQUIRE_BUILT_AT="1")

    assert proc.returncode == 0, (
        f"`builtAt` 非空却判红 ⇒ 判据过严（会把好部署挡住）：\n{proc.stdout}\n{proc.stderr}"
    )
    assert "SERVED_VERSION=match" in proc.stdout
    assert "2026-10-16T03:27:11Z" in proc.stdout, (
        f"绿档没有把线上 `builtAt` 读数打出来 ⇒ 复算者看不到取值源是否真接上了：\n{proc.stdout}"
    )


def test_deploy_leg_requires_builtat_so_it_cannot_be_a_vacuous_assertion():
    """判据 12 的**接线**面：发布腿必须显式要求判 `builtAt`（否则上面那条判据在 CI 里永不生效）。

    形态：`SERVED_VERSION_REQUIRE_BUILT_AT: '1'` 必须在 served-version 断言步的 `env:` 块里
    （**不是**别的地方 —— 判据生效面 = 那一步）。
    """
    text = workflow_text()
    steps = re.split(r"\n      - name: ", text)
    served = [s for s in steps if s.startswith(f'"{SERVED_STEP}"')]
    assert len(served) == 1, f"期望恰好 1 个 served-version 断言步，实测 {len(served)}"
    assert "SERVED_VERSION_REQUIRE_BUILT_AT: '1'" in served[0], (
        "served-version 断言步没有要求判 `builtAt` ⇒ issue #7015 的具名判据在 CI 里**永不生效**"
        "（`builtAt` 又变回恒真的空断言）"
    )


def test_build_identity_value_source_is_the_runner_clock_not_an_invented_name():
    """🔴 **取值源**（issue #7015 / #7029 的病灶本身）：`BUILT_AT` 必须由 **runner 时钟现算**
    （`date -u +%Y-%m-%dT%H:%M:%SZ`）；**既不许**读未定义的 `GITHUB_*` 变量名，
    **也不许**用猜出来的 `${{ github.<prop> }}`（名字不存在时 Actions 一样解出**空串**）。

    两代病逐字（都实测踩过）：
    · 改前：`echo "BUILT_AT=${GITHUB_RUN_STARTED_AT:-}"` —— 该名字**不是** GitHub 注入的环境变量；
    · #7016：`env: RUN_STARTED_AT: ${{ github.run_started_at }}` —— 该**属性不存在**
      （官方 `github` 上下文属性表 40 个里没有 `run_started_at`）⇒ 真机 env 清单里 `RUN_STARTED_AT:` 为空。
    """
    text = workflow_text()
    assert re.search(r"BUILT_AT=\$\(date -u \+%Y-%m-%dT%H:%M:%SZ\)", text), (
        "解算步没有从 **runner 时钟**现算 `BUILT_AT` ⇒ 取值源仍是某个变量名/属性名"
        "（issue #7015 / #7029 的病灶：猜的名字解出空串而无一物变红）"
    )
    # 取值面（**非注释**行）里一律不许再出现这两个名字 —— 找根因的注释必然会提到它们，
    # 那不是「还在用它」。判据 = 非注释行 grep。
    for name in ("GITHUB_RUN_STARTED_AT", "github.run_started_at"):
        body_offenders = [
            line for line in text.splitlines()
            if name in line and not line.lstrip().startswith("#")
        ]
        assert not body_offenders, (
            f"workflow 的**取值面**里仍出现 `{name}` —— 它**不存在**（issue #7015 / #7029）"
            "⇒ 取值恒为空串而没有任何东西会红：\n" + "\n".join(body_offenders)
        )
    # 解算步必须 fail-closed：取值源为空 ⇒ 具名判红（不许静默写空串），且**点名当前来源**
    assert re.search(r'if \[ -z "\$BUILT_AT" \]', text), (
        "解算步没有「取值源为空 ⇒ 判红」的自检 ⇒ 空值会被静默烘焙进镜像（改前形态）"
    )
    assert "runner 时钟" in text, (
        "取值源自检的报错文案没有**点名当前来源**（本仓口径：判红要能直接指向取值源）"
    )
    # ISO8601 形态自检（`admin-web` 的 Dockerfile 逐字写着「调用方在 workflow 里已 fail-closed 校验过形态」）
    assert re.search(r"\[0-9\]\[0-9\]\[0-9\]\[0-9\]-\[0-9\]\[0-9\]-\[0-9\]\[0-9\]T", text), (
        "解算步没有校验 `BUILT_AT` 的 ISO8601 形态 ⇒ 形态坏掉的时刻会一路烘焙进产物"
    )


def test_workflow_run_bodies_never_expand_undefined_github_env_literals():
    """**类级元守卫**（issue #7015 的固化面）：凡 workflow 的 run 正文里当默认值用的 `GITHUB_*`
    字面量，必须是 GitHub **真的**会注入的环境变量（或已被显式登记为例外）—— 否则判红并具名。

    为什么需要它：`GITHUB_RUN_STARTED_AT` 是**编造的名字**（GitHub 的 run 开始时刻只在 context
    `github.run_started_at` 里）⇒ `… ${GITHUB_RUN_STARTED_AT:-} …` 恒空，而**没有任何东西会红**
    （shell 里未定义变量只是空串）⇒ 缺陷可以活到真机复探才被发现。本条把「编造的 `GITHUB_*` 名」
    变成**编辑期**的具名红。

    边界（照实登记）：① 只扫**字面量**形态（`${{ … }}` 表达式由 Actions 求值，不在射程内）；
    ② 只认注解里的「未定义」这一半 —— 「定义错了」（值是空串）由 `builtAt` 那条实例判据承担；
    ③ 例外表 `GITHUB_ENV_LITERAL_EXEMPTIONS` **只许缩短**（有 fail-closed 自证，见下）。
    """
    import yaml  # 仓内既有依赖（`tests/unit_ci_workflows/test_swas_server_side_build.py` 已在用）

    assert GITHUB_ENV_LITERAL_EXEMPTIONS == {}, (
        "例外表不再为空 —— 有人给某个 `GITHUB_*` 名字加了自定义 env。这不是「不许」，"
        "而是**必须显式复核**：确认那个名字不是「编造的 GitHub 默认变量」再登记（并写理由）；"
        f"现取：{GITHUB_ENV_LITERAL_EXEMPTIONS}"
    )
    assert DEFAULT_GITHUB_ENV_LITERALS, "默认变量白名单被清空了 ⇒ 本判据会退化成恒真（fail-closed）"

    workflows = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    assert len(workflows) >= 10, f"反空跑锚点：workflow 数量异常（{len(workflows)}）⇒ 扫描面可能漂了"
    offenders: list[str] = []
    for wf in workflows:
        for name in sorted(_literal_github_env_defaults(wf)):
            if name in DEFAULT_GITHUB_ENV_LITERALS or name in GITHUB_ENV_LITERAL_EXEMPTIONS:
                continue
            offenders.append(f"{wf.name}::${name}")
    assert not offenders, (
        "下列 `GITHUB_*` 字面量**不是** GitHub 注入的环境变量（编造的名字）⇒ shell 展开恒为空\n"
        "（正是 issue #7015 的病灶：`GITHUB_RUN_STARTED_AT`）⇒ 改用 context 表达式经 `env:` 注入，"
        "或把该名字加进 `GITHUB_ENV_LITERAL_EXEMPTIONS` 并写理由：\n  " + "\n  ".join(offenders)
    )


def test_undefined_github_env_literal_guard_has_teeth(tmp_path):
    """**判别力自证**（注入式）：把 `deploy-admin-api.yml` 的正文喂进同一套判定函数，
    注入一处 `${{ github.run_started_at }}` → `${GITHUB_RUN_STARTED_AT:-}`（= 改前逐字形态）⇒
    判定函数必须**报出这个名字**；未注入的对照臂 ⇒ 不报。

    没有这一条，上面那条守卫可以「因为扫不到任何东西」而恒绿（本仓点名的空跑形态）。
    """
    source = read(WORKFLOW)
    assert "GITHUB_RUN_STARTED_AT: " not in source, (
        "反空跑锚点：本树已修好，注入应以『改前形态』为语料"
    )
    injected = source.replace('echo "BUILT_AT=${BUILT_AT}"', 'echo "BUILT_AT=${GITHUB_RUN_STARTED_AT:-}"')
    assert injected != source, "注入没生效（锚点漂了）⇒ 本自证是空跑"

    victim = tmp_path / "deploy-admin-api.yml"
    victim.write_text(injected, encoding="utf-8")
    found_injected = _literal_github_env_defaults(victim)
    assert "GITHUB_RUN_STARTED_AT" in found_injected, (
        f"注入「编造的 GITHUB_* 名」却**没**被判定函数报出 ⇒ 守卫不具判别力；实得 {sorted(found_injected)}"
    )

    clean = tmp_path / "clean.yml"
    clean.write_text(source, encoding="utf-8")
    assert "GITHUB_RUN_STARTED_AT" not in _literal_github_env_defaults(clean), (
        "对照臂：未注入的本树正文被报出 `GITHUB_RUN_STARTED_AT` ⇒ 判定函数有假阳性"
    )


def test_workflow_yaml_still_parses_after_the_value_source_change():
    """反空跑/形态：改完的 workflow 必须仍是**合法 YAML**，且解算步的 `env:` 真挂在它自己身上。

    改前的三处 `${GITHUB_RUN_STARTED_AT:-…}` 是纯文本改动，不会让 YAML 变坏；本次新增了
    step 级 `env:`（缩进敏感）⇒ 用 YAML 解析把「缩进写错导致 env 挂到别的 step / 整文件坏掉」钉住。
    """
    import yaml

    doc = yaml.safe_load(read(WORKFLOW))
    steps = doc["jobs"]["build-and-deploy"]["steps"]
    resolve = [s for s in steps if s.get("name") == RESOLVE_STEP]
    assert len(resolve) == 1, f"期望恰好 1 个解算步，实测 {len(resolve)}"
    env = resolve[0].get("env") or {}
    assert "RUN_STARTED_AT" not in env, (
        f"解算步仍在用 `env:` 传取值源（实得 {env}）⇒ 那又回到「猜一个名字」的形态"
        "（issue #7015 的 `GITHUB_RUN_STARTED_AT` / #7029 的 `${{ github.run_started_at }}` 都是这么来的）"
    )
    assert "date -u +%Y-%m-%dT%H:%M:%SZ" in resolve[0]["run"], (
        "解算步的取值源不是 runner 时钟（`date -u`）⇒ `builtAt` 仍可能取到空串"
    )
    served = [s for s in steps if s.get("name") == SERVED_STEP]
    assert len(served) == 1, f"期望恰好 1 个 served-version 断言步，实测 {len(served)}"
    assert (served[0].get("env") or {}).get("SERVED_VERSION_REQUIRE_BUILT_AT") == "1", (
        "served-version 断言步的 `env:` 没要求判 `builtAt`（YAML 层读数，与文本判据互为对照）"
    )
    # ── 顺带的形态守卫（本包实测踩到，见 `RESOLVE_STEP` 的注释）────────────────────
    # 未加引号的步名里出现 ` #` ⇒ YAML 把它当**注释起点** ⇒ 名字被**静默截断**
    # （实测：`Resolve build identity (issue #6951）` → `"Resolve build identity (issue"`）
    # ⇒ 任何「按名字取步」的判据会取空、并可能静默空跑。
    truncated = [
        line.strip() for line in read(WORKFLOW).splitlines()
        if re.match(r"^\s*- name:\s*[^\"'\n]\S*\s#", line)
    ]
    assert not truncated, (
        "workflow 里有**未加引号**且含 ` #` 的步名 ⇒ YAML 会把 `#` 之后当注释、名字被静默截断：\n  "
        + "\n  ".join(truncated)
    )

