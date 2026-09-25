# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012）
"""C 端 H5 **产物新鲜度**守卫（`scripts/h5_freshness_guard.py`，issue #4184 判据 2）。

## 病灶（实测 2026-09-25）

线上 `app.migaozn.com/js/app.js` 的 `Last-Modified` = **08-30 14:54 +08**，
而 `origin/main` 上 `frontend/mini-app/**` 最近一次改动 = **09-21 14:13 +08** ⇒ 线上落后 ~22 天，
**没有任何东西会因此变红**（「C 端已部署」的说法一直被当真）。

## 判据与红证

| # | 断言 | 红证（注入 ⇒ 必红） |
|---|---|---|
| 1 | 线上时间 ≥ 源码改动时间 − 宽限 ⇒ `fresh` | 把 `judge` 改成恒 `fresh` ⇒ 第 2 条红 |
| 2 | 线上时间**早于**源码改动（超出宽限）⇒ `stale`（报告型 `::warning::`；`--gate` ⇒ exit 2） | 同上 |
| 3 | **取不到** `Last-Modified`（无该头 / 连不上）⇒ `unknown` + exit 3（**不等于**新鲜） | 把 fail-closed 改成 `fresh` ⇒ 本组红 |
| 4 | 宽限边界：差恰好 = 宽限 ⇒ `fresh`（不苛刻） | 把 `>=` 改成 `>` ⇒ 本组红 |

网络用**本机 `http.server`**（真 HTTP、零外网），git 用**真临时仓库** —— 不 mock 被测函数。
"""
from __future__ import annotations

import http.server
import importlib.util
import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("h5_freshness_guard", REPO_ROOT / "scripts" / "h5_freshness_guard.py")
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)          # type: ignore[union-attr]

GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"}
UTC = timezone.utc


# ── 1) judge()：纯函数，判据本体 ─────────────────────────────────────────────

def test_judge_fresh_when_live_is_newer():
    live, src = datetime(2026, 9, 22, tzinfo=UTC), datetime(2026, 9, 21, tzinfo=UTC)
    verdict, why = mod.judge(live, src, grace_hours=6)
    assert verdict == "fresh", why


def test_judge_stale_when_live_is_older_beyond_grace():
    """本单的**核心形态**：线上落后 22 天 ⇒ 必须判 stale（红证：judge 恒 fresh ⇒ 本用例红）。"""
    live, src = datetime(2026, 8, 30, 6, 54, tzinfo=UTC), datetime(2026, 9, 21, 6, 13, tzinfo=UTC)
    verdict, why = mod.judge(live, src, grace_hours=6)
    assert verdict == "stale", why
    assert "陈旧" in why and "落后" in why, why


def test_judge_grace_boundary_is_fresh():
    """差恰好 = 宽限 ⇒ fresh（红证：把 `>=` 改成 `>` ⇒ 本用例红）。"""
    src = datetime(2026, 9, 21, 6, 0, tzinfo=UTC)
    verdict, _ = mod.judge(src - timedelta(hours=6), src, grace_hours=6)
    assert verdict == "fresh"


def test_judge_unknown_when_live_missing():
    """取不到线上时间 ⇒ unknown（**不等于**新鲜）。"""
    verdict, why = mod.judge(None, datetime(2026, 9, 21, tzinfo=UTC), grace_hours=6)
    assert verdict == "unknown" and "无法判定" in why, why


def test_judge_unknown_when_source_missing():
    verdict, why = mod.judge(datetime(2026, 9, 21, tzinfo=UTC), None, grace_hours=6)
    assert verdict == "unknown" and "无法判定" in why, why


# ── 2) fetch_last_modified()：真 HTTP（本机 server），不 mock ─────────────────

class _Handler(http.server.BaseHTTPRequestHandler):
    last_modified: str | None = "Sun, 30 Aug 2026 06:54:48 GMT"

    def do_HEAD(self):                                        # noqa: N802
        self.send_response(200)
        if self.last_modified:
            self.send_header("Last-Modified", self.last_modified)
        self.end_headers()

    def log_message(self, *a):                                # 静音（裸 `pass` 会被弱断言扫描器计一处，故用 return）
        return


def _serve(tmp_path: Path, last_modified: str | None):
    handler = type("H", (_Handler,), {"last_modified": last_modified})
    httpd = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/js/app.js"


