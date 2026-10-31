# case_ids: MC-012
# （沿用 `tests/unit_ci_workflows/**` 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 `.github/cases/misc.yml` 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""试用客户上线 runbook 的**可执行判据**（issue #8218 目标①：先 1~2 家试用客户）。

## 被判的对象（两件，缺一件就等于没判）

| 对象 | 位置 | 它必须满足什么 |
|---|---|---|
| 只读判据 | `scripts/trial_onboarding_check.py` | 三态 `0/1/3`、**只读**（无登录/无 POST/无写盘）、把「缺配置」判成 `3` 而不是绿 |
| runbook | `docs/deployment/trial-onboarding.md` | 命令**逐字**指向那个脚本（判据存在但没人跑 = 假绿）；索引里可达 |

## 为什么要有这一组判据（病，逐条线上形态）

2026-10-31 上线审计（#8200）里反复出现的形态是**「面看着正常、扫下去是错的」**：

- `app.migaozn.com/download` 实测 **200**，但那是 C 端 SPA fallback（~507 字节的一页），
  不是下载页 —— **只看状态码的验收会在这里假绿**。真正的下载页在裸域 `migaozn.com/download`。
- `/terminal` 裸前缀若没有 301，同样落 SPA fallback ⇒ 缺失文件也回 200，客户端把 HTML 当清单解析。
- 终端清单还可能**没发布**（线上实测 `/terminal/latest.json` = 404）—— 它既不是「绿」（终端装不上），
  也不该被当成「上线缺陷」（是开通前置未执行）⇒ 必须落 `3`，而 `3` **不得当 0 读**。
- 企业编码归属是试用期最该核的**数据边界**：纸上的码 302 落点里必须写着**这家**企业
  （`/s/<码>/json` 面上**故意**没有 tenant_code，只有 302 面有）⇒ 没有一张印出来的码就**判定不了**，
  同样落 `3`。

## 判据（每条都能单独变红；红证 = 下面 `test_…red…` 系列，各改**一个**条件）

| # | 判据 | 变红形态 |
|---|---|---|
| 1 | 全好 ⇒ `rc=0`，且每条判据都出现在输出里 | 少判了一条 ⇒ 红 |
| 2 | 清单**未发布**（404）⇒ `rc=3`（不是 0、也不是 1） | 把 404 读成通过 / 读成缺陷 ⇒ 红 |
| 3 | 清单语义坏（`sha256` 非 64 位十六进制）⇒ `rc=1` | 只判 200 不判语义 ⇒ 红 |
| 4 | 清单 `size` 与载荷 `Content-Length` 不一致 ⇒ `rc=1` | 「清单说有、下载对不上」是终端侧失败而服务器无感 ⇒ 红 |
| 5 | `/terminal` 回 200（不是 301）⇒ `rc=1` | 裸前缀落 SPA fallback ⇒ 红 |
| 6 | `/download` 200 但正文不含真页面标记（SPA fallback）⇒ `rc=1` | 只看状态码 ⇒ 红（线上真有这一页） |
| 7 | 未知短码 `/s/<码>/json` 回 200 ⇒ `rc=1` | 小程序的 A 档会把未知码当有效码 ⇒ 红 |
| 8 | 缺 HSTS（`/w/`）⇒ `rc=1` | 会话摆在 localStorage，缺 HSTS = 可降级 ⇒ 红 |
| 9 | 工人短码落点是**别家**企业 ⇒ `rc=1`（数据边界） | 只判 302 不判归属 ⇒ 红 |
| 10 | worker 短码 `302` 的 token 与 `/s/<码>/json` 不一致 ⇒ `rc=1` | A 档拿到旧 token ⇒ 红 |
| 11 | 缺 `--enterprise-code` ⇒ `rc=3`，但静态面**照跑**（不因缺配置而少判） | 直接 exit 3 什么都不判 ⇒ 红 |
| 12 | 连不上 ⇒ `rc=3`（不是 0） | 网络异常读成通过 ⇒ 红 |
| 13 | 脚本**只读**：源码里没有 POST 载荷、没有 `open(`、没有子进程 | 判据自己变成写操作 ⇒ 红 |
| 14 | **接线**：runbook 里那条命令逐字指向本脚本 + `docs/wiki/INDEX.md` 可达 + 文档声明三态语义 | 文档写了别的命令 / 索引不可达 ⇒ 红 |

