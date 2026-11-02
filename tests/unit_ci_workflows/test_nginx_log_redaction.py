# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""短链 token **不进访问日志**（issue #8218 P1-10，2026-10-31 上线审计）。

## 病（durable 证据在审计 findings 的 P1-10 行）

报工 / 入库 / 加工单三种短码把 token 放在 **URL query**：`WorkerShortLinkController::resolve` 302 出
`Location: /b/?t=<token>&tenant_id=…`（`InboundLabelShortLinkController` / `ProcessingOrderShortLinkController`
同族）。nginx 默认的 `log_format main` 第一段是 `"$request"` = **方法 + 完整原始 URI（含 query）**
⇒ token 逐字落进 `/var/log/nginx/access.log`；并且 `$http_referer` 会把同一个 token 带到后续每个
静态资源的日志行里。那份日志**长期保留、所有人可见**，而 token 可直接用来**冒用工人身份报工/入库**。

## 取舍与修法（登记在 docs/deployment/production-deployment.md 的「短链 token」节）

短码形态**不改**（换一次性票据是后端契约变更 ⇒ 另单）；只在日志侧脱敏：
`log_format migao_no_token` 用 `$request_method $uri $server_protocol`（`$uri` **不含** args），
且**不带** `$http_referer` ⇒ token 在日志里**物理上不可能**出现。
**每个** server 块（含明文 :80 那两块 —— 明文请求同样会带 token）都必须显式使用它。

## 判据（每条都能单独变红）

| # | 判据 | 变红形态 |
|---|---|---|
| 1 | `log_format migao_no_token` 存在，含 `$uri`，**不含** `$request` / `$request_uri` / `$args` / `$http_referer` | 把 `$uri` 换回 `$request`（或顺手加回 Referer）⇒ 红 |
| 2 | **每个** `server` 块（80 与 443 都算）都有 `access_log … migao_no_token` | 新增一个 server 块（或删掉某一块的 access_log）⇒ 红（会静默继承默认的 `$request` 格式） |
| 3 | **语义模拟**：按该格式渲染一条「带 token 的真实请求」⇒ 渲染结果里**没有** token 值 | 格式里任何一处引用了带 query/Referer 的变量 ⇒ 红（不是文本匹配，是真渲染） |
| 4 | token 落地面（`/w/`、`/b/`、`/b/report/`）所在的 server 用了该格式 | 把 app 域切回默认格式 ⇒ 红 |
| 5 | 文档里**登记了有意取舍 + 重启条件**（`docs/deployment/production-deployment.md`） | 删掉那节 ⇒ 红（「有意不做」不许被读成「已解决」） |
| 6 | 注入式自证（判据 1/2 在内存变异文本上各自判红） | 任一注入没被检出 ⇒ 红 |

## 红证（改前）

```bash
grep -cE 'log_format|access_log' deploy/swas/nginx.conf   # 改前 0（默认格式 = $request + $http_referer）
```

## 边界（照实登记，§19.1）

- **不跑 nginx**（本机没有 nginx 二进制 / docker）⇒ 判据 3 是**按 nginx 的变量语义**在 Python 里
  渲染该 `log_format` 串（变量名直接替换成样本值），**不是**真 nginx 的日志输出。真机复核命令写在
  文档里（`docker compose exec -T nginx grep -c 't=' /var/log/nginx/access.log` ⇒ 期望 0）。
- 判据 2 只看**本仓 canonical 的** `deploy/swas/nginx.conf`；服务器上被手工改过的那份不在射程内
  （部署腿每次 `cp` 覆盖它，这是既有机制）。
- 它证明不了「后端应用日志不记 token」（Spring 的访问日志 / 异常栈不在本仓配置面内）——
  本单只治 nginx access log 这一面，如实登记为残余。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from unit_ci_workflows.test_swas_nginx_rate_limit import parse_nginx

REPO_ROOT = Path(__file__).resolve().parents[2]
NGINX_CONF = REPO_ROOT / "deploy" / "swas" / "nginx.conf"
DOC = REPO_ROOT / "docs" / "deployment" / "production-deployment.md"