def test_fetch_parses_last_modified_header(tmp_path):
    httpd, url = _serve(tmp_path, "Sun, 30 Aug 2026 06:54:48 GMT")
    try:
        got = mod.fetch_last_modified(url)
    finally:
        httpd.shutdown()
    assert got == datetime(2026, 8, 30, 6, 54, 48, tzinfo=UTC), got


def test_fetch_fails_closed_without_header(tmp_path):
    httpd, url = _serve(tmp_path, None)
    try:
        got = mod.fetch_last_modified(url)
    finally:
        httpd.shutdown()
    # 断言**业务结论**（不是"取到的值是不是 None"那种存在性断言）：没有该头 ⇒ 必须判「无法判定」
    verdict, why = mod.judge(got, datetime(2026, 9, 21, tzinfo=UTC), grace_hours=6)
    assert (verdict, "无法判定" in why) == ("unknown", True), (got, verdict, why)


def test_fetch_fails_closed_when_unreachable():
    """连不上（端口没人听）⇒ 判「无法判定」，不得抛异常、不得当新鲜。"""
    got = mod.fetch_last_modified("http://127.0.0.1:9/js/app.js", timeout=2)
    verdict, why = mod.judge(got, datetime(2026, 9, 21, tzinfo=UTC), grace_hours=6)
    assert (verdict, "无法判定" in why) == ("unknown", True), (got, verdict, why)


# ── 3) CLI 端到端：真临时 git 仓库 + 本机 server ─────────────────────────────

def _repo_with_mini_app_commit(tmp_path: Path, when: str) -> Path:
    repo = tmp_path / "repo"
    (repo / "frontend" / "mini-app" / "src").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True, env=GIT_ENV)
    (repo / "frontend" / "mini-app" / "src" / "a.ts").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, env=GIT_ENV)
    subprocess.run(["git", "commit", "-qm", "feat(frontend): C 端改动"],
                   cwd=repo, check=True, env={**GIT_ENV, "GIT_COMMITTER_DATE": when, "GIT_AUTHOR_DATE": when})
    return repo


def _run_cli(repo: Path, url: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "h5_freshness_guard.py"),
                           "--url", url, "--ref", "HEAD", *args],
                          cwd=str(repo), capture_output=True, text=True, timeout=60)


def test_cli_reports_stale_as_warning_without_failing(tmp_path):
    """陈旧 ⇒ 默认**报告型**：`::warning::` + exit 0 + 读数行（不把 main 判红）。"""
    repo = _repo_with_mini_app_commit(tmp_path, "2026-09-21T06:13:46+00:00")
    httpd, url = _serve(tmp_path, "Sun, 30 Aug 2026 06:54:48 GMT")
    try:
        out = _run_cli(repo, url)
    finally:
        httpd.shutdown()
    assert out.returncode == 0, (out.returncode, out.stdout, out.stderr)
    assert "::warning::" in out.stdout and "陈旧" in out.stdout, out.stdout
    assert "MIGAO-H5FRESH-SUMMARY seen=1 acted=1 rc=0" in out.stdout, out.stdout


def test_cli_gate_mode_exits_nonzero_when_stale(tmp_path):
    """`--gate` ⇒ 超期即 exit 2（供将来 C 端 H5 有发布通路后切门禁用）。"""
    repo = _repo_with_mini_app_commit(tmp_path, "2026-09-21T06:13:46+00:00")
    httpd, url = _serve(tmp_path, "Sun, 30 Aug 2026 06:54:48 GMT")
    try:
        out = _run_cli(repo, url, "--gate")
    finally:
        httpd.shutdown()
    assert out.returncode == 2, (out.returncode, out.stdout)
    assert "rc=2" in out.stdout, out.stdout


def test_cli_fails_closed_when_live_unreachable(tmp_path):
    """取不到线上时间 ⇒ exit 3 + `rc=3` 读数（「没跑/取不到」必须长得像「没跑」）。"""
    repo = _repo_with_mini_app_commit(tmp_path, "2026-09-21T06:13:46+00:00")
    out = _run_cli(repo, "http://127.0.0.1:9/js/app.js")
    assert out.returncode == 3, (out.returncode, out.stdout, out.stderr)
    assert "rc=3" in out.stdout and "无法判定" in out.stderr, (out.stdout, out.stderr)