#!/usr/bin/env python3
"""试用客户上线前的**只读**开通面判据（上线审计 issue #8197，runbook = docs/deployment/trial-onboarding.md）。

## 它判什么（以及**不**判什么）

第一批 1~2 家试用客户的「上线当天」要按顺序过四关：建号 → 装终端 → 扫二维码 → 首单报工。
前两关有一半是**外部动作**（微信后台、终端签名、真机安装），机器判不了 —— 本脚本只判
**线上公开面**这一半，且**只读**：全部 GET/HEAD，不登录、不 POST、不写任何东西
（登录探测会触发 `LoginFailureGuard` 的失败计数 ⇒ 锁号，那是**写**行为，禁止）。

| 判据 | 面 | 通过形态 |
|---|---|---|
| `enterprise-code` | 入参 | 符合 `LoginIdentifiers.TENANT_CODE_PATTERN`（2~32 位小写/数字/`_`/`-`）且非保留字 |
| `download-page` | `{site}/download` | 200 + `text/html` + 出**真实正文**（不是 SPA fallback） |
| `terminal-dir-redirect` | `{app}/terminal` | **301** → `/terminal/`（裸前缀落 SPA fallback = 假 200） |
| `windows-manifest` | `{app}/terminal/latest.json` | 200 + 字段齐 / `sha256` 64 位 / `size` > 0 / 载荷对得上 |
| `android-manifest` | `{app}/terminal/android/latest.json` | 同上 + `versionCode` 正整数（单调递增的比较依据） |
| `bmini-report-page` | `{app}/b/report/` | 200 + `text/html`（扫码 302 的落点） |
| `worker-h5-page` | `{app}/w/` | 200（兼容期工人端） |
| `shortlink-json-contract` | `{app}/s/<未知码>/json` | **404 + `application/json` + `{"error":"not_found"}`** |
| `security-headers` | 上述各面 | HSTS + nosniff（`/w/` `/b/report/` 另要 CSP） |
| `tenant-binding` | `{app}/s/<工人短码>` + `/o/<加工单短码>` | 302 落点里 `tenant_code` == 入参企业编码 |
| `shortlink-json-parity` | `{app}/s/<工人短码>/json` | 与 302 面**同一份** token（A 档拿到旧 token = 报工失败） |

## 三态退出码（**`3` 不得当 `0` 读**）

| 码 | 含义 |
|---|---|
| `0` | 全部判据通过（可以开始真机安装与首单报工） |
| `1` | 有**确定**的缺陷：面 404/非 200、清单语义坏、缺头、短码归属别的企业 |
| `3` | **不可判定 / 缺配置**：连不上、清单**还没发布**、没给工人短码 ⇒ **不是通过** |

`1` 优先于 `3`：已确定的缺陷不该被另一面探不到稀释成「不可判定」（沿用
`deploy/scripts/prod-security-headers.sh` 的口径）。

## 为什么 manifest 404 是 `3` 而不是 `1`

终端**还没发布**是**开通前置未执行**（需要人跑 `terminal-publish.yml`，还要终端仓出签名产物），
不是线上面的缺陷 —— 与 `prod-security-headers.sh` 把 `/terminal/` 的 404 当合格回答同因。
但它**绝不能绿**：没有清单就装不了终端，试用客户的上线顺序根本走不下去。

## 用法

```bash
python3 scripts/trial_onboarding_check.py \
  --enterprise-code acme-fabric \
  --worker-code 7K3M9QP2 \        # 可选：纸上真实的工人短码（8 位 Crockford Base32）
  --order-code 4HX2W9TD          # 可选：加工单纸上的短码
```

缺 `--enterprise-code` ⇒ 静态面照跑，但整体 `rc=3`（缺配置不是绿）。
`--worker-code` / `--order-code` 都给不出来 ⇒ `tenant-binding` 记 `3` ⇒ 整体 `rc=3`：
**没有一张印出来的码，就无法证明「这家企业的码真的指向这家企业」** —— 而这正是试用期最该核的那条边界。

## 边界（照实登记）

- **只判公开面**：登录后的建号、报工、计件、打印一律不判（需要凭据 ⇒ 属于人做的上线 checklist）。
- **不判签名**：安装包有没有代码签名，公网读不到（Windows 签名要 `signtool verify`、APK 要 `apksigner`）⇒
  runbook 里如实登记「当前未签名/自签」，本脚本**不**给任何签名结论。
- **不替代** `deploy/scripts/prod-security-headers.sh`：那里判 `max-age` 下限与 CSP 形态（含
  `default-src 'self'` / `script-src` / 禁通配与 `unsafe-eval`）；这里只判开通链路上那几面的**有没有**。
- **`--worker-code` 是可信输入**：脚本核的是「这张纸现在指向谁」，不核「这张纸该发给谁」。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ── 契约常量（真值源各只有一份；这里只**读**，不复制判定逻辑） ──────────────────────
# 企业编码形态：backend/admin-api/src/main/java/com/migao/admin/support/LoginIdentifiers.java::TENANT_CODE_PATTERN
TENANT_CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")
# backend/admin-api/src/main/java/com/migao/admin/support/LoginIdentifiers.java::RESERVED_TENANT_CODES
RESERVED_TENANT_CODES = frozenset(
    {"admin", "api", "www", "app", "platform", "support", "system", "root", "login", "auth"}
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# 报工页落点：backend/admin-api/src/main/java/com/migao/admin/service/WorkerShortLinkService.java::REPORT_PAGE_PATH
REPORT_PAGE_PATH = "/b/report/"

# 探针短码：8 位 Crockford Base32（格式合法 ⇒ 走完 normalize + 查库，而不是被格式校验提前挡掉）。
# 32^8 ≈ 1.1e12 ⇒ 撞到真码的概率可忽略；即使撞到，本脚本会判红并打印实际状态码，不会假绿。
UNKNOWN_SHORT_CODE = "00000000"

# `/download` 的真正文标记：页面的 title / lead 都含它（`frontend/admin-web/src/app/(corporate)/download/page.tsx`）。
# 用「正文标记」而不是「长度阈值」：app 域的 `/download` 会落 SPA fallback 拿到 **200 的一页 C 端 HTML**
# ⇒ 只看状态码会把假 200 读成通过（同族实证：nginx.conf 里 `/terminal` 必须 301、`/i/` 曾与根同哈希）。
DOWNLOAD_MARKER = "观星台终端"

OK, FAIL, UNKNOWN = "OK", "FAIL", "UNKNOWN"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """**不跟随**跳转：本脚本要读 302 的 `Location` 本体（不是它的落点）。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401 (接口签名)
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _request(url: str, timeout: float, method: str = "GET"):
    """只读请求：返回 `(status, headers, body_bytes, error)`；连不上时 `status=None`、`error` 非空。"""
    req = urllib.request.Request(url, method=method, headers={"User-Agent": "migao-trial-onboarding-check/1"})
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            body = b"" if method == "HEAD" else resp.read(256 * 1024)
            return resp.status, resp.headers, body, None
    except urllib.error.HTTPError as exc:  # 4xx/5xx 是**可读的读数**，不是异常
        body = b"" if method == "HEAD" else exc.read(256 * 1024)
        return exc.code, exc.headers, body, None
    except Exception as exc:  # 连不上 / DNS / TLS / 超时 ⇒ 不可判定（3），归因成缺陷（1）
        return None, {}, b"", f"{type(exc).__name__}: {exc}"