FORMAT_NAME = "migao_no_token"
#: 带 token 的落地面（审计点名的三族短码最终都跳到 app 域的这两段前缀上）
TOKEN_FACES = ("/w/", "/b/", "/b/report/")
#: 样本请求：真机形态（`/b/?t=<token>&tenant_id=2`）
SAMPLE_TOKEN = "SECRET-TOKEN-9f3a1c"
SAMPLE_VARIABLES = {
    "$remote_addr": "203.0.113.9",
    "$remote_user": "-",
    "$time_local": "31/Oct/2026:12:00:00 +0800",
    "$request_method": "GET",
    "$uri": "/b/",
    "$server_protocol": "HTTP/1.1",
    "$status": "302",
    "$body_bytes_sent": "0",
    "$http_user_agent": "Mozilla/5.0",
    "$http_x_forwarded_for": "203.0.113.9",
    # 👇 这两个**故意**给成带 token 的值：格式里只要引用了它们，渲染结果就会漏出 token
    "$request": f"GET /b/?t={SAMPLE_TOKEN}&tenant_id=2 HTTP/1.1",
    "$request_uri": f"/b/?t={SAMPLE_TOKEN}&tenant_id=2",
    "$args": f"t={SAMPLE_TOKEN}&tenant_id=2",
    "$http_referer": f"https://app.migaozn.com/w/?t={SAMPLE_TOKEN}",
}


# ══════════════════════════════════════════════════════════════════════════
# 一、解析工具
# ══════════════════════════════════════════════════════════════════════════


def _servers(text: str) -> list:
    return [b for b in parse_nginx(text).children if b.header == "server"]


def _log_formats(text: str) -> dict[str, str]:
    """→ {格式名: 格式串}（`log_format <name> '…'`；nginx 允许同一指令跨行 = parse 已合并成一条）。"""
    out: dict[str, str] = {}
    for statement in parse_nginx(text).directives:
        if not statement.startswith("log_format "):
            continue
        m = re.match(r"log_format\s+(\S+)\s+(.*)$", statement, re.S)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def _access_logs(server) -> list[str]:
    return [d for d in server.directives if d.startswith("access_log ")]


def _server_label(server) -> str:
    name = next((d for d in server.directives if d.startswith("server_name ")), "server_name ?")
    listen = next((d for d in server.directives if d.startswith("listen ")), "listen ?")
    return f"{listen} / {name}"


# ══════════════════════════════════════════════════════════════════════════
# 二、纯函数判据（吃文本 ⇒ 注入式自证可喂变异文本）
# ══════════════════════════════════════════════════════════════════════════


def render_log_line(fmt: str, variables: dict[str, str]) -> str:
    """按 nginx 语义渲染格式串（**最长变量名优先**替换，避免 `$request` 吃掉 `$request_method`）。"""
    out = fmt
    for name in sorted(variables, key=len, reverse=True):
        out = out.replace(name, variables[name])
    return out


def judge_redaction(nginx_text: str, doc_text: str) -> list[str]:
    v: list[str] = []
    formats = _log_formats(nginx_text)

    # ── 判据 1：格式本体 ────────────────────────────────────────────────────
    fmt = formats.get(FORMAT_NAME)
    if fmt is None:
        v.append(f"nginx.conf 里没有 `log_format {FORMAT_NAME}` ⇒ 访问日志仍会记 `$request`（含 query）")
    else:
        if "$uri" not in fmt:
            v.append(f"`{FORMAT_NAME}` 里没有 `$uri`（只有 `$uri` 是「不含 args 的路径」）")
        for bad, why in (
            ("$request_uri", "原始 URI 含 query"),
            ("$args", "query 串本身"),
            ("$http_referer", "Referer 会把 token 带到后续静态资源的日志行"),
        ):
            if bad in fmt:
                v.append(f"`{FORMAT_NAME}` 里出现 {bad}（{why}）⇒ token 会漏进日志")
        # `$request` 必须**整词**判（`$request_method` / `$request_uri` 里都含这几个字母）
        if re.search(r"\$request\b", fmt):
            v.append(f"`{FORMAT_NAME}` 里出现 `$request`（方法 + **完整原始 URI**，含 query）⇒ token 会漏进日志")

    # ── 判据 3：语义渲染（带 token 的真实请求 ⇒ 输出里不许有 token）────────────
    if fmt is not None:
        rendered = render_log_line(fmt, SAMPLE_VARIABLES)
        if SAMPLE_TOKEN in rendered:
            v.append(f"渲染出来的日志行含 token（{SAMPLE_TOKEN}）⇒ 脱敏失效：{rendered}")

    # ── 判据 2：**每个** server 块都必须显式用该格式 ──────────────────────────
    servers = _servers(nginx_text)
    if not servers:
        v.append("nginx.conf 里一个 server 块都没有 —— 判据坐标没了")
    for server in servers:
        logs = _access_logs(server)
        if not logs:
            v.append(f"{_server_label(server)} 没有 `access_log … {FORMAT_NAME}`（会继承默认的 `$request` 格式）")
            continue
        if not any(FORMAT_NAME in directive for directive in logs):
            v.append(f"{_server_label(server)} 的 access_log 没用 `{FORMAT_NAME}`：{logs}")

    # ── 判据 4：token 落地面所在 server 用了该格式 ────────────────────────────
    for server in servers:
        prefixes = [loc.header.split()[-1] for loc in server.children if loc.header.startswith("location ")]
        if not any(face in prefixes for face in TOKEN_FACES):
            continue
        if not any(FORMAT_NAME in directive for directive in _access_logs(server)):
            v.append(
                f"{_server_label(server)} 承载 token 落地面（{', '.join(f for f in TOKEN_FACES if f in prefixes)}）"
                f"却没用 `{FORMAT_NAME}`"
            )

    # ── 判据 5：文档登记了「有意取舍 + 重启条件」────────────────────────────────
    for marker in ("短链 token：**有意取舍**", "日志侧脱敏", "重启条件"):
        if marker not in doc_text:
            v.append(f"docs/deployment/production-deployment.md 里没有登记「{marker}」——取舍必须写明，不能只做不记")
    return v