## 复算

```bash
python3 -m pytest tests/unit_ci_workflows/test_trial_onboarding_check.py -q
python3 scripts/trial_onboarding_check.py --enterprise-code <企业编码> --worker-code <纸上短码>
```
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "trial_onboarding_check.py"
RUNBOOK = REPO / "docs" / "deployment" / "trial-onboarding.md"
INDEX = REPO / "docs" / "wiki" / "INDEX.md"

ENTERPRISE_CODE = "acme-fabric"
WORKER_CODE = "7K3M9QP2"
ORDER_CODE = "4HX2W9TD"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════
# 本机 stub：把「线上公开面」压成一个可改单点的 responder
# ══════════════════════════════════════════════════════════════════════════


class _Stub(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    #: 每次测试由 `stub` fixture 重置为下面这份基线（测试只改自己要变红的那**一个**键）
    cfg: dict = {}

    DEFAULTS = {
        "download_body": "<html><title>下载中心 — 观星台终端</title>观星台终端安装包</html>",
        "terminal_status": 301,
        "manifest_status": 200,
        "android_status": 200,
        "manifest_overrides": {},
        "payload_length": 1024,
        "json_status": 404,
        "headers": True,
        "worker_tenant_code": ENTERPRISE_CODE,
        "worker_token": "tok-abc123",
        "json_token": "tok-abc123",
        "order_status": 302,
    }

    # ── 工具 ────────────────────────────────────────────────────────────
    def _send(self, status: int, body: bytes = b"ok", *, content_type: str = "text/html",
              extra: dict | None = None) -> None:
        self.send_response(status)
        headers = {"content-type": content_type}
        if self.cfg["headers"]:
            headers["strict-transport-security"] = "max-age=31536000; includeSubDomains"
            headers["x-content-type-options"] = "nosniff"
            headers["content-security-policy"] = "default-src 'self'; script-src 'self'"
        headers.update(extra or {})
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _manifest(self) -> dict:
        base = {
            "version": "1.0.1.0",
            "download_url": f"http://127.0.0.1:{self.server.server_address[1]}/terminal/GuanxingtaiSetup.exe",
            "sha256": "a" * 64,
            "size": self.cfg["payload_length"],
            "notes": "首个发布版",
            "published_at": "2026-10-31",
        }
        base.update(self.cfg["manifest_overrides"])
        return base

    # ── 路由 ────────────────────────────────────────────────────────────
    def do_HEAD(self):  # noqa: N802 - BaseHTTPRequestHandler 的接口
        if self.path.endswith((".exe", ".apk")):
            self._send(200, b"", content_type="application/octet-stream",
                       extra={"content-length": str(self.cfg["payload_length"])})
        else:
            self._send(404, b"")

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        cfg = self.cfg

        if path == "/download":
            self._send(200, cfg["download_body"].encode())
        elif path == "/terminal":
            if cfg["terminal_status"] == 301:
                self._send(301, b"", extra={"location": "/terminal/"})
            else:
                self._send(cfg["terminal_status"], b"<html>spa fallback</html>")
        elif path == "/terminal/latest.json":
            if cfg["manifest_status"] != 200:
                self._send(cfg["manifest_status"], b"not found")
            else:
                self._send(200, json.dumps(self._manifest()).encode(), content_type="application/json")
        elif path == "/terminal/android/latest.json":
            if cfg["android_status"] != 200:
                self._send(cfg["android_status"], b"not found")
            else:
                body = {
                    "versionCode": 7,
                    "versionName": "1.0.1",
                    "download_url": f"http://127.0.0.1:{self.server.server_address[1]}/terminal/GuanxingtaiTerminal-1.0.1.apk",
                    "sha256": "b" * 64,
                    "size": cfg["payload_length"],
                    "notes": "首个发布版",
                    "published_at": "2026-10-31",
                }
                body.update(cfg["manifest_overrides"])
                self._send(200, json.dumps(body).encode(), content_type="application/json")
        elif path in ("/b/report/", "/w/"):
            self._send(200, b"<html>page</html>")
        elif path.startswith("/s/") and path.endswith("/json"):
            code = path[len("/s/"):-len("/json")]
            if code == WORKER_CODE:
                # 真实短码的 A 档 JSON 面（与 302 面同一份 token）
                self._send(
                    200,
                    json.dumps({"reportPath": "/b/report/", "token": cfg["json_token"]}).encode(),
                    content_type="application/json",
                )
            elif cfg["json_status"] == 404:
                self._send(404, b'{"error":"not_found"}', content_type="application/json")
            else:
                self._send(
                    200,
                    json.dumps({"reportPath": "/b/report/", "token": cfg["json_token"]}).encode(),
                    content_type="application/json",
                )
        elif path.startswith("/s/"):
            self._send(
                302,
                b"",
                extra={
                    "location": f"/b/report/?t={cfg['worker_token']}&tenant_id=1&tenant_code={cfg['worker_tenant_code']}"
                },
            )
        elif path.startswith("/o/"):
            if cfg["order_status"] != 302:
                self._send(cfg["order_status"], b"")
            else:
                self._send(
                    302,
                    b"",
                    extra={
                        "location": f"/b/report/?t={cfg['worker_token']}&tenant_id=1&tenant_code={cfg['worker_tenant_code']}"
                    },
                )
        else:
            self._send(404, b"")

    def log_message(self, *args):  # 静音（stub 不污染测试输出）
        return


@pytest.fixture()
def stub():
    _Stub.cfg = dict(_Stub.DEFAULTS)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _run(base: str, *extra: str, timeout: int = 120, script: Path | None = None):
    args = [
        sys.executable,
        str(script or SCRIPT),
        "--app-base",
        base,
        "--site-base",
        base,
        "--timeout",
        "10",
        *extra,
    ]
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


# ══════════════════════════════════════════════════════════════════════════
# 一、三态 + 逐条判据（判据 1~12）
# ══════════════════════════════════════════════════════════════════════════


def test_green_when_every_face_is_complete(stub):
    out = _run(stub, "--enterprise-code", ENTERPRISE_CODE, "--worker-code", WORKER_CODE, "--order-code", ORDER_CODE)
    assert out.returncode == 0, f"{out.stdout}\n{out.stderr}"
    assert "TRIAL-ONBOARDING-SUMMARY rc=0" in out.stdout
    # 判据一条都不许缺（少判一条 = 覆盖面缩水，但汇总照样绿 —— 那正是最坏的假绿形态）
    for name in (
        "enterprise-code",
        "download-page",
        "terminal-dir-redirect",
        "windows-manifest",
        "android-manifest",
        "bmini-report-page",
        "worker-h5-page",
        "shortlink-json-contract",
        "shortlink-json-parity",
        "tenant-binding-worker",
        "tenant-binding-order",
        "headers-site-download",
        "headers-b-report",
        "headers-w",
    ):
        assert name in out.stdout, f"判据 `{name}` 没出现在输出里：\n{out.stdout}"


def test_red_when_manifest_not_published(stub):  # noqa: D401 - 名字即判据
    """判据 2：**未发布** ⇒ rc=3（既不是绿，也不是上线缺陷）。"""
    _Stub.cfg["manifest_status"] = 404
    _Stub.cfg["android_status"] = 404
    out = _run(stub, "--enterprise-code", ENTERPRISE_CODE, "--worker-code", WORKER_CODE)
    assert out.returncode == 3, f"清单未发布必须退 3（3 不得当 0 读），实测 {out.returncode}\n{out.stdout}"
    assert "TRIAL-ONBOARDING-SUMMARY rc=3" in out.stdout
    assert "未发布" in out.stdout


def test_red_when_manifest_semantics_are_broken(stub):
    """判据 3：`sha256` 不是 64 位十六进制 ⇒ rc=1（只判 200 会漏）。"""
    _Stub.cfg["manifest_overrides"] = {"sha256": "deadbeef"}
    out = _run(stub, "--enterprise-code", ENTERPRISE_CODE, "--worker-code", WORKER_CODE)
    assert out.returncode == 1, f"清单语义坏必须判红，实测 {out.returncode}\n{out.stdout}"
    assert "windows-manifest" in out.stdout and "sha256" in out.stdout


def test_red_when_manifest_size_disagrees_with_payload(stub):
    """判据 4：清单 `size` ≠ 载荷 `content-length` ⇒ rc=1（终端下载后校验失败，服务器侧无感）。"""
    _Stub.cfg["manifest_overrides"] = {"size": 999999999}
    out = _run(stub, "--enterprise-code", ENTERPRISE_CODE, "--worker-code", WORKER_CODE)
    assert out.returncode == 1, f"清单与载荷对不上必须判红，实测 {out.returncode}\n{out.stdout}"
    assert "content-length" in out.stdout


def test_red_when_terminal_prefix_is_not_a_redirect(stub):
    """判据 5：`/terminal` 回 200 ⇒ 裸前缀落 SPA fallback ⇒ rc=1。"""
    _Stub.cfg["terminal_status"] = 200
    out = _run(stub, "--enterprise-code", ENTERPRISE_CODE, "--worker-code", WORKER_CODE)
    assert out.returncode == 1, f"{out.stdout}"
    assert "terminal-dir-redirect" in out.stdout and "301" in out.stdout


def test_red_when_download_page_is_a_200_spa_fallback(stub):
    """判据 6：`/download` 200 但正文是 SPA fallback ⇒ rc=1（线上真有这一页）。"""
    _Stub.cfg["download_body"] = "<html><div id=\"app\"></div></html>"
    out = _run(stub, "--enterprise-code", ENTERPRISE_CODE, "--worker-code", WORKER_CODE)
    assert out.returncode == 1, f"{out.stdout}"
    assert "download-page" in out.stdout and "SPA fallback" in out.stdout


def test_red_when_unknown_shortlink_json_is_200(stub):
    """判据 7：未知短码的 JSON 面回 200 ⇒ 小程序 A 档会把未知码当有效码 ⇒ rc=1。"""
    _Stub.cfg["json_status"] = 200
    out = _run(stub, "--enterprise-code", ENTERPRISE_CODE, "--worker-code", WORKER_CODE)
    assert out.returncode == 1, f"{out.stdout}"
    assert "shortlink-json-contract" in out.stdout


def test_red_when_hsts_is_missing(stub):
    """判据 8：`/w/` 缺 HSTS ⇒ rc=1（三个前端都把会话摆在 localStorage）。"""
    _Stub.cfg["headers"] = False
    out = _run(stub, "--enterprise-code", ENTERPRISE_CODE, "--worker-code", WORKER_CODE)
    assert out.returncode == 1, f"{out.stdout}"
    assert "strict-transport-security" in out.stdout


def test_red_when_short_code_points_to_another_tenant(stub):
    """判据 9：工人短码落点是**别家**企业 ⇒ 数据边界破了 ⇒ rc=1。"""
    _Stub.cfg["worker_tenant_code"] = "someone-else"
    out = _run(stub, "--enterprise-code", ENTERPRISE_CODE, "--worker-code", WORKER_CODE)
    assert out.returncode == 1, f"{out.stdout}"
    assert "tenant-binding-worker" in out.stdout and "someone-else" in out.stdout


def test_red_when_json_token_disagrees_with_302(stub):
    """判据 10：A 档 JSON 面的 token 与 302 面不一致 ⇒ rc=1（拿到旧 token = 报工失败）。"""
    _Stub.cfg["json_token"] = "tok-stale"
    out = _run(stub, "--enterprise-code", ENTERPRISE_CODE, "--worker-code", WORKER_CODE)
    assert out.returncode == 1, f"{out.stdout}"
    assert "shortlink-json-parity" in out.stdout and "不一致" in out.stdout


def test_unknown_when_enterprise_code_is_absent_but_static_faces_still_judged(stub):
    """判据 11：缺 `--enterprise-code` ⇒ rc=3，**但静态面照跑**（不许「缺配置就什么都不判」）。"""
    out = _run(stub)
    assert out.returncode == 3, f"缺配置必须退 3（不得绿），实测 {out.returncode}\n{out.stdout}"
    assert "TRIAL-ONBOARDING-SUMMARY rc=3" in out.stdout
    assert "download-page" in out.stdout and "✅" in out.stdout
    assert "enterprise-code" in out.stdout


def test_unknown_when_unreachable():
    """判据 12：连不上 ⇒ rc=3（不是 0、也不是 1）。"""
    out = _run("http://127.0.0.1:1", "--enterprise-code", ENTERPRISE_CODE)
    assert out.returncode == 3, f"连不上必须退 3，实测 {out.returncode}\n{out.stdout}"
    assert "TRIAL-ONBOARDING-SUMMARY rc=3" in out.stdout


# ══════════════════════════════════════════════════════════════════════════
# 二、判据 13：脚本**只读**（判据自己变成写操作 = 最讽刺的缺陷）
# ══════════════════════════════════════════════════════════════════════════


def test_check_script_is_read_only():
    src = _read(SCRIPT)
    forbidden = {
        "subprocess": "不许起子进程（那是另一条会写盘/写库的路径）",
        "data=": "HTTP 请求不许带请求体（带体 = POST/PUT 语义）",
        'method="POST"': "不许 POST",
        'method="PUT"': "不许 PUT",
        'method="DELETE"': "不许 DELETE",
        "requests.": "只用标准库（不给判据引入网络客户端的第二份实现）",
        "shutil": "不许有删除动作",
        "os.remove": "不许删除",
        "unlink(": "不许删除",
    }
    hits = [f"{token} → {why}" for token, why in forbidden.items() if token in src]
    # 内置 `open(` = 读写本地文件；`_OPENER.open(` 是 urllib 的请求方法，不算（用负向前瞻区分）
    if re.search(r"(?<![.\w])open\(", src):
        hits.append("open( → 不许写/读本地文件（判据只读，证据只在终端输出里）")
    assert not hits, "只读判据被写成了会改状态的脚本：\n- " + "\n- ".join(hits)
    # 登录探测是**写**行为（`LoginFailureGuard` 会累计失败次数 ⇒ 锁号）—— 判据里一个都不许有
    assert "/api/auth/" not in src, "判据里不许出现登录端点（登录失败会触发锁号）"
    assert "/api/worker/login" not in src, "判据里不许出现工人登录端点"


# ══════════════════════════════════════════════════════════════════════════
# 三、判据 14：接线（判据存在但没人跑 = 假绿）
# ══════════════════════════════════════════════════════════════════════════


def test_runbook_exists_and_commands_point_at_the_real_script():
    assert RUNBOOK.exists(), f"runbook 不在：{RUNBOOK}"
    doc = _read(RUNBOOK)
    # ① 命令必须逐字指向本脚本（写成别名/别的路径 ⇒ 人手跑的时候跑不到）
    assert "scripts/trial_onboarding_check.py" in doc, "runbook 没有指向 scripts/trial_onboarding_check.py"
    commands = [line for line in doc.splitlines() if "trial_onboarding_check.py" in line and "--enterprise-code" in line]
    assert commands, "runbook 里没有一条带 --enterprise-code 的可复制命令"
    # ② 三态语义必须写清（`3` 不得当 `0` 读 —— 这是本判据最容易被读错的一格）
    assert "rc=3" in doc or "`3`" in doc, "runbook 没有写三态退出码"
    assert "不得当" in doc and "0" in doc, "runbook 没有写「3 不得当 0 读」"


def test_index_links_the_runbook():
    index = _read(INDEX)
    assert "trial-onboarding.md" in index, "docs/wiki/INDEX.md 里没有 trial-onboarding.md（索引不可达 = 事实上找不到）"
    assert "trial-onboarding" in index, "索引条目缺名"


def test_runbook_records_the_external_steps_it_cannot_verify():
    """runbook 必须**如实登记**它自己判不了的外部项（否则读者会以为脚本绿了就能开通）。"""
    doc = _read(RUNBOOK)
    for anchor in ("微信后台", "签名", "WebView2", "未知来源"):
        assert anchor in doc, f"runbook 缺少外部项登记：{anchor}"
    # 终端清单没发布时不许写成「通过」——这条与判据 2 同源，写进文档才算闭环
    assert "未发布" in doc, "runbook 没有写「清单未发布」这一态该怎么读"


# ══════════════════════════════════════════════════════════════════════════
# 四、判据 15：注入式自证 —— 红是**判据代码**造成的，不是 stub 造成的
# ══════════════════════════════════════════════════════════════════════════


def test_injection_a_blind_judgment_goes_green_on_the_same_stub(tmp_path, stub):
    """把「`/download` 正文必须含真页面标记」这一条改瞎 ⇒ 同一个 stub 上原判据红、瞎判据绿。

    这是「红证」的另一半：判据 6 的红**不是** stub 环境造成的 —— 换掉那一行判断，同样的输入就不再红。
    """
    _Stub.cfg["download_body"] = "<html><div id=\"app\"></div></html>"  # 真实缺陷：SPA fallback 假 200

    real = _run(stub, "--enterprise-code", ENTERPRISE_CODE, "--worker-code", WORKER_CODE)
    assert real.returncode == 1, f"原判据必须抓住这个缺陷：\n{real.stdout}"
    assert "SPA fallback" in real.stdout

    src = _read(SCRIPT)
    blind = src.replace('elif DOWNLOAD_MARKER not in body.decode("utf-8", "replace"):', "elif False:")
    assert blind != src, "注入没生效（脚本里已没有那一行判断）—— 先自证注入成功再谈红证"
    mutated = tmp_path / "trial_onboarding_check_blind.py"
    mutated.write_text(blind, encoding="utf-8")

    out = _run(stub, "--enterprise-code", ENTERPRISE_CODE, "--worker-code", WORKER_CODE, script=mutated)
    assert out.returncode == 0, (
        "判据被改瞎后仍然判红 ⇒ 那这条红来自别处（stub / 其它判据），本条红证不成立：\n" + out.stdout
    )


# ══════════════════════════════════════════════════════════════════════════
# 五、判据 16：本测试自己声明的 case_ids 在测试头 50 行内（QA Growth Gate 硬约束 A）
# ══════════════════════════════════════════════════════════════════════════


def test_case_ids_declared_within_head():
    head = "\n".join(_read(Path(__file__)).splitlines()[:50])
    assert re.search(r"^\s*#\s*case_ids\s*[:=]\s*MC-\d+", head, re.MULTILINE), (
        "case_ids 必须在文件前 50 行、且是**注释起始**的声明行（docstring 里提及不算）"
    )