class Report:
    """判据台账（一条判据一行输出 + 计数汇总；不写盘）。"""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, name: str, state: str, detail: str) -> None:
        self.rows.append((name, state, detail))
        icon = {OK: "✅", FAIL: "❌", UNKNOWN: "????"}[state]
        print(f"  {icon} {name:<24} {detail}")

    def verdict(self) -> int:
        failed = sum(1 for _, s, _ in self.rows if s == FAIL)
        unknown = sum(1 for _, s, _ in self.rows if s == UNKNOWN)
        passed = sum(1 for _, s, _ in self.rows if s == OK)
        summary = (
            f"TRIAL-ONBOARDING-SUMMARY rc={1 if failed else (3 if unknown else 0)}"
            f" passed={passed} failed={failed} unknown={unknown}"
        )
        print("\n" + summary)
        return 1 if failed else (3 if unknown else 0)


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _is_download_url_ok(url: str, suffix: str) -> bool:
    """`download_url` 形态：**线上必须 https**；只有回环地址（本机 stub / 本地联调）才放行 http。

    放行回环是为了让判据能被**本机 stub** 驱动（`tests/unit_ci_workflows/test_trial_onboarding_check.py`）——
    否则「清单语义」这条判据只能靠线上真环境来验，而它恰恰是最需要红证的一条。
    """
    parts = urllib.parse.urlsplit(url)
    if not parts.path.lower().endswith(suffix):
        return False
    if parts.scheme == "https":
        return True
    return parts.scheme == "http" and (parts.hostname or "") in _LOOPBACK_HOSTS


