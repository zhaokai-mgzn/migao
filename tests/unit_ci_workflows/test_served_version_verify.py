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
6. **接线（注入面三处同源）**：`deploy-admin-api.yml`（`BUILD_SHA` / `BUILD_TAG` / `BUILT_AT`）
   → `deploy/swas/deploy.sh`（`MIGAO_BUILD_SHA` 等 `--build-arg`）
   → `backend/admin-api/Dockerfile`（`ARG` + `ENV`）→ `VersionController`（读同名环境变量）。
   任一环改名 ⇒ 具名判红（这是「端点报出的真是这次构建」的必要条件，不是装饰）。
7. **端点的泄露面白名单**：`VersionController` 的响应体**只许**有 5 个非敏感键
   （`app` / `sha` / `tag` / `builtAt` / `servedAt`）⇒ 有人往里塞主机名 / 路径 / 环境变量 / 配置
   就判红（逼一次「它会不会泄露」的复核）。
8. **`/api/version` 落在已放行的路径面**：`SecurityConfig` 的 `permitAll` 必须含它，
   而 `nginx.conf` 必须**仍然**屏蔽 actuator 面 —— 后者是「探活面 ≠ 探版本面」这个前提本身，
   被悄悄放开会让本判据的设计前提消失（也不该顺带把 actuator 详情面暴露出去）。

## 桩的诚实标注（照实登记，§19.1）

- 本文件**不联网**：`/api/version` 由**本进程内**的 `http.server` 提供，脚本以
  `BASE_URL=http://127.0.0.1:<port>` + `SERVED_VERSION_PATH` / `SERVED_VERSION_RETRIES` 驱动。
  ⇒ 本文件证的是「**脚本在给定输入下会做什么**」，**不是**「线上真的会这么回」。
- **未覆盖（照实登记）**：① 线上真机复探（需要一次真实部署，本包**未做**）；
  ② `deploy-frontend.yml` / `deploy-ai-agent-service.yml` 两条腿**未接线**（同形缺口；
  前端那半边还依赖 #6611 的构建期注入面）；③ Java 侧只做**静态接线判据**，
  本包**未**跑 `mvn test`（worktree 无构建产物、且那属于全量档）。
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
        {"app": app, "sha": sha, "tag": tag, "builtAt": built_at,
         "servedAt": "2026-10-16T08:00:00+08:00"}
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


def test_build_identity_wiring_is_same_source_across_four_layers():
    """判据 6：注入面四层同源（少一环 ⇒ 端点报的就不是这次构建，`sha` 会恒为空）。"""
    wf = workflow_text()
    deploy_sh = read(DEPLOY_SH)
    dockerfile = read(DOCKERFILE)
    controller = read(CONTROLLER)

    # ① workflow：解算 build identity 并交给部署步（env 名 → deploy.sh 的变量名）
    assert "id: build_id" in wf, "workflow 没有解算构建身份（git rev-parse HEAD）"
    assert 'echo "BUILD_SHA=$SHA" >> "$GITHUB_OUTPUT"' in wf, "构建身份没有落成 step output"
    for env_name, source in (
        ("BUILD_SHA: ${{ steps.build_id.outputs.BUILD_SHA }}", "step output"),
        ("BUILD_TAG: ${{ steps.tag.outputs.IMAGE_TAG }}", "镜像 tag（与 compose 同源）"),
        ("BUILT_AT: ${{ steps.build_id.outputs.BUILT_AT }}", "部署期时钟"),
    ):
        assert env_name in wf, f"部署步没有把构建身份传下去：{env_name}（来源 {source}）"

    # ② deploy.sh：三个变量 → `--build-arg MIGAO_BUILD_*`
    for var in ("BUILD_SHA", "BUILD_TAG", "BUILT_AT"):
        assert re.search(rf"^{var}=\$\{{{var}:-", deploy_sh, re.M), (
            f"deploy.sh 没有 `${var}` 的入口（`set -u` 下裸引用会当场炸；且会静默丢注入面）"
        )
    for arg in ("MIGAO_BUILD_SHA=${BUILD_SHA:-}", "MIGAO_BUILD_TAG=${BUILD_TAG:-$TAG}",
                "MIGAO_BUILT_AT=${BUILT_AT:-}"):
        assert arg in deploy_sh, f"deploy.sh 没有把 `{arg}` 交给 docker build"

    # ③ Dockerfile：ARG 必须在**两个 stage** 各声明一次（ARG 作用域是 per-stage），
    #    并由 ENV 落到运行时容器（消费面读的是环境变量）
    for name in ("MIGAO_BUILD_SHA", "MIGAO_BUILD_TAG", "MIGAO_BUILT_AT"):
        assert dockerfile.count(f"ARG {name}=") == 2, (
            f"Dockerfile 的 `ARG {name}=` 必须出现 **2** 次（builder + runtime 两个 stage 各一次）"
            f"，实测 {dockerfile.count(f'ARG {name}=')} 次"
        )
        assert f"ENV {name}=${name}" in dockerfile, f"Dockerfile 没有把 `{name}` 落成容器环境变量"

    # ④ 控制器：读的必须是**同名**环境变量（改名 ⇒ 端点报空串 ⇒ 判据恒「探不到」）
    for name in ("MIGAO_BUILD_SHA", "MIGAO_BUILD_TAG", "MIGAO_BUILT_AT"):
        assert f'@Value("${{{name}:}}")' in controller, (
            f"VersionController 没有读环境变量 `{name}`（四层里这一环断了）"
        )


def test_version_endpoint_field_whitelist_blocks_accidental_leaks():
    """判据 7：端点的泄露面 = 5 个非敏感字段；加字段就判红（逼一次安全复核）。"""
    controller = read(CONTROLLER)
    keys = re.findall(r'body\.put\("([^"]+)"', controller)
    assert keys == ["app", "sha", "tag", "builtAt", "servedAt"], (
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
