# case_ids: MC-146
"""冒烟 / 种子夹具的**库存链路**判据（issue #7600；SDQS §33「绿证明的是页面，不是数据」）。

## 病灶（issue #7600 的 durable 证据）

冒烟与种子夹具**绕过业务链路直写库存**：

| 直写点 | 现取形态 | 分档 |
|---|---|---|
| `scripts/ui-smoke-merchant/spec.mjs` 的 `createProductFixture` | 建品 payload 里 `skus[].stock = 120`（#7597 后建品接口**忽略**该字段 ⇒ 库里是 0） | **A**（能走公开 API ⇒ 已改成入库单过账） |
| `docs/deployment/demo-seed.sql` | 14 条 `INSERT INTO product_skus (…, stock, …)` | **B**（psql 夹具，无 HTTP 写面） |
| `tests/agent_eval/fixtures/xiaobu_eval_seed.sql` / `mibao_eval_seed.sql` | 2 + 1 条同形 INSERT | **B**（同上，一次性评测栈） |
| `backend/admin-api/src/main/java/**` 的 `product_skus` | mapper SQL / 迁移 | **C**（产品代码，不在扫描面） |

⇒ 页面绿了，但「库存从哪来、扣减对不对」这条链路根本没被走到（#7597 之后更糟：夹具以为有 120，
库里是 0，而旅程判据只看「商品列表有行」）。

## 判据（每条都能单独变红，具名 `文件:行`）

| # | 判据 | 回归时会怎么红 |
|---|---|---|
| ① | 夹具面上的 `product_skus.stock` 直写**必须已登记**（台账 `smoke_fixture_direct_write_ledger.json` 的 scope 内） | 往 spec.mjs / 任一 seed 里新加一条直写而不登记 ⇒ 红并具名 `文件:行` |
| ② | 台账条目必须**仍然成立**（marker 在、站点数**两个方向**都对得上） | 删掉某条已登记直写点却不改台账 ⇒ 红；台账写了不存在的点 ⇒ 红（台账只许缩短） |
| ③ | **负控**：产品代码里的 `product_skus` **不被扫**（同一正则对夹具面会命中，证明射程准） | 判据把产品代码也扫进去（误报面扩大）或扫描器失效 ⇒ 红 |
| ④ | **红证**：内存里删掉一条已登记直写点 ⇒ ② 必红；恢复 ⇒ 不红 | 这条自己不红 = 空判据 |
| ⑤ | **A 类不许退回 B 类**：`createProductFixture` 不带 SKU 库存字段、必须调 `seedSkuStockViaInbound`（入库单建单即过账），建品旅程断言 0 → 120 | 有人把 `stock: 120` 写回、或摘掉入库调用 ⇒ 红 |

**零网络 / 零 DB / 零时钟**：只读仓内文本（spec 与 seed 是真语料），纯函数可复算。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
LEDGER_PATH = Path(__file__).resolve().parent / "smoke_fixture_direct_write_ledger.json"
SPEC = REPO / "scripts" / "ui-smoke-merchant" / "spec.mjs"
PRODUCT_CODE_ROOT = REPO / "backend" / "admin-api" / "src" / "main" / "java"

SQL_STOCK_INSERT_RE = re.compile(r"INSERT\s+INTO\s+product_skus\s*\(([^)]*)\)", re.I)
JS_STOCK_RE = re.compile(r"^\s*stock\s*:\s*\S")
MARKER_RE = re.compile(r"SDQS-WAIVER:\s*(DFW-[A-Z0-9-]+)")


# ── 纯函数扫描器（射程 = 台账声明的夹具面；产品代码不在面内）──────────────────

def _in_scope(rel: str, surfaces: list[str]) -> bool:
    return any(rel.startswith(s) if s.endswith("/") else rel == s for s in surfaces)


def direct_writes(sources: dict[str, str], surfaces: list[str] | None = None) -> list[dict[str, Any]]:
    """夹具面上的库存直写点（1-based 行号）。"""
    surfaces = surfaces or []
    hits: list[dict[str, Any]] = []
    for rel, text in sources.items():
        if surfaces and not _in_scope(rel, surfaces):
            continue
        if rel.endswith(".sql"):
            for lineno, line in enumerate(text.splitlines(), 1):
                code = line.split("--", 1)[0]
                m = SQL_STOCK_INSERT_RE.search(code)
                if not m:
                    continue
                cols = {c.strip().lower() for c in m.group(1).split(",")}
                if "stock" in cols:
                    hits.append({"file": rel, "line": lineno, "kind": "sql"})
        elif rel.endswith((".mjs", ".js")):
            for lineno, line in enumerate(text.splitlines(), 1):
                if JS_STOCK_RE.match(line):
                    hits.append({"file": rel, "line": lineno, "kind": "js"})
    return hits


def _find_line(lines: list[str], anchor: str, start: int = 0) -> int:
    for idx in range(start, len(lines)):
        if anchor in lines[idx]:
            return idx
    return -1


def audit(sources: dict[str, str], ledger: dict[str, Any]) -> list[str]:
    """台账 ⇄ 现场 双向对账。返回问题清单（空 = 绿）。

    ① 未登记即红 / ② 台账陈旧（marker 不在、站点数两个方向不符）/ scope 锚缺失。
    """
    problems: list[str] = []
    waivers = ledger.get("waivers") or []
    if not waivers:
        problems.append("台账 `waivers` 为空（fail-closed：空台账不许当绿）")
        return problems

    hits = direct_writes(sources, ledger.get("scan_surfaces") or [])
    scopes: dict[str, tuple[str, int, int]] = {}

    for w in waivers:
        wid, rel = w.get("id", "<无 id>"), w.get("file", "")
        text = sources.get(rel)
        if text is None:
            problems.append(f"台账条目 {wid} 的文件读不到：{rel}")
            continue
        marker = w.get("marker", "")
        if not marker or marker not in text:
            problems.append(f"台账陈旧（marker 不在现场）：{wid} ⇒ {rel} 里找不到 {marker!r}")
            continue
        lines = text.splitlines()
        lo = _find_line(lines, w.get("scope_start", marker))
        hi = _find_line(lines, w.get("scope_end", ""), lo + 1) if w.get("scope_end") else len(lines)
        if lo < 0 or hi <= lo:
            problems.append(f"台账陈旧（scope 锚解析不到）：{wid} ⇒ {rel} 的 start={w.get('scope_start')!r} / end={w.get('scope_end')!r}")
            continue
        scopes[wid] = (rel, lo, hi)

    owned = {wid: 0 for wid in scopes}
    for h in hits:
        owners = [wid for wid, (rel, lo, hi) in scopes.items()
                  if rel == h["file"] and lo < (h["line"] - 1) < hi]
        if not owners:
            problems.append(
                f"未登记的库存直写点：{h['file']}:{h['line']}（kind={h['kind']}）"
                f" —— 要么改走公开 API（A 类），要么在本文件同批登记（B 类）")
        elif len(owners) > 1:
            problems.append(f"直写点 {h['file']}:{h['line']} 同时落在多个登记 scope 里：{sorted(owners)}")
        else:
            owned[owners[0]] += 1

    for w in waivers:
        wid = w.get("id", "<无 id>")
        if wid not in scopes:
            continue
        expect = int(w.get("expect_sites", 0))
        got = owned[wid]
        if got != expect:
            problems.append(
                f"台账与现场不符：{wid}（{scopes[wid][0]}）登记 {expect} 条直写点，现场 {got} 条"
                f" —— 变多 = 有新直写未登记；变少 = 台账陈旧（删点必须同批改台账）")

    declared = ledger.get("baseline_sites")
    if isinstance(declared, int) and declared != len(hits):
        problems.append(f"台账 baseline_sites={declared} 与现场直写点总数 {len(hits)} 不符（只许缩短）")
    exactly = sum(int(w.get("expect_sites", 0)) for w in waivers)
    if exactly != len(hits):
        problems.append(f"各条目 expect_sites 之和 {exactly} ≠ 现场 {len(hits)}")
    return problems


# ── A 类判据（⑤）：冒烟的库存必须来自公开 API ────────────────────────────────

def check_smoke_spec(text: str) -> list[str]:
    """`createProductFixture` 不许带 SKU 库存字段，必须走入库单过账。"""
    problems: list[str] = []
    m = re.search(r"async function createProductFixture\([\s\S]*?\n\}", text)
    if not m:
        return ["spec.mjs 里找不到 createProductFixture（判据失去被测对象，fail-closed）"]
    body = m.group(0)
    for line in body.splitlines():
        if JS_STOCK_RE.match(line):
            problems.append(f"createProductFixture 又直接写 SKU 库存：{line.strip()!r}（库存只由单据产生）")
    if "seedSkuStockViaInbound(page" not in body:
        problems.append("createProductFixture 未走公开 API 造库存（缺 seedSkuStockViaInbound 调用）")
    if "async function seedSkuStockViaInbound" not in text:
        problems.append("缺 seedSkuStockViaInbound 定义（入库单建单即过账的唯一入口）")
    if "/api/admin/inbound-orders" not in text:
        problems.append("spec.mjs 未调用入库单接口（库存必须来自真实单据，不允许夹具直写）")
    for anchor in ("库存应全为 0", "过账后 SKU 库存应全为 120"):
        if anchor not in text:
            problems.append(f"建品旅程缺库存链路判据锚点：{anchor!r}（0 → 入库 → 120）")
    return problems


# ── 真实语料读取 ────────────────────────────────────────────────────────────

def _ledger() -> dict[str, Any]:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def _sources() -> dict[str, str]:
    spans: list[str] = []
    for surface in _ledger().get("scan_surfaces") or []:
        p = REPO / surface
        if p.is_dir():
            spans.extend(str(f.relative_to(REPO)) for f in sorted(p.rglob("*")) if f.is_file())
        elif p.is_file():
            spans.append(surface)
    return {rel: (REPO / rel).read_text(encoding="utf-8", errors="replace") for rel in spans}


# ── 判据 ① + ②：真语料上零未登记、登记点全部仍成立 ──────────────────────────

def test_no_unregistered_direct_write_on_the_real_corpus():
    problems = audit(_sources(), _ledger())
    assert problems == [], "夹具面存在未登记 / 台账陈旧的库存直写点：\n" + "\n".join(problems)


def test_scan_is_not_dead():
    hits = direct_writes(_sources(), _ledger().get("scan_surfaces") or [])
    ledger = _ledger()
    assert len(hits) > 0, "扫描面一条直写点都没扫到 ⇒ 扫描器已死（空结果 ≠ 通过）"
    assert len(hits) == ledger["baseline_sites"], (
        f"现场直写点 {len(hits)} 条，台账 baseline_sites={ledger['baseline_sites']}（只许缩短）")
    assert len(hits) == sum(w["expect_sites"] for w in ledger["waivers"])


def test_registered_sites_are_all_still_there():
    """② 台账陈旧即红：每条登记点的 marker 与站点数都必须与现场一致。"""
    sources, ledger = _sources(), _ledger()
    for waiver in ledger["waivers"]:
        rel = waiver["file"]
        assert waiver["marker"] in sources[rel], f"{waiver['id']} 的登记标记在 {rel} 里消失了（台账陈旧）"
        _, lo, hi = _scopes_for(sources, waiver)
        got = len([h for h in direct_writes({rel: sources[rel]}, [rel]) if lo < (h["line"] - 1) < hi])
        assert got == waiver["expect_sites"], (
            f"{waiver['id']}（{rel}）登记 {waiver['expect_sites']} 条，现场 {got} 条")


def _scopes_for(sources: dict[str, str], waiver: dict[str, Any]) -> tuple[str, int, int]:
    lines = sources[waiver["file"]].splitlines()
    lo = _find_line(lines, waiver["scope_start"])
    hi = _find_line(lines, waiver["scope_end"], lo + 1)
    assert lo >= 0 and hi > lo, f"{waiver['id']} 的 scope 锚解析不到（{waiver['scope_start']!r}）"
    return waiver["file"], lo, hi


# ── 判据 ③：负控 —— 产品代码的产品 `product_skus` 不被扫 ─────────────────────

def test_product_code_is_out_of_scan_scope():
    mapper = PRODUCT_CODE_ROOT / "com" / "migao" / "admin" / "mapper" / "ProductSkuMapper.java"
    text = mapper.read_text(encoding="utf-8")
    assert "product_skus" in text, "负控失效：产品代码里本来应有 product_skus（否则这条负控是空断言）"
    rel = str(mapper.relative_to(REPO))
    surfaces = _ledger()["scan_surfaces"]
    assert not _in_scope(rel, surfaces), f"产品代码 {rel} 落进了夹具扫描面（射程被误扩大）"
    assert direct_writes({rel: text}, surfaces) == []
    # 同一正则对夹具面确实会命中（证明上面的空结果不是正则失灵）
    probe = {"scripts/ui-smoke-merchant/spec.mjs": "  const skus = [\n    stock: 120,\n  ]\n"}
    assert direct_writes(probe, surfaces) != []


# ── 判据 ④：红证（注入式、内存内，可复算）────────────────────────────────────

def test_red_proof_removing_a_registered_site_turns_red():
    """删掉一条已登记的直写点、台账不改 ⇒ ② 必红；恢复 ⇒ 不红（双向对照）。"""
    sources, ledger = _sources(), _ledger()
    rel = "docs/deployment/demo-seed.sql"
    lines = sources[rel].splitlines()
    idx = next(i for i, line in enumerate(lines)
               if SQL_STOCK_INSERT_RE.search(line) and "stock" in line)
    mutated = dict(sources)
    mutated[rel] = "\n".join(lines[:idx] + lines[idx + 1:])
    assert mutated[rel] != sources[rel], "变异注入未生效（删掉的行不存在？）"
    problems = audit(mutated, ledger)
    assert problems, "删掉已登记直写点却不改台账 ⇒ 必须红（否则 ② 是空判据）"
    assert any("DFW-DEMO-SEED-001" in p for p in problems), f"红未归因到具体登记点：{problems}"
    assert audit(sources, ledger) == [], "恢复后必须回到绿（否则判据恒红）"


def test_red_proof_new_unregistered_write_turns_red():
    """往冒烟 spec 里加一条 SKU 库存直写 ⇒ ① 必红并具名 spec.mjs。"""
    sources, ledger = _sources(), _ledger()
    rel = "scripts/ui-smoke-merchant/spec.mjs"
    mutated = dict(sources)
    mutated[rel] = sources[rel] + "\n    stock: 120,\n"
    problems = audit(mutated, ledger)
    assert problems, "新增未登记的库存直写 ⇒ 必须红"
    assert any(p.startswith(f"未登记的库存直写点：{rel}:") for p in problems), (
        f"红未具名到 {rel}:行：{problems}")


# ── 判据 ⑤：A 类不许退回 B 类 ────────────────────────────────────────────────

def test_smoke_fixture_stock_comes_from_the_inbound_api():
    assert check_smoke_spec(SPEC.read_text(encoding="utf-8")) == []


def test_smoke_spec_judge_has_discriminating_power():
    text = SPEC.read_text(encoding="utf-8")
    # 坏形态 A：把 `stock: 120` 写回 SKU payload
    back_to_direct = text.replace("    price: basePrice,\n    skuCode:",
                                  "    price: basePrice,\n    stock: 120,\n    skuCode:", 1)
    assert back_to_direct != text, "变异注入未生效（锚点已漂移）"
    assert any("直接写 SKU 库存" in p for p in check_smoke_spec(back_to_direct))
    # 坏形态 B：摘掉入库单调用（回到「建品即认为有库存」）
    no_inbound = text.replace("seedSkuStockViaInbound(page, { productId: id, skus: skuRows, meters: 120 })",
                              "Promise.resolve({ id: '<kept>' })", 1)
    assert no_inbound != text, "变异注入未生效（锚点已漂移）"
    assert any("未走公开 API" in p for p in check_smoke_spec(no_inbound))
    # 对照：只改注释 ⇒ 不红
    comment_only = text.replace("库存只由真实单据产生", "库存由真实单据产生（注释措辞）", 1)
    assert comment_only != text
    assert check_smoke_spec(comment_only) == []
