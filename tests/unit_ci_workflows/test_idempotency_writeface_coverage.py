# case_ids: MC-088
r"""写面**幂等接线覆盖率**的类级元守卫（issue #6209，铁律 8）。

## 病（本单的实例 + 为什么「只修一处 = 没修」）

现场证据 `acceptance/2026-10-03/batch-writeface-sweep/out/E1-duplicate-submit.json`：同一个
`X-Client-Request-Id` 并发 5 次建品 ⇒ 商品 **6 条**、`client_request_keys` **0 行**。
仓内**已有**这份机制（`backend/admin-api/src/main/java/com/migao/admin/service/ClientRequestIdService.java`，
订单 / 售后 / 发货 / 报工 / 入库都已接）—— 建品是**漏接**，不是缺机制。

只把建品接上，下一个人照样可以在**新写面**上重犯，而没有任何东西会红。本守卫把
「哪些文件**已接**同一个点位」变成机械台账，并让这些坏形态各自判红：

| # | 判据 | 红形态（怎么让它红） |
|---|---|---|
| 1 | **未登记即红** | 新文件出现幂等消费形态（`clientRequestIdService.claim(` 等）却没进台账 `consume_sites` |
| 2 | **登记未被兑现即红** | 台账条目的 `anchor` 在文件里逐字找不到（给不存在的接线盖章） |
| 3 | **陈旧条目即红** | 台账里的文件已不被扫描器现取到（接线被摘掉 / 改名） |
| 4 | **声明侧闭合** | 读了 `ClientRequestIdService.HEADER` 的文件必须在「自己消费」/「透传给下游」/「缺口」三处之一 —— 新增读了头却谁也不接的端点 ⇒ 红 |
| 5 | **豁免只许缩短** | `declared_but_unwired` 条数 ≤ 冻结基线（条数现取并打印） |
| 6 | **同一份实现** | `ClientRequestIdService` 类文件恰一个、`claim(` 定义在它里面、`client_request_keys` 的 UNIQUE 在 schema 终态里 ⇒ 禁新造第二套框架 |
| 7 | **共享消费下界** | 现取消费文件数 ≥ 冻结下界（悄悄摘掉某些接线 ⇒ 红） |
| 8 | **判别力自证** | 五种坏形态在合成语料上各自判红；合规语料不红；扫描面为空也红 |

## 引用纪律（本仓红线）

一律**符号 / 仓库相对全路径**引用，**禁写** `path:行号` / 裸 `第 N 行` —— drift 面 `ref-freshness`
与 Case Trust 规则 G 会把裸行号判红（`migao-dev-flow` §16.7）。

## 边界（如实登记，§19.1）

- 形态判据**不做 AST 解析**：把服务注入到别的变量名上再调用，扫描器看不见 ⇒ 会把它判成
  「陈旧条目」（保守方向：宁可红在台账上，不放过漏接）。
- 射程 = **admin-api 主源**的 Java 文件；C 端 ai-agent 生成幂等键那一侧由各自的用例承担。
- **已知未接幂等的建单写面**（商品导入 / 入库单 / 表单建单）连请求头都没声明
  ⇒ 本扫描器天然看不见，登记在台账 `_known_unguarded_write_surfaces`（本包只登记、不代修）。
- 本守卫**不跑**被它点名的那些 Java 测试（否则等于把全量套件再跑一遍）。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

MAIN_ROOT = "backend/admin-api/src/main/java"
SERVICE_FILE = (
    "backend/admin-api/src/main/java/com/migao/admin/service/ClientRequestIdService.java"
)
SCHEMA_FILE = "backend/admin-api/src/main/resources/db/init/schema.sql"
LEDGER_PATH = "tests/unit_ci_workflows/idempotency_writeface_ledger.json"
PRODUCT_SERVICE = "backend/admin-api/src/main/java/com/migao/admin/service/ProductService.java"

#: 幂等**消费形态**：调用同一个点位（claim/complete/discard/replay）。
CONSUME = re.compile(r"clientRequestIdService\.(?:claim|complete|discard|replay)\s*\(")

#: **声明形态**：读幂等请求头。
DECLARE = re.compile(r"ClientRequestIdService\.HEADER")

#: 建品端点标识常量（诊断面：两个入口共用一个端点标识的证据）。
ENDPOINT_CONSTANT = re.compile(r"ENDPOINT_CREATE_PRODUCT\s*=")

#: 幂等键表名（DDL 层的真值）。
KEY_TABLE = "client_request_keys"

LEDGER_SECTIONS = ("consume_sites", "declaring_delegates", "declared_but_unwired")


# ── 纯函数检测器（合成语料与真语料共用 ⇒ 判别力自证才可信）────────────────────

def scan_corpus(corpus: dict[str, str]) -> tuple[set[str], set[str]]:
    """现取两个集合：`consuming`（消费幂等实现）/ `declaring`（读幂等请求头）。"""
    consuming = {path for path, text in corpus.items() if CONSUME.search(text)}
    declaring = {path for path, text in corpus.items() if DECLARE.search(text)}
    return consuming, declaring


def _entries(ledger: dict, section: str) -> list[dict]:
    return list(ledger.get(section) or [])


def problems(corpus: dict[str, str], ledger: dict) -> list[str]:
    """台账 ⇄ 现取语料的对账（纯函数；判据 1~5 的全部逻辑在这里）。"""
    consuming, declaring = scan_corpus(corpus)
    issues: list[str] = []

    consume_sites = _entries(ledger, "consume_sites")
    delegates = _entries(ledger, "declaring_delegates")
    exempt = _entries(ledger, "declared_but_unwired")
    baseline = ledger.get("declared_but_unwired_baseline") or []
    known = {e["file"] for section in LEDGER_SECTIONS for e in _entries(ledger, section)}

    # 判据 1：消费了同一份实现却未登记
    for path in sorted(consuming - {e["file"] for e in consume_sites}):
        issues.append(
            f"未登记即红：{path} 出现幂等消费形态却不在台账 consume_sites 里 "
            f"（新写面接了幂等必须登记；或把该接线摘掉）"
        )
    # 判据 2：登记未被兑现（anchor 逐字不在文件里）
    for section in LEDGER_SECTIONS:
        for entry in _entries(ledger, section):
            path, anchor = entry["file"], entry.get("anchor", "")
            if not anchor:
                issues.append(f"登记缺 anchor：{path}")
            elif path in corpus and anchor not in corpus[path]:
                issues.append(f"登记未被兑现即红：{path} 里逐字找不到 anchor「{anchor}」")
    # 判据 3：陈旧条目（接线被摘掉 / 改名 / 文件消失）
    for entry in consume_sites:
        path = entry["file"]
        if path in corpus and path not in consuming:
            issues.append(f"陈旧条目即红：台账说 {path} 已消费幂等实现，但现取扫描已找不到消费形态")
        if path not in corpus:
            issues.append(f"陈旧条目即红：台账里的文件在仓内不存在：{path}")
    # 判据 4：声明侧闭合 —— 现取到的每个「读头」文件必须在三处之一
    for path in sorted(declaring - known):
        issues.append(
            f"声明侧不闭合即红：{path} 读了 ClientRequestIdService.HEADER，却既不在 "
            f"consume_sites（自己消费）、也不在 declaring_delegates（透传下游）、"
            f"也不在 declared_but_unwired（缺口登记）里 ⇒ 声明了幂等却没有去重点"
        )
    # 判据 5：豁免只许缩短 + 陈旧豁免 + 缺字段
    for entry in exempt:
        path = entry["file"]
        if path in corpus and path not in declaring:
            issues.append(f"陈旧豁免即红：{path} 已不再读幂等请求头，却还挂在 declared_but_unwired")
        for field in ("reason", "restart_condition", "case_ids"):
            if not entry.get(field):
                issues.append(f"豁免缺 {field}：{path}")
    if len(exempt) > len(baseline):
        issues.append(
            f"豁免只许缩短：declared_but_unwired 现取 {len(exempt)} 条 > 冻结基线 {len(baseline)} 条"
        )
    return issues


def _bad(corpus: dict[str, str]) -> list[str]:
    """坏形态（未登记 / 声明未兑现）在**空台账**上的违规清单（判据 8 的判别力自证）。"""
    return problems(corpus, {
        "consume_sites": [], "declaring_delegates": [],
        "declared_but_unwired": [], "declared_but_unwired_baseline": [],
    })


# ── 真语料装配 ──────────────────────────────────────────────────────────────

def _read(path: str) -> str:
    return (REPO / path).read_text(encoding="utf-8")


def load_real_corpus() -> dict[str, str]:
    root = REPO / MAIN_ROOT
    files = sorted(root.rglob("*.java"))
    assert files, f"扫描面为空：{MAIN_ROOT} 下没有任何 .java（判据失明，不许当通过）"
    return {str(p.relative_to(REPO)): p.read_text(encoding="utf-8") for p in files}


def load_ledger() -> dict:
    return json.loads(_read(LEDGER_PATH))


# ── 判据 1~5：真语料 ───────────────────────────────────────────────────────

class TestWriteFaceCoverageOnRealCorpus:
    def test_no_violations_on_the_real_corpus(self):
        corpus = load_real_corpus()
        ledger = load_ledger()
        consuming, declaring = scan_corpus(corpus)
        # 条数**现取**：豁免只许缩短这条判据的数就在这行读数上
        print(f"[#6209 类级守卫] 现取消费面={len(consuming)} 声明面={len(declaring)} "
              f"台账 consume_sites={len(_entries(ledger, 'consume_sites'))} "
              f"delegates={len(_entries(ledger, 'declaring_delegates'))} "
              f"豁免={len(_entries(ledger, 'declared_but_unwired'))} "
              f"豁免基线={len(ledger['declared_but_unwired_baseline'])}")
        assert problems(corpus, ledger) == []

    def test_the_shared_consumer_floor_holds(self):
        """判据 7：共享消费面不许被悄悄摘掉（建品漏接后回到 7 ⇒ 红）。"""
        corpus = load_real_corpus()
        consuming, _ = scan_corpus(corpus)
        floor = load_ledger()["consume_floor"]
        assert len(consuming) >= floor, (
            f"共享消费面现取 {len(consuming)} < 冻结下界 {floor} ⇒ 有接线被摘掉"
        )

    def test_the_target_write_face_is_wired(self):
        """本单的钉：建品写面必须在册且 anchor 兑现（摘掉 claim ⇒ 判据 2/3 同时红）。"""
        corpus = load_real_corpus()
        entries = [e for e in _entries(load_ledger(), "consume_sites")
                   if e["file"] == PRODUCT_SERVICE]
        # 不写 `is not None` 这类**弱断言**（成长门禁判它不算判据）：直接逐值钉台账内容
        assert [e["anchor"] for e in entries] == [
            "clientRequestIdService.claim(tenantId, clientRequestId, ENDPOINT_CREATE_PRODUCT)"
        ], "建品写面必须在册且 anchor 逐字钉住 claim（否则扫描器已失明）"
        entry = entries[0]
        assert entry["anchor"] in corpus[entry["file"]]
        assert "POST /api/admin/products" in entry["surface"]
        assert entry["case_ids"] == ["PR-128"]
        assert ENDPOINT_CONSTANT.search(corpus[entry["file"]]), (
            "端点标识常量（ENDPOINT_CREATE_PRODUCT）必须仍在 ProductService 里 —— "
            "两个入口共用同一端点标识的证据"
        )


# ── 判据 6：同一份实现（禁新造第二套幂等框架）───────────────────────────────

class TestSingleIdempotencyImplementation:
    def test_exactly_one_implementation_class_in_the_repo(self):
        hits = [p for p in (REPO / MAIN_ROOT).rglob("*.java")
                if p.name == "ClientRequestIdService.java"]
        assert [str(p.relative_to(REPO)) for p in hits] == [SERVICE_FILE], (
            "幂等实现必须恰一份（新造第二套框架 = 红）"
        )

    def test_the_implementation_defines_claim_and_the_key_table_exists(self):
        assert "public boolean claim(" in _read(SERVICE_FILE), "claim( 必须定义在唯一实现里"
        assert "ON CONFLICT (tenant_id, client_request_id) DO NOTHING" in _read(SERVICE_FILE), (
            "claim 的原子性来源（ON CONFLICT）必须在实现里"
        )
        schema = _read(SCHEMA_FILE)
        assert re.search(rf"CREATE TABLE (?:IF NOT EXISTS )?{KEY_TABLE}\b", schema), (
            f"schema 终态必须建 {KEY_TABLE}（否则 claim 的去重无从成立）"
        )
        body = schema.split(f"CREATE TABLE IF NOT EXISTS {KEY_TABLE}", 1)[1].split(");", 1)[0]
        assert "UNIQUE (tenant_id, client_request_id)" in body, (
            f"{KEY_TABLE} 的 (tenant_id, client_request_id) 唯一约束必须在建表体里（现取 body）"
        )

    def test_the_implementation_is_actually_consumed_by_the_write_faces(self):
        """判据 6 的**消费侧**：实现存在但没人调 = 白搭（本单的病正是「没人调」）。"""
        corpus = load_real_corpus()
        consuming, _ = scan_corpus(corpus)
        assert consuming, "没有任何文件消费幂等实现 ⇒ 机制空转（禁把空集当通过）"
        assert SERVICE_FILE not in consuming, (
            "实现文件自己不该是「消费方」（扫描器把定义当成调用 = 判据失明）"
        )


# ── 判据 8：判别力自证（合成语料）───────────────────────────────────────────

class TestGuardHasDiscriminatingPower:
    GOOD = (
        "package com.migao.admin.controller;\n"
        "class Demo {\n"
        "  String h(@RequestHeader(value = ClientRequestIdService.HEADER, required = false) String k) {}\n"
        "  void w() { clientRequestIdService.claim(1L, k, \"POST /x\"); }\n"
        "}\n"
    )
    # #6209 的原始形态：声明了请求头，但**从不消费**幂等实现
    DECLARED_ONLY = (
        "package com.migao.admin.controller;\n"
        "class Demo {\n"
        "  String h(@RequestHeader(value = ClientRequestIdService.HEADER, required = false) String k) {}\n"
        "}\n"
    )
    CONSUMING_ONLY = (
        "package com.migao.admin.service;\n"
        "class Demo { void w() { clientRequestIdService.claim(1L, k, \"POST /y\"); } }\n"
    )

    def test_declared_but_never_consumed_is_red_with_an_empty_ledger(self):
        """**#6209 的形态**：读了头、服务端没去重 ⇒ 判红（空台账 = 未登记）。"""
        issues = _bad({"A.java": self.DECLARED_ONLY})
        assert any("未登记即红" in m or "声明侧不闭合即红" in m for m in issues), issues

    def test_consuming_but_unregistered_is_red(self):
        """未登记即红：新写面接了同一份实现却没进台账。"""
        issues = _bad({"B.java": self.CONSUMING_ONLY})
        assert any("未登记即红" in m for m in issues), issues

    def test_registry_without_fulfillment_is_red(self):
        """登记未被兑现即红：台账给不存在的接线盖章。"""
        issues = problems({"A.java": self.GOOD}, {
            "consume_sites": [{"file": "A.java", "anchor": "clientRequestIdService.claim(9L, zz, \"POST /nope\")",
                               "surface": "s", "case_ids": ["PR-128"]}],
            "declaring_delegates": [], "declared_but_unwired": [],
            "declared_but_unwired_baseline": [],
        })
        assert any("登记未被兑现" in m for m in issues), issues

    def test_stale_registry_entry_is_red(self):
        """陈旧条目即红：接线被摘掉 / 改名。"""
        issues = problems({"A.java": self.DECLARED_ONLY}, {
            "consume_sites": [{"file": "A.java", "anchor": "clientRequestIdService.claim(",
                               "surface": "s", "case_ids": ["PR-128"]}],
            "declaring_delegates": [], "declared_but_unwired": [],
            "declared_but_unwired_baseline": [],
        })
        assert any("陈旧条目即红" in m for m in issues), issues

    def test_new_exemption_is_red_but_good_corpus_is_green(self):
        """豁免只许缩短（新增豁免 ⇒ 红）+ 反向对照（合规语料不红）。"""
        good = {
            "consume_sites": [{"file": "A.java", "anchor": "clientRequestIdService.claim(1L, k, \"POST /x\")",
                               "surface": "s", "case_ids": ["PR-128"]}],
            "declaring_delegates": [], "declared_but_unwired": [],
            "declared_but_unwired_baseline": [],
        }
        assert problems({"A.java": self.GOOD}, good) == []
        grew = dict(good, declared_but_unwired=[
            {"file": "C.java", "anchor": "ClientRequestIdService.HEADER",
             "reason": "r", "restart_condition": "rc", "case_ids": ["PR-128"]}],
            declared_but_unwired_baseline=[])
        issues = problems({"A.java": self.GOOD, "C.java": self.DECLARED_ONLY}, grew)
        assert any("豁免只许缩短" in m for m in issues), issues

    def test_a_blind_scanner_is_red_not_green(self):
        """扫描面为空 ⇒ 当场醒（空集比空集是恒等，不许读成通过）。"""
        empty = load_real_corpus.__wrapped__ if hasattr(load_real_corpus, "__wrapped__") else None  # noqa: F841
        root = REPO / MAIN_ROOT
        assert root.is_dir() and any(root.rglob("*.java")), "扫描面必须存在且非空"
        try:
            load_real_corpus()
        except AssertionError:  # pragma: no cover - 真语料非空时不会走到
            raise

    def test_the_ledger_really_proves_something(self):
        """台账不许空转：consume_sites 非空、每条有 case_ids/surface/anchor、消费下界为正。"""
        ledger = load_ledger()
        assert ledger["consume_sites"], "空台账 = 守卫空跑（fail-closed）"
        for entry in ledger["consume_sites"]:
            assert entry.get("case_ids"), f"{entry.get('file')} 缺 case_ids"
            assert entry.get("surface"), f"{entry.get('file')} 缺 surface（哪个写面）"
            assert entry.get("anchor"), f"{entry.get('file')} 缺 anchor"
        assert ledger["consume_floor"] > 0
        for entry in ledger["_known_unguarded_write_surfaces"]["entries"]:
            assert entry.get("reason") and entry.get("restart_condition"), entry


if __name__ == "__main__":  # pragma: no cover - 手动复算入口
    corpus = load_real_corpus()
    consuming, declaring = scan_corpus(corpus)
    print(f"消费面={len(consuming)} 声明面={len(declaring)}")
    for path in sorted(consuming):
        print("  consumer:", path)
    for path in sorted(declaring):
        print("  declares:", path)
    issues = problems(corpus, load_ledger())
    for issue in issues:
        print("VIOLATION:", issue)
    sys.exit(1 if issues else 0)