def _header(headers, name: str) -> str:
    """响应头取值（大小写不敏感）；`HTTPMessage` 自带 `get`，缺失返回空串。"""
    return (headers.get(name) or "").strip() if headers else ""


def check_headers(report: Report, label: str, headers, *, want_csp: bool) -> None:
    """HSTS + nosniff（+ 两处静态面的 CSP）。缺**任一** ⇒ FAIL（确定的缺陷）。"""
    missing = []
    if not _header(headers, "Strict-Transport-Security"):
        missing.append("strict-transport-security")
    if not _header(headers, "X-Content-Type-Options"):
        missing.append("x-content-type-options")
    if want_csp and not _header(headers, "Content-Security-Policy"):
        missing.append("content-security-policy")
    if missing:
        report.add(f"headers-{label}", FAIL, "缺 " + ",".join(missing))
    else:
        report.add(f"headers-{label}", OK, f"HSTS+nosniff{'+CSP' if want_csp else ''}")


def check_manifest(report: Report, name: str, app: str, path: str, timeout: float, *, android: bool) -> None:
    """发布清单的**语义**判据：字段齐 + 哈希形态 + 载荷真能下载且大小对得上。

    404 ⇒ UNKNOWN（没发布）；语义坏 / 载荷对不上 ⇒ FAIL（终端会拿坏清单去更新，且服务器侧无感）。
    """
    url = app + path
    status, headers, body, error = _request(url, timeout)
    if status is None:
        report.add(name, UNKNOWN, f"{path} 探不到（{error}）")
        return
    if status == 404:
        # 面存在但**还没发布**（`location /terminal/` 的 try_files =404）—— 开通前置未执行，不是通过
        report.add(name, UNKNOWN, f"{path} 404 未发布（先跑 terminal-publish.yml，见 runbook §2）")
        return
    if status != 200:
        report.add(name, FAIL, f"{path} 期望 200/404，实测 {status}")
        return
    if "json" not in _header(headers, "Content-Type").lower():
        report.add(name, FAIL, f"{path} Content-Type 不是 JSON（{_header(headers, 'Content-Type') or '空'}）")
        return
    try:
        manifest = json.loads(body.decode("utf-8"))
    except Exception as exc:
        report.add(name, FAIL, f"{path} 不是合法 JSON（{type(exc).__name__}）")
        return
    if not isinstance(manifest, dict):
        report.add(name, FAIL, f"{path} 顶层不是对象")
        return

    version = manifest.get("versionName" if android else "version")
    download_url = manifest.get("download_url")
    sha256 = manifest.get("sha256")
    size = manifest.get("size")
    published_at = manifest.get("published_at")
    suffix = ".apk" if android else ".exe"
    problems = []
    if not isinstance(version, str) or not version.strip():
        problems.append("缺 version" + ("Name" if android else ""))
    if android and not (isinstance(manifest.get("versionCode"), int) and manifest["versionCode"] > 0):
        problems.append("versionCode 不是正整数")
    if not isinstance(download_url, str) or not _is_download_url_ok(download_url, suffix):
        problems.append(f"download_url 不是 https 的 {suffix}")
    if not isinstance(sha256, str) or not SHA256_RE.match(sha256.lower()):
        problems.append("sha256 不是 64 位十六进制")
    if not isinstance(size, int) or size <= 0:
        problems.append("size 不是正整数")
    if not isinstance(published_at, str) or not DATE_RE.match(published_at):
        problems.append("published_at 不是 YYYY-MM-DD")
    if problems:
        report.add(name, FAIL, f"{path} 语义不合规：{'；'.join(problems)}")
        return

    # 清单必须**与载荷对得上**：否则线上是「清单说有、下载 404」/「哈希对不上」，
    # 而服务器侧完全无感（真值 = deploy/swas/terminal-publish-remote.sh 的 check_manifest）。
    head_status, head_headers, _, head_error = _request(download_url, timeout, method="HEAD")
    if head_status is None:
        report.add(name, UNKNOWN, f"清单 OK（{version}）但载荷探不到（{head_error}）")
        return
    if head_status != 200:
        report.add(name, FAIL, f"清单 OK（{version}）但 download_url 实测 {head_status}")
        return
    content_length = _header(head_headers, "Content-Length")
    if content_length.isdigit() and int(content_length) != size:
        report.add(name, FAIL, f"清单 size={size} ≠ 载荷 content-length={content_length}")
        return
    report.add(name, OK, f"{version} sha256={sha256[:12]}… size={size} 载荷 200")


