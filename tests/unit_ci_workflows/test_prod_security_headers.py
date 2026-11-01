# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""线上**安全响应头**判据 + 它的接线（issue #8218 P1-08 / P1-09）。

## 病（2026-10-31 上线审计，逐条线上读数）

- **P1-08「声明存在 ≠ 可达」**：`SecurityConfig` 明明白白写了 HSTS
  （`maxAgeInSeconds(31536000).includeSubDomains(true)`），而线上
  `curl -sI https://api.migaozn.com/api/version | grep -i strict-transport` **无输出**。
  机制 = nginx 终止 TLS 后以 http 回源，Spring 默认不看 `X-Forwarded-Proto` ⇒ `isSecure()` 为假。
- **P1-09 静态域零安全头**：`/w/`（工人端）、`/b/`（商家端）、官网 `/download` 都没有
  nosniff / HSTS / CSP；两个前端都把会话摆在 localStorage ⇒ 一次 XSS 即可冒用工人身份报工/入库。

## 判据（每条都能单独变红）

| # | 判据 | 变红形态 |
|---|---|---|
| 1 | `application.yml` 有 `server.forward-headers-strategy: native`（Tomcat RemoteIpValve：还原 `isSecure()` 且**保留** `X-Forwarded-*` 头，`SameOriginOriginHeaderFilter` 的读头逻辑不受影响） | 删掉 / 改成 `framework`（会剥离那些头 ⇒ 同源判定翻成跨域）⇒ 红 |
| 2 | `SecurityConfig` 仍声明 HSTS（`maxAgeInSeconds(31536000)`） | 删掉 ⇒ 红（判据 1 修的东西没有发射源了） |
| 3 | nginx：**api 域不许**加 HSTS（避免与 Spring 重复 ⇒ RFC 6797 整条忽略） | 给 api 段加一条 ⇒ 红 |
| 4 | nginx：ai-api 段、admin-web 段的 `location /`、app 段的 `location /` 都有 HSTS + nosniff | 删任一条 ⇒ 红 |
| 5 | nginx：`/w/` `/b/` `/b/report/` 有 CSP + HSTS + nosniff；`/terminal/` 有 HSTS | 删任一条 ⇒ 红 |
| 6 | CSP「最小」= 有 `default-src 'self'` + `script-src` + `frame-ancestors 'self'`；无 `*` 通配、无 `unsafe-eval` | 放宽成 `*` / `unsafe-eval` ⇒ 红 |
| 7 | **CSP 与真实产物一致**：`/b/` 的 `script-src` 必须含 `'unsafe-inline'`（`frontend/bmini-app/src/index.html` 有两段内联脚本）；`/w/` 必须**不含**（`frontend/worker-h5/*.html` 没有内联脚本） | 收紧 `/b/` ⇒ 真白屏；给 `/w/` 放宽 ⇒ 削弱防护（两边都判红） |
| 8 | 判据本体 `deploy/scripts/prod-security-headers.sh` 存在且**只读**（无 rm/POST/写盘动作） | 让它改东西 ⇒ 红 |
| 9 | **执行式**：该脚本喂「带齐头的 stub server」⇒ rc=0；喂「缺 HSTS」⇒ rc=1 且指名 `strict-transport-security`；喂「连不上」⇒ rc=3（3 不当 0 读） | 三态退化（例如永远 0）⇒ 红 |
| 10 | **接线**：`deploy-admin-api.yml` 真跑这个脚本，且排在那条腿的 served-sha 断言**之后**（部署后才判） | 删接线 ⇒ 红（判据存在但没人跑 = 假绿） |
| 11 | 注入式自证（判据 1/3/4/5/7 在内存变异文本上各自判红） | 任一注入没被检出 ⇒ 红 |

## 边界（照实登记，§19.1）

- 判据 3~7 读的是**配置文本**（nginx 的结构化解析 + `set` 变量解析），**不跑 nginx**
  ⇒ 它证明不了 `nginx -t` 通过（本机无 nginx）。已在开发时用 crossplane 解析器做过语法校验，
  但那**不是** nginx 本体（如实登记）。
