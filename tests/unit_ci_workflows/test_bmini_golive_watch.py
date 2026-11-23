# case_ids: BM-069
r"""B 端上线值守（`scripts/bmini-golive-watch.sh`）的判据（issue #9072）。

## 病（本单要治的形态）

B 端小程序 v1.0.2 已上线（2026-11-23 10:49:54 发布），而「B 端线上是否健康 / 是否落后本仓库」
**没有一个一眼看全的只读读数**：要分别跑 `deploy/scripts/prod-smoke.sh`（八面 + 身份 + 域名泄漏）、
两个版本身份探针、再看 `deploy/scripts/bmini-dist-budget.json` 的台账。**漏一面就以为「没事」**，
而三类缺口恰好都是「没人会想起来单独跑」的：① 某一面 502；② 线上 sha 落后 `origin/release`；
③ 下一次发版会撞包体上限。

## 本文件锁什么（每条都能单独变红；判据本体 = `scripts/bmini-golive-watch.sh`）

| # | 判据 | 红证（本文件实跑） |
|---|---|---|
| 1 | **五个面各自可判**：健康 / 版本身份 / 域名泄漏 / 包体预算 / 客户端错误；每面一行 `PASS`/`FAIL`/`SKIP` | 桩 curl 逐面喂红 ⇒ 对应面变 `FAIL`（用例 3/5/7/8） |
| 2 | **网络失败 ⇒ `SKIP`，不是 `PASS`**（人工值守时本机离线不该被读成「B 端坏了」，更不能被读成「好的」） | 从桩表里摘掉 `https://app.cytda.com/b/` ⇒ 该行 `SKIP`、`rc=3`、且**没有**它的 `PASS` 行 |
| 3 | **退出码三态**：`0` 全通过 / `1` 有 FAIL（**优先于** SKIP）/ `3` 有 SKIP 无 FAIL | 绿表 + 子集四面 ⇒ `0`；缺一面 ⇒ `3`；改坏一面 ⇒ `1`（若同时有 SKIP 仍 `1`） |
| 4 | **无 C 端面**：脚本与它的委托面都不得探 `app.*` 的 h5 根、`/w/`、`frontend/mini-app` | 静态扫脚本正文；再从桩日志取 `faces=health` 与 `faces=leak` 实际请求的 URL 集合，断言不含 C 端面 |
| 5 | **复用既有的判据本体，不抄第二份**：版本身份 = 两个既有探针；域名泄漏 = `prod-smoke.sh` 的泄漏段；包体 = 预算台账 | 静态断言三处引用都在；`2097152` / `1887436`（上限常量）在脚本里**一个都不许出现** |
| 6 | **`SMOKE_ONLY` 缺省仍是三段全跑**（我为了复用才加的开关，不许改部署腿语义） | 不传 `SMOKE_ONLY` 且不给 `REL_SHA` ⇒ 仍报「不可判定」（身份段真的跑了）+ `rc=3`；`SMOKE_ONLY=faces` 全绿 ⇒ `rc=0` |
| 7 | **只读 / 无排程**：不写盘、不动 git、不引 cron | 静态守卫 + 自证（把一行写重定向喂给检测器 ⇒ 必命中） |
| 8 | **空跑 = 假绿**：一个面都没判 ⇒ `rc=3` + 出声，绝不当 `0` | `BMINI_GOLIVE_FACES=health,bogus` ⇒ `rc=3` 且 `::error::` 点名未知面 |

## 边界（照实登记，不粉饰）

- **⑤ 客户端错误面恒 `SKIP`**（本仓没有只读出口：`ClientErrorController` 只有 `POST /api/client-errors`，
  落一行日志、无查询端点）⇒ **缺省全跑时 `rc` 常态是 `3`**。这不是故障，是本命令要说的那句
  「有一面判不了」；把它折成 `0` 正是本仓反复踩的「探不到当通过」。
- 判不了「B 端业务对不对」（那是 e2e / 冒烟的射程），也判不了微信后台的域名白名单。
- 版本身份按**前 7 位**比对（与镜像 tag `sha-<7hex>` 同口径，沿用既有探针实现）。
- 包体面取 `measurements` 里**生产域读数**（`cytda=` 命中且 `migaozn=0`）的**最大值**（保守方向）；
  台账里没有这类读数 ⇒ `SKIP`（**不许**拿漂移包 / 测试域产物当发版读数）。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bmini_dist import (  # noqa: E402  （预算常量只许来自台账，判据不抄第二份）
    CAP_BYTES,
    MAIN_LIMIT_BYTES,
    RESERVE_BYTES,
)
WATCH = ROOT / "scripts" / "bmini-golive-watch.sh"
SMOKE = ROOT / "deploy" / "scripts" / "prod-smoke.sh"
BUDGET = ROOT / "deploy" / "scripts" / "bmini-dist-budget.json"

#: 与 `prod-smoke.sh` / `admin-web-version-probe.sh` 的 URL 形态逐字一致（stub 按 URL 索引）
RELEASE_SHA = "26ff9f7160ca573b3bc04c0579bc6c055e58783d"
RELEASE7 = RELEASE_SHA[:7]

HEALTH_URLS = (
    "https://app.cytda.com/b/",
    "https://api.cytda.com/api/version",
    "https://ai-api.cytda.com/version",
    "https://merchant.cytda.com/login",
    "https://cytda.com/",
)
LEAK_URLS = (
    "https://cytda.com/",
    "https://www.cytda.com/sitemap.xml",
    "https://www.cytda.com/robots.txt",
    "https://app.cytda.com/b/js/app.js",
)
#: C 端面（**任何**被探的 URL 都不许是它们）
C_END_URLS = ("https://app.cytda.com/", "https://app.cytda.com/w/", "https://app.migaozn.com/")
MERCHANT_VERSION_URL = "https://merchant.cytda.com/version.json"

ALL_FACES = "health,identity,leak,budget"
FOUR_FACES = "health,identity,leak,budget"

#: 桩 `curl`：只认 `-o` / `-w` / `-m` / `-H` / URL；按表回放状态码与 body（表里没有 ⇒ 网络失败 000/rc7）
STUB_CURL = r'''#!/usr/bin/env python3
import json, os, sys

table = {}
try:
    with open(os.environ["STUB_CURL_TABLE"], encoding="utf-8") as fh:
        table = json.load(fh)
except Exception:
    table = {}

args = sys.argv[1:]
url = args[-1] if args else ""
want = ""
out_path = None
i = 0
while i < len(args):
    a = args[i]
    if a == "-w" and i + 1 < len(args):
        want = args[i + 1]; i += 2; continue
    if a == "-o" and i + 1 < len(args):
        out_path = args[i + 1]; i += 2; continue
    if a in ("-m", "-H", "--max-time", "--connect-timeout") and i + 1 < len(args):
        i += 2; continue
    i += 1

log = os.environ.get("STUB_CURL_LOG")
if log:
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(url + "\n")

entry = table.get(url)
if entry is None:
    body, code, rc, ctype = "", "000", 7, ""
else:
    body = entry.get("body", "")
    code = str(entry.get("code", 200))
    rc = int(entry.get("rc", 0))
    ctype = entry.get("content_type", "application/json")

if out_path and out_path != "/dev/null":
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(body)

if want:
    sys.stdout.write(
        want.replace("\\n", "\n").replace("%{http_code}", code).replace("%{content_type}", ctype)
    )
else:
    sys.stdout.write(body)
sys.exit(rc)
'''


# ── 夹具 ────────────────────────────────────────────────────────────────────
def _green_table() -> dict:
    """全绿的桩表：五个健康面 200、两个身份面 == 发布身份、四个泄漏面 0 命中。"""
    table = {u: {"code": 200, "body": "ok"} for u in HEALTH_URLS + LEAK_URLS}
    table["https://api.cytda.com/api/version"] = {
        "code": 200,
        "body": json.dumps(
            {"app": "admin-api", "sha": RELEASE_SHA, "builtAt": "2026-11-23T02:00:00Z"}
        ),
    }
    table[MERCHANT_VERSION_URL] = {
        "code": 200,
        "body": json.dumps(
            {"app": "admin-web", "sha": RELEASE_SHA, "builtAt": "2026-11-23T02:00:00Z"}
        ),
    }
    return table


def _env_with_stub(tmp_path: Path, table: dict) -> tuple[dict, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "curl"
    stub.write_text(STUB_CURL, encoding="utf-8")
    stub.chmod(0o755)
    table_path = tmp_path / "table.json"
    table_path.write_text(json.dumps(table), encoding="utf-8")
    log = tmp_path / "curl.log"
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["STUB_CURL_TABLE"] = str(table_path)
    env["STUB_CURL_LOG"] = str(log)
    env["BMINI_GOLIVE_RELEASE_SHA"] = RELEASE_SHA
    env["BMINI_GOLIVE_REPO"] = str(ROOT)
    # 委托探针不重试（值守读数要快；重试语义是既有探针自己的事）
    env["SERVED_VERSION_RETRIES"] = "1"
    env["ADMIN_WEB_SERVED_RETRIES"] = "1"
    for key in ("SERVED_VERSION_RETRY_DELAY", "ADMIN_WEB_SERVED_RETRY_DELAY"):
        env[key] = "0"
    return env, log


def _run(
    tmp_path: Path,
    table: dict | None = None,
    *,
    faces: str | None = ALL_FACES,
    budget_file: Path | None = None,
    extra: dict | None = None,
) -> tuple[subprocess.CompletedProcess, Path]:
    env, log = _env_with_stub(tmp_path, _green_table() if table is None else table)
    if faces is not None:
        env["BMINI_GOLIVE_FACES"] = faces
    if budget_file is not None:
        env["BMINI_GOLIVE_BUDGET_FILE"] = str(budget_file)
    if extra:
        env.update(extra)
    proc = subprocess.run(
        ["bash", str(WATCH)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=180
    )
    return proc, log


def _summary(out: str) -> str:
    lines = [ln for ln in out.splitlines() if ln.startswith("BMINI-GOLIVE-SUMMARY")]
    assert len(lines) == 1, f"机读汇总行必须恰好一行，实测 {len(lines)}：\n{out}"
    return lines[0]


def _budget_with(tmp_path: Path, **overrides) -> Path:
    data = json.loads(BUDGET.read_text(encoding="utf-8"))
    data.update(overrides)
    path = tmp_path / "budget.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ── 判据 1/3：五个面各自可判 + 三态退出码 ────────────────────────────────────
def test_full_run_is_honest_about_the_missing_client_error_carrier(tmp_path):
    """缺省全跑：四个面判得动且全绿，⑤ 恒 SKIP ⇒ **rc=3**（`3` 不得当 `0` 读）。"""
    proc, _ = _run(tmp_path, faces=None)
    assert proc.returncode == 3, proc.stdout + proc.stderr
    out = proc.stdout
    for face in ("① 健康", "② 版本身份", "③ 域名泄漏", "④ 小程序包体", "⑤ 客户端错误"):
        assert face in out, f"缺面：{face}\n{out}"
    assert "PASS  https://app.cytda.com/b/" in out
    assert f"线上 sha 前 7 位 == {RELEASE7}" in out
    assert "0 处（4 面通过）" in out
    assert "SKIP  Top-N 读数" in out
    assert "载体缺失" in out and "重启条件" in out, "⑤ 必须写清「载体缺失 + 重启条件」"
    summary = _summary(out)
    assert "rc=3" in summary and "fail=0" in summary and "skip=1" in summary, summary
    assert f"release={RELEASE7}" in summary, summary
    assert "client-errors:SKIP" in summary, summary


def test_subset_four_faces_all_green_exits_zero(tmp_path):
    """四个判得动的面全绿 ⇒ rc=0（三态里的 `0` 只能由「每一面都判过且都通过」得到）。"""
    proc, _ = _run(tmp_path, faces=FOUR_FACES)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    summary = _summary(proc.stdout)
    assert "rc=0" in summary and "skip=0" in summary and "fail=0" in summary, summary


# ── 判据 1：每个面的 FAIL 都能被触发（注入式：把期望值改坏）───────────────────
def test_health_non_200_is_fail_and_exits_one(tmp_path):
    """健康面拿到 500 的**响应** ⇒ FAIL（拿到响应就不是「探不到」）。"""
    table = _green_table()
    table["https://cytda.com/"] = {"code": 500, "body": "boom"}
    proc, _ = _run(tmp_path, table, faces="health")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "FAIL  https://cytda.com/" in proc.stdout
    assert "HTTP 500（期望 200）" in proc.stdout
    assert "health:FAIL" in _summary(proc.stdout)


def test_network_failure_is_skip_not_pass(tmp_path):
    """桩表里没有该 URL ⇒ 连接失败（000）⇒ SKIP，**不许**是 PASS，也不许是 FAIL。"""
    table = _green_table()
    table.pop("https://app.cytda.com/b/")
    proc, _ = _run(tmp_path, table, faces="health")
    assert proc.returncode == 3, proc.stdout + proc.stderr
    out = proc.stdout
    assert "SKIP  https://app.cytda.com/b/" in out, out
    assert "PASS  https://app.cytda.com/b/" not in out, out
    assert "FAIL  https://app.cytda.com/b/" not in out, out
    assert "health:SKIP" in _summary(out)


def test_identity_mismatch_is_fail(tmp_path):
    """线上 sha ≠ 发布身份 ⇒ FAIL，且具名到「落后发布线」（不是笼统的「版本不对」）。"""
    table = _green_table()
    table["https://api.cytda.com/api/version"] = {
        "code": 200,
        "body": json.dumps(
            {"app": "admin-api", "sha": "deadbeef" * 5, "builtAt": "2026-11-21T05:11:25Z"}
        ),
    }
    proc, _ = _run(tmp_path, table, faces="identity")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    out = proc.stdout
    assert "FAIL  api（served-version-verify.sh）" in out
    assert "线上 sha deadbee ≠ origin/release" in out, out
    assert "线上落后发布线" in out, out
    assert "identity:FAIL" in _summary(out)


def test_identity_unreachable_is_skip(tmp_path):
    """两个身份面都探不到（表里没有）⇒ 两条 SKIP + rc=3（探不到 ≠ 不一致）。"""
    table = _green_table()
    table.pop("https://api.cytda.com/api/version")
    table.pop(MERCHANT_VERSION_URL)
    proc, _ = _run(tmp_path, table, faces="identity")
    assert proc.returncode == 3, proc.stdout + proc.stderr
    out = proc.stdout
    assert out.count("SKIP") >= 2, out
    assert "API 探不到" not in out  # 只是防止有人把文案写成「探到了」
    statuses = [ln.strip() for ln in out.splitlines()
                if ln.strip().startswith(("PASS", "FAIL", "SKIP"))]
    assert statuses and not [s for s in statuses if s.startswith("FAIL")], out
    assert "identity:SKIP" in _summary(out)


def test_leak_hit_is_fail(tmp_path):
    """泄漏面命中 `migaozn.com` ⇒ FAIL（判据本体仍是 `prod-smoke.sh` 的泄漏段）。"""
    table = _green_table()
    table["https://cytda.com/"] = {"code": 200, "body": "<script src='https://app.migaozn.com/x.js'></script>"}
    proc, log = _run(tmp_path, table, faces="leak")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    out = proc.stdout
    assert "FAIL  migaozn 命中（B 端相关面）" in out, out
    assert "❌ 1 处 migaozn" in out, out
    assert "leak:FAIL" in _summary(out)
    # 只跑泄漏段时，身份/健康面一次都不该被请求（复用 ≠ 顺带跑别的段）
    probed = set(log.read_text(encoding="utf-8").split())
    assert probed == set(LEAK_URLS), probed


def test_budget_over_budget_is_fail(tmp_path):
    """台账读数超过主包预算 ⇒ FAIL 且说出超多少字节。"""
    budget = _budget_with(
        tmp_path,
        measurements=[{"path": "~/x/dist", "bytes": 9000000, "domains": "cytda=1 migaozn=0"}],
    )
    proc, _ = _run(tmp_path, faces="budget", budget_file=budget)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    out = proc.stdout
    assert "FAIL  最近实测 dist vs 主包预算" in out, out
    assert f"9,000,000 > {MAIN_LIMIT_BYTES:,}" in out, out
    assert "budget:FAIL" in _summary(out)


def test_budget_without_production_measurement_is_skip(tmp_path):
    """台账里只有漂移包 / 测试域读数 ⇒ SKIP（拿漂移包当发版读数是假绿）。"""
    budget = _budget_with(
        tmp_path,
        measurements=[
            {"path": "~/drift", "bytes": 1465247, "domains": "migaozn=1 localhost=1"},
            {"path": "~/test-build", "bytes": 1465251, "domains": "migaozn=3 cytda=0"},
        ],
    )
    proc, _ = _run(tmp_path, faces="budget", budget_file=budget)
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "SKIP  包体预算" in proc.stdout, proc.stdout
    assert "生产域" in proc.stdout
    assert "PASS  最近实测 dist" not in proc.stdout


# ── 判据 8：空跑 = 假绿 ─────────────────────────────────────────────────────
def test_unknown_face_is_red_not_green(tmp_path):
    proc, _ = _run(tmp_path, faces="health,bogus")
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "bogus" in proc.stdout + proc.stderr
    assert "rc=3" in _summary(proc.stdout)


def test_empty_face_env_falls_back_to_all_faces(tmp_path):
    """显式给空串不许变成「一个面都不跑还绿」（knob 的 fail-closed 面）。"""
    proc, _ = _run(tmp_path, faces="")
    assert proc.returncode == 3, proc.stdout + proc.stderr
    out = proc.stdout
    assert "pass=9" in _summary(out), out  # 缺省五面全跑：5 健康 + 2 身份 + 1 泄漏 + 1 包体 = 9 个 PASS
    assert "⑤ 客户端错误" in out


# ── 判据 4：无 C 端面（静态 + 行为两侧都钉）─────────────────────────────────
_URL_RE = re.compile(r"https?://[^\s'\"`{})]+")


def test_script_contains_no_c_end_url():
    text = WATCH.read_text(encoding="utf-8")
    urls = _URL_RE.findall(text)
    assert urls, "脚本里连一个 URL 都没有 —— 检测器是空断言"
    for url in urls:
        assert url not in C_END_URLS, f"脚本里出现 C 端面：{url}"
        assert "migaozn.com" not in url, f"脚本里出现测试域：{url}"
        if url.startswith("https://app.cytda.com"):
            assert url.startswith("https://app.cytda.com/b/") or url == "https://app.cytda.com", \
                f"`app.<域>` 只许是 `/b/` 面：{url}"
        assert "/w/" not in url, f"不得探工人端：{url}"
    assert "frontend/mini-app" not in text, "不得碰 C 端产物目录"
    # 自证：换成一个 C 端 URL，检测器必须命中
    assert {u for u in _URL_RE.findall("curl https://app.cytda.com/w/")} & set(C_END_URLS)


def test_behaviour_probes_only_b_end_faces(tmp_path):
    """行为侧：`faces=health` 只请求那五个 B 端面；`faces=leak` 只请求泄漏段那四个面。"""
    proc, log = _run(tmp_path, faces="health")
    probed = set(log.read_text(encoding="utf-8").split())
    assert probed == set(HEALTH_URLS), probed
    assert not (probed & set(C_END_URLS)), probed

    proc2, log2 = _run(tmp_path / "leak", faces="leak")
    probed2 = set(log2.read_text(encoding="utf-8").split())
    assert probed2 == set(LEAK_URLS), probed2
    assert not (probed2 & set(C_END_URLS)), probed2


# ── 判据 5：复用既有判据本体；不许有第二把尺子 ─────────────────────────────
def test_reuses_existing_carriers_and_has_no_second_cap_constant():
    text = WATCH.read_text(encoding="utf-8")
    for carrier in (
        "deploy/scripts/served-version-verify.sh",
        "deploy/scripts/admin-web-version-probe.sh",
        "deploy/scripts/prod-smoke.sh",
        "deploy/scripts/bmini-dist-budget.json",
    ):
        assert carrier in text, f"没有复用既有载体：{carrier}"
    for cap in (CAP_BYTES, MAIN_LIMIT_BYTES, RESERVE_BYTES):
        assert str(cap) not in text, f"脚本里出现第二份上限常量 {cap}（预算必须只来自台账）"
    assert "SMOKE_ONLY=leak" in text, "域名泄漏段必须用 `SMOKE_ONLY=leak` 复用，而不是自己再写一份"


# ── 判据 7：只读 / 无排程（静态禁令 + 实跑前后比对工作树）──────────────────
#: 只读命令的静态禁令：写盘工具 / 定时排程 / 变更 git / 触发部署。命中任一 ⇒ 红。
_BANNED_READONLY = (
    "mktemp", "tee ", "crontab", "cron", "schedule", "git fetch", "git push", "git checkout",
    "git stash", "git add", "cut-release", "workflow run", "gh ", "rm -",
)


def _banned_hits(text: str) -> list[str]:
    return [b for b in _BANNED_READONLY if b in text]


def test_script_is_read_only_and_unscheduled(tmp_path):
    text = WATCH.read_text(encoding="utf-8")
    assert not _banned_hits(text), f"只读命令里出现禁令项：{_banned_hits(text)}"
    # 自证检测器不是空断言
    assert _banned_hits("crontab -l") and _banned_hits("git push origin main")

    # 行为面：真跑一次（健康 + 包体；都在桩上 / 只读台账）⇒ 工作树一个字节都不许变
    before = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True,
                            text=True, timeout=60).stdout
    proc, _ = _run(tmp_path, faces="health,budget")
    after = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True,
                           text=True, timeout=60).stdout
    assert proc.returncode in (0, 3), proc.stdout + proc.stderr
    assert before == after, f"只读命令改动了工作树：\n--- before ---\n{before}\n--- after ---\n{after}"


# ── 判据 6：`SMOKE_ONLY` 缺省仍是三段全跑（改既有载体的回归面）──────────────
def test_prod_smoke_section_filter_keeps_default_semantics(tmp_path):
    # `prod-smoke.sh` 自己那八面（含 C 端根与 `/w/` —— 那是**部署腿**的面清单，与本命令无关）
    smoke_faces = (
        "https://cytda.com/",
        "https://www.cytda.com/",
        "https://merchant.cytda.com/login",
        "https://api.cytda.com/api/version",
        "https://ai-api.cytda.com/version",
        "https://app.cytda.com/",
        "https://app.cytda.com/b/",
        "https://app.cytda.com/w/",
    )
    table = _green_table()
    for url in smoke_faces:
        table.setdefault(url, {"code": 200, "body": "ok"})
    env, _ = _env_with_stub(tmp_path, table)
    env.pop("BMINI_GOLIVE_FACES", None)
    env.pop("REL_SHA", None)
    # ① 缺省（不传 SMOKE_ONLY）：三段全跑 ⇒ 没有 REL_SHA 时身份段仍报「不可判定」⇒ rc=3
    default_run = subprocess.run(
        ["bash", str(SMOKE)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120
    )
    assert default_run.returncode == 3, default_run.stdout + default_run.stderr
    assert "版本身份" in default_run.stdout and "不可判定" in default_run.stdout
    assert "域名泄漏" in default_run.stdout
    # ② 显式 SMOKE_ONLY=faces：只跑健康段 ⇒ 八面全绿 rc=0
    only_faces = dict(env, SMOKE_ONLY="faces")
    faces_run = subprocess.run(
        ["bash", str(SMOKE)], cwd=ROOT, env=only_faces, capture_output=True, text=True, timeout=120
    )
    assert faces_run.returncode == 0, faces_run.stdout + faces_run.stderr
    assert "版本身份" not in faces_run.stdout