def check_tenant_binding(
    report: Report, app: str, enterprise_code: str, timeout: float, worker_code: str, order_code: str
) -> None:
    """企业编码**归属**：印出来的码 302 落点里必须写着这家企业。

    `reportPageLocation()` 拼的是 `/b/report/?t=<token>&tenant_id=…&tenant_code=…`
    ⇒ 这是零凭据、零写入就能读到的**唯一**归属证据（`/s/<码>/json` 面上**故意**没有 tenant_code）。
    """
    if not enterprise_code:
        # 没有企业编码就没有比较基准 ⇒ 这一条**判定不了**（缺配置是 3，不是缺陷 1）
        report.add("tenant-binding", UNKNOWN, "缺 --enterprise-code ⇒ 没有归属基准，无法核这张码属于谁")
        return
    probes = [("worker", "/s/", worker_code), ("order", "/o/", order_code)]
    usable = [(label, prefix, code) for label, prefix, code in probes if code]
    if not usable:
        report.add(
            "tenant-binding",
            UNKNOWN,
            "缺 --worker-code / --order-code ⇒ 无法核企业编码归属（没有印出来的码就不是通过）",
        )
        return
    for label, prefix, code in usable:
        path = f"{prefix}{urllib.parse.quote(code)}"
        status, headers, _, error = _request(app + path, timeout)
        if status is None:
            report.add(f"tenant-binding-{label}", UNKNOWN, f"{path} 探不到（{error}）")
            continue
        if status != 302:
            report.add(f"tenant-binding-{label}", FAIL, f"{path} 期望 302，实测 {status}（码失效 ⇒ 纸作废/未开通）")
            continue
        location = _header(headers, "Location")
        if REPORT_PAGE_PATH not in location:
            report.add(f"tenant-binding-{label}", FAIL, f"{path} 落点不是 {REPORT_PAGE_PATH}：{location}")
            continue
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(location).query)
        actual = (query.get("tenant_code") or [""])[0].lower()
        if actual != enterprise_code:
            report.add(f"tenant-binding-{label}", FAIL, f"{path} 落点 tenant_code={actual or '(空)'} ≠ {enterprise_code}")
            continue
        # A 档 JSON 面与 302 面必须**同一份**语义：token 逐字相同（issue #8196）
        if label == "worker":
            json_status, json_headers, json_body, json_error = _request(app + path + "/json", timeout)
            if json_status is None:
                report.add("shortlink-json-parity", UNKNOWN, f"{path}/json 探不到（{json_error}）")
                continue
            try:
                payload = json.loads(json_body.decode("utf-8"))
            except Exception:
                payload = {}
            expected_token = (query.get("t") or [""])[0]
            if json_status != 200 or "json" not in _header(json_headers, "Content-Type").lower():
                report.add("shortlink-json-parity", FAIL, f"{path}/json 期望 200 JSON，实测 {json_status}")
                continue
            if payload.get("reportPath") != REPORT_PAGE_PATH or payload.get("token") != expected_token:
                report.add(
                    "shortlink-json-parity",
                    FAIL,
                    f"{path}/json 与 302 面不一致（reportPath={payload.get('reportPath')!r} token 相同={payload.get('token') == expected_token}）",
                )
                continue
            report.add("shortlink-json-parity", OK, f"{path}/json 与 302 的 token 逐字一致")
        report.add(f"tenant-binding-{label}", OK, f"{path} → tenant_code={actual}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="试用客户上线前的只读开通面判据（不登录、不写盘）")
    parser.add_argument("--enterprise-code", default="", help="企业编码（tenants.code，登录用；缺 ⇒ rc=3）")
    parser.add_argument("--app-base", default="https://app.migaozn.com", help="应用域（/terminal /b/ /w/ /s/ /o/）")
    parser.add_argument("--site-base", default="https://migaozn.com", help="官网域（/download）")
    parser.add_argument("--worker-code", default="", help="纸上真实的工人短码（8 位 Crockford Base32）")
    parser.add_argument("--order-code", default="", help="加工单纸上的短码（8 位 Crockford Base32）")
    parser.add_argument("--timeout", type=float, default=15.0, help="单次请求超时秒（默认 15）")
    args = parser.parse_args(argv)

    app = args.app_base.rstrip("/")
    site = args.site_base.rstrip("/")
    enterprise_code = args.enterprise_code.strip().lower()
    report = Report()

    print("TRIAL-ONBOARDING-CHECK（只读：全部 GET/HEAD，无登录、无 POST、无写盘）")
    print(f"  app={app}  site={site}  enterprise_code={enterprise_code or '(未给)'}  {time.strftime('%Y-%m-%d %H:%M:%S %z')}")
    print("\n[1] 建号 / 租户（入参形态）")
    if not enterprise_code:
        report.add("enterprise-code", UNKNOWN, "缺 --enterprise-code ⇒ 无法核对这家企业的码归属（缺配置不是绿）")
    elif not TENANT_CODE_PATTERN.match(enterprise_code):
        report.add("enterprise-code", FAIL, f"{enterprise_code} 不符合 ^[a-z0-9][a-z0-9_-]{{1,31}}$")
    elif enterprise_code in RESERVED_TENANT_CODES:
        report.add("enterprise-code", FAIL, f"{enterprise_code} 是保留字（全平台不可占用）")
    else:
        report.add("enterprise-code", OK, enterprise_code)

    print("\n[2] 终端下载面（/download + /terminal）")
    status, headers, body, error = _request(site + "/download", args.timeout)
    if status is None:
        report.add("download-page", UNKNOWN, f"{site}/download 探不到（{error}）")
    elif status != 200:
        report.add("download-page", FAIL, f"{site}/download 期望 200，实测 {status}")
    elif DOWNLOAD_MARKER not in body.decode("utf-8", "replace"):
        # 假 200 形态：SPA fallback / 别的站点内容。app 域的 /download 就是这样一页。
        report.add("download-page", FAIL, f"{site}/download 200 但正文不含「{DOWNLOAD_MARKER}」（像是 SPA fallback）")
    else:
        report.add("download-page", OK, f"200 text/html，正文含「{DOWNLOAD_MARKER}」（{len(body)} bytes）")

    status, headers, _, error = _request(app + "/terminal", args.timeout)
    if status is None:
        report.add("terminal-dir-redirect", UNKNOWN, f"{app}/terminal 探不到（{error}）")
    elif status != 301:
        report.add("terminal-dir-redirect", FAIL, f"{app}/terminal 期望 301，实测 {status}")
    elif not _header(headers, "Location").rstrip("/").endswith("/terminal"):
        report.add("terminal-dir-redirect", FAIL, f"301 落点异常：{_header(headers, 'Location')}")
    else:
        report.add("terminal-dir-redirect", OK, f"301 → {_header(headers, 'Location')}")

    check_manifest(report, "windows-manifest", app, "/terminal/latest.json", args.timeout, android=False)
    check_manifest(report, "android-manifest", app, "/terminal/android/latest.json", args.timeout, android=True)

    print("\n[3] 小程序 / H5 面（扫码落点）")
    for name, path, want_csp in (
        ("bmini-report-page", "/b/report/", True),
        ("worker-h5-page", "/w/", True),
    ):
        status, headers, _, error = _request(app + path, args.timeout)
        if status is None:
            report.add(name, UNKNOWN, f"{path} 探不到（{error}）")
            continue
        if status != 200:
            report.add(name, FAIL, f"{path} 期望 200，实测 {status}")
            continue
        report.add(name, OK, f"200 {_header(headers, 'Content-Type')}")
        check_headers(report, path.strip("/").replace("/", "-"), headers, want_csp=want_csp)

    print("\n[4] 二维码（短码面）")
    status, headers, body, error = _request(f"{app}/s/{UNKNOWN_SHORT_CODE}/json", args.timeout)
    if status is None:
        report.add("shortlink-json-contract", UNKNOWN, f"/s/<未知>/json 探不到（{error}）")
    elif status != 404:
        report.add("shortlink-json-contract", FAIL, f"/s/{UNKNOWN_SHORT_CODE}/json 期望 404，实测 {status}")
    elif "json" not in _header(headers, "Content-Type").lower():
        report.add("shortlink-json-contract", FAIL, f"404 的 Content-Type 不是 JSON（{_header(headers, 'Content-Type') or '空'}）")
    else:
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            payload = {}
        if payload.get("error") != "not_found":
            report.add("shortlink-json-contract", FAIL, f"404 体不是 {{\"error\":\"not_found\"}}：{body[:80]!r}")
        else:
            report.add("shortlink-json-contract", OK, "未知码 ⇒ 404 application/json + not_found")
    check_tenant_binding(report, app, enterprise_code, args.timeout, args.worker_code.strip().upper(), args.order_code.strip().upper())

    print("\n[5] 安全头（HSTS / nosniff / CSP —— 三个 localStorage 会话面的基线）")
    status, headers, _, error = _request(site + "/download", args.timeout)
    if status is None:
        report.add("headers-site-download", UNKNOWN, f"探不到（{error}）")
    else:
        check_headers(report, "site-download", headers, want_csp=False)

    print("\n提示：安全头的**深度**判定（max-age 下限 / CSP 形态 / 各域全覆盖）由 "
          "deploy/scripts/prod-security-headers.sh 承担，本脚本只判开通链路上的这几面。")
    print("提示：签名现状（Windows Authenticode / APK apksigner）公网读不到 ⇒ 本脚本**不**给签名结论，"
          "见 runbook §2.3。")
    return report.verdict()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