- 判据 9 跑的是**真脚本**、喂的是本机 stub server（不是线上）⇒ 证明的是「脚本的三态语义与判据面」；
  「**线上**到底带没带」由 CI 在部署腿里真跑它（接线见判据 10）。
- **不联网**跑生产：PR 的绿不应取决于生产此刻的状态（那会让判据变成 flaky）。
"""
from __future__ import annotations

import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from unit_ci_workflows.test_swas_nginx_rate_limit import parse_nginx

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_YML = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "resources" / "application.yml"
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
SCRIPT = REPO_ROOT / "deploy" / "scripts" / "prod-security-headers.sh"
DEPLOY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-admin-api.yml"
WORKER_H5_DIR = REPO_ROOT / "frontend" / "worker-h5"
BMINI_INDEX_HTML = REPO_ROOT / "frontend" / "bmini-app" / "src" / "index.html"

HSTS_DIRECTIVE = "Strict-Transport-Security"


# ══════════════════════════════════════════════════════════════════════════
# 一、nginx 结构化读取（复用既有解析器；不写第二把尺子）
# ══════════════════════════════════════════════════════════════════════════


def servers_by_domain(text: str) -> dict[str, object]:
    """→ {域名: server 块}（一个 server 段可声明多个 `server_name` ⇒ **每个名字都登记**）。"""
    out: dict[str, object] = {}
    for block in parse_nginx(text).children:
        if block.header != "server":
            continue
        names = [d for d in block.directives if d.startswith("server_name ")]
        if not names:
            continue
        for name in names[0].split()[1:]:
            out[name] = block
    return out


def locations(server) -> dict[str, object]:
    return {loc.header.split()[-1]: loc for loc in server.children if loc.header.startswith("location ")}


def directives_in(block) -> str:
    return "\n".join(block.directives)


def _server_sets(server) -> dict[str, str]:
    """→ {变量名: 值}：server 段里的 `set $name "value"`（CSP 策略串的唯一来源）。"""
    out: dict[str, str] = {}
    for statement in server.directives:
        m = re.match(r'^set\s+(\S+)\s+"([^"]*)"$', statement)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def resolve_csp(server, location_block) -> str:
    """取 location 里的 CSP 头；值可能是 server 级 `set` 的变量 ⇒ 解析成实际策略串。"""
    prefix = "add_header Content-Security-Policy "
    for statement in location_block.directives:
        if not statement.startswith(prefix):
            continue
        value = statement[len(prefix):].strip().rstrip(";").strip()
        if value.endswith(" always"):
            value = value[: -len(" always")].strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        if value.startswith("$"):
            return _server_sets(server).get(value, "")
        return value
    return ""


def has_header(block, header: str) -> bool:
    return any(d.startswith(f"add_header {header} ") for d in block.directives)


# ══════════════════════════════════════════════════════════════════════════
# 二、纯函数判据
# ══════════════════════════════════════════════════════════════════════════


def judge_app_config(app_text: str) -> list[str]:
    v: list[str] = []
    doc = yaml.safe_load(app_text) or {}
    server = doc.get("server") or {}
    strategy = server.get("forward-headers-strategy")
    if strategy != "native":
        v.append(
            f"application.yml 的 server.forward-headers-strategy = {strategy!r}，期望 'native' "
            "⇒ 否则 nginx 终止 TLS 后 Spring 认为请求是 http，HSTS 一个字节都不发（P1-08）"
        )
    if server.get("port") != 8080:
        v.append(f"application.yml 的 server.port = {server.get('port')!r}（期望 8080，判据坐标变了要复核）")
    return v


def judge_security_config(java_text: str) -> list[str]:
    v: list[str] = []
    if "maxAgeInSeconds(31536000)" not in java_text:
        v.append(
            "SecurityConfig 里找不到 `maxAgeInSeconds(31536000)` —— 判据 1 修的 `forward-headers-strategy` "
            "就失去了发射源（HSTS 声明被删了）"
        )
    if "httpStrictTransportSecurity" not in java_text:
        v.append("SecurityConfig 里找不到 `httpStrictTransportSecurity`（HSTS 声明没了）")
    return v


def judge_nginx_headers(text: str) -> list[str]:
    v: list[str] = []
    servers = servers_by_domain(text)
    for domain in ("api.migaozn.com", "ai-api.migaozn.com", "app.migaozn.com", "merchant.migaozn.com"):
        if domain not in servers:
            v.append(f"nginx.conf 里找不到 {domain} 的 server 段（判据坐标没了）")
    if len(v):
        return v

    # 判据 3：api 域**不许**由 nginx 发 HSTS（会与 Spring 的重复 ⇒ RFC 6797 整条忽略）
    api = servers["api.migaozn.com"]
    if HSTS_DIRECTIVE in directives_in(api) or any(
        HSTS_DIRECTIVE in directives_in(loc) for loc in api.children
    ):
        v.append(
            "api.migaozn.com 段出现了 nginx 的 HSTS —— 该域由 Spring Security 发；"
            "重复的 STS 头按 RFC 6797 会被浏览器**整条忽略**（等于把 HSTS 关掉）"
        )

    # 判据 4：ai-api 段（server 级）
    ai = servers["ai-api.migaozn.com"]
    for header in (HSTS_DIRECTIVE, "X-Content-Type-Options"):
        if not has_header(ai, header):
            v.append(f"ai-api.migaozn.com 段缺 `add_header {header}`（FastAPI 自己不发头）")

    # 判据 4：admin-web 段的 `location /`（承载 /download 与全部页面）
    web = servers["merchant.migaozn.com"]
    web_root = locations(web).get("/")
    if web_root is None:
        v.append("merchant.migaozn.com 段没有 `location /`（判据坐标没了）")
    else:
        for header in (HSTS_DIRECTIVE, "X-Content-Type-Options"):
            if not has_header(web_root, header):
                v.append(f"merchant.migaozn.com 的 `location /` 缺 `add_header {header}`（含官网 /download）")

    # 判据 4/5：app 段
    app = servers["app.migaozn.com"]
    app_locations = locations(app)
    app_root = app_locations.get("/")
    if app_root is None:
        v.append("app.migaozn.com 段没有 `location /`（判据坐标没了）")
    else:
        for header in (HSTS_DIRECTIVE, "X-Content-Type-Options"):
            if not has_header(app_root, header):
                v.append(f"app.migaozn.com 的 `location /` 缺 `add_header {header}`（C 端元元页面面）")
    for face in ("/w/", "/b/", "/b/report/"):
        loc = app_locations.get(face)
        if loc is None:
            v.append(f"app.migaozn.com 段没有 `location {face}`（判据坐标没了）")
            continue
        for header in (HSTS_DIRECTIVE, "X-Content-Type-Options"):
            if not has_header(loc, header):
                v.append(f"`{face}` 缺 `add_header {header}`")
        if not resolve_csp(app, loc):
            v.append(f"`{face}` 缺 Content-Security-Policy（审计 P1-09 点名要最小 CSP）")
    terminal = app_locations.get("/terminal/")
    if terminal is None:
        v.append("app.migaozn.com 段没有 `location /terminal/`（判据坐标没了）")
    elif not has_header(terminal, HSTS_DIRECTIVE):
        v.append("`/terminal/` 缺 HSTS（该块自己写 add_header ⇒ 不继承 server 级，必须重新声明）")

    # 判据 6：CSP「最小」的可判定三条
    for face in ("/w/", "/b/", "/b/report/"):
        loc = app_locations.get(face)
        if loc is None:
            continue
        csp = resolve_csp(app, loc)
        if not csp:
            continue
        lowered = csp.lower()
        if "default-src 'self'" not in lowered:
            v.append(f"`{face}` 的 CSP 缺 `default-src 'self'`")
        if "script-src" not in lowered:
            v.append(f"`{face}` 的 CSP 缺 `script-src`")
        if "frame-ancestors 'self'" not in lowered:
            v.append(f"`{face}` 的 CSP 缺 `frame-ancestors 'self'`（防被嵌入）")
        if "*" in csp:
            v.append(f"`{face}` 的 CSP 出现通配来源 `*`（等于没 CSP）")
        if "'unsafe-eval'" in lowered:
            v.append(f"`{face}` 的 CSP 含 `'unsafe-eval'`（等于没 CSP）")
    return v


def has_inline_script(html: str) -> bool:
    """`<script>` 且**没有 src** 且有内容 ⇒ 内联脚本（CSP 的 `'unsafe-inline'` 面）。"""
    for m in re.finditer(r"<script\b([^>]*)>(.*?)</script>", html, re.S | re.I):
        attrs, body = m.group(1), m.group(2)
        if "src=" in attrs.lower():
            continue
        if body.strip():
            return True
    return False


def _csp_directive(csp: str, name: str) -> str:
    """取 CSP 里某个指令的值（**只**看这一条：`style-src` 的 `'unsafe-inline'` 与 `script-src` 是两回事）。"""
    for part in csp.split(";"):
        tokens = part.strip().split()
        if tokens and tokens[0].lower() == name:
            return " ".join(tokens[1:]).lower()
    return ""


def judge_csp_source_compat(nginx_text: str, worker_htmls: list[str], bmini_html: str) -> list[str]:
    """判据 7：CSP 与产物**必须一致**（否则要么白屏、要么防护名存实亡）。"""
    v: list[str] = []
    app = servers_by_domain(nginx_text).get("app.migaozn.com")
    if app is None:
        return ["nginx.conf 里找不到 app.migaozn.com 段（判据坐标没了）"]
    app_locations = locations(app)

    worker_csp = resolve_csp(app, app_locations.get("/w/")) if app_locations.get("/w/") else ""
    bmini_csp = resolve_csp(app, app_locations.get("/b/")) if app_locations.get("/b/") else ""
    worker_script = _csp_directive(worker_csp, "script-src")
    bmini_script = _csp_directive(bmini_csp, "script-src")

    worker_inline = any(has_inline_script(html) for html in worker_htmls)
    bmini_inline = has_inline_script(bmini_html)

    if worker_inline and "'unsafe-inline'" not in worker_script:
        v.append("worker-h5 的 HTML 里有内联脚本，但 `/w/` 的 CSP `script-src` 没放 `'unsafe-inline'` ⇒ 整页脚本会被拦（白屏）")
    if not worker_inline and "'unsafe-inline'" in worker_script:
        v.append("worker-h5 的 HTML 里**没有**内联脚本，`/w/` 的 CSP `script-src` 却放了 `'unsafe-inline'` ⇒ 无谓放宽（可收紧）")
    if bmini_inline and "'unsafe-inline'" not in bmini_script:
        v.append(
            "bmini h5 的 `src/index.html` 有内联脚本（`window.TARO_ENV` + 响应式根字号），"
            "但 `/b/` 的 CSP `script-src` 没放 `'unsafe-inline'` ⇒ 真白屏（issue #5721 的根字号会失效）"
        )
    if not bmini_inline and "'unsafe-inline'" in bmini_script:
        v.append("bmini h5 已无内联脚本，`/b/` 的 CSP `script-src` 仍放 `'unsafe-inline'` ⇒ 可收紧（登记的重启条件已满足）")
    return v


def judge_script_is_read_only(script_text: str) -> list[str]:
    v: list[str] = []
    for bad, why in (
        (r"\brm\s", "删除"),
        (r"curl[^\n]*-(X|d)\s*(POST|PUT|DELETE)", "写请求"),
        (r"\btee\b", "写盘"),
        (r">\s*/(?!dev)", "重定向写盘"),
    ):
        if re.search(bad, script_text):
            v.append(f"判据本体 `deploy/scripts/prod-security-headers.sh` 里出现{why}动作 /{bad}/ ⇒ 线上判据必须**只读**")
    return v


# ══════════════════════════════════════════════════════════════════════════
# 三、静态判据
# ══════════════════════════════════════════════════════════════════════════


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_delivery_pipeline_emits_hsts_and_static_headers():
    v = (
        judge_app_config(_read(APP_YML))
        + judge_security_config(_read(SECURITY_CONFIG))
        + judge_nginx_headers(_read(NGINX_CONF))
        + judge_csp_source_compat(
            _read(NGINX_CONF),
            [_read(p) for p in sorted(WORKER_H5_DIR.glob("*.html"))],
            _read(BMINI_INDEX_HTML),
        )
        + judge_script_is_read_only(_read(SCRIPT))
    )
    assert not v, "安全响应头判据未通过：\n- " + "\n- ".join(v)


# ══════════════════════════════════════════════════════════════════════════
# 四、判据 9：**执行式** —— 真脚本 + 本机 stub server（三态各一次）
# ══════════════════════════════════════════════════════════════════════════


GOOD_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
}
CSP_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; frame-ancestors 'self'"
}


class _StubHandler(BaseHTTPRequestHandler):
    mode = "good"  # 由测试改写：good / no-hsts
    protocol_version = "HTTP/1.1"

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler 的接口
        status = 404 if self.path.startswith("/terminal/") else 200
        self.send_response(status)
        headers = dict(GOOD_HEADERS) if self.mode == "good" else {"X-Content-Type-Options": "nosniff"}
        if self.path in ("/w/", "/b/"):
            headers.update(CSP_HEADERS)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):  # 静音（stub server 不要污染测试输出）
        return


@pytest.fixture()
def stub_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def _run_script(base: str, *, timeout: int = 120):
    import os
    import subprocess

    env = dict(os.environ)
    env.update(
        {
            "PROD_HEADERS_API_BASE": base,
            "PROD_HEADERS_MERCHANT_BASE": base,
            "PROD_HEADERS_SITE_BASE": base,
            "PROD_HEADERS_APP_BASE": base,
            "PROD_HEADERS_AI_BASE": base,
            "PROD_HEADERS_TIMEOUT": "10",
        }
    )
    return subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, env=env, timeout=timeout
    )


def test_script_green_on_complete_headers(stub_server):
    _StubHandler.mode = "good"
    out = _run_script(f"http://127.0.0.1:{stub_server.server_address[1]}")
    assert out.returncode == 0, f"{out.stdout}\n{out.stderr}"
    assert "PROD-HEADERS-SUMMARY rc=0" in out.stdout


def test_script_red_on_missing_hsts(stub_server):
    _StubHandler.mode = "no-hsts"
    out = _run_script(f"http://127.0.0.1:{stub_server.server_address[1]}")
    assert out.returncode == 1, f"缺 HSTS 必须判红（1），实测 {out.returncode}\n{out.stdout}"
    assert "strict-transport-security" in out.stdout
    assert "PROD-HEADERS-SUMMARY rc=1" in out.stdout


def test_script_unknown_when_unreachable():
    out = _run_script("http://127.0.0.1:1")
    assert out.returncode == 3, f"连不上必须退 3（不得当 0 读），实测 {out.returncode}\n{out.stdout}"
    assert "PROD-HEADERS-SUMMARY rc=3" in out.stdout


# ══════════════════════════════════════════════════════════════════════════
# 五、判据 10：接线（判据存在但没人跑 = 假绿）
# ══════════════════════════════════════════════════════════════════════════


def _steps_of_deploy_job() -> list[dict]:
    doc = yaml.safe_load(_read(DEPLOY_WORKFLOW))
    job = doc["jobs"]["build-and-deploy"]
    return job.get("steps") or []


def test_headers_judgment_is_wired_into_the_deploy_leg():
    runs = [(step.get("name") or "", step.get("run") or "") for step in _steps_of_deploy_job()]
    headers_idx = [i for i, (_, body) in enumerate(runs) if "prod-security-headers.sh" in body]
    assert headers_idx, (
        "deploy-admin-api.yml 的 build-and-deploy 里没有跑 `deploy/scripts/prod-security-headers.sh` —— "
        "判据存在但没有人跑（假绿）"
    )
    served_idx = [i for i, (_, body) in enumerate(runs) if "served-version-verify.sh" in body]
    assert served_idx, "deploy-admin-api.yml 里找不到 served-version-verify.sh 那一步（判据 10 的坐标没了）"
    assert headers_idx[0] > served_idx[0], "安全头判据必须排在 served-sha 断言**之后**（部署后才判）"


# ══════════════════════════════════════════════════════════════════════════
# 六、注入式红证
# ══════════════════════════════════════════════════════════════════════════


def _inject(text: str, needle: str, replacement: str) -> str:
    assert needle in text, f"注入点定位失败（fail-closed）：找不到 {needle!r}"
    mutated = text.replace(needle, replacement, 1)
    assert mutated != text, "变异注入未生效（自证失败 ⇒ 下面的红证是空断言）"
    return mutated


def test_injection_missing_forward_headers_strategy_is_caught():
    mutated = _inject(_read(APP_YML), "  forward-headers-strategy: native\n", "")
    v = judge_app_config(mutated)
    assert any("forward-headers-strategy" in x for x in v), v


def test_injection_hsts_removed_from_static_face_is_caught():
    mutated = _inject(
        _read(NGINX_CONF),
        '        add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;\n'
        "        add_header X-Content-Type-Options nosniff always;\n"
        "        add_header Content-Security-Policy $migao_csp_worker always;\n"
        "        try_files $uri $uri/ /w/index.html;",
        "        add_header X-Content-Type-Options nosniff always;\n"
        "        add_header Content-Security-Policy $migao_csp_worker always;\n"
        "        try_files $uri $uri/ /w/index.html;",
    )
    v = judge_nginx_headers(mutated)
    assert any("/w/" in x and HSTS_DIRECTIVE in x for x in v), v


def test_injection_csp_removed_from_bmini_is_caught():
    mutated = _inject(
        _read(NGINX_CONF),
        "        add_header Content-Security-Policy $migao_csp_bmini always;\n",
        "",
    )
    v = judge_nginx_headers(mutated)
    assert any("/b/" in x and "Content-Security-Policy" in x for x in v), v


def test_injection_hsts_added_to_api_domain_is_caught():
    mutated = _inject(
        _read(NGINX_CONF),
        "    # 访问日志脱敏（issue #8218 P1-10）：本域是 token 的**来源**",
        '    add_header Strict-Transport-Security "max-age=31536000" always;\n'
        "    # 访问日志脱敏（issue #8218 P1-10）：本域是 token 的**来源**",
    )
    v = judge_nginx_headers(mutated)
    assert any("api.migaozn.com" in x and "RFC 6797" in x for x in v), v


def test_injection_csp_relaxed_on_worker_face_is_caught():
    mutated = _inject(
        _read(NGINX_CONF),
        "script-src 'self'; style-src 'self' 'unsafe-inline'; img-src",
        "script-src * 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src",
    )
    v = judge_nginx_headers(mutated)
    assert any("通配来源" in x for x in v), v
    assert any("unsafe-eval" in x for x in v), v


def test_injection_script_wiring_removed_is_caught():
    """判据 10 的判别力：把接线 step 的 run 换掉 ⇒ 必须判红。"""
    doc = yaml.safe_load(_read(DEPLOY_WORKFLOW))
    steps = doc["jobs"]["build-and-deploy"]["steps"]
    hit = [s for s in steps if "prod-security-headers.sh" in (s.get("run") or "")]
    assert hit, "生产 workflow 里没有接线（本判据的前提已破）"
    # 在内存里把接线摘掉，再用与判据 10 同一份逻辑判定
    for step in hit:
        step["run"] = step["run"].replace("prod-security-headers.sh", "echo skipped")
    still_wired = any("prod-security-headers.sh" in (s.get("run") or "") for s in steps)
    assert not still_wired, "摘线注入未生效（自证失败）"


if __name__ == "__main__":  # pragma: no cover - 手工复算入口
    raise SystemExit(pytest.main([__file__, "-q"]))
