# case_ids: MC-106
"""**admin-web 发布腿的身份自证必须可判读**（issue #6611 逐字病灶 + #6746 兜底零交付）。

## 病（现取读数，不是推断）

1. **身份判据不具判别力**（issue #6611 逐字）：「`index.html` 字节哈希**跨版本相同**
   （只证 chunk 图，不证部署了哪份代码）」—— 实测应用代码变了、`index.html` 的 sha256
   前后都是 `b1f3a2ef2929ec66`。
2. **HTTP 200 不能证明任何东西**（同族，`deploy/scripts/worker-h5-verify-served.sh` 自己写下的）：
   「200 是**恒真**的（空断言）」—— `deploy/swas/nginx.conf` 的 `location /` 是
   `try_files $uri $uri/ /index.html`，某些路径会**静默回落**到 index.html
   ⇒ **200 + HTML 恰恰是「探不到身份面」的形态**。
3. **schedule 兜底报 success 却零交付**（issue #6746 逐字）：run `38093028269`
   （2026-10-10T22:52:33Z）`conclusion=success` 而整个 job 只跑 **22 秒**，同刻线上 CSS 仍是旧
   的、内容级判据 `primary-50-lit` **0 命中**。判据是「**镜像存在**」而非「**线上是它**」。
4. **改前本腿没有任何版本自证**：`deploy/scripts/admin-web-verify-served.sh` **不存在**；
   `deploy-frontend.yml` 里 version / served-version / verify-served / buildId / NEXT_PUBLIC_BUILD
   逐字**零命中** ⇒ 本单是**从零建**。

## 本文件锁什么

判据本体 = `deploy/scripts/admin-web-verify-served.sh`（同族范式 =
`deploy/scripts/served-version-verify.sh` 的判别力口径：**探线上真正响应的内容**，不是探「推没推」）：

1. **红证（会红才算判据）**：注入一个**错误的期望 sha** ⇒ **退出码 1** + 输出里同时有
   「探到什么 / 期望什么 / 可复制复算命令」三件。
2. **绿（同口径的对照臂）**：期望 sha == 线上 sha ⇒ **退出码 0** + `SERVED_VERSION=match`。
   ⚠️ 没有这一条，「恒红」也能过上面那条 ⇒ 红证本身不成立。
3. **探不到 ⇒ fail-closed**：连不上 / 非 200 / **响应是 HTML（回落）** / body 不是 JSON /
   `sha` 为空或 `unknown`（**老镜像没有构建期注入面** —— 最易退化成空断言的路径）/ `sha` 非 hex /
   `app` 不是 admin-web / 期望 sha 形态不合法 ⇒ **退出码 3**，**不得**当「一致」。
4. **陷阱二的显式处理**：`Content-Type` 是 HTML **或** body 以 `<` 开头 ⇒ 判**探不到**，
   **绝不许**「200 就通过」（判据 3 的 `html_*` 两态即这一条的红证）。
5. **结构判据**：`deploy-frontend.yml` 的通过条件不再可能是「产物/镜像存在」—— 它必须真的调用
   admin-web 的身份探针，且期望值来自本次部署（`github.sha`），退出码**原样透传**
   （不许把 3 归一化成 0）。这类断言步的 `if:` 不许绑在 `steps.sync.outputs.skip` 上，
   必须是 `always()`（跳过档也要探一次 —— 那正是 #6746 的读数面）。
6. **注入面五跳同源**（少一环 ⇒ 身份面报的就不是这次构建）：
   `deploy-frontend.yml`（解算 build identity + 部署步 env）→ **远程调用参数面**
   （`swas-deploy-ci.sh` 的第 9/10 位 `"$BUILD_SHA"` / `"$BUILT_AT"`）→ 驱动脚本的 BOOTSTRAP 渲染
   → `deploy/swas/deploy.sh`（`MIGAO_BUILD_SHA` 等 `--build-arg`）→ `frontend/admin-web/Dockerfile`
   （`ARG` + 构建期写出 `public/version.json`）。任一环改名 / 摘掉 ⇒ 具名判红。
7. **`deployed` 的语义自洽** + schedule 兜底档**显式出声**：`deployed` 必须是 `skip != 'true'`，
   消费侧（探测 job 的 `if:`）随之 `== 'true'`；跳过档必须有 `::notice::` + run summary 的声明步。
   （与 admin-api 腿的 `deploy-admin-api.yml` 同款订正 —— **两处同时翻转** ⇒ 行为等价、读数不再自相矛盾。）

## 桩的诚实标注（照实登记，§19.1）

- 本文件**不联网**：身份面由**本进程内**的 `http.server` 提供，脚本以
  `http://127.0.0.1:<port>` + `ADMIN_WEB_SERVED_PATH` / `ADMIN_WEB_SERVED_RETRIES` 驱动。
  ⇒ 本文件证的是「**脚本在给定输入下会做什么**」，**不是**「线上真的会这么回」。
- **未覆盖（照实登记）**：① **线上真机复探**需要一次真实部署（由集成侧触发；本包**不在真机上跑**）
  —— 这是本条判据的**唯一终判**，命令逐字：
  `bash deploy/scripts/admin-web-verify-served.sh 'https://merchant.migaozn.com' "$(git rev-parse origin/main)"`
  （要求 rc=0 + `SERVED_VERSION=match`）；
  ② 判不了「`docker build` 真的把 `public/version.json` 打进了镜像」（需要一次真构建；静态判据
  只能钉住 Dockerfile 里那段 `RUN` 的形态与默认值）；
  ③ 判不了「Next.js 会把这个文件按原样发出去」（那是框架行为；真机复探才看得见）；
  ④ **另三条静态落地面腿**（`worker-h5` / `bmini-h5` / `c-end-h5`）的身份面**不在本单射程**，
  逐腿清单见本文件末尾的 `test_static_landing_legs_identity_debt_is_ledgered`。

## 实测的线上形态（本包现取，2026-10-16）

`curl -sS -m 12 -o /dev/null -w '%{http_code} %{content_type}' https://merchant.migaozn.com/version.json`
⇒ 逐字 `404 text/html; charset=utf-8`（body = Next 的 404 页）。
⇒ 该 host 上**没有**静默回落到 200+HTML 的形态（这是好消息：200 不是恒真），
但**回落风险照旧是真实的**（`deploy/swas/nginx.conf` 的 `location /` 就是 try_files 回落），
所以脚本把「拿到 HTML ⇒ 判探不到」做成**显式分支**并带红证，而不是靠「这个 host 不会回落」的假设。
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE = REPO_ROOT / "deploy" / "scripts" / "admin-web-verify-served.sh"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-frontend.yml"
ADMIN_API_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-admin-api.yml"
DOCKERFILE = REPO_ROOT / "frontend" / "admin-web" / "Dockerfile"
DEPLOY_SH = REPO_ROOT / "deploy" / "swas" / "deploy.sh"
CI_SCRIPT = REPO_ROOT / "deploy" / "scripts" / "swas-deploy-ci.sh"
NGINX_CONF = REPO_ROOT / "deploy" / "swas" / "nginx.conf"
STATIC_LEGS = {
    "worker-h5": REPO_ROOT / "deploy" / "scripts" / "worker-h5-verify-served.sh",
    "bmini-h5": REPO_ROOT / "deploy" / "scripts" / "bmini-h5-verify-served.sh",
    "c-end-h5": REPO_ROOT / "deploy" / "scripts" / "c-end-h5-verify-served.sh",
}

# 与 CI 的 shell 同形
BASH_SHELL = ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail"]

# 判据 1 的红证锚点（注入一个**错误的期望 sha**）与判据 2 的对照臂
TARGET_SHA = "6f3aec2b8c0d9e1f2a3b4c5d6e7f8091a2b3c4d5"
WRONG_SHA = "deadbee" + "0" * 33
# 构建身份过「CI → 驱动脚本 → 服务器」边界的**实参形态**（issue #6951 的第 5 跳，本腿照做）
BUILD_SHA_ARG = '"$BUILD_SHA"'
BUILT_AT_ARG = '"$BUILT_AT"'
BUILD_TAG_ARG = '"$BUILD_TAG"'
SERVED_STEP = 'Assert served sha == deployed sha (admin-web 线上就是本次构建，issue #6611)'
DECLARE_STEP = 'Declare deployment state (schedule 兜底档，issue #6746)'


def read(path: Path) -> str:
    assert path.is_file(), f"反空跑锚点：文件不存在 → {path}"
    return path.read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════
# 进程内身份面桩：状态码 / Content-Type / body 全部由用例给定（零网络、零外部依赖）
# ══════════════════════════════════════════════════════════════════════════

class _Handler(BaseHTTPRequestHandler):
    status = 200
    body = b""
    content_type = "application/json"

    def do_GET(self):  # noqa: N802（http.server 的协议方法名）
        self.send_response(self.status)
        self.send_header("Content-Type", self.content_type)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):  # 静音（判据输出只留被测脚本自己的读数）
        return


class ProbeStub:
    """起一个只服务身份面的本地 HTTP 桩，供脚本以真实 curl 打它。

    `fallback_to_html=True` 模拟**回落**：任意路径都回 200 + 页面 HTML
    —— 这正是 `nginx try_files … /index.html` 的形态，也是本单的陷阱二。
    """

    def __init__(self, body: bytes = b"", status: int = 200, content_type: str = "application/json",
                 fallback_to_html: bool = False):
        self.body = body
        self.status = status
        self.content_type = content_type
        self.fallback_to_html = fallback_to_html

    def __enter__(self) -> "ProbeStub":
        outer = self
        h_body = (b'<!DOCTYPE html><html lang="zh-CN"><head><title>migao</title></head></html>'
                  if self.fallback_to_html else self.body)
        h_type = "text/html; charset=utf-8" if self.fallback_to_html else self.content_type

        class H(_Handler):
            status = outer.status
            body = h_body
            content_type = h_type

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
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


def identity_body(sha: str, app: str = "admin-web", tag: str = "sha-6f3aec2",
                  built_at: str = "2026-10-16T00:00:00Z") -> bytes:
    return json.dumps(
        {"app": app, "sha": sha, "tag": tag, "builtAt": built_at}
    ).encode("utf-8")


def run_probe(base_url: str, expected: str, **env_extra: str) -> subprocess.CompletedProcess:
    """跑**真脚本**（不是复制一段逻辑来测），只把 BASE_URL / 路径 / 重试参数换成桩。"""
    env = dict(os.environ)
    env.update({
        "ADMIN_WEB_SERVED_RETRIES": "1",
        "ADMIN_WEB_SERVED_RETRY_DELAY": "0",
        "ADMIN_WEB_SERVED_PATH": "/version.json",
        # 桩上没有 CI 变量；显式清掉以免「本机跑」与「CI 跑」不同形
        "GITHUB_SHA": "",
    })
    env.update(env_extra)
    return subprocess.run(
        BASH_SHELL + [str(PROBE), base_url, expected],
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
    with ProbeStub(identity_body(TARGET_SHA)) as stub:
        proc = run_probe(stub.base_url, WRONG_SHA)

    assert proc.returncode == 1, (
        "注入错误期望 sha 却**没有**判红 ⇒ 判据不具判别力（正是 issue #6611 的形态）\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    out = proc.stdout
    assert TARGET_SHA in out, f"判红输出里没有**实测** sha（探到什么）：\n{out}"
    assert WRONG_SHA in out, f"判红输出里没有**期望** sha：\n{out}"
    assert "admin-web-verify-served.sh" in out, f"判红输出里没有可复制复算命令：\n{out}"
    assert "curl" in out, f"判红输出里没有可直接粘贴的 curl 复算命令：\n{out}"
    assert "SERVED_VERSION=mismatch" in out, f"缺机读读数 SERVED_VERSION=mismatch：\n{out}"
    assert "::error::" in out, f"判红没有落成 GitHub 注解（::error::）：\n{out}"


def test_served_sha_match_is_green_control_arm():
    """对照臂：同一场景、只把期望 sha 换回真的 ⇒ 退出码 0 + `SERVED_VERSION=match`。

    ⚠️ 这一条是红证的**必要性对照**：没有它，「恒红」也能过上面那条 ⇒ 红证本身不成立。
    """
    with ProbeStub(identity_body(TARGET_SHA)) as stub:
        proc = run_probe(stub.base_url, TARGET_SHA)

    assert proc.returncode == 0, f"期望 sha 与线上一致却判红：\n{proc.stdout}\n{proc.stderr}"
    assert "SERVED_VERSION=match" in proc.stdout
    assert "SERVED_VERSION=mismatch" not in proc.stdout


def test_full_sha_from_identity_face_matches_seven_char_tag_prefix():
    """身份面报 40 位、镜像 tag 是 7 位 ⇒ 比前 7 位（本仓全链路既有口径），不许因位宽不同误红。"""
    with ProbeStub(identity_body(TARGET_SHA)) as stub:
        proc = run_probe(stub.base_url, TARGET_SHA[:7])

    assert proc.returncode == 0, f"7 位期望 sha 与 40 位实测 sha 同源却判红：\n{proc.stdout}"


# ══════════════════════════════════════════════════════════════════════════
# 判据 3 / 4：探不到 ⇒ 退出码 3（fail-closed，**绝不当绿**）+ 回落显式处理
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "name, stub_kwargs, expected_sha, expect_recompute_cmd",
    [
        ("sha 为空（老镜像没有构建期注入面）", {"body": identity_body("")}, TARGET_SHA, True),
        ("sha 是 unknown（--build-arg 没过边界）",
         {"body": identity_body("unknown")}, TARGET_SHA, True),
        ("响应是 HTML（回落）", {"fallback_to_html": True}, TARGET_SHA, True),
        ("Content-Type 是 text/html 但 body 是 JSON（撒谎的响应）",
         {"body": identity_body(TARGET_SHA), "content_type": "text/html"}, TARGET_SHA, True),
        ("body 不是 JSON", {"body": b"<!DOCTYPE html><html>404</html>"}, TARGET_SHA, True),
        ("HTTP 404（身份面不存在 / 容器没起）", {"body": b"", "status": 404}, TARGET_SHA, True),
        ("HTTP 503（滚动重启中）", {"body": b"", "status": 503}, TARGET_SHA, True),
        ("sha 不是 hex（形态不符）", {"body": identity_body("not-a-sha")}, TARGET_SHA, True),
        ("app 不是 admin-web", {"body": identity_body(TARGET_SHA, app="ai-agent")}, TARGET_SHA, True),
        # 这两条坏的**是期望值本身**（判据的前置没成立）⇒ 给复算命令是无意义的
        # （"再跑一次同一个坏期望" 不解决问题）⇒ 它们只要求三态正确 + 机读读数正确。
        ("期望 sha 形态不合法", {"body": identity_body(TARGET_SHA)}, "not-a-sha", False),
        ("期望 sha 太短（<7 位）", {"body": identity_body(TARGET_SHA)}, "6f3aec", False),
    ],
)
def test_unverifiable_is_exit_3_never_green(name, stub_kwargs, expected_sha, expect_recompute_cmd):
    """「探不到」必须长得像「探不到」：退 3 + `SERVED_VERSION=unknown`，**不得**退 0。

    🔴 其中两条是**本判据最容易退化成空断言**的路径：
    · 「sha 为空 / unknown」—— 老镜像、或构建身份没过「CI→驱动脚本→服务器」边界时，
      把空值当绿会让判据在每一次「镜像没换」的部署上悄悄通过（issue #6951 的真机形态）；
    · 「响应是 HTML」—— HTTP 200 + 页面 HTML 是 nginx `try_files` 回落的形态，
      把 200 当通过就是本单陷阱二的空断言。
    """
    env_extra = {"ADMIN_WEB_SERVED_APP": "admin-web"}
    with ProbeStub(**stub_kwargs) as stub:
        proc = run_probe(stub.base_url, expected_sha, **env_extra)

    assert proc.returncode == 3, (
        f"[{name}] 期望 fail-closed(3)，实际 {proc.returncode} ⇒ 「取不到」被当成了别的语义\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert "SERVED_VERSION=unknown" in proc.stdout, f"[{name}] 缺机读读数 SERVED_VERSION=unknown"
    assert "SERVED_VERSION=match" not in proc.stdout, f"[{name}] 探不到却报了 match"
    if expect_recompute_cmd:
        assert "admin-web-verify-served.sh" in proc.stdout, f"[{name}] 探不到时没给可复制复算命令"


def test_unreachable_endpoint_is_exit_3():
    """连不上（端口没人听）⇒ 退 3（不是 0、也不是 1）。"""
    port = free_port_that_is_closed()
    proc = run_probe(f"http://127.0.0.1:{port}", TARGET_SHA)

    assert proc.returncode == 3, f"连不上应判「探不到」(3)，实际 {proc.returncode}:\n{proc.stdout}"
    assert "SERVED_VERSION=unknown" in proc.stdout
    assert "curl -sS" in proc.stdout, "「探不到」时也要给可直接粘贴的复算命令"


def test_probe_reports_html_fallback_and_never_passes_on_status_200_alone():
    """陷阱二的正向红证：**200 + HTML** 必须判探不到，且输出里点出「回落」而不是「sha 为空」。

    为什么单列一条（判据 3 的参数化里已有 `fallback_to_html`）：这条还断言**具名理由**——
    「探不到」的原因写错（写成「sha 为空」）会把排查引向「构建身份没注入」，
    而真因是「这个路径回落到页面了」，处置完全不同。
    """
    with ProbeStub(b"", fallback_to_html=True) as stub:
        proc = run_probe(stub.base_url, TARGET_SHA)

    assert proc.returncode == 3, (
        f"200 + HTML（回落形态）没有被判「探不到」⇒ 200 又被当成了证据（陷阱二）\n{proc.stdout}"
    )
    assert "SERVED_VERSION=match" not in proc.stdout
    assert "HTML" in proc.stdout, f"探不到的理由没有点名 HTML / 回落：\n{proc.stdout}"


# ══════════════════════════════════════════════════════════════════════════
# 判据 5：发布腿的**结构**判据（通过条件不再可能是「产物存在」）
# ══════════════════════════════════════════════════════════════════════════

def _step_body(text: str, name: str) -> str:
    """取一个 step 的正文（`- name:` 到下一个 `- name:`）。取不到 ⇒ **显式失败**（不是空跑）。"""
    steps = re.split(r"\n      - name: ", text)
    hits = [s for s in steps if s.startswith(f'"{name}"')]
    assert len(hits) == 1, f"期望恰好 1 个名为 {name!r} 的 step，实测 {len(hits)}"
    return hits[0]


def test_deploy_leg_asserts_served_sha_not_artifact_existence():
    """判据 5：发布腿必须**真的**断言「线上 sha == 本次部署的 sha」，且期望值来自本次部署。"""
    text = read(WORKFLOW)
    assert SERVED_STEP in text, "部署腿里没有 admin-web 的 served-sha 断言步 ⇒ 通过条件仍停在「产物存在」"
    assert "deploy/scripts/admin-web-verify-served.sh" in text, (
        "没有调用本仓的身份探针本体 ⇒ 要么判据缺失、要么被内联复制（两条都不许）"
    )
    assert "EXPECTED_SHA: ${{ github.sha }}" in text, (
        "期望 sha 不是本次部署的 commit ⇒ 判据比的是别的东西（issue #6554 的形态）"
    )
    assert 'exit "$rc"' in text, "served-sha 断言没有把退出码原样透传 ⇒ 三态会退化成两态"
    assert "rc=$?" in text, "没有捕获探针的退出码 ⇒ `exit \"$rc\"` 无从依据"


def test_served_assertion_never_keys_pass_on_artifact_existence():
    """判据 5（类级形态）：served-sha 断言的**生效条件**不得绑在「产物/结论」面上。

    允许 `steps.sync.outputs.skip` 继续决定「**要不要构建/部署**」（那是省算力，不是判据）；
    不允许它出现在 served-sha 断言的 `if:` 里 —— 一旦有人把它改成
    `if: steps.sync.outputs.skip != 'true'`（= 跳过档不验证），当场判红。
    """
    body = _step_body(read(WORKFLOW), SERVED_STEP)
    if_match = re.search(r"^\s*if:\s*(.+)$", body, re.M)
    assert if_match, "served-sha 断言步没有 `if:` ⇒ 无法判定它在哪条路径上生效"
    condition = if_match.group(1)
    assert "steps.sync.outputs.skip" not in condition, (
        "served-sha 断言的生效条件绑在 `steps.sync.outputs.skip` 上 ⇒ "
        "跳过档（schedule 兜底）就不再验证线上是不是目标构建 —— 那正是 issue #6746 的形态"
    )
    assert "always()" in condition, (
        f"served-sha 断言不是 `always()` ⇒ 可能在跳过档整步不跑（实测条件：{condition}）"
    )


def test_schedule_skip_path_declares_that_nothing_was_delivered():
    """判据 7：schedule 兜底档（skip=true ⇒ 本轮未部署）必须**显式出声**，不得静默 success。"""
    text = read(WORKFLOW)
    assert DECLARE_STEP in text, (
        "没有「本轮未部署 ⇒ 没有发生任何交付」的声明步 ⇒ 22 秒的 success 仍会被读成「已交付」（#6746）"
    )
    assert "::notice::" in text, "声明步没有落成可见注解（::notice::）"
    assert "本轮**未部署**" in text, "声明步没有逐字写出「本轮未部署」"
    assert "GITHUB_STEP_SUMMARY" in text.split(DECLARE_STEP, 1)[1], (
        "声明步没有落 run summary ⇒ 只活在日志里（会被截断）"
    )
    # `deployed` 的语义必须自洽（与 admin-api 腿同款订正；两处同时翻转 ⇒ 行为等价）
    assert "deployed: ${{ steps.sync.outputs.skip != 'true' }}" in text, (
        "`deployed` 仍写成 `steps.sync.outputs.skip` ⇒ 名字与含义相反（本轮未部署却报 deployed=true）"
    )
    probe_if = re.search(r"needs: build-and-deploy\n(?:.*\n)*?\s*if: (.+)$", text, re.M)
    assert probe_if and "deployed == 'true'" in probe_if.group(1), (
        "探测 job 的条件与订正后的 `deployed` 语义不一致（两处必须同时翻转）"
    )
    # 与本仓既有同族腿一致：admin-api 也是这两条形态（防「只改了一条腿」）
    api = read(ADMIN_API_WORKFLOW)
    assert "deployed: ${{ steps.sync.outputs.skip != 'true' }}" in api, (
        "admin-api 腿的 `deployed` 语义与前端腿不再同形 ⇒ 两腿读数口径分裂"
    )


# ══════════════════════════════════════════════════════════════════════════
# 判据 6：注入面五跳同源（跨「CI → 驱动脚本 → 服务器」边界）
# ══════════════════════════════════════════════════════════════════════════

def test_build_identity_wiring_is_same_source_across_five_hops():
    """判据 6：注入面从「本次部署的 sha」到「身份面读到的那个值」共 **5 跳**，断任何一跳 ⇒
    身份面报的就不是这次构建（sha 为 `unknown` ⇒ 探针判「探不到」）。

    | 跳 | 载体 | 逐字形态 |
    |---|---|---|
    | 1 | `deploy-frontend.yml` 解算 build identity + 部署步 env | `id: build_id` · `BUILD_SHA=$SHA` · 三项 env |
    | **2** | **workflow 的远程调用**（`swas-deploy-ci.sh` 的第 9/10 个位置参数） | `admin-web "$BUILD_SHA" "$BUILT_AT"` |
    | **3** | **驱动脚本的 BOOTSTRAP**（`export …;` 串 + `__PLACEHOLDER__` 渲染点） | `BUILD_SHA=__BUILD_SHA__ BUILT_AT=__BUILT_AT__` + 显式渲染 |
    | 4 | `deploy/swas/deploy.sh` | `BUILD_SHA=${BUILD_SHA:-}` → `--build-arg MIGAO_BUILD_SHA=${BUILD_SHA:-}` |
    | 5 | `frontend/admin-web/Dockerfile` | `ARG MIGAO_BUILD_SHA=` → 构建期写出 `public/version.json` |

    🔴 **跳 2 / 3 是 issue #6951 在 admin-api 腿上踩出来的真机缺陷**（构建发生在**服务器上**，
    而 `BUILD_SHA` 只落在 runner 的步骤 env 里 ⇒ 远端读到空串）—— 本腿**照同一范式接**，不发明新机制。
    """
    wf = read(WORKFLOW)
    ci = read(CI_SCRIPT)
    deploy_sh = read(DEPLOY_SH)
    dockerfile = read(DOCKERFILE)

    # ① 跳 1 — workflow：解算 build identity 并交给部署步
    assert "id: build_id" in wf, "workflow 没有解算构建身份（git rev-parse HEAD）"
    assert 'echo "BUILD_SHA=$SHA" >> "$GITHUB_OUTPUT"' in wf, "构建身份没有落成 step output"
    for env_name, source in (
        ("BUILD_SHA: ${{ steps.build_id.outputs.BUILD_SHA }}", "step output"),
        ("BUILD_TAG: ${{ steps.tag.outputs.IMAGE_TAG }}", "镜像 tag（与 compose 同源）"),
        ("BUILT_AT: ${{ steps.build_id.outputs.BUILT_AT }}", "部署期时钟"),
    ):
        assert env_name in wf, f"部署步没有把构建身份传下去：{env_name}（来源 {source}）"

    # ② 跳 2 — 远程调用必须过**参数面**（不是只留在 runner 的步骤 env）
    call = re.search(r"bash deploy/scripts/swas-deploy-ci\.sh \\\n((?:.*\\\n)*.*)", wf)
    assert call, "workflow 里找不到 `swas-deploy-ci.sh` 的调用（判据锚点已漂移）"
    call_args = call.group(1).replace("\\\n", " ").split()
    assert "admin-web" in call_args, f"远程调用里找不到服务键（判据锚点已漂移）：{call_args}"
    for token in (BUILD_SHA_ARG, BUILT_AT_ARG):
        assert token in call_args, (
            f"workflow 的远程调用**没有把构建身份交给驱动脚本**（实参缺 {token}）⇒ "
            "这一跳就是 issue #6951 的病根：构建发生在**服务器上**，身份只活在 runner 的步骤 env 里"
            " ⇒ 远端读到空串 ⇒ 身份面的 sha 是 unknown ⇒ 探针只能判「探不到」"
        )
    assert BUILD_TAG_ARG not in call_args, (
        f"`{BUILD_TAG_ARG}` 被当实参传了 —— 它**有意**不走参数面（远端 `TAG` = 镜像 tag 已是同一个值），"
        "再送一份就是第二条会漂的口径"
    )

    # ③ 跳 3 — 驱动脚本：模板带占位符 + 从参数面读 + 显式渲染 + 未渲染即 fail-closed
    for ph in ("BUILD_SHA", "BUILT_AT"):
        assert f"{ph}=__{ph}__" in ci, (
            f"BOOTSTRAP 没有把 `{ph}` 送往远端（`export …;` 串里没有占位符 `__{ph}__`）"
            " ⇒ 远端 `deploy.sh` 读到空串 ⇒ 身份面那两个字段是 unknown"
        )
        assert re.search(rf"out=\$\{{out//__{ph}__/\$\{{", ci), (
            f"占位符 `__{ph}__` 没有在 `render_bootstrap` 里被**显式渲染**"
            " ⇒ 纯文本断言会被「模板里有占位符、渲染点却空转」骗过"
        )
    assert re.search(r"\*__BUILD_SHA__\*", ci) or re.search(r"\|\s*\*__BUILD_SHA__\*", ci), (
        "渲染后没有把 `__BUILD_SHA__` 列入未替换即 fail-closed 的自证 ⇒ 漏渲染会被静默发给远端"
    )

    # ④ 跳 4 — deploy.sh：三个变量 → `--build-arg MIGAO_BUILD_*`
    for var in ("BUILD_SHA", "BUILD_TAG", "BUILT_AT"):
        assert re.search(rf"^{var}=\$\{{{var}:-", deploy_sh, re.M), (
            f"deploy.sh 没有 `${var}` 的入口（`set -u` 下裸引用会当场炸；且会静默丢注入面）"
        )
    for arg in ("MIGAO_BUILD_SHA=${BUILD_SHA:-}", "MIGAO_BUILD_TAG=${BUILD_TAG:-$TAG}",
                "MIGAO_BUILT_AT=${BUILT_AT:-}"):
        assert arg in deploy_sh, f"deploy.sh 没有把 `{arg}` 交给 docker build"

    # ⑤ 跳 5 — Dockerfile：ARG **必须存在** + 构建期把身份写进 public/version.json
    #    （这是「admin-web 也声明了这三个 ARG」的唯一机械证据：改前它一个都没声明，
    #      docker 对未声明的 `--build-arg` **静默忽略** ⇒ 身份面不存在也不会报错）
    for name in ("MIGAO_BUILD_SHA", "MIGAO_BUILD_TAG", "MIGAO_BUILT_AT"):
        assert f"ARG {name}=" in dockerfile, (
            f"admin-web 的 Dockerfile 没有声明 `{name}` ⇒ `--build-arg` 被 docker **静默忽略**"
            " ⇒ 构建期身份写不进产物（空注入面）"
        )
    assert "public/version.json" in dockerfile, (
        "Dockerfile 没有把身份写成 `public/version.json`（Next 的静态面）⇒ 线上探不到身份面"
    )
    assert '"app":"admin-web"' in dockerfile, "身份面没有写 app 标识 ⇒ 探针的 `app` 判据无从比对"
    # 默认值必须是**探针会判「探不到」**的值（不是空串、不是任何 hex）
    assert "ARG MIGAO_BUILD_SHA=unknown" in dockerfile, (
        "MIGAO_BUILD_SHA 的默认值不是 `unknown` ⇒ 未注入时可能退化成「空 == 空 ⇒ 绿」的空断言"
    )
    assert 'case "$MIGAO_BUILD_SHA" in *[!0-9a-f]*) MIGAO_BUILD_SHA=unknown' in dockerfile, (
        "Dockerfile 没有把非 hex / 过短的 sha 规范化成 `unknown` ⇒ 身份面可能自报畸形值"
    )


# ══════════════════════════════════════════════════════════════════════════
# 类级（§23）：另三条静态落地面腿的身份面债务必须**登记在案**（会红）
# ══════════════════════════════════════════════════════════════════════════

def test_static_landing_legs_identity_debt_is_ledgered():
    """类级判据：另三条静态落地面腿（`worker-h5` / `bmini-h5` / `c-end-h5`）用的仍是
    「线上字节 == 本仓产物」的身份判据 —— issue #6611 已逐条核过它们的**判别力**：

    | 腿 | 身份判据比的对象 | 判别力 |
    |---|---|---|
    | `bmini-h5` | `index.html` 的 sha256 | ❌ 跨版本相同（#6611 实测 `b1f3a2ef2929ec66` 前后一致）|
    | `c-end-h5` | `index.html` 的 sha256 | ❌ 同形态 |
    | `worker-h5` | `index.html` + `app.js` 的 sha256 | ⚠️ 略强（多比 `app.js`），按需加载的分块仍不覆盖 |

    🔴 本单**只修 admin-web 一条腿**（写面与验收面都在 `deploy-frontend.yml`）；另三条腿
    **不在本单射程**。本判据的作用 = **让「还有三条腿同形」这件事进不了「已解决」的错觉**：
    三条腿的脚本必须**仍然存在且确实比对字节哈希** ⇒ 哪天有人把它们改成有判别力的身份面，
    本判据当场判红、逼一次「三类清单/PR body 要同步更新」的复核。
    （它们各自的修法是独立单，见 PR body 的「未固化项」。）
    """
    for leg, path in STATIC_LEGS.items():
        text = read(path)
        assert re.search(r"sha256|file_sha256", text), (
            f"{leg}: 该腿的身份判据不再是字节哈希形态 ⇒ 本清单已过期（更新清单 + PR body 的类级节）"
        )
        assert re.search(r"\bindex\.html\b", text), (
            f"{leg}: 该腿不再比对 index.html ⇒ 本清单已过期（更新清单 + PR body 的类级节）"
        )
    # admin-web 的这一条**必须不再是字节哈希形态**（否则本单等于没修）。
    # ⚠️ 只扫**代码行**（剥掉 `#` 起的行尾注释）：脚本头部/正文里**必须**能写出「index.html
    #    字节哈希跨版本相同」这句病灶说明（那是判据的由来），把它算成违规就是判据咬自己的文案。
    probe_code = "\n".join(
        line.split("#", 1)[0] for line in read(PROBE).splitlines()
    )
    assert "index.html" not in probe_code, (
        "admin-web 的身份探针的**代码**里仍然出现 index.html ⇒ 又把「跨版本相同的字节哈希」当成身份判据了"
    )
    # 陷阱二的形态也要在 nginx 侧登记：`location /` 若出现 `try_files … /index.html`，
    # 那么「200 + HTML」这种回落形态就是**可达的**（探针必须显式处理它 —— 见判据 3/4）
    nginx = read(NGINX_CONF)
    assert re.search(r"try_files \$uri \$uri/ /index\.html;", nginx), (
        "nginx 的静态落地腿回落形态不见了 ⇒ 本判据的前提（200 可能配 HTML）变了，停下来复核"
    )


# ══════════════════════════════════════════════════════════════════════════
# 脚本自身形态守卫（反空跑 + `bash -n`）
# ══════════════════════════════════════════════════════════════════════════

def test_shared_script_is_executable_and_self_describing():
    """反空跑 + 可执行：脚本必须带 shebang、可执行位、三态机读读数齐备。"""
    assert PROBE.is_file(), "判据本体脚本不存在"
    text = read(PROBE)
    assert text.startswith("#!/usr/bin/env bash"), "缺 shebang"
    mode = PROBE.stat().st_mode
    assert mode & 0o111, f"脚本不可执行（mode={oct(mode)}）⇒ CI 里 `bash <path>` 之外的形式会失败"
    for anchor in ('SERVED_VERSION=match', 'SERVED_VERSION=mismatch', 'SERVED_VERSION=unknown'):
        assert anchor in text, f"缺机读读数 {anchor}（下游消费面会失去三态区分）"


def test_shared_script_parses_and_has_no_unquoted_cjk_adjacent_expansion():
    """`bash -n` + **中文紧贴裸变量**的形态守卫（同族脚本实测踩过）。

    🔴 实测（同族 `served-version-verify.sh` 的第一版）：中文全角括号紧跟 `$EXPECTED`
    ⇒ bash 把 `（` 的字节并进**变量名** ⇒ `set -u` 下报 unbound variable，
    而真正的坏点在**几行之外**（诊断成本极高）。同一形态还能造成未闭合引号（整段被吞）。
    """
    text = read(PROBE)
    syntax = subprocess.run(BASH_SHELL[:1] + ["-n", str(PROBE)],
                            capture_output=True, text=True, timeout=60)
    assert syntax.returncode == 0, f"脚本语法不过 `bash -n`：\n{syntax.stderr}"

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
