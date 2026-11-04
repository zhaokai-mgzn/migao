"""「需要本机服务 + 凭据的 e2e 面」的**前置就绪判定**（issue #6160）—— 单一实现。

为什么单独一个模块（而不是写在某个用例文件里）：同一条判定要被**两处**用，各写一份必然漂移 ——

  ① 用例面自己：``tests/test_e2e_mibao_scenarios.py`` 的 skipif —— 未就绪 ⇒ **skip**，
     而不是 20 条 ``failed``（实测：``chat 接口返回非 200：401, detail={"code":"AUTH_REQUIRED"}``）；
  ② 本地门禁：``verify-all.sh`` 的 ``ai-agent-e2e`` 前置（``scripts/ai-agent-e2e-readiness.py``
     现取面清单后调用本函数）—— 未就绪 ⇒ **⏭️ 不计通过** + 一行可行动的「准备」。

**stdlib-only**（不依赖 venv / httpx）：探针侧要能在**没建 venv** 的 worktree 里真去探，
也要能在 CI 的 ``tests/unit_ci_workflows`` job（不装 ai-agent 依赖）里被直接跑。

口径：就绪 ⇒ ``""``；未就绪 ⇒ 一行**可行动**的说明（缺什么 + 怎么准备）。

🔴 **只看「探得通不通」，不看业务断言** —— 探得通之后用例照常跑、照常判红绿；
   真失败**不许**被吞成未就绪（否则本判定会变成掩盖回归的盖子）。
"""
from __future__ import annotations

import http.client
import socket
from urllib import error, request
from urllib.parse import urlsplit


def _is_timeout(exc: BaseException) -> bool:
    """**读超时族**的统一识别（``TimeoutError`` / ``socket.timeout`` / ``URLError(reason=…)``）。

    Python 3.10 起 ``socket.timeout`` 就是 ``TimeoutError``（同一个类）⇒ 判一次即可；
    ``urllib`` 在**连接阶段**才把超时包成 ``URLError``，故先剥一层 ``reason`` 再判。
    """
    if isinstance(exc, error.URLError) and isinstance(exc.reason, BaseException):
        exc = exc.reason
    return isinstance(exc, TimeoutError) or "timed out" in str(exc).lower()


def _read_timeout_reason(endpoint: str, port: int, timeout: float) -> str:
    """**有监听但读超时** ⇒ 未就绪 + 一条能当场执行的出口（issue #8647）。

    为什么不能当「就绪」：端口有监听只证明**进程还在**，回不了包说明它已经不是可用服务
    （实测先例：5 天前的 uvicorn，``/health`` 还能回 200，其它路径接受连接后永不回包）。
    """
    return (
        f"AI Agent Service 在 {endpoint} 有监听但**读超时**"
        f"（{timeout:g}s 内没有任何响应）⇒ 疑似僵而不死的旧进程占着 {port} 端口"
        f"（进程还在、服务已不可用）⇒ 先看是谁占着：`lsof -nP -iTCP:{port} -sTCP:LISTEN`，"
        "确认后 kill 掉它并重启服务，再重跑本档"
    )


def not_ready_reason(endpoint: str, headers: dict, timeout: float = 5.0) -> str:
    """真去探一次 ``endpoint`` —— 返回 ``""``（就绪）或一行可行动的未就绪说明。

    探法是**空体 POST**（``{}``）：该服务的鉴权是 FastAPI 依赖、**先于请求体校验**执行
    （2026-10-03 实测：无凭据 ⇒ 401 AUTH_REQUIRED；凭据被接受 + 空体 ⇒ 422 Field required）
    ⇒ 既能判「凭据被不被接受」，又**不触发 LLM**（不会为一次就绪探测付一次真实对话）。

    分类（**只认「探不通」这一种为未就绪**，其余一律照常跑、由用例判红绿）：

      · 连不上（服务没在跑 / 端口不通）        ⇒ 未就绪
      · **有监听但读超时 / 读不到响应**        ⇒ 未就绪（issue #8647）
      · HTTP 401 / 403（凭据不被接受）        ⇒ 未就绪
      · 其它任何状态（含 422 / 5xx / 200）     ⇒ **就绪**（判不了 ≠ 未就绪；真失败仍由用例判红）

    🔴 **本函数对「传输层探不通」永不抛异常**（issue #8647）：调用点之一是
    ``tests/test_e2e_mibao_scenarios.py`` 的**模块级**判定 ⇒ 抛出的异常会让 pytest 在**收集阶段**
    中止整档（不是跑红、也不是未就绪，报表里什么都看不到）。故 ``OSError`` / ``http.client``
    的整族传输异常一律折成「未就绪 + 一行出口」，**绝不**折成「就绪」或「跳过」。
    """
    parsed = urlsplit(endpoint)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        socket.create_connection((parsed.hostname, port), timeout=3).close()
    except OSError as exc:
        return (
            f"AI Agent Service 未在 {endpoint} 运行（{type(exc).__name__}: {exc}）"
            " ⇒ 先在本机起服务再重跑（见用例文件头部「前提条件」）"
        )
    req = request.Request(
        endpoint,
        data=b"{}",
        method="POST",
        headers={**headers, "Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
    except error.HTTPError as exc:
        status = exc.code
    except error.URLError as exc:
        if _is_timeout(exc):
            return _read_timeout_reason(endpoint, port, timeout)
        return f"chat 端点 {endpoint} 请求失败（{exc.reason}）⇒ 确认服务健康后重跑"
    except (OSError, http.client.HTTPException) as exc:
        # 连接**已建立**、但读不到响应（issue #8647 的病根就是这里此前**没被 catch**）：
        # 读超时 / 对端掐断 / 回了不是 HTTP 的东西 —— 一律「探不通 ⇒ 未就绪」，
        # 不许上抛（上抛 = 收集阶段中止整档），也不许当「就绪」或「跳过」。
        if _is_timeout(exc):
            return _read_timeout_reason(endpoint, port, timeout)
        return (
            f"chat 端点 {endpoint} 有监听但探不通（{type(exc).__name__}: {exc}）"
            f" ⇒ 服务可能僵而不死：确认后 kill 占着 {port} 的旧进程并重启（判不了 ≠ 就绪）"
        )
    if status in (401, 403):
        return (
            f"chat 端点拒绝本用例的凭据：HTTP {status}"
            "（本机服务与用例 HEADERS 里的凭据不一致；实测本机 DEBUG=true 的服务要"
            " X-Debug-Role 或 JWT，而用例只带 X-Service-Token）⇒ 把服务与用例的凭据对齐后重跑"
        )
    return ""
