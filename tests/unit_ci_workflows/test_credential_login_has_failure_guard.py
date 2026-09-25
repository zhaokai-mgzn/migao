# case_ids: AU-011
"""凭据类登录入口必须有失败计数 —— 类级元守卫（issue #5531）。

## 为什么需要这条（类级固化）

issue #5531 的实测读数：员工「用户名@企业编码 + 密码」登录**连续 6 次错密码恒 401**，
无失败计数、无锁定、无限频 —— 而**同一认证链**的短信侧有 `SmsService.MAX_VERIFY_FAILS = 5`。
**只给员工登录补一个计数器 = 没修**：下一次有人新增一个凭据校验入口（或把已禁用的入口重新启用），
同样会**静默地**没有防护，而没有任何东西会因此变红。

## 判据

全仓 Java 源码里每个 `passwordEncoder.matches(...)` 出现的**方法**，必须满足其一：
① **受守卫**：方法体内引用了 `LoginFailureGuard`（`loginFailureGuard` / `LoginFailureGuard`）；
② **已登记**：在 `tests/unit_ci_workflows/credential_login_guard_ledger.json` 的 `entries` 里
   （必须写明理由：为什么它不是"可被猜解的未认证入口"）。
**未登记即红；台账只许缩短**（销账 = 该方法已受守卫或已删除 ⇒ 必须删条目）。

## 边界（如实登记）

- 本守卫是**文本层**判据：它只认「方法体内出现守卫引用」这一形态。把守卫调用藏进另一个
  辅助方法里（本类内部转发）会绕过它 —— 无机械锁，靠评审（同族：`test_tenant_scoped_user_queries.py` 的边界）。
- 它**不**检查阈值/窗口/文案是否与短信侧一致（那由 `EmployeeLoginLockoutTest` / `WorkerLoginLockoutTest` 钉）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
JAVA_ROOT = REPO / "backend/admin-api/src/main/java"
LEDGER = Path(__file__).resolve().parent / "credential_login_guard_ledger.json"

CREDENTIAL_CALL = "passwordEncoder.matches("
GUARD_TOKENS = ("loginFailureGuard", "LoginFailureGuard")
# ⚠️ 修饰符**可选**：红证夹具（以及任何漏写修饰符的方法）同样要被扫到 ——
#    实测踩过：写死修饰符时，无修饰符的注入语料被静默漏掉 ⇒ 那条红证成了空断言。
METHOD_SIG = re.compile(r"(?:public|private|protected)\s+[\w<>\[\],\.\s]+\s+(\w+)\s*\(")
METHOD_SIG_LOOSE = re.compile(r"(?:^|\n)\s*(?:public|private|protected)?\s*[\w<>\[\],\.\s]+?\s+(\w+)\s*\(")


def scan_sites(root: Path = JAVA_ROOT) -> list[dict]:
    """→ [{'site': '<相对路径>::<方法名>', 'guarded': bool}]（同方法多次出现只记一条）。"""
    found: dict[str, bool] = {}
    for path in sorted(Path(root).rglob("*.java")):
        src = path.read_text(encoding="utf-8")
        if CREDENTIAL_CALL not in src:
            continue
        rel = path.relative_to(REPO) if str(path).startswith(str(REPO)) else path.name
        for m in re.finditer(re.escape(CREDENTIAL_CALL), src):
            head = src[: m.start()]
            sigs = list(METHOD_SIG.finditer(head))
            if not sigs:
                # 宽松兜底：无访问修饰符的方法（红证夹具形态）也必须被扫到
                loose = list(METHOD_SIG_LOOSE.finditer(head))
                if not loose:
                    continue
                sigs = loose
            method = sigs[-1].group(1)
            body_start = sigs[-1].start()
            nxt = re.search(r"\n    (?:public|private|protected)\s", src[m.start():])
            body_end = m.start() + (nxt.start() if nxt else 2000)
            body = src[body_start:body_end]
            site = f"{rel}::{method}"
            guarded = any(tok in body for tok in GUARD_TOKENS)
            # 同一方法内多处：只要有一处受守卫就算受守卫（保守：宁可少报）
            found[site] = found.get(site, False) or guarded
    return [{"site": s, "guarded": g} for s, g in sorted(found.items())]


def _ledger() -> dict:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def unregistered_unguarded(sites: list[dict], ledger: dict) -> list[str]:
    registered = {e["site"] for e in ledger["entries"]}
    return [s["site"] for s in sites if not s["guarded"] and s["site"] not in registered]


def stale_ledger_entries(sites: list[dict], ledger: dict) -> list[str]:
    """台账条目的现场必须仍是「未受守卫」⇒ 否则是"销账未删条目"。现场消失（方法被删）也视为陈旧。"""
    by_site = {s["site"]: s for s in sites}
    stale = []
    for e in ledger["entries"]:
        s = by_site.get(e["site"])
        if s is None or s["guarded"]:
            stale.append(e["site"])
    return stale


# ── 判据 ────────────────────────────────────────────────────────────────────


def test_scanner_covers_known_sites_and_is_not_empty():
    """防判据空跑：语料必须非空，且必须含两处**已知受守卫**的凭据入口。"""
    sites = scan_sites()
    assert sites, "扫描面为空 ⇒ 判据静默空跑（检查 Java 根路径）"
    guarded = {s["site"] for s in sites if s["guarded"]}
    assert "backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java::loginByEmployee" in guarded, (
        "员工登录入口必须被识别为受守卫（否则扫描口径坏了）"
    )
    assert "backend/admin-api/src/main/java/com/migao/admin/worker/WorkerSessionService.java::login" in guarded, (
        "工人 PIN 登录入口必须被识别为受守卫"
    )


def test_every_credential_site_is_guarded_or_registered():
    sites = scan_sites()
    bad = unregistered_unguarded(sites, _ledger())
    assert bad == [], (
        "以下凭据校验方法既没有失败计数、也没有登记豁免 ⇒ 未登记即红。\n"
        "出口：① 接上 LoginFailureGuard（推荐）；② 若它确实不是未认证的可猜解入口，"
        "在 tests/unit_ci_workflows/credential_login_guard_ledger.json 登记并写明理由。\n"
        f"未登记项：{bad}"
    )


def test_ledger_has_no_stale_entries():
    stale = stale_ledger_entries(scan_sites(), _ledger())
    assert stale == [], (
        "台账条目对应的现场已受守卫（或方法已不存在）⇒ **销账未删条目**，请同步删除：\n" + "\n".join(stale)
    )


def test_ledger_total_only_shrinks():
    ledger = _ledger()
    now = len(ledger["entries"])
    assert now <= ledger["baseline_total"], (
        f"台账条数 {now} > 基线 {ledger['baseline_total']} ⇒ 新增豁免（只许缩短）。"
        "新增豁免必须先证明该入口不是可被猜解的未认证入口，并同步抬高 baseline_total —— 那需要评审裁定。"
    )
    assert now == len({e["site"] for e in ledger["entries"]}), "台账里有重复 site"


def test_red_proof_injected_unguarded_site_is_detected(tmp_path: Path):
    """注入式红证：写一个**未受守卫**的凭据校验方法 ⇒ 判据必红（证明它真会响）。"""
    injected = tmp_path / "Injected.java"
    injected.write_text(
        "package com.migao.admin.service;\n"
        "class Injected {\n"
        "    boolean verify(String raw, String hash) {\n"
        "        return passwordEncoder.matches(raw, hash);\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    sites = scan_sites(tmp_path)
    assert sites, "注入的语料没被扫到 ⇒ 红证无效（先修扫描口径）"
    assert unregistered_unguarded(sites, {"entries": []}) == [f"{injected.name}::verify"], (
        "注入的未受守卫入口必须被判红 —— 否则这条守卫是空断言"
    )


def test_red_proof_guarded_site_is_not_flagged(tmp_path: Path):
    """负控：同样形态但引用了守卫 ⇒ 不得误报（否则守卫会把合规写法判红）。"""
    ok = tmp_path / "Guarded.java"
    ok.write_text(
        "package com.migao.admin.service;\n"
        "class Guarded {\n"
        "    boolean verify(String raw, String hash, String key) {\n"
        "        if (loginFailureGuard.isLocked(key)) { return false; }\n"
        "        return passwordEncoder.matches(raw, hash);\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    assert unregistered_unguarded(scan_sites(tmp_path), {"entries": []}) == []