def all_violations(nginx_text: str, doc_text: str) -> list[str]:
    return judge_redaction(nginx_text, doc_text)


# ══════════════════════════════════════════════════════════════════════════
# 三、静态判据（读仓内现状）
# ══════════════════════════════════════════════════════════════════════════


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_access_log_never_carries_short_link_token():
    v = all_violations(_read(NGINX_CONF), _read(DOC))
    assert not v, "访问日志脱敏判据未通过：\n- " + "\n- ".join(v)


# ══════════════════════════════════════════════════════════════════════════
# 四、注入式红证（判据 6：判据真的会红，且**指名**）
# ══════════════════════════════════════════════════════════════════════════


def _inject(text: str, needle: str, replacement: str) -> str:
    assert needle in text, f"注入点定位失败（fail-closed）：找不到 {needle!r}"
    mutated = text.replace(needle, replacement, 1)
    assert mutated != text, "变异注入未生效（自证失败 ⇒ 下面的红证是空断言）"
    return mutated


def test_injection_request_uri_in_format_is_caught():
    text = _inject(
        _read(NGINX_CONF), "\"$request_method $uri $server_protocol\"", "\"$request_uri $server_protocol\""
    )
    v = judge_redaction(text, _read(DOC))
    assert any("$request_uri" in x for x in v), v
    # 语义面：渲染结果必须真的漏出 token（证明判据 3 有判别力）
    assert any("含 token" in x for x in v), v


def test_injection_referer_in_format_is_caught():
    text = _inject(_read(NGINX_CONF), ' "$http_user_agent" "$http_x_forwarded_for"', ' "$http_user_agent" "$http_referer"')
    v = judge_redaction(text, _read(DOC))
    assert any("$http_referer" in x for x in v), v


def test_injection_server_without_access_log_is_caught():
    # 删掉 app 域 :80 那块的 access_log（它承载 `http://app.migaozn.com/b/?t=`）
    text = _inject(
        _read(NGINX_CONF),
        "    # 明文面也**必须**脱敏（issue #8218 P1-10）：`http://app.migaozn.com/b/?t=<token>` 会先落到这里。\n"
        "    access_log /var/log/nginx/access.log migao_no_token;\n",
        "",
    )
    v = judge_redaction(text, _read(DOC))
    assert any("没有 `access_log" in x for x in v), v


def test_injection_doc_registration_removed_is_caught():
    doc = _read(DOC)
    mutated = doc.replace("重启条件", "以后再说")  # 文档里有两处（安全头 / 短链 token），全删
    assert mutated != doc, "变异注入未生效（自证失败 ⇒ 下面的红证是空断言）"
    assert "重启条件" not in mutated
    v = judge_redaction(_read(NGINX_CONF), mutated)
    assert any("重启条件" in x for x in v), v


if __name__ == "__main__":  # pragma: no cover - 手工复算入口
    raise SystemExit(pytest.main([__file__, "-q"]))
